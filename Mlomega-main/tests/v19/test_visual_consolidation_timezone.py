from __future__ import annotations

from mlomega_audio_elite.db import connect
from mlomega_audio_elite.v19_visual_consolidation import _time_slot, run_visual_consolidation
from mlomega_audio_elite.v19_visual_store import store_visual_event


def _event(at: str, suffix: str) -> dict:
    return {
        "visual_event_id": f"event-{suffix}",
        "memory_owner_id": "me",
        "live_session_id": "local-day-session",
        "event_type": "object_seen",
        "occurred_at": at,
        "entity": {"entity_id": "stable-mug", "label": "mug"},
        "truth_level": "observed",
        "confidence": 0.9,
        "evidence": [{"kind": "frame", "frame_id": suffix}],
    }


def test_visual_day_uses_paris_civil_bounds_not_utc_midnight(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_LOCAL_TZ", "Europe/Paris")

    # 2026-07-10 Europe/Paris is [Jul 9 22:00Z, Jul 10 22:00Z).
    for at, suffix in (
        ("2026-07-09T21:59:59+00:00", "before"),
        ("2026-07-09T22:00:00+00:00", "start"),
        ("2026-07-10T21:59:59+00:00", "end-minus"),
        ("2026-07-10T22:00:00+00:00", "after"),
    ):
        store_visual_event(_event(at, suffix), db_path=db_path)

    report = run_visual_consolidation(
        person_id="me", package_date="2026-07-10", db_path=db_path
    )
    assert report["visual_event_count"] == 2
    with connect(db_path) as con:
        summary = con.execute(
            "SELECT summary_start,summary_end FROM scene_session_summaries_v19"
        ).fetchone()
    assert summary["summary_start"] == "2026-07-09T22:00:00+00:00"
    assert summary["summary_end"] == "2026-07-10T21:59:59+00:00"


def test_time_slot_is_derived_in_local_timezone(monkeypatch):
    monkeypatch.setenv("MLOMEGA_LOCAL_TZ", "Europe/Paris")
    assert _time_slot("2026-07-10T04:30:00+00:00") == "morning"
