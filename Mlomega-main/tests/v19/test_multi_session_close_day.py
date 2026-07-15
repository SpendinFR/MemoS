"""Multi-session / day close-day reopen (E47-C livrable 6, guide E47 §6).

A close-day is idempotent per (person_id, package_date): once the day's
``v18_close_day_runs`` row is ``completed``, ``close_brainlive_day`` short-circuits
with ``resumed_close_day`` BEFORE it consults ``force`` or ``begin_or_resume_run``.
So a SECOND live session on the same day would be skipped and never consolidated.

``--allow-rerun`` on ``run_phoneonly_close_day.py`` is the explicit service-side
reopen: it flips ONLY the day's own ``v18_close_day_runs`` row back to
``reopened`` (additive UPDATE via the core's own DB helpers — no core edit), so
the next ``close_brainlive_day`` proceeds, ``begin_or_resume_run`` creates a FRESH
pipeline run (the completed one is invisible to its active-only lookup), and every
stage replays on the CUMULATED data — idempotently (stable_id + upsert).

These tests assert:
  * reopen flips a completed day row to ``reopened`` (short-circuit no longer
    fires) and is a no-op on a missing / not-completed row;
  * a fresh close_brainlive_day after reopen creates a NEW pipeline run (no
    ``resumed_close_day``), i.e. the second session IS re-consolidated;
  * the SinglePhoneRuntimeManager arms allow_rerun on the second same-day session
    and the CloseDay subprocess command carries --allow-rerun.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
LIVE = ROOT / "services" / "live-pc"
SCRIPTS = ROOT / "scripts"
for _p in (SRC, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


close_day_script = _load("run_phoneonly_close_day", SCRIPTS / "run_phoneonly_close_day.py")
runtime_mod = _load("ms_runtime", LIVE / "phoneonly_runtime.py")


def test_close_day_removes_only_known_blackhole_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "localhost:9")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.test:8080")

    removed = close_day_script._sanitize_blackhole_proxy_env()

    assert removed
    assert not any(
        value in {"http://127.0.0.1:9", "localhost:9"}
        for name, value in close_day_script.os.environ.items()
        if name.lower() in {"http_proxy", "https_proxy", "all_proxy"}
    )
    assert close_day_script.os.environ["ALL_PROXY"] == "http://proxy.example.test:8080"


def _seed_completed_close_day(person_id: str, day: str, *, close_day_id: str = "cd-1"):
    """Insert a completed v18_close_day_runs row (as a first session would leave)."""
    from mlomega_audio_elite.v18_close_day import ensure_close_day_schema
    from mlomega_audio_elite.db import connect, write_transaction
    from mlomega_audio_elite.utils import now_iso

    ensure_close_day_schema()
    now = now_iso()
    with connect() as con, write_transaction(con):
        con.execute(
            """INSERT INTO v18_close_day_runs(
                 close_day_id,person_id,package_date,status,cleanup_eligible,result_json,
                 created_at,updated_at,completed_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (close_day_id, person_id, day, "completed", 1, '{"status":"completed"}', now, now, now),
        )


def _day_row(person_id: str, day: str):
    from mlomega_audio_elite.db import connect

    with connect() as con:
        row = con.execute(
            "SELECT status, cleanup_eligible, completed_at FROM v18_close_day_runs WHERE person_id=? AND package_date=?",
            (person_id, day),
        ).fetchone()
    return dict(row) if row is not None else None


def test_reopen_flips_completed_day_to_reopened(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))

    day = "2026-07-07"
    _seed_completed_close_day("owner", day)
    assert _day_row("owner", day)["status"] == "completed"

    report = close_day_script._reopen_completed_close_day(person_id="owner", package_date=day)
    assert report == {"reopened": True, "prior_status": "completed", "package_date": day}

    row = _day_row("owner", day)
    # No longer completed → close_brainlive_day's short-circuit will not fire.
    assert row["status"] == "reopened"
    assert row["cleanup_eligible"] == 0
    assert row["completed_at"] is None


def test_reopen_is_noop_when_absent_or_not_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))

    day = "2026-07-07"
    # Absent row → no-op.
    r1 = close_day_script._reopen_completed_close_day(person_id="owner", package_date=day)
    assert r1["reopened"] is False and r1["reason"] == "no_close_day_row"

    # A not-completed (running) row → no-op, left untouched.
    from mlomega_audio_elite.v18_close_day import ensure_close_day_schema
    from mlomega_audio_elite.db import connect, write_transaction
    from mlomega_audio_elite.utils import now_iso

    ensure_close_day_schema()
    now = now_iso()
    with connect() as con, write_transaction(con):
        con.execute(
            """INSERT INTO v18_close_day_runs(
                 close_day_id,person_id,package_date,status,cleanup_eligible,result_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            ("cd-run", "owner", day, "running", 0, "{}", now, now),
        )
    r2 = close_day_script._reopen_completed_close_day(person_id="owner", package_date=day)
    assert r2["reopened"] is False and r2["reason"] == "status_running"
    assert _day_row("owner", day)["status"] == "running"


def test_reopened_day_no_longer_short_circuits(tmp_path, monkeypatch):
    """After reopen, the load-existing check the short-circuit depends on no longer
    reports 'completed', so close_brainlive_day would proceed to a fresh run."""
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))

    day = "2026-07-07"
    _seed_completed_close_day("owner", day)

    from mlomega_audio_elite.v18_close_day import _load_existing_close_day

    before = _load_existing_close_day("owner", day)
    assert str(before["status"]) == "completed"  # would short-circuit

    close_day_script._reopen_completed_close_day(person_id="owner", package_date=day)
    after = _load_existing_close_day("owner", day)
    assert str(after["status"]) != "completed"  # short-circuit bypassed


def test_second_session_gets_fresh_pipeline_run_not_resumed(tmp_path, monkeypatch):
    """The core guarantee: after reopen, begin_or_resume_run with the SAME
    idempotency key returns a NEW run (resumed=False), because the first run is
    completed and its active-only lookup ignores it. This is what makes the second
    session re-run every stage on cumulated data instead of being short-circuited."""
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))

    from mlomega_audio_elite.governance_v18 import (
        Scope,
        begin_or_resume_run,
        ensure_v18_schema,
        update_run,
    )

    ensure_v18_schema()
    day = "2026-07-07"
    key = f"close_day_v18_7:owner:{day}"
    scope = Scope(person_id="owner", mode="maintenance")
    manifest = {"release": "x", "package_date": day, "person_id": "owner"}

    # First session's close-day run, then completed (as the first close-day leaves it).
    run1, resumed1 = begin_or_resume_run(
        pipeline_name="brainlive_close_day", scope=scope, input_manifest=manifest,
        idempotency_key=key, force_resume=False,
    )
    assert resumed1 is False
    update_run(run1, status="completed")

    # Re-issuing the SAME key now (second session) does NOT resume the completed
    # run — it creates a fresh, independent run.
    run2, resumed2 = begin_or_resume_run(
        pipeline_name="brainlive_close_day", scope=scope, input_manifest=manifest,
        idempotency_key=key, force_resume=False,
    )
    assert resumed2 is False
    assert run2 != run1


# --------------------------------------------------------------------------- runtime


class FakeIngress:
    def __init__(self, **_):
        self.on_audio_chunk = None
        self.on_receipt = None
        self.on_datachannel_open = None
        self.sent = []

    async def __aiter__(self):
        if False:
            yield None

    def send_ui_intent(self, p):
        return 0

    async def close(self):
        return None

    def stats(self):
        return {"peer_state": "new"}


class FakeConversation:
    live_session_id = "brainlive-x"
    metrics = {"conversation_turns": 1}

    def end_session(self, **_):
        return {"status": "ended"}


class FakePipeline:
    def __init__(self, *, ingress, **_):
        self.ingress = ingress
        self.conversation = FakeConversation()
        self.audio_archive = type("A", (), {"metrics": {"segments_archived": 1}})()
        self.end_calls = 0

    async def run_video(self):
        async for _ in self.ingress:
            pass

    def on_audio_chunk(self, *_):
        return []

    def end_session(self, **_):
        self.end_calls += 1

    def flush_audio(self):
        return []

    def release_live_resources(self):
        return None

    def metrics(self):
        return {"conversation_turns": 1, "keyframes_recorded": 1}


def test_manager_arms_allow_rerun_on_second_same_day_session(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "same-process.db"))
    close_kwargs = []

    async def scenario():
        manager = runtime_mod.SinglePhoneRuntimeManager(
            ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
            close_day=lambda **kw: close_kwargs.append(kw) or {"status": "completed"},
        )
        first = await manager.get_or_create("sess-1")
        assert first.allow_rerun is False  # first session of the day
        await first.end_and_close_day()
        assert first.close_day_status == "completed"
        # Second same-day session: the manager arms allow_rerun.
        second = await manager.get_or_create("sess-2")
        assert second.allow_rerun is True
        assert manager._completed_close_days == 1

    asyncio.run(scenario())


def test_manager_reads_completed_close_day_after_service_restart(tmp_path, monkeypatch):
    db = tmp_path / "restart.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    day = datetime.now().astimezone().date().isoformat()
    _seed_completed_close_day("owner", day)

    async def scenario():
        # Fresh manager: its in-memory counter is zero, exactly like a PC service
        # restart. The durable day row must still arm the reopen path.
        manager = runtime_mod.SinglePhoneRuntimeManager(
            person_id="owner",
            db_path=db,
            ingress_factory=FakeIngress,
            pipeline_factory=FakePipeline,
            close_day=lambda **_: {"status": "completed"},
        )
        runtime = await manager.get_or_create("transport-after-restart")
        assert manager._completed_close_days == 0
        assert runtime.allow_rerun is True

    asyncio.run(scenario())


def test_retention_failure_is_persisted_without_reclassifying_close_day(tmp_path, monkeypatch):
    db_path = tmp_path / "maintenance.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    report = close_day_script._record_maintenance_report(
        run_id="close-run",
        person_id="owner",
        package_date="2026-07-10",
        live_session_id="live-one",
        clip_tiering={"status": "ok", "warnings": []},
        media_retention={"status": "error", "error": "disk locked", "warnings": []},
    )
    assert report["status"] == "error"
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        row = con.execute(
            """SELECT status,errors_json FROM phoneonly_close_day_maintenance_v19
               WHERE run_id=? AND live_session_id=?""",
            ("close-run", "live-one"),
        ).fetchone()
    assert row["status"] == "error"
    assert "disk locked" in row["errors_json"]


def test_close_day_subprocess_command_carries_allow_rerun(monkeypatch):
    """The subprocess CloseDay command includes --allow-rerun for a rerun session,
    and omits it otherwise (verified without spawning a real process)."""
    captured = {}

    class FakeProc:
        stdout = '{"status": "completed"}'
        stderr = ""

    def fake_run(cmd, **_):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(runtime_mod.subprocess if hasattr(runtime_mod, "subprocess") else __import__("subprocess"), "run", fake_run)
    # Patch the module-level subprocess.run used inside _run_close_day.
    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", fake_run)
    # Ensure the "core python missing" guard passes by faking the interpreter path.
    monkeypatch.setattr(runtime_mod.Path, "exists", lambda self: True)

    rt = runtime_mod.PhoneOnlyRuntime(
        "sess-2", person_id="owner",
        ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        allow_rerun=True,
    )
    rt._run_close_day(person_id="owner", live_session_id="live-2")
    assert "--allow-rerun" in captured["cmd"]

    captured.clear()
    rt2 = runtime_mod.PhoneOnlyRuntime(
        "sess-1", person_id="owner",
        ingress_factory=FakeIngress, pipeline_factory=FakePipeline,
        allow_rerun=False,
    )
    rt2._run_close_day(person_id="owner", live_session_id="live-1")
    assert "--allow-rerun" not in captured["cmd"]
