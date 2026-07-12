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
from typing import Any, Callable, Mapping, Sequence

from .night_orchestrator import (
    MergeItem,
    PlanUnit,
    build_coverage_report,
    estimate_tokens_for_text,
    plan_windows,
    resolve_overlap,
)
from .night_orchestrator.coverage import persist_coverage

STAGE_NAME = "brain2_episodes"


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
        # A turn's prompt cost ~= its text plus a small per-turn envelope.
        tokens = estimate_tokens_for_text(str(t.get("text") or "")) + 24
        units.append(PlanUnit(ref_id=ref, tokens=tokens, ts=str(t.get("idx", i))))
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
    """Merge episodes that cite the SAME evidence turns (overlap duplicates).

    Two episodes with an identical evidence-turn set (produced once per window in
    the shared overlap) collapse to one; the survivor keeps its payload and the
    union of evidence turns. Episodes over different turns stay distinct - dedup
    is by evidence, never by text.
    """
    items: list[MergeItem] = []
    payloads: dict[str, dict[str, Any]] = {}
    for i, ep in enumerate(episodes):
        if not isinstance(ep, dict):
            continue
        ev = [str(x) for x in (ep.get("evidence_turn_ids") or []) if x]
        key = "ep|" + "|".join(sorted(ev)) if ev else f"ep_noev|{i}"
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
    llm_call: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    materialize: Callable[[Any, str, dict[str, Any]], int],
    mission: str,
    schema: dict[str, Any],
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
    budget = budget_tokens or _poststop_input_budget()
    windows = plan_windows(
        units, stage_name=STAGE_NAME, max_input_tokens=budget,
        target_units=target_turns, overlap=overlap,
    )

    all_eps: list[Mapping[str, Any]] = []
    missing_context: list[Any] = []
    covered: set[str] = set()
    for w in windows:
        win_turns = [by_id[u.ref_id] for u in w.units if u.ref_id in by_id]
        win_bundle = dict(bundle)
        win_bundle["turns"] = win_turns
        prompt = safe_prompt(
            {"mission": mission, "conversation_bundle": win_bundle, "schema": schema}
        )
        out = llm_call("episode_builder", prompt, schema)
        if isinstance(out, dict):
            all_eps.extend(x for x in (out.get("episodes") or []) if isinstance(x, dict))
            missing_context.extend(out.get("missing_context") or [])
        # Coverage is credited to the window's PRIMARY turns (overlap is a copy).
        covered.update(u.ref_id for u in w.primary_units)

    merged = _dedupe_episodes(all_eps)
    count = materialize(con, conversation_id, {"episodes": merged, "missing_context": missing_context})

    expected = [u.ref_id for u in units]
    report = build_coverage_report(
        stage_name=STAGE_NAME, expected_ids=expected, covered_refs=covered
    )
    persist_coverage(
        con, person_id=person_id, package_date=package_date,
        source_ref=conversation_id, report=report,
    )
    if not report.ok:
        raise RuntimeError(
            f"brain2_episodes coverage incomplete: {len(report.missing)} turns uncovered"
        )
    return {
        "episodes": count,
        "windows": len(windows),
        "coverage_ok": report.ok,
        "merged_from": len(all_eps),
    }
