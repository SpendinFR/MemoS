from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mlomega_audio_elite.spatial_bbox_v19 import sanitize_detector_bbox


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


worldbrain = _load("bbox_worldbrain", "services/live-pc/worldbrain.py")
visionrt = _load("bbox_visionrt", "services/live-pc/visionrt.py")


def test_long_tail_last_seen_reuses_latest_deep_vision_observation(
    tmp_path, monkeypatch
):
    brain, db_path = _brain(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE brainlive_deep_vision_observations_v161(
                 deep_observation_id TEXT PRIMARY KEY,
                 person_id TEXT,
                 live_session_id TEXT,
                 frame_id TEXT,
                 frame_time TEXT,
                 location_hint TEXT,
                 objects_json TEXT,
                 status TEXT,
                 created_at TEXT)"""
        )
        con.executemany(
            """INSERT INTO brainlive_deep_vision_observations_v161
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (
                    "deep-old", "me", "session-old", "frame-old",
                    "2026-07-20T08:00:00+00:00", "chambre",
                    '["lunettes"]', "ok", "2026-07-20T08:00:00+00:00",
                ),
                (
                    "deep-new", "me", "session-new", "frame-new",
                    "2026-07-22T18:00:00+00:00", "salon",
                    '[{"label":"lunettes"}]', "ok",
                    "2026-07-22T18:00:00+00:00",
                ),
            ],
        )
        con.commit()

    result = brain.find_entity_record("où sont mes lunettes ?")

    assert result is not None
    assert result["source"] == "deep_vision_last_seen"
    assert result["place_hint"] == "salon"
    assert result["last_bbox"] is None
    assert result["visible"] is False
    assert "deep-new" in result["evidence"][0]


def _delta(frame_id: str, bbox, *, width=576, height=1024):
    return {
        "session_id": "bbox-session",
        "source_frame_id": frame_id,
        "frame_width": width,
        "frame_height": height,
        "rotation": 90,
        "mirrored": True,
        "coordinate_space": "detector_pixels",
        "entities": [{
            "track_id": "glasses-track",
            "kind": "object",
            "label": "glasses",
            "bbox": bbox,
            "confidence": 0.9,
            "visibility": 1.0,
            "age": 3,
        }],
        "relations": [],
        "changes": [],
        "map_quality": 0.0,
        "evidence_refs": [f"frame:{frame_id}"],
    }


def _brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    return worldbrain.WorldBrain(
        person_id="me",
        live_session_id="bbox-session",
        db_path=db_path,
        service_db_path=db_path,
        config=worldbrain.WorldBrainConfig(
            promote_min_observations=1,
            promote_min_confidence=0.3,
        ),
        publish_world_state=False,
    ), db_path


@pytest.mark.parametrize(
    ("raw", "width", "height", "expected", "status"),
    [
        ([500, 900, 100, 200], 576, 1024, (100.0, 200.0, 500.0, 900.0), "normalized"),
        ([-20, -5, 640, 1100], 576, 1024, (0.0, 0.0, 576.0, 1024.0), "normalized"),
        ([10, 20, 100, 200], 1024, 576, (10.0, 20.0, 100.0, 200.0), "valid"),
    ],
)
def test_detector_bbox_is_ordered_and_clamped_to_real_frame(
    raw, width, height, expected, status
):
    checked = sanitize_detector_bbox(
        raw, frame_width=width, frame_height=height, require_dimensions=True
    )
    assert checked.bbox == expected
    assert checked.status == status


@pytest.mark.parametrize(
    "raw",
    [
        [10, 10, 10, 30],
        [float("nan"), 0, 10, 10],
        None,
    ],
)
def test_invalid_detector_bbox_is_rejected(raw):
    checked = sanitize_detector_bbox(
        raw, frame_width=576, frame_height=1024, require_dimensions=True
    )
    assert checked.bbox is None
    assert checked.status == "rejected"


def test_visionrt_emits_detector_geometry_and_preserves_raw_audit():
    runtime = object.__new__(visionrt.VisionRT)
    runtime.session_id = "bbox-session"
    runtime.scene_ttl_ms = 1000
    runtime._prev_track_ids = set()
    runtime._changes_paused = False
    runtime.on_scene_delta = None
    runtime.metrics = SimpleNamespace(scene_delta_count=0)
    track = SimpleNamespace(
        track_id="g1",
        kind="object",
        label="glasses",
        box=[620.0, 900.0, -20.0, 200.0],
        score=0.9,
        visibility=1.0,
        age=2,
    )

    delta = runtime._emit_scene_delta(
        "frame-1",
        [track],
        frame_width=576,
        frame_height=1024,
        rotation=90,
        mirrored=True,
    )

    assert delta["frame_width"] == 576
    assert delta["frame_height"] == 1024
    assert delta["rotation"] == 90
    assert delta["mirrored"] is True
    assert delta["coordinate_space"] == "detector_pixels"
    assert delta["entities"][0]["bbox"] == [0.0, 200.0, 576.0, 900.0]
    assert delta["entities"][0]["bbox_audit"]["bbox_raw"] == [
        620.0, 900.0, -20.0, 200.0
    ]


def test_rejected_bbox_cannot_create_false_movement_or_relation(
    tmp_path, monkeypatch
):
    brain, db_path = _brain(tmp_path, monkeypatch)
    first = brain.ingest_scene_delta(_delta("f1", [10, 10, 80, 80]))
    assert first["promoted"]
    before = next(iter(brain.entities.values())).last_bbox

    rejected = brain.ingest_scene_delta(_delta("f2", [900, 100, 950, 200]))

    assert next(iter(brain.entities.values())).last_bbox == before
    assert not any(change["type"] == "moved" for change in rejected["changes"])
    assert rejected["relations"] == []
    assert brain.metrics["bbox_rejected"] == 1
    with sqlite3.connect(db_path) as con:
        audit = con.execute(
            """SELECT status, frame_width, frame_height, rotation, mirrored
               FROM worldbrain_bbox_audit WHERE frame_id='f2'"""
        ).fetchone()
    assert audit == ("rejected", 576, 1024, 90, 1)


def test_true_movement_still_uses_detector_frame_not_thumbnail(
    tmp_path, monkeypatch
):
    brain, _ = _brain(tmp_path, monkeypatch)
    brain.ingest_scene_delta(_delta("f1", [10, 10, 80, 80]))
    moved = brain.ingest_scene_delta(_delta("f2", [450, 800, 540, 980]))

    assert any(change["type"] == "moved" for change in moved["changes"])
    bbox = next(iter(brain.entities.values())).last_bbox
    assert bbox == (450.0, 800.0, 540.0, 980.0)
    assert bbox[2] > 304 and bbox[3] > 540


def test_multi_object_relations_use_only_valid_boxes(tmp_path, monkeypatch):
    brain, _ = _brain(tmp_path, monkeypatch)
    delta = _delta("multi", [40, 40, 200, 400])
    delta["entities"].append({
        "track_id": "phone-track",
        "kind": "object",
        "label": "cell phone",
        "bbox": [80, 160, 120, 220],
        "confidence": 0.9,
        "visibility": 1.0,
        "age": 3,
    })
    delta["entities"].append({
        "track_id": "bad-track",
        "kind": "object",
        "label": "bag",
        "bbox": [-100, 50, -10, 200],
        "confidence": 0.9,
        "visibility": 1.0,
        "age": 3,
    })

    result = brain.ingest_scene_delta(delta)

    assert len(result["promoted"]) == 2
    assert all(
        relation["subject"] != "bad-track"
        and relation["object"] != "bad-track"
        for relation in result["relations"]
    )


def test_targeted_vlm_bbox_maps_crop_to_real_screen_without_default_box():
    mapped = visionrt.VisionRT._vlm_bbox_to_screen(
        [100, 200, 700, 800],
        crop_bbox=[100, 50, 500, 450],
        frame_width=1000,
        frame_height=500,
    )
    assert mapped == {"x": 0.14, "y": 0.26, "w": 0.24, "h": 0.48}
    assert visionrt.VisionRT._vlm_bbox_to_screen(
        [0, 0, 0, 0],
        crop_bbox=None,
        frame_width=1000,
        frame_height=500,
    ) is None


def test_detector_focus_bbox_maps_back_from_crop_pixels():
    mapped = visionrt.VisionRT._crop_pixel_bbox_to_screen(
        [20, 10, 120, 110],
        crop_bbox=[200, 100, 600, 400],
        frame_width=1000,
        frame_height=500,
    )
    assert mapped == {"x": 0.22, "y": 0.22, "w": 0.1, "h": 0.2}


def test_targeted_vlm_sighting_updates_durable_last_position(
    tmp_path, monkeypatch
):
    brain, db_path = _brain(tmp_path, monkeypatch)
    first = brain.record_semantic_sighting(
        label="lunettes",
        bbox=[100, 200, 300, 400],
        frame_width=576,
        frame_height=1024,
        frame_id="vlm-1",
        confidence=0.55,
    )
    second = brain.record_semantic_sighting(
        label="lunettes",
        bbox=[250, 300, 500, 700],
        frame_width=576,
        frame_height=1024,
        frame_id="vlm-2",
        confidence=0.6,
    )

    assert second["entity_id"] == first["entity_id"]
    assert second["last_bbox"] == [250.0, 300.0, 500.0, 700.0]
    assert second["observation_count"] == 2
    assert second["truth_level"] == "probable"
    assert second["source"] == "targeted_vlm"
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            """SELECT observation_count,truth_level,source,last_bbox_json
               FROM worldbrain_entity_registry_v19 WHERE entity_id=?""",
            (second["entity_id"],),
        ).fetchone()
    assert row[:3] == (2, "probable", "targeted_vlm")
    assert row[3] == "[250.0, 300.0, 500.0, 700.0]"
