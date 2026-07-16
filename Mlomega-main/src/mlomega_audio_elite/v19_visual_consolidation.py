"""V19 nightly visual consolidation (Lot 2, E15).

Consolidates the day's ``visual_events_v19`` purely from V19 tables (no
WorldBrain yet — that arrives in Lot 3). What it does, honestly and only from
observed rows:

1. Aggregate the day's events into a **last-seen per entity** map.
2. Detect **object moves**: an entity seen at a place different from its most
   recent previous last-seen emits an inferred ``object_moved`` event
   (``truth_level='inferred'``) that references both observations.
3. Detect **spatial routines**: the same (entity, place, time-slot) observed
   >=3 times upserts a ``brain2_spatial_routine_models`` row.
4. Write a ``scene_session_summaries_v19`` row summarising the day.

All writes stay owner-scoped and append-only where the target is immutable.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .db import connect, insert_only, upsert, write_transaction
from .night_orchestrator.deep_vision_selection import frame_id_from_evidence
from .utils import json_dumps, json_loads, now_iso, stable_id
from .v19_visual_store import ensure_v19_visual_schema, store_scene_summary

SPATIAL_ROUTINE_MIN_OCCURRENCES = 3

# E64-I4.3: durable, additive record proving that the day's visual consolidation
# REUSED an already-validated Deep Vision analysis (semantics) joined to the
# VisionRT live detection/track/bbox for the SAME image, instead of paying a
# second VLM inference. Keyed by stable ids so a rejeu upserts (never duplicates)
# and always carries provenance back to the origin observation + live event.
DEEP_VISION_REUSE_TABLE = "visual_consolidation_deep_reuse_v19"

_DEEP_VISION_REUSE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {DEEP_VISION_REUSE_TABLE}(
  reuse_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  bundle_id TEXT NOT NULL,
  frame_id TEXT,
  deep_observation_id TEXT NOT NULL,
  live_session_id TEXT,
  observed_activity TEXT,
  location_hint TEXT,
  visionrt_track_present INTEGER NOT NULL DEFAULT 0,
  visionrt_bbox_present INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  source_refs_json TEXT DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vc_deep_reuse_owner
  ON {DEEP_VISION_REUSE_TABLE}(person_id, package_date, bundle_id);
"""


def _entity_key(event: dict[str, Any]) -> str | None:
    entity = json_loads(event.get("entity_json"), {}) or {}
    if not isinstance(entity, dict):
        return None
    key = entity.get("entity_id") or entity.get("label") or entity.get("kind")
    return str(key).strip().lower() if key else None


def _place_key(event: dict[str, Any]) -> str | None:
    place = json_loads(event.get("place_json"), {}) or {}
    if isinstance(place, dict):
        key = place.get("place_id") or place.get("label") or place.get("name")
        if key:
            return str(key).strip().lower()
    obs = json_loads(event.get("observation_json"), {}) or {}
    if isinstance(obs, dict) and obs.get("place"):
        return str(obs["place"]).strip().lower()
    return None


def _local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("MLOMEGA_LOCAL_TZ", "Europe/Paris"))
    except Exception:
        return ZoneInfo("Europe/Paris")


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _local_day_utc_bounds(package_date: str) -> tuple[str, str]:
    """Return the local civil day's exact half-open bounds expressed in UTC."""
    local_day = date.fromisoformat(str(package_date)[:10])
    local_start = datetime.combine(local_day, time.min, tzinfo=_local_zone())
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc).isoformat(), local_end.astimezone(timezone.utc).isoformat()


def _time_slot(occurred_at: str | None) -> str:
    """Coarse time slot in the configured local civil timezone."""
    if not occurred_at:
        return "unknown"
    parsed = _parse_instant(occurred_at)
    if parsed is None:
        return "unknown"
    hour = parsed.astimezone(_local_zone()).hour
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def _frame_bbox_from_event(event: dict[str, Any]) -> list[float] | None:
    """Extract the VisionRT bbox this event carries (last-seen or moved-after)."""
    obs = json_loads(event.get("observation_json"), {}) or {}
    if not isinstance(obs, dict):
        return None
    bbox = obs.get("bbox")
    if bbox is None and isinstance(obs.get("after"), dict):
        bbox = obs["after"].get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        except (TypeError, ValueError):
            return None
    return None


def reuse_deep_vision_outputs(
    *,
    person_id: str,
    package_date: str,
    day_start: str,
    day_end: str,
    live_session_id: str | None = None,
    db_path=None,
) -> dict[str, Any]:
    """Reuse already-validated Deep Vision semantics + VisionRT positions by code.

    E64-I4.3: at close-day the offline Deep Vision pass (post_stop, which runs
    BEFORE this stage) has already written validated observations for the day's
    keyframes into ``brainlive_deep_vision_observations_v161`` (status='ok'), and
    VisionRT has already recorded live detections/tracks/bbox in
    ``visual_events_v19``. This joins the two by person/date/bundle/frame and
    records a durable reuse row per validated observation - WITHOUT any new VLM
    call. Provenance (``source_refs``) points back to the origin observation and,
    when available, the matching VisionRT visual event, so the reuse is fully
    traceable. Idempotent by ``reuse_id`` (a rejeu upserts, never duplicates).

    Explicit fallback: an observation whose image has no validated analysis is
    never reached here (status filter); a reused observation with no matching
    VisionRT bbox/track is recorded with ``status='reused_no_position'`` rather
    than silently dropped, so the degraded case is documented, never a crash.
    """
    with connect(db_path) as con:
        has_obs = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='brainlive_deep_vision_observations_v161'"
        ).fetchone()
        if not has_obs:
            return {"status": "absent", "reused": 0, "with_position": 0, "semantics": [], "reason": "no_deep_vision_observations_table"}
        # Only ALREADY-VALIDATED semantics are reused; a failed/degraded image is
        # not reused as if it were analysed.
        obs_rows = [
            dict(r)
            for r in con.execute(
                "SELECT deep_observation_id, bundle_id, frame_id, live_session_id, "
                "observed_activity, location_hint, image_path "
                "FROM brainlive_deep_vision_observations_v161 "
                "WHERE person_id=? AND package_date=? AND status='ok'"
                + (" AND live_session_id=?" if live_session_id else ""),
                (person_id, package_date, live_session_id) if live_session_id else (person_id, package_date),
            ).fetchall()
        ]
        # VisionRT live events for the day, indexed by frame_id (bbox/track reuse).
        vrt_q = (
            "SELECT e.visual_event_id, e.event_type, e.entity_json, e.observation_json, "
            "e.evidence_refs_json, a.frame_id AS asset_frame_id "
            "FROM visual_events_v19 e "
            "LEFT JOIN visual_evidence_assets_v19 a ON a.visual_asset_id = e.asset_id "
            "WHERE e.person_id=? AND e.occurred_at>=? AND e.occurred_at<? AND e.truth_level='observed'"
        )
        vrt_params: list[Any] = [person_id, day_start, day_end]
        if live_session_id:
            vrt_q += " AND e.live_session_id=?"
            vrt_params.append(live_session_id)
        # ALL VisionRT rows of a frame are kept (several objects on one image
        # are several detections); keeping only the first row lost objects.
        vrt_by_frame: dict[str, list[dict[str, Any]]] = {}
        for r in con.execute(vrt_q, tuple(vrt_params)).fetchall():
            row = dict(r)
            obs = json_loads(row.get("observation_json"), {}) or {}
            fid = str(
                frame_id_from_evidence(row.get("evidence_refs_json"))
                or row.get("asset_frame_id")
                or (obs.get("frame_id") if isinstance(obs, dict) else "")
                or ""
            ).strip()
            if fid:
                vrt_by_frame.setdefault(fid, []).append(row)

    if not obs_rows:
        return {"status": "absent", "reused": 0, "with_position": 0, "semantics": [], "reason": "no_validated_deep_vision_observations"}

    now = now_iso()
    reused = 0
    with_position = 0
    semantics: list[dict[str, Any]] = []
    with connect(db_path) as con, write_transaction(con):
        con.executescript(_DEEP_VISION_REUSE_SCHEMA)
        for obs in obs_rows:
            fid = str(obs.get("frame_id") or "").strip()
            vrt_rows = vrt_by_frame.get(fid, []) if fid else []
            # Every object detected on this frame is reused, not just the first.
            bboxes = [b for b in (_frame_bbox_from_event(v) for v in vrt_rows) if b is not None]
            track_present = bool(vrt_rows)
            bbox_present = bool(bboxes)
            if bbox_present:
                with_position += 1
            source_refs = [
                {
                    "source_table": "brainlive_deep_vision_observations_v161",
                    "source_id": obs.get("deep_observation_id"),
                    "reuse": "validated_vlm_semantics",
                }
            ]
            for vrt in vrt_rows:
                source_refs.append(
                    {
                        "source_table": "visual_events_v19",
                        "source_id": vrt.get("visual_event_id"),
                        "reuse": "visionrt_detection_track_bbox",
                    }
                )
            semantics.append(
                {
                    "frame_id": fid or None,
                    "deep_observation_id": obs.get("deep_observation_id"),
                    "observed_activity": obs.get("observed_activity"),
                    "location_hint": obs.get("location_hint"),
                    "live_session_id": obs.get("live_session_id") or live_session_id,
                }
            )
            reuse_id = stable_id(
                "vcdeepreuse", person_id, package_date, obs.get("bundle_id"), obs.get("deep_observation_id")
            )
            status = "reused" if bbox_present else "reused_no_position"
            upsert(
                con,
                DEEP_VISION_REUSE_TABLE,
                {
                    "reuse_id": reuse_id,
                    "person_id": person_id,
                    "package_date": package_date,
                    "bundle_id": str(obs.get("bundle_id") or ""),
                    "frame_id": fid or None,
                    "deep_observation_id": obs.get("deep_observation_id"),
                    "live_session_id": obs.get("live_session_id") or live_session_id,
                    "observed_activity": obs.get("observed_activity"),
                    "location_hint": obs.get("location_hint"),
                    "visionrt_track_present": 1 if track_present else 0,
                    "visionrt_bbox_present": 1 if bbox_present else 0,
                    "status": status,
                    "source_refs_json": json_dumps(source_refs),
                    "created_at": now,
                    "updated_at": now,
                },
                "reuse_id",
            )
            reused += 1

    return {
        "status": "reused" if with_position else "reused_no_position",
        "reused": reused,
        "with_position": with_position,
        # Validated VLM semantics, exposed so the historic consolidation writers
        # (summary/moves/routines) actually CONSUME them, not just count them.
        "semantics": semantics,
    }


def run_visual_consolidation(
    *,
    person_id: str,
    package_date: str,
    live_session_id: str | None = None,
    db_path=None,
) -> dict[str, Any]:
    ensure_v19_visual_schema(db_path)
    now = now_iso()
    day_start, day_end = _local_day_utc_bounds(package_date)

    with connect(db_path) as con:
        q = "SELECT * FROM visual_events_v19 WHERE person_id=? AND occurred_at>=? AND occurred_at<?"
        params: list[Any] = [person_id, day_start, day_end]
        if live_session_id:
            q += " AND live_session_id=?"
            params.append(live_session_id)
        q += " ORDER BY occurred_at ASC, created_at ASC"
        day_events = [dict(r) for r in con.execute(q, tuple(params)).fetchall()]
        # Prior last-seen per entity (before the day) to detect moves at day boundary.
        prior = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM visual_events_v19 WHERE person_id=? AND occurred_at < ? "
                "AND event_type != 'object_moved' ORDER BY occurred_at ASC, created_at ASC",
                (person_id, day_start),
            ).fetchall()
        ]

    # E64-I4.3: reuse the already-validated Deep Vision semantics + VisionRT
    # positions BY CODE (join on person/date/bundle/frame). No VLM is re-called;
    # a validated image is never re-analysed. Runs BEFORE the aggregation loop so
    # its semantics actually FEED the historic writers below (place fallback for
    # routines/moves, activities/locations in the summary), with provenance.
    reuse = reuse_deep_vision_outputs(
        person_id=person_id,
        package_date=package_date,
        day_start=day_start,
        day_end=day_end,
        live_session_id=live_session_id,
        db_path=db_path,
    )
    deep_semantics = list(reuse.get("semantics") or [])
    deep_place_by_frame: dict[str, dict[str, Any]] = {}
    for sem in deep_semantics:
        fid = str(sem.get("frame_id") or "").strip()
        hint = str(sem.get("location_hint") or "").strip()
        if fid and hint and fid not in deep_place_by_frame:
            deep_place_by_frame[fid] = {
                "place": hint.lower(),
                "deep_observation_id": sem.get("deep_observation_id"),
            }

    def _deep_place_for(ev: dict[str, Any]) -> dict[str, Any] | None:
        """Validated Deep Vision location for the frame this event points at."""
        fid = frame_id_from_evidence(ev.get("evidence_refs_json"))
        return deep_place_by_frame.get(fid) if fid else None

    # Build last-seen map from prior events.
    last_seen: dict[str, dict[str, Any]] = {}
    for ev in prior:
        ek = _entity_key(ev)
        if ek:
            last_seen[ek] = {"place": _place_key(ev), "event": ev}

    move_events: list[dict[str, Any]] = []
    routine_counts: dict[tuple[str, str, str], dict[str, Any]] = {}

    for ev in day_events:
        if str(ev.get("event_type")) == "object_moved":
            continue
        ek = _entity_key(ev)
        pk = _place_key(ev)
        # Deep Vision location fallback: an event with no live place hint but a
        # validated VLM location for its frame gets that place, with provenance.
        deep_place = None
        if pk is None:
            deep_place = _deep_place_for(ev)
            if deep_place:
                pk = deep_place["place"]
        if ek is None:
            continue
        # Spatial routine accumulation.
        if pk:
            slot = _time_slot(ev.get("occurred_at"))
            rk = (ek, pk, slot)
            bucket = routine_counts.setdefault(rk, {"count": 0, "refs": [], "first": ev.get("occurred_at"), "last": ev.get("occurred_at")})
            bucket["count"] += 1
            bucket["last"] = ev.get("occurred_at")
            if len(bucket["refs"]) < 20:
                bucket["refs"].append({"source_table": "visual_events_v19", "source_id": ev["visual_event_id"]})
                if deep_place:
                    bucket["refs"].append({
                        "source_table": "brainlive_deep_vision_observations_v161",
                        "source_id": deep_place.get("deep_observation_id"),
                        "reuse": "deep_vision_location_hint",
                    })
        # Move detection vs prior last-seen.
        prev = last_seen.get(ek)
        if prev is not None and prev.get("place") and pk and prev["place"] != pk:
            move_events.append({"entity_key": ek, "from": prev, "to": ev})
        # Update last-seen.
        last_seen[ek] = {"place": pk, "event": ev}

    inferred_ids: list[str] = []
    routine_ids: list[str] = []
    with connect(db_path) as con, write_transaction(con):
        for mv in move_events:
            from_ev = mv["from"]["event"]
            to_ev = mv["to"]
            refs = [
                {"source_table": "visual_events_v19", "source_id": from_ev["visual_event_id"]},
                {"source_table": "visual_events_v19", "source_id": to_ev["visual_event_id"]},
            ]
            move_id = stable_id("v19move", person_id, from_ev["visual_event_id"], to_ev["visual_event_id"])
            wrote = insert_only(
                con,
                "visual_events_v19",
                {
                    "visual_event_id": move_id,
                    "person_id": person_id,
                    "live_session_id": to_ev.get("live_session_id") or (live_session_id or ""),
                    "event_type": "object_moved",
                    "occurred_at": to_ev.get("occurred_at") or now,
                    "entity_json": to_ev.get("entity_json") or "{}",
                    "observation_json": json_dumps({
                        "from_place": mv["from"].get("place"),
                        "to_place": _place_key(to_ev),
                        "from_event_id": from_ev["visual_event_id"],
                        "to_event_id": to_ev["visual_event_id"],
                    }),
                    "place_json": to_ev.get("place_json") or "{}",
                    "truth_level": "inferred",
                    "confidence": 0.6,
                    "evidence_refs_json": json_dumps(refs),
                    "provenance_json": json_dumps({"models": ["v19_visual_consolidation"]}),
                    "asset_id": None,
                    "created_at": now,
                },
                on_conflict="ignore",
            )
            if wrote:
                inferred_ids.append(move_id)

        for (ek, pk, slot), bucket in routine_counts.items():
            if bucket["count"] < SPATIAL_ROUTINE_MIN_OCCURRENCES:
                continue
            rid = stable_id("spatroutine", person_id, ek, pk, slot)
            existing = con.execute(
                "SELECT occurrence_count, first_observed, created_at FROM brain2_spatial_routine_models WHERE routine_id=?",
                (rid,),
            ).fetchone()
            first_observed = existing["first_observed"] if existing and existing["first_observed"] else bucket["first"]
            created_at = existing["created_at"] if existing else now
            upsert(
                con,
                "brain2_spatial_routine_models",
                {
                    "routine_id": rid,
                    "person_id": person_id,
                    "live_session_id": live_session_id,
                    "entity_key": ek,
                    "place_key": pk,
                    "time_slot": slot,
                    "occurrence_count": int(bucket["count"]),
                    "confidence": min(1.0, 0.5 + 0.1 * int(bucket["count"])),
                    "evidence_refs_json": json_dumps(bucket["refs"]),
                    "first_observed": first_observed,
                    "last_observed": bucket["last"],
                    "updated_at": now,
                    "created_at": created_at,
                },
                "routine_id",
            )
            routine_ids.append(rid)

    summary_id = None
    if day_events:
        # The validated VLM semantics FEED the historic summary (activities and
        # locations actually observed, each traceable), not just counters.
        observed_activities: list[str] = []
        deep_locations: list[str] = []
        for sem in deep_semantics:
            act = str(sem.get("observed_activity") or "").strip()
            loc = str(sem.get("location_hint") or "").strip()
            if act and act not in observed_activities:
                observed_activities.append(act)
            if loc and loc not in deep_locations:
                deep_locations.append(loc)
        evidence_refs = [
            {"source_table": "visual_events_v19", "source_id": r["visual_event_id"]} for r in day_events[:20]
        ] + [
            {
                "source_table": "brainlive_deep_vision_observations_v161",
                "source_id": sem.get("deep_observation_id"),
                "reuse": "validated_vlm_semantics",
            }
            for sem in deep_semantics[:20]
            if sem.get("deep_observation_id")
        ]
        summary_id = store_scene_summary(
            {
                "memory_owner_id": person_id,
                "live_session_id": live_session_id or day_events[-1]["live_session_id"],
                "summary_start": day_events[0]["occurred_at"],
                "summary_end": day_events[-1]["occurred_at"],
                "summary": {
                    "event_count": len(day_events),
                    "event_types": sorted({r["event_type"] for r in day_events}),
                    "entities_last_seen": {k: v.get("place") for k, v in last_seen.items()},
                    "object_moves": len(inferred_ids),
                    "spatial_routines": len(routine_ids),
                    "deep_vision_reused": reuse.get("reused", 0),
                    "deep_vision_reused_with_position": reuse.get("with_position", 0),
                    "observed_activities": observed_activities,
                    "deep_vision_locations": deep_locations,
                },
                "evidence_refs": evidence_refs,
            },
            db_path=db_path,
        )

    return {
        "status": "completed",
        "stage": "visual_consolidation",
        "summary_id": summary_id,
        "visual_event_count": len(day_events),
        "object_moved_count": len(inferred_ids),
        "spatial_routine_count": len(routine_ids),
        "deep_vision_reuse": reuse,
        "package_date": package_date,
    }
