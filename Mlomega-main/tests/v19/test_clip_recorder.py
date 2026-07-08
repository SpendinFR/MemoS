"""E55 — clip recorder + tiering, on the REAL V19 tables.

These tests prove the FROZEN §E55 invariants of
``services/live-pc/clip_recorder.py`` (no live WebRTC needed):

1. **drop-on-full never blocks** — with a full bounded queue, ``offer`` returns
   immediately (False) and increments the drop counter; the live thread is never
   blocked and never sees an exception.
2. **segment written + indexed** — a real ffmpeg encode of synthetic BGR frames
   produces an MP4 whose row lands in ``visual_evidence_assets_v19`` with the
   columns ``replay_service`` selects (skipped, marked, if ffmpeg is absent).
3. **replay finds the clip** — the exact query of ``replay_service.assemble_bundle``
   (person_id + captured_at window + asset_kind IN ('clip','video','gif') + uri)
   returns the indexed clip with NO change to the store.
4. **tiering keeps interesting / drops boring** — a clip whose window contains a
   visual event (or is referenced) is KEPT; a young, boring, unreferenced one is
   dropped (file + asset row).
5. **best-effort** — a broken ffmpeg (bad binary) never raises out of the
   recorder; the session/capture are unaffected.
"""

from __future__ import annotations

import importlib.util
import queue
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src", ROOT / "services" / "live-pc"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

np = pytest.importorskip("numpy")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cr = _load("v19_clip_recorder", "services/live-pc/clip_recorder.py")


def _env(tmp_path, monkeypatch):
    """Isolate DB + media root into tmp_path so nothing touches the real store."""
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "e55.db"))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_EVIDENCE", str(tmp_path / "raw" / "evidence"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_MEDIA", str(tmp_path / "media"))
    from mlomega_audio_elite.db import init_db
    from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema

    init_db()
    ensure_v19_visual_schema()


def _frame(h=120, w=160, val=None):
    if val is None:
        return (np.random.rand(h, w, 3) * 255).astype(np.uint8)
    return np.full((h, w, 3), val, dtype=np.uint8)


# ===================================================== 1. drop-on-full never blocks
def test_offer_drops_on_full_without_blocking(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    cfg = cr.RecorderConfig(enabled=True, queue_max_frames=2, target_fps=1000)
    rec = cr.ClipRecorder(person_id="me", session_id="s1", config=cfg)
    # Do NOT start the pump thread: the queue never drains, so it fills and stays
    # full. Any further offer must drop immediately, never block.
    frame = _frame()
    accepted = 0
    dropped = 0
    for i in range(50):
        # target_fps=1000 => ~1ms decimation; sleep a hair so frames are accepted
        # until the queue is full, then all drop.
        time.sleep(0.002)
        t0 = time.perf_counter()
        ok = rec.offer(frame, capture_ns=None)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.05, "offer must return immediately (non-blocking)"
        accepted += int(ok)
        dropped += int(not ok)
    assert rec._queue.full(), "queue should have saturated"
    assert rec.metrics.frames_dropped > 0, "full queue must count drops"
    assert accepted <= cfg.queue_max_frames + 1
    assert dropped > 0


def test_disabled_recorder_is_noop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    rec = cr.ClipRecorder(config=cr.RecorderConfig(enabled=False))
    assert rec.offer(_frame()) is False
    assert rec.metrics.frames_offered == 0
    rec.start()  # no-op
    assert rec._thread is None


# ===================================================== 2/3. segment written+indexed, replay finds
def _replay_query(db_path, person_id, start, end):
    """The EXACT SELECT of replay_service.assemble_bundle (clips branch)."""
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        return [dict(r) for r in con.execute(
            """SELECT visual_asset_id, asset_kind, uri, sha256, captured_at
               FROM visual_evidence_assets_v19
               WHERE person_id=? AND captured_at >= ? AND captured_at <= ?
                 AND asset_kind IN ('clip','video','gif')
               ORDER BY captured_at LIMIT ?""",
            (person_id, start, end, 100),
        ).fetchall()]


@pytest.mark.skipif(not cr.ffmpeg_available(), reason="ffmpeg not installed")
def test_segment_written_indexed_and_replay_finds_it(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # Short segment so it rotates and indexes within the test.
    cfg = cr.RecorderConfig(
        enabled=True, segment_seconds=1, target_fps=10, height=120,
        bitrate_kbps=300, queue_max_frames=200,
    )
    rec = cr.ClipRecorder(person_id="me", session_id="sess-clip", config=cfg)
    rec.start()
    # Feed ~2s of frames; decimation is by capture_ns so advance a virtual clock.
    base = time.monotonic_ns()
    for i in range(40):
        rec.offer(_frame(val=(i * 6) % 255), capture_ns=base + i * 100_000_000)  # 10 fps
    # Give the pump time to rotate at least one 1s segment.
    time.sleep(2.5)
    metrics = rec.stop()

    assert metrics["frames_encoded"] > 0, "ffmpeg should have encoded frames"
    assert metrics["segments_written"] >= 1, "at least one segment must be written"
    assert metrics["segments_indexed"] >= 1, "each written segment must be indexed"

    # The file exists under <media>/clips/AAAA-MM-JJ/.
    clip_files = list((tmp_path / "media" / "clips").rglob("*.mp4"))
    assert clip_files, "an MP4 clip file must exist on disk"
    assert all(f.stat().st_size > 0 for f in clip_files)

    # Replay's exact query finds the clip in a wide window.
    rows = _replay_query(None, "me", "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00")
    assert rows, "replay_service query must return the indexed clip"
    r = rows[0]
    assert r["asset_kind"] == "clip"
    assert r["uri"] and Path(r["uri"]).exists()
    assert r["sha256"], "clip must carry a sha256 for evidence integrity"


# ===================================================== 4. tiering keeps/drops
def _insert_clip_row(db_path, *, asset_id, uri, captured_at, session="sess-t",
                     window_start=None, window_end=None):
    """Index a clip directly (no ffmpeg) to test tiering deterministically."""
    from mlomega_audio_elite.db import connect, write_transaction, upsert
    from mlomega_audio_elite.utils import json_dumps, now_iso

    meta = {"asset_kind": "clip", "window_start": window_start or captured_at,
            "window_end": window_end or captured_at}
    with connect(db_path) as con, write_transaction(con):
        upsert(con, "visual_evidence_assets_v19", {
            "visual_asset_id": asset_id, "person_id": "me", "live_session_id": session,
            "asset_kind": "clip", "uri": uri, "sha256": "deadbeef",
            "frame_id": None, "clip_id": asset_id, "captured_at": captured_at,
            "metadata_json": json_dumps(meta), "created_at": now_iso(),
        }, "visual_asset_id")


def _insert_event(db_path, *, occurred_at, session="sess-t"):
    from mlomega_audio_elite.v19_visual_store import store_visual_event

    return store_visual_event({
        "memory_owner_id": "me", "live_session_id": session,
        "event_type": "entity_last_seen", "occurred_at": occurred_at,
        "entity": {"entity_id": "e1", "label": "person"},
        "truth_level": "observed", "confidence": 0.9,
        "provenance": {"producer": "test"},
    }, db_path=db_path)


def test_tiering_keeps_interesting_drops_boring(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc).replace(microsecond=0)

    def _iso(dt):
        return dt.isoformat(timespec="milliseconds")

    # Two disjoint, young (today) windows so the single event lands in only one.
    boring_start = _iso(base)
    boring_end = _iso(base + timedelta(seconds=30))
    good_start = _iso(base + timedelta(minutes=5))
    good_end = _iso(base + timedelta(minutes=5, seconds=30))
    event_at = _iso(base + timedelta(minutes=5, seconds=10))  # inside the good window only

    media = tmp_path / "media" / "clips" / "today"
    media.mkdir(parents=True, exist_ok=True)

    # (a) BORING: no event in window, unreferenced, young → must be DROPPED.
    boring = media / "boring.mp4"
    boring.write_bytes(b"\x00" * 2048)
    _insert_clip_row(None, asset_id="clip-boring", uri=str(boring.resolve()),
                     captured_at=boring_start, window_start=boring_start, window_end=boring_end)

    # (b) INTERESTING: a visual event falls inside its window → must be KEPT.
    interesting = media / "interesting.mp4"
    interesting.write_bytes(b"\x00" * 2048)
    _insert_clip_row(None, asset_id="clip-good", uri=str(interesting.resolve()),
                     captured_at=good_start, window_start=good_start, window_end=good_end)
    _insert_event(None, occurred_at=event_at)  # inside [good_start, good_end] only

    report = cr.tier_clips_close_day(person_id="me", db_path=None)

    assert report["status"] == "ok", report
    assert not boring.exists(), "boring, unreferenced, young clip must be dropped"
    assert interesting.exists(), "clip with an event in its window must be kept"
    assert report["dropped"] >= 1
    assert report["kept"] >= 1

    # The dropped clip's asset row is gone; the kept one remains.
    from mlomega_audio_elite.db import connect
    with connect() as con:
        assert con.execute(
            "SELECT 1 FROM visual_evidence_assets_v19 WHERE visual_asset_id='clip-boring'"
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM visual_evidence_assets_v19 WHERE visual_asset_id='clip-good'"
        ).fetchone() is not None


# ===================================================== 5. best-effort
def test_bad_ffmpeg_binary_never_raises(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # Force the spawn to fail by pointing ffmpeg at a non-existent binary path.
    cfg = cr.RecorderConfig(enabled=True, segment_seconds=1, target_fps=10)
    rec = cr.ClipRecorder(person_id="me", session_id="bad", config=cfg)
    # Make ffmpeg_available() pass but the actual spawn fail.
    monkeypatch.setattr(cr, "ffmpeg_available", lambda: True)
    real_popen = cr.subprocess.Popen

    def _boom(*a, **k):
        raise FileNotFoundError("ffmpeg missing on PATH")

    monkeypatch.setattr(cr.subprocess, "Popen", _boom)
    rec.start()
    base = time.monotonic_ns()
    for i in range(20):
        # Must never raise even though every segment spawn fails.
        assert rec.offer(_frame(), capture_ns=base + i * 100_000_000) in (True, False)
    time.sleep(0.5)
    metrics = rec.stop()
    monkeypatch.setattr(cr.subprocess, "Popen", real_popen)

    assert metrics["ffmpeg_errors"] >= 1, "spawn failures must be counted, not raised"
    assert metrics["segments_written"] == 0


def test_tiering_best_effort_on_missing_module(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # No clips at all → must return a clean ok report, never raise.
    report = cr.tier_clips_close_day(person_id="me", db_path=None)
    assert report["status"] == "ok"
    assert report["inspected"] == 0
