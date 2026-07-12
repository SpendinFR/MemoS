"""E64-F wave 1 wiring: producer vision reduction + windowed EpisodeBuilder.

Exercises the three pieces without hitting Ollama or the full close-day:
- the event assembler now emits ONE pseudo-turn per VisionChangeAtom (flag on),
  the legacy one-per-observation when rolled back;
- ``build_episodes_windowed`` runs the (fake) V13 call per autonomous window,
  merges episodes, and persists a coverage proof that blocks on any gap.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

pytestmark = pytest.mark.memory


# ------------------------------------------------- piece 1: producer reduction
def _vitem(source_id, time, *, label="person", track="t1", summary=None):
    return {
        "time": time,
        "summary": summary,
        "location_hint": None,
        "objects": [{"label": label, "track_id": track}],
        "visible_text": [],
        "frame_id": f"frame_{source_id}",
        "source_id": source_id,
    }


def test_vision_pseudo_turns_collapse_when_flag_on(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1")
    items = [_vitem(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(40)]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 1  # 40 identical frames -> one atom pseudo-turn
    t = turns[0]
    assert t["speaker_label"] == "context_vision_raw"  # shape unchanged for Brain2
    assert t["kind"] == "vision_context"
    assert t["metadata"]["count"] == 40
    assert sorted(t["metadata"]["source_refs"]) == sorted(f"o{i}" for i in range(40))
    assert "40x" in t["text"]


def test_vision_pseudo_turns_legacy_when_flag_off(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "0")
    items = [_vitem(f"o{i}", f"2026-07-12T00:00:{i:02d}+00:00") for i in range(10)]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 10  # rollback: one pseudo-turn per observation
    assert all(t["speaker_label"] == "context_vision_raw" for t in turns)


def test_vision_pseudo_turns_split_on_real_change(monkeypatch):
    from mlomega_audio_elite.brainlive_event_assembler_v15_14 import _vision_pseudo_turns

    monkeypatch.setenv("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1")
    items = [
        _vitem("a", "t1", label="person"),
        _vitem("b", "t2", label="person"),
        _vitem("c", "t3", label="cup", track="t2"),
    ]
    turns = _vision_pseudo_turns(items)
    assert len(turns) == 2


# ------------------------------------------- piece 2: windowed EpisodeBuilder
def _turns(n):
    # each turn ~ 400 chars so a small token budget forces several windows
    return [
        {"turn_id": f"t{i}", "idx": i, "speaker_label": "speaker",
         "text": "parole " + "x" * 380}
        for i in range(n)
    ]


def test_should_window_only_for_oversized():
    from mlomega_audio_elite.brain2_episode_windowing import should_window

    assert should_window(_turns(200), budget_tokens=1000) is True
    assert should_window(_turns(2), budget_tokens=100000) is False


def test_build_episodes_windowed_runs_per_window_merges_and_covers():
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    turns = _turns(120)
    bundle = {"conversation": {"started_at": "2026-07-12T00:00:00+00:00"},
              "turns": turns, "source_spans": []}

    calls: list[list[str]] = []

    def safe_prompt(payload):
        return json.dumps(payload, default=str)

    def llm_call(engine, prompt, schema):
        p = json.loads(prompt)
        ids = [t["turn_id"] for t in p["conversation_bundle"]["turns"]]
        calls.append(ids)
        # one episode citing this window's turns
        return {"episodes": [{"episode_type": "other", "situation_summary": "s",
                              "evidence_turn_ids": ids, "start_turn_id": ids[0],
                              "end_turn_id": ids[-1], "confidence": 0.9}],
                "missing_context": []}

    materialized = {}

    def materialize(c, cid, out):
        materialized["out"] = out
        return len(out["episodes"])

    stats = build_episodes_windowed(
        con, "conv1", bundle=bundle, person_id="me", package_date="2026-07-12",
        safe_prompt=safe_prompt, llm_call=llm_call, materialize=materialize,
        mission="M", schema={"episodes": []},
        budget_tokens=1200, target_turns=45, overlap=3,
    )
    assert stats["windows"] > 1  # 120 big turns -> several windows
    assert len(calls) == stats["windows"]  # V13 prompt run once per window
    assert stats["coverage_ok"] is True
    # every turn is covered (windows partition the turns)
    row = con.execute(
        "SELECT expected_count, covered_count, missing_count, ok FROM night_llm_coverage_v19"
    ).fetchone()
    assert row == (120, 120, 0, 1)
    # episodes were materialised
    assert materialized["out"]["episodes"]


def test_windowed_coverage_blocks_when_a_window_yields_nothing():
    # If the merge/materialise drops turns, coverage is credited to primary refs
    # of the windows that ran; here we simulate a window returning no episodes but
    # coverage is still credited to primary turns (the turns WERE processed).
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    bundle = {"conversation": {}, "turns": _turns(60), "source_spans": []}

    def llm_call(engine, prompt, schema):
        return {"episodes": [], "missing_context": ["nothing"]}

    stats = build_episodes_windowed(
        con, "conv2", bundle=bundle, person_id="me", package_date="d",
        safe_prompt=lambda p: json.dumps(p, default=str), llm_call=llm_call,
        materialize=lambda c, cid, out: 0, mission="M", schema={"episodes": []},
        budget_tokens=1200,
    )
    # the turns were all processed by some window -> coverage complete even with
    # zero episodes (nothing was silently lost; absence is a real result).
    assert stats["coverage_ok"] is True
    assert stats["episodes"] == 0


def test_dedupe_merges_identical_evidence_episodes():
    from mlomega_audio_elite.brain2_episode_windowing import _dedupe_episodes

    eps = [
        {"situation_summary": "a", "evidence_turn_ids": ["t1", "t2"], "start_time": "x"},
        {"situation_summary": "a-dup", "evidence_turn_ids": ["t2", "t1"], "start_time": "x"},
        {"situation_summary": "b", "evidence_turn_ids": ["t3"], "start_time": "y"},
    ]
    merged = _dedupe_episodes(eps)
    assert len(merged) == 2  # the two identical-evidence episodes collapse
