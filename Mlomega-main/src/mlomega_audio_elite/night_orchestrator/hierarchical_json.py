"""Bounded hierarchical JSON calls for day/conversation-wide night stages.

The business stage still owns its system prompt, payload and output schema. This
module only turns unbounded collections into token-aware durable windows, then
reduces validated partial outputs through bounded merge levels. Every leaf ref
survives transitively to the final envelope; no writer sees partial JSON.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass
from contextlib import nullcontext
import math
import os
from typing import Any, Mapping, Sequence

from ..config import get_settings
from ..db import connect
from ..utils import json_dumps, json_loads, now_iso, sha256_bytes, stable_id
from .coverage import (
    build_coverage_report,
    covered_refs_from_outputs_table,
    persist_coverage,
)
from .executor import ModelBudget, StageScope, run_windows
from .ollama_window_llm import OllamaWindowLLM
from .stage_adapter import estimate_tokens_for_text
from .window_planner import PlanUnit, plan_windows


@dataclass(frozen=True)
class _Leaf:
    ref_id: str
    path: tuple[str, ...]
    value: Any
    digest: str


def _digest(value: Any) -> str:
    return sha256_bytes(json_dumps(value).encode("utf-8"))


def _extract_lists(value: Any, path: tuple[str, ...] = ()) -> tuple[Any, list[_Leaf]]:
    """Replace list contents by manifests and return every item as a leaf."""
    leaves: list[_Leaf] = []
    if isinstance(value, Mapping):
        base: dict[str, Any] = {}
        for key, child in value.items():
            if not path and str(key) in {
                "schema", "rules", "strict_rules", "hard_rules", "contract",
                "update_rules", "required_behavior", "horizons", "policy",
            }:
                base[str(key)] = child
                continue
            # SQLite projections commonly persist large evidence collections as
            # ``*_json`` text. Treating those strings as indivisible shared
            # context repeated 100k+ tokens in every reconciliation window.
            # Decode only explicitly JSON-named fields and preserve the exact
            # parsed values as ordinary evidence leaves.
            parsed_child = child
            if isinstance(child, str) and str(key).endswith("_json"):
                decoded = json_loads(child, None)
                if isinstance(decoded, (list, dict)):
                    parsed_child = decoded
            projected, child_leaves = _extract_lists(
                parsed_child, path + (str(key),)
            )
            base[str(key)] = projected
            leaves.extend(child_leaves)
        return base, leaves
    if isinstance(value, list):
        for index, item in enumerate(value):
            digest = _digest(item)
            leaves.append(_Leaf(
                ref_id=stable_id("nightleaf", *path, index, digest),
                path=path,
                value=item,
                digest=digest,
            ))
        return {"item_count": len(value), "items_supplied_by_window": True}, leaves
    return value, leaves


def build_evidence_leaf_index(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve opaque night leaves back to the exact input rows they represent.

    Business validators still own table and owner checks.  The digest alias is
    accepted only when it is the exact, unique digest of a leaf in this payload;
    this recovers a Qwen copy error observed with adjacent ``evidence_ref`` and
    ``digest`` fields without trusting an invented identifier.
    """
    _, leaves = _extract_lists(dict(payload))
    index: dict[str, dict[str, Any]] = {}
    digest_entries: dict[str, dict[str, Any] | None] = {}
    for leaf in leaves:
        entry = {
            "ref_id": leaf.ref_id,
            "path": tuple(leaf.path),
            "value": leaf.value,
            "digest": leaf.digest,
        }
        index[leaf.ref_id] = entry
        digest_key = f"nightleaf_{leaf.digest}"
        digest_entries[digest_key] = (
            None if digest_key in digest_entries else entry
        )
    index.update({key: entry for key, entry in digest_entries.items() if entry})
    return index


def _window_payload(base: Any, leaves: Sequence[_Leaf]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for leaf in leaves:
        key = ".".join(leaf.path) or "$"
        grouped.setdefault(key, []).append({
            "evidence_ref": leaf.ref_id,
            "digest": leaf.digest,
            "value": leaf.value,
        })
    return {
        "shared_context": base,
        "window_collections": grouped,
        "window_evidence_refs": [leaf.ref_id for leaf in leaves],
    }


def _validate_schema_shape(value: Any, schema: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and set(schema).issubset(value)


def _validate_top_level_cardinality(
    value: Any, schema: Mapping[str, Any], guard: Mapping[str, Any]
) -> bool:
    if not isinstance(value, Mapping):
        return False
    maximum = int(guard.get("max_items_per_top_level_list") or 0)
    epistemic_maximum = int(
        guard.get("max_items_per_epistemic_list") or maximum
    )
    for key, template in schema.items():
        if isinstance(template, list):
            items = value.get(key)
            # Missing/counter evidence is not business output cardinality.  Using
            # the small business-list cap here rejected an otherwise valid People
            # Identity response solely because it honestly listed 14 distinct
            # missing inputs.  Keep this bounded, but give epistemic disclosures
            # their own budget-derived ceiling.
            field_maximum = (
                epistemic_maximum
                if key in {"missing_context", "evidence", "counter_evidence"}
                else maximum
            )
            if not isinstance(items, list) or len(items) > field_maximum:
                return False
    return True


def _lossless_array_union(
    values: Sequence[Mapping[str, Any]], schema: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Union disjoint window projections without asking an LLM to copy JSON.

    This is intentionally narrow and opt-in: every top-level field must be an
    array, a numeric aggregate or a presentation-only string. Arrays preserve
    first-seen order and remove exact canonical duplicates only; semantic
    near-duplicates and contradictions remain. Numeric aggregates use the finite
    arithmetic mean. Distinct strings are retained verbatim in encounter order,
    separated by newlines; no model-authored summary is discarded.
    """
    merged: dict[str, Any] = {}
    for key, template in schema.items():
        present = [value.get(key) for value in values if key in value]
        if isinstance(template, list):
            if any(not isinstance(item, list) for item in present):
                return None
            seen: set[str] = set()
            combined: list[Any] = []
            for items in present:
                for item in items:
                    digest = _digest(item)
                    if digest not in seen:
                        seen.add(digest)
                        combined.append(item)
            merged[key] = combined
            continue
        if isinstance(template, (int, float)) and not isinstance(template, bool):
            numbers = [
                float(item) for item in present
                if isinstance(item, (int, float)) and not isinstance(item, bool)
                and math.isfinite(float(item))
            ]
            if len(numbers) != len(present) or not numbers:
                return None
            merged[key] = sum(numbers) / len(numbers)
            continue
        if isinstance(template, str):
            if any(not isinstance(item, str) for item in present):
                return None
            distinct = list(dict.fromkeys(item for item in present if item))
            merged[key] = "\n".join(distinct)
            continue
        return None
    return merged


def _output_cardinality_guard(
    schema: Mapping[str, Any], *, output_budget: int,
    requested_max_items: int | None = None,
) -> dict[str, Any]:
    """Describe a bounded *derived* projection without dropping source proof.

    The raw evidence remains in its source tables and coverage manifest.  This
    guard prevents a model from turning a small operational schema into an
    unbounded catalogue that is guaranteed to hit the response limit.
    """
    top_level_lists = max(1, sum(isinstance(value, list) for value in schema.values()))
    max_items = max(4, min(16, int(output_budget) // (180 * top_level_lists)))
    if requested_max_items is not None:
        max_items = max(0, min(max_items, int(requested_max_items)))
    max_epistemic_items = max(
        max_items,
        min(24, max(4, int(output_budget) // 256)),
    )
    return {
        "max_response_tokens": max(256, int(output_budget) - 384),
        "max_items_per_top_level_list": max_items,
        "max_items_per_epistemic_list": max_epistemic_items,
        "max_values_per_nested_list": 8,
        "max_chars_per_free_text_field": 600,
        "selection_rule": (
            "Keep the most distinct, evidence-backed and operationally useful "
            "items. Merge real duplicates; do not omit contradictions. This "
            "bounds only the derived projection: source evidence remains durable."
        ),
    }


def _run_hierarchical_json_single_schema(
    *,
    stage_name: str,
    person_id: str,
    package_date: str,
    source_ref: str,
    system: str,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    timeout: float,
    client: Any | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
    connection: Any | None = None,
    lossless_array_merge: bool = False,
    prefer_lossless_input_windows: bool = False,
) -> dict[str, Any]:
    """Return one complete schema object or raise without applying a partial."""
    # Legacy stages often embed the exact output schema in their payload. It is
    # control metadata, not evidence: the renderer includes it in the business
    # prompt and the provider also receives it as an executable JSON grammar.
    # Drop only that identical transport duplicate.
    payload = dict(payload)
    if payload.get("schema") == schema:
        payload.pop("schema", None)
    import os as _os
    cfg = get_settings()
    context_window = int(context_window or cfg.ollama_context_poststop)
    if output_budget is None:
        try:
            output_budget = max(256, int(_os.environ.get(
                "MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"
            )))
        except ValueError:
            output_budget = 4096
    # PRO cloud (DeepSeek): the hierarchical v14 stages (clarification inbox, etc.)
    # were budgeting against the LOCAL P1 window (~24k) and a 4096 output cap, so a
    # legitimate clarification output truncated (finish=length) and quarantined
    # (Gate B 183352 v14_clarification_inbox:level1). DeepSeek handles 128k / 8k
    # output; mirror the engine fan-out's cloud budget so these stages get the same
    # room. The local path (no flag) keeps ollama_context_poststop / 4096 unchanged.
    if _os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        try:
            context_window = max(context_window, int(
                _os.environ.get("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "57344")))
        except ValueError:
            context_window = max(context_window, 57344)
        try:
            output_budget = max(int(output_budget), int(
                _os.environ.get("MLOMEGA_CLOUD_MAX_OUTPUT_TOKENS", "8192")))
        except ValueError:
            output_budget = max(int(output_budget), 8192)
    budget = ModelBudget(
        context_window=context_window,
        output_reserve=int(output_budget),
        safety_margin=768,
    )
    cardinality_guard = _output_cardinality_guard(
        schema, output_budget=int(output_budget),
        requested_max_items=(
            int((payload.get("output_cardinality") or {}).get("max_items_per_list"))
            if isinstance(payload.get("output_cardinality"), Mapping)
            and (payload.get("output_cardinality") or {}).get("max_items_per_list") is not None
            else None
        ),
    )
    llm = OllamaWindowLLM(
        system=system, client=client, schema_hint=dict(schema), timeout=timeout
    )
    model = str(getattr(llm, "model", "ollama-json"))
    digest = _digest(payload)
    complete_leaf = _Leaf(
        stable_id("nightleaf", stage_name, digest), ("$",), dict(payload), digest
    )
    # Probe the exact level-0 envelope, not a smaller approximation.  The
    # evidence-ref/digest/window wrapper is material on near-limit payloads: an
    # earlier approximation admitted a 20,190-token clarification request into
    # a 19,712-token budget and then quarantined it before the first call.
    complete_probe = json_dumps({
        "mission": payload.get("mission"),
        "hierarchical_instruction": (
            "Analyse uniquement cette fenÃªtre de preuves. Produis le "
            "schÃ©ma mÃ©tier complet pour ce sous-ensemble; n'invente "
            "aucune preuve absente."
        ),
        "level": 0,
        "input": _window_payload({"complete_input_window": True}, [complete_leaf]),
        "schema": schema,
        "output_cardinality_guard": cardinality_guard,
    })
    # ``run_windows`` budgets the complete request mapping, including the
    # separately supplied schema hint. Mirror that calculation here; measuring
    # only the prompt string still under-counted the clarification contract.
    complete_request = {"prompt": complete_probe, "schema_hint": dict(schema)}
    if prefer_lossless_input_windows:
        # Some broad contracts contain only append-only collections plus a
        # numeric aggregate.  Splitting their OUTPUT schema first makes every
        # responsibility reread the same transcript.  Extract evidence leaves
        # once instead, ask for the complete contract per evidence window and
        # merge those disjoint projections deterministically below.  Keeping
        # leaves even when the complete request would fit also gives the length
        # recovery path something real to subdivide.
        base, leaves = _extract_lists(dict(payload))
    elif estimate_tokens_for_text(json_dumps(complete_request)) <= budget.max_input_tokens:
        leaves = [complete_leaf]
        base = {"complete_input_window": True}
    else:
        base, leaves = _extract_lists(dict(payload))
    if not leaves:
        # One bounded object with no splittable collection. It still goes through
        # the executor so truncation/JSON/retry/checkpoint semantics stay common.
        digest = _digest(payload)
        leaves = [_Leaf(stable_id("nightleaf", stage_name, digest), ("$",), dict(payload), digest)]
        base = {"single_object_window": True}

    with (nullcontext(connection) if connection is not None else connect()) as con:
        level = 0
        current = leaves
        original_refs = [leaf.ref_id for leaf in leaves]
        final_output: dict[str, Any] | None = None
        final_parent_refs: list[str] = []
        while True:
            by_id = {leaf.ref_id: leaf for leaf in current}
            units = [
                PlanUnit(
                    ref_id=leaf.ref_id,
                    tokens=estimate_tokens_for_text(json_dumps({
                        "path": leaf.path, "value": leaf.value,
                    })) + 24,
                    content_digest=leaf.digest,
                )
                for leaf in current
            ]
            scoped_stage = f"{stage_name}:level{level}"

            def render(window_units) -> dict[str, Any]:
                selected = [by_id[unit.ref_id] for unit in window_units]
                if level == 0:
                    body = _window_payload(base, selected)
                    instruction = (
                        "Analyse uniquement cette fenêtre de preuves. Produis le "
                        "schéma métier complet pour ce sous-ensemble; n'invente "
                        "aucune preuve absente."
                    )
                else:
                    body = {
                        "partial_outputs": [leaf.value for leaf in selected],
                        "partial_refs": [leaf.ref_id for leaf in selected],
                    }
                    instruction = (
                        "Consolide ces sorties partielles du même moteur. Préserve "
                        "contradictions, contre-preuves et éléments distincts; "
                        "déduplique seulement les objets réellement identiques."
                    )
                return {
                    "prompt": json_dumps({
                        "mission": payload.get("mission"),
                        "hierarchical_instruction": instruction,
                        "level": level,
                        "input": body,
                        "schema": schema,
                        "output_cardinality_guard": cardinality_guard,
                    }),
                    "schema_hint": dict(schema),
                }

            def envelope(value: Any, primary) -> dict[str, Any]:
                parent_refs: list[str] = []
                for unit in primary:
                    leaf = by_id[unit.ref_id]
                    if level == 0:
                        parent_refs.append(leaf.ref_id)
                    elif isinstance(leaf.value, Mapping):
                        parent_refs.extend(leaf.value.get("_parent_refs", []))
                return {
                    "evidence_refs": list(dict.fromkeys(parent_refs)),
                    "result": value,
                }

            empty = json_dumps({
                "mission": payload.get("mission"),
                "hierarchical_instruction": "bounded window",
                "level": level,
                "input": {},
                "schema": schema,
                "output_cardinality_guard": cardinality_guard,
            })
            overhead_tokens = estimate_tokens_for_text(empty)
            # Use the planner's validated 40-50-unit operating point.  The old
            # value of 10 created dozens of tiny calls even when the token
            # budget could safely carry far more evidence.  Token accounting
            # remains the hard limit, so this changes batching only, never
            # evidence coverage.
            target_units = 45 if level == 0 else 4
            expected_planned_count = len(plan_windows(
                units,
                stage_name=scoped_stage,
                max_input_tokens=max(1, budget.max_input_tokens - overhead_tokens),
                target_units=target_units,
                overlap=0,
            ))
            parallel_workers = 1
            connection_factory = None
            if (
                connection is None
                and _os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
                in {"1", "true", "yes", "on"}
                and expected_planned_count > 1
            ):
                try:
                    parallel_workers = max(
                        1,
                        min(
                            12,
                            int(_os.environ.get("MLOMEGA_PRO_WINDOW_WORKERS", "8")),
                        ),
                    )
                except ValueError:
                    parallel_workers = 8
                connection_factory = connect
            if _os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
                "1", "true", "yes", "on",
            }:
                from ..cloud_providers_v19 import cloud_engine_stage

                stage_context = cloud_engine_stage(scoped_stage)
            else:
                stage_context = nullcontext()
            with stage_context:
                stage = run_windows(
                    units,
                    con=con,
                    scope=StageScope(
                        person_id=person_id,
                        package_date=package_date,
                        stage_name=scoped_stage,
                        adapter_version="e64f-hierarchical-json-v4-dense-windows",
                        prompt_version=f"{stage_name}:v3-dense-cardinality",
                        model=model,
                    ),
                    llm=llm,
                    budget=budget,
                    render=render,
                    validate=lambda value: (
                        _validate_schema_shape(value, schema)
                        and _validate_top_level_cardinality(
                            value, schema, cardinality_guard
                        )
                    ),
                    decorate_output=envelope,
                    target_units=target_units,
                    overlap=0,
                    prompt_overhead_tokens=overhead_tokens,
                    # Leaf evidence can be divided safely. A merge already contains
                    # partial full-schema outputs; length there means split output
                    # responsibilities, which the calling adapter owns.
                    subdivide_on_length=(level == 0),
                    parallel_workers=parallel_workers,
                    connection_factory=connection_factory,
                )
            if not stage.all_completed:
                raise RuntimeError(
                    f"{scoped_stage} incomplete: "
                    f"states={[window.state for window in stage.windows]}"
                )
            outputs = [out for out in stage.outputs if isinstance(out, Mapping)]
            if not outputs:
                raise RuntimeError(f"{scoped_stage} completed without output")
            if lossless_array_merge and len(outputs) > 1:
                partials = [
                    out.get("result") for out in outputs
                    if isinstance(out.get("result"), Mapping)
                ]
                merged = _lossless_array_union(partials, schema)
                if merged is None or len(partials) != len(outputs):
                    raise RuntimeError(
                        f"{scoped_stage} is not eligible for lossless array merge"
                    )
                final_output = merged
                final_parent_refs = list(dict.fromkeys(
                    str(ref)
                    for out in outputs
                    for ref in out.get("evidence_refs", [])
                ))
                break
            if level > 0 and len(outputs) > expected_planned_count:
                # The planner proved this merge level needed fewer calls. Extra
                # outputs therefore came from response-length subdivision, not
                # input size. Repeating full-schema fan-in is wasteful; let the
                # stage adapter split output responsibilities immediately.
                raise RuntimeError(
                    f"{scoped_stage} merge subdivision requires schema split: "
                    f"planned={expected_planned_count} outputs={len(outputs)}"
                )
            if len(outputs) == 1:
                result = outputs[0].get("result")
                if not _validate_schema_shape(result, schema):
                    raise RuntimeError(f"{scoped_stage} final output violates schema")
                final_output = dict(result)
                final_parent_refs = [str(ref) for ref in outputs[0].get("evidence_refs", [])]
                break
            if level > 0 and len(outputs) >= len(current):
                # Subdivision produced one full-schema output per merge input:
                # another level would repeat the same fan-in forever.  Fail fast
                # so a stage adapter can split OUTPUT responsibilities/schemas,
                # rather than burning up to twelve identical merge levels.
                raise RuntimeError(
                    f"{scoped_stage} merge made no progress: "
                    f"inputs={len(current)} outputs={len(outputs)}"
                )
            current = [
                _Leaf(
                    ref_id=stable_id("nightmerge", scoped_stage, index, _digest(out)),
                    path=("partial_outputs",),
                    value={
                        "output": out.get("result"),
                        "_parent_refs": out.get("evidence_refs", []),
                    },
                    digest=_digest(out),
                )
                for index, out in enumerate(outputs)
            ]
            level += 1
            if level > 12:
                raise RuntimeError(f"{stage_name} exceeded hierarchical merge depth")

        report = build_coverage_report(
            stage_name=stage_name,
            expected_ids=original_refs,
            covered_refs=final_parent_refs,
        )
        persist_coverage(
            con, person_id=person_id, package_date=package_date,
            source_ref=source_ref, report=report,
        )
        con.commit()
        if not report.ok:
            raise RuntimeError(
                f"{stage_name} final coverage incomplete: missing={len(report.missing)}"
            )
    assert final_output is not None
    return final_output


_STAGE_RESPONSIBILITY_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "v14_interpersonal_state": (
        (
            "other_person_state_snapshots", "emotional_couplings",
            "micro_interaction_impacts", "social_aftereffects",
        ),
        (
            "relationship_state_models", "interpersonal_loops",
            "intervention_suggestions", "person_model_summaries",
            "missing_context", "confidence",
        ),
    ),
    "life_model_patch": (
        ("operations",),
        (
            "patch_intent", "strata_guidance", "missing_evidence_for_magic",
            "do_not_update_without", "summary_for_brainlive",
        ),
    ),
}


def _schema_responsibility_parts(
    schema: Mapping[str, Any], *, stage_name: str | None = None,
    max_schema_chars: int = 1400,
    max_list_fields: int = 2,
) -> list[dict[str, Any]]:
    """Partition a broad top-level contract into disjoint responsibilities.

    Every part receives the same evidence.  Only output ownership is split, so
    no event, prompt rule or business capability is removed.  The partition is
    deterministic and preserves the original key order.
    """
    registered = _STAGE_RESPONSIBILITY_KEYS.get(str(stage_name or ""))
    if registered:
        flattened = [key for part in registered for key in part]
        if set(flattened) != set(schema) or len(flattened) != len(schema):
            raise RuntimeError(
                f"{stage_name} responsibility registry does not cover schema exactly"
            )
        return [{key: schema[key] for key in keys} for keys in registered]

    parts: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    current_family: str | None = None
    current_list_fields = 0

    def family(template: Any) -> str:
        # Array/numeric contracts can be merged deterministically.  Never mix
        # them with a semantic object: one such object disabled the lossless
        # union for an otherwise array-only responsibility and made live-ready
        # recursively regenerate the same large JSON during fan-in.
        if isinstance(template, list) or (
            isinstance(template, (int, float)) and not isinstance(template, bool)
        ):
            return "lossless"
        if isinstance(template, Mapping):
            return "object"
        return "scalar"

    for key, template in schema.items():
        item_family = family(template)
        candidate = {**current, str(key): template}
        should_flush = bool(current) and (
            len(json_dumps(candidate)) > max_schema_chars
            or current_family != item_family
            or (item_family == "lossless" and current_list_fields >= max_list_fields)
            or item_family == "object"
        )
        if should_flush:
            parts.append(current)
            current = {str(key): template}
            current_family = item_family
            current_list_fields = 1 if item_family == "lossless" else 0
        else:
            current = candidate
            current_family = item_family
            if item_family == "lossless":
                current_list_fields += 1
    if current:
        parts.append(current)
    return parts


def _requires_output_responsibility_split(
    schema: Mapping[str, Any], *, stage_name: str | None = None
) -> bool:
    """Identify contracts known to be too broad for one bounded JSON answer.

    Real Qwen 9B runs showed the recurring failure boundary around the V14
    Interpersonal and V15 Life-Model contracts (roughly 3k schema characters,
    9+ independent top-level collections).  Small schemas remain on the normal
    single-contract path, avoiding unnecessary duplicate evidence reads.
    """
    registered = _STAGE_RESPONSIBILITY_KEYS.get(str(stage_name or ""))
    if registered:
        registered_keys = {key for part in registered for key in part}
        if registered_keys == set(schema):
            return True
    list_fields = sum(isinstance(value, list) for value in schema.values())
    return len(json_dumps(schema)) >= 2000 or list_fields >= 8


def _supports_lossless_window_union(schema: Mapping[str, Any]) -> bool:
    return bool(schema) and all(
        isinstance(value, list)
        or (isinstance(value, (int, float)) and not isinstance(value, bool))
        for value in schema.values()
    )


# These stages make their semantic judgement independently inside each evidence
# window. Their fan-in contains only candidate arrays, confidence aggregates and
# a presentation summary unused by canonical writers. Re-asking the LLM to copy
# that material caused repeatable length/contract failures on the real Gate B DB.
# The central merge preserves every distinct candidate and summary verbatim.
_LOSSLESS_PROJECTION_STAGES = {
    "v13_autonomous_insights",
    "v18_autonomous_candidates",
}


def run_hierarchical_json(
    *,
    stage_name: str,
    person_id: str,
    package_date: str,
    source_ref: str,
    system: str,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    timeout: float,
    client: Any | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
    connection: Any | None = None,
    lossless_array_merge: bool = False,
) -> dict[str, Any]:
    """Run a bounded JSON stage, splitting broad OUTPUT contracts centrally.

    This is the shared prevention layer: large schemas are separated before an
    inevitably truncated full-schema call.  Each responsibility sees the full
    payload, produces disjoint keys, and is checkpointed independently.  The
    final merge is a plain key union, therefore it cannot drop or reinterpret a
    result from another responsibility.
    """
    schema = dict(schema)
    lossless_array_merge = bool(
        lossless_array_merge or stage_name in _LOSSLESS_PROJECTION_STAGES
    )
    from .prompt_projection import project_stage_payload, restore_stage_output
    projection = project_stage_payload(
        stage_name=stage_name,
        person_id=person_id,
        source_ref=source_ref,
        payload=payload,
        connection=connection,
    )
    payload = projection.payload
    if (
        stage_name == "v14_interpersonal_state"
        and _supports_lossless_window_union(schema)
    ):
        # The V14.6 contract is nine append-only collections plus confidence.
        # Its former two output responsibilities each reread the complete
        # conversation, multiplying both prompt cost and latency.  A single
        # evidence pass is lossless here: every window returns the full schema,
        # arrays are exact-unioned and confidence is averaged by the shared
        # deterministic reducer.  Raw evidence coverage remains authoritative.
        result = _run_hierarchical_json_single_schema(
            stage_name=stage_name,
            person_id=person_id,
            package_date=package_date,
            source_ref=source_ref,
            system=system,
            payload=payload,
            schema=schema,
            timeout=timeout,
            client=client,
            context_window=context_window,
            output_budget=output_budget,
            connection=connection,
            lossless_array_merge=True,
            prefer_lossless_input_windows=True,
        )
        return restore_stage_output(result, projection)
    if not _requires_output_responsibility_split(schema, stage_name=stage_name):
        result = _run_hierarchical_json_single_schema(
            stage_name=stage_name,
            person_id=person_id,
            package_date=package_date,
            source_ref=source_ref,
            system=system,
            payload=payload,
            schema=schema,
            timeout=timeout,
            client=client,
            context_window=context_window,
            output_budget=output_budget,
            connection=connection,
            lossless_array_merge=lossless_array_merge,
        )
        return restore_stage_output(result, projection)

    parts = _schema_responsibility_parts(schema, stage_name=stage_name)
    if len(parts) <= 1:
        result = _run_hierarchical_json_single_schema(
            stage_name=stage_name,
            person_id=person_id,
            package_date=package_date,
            source_ref=source_ref,
            system=system,
            payload=payload,
            schema=schema,
            timeout=timeout,
            client=client,
            context_window=context_window,
            output_budget=output_budget,
            connection=connection,
            lossless_array_merge=lossless_array_merge,
        )
        return restore_stage_output(result, projection)

    merged: dict[str, Any] = {}
    covered_responsibilities: list[str] = []
    expected_responsibilities: list[str] = []

    def _run_responsibility(index: int, part: Mapping[str, Any]) -> tuple[
        int, dict[str, Any], str
    ]:
        keys = tuple(part)
        responsibility_ref = stable_id(
            "nightresponsibility", stage_name, index, *keys
        )
        part_payload = dict(payload)
        if part_payload.get("schema") == schema:
            # The executable schema is already supplied out-of-band.  Never
            # leave the original full contract inside a focused prompt.
            part_payload.pop("schema", None)
        key_tag = stable_id("responsibility", *keys)[-12:]
        part_result = _run_hierarchical_json_single_schema(
            stage_name=f"{stage_name}:responsibility_{index}_{key_tag}",
            person_id=person_id,
            package_date=package_date,
            source_ref=f"{source_ref}:responsibility:{index}",
            system=(
                system
                + "\nResponsabilit\u00e9 de sortie cibl\u00e9e: produis uniquement les "
                  "cl\u00e9s du sch\u00e9ma fourni; les autres responsabilit\u00e9s sont "
                  "trait\u00e9es s\u00e9par\u00e9ment sur les m\u00eames preuves."
            ),
            payload=part_payload,
            schema=part,
            timeout=timeout,
            client=client,
            context_window=context_window,
            output_budget=output_budget,
            connection=connection,
            lossless_array_merge=(
                lossless_array_merge or _supports_lossless_window_union(part)
            ),
        )
        return index, part_result, responsibility_ref

    indexed_parts = list(enumerate(parts))
    part_results: dict[int, tuple[dict[str, Any], str]] = {}
    pro_parallel = (
        connection is None
        and len(indexed_parts) > 1
        and os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if pro_parallel:
        try:
            responsibility_workers = max(
                1,
                min(
                    8,
                    int(os.environ.get(
                        "MLOMEGA_PRO_RESPONSIBILITY_WORKERS", "4"
                    )),
                ),
            )
        except ValueError:
            responsibility_workers = 4
        with ThreadPoolExecutor(
            max_workers=min(responsibility_workers, len(indexed_parts)),
            thread_name_prefix="mlomega-pro-responsibility",
        ) as pool:
            futures = {
                pool.submit(copy_context().run, _run_responsibility, index, part): index
                for index, part in indexed_parts
            }
            for future in as_completed(futures):
                index, part_result, responsibility_ref = future.result()
                part_results[index] = (part_result, responsibility_ref)
    else:
        for index, part in indexed_parts:
            _, part_result, responsibility_ref = _run_responsibility(index, part)
            part_results[index] = (part_result, responsibility_ref)

    for index, part in indexed_parts:
        part_result, responsibility_ref = part_results[index]
        expected_responsibilities.append(responsibility_ref)
        if set(part_result) != set(part):
            raise RuntimeError(
                f"{stage_name} responsibility {index} returned wrong keys: "
                f"expected={sorted(part)} observed={sorted(part_result)}"
            )
        overlap = set(merged).intersection(part_result)
        if overlap:
            raise RuntimeError(
                f"{stage_name} responsibility overlap: {sorted(overlap)}"
            )
        merged.update(part_result)
        covered_responsibilities.append(responsibility_ref)

    if set(merged) != set(schema):
        raise RuntimeError(
            f"{stage_name} responsibility coverage incomplete: "
            f"missing={sorted(set(schema) - set(merged))}"
        )
    report = build_coverage_report(
        stage_name=stage_name,
        expected_ids=expected_responsibilities,
        covered_refs=covered_responsibilities,
    )
    with (nullcontext(connection) if connection is not None else connect()) as con:
        persist_coverage(
            con,
            person_id=person_id,
            package_date=package_date,
            source_ref=source_ref,
            report=report,
        )
        con.commit()
    if not report.ok:
        raise RuntimeError(
            f"{stage_name} responsibility manifest incomplete: "
            f"missing={len(report.missing)}"
        )
    return restore_stage_output({key: merged[key] for key in schema}, projection)
