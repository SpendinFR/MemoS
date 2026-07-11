from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .db import connect, init_db, upsert, write_transaction
from .utils import json_dumps, json_loads, now_iso, stable_id

DEFAULT_WEAKENING_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS life_model_entries_v19 (
  entry_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  temporal_axis TEXT NOT NULL,
  statement TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  evidence_refs_json TEXT DEFAULT '[]',
  verification_spec_json TEXT DEFAULT '{}',
  prediction_template_json TEXT DEFAULT '{}',
  source_table TEXT,
  source_id TEXT,
  source_updated_at TEXT,
  first_observed TEXT,
  last_confirmed TEXT,
  revision_history_json TEXT DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_life_model_entries_v19_owner ON life_model_entries_v19(person_id, dimension, status);
"""


def ensure_life_model_store(db_path=None) -> None:
    init_db(db_path)
    with connect(db_path) as con, write_transaction(con):
        con.executescript(SCHEMA)
        migrations = {
            "verification_spec_json": "TEXT DEFAULT '{}'",
            "prediction_template_json": "TEXT DEFAULT '{}'",
            "source_table": "TEXT",
            "source_id": "TEXT",
            "source_updated_at": "TEXT",
        }
        for col, ddl in migrations.items():
            try:
                con.execute(f"ALTER TABLE life_model_entries_v19 ADD COLUMN {col} {ddl}")
            except Exception:
                pass
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_life_model_entries_v19_source "
            "ON life_model_entries_v19(person_id,source_table,source_id)"
        )


def apply_life_model_delta(person_id: str, delta: Mapping[str, Any], *, db_path=None) -> str:
    """Apply a typed incremental V19 life-model delta.

    The caller must provide the statement and evidence-bearing delta.  This
    helper preserves revision history and never regenerates the whole model.
    """
    ensure_life_model_store(db_path)
    now = now_iso()
    stmt = str(delta.get("statement") or "").strip()
    if not stmt:
        raise ValueError("life_model_v19 delta requires statement")
    operation = str(delta.get("operation") or "upsert")
    eid = str(delta.get("entry_id") or stable_id("lifev19", person_id, delta.get("dimension"), delta.get("temporal_axis"), stmt))
    with connect(db_path) as con, write_transaction(con):
        existing = con.execute(
            "SELECT revision_history_json,created_at,first_observed,source_table,source_id,source_updated_at "
            "FROM life_model_entries_v19 WHERE entry_id=?",
            (eid,),
        ).fetchone()
        history = json_loads(existing["revision_history_json"], []) if existing else []
        if not isinstance(history, list):
            history = []
        history.append({"at": now, "operation": operation, "delta": dict(delta)})
        upsert(
            con,
            "life_model_entries_v19",
            {
                "entry_id": eid,
                "person_id": person_id,
                "dimension": str(delta.get("dimension") or "unspecified"),
                "temporal_axis": str(delta.get("temporal_axis") or "present"),
                "statement": stmt,
                "confidence": max(0.0, min(1.0, float(delta.get("confidence") or 0.5))),
                "status": str(delta.get("status") or "active"),
                "evidence_refs_json": json_dumps(delta.get("evidence_refs") or []),
                "verification_spec_json": json_dumps(delta.get("verification_spec") or {}),
                "prediction_template_json": json_dumps(delta.get("prediction_template") or {}),
                "source_table": delta.get("source_table") or (existing["source_table"] if existing else None),
                "source_id": delta.get("source_id") or (existing["source_id"] if existing else None),
                "source_updated_at": delta.get("source_updated_at") or (existing["source_updated_at"] if existing else None),
                "first_observed": delta.get("first_observed") or (existing["first_observed"] if existing else now),
                "last_confirmed": delta.get("last_confirmed") or now,
                "revision_history_json": json_dumps(history),
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            },
            "entry_id",
        )
    return eid


_CANONICAL_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "table": "brain2_personal_routine_models", "pk": "routine_id",
        "statement": ("routine_name",), "dimension": "routines", "temporal_axis": "present",
    },
    {
        "table": "brain2_place_preference_models", "pk": "place_model_id",
        "statement": ("meaning_for_user", "place_key"), "dimension": "preferences", "temporal_axis": "present",
    },
    {
        "table": "brain2_action_preference_models", "pk": "action_model_id",
        "statement": ("preference_or_tendency", "action_or_choice"), "dimension": "preferences", "temporal_axis": "present",
    },
    {
        "table": "brain2_need_expectation_models", "pk": "need_model_id",
        "statement": ("need_or_expectation",), "dimension": "goals", "temporal_axis": "present",
    },
    {
        "table": "brain2_expression_state_models", "pk": "expression_model_id",
        "statement": ("expression_or_style",), "dimension": "language_personal", "temporal_axis": "present",
    },
    {
        "table": "brain2_emotional_trajectory_models", "pk": "trajectory_model_id",
        "statement": ("trajectory_name",), "dimension": "emotions", "temporal_axis": "future_short",
    },
    {
        "table": "brain2_contextual_self_models", "pk": "contextual_model_id",
        "statement": ("self_state_summary", "context_key"), "dimension": "identity", "temporal_axis": "present",
    },
    {
        "table": "brain2_live_prediction_hooks", "pk": "hook_id",
        "statement": ("hook_name",), "dimension": "routines", "temporal_axis": "future_short",
        "verification": "predicts_json",
    },
    {
        "table": "brain2_live_affordance_preferences", "pk": "affordance_pref_id",
        "statement": ("affordance_type",), "dimension": "preferences", "temporal_axis": "present",
    },
)


def _first_text(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _evidence_refs_from_canonical(row: Mapping[str, Any], *, table: str, source_id: str) -> list[Any]:
    refs: list[Any] = [{"source_table": table, "source_id": source_id}]
    evidence = json_loads(row.get("evidence_json"), [])
    if isinstance(evidence, list):
        refs.extend(evidence)
    return refs


def _explicit_verification_spec(row: Mapping[str, Any], column: str | None) -> dict[str, Any]:
    if not column:
        return {}
    candidate = json_loads(row.get(column), {})
    if not isinstance(candidate, dict):
        return {}
    nested = candidate.get("verification_spec")
    if isinstance(nested, dict):
        candidate = nested
    if not any(candidate.get(k) for k in ("event_type", "entity_label", "place_label", "observation_contains")):
        return {}
    out = dict(candidate)
    sources = [str(item) for item in (out.get("sources") or out.get("observation_sources") or [])]
    if "visual_events_v19" not in sources:
        sources.append("visual_events_v19")
    out["sources"] = sources
    return out


def project_canonical_life_model(person_id: str, *, db_path=None) -> dict[str, Any]:
    """Project the real V15.10/V15.13 canonical store into durable V19 entries.

    The existing nightly LLM pipeline remains the sole producer of statements.
    This bridge adds typed V19 provenance and is idempotent on the canonical row's
    ``updated_at``; tests/simulators no longer need to seed V19 for production.
    """
    from .brain2_life_model_v15_10 import ensure_life_model_schema

    ensure_life_model_schema()
    ensure_life_model_store(db_path)
    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    for spec in _CANONICAL_SOURCES:
        table = str(spec["table"])
        pk = str(spec["pk"])
        with connect(db_path) as con:
            table_exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if table_exists is None:
                continue
            rows = [dict(row) for row in con.execute(
                f"SELECT * FROM {table} WHERE person_id=?", (person_id,)
            ).fetchall()]
        for row in rows:
            source_id = str(row.get(pk) or "").strip()
            statement = _first_text(row, tuple(spec["statement"]))
            if not source_id or not statement:
                continue
            source_updated_at = str(row.get("updated_at") or row.get("created_at") or "") or None
            entry_id = stable_id("lifev19src", person_id, table, source_id)
            with connect(db_path) as con:
                existing = con.execute(
                    "SELECT source_updated_at FROM life_model_entries_v19 WHERE entry_id=? AND person_id=?",
                    (entry_id, person_id),
                ).fetchone()
            if existing and str(existing["source_updated_at"] or "") == str(source_updated_at or ""):
                unchanged.append(entry_id)
                continue
            raw_status = str(row.get("status") or "active").lower()
            status = {
                "active": "active", "confirmed": "confirmed", "candidate": "active",
                "weakened": "weakening", "weakening": "weakening",
                "contradicted": "contradicted", "obsolete": "superseded", "superseded": "superseded",
            }.get(raw_status, "active")
            verification = _explicit_verification_spec(row, spec.get("verification"))
            apply_life_model_delta(
                person_id,
                {
                    "entry_id": entry_id,
                    "dimension": spec["dimension"],
                    "temporal_axis": spec["temporal_axis"],
                    "statement": statement,
                    "confidence": row.get("confidence") or 0.5,
                    "status": status,
                    "evidence_refs": _evidence_refs_from_canonical(row, table=table, source_id=source_id),
                    "verification_spec": verification,
                    "prediction_template": verification,
                    "source_table": table,
                    "source_id": source_id,
                    "source_updated_at": source_updated_at,
                    "first_observed": row.get("created_at"),
                    "last_confirmed": row.get("updated_at") or row.get("created_at"),
                    "operation": "project_canonical_update" if existing else "project_canonical_create",
                },
                db_path=db_path,
            )
            (updated if existing else created).append(entry_id)
    return {
        "status": "completed",
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "entry_ids": [*created, *updated, *unchanged],
        "count": len(created) + len(updated) + len(unchanged),
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _set_status(con, *, entry_id: str, status: str, now: str, note: Mapping[str, Any]) -> None:
    row = con.execute(
        "SELECT revision_history_json FROM life_model_entries_v19 WHERE entry_id=?", (entry_id,)
    ).fetchone()
    if not row:
        return
    history = json_loads(row["revision_history_json"], [])
    if not isinstance(history, list):
        history = []
    history.append({"at": now, "operation": status, "note": dict(note)})
    con.execute(
        "UPDATE life_model_entries_v19 SET status=?, revision_history_json=?, updated_at=? WHERE entry_id=?",
        (status, json_dumps(history), now, entry_id),
    )


def weaken_stale_entries(
    person_id: str,
    *,
    as_of: str | None = None,
    stale_days: int = DEFAULT_WEAKENING_DAYS,
    db_path=None,
) -> list[str]:
    """Transition ``active`` entries not re-confirmed for ``stale_days`` to ``weakening``.

    An entry is never deleted silently: it merely decays in status so the
    projection/prediction layers stop treating it as fully current, while its
    revision history is preserved for audit.
    """
    ensure_life_model_store(db_path)
    now = now_iso()
    ref_dt = _parse_dt(as_of) or _parse_dt(now) or datetime.now(timezone.utc)
    cutoff = ref_dt - timedelta(days=max(0, int(stale_days)))
    weakened: list[str] = []
    with connect(db_path) as con, write_transaction(con):
        rows = [
            dict(r)
            for r in con.execute(
                "SELECT entry_id, last_confirmed, first_observed, created_at FROM life_model_entries_v19 "
                "WHERE person_id=? AND status='active'",
                (person_id,),
            ).fetchall()
        ]
        for row in rows:
            last = _parse_dt(row.get("last_confirmed")) or _parse_dt(row.get("first_observed")) or _parse_dt(row.get("created_at"))
            if last is not None and last < cutoff:
                _set_status(
                    con,
                    entry_id=row["entry_id"],
                    status="weakening",
                    now=now,
                    note={"reason": "not_reconfirmed", "stale_days": int(stale_days), "last_confirmed": row.get("last_confirmed")},
                )
                weakened.append(row["entry_id"])
    return weakened


def mark_contradicted(
    person_id: str,
    entry_id: str,
    *,
    contradicting_ref: Mapping[str, Any],
    db_path=None,
) -> bool:
    """Move an entry to ``contradicted`` with a reference to the contradicting delta."""
    ensure_life_model_store(db_path)
    now = now_iso()
    with connect(db_path) as con, write_transaction(con):
        exists = con.execute(
            "SELECT 1 FROM life_model_entries_v19 WHERE entry_id=? AND person_id=?", (entry_id, person_id)
        ).fetchone()
        if not exists:
            return False
        _set_status(
            con,
            entry_id=entry_id,
            status="contradicted",
            now=now,
            note={"reason": "contradicted", "contradicting_ref": dict(contradicting_ref)},
        )
    return True


def run_life_model_v19_stage(
    *,
    person_id: str,
    package_date: str,
    stale_days: int = DEFAULT_WEAKENING_DAYS,
    db_path=None,
) -> dict[str, Any]:
    """Durable Life-Model V19 close-day stage (incremental deltas only).

    Collects the day's new facts — confirmed visual events, resolved prediction
    outcomes and confirmed patterns — and applies incremental deltas:
    - a matching visual/place fact ``confirms`` the corresponding routine entry
      (bumps ``last_confirmed``, appends history, never regenerates the model);
    - a ``refuted`` prediction outcome ``contradicts`` its source entry;
    - active entries not re-confirmed for ``stale_days`` decay to ``weakening``.

    This stage never regenerates the whole model and never deletes entries.
    """
    from .v19_visual_store import ensure_v19_visual_schema

    ensure_life_model_store(db_path)
    ensure_v19_visual_schema(db_path)
    from .v19_visual_consolidation import _local_day_utc_bounds

    day_start, day_end = _local_day_utc_bounds(package_date)
    projected = project_canonical_life_model(person_id, db_path=db_path)
    confirmed: list[str] = []
    contradicted: list[str] = []

    with connect(db_path) as con:
        events = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM visual_events_v19 WHERE person_id=? AND occurred_at>=? AND occurred_at<?",
                (person_id, day_start, day_end),
            ).fetchall()
        ]
        entries = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM life_model_entries_v19 WHERE person_id=? AND status IN ('active','confirmed','weakening')",
                (person_id,),
            ).fetchall()
        ]
        try:
            refuted = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM prediction_outcomes_v19 WHERE person_id=? AND status='refuted' "
                    "AND resolved_at>=? AND resolved_at<?",
                    (person_id, day_start, day_end),
                ).fetchall()
            ]
        except Exception:
            refuted = []
        try:
            predictions = {
                r["prediction_id"]: dict(r)
                for r in con.execute("SELECT * FROM predictions_v19 WHERE person_id=?", (person_id,)).fetchall()
            }
        except Exception:
            predictions = {}

    # Confirm entries whose verification spec matched a day event.
    event_blobs = [
        (
            str(e.get("event_type") or "").lower(),
            " ".join(str(e.get(k) or "") for k in ("entity_json", "observation_json", "place_json")).lower(),
            e,
        )
        for e in events
    ]
    for entry in entries:
        spec = json_loads(entry.get("verification_spec_json"), {}) or {}
        if not isinstance(spec, dict) or not spec:
            continue
        want_type = str(spec.get("event_type") or "").lower()
        want_labels = [str(spec.get(k) or "").strip().lower() for k in ("entity_label", "place_label", "observation_contains")]
        want_labels = [w for w in want_labels if w]
        match = None
        for etype, blob, ev in event_blobs:
            if want_type and etype != want_type:
                continue
            if any(w not in blob for w in want_labels):
                continue
            match = ev
            break
        if match is not None:
            apply_life_model_delta(
                person_id,
                {
                    "entry_id": entry["entry_id"],
                    "dimension": entry["dimension"],
                    "temporal_axis": entry["temporal_axis"],
                    "statement": entry["statement"],
                    "operation": "confirm",
                    "status": "active" if entry["status"] == "weakening" else entry["status"],
                    "confidence": entry.get("confidence"),
                    "evidence_refs": [{"source_table": "visual_events_v19", "source_id": match["visual_event_id"]}],
                    "verification_spec": spec,
                    "last_confirmed": match.get("occurred_at"),
                },
                db_path=db_path,
            )
            confirmed.append(entry["entry_id"])

    # Contradict entries whose emitted prediction was refuted today.
    for outcome in refuted:
        pred = predictions.get(outcome.get("prediction_id"), {})
        source_entry_id = str(pred.get("source_entry_id") or "").strip() or None
        if source_entry_id and source_entry_id not in contradicted:
            mark_contradicted(
                person_id,
                source_entry_id,
                contradicting_ref={"source_table": "prediction_outcomes_v19", "source_id": outcome["outcome_id"]},
                db_path=db_path,
            )
            contradicted.append(source_entry_id)

    weakened = weaken_stale_entries(person_id, as_of=day_end, stale_days=stale_days, db_path=db_path)

    total = 0
    with connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM life_model_entries_v19 WHERE person_id=?", (person_id,)).fetchone()[0]

    return {
        "status": "completed",
        "stage": "life_model_v19",
        "package_date": package_date,
        "projected": projected,
        "confirmed": confirmed,
        "contradicted": contradicted,
        "weakened": weakened,
        "count": total,
    }
