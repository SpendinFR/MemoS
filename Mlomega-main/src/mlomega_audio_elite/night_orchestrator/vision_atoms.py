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
from dataclasses import dataclass, field
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
