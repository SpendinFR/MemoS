"""E64-B vision reduction - lossless collapse of raw scene observations.

The first real nightly run flattened ~472 ``vision_scene_observations`` (almost
one per frame, mostly the SAME state, e.g. "person track t1") into ~945 vision
pseudo-turns and shipped them raw to Brain2, blowing the prompt to 1.6M chars.

This module collapses those observations DETERMINISTICALLY and WITHOUT LOSS:
consecutive observations that share the same *state* (the set of (label,
track_id) objects + people_count + visible text + scene/location) become one
``VisionChangeAtom`` carrying ``[first_seen, last_seen, count, digest,
source_refs]``. A REAL change (a new/left label or track, a people-count change,
new visible text, a scene/location change) opens a new atom. A change in
*confidence only* never opens a new atom - confidence is jitter, not a cognitive
event. Every raw ``observation_id`` ends up in exactly one atom's
``source_refs``; the raw frames and observations stay untouched in the DB for
replay. No LLM is involved and no business prompt is touched.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..utils import stable_id
from .evidence_ref import content_digest

# Fields that define the STABLE state of a scene observation. Confidence and raw
# per-frame numbers are intentionally excluded so pure jitter does not split.
_STATE_FIELDS = ("objects", "people_count", "visible_text", "location_hint", "scene_summary")


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _object_identity(objects: Any) -> list[list[str]]:
    """Deterministic identity of the detected objects: sorted (label, track_id).

    Confidence is dropped on purpose. The result is a sorted list of [label,
    track] pairs so two observations with the same objects in any order compare
    equal.
    """
    out: list[list[str]] = []
    for obj in objects or []:
        if not isinstance(obj, Mapping):
            continue
        label = str(obj.get("label") or "")
        track = str(obj.get("track_id") or obj.get("track") or "")
        out.append([label, track])
    out.sort()
    return out


def _observation_state(obs: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the stable, comparable state of one observation row."""
    objects = _loads(obs.get("objects_json"), [])
    if not objects:
        # Some producers nest objects under raw_json.
        raw = _loads(obs.get("raw_json"), {})
        if isinstance(raw, Mapping):
            objects = raw.get("objects") or []
    visible_text = _loads(obs.get("visible_text_json"), [])
    people = obs.get("people_count")
    return {
        "objects": _object_identity(objects),
        "people_count": None if people is None else int(people),
        "visible_text": sorted(str(t) for t in (visible_text or [])),
        "location_hint": obs.get("location_hint") or None,
        "scene_summary": obs.get("scene_summary") or None,
    }


def _state_key(state: Mapping[str, Any]) -> str:
    return content_digest({k: state.get(k) for k in _STATE_FIELDS})


def _pk(obs: Mapping[str, Any]) -> str:
    return str(obs.get("observation_id") or obs.get("id") or "")


def _ts(obs: Mapping[str, Any]) -> str:
    return str(obs.get("created_at") or obs.get("captured_at") or "")


@dataclass(frozen=True)
class VisionChangeAtom:
    """One maximal run of an identical scene state (lossless, provenance-complete)."""

    atom_id: str
    kind: str  # "state_range" today; transitions are described by entered/left
    state_key: str
    first_seen: str
    last_seen: str
    count: int
    digest: str
    source_refs: tuple[str, ...]  # observation_ids covered (exactly-once)
    frame_refs: tuple[str, ...]  # frame_ids covered
    summary: Mapping[str, Any]  # minimal LLM-facing fields (labels/tracks/people/text)
    entered: tuple[str, ...] = field(default_factory=tuple)  # (label:track) new vs prev atom
    left: tuple[str, ...] = field(default_factory=tuple)  # (label:track) gone vs prev atom

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "kind": self.kind,
            "state_key": self.state_key,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "count": self.count,
            "digest": self.digest,
            "source_refs": list(self.source_refs),
            "frame_refs": list(self.frame_refs),
            "summary": dict(self.summary),
            "entered": list(self.entered),
            "left": list(self.left),
        }


def _labels_tracks(state: Mapping[str, Any]) -> set[str]:
    return {f"{label}:{track}" for label, track in state.get("objects", [])}


def reduce_vision_observations(
    observations: Iterable[Mapping[str, Any]],
) -> list[VisionChangeAtom]:
    """Collapse raw scene observations into lossless VisionChangeAtoms.

    Guarantees (enforced by tests):
    - every input observation_id appears in exactly one atom's ``source_refs``;
    - consecutive identical states merge into a single range atom;
    - a real state change (labels/tracks/people/text/scene) opens a new atom;
    - a confidence-only difference never opens a new atom;
    - ordering is deterministic (by created_at then observation_id).
    """
    rows = [o for o in observations if _pk(o)]
    rows.sort(key=lambda o: (_ts(o), _pk(o)))

    atoms: list[VisionChangeAtom] = []
    cur_state: dict[str, Any] | None = None
    cur_key: str | None = None
    cur_refs: list[str] = []
    cur_frames: list[str] = []
    cur_first: str = ""
    cur_last: str = ""
    prev_lt: set[str] = set()

    def _flush() -> None:
        nonlocal prev_lt
        if cur_state is None or not cur_refs:
            return
        lt = _labels_tracks(cur_state)
        entered = tuple(sorted(lt - prev_lt))
        left = tuple(sorted(prev_lt - lt))
        atom_id = stable_id("vatom", cur_key, cur_refs[0], cur_refs[-1])
        atoms.append(
            VisionChangeAtom(
                atom_id=atom_id,
                kind="state_range",
                state_key=str(cur_key),
                first_seen=cur_first,
                last_seen=cur_last,
                count=len(cur_refs),
                digest=content_digest(
                    {"state": cur_state, "source_refs": cur_refs}
                ),
                source_refs=tuple(cur_refs),
                frame_refs=tuple(dict.fromkeys(cur_frames)),
                summary={
                    "objects": cur_state.get("objects"),
                    "people_count": cur_state.get("people_count"),
                    "visible_text": cur_state.get("visible_text"),
                    "location_hint": cur_state.get("location_hint"),
                    "scene_summary": cur_state.get("scene_summary"),
                },
                entered=entered,
                left=left,
            )
        )
        prev_lt = lt

    for obs in rows:
        state = _observation_state(obs)
        key = _state_key(state)
        pk = _pk(obs)
        frame = str(obs.get("frame_id") or "")
        ts = _ts(obs)
        if cur_key is None:
            cur_state, cur_key = state, key
            cur_refs, cur_frames = [pk], ([frame] if frame else [])
            cur_first = cur_last = ts
        elif key == cur_key:
            cur_refs.append(pk)
            if frame:
                cur_frames.append(frame)
            cur_last = ts
        else:
            _flush()
            cur_state, cur_key = state, key
            cur_refs, cur_frames = [pk], ([frame] if frame else [])
            cur_first = cur_last = ts
    _flush()
    return atoms


def _timeline_item_to_observation(item: Mapping[str, Any], idx: int) -> dict[str, Any]:
    """Map one ``vision_timeline_json`` item (event assembler shape) to the
    canonical scene-observation shape ``reduce_vision_observations`` consumes.

    The assembler item already carries ``source_id`` (the observation_id) and
    ``frame_id``; objects/visible_text are already decoded lists. ``time`` is the
    event time. This lets the SAME tested reducer collapse the bundle's vision
    timeline without re-reading the DB.
    """
    return {
        "observation_id": str(item.get("source_id") or f"vtl_{idx}"),
        "frame_id": item.get("frame_id") or "",
        "objects_json": item.get("objects") or [],
        "people_count": item.get("people_count"),
        "visible_text_json": item.get("visible_text") or [],
        "location_hint": item.get("location_hint"),
        "scene_summary": item.get("summary"),
        "created_at": item.get("time") or "",
    }


def reduce_vision_timeline(items: Iterable[Mapping[str, Any]]) -> list[VisionChangeAtom]:
    """Collapse the event assembler's ``vision_timeline`` items into atoms.

    Same guarantees as ``reduce_vision_observations`` (lossless, deterministic,
    confidence-agnostic) but for the bundle-side item shape. Used to feed Brain2
    a few change atoms instead of ~945 per-frame pseudo-turns.
    """
    rows = list(items)
    # ``vision_timeline_json`` contains TWO records for most detector instants:
    # a raw ``vision_frames`` row (no objects; summary is a unique filename) and
    # a semantic ``vision_scene_observations`` row. Feeding both into the state
    # reducer alternates empty/raw and detected states, producing almost one atom
    # per row. Raw frames are immutable evidence, not cognitive state changes:
    # attach them to the nearest semantic observation, then reduce the semantic
    # stream. No source/frame id is discarded.
    raw_frames = [it for it in rows if str(it.get("source_table") or "") == "vision_frames"]
    semantic = [it for it in rows if str(it.get("source_table") or "") != "vision_frames"]
    if not semantic:
        # A camera-only bundle still has one honest evidence range instead of
        # hundreds of filename-driven pseudo-events.
        semantic = [
            {
                **dict(it),
                "summary": None,
                "objects": [],
                "visible_text": [],
            }
            for it in raw_frames
        ]
        raw_frames = []

    def _time_value(item: Mapping[str, Any]) -> float:
        text = str(item.get("time") or "").replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).timestamp()
        except (TypeError, ValueError):
            return 0.0

    ordered_semantic = sorted(
        enumerate(semantic), key=lambda pair: (_time_value(pair[1]), pair[0])
    )
    semantic_times = [_time_value(item) for _, item in ordered_semantic]
    raw_by_semantic_id: dict[str, list[Mapping[str, Any]]] = {}
    for raw in raw_frames:
        t = _time_value(raw)
        pos = bisect_left(semantic_times, t)
        candidates = [p for p in (pos - 1, pos) if 0 <= p < len(ordered_semantic)]
        nearest = min(candidates, key=lambda p: abs(semantic_times[p] - t))
        owner_index, owner = ordered_semantic[nearest]
        owner_id = str(owner.get("source_id") or f"vtl_{owner_index}")
        raw_by_semantic_id.setdefault(owner_id, []).append(raw)

    obs = [_timeline_item_to_observation(it, i) for i, it in enumerate(semantic)]
    atoms = reduce_vision_observations(obs)
    if not raw_by_semantic_id:
        return atoms

    expanded: list[VisionChangeAtom] = []
    for atom in atoms:
        source_refs: list[str] = []
        frame_refs = list(atom.frame_refs)
        for source_ref in atom.source_refs:
            source_refs.append(source_ref)
            for raw in raw_by_semantic_id.get(source_ref, []):
                raw_source = str(raw.get("source_id") or "")
                raw_frame = str(raw.get("frame_id") or "")
                if raw_source:
                    source_refs.append(raw_source)
                if raw_frame:
                    frame_refs.append(raw_frame)
        source_refs = list(dict.fromkeys(source_refs))
        frame_refs = list(dict.fromkeys(frame_refs))
        expanded.append(
            replace(
                atom,
                atom_id=stable_id(
                    "vatom", atom.state_key, source_refs[0], source_refs[-1]
                ),
                digest=content_digest(
                    {"state_key": atom.state_key, "source_refs": source_refs}
                ),
                source_refs=tuple(source_refs),
                frame_refs=tuple(frame_refs),
            )
        )
    return expanded
