from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "services" / "live-pc"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


deferred = _load("test_e64i_deferred_fine_intel", "deferred_fine_intel.py")


class _LLM:
    def __init__(self, *, invalid: bool = False) -> None:
        self.calls = 0
        self.invalid = invalid

    def complete_json(self, _system, prompt, **_kwargs):
        self.calls += 1
        turns = json.loads(prompt)["turns"]
        out = []
        for item in turns:
            out.append(
                {
                    "turn_id": item["turn_id"],
                    "addressed": item["turn_id"].endswith("1"),
                    "name": "Max" if item["turn_id"].endswith("1") else "",
                    "addressee": "previous_speaker",
                    "address_confidence": 0.8,
                    "states_fact": item["turn_id"].endswith("2"),
                    "subject_hint": "table",
                    "attribute": "couleur",
                    "value": "bleue",
                    "fact_confidence": 0.7,
                }
            )
        if self.invalid:
            out.pop()
        return {"turns": out}


class _Hypotheses:
    def __init__(self) -> None:
        self.calls = []

    def apply_addressed_name_signal(self, signal, **kwargs):
        self.calls.append((signal, kwargs))


class _Attributes:
    def __init__(self) -> None:
        self.calls = []

    def apply_heard_fact(self, signal, **kwargs):
        self.calls.append((signal, kwargs))


def _batcher(db: Path, llm, hyp=None, attr=None, *, size=8):
    return deferred.DeferredFineIntel(
        person_id="me",
        live_session_id="live-1",
        db_path=db,
        llm=llm,
        hypothesis_engine=hyp or _Hypotheses(),
        attribute_memory=attr or _Attributes(),
        batch_size=size,
    )


def _enqueue(batch, count: int) -> None:
    for i in range(count):
        assert batch.enqueue_turn(
            turn_id=f"turn-{i}",
            text=f"phrase {i}",
            speaker_entity="speaker-a",
            present_person_entities=["person-b"],
            default_subject="salon",
        )


def test_nine_durable_turns_cost_two_bounded_calls_and_keep_all_ids(tmp_path):
    llm = _LLM()
    hyp, attr = _Hypotheses(), _Attributes()
    batch = _batcher(tmp_path / "memory.db", llm, hyp, attr)
    _enqueue(batch, 9)

    result = batch.process_pending()

    assert result["status"] == "completed"
    assert llm.calls == 2
    assert len(hyp.calls) == len(attr.calls) == 9
    assert {call[1]["evidence_ref"] for call in hyp.calls} == {
        f"brainlive_turn:turn-{i}" for i in range(9)
    }


def test_restart_reuses_extracted_json_without_repaying_model(tmp_path):
    db = tmp_path / "memory.db"
    first_llm = _LLM()
    first = _batcher(db, first_llm, size=4)
    _enqueue(first, 4)
    rows = first._load_rows("pending", 4, attempts_lt=3)
    first._extract_batch(rows)
    assert first_llm.calls == 1

    replay_llm = _LLM(invalid=True)
    replay = _batcher(db, replay_llm, size=4)
    result = replay.process_pending()

    assert result["status"] == "completed"
    assert replay_llm.calls == 0
    assert replay.metrics["reused_extractions"] == 4


def test_cardinality_mismatch_keeps_every_turn_pending_for_retry(tmp_path):
    batch = _batcher(tmp_path / "memory.db", _LLM(invalid=True), size=4)
    _enqueue(batch, 4)

    with pytest.raises(ValueError, match="cardinality"):
        batch.process_pending()

    assert batch.pending_count() == 4
    rows = batch._load_rows("pending", 4)
    assert {int(row["attempts"]) for row in rows} == {1}
    assert all(row["result_json"] is None for row in rows)
