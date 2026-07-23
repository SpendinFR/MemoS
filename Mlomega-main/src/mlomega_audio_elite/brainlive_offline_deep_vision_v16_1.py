from __future__ import annotations

"""V16.1 offline heavy VLM pass for BrainLive event bundles.

BrainLive must stay fast during the day, so its live VLM descriptions are short.
For silent/non-verbal life episodes, that is often not enough: an office screen,
a cigarette/pause scene, a desk state, a place/affordance, or a body/activity
cue can matter even when nobody speaks.

This module runs only after V15.14 has assembled full event bundles. It selects a
small set of representative keyframes per event, re-runs a heavier/offline VLM
on those image files, stores detailed observations, optionally materializes them
as Brain2 context turns, and makes them available to V16.0 silent-life mining.

Important contract:
- no live-loop latency impact;
- no reconstruction of a conversation;
- no psychological certainty from images;
- VLM output is system visual evidence, not user speech;
- default max keyframes per bundle is 12, sampled across the event timeline.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import get_settings
from .db import connect, init_db, upsert
from .llm import EliteLLMError, json_schema_for_hint, ollama_generate, ollama_unload
from .runtime_v18_7 import classify_failure, gpu_phase, record_phase_event
from .utils import json_dumps, json_loads, now_iso, stable_id

VERSION = "16.1.1-v18.8.1-evidence-connected"


class DeepVisionCoveragePersistError(RuntimeError):
    """E64-I4.4: durable frame-coverage persistence failed.

    Coverage is the proof that 100% of the session's frames are accounted for
    (selected keyframe or represented-by).  If that proof cannot be durably
    written, the Deep Vision product output is NOT trustworthy: the in-memory
    mapping still exists for the current process, but a resume/audit/gate can no
    longer verify coverage from the database.  We therefore refuse to report a
    silent success.  This error is raised at selection time and converted, in
    the bundle loop, into a non-retryable ``blocked`` frame failure so the
    durable ``brainlive_deep_vision_runs_v161`` row lands ``status='blocked'`` and
    the I0.4 capability manifest (``_deep_vision_capability``) marks Deep Vision
    ``failed`` — which forbids ``complete=1``.
    """


class DeepVisionEvidenceMaterializationError(RuntimeError):
    """Selected semantic keyframes could not all be backed by readable pixels.

    ``selected_count`` is the coverage selector's durable truth. ``readable_count``
    is the number of those selected frames that already had pixels or were
    deterministically materialized from an E55 clip.  Runners persist both counts
    and block the capability instead of silently shrinking the selected set.
    """

    def __init__(
        self,
        message: str,
        *,
        selected_count: int,
        readable_count: int,
        missing_frame_ids: list[str],
    ) -> None:
        super().__init__(message)
        self.selected_count = int(selected_count)
        self.readable_count = int(readable_count)
        self.missing_frame_ids = tuple(missing_frame_ids)

# E64-I4.2: the offline heavy pass is a VISION-language model. When no explicit
# override is set, fall back to a real VLM, NOT ``settings.ollama_model`` (which
# is the TEXT model, ``qwen3.5:9b``). Sending images to a text model produced
# empty/garbage JSON silently. ``.env`` still overrides via the env vars below.
DEFAULT_OFFLINE_VLM_MODEL = "qwen3-vl:8b"


def _resolve_offline_vlm_model(model: str | None = None) -> str:
    """Deterministic offline-VLM model resolution used by every Deep Vision path.

    Priority: explicit ``model`` arg > ``MLOMEGA_OFFLINE_VLM_MODEL`` >
    ``MLOMEGA_VLM_HEAVY_MODEL`` > ``MLOMEGA_VLM_MODEL`` > the VLM default. The
    text ``settings.ollama_model`` is intentionally NOT a fallback here.
    """
    return (
        model
        or os.environ.get("MLOMEGA_OFFLINE_VLM_MODEL")
        or os.environ.get("MLOMEGA_VLM_HEAVY_MODEL")
        or os.environ.get("MLOMEGA_VLM_MODEL")
        or DEFAULT_OFFLINE_VLM_MODEL
    )


# E64-I4.2 prompt version: bump ANY time the system prompt, user prompt template,
# expected JSON shape, or decoding options change. It is part of the cache key so
# a prompt change forces a cache miss (a stale answer is never reused).
DEEP_VISION_PROMPT_VERSION = "dv-2026-07-16.1"

# E64-I4.2 additive VLM cache: keyed ONLY by sha256(image) + exact model +
# prompt version. A retry/rerun on an already-VALIDATED image never re-hits the
# network. Only strictly-valid JSON is ever cached.
DEEP_VISION_CACHE_TABLE = "deep_vision_vlm_cache_v19"

DEEP_VISION_CACHE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {DEEP_VISION_CACHE_TABLE}(
  cache_key TEXT PRIMARY KEY,
  image_sha256 TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  response_json TEXT NOT NULL,
  output_tokens INTEGER,
  latency_ms INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE(image_sha256, model, prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_deep_vision_vlm_cache_lookup
  ON {DEEP_VISION_CACHE_TABLE}(image_sha256, model, prompt_version);
"""

# Keys the offline VLM must return for its JSON to be accepted as valid. A subset
# of DEEP_VISION_SCHEMA_HINT: the fields normalisation and downstream evidence
# actually consume. Missing all of them => the model returned garbage/empty.
_DEEP_VISION_REQUIRED_KEYS = ("scene_summary_detailed", "observed_activity")


def _image_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _deep_vision_cache_key(image_sha256: str, model: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{image_sha256}|{model}|{prompt_version}".encode("utf-8")).hexdigest()


def _validate_deep_vision_json(data: Any) -> dict[str, Any]:
    """Strict-enough validation: an object carrying the required evidence fields.

    An empty ``{}`` (the classic Qwen "burned its budget thinking" result) or a
    non-object is rejected so it is NEVER cached or applied. Raises
    ``EliteLLMError`` on failure.
    """
    if not isinstance(data, dict):
        raise EliteLLMError("Réponse VLM offline JSON non-objet.")
    present = [k for k in _DEEP_VISION_REQUIRED_KEYS if str(data.get(k) or "").strip()]
    if not present:
        raise EliteLLMError(
            "Réponse VLM offline invalide: aucun champ requis "
            f"{list(_DEEP_VISION_REQUIRED_KEYS)} non vide."
        )
    return data


def ensure_deep_vision_cache_schema(con: Any) -> None:
    con.executescript(DEEP_VISION_CACHE_SCHEMA)


def _deep_vision_cache_get(image_sha256: str, model: str, prompt_version: str) -> dict[str, Any] | None:
    """Return the cached VALID response for this exact image+model+prompt, or None.

    A cache hit proves a 2nd run pays zero network cost. Any read error degrades
    gracefully to a miss (the caller then makes the real call).
    """
    try:
        with connect() as con:
            ensure_deep_vision_cache_schema(con)
            row = con.execute(
                f"SELECT response_json FROM {DEEP_VISION_CACHE_TABLE} WHERE image_sha256=? AND model=? AND prompt_version=?",
                (image_sha256, model, prompt_version),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        data = json.loads(row["response_json"] if not isinstance(row, tuple) else row[0])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _deep_vision_cache_put(
    *, image_sha256: str, model: str, prompt_version: str, data: dict[str, Any], output_tokens: int | None, latency_ms: int | None
) -> None:
    key = _deep_vision_cache_key(image_sha256, model, prompt_version)
    try:
        with connect() as con:
            ensure_deep_vision_cache_schema(con)
            con.execute(
                f"""INSERT OR IGNORE INTO {DEEP_VISION_CACHE_TABLE}(
                      cache_key, image_sha256, model, prompt_version, response_json,
                      output_tokens, latency_ms, created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                (key, image_sha256, model, prompt_version, json_dumps(data), output_tokens, latency_ms, now_iso()),
            )
            con.commit()
    except Exception:
        # Cache write must never break the analysis path.
        pass


def _parse_deep_vision_body(body_text: str) -> tuple[dict[str, Any], str]:
    """Parse JSON with lossless wrapper removal, never invented content."""
    text = str(body_text or "").strip()
    candidates: list[tuple[str, str]] = [("strict", text)]
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidates.append(("unwrap_json_fence", "\n".join(lines).strip()))
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(("extract_complete_object", text[first:last + 1]))
    last_error: Exception | None = None
    seen: set[str] = set()
    for strategy, candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return _validate_deep_vision_json(json.loads(candidate)), strategy
        except (TypeError, ValueError, EliteLLMError) as exc:
            last_error = exc
    raise EliteLLMError(f"Réponse VLM offline non-JSON: {last_error or 'empty output'}")


def _vlm_attempt_audit(
    outer: dict[str, Any], body_text: str, error: Exception | None
) -> dict[str, Any]:
    return {
        "done_reason": outer.get("done_reason") or outer.get("finish_reason"),
        "eval_count": outer.get("eval_count"),
        "raw_chars": len(body_text),
        "raw_sha256": hashlib.sha256(
            body_text.encode("utf-8", errors="replace")
        ).hexdigest(),
        "error": str(error)[:500] if error is not None else None,
    }

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS brainlive_deep_vision_runs_v161(
  run_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  model TEXT,
  max_keyframes_per_bundle INTEGER DEFAULT 12,
  scanned_bundles INTEGER DEFAULT 0,
  selected_keyframes INTEGER DEFAULT 0,
  readable_keyframes INTEGER DEFAULT 0,
  analyzed_keyframes INTEGER DEFAULT 0,
  appended_brain2_turns INTEGER DEFAULT 0,
  status TEXT NOT NULL,
  error_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brainlive_deep_vision_observations_v161(
  deep_observation_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  bundle_id TEXT NOT NULL,
  live_session_id TEXT,
  conversation_id TEXT,
  frame_id TEXT,
  image_path TEXT NOT NULL,
  frame_time TEXT,
  sample_index INTEGER DEFAULT 0,
  sample_reason TEXT,
  model TEXT,
  status TEXT NOT NULL,
  scene_summary_detailed TEXT,
  observed_activity TEXT,
  activity_confidence REAL DEFAULT 0.0,
  location_hint TEXT,
  spatial_layout TEXT,
  objects_json TEXT DEFAULT '[]',
  affordances_json TEXT DEFAULT '[]',
  visible_text_json TEXT DEFAULT '[]',
  people_presence_json TEXT DEFAULT '{}',
  screens_or_devices_json TEXT DEFAULT '[]',
  posture_motion_json TEXT DEFAULT '{}',
  work_or_rest_signal_json TEXT DEFAULT '{}',
  smoking_pause_signal_json TEXT DEFAULT '{}',
  exact_visual_evidence_json TEXT DEFAULT '[]',
  uncertainty_json TEXT DEFAULT '[]',
  qwen_json TEXT DEFAULT '{}',
  latency_ms INTEGER,
  error_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brainlive_deep_vision_brain2_exports_v161(
  export_id TEXT PRIMARY KEY,
  deep_observation_id TEXT NOT NULL,
  bundle_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  turn_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deep_vision_keyframe_materializations_v19(
  materialization_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  bundle_id TEXT,
  frame_id TEXT NOT NULL,
  live_session_id TEXT,
  frame_time TEXT NOT NULL,
  source_clip_id TEXT NOT NULL,
  source_clip_uri TEXT NOT NULL,
  source_clip_sha256 TEXT,
  clip_window_start TEXT NOT NULL,
  clip_window_end TEXT NOT NULL,
  requested_offset_s REAL NOT NULL,
  offset_s REAL NOT NULL,
  time_clamped INTEGER NOT NULL DEFAULT 0,
  image_asset_id TEXT NOT NULL,
  image_path TEXT NOT NULL,
  image_sha256 TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(person_id, frame_id)
);

CREATE INDEX IF NOT EXISTS idx_bldeep161_person_date ON brainlive_deep_vision_observations_v161(person_id, package_date, bundle_id, frame_time);
CREATE INDEX IF NOT EXISTS idx_bldeep161_bundle ON brainlive_deep_vision_observations_v161(bundle_id, status);
CREATE INDEX IF NOT EXISTS idx_bldeep161_conv ON brainlive_deep_vision_brain2_exports_v161(conversation_id, status);
CREATE INDEX IF NOT EXISTS idx_deepmat19_scope ON deep_vision_keyframe_materializations_v19(person_id,package_date,live_session_id,frame_id);
"""

DEEP_VISION_SCHEMA_HINT: dict[str, Any] = {
    "scene_summary_detailed": "detailed visible description, no mind-reading",
    "observed_activity": "computer_work|phone_use|smoking_pause|walking|resting|waiting|social_presence|travel|household|unknown",
    "activity_confidence": 0.0,
    "location_hint": "visible/probable place only",
    "spatial_layout": "short spatial layout",
    "objects": ["visible object names"],
    "affordances": [
        {"label": "shade|bench|quiet_corner|screen|desk|door|path|wall|seat|other", "position_hint": "left/right/front/...", "why_relevant_visually": "visible property only", "confidence": 0.0}
    ],
    "visible_text": ["text visible in image, if any"],
    "people_presence": {"people_count": 0, "known_identity_visible": False, "notes": "uncertain unless explicit"},
    "screens_or_devices": [{"type": "computer|phone|tablet|other", "visible_content_summary": "only visible text/layout", "confidence": 0.0}],
    "posture_motion": {"visible_posture": "", "movement_hint": "", "confidence": 0.0},
    "work_or_rest_signal": {"signal": "work|rest|ambiguous|none", "visual_evidence": [], "confidence": 0.0},
    "smoking_pause_signal": {"signal": "smoking_visible|pause_outside_possible|none|ambiguous", "visual_evidence": [], "confidence": 0.0},
    "exact_visual_evidence": ["short exact visual observations from the image"],
    "uncertainty": ["what cannot be concluded"],
    "confidence": 0.0,
}


def ensure_deep_vision_schema() -> None:
    init_db()
    with connect() as con:
        con.executescript(SCHEMA)
        _ensure_deep_vision_run_schema(con)
        con.commit()


def _ensure_deep_vision_run_schema(con: Any) -> None:
    """Migrate the run proof to the selected/readable/analyzed triple."""

    columns = {
        str(row[1])
        for row in con.execute("PRAGMA table_info(brainlive_deep_vision_runs_v161)").fetchall()
    }
    if "readable_keyframes" not in columns:
        con.execute(
            "ALTER TABLE brainlive_deep_vision_runs_v161 "
            "ADD COLUMN readable_keyframes INTEGER DEFAULT 0"
        )


def _table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _rows(con, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except Exception:
        return []


def _safe_json(v: Any, default: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    return json_loads(v if isinstance(v, str) else None, default)


def _clip(value: Any, n: int = 1600) -> str:
    s = str(value or "").strip()
    return s[:n] + ("…" if len(s) > n else "")


def _clamp(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        v = default
    return max(0.0, min(1.0, v))


def _image_exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).expanduser().exists()
    except Exception:
        return False


def _package_day(package_date: str | None) -> str:
    from .brainlive_event_assembler_v15_14 import _period_bounds
    return _period_bounds(package_date)[0]


def _transcript_chars(bundle: dict[str, Any]) -> int:
    turns = _safe_json(bundle.get("transcript_json"), []) or []
    return sum(len(str(t.get("text") or "")) for t in turns if isinstance(t, dict))


def _rehydrate_frame_paths(timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recover physical frame evidence from SQLite for legacy/compact bundles.

    This makes deep vision robust even if a prior assembler version compacted a
    raw timeline before carrying image_path into the bundle JSON.
    """
    ids = sorted({str(v.get("frame_id")) for v in timeline if isinstance(v, dict) and v.get("frame_id")})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with connect() as con:
        rows = _rows(con, f"SELECT frame_id,image_path,image_sha256,metadata_json,captured_at FROM vision_frames WHERE frame_id IN ({placeholders})", tuple(ids))
        # I4.4 materializations are derived evidence and MUST NOT rewrite the
        # immutable raw ``vision_frames`` occurrence. Rehydrate their managed
        # pixels through the additive mapping table on every resume instead.
        materialized = (
            _rows(
                con,
                f"""SELECT frame_id,image_path,image_sha256,frame_time AS captured_at,
                           source_clip_id,offset_s
                    FROM deep_vision_keyframe_materializations_v19
                    WHERE frame_id IN ({placeholders}) AND status='readable'""",
                tuple(ids),
            )
            if _table_exists(con, "deep_vision_keyframe_materializations_v19")
            else []
        )
    hydrated = {str(row["frame_id"]): row for row in rows}
    for row in materialized:
        # A readable derived keyframe overrides only the missing file projection;
        # the immutable raw row remains untouched in the database.
        if _image_exists(str(row.get("image_path") or "")):
            hydrated[str(row["frame_id"])] = row
    return hydrated


def _keyframe_candidates(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deduplicated raw-pixel candidates from an event bundle.

    Bundles persist their own image path in V18.8.1.  We still rehydrate from
    ``vision_frames`` as a backward-compatible integrity guard for V18.8 bundles
    assembled before the evidence-link fix.
    """
    timeline = [v for v in (_safe_json(bundle.get("vision_timeline_json"), []) or []) if isinstance(v, dict)]
    frame_rows = _rehydrate_frame_paths(timeline)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, v in enumerate(timeline):
        frame_id = str(v.get("frame_id") or "").strip() or None
        hydrated = frame_rows.get(frame_id or "", {})
        image_path = str(v.get("image_path") or hydrated.get("image_path") or "").strip()
        dedupe = image_path or frame_id or json_dumps(v)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append({
            "bundle_id": bundle.get("bundle_id"),
            "live_session_id": bundle.get("live_session_id"),
            "conversation_id": bundle.get("brain2_conversation_id"),
            "frame_id": frame_id,
            "image_path": image_path,
            "frame_time": v.get("time") or hydrated.get("captured_at"),
            "live_summary": v.get("summary"),
            "location_hint": v.get("location_hint"),
            "objects": v.get("objects"),
            "affordances": v.get("affordances"),
            "possible_user_activities": v.get("possible_user_activities"),
            "index": idx,
            "exists": _image_exists(image_path),
        })
    return out


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip_window(row: dict[str, Any]) -> tuple[datetime, datetime, dict[str, Any]] | None:
    meta = json_loads(row.get("metadata_json"), {}) or {}
    if not isinstance(meta, dict):
        meta = {}
    start = _parse_utc(meta.get("window_start") or row.get("captured_at"))
    end = _parse_utc(meta.get("window_end"))
    if start is None:
        return None
    if end is None:
        try:
            duration = max(0.0, float(meta.get("duration_s") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        end = datetime.fromtimestamp(start.timestamp() + duration, tz=timezone.utc)
    if end < start:
        return None
    return start, end, meta


def _find_e55_clip_for_frame(
    *, person_id: str, live_session_id: str | None, frame_time: Any
) -> dict[str, Any] | None:
    """Find the indexed E55 clip that durably covers ``frame_time``.

    A small tolerance absorbs recorder queue/wall-clock skew, but extraction is
    always clamped to the clip's proven window and the clamp is preserved in the
    materialization provenance.
    """

    target = _parse_utc(frame_time)
    if target is None:
        return None
    try:
        tolerance = max(
            0.0,
            float(os.environ.get("MLOMEGA_DEEP_VISION_CLIP_TIME_TOLERANCE_S", "3.0")),
        )
    except (TypeError, ValueError):
        tolerance = 3.0
    try:
        with connect() as con:
            if not _table_exists(con, "visual_evidence_assets_v19"):
                return None
            sql = (
                "SELECT visual_asset_id,live_session_id,uri,sha256,captured_at,metadata_json "
                "FROM visual_evidence_assets_v19 WHERE person_id=? "
                "AND asset_kind IN ('clip','video')"
            )
            params: list[Any] = [person_id]
            if live_session_id:
                sql += " AND live_session_id=?"
                params.append(str(live_session_id))
            rows = [dict(row) for row in con.execute(sql, tuple(params)).fetchall()]
    except Exception:
        return None
    matches: list[tuple[float, float, dict[str, Any]]] = []
    for row in rows:
        path = Path(str(row.get("uri") or "")).expanduser()
        if not _image_exists(str(path)):
            continue
        window = _clip_window(row)
        if window is None:
            continue
        start, end, meta = window
        before = max(0.0, (start - target).total_seconds())
        after = max(0.0, (target - end).total_seconds())
        distance = before + after
        if distance > tolerance:
            continue
        wall_offset = (target - start).total_seconds()
        wall_duration = max(0.0, (end - start).total_seconds())
        # E55 rotates clips on wall-clock time, while the encoded MP4 duration is
        # ``frames_encoded / target_fps``.  Under load those clocks legitimately
        # diverge (for example a 120 s recorder window may contain 80 s of video).
        # Seeking the MP4 with the wall offset then asks FFmpeg for a frame beyond
        # EOF.  Map the capture occurrence proportionally onto the durable media
        # timeline; do not drop the late keyframe or pretend it had no pixels.
        try:
            media_duration = max(0.0, float(meta.get("duration_s") or 0.0))
        except (TypeError, ValueError):
            media_duration = 0.0
        if media_duration <= 0.0:
            media_duration = wall_duration
        scale = media_duration / wall_duration if wall_duration > 0.0 else 1.0
        requested_media_offset = wall_offset * scale
        try:
            fps = max(1.0, float(meta.get("fps") or 30.0))
        except (TypeError, ValueError):
            fps = 30.0
        max_offset = max(0.0, media_duration - (1.0 / fps))
        offset = min(max(requested_media_offset, 0.0), max_offset)
        enriched = {
            **row,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "offset_s": offset,
            "requested_offset_s": requested_media_offset,
            "wall_requested_offset_s": wall_offset,
            "wall_duration_s": wall_duration,
            "media_duration_s": media_duration,
            "wall_to_media_scale": scale,
            "time_rescaled": abs(scale - 1.0) > 1e-6,
            "time_clamped": abs(offset - requested_media_offset) > 1e-6,
            "metadata": meta,
        }
        # Exact containment wins; then choose the closest window and earliest
        # offset so overlapping segment boundaries are deterministic.
        matches.append((distance, offset, enriched))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1], str(item[2].get("visual_asset_id"))))
    return matches[0][2]


def _materialized_keyframe_path(
    *, person_id: str, live_session_id: str | None, frame_id: str, frame_time: Any, clip_id: str
) -> Path:
    root = Path(
        os.environ.get("MLOMEGA_MEDIA")
        or (Path(__file__).resolve().parents[2] / "storage" / "media")
    ).expanduser()
    captured = _parse_utc(frame_time)
    day = (captured or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    digest = hashlib.sha256(
        "|".join((person_id, str(live_session_id or ""), frame_id, str(frame_time or ""), clip_id)).encode("utf-8")
    ).hexdigest()[:20]
    return root / "keyframes" / day / "deep_materialized" / f"deep_{digest}.jpg"


def _persist_materialized_keyframe(
    *,
    candidate: dict[str, Any],
    person_id: str,
    package_date: str,
    live_session_id: str | None,
    output_path: Path,
    clip: dict[str, Any],
) -> None:
    frame_id = str(candidate.get("frame_id") or "").strip()
    if not frame_id:
        raise RuntimeError("selected frame has no durable frame_id")
    data = output_path.read_bytes()
    if not data:
        raise RuntimeError("materialized keyframe is empty")
    image_sha = hashlib.sha256(data).hexdigest()
    asset_id = stable_id("rawasset", str(output_path.resolve()), image_sha)
    materialization = {
        "producer": "E64.I4.4.e55_keyframe_materializer",
        "source_clip_id": clip.get("visual_asset_id"),
        "source_clip_uri": str(clip.get("uri") or ""),
        "source_clip_sha256": clip.get("sha256"),
        "clip_window_start": clip.get("window_start"),
        "clip_window_end": clip.get("window_end"),
        "requested_frame_time": candidate.get("frame_time"),
        "offset_s": round(float(clip.get("offset_s") or 0.0), 6),
        "requested_offset_s": round(float(clip.get("requested_offset_s") or 0.0), 6),
        "wall_requested_offset_s": round(float(clip.get("wall_requested_offset_s") or 0.0), 6),
        "wall_duration_s": round(float(clip.get("wall_duration_s") or 0.0), 6),
        "media_duration_s": round(float(clip.get("media_duration_s") or 0.0), 6),
        "wall_to_media_scale": float(clip.get("wall_to_media_scale") or 1.0),
        "time_rescaled": bool(clip.get("time_rescaled")),
        "time_clamped": bool(clip.get("time_clamped")),
    }
    from .night_orchestrator.deep_vision_selection import _image_dimensions

    dims = _image_dimensions(str(output_path))
    now = now_iso()
    with connect() as con:
        upsert(
            con,
            "raw_assets",
            {
                "asset_id": asset_id,
                "type": "image",
                "path": str(output_path.resolve()),
                "sha256": image_sha,
                "captured_at": candidate.get("frame_time"),
                "source": "deep_vision_e55_materialization",
                "metadata_json": json_dumps(materialization),
                "created_at": now,
            },
            "asset_id",
        )
        # ``vision_frames`` is an immutable capture occurrence. The E55-derived
        # JPEG is not byte-identical to that vanished raw frame, so keep it in an
        # additive mapping rather than rewriting the historical row.
        upsert(
            con,
            "deep_vision_keyframe_materializations_v19",
            {
                "materialization_id": stable_id("deepmat19", person_id, frame_id),
                "person_id": person_id,
                "package_date": package_date,
                "bundle_id": candidate.get("bundle_id"),
                "frame_id": frame_id,
                "live_session_id": live_session_id,
                "frame_time": candidate.get("frame_time"),
                "source_clip_id": str(clip.get("visual_asset_id") or ""),
                "source_clip_uri": str(clip.get("uri") or ""),
                "source_clip_sha256": clip.get("sha256"),
                "clip_window_start": clip.get("window_start"),
                "clip_window_end": clip.get("window_end"),
                "requested_offset_s": float(clip.get("requested_offset_s") or 0.0),
                "offset_s": float(clip.get("offset_s") or 0.0),
                "time_clamped": 1 if clip.get("time_clamped") else 0,
                "image_asset_id": asset_id,
                "image_path": str(output_path.resolve()),
                "image_sha256": image_sha,
                "width": dims[0] if dims else None,
                "height": dims[1] if dims else None,
                "status": "readable",
                "created_at": now,
                "updated_at": now,
            },
            "materialization_id",
        )
        con.commit()
    candidate.update(
        {
            "image_path": str(output_path.resolve()),
            "exists": True,
            "materialized_from_clip_id": clip.get("visual_asset_id"),
            "materialization_offset_s": clip.get("offset_s"),
        }
    )


def _materialize_selected_from_e55(
    *, bundle: dict[str, Any], result: Any, all_candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return every selected keyframe with readable pixels, or fail closed.

    The night selector operates on the full semantic timeline, while the live
    VisionRT keyframe sink stores only its own sparse subset. Missing selected
    pixels are reconstructed from the E55 clip covering the frame timestamp and
    registered as normal ``vision_frames`` evidence. No selected id is silently
    removed from the run count.
    """

    selected_ids = list(result.selected_frame_ids)
    by_frame_id = {
        str(candidate.get("frame_id") or candidate.get("image_path") or "").strip(): candidate
        for candidate in all_candidates
        if str(candidate.get("frame_id") or candidate.get("image_path") or "").strip()
    }
    person_id = str(bundle.get("person_id") or "me")
    package_date = str(bundle.get("package_date") or "")
    live_session_id = str(bundle.get("live_session_id") or "").strip() or None
    ffmpeg = shutil.which("ffmpeg")
    readable: list[dict[str, Any]] = []
    failures: list[str] = []
    for frame_id in selected_ids:
        candidate = by_frame_id.get(frame_id)
        if candidate is None:
            failures.append(frame_id)
            continue
        path = str(candidate.get("image_path") or "")
        if _image_exists(path):
            candidate["exists"] = True
            readable.append(candidate)
            continue
        clip = _find_e55_clip_for_frame(
            person_id=person_id,
            live_session_id=live_session_id,
            frame_time=candidate.get("frame_time"),
        )
        if clip is None or ffmpeg is None:
            failures.append(frame_id)
            continue
        output_path = _materialized_keyframe_path(
            person_id=person_id,
            live_session_id=live_session_id,
            frame_id=frame_id,
            frame_time=candidate.get("frame_time"),
            clip_id=str(clip.get("visual_asset_id") or "clip"),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not _image_exists(str(output_path)):
            tmp_path = output_path.with_name(output_path.stem + ".tmp.jpg")
            try:
                timeout_s = max(
                    1.0,
                    float(os.environ.get("MLOMEGA_DEEP_VISION_FFMPEG_TIMEOUT_S", "60")),
                )
            except (TypeError, ValueError):
                timeout_s = 60.0
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(clip.get("uri")),
                "-ss",
                f"{float(clip.get('offset_s') or 0.0):.6f}",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(tmp_path),
            ]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
                if proc.returncode != 0 or not _image_exists(str(tmp_path)):
                    raise RuntimeError((proc.stderr or "ffmpeg produced no image")[-1000:])
                tmp_path.replace(output_path)
            except Exception as exc:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                record_phase_event(
                    "deep_vision_keyframe_materialization_failed",
                    bundle_id=bundle.get("bundle_id"),
                    frame_id=frame_id,
                    source_clip_id=clip.get("visual_asset_id"),
                    error=str(exc)[:400],
                )
                failures.append(frame_id)
                continue
        try:
            _persist_materialized_keyframe(
                candidate=candidate,
                person_id=person_id,
                package_date=package_date,
                live_session_id=live_session_id,
                output_path=output_path,
                clip=clip,
            )
        except Exception as exc:
            record_phase_event(
                "deep_vision_keyframe_registration_failed",
                bundle_id=bundle.get("bundle_id"),
                frame_id=frame_id,
                source_clip_id=clip.get("visual_asset_id"),
                error=str(exc)[:400],
            )
            failures.append(frame_id)
            continue
        readable.append(candidate)
        record_phase_event(
            "deep_vision_keyframe_materialized",
            bundle_id=bundle.get("bundle_id"),
            frame_id=frame_id,
            source_clip_id=clip.get("visual_asset_id"),
            offset_s=clip.get("offset_s"),
        )
    if failures or len(readable) != len(selected_ids):
        missing = list(dict.fromkeys([*failures, *[fid for fid in selected_ids if fid not in {str(r.get('frame_id') or r.get('image_path') or '') for r in readable}]]))
        raise DeepVisionEvidenceMaterializationError(
            "deep vision selected keyframes lack readable pixels after E55 materialization: "
            + ",".join(missing[:20]),
            selected_count=len(selected_ids),
            readable_count=len(readable),
            missing_frame_ids=missing,
        )
    return readable

def _collect_requested_frame_ids(bundle: dict[str, Any]) -> set[str]:
    """Frame ids named by a real live vision focus request (what_is/ocr/zoom/find).

    We only read structures that already exist. A focus request that names a
    ``frame_id`` shows up in ``brainlive_sensor_events`` (modality vision) or in
    the assembled ``brainlive_raw_timeline_v1514`` with a vision-request evidence
    role.  When neither table nor row exists (the common case) we return an empty
    set - no table is invented and no request is fabricated.
    """
    live_session_id = str(bundle.get("live_session_id") or "").strip()
    package_date = str(bundle.get("package_date") or "").strip()
    ids: set[str] = set()
    try:
        with connect() as con:
            if _table_exists(con, "brainlive_sensor_events"):
                params: list[Any] = []
                where = ["modality='vision'", "frame_id IS NOT NULL", "frame_id<>''"]
                # sensor events may not carry frame_id in every schema; guard it.
                cols = {r[1] for r in con.execute("PRAGMA table_info(brainlive_sensor_events)").fetchall()}
                if "frame_id" in cols:
                    if live_session_id and "live_session_id" in cols:
                        where.append("live_session_id=?")
                        params.append(live_session_id)
                    ids.update(
                        str(r["frame_id"])
                        for r in _rows(con, "SELECT frame_id FROM brainlive_sensor_events WHERE " + " AND ".join(where), tuple(params))
                        if r.get("frame_id")
                    )
            if _table_exists(con, "brainlive_raw_timeline_v1514"):
                where = ["frame_id IS NOT NULL", "frame_id<>''", "evidence_role LIKE '%request%'"]
                params = []
                if package_date:
                    where.append("package_date=?")
                    params.append(package_date)
                if live_session_id:
                    where.append("live_session_id=?")
                    params.append(live_session_id)
                ids.update(
                    str(r["frame_id"])
                    for r in _rows(con, "SELECT frame_id FROM brainlive_raw_timeline_v1514 WHERE " + " AND ".join(where), tuple(params))
                    if r.get("frame_id")
                )
    except Exception:
        return ids
    return ids


def _apply_optional_ceiling(result: Any) -> Any:
    """Apply MLOMEGA_DEEP_VISION_MAX_KEYFRAMES if set (OFF by default).

    The change policy, not a quota, decides the keyframe count.  This ceiling is
    only for a genuine change storm; when it fires it demotes overflow keyframes
    to represented-by (coverage stays 100%), never a silent drop.
    """
    raw = os.environ.get("MLOMEGA_DEEP_VISION_MAX_KEYFRAMES")
    if raw is None or not str(raw).strip():
        return result
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return result
    if cap <= 0:
        return result
    from .night_orchestrator.deep_vision_selection import apply_max_keyframes_ceiling
    return apply_max_keyframes_ceiling(result, cap)


def select_keyframes_for_bundle(bundle: dict[str, Any], *, max_keyframes: int = 12, silent_bias: bool = True) -> list[dict[str, Any]]:
    """Select coverage-complete representative keyframes across the event.

    A frame becomes a keyframe when it carries genuinely new information: a real
    scene/object/person change (a new ``VisionChangeAtom``), OCR (visible text),
    an explicit live user request, or a configurable safety interval.  This is a
    policy, not a quota: a change-rich event yields more keyframes than a static
    one, and no frame is dropped silently.  Every non-selected frame is mapped to
    the keyframe/atom that represents it and persisted in
    ``deep_vision_frame_coverage_v19`` so 100% of the session's frames are proven
    accounted for. A selected frame whose sparse live keyframe file is absent is
    materialized from its indexed E55 clip at the captured timestamp. If that
    cannot be done, selection fails closed; it is never silently removed from the
    run count.

    ``max_keyframes`` is retained only for backward-compatible call signatures;
    it is NOT used as a quota.  The change policy alone decides how many
    keyframes are warranted, so a change-rich 5-minute event keeps all its
    distinct keyframes instead of being silently truncated to 12.  A pathological
    hard ceiling can be re-enabled with ``MLOMEGA_DEEP_VISION_MAX_KEYFRAMES`` for
    a genuine change storm; when it fires, overflow keyframes are demoted to
    represented-by their previous kept keyframe (still covered), never dropped by
    a silent ``rows[:N]``.
    """
    from .night_orchestrator.deep_vision_selection import (
        load_frame_dimensions,
        load_visionrt_frame_positions,
        normalize_frame_positions,
        persist_frame_coverage,
        select_keyframes_with_coverage,
    )

    all_candidates = _keyframe_candidates(bundle)
    if not all_candidates:
        return []

    requested = _collect_requested_frame_ids(bundle)
    # E64-I4.3: reuse the VisionRT live positions (bbox recorded in
    # visual_events_v19) so a major displacement at constant labels opens a
    # keyframe. VisionRT bboxes are PIXEL [x1,y1,x2,y2]; they are normalised by
    # the frame's REAL dimensions (vision_frames width/height, its metadata, or
    # the stored keyframe file's own header - the same buffer the detector saw).
    # A frame whose dimensions cannot be resolved is SKIPPED with an explicit
    # phase event, never clamped silently; the label-set-only signal remains.
    frame_positions: dict[str, Any] = {}
    frame_ids = [str(c.get("frame_id") or "").strip() for c in all_candidates if c.get("frame_id")]
    try:
        with connect() as con:
            raw_positions = load_visionrt_frame_positions(
                con,
                person_id=str(bundle.get("person_id") or "me"),
                live_session_id=bundle.get("live_session_id"),
                frame_ids=frame_ids,
            )
            if raw_positions:
                paths_by_frame = {
                    str(c.get("frame_id") or "").strip(): str(c.get("image_path") or "")
                    for c in all_candidates
                    if c.get("frame_id") and c.get("image_path")
                }
                dims = load_frame_dimensions(
                    con, frame_ids=list(raw_positions.keys()), image_paths_by_frame=paths_by_frame
                )
                frame_positions, skipped = normalize_frame_positions(raw_positions, dims)
                for fid in skipped:
                    record_phase_event(
                        "deep_vision_position_dims_unavailable",
                        bundle_id=bundle.get("bundle_id"),
                        frame_id=fid,
                    )
    except Exception:
        frame_positions = {}
    result = select_keyframes_with_coverage(
        bundle, all_candidates, requested_frame_ids=requested, frame_positions=frame_positions
    )

    # Optional pathological ceiling (OFF by default). When set, demote overflow
    # keyframes to represented-by so coverage stays complete; never a silent drop.
    result = _apply_optional_ceiling(result)

    # Durably persist the coverage of EVERY frame (selected | represented). This
    # is additive provenance; raw frames/observations are never touched.
    person_id = str(bundle.get("person_id") or "me")
    package_date = str(bundle.get("package_date") or "")
    # E64-I4.4: coverage persistence is the DURABLE proof that 100% of the
    # session's frames are accounted for. A silent ``except: pass`` here let a
    # run report a green Deep Vision while the coverage proof was never written
    # (a resume/audit/gate could no longer verify it from the DB). We now raise a
    # STRUCTURED error; the caller (bundle loop) turns it into a non-retryable
    # ``blocked`` frame failure so the run row is ``status='blocked'`` and the
    # I0.4 gate marks Deep Vision ``failed`` (no ``complete=1``).
    try:
        with connect() as con:
            persist_frame_coverage(con, person_id=person_id, package_date=package_date, result=result)
            con.commit()
    except Exception as exc:
        record_phase_event(
            "deep_vision_coverage_persist_failed",
            bundle_id=bundle.get("bundle_id"),
            person_id=person_id,
            package_date=package_date,
            error=str(exc)[:400],
        )
        raise DeepVisionCoveragePersistError(
            f"deep vision frame coverage not persisted for {person_id}/{package_date}: {exc}"
        ) from exc

    selected = _materialize_selected_from_e55(
        bundle=bundle,
        result=result,
        all_candidates=all_candidates,
    )

    for i, item in enumerate(selected):
        item["sample_index"] = i
        fid = str(item.get("frame_id") or item.get("image_path") or "").strip()
        reasons = result.reasons_by_frame.get(fid) or ()
        item["sample_reason"] = "+".join(reasons) if reasons else "coverage_keyframe"
    return selected


def _deep_vlm_json(image_path: str, *, model: str | None, timeout: float, personal_context: dict[str, Any] | None = None, num_predict: int = 900, use_cache: bool = True) -> dict[str, Any]:
    settings = get_settings()
    cloud_vlm = os.environ.get("MLOMEGA_CLOUD_VLM_PROVIDER", "local").strip().lower()
    if cloud_vlm != "gemini" and not settings.enable_ollama:
        raise EliteLLMError("MLOMEGA_ENABLE_OLLAMA=false: VLM offline requis pour analyse visuelle profonde.")
    p = Path(image_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(p)
    chosen_model = (
        os.environ.get("MLOMEGA_GEMINI_VLM_MODEL", "gemini-3.1-flash-lite")
        if cloud_vlm == "gemini" else _resolve_offline_vlm_model(model)
    )
    image_sha = _image_sha256(p)
    if use_cache:
        cached = _deep_vision_cache_get(image_sha, chosen_model, DEEP_VISION_PROMPT_VERSION)
        if cached is not None:
            out = dict(cached)
            out["_model"] = chosen_model
            out["_cache_hit"] = True
            out["_vlm_attempt_count"] = 0
            out["_vlm_recovery_strategy"] = "validated_cache"
            return out
    image_b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    system = (
        "Tu es le VLM offline lourd de Brain2/BrainLive. Tu analyses une keyframe d'un événement de vie. "
        "Décris précisément ce qui est visible: activité possible, lieu, objets, écran/appareil, posture/mouvement visible, affordances. "
        "Interdiction de deviner l'état psychologique ou l'intention interne. Si tu proposes travail/repos/pause/cigarette, cite uniquement les indices visuels. "
        "Cette sortie peut devenir preuve mémoire; sois prudent, détaillé, et marque l'incertitude. JSON strict uniquement."
    )
    prompt = json_dumps({
        "mission": "Analyse offline détaillée d'une image BrainLive pour épisodes sans parole et routines de vie.",
        "personal_context_light": personal_context or {},
        "must_separate": ["visible action", "possible activity", "hypothetical need/mood must NOT be inferred here"],
        "examples_of_use": ["ordinateur/travail", "pause dehors/cigarette", "détente", "lieu récurrent", "ombre/banc/coin calme"],
        "rules": [
            "ne pas reconstruire de conversation",
            "ne pas conclure l'humeur depuis l'image seule",
            "visible object/affordance only",
            "cite exact_visual_evidence",
            "si doute: observed_activity=unknown ou confidence basse",
        ],
    })
    base_prompt = (
        f"SYSTEM:\n{system}\n\nUSER:\n{prompt}\n\nReturn strict JSON only."
        f"\n\nExpected shape:\n{json.dumps(DEEP_VISION_SCHEMA_HINT, ensure_ascii=False)}"
    )
    if cloud_vlm == "gemini":
        from .cloud_budget_v19 import CloudBudgetExceeded, cloud_budget_policy
        from .cloud_providers_v19 import gemini_vision_json

        attempts: list[dict[str, Any]] = []
        total_latency_ms = 0
        total_output_tokens = 0
        parsed_data: dict[str, Any] | None = None
        parse_strategy = "strict"
        for attempt_index in (1, 2):
            compact_retry = attempt_index == 2
            recovery = ""
            if compact_retry:
                recovery = (
                    "\n\nRECOVERY: la sortie précédente était invalide. Retourne le même "
                    "schéma compact, sans commentaire hors JSON; listes <=6 éléments."
                )
            try:
                raw_data, meta = gemini_vision_json(
                    p,
                    system=system,
                    prompt=prompt + recovery,
                    schema=json_schema_for_hint(DEEP_VISION_SCHEMA_HINT),
                    max_output_tokens=max(1200, int(num_predict or 900)) if compact_retry else int(num_predict or 900),
                    timeout=max(float(timeout), settings.poststop_vlm_timeout_s),
                )
                parsed_data, parse_strategy = _parse_deep_vision_body(
                    json.dumps(raw_data, ensure_ascii=False)
                )
                total_latency_ms += int(meta.get("latency_ms") or 0)
                total_output_tokens += int(meta.get("output_tokens") or 0)
                attempts.append({
                    "attempt": attempt_index,
                    "strategy": "compact_retry" if compact_retry else "primary",
                    "parse_strategy": parse_strategy,
                    "provider": "gemini",
                })
                break
            except CloudBudgetExceeded:
                if cloud_budget_policy() != "local":
                    raise
                # The CloseDay worker is isolated and sequential. Temporarily
                # select the already-proven local VLM, then restore PRO for the
                # next image/stage. No prompt or writer changes.
                prior = os.environ.get("MLOMEGA_CLOUD_VLM_PROVIDER")
                os.environ["MLOMEGA_CLOUD_VLM_PROVIDER"] = "local"
                try:
                    return _deep_vlm_json(
                        image_path, model=model, timeout=timeout,
                        personal_context=personal_context, num_predict=num_predict,
                        use_cache=use_cache,
                    )
                finally:
                    if prior is None:
                        os.environ.pop("MLOMEGA_CLOUD_VLM_PROVIDER", None)
                    else:
                        os.environ["MLOMEGA_CLOUD_VLM_PROVIDER"] = prior
            except Exception as exc:
                attempts.append({
                    "attempt": attempt_index,
                    "strategy": "compact_retry" if compact_retry else "primary",
                    "provider": "gemini",
                    "error": str(exc)[:500],
                })
                if attempt_index == 2:
                    raise
        if parsed_data is None:
            raise EliteLLMError("Réponse Gemini VLM absente après tentative bornée")
        output_tokens = total_output_tokens or None
        parsed_data["_model"] = chosen_model
        parsed_data["_cache_hit"] = False
        parsed_data["_output_tokens"] = output_tokens
        parsed_data["_latency_ms"] = total_latency_ms
        parsed_data["_vlm_attempt_count"] = len(attempts)
        parsed_data["_vlm_recovery_strategy"] = "compact_retry" if len(attempts) > 1 else parse_strategy
        parsed_data["_vlm_attempt_audit"] = attempts
        if use_cache:
            _deep_vision_cache_put(
                image_sha256=image_sha, model=chosen_model, prompt_version=DEEP_VISION_PROMPT_VERSION,
                data={k: v for k, v in parsed_data.items() if not k.startswith("_")},
                output_tokens=output_tokens, latency_ms=total_latency_ms,
            )
        return parsed_data
    attempts: list[dict[str, Any]] = []
    total_latency_ms = 0
    total_output_tokens = 0
    data: dict[str, Any] | None = None
    parse_strategy = "strict"
    for attempt_index in (1, 2):
        compact_retry = attempt_index == 2
        recovery = ""
        if compact_retry:
            recovery = (
                "\n\nRECOVERY: la sortie précédente était tronquée ou invalide. "
                "Retourne le MEME schéma, mais compact: chaque texte <=240 caractères; "
                "objects/affordances/visible_text/exact_visual_evidence/uncertainty <=6 éléments; "
                "utilise [] ou {} pour les champs sans preuve. Aucun commentaire hors JSON."
            )
        payload = {
            "model": chosen_model,
            "prompt": base_prompt + recovery,
            "images": [image_b64],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": max(1200, int(num_predict or 900)) if compact_retry else int(num_predict or 900),
            },
        }
        started = time.time()
        outer = ollama_generate(
            payload,
            timeout=max(float(timeout), settings.poststop_vlm_timeout_s),
            component="post_stop_deep_vision",
            poststop_min_timeout_s=settings.poststop_vlm_timeout_s,
        )
        latency_ms = int((time.time() - started) * 1000)
        total_latency_ms += latency_ms
        body_text = str(outer.get("response") or "").strip()
        if not body_text:
            body_text = str(outer.get("thinking") or "").strip()
        try:
            total_output_tokens += int(outer.get("eval_count") or 0)
        except (TypeError, ValueError):
            pass
        try:
            data, parse_strategy = _parse_deep_vision_body(body_text)
        except EliteLLMError as exc:
            audit = _vlm_attempt_audit(outer, body_text, exc)
            audit.update({"attempt": attempt_index, "strategy": "compact_retry" if compact_retry else "primary"})
            attempts.append(audit)
            record_phase_event("deep_vision_vlm_output_invalid", **audit)
            if attempt_index == 1:
                continue
            raise EliteLLMError(
                "Réponse VLM offline non-JSON après retry compact; "
                f"attempts={json_dumps(attempts)}"
            ) from exc
        audit = _vlm_attempt_audit(outer, body_text, None)
        audit.update({
            "attempt": attempt_index,
            "strategy": "compact_retry" if compact_retry else "primary",
            "parse_strategy": parse_strategy,
        })
        attempts.append(audit)
        if compact_retry:
            record_phase_event("deep_vision_vlm_compact_retry_recovered", **audit)
        break
    if data is None:
        raise EliteLLMError("Réponse VLM offline absente après tentative bornée")
    output_tokens = total_output_tokens or None
    data["_model"] = chosen_model
    data["_cache_hit"] = False
    data["_output_tokens"] = output_tokens
    data["_latency_ms"] = total_latency_ms
    data["_vlm_attempt_count"] = len(attempts)
    data["_vlm_recovery_strategy"] = "compact_retry" if len(attempts) > 1 else parse_strategy
    data["_vlm_attempt_audit"] = attempts
    if use_cache:
        _deep_vision_cache_put(
            image_sha256=image_sha, model=chosen_model, prompt_version=DEEP_VISION_PROMPT_VERSION,
            data={k: v for k, v in data.items() if not k.startswith("_")},
            output_tokens=output_tokens, latency_ms=total_latency_ms,
        )
    return data


def _normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    affs = raw.get("affordances") or []
    if isinstance(affs, dict):
        affs = [affs]
    objs = raw.get("objects") or []
    if isinstance(objs, str):
        objs = [objs]
    visible = raw.get("visible_text") or []
    if isinstance(visible, str):
        visible = [visible]
    evidence = raw.get("exact_visual_evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    uncertainty = raw.get("uncertainty") or []
    if isinstance(uncertainty, str):
        uncertainty = [uncertainty]
    return {
        "scene_summary_detailed": _clip(raw.get("scene_summary_detailed") or raw.get("scene_summary") or raw.get("summary"), 2500),
        "observed_activity": _clip(raw.get("observed_activity") or raw.get("activity") or "unknown", 160),
        "activity_confidence": _clamp(raw.get("activity_confidence") if raw.get("activity_confidence") is not None else raw.get("confidence"), 0.0),
        "location_hint": _clip(raw.get("location_hint"), 300) if raw.get("location_hint") else None,
        "spatial_layout": _clip(raw.get("spatial_layout") or raw.get("spatial_context"), 1200) if (raw.get("spatial_layout") or raw.get("spatial_context")) else None,
        "objects": objs if isinstance(objs, list) else [],
        "affordances": affs if isinstance(affs, list) else [],
        "visible_text": visible if isinstance(visible, list) else [],
        "people_presence": raw.get("people_presence") if isinstance(raw.get("people_presence"), dict) else {},
        "screens_or_devices": raw.get("screens_or_devices") if isinstance(raw.get("screens_or_devices"), list) else [],
        "posture_motion": raw.get("posture_motion") if isinstance(raw.get("posture_motion"), dict) else {},
        "work_or_rest_signal": raw.get("work_or_rest_signal") if isinstance(raw.get("work_or_rest_signal"), dict) else {},
        "smoking_pause_signal": raw.get("smoking_pause_signal") if isinstance(raw.get("smoking_pause_signal"), dict) else {},
        "exact_visual_evidence": [str(x)[:1000] for x in evidence if x][:12],
        "uncertainty": [str(x)[:1000] for x in uncertainty if x][:10],
        "qwen_json": raw,
    }


def _fallback_from_live(candidate: dict[str, Any], error_text: str | None = None) -> dict[str, Any]:
    parts = []
    if candidate.get("live_summary"):
        parts.append(str(candidate.get("live_summary")))
    if candidate.get("location_hint"):
        parts.append("lieu=" + str(candidate.get("location_hint")))
    if candidate.get("objects"):
        parts.append("objets=" + json_dumps(candidate.get("objects")))
    if candidate.get("affordances"):
        parts.append("affordances=" + json_dumps(candidate.get("affordances")))
    if candidate.get("possible_user_activities"):
        parts.append("activites_possibles=" + json_dumps(candidate.get("possible_user_activities")))
    return {
        "scene_summary_detailed": " | ".join(parts)[:2500],
        "observed_activity": "unknown",
        "activity_confidence": 0.0,
        "location_hint": candidate.get("location_hint"),
        "spatial_layout": None,
        "objects": candidate.get("objects") if isinstance(candidate.get("objects"), list) else [],
        "affordances": candidate.get("affordances") if isinstance(candidate.get("affordances"), list) else [],
        "visible_text": [],
        "people_presence": {},
        "screens_or_devices": [],
        "posture_motion": {},
        "work_or_rest_signal": {},
        "smoking_pause_signal": {},
        "exact_visual_evidence": [x for x in parts if x][:8],
        "uncertainty": ["deep_vlm_failed: " + (error_text or "unknown_error")[:400]],
        "qwen_json": {"fallback_from_live_vision": True, "error": error_text},
    }


def run_offline_deep_vision_for_bundles(
    person_id: str = "me",
    *,
    package_date: str | None = None,
    live_session_id: str | None = None,
    model: str | None = None,
    timeout_per_image: float | None = None,
    max_keyframes_per_bundle: int = 12,
    transcript_char_threshold: int | None = None,
    limit_bundles: int = 200,
    append_to_brain2: bool = True,
    fail_on_vlm_error: bool = False,
    use_vlm: bool = True,
) -> dict[str, Any]:
    """Run the heavy/offline VLM pass over assembled event bundles.

    If transcript_char_threshold is None, all bundles with available images are
    eligible.  In the post-stop flow we run it before V16.0 silent-life mining so
    silent events can use detailed observations.  Default max images: 12 per
    bundle.
    """
    ensure_deep_vision_schema()
    from .config import get_settings
    settings = get_settings()
    timeout_per_image = float(timeout_per_image or settings.poststop_vlm_timeout_s)
    day = _package_day(package_date)
    run_id = stable_id("bldeep161run", person_id, day, now_iso(), uuid4().hex)
    now = now_iso()
    scanned = selected = readable = analyzed = appended = 0
    status = "ok"
    error_text = None
    frame_failures: list[dict[str, Any]] = []
    chosen_model = _resolve_offline_vlm_model(model)
    try:
        with connect() as con:
            if not _table_exists(con, "brainlive_event_bundles_v1514"):
                bundles: list[dict[str, Any]] = []
            else:
                bundle_sql = "SELECT * FROM brainlive_event_bundles_v1514 WHERE person_id=? AND package_date=?"
                bundle_params: list[Any] = [person_id, day]
                if live_session_id:
                    bundle_sql += " AND live_session_id=?"
                    bundle_params.append(str(live_session_id))
                bundle_sql += " ORDER BY start_time LIMIT ?"
                bundle_params.append(int(limit_bundles))
                bundles = _rows(con, bundle_sql, tuple(bundle_params))
            scanned = len(bundles)
            # VLM is intentionally the only GPU-heavy work in this phase.  The
            # phase boundary releases WhisperX/Pyannote allocations before the
            # first frame and frees VLM allocations before Brain2 starts.
            with gpu_phase("post_stop_deep_vision", release_before=True, release_after=True):
                for b in bundles:
                    if transcript_char_threshold is not None and _transcript_chars(b) > int(transcript_char_threshold):
                        continue
                    all_candidates = _keyframe_candidates(b)
                    try:
                        frames = select_keyframes_for_bundle(b, max_keyframes=max_keyframes_per_bundle)
                    except DeepVisionCoveragePersistError as exc:
                        # E64-I4.4: coverage proof could not be durably written.
                        # Do not analyse on an unverifiable coverage: record a
                        # non-retryable blocked failure so the run row is blocked
                        # and the I0.4 gate marks Deep Vision failed.
                        frame_failures.append({
                            "bundle_id": b.get("bundle_id"),
                            "frame_id": (all_candidates[0].get("frame_id") if all_candidates else None),
                            "error_code": "blocked_coverage_persist_failed",
                            "retryable": False,
                            "error": str(exc)[:1500],
                        })
                        continue
                    except DeepVisionEvidenceMaterializationError as exc:
                        selected += exc.selected_count
                        readable += exc.readable_count
                        frame_failures.append({
                            "bundle_id": b.get("bundle_id"),
                            "frame_id": exc.missing_frame_ids[0] if exc.missing_frame_ids else None,
                            "error_code": "blocked_selected_pixels_unavailable",
                            "retryable": False,
                            "selected_keyframes": exc.selected_count,
                            "readable_keyframes": exc.readable_count,
                            "missing_frame_ids": list(exc.missing_frame_ids),
                            "error": str(exc)[:1500],
                        })
                        record_phase_event(
                            "deep_vision_selected_pixels_unavailable",
                            bundle_id=b.get("bundle_id"),
                            selected_keyframes=exc.selected_count,
                            readable_keyframes=exc.readable_count,
                            missing_frame_ids=list(exc.missing_frame_ids)[:20],
                        )
                        continue
                    # A bundle with captured visual evidence must not silently
                    # report a successful deep-vision stage with zero usable
                    # pixels. This blocks cleanup and leaves the source files for
                    # repair/resume rather than letting Brain2 proceed on a false
                    # "no visual evidence" conclusion.
                    if all_candidates and not frames:
                        frame_failures.append({
                            "bundle_id": b.get("bundle_id"),
                            "frame_id": all_candidates[0].get("frame_id"),
                            "error_code": "blocked_visual_evidence_unavailable",
                            "retryable": False,
                            "error": "bundle contains visual frames but no readable keyframe path",
                        })
                        record_phase_event("deep_vision_visual_evidence_unavailable", bundle_id=b.get("bundle_id"), frame_id=all_candidates[0].get("frame_id"))
                        continue
                    selected += len(frames)
                    readable += len(frames)
                    parallel_results: dict[str, dict[str, Any]] = {}
                    cloud_parallel = (
                        use_vlm
                        and os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
                        in {"1", "true", "yes", "on"}
                        and os.environ.get("MLOMEGA_CLOUD_VLM_PROVIDER", "local").strip().lower()
                        == "gemini"
                    )
                    if cloud_parallel:
                        try:
                            vision_workers = max(
                                1,
                                min(
                                    12,
                                    int(os.environ.get("MLOMEGA_PRO_VISION_WORKERS", "8")),
                                ),
                            )
                        except ValueError:
                            vision_workers = 8

                        pending_frames: list[tuple[str, dict[str, Any]]] = []
                        for frame in frames:
                            observation_id = stable_id(
                                "bldeep161",
                                person_id,
                                b.get("bundle_id"),
                                frame.get("frame_id") or frame.get("image_path"),
                                frame.get("sample_index"),
                                chosen_model,
                            )
                            existing = con.execute(
                                "SELECT status FROM brainlive_deep_vision_observations_v161 "
                                "WHERE deep_observation_id=?",
                                (observation_id,),
                            ).fetchone()
                            if not (existing and existing["status"] == "ok"):
                                pending_frames.append((observation_id, frame))

                        def _analyze_cloud_frame(frame: dict[str, Any]) -> dict[str, Any]:
                            started = time.time()
                            try:
                                raw = _deep_vlm_json(
                                    str(frame.get("image_path")),
                                    model=chosen_model,
                                    timeout=timeout_per_image,
                                    personal_context={
                                        "bundle_title": b.get("title"),
                                        "place": _safe_json(b.get("place_json"), {}),
                                        "live_summary": frame.get("live_summary"),
                                    },
                                )
                                return {
                                    "raw": raw,
                                    "status": "ok",
                                    "error": None,
                                    "failure": None,
                                    "latency_ms": int((time.time() - started) * 1000),
                                }
                            except Exception as exc:
                                failure = classify_failure(exc)
                                return {
                                    "raw": {},
                                    "status": (
                                        "retryable_error" if failure.retryable else "blocked"
                                    ),
                                    "error": str(exc)[:1500],
                                    "failure": failure,
                                    "exception": exc,
                                    "latency_ms": int((time.time() - started) * 1000),
                                }

                        if pending_frames:
                            with ThreadPoolExecutor(
                                max_workers=min(vision_workers, len(pending_frames)),
                                thread_name_prefix="mlomega-pro-vision",
                            ) as pool:
                                futures = {
                                    pool.submit(
                                        copy_context().run, _analyze_cloud_frame, frame
                                    ): observation_id
                                    for observation_id, frame in pending_frames
                                }
                                for future in as_completed(futures):
                                    parallel_results[futures[future]] = future.result()

                    for f in frames:
                        obs_id = stable_id("bldeep161", person_id, b.get("bundle_id"), f.get("frame_id") or f.get("image_path"), f.get("sample_index"), chosen_model)
                        existing = con.execute("SELECT status FROM brainlive_deep_vision_observations_v161 WHERE deep_observation_id=?", (obs_id,)).fetchone()
                        if existing and existing["status"] == "ok":
                            analyzed += 1
                            continue
                        started = time.time()
                        status_row = "ok"
                        row_error = None
                        raw: dict[str, Any] = {}
                        if obs_id in parallel_results:
                            result = parallel_results[obs_id]
                            raw = dict(result.get("raw") or {})
                            status_row = str(result.get("status") or "blocked")
                            row_error = result.get("error")
                            latency_ms = int(result.get("latency_ms") or 0)
                            failure = result.get("failure")
                            if failure is not None:
                                frame_failures.append({
                                    "bundle_id": b.get("bundle_id"),
                                    "frame_id": f.get("frame_id"),
                                    "error_code": failure.code,
                                    "retryable": failure.retryable,
                                    "error": row_error,
                                })
                                record_phase_event(
                                    "deep_vision_frame_failed",
                                    bundle_id=b.get("bundle_id"),
                                    frame_id=f.get("frame_id"),
                                    error_code=failure.code,
                                    retryable=failure.retryable,
                                )
                                if fail_on_vlm_error:
                                    raise result.get("exception") or RuntimeError(row_error)
                        elif use_vlm:
                            try:
                                raw = _deep_vlm_json(str(f.get("image_path")), model=chosen_model, timeout=timeout_per_image, personal_context={"bundle_title": b.get("title"), "place": _safe_json(b.get("place_json"), {}), "live_summary": f.get("live_summary")})
                            except Exception as exc:
                                failure = classify_failure(exc)
                                row_error = str(exc)[:1500]
                                # Store a classification at image granularity.  A later
                                # resume will skip `ok` observations and retry only this
                                # keyframe with the same deterministic observation id.
                                status_row = "retryable_error" if failure.retryable else "blocked"
                                frame_failures.append({"bundle_id": b.get("bundle_id"), "frame_id": f.get("frame_id"), "error_code": failure.code, "retryable": failure.retryable, "error": row_error})
                                record_phase_event("deep_vision_frame_failed", bundle_id=b.get("bundle_id"), frame_id=f.get("frame_id"), error_code=failure.code, retryable=failure.retryable)
                                if fail_on_vlm_error:
                                    raise
                        else:
                            row_error = "use_vlm=false"
                            status_row = "skipped_no_vlm"
                        norm = _normalize_observation(raw) if raw else _fallback_from_live(f, row_error)
                        if obs_id not in parallel_results:
                            latency_ms = int((time.time() - started) * 1000)
                        upsert(con, "brainlive_deep_vision_observations_v161", {
                            "deep_observation_id": obs_id,
                            "run_id": run_id,
                            "person_id": person_id,
                            "package_date": day,
                            "bundle_id": b.get("bundle_id"),
                            "live_session_id": b.get("live_session_id"),
                            "conversation_id": b.get("brain2_conversation_id"),
                            "frame_id": f.get("frame_id"),
                            "image_path": str(Path(str(f.get("image_path"))).expanduser()),
                            "frame_time": f.get("frame_time"),
                            "sample_index": int(f.get("sample_index") or 0),
                            "sample_reason": f.get("sample_reason"),
                            "model": chosen_model,
                            "status": status_row,
                            "scene_summary_detailed": norm["scene_summary_detailed"],
                            "observed_activity": norm["observed_activity"],
                            "activity_confidence": norm["activity_confidence"],
                            "location_hint": norm.get("location_hint"),
                            "spatial_layout": norm.get("spatial_layout"),
                            "objects_json": json_dumps(norm.get("objects") or []),
                            "affordances_json": json_dumps(norm.get("affordances") or []),
                            "visible_text_json": json_dumps(norm.get("visible_text") or []),
                            "people_presence_json": json_dumps(norm.get("people_presence") or {}),
                            "screens_or_devices_json": json_dumps(norm.get("screens_or_devices") or []),
                            "posture_motion_json": json_dumps(norm.get("posture_motion") or {}),
                            "work_or_rest_signal_json": json_dumps(norm.get("work_or_rest_signal") or {}),
                            "smoking_pause_signal_json": json_dumps(norm.get("smoking_pause_signal") or {}),
                            "exact_visual_evidence_json": json_dumps(norm.get("exact_visual_evidence") or []),
                            "uncertainty_json": json_dumps(norm.get("uncertainty") or []),
                            "qwen_json": json_dumps(norm.get("qwen_json") or {}),
                            "latency_ms": latency_ms,
                            "error_text": row_error,
                            "created_at": now_iso(),
                            "updated_at": now_iso(),
                        }, "deep_observation_id")
                        if status_row == "ok":
                            analyzed += 1
            con.commit()
        if selected != readable or readable != analyzed:
            frame_failures.append({
                "error_code": "blocked_deep_vision_count_mismatch",
                "retryable": False,
                "selected_keyframes": selected,
                "readable_keyframes": readable,
                "analyzed_keyframes": analyzed,
                "error": (
                    "deep vision proof mismatch: "
                    f"selected={selected}, readable={readable}, analyzed={analyzed}"
                ),
            })
        if frame_failures:
            status = "retryable_error" if all(bool(item.get("retryable")) for item in frame_failures) else "blocked"
            error_text = f"{len(frame_failures)} deep VLM keyframe(s) unresolved"
        # Do not append fallback/error observations to Brain2. The retained `ok`
        # images are durable, while unresolved images keep the post-stop stage
        # retryable and block Brain2/cleanup until they are repaired.
        if append_to_brain2 and status == "ok":
            appended = append_deep_vision_context_turns_to_brain2(person_id, package_date=day, only_status_ok=True).get("turns_appended", 0)
    except Exception as exc:
        status = "error"
        error_text = str(exc)[:2000]
        raise
    finally:
        with connect() as con:
            upsert(con, "brainlive_deep_vision_runs_v161", {
                "run_id": run_id,
                "person_id": person_id,
                "package_date": day,
                "model": chosen_model,
                "max_keyframes_per_bundle": int(max_keyframes_per_bundle or 12),
                "scanned_bundles": scanned,
                "selected_keyframes": selected,
                "readable_keyframes": readable,
                "analyzed_keyframes": analyzed,
                "appended_brain2_turns": appended,
                "status": status,
                "error_text": error_text,
                "created_at": now,
                "updated_at": now_iso(),
            }, "run_id")
            con.commit()
        # Qwen-VL is only needed for this phase. Do not leave it resident while
        # Brain2 and its local LLM are about to use the same GPU.
        if use_vlm:
            ollama_unload(model=chosen_model)
            record_phase_event("deep_vision_model_unloaded", model=chosen_model)
    return {"version": VERSION, "run_id": run_id, "person_id": person_id, "package_date": day, "live_session_id": live_session_id, "model": chosen_model, "max_keyframes_per_bundle": int(max_keyframes_per_bundle or 12), "scanned_bundles": scanned, "selected_keyframes": selected, "readable_keyframes": readable, "analyzed_keyframes": analyzed, "appended_brain2_turns": appended, "status": status, "failures": frame_failures, "error": error_text}


def _deep_turn_text(row: dict[str, Any]) -> str:
    parts = []
    if row.get("scene_summary_detailed"):
        parts.append(str(row.get("scene_summary_detailed")))
    if row.get("observed_activity"):
        parts.append("activité_visible=" + str(row.get("observed_activity")))
    if row.get("location_hint"):
        parts.append("lieu_probable=" + str(row.get("location_hint")))
    if row.get("spatial_layout"):
        parts.append("spatial=" + str(row.get("spatial_layout")))
    for label, col in (("objets", "objects_json"), ("affordances", "affordances_json"), ("texte_visible", "visible_text_json"), ("écrans_appareils", "screens_or_devices_json")):
        vals = _safe_json(row.get(col), [] if col.endswith("json") else {})
        if vals:
            parts.append(f"{label}=" + json_dumps(vals))
    ev = _safe_json(row.get("exact_visual_evidence_json"), [])
    if ev:
        parts.append("preuves_visuelles=" + json_dumps(ev[:8]))
    unc = _safe_json(row.get("uncertainty_json"), [])
    if unc:
        parts.append("incertitudes=" + json_dumps(unc[:6]))
    return ("[CONTEXT_VISION_DEEP] " + " | ".join(parts))[:8000]


def _active_conversation_for_bundle(
    con: Any, *, person_id: str, bundle_id: str, fallback: str | None
) -> str | None:
    """Resolve the current Brain2 conversation after Deep Audio supersession.

    The V15.14 export points at the first assembled conversation. Deep Audio then
    creates a refined conversation and marks the first scope inactive. Appending
    Deep Vision to the stale export made the real Brain2 path miss every VLM
    observation. Resolve through the durable active scope, without rewriting or
    deleting the immutable first export.
    """

    if _table_exists(con, "v18_conversation_scopes"):
        rows = _rows(
            con,
            """SELECT conversation_id,evidence_json
                 FROM v18_conversation_scopes
                WHERE person_id=? AND active=1
                ORDER BY updated_at DESC, conversation_id""",
            (person_id,),
        )
        for row in rows:
            evidence = _safe_json(row.get("evidence_json"), {})
            if isinstance(evidence, dict) and str(evidence.get("bundle_id") or "") == bundle_id:
                return str(row.get("conversation_id"))
    return str(fallback) if fallback else None


def _conversation_relative_seconds(con: Any, *, conversation_id: str, frame_time: Any) -> float | None:
    row = con.execute(
        "SELECT started_at FROM conversations WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    started = _parse_utc(row["started_at"] if row else None)
    captured = _parse_utc(frame_time)
    if started is None or captured is None:
        return None
    return max(0.0, (captured - started).total_seconds())


def append_deep_vision_context_turns_to_brain2(person_id: str = "me", *, package_date: str | None = None, only_status_ok: bool = False) -> dict[str, Any]:
    """Append deep VLM observations as context turns in exported Brain2 conversations."""
    ensure_deep_vision_schema()
    day = _package_day(package_date)
    appended = 0
    with connect() as con:
        status_filter = "AND o.status='ok'" if only_status_ok else "AND o.status IN ('ok','vlm_error','skipped_no_vlm')"
        rows = _rows(con, f"""
            SELECT o.*, e.conversation_id AS exported_conversation_id
            FROM brainlive_deep_vision_observations_v161 o
            JOIN brainlive_brain2_event_exports_v1514 e ON e.bundle_id=o.bundle_id
            WHERE o.person_id=? AND o.package_date=? {status_filter}
            ORDER BY o.bundle_id, o.sample_index, o.frame_time
        """, (person_id, day))
        for r in rows:
            conv_id = _active_conversation_for_bundle(
                con,
                person_id=person_id,
                bundle_id=str(r.get("bundle_id") or ""),
                fallback=r.get("exported_conversation_id") or r.get("conversation_id"),
            )
            if not conv_id:
                continue
            export_id = stable_id("bldeep161export", r.get("deep_observation_id"), conv_id)
            if con.execute("SELECT 1 FROM brainlive_deep_vision_brain2_exports_v161 WHERE export_id=?", (export_id,)).fetchone():
                continue
            max_idx_row = con.execute("SELECT COALESCE(MAX(idx), -1) AS m FROM turns WHERE conversation_id=?", (conv_id,)).fetchone()
            idx = int(max_idx_row["m"] or -1) + 1
            text = _deep_turn_text(r)
            turn_id = stable_id("turn_bldeep161", conv_id, r.get("deep_observation_id"), text)
            prev = con.execute("SELECT turn_id FROM turns WHERE conversation_id=? ORDER BY idx DESC LIMIT 1", (conv_id,)).fetchone()
            relative_s = _conversation_relative_seconds(
                con, conversation_id=conv_id, frame_time=r.get("frame_time")
            )
            upsert(con, "turns", {
                "turn_id": turn_id,
                "conversation_id": conv_id,
                "idx": idx,
                "speaker_label": "context_vision_deep",
                "person_id": None,
                "start_s": relative_s,
                "end_s": relative_s,
                "text": text,
                "previous_turn_id": prev["turn_id"] if prev else None,
                "metadata_json": json_dumps({
                    "kind": "deep_vision_context",
                    "time": r.get("frame_time"),
                    "evidence_role": "system_observation_not_user_speech",
                    "brainlive_bundle_id": r.get("bundle_id"),
                    "deep_observation_id": r.get("deep_observation_id"),
                    "frame_id": r.get("frame_id"),
                    "image_path": r.get("image_path"),
                    "model": r.get("model"),
                    "status": r.get("status"),
                    "v16_1": True,
                }),
            }, "turn_id")
            upsert(con, "brainlive_deep_vision_brain2_exports_v161", {
                "export_id": export_id,
                "deep_observation_id": r.get("deep_observation_id"),
                "bundle_id": r.get("bundle_id"),
                "conversation_id": conv_id,
                "turn_id": turn_id,
                "status": "exported",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }, "export_id")
            appended += 1
        con.commit()
    return {"version": VERSION, "person_id": person_id, "package_date": day, "turns_appended": appended}


def deep_vision_audit(person_id: str = "me", *, package_date: str | None = None) -> dict[str, Any]:
    ensure_deep_vision_schema()
    day = _package_day(package_date)
    with connect() as con:
        runs = _rows(con, "SELECT * FROM brainlive_deep_vision_runs_v161 WHERE person_id=? AND package_date=? ORDER BY created_at DESC LIMIT 5", (person_id, day))
        counts = _rows(con, "SELECT status, COUNT(*) AS n FROM brainlive_deep_vision_observations_v161 WHERE person_id=? AND package_date=? GROUP BY status", (person_id, day))
        exported = _rows(con, """
            SELECT COUNT(*) AS n FROM brainlive_deep_vision_brain2_exports_v161 e
            JOIN brainlive_deep_vision_observations_v161 o ON o.deep_observation_id=e.deep_observation_id
            WHERE o.person_id=? AND o.package_date=?
        """, (person_id, day))
    return {"version": VERSION, "person_id": person_id, "package_date": day, "latest_runs": runs, "observation_counts": {r["status"]: int(r["n"]) for r in counts}, "brain2_deep_vision_turns": int(exported[0]["n"]) if exported else 0}

# V18: failed deep-VLM responses never become pseudo-dialogue evidence.
from .v18_poststop_outputs import install_deep as _install_v18_deep_outputs
_globals_v18_deep_outputs = _install_v18_deep_outputs(__import__(__name__, fromlist=['*']))
globals().update(_globals_v18_deep_outputs)
