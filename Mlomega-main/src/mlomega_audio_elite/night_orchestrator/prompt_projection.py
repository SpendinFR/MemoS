"""Lossless projection of durable provenance into an LLM-facing payload.

Opaque database identifiers are essential to coverage, but hundreds of random
IDs carry no semantic information for a model.  Stage adapters can opt in to
this helper for known provenance fields.  The prompt receives a stable manifest
(count + digest), while the original payload remains untouched and is used by
the coverage ledger after the call.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Collection, Mapping

from .evidence_ref import content_digest


@dataclass(frozen=True)
class StagePromptProjection:
    payload: Mapping[str, Any]
    turn_id_by_ref: Mapping[str, str]
    applied: bool
    original_tokens: int
    projected_tokens: int
    purpose: str | None = None


_STAGE_PURPOSES = {
    "v14_people_identity": "people_identity",
    "v14_people_open_loops": "open_loops",
    "coordination_day_package": "coordination_day_package",
    "coordination_watch_bindings": "coordination_watch_bindings",
    "coordination_reconciliation": "coordination_reconciliation",
    "life_model_patch": "life_model_patch",
}


def _stage_purpose(stage_name: str) -> str | None:
    if stage_name.startswith("v14_interpersonal_state"):
        return "interpersonal"
    return _STAGE_PURPOSES.get(stage_name)


def project_stage_payload(
    *,
    stage_name: str,
    person_id: str,
    source_ref: str,
    payload: Mapping[str, Any],
    connection: Any | None = None,
) -> StagePromptProjection:
    """Apply a registered semantic projection once, before all window splits.

    Business modules continue to own their missions, schemas and writers.  The
    orchestrator owns cardinality: a registered stage receives the same exact
    turns and validated facts once, regardless of how many output
    responsibilities the executor later creates.
    """

    from ..utils import json_dumps
    from .stage_adapter import estimate_tokens_for_text

    original = dict(payload)
    original_tokens = estimate_tokens_for_text(json_dumps(original))
    purpose = _stage_purpose(stage_name)
    if not purpose:
        return StagePromptProjection(
            payload=original, turn_id_by_ref={}, applied=False,
            original_tokens=original_tokens, projected_tokens=original_tokens,
        )
    from ..brain2_shared_facts_v19 import (
        compact_stage_input,
        shared_facts_enabled,
    )
    if not shared_facts_enabled():
        return StagePromptProjection(
            payload=original, turn_id_by_ref={}, applied=False,
            original_tokens=original_tokens, projected_tokens=original_tokens,
            purpose=purpose,
        )

    owned = None
    con = connection
    if con is None:
        from ..db import connect
        owned = connect()
        con = owned
    try:
        projected = dict(original)
        turn_id_by_ref: dict[str, str] = {}
        if purpose in {"people_identity", "open_loops", "interpersonal"}:
            stage_input = compact_stage_input(
                con, source_ref, person_id=person_id, purpose=purpose
            )
            turn_id_by_ref = dict(stage_input.pop("_turn_id_map", {}))
            if purpose in {"people_identity", "open_loops"}:
                projected["conversation_data"] = stage_input
                projected["background"] = {
                    "projection": stage_input["projection_version"],
                    "included_in_conversation_data": True,
                }
            else:
                projected["conversation_payload"] = stage_input
                projected["background"] = {
                    "projection": stage_input["projection_version"],
                    "included_in_conversation_payload": True,
                }
        else:
            from .daily_fact_projection import (
                load_daily_shared_registry,
                project_day_evidence,
                project_forecast_evidence,
                project_life_patch_payload,
                project_reconciliation_payload,
            )
            if purpose == "coordination_day_package":
                raw = original.get("brainlive_day_evidence") or {}
                package_date = str(raw.get("package_date") or source_ref.rsplit(":", 1)[-1])[:10]
                registry = load_daily_shared_registry(
                    con, person_id=person_id, package_date=package_date
                )
                projected["brainlive_day_evidence"] = project_day_evidence(
                    raw, shared_registry=registry
                )
            elif purpose == "coordination_watch_bindings":
                projected["brain2_forecast_evidence"] = project_forecast_evidence(
                    original.get("brain2_forecast_evidence") or {}
                )
            elif purpose == "coordination_reconciliation":
                projected = project_reconciliation_payload(original)
            elif purpose == "life_model_patch":
                delta = original.get("new_delta_evidence") or {}
                package_date = str(
                    delta.get("period_start") or delta.get("as_of") or ""
                )[:10]
                registry = load_daily_shared_registry(
                    con, person_id=person_id, package_date=package_date
                ) if package_date else {}
                projected = project_life_patch_payload(
                    original, shared_registry=registry,
                    owner_person_id=person_id,
                )
                turn_id_by_ref = dict(projected.pop("_turn_id_map", {}))
        projected_tokens = estimate_tokens_for_text(json_dumps(projected))
        con.execute("""
            CREATE TABLE IF NOT EXISTS night_prompt_projections_v19(
                projection_id TEXT PRIMARY KEY,
                stage_name TEXT NOT NULL,
                person_id TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                purpose TEXT NOT NULL,
                original_tokens INTEGER NOT NULL,
                projected_tokens INTEGER NOT NULL,
                turn_ref_count INTEGER NOT NULL,
                original_digest TEXT NOT NULL,
                projected_digest TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        from ..utils import now_iso, stable_id
        projection_id = stable_id(
            "night-prompt-projection-v19", stage_name, person_id, source_ref,
            content_digest(original), content_digest(projected),
        )
        con.execute(
            """INSERT INTO night_prompt_projections_v19(
                   projection_id,stage_name,person_id,source_ref,purpose,
                   original_tokens,projected_tokens,turn_ref_count,
                   original_digest,projected_digest,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(projection_id) DO NOTHING""",
            (
                projection_id, stage_name, person_id, source_ref, purpose,
                original_tokens, projected_tokens, len(turn_id_by_ref),
                content_digest(original), content_digest(projected), now_iso(),
            ),
        )
        if owned is not None:
            con.commit()
        return StagePromptProjection(
            payload=projected,
            turn_id_by_ref=turn_id_by_ref,
            applied=True,
            original_tokens=original_tokens,
            projected_tokens=projected_tokens,
            purpose=purpose,
        )
    finally:
        if owned is not None:
            owned.close()


def restore_stage_output(value: Any, projection: StagePromptProjection) -> Any:
    if not projection.turn_id_by_ref:
        return value
    from ..brain2_shared_facts_v19 import expand_turn_refs
    return expand_turn_refs(value, projection.turn_id_by_ref)


def project_opaque_ref_lists(
    payload: Any,
    *,
    field_names: Collection[str],
) -> Any:
    """Return a deep prompt projection with selected ID lists compacted.

    This is deliberately opt-in: a stage must name fields that are provenance
    only.  Semantic lists are therefore never compacted by a global heuristic.
    """
    selected = frozenset(str(name) for name in field_names)

    def _project(value: Any) -> Any:
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, child in value.items():
                name = str(key)
                if name in selected and isinstance(child, (list, tuple)):
                    refs = [str(ref) for ref in child if ref]
                    out[f"{name}_manifest"] = {
                        "count": len(refs),
                        "digest": content_digest(refs),
                    }
                else:
                    out[name] = _project(child)
            return out
        if isinstance(value, (list, tuple)):
            return [_project(item) for item in value]
        return deepcopy(value)

    return _project(payload)
