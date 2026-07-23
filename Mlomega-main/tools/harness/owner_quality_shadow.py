from __future__ import annotations

"""Manual, proposal-only quality audit for an existing MLOmega database.

The source database is always opened read-only.  ``--plan-only`` performs no
model call.  ``--execute`` requires the exact saved plan, works on a fresh
clone and only emits a JSON report: it never rewrites canonical memory tables.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


PROPOSAL_ONLY = (
    "bounded_actions_only: no generated SQL; canonical writes are limited to "
    "deterministic confidence clamps, all other decisions are audited overlays"
)
_PLACEHOLDERS = {
    "", "unknown", "inconnu", "none", "null", "n/a", "na", "undefined",
    "unspecified", "not specified", "true", "false",
}
_DETERMINISTIC_KINDS = {
    "confidence_above_evidence_ceiling",
    "fact_claims_missing_evidence",
    "exact_duplicate_canonical_fact",
    "prediction_without_replayable_proof",
    "duplicate_life_watch",
    "premature_life_promotion",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _clone_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"clone déjà présent; utilise un nouveau --out: {target}")
    with _connect_ro(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def _json(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _compact(value: Any, limit: int = 700) -> str:
    if isinstance(value, str):
        parsed = _json(value)
        text = (
            json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if parsed is not None
            else value
        )
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _candidate(
    kind: str,
    title: str,
    reason: str,
    refs: Iterable[dict[str, Any]],
    *,
    severity: str = "review",
    evidence: Any = None,
    suggestion: str = "review",
) -> dict[str, Any]:
    refs_list = sorted(
        [dict(ref) for ref in refs],
        key=lambda ref: (str(ref.get("table")), str(ref.get("id"))),
    )
    identity = json.dumps(
        {"kind": kind, "refs": refs_list, "reason": reason},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "candidate_id": "oqs_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:18],
        "kind": kind,
        "severity": severity,
        "title": title,
        "reason": reason,
        "refs": refs_list,
        "evidence": evidence,
        "suggested_action": suggestion,
        "authority": PROPOSAL_ONLY,
    }


def _owner_clause(columns: set[str], owner_id: str) -> tuple[str, tuple[Any, ...]]:
    return (" WHERE person_id=?", (owner_id,)) if "person_id" in columns else ("", ())


def _scan_shared_facts(
    con: sqlite3.Connection, owner_id: str
) -> list[dict[str, Any]]:
    tables = _tables(con)
    table = "brain2_shared_facts_v19"
    if table not in tables:
        return []
    facts = [
        dict(row)
        for row in con.execute(
            """SELECT fact_id,person_id,conversation_id,episode_id,source_engine,
                      source_field,fact_type,subject_ref,epistemic_status,
                      evidence_status,confidence,confidence_ceiling,payload_json,
                      payload_digest
               FROM brain2_shared_facts_v19 WHERE person_id=?""",
            (owner_id,),
        )
    ]
    findings: list[dict[str, Any]] = []
    by_digest: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for fact in facts:
        digest = str(fact.get("payload_digest") or "")
        if digest:
            by_digest.setdefault(
                (
                    str(fact.get("conversation_id") or ""),
                    str(fact.get("episode_id") or ""),
                    digest,
                ),
                [],
            ).append(fact)
        confidence = float(fact.get("confidence") or 0.0)
        ceiling = float(fact.get("confidence_ceiling") or 0.0)
        if ceiling > 0 and confidence > ceiling + 1e-9:
            findings.append(_candidate(
                "confidence_above_evidence_ceiling",
                f"Confiance {confidence:.2f} supérieure au plafond {ceiling:.2f}",
                "La confiance dérivée dépasse le plafond de sa meilleure preuve.",
                [{"table": table, "id": fact["fact_id"]}],
                severity="high",
                evidence={
                    "fact_type": fact.get("fact_type"),
                    "source_engine": fact.get("source_engine"),
                    "confidence": confidence,
                    "confidence_ceiling": ceiling,
                },
                suggestion="review_confidence_only",
            ))
    for (conversation_id, episode_id, digest), group in by_digest.items():
        if len(group) <= 1:
            continue
        findings.append(_candidate(
            "exact_duplicate_canonical_fact",
            f"{len(group)} faits canoniques au payload identique",
            "Le même payload_digest existe plusieurs fois pour le même owner.",
            [{"table": table, "id": fact["fact_id"]} for fact in group],
            evidence={
                "payload_digest": digest,
                "conversation_id": conversation_id,
                "episode_id": episode_id,
                "engines": sorted({str(f.get("source_engine") or "") for f in group}),
                "payload": _compact(group[0].get("payload_json")),
            },
            suggestion="propose_canonical_keep_and_aliases",
        ))

    evidence_by_fact: set[str] = set()
    if "brain2_shared_fact_evidence_v19" in tables:
        evidence_by_fact = {
            str(row[0])
            for row in con.execute(
                """SELECT DISTINCT e.fact_id
                   FROM brain2_shared_fact_evidence_v19 e
                   JOIN brain2_shared_facts_v19 f ON f.fact_id=e.fact_id
                   WHERE f.person_id=?""",
                (owner_id,),
            )
        }
    for fact in facts:
        if (
            str(fact.get("evidence_status") or "").lower() == "cited"
            and str(fact["fact_id"]) not in evidence_by_fact
        ):
            findings.append(_candidate(
                "fact_claims_missing_evidence",
                "Fait déclaré sourcé sans lien de preuve",
                "evidence_status=cited mais aucune ligne de preuve ne référence le fait.",
                [{"table": table, "id": fact["fact_id"]}],
                severity="high",
                evidence={
                    "fact_type": fact.get("fact_type"),
                    "source_engine": fact.get("source_engine"),
                    "payload": _compact(fact.get("payload_json")),
                },
                suggestion="quarantine_until_evidence_is_restored",
            ))

    # Same semantic slot with different payloads is an ambiguity, not an automatic
    # contradiction.  DeepSeek/human review decides from the cited evidence.
    semantic_slots: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for fact in facts:
        key = (
            str(fact.get("subject_ref") or ""),
            str(fact.get("fact_type") or ""),
            str(fact.get("source_field") or ""),
        )
        semantic_slots.setdefault(key, []).append(fact)
    for key, group in semantic_slots.items():
        digests = {str(item.get("payload_digest") or "") for item in group}
        if len(group) < 2 or len(digests) < 2 or not key[1]:
            continue
        findings.append(_candidate(
            "possible_semantic_conflict",
            f"Valeurs différentes pour {key[1]}",
            "Plusieurs faits occupent le même slot sémantique; évolution, nuance et contradiction doivent être distinguées.",
            [{"table": table, "id": fact["fact_id"]} for fact in group[:12]],
            evidence={
                "subject_ref": key[0] or None,
                "source_field": key[2] or None,
                "payloads": [_compact(fact.get("payload_json"), 360) for fact in group[:12]],
            },
            suggestion="classify_evolution_vs_contradiction",
        ))
    return findings


def _scan_life_and_predictions(
    con: sqlite3.Connection, owner_id: str
) -> list[dict[str, Any]]:
    tables = _tables(con)
    findings: list[dict[str, Any]] = []
    if "brain2_life_model_watch_candidates" in tables:
        rows = [
            dict(row)
            for row in con.execute(
                """SELECT * FROM brain2_life_model_watch_candidates
                   WHERE person_id=?""",
                (owner_id,),
            )
        ]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row.get("candidate_kind") or ""), str(row.get("identity_key") or ""))
            grouped.setdefault(key, []).append(row)
            promoted = bool(row.get("promoted_target_id")) or "promot" in str(
                row.get("status") or ""
            ).lower()
            if promoted and (
                int(row.get("occurrence_count") or 0) < 2
                or int(row.get("independent_count") or 0) < 2
            ):
                findings.append(_candidate(
                    "premature_life_promotion",
                    "Promotion Life Model avec preuve insuffisante",
                    "Une promotion doit commencer watch et exiger répétition ou preuves indépendantes.",
                    [{"table": "brain2_life_model_watch_candidates", "id": row["watch_id"]}],
                    severity="high",
                    evidence={
                        "candidate_kind": row.get("candidate_kind"),
                        "identity_key": row.get("identity_key"),
                        "occurrences": row.get("occurrence_count"),
                        "independent_sources": row.get("independent_count"),
                        "status": row.get("status"),
                        "sources": _json(row.get("evidence_json"), []),
                    },
                    suggestion="review_or_demote_to_watch",
                ))
        for key, group in grouped.items():
            if len(group) > 1:
                findings.append(_candidate(
                    "duplicate_life_watch",
                    f"{len(group)} watches pour {key[0] or 'type inconnu'} / {key[1] or 'clé vide'}",
                    "candidate_kind et identity_key identiques devraient former un seul historique de watch.",
                    [
                        {"table": "brain2_life_model_watch_candidates", "id": row["watch_id"]}
                        for row in group
                    ],
                    evidence={"candidate_kind": key[0], "identity_key": key[1]},
                    suggestion="propose_watch_merge_preserving_all_sources",
                ))

    for table in ("predictions_v19", "predictions"):
        if table not in tables:
            continue
        cols = _columns(con, table)
        owner_sql, params = _owner_clause(cols, owner_id)
        rows = [dict(row) for row in con.execute(f'SELECT * FROM "{table}"{owner_sql}', params)]
        id_col = "prediction_id" if "prediction_id" in cols else "id"
        for row in rows:
            evidence = row.get("evidence_refs_json") or row.get("evidence_json")
            verification = row.get("verification_spec_json") or row.get("verification_spec")
            if not _json(evidence, []) or not _json(verification, {}):
                rid = row.get(id_col) or row.get("prediction_case_id") or "row"
                findings.append(_candidate(
                    "prediction_without_replayable_proof",
                    "Prédiction sans preuve ou vérificateur relisible",
                    "Une prédiction durable doit citer ses précédents et décrire comment son outcome sera vérifié.",
                    [{"table": table, "id": rid}],
                    severity="high",
                    evidence={
                        "statement": row.get("statement") or row.get("prediction"),
                        "confidence": row.get("confidence"),
                        "has_evidence": bool(_json(evidence, [])),
                        "has_verification_spec": bool(_json(verification, {})),
                    },
                    suggestion="keep_unpromoted_until_proven",
                ))
    return findings


def _scan_cross_table_semantics(
    con: sqlite3.Connection, owner_id: str
) -> list[dict[str, Any]]:
    tables = _tables(con)
    specs = {
        "life_model_entries_v19": ("entry_id", "statement"),
        "self_schema_v19": ("schema_id", "statement"),
        "predictions_v19": ("prediction_id", "statement"),
        "brainlive_life_hypotheses": ("hypothesis_id", "statement"),
        "confirmed_patterns": ("pattern_id", "summary"),
        "candidate_patterns": ("pattern_id", "summary"),
    }
    normalized: dict[str, list[dict[str, Any]]] = {}
    findings: list[dict[str, Any]] = []
    for table, (id_col, text_col) in specs.items():
        if table not in tables:
            continue
        cols = _columns(con, table)
        if id_col not in cols or text_col not in cols:
            continue
        owner_sql, params = _owner_clause(cols, owner_id)
        rows = con.execute(
            f'SELECT "{id_col}","{text_col}" FROM "{table}"{owner_sql}', params
        )
        for row in rows:
            text = " ".join(str(row[text_col] or "").casefold().split())
            if not text or text in _PLACEHOLDERS:
                findings.append(_candidate(
                    "schema_filler",
                    f"Entrée sémantique vide dans {table}",
                    "La ligne remplit un schéma sans assertion humaine exploitable.",
                    [{"table": table, "id": row[id_col]}],
                    evidence={"semantic_field": text_col, "value": row[text_col]},
                    suggestion="review_placeholder_or_quarantine",
                ))
            elif len(text) >= 12:
                normalized.setdefault(text, []).append(
                    {"table": table, "id": row[id_col], "text": str(row[text_col])}
                )
    for _text, refs in normalized.items():
        if len(refs) <= 1 or len({ref["table"] for ref in refs}) <= 1:
            continue
        findings.append(_candidate(
            "cross_table_semantic_duplicate",
            f"Même assertion dans {len(refs)} couches",
            "Une assertion identique peut être une projection légitime ou une duplication inutile; ne pas supprimer sans contrat consommateur.",
            [{"table": ref["table"], "id": ref["id"]} for ref in refs],
            evidence={"statement": refs[0]["text"]},
            suggestion="classify_projection_vs_duplicate",
        ))
    return findings


def scan_database(
    source: Path, *, owner_id: str, max_candidates: int = 80
) -> dict[str, Any]:
    with _connect_ro(source) as con:
        candidates = [
            *_scan_shared_facts(con, owner_id),
            *_scan_life_and_predictions(con, owner_id),
            *_scan_cross_table_semantics(con, owner_id),
        ]
        # Stable order makes a saved plan reproducible and reviewable.
        candidates.sort(
            key=lambda item: (
                {"high": 0, "review": 1, "low": 2}.get(item["severity"], 9),
                item["kind"],
                item["candidate_id"],
            )
        )
        deterministic = [
            item for item in candidates if item["kind"] in _DETERMINISTIC_KINDS
        ]
        ambiguous = [
            item for item in candidates if item["kind"] not in _DETERMINISTIC_KINDS
        ][: max(1, int(max_candidates))]
        candidates = deterministic + ambiguous
        tables = _tables(con)
        inventory = {
            "tables": len(tables),
            "canonical_facts": (
                con.execute(
                    "SELECT COUNT(*) FROM brain2_shared_facts_v19 WHERE person_id=?",
                    (owner_id,),
                ).fetchone()[0]
                if "brain2_shared_facts_v19" in tables
                else 0
            ),
            "deep_vision_observations_reused": (
                con.execute(
                    "SELECT COUNT(*) FROM brainlive_deep_vision_observations_v161 WHERE person_id=?",
                    (owner_id,),
                ).fetchone()[0]
                if "brainlive_deep_vision_observations_v161" in tables
                else 0
            ),
            "vision_calls_planned": 0,
        }
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate["kind"]] = counts.get(candidate["kind"], 0) + 1
    return {"inventory": inventory, "counts_by_kind": counts, "candidates": candidates}


def _estimated_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8")) // 3)


def _batch_candidates(
    candidates: list[dict[str, Any]], size: int
) -> list[list[dict[str, Any]]]:
    size = max(1, min(20, int(size)))
    return [candidates[index:index + size] for index in range(0, len(candidates), size)]


def _daily_committed_eur(con: sqlite3.Connection) -> float:
    if "cloud_cost_ledger_v19" not in _tables(con):
        return 0.0
    day = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    row = con.execute(
        """SELECT COALESCE(SUM(CASE
                 WHEN status IN ('reserved','in_flight','uncertain') THEN reserved_eur
                 ELSE COALESCE(actual_eur,reserved_eur,0) END),0)
           FROM cloud_cost_ledger_v19
           WHERE budget_day=? AND status IN
             ('reserved','in_flight','uncertain','completed','failed_charged')""",
        (day,),
    ).fetchone()
    return float(row[0] or 0.0)


def build_plan(
    source: Path,
    *,
    owner_id: str,
    owner_name: str,
    model: str,
    budget_eur: float,
    batch_size: int,
    max_candidates: int,
) -> dict[str, Any]:
    source_sha = _sha256(source)
    scan = scan_database(source, owner_id=owner_id, max_candidates=max_candidates)
    review_candidates = [
        item for item in scan["candidates"]
        if item["kind"] not in _DETERMINISTIC_KINDS
    ]
    batches = _batch_candidates(review_candidates, batch_size)
    batch_plans = []
    total_input = total_output = 0
    for index, batch in enumerate(batches):
        payload = json.dumps(batch, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_tokens = _estimated_tokens(payload) + 700
        output_tokens = min(2400, 180 + len(batch) * 180)
        total_input += input_tokens
        total_output += output_tokens
        batch_plans.append({
            "batch": index + 1,
            "candidate_ids": [item["candidate_id"] for item in batch],
            "estimated_input_tokens": input_tokens,
            "reserved_output_tokens": output_tokens,
        })
    from mlomega_audio_elite.cloud_budget_v19 import usd_to_eur
    from mlomega_audio_elite.cloud_providers_v19 import DEEPSEEK_TARIFFS_USD_PER_M

    tariff = DEEPSEEK_TARIFFS_USD_PER_M[model]
    # No cache saving is claimed: batches are deliberately small and distinct.
    worst_eur = usd_to_eur(
        (total_input * tariff["cache_miss"] + total_output * tariff["output"]) / 1_000_000
    )
    with _connect_ro(source) as con:
        committed = _daily_committed_eur(con)
    remaining = max(0.0, float(budget_eur) - committed)
    candidate_digest = hashlib.sha256(
        json.dumps(
            scan["candidates"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "version": "owner-quality-shadow-plan-v1",
        "mode": "plan_only_zero_calls",
        "created_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "source_db": str(source),
        "source_sha256": source_sha,
        "source_unchanged": _sha256(source) == source_sha,
        "owner": {"person_id": owner_id, "display_name": owner_name},
        "provider": {"text_backend": "deepseek", "model": model, "vision_backend": "existing"},
        "authority": PROPOSAL_ONLY,
        "scan": scan,
        "candidate_digest": candidate_digest,
        "quote": {
            "calls": len(batches),
            "deterministic_candidates": (
                len(scan["candidates"]) - len(review_candidates)
            ),
            "deepseek_candidates": len(review_candidates),
            "estimated_input_tokens": total_input,
            "reserved_output_tokens": total_output,
            "estimated_cost_eur_min": round(worst_eur, 6),
            "estimated_cost_eur_max": round(worst_eur * 1.15, 6),
            "estimated_wall_seconds_min": len(batches) * 8,
            "estimated_wall_seconds_max": len(batches) * 45,
            "daily_budget_eur": float(budget_eur),
            "already_committed_eur": round(committed, 6),
            "remaining_before_shadow_eur": round(remaining, 6),
            "executable": worst_eur * 1.15 <= remaining + 1e-9,
            "cache_saving_assumed": False,
            "batches": batch_plans,
        },
    }


def _load_env_file() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in {
            "DEEPSEEK_API_KEY", "MLOMEGA_DEEPSEEK_BASE_URL",
            "MLOMEGA_CLOUD_USD_PER_EUR",
        }:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _review_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "candidate_id", "verdict", "reason",
                        "recommended_action", "keep_refs", "merge_refs",
                    ],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["confirmed", "not_issue", "needs_human"],
                        },
                        "reason": {"type": "string"},
                        "recommended_action": {
                            "type": "string",
                            "enum": [
                                "keep", "review", "quarantine", "merge_proposal",
                                "confidence_review", "evidence_repair",
                            ],
                        },
                        "keep_refs": {"type": "array", "items": {"type": "string"}},
                        "merge_refs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    }


def _execute_plan(
    source: Path,
    output: Path,
    plan: dict[str, Any],
    *,
    model: str,
    budget_eur: float,
    timeout: float,
) -> dict[str, Any]:
    if plan.get("version") != "owner-quality-shadow-plan-v1":
        raise ValueError("plan incompatible")
    if str(source) != str(Path(plan["source_db"]).resolve()):
        raise ValueError("--db ne correspond pas au plan")
    source_sha = _sha256(source)
    if source_sha != plan.get("source_sha256"):
        raise RuntimeError("la DB source a changé depuis le devis; refaire --plan-only")
    if model != (plan.get("provider") or {}).get("model"):
        raise ValueError("le modèle doit être identique au devis")
    if float(budget_eur) != float((plan.get("quote") or {}).get("daily_budget_eur")):
        raise ValueError("le budget doit être identique au devis")
    if not bool((plan.get("quote") or {}).get("executable")):
        raise RuntimeError("devis au-dessus du budget quotidien restant")

    clone = output.with_suffix(".db")
    _clone_database(source, clone)
    _load_env_file()
    previous_env = {
        key: os.environ.get(key)
        for key in (
            "MLOMEGA_DB", "MLOMEGA_CLOUD_MODE", "MLOMEGA_LLM_BACKEND",
            "MLOMEGA_DEEPSEEK_MODEL", "MLOMEGA_CLOUD_DAILY_BUDGET_EUR",
            "MLOMEGA_CLOUD_ON_BUDGET", "MLOMEGA_CLOUD_RUN_ID",
        )
    }
    os.environ.update({
        "MLOMEGA_DB": str(clone),
        "MLOMEGA_CLOUD_MODE": "pro",
        "MLOMEGA_LLM_BACKEND": "deepseek",
        "MLOMEGA_DEEPSEEK_MODEL": model,
        "MLOMEGA_CLOUD_DAILY_BUDGET_EUR": str(budget_eur),
        "MLOMEGA_CLOUD_ON_BUDGET": "stop",
        "MLOMEGA_CLOUD_RUN_ID": "owner_quality_shadow_" + source_sha[:12],
    })
    started = time.perf_counter()
    calls: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = [
        {
            "candidate_id": item["candidate_id"],
            "verdict": "confirmed",
            "reason": (
                "Validé par contrat SQL déterministe; aucun appel LLM nécessaire."
            ),
            "recommended_action": (
                "confidence_review"
                if item["kind"] == "confidence_above_evidence_ceiling"
                else "review"
            ),
            "keep_refs": [],
            "merge_refs": [],
            "validator": "deterministic_v1",
        }
        for item in (plan.get("scan") or {}).get("candidates") or []
        if item.get("kind") in _DETERMINISTIC_KINDS
    ]
    try:
        from mlomega_audio_elite.cloud_providers_v19 import cloud_engine_stage
        from mlomega_audio_elite.llm import OllamaJsonClient

        client = OllamaJsonClient(backend="deepseek", model=model)
        candidates_by_id = {
            item["candidate_id"]: item
            for item in (plan.get("scan") or {}).get("candidates") or []
        }
        for batch in (plan.get("quote") or {}).get("batches") or []:
            candidate_ids = list(batch["candidate_ids"])
            payload = [candidates_by_id[cid] for cid in candidate_ids]
            stage = f"owner_quality_shadow:{int(batch['batch']):03d}"
            prompt = json.dumps(
                {
                    "owner": plan.get("owner"),
                    "authority": PROPOSAL_ONLY,
                    "rules": [
                        "Judge only from the supplied evidence.",
                        "Different layers may legitimately project the same fact.",
                        "A temporal evolution is not a contradiction.",
                        "Never recommend a database write; emit a review proposal only.",
                        "keep_refs and merge_refs must be empty or exact table:id strings from the candidate refs.",
                        "Return exactly one finding for every candidate_id.",
                    ],
                    "candidates": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            call_started = time.perf_counter()
            with cloud_engine_stage(stage):
                result = client.generate_json(
                    "You are MLOmega's conservative weekly memory-quality auditor.",
                    prompt,
                    timeout=timeout,
                    max_output_tokens=int(batch["reserved_output_tokens"]),
                    format_schema=_review_schema(),
                )
            elapsed_ms = int((time.perf_counter() - call_started) * 1000)
            returned = result.data.get("findings") if result.ok else []
            returned = returned if isinstance(returned, list) else []
            returned_ids = {
                str(item.get("candidate_id"))
                for item in returned if isinstance(item, dict)
            }
            complete = (
                result.ok
                and returned_ids == set(candidate_ids)
                and all(isinstance(item, dict) for item in returned)
            )
            calls.append({
                "stage": stage,
                "request_digest": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "provider": "deepseek",
                "model": model,
                "candidate_ids": candidate_ids,
                "started_at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
                "latency_ms": elapsed_ms,
                "json_valid": bool(result.ok),
                "contract_complete": complete,
                "prompt_tokens": result.prompt_tokens,
                "output_tokens": result.completion_tokens,
                "finish_reason": result.finish_reason,
                "error_kind": result.error_kind,
            })
            if not complete:
                raise RuntimeError(
                    f"{stage}: réponse incomplète; aucune proposition partielle acceptée"
                )
            findings.extend(returned)
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    ledger: list[dict[str, Any]] = []
    with _connect_ro(clone) as con:
        if "cloud_cost_ledger_v19" in _tables(con):
            ledger = [
                dict(row)
                for row in con.execute(
                    """SELECT call_id,stage_name,status,input_tokens,cache_hit_tokens,
                              cache_miss_tokens,output_tokens,latency_ms,http_status,
                              retry_count,actual_eur,error_code,created_at,updated_at
                       FROM cloud_cost_ledger_v19
                       WHERE run_id=? ORDER BY created_at""",
                    ("owner_quality_shadow_" + source_sha[:12],),
                )
            ]
    actual_cost = sum(float(row.get("actual_eur") or 0.0) for row in ledger)
    return {
        "version": "owner-quality-shadow-report-v1",
        "mode": "execute_proposal_only",
        "source_db": str(source),
        "source_sha256_before": source_sha,
        "source_sha256_after": _sha256(source),
        "source_unchanged": _sha256(source) == source_sha,
        "clone_db": str(clone),
        "plan_digest": hashlib.sha256(
            json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "owner": plan.get("owner"),
        "provider": plan.get("provider"),
        "authority": PROPOSAL_ONLY,
        "summary": {
            "candidates": len((plan.get("scan") or {}).get("candidates") or []),
            "reviewed": len(findings),
            "confirmed": sum(1 for item in findings if item.get("verdict") == "confirmed"),
            "needs_human": sum(1 for item in findings if item.get("verdict") == "needs_human"),
            "not_issue": sum(1 for item in findings if item.get("verdict") == "not_issue"),
            "actual_cost_eur": round(actual_cost, 6),
            "wall_seconds": round(time.perf_counter() - started, 3),
            "writes_to_source": 0,
        },
        "predicted": plan.get("quote"),
        "calls": calls,
        "ledger": ledger,
        "candidates": (plan.get("scan") or {}).get("candidates") or [],
        "findings": findings,
    }


_SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_quality_shadow_runs_v19 (
  shadow_run_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  source_sha256_before TEXT NOT NULL,
  source_sha256_after TEXT,
  plan_digest TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  candidates_count INTEGER NOT NULL,
  decisions_count INTEGER NOT NULL DEFAULT 0,
  canonical_updates_count INTEGER NOT NULL DEFAULT 0,
  report_path TEXT NOT NULL,
  backup_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS owner_quality_shadow_decisions_v19 (
  decision_id TEXT PRIMARY KEY,
  shadow_run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  target_table TEXT NOT NULL,
  target_id TEXT NOT NULL,
  candidate_kind TEXT NOT NULL,
  verdict TEXT NOT NULL,
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(shadow_run_id,candidate_id,target_table,target_id)
);
CREATE INDEX IF NOT EXISTS idx_owner_quality_shadow_target_v19
  ON owner_quality_shadow_decisions_v19(target_table,target_id,action);
"""


def _ref_key(ref: dict[str, Any]) -> str:
    return f"{ref.get('table')}:{ref.get('id')}"


def _validated_actions(
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert model verdicts to a tiny, deterministic operation vocabulary."""

    candidates = {
        str(item["candidate_id"]): item for item in report.get("candidates") or []
    }
    findings = {
        str(item.get("candidate_id")): item
        for item in report.get("findings") or []
        if isinstance(item, dict)
    }
    actions: list[dict[str, Any]] = []
    for candidate_id, candidate in candidates.items():
        finding = findings.get(candidate_id)
        if not finding:
            raise RuntimeError(f"verdict absent pour {candidate_id}")
        verdict = str(finding.get("verdict") or "")
        if verdict not in {"confirmed", "not_issue", "needs_human"}:
            raise RuntimeError(f"verdict inconnu pour {candidate_id}")
        refs = [dict(ref) for ref in candidate.get("refs") or []]
        candidate_keys = {_ref_key(ref) for ref in refs}
        returned_keys = {
            str(value)
            for key in ("keep_refs", "merge_refs")
            for value in (finding.get(key) or [])
        }
        if not returned_keys <= candidate_keys:
            raise RuntimeError(f"{candidate_id}: DeepSeek a cité une cible hors candidat")

        action_by_ref: dict[str, str] = {
            _ref_key(ref): "not_issue" if verdict == "not_issue" else "review_annotation"
            for ref in refs
        }
        kind = str(candidate.get("kind") or "")
        if verdict == "confirmed" and kind == "confidence_above_evidence_ceiling":
            action_by_ref = {_ref_key(refs[0]): "confidence_clamp"}
        elif verdict == "confirmed" and kind == "exact_duplicate_canonical_fact":
            # Exact payload only: keep the oldest/stable lexical id and suppress
            # duplicate presentation.  Canonical rows are not deleted because
            # engine capability provenance may legitimately reference each one.
            keep = min(candidate_keys)
            requested_keep = {
                str(value) for value in (finding.get("keep_refs") or [])
                if str(value) in candidate_keys
            }
            if len(requested_keep) == 1:
                keep = next(iter(requested_keep))
            action_by_ref = {
                key: "keep" if key == keep else "suppress_duplicate"
                for key in candidate_keys
            }
        elif verdict == "confirmed" and kind == "schema_filler":
            action_by_ref = {key: "suppress_filler" for key in candidate_keys}
        for ref in refs:
            actions.append({
                "candidate_id": candidate_id,
                "candidate_kind": kind,
                "target_table": str(ref.get("table") or ""),
                "target_id": str(ref.get("id") or ""),
                "verdict": verdict,
                "action": action_by_ref[_ref_key(ref)],
                "reason": str(finding.get("reason") or ""),
                "evidence": candidate.get("evidence"),
            })
    return actions


def _apply_validated_report(
    source: Path,
    output: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Apply only code-defined safe actions after a backup and clone validation."""

    if not bool(report.get("source_unchanged")):
        raise RuntimeError("source modifiée pendant l'audit; application refusée")
    source_sha = _sha256(source)
    if source_sha != report.get("source_sha256_before"):
        raise RuntimeError("source modifiée depuis l'audit; application refusée")
    actions = _validated_actions(report)
    stamp = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.stem}.pre-owner-shadow-{stamp}{source.suffix}")
    if backup.exists():
        raise FileExistsError(backup)
    # SQLite backup includes committed WAL pages; a plain file copy could miss
    # them even on an otherwise quiet Sunday/day-off run.
    _clone_database(source, backup)
    with _connect_ro(backup) as backup_check:
        backup_ok = str(backup_check.execute("PRAGMA quick_check").fetchone()[0])
    if backup_ok.lower() != "ok":
        backup.unlink(missing_ok=True)
        raise RuntimeError("la sauvegarde SQLite est invalide; application refusée")

    plan_digest = str(report.get("plan_digest") or "")
    run_id = "oqshadow_" + hashlib.sha256(
        (source_sha + plan_digest + stamp).encode("utf-8")
    ).hexdigest()[:20]
    now = datetime.now(ZoneInfo("Europe/Paris")).isoformat()
    canonical_updates = 0
    try:
        con = sqlite3.connect(source)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(_SHADOW_SCHEMA)
        con.commit()
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """INSERT INTO owner_quality_shadow_runs_v19(
                 shadow_run_id,person_id,source_sha256_before,plan_digest,model,
                 status,candidates_count,report_path,backup_path,created_at)
               VALUES(?,?,?,?,?,'applying',?,?,?,?)""",
            (
                run_id,
                str((report.get("owner") or {}).get("person_id") or "me"),
                source_sha,
                plan_digest,
                str((report.get("provider") or {}).get("model")
                    or os.environ.get("MLOMEGA_DEEPSEEK_MODEL")
                    or "deepseek-v4-pro"),
                len(report.get("candidates") or []),
                str(output),
                str(backup),
                now,
            ),
        )
        for action in actions:
            applied = 0
            if (
                action["action"] == "confidence_clamp"
                and action["target_table"] == "brain2_shared_facts_v19"
            ):
                row = con.execute(
                    """SELECT confidence,confidence_ceiling
                       FROM brain2_shared_facts_v19 WHERE fact_id=?""",
                    (action["target_id"],),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"fait disparu: {action['target_id']}")
                confidence = float(row["confidence"] or 0.0)
                ceiling = float(row["confidence_ceiling"] or 0.0)
                if ceiling <= 0 or confidence <= ceiling:
                    raise RuntimeError(
                        f"précondition confidence_clamp invalide: {action['target_id']}"
                    )
                if "updated_at" in _columns(con, "brain2_shared_facts_v19"):
                    con.execute(
                        """UPDATE brain2_shared_facts_v19
                           SET confidence=confidence_ceiling,updated_at=?
                           WHERE fact_id=?""",
                        (now, action["target_id"]),
                    )
                else:
                    con.execute(
                        """UPDATE brain2_shared_facts_v19
                           SET confidence=confidence_ceiling WHERE fact_id=?""",
                        (action["target_id"],),
                    )
                canonical_updates += 1
                applied = 1
            decision_id = "oqdecision_" + hashlib.sha256(
                (
                    run_id + action["candidate_id"] + action["target_table"]
                    + action["target_id"]
                ).encode("utf-8")
            ).hexdigest()[:20]
            con.execute(
                """INSERT INTO owner_quality_shadow_decisions_v19(
                     decision_id,shadow_run_id,candidate_id,target_table,target_id,
                     candidate_kind,verdict,action,reason,evidence_json,applied,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id, run_id, action["candidate_id"],
                    action["target_table"], action["target_id"],
                    action["candidate_kind"], action["verdict"], action["action"],
                    action["reason"],
                    json.dumps(action.get("evidence"), ensure_ascii=False, sort_keys=True),
                    applied, now,
                ),
            )
        foreign_key_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"foreign_key_check rouge: {foreign_key_errors[:3]}")
        quick = con.execute("PRAGMA quick_check").fetchone()
        if not quick or str(quick[0]).lower() != "ok":
            raise RuntimeError(f"quick_check rouge: {quick}")
        con.execute(
            """UPDATE owner_quality_shadow_runs_v19
               SET status='completed',decisions_count=?,
                   canonical_updates_count=?,completed_at=?
               WHERE shadow_run_id=?""",
            (len(actions), canonical_updates, now, run_id),
        )
        con.commit()
        con.close()
    except Exception:
        try:
            con.rollback()
            con.close()
        except Exception:
            pass
        shutil.copy2(backup, source)
        if _sha256(source) != source_sha:
            raise RuntimeError("rollback source impossible; restaure la sauvegarde") from None
        raise

    after_sha = _sha256(source)
    with _connect_ro(source) as check:
        stored = check.execute(
            """SELECT status,decisions_count,canonical_updates_count
               FROM owner_quality_shadow_runs_v19 WHERE shadow_run_id=?""",
            (run_id,),
        ).fetchone()
        quick = str(check.execute("PRAGMA quick_check").fetchone()[0])
    return {
        "enabled": True,
        "policy": "deepseek_decides_code_validates_bounded_actions",
        "shadow_run_id": run_id,
        "backup_db": str(backup),
        "source_sha256_before": source_sha,
        "source_sha256_after": after_sha,
        "decisions_persisted": int(stored["decisions_count"]),
        "canonical_updates": int(stored["canonical_updates_count"]),
        "presentation_overlays": sum(
            1 for action in actions
            if action["action"] in {"suppress_duplicate", "suppress_filler"}
        ),
        "quick_check": quick,
        "rollback_available": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit hebdomadaire owner/qualité, manuel et proposal-only."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--db", required=True)
    parser.add_argument("--owner-id", default="me")
    parser.add_argument("--owner-name", default="William")
    parser.add_argument("--text-backend", choices=["deepseek"], default="deepseek")
    parser.add_argument("--deepseek-model", default="deepseek-v4-pro")
    parser.add_argument("--vision-backend", choices=["existing"], default="existing")
    parser.add_argument("--budget-eur", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--plan", help="Rapport --plan-only exact, obligatoire avec --execute")
    parser.add_argument(
        "--apply-safe",
        action="store_true",
        help="Après décision DeepSeek, applique automatiquement les seules actions codées et validées.",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.deepseek_model != "deepseek-v4-pro":
        raise SystemExit("ce gate qualité est validé uniquement avec deepseek-v4-pro")
    if not 0 < args.budget_eur <= 1.0:
        raise SystemExit("--budget-eur doit rester dans ]0,1.00] pour le shadow")
    source = Path(args.db).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.plan_only:
        if output.exists():
            raise SystemExit(f"--out existe déjà: {output}")
        plan = build_plan(
            source,
            owner_id=args.owner_id,
            owner_name=args.owner_name,
            model=args.deepseek_model,
            budget_eur=args.budget_eur,
            batch_size=args.batch_size,
            max_candidates=args.max_candidates,
        )
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "mode": plan["mode"],
            "out": str(output),
            "candidates": len(plan["scan"]["candidates"]),
            "calls": plan["quote"]["calls"],
            "cost_max_eur": plan["quote"]["estimated_cost_eur_max"],
            "executable": plan["quote"]["executable"],
            "source_unchanged": plan["source_unchanged"],
        }, ensure_ascii=False))
        return 0

    if not args.plan:
        raise SystemExit("--execute exige --plan <rapport-plan.json>")
    if output.exists() or output.with_suffix(".db").exists():
        raise SystemExit("--out ou son clone existe déjà; utilise un nouveau stamp")
    saved_plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    report = _execute_plan(
        source,
        output,
        saved_plan,
        model=args.deepseek_model,
        budget_eur=args.budget_eur,
        timeout=args.timeout,
    )
    if args.apply_safe:
        report["application"] = _apply_validated_report(source, output, report)
        report["source_sha256_after"] = _sha256(source)
        report["source_unchanged"] = False
        report["summary"]["canonical_updates"] = report["application"]["canonical_updates"]
        report["summary"]["presentation_overlays"] = report["application"]["presentation_overlays"]
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "mode": report["mode"],
        "out": str(output),
        "clone": report["clone_db"],
        "source_unchanged": report["source_unchanged"],
        **report["summary"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
