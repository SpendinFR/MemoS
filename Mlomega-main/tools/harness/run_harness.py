from __future__ import annotations

"""E63 harness orchestrator.

Two modes:
  * default   : start the REAL product server (services/live-pc/sessionhub_http.py)
                in a subprocess using the .venv-live interpreter on a dedicated
                test port, run the fake device, fold /metrics into the report,
                run the DB assertions, then tear the server down cleanly.
  * --attach  : do not spawn; use an already-running SessionHub at --host/--port
                (useful to point the harness at the real 8710 server).

The scratch DB: unless --db is given, a fresh <scratch>/harness_memory.db is used
and MLOMEGA_DB is exported to the server subprocess so the run never touches the
real memory.db. In --attach mode the DB is whatever the attached server uses; pass
--db to point the assertions at it.

--with-close-day runs the FULL nightly close-day (WhisperX GPU, heavy) via the
product's own subprocess into the core .venv. OFF by default. The close-day is
triggered by /session/end inside the device run; here the flag only widens the
assertions and lengthens the wait.

New file only; spawns the product server unmodified.
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

sys.path.insert(0, str(HERE))
import fake_xr_device as fxr  # noqa: E402
import assertions as asrt  # noqa: E402


def _venv_python() -> Path:
    py = ROOT / ".venv-live" / "Scripts" / "python.exe"
    if not py.exists():
        raise RuntimeError(f".venv-live python missing: {py}")
    return py


def _http_get(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _wait_health(host: str, port: int, *, timeout_s: float, require_pairing: bool = True) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        got = _http_get(f"http://{host}:{port}/health", timeout=1.5)
        if got is not None:
            last = got
            if not require_pairing or got.get("pairing_ready"):
                return last
        time.sleep(1.0)
    return last


def _fetch_metrics(host: str, port: int) -> dict[str, Any]:
    got = _http_get(f"http://{host}:{port}/metrics", timeout=3.0)
    return got or {}


def start_server(host: str, port: int, db: Path, *, log: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["MLOMEGA_DB"] = str(db.resolve())
    # Production default: the GPU phase orchestration (preflight tests P1 then
    # stops it; live runs Ollama only; night text/vision phases swap P1/VLM) must
    # be ACTIVE without a manual export. Explicit "0" remains the rollback.
    env.setdefault("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    py = _venv_python()
    cmd = [
        str(py), str(ROOT / "services" / "live-pc" / "sessionhub_http.py"),
        "--host", host, "--port", str(port),
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E63 harness orchestrator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8730)
    parser.add_argument("--attach", action="store_true", help="use an already-running server")
    parser.add_argument("--db", default=None, help="sqlite DB path (default scratch harness DB)")
    parser.add_argument("--media", default=None)
    parser.add_argument("--scenario", default=str(fxr.DEFAULT_SCENARIO))
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--session-id", dest="session_id", default="e63-harness")
    parser.add_argument("--with-close-day", action="store_true")
    parser.add_argument("--no-end-session", dest="end_session", action="store_false", default=True)
    parser.add_argument("--person-id", default="me")
    parser.add_argument("--server-timeout", type=float, default=120.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--synth-seconds", type=int, default=30)
    args = parser.parse_args(argv)

    scratch = HERE / "_run"
    scratch.mkdir(parents=True, exist_ok=True)
    db = Path(args.db).resolve() if args.db else (scratch / "harness_memory.db").resolve()
    if not args.attach and args.db is None and db.exists():
        # Fresh DB per spawned run so assertions are unambiguous.
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db) + suffix)
            if p.exists():
                p.unlink()

    proc: subprocess.Popen | None = None
    server_log = scratch / "server.log"
    try:
        if not args.attach:
            print(f"[harness] starting server on {args.host}:{args.port} (db={db})")
            proc = start_server(args.host, args.port, db, log=server_log)
        health = _wait_health(
            args.host, args.port, timeout_s=args.server_timeout, require_pairing=True
        )
        if not health.get("pairing_ready"):
            print(f"[harness] server not pairing_ready: {json.dumps(health)[:800]}")
            if proc is not None and proc.poll() is not None:
                print(f"[harness] server exited early; tail of {server_log}:")
                print(server_log.read_text(encoding='utf-8', errors='replace')[-2000:])
            return 3
        print(f"[harness] pairing_ready (ai_ready={health.get('ai_ready')})")

        # Build media (synthetic if not provided) before running the device.
        if args.media:
            media = Path(args.media)
        else:
            media = fxr.synth_media_mp4(scratch / "harness_media.mp4", duration=int(args.synth_seconds))

        scenario = fxr.load_scenario(Path(args.scenario))
        device = fxr.FakeXrDevice(
            host=args.host, port=args.port, media=media, scenario=scenario,
            device_id=args.session_id, duration=args.duration, end_session=args.end_session,
        )
        report = asyncio.run(device.run())

        if args.with_close_day and args.end_session:
            # /session/end already kicked start_close_day; poll status until the
            # heavy subprocess finishes (bounded).
            print("[harness] waiting for close-day to complete (heavy)...")
            _poll_close_day(args.host, args.port, report, timeout_s=1800.0)

        metrics = _fetch_metrics(args.host, args.port)
        active = (metrics or {}).get("active") or {}
        report["server_metrics_active"] = active
        report["ui_intents_delivered"] = active.get("ui_intents_delivered", 0)
        report["server_close_day"] = active.get("close_day")

        report_path = scratch / "device_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        res = asrt.run_assertions(
            db=db, person_id=args.person_id,
            with_close_day=args.with_close_day, report=report,
        )
        print(res.render())
        summary = {"ok": res.ok, "report": report, "checks": res.checks, "db": str(db)}
        if args.out:
            Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 0 if res.ok else 1
    finally:
        if proc is not None:
            print("[harness] stopping server")
            stop_server(proc)


def _poll_close_day(host: str, port: int, report: dict[str, Any], *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    sid = report.get("session_id")
    tok = None  # close-day status is available via /metrics without the token.
    while time.monotonic() < deadline:
        metrics = _fetch_metrics(host, port)
        active = (metrics or {}).get("active") or {}
        state = active.get("close_day")
        if state in {"completed", "error"}:
            report["server_close_day"] = state
            return
        # A failed end can never start CloseDay. Waiting the full 30-minute
        # nightly budget here hid the real transport/drain failure and produced
        # a bogus performance measurement. Preserve the explicit boundary and
        # return immediately so assertions report the right failure.
        if active.get("end_session") == "error" and state == "not_started":
            report["server_close_day"] = state
            report["end_session_status"] = "error"
            report.setdefault("errors", []).append(
                "close_day_not_started_after_end_session_error"
            )
            return
        time.sleep(5.0)


if __name__ == "__main__":
    sys.exit(main())
