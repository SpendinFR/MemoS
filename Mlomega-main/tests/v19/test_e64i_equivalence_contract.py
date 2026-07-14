from __future__ import annotations

import json
import sqlite3


def test_r3_matrix_covers_every_schema_responsibility_and_real_consumer():
    from mlomega_audio_elite.night_orchestrator.equivalence_contract import (
        validate_equivalence_contract,
    )

    result = validate_equivalence_contract()
    assert result["responsibility_count"] == 18
    assert result["failures"] == []
    assert result["ready"] is True


def _seed_v14_contract_db(path, *, confidence: float, exact_refs: bool) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE v14_5_people_context_profiles(
          profile_id TEXT PRIMARY KEY, person_id TEXT, known_person_id TEXT,
          evidence_count INTEGER, confidence REAL
        );
        CREATE TABLE v14_6_relationship_state_models(
          model_id TEXT PRIMARY KEY, person_id TEXT, person_hint TEXT,
          known_person_id TEXT, evidence_json TEXT, confidence REAL
        );
        CREATE TABLE v14_6_interpersonal_loop_cards(
          loop_id TEXT PRIMARY KEY, person_id TEXT, person_hint TEXT,
          evidence_json TEXT, confidence REAL
        );
        CREATE TABLE v14_6_interpersonal_runs(
          run_id TEXT PRIMARY KEY, person_id TEXT, status TEXT,
          qwen_output_json TEXT, created_at TEXT
        );
        """
    )
    refs = json.dumps([{"turn_ref": "turn-1"}] if exact_refs else [{"text": "claim"}])
    con.execute(
        "INSERT INTO v14_5_people_context_profiles VALUES(?,?,?,?,?)",
        ("profile", "me", None, 2, 0.5),
    )
    con.execute(
        "INSERT INTO v14_6_relationship_state_models VALUES(?,?,?,?,?,?)",
        ("model", "me", "speaker", None, refs, confidence),
    )
    con.execute(
        "INSERT INTO v14_6_interpersonal_loop_cards VALUES(?,?,?,?,?)",
        ("loop", "me", "speaker", refs, confidence),
    )
    from mlomega_audio_elite.interpersonal_state_v14_6 import INTERPERSONAL_SCHEMA
    con.execute(
        "INSERT INTO v14_6_interpersonal_runs VALUES(?,?,?,?,?)",
        ("run", "me", "ok", json.dumps(INTERPERSONAL_SCHEMA), "2026-07-15T00:00:00Z"),
    )
    con.commit()
    con.close()


def test_r3_clone_comparison_rejects_unresolved_overconfidence(tmp_path):
    from mlomega_audio_elite.night_orchestrator.equivalence_contract import (
        compare_v14_clones,
    )

    baseline = tmp_path / "baseline.db"
    shadow = tmp_path / "shadow.db"
    _seed_v14_contract_db(baseline, confidence=0.6, exact_refs=True)
    _seed_v14_contract_db(shadow, confidence=0.9, exact_refs=True)

    result = compare_v14_clones(baseline, shadow)
    assert result["ready"] is False
    assert {item["kind"] for item in result["regressions"]} == {
        "unresolved_person_overconfidence"
    }


def test_r3_clone_comparison_accepts_full_schema_proof_and_prudence(tmp_path):
    from mlomega_audio_elite.night_orchestrator.equivalence_contract import (
        compare_v14_clones,
    )

    baseline = tmp_path / "baseline.db"
    shadow = tmp_path / "shadow.db"
    _seed_v14_contract_db(baseline, confidence=0.6, exact_refs=True)
    _seed_v14_contract_db(shadow, confidence=0.6, exact_refs=True)

    result = compare_v14_clones(baseline, shadow)
    assert result["ready"] is True
    assert result["regressions"] == []


def test_v14_writer_caps_single_conversation_hypotheses_without_dropping_content(
    tmp_path, monkeypatch,
):
    from mlomega_audio_elite import interpersonal_state_v14_6 as module
    from mlomega_audio_elite.db import connect

    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "v14-prudence.db"))
    monkeypatch.setattr(module, "_conversation_payload", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module, "_background", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module, "_run_interpersonal_contract", lambda *_args, **_kwargs: {
        **{key: [] for key, value in module.INTERPERSONAL_SCHEMA.items() if isinstance(value, list)},
        "relationship_state_models": [{
            "person_hint": "UNKNOWN_VOICE_002",
            "known_person_id": None,
            "relationship_state_summary": "useful but provisional detail",
            "evidence": [{"turn_ref": "turn-1"}],
            "counter_evidence": [{"kind": "identity_unresolved"}],
            "confidence": 0.95,
        }],
        "interpersonal_loops": [{
            "person_hint": "UNKNOWN_VOICE_002",
            "loop_title": "provisional loop",
            "evidence": [{"turn_ref": "turn-1"}],
            "confidence": 0.9,
        }],
        "confidence": 0.95,
    })

    result = module.analyze_interpersonal_state("conversation-1", person_id="me")
    assert result["status"] == "ok"
    with connect() as con:
        model = con.execute(
            "SELECT relationship_state_summary,confidence FROM v14_6_relationship_state_models"
        ).fetchone()
        loop = con.execute(
            "SELECT loop_title,confidence FROM v14_6_interpersonal_loop_cards"
        ).fetchone()
    assert model["relationship_state_summary"] == "useful but provisional detail"
    assert model["confidence"] == 0.65
    assert loop["loop_title"] == "provisional loop"
    assert loop["confidence"] == 0.65


def test_r3_runtime_proof_reads_compiled_writers_and_exact_sources(tmp_path):
    from mlomega_audio_elite.brainlive_brain2_coordination_v15_12 import DAY_PACKAGE_SCHEMA
    from mlomega_audio_elite.night_orchestrator.equivalence_contract import (
        audit_r3_runtime_evidence,
    )

    coordination = tmp_path / "coordination.db"
    con = sqlite3.connect(coordination)
    con.executescript(
        """
        CREATE TABLE brainlive_day_packages(
          package_id TEXT PRIMARY KEY,person_id TEXT,status TEXT,llm_summary_json TEXT,created_at TEXT
        );
        CREATE TABLE predictions(prediction_id TEXT PRIMARY KEY);
        CREATE TABLE brain2_live_watch_bindings(
          binding_id TEXT PRIMARY KEY,person_id TEXT,source_table TEXT,source_id TEXT,status TEXT
        );
        CREATE TABLE brain2_brainlive_coordination_runs(
          run_id TEXT PRIMARY KEY,person_id TEXT,status TEXT,counts_json TEXT,finished_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO brainlive_day_packages VALUES(?,?,?,?,?)",
        ("package", "me", "compiled_ready", json.dumps(DAY_PACKAGE_SCHEMA), "2026-07-15T00:00:00Z"),
    )
    con.execute("INSERT INTO predictions VALUES(?)", ("prediction",))
    con.execute(
        "INSERT INTO brain2_live_watch_bindings VALUES(?,?,?,?,?)",
        ("binding", "me", "predictions", "prediction", "active"),
    )
    con.execute(
        "INSERT INTO brain2_brainlive_coordination_runs VALUES(?,?,?,?,?)",
        ("run", "me", "ok", json.dumps({"reconciliations_created": 0}), "2026-07-15T00:01:00Z"),
    )
    con.commit()
    con.close()

    life = tmp_path / "life.db"
    con = sqlite3.connect(life)
    con.executescript(
        """
        CREATE TABLE action_outcomes(outcome_id TEXT PRIMARY KEY);
        CREATE TABLE brain2_life_model_consumed_sources(
          person_id TEXT,source_table TEXT,source_id TEXT
        );
        CREATE TABLE brain2_life_model_checkpoints(
          checkpoint_id TEXT PRIMARY KEY,person_id TEXT,source_count INTEGER,committed_at TEXT
        );
        CREATE TABLE brain2_life_model_watch_candidates(
          watch_id TEXT PRIMARY KEY,person_id TEXT,status TEXT,
          occurrence_count INTEGER,independent_count INTEGER
        );
        """
    )
    con.execute("INSERT INTO action_outcomes VALUES(?)", ("outcome",))
    con.execute(
        "INSERT INTO brain2_life_model_consumed_sources VALUES(?,?,?)",
        ("me", "action_outcomes", "outcome"),
    )
    con.execute(
        "INSERT INTO brain2_life_model_checkpoints VALUES(?,?,?,?)",
        ("first", "me", 1, "2026-07-15T00:00:00Z"),
    )
    con.execute(
        "INSERT INTO brain2_life_model_checkpoints VALUES(?,?,?,?)",
        ("replay", "me", 0, "2026-07-15T00:01:00Z"),
    )
    con.execute(
        "INSERT INTO brain2_life_model_watch_candidates VALUES(?,?,?,?,?)",
        ("watch", "me", "watching", 1, 1),
    )
    con.commit()
    con.close()

    result = audit_r3_runtime_evidence(coordination, life)
    assert result["ready"] is True
    assert result["coordination"]["invalid_binding_count"] == 0
    assert result["life"]["positive_checkpoint_sources"] == 1
    assert result["life"]["replay_source_count"] == 0
