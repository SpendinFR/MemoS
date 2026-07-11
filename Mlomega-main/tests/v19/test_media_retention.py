"""E54 — media retention & disk budget, over the REAL tables.

These tests prove the invariants of ``services/live-pc/media_retention.py`` on the
actual V18/V19 schema (no hardware):

1. **referenced is never selected** — a keyframe cited by a ``visual_events_v19``
   evidence ref is never age-purged nor budget-evicted, even when it is the oldest.
2. **unreferenced age-purge** — an unreferenced keyframe older than
   ``retention_days`` is deleted (file + rows); a referenced one of the same age is
   kept.
3. **budget eviction, oldest-first, protects referenced** — over budget, the oldest
   unreferenced media is evicted first; a fully-referenced overshoot deletes nothing
   and WARNs.
4. **no-op under quota** — under budget with everything young, nothing is deleted.
5. **transcode reversible** — WAV → Opus keeps the original sha in metadata and
   repoints the DB; skipped honestly (no crash) when ffmpeg is absent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mr = _load("v19_media_retention", "services/live-pc/media_retention.py")


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "e54.db"))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_EVIDENCE", str(tmp_path / "raw" / "evidence"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    from mlomega_audio_elite.db import init_db
    from mlomega_audio_elite.brainlive_v15 import ensure_brainlive_schema
    from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema

    init_db()
    ensure_brainlive_schema()
    ensure_v19_visual_schema()


def _iso(day: str) -> str:
    return f"{day}T10:00:00+00:00"


def _make_keyframe(tmp_path, *, frame_id: str, captured_day: str, size: int = 4096) -> Path:
    """Write a real keyframe file + its vision_frames/raw_assets rows."""
    from mlomega_audio_elite.v19_keyframes import register_xr_keyframe

    media = tmp_path / "media" / "keyframes" / captured_day
    media.mkdir(parents=True, exist_ok=True)
    path = media / f"{frame_id}.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"k" * (size - 3))  # jpeg-ish bytes
    register_xr_keyframe(
        person_id="me", live_session_id="sess-1", image_path=str(path),
        captured_at=_iso(captured_day), frame_id=frame_id,
    )
    return path


def _reference_keyframe(frame_id: str, *, occurred_day: str) -> None:
    """Cite a keyframe as evidence in a visual_events_v19 row (the real link)."""
    from mlomega_audio_elite.v19_visual_store import store_visual_event

    store_visual_event({
        "memory_owner_id": "me", "live_session_id": "sess-1",
        "event_type": "entity_last_seen", "occurred_at": _iso(occurred_day),
        "entity": {"entity_id": "ent-1", "label": "mug"},
        "truth_level": "observed", "confidence": 0.9,
        "evidence": [f"frame:{frame_id}"],
        "provenance": {"producer": "test"},
    })


# ===================================================== 1. referenced never selected
def test_referenced_keyframe_never_selected(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ref = _make_keyframe(tmp_path, frame_id="kf-ref", captured_day="2000-01-01")  # ancient
    _reference_keyframe("kf-ref", occurred_day="2000-01-01")

    cfg = mr.RetentionConfig(total_gb=100, retention_days=1, transcode_audio=False)
    ret = mr.MediaRetention(person_id="me", config=cfg, db_path=None)

    inv = ret.inventory()
    ref_item = next(i for i in inv if i.path == str(ref))
    assert ref_item.referenced is True

    report = ret.run(transcode=False)
    assert ref.exists(), "a referenced keyframe must never be purged"
    assert report["purged_aged"] == 0


# ===================================================== 2. unreferenced age-purge
def test_unreferenced_aged_purged_referenced_kept(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    old_unref = _make_keyframe(tmp_path, frame_id="kf-old", captured_day="2000-01-01")
    old_ref = _make_keyframe(tmp_path, frame_id="kf-oldref", captured_day="2000-01-01")
    _reference_keyframe("kf-oldref", occurred_day="2000-01-01")

    cfg = mr.RetentionConfig(total_gb=100, retention_days=30, transcode_audio=False)
    report = mr.MediaRetention(person_id="me", config=cfg, db_path=None).run(transcode=False)

    assert not old_unref.exists(), "unreferenced aged keyframe should be purged"
    assert old_ref.exists(), "referenced keyframe of same age must be kept"
    assert report["purged_aged"] == 1

    # Rows removed coherently for the purged one, kept for the referenced one.
    from mlomega_audio_elite.db import connect
    with connect() as con:
        assert con.execute("SELECT 1 FROM vision_frames WHERE frame_id='kf-old'").fetchone() is None
        assert con.execute("SELECT 1 FROM vision_frames WHERE frame_id='kf-oldref'").fetchone() is not None


# ===================================================== 3. budget eviction oldest-first
def test_budget_evicts_oldest_unreferenced_first(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    big = 200_000
    # Three unreferenced keyframes, different ages; tiny budget forces eviction.
    old = _make_keyframe(tmp_path, frame_id="kf-a-old", captured_day="2001-01-01", size=big)
    mid = _make_keyframe(tmp_path, frame_id="kf-b-mid", captured_day="2005-01-01", size=big)
    new = _make_keyframe(tmp_path, frame_id="kf-c-new", captured_day="2010-01-01", size=big)

    # Budget below total (~0.6 MB), above two items — evict just the oldest.
    total_gb = (big * 2.5) / (1024 ** 3)
    cfg = mr.RetentionConfig(total_gb=total_gb, warn_gb=0, retention_days=100000, transcode_audio=False)
    report = mr.MediaRetention(person_id="me", config=cfg, db_path=None).run(transcode=False)

    assert not old.exists(), "oldest unreferenced evicted first"
    assert mid.exists() and new.exists(), "newer media kept once under budget"
    assert report["evicted_budget"] == 1


def test_budget_never_evicts_referenced_overshoot_warns(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    big = 200_000
    a = _make_keyframe(tmp_path, frame_id="kf-r1", captured_day="2001-01-01", size=big)
    b = _make_keyframe(tmp_path, frame_id="kf-r2", captured_day="2002-01-01", size=big)
    _reference_keyframe("kf-r1", occurred_day="2001-01-01")
    _reference_keyframe("kf-r2", occurred_day="2002-01-01")

    # Budget below total but everything is referenced → nothing deleted, WARN.
    cfg = mr.RetentionConfig(total_gb=(big / (1024 ** 3)), retention_days=100000, transcode_audio=False)
    report = mr.MediaRetention(person_id="me", config=cfg, db_path=None).run(transcode=False)

    assert a.exists() and b.exists(), "referenced media never evicted even over budget"
    assert report["evicted_budget"] == 0
    assert any("referenced" in w for w in report["warnings"])


# ===================================================== 4. no-op under quota
def test_noop_under_quota(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    kf = _make_keyframe(tmp_path, frame_id="kf-young", captured_day="2099-01-01")  # future = young

    cfg = mr.RetentionConfig(total_gb=100, retention_days=90, transcode_audio=False)
    report = mr.MediaRetention(person_id="me", config=cfg, db_path=None).run(transcode=False)

    assert kf.exists()
    assert report["purged_aged"] == 0
    assert report["evicted_budget"] == 0


def test_inventory_and_evidence_are_strictly_owner_scoped(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    mine = _make_keyframe(tmp_path, frame_id="kf-mine", captured_day="2000-01-01")
    from mlomega_audio_elite.v19_keyframes import register_xr_keyframe
    other = tmp_path / "media" / "other.jpg"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"other")
    register_xr_keyframe(
        person_id="other", live_session_id="other-session", image_path=str(other),
        captured_at=_iso("2000-01-01"), frame_id="kf-other",
    )
    # Another owner citing our token must neither protect nor expose our media.
    from mlomega_audio_elite.v19_visual_store import store_visual_event
    store_visual_event({
        "memory_owner_id": "other", "live_session_id": "other-session",
        "event_type": "object_seen", "occurred_at": _iso("2000-01-01"),
        "truth_level": "observed", "confidence": 1.0,
        "evidence": ["frame:kf-mine"],
    })
    ret = mr.MediaRetention(
        person_id="me",
        config=mr.RetentionConfig(total_gb=100, retention_days=1, transcode_audio=False),
    )
    inventory = ret.inventory()
    assert {item.path for item in inventory} == {str(mine)}
    ret.run(transcode=False)
    assert not mine.exists(), "other-owner evidence must not protect this owner's unreferenced media"
    assert other.exists(), "a retention pass must not touch another owner's file"


# ===================================================== 5. transcode reversible
def _archive_wav(tmp_path):
    import numpy as np
    from mlomega_audio_elite.brainlive_v15 import start_live_session

    aa = _load("v19_audio_archive", "services/live-pc/audio_archive.py")
    sess = start_live_session(person_id="me", title="e54 audio", mode="live_xr")
    sid = sess["live_session_id"]
    arc = aa.AudioArchive(person_id="me", live_session_id=sid)
    t = np.arange(16000, dtype=np.float32) / 16000.0
    seg = (0.4 * np.sin(2 * np.pi * 180.0 * t)).astype(np.float32)
    res = arc.archive_segment(seg, absolute_start=_iso("2020-01-01"), source_event_id="ev-1")
    assert res.archived, res.reason
    return Path(res.wav_path)


@pytest.mark.skipif(not mr.ffmpeg_available(), reason="ffmpeg not available")
def test_transcode_reversible_repoints_and_keeps_sha(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    wav = _archive_wav(tmp_path)
    assert wav.exists()

    from mlomega_audio_elite.db import connect
    with connect() as con:
        before = con.execute(
            """SELECT source_sha256 FROM brainlive_sensor_events
               WHERE source_path=? AND modality='audio' AND event_type='speech_segment'""",
            (str(wav.resolve()),),
        ).fetchone()
    orig_sha = before["source_sha256"] if before else None
    assert orig_sha, "sensor event should carry the original WAV sha"

    cfg = mr.RetentionConfig(transcode_audio=True)
    report = mr.RetentionReport()
    mr.MediaRetention(person_id="me", config=cfg, db_path=None).transcode_audio_chunks(report)

    assert report.transcoded == 1
    assert not wav.exists(), "WAV removed only after Opus exists"
    opus = wav.with_suffix(".opus")
    assert opus.exists()

    from mlomega_audio_elite.utils import json_loads
    with connect() as con:
        row = con.execute(
            "SELECT chunk_path, source_path, speaker_json FROM brainlive_audio_segments_v154 WHERE segment_id IS NOT NULL LIMIT 1"
        ).fetchone()
    assert str(row["chunk_path"]).endswith(".opus")
    meta = json_loads(row["speaker_json"], {}) or {}
    assert meta.get("transcode", {}).get("original_sha256") == orig_sha


def test_transcode_disabled_by_config_is_noop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    wav = _archive_wav(tmp_path)
    cfg = mr.RetentionConfig(transcode_audio=False)
    report = mr.RetentionReport()
    mr.MediaRetention(person_id="me", config=cfg, db_path=None).transcode_audio_chunks(report)
    assert wav.exists(), "disabled transcode keeps the WAV untouched"
    assert report.transcoded == 0
