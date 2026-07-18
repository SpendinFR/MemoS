from __future__ import annotations

import json
import sqlite3


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE brain2_shared_fact_runs_v19(
          conversation_id TEXT, status TEXT
        );
        CREATE TABLE v13_engine_runs(
          engine_run_id TEXT PRIMARY KEY, engine_name TEXT, episode_id TEXT,
          conversation_id TEXT, person_id TEXT, status TEXT, finished_at TEXT
        );
        CREATE TABLE v13_engine_outputs(
          output_id TEXT PRIMARY KEY, engine_run_id TEXT, output_json TEXT,
          evidence_json TEXT, counter_evidence_json TEXT, confidence REAL,
          validation_status TEXT
        );
        """
    )


def _insert(
    con: sqlite3.Connection, engine: str, output: dict, *, index: int,
) -> None:
    run_id = f"run-{index}"
    con.execute(
        "INSERT INTO v13_engine_runs VALUES(?,?,?,?,?,?,?)",
        (
            run_id, engine, "episode-1", "conversation-1", "me",
            "completed", f"2026-07-18T00:00:0{index}Z",
        ),
    )
    con.execute(
        "INSERT INTO v13_engine_outputs VALUES(?,?,?,?,?,?,?)",
        (
            f"output-{index}", run_id, json.dumps(output), "[]", "[]",
            0.5, "valid",
        ),
    )


def test_compiler_reuses_strict_semantics_without_second_model_pass():
    from mlomega_audio_elite.v18_autonomous import (
        _compile_strict_autonomous_candidates,
    )

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute(
        "INSERT INTO brain2_shared_fact_runs_v19 VALUES('conversation-1','complete')"
    )
    _insert(con, "prediction_engine", {"predictions": [{
        "prediction_target": "next_action", "predicted_value": "confirmer le nom",
        "probability": 0.8, "confidence": 0.7, "why": ["t1"],
    }]}, index=1)
    _insert(con, "pattern_miner", {"candidate_patterns": [{
        "pattern_type": "social_verification", "pattern_key": "identity_check",
        "title": "Vérification répétée", "confidence": 0.6,
    }], "confirmed_patterns": []}, index=2)
    _insert(con, "outcome_tracker", {"open_loops": [{
        "item": "objet à réparer", "what_would_close_it": "nommer l'objet",
        "risk_if_unclosed": "contexte incomplet",
    }]}, index=3)

    out = _compile_strict_autonomous_candidates(
        con, conversation_id="conversation-1", person_id="me",
    )

    assert out is not None
    assert out["compiler"] == "strict_engine_outputs_v1"
    assert {item["insight_type"] for item in out["insights"]} == {
        "prediction", "hypothesis", "question_to_user",
    }
    assert all(item["why"] for item in out["insights"])
    assert "aucune réanalyse brute" in out["global_summary"]


def test_compiler_falls_back_only_when_strict_run_is_not_complete():
    from mlomega_audio_elite.v18_autonomous import (
        _compile_strict_autonomous_candidates,
    )

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    _schema(con)
    assert _compile_strict_autonomous_candidates(
        con, conversation_id="conversation-1", person_id="me",
    ) is None

    con.execute(
        "INSERT INTO brain2_shared_fact_runs_v19 VALUES('conversation-1','complete')"
    )
    out = _compile_strict_autonomous_candidates(
        con, conversation_id="conversation-1", person_id="me",
    )
    assert out is not None
    assert out["insights"] == []
