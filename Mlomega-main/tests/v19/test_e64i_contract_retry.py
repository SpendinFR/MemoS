from __future__ import annotations

"""E64-i Gate B #6 — durable contract-rejection audit + no identical retry.

Proves the non-negotiable behaviours that unblocked the lossless gate on the
``brain2_conversation_detail`` window 6 that was quarantined after replaying the
SAME rejected output twice:

1. every contract rejection is persisted durably (raw output, parsed candidate,
   the precise violated rule/path/values, the digests and the strategy);
2. a byte-identical retry NEVER leaves the host — a second strictly identical
   rejected answer forbids further calls and hands over to the deterministic
   alternative strategy (a fake LLM call counter proves it);
3. the alternative strategy splits the window in two, drives each half, merges,
   and the coverage stays lossless (every source unit produced exactly once).

All fakes, in-memory SQLite; no business prompt, no real model.
"""

import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator import (
    LLMCallResult,
    ModelBudget,
    PlanUnit,
    PlannedWindow,
    StageScope,
    WindowSpec,
    run_windows,
)
from mlomega_audio_elite.night_orchestrator import checkpoint_store as cp
from mlomega_audio_elite.night_orchestrator.evidence_ref import content_digest

pytestmark = pytest.mark.memory


def _con():
    con = sqlite3.connect(":memory:")
    cp.ensure_schema(con)
    return con


def _units(n, tokens=10):
    return [PlanUnit(ref_id=f"u{i}", tokens=tokens, ts=f"t{i:03d}") for i in range(n)]


def _scope(stage="brain2_conversation_detail"):
    return StageScope(person_id="me", package_date="2026-07-17", stage_name=stage,
                      adapter_version="a1", prompt_version="p1", model="qwen")


def _render(units):
    return {"units": [u.ref_id for u in units]}


# --------------------------------------------------------------------------- #
# 1 + 2 : a fake LLM returns the SAME invalid output twice.                    #
#         The 2nd identical call must NEVER leave, the alt strategy must fire, #
#         and the rejection must be persisted with the precise violation.      #
# --------------------------------------------------------------------------- #
class SameInvalidTwice:
    """Always returns the identical (deterministic) rejected output."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, output_budget):
        self.calls += 1
        # A fixed answer independent of attempt: a temperature-0 retry is identical.
        return LLMCallResult(ok=True, data={"units": prompt["units"], "bad": True},
                             finish_reason="stop", prompt_tokens=11, completion_tokens=7)


def test_identical_rejection_forbids_second_call_and_triggers_alt_strategy():
    con = _con()
    llm = SameInvalidTwice()
    resolved = {"count": 0}

    def describe(candidate, window):
        return {
            "rule": "coverage_incomplete",
            "json_path": "conversation_episode.subthemes",
            "expected": "all source turns cited once",
            "received": "missing coverage",
        }

    def resolve(window, ctx):
        # The alternative strategy would split + re-run; here we only prove it is
        # invoked exactly once, after the identical retry was refused.
        resolved["count"] += 1
        return False  # not handled -> executor quarantines (still no 2nd LLM call)

    res = run_windows(
        _units(4), con=con, scope=_scope(), llm=llm,
        budget=ModelBudget(context_window=100000, output_reserve=200),
        render=_render, validate=lambda d: not d.get("bad"),
        describe_contract_violation=describe,
        resolve_contract_rejection=resolve,
        target_units=4, overlap=0, prompt_overhead_tokens=0, max_attempts=3,
    )

    # The FIRST call ran; the SECOND identical call was refused (economy+honesty).
    assert llm.calls == 1
    # The alternative strategy was consulted (exactly once).
    assert resolved["count"] == 1
    # Not handled -> quarantined, nothing partial applied.
    assert len(res.quarantined) == 1
    assert res.outputs == []


def test_rejection_persists_rule_path_values_and_digests():
    con = _con()
    llm = SameInvalidTwice()

    def describe(candidate, window):
        return {
            "rule": "coverage_incomplete",
            "json_path": "conversation_episode.subthemes",
            "expected": ["u0", "u1", "u2", "u3"],
            "received": ["u0", "u1"],
        }

    run_windows(
        _units(4), con=con, scope=_scope(), llm=llm,
        budget=ModelBudget(context_window=100000, output_reserve=200),
        render=_render, validate=lambda d: not d.get("bad"),
        describe_contract_violation=describe,
        target_units=4, overlap=0, prompt_overhead_tokens=0, max_attempts=3,
    )

    rows = con.execute(
        f"SELECT strategy, raw_output, parsed_output_json, violations_json, "
        f"input_digest, output_digest, finish_reason, completion_tokens "
        f"FROM {cp.REJECTIONS_TABLE} ORDER BY created_at"
    ).fetchall()
    # Both rejected attempts are audited (the 2nd is refused as a call, but the
    # first identical answer that proved the loop is durably recorded).
    assert rows, "at least one rejection persisted"
    strategy, raw, parsed, violations, in_dig, out_dig, finish, out_tokens = rows[0]
    import json as _json

    assert "u0" in raw and '"bad": true' in raw.lower().replace(" ", " ")
    assert _json.loads(violations)["rule"] == "coverage_incomplete"
    assert _json.loads(violations)["json_path"] == "conversation_episode.subthemes"
    assert _json.loads(violations)["received"] == ["u0", "u1"]
    assert in_dig and out_dig and finish == "stop"
    # The parsed candidate (validator input) is kept beside the raw output.
    assert parsed is not None
    # The telemetry no longer hides the rejection behind an empty facts blob.
    call = con.execute(
        f"SELECT facts_produced_json FROM {cp.CALLS_TABLE} WHERE outcome='contract_rejected' LIMIT 1"
    ).fetchone()
    assert call is not None
    facts = _json.loads(call[0])
    assert facts.get("violations", {}).get("rule") == "coverage_incomplete"
    assert facts.get("rejection_output_digest")


# --------------------------------------------------------------------------- #
# 3 : split -> merge -> coverage lossless via the alternative strategy.        #
#     A window whose whole-batch answer is rejected but whose two halves each   #
#     validate must be resolved by driving the two child windows, keeping every #
#     source unit covered exactly once.                                         #
# --------------------------------------------------------------------------- #
class RejectWholeAcceptHalves:
    """Rejects the full 4-unit window, validates each 2-unit half."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, output_budget):
        self.calls += 1
        units = prompt["units"]
        if len(units) >= 4:
            return LLMCallResult(ok=True, data={"units": units, "bad": True},
                                 finish_reason="stop")
        return LLMCallResult(ok=True, data={"units": units, "bad": False},
                             finish_reason="stop")


def test_split_merge_keeps_coverage_lossless():
    con = _con()
    llm = RejectWholeAcceptHalves()
    scope = _scope("split_stage")

    def describe(candidate, window):
        return {"rule": "cardinality", "json_path": "units",
                "expected": "one per half", "received": "batch"}

    def resolve(window, ctx):
        # Deterministic split of the window's primary units into two halves; each
        # half is driven through the executor's own machinery (drive hook) so it is
        # budgeted, validated and checkpointed exactly like any leaf window.
        primary = list(window.primary_units)
        if len(primary) < 2:
            return False
        mid = len(primary) // 2
        halves = [primary[:mid], primary[mid:]]
        drive = ctx["drive"]
        base = int(window.spec.window_index)
        child_indexes = []
        for i, half in enumerate(halves):
            refs = tuple(u.ref_id for u in half)
            idx = base * 1000 + i + 1
            child_indexes.append(idx)
            spec = WindowSpec(
                stage_name=scope.stage_name, window_index=idx,
                primary_refs=refs, overlap_refs=(),
                input_digest=content_digest(list(refs)),
            )
            drive(PlannedWindow(spec=spec, primary_units=tuple(half),
                                overlap_units=(), input_tokens=sum(u.tokens for u in half)))
        result = ctx["result"]
        done = [w for w in result.windows
                if w.window_index in child_indexes and w.state == cp.STATE_COMPLETED]
        return len(done) == len(halves)

    res = run_windows(
        _units(4), con=con, scope=scope, llm=llm,
        budget=ModelBudget(context_window=100000, output_reserve=200),
        render=_render, validate=lambda d: not d.get("bad"),
        describe_contract_violation=describe,
        resolve_contract_rejection=resolve,
        target_units=4, overlap=0, prompt_overhead_tokens=0, max_attempts=3,
    )

    # The parent window is not quarantined; the two halves completed.
    assert res.quarantined == []
    covered = sorted(u for o in res.outputs for u in o["units"])
    # Every source unit produced exactly once (lossless).
    assert covered == ["u0", "u1", "u2", "u3"]
    # No identical retry of the whole batch: the parent's batch call ran once,
    # then two half calls. No fourth (repeat) whole-batch call.
    assert llm.calls == 3
    # The parent is recorded subdivided (its work lives in the children).
    states = dict(con.execute(
        f"SELECT state, COUNT(*) FROM {cp.WINDOWS_TABLE} GROUP BY state"
    ).fetchall())
    assert states.get("completed") == 2
    assert states.get("subdivided") == 1


def test_resume_does_not_replay_resolved_children(tmp_path):
    """A resolved (split) window resumes without repaying any child LLM call."""
    path = tmp_path / "cp.db"
    con = sqlite3.connect(path)
    cp.ensure_schema(con)
    scope = _scope("split_resume")

    def resolve(window, ctx):
        primary = list(window.primary_units)
        if len(primary) < 2:
            return False
        mid = len(primary) // 2
        drive = ctx["drive"]
        base = int(window.spec.window_index)
        idxs = []
        for i, half in enumerate([primary[:mid], primary[mid:]]):
            refs = tuple(u.ref_id for u in half)
            idx = base * 1000 + i + 1
            idxs.append(idx)
            spec = WindowSpec(stage_name=scope.stage_name, window_index=idx,
                              primary_refs=refs, overlap_refs=(),
                              input_digest=content_digest(list(refs)))
            drive(PlannedWindow(spec=spec, primary_units=tuple(half),
                                overlap_units=(), input_tokens=sum(u.tokens for u in half)))
        result = ctx["result"]
        return len([w for w in result.windows
                    if w.window_index in idxs and w.state == cp.STATE_COMPLETED]) == 2

    kwargs = dict(
        con=con, scope=scope,
        budget=ModelBudget(context_window=100000, output_reserve=200),
        render=_render, validate=lambda d: not d.get("bad"),
        resolve_contract_rejection=resolve,
        target_units=4, overlap=0, prompt_overhead_tokens=0, max_attempts=3,
    )
    first = run_windows(_units(4), llm=RejectWholeAcceptHalves(), **kwargs)
    assert first.quarantined == []
    con.commit()

    class NeverCalled:
        def generate(self, prompt, *, output_budget):
            raise AssertionError("no LLM call must happen on resume")

    second = run_windows(_units(4), llm=NeverCalled(), **kwargs)
    covered = sorted(u for o in second.outputs for u in o["units"])
    assert covered == ["u0", "u1", "u2", "u3"]
