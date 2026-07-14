from __future__ import annotations

import pytest


def test_completed_people_and_open_loop_contracts_are_reused(tmp_path, monkeypatch):
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.people_openloops_v14_5 import (
        IDENTITY_SCHEMA,
        OPEN_LOOP_SCHEMA,
        analyze_people_identity_hypotheses,
        ensure_v14_5_schema,
        track_personal_open_loops,
    )
    from mlomega_audio_elite.utils import json_dumps

    db_path = tmp_path / "people-resume.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    ensure_v14_5_schema()
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO v14_5_people_identity_runs(
                   run_id,conversation_id,person_id,status,error_text,
                   qwen_output_json,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                "people-ok",
                "conversation-immutable",
                "me",
                "ok",
                None,
                json_dumps(IDENTITY_SCHEMA),
                "2026-07-14T00:00:00Z",
            ),
        )
        con.execute(
            """INSERT INTO v14_5_open_loop_runs(
                   run_id,conversation_id,person_id,status,error_text,
                   new_or_updated_count,qwen_output_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                "loops-ok",
                "conversation-immutable",
                "me",
                "ok",
                None,
                3,
                json_dumps(OPEN_LOOP_SCHEMA),
                "2026-07-14T00:00:00Z",
            ),
        )
        con.commit()

    people = analyze_people_identity_hypotheses(
        "conversation-immutable", person_id="me"
    )
    loops = track_personal_open_loops("conversation-immutable", person_id="me")

    assert people["status"] == "ok" and people["resumed"] is True
    assert people["run_id"] == "people-ok"
    assert loops["status"] == "ok" and loops["resumed"] is True
    assert loops["run_id"] == "loops-ok"
    assert loops["new_or_updated_count"] == 3


def test_brain2_step_never_checkpoints_embedded_error_as_completed(tmp_path, monkeypatch):
    from mlomega_audio_elite.brain2_flow_v13_3 import _record_brain2_step
    from mlomega_audio_elite.db import connect

    db_path = tmp_path / "step-status.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    kwargs = {
        "pipeline_run_id": "pipeline",
        "conversation_id": "conversation",
        "step_name": "v14_interpersonal",
    }

    with pytest.raises(RuntimeError, match="returned status=error"):
        _record_brain2_step(
            **kwargs, fn=lambda: {"status": "error", "error": "length"}
        )
    with connect(db_path) as con:
        row = con.execute(
            "SELECT status FROM brain2_conversation_step_runs_v187"
        ).fetchone()
    assert row["status"] == "blocked"

    completed = _record_brain2_step(**kwargs, fn=lambda: {"status": "ok"})
    assert completed["status"] == "completed"

    # The valid cached checkpoint is reused; the function must not run again.
    reused = _record_brain2_step(
        **kwargs, fn=lambda: (_ for _ in ()).throw(AssertionError("reran"))
    )
    assert reused["status"] == "skipped_checkpoint"


def test_brain2_step_rejects_known_nested_engine_error(tmp_path, monkeypatch):
    from mlomega_audio_elite.brain2_flow_v13_3 import _record_brain2_step

    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "nested-step-status.db"))
    with pytest.raises(RuntimeError, match="inbox:error"):
        _record_brain2_step(
            pipeline_run_id="pipeline",
            conversation_id="conversation",
            step_name="v14_clarifications",
            fn=lambda: {"inbox": {"status": "error", "error": "length"}, "export": {}},
        )


def test_interpersonal_contract_delegates_disjoint_responsibilities_to_orchestrator(monkeypatch):
    from mlomega_audio_elite import interpersonal_state_v14_6 as module
    from mlomega_audio_elite.night_orchestrator.hierarchical_json import (
        _schema_responsibility_parts,
    )

    calls = []

    def fake_llm(system, payload, schema, timeout, *, stage_context):
        calls.append((stage_context["stage_name"], tuple(schema)))
        return {key: value for key, value in schema.items()}

    monkeypatch.setattr(module, "_llm_json", fake_llm)
    result = module._run_interpersonal_contract(
        {"conversation_payload": {"turns": []}},
        person_id="me",
        conversation_id="conversation",
        package_date="2026-07-14",
    )

    # The business adapter makes one full-contract delegation.  The shared
    # orchestrator, not this module, owns the two output responsibilities.
    assert len(calls) == 1
    assert set(calls[0][1]) == set(module.INTERPERSONAL_SCHEMA)
    parts = _schema_responsibility_parts(
        module.INTERPERSONAL_SCHEMA, stage_name="v14_interpersonal_state"
    )
    assert len(parts) == 2
    assert set(parts[0]).isdisjoint(parts[1])
    assert set(parts[0]) | set(parts[1]) == set(module.INTERPERSONAL_SCHEMA)
    assert set(result) == set(module.INTERPERSONAL_SCHEMA)


def test_interpersonal_writer_projection_normalizes_structured_text_without_fake_id():
    from mlomega_audio_elite import interpersonal_state_v14_6 as module

    value = {key: item for key, item in module.INTERPERSONAL_SCHEMA.items()}
    value["other_person_state_snapshots"] = [{
        "known_person_id": {"status": "unknown"},
        "person_hint": {"label": "speaker A"},
        "moment_state_summary": {"hypothesis": "guarded"},
        "evidence_turn_ids": {"turn_id": "turn-1"},
        "confidence": "0.8",
    }]

    normalized = module._normalize_interpersonal_contract(value)
    snapshot = normalized["other_person_state_snapshots"][0]

    assert snapshot["known_person_id"] is None
    assert isinstance(snapshot["person_hint"], str)
    assert isinstance(snapshot["moment_state_summary"], str)
    assert snapshot["evidence_turn_ids"] == [{"turn_id": "turn-1"}]
    assert snapshot["confidence"] == 0.8


def test_people_writer_projection_normalizes_structured_text_without_fake_id():
    from mlomega_audio_elite.people_openloops_v14_5 import IDENTITY_SCHEMA
    from mlomega_audio_elite.night_orchestrator.contract_normalization import (
        normalize_contract_output,
    )

    normalized = normalize_contract_output({
        "speaker_identity_hypotheses": [],
        "relationship_inferences": [],
        "people_context_profiles": [{
            "person_hint": {"label": "speaker A"},
            "known_person_id": {"status": "unknown"},
            "speaker_label": {"value": "UNKNOWN_VOICE_001"},
            "what_you_often_talk_about": {"topic": "project"},
            "confidence": "0.7",
        }],
        "missing_context": [],
        "confidence": 0.5,
    }, IDENTITY_SCHEMA)

    profile = normalized["people_context_profiles"][0]
    assert isinstance(profile["person_hint"], str)
    assert profile["known_person_id"] is None
    assert isinstance(profile["speaker_label"], str)
    assert profile["what_you_often_talk_about"] == [{"topic": "project"}]
    assert profile["confidence"] == 0.7


def test_opt_in_lossless_array_merge_preserves_distinct_findings():
    import sqlite3
    from mlomega_audio_elite.llm import LLMResult
    from mlomega_audio_elite.night_orchestrator import run_hierarchical_json

    class Client:
        model = "fake-lossless-union"

        def __init__(self):
            self.calls = 0

        def generate_json(self, system, prompt, schema_hint, timeout, **kwargs):
            self.calls += 1
            return LLMResult(
                ok=True,
                data={
                    "items": [{"finding": self.calls % 2}],
                    "confidence": 0.4 + (0.2 * (self.calls % 2)),
                },
                finish_reason="stop",
            )

    client = Client()
    result = run_hierarchical_json(
        stage_name="lossless_union",
        person_id="me",
        package_date="2026-07-14",
        source_ref="fixture",
        system="system",
        payload={
            "mission": "analyse",
            "evidence": [{"id": i, "text": "x" * 1000} for i in range(24)],
        },
        schema={"items": [], "confidence": 0.0},
        timeout=10,
        client=client,
        context_window=4096,
        output_budget=512,
        connection=sqlite3.connect(":memory:"),
        lossless_array_merge=True,
    )

    assert client.calls > 1
    assert result["items"] == [{"finding": 1}, {"finding": 0}]
    assert 0.4 <= result["confidence"] <= 0.6
