"""E64-I4.1 Deep Vision keyframe selection WITH coverage.

The historical Deep Vision selector (``select_keyframes_for_bundle`` in
``brainlive_offline_deep_vision_v16_1``) sampled ``max_keyframes`` frames by even
index spacing and silently dropped every other frame. That is a *quota*, not a
*policy*: on the reference video it happened to keep ~11 frames, but nothing
proved that the dropped frames were redundant, and a broken evidence bridge could
collapse the whole event to a single frame with no trace of the rest.

This module replaces the quota with a coverage-complete selection policy. A frame
becomes a keyframe when it carries genuinely new information:

* **scene/object/person change** - it opens a new ``VisionChangeAtom`` (a new or
  departed object/track, a people-count change, a scene/location change);
* **OCR** - the frame's observation has non-empty ``visible_text``;
* **explicit user request** - a live what_is/ocr/zoom/find focus request is
  linked to the frame (via a per-frame marker or a vision sensor/timeline event
  that names the ``frame_id``);
* **safety interval** - no keyframe has been taken for
  ``MLOMEGA_DEEP_VISION_SAFETY_INTERVAL_S`` seconds (default 60), so a long,
  unchanging span still gets a periodic anchor.

Crucially, every frame that is *not* selected is mapped durably to the keyframe
(and the ``VisionChangeAtom``) that represents it, so zero frame is orphaned. The
selection is not a quota: a change-rich session produces more keyframes than a
static one, and there is no silent ``rows[:N]`` truncation.

No LLM/VLM is called here - selection is deterministic. The heavy VLM still runs
downstream on the selected keyframes via the same runner, and the same durable
``brainlive_deep_vision_runs_v161`` writer records selected/analysed counts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .vision_atoms import VisionChangeAtom, reduce_vision_timeline

# Reasons a frame is promoted to a keyframe. Ordered by priority so that a frame
# satisfying several conditions records the strongest single reason but the full
# set is retained for audit.
REASON_SCENE_CHANGE = "scene_object_person_change"
REASON_OCR = "ocr_visible_text"
REASON_USER_REQUEST = "explicit_user_request"
REASON_SAFETY_INTERVAL = "safety_interval"
_REASON_PRIORITY = (
    REASON_USER_REQUEST,
    REASON_OCR,
    REASON_SCENE_CHANGE,
    REASON_SAFETY_INTERVAL,
)

# How a non-selected frame is accounted for in the coverage manifest.
COVER_REPRESENTED_BY_KEYFRAME = "represented_by_keyframe"

DEFAULT_SAFETY_INTERVAL_S = 60.0
SAFETY_INTERVAL_ENV = "MLOMEGA_DEEP_VISION_SAFETY_INTERVAL_S"

# E64-I4.2 Codex arbitrage: the state signature that OPENS a keyframe is
# track-agnostic. A change of ``track_id`` alone (the tracker re-numbering the
# same person) is NOT a cognitive event and must not open a keyframe.  Two
# neighbouring "micro-transitions" (a brief A->B->A flip, or a burst of changes
# inside a short temporal window) are grouped into a single keyframe event.  A
# genuine change of labels / people-count / OCR text / location/scene, or a major
# spatial displacement of a bounding box, still opens a keyframe.  Every frame -
# keyframe or not - stays 100% covered.
DEFAULT_MICRO_TRANSITION_WINDOW_S = 2.5
MICRO_TRANSITION_WINDOW_ENV = "MLOMEGA_DEEP_VISION_MICRO_TRANSITION_WINDOW_S"

# A bbox centroid must move by at least this fraction of the frame's diagonal
# (normalised 0..1 coordinates) to count as a real spatial change when labels are
# otherwise identical. Only used when bbox/position is present in observations;
# see ``_spatial_signature`` for the documented no-position limitation.
DEFAULT_SPATIAL_MOVE_THRESHOLD = 0.20
SPATIAL_MOVE_THRESHOLD_ENV = "MLOMEGA_DEEP_VISION_SPATIAL_MOVE_THRESHOLD"

COVERAGE_TABLE = "deep_vision_frame_coverage_v19"

_COVERAGE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {COVERAGE_TABLE}(
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  bundle_id TEXT NOT NULL,
  frame_id TEXT NOT NULL,
  live_session_id TEXT,
  is_keyframe INTEGER NOT NULL DEFAULT 0,
  covered_by_keyframe_id TEXT,
  covered_by_atom_id TEXT,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(person_id, package_date, bundle_id, frame_id)
);
CREATE INDEX IF NOT EXISTS idx_deep_vision_frame_coverage_bundle
  ON {COVERAGE_TABLE}(person_id, package_date, bundle_id, is_keyframe);
"""


def safety_interval_seconds() -> float:
    """Configurable safety interval; falls back to a sane 60s default."""
    raw = os.environ.get(SAFETY_INTERVAL_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_SAFETY_INTERVAL_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SAFETY_INTERVAL_S
    return value if value > 0 else DEFAULT_SAFETY_INTERVAL_S


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def micro_transition_window_seconds() -> float:
    """Temporal window inside which neighbouring flips are grouped into one event.

    ``0`` disables grouping (every track-agnostic change opens a keyframe).
    """
    return _float_env(MICRO_TRANSITION_WINDOW_ENV, DEFAULT_MICRO_TRANSITION_WINDOW_S)


def spatial_move_threshold() -> float:
    return _float_env(SPATIAL_MOVE_THRESHOLD_ENV, DEFAULT_SPATIAL_MOVE_THRESHOLD)


def ensure_coverage_schema(con: Any) -> None:
    con.executescript(_COVERAGE_SCHEMA)


# --------------------------------------------------------------------------- #
# Track-agnostic semantic signature (Codex I4.2 option (b))                    #
# --------------------------------------------------------------------------- #

def _label_multiset(objects: Any) -> tuple[str, ...]:
    """Sorted multiset of visible labels, IGNORING track_id.

    ``[{person,t1},{person,t2}]`` and ``[{person,t9},{person,t3}]`` compare equal
    (same two people, tracker just renumbered them).  ``[{person},{dog}]`` differs
    from ``[{person}]`` (a real object appeared).  The multiset (not the set) is
    kept so ``person,person`` differs from ``person`` - a second person arriving
    IS a real change even though the label string is identical.
    """
    out: list[str] = []
    for obj in objects or []:
        if isinstance(obj, Mapping):
            label = str(obj.get("label") or "").strip()
        else:
            label = str(obj or "").strip()
        if label:
            out.append(label)
    out.sort()
    return tuple(out)


def _bbox_of(obj: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    """Best-effort normalised (cx, cy, w, h) centroid+size for one detection.

    Accepts a few common shapes (``bbox``/``box`` as [x1,y1,x2,y2] or
    {x,y,w,h}).  Returns ``None`` when no position is present - which is the
    common case in this dataset (see the documented limitation in
    ``_spatial_signature``).
    """
    raw = obj.get("bbox")
    if raw is None:
        raw = obj.get("box")
    if raw is None:
        raw = obj.get("position")
    if isinstance(raw, Mapping):
        try:
            x = float(raw.get("x", raw.get("cx", raw.get("left"))))
            y = float(raw.get("y", raw.get("cy", raw.get("top"))))
            w = float(raw.get("w", raw.get("width", 0.0)) or 0.0)
            h = float(raw.get("h", raw.get("height", 0.0)) or 0.0)
        except (TypeError, ValueError):
            return None
        return (x + w / 2.0, y + h / 2.0, w, h)
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            x1, y1, x2, y2 = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
        except (TypeError, ValueError):
            return None
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0, abs(x2 - x1), abs(y2 - y1))
    return None


def _spatial_signature(objects: Any, threshold: float) -> tuple[tuple[str, int, int], ...] | None:
    """Coarse per-label centroid buckets so a MAJOR displacement counts as change.

    Returns ``None`` when NO detection carries a usable bbox/position (the case in
    the current ``vision_scene_observations`` data, which stores only label +
    track_id + confidence). LIMITATION: without positions, a pure spatial move of
    an object whose label set is unchanged CANNOT be detected here and will not
    open a keyframe - this is the documented cost of the label-set-only signal and
    is safe (the frame stays covered by its representative). When positions ARE
    present, the centroid is bucketed on a grid of ``1/threshold`` cells so only a
    displacement beyond ``threshold`` of the frame changes the bucket.
    """
    buckets: list[tuple[str, int, int]] = []
    saw_position = False
    grid = max(1, int(round(1.0 / threshold))) if threshold > 0 else 1
    for obj in objects or []:
        if not isinstance(obj, Mapping):
            continue
        box = _bbox_of(obj)
        if box is None:
            continue
        saw_position = True
        cx, cy, _w, _h = box
        gx = int(min(max(cx, 0.0), 0.999999) * grid)
        gy = int(min(max(cy, 0.0), 0.999999) * grid)
        buckets.append((str(obj.get("label") or ""), gx, gy))
    if not saw_position:
        return None
    buckets.sort()
    return tuple(buckets)


def frame_signature(
    item: Mapping[str, Any], *, spatial_threshold: float | None = None
) -> tuple[Any, ...]:
    """Track-agnostic semantic signature of ONE timeline/observation item.

    Two items with the same signature are the SAME cognitive state and must not
    each open a keyframe. ``track_id`` is intentionally excluded; a spatial
    signature is appended only when position data exists.
    """
    threshold = spatial_move_threshold() if spatial_threshold is None else spatial_threshold
    objects = item.get("objects")
    if objects is None:
        objects = item.get("objects_json")
    if isinstance(objects, str):
        import json

        try:
            objects = json.loads(objects)
        except (TypeError, ValueError):
            objects = []
    people = item.get("people_count")
    try:
        people = None if people is None else int(people)
    except (TypeError, ValueError):
        people = None
    location = item.get("location_hint") or item.get("location") or None
    scene = item.get("summary") if item.get("summary") is not None else item.get("scene_summary")
    return (
        _label_multiset(objects),
        people,
        tuple(_visible_text_of(item)),
        str(location) if location else None,
        str(scene) if scene else None,
        _spatial_signature(objects, threshold),
    )


# --------------------------------------------------------------------------- #
# E64-I4.3 VisionRT position bridge (constant-label displacement)              #
# --------------------------------------------------------------------------- #
# The semantic ``vision_scene_observations`` timeline carries label + track_id +
# confidence but NO bbox, so ``_spatial_signature`` returned ``None`` and a pure
# spatial move at constant labels never opened a keyframe (the documented I4.2
# limitation). VisionRT (worldbrain) DID record the positions live: it writes
# ``visual_events_v19`` rows whose ``observation_json`` carries ``bbox`` (an
# ``entity_last_seen`` row's ``{"bbox":[...]}`` or a ``change_moved`` row's
# ``{"after":{"bbox":[...]}}``). These positions are already in the DB at night,
# keyed by the same frame_id/live_session_id the bundle timeline uses. We reuse
# them here (no new detection, no VLM) to inject positions into timeline items
# that lack them, so a real displacement opens a keyframe. Absent bbox -> nothing
# injected -> the documented safe fallback (frame stays covered by its rep).


def frame_id_from_evidence(refs: Any) -> str | None:
    """Recover the ``frame_id`` a VisionRT event points at, from its evidence.

    Worldbrain writes evidence refs as STRINGS ``"frame:<frame_id>"`` (the real
    live format); some callers pass mappings carrying ``frame_id``. Both are
    honoured; nothing else is guessed.
    """
    import json as _json

    if isinstance(refs, str):
        try:
            refs = _json.loads(refs)
        except (TypeError, ValueError):
            refs = []
    for ref in refs or []:
        if isinstance(ref, str) and ref.startswith("frame:"):
            fid = ref[len("frame:"):].strip()
            if fid:
                return fid
        elif isinstance(ref, Mapping):
            fid = str(ref.get("frame_id") or "").strip()
            if fid:
                return fid
    return None


def load_visionrt_frame_positions(
    con: Any,
    *,
    person_id: str,
    live_session_id: str | None = None,
    frame_ids: Iterable[str] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Map ``frame_id -> [{label, bbox:[x1,y1,x2,y2]}]`` from ``visual_events_v19``.

    The bbox is returned AS RECORDED by VisionRT - i.e. in PIXELS of the frame
    it was detected on (visionrt emits detector boxes ``[x1,y1,x2,y2]`` in image
    coordinates). Callers MUST normalise via :func:`normalize_frame_positions`
    before feeding the spatial signature. ALL detections of a frame are kept
    (several objects on one image are all returned). Frame identity comes from
    the event's evidence refs (worldbrain's real ``"frame:<id>"`` strings) or,
    for mapping-evidence writers, the linked evidence asset. Returns an empty
    map on any error or when the table is absent - the caller then degrades to
    the label-set-only signal (documented fallback).
    """
    import json as _json

    wanted = {str(f).strip() for f in frame_ids if str(f).strip()}
    positions: dict[str, list[dict[str, Any]]] = {}
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='visual_events_v19'"
        ).fetchone()
        if not exists:
            return {}
        sql = (
            "SELECT e.entity_json, e.observation_json, e.evidence_refs_json, "
            "a.frame_id AS asset_frame_id "
            "FROM visual_events_v19 e "
            "LEFT JOIN visual_evidence_assets_v19 a ON a.visual_asset_id = e.asset_id "
            "WHERE e.person_id=? AND e.truth_level='observed' "
            "AND e.event_type IN ('entity_last_seen','change_moved','change_appeared')"
        )
        params: list[Any] = [person_id]
        if live_session_id:
            sql += " AND e.live_session_id=?"
            params.append(str(live_session_id))
        rows = con.execute(sql, tuple(params)).fetchall()
    except Exception:
        return {}

    for row in rows:
        try:
            data = dict(row) if not isinstance(row, dict) else row
        except Exception:
            data = {
                "entity_json": row[0], "observation_json": row[1],
                "evidence_refs_json": row[2], "asset_frame_id": row[3],
            }
        obs_raw = data.get("observation_json")
        try:
            obs = _json.loads(obs_raw) if isinstance(obs_raw, str) else (obs_raw or {})
        except (TypeError, ValueError):
            obs = {}
        if not isinstance(obs, Mapping):
            continue
        # A move row carries the destination position under ``after.bbox``; a
        # last-seen/appeared row carries it directly under ``bbox``.
        bbox = obs.get("bbox")
        if bbox is None and isinstance(obs.get("after"), Mapping):
            bbox = obs["after"].get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        ent_raw = data.get("entity_json")
        try:
            ent = _json.loads(ent_raw) if isinstance(ent_raw, str) else (ent_raw or {})
        except (TypeError, ValueError):
            ent = {}
        label = str((ent or {}).get("label") or "").strip()
        frame_id = (
            frame_id_from_evidence(data.get("evidence_refs_json"))
            or str(data.get("asset_frame_id") or obs.get("frame_id") or "").strip()
            or None
        )
        if not frame_id:
            continue
        if wanted and frame_id not in wanted:
            continue
        positions.setdefault(frame_id, []).append(
            {"label": label, "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]}
        )
    return positions


def _image_dimensions(path: str | None) -> tuple[int, int] | None:
    """(width, height) read from a PNG/JPEG file header, pure Python.

    The stored keyframe is the SAME ``frame_bgr`` buffer VisionRT ran detection
    on (visionrt records keyframes from the detection frame), so the file's own
    pixel dimensions are the correct normaliser for its bboxes. Returns ``None``
    for a missing/unreadable/unknown-format file - never guesses.
    """
    if not path:
        return None
    try:
        from pathlib import Path as _Path

        p = _Path(path).expanduser()
        with p.open("rb") as fh:
            head = fh.read(26)
            # PNG: 8-byte signature then IHDR with big-endian width/height.
            if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
                w = int.from_bytes(head[16:20], "big")
                h = int.from_bytes(head[20:24], "big")
                return (w, h) if w > 0 and h > 0 else None
            # JPEG: scan segments for a SOFn marker carrying height/width.
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    marker = fh.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    code = marker[1]
                    if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                        continue
                    seg_len_raw = fh.read(2)
                    if len(seg_len_raw) < 2:
                        return None
                    seg_len = int.from_bytes(seg_len_raw, "big")
                    if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                        body = fh.read(5)
                        if len(body) < 5:
                            return None
                        h = int.from_bytes(body[1:3], "big")
                        w = int.from_bytes(body[3:5], "big")
                        return (w, h) if w > 0 and h > 0 else None
                    fh.seek(seg_len - 2, 1)
    except Exception:
        return None
    return None


def load_frame_dimensions(
    con: Any,
    *,
    frame_ids: Iterable[str],
    image_paths_by_frame: Mapping[str, str] | None = None,
) -> dict[str, tuple[int, int]]:
    """Resolve each frame's REAL pixel dimensions, from real sources only.

    Priority (documented, no magic):
    1. ``vision_frames.width/height`` when set (the schema's authoritative slot -
       currently every writer leaves them NULL, hence the fallbacks);
    2. ``vision_frames.metadata_json`` ``width``/``height`` (or
       ``frame_width``/``frame_height``) when a capture client recorded them;
    3. the stored keyframe file's own header (PNG/JPEG probe) - VisionRT detects
       on the same buffer the keyframe recorder stores, so the file's dimensions
       ARE the bbox coordinate space.

    The live ``target_video_height`` (480/540/720 depending on network profile)
    is deliberately NOT used: it is a client hint, not a per-frame fact. A frame
    with no resolvable dimensions is simply ABSENT from the returned map - the
    caller must then skip position injection for it (explicit fallback), never
    clamp pixel values silently.
    """
    import json as _json

    ids = [str(f).strip() for f in frame_ids if str(f).strip()]
    dims: dict[str, tuple[int, int]] = {}
    paths: dict[str, str] = dict(image_paths_by_frame or {})
    if ids:
        try:
            placeholders = ",".join("?" for _ in ids)
            rows = con.execute(
                f"SELECT frame_id, width, height, metadata_json, image_path "
                f"FROM vision_frames WHERE frame_id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        except Exception:
            rows = []
        for row in rows:
            data = dict(row)
            fid = str(data.get("frame_id") or "").strip()
            if not fid:
                continue
            w, h = data.get("width"), data.get("height")
            try:
                if w and h and int(w) > 0 and int(h) > 0:
                    dims[fid] = (int(w), int(h))
                    continue
            except (TypeError, ValueError):
                pass
            meta_raw = data.get("metadata_json")
            try:
                meta = _json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
            except (TypeError, ValueError):
                meta = {}
            if isinstance(meta, Mapping):
                mw = meta.get("width") or meta.get("frame_width")
                mh = meta.get("height") or meta.get("frame_height")
                try:
                    if mw and mh and int(mw) > 0 and int(mh) > 0:
                        dims[fid] = (int(mw), int(mh))
                        continue
                except (TypeError, ValueError):
                    pass
            if data.get("image_path") and fid not in paths:
                paths[fid] = str(data.get("image_path"))
    for fid, path in paths.items():
        if fid in dims:
            continue
        probed = _image_dimensions(path)
        if probed:
            dims[fid] = probed
    return dims


def normalize_frame_positions(
    positions: Mapping[str, list[dict[str, Any]]],
    dims: Mapping[str, tuple[int, int]],
) -> tuple[dict[str, list[dict[str, Any]]], tuple[str, ...]]:
    """Convert VisionRT PIXEL bboxes to normalised 0..1 frame coordinates.

    ``_spatial_signature`` buckets centroids on a 0..1 grid, so raw pixel input
    would be clamped to a single cell and every real displacement would be
    invisible. A bbox whose four values already lie in [0, 1] is treated as
    normalised and passed through (dimensionless writers). Anything else is
    pixel data and REQUIRES the frame's real dimensions; a frame with positions
    but no known dimensions is dropped from the result and returned in
    ``skipped`` so the caller can trace the explicit fallback - it is NEVER
    silently clamped.
    """
    normalized: dict[str, list[dict[str, Any]]] = {}
    skipped: list[str] = []
    for fid, dets in positions.items():
        wh = dims.get(fid)
        out: list[dict[str, Any]] = []
        frame_skipped = False
        for det in dets:
            bbox = det.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                vals = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
            except (TypeError, ValueError):
                continue
            if all(0.0 <= v <= 1.0 for v in vals):
                out.append({**det, "bbox": vals})
                continue
            if not wh or wh[0] <= 0 or wh[1] <= 0:
                frame_skipped = True
                continue
            w, h = float(wh[0]), float(wh[1])
            out.append({**det, "bbox": [vals[0] / w, vals[1] / h, vals[2] / w, vals[3] / h]})
        if out:
            normalized[fid] = out
        if frame_skipped:
            skipped.append(fid)
    return normalized, tuple(skipped)


def _inject_positions(
    item: Mapping[str, Any], positions: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Return a copy of ``item`` whose objects carry VisionRT bbox by label.

    Only fills a bbox when the object has none, matching VisionRT detections to
    timeline objects by label (position order for homonyms). If no VisionRT
    position exists for the frame, the item is returned unchanged -> the
    signature stays label-set-only (documented safe fallback).
    """
    fid = str(item.get("frame_id") or "").strip()
    vrt = positions.get(fid) if fid else None
    if not vrt:
        return dict(item)
    objects = item.get("objects")
    if objects is None:
        objects = item.get("objects_json")
    if isinstance(objects, str):
        import json as _json

        try:
            objects = _json.loads(objects)
        except (TypeError, ValueError):
            objects = []
    if not isinstance(objects, list) or not objects:
        # No per-object list to enrich: expose the raw VisionRT detections so a
        # displacement of a tracked entity still contributes a spatial signature.
        merged = dict(item)
        merged["objects"] = [dict(d) for d in vrt]
        return merged
    # Group VisionRT positions by label so homonyms are matched in order.
    by_label: dict[str, list[list[float]]] = {}
    for d in vrt:
        by_label.setdefault(str(d.get("label") or ""), []).append(list(d.get("bbox") or []))
    used: dict[str, int] = {}
    new_objects: list[Any] = []
    for obj in objects:
        if not isinstance(obj, Mapping):
            new_objects.append(obj)
            continue
        obj = dict(obj)
        if _bbox_of(obj) is None:
            lbl = str(obj.get("label") or "").strip()
            slots = by_label.get(lbl) or []
            idx = used.get(lbl, 0)
            if idx < len(slots) and len(slots[idx]) >= 4:
                obj["bbox"] = slots[idx]
                used[lbl] = idx + 1
        new_objects.append(obj)
    merged = dict(item)
    merged["objects"] = new_objects
    return merged


@dataclass(frozen=True)
class FrameCoverage:
    """One frame's durable accounting: either a keyframe or represented by one."""

    frame_id: str
    is_keyframe: bool
    covered_by_keyframe_id: str | None
    covered_by_atom_id: str | None
    reason: str
    live_session_id: str | None = None


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of the coverage-complete keyframe selection for one bundle."""

    bundle_id: str | None
    selected_frame_ids: tuple[str, ...]
    coverage: tuple[FrameCoverage, ...]
    atoms: tuple[VisionChangeAtom, ...]
    reasons_by_frame: Mapping[str, tuple[str, ...]]

    @property
    def selected_count(self) -> int:
        return len(self.selected_frame_ids)

    @property
    def total_frames(self) -> int:
        return len(self.coverage)

    @property
    def orphan_frame_ids(self) -> tuple[str, ...]:
        """Frames that are neither a keyframe nor mapped to one (must be zero)."""
        orphans = []
        for c in self.coverage:
            if c.is_keyframe:
                continue
            if not c.covered_by_keyframe_id and not c.covered_by_atom_id:
                orphans.append(c.frame_id)
        return tuple(orphans)

    @property
    def fully_covered(self) -> bool:
        return not self.orphan_frame_ids


def _parse_time(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _visible_text_of(item: Mapping[str, Any]) -> list[str]:
    raw = item.get("visible_text")
    if raw is None:
        raw = item.get("visible_text_json")
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [raw] if raw.strip() else []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(t) for t in raw if str(t).strip()]


def _is_user_requested(
    item: Mapping[str, Any], requested_frame_ids: set[str]
) -> bool:
    """A frame is user-requested when the live path linked a focus intent to it.

    Two existing signals are honoured, no new table is invented:

    * a per-frame timeline marker (``user_requested`` / ``user_request`` /
      ``focus_request``) set by the live intent bridge; and
    * a ``frame_id`` present in ``requested_frame_ids`` (collected upstream from
      real vision sensor/timeline events - e.g. ``brainlive_sensor_events`` /
      ``brainlive_raw_timeline_v1514`` rows whose modality is a vision focus
      request naming that frame).
    """
    frame_id = str(item.get("frame_id") or "").strip()
    if frame_id and frame_id in requested_frame_ids:
        return True
    for key in ("user_requested", "user_request", "focus_request", "vision_request"):
        val = item.get(key)
        if isinstance(val, bool) and val:
            return True
        if isinstance(val, (str, dict, list)) and val:
            return True
    return False


def _atom_index_for_semantic_frame(
    atoms: Sequence[VisionChangeAtom],
) -> dict[str, VisionChangeAtom]:
    """Map every frame_id an atom covers -> that atom (exactly-once by design)."""
    index: dict[str, VisionChangeAtom] = {}
    for atom in atoms:
        for fid in atom.frame_refs:
            index[str(fid)] = atom
    return index


def _plan_keyframe_events(
    ordered: Sequence[tuple[str, tuple[Any, ...], float | None]],
    *,
    forced_frames: set[str],
    window_s: float,
) -> dict[str, str]:
    """Decide which frames OPEN a keyframe, grouping micro-transitions.

    ``ordered`` is a time-sorted list of ``(frame_id, signature, time)``.  Returns
    a mapping ``frame_id -> REASON_SCENE_CHANGE`` for every frame that opens a
    keyframe by a genuine, track-agnostic state change (forced OCR/user/safety
    frames are handled by the caller and are NOT included here).

    Grouping (Codex I4.2):
    * a signature differing from the last CONFIRMED signature is a *candidate*
      change; it opens a keyframe only once it is confirmed;
    * a candidate that reverts to the previous confirmed signature within
      ``window_s`` (a brief A->B->A flip) is a flicker and is dropped - no
      keyframe, the frames stay covered by the A representative;
    * a burst of several distinct signatures inside ``window_s`` collapses to the
      LAST one in the burst (successive neighbouring transitions = one event);
    * ``window_s <= 0`` disables grouping: every distinct signature opens.

    A frame in ``forced_frames`` (OCR / explicit request) anchors the running
    confirmed signature so a forced keyframe is never immediately re-opened as a
    redundant scene change.
    """
    opens: dict[str, str] = {}
    confirmed_sig: tuple[Any, ...] | None = None
    # A pending burst: the first differing frame and its running "best" (latest)
    # candidate frame/sig, plus the burst start time.
    pending_fid: str | None = None
    pending_sig: tuple[Any, ...] | None = None
    pending_start: float | None = None

    def _commit_pending() -> None:
        nonlocal confirmed_sig, pending_fid, pending_sig, pending_start
        if pending_fid is not None and pending_sig is not None:
            # A real, confirmed change: the last frame of the burst opens.
            if pending_sig != confirmed_sig:
                opens[pending_fid] = REASON_SCENE_CHANGE
                confirmed_sig = pending_sig
        pending_fid = pending_sig = pending_start = None

    for fid, sig, t in ordered:
        if confirmed_sig is None and pending_fid is None:
            # First frame: opens coverage as the initial confirmed state.
            opens[fid] = REASON_SCENE_CHANGE
            confirmed_sig = sig
            continue
        if fid in forced_frames:
            # A forced keyframe resets the running state to whatever it shows, so
            # the very next identical frame is not re-opened.
            _commit_pending()
            confirmed_sig = sig
            continue
        if sig == confirmed_sig:
            # Back to (or still) the confirmed state: any pending flip was a
            # flicker -> drop it.
            pending_fid = pending_sig = pending_start = None
            continue
        # sig differs from the confirmed state.
        if window_s <= 0:
            opens[fid] = REASON_SCENE_CHANGE
            confirmed_sig = sig
            continue
        if pending_fid is None:
            pending_fid, pending_sig, pending_start = fid, sig, t
            continue
        # A burst is in progress. If we are still inside the window, keep the
        # latest differing signature as the burst's representative.
        within = (
            pending_start is not None and t is not None and (t - pending_start) <= window_s
        )
        if within:
            pending_fid, pending_sig = fid, sig
        else:
            # The previous burst has settled on a stable new state -> commit it,
            # then start a fresh pending burst for the current frame.
            _commit_pending()
            if sig == confirmed_sig:
                pending_fid = pending_sig = pending_start = None
            else:
                pending_fid, pending_sig, pending_start = fid, sig, t
    _commit_pending()
    return opens


def select_keyframes_with_coverage(
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    requested_frame_ids: Iterable[str] = (),
    safety_interval_s: float | None = None,
    micro_transition_window_s: float | None = None,
    frame_positions: Mapping[str, list[dict[str, Any]]] | None = None,
) -> SelectionResult:
    """Select coverage-complete keyframes for one event bundle.

    ``candidates`` are the deduplicated raw-pixel candidates the base module
    already builds (``_keyframe_candidates``): one dict per usable frame with at
    least ``frame_id``/``image_path``/``frame_time``. Change detection uses a
    TRACK-AGNOSTIC semantic signature (Codex I4.2): a bare ``track_id`` change
    never opens a keyframe, and neighbouring micro-transitions (A->B->A flips, or
    bursts inside ``micro_transition_window_s``) are grouped into a single event.
    A genuine change of labels/people/OCR/location/scene (or a major spatial
    displacement when positions exist) still opens a keyframe. The lossless
    ``reduce_vision_timeline`` atoms are still computed for provenance so every
    covered frame links to a stable representative.

    Returns a :class:`SelectionResult` where every candidate frame is either a
    keyframe or mapped to the keyframe/atom that represents it - zero orphans.
    """
    bundle_id = bundle.get("bundle_id")
    live_session_id = bundle.get("live_session_id")
    requested = {str(f) for f in requested_frame_ids if str(f).strip()}
    interval = safety_interval_s if safety_interval_s is not None else safety_interval_seconds()
    window_s = (
        micro_transition_window_s
        if micro_transition_window_s is not None
        else micro_transition_window_seconds()
    )

    # --- 1. change atoms from the semantic vision timeline (lossless) ---------
    timeline = bundle.get("vision_timeline_json")
    if isinstance(timeline, str):
        import json

        try:
            timeline = json.loads(timeline)
        except (TypeError, ValueError):
            timeline = []
    timeline_items = [it for it in (timeline or []) if isinstance(it, Mapping)]
    atoms = reduce_vision_timeline(timeline_items) if timeline_items else []
    frame_to_atom = _atom_index_for_semantic_frame(atoms)
    # First frame of each atom = the atom's representative keyframe.
    atom_first_frame: dict[str, str] = {}
    for atom in atoms:
        if atom.frame_refs:
            atom_first_frame[atom.atom_id] = str(atom.frame_refs[0])

    # Per-frame OCR / user-request signals AND the track-agnostic signature, read
    # from the timeline items so the signal survives even for frames without a
    # readable image path.
    ocr_frames: set[str] = set()
    user_frames: set[str] = set()
    frame_signatures: dict[str, tuple[Any, ...]] = {}
    # E64-I4.3: enrich each item with VisionRT positions (already-recorded live
    # bbox) so a constant-label displacement contributes a spatial signature and
    # opens a keyframe. When no position exists, the item is unchanged and the
    # signature stays label-set-only (documented safe fallback).
    positions = frame_positions or {}
    for it in timeline_items:
        fid = str(it.get("frame_id") or "").strip()
        if not fid:
            continue
        enriched = _inject_positions(it, positions) if positions else it
        frame_signatures[fid] = frame_signature(enriched)
        if _visible_text_of(it):
            ocr_frames.add(fid)
        if _is_user_requested(it, requested):
            user_frames.add(fid)

    # --- 2. order candidates by time then id (deterministic) ------------------
    def _sort_key(c: Mapping[str, Any]) -> tuple[float, str]:
        t = _parse_time(c.get("frame_time"))
        return (t if t is not None else float("inf"), str(c.get("frame_id") or c.get("image_path") or ""))

    ordered = sorted(candidates, key=_sort_key)

    # --- 3. plan the grouped scene-change keyframe openings -------------------
    # A candidate's signature falls back to the atom identity when the timeline
    # carried no per-frame observation (raw camera-only frames), so those still
    # get one anchor instead of one keyframe per frame.
    def _sig_for(fid: str) -> tuple[Any, ...]:
        sig = frame_signatures.get(fid)
        if sig is not None:
            return sig
        atom = frame_to_atom.get(fid)
        return ("__atom__", atom.atom_id if atom else None)

    ordered_sig_seq = [
        (
            str(c.get("frame_id") or c.get("image_path") or "").strip(),
            _sig_for(str(c.get("frame_id") or c.get("image_path") or "").strip()),
            _parse_time(c.get("frame_time")),
        )
        for c in ordered
        if str(c.get("frame_id") or c.get("image_path") or "").strip()
    ]
    scene_change_opens = _plan_keyframe_events(
        ordered_sig_seq,
        forced_frames=ocr_frames | user_frames,
        window_s=window_s,
    )

    reasons_by_frame: dict[str, list[str]] = {}
    selected_frame_ids: list[str] = []
    coverage: list[FrameCoverage] = []

    # Representative keyframe currently standing in for the running state.
    current_keyframe_id: str | None = None
    current_atom_id: str | None = None
    last_keyframe_time: float | None = None

    def _add_reason(fid: str, reason: str) -> None:
        reasons_by_frame.setdefault(fid, [])
        if reason not in reasons_by_frame[fid]:
            reasons_by_frame[fid].append(reason)

    for c in ordered:
        fid = str(c.get("frame_id") or c.get("image_path") or "").strip()
        if not fid:
            continue
        atom = frame_to_atom.get(fid)
        atom_id = atom.atom_id if atom else None
        ctime = _parse_time(c.get("frame_time"))

        reasons: list[str] = []
        # (a) track-agnostic scene/object/person change (grouped): this frame was
        # planned to open a keyframe by the micro-transition-aware planner.
        if fid in scene_change_opens:
            reasons.append(REASON_SCENE_CHANGE)
        # (b) OCR.
        if fid in ocr_frames:
            reasons.append(REASON_OCR)
        # (c) explicit user request.
        if fid in user_frames:
            reasons.append(REASON_USER_REQUEST)
        # (d) safety interval: nothing selected for `interval` seconds.
        if (
            not reasons
            and last_keyframe_time is not None
            and ctime is not None
            and (ctime - last_keyframe_time) >= interval
        ):
            reasons.append(REASON_SAFETY_INTERVAL)
        # The very first usable frame is always a keyframe (opens coverage).
        if current_keyframe_id is None and not reasons:
            reasons.append(REASON_SCENE_CHANGE if atom_id is not None else REASON_SAFETY_INTERVAL)

        if reasons:
            selected_frame_ids.append(fid)
            for r in reasons:
                _add_reason(fid, r)
            current_keyframe_id = fid
            current_atom_id = atom_id
            if ctime is not None:
                last_keyframe_time = ctime
            coverage.append(
                FrameCoverage(
                    frame_id=fid,
                    is_keyframe=True,
                    covered_by_keyframe_id=None,
                    covered_by_atom_id=atom_id,
                    reason=_dominant_reason(reasons),
                    live_session_id=live_session_id,
                )
            )
        else:
            # Represented by the current keyframe. Prefer the atom's own first
            # frame as the representative when available (stable across reruns),
            # but ONLY if that atom-first frame was actually selected - micro-
            # transition grouping can suppress an atom's opening frame, and a
            # represented frame must never point to a non-selected keyframe.
            rep_keyframe = current_keyframe_id
            rep_atom = atom_id if atom_id is not None else current_atom_id
            if (
                rep_atom is not None
                and rep_atom in atom_first_frame
                and atom_first_frame[rep_atom] in selected_frame_ids
            ):
                rep_keyframe = atom_first_frame[rep_atom]
            coverage.append(
                FrameCoverage(
                    frame_id=fid,
                    is_keyframe=False,
                    covered_by_keyframe_id=rep_keyframe,
                    covered_by_atom_id=rep_atom,
                    reason=COVER_REPRESENTED_BY_KEYFRAME,
                    live_session_id=live_session_id,
                )
            )

    return SelectionResult(
        bundle_id=bundle_id,
        selected_frame_ids=tuple(dict.fromkeys(selected_frame_ids)),
        coverage=tuple(coverage),
        atoms=tuple(atoms),
        reasons_by_frame={k: tuple(v) for k, v in reasons_by_frame.items()},
    )


def apply_max_keyframes_ceiling(result: SelectionResult, cap: int) -> SelectionResult:
    """Enforce a pathological hard ceiling WITHOUT dropping any frame.

    Overflow keyframes (beyond ``cap``, kept in deterministic order) are demoted
    to ``represented_by`` the previous KEPT keyframe. Coverage stays 100% - this
    is never a silent ``rows[:N]`` truncation; every demoted keyframe still points
    to a representative. A non-positive ``cap`` or a result already within the cap
    is returned unchanged.
    """
    if cap <= 0 or result.selected_count <= cap:
        return result

    kept: list[str] = list(result.selected_frame_ids[:cap])
    kept_set = set(kept)
    last_kept = kept[-1] if kept else None

    new_coverage: list[FrameCoverage] = []
    new_reasons = {k: v for k, v in result.reasons_by_frame.items()}
    for cov in result.coverage:
        if cov.is_keyframe and cov.frame_id not in kept_set:
            # Demote: represented by the last kept keyframe, keep its atom link.
            new_coverage.append(
                FrameCoverage(
                    frame_id=cov.frame_id,
                    is_keyframe=False,
                    covered_by_keyframe_id=last_kept,
                    covered_by_atom_id=cov.covered_by_atom_id,
                    reason=COVER_REPRESENTED_BY_KEYFRAME,
                    live_session_id=cov.live_session_id,
                )
            )
            new_reasons.pop(cov.frame_id, None)
        else:
            new_coverage.append(cov)

    return SelectionResult(
        bundle_id=result.bundle_id,
        selected_frame_ids=tuple(kept),
        coverage=tuple(new_coverage),
        atoms=result.atoms,
        reasons_by_frame=new_reasons,
    )


def _dominant_reason(reasons: Sequence[str]) -> str:
    for reason in _REASON_PRIORITY:
        if reason in reasons:
            return reason
    return reasons[0] if reasons else REASON_SAFETY_INTERVAL


def persist_frame_coverage(
    con: Any,
    *,
    person_id: str,
    package_date: str,
    result: SelectionResult,
) -> int:
    """Durably record every frame's coverage (keyframe or represented-by).

    Idempotent per (person, date, bundle, frame): a rerun upserts. Returns the
    number of coverage rows written. Raw frames/observations are never mutated -
    this table is purely additive provenance.
    """
    from ..utils import now_iso

    ensure_coverage_schema(con)
    written = 0
    for cov in result.coverage:
        con.execute(
            f"""INSERT OR REPLACE INTO {COVERAGE_TABLE}(
                  person_id, package_date, bundle_id, frame_id, live_session_id,
                  is_keyframe, covered_by_keyframe_id, covered_by_atom_id, reason, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                person_id,
                package_date,
                str(result.bundle_id or ""),
                cov.frame_id,
                cov.live_session_id,
                1 if cov.is_keyframe else 0,
                cov.covered_by_keyframe_id,
                cov.covered_by_atom_id,
                cov.reason,
                now_iso(),
            ),
        )
        written += 1
    return written


def coverage_manifest(result: SelectionResult) -> dict[str, Any]:
    """A selection manifest proving 100% of frames are selected or represented.

    Mirrors the shape of the night-orchestrator coverage report: an ``ok`` flag,
    the total/selected/represented counts, and the (must-be-empty) orphan list.
    """
    represented = [c for c in result.coverage if not c.is_keyframe]
    return {
        "bundle_id": result.bundle_id,
        "total_frames": result.total_frames,
        "selected_keyframes": result.selected_count,
        "represented_frames": len(represented),
        "orphan_frames": list(result.orphan_frame_ids),
        "ok": result.fully_covered,
    }
