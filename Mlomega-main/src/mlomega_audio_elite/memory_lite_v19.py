from __future__ import annotations

"""Fast, owner-centred CloseDay profile.

``full`` remains the reference cognitive pipeline.  This module is a separate
profile which preserves every live transcript as canonical evidence, groups it
into bounded coherent episodes, and pays for one semantic extraction per
episode.  It deliberately does not call or impersonate the V13/V14/V15 engine
chain.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .db import connect, init_db, upsert, write_transaction
from .llm import OllamaJsonClient
from .utils import json_dumps, json_loads, now_iso, stable_id


VERSION = "19.0-memory-lite-1"
MAX_EPISODE_SECONDS = 20 * 60
MAX_EPISODE_CHARS = 48_000
GAP_SECONDS = 4 * 60

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS memory_lite_close_day_runs_v19(
  run_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  status TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  episode_count INTEGER NOT NULL DEFAULT 0,
  fact_count INTEGER NOT NULL DEFAULT 0,
  relationship_count INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL DEFAULT '{}',
  error_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(person_id,package_date,live_session_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_lite_run_owner_day_v19
  ON memory_lite_close_day_runs_v19(person_id,package_date,status);

CREATE TABLE IF NOT EXISTS memory_lite_facts_v19(
  fact_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  live_session_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  episode_id TEXT,
  fact_kind TEXT NOT NULL,
  statement TEXT NOT NULL,
  subject_person_id TEXT,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  occurred_at TEXT,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  activation_contexts_json TEXT NOT NULL DEFAULT '[]',
  live_use_json TEXT NOT NULL DEFAULT '{}',
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_lite_fact_owner_kind_v19
  ON memory_lite_facts_v19(person_id,fact_kind,updated_at);

CREATE TABLE IF NOT EXISTS v18_conversation_scopes(
  conversation_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(conversation_id,person_id)
);

CREATE TABLE IF NOT EXISTS brainlive_personal_model_exports(
  export_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  live_session_id TEXT,
  active_people_json TEXT DEFAULT '[]',
  place_hint TEXT,
  topic_hint TEXT,
  source_counts_json TEXT DEFAULT '{}',
  raw_feed_json TEXT DEFAULT '{}',
  live_ready_json TEXT DEFAULT '{}',
  status TEXT NOT NULL,
  llm_model TEXT,
  error_text TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brainlive_live_relevance_index(
  index_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  export_id TEXT,
  live_session_id TEXT,
  index_type TEXT NOT NULL,
  key TEXT NOT NULL,
  summary TEXT NOT NULL,
  activation_contexts_json TEXT DEFAULT '[]',
  live_use_json TEXT DEFAULT '{}',
  evidence_json TEXT DEFAULT '[]',
  counter_evidence_json TEXT DEFAULT '[]',
  confidence REAL DEFAULT 0.5,
  status TEXT DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blpm_exports_person_time
  ON brainlive_personal_model_exports(person_id,created_at);
CREATE INDEX IF NOT EXISTS idx_blpm_index_person_type
  ON brainlive_live_relevance_index(person_id,index_type,status,confidence);
"""


LITE_SCHEMA: dict[str, Any] = {
    "episode": {
        "title": "",
        "topic": "",
        "summary": "",
        "outcome": "",
        "unresolved": "",
        "confidence": 0.0,
    },
    "subthemes": [
        {"title": "", "summary": "", "turn_ids": [], "confidence": 0.0}
    ],
    "owner_memories": [
        {
            "kind": "event|place|goal|preference|routine|expression|emotion|identity|fact",
            "statement": "",
            "confidence": 0.0,
            "status": "observed|watch",
            "evidence_refs": [],
            "activation_contexts": [],
            "live_use": "",
        }
    ],
    "relationships": [
        {
            "other_person_id": "",
            "summary": "",
            "owner_response": "",
            "other_response": "",
            "recurring_topics": [],
            "confidence": 0.0,
            "evidence_refs": [],
        }
    ],
    "live_hooks": [
        {
            "kind": "watch|suggestion",
            "summary": "",
            "activation_contexts": [],
            "recommended_action": "",
            "confidence": 0.0,
            "evidence_refs": [],
        }
    ],
}


_SYSTEM = """Tu compiles une mémoire personnelle factuelle et directement utile.
Le propriétaire est {owner_name} (person_id={person_id}). Le centre de chaque
analyse est: ce que {owner_name} dit, fait, choisit, cherche, ressent explicitement
ou montre par une réaction observable; puis comment les autres personnes
interagissent avec lui. Les autres restent modélisés quand cela aide sa relation.

Règles absolues:
- aucune psychologie générique et aucun remplissage de champ;
- une seule occurrence ne devient jamais une habitude: status=watch;
- observed exige une preuve positive explicite; non observé reste inconnu;
- chaque mémoire, relation et hook cite uniquement les evidence_refs fournies;
- distinguer parole, action probable T1, texte OCR, vision et constat Sherlock;
- une action T1 probable ne devient pas certaine sans corroboration;
- résumer sans perdre dates, personnes, prix, décisions, promesses et issues;
- JSON strict selon le schéma."""


@dataclass(frozen=True)
class LiteSegment:
    index: int
    start_at: str
    end_at: str
    turns: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]


def ensure_memory_lite_schema(db_path: Path | None = None) -> None:
    init_db(db_path)
    with connect(db_path) as con, write_transaction(con):
        con.executescript(SCHEMA)


def _table_exists(con: Any, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _clean_list(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _owner_name(con: Any, person_id: str) -> str:
    row = con.execute(
        """SELECT display_name FROM speaker_profiles
           WHERE person_id=? OR is_user=1
           ORDER BY CASE WHEN person_id=? THEN 0 ELSE 1 END, created_at LIMIT 1""",
        (person_id, person_id),
    ).fetchone()
    return str(row["display_name"]).strip() if row and row["display_name"] else "William"


def _load_turns(con: Any, live_session_id: str) -> list[dict[str, Any]]:
    if not _table_exists(con, "brainlive_turn_buffer"):
        return []
    rows = con.execute(
        """SELECT * FROM brainlive_turn_buffer
           WHERE live_session_id=? AND is_final=1
             AND TRIM(COALESCE(text_final,text_partial,''))<>''
           ORDER BY COALESCE(timestamp_start,created_at),created_at,live_turn_id""",
        (live_session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _meaningful_prelude(con: Any, *, person_id: str, live_session_id: str) -> list[dict[str, Any]]:
    """Return bounded, evidenced Prelude facts; decorative/UI telemetry is excluded."""

    out: list[dict[str, Any]] = []

    def add(table: str, pk: str, occurred: str, statement: str, confidence: Any, row: Mapping[str, Any]) -> None:
        sid = str(row.get(pk) or "").strip()
        text = str(statement or "").strip()
        if not sid or not text:
            return
        out.append(
            {
                "ref": f"{table}:{sid}",
                "source_table": table,
                "source_id": sid,
                "occurred_at": str(row.get(occurred) or ""),
                "statement": text[:700],
                "confidence": _clamp(confidence),
                "truth_level": str(row.get("truth_level") or "observed"),
            }
        )

    if _table_exists(con, "live_action_candidates_v19"):
        rows = con.execute(
            """SELECT * FROM live_action_candidates_v19
               WHERE person_id=? AND live_session_id=? AND confidence>=0.55
               ORDER BY ended_at LIMIT 160""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            subject = str(row.get("subject_label") or "quelqu'un")
            obj = str(row.get("object_label") or "").strip()
            statement = f"action probable: {subject} {row.get('action_type')}"
            if obj:
                statement += f" {obj}"
            add("live_action_candidates_v19", "action_event_id", "ended_at", statement, row.get("confidence"), row)

    if _table_exists(con, "world_text_observations_v19"):
        rows = con.execute(
            """SELECT * FROM world_text_observations_v19
               WHERE person_id=? AND live_session_id=? AND confidence>=0.60
               ORDER BY observed_at LIMIT 120""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            category = str(row.get("category") or "world_text")
            # Generic OCR noise is not memory. Prices, addresses, notices,
            # medicine/legal text and explicitly located text are useful.
            if (
                category == "world_text"
                and row.get("numeric_value") is None
                and not row.get("place_key")
            ):
                continue
            statement = f"{category}: {row.get('text')}"
            if row.get("place_key"):
                statement += f" (lieu: {row.get('place_key')})"
            add("world_text_observations_v19", "text_observation_id", "observed_at", statement, row.get("confidence"), row)

    if _table_exists(con, "visual_events_v19"):
        rows = con.execute(
            """SELECT * FROM visual_events_v19
               WHERE person_id=? AND live_session_id=? AND confidence>=0.50
               ORDER BY occurred_at LIMIT 160""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            event_type = str(row.get("event_type") or "")
            if event_type not in {
                "change_appeared", "change_disappeared", "change_moved",
                "entity_last_seen", "deep_vision_observation", "place_observed",
            }:
                continue
            entity = json_loads(row.get("entity_json"), {}) or {}
            observation = json_loads(row.get("observation_json"), {}) or {}
            label = entity.get("label") or entity.get("entity_label") or observation.get("label") or ""
            summary = observation.get("summary") or observation.get("text") or ""
            statement = " ".join(part for part in (event_type, str(label), str(summary)) if part)
            add("visual_events_v19", "visual_event_id", "occurred_at", statement, row.get("confidence"), row)

    if _table_exists(con, "brainlive_world_states"):
        rows = con.execute(
            """SELECT * FROM brainlive_world_states
               WHERE person_id=? AND live_session_id=? AND confidence>=0.45
               ORDER BY state_time LIMIT 120""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            place = str(row.get("where_am_i") or "").strip()
            activity = str(row.get("what_is_happening") or "").strip()
            if not place and not activity:
                continue
            statement = " ; ".join(
                item for item in (f"lieu: {place}" if place else "", activity) if item
            )
            add(
                "brainlive_world_states",
                "world_state_id",
                "state_time",
                statement,
                row.get("confidence"),
                row,
            )

    if _table_exists(con, "scene_session_summaries_v19"):
        rows = con.execute(
            """SELECT * FROM scene_session_summaries_v19
               WHERE person_id=? AND live_session_id=?
               ORDER BY summary_start LIMIT 60""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            summary = json_loads(row.get("summary_json"), {}) or {}
            text = (
                str(summary.get("summary") or summary.get("activity") or "").strip()
                if isinstance(summary, Mapping) else ""
            )
            place = str(row.get("place_hint") or "").strip()
            statement = " ; ".join(
                item for item in (f"lieu: {place}" if place else "", text) if item
            )
            if statement:
                add(
                    "scene_session_summaries_v19",
                    "scene_summary_id",
                    "summary_start",
                    statement,
                    row.get("map_quality") or 0.5,
                    row,
                )

    if _table_exists(con, "sherlock_findings_v19"):
        rows = con.execute(
            """SELECT f.* FROM sherlock_findings_v19 f
               JOIN sherlock_sessions_v19 s
                 ON s.sherlock_session_id=f.sherlock_session_id
               WHERE f.person_id=? AND s.live_session_id=?
                 AND f.status NOT IN ('rejected','invalid')
                 AND f.confidence>=0.50
               ORDER BY f.observed_at LIMIT 80""",
            (person_id, live_session_id),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            add("sherlock_findings_v19", "finding_id", "observed_at", row.get("statement"), row.get("confidence"), row)

    # Stable ordering is part of the input digest and resume contract.
    out.sort(key=lambda item: (item.get("occurred_at") or "", item["ref"]))
    return out


def _seconds_between(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    ldt = _iso(left.get("timestamp_start") or left.get("created_at"))
    rdt = _iso(right.get("timestamp_start") or right.get("created_at"))
    return (rdt - ldt).total_seconds() if ldt and rdt else 0.0


def _segments(turns: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[LiteSegment]:
    if not turns:
        return []
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    chars = 0
    start_dt: datetime | None = None
    prior: dict[str, Any] | None = None
    for turn in turns:
        when = _iso(turn.get("timestamp_start") or turn.get("created_at"))
        text = str(turn.get("text_final") or turn.get("text_partial") or "")
        duration = (when - start_dt).total_seconds() if when and start_dt else 0.0
        gap = _seconds_between(prior, turn) if prior else 0.0
        conversation_changed = bool(
            current
            and turn.get("conversation_id")
            and current[-1].get("conversation_id")
            and turn.get("conversation_id") != current[-1].get("conversation_id")
        )
        if current and (
            gap > GAP_SECONDS
            or duration > MAX_EPISODE_SECONDS
            or chars + len(text) > MAX_EPISODE_CHARS
            or conversation_changed
        ):
            chunks.append(current)
            current = []
            chars = 0
            start_dt = when
        if not current:
            start_dt = when
        current.append(turn)
        chars += len(text)
        prior = turn
    if current:
        chunks.append(current)

    segments: list[LiteSegment] = []
    for index, chunk in enumerate(chunks):
        start = str(chunk[0].get("timestamp_start") or chunk[0].get("created_at") or "")
        end = str(chunk[-1].get("timestamp_end") or chunk[-1].get("created_at") or start)
        start_dt = _iso(start)
        end_dt = _iso(end)
        attached: list[dict[str, Any]] = []
        for item in evidence:
            when = _iso(item.get("occurred_at"))
            if when is None or start_dt is None or end_dt is None:
                continue
            if start_dt.timestamp() - 30 <= when.timestamp() <= end_dt.timestamp() + 30:
                attached.append(item)
        segments.append(
            LiteSegment(
                index=index,
                start_at=start,
                end_at=end,
                turns=tuple(chunk),
                evidence=tuple(attached),
            )
        )
    return segments


def _segment_payload(segment: LiteSegment, *, owner_name: str, person_id: str) -> dict[str, Any]:
    return {
        "owner": {"person_id": person_id, "display_name": owner_name},
        "window": {"start": segment.start_at, "end": segment.end_at},
        "turns": [
            {
                "ref": f"brainlive_turn_buffer:{turn['live_turn_id']}",
                "turn_id": str(turn["live_turn_id"]),
                "at": turn.get("timestamp_start") or turn.get("created_at"),
                "speaker_person_id": turn.get("speaker_person_id"),
                "speaker_label": turn.get("speaker_label"),
                "speaker_confidence": _clamp(turn.get("speaker_confidence"), 0.0),
                "asr_confidence": _clamp(turn.get("asr_confidence"), 0.0),
                "text": str(turn.get("text_final") or turn.get("text_partial") or ""),
            }
            for turn in segment.turns
        ],
        "additional_evidence": list(segment.evidence),
    }


def _default_analyse(
    payload: Mapping[str, Any], *, owner_name: str, person_id: str
) -> dict[str, Any]:
    client = OllamaJsonClient()
    return client.require_json(
        _SYSTEM.format(owner_name=owner_name, person_id=person_id),
        json_dumps(payload),
        schema_hint=LITE_SCHEMA,
        timeout=float(os.environ.get("MLOMEGA_MEMORY_LITE_TIMEOUT_S", "360")),
        max_output_tokens=int(os.environ.get("MLOMEGA_MEMORY_LITE_OUTPUT_TOKENS", "3200")),
    )


def _normalise_analysis(
    raw: Mapping[str, Any],
    *,
    allowed_refs: set[str],
    fallback_title: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeError("memory_lite analysis returned a non-object")
    episode = raw.get("episode")
    if not isinstance(episode, Mapping) or not str(episode.get("summary") or "").strip():
        raise RuntimeError("memory_lite analysis missing episode.summary")

    def refs(value: Any) -> list[str]:
        return [ref for ref in _clean_list(value, limit=30) if ref in allowed_refs]

    subthemes: list[dict[str, Any]] = []
    for item in raw.get("subthemes") or []:
        if not isinstance(item, Mapping):
            continue
        turn_ids = []
        for turn_id in _clean_list(item.get("turn_ids"), limit=30):
            ref = f"brainlive_turn_buffer:{turn_id}"
            if ref in allowed_refs:
                turn_ids.append(turn_id)
        if str(item.get("summary") or "").strip() and turn_ids:
            subthemes.append(
                {
                    "title": str(item.get("title") or "Sous-thème")[:160],
                    "summary": str(item.get("summary"))[:1200],
                    "turn_ids": turn_ids,
                    "confidence": _clamp(item.get("confidence")),
                }
            )

    memories: list[dict[str, Any]] = []
    allowed_kinds = {
        "event", "place", "goal", "preference", "routine",
        "expression", "emotion", "identity", "fact",
    }
    for item in raw.get("owner_memories") or []:
        if not isinstance(item, Mapping):
            continue
        evidence_refs = refs(item.get("evidence_refs"))
        statement = str(item.get("statement") or "").strip()
        kind = str(item.get("kind") or "fact").lower()
        if statement and evidence_refs and kind in allowed_kinds:
            status = str(item.get("status") or "watch").lower()
            if status not in {"observed", "watch"}:
                status = "watch"
            if kind in {"routine", "preference", "emotion", "identity", "expression"}:
                # One bounded episode cannot prove a repeated pattern.
                status = "watch"
            if all(ref.startswith("live_action_candidates_v19:") for ref in evidence_refs):
                # T1 is explicitly a probable action candidate. It can support
                # an observed fact only after a second, independent modality.
                status = "watch"
            memories.append(
                {
                    "kind": kind,
                    "statement": statement[:1200],
                    "confidence": _clamp(item.get("confidence")),
                    "status": status,
                    "evidence_refs": evidence_refs,
                    "activation_contexts": _clean_list(item.get("activation_contexts"), limit=8),
                    "live_use": str(item.get("live_use") or "")[:500],
                }
            )

    relationships: list[dict[str, Any]] = []
    for item in raw.get("relationships") or []:
        if not isinstance(item, Mapping):
            continue
        other = str(item.get("other_person_id") or "").strip()
        evidence_refs = refs(item.get("evidence_refs"))
        summary = str(item.get("summary") or "").strip()
        if other and summary and evidence_refs:
            relationships.append(
                {
                    "other_person_id": other[:160],
                    "summary": summary[:1200],
                    "owner_response": str(item.get("owner_response") or "")[:700],
                    "other_response": str(item.get("other_response") or "")[:700],
                    "recurring_topics": _clean_list(item.get("recurring_topics"), limit=8),
                    "confidence": _clamp(item.get("confidence")),
                    "evidence_refs": evidence_refs,
                }
            )

    hooks: list[dict[str, Any]] = []
    for item in raw.get("live_hooks") or []:
        if not isinstance(item, Mapping):
            continue
        evidence_refs = refs(item.get("evidence_refs"))
        summary = str(item.get("summary") or "").strip()
        if summary and evidence_refs:
            hooks.append(
                {
                    "kind": "suggestion" if str(item.get("kind")) == "suggestion" else "watch",
                    "summary": summary[:900],
                    "activation_contexts": _clean_list(item.get("activation_contexts"), limit=8),
                    "recommended_action": str(item.get("recommended_action") or "")[:500],
                    "confidence": _clamp(item.get("confidence")),
                    "evidence_refs": evidence_refs,
                }
            )

    return {
        "episode": {
            "title": str(episode.get("title") or fallback_title)[:200],
            "topic": str(episode.get("topic") or "")[:200],
            "summary": str(episode.get("summary"))[:3000],
            "outcome": str(episode.get("outcome") or "")[:1000],
            "unresolved": str(episode.get("unresolved") or "")[:1000],
            "confidence": _clamp(episode.get("confidence")),
        },
        "subthemes": subthemes,
        "owner_memories": memories,
        "relationships": relationships,
        "live_hooks": hooks,
    }


def _materialise_conversation(
    con: Any,
    *,
    person_id: str,
    live_session_id: str,
    package_date: str,
    turns: list[dict[str, Any]],
) -> tuple[str, dict[str, str]]:
    now = now_iso()
    conversation_id = stable_id("memory_lite_conversation", person_id, live_session_id)
    participants = sorted(
        {
            str(turn.get("speaker_person_id") or turn.get("speaker_label") or "").strip()
            for turn in turns
            if str(turn.get("speaker_person_id") or turn.get("speaker_label") or "").strip()
        }
    )
    con.execute(
        """INSERT INTO conversations(
             conversation_id,title,started_at,ended_at,topic,channel,
             participants_json,speaker_map_json,relationship_context_json,
             source_asset_id,raw_json,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(conversation_id) DO UPDATE SET
             started_at=excluded.started_at,ended_at=excluded.ended_at,
             participants_json=excluded.participants_json,raw_json=excluded.raw_json""",
        (
            conversation_id,
            f"Memory Lite {package_date}",
            turns[0].get("timestamp_start") or turns[0].get("created_at"),
            turns[-1].get("timestamp_end") or turns[-1].get("created_at"),
            "memory_lite_owner_day",
            "memory_lite_v19",
            json_dumps(participants),
            "{}",
            "{}",
            None,
            json_dumps(
                {
                    "memory_profile": "lite",
                    "live_session_id": live_session_id,
                    "source_table": "brainlive_turn_buffer",
                    "lossless_turn_count": len(turns),
                }
            ),
            now,
        ),
    )
    con.execute(
        """INSERT INTO v18_conversation_scopes(
             conversation_id,person_id,evidence_kind,evidence_json,active,created_at,updated_at)
           VALUES(?,?,'turn_owner',?,1,?,?)
           ON CONFLICT(conversation_id,person_id) DO UPDATE SET
             evidence_kind=excluded.evidence_kind,evidence_json=excluded.evidence_json,
             active=1,updated_at=excluded.updated_at""",
        (
            conversation_id,
            person_id,
            json_dumps({"live_session_id": live_session_id, "profile": "lite"}),
            now,
            now,
        ),
    )
    turn_map: dict[str, str] = {}
    start_dt = _iso(turns[0].get("timestamp_start") or turns[0].get("created_at"))
    for idx, source in enumerate(turns):
        source_id = str(source["live_turn_id"])
        turn_id = stable_id("memory_lite_turn", person_id, live_session_id, source_id)
        turn_map[source_id] = turn_id
        at = _iso(source.get("timestamp_start") or source.get("created_at"))
        end = _iso(source.get("timestamp_end") or source.get("created_at"))
        start_s = max(0.0, (at - start_dt).total_seconds()) if at and start_dt else float(idx)
        end_s = max(start_s, (end - start_dt).total_seconds()) if end and start_dt else start_s
        con.execute(
            """INSERT INTO turns(
                 turn_id,conversation_id,idx,speaker_label,person_id,start_s,end_s,
                 text,previous_turn_id,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(turn_id) DO UPDATE SET
                 speaker_label=excluded.speaker_label,person_id=excluded.person_id,
                 text=excluded.text,metadata_json=excluded.metadata_json""",
            (
                turn_id,
                conversation_id,
                idx,
                source.get("speaker_label"),
                source.get("speaker_person_id"),
                start_s,
                end_s,
                str(source.get("text_final") or source.get("text_partial") or ""),
                turn_map.get(str(turns[idx - 1]["live_turn_id"])) if idx else None,
                json_dumps(
                    {
                        "source_table": "brainlive_turn_buffer",
                        "source_id": source_id,
                        "live_session_id": live_session_id,
                        "timestamp_start": source.get("timestamp_start"),
                        "timestamp_end": source.get("timestamp_end"),
                        "speaker_confidence": source.get("speaker_confidence"),
                        "asr_confidence": source.get("asr_confidence"),
                        "memory_profile": "lite",
                    }
                ),
            ),
        )
    return conversation_id, turn_map


def _dimension(kind: str) -> str:
    return {
        "event": "events",
        "place": "places",
        "goal": "goals",
        "preference": "preferences",
        "routine": "routines",
        "expression": "language_personal",
        "emotion": "emotions",
        "identity": "identity",
        "fact": "facts",
    }.get(kind, "facts")


def _persist(
    *,
    db_path: Path | None,
    run_id: str,
    person_id: str,
    live_session_id: str,
    package_date: str,
    owner_name: str,
    turns: list[dict[str, Any]],
    segments: list[LiteSegment],
    analyses: list[dict[str, Any]],
    input_digest: str,
) -> dict[str, Any]:
    from .v19_life_model_store import apply_life_model_delta, ensure_life_model_store

    ensure_life_model_store(db_path)
    now = now_iso()
    episode_ids: list[str] = []
    facts: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    hooks: list[dict[str, Any]] = []
    with connect(db_path) as con, write_transaction(con):
        con.executescript(SCHEMA)
        conversation_id, turn_map = _materialise_conversation(
            con,
            person_id=person_id,
            live_session_id=live_session_id,
            package_date=package_date,
            turns=turns,
        )
        for segment, analysis in zip(segments, analyses):
            start_source = str(segment.turns[0]["live_turn_id"])
            end_source = str(segment.turns[-1]["live_turn_id"])
            episode_id = stable_id(
                "memory_lite_episode", person_id, live_session_id, start_source, end_source
            )
            episode_ids.append(episode_id)
            episode = analysis["episode"]
            participants = sorted(
                {
                    str(t.get("speaker_person_id") or t.get("speaker_label") or "").strip()
                    for t in segment.turns
                    if str(t.get("speaker_person_id") or t.get("speaker_label") or "").strip()
                }
            )
            con.execute(
                """INSERT INTO episodes(
                     episode_id,episode_type,source_conversation_id,start_turn_id,end_turn_id,
                     start_time,end_time,participants_json,location_text,channel,topic,
                     situation_summary,trigger_summary,user_state_before_json,
                     speech_or_action_summary,target_person_id,target_reaction_summary,
                     user_state_after_json,outcome_summary,unresolved_tension,truth_status,
                     confidence,importance_score,lifecycle_status,metadata_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(episode_id) DO UPDATE SET
                     topic=excluded.topic,situation_summary=excluded.situation_summary,
                     outcome_summary=excluded.outcome_summary,
                     unresolved_tension=excluded.unresolved_tension,
                     confidence=excluded.confidence,metadata_json=excluded.metadata_json,
                     updated_at=excluded.updated_at""",
                (
                    episode_id,
                    "memory_lite_owner_episode",
                    conversation_id,
                    turn_map[start_source],
                    turn_map[end_source],
                    segment.start_at,
                    segment.end_at,
                    json_dumps(participants),
                    None,
                    "memory_lite_v19",
                    episode["topic"],
                    episode["summary"],
                    None,
                    "{}",
                    episode["summary"],
                    None,
                    None,
                    "{}",
                    episode["outcome"] or None,
                    episode["unresolved"] or None,
                    "observed",
                    episode["confidence"],
                    min(1.0, 0.4 + episode["confidence"] * 0.5),
                    "active",
                    json_dumps(
                        {
                            "profile": "lite",
                            "run_id": run_id,
                            "title": episode["title"],
                            "source_live_turn_ids": [str(t["live_turn_id"]) for t in segment.turns],
                        }
                    ),
                    now,
                    now,
                ),
            )
            for turn in segment.turns:
                source_id = str(turn["live_turn_id"])
                evidence_id = stable_id("memory_lite_episode_evidence", episode_id, source_id)
                con.execute(
                    """INSERT INTO episode_evidence(
                         episode_evidence_id,episode_id,source_span_id,turn_id,evidence_role,
                         evidence_text,confidence,metadata_json,created_at)
                       VALUES(?,?,NULL,?,'transcript',?,?,?,?)
                       ON CONFLICT(episode_evidence_id) DO UPDATE SET
                         evidence_text=excluded.evidence_text,confidence=excluded.confidence,
                         metadata_json=excluded.metadata_json""",
                    (
                        evidence_id,
                        episode_id,
                        turn_map[source_id],
                        str(turn.get("text_final") or turn.get("text_partial") or ""),
                        _clamp(turn.get("asr_confidence"), 0.0),
                        json_dumps({"source_table": "brainlive_turn_buffer", "source_id": source_id}),
                        now,
                    ),
                )
            for ordinal, subtheme in enumerate(analysis["subthemes"]):
                mapped = [turn_map[item] for item in subtheme["turn_ids"] if item in turn_map]
                if not mapped:
                    continue
                subtheme_id = stable_id("memory_lite_subtheme", episode_id, ordinal)
                con.execute(
                    """INSERT INTO episode_subthemes_v19(
                         subtheme_id,episode_id,ordinal,subtheme_type,title,summary,
                         start_turn_id,end_turn_id,participants_json,outcome_summary,
                         unresolved_tension,confidence,metadata_json,created_at,updated_at)
                       VALUES(?,?,?,'other',?,?,?,?,'[]',NULL,NULL,?,?,?,?)
                       ON CONFLICT(subtheme_id) DO UPDATE SET
                         title=excluded.title,summary=excluded.summary,
                         start_turn_id=excluded.start_turn_id,end_turn_id=excluded.end_turn_id,
                         confidence=excluded.confidence,updated_at=excluded.updated_at""",
                    (
                        subtheme_id,
                        episode_id,
                        ordinal,
                        subtheme["title"],
                        subtheme["summary"],
                        mapped[0],
                        mapped[-1],
                        subtheme["confidence"],
                        json_dumps({"profile": "lite", "source_live_turn_ids": subtheme["turn_ids"]}),
                        now,
                        now,
                    ),
                )
            for item in analysis["owner_memories"]:
                fact_id = stable_id(
                    "memory_lite_fact",
                    person_id,
                    item["kind"],
                    item["statement"].casefold(),
                    *item["evidence_refs"],
                )
                row = {**item, "fact_id": fact_id, "episode_id": episode_id}
                facts.append(row)
                con.execute(
                    """INSERT INTO memory_lite_facts_v19(
                         fact_id,person_id,live_session_id,package_date,episode_id,fact_kind,
                         statement,subject_person_id,confidence,status,occurred_at,
                         evidence_refs_json,activation_contexts_json,live_use_json,detail_json,
                         created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(fact_id) DO UPDATE SET
                         confidence=excluded.confidence,status=excluded.status,
                         activation_contexts_json=excluded.activation_contexts_json,
                         live_use_json=excluded.live_use_json,updated_at=excluded.updated_at""",
                    (
                        fact_id,
                        person_id,
                        live_session_id,
                        package_date,
                        episode_id,
                        item["kind"],
                        item["statement"],
                        person_id,
                        item["confidence"],
                        item["status"],
                        segment.start_at,
                        json_dumps(item["evidence_refs"]),
                        json_dumps(item["activation_contexts"]),
                        json_dumps({"summary": item["live_use"]}),
                        json_dumps({"profile": "lite"}),
                        now,
                        now,
                    ),
                )
            for item in analysis["relationships"]:
                relationships.append({**item, "episode_id": episode_id})
                other = item["other_person_id"]
                # Same identity convention as the historical V12 writer, so
                # switching Full/Lite enriches one relation instead of forking it.
                relationship_id = stable_id("rel", sorted([person_id, other]))
                existing = con.execute(
                    "SELECT evidence_count,created_at,metadata_json FROM relationship_models WHERE relationship_id=?",
                    (relationship_id,),
                ).fetchone()
                history = json_loads(existing["metadata_json"], {}) if existing else {}
                if not isinstance(history, dict):
                    history = {}
                observations = history.get("lite_observations")
                if not isinstance(observations, list):
                    observations = []
                observation = {
                    "episode_id": episode_id,
                    "summary": item["summary"],
                    "owner_response": item["owner_response"],
                    "other_response": item["other_response"],
                    "topics": item["recurring_topics"],
                    "evidence_refs": item["evidence_refs"],
                    "at": segment.start_at,
                }
                observations = [entry for entry in observations if entry.get("episode_id") != episode_id]
                observations.append(observation)
                history.update({"memory_profile": "lite", "lite_observations": observations[-30:]})
                con.execute(
                    """INSERT INTO relationship_models(
                         relationship_id,person_a,person_b,relationship_type,trust_level,
                         tension_level,attachment_level,dependency_level,power_balance,
                         conflict_frequency,repair_frequency,communication_style,
                         common_triggers_json,common_loops_json,current_status,evidence_count,
                         confidence,metadata_json,created_at,updated_at)
                       VALUES(?,?,?,'observed_contact',0.5,0.5,0.5,0.5,NULL,0,0,?,
                              '[]','[]','active',?,?,?, ?,?)
                       ON CONFLICT(relationship_id) DO UPDATE SET
                         evidence_count=excluded.evidence_count,
                         confidence=MAX(relationship_models.confidence,excluded.confidence),
                         metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                    (
                        relationship_id,
                        person_id,
                        other,
                        item["summary"],
                        int(existing["evidence_count"] or 0) + 1 if existing else 1,
                        item["confidence"],
                        json_dumps(history),
                        existing["created_at"] if existing else now,
                        now,
                    ),
                )
                interaction_id = stable_id("memory_lite_interaction", episode_id, other)
                con.execute(
                    """INSERT INTO interaction_episodes(
                         interaction_id,episode_id,user_person_id,other_person_id,
                         relationship_type,trust_level,tension_level,dependency_level,
                         message_direction,user_speech_act,other_reaction,user_followup,
                         communication_result,confidence,metadata_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,NULL,NULL,NULL,'bidirectional',?,?,?,?,?,?,?,?)
                       ON CONFLICT(interaction_id) DO UPDATE SET
                         user_speech_act=excluded.user_speech_act,
                         other_reaction=excluded.other_reaction,
                         communication_result=excluded.communication_result,
                         confidence=excluded.confidence,metadata_json=excluded.metadata_json,
                         updated_at=excluded.updated_at""",
                    (
                        interaction_id,
                        episode_id,
                        person_id,
                        other,
                        "observed_contact",
                        item["owner_response"] or None,
                        item["other_response"] or None,
                        None,
                        item["summary"],
                        item["confidence"],
                        json_dumps(
                            {
                                "profile": "lite",
                                "topics": item["recurring_topics"],
                                "evidence_refs": item["evidence_refs"],
                            }
                        ),
                        now,
                        now,
                    ),
                )
            hooks.extend({**item, "episode_id": episode_id} for item in analysis["live_hooks"])

    # Typed Life V19 writes run through its existing revision-aware writer.
    # The journal keeps every occurrence, while the canonical Life identity is
    # statement-based: repeated days strengthen one entry instead of multiplying
    # semantically identical rows.
    for fact in facts:
        with connect(db_path) as con:
            occurrences = [
                dict(row)
                for row in con.execute(
                    """SELECT live_session_id,evidence_refs_json,confidence,status
                       FROM memory_lite_facts_v19
                       WHERE person_id=? AND fact_kind=? AND LOWER(statement)=LOWER(?)""",
                    (person_id, fact["kind"], fact["statement"]),
                ).fetchall()
            ]
        sessions = {str(row["live_session_id"]) for row in occurrences}
        refs: list[str] = []
        for row in occurrences:
            for ref in json_loads(row.get("evidence_refs_json"), []) or []:
                text = str(ref or "").strip()
                if text and text not in refs:
                    refs.append(text)
        pattern_kind = fact["kind"] in {
            "routine", "preference", "emotion", "identity", "expression"
        }
        canonical_status = (
            "confirmed" if pattern_kind and len(sessions) >= 2
            else "watch" if pattern_kind
            else "active"
        )
        canonical_confidence = max(
            [_clamp(row.get("confidence")) for row in occurrences] or [fact["confidence"]]
        )
        if len(sessions) >= 2:
            canonical_confidence = min(1.0, canonical_confidence + 0.05)
        apply_life_model_delta(
            person_id,
            {
                "entry_id": stable_id(
                    "memory_lite_life",
                    person_id,
                    fact["kind"],
                    fact["statement"].casefold(),
                ),
                "dimension": _dimension(fact["kind"]),
                "temporal_axis": "present",
                "statement": fact["statement"],
                "confidence": canonical_confidence,
                "status": canonical_status,
                "evidence_refs": refs,
                "source_table": "memory_lite_facts_v19",
                "source_id": fact["fact_id"],
                "source_updated_at": now,
                "first_observed": segments[0].start_at if segments else now,
                "last_confirmed": now,
                "operation": "upsert",
            },
            db_path=db_path,
        )

    live_ready = _build_live_ready(
        owner_name=owner_name,
        analyses=analyses,
        facts=facts,
        relationships=relationships,
        hooks=hooks,
    )
    export_id = _persist_live_ready(
        db_path=db_path,
        person_id=person_id,
        live_session_id=live_session_id,
        package_date=package_date,
        owner_name=owner_name,
        live_ready=live_ready,
        episode_ids=episode_ids,
        facts=facts,
        relationships=relationships,
    )
    result = {
        "version": VERSION,
        "memory_profile": "lite",
        "run_id": run_id,
        "person_id": person_id,
        "package_date": package_date,
        "live_session_id": live_session_id,
        "status": "completed",
        "input_digest": input_digest,
        "episode_ids": episode_ids,
        "fact_ids": [item["fact_id"] for item in facts],
        "relationship_count": len(relationships),
        "live_ready_export_id": export_id,
        "calls": len(segments),
        "cleanup": {"eligible": True, "profile": "lite"},
    }
    with connect(db_path) as con, write_transaction(con):
        con.execute(
            """UPDATE memory_lite_close_day_runs_v19
               SET status='completed',episode_count=?,fact_count=?,relationship_count=?,
                   result_json=?,error_text=NULL,updated_at=?,completed_at=?
               WHERE run_id=?""",
            (
                len(episode_ids),
                len(facts),
                len(relationships),
                json_dumps(result),
                now,
                now,
                run_id,
            ),
        )
    return result


def _build_live_ready(
    *,
    owner_name: str,
    analyses: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    hooks: list[dict[str, Any]],
) -> dict[str, Any]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_kind.setdefault(fact["kind"], []).append(fact)

    def evidence(item: Mapping[str, Any]) -> list[str]:
        return list(item.get("evidence_refs") or [])

    def fact_rows(kind: str, key: str) -> list[dict[str, Any]]:
        return [
            {
                key: item["statement"],
                "confidence": item["confidence"],
                "status": item["status"],
                "activation_contexts": item["activation_contexts"],
                "evidence": evidence(item),
            }
            for item in by_kind.get(kind, [])
        ]

    identity = by_kind.get("identity", [])
    owner_summary = " | ".join(
        analysis["episode"]["summary"] for analysis in analyses[-3:]
    )[:2400]
    return {
        "identity_model": {
            "who_william_is_operationally": owner_summary,
            "stable_traits": [
                item["statement"] for item in identity if item["status"] == "observed"
            ],
            "current_unknowns": [
                item["statement"] for item in identity if item["status"] == "watch"
            ],
            "confidence": max([item["confidence"] for item in identity] or [0.0]),
            "owner_display_name": owner_name,
        },
        "routines": fact_rows("routine", "name"),
        "places": fact_rows("place", "place"),
        "language_and_expressions": fact_rows("expression", "expression_or_style"),
        "needs_expectations_preferences": (
            fact_rows("goal", "item") + fact_rows("preference", "item")
        ),
        "emotional_state_patterns": fact_rows("emotion", "state_or_pattern"),
        "relationship_live_packs": [
            {
                "person_or_group": item["other_person_id"],
                "known_loops": [item["summary"]],
                "good_moves": [],
                "bad_moves": [],
                "watch_signals": item["recurring_topics"],
                "confidence": item["confidence"],
                "evidence": item["evidence_refs"],
            }
            for item in relationships
        ],
        "forecast_hooks": [
            {
                "forecast": item["summary"],
                "horizon": "H1",
                "activation_conditions": item["activation_contexts"],
                "intervention_options": [item["recommended_action"]]
                if item["recommended_action"] else [],
                "confidence": item["confidence"],
                "evidence": item["evidence_refs"],
            }
            for item in hooks
        ],
        "brainlive_operational_rules": [
            {
                "rule": item["recommended_action"] or item["summary"],
                "when_to_use": item["activation_contexts"],
                "when_not_to_use": [],
                "confidence": item["confidence"],
                "evidence": item["evidence_refs"],
            }
            for item in hooks if item["kind"] == "suggestion"
        ],
        "recent_owner_facts": (
            fact_rows("event", "item") + fact_rows("fact", "item")
        ),
        "missing_for_magic": [],
        "memory_profile": "lite",
    }


def _persist_live_ready(
    *,
    db_path: Path | None,
    person_id: str,
    live_session_id: str,
    package_date: str,
    owner_name: str,
    live_ready: dict[str, Any],
    episode_ids: list[str],
    facts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> str:
    now = now_iso()
    export_id = stable_id("memory_lite_live_ready", person_id, live_session_id, package_date)
    with connect(db_path) as con, write_transaction(con):
        con.executescript(SCHEMA)
        previous = con.execute(
            """SELECT live_ready_json FROM brainlive_personal_model_exports
               WHERE person_id=? AND export_id<>?
               ORDER BY created_at DESC LIMIT 1""",
            (person_id, export_id),
        ).fetchone()
        previous_ready = json_loads(previous["live_ready_json"], {}) if previous else {}
        if isinstance(previous_ready, dict) and previous_ready:
            live_ready = _merge_live_ready(previous_ready, live_ready)
        con.execute(
            """INSERT INTO brainlive_personal_model_exports(
                 export_id,person_id,live_session_id,active_people_json,place_hint,
                 topic_hint,source_counts_json,raw_feed_json,live_ready_json,status,
                 llm_model,error_text,created_at)
               VALUES(?,?,?,?,NULL,NULL,?,?,?,'lite_ready',?,NULL,?)
               ON CONFLICT(export_id) DO UPDATE SET
                 active_people_json=excluded.active_people_json,
                 source_counts_json=excluded.source_counts_json,
                 raw_feed_json=excluded.raw_feed_json,
                 live_ready_json=excluded.live_ready_json,status='lite_ready',
                 llm_model=excluded.llm_model,error_text=NULL,created_at=excluded.created_at""",
            (
                export_id,
                person_id,
                live_session_id,
                json_dumps(sorted({item["other_person_id"] for item in relationships})),
                json_dumps(
                    {
                        "episodes": len(episode_ids),
                        "facts": len(facts),
                        "relationships": len(relationships),
                    }
                ),
                json_dumps(
                    {
                        "memory_profile": "lite",
                        "owner": owner_name,
                        "episode_ids": episode_ids,
                        "fact_ids": [item["fact_id"] for item in facts],
                    }
                ),
                json_dumps(live_ready),
                os.environ.get("MLOMEGA_LLM_BACKEND", "ollama"),
                now,
            ),
        )
        groups = {
            "routine": live_ready.get("routines") or [],
            "place": live_ready.get("places") or [],
            "language_expression": live_ready.get("language_and_expressions") or [],
            "need_expectation_preference": live_ready.get("needs_expectations_preferences") or [],
            "emotional_pattern": live_ready.get("emotional_state_patterns") or [],
            "relationship_live_pack": live_ready.get("relationship_live_packs") or [],
            "forecast_hook": live_ready.get("forecast_hooks") or [],
            "operational_rule": live_ready.get("brainlive_operational_rules") or [],
        }
        for index_type, items in groups.items():
            for ordinal, item in enumerate(items):
                if not isinstance(item, Mapping):
                    continue
                key = str(
                    item.get("name") or item.get("place") or
                    item.get("expression_or_style") or item.get("item") or
                    item.get("state_or_pattern") or item.get("person_or_group") or
                    item.get("forecast") or item.get("rule") or f"{index_type}-{ordinal}"
                )
                summary = str(
                    item.get("future_prediction_use") or item.get("meaning_for_william") or
                    item.get("personal_meaning") or item.get("future_risk_or_need") or
                    item.get("forecast") or item.get("rule") or
                    (item.get("known_loops") or [key])[0] or key
                )
                refs = item.get("evidence") if isinstance(item.get("evidence"), list) else []
                activation = (
                    item.get("activation_contexts") or item.get("watch_signals") or
                    item.get("activation_conditions") or item.get("when_to_use") or []
                )
                index_id = stable_id("memory_lite_live_index", export_id, index_type, key)
                con.execute(
                    """INSERT INTO brainlive_live_relevance_index(
                         index_id,person_id,export_id,live_session_id,index_type,key,
                         summary,activation_contexts_json,live_use_json,evidence_json,
                         counter_evidence_json,confidence,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,? ,?,'[]',?,'active',?,?)
                       ON CONFLICT(index_id) DO UPDATE SET
                         summary=excluded.summary,
                         activation_contexts_json=excluded.activation_contexts_json,
                         live_use_json=excluded.live_use_json,
                         evidence_json=excluded.evidence_json,
                         confidence=excluded.confidence,status='active',
                         updated_at=excluded.updated_at""",
                    (
                        index_id,
                        person_id,
                        export_id,
                        live_session_id,
                        index_type,
                        key[:300],
                        summary[:1500],
                        json_dumps(activation),
                        json_dumps({"memory_profile": "lite"}),
                        json_dumps(refs),
                        _clamp(item.get("confidence")),
                        now,
                        now,
                    ),
                )
    return export_id


def _merge_live_ready(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Carry durable cognition forward without a second synthesis call."""

    merged = dict(current)
    list_sections = {
        "routines": ("name",),
        "places": ("place",),
        "language_and_expressions": ("expression_or_style",),
        "needs_expectations_preferences": ("item",),
        "emotional_state_patterns": ("state_or_pattern",),
        "relationship_live_packs": ("person_or_group",),
        "forecast_hooks": ("forecast",),
        "brainlive_operational_rules": ("rule",),
        "recent_owner_facts": ("item",),
    }
    for section, keys in list_sections.items():
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates = list(current.get(section) or []) + list(previous.get(section) or [])
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            identity = "|".join(str(item.get(key) or "").strip().casefold() for key in keys)
            if not identity:
                identity = hashlib.sha256(json_dumps(dict(item)).encode("utf-8")).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            out.append(dict(item))
            if len(out) >= 80:
                break
        merged[section] = out

    old_identity = previous.get("identity_model")
    new_identity = current.get("identity_model")
    if isinstance(old_identity, Mapping) and isinstance(new_identity, Mapping):
        summaries = [
            str(new_identity.get("who_william_is_operationally") or "").strip(),
            str(old_identity.get("who_william_is_operationally") or "").strip(),
        ]
        merged["identity_model"] = {
            **dict(old_identity),
            **dict(new_identity),
            "who_william_is_operationally": " | ".join(
                item for index, item in enumerate(summaries)
                if item and item not in summaries[:index]
            )[:4000],
            "stable_traits": _clean_list(
                list(new_identity.get("stable_traits") or [])
                + list(old_identity.get("stable_traits") or []),
                limit=80,
            ),
            "current_unknowns": _clean_list(
                list(new_identity.get("current_unknowns") or [])
                + list(old_identity.get("current_unknowns") or []),
                limit=80,
            ),
            "confidence": max(
                _clamp(old_identity.get("confidence"), 0.0),
                _clamp(new_identity.get("confidence"), 0.0),
            ),
        }
    merged["memory_profile"] = "lite"
    return merged


def run_memory_lite_close_day(
    *,
    person_id: str,
    live_session_id: str,
    package_date: str,
    force: bool = False,
    db_path: Path | None = None,
    analyse: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run/resume the independent Lite profile for one sealed live session."""

    if not person_id or not live_session_id or not package_date:
        raise ValueError("memory_lite requires person_id, live_session_id and package_date")
    path = Path(db_path) if db_path is not None else None
    ensure_memory_lite_schema(path)
    run_id = stable_id("memory_lite_close_day", person_id, package_date, live_session_id)
    with connect(path) as con:
        turns = _load_turns(con, live_session_id)
        if not turns:
            raise RuntimeError("memory_lite has no final live transcript to consolidate")
        owner_name = _owner_name(con, person_id)
        prelude = _meaningful_prelude(
            con, person_id=person_id, live_session_id=live_session_id
        )
        input_digest = hashlib.sha256(
            json_dumps(
                {
                    "turns": [
                        (
                            row.get("live_turn_id"),
                            row.get("speaker_person_id"),
                            row.get("text_final") or row.get("text_partial"),
                        )
                        for row in turns
                    ],
                    "prelude": prelude,
                    "version": VERSION,
                }
            ).encode("utf-8")
        ).hexdigest()
        existing = con.execute(
            "SELECT status,input_digest,result_json FROM memory_lite_close_day_runs_v19 WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if (
            existing
            and str(existing["status"]) == "completed"
            and str(existing["input_digest"]) == input_digest
            and not force
        ):
            result = json_loads(existing["result_json"], {}) or {}
            return {**result, "resumed_close_day": True}

    now = now_iso()
    with connect(path) as con, write_transaction(con):
        con.execute(
            """INSERT INTO memory_lite_close_day_runs_v19(
                 run_id,person_id,package_date,live_session_id,status,input_digest,
                 episode_count,fact_count,relationship_count,result_json,error_text,
                 created_at,updated_at,completed_at)
               VALUES(?,?,?,?,'running',?,0,0,0,'{}',NULL,?,?,NULL)
               ON CONFLICT(run_id) DO UPDATE SET
                 status='running',input_digest=excluded.input_digest,error_text=NULL,
                 updated_at=excluded.updated_at,completed_at=NULL""",
            (
                run_id,
                person_id,
                package_date,
                live_session_id,
                input_digest,
                now,
                now,
            ),
        )

    segments = _segments(turns, prelude)
    analyser = analyse or _default_analyse
    workers = 1
    if os.environ.get("MLOMEGA_LLM_BACKEND", "ollama").strip().lower() == "deepseek":
        workers = max(1, min(8, int(os.environ.get("MLOMEGA_MEMORY_LITE_WORKERS", "4"))))

    def one(segment: LiteSegment) -> tuple[int, dict[str, Any]]:
        payload = _segment_payload(
            segment, owner_name=owner_name, person_id=person_id
        )
        allowed_refs = {
            str(item["ref"]) for item in payload["turns"] + payload["additional_evidence"]
        }
        raw = analyser(payload, owner_name=owner_name, person_id=person_id)
        return segment.index, _normalise_analysis(
            raw,
            allowed_refs=allowed_refs,
            fallback_title=f"Épisode {segment.index + 1}",
        )

    try:
        ordered: dict[int, dict[str, Any]] = {}
        if workers > 1 and len(segments) > 1:
            with ThreadPoolExecutor(
                max_workers=min(workers, len(segments)),
                thread_name_prefix="memory-lite",
            ) as pool:
                futures = {pool.submit(one, segment): segment.index for segment in segments}
                for future in as_completed(futures):
                    index, output = future.result()
                    ordered[index] = output
        else:
            for segment in segments:
                index, output = one(segment)
                ordered[index] = output
        analyses = [ordered[index] for index in range(len(segments))]
        return _persist(
            db_path=path,
            run_id=run_id,
            person_id=person_id,
            live_session_id=live_session_id,
            package_date=package_date,
            owner_name=owner_name,
            turns=turns,
            segments=segments,
            analyses=analyses,
            input_digest=input_digest,
        )
    except Exception as exc:
        with connect(path) as con, write_transaction(con):
            con.execute(
                """UPDATE memory_lite_close_day_runs_v19
                   SET status='error',error_text=?,updated_at=? WHERE run_id=?""",
                (f"{type(exc).__name__}: {str(exc)[:1800]}", now_iso(), run_id),
            )
        raise
