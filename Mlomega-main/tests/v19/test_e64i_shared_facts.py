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


def test_orchestrator_replaces_legacy_autonomy_and_mirror_bundles(tmp_path, monkeypatch):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        project_stage_payload,
    )

    with connect(db_path) as con:
        for stage_name, purpose in (
            ("v18_autonomous_candidates", "autonomous_candidates"),
            ("v14_pattern_mirror", "pattern_mirror"),
        ):
            projection = project_stage_payload(
                stage_name=stage_name,
                person_id="me",
                source_ref="conv-i2",
                payload={"mission": stage_name, "bundle": {"legacy_raw": True}},
                connection=con,
            )
            assert projection.applied is True
            assert projection.purpose == purpose
            assert projection.payload["bundle"]["lossless_turn_manifest"] == {
                "source_count": 1, "included_count": 1, "omitted_turn_ids": [],
            }
            assert projection.payload["bundle"]["turns"][0]["turn_id"] == "t0"
            assert projection.payload["canonical_projection"]["raw_bundle_replaced"] is True


def test_pattern_mirror_first_conversation_is_an_honest_zero_call_gate(tmp_path, monkeypatch):
    _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite import pattern_mirror_v14 as mirror

    monkeypatch.setattr(
        mirror, "_llm_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("one conversation cannot prove a long-horizon pattern")
        ),
    )
    result = mirror.run_pattern_mirror(
        "conv-i2", person_id="me", trigger_type="test",
        scope="post_conversation_long_horizon",
    )

    assert result["status"] == "ok"
    assert result["llm_calls"] == 0
    assert result["gate"] == "insufficient_independent_conversations_for_long_horizon"
    assert result["raw"]["missing_context"] == [
        "insufficient_independent_conversations_for_long_horizon"
    ]


def test_all_generic_product_stages_declare_their_input_policy():
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        stage_input_policy,
    )

    expected = {
        "v13_subtopics": "canonical_projection",
        "v13_latent_outcomes": "canonical_projection",
        "v13_autonomous_insights": "canonical_projection",
        "v18_latent_outcomes": "canonical_projection",
        "v18_autonomous_candidates": "canonical_projection",
        "v14_people_identity": "canonical_projection",
        "v14_people_open_loops": "canonical_projection",
        "v14_interpersonal_state": "canonical_projection",
        "v14_pattern_mirror": "canonical_projection",
        "v14_proactive_interventions": "canonical_projection",
        "v14_clarification_inbox": "bounded_candidate_input",
        "v14_periodic_mirror_day": "canonical_daily_projection",
        "life_model_bootstrap": "canonical_projection",
        "life_model_patch": "canonical_projection",
        "coordination_day_package": "canonical_projection",
        "coordination_watch_bindings": "canonical_projection",
        "coordination_reconciliation": "canonical_projection",
        "silent_life_bundle": "bounded_sensor_bundle",
        "brainlive_live_ready": "deterministic_primary_with_bounded_fallback",
        "brain2_engine_fields:engine:episode": "specialized_window_executor",
        "brain2_engine_batch:conversation:engine:g0": "specialized_window_executor",
        "brain2_global_pack:conversation:root:digest": "specialized_window_executor",
        "brain2_episode_pack:conversation:episode:pack": "specialized_window_executor",
        "brain2_episodes:conversation": "specialized_window_executor",
        "brain2_sensor_routing": "specialized_window_executor",
    }
    assert {name: stage_input_policy(name) for name in expected} == expected


def test_orchestrator_projects_outcome_and_intervention_without_raw_reanalysis(
    tmp_path, monkeypatch,
):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        project_stage_payload,
    )

    with connect(db_path) as con:
        outcome = project_stage_payload(
            stage_name="v13_latent_outcomes", person_id="me",
            source_ref="conv-i2",
            payload={
                "new_conversation": {"legacy": True},
                "new_turns": [{"turn_id": "duplicated"}],
                "pending_items": [{"source_table": "predictions", "source_id": "p1"}],
            }, connection=con,
        )
        proactive = project_stage_payload(
            stage_name="v14_proactive_interventions", person_id="me",
            source_ref="conv-i2",
            payload={
                "context": {
                    "recent_turns": [{"text": "must not be re-analysed"}],
                    "recent_episodes": [{"summary": "duplicate"}],
                    "context_addenda": {"raw": "duplicate"},
                    "interpersonal_suggestions": [{"suggestion_id": "s1"}],
                    "existing_open_queue": [],
                },
                "policy": {"min_queue_confidence": 0.42},
            }, connection=con,
        )

    assert outcome.payload["pending_items"][0]["source_id"] == "p1"
    assert outcome.payload["new_turns"][0]["turn_id"] == "t0"
    assert outcome.payload["canonical_projection"]["all_turns_present_once"] is True
    context = proactive.payload["context"]
    assert "recent_turns" not in context
    assert "recent_episodes" not in context
    assert "context_addenda" not in context
    assert context["interpersonal_suggestions"] == [{"suggestion_id": "s1"}]
    assert context["current_conversation"]["candidate_facts"] is not None


def test_intervention_writer_normalizes_richer_model_text_values():
    from mlomega_audio_elite.proactive_interventions_v14_7 import _text_field

    assert _text_field(
        {"person_hint": "Maxime", "person_id": "person-1"},
        preferred_keys=("person_hint", "name", "person_id"),
    ) == "Maxime"
    assert json.loads(_text_field(["one", "two"])) == ["one", "two"]


def test_close_day_accepts_honest_life_watch_and_idempotent_empty_delta():
    from mlomega_audio_elite.v18_close_day import _status_ok

    assert _status_ok({"status": "compiled_watch_only"}, stage_name="life_model")
    assert _status_ok({"status": "compiled_no_life_delta"}, stage_name="life_model")
    assert not _status_ok({"status": "error"}, stage_name="life_model")


def test_e64_canonical_paths_are_product_default_with_explicit_rollback(monkeypatch):
    from mlomega_audio_elite.brain2_conversation_episode import (
        conversation_episode_enabled,
    )
    from mlomega_audio_elite.brain2_shared_facts_v19 import shared_facts_enabled

    monkeypatch.delenv("MLOMEGA_E64_CONVERSATION_EPISODES", raising=False)
    monkeypatch.delenv("MLOMEGA_E64_SHARED_FACTS", raising=False)
    assert conversation_episode_enabled() is True
    assert shared_facts_enabled() is True
    monkeypatch.setenv("MLOMEGA_E64_CONVERSATION_EPISODES", "0")
    monkeypatch.setenv("MLOMEGA_E64_SHARED_FACTS", "0")
    assert conversation_episode_enabled() is False
    assert shared_facts_enabled() is False


def test_daily_longitudinal_projections_keep_raw_only_as_durable_manifest(
    tmp_path, monkeypatch,
):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        project_stage_payload,
    )

    raw = {
        "person_id": "me", "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-01T23:59:59Z",
        "language": {"turns_recent": [{"text": "opaque raw duplicate"}]},
        "observed_life": {"episodes": [{"summary": "opaque raw duplicate"}]},
    }
    with connect(db_path) as con:
        life = project_stage_payload(
            stage_name="life_model_bootstrap", person_id="me",
            source_ref="me:2026-01-01:bootstrap",
            payload={"raw_evidence": raw}, connection=con,
        )
        periodic = project_stage_payload(
            stage_name="v14_periodic_mirror_day", person_id="me",
            source_ref="me:day:2026-01-01",
            payload={"bundle": {**raw, "period": "day"}, "v14_digest": {}},
            connection=con,
        )

    life_prompt = life.payload["raw_evidence"]
    mirror_prompt = periodic.payload["bundle"]
    assert "language" not in life_prompt
    assert "observed_life" not in life_prompt
    assert life_prompt["raw_source_manifest"]["digest"]
    assert mirror_prompt["raw_source_manifest"]["digest"]
    assert life_prompt["shared_registry"]["source_manifest"]["digest"]
    assert periodic.payload["v14_digest"] == {}


def test_unregistered_product_stage_fails_before_replaying_raw_bundle(
    tmp_path, monkeypatch,
):
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    import pytest
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.night_orchestrator.prompt_projection import (
        project_stage_payload,
    )

    with connect(db_path) as con, pytest.raises(
        RuntimeError, match="unregistered product stage input policy"
    ):
        project_stage_payload(
            stage_name="v14_future_accidental_raw_bundle", person_id="me",
            source_ref="conv-i2", payload={"bundle": {"raw": [1, 2, 3]}},
            connection=con,
        )
