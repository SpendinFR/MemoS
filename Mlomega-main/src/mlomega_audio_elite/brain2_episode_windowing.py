"""E64-F wave 1 - windowed EpisodeBuilder around the UNCHANGED V13 prompt.

The single Brain2 episode_builder call over a whole day's conversation truncates
(OBS-13). This module keeps the exact V13 prompt/schema and instead runs it over
autonomous windows of turns (E64-C planning), then merges the structured episode
outputs (E64-D overlap dedup) and persists a coverage proof (E64-E). It does NOT
build a giant prompt, does NOT alter the V13 prompt text, and loses no turn: the
windows partition the turns (+bounded overlap) and coverage blocks on any gap.

The reusable V13 helpers (``conversation_bundle``, ``safe_prompt``, ``llm_call``,
``materialize``) are injected by ``brain2_strict_v13_2`` so this module never
imports it back (no cycle).
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Callable, Mapping, Sequence

from .night_orchestrator import (
    MergeItem,
    ModelBudget,
    OllamaWindowLLM,
    PlanUnit,
    StageScope,
    build_coverage_report,
    covered_refs_from_outputs_table,
    estimate_tokens_for_text,
    resolve_overlap,
    run_windows,
)
from .night_orchestrator import checkpoint_store as cp
from .night_orchestrator.coverage import persist_coverage
from .night_orchestrator.evidence_ref import content_digest

STAGE_NAME = "brain2_episodes"


def _source_coverage(
    turns: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, list[str]]]:
    """Expand vision atom turns back to their raw observation evidence.

    Ordinary audio/context turns remain direct evidence. A reduced vision turn
    is the atom ID and its ``metadata_json.source.source_refs`` are the raw
    observations it represents. This is what lets the final manifest prove the
    original 985 inputs rather than merely the ~160 reduced prompt units.
    """
    expected: list[str] = []
    atom_parents: dict[str, list[str]] = {}
    for i, turn in enumerate(turns):
        turn_id = str(turn.get("turn_id") or f"idx{turn.get('idx', i)}")
        metadata = turn.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        refs = source.get("source_refs") if isinstance(source, Mapping) else None
        if source and source.get("vision_change_atom") and isinstance(refs, list):
            parents = [str(ref) for ref in refs if ref]
            if parents:
                atom_parents[turn_id] = parents
                expected.extend(parents)
                continue
        expected.append(turn_id)
    return list(dict.fromkeys(expected)), atom_parents


def orchestrator_enabled() -> bool:
    """E64 night orchestrator flag. Default ON; set MLOMEGA_E64_NIGHT_ORCHESTRATOR=0 to roll back."""
    return os.environ.get("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1") != "0"


def _poststop_input_budget() -> int:
    """Token budget for the TURNS in one window (leaves room for prompt+output)."""
    try:
        return max(1000, int(os.environ.get("MLOMEGA_E64_WINDOW_INPUT_TOKENS", "9000")))
    except ValueError:
        return 9000


def _turn_units(turns: Sequence[Mapping[str, Any]]) -> tuple[list[PlanUnit], dict[str, Mapping[str, Any]]]:
    units: list[PlanUnit] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for i, t in enumerate(turns):
        ref = str(t.get("turn_id") or f"idx{t.get('idx', i)}")
        # Budget the complete serialised turn, not only its text: metadata and
        # source refs are part of the real prompt too.
        payload_digest = content_digest(dict(t))
        tokens = estimate_tokens_for_text(str(dict(t))) + 24
        units.append(
            PlanUnit(
                ref_id=ref, tokens=tokens, ts=str(t.get("idx", i)),
                content_digest=payload_digest,
            )
        )
        by_id[ref] = t
    return units, by_id


def should_window(turns: Sequence[Mapping[str, Any]], *, budget_tokens: int | None = None) -> bool:
    """True when the turns would not comfortably fit one V13 call.

    Small conversations keep the legacy single-call path (behaviour unchanged);
    only oversized ones are windowed, minimising blast radius.
    """
    budget = budget_tokens or _poststop_input_budget()
    total = sum(estimate_tokens_for_text(str(t.get("text") or "")) + 24 for t in turns)
    return total > budget


def _dedupe_episodes(episodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge compatible episodes that share overlap evidence.

    The semantic key uses structural business fields, never summaries/text. Two
    compatible episodes collapse only if E64-D also proves evidence or time
    overlap; partially different evidence sets across adjacent windows therefore
    merge correctly and keep their union.
    """
    items: list[MergeItem] = []
    payloads: dict[str, dict[str, Any]] = {}
    for i, ep in enumerate(episodes):
        if not isinstance(ep, dict):
            continue
        ev = [str(x) for x in (ep.get("evidence_turn_ids") or []) if x]
        participants = sorted(
            str(x).strip().casefold()
            for x in (ep.get("participants") or [])
            if str(x).strip()
        )
        key = "|".join([
            "episode",
            str(ep.get("episode_type") or "other").strip().casefold(),
            ",".join(participants),
            str(ep.get("target_person") or "").strip().casefold(),
            str(ep.get("channel") or "").strip().casefold(),
            str(ep.get("location") or "").strip().casefold(),
        ])
        item_id = f"ep{i}"
        payloads[item_id] = dict(ep)
        items.append(
            MergeItem(
                item_id=item_id,
                semantic_key=key,
                evidence_refs=frozenset(ev),
                time_start=str(ep.get("start_time") or ep.get("start_turn_id") or ""),
                time_end=str(ep.get("end_time") or ep.get("end_turn_id") or ""),
                payload={"item_id": item_id},
            )
        )
    survivors = resolve_overlap(items).survivors
    merged: list[dict[str, Any]] = []
    for surv in survivors:
        ep = payloads[surv.payload["item_id"]]
        # Preserve the union of evidence turns discovered across duplicates.
        if surv.evidence_refs:
            ep["evidence_turn_ids"] = sorted(surv.evidence_refs)
        merged.append(ep)
    return merged


def build_episodes_windowed(
    con: Any,
    conversation_id: str,
    *,
    bundle: Mapping[str, Any],
    person_id: str,
    package_date: str,
    safe_prompt: Callable[[dict[str, Any]], str],
    materialize: Callable[[Any, str, dict[str, Any]], int],
    mission: str,
    schema: dict[str, Any],
    system: str,
    window_llm: Any | None = None,
    model_name: str | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
    budget_tokens: int | None = None,
    target_turns: int = 45,
    overlap: int = 3,
) -> dict[str, Any]:
    """Run the V13 episode prompt per window, merge episodes, persist coverage.

    Returns a summary dict incl. ``episodes`` (materialised count), ``windows``
    and ``coverage_ok``. Raises if any turn is left uncovered (missing).
    """
    turns = list(bundle.get("turns") or [])
    units, by_id = _turn_units(turns)

    from .config import get_settings

    cfg = get_settings()
    if output_budget is None:
        try:
            output_budget = max(256, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096")))
        except ValueError:
            output_budget = 4096
    safety_margin = 768
    if budget_tokens is not None:
        # Test/diagnostic override means the desired maximum INPUT budget.
        context_window = int(budget_tokens) + int(output_budget) + safety_margin
    context_window = int(context_window or cfg.ollama_context_poststop)
    model_budget = ModelBudget(
        context_window=context_window,
        output_reserve=int(output_budget),
        safety_margin=safety_margin,
    )

    if window_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        window_llm = OllamaWindowLLM(
            system=system, schema_hint=schema, timeout=timeout,
        )
    model_name = str(model_name or getattr(window_llm, "model", "injected-window-llm"))
    scoped_stage = f"{STAGE_NAME}:{conversation_id}"

    def render(window_units: Sequence[PlanUnit]) -> Mapping[str, Any]:
        win_turns = [by_id[u.ref_id] for u in window_units if u.ref_id in by_id]
        win_bundle = dict(bundle)
        win_bundle["turns"] = win_turns
        return {"prompt": safe_prompt(
            {"mission": mission, "conversation_bundle": win_bundle, "schema": schema}
        )}

    def validate(output: Any) -> bool:
        if not isinstance(output, dict):
            return False
        episodes = output.get("episodes")
        missing = output.get("missing_context")
        if not isinstance(episodes, list) or not isinstance(missing, list):
            return False
        return all(
            isinstance(ep, dict)
            and isinstance(ep.get("evidence_turn_ids", []), list)
            for ep in episodes
        )

    def durable_envelope(output: Any, primary: Sequence[PlanUnit]) -> dict[str, Any]:
        # This manifest is written atomically WITH a validated model output. It
        # proves which primary evidence entered that durable result; overlap refs
        # remain copies and are intentionally not credited twice.
        return {
            "schema_version": "e64f.brain2.window.v2",
            "evidence_refs": [u.ref_id for u in primary],
            "result": output,
        }

    empty_bundle = dict(bundle)
    empty_bundle["turns"] = []
    prompt_overhead = estimate_tokens_for_text(
        safe_prompt({"mission": mission, "conversation_bundle": empty_bundle, "schema": schema})
    )
    stage = run_windows(
        units,
        con=con,
        scope=StageScope(
            person_id=person_id,
            package_date=package_date,
            stage_name=scoped_stage,
            adapter_version="e64f-episode-window-v2",
            prompt_version="v13-episode-mission-unchanged-v1",
            model=model_name,
        ),
        llm=window_llm,
        budget=model_budget,
        render=render,
        validate=validate,
        decorate_output=durable_envelope,
        target_units=target_turns,
        overlap=overlap,
        prompt_overhead_tokens=prompt_overhead,
        sleeper=time.sleep,
    )

    # Anti-loss proof comes ONLY from validated outputs re-read from the durable
    # output table. It never trusts the planner's in-memory primary list.
    covered = covered_refs_from_outputs_table(
        con,
        person_id=person_id,
        package_date=package_date,
        stage_name=scoped_stage,
        extract_refs=lambda stored: stored.get("evidence_refs", [])
        if isinstance(stored, dict) else (),
    )
    expected, atom_parent_index = _source_coverage(turns)
    quarantined = {
        source_ref: (window.error_text or "quarantined")
        for window in stage.quarantined
        for ref in window.primary_refs
        for source_ref in atom_parent_index.get(ref, [ref])
    }
    report = build_coverage_report(
        stage_name=STAGE_NAME,
        expected_ids=expected,
        covered_refs=covered,
        atom_parent_index=atom_parent_index,
        quarantined_reasons=quarantined,
    )
    persist_coverage(
        con, person_id=person_id, package_date=package_date,
        source_ref=conversation_id, report=report,
    )
    con.commit()
    if not report.ok or not stage.all_completed:
        raise RuntimeError(
            "brain2_episodes incomplete: "
            f"missing={len(report.missing)} quarantined={len(stage.quarantined)} "
            f"states={[w.state for w in stage.windows]}"
        )

    persisted = cp.load_outputs(
        con, person_id=person_id, package_date=package_date, stage_name=scoped_stage,
    )
    all_eps: list[Mapping[str, Any]] = []
    missing_context: list[Any] = []
    for row in persisted:
        envelope = row.get("output") if isinstance(row, dict) else None
        out = envelope.get("result") if isinstance(envelope, dict) else None
        if isinstance(out, dict):
            all_eps.extend(x for x in (out.get("episodes") or []) if isinstance(x, dict))
            missing_context.extend(out.get("missing_context") or [])

    merged = _dedupe_episodes(all_eps)
    count = materialize(con, conversation_id, {"episodes": merged, "missing_context": missing_context})
    return {
        "episodes": count,
        "windows": len(stage.windows),
        "coverage_ok": report.ok,
        "merged_from": len(all_eps),
    }
