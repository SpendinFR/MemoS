#!/usr/bin/env python
"""E30-A autonomous runner (core-venv phase).

Runs the heavy, LLM/VLM-real part of the E30-A overnight validation:

  * seed a synthetic 30-day life for MLOMEGA_PERSON_ID in the REAL foyer DB
    (simulators.synthetic_life.run_synthetic_life), then
  * run a REAL close-day (use_llm=True) for 3 representative days (the last day
    and 2 earlier ones), timing each stage, capturing close_day_status; then
  * collect DB counters (predictions, self_schema, life-model deltas, visual
    events) and write a JSON summary the PowerShell wrapper folds into
    E30A_REPORT.md.

This module is imported/run with the CORE .venv (torch/whisperx) because
close_brainlive_day pulls in the deep pipeline. It must be launched with
PYTHONPATH including `src` and the project root (so `simulators` resolves);
E30A_RUN.ps1 sets that up. Every phase is guarded: a failure is recorded and
the run continues so the night never stops silently.

Usage (invoked by E30A_RUN.ps1):
  python scripts/e30a_runner.py --person me --days 30 --out <json> [--skip-seed]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _db_path() -> Path | None:
    """Resolve MLOMEGA_DB to a Path (db.connect() / store helpers require a Path,
    not a str: they call path.parent.mkdir). None -> the store falls back to the
    config-derived db_path (also from MLOMEGA_DB)."""
    raw = os.environ.get("MLOMEGA_DB")
    return Path(raw).expanduser() if raw else None


def _counters(person_id: str) -> dict:
    """Best-effort DB counters for the report. Never raises."""
    out: dict = {}
    try:
        from mlomega_audio_elite.db import connect
    except Exception as exc:  # pragma: no cover
        return {"_error": f"connect import failed: {exc}"}
    db = _db_path()
    queries = {
        "visual_events_total": "SELECT COUNT(*) FROM visual_events_v19 WHERE person_id=?",
        "visual_events_object_moved": "SELECT COUNT(*) FROM visual_events_v19 WHERE person_id=? AND event_type='object_moved'",
        "predictions_total": "SELECT COUNT(*) FROM prediction_outcomes_v19 WHERE person_id=?",
        "predictions_verified": "SELECT COUNT(*) FROM prediction_outcomes_v19 WHERE person_id=? AND status='verified'",
        "predictions_refuted": "SELECT COUNT(*) FROM prediction_outcomes_v19 WHERE person_id=? AND status='refuted'",
        "self_schema_entries": "SELECT COUNT(*) FROM self_schema_v19 WHERE person_id=?",
        "self_schema_conditional": "SELECT COUNT(*) FROM self_schema_v19 WHERE person_id=? AND entry_type='conditionnel'",
        "spatial_routines": "SELECT COUNT(*) FROM brain2_spatial_routine_models WHERE person_id=?",
        "life_model_entries": "SELECT COUNT(*) FROM life_model_entries_v19 WHERE person_id=?",
    }
    try:
        with connect(db) as con:
            for key, sql in queries.items():
                try:
                    out[key] = con.execute(sql, (person_id,)).fetchone()[0]
                except Exception as exc:
                    out[key] = f"n/a ({type(exc).__name__})"
    except Exception as exc:
        out["_error"] = f"counter query failed: {exc}"
    return out


def phase_seed(person_id: str, days: int, report: dict) -> None:
    started = time.monotonic()
    try:
        from simulators.synthetic_life import run_synthetic_life
        from mlomega_audio_elite.v19_visual_store import ensure_v19_visual_schema

        db = _db_path()
        if db:
            db.parent.mkdir(parents=True, exist_ok=True)
            ensure_v19_visual_schema(db)
        _log(f"seed: run_synthetic_life(person_id={person_id!r}, days={days}) -> real DB {db}")
        result = run_synthetic_life(person_id=person_id, days=days, db_path=db)
        report["seed"] = {"ok": True, "seconds": round(time.monotonic() - started, 2), "result": result}
        _log(f"seed: OK in {report['seed']['seconds']}s -> {result}")
    except Exception as exc:
        report["seed"] = {
            "ok": False,
            "seconds": round(time.monotonic() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        _log(f"seed: FAILED {type(exc).__name__}: {exc}")


def _representative_days(days: int) -> list[str]:
    """Last day + 2 earlier representative ones (June 2026 month)."""
    idxs = sorted({days, max(1, days // 2), max(1, days - 7)})
    return [f"2026-06-{min(d, 30):02d}" for d in idxs]


def phase_close_day(person_id: str, days: int, report: dict) -> None:
    report["close_days"] = []
    try:
        from mlomega_audio_elite.v18_close_day import (
            close_brainlive_day,
            close_day_status,
            ensure_close_day_schema,
        )
        ensure_close_day_schema()
    except Exception as exc:
        report["close_day_import_error"] = f"{type(exc).__name__}: {exc}"
        _log(f"close-day: import FAILED {exc}")
        return

    for day in _representative_days(days):
        entry: dict = {"package_date": day}
        started = time.monotonic()
        _log(f"close-day: REAL close_brainlive_day(person_id={person_id!r}, package_date={day}, use_llm=True) ...")
        try:
            res = close_brainlive_day(person_id=person_id, package_date=day, use_llm=True)
            elapsed = round(time.monotonic() - started, 2)
            stages = res.get("stages", {}) if isinstance(res, dict) else {}
            stage_timing = {}
            if isinstance(stages, dict):
                for sname, sval in stages.items():
                    if isinstance(sval, dict):
                        stage_timing[sname] = {
                            k: sval.get(k)
                            for k in ("status", "duration_s", "seconds", "elapsed_s", "gpu_phase", "attempts")
                            if k in sval
                        }
                    else:
                        stage_timing[sname] = sval
            entry.update({
                "ok": True,
                "seconds": elapsed,
                "status": res.get("status") if isinstance(res, dict) else None,
                "run_id": res.get("run_id") if isinstance(res, dict) else None,
                "resumed": res.get("resumed") if isinstance(res, dict) else None,
                "cleanup_eligible": (res.get("cleanup", {}) or {}).get("eligible") if isinstance(res, dict) else None,
                "stages": stage_timing,
            })
            _log(f"close-day {day}: status={entry['status']} in {elapsed}s, {len(stage_timing)} stages")
        except Exception as exc:
            entry.update({
                "ok": False,
                "seconds": round(time.monotonic() - started, 2),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            _log(f"close-day {day}: FAILED {type(exc).__name__}: {exc}")

        # Status snapshot (best-effort, independent of the run outcome).
        try:
            entry["final_status"] = close_day_status(person_id=person_id, package_date=day)
        except Exception as exc:
            entry["final_status_error"] = f"{type(exc).__name__}: {exc}"

        report["close_days"].append(entry)


def main() -> int:
    ap = argparse.ArgumentParser(description="E30-A core-venv runner (seed + real close-day + counters).")
    ap.add_argument("--person", default=os.environ.get("MLOMEGA_PERSON_ID", "me"))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True, help="path to the JSON summary written for the PS wrapper")
    ap.add_argument("--skip-seed", action="store_true", help="skip the 30-day synthetic seed (reuse existing DB)")
    args = ap.parse_args()

    report: dict = {
        "started_at": _now(),
        "person_id": args.person,
        "days": args.days,
        "db_path": str(_db_path()) if _db_path() else None,
        "python": sys.version.split()[0],
        "executable": sys.executable,
    }

    _log(f"E30-A runner start: person={args.person} days={args.days} db={_db_path()}")
    report["counters_before"] = _counters(args.person)

    if args.skip_seed:
        report["seed"] = {"ok": True, "skipped": True}
        _log("seed: skipped (--skip-seed)")
    else:
        phase_seed(args.person, args.days, report)

    phase_close_day(args.person, args.days, report)

    report["counters_after"] = _counters(args.person)
    report["finished_at"] = _now()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"E30-A runner done -> {out}")

    # Exit 0 even on per-phase failures: the report captures them and the night
    # must not abort. Only a total inability to write the report is a hard error.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"[FATAL] e30a_runner: {exc}", flush=True)
        traceback.print_exc()
        sys.exit(1)
