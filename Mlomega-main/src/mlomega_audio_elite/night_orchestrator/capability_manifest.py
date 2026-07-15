from __future__ import annotations

"""E64-I0.4 product capability manifest (OBS-38).

The close-day durable output manifest proves that every *returned id* has a
retained row.  It does not prove that every REQUIRED product capability actually
produced a product output.  A stage can traverse green while its sub-engine
faked a success:

* Deep Vision reports ``brainlive_deep_vision_runs_v161.status='ok'`` after
  selecting keyframes but analysing zero of them (selected>0, analyzed==0);
* a V13.4/V14 checkpoint is closed "AUDIT ONLY" (audited, not producing);
* a V17 similarity ``abstained`` after the embedder cache was refused;
* an engine returned ``degraded`` / ``bypassed`` but the stage marker stayed
  ``completed``.

This module builds the final census of the MANDATORY capabilities of a
close-day and assigns each an explicit product verdict.  It reads the real
stage results plus the durable sub-engine tables — never the stage marker
alone — so the manifest states the truth (no false-green, no false-red).

Verdicts
--------
``product_validated`` : the capability produced a durable product output.
``valid_empty``       : no output, but emptiness is PROVEN applicable.
``not_applicable``    : the capability was legitimately inapplicable, proven.
``degraded``          : produced a partial / lowered-quality output.  BLOCKS.
``abstained``         : declined to produce (e.g. refused cache).  BLOCKS.
``bypassed``          : the stage was skipped although it was due.  BLOCKS.
``failed``            : the capability failed (incl. false-green).  BLOCKS.

Only ``product_validated``, ``valid_empty`` and ``not_applicable`` let a
close-day reach ``complete=1``.  Any blocking verdict makes the run
``blocked`` with a readable cause and keeps cleanup ineligible.  The manifest
is persisted per run (``v18_close_day_capability_manifests``) so the exact
blocking capability and reason survive the process.
"""

import os
from typing import Any, Callable

from ..db import connect, write_transaction
from ..governance_v18 import ScopeError, StageGateError, strict_one
from ..utils import json_dumps, json_loads, new_id, now_iso

CAPABILITY_GATE_ENV = "MLOMEGA_E64_CAPABILITY_GATE"

# Product verdicts that permit ``complete=1``.  Everything else blocks the run
# and the cleanup gate.
PASSING_VERDICTS = frozenset({"product_validated", "valid_empty", "not_applicable"})
BLOCKING_VERDICTS = frozenset({"degraded", "abstained", "bypassed", "failed"})
ALL_VERDICTS = PASSING_VERDICTS | BLOCKING_VERDICTS

# Sub-engine / stage status tokens that are never a product success even when a
# stage marker reports ``completed``.  These are the "audit only", "bypassed"
# and "declined" runtime states behind OBS-38.
_ABSTAINED_TOKENS = frozenset({"abstained", "abstain", "declined"})
_DEGRADED_TOKENS = frozenset({"degraded", "partial", "quarantined", "blocked", "incomplete"})
_BYPASSED_TOKENS = frozenset({"skipped", "bypassed", "audit_only", "audit-only", "audit only"})
# Life Model successes that look empty but are legitimate epistemic outcomes.
_LIFE_MODEL_VALID_EMPTY = frozenset({"compiled_watch_only", "compiled_no_life_delta"})

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS v18_close_day_capability_manifests(
  manifest_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  complete INTEGER NOT NULL CHECK(complete IN (0,1)),
  blocking_json TEXT NOT NULL DEFAULT '[]',
  capabilities_json TEXT NOT NULL DEFAULT '[]',
  reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v18_capability_manifest_complete
  ON v18_close_day_capability_manifests(person_id, complete, updated_at);
"""


def capability_gate_enabled() -> bool:
    """OBS-38 is a correctness fix, on by default.

    A single emergency switch (``MLOMEGA_E64_CAPABILITY_GATE=0``) restores the
    pre-I0.4 behaviour where ``semantic_warnings`` did not block ``complete=1``,
    for a controlled rollback only.
    """
    return os.environ.get(CAPABILITY_GATE_ENV, "1").strip() != "0"


def ensure_capability_manifest_schema() -> None:
    with connect() as con, write_transaction(con):
        con.executescript(SCHEMA)


def _status(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    return str(result.get("status") or "").strip().lower()


def _capability(
    name: str,
    *,
    verdict: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if verdict not in ALL_VERDICTS:
        raise StageGateError(f"capability {name} got an unsupported verdict {verdict!r}")
    return {
        "capability": name,
        "verdict": verdict,
        "blocks": verdict in BLOCKING_VERDICTS,
        "reason": reason,
        "evidence": evidence or {},
    }


def _table_exists(con: Any, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _verdict_from_status(name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Map a stage/sub-engine status token to a product verdict.

    A missing result is a bypass (the capability never ran).  A recognised
    abstained/degraded/bypassed token is a block.  Any other status is treated
    as a produced output and handed to the caller-supplied evidence check.
    """
    status = _status(result)
    if not isinstance(result, dict) or not status:
        return _capability(name, verdict="bypassed", reason=f"{name} produced no result", evidence={"status": status or None})
    if status in _ABSTAINED_TOKENS:
        return _capability(name, verdict="abstained", reason=f"{name} abstained: {result.get('reason') or status}", evidence={"status": status})
    if status in _BYPASSED_TOKENS:
        return _capability(name, verdict="bypassed", reason=f"{name} was bypassed/audit-only: {status}", evidence={"status": status})
    if status in _DEGRADED_TOKENS or "degraded" in status or "audit_only" in status or "audit only" in status:
        return _capability(name, verdict="degraded", reason=f"{name} is degraded: {status}", evidence={"status": status})
    return _capability(name, verdict="product_validated", reason=f"{name} status {status}", evidence={"status": status})


# --------------------------------------------------------------------------- #
# Per-capability durable checks.  Each reads the REAL sub-engine table, so a    #
# stage marker that says ``ok`` cannot hide a false-green.                      #
# --------------------------------------------------------------------------- #


def _deep_vision_capability(con: Any, *, person_id: str, package_date: str, post_stop: dict[str, Any]) -> dict[str, Any]:
    """False-green detector: selected keyframes > 0 but analyzed == 0.

    ``brainlive_deep_vision_runs_v161`` carries selected/analyzed. Deep Vision
    reports ``status='ok'`` even when every selected frame was quarantined; the
    durable row exposes that. ``valid_empty`` is only accepted when nothing was
    selected (no visual evidence to analyse).
    """
    name = "deep_vision"
    deep = post_stop.get("v16_deep_vision") if isinstance(post_stop, dict) else None
    if not isinstance(deep, dict):
        return _capability(name, verdict="bypassed", reason="deep vision produced no result in post-stop", evidence={})
    status = _status(deep)
    if status in {"skipped", "skipped_requires_retention", "skipped_no_audio"}:
        # A skip is only valid when the durable row confirms nothing was selected.
        pass
    if not _table_exists(con, "brainlive_deep_vision_runs_v161"):
        # No durable row to prove against: trust only a proven-empty stage.
        if status in {"ok", "completed"}:
            return _capability(name, verdict="valid_empty", reason="deep vision reported ok, no durable run row (no bundles)", evidence={"status": status})
        return _verdict_from_status(name, deep)
    rows = con.execute(
        "SELECT scanned_bundles,selected_keyframes,analyzed_keyframes,status "
        "FROM brainlive_deep_vision_runs_v161 WHERE person_id=? AND package_date=?",
        (person_id, package_date),
    ).fetchall()
    if not rows:
        # No run row at all: emptiness is only valid if the stage itself is ok
        # (nothing to analyse). A non-ok stage without a row is a bypass.
        if status in {"ok", "completed"}:
            return _capability(name, verdict="valid_empty", reason="no deep-vision run row (no active bundles)", evidence={"status": status})
        return _capability(name, verdict="bypassed", reason=f"deep vision has no durable run row and stage is {status}", evidence={"status": status})
    selected = sum(int(r["selected_keyframes"] or 0) for r in rows)
    analyzed = sum(int(r["analyzed_keyframes"] or 0) for r in rows)
    scanned = sum(int(r["scanned_bundles"] or 0) for r in rows)
    row_statuses = {str(r["status"] or "").strip().lower() for r in rows}
    evidence = {"scanned_bundles": scanned, "selected_keyframes": selected, "analyzed_keyframes": analyzed, "run_statuses": sorted(row_statuses)}
    if any(rs in {"error", "blocked"} for rs in row_statuses):
        return _capability(name, verdict="failed", reason="deep vision run is error/blocked", evidence=evidence)
    if selected > 0 and analyzed == 0:
        # The OBS-38 false-green: keyframes were chosen but none were analysed,
        # yet the run says ``ok``.
        return _capability(name, verdict="failed", reason="deep vision selected keyframes but analysed none (false-green)", evidence=evidence)
    if selected == 0:
        # Nothing to analyse: valid empty only when the stage itself is ok.
        if status in {"ok", "completed"} and not (row_statuses - {"ok", "completed"}):
            return _capability(name, verdict="valid_empty", reason="no keyframes selected for analysis", evidence=evidence)
        return _capability(name, verdict="degraded", reason=f"deep vision selected nothing and run status is {sorted(row_statuses)}", evidence=evidence)
    if analyzed < selected:
        # Some frames analysed, some not: partial, and the run masked it as ok.
        return _capability(name, verdict="degraded", reason="deep vision analysed only part of the selected keyframes", evidence=evidence)
    return _capability(name, verdict="product_validated", reason="deep vision analysed every selected keyframe", evidence=evidence)


def _deep_audio_capability(post_stop: dict[str, Any]) -> dict[str, Any]:
    name = "deep_audio"
    deep = post_stop.get("v18_deep_audio") if isinstance(post_stop, dict) else None
    if not isinstance(deep, dict):
        return _capability(name, verdict="bypassed", reason="deep audio produced no result", evidence={})
    status = _status(deep)
    if status == "skipped_no_audio":
        return _capability(name, verdict="not_applicable", reason="no raw audio to refine", evidence={"status": status})
    if status == "skipped_requires_retention":
        # Raw audio existed but refinement was skipped: cleanup must stay blocked.
        return _capability(name, verdict="bypassed", reason="deep audio skipped while raw audio requires retention", evidence={"status": status})
    if status in {"ok", "completed"}:
        return _capability(name, verdict="product_validated", reason="deep audio completed", evidence={"status": status})
    return _verdict_from_status(name, deep)


def _event_assembly_capability(post_stop: dict[str, Any]) -> dict[str, Any]:
    name = "event_assembly"
    assembly = post_stop.get("assembly") if isinstance(post_stop, dict) else None
    if not isinstance(assembly, dict):
        return _capability(name, verdict="bypassed", reason="event assembly produced no result", evidence={})
    if bool(assembly.get("incomplete")):
        return _capability(name, verdict="degraded", reason=f"event assembly incomplete: {assembly.get('incomplete_reasons')}", evidence={"incomplete": True})
    bundles = int(assembly.get("bundles", 0) or 0)
    raw_rows = int(assembly.get("raw_rows", 0) or 0)
    if raw_rows == 0 and bundles == 0:
        return _capability(name, verdict="valid_empty", reason="no raw timeline rows to assemble", evidence={"bundles": 0, "raw_rows": 0})
    return _capability(name, verdict="product_validated", reason="event assembly produced bundles", evidence={"bundles": bundles, "raw_rows": raw_rows})


def _brain2_capability(post_stop: dict[str, Any]) -> dict[str, Any]:
    """V13 pack local/global + V14 identity/open-loops/interpersonal.

    The V13/V14 deep stack runs inside the post-stop ``brain2`` sub-stage. Its
    per-conversation status lands in ``brain2_processed``. An "AUDIT ONLY" or
    otherwise non-ok conversation outcome is a bypass, not a product output.
    """
    name = "brain2_v13_v14"
    processed = post_stop.get("brain2_processed") if isinstance(post_stop, dict) else None
    if processed is None:
        return _capability(name, verdict="bypassed", reason="brain2 V13/V14 produced no result", evidence={})
    if not isinstance(processed, list):
        return _capability(name, verdict="degraded", reason="brain2 result is not a conversation list", evidence={})
    if not processed:
        # No conversation to deepen (e.g. a silent day) is a proven empty only
        # when the post-stop stage itself completed.
        if _status(post_stop) in {"completed", "ok"}:
            return _capability(name, verdict="valid_empty", reason="no exported conversation required V13/V14", evidence={"conversations": 0})
        return _capability(name, verdict="bypassed", reason="no brain2 conversations and post-stop not completed", evidence={})
    audited: list[str] = []
    degraded: list[str] = []
    for entry in processed:
        if not isinstance(entry, dict):
            continue
        st = str(entry.get("status") or "").strip().lower()
        conv = str(entry.get("conversation_id") or entry.get("id") or "?")
        if st in _BYPASSED_TOKENS or "audit" in st:
            audited.append(conv)
        elif st and st not in {"ok", "completed", "skipped_already_ok"}:
            degraded.append(conv)
    if audited:
        return _capability(name, verdict="bypassed", reason=f"brain2 conversations closed audit-only/bypassed: {audited}", evidence={"audit_only": audited})
    if degraded:
        return _capability(name, verdict="degraded", reason=f"brain2 conversations did not complete V13/V14: {degraded}", evidence={"degraded": degraded})
    return _capability(name, verdict="product_validated", reason="brain2 V13/V14 completed on every conversation", evidence={"conversations": len(processed)})


def _coordination_capability(coordination: dict[str, Any]) -> dict[str, Any]:
    """Day package / watch bindings / reconciliation.

    A child (package/bindings/reconciliation) that ``abstained`` — for example
    a V17 similarity that declined after the embedder cache was refused —
    blocks the day.
    """
    name = "coordination"
    if not isinstance(coordination, dict):
        return _capability(name, verdict="bypassed", reason="coordination produced no result", evidence={})
    if _status(coordination) in _ABSTAINED_TOKENS:
        return _capability(name, verdict="abstained", reason="coordination abstained", evidence={"status": _status(coordination)})
    abstained_children: dict[str, str] = {}
    degraded_children: dict[str, str] = {}
    for child_name in ("package", "bindings", "reconciliation"):
        child = coordination.get(child_name)
        if not isinstance(child, dict):
            continue
        st = _status(child)
        if st in _ABSTAINED_TOKENS:
            abstained_children[child_name] = str(child.get("reason") or st)
        elif st in _DEGRADED_TOKENS:
            degraded_children[child_name] = st
    if abstained_children:
        return _capability(name, verdict="abstained", reason=f"coordination child abstained: {abstained_children}", evidence={"abstained": abstained_children})
    if degraded_children:
        return _capability(name, verdict="degraded", reason=f"coordination child degraded: {degraded_children}", evidence={"degraded": degraded_children})
    return _verdict_from_status(name, coordination)


def _life_model_capability(life: dict[str, Any]) -> dict[str, Any]:
    """Life Model patch.

    ``compiled_watch_only`` and ``compiled_no_life_delta`` are VALID successes
    (first observation retained without promotion, or the idempotent resume
    verdict) — they are ``valid_empty``, never a failure.
    """
    name = "life_model"
    if not isinstance(life, dict):
        return _capability(name, verdict="bypassed", reason="life model produced no result", evidence={})
    status = _status(life)
    if status in _LIFE_MODEL_VALID_EMPTY:
        return _capability(name, verdict="valid_empty", reason=f"life model valid success: {status}", evidence={"status": status})
    if status in {"llm_patch_ready", "ok", "completed", "active"}:
        return _capability(name, verdict="product_validated", reason=f"life model patch: {status}", evidence={"status": status})
    if life.get("mode") == "bootstrap_v15_10":
        bootstrap = life.get("bootstrap") or {}
        bstatus = str((bootstrap or {}).get("status") or "").strip().lower()
        if bstatus == "abstained_no_owner_evidence":
            return _capability(name, verdict="valid_empty", reason="life model bootstrap abstained: no owner evidence (proven applicable)", evidence={"bootstrap_status": bstatus})
        if bstatus in {"llm_ready", "ok", "completed", "active"}:
            return _capability(name, verdict="product_validated", reason=f"life model bootstrap: {bstatus}", evidence={"bootstrap_status": bstatus})
        return _capability(name, verdict="bypassed", reason=f"life model bootstrap status {bstatus}", evidence={"bootstrap_status": bstatus})
    return _verdict_from_status(name, life)


def _empty_output_capability(
    name: str,
    result: dict[str, Any],
    *,
    id_keys: tuple[str, ...],
    has_eligible_inputs: bool,
    inputs_label: str,
) -> dict[str, Any]:
    """A V19 stage whose product output is a list of ids.

    An empty output is ``valid_empty`` ONLY when there were no eligible durable
    inputs (proven applicability). An empty output WITH eligible inputs is a
    false-green — the stage traversed but produced nothing it should have.
    """
    if not isinstance(result, dict):
        return _capability(name, verdict="bypassed", reason=f"{name} produced no result", evidence={})
    status = _status(result)
    if status in _ABSTAINED_TOKENS:
        return _capability(name, verdict="abstained", reason=f"{name} abstained", evidence={"status": status})
    if status in _DEGRADED_TOKENS or status in _BYPASSED_TOKENS:
        return _verdict_from_status(name, result)
    produced: list[str] = []
    for key in id_keys:
        value = result.get(key)
        if isinstance(value, list):
            produced.extend(str(x) for x in value if x)
        elif isinstance(value, dict):
            for sub in value.values():
                if isinstance(sub, list):
                    produced.extend(str(x) for x in sub if x)
    produced = [p for p in dict.fromkeys(produced)]
    if produced:
        return _capability(name, verdict="product_validated", reason=f"{name} produced {len(produced)} output(s)", evidence={"produced": len(produced)})
    if has_eligible_inputs:
        return _capability(
            name, verdict="failed",
            reason=f"{name} produced nothing despite eligible {inputs_label} (false-green)",
            evidence={"produced": 0, "eligible_inputs": True},
        )
    return _capability(name, verdict="valid_empty", reason=f"{name} empty and no eligible {inputs_label} (proven applicable)", evidence={"produced": 0, "eligible_inputs": False})


def build_capability_manifest(
    *,
    person_id: str,
    package_date: str,
    stage_results: dict[str, dict[str, Any]],
    semantic_warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recense the mandatory capabilities and assign each a product verdict.

    ``semantic_warnings`` (from the existing ``_semantic_output_warnings``)
    prove that a V19 stage had eligible durable inputs yet produced nothing;
    that turns an "empty" into a false-green ``failed`` rather than a benign
    ``valid_empty``.
    """
    warnings_by_code = {str((w or {}).get("code")): w for w in (semantic_warnings or [])}
    post_stop = stage_results.get("post_stop") or {}
    capabilities: list[dict[str, Any]] = []

    with connect() as con:
        # 1-4: post-stop sub-engines, read from durable rows where they exist.
        capabilities.append(_deep_audio_capability(post_stop))
        capabilities.append(_deep_vision_capability(con, person_id=person_id, package_date=package_date, post_stop=post_stop))
        capabilities.append(_event_assembly_capability(post_stop))
        capabilities.append(_brain2_capability(post_stop))

    # 5: visual consolidation (close-day stage).
    capabilities.append(_verdict_from_status("visual_consolidation", stage_results.get("visual_consolidation") or {}))

    # 6: longitudinal rollups. A period rollup that was due but not durably
    # observed is reported by the semantic warning; it is a bypass here.
    longitudinal = stage_results.get("longitudinal") or {}
    if warnings_by_code.get("longitudinal_rollup_not_durably_observed"):
        capabilities.append(_capability(
            "longitudinal", verdict="bypassed",
            reason="a due week/month rollup was not durably observed",
            evidence=warnings_by_code["longitudinal_rollup_not_durably_observed"],
        ))
    else:
        capabilities.append(_verdict_from_status("longitudinal", longitudinal))

    # 7: coordination (day package / watch bindings / reconciliation).
    capabilities.append(_coordination_capability(stage_results.get("coordination") or {}))

    # 8: Life Model patch.
    capabilities.append(_life_model_capability(stage_results.get("life_model") or {}))

    # 9-12: V19 stages whose empty output is only valid without eligible inputs.
    capabilities.append(_empty_output_capability(
        "outcome_resolution", stage_results.get("outcome_resolution") or {},
        id_keys=("outcome_ids",), has_eligible_inputs=False, inputs_label="prediction outcomes",
    ))
    capabilities.append(_empty_output_capability(
        "life_model_v19", stage_results.get("life_model_v19") or {},
        id_keys=("confirmed", "contradicted", "weakened", "projected"),
        has_eligible_inputs=bool(warnings_by_code.get("life_model_v19_empty_with_canonical_inputs")),
        inputs_label="canonical model inputs",
    ))
    capabilities.append(_empty_output_capability(
        "prediction_emission", stage_results.get("prediction_emission") or {},
        id_keys=("prediction_ids",),
        has_eligible_inputs=bool(warnings_by_code.get("prediction_emission_empty_with_eligible_entries")),
        inputs_label="predictable entries",
    ))
    capabilities.append(_empty_output_capability(
        "self_schema", stage_results.get("self_schema") or {},
        id_keys=("schema_entry_ids",),
        has_eligible_inputs=bool(warnings_by_code.get("self_schema_empty_with_eligible_inputs")),
        inputs_label="self-schema inputs",
    ))

    # 13: live-ready projection.
    capabilities.append(_verdict_from_status("live_ready", stage_results.get("live_ready") or {}))

    blocking = [c for c in capabilities if c["blocks"]]
    complete = not blocking
    reason = None
    if blocking:
        reason = "; ".join(f"{c['capability']}={c['verdict']} ({c['reason']})" for c in blocking)
    return {
        "person_id": person_id,
        "package_date": package_date,
        "complete": complete,
        "capabilities": capabilities,
        "blocking": blocking,
        "reason": reason,
    }


def persist_capability_manifest(
    *, run_id: str, person_id: str, package_date: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Persist the detailed manifest per run, keyed by the canonical run id."""
    ensure_capability_manifest_schema()
    with connect() as con, write_transaction(con):
        run = strict_one(con, "SELECT person_id FROM v18_pipeline_runs WHERE run_id=?", (run_id,), purpose="capability manifest run owner")
        if not run:
            raise StageGateError(f"unknown pipeline run: {run_id}")
        if str(run["person_id"]) != person_id:
            raise ScopeError("capability manifest owner does not match run owner")
        con.execute(
            """INSERT INTO v18_close_day_capability_manifests(
                 manifest_id,run_id,person_id,package_date,complete,blocking_json,capabilities_json,reason,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET complete=excluded.complete,
                 blocking_json=excluded.blocking_json,capabilities_json=excluded.capabilities_json,
                 reason=excluded.reason,updated_at=excluded.updated_at""",
            (
                new_id("capability_manifest"), run_id, person_id, package_date,
                1 if manifest["complete"] else 0,
                json_dumps(manifest["blocking"]), json_dumps(manifest["capabilities"]),
                manifest.get("reason"), now_iso(), now_iso(),
            ),
        )
    return manifest


def load_capability_manifest(*, run_id: str) -> dict[str, Any] | None:
    ensure_capability_manifest_schema()
    with connect() as con:
        row = strict_one(
            con,
            "SELECT run_id,person_id,package_date,complete,blocking_json,capabilities_json,reason "
            "FROM v18_close_day_capability_manifests WHERE run_id=?",
            (run_id,),
            purpose="capability manifest lookup",
        )
    if not row:
        return None
    return {
        "run_id": row["run_id"],
        "person_id": row["person_id"],
        "package_date": row["package_date"],
        "complete": bool(row["complete"]),
        "blocking": json_loads(row["blocking_json"], []),
        "capabilities": json_loads(row["capabilities_json"], []),
        "reason": row["reason"],
    }
