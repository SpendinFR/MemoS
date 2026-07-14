from __future__ import annotations

import json
from pathlib import Path


def _fixture_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "shared-facts.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_E64_SHARED_FACTS", "1")

    from mlomega_audio_elite.brain2_conversation_episode import (
        CONVERSATION_EPISODE_BUILD_VERSION,
    )
    from mlomega_audio_elite.brain2_strict_v13_2 import ensure_strict_v13_schema
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.utils import now_iso

    ensure_strict_v13_schema()
    now = now_iso()
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO conversations(
                   conversation_id,title,started_at,channel,participants_json,
                   speaker_map_json,relationship_context_json,raw_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("conv-i2", "fixture", now, "phoneonly", "[]", "{}", "{}", "{}", now),
        )
        con.execute(
            """INSERT INTO turns(
                   turn_id,conversation_id,idx,speaker_label,person_id,start_s,end_s,
                   text,previous_turn_id,metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "t1", "conv-i2", 0, "SPEAKER_00", "UNKNOWN_VOICE_1", 0.0, 1.0,
                "J'ai rendez-vous demain.", None, "{}",
            ),
        )
        con.execute(
            """INSERT INTO episodes(
                   episode_id,episode_type,start_time,source_conversation_id,
                   start_turn_id,end_turn_id,participants_json,channel,topic,
                   situation_summary,confidence,truth_status,importance_score,
                   lifecycle_status,metadata_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "ep-i2", "conversation", now, "conv-i2", "t1", "t1",
                '["UNKNOWN_VOICE_1"]', "phoneonly", "rendez-vous",
                "Une conversation avec un projet de rendez-vous.", 0.8, "inferred",
                0.8, "active", json.dumps({
                    "episode_source": CONVERSATION_EPISODE_BUILD_VERSION,
                    "coverage_status": "complete",
                    "subtheme_types": ["planning"],
                }), now, now,
            ),
        )
        con.commit()
    return db_path


def test_shared_fact_roundtrip_capabilities_and_evidence(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import (
        compact_fact_bundle,
        finish_episode_fact_run,
        record_engine_not_applicable,
        record_engine_output,
    )
    from mlomega_audio_elite.db import connect

    context = {
        "situation": {
            "situation_type": "conversation", "life_domain": "personal",
            "participants": ["UNKNOWN_VOICE_1"], "main_person": "UNKNOWN_VOICE_1",
            "targets": ["rendez-vous"], "place_explicit": None,
            "place_inferred": None, "social_context": "informal",
            "power_balance": "unknown", "stakes": "low", "constraints": [],
        },
        "resolved_references": [], "missing_context": [],
        "evidence": ["t1"], "counter_evidence": [], "confidence": 0.8,
    }
    outcome = {
        "intention_outcome_links": [], "open_loops": [],
        "evidence": ["t1"], "counter_evidence": [], "confidence": 0.7,
    }
    with connect(db_path) as con:
        rebuilt = record_engine_output(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2",
            engine_name="context_resolver", output=context,
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="human_narrative_episode",
        )
        assert rebuilt == context
        record_engine_output(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2",
            engine_name="outcome_tracker", output=outcome,
            schema=ENGINE_SCHEMAS["outcome_tracker"],
            applicability_reason="episode_type_can_support_intention_or_outcome",
        )
        record_engine_not_applicable(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2",
            engine_name="internal_state_engine",
            schema=ENGINE_SCHEMAS["internal_state_engine"],
            reason="episode_type_has_state_evidence",
        )
        stats = finish_episode_fact_run(
            con, conversation_id="conv-i2", episode_id="ep-i2"
        )
        con.commit()

        assert stats["engines"] == 3
        assert stats["facts"] == 1
        assert con.execute(
            "SELECT evaluation_status FROM brain2_shared_capabilities_v19 "
            "WHERE engine_name='outcome_tracker' AND field_name='open_loops'"
        ).fetchone()[0] == "empty_valid"
        assert con.execute(
            "SELECT evaluation_status FROM brain2_shared_capabilities_v19 "
            "WHERE engine_name='internal_state_engine' AND field_name='state_before'"
        ).fetchone()[0] == "not_applicable"
        assert con.execute(
            "SELECT COUNT(*) FROM brain2_shared_fact_evidence_v19 WHERE turn_id='t1'"
        ).fetchone()[0] == 1
        bundle = compact_fact_bundle(con, "conv-i2")
        assert bundle["facts"][0]["fact_type"] == "situation"
        assert bundle["facts"][0]["subject_ref"] == "UNKNOWN_VOICE_1"
        assert bundle["facts"][0]["confidence_ceiling"] == 0.8


def test_v14_open_loop_reuses_complete_empty_v13_verdict(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import (
        can_reuse_empty_v14_open_loops,
        finish_episode_fact_run,
        record_engine_output,
    )
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite import people_openloops_v14_5 as v145

    with connect(db_path) as con:
        record_engine_output(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2",
            engine_name="outcome_tracker",
            output={
                "intention_outcome_links": [], "open_loops": [],
                "evidence": ["t1"], "counter_evidence": [], "confidence": 0.7,
            },
            schema=ENGINE_SCHEMAS["outcome_tracker"],
            applicability_reason="episode_type_can_support_intention_or_outcome",
        )
        finish_episode_fact_run(con, conversation_id="conv-i2", episode_id="ep-i2")
        con.commit()
        assert can_reuse_empty_v14_open_loops(con, "conv-i2") == (
            True, "v13_outcome_tracker_complete_empty"
        )

    def forbidden_llm(*_args, **_kwargs):
        raise AssertionError("V14 must reuse the validated empty V13 capability")

    monkeypatch.setattr(v145, "_llm_json", forbidden_llm)
    result = v145.track_personal_open_loops("conv-i2", person_id="me")
    assert result["status"] == "ok"
    assert result["new_or_updated_count"] == 0
    assert result["reused_shared_facts"] is True
    assert result["raw"]["shared_fact_reuse"]["source_engine"] == "outcome_tracker"


def test_open_loop_reuse_refuses_a_real_candidate(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import (
        can_reuse_empty_v14_open_loops,
        finish_episode_fact_run,
        record_engine_output,
    )
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        record_engine_output(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2",
            engine_name="outcome_tracker",
            output={
                "intention_outcome_links": [],
                "open_loops": [{
                    "item": "Confirmer le rendez-vous",
                    "what_would_close_it": "Une confirmation",
                    "risk_if_unclosed": "Rendez-vous manqué",
                }],
                "evidence": ["t1"], "counter_evidence": [], "confidence": 0.7,
            },
            schema=ENGINE_SCHEMAS["outcome_tracker"],
            applicability_reason="episode_type_can_support_intention_or_outcome",
        )
        finish_episode_fact_run(con, conversation_id="conv-i2", episode_id="ep-i2")
        con.commit()
        allowed, reason = can_reuse_empty_v14_open_loops(con, "conv-i2")
        assert allowed is False
        assert reason == "outcome_tracker_has_candidates_or_invalid"


def test_compact_stage_input_keeps_every_turn_and_structural_subtheme(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_shared_facts_v19 import (
        compact_stage_input,
        finish_episode_fact_run,
        record_episode_structure,
    )
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        # The fixture has no subtheme rows, but the complete parent remains a
        # first-class structural fact and the turn manifest is still lossless.
        record_episode_structure(
            con, person_id="me", conversation_id="conv-i2", episode_id="ep-i2"
        )
        finish_episode_fact_run(con, conversation_id="conv-i2", episode_id="ep-i2")
        projection = compact_stage_input(
            con, "conv-i2", person_id="me", purpose="people_identity"
        )
        con.commit()

        assert projection["lossless_turn_manifest"] == {
            "source_count": 1, "included_count": 1, "omitted_turn_ids": [],
        }
        assert projection["turns"][0]["text"] == "J'ai rendez-vous demain."
        assert projection["conversation_outline"]["parent"]["episode_id"] == "ep-i2"


def test_orchestrator_projects_identity_and_restores_turn_ids(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        project_stage_payload,
        restore_stage_output,
    )

    with connect(db_path) as con:
        projection = project_stage_payload(
            stage_name="v14_people_identity",
            person_id="me",
            source_ref="conv-i2",
            payload={"mission": "identity", "conversation_data": {"raw": True}},
            connection=con,
        )
        con.commit()
    assert projection.applied is True
    projected = projection.payload["conversation_data"]
    assert projected["projection_version"].startswith("e64-i2")
    assert projected["lossless_turn_manifest"]["omitted_turn_ids"] == []
    assert projection.payload["background"]["included_in_conversation_data"] is True
    assert projected["turns"][0]["turn_id"] == "t0"
    restored = restore_stage_output(
        {"speaker_identity_hypotheses": [{"evidence_turn_ids": ["t0"]}]},
        projection,
    )
    assert restored["speaker_identity_hypotheses"][0]["evidence_turn_ids"] == ["t1"]
