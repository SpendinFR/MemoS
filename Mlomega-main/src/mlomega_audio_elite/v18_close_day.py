from __future__ import annotations

"""V18.4 one-command end-of-day orchestration.

This module deliberately keeps V13-V17 as the substantive engines.  It adds a
single durable day-level coordinator that runs *after* the session-scoped
post-stop flow has retained its outputs:

    post-stop session -> V17 day longitudinal -> V15.12 coordination
    -> V15.13 Life Model -> V15.9 live-ready projection -> cleanup gate

The coordinator is idempotent per person/day.  A raw-media purge is never
performed here; callers (for example the Phone Bridge) must first receive a
positive ``cleanup`` result and may then delete only their own raw files.
"""

from dataclasses import dataclass
from typing import Any, Callable

from .db import connect, init_db, upsert, write_transaction
from .config import get_settings
from .runtime_v18_7 import acquire_execution_lease, classify_failure, heartbeat_execution_lease, record_phase_event
from .governance_v18 import (
    Scope,
    StageGateError,
    assert_cleanup_eligible,
    begin_or_resume_run,
    ensure_v18_schema,
    finish_stage,
    record_output_manifest,
    start_stage,
    strict_one,
    update_run,
    mark_run_retryable,
    record_recovery_state,
    recovery_state,
    recover_stale_stages,
)
from .utils import json_dumps, json_loads, now_iso, stable_id

VERSION = "18.7.1-resumable-close-day"

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS v18_close_day_runs(
  close_day_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  live_session_id TEXT,
  service_run_id TEXT,
  post_stop_run_id TEXT,
  status TEXT NOT NULL,
  cleanup_eligible INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_eligible IN (0,1)),
  result_json TEXT NOT NULL DEFAULT '{}',
  error_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(person_id, package_date)
);
CREATE INDEX IF NOT EXISTS idx_v18_close_day_person_date
  ON v18_close_day_runs(person_id, package_date, updated_at);
"""


@dataclass(frozen=True)
class _Context:
    person_id: str
    package_date: str
    live_session_id: str | None
    service_run_id: str | None


def ensure_close_day_schema() -> None:
    init_db()
    # A direct ``brainlive-close-day`` may be run after a manual stop, without
    # the long-lived service import having previously created its state tables.
    # Install that schema before resolving the last run; this is additive and
    # keeps the command safe on a newly initialized V18 database.
    from .brainlive_service_v15_5 import ensure_service_schema
    from .brainlive_poststop_deep_flow_v15_15 import ensure_post_stop_deep_flow_schema
    ensure_service_schema()
    ensure_post_stop_deep_flow_schema()
    ensure_v18_schema()
    with connect() as con, write_transaction(con):
        con.executescript(SCHEMA)


def _one(con: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    return strict_one(con, sql, params, purpose="close-day query")


def _status_ok(result: Any, *, stage_name: str) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    allowed = {
        "post_stop": {"completed"},
        "longitudinal": {"ok", "completed"},
        "coordination": {"ok", "completed"},
        # V15.13 returns ``llm_patch_ready`` for a patch and bootstrap embeds
        # the V15.10 status in ``bootstrap``.
        # These are successful epistemic outcomes, not processing failures:
        # ``compiled_watch_only`` persists a first observation without promoting
        # it, while ``compiled_no_life_delta`` is the idempotent resume verdict
        # after every durable source revision has already been consumed.
        "life_model": {
            "llm_patch_ready", "compiled_watch_only",
            "compiled_no_life_delta", "ok", "completed", "active",
        },
        "live_ready": {"active", "ok", "completed", "llm_ready"},
        "visual_consolidation": {"completed", "ok"},
        "outcome_resolution": {"completed", "ok"},
        "life_model_v19": {"completed", "ok"},
        "prediction_emission": {"completed", "ok"},
        "self_schema": {"completed", "ok"},
    }
    if stage_name == "life_model" and result.get("mode") == "bootstrap_v15_10":
        bootstrap = result.get("bootstrap") or {}
        return isinstance(bootstrap, dict) and str(bootstrap.get("status") or "").lower() in {"llm_ready", "abstained_no_owner_evidence", "ok", "completed", "active"}
    return status in allowed.get(stage_name, {"ok", "completed"})


def _stage_identifier(name: str, result: dict[str, Any]) -> str:
    keys = {
        "post_stop": ("run_id",),
        "longitudinal": ("run_id",),
        "coordination": ("run_id",),
        "life_model": ("patch_run_id",),
        "live_ready": ("export_id",),
        "visual_consolidation": ("summary_id",),
        "outcome_resolution": ("count",),
        "life_model_v19": ("count",),
        "prediction_emission": ("count",),
        "self_schema": ("count",),
    }
    for key in keys.get(name, ()):
        if result.get(key):
            return f"{name}:{result[key]}"
    if name == "life_model":
        bootstrap = result.get("bootstrap") or {}
        if isinstance(bootstrap, dict) and bootstrap.get("export_id"):
            return f"life_model:{bootstrap['export_id']}"
    if result.get("stage") or name in {"visual_consolidation", "outcome_resolution", "life_model_v19", "prediction_emission", "self_schema"}:
        return f"{name}:{stable_id(name, result.get('summary_id'), result.get('count'), result.get('package_date'))}"
    raise StageGateError(f"close-day {name} returned no durable identifier")


_CLOSE_DAY_REQUIRED_STAGES = (
    "post_stop",
    "visual_consolidation",
    "longitudinal",
    "coordination",
    "life_model",
    "outcome_resolution",
    "life_model_v19",
    "prediction_emission",
    "self_schema",
    "live_ready",
)


def _stage_artifacts(name: str, result: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Return (manifest id, table, pk column, pk value) for actual outputs."""
    artifacts: list[tuple[str, str, str, str]] = []

    def add(table: str, column: str, value: Any) -> None:
        if value:
            text = str(value)
            artifacts.append((f"{name}:{text}", table, column, text))

    if name == "post_stop":
        add("v18_pipeline_runs", "run_id", result.get("run_id"))
    elif name == "visual_consolidation":
        add("scene_session_summaries_v19", "scene_summary_id", result.get("summary_id"))
    elif name == "longitudinal":
        day = result.get("day") if isinstance(result.get("day"), dict) else result
        add("brain2_longitudinal_runs_v17", "run_id", day.get("run_id"))
    elif name == "coordination":
        add("brain2_brainlive_coordination_runs", "run_id", result.get("run_id"))
    elif name == "life_model":
        add("brain2_life_model_patch_runs", "patch_run_id", result.get("patch_run_id"))
        bootstrap = result.get("bootstrap") or {}
        if isinstance(bootstrap, dict):
            add("brain2_life_model_exports", "export_id", bootstrap.get("export_id"))
    elif name == "outcome_resolution":
        for value in result.get("outcome_ids") or []:
            add("prediction_outcomes_v19", "outcome_id", value)
    elif name == "life_model_v19":
        for key in ("confirmed", "contradicted", "weakened"):
            for value in result.get(key) or []:
                add("life_model_entries_v19", "entry_id", value)
        projected = result.get("projected") if isinstance(result.get("projected"), dict) else {}
        for key in ("created", "updated"):
            for value in projected.get(key) or []:
                add("life_model_entries_v19", "entry_id", value)
    elif name == "prediction_emission":
        for value in result.get("prediction_ids") or []:
            add("predictions_v19", "prediction_id", value)
    elif name == "self_schema":
        for value in result.get("schema_entry_ids") or []:
            add("self_schema_v19", "schema_entry_id", value)
    elif name == "live_ready":
        add("brainlive_personal_model_exports", "export_id", result.get("export_id"))
    # One target can be present in two result buckets (for example an entry
    # weakened then confirmed during a resumed day); it is still one artifact.
    return list(dict.fromkeys(artifacts))


def _verified_close_day_outputs(
    *, run_id: str, person_id: str, stage_results: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Build expected outputs and independently observe their durable rows.

    Stage markers are a static contract.  They are observed only by re-reading a
    completed, semantically valid checkpoint.  Every concrete id returned by a
    stage is additionally looked up in its owning table and owner scope.  This
    prevents the former ``observed=list(expected)`` circular proof.
    """
    expected = [f"stage:{name}" for name in _CLOSE_DAY_REQUIRED_STAGES]
    observed: list[str] = []
    artifact_specs: list[tuple[str, str, str, str]] = []
    for name in _CLOSE_DAY_REQUIRED_STAGES:
        artifact_specs.extend(_stage_artifacts(name, stage_results[name]))
    expected.extend(identifier for identifier, _, _, _ in artifact_specs)
    expected = list(dict.fromkeys(expected))

    with connect() as con:
        checkpoints = {
            str(row["stage_name"]): dict(row)
            for row in con.execute(
                """SELECT stage_name,status,result_json FROM v18_pipeline_stages
                   WHERE run_id=?""",
                (run_id,),
            ).fetchall()
        }
        for name in _CLOSE_DAY_REQUIRED_STAGES:
            row = checkpoints.get(name)
            cached = json_loads(row.get("result_json"), {}) if row else {}
            if (
                row
                and str(row.get("status")) == "completed"
                and isinstance(cached, dict)
                and _status_ok(cached, stage_name=name)
            ):
                observed.append(f"stage:{name}")

        for identifier, table, column, value in artifact_specs:
            table_exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if table_exists is None:
                continue
            row = con.execute(
                f"SELECT 1 FROM {table} WHERE {column}=? AND person_id=? LIMIT 1",
                (value, person_id),
            ).fetchone()
            if row is not None:
                observed.append(identifier)
    return expected, list(dict.fromkeys(observed))


def _package_day(value: str | None) -> str:
    from .brainlive_poststop_deep_flow_v15_15 import _package_day as post_stop_day
    return post_stop_day(value)


def _due_longitudinal_periods(day: str) -> list[str]:
    """E54: which week/month rollups are due when closing ``day`` (YYYY-MM-DD).

    ``week`` when ``day`` is a Sunday (ISO end-of-week), ``month`` when ``day`` is
    the last day of its month — so each rollup consolidates a COMPLETE period. Any
    parse issue yields no extra period (day-only, the safe default).
    """
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(day)[:10])
    except Exception:
        return []
    due: list[str] = []
    if d.isoweekday() == 7:  # Sunday closes the ISO week
        due.append("week")
    next_day = d + _dt.timedelta(days=1)
    if next_day.month != d.month:  # last day of the month
        due.append("month")
    return due


def _semantic_output_warnings(
    *, person_id: str, package_date: str, stage_results: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Report semantically empty outputs without making an empty day fail.

    The durable manifest proves every returned id.  These checks cover the other
    direction: eligible durable inputs that unexpectedly produced no output.
    """
    warnings: list[dict[str, Any]] = []
    canonical_tables = (
        "brain2_personal_routine_models", "brain2_place_preference_models",
        "brain2_action_preference_models", "brain2_need_expectation_models",
        "brain2_expression_state_models", "brain2_emotional_trajectory_models",
        "brain2_contextual_self_models", "brain2_live_prediction_hooks",
        "brain2_live_affordance_preferences",
    )
    with connect() as con:
        def table_exists(name: str) -> bool:
            return con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone() is not None

        canonical_count = 0
        for table in canonical_tables:
            if table_exists(table):
                canonical_count += int(con.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE person_id=? AND status IN ('active','confirmed','candidate')",
                    (person_id,),
                ).fetchone()[0])
        if canonical_count and int((stage_results.get("life_model_v19") or {}).get("count") or 0) == 0:
            warnings.append({
                "code": "life_model_v19_empty_with_canonical_inputs",
                "eligible_inputs": canonical_count,
            })

        eligible_predictions = 0
        if table_exists("life_model_entries_v19"):
            rows = con.execute(
                "SELECT verification_spec_json,prediction_template_json FROM life_model_entries_v19 "
                "WHERE person_id=? AND status IN ('active','confirmed')",
                (person_id,),
            ).fetchall()
            for row in rows:
                spec = json_loads(row["verification_spec_json"], {}) or json_loads(row["prediction_template_json"], {})
                if isinstance(spec, dict) and "visual_events_v19" in {
                    str(x) for x in (spec.get("sources") or spec.get("observation_sources") or [])
                } and any(spec.get(key) for key in ("event_type", "entity_label", "place_label", "observation_contains")):
                    eligible_predictions += 1
        if eligible_predictions and not ((stage_results.get("prediction_emission") or {}).get("prediction_ids") or []):
            warnings.append({
                "code": "prediction_emission_empty_with_eligible_entries",
                "eligible_inputs": eligible_predictions,
            })

        schema_inputs = 0
        if table_exists("life_model_entries_v19"):
            schema_inputs += int(con.execute(
                "SELECT COUNT(*) FROM life_model_entries_v19 WHERE person_id=? "
                "AND status IN ('active','confirmed','weakening')", (person_id,)
            ).fetchone()[0])
        if table_exists("confirmed_patterns"):
            schema_inputs += int(con.execute(
                "SELECT COUNT(*) FROM confirmed_patterns WHERE person_id=? "
                "AND validity_status IN ('active','confirmed')", (person_id,)
            ).fetchone()[0])
        if schema_inputs and not ((stage_results.get("self_schema") or {}).get("schema_entry_ids") or []):
            warnings.append({
                "code": "self_schema_empty_with_eligible_inputs",
                "eligible_inputs": schema_inputs,
            })

        longitudinal = stage_results.get("longitudinal") or {}
        for period in _due_longitudinal_periods(package_date):
            period_result = longitudinal.get(period) if isinstance(longitudinal.get(period), dict) else {}
            run_id = str((period_result or {}).get("run_id") or "")
            durable = bool(run_id) and table_exists("brain2_longitudinal_runs_v17") and con.execute(
                "SELECT 1 FROM brain2_longitudinal_runs_v17 "
                "WHERE run_id=? AND person_id=? AND period=? AND status IN ('ok','completed')",
                (run_id, person_id, period),
            ).fetchone() is not None
            if not durable:
                warnings.append({
                    "code": "longitudinal_rollup_not_durably_observed",
                    "period": period,
                    "run_id": run_id or None,
                })
    return warnings


def _resolve_context(
    *,
    person_id: str,
    package_date: str,
    live_session_id: str | None,
    service_run_id: str | None,
) -> _Context:
    """Resolve a single session/run without guessing an owner.

    A hard PC shutdown leaves a historical ``running`` row.  Convert only a
    stale heartbeat into explicit ``orphaned`` before enforcing the active-run
    gate, so a resume can safely continue post-stop without pretending the
    service ended normally.
    """
    from .brainlive_service_v15_5 import recover_stale_brainlive_service_runs
    recover_stale_brainlive_service_runs()
    with connect() as con:
        service: dict[str, Any] | None = None
        if service_run_id:
            service = _one(
                con,
                "SELECT * FROM brainlive_service_runs WHERE service_run_id=? AND person_id=?",
                (service_run_id, person_id),
            )
            if not service:
                raise StageGateError("close-day service run is missing or belongs to another owner")
        elif live_session_id:
            service = _one(
                con,
                """SELECT * FROM brainlive_service_runs
                   WHERE live_session_id=? AND person_id=?
                   ORDER BY started_at DESC LIMIT 1""",
                (live_session_id, person_id),
            )
        else:
            service = _one(
                con,
                """SELECT * FROM brainlive_service_runs
                   WHERE person_id=?
                   ORDER BY COALESCE(stopped_at, started_at) DESC LIMIT 1""",
                (person_id,),
            )
        resolved_session = live_session_id or (str(service.get("live_session_id")) if service and service.get("live_session_id") else None)
        resolved_run = service_run_id or (str(service.get("service_run_id")) if service and service.get("service_run_id") else None)
        active = [
            dict(r)
            for r in con.execute(
                """SELECT service_run_id,live_session_id,status FROM brainlive_service_runs
                   WHERE person_id=? AND status IN ('running','stop_requested')""",
                (person_id,),
            ).fetchall()
        ]
    if active:
        raise StageGateError(
            "close-day blocked: an active BrainLive service still exists; request stop first "
            f"({', '.join(str(r.get('service_run_id')) for r in active)})"
        )
    # Only the resolved session may gate this close-day.  A historical orphan
    # from another already-closed day must not block today's independent run.
    unresolved_sql = """SELECT service_run_id,status FROM brainlive_service_runs
        WHERE person_id=? AND status IN ('stopped_pending_ingest','orphaned','drain_recovery')"""
    unresolved_params: list[Any] = [person_id]
    if resolved_session:
        unresolved_sql += " AND live_session_id=?"
        unresolved_params.append(resolved_session)
    elif resolved_run:
        unresolved_sql += " AND service_run_id=?"
        unresolved_params.append(resolved_run)
    unresolved = [dict(r) for r in con.execute(unresolved_sql, tuple(unresolved_params)).fetchall()]
    if unresolved:
        raise StageGateError(
            "close-day blocked: raw inbox acknowledgement is incomplete after an interrupted service; "
            "run brainlive-resume-inbox-drain first "
            f"({', '.join(str(r.get('service_run_id')) for r in unresolved)})"
        )
    return _Context(person_id=person_id, package_date=package_date, live_session_id=resolved_session, service_run_id=resolved_run)


def _load_existing_close_day(person_id: str, package_date: str) -> dict[str, Any] | None:
    with connect() as con:
        row = _one(
            con,
            "SELECT * FROM v18_close_day_runs WHERE person_id=? AND package_date=?",
            (person_id, package_date),
        )
    return row


def _save_close_day(
    *,
    close_day_id: str,
    ctx: _Context,
    status: str,
    post_stop_run_id: str | None,
    cleanup_eligible: bool,
    result: dict[str, Any],
    error_text: str | None = None,
) -> None:
    """Upsert by logical person/day, not only by a physical run id.

    This also repairs legacy V18.5 failed rows: a new canonical V18.7 run can
    replace the row's primary id without violating ``UNIQUE(person_id,date)``.
    """
    now = now_iso()
    with connect() as con, write_transaction(con):
        previous = _one(con, "SELECT created_at FROM v18_close_day_runs WHERE person_id=? AND package_date=?", (ctx.person_id, ctx.package_date)) or {}
        con.execute(
            """INSERT INTO v18_close_day_runs(
                 close_day_id,person_id,package_date,live_session_id,service_run_id,post_stop_run_id,
                 status,cleanup_eligible,result_json,error_text,created_at,updated_at,completed_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(person_id,package_date) DO UPDATE SET
                 close_day_id=excluded.close_day_id, live_session_id=excluded.live_session_id,
                 service_run_id=excluded.service_run_id, post_stop_run_id=excluded.post_stop_run_id,
                 status=excluded.status, cleanup_eligible=excluded.cleanup_eligible,
                 result_json=excluded.result_json,error_text=excluded.error_text,
                 updated_at=excluded.updated_at, completed_at=excluded.completed_at""",
            (close_day_id, ctx.person_id, ctx.package_date, ctx.live_session_id, ctx.service_run_id, post_stop_run_id,
             status, 1 if cleanup_eligible else 0, json_dumps(result), error_text,
             previous.get("created_at") or now, now, now if status == "completed" else None),
        )


def _run_stage(*, run_id: str, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run or resume a day-level stage without discarding a prior checkpoint."""
    with connect() as con, write_transaction(con):
        existing = _one(con, "SELECT status,result_json FROM v18_pipeline_stages WHERE run_id=? AND stage_name=?", (run_id, name))
        if existing and str(existing.get("status")) == "completed":
            cached = json_loads(existing.get("result_json"), {}) or {}
            if isinstance(cached, dict):
                return {**cached, "resumed_stage": True}
            raise StageGateError(f"close-day {name} has an invalid cached result")
        start_stage(con, run_id=run_id, stage_name=name, required=True)
    record_recovery_state(run_id=run_id, state="running", stage_name=name)
    try:
        result = fn()
        if not _status_ok(result, stage_name=name):
            # Preserve retryable status from the post-stop result instead of
            # flattening it into a generic StageGateError.
            st = str((result or {}).get("status") or "blocked").lower()
            from .runtime_v18_7 import RuntimePolicyError
            raise RuntimePolicyError(f"close-day {name} returned {st}", code=f"{name}_{st}", retryable=st in {"retryable_error", "retryable", "pending_retry"})
    except Exception as exc:
        failure = classify_failure(exc)
        with connect() as con, write_transaction(con):
            finish_stage(con, run_id=run_id, stage_name=name, result={"status": "error", "error_code": failure.code}, status="failed", error_text=str(exc)[:2000])
        if failure.retryable:
            cfg = get_settings()
            delay = int(cfg.poststop_retry_backoff_seconds[-1]) if cfg.poststop_retry_backoff_seconds else 0
            mark_run_retryable(run_id=run_id, stage_name=name, error_code=failure.code, error_text=str(exc), retry_after_seconds=delay)
        else:
            record_recovery_state(run_id=run_id, state="blocked", stage_name=name, error_code=failure.code, error_text=str(exc))
        raise
    with connect() as con, write_transaction(con):
        finish_stage(con, run_id=run_id, stage_name=name, result=result, status="completed")
    return result


def _find_completed_post_stop(ctx: _Context) -> dict[str, Any] | None:
    with connect() as con:
        where = ["person_id=?", "package_date=?", "status='completed'"]
        params: list[Any] = [ctx.person_id, ctx.package_date]
        if ctx.live_session_id:
            where.append("live_session_id=?")
            params.append(ctx.live_session_id)
        row = _one(
            con,
            f"SELECT * FROM brainlive_post_stop_deep_flow_runs_v1515 WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 1",
            tuple(params),
        )
    if not row:
        return None
    return {
        "run_id": row.get("run_id"),
        "status": row.get("status"),
        "package_date": row.get("package_date"),
        "resumed_existing_post_stop": True,
    }


def close_brainlive_day(
    *,
    person_id: str,
    live_session_id: str | None = None,
    service_run_id: str | None = None,
    package_date: str | None = None,
    use_llm: bool = True,
    force: bool = False,
    post_stop_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize or resume one logical close-day run.

    A retryable stage failure never becomes a terminal day.  The next call keeps
    the same run id, returns completed checkpoints, and resumes at the first
    failed stage.  ``force`` only bypasses a safety backoff; it does not erase
    or duplicate completed work.
    """
    if not person_id:
        raise StageGateError("close-day requires explicit person_id")
    cfg = get_settings()
    ensure_close_day_schema()
    day = _package_day(package_date)
    existing = _load_existing_close_day(person_id, day)
    if existing and str(existing.get("status")) == "completed":
        cached = json_loads(existing.get("result_json"), {}) or {}
        return {**(cached if isinstance(cached, dict) else {}), "resumed_close_day": True}

    ctx = _resolve_context(person_id=person_id, package_date=day, live_session_id=live_session_id, service_run_id=service_run_id)
    scope = Scope(person_id=person_id, mode="maintenance")
    manifest = {
        "release": VERSION, "package_date": day, "person_id": person_id,
        "use_llm": bool(use_llm), "ollama_model": cfg.ollama_model,
    }
    run_id, resumed = begin_or_resume_run(
        pipeline_name="brainlive_close_day", scope=scope, input_manifest=manifest,
        idempotency_key=f"close_day_v18_7:{person_id}:{day}", force_resume=bool(force),
    )
    execution_lease = acquire_execution_lease(run_id=run_id, purpose="brainlive_close_day")
    if not execution_lease.acquired:
        return {
            "version": VERSION, "run_id": run_id, "person_id": person_id, "package_date": day,
            "status": "in_progress", "resumed": resumed,
            "lease_owner_pid": execution_lease.owner_pid, "lease_owner_host": execution_lease.owner_host,
            "cleanup": {"eligible": False},
        }
    try:
        recover_stale_stages(
            run_id=run_id,
            stale_after_seconds=0 if (force or execution_lease.reclaimed) else cfg.stage_stale_after_s,
            reason="close_day_resume_v18_7",
        )
    except Exception:
        execution_lease.release()
        raise
    _save_close_day(
        close_day_id=run_id, ctx=ctx, status="running", post_stop_run_id=(post_stop_result or {}).get("run_id") if isinstance(post_stop_result, dict) else None,
        cleanup_eligible=False, result={"version": VERSION, "run_id": run_id, "person_id": person_id, "package_date": day, "status": "running", "resumed": resumed},
    )
    result: dict[str, Any] = {
        "version": VERSION, "run_id": run_id, "person_id": person_id, "package_date": day,
        "live_session_id": ctx.live_session_id, "service_run_id": ctx.service_run_id, "resumed": resumed,
        "status": "blocked", "stages": {}, "cleanup": {"eligible": False},
    }
    post_stop_run_id: str | None = None
    try:
        # The day-level lease is refreshed before each heavy stage.  If the PC
        # dies, its PID disappears and the next RESUME can reclaim this exact run.
        heartbeat_execution_lease(execution_lease)
        def do_post_stop() -> dict[str, Any]:
            candidate = post_stop_result if isinstance(post_stop_result, dict) else _find_completed_post_stop(ctx)
            if not candidate:
                from .brainlive_poststop_deep_flow_v15_15 import run_brainlive_post_stop_deep_flow
                candidate = run_brainlive_post_stop_deep_flow(
                    person_id=person_id, live_session_id=ctx.live_session_id, service_run_id=ctx.service_run_id,
                    package_date=day, force=force, use_llm=use_llm,
                )
            if str(candidate.get("status")) != "completed":
                return dict(candidate)
            return dict(candidate)

        heartbeat_execution_lease(execution_lease)
        post = _run_stage(run_id=run_id, name="post_stop", fn=do_post_stop)
        result["stages"]["post_stop"] = post
        post_stop_run_id = str(post.get("run_id") or "") or None
        if not post_stop_run_id:
            raise StageGateError("post-stop completed without a durable run id")
        from .brainlive_poststop_deep_flow_v15_15 import post_stop_cleanup_eligible
        post_gate = post_stop_cleanup_eligible(run_id=post_stop_run_id, person_id=person_id)
        result["post_stop_cleanup_gate"] = post_gate
        if not bool((post_gate or {}).get("eligible")):
            raise StageGateError("close-day blocked: the session post-stop cleanup gate is not eligible")

        def do_visual_consolidation() -> dict[str, Any]:
            from .v19_visual_consolidation import run_visual_consolidation
            return run_visual_consolidation(person_id=person_id, package_date=day, live_session_id=ctx.live_session_id)
        heartbeat_execution_lease(execution_lease)
        visual_consolidation = _run_stage(run_id=run_id, name="visual_consolidation", fn=do_visual_consolidation)
        result["stages"]["visual_consolidation"] = visual_consolidation

        def do_longitudinal() -> dict[str, Any]:
            from .brain2_longitudinal_cases_v17 import run_longitudinal_consolidation
            # E54: the day rollup runs at every close-day. When the closed day is the
            # LAST day of an ISO week (Sunday) or of a month, the corresponding
            # week/month rollup runs too — on the now-complete period, with the
            # periodic mirror layer (parity with the V15/V18 nightly scheduler, which
            # the PhoneOnly close-day path never invokes). Idempotent per period via
            # the store's own keying, so a re-run does not duplicate.
            out: dict[str, Any] = {
                "day": run_longitudinal_consolidation(
                    person_id=person_id, period="day", run_date=day,
                    use_llm=use_llm, run_periodic_mirror_layer=False, force_cases=False)
            }
            for period in _due_longitudinal_periods(day):
                out[period] = run_longitudinal_consolidation(
                    person_id=person_id, period=period, run_date=day,
                    use_llm=use_llm, run_periodic_mirror_layer=True, force_cases=False)
            out["periods_run"] = ["day", *(_due_longitudinal_periods(day))]
            period_statuses = {
                period: str((out.get(period) or {}).get("status") or "missing").lower()
                for period in out["periods_run"]
            }
            out["period_statuses"] = period_statuses
            out["status"] = (
                "completed"
                if all(status in {"ok", "completed"} for status in period_statuses.values())
                else "failed"
            )
            return out
        heartbeat_execution_lease(execution_lease)
        longitudinal = _run_stage(run_id=run_id, name="longitudinal", fn=do_longitudinal)
        result["stages"]["longitudinal"] = longitudinal

        def do_coordination() -> dict[str, Any]:
            from .brainlive_brain2_coordination_v15_12 import run_brainlive_brain2_coordination
            from .runtime_v18_7 import gpu_phase
            with gpu_phase("post_stop_close_day", release_before=False, release_after=False):
                return run_brainlive_brain2_coordination(person_id=person_id, package_date=day, use_llm=use_llm, timeout=cfg.poststop_llm_timeout_s)
        heartbeat_execution_lease(execution_lease)
        coordination = _run_stage(run_id=run_id, name="coordination", fn=do_coordination)
        result["stages"]["coordination"] = coordination

        def do_life_model() -> dict[str, Any]:
            from .brain2_life_model_updater_v15_13 import run_brain2_life_model_update
            from .brain2_longitudinal_cases_v17 import period_bounds
            from .runtime_v18_7 import gpu_phase
            start_at, end_at, _ = period_bounds("day", run_date=day)
            with gpu_phase("post_stop_close_day", release_before=False, release_after=False):
                return run_brain2_life_model_update(person_id, period_start=start_at, period_end=end_at, use_llm=use_llm, timeout=cfg.poststop_llm_timeout_s, limit=120)
        heartbeat_execution_lease(execution_lease)
        life = _run_stage(run_id=run_id, name="life_model", fn=do_life_model)
        result["stages"]["life_model"] = life

        def do_outcome_resolution() -> dict[str, Any]:
            from .v19_outcome_watcher import resolve_prediction_outcomes
            return resolve_prediction_outcomes(person_id=person_id, package_date=day)
        heartbeat_execution_lease(execution_lease)
        outcome_resolution = _run_stage(run_id=run_id, name="outcome_resolution", fn=do_outcome_resolution)
        result["stages"]["outcome_resolution"] = outcome_resolution

        def do_life_model_v19() -> dict[str, Any]:
            from .v19_life_model_store import run_life_model_v19_stage
            from .runtime_v18_7 import gpu_phase
            with gpu_phase("post_stop_close_day", release_before=False, release_after=False):
                return run_life_model_v19_stage(person_id=person_id, package_date=day)
        heartbeat_execution_lease(execution_lease)
        life_model_v19 = _run_stage(run_id=run_id, name="life_model_v19", fn=do_life_model_v19)
        result["stages"]["life_model_v19"] = life_model_v19

        def do_prediction_emission() -> dict[str, Any]:
            from .v19_prediction_loop import emit_daily_predictions
            return emit_daily_predictions(person_id=person_id, package_date=day)
        heartbeat_execution_lease(execution_lease)
        prediction_emission = _run_stage(run_id=run_id, name="prediction_emission", fn=do_prediction_emission)
        result["stages"]["prediction_emission"] = prediction_emission

        def do_self_schema() -> dict[str, Any]:
            from .v19_self_schema import rebuild_self_schema
            return rebuild_self_schema(person_id=person_id)
        heartbeat_execution_lease(execution_lease)
        self_schema = _run_stage(run_id=run_id, name="self_schema", fn=do_self_schema)
        result["stages"]["self_schema"] = self_schema

        def do_live_ready() -> dict[str, Any]:
            from .brainlive_personal_model_v15_9 import build_brain2_live_personal_model
            from .runtime_v18_7 import gpu_phase
            with gpu_phase("post_stop_close_day", release_before=False, release_after=False):
                return build_brain2_live_personal_model(person_id=person_id, use_llm=use_llm, timeout=cfg.poststop_llm_timeout_s, limit=80)
        heartbeat_execution_lease(execution_lease)
        live_ready = _run_stage(run_id=run_id, name="live_ready", fn=do_live_ready)
        result["stages"]["live_ready"] = live_ready

        stage_results = {
            "post_stop": post,
            "visual_consolidation": visual_consolidation,
            "longitudinal": longitudinal,
            "coordination": coordination,
            "life_model": life,
            "outcome_resolution": outcome_resolution,
            "life_model_v19": life_model_v19,
            "prediction_emission": prediction_emission,
            "self_schema": self_schema,
            "live_ready": live_ready,
        }
        semantic_warnings = _semantic_output_warnings(
            person_id=person_id, package_date=day, stage_results=stage_results
        )
        if semantic_warnings:
            result["semantic_warnings"] = semantic_warnings

        expected, observed = _verified_close_day_outputs(
            run_id=run_id,
            person_id=person_id,
            stage_results=stage_results,
        )
        output = record_output_manifest(
            run_id=run_id,
            person_id=person_id,
            expected=expected,
            observed=observed,
            reason="close_day_durable_output_verification_v18_7",
        )
        if not output["complete"]:
            missing = sorted(set(expected) - set(observed))
            raise StageGateError(f"close-day durable output manifest is incomplete: {missing}")
        update_run(run_id, status="completed")
        cleanup = assert_cleanup_eligible(
            run_id=run_id,
            person_id=person_id,
            required_stages=list(_CLOSE_DAY_REQUIRED_STAGES),
        )
        result.update(status="completed", output_manifest=output, cleanup={**cleanup, "post_stop_run_id": post_stop_run_id})
        _save_close_day(close_day_id=run_id, ctx=ctx, status="completed", post_stop_run_id=post_stop_run_id, cleanup_eligible=True, result=result)
    except Exception as exc:
        error = str(exc)[:2000]
        failure = classify_failure(exc)
        if failure.retryable:
            status = "retryable_error"
            delay = int(cfg.poststop_retry_backoff_seconds[-1]) if cfg.poststop_retry_backoff_seconds else 0
            mark_run_retryable(run_id=run_id, stage_name="close_day", error_code=failure.code, error_text=error, retry_after_seconds=delay)
        else:
            # Preserve the canonical run and every completed checkpoint.  A
            # configuration/evidence block is not a reason to create a new
            # day or rerun deep audio after the operator fixes the condition.
            # Normal invocation stays blocked; explicit RESUME --force is the
            # controlled re-entry point enforced by assert_run_resumable().
            status = "blocked"
            try:
                record_recovery_state(run_id=run_id, state="blocked", stage_name="close_day", error_code=failure.code, error_text=error)
            except Exception:
                pass
        result.update(status=status, error=error, cleanup={"eligible": False, "reason": f"close_day_{status}"})
        _save_close_day(close_day_id=run_id, ctx=ctx, status=status, post_stop_run_id=post_stop_run_id, cleanup_eligible=False, result=result, error_text=error)
        record_phase_event("close_day_failed", run_id=run_id, error_code=failure.code, retryable=failure.retryable)
    finally:
        # One release at the phase boundary, never between deep LLM stages.
        try:
            from .llm import ollama_unload
            ollama_unload(model=cfg.ollama_model)
        except Exception:
            pass
        execution_lease.release()
    return result

def close_day_status(*, person_id: str, package_date: str | None = None) -> dict[str, Any]:
    ensure_close_day_schema()
    day = _package_day(package_date)
    row = _load_existing_close_day(person_id, day)
    if not row:
        return {"version": VERSION, "person_id": person_id, "package_date": day, "status": "missing"}
    result = json_loads(row.get("result_json"), {}) or {}
    return {
        "version": VERSION,
        "person_id": person_id,
        "package_date": day,
        "close_day_id": row.get("close_day_id"),
        "status": row.get("status"),
        "cleanup_eligible": bool(row.get("cleanup_eligible")),
        "live_session_id": row.get("live_session_id"),
        "service_run_id": row.get("service_run_id"),
        "post_stop_run_id": row.get("post_stop_run_id"),
        "error": row.get("error_text"),
        "recovery": recovery_state(run_id=str(row.get("close_day_id"))) if row.get("close_day_id") else None,
        "result": result,
    }
