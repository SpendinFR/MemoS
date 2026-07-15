from __future__ import annotations

"""E64-I4.1 Deep Vision selection WITH coverage.

The historical selector sampled keyframes by even index spacing (a quota) and
silently dropped every other frame with no trace. These tests prove the new
policy:

* a real scene/object/person change opens a keyframe;
* repeated identical frames do NOT each become keyframes, but every one of them
  is covered by the representative keyframe/atom;
* OCR (visible text) forces a keyframe;
* an explicit user request linked to a frame forces a keyframe;
* a long unchanging span still gets a safety-interval keyframe;
* the selection manifest proves 100% of frames are selected OR represented -
  zero orphans;
* it is NOT a quota: a change-rich session yields more keyframes than a static
  one.

No LLM/VLM is called - selection is deterministic. Coverage persistence is
exercised against a monkeypatched MLOMEGA_DB and the raw frames are never
mutated.
"""

import pytest

from mlomega_audio_elite.night_orchestrator.deep_vision_selection import (
    COVERAGE_TABLE,
    REASON_OCR,
    REASON_SAFETY_INTERVAL,
    REASON_SCENE_CHANGE,
    REASON_USER_REQUEST,
    coverage_manifest,
    ensure_coverage_schema,
    persist_frame_coverage,
    select_keyframes_with_coverage,
)


# --------------------------------------------------------------------------- #
# Builders that produce the bundle/timeline/candidate shapes the real path uses #
# --------------------------------------------------------------------------- #

def _obs_item(idx, *, ts, objects, people=1, visible_text=None, user_requested=False, location="office", summary=None):
    """One semantic vision_scene_observations timeline item (assembler shape).

    ``summary`` follows the STATE, not the frame index (as in real data, where a
    static scene keeps the same summary while confidence-only jitter varies). A
    per-index summary would artificially split every frame into its own atom.
    """
    return {
        "source_table": "vision_scene_observations",
        "source_id": f"obs_{idx}",
        "frame_id": f"frame_{idx}",
        "time": ts,
        "objects": objects,
        "people_count": people,
        "visible_text": visible_text or [],
        "location_hint": location,
        "summary": summary,
        **({"user_requested": True} if user_requested else {}),
    }


def _candidate(idx, *, ts, exists=True):
    """One raw-pixel candidate (base module _keyframe_candidates shape)."""
    return {
        "bundle_id": "b1",
        "live_session_id": "sess1",
        "frame_id": f"frame_{idx}",
        "image_path": f"/fake/frame_{idx}.jpg",
        "frame_time": ts,
        "index": idx,
        "exists": exists,
    }


def _bundle(items):
    return {
        "bundle_id": "b1",
        "person_id": "me",
        "package_date": "2026-07-14",
        "live_session_id": "sess1",
        "vision_timeline_json": items,
    }


def _ts(sec):
    return f"2026-07-14T08:29:{sec:02d}+00:00"


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #

def test_scene_object_person_change_opens_keyframe():
    person = [{"label": "person", "track_id": "t1"}]
    person_plus_dog = [{"label": "person", "track_id": "t1"}, {"label": "dog", "track_id": "t2"}]
    items = [
        _obs_item(0, ts=_ts(0), objects=person),
        _obs_item(1, ts=_ts(2), objects=person),          # identical -> represented
        _obs_item(2, ts=_ts(4), objects=person_plus_dog), # new object -> keyframe
        _obs_item(3, ts=_ts(6), objects=person),          # dog left -> keyframe
    ]
    cands = [_candidate(i, ts=_ts(t)) for i, t in ((0, 0), (1, 2), (2, 4), (3, 6))]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)

    assert "frame_0" in result.selected_frame_ids  # first state
    assert "frame_2" in result.selected_frame_ids  # object appeared
    assert "frame_3" in result.selected_frame_ids  # object left
    assert "frame_1" not in result.selected_frame_ids  # identical to frame_0
    assert REASON_SCENE_CHANGE in result.reasons_by_frame["frame_2"]


def test_repeated_identical_frames_are_covered_not_reselected():
    person = [{"label": "person", "track_id": "t1"}]
    items = [_obs_item(i, ts=_ts(i), objects=person) for i in range(6)]
    cands = [_candidate(i, ts=_ts(i)) for i in range(6)]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)

    # A single static state -> exactly one keyframe, never one per frame.
    assert result.selected_count == 1
    assert result.total_frames == 6
    # Every non-selected frame points to the representative keyframe/atom.
    represented = [c for c in result.coverage if not c.is_keyframe]
    assert len(represented) == 5
    for cov in represented:
        assert cov.covered_by_keyframe_id == "frame_0"
        assert cov.covered_by_atom_id  # atom stands in for the run
    assert result.fully_covered


def test_ocr_visible_text_forces_keyframe():
    person = [{"label": "person", "track_id": "t1"}]
    items = [
        _obs_item(0, ts=_ts(0), objects=person),
        _obs_item(1, ts=_ts(2), objects=person),                            # identical
        _obs_item(2, ts=_ts(4), objects=person, visible_text=["EXIT 4A"]),  # OCR
    ]
    cands = [_candidate(i, ts=_ts(t)) for i, t in ((0, 0), (1, 2), (2, 4))]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)

    assert "frame_2" in result.selected_frame_ids
    assert REASON_OCR in result.reasons_by_frame["frame_2"]


def test_explicit_user_request_forces_keyframe():
    person = [{"label": "person", "track_id": "t1"}]
    items = [
        _obs_item(0, ts=_ts(0), objects=person),
        _obs_item(1, ts=_ts(2), objects=person, user_requested=True),  # "c'est quoi ça"
    ]
    cands = [_candidate(i, ts=_ts(t)) for i, t in ((0, 0), (1, 2))]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)

    assert "frame_1" in result.selected_frame_ids
    assert REASON_USER_REQUEST in result.reasons_by_frame["frame_1"]


def test_user_request_via_frame_id_channel():
    """A request naming a frame_id (real sensor/timeline event) also promotes."""
    person = [{"label": "person", "track_id": "t1"}]
    items = [_obs_item(i, ts=_ts(i * 2), objects=person) for i in range(3)]
    cands = [_candidate(i, ts=_ts(i * 2)) for i in range(3)]
    result = select_keyframes_with_coverage(
        _bundle(items), cands, requested_frame_ids={"frame_2"}, safety_interval_s=999
    )
    assert "frame_2" in result.selected_frame_ids
    assert REASON_USER_REQUEST in result.reasons_by_frame["frame_2"]


def test_long_static_span_gets_safety_interval_keyframe():
    person = [{"label": "person", "track_id": "t1"}]
    # 5 identical frames spaced 30s apart, safety interval 60s -> anchors at
    # t=0 (first) and again once >=60s have elapsed.
    times = [0, 30, 60, 90, 120]
    items = [_obs_item(i, ts=_ts_min(t), objects=person) for i, t in enumerate(times)]
    cands = [_candidate(i, ts=_ts_min(t)) for i, t in enumerate(times)]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=60)

    # First frame anchors; the safety interval must add at least one more.
    assert result.selected_count >= 2
    safety = [f for f, rs in result.reasons_by_frame.items() if REASON_SAFETY_INTERVAL in rs]
    assert safety, "a long unchanging span must yield a safety-interval keyframe"
    assert result.fully_covered


def test_manifest_proves_full_coverage_zero_orphans():
    person = [{"label": "person", "track_id": "t1"}]
    dog = [{"label": "person", "track_id": "t1"}, {"label": "dog", "track_id": "t2"}]
    items = [
        _obs_item(0, ts=_ts(0), objects=person),
        _obs_item(1, ts=_ts(2), objects=person),
        _obs_item(2, ts=_ts(4), objects=dog, visible_text=["SIGN"]),
        _obs_item(3, ts=_ts(6), objects=dog),
        _obs_item(4, ts=_ts(8), objects=person),
    ]
    cands = [_candidate(i, ts=_ts(i * 2)) for i in range(5)]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)
    manifest = coverage_manifest(result)

    assert manifest["ok"] is True
    assert manifest["orphan_frames"] == []
    assert manifest["selected_keyframes"] + manifest["represented_frames"] == manifest["total_frames"] == 5


def test_not_a_quota_richer_session_yields_more_keyframes():
    person = [{"label": "person", "track_id": "t1"}]

    static_items = [_obs_item(i, ts=_ts(i), objects=person) for i in range(8)]
    static_cands = [_candidate(i, ts=_ts(i)) for i in range(8)]
    static = select_keyframes_with_coverage(_bundle(static_items), static_cands, safety_interval_s=999)

    # A session where the object set changes on every frame.
    rich_items = []
    rich_cands = []
    for i in range(8):
        objs = [{"label": "person", "track_id": "t1"}]
        if i % 2 == 0:
            objs.append({"label": f"obj{i}", "track_id": f"o{i}"})
        rich_items.append(_obs_item(i, ts=_ts(i), objects=objs))
        rich_cands.append(_candidate(i, ts=_ts(i)))
    rich = select_keyframes_with_coverage(_bundle(rich_items), rich_cands, safety_interval_s=999)

    assert static.selected_count == 1
    assert rich.selected_count > static.selected_count
    assert static.fully_covered and rich.fully_covered


def test_persist_coverage_is_additive_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "sel.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))

    from mlomega_audio_elite.db import connect

    person = [{"label": "person", "track_id": "t1"}]
    items = [_obs_item(i, ts=_ts(i), objects=person) for i in range(4)]
    cands = [_candidate(i, ts=_ts(i)) for i in range(4)]
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)

    with connect() as con:
        ensure_coverage_schema(con)
        n1 = persist_frame_coverage(con, person_id="me", package_date="2026-07-14", result=result)
        con.commit()
        n2 = persist_frame_coverage(con, person_id="me", package_date="2026-07-14", result=result)
        con.commit()
        rows = con.execute(f"SELECT frame_id,is_keyframe FROM {COVERAGE_TABLE}").fetchall()

    assert n1 == n2 == 4
    # Idempotent: rerun upserts, does not duplicate.
    assert len(rows) == 4
    keyframes = [r for r in rows if r["is_keyframe"]]
    assert len(keyframes) == 1


def test_base_module_select_keyframes_uses_coverage_policy(tmp_path, monkeypatch):
    """The real path (base module) delegates to the coverage policy and persists."""
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "base.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))

    from mlomega_audio_elite import brainlive_offline_deep_vision_v16_1 as base
    from mlomega_audio_elite.db import connect

    person = [{"label": "person", "track_id": "t1"}]
    dog = [{"label": "person", "track_id": "t1"}, {"label": "dog", "track_id": "t2"}]
    # Two distinct states, both with readable images.
    items = [
        {"source_table": "vision_scene_observations", "source_id": "o0", "frame_id": "frame_0",
         "image_path": "/fake/frame_0.jpg", "time": _ts(0), "objects": person, "people_count": 1, "visible_text": [], "summary": "a"},
        {"source_table": "vision_scene_observations", "source_id": "o1", "frame_id": "frame_1",
         "image_path": "/fake/frame_1.jpg", "time": _ts(2), "objects": person, "people_count": 1, "visible_text": [], "summary": "a"},
        {"source_table": "vision_scene_observations", "source_id": "o2", "frame_id": "frame_2",
         "image_path": "/fake/frame_2.jpg", "time": _ts(4), "objects": dog, "people_count": 1, "visible_text": [], "summary": "b"},
    ]
    bundle = {
        "bundle_id": "b1", "person_id": "me", "package_date": "2026-07-14",
        "live_session_id": "sess1", "brain2_conversation_id": None,
        "vision_timeline_json": __import__("json").dumps(items),
    }

    # Force candidates to be "readable" without touching disk: patch _image_exists.
    monkeypatch.setattr(base, "_image_exists", lambda p: bool(p))

    selected = base.select_keyframes_for_bundle(bundle, max_keyframes=12)
    frame_ids = {f.get("frame_id") for f in selected}

    # Two distinct states -> two keyframes; the repeated one is not reselected.
    assert frame_ids == {"frame_0", "frame_2"}
    assert all("sample_index" in f and "sample_reason" in f for f in selected)

    # Coverage of all three frames was persisted (additive), zero orphans.
    with connect() as con:
        rows = con.execute(
            "SELECT frame_id,is_keyframe,covered_by_keyframe_id FROM deep_vision_frame_coverage_v19 ORDER BY frame_id"
        ).fetchall()
    assert len(rows) == 3
    covered_repeat = [r for r in rows if r["frame_id"] == "frame_1"][0]
    assert not covered_repeat["is_keyframe"]
    assert covered_repeat["covered_by_keyframe_id"] == "frame_0"


def test_optional_ceiling_demotes_overflow_without_dropping_frames():
    """A hard ceiling keeps coverage 100% by demoting overflow keyframes."""
    from mlomega_audio_elite.night_orchestrator.deep_vision_selection import (
        apply_max_keyframes_ceiling,
    )

    # 5 distinct states -> 5 keyframes; cap at 2 must keep 2, demote 3, cover all.
    items = []
    cands = []
    for i in range(5):
        objs = [{"label": "person", "track_id": "t1"}, {"label": f"obj{i}", "track_id": f"o{i}"}]
        items.append(_obs_item(i, ts=_ts(i), objects=objs))
        cands.append(_candidate(i, ts=_ts(i)))
    result = select_keyframes_with_coverage(_bundle(items), cands, safety_interval_s=999)
    assert result.selected_count == 5

    capped = apply_max_keyframes_ceiling(result, 2)
    assert capped.selected_count == 2
    # No frame dropped: still 5 accounted, zero orphans.
    assert capped.total_frames == 5
    assert capped.fully_covered
    manifest = coverage_manifest(capped)
    assert manifest["selected_keyframes"] + manifest["represented_frames"] == 5


def _ts_min(total_seconds):
    m, s = divmod(total_seconds, 60)
    return f"2026-07-14T08:{29 + m:02d}:{s:02d}+00:00"
