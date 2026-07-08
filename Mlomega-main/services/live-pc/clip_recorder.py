from __future__ import annotations

"""ClipRecorder — E55: record live video as real MP4 clips, best-effort, tiered.

Goal: be able to *replay the scene as real video* (not only the keyframe
slideshow). Design is **FROZEN** in ``docs/PROD_BACKLOG.md`` §E55 and the hard
non-negotiable constraint drives every choice here:

    the encode must NEVER slow down the live path (BrainLive / VisionRT / ASR).

How that guarantee is met **by construction** (not by hoping the CPU is cheap):

1. **Bounded queue, DROP-on-full.** The live consumer (``gateway._consume_track``)
   calls :meth:`offer` which does a *non-blocking* ``put``. If the queue is full
   the frame is dropped and ``offer`` returns immediately — the live loop never
   blocks, never waits on the encoder, never applies back-pressure.
2. **ffmpeg in a SEPARATE PROCESS at LOW priority.** A dedicated pump *thread*
   owns the ffmpeg ``subprocess`` (rawvideo bgr24 → libx264 veryfast) and feeds
   it via stdin. The heavy work (encode) is a child process reniced to idle/low
   priority, so it competes for CPU only with spare cycles and never with the
   GPU (no NVENC) nor with the asyncio event loop that runs the live pipeline.
3. **Auto-pause on persistent drops.** A sliding-window drop counter; if drops
   stay above threshold the recorder suspends itself (logs it), the live keeps
   running untouched, and it resumes once the pressure clears.
4. **Best-effort everywhere.** ffmpeg absent / crash / broken pipe / DB error:
   captured, counted, logged — *never* raised into the caller. A dead recorder
   degrades to a no-op; the session and the capture are never affected.

Storage: clips land under ``<media_root>/clips/AAAA-MM-JJ/`` (reusing
``visionrt.media_root``; env ``MLOMEGA_MEDIA`` else ``storage/media/``). Eviction
and the disk budget are E54's job (``media_retention.py``); we only *index* each
finished segment into ``visual_evidence_assets_v19`` (asset_kind='clip') so
``replay_service.assemble_bundle`` finds it with NO change.
"""

import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (_ROOT, _ROOT / "src", _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

log = logging.getLogger("mlomega.clip_recorder")


# --------------------------------------------------------------------------- cfg
@dataclass
class RecorderConfig:
    enabled: bool = True
    segment_seconds: int = 120
    target_fps: int = 12
    height: int = 540          # width derived from the real frame aspect ratio
    bitrate_kbps: int = 1000
    queue_max_frames: int = 60
    # Auto-pause: if >= this many drops happen inside the sliding window we
    # suspend recording until the pressure clears.
    drop_pause_threshold: int = 120
    drop_window_seconds: float = 10.0
    drop_resume_seconds: float = 15.0
    # Tiering (close-day): a 'boring', unreferenced clip younger than this many
    # days is dropped to keyframes-only. Older ones are E54's budget problem.
    keep_boring_days: int = 2
    preset: str = "veryfast"

    @property
    def frame_interval_ns(self) -> int:
        fps = max(1, int(self.target_fps))
        return int(1_000_000_000 / fps)


def load_recorder_config(profile_path: str | Path | None = None) -> RecorderConfig:
    """Build a RecorderConfig from a profile's ``clip_recording:`` block.

    Defaults to ``configs/profiles/rtx3070.yaml`` (the VisionRT profile) and
    falls back to coded defaults for any missing key. Never raises."""
    cfg = RecorderConfig()
    path = Path(profile_path) if profile_path else (_ROOT / "configs" / "profiles" / "rtx3070.yaml")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cr = (data.get("clip_recording") or {}) if isinstance(data, dict) else {}
        if isinstance(cr, dict):
            cfg.enabled = bool(cr.get("enabled", cfg.enabled))
            cfg.segment_seconds = int(cr.get("segment_seconds", cfg.segment_seconds))
            cfg.target_fps = int(cr.get("target_fps", cfg.target_fps))
            cfg.height = int(cr.get("height", cfg.height))
            cfg.bitrate_kbps = int(cr.get("bitrate_kbps", cfg.bitrate_kbps))
            cfg.queue_max_frames = int(cr.get("queue_max_frames", cfg.queue_max_frames))
            cfg.drop_pause_threshold = int(cr.get("drop_pause_threshold", cfg.drop_pause_threshold))
            cfg.keep_boring_days = int(cr.get("keep_boring_days", cfg.keep_boring_days))
            if cr.get("preset"):
                cfg.preset = str(cr.get("preset"))
    except Exception:
        pass
    return cfg


# ------------------------------------------------------------------------- utils
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _clips_day_dir(captured_at: str | None = None) -> Path:
    """``<media_root>/clips/AAAA-MM-JJ/`` for the day of ``captured_at`` (UTC)."""
    try:
        from visionrt import media_root  # type: ignore
    except Exception:
        env = os.environ.get("MLOMEGA_MEDIA")
        root = Path(env) if env else (_ROOT / "storage" / "media")
        media_root = lambda: root  # noqa: E731
    day = None
    if captured_at:
        try:
            txt = str(captured_at).strip().replace("Z", "+00:00")
            day = datetime.fromisoformat(txt).astimezone(timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            day = None
    if not day:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return media_root() / "clips" / day


def _low_priority_kwargs() -> dict[str, Any]:
    """Popen kwargs that start the child at LOW priority on this OS.

    Windows: BELOW_NORMAL_PRIORITY_CLASS via creationflags. POSIX: a preexec_fn
    that renices the child to +15 (near-idle). Both are best-effort — if the
    platform hook is missing we still start (nice() is applied post-spawn too)."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        flag = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
        kwargs["creationflags"] = flag
    else:
        def _renice() -> None:  # pragma: no cover - POSIX only
            try:
                os.nice(15)
            except Exception:
                pass
        kwargs["preexec_fn"] = _renice
    return kwargs


def _demote_process(pid: int) -> None:
    """Best-effort second belt: renice the running child to idle via psutil."""
    try:
        import psutil  # type: ignore

        p = psutil.Process(pid)
        if os.name == "nt":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # type: ignore[attr-defined]
        else:
            p.nice(19)
    except Exception:
        pass


def _iso_from_ns(capture_ns: int | None) -> str:
    """Best clip timestamp: monotonic pts ns is not wall-clock, so we anchor on
    wall-clock 'now' (the segment start) and keep pts only for ordering."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------------- store
def _index_clip_asset(
    *,
    person_id: str,
    session_id: str,
    path: Path,
    captured_at: str,
    window_end: str,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    db_path: Any = None,
) -> str | None:
    """Insert one finished clip into ``visual_evidence_assets_v19`` as asset_kind
    ='clip'. Columns match ``replay_service.assemble_bundle``'s SELECT
    (person_id, captured_at window, asset_kind IN ('clip',...), uri, sha256).

    Reuses the core writers (``upsert``/``ensure_v19_visual_schema``) — we do NOT
    touch the store core, only call it. Best-effort: returns the asset id or None."""
    try:
        from mlomega_audio_elite.db import connect, write_transaction, upsert  # type: ignore
        from mlomega_audio_elite.utils import new_id, now_iso, sha256_file  # type: ignore
        from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema  # type: ignore
    except Exception as exc:
        log.warning("clip index: core store unavailable: %s", exc)
        return None
    try:
        sha = sha256_file(path)
    except Exception:
        sha = None
    try:
        ensure_v19_visual_schema(db_path)
        asset_id = new_id("v19clip")
        now = now_iso()
        from mlomega_audio_elite.utils import json_dumps  # type: ignore

        meta = json_dumps({
            "asset_kind": "clip", "codec": "h264", "container": "mp4",
            "width": int(width), "height": int(height), "fps": int(fps),
            "duration_s": round(float(duration_s), 3),
            "window_start": captured_at, "window_end": window_end,
            "producer": "E55.clip_recorder",
        })
        with connect(db_path) as con, write_transaction(con):
            upsert(con, "visual_evidence_assets_v19", {
                "visual_asset_id": asset_id,
                "person_id": person_id,
                "live_session_id": session_id,
                "asset_kind": "clip",
                "uri": str(path.resolve()),
                "sha256": sha,
                "frame_id": None,
                "clip_id": asset_id,
                "captured_at": captured_at,
                "metadata_json": meta,
                "created_at": now,
            }, "visual_asset_id")
        return asset_id
    except Exception as exc:
        log.warning("clip index failed for %s: %s", path.name, exc)
        return None


# ---------------------------------------------------------------------- recorder
@dataclass
class RecorderMetrics:
    frames_offered: int = 0
    frames_encoded: int = 0
    frames_dropped: int = 0
    segments_written: int = 0
    segments_indexed: int = 0
    paused: bool = False
    pause_events: int = 0
    ffmpeg_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames_offered": self.frames_offered,
            "frames_encoded": self.frames_encoded,
            "frames_dropped": self.frames_dropped,
            "segments_written": self.segments_written,
            "segments_indexed": self.segments_indexed,
            "paused": self.paused,
            "pause_events": self.pause_events,
            "ffmpeg_errors": self.ffmpeg_errors,
        }


class ClipRecorder:
    """Encode live frames to segmented MP4 clips in a low-priority ffmpeg process.

    The producer side is :meth:`offer` — non-blocking, drop-on-full. A single
    daemon thread consumes the queue, spawns/feeds ffmpeg per segment, rotates
    segments every ``segment_seconds``, indexes each finished segment, and
    auto-pauses under sustained drop pressure. Construct with :meth:`start`;
    tear down with :meth:`stop`. Never raises out of ``offer``/``start``/``stop``.
    """

    def __init__(
        self,
        *,
        person_id: str = "me",
        session_id: str = "session",
        config: RecorderConfig | None = None,
        db_path: Any = None,
    ) -> None:
        self.person_id = person_id or "me"
        self.session_id = session_id or "session"
        self.config = config or RecorderConfig()
        self.db_path = db_path
        self.metrics = RecorderMetrics()

        self._queue: "queue.Queue[tuple[Any, int] | None]" = queue.Queue(
            maxsize=max(1, int(self.config.queue_max_frames))
        )
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._paused = threading.Event()
        # Sliding-window drop timestamps for auto-pause.
        self._drop_ts: deque[float] = deque()
        self._paused_at: float = 0.0
        self._last_offer_ns: int = 0
        # Per-segment ffmpeg handles (owned by the pump thread only).
        self._proc: subprocess.Popen[bytes] | None = None
        self._seg_path: Path | None = None
        self._seg_started_at: str | None = None
        self._seg_start_wall: float = 0.0
        self._seg_frames: int = 0
        self._width: int = 0
        self._height: int = 0

    # ------------------------------------------------------------------ producer
    def offer(self, frame_bgr: Any, capture_ns: int | None = None) -> bool:
        """Live-thread entry. NON-BLOCKING: enqueue a copy of the decoded BGR
        frame for encoding, or drop it if the queue is full / recorder disabled.

        Returns True if the frame was queued, False if dropped/ignored. This
        method must never block the caller and never raise — the live pipeline
        depends on it returning in microseconds regardless of encoder state."""
        cfg = self.config
        if not cfg.enabled or self._stopped.is_set():
            return False
        self.metrics.frames_offered += 1
        if self._paused.is_set():
            self._maybe_resume()
            if self._paused.is_set():
                self.metrics.frames_dropped += 1
                return False
        # Frame-rate decimation on the cheap side (before the copy): only accept
        # roughly one frame per target interval; the rest are ignored (not counted
        # as pressure drops — they are the intended downsample).
        now_ns = capture_ns if capture_ns is not None else time.monotonic_ns()
        if self._last_offer_ns and (now_ns - self._last_offer_ns) < cfg.frame_interval_ns:
            return False
        try:
            # Copy so the encoder owns immutable pixels even if the live buffer is
            # reused; ``.copy()`` is cheap vs. the encode and keeps us decoupled.
            payload = frame_bgr.copy() if hasattr(frame_bgr, "copy") else frame_bgr
        except Exception:
            self.metrics.frames_dropped += 1
            return False
        try:
            self._queue.put_nowait((payload, now_ns))
            self._last_offer_ns = now_ns
            return True
        except queue.Full:
            self._record_drop()
            return False

    def _record_drop(self) -> None:
        self.metrics.frames_dropped += 1
        now = time.monotonic()
        self._drop_ts.append(now)
        window = self.config.drop_window_seconds
        while self._drop_ts and (now - self._drop_ts[0]) > window:
            self._drop_ts.popleft()
        if len(self._drop_ts) >= self.config.drop_pause_threshold and not self._paused.is_set():
            self._paused.set()
            self._paused_at = now
            self.metrics.paused = True
            self.metrics.pause_events += 1
            log.warning(
                "ClipRecorder auto-paused: %d drops in %.0fs window (live unaffected)",
                len(self._drop_ts), window,
            )

    def _maybe_resume(self) -> None:
        if not self._paused.is_set():
            return
        if (time.monotonic() - self._paused_at) >= self.config.drop_resume_seconds:
            self._paused.clear()
            self._drop_ts.clear()
            self.metrics.paused = False
            log.info("ClipRecorder resumed after auto-pause")

    # -------------------------------------------------------------------- thread
    def start(self) -> None:
        """Start the pump thread. Best-effort no-op if disabled or already up."""
        if not self.config.enabled or self._thread is not None:
            return
        self._stopped.clear()
        t = threading.Thread(target=self._run, name="clip-recorder", daemon=True)
        self._thread = t
        t.start()

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        """Flush and close the current segment, join the thread. Never raises."""
        self._stopped.set()
        try:
            self._queue.put_nowait(None)  # wake the pump
        except queue.Full:
            pass
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
        self._thread = None
        return self.metrics.to_dict()

    def _run(self) -> None:
        try:
            if not ffmpeg_available():
                log.warning("ffmpeg absent: clip recording disabled (session unaffected)")
                self.config.enabled = False
                return
            while not self._stopped.is_set():
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    # Idle: rotate a stale segment so a paused stream still closes.
                    if self._proc is not None and self._segment_expired():
                        self._close_segment()
                    self._maybe_resume()
                    continue
                if item is None:
                    break
                frame_bgr, _cap_ns = item
                self._encode_frame(frame_bgr)
                if self._segment_expired():
                    self._close_segment()
        except Exception as exc:  # pragma: no cover - top-level guard
            log.warning("ClipRecorder pump aborted (live unaffected): %s", exc)
        finally:
            self._close_segment()

    # ------------------------------------------------------------------ ffmpeg
    def _segment_expired(self) -> bool:
        if self._proc is None:
            return False
        return (time.monotonic() - self._seg_start_wall) >= self.config.segment_seconds

    def _open_segment(self, frame_bgr: Any) -> None:
        try:
            import numpy as np  # type: ignore

            arr = np.asarray(frame_bgr)
            src_h, src_w = int(arr.shape[0]), int(arr.shape[1])
        except Exception:
            self.metrics.ffmpeg_errors += 1
            return
        if src_h <= 0 or src_w <= 0:
            return
        # Downscale to configured height, keep aspect, force even dims (libx264).
        out_h = min(self.config.height, src_h)
        out_w = int(round(src_w * (out_h / src_h)))
        out_w -= out_w % 2
        out_h -= out_h % 2
        out_w = max(2, out_w)
        out_h = max(2, out_h)
        self._width, self._height = out_w, out_h

        captured_at = _iso_from_ns(None)
        day_dir = _clips_day_dir(captured_at)
        try:
            day_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.metrics.ffmpeg_errors += 1
            log.warning("clip dir create failed: %s", exc)
            return
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        seg_path = day_dir / f"{self.session_id}_{stamp}_{self.metrics.segments_written:04d}.mp4"

        vf = f"scale={src_w}:{src_h},fps={self.config.target_fps},scale={out_w}:{out_h}"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{src_w}x{src_h}",
            "-r", str(self.config.target_fps),
            "-i", "pipe:0",
            "-vf", vf,
            "-c:v", "libx264", "-preset", self.config.preset,
            "-pix_fmt", "yuv420p",
            "-b:v", f"{self.config.bitrate_kbps}k",
            "-maxrate", f"{self.config.bitrate_kbps}k",
            "-bufsize", f"{self.config.bitrate_kbps * 2}k",
            "-movflags", "+faststart",
            str(seg_path),
        ]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **_low_priority_kwargs(),
            )
        except Exception as exc:
            self.metrics.ffmpeg_errors += 1
            log.warning("ffmpeg spawn failed (recording best-effort off): %s", exc)
            return
        _demote_process(proc.pid)
        self._proc = proc
        self._seg_path = seg_path
        self._seg_started_at = captured_at
        self._seg_start_wall = time.monotonic()
        self._seg_frames = 0

    def _encode_frame(self, frame_bgr: Any) -> None:
        if self._proc is None:
            self._open_segment(frame_bgr)
            if self._proc is None:
                return
        try:
            import numpy as np  # type: ignore

            arr = np.ascontiguousarray(np.asarray(frame_bgr, dtype=np.uint8))
            stdin = self._proc.stdin
            if stdin is None:
                raise BrokenPipeError("ffmpeg stdin closed")
            stdin.write(arr.tobytes())
            self._seg_frames += 1
            self.metrics.frames_encoded += 1
        except (BrokenPipeError, OSError, ValueError) as exc:
            self.metrics.ffmpeg_errors += 1
            log.warning("ffmpeg write failed, rotating segment: %s", exc)
            self._abort_segment()

    def _close_segment(self) -> None:
        proc, seg_path = self._proc, self._seg_path
        started_at, frames = self._seg_started_at, self._seg_frames
        self._proc = None
        self._seg_path = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=30)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        if seg_path is None or frames <= 0:
            return
        try:
            if not seg_path.exists() or seg_path.stat().st_size == 0:
                self.metrics.ffmpeg_errors += 1
                return
        except OSError:
            return
        self.metrics.segments_written += 1
        duration_s = frames / max(1, self.config.target_fps)
        window_end = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        asset_id = _index_clip_asset(
            person_id=self.person_id, session_id=self.session_id,
            path=seg_path, captured_at=started_at or window_end, window_end=window_end,
            width=self._width, height=self._height, fps=self.config.target_fps,
            duration_s=duration_s, db_path=self.db_path,
        )
        if asset_id:
            self.metrics.segments_indexed += 1

    def _abort_segment(self) -> None:
        proc = self._proc
        self._proc = None
        self._seg_path = None
        self._seg_frames = 0
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------- close-day tier
def tier_clips_close_day(
    *,
    person_id: str,
    db_path: Any = None,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    """Close-day tiering: demote 'boring', UNREFERENCED, recent clips to
    keyframes-only (delete the MP4 + its asset row). Keyframes already extracted
    stay (timelapse). Runs from the SAME point as E54 retention, best-effort.

    'Interesting' (KEPT) = referenced by a proof (E54's notion), OR a
    ``visual_events_v19`` event fell inside the clip's window (active
    conversation / movement / change). Everything else that is young and boring
    is dropped; old boring clips are E54's budget concern, not ours (we leave
    them so E54 evicts oldest-first under budget). Never raises."""
    report: dict[str, Any] = {
        "status": "ok", "inspected": 0, "kept": 0, "dropped": 0,
        "dropped_bytes": 0, "warnings": [],
    }
    try:
        cfg = load_recorder_config(profile_path)
    except Exception:
        cfg = RecorderConfig()
    try:
        # Reuse E54's MediaRetention primitives: its inventory already flags each
        # clip referenced/unreferenced against the whole evidence chain. We do NOT
        # reinvent 'referenced' — we ask media_retention.
        import importlib.util

        mr_path = _HERE / "media_retention.py"
        spec = importlib.util.spec_from_file_location("v19_media_retention_e55", mr_path)
        if spec is None or spec.loader is None:
            report["status"] = "error"
            report["warnings"].append("media_retention module not found")
            return report
        mr = importlib.util.module_from_spec(spec)
        sys.modules["v19_media_retention_e55"] = mr
        spec.loader.exec_module(mr)
    except Exception as exc:
        report["status"] = "error"
        report["warnings"].append(f"media_retention import failed: {str(exc)[:120]}")
        return report

    try:
        from mlomega_audio_elite.utils import json_loads  # type: ignore
    except Exception:
        json_loads = None  # type: ignore

    try:
        retention = mr.MediaRetention(person_id=person_id, db_path=db_path)
        items = retention.inventory()  # each MediaItem already has .referenced
        clips = [it for it in items if getattr(it, "media_kind", None) == "clip"]
        report["inspected"] = len(clips)

        event_windows = _load_event_times(mr, retention, db_path)
        now = _now_utc()
        floor_days = max(0, int(cfg.keep_boring_days))

        for it in clips:
            referenced = bool(getattr(it, "referenced", False))
            captured = getattr(it, "captured_at", None)
            interesting = referenced or _has_event_in_window(
                mr, retention, it, event_windows, json_loads
            )
            if interesting:
                report["kept"] += 1
                continue
            # Only demote YOUNG boring clips; leave old ones to E54's budget.
            age_days = _age_days(mr, retention, it, now)
            if age_days > floor_days:
                report["kept"] += 1
                continue
            freed = retention._delete_item(it)  # deletes file + asset row coherently
            if freed or not Path(getattr(it, "path", "")).exists():
                report["dropped"] += 1
                report["dropped_bytes"] += int(getattr(it, "size_bytes", 0) or 0)
            else:
                report["kept"] += 1
    except Exception as exc:  # pragma: no cover - top-level guard
        report["status"] = "error"
        report["warnings"].append(f"tiering aborted: {str(exc)[:140]}")
    return report


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(mr: Any, retention: Any, item: Any, now: datetime) -> float:
    try:
        return retention._age_days(item, now)
    except Exception:
        return 0.0


def _load_event_times(mr: Any, retention: Any, db_path: Any) -> list[str]:
    """All visual_events_v19 occurrence timestamps (ISO). A clip whose window
    contains one is 'interesting'."""
    out: list[str] = []
    try:
        with retention._connect() as con:
            if not retention._table_exists(con, "visual_events_v19"):
                return out
            for (t,) in con.execute(
                "SELECT occurred_at FROM visual_events_v19 WHERE occurred_at IS NOT NULL"
            ):
                if t:
                    out.append(str(t))
    except Exception:
        pass
    return out


def _has_event_in_window(mr: Any, retention: Any, item: Any, events: list[str], json_loads: Any) -> bool:
    """True if any visual event occurred inside [captured_at, window_end]. The
    window is read from the clip's metadata (written by the recorder)."""
    if not events:
        return False
    start = getattr(item, "captured_at", None)
    end = None
    try:
        with retention._connect() as con:
            row = con.execute(
                "SELECT metadata_json FROM visual_evidence_assets_v19 WHERE uri=? LIMIT 1",
                (getattr(item, "path", None),),
            ).fetchone()
        if row and row[0] and json_loads is not None:
            meta = json_loads(row[0], {}) or {}
            if isinstance(meta, dict):
                start = meta.get("window_start") or start
                end = meta.get("window_end")
    except Exception:
        pass
    s = _parse_iso(start)
    e = _parse_iso(end) if end else None
    if s is None:
        return False
    for t in events:
        et = _parse_iso(t)
        if et is None:
            continue
        if et >= s and (e is None or et <= e):
            return True
    return False


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = str(text).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
