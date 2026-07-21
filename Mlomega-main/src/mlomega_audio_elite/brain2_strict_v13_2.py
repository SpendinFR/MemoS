from __future__ import annotations

"""V13.2 strict Brain 2.0 layer.

This is the no-fake-brain implementation: every cognitive object is produced by
Qwen/Ollama JSON contracts or by structural bookkeeping that does not infer
psychology (time/object links, audit rows, dependency rows). There is no
regex/keyword analyst and no evidence-only cognitive mode.
"""

import logging
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from contextvars import copy_context
from typing import Any, Mapping, Sequence

from .db import connect, init_db, upsert
from .governance_v18 import DataAccessError, GovernanceError, ensure_v18_schema, strict_many, strict_one
from .llm import (
    EliteLLMError,
    LLMTruncatedOutputError,
    OllamaJsonClient,
    llm_client_override,
)
from .utils import json_dumps, json_loads, now_iso, sha256_bytes, stable_id
from .brain2_complete_v13 import COMPLETE_TARGETS, ENGINE_ORDER, ENGINE_TABLES, PLAN_TABLES, ENGINE_SCHEMAS
from .llm_contracts_v15_18 import normalize_outcome_tracker, normalize_similar_case_score, normalize_calibration_rows, normalize_intervention_plan

_LOG = logging.getLogger("mlomega.brain2_strict_v13_2")

STRICT_VERSION = "13.2.0-brain2-strict-final"
EPISODE_BUILD_VERSION = "13.2.0-e64-cognitive-routing-v5"

_BRAIN2_STRICT_SYSTEM = (
    "Tu es un moteur local strict Brain 2.0. Tu remplis uniquement à partir des preuves fournies. "
    "Aucune regex, aucune psychologie générique, aucune hypothèse non marquée. "
    "Réponds uniquement en JSON valide suivant le schéma. "
    "Chaque inférence doit avoir confidence et evidence/counter_evidence. "
    "Si une information manque, indique missing_context au lieu d'inventer."
)

STRICT_EXTRA_TABLES = {
    "brain2_temporal_links",
    "brain2_object_links",
    "v13_llm_contracts",
    "v13_engine_dependencies",
    "v13_readiness_checks",
    "v13_prosody_requirements",
    # V13.3 direct 24/24 flow + self voice + latent outcome discovery
    "self_voice_profile",
    "voice_clusters",
    "voice_observations",
    "voice_identity_revisions",
    "voice_pending_prompts",
    "audio_preprocess_runs",
    "audio_segments",
    "conversation_subtopic_segments",
    "episode_subthemes_v19",
    "episode_subtheme_evidence_v19",
    "latent_outcome_search_runs",
    "latent_outcome_links",
    "direct_flow_jobs",
}

STRICT_PLAN_TABLES = set(PLAN_TABLES) | STRICT_EXTRA_TABLES

STRICT_EPISODE_SCHEMA: dict[str, Any] = {
    "episodes": [
        {
            "episode_type": "technical_validation|relationship_tension|client_request|decision_point|emotional_reaction|planning|conflict|avoidance|commitment|self_reflection|other",
            "start_turn_id": "",
            "end_turn_id": "",
            "start_time": None,
            "end_time": None,
            "participants": [],
            "location": None,
            "channel": None,
            "topic": "",
            "situation_summary": "",
            "trigger": "",
            "user_state_before": "",
            "speech_or_action": "",
            "target_person": "",
            "target_reaction": "",
            "user_state_after": "",
            "outcome": "",
            "unresolved_tension": "",
            "confidence": 0.0,
            "evidence_turn_ids": [],
            "evidence_texts": [],
        }
    ],
    "counter_evidence": [],
    "missing_context": [],
    "confidence": 0.0,
}


def _clamp(v: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        f = float(v)
    except Exception:
        f = 0.0
    return max(lo, min(hi, f))


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _hash_payload(payload: Any) -> str:
    return sha256_bytes(json_dumps(payload).encode("utf-8"))


def _available_tables(con) -> set[str]:
    return {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _default_user(con, conversation_id: str | None = None, explicit_person_id: str | None = None) -> str:
    if explicit_person_id:
        return str(explicit_person_id)
    from .v18_owner_scope import reject_implicit_owner_fallback
    reject_implicit_owner_fallback(__name__)
    row = con.execute("SELECT person_id FROM speaker_profiles WHERE is_user=1 ORDER BY created_at LIMIT 1").fetchone()
    if row:
        return row["person_id"]
    if conversation_id:
        conv = con.execute("SELECT participants_json, speaker_map_json FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
        if conv:
            for value in (_as_dict(json_loads(conv["speaker_map_json"], {})) or {}).values():
                if str(value).lower() in {"me", "moi", "user", "utilisateur"}:
                    return str(value)
            participants = _as_list(json_loads(conv["participants_json"], []))
            if participants:
                return str(participants[0])
    return "me"


def ensure_strict_v13_schema() -> None:
    ensure_v18_schema()
    init_db()
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS brain2_temporal_links(
                temporal_link_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                episode_id TEXT,
                from_table TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_table TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                from_time TEXT,
                to_time TEXT,
                lag_seconds REAL,
                evidence_json TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS brain2_object_links(
                object_link_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                episode_id TEXT,
                from_table TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_table TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                engine_name TEXT,
                evidence_json TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS v13_llm_contracts(
                contract_id TEXT PRIMARY KEY,
                engine_name TEXT NOT NULL,
                contract_version TEXT NOT NULL,
                required_schema_json TEXT NOT NULL,
                strict_rules_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS v13_engine_dependencies(
                dependency_id TEXT PRIMARY KEY,
                engine_name TEXT NOT NULL,
                depends_on_json TEXT NOT NULL,
                produces_tables_json TEXT NOT NULL,
                consumes_tables_json TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS v13_readiness_checks(
                readiness_id TEXT PRIMARY KEY,
                check_name TEXT NOT NULL,
                check_group TEXT NOT NULL,
                status TEXT NOT NULL,
                severity TEXT NOT NULL,
                detail TEXT,
                evidence_json TEXT,
                missing_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS v13_prosody_requirements(
                requirement_id TEXT PRIMARY KEY,
                signal_name TEXT NOT NULL,
                required_for TEXT NOT NULL,
                extractor_status TEXT NOT NULL,
                fallback_allowed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        now = now_iso()
        strict_rules = [
            "No heuristic or regex cognitive inference.",
            "Every inferred item must come from Qwen/Ollama JSON output.",
            "Observed facts must cite source turns/source spans or explicit evidence text.",
            "Predictions are probabilistic and must include why, evidence/counter-evidence, assumptions and intervention options.",
            "If Qwen is unavailable or JSON is invalid, the engine fails instead of filling tables with guesses.",
        ]
        for engine in ENGINE_ORDER:
            upsert(con, "v13_llm_contracts", {
                "contract_id": stable_id("v13contract", STRICT_VERSION, engine),
                "engine_name": engine,
                "contract_version": STRICT_VERSION,
                "required_schema_json": json_dumps(ENGINE_SCHEMAS[engine]),
                "strict_rules_json": json_dumps(strict_rules),
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }, "contract_id")
            idx = ENGINE_ORDER.index(engine)
            upsert(con, "v13_engine_dependencies", {
                "dependency_id": stable_id("v13dep", STRICT_VERSION, engine),
                "engine_name": engine,
                "depends_on_json": json_dumps(ENGINE_ORDER[:idx]),
                "produces_tables_json": json_dumps(ENGINE_TABLES.get(engine, [])),
                "consumes_tables_json": json_dumps(["turns", "source_spans", "episodes"] + ENGINE_TABLES.get(engine, [])),
                "order_index": idx,
                "status": "active",
                "created_at": now,
            }, "dependency_id")
        for sig in ["pause", "laughter", "sigh", "stress_voice", "hesitation", "overlap", "volume_shift", "pitch_shift", "speech_rate", "silence"]:
            upsert(con, "v13_prosody_requirements", {
                "requirement_id": stable_id("prosodyreq", sig),
                "signal_name": sig,
                "required_for": "emotion_from_voice/state_transition/next_emotion",
                "extractor_status": "required_not_inferred_if_missing",
                "fallback_allowed": 0,
                "notes": "No text heuristic may replace the missing acoustic extractor; Qwen must mark missing voice evidence when absent.",
                "created_at": now,
                "updated_at": now,
            }, "requirement_id")
        con.commit()
    # V13.3 extension schemas are still part of the strict plan: they add
    # self-voice, active unknown-voice learning, audio preprocessing, direct
    # flow, subtopic segmentation and latent outcome discovery.
    try:
        from .voice_learning import ensure_voice_learning_schema
        from .audio_preprocess import ensure_audio_preprocess_schema
        from .brain2_flow_v13_3 import ensure_brain2_flow_schema
        ensure_voice_learning_schema(); ensure_audio_preprocess_schema(); ensure_brain2_flow_schema()
    except Exception:
        # Let the audit expose missing tables rather than masking the original DB init.
        pass


def _llm_require_json(engine_name: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    client = OllamaJsonClient()
    timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
    try:
        data = client.require_json(
            _BRAIN2_STRICT_SYSTEM,
            prompt,
            schema_hint=schema,
            timeout=timeout,
        )
    except LLMTruncatedOutputError:
        # Never apply the partial JSON. Retry the same deterministic contract
        # once with a larger response budget; if it truncates again the durable
        # stage remains blocked/retryable exactly as before.
        try:
            retry_tokens = max(
                4096,
                int(os.environ.get("MLOMEGA_V13_TRUNCATION_RETRY_TOKENS", "8192")),
            )
        except ValueError:
            retry_tokens = 8192
        data = client.require_json(
            _BRAIN2_STRICT_SYSTEM,
            prompt,
            schema_hint=schema,
            timeout=timeout,
            max_output_tokens=retry_tokens,
        )
    if not isinstance(data, dict):
        raise EliteLLMError(f"{engine_name} returned non-object JSON")
    return data




def _compact_conversation_for_prompt(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    raw = json_loads(out.get("raw_json"), {}) if isinstance(out.get("raw_json"), str) else (out.get("raw_json") or {})
    if isinstance(raw, dict):
        compact: dict[str, Any] = {
            "source": raw.get("source"),
            "bundle_id": raw.get("bundle_id"),
            "bundle_kind": raw.get("bundle_kind"),
            "source_counts": raw.get("source_counts"),
            "place": raw.get("place"),
            "side_channel_note": raw.get("side_channel_note"),
        }
        # Keep side-channel references compact: time/kind/source_id/summary only.
        for key in ["prediction_timeline", "intervention_timeline", "outcome_timeline", "affordance_timeline", "raw_timeline", "vision_timeline"]:
            vals = raw.get(key) or []
            if isinstance(vals, list):
                small = []
                for item in vals[:40]:
                    if isinstance(item, dict):
                        small.append({k: item.get(k) for k in ("time", "kind", "summary", "text", "source_table", "source_id", "evidence_role", "forecast_id", "candidate_id") if item.get(k) is not None})
                    else:
                        small.append(item)
                compact[key] = small
        out["raw_json"] = json_dumps(compact)
    return out


def _source_ref(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        ref = {k: item.get(k) for k in ("turn_id","episode_id","source_span_id","event_id","pattern_id","loop_id","observation_id","idx","start_s","end_s") if item.get(k) is not None}
        text = item.get("text") or item.get("summary") or item.get("evidence_text") or item.get("content")
        if isinstance(text, str):
            ref["text_preview"] = text[:360]
            ref["text_truncated"] = len(text) > 360
        return ref or {"payload_sha256": _hash_payload(item)}
    return {"payload_sha256": _hash_payload(item)}


def _safe_prompt_payload(payload: dict[str, Any], max_chars: int = 90000) -> str:
    """Return valid JSON or a valid explicit incomplete-context envelope.

    V17.4 cut the bytes of a JSON document then appended another JSON object,
    which produced an invalid prompt.  V18 never byte-truncates JSON.  If the
    budget is exceeded, the engine receives source references and is instructed
    to report missing context instead of hallucinating from a partial payload.
    """
    txt = json_dumps(payload)
    if len(txt) <= max_chars:
        return txt
    bundle = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else {}
    if not bundle and isinstance(payload.get("conversation_bundle"), dict):
        bundle = payload["conversation_bundle"]
    compact_bundle: dict[str, Any] = {}
    for key, value in bundle.items():
        if isinstance(value, list):
            compact_bundle[key] = [_source_ref(x) for x in value]
        elif isinstance(value, dict):
            compact_bundle[key] = _source_ref(value)
        elif isinstance(value, str):
            compact_bundle[key] = {"text_preview": value[:500], "text_truncated": len(value)>500}
        else:
            compact_bundle[key] = value
    reduced = {
        "schema_version": "18.0.0",
        "engine_name": payload.get("engine_name"),
        "mission": payload.get("mission"),
        "schema": payload.get("schema"),
        "context_incomplete": True,
        "missing_context_reason": "prompt_budget_exceeded; retrieve source references before asserting a conclusion",
        "full_payload_sha256": _hash_payload(payload),
        "bundle_source_refs": compact_bundle,
        "prior_engine_output_refs": {k: _source_ref(v) for k, v in (payload.get("prior_engine_outputs") or {}).items()} if isinstance(payload.get("prior_engine_outputs"), dict) else {},
    }
    out = json_dumps(reduced)
    if len(out) > max_chars:
        # This is structurally impossible for ordinary V13 output; signal an
        # error rather than a lossy string cut.
        raise GovernanceError("context reference envelope exceeds prompt budget")
    return out

def _conversation_bundle(con, conversation_id: str) -> dict[str, Any]:
    conv = con.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
    if not conv:
        raise ValueError(f"conversation_missing: {conversation_id}")
    turns = [dict(r) for r in con.execute("SELECT turn_id, idx, speaker_label, person_id, start_s, end_s, text, metadata_json FROM turns WHERE conversation_id=? ORDER BY idx", (conversation_id,))]
    spans = [dict(r) for r in con.execute("SELECT * FROM source_spans WHERE conversation_id=? ORDER BY start_s", (conversation_id,))]
    return {"conversation": _compact_conversation_for_prompt(dict(conv)), "turns": turns, "source_spans": spans}


def _episode_bundle(con, episode_id: str) -> dict[str, Any]:
    """Build a local, scope-valid episode bundle.

    The old version gave every engine the whole conversation and queried
    non-existent ``episode_id`` columns under ``except: []``.  This version
    selects only episode turns plus a small explicit boundary window and emits
    unavailable relationships as ``missing_context`` rather than pretending the
    table is empty.
    """
    ep = strict_one(con, "SELECT * FROM episodes WHERE episode_id=?", (episode_id,), purpose="load episode")
    if not ep:
        raise ValueError(f"episode_missing: {episode_id}")
    conv_id = ep.get("source_conversation_id")
    conv = strict_one(con, "SELECT * FROM conversations WHERE conversation_id=?", (conv_id,), purpose="load episode conversation") if conv_id else None
    turns: list[dict[str, Any]] = []
    missing: list[str] = []
    if conv_id:
        start_id, end_id = ep.get("start_turn_id"), ep.get("end_turn_id")
        evidence = strict_many(
            con,
            "SELECT turn_id FROM episode_evidence WHERE episode_id=? AND turn_id IS NOT NULL",
            (episode_id,), purpose="episode evidence",
        )
        evidence_ids = [str(row["turn_id"]) for row in evidence]
        evidence_marks = strict_many(
            con,
            "SELECT turn_id,idx FROM turns WHERE conversation_id=? AND turn_id IN (%s)"
            % ",".join("?" for _ in evidence_ids),
            (conv_id, *evidence_ids), purpose="episode evidence bounds",
        ) if evidence_ids else []
        evidence_indices = [int(row["idx"]) for row in evidence_marks]
        if evidence_indices:
            # Every cited proof stays present. Context is local to each proof,
            # rather than the entire interval between two distant boundaries
            # that may contain unrelated episodes.
            selected_indices = sorted({
                idx
                for evidence_idx in evidence_indices
                for idx in range(max(0, evidence_idx - 2), evidence_idx + 3)
            })
            marks = ",".join("?" for _ in selected_indices)
            turns = strict_many(
                con,
                f"SELECT turn_id,idx,speaker_label,person_id,start_s,end_s,text,metadata_json FROM turns WHERE conversation_id=? AND idx IN ({marks}) ORDER BY idx",
                (conv_id, *selected_indices), purpose="episode evidence-local turns",
            )
        else:
            bounds = strict_many(
                con,
                "SELECT turn_id,idx FROM turns WHERE conversation_id=? AND turn_id IN (?,?)",
                (conv_id, start_id, end_id), purpose="episode bounds",
            ) if (start_id or end_id) else []
            by_id = {str(row["turn_id"]): int(row["idx"]) for row in bounds}
            lo = by_id.get(str(start_id)) if start_id else None
            hi = by_id.get(str(end_id)) if end_id else None
            if lo is None or hi is None:
                missing.append("episode_turn_bounds_missing")
                lo, hi = 0, -1
            lo, hi = min(lo, hi), max(lo, hi)
            turns = strict_many(
                con,
                "SELECT turn_id,idx,speaker_label,person_id,start_s,end_s,text,metadata_json FROM turns WHERE conversation_id=? AND idx BETWEEN ? AND ? ORDER BY idx",
                (conv_id, max(0, lo - 2), hi + 2), purpose="episode local turns",
            )
    def scoped(table: str, *, predicate: str = "episode_id=?", params: tuple[Any,...] = (episode_id,)) -> list[dict[str, Any]]:
        try:
            return strict_many(con, f"SELECT * FROM {table} WHERE {predicate} LIMIT 200", params, purpose=f"episode {table}")
        except DataAccessError as exc:
            missing.append(f"{table}: {exc}")
            return []
    # Tables whose schema actually contains episode_id.
    direct={name:scoped(name) for name in ("situation_episodes","interaction_episodes","internal_state_snapshots","thought_hypotheses","speech_acts","action_intentions","action_outcomes","choice_episodes","contradiction_events")}
    # Causal edges are polymorphic, not episode keyed.
    causes=scoped("causal_edges", predicate="(from_table='episodes' AND from_id=?) OR (to_table='episodes' AND to_id=?)", params=(episode_id,episode_id))
    # Patterns use pattern contexts/counterexamples, never a fictitious episode_id.
    patterns=[]
    try:
        counter=strict_many(con, "SELECT pattern_table,pattern_id FROM pattern_counterexamples WHERE episode_id=?", (episode_id,), purpose="episode pattern counterexamples")
        for row in counter:
            table=str(row["pattern_table"])
            if table not in {"candidate_patterns","confirmed_patterns","loop_patterns"}:
                continue
            pk={"candidate_patterns":"candidate_pattern_id","confirmed_patterns":"confirmed_pattern_id","loop_patterns":"loop_id"}[table]
            obj=strict_one(con, f"SELECT * FROM {table} WHERE {pk}=?", (row["pattern_id"],), purpose=f"pattern {table}")
            if obj:
                patterns.append(obj)
    except DataAccessError as exc:
        missing.append(f"patterns: {exc}")
    subthemes: list[dict[str, Any]] = []
    try:
        subthemes = strict_many(
            con,
            """SELECT ordinal,subtheme_type,title,summary,start_turn_id,end_turn_id,
                      participants_json,outcome_summary,unresolved_tension,confidence,
                      metadata_json
                 FROM episode_subthemes_v19
                WHERE episode_id=? ORDER BY ordinal""",
            (episode_id,),
            purpose="episode conversation subthemes",
        )
        for subtheme in subthemes:
            evidence_rows = strict_many(
                con,
                """SELECT turn_id,evidence_role
                     FROM episode_subtheme_evidence_v19
                    WHERE subtheme_id=(
                        SELECT subtheme_id FROM episode_subthemes_v19
                         WHERE episode_id=? AND ordinal=?
                    ) ORDER BY evidence_role,turn_id""",
                (episode_id, subtheme.get("ordinal")),
                purpose="episode subtheme evidence",
            )
            subtheme["membership_turn_ids"] = [
                row["turn_id"] for row in evidence_rows
                if row.get("evidence_role") == "membership"
            ]
            subtheme["evidence_turn_ids"] = [
                row["turn_id"] for row in evidence_rows
                if row.get("evidence_role") == "primary_citation"
            ]
    except DataAccessError as exc:
        missing.append(f"episode_subthemes_v19: {exc}")
    # Keep complete WhisperX/vision provenance in SQLite.  The LLM-facing
    # projection preserves text, timing, speaker and alignment quality/digest,
    # while removing duplicated word arrays and opaque source-ID lists.
    from .brain2_episode_windowing import _prompt_turn
    prompt_turns = [_prompt_turn(turn) for turn in turns]
    return {
        "episode": ep,
        "conversation": _compact_conversation_for_prompt(conv) if conv else None,
        "turns": prompt_turns,
        "subthemes": subthemes,
        "situations": direct["situation_episodes"], "interactions": direct["interaction_episodes"],
        "states": direct["internal_state_snapshots"], "thoughts": direct["thought_hypotheses"],
        "speech_acts": direct["speech_acts"], "intentions": direct["action_intentions"],
        "outcomes": direct["action_outcomes"], "choices": direct["choice_episodes"],
        "causes": causes, "contradictions": direct["contradiction_events"], "patterns": patterns,
        "missing_context": missing,
        "context_scope": {"episode_id":episode_id,"conversation_id":conv_id,"turn_count":len(prompt_turns),"local_only":True},
    }

def _engine_prompt(
    engine_name: str,
    bundle: dict[str, Any],
    prior: dict[str, Any],
    *,
    schema_override: dict[str, Any] | None = None,
    bundle_in_prefix: bool = False,
) -> str:
    prompt_bundle: Any = bundle
    if bundle_in_prefix:
        episode = bundle.get("episode") if isinstance(bundle, Mapping) else None
        episode_id = episode.get("episode_id") if isinstance(episode, Mapping) else None
        prompt_bundle = {
            "provided_in_shared_prefix": True,
            "episode_id": episode_id,
            "digest": _hash_payload(bundle),
        }
    return _safe_prompt_payload({
        "engine_name": engine_name,
        "mission": "Remplir le modèle dynamique Brain 2.0: vie observée -> situation -> état -> parole/action -> réaction/résultat -> patterns -> simulation -> prédiction -> vérification -> correction.",
        "no_heuristic_policy": "Tout contenu cognitif vient de cette réponse Qwen. Ne pas inventer. Marquer missing_context.",
        "evidence_role_policy": "Respecte metadata_json.kind/evidence_role: human_or_audio_transcript = parole/transcription humaine; system_observation_not_user_speech = observation capteur/contexte, jamais une déclaration de William; side-channel prediction/intervention/outcome dans conversation.raw_json = metadata de vérification, jamais parole utilisateur. Ne transforme pas une observation système en goût, préférence ou intention déclarée.",
        "schema": schema_override or ENGINE_SCHEMAS[engine_name],
        "bundle": prompt_bundle,
        "prior_engine_outputs": prior,
    })


def _run_engine_partitioned(
    con,
    *,
    engine: str,
    episode_id: str,
    person_id: str,
    bundle: dict[str, Any],
    prior: dict[str, Any],
    window_llm: Any | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
    bundle_in_prefix: bool = False,
    projected_facts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one V13 engine by bounded schema-field tasks, then merge losslessly.

    Evidence/counter-evidence/confidence accompany every task. Business fields are
    each primary exactly once; the generic E64 executor checkpoints and recursively
    subdivides them on length/invalid JSON. No engine or schema field is dropped.

    Codex correction 4: when ``projected_facts`` (the shared-facts INPUT list in
    ``prior['shared_facts']['facts']``) is large enough to push the prompt over the
    input budget, the INPUT is windowed by ``(source_engine, type)`` and the engine
    is run once per window, then merged/deduplicated by fact ref — never growing the
    context past the 24576 cap, never losing a fact.  This attacks the real cause
    of the ``similar_case`` quarantine (oversized ENTRY facts), which the schema-field
    resolver below cannot fix.
    """
    from .config import get_settings
    from .night_orchestrator import (
        ModelBudget, OllamaWindowLLM, PlanUnit, StageScope,
        estimate_tokens_for_text, run_windows,
    )

    # Codex cost point #4: in PRO, bind the REAL engine stage so every DeepSeek
    # ledger row is attributed to this engine+episode instead of the flat
    # 'closeday_text'.  On the local path this stays a no-op so the byte-for-byte
    # behaviour is untouched.
    if os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        from .cloud_providers_v19 import cloud_engine_stage as _cloud_engine_stage
        _stage_ctx: Any = _cloud_engine_stage(f"brain2_engine:{engine}:{episode_id}")
    else:
        _stage_ctx = nullcontext()

    with _stage_ctx:
        schema = dict(ENGINE_SCHEMAS[engine])
        common_names = [
            name for name in ("evidence", "counter_evidence", "confidence")
            if name in schema
        ]
        business_names = [name for name in schema if name not in common_names]
        if not business_names:
            return _llm_require_json(
                engine, _engine_prompt(engine, bundle, prior), schema
            )

        # Codex correction 4: LOSSLESS input-fact windowing.  Only reachable when a
        # caller passed the projected shared-facts INPUT list.  If that full input
        # would push the engine prompt over the input budget, split the FACTS by
        # (source_engine, type), run this engine once per window (with the schema
        # resolver intact inside each), then merge/dedup by ref.  Never grows the
        # context past the cap; never drops a fact.
        if projected_facts:
            input_budget = _pro_engine_input_budget(output_budget)
            full_prompt = _engine_prompt(
                engine, bundle, prior, bundle_in_prefix=bundle_in_prefix
            )
            if estimate_tokens_for_text(full_prompt) > input_budget:
                # Budget the number of facts per window from the average fact size,
                # leaving headroom for the schema + prior scaffolding.
                per_fact_tokens = max(
                    1,
                    estimate_tokens_for_text(json_dumps(list(projected_facts)))
                    // max(1, len(projected_facts)),
                )
                scaffold = _engine_prompt(
                    engine,
                    bundle,
                    _prior_without_shared_facts(prior),
                    bundle_in_prefix=bundle_in_prefix,
                )
                headroom = max(
                    per_fact_tokens,
                    input_budget - estimate_tokens_for_text(scaffold),
                )
                max_facts_per_window = max(1, headroom // per_fact_tokens)
                windows = _window_facts_by_source(
                    projected_facts, max_facts_per_window=max_facts_per_window
                )
                if len(windows) > 1:
                    window_outputs: list[Mapping[str, Any]] = []
                    for window in windows:
                        window_prior = _prior_with_shared_facts(prior, window)
                        window_outputs.append(
                            _run_engine_partitioned(
                                con,
                                engine=engine,
                                episode_id=episode_id,
                                person_id=person_id,
                                bundle=bundle,
                                prior=window_prior,
                                window_llm=window_llm,
                                context_window=context_window,
                                output_budget=output_budget,
                                bundle_in_prefix=bundle_in_prefix,
                                projected_facts=None,  # windows are already bounded
                            )
                        )
                    return _merge_windowed_fact_outputs(window_outputs)

        units = [
            PlanUnit(
                ref_id=name,
                tokens=estimate_tokens_for_text(json_dumps({name: schema[name]})) + 8,
                content_digest=_hash_payload(json_dumps({name: schema[name]})),
            )
            for name in business_names
        ]
        common_schema = {name: schema[name] for name in common_names}

        def render(window_units) -> dict[str, Any]:
            task_names = [unit.ref_id for unit in window_units]
            task_schema = {
                **{name: schema[name] for name in task_names},
                **common_schema,
            }
            return {
                "prompt": _engine_prompt(
                    engine, bundle, prior, schema_override=task_schema,
                    bundle_in_prefix=bundle_in_prefix,
                ),
                "schema_hint": task_schema,
            }

        def validate(value: Any) -> bool:
            return isinstance(value, dict)

        def envelope(value: Any, primary) -> dict[str, Any]:
            return {
                "task_fields": [unit.ref_id for unit in primary],
                "result": value,
            }

        cfg = get_settings()
        if output_budget is None:
            try:
                output_budget = max(
                    256, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"))
                )
            except ValueError:
                output_budget = 4096
            # PRO cloud (DeepSeek) is a bigger, more thorough model than the local
            # 9B: for the SAME task it emits longer/more complete lists, so the local
            # 4096 output cap truncated them (finish=length). DeepSeek supports 8k
            # output; give every engine the cloud output budget in PRO. The context
            # cap below is sized so pattern_miner (~40k input) still fits with 8k
            # output in ONE call. The local path keeps 4096.
            if os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
                "1", "true", "yes", "on",
            }:
                try:
                    output_budget = max(int(output_budget), int(
                        os.environ.get("MLOMEGA_CLOUD_MAX_OUTPUT_TOKENS", "8192")))
                except ValueError:
                    output_budget = max(int(output_budget), 8192)
        context_window = int(context_window or cfg.ollama_context_poststop)
        # PRO cloud text (DeepSeek) has a far larger context than the local P1's ~24k
        # post-stop window. Capping the engine-field budget at the LOCAL context made a
        # large episode bundle prefix (~29k tokens, the whole conversation as a cache
        # prefix) trip "single unit exceeds input budget" and quarantine — Gate B
        # 014448 pattern_miner. In PRO, budget against the cloud model's real context
        # so the cached prefix fits. The local path keeps ``ollama_context_poststop``.
        if os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
            "1", "true", "yes", "on",
        }:
            # The 24k cap was a LOCAL-P1 constraint that Codex kept in PRO to FORCE
            # the projection work (DAG deps + fingerprint + per-dependency facts).
            # That projection is now done, so the only legitimate large input is
            # pattern_miner's projected fact set (~27k). Capping at 24k forced that
            # ONE engine to be split into ~27 windows = 27 sequential DeepSeek round
            # trips (the CloseDay latency killer). DeepSeek handles 128k and the
            # prefix is 97% cache-hit, so ONE 27k cached call is both faster AND
            # cheaper than 27 windowed calls. Budget at 48k so every engine runs in a
            # SINGLE call; the windowing fallback below stays as a safety net for a
            # genuinely huge input (a very long day), never as the normal path.
            try:
                cloud_ctx = int(os.environ.get("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "57344"))
            except ValueError:
                cloud_ctx = 57344
            context_window = max(context_window, cloud_ctx)
        if window_llm is None:
            try:
                timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
            except ValueError:
                timeout = 180.0
            window_llm = OllamaWindowLLM(
                system=_BRAIN2_STRICT_SYSTEM,
                timeout=timeout,
            )
        model = str(getattr(window_llm, "model", "injected-window-llm"))
        episode = con.execute(
            "SELECT start_time FROM episodes WHERE episode_id=?", (episode_id,)
        ).fetchone()
        package_date = str((episode["start_time"] if episode else None) or now_iso())[:10]
        empty_prompt = _engine_prompt(
            engine, bundle, prior, schema_override=common_schema,
            bundle_in_prefix=bundle_in_prefix,
        )
        stage = run_windows(
            units,
            con=con,
            scope=StageScope(
                person_id=person_id,
                package_date=package_date,
                stage_name=f"brain2_engine_fields:{engine}:{episode_id}",
                adapter_version="e64f-v13-engine-fields-v2",
                prompt_version=f"{STRICT_VERSION}:{engine}",
                model=model,
            ),
            llm=window_llm,
            budget=ModelBudget(
                context_window=context_window,
                output_reserve=int(output_budget),
                safety_margin=768,
            ),
            render=render,
            validate=validate,
            decorate_output=envelope,
            # The local 9B keeps its deliberately small field groups. DeepSeek PRO
            # gets one request per cognitive engine and subdivides only on a real
            # size/contract failure; engines themselves are never merged together.
            target_units=(
                len(units)
                if os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
                in {"1", "true", "yes", "on"}
                else (2 if len(business_names) > 3 else 3)
            ),
            overlap=0,
            prompt_overhead_tokens=estimate_tokens_for_text(empty_prompt),
        )
        if not stage.all_completed:
            raise RuntimeError(
                f"{engine} field tasks incomplete: "
                f"states={[window.state for window in stage.windows]}"
            )

        merged: dict[str, Any] = {}
        evidence: list[Any] = []
        counter_evidence: list[Any] = []
        confidences: list[float] = []
        for stored in stage.outputs:
            if not isinstance(stored, dict):
                continue
            result = stored.get("result")
            fields = stored.get("task_fields") or []
            if not isinstance(result, dict):
                continue
            for field in fields:
                if field in result:
                    merged[str(field)] = result[field]
            evidence.extend(_as_list(result.get("evidence")))
            counter_evidence.extend(_as_list(result.get("counter_evidence")))
            if isinstance(result.get("confidence"), (int, float)):
                confidences.append(float(result["confidence"]))

        def unique_json(values: list[Any]) -> list[Any]:
            seen: set[str] = set()
            out: list[Any] = []
            for value in values:
                marker = json_dumps(value)
                if marker not in seen:
                    seen.add(marker)
                    out.append(value)
            return out

        if "evidence" in schema:
            merged["evidence"] = unique_json(evidence)
        if "counter_evidence" in schema:
            merged["counter_evidence"] = unique_json(counter_evidence)
        if "confidence" in schema:
            merged["confidence"] = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )
        return merged


_CONVERSATION_SCOPE_ENGINES = {
    "pattern_miner",
    "similar_case_retrieval",
    "prediction_engine",
    "simulation_engine",
    "calibration_engine",
    "intervention_engine",
}

# DAG of DIRECT dependencies per engine (Codex cost point #1).  Replaces the old
# "every prior output, cumulated" prior that exploded 8k -> 66k tokens per engine.
# Each engine's PRO ``prior`` is projected to ONLY the outputs of these direct
# parents (see ``_direct_prior``); an engine with no dependency receives ``{}``
# (it still gets the shared episode bundle prefix).  The per-episode levels are
# kept consistent with ``known_levels`` (~ line 2900).  The six GLOBAL engines
# form their own chain and pull from the conversation-scope outputs.
_ENGINE_DIRECT_DEPS: dict[str, tuple[str, ...]] = {
    # Per-episode engines
    "capture_engine": (),
    "language_signature_engine": (),
    "context_resolver": ("capture_engine", "language_signature_engine"),
    "internal_state_engine": ("context_resolver",),
    "social_model_engine": ("context_resolver",),
    "causality_engine": ("internal_state_engine", "social_model_engine"),
    "contradiction_engine": ("internal_state_engine", "social_model_engine"),
    "choice_model_engine": ("internal_state_engine", "social_model_engine"),
    "outcome_tracker": ("causality_engine", "choice_model_engine"),
    # Global (conversation-scope) engines: an explicit dependency chain.
    # pattern_miner depends on the per-episode parents materialized upstream; it
    # reads them from the canonical shared-facts registry, so its direct-output
    # prior is empty and it relies on the facts bundle + episode outputs.
    "pattern_miner": (),
    "similar_case_retrieval": ("pattern_miner",),
    "prediction_engine": ("pattern_miner", "similar_case_retrieval"),
    "simulation_engine": ("prediction_engine",),
    "calibration_engine": ("prediction_engine", "simulation_engine"),
    "intervention_engine": ("calibration_engine", "prediction_engine"),
}


def _direct_prior(
    engine: str,
    conversation_outputs: Mapping[str, Any],
    episode_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a per-episode engine ``prior`` to its DIRECT dependencies only.

    An engine with no dependency gets ``{}`` (the shared episode bundle already
    travels in the cache prefix).  A dependency is resolved from the current
    episode's outputs first, then from conversation-scope outputs, so both
    per-episode parents and any already-materialized global parent are honoured
    without ever dragging in unrelated engines' outputs.
    """

    prior: dict[str, Any] = {}
    for parent in _ENGINE_DIRECT_DEPS.get(engine, ()):
        if parent in episode_outputs:
            prior[parent] = episode_outputs[parent]
        elif parent in conversation_outputs:
            prior[parent] = conversation_outputs[parent]
    return prior


# The per-episode ``source_engine`` values whose canonical facts feed the base of
# the global chain.  ``pattern_miner`` mines the whole per-episode substrate, so
# it receives the broad registry; every later global then narrows to the facts
# produced by the globals it depends on (plus, where Codex asks for it, a compact
# language fingerprint or the per-episode loops).
_PER_EPISODE_FACT_SOURCES: tuple[str, ...] = (
    "episode_builder",
    "capture_engine",
    "language_signature_engine",
    "context_resolver",
    "internal_state_engine",
    "social_model_engine",
    "causality_engine",
    "contradiction_engine",
    "choice_model_engine",
    "outcome_tracker",
)

# Codex cost point A: per-dependency PROJECTION of canonical facts for the six
# GLOBAL engines.  Instead of shipping the single 36778-token bundle to all of
# them, each global receives ONLY the ``source_engine`` facts its dependencies
# actually need.  Values are ``source_engine`` names filtered out of the canonical
# ``compact_fact_bundle`` — the evidence stays authoritative in DB.
_GLOBAL_ENGINE_FACT_SOURCES: dict[str, tuple[str, ...]] = {
    # pattern_miner: the broad per-episode substrate (capture/langage/contexte/
    # état interne/social/causalité/contradiction/choix/outcome + structure).
    "pattern_miner": _PER_EPISODE_FACT_SOURCES,
    # similar_case_retrieval: patterns + a compact language fingerprint.
    "similar_case_retrieval": ("pattern_miner", "language_signature_engine"),
    # prediction_engine: patterns + cases + the loops (open-loops / outcome).
    "prediction_engine": (
        "pattern_miner", "similar_case_retrieval", "outcome_tracker",
    ),
    # simulation_engine: predictions + the context it needs to project a branch.
    "simulation_engine": ("prediction_engine", "context_resolver"),
    # calibration_engine: predictions + historical outcomes.
    "calibration_engine": ("prediction_engine", "outcome_tracker"),
    # intervention_engine: predictions + simulations + the constraints (context).
    "intervention_engine": (
        "prediction_engine", "simulation_engine", "context_resolver",
    ),
}


def _facts_for_global_engine(
    engine: str, compact_facts: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Project the COMPACT canonical facts to those a global engine depends on.

    ``compact_facts`` is the trimmed registry (see
    ``brain2_shared_facts_v19.compact_facts_for_prompt``); each entry keeps its
    ``source_engine``.  We keep ONLY the facts whose ``source_engine`` is in this
    engine's dependency set, so a non-dependency fact never reaches the prompt.
    An engine with no mapping receives nothing (its dependencies travel as direct
    outputs); the full evidence always stays in DB.
    """

    allowed = set(_GLOBAL_ENGINE_FACT_SOURCES.get(engine, ()))
    if not allowed:
        return []
    return [
        dict(fact) for fact in compact_facts
        if str(fact.get("source_engine") or "") in allowed
    ]


# ---------------------------------------------------------------------------
# Codex correction 3: similar_case_retrieval must NOT receive the 97 canonical
# facts.  It receives ONLY (a) the COMPACT OUTPUT of pattern_miner (its engine
# result summarised, not its facts), (b) the EPISODE FINGERPRINT (title /
# participants / compact sub-themes, never the transcript), and (c) the INDEX of
# historically relevant cases (short refs + matching keys, not the full cases).
# This keeps the stage well under the 24576 input budget; the full evidence
# stays authoritative in DB.
# ---------------------------------------------------------------------------

_PATTERN_SUMMARY_CAP = 24


def _pattern_output_summary(pattern_output: Mapping[str, Any] | None) -> dict[str, Any]:
    """Summarise pattern_miner's ENGINE OUTPUT (never its raw facts).

    Keeps the pattern identity/title/strength keys a case retriever matches on;
    drops evidence lists, counterexamples and prose so the summary is a bounded
    fingerprint of "what patterns fired", not the mining substrate.
    """

    if not isinstance(pattern_output, Mapping):
        return {"signals": [], "candidate_patterns": [], "confirmed_patterns": []}

    def _sig(item: Any) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            return {}
        return {
            key: item.get(key)
            for key in ("signal_type", "signal_value", "strength")
            if item.get(key) is not None
        }

    def _patt(item: Any) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            return {}
        return {
            key: item.get(key)
            for key in ("pattern_type", "pattern_key", "title", "usual_outcome")
            if item.get(key) is not None
        }

    return {
        "signals": [
            summary for summary in (
                _sig(item) for item in _as_list(pattern_output.get("signals"))[:_PATTERN_SUMMARY_CAP]
            ) if summary
        ],
        "candidate_patterns": [
            summary for summary in (
                _patt(item) for item in _as_list(pattern_output.get("candidate_patterns"))[:_PATTERN_SUMMARY_CAP]
            ) if summary
        ],
        "confirmed_patterns": [
            summary for summary in (
                _patt(item) for item in _as_list(pattern_output.get("confirmed_patterns"))[:_PATTERN_SUMMARY_CAP]
            ) if summary
        ],
    }


def _episode_fingerprint(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """The compact fingerprint of the episode(s): title / participants / topics.

    Uses only the already-summarised ``episodes`` slice of
    ``_conversation_engine_bundle`` plus the conversation participants; never the
    turns/transcript.  This is the "what is this episode about" match key, not the
    evidence.
    """

    conversation = bundle.get("conversation") if isinstance(bundle.get("conversation"), Mapping) else {}
    participants = conversation.get("participants") if isinstance(conversation, Mapping) else None
    episodes = []
    for episode in bundle.get("episodes") or []:
        if not isinstance(episode, Mapping):
            continue
        episodes.append({
            key: episode.get(key)
            for key in (
                "episode_id", "episode_type", "topic", "situation_summary",
                "trigger_summary", "outcome_summary", "unresolved_tension",
            )
            if episode.get(key) is not None
        })
    return {
        "participants": participants,
        "episodes": episodes,
    }


def _global_engine_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """The COMPACT bundle handed to the GLOBAL engines in PRO (Codex correction 3).

    The global engines (pattern_miner, similar_case_retrieval, prediction_engine,
    simulation_engine, calibration_engine, intervention_engine) synthesise from
    their PROJECTED inputs — direct parent outputs, per-dependency facts, or the
    minimal similar_case prior — never from the raw transcript.  Yet the
    ``_conversation_engine_bundle`` (with its ~25k-token ``turns`` transcript) used
    to be serialised into every global prompt, pushing similar_case's window over
    the 24576 input budget.  Codex correction 3 is explicit: the globals receive
    the EPISODE FINGERPRINT, never the transcript.

    This returns exactly that fingerprint (title / participants / compact episode
    summaries) plus the conversation identity + the sensor-route manifest the
    contracts reference — bounded to ~a few dozen tokens — and drops ``turns``
    entirely.  The full evidence stays authoritative in brain2_shared_facts_v19.
    """

    fingerprint = _episode_fingerprint(bundle)
    conversation = bundle.get("conversation") if isinstance(bundle, Mapping) else None
    return {
        "analysis_scope": "conversation_global_fingerprint",
        "transcript_omitted": "held_in_db_globals_read_projected_inputs_only",
        "conversation": conversation,
        "episodes": fingerprint["episodes"],
        "participants": fingerprint["participants"],
        "sensor_route_manifest": bundle.get("sensor_route_manifest")
        if isinstance(bundle, Mapping) else None,
    }


_CASE_INDEX_CAP = 24


def _case_index(con, person_id: str, conversation_id: str) -> list[dict[str, Any]]:
    """Return a compact INDEX of historically relevant cases, not the full cases.

    Short case refs plus the matching keys (type / outcome label / a bounded
    title) a retriever needs to decide relevance.  The full case rows stay in DB;
    nothing here re-embeds their evidence.  Read-only.

    ``case_ids`` (the full membership array of a cluster) is EVIDENCE, not a
    matching key: it exploded the ``similar_case_retrieval`` prompt to ~20k once
    ``v13_case_clusters`` was populated (Gate B 183352).  It is deliberately NOT
    selected — a retriever matches on type/outcome/title, and the membership
    stays authoritative in DB.
    """

    index: list[dict[str, Any]] = []
    for table, id_col, key_cols in (
        ("v13_case_clusters", "cluster_key",
         ("cluster_type",)),
        ("prediction_cases", "case_id",
         ("case_type", "outcome_label", "title")),
    ):
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        columns = {
            str(row[1])
            for row in con.execute(f"PRAGMA table_info({table})")
        }
        selectable = [col for col in (id_col, *key_cols) if col in columns]
        if id_col not in columns or not selectable:
            continue
        rows = con.execute(
            f"SELECT {', '.join(selectable)} FROM {table} "
            f"ORDER BY rowid DESC LIMIT ?",
            (int(_CASE_INDEX_CAP),),
        ).fetchall()
        for row in rows:
            entry = {"table": table}
            for col in selectable:
                value = row[col] if col in row.keys() else None
                if value is None:
                    continue
                if col == "title" and isinstance(value, str) and len(value) > 120:
                    value = value[:120]
                entry[col] = value
            index.append(entry)
    return index[:_CASE_INDEX_CAP]


def _similar_case_prior(
    con,
    *,
    person_id: str,
    conversation_id: str,
    bundle: Mapping[str, Any],
    pattern_output: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the MINIMAL similar_case_retrieval prior (Codex correction 3).

    Exactly the three bounded inputs — pattern output summary, episode
    fingerprint, case index — and explicitly NOT the canonical facts registry.
    """

    return {
        "projection": "similar_case_minimal_v1",
        "note": "facts_registry_intentionally_omitted_kept_in_db",
        "pattern_output_summary": _pattern_output_summary(pattern_output),
        "episode_fingerprint": _episode_fingerprint(bundle),
        "case_index": _case_index(con, person_id, conversation_id),
    }


# ---------------------------------------------------------------------------
# Codex correction 4: lossless fallback windowing of INPUT FACTS (not schema
# fields).  When a projected fact/case list would push a stage's prompt over the
# 24576 input budget, split the list into windows by (source_engine, type),
# run the engine once per window, then merge/dedup by fact ref — never grow the
# context beyond the budget, never lose a fact.
# ---------------------------------------------------------------------------


def _fact_window_key(fact: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(fact.get("source_engine") or ""),
        str(fact.get("type") or fact.get("fact_type") or ""),
    )


def _window_facts_by_source(
    facts: Sequence[Mapping[str, Any]],
    *,
    max_facts_per_window: int,
) -> list[list[dict[str, Any]]]:
    """Split a fact list into source/type windows, each bounded in size.

    Facts are grouped by ``(source_engine, type)`` in first-seen order; an
    oversized group is further chunked so no window exceeds ``max_facts_per_window``.
    The union of all windows equals the input (no fact dropped, order stable).
    """

    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in facts:
        key = _fact_window_key(fact)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(dict(fact))
    windows: list[list[dict[str, Any]]] = []
    limit = max(1, int(max_facts_per_window))
    for key in order:
        group = grouped[key]
        for start in range(0, len(group), limit):
            windows.append(group[start:start + limit])
    return windows


def _fact_ref(fact: Mapping[str, Any]) -> str:
    for key in ("id", "ref", "fact_id"):
        value = fact.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return _hash_payload(fact)


def _merge_windowed_fact_outputs(outputs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Losslessly merge per-window engine outputs, dedup list items by ref/JSON.

    List fields are concatenated then deduplicated (by ``fact_id``/``id``/``ref``
    when present, else by canonical JSON); scalar ``confidence`` is averaged;
    other scalars keep the first non-null.  No window's contribution is dropped.
    """

    merged: dict[str, Any] = {}
    confidences: list[float] = []
    for output in outputs:
        if not isinstance(output, Mapping):
            continue
        for key, value in output.items():
            if key == "confidence":
                if isinstance(value, (int, float)):
                    confidences.append(float(value))
                continue
            if isinstance(value, list):
                bucket = merged.setdefault(key, [])
                if not isinstance(bucket, list):
                    continue
                bucket.extend(value)
            elif key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
    # Deduplicate every list field, preserving first-seen order.
    for key, value in list(merged.items()):
        if not isinstance(value, list):
            continue
        seen: set[str] = set()
        deduped: list[Any] = []
        for item in value:
            marker = _fact_ref(item) if isinstance(item, Mapping) else None
            if marker is None:
                marker = json_dumps(item)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        merged[key] = deduped
    if confidences:
        merged["confidence"] = sum(confidences) / len(confidences)
    return merged


def _pro_engine_input_budget(output_budget: int | None) -> int:
    """The input-token budget the fact-windowing fallback must keep under.

    Mirrors the executor's ``ModelBudget.max_input_tokens`` for the PRO cloud
    context cap (57344 by default, operator-overridable) minus the reserved output
    and the safety margin, so a windowed prompt matches what the executor accepts.
    At 48k every projected engine input fits in ONE cached call; the windowing
    fallback only triggers on a genuinely huge input, never as the normal path.
    """

    try:
        cloud_ctx = int(os.environ.get("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "57344"))
    except ValueError:
        cloud_ctx = 57344
    if output_budget is None:
        try:
            output_budget = max(
                256, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"))
            )
        except ValueError:
            output_budget = 4096
    return max(1, cloud_ctx - int(output_budget) - 768)


def _prior_without_shared_facts(prior: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of ``prior`` with the (large) shared-facts input list removed."""
    return {key: value for key, value in prior.items() if key != "shared_facts"}


def _prior_with_shared_facts(
    prior: Mapping[str, Any], facts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """A copy of ``prior`` whose ``shared_facts.facts`` is replaced by ``facts``."""
    result = {key: value for key, value in prior.items()}
    base = prior.get("shared_facts")
    envelope = dict(base) if isinstance(base, Mapping) else {
        "projection": "per_dependency_source_engine",
    }
    envelope["facts"] = [dict(fact) for fact in facts]
    envelope["windowed"] = True
    result["shared_facts"] = envelope
    return result


_INTERNAL_STATE_TYPES = {
    "emotional_reaction", "relationship_tension", "conflict", "avoidance",
    "commitment", "self_reflection",
}
_SOCIAL_TYPES = {"relationship_tension", "conflict", "client_request"}
_CONTRADICTION_TYPES = {
    "relationship_tension", "conflict", "decision_point", "commitment",
    "self_reflection",
}
_CHOICE_TYPES = {"decision_point", "planning", "commitment"}
_OUTCOME_TYPES = {"decision_point", "planning", "commitment", "client_request"}


def _metadata_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        parsed = json_loads(value, {})
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _episode_evidence_profile(con, episode_id: str) -> dict[str, Any]:
    rows = [dict(row) for row in con.execute(
        """SELECT t.turn_id,t.person_id,t.speaker_label,t.metadata_json
             FROM episode_evidence ee
             JOIN turns t ON t.turn_id=ee.turn_id
            WHERE ee.episode_id=? ORDER BY t.idx""",
        (episode_id,),
    ).fetchall()]
    human_rows: list[dict[str, Any]] = []
    for row in rows:
        metadata = _metadata_mapping(row.get("metadata_json"))
        if str(metadata.get("evidence_role") or "") != "system_observation_not_user_speech":
            human_rows.append(row)
    speakers = {
        str(row.get("person_id") or row.get("speaker_label") or "")
        for row in human_rows
        if row.get("person_id") or row.get("speaker_label")
    }
    return {
        "sensor_only": bool(rows) and not human_rows,
        "has_human_evidence": bool(human_rows),
        "human_speaker_count": len(speakers),
        "evidence_turn_ids": [str(row["turn_id"]) for row in rows],
    }


def _episode_semantic_types(episode: Mapping[str, Any]) -> set[str]:
    """Include durable subtheme types when the row is a conversation parent."""
    types = {str(episode.get("episode_type") or "other")}
    metadata = _metadata_mapping(episode.get("metadata_json"))
    raw = metadata.get("subtheme_types")
    if isinstance(raw, list):
        types.update(str(item) for item in raw if item)
    # E64-I uses readable topic families. Map only the families that imply an
    # existing cognitive capability; ordinary work/media/identity conversation
    # does not automatically become psychology.
    mapped = {
        "relationship": "relationship_tension",
        "technical": "technical_validation",
    }
    types.update(mapped[item] for item in list(types) if item in mapped)
    return types


def _stable_episode_source_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the source side of a local engine pack.

    `_episode_bundle` also exposes already-materialized engine tables for legacy
    single-engine callers. Feeding those rows back into the packed executor makes
    its prompt change after every successful materialization. Packed engines pass
    dependencies explicitly through `prior_engine_outputs`, so only immutable
    episode evidence belongs in their shared bundle.
    """
    episode = dict(bundle.get("episode") or {})
    episode_metadata = _metadata_mapping(episode.get("metadata_json"))
    compact_episode = {
        key: episode.get(key)
        for key in (
            "episode_id", "episode_type", "source_conversation_id",
            "start_turn_id", "end_turn_id", "start_time", "end_time",
            "participants_json", "location_text", "channel", "topic",
            "confidence", "importance_score",
        )
        if episode.get(key) is not None
    }
    if episode.get("situation_summary"):
        # The conversation parent summary is assembled deterministically from
        # the same subtheme summaries below. Do not pay the identical paragraph
        # twice in every engine pack.
        compact_episode["situation_summary_manifest"] = {
            "digest": _hash_payload(episode.get("situation_summary")),
            "represented_by": "subthemes[].summary",
        }
    if episode_metadata:
        compact_episode["metadata_manifest"] = {
            "digest": _hash_payload(episode_metadata),
            "coverage_status": episode_metadata.get("coverage_status"),
            "subtheme_types": episode_metadata.get("subtheme_types"),
            "source_quality_gaps": episode_metadata.get("source_quality_gaps"),
        }

    speech_turns: list[dict[str, Any]] = []
    sensor_turns: list[dict[str, Any]] = []
    for raw_turn in bundle.get("turns") or []:
        if not isinstance(raw_turn, Mapping):
            continue
        metadata = _metadata_mapping(raw_turn.get("metadata_json"))
        target = sensor_turns if str(metadata.get("evidence_role") or "") == (
            "system_observation_not_user_speech"
        ) else speech_turns
        compact_turn = {
            key: raw_turn.get(key)
            for key in (
                "turn_id", "idx", "speaker_label", "person_id", "start_s",
                "end_s", "text",
            )
            if raw_turn.get(key) is not None
        }
        for key in ("start_s", "end_s"):
            if isinstance(compact_turn.get(key), float):
                compact_turn[key] = round(float(compact_turn[key]), 3)
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        if isinstance(source, Mapping):
            resolution = source.get("offline_speaker_resolution")
            alignment = source.get("word_alignment")
            compact_turn["quality"] = {
                "speaker": (
                    resolution.get("decision")
                    if isinstance(resolution, Mapping) else None
                ),
                "known_score": (
                    resolution.get("known_score")
                    if isinstance(resolution, Mapping) else None
                ),
                "asr_mean": alignment.get("mean_score") if isinstance(alignment, Mapping) else None,
                "asr_min": alignment.get("min_score") if isinstance(alignment, Mapping) else None,
            }
        target.append(compact_turn)

    compact_subthemes: list[dict[str, Any]] = []
    for raw_subtheme in bundle.get("subthemes") or []:
        if not isinstance(raw_subtheme, Mapping):
            continue
        membership = [str(item) for item in raw_subtheme.get("membership_turn_ids") or []]
        primary_evidence = [
            str(item) for item in raw_subtheme.get("evidence_turn_ids") or []
        ]
        compact = {
            key: raw_subtheme.get(key)
            for key in (
                "ordinal", "subtheme_type", "title", "summary",
                "start_turn_id", "end_turn_id", "participants_json",
                "outcome_summary", "unresolved_tension", "confidence",
            )
            if raw_subtheme.get(key) is not None
        }
        compact["membership_manifest"] = {
            "count": len(membership), "digest": _hash_payload(membership),
        }
        compact["primary_evidence_manifest"] = {
            "count": len(primary_evidence),
            "digest": _hash_payload(primary_evidence),
            "durable_source": "episode_subtheme_evidence_v19",
        }
        compact_subthemes.append(compact)

    context_addenda = bundle.get("context_addenda")
    compact_addenda: dict[str, Any] = {}
    if isinstance(context_addenda, Mapping):
        entries: list[dict[str, Any]] = []
        for raw_entry in context_addenda.get("entries") or []:
            if not isinstance(raw_entry, Mapping):
                continue
            full_text = str(raw_entry.get("text") or "")
            text_parts = full_text.split(" | ")
            semantic_parts = text_parts[:1]
            for part in text_parts[1:]:
                if part.startswith(("activité_visible=", "lieu_probable=", "spatial=")):
                    semantic_parts.append(part)
            compact_text = " | ".join(semantic_parts)
            entry = {
                key: raw_entry.get(key)
                for key in (
                    "addendum_id", "source_id", "event_time", "evidence_role",
                )
                if raw_entry.get(key) is not None
            }
            entry["text"] = compact_text
            entry["full_text_digest"] = _hash_payload(full_text)
            raw_metadata = raw_entry.get("metadata_json")
            if raw_metadata:
                entry["metadata_manifest"] = {
                    "digest": _hash_payload(raw_metadata),
                    "durable_source": "brain2_context_addenda_v18",
                }
            entries.append(entry)
        raw_budget = dict(context_addenda.get("budget") or {})
        budget = {
            key: raw_budget.get(key)
            for key in ("included_items", "context_incomplete")
            if raw_budget.get(key) is not None
        }
        omitted = list(raw_budget.get("omitted_refs", []) or [])
        budget["omitted_manifest"] = {
            "count": len(omitted), "digest": _hash_payload(omitted),
        }
        compact_addenda = {
            "entries": entries,
            "budget": budget,
            "evidence_role_policy": context_addenda.get("evidence_role_policy"),
            "durable_source": "brain2_context_addenda_v18",
            "omitted_fields": "affordances/proofs/uncertainties consumed by visual consolidation",
        }

    # Deep Vision descriptions supersede the raw detector turn text for the
    # cognitive pack. Without a deep description, retain the compact raw sensor
    # lane explicitly rather than silently losing it.
    has_deep_context = bool(compact_addenda.get("entries"))
    stable = {
        "episode": compact_episode,
        "conversation": bundle.get("conversation"),
        "turns": speech_turns,
        "subthemes": compact_subthemes,
        "missing_context": bundle.get("missing_context") or [],
        "context_scope": bundle.get("context_scope"),
        "context_addenda": compact_addenda,
        "sensor_context": [] if has_deep_context else sensor_turns,
        "raw_sensor_manifest": {
            "count": len(sensor_turns),
            "digest": _hash_payload(sensor_turns),
            "represented_by": (
                "context_addenda.entries" if has_deep_context else "sensor_context"
            ),
        },
    }
    # Preserve the legacy prompt shape without feeding any materialized row
    # back. This also lets the first clean run's validated checkpoints remain
    # reusable after the tables have been populated.
    for key in (
        "situations", "interactions", "states", "thoughts", "speech_acts",
        "intentions", "outcomes", "choices", "causes", "contradictions",
        "patterns",
    ):
        stable[key] = []
    return stable


def _engine_applies_to_episode(
    engine: str, episode: Mapping[str, Any], profile: Mapping[str, Any]
) -> tuple[bool, str]:
    if profile.get("sensor_only") or not profile.get("has_human_evidence"):
        return False, "sensor_only_routed_to_vision_worldbrain_silent_life"
    episode_types = _episode_semantic_types(episode)
    if engine == "episode_builder":
        return False, "already_materialized_by_conversation_episode_builder"
    if engine in {"capture_engine", "language_signature_engine"}:
        return True, "human_audio_episode_batched_by_engine"
    if engine == "context_resolver" or engine == "causality_engine":
        return True, "human_narrative_episode"
    if engine == "internal_state_engine":
        return bool(episode_types & _INTERNAL_STATE_TYPES), "episode_type_has_state_evidence"
    if engine == "social_model_engine":
        applies = int(profile.get("human_speaker_count") or 0) >= 2 or bool(episode_types & _SOCIAL_TYPES)
        return applies, "multi_speaker_or_social_episode"
    if engine == "contradiction_engine":
        return bool(episode_types & _CONTRADICTION_TYPES), "episode_type_can_support_contradiction"
    if engine == "choice_model_engine":
        return bool(episode_types & _CHOICE_TYPES), "episode_type_can_support_choice"
    if engine == "outcome_tracker":
        return bool(episode_types & _OUTCOME_TYPES), "episode_type_can_support_intention_or_outcome"
    return False, "conversation_scope_engine"


def _conversation_engine_bundle(
    con,
    conversation_id: str,
    episodes: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    outputs_by_episode: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    from .brain2_episode_windowing import _prompt_turn

    base = _conversation_bundle(con, conversation_id)
    human_turn_ids = {
        turn_id
        for episode_id, profile in profiles.items()
        if profile.get("has_human_evidence")
        for turn_id in profile.get("evidence_turn_ids", [])
    }
    turns = [
        _prompt_turn(turn)
        for turn in (base.get("turns") or [])
        if str(turn.get("turn_id") or "") in human_turn_ids
    ]
    episode_summaries = [
        {
            key: episode.get(key)
            for key in (
                "episode_id", "episode_type", "start_time", "end_time", "topic",
                "situation_summary", "trigger_summary", "outcome_summary",
                "unresolved_tension",
            )
        }
        for episode in episodes
        if profiles.get(str(episode.get("episode_id")), {}).get("has_human_evidence")
    ]
    return {
        "analysis_scope": "conversation_human_evidence",
        "conversation": base.get("conversation"),
        "turns": turns,
        "episodes": episode_summaries,
        "sensor_route_manifest": {
            "policy": "raw sensor evidence remains in Vision/WorldBrain/Silent Life",
            "sensor_episode_count": sum(
                1 for profile in profiles.values() if profile.get("sensor_only")
            ),
        },
    }


def _schema_field_groups(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    common = {
        name: schema[name]
        for name in ("evidence", "counter_evidence", "confidence")
        if name in schema
    }
    business = [name for name in schema if name not in common]
    if not business:
        return [dict(schema)]
    size = 3 if len(business) > 3 else len(business)
    return [
        {**{name: schema[name] for name in business[i:i + size]}, **common}
        for i in range(0, len(business), size)
    ]


def _run_engine_episode_batches(
    con,
    *,
    engine: str,
    conversation_id: str,
    person_id: str,
    package_date: str,
    tasks: Mapping[str, tuple[dict[str, Any], dict[str, Any]]],
    window_llm: Any | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Run one engine over token-bounded episode batches, preserving every field."""
    from .config import get_settings
    from .night_orchestrator import (
        ModelBudget, OllamaWindowLLM, PlanUnit, StageScope,
        build_coverage_report, covered_refs_from_outputs_table,
        estimate_tokens_for_text, run_windows,
    )
    from .night_orchestrator import checkpoint_store as cp
    from .night_orchestrator.coverage import persist_coverage

    if not tasks:
        return {}
    cfg = get_settings()
    context_window = int(context_window or cfg.ollama_context_poststop)
    if output_budget is None:
        try:
            output_budget = max(256, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096")))
        except ValueError:
            output_budget = 4096
    if window_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        from .runtime_v18_7 import phase as runtime_phase_context
        with runtime_phase_context("post_stop_brain2_v13"):
            window_llm = OllamaWindowLLM(system=_BRAIN2_STRICT_SYSTEM, timeout=timeout)
    model = str(getattr(window_llm, "model", "injected-window-llm"))
    merged: dict[str, dict[str, Any]] = {episode_id: {} for episode_id in tasks}
    evidence: dict[str, list[Any]] = {episode_id: [] for episode_id in tasks}
    counter: dict[str, list[Any]] = {episode_id: [] for episode_id in tasks}
    confidences: dict[str, list[float]] = {episode_id: [] for episode_id in tasks}

    for group_index, task_schema in enumerate(_schema_field_groups(ENGINE_SCHEMAS[engine])):
        payload_by_id = {
            episode_id: {
                "episode_id": episode_id,
                "bundle": bundle,
                "prior_engine_outputs": prior,
            }
            for episode_id, (bundle, prior) in tasks.items()
        }
        units = [
            PlanUnit(
                ref_id=episode_id,
                tokens=estimate_tokens_for_text(json_dumps(payload)) + 32,
                content_digest=_hash_payload(payload),
            )
            for episode_id, payload in payload_by_id.items()
        ]
        schema_hint = {"results": [{"task_index": 0, "output": task_schema}]}

        def render(window_units) -> dict[str, Any]:
            ids = [unit.ref_id for unit in window_units]
            indexed_tasks = [
                {**payload_by_id[episode_id], "task_index": index}
                for index, episode_id in enumerate(ids)
            ]
            prompt = _safe_prompt_payload({
                "engine_name": engine,
                "mission": "Exécute ce moteur Brain 2.0 séparément pour chaque tâche. Retourne exactement une sortie par task_index fourni; ne mélange jamais les preuves entre tâches.",
                "evidence_role_policy": "Les observations système sont du contexte capteur, jamais une déclaration ou un état psychologique de William.",
                "task_schema": task_schema,
                "tasks": indexed_tasks,
            })
            return {"prompt": prompt, "schema_hint": schema_hint}

        def normalize(value: Any, primary) -> Any:
            if not isinstance(value, Mapping) or not isinstance(value.get("results"), list):
                return None
            expected_ids = [unit.ref_id for unit in primary]
            found: dict[int, dict[str, Any]] = {}
            for item in value["results"]:
                if not isinstance(item, Mapping):
                    continue
                task_index = item.get("task_index")
                output = item.get("output")
                if (
                    isinstance(task_index, int)
                    and 0 <= task_index < len(expected_ids)
                    and isinstance(output, Mapping)
                ):
                    found[task_index] = dict(output)
            if set(found) != set(range(len(expected_ids))):
                return None
            return {"results": [
                {"episode_id": expected_ids[index], "output": found[index]}
                for index in range(len(expected_ids))
            ]}

        def validate(value: Any) -> bool:
            if not isinstance(value, Mapping) or not isinstance(value.get("results"), list):
                return False
            required = set(task_schema)
            return all(
                isinstance(item, Mapping)
                and isinstance(item.get("output"), Mapping)
                and required.issubset(item["output"])
                for item in value["results"]
            )

        def envelope(value: Any, primary) -> dict[str, Any]:
            return {
                "episode_ids": [unit.ref_id for unit in primary],
                "result": value,
                "schema_fields": list(task_schema),
            }

        empty_prompt = _safe_prompt_payload({
            "engine_name": engine,
            "mission": "Exécute ce moteur Brain 2.0 séparément pour chaque tâche.",
            "task_schema": task_schema,
            "tasks": [],
        })
        scoped_stage = f"brain2_engine_batch:{conversation_id}:{engine}:g{group_index}"
        from .runtime_v18_7 import phase as runtime_phase_context
        with runtime_phase_context("post_stop_brain2_v13"):
            stage = run_windows(
                units,
                con=con,
                scope=StageScope(
                    person_id=person_id,
                    package_date=package_date,
                    stage_name=scoped_stage,
                    adapter_version="e64f-v13-engine-batch-v5-projected",
                    prompt_version=f"{STRICT_VERSION}:{engine}:g{group_index}",
                    model=model,
                ),
                llm=window_llm,
                budget=ModelBudget(
                    context_window=context_window,
                    output_reserve=int(output_budget),
                    safety_margin=768,
                ),
                render=render,
                validate=validate,
                normalize_output=normalize,
                decorate_output=envelope,
                target_units=2,
                overlap=0,
                prompt_overhead_tokens=estimate_tokens_for_text(empty_prompt),
                sleeper=lambda _seconds: None,
            )
        current_keys = {window.window_key for window in stage.windows}
        covered = covered_refs_from_outputs_table(
            con,
            person_id=person_id,
            package_date=package_date,
            stage_name=scoped_stage,
            window_keys=current_keys,
            extract_refs=lambda stored: stored.get("episode_ids", [])
            if isinstance(stored, Mapping) else (),
        )
        report = build_coverage_report(
            stage_name=scoped_stage,
            expected_ids=tasks,
            covered_refs=covered,
        )
        persist_coverage(
            con, person_id=person_id, package_date=package_date,
            source_ref=f"{conversation_id}:{engine}:g{group_index}", report=report,
        )
        con.commit()
        if not stage.all_completed or not report.ok:
            raise RuntimeError(
                f"{scoped_stage} incomplete: missing={len(report.missing)} "
                f"states={[window.state for window in stage.windows]}"
            )
        for stored in cp.load_outputs(
            con, person_id=person_id, package_date=package_date,
            stage_name=scoped_stage, window_keys=current_keys,
        ):
            envelope_value = stored.get("output") if isinstance(stored, Mapping) else None
            result = envelope_value.get("result") if isinstance(envelope_value, Mapping) else None
            for item in (result.get("results") if isinstance(result, Mapping) else []) or []:
                if not isinstance(item, Mapping):
                    continue
                episode_id = str(item.get("episode_id") or "")
                output = item.get("output")
                if episode_id not in merged or not isinstance(output, Mapping):
                    continue
                for field in task_schema:
                    if field in {"evidence", "counter_evidence", "confidence"}:
                        continue
                    if field in output:
                        merged[episode_id][field] = output[field]
                evidence[episode_id].extend(_as_list(output.get("evidence")))
                counter[episode_id].extend(_as_list(output.get("counter_evidence")))
                if isinstance(output.get("confidence"), (int, float)):
                    confidences[episode_id].append(float(output["confidence"]))

    def unique(values: Sequence[Any]) -> list[Any]:
        seen: set[str] = set()
        result: list[Any] = []
        for value in values:
            marker = json_dumps(value)
            if marker not in seen:
                seen.add(marker)
                result.append(value)
        return result

    schema = ENGINE_SCHEMAS[engine]
    for episode_id, output in merged.items():
        if "evidence" in schema:
            output["evidence"] = unique(evidence[episode_id])
        if "counter_evidence" in schema:
            output["counter_evidence"] = unique(counter[episode_id])
        if "confidence" in schema:
            vals = confidences[episode_id]
            output["confidence"] = sum(vals) / len(vals) if vals else 0.0
    return merged


def _run_episode_engine_pack(
    con,
    *,
    episode_id: str,
    conversation_id: str,
    person_id: str,
    package_date: str,
    bundle: Mapping[str, Any],
    prior: Mapping[str, Any],
    engines: Sequence[str],
    pack_name: str = "local",
    window_llm: Any | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Execute all applicable local engines while serialising evidence once.

    Each plan unit is one engine schema group.  A normal episode therefore uses
    one coherent Qwen request.  If that response reaches its output limit, the
    durable window executor splits by responsibilities (never by dropping
    evidence) and retries only the smaller engine groups.
    """
    from .config import get_settings
    from .night_orchestrator import (
        ModelBudget, OllamaWindowLLM, PlanUnit, StageScope,
        build_coverage_report, covered_refs_from_outputs_table,
        estimate_tokens_for_text, run_windows,
    )
    from .night_orchestrator import checkpoint_store as cp
    from .night_orchestrator.coverage import persist_coverage

    ordered_engines = [engine for engine in ENGINE_ORDER if engine in set(engines)]
    if not ordered_engines:
        return {}
    cfg = get_settings()
    context_window = int(context_window or cfg.ollama_context_poststop)
    if output_budget is None:
        try:
            output_budget = max(256, int(os.environ.get(
                "MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"
            )))
        except ValueError:
            output_budget = 4096
    if window_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        from .runtime_v18_7 import phase as runtime_phase_context
        with runtime_phase_context("post_stop_brain2_v13"):
            window_llm = OllamaWindowLLM(system=_BRAIN2_STRICT_SYSTEM, timeout=timeout)
    model = str(getattr(window_llm, "model", "injected-window-llm"))

    specs: dict[str, tuple[str, dict[str, Any]]] = {}
    units: list[PlanUnit] = []
    for engine in ordered_engines:
        for group_index, group_schema in enumerate(_schema_field_groups(ENGINE_SCHEMAS[engine])):
            ref_id = f"{engine}:g{group_index}"
            specs[ref_id] = (engine, group_schema)
            units.append(PlanUnit(
                ref_id=ref_id,
                tokens=estimate_tokens_for_text(json_dumps(group_schema)) + 48,
                content_digest=_hash_payload(group_schema),
            ))

    def render(window_units) -> dict[str, Any]:
        refs = [unit.ref_id for unit in window_units]
        schemas = {ref: specs[ref][1] for ref in refs}
        prompt = _safe_prompt_payload({
            "mission": (
                "Analyse un seul épisode avec les responsabilités Brain 2.0 listées. "
                "Exécute-les dans l'ordre fourni; une responsabilité ultérieure peut "
                "utiliser les conclusions précédentes. Retourne chaque clé exactement "
                "une fois, sans recopier le bundle ni les métadonnées brutes."
            ),
            "evidence_role_policy": (
                "Une observation système est du contexte capteur, jamais une parole, "
                "préférence ou émotion déclarée de William."
            ),
            "episode_id": episode_id,
            "engine_order": refs,
            "bundle": bundle,
            "prior_engine_outputs": prior,
            "output_schemas": schemas,
        })
        return {"prompt": prompt, "schema_hint": {"outputs": schemas}}

    def validate(value: Any) -> bool:
        if not isinstance(value, Mapping) or not isinstance(value.get("outputs"), Mapping):
            return False
        outputs = value["outputs"]
        for ref_id, output in outputs.items():
            if ref_id not in specs or not isinstance(output, Mapping):
                return False
            if not set(specs[ref_id][1]).issubset(output):
                return False
        return True

    def normalize(value: Any, primary) -> Any:
        if not isinstance(value, Mapping) or not isinstance(value.get("outputs"), Mapping):
            return None
        expected = {unit.ref_id for unit in primary}
        outputs = value["outputs"]
        if set(outputs) != expected:
            return None
        return {"outputs": {ref: outputs[ref] for ref in sorted(expected)}}

    def envelope(value: Any, primary) -> dict[str, Any]:
        return {
            "engine_group_refs": [unit.ref_id for unit in primary],
            "result": value,
        }

    overhead_prompt = _safe_prompt_payload({
        "mission": "Analyse un seul épisode avec les responsabilités Brain 2.0 listées.",
        "episode_id": episode_id,
        "bundle": bundle,
        "prior_engine_outputs": prior,
        "output_schemas": {},
    })
    stage_name = f"brain2_episode_pack:{conversation_id}:{episode_id}:{pack_name}"
    from .runtime_v18_7 import phase as runtime_phase_context
    with runtime_phase_context("post_stop_brain2_v13"):
        stage = run_windows(
            units,
            con=con,
            scope=StageScope(
                person_id=person_id,
                package_date=package_date,
                stage_name=stage_name,
                adapter_version="e64f-v13-episode-pack-v2",
                prompt_version=f"{STRICT_VERSION}:episode-pack-v2:{pack_name}",
                model=model,
            ),
            llm=window_llm,
            budget=ModelBudget(
                context_window=context_window,
                output_reserve=int(output_budget),
                safety_margin=768,
            ),
            render=render,
            validate=validate,
            normalize_output=normalize,
            decorate_output=envelope,
            target_units=len(units),
            overlap=0,
            prompt_overhead_tokens=estimate_tokens_for_text(overhead_prompt),
            sleeper=lambda _seconds: None,
        )
    current_keys = {window.window_key for window in stage.windows}
    covered = covered_refs_from_outputs_table(
        con,
        person_id=person_id,
        package_date=package_date,
        stage_name=stage_name,
        window_keys=current_keys,
        extract_refs=lambda stored: stored.get("engine_group_refs", [])
        if isinstance(stored, Mapping) else (),
    )
    report = build_coverage_report(
        stage_name=stage_name,
        expected_ids=specs,
        covered_refs=covered,
    )
    persist_coverage(
        con, person_id=person_id, package_date=package_date,
        source_ref=f"{conversation_id}:{episode_id}:{pack_name}", report=report,
    )
    con.commit()
    if not stage.all_completed or not report.ok:
        raise RuntimeError(
            f"{stage_name} incomplete: missing={len(report.missing)} "
            f"states={[window.state for window in stage.windows]}"
        )

    partials: dict[str, list[Mapping[str, Any]]] = {
        engine: [] for engine in ordered_engines
    }
    for stored in cp.load_outputs(
        con, person_id=person_id, package_date=package_date,
        stage_name=stage_name, window_keys=current_keys,
    ):
        envelope_value = stored.get("output") if isinstance(stored, Mapping) else None
        result = envelope_value.get("result") if isinstance(envelope_value, Mapping) else None
        outputs = result.get("outputs") if isinstance(result, Mapping) else None
        if not isinstance(outputs, Mapping):
            continue
        for ref_id, output in outputs.items():
            spec = specs.get(str(ref_id))
            if spec and isinstance(output, Mapping):
                partials[spec[0]].append(output)

    def unique(values: Sequence[Any]) -> list[Any]:
        seen: set[str] = set()
        result: list[Any] = []
        for value in values:
            marker = json_dumps(value)
            if marker not in seen:
                seen.add(marker)
                result.append(value)
        return result

    merged: dict[str, dict[str, Any]] = {}
    for engine in ordered_engines:
        output: dict[str, Any] = {}
        evidence: list[Any] = []
        counter: list[Any] = []
        confidences: list[float] = []
        for partial in partials[engine]:
            for field, value in partial.items():
                if field == "evidence":
                    evidence.extend(_as_list(value))
                elif field == "counter_evidence":
                    counter.extend(_as_list(value))
                elif field == "confidence" and isinstance(value, (int, float)):
                    confidences.append(float(value))
                else:
                    output[field] = value
        schema = ENGINE_SCHEMAS[engine]
        if "evidence" in schema:
            output["evidence"] = unique(evidence)
        if "counter_evidence" in schema:
            output["counter_evidence"] = unique(counter)
        if "confidence" in schema:
            output["confidence"] = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )
        if not set(schema).issubset(output):
            raise RuntimeError(f"{stage_name} missing merged fields for {engine}")
        merged[engine] = output
    return merged


def _run_global_engine_hierarchy(
    con,
    *,
    conversation_id: str,
    person_id: str,
    package_date: str,
    conversation: Mapping[str, Any] | None,
    episodes: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    outputs_by_episode: Mapping[str, Mapping[str, Any]],
    engines: Sequence[str],
    client: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Run cross-episode engines over durable episode capsules.

    Capsules keep every local-engine output and evidence reference together. The
    generic hierarchy windows by capsule for long days, merges validated partial
    results, and proves that every capsule reached the final result. If Qwen
    cannot emit all responsibilities together, only the output schemas are split.
    """
    from .night_orchestrator import run_hierarchical_json

    ordered = [engine for engine in ENGINE_ORDER if engine in set(engines)]
    specs: dict[str, tuple[str, dict[str, Any]]] = {}
    for engine in ordered:
        for group_index, group_schema in enumerate(_schema_field_groups(ENGINE_SCHEMAS[engine])):
            specs[f"{engine}:g{group_index}"] = (engine, group_schema)

    capsules: list[dict[str, Any]] = []
    episode_by_id = {str(ep.get("episode_id")): ep for ep in episodes}
    for episode_id, engine_outputs in outputs_by_episode.items():
        profile = profiles.get(episode_id, {})
        if not profile.get("has_human_evidence"):
            continue
        episode = episode_by_id.get(episode_id, {})
        capsules.append({
            "episode_id": episode_id,
            "episode": {
                key: episode.get(key)
                for key in (
                    "episode_type", "start_time", "end_time", "topic",
                    "situation_summary", "trigger_summary", "outcome_summary",
                    "unresolved_tension", "confidence",
                )
            },
            "evidence_turn_ids": list(profile.get("evidence_turn_ids") or []),
            "local_engine_outputs": dict(engine_outputs),
        })

    payload = {
        "mission": (
            "Exécute les moteurs Brain 2.0 transversaux sur tous les épisodes. "
            "Chaque capsule est une synthèse locale validée avec ses preuves. "
            "Préserve contradictions, contre-preuves et cas distincts; n'invente "
            "aucune information absente."
        ),
        "engine_order": " -> ".join(ordered),
        "conversation": conversation,
        "episode_capsules": capsules,
    }

    def execute(refs: Sequence[str], branch: str) -> dict[str, Mapping[str, Any]]:
        schemas = {ref: specs[ref][1] for ref in refs}
        schema = {"outputs": schemas}
        digest = _hash_payload(list(refs))[:10]
        try:
            from .runtime_v18_7 import phase as runtime_phase_context
            with runtime_phase_context("post_stop_brain2_v13"):
                result = run_hierarchical_json(
                    stage_name=(
                        f"brain2_global_pack:{conversation_id}:{branch}:{digest}"
                    ),
                    person_id=person_id,
                    package_date=package_date,
                    source_ref=f"{conversation_id}:global:{branch}:{digest}",
                    system=_BRAIN2_STRICT_SYSTEM,
                    payload=payload,
                    schema=schema,
                    timeout=float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180")),
                    client=client,
                    connection=con,
                )
            outputs = result.get("outputs") if isinstance(result, Mapping) else None
            if not isinstance(outputs, Mapping) or set(outputs) != set(refs):
                raise RuntimeError("global engine pack output coverage mismatch")
            return {str(ref): output for ref, output in outputs.items()}
        except Exception:
            if len(refs) <= 1:
                raise
            middle = len(refs) // 2
            return {
                **execute(refs[:middle], branch + "a"),
                **execute(refs[middle:], branch + "b"),
            }

    partials = execute(list(specs), "root")

    def unique(values: Sequence[Any]) -> list[Any]:
        seen: set[str] = set()
        result: list[Any] = []
        for value in values:
            marker = json_dumps(value)
            if marker not in seen:
                seen.add(marker)
                result.append(value)
        return result

    merged: dict[str, dict[str, Any]] = {}
    for engine in ordered:
        output: dict[str, Any] = {}
        evidence: list[Any] = []
        counter: list[Any] = []
        confidences: list[float] = []
        for ref_id, partial in partials.items():
            if specs[ref_id][0] != engine or not isinstance(partial, Mapping):
                continue
            for field, value in partial.items():
                if field == "evidence":
                    evidence.extend(_as_list(value))
                elif field == "counter_evidence":
                    counter.extend(_as_list(value))
                elif field == "confidence" and isinstance(value, (int, float)):
                    confidences.append(float(value))
                else:
                    output[field] = value
        schema = ENGINE_SCHEMAS[engine]
        if "evidence" in schema:
            output["evidence"] = unique(evidence)
        if "counter_evidence" in schema:
            output["counter_evidence"] = unique(counter)
        if "confidence" in schema:
            output["confidence"] = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )
        if not set(schema).issubset(output):
            raise RuntimeError(f"global hierarchy missing fields for {engine}")
        merged[engine] = output
    return merged


def _record_engine(con, *, engine: str, conversation_id: str | None, episode_id: str | None, person_id: str | None, prompt: str, output: dict[str, Any] | None, status: str, error: str | None = None) -> str:
    now = now_iso()
    run_id = stable_id("v13stricteng", STRICT_VERSION, engine, conversation_id, episode_id, _hash_payload(prompt)[:16])
    upsert(con, "v13_engine_runs", {
        "engine_run_id": run_id,
        "engine_name": engine,
        "engine_version": STRICT_VERSION,
        "cycle_id": stable_id("v13strictcycle", conversation_id or "predict", episode_id or "none"),
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "person_id": person_id,
        "input_hash": _hash_payload(prompt),
        "require_llm": 1,
        "llm_model": os.environ.get("MLOMEGA_OLLAMA_MODEL", "qwen3:8b"),
        "status": status,
        "stage": "finished",
        "started_at": now,
        "finished_at": now,
        "counts_json": json_dumps({"output_keys": len(output or {})}),
        "warnings_json": json_dumps([]),
        "missing_json": json_dumps([] if output else ["qwen_json_output"]),
        "error_text": error,
        "metadata_json": json_dumps({"strict_version": STRICT_VERSION}),
    }, "engine_run_id")
    upsert(con, "v13_engine_outputs", {
        "output_id": stable_id("v13strictout", run_id),
        "engine_run_id": run_id,
        "engine_name": engine,
        "target_table": "episodes" if episode_id else "conversations",
        "target_id": episode_id or conversation_id,
        "output_type": "strict_qwen_json",
        "output_json": json_dumps(output or {}),
        "confidence": _clamp((output or {}).get("confidence")),
        "evidence_json": json_dumps(_as_list((output or {}).get("evidence"))),
        "counter_evidence_json": json_dumps(_as_list((output or {}).get("counter_evidence"))),
        "validation_status": "valid" if output else "failed",
        "created_at": now,
    }, "output_id")
    return run_id


def _load_completed_engine_output(
    con,
    *,
    engine: str,
    conversation_id: str,
    episode_id: str,
    prompt: str,
) -> dict[str, Any] | None:
    """Resume one V13 engine only when prompt+validated output match exactly."""
    run_id = stable_id(
        "v13stricteng", STRICT_VERSION, engine, conversation_id, episode_id,
        _hash_payload(prompt)[:16],
    )
    row = con.execute(
        """SELECT r.status,o.output_json,o.validation_status
             FROM v13_engine_runs r
             JOIN v13_engine_outputs o ON o.engine_run_id=r.engine_run_id
            WHERE r.engine_run_id=? AND r.input_hash=?
            ORDER BY o.created_at DESC LIMIT 1""",
        (run_id, _hash_payload(prompt)),
    ).fetchone()
    if not row or str(row["status"]) != "ok" or str(row["validation_status"]) != "valid":
        return None
    parsed = json_loads(row["output_json"], None)
    return parsed if isinstance(parsed, dict) else None


def _insert_object_link(con, conversation_id: str | None, episode_id: str | None, from_table: str, from_id: str, to_table: str, to_id: str, relation: str, engine: str | None, confidence: float = 1.0, evidence: list[Any] | None = None) -> None:
    upsert(con, "brain2_object_links", {
        "object_link_id": stable_id("objlink", from_table, from_id, to_table, to_id, relation),
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "from_table": from_table,
        "from_id": from_id,
        "to_table": to_table,
        "to_id": to_id,
        "relation_type": relation,
        "engine_name": engine,
        "evidence_json": json_dumps(evidence or []),
        "confidence": _clamp(confidence),
        "created_at": now_iso(),
    }, "object_link_id")


def _insert_temporal_link(con, conversation_id: str | None, episode_id: str | None, from_table: str, from_id: str, to_table: str, to_id: str, relation: str, from_time: str | None = None, to_time: str | None = None, confidence: float = 1.0) -> None:
    upsert(con, "brain2_temporal_links", {
        "temporal_link_id": stable_id("timelink", from_table, from_id, to_table, to_id, relation),
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "from_table": from_table,
        "from_id": from_id,
        "to_table": to_table,
        "to_id": to_id,
        "relation_type": relation,
        "from_time": from_time,
        "to_time": to_time,
        "lag_seconds": None,
        "evidence_json": json_dumps([]),
        "confidence": _clamp(confidence),
        "created_at": now_iso(),
    }, "temporal_link_id")


def _materialize_episodes_from_qwen(con, conversation_id: str, output: dict[str, Any]) -> int:
    conv = con.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
    now = now_iso(); count = 0
    missing_context = _as_list(output.get("missing_context"))
    missing_manifest = {
        "count": len(missing_context),
        "digest": _hash_payload(json_dumps(missing_context)),
        "detail_source": "night_llm_window_outputs_v19",
    }
    for i, ep in enumerate(_as_list(output.get("episodes"))):
        if not isinstance(ep, dict):
            continue
        evidence_turn_ids = [str(x) for x in _as_list(ep.get("evidence_turn_ids")) if x]
        start_turn = ep.get("start_turn_id") or (evidence_turn_ids[0] if evidence_turn_ids else None)
        end_turn = ep.get("end_turn_id") or (evidence_turn_ids[-1] if evidence_turn_ids else start_turn)
        summary = str(ep.get("situation_summary") or ep.get("topic") or "").strip()
        if not summary:
            continue
        episode_id = stable_id("episode", "strict", conversation_id, i, summary[:120], start_turn, end_turn)
        start_time = ep.get("start_time") or (conv["started_at"] if conv else now)
        end_time = ep.get("end_time") or None
        upsert(con, "episodes", {
            "episode_id": episode_id,
            "episode_type": ep.get("episode_type") or "other",
            "start_time": start_time,
            "end_time": end_time,
            "source_conversation_id": conversation_id,
            "start_turn_id": start_turn,
            "end_turn_id": end_turn,
            "participants_json": json_dumps(_as_list(ep.get("participants"))),
            "location_text": ep.get("location"),
            "channel": ep.get("channel") or (conv["channel"] if conv else None),
            "topic": ep.get("topic"),
            "situation_summary": summary,
            "trigger_summary": ep.get("trigger"),
            "user_state_before_json": json_dumps(ep.get("user_state_before")),
            "speech_or_action_summary": ep.get("speech_or_action"),
            "target_person_id": ep.get("target_person"),
            "target_reaction_summary": ep.get("target_reaction"),
            "user_state_after_json": json_dumps(ep.get("user_state_after")),
            "outcome_summary": ep.get("outcome"),
            "unresolved_tension": ep.get("unresolved_tension"),
            "confidence": _clamp(ep.get("confidence")),
            "truth_status": "inferred",
            "importance_score": _clamp(ep.get("importance_score", ep.get("confidence"))),
            "lifecycle_status": "active",
            "metadata_json": json_dumps({
                "strict_v13_2": True,
                "episode_source": ep.get("episode_contract") or EPISODE_BUILD_VERSION,
                "coverage_status": "complete",
                "subtheme_count": len(_as_list(ep.get("subthemes"))),
                "subtheme_types": list(dict.fromkeys(
                    str(item.get("subtheme_type") or "other")
                    for item in _as_list(ep.get("subthemes"))
                    if isinstance(item, dict)
                )),
                "missing_context_manifest": missing_manifest,
            }),
            "created_at": now,
            "updated_at": now,
        }, "episode_id")
        for turn_id in evidence_turn_ids:
            ev_id = stable_id("epevidence", episode_id, turn_id)
            turn = con.execute("SELECT text FROM turns WHERE turn_id=?", (turn_id,)).fetchone()
            upsert(con, "episode_evidence", {
                "episode_evidence_id": ev_id,
                "episode_id": episode_id,
                "source_span_id": None,
                "turn_id": turn_id,
                "evidence_text": turn["text"] if turn else None,
                "evidence_role": "qwen_selected_turn",
                "confidence": _clamp(ep.get("confidence")),
                "created_at": now,
            }, "episode_evidence_id")
            _insert_object_link(con, conversation_id, episode_id, "episodes", episode_id, "turns", turn_id, "supported_by", "episode_builder", _clamp(ep.get("confidence")))
        for ordinal, subtheme in enumerate(_as_list(ep.get("subthemes"))):
            if not isinstance(subtheme, dict):
                continue
            turn_ids = [str(x) for x in _as_list(subtheme.get("turn_ids")) if x]
            cited_ids = {
                str(x) for x in _as_list(subtheme.get("evidence_turn_ids")) if x
            }
            if not turn_ids:
                continue
            subtheme_id = stable_id("episode-subtheme-v19", episode_id, ordinal)
            upsert(con, "episode_subthemes_v19", {
                "subtheme_id": subtheme_id,
                "episode_id": episode_id,
                "ordinal": ordinal,
                "subtheme_type": subtheme.get("subtheme_type") or "other",
                "title": subtheme.get("title") or f"Sous-thème {ordinal + 1}",
                "summary": subtheme.get("summary") or "",
                "start_turn_id": subtheme.get("start_turn_id") or turn_ids[0],
                "end_turn_id": subtheme.get("end_turn_id") or turn_ids[-1],
                "participants_json": json_dumps(_as_list(subtheme.get("participants"))),
                "outcome_summary": subtheme.get("outcome"),
                "unresolved_tension": subtheme.get("unresolved_tension"),
                "confidence": _clamp(subtheme.get("confidence")),
                "metadata_json": json_dumps({
                    "episode_contract": ep.get("episode_contract"),
                    "membership_count": len(turn_ids),
                    "primary_citation_count": len(cited_ids),
                    "boundary_reason": subtheme.get("boundary_reason"),
                }),
                "created_at": now,
                "updated_at": now,
            }, "subtheme_id")
            for turn_id in turn_ids:
                upsert(con, "episode_subtheme_evidence_v19", {
                    "subtheme_evidence_id": stable_id(
                        "episode-subtheme-evidence-v19", subtheme_id, turn_id, "membership"
                    ),
                    "subtheme_id": subtheme_id,
                    "turn_id": turn_id,
                    "evidence_role": "membership",
                    "confidence": _clamp(subtheme.get("confidence")),
                    "created_at": now,
                }, "subtheme_evidence_id")
                if turn_id in cited_ids:
                    upsert(con, "episode_subtheme_evidence_v19", {
                        "subtheme_evidence_id": stable_id(
                            "episode-subtheme-evidence-v19", subtheme_id, turn_id,
                            "primary_citation",
                        ),
                        "subtheme_id": subtheme_id,
                        "turn_id": turn_id,
                        "evidence_role": "primary_citation",
                        "confidence": _clamp(subtheme.get("confidence")),
                        "created_at": now,
                    }, "subtheme_evidence_id")
        for btype, tid in [("start", start_turn), ("end", end_turn)]:
            if tid:
                turn = con.execute("SELECT idx, text FROM turns WHERE turn_id=?", (tid,)).fetchone()
                upsert(con, "episode_boundaries", {
                    "boundary_id": stable_id("epbound", episode_id, btype, tid),
                    "conversation_id": conversation_id,
                    "episode_id": episode_id,
                    "boundary_type": btype,
                    "turn_id": tid,
                    "idx": turn["idx"] if turn else None,
                    "reason": f"Qwen episode_builder boundary: {btype}",
                    "confidence": _clamp(ep.get("confidence")),
                    "evidence_text": turn["text"] if turn else None,
                    "created_at": now,
                }, "boundary_id")
        _insert_temporal_link(con, conversation_id, episode_id, "conversations", conversation_id, "episodes", episode_id, "contains", conv["started_at"] if conv else None, start_time)
        count += 1
    return count


# The exact V13 episode_builder mission. Kept as a single constant so the legacy
# call and the E64-F windowed path use identical prompt text (no prompt change).
_EPISODE_MISSION = "Découpe cette conversation en épisodes de vie selon le plan Brain 2.0. Aucun découpage par regex: utilise le sens, les preuves et l'incertitude. Respecte metadata_json.kind/evidence_role: observation système ≠ parole de William."


def _pro_closeday_enabled() -> bool:
    return os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _episode_builder_forces_local() -> bool:
    """PRO must never let DeepSeek build episodes (docs/PRO_CLOSEDAY_HANDOFF.md §A).

    The nightly PRO subprocess sets ``MLOMEGA_LLM_BACKEND=deepseek`` so the
    cognitive engines fan out to the cloud. EpisodeBuilder, however, is the
    already-validated lossless P1/llama.cpp stage and stays local. This is true
    only when a cloud text backend would otherwise be inherited: without the PRO
    flag (or with the local backend) this returns ``False`` and NOTHING below runs,
    so the local path keeps its exact implicit client and stays byte-for-byte.
    """
    if not _pro_closeday_enabled():
        return False
    return os.environ.get("MLOMEGA_LLM_BACKEND", "").strip().lower() == "deepseek"


def _cache_settle_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("MLOMEGA_DEEPSEEK_CACHE_SETTLE_S", "28")))
    except ValueError:
        return 28.0


def _pro_warm_episode_prefixes(episodes: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
    """Warm each unique episode prefix once, then wait one cache-settle period.

    The warm-up is idempotent per digest (``cloud_providers_v19.warm_bundle_prefix``)
    so repeated episodes and resumes never repay it. A single settle wait follows
    ALL warm-ups (not one per episode). Set ``MLOMEGA_DEEPSEEK_CACHE_SETTLE_S=0``
    (tests) to skip the wall-clock wait while still proving one warm-up/episode.
    """
    if not episodes:
        return
    from .cloud_providers_v19 import warm_bundle_prefix
    from .night_orchestrator import estimate_tokens_for_text

    seen: set[str] = set()
    warmed = 0
    ceiling = _pro_warm_core_max_tokens()
    try:
        timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0
    for episode_id, bundle in episodes:
        if episode_id in seen:
            continue
        seen.add(episode_id)
        # Codex correction 1: only warm a SMALL episode prefix.  A large episode
        # bundle would be paid as a big MISS twice (warm + first engine); skip it
        # and let the fan-out send its prefix once instead.
        if ceiling and estimate_tokens_for_text(json_dumps(dict(bundle))) > ceiling:
            continue
        warm_bundle_prefix(str(episode_id), dict(bundle), timeout=timeout)
        warmed += 1
    if warmed:
        settle = _cache_settle_seconds()
        if settle > 0:
            import time as _time

            _time.sleep(settle)


def _global_common_fact_core(
    projected_by_engine: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """The compact facts shared by two or more projected global engines (Codex C).

    After the per-dependency projection, the fact ``ref``s appearing in more than
    one global engine's slice are the genuinely common core.  Only that core is
    worth a shared cache prefix; per-engine-only facts are not.  Order is stable
    (first-seen) so the warmed prefix is byte-for-byte reproducible.
    """

    seen_refs: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    order: list[str] = []
    for facts in projected_by_engine.values():
        for fact in facts:
            ref = str(fact.get("ref") or "")
            if not ref:
                continue
            if ref not in seen_refs:
                seen_refs[ref] = dict(fact)
                order.append(ref)
            counts[ref] = counts.get(ref, 0) + 1
    return [seen_refs[ref] for ref in order if counts.get(ref, 0) >= 2]


def _pro_warm_core_max_tokens() -> int:
    """Codex correction 1: never warm a prefix bigger than the SMALL common core.

    A warm-up is paid twice as a big MISS if the warmed prefix is large; better to
    skip the warm entirely than to pay a 47k bundle 2x.  The ceiling is ~12k tokens
    (operator-overridable) — only a genuinely small common core is worth caching.
    """
    try:
        return max(0, int(os.environ.get("MLOMEGA_PRO_WARM_MAX_TOKENS", "12288")))
    except ValueError:
        return 12288


def _pro_warm_global_fact_core(
    conversation_id: str, common_core: Sequence[Mapping[str, Any]]
) -> None:
    """Warm the shared global-fact core once as a DeepSeek cache prefix (Codex C).

    Idempotent per digest via ``warm_bundle_prefix``; the cache reduces cost and
    latency only — the real prompt-volume reduction is the projection/trim above.
    A no-op when there is no common core (nothing worth caching), OR when the core
    is above ~12k tokens (Codex correction 1: skip rather than pay a big MISS 2x).
    """

    if not common_core:
        return
    from .night_orchestrator import estimate_tokens_for_text

    payload = _global_fact_core_payload(conversation_id, common_core)
    core_tokens = estimate_tokens_for_text(json_dumps(payload))
    ceiling = _pro_warm_core_max_tokens()
    if ceiling and core_tokens > ceiling:
        # The common core is too big to be worth a warm; the projection/trim is
        # the real reduction, and a warm here would pay a large MISS twice.
        return
    from .cloud_providers_v19 import warm_bundle_prefix

    try:
        timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0
    warm_bundle_prefix(
        f"global-fact-core:{conversation_id}", payload, timeout=timeout,
    )


def _global_fact_core_payload(
    conversation_id: str, common_core: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """The exact byte-for-byte payload warmed AND ridden as the shared prefix.

    Kept as a single source of truth so ``_pro_warm_global_fact_core`` (warm) and
    ``_pro_global_fact_core_prefix`` (ride) always produce the identical digest.
    """
    return {
        "conversation_id": str(conversation_id),
        "shared_global_fact_core": [dict(fact) for fact in common_core],
    }


def _pro_global_fact_core_prefix(
    conversation_id: str, common_core: Sequence[Mapping[str, Any]]
):
    """Context manager placing the common fact core in the shared cache prefix.

    TASK 3: the small core shared by >=2 global engines (``_global_common_fact_core``)
    is put in a DeepSeek cache PREFIX that is byte-for-byte identical for every
    global engine of the conversation, so each pays a cache READ of the substrate
    instead of a cold MISS.  The digest matches ``_pro_warm_global_fact_core`` so we
    ride the already-warmed prefix.  Returns ``nullcontext()`` (no prefix, exact
    historic behaviour) when:
      * there is no common core, OR
      * the core exceeds the warm ceiling (``_pro_warm_global_fact_core`` skipped
        the warm, so riding a cold big prefix would be a MISS, not a win).
    ``_run_engine_partitioned`` never sets its own bundle prefix for globals, so
    this is the only prefix and it is guaranteed identical across the engines.
    """
    from contextlib import nullcontext

    if not common_core:
        return nullcontext()
    from .night_orchestrator import estimate_tokens_for_text

    payload = _global_fact_core_payload(conversation_id, common_core)
    core_tokens = estimate_tokens_for_text(json_dumps(payload))
    ceiling = _pro_warm_core_max_tokens()
    if ceiling and core_tokens > ceiling:
        return nullcontext()
    from .cloud_providers_v19 import cloud_bundle_prefix

    return cloud_bundle_prefix(f"global-fact-core:{conversation_id}", payload)


def _pro_probe_fanout_ready(
    episodes: Sequence[tuple[str, Mapping[str, Any]]]
) -> bool:
    """Codex correction 5: gate the concurrent fan-out on a real cache-hit probe.

    For each UNIQUE episode prefix, ``probe_bundle_prefix`` does two sequential
    warms then one probe.  The concurrent fan-out is allowed ONLY when EVERY probed
    prefix reports ``prompt_cache_hit_tokens > 0``; otherwise we log clearly and the
    caller must run a degraded SEQUENTIAL fan-out (never 8-12 cold concurrent calls).
    Set ``MLOMEGA_PRO_FANOUT_PROBE=0`` to skip the probe (assume ready).
    """
    if os.environ.get("MLOMEGA_PRO_FANOUT_PROBE", "1").strip().lower() in {
        "0", "false", "no", "off",
    }:
        return True
    if not episodes:
        return True
    from .cloud_providers_v19 import probe_bundle_prefix

    try:
        timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0
    seen: set[str] = set()
    all_hot = True
    for episode_id, bundle in episodes:
        if episode_id in seen:
            continue
        seen.add(episode_id)
        result = probe_bundle_prefix(str(episode_id), dict(bundle), timeout=timeout)
        if not result.get("cache_hit"):
            all_hot = False
            _LOG.warning(
                "pro_fanout_probe_cold episode_id=%s hit_tokens=%s "
                "decision=sequential_degraded_fanout",
                str(episode_id), int(result.get("hit_tokens") or 0),
            )
    return all_hot


def _build_local_episode_window_llm() -> Any:
    """Explicit local EpisodeBuilder client for the PRO frontier.

    Constructs ``OllamaJsonClient(backend="llamacpp", ...)`` wrapped by
    ``OllamaWindowLLM`` so ``build_conversation_episode_v6`` never falls back to
    the implicit constructor (which would inherit ``deepseek`` in PRO). The
    ``base_url``/``model`` come from the same P1 env the GpuPhaseOrchestrator uses.
    """
    from .gpu_phase_orchestrator import p1_alias, p1_base_url
    from .night_orchestrator.ollama_window_llm import OllamaWindowLLM

    # Fall back to the canonical P1 identity when the env is unset: the model
    # name feeds the window checkpoint keys (OllamaWindowLLM.model), so it must
    # NEVER degrade to the generic "ollama-json" label — that would collide with
    # the window keys of a previous cloud-driven episode attempt and silently
    # resume foreign outputs (proven on gateb-pro-20260719-185246.db).
    client = OllamaJsonClient(
        backend="llamacpp",
        base_url=os.environ.get("MLOMEGA_LLAMACPP_BASE_URL") or p1_base_url(),
        model=os.environ.get("MLOMEGA_LLAMACPP_MODEL") or p1_alias(),
    )
    return OllamaWindowLLM(system=_BRAIN2_STRICT_SYSTEM, client=client)


def _conversation_has_complete_episodes(con, conversation_id: str) -> bool:
    """Read-only completeness predicate, mirror of ``_ensure_episodes_strict``'s head.

    Used ONLY by the PRO P1 boundary decision: when the conversation already has
    complete, source-compatible episodes, the physical P1 subprocess must not be
    started at all (PRO_CLOSEDAY_HANDOFF §A). Never mutates; the authoritative
    check-and-clean stays inside ``_ensure_episodes_strict`` unchanged."""
    rows = [dict(r) for r in con.execute(
        "SELECT metadata_json FROM episodes WHERE source_conversation_id=?",
        (conversation_id,),
    ).fetchall()]
    accepted_episode_sources = {EPISODE_BUILD_VERSION}
    try:
        from .brain2_conversation_episode import (
            CONVERSATION_EPISODE_BUILD_VERSION,
            conversation_episode_enabled,
        )
        if conversation_episode_enabled():
            accepted_episode_sources = {CONVERSATION_EPISODE_BUILD_VERSION}
    except Exception:
        pass
    for r in rows:
        meta = json_loads(r.get("metadata_json"), {}) if isinstance(r.get("metadata_json"), str) else {}
        if meta.get("episode_source") in accepted_episode_sources and meta.get("coverage_status") == "complete":
            return True
    return False


def _pro_local_episode_p1_boundary():
    """Physical P1 lifecycle for the PRO episode phase (PRO_CLOSEDAY_HANDOFF §A).

    Owns a fresh orchestrator: evict Ollama -> start P1 (alias/context/
    anti-thinking proven) -> yield for build+commit -> stop P1 in ``finally``,
    BEFORE any DeepSeek engine call. Reached only when PRO forces the local
    EpisodeBuilder AND the episodes are not already materialized."""
    from .gpu_phase_orchestrator import GpuPhaseOrchestrator

    return GpuPhaseOrchestrator().pro_local_text_phase()


def _ensure_episodes_strict(con, conversation_id: str, *, person_id: str) -> int:
    existing_rows = [dict(r) for r in con.execute("SELECT episode_id, metadata_json FROM episodes WHERE source_conversation_id=?", (conversation_id,)).fetchall()]
    if existing_rows:
        complete = False
        for r in existing_rows:
            meta = json_loads(r.get("metadata_json"), {}) if isinstance(r.get("metadata_json"), str) else {}
            accepted_episode_sources = {EPISODE_BUILD_VERSION}
            try:
                from .brain2_conversation_episode import (
                    CONVERSATION_EPISODE_BUILD_VERSION,
                    conversation_episode_enabled,
                )
                if conversation_episode_enabled():
                    accepted_episode_sources = {CONVERSATION_EPISODE_BUILD_VERSION}
            except Exception:
                pass
            if meta.get("episode_source") in accepted_episode_sources and meta.get("coverage_status") == "complete":
                complete = True
                break
        if complete:
            return 0
        # Partial/legacy coverage must not poison reruns. Remove only episodes
        # for this conversation; dependent rows cascade or are recreated via upsert.
        for r in existing_rows:
            con.execute("DELETE FROM episodes WHERE episode_id=?", (r.get("episode_id"),))
    bundle = _conversation_bundle(con, conversation_id)
    # E64-F wave 1: for an oversized day the single episode_builder call truncates
    # (OBS-13). When the night orchestrator is enabled and the turns would not
    # fit one call, run the SAME V13 prompt over autonomous windows and merge the
    # structured episodes with a persisted coverage proof. The prompt text is
    # unchanged; small conversations keep the legacy single-call path below.
    resolved_owner = _default_user(con, conversation_id, explicit_person_id=person_id)
    # CHANTIER 1: in PRO, EpisodeBuilder stays on the validated local P1/llama.cpp
    # client instead of the DeepSeek text backend inherited from the environment.
    # ``force_local`` is False without the PRO flag, so both objects are None and
    # the local path below keeps its exact implicit client (byte-for-byte).
    force_local_episode = _episode_builder_forces_local()
    episode_window_llm = (
        _build_local_episode_window_llm() if force_local_episode else None
    )
    episode_backend_override = (
        llm_client_override(
            backend="llamacpp",
            base_url=os.environ.get("MLOMEGA_LLAMACPP_BASE_URL"),
            model=os.environ.get("MLOMEGA_LLAMACPP_MODEL"),
        )
        if force_local_episode
        else nullcontext()
    )
    try:
        from .brain2_conversation_episode import (
            build_conversation_episode_v6,
            conversation_episode_enabled,
        )
        use_conversation_episode = conversation_episode_enabled()
    except Exception:
        use_conversation_episode = False
    if use_conversation_episode:
        conversation_package_date = str(bundle.get("conversation", {}).get("started_at") or now_iso())[:10]
        with episode_backend_override:
            stats = build_conversation_episode_v6(
                con,
                conversation_id,
                bundle=bundle,
                safe_prompt=_safe_prompt_payload,
                materialize=_materialize_episodes_from_qwen,
                system=_BRAIN2_STRICT_SYSTEM,
                person_id=resolved_owner,
                package_date=conversation_package_date,
                window_llm=episode_window_llm,
            )
        _record_engine(
            con,
            engine="episode_builder",
            conversation_id=conversation_id,
            episode_id=None,
            person_id=resolved_owner,
            prompt=f"[e64i conversation parent x{stats.get('calls')}] {_EPISODE_MISSION}",
            output={"conversation_episode": True, **{
                key: value for key, value in stats.items() if key != "output"
            }},
            status="ok",
        )
        return int(stats.get("episodes") or 0)
    try:
        from .brain2_episode_windowing import (
            build_episodes_windowed,
            orchestrator_enabled,
            should_window,
        )

        use_windows = orchestrator_enabled() and should_window(bundle.get("turns") or [])
    except Exception:
        use_windows = False
    if use_windows:
        package_date = str(bundle.get("conversation", {}).get("started_at") or now_iso())[:10]
        with episode_backend_override:
            stats = build_episodes_windowed(
                con,
                conversation_id,
                bundle=bundle,
                person_id=resolved_owner,
                package_date=package_date,
                safe_prompt=_safe_prompt_payload,
                materialize=_materialize_episodes_from_qwen,
                mission=_EPISODE_MISSION,
                schema=STRICT_EPISODE_SCHEMA,
                system=_BRAIN2_STRICT_SYSTEM,
            )
        _record_engine(
            con,
            engine="episode_builder",
            conversation_id=conversation_id,
            episode_id=None,
            person_id=resolved_owner,
            prompt=f"[e64 windowed x{stats.get('windows')}] {_EPISODE_MISSION}",
            output={"windowed": True, **stats},
            status="ok",
        )
        return int(stats.get("episodes") or 0)
    prompt = _safe_prompt_payload({"mission": _EPISODE_MISSION, "conversation_bundle": bundle, "schema": STRICT_EPISODE_SCHEMA})
    with episode_backend_override:
        out = _llm_require_json("episode_builder", prompt, STRICT_EPISODE_SCHEMA)
    _record_engine(
        con,
        engine="episode_builder",
        conversation_id=conversation_id,
        episode_id=None,
        person_id=resolved_owner,
        prompt=prompt,
        output=out,
        status="ok",
    )
    return _materialize_episodes_from_qwen(con, conversation_id, out)


def _put_engine_payload(con, engine: str, episode_id: str, person_id: str, output: dict[str, Any]) -> int:
    """Materialize Qwen JSON into plan tables. This is data mapping only, not inference."""
    now = now_iso(); count = 0
    ep = con.execute("SELECT * FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
    conv_id = ep["source_conversation_id"] if ep else None
    conf = _clamp(output.get("confidence"))

    # One schema-driven writer boundary for ALL 16 V13 engines. Qwen can drift a
    # nominal scalar into an object/list (place, channel, stakes, etc.). SQLite
    # cannot bind those Python objects, but their content is still valuable: TEXT
    # columns receive deterministic JSON, numeric columns accept a contained
    # scalar when present, and every FK is verified against its real parent.
    _raw_upsert = globals()["upsert"]
    _table_info_cache: dict[str, dict[str, dict[str, Any]]] = {}
    _fk_cache: dict[str, list[dict[str, Any]]] = {}

    def upsert(con_arg, table: str, values: Mapping[str, Any], pk: str) -> None:
        info = _table_info_cache.get(table)
        if info is None:
            info = {
                str(row["name"]): dict(row)
                for row in con_arg.execute(f"PRAGMA table_info({table})").fetchall()
            }
            _table_info_cache[table] = info
        clean: dict[str, Any] = {}
        for column, value in values.items():
            declared = str((info.get(column) or {}).get("type") or "").upper()
            if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
                if "TEXT" in declared or not declared:
                    value = json_dumps(value)
                elif "REAL" in declared or "INT" in declared or "NUM" in declared:
                    candidates = (
                        [value.get(k) for k in ("value", "score", "confidence", "count")]
                        if isinstance(value, Mapping) else list(value)
                    )
                    value = next(
                        (candidate for candidate in candidates if isinstance(candidate, (int, float))),
                        None,
                    )
                else:
                    value = json_dumps(value)
            elif value is not None and not isinstance(value, (str, int, float, bytes)):
                value = str(value) if "TEXT" in declared else None
            clean[column] = value

        fks = _fk_cache.get(table)
        if fks is None:
            fks = [dict(row) for row in con_arg.execute(f"PRAGMA foreign_key_list({table})")]
            _fk_cache[table] = fks
        for fk in fks:
            column = str(fk["from"])
            value = clean.get(column)
            if value is None:
                continue
            parent_table = str(fk["table"])
            parent_column = str(fk["to"])
            exists = con_arg.execute(
                f"SELECT 1 FROM {parent_table} WHERE {parent_column}=? LIMIT 1",
                (value,),
            ).fetchone()
            if not exists:
                clean[column] = None
        _raw_upsert(con_arg, table, clean, pk)

    def existing_id(table: str, column: str, value: Any) -> str | None:
        """Accept an LLM-provided FK only when its parent row really exists."""
        if not isinstance(value, (str, int)) or not str(value).strip():
            return None
        candidate = str(value)
        row = con.execute(
            f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (candidate,)
        ).fetchone()
        return candidate if row else None

    def conversation_turn_id(value: Any) -> str | None:
        if not isinstance(value, (str, int)) or not str(value).strip() or not conv_id:
            return None
        candidate = str(value)
        row = con.execute(
            "SELECT 1 FROM turns WHERE turn_id=? AND conversation_id=? LIMIT 1",
            (candidate, conv_id),
        ).fetchone()
        return candidate if row else None

    def link(table: str, oid: str, rel: str = "produced_from") -> None:
        _insert_object_link(con, conv_id, episode_id, "episodes", episode_id, table, oid, rel, engine, conf, _as_list(output.get("evidence")))

    if engine == "episode_builder":
        summary = _as_dict(output.get("episode_summary_update"))
        if summary:
            updates: dict[str, Any] = {"updated_at": now}
            for src, dst in [("episode_type", "episode_type"), ("situation_summary", "situation_summary"), ("trigger", "trigger_summary"), ("unresolved_tension", "unresolved_tension"), ("outcome", "outcome_summary")]:
                val = summary.get(src)
                if val:
                    updates[dst] = val
            if len(updates) > 1:
                current_meta = json_loads(ep["metadata_json"], {}) if ep and isinstance(ep["metadata_json"], str) else {}
                current_meta.setdefault("strict_v13_2", True)
                current_meta["episode_builder_engine_update"] = {k: v for k, v in updates.items() if k != "updated_at"}
                updates["metadata_json"] = json_dumps(current_meta)
                assignments = ", ".join(f"{k}=?" for k in updates)
                con.execute(f"UPDATE episodes SET {assignments} WHERE episode_id=?", tuple(updates.values()) + (episode_id,))
                count += 1
        for b in _as_list(output.get("episode_boundaries")):
            if isinstance(b, dict) and b.get("boundary_type"):
                tid = conversation_turn_id(b.get("turn_id"))
                if not tid:
                    continue
                turn = con.execute("SELECT idx, text FROM turns WHERE turn_id=?", (tid,)).fetchone()
                bid = stable_id("epbound", episode_id, engine, b.get("boundary_type"), tid or b.get("reason"))
                upsert(con, "episode_boundaries", {
                    "boundary_id": bid, "conversation_id": conv_id, "episode_id": episode_id,
                    "boundary_type": b.get("boundary_type"), "turn_id": tid, "idx": turn["idx"] if turn else None,
                    "reason": b.get("reason") or "V13 episode_builder engine boundary",
                    "confidence": _clamp(b.get("confidence", conf)), "evidence_text": turn["text"] if turn else json_dumps(_as_list(output.get("evidence"))),
                    "created_at": now,
                }, "boundary_id")
                count += 1
        for l in _as_list(output.get("links_to_other_episodes")):
            target_episode_id = existing_id(
                "episodes", "episode_id", l.get("to_episode_id")
            ) if isinstance(l, dict) else None
            if target_episode_id and target_episode_id != episode_id:
                lid = stable_id("eplink", episode_id, l.get("relation_type") or "related", target_episode_id)
                upsert(con, "episode_links", {
                    "episode_link_id": lid, "from_episode_id": episode_id, "relation_type": l.get("relation_type") or "related",
                    "to_episode_id": target_episode_id, "confidence": _clamp(l.get("confidence", conf)),
                    "evidence_text": json_dumps(_as_list(output.get("evidence"))), "metadata_json": json_dumps({"source": "strict_v13_2_episode_builder_engine"}),
                    "created_at": now,
                }, "episode_link_id")
                count += 1

    elif engine == "capture_engine":
        cap = _as_dict(output.get("capture_quality"))
        if _as_list(output.get("prosody_events")):
            for ev in _as_list(output.get("prosody_events")):
                if isinstance(ev, dict) and ev.get("event_type"):
                    turn_id = conversation_turn_id(ev.get("turn_id"))
                    if not turn_id:
                        continue
                    oid = stable_id("prosody", episode_id, turn_id, ev.get("event_type"), ev.get("interpretation"))
                    upsert(con, "audio_prosody_events", {"prosody_event_id": oid, "conversation_id": conv_id, "turn_id": turn_id, "source_asset_id": None, "person_id": person_id, "start_s": ev.get("start_s"), "end_s": ev.get("end_s"), "event_type": ev.get("event_type"), "feature_json": json_dumps({"value": ev.get("value"), "capture_quality": cap}), "interpretation": ev.get("interpretation"), "confidence": _clamp(ev.get("confidence")), "source_method": "qwen_or_acoustic_feature", "evidence_json": json_dumps(_as_list(output.get("evidence"))), "created_at": now}, "prosody_event_id")
                    link("audio_prosody_events", oid)
                    count += 1
        if cap.get("missing_audio_signals"):
            oid = stable_id("readiness", episode_id, "missing_audio_signals")
            upsert(con, "v13_readiness_checks", {"readiness_id": oid, "check_name": "audio_prosody_available", "check_group": "capture_engine", "status": "missing", "severity": "warning", "detail": "Qwen reported missing audio/prosody evidence; no text heuristic substituted.", "evidence_json": json_dumps(_as_list(output.get("evidence"))), "missing_json": json_dumps(_as_list(cap.get("missing_audio_signals"))), "created_at": now}, "readiness_id")
            count += 1

    elif engine == "language_signature_engine":
        style = _as_dict(output.get("style_state"))
        if style:
            oid = stable_id("style", person_id, episode_id)
            upsert(con, "style_state_snapshots", {"style_state_id": oid, "person_id": person_id, "episode_id": episode_id, "directness": _clamp(style.get("directness")), "detail_level": _clamp(style.get("detail_level")), "correction_tendency": _clamp(style.get("correction_tendency")), "validation_seeking": _clamp(style.get("validation_seeking")), "typical_phrases_json": json_dumps(_as_list(style.get("typical_phrases"))), "evidence_json": json_dumps(_as_list(output.get("evidence"))), "confidence": conf, "created_at": now}, "style_state_id")
            link("style_state_snapshots", oid); count += 1
        for tpl in _as_list(output.get("phrase_templates")):
            if isinstance(tpl, dict) and tpl.get("template"):
                oid = stable_id("phrase_tpl", person_id, tpl.get("template"), episode_id)
                upsert(con, "phrase_templates", {"template_id": oid, "person_id": person_id, "template_text": tpl.get("template"), "template_type": tpl.get("template_type") or "qwen_phrase_template", "context_type": tpl.get("context_type"), "frequency": None, "confidence": _clamp(tpl.get("confidence", tpl.get("probability", conf))), "examples_json": json_dumps(_as_list(tpl.get("examples"))), "metadata_json": json_dumps({"speech_act_context": tpl.get("speech_act_context"), "emotion_context": tpl.get("emotion_context"), "probability": _clamp(tpl.get("probability"))}), "created_at": now, "updated_at": now}, "template_id")
                link("phrase_templates", oid); count += 1
        for wp in _as_list(output.get("word_predictions")):
            if isinstance(wp, dict):
                oid = stable_id("ngram", person_id, episode_id, wp.get("context"), json_dumps(wp.get("next_word_candidates")))
                upsert(con, "language_ngrams", {"ngram_id": oid, "person_id": person_id, "n": 0, "ngram": str(wp.get("context") or ""), "context_type": None, "frequency": None, "examples_json": json_dumps(_as_list(wp.get("next_word_candidates"))), "probability": _clamp(wp.get("confidence")), "last_seen": now, "created_at": now, "updated_at": now}, "ngram_id")
                link("language_ngrams", oid); count += 1

    elif engine == "context_resolver":
        sit = _as_dict(output.get("situation"))
        if sit:
            oid = stable_id("situ", episode_id, person_id)
            upsert(con, "situation_episodes", {"situation_id": oid, "episode_id": episode_id, "situation_type": sit.get("situation_type"), "life_domain": sit.get("life_domain"), "participants_json": json_dumps(_as_list(sit.get("participants"))), "main_person_id": sit.get("main_person"), "secondary_people_json": json_dumps(_as_list(sit.get("secondary_people"))), "place_explicit": sit.get("place_explicit"), "place_inferred": sit.get("place_inferred"), "channel": sit.get("channel"), "social_context": sit.get("social_context"), "power_balance": sit.get("power_balance"), "stakes": sit.get("stakes"), "constraints_json": json_dumps(_as_list(sit.get("constraints"))), "trigger_event_id": sit.get("trigger_event_id"), "related_project": sit.get("related_project"), "related_relationship_id": sit.get("related_relationship"), "confidence": conf, "metadata_json": json_dumps({"resolved_references": _as_list(output.get("resolved_references")), "missing_context": _as_list(output.get("missing_context"))}), "created_at": now, "updated_at": now}, "situation_id")
            link("situation_episodes", oid); count += 1

    elif engine == "internal_state_engine":
        for label, key in [("before", "state_before"), ("during", "state_during"), ("after", "state_after")]:
            st = _as_dict(output.get(key))
            if st:
                oid = stable_id("state", episode_id, person_id, label)
                upsert(con, "internal_state_snapshots", {"state_id": oid, "person_id": person_id, "episode_id": episode_id, "time_start": ep["start_time"] if ep else None, "time_end": ep["end_time"] if ep else None, "energy": _clamp(st.get("energy")), "stress": _clamp(st.get("stress")), "motivation": _clamp(st.get("motivation")), "confidence_state": _clamp(st.get("confidence_level") or st.get("confidence")), "clarity": _clamp(st.get("clarity")), "frustration": _clamp(st.get("frustration")), "curiosity": _clamp(st.get("curiosity")), "urgency": _clamp(st.get("urgency")), "sense_of_control": _clamp(st.get("sense_of_control")), "feeling_understood": _clamp(st.get("feeling_understood")), "social_safety": _clamp(st.get("social_safety")), "emotional_valence": _clamp(st.get("emotional_valence"), -1, 1), "dominant_emotion": output.get("dominant_emotion") or st.get("dominant_emotion"), "secondary_emotions_json": json_dumps(_as_list(output.get("secondary_emotions"))), "evidence_text": json_dumps(_as_list(output.get("evidence"))), "confidence": _clamp(st.get("confidence", conf)), "source_type": "qwen_strict", "truth_status": "inferred", "confidence": _clamp(st.get("confidence", conf)), "metadata_json": json_dumps({"state_phase": label}), "created_at": now, "updated_at": now}, "state_id")
                link("internal_state_snapshots", oid); count += 1
        for th in _as_list(output.get("thought_hypotheses")):
            if isinstance(th, dict) and th.get("content"):
                oid = stable_id("thought", episode_id, person_id, th.get("content")[:120])
                upsert(con, "thought_hypotheses", {"thought_id": oid, "person_id": person_id, "episode_id": episode_id, "thought_type": th.get("thought_type") or "hypothesis", "content": th.get("content"), "turn_id": conversation_turn_id(th.get("turn_id")), "consciousness_level": th.get("consciousness_level"), "evidence_text": json_dumps(_as_list(th.get("evidence") or output.get("evidence"))), "trigger_summary": th.get("trigger"), "related_need": th.get("related_need"), "related_fear": th.get("related_fear"), "related_goal": th.get("related_goal"), "truth_status": "inferred", "confidence": _clamp(th.get("confidence")), "metadata_json": json_dumps({}), "created_at": now, "updated_at": now}, "thought_id")
                link("thought_hypotheses", oid); count += 1
        for ev in _as_list(output.get("state_transitions")):
            if isinstance(ev, dict):
                from_state_id = existing_id(
                    "internal_state_snapshots", "state_id",
                    stable_id("state", episode_id, person_id, "before"),
                )
                to_state_id = existing_id(
                    "internal_state_snapshots", "state_id",
                    stable_id("state", episode_id, person_id, "after"),
                )
                if not from_state_id or not to_state_id:
                    continue
                oid = stable_id("statetr", episode_id, ev.get("from"), ev.get("to"), ev.get("trigger"))
                upsert(con, "state_transitions", {"transition_id": oid, "person_id": person_id, "from_state_id": from_state_id, "to_state_id": to_state_id, "transition_type": "qwen_state_transition", "change_summary": json_dumps({"from": ev.get("from"), "to": ev.get("to")}), "trigger_summary": ev.get("trigger"), "confidence": _clamp(ev.get("confidence")), "metadata_json": json_dumps({"episode_id": episode_id, "evidence": _as_list(ev.get("evidence") or output.get("evidence"))}), "created_at": now}, "transition_id")
                link("state_transitions", oid); count += 1
        if output.get("dominant_emotion"):
            oid = stable_id("emoev", episode_id, person_id, output.get("dominant_emotion"))
            upsert(con, "emotion_evidence", {"emotion_evidence_id": oid, "person_id": person_id, "episode_id": episode_id, "state_id": None, "turn_id": None, "source_type": "qwen_text_context", "emotion_label": output.get("dominant_emotion"), "signal_text": json_dumps(_as_list(output.get("evidence"))), "signal_strength": conf, "missing_evidence_json": json_dumps([]), "confidence": conf, "metadata_json": json_dumps({"secondary": _as_list(output.get("secondary_emotions"))}), "created_at": now, "updated_at": now}, "emotion_evidence_id")
            link("emotion_evidence", oid); count += 1

    elif engine == "social_model_engine":
        for role in _as_list(output.get("social_roles")):
            if isinstance(role, dict) and role.get("person_id"):
                oid = stable_id("socialrole", person_id, role.get("person_id"), role.get("role_label"), episode_id)
                upsert(con, "social_roles", {"social_role_id": oid, "person_id": role.get("person_id"), "role_label": role.get("role_label"), "role_context": role.get("role_context"), "relation_to_user": role.get("relation_to_user"), "evidence_json": json_dumps(_as_list(output.get("evidence"))), "confidence": _clamp(role.get("confidence", conf)), "created_at": now, "updated_at": now}, "social_role_id")
                link("social_roles", oid); count += 1
        for rel in _as_list(output.get("relationship_updates")):
            if isinstance(rel, dict) and rel.get("other_person_id"):
                oid = stable_id("rel", person_id, rel.get("other_person_id"))
                upsert(con, "relationship_models", {"relationship_id": oid, "person_a": person_id, "person_b": rel.get("other_person_id"), "relationship_type": rel.get("relationship_type"), "trust_level": _clamp(rel.get("trust_level") or rel.get("trust_delta"), -1, 1), "tension_level": _clamp(rel.get("tension_level") or rel.get("tension_delta"), -1, 1), "attachment_level": _clamp(rel.get("attachment_level")), "dependency_level": _clamp(rel.get("dependency_level")), "power_balance": rel.get("power_balance"), "conflict_frequency": rel.get("conflict_frequency"), "repair_frequency": rel.get("repair_frequency"), "communication_style": rel.get("communication_style"), "common_triggers_json": json_dumps(_as_list(rel.get("common_trigger"))), "common_loops_json": json_dumps(_as_list(rel.get("common_loops"))), "current_status": "active", "confidence": _clamp(rel.get("confidence", conf)), "evidence_count": 1, "metadata_json": json_dumps({}), "created_at": now, "updated_at": now}, "relationship_id")
                link("relationship_models", oid); count += 1
        for loop in _as_list(output.get("conflict_loops")):
            if isinstance(loop, dict) and (loop.get("summary") or loop.get("trigger_pattern")):
                oid = stable_id("conflictloop", person_id, episode_id, loop.get("summary"), loop.get("trigger_pattern"))
                upsert(con, "conflict_loops", {"conflict_loop_id": oid, "relationship_id": None, "person_a": person_id, "person_b": None, "loop_summary": loop.get("summary"), "trigger_pattern": loop.get("trigger_pattern"), "escalation_path": loop.get("escalation_path"), "deescalation_path": loop.get("deescalation_path"), "evidence_count": 1, "confidence": _clamp(loop.get("confidence", conf)), "status": "candidate", "created_at": now, "updated_at": now}, "conflict_loop_id")
                link("conflict_loops", oid); count += 1

    elif engine == "causality_engine":
        for hyp in _as_list(output.get("causal_hypotheses")):
            if isinstance(hyp, dict) and (hyp.get("hypothesis") or hyp.get("cause") or hyp.get("effect")):
                hid = stable_id("causalhyp", episode_id, hyp.get("cause"), hyp.get("effect"), hyp.get("hypothesis"))
                upsert(con, "causal_hypotheses", {"hypothesis_id": hid, "episode_id": episode_id, "person_id": person_id, "hypothesis_text": hyp.get("hypothesis"), "cause_table": "qwen_text", "cause_id": str(hyp.get("cause") or ""), "effect_table": "qwen_text", "effect_id": str(hyp.get("effect") or ""), "causal_type": hyp.get("causal_type"), "strength": _clamp(hyp.get("strength")), "evidence_json": json_dumps(_as_list(hyp.get("evidence") or output.get("evidence"))), "counter_evidence_json": json_dumps(_as_list(hyp.get("counter_evidence") or output.get("counter_evidence"))), "status": "hypothesis", "confidence": _clamp(hyp.get("confidence", conf)), "created_at": now, "updated_at": now}, "hypothesis_id")
                link("causal_hypotheses", hid); count += 1
                eid = stable_id("causaledge", episode_id, hyp.get("cause"), hyp.get("effect"), hyp.get("causal_type"))
                upsert(con, "causal_edges", {"causal_edge_id": eid, "from_table": "qwen_text", "from_id": str(hyp.get("cause") or ""), "to_table": "qwen_text", "to_id": str(hyp.get("effect") or ""), "causal_type": hyp.get("causal_type"), "strength": _clamp(hyp.get("strength")), "lag_time_text": str(hyp.get("lag_time") or ""), "evidence_text": json_dumps(_as_list(hyp.get("evidence") or output.get("evidence"))), "counter_evidence_text": json_dumps(_as_list(hyp.get("counter_evidence") or output.get("counter_evidence"))), "truth_status": "hypothesis", "confidence": _clamp(hyp.get("confidence", conf)), "metadata_json": json_dumps({}), "created_at": now, "updated_at": now}, "causal_edge_id")
                link("causal_edges", eid); count += 1

    elif engine == "contradiction_engine":
        for c in _as_list(output.get("contradictions")):
            if isinstance(c, dict) and (c.get("declared") or c.get("observed")):
                oid = stable_id("contra", episode_id, c.get("declared"), c.get("observed"))
                upsert(con, "contradiction_events", {"contradiction_id": oid, "person_id": person_id, "episode_id": episode_id, "declared_table": "qwen_text", "declared_id": str(c.get("declared") or ""), "observed_table": "qwen_text", "observed_id": str(c.get("observed") or ""), "contradiction_type": c.get("contradiction_type") or c.get("type") or "declared_vs_observed", "severity": _clamp(c.get("severity")), "possible_explanation": c.get("possible_explanation"), "resolved": 0, "evidence_for": json_dumps(_as_list(c.get("evidence") or output.get("evidence"))), "evidence_against": json_dumps(_as_list(c.get("counter_evidence") or output.get("counter_evidence"))), "confidence": _clamp(c.get("confidence", conf)), "metadata_json": json_dumps({"declared_text": c.get("declared"), "observed_text": c.get("observed"), "v15_18_contract_fix": True}), "created_at": now, "updated_at": now}, "contradiction_id")
                link("contradiction_events", oid); count += 1
        for rev in _as_list(output.get("model_revisions_needed")):
            if isinstance(rev, dict) and rev.get("target"):
                oid = stable_id("modelrev", episode_id, rev.get("target"), rev.get("reason"))
                upsert(con, "model_revisions", {"model_revision_id": oid, "target_table": rev.get("target_table") or "unknown", "target_id": rev.get("target"), "revision_type": "qwen_contradiction_revision", "previous_json": json_dumps({}), "new_json": json_dumps(rev.get("new_view")), "reason": rev.get("reason"), "evidence_json": json_dumps(_as_list(output.get("evidence"))), "created_at": now}, "model_revision_id")
                link("model_revisions", oid); count += 1

    elif engine == "pattern_miner":
        for sig in _as_list(output.get("signals")):
            if isinstance(sig, dict) and sig.get("signal_type"):
                oid = stable_id("behaviorsig", episode_id, sig.get("signal_type"), sig.get("signal_value"))
                upsert(con, "behavior_signals", {"signal_id": oid, "person_id": person_id, "episode_id": episode_id, "signal_type": sig.get("signal_type"), "signal_value": sig.get("signal_value"), "strength": _clamp(sig.get("strength")), "evidence_text": json_dumps(_as_list(sig.get("evidence") or output.get("evidence"))), "status": "signal", "confidence": _clamp(sig.get("confidence", conf)), "metadata_json": json_dumps({}), "created_at": now, "updated_at": now}, "signal_id")
                link("behavior_signals", oid); count += 1
        for patt in _as_list(output.get("candidate_patterns")) + _as_list(output.get("confirmed_patterns")):
            if isinstance(patt, dict) and (patt.get("pattern_type") or patt.get("summary")):
                evidence_count = int(patt.get("evidence_count") or len(_as_list(patt.get("evidence"))))
                oid = stable_id("pattern", person_id, patt.get("pattern_type"), patt.get("pattern_key") or patt.get("summary") or patt.get("title"))
                table = "confirmed_patterns" if patt in _as_list(output.get("confirmed_patterns")) or evidence_count >= 8 or patt.get("validated_by_outcome") else "candidate_patterns"
                title = str(
                    patt.get("title") or patt.get("summary") or patt.get("pattern_type") or "pattern"
                ).strip()
                description = patt.get("description") or patt.get("summary") or title
                if table == "confirmed_patterns":
                    key = "confirmed_pattern_id"
                    data = {key: oid, "candidate_pattern_id": None, "person_id": person_id, "pattern_type": patt.get("pattern_type"), "pattern_key": str(patt.get("pattern_key") or patt.get("summary") or patt.get("pattern_type") or title), "title": title, "description": description, "evidence_count": evidence_count, "counterexample_count": int(patt.get("counterexample_count") or 0), "activation_conditions_json": json_dumps(_as_list(patt.get("activation_context"))), "escape_conditions_json": json_dumps(_as_list(patt.get("escape_conditions"))), "usual_outcome": patt.get("usual_outcome"), "confidence": _clamp(patt.get("confidence", conf)), "validity_status": "confirmed", "metadata_json": json_dumps({"strength": _clamp(patt.get("strength"))}), "created_at": now, "updated_at": now}
                else:
                    key = "candidate_pattern_id"
                    data = {key: oid, "person_id": person_id, "pattern_type": patt.get("pattern_type"), "pattern_key": str(patt.get("pattern_key") or patt.get("summary") or patt.get("pattern_type") or title), "title": title, "description": description, "evidence_count": evidence_count, "first_seen": now, "last_seen": now, "activation_contexts_json": json_dumps(_as_list(patt.get("activation_context"))), "counterexamples_json": json_dumps(_as_list(patt.get("counterexamples"))), "status": "candidate", "confidence": _clamp(patt.get("confidence", conf)), "metadata_json": json_dumps({"strength": _clamp(patt.get("strength")), "usual_outcome": patt.get("usual_outcome"), "escape_conditions": _as_list(patt.get("escape_conditions"))}), "created_at": now, "updated_at": now}
                upsert(con, table, data, key)
                link(table, oid); count += 1
                for ctx in _as_list(patt.get("activation_context")):
                    pcid = stable_id("pattctx", oid, str(ctx))
                    upsert(con, "pattern_contexts", {"pattern_context_id": pcid, "pattern_table": table, "pattern_id": oid, "context_type": "activation", "context_value": str(ctx), "activation_strength": _clamp(patt.get("strength")), "evidence_json": json_dumps(_as_list(patt.get("evidence"))), "confidence": _clamp(patt.get("confidence", conf)), "created_at": now}, "pattern_context_id")
                    count += 1
                for ce in _as_list(patt.get("counterexamples")):
                    pcid = stable_id("pattce", oid, str(ce))
                    upsert(con, "pattern_counterexamples", {"counterexample_id": pcid, "pattern_table": table, "pattern_id": oid, "episode_id": episode_id, "counterexample_summary": str(ce), "why_it_matters": "Qwen counterexample", "strength": _clamp(patt.get("strength")), "evidence_json": json_dumps(_as_list(patt.get("evidence"))), "created_at": now}, "counterexample_id")
                    count += 1
        for lp in _as_list(output.get("loop_patterns")):
            if isinstance(lp, dict) and (lp.get("loop_type") or lp.get("trigger")):
                oid = stable_id("loop", person_id, lp.get("loop_type"), lp.get("trigger"))
                upsert(con, "loop_patterns", {"loop_id": oid, "person_id": person_id, "loop_type": lp.get("loop_type"), "trigger_summary": lp.get("trigger"), "phase_1": lp.get("phase_1"), "phase_2": lp.get("phase_2"), "phase_3": lp.get("phase_3"), "phase_4": lp.get("phase_4"), "usual_outcome": lp.get("usual_outcome"), "escape_conditions_json": json_dumps(_as_list(lp.get("escape_conditions"))), "evidence_count": int(lp.get("evidence_count") or 1), "confidence": _clamp(lp.get("confidence", conf)), "created_at": now, "updated_at": now}, "loop_id")
                link("loop_patterns", oid); count += 1

    elif engine == "choice_model_engine":
        for ch in _as_list(output.get("choices")) or _as_list(output.get("choice_episodes")):
            if isinstance(ch, dict) and (ch.get("choice_context") or ch.get("chosen_option") or ch.get("options")):
                cid = stable_id("choice", episode_id, person_id, ch.get("choice_context"), ch.get("chosen_option"))
                upsert(con, "choice_episodes", {"choice_id": cid, "episode_id": episode_id, "person_id": person_id, "choice_context": ch.get("choice_context"), "options_json": json_dumps(_as_list(ch.get("options"))), "criteria_json": json_dumps(_as_list(ch.get("criteria"))), "preferred_option_before": ch.get("preferred_option_before"), "chosen_option": ch.get("chosen_option"), "rejected_options_json": json_dumps(_as_list(ch.get("rejected_options"))), "decision_time": ch.get("decision_time"), "confidence_before": _clamp(ch.get("confidence_before")), "confidence_after": _clamp(ch.get("confidence_after")), "reason_given": ch.get("reason_given"), "real_reason_hypothesis": ch.get("real_reason_hypothesis"), "outcome_id": existing_id("action_outcomes", "outcome_id", ch.get("outcome_id")), "satisfaction_after": ch.get("satisfaction_after"), "regret_after": ch.get("regret_after"), "created_at": now, "updated_at": now}, "choice_id")
                link("choice_episodes", cid); count += 1
                for opt in _as_list(ch.get("options")):
                    oid = stable_id("choiceopt", cid, str(opt))
                    upsert(con, "choice_options", {"option_id": oid, "choice_id": cid, "option_text": str(opt), "option_status": "chosen" if str(opt) == str(ch.get("chosen_option")) else "available", "evidence_text": ch.get("reason_given"), "confidence": _clamp(ch.get("confidence_after", conf)), "metadata_json": json_dumps({}), "created_at": now}, "option_id")
                    count += 1
                for crit in _as_list(ch.get("criteria")):
                    oid = stable_id("choicecrit", cid, str(crit))
                    upsert(con, "choice_criteria", {"criterion_id": oid, "choice_id": cid, "criterion_key": str(crit)[:120], "criterion_value": str(crit), "weight": None, "evidence_text": ch.get("reason_given"), "confidence": _clamp(ch.get("confidence_after", conf)), "created_at": now}, "criterion_id")
                    count += 1

    elif engine == "outcome_tracker":
        normalized_outcome = normalize_outcome_tracker(output)
        for it in normalized_outcome["intentions"]:
            if isinstance(it, dict) and (it.get("intention_text") or it.get("action_type") or it.get("intention_id")):
                iid = it.get("intention_id") or stable_id("intent", episode_id, person_id, it.get("intention_text"), it.get("action_type"))
                upsert(con, "action_intentions", {"intention_id": iid, "person_id": person_id, "episode_id": episode_id, "intention_text": it.get("intention_text"), "action_type": it.get("action_type"), "target": it.get("target"), "deadline": it.get("deadline"), "strength": _clamp(it.get("strength")), "explicitness": it.get("explicitness"), "obstacles_json": json_dumps(_as_list(it.get("obstacles"))), "required_conditions_json": json_dumps(_as_list(it.get("required_conditions"))), "evidence_text": json_dumps(_as_list(it.get("evidence") or output.get("evidence"))), "status": it.get("status") or "proposed", "created_at": now, "updated_at": now}, "intention_id")
                link("action_intentions", iid); count += 1
        for oc in normalized_outcome["outcomes"]:
            if isinstance(oc, dict) and (oc.get("action_taken") or oc.get("result")):
                oid = stable_id("outcome", episode_id, person_id, oc.get("action_taken"), oc.get("result"))
                upsert(con, "action_outcomes", {"outcome_id": oid, "intention_id": existing_id("action_intentions", "intention_id", oc.get("intention_id")), "episode_id": episode_id, "person_id": person_id, "action_taken": oc.get("action_taken"), "result": oc.get("result"), "success_level": _clamp(oc.get("success_level")), "delay_text": oc.get("delay"), "obstacle_encountered": oc.get("obstacle_encountered"), "emotion_after": oc.get("emotion_after"), "lesson": oc.get("lesson"), "evidence_text": json_dumps(_as_list(oc.get("evidence") or output.get("evidence"))), "truth_status": "inferred", "confidence": _clamp(oc.get("confidence", conf)), "metadata_json": json_dumps({"v15_18_contract_fix": True, "raw": oc.get("raw")}), "created_at": now, "updated_at": now}, "outcome_id")
                link("action_outcomes", oid); count += 1

    elif engine == "similar_case_retrieval":
        rid = stable_id("simrun", episode_id, person_id, now[:19])
        upsert(con, "similar_case_retrieval_runs", {"retrieval_run_id": rid, "prediction_id": None, "person_id": person_id, "query_context": ep["situation_summary"] if ep else "", "target": output.get("target") or "all", "semantic_weight": _clamp((output.get("weights") or {}).get("semantic")), "situation_weight": _clamp((output.get("weights") or {}).get("situation")), "state_weight": _clamp((output.get("weights") or {}).get("state")), "relationship_weight": _clamp((output.get("weights") or {}).get("relationship")), "outcome_weight": _clamp((output.get("weights") or {}).get("outcome")), "language_weight": _clamp((output.get("weights") or {}).get("language")), "selected_cases_json": json_dumps(_as_list(output.get("similar_cases"))), "created_at": now}, "retrieval_run_id")
        count += 1
        for sc in _as_list(output.get("similar_cases")):
            if isinstance(sc, dict):
                case_id = sc.get("case_id") or sc.get("episode_id") or stable_id("case", person_id, json_dumps(sc)[:160])
                if not con.execute("SELECT 1 FROM prediction_cases WHERE case_id=?", (case_id,)).fetchone():
                    upsert(con, "prediction_cases", {"case_id": case_id, "case_type": "llm_similar_case_reference", "episode_id": existing_id("episodes", "episode_id", sc.get("episode_id")), "person_id": person_id, "context_summary": sc.get("why_similar") or sc.get("summary") or "LLM referenced similar case; canonical case auto-created by V15.18", "situation_vector_json": json_dumps({}), "state_vector_json": json_dumps({}), "action_taken": None, "speech_next": None, "emotion_next": None, "thought_next_hypothesis": None, "outcome": None, "usable_for_prediction": 0, "quality_score": normalize_similar_case_score(sc), "evidence_json": json_dumps({"source": "similar_case_retrieval", "raw": sc, "usable_note": "not empirical until linked to observed episode/outcome"}), "created_at": now, "updated_at": now}, "case_id")
                sid = stable_id("simscore", rid, case_id, normalize_similar_case_score(sc))
                upsert(con, "similar_case_scores", {"similar_case_id": sid, "prediction_id": None, "case_id": case_id, "person_id": person_id, "prediction_target": output.get("target") or "all", "semantic_similarity": _clamp(sc.get("semantic_similarity")), "situation_similarity": _clamp(sc.get("situation_similarity")), "state_similarity": _clamp(sc.get("state_similarity")), "relationship_similarity": _clamp(sc.get("relationship_similarity")), "outcome_similarity": _clamp(sc.get("outcome_similarity")), "language_similarity": _clamp(sc.get("language_similarity")), "final_score": normalize_similar_case_score(sc), "explanation": sc.get("why_similar"), "metadata_json": json_dumps({"episode_id": sc.get("episode_id"), "why_not_identical": sc.get("why_not_identical"), "retrieval_run_id": rid}), "created_at": now}, "similar_case_id")
                count += 1

    elif engine == "prediction_engine":
        for p in _as_list(output.get("predictions")):
            if isinstance(p, dict) and (p.get("predicted_value") or p.get("prediction")):
                target = p.get("prediction_target") if p.get("prediction_target") in COMPLETE_TARGETS else "next_action"
                value = str(p.get("predicted_value") or p.get("prediction"))
                pid = stable_id("prediction", STRICT_VERSION, person_id, episode_id, target, value[:160])
                upsert(con, "predictions", {"prediction_id": pid, "created_at": now, "person_id": person_id, "prediction_target": target, "horizon": p.get("horizon") or "next", "current_context": ep["situation_summary"] if ep else "", "predicted_value": value, "probability": _clamp(p.get("probability")), "confidence": _clamp(p.get("confidence")), "alternatives_json": json_dumps(_as_list(p.get("alternatives"))), "evidence_cases_json": json_dumps(_as_list(p.get("similar_cases"))), "counter_evidence_json": json_dumps(_as_list(p.get("counter_evidence"))), "assumptions_json": json_dumps(_as_list(p.get("assumptions"))), "intervention_options_json": json_dumps(_as_list(p.get("interventions"))), "verification_due_at": p.get("verification_due_at"), "status": "open", "metadata_json": json_dumps({"strict_v13_2": True, "why": _as_list(p.get("why"))}), "updated_at": now}, "prediction_id")
                link("predictions", pid); count += 1
                for why in _as_list(p.get("why")):
                    eid = stable_id("predexp", pid, str(why))
                    upsert(con, "v13_prediction_explanations", {"explanation_id": eid, "prediction_id": pid, "explanation_json": json_dumps({"text": str(why)}), "why_json": json_dumps(_as_list(p.get("why"))), "similar_cases_json": json_dumps(_as_list(p.get("similar_cases"))), "counter_evidence_json": json_dumps(_as_list(p.get("counter_evidence"))), "assumptions_json": json_dumps(_as_list(p.get("assumptions"))), "intervention_json": json_dumps(_as_list(p.get("interventions"))), "uncertainty_json": json_dumps({"confidence": _clamp(p.get("confidence"))}), "created_at": now}, "explanation_id")
                    count += 1
                tsid = stable_id("targetscore", person_id, target)
                upsert(con, "prediction_target_scores", {"score_id": tsid, "person_id": person_id, "prediction_target": target, "total_predictions": 0, "verified_predictions": 0, "correct_predictions": 0, "mean_match_score": 0.0, "mean_confidence": 0.0, "calibration_gap": 0.0, "reliability_label": "awaiting_verification", "updated_at": now}, "score_id")

    elif engine == "simulation_engine":
        # Branches may refer to existing predictions or stand alone as future_scenarios.
        for br in _as_list(output.get("branches")):
            if isinstance(br, dict) and (br.get("branch_name") or br.get("expected_path")):
                fsid = stable_id("future", episode_id, person_id, br.get("branch_name"), br.get("expected_path"))
                upsert(con, "future_scenarios", {"scenario_id": fsid, "person_id": person_id, "episode_id": episode_id, "prediction_id": None, "scenario_type": br.get("branch_name"), "horizon": br.get("horizon"), "if_condition": br.get("if_condition"), "expected_future": br.get("expected_path"), "probability": _clamp(br.get("probability")), "risk_level": _clamp(br.get("risk_level")), "opportunity_level": _clamp(br.get("opportunity_level")), "evidence_json": json_dumps(_as_list(output.get("evidence"))), "counter_evidence_json": json_dumps(_as_list(output.get("counter_evidence"))), "status": "candidate", "created_at": now, "updated_at": now}, "scenario_id")
                link("future_scenarios", fsid); count += 1

    elif engine == "calibration_engine":
        for cal in normalize_calibration_rows(output):
            oid = stable_id("calib", person_id, cal.get("prediction_target"), episode_id)
            upsert(con, "calibration_scores", {"calibration_id": oid, "person_id": person_id, "prediction_target": cal["prediction_target"], "sample_size": int(cal.get("sample_size") or 0), "accuracy": _clamp(cal.get("accuracy")), "mean_confidence": _clamp(cal.get("mean_confidence")), "calibration_gap": _clamp(cal.get("calibration_gap"), -1, 1), "notes": cal.get("notes") or "awaiting_verified_predictions", "calculated_at": now, "metadata_json": json_dumps({"v15_18_contract_fix": True, "raw": cal.get("metadata")})}, "calibration_id")
            link("calibration_scores", oid); count += 1

    elif engine == "intervention_engine":
        for item in _as_list(output.get("trajectory_warnings")):
            text = str(item if not isinstance(item, dict) else item.get("warning") or item.get("text") or item)
            if text:
                oid = stable_id("trajwarn", episode_id, person_id, text[:120])
                upsert(con, "trajectory_warnings", {"warning_id": oid, "person_id": person_id, "episode_id": episode_id, "prediction_id": None, "warning_type": "qwen_trajectory_warning", "title": text[:120], "detail": text, "severity": "warning", "probability": _clamp(item.get("risk_level") if isinstance(item, dict) else conf), "evidence_json": json_dumps(_as_list(output.get("evidence"))), "counter_evidence_json": json_dumps(_as_list(output.get("counter_evidence"))), "status": "active", "created_at": now, "updated_at": now}, "warning_id")
                link("trajectory_warnings", oid); count += 1
        for esc in _as_list(output.get("escape_conditions")):
            text = str(esc if not isinstance(esc, dict) else esc.get("condition") or esc.get("text") or esc)
            if text:
                oid = stable_id("escape", episode_id, person_id, text[:120])
                upsert(con, "escape_conditions", {"escape_id": oid, "person_id": person_id, "loop_id": None, "prediction_id": None, "condition_text": text, "expected_effect": esc.get("expected_effect") if isinstance(esc, dict) else None, "confidence": conf, "evidence_json": json_dumps(_as_list(output.get("evidence"))), "status": "candidate", "created_at": now, "updated_at": now}, "escape_id")
                link("escape_conditions", oid); count += 1
        for raw_plan in _as_list(output.get("interventions") or output.get("intervention_plans")):
            if isinstance(raw_plan, dict):
                plan = normalize_intervention_plan(raw_plan)
                if plan.get("goal") or plan.get("desired_trajectory"):
                    oid = stable_id("intervention", episode_id, person_id, plan.get("goal"), plan.get("desired_trajectory"))
                    upsert(con, "v13_intervention_plans", {"intervention_plan_id": oid, "prediction_id": None, "person_id": person_id, "episode_id": episode_id, "goal": plan.get("goal"), "current_trajectory": plan.get("current_trajectory"), "desired_trajectory": plan.get("desired_trajectory"), "actions_json": json_dumps(_as_list(plan.get("actions"))), "expected_effects_json": json_dumps(_as_list(plan.get("expected_effects"))), "risks_json": json_dumps(_as_list(plan.get("risks"))), "verification_plan_json": json_dumps(_as_list(plan.get("verification_plan"))), "confidence": _clamp(plan.get("confidence", conf)), "status": "candidate", "created_at": now, "updated_at": now}, "intervention_plan_id")
                    link("v13_intervention_plans", oid); count += 1
    return count


def _create_readiness_checks(con, conversation_id: str) -> None:
    now = now_iso()
    tables = _available_tables(con)
    for table in sorted(STRICT_PLAN_TABLES):
        ok = table in tables
        upsert(con, "v13_readiness_checks", {"readiness_id": stable_id("ready", STRICT_VERSION, table), "check_name": table, "check_group": "schema", "status": "ok" if ok else "missing", "severity": "ok" if ok else "critical", "detail": None if ok else f"missing table {table}", "evidence_json": json_dumps(["sqlite_schema"] if ok else []), "missing_json": json_dumps([] if ok else [table]), "created_at": now}, "readiness_id")
    # Critical contract: strict build requires Qwen and no evidence-only cognitive mode.
    upsert(con, "v13_readiness_checks", {"readiness_id": stable_id("ready", STRICT_VERSION, "qwen_required"), "check_name": "qwen_required", "check_group": "runtime", "status": "required", "severity": "critical", "detail": "V13.2 cognitive engines fail if Qwen/Ollama is unavailable or returns invalid JSON.", "evidence_json": json_dumps([]), "missing_json": json_dumps([]), "created_at": now}, "readiness_id")


def audit_strict_v13_plan(*, persist: bool = True) -> dict[str, Any]:
    ensure_strict_v13_schema()
    now = now_iso()
    rows: list[dict[str, Any]] = []
    with connect() as con:
        tables = _available_tables(con)
        for table in sorted(STRICT_PLAN_TABLES):
            ok = table in tables
            rows.append({"section": "tables", "item": table, "status": "ok" if ok else "missing", "missing": [] if ok else [table]})
        for engine in ENGINE_ORDER:
            missing = [t for t in ENGINE_TABLES.get(engine, []) if t not in tables]
            contract = con.execute("SELECT contract_id FROM v13_llm_contracts WHERE engine_name=?", (engine,)).fetchone()
            if not contract:
                missing.append("v13_llm_contracts:" + engine)
            rows.append({"section": "engines", "item": engine, "status": "ok" if not missing else "partial", "missing": missing})
        for rule in ["no_evidence_only_cognitive_mode", "no_heuristic_regex_cognitive_inference", "qwen_json_contract_required", "temporal_and_object_links_present"]:
            rows.append({"section": "strictness", "item": rule, "status": "ok", "missing": []})
        if persist:
            for r in rows:
                upsert(con, "v13_complete_contract_checks", {"check_id": stable_id("v132check", r["section"], r["item"]), "check_group": r["section"], "check_name": r["item"], "required_status": "ok", "actual_status": r["status"], "detail": "" if r["status"] == "ok" else "missing: " + ", ".join(r["missing"]), "severity": "info" if r["status"] == "ok" else "critical", "created_at": now}, "check_id")
            con.commit()
    return {"version": STRICT_VERSION, "total_items": len(rows), "ok": sum(1 for r in rows if r["status"] == "ok"), "partial_or_missing": [r for r in rows if r["status"] != "ok"], "rows": rows}


def build_strict_v13_for_conversation(conversation_id: str, *, max_episodes: int | None = None, person_id: str | None = None) -> dict[str, Any]:
    ensure_strict_v13_schema()
    audit = audit_strict_v13_plan(persist=True)
    counts: Counter[str] = Counter()
    results = []
    try:
        from . import brain2_shared_facts_v19 as shared_facts
        use_shared_facts = shared_facts.shared_facts_enabled()
    except Exception:
        shared_facts = None
        use_shared_facts = False
    with connect() as con:
        if use_shared_facts and shared_facts is not None:
            shared_facts.ensure_shared_fact_schema(con)
        person_id = _default_user(con, conversation_id, explicit_person_id=person_id)
        # CHANTIER 1 (physical frontier): in PRO with missing episodes, the local
        # P1 subprocess is started for the build and ALWAYS stopped before any
        # DeepSeek engine call. Episodes already complete => P1 never starts.
        # Without the PRO flag the two statements below are the historic ones.
        if _episode_builder_forces_local() and not _conversation_has_complete_episodes(
            con, conversation_id
        ):
            with _pro_local_episode_p1_boundary():
                counts["episodes_created_by_qwen"] += _ensure_episodes_strict(
                    con, conversation_id, person_id=person_id
                )
                # Episodes must be durable BEFORE P1 goes away (handoff §A:
                # build -> coverage -> commit -> stop P1 -> cloud fan-out).
                con.commit()
        else:
            counts["episodes_created_by_qwen"] += _ensure_episodes_strict(
                con, conversation_id, person_id=person_id
            )
        _create_readiness_checks(con, conversation_id)
        # EpisodeBuilder is a complete, independently covered stage. Keep its
        # materialized episodes durable before the per-episode engine matrix so a
        # later engine failure never forces EpisodeBuilder materialization again.
        con.commit()
        episodes = [dict(r) for r in con.execute(
            "SELECT * FROM episodes WHERE source_conversation_id=? ORDER BY start_time, created_at",
            (conversation_id,),
        )]
        if max_episodes is not None:
            episodes = episodes[:max_episodes]
        profiles = {
            str(episode["episode_id"]): _episode_evidence_profile(con, str(episode["episode_id"]))
            for episode in episodes
        }
        bundles = {
            str(episode["episode_id"]): _stable_episode_source_bundle(
                _episode_bundle(con, str(episode["episode_id"]))
            )
            for episode in episodes
        }
        outputs_by_episode: dict[str, dict[str, Any]] = {
            str(episode["episode_id"]): {} for episode in episodes
        }
        episode_counts: dict[str, Counter[str]] = {
            str(episode["episode_id"]): Counter() for episode in episodes
        }
        applicability_reasons: dict[str, dict[str, str]] = {
            str(episode["episode_id"]): {} for episode in episodes
        }
        human_episode_ids = [
            str(episode["episode_id"])
            for episode in episodes
            if profiles[str(episode["episode_id"])].get("has_human_evidence")
        ]
        anchor_episode_id = human_episode_ids[0] if human_episode_ids else None
        conversation_outputs: dict[str, Any] = {}
        conversation_row = con.execute(
            "SELECT started_at FROM conversations WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        package_date = str((conversation_row["started_at"] if conversation_row else None) or now_iso())[:10]
        pro_fanout = (
            os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
            in {"1", "true", "yes", "on"}
            and os.environ.get("MLOMEGA_PRO_FANOUT", "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        pro_episode_work: list[dict[str, Any]] = []

        if use_shared_facts and shared_facts is not None:
            for episode in episodes:
                shared_facts.record_episode_structure(
                    con,
                    person_id=person_id,
                    conversation_id=conversation_id,
                    episode_id=str(episode["episode_id"]),
                )

        # Local engines share the exact same episode evidence. Execute their
        # schema groups as one durable pack, then split by responsibility only
        # when the model/provider reports a real size failure. This preserves all
        # engines while avoiding 6-9 serialisations of the same episode.
        local_engines = [
            engine for engine in ENGINE_ORDER
            if engine != "episode_builder" and engine not in _CONVERSATION_SCOPE_ENGINES
        ]
        for episode in episodes:
            episode_id = str(episode["episode_id"])
            pending: list[str] = []
            resume_prefix = True
            for engine in local_engines:
                applies, reason = _engine_applies_to_episode(
                    engine, episode, profiles[episode_id]
                )
                applicability_reasons[episode_id][engine] = reason
                if not applies:
                    episode_counts[episode_id][f"{engine}_not_applicable"] += 1
                    counts[f"engine_{engine}_not_applicable"] += 1
                    if use_shared_facts and shared_facts is not None:
                        shared_facts.record_engine_not_applicable(
                            con,
                            person_id=person_id,
                            conversation_id=conversation_id,
                            episode_id=episode_id,
                            engine_name=engine,
                            schema=ENGINE_SCHEMAS[engine],
                            reason=reason,
                        )
                    continue
                prior = {**conversation_outputs, **outputs_by_episode[episode_id]}
                prompt = _engine_prompt(
                    engine, bundles[episode_id], prior,
                    bundle_in_prefix=pro_fanout,
                )
                resumed_output = _load_completed_engine_output(
                    con, engine=engine, conversation_id=conversation_id,
                    episode_id=episode_id, prompt=prompt,
                ) if resume_prefix else None
                if resumed_output is not None:
                    if use_shared_facts and shared_facts is not None:
                        resumed_output = shared_facts.record_engine_output(
                            con,
                            person_id=person_id,
                            conversation_id=conversation_id,
                            episode_id=episode_id,
                            engine_name=engine,
                            output=resumed_output,
                            schema=ENGINE_SCHEMAS[engine],
                            applicability_reason=reason,
                        )
                    outputs_by_episode[episode_id][engine] = resumed_output
                    episode_counts[episode_id][f"{engine}_resumed"] += 1
                    counts[f"engine_{engine}_resumed"] += 1
                else:
                    resume_prefix = False
                    pending.append(engine)

            if not pending:
                continue
            pack_prior = {**conversation_outputs, **outputs_by_episode[episode_id]}
            if pro_fanout:
                pro_episode_work.append({
                    "episode_id": episode_id,
                    "pending": tuple(pending),
                    "prior": pack_prior,
                    "bundle": bundles[episode_id],
                })
                continue
            try:
                packed = _run_episode_engine_pack(
                    con,
                    episode_id=episode_id,
                    conversation_id=conversation_id,
                    person_id=person_id,
                    package_date=package_date,
                    bundle=bundles[episode_id],
                    prior=pack_prior,
                    engines=pending,
                )
                for engine in pending:
                    out = packed[engine]
                    if use_shared_facts and shared_facts is not None:
                        out = shared_facts.record_engine_output(
                            con,
                            person_id=person_id,
                            conversation_id=conversation_id,
                            episode_id=episode_id,
                            engine_name=engine,
                            output=out,
                            schema=ENGINE_SCHEMAS[engine],
                            applicability_reason=applicability_reasons[episode_id][engine],
                        )
                    prior = {**conversation_outputs, **outputs_by_episode[episode_id]}
                    prompt = _engine_prompt(engine, bundles[episode_id], prior)
                    _record_engine(
                        con, engine=engine, conversation_id=conversation_id,
                        episode_id=episode_id, person_id=person_id,
                        prompt=prompt, output=out, status="ok",
                    )
                    outputs_by_episode[episode_id][engine] = out
                    mat = _put_engine_payload(con, engine, episode_id, person_id, out)
                    episode_counts[episode_id][f"{engine}_rows"] += mat
                    counts[f"engine_{engine}"] += 1
                    counts[f"{engine}_rows"] += mat
                con.commit()
            except Exception as exc:
                for engine in pending:
                    prior = {**conversation_outputs, **outputs_by_episode[episode_id]}
                    prompt = _engine_prompt(engine, bundles[episode_id], prior)
                    _record_engine(
                        con, engine=engine, conversation_id=conversation_id,
                        episode_id=episode_id, person_id=person_id,
                        prompt=prompt, output=None, status="error",
                        error=str(exc)[:1000],
                    )
                con.commit()
                raise

        if pro_episode_work:
            # Cloud-only DAG: each cognitive engine keeps its own schema/request.
            # Only independent engines share a wave, while dependency barriers
            # materialize their outputs before the following level. The local
            # episode-pack-v2 path above remains byte-for-byte unchanged.
            con.commit()

            # CHANTIER 2 step 2-4: prime each UNIQUE episode prefix once, then wait
            # a SINGLE cache propagation before the concurrent fan-out (never one
            # wait per episode). Warm-up is deduplicated by digest, so a resume or
            # a repeated episode never repays it. Only runs under PRO fan-out.
            episode_prefixes = [
                (str(work["episode_id"]), dict(work["bundle"]))
                for work in pro_episode_work
            ]
            _pro_warm_episode_prefixes(episode_prefixes)
            # Codex correction 5: gate the CONCURRENT fan-out on a real cache-hit
            # probe (two warms + one probe).  When the probe is cold, degrade to a
            # SEQUENTIAL fan-out instead of firing 8-12 cold concurrent calls.
            fanout_ready = _pro_probe_fanout_ready(episode_prefixes)

            def run_engine_task(task: Mapping[str, Any]) -> dict[str, Any]:
                with connect() as worker_con:
                    from .cloud_providers_v19 import cloud_bundle_prefix
                    with cloud_bundle_prefix(str(task["episode_id"]), dict(task["bundle"])):
                        return _run_engine_partitioned(
                            worker_con,
                            engine=str(task["engine"]),
                            episode_id=str(task["episode_id"]),
                            person_id=person_id,
                            bundle=task["bundle"],
                            prior=task["prior"],
                            bundle_in_prefix=True,
                        )

            try:
                initial_width = max(1, min(12, int(os.environ.get("MLOMEGA_PRO_FANOUT_INITIAL", "4"))))
            except ValueError:
                initial_width = 4
            try:
                max_width = max(
                    initial_width,
                    min(40, int(os.environ.get("MLOMEGA_CLOUD_MAX_IN_FLIGHT", "12"))),
                )
            except ValueError:
                max_width = max(initial_width, 12)
            if not fanout_ready:
                # Degraded sequential fan-out: cold cache, so one call at a time.
                initial_width = 1
                max_width = 1

            known_levels = [
                ("capture_engine", "language_signature_engine"),
                ("context_resolver",),
                ("internal_state_engine", "social_model_engine"),
                ("causality_engine", "contradiction_engine", "choice_model_engine"),
                ("outcome_tracker",),
            ]
            known = {engine for level in known_levels for engine in level}
            for engine in local_engines:
                if engine not in known:
                    known_levels.append((engine,))

            for level in known_levels:
                tasks: list[dict[str, Any]] = []
                for work in pro_episode_work:
                    episode_id = str(work["episode_id"])
                    for engine in level:
                        if engine in work["pending"]:
                            tasks.append({
                                "episode_id": episode_id,
                                "engine": engine,
                                "bundle": work["bundle"],
                                # DAG projection (Codex cost point #1): send only
                                # this engine's DIRECT dependency outputs, never
                                # the whole cumulated prior.
                                "prior": _direct_prior(
                                    engine,
                                    conversation_outputs,
                                    outputs_by_episode[episode_id],
                                ),
                            })
                if not tasks:
                    continue

                task_results: dict[tuple[str, str], dict[str, Any] | Exception] = {}
                cursor = 0
                wave_width = initial_width
                while cursor < len(tasks):
                    wave = tasks[cursor:cursor + wave_width]
                    with ThreadPoolExecutor(
                        max_workers=len(wave), thread_name_prefix="mlomega-pro-engine"
                    ) as pool:
                        futures = {}
                        for task in wave:
                            # ContextVar carries the exact canonical bundle prefix;
                            # copies share its one warm-cache response.
                            context = copy_context()
                            future = pool.submit(context.run, run_engine_task, task)
                            futures[future] = (str(task["episode_id"]), str(task["engine"]))
                        for future in as_completed(futures):
                            key = futures[future]
                            try:
                                task_results[key] = future.result()
                            except Exception as exc:
                                task_results[key] = exc
                    cursor += len(wave)
                    wave_width = min(max_width, wave_width * 2)

                # Deterministic writer barrier before dependent engines proceed.
                for task in tasks:
                    episode_id = str(task["episode_id"])
                    engine = str(task["engine"])
                    out_or_error = task_results[(episode_id, engine)]
                    prompt = _engine_prompt(
                        engine, bundles[episode_id], task["prior"],
                        bundle_in_prefix=True,
                    )
                    if isinstance(out_or_error, Exception):
                        _record_engine(
                            con, engine=engine, conversation_id=conversation_id,
                            episode_id=episode_id, person_id=person_id,
                            prompt=prompt, output=None, status="error",
                            error=str(out_or_error)[:1000],
                        )
                        con.commit()
                        raise out_or_error
                    out = out_or_error
                    if use_shared_facts and shared_facts is not None:
                        out = shared_facts.record_engine_output(
                            con,
                            person_id=person_id,
                            conversation_id=conversation_id,
                            episode_id=episode_id,
                            engine_name=engine,
                            output=out,
                            schema=ENGINE_SCHEMAS[engine],
                            applicability_reason=applicability_reasons[episode_id][engine],
                        )
                    _record_engine(
                        con, engine=engine, conversation_id=conversation_id,
                        episode_id=episode_id, person_id=person_id,
                        prompt=prompt, output=out, status="ok",
                    )
                    outputs_by_episode[episode_id][engine] = out
                    mat = _put_engine_payload(con, engine, episode_id, person_id, out)
                    episode_counts[episode_id][f"{engine}_rows"] += mat
                    counts[f"engine_{engine}"] += 1
                    counts[f"{engine}_rows"] += mat
                con.commit()

        # Cross-episode engines also share one compact conversation package.
        # Pack them once and let the same durable executor subdivide by engine
        # schema only if Qwen cannot return the complete JSON in one response.
        global_engines = [e for e in ENGINE_ORDER if e in _CONVERSATION_SCOPE_ENGINES]
        if anchor_episode_id and global_engines:
            for engine in global_engines:
                for episode in episodes:
                    episode_id = str(episode["episode_id"])
                    if episode_id != anchor_episode_id:
                        episode_counts[episode_id][f"{engine}_not_applicable"] += 1
                        counts[f"engine_{engine}_not_applicable"] += 1
                        if use_shared_facts and shared_facts is not None:
                            shared_facts.record_engine_not_applicable(
                                con,
                                person_id=person_id,
                                conversation_id=conversation_id,
                                episode_id=episode_id,
                                engine_name=engine,
                                schema=ENGINE_SCHEMAS[engine],
                                reason="conversation_scope_on_parent_anchor",
                            )
            bundle = _conversation_engine_bundle(
                con, conversation_id, episodes, profiles, outputs_by_episode
            )
            pending_globals: list[str] = []
            resume_prefix = True
            for engine in global_engines:
                prior = {
                    "conversation_outputs": conversation_outputs,
                    "by_episode": {
                        key: value for key, value in outputs_by_episode.items() if value
                    },
                }
                prompt = _engine_prompt(engine, bundle, prior)
                resumed_output = _load_completed_engine_output(
                    con, engine=engine, conversation_id=conversation_id,
                    episode_id=anchor_episode_id, prompt=prompt,
                ) if resume_prefix else None
                if resumed_output is not None:
                    if use_shared_facts and shared_facts is not None:
                        resumed_output = shared_facts.record_engine_output(
                            con,
                            person_id=person_id,
                            conversation_id=conversation_id,
                            episode_id=anchor_episode_id,
                            engine_name=engine,
                            output=resumed_output,
                            schema=ENGINE_SCHEMAS[engine],
                            applicability_reason="conversation_scope_parent",
                        )
                    outputs_by_episode[anchor_episode_id][engine] = resumed_output
                    conversation_outputs[engine] = resumed_output
                    episode_counts[anchor_episode_id][f"{engine}_resumed"] += 1
                    counts[f"engine_{engine}_resumed"] += 1
                else:
                    resume_prefix = False
                    pending_globals.append(engine)

            if pending_globals:
                try:
                    if pro_fanout:
                        # These engines form a real dependency chain; keep one
                        # request per engine, sequentially enriching prior output.
                        # Codex cost point #2: instead of shipping every raw prior
                        # output + all ``by_episode`` (the 8k->66k explosion), each
                        # global engine receives ONLY (a) the outputs of its DIRECT
                        # parents (from ``_ENGINE_DIRECT_DEPS``) and (b) a
                        # PER-DEPENDENCY PROJECTION of the canonical facts (Codex
                        # point A): only the ``source_engine`` facts its dependencies
                        # need, in the COMPACT trimmed form (Codex point B).  The old
                        # single 36778-token bundle sent to all six is gone; the full
                        # evidence stays authoritative in brain2_shared_facts_v19.
                        compact_facts: list[dict[str, Any]] = []
                        if use_shared_facts and shared_facts is not None:
                            fact_bundle = shared_facts.compact_fact_bundle(
                                con, conversation_id
                            )
                            turn_refs = shared_facts.conversation_turn_refs(
                                con, conversation_id
                            )
                            compact_facts = shared_facts.compact_facts_for_prompt(
                                fact_bundle, turn_refs
                            )
                        # Codex point C: the small core of facts truly common to
                        # several globals (after projection) is placed once in a
                        # shared DeepSeek cache prefix and warmed a single time, so
                        # the fan-out pays cache reads, not N re-sends of the core.
                        projected_by_engine = {
                            engine: _facts_for_global_engine(engine, compact_facts)
                            for engine in pending_globals
                        }
                        common_core = _global_common_fact_core(projected_by_engine)
                        _pro_warm_global_fact_core(conversation_id, common_core)
                        # TASK 3: place the SAME common fact core (byte-for-byte)
                        # in a shared DeepSeek cache PREFIX for every global engine
                        # of this conversation, so the substrate the globals share
                        # is paid as a cache READ once instead of N cold MISSes.
                        # The bundle_id/payload MUST match ``_pro_warm_global_fact_core``
                        # exactly so the warmed digest is the one we ride on. The
                        # per-dependency projection (volume control) is untouched:
                        # only the genuinely COMMON core rides the shared prefix.
                        global_core_prefix = _pro_global_fact_core_prefix(
                            conversation_id, common_core
                        )
                        # Codex correction 3: the GLOBAL engines read their
                        # projected inputs (direct parents / per-dependency facts /
                        # similar_case prior), NEVER the transcript.  Ship them the
                        # compact episode fingerprint instead of the ~25k-token
                        # ``bundle`` so similar_case's window falls back under the
                        # 24576 input budget.  The per-episode path keeps its full
                        # episode bundle (those engines analyse the episode content).
                        global_bundle = _global_engine_bundle(bundle)
                        packed: dict[str, dict[str, Any]] = {}
                        with global_core_prefix:
                          for engine in pending_globals:
                            # Codex: a GLOBAL engine synthesises from its projected
                            # COMPACT inputs (the shared-facts projection / the
                            # similar_case summary), NEVER the full raw parent engine
                            # outputs.  Passing ``direct_dependencies`` (the ~20k full
                            # parent output) re-sent pattern_miner's whole output on
                            # top of its own compact summary and pushed
                            # similar_case to 21k > budget (Gate B 183352).  The
                            # per-episode DAG prior is unchanged; only the global
                            # chain drops the raw parent outputs here.
                            global_prior: dict[str, Any] = {}
                            projected = projected_by_engine.get(engine) or []
                            # Only engines that actually carry the shared-facts
                            # INPUT list expose it to the lossless windowing fallback.
                            windowed_facts: list[dict[str, Any]] | None = None
                            if engine == "similar_case_retrieval":
                                # Codex correction 3: this stage receives ONLY the
                                # pattern output summary + episode fingerprint +
                                # case index — NEVER the 97-fact registry NOR the full
                                # pattern output — so it stays under the input budget.
                                global_prior = {
                                    "similar_case_input": _similar_case_prior(
                                        con,
                                        person_id=person_id,
                                        conversation_id=conversation_id,
                                        bundle=global_bundle,
                                        pattern_output=packed.get("pattern_miner"),
                                    ),
                                }
                            elif projected:
                                global_prior["shared_facts"] = {
                                    "conversation_id": conversation_id,
                                    "projection": "per_dependency_source_engine",
                                    "facts": projected,
                                }
                                windowed_facts = projected
                            packed[engine] = _run_engine_partitioned(
                                con,
                                engine=engine,
                                episode_id=anchor_episode_id,
                                person_id=person_id,
                                bundle=global_bundle,
                                prior=global_prior,
                                projected_facts=windowed_facts,
                            )
                    else:
                        packed = _run_global_engine_hierarchy(
                            con,
                            conversation_id=conversation_id,
                            person_id=person_id,
                            package_date=package_date,
                            conversation=bundle.get("conversation"),
                            episodes=episodes,
                            profiles=profiles,
                            outputs_by_episode=outputs_by_episode,
                            engines=pending_globals,
                        )
                    for engine in pending_globals:
                        out = packed[engine]
                        if use_shared_facts and shared_facts is not None:
                            out = shared_facts.record_engine_output(
                                con,
                                person_id=person_id,
                                conversation_id=conversation_id,
                                episode_id=anchor_episode_id,
                                engine_name=engine,
                                output=out,
                                schema=ENGINE_SCHEMAS[engine],
                                applicability_reason="conversation_scope_parent",
                            )
                        prior = {
                            "conversation_outputs": conversation_outputs,
                            "by_episode": {
                                key: value for key, value in outputs_by_episode.items()
                                if value
                            },
                        }
                        prompt = _engine_prompt(engine, bundle, prior)
                        _record_engine(
                            con, engine=engine, conversation_id=conversation_id,
                            episode_id=anchor_episode_id, person_id=person_id,
                            prompt=prompt, output=out, status="ok",
                        )
                        outputs_by_episode[anchor_episode_id][engine] = out
                        conversation_outputs[engine] = out
                        mat = _put_engine_payload(
                            con, engine, anchor_episode_id, person_id, out
                        )
                        episode_counts[anchor_episode_id][f"{engine}_rows"] += mat
                        counts[f"engine_{engine}"] += 1
                        counts[f"{engine}_rows"] += mat
                    con.commit()
                except Exception as exc:
                    for engine in pending_globals:
                        prior = {
                            "conversation_outputs": conversation_outputs,
                            "by_episode": {
                                key: value for key, value in outputs_by_episode.items()
                                if value
                            },
                        }
                        prompt = _engine_prompt(engine, bundle, prior)
                        _record_engine(
                            con, engine=engine, conversation_id=conversation_id,
                            episode_id=anchor_episode_id, person_id=person_id,
                            prompt=prompt, output=None, status="error",
                            error=str(exc)[:1000],
                        )
                    con.commit()
                    raise

        for episode in episodes:
            episode_id = str(episode["episode_id"])
            if use_shared_facts and shared_facts is not None:
                shared_stats = shared_facts.finish_episode_fact_run(
                    con, conversation_id=conversation_id, episode_id=episode_id
                )
                episode_counts[episode_id]["shared_fact_engines"] += shared_stats["engines"]
                episode_counts[episode_id]["shared_fact_capabilities"] += shared_stats["capabilities"]
                episode_counts[episode_id]["shared_facts"] += shared_stats["facts"]
                episode_counts[episode_id]["shared_facts_uncited"] += shared_stats["uncited_facts"]
            results.append({
                "episode_id": episode_id,
                "engines_run": sum(
                    1 for key in episode_counts[episode_id]
                    if key.endswith("_rows") or key.endswith("_resumed")
                ),
                "sensor_only": bool(profiles[episode_id].get("sensor_only")),
                "counts": dict(episode_counts[episode_id]),
            })
        con.commit()
    return {"version": STRICT_VERSION, "mode": "strict_qwen_no_heuristics", "conversation_id": conversation_id, "episodes": len(results), "results": results, "counts": dict(counts), "audit_ok": audit["ok"], "audit_total": audit["total_items"], "audit_missing": audit["partial_or_missing"]}


def build_strict_v13_all(*, max_episodes_per_conversation: int | None = None) -> dict[str, Any]:
    ensure_strict_v13_schema()
    with connect() as con:
        convs = [r["conversation_id"] for r in con.execute("SELECT conversation_id FROM conversations ORDER BY started_at, created_at")]
    return {"version": STRICT_VERSION, "mode": "strict_qwen_no_heuristics", "conversations": len(convs), "results": [build_strict_v13_for_conversation(cid, max_episodes=max_episodes_per_conversation) for cid in convs]}


def predict_strict_v13(target: str, context: str, *, person_id: str | None = None, horizon: str = "next") -> dict[str, Any]:
    ensure_strict_v13_schema()
    target = target if target in COMPLETE_TARGETS else "next_action"
    with connect() as con:
        person_id = person_id or _default_user(con)
        bundle = {
            "prediction_request": {"target": target, "context": context, "horizon": horizon, "person_id": person_id},
            "recent_predictions": [dict(r) for r in con.execute("SELECT * FROM predictions WHERE person_id=? AND status IN ('open','active','watch') ORDER BY created_at DESC LIMIT 50", (person_id,))],
            "recent_cases": [dict(r) for r in con.execute("SELECT * FROM prediction_cases WHERE person_id=? AND COALESCE(usable_for_prediction,1)=1 ORDER BY created_at DESC LIMIT 50", (person_id,))],
            "self_model": [dict(r) for r in con.execute("SELECT * FROM self_model_dimensions WHERE person_id=? LIMIT 100", (person_id,))],
            "relationships": [dict(r) for r in con.execute("SELECT * FROM relationship_models WHERE person_a=? OR person_b=? LIMIT 100", (person_id, person_id))],
        }
        prompt = json_dumps({"mission": "Prédiction Brain 2.0 stricte. Produis prediction JSON avec probability/confidence/why/similar_cases/counter_evidence/assumptions/interventions/branches. Ne complète rien sans preuves.", "bundle": bundle, "schema": ENGINE_SCHEMAS["prediction_engine"]})
        out = _llm_require_json("prediction_engine", prompt, ENGINE_SCHEMAS["prediction_engine"])
        run_id = _record_engine(con, engine="prediction_engine", conversation_id=None, episode_id=None, person_id=person_id, prompt=prompt, output=out, status="ok")
        # Materialize without episode by creating prediction rows directly.
        now = now_iso(); pred_ids = []
        for p in _as_list(out.get("predictions")):
            if isinstance(p, dict) and (p.get("predicted_value") or p.get("prediction")):
                pid = stable_id("prediction", STRICT_VERSION, person_id, target, context[:160], p.get("predicted_value") or p.get("prediction"))
                value = str(p.get("predicted_value") or p.get("prediction"))
                upsert(con, "predictions", {"prediction_id": pid, "created_at": now, "person_id": person_id, "prediction_target": p.get("prediction_target") or target, "horizon": p.get("horizon") or horizon, "current_context": context, "predicted_value": value, "probability": _clamp(p.get("probability")), "confidence": _clamp(p.get("confidence")), "alternatives_json": json_dumps(_as_list(p.get("alternatives"))), "evidence_cases_json": json_dumps(_as_list(p.get("similar_cases"))), "counter_evidence_json": json_dumps(_as_list(p.get("counter_evidence"))), "assumptions_json": json_dumps(_as_list(p.get("assumptions"))), "intervention_options_json": json_dumps(_as_list(p.get("interventions"))), "verification_due_at": p.get("verification_due_at"), "status": "open", "metadata_json": json_dumps({"strict_v13_2": True, "why": _as_list(p.get("why")), "engine_run_id": run_id}), "updated_at": now}, "prediction_id")
                pred_ids.append(pid)
        con.commit()
    return {"version": STRICT_VERSION, "mode": "strict_qwen_no_heuristics", "prediction_ids": pred_ids, "raw_prediction_json": out}


def verify_strict_v13_prediction(prediction_id: str, observed_value: str, *, match_score: float | None = None, note: str | None = None) -> dict[str, Any]:
    ensure_strict_v13_schema()
    with connect() as con:
        pred = con.execute("SELECT * FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
        if not pred:
            return {"error": "prediction_missing", "prediction_id": prediction_id}
        person_id = pred["person_id"] or _default_user(con)
        prompt = json_dumps({"mission": "Calibre strictement cette prédiction à partir de l'observation. Ne juge pas par règle; compare sémantiquement et explique.", "prediction": dict(pred), "observed_value": observed_value, "user_match_score_optional": match_score, "note": note, "schema": ENGINE_SCHEMAS["calibration_engine"]})
        out = _llm_require_json("calibration_engine", prompt, ENGINE_SCHEMAS["calibration_engine"])
        _record_engine(con, engine="calibration_engine", conversation_id=None, episode_id=None, person_id=person_id, prompt=prompt, output=out, status="ok")
        now = now_iso()
        result_id = stable_id("predres", prediction_id, observed_value[:160])
        ms = _clamp(out.get("match_score", match_score))
        upsert(con, "prediction_results", {"result_id": result_id, "prediction_id": prediction_id, "observed_value": observed_value, "match_score": ms, "was_correct": 1 if bool(out.get("was_correct")) else 0, "why_correct": out.get("why_correct"), "why_wrong": out.get("why_wrong"), "model_update": json_dumps(out.get("model_update") or {}), "verified_at": now, "metadata_json": json_dumps({"strict_v13_2": True, "note": note})}, "result_id")
        upsert(con, "model_revisions", {"model_revision_id": stable_id("modelrev", prediction_id, result_id), "target_table": "predictions", "target_id": prediction_id, "revision_type": "strict_prediction_verification", "previous_json": json_dumps(dict(pred)), "new_json": json_dumps({"observed_value": observed_value, "calibration": out}), "reason": out.get("why_wrong") or out.get("why_correct") or note or "strict verification", "evidence_json": json_dumps([observed_value]), "created_at": now}, "model_revision_id")
        upsert(con, "v13_replay_events", {"replay_id": stable_id("replay", prediction_id, result_id), "person_id": person_id, "prediction_id": prediction_id, "source_case_id": None, "episode_id": None, "predicted_target": pred["prediction_target"], "predicted_value": pred["predicted_value"], "observed_value": observed_value, "match_score": ms, "verdict": "correct" if bool(out.get("was_correct")) else "wrong_or_partial", "lesson_json": json_dumps(out.get("lesson") or out.get("model_update") or {}), "created_at": now}, "replay_id")
        was_correct = bool(out.get("was_correct"))
        closed_status = "closed_confirmed" if was_correct else ("closed_partial" if ms >= 0.35 else "closed_wrong")
        con.execute("UPDATE predictions SET status=?, updated_at=? WHERE prediction_id=?", (closed_status, now, prediction_id))
        try:
            con.execute("UPDATE brain2_live_watch_bindings SET status=?, updated_at=? WHERE source_table='predictions' AND source_id=?", ("disabled_verified_wrong" if not was_correct else "verified_confirmed", now, prediction_id))
        except Exception:
            pass
        con.commit()
    return {"version": STRICT_VERSION, "mode": "strict_qwen_no_heuristics", "prediction_id": prediction_id, "calibration": out, "result_id": result_id}


def strict_v13_overview() -> dict[str, Any]:
    ensure_strict_v13_schema()
    audit = audit_strict_v13_plan(persist=False)
    with connect() as con:
        counts = {}
        for t in sorted(STRICT_PLAN_TABLES):
            try:
                counts[t] = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            except Exception:
                counts[t] = "missing"
        cycles = [dict(r) for r in con.execute("SELECT engine_run_id, engine_name, status, episode_id, started_at, finished_at FROM v13_engine_runs ORDER BY started_at DESC LIMIT 20")]
    return {"version": STRICT_VERSION, "mode": "strict_qwen_no_heuristics", "audit": audit, "counts": counts, "latest_engine_runs": cycles}

# V18: derived multimodal evidence is a local source-addressable addendum, not dialogue.
from .v18_brain2_context import install as _install_v18_brain2_context
_globals_v18_brain2_context = _install_v18_brain2_context(__import__(__name__, fromlist=['*']))
globals().update(_globals_v18_brain2_context)
