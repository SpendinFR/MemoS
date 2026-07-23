from __future__ import annotations

"""WorldBrain — the spatial/relational *present* (guide §10.2).

WorldBrain consumes the :class:`SceneDelta` stream emitted by VisionRT (E27) and
maintains the live, relational picture of *what is here now*:

* :class:`WorldEntity` — a durable ``entity_id`` **promoted** from repeated,
  confirmed tracks. A single weak bbox never becomes an entity (§7.1): promotion
  requires ``promote_min_observations`` confirmed sightings above
  ``promote_min_confidence``.
* :class:`Observation` — one dated, correctable sighting (frame_id, track_id,
  state, model, confidence, evidence).
* :class:`Relation` — subject/predicate/object derived *geometrically* from the
  bboxes of the current frame (``on_top_of``, ``near``, ``holds``).
* :class:`SceneSession` — place_hint, active_zone, map_quality for a visit/task.
* :class:`ChangeEvent` — appeared/disappeared/moved with before/after evidence.

Persistence is layered and never invents a parallel schema for core tables
(piège #11):

* last-seen + changes → ``visual_events_v19`` via ``store_visual_event`` (with an
  explicit ``memory_owner_id``);
* end-of-session summaries → ``scene_session_summaries_v19``;
* the current world state → the REAL ``brainlive_world_states`` /
  ``vision_scene_observations`` via ``v19_visual_context.publish_visual_context``.

Only *session* bookkeeping lives in a light service-local SQLite file — never a
new table in the core.

WorldBrain does **not** produce a psychological profile or arbitrary UI output
(handoff §ne-fait-pas). It reports facts; BrainLive decides what to say.
"""

import importlib.util
import sqlite3
import sys
import threading
import time
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mlomega_audio_elite.spatial_bbox_v19 import BBoxValidation, sanitize_detector_bbox

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_store():
    """Import the core V19 store lazily (kept out of import cycles / tests)."""
    from mlomega_audio_elite import v19_visual_store as store  # type: ignore

    return store


def _load_visual_context():
    from mlomega_audio_elite import v19_visual_context as ctx  # type: ignore

    return ctx


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# --------------------------------------------------------------------------- data
@dataclass
class Observation:
    """One dated, correctable sighting of a track (§10.2)."""

    observation_id: str
    frame_id: str
    track_id: str
    kind: str
    label: str
    state: str  # "visible" | "last_seen" | ...
    model: str
    confidence: float
    bbox: tuple[float, float, float, float]
    observed_at: str
    evidence_refs: list[str] = field(default_factory=list)
    entity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "frame_id": self.frame_id,
            "track_id": self.track_id,
            "entity_id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "model": self.model,
            "confidence": round(float(self.confidence), 3),
            "bbox": [round(float(v), 1) for v in self.bbox],
            "observed_at": self.observed_at,
            "evidence": list(self.evidence_refs),
        }


@dataclass
class WorldEntity:
    """A durable entity promoted from repeated confirmed tracks."""

    entity_id: str
    kind: str
    label: str
    confidence: float
    lifecycle: str = "candidate"  # candidate → confirmed → last_seen → gone
    track_id: str | None = None
    first_seen: str = ""
    last_seen: str = ""
    last_bbox: tuple[float, float, float, float] | None = None
    observation_count: int = 0
    evidence_refs: list[str] = field(default_factory=list)
    truth_level: str = "observed"
    source: str = "visionrt"

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or _utc_now()
        try:
            last = datetime.fromisoformat(self.last_seen)
        except (ValueError, TypeError):
            return 0.0
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return max(0.0, (now - last).total_seconds())

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "confidence": round(float(self.confidence), 3),
            "lifecycle": self.lifecycle,
            "track_id": self.track_id,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_bbox": [round(float(v), 1) for v in self.last_bbox] if self.last_bbox else None,
            "observation_count": self.observation_count,
            "age_seconds": round(self.age_seconds(now), 1),
            "evidence": list(self.evidence_refs),
            "truth_level": self.truth_level,
            "source": self.source,
        }


@dataclass
class Relation:
    subject: str  # entity_id or track_id
    predicate: str  # on_top_of | near | holds
    object: str
    observed_at: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "observed_at": self.observed_at,
            "confidence": round(float(self.confidence), 3),
            "evidence": list(self.evidence_refs),
        }


@dataclass
class ChangeEvent:
    change_type: str  # appeared | disappeared | moved | attribute_changed
    entity_id: str
    label: str
    observed_at: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.change_type,
            "entity_id": self.entity_id,
            "label": self.label,
            "observed_at": self.observed_at,
            "before": self.before,
            "after": self.after,
            "evidence": list(self.evidence_refs),
        }


@dataclass
class SceneSession:
    session_id: str
    place_hint: str | None = None
    active_zone: str | None = None
    map_quality: float = 0.0
    started_at: str = ""
    keyframes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- config
@dataclass
class WorldBrainConfig:
    """Promotion / geometry / staleness thresholds (all config, never hardcoded)."""

    promote_min_observations: int = 3
    promote_min_confidence: float = 0.35
    near_iou_gap_ratio: float = 0.6      # centre distance / mean box size below → near
    on_top_overlap_ratio: float = 0.15   # horizontal overlap fraction for on_top_of
    holds_person_overlap_ratio: float = 0.10
    moved_center_ratio: float = 0.25     # centre shift / box diag above → moved
    stale_after_seconds: float = 20.0    # entity marked last_seen when unseen this long


# --------------------------------------------------------------------------- geometry
def _center(box: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _size(box: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (abs(x2 - x1), abs(y2 - y1))


def _diag(box: Sequence[float]) -> float:
    w, h = _size(box)
    return (w * w + h * h) ** 0.5


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _horizontal_overlap_frac(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, _, ax2, _ = a
    bx1, _, bx2, _ = b
    ov = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    wa = max(1e-6, ax2 - ax1)
    return ov / wa


# --------------------------------------------------------------------------- WorldBrain
class WorldBrain:
    """Maintains the live entity/relation/change picture from SceneDeltas."""

    def __init__(
        self,
        *,
        person_id: str,
        live_session_id: str,
        config: WorldBrainConfig | None = None,
        db_path: Any = None,
        service_db_path: str | Path | None = None,
        spatial: Any = None,
        publish_world_state: bool = True,
    ) -> None:
        self.person_id = person_id
        self.live_session_id = live_session_id
        self.config = config or WorldBrainConfig()
        self.db_path = db_path  # core memory DB (visual_events_v19, world_states)
        self.spatial = spatial
        self.publish_world_state = publish_world_state

        self.session = SceneSession(
            session_id=live_session_id, started_at=_iso(_utc_now())
        )
        self.entities: dict[str, WorldEntity] = {}          # entity_id → entity
        # E35 §3: labels/zones the user has verbally corrected away ("ce n'est pas
        # mon téléphone", "on n'est pas au bureau"). A suspended label is filtered
        # out of every subsequent snapshot/SceneDelta; a suspended zone is dropped
        # from ``active_zone``. Correction is durable within the session.
        self._suspended_labels: set[str] = set()            # normalised labels
        self._suspended_zones: set[str] = set()             # zone ids / place hints
        self._track_to_entity: dict[str, str] = {}          # track_id → entity_id
        self._track_counts: dict[str, int] = {}             # track_id → confirmed hits
        self._track_last: dict[str, dict[str, Any]] = {}    # track_id → last raw entry
        self.relations: list[Relation] = []
        self.change_events: list[ChangeEvent] = []
        self._obs_seq = 0

        # Light service-local SQLite for session persistence (never a core table).
        # The connection is created on the init thread but used from the vision
        # worker threads (ingest_scene_delta), so it MUST allow cross-thread use
        # (check_same_thread=False) and every access MUST be serialized by
        # ``self._db_lock`` — sqlite3 connections are not internally thread-safe.
        self._db_lock = threading.RLock()
        self._svc_db = self._init_service_db(service_db_path)
        self._init_entity_registry()

        self.metrics = {
            "scene_deltas": 0,
            "entities_promoted": 0,
            "last_seen_count": 0,
            "change_events": 0,
            "relations": 0,
            "world_state_published": 0,
            "bbox_normalized": 0,
            "bbox_rejected": 0,
        }

    # -------------------------------------------------------- service-local store
    def _init_service_db(self, path: str | Path | None) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(path) if path else ":memory:", check_same_thread=False
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS worldbrain_session_entities(
                 entity_id TEXT PRIMARY KEY, live_session_id TEXT, kind TEXT,
                 label TEXT, lifecycle TEXT, first_seen TEXT, last_seen TEXT,
                 observation_count INTEGER, confidence REAL, last_bbox TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS worldbrain_session_changes(
                 change_seq INTEGER PRIMARY KEY AUTOINCREMENT, live_session_id TEXT,
                 change_type TEXT, entity_id TEXT, label TEXT, observed_at TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS worldbrain_bbox_audit(
                 audit_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                 live_session_id TEXT NOT NULL, frame_id TEXT NOT NULL,
                 track_id TEXT, label TEXT, status TEXT NOT NULL,
                 raw_bbox_json TEXT, normalized_bbox_json TEXT,
                 reasons_json TEXT NOT NULL, frame_width INTEGER,
                 frame_height INTEGER, rotation INTEGER, mirrored INTEGER,
                 coordinate_space TEXT NOT NULL, created_at TEXT NOT NULL)"""
        )
        conn.commit()
        return conn

    def _record_bbox_audit(
        self,
        *,
        frame_id: str,
        track_id: str,
        label: str,
        checked: Any,
        rotation: int,
        mirrored: bool,
        created_at: str,
    ) -> None:
        with self._db_lock:
            self._svc_db.execute(
                """INSERT INTO worldbrain_bbox_audit(
                     live_session_id,frame_id,track_id,label,status,raw_bbox_json,
                     normalized_bbox_json,reasons_json,frame_width,frame_height,
                     rotation,mirrored,coordinate_space,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.live_session_id,
                    frame_id,
                    track_id,
                    label,
                    checked.status,
                    json.dumps(list(checked.raw) if checked.raw is not None else None),
                    json.dumps(list(checked.bbox) if checked.bbox is not None else None),
                    json.dumps(list(checked.reasons)),
                    checked.frame_width,
                    checked.frame_height,
                    rotation,
                    int(bool(mirrored)),
                    checked.coordinate_space,
                    created_at,
                ),
            )
            self._svc_db.commit()

    def _persist_entity(self, e: WorldEntity) -> None:
        import json as _json

        with self._db_lock:
            self._svc_db.execute(
                """INSERT INTO worldbrain_session_entities(
                     entity_id, live_session_id, kind, label, lifecycle, first_seen,
                     last_seen, observation_count, confidence, last_bbox)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                     lifecycle=excluded.lifecycle, last_seen=excluded.last_seen,
                     observation_count=excluded.observation_count,
                     confidence=excluded.confidence, last_bbox=excluded.last_bbox""",
                (
                    e.entity_id, self.live_session_id, e.kind, e.label, e.lifecycle,
                    e.first_seen, e.last_seen, e.observation_count, e.confidence,
                    _json.dumps(list(e.last_bbox) if e.last_bbox else None),
                ),
            )
            self._svc_db.commit()
        self._persist_registry_entity(e)

    def _init_entity_registry(self) -> None:
        """Install the owner-scoped registry used across PhoneOnly sessions."""
        from mlomega_audio_elite.db import connect, write_transaction  # type: ignore

        with connect(self.db_path) as con, write_transaction(con):
            con.execute(
                """CREATE TABLE IF NOT EXISTS worldbrain_entity_registry_v19(
                     entity_id TEXT PRIMARY KEY,
                     person_id TEXT NOT NULL,
                     kind TEXT NOT NULL,
                     normalized_label TEXT NOT NULL,
                     display_label TEXT NOT NULL,
                     entity_slot INTEGER NOT NULL,
                     first_seen TEXT NOT NULL,
                     last_seen TEXT NOT NULL,
                     last_session_id TEXT NOT NULL,
                     last_track_id TEXT,
                     last_bbox_json TEXT,
                     observation_count INTEGER NOT NULL DEFAULT 0,
                     confidence REAL NOT NULL DEFAULT 0.0,
                     UNIQUE(person_id,kind,normalized_label,entity_slot))"""
            )
            con.execute(
                """CREATE INDEX IF NOT EXISTS idx_worldbrain_registry_owner_label
                   ON worldbrain_entity_registry_v19(
                      person_id,kind,normalized_label,last_seen)"""
            )
            columns = {
                str(row["name"])
                for row in con.execute(
                    "PRAGMA table_info(worldbrain_entity_registry_v19)"
                ).fetchall()
            }
            for name, ddl in (
                ("truth_level", "TEXT NOT NULL DEFAULT 'observed'"),
                ("source", "TEXT NOT NULL DEFAULT 'visionrt'"),
                ("evidence_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if name not in columns:
                    con.execute(
                        f"ALTER TABLE worldbrain_entity_registry_v19 "
                        f"ADD COLUMN {name} {ddl}"
                    )

    @staticmethod
    def _identity_label(label: str) -> str:
        return " ".join(str(label or "object").strip().lower().split()) or "object"

    def _claim_entity_id(self, obs: Observation) -> str:
        """Reuse a durable slot while keeping raw tracker ids session-scoped.

        A lone prior object with the same detector class is reused.  With several
        homonymous objects, bbox overlap/centre proximity chooses among slots not
        already claimed in this session, so simultaneous tracks stay distinct.
        This is a continuity heuristic, not biometric object re-identification.
        """
        from mlomega_audio_elite.db import connect  # type: ignore
        from mlomega_audio_elite.utils import stable_id  # type: ignore

        normalized = self._identity_label(obs.label)
        with connect(self.db_path) as con:
            rows = [dict(row) for row in con.execute(
                """SELECT * FROM worldbrain_entity_registry_v19
                   WHERE person_id=? AND kind=? AND normalized_label=?
                   ORDER BY last_seen DESC,entity_slot ASC""",
                (self.person_id, obs.kind, normalized),
            ).fetchall()]
        claimed = set(self.entities)
        available = [row for row in rows if str(row["entity_id"]) not in claimed]
        if available:
            import json as _json

            def score(row: dict[str, Any]) -> tuple[float, float]:
                try:
                    prior = tuple(float(v) for v in (_json.loads(row.get("last_bbox_json") or "null") or ()))
                    if len(prior) != 4:
                        raise ValueError("missing bbox")
                    overlap = _iou(prior, obs.bbox)
                    pa, pb = _center(prior), _center(obs.bbox)
                    distance = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5
                    return overlap, -distance
                except Exception:
                    return 0.0, float("-inf")

            chosen = available[0] if len(available) == 1 else max(available, key=score)
            return str(chosen["entity_id"])

        next_slot = 1 + max((int(row.get("entity_slot") or 0) for row in rows), default=0)
        return stable_id("worldentity", self.person_id, obs.kind, normalized, next_slot)

    def _persist_registry_entity(self, e: WorldEntity) -> None:
        import json as _json
        from mlomega_audio_elite.db import connect, write_transaction  # type: ignore

        normalized = self._identity_label(e.label)
        with connect(self.db_path) as con, write_transaction(con):
            existing = con.execute(
                "SELECT entity_slot,first_seen FROM worldbrain_entity_registry_v19 WHERE entity_id=?",
                (e.entity_id,),
            ).fetchone()
            if existing is None:
                slot_row = con.execute(
                    """SELECT COALESCE(MAX(entity_slot),0)+1 AS next_slot
                       FROM worldbrain_entity_registry_v19
                       WHERE person_id=? AND kind=? AND normalized_label=?""",
                    (self.person_id, e.kind, normalized),
                ).fetchone()
                slot = int(slot_row["next_slot"] if slot_row else 1)
                first_seen = e.first_seen
            else:
                slot = int(existing["entity_slot"])
                first_seen = str(existing["first_seen"])
            con.execute(
                """INSERT INTO worldbrain_entity_registry_v19(
                      entity_id,person_id,kind,normalized_label,display_label,
                      entity_slot,first_seen,last_seen,last_session_id,last_track_id,
                      last_bbox_json,observation_count,confidence,truth_level,source,
                      evidence_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                      display_label=excluded.display_label,
                      last_seen=excluded.last_seen,
                      last_session_id=excluded.last_session_id,
                      last_track_id=excluded.last_track_id,
                      last_bbox_json=excluded.last_bbox_json,
                      observation_count=worldbrain_entity_registry_v19.observation_count+1,
                      confidence=MAX(worldbrain_entity_registry_v19.confidence,excluded.confidence),
                      truth_level=excluded.truth_level,
                      source=excluded.source,
                      evidence_json=excluded.evidence_json""",
                (
                    e.entity_id, self.person_id, e.kind, normalized, e.label, slot,
                    first_seen, e.last_seen, self.live_session_id, e.track_id,
                    _json.dumps(list(e.last_bbox) if e.last_bbox else None),
                    max(1, int(e.observation_count)), float(e.confidence),
                    e.truth_level, e.source, _json.dumps(list(e.evidence_refs)),
                ),
            )

    def record_semantic_sighting(
        self,
        *,
        label: str,
        bbox: Sequence[float],
        frame_width: int,
        frame_height: int,
        frame_id: str,
        observed_at: str | None = None,
        confidence: float = 0.55,
        evidence_refs: Sequence[str] | None = None,
        source: str = "targeted_vlm",
        truth_level: str = "probable",
    ) -> dict[str, Any]:
        """Persist one user-triggered open-vocabulary sighting.

        This is deliberately separate from detector promotion: a targeted VLM hit
        is current and useful, but remains ``probable`` rather than masquerading as
        a repeated detector observation. Geometry must already be tied to the real
        source frame and is validated again here.
        """
        checked = sanitize_detector_bbox(
            bbox,
            frame_width=frame_width,
            frame_height=frame_height,
            require_dimensions=True,
        )
        if not checked.usable or checked.bbox is None:
            raise ValueError("semantic_sighting_bbox_invalid")
        clean_label = str(label or "").strip()
        if not clean_label:
            raise ValueError("semantic_sighting_label_missing")

        now_iso = str(observed_at or _iso(_utc_now()))
        evidence = [
            str(ref) for ref in (evidence_refs or [f"frame:{frame_id}"]) if str(ref)
        ]
        track_id = f"semantic:{self._identity_label(clean_label)}"
        observation = Observation(
            observation_id=self._next_obs_id(),
            frame_id=str(frame_id or "unknown"),
            track_id=track_id,
            kind="object",
            label=clean_label,
            state="visible",
            model=source,
            confidence=float(confidence),
            bbox=checked.bbox,
            observed_at=now_iso,
            evidence_refs=evidence,
        )
        entity_id = self._track_to_entity.get(track_id) or self._claim_entity_id(
            observation
        )
        entity = self.entities.get(entity_id)
        if entity is None:
            entity = WorldEntity(
                entity_id=entity_id,
                kind="object",
                label=clean_label,
                confidence=float(confidence),
                lifecycle="confirmed",
                track_id=track_id,
                first_seen=now_iso,
                last_seen=now_iso,
                last_bbox=checked.bbox,
                observation_count=1,
                evidence_refs=evidence,
                truth_level=truth_level,
                source=source,
            )
            self.entities[entity_id] = entity
            self._track_to_entity[track_id] = entity_id
            self.metrics["entities_promoted"] += 1
        else:
            entity.label = clean_label
            entity.last_seen = now_iso
            entity.last_bbox = checked.bbox
            entity.observation_count += 1
            entity.confidence = max(entity.confidence, float(confidence))
            entity.lifecycle = "confirmed"
            entity.truth_level = truth_level
            entity.source = source
            for ref in evidence:
                if ref not in entity.evidence_refs:
                    entity.evidence_refs.append(ref)
        self._persist_entity(entity)

        _load_store().store_visual_event(
            {
                "memory_owner_id": self.person_id,
                "live_session_id": self.live_session_id,
                "event_type": "entity_last_seen",
                "occurred_at": now_iso,
                "entity": {
                    "entity_id": entity.entity_id,
                    "kind": entity.kind,
                    "label": entity.label,
                    "lifecycle": entity.lifecycle,
                },
                "observation": {
                    "bbox": list(entity.last_bbox or ()),
                    "frame_width": int(frame_width),
                    "frame_height": int(frame_height),
                    "observation_count": entity.observation_count,
                },
                "truth_level": truth_level,
                "confidence": float(confidence),
                "evidence": evidence,
                "provenance": {"producer": source},
            },
            db_path=self.db_path,
        )
        result = entity.to_dict()
        result.update(
            {
                "visible": True,
                "place_hint": self.session.place_hint,
                "last_session_id": self.live_session_id,
            }
        )
        return result

    # --------------------------------------------------------------- ingest
    def _next_obs_id(self) -> str:
        self._obs_seq += 1
        return f"obs-{self.live_session_id}-{self._obs_seq}"

    def ingest_scene_delta(self, delta: Mapping[str, Any]) -> dict[str, Any]:
        """Consume one SceneDelta; return promoted/changed entities for this frame."""
        self.metrics["scene_deltas"] += 1
        now = _utc_now()
        now_iso = _iso(now)
        frame_id = str(delta.get("source_frame_id") or "unknown")
        evidence_ref = f"frame:{frame_id}"
        map_quality = float(delta.get("map_quality") or 0.0)
        frame_width = delta.get("frame_width")
        frame_height = delta.get("frame_height")
        rotation = int(delta.get("rotation") or 0)
        mirrored = bool(delta.get("mirrored"))
        coordinate_space = str(delta.get("coordinate_space") or "legacy_unbounded")
        require_dimensions = coordinate_space == "detector_pixels"

        # map quality: prefer the spatial provider's measured value when present.
        if self.spatial is not None:
            try:
                mq = self.spatial.map_quality()
                if mq is not None:
                    map_quality = float(mq)
            except Exception:
                pass
            try:
                active_zone = self.spatial.active_zone()
                normalized_zone = str(active_zone).strip() if active_zone else None
                if normalized_zone and self._norm_label(normalized_zone) in self._suspended_zones:
                    normalized_zone = None
                self.session.active_zone = normalized_zone
            except Exception:
                # Spatial quality and zone identity degrade independently. Keep
                # the last proven zone if a provider has a transient failure.
                pass
        self.session.map_quality = map_quality

        raw_entities = list(delta.get("entities") or [])
        seen_track_ids: set[str] = set()
        observations: list[Observation] = []
        promoted_now: list[WorldEntity] = []

        for ent in raw_entities:
            track_id = str(ent.get("track_id") or "")
            if not track_id:
                continue
            seen_track_ids.add(track_id)
            label = str(ent.get("label") or ent.get("kind") or "object")
            # E35 §3: a label the user corrected away never re-promotes or updates
            # an entity — the wrong label stays out of the world picture.
            if self.is_label_suspended(label):
                continue
            kind = str(ent.get("kind") or "object")
            conf = float(ent.get("confidence") or 0.0)
            checked = sanitize_detector_bbox(
                ent.get("bbox"),
                frame_width=frame_width,
                frame_height=frame_height,
                require_dimensions=require_dimensions,
            )
            upstream_audit = ent.get("bbox_audit")
            if isinstance(upstream_audit, Mapping):
                try:
                    upstream_raw = tuple(
                        float(value) for value in (upstream_audit.get("bbox_raw") or ())
                    )
                    if len(upstream_raw) != 4:
                        upstream_raw = checked.raw or ()
                except (TypeError, ValueError):
                    upstream_raw = checked.raw or ()
                audit_checked = BBoxValidation(
                    checked.bbox,
                    upstream_raw if len(upstream_raw) == 4 else checked.raw,
                    str(upstream_audit.get("bbox_status") or checked.status),
                    tuple(upstream_audit.get("bbox_reasons") or checked.reasons),
                    checked.frame_width,
                    checked.frame_height,
                    coordinate_space,
                )
            else:
                audit_checked = checked
            if audit_checked.status not in {"valid", "legacy_valid"}:
                self._record_bbox_audit(
                    frame_id=frame_id,
                    track_id=track_id,
                    label=label,
                    checked=audit_checked,
                    rotation=rotation,
                    mirrored=mirrored,
                    created_at=now_iso,
                )
            if checked.status == "normalized":
                self.metrics["bbox_normalized"] += 1
            if not checked.usable:
                self.metrics["bbox_rejected"] += 1
                self._track_last[track_id] = {
                    "label": label,
                    "kind": kind,
                    "confidence": conf,
                    "bbox": None,
                    "bbox_status": "rejected",
                    "observed_at": now_iso,
                    "frame_id": frame_id,
                }
                # The sourced label/detection still refreshes an already promoted
                # entity, but geometry is deliberately left untouched.
                entity_id = self._track_to_entity.get(track_id)
                if entity_id is not None:
                    e = self.entities[entity_id]
                    e.last_seen = now_iso
                    e.confidence = max(e.confidence, conf)
                    e.lifecycle = "confirmed"
                    if evidence_ref not in e.evidence_refs:
                        e.evidence_refs.append(evidence_ref)
                    self._persist_entity(e)
                continue
            bbox = checked.bbox
            assert bbox is not None

            obs = Observation(
                observation_id=self._next_obs_id(), frame_id=frame_id,
                track_id=track_id, kind=kind, label=label, state="visible",
                model="visionrt", confidence=conf, bbox=bbox,
                observed_at=now_iso, evidence_refs=[evidence_ref],
            )
            observations.append(obs)
            self._track_last[track_id] = {
                "label": label, "kind": kind, "confidence": conf,
                "bbox": bbox, "observed_at": now_iso, "frame_id": frame_id,
            }

            # Promotion: only confirmed tracks above the confidence floor count.
            if conf >= self.config.promote_min_confidence:
                self._track_counts[track_id] = self._track_counts.get(track_id, 0) + 1

            entity_id = self._track_to_entity.get(track_id)
            if entity_id is None and self._track_counts.get(track_id, 0) >= self.config.promote_min_observations:
                entity_id = self._promote(track_id, obs, now_iso, evidence_ref)
                promoted_now.append(self.entities[entity_id])

            if entity_id is not None:
                e = self.entities[entity_id]
                self._update_entity(e, obs, now_iso, evidence_ref)
                obs.entity_id = entity_id

        # Relations from the current frame geometry (only among visible tracks).
        frame_relations = self._derive_relations(observations, now_iso, evidence_ref)
        self.relations = frame_relations  # relations are frame-scoped
        self.metrics["relations"] = len(frame_relations)

        # Change detection: appeared / moved / disappeared (last-seen ageing).
        changes = self._detect_changes(seen_track_ids, now, now_iso, evidence_ref)

        # Persist last-seen + changes into visual_events_v19 (owner-scoped).
        self._persist_events(promoted_now, changes, now_iso)

        # Publish current world state into the REAL core tables.
        if self.publish_world_state:
            self._publish_world_state(observations, now_iso, map_quality)

        return {
            "frame_id": frame_id,
            "promoted": [e.entity_id for e in promoted_now],
            "changes": [c.to_dict() for c in changes],
            "relations": [r.to_dict() for r in frame_relations],
            "map_quality": map_quality,
        }

    def _promote(self, track_id: str, obs: Observation, now_iso: str, ev: str) -> str:
        entity_id = self._claim_entity_id(obs)
        e = WorldEntity(
            entity_id=entity_id, kind=obs.kind, label=obs.label,
            confidence=obs.confidence, lifecycle="confirmed", track_id=track_id,
            first_seen=now_iso, last_seen=now_iso, last_bbox=obs.bbox,
            observation_count=self._track_counts.get(track_id, 1),
            evidence_refs=[ev],
        )
        self.entities[entity_id] = e
        self._track_to_entity[track_id] = entity_id
        self.metrics["entities_promoted"] += 1
        self._persist_entity(e)
        return entity_id

    def _update_entity(self, e: WorldEntity, obs: Observation, now_iso: str, ev: str) -> None:
        e.last_seen = now_iso
        e.last_bbox = obs.bbox
        e.observation_count += 1
        e.confidence = max(e.confidence, obs.confidence)
        e.lifecycle = "confirmed"
        if ev not in e.evidence_refs:
            e.evidence_refs.append(ev)
        self._persist_entity(e)

    # ---------------------------------------------------------------- relations
    def _derive_relations(
        self, observations: list[Observation], now_iso: str, ev: str
    ) -> list[Relation]:
        rels: list[Relation] = []
        cfg = self.config
        n = len(observations)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                a, b = observations[i], observations[j]
                sid = a.entity_id or a.track_id
                oid = b.entity_id or b.track_id
                ca, cb = _center(a.bbox), _center(b.bbox)
                wa, ha = _size(a.bbox)
                mean_size = max(1e-6, (wa + ha) / 2.0)
                dist = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5

                # holds: a person whose bbox overlaps a small object it carries.
                if a.kind == "object" and a.label == "person" and b.kind == "object" and b.label != "person":
                    if _iou(a.bbox, b.bbox) > 0 and _horizontal_overlap_frac(b.bbox, a.bbox) >= cfg.holds_person_overlap_ratio:
                        rels.append(Relation(sid, "holds", oid, now_iso, min(a.confidence, b.confidence), [ev]))
                        continue

                # on_top_of: b's bottom near a's top, with horizontal overlap.
                if _horizontal_overlap_frac(a.bbox, b.bbox) >= cfg.on_top_overlap_ratio:
                    a_top, b_bottom = a.bbox[1], b.bbox[3]
                    if 0 <= (a_top - b_bottom) < mean_size * 0.5 or _iou(a.bbox, b.bbox) > cfg.on_top_overlap_ratio:
                        if ca[1] < cb[1]:  # a is higher on screen than b
                            rels.append(Relation(sid, "on_top_of", oid, now_iso, min(a.confidence, b.confidence), [ev]))
                            continue

                # near: centres close relative to box size (report once, i<j).
                if i < j and dist <= mean_size * (1.0 / max(1e-6, cfg.near_iou_gap_ratio)):
                    rels.append(Relation(sid, "near", oid, now_iso, min(a.confidence, b.confidence), [ev]))
        return rels

    # ---------------------------------------------------------------- changes
    def _detect_changes(
        self, seen_track_ids: set[str], now: datetime, now_iso: str, ev: str
    ) -> list[ChangeEvent]:
        changes: list[ChangeEvent] = []
        for entity_id, e in self.entities.items():
            tid = e.track_id
            if tid in seen_track_ids:
                # Was it moved? Compare against the stored bbox before this update.
                prev = getattr(e, "_prev_bbox_for_change", None)
                cur = e.last_bbox
                if prev is not None and cur is not None:
                    shift = ((_center(prev)[0] - _center(cur)[0]) ** 2 + (_center(prev)[1] - _center(cur)[1]) ** 2) ** 0.5
                    if shift > _diag(cur) * self.config.moved_center_ratio:
                        changes.append(ChangeEvent(
                            "moved", entity_id, e.label, now_iso,
                            before={"bbox": [round(v, 1) for v in prev]},
                            after={"bbox": [round(v, 1) for v in cur]},
                            evidence_refs=[ev],
                        ))
                        if e.lifecycle == "last_seen":
                            e.lifecycle = "confirmed"
                e._prev_bbox_for_change = cur  # type: ignore[attr-defined]
                if e.lifecycle == "last_seen":
                    changes.append(ChangeEvent("appeared", entity_id, e.label, now_iso, after={"bbox": [round(v, 1) for v in cur] if cur else None}, evidence_refs=[ev]))
                    e.lifecycle = "confirmed"
            else:
                if e.lifecycle == "confirmed" and e.age_seconds(now) >= self.config.stale_after_seconds:
                    e.lifecycle = "last_seen"
                    self.metrics["last_seen_count"] += 1
                    changes.append(ChangeEvent(
                        "disappeared", entity_id, e.label, e.last_seen,
                        before={"bbox": [round(v, 1) for v in e.last_bbox] if e.last_bbox else None},
                        evidence_refs=e.evidence_refs[-1:] or [ev],
                    ))
        self.change_events.extend(changes)
        self.metrics["change_events"] += len(changes)
        if changes:
            with self._db_lock:
                for c in changes:
                    self._svc_db.execute(
                        "INSERT INTO worldbrain_session_changes(live_session_id, change_type, entity_id, label, observed_at) VALUES(?,?,?,?,?)",
                        (self.live_session_id, c.change_type, c.entity_id, c.label, c.observed_at),
                    )
                self._svc_db.commit()
        return changes

    # ---------------------------------------------------------------- attribute change
    def record_attribute_change(
        self,
        *,
        subject: str,
        attribute: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        evidence_refs: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Record an ``attribute_changed`` ChangeEvent (E38 §2).

        A value observed for a (subject, attribute) differs from a prior session's
        value — a bi-modal change (a SEEN value can contradict a HEARD one and
        vice-versa; the ``source`` on each side records which). Appended to
        ``change_events``, persisted into ``visual_events_v19`` with a truth_level
        derived from the two sources, and returned for the scene adapter to surface
        proactively if relevant. ``subject`` is used as the change's ``entity_id`` so
        it rides the same channel as spatial changes (a subject may be an entity, a
        person entity, or a place/zone key — all stable subject strings)."""
        now_iso = _iso(_utc_now())
        ev = list(evidence_refs or [])
        label = getattr(self.entities.get(subject), "label", subject) if isinstance(subject, str) else subject
        change = ChangeEvent(
            "attribute_changed", subject, str(label), now_iso,
            before={"attribute": attribute, **dict(before)},
            after={"attribute": attribute, **dict(after)},
            evidence_refs=ev,
        )
        self.change_events.append(change)
        self.metrics["change_events"] += 1
        try:
            with self._db_lock:
                self._svc_db.execute(
                    "INSERT INTO worldbrain_session_changes(live_session_id, change_type, entity_id, label, observed_at) VALUES(?,?,?,?,?)",
                    (self.live_session_id, change.change_type, subject, str(label), now_iso),
                )
                self._svc_db.commit()
        except Exception:
            pass
        # A change confirmed by two independent modalities (seen + heard) is
        # observed; a single-modality diff is probable (a re-reading could differ).
        sources = {str(before.get("source") or ""), str(after.get("source") or "")}
        truth_level = "observed" if len(sources - {""}) >= 2 else "probable"
        try:
            store = _load_store()
            store.store_visual_event({
                "memory_owner_id": self.person_id,
                "live_session_id": self.live_session_id,
                "event_type": "change_attribute_changed",
                "occurred_at": now_iso,
                "entity": {"entity_id": subject, "label": str(label), "attribute": attribute},
                "observation": {"before": change.before, "after": change.after},
                "truth_level": truth_level,
                "confidence": 0.7,
                "evidence": ev,
                "provenance": {"producer": "attribute_memory"},
            }, db_path=self.db_path)
        except Exception:
            pass
        return change.to_dict()

    # ---------------------------------------------------------------- correction
    @staticmethod
    def _norm_label(label: str | None) -> str:
        return (label or "").strip().lower()

    def suspend_label(self, label: str) -> int:
        """Suspend an object/place *label* the user corrected away (E35 §3).

        Every entity carrying this label is dropped now and filtered out of every
        subsequent snapshot/SceneDelta. Returns the number of live entities hidden.
        The label stays suspended for the session so a re-detection under the same
        (wrong) label does not resurface it."""
        norm = self._norm_label(label)
        if not norm:
            return 0
        self._suspended_labels.add(norm)
        hidden = 0
        for eid, e in list(self.entities.items()):
            if self._norm_label(e.label) == norm:
                self.entities.pop(eid, None)
                # forget the track binding so a new sighting must re-promote
                for tid, mapped in list(self._track_to_entity.items()):
                    if mapped == eid:
                        self._track_to_entity.pop(tid, None)
                        self._track_counts.pop(tid, None)
                hidden += 1
        return hidden

    def suspend_zone(self, zone: str) -> None:
        """Suspend a place/zone label the user corrected away ("on n'est pas au
        bureau"). Clears it from the current session place/active_zone and keeps it
        out of future snapshots until re-established."""
        norm = self._norm_label(zone)
        if not norm:
            return
        self._suspended_zones.add(norm)
        if self._norm_label(self.session.place_hint) == norm:
            self.session.place_hint = None
        if self._norm_label(self.session.active_zone) == norm:
            self.session.active_zone = None

    def is_label_suspended(self, label: str | None) -> bool:
        return self._norm_label(label) in self._suspended_labels

    # ---------------------------------------------------------------- last-seen
    def last_seen(self) -> list[dict[str, Any]]:
        """Every known entity with its age (visible or stale), minus any label the
        user has verbally suspended (E35 §3)."""
        now = _utc_now()
        return [e.to_dict(now) for e in self.entities.values()
                if not self.is_label_suspended(e.label)]

    def last_seen_entity(self, entity_id: str) -> WorldEntity | None:
        return self.entities.get(entity_id)

    def find_entity(self, query: str) -> WorldEntity | None:
        """Best current or durable last-seen entity matching ``query``.

        The old implementation only searched ``self.entities`` and therefore lost
        every object as soon as the PhoneOnly process/session restarted.  The
        owner-scoped registry is the durable source of truth for FocusSearch; a
        registry hit is rehydrated as ``last_seen`` and never presented as visible.
        """
        record = self.find_entity_record(query)
        if not record:
            return None
        bbox = record.get("last_bbox")
        return WorldEntity(
            entity_id=str(record["entity_id"]),
            kind=str(record.get("kind") or "object"),
            label=str(record.get("label") or query or "object"),
            confidence=float(record.get("confidence") or 0.0),
            lifecycle="confirmed" if record.get("visible") else "last_seen",
            track_id=record.get("track_id"),
            first_seen=str(record.get("first_seen") or ""),
            last_seen=str(record.get("last_seen") or ""),
            last_bbox=tuple(float(v) for v in bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None,
            observation_count=int(record.get("observation_count") or 0),
            evidence_refs=list(record.get("evidence") or []),
        )

    @staticmethod
    def _search_terms(value: str | None) -> tuple[str, set[str]]:
        """Language-tolerant label matching without an object-name dictionary."""
        raw = unicodedata.normalize("NFKD", str(value or "").lower())
        folded = "".join(ch for ch in raw if not unicodedata.combining(ch))
        normalized = " ".join(re.findall(r"[a-z0-9]+", folded))
        # Function words do not identify an object.  This is grammar cleanup, not
        # an object lexicon: every noun remains data-driven from VisionRT.
        stop = {
            "le", "la", "les", "un", "une", "des", "du", "de", "mon", "ma",
            "mes", "notre", "nos", "the", "a", "an", "my", "our", "please",
            "stp", "svp", "objet", "object",
        }
        terms = {part for part in normalized.split() if part not in stop}
        return normalized, terms

    @classmethod
    def _label_match_score(cls, query: str, label: str) -> float:
        q_norm, q_terms = cls._search_terms(query)
        l_norm, l_terms = cls._search_terms(label)
        if not q_norm or not l_norm:
            return 0.0
        if q_norm == l_norm:
            return 4.0
        if l_norm in q_norm or q_norm in l_norm:
            return 3.0
        if not q_terms or not l_terms:
            return 0.0
        overlap = len(q_terms & l_terms)
        if overlap == 0:
            return 0.0
        return 1.0 + overlap / max(len(q_terms), len(l_terms))

    def _last_place_for_session(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        from mlomega_audio_elite.db import connect  # type: ignore

        try:
            with connect(self.db_path) as con:
                row = con.execute(
                    """SELECT place_hint FROM scene_session_summaries_v19
                       WHERE person_id=? AND live_session_id=?
                       ORDER BY summary_end DESC,created_at DESC LIMIT 1""",
                    (self.person_id, session_id),
                ).fetchone()
            return str(row["place_hint"]) if row and row["place_hint"] else None
        except sqlite3.Error:
            return None

    def find_entity_record(self, query: str) -> dict[str, Any] | None:
        """Return the freshest owner-scoped sighting with explicit epistemic state.

        ``visible`` is true only for an entity confirmed in this live session.
        Cross-session registry rows remain remembered facts with their timestamp,
        confidence, place (when a session summary exists) and durable evidence id.
        """
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        now = _utc_now()
        for entity in self.entities.values():
            if self.is_label_suspended(entity.label):
                continue
            score = self._label_match_score(query, entity.label)
            if score <= 0:
                continue
            item = entity.to_dict(now)
            item.update({
                "visible": entity.lifecycle == "confirmed",
                "place_hint": self.session.place_hint,
                "last_session_id": self.live_session_id,
                "source": entity.source or "live_worldbrain",
            })
            candidates.append((score + 1.0, entity.last_seen, item))

        from mlomega_audio_elite.db import connect  # type: ignore

        try:
            with connect(self.db_path) as con:
                rows = [dict(row) for row in con.execute(
                    """SELECT * FROM worldbrain_entity_registry_v19
                       WHERE person_id=? ORDER BY last_seen DESC""",
                    (self.person_id,),
                ).fetchall()]
        except sqlite3.Error:
            rows = []
        for row in rows:
            label = str(row.get("display_label") or row.get("normalized_label") or "")
            if self.is_label_suspended(label):
                continue
            score = self._label_match_score(query, label)
            if score <= 0:
                continue
            entity_id = str(row.get("entity_id") or "")
            # The live representation is more precise and already present above.
            if entity_id in self.entities:
                continue
            last_seen = str(row.get("last_seen") or "")
            try:
                observed = datetime.fromisoformat(last_seen)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (now - observed).total_seconds())
            except (TypeError, ValueError):
                age_seconds = None
            try:
                last_bbox = json.loads(row.get("last_bbox_json") or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                last_bbox = None
            session_id = str(row.get("last_session_id") or "")
            try:
                durable_evidence = json.loads(row.get("evidence_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                durable_evidence = []
            candidates.append((score, last_seen, {
                "entity_id": entity_id,
                "kind": row.get("kind"),
                "label": label,
                "confidence": float(row.get("confidence") or 0.0),
                "visible": False,
                "lifecycle": "last_seen",
                "track_id": row.get("last_track_id"),
                "first_seen": row.get("first_seen"),
                "last_seen": last_seen,
                "last_bbox": last_bbox,
                "observation_count": int(row.get("observation_count") or 0),
                "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                "place_hint": self._last_place_for_session(session_id),
                "last_session_id": session_id,
                "evidence": [
                    f"worldbrain_entity_registry_v19:{entity_id}",
                    *[str(ref) for ref in durable_evidence if str(ref)],
                ],
                "source": (
                    row.get("source")
                    if row.get("source") not in {None, "", "visionrt"}
                    else "durable_registry"
                ),
                "truth_level": row.get("truth_level") or "observed",
            }))
        # Open-vocabulary objects (keys, eyeglasses, personal tools, etc.) are
        # outside the fixed COCO-80 detector.  The nightly Deep Vision pass does
        # observe them on selected, coverage-proven keyframes.  Reuse its audited
        # object list as a *coarse last-seen* fallback: no bbox and therefore no
        # arrow/bearing, but a real time/place/evidence answer instead of losing
        # the observation completely.  Latest matching observation wins.
        try:
            with connect(self.db_path) as con:
                deep_rows = [
                    dict(row) for row in con.execute(
                        """SELECT deep_observation_id,live_session_id,frame_id,
                                  frame_time,location_hint,objects_json
                           FROM brainlive_deep_vision_observations_v161
                           WHERE person_id=? AND status='ok'
                           ORDER BY COALESCE(frame_time,created_at) DESC LIMIT 500""",
                        (self.person_id,),
                    ).fetchall()
                ]
        except sqlite3.Error:
            deep_rows = []
        for row in deep_rows:
            try:
                objects = json.loads(row.get("objects_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                objects = []
            if not isinstance(objects, list):
                continue
            for raw_object in objects:
                if isinstance(raw_object, dict):
                    label = str(
                        raw_object.get("label")
                        or raw_object.get("name")
                        or raw_object.get("object")
                        or ""
                    )
                else:
                    label = str(raw_object or "")
                if not label or self.is_label_suspended(label):
                    continue
                score = self._label_match_score(query, label)
                if score <= 0:
                    continue
                last_seen = str(row.get("frame_time") or "")
                try:
                    observed = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                    age_seconds = max(0.0, (now - observed).total_seconds())
                except (TypeError, ValueError):
                    age_seconds = None
                observation_id = str(row.get("deep_observation_id") or "")
                frame_id = str(row.get("frame_id") or "")
                candidates.append((score, last_seen, {
                    "entity_id": f"deepvision:{observation_id}:{label.casefold()}",
                    "kind": "object",
                    "label": label,
                    "confidence": 0.55,
                    "visible": False,
                    "lifecycle": "last_seen",
                    "track_id": None,
                    "first_seen": last_seen,
                    "last_seen": last_seen,
                    "last_bbox": None,
                    "observation_count": 1,
                    "age_seconds": (
                        round(age_seconds, 1) if age_seconds is not None else None
                    ),
                    "place_hint": row.get("location_hint"),
                    "last_session_id": row.get("live_session_id"),
                    "evidence": [
                        f"brainlive_deep_vision_observations_v161:{observation_id}",
                        *( [f"frame:{frame_id}"] if frame_id else [] ),
                    ],
                    "source": "deep_vision_last_seen",
                    "truth_level": "probable",
                }))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    # ---------------------------------------------------------------- persistence
    def _persist_events(
        self, promoted: list[WorldEntity], changes: list[ChangeEvent], now_iso: str
    ) -> None:
        store = _load_store()
        for e in promoted:
            store.store_visual_event({
                "memory_owner_id": self.person_id,
                "live_session_id": self.live_session_id,
                "event_type": "entity_last_seen",
                "occurred_at": e.last_seen or now_iso,
                "entity": {"entity_id": e.entity_id, "kind": e.kind, "label": e.label, "lifecycle": e.lifecycle},
                "observation": {"bbox": list(e.last_bbox) if e.last_bbox else None, "observation_count": e.observation_count},
                "truth_level": "observed",
                "confidence": e.confidence,
                "evidence": e.evidence_refs,
                "provenance": {"producer": "worldbrain"},
            }, db_path=self.db_path)
        for c in changes:
            store.store_visual_event({
                "memory_owner_id": self.person_id,
                "live_session_id": self.live_session_id,
                "event_type": f"change_{c.change_type}",
                "occurred_at": c.observed_at,
                "entity": {"entity_id": c.entity_id, "label": c.label},
                "observation": {"before": c.before, "after": c.after},
                "truth_level": "observed",
                "confidence": 0.7,
                "evidence": c.evidence_refs,
                "provenance": {"producer": "worldbrain"},
            }, db_path=self.db_path)

    def _publish_world_state(
        self, observations: list[Observation], now_iso: str, map_quality: float
    ) -> None:
        ctx = _load_visual_context()
        visible = [o.to_dict() for o in observations]
        world_state = {
            "state_time": now_iso,
            "where_am_i": self.session.place_hint,
            "who_is_active": [o["label"] for o in visible if o["label"] == "person"],
            "what_is_happening": None,
            "visual_context": {
                "visible_entities": visible,
                "map_quality": round(map_quality, 3),
                "active_zone": self.session.active_zone,
            },
            "evidence": sorted({r for o in observations for r in o.evidence_refs}),
            "confidence": 0.8,
        }
        scene_obs = [{
            "model": "worldbrain",
            "scene_summary": None,
            "location_hint": self.session.place_hint,
            "people_count": sum(1 for o in visible if o["label"] == "person"),
            "objects": [{"label": o["label"], "track_id": o["track_id"], "confidence": o["confidence"]} for o in visible],
            "confidence": 0.8,
        }] if visible else []
        try:
            ctx.publish_visual_context(
                person_id=self.person_id, live_session_id=self.live_session_id,
                world_state=world_state, observations=scene_obs, db_path=self.db_path,
            )
            self.metrics["world_state_published"] += 1
        except Exception:
            pass

    # ---------------------------------------------------------------- summary
    def end_session(self, *, place_hint: str | None = None) -> str:
        """Flush an end-of-session summary into scene_session_summaries_v19."""
        store = _load_store()
        now_iso = _iso(_utc_now())
        entities = self.last_seen()
        summary = {
            "entities": entities,
            "entity_count": len(entities),
            "change_count": len(self.change_events),
            "changes": [c.to_dict() for c in self.change_events[-50:]],
            "active_zone": self.session.active_zone,
        }
        evidence = sorted({r for e in self.entities.values() for r in e.evidence_refs})
        return store.store_scene_summary({
            "memory_owner_id": self.person_id,
            "live_session_id": self.live_session_id,
            "summary_start": self.session.started_at,
            "summary_end": now_iso,
            "place_hint": place_hint or self.session.place_hint,
            "map_quality": self.session.map_quality,
            "summary": summary,
            "evidence_refs": evidence,
        }, db_path=self.db_path)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.live_session_id,
            "place_hint": self.session.place_hint,
            "active_zone": self.session.active_zone,
            "map_quality": round(self.session.map_quality, 3),
            "entities": self.last_seen(),
            "relations": [r.to_dict() for r in self.relations],
            "recent_changes": [c.to_dict() for c in self.change_events[-10:]],
            "metrics": dict(self.metrics),
        }
