from __future__ import annotations

from datetime import datetime, timezone

import pytest


pytestmark = pytest.mark.memory


def _env(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_LOCAL_TZ", "Europe/Paris")
    return db_path


def test_canonical_night_model_projects_into_v19_without_seed(tmp_path, monkeypatch):
    db_path = _env(tmp_path, monkeypatch)
    person_id = "owner-project"

    from mlomega_audio_elite.brain2_life_model_v15_10 import (
        ensure_life_model_schema,
        store_canonical_life_model,
    )
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.v19_visual_store import store_visual_event
    from mlomega_audio_elite.v19_life_model_store import run_life_model_v19_stage

    ensure_life_model_schema()
    evidence_id = store_visual_event({
        "memory_owner_id": person_id,
        "live_session_id": "source-session",
        "event_type": "routine_observed",
        "occurred_at": "2026-07-11T07:00:00+00:00",
        "truth_level": "observed",
        "confidence": 0.9,
        "evidence": [{"frame_id": "source-frame", "sha256": "sha", "kind": "keyframe"}],
    }, db_path=db_path)
    store_canonical_life_model(
        person_id,
        "export-real-night",
        {
            "personal_routine_models": [{
                "routine_name": "café matinal observé",
                "evidence": [{"source_table": "visual_events_v19", "source_id": evidence_id}],
                "confidence": 0.82,
            }]
        },
    )

    first = run_life_model_v19_stage(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    assert first["projected"]["created"]
    with connect(db_path) as con:
        row = dict(con.execute(
            "SELECT * FROM life_model_entries_v19 WHERE person_id=?", (person_id,)
        ).fetchone())
    assert row["statement"] == "café matinal observé"
    assert row["source_table"] == "brain2_personal_routine_models"
    assert row["source_id"]

    second = run_life_model_v19_stage(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    assert second["projected"]["created"] == []
    assert second["projected"]["updated"] == []
    assert second["projected"]["unchanged"]


def test_prediction_keeps_source_entry_and_skips_uncausal_calibration(tmp_path, monkeypatch):
    db_path = _env(tmp_path, monkeypatch)
    person_id = "owner-prediction"

    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.v19_life_model_store import apply_life_model_delta
    from mlomega_audio_elite.v19_outcome_watcher import resolve_prediction_outcomes
    from mlomega_audio_elite.v19_prediction_loop import emit_daily_predictions
    from mlomega_audio_elite.v19_visual_store import store_visual_event

    entry_id = apply_life_model_delta(person_id, {
        "dimension": "routines",
        "temporal_axis": "future_short",
        "statement": "visite du café attendue",
        "confidence": 0.8,
        "verification_spec": {
            "event_type": "visit", "place_label": "cafe", "sources": ["visual_events_v19"]
        },
    }, db_path=db_path)
    emitted = emit_daily_predictions(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    assert emitted["prediction_ids"]
    with connect(db_path) as con:
        prediction = dict(con.execute(
            "SELECT * FROM predictions_v19 WHERE prediction_id=?", (emitted["prediction_ids"][0],)
        ).fetchone())
    assert prediction["source_entry_id"] == entry_id

    store_visual_event({
        "memory_owner_id": person_id,
        "live_session_id": "session",
        "event_type": "visit",
        "occurred_at": "2026-07-11T08:00:00+00:00",
        "place": {"label": "cafe"},
        "truth_level": "observed",
        "confidence": 0.9,
        "evidence": [{"frame_id": "f1", "sha256": "sha", "kind": "keyframe"}],
    }, db_path=db_path)
    resolved = resolve_prediction_outcomes(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    assert resolved["resolved"][0]["status"] == "verified"
    with connect(db_path) as con:
        has_labels = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v18_predictive_similarity_labels'"
        ).fetchone()
        labels = 0 if has_labels is None else con.execute(
            "SELECT COUNT(*) FROM v18_predictive_similarity_labels WHERE person_id=?", (person_id,)
        ).fetchone()[0]
        audit = con.execute(
            "SELECT audit_json FROM prediction_outcomes_v19 WHERE prediction_id=?",
            (prediction["prediction_id"],),
        ).fetchone()[0]
    assert labels == 0
    assert "no_causal_case_pair" in audit


def test_self_schema_removes_invalid_sources_and_filters_other_owner_edges(tmp_path, monkeypatch):
    db_path = _env(tmp_path, monkeypatch)

    from mlomega_audio_elite.db import connect, upsert, write_transaction
    from mlomega_audio_elite.utils import now_iso, stable_id
    from mlomega_audio_elite.v19_life_model_store import apply_life_model_delta, mark_contradicted
    from mlomega_audio_elite.v19_self_schema import ensure_self_schema, rebuild_self_schema

    ensure_self_schema(db_path)
    owner = "owner-a"
    other = "owner-b"
    entry_id = apply_life_model_delta(owner, {
        "dimension": "values", "temporal_axis": "present", "statement": "préfère le calme"
    }, db_path=db_path)
    now = now_iso()
    with connect(db_path) as con, write_transaction(con):
        for pid, pattern_id in ((owner, "pattern-a"), (other, "pattern-b")):
            upsert(con, "confirmed_patterns", {
                "confirmed_pattern_id": pattern_id,
                "person_id": pid,
                "pattern_type": "conditional",
                "pattern_key": pattern_id,
                "title": pattern_id,
                "description": pattern_id,
                "evidence_count": 2,
                "counterexample_count": 0,
                "confidence": 0.8,
                "validity_status": "active",
                "created_at": now,
                "updated_at": now,
            }, "confirmed_pattern_id")
            edge_id = stable_id("edge", pattern_id)
            upsert(con, "causal_edges", {
                "causal_edge_id": edge_id,
                "from_table": "confirmed_patterns",
                "from_id": pattern_id,
                "to_table": "confirmed_patterns",
                "to_id": pattern_id,
                "causal_type": "supports",
                "truth_status": "confirmed",
                "confidence": 0.8,
                "created_at": now,
                "updated_at": now,
            }, "causal_edge_id")

    rebuild_self_schema(person_id=owner, db_path=db_path)
    with connect(db_path) as con:
        causal_sources = [row[0] for row in con.execute(
            "SELECT source_json FROM self_schema_v19 WHERE person_id=? AND entry_type='causal'",
            (owner,),
        ).fetchall()]
    assert len(causal_sources) == 1
    assert stable_id("edge", "pattern-a") in causal_sources[0]

    mark_contradicted(
        owner, entry_id,
        contradicting_ref={"source_table": "manual_review", "source_id": "review-1"},
        db_path=db_path,
    )
    rebuild_self_schema(person_id=owner, db_path=db_path)
    with connect(db_path) as con:
        stale = con.execute(
            "SELECT COUNT(*) FROM self_schema_v19 WHERE person_id=? AND source_json LIKE ?",
            (owner, f"%{entry_id}%"),
        ).fetchone()[0]
    assert stale == 0


def test_local_civil_time_drives_replay_prediction_and_life_stage(tmp_path, monkeypatch):
    db_path = _env(tmp_path, monkeypatch)
    person_id = "owner-time"

    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.v19_life_model_store import apply_life_model_delta, run_life_model_v19_stage
    from mlomega_audio_elite.v19_prediction_loop import emit_daily_predictions
    from mlomega_audio_elite.v19_visual_store import store_visual_event

    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "services" / "live-pc" / "replay_service.py"
    spec = importlib.util.spec_from_file_location("e61_replay_service", path)
    assert spec and spec.loader
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)

    start, end = replay.parse_time_window("14h", date="2026-07-11")
    assert start == "2026-07-11T12:00:00+00:00"
    assert end == "2026-07-11T12:15:00+00:00"

    entry_id = apply_life_model_delta(person_id, {
        "dimension": "routines",
        "temporal_axis": "future_short",
        "statement": "routine nocturne",
        "verification_spec": {
            "event_type": "visit", "place_label": "home", "sources": ["visual_events_v19"],
            "horizon_start_hour": 0, "horizon_end_hour": 2,
        },
    }, db_path=db_path)
    emitted = emit_daily_predictions(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    with connect(db_path) as con:
        pred = dict(con.execute(
            "SELECT * FROM predictions_v19 WHERE prediction_id=?", (emitted["prediction_ids"][0],)
        ).fetchone())
    assert pred["source_entry_id"] == entry_id
    assert pred["horizon_start"] == "2026-07-10T22:00:00+00:00"
    assert pred["horizon_end"] == "2026-07-11T00:00:00+00:00"

    store_visual_event({
        "memory_owner_id": person_id,
        "live_session_id": "session-time",
        "event_type": "visit",
        "occurred_at": "2026-07-10T22:30:00+00:00",
        "place": {"label": "home"},
        "truth_level": "observed",
        "confidence": 0.9,
        "evidence": [{"frame_id": "night", "sha256": "sha", "kind": "keyframe"}],
    }, db_path=db_path)
    stage = run_life_model_v19_stage(
        person_id=person_id, package_date="2026-07-11", db_path=db_path
    )
    assert entry_id in stage["confirmed"]


def test_close_day_warns_when_eligible_inputs_produce_no_semantic_output(tmp_path, monkeypatch):
    db_path = _env(tmp_path, monkeypatch)
    person_id = "owner-warning"

    from mlomega_audio_elite.brain2_life_model_v15_10 import ensure_life_model_schema, store_canonical_life_model
    from mlomega_audio_elite.v18_close_day import _semantic_output_warnings
    from mlomega_audio_elite.v19_visual_store import store_visual_event

    ensure_life_model_schema()
    evidence_id = store_visual_event({
        "memory_owner_id": person_id,
        "live_session_id": "warning-session",
        "event_type": "routine_observed",
        "occurred_at": "2026-07-08T07:00:00+00:00",
        "truth_level": "observed",
        "confidence": 0.9,
        "evidence": [{"frame_id": "warning-frame", "sha256": "sha", "kind": "keyframe"}],
    }, db_path=db_path)
    store_canonical_life_model(person_id, "export-warning", {
        "personal_routine_models": [{
            "routine_name": "routine durable",
            "confidence": 0.8,
            "evidence": [{"source_table": "visual_events_v19", "source_id": evidence_id}],
        }]
    })
    warnings = _semantic_output_warnings(
        person_id=person_id,
        package_date="2026-07-08",
        stage_results={
            "life_model_v19": {"count": 0},
            "prediction_emission": {"prediction_ids": []},
            "self_schema": {"schema_entry_ids": []},
            "longitudinal": {},
        },
    )
    assert any(item["code"] == "life_model_v19_empty_with_canonical_inputs" for item in warnings)
