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
    input_policy: str | None = None


_STAGE_PURPOSES = {
    "v13_subtopics": "subtopic_segmentation",
    "v13_latent_outcomes": "outcome_resolution",
    "v18_latent_outcomes": "outcome_resolution",
    "v13_autonomous_insights": "autonomous_candidates",
    "v18_autonomous_candidates": "autonomous_candidates",
    "v14_people_identity": "people_identity",
    "v14_people_open_loops": "open_loops",
    "v14_pattern_mirror": "pattern_mirror",
    "v14_proactive_interventions": "proactive_interventions",
    "life_model_bootstrap": "life_model_bootstrap",
    "coordination_day_package": "coordination_day_package",
    "coordination_watch_bindings": "coordination_watch_bindings",
    "coordination_reconciliation": "coordination_reconciliation",
    "life_model_patch": "life_model_patch",
}

# Every product call site using the generic hierarchical executor must declare
# what kind of input it owns.  This is deliberately central: adding a new
# ``v13_``/``v14_``/``v18_``/Brain2 stage without registering it must fail in
# tests and pre-production instead of silently replaying a raw bundle once per
# output responsibility.
_STAGE_INPUT_POLICIES = {
    **{name: "canonical_projection" for name in _STAGE_PURPOSES},
    "v14_interpersonal_state": "canonical_projection",
    "v14_clarification_inbox": "bounded_candidate_input",
    "silent_life_bundle": "bounded_sensor_bundle",
    "brainlive_live_ready": "deterministic_primary_with_bounded_fallback",
    "brain2_sensor_routing": "specialized_window_executor",
}

_STAGE_INPUT_POLICY_PREFIXES = (
    ("v14_periodic_mirror_", "canonical_daily_projection"),
    ("brain2_engine_fields:", "specialized_window_executor"),
    ("brain2_engine_batch:", "specialized_window_executor"),
    ("brain2_global_pack:", "specialized_window_executor"),
    ("brain2_episode_pack:", "specialized_window_executor"),
    ("brain2_episodes:", "specialized_window_executor"),
)

_PRODUCT_STAGE_PREFIXES = (
    "v13_", "v14_", "v18_", "life_model_", "brainlive_",
    "coordination_", "silent_", "brain2_",
)


def stage_input_policy(stage_name: str) -> str | None:
    exact = _STAGE_INPUT_POLICIES.get(stage_name)
    if exact:
        return exact
    for prefix, policy in _STAGE_INPUT_POLICY_PREFIXES:
        if stage_name.startswith(prefix):
            return policy
    return None


def _stage_purpose(stage_name: str) -> str | None:
    if stage_name.startswith("v14_interpersonal_state"):
        return "interpersonal"
    if stage_name.startswith("v14_periodic_mirror_"):
        return "periodic_mirror"
    return _STAGE_PURPOSES.get(stage_name)


def _nested_source_manifest(value: Any) -> dict[str, Any]:
    """Prove the durable raw input without copying it into an LLM prompt."""

    if isinstance(value, Mapping):
        return {
            "kind": "mapping",
            "digest": content_digest(value),
            "children": {
                str(key): _nested_source_manifest(child)
                for key, child in value.items()
            },
        }
    if isinstance(value, (list, tuple)):
        return {
            "kind": "collection", "count": len(value),
            "digest": content_digest(value),
        }
    return {"kind": "scalar", "digest": content_digest(value)}


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
    input_policy = stage_input_policy(stage_name)
    from ..brain2_shared_facts_v19 import shared_facts_enabled
    shared_enabled = shared_facts_enabled()
    if (
        shared_enabled
        and stage_name.startswith(_PRODUCT_STAGE_PREFIXES)
        and input_policy is None
    ):
        raise RuntimeError(
            f"unregistered product stage input policy: {stage_name}; "
            "declare a canonical projection, bounded input or specialized executor"
        )
    if not purpose:
        return StagePromptProjection(
            payload=original, turn_id_by_ref={}, applied=False,
            original_tokens=original_tokens, projected_tokens=original_tokens,
            input_policy=input_policy,
        )
    from ..brain2_shared_facts_v19 import (
        compact_stage_input,
    )
    if not shared_enabled:
        return StagePromptProjection(
            payload=original, turn_id_by_ref={}, applied=False,
            original_tokens=original_tokens, projected_tokens=original_tokens,
            purpose=purpose, input_policy=input_policy,
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
        if purpose in {
            "people_identity", "open_loops", "interpersonal",
            "autonomous_candidates", "pattern_mirror", "subtopic_segmentation",
            "outcome_resolution", "proactive_interventions",
        }:
            conversation_exists = bool(con.execute(
                "SELECT 1 FROM conversations WHERE conversation_id=?", (source_ref,)
            ).fetchone())
            stage_input: dict[str, Any] = {}
            if conversation_exists:
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
            elif purpose == "interpersonal":
                projected["conversation_payload"] = stage_input
                projected["background"] = {
                    "projection": stage_input["projection_version"],
                    "included_in_conversation_payload": True,
                }
            elif purpose in {"autonomous_candidates", "pattern_mirror"}:
                projected["bundle"] = stage_input
                projected["canonical_projection"] = {
                    "projection": stage_input["projection_version"],
                    "purpose": purpose,
                    "raw_bundle_replaced": True,
                }
            elif purpose == "subtopic_segmentation":
                projected["conversation"] = stage_input["conversation"]
                projected["turns"] = stage_input["turns"]
                projected["context_addenda"] = stage_input["context_addenda"]
                projected["canonical_projection"] = {
                    "projection": stage_input["projection_version"],
                    "purpose": purpose, "all_turns_present_once": True,
                }
            elif purpose == "outcome_resolution":
                conversation_key = (
                    "new_conversation" if "new_conversation" in projected
                    else "conversation"
                )
                turns_key = "new_turns" if "new_turns" in projected else "turns"
                projected[conversation_key] = stage_input["conversation"]
                projected[turns_key] = stage_input["turns"]
                if "context_addenda" in projected:
                    projected["context_addenda"] = stage_input["context_addenda"]
                projected["canonical_projection"] = {
                    "projection": stage_input["projection_version"],
                    "purpose": purpose, "pending_items_preserved": True,
                    "all_turns_present_once": True,
                }
            elif purpose == "proactive_interventions":
                raw_context = original.get("context")
                raw_context = raw_context if isinstance(raw_context, Mapping) else {}
                # V14.7 chooses among upstream candidates.  Re-reading raw turns,
                # episodes and context addenda here both duplicates cognition and
                # lets a one-minute exchange become unsupported psychology.
                candidate_keys = (
                    "interpersonal_aftereffects", "interpersonal_loops",
                    "interpersonal_suggestions", "active_open_loops",
                    "solution_candidates", "pattern_cards",
                    "trajectory_forecasts", "forecast_watch_queue",
                    "recent_predictions", "recent_prediction_results",
                    "recent_state", "existing_open_queue", "policy",
                )
                projected_context = {
                    key: raw_context.get(key)
                    for key in candidate_keys if key in raw_context
                }
                if stage_input:
                    projected_context["current_conversation"] = {
                        "conversation": stage_input["conversation"],
                        "outline": stage_input["conversation_outline"],
                        "candidate_facts": stage_input["facts"],
                        "capabilities": stage_input["capabilities"],
                    }
                projected["context"] = projected_context
                projected["canonical_projection"] = {
                    "projection": (
                        stage_input.get("projection_version") or "candidate-input-v1"
                    ),
                    "purpose": purpose,
                    "raw_turns_reanalysis": False,
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
            elif purpose == "life_model_bootstrap":
                raw = original.get("raw_evidence") or {}
                package_date = str(
                    raw.get("period_start") or raw.get("period_end") or source_ref
                )[:10]
                registry = load_daily_shared_registry(
                    con, person_id=person_id, package_date=package_date
                )
                projected["raw_evidence"] = {
                    "projection_version": "e64i-life-bootstrap-shared-facts-v1",
                    "person_id": person_id,
                    "period_start": raw.get("period_start"),
                    "period_end": raw.get("period_end"),
                    "shared_registry": registry,
                    "raw_source_manifest": _nested_source_manifest(raw),
                }
            elif purpose == "periodic_mirror":
                raw = original.get("bundle") or {}
                package_date = str(
                    raw.get("period_end") or raw.get("period_start") or source_ref
                )[:10]
                registry = load_daily_shared_registry(
                    con, person_id=person_id, package_date=package_date
                )
                projected["bundle"] = {
                    "projection_version": "e64i-periodic-mirror-shared-facts-v1",
                    "person_id": person_id,
                    "period": raw.get("period"),
                    "period_start": raw.get("period_start"),
                    "period_end": raw.get("period_end"),
                    "shared_registry": registry,
                    "raw_source_manifest": _nested_source_manifest(raw),
                }
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
            purpose=purpose, input_policy=input_policy,
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
