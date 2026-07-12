"""E64-C tests: token-aware windowing, durable checkpoints, executor policies.

Proves the non-negotiable behaviours with a deterministic fake LLM and an
in-memory SQLite checkpoint store: window planning never drops a unit and honours
the token budget, overlap markers, subdivision on truncation, quarantine of an
irreducible truncation, bounded repair on invalid output, transient retry+resume,
and never applying a partial. No business prompt and no close-day code involved.
"""

from __future__ import annotations

import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator import (
    LLMCallResult,
    ModelBudget,
    PlanUnit,
    StageScope,
    plan_windows,
    run_windows,
)
from mlomega_audio_elite.night_orchestrator import checkpoint_store as cp

pytestmark = pytest.mark.memory


def _con():
    con = sqlite3.connect(":memory:")
    cp.ensure_schema(con)
    return con


def _units(n, tokens=10):
    return [PlanUnit(ref_id=f"u{i}", tokens=tokens, ts=f"t{i:03d}") for i in range(n)]


def _scope(stage="s"):
    return StageScope(person_id="me", package_date="2026-07-12", stage_name=stage,
                      adapter_version="a1", prompt_version="p1", model="qwen")


# ------------------------------------------------------------------- planner
def test_plan_targets_units_but_cuts_on_token_budget():
    units = _units(100, tokens=10)
    # target 45 units, but 200 input tokens max => ~20 units/window by budget
    wins = plan_windows(units, stage_name="s", max_input_tokens=200, target_units=45, overlap=0)
    # every window's input tokens <= budget
    assert all(w.input_tokens <= 200 for w in wins)
    # no window exceeds the target
    assert all(len(w.primary_units) <= 45 for w in wins)


def test_planner_is_lossless_every_unit_primary_exactly_once():
    units = _units(97, tokens=7)
    wins = plan_windows(units, stage_name="s", max_input_tokens=100, target_units=45, overlap=3)
    primary = [u.ref_id for w in wins for u in w.primary_units]
    assert sorted(primary) == sorted(u.ref_id for u in units)
    assert len(primary) == len(set(primary))  # each primary exactly once


def test_overlap_units_are_marked_not_primary():
    units = _units(20, tokens=1)
    wins = plan_windows(units, stage_name="s", max_input_tokens=5, target_units=45, overlap=2)
    assert len(wins) >= 2
    # window 2's overlap == tail of window 1's primary
    assert wins[1].spec.overlap_refs == tuple(u.ref_id for u in wins[0].primary_units[-2:])


def test_hard_boundary_opens_a_window():
    units = [PlanUnit("a", 1), PlanUnit("b", 1, boundary=True), PlanUnit("c", 1)]
    wins = plan_windows(units, stage_name="s", max_input_tokens=999, target_units=45, overlap=0)
    assert [tuple(u.ref_id for u in w.primary_units) for w in wins] == [("a",), ("b", "c")]


# --------------------------------------------------------------- executor OK
def _render(units):
    return {"units": [u.ref_id for u in units]}


class OkLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, output_budget):
        self.calls += 1
        return LLMCallResult(ok=True, data={"episodes": prompt["units"]})


def test_executor_completes_and_checkpoints_all_windows():
    con = _con()
    llm = OkLLM()
    res = run_windows(_units(30), con=con, scope=_scope(), llm=llm,
                      budget=ModelBudget(context_window=1000, output_reserve=200),
                      render=_render, validate=lambda d: True, target_units=10, overlap=0,
                      prompt_overhead_tokens=0)
    assert res.all_completed
    assert len(res.windows) == 3  # 30 units / 10 per window
    assert len(res.outputs) == 3
    rows = con.execute(f"SELECT state, COUNT(*) FROM {cp.WINDOWS_TABLE} GROUP BY state").fetchall()
    assert dict(rows) == {"completed": 3}


def test_resume_skips_completed_windows_no_double_output():
    con = _con()
    scope = _scope()
    budget = ModelBudget(context_window=1000, output_reserve=200)
    first = run_windows(_units(30), con=con, scope=scope, llm=OkLLM(),
                        budget=budget, render=_render, validate=lambda d: True,
                        target_units=10, overlap=0, prompt_overhead_tokens=0)
    assert first.all_completed
    llm2 = OkLLM()
    second = run_windows(_units(30), con=con, scope=scope, llm=llm2,
                         budget=budget, render=_render, validate=lambda d: True,
                         target_units=10, overlap=0, prompt_overhead_tokens=0)
    assert second.all_completed
    assert llm2.calls == 0  # everything resumed from checkpoints
    # outputs table did not double
    n = con.execute(f"SELECT COUNT(*) FROM {cp.OUTPUTS_TABLE}").fetchone()[0]
    assert n == 3


# ------------------------------------------------- subdivision on truncation
class TruncateUntilSmall:
    """Returns length-truncation until the window holds <= max_ok units."""

    def __init__(self, max_ok):
        self.max_ok = max_ok
        self.calls = 0

    def generate(self, prompt, *, output_budget):
        self.calls += 1
        if len(prompt["units"]) > self.max_ok:
            return LLMCallResult(ok=False, error_kind="length", finish_reason="length")
        return LLMCallResult(ok=True, data={"episodes": prompt["units"]})


def test_length_truncation_subdivides_recursively_and_covers_all():
    con = _con()
    llm = TruncateUntilSmall(max_ok=4)
    res = run_windows(_units(16), con=con, scope=_scope(), llm=llm,
                      budget=ModelBudget(context_window=100000, output_reserve=200),
                      render=_render, validate=lambda d: True, target_units=16, overlap=0)
    # all leaf windows completed, no unit lost
    covered = [u for o in res.outputs for u in o["episodes"]]
    assert sorted(covered) == sorted(f"u{i}" for i in range(16))
    assert res.quarantined == []


class AlwaysTruncate:
    def generate(self, prompt, *, output_budget):
        return LLMCallResult(ok=False, error_kind="length", finish_reason="length")


def test_single_unit_that_still_truncates_is_quarantined_not_applied():
    con = _con()
    res = run_windows(_units(2), con=con, scope=_scope(), llm=AlwaysTruncate(),
                      budget=ModelBudget(context_window=100000, output_reserve=200),
                      render=_render, validate=lambda d: True, target_units=2, overlap=0)
    assert len(res.quarantined) == 2  # each irreducible unit quarantined
    assert res.outputs == []  # nothing partial applied
    states = {r[0] for r in con.execute(f"SELECT DISTINCT state FROM {cp.WINDOWS_TABLE}")}
    # the 2-unit parent is 'subdivided'; its two single-unit leaves are quarantined
    assert states == {"subdivided", "quarantined"}


# --------------------------------------------------- over-budget refusal
def test_oversized_single_unit_is_refused_and_quarantined():
    con = _con()
    # one unit costs 10000 tokens; budget max_input is tiny
    units = [PlanUnit("big", 10000)]
    res = run_windows(units, con=con, scope=_scope(), llm=OkLLM(),
                      budget=ModelBudget(context_window=1000, output_reserve=200, safety_margin=100),
                      render=_render, validate=lambda d: True, target_units=45, overlap=0,
                      prompt_overhead_tokens=0)
    assert len(res.quarantined) == 1
    assert res.outputs == []


# ------------------------------------------------- invalid output repair
class InvalidThenValid:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, output_budget):
        self.calls += 1
        # ok=True but the contract validator will reject the first answer
        return LLMCallResult(ok=True, data={"bad": self.calls == 1, "units": prompt["units"]})


def test_bounded_repair_then_success():
    con = _con()
    llm = InvalidThenValid()
    res = run_windows(_units(3), con=con, scope=_scope(), llm=llm,
                      budget=ModelBudget(context_window=1000, output_reserve=100),
                      render=_render, validate=lambda d: not d.get("bad"),
                      target_units=3, overlap=0)
    assert res.all_completed
    assert llm.calls == 2  # first invalid, second valid


class AlwaysInvalid:
    def generate(self, prompt, *, output_budget):
        return LLMCallResult(ok=True, data={"bad": True})


def test_persistently_invalid_is_quarantined_after_bounded_repair():
    con = _con()
    res = run_windows(_units(3), con=con, scope=_scope(), llm=AlwaysInvalid(),
                      budget=ModelBudget(context_window=1000, output_reserve=100),
                      render=_render, validate=lambda d: not d.get("bad"),
                      target_units=3, overlap=0)
    assert len(res.quarantined) == 1
    assert res.outputs == []


# ------------------------------------------------- transient retry + resume
class FlakyThenDown:
    def generate(self, prompt, *, output_budget):
        return LLMCallResult(ok=False, error_kind="unavailable", finish_reason=None)


def test_transient_unavailable_retries_then_errors_resumable():
    con = _con()
    sleeps = []
    res = run_windows(_units(3), con=con, scope=_scope(), llm=FlakyThenDown(),
                      budget=ModelBudget(context_window=1000, output_reserve=100),
                      render=_render, validate=lambda d: True, target_units=3, overlap=0,
                      max_attempts=3, sleeper=sleeps.append)
    assert res.windows[0].state == cp.STATE_ERROR  # retryable, not applied
    assert res.outputs == []
    assert len(sleeps) >= 2  # backed off between attempts
    # a later run with a healthy LLM resumes the errored window (not skipped)
    ok = run_windows(_units(3), con=con, scope=_scope(), llm=OkLLM(),
                     budget=ModelBudget(context_window=1000, output_reserve=100),
                     render=_render, validate=lambda d: True, target_units=3, overlap=0)
    assert ok.all_completed


def test_window_key_is_idempotent_and_scope_sensitive():
    k1 = cp.window_key(person_id="me", package_date="d", stage_name="s", input_digest="x",
                       window_index=0, adapter_version="a1", prompt_version="p1", model="m")
    k2 = cp.window_key(person_id="me", package_date="d", stage_name="s", input_digest="x",
                       window_index=0, adapter_version="a1", prompt_version="p1", model="m")
    k3 = cp.window_key(person_id="me", package_date="d", stage_name="s", input_digest="x",
                       window_index=0, adapter_version="a2", prompt_version="p1", model="m")
    assert k1 == k2 and k1 != k3  # same inputs same key; new adapter -> new key
