from __future__ import annotations

"""Durable, provider-neutral cloud budget ledger for the opt-in PRO path.

The local product path never imports this module unless a cloud provider is
selected.  Every paid request reserves a conservative upper bound in the same
SQLite database as the CloseDay run, then reconciles the reservation with the
provider's returned usage.  ``BEGIN IMMEDIATE`` makes concurrent reservations
atomic across the SessionHub, DeepAudio subprocess and CloseDay process.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .db import connect, write_transaction
from .utils import now_iso


LEDGER_TABLE = "cloud_cost_ledger_v19"

# OBS-70 crash-safe frontier (docs/PRO_CLOSEDAY_HANDOFF.md, §"crash/budget"):
#   run_id / worker_id  : durable identity of the process that owns a reservation.
#   sent_at             : set the instant BEFORE the HTTP request leaves; its
#                         presence is the proof a request may have been billed.
#   status='in_flight'  : persisted after ``mark_cloud_in_flight`` and before the
#                         network call, so a crash mid-call is recoverable.
LEDGER_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE}(
  call_id TEXT PRIMARY KEY,
  budget_day TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  status TEXT NOT NULL,
  reserved_eur REAL NOT NULL DEFAULT 0,
  actual_eur REAL,
  input_tokens INTEGER,
  cache_hit_tokens INTEGER,
  cache_miss_tokens INTEGER,
  output_tokens INTEGER,
  audio_seconds REAL,
  image_count INTEGER,
  latency_ms INTEGER,
  http_status INTEGER,
  retry_count INTEGER NOT NULL DEFAULT 0,
  tariff_json TEXT NOT NULL DEFAULT '{{}}',
  usage_json TEXT NOT NULL DEFAULT '{{}}',
  error_code TEXT,
  run_id TEXT,
  worker_id TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cloud_cost_day_v19
  ON {LEDGER_TABLE}(budget_day,status,provider,model);
"""

# Created only AFTER the identity columns are guaranteed to exist (a pre-OBS-70
# table is migrated first), so a legacy ledger does not fail on ``run_id``.
_LEDGER_RUN_INDEX = (
    f"CREATE INDEX IF NOT EXISTS idx_cloud_cost_run_v19 "
    f"ON {LEDGER_TABLE}(run_id,status);"
)

# Columns added after the first PRO ledger shipped. Old databases (e.g. the
# preserved gateb-pro-20260719-185246.db) must gain them without losing a row.
_LEDGER_ADDED_COLUMNS = (("run_id", "TEXT"), ("worker_id", "TEXT"), ("sent_at", "TEXT"))

# Every status that must count at (at least) its reserved worst case in the cap.
# ``in_flight`` and ``uncertain`` are conservative: a possibly-billed request is
# never released on age alone (OBS-70).
_COMMITTED_STATUSES = (
    "reserved", "in_flight", "completed", "failed_charged", "uncertain",
)


_PROCESS_RUN_ID: str | None = None
_PROCESS_WORKER_ID: str | None = None


class CloudBudgetExceeded(RuntimeError):
    def __init__(
        self,
        *,
        requested_eur: float,
        committed_eur: float,
        limit_eur: float,
        provider: str,
        model: str,
        policy: str,
    ) -> None:
        self.requested_eur = float(requested_eur)
        self.committed_eur = float(committed_eur)
        self.limit_eur = float(limit_eur)
        self.provider = str(provider)
        self.model = str(model)
        self.policy = str(policy)
        super().__init__(
            "cloud budget would be exceeded: "
            f"committed={self.committed_eur:.6f} EUR + "
            f"request={self.requested_eur:.6f} EUR > "
            f"limit={self.limit_eur:.6f} EUR; provider={self.provider}; "
            f"model={self.model}; policy={self.policy}"
        )


@dataclass(frozen=True)
class CloudReservation:
    call_id: str
    provider: str
    model: str
    stage_name: str
    reserved_eur: float
    budget_day: str
    tariff: dict[str, Any]
    run_id: str = ""
    worker_id: str = ""


def cloud_mode_enabled() -> bool:
    return os.environ.get("MLOMEGA_CLOUD_MODE", "local").strip().lower() in {
        "pro", "cloud", "deepseek",
    }


def cloud_budget_limit_eur() -> float:
    raw = os.environ.get(
        "MLOMEGA_CLOUD_DAILY_BUDGET_EUR",
        os.environ.get("MLOMEGA_DEEPSEEK_DAILY_BUDGET_EUR", "1.50"),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 1.50
    if value <= 0:
        raise ValueError("MLOMEGA_CLOUD_DAILY_BUDGET_EUR must be > 0")
    return value


def cloud_budget_policy() -> str:
    policy = os.environ.get("MLOMEGA_CLOUD_ON_BUDGET", "stop").strip().lower()
    if policy not in {"stop", "flash", "local"}:
        raise ValueError("MLOMEGA_CLOUD_ON_BUDGET must be stop|flash|local")
    return policy


def usd_per_eur() -> float:
    """Tariff conversion snapshot; overridable without a network lookup."""

    raw = os.environ.get("MLOMEGA_CLOUD_USD_PER_EUR", "1.1435")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 1.1435
    return value if value > 0 else 1.1435


def usd_to_eur(value: float) -> float:
    return max(0.0, float(value)) / usd_per_eur()


def _budget_day() -> str:
    try:
        tz = ZoneInfo(os.environ.get("MLOMEGA_LOCAL_TZ", "Europe/Paris"))
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def _migrate_ledger_columns(con: Any) -> None:
    """Add the crash-safe identity/frontier columns to a pre-OBS-70 ledger."""
    existing = {
        str(row["name"])
        for row in con.execute(f"PRAGMA table_info({LEDGER_TABLE})").fetchall()
    }
    for name, decl in _LEDGER_ADDED_COLUMNS:
        if name not in existing:
            con.execute(f"ALTER TABLE {LEDGER_TABLE} ADD COLUMN {name} {decl}")


def ensure_cloud_budget_schema() -> None:
    with connect() as con:
        con.executescript(LEDGER_SCHEMA)
        _migrate_ledger_columns(con)
        con.execute(_LEDGER_RUN_INDEX)
        con.commit()


def cloud_run_id() -> str:
    """Durable identity of the CloseDay run that owns a reservation.

    Prefer an explicit run identity set by the launcher so a resume of the SAME
    run recognises its own prior reservations; fall back to a per-process id.
    """
    for key in ("MLOMEGA_CLOUD_RUN_ID", "MLOMEGA_CLOSE_DAY_RUN_ID", "MLOMEGA_RUN_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    global _PROCESS_RUN_ID
    if _PROCESS_RUN_ID is None:
        _PROCESS_RUN_ID = f"run_{uuid4().hex}"
    return _PROCESS_RUN_ID


def cloud_worker_id() -> str:
    """Per-process/worker identity (thread-safe: derived once per process)."""
    global _PROCESS_WORKER_ID
    if _PROCESS_WORKER_ID is None:
        _PROCESS_WORKER_ID = f"worker_{os.getpid()}_{uuid4().hex[:8]}"
    return _PROCESS_WORKER_ID


def _committed_eur(con: Any, budget_day: str) -> float:
    placeholders = ",".join("?" for _ in _COMMITTED_STATUSES)
    row = con.execute(
        f"""SELECT COALESCE(SUM(
               CASE WHEN status IN ('reserved','in_flight') THEN reserved_eur
                    ELSE COALESCE(actual_eur,reserved_eur) END
             ),0) AS total
             FROM {LEDGER_TABLE}
             WHERE budget_day=? AND status IN ({placeholders})""",
        (budget_day, *_COMMITTED_STATUSES),
    ).fetchone()
    return float(row["total"] if row is not None else 0.0)


def reserve_cloud_cost(
    *,
    provider: str,
    model: str,
    stage_name: str,
    worst_case_eur: float,
    tariff: dict[str, Any],
) -> CloudReservation:
    ensure_cloud_budget_schema()
    amount = max(0.0, float(worst_case_eur))
    day = _budget_day()
    limit = cloud_budget_limit_eur()
    policy = cloud_budget_policy()
    call_id = f"cloudcall_{uuid4().hex}"
    timestamp = now_iso()
    run_id = cloud_run_id()
    worker_id = cloud_worker_id()
    with connect() as con, write_transaction(con, immediate=True):
        committed = _committed_eur(con, day)
        if committed + amount > limit + 1e-9:
            raise CloudBudgetExceeded(
                requested_eur=amount,
                committed_eur=committed,
                limit_eur=limit,
                provider=provider,
                model=model,
                policy=policy,
            )
        con.execute(
            f"""INSERT INTO {LEDGER_TABLE}(
                 call_id,budget_day,provider,model,stage_name,status,
                 reserved_eur,tariff_json,run_id,worker_id,created_at,updated_at)
                 VALUES(?,?,?,?,?,'reserved',?,?,?,?,?,?)""",
            (
                call_id, day, str(provider), str(model), str(stage_name), amount,
                json.dumps(tariff, ensure_ascii=False, sort_keys=True),
                run_id, worker_id, timestamp, timestamp,
            ),
        )
    return CloudReservation(
        call_id=call_id,
        provider=str(provider),
        model=str(model),
        stage_name=str(stage_name),
        reserved_eur=amount,
        budget_day=day,
        tariff=dict(tariff),
        run_id=run_id,
        worker_id=worker_id,
    )


def mark_cloud_in_flight(reservation: CloudReservation) -> None:
    """Persist the durable ``reserved -> in_flight`` frontier BEFORE the HTTP send.

    After this returns, the row carries ``sent_at`` and ``status='in_flight'``: a
    crash from here until reconciliation proves the request *may* have been billed,
    so recovery keeps it at worst case (``uncertain``) instead of releasing it.
    A row already reconciled (completed/failed_charged/uncertain) is left as-is so
    a late duplicate call cannot regress a settled cost.
    """
    ensure_cloud_budget_schema()
    with connect() as con, write_transaction(con, immediate=True):
        con.execute(
            f"""UPDATE {LEDGER_TABLE}
                SET status='in_flight',sent_at=?,updated_at=?
                WHERE call_id=? AND status='reserved'""",
            (now_iso(), now_iso(), reservation.call_id),
        )


def reconcile_cloud_cost(
    reservation: CloudReservation,
    *,
    actual_eur: float,
    status: str = "completed",
    input_tokens: int | None = None,
    cache_hit_tokens: int | None = None,
    cache_miss_tokens: int | None = None,
    output_tokens: int | None = None,
    audio_seconds: float | None = None,
    image_count: int | None = None,
    latency_ms: int | None = None,
    http_status: int | None = None,
    retry_count: int = 0,
    usage: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    if status not in {"completed", "failed_charged", "uncertain"}:
        raise ValueError(f"invalid reconciled cloud status: {status}")
    ensure_cloud_budget_schema()
    with connect() as con, write_transaction(con, immediate=True):
        con.execute(
            f"""UPDATE {LEDGER_TABLE}
                SET status=?,actual_eur=?,input_tokens=?,cache_hit_tokens=?,
                    cache_miss_tokens=?,output_tokens=?,audio_seconds=?,image_count=?,
                    latency_ms=?,http_status=?,retry_count=?,usage_json=?,error_code=?,
                    updated_at=?
                WHERE call_id=?""",
            (
                status, max(0.0, float(actual_eur)), input_tokens,
                cache_hit_tokens, cache_miss_tokens, output_tokens,
                audio_seconds, image_count, latency_ms, http_status,
                int(retry_count),
                json.dumps(usage or {}, ensure_ascii=False, sort_keys=True, default=str),
                error_code, now_iso(), reservation.call_id,
            ),
        )


def release_cloud_reservation(
    reservation: CloudReservation,
    *,
    error_code: str,
    request_was_sent: bool,
) -> None:
    """Release a pre-network failure; retain worst case after an uncertain send."""

    if request_was_sent:
        reconcile_cloud_cost(
            reservation,
            actual_eur=reservation.reserved_eur,
            status="uncertain",
            error_code=error_code,
        )
        return
    ensure_cloud_budget_schema()
    with connect() as con, write_transaction(con, immediate=True):
        con.execute(
            f"""UPDATE {LEDGER_TABLE}
                SET status='released',actual_eur=0,error_code=?,updated_at=?
                WHERE call_id=?""",
            (str(error_code), now_iso(), reservation.call_id),
        )


def recover_cloud_reservations(*, active_run_id: str | None = None) -> dict[str, Any]:
    """Reconcile reservations orphaned by a crash, conservatively (OBS-70).

    Called ONCE at the start of a resumed PRO run, before any new reservation.
    The rule mirrors ``docs/PRO_CLOSEDAY_HANDOFF.md``:

    * A ``reserved`` row that belongs to a DIFFERENT, now-inactive run and was
      never marked ``in_flight`` (no ``sent_at``) is PROVEN to have never sent a
      request. It becomes ``released`` and frees its worst case.
    * An ``in_flight`` row (``sent_at`` present) from any run MAY have been billed.
      It becomes ``uncertain`` and KEEPS its reserved worst case in the cap. Age is
      never a release reason.
    * Rows owned by the ACTIVE run are left untouched: the live process is still
      the authority on its own reservations (idempotent re-entry, concurrency).

    Idempotent: re-running only transitions rows that are still reserved/in_flight
    and not owned by the active run, so a second call is a no-op.
    """
    ensure_cloud_budget_schema()
    active = str(active_run_id or cloud_run_id())
    released = 0
    uncertain = 0
    with connect() as con, write_transaction(con, immediate=True):
        # Proven non-emission: a foreign run's still-reserved row with no sent_at.
        cursor = con.execute(
            f"""UPDATE {LEDGER_TABLE}
                SET status='released',actual_eur=0,error_code='recovered_never_sent',
                    updated_at=?
                WHERE status='reserved' AND sent_at IS NULL
                  AND (run_id IS NULL OR run_id<>?)""",
            (now_iso(), active),
        )
        released = int(cursor.rowcount or 0)
        # Possibly billed: any orphaned in_flight row keeps worst case as uncertain.
        cursor = con.execute(
            f"""UPDATE {LEDGER_TABLE}
                SET status='uncertain',actual_eur=reserved_eur,
                    error_code=COALESCE(error_code,'recovered_uncertain_send'),
                    updated_at=?
                WHERE status='in_flight'
                  AND (run_id IS NULL OR run_id<>?)""",
            (now_iso(), active),
        )
        uncertain = int(cursor.rowcount or 0)
    return {
        "active_run_id": active,
        "released": released,
        "uncertain": uncertain,
    }


def cloud_budget_summary(
    *, budget_day: str | None = None, initialized_only: bool = False
) -> dict[str, Any]:
    if initialized_only:
        with connect() as con:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (LEDGER_TABLE,),
            ).fetchone()
        if exists is None:
            return {
                "budget_day": budget_day or _budget_day(),
                "limit_eur": cloud_budget_limit_eur(),
                "committed_eur": 0.0,
                "remaining_eur": cloud_budget_limit_eur(),
                "policy": cloud_budget_policy(),
                "rows": [],
                "status": "not_started",
            }
    else:
        ensure_cloud_budget_schema()
    day = budget_day or _budget_day()
    with connect() as con:
        rows = con.execute(
            f"""SELECT provider,model,status,COUNT(*) AS calls,
                       COALESCE(SUM(reserved_eur),0) AS reserved_eur,
                       COALESCE(SUM(actual_eur),0) AS actual_eur,
                       COALESCE(SUM(input_tokens),0) AS input_tokens,
                       COALESCE(SUM(cache_hit_tokens),0) AS cache_hit_tokens,
                       COALESCE(SUM(cache_miss_tokens),0) AS cache_miss_tokens,
                       COALESCE(SUM(output_tokens),0) AS output_tokens,
                       COALESCE(SUM(audio_seconds),0) AS audio_seconds,
                       COALESCE(SUM(image_count),0) AS images
                FROM {LEDGER_TABLE} WHERE budget_day=?
                GROUP BY provider,model,status ORDER BY provider,model,status""",
            (day,),
        ).fetchall()
        committed = _committed_eur(con, day)
    return {
        "budget_day": day,
        "limit_eur": cloud_budget_limit_eur(),
        "committed_eur": committed,
        "remaining_eur": max(0.0, cloud_budget_limit_eur() - committed),
        "policy": cloud_budget_policy(),
        "rows": [dict(row) for row in rows],
    }


__all__ = [
    "CloudBudgetExceeded",
    "CloudReservation",
    "cloud_budget_limit_eur",
    "cloud_budget_policy",
    "cloud_budget_summary",
    "cloud_mode_enabled",
    "cloud_run_id",
    "cloud_worker_id",
    "ensure_cloud_budget_schema",
    "mark_cloud_in_flight",
    "reconcile_cloud_cost",
    "recover_cloud_reservations",
    "release_cloud_reservation",
    "reserve_cloud_cost",
    "usd_per_eur",
    "usd_to_eur",
]
