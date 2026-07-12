"""E64-B read-only loaders - real evidence tables -> rows + EvidenceRefs.

These functions ONLY read. They never create, alter or delete rows in the
evidence tables. They map the real close-day schema (verified against the live
17MB memory.db) into plain dicts for the atom builders and into ``EvidenceRef``
handles for the coverage manifest.

Verified source tables:
- ``vision_scene_observations`` (observation_id PK, frame_id, live_session_id,
  objects_json, people_count, visible_text_json, scene_summary, created_at).
- ``brainlive_audio_segments_v154`` (segment_id PK, live_session_id, person_id,
  transcript_text, start_s/end_s, absolute_start/end, source_path, created_at).
"""

from __future__ import annotations

from typing import Any, Sequence

from .evidence_ref import EvidenceRef, make_ref

VISION_OBS_TABLE = "vision_scene_observations"
AUDIO_SEG_TABLE = "brainlive_audio_segments_v154"


def _rows(con: Any, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    cur = con.execute(sql, tuple(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_vision_observations(
    con: Any, *, live_session_id: str
) -> list[dict[str, Any]]:
    """Raw scene observations for one BrainLive session, oldest first."""
    return _rows(
        con,
        f"""SELECT * FROM {VISION_OBS_TABLE}
            WHERE live_session_id=?
            ORDER BY created_at, observation_id""",
        [live_session_id],
    )


def load_audio_segments(con: Any, *, live_session_id: str) -> list[dict[str, Any]]:
    """Diarised audio segments for one BrainLive session, oldest first."""
    return _rows(
        con,
        f"""SELECT * FROM {AUDIO_SEG_TABLE}
            WHERE live_session_id=?
            ORDER BY absolute_start, segment_id""",
        [live_session_id],
    )


def vision_observation_refs(
    rows: Sequence[dict[str, Any]], *, person_id: str | None = None
) -> list[EvidenceRef]:
    """One EvidenceRef per raw scene observation (the expected-coverage set)."""
    refs: list[EvidenceRef] = []
    for obs in rows:
        pk = str(obs.get("observation_id") or "")
        if not pk:
            continue
        refs.append(
            make_ref(
                source_table=VISION_OBS_TABLE,
                source_pk=pk,
                modality="vision",
                payload_kind="scene_observation",
                payload=obs,
                timestamp=str(obs.get("created_at") or "") or None,
                person_id=person_id,
            )
        )
    return refs


def audio_segment_refs(
    rows: Sequence[dict[str, Any]], *, person_id: str | None = None
) -> list[EvidenceRef]:
    """One EvidenceRef per raw audio segment."""
    refs: list[EvidenceRef] = []
    for seg in rows:
        pk = str(seg.get("segment_id") or "")
        if not pk:
            continue
        refs.append(
            make_ref(
                source_table=AUDIO_SEG_TABLE,
                source_pk=pk,
                modality="audio",
                payload_kind="audio_segment",
                payload=seg,
                timestamp=str(seg.get("absolute_start") or "") or None,
                person_id=(seg.get("person_id") or person_id),
            )
        )
    return refs
