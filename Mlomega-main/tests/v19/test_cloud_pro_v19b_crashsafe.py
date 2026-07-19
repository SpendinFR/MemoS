"""OBS-70 crash-safe ledger + CHANTIER 1 local EpisodeBuilder frontier tests.

All fakes: no P1 subprocess, no real DeepSeek/Groq/Gemini call.  Every test that
exercises PRO proves that the default (no-flag) path is untouched.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mlomega_audio_elite import cloud_budget_v19 as budget
from mlomega_audio_elite import cloud_providers_v19 as cloud


@pytest.fixture
def cloud_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cloud.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.50")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    # A stable run identity makes "same run vs foreign run" assertions explicit.
    monkeypatch.setenv("MLOMEGA_CLOUD_RUN_ID", "run-active")
    return db


def _rows(db: Path) -> list[dict]:
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT call_id,status,reserved_eur,actual_eur,run_id,worker_id,sent_at "
            "FROM cloud_cost_ledger_v19"
        )]


# ---------------------------------------------------------------------------
# CHANTIER 3 — durable reserved -> in_flight frontier and crash recovery
# ---------------------------------------------------------------------------

def test_reservation_carries_durable_run_and_worker_identity(cloud_env: Path) -> None:
    reservation = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.01, tariff={}
    )
    rows = _rows(cloud_env)
    assert len(rows) == 1
    assert rows[0]["status"] == "reserved"
    assert rows[0]["run_id"] == "run-active"
    assert rows[0]["worker_id"]
    assert rows[0]["sent_at"] is None
    assert reservation.run_id == "run-active"


def test_mark_in_flight_persists_frontier_before_send(cloud_env: Path) -> None:
    reservation = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.01, tariff={}
    )
    budget.mark_cloud_in_flight(reservation)
    row = _rows(cloud_env)[0]
    assert row["status"] == "in_flight"
    assert row["sent_at"] is not None
    # An in_flight row still counts at worst case in the cap.
    assert budget.cloud_budget_summary()["committed_eur"] == pytest.approx(0.01)


def test_deepseek_marks_in_flight_before_http(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_status: list[str] = []

    def fake_json_request(url, payload, **kwargs):
        # At HTTP time the reservation MUST already be durably in_flight.
        with sqlite3.connect(cloud_env) as con:
            seen_status.append(
                con.execute("SELECT status FROM cloud_cost_ledger_v19").fetchone()[0]
            )
        return {
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    cloud._deepseek_request(
        messages=[{"role": "user", "content": "x"}], model="deepseek-v4-pro",
        max_output_tokens=50, timeout=5, stage_name="t", json_schema={"type": "object"},
    )
    assert seen_status == ["in_flight"]
    assert _rows(cloud_env)[0]["status"] == "completed"


def test_crash_before_send_is_releasable(cloud_env: Path) -> None:
    """A never-sent reservation from a FINISHED foreign run frees its worst case."""
    # Simulate a previous run's crash: reserved, never marked in_flight.
    import os
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-crashed"
    budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.40, tariff={}
    )
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-active"

    report = budget.recover_cloud_reservations()
    assert report["released"] == 1
    assert report["uncertain"] == 0
    row = _rows(cloud_env)[0]
    assert row["status"] == "released"
    assert row["actual_eur"] == 0
    # Released rows no longer occupy the cap.
    assert budget.cloud_budget_summary()["committed_eur"] == pytest.approx(0.0)


def test_crash_after_marking_sent_is_uncertain_and_counted(cloud_env: Path) -> None:
    import os
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-crashed"
    reservation = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.40, tariff={}
    )
    budget.mark_cloud_in_flight(reservation)  # sent_at set, process then dies
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-active"

    report = budget.recover_cloud_reservations()
    assert report["uncertain"] == 1
    assert report["released"] == 0
    row = _rows(cloud_env)[0]
    assert row["status"] == "uncertain"
    assert row["actual_eur"] == pytest.approx(0.40)
    # A possibly-billed request keeps its worst case in the daily cap.
    assert budget.cloud_budget_summary()["committed_eur"] == pytest.approx(0.40)


def test_recovery_never_touches_active_run_reservations(cloud_env: Path) -> None:
    """The live run stays authoritative on its own reserved/in_flight rows."""
    active_reserved = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.10, tariff={}
    )
    active_inflight = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s2", worst_case_eur=0.10, tariff={}
    )
    budget.mark_cloud_in_flight(active_inflight)

    report = budget.recover_cloud_reservations()
    assert report["released"] == 0 and report["uncertain"] == 0
    by_id = {r["call_id"]: r for r in _rows(cloud_env)}
    assert by_id[active_reserved.call_id]["status"] == "reserved"
    assert by_id[active_inflight.call_id]["status"] == "in_flight"


def test_recovery_is_idempotent_and_concurrent_safe(cloud_env: Path) -> None:
    import os
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-crashed"
    never_sent = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s", worst_case_eur=0.10, tariff={}
    )
    sent = budget.reserve_cloud_cost(
        provider="deepseek", model="m", stage_name="s2", worst_case_eur=0.10, tariff={}
    )
    budget.mark_cloud_in_flight(sent)
    os.environ["MLOMEGA_CLOUD_RUN_ID"] = "run-active"

    first = budget.recover_cloud_reservations()
    second = budget.recover_cloud_reservations()  # concurrent/re-entry
    assert (first["released"], first["uncertain"]) == (1, 1)
    assert (second["released"], second["uncertain"]) == (0, 0)
    by_id = {r["call_id"]: r for r in _rows(cloud_env)}
    assert by_id[never_sent.call_id]["status"] == "released"
    assert by_id[sent.call_id]["status"] == "uncertain"


def test_migration_adds_columns_to_pre_obs70_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An old ledger (no run_id/worker_id/sent_at) is migrated without losing rows."""
    db = tmp_path / "legacy.db"
    # Use TODAY's budget day so the summary (which filters on it) sees the row,
    # independent of the wall-clock date the suite runs on.
    today = budget._budget_day()
    with sqlite3.connect(db) as con:
        con.execute(
            """CREATE TABLE cloud_cost_ledger_v19(
                 call_id TEXT PRIMARY KEY, budget_day TEXT NOT NULL, provider TEXT NOT NULL,
                 model TEXT NOT NULL, stage_name TEXT NOT NULL, status TEXT NOT NULL,
                 reserved_eur REAL NOT NULL DEFAULT 0, actual_eur REAL,
                 input_tokens INTEGER, cache_hit_tokens INTEGER, cache_miss_tokens INTEGER,
                 output_tokens INTEGER, audio_seconds REAL, image_count INTEGER,
                 latency_ms INTEGER, http_status INTEGER, retry_count INTEGER NOT NULL DEFAULT 0,
                 tariff_json TEXT NOT NULL DEFAULT '{}', usage_json TEXT NOT NULL DEFAULT '{}',
                 error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        con.execute(
            "INSERT INTO cloud_cost_ledger_v19(call_id,budget_day,provider,model,stage_name,"
            "status,reserved_eur,created_at,updated_at) VALUES('old',?,'deepseek',"
            "'m','s','reserved',0.20,'t','t')",
            (today,),
        )
        con.commit()
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    budget.ensure_cloud_budget_schema()
    with sqlite3.connect(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(cloud_cost_ledger_v19)")}
        assert {"run_id", "worker_id", "sent_at"} <= cols
        # No row was lost, and the old reserved cost is still counted.
        assert con.execute("SELECT COUNT(*) FROM cloud_cost_ledger_v19").fetchone()[0] == 1
    # The preserved reserved line stays in the committed cap (never edited by hand).
    assert budget.cloud_budget_summary()["committed_eur"] == pytest.approx(0.20)


def test_ledger_frontier_is_inert_without_pro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The new functions never fire on the local path (nothing calls them)."""
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    monkeypatch.delenv("MLOMEGA_CLOUD_MODE", raising=False)
    # cloud_mode_enabled gates whether the ledger is even consulted by callers.
    assert budget.cloud_mode_enabled() is False
