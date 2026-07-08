from __future__ import annotations

"""ChangeAttention — instant "something changed here" cue on zone re-entry (E48-B §2).

The nightly detection already exists: E28 WorldBrain change candidates (moved /
appeared / disappeared) and E38 bi-modal attribute changes are consolidated at
close-day. What is missing is the *live* cue: when the wearer RE-ENTERS a zone
they were already in during this session (or, best-effort, a zone matching a
``place_hint`` seen in a past session), compare the *current* observed state
(WorldBrain confirmed/last-seen entities visible in that zone) against the
*memorized* state from the last visit → if the difference is net (entities
disappeared/appeared beyond a noise floor), emit ONE sober cue — a low-priority
point of interest, never a precise spatial arrow, never a fabricated claim.

Zone identity (honest limits, ADR docs/DECISIONS.md):

* ``active_zone`` (``spatial.PoseKeyframeMap`` pose-cluster id, e.g. ``zone-3``)
  is stable only *within* a session — it is what lets us detect "you left this
  corner and came back" during the same session. This is the primary, always-on
  path.
* ``place_hint`` (a string the user/system establishes, e.g. at ``end_session``)
  is the only identifier that is stable *across* sessions today. When present,
  :class:`ChangeAttention` also folds in the entities recorded in the most recent
  ``scene_session_summaries_v19`` row for that same ``place_hint`` (read-only,
  the same table WorldBrain already writes at end of session — no new schema).
  Absent a matching prior summary, cross-session comparison is silently skipped
  (never invented).

Anti-noise invariants (§2 of the backlog, non-negotiable):

* SILENCE if ``map_quality`` is below ``min_map_quality`` — a change cue is a
  spatial claim ("here"), and a low-quality map cannot honestly support "here".
* SILENCE on the FIRST visit to a zone (nothing to compare against yet).
* A cue requires the delta score to clear ``min_change_score`` (net differences
  over the union of memorized/current labels) — single-entity noise from a
  promotion/track-flap does not qualify.
* Per-zone cooldown (``cooldown_seconds``): no second cue for the same zone
  before it elapses, even across multiple re-entries.
* At most ONE cue per re-entry (the first qualifying re-entry check wins; the
  zone is not re-evaluated again until the wearer leaves and re-enters).

Delivery reuses the existing scene-adapter path (``BrainLiveSceneAdapter._enqueue``
→ ``v18_delivery.enqueue_delivery`` → the canonical H1 delivery queue) — no new
queue, no new broker. The candidate is a ``context_card`` with ``priority`` low,
an honest ``truth_level`` (``probable`` — a set-difference is suggestive, not a
verified fact) and whatever evidence refs the changed entities carry.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_connect():
    from mlomega_audio_elite.db import connect  # type: ignore

    return connect


# --------------------------------------------------------------------------- config
@dataclass
class ChangeAttentionConfig:
    """Thresholds/cooldown — all config, never hardcoded (same style as siblings)."""

    min_change_score: float = 0.34   # net label diffs / union size, above which a cue fires
    cooldown_seconds: float = 300.0  # no re-cue for the same zone before this elapses
    min_map_quality: float = 0.35    # below this, total silence (no spatial claim)
    max_zones_tracked: int = 64      # bound on the in-session zone-state map


@dataclass
class _ZoneMemory:
    labels: set[str] = field(default_factory=set)
    last_left_at: float | None = None   # monotonic time the zone was last exited
    last_cue_at: float | None = None    # monotonic time the last cue fired (cooldown)
    visited: bool = False               # False until the FIRST full pass through the zone


def _entity_labels(entities: Sequence[Mapping[str, Any]]) -> set[str]:
    """Normalised label set of currently *present* (not stale) entities."""
    out: set[str] = set()
    for e in entities:
        if e.get("lifecycle") not in ("confirmed", None):
            continue
        label = str(e.get("label") or "").strip().lower()
        if label:
            out.add(label)
    return out


def _change_score(memorized: set[str], current: set[str]) -> float:
    union = memorized | current
    if not union:
        return 0.0
    diff = memorized ^ current  # appeared or disappeared labels
    return len(diff) / len(union)


class ChangeAttention:
    """Detects a net state change on zone re-entry and emits one sober cue.

    Fed by the same ``SceneDelta``/``WorldBrain.snapshot`` cadence as the scene
    adapter — call :meth:`on_scene_snapshot` once per delta (or on the same
    cadence as ``_on_scene_delta``). Delivery is via the injected ``scene_adapter``
    (must expose ``_enqueue``); a bare instance without one only computes/returns
    the cue dict so callers/tests can inspect it without a live queue.
    """

    def __init__(
        self,
        *,
        person_id: str = "me",
        live_session_id: str = "",
        db_path: Any = None,
        scene_adapter: Any = None,
        config: ChangeAttentionConfig | None = None,
        now_fn: Any = None,
    ) -> None:
        self.person_id = person_id
        self.live_session_id = live_session_id
        self.db_path = db_path
        self.scene_adapter = scene_adapter
        self.config = config or ChangeAttentionConfig()
        self._now = now_fn or _monotonic
        self._zones: dict[str, _ZoneMemory] = {}
        self._current_zone: str | None = None
        self._cross_session_checked: set[str] = set()  # place_hint keys already folded in
        self.metrics = {
            "zone_entries": 0,
            "zone_reentries": 0,
            "cues_emitted": 0,
            "silenced_low_quality": 0,
            "silenced_cooldown": 0,
            "silenced_first_visit": 0,
            "silenced_below_threshold": 0,
        }

    # ----------------------------------------------------------------- ingest
    def on_scene_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        place_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Consume one ``WorldBrain.snapshot()``-shaped mapping.

        ``zone`` is ``snapshot['active_zone']`` (falls back to nothing — a session
        with no spatial provider never fires). Returns the enqueue result dict if
        a cue was emitted, else ``None`` (silence, by far the common case)."""
        zone = snapshot.get("active_zone")
        if not zone:
            return None
        zone = str(zone)
        map_quality = float(snapshot.get("map_quality") or 0.0)
        current_labels = _entity_labels(snapshot.get("entities") or [])
        now = self._now()

        if zone != self._current_zone:
            result = self._handle_zone_entry(
                zone, current_labels=current_labels, map_quality=map_quality,
                now=now, place_hint=place_hint,
            )
            # Mark the previously-active zone as "left" so its memory is frozen.
            if self._current_zone is not None and self._current_zone in self._zones:
                self._zones[self._current_zone].last_left_at = now
            self._current_zone = zone
            return result

        # Still in the same zone: keep the memorized label set current so the
        # NEXT re-entry compares against the freshest state, but never re-fire.
        mem = self._zones.get(zone)
        if mem is not None:
            mem.labels |= current_labels
        return None

    def _handle_zone_entry(
        self,
        zone: str,
        *,
        current_labels: set[str],
        map_quality: float,
        now: float,
        place_hint: str | None,
    ) -> dict[str, Any] | None:
        cfg = self.config
        mem = self._zones.get(zone)
        if mem is None:
            mem = self._new_zone_memory(zone, place_hint=place_hint)
            self._zones[zone] = mem
            self._evict_if_needed()

        is_reentry = mem.visited
        self.metrics["zone_reentries" if is_reentry else "zone_entries"] += 1

        if not is_reentry:
            # First visit: nothing to compare against — silently learn the state.
            mem.visited = True
            mem.labels = set(current_labels)
            self.metrics["silenced_first_visit"] += 1
            return None

        # SILENCE if map quality is too low to honestly support a "here" claim.
        if map_quality < cfg.min_map_quality:
            self.metrics["silenced_low_quality"] += 1
            mem.labels |= current_labels
            return None

        # Per-zone cooldown — even a real change does not re-cue too often.
        if mem.last_cue_at is not None and (now - mem.last_cue_at) < cfg.cooldown_seconds:
            self.metrics["silenced_cooldown"] += 1
            mem.labels |= current_labels
            return None

        memorized = set(mem.labels)
        score = _change_score(memorized, current_labels)
        if score < cfg.min_change_score:
            self.metrics["silenced_below_threshold"] += 1
            mem.labels |= current_labels
            return None

        appeared = sorted(current_labels - memorized)
        disappeared = sorted(memorized - current_labels)
        mem.last_cue_at = now
        mem.labels = set(current_labels)
        return self._emit_cue(
            zone=zone, appeared=appeared, disappeared=disappeared,
            score=score, place_hint=place_hint,
        )

    def _new_zone_memory(self, zone: str, *, place_hint: str | None) -> _ZoneMemory:
        """Seed a freshly-seen zone from a matching PAST session summary when a
        stable ``place_hint`` is available (best-effort, read-only, ADR §cross
        -session). Absent a match, the zone starts unvisited (first-visit silence)."""
        if not place_hint or place_hint in self._cross_session_checked:
            return _ZoneMemory()
        self._cross_session_checked.add(place_hint)
        prior = self._prior_session_labels(place_hint)
        if prior is None:
            return _ZoneMemory()
        return _ZoneMemory(labels=prior, visited=True)

    def _prior_session_labels(self, place_hint: str) -> set[str] | None:
        """Entities recorded in the most recent ``scene_session_summaries_v19`` row
        for this ``place_hint`` (read-only core query, mirrors the pattern already
        used by ``routine_associations.py``). ``None`` on any absence/failure —
        never a crash, never a fabricated memory."""
        try:
            import json as _json

            connect = _load_connect()
            with connect(self.db_path) as con:
                row = con.execute(
                    """SELECT summary_json FROM scene_session_summaries_v19
                       WHERE person_id=? AND place_hint=? AND live_session_id!=?
                       ORDER BY summary_end DESC, created_at DESC LIMIT 1""",
                    (self.person_id, place_hint, self.live_session_id),
                ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        try:
            summary = _json.loads(row["summary_json"] or "{}")
        except Exception:
            return None
        entities = summary.get("entities") if isinstance(summary, dict) else None
        if not isinstance(entities, list):
            return None
        return _entity_labels(entities)

    def _evict_if_needed(self) -> None:
        cap = self.config.max_zones_tracked
        if len(self._zones) <= cap:
            return
        # Drop the longest-untouched zone (by last_left_at, oldest first); zones
        # never left (None) are kept as they may still be active.
        candidates = [(k, v.last_left_at) for k, v in self._zones.items() if v.last_left_at is not None]
        if not candidates:
            return
        oldest_key = min(candidates, key=lambda kv: kv[1])[0]
        self._zones.pop(oldest_key, None)

    # ----------------------------------------------------------------- emit
    def _emit_cue(
        self,
        *,
        zone: str,
        appeared: list[str],
        disappeared: list[str],
        score: float,
        place_hint: str | None,
    ) -> dict[str, Any] | None:
        message = self._cue_message(appeared, disappeared)
        evidence = self._evidence_refs(appeared, disappeared)
        self.metrics["cues_emitted"] += 1
        if self.scene_adapter is None or not hasattr(self.scene_adapter, "_enqueue"):
            # No delivery path wired (e.g. unit test computing the cue only).
            return {
                "status": "computed", "zone": zone, "message": message,
                "appeared": appeared, "disappeared": disappeared,
                "score": round(score, 3), "evidence_refs": evidence,
            }
        source_key = f"scene:{self.live_session_id}:change_attention:{zone}"
        result = self.scene_adapter._enqueue(
            source_key=source_key, message=message, evidence_refs=evidence,
            priority=0.35,  # deliberately low — a sober point of interest, not an alert
            kind="change_attention",
        )
        return {**result, "zone": zone, "appeared": appeared, "disappeared": disappeared,
                "score": round(score, 3)}

    @staticmethod
    def _cue_message(appeared: list[str], disappeared: list[str]) -> str:
        """A sober, honest point-of-interest — never a precise spatial arrow, never
        naming a single confident cause when several entities differ."""
        if len(disappeared) == 1 and not appeared:
            return f"Quelque chose a changé ici : {disappeared[0]} ne semble plus là."
        if len(appeared) == 1 and not disappeared:
            return f"Quelque chose a changé ici : {appeared[0]} n'y était pas avant."
        return "Quelque chose a changé ici depuis ta dernière visite."

    def _evidence_refs(self, appeared: list[str], disappeared: list[str]) -> list[str]:
        wb = getattr(self.scene_adapter, "world", None)
        if wb is None:
            return []
        refs: set[str] = set()
        try:
            for e in wb.last_seen():
                if str(e.get("label") or "").lower() in {*appeared, *disappeared}:
                    refs.update(e.get("evidence") or [])
        except Exception:
            return []
        return sorted(refs)

    # ----------------------------------------------------------------- introspection
    def snapshot(self) -> dict[str, Any]:
        return {
            "current_zone": self._current_zone,
            "zones_tracked": len(self._zones),
            "metrics": dict(self.metrics),
        }


def _monotonic() -> float:
    import time

    return time.monotonic()
