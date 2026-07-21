from __future__ import annotations

"""V15.13 Brain2 Life Model updater with strata and patch semantics.

This module fixes the unsafe pattern of rebuilding William's whole life model on
one nightly prompt. It makes Brain2's life model behave like a stable memory:

- General model: slow, high-confidence identity/routines/preferences.
- Recent model: last weeks/months; can shift but requires evidence.
- Very recent model: last 24-72h; useful for BrainLive but not yet truth.

The LLM is used as a *patch proposer*, not as an unrestricted rewriter. It sees:
current life model snapshots + new evidence delta + outcomes/reconciliations and
must return operations such as create, confirm, update, weaken, contradict,
obsolete or keep. Deterministic code stores patch runs, lifecycle rows and
stratified snapshots. BrainLive should prefer active/confirmed hooks and treat
very_recent/candidate items as watch-only unless confidence is high.

Strict policy: no regex/keyword psychology. Deterministic code can count,
window, link and apply lifecycle metadata. Psychological/intention/need meaning
comes from Brain2 LLM outputs or existing evidence with explicit confidence.
"""

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import re
from typing import Any

from .db import connect, init_db, upsert, write_transaction
from .llm import OllamaJsonClient
from .utils import json_dumps, json_loads, now_iso, stable_id
from .brain2_life_model_v15_10 import (
    CANONICAL_SCHEMA,
    collect_canonical_evidence,
    ensure_life_model_schema,
    build_brain2_canonical_life_model,
    store_canonical_life_model,
)

VERSION = "15.13.0-brain2-life-model-updater-stratified"

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS brain2_life_model_patch_runs(
  patch_run_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  status TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  current_model_digest TEXT,
  delta_counts_json TEXT DEFAULT '{}',
  patch_json TEXT DEFAULT '{}',
  error_text TEXT,
  llm_model TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS brain2_life_model_patch_operations(
  operation_id TEXT PRIMARY KEY,
  patch_run_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  op TEXT NOT NULL,
  target_layer TEXT NOT NULL,
  target_table TEXT,
  target_id TEXT,
  identity_key TEXT,
  stratum TEXT NOT NULL DEFAULT 'recent',
  reason TEXT,
  evidence_json TEXT DEFAULT '[]',
  counter_evidence_json TEXT DEFAULT '[]',
  confidence_before REAL,
  confidence_after REAL,
  confidence_delta REAL DEFAULT 0.0,
  patch_data_json TEXT DEFAULT '{}',
  lifecycle_json TEXT DEFAULT '{}',
  live_effect_json TEXT DEFAULT '{}',
  status TEXT DEFAULT 'applied',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brain2_life_model_strata(
  stratum_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  stratum TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  model_json TEXT DEFAULT '{}',
  evidence_window_start TEXT,
  evidence_window_end TEXT,
  patch_run_id TEXT,
  source_counts_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brain2_life_model_item_lifecycle(
  lifecycle_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  source_table TEXT NOT NULL,
  source_id TEXT NOT NULL,
  layer TEXT NOT NULL,
  identity_key TEXT,
  stratum TEXT NOT NULL DEFAULT 'recent',
  truth_status TEXT NOT NULL DEFAULT 'candidate',
  first_seen_at TEXT,
  last_seen_at TEXT,
  last_confirmed_at TEXT,
  last_contradicted_at TEXT,
  evidence_count INTEGER DEFAULT 0,
  counter_evidence_count INTEGER DEFAULT 0,
  confidence REAL DEFAULT 0.5,
  recency_weight REAL DEFAULT 1.0,
  staleness_score REAL DEFAULT 0.0,
  valid_from TEXT,
  valid_until TEXT,
  superseded_by TEXT,
  obsolete_reason TEXT,
  use_policy TEXT DEFAULT 'watch_only',
  notes_json TEXT DEFAULT '{}',
  updated_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brain2_life_model_delta_evidence(
  delta_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  status TEXT NOT NULL,
  source_counts_json TEXT DEFAULT '{}',
  raw_evidence_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brain2_life_model_watch_candidates(
  watch_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  candidate_kind TEXT NOT NULL,
  identity_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'watching',
  occurrence_count INTEGER NOT NULL DEFAULT 1,
  independent_count INTEGER NOT NULL DEFAULT 1,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  promoted_target_layer TEXT,
  promoted_target_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brain2_life_model_consumed_sources(
  person_id TEXT NOT NULL,
  source_table TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  source_family TEXT NOT NULL,
  source_time TEXT,
  patch_run_id TEXT NOT NULL,
  consumed_at TEXT NOT NULL,
  PRIMARY KEY(person_id, source_table, source_id)
);

CREATE TABLE IF NOT EXISTS brain2_life_model_checkpoints(
  checkpoint_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  patch_run_id TEXT NOT NULL,
  status TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  source_count INTEGER NOT NULL,
  family_counts_json TEXT NOT NULL DEFAULT '{}',
  family_cursors_json TEXT NOT NULL DEFAULT '{}',
  period_start TEXT,
  period_end TEXT,
  committed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_b2_life_patch_person ON brain2_life_model_patch_runs(person_id, created_at);
CREATE INDEX IF NOT EXISTS idx_b2_life_ops_person ON brain2_life_model_patch_operations(person_id, target_layer, op, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_b2_life_strata_unique ON brain2_life_model_strata(person_id, stratum);
CREATE UNIQUE INDEX IF NOT EXISTS idx_b2_life_item_lifecycle_unique ON brain2_life_model_item_lifecycle(person_id, source_table, source_id, stratum);
CREATE UNIQUE INDEX IF NOT EXISTS idx_b2_life_watch_identity ON brain2_life_model_watch_candidates(person_id, candidate_kind, identity_key);
"""

PATCH_SCHEMA: dict[str, Any] = {
    "patch_intent": "incremental_update_not_rewrite",
    "operations": [
        {
            "op": "create|confirm|update|weaken|contradict|obsolete|keep",
            "target_layer": "routine|place|action_preference|need_expectation|expression_state|emotional_trajectory|contextual_self|live_prediction_hook|affordance_preference",
            "target_id": "optional existing id",
            "identity_key": "stable human-readable key",
            "stratum": "general|recent|very_recent",
            "reason": "why this operation is justified by new evidence",
            "evidence": [{
                "source_table": "exact physical table shown in the input",
                "source_id": "exact source id shown in the input",
            }],
            "counter_evidence": [{
                "source_table": "exact physical table shown in the input",
                "source_id": "exact source id shown in the input",
            }],
            "confidence_before": 0.0,
            "confidence_after": 0.0,
            "confidence_delta": 0.0,
            "patch_data": {},
            "lifecycle": {
                "truth_status": "candidate|active|confirmed|weakened|contradicted|obsolete|superseded",
                "use_policy": "do_not_use|watch_only|silent_context|proactive_allowed|strong_live_hook",
                "valid_from": "optional iso datetime",
                "valid_until": "optional iso datetime",
                "obsolete_reason": "optional"
            },
            "live_effect": {
                "horizons": ["H0", "H1", "H2", "day", "week", "long"],
                "brainlive_action": "watch|preload_context|activate_hook|allow_intervention|avoid_intervention",
                "notes_for_brainlive": []
            }
        }
    ],
    "strata_guidance": {
        "general": "slow/stable model; change only with repeated/strong evidence",
        "recent": "last weeks/months; active tendencies, can move faster",
        "very_recent": "last 24-72h; mostly watch-only unless strongly confirmed"
    },
    "missing_evidence_for_magic": [],
    "do_not_update_without": [],
    "summary_for_brainlive": []
}

LAYER_TO_CANONICAL_KEY = {
    "routine": "personal_routine_models",
    "place": "place_preference_models",
    "action_preference": "action_preference_models",
    "need_expectation": "need_expectation_models",
    "expression_state": "expression_state_models",
    "emotional_trajectory": "emotional_trajectory_models",
    "contextual_self": "contextual_self_models",
    "live_prediction_hook": "live_prediction_hooks",
    "affordance_preference": "live_affordance_preferences",
}

CANONICAL_TABLES: dict[str, tuple[str, str, str]] = {
    "routine": ("brain2_personal_routine_models", "routine_id", "routine_name"),
    "place": ("brain2_place_preference_models", "place_model_id", "place_key"),
    "action_preference": ("brain2_action_preference_models", "action_model_id", "action_or_choice"),
    "need_expectation": ("brain2_need_expectation_models", "need_model_id", "need_or_expectation"),
    "expression_state": ("brain2_expression_state_models", "expression_model_id", "expression_or_style"),
    "emotional_trajectory": ("brain2_emotional_trajectory_models", "trajectory_model_id", "trajectory_name"),
    "contextual_self": ("brain2_contextual_self_models", "contextual_model_id", "context_key"),
    "live_prediction_hook": ("brain2_live_prediction_hooks", "hook_id", "hook_name"),
    "affordance_preference": ("brain2_live_affordance_preferences", "affordance_pref_id", "affordance_type"),
}


def ensure_life_model_updater_schema() -> None:
    ensure_life_model_schema()
    init_db()
    with connect() as con:
        con.executescript(SCHEMA)
        con.commit()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _clamp(v: Any, default: float = 0.5) -> float:
    try:
        x = float(v)
    except Exception:
        x = default
    return max(0.0, min(1.0, x))


def _list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _table_exists(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _query(con, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except Exception:
        return []


def _count(feed: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for k, v in feed.items():
        if isinstance(v, dict):
            counts[k] = sum(len(x) if isinstance(x, list) else (1 if x else 0) for x in v.values())
        elif isinstance(v, list):
            counts[k] = len(v)
        else:
            counts[k] = 1 if v else 0
    return counts


def _safe_json(v: Any, default: Any) -> Any:
    return json_loads(v, default) if isinstance(v, str) else (v if v is not None else default)


def _compact_rows(rows: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        r = dict(row)
        for k, v in list(r.items()):
            if isinstance(v, str) and len(v) > 1600:
                r[k] = v[:1600] + "…"
        out.append(r)
    return out


def load_current_life_model(person_id: str, *, limit: int = 80) -> dict[str, Any]:
    """Load the complete current model; ``limit`` is only a page size."""
    ensure_life_model_updater_schema()
    current: dict[str, Any] = {"person_id": person_id, "canonical_layers": {}, "strata": {}, "lifecycle": [], "source_manifests": {}}
    with connect() as con:
        from .night_orchestrator.paged_evidence import read_query_pages
        page_size = max(1, int(limit))

        def read(family: str, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
            result = read_query_pages(
                con, stage_name="life_model_current_state", person_id=person_id,
                source_family=family, select_sql=sql, params=params,
                page_size=page_size, scope_key="current",
            )
            current["source_manifests"][family] = result.manifest
            return result.rows

        for layer, (table, id_col, _name_col) in CANONICAL_TABLES.items():
            if _table_exists(con, table):
                current["canonical_layers"][layer] = read(
                    f"canonical_layers.{layer}",
                    f"SELECT x.*,x.{id_col} AS __page_pk FROM {table} x WHERE x.person_id=?",
                    (person_id,),
                )
            else:
                current["canonical_layers"][layer] = []
        if _table_exists(con, "brain2_life_model_strata"):
            for row in _query(con, "SELECT * FROM brain2_life_model_strata WHERE person_id=? ORDER BY updated_at DESC", (person_id,)):
                current["strata"][row.get("stratum") or "unknown"] = _safe_json(row.get("model_json"), {})
        if _table_exists(con, "brain2_life_model_item_lifecycle"):
            current["lifecycle"] = read(
                "lifecycle",
                "SELECT x.*,x.lifecycle_id AS __page_pk FROM brain2_life_model_item_lifecycle x WHERE x.person_id=?",
                (person_id,),
            )
        if _table_exists(con, "brain2_life_model_exports"):
            row = con.execute("SELECT export_id,status,created_at,source_counts_json FROM brain2_life_model_exports WHERE person_id=? ORDER BY created_at DESC LIMIT 1", (person_id,)).fetchone()
            if row:
                current["latest_export"] = {"export_id": row["export_id"], "status": row["status"], "created_at": row["created_at"], "source_counts": _safe_json(row["source_counts_json"], {})}
    return current


def collect_life_model_delta(person_id: str, *, period_start: str | None = None, period_end: str | None = None, limit: int = 120) -> dict[str, Any]:
    """Collect only new/relevant evidence windows; no psychological synthesis."""
    ensure_life_model_updater_schema()
    now_dt = _now_dt()
    if period_end is None:
        period_end = _iso(now_dt)
    if period_start is None:
        # Default to last 24h for a nightly patch. General/recent windows are sent
        # separately as context; this delta is what can change the model today.
        period_start = _iso(now_dt - timedelta(days=1))
    delta = collect_canonical_evidence(person_id, period_start=period_start, period_end=period_end, limit=limit)
    # Add live-day packages and reconciliations explicitly because they are the
    # bridge from BrainLive outcomes back into Brain2.
    with connect() as con:
        live: dict[str, Any] = {}
        if _table_exists(con, "brainlive_day_packages"):
            live["day_packages"] = _compact_rows(_query(con, "SELECT * FROM brainlive_day_packages WHERE person_id=? AND COALESCE(period_end, updated_at, created_at) >= ? ORDER BY created_at DESC LIMIT ?", (person_id, period_start, limit)), limit)
        if _table_exists(con, "brainlive_brain2_reconciliations"):
            live["reconciliations"] = _compact_rows(_query(con, "SELECT * FROM brainlive_brain2_reconciliations WHERE person_id=? AND updated_at >= ? ORDER BY updated_at DESC LIMIT ?", (person_id, period_start, limit)), limit)
        if _table_exists(con, "brainlive_context_snapshots_v1512"):
            live["context_snapshots"] = _compact_rows(_query(con, "SELECT * FROM brainlive_context_snapshots_v1512 WHERE person_id=? AND created_at >= ? ORDER BY created_at DESC LIMIT ?", (person_id, period_start, limit)), limit)
        # V15.14: full BrainLive event bundles are the preferred offline evidence
        # for Life Model updates because they preserve transcripts, diarization,
        # vision descriptions, world states, predictions, interventions and outcomes
        # as one scene instead of short live fragments.
        if _table_exists(con, "brainlive_event_bundles_v1514"):
            live["event_bundles"] = _compact_rows(_query(con, "SELECT * FROM brainlive_event_bundles_v1514 WHERE person_id=? AND COALESCE(end_time, start_time, updated_at, created_at) >= ? ORDER BY COALESCE(start_time, created_at) DESC LIMIT ?", (person_id, period_start, limit)), limit)
        if _table_exists(con, "brainlive_brain2_event_exports_v1514"):
            live["event_exports_to_brain2"] = _compact_rows(_query(con, "SELECT * FROM brainlive_brain2_event_exports_v1514 WHERE person_id=? AND export_status IN ('active','ok','exported') AND updated_at >= ? ORDER BY updated_at DESC LIMIT ?", (person_id, period_start, limit)), limit)
        # V16.0: non-verbal/silent routines and activities created from BrainLive
        # vision/place/world-state evidence. These are important when there was no
        # conversation: computer work, cigarette/pause, resting, walking, waiting.
        if _table_exists(con, "brainlive_silent_event_candidates_v160"):
            live["silent_nonverbal_candidates_v160"] = _compact_rows(_query(con, "SELECT * FROM brainlive_silent_event_candidates_v160 WHERE person_id=? AND COALESCE(end_time, start_time, updated_at, created_at) >= ? ORDER BY COALESCE(start_time, created_at) DESC LIMIT ?", (person_id, period_start, limit)), limit)
        delta["brainlive_bridge_delta"] = live
        delta_id = stable_id("b2delta", person_id, period_start, period_end)
        upsert(con, "brain2_life_model_delta_evidence", {
            "delta_id": delta_id, "person_id": person_id, "period_start": period_start, "period_end": period_end,
            "status": "ready", "source_counts_json": json_dumps(_count(delta)), "raw_evidence_json": json_dumps(delta), "created_at": now_iso(),
        }, "delta_id")
        con.commit()
    return delta


def _summarize_strata(person_id: str) -> dict[str, Any]:
    """Build deterministic strata snapshots from canonical tables+lifecycle."""
    ensure_life_model_updater_schema()
    with connect() as con:
        strata: dict[str, Any] = {"general": {}, "recent": {}, "very_recent": {}}
        for layer, (table, id_col, name_col) in CANONICAL_TABLES.items():
            if not _table_exists(con, table):
                for s in strata:
                    strata[s][layer] = []
                continue
            rows = _query(con, f"SELECT * FROM {table} WHERE person_id=? ORDER BY confidence DESC, updated_at DESC LIMIT 80", (person_id,))
            lifecycle_map: dict[tuple[str, str], dict[str, Any]] = {}
            if _table_exists(con, "brain2_life_model_item_lifecycle"):
                for lc in _query(con, "SELECT * FROM brain2_life_model_item_lifecycle WHERE person_id=? AND source_table=?", (person_id, table)):
                    lifecycle_map[(lc.get("source_id"), lc.get("stratum"))] = lc
            for s in strata:
                items = []
                for r in rows:
                    lc = lifecycle_map.get((r.get(id_col), s))
                    if lc and (str(lc.get("truth_status") or "").lower() in {"contradicted", "obsolete", "rejected", "false", "wrong"} or str(lc.get("use_policy") or "").lower() in {"do_not_use", "forbidden", "never_use"}):
                        continue
                    if s == "general":
                        if r.get("status") in ("obsolete", "contradicted"):
                            continue
                        # General only high-ish confidence unless lifecycle confirmed.
                        if float(r.get("confidence") or 0.0) < 0.55 and not (lc and lc.get("truth_status") in ("confirmed", "active")):
                            continue
                    elif s == "recent":
                        if r.get("status") in ("obsolete",):
                            continue
                    else:  # very_recent
                        if not lc or lc.get("stratum") != "very_recent":
                            continue
                    item = dict(r)
                    if lc:
                        item["lifecycle"] = lc
                    items.append(item)
                strata[s][layer] = _compact_rows(items, 80)
        return strata


def synthesize_life_model_patch(
    current_model: dict[str, Any],
    delta_evidence: dict[str, Any],
    *,
    timeout: float = 180.0,
    person_id: str | None = None,
    package_date: str | None = None,
    source_ref: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    try:
        client = OllamaJsonClient()
        system = (
            "Tu es le Brain2 Life Model Updater. Tu ne réécris PAS toute la vie de William. "
            "Tu proposes uniquement des PATCH OPERATIONS sur le modèle existant: create, confirm, update, weaken, contradict, obsolete ou keep. "
            "Tu dois respecter les strates general/recent/very_recent: general change lentement; recent suit les semaines/mois; very_recent observe les dernières 24-72h. "
            "Aucune psychologie générique, aucune regex, aucune certitude sans preuves. Une occurrence isolée crée au mieux candidate/watch_only, pas une vérité. "
            "Un modèle ne devient proactif live que s'il est actif/confirmé avec preuves, outcomes ou confirmations. JSON strict uniquement."
        )
        owner_summary = (
            _owner_delta_evidence_summary(delta_evidence, person_id)
            if person_id else {"total": 1, "owner_observed_rows": 0,
                               "owner_nonverbal_rows": 0, "observed_outcomes": 0}
        )
        durable_changes = int(owner_summary.get("owner_observed_rows") or 0) + int(
            owner_summary.get("owner_nonverbal_rows") or 0
        ) + 2 * int(owner_summary.get("observed_outcomes") or 0)
        max_per_window = min(6, 3 + min(3, durable_changes))
        output_cardinality = {
            "max_items_per_list": max_per_window,
            "max_operations_total": min(12, max_per_window * 2),
            "basis": owner_summary,
            "overflow_policy": "reject_whole_patch_never_truncate",
        }
        payload = {
            "mission": "Update William's canonical life model by patching it, not rebuilding it. Preserve stable knowledge unless new evidence confirms/contradicts it.",
            "current_life_model": current_model,
            "new_delta_evidence": delta_evidence,
            "output_cardinality": output_cardinality,
            "update_rules": [
                "The model subject is William/me only. owner_scope=owner_verified may describe William; unresolved/other-speaker evidence is context only.",
                "Never attribute another speaker's words, emotion, preference or action to William.",
                "One minute or one occurrence cannot establish a longitudinal pattern or an emotion without an explicit owner-scoped signal.",
                "1 occurrence -> candidate/very_recent/watch_only unless very strong evidence.",
                "2-3 consistent occurrences -> recent hypothesis/active, still cautious.",
                "Repeated confirmations/outcomes -> general/confirmed/proactive_allowed.",
                "Single counter-example weakens only slightly; repeated contradictions can contradict/obsolete.",
                "Never delete/obsolete without counter_evidence and reason.",
                "Separate observed action from inferred need/emotion/intention.",
                "Output patch operations only; include evidence ids/snippets, counter-evidence, lifecycle and live_effect.",
                "Every operation must cite at least one NEW owner-scoped durable row with the exact source_table/source_id from this payload.",
                "Turns are context, not durable trait evidence; when an outcome triggered this run, do not replace it with unrelated speech evidence.",
            ],
            "schema": PATCH_SCHEMA,
        }
        if person_id:
            from .night_orchestrator import run_hierarchical_json
            # Only operations require semantic judgment.  The remaining PATCH
            # fields are policy/telemetry derived from those operations; asking
            # the model to regenerate them for every evidence window caused a
            # costly merge fan-out and added no memory quality.
            operation_result = run_hierarchical_json(
                stage_name="life_model_patch",
                person_id=person_id,
                package_date=str(package_date or now_iso())[:10],
                source_ref=str(source_ref or f"{person_id}:life_model_patch"),
                system=system,
                payload=payload,
                schema={"operations": PATCH_SCHEMA["operations"]},
                timeout=timeout,
                client=client,
                lossless_array_merge=True,
            )
            operations = []
            durable_refs = _durable_owner_evidence_refs(delta_evidence, person_id)
            durable_table_by_id = {
                source_id: table for table, source_id in durable_refs
            }
            for raw_operation in operation_result.get("operations") or []:
                if not isinstance(raw_operation, dict):
                    continue
                operation = dict(raw_operation)
                for evidence_field in ("evidence", "counter_evidence"):
                    normalized_refs = []
                    for raw_ref in operation.get(evidence_field) or []:
                        if isinstance(raw_ref, dict) and raw_ref.get("source_table") and raw_ref.get("source_id"):
                            normalized_refs.append(raw_ref)
                            continue
                        if isinstance(raw_ref, dict):
                            turn_id = raw_ref.get("turn_ref") or raw_ref.get("turn_id")
                            if turn_id:
                                normalized_refs.append({
                                    "source_table": "turns",
                                    "source_id": str(turn_id),
                                    "speaker": raw_ref.get("speaker"),
                                    "text": raw_ref.get("text"),
                                })
                                continue
                            source_id = str(raw_ref.get("source_id") or "")
                            if source_id in durable_table_by_id:
                                normalized_refs.append({
                                    **raw_ref,
                                    "source_table": durable_table_by_id[source_id],
                                    "source_id": source_id,
                                })
                                continue
                            if source_id.startswith("turn_"):
                                normalized_refs.append({
                                    **raw_ref,
                                    "source_table": "turns",
                                    "source_id": source_id,
                                })
                                continue
                        if isinstance(raw_ref, str) and raw_ref.startswith("turn_"):
                            normalized_refs.append({
                                "source_table": "turns", "source_id": raw_ref,
                            })
                            continue
                        normalized_refs.append(raw_ref)
                    operation[evidence_field] = normalized_refs
                operations.append(operation)
            operations = _enforce_life_patch_policy(
                operations,
                durable_refs=durable_refs,
                current_model=current_model,
            )
            if len(operations) > output_cardinality["max_operations_total"]:
                raise RuntimeError(
                    "life_model_patch operations exceed evidence-derived total: "
                    f"{len(operations)}>{output_cardinality['max_operations_total']}"
                )
            patch = {
                "patch_intent": "incremental_update_not_rewrite",
                "operations": operations,
                "strata_guidance": dict(PATCH_SCHEMA["strata_guidance"]),
                "missing_evidence_for_magic": [],
                "do_not_update_without": [
                    "repeated_or_strong_owner_scoped_evidence",
                    "counter_evidence_before_weaken_contradict_or_obsolete",
                    "observed_outcome_before_longitudinal_confirmation",
                ],
                "summary_for_brainlive": [
                    {
                        "target_layer": op.get("target_layer"),
                        "target_id": op.get("target_id"),
                        "identity_key": op.get("identity_key"),
                        "op": op.get("op"),
                        "live_effect": op.get("live_effect") or {},
                    }
                    for op in operations if isinstance(op, dict)
                    and isinstance(op.get("live_effect"), dict)
                    and op.get("live_effect")
                ],
            }
            return patch, None
        return client.require_json(system, json_dumps(payload), schema_hint=PATCH_SCHEMA, timeout=timeout), None
    except Exception as exc:
        return {"llm_required": True, "error": str(exc)}, str(exc)


def _owner_delta_evidence_summary(
    delta: dict[str, Any], person_id: str
) -> dict[str, Any]:
    """Count only evidence that can safely describe the memory owner.

    Conversation rows scoped to the owner's database are not necessarily the
    owner's speech.  Until diarization/voice identity maps a turn to ``me``, it
    may describe the other speaker and must remain context-only.
    """

    aliases = {str(person_id).strip().lower(), "me", "user", "utilisateur", "william"}
    language = delta.get("language") if isinstance(delta.get("language"), dict) else {}
    owner_turn_ids = {
        str(row.get("turn_id"))
        for row in (language.get("turns_recent") or [])
        if isinstance(row, dict)
        and str(row.get("person_id") or "").strip().lower() in aliases
        and row.get("turn_id")
    }
    counts = {"owner_turns": len(owner_turn_ids)}

    observed = delta.get("observed_life") if isinstance(delta.get("observed_life"), dict) else {}
    owner_rows = 0
    owner_keys = {
        "life_events": ("subject_person_id", "person_id"),
        "interaction_episodes": ("user_person_id", "person_id"),
        "choice_episodes": ("person_id",),
        "action_intentions": ("person_id",),
        "action_outcomes": ("person_id",),
    }
    for section, keys in owner_keys.items():
        for row in observed.get(section) or []:
            if not isinstance(row, dict):
                continue
            if any(
                str(row.get(key) or "").strip().lower() in aliases for key in keys
            ):
                owner_rows += 1
    counts["owner_observed_rows"] = owner_rows

    internal = delta.get("self_and_internal") if isinstance(delta.get("self_and_internal"), dict) else {}
    owner_internal = 0
    owner_explicit_self_facts = 0
    for section, rows in internal.items():
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("turn_id") or "") in owner_turn_ids:
                owner_internal += 1
                if section == "self_model_facts":
                    owner_explicit_self_facts += 1
    counts["owner_internal_rows"] = owner_internal
    counts["owner_explicit_self_facts"] = owner_explicit_self_facts

    bridge = delta.get("brainlive_bridge_delta") if isinstance(delta.get("brainlive_bridge_delta"), dict) else {}
    owner_nonverbal = sum(
        1 for row in (
            list(bridge.get("brainlive_silent_event_candidates_v160") or [])
            + list(bridge.get("silent_nonverbal_candidates_v160") or [])
        )
        if isinstance(row, dict)
        and str(row.get("person_id") or person_id).strip().lower() in aliases
    )
    counts["owner_nonverbal_rows"] = owner_nonverbal

    observed_outcomes = 0
    for row in (
        list(bridge.get("brainlive_brain2_reconciliations") or [])
        + list(bridge.get("reconciliations") or [])
    ):
        if not isinstance(row, dict):
            continue
        happened = _safe_json(row.get("what_happened_json"), {})
        if row.get("verdict") in {"confirmed", "contradicted", "partially_confirmed"} and happened:
            observed_outcomes += 1
    counts["observed_outcomes"] = observed_outcomes
    memory = delta.get("memory_and_patterns") if isinstance(delta.get("memory_and_patterns"), dict) else {}
    longitudinal = len(memory.get("confirmed_patterns") or []) + sum(
        1 for row in (memory.get("global_patterns_v17") or [])
        if isinstance(row, dict) and int(
            row.get("evidence_count") or row.get("recurrence_count") or 0
        ) >= 3
    )
    counts["longitudinal_confirmed_rows"] = longitudinal
    counts["total"] = sum(counts.values())
    counts["trigger_total"] = (
        owner_rows + owner_nonverbal + observed_outcomes
        + owner_explicit_self_facts + longitudinal
    )
    return counts


def _durable_owner_evidence_refs(
    delta: dict[str, Any], person_id: str,
) -> set[tuple[str, str]]:
    """List new owner-scoped rows allowed to drive a Life patch."""

    aliases = {str(person_id).strip().lower(), "me", "user", "utilisateur", "william"}
    refs: set[tuple[str, str]] = set()
    observed = delta.get("observed_life") if isinstance(delta.get("observed_life"), dict) else {}
    observed_sources = {
        "life_events": ("event_id", ("subject_person_id", "person_id")),
        "interaction_episodes": ("interaction_id", ("user_person_id", "person_id")),
        "choice_episodes": ("choice_id", ("person_id",)),
        "action_intentions": ("intention_id", ("person_id",)),
        "action_outcomes": ("outcome_id", ("person_id",)),
    }
    for table, (id_field, owner_fields) in observed_sources.items():
        for row in observed.get(table) or []:
            if not isinstance(row, dict):
                continue
            if not any(str(row.get(field) or "").strip().lower() in aliases for field in owner_fields):
                continue
            if row.get(id_field):
                refs.add((table, str(row[id_field])))

    language = delta.get("language") if isinstance(delta.get("language"), dict) else {}
    owner_turn_ids = {
        str(row.get("turn_id")) for row in (language.get("turns_recent") or [])
        if isinstance(row, dict) and row.get("turn_id")
        and str(row.get("person_id") or "").strip().lower() in aliases
    }
    internal = delta.get("self_and_internal") if isinstance(delta.get("self_and_internal"), dict) else {}
    for row in internal.get("self_model_facts") or []:
        if not isinstance(row, dict) or str(row.get("turn_id") or "") not in owner_turn_ids:
            continue
        if row.get("fact_id"):
            refs.add(("self_model_facts", str(row["fact_id"])))

    bridge = delta.get("brainlive_bridge_delta") if isinstance(delta.get("brainlive_bridge_delta"), dict) else {}
    for row in (
        list(bridge.get("brainlive_silent_event_candidates_v160") or [])
        + list(bridge.get("silent_nonverbal_candidates_v160") or [])
    ):
        if not isinstance(row, dict):
            continue
        if str(row.get("person_id") or person_id).strip().lower() in aliases and row.get("candidate_id"):
            refs.add(("brainlive_silent_event_candidates_v160", str(row["candidate_id"])))

    memory = delta.get("memory_and_patterns") if isinstance(delta.get("memory_and_patterns"), dict) else {}
    for row in memory.get("confirmed_patterns") or []:
        if isinstance(row, dict) and row.get("confirmed_pattern_id"):
            refs.add(("confirmed_patterns", str(row["confirmed_pattern_id"])))
    for row in memory.get("global_patterns_v17") or []:
        if not isinstance(row, dict) or int(row.get("evidence_count") or row.get("recurrence_count") or 0) < 3:
            continue
        if row.get("pattern_id"):
            refs.add(("brain2_global_life_patterns_v17", str(row["pattern_id"])))
    return refs


def _enforce_life_patch_policy(
    operations: list[dict[str, Any]], *,
    durable_refs: set[tuple[str, str]], current_model: dict[str, Any],
) -> list[dict[str, Any]]:
    """Require delta causality and keep first sightings watch-only."""

    known_target_ids = {
        str(value)
        for rows in (current_model.get("canonical_layers") or {}).values()
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict)
        for key, value in row.items()
        if key.endswith("_id") and value
    }
    prior_evidence_by_target: dict[str, int] = {}
    for row in current_model.get("lifecycle") or []:
        if not isinstance(row, dict) or not row.get("source_id"):
            continue
        source_id = str(row["source_id"])
        prior_evidence_by_target[source_id] = max(
            prior_evidence_by_target.get(source_id, 0), int(row.get("evidence_count") or 0),
        )

    guarded: list[dict[str, Any]] = []
    for raw in operations:
        operation = dict(raw)
        evidence_keys = {
            (str(ref.get("source_table") or ""), str(ref.get("source_id") or ""))
            for ref in operation.get("evidence") or [] if isinstance(ref, dict)
        }
        new_drivers = evidence_keys & durable_refs
        if not new_drivers:
            # An operation with NO new owner-scoped durable evidence must never
            # become a durable trait (the core "no trait without evidence"
            # invariant). Locally the 9B never emits one, so this raises. DeepSeek
            # (bigger, more eager) sometimes proposes a trait it cannot ground; in
            # PRO, ABSTAIN that single operation instead of blocking the whole
            # CloseDay — every evidence-backed operation still applies and the
            # ungrounded one is dropped exactly as the invariant demands. Never
            # silent. The LOCAL path keeps the hard raise (byte-for-byte unchanged).
            import os as _os
            if _os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
                "1", "true", "yes", "on",
            }:
                try:
                    from .runtime_v18_7 import record_phase_event
                    record_phase_event(
                        "life_patch_operation_abstained_no_durable_evidence",
                        operation=str(
                            operation.get("identity_key")
                            or operation.get("target_id") or "unknown"
                        ),
                    )
                except Exception:
                    pass
                continue
            raise RuntimeError(
                "Life operation has no new owner-scoped durable evidence: "
                f"{operation.get('identity_key') or operation.get('target_id') or 'unknown'}"
            )

        target_id = str(operation.get("target_id") or "")
        if operation.get("op") == "create":
            if target_id in known_target_ids:
                operation["op"] = "update"
            else:
                operation.pop("target_id", None)
                target_id = ""
        support_count = len(new_drivers) + prior_evidence_by_target.get(target_id, 0)
        if support_count < 2:
            operation["stratum"] = "very_recent"
            before = _clamp(operation.get("confidence_before"), 0.0)
            after = min(_clamp(operation.get("confidence_after"), 0.5), 0.65)
            operation["confidence_before"] = before
            operation["confidence_after"] = after
            operation["confidence_delta"] = after - before
            lifecycle = dict(operation.get("lifecycle") or {})
            lifecycle["truth_status"] = "candidate"
            lifecycle["use_policy"] = "watch_only"
            operation["lifecycle"] = lifecycle
            live_effect = dict(operation.get("live_effect") or {})
            live_effect["brainlive_action"] = "watch"
            live_effect["horizons"] = list(live_effect.get("horizons") or ["H1"])
            operation["live_effect"] = live_effect
        guarded.append(operation)
    return guarded


def _watch_identity(*values: Any) -> str:
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
        if text:
            return text[:500]
    return "unknown"


def compile_life_watch_candidates(
    person_id: str, delta: dict[str, Any],
) -> dict[str, Any]:
    """Persist first observations without turning them into owner traits.

    Exact source ids make the compiler idempotent.  A candidate becomes
    promotion-ready only after two independent episode/source groups; semantic
    layer selection remains an LLM task at that point.
    """

    ensure_life_model_updater_schema()
    aliases = {str(person_id).strip().lower(), "me", "user", "utilisateur", "william"}
    seeds: list[dict[str, Any]] = []
    observed = delta.get("observed_life") if isinstance(delta.get("observed_life"), dict) else {}
    source_specs = {
        "life_events": (
            "event_id", ("subject_person_id", "person_id"),
            ("event_type", "summary", "title", "description"),
        ),
        "interaction_episodes": (
            "interaction_id", ("user_person_id", "person_id"),
            ("interaction_type", "summary", "title"),
        ),
        "choice_episodes": (
            "choice_id", ("person_id",),
            ("choice", "chosen_option", "decision", "summary"),
        ),
        "action_intentions": (
            "intention_id", ("person_id",),
            ("action", "intention", "goal", "summary"),
        ),
        "action_outcomes": (
            "outcome_id", ("person_id",),
            ("action_taken", "result", "lesson"),
        ),
    }
    for table, (id_field, owner_fields, identity_fields) in source_specs.items():
        for row in observed.get(table) or []:
            if not isinstance(row, dict) or not row.get(id_field):
                continue
            if not any(str(row.get(field) or "").strip().lower() in aliases for field in owner_fields):
                continue
            source_id = str(row[id_field])
            identity_key = _watch_identity(*(row.get(field) for field in identity_fields))
            seeds.append({
                "candidate_kind": table,
                "identity_key": identity_key,
                "source_table": table,
                "source_id": source_id,
                "episode_id": row.get("episode_id"),
                "occurred_at": row.get("occurred_start") or row.get("created_at") or row.get("updated_at"),
            })

    bridge = delta.get("brainlive_bridge_delta") if isinstance(delta.get("brainlive_bridge_delta"), dict) else {}
    for row in (
        list(bridge.get("brainlive_silent_event_candidates_v160") or [])
        + list(bridge.get("silent_nonverbal_candidates_v160") or [])
    ):
        if not isinstance(row, dict) or not row.get("candidate_id"):
            continue
        if str(row.get("person_id") or person_id).strip().lower() not in aliases:
            continue
        seeds.append({
            "candidate_kind": "silent_nonverbal",
            "identity_key": _watch_identity(
                row.get("event_type"), row.get("activity"), row.get("title"), row.get("summary")
            ),
            "source_table": "brainlive_silent_event_candidates_v160",
            "source_id": str(row["candidate_id"]),
            "episode_id": row.get("bundle_id") or row.get("live_session_id"),
            "occurred_at": row.get("start_time") or row.get("created_at"),
        })

    now = now_iso()
    compiled: list[dict[str, Any]] = []
    with connect() as con:
        for seed in seeds:
            watch_id = stable_id(
                "b2lifewatch", person_id, seed["candidate_kind"], seed["identity_key"]
            )
            existing = con.execute(
                "SELECT * FROM brain2_life_model_watch_candidates WHERE watch_id=?",
                (watch_id,),
            ).fetchone()
            evidence = _safe_json(existing["evidence_json"], []) if existing else []
            if not isinstance(evidence, list):
                evidence = []
            evidence_key = (seed["source_table"], seed["source_id"])
            if not any(
                isinstance(ref, dict)
                and (ref.get("source_table"), ref.get("source_id")) == evidence_key
                for ref in evidence
            ):
                evidence.append({
                    "source_table": seed["source_table"],
                    "source_id": seed["source_id"],
                    "episode_id": seed.get("episode_id"),
                    "occurred_at": seed.get("occurred_at"),
                })
            independent_groups = {
                str(ref.get("episode_id") or ref.get("source_id"))
                for ref in evidence if isinstance(ref, dict)
                and (ref.get("episode_id") or ref.get("source_id"))
            }
            independent_count = len(independent_groups)
            status = "promotion_ready" if independent_count >= 2 else "watching"
            upsert(con, "brain2_life_model_watch_candidates", {
                "watch_id": watch_id, "person_id": person_id,
                "candidate_kind": seed["candidate_kind"],
                "identity_key": seed["identity_key"], "status": status,
                "occurrence_count": len(evidence),
                "independent_count": independent_count,
                "evidence_json": json_dumps(evidence),
                "first_seen_at": existing["first_seen_at"] if existing else (seed.get("occurred_at") or now),
                "last_seen_at": seed.get("occurred_at") or now,
                "promoted_target_layer": existing["promoted_target_layer"] if existing else None,
                "promoted_target_id": existing["promoted_target_id"] if existing else None,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }, "watch_id")
            compiled.append({
                "watch_id": watch_id, "candidate_kind": seed["candidate_kind"],
                "identity_key": seed["identity_key"], "status": status,
                "occurrence_count": len(evidence),
                "independent_count": independent_count,
                "evidence": evidence,
            })
        con.commit()
    unique = {item["watch_id"]: item for item in compiled}
    items = list(unique.values())
    return {
        "candidate_count": len(items),
        "promotion_ready_count": sum(item["status"] == "promotion_ready" for item in items),
        "candidates": items,
    }


_LIFE_CHECKPOINT_SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("observed_life", "episodes"): ("episodes", "episode_id"),
    ("observed_life", "life_events"): ("life_events", "event_id"),
    ("observed_life", "situation_episodes"): ("situation_episodes", "situation_id"),
    ("observed_life", "interaction_episodes"): ("interaction_episodes", "interaction_id"),
    ("observed_life", "choice_episodes"): ("choice_episodes", "choice_id"),
    ("observed_life", "action_intentions"): ("action_intentions", "intention_id"),
    ("observed_life", "action_outcomes"): ("action_outcomes", "outcome_id"),
    ("self_and_internal", "self_model_dimensions"): ("self_model_dimensions", "dimension_id"),
    ("self_and_internal", "self_model_facts"): ("self_model_facts", "fact_id"),
    ("self_and_internal", "internal_state_snapshots"): ("internal_state_snapshots", "state_id"),
    ("self_and_internal", "emotion_evidence"): ("emotion_evidence", "emotion_evidence_id"),
    ("self_and_internal", "thought_hypotheses"): ("thought_hypotheses", "thought_id"),
    ("self_and_internal", "behavior_signals"): ("behavior_signals", "signal_id"),
    ("language", "personal_language_patterns"): ("personal_language_patterns", "language_pattern_id"),
    ("language", "phrase_templates"): ("phrase_templates", "template_id"),
    ("language", "turns_recent"): ("turns", "turn_id"),
    ("memory_and_patterns", "memory_cards"): ("memory_cards", "card_id"),
    ("memory_and_patterns", "candidate_patterns"): ("candidate_patterns", "candidate_pattern_id"),
    ("memory_and_patterns", "confirmed_patterns"): ("confirmed_patterns", "confirmed_pattern_id"),
    ("memory_and_patterns", "global_patterns_v17"): ("brain2_global_life_patterns_v17", "pattern_id"),
    ("forecasts_future", "brainlive_short_horizon_forecasts"): ("brainlive_short_horizon_forecasts", "forecast_id"),
    ("brain2_canonical_life_model", "personal_routine_models"): ("brain2_personal_routine_models", "routine_id"),
    ("brain2_canonical_life_model", "place_preference_models"): ("brain2_place_preference_models", "place_model_id"),
    ("brain2_canonical_life_model", "action_preference_models"): ("brain2_action_preference_models", "action_model_id"),
    ("brain2_canonical_life_model", "need_expectation_models"): ("brain2_need_expectation_models", "need_model_id"),
    ("brain2_canonical_life_model", "expression_state_models"): ("brain2_expression_state_models", "expression_model_id"),
    ("brain2_canonical_life_model", "emotional_trajectory_models"): ("brain2_emotional_trajectory_models", "trajectory_model_id"),
    ("brain2_canonical_life_model", "contextual_self_models"): ("brain2_contextual_self_models", "contextual_model_id"),
    ("brain2_canonical_life_model", "live_prediction_hooks"): ("brain2_live_prediction_hooks", "hook_id"),
    ("brain2_canonical_life_model", "live_affordance_preferences"): ("brain2_live_affordance_preferences", "affordance_pref_id"),
    ("brain2_canonical_life_model", "routine"): ("brain2_personal_routine_models", "routine_id"),
    ("brain2_canonical_life_model", "place"): ("brain2_place_preference_models", "place_model_id"),
    ("brain2_canonical_life_model", "action_preference"): ("brain2_action_preference_models", "action_model_id"),
    ("brain2_canonical_life_model", "need_expectation"): ("brain2_need_expectation_models", "need_model_id"),
    ("brain2_canonical_life_model", "expression_state"): ("brain2_expression_state_models", "expression_model_id"),
    ("brain2_canonical_life_model", "emotional_trajectory"): ("brain2_emotional_trajectory_models", "trajectory_model_id"),
    ("brain2_canonical_life_model", "contextual_self"): ("brain2_contextual_self_models", "contextual_model_id"),
    ("brain2_canonical_life_model", "live_prediction_hook"): ("brain2_live_prediction_hooks", "hook_id"),
    ("brain2_canonical_life_model", "affordance_preference"): ("brain2_live_affordance_preferences", "affordance_pref_id"),
    ("brainlive_bridge_delta", "day_packages"): ("brainlive_day_packages", "package_id"),
    ("brainlive_bridge_delta", "brainlive_day_packages"): ("brainlive_day_packages", "package_id"),
    ("brainlive_bridge_delta", "reconciliations"): ("brainlive_brain2_reconciliations", "reconciliation_id"),
    ("brainlive_bridge_delta", "brainlive_brain2_reconciliations"): ("brainlive_brain2_reconciliations", "reconciliation_id"),
    ("brainlive_bridge_delta", "context_snapshots"): ("brainlive_context_snapshots_v1512", "snapshot_id"),
    ("brainlive_bridge_delta", "brainlive_context_snapshots_v1512"): ("brainlive_context_snapshots_v1512", "snapshot_id"),
    ("brainlive_bridge_delta", "event_bundles"): ("brainlive_event_bundles_v1514", "bundle_id"),
    ("brainlive_bridge_delta", "brainlive_event_bundles_v1514"): ("brainlive_event_bundles_v1514", "bundle_id"),
    ("brainlive_bridge_delta", "event_exports_to_brain2"): ("brainlive_brain2_event_exports_v1514", "export_id"),
    ("brainlive_bridge_delta", "brainlive_brain2_event_exports_v1514"): ("brainlive_brain2_event_exports_v1514", "export_id"),
    ("brainlive_bridge_delta", "silent_nonverbal_candidates_v160"): ("brainlive_silent_event_candidates_v160", "candidate_id"),
    ("brainlive_bridge_delta", "brainlive_silent_event_candidates_v160"): ("brainlive_silent_event_candidates_v160", "candidate_id"),
}


def _life_source_time(row: dict[str, Any]) -> str | None:
    for field in (
        "updated_at", "created_at", "occurred_at", "occurred_start", "start_time",
        "time_start", "last_seen", "observed_at",
    ):
        if row.get(field) is not None:
            return str(row[field])
    return None


def prepare_life_checkpoint_delta(
    person_id: str, delta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exclude only exact source revisions already committed by a prior run."""

    ensure_life_model_updater_schema()
    from .night_orchestrator import content_digest

    projected = deepcopy(delta)
    with connect() as con:
        consumed = {
            (str(row["source_table"]), str(row["source_id"])): str(row["source_digest"])
            for row in con.execute(
                "SELECT source_table,source_id,source_digest FROM brain2_life_model_consumed_sources WHERE person_id=?",
                (person_id,),
            ).fetchall()
        }
    entries: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for (section, name), (source_table, id_field) in _LIFE_CHECKPOINT_SPECS.items():
        container = projected.get(section)
        if not isinstance(container, dict) or not isinstance(container.get(name), list):
            continue
        kept: list[Any] = []
        for raw in container.get(name) or []:
            if not isinstance(raw, dict) or not raw.get(id_field):
                kept.append(raw)
                continue
            source_id = str(raw[id_field])
            source_digest = content_digest(raw)
            if consumed.get((source_table, source_id)) == source_digest:
                continue
            kept.append(raw)
            family = f"{section}.{name}"
            entries.append({
                "source_family": family,
                "source_table": source_table,
                "source_id": source_id,
                "source_digest": source_digest,
                "source_time": _life_source_time(raw),
            })
            family_counts[family] = family_counts.get(family, 0) + 1
        container[name] = kept
    input_digest = content_digest(sorted(
        (
            entry["source_table"], entry["source_id"], entry["source_digest"]
        ) for entry in entries
    ))
    manifest = {
        "input_digest": input_digest,
        "source_count": len(entries),
        "family_counts": family_counts,
        "entries": entries,
    }
    projected["checkpoint_delta_manifest"] = {
        key: value for key, value in manifest.items() if key != "entries"
    }
    return projected, manifest


def commit_life_checkpoint(
    person_id: str, patch_run_id: str, checkpoint: dict[str, Any], *,
    status: str, period_start: str | None, period_end: str | None,
) -> dict[str, Any]:
    """Commit consumed source revisions only after the Life writer succeeded."""

    now = now_iso()
    entries = [entry for entry in checkpoint.get("entries") or [] if isinstance(entry, dict)]
    family_cursors: dict[str, dict[str, Any]] = {}
    for entry in entries:
        family = str(entry.get("source_family") or "unknown")
        cursor = {"source_time": entry.get("source_time"), "source_id": entry.get("source_id")}
        previous = family_cursors.get(family)
        if previous is None or (
            str(cursor.get("source_time") or ""), str(cursor.get("source_id") or "")
        ) > (
            str(previous.get("source_time") or ""), str(previous.get("source_id") or "")
        ):
            family_cursors[family] = cursor
    checkpoint_id = stable_id(
        "b2lifecheckpoint", person_id, checkpoint.get("input_digest") or "empty"
    )
    with connect() as con, write_transaction(con):
        for entry in entries:
            con.execute(
                """INSERT INTO brain2_life_model_consumed_sources(
                       person_id,source_table,source_id,source_digest,source_family,
                       source_time,patch_run_id,consumed_at
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(person_id,source_table,source_id) DO UPDATE SET
                       source_digest=excluded.source_digest,
                       source_family=excluded.source_family,
                       source_time=excluded.source_time,
                       patch_run_id=excluded.patch_run_id,
                       consumed_at=excluded.consumed_at""",
                (
                    person_id, entry["source_table"], entry["source_id"],
                    entry["source_digest"], entry["source_family"],
                    entry.get("source_time"), patch_run_id, now,
                ),
            )
        upsert(con, "brain2_life_model_checkpoints", {
            "checkpoint_id": checkpoint_id,
            "person_id": person_id,
            "patch_run_id": patch_run_id,
            "status": status,
            "input_digest": checkpoint.get("input_digest") or "",
            "source_count": len(entries),
            "family_counts_json": json_dumps(checkpoint.get("family_counts") or {}),
            "family_cursors_json": json_dumps(family_cursors),
            "period_start": period_start,
            "period_end": period_end,
            "committed_at": now,
        }, "checkpoint_id")
    return {
        "checkpoint_id": checkpoint_id,
        "source_count": len(entries),
        "family_counts": checkpoint.get("family_counts") or {},
        "family_cursors": family_cursors,
    }


def _target_table_for_layer(layer: str) -> tuple[str, str, str] | None:
    return CANONICAL_TABLES.get(layer)


def _minimal_canonical_from_operation(
    layer: str, op: dict[str, Any], *, existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Convert one operation patch_data into the V15.10 canonical schema shape."""
    key = LAYER_TO_CANONICAL_KEY.get(layer)
    if not key:
        return {}
    pdata = op.get("patch_data") if isinstance(op.get("patch_data"), dict) else {}
    identity = op.get("identity_key") or pdata.get("name") or pdata.get("routine_name") or pdata.get("place_key") or pdata.get("hook_name") or "unknown"
    base: dict[str, Any] = {}
    for field, value in (existing or {}).items():
        if field in {
            "person_id", "export_id", "created_at", "updated_at", "status",
        } or field.endswith("_id"):
            continue
        if field.endswith("_json"):
            base[field[:-5]] = _safe_json(value, [] if str(value or "").lstrip().startswith("[") else {})
        else:
            base[field] = value
    base.update(pdata)
    base.setdefault("confidence", op.get("confidence_after", op.get("confidence_before", 0.5)))
    base.setdefault("evidence", op.get("evidence") or [])
    base.setdefault("counter_evidence", op.get("counter_evidence") or [])
    # Normalize required name fields per layer.
    if layer == "routine":
        base.setdefault("routine_name", identity)
    elif layer == "place":
        base.setdefault("place_key", identity)
    elif layer == "action_preference":
        base.setdefault("action_or_choice", identity)
    elif layer == "need_expectation":
        base.setdefault("need_or_expectation", identity)
    elif layer == "expression_state":
        base.setdefault("expression_or_style", identity)
    elif layer == "emotional_trajectory":
        base.setdefault("trajectory_name", identity)
    elif layer == "contextual_self":
        base.setdefault("context_key", identity)
    elif layer == "live_prediction_hook":
        base.setdefault("hook_name", identity)
        base.setdefault("horizon", op.get("live_effect", {}).get("horizons", ["H1"])[0] if isinstance(op.get("live_effect"), dict) else "H1")
    elif layer == "affordance_preference":
        base.setdefault("affordance_type", identity)
    return {key: [base]}


def _merge_canonical_models(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if k not in out:
            out[k] = []
        if isinstance(out[k], list) and isinstance(v, list):
            out[k].extend(v)
        else:
            out[k] = v
    return out


def apply_life_model_patch(person_id: str, patch_run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_life_model_updater_schema()
    now = now_iso()
    ops = _list(patch.get("operations")) if isinstance(patch, dict) else []
    canonical_updates: dict[str, Any] = {}
    applied = 0
    with connect() as con:
        for idx, op in enumerate(ops):
            if not isinstance(op, dict):
                continue
            operation = str(op.get("op") or "keep").lower()
            layer = str(op.get("target_layer") or "unknown").lower()
            stratum = str(op.get("stratum") or "recent").lower()
            if stratum not in {"general", "recent", "very_recent"}:
                stratum = "recent"
            identity_key = str(op.get("identity_key") or op.get("target_id") or f"op_{idx}")[:500]
            table_info = _target_table_for_layer(layer)
            target_table = table_info[0] if table_info else None
            target_id = op.get("target_id")
            # For create/update/confirm, also update canonical tables using V15.10 store function.
            if operation in {"create", "update", "confirm"} and layer in LAYER_TO_CANONICAL_KEY:
                existing_payload = None
                if table_info and target_id:
                    existing_row = con.execute(
                        f"SELECT * FROM {table_info[0]} WHERE {table_info[1]}=? AND person_id=?",
                        (target_id, person_id),
                    ).fetchone()
                    existing_payload = dict(existing_row) if existing_row else None
                canonical_updates = _merge_canonical_models(
                    canonical_updates,
                    _minimal_canonical_from_operation(
                        layer, op, existing=existing_payload
                    ),
                )
            if target_table and not target_id:
                prefix = {
                    "routine": "b2routine", "place": "b2place", "action_preference": "b2action", "need_expectation": "b2need",
                    "expression_state": "b2expr", "emotional_trajectory": "b2traj", "contextual_self": "b2ctxself",
                    "live_prediction_hook": "b2hook", "affordance_preference": "b2affpref",
                }.get(layer, "b2life")
                target_id = stable_id(prefix, person_id, identity_key)
            confidence_before = op.get("confidence_before")
            confidence_after = op.get("confidence_after")
            cd = _clamp(confidence_after, _clamp(confidence_before, 0.5)) - _clamp(confidence_before, 0.5)
            if op.get("confidence_delta") is not None:
                try:
                    cd = float(op.get("confidence_delta"))
                except Exception:
                    pass
            operation_id = stable_id("b2patchop", patch_run_id, idx, operation, layer, identity_key)
            operation_already_applied = con.execute(
                "SELECT 1 FROM brain2_life_model_patch_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone() is not None
            upsert(con, "brain2_life_model_patch_operations", {
                "operation_id": operation_id, "patch_run_id": patch_run_id, "person_id": person_id, "op": operation,
                "target_layer": layer, "target_table": target_table, "target_id": target_id, "identity_key": identity_key,
                "stratum": stratum, "reason": op.get("reason"), "evidence_json": json_dumps(op.get("evidence") or []),
                "counter_evidence_json": json_dumps(op.get("counter_evidence") or []),
                "confidence_before": _clamp(confidence_before) if confidence_before is not None else None,
                "confidence_after": _clamp(confidence_after) if confidence_after is not None else None,
                "confidence_delta": cd, "patch_data_json": json_dumps(op.get("patch_data") or {}),
                "lifecycle_json": json_dumps(op.get("lifecycle") or {}), "live_effect_json": json_dumps(op.get("live_effect") or {}),
                "status": "applied" if operation != "keep" else "recorded", "created_at": now,
            }, "operation_id")
            lifecycle = op.get("lifecycle") if isinstance(op.get("lifecycle"), dict) else {}
            truth_status = lifecycle.get("truth_status") or ({"create": "candidate", "confirm": "confirmed", "update": "active", "weaken": "weakened", "contradict": "contradicted", "obsolete": "obsolete", "keep": "active"}.get(operation, "candidate"))
            use_policy = lifecycle.get("use_policy") or ({"candidate": "watch_only", "weakened": "watch_only", "contradicted": "do_not_use", "obsolete": "do_not_use", "confirmed": "proactive_allowed", "active": "silent_context"}.get(truth_status, "watch_only"))
            if target_table and target_id:
                existing = con.execute("SELECT * FROM brain2_life_model_item_lifecycle WHERE person_id=? AND source_table=? AND source_id=? AND stratum=?", (person_id, target_table, target_id, stratum)).fetchone()
                evidence_count = int(existing["evidence_count"] if existing else 0) + (0 if operation_already_applied else len(_list(op.get("evidence"))))
                counter_count = int(existing["counter_evidence_count"] if existing else 0) + (0 if operation_already_applied else len(_list(op.get("counter_evidence"))))
                upsert(con, "brain2_life_model_item_lifecycle", {
                    "lifecycle_id": stable_id("b2lifecycle", person_id, target_table, target_id, stratum),
                    "person_id": person_id, "source_table": target_table, "source_id": target_id, "layer": layer,
                    "identity_key": identity_key, "stratum": stratum, "truth_status": truth_status,
                    "first_seen_at": existing["first_seen_at"] if existing else now,
                    "last_seen_at": now,
                    "last_confirmed_at": now if truth_status in {"active", "confirmed"} else (existing["last_confirmed_at"] if existing else None),
                    "last_contradicted_at": now if truth_status in {"contradicted", "weakened", "obsolete"} else (existing["last_contradicted_at"] if existing else None),
                    "evidence_count": evidence_count, "counter_evidence_count": counter_count,
                    "confidence": _clamp(confidence_after, _clamp(confidence_before, 0.5)),
                    "recency_weight": 1.0 if stratum == "very_recent" else (0.75 if stratum == "recent" else 0.45),
                    "staleness_score": 0.0 if truth_status not in {"obsolete", "contradicted"} else 1.0,
                    "valid_from": lifecycle.get("valid_from"), "valid_until": lifecycle.get("valid_until"),
                    "superseded_by": lifecycle.get("superseded_by"), "obsolete_reason": lifecycle.get("obsolete_reason"),
                    "use_policy": use_policy, "notes_json": json_dumps({"reason": op.get("reason"), "live_effect": op.get("live_effect") or {}}),
                    "updated_at": now, "created_at": existing["created_at"] if existing else now,
                }, "lifecycle_id")
            if not operation_already_applied:
                applied += 1
        con.commit()
    if canonical_updates:
        store_canonical_life_model(person_id, patch_run_id, canonical_updates)
    update_life_model_strata(person_id, patch_run_id=patch_run_id)
    return {"applied_operations": applied, "canonical_update_layers": list(canonical_updates.keys())}


def update_life_model_strata(person_id: str, *, patch_run_id: str | None = None) -> dict[str, Any]:
    ensure_life_model_updater_schema()
    now = now_iso()
    strata = _summarize_strata(person_id)
    with connect() as con:
        for stratum, model in strata.items():
            if stratum == "very_recent":
                start = _iso(_now_dt() - timedelta(days=3))
            elif stratum == "recent":
                start = _iso(_now_dt() - timedelta(days=45))
            else:
                start = None
            upsert(con, "brain2_life_model_strata", {
                "stratum_id": stable_id("b2stratum", person_id, stratum), "person_id": person_id, "stratum": stratum,
                "status": "active", "model_json": json_dumps(model), "evidence_window_start": start,
                "evidence_window_end": now, "patch_run_id": patch_run_id, "source_counts_json": json_dumps(_count(model)),
                "created_at": now, "updated_at": now,
            }, "stratum_id")
        con.commit()
    return {"person_id": person_id, "strata": {k: _count(v) for k, v in strata.items()}}


def run_brain2_life_model_update(person_id: str, *, period_start: str | None = None, period_end: str | None = None, use_llm: bool = True, timeout: float = 180.0, limit: int = 120, bootstrap_if_empty: bool = True) -> dict[str, Any]:
    """Patch the life model with delta evidence and keep general/recent/very_recent snapshots."""
    ensure_life_model_updater_schema()
    now = now_iso()
    current = load_current_life_model(person_id, limit=limit)
    has_current = any(current.get("canonical_layers", {}).get(layer) for layer in current.get("canonical_layers", {}))
    from .brain2_shared_facts_v19 import shared_facts_enabled
    if bootstrap_if_empty and not has_current and not shared_facts_enabled():
        # First run: V15.10 builds the first canonical base from Brain2 evidence.
        bootstrap = build_brain2_canonical_life_model(person_id, period_start=period_start, period_end=period_end, use_llm=use_llm, timeout=timeout, limit=limit)
        update_life_model_strata(person_id, patch_run_id=bootstrap.get("export_id"))
        return {"version": VERSION, "person_id": person_id, "mode": "bootstrap_v15_10", "bootstrap": bootstrap, "strata": update_life_model_strata(person_id, patch_run_id=bootstrap.get("export_id"))}
    raw_delta = collect_life_model_delta(person_id, period_start=period_start, period_end=period_end, limit=limit)
    delta, checkpoint_input = prepare_life_checkpoint_delta(person_id, raw_delta)
    from .night_orchestrator import content_digest
    # The count-only digest could reuse a checkpoint after model content changed
    # without changing cardinality.  Resume keys must cover the actual state.
    current_digest = content_digest(current)
    patch_run_id = stable_id(
        "b2patch", person_id, checkpoint_input.get("input_digest") or "empty",
        current_digest,
    )
    owner_evidence = _owner_delta_evidence_summary(delta, person_id)
    watch_candidates = compile_life_watch_candidates(person_id, delta)
    delta["life_watch_candidates"] = watch_candidates.get("candidates") or []
    semantic_trigger_total = (
        int(owner_evidence.get("owner_explicit_self_facts") or 0)
        + int(owner_evidence.get("longitudinal_confirmed_rows") or 0)
        + int(watch_candidates.get("promotion_ready_count") or 0)
    )
    error: str | None = None
    patch: dict[str, Any]
    if use_llm and semantic_trigger_total == 0:
        patch = {
            "patch_intent": (
                "first_observations_persisted_as_watch_candidates"
                if watch_candidates.get("candidate_count")
                else "no_durable_owner_scoped_life_delta"
            ),
            "operations": [],
            "strata_guidance": dict(PATCH_SCHEMA["strata_guidance"]),
            "missing_evidence_for_magic": [
                "No repeated/independent evidence or confirmed longitudinal pattern justified a canonical Life Model promotion. First observations remain durable watch candidates."
            ],
            "do_not_update_without": ["verified_owner_scoped_evidence"],
            "summary_for_brainlive": [],
        }
        status = (
            "compiled_watch_only"
            if watch_candidates.get("candidate_count")
            else "compiled_no_life_delta"
        )
    elif use_llm:
        patch, error = synthesize_life_model_patch(
            current, delta, timeout=timeout, person_id=person_id,
            package_date=str(period_end or now_iso())[:10],
            source_ref=stable_id(
                "life_model_patch_input", person_id,
                checkpoint_input.get("input_digest") or "empty", current_digest,
            ),
        )
        status = "llm_patch_ready" if not error else "delta_ready_llm_required"
    else:
        patch = {"llm_required": True, "reason": "use_llm=false", "operations": []}
        status = "delta_only_llm_disabled"
    with connect() as con:
        upsert(con, "brain2_life_model_patch_runs", {
            "patch_run_id": patch_run_id, "person_id": person_id, "status": status,
            "period_start": period_start, "period_end": period_end,
            "current_model_digest": current_digest,
            "delta_counts_json": json_dumps(_count(delta)), "patch_json": json_dumps(patch), "error_text": error,
            "llm_model": None, "created_at": now, "finished_at": now_iso(),
        }, "patch_run_id")
        con.commit()
    applied = {"applied_operations": 0}
    if isinstance(patch, dict) and not patch.get("llm_required"):
        applied = apply_life_model_patch(person_id, patch_run_id, patch)
    else:
        update_life_model_strata(person_id, patch_run_id=patch_run_id)
    checkpoint_result = None
    if isinstance(patch, dict) and not patch.get("llm_required"):
        checkpoint_result = commit_life_checkpoint(
            person_id, patch_run_id, checkpoint_input, status=status,
            period_start=period_start, period_end=period_end,
        )
    return {"version": VERSION, "person_id": person_id, "patch_run_id": patch_run_id, "status": status, "delta_counts": _count(delta), "owner_evidence": owner_evidence, "watch_candidates": watch_candidates, "semantic_trigger_total": semantic_trigger_total, "checkpoint": checkpoint_result, "patch": patch, "applied": applied}


def latest_life_model_strata(person_id: str) -> dict[str, Any]:
    ensure_life_model_updater_schema()
    with connect() as con:
        rows = _query(con, "SELECT * FROM brain2_life_model_strata WHERE person_id=? ORDER BY updated_at DESC", (person_id,))
    return {r.get("stratum") or "unknown": {"status": r.get("status"), "model": _safe_json(r.get("model_json"), {}), "updated_at": r.get("updated_at"), "source_counts": _safe_json(r.get("source_counts_json"), {})} for r in rows}


def brain2_life_model_update_audit(person_id: str) -> dict[str, Any]:
    ensure_life_model_updater_schema()
    strata = latest_life_model_strata(person_id)
    with connect() as con:
        runs = _query(con, "SELECT patch_run_id,status,period_start,period_end,delta_counts_json,created_at FROM brain2_life_model_patch_runs WHERE person_id=? ORDER BY created_at DESC LIMIT 5", (person_id,)) if _table_exists(con, "brain2_life_model_patch_runs") else []
        ops = _query(con, "SELECT op,target_layer,stratum,truth_status,use_policy,COUNT(*) AS c FROM brain2_life_model_patch_operations po LEFT JOIN brain2_life_model_item_lifecycle lc ON lc.person_id=po.person_id AND lc.source_id=po.target_id AND lc.stratum=po.stratum WHERE po.person_id=? GROUP BY op,target_layer,stratum,truth_status,use_policy", (person_id,)) if _table_exists(con, "brain2_life_model_patch_operations") else []
    return {"version": VERSION, "person_id": person_id, "strata_available": list(strata.keys()), "strata_counts": {k: v.get("source_counts", {}) for k, v in strata.items()}, "recent_patch_runs": runs, "operation_counts": ops, "verdict": "ready" if strata else "needs_update"}

# Preserve the legacy writer under explicit names before replacing public entry
# points with V18's validation, owner scope and lifecycle gates.
_v17_apply_life_model_patch = apply_life_model_patch
_v17_run_brain2_life_model_update = run_brain2_life_model_update
from . import brain2_life_model_v15_10 as _v18_canonical_life_model_module
from .v18_life_model import install_updater as _install_v18_life_model_updater
_globals_v18_life_model_updater = _install_v18_life_model_updater(__import__(__name__, fromlist=['*']), _v18_canonical_life_model_module)
globals().update(_globals_v18_life_model_updater)
