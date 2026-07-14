from __future__ import annotations

"""Executable E64-I/R3 map from semantic responsibility to real consumers.

The map deliberately stays at the responsibility boundary.  Wording is allowed
to change between baseline and shadow; a responsibility, durable writer, proof
boundary or downstream reader is not.
"""

from dataclasses import dataclass
import importlib
import inspect
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


VERSION = "e64i-r3-equivalence-v1"


@dataclass(frozen=True)
class Responsibility:
    facts: tuple[str, ...]
    writer_table: str
    writer_field: str
    consumers: tuple[tuple[str, str], ...]
    proof_policy: str


DAY_CONSUMERS = (
    ("mlomega_audio_elite.brainlive_brain2_coordination_v15_12:reconcile_brainlive_with_brain2", "brainlive_day_packages"),
    ("mlomega_audio_elite.brain2_life_model_updater_v15_13:collect_life_model_delta", "brainlive_day_packages"),
)
WATCH_CONSUMERS = (
    ("mlomega_audio_elite.brainlive_brain2_coordination_v15_12:snapshot_live_context_for_audit", "brain2_live_watch_bindings"),
    ("mlomega_audio_elite.brainlive_personal_model_v15_9:collect_brain2_life_feed", "brain2_live_watch_bindings"),
)
RECONCILIATION_CONSUMERS = (
    ("mlomega_audio_elite.brainlive_brain2_coordination_v15_12:update_life_model_lifecycle", "brainlive_brain2_reconciliations"),
    ("mlomega_audio_elite.brain2_life_model_updater_v15_13:collect_life_model_delta", "brainlive_brain2_reconciliations"),
)
LIFE_CONSUMERS = (
    ("mlomega_audio_elite.v19_life_model_store:project_canonical_life_model", "_CANONICAL_SOURCES"),
    ("mlomega_audio_elite.brainlive_personal_model_v15_9:collect_brain2_life_feed", "brain2_personal_routine_models"),
)


CONTRACT: dict[str, dict[str, Responsibility]] = {
    "coordination_day_package": {
        "day_summary": Responsibility(("daily_registry",), "brainlive_day_packages", "llm_summary_json.day_summary", DAY_CONSUMERS, "summary cannot create facts"),
        "important_live_moments": Responsibility(("turns", "sensor_events", "vision", "event_bundles"), "brainlive_day_packages", "llm_summary_json.important_live_moments", DAY_CONSUMERS, "each moment remains backed by raw package evidence"),
        "prediction_lessons": Responsibility(("predictions", "outcomes"), "brainlive_day_packages", "llm_summary_json.prediction_lessons", DAY_CONSUMERS, "prediction and outcome are not interchangeable"),
        "intervention_lessons": Responsibility(("interventions", "outcomes"), "brainlive_day_packages", "llm_summary_json.intervention_lessons", DAY_CONSUMERS, "no success without observed outcome"),
        "silence_lessons": Responsibility(("silences", "missed_opportunities"), "brainlive_day_packages", "llm_summary_json.silence_lessons", DAY_CONSUMERS, "absence remains unknown unless explicitly evaluated"),
        "model_update_candidates": Responsibility(("outcomes", "disagreements", "event_bundles"), "brainlive_day_packages", "llm_summary_json.model_update_candidates", DAY_CONSUMERS, "candidate only, never direct canonical promotion"),
        "questions_for_brain2": Responsibility(("unresolved_sources", "disagreements"), "brainlive_day_packages", "llm_summary_json.questions_for_brain2", DAY_CONSUMERS, "uncertainty must remain explicit"),
    },
    "coordination_watch_bindings": {
        "watch_bindings": Responsibility(("predictions", "forecasts", "warnings", "canonical_life_hooks"), "brain2_live_watch_bindings", "one row per source binding", WATCH_CONSUMERS, "physical source_table/source_id must resolve for the owner"),
        "missing_for_live_activation": Responsibility(("unresolved_sources",), "brain2_brainlive_coordination_runs", "returned diagnostic", WATCH_CONSUMERS, "missing prerequisites cannot be represented as an active binding"),
    },
    "coordination_reconciliation": {
        "reconciliations": Responsibility(("comparable_prediction_outcome_pairs",), "brainlive_brain2_reconciliations", "one row per comparable pair", RECONCILIATION_CONSUMERS, "non-observed is unknown, never contradicted"),
        "summary_for_brain2": Responsibility(("validated_reconciliations",), "brainlive_brain2_reconciliations", "returned diagnostic", RECONCILIATION_CONSUMERS, "summary cannot outrun row verdicts"),
        "summary_for_brainlive": Responsibility(("validated_reconciliations",), "brainlive_brain2_reconciliations", "returned diagnostic", RECONCILIATION_CONSUMERS, "summary cannot outrun row verdicts"),
    },
    "life_model_patch": {
        "patch_intent": Responsibility(("checkpoint_delta",), "brain2_life_model_patch_runs", "patch_json.patch_intent", LIFE_CONSUMERS, "incremental patch, never whole-life rewrite"),
        "operations": Responsibility(("owner_scoped_durable_delta", "current_canonical_model"), "brain2_life_model_patch_operations", "one row per validated operation", LIFE_CONSUMERS, "every operation cites a new exact durable owner source"),
        "strata_guidance": Responsibility(("lifecycle_policy",), "brain2_life_model_patch_runs", "patch_json.strata_guidance", LIFE_CONSUMERS, "first occurrence remains very_recent/watch_only"),
        "missing_evidence_for_magic": Responsibility(("checkpoint_delta",), "brain2_life_model_patch_runs", "patch_json.missing_evidence_for_magic", LIFE_CONSUMERS, "abstention is durable evidence of insufficiency"),
        "do_not_update_without": Responsibility(("proof_policy",), "brain2_life_model_patch_runs", "patch_json.do_not_update_without", LIFE_CONSUMERS, "guard is preserved with the run"),
        "summary_for_brainlive": Responsibility(("validated_operations",), "brain2_life_model_patch_runs", "patch_json.summary_for_brainlive", LIFE_CONSUMERS, "only validated operations can become live effects"),
    },
}


def _schemas() -> dict[str, Mapping[str, Any]]:
    from ..brain2_life_model_updater_v15_13 import PATCH_SCHEMA
    from ..brainlive_brain2_coordination_v15_12 import (
        DAY_PACKAGE_SCHEMA,
        RECONCILIATION_SCHEMA,
        WATCH_BINDING_SCHEMA,
    )

    return {
        "coordination_day_package": DAY_PACKAGE_SCHEMA,
        "coordination_watch_bindings": WATCH_BINDING_SCHEMA,
        "coordination_reconciliation": RECONCILIATION_SCHEMA,
        "life_model_patch": PATCH_SCHEMA,
    }


def _call_chain_reads(function: Any, token: str, seen: set[int] | None = None) -> bool:
    """Follow production wrappers (``old_*`` closures) to the real SQL reader."""

    seen = seen or set()
    if id(function) in seen or not callable(function):
        return False
    seen.add(id(function))
    try:
        if token in inspect.getsource(function):
            return True
        closure = inspect.getclosurevars(function)
    except (OSError, TypeError):
        return False
    delegated = {
        **closure.nonlocals,
        **{
            name: value for name, value in closure.globals.items()
            if name.startswith("old_")
        },
    }
    return any(
        _call_chain_reads(value, token, seen)
        for value in delegated.values() if callable(value)
    )


def validate_equivalence_contract() -> dict[str, Any]:
    """Prove schema coverage and that each declared consumer reads its real table."""

    failures: list[dict[str, Any]] = []
    schema_keys: dict[str, list[str]] = {}
    for stage, schema in _schemas().items():
        expected = set(schema)
        mapped = set(CONTRACT.get(stage) or {})
        schema_keys[stage] = sorted(expected)
        if expected != mapped:
            failures.append({
                "stage": stage,
                "kind": "schema_matrix_mismatch",
                "missing": sorted(expected - mapped),
                "extra": sorted(mapped - expected),
            })
        for field, responsibility in (CONTRACT.get(stage) or {}).items():
            for symbol, read_token in responsibility.consumers:
                module_name, function_name = symbol.split(":", 1)
                try:
                    function = getattr(importlib.import_module(module_name), function_name)
                    if not _call_chain_reads(function, read_token):
                        failures.append({
                            "stage": stage,
                            "field": field,
                            "kind": "consumer_does_not_read_declared_table",
                            "consumer": symbol,
                            "table": read_token,
                        })
                except Exception as exc:
                    failures.append({
                        "stage": stage,
                        "field": field,
                        "kind": "consumer_unavailable",
                        "consumer": symbol,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    return {
        "version": VERSION,
        "ready": not failures,
        "schema_keys": schema_keys,
        "responsibility_count": sum(len(fields) for fields in CONTRACT.values()),
        "failures": failures,
    }


_V14_TABLES = (
    ("v14_5_people_context_profiles", "known_person_id", "evidence_count", "confidence"),
    ("v14_6_relationship_state_models", "known_person_id", "evidence_json", "confidence"),
    ("v14_6_interpersonal_loop_cards", None, "evidence_json", "confidence"),
)


def _json(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _has_exact_ref(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_exact_ref(item) for item in value)
    if isinstance(value, dict):
        return bool(value.get("turn_id") or value.get("turn_ref") or (
            value.get("source_table") and value.get("source_id")
        )) or any(_has_exact_ref(item) for item in value.values())
    return False


def audit_v14_database(path: str | Path, *, person_id: str = "me") -> dict[str, Any]:
    """Read one immutable clone and measure responsibility/provenance/prudence."""

    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    tables = {str(row[0]) for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    metrics: dict[str, Any] = {}
    unresolved_high_confidence: list[dict[str, Any]] = []
    for table, known_field, evidence_field, confidence_field in _V14_TABLES:
        if table not in tables:
            metrics[table] = {"present": False, "rows": 0}
            continue
        rows = [dict(row) for row in con.execute(
            f"SELECT * FROM {table} WHERE person_id=?", (person_id,)
        ).fetchall()]
        exact = 0
        for row in rows:
            evidence = row.get(evidence_field)
            if evidence_field == "evidence_count":
                has_proof = int(evidence or 0) > 0
            else:
                has_proof = _has_exact_ref(_json(evidence, []))
            exact += int(has_proof)
            unresolved = not row.get(known_field) if known_field else True
            confidence = float(row.get(confidence_field) or 0.0)
            if unresolved and confidence > 0.65:
                unresolved_high_confidence.append({
                    "table": table,
                    "row_id": next((row.get(key) for key in row if key.endswith("_id")), None),
                    "person_hint": row.get("person_hint"),
                    "confidence": confidence,
                })
        metrics[table] = {
            "present": True,
            "rows": len(rows),
            "rows_with_exact_or_counted_proof": exact,
            "proof_coverage": (exact / len(rows)) if rows else 1.0,
        }

    interpersonal_keys: list[str] = []
    if "v14_6_interpersonal_runs" in tables:
        row = con.execute(
            "SELECT qwen_output_json FROM v14_6_interpersonal_runs "
            "WHERE person_id=? AND status='ok' ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ).fetchone()
        interpersonal_keys = sorted((_json(row[0], {}) if row else {}).keys())
    con.close()
    from ..interpersonal_state_v14_6 import INTERPERSONAL_SCHEMA

    missing_responsibilities = sorted(set(INTERPERSONAL_SCHEMA) - set(interpersonal_keys))
    return {
        "path": str(Path(path)),
        "tables": metrics,
        "interpersonal_responsibilities": interpersonal_keys,
        "missing_interpersonal_responsibilities": missing_responsibilities,
        "unresolved_high_confidence": unresolved_high_confidence,
        "ready": not missing_responsibilities and not unresolved_high_confidence
            and all(item.get("present") for item in metrics.values()),
    }


def compare_v14_clones(
    baseline_path: str | Path, shadow_path: str | Path, *, person_id: str = "me",
) -> dict[str, Any]:
    baseline = audit_v14_database(baseline_path, person_id=person_id)
    shadow = audit_v14_database(shadow_path, person_id=person_id)
    regressions: list[dict[str, Any]] = []
    for table in (item[0] for item in _V14_TABLES):
        before = baseline["tables"][table]
        after = shadow["tables"][table]
        if before.get("present") and not after.get("present"):
            regressions.append({"table": table, "kind": "writer_missing"})
        if float(after.get("proof_coverage") or 0.0) < float(before.get("proof_coverage") or 0.0):
            regressions.append({"table": table, "kind": "proof_coverage_decreased"})
    if shadow["missing_interpersonal_responsibilities"]:
        regressions.append({
            "kind": "schema_responsibility_missing",
            "fields": shadow["missing_interpersonal_responsibilities"],
        })
    if shadow["unresolved_high_confidence"]:
        regressions.append({
            "kind": "unresolved_person_overconfidence",
            "rows": shadow["unresolved_high_confidence"],
        })
    return {
        "version": VERSION,
        "ready": not regressions,
        "baseline": baseline,
        "shadow": shadow,
        "regressions": regressions,
    }


def _open_readonly(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _source_exists(con: sqlite3.Connection, table: str, source_id: str) -> bool:
    if not table or not source_id or not table.replace("_", "").isalnum():
        return False
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is None:
        return False
    info = con.execute(f"PRAGMA table_info({table})").fetchall()
    primary = [str(row[1]) for row in sorted(info, key=lambda row: int(row[5] or 0)) if int(row[5] or 0)]
    candidates = primary or [str(row[1]) for row in info if str(row[1]).endswith("_id")]
    for column in candidates:
        if con.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (source_id,)).fetchone():
            return True
    return False


def audit_r3_runtime_evidence(
    coordination_path: str | Path,
    life_path: str | Path,
    *,
    person_id: str = "me",
) -> dict[str, Any]:
    """Relate the executable matrix to the two immutable R2 proof clones."""

    failures: list[dict[str, Any]] = []
    coordination: dict[str, Any] = {}
    with _open_readonly(coordination_path) as con:
        package = con.execute(
            "SELECT * FROM brainlive_day_packages WHERE person_id=? "
            "AND status='compiled_ready' ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ).fetchone()
        summary = _json(package["llm_summary_json"], {}) if package else {}
        missing_day = sorted(set(_schemas()["coordination_day_package"]) - set(summary))
        if package is None or missing_day:
            failures.append({"kind": "compiled_day_package_incomplete", "missing": missing_day})

        bindings = con.execute(
            "SELECT binding_id,source_table,source_id,status FROM brain2_live_watch_bindings "
            "WHERE person_id=? AND status='active'",
            (person_id,),
        ).fetchall()
        invalid_bindings = [
            dict(row) for row in bindings
            if not _source_exists(con, str(row["source_table"]), str(row["source_id"]))
        ]
        if invalid_bindings:
            failures.append({"kind": "active_binding_source_unresolved", "rows": invalid_bindings})

        run = con.execute(
            "SELECT * FROM brain2_brainlive_coordination_runs WHERE person_id=? "
            "ORDER BY finished_at DESC LIMIT 1", (person_id,),
        ).fetchone()
        run_counts = _json(run["counts_json"], {}) if run else {}
        if run is None or run["status"] != "ok":
            failures.append({"kind": "coordination_run_not_ok"})
        coordination = {
            "package_id": package["package_id"] if package else None,
            "day_fields": sorted(summary),
            "active_binding_count": len(bindings),
            "invalid_binding_count": len(invalid_bindings),
            "run_id": run["run_id"] if run else None,
            "run_status": run["status"] if run else None,
            "reconciliations_created": run_counts.get("reconciliations_created"),
        }

    life: dict[str, Any] = {}
    with _open_readonly(life_path) as con:
        checkpoints = con.execute(
            "SELECT * FROM brain2_life_model_checkpoints WHERE person_id=? "
            "ORDER BY committed_at", (person_id,),
        ).fetchall()
        positive = [row for row in checkpoints if int(row["source_count"] or 0) > 0]
        replay_zero = bool(checkpoints and int(checkpoints[-1]["source_count"] or 0) == 0)
        if not positive:
            failures.append({"kind": "life_checkpoint_has_no_consumed_delta"})
        if not replay_zero:
            failures.append({"kind": "life_checkpoint_replay_not_empty"})
        consumed = con.execute(
            "SELECT source_table,source_id FROM brain2_life_model_consumed_sources "
            "WHERE person_id=?", (person_id,),
        ).fetchall()
        missing_sources = [
            dict(row) for row in consumed
            if not _source_exists(con, str(row["source_table"]), str(row["source_id"]))
        ]
        if missing_sources:
            failures.append({"kind": "life_consumed_source_missing", "rows": missing_sources})
        watches = con.execute(
            "SELECT status,occurrence_count,independent_count FROM "
            "brain2_life_model_watch_candidates WHERE person_id=?", (person_id,),
        ).fetchall()
        if any(int(row["independent_count"] or 0) > int(row["occurrence_count"] or 0) for row in watches):
            failures.append({"kind": "life_watch_independence_impossible"})
        life = {
            "checkpoint_count": len(checkpoints),
            "positive_checkpoint_sources": sum(int(row["source_count"] or 0) for row in positive),
            "replay_source_count": int(checkpoints[-1]["source_count"] or 0) if checkpoints else None,
            "consumed_source_count": len(consumed),
            "missing_consumed_sources": len(missing_sources),
            "watch_count": len(watches),
        }

    return {
        "version": VERSION,
        "ready": not failures,
        "coordination": coordination,
        "life": life,
        "failures": failures,
    }
