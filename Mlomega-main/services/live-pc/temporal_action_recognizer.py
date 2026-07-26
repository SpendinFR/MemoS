from __future__ import annotations

"""Bounded temporal action candidates derived from the real VisionRT track stream.

This is deliberately not a frame classifier pretending to understand every
gesture.  It recognises only transitions for which the existing detector stream
provides temporal evidence (enter/exit, take/place and coarse sit/stand).  Every
result is persisted as ``probable`` with the contributing frame ids; downstream
code may promote it only after independent corroboration.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_action_candidates_v19(
  action_event_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  subject_track_id TEXT,
  subject_label TEXT,
  object_track_id TEXT,
  object_label TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  confidence REAL NOT NULL,
  truth_level TEXT NOT NULL,
  status TEXT NOT NULL,
  model TEXT NOT NULL,
  source_frame_ids_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_action_owner_time_v19
  ON live_action_candidates_v19(person_id,ended_at,action_type);
CREATE INDEX IF NOT EXISTS idx_live_action_session_v19
  ON live_action_candidates_v19(live_session_id,ended_at);
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bbox(raw: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _centre(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return (box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5


def _size(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def _intersection_over_object(
    obj: tuple[float, float, float, float],
    person: tuple[float, float, float, float],
) -> float:
    ix = max(0.0, min(obj[2], person[2]) - max(obj[0], person[0]))
    iy = max(0.0, min(obj[3], person[3]) - max(obj[1], person[1]))
    area = max(1.0, (obj[2] - obj[0]) * (obj[3] - obj[1]))
    return ix * iy / area


@dataclass
class _Track:
    track_id: str
    label: str
    kind: str
    first_at: float
    last_at: float
    first_iso: str
    last_iso: str
    first_box: tuple[float, float, float, float]
    box: tuple[float, float, float, float]
    frame_ids: list[str] = field(default_factory=list)
    seen: int = 1
    entered_emitted: bool = False
    exited_emitted: bool = False
    held_by: str | None = None
    released_from: str | None = None
    released_at: float | None = None
    moving: bool = False
    stable_samples: int = 0
    posture: str | None = None
    posture_candidate: str | None = None
    posture_samples: int = 0


class TemporalActionRecognizer:
    """Stateful, O(number-of-live-tracks) action recogniser."""

    def __init__(
        self,
        *,
        person_id: str,
        live_session_id: str,
        db_path: str | Path | None,
        min_sightings: int = 3,
        max_tracks: int = 128,
    ) -> None:
        self.person_id = str(person_id or "me")
        self.live_session_id = str(live_session_id or "live")
        self.db_path = Path(db_path or "storage/memory.db")
        self.min_sightings = max(2, int(min_sightings))
        self.max_tracks = max(16, int(max_tracks))
        self._tracks: dict[str, _Track] = {}
        self.metrics = {
            "scene_deltas": 0,
            "events": 0,
            "abstentions": 0,
            "tracks": 0,
        }
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=3.0)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    @staticmethod
    def _event_id(
        session_id: str,
        action_type: str,
        subject: str,
        obj: str | None,
        frame_id: str,
    ) -> str:
        raw = "\x1f".join(
            (session_id, action_type, subject, obj or "", frame_id)
        ).encode("utf-8")
        return "liveaction_" + hashlib.sha256(raw).hexdigest()[:24]

    def _emit(
        self,
        action_type: str,
        subject: _Track,
        *,
        frame_id: str,
        now_iso: str,
        confidence: float,
        object_track: _Track | None = None,
        detail: Mapping[str, Any] | None = None,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        frames = list(dict.fromkeys((subject.frame_ids + [frame_id])[-8:]))
        event = {
            "action_event_id": self._event_id(
                self.live_session_id,
                action_type,
                subject.track_id,
                object_track.track_id if object_track else None,
                frame_id,
            ),
            "person_id": self.person_id,
            "live_session_id": self.live_session_id,
            "action_type": action_type,
            "subject_track_id": subject.track_id,
            "subject_label": subject.label,
            "object_track_id": object_track.track_id if object_track else None,
            "object_label": object_track.label if object_track else None,
            "started_at": started_at or subject.first_iso,
            "ended_at": now_iso,
            "confidence": round(max(0.0, min(float(confidence), 0.89)), 3),
            "truth_level": "probable",
            "status": "candidate",
            "model": "visionrt-temporal-v1",
            "source_frame_ids": frames,
            "evidence_refs": [f"frame:{value}" for value in frames],
            "detail": dict(detail or {}),
        }
        with self._connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO live_action_candidates_v19(
                     action_event_id,person_id,live_session_id,action_type,
                     subject_track_id,subject_label,object_track_id,object_label,
                     started_at,ended_at,confidence,truth_level,status,model,
                     source_frame_ids_json,evidence_refs_json,detail_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["action_event_id"],
                    self.person_id,
                    self.live_session_id,
                    action_type,
                    event["subject_track_id"],
                    event["subject_label"],
                    event["object_track_id"],
                    event["object_label"],
                    event["started_at"],
                    event["ended_at"],
                    event["confidence"],
                    "probable",
                    "candidate",
                    event["model"],
                    json.dumps(frames, ensure_ascii=False),
                    json.dumps(event["evidence_refs"], ensure_ascii=False),
                    json.dumps(event["detail"], ensure_ascii=False, sort_keys=True),
                    now_iso,
                ),
            )
            inserted = int(con.execute("SELECT changes()").fetchone()[0])
        if inserted:
            self.metrics["events"] += 1
        return event

    def ingest(
        self,
        delta: Mapping[str, Any],
        *,
        monotonic_s: float,
        observed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.metrics["scene_deltas"] += 1
        now_dt = observed_at or _utc_now()
        now_iso = now_dt.isoformat()
        frame_id = str(delta.get("source_frame_id") or "unknown")
        width = max(1.0, float(delta.get("frame_width") or 1.0))
        height = max(1.0, float(delta.get("frame_height") or 1.0))
        entities: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
        for raw in list(delta.get("entities") or [])[: self.max_tracks]:
            if not isinstance(raw, dict):
                continue
            box = _bbox(raw.get("bbox"))
            track_id = str(raw.get("track_id") or "")
            if box is None or not track_id:
                continue
            entities.append((raw, box))

        people = [
            (str(raw.get("track_id")), box)
            for raw, box in entities
            if str(raw.get("label") or "").casefold() == "person"
            or str(raw.get("kind") or "").casefold() == "person"
        ]
        current: set[str] = set()
        events: list[dict[str, Any]] = []

        for raw, box in entities:
            track_id = str(raw.get("track_id"))
            current.add(track_id)
            label = str(raw.get("label") or raw.get("kind") or "object")
            kind = str(raw.get("kind") or "object")
            state = self._tracks.get(track_id)
            if state is None:
                state = _Track(
                    track_id,
                    label,
                    kind,
                    monotonic_s,
                    monotonic_s,
                    now_iso,
                    now_iso,
                    box,
                    box,
                    [frame_id],
                )
                self._tracks[track_id] = state
                continue

            elapsed = max(1e-3, monotonic_s - state.last_at)
            prior_box = state.box
            prior_centre = _centre(prior_box)
            centre = _centre(box)
            displacement = (
                ((centre[0] - prior_centre[0]) / width) ** 2
                + ((centre[1] - prior_centre[1]) / height) ** 2
            ) ** 0.5
            state.moving = displacement / elapsed >= 0.035
            state.stable_samples = 0 if state.moving else state.stable_samples + 1
            state.last_at = monotonic_s
            state.last_iso = now_iso
            state.box = box
            state.label = label
            state.kind = kind
            state.seen += 1
            state.frame_ids = (state.frame_ids + [frame_id])[-8:]

            is_person = label.casefold() == "person" or kind.casefold() == "person"
            if (
                is_person
                and not state.entered_emitted
                and state.seen >= self.min_sightings
            ):
                state.entered_emitted = True
                events.append(
                    self._emit(
                        "enter_scene",
                        state,
                        frame_id=frame_id,
                        now_iso=now_iso,
                        confidence=float(raw.get("confidence") or 0.5) * 0.9,
                        detail={"sightings": state.seen},
                    )
                )

            if is_person:
                box_w, box_h = _size(box)
                ratio = box_h / max(1.0, box_w)
                posture = "standing" if ratio >= 1.75 else "sitting" if ratio <= 1.25 else None
                if posture and posture != state.posture:
                    if posture == state.posture_candidate:
                        state.posture_samples += 1
                    else:
                        state.posture_candidate = posture
                        state.posture_samples = 1
                    if state.posture_samples >= 3:
                        previous = state.posture
                        state.posture = posture
                        state.posture_candidate = None
                        state.posture_samples = 0
                        if previous is not None:
                            events.append(
                                self._emit(
                                    "stand_up" if posture == "standing" else "sit_down",
                                    state,
                                    frame_id=frame_id,
                                    now_iso=now_iso,
                                    confidence=0.58,
                                    started_at=state.last_iso,
                                    detail={
                                        "previous_posture": previous,
                                        "posture": posture,
                                        "bbox_aspect_ratio": round(ratio, 3),
                                    },
                                )
                            )
                continue

            holder_id = next(
                (
                    person_id
                    for person_id, person_box in people
                    if _intersection_over_object(box, person_box) >= 0.55
                ),
                None,
            )
            if holder_id and state.held_by != holder_id and state.seen >= self.min_sightings:
                holder = self._tracks.get(holder_id)
                if holder is not None and displacement >= 0.02:
                    state.held_by = holder_id
                    state.released_from = None
                    state.released_at = None
                    events.append(
                        self._emit(
                            "take_object",
                            holder,
                            object_track=state,
                            frame_id=frame_id,
                            now_iso=now_iso,
                            confidence=min(
                                float(raw.get("confidence") or 0.5), 0.78
                            ),
                            started_at=now_iso,
                            detail={
                                "overlap_ratio": round(
                                    _intersection_over_object(box, dict(people)[holder_id]), 3
                                )
                            },
                        )
                    )
            elif not holder_id and state.held_by:
                state.released_from = state.held_by
                state.released_at = monotonic_s
                state.held_by = None
                state.stable_samples = 0
            elif (
                not holder_id
                and state.released_from
                and state.released_at is not None
                and state.stable_samples >= 2
                and monotonic_s - state.released_at <= 4.0
            ):
                holder = self._tracks.get(state.released_from)
                if holder is not None:
                    events.append(
                        self._emit(
                            "place_object",
                            holder,
                            object_track=state,
                            frame_id=frame_id,
                            now_iso=now_iso,
                            confidence=min(
                                float(raw.get("confidence") or 0.5), 0.76
                            ),
                            started_at=state.last_iso,
                            detail={"stable_samples": state.stable_samples},
                        )
                    )
                state.released_from = None
                state.released_at = None

        for track_id, state in list(self._tracks.items()):
            if track_id in current or state.exited_emitted:
                if (
                    track_id not in current
                    and monotonic_s - state.last_at > 15.0
                ):
                    del self._tracks[track_id]
                continue
            is_person = (
                state.label.casefold() == "person"
                or state.kind.casefold() == "person"
            )
            if is_person and state.seen >= self.min_sightings:
                state.exited_emitted = True
                events.append(
                    self._emit(
                        "exit_scene",
                        state,
                        frame_id=frame_id,
                        now_iso=now_iso,
                        confidence=0.62,
                        detail={"last_seen_at": state.last_iso, "sightings": state.seen},
                    )
                )
            elif monotonic_s - state.last_at > 8.0:
                self.metrics["abstentions"] += 1
                del self._tracks[track_id]

        self.metrics["tracks"] = len(self._tracks)
        return events
