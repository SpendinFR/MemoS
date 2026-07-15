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


def ensure_coverage_schema(con: Any) -> None:
    con.executescript(_COVERAGE_SCHEMA)


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


def select_keyframes_with_coverage(
    bundle: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    requested_frame_ids: Iterable[str] = (),
    safety_interval_s: float | None = None,
) -> SelectionResult:
    """Select coverage-complete keyframes for one event bundle.

    ``candidates`` are the deduplicated raw-pixel candidates the base module
    already builds (``_keyframe_candidates``): one dict per usable frame with at
    least ``frame_id``/``image_path``/``frame_time``. The vision *timeline* of the
    bundle (semantic observations) drives change detection via the tested
    ``reduce_vision_timeline`` reducer, so a change of scene/object/person opens a
    new atom while pure confidence jitter never does.

    Returns a :class:`SelectionResult` where every candidate frame is either a
    keyframe or mapped to the keyframe/atom that represents it - zero orphans.
    """
    bundle_id = bundle.get("bundle_id")
    live_session_id = bundle.get("live_session_id")
    requested = {str(f) for f in requested_frame_ids if str(f).strip()}
    interval = safety_interval_s if safety_interval_s is not None else safety_interval_seconds()

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

    # Per-frame OCR / user-request signals, read from the timeline items so the
    # signal survives even for frames without a readable image path.
    ocr_frames: set[str] = set()
    user_frames: set[str] = set()
    for it in timeline_items:
        fid = str(it.get("frame_id") or "").strip()
        if not fid:
            continue
        if _visible_text_of(it):
            ocr_frames.add(fid)
        if _is_user_requested(it, requested):
            user_frames.add(fid)

    # --- 2. order candidates by time then id (deterministic) ------------------
    def _sort_key(c: Mapping[str, Any]) -> tuple[float, str]:
        t = _parse_time(c.get("frame_time"))
        return (t if t is not None else float("inf"), str(c.get("frame_id") or c.get("image_path") or ""))

    ordered = sorted(candidates, key=_sort_key)

    reasons_by_frame: dict[str, list[str]] = {}
    selected_frame_ids: list[str] = []
    coverage: list[FrameCoverage] = []

    # Representative keyframe currently standing in for the running state. When an
    # atom changes, the first frame of the new atom becomes the representative.
    current_keyframe_id: str | None = None
    current_atom_id: str | None = None
    last_keyframe_time: float | None = None
    seen_atoms: set[str] = set()

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
        # (a) scene/object/person change: this frame belongs to an atom we have
        # not opened yet.
        if atom_id is not None and atom_id not in seen_atoms:
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
            if atom_id is not None:
                seen_atoms.add(atom_id)
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
            # frame as the representative when available (stable across reruns).
            rep_keyframe = current_keyframe_id
            rep_atom = atom_id if atom_id is not None else current_atom_id
            if rep_atom is not None and rep_atom in atom_first_frame:
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
