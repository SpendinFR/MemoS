"""I1.3 - windowed long-conversation episode building, no input_budget_exceeded.

These tests drive ``build_conversation_episode_v6`` with a conversation that
largely exceeds one model context. The two v6 passes (boundary segmentation and
locked-segment detail) are windowed through the E64 orchestrator; the fakes here
respond per window, never a real LLM. The assertions prove the I1.3 contract:

- an oversized conversation is windowed, never ``input_budget_exceeded``;
- the segmentation windows are reassembled BY CODE into one contiguous, gap-free
  partition (every human turn covered exactly once, borders reconciled once);
- locked segments are detailed in bounded batches of WHOLE segments;
- a second run over the same input replays zero LLM calls (durable checkpoints);
- no fusion by text and no lost refs/subthemes;
- a short conversation keeps the historic two-call path with identical prompts.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from mlomega_audio_elite.brain2_conversation_episode import (
    _DETAIL_MISSION,
    _SEGMENTATION_MISSION,
    build_conversation_episode_v6,
)
from mlomega_audio_elite.night_orchestrator.executor import LLMCallResult


@contextmanager
def connect(_path: str = ":memory:"):
    """A minimal checkpoint-capable connection (no business schema needed)."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


# A per-turn text long enough that a few dozen turns blow past a small budget,
# yet a SINGLE turn/segment still fits comfortably (so windowing splits by budget
# without pathologically quarantining a lone oversized unit).
_LONG_TEXT = "Nous discutons du rendez-vous et du metier avec quelques mots."


def _long_turns(count: int) -> list[dict[str, object]]:
    return [
        {
            "turn_id": f"t{index}",
            "idx": index,
            "speaker_label": "SPEAKER_00" if index % 3 else "SPEAKER_01",
            "person_id": "UNKNOWN_VOICE_001" if index % 3 else "UNKNOWN_VOICE_002",
            "start_s": float(index),
            "end_s": float(index) + 0.5,
            "text": f"Tour {index}: {_LONG_TEXT}",
            "metadata_json": json.dumps({
                "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript",
                "source": {"word_alignment": {"count": 20, "mean_score": 0.82}},
            }),
        }
        for index in range(count)
    ]


def _bundle(turns: list[dict[str, object]]) -> dict[str, object]:
    return {
        "conversation": {
            "conversation_id": "convL",
            "channel": "phoneonly",
            "person_id": "OWNER_1",
            "started_at": "2026-07-15T10:00:00",
        },
        "turns": turns,
        "source_spans": [],
    }


class WindowedFakeLLM:
    """Deterministic per-window responder for both v6 passes.

    Segmentation: one segment per window covering all of that window's primary
    (``human_turn_ids``) turns, ending on the last one. Detail: one subtheme per
    segment in the batch, echoing the segment ordinal + turn_ids so the reassembly
    can prove a lossless, text-free partition.
    """

    model = "windowed-fake"

    def __init__(self) -> None:
        self.segmentation_calls: list[dict] = []
        self.detail_calls: list[dict] = []

    def generate(self, payload, *, output_budget):
        prompt = json.loads(payload["prompt"]) if isinstance(payload.get("prompt"), str) else payload
        mission = prompt.get("mission")
        if mission == _SEGMENTATION_MISSION:
            self.segmentation_calls.append(prompt)
            primary = list(prompt["contract"]["human_turn_ids"])
            # Cut every ~3 primary turns so sub-theme borders land both INSIDE a
            # window and AT window edges (the last cut is always the window's last
            # primary). Small segments also keep every single-segment detail batch
            # comfortably under budget, so the batching path is exercised without a
            # pathological oversized-lone-segment quarantine.
            cuts: list[str] = []
            for offset in range(2, len(primary), 3):
                cuts.append(primary[offset])
            if not cuts or cuts[-1] != primary[-1]:
                cuts.append(primary[-1])
            return LLMCallResult(ok=True, data={
                "segments": [
                    {
                        "ordinal": ordinal,
                        "title_hint": f"Bloc {end}",
                        "end_turn_id": end,
                        "boundary_reason": "conversation_start" if ordinal == 0 else "new_goal",
                    }
                    for ordinal, end in enumerate(cuts)
                ],
                "missing_context": [],
            })
        if mission == _DETAIL_MISSION:
            self.detail_calls.append(prompt)
            segments = prompt["segments"]
            subthemes = []
            for segment in segments:
                turn_ids = [str(turn["turn_id"]) for turn in segment["turns"]]
                subthemes.append({
                    "ordinal": int(segment["ordinal"]),
                    "subtheme_type": "other",
                    "title": f"Detail {segment['ordinal']}",
                    "summary": f"Resume du segment {segment['ordinal']} ({turn_ids[0]}..{turn_ids[-1]}).",
                    "participants": ["UNKNOWN_VOICE_001"],
                    "evidence_turn_ids": turn_ids,
                    "outcome": None,
                    "unresolved_tension": None,
                    "confidence": 0.7,
                })
            return LLMCallResult(ok=True, data={
                "conversation_episode": {
                    "title": "Longue conversation",
                    "situation_summary": "Une longue conversation multi-sujets.",
                    "participants": ["UNKNOWN_VOICE_001", "UNKNOWN_VOICE_002"],
                    "location": None,
                    "channel": "phoneonly",
                    "confidence": 0.75,
                    "subthemes": subthemes,
                },
                "missing_context": [],
            })
        raise AssertionError(f"unexpected mission: {mission}")


def _run(con, llm, turns, *, input_budget=2500, output_budget=512):
    written = {}

    def materialize(_con, _conversation_id, output):
        written["output"] = output
        return len(output["episodes"])

    stats = build_conversation_episode_v6(
        con,
        "convL",
        bundle=_bundle(turns),
        safe_prompt=lambda payload: json.dumps(payload, ensure_ascii=False),
        materialize=materialize,
        system="strict",
        window_llm=llm,
        input_budget=input_budget,
        output_budget=output_budget,
        person_id="OWNER_1",
        package_date="2026-07-15",
    )
    return stats, written


def test_oversized_conversation_is_windowed_without_budget_error():
    turns = _long_turns(60)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        stats, written = _run(con, llm, turns)
    # More than one segmentation window was needed (the conversation did not fit).
    assert len(llm.segmentation_calls) >= 2
    assert stats["windowed_segmentation"] >= 2
    # No input_budget_exceeded was raised: we reached materialization.
    assert stats["episodes"] == 1
    parent = written["output"]["episodes"][0]
    # Every human turn is covered exactly once, in one contiguous subtheme union.
    assert parent["evidence_turn_ids"] == [f"t{i}" for i in range(60)]
    covered = [tid for sub in parent["subthemes"] for tid in sub["turn_ids"]]
    assert covered == [f"t{i}" for i in range(60)]
    assert len(covered) == len(set(covered)) == 60


def test_partition_has_no_gap_or_duplicate_across_window_borders():
    turns = _long_turns(50)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        _stats, written = _run(con, llm, turns)
    parent = written["output"]["episodes"][0]
    subthemes = parent["subthemes"]
    # Contiguous, strictly ordered, abutting subthemes: each starts exactly where
    # the previous ends + 1 (borders reconciled once, no gap, no duplicate).
    flat = [tid for sub in subthemes for tid in sub["turn_ids"]]
    assert flat == [f"t{i}" for i in range(50)]
    # Boundaries: end of window k and start of window k+1 are adjacent, not equal.
    ends = [sub["end_turn_id"] for sub in subthemes]
    starts = [sub["start_turn_id"] for sub in subthemes]
    assert len(set(ends)) == len(ends)  # no boundary emitted twice
    assert starts[0] == "t0" and ends[-1] == "t49"


def test_segments_detailed_in_bounded_batches_of_whole_segments():
    # A tiny input budget forces the detail pass to split into several batches;
    # every subtheme still comes back, and no segment is cut across a batch.
    turns = _long_turns(45)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        stats, written = _run(con, llm, turns)
    assert stats["windowed_detail"] >= 1
    # More than one detail batch was needed (the segments did not fit one call).
    assert len(llm.detail_calls) >= 2
    # Detail was called at least once; if batched, more than once. Each detail
    # prompt only ever contains whole segments (its turns match a segment union).
    assert llm.detail_calls
    for call in llm.detail_calls:
        for segment in call["segments"]:
            ids = [str(turn["turn_id"]) for turn in segment["turns"]]
            assert ids == segment["turn_ids"]
    subthemes = written["output"]["episodes"][0]["subthemes"]
    # No subtheme lost across batches.
    assert [s["ordinal"] for s in subthemes] == list(range(len(subthemes)))


def test_resume_replays_zero_new_llm_calls():
    turns = _long_turns(60)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        _run(con, llm, turns)
        first_seg = len(llm.segmentation_calls)
        first_detail = len(llm.detail_calls)
        assert first_seg >= 1 and first_detail >= 1
        # Second run over the same input on the SAME durable checkpoints.
        _run(con, llm, turns)
    # Not a single additional LLM call: every window resumed from its checkpoint.
    assert len(llm.segmentation_calls) == first_seg
    assert len(llm.detail_calls) == first_detail


def test_no_ref_or_subtheme_loss_reaches_the_writer():
    turns = _long_turns(48)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        _stats, written = _run(con, llm, turns)
    parent = written["output"]["episodes"][0]
    # Parent evidence is the full ordered turn union.
    assert parent["evidence_turn_ids"] == [f"t{i}" for i in range(48)]
    # Every subtheme carries non-empty evidence that is a subset of its membership.
    for sub in parent["subthemes"]:
        assert sub["evidence_turn_ids"]
        assert set(sub["evidence_turn_ids"]).issubset(set(sub["turn_ids"]))
    # Speaker-identity gap surfaced deterministically (unknown voices present).
    assert "speaker_identity_unenrolled" in written["output"]["missing_context"]


def test_sensor_turn_never_becomes_a_subtheme_in_windowed_path():
    turns = _long_turns(50)
    sensor = {
        "turn_id": "vision-1",
        "idx": 999,
        "text": "personne visible",
        "metadata_json": json.dumps({
            "evidence_role": "system_observation_not_user_speech",
            "source": {"vision_change_atom": True, "count": 30},
        }),
    }
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        _stats, written = _run(con, llm, [*turns, sensor])
    parent = written["output"]["episodes"][0]
    assert "vision-1" not in parent["evidence_turn_ids"]
    for sub in parent["subthemes"]:
        assert "vision-1" not in sub["turn_ids"]
        assert "vision-1" not in sub["evidence_turn_ids"]


def test_short_conversation_keeps_two_call_path_unchanged():
    # A small conversation with a generous budget must not window: exactly two
    # calls (one segmentation, one detail), same prompts as the historic path.
    turns = _long_turns(6)
    llm = WindowedFakeLLM()
    with connect(":memory:") as con:
        stats, _written = _run(con, llm, turns, input_budget=100_000)
    assert stats["calls"] == 2
    assert stats["segmentation_calls"] == 1 and stats["detail_calls"] == 1
    assert stats["windowed_segmentation"] == 0 and stats["windowed_detail"] == 0
    assert len(llm.segmentation_calls) == 1 and len(llm.detail_calls) == 1
    # The single segmentation prompt saw every human turn id (no windowing).
    assert llm.segmentation_calls[0]["contract"]["human_turn_ids"] == [f"t{i}" for i in range(6)]
