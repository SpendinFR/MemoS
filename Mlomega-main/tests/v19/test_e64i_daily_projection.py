from __future__ import annotations

from mlomega_audio_elite.night_orchestrator.daily_fact_projection import (
    build_reconciliation_candidates,
    compile_day_package,
    compile_watch_bindings,
    project_day_evidence,
    project_life_patch_payload,
)
from mlomega_audio_elite.night_orchestrator.stage_adapter import (
    estimate_tokens_for_text,
)
from mlomega_audio_elite.utils import json_dumps
import pytest


def test_day_projection_keeps_all_vision_refs_and_raw_manifest():
    rows = [
        {
            "observation_id": f"obs-{index}",
            "frame_id": f"frame-{index}",
            "created_at": f"2026-07-14T10:00:0{index}Z",
            "scene_summary": "salon",
            "objects_json": '[{"label":"lunettes","track_id":"g1"}]',
            "visible_text_json": "[]",
            "people_count": 1,
            "confidence": 0.9 - index / 10,
        }
        for index in range(3)
    ]
    raw = {
        "package_date": "2026-07-14",
        "period_start": "2026-07-14T00:00:00Z",
        "period_end": "2026-07-15T00:00:00Z",
        "vision_observations": rows,
        "turns": [],
    }

    projected = project_day_evidence(raw)

    assert projected["source_manifests"]["vision_observations"]["source_count"] == 3
    atoms = projected["sections"]["vision_change_atoms"]
    assert len(atoms) == 1
    assert atoms[0]["source_refs"] == ["obs-0", "obs-1", "obs-2"]
    assert atoms[0]["first_seen"] == "2026-07-14T10:00:00Z"
    assert atoms[0]["last_seen"] == "2026-07-14T10:00:02Z"


def test_day_compiler_marks_low_asr_and_does_not_infer_language():
    raw = {
        "package_date": "2026-07-14",
        "period_start": "2026-07-14T00:00:00Z",
        "period_end": "2026-07-15T00:00:00Z",
        "turns": [{
            "live_turn_id": "turn-1", "text_final": "texte incertain",
            "asr_confidence": 0.12, "timestamp_start": "2026-07-14T12:00:00Z",
        }],
    }
    projected = project_day_evidence(raw, shared_registry={"facts": []})

    package = compile_day_package(raw, projected)

    assert package["important_live_moments"][0]["epistemic_status"] == "uncertain_asr"
    assert "language" not in json_dumps(package).lower()


def test_watch_compiler_is_one_to_one_and_preserves_source_ids():
    evidence = {
        "predictions_short_and_next": [{
            "prediction_id": "pred-1", "prediction_target": "prendre les lunettes",
            "horizon": "short", "probability": 0.7,
            "activation_conditions_json": '[{"room":"salon"}]',
        }],
        "brain2_live_prediction_hooks": [{
            "hook_id": "hook-1", "hook_name": "départ maison", "horizon": "H0",
            "watch_signals_json": '["clés","porte"]', "confidence": 0.8,
        }],
        "life_model_needs": [{
            "need_model_id": "need-context-only",
            "need_or_expectation": "être écouté", "status": "active",
        }],
    }
    table_map = {
        "predictions_short_and_next": "predictions",
        "brain2_live_prediction_hooks": "brain2_live_prediction_hooks",
        "life_model_needs": "brain2_need_expectation_models",
    }

    items = compile_watch_bindings(evidence, section_table_map=table_map)

    assert {(item["source_table"], item["source_id"]) for item in items} == {
        ("predictions", "pred-1"),
        ("brain2_live_prediction_hooks", "hook-1"),
    }
    assert items[0]["horizon"] == "H1"


def test_reconciliation_only_compiles_explicit_observed_outcomes():
    brain2 = {"predictions_short_and_next": [{"prediction_id": "pred-1"}]}
    no_outcome = {"predictions_json": '[{"prediction_id":"pred-1","status":"active"}]'}
    exact, ambiguous = build_reconciliation_candidates(no_outcome, brain2)
    assert exact == []
    assert ambiguous == []

    observed = {
        "outcomes_json": '[{"prediction_id":"pred-1","outcome_id":"out-1",'
        '"outcome_status":"success","confidence":0.9}]'
    }
    exact, ambiguous = build_reconciliation_candidates(observed, brain2)
    assert ambiguous == []
    assert exact[0]["verdict"] == "confirmed"
    assert exact[0]["brain2_source_id"] == "pred-1"


def test_life_projection_indexes_all_rows_without_replaying_unrelated_history():
    rows = []
    for index in range(20):
        name = "lunettes salon" if index == 7 else f"routine sans rapport {index}"
        rows.append({
            "routine_id": f"routine-{index}", "routine_name": name,
            "status": "active", "confidence": 0.7,
            "evidence_json": json_dumps([{"id": f"ev-{index}-{n}", "text": "preuve longue" * 20} for n in range(20)]),
            "likely_needs_json": json_dumps(["retrouver rapidement les objets"] * 10),
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-07-14T00:00:00Z",
            "export_id": "same-export",
        })
    payload = {
        "mission": "patch",
        "current_life_model": {
            "person_id": "me", "canonical_layers": {"routine": rows},
            "lifecycle": [], "strata": {}, "latest_export": {},
        },
        "new_delta_evidence": {
            "observed_life": {"life_events": [{
                "subject_person_id": "me",
                "summary": "lunettes vues dans le salon",
            }]}
        },
        "update_rules": ["patch only"],
    }

    projected = project_life_patch_payload(payload)
    current = projected["current_life_model"]

    assert len(current["canonical_index"]["routine"]) == 20
    details = current["delta_relevant_details"]["routine"]
    assert details == []
    assert any(
        row["routine_id"] == "routine-7"
        and row["routine_name"] == "lunettes salon"
        for row in current["canonical_index"]["routine"]
    )
    assert current["selection_manifest"]["routine"]["total_rows"] == 20
    assert "same-export" not in json_dumps(projected)
    assert estimate_tokens_for_text(json_dumps(projected)) < (
        estimate_tokens_for_text(json_dumps(payload)) / 3
    )


def test_life_owner_gate_rejects_unknown_speakers_and_accepts_me():
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        _owner_delta_evidence_summary,
    )

    unknown = {
        "language": {"turns_recent": [{
            "turn_id": "t-other", "person_id": "UNKNOWN_VOICE_001",
            "text": "Je préfère ceci",
        }]},
        "self_and_internal": {"behavior_signals": [{
            "turn_id": "t-other", "person_id": "me",
        }]},
    }
    assert _owner_delta_evidence_summary(unknown, "me")["total"] == 0

    owner = {
        "language": {"turns_recent": [{
            "turn_id": "t-me", "person_id": "me", "text": "Je préfère ceci",
        }]},
        "self_and_internal": {"behavior_signals": [{
            "turn_id": "t-me", "person_id": "me",
        }]},
    }
    summary = _owner_delta_evidence_summary(owner, "me")
    assert summary["owner_turns"] == 1
    assert summary["owner_internal_rows"] == 1
    assert summary["total"] == 2
    assert summary["trigger_total"] == 0

    durable = {
        "observed_life": {"action_outcomes": [{
            "outcome_id": "out-1", "person_id": "me", "result": "completed",
        }]}
    }
    durable_summary = _owner_delta_evidence_summary(durable, "me")
    assert durable_summary["owner_observed_rows"] == 1
    assert durable_summary["trigger_total"] == 1


def test_life_projection_keeps_registry_and_excludes_unrelated_raw_speech():
    payload = {
        "mission": "patch",
        "current_life_model": {"canonical_layers": {}, "lifecycle": []},
        "new_delta_evidence": {
            "language": {"turns_recent": [{
                "turn_id": "turn-unrelated", "person_id": "me",
                "conversation_id": "conv-1", "text": "Maxime ?",
            }]},
            "observed_life": {"action_outcomes": [{
                "outcome_id": "out-1", "person_id": "me",
                "result": "identite clarifiee",
            }]},
        },
    }
    registry = {"facts": [{
        "fact_id": "fact-1", "subject_ref": "me", "fact_type": "outcome",
        "payload": {"result": "identite clarifiee"},
    }], "capabilities": []}

    projected = project_life_patch_payload(payload, shared_registry=registry)

    language = projected["new_delta_evidence"]["language"]
    assert language["turns_recent"] == []
    assert language["turn_transport_manifest"]["source_count"] == 1
    assert language["turn_transport_manifest"]["omitted_count"] == 1
    facts = projected["new_delta_evidence"]["shared_registry"]["facts"]
    assert facts[0]["fact_id"] == "fact-1"
    assert facts[0]["owner_scope"] == "owner_verified"


def test_life_patch_requires_durable_driver_and_clamps_first_sighting():
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        _enforce_life_patch_policy,
    )

    durable = {("action_outcomes", "out-1")}
    with pytest.raises(RuntimeError, match="no new owner-scoped durable evidence"):
        _enforce_life_patch_policy([{
            "op": "create", "identity_key": "ask identity",
            "evidence": [{"source_table": "turns", "source_id": "turn-1"}],
        }], durable_refs=durable, current_model={})

    guarded = _enforce_life_patch_policy([{
        "op": "create", "target_id": "model-invented-id",
        "identity_key": "ask identity", "stratum": "general",
        "confidence_before": 0.0, "confidence_after": 0.95,
        "evidence": [{"source_table": "action_outcomes", "source_id": "out-1"}],
        "lifecycle": {"truth_status": "confirmed", "use_policy": "strong_live_hook"},
        "live_effect": {"brainlive_action": "activate_hook", "horizons": ["H0"]},
    }], durable_refs=durable, current_model={})[0]

    assert "target_id" not in guarded
    assert guarded["stratum"] == "very_recent"
    assert guarded["confidence_after"] == 0.65
    assert guarded["lifecycle"]["truth_status"] == "candidate"
    assert guarded["lifecycle"]["use_policy"] == "watch_only"
    assert guarded["live_effect"]["brainlive_action"] == "watch"


def test_partial_life_patch_preserves_existing_canonical_fields():
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        _minimal_canonical_from_operation,
    )

    existing = {
        "action_model_id": "b2action-existing", "person_id": "me",
        "action_or_choice": "ask identity", "preference_or_tendency": "verify first",
        "context_conditions_json": '["unknown caller"]',
        "evidence_json": '[{"source_table":"turns","source_id":"turn-old"}]',
        "confidence": 0.55, "status": "active",
    }
    model = _minimal_canonical_from_operation("action_preference", {
        "identity_key": "ask identity", "confidence_after": 0.6,
        "patch_data": {"why_it_matters": "avoid confusion"},
        "evidence": [{"source_table": "action_outcomes", "source_id": "out-1"}],
    }, existing=existing)
    row = model["action_preference_models"][0]

    assert row["preference_or_tendency"] == "verify first"
    assert row["context_conditions"] == ["unknown caller"]
    assert row["why_it_matters"] == "avoid confusion"


def test_life_watch_compiler_is_idempotent_and_promotes_only_independent_repetition(
    tmp_path, monkeypatch,
):
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        compile_life_watch_candidates,
    )

    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "life-watch.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    first = {"observed_life": {"action_outcomes": [{
        "outcome_id": "out-1", "episode_id": "episode-1", "person_id": "me",
        "action_taken": "Demander confirmation identite", "result": "clarifie",
        "created_at": "2026-07-14T09:00:00Z",
    }]}}

    one = compile_life_watch_candidates("me", first)
    repeated_same_source = compile_life_watch_candidates("me", first)

    assert one["promotion_ready_count"] == 0
    assert one["candidates"][0]["status"] == "watching"
    assert repeated_same_source["candidates"][0]["occurrence_count"] == 1

    second = {"observed_life": {"action_outcomes": [{
        "outcome_id": "out-2", "episode_id": "episode-2", "person_id": "me",
        "action_taken": "demander confirmation identite", "result": "clarifie",
        "created_at": "2026-07-15T09:00:00Z",
    }]}}
    promoted = compile_life_watch_candidates("me", second)

    assert promoted["promotion_ready_count"] == 1
    assert promoted["candidates"][0]["status"] == "promotion_ready"
    assert promoted["candidates"][0]["occurrence_count"] == 2
    assert promoted["candidates"][0]["independent_count"] == 2


def test_life_checkpoint_replays_only_new_or_changed_source_revisions(
    tmp_path, monkeypatch,
):
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        commit_life_checkpoint,
        prepare_life_checkpoint_delta,
    )

    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "life-checkpoint.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    delta = {"observed_life": {"action_outcomes": [{
        "outcome_id": "out-1", "episode_id": "episode-1", "person_id": "me",
        "action_taken": "demander confirmation", "result": "clarifie",
        "updated_at": "2026-07-14T09:00:00Z",
    }]}}

    first, first_checkpoint = prepare_life_checkpoint_delta("me", delta)
    assert first_checkpoint["source_count"] == 1
    assert len(first["observed_life"]["action_outcomes"]) == 1
    committed = commit_life_checkpoint(
        "me", "patch-1", first_checkpoint, status="compiled_watch_only",
        period_start="2026-07-14T00:00:00Z", period_end="2026-07-15T00:00:00Z",
    )
    assert committed["source_count"] == 1

    replay, replay_checkpoint = prepare_life_checkpoint_delta("me", delta)
    assert replay_checkpoint["source_count"] == 0
    assert replay["observed_life"]["action_outcomes"] == []

    changed = {"observed_life": {"action_outcomes": [{
        **delta["observed_life"]["action_outcomes"][0],
        "result": "clarifie et confirme", "updated_at": "2026-07-14T09:05:00Z",
    }]}}
    revised, revised_checkpoint = prepare_life_checkpoint_delta("me", changed)
    assert revised_checkpoint["source_count"] == 1
    assert revised["observed_life"]["action_outcomes"][0]["result"] == "clarifie et confirme"
