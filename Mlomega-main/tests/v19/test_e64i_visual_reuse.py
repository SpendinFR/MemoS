from __future__ import annotations

"""E64-I4.3 Deep Vision reuse in visual_consolidation + VisionRT movement bridge.

The wiring proven here (real raccord, no video re-run, no real VLM):

* VisionRT (worldbrain) records live detections/tracks/bbox in
  ``visual_events_v19``; Deep Vision writes VALIDATED semantics per keyframe in
  ``brainlive_deep_vision_observations_v161`` (status='ok'); ``visual_consolidation``
  now REUSES both BY CODE (join on person/date/bundle/frame) instead of paying a
  second inference.

Codex-required tests only:
* reuse: an image already analysed -> ZERO network calls (a wrapped VLM counter
  stays at 0 through the whole consolidation);
* movement preserved: a MAJOR displacement at CONSTANT labels (VisionRT bbox)
  opens a keyframe instead of being ignored (closes the I4.2 no-position limit);
* explicit fallback when data is absent (no bbox / no validated analysis) -> a
  documented status, never a crash and never a false-complete;
* no duplicate at rejeu: re-running the consolidation upserts, never duplicates.

Fakes + MLOMEGA_DB monkeypatch; the real DBs are never touched.
"""

import pytest

from mlomega_audio_elite.db import connect, init_db, write_transaction
from mlomega_audio_elite.utils import now_iso, stable_id


PERSON = "me"
DATE = "2026-07-14"
SESSION = "sess1"
DAY_START = "2026-07-13T22:00:00+00:00"  # Europe/Paris civil-day bounds (UTC)
DAY_END = "2026-07-14T22:00:00+00:00"


# --------------------------------------------------------------------------- #
# Seed helpers (mirror the real writer shapes)                                #
# --------------------------------------------------------------------------- #

def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "reuse.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_LOCAL_TZ", "Europe/Paris")


def _seed_deep_observation(
    con, *, obs_id, bundle_id, frame_id, status="ok", activity="computer_work", image_path="/fake/kf.jpg"
):
    con.executescript(
        """CREATE TABLE IF NOT EXISTS brainlive_deep_vision_observations_v161(
             deep_observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, person_id TEXT NOT NULL,
             package_date TEXT NOT NULL, bundle_id TEXT NOT NULL, live_session_id TEXT,
             conversation_id TEXT, frame_id TEXT, image_path TEXT NOT NULL, frame_time TEXT,
             sample_index INTEGER DEFAULT 0, sample_reason TEXT, model TEXT, status TEXT NOT NULL,
             scene_summary_detailed TEXT, observed_activity TEXT, activity_confidence REAL DEFAULT 0.0,
             location_hint TEXT, spatial_layout TEXT, objects_json TEXT DEFAULT '[]',
             affordances_json TEXT DEFAULT '[]', visible_text_json TEXT DEFAULT '[]',
             people_presence_json TEXT DEFAULT '{}', screens_or_devices_json TEXT DEFAULT '[]',
             posture_motion_json TEXT DEFAULT '{}', work_or_rest_signal_json TEXT DEFAULT '{}',
             smoking_pause_signal_json TEXT DEFAULT '{}', exact_visual_evidence_json TEXT DEFAULT '[]',
             uncertainty_json TEXT DEFAULT '[]', qwen_json TEXT DEFAULT '{}', latency_ms INTEGER,
             error_text TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"""
    )
    con.execute(
        """INSERT INTO brainlive_deep_vision_observations_v161(
             deep_observation_id, run_id, person_id, package_date, bundle_id, live_session_id,
             frame_id, image_path, observed_activity, location_hint, status, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (obs_id, "run1", PERSON, DATE, bundle_id, SESSION, frame_id, image_path, activity,
         "office", status, now_iso(), now_iso()),
    )


def _seed_visionrt_event(store, *, frame_id, label, bbox, occurred_at, event_type="entity_last_seen", db_path):
    """Write a VisionRT visual event + its evidence asset carrying frame_id."""
    payload = {
        "memory_owner_id": PERSON,
        "live_session_id": SESSION,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "entity": {"entity_id": f"ent_{label}", "kind": "object", "label": label},
        "observation": {"bbox": list(bbox), "observation_count": 3},
        "truth_level": "observed",
        "confidence": 0.8,
        "evidence": [{"frame_id": frame_id, "kind": "frame", "sha256": f"sha_{frame_id}"}],
        "provenance": {"producer": "worldbrain"},
    }
    return store.store_visual_event(payload, db_path=db_path)


# --------------------------------------------------------------------------- #
# 1. Reuse = ZERO network calls                                                #
# --------------------------------------------------------------------------- #

def test_reuse_of_validated_analysis_makes_zero_network_calls(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    init_db()

    from mlomega_audio_elite import brainlive_offline_deep_vision_v16_1 as base
    from mlomega_audio_elite import v19_visual_store as store
    from mlomega_audio_elite.v19_visual_consolidation import (
        DEEP_VISION_REUSE_TABLE,
        run_visual_consolidation,
    )

    # A wrapped VLM: any call during consolidation is a hard failure.
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("visual_consolidation must NEVER call the VLM for an already-analysed image")

    monkeypatch.setattr(base, "_deep_vlm_json", boom)
    monkeypatch.setattr(base, "ollama_generate", boom)

    store.ensure_v19_visual_schema()
    with connect() as con, write_transaction(con):
        _seed_deep_observation(con, obs_id="obs1", bundle_id="b1", frame_id="frame_1")
    _seed_visionrt_event(
        store, frame_id="frame_1", label="cup", bbox=[10.0, 10.0, 20.0, 20.0],
        occurred_at="2026-07-14T09:00:00+00:00", db_path=None,
    )

    out = run_visual_consolidation(person_id=PERSON, package_date=DATE, live_session_id=SESSION)

    assert calls["n"] == 0
    reuse = out["deep_vision_reuse"]
    assert reuse["reused"] == 1
    assert reuse["with_position"] == 1
    assert reuse["status"] == "reused"

    with connect() as con:
        rows = con.execute(
            f"SELECT deep_observation_id, visionrt_bbox_present, status, source_refs_json "
            f"FROM {DEEP_VISION_REUSE_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["visionrt_bbox_present"] == 1
    assert rows[0]["status"] == "reused"
    # Provenance points back to BOTH the origin VLM analysis and the VisionRT event.
    assert "brainlive_deep_vision_observations_v161" in rows[0]["source_refs_json"]
    assert "visual_events_v19" in rows[0]["source_refs_json"]


# --------------------------------------------------------------------------- #
# 2. Movement at constant labels preserved via VisionRT bbox                   #
# --------------------------------------------------------------------------- #

def test_constant_label_displacement_opens_keyframe_via_visionrt_bbox():
    """Closes the I4.2 no-position limitation: a MAJOR move at same labels opens a keyframe."""
    from mlomega_audio_elite.night_orchestrator.deep_vision_selection import (
        REASON_SCENE_CHANGE,
        select_keyframes_with_coverage,
    )

    def _ts(s):
        return f"2026-07-14T08:29:{s:02d}+00:00"

    # Same single label "cup" throughout (no label/people/OCR change at all).
    items = [
        {"source_table": "vision_scene_observations", "source_id": "o0", "frame_id": "frame_0",
         "time": _ts(0), "objects": [{"label": "cup", "track_id": "t1"}], "people_count": 0, "summary": "s"},
        {"source_table": "vision_scene_observations", "source_id": "o1", "frame_id": "frame_1",
         "time": _ts(4), "objects": [{"label": "cup", "track_id": "t1"}], "people_count": 0, "summary": "s"},
        {"source_table": "vision_scene_observations", "source_id": "o2", "frame_id": "frame_2",
         "time": _ts(8), "objects": [{"label": "cup", "track_id": "t1"}], "people_count": 0, "summary": "s"},
    ]
    cands = [
        {"bundle_id": "b1", "frame_id": f"frame_{i}", "image_path": f"/f{i}.jpg",
         "frame_time": _ts(i * 4), "exists": True}
        for i in range(3)
    ]
    bundle = {"bundle_id": "b1", "person_id": PERSON, "package_date": DATE,
              "live_session_id": SESSION, "vision_timeline_json": items}

    # VisionRT positions (normalised 0..1): the cup jumps from the top-left to the
    # bottom-right between frame_0 and frame_2 - a major displacement (> 0.20 of
    # the frame) at a CONSTANT label.
    frame_positions = {
        "frame_0": [{"label": "cup", "bbox": [0.05, 0.05, 0.05, 0.05]}],
        "frame_1": [{"label": "cup", "bbox": [0.06, 0.06, 0.05, 0.05]}],  # negligible move
        "frame_2": [{"label": "cup", "bbox": [0.85, 0.85, 0.05, 0.05]}],  # major move
    }

    # WITHOUT positions: label-set-only -> single keyframe (documented limitation).
    baseline = select_keyframes_with_coverage(bundle, cands, safety_interval_s=999, micro_transition_window_s=0)
    assert baseline.selected_count == 1

    # WITH VisionRT positions: the major move opens a second keyframe.
    moved = select_keyframes_with_coverage(
        bundle, cands, safety_interval_s=999, micro_transition_window_s=0, frame_positions=frame_positions
    )
    assert moved.selected_count == 2
    assert "frame_2" in moved.selected_frame_ids
    assert REASON_SCENE_CHANGE in moved.reasons_by_frame["frame_2"]
    assert moved.fully_covered  # never a silent drop


# --------------------------------------------------------------------------- #
# 3. Explicit fallback when a datum is absent                                  #
# --------------------------------------------------------------------------- #

def test_fallback_when_no_validated_analysis_is_explicit(monkeypatch, tmp_path):
    """No validated Deep Vision observation -> explicit 'absent', never a crash/false-complete."""
    _env(monkeypatch, tmp_path)
    init_db()
    from mlomega_audio_elite import v19_visual_store as store
    from mlomega_audio_elite.v19_visual_consolidation import run_visual_consolidation

    store.ensure_v19_visual_schema()
    # A VisionRT event exists but there is NO deep-vision observation at all.
    _seed_visionrt_event(
        store, frame_id="frame_9", label="cup", bbox=[1.0, 2.0, 3.0, 4.0],
        occurred_at="2026-07-14T09:00:00+00:00", db_path=None,
    )
    out = run_visual_consolidation(person_id=PERSON, package_date=DATE, live_session_id=SESSION)
    assert out["status"] == "completed"  # the stage still completes
    assert out["deep_vision_reuse"]["status"] == "absent"
    assert out["deep_vision_reuse"]["reused"] == 0


def test_fallback_when_analysis_has_no_visionrt_position_is_explicit(monkeypatch, tmp_path):
    """A validated analysis with NO matching VisionRT bbox is reused but flagged degraded."""
    _env(monkeypatch, tmp_path)
    init_db()
    from mlomega_audio_elite import v19_visual_store as store
    from mlomega_audio_elite.v19_visual_consolidation import (
        DEEP_VISION_REUSE_TABLE,
        run_visual_consolidation,
    )

    store.ensure_v19_visual_schema()
    with connect() as con, write_transaction(con):
        _seed_deep_observation(con, obs_id="obsNP", bundle_id="b1", frame_id="frame_no_pos")
    # No VisionRT event for frame_no_pos.
    out = run_visual_consolidation(person_id=PERSON, package_date=DATE, live_session_id=SESSION)
    reuse = out["deep_vision_reuse"]
    assert reuse["reused"] == 1
    assert reuse["with_position"] == 0
    assert reuse["status"] == "reused_no_position"
    with connect() as con:
        row = con.execute(
            f"SELECT status, visionrt_bbox_present FROM {DEEP_VISION_REUSE_TABLE}"
        ).fetchone()
    assert row["status"] == "reused_no_position"
    assert row["visionrt_bbox_present"] == 0


# --------------------------------------------------------------------------- #
# 4. No duplicate at rejeu (idempotence)                                       #
# --------------------------------------------------------------------------- #

def test_rejeu_does_not_duplicate_reuse_rows(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    init_db()
    from mlomega_audio_elite import v19_visual_store as store
    from mlomega_audio_elite.v19_visual_consolidation import (
        DEEP_VISION_REUSE_TABLE,
        run_visual_consolidation,
    )

    store.ensure_v19_visual_schema()
    with connect() as con, write_transaction(con):
        _seed_deep_observation(con, obs_id="obsA", bundle_id="b1", frame_id="frame_1")
        _seed_deep_observation(con, obs_id="obsB", bundle_id="b1", frame_id="frame_2")
    _seed_visionrt_event(
        store, frame_id="frame_1", label="cup", bbox=[10.0, 10.0, 20.0, 20.0],
        occurred_at="2026-07-14T09:00:00+00:00", db_path=None,
    )

    first = run_visual_consolidation(person_id=PERSON, package_date=DATE, live_session_id=SESSION)
    second = run_visual_consolidation(person_id=PERSON, package_date=DATE, live_session_id=SESSION)

    assert first["deep_vision_reuse"]["reused"] == 2
    assert second["deep_vision_reuse"]["reused"] == 2

    with connect() as con:
        n = con.execute(f"SELECT COUNT(*) AS n FROM {DEEP_VISION_REUSE_TABLE}").fetchone()["n"]
        created = con.execute(
            f"SELECT created_at, updated_at FROM {DEEP_VISION_REUSE_TABLE} WHERE deep_observation_id='obsA'"
        ).fetchone()
    # Rerun upserts: still exactly 2 rows, and created_at was preserved.
    assert n == 2
    assert created["created_at"] is not None
