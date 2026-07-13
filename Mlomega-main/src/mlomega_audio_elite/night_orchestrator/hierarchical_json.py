"""Bounded hierarchical JSON calls for day/conversation-wide night stages.

The business stage still owns its system prompt, payload and output schema. This
module only turns unbounded collections into token-aware durable windows, then
reduces validated partial outputs through bounded merge levels. Every leaf ref
survives transitively to the final envelope; no writer sees partial JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from typing import Any, Mapping, Sequence

from ..config import get_settings
from ..db import connect
from ..utils import json_dumps, now_iso, sha256_bytes, stable_id
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
            projected, child_leaves = _extract_lists(child, path + (str(key),))
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
) -> dict[str, Any]:
    """Return one complete schema object or raise without applying a partial."""
    cfg = get_settings()
    context_window = int(context_window or cfg.ollama_context_poststop)
    if output_budget is None:
        try:
            output_budget = max(256, int(__import__("os").environ.get(
                "MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"
            )))
        except ValueError:
            output_budget = 4096
    budget = ModelBudget(
        context_window=context_window,
        output_reserve=int(output_budget),
        safety_margin=768,
    )
    llm = OllamaWindowLLM(
        system=system, client=client, schema_hint=dict(schema), timeout=timeout
    )
    model = str(getattr(llm, "model", "ollama-json"))
    full_probe = json_dumps({
        "mission": payload.get("mission"),
        "hierarchical_instruction": "bounded complete input",
        "input": payload,
        "schema": schema,
    })
    if estimate_tokens_for_text(full_probe) <= budget.max_input_tokens:
        digest = _digest(payload)
        leaves = [_Leaf(
            stable_id("nightleaf", stage_name, digest), ("$",), dict(payload), digest
        )]
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
            })
            overhead_tokens = estimate_tokens_for_text(empty)
            target_units = 10 if level == 0 else 4
            expected_planned_count = len(plan_windows(
                units,
                stage_name=scoped_stage,
                max_input_tokens=max(1, budget.max_input_tokens - overhead_tokens),
                target_units=target_units,
                overlap=0,
            ))
            stage = run_windows(
                units,
                con=con,
                scope=StageScope(
                    person_id=person_id,
                    package_date=package_date,
                    stage_name=scoped_stage,
                    adapter_version="e64f-hierarchical-json-v1",
                    prompt_version=f"{stage_name}:v1",
                    model=model,
                ),
                llm=llm,
                budget=budget,
                render=render,
                validate=lambda value: _validate_schema_shape(value, schema),
                decorate_output=envelope,
                target_units=target_units,
                overlap=0,
                prompt_overhead_tokens=overhead_tokens,
                # Leaf evidence can be divided safely. A merge already contains
                # partial full-schema outputs; length there means split output
                # responsibilities, which the calling adapter owns.
                subdivide_on_length=(level == 0),
            )
            if not stage.all_completed:
                raise RuntimeError(
                    f"{scoped_stage} incomplete: "
                    f"states={[window.state for window in stage.windows]}"
                )
            outputs = [out for out in stage.outputs if isinstance(out, Mapping)]
            if not outputs:
                raise RuntimeError(f"{scoped_stage} completed without output")
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
