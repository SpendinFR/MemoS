"""2.1-B — PRO close-day routes ALL segmentation through the lossless executor.

The single-call segmentation path is not lossless by construction: it needs the
model to emit an ``end`` boundary on the LAST turn, and the 9B used on the PRO
close-day sometimes stops before the tail fillers (Gate B 20260720-014448 →
``segmentation_not_lossless``). The windowed path forces the last segment onto
each window's last primary turn, so PRO routes through it even when the whole
input would fit one call, inheriting the executor's audited rejection, no-
identical-retry, contiguous split→merge and lossless coverage — reusing the
executor, never a second single-call hack.

All fakes, in-memory SQLite; no business prompt change, no real model.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from mlomega_audio_elite.brain2_conversation_episode import (
    ConversationEpisodeContractError,
    SEGMENTATION_STAGE_NAME,
    _SEGMENTATION_MISSION,
    _DETAIL_MISSION,
    build_conversation_episode_v6,
)
from mlomega_audio_elite.night_orchestrator import checkpoint_store as cp
from mlomega_audio_elite.night_orchestrator.executor import LLMCallResult

pytestmark = pytest.mark.memory


@contextmanager
def connect():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


# A 137-turn conversation mixing substantial turns and short fillers — the exact
# structural shape of the Groq-fed PRO run (69 conversational turns + fillers;
# here scaled to 137 to also exceed a single target-turns window).
_FILLERS = ["Ouais.", "Hein ?", "Ok.", "Mm.", "Bah.", "Voilà.", "Ah ouais ?"]
_LONG = "On reparle du rendez-vous et du metier avec quelques details concrets ici."


def _turns_with_fillers(count: int) -> list[dict[str, object]]:
    turns = []
    for index in range(count):
        # Every 3rd turn is a short filler; the rest are substantial.
        is_filler = index % 3 == 2
        text = _FILLERS[index % len(_FILLERS)] if is_filler else f"Tour {index}: {_LONG}"
        turns.append({
            "turn_id": f"t{index}",
            "idx": index,
            "speaker_label": "SPEAKER_00" if index % 2 else "SPEAKER_01",
            "person_id": "UNKNOWN_VOICE_001" if index % 2 else "UNKNOWN_VOICE_002",
            "start_s": float(index),
            "end_s": float(index) + 0.4,
            "text": text,
            "metadata_json": json.dumps({
                "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript",
                "source": {"word_alignment": {"count": 8, "mean_score": 0.82}},
            }),
        })
    return turns


def _bundle(turns: list[dict[str, object]]) -> dict[str, object]:
    return {
        "conversation": {
            "conversation_id": "convPRO",
            "channel": "phoneonly",
            "person_id": "OWNER_1",
            "started_at": "2026-07-20T10:00:00",
        },
        "turns": turns,
        "source_spans": [],
    }


def _detail_subthemes(prompt: dict) -> dict:
    subthemes = []
    for segment in prompt["segments"]:
        turn_ids = [str(turn["turn_id"]) for turn in segment["turns"]]
        subthemes.append({
            "ordinal": int(segment["ordinal"]),
            "subtheme_type": "other",
            "title": f"Detail {segment['ordinal']}",
            "summary": f"Resume ({turn_ids[0]}..{turn_ids[-1]}).",
            "participants": ["UNKNOWN_VOICE_001"],
            "evidence_turn_ids": turn_ids,
            "outcome": None,
            "unresolved_tension": None,
            "confidence": 0.7,
        })
    return {
        "conversation_episode": {
            "title": "Conversation PRO",
            "situation_summary": "Une conversation multi-sujets avec fillers.",
            "participants": ["UNKNOWN_VOICE_001", "UNKNOWN_VOICE_002"],
            "location": None,
            "channel": "phoneonly",
            "confidence": 0.75,
            "subthemes": subthemes,
        },
        "missing_context": [],
    }


class SegFake:
    """Per-window segmentation responder with a configurable tail behaviour.

    ``tail='full'`` ends each window's segment on its last primary turn (lossless
    even single-call). ``tail='early'`` ends on the SECOND-TO-LAST primary,
    mimicking the 9B dropping trailing fillers: single-call trips
    ``segmentation_not_lossless``; the windowed path forces the edge → lossless.
    """

    model = "seg-fake-p1"

    def __init__(self, *, tail: str = "full") -> None:
        self.tail = tail
        self.segmentation_calls = 0
        self.detail_calls = 0

    def generate(self, payload, *, output_budget):
        prompt = json.loads(payload["prompt"]) if isinstance(payload.get("prompt"), str) else payload
        mission = prompt.get("mission")
        if mission == _SEGMENTATION_MISSION:
            self.segmentation_calls += 1
            primary = list(prompt["contract"]["human_turn_ids"])
            # Cut every ~3 primary turns so detail batches stay small (a lone
            # 50-turn segment would blow the detail budget). Mirrors the proven
            # WindowedFakeLLM. ``tail='early'`` omits the final forced cut, so the
            # last real boundary lands BEFORE the window's last primary — the exact
            # 9B tail-drop the forced window edge must recover.
            cuts = [primary[offset] for offset in range(2, len(primary), 3)]
            if self.tail != "early" and (not cuts or cuts[-1] != primary[-1]):
                cuts.append(primary[-1])
            if not cuts:
                cuts = [primary[-1]] if self.tail != "early" else [primary[0]]
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
            self.detail_calls += 1
            return LLMCallResult(ok=True, data=_detail_subthemes(prompt))
        raise AssertionError(f"unexpected mission: {mission}")


class RejectWholeAcceptHalvesSeg:
    """Rejects a window with >=4 primary turns (emits an end OUTSIDE its primary
    range → normalize returns None → contract rejection), accepts smaller halves.
    Proves the executor's contiguous split→merge lossless recovery on segmentation.
    """

    model = "seg-fake-reject"

    def __init__(self) -> None:
        self.segmentation_calls = 0
        self.detail_calls = 0

    def generate(self, payload, *, output_budget):
        prompt = json.loads(payload["prompt"]) if isinstance(payload.get("prompt"), str) else payload
        mission = prompt.get("mission")
        if mission == _SEGMENTATION_MISSION:
            self.segmentation_calls += 1
            primary = list(prompt["contract"]["human_turn_ids"])
            context_only = list(prompt["contract"]["context_only_turn_ids"])
            if len(primary) >= 4 and context_only:
                # Malformed: an end on a context-only (non-primary) turn.
                return LLMCallResult(ok=True, data={
                    "segments": [{
                        "ordinal": 0, "title_hint": "bad",
                        "end_turn_id": context_only[0],
                        "boundary_reason": "new_goal",
                    }],
                    "missing_context": [],
                })
            return LLMCallResult(ok=True, data={
                "segments": [{
                    "ordinal": 0, "title_hint": f"Bloc {primary[-1]}",
                    "end_turn_id": primary[-1],
                    "boundary_reason": "conversation_start",
                }],
                "missing_context": [],
            })
        if mission == _DETAIL_MISSION:
            self.detail_calls += 1
            return LLMCallResult(ok=True, data=_detail_subthemes(prompt))
        raise AssertionError(f"unexpected mission: {mission}")


class RaisingLLM:
    # Same model label as the first run: the checkpoint key includes the model,
    # so a resume with a different label would (wrongly) miss the checkpoints.
    model = "seg-fake-p1"

    def generate(self, payload, *, output_budget):
        raise AssertionError("resume must not repay any LLM call")


def _run(con, llm, turns, *, input_budget, output_budget=512):
    written = {}

    def materialize(_con, _conversation_id, output):
        written["output"] = output
        return len(output["episodes"])

    stats = build_conversation_episode_v6(
        con, "convPRO",
        bundle=_bundle(turns),
        safe_prompt=lambda payload: json.dumps(payload, ensure_ascii=False),
        materialize=materialize,
        system="strict",
        window_llm=llm,
        input_budget=input_budget,
        output_budget=output_budget,
        person_id="OWNER_1",
        package_date="2026-07-20",
    )
    return stats, written


def _covered_turn_ids(written) -> list[str]:
    parent = written["output"]["episodes"][0]
    return [tid for sub in parent["subthemes"] for tid in sub["turn_ids"]]


# --------------------------------------------------------------------------- #
# 1. PRO forces the windowed executor even when the whole input FITS one call. #
# --------------------------------------------------------------------------- #
def test_pro_forces_windowed_segmentation_even_when_input_fits(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    turns = _turns_with_fillers(137)
    llm = SegFake(tail="full")
    # A budget large enough that the WHOLE conversation fits one call: without the
    # PRO flag this would take the single-call path. PRO must still window.
    with connect() as con:
        stats, written = _run(con, llm, turns, input_budget=1_000_000)
    assert stats["windowed_segmentation"] >= 2         # windowed, not single-call
    assert llm.segmentation_calls >= 2                 # one call per window
    covered = _covered_turn_ids(written)
    assert covered == [f"t{i}" for i in range(137)]    # lossless, exact order
    assert len(covered) == len(set(covered)) == 137


# --------------------------------------------------------------------------- #
# 2. An incomplete root (9B stops before the tail) is lossless in PRO windows, #
#    while the SAME output trips segmentation_not_lossless single-call.        #
# --------------------------------------------------------------------------- #
def test_incomplete_tail_is_lossless_in_pro_windowed():
    turns = _turns_with_fillers(50)
    # No PRO flag + a budget that fits everything → single-call path. The fake
    # stops before the last turn → the global normalizer rejects it as not lossless.
    with connect() as con:
        with pytest.raises(ConversationEpisodeContractError, match="segmentation_not_lossless"):
            _run(con, SegFake(tail="early"), turns, input_budget=1_000_000)


def test_incomplete_tail_recovered_by_forced_window_edge(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    turns = _turns_with_fillers(50)
    llm = SegFake(tail="early")   # every window stops before its last filler
    with connect() as con:
        _stats, written = _run(con, llm, turns, input_budget=1_000_000)
    covered = _covered_turn_ids(written)
    # The forced window edge recovers every dropped tail filler: still lossless.
    assert covered == [f"t{i}" for i in range(50)]
    assert len(covered) == len(set(covered)) == 50


# --------------------------------------------------------------------------- #
# 3. A contract rejection splits the window contiguously, merges, stays        #
#    lossless — reusing the executor's own subdivide, no reimplemented scale.   #
# --------------------------------------------------------------------------- #
def test_contract_rejection_splits_and_merges_lossless(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_E64_CONVERSATION_TARGET_TURNS", "4")
    monkeypatch.setenv("MLOMEGA_E64_CONVERSATION_OVERLAP", "2")
    turns = _turns_with_fillers(16)
    llm = RejectWholeAcceptHalvesSeg()
    with connect() as con:
        _stats, written = _run(con, llm, turns, input_budget=1_000_000)
        covered = _covered_turn_ids(written)
        assert covered == [f"t{i}" for i in range(16)]   # lossless after split/merge
        assert len(covered) == len(set(covered)) == 16
        # A subdivided parent exists among the segmentation windows.
        states = dict(con.execute(
            "SELECT state, COUNT(*) FROM night_llm_windows_v19 "
            "WHERE stage_name=? GROUP BY state", (SEGMENTATION_STAGE_NAME,),
        ).fetchall())
        assert states.get("subdivided", 0) >= 1
        assert states.get("quarantined", 0) == 0


# --------------------------------------------------------------------------- #
# 4 + 5. No filler lost or invented; the raw rejection is audited durably.      #
# --------------------------------------------------------------------------- #
def test_no_filler_lost_or_invented_and_rejection_audited(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_E64_CONVERSATION_TARGET_TURNS", "4")
    monkeypatch.setenv("MLOMEGA_E64_CONVERSATION_OVERLAP", "2")
    turns = _turns_with_fillers(16)
    source_ids = {f"t{i}" for i in range(16)}
    with connect() as con:
        _stats, written = _run(con, llm := RejectWholeAcceptHalvesSeg(), turns, input_budget=1_000_000)
        covered = set(_covered_turn_ids(written))
        assert covered == source_ids                     # nothing lost, nothing invented
        has_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (cp.REJECTIONS_TABLE,)
        ).fetchone()
        rows = con.execute(
            f"SELECT violations_json, raw_output, input_digest, output_digest "
            f"FROM {cp.REJECTIONS_TABLE} WHERE stage_name=?",
            (SEGMENTATION_STAGE_NAME,),
        ).fetchall() if has_table else []
        assert rows, "at least one segmentation rejection persisted"
        # The exact violation rule + the raw model output + digests are audited.
        assert any("segmentation_window" in str(r[0]) for r in rows)
        assert all(r[1] and r[2] and r[3] for r in rows)


# --------------------------------------------------------------------------- #
# 6. Resume replays zero LLM calls (durable checkpoints).                       #
# --------------------------------------------------------------------------- #
def test_resume_replays_zero_llm_calls(monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    turns = _turns_with_fillers(50)
    # A tight budget windows BOTH passes (segmentation + detail) so every model
    # call is durably checkpointed; the resume must then repay nothing at all.
    with connect() as con:
        _s1, w1 = _run(con, SegFake(tail="full"), turns, input_budget=2500)
        first = _covered_turn_ids(w1)
        assert _s1["windowed_segmentation"] >= 2 and _s1["windowed_detail"] >= 1
        _s2, w2 = _run(con, RaisingLLM(), turns, input_budget=2500)
        assert _covered_turn_ids(w2) == first == [f"t{i}" for i in range(50)]


# --------------------------------------------------------------------------- #
# 7. Without the PRO flag the historic single-call path is unchanged.          #
# --------------------------------------------------------------------------- #
def test_without_pro_flag_single_call_path_unchanged(monkeypatch):
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    turns = _turns_with_fillers(50)
    llm = SegFake(tail="full")
    with connect() as con:
        stats, written = _run(con, llm, turns, input_budget=1_000_000)
    # Single call, no windowing: exactly the historic behaviour.
    assert stats["windowed_segmentation"] == 0
    assert llm.segmentation_calls == 1
    covered = _covered_turn_ids(written)
    assert covered == [f"t{i}" for i in range(50)]
