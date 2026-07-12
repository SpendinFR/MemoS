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

from mlomega_audio_elite.night_orchestrator import LLMCallResult

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


def test_source_coverage_expands_atoms_to_all_985_raw_proofs():
    from mlomega_audio_elite.brain2_episode_windowing import _source_coverage

    turns = _turns(40)
    raw_refs = [f"obs{i}" for i in range(945)]
    for atom_index in range(120):
        refs = raw_refs[atom_index::120]
        turns.append({
            "turn_id": f"vision_atom_{atom_index}",
            "idx": 40 + atom_index,
            "text": "vision",
            "metadata_json": json.dumps({
                "source": {
                    "vision_change_atom": True,
                    "source_refs": refs,
                }
            }),
        })
    expected, atom_index = _source_coverage(turns)
    assert len(expected) == 985
    assert set(expected) == {f"t{i}" for i in range(40)} | set(raw_refs)
    assert len(atom_index) == 120


def test_build_episodes_windowed_runs_per_window_merges_and_covers():
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    turns = _turns(120)
    bundle = {"conversation": {"started_at": "2026-07-12T00:00:00+00:00"},
              "turns": turns, "source_spans": []}

    calls: list[list[str]] = []

    def safe_prompt(payload):
        return json.dumps(payload, default=str)

    class FakeWindowLLM:
        model = "fake-e64f"

        def generate(self, payload, *, output_budget):
            p = json.loads(payload["prompt"])
            ids = [t["turn_id"] for t in p["conversation_bundle"]["turns"]]
            calls.append(ids)
            return LLMCallResult(ok=True, data={
                "episodes": [{"episode_type": "other", "situation_summary": "s",
                              "evidence_turn_ids": ids, "start_turn_id": ids[0],
                              "end_turn_id": ids[-1], "confidence": 0.9}],
                "missing_context": [],
            })

    materialized = {}

    def materialize(c, cid, out):
        materialized["out"] = out
        return len(out["episodes"])

    stats = build_episodes_windowed(
        con, "conv1", bundle=bundle, person_id="me", package_date="2026-07-12",
        safe_prompt=safe_prompt, materialize=materialize,
        mission="M", schema={"episodes": [], "missing_context": []}, system="S",
        window_llm=FakeWindowLLM(), output_budget=256,
        budget_tokens=1200, target_turns=45, overlap=3,
    )
    assert stats["windows"] > 1  # 120 big turns -> several windows
    assert len(calls) == stats["windows"]  # V13 prompt run once per window
    assert stats["coverage_ok"] is True
    # Every turn is covered by evidence manifests attached to VALIDATED outputs
    # and persisted in the real E64-C output table.
    row = con.execute(
        "SELECT expected_count, covered_count, missing_count, ok FROM night_llm_coverage_v19"
    ).fetchone()
    assert row == (120, 120, 0, 1)
    assert con.execute("SELECT COUNT(*) FROM night_llm_window_outputs_v19").fetchone()[0] == stats["windows"]
    # episodes were materialised
    assert materialized["out"]["episodes"]


def test_windowed_coverage_accepts_valid_persisted_empty_result():
    # Zero episodes is a legitimate semantic result. Coverage is still real
    # because the validated empty result + its processed evidence manifest are
    # persisted atomically in night_llm_window_outputs_v19.
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    bundle = {"conversation": {}, "turns": _turns(60), "source_spans": []}

    class EmptyWindowLLM:
        model = "fake-empty"

        def generate(self, payload, *, output_budget):
            return LLMCallResult(
                ok=True, data={"episodes": [], "missing_context": ["nothing"]}
            )

    stats = build_episodes_windowed(
        con, "conv2", bundle=bundle, person_id="me", package_date="d",
        safe_prompt=lambda p: json.dumps(p, default=str),
        materialize=lambda c, cid, out: 0, mission="M",
        schema={"episodes": [], "missing_context": []}, system="S",
        window_llm=EmptyWindowLLM(), output_budget=256, budget_tokens=1200,
    )
    assert stats["coverage_ok"] is True
    assert stats["episodes"] == 0


def test_windowed_failure_is_not_credited_or_materialized():
    from mlomega_audio_elite.brain2_episode_windowing import build_episodes_windowed

    con = sqlite3.connect(":memory:")
    bundle = {"conversation": {}, "turns": _turns(12), "source_spans": []}
    materialized = []

    class DownWindowLLM:
        model = "fake-down"

        def generate(self, payload, *, output_budget):
            return LLMCallResult(ok=False, error_kind="unavailable")

    with pytest.raises(RuntimeError, match="incomplete"):
        build_episodes_windowed(
            con, "conv-down", bundle=bundle, person_id="me", package_date="d",
            safe_prompt=lambda p: json.dumps(p, default=str),
            materialize=lambda *args: materialized.append(args), mission="M",
            schema={"episodes": [], "missing_context": []}, system="S",
            window_llm=DownWindowLLM(), output_budget=256, budget_tokens=1200,
        )
    assert materialized == []
    assert con.execute("SELECT COUNT(*) FROM night_llm_window_outputs_v19").fetchone()[0] == 0
    expected, covered, missing, ok = con.execute(
        "SELECT expected_count, covered_count, missing_count, ok FROM night_llm_coverage_v19"
    ).fetchone()
    assert expected == missing == 12
    assert covered == ok == 0


def test_dedupe_merges_identical_evidence_episodes():
    from mlomega_audio_elite.brain2_episode_windowing import _dedupe_episodes

    eps = [
        {"situation_summary": "a", "evidence_turn_ids": ["t1", "t2"], "start_time": "x"},
        {"situation_summary": "a-dup", "evidence_turn_ids": ["t2", "t1"], "start_time": "x"},
        {"situation_summary": "b", "evidence_turn_ids": ["t3"], "start_time": "y"},
    ]
    merged = _dedupe_episodes(eps)
    assert len(merged) == 2  # the two identical-evidence episodes collapse


def test_dedupe_merges_partial_boundary_episode_by_shared_evidence():
    from mlomega_audio_elite.brain2_episode_windowing import _dedupe_episodes

    eps = [
        {"episode_type": "planning", "participants": ["me"],
         "situation_summary": "début", "evidence_turn_ids": ["t40", "t41", "t42"]},
        {"episode_type": "planning", "participants": ["me"],
         "situation_summary": "suite", "evidence_turn_ids": ["t42", "t43", "t44"]},
    ]
    merged = _dedupe_episodes(eps)
    assert len(merged) == 1
    assert set(merged[0]["evidence_turn_ids"]) == {"t40", "t41", "t42", "t43", "t44"}
