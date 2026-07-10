from __future__ import annotations

from mlomega_audio_elite.db import connect, write_transaction
from mlomega_audio_elite.governance_v18 import (
    Scope,
    begin_or_resume_run,
    finish_stage,
    start_stage,
)
from mlomega_audio_elite.v18_close_day import (
    _CLOSE_DAY_REQUIRED_STAGES,
    _verified_close_day_outputs,
)
from mlomega_audio_elite.v19_visual_store import store_scene_summary


def _results() -> dict[str, dict]:
    return {
        "post_stop": {"status": "completed"},
        "visual_consolidation": {
            "status": "completed", "stage": "visual_consolidation",
            "summary_id": "summary-proof",
        },
        "longitudinal": {"status": "completed"},
        "coordination": {"status": "ok"},
        "life_model": {"status": "active"},
        "outcome_resolution": {"status": "completed", "outcome_ids": []},
        "life_model_v19": {"status": "completed", "confirmed": [], "contradicted": [], "weakened": []},
        "prediction_emission": {"status": "completed", "prediction_ids": []},
        "self_schema": {"status": "completed", "schema_entry_ids": []},
        "live_ready": {"status": "active"},
    }


def test_manifest_observes_real_artifact_rows_not_returned_ids(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    results = _results()
    run_id, _ = begin_or_resume_run(
        pipeline_name="close_day_test",
        scope=Scope(person_id="me", mode="maintenance"),
        input_manifest={"test": True},
        idempotency_key="close-day-proof",
    )
    with connect(db_path) as con, write_transaction(con):
        for name in _CLOSE_DAY_REQUIRED_STAGES:
            start_stage(con, run_id=run_id, stage_name=name, required=True)
            finish_stage(
                con, run_id=run_id, stage_name=name,
                result=results[name], status="completed",
            )

    expected, observed = _verified_close_day_outputs(
        run_id=run_id, person_id="me", stage_results=results
    )
    assert "visual_consolidation:summary-proof" in expected
    assert "visual_consolidation:summary-proof" not in observed
    assert all(f"stage:{name}" in observed for name in _CLOSE_DAY_REQUIRED_STAGES)

    store_scene_summary(
        {
            "scene_summary_id": "summary-proof",
            "memory_owner_id": "me",
            "live_session_id": "session-proof",
            "summary_start": "2026-07-10T08:00:00+00:00",
            "summary_end": "2026-07-10T09:00:00+00:00",
            "summary": {"event_count": 1},
        },
        db_path=db_path,
    )
    expected, observed = _verified_close_day_outputs(
        run_id=run_id, person_id="me", stage_results=results
    )
    assert set(expected) == set(observed)
