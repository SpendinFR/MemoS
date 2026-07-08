from __future__ import annotations

"""Resume-safe PhoneOnly CloseDay worker.

Normally a close-day is idempotent per (person_id, package_date): once the day's
``v18_close_day_runs`` row is ``completed``, ``close_brainlive_day`` short-circuits
and returns the cached result (``resumed_close_day``) BEFORE it ever consults
``force`` or ``begin_or_resume_run``. That is correct for a crash/resume of the
SAME session, but it means a SECOND live session on the SAME day is skipped — its
turns/audio never reach a close-day and are not consolidated.

``--allow-rerun`` (E47-C livrable 6, multi-session/day) is the explicit,
service-side reopen path. It does NOT touch the core: it flips only the day's own
``v18_close_day_runs`` row from ``completed`` back to a resolvable status
(``reopened``) via the core's own DB helpers (additive UPDATE on an existing
row). With the day row no longer ``completed``, the next ``close_brainlive_day``
call proceeds past the short-circuit; ``begin_or_resume_run`` finds no ACTIVE
pipeline run for the idempotency key (the previous one is ``completed`` and the
lookup only matches ``started``/``running``), so it creates a FRESH run and
re-executes every stage on the CUMULATED data of both sessions. Re-run is
idempotent by construction: each stage keys its writes on ``stable_id`` and
upserts (visual_consolidation moves/routines, life_model_v19 entries, etc.), so a
replay updates the same rows instead of duplicating assembler/bundle output.

See docs/DECISIONS.md §E47C for the ADR (why reopen-by-status, not delete/force).
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reopen_completed_close_day(*, person_id: str, package_date: str | None) -> dict:
    """Flip today's completed close-day row back to a resolvable status.

    Additive service-side reopen: touches ONLY the day's own row in
    ``v18_close_day_runs`` (an existing, non-core-owned status column), through the
    core's ``connect``/``write_transaction`` — no core code is modified. Returns a
    small report of what changed. A missing or not-completed row is a no-op (the
    normal resume path already handles those)."""
    from mlomega_audio_elite.v18_close_day import (
        _package_day,
        ensure_close_day_schema,
    )
    from mlomega_audio_elite.db import connect, write_transaction
    from mlomega_audio_elite.utils import now_iso

    ensure_close_day_schema()
    day = _package_day(package_date)
    with connect() as con, write_transaction(con):
        row = con.execute(
            "SELECT close_day_id, status FROM v18_close_day_runs WHERE person_id=? AND package_date=?",
            (person_id, day),
        ).fetchone()
        if row is None:
            return {"reopened": False, "reason": "no_close_day_row", "package_date": day}
        prior_status = str(row["status"])
        if prior_status != "completed":
            return {"reopened": False, "reason": f"status_{prior_status}", "package_date": day}
        # Reopen: a non-completed status lets close_brainlive_day proceed. We keep
        # cleanup_eligible=0 so no raw purge is authorised until the re-run
        # re-establishes the gate; the completed pipeline run is left intact and a
        # fresh one is created on the next close_brainlive_day call.
        con.execute(
            """UPDATE v18_close_day_runs
                 SET status='reopened', cleanup_eligible=0, updated_at=?, completed_at=NULL
               WHERE person_id=? AND package_date=?""",
            (now_iso(), person_id, day),
        )
    return {"reopened": True, "prior_status": "completed", "package_date": day}


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume-safe PhoneOnly CloseDay worker")
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--live-session-id", required=True)
    parser.add_argument("--package-date", default=None)
    parser.add_argument(
        "--allow-rerun",
        action="store_true",
        help="reopen today's completed close-day so a second same-day session is consolidated (E47-C)",
    )
    args = parser.parse_args()

    from mlomega_audio_elite.v18_close_day import close_brainlive_day

    reopen_report = None
    if args.allow_rerun:
        reopen_report = _reopen_completed_close_day(
            person_id=args.person_id, package_date=args.package_date
        )

    result = close_brainlive_day(
        person_id=args.person_id,
        live_session_id=args.live_session_id,
        package_date=args.package_date,
        # force bypasses only a safety backoff; the reopen above is what actually
        # un-skips a completed day, so pair them for an explicit second session.
        force=bool(args.allow_rerun),
    )
    if reopen_report is not None:
        result = {**result, "reopen": reopen_report}

    # E54: media retention runs ONLY after the close-day has authorised cleanup
    # (cleanup.eligible == True — the gate the pipeline sets once every stage,
    # incl. the deep-audio re-transcription, is done). Best-effort: a failing
    # purge/transcode never fails the close-day (the exit code stays driven by
    # the close-day status alone).
    cleanup = result.get("cleanup") if isinstance(result, dict) else None
    if isinstance(cleanup, dict) and bool(cleanup.get("eligible")):
        # E55 tiering runs BEFORE E54 retention: it demotes boring/unreferenced
        # clips to keyframes-only (deletes the MP4 + its asset row), then E54
        # applies age-purge/budget on what remains. Both are best-effort.
        clip_tiering = _run_clip_tiering(person_id=args.person_id)
        retention = _run_media_retention(person_id=args.person_id)
        result = {**result, "clip_tiering": clip_tiering, "media_retention": retention}

    print(json.dumps(result, ensure_ascii=False))
    return 0 if str(result.get("status")) == "completed" else 2


def _run_media_retention(*, person_id: str) -> dict:
    """Invoke the E54 retention module (services/live-pc/media_retention.py).

    Loaded by file path — it lives under the live-pc service tree, not the ``src``
    package. Never raises: any error is returned as a small report so it cannot
    fail the close-day."""
    try:
        import importlib.util

        mod_path = ROOT / "services" / "live-pc" / "media_retention.py"
        spec = importlib.util.spec_from_file_location("v19_media_retention", mod_path)
        if spec is None or spec.loader is None:
            return {"status": "error", "error": "media_retention module not found"}
        module = importlib.util.module_from_spec(spec)
        sys.modules["v19_media_retention"] = module
        spec.loader.exec_module(module)
        return module.run_media_retention(person_id=person_id)
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:160]}


def _run_clip_tiering(*, person_id: str) -> dict:
    """Invoke the E55 clip tiering (services/live-pc/clip_recorder.py).

    Loaded by file path — same pattern as media_retention. Never raises: any
    error is returned as a small report so it cannot fail the close-day."""
    try:
        import importlib.util

        mod_path = ROOT / "services" / "live-pc" / "clip_recorder.py"
        spec = importlib.util.spec_from_file_location("v19_clip_recorder", mod_path)
        if spec is None or spec.loader is None:
            return {"status": "error", "error": "clip_recorder module not found"}
        module = importlib.util.module_from_spec(spec)
        sys.modules["v19_clip_recorder"] = module
        spec.loader.exec_module(module)
        return module.tier_clips_close_day(person_id=person_id)
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:160]}


if __name__ == "__main__":
    raise SystemExit(main())
