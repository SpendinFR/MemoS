
"""
MemoryLight Omega — Dashboard 2.0
=================================

One-page Streamlit dashboard for the MemoryLight / mlomega_audio_elite SQLite database.
It is strictly read-only: no CLI bridge and no write unlock are exposed.

Run:
    streamlit run app.py -- --db /path/to/memory.db --person-id me

Optional CLI bridge:
    streamlit run app.py -- --db /path/to/memory.db --project-root /path/to/project
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import streamlit as st

from read_model import (
    TECHNICAL_TABLES,
    bbox_audit,
    certainty_bucket,
    deep_vision_view,
    human_title,
    life_watch_view,
    parse_json,
    semantic_text,
)

APP_TITLE = "MemoryLight Dashboard"
APP_SUBTITLE = "Self-model visible • mémoire 2.0 • cockpit une-page"
DEFAULT_PERSON_ID = "me"

TIME_COLUMNS = [
    "updated_at", "created_at", "last_seen_at", "last_seen", "verified_at", "due_at",
    "asked_at", "answered_at", "time_start", "start_time", "period_end", "period_start",
    "timestamp", "event_time", "observed_at", "ingested_at", "ended_at", "started_at",
]
CONFIDENCE_COLUMNS = [
    "confidence", "confidence_hint", "probability", "score", "match_score", "salience",
    "intensity", "strength", "relevance", "certainty", "support_score",
]
STATUS_COLUMNS = ["status", "current_status", "truth_status", "validity_status", "priority", "severity", "risk_level", "result"]
TITLE_COLUMNS = [
    "title", "section_name", "dimension_key", "fact_type", "pattern_type", "loop_type",
    "clarification_type", "question_text", "current_situation", "relationship_state_summary",
    "expression", "token", "dominant_emotion", "content", "summary", "message", "name",
    "event_type", "forecast_type", "hypothesis_type", "intervention_type", "open_loop_type",
]
BODY_COLUMNS = [
    "overall_reading", "state_summary", "content", "canonical_summary", "hidden_pattern_summary",
    "why_user_may_not_see_it", "possible_future_if_unchanged", "probable_path", "message",
    "recommended_action", "why_now", "question_text", "why_needed", "answer_summary", "evidence_text",
    "personal_meaning", "relationship_state_summary", "communication_style", "model_update", "why_correct",
    "why_wrong", "description", "summary", "rationale", "reason", "interpretation", "hypothesis",
    "prediction", "expected_outcome", "next_best_action", "action_text", "observed_outcome",
]
EVIDENCE_COLUMNS = [
    "evidence_text", "evidence_json", "source_spans_json", "supporting_evidence_json", "counter_evidence_json",
    "proof_json", "quotes_json", "examples_json", "observations_json", "source_text", "text",
]

CORE_TABLES = {
    "Self-model": [
        "v14_3_self_model_exports",
        "v14_3_self_model_export_sections",
        "v14_periodic_self_snapshots",
        "v14_self_model_readings",
        "v13_user_model_snapshots",
        "self_model_facts",
        "self_model_dimensions",
        "memory_cards",
        "memory_facets",
        "memory_evidence",
        "memory_links",
        "memory_revisions",
    ],
    "Ressenti du jour": [
        "internal_state_snapshots",
        "emotion_evidence",
        "thought_hypotheses",
        "state_transitions",
        "activation_signals",
        "behavior_signals",
        "audio_prosody_events",
        "v14_6_social_aftereffects",
    ],
    "Langage & tics": [
        "personal_language_patterns",
        "expression_signals",
        "word_signals",
        "phrase_templates",
        "language_ngrams",
        "next_phrase_cases",
        "style_state_snapshots",
        "speech_acts",
        "utterance_analyses",
    ],
    "Patterns & contradictions": [
        "v14_pattern_mirror_cards",
        "v14_blindspot_hypotheses",
        "v14_long_horizon_threads",
        "v14_repetition_chains",
        "v14_counterfactual_lessons",
        "patterns",
        "candidate_patterns",
        "confirmed_patterns",
        "loop_patterns",
        "pattern_contexts",
        "pattern_counterexamples",
        "contradiction_events",
        "counter_evidence_items",
    ],
    "Causalité & prédictions": [
        "causal_hypotheses",
        "causal_edges",
        "prediction_cases",
        "predictions",
        "prediction_results",
        "prediction_target_scores",
        "simulation_branches",
        "future_scenarios",
        "trajectory_warnings",
        "trajectory_interventions",
        "escape_conditions",
        "latent_outcome_links",
        "latent_outcome_search_runs",
        "v14_trajectory_forecasts",
        "v14_forecast_watch_queue",
        "v14_4_auto_verify_runs",
        "v14_4_auto_verify_links",
        "calibration_scores",
        "model_revisions",
        "v13_prediction_explanations",
    ],
    "Open-loops & actions": [
        "v14_5_personal_open_loops",
        "v14_5_open_loop_updates",
        "v14_5_active_questions",
        "v14_5_solution_candidates",
        "v14_5_next_best_actions",
        "v14_open_questions",
        "action_intentions",
        "action_outcomes",
        "commitments",
        "decisions",
        "recommended_actions",
        "choice_episodes",
        "choice_options",
        "choice_criteria",
        "ideas",
    ],
    "Relations & personnes": [
        "v14_5_people_identity_hypotheses",
        "v14_5_people_identity_runs",
        "v14_5_people_context_profiles",
        "v14_5_relationship_inference_cards",
        "v14_5_speaker_name_evidence",
        "v14_people_trigger_maps",
        "v14_6_relationship_state_models",
        "v14_6_person_model_summaries",
        "v14_6_other_person_state_snapshots",
        "v14_6_interpersonal_loop_cards",
        "v14_6_interpersonal_emotional_couplings",
        "v14_6_micro_interaction_impacts",
        "relationship_models",
        "relations",
        "social_roles",
        "trust_history",
        "conflict_loops",
        "repair_patterns",
        "person_reaction_patterns",
        "interaction_episodes",
    ],
    "Interventions": [
        "v14_7_intervention_queue",
        "v14_7_intervention_opportunities",
        "v14_7_intervention_feedback",
        "v14_7_intervention_outcomes",
        "v14_7_intervention_policies",
        "v14_7_intervention_runs",
        "v14_7_intervention_exports",
        "v14_intervention_triggers",
        "v14_6_intervention_suggestions",
        "v13_intervention_plans",
    ],
    "Clarifications": [
        "v14_8_clarification_items",
        "v14_8_clarification_answers",
        "v14_8_clarification_resolution_attempts",
        "v14_8_clarification_policies",
        "v14_8_clarification_runs",
        "v14_8_clarification_exports",
        "voice_pending_prompts",
        "speaker_uncertainty_segments",
    ],
    "Timeline & mémoire brute": [
        "conversations",
        "turns",
        "source_spans",
        "source_items",
        "raw_assets",
        "episodes",
        "episode_boundaries",
        "episode_evidence",
        "episode_links",
        "life_events",
        "life_event_entities",
        "lifestream_segments",
        "memory_timeline_edges",
        "conversation_turning_points",
        "conversation_topic_threads",
        "conversation_subtopic_segments",
        "conversation_callbacks",
        "conversation_discourse_maps",
        "utterance_discourse_links",
        "entities",
        "atomic_memories",
        "memory_frames",
        "reflection_states",
        "reflection_edges",
        "situation_episodes",
    ],
    "Audio & voix": [
        "audio_preprocess_runs",
        "audio_segments",
        "audio_chunk_groups",
        "audio_timestamp_maps",
        "audio_chunk_conversation_links",
        "speaker_profiles",
        "speaker_matches",
        "voice_embeddings",
        "self_voice_profile",
        "voice_clusters",
        "voice_observations",
        "voice_identity_revisions",
    ],
    "Flow & qualité": [
        "direct_flow_jobs",
        "extraction_runs",
        "sync_jobs",
        "v12_engine_runs",
        "v12_quality_findings",
        "v12_quarantine",
        "v12_schema_migrations",
        "v12_canonical_facets",
        "v13_engine_runs",
        "v13_engine_outputs",
        "v13_cognitive_cycles",
        "v13_llm_extractions",
        "v13_autonomous_runs",
        "v13_autonomous_insights",
        "v13_autonomous_ask_runs",
        "v13_readiness_checks",
        "v13_memory_contract_checks",
        "v13_complete_contract_checks",
        "v13_component_coverage",
        "v13_engine_dependencies",
        "v13_llm_contracts",
        "v13_prosody_requirements",
        "v13_plan_requirements",
        "v13_plan_audit_rows",
        "v13_case_clusters",
        "v13_dynamic_models",
        "v13_replay_events",
        "v14_mirror_runs",
        "v14_ask_runs",
        "v14_contract_checks",
        "v14_1_router_runs",
        "v14_1_selection_runs",
        "v14_1_selection_candidates",
        "v14_1_answer_packets",
        "v14_1_raw_recall_windows",
        "v14_1_route_contract_checks",
        "v14_2_vector_search_runs",
        "v14_2_vector_candidates",
        "v14_2_fusion_runs",
        "v14_2_fused_candidates",
        "v14_2_selection_signal_scores",
        "v14_2_noise_guardrail_reports",
        "v14_2_answer_packets",
        "v14_2_contract_checks",
        "v14_3_schedule_state",
        "v14_3_schedule_runs",
        "v14_3_contract_checks",
        "v14_4_autopilot_coverage",
        "v14_5_contract_checks",
        "v14_6_contract_checks",
        "v14_7_contract_checks",
        "v14_8_contract_checks",
        "vector_sync_manifest",
        "retrieval_chunks",
        "similar_case_retrieval_runs",
        "similar_case_scores",
        "brain2_object_links",
        "brain2_temporal_links",
    ],
    "V19 — live, vision & modèle de vie": [
        # Hypothèses E38
        "brainlive_life_hypotheses",
        "brainlive_hypothesis_evidence",
        # Life Model V19
        "life_model_entries_v19",
        "self_schema_v19",
        "predictions_v19",
        "prediction_outcomes_v19",
        "brain2_life_model_item_lifecycle",
        "calibration_scores",
        # Événements visuels + preuves
        "visual_events_v19",
        "visual_evidence_assets_v19",
        # Entités / lieux / routines WorldBrain
        "world_entity_links_v19",
        "brain2_spatial_routine_models",
        "scene_session_summaries_v19",
        # Sessions live + close-day
        "brainlive_sessions",
        "v18_close_day_runs",
        # Compteurs live
        "ui_interaction_outcomes_v19",
        "brainlive_intervention_deliveries",
        "brainlive_intervention_outcomes_v188",
    ],
}

SECTION_EMOJIS = {
    "Self-model": "🧠",
    "Ressenti du jour": "🌡️",
    "Langage & tics": "🗣️",
    "Patterns & contradictions": "🔁",
    "Causalité & prédictions": "🔮",
    "Open-loops & actions": "🧩",
    "Relations & personnes": "👥",
    "Interventions": "⚡",
    "Clarifications": "❓",
    "Timeline & mémoire brute": "🕰️",
    "Audio & voix": "🎙️",
    "Flow & qualité": "📊",
    "V19 — live, vision & modèle de vie": "🛰️",
}

SECTION_INTENTS = {
    "Self-model": "Ce que le système croit savoir de l’utilisateur, avec faits, hypothèses, dimensions, preuves et inconnues.",
    "Ressenti du jour": "État intérieur inféré : énergie, stress, clarté, émotion dominante, besoin latent, tensions et transitions.",
    "Langage & tics": "Mots, expressions, tournures, tics de langage, style, marqueurs de doute ou de validation.",
    "Patterns & contradictions": "Répétitions, boucles, angles morts, contradictions, contre-exemples, trajectoires qui se renforcent ou disparaissent.",
    "Causalité & prédictions": "Hypothèses si X alors Y, scénarios futurs, prédictions, vérifications, calibration et révisions du modèle.",
    "Open-loops & actions": "Questions ouvertes, désirs, décisions, blocages, solutions candidates et prochaines actions.",
    "Relations & personnes": "Personnes, identités supposées, relations, effets sociaux, modèles des autres et boucles interpersonnelles.",
    "Interventions": "Messages proactifs, opportunités d’action, feedback, priorités, timing et historique d’aide.",
    "Clarifications": "Questions que le système veut poser ou surveiller pour corriger le modèle sans inventer.",
    "Timeline & mémoire brute": "Conversations, tours de parole, sources, épisodes, événements, décisions et mémoire chronologique.",
    "Audio & voix": "Fichiers audio, speakers, segments, identités vocales et incertitudes liées aux voix.",
    "Flow & qualité": "Jobs, runs, audits, erreurs, contrats, qualité vectorielle, sélection, anti-bruit et traçabilité technique.",
    "V19 — live, vision & modèle de vie": "Ce que la mémoire produit maintenant : hypothèses d'identité, modèle de vie typé, prédictions vérifiées, événements visuels prouvés, entités/lieux/routines, sessions live et close-day.",
}

@dataclass(frozen=True)
class TableInfo:
    name: str
    count: int
    columns: tuple[str, ...]
    section: str

@dataclass(frozen=True)
class DashFilters:
    person_id: str
    date_start: str
    date_end: str
    min_confidence: float
    person_query: str
    status_query: str

@dataclass(frozen=True)
class CliConfig:
    enabled: bool
    write_enabled: bool
    cli_command: str
    project_root: str
    timeout_seconds: int


def find_project_root() -> Optional[Path]:
    """Locate the MLOmega project root (contains .env and src/) from this file."""
    env_root = os.environ.get("MLOMEGA_PROJECT_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)
    here = Path(__file__).resolve()
    # apps/memory-dashboard/app.py -> project root is two levels up.
    for cand in [here.parent.parent.parent, here.parent.parent, *here.parents]:
        if (cand / ".env").exists() or (cand / "src" / "mlomega_audio_elite").exists():
            return cand
    return None


def load_project_env() -> None:
    """Populate MLOMEGA_* env vars from the project .env if not already set.

    Read-only parse: only fills variables that are not already in the
    environment, so an explicit --db / MLOMEGA_DB always wins.
    """
    root = find_project_root()
    if not root:
        return
    env_file = root / ".env"
    if env_file.exists():
        try:
            for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            pass
    if "MLOMEGA_PROJECT_ROOT" not in os.environ:
        os.environ["MLOMEGA_PROJECT_ROOT"] = str(root)


def parse_args() -> argparse.Namespace:
    load_project_env()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", default=os.environ.get("MLOMEGA_DB", ""))
    parser.add_argument("--person-id", default=os.environ.get("MLOMEGA_PERSON_ID", DEFAULT_PERSON_ID))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("MLOMEGA_DASHBOARD_LIMIT", "14")))
    parser.add_argument("--project-root", default=os.environ.get("MLOMEGA_PROJECT_ROOT", ""))
    parser.add_argument("--shadow-report", default=os.environ.get("MLOMEGA_SHADOW_REPORT", ""))
    args, _ = parser.parse_known_args()
    return args


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def find_candidate_dbs() -> list[Path]:
    roots = [Path.cwd(), Path.cwd() / "data", Path.home()]
    env = os.environ.get("MLOMEGA_DB")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser())
    for root in roots:
        if not root.exists():
            continue
        try:
            if root == Path.cwd():
                for pattern in ("*.sqlite", "*.sqlite3", "*.db"):
                    candidates.extend(root.rglob(pattern))
            else:
                for pattern in ("*.sqlite", "*.sqlite3", "*.db"):
                    candidates.extend(root.glob(pattern))
        except Exception:
            pass
    seen: set[str] = set()
    unique: list[Path] = []
    for p in candidates:
        try:
            rp = str(p.resolve()) if p.exists() else str(p)
        except Exception:
            rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        unique.append(p)
    unique.sort(key=lambda p: (0 if re.search(r"mlomega|memory|omega|audio", p.name, re.I) else 1, str(p)))
    return unique[:25]


def connect_readonly(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Base introuvable: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(show_spinner=False, ttl=5)
def file_sha256(db_path: str) -> str:
    digest = hashlib.sha256()
    with Path(db_path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@st.cache_data(show_spinner=False, ttl=2)
def shadow_hidden_ids(db_path: str) -> dict[str, set[str]]:
    hidden: dict[str, set[str]] = {}
    if "owner_quality_shadow_decisions_v19" not in set(list_tables_cached(db_path)):
        return hidden
    con = connect_readonly(db_path)
    try:
        rows = con.execute(
            """SELECT target_table,target_id
               FROM owner_quality_shadow_decisions_v19
               WHERE verdict='confirmed'
                 AND action IN ('suppress_duplicate','suppress_filler')"""
        ).fetchall()
        for row in rows:
            hidden.setdefault(str(row[0]), set()).add(str(row[1]))
    finally:
        con.close()
    return hidden


def filter_shadow_hidden(db_path: str, table: str, df: pd.DataFrame) -> pd.DataFrame:
    ids = shadow_hidden_ids(db_path).get(table) or set()
    if not ids or df.empty:
        return df
    id_columns = [
        column for column in df.columns
        if column == "id" or column.endswith("_id")
    ]
    if not id_columns:
        return df
    id_column = id_columns[0]
    return df[~df[id_column].astype(str).isin(ids)]


@st.cache_data(show_spinner=False, ttl=2)
def list_tables_cached(db_path: str) -> list[str]:
    conn = connect_readonly(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=2)
def get_columns_cached(db_path: str, table: str) -> list[str]:
    conn = connect_readonly(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        return [r[1] for r in rows]
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=2)
def count_table_cached(db_path: str, table: str) -> int:
    conn = connect_readonly(db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}").fetchone()[0])
    except Exception:
        return 0
    finally:
        conn.close()


def order_clause(columns: Iterable[str]) -> str:
    cols = set(columns)
    for c in TIME_COLUMNS:
        if c in cols:
            return f"ORDER BY {quote_ident(c)} DESC"
    return ""


def first_time_column(columns: Iterable[str]) -> Optional[str]:
    cols = set(columns)
    for c in TIME_COLUMNS:
        if c in cols:
            return c
    return None


def first_confidence_column(columns: Iterable[str]) -> Optional[str]:
    cols = set(columns)
    for c in CONFIDENCE_COLUMNS:
        if c in cols:
            return c
    return None


def looks_textual_column(col: str) -> bool:
    return bool(re.search(r"text|json|content|summary|title|name|status|type|reason|why|message|emotion|domain|pattern|question|answer|path|value|note|id|description", col, re.I))


def assign_section(table: str) -> str:
    for section, names in CORE_TABLES.items():
        if table in names:
            return section
    t = table.lower()
    if "clarification" in t:
        return "Clarifications"
    if "intervention" in t:
        return "Interventions"
    if "voice" in t or "speaker" in t or "audio" in t:
        return "Audio & voix"
    if "prediction" in t or "forecast" in t or "causal" in t or "simulation" in t or "trajectory" in t:
        return "Causalité & prédictions"
    if "pattern" in t or "contradiction" in t or "blindspot" in t:
        return "Patterns & contradictions"
    if "language" in t or "word" in t or "expression" in t or "phrase" in t:
        return "Langage & tics"
    if "relationship" in t or "people" in t or "person" in t or "social" in t:
        return "Relations & personnes"
    if "loop" in t or "action" in t or "decision" in t or "commitment" in t:
        return "Open-loops & actions"
    if "self" in t or "memory" in t or "model" in t:
        return "Self-model"
    if "conversation" in t or "turn" in t or "episode" in t or "source" in t or "life" in t:
        return "Timeline & mémoire brute"
    return "Flow & qualité"


def collect_table_infos(db_path: str) -> list[TableInfo]:
    infos: list[TableInfo] = []
    for t in list_tables_cached(db_path):
        infos.append(TableInfo(name=t, count=count_table_cached(db_path, t), columns=tuple(get_columns_cached(db_path, t)), section=assign_section(t)))
    return infos


@st.cache_data(show_spinner=False, ttl=2)
def load_rows_filtered_cached(
    db_path: str,
    table: str,
    limit: int,
    person_id: str,
    date_start: str,
    date_end: str,
    min_confidence: float,
    person_query: str,
    status_query: str,
) -> pd.DataFrame:
    conn = connect_readonly(db_path)
    try:
        cols = get_columns_cached(db_path, table)
        q = f"SELECT * FROM {quote_ident(table)}"
        wheres: list[str] = []
        params: list[Any] = []
        if person_id and "person_id" in cols:
            wheres.append("person_id = ?")
            params.append(person_id)
        tc = first_time_column(cols)
        if date_start and tc:
            wheres.append(f"substr(CAST({quote_ident(tc)} AS TEXT), 1, 10) >= ?")
            params.append(date_start)
        if date_end and tc:
            wheres.append(f"substr(CAST({quote_ident(tc)} AS TEXT), 1, 10) <= ?")
            params.append(date_end)
        cc = first_confidence_column(cols)
        if min_confidence > 0 and cc:
            wheres.append(f"CAST({quote_ident(cc)} AS REAL) >= ?")
            params.append(min_confidence)
        if person_query:
            pcols = [c for c in cols if any(k in c.lower() for k in ["person", "speaker", "name", "relationship"])]
            if pcols:
                wheres.append("(" + " OR ".join([f"CAST({quote_ident(c)} AS TEXT) LIKE ?" for c in pcols]) + ")")
                params.extend([f"%{person_query}%"] * len(pcols))
        if status_query:
            scols = [c for c in cols if c in STATUS_COLUMNS or "status" in c.lower() or "priority" in c.lower()]
            if scols:
                wheres.append("(" + " OR ".join([f"CAST({quote_ident(c)} AS TEXT) LIKE ?" for c in scols]) + ")")
                params.extend([f"%{status_query}%"] * len(scols))
        if wheres:
            q += " WHERE " + " AND ".join(wheres)
        oc = order_clause(cols)
        if oc:
            q += " " + oc
        q += " LIMIT ?"
        params.append(int(limit))
        return pd.read_sql_query(q, conn, params=params)
    except Exception as exc:
        return pd.DataFrame({"error": [str(exc)]})
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=2)
def search_cached(db_path: str, query: str, tables: tuple[str, ...], limit_per_table: int = 5) -> dict[str, pd.DataFrame]:
    if not query.strip():
        return {}
    conn = connect_readonly(db_path)
    out: dict[str, pd.DataFrame] = {}
    try:
        qlike = f"%{query}%"
        for table in tables:
            cols = get_columns_cached(db_path, table)
            text_cols = [c for c in cols if looks_textual_column(c)]
            if not text_cols:
                continue
            wheres = " OR ".join([f"CAST({quote_ident(c)} AS TEXT) LIKE ?" for c in text_cols])
            sql = f"SELECT * FROM {quote_ident(table)} WHERE {wheres}"
            oc = order_clause(cols)
            if oc:
                sql += " " + oc
            sql += " LIMIT ?"
            params = [qlike] * len(text_cols) + [limit_per_table]
            try:
                df = pd.read_sql_query(sql, conn, params=params)
                if not df.empty:
                    out[table] = df
            except Exception:
                continue
        return out
    finally:
        conn.close()


def fmt_num(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def fmt_conf(v: Any) -> str:
    try:
        f = float(v)
        if f <= 1:
            return f"{round(f * 100):.0f}%"
        return f"{f:.2f}"
    except Exception:
        return "—"


def conf_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f <= 1 else f / 100.0
    except Exception:
        return None


def truncate(text: Any, n: int = 240) -> str:
    if text is None:
        return ""
    s = str(text).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def first_existing(row: pd.Series, cols: Iterable[str]) -> Any:
    for c in cols:
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip() != "":
            return row[c]
    return None


def pick_confidence(row: pd.Series) -> Any:
    return first_existing(row, CONFIDENCE_COLUMNS)


def pick_status(row: pd.Series) -> Any:
    return first_existing(row, STATUS_COLUMNS)


def pick_time(row: pd.Series) -> Any:
    return first_existing(row, TIME_COLUMNS)


def pick_title(row: pd.Series) -> str:
    val = first_existing(row, TITLE_COLUMNS)
    if val:
        return truncate(val, 96)
    for c in row.index:
        if c.endswith("_id") and pd.notna(row[c]) and str(row[c]).strip():
            return str(row[c])
    return "Élément"


def pick_body(row: pd.Series) -> str:
    val = first_existing(row, BODY_COLUMNS)
    if val:
        return truncate(val, 330)
    for c, v in row.items():
        if pd.notna(v) and isinstance(v, str) and len(v) > 30:
            return truncate(v, 330)
    return ""


def safe_json_preview(value: Any, max_items: int = 5) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if not isinstance(value, str):
        return truncate(value, 160)
    s = value.strip()
    if not s or s in ["{}", "[]"]:
        return ""
    try:
        obj = json.loads(s)
    except Exception:
        return truncate(s, 220)
    if isinstance(obj, list):
        parts = [truncate(x, 90) if not isinstance(x, dict) else truncate(json.dumps(x, ensure_ascii=False), 120) for x in obj[:max_items]]
        return " • ".join(parts)
    if isinstance(obj, dict):
        parts = []
        for k, v in list(obj.items())[:max_items]:
            parts.append(f"{k}: {truncate(v, 90)}")
        return " • ".join(parts)
    return truncate(obj, 160)


def html_escape(s: Any) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pretty_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if c.endswith("_json") or "json" in c.lower():
            out[c] = out[c].map(lambda x: safe_json_preview(x, max_items=6))
        elif out[c].dtype == object:
            out[c] = out[c].map(lambda x: truncate(x, 360))
    return out


def render_css() -> None:
    st.markdown("""
<style>
:root {
  --card-bg: rgba(255,255,255,.052);
  --card-bg-2: rgba(255,255,255,.032);
  --card-border: rgba(255,255,255,.12);
  --muted: rgba(255,255,255,.68);
}
.main .block-container { max-width: 1480px; padding-top: 1.6rem; }
[data-testid="stSidebar"] { background: rgba(15, 18, 27, .86); }
.hero {
  padding: 24px 26px; border: 1px solid var(--card-border); border-radius: 28px;
  background: radial-gradient(circle at 12% 22%, rgba(130,117,255,.26), transparent 34%),
              radial-gradient(circle at 86% 12%, rgba(78,190,255,.12), transparent 32%),
              linear-gradient(135deg, rgba(255,255,255,.075), rgba(255,255,255,.025));
  box-shadow: 0 18px 50px rgba(0,0,0,.20); margin-bottom: 18px;
}
.hero h1 { margin: 0; font-size: 2.25rem; letter-spacing: -.045em; }
.hero p { margin: 7px 0 0 0; color: var(--muted); font-size: 1rem; }
.card {
  padding: 15px 16px; border: 1px solid var(--card-border); border-radius: 20px; background: var(--card-bg);
  margin-bottom: 11px; min-height: 100px; box-shadow: 0 8px 20px rgba(0,0,0,.10);
}
.card.tight { min-height: 72px; }
.card h4 { margin: 2px 0 7px 0; font-size: 1.03rem; letter-spacing: -.015em; }
.card p { margin: 0; color: var(--muted); font-size: .92rem; line-height: 1.35rem; }
.chip { display:inline-block; padding: 3px 9px; margin: 2px 4px 4px 0; border: 1px solid var(--card-border); border-radius: 999px; color: var(--muted); font-size: .78rem; background: rgba(255,255,255,.035); }
.section-title { margin-top: 24px; padding-top: 6px; font-size: 1.35rem; font-weight: 780; letter-spacing: -.028em; }
.small-muted { color: var(--muted); font-size: .86rem; }
.evidence {
  border-left: 3px solid rgba(255,255,255,.22); padding: 9px 12px; border-radius: 12px;
  background: var(--card-bg-2); margin: 8px 0;
}
hr { opacity: .16; }
.stDataFrame { border: 1px solid rgba(255,255,255,.08); border-radius: 14px; overflow: hidden; }
button[kind="primary"] { border-radius: 12px !important; }
</style>
""", unsafe_allow_html=True)


def card_html(label: str, title: str, body: str, meta: str = "", tight: bool = False) -> str:
    cls = "card tight" if tight else "card"
    return f"""
<div class="{cls}">
  <span class="chip">{html_escape(label)}</span>
  <h4>{html_escape(title or '—')}</h4>
  <p>{html_escape(body or 'Pas de résumé disponible.')}</p>
  <div class="small-muted" style="margin-top:8px;">{html_escape(meta or '')}</div>
</div>
"""


def render_hero(db_path: str, person_id: str, filters: DashFilters, cli: CliConfig) -> None:
    date_span = "toutes dates"
    if filters.date_start or filters.date_end:
        date_span = f"{filters.date_start or 'début'} → {filters.date_end or 'fin'}"
    st.markdown(f"""
<div class="hero">
  <h1>🧠 {APP_TITLE}</h1>
  <p>{APP_SUBTITLE} — personne: <b>{html_escape(person_id)}</b> — DB: <code>{html_escape(Path(db_path).name)}</code></p>
  <p><span class="chip">lecture seule stricte</span><span class="chip">aucun CLI / aucun appel modèle</span><span class="chip">{html_escape(date_span)}</span></p>
  <p class="small-muted">SHA-256 DB : <code>{html_escape(file_sha256(db_path))}</code></p>
</div>
""", unsafe_allow_html=True)


def load_first(db_path: str, tables: list[str], filters: DashFilters, limit: int = 1) -> Optional[tuple[str, pd.DataFrame]]:
    existing = set(list_tables_cached(db_path))
    for t in tables:
        if t not in existing:
            continue
        df = load_rows_filtered_cached(db_path, t, limit, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
        if not df.empty and "error" not in df.columns:
            return t, df
    return None


def compute_reliability(db_path: str, filters: DashFilters) -> dict[str, Any]:
    existing = set(list_tables_cached(db_path))
    verified = correct = partial = wrong = 0
    score_samples: list[float] = []
    for table in ["prediction_results", "v14_4_auto_verify_links", "calibration_scores", "prediction_target_scores"]:
        if table not in existing:
            continue
        df = load_rows_filtered_cached(db_path, table, 500, filters.person_id, filters.date_start, filters.date_end, 0.0, filters.person_query, filters.status_query)
        if df.empty or "error" in df.columns:
            continue
        for _, r in df.iterrows():
            verified += 1
            score = conf_float(first_existing(r, ["match_score", "score", "calibration", "accuracy", "probability", "confidence"]))
            txt = " ".join(str(v).lower() for v in r.values if pd.notna(v))[:2000]
            if score is not None:
                score_samples.append(score)
                if score >= 0.67:
                    correct += 1
                elif score >= 0.34:
                    partial += 1
                else:
                    wrong += 1
            elif any(k in txt for k in ["correct", "matched", "success", "verified", "true"]):
                correct += 1
            elif any(k in txt for k in ["partial", "partly"]):
                partial += 1
            elif any(k in txt for k in ["wrong", "false", "miss", "failed", "incorrect"]):
                wrong += 1
            else:
                partial += 1
    if verified == 0:
        return {"verified": 0, "correct": 0, "partial": 0, "wrong": 0, "score_pct": 0, "label": "non calibré"}
    weighted = (correct + 0.5 * partial) / max(verified, 1)
    if score_samples:
        weighted = (weighted + sum(score_samples) / len(score_samples)) / 2
    return {"verified": verified, "correct": correct, "partial": partial, "wrong": wrong, "score_pct": round(weighted * 100), "label": "mesuré"}


def render_metric_cards(infos: list[TableInfo], db_path: str, filters: DashFilters) -> None:
    counts = {i.name: i.count for i in infos}
    conversations = counts.get("conversations", 0)
    turns = counts.get("turns", 0)
    patterns = sum(counts.get(t, 0) for t in ["v14_pattern_mirror_cards", "patterns", "confirmed_patterns", "candidate_patterns"])
    predictions = sum(counts.get(t, 0) for t in ["v14_trajectory_forecasts", "predictions", "prediction_results", "future_scenarios"])
    loops = sum(counts.get(t, 0) for t in ["v14_5_personal_open_loops", "v14_5_active_questions", "loop_patterns"])
    clarifs = counts.get("v14_8_clarification_items", 0)
    interventions = counts.get("v14_7_intervention_queue", 0)
    reliability = compute_reliability(db_path, filters)
    row_total = sum(i.count for i in infos)
    cols = st.columns(8)
    metrics = [
        ("Tables", len(infos)), ("Lignes", row_total), ("Conversations", conversations), ("Tours", turns),
        ("Patterns", patterns), ("Prédictions", predictions), ("Open-loops", loops), ("Fiabilité", f"{reliability['score_pct']}%"),
    ]
    for col, (label, val) in zip(cols, metrics):
        col.metric(label, fmt_num(val) if isinstance(val, int) else val)
    st.caption(f"Clarifications: {fmt_num(clarifs)} · Interventions: {fmt_num(interventions)}")


def evidence_preview_from_row(row: pd.Series) -> str:
    chunks: list[str] = []
    for c in EVIDENCE_COLUMNS:
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip():
            val = row[c]
            chunks.append(safe_json_preview(val) if "json" in c.lower() else truncate(val, 230))
    return " • ".join([c for c in chunks if c][:2])




def render_selfmodel_front(db_path: str, filters: DashFilters) -> None:
    st.markdown('<div class="section-title">Self-model immédiat</div>', unsafe_allow_html=True)
    st.caption("Le modèle de soi visible sans navigation : identité, traits, besoins, peurs, langage, relations, boucles, prédictions et zones inconnues.")
    cards: list[tuple[str, str, str, str]] = []
    specs = [
        ("Lecture globale", ["v14_3_self_model_exports", "v14_periodic_self_snapshots", "v14_self_model_readings", "v13_user_model_snapshots"]),
        ("Traits / dimensions", ["self_model_dimensions", "self_model_facts", "memory_facets"]),
        ("Besoins / valeurs / peurs", ["self_model_facts", "memory_cards", "v14_3_self_model_export_sections"]),
        ("Langage / tics", ["personal_language_patterns", "expression_signals", "word_signals", "phrase_templates"]),
        ("Pattern dominant", ["v14_pattern_mirror_cards", "confirmed_patterns", "candidate_patterns", "loop_patterns"]),
        ("Relation dominante", ["v14_6_relationship_state_models", "v14_5_relationship_inference_cards", "relationship_models", "v14_6_person_model_summaries"]),
        ("Open-loop actif", ["v14_5_personal_open_loops", "v14_5_active_questions", "v14_5_solution_candidates"]),
        ("Prédiction active", ["v14_trajectory_forecasts", "predictions", "future_scenarios", "latent_outcome_links"]),
        ("Angle mort / inconnu", ["v14_blindspot_hypotheses", "contradiction_events", "counter_evidence_items", "v14_8_clarification_items"]),
    ]
    for label, tables in specs:
        item = load_first(db_path, tables, filters, 1)
        if item:
            table, df = item
            r = df.iloc[0]
            cards.append((label, pick_title(r), pick_body(r) or evidence_preview_from_row(r), f"{table} · {pick_status(r) or '—'} · {fmt_conf(pick_confidence(r))}"))
    if not cards:
        st.info("Le self-model n’a pas encore assez de données pour une synthèse visible.")
        return
    cols = st.columns(3)
    for i, item in enumerate(cards):
        label, title, body, meta = item
        cols[i % 3].markdown(card_html(label, title, body, meta), unsafe_allow_html=True)

def render_today_block(db_path: str, filters: DashFilters) -> None:
    st.markdown('<div class="section-title">Aujourd’hui</div>', unsafe_allow_html=True)
    st.caption("Lecture synthétique des signaux les plus récents : ressenti, boucle active, prédiction, action, clarification et intervention.")
    today_filters = DashFilters(filters.person_id, date.today().isoformat(), date.today().isoformat(), filters.min_confidence, filters.person_query, filters.status_query)
    cards: list[tuple[str, str, str, str]] = []
    specs = [
        ("Ressenti probable", ["internal_state_snapshots", "v14_periodic_self_snapshots", "v14_self_model_readings"], "état"),
        ("Sujet / mémoire dominante", ["memory_cards", "v14_3_self_model_export_sections", "conversations", "turns"], "mémoire"),
        ("Boucle active", ["v14_pattern_mirror_cards", "loop_patterns", "confirmed_patterns", "candidate_patterns"], "pattern"),
        ("Trajectoire à surveiller", ["v14_trajectory_forecasts", "predictions", "future_scenarios", "trajectory_warnings"], "prédiction"),
        ("Prochaine meilleure action", ["v14_5_next_best_actions", "recommended_actions", "v14_7_intervention_queue", "trajectory_interventions"], "action"),
        ("Clarification utile", ["v14_8_clarification_items", "voice_pending_prompts"], "clarification"),
    ]
    for label, tables, fallback_status in specs:
        item = load_first(db_path, tables, today_filters, 1) or load_first(db_path, tables, filters, 1)
        if item:
            table, df = item
            r = df.iloc[0]
            cards.append((label, pick_title(r), pick_body(r) or evidence_preview_from_row(r), f"{table} · {pick_status(r) or fallback_status} · {fmt_conf(pick_confidence(r))}"))
    if not cards:
        st.info("Pas encore assez de données pour construire le bloc Aujourd’hui.")
        return
    cols = st.columns(3)
    for i, item in enumerate(cards):
        label, title, body, meta = item
        cols[i % 3].markdown(card_html(label, title, body, meta), unsafe_allow_html=True)


def render_certainty_panel(db_path: str, infos: list[TableInfo], filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Ce qui est sûr / hypothèse / prédiction</div>', unsafe_allow_html=True)
    facts: list[tuple[str, pd.Series]] = []
    hyps: list[tuple[str, pd.Series]] = []
    preds: list[tuple[str, pd.Series]] = []
    for i in infos:
        if i.count == 0 or i.name in TECHNICAL_TABLES:
            continue
        declared_bucket = certainty_bucket(i.name, {})
        if declared_bucket is None:
            continue
        df = load_rows_filtered_cached(db_path, i.name, min(limit, 8), filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
        df = filter_shadow_hidden(db_path, i.name, df)
        if df.empty or "error" in df.columns:
            continue
        for _, r in df.iterrows():
            bucket = certainty_bucket(i.name, r)
            if bucket == "prediction":
                preds.append((i.name, r))
            elif bucket == "hypothesis":
                hyps.append((i.name, r))
            elif bucket == "fact":
                facts.append((i.name, r))
            if len(facts) >= 10 and len(hyps) >= 10 and len(preds) >= 10:
                break
    cols = st.columns(3)
    buckets = [("✅ Sûr / observé", facts[:5]), ("🧪 Hypothèses", hyps[:5]), ("🔮 Prédictions", preds[:5])]
    for col, (title, rows) in zip(cols, buckets):
        col.markdown(f"**{title}**")
        if not rows:
            col.caption("Aucun élément détecté avec les filtres actuels.")
            continue
        for table, r in rows:
            title_text = human_title(table, r)
            body_text = semantic_text(r, fallback=evidence_preview_from_row(r))
            col.markdown(card_html(table, title_text, body_text, f"{pick_status(r) or '—'} · {fmt_conf(pick_confidence(r))}", tight=True), unsafe_allow_html=True)


def render_reliability_panel(db_path: str, filters: DashFilters) -> None:
    st.markdown('<div class="section-title">Score de fiabilité</div>', unsafe_allow_html=True)
    rel = compute_reliability(db_path, filters)
    cols = st.columns([1.2, 1, 1, 1, 1])
    cols[0].metric("Fiabilité estimée", f"{rel['score_pct']}%", rel["label"])
    cols[1].metric("Vérifiées", fmt_num(rel["verified"]))
    cols[2].metric("Correctes", fmt_num(rel["correct"]))
    cols[3].metric("Partielles", fmt_num(rel["partial"]))
    cols[4].metric("Fausses", fmt_num(rel["wrong"]))
    if rel["verified"]:
        st.progress(min(max(rel["score_pct"] / 100, 0), 1), text="Score calculé à partir des résultats de prédictions / calibration présents dans la DB.")
    else:
        st.warning("Aucune prédiction vérifiée trouvée : le système peut être riche en hypothèses, mais sa fiabilité n’est pas encore mesurée.")


def collect_timeline_events(db_path: str, infos: list[TableInfo], filters: DashFilters, max_rows: int = 400) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    priority_sections = [
        "Timeline & mémoire brute", "Self-model", "Ressenti du jour", "Patterns & contradictions",
        "Causalité & prédictions", "Open-loops & actions", "Relations & personnes", "Interventions", "Clarifications",
    ]
    ordered = sorted([i for i in infos if i.count > 0 and first_time_column(i.columns)], key=lambda x: (priority_sections.index(x.section) if x.section in priority_sections else 99, x.name))
    per_table = max(5, min(40, max_rows // max(len(ordered), 1)))
    for i in ordered:
        df = load_rows_filtered_cached(db_path, i.name, per_table, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
        if df.empty or "error" in df.columns:
            continue
        for _, r in df.iterrows():
            t = pick_time(r)
            if not t:
                continue
            rows.append({"time": str(t), "section": i.section, "table": i.name, "title": pick_title(r), "body": pick_body(r) or evidence_preview_from_row(r), "confidence": fmt_conf(pick_confidence(r))})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_dt"] = pd.to_datetime(out["time"], errors="coerce")
    return out.sort_values("_dt", ascending=False, na_position="last").drop(columns=["_dt"]).head(max_rows)


def render_timeline_graph(db_path: str, infos: list[TableInfo], filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Timeline graphique</div>', unsafe_allow_html=True)
    events = collect_timeline_events(db_path, infos, filters, max_rows=max(300, limit * 25))
    if events.empty:
        st.info("Aucun événement horodaté trouvé avec les filtres actuels.")
        return
    events["day"] = pd.to_datetime(events["time"], errors="coerce").dt.date.astype(str)
    chart = events.groupby(["day", "section"]).size().reset_index(name="count")
    pivot = chart.pivot(index="day", columns="section", values="count").fillna(0).sort_index()
    st.bar_chart(pivot, use_container_width=True)
    with st.expander("Événements récents de la timeline", expanded=True):
        for _, r in events.head(min(30, limit * 2)).iterrows():
            st.markdown(card_html(str(r["section"]), str(r["title"]), str(r["body"]), f"{r['time']} · {r['table']} · {r['confidence']}", tight=True), unsafe_allow_html=True)


def render_evidence_view(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Vue preuves</div>', unsafe_allow_html=True)
    st.caption("Extraits, sources, contre-preuves et observations. C’est la couche qui empêche le dashboard de devenir un simple horoscope IA.")
    existing = set(list_tables_cached(db_path))
    evidence_tables = [t for t in [
        "memory_evidence", "source_spans", "episode_evidence", "v14_5_speaker_name_evidence",
        "counter_evidence_items", "pattern_counterexamples", "v14_4_auto_verify_links",
        "v14_8_clarification_resolution_attempts", "v14_2_noise_guardrail_reports",
    ] if t in existing]
    if not evidence_tables:
        st.info("Aucune table de preuves dédiée trouvée.")
        return
    q = st.text_input("Filtrer les preuves", placeholder="mot, personne, sujet, source...", key="evidence_query")
    shown = 0
    for t in evidence_tables:
        df = load_rows_filtered_cached(db_path, t, limit, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
        if df.empty or "error" in df.columns:
            continue
        if q.strip():
            mask = df.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
            df = df[mask]
        if df.empty:
            continue
        with st.expander(f"{t} — {len(df)} preuve(s)", expanded=shown == 0):
            for _, r in df.head(limit).iterrows():
                title = pick_title(r)
                body = pick_body(r) or evidence_preview_from_row(r)
                meta = f"{pick_time(r) or ''} · {pick_status(r) or ''} · {fmt_conf(pick_confidence(r))}"
                st.markdown(f"""
<div class="evidence">
  <span class="chip">{html_escape(t)}</span>
  <b>{html_escape(title)}</b><br/>
  <span class="small-muted">{html_escape(meta)}</span>
  <p style="margin-top:6px;">{html_escape(body or 'Preuve sans champ texte évident.')}</p>
</div>
""", unsafe_allow_html=True)
            st.dataframe(pretty_df(df), use_container_width=True, hide_index=True)
        shown += 1
    if shown == 0:
        st.info("Aucune preuve ne correspond aux filtres.")


def render_cards_from_df(df: pd.DataFrame, table: str, max_cards: int = 3) -> None:
    rows = list(df.head(max_cards).iterrows())
    if not rows:
        return
    cols = st.columns(min(3, len(rows)))
    for col, (_, row) in zip(cols, rows):
        meta_parts: list[str] = []
        if pick_status(row):
            meta_parts.append(str(pick_status(row)))
        if pick_confidence(row) is not None:
            meta_parts.append(fmt_conf(pick_confidence(row)))
        if pick_time(row):
            meta_parts.append(truncate(pick_time(row), 36))
        col.markdown(card_html(table, pick_title(row), pick_body(row) or evidence_preview_from_row(row), " · ".join(meta_parts)), unsafe_allow_html=True)
        ev = evidence_preview_from_row(row)
        if ev and ev != pick_body(row):
            col.markdown(f'<div class="evidence"><span class="small-muted">preuve</span><br/>{html_escape(ev)}</div>', unsafe_allow_html=True)


def render_section(db_path: str, filters: DashFilters, section: str, tables: list[str], infos_by_name: dict[str, TableInfo], limit: int, compact: bool) -> None:
    existing = [t for t in tables if t in infos_by_name]
    if not existing:
        return
    total_rows = sum(infos_by_name[t].count for t in existing)
    emoji = SECTION_EMOJIS.get(section, "•")
    expanded_defaults = ["Self-model", "Ressenti du jour", "Langage & tics", "Patterns & contradictions", "Causalité & prédictions", "Open-loops & actions"]
    with st.expander(f"{emoji} {section} — {fmt_num(total_rows)} lignes / {len(existing)} tables", expanded=section in expanded_defaults):
        st.caption(SECTION_INTENTS.get(section, ""))
        chip_html = "".join([f'<span class="chip">{t}: {fmt_num(infos_by_name[t].count)}</span>' for t in existing if infos_by_name[t].count > 0])
        if chip_html:
            st.markdown(chip_html, unsafe_allow_html=True)
        else:
            st.caption("Tables présentes mais vides.")
        non_empty = [t for t in existing if infos_by_name[t].count > 0]
        shown = 0
        for t in non_empty[:8 if compact else 18]:
            df = load_rows_filtered_cached(db_path, t, limit, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
            df = filter_shadow_hidden(db_path, t, df)
            if df.empty or "error" in df.columns:
                continue
            st.markdown(f"**{t}**")
            render_cards_from_df(df, table=t, max_cards=3 if compact else 6)
            with st.expander(f"Détails table `{t}`", expanded=False):
                st.dataframe(pretty_df(df), use_container_width=True, hide_index=True)
                evidence_cols = [c for c in df.columns if c in EVIDENCE_COLUMNS or "evidence" in c.lower() or "source" in c.lower()]
                if evidence_cols:
                    st.caption("Colonnes preuves/source détectées : " + ", ".join(evidence_cols))
            shown += 1
        if shown == 0:
            st.info("Aucune ligne à afficher pour les filtres actuels.")


def render_search(db_path: str, infos: list[TableInfo], limit: int) -> None:
    st.markdown('<div class="section-title">Recherche globale</div>', unsafe_allow_html=True)
    q = st.text_input("Chercher dans toutes les tables texte/JSON", placeholder="ex: peur, décision, Max, ok ok, benchmark...")
    if not q.strip():
        return
    non_empty = tuple(i.name for i in infos if i.count > 0)
    results = search_cached(db_path, q, non_empty, limit_per_table=min(limit, 10))
    if not results:
        st.info("Aucun résultat trouvé.")
        return
    st.caption(f"Résultats dans {len(results)} tables.")
    for table, df in results.items():
        with st.expander(f"{table} — {len(df)} résultat(s)", expanded=True):
            render_cards_from_df(df, table, max_cards=min(6, len(df)))
            st.dataframe(pretty_df(df), use_container_width=True, hide_index=True)


def run_cli_command(cli: CliConfig, db_path: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    if not cli.enabled:
        raise RuntimeError("CLI interactif désactivé.")
    base = shlex.split(cli.cli_command.strip() or "mlomega-audio")
    cmd = base + args
    env = os.environ.copy()
    env["MLOMEGA_DB"] = str(Path(db_path).expanduser().resolve())
    if cli.project_root:
        root = Path(cli.project_root).expanduser().resolve()
        env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
        cwd = str(root)
    else:
        cwd = None
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=cli.timeout_seconds)


def render_chat(db_path: str, filters: DashFilters, cli: CliConfig) -> None:
    st.markdown('<div class="section-title">Chat naturel branché sur v14-ask</div>', unsafe_allow_html=True)
    st.caption("Le chat appelle la commande officielle `v14-ask`. Désactivé par défaut pour préserver le mode lecture seule strict.")
    question = st.text_area("Question au cerveau", placeholder="Qu’est-ce que je répète sans le voir ?", height=90)
    col1, col2 = st.columns([1, 3])
    ask = col1.button("Demander à v14-ask", type="primary", disabled=not cli.enabled or not question.strip())
    col2.caption("Active le CLI dans la barre latérale si le bouton est désactivé. `v14-ask` peut écrire des logs selon le projet, donc ce n’est pas le mode lecture seule pur.")
    if ask:
        with st.spinner("Appel de v14-ask…"):
            try:
                cp = run_cli_command(cli, db_path, ["v14-ask", question, "--person-id", filters.person_id])
            except Exception as exc:
                st.error(f"Erreur CLI: {exc}")
                return
        if cp.returncode != 0:
            st.error(f"v14-ask a échoué — code {cp.returncode}")
            if cp.stderr:
                st.code(cp.stderr)
            if cp.stdout:
                st.code(cp.stdout)
        else:
            st.success("Réponse v14-ask")
            out = cp.stdout.strip()
            try:
                st.json(json.loads(out))
            except Exception:
                st.code(out or "(sortie vide)")
            if cp.stderr.strip():
                with st.expander("stderr", expanded=False):
                    st.code(cp.stderr)


def detect_id(row: pd.Series, preferred: list[str]) -> Optional[str]:
    for c in preferred + ["id", "item_id", "queue_id", "clarification_id", "intervention_id"]:
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip():
            return str(row[c])
    for c in row.index:
        if c.endswith("_id") and pd.notna(row[c]) and str(row[c]).strip():
            return str(row[c])
    return None


def render_clarification_write(db_path: str, filters: DashFilters, cli: CliConfig, limit: int) -> None:
    st.markdown('<div class="section-title">Clarifications — réponse contrôlée</div>', unsafe_allow_html=True)
    st.caption("Lecture des questions en attente + réponse via `v14-answer` uniquement si le mode écriture CLI est déverrouillé.")
    existing = set(list_tables_cached(db_path))
    if "v14_8_clarification_items" not in existing:
        st.info("Table `v14_8_clarification_items` absente.")
        return
    status = filters.status_query or "queued"
    df = load_rows_filtered_cached(db_path, "v14_8_clarification_items", limit, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, status)
    if df.empty or "error" in df.columns:
        st.info("Aucune clarification à afficher avec les filtres actuels.")
        return
    for idx, r in df.iterrows():
        item_id = detect_id(r, ["item_id", "clarification_item_id", "clarification_id"])
        with st.container(border=True):
            st.markdown(f"**{pick_title(r)}**")
            st.caption(f"{item_id or 'id inconnu'} · {pick_status(r) or '—'} · {fmt_conf(pick_confidence(r))} · {pick_time(r) or ''}")
            body = pick_body(r) or evidence_preview_from_row(r)
            if body:
                st.write(body)
            answer = st.text_area("Réponse", key=f"clar_answer_{idx}_{item_id}", placeholder="Oui / non / correction naturelle…")
            send = st.button("Envoyer v14-answer", key=f"send_clar_{idx}_{item_id}", disabled=not (cli.enabled and cli.write_enabled and item_id and answer.strip()))
            if send:
                with st.spinner("Envoi de la clarification via CLI…"):
                    try:
                        cp = run_cli_command(cli, db_path, ["v14-answer", item_id, answer, "--person-id", filters.person_id])
                    except Exception as exc:
                        st.error(f"Erreur CLI: {exc}")
                        continue
                if cp.returncode == 0:
                    st.success("Clarification envoyée.")
                    if cp.stdout.strip():
                        st.code(cp.stdout)
                else:
                    st.error(f"Échec v14-answer — code {cp.returncode}")
                    st.code(cp.stderr or cp.stdout)


def render_intervention_feedback(db_path: str, filters: DashFilters, cli: CliConfig, limit: int) -> None:
    st.markdown('<div class="section-title">Interventions — feedback contrôlé</div>', unsafe_allow_html=True)
    st.caption("Feedback via `v14-intervention-feedback`, déverrouillage explicite requis.")
    existing = set(list_tables_cached(db_path))
    if "v14_7_intervention_queue" not in existing:
        st.info("Table `v14_7_intervention_queue` absente.")
        return
    df = load_rows_filtered_cached(db_path, "v14_7_intervention_queue", limit, filters.person_id, filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
    if df.empty or "error" in df.columns:
        st.info("Aucune intervention à afficher avec les filtres actuels.")
        return
    types = ["helpful", "acted", "dismissed", "not_relevant", "too_intrusive", "snoozed", "delivered"]
    for idx, r in df.iterrows():
        queue_id = detect_id(r, ["queue_id", "intervention_queue_id", "intervention_id"])
        with st.container(border=True):
            st.markdown(f"**{pick_title(r)}**")
            st.caption(f"{queue_id or 'id inconnu'} · {pick_status(r) or '—'} · {fmt_conf(pick_confidence(r))} · {pick_time(r) or ''}")
            body = pick_body(r) or evidence_preview_from_row(r)
            if body:
                st.write(body)
            c1, c2, c3 = st.columns([1, 1, 2])
            ftype = c1.selectbox("Feedback", types, key=f"fb_type_{idx}_{queue_id}")
            helpful = c2.slider("Utilité", 0.0, 1.0, 0.5, 0.1, key=f"fb_help_{idx}_{queue_id}")
            note = c3.text_input("Note", key=f"fb_note_{idx}_{queue_id}", placeholder="Pourquoi utile/faux/trop intrusif…")
            action_taken = st.text_input("Action faite", key=f"fb_action_{idx}_{queue_id}", placeholder="Optionnel")
            send = st.button("Envoyer feedback", key=f"send_fb_{idx}_{queue_id}", disabled=not (cli.enabled and cli.write_enabled and queue_id))
            if send:
                args = ["v14-intervention-feedback", queue_id, "--type", ftype, "--person-id", filters.person_id, "--helpfulness", str(helpful)]
                if note.strip():
                    args += ["--note", note]
                if action_taken.strip():
                    args += ["--action-taken", action_taken]
                with st.spinner("Envoi du feedback via CLI…"):
                    try:
                        cp = run_cli_command(cli, db_path, args)
                    except Exception as exc:
                        st.error(f"Erreur CLI: {exc}")
                        continue
                if cp.returncode == 0:
                    st.success("Feedback envoyé.")
                    if cp.stdout.strip():
                        st.code(cp.stdout)
                else:
                    st.error(f"Échec feedback — code {cp.returncode}")
                    st.code(cp.stderr or cp.stdout)


# ---------------------------------------------------------------------------
# V19 — vues dédiées (schémas réels inspectés dans memory.db, jamais devinés).
# Chaque table absente s'affiche « absent » proprement, jamais une stacktrace.
# ---------------------------------------------------------------------------

def _table_exists(db_path: str, table: str) -> bool:
    return table in set(list_tables_cached(db_path))


def _v19_load(db_path: str, table: str, filters: DashFilters, limit: int, order_desc_on: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Read-only load of a V19 table with person filter, or None if absent.

    Returns an empty DataFrame (not None) when the table exists but has no rows.
    """
    if not _table_exists(db_path, table):
        return None
    cols = get_columns_cached(db_path, table)
    conn = connect_readonly(db_path)
    try:
        wheres: list[str] = []
        params: list[Any] = []
        if filters.person_id and "person_id" in cols:
            wheres.append("person_id = ?")
            params.append(filters.person_id)
        q = f"SELECT * FROM {quote_ident(table)}"
        if wheres:
            q += " WHERE " + " AND ".join(wheres)
        oc = None
        if order_desc_on and order_desc_on in cols:
            oc = f"ORDER BY {quote_ident(order_desc_on)} DESC"
        else:
            oc = order_clause(cols)
        if oc:
            q += " " + oc
        q += " LIMIT ?"
        params.append(int(limit))
        return pd.read_sql_query(q, conn, params=params)
    except Exception as exc:  # pragma: no cover - defensive
        return pd.DataFrame({"error": [str(exc)]})
    finally:
        conn.close()


def _v19_absent(table: str) -> None:
    st.caption(f"`{table}` — absent de cette base.")


def _v19_json_chips(row: pd.Series, cols: Iterable[str]) -> str:
    parts: list[str] = []
    for c in cols:
        if c in row.index and pd.notna(row[c]):
            prev = safe_json_preview(row[c]) if "json" in c.lower() else truncate(row[c], 120)
            if prev:
                parts.append(f'<span class="chip">{html_escape(c)}: {html_escape(prev)}</span>')
    return "".join(parts)


def render_v19_hypotheses(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Hypothèses E38 (identité / vie)</div>', unsafe_allow_html=True)
    st.caption("En attente / auto-confirmées / réfutées, avec leurs preuves (`brainlive_life_hypotheses` + `brainlive_hypothesis_evidence`).")
    hyp = _v19_load(db_path, "brainlive_life_hypotheses", filters, max(limit, 60), order_desc_on="updated_at")
    if hyp is None:
        _v19_absent("brainlive_life_hypotheses")
        return
    if hyp.empty:
        st.info("Aucune hypothèse enregistrée pour l'instant.")
        return
    ev = _v19_load(db_path, "brainlive_hypothesis_evidence", filters, 500, order_desc_on="observed_at")
    ev_ok = ev is not None and not ev.empty and "error" not in (ev.columns if ev is not None else [])

    def bucket(status: str) -> str:
        s = str(status or "").lower()
        if any(k in s for k in ["confirm", "observed", "promoted", "auto", "accepted", "resolved"]):
            return "confirmed"
        if any(k in s for k in ["refut", "reject", "false", "contradict", "disproved", "dismiss"]):
            return "refuted"
        return "pending"

    groups: dict[str, list[pd.Series]] = {"pending": [], "confirmed": [], "refuted": []}
    for _, r in hyp.iterrows():
        groups[bucket(r.get("status"))].append(r)

    cols = st.columns(3)
    titles = [("🕓 En attente", "pending"), ("✅ Auto-confirmées", "confirmed"), ("❌ Réfutées", "refuted")]
    for col, (label, key) in zip(cols, titles):
        col.markdown(f"**{label} ({len(groups[key])})**")
        if not groups[key]:
            col.caption("Aucune.")
            continue
        for r in groups[key][:8]:
            hid = str(r.get("hypothesis_id") or "")
            body = truncate(r.get("statement"), 220)
            meta = f"{r.get('hypothesis_type') or '—'} · conf {fmt_conf(r.get('confidence'))} · +{r.get('evidence_count') or 0}/-{r.get('counter_evidence_count') or 0}"
            col.markdown(card_html(str(r.get("status") or key), body, "", meta, tight=True), unsafe_allow_html=True)
            if ev_ok:
                sub = ev[ev["hypothesis_id"] == hid] if "hypothesis_id" in ev.columns else ev.iloc[0:0]
                for _, e in sub.head(3).iterrows():
                    txt = truncate(e.get("evidence_text"), 160)
                    role = e.get("evidence_role") or "preuve"
                    if txt:
                        col.markdown(f'<div class="evidence"><span class="small-muted">{html_escape(role)}</span><br/>{html_escape(txt)}</div>', unsafe_allow_html=True)


def render_v19_life_model(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Life Model V19</div>', unsafe_allow_html=True)
    st.caption("Entrées typées, historique/transitions, prédictions + verification_spec + outcomes + calibration.")

    watches = _v19_load(
        db_path, "brain2_life_model_watch_candidates", filters,
        max(limit, 40), order_desc_on="last_seen_at",
    )
    with st.expander("👀 Candidats Life en observation", expanded=True):
        if watches is None:
            _v19_absent("brain2_life_model_watch_candidates")
        elif watches.empty:
            st.caption("Aucun candidat Life en observation.")
        else:
            for _, raw in watches.iterrows():
                view = life_watch_view(raw)
                promoted = (
                    f" · promu vers {view['promoted_to']}"
                    if view["promoted_to"] else ""
                )
                meta = (
                    f"{view['status']} · {view['occurrences']} occurrence(s) · "
                    f"{view['independent_sources']} source(s) indépendante(s){promoted}"
                )
                source_lines = []
                for source in view["sources"][:5]:
                    if isinstance(source, dict):
                        source_lines.append(
                            f"{source.get('occurred_at') or 'date inconnue'} · "
                            f"{source.get('source_table') or 'source'}:{source.get('source_id') or '—'}"
                        )
                st.markdown(
                    card_html(
                        "watch",
                        view["title"],
                        " | ".join(source_lines) or "Preuve en attente.",
                        meta,
                        tight=True,
                    ),
                    unsafe_allow_html=True,
                )
                with st.expander("Preuves et identifiant technique", expanded=False):
                    st.code(str(view["watch_id"] or ""))
                    st.json(view["sources"])

    with st.expander("🧬 Entrées typées & schéma de soi", expanded=True):
        entries = _v19_load(db_path, "life_model_entries_v19", filters, max(limit, 40), order_desc_on="updated_at")
        if entries is None:
            _v19_absent("life_model_entries_v19")
        elif entries.empty:
            st.info("Aucune entrée de modèle de vie.")
        else:
            for _, r in entries.iterrows():
                meta = f"{r.get('dimension') or '—'} · {r.get('temporal_axis') or '—'} · {r.get('status') or '—'} · conf {fmt_conf(r.get('confidence'))} · vu {truncate(r.get('first_observed'), 20)}→{truncate(r.get('last_confirmed'), 20)}"
                st.markdown(card_html("entry", truncate(r.get("statement"), 200), "", meta, tight=True), unsafe_allow_html=True)
                chips = _v19_json_chips(r, ["verification_spec_json", "prediction_template_json", "revision_history_json"])
                if chips:
                    st.markdown(chips, unsafe_allow_html=True)
        schema = _v19_load(db_path, "self_schema_v19", filters, 30, order_desc_on="updated_at")
        if schema is not None and not schema.empty and "error" not in schema.columns:
            st.markdown("**self_schema_v19**")
            for _, r in schema.iterrows():
                st.markdown(card_html(str(r.get("entry_type") or "schema"), truncate(r.get("statement"), 180), "", f"occurrence {fmt_conf(r.get('occurrence_rate'))}", tight=True), unsafe_allow_html=True)

    with st.expander("🔮 Prédictions, outcomes & calibration", expanded=True):
        preds = _v19_load(db_path, "predictions_v19", filters, max(limit, 40), order_desc_on="emitted_at")
        outs = _v19_load(db_path, "prediction_outcomes_v19", filters, 500, order_desc_on="resolved_at")
        if preds is None:
            _v19_absent("predictions_v19")
        elif preds.empty:
            st.info("Aucune prédiction V19.")
        else:
            out_by_pred: dict[str, pd.Series] = {}
            if outs is not None and not outs.empty and "prediction_id" in outs.columns:
                for _, o in outs.iterrows():
                    out_by_pred[str(o.get("prediction_id"))] = o
            verified = refuted = 0
            for _, r in preds.iterrows():
                pid = str(r.get("prediction_id") or "")
                o = out_by_pred.get(pid)
                ostatus = str(o.get("status")).lower() if o is not None else ""
                if "verif" in ostatus or "correct" in ostatus or "true" in ostatus:
                    verified += 1
                elif "refut" in ostatus or "false" in ostatus or "miss" in ostatus:
                    refuted += 1
                tag = f"outcome: {o.get('status')}" if o is not None else "en attente"
                meta = f"{r.get('status') or '—'} · conf {fmt_conf(r.get('confidence'))} · {truncate(r.get('horizon_start'), 16)}→{truncate(r.get('horizon_end'), 16)} · {tag}"
                st.markdown(card_html("prédiction", truncate(r.get("statement"), 200), "", meta, tight=True), unsafe_allow_html=True)
                chips = _v19_json_chips(r, ["verification_spec_json"])
                if o is not None:
                    chips += _v19_json_chips(o, ["audit_json"])
                if chips:
                    st.markdown(chips, unsafe_allow_html=True)
            st.caption(f"Outcomes : ✅ vérifiées {verified} · ❌ réfutées {refuted} · total prédictions affichées {len(preds)}")
        calib = _v19_load(db_path, "calibration_scores", filters, 30, order_desc_on="calculated_at")
        if calib is None:
            _v19_absent("calibration_scores")
        elif calib.empty:
            st.caption("`calibration_scores` — présent mais vide (pas encore calibré).")
        else:
            st.markdown("**Calibration**")
            st.dataframe(pretty_df(calib), use_container_width=True, hide_index=True)


def render_v19_visual(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Ce qui a réellement été vu</div>', unsafe_allow_html=True)
    st.caption("Réutilise les observations Deep Vision déjà persistées : aucun rappel VLM.")
    ev = _v19_load(db_path, "visual_events_v19", filters, max(limit, 60), order_desc_on="occurred_at")
    assets = _v19_load(db_path, "visual_evidence_assets_v19", filters, 500, order_desc_on="captured_at")
    deep = _v19_load(
        db_path, "brainlive_deep_vision_observations_v161", filters,
        max(limit, 80), order_desc_on="frame_time",
    )
    reuse = _v19_load(
        db_path, "visual_consolidation_deep_reuse_v19", filters,
        500, order_desc_on="updated_at",
    )
    asset_by_id: dict[str, pd.Series] = {}
    asset_by_frame: dict[str, pd.Series] = {}
    if assets is not None and not assets.empty and "visual_asset_id" in assets.columns:
        for _, a in assets.iterrows():
            asset_by_id[str(a.get("visual_asset_id"))] = a
            if a.get("frame_id"):
                asset_by_frame[str(a.get("frame_id"))] = a

    deep_by_frame: dict[str, dict[str, Any]] = {}
    if deep is None:
        _v19_absent("brainlive_deep_vision_observations_v161")
    elif deep.empty:
        st.info("Aucune observation Deep Vision persistée.")
    else:
        for _, r in deep.head(max(limit, 30)).iterrows():
            view = deep_vision_view(r)
            deep_by_frame[str(view["frame_id"] or "")] = view
            cols = st.columns([1, 3])
            image_path = Path(str(view["image_path"] or ""))
            if image_path.is_file():
                cols[0].image(str(image_path), use_container_width=True)
            else:
                cols[0].caption("Miniature absente ou déplacée.")
            people_count = view["people"].get("people_count") if view["people"] else None
            details = []
            if view["activity"]:
                details.append(f"activité : {view['activity']}")
            if view["location"]:
                details.append(f"lieu : {view['location']}")
            if people_count is not None:
                details.append(f"personnes : {people_count}")
            if view["objects"]:
                details.append("objets : " + ", ".join(map(str, view["objects"][:8])))
            if view["visible_text"]:
                details.append("OCR : " + " | ".join(map(str, view["visible_text"][:5])))
            meta = (
                f"{truncate(view['frame_time'], 20)} · raison {view['sample_reason'] or '—'} · "
                f"{view['status'] or '—'} · {view['model'] or '—'}"
            )
            cols[1].markdown(
                card_html(
                    "vision prouvée",
                    truncate(view["title"], 500),
                    " · ".join(details),
                    meta,
                    tight=True,
                ),
                unsafe_allow_html=True,
            )
            if view["uncertainty"]:
                cols[1].caption(
                    "Incertitudes : " + " | ".join(map(str, view["uncertainty"][:4]))
                )
            asset = asset_by_frame.get(str(view["frame_id"] or ""))
            if asset is not None:
                cols[1].caption(
                    f"SHA-256 preuve : {asset.get('sha256') or '—'}"
                )
            with cols[1].expander("Provenance technique", expanded=False):
                st.code(str(view["frame_id"] or ""))
                st.code(str(view["image_path"] or ""))
                st.json({key: r.get(key) for key in r.index if key.endswith("_json")})

    with st.expander("Géométrie VisionRT et événements techniques", expanded=False):
        if ev is None:
            _v19_absent("visual_events_v19")
        elif ev.empty:
            st.caption("Aucun événement géométrique.")
        else:
            invalid = 0
            rows = []
            for _, r in ev.head(max(limit, 80)).iterrows():
                audit = bbox_audit(r.get("observation_json"))
                if audit.get("present") and audit.get("valid") is False:
                    invalid += 1
                refs = parse_json(r.get("evidence_refs_json"), [])
                refs = refs if isinstance(refs, list) else []
                frame_ids = [
                    str(ref).split("frame:", 1)[1]
                    for ref in refs if str(ref).startswith("frame:")
                ]
                linked = next(
                    (deep_by_frame[frame_id]["title"] for frame_id in frame_ids if frame_id in deep_by_frame),
                    "",
                )
                entity = parse_json(r.get("entity_json"), {})
                entity = entity if isinstance(entity, dict) else {}
                rows.append({
                    "date": r.get("occurred_at"),
                    "type": r.get("event_type"),
                    "objet": entity.get("label"),
                    "confiance": r.get("confidence"),
                    "bbox": audit.get("bbox"),
                    "géométrie": audit.get("label"),
                    "résumé Deep Vision lié": linked,
                })
            st.caption(
                f"{len(rows)} événement(s) affiché(s) · {invalid} bbox legacy invalide(s), "
                "signalées mais jamais réparées silencieusement."
            )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Audit technique : assets et réemploi", expanded=False):
        if assets is None:
            _v19_absent("visual_evidence_assets_v19")
        elif assets.empty:
            st.caption("Aucun asset.")
        else:
            st.dataframe(pretty_df(assets), use_container_width=True, hide_index=True)
        if reuse is None:
            _v19_absent("visual_consolidation_deep_reuse_v19")
        elif not reuse.empty:
            st.dataframe(pretty_df(reuse), use_container_width=True, hide_index=True)


def render_v19_world(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Entités, lieux & routines (WorldBrain V19)</div>', unsafe_allow_html=True)
    st.caption("`world_entity_links_v19`, `brain2_spatial_routine_models`, `scene_session_summaries_v19` (attributs changés inclus).")
    specs = [
        ("Liens entités", "world_entity_links_v19", "observed_at"),
        ("Routines spatiales", "brain2_spatial_routine_models", "last_observed"),
        ("Résumés de scène / lieux", "scene_session_summaries_v19", "created_at"),
    ]
    for label, table, order_col in specs:
        with st.expander(f"{label} — `{table}`", expanded=table == "scene_session_summaries_v19"):
            df = _v19_load(db_path, table, filters, max(limit, 40), order_desc_on=order_col)
            if df is None:
                _v19_absent(table)
            elif df.empty:
                st.caption("Présent mais vide.")
            else:
                st.dataframe(pretty_df(df), use_container_width=True, hide_index=True)


def render_v19_sessions(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Sessions live & close-day</div>', unsafe_allow_html=True)
    st.caption("`brainlive_sessions` + `v18_close_day_runs` (multi-sessions du jour, statut `reopened`, durées).")
    sess = _v19_load(db_path, "brainlive_sessions", filters, max(limit, 40), order_desc_on="started_at")
    with st.expander("Sessions live", expanded=True):
        if sess is None:
            _v19_absent("brainlive_sessions")
        elif sess.empty:
            st.caption("Aucune session live enregistrée.")
        else:
            for _, r in sess.iterrows():
                meta = f"{r.get('status') or '—'} · mode {r.get('current_mode') or '—'} · {truncate(r.get('started_at'), 20)} → {truncate(r.get('ended_at'), 20)}"
                st.markdown(card_html("session", truncate(r.get("session_title") or r.get("live_session_id"), 120), truncate(r.get("active_location_hint"), 120), meta, tight=True), unsafe_allow_html=True)
    runs = _v19_load(db_path, "v18_close_day_runs", filters, max(limit, 40), order_desc_on="created_at")
    with st.expander("Close-day runs (dont reopened / multi-sessions)", expanded=True):
        if runs is None:
            _v19_absent("v18_close_day_runs")
        elif runs.empty:
            st.caption("Aucun close-day run.")
        else:
            for _, r in runs.iterrows():
                status = str(r.get("status") or "—")
                flag = " · 🔁 reopened" if "reopen" in status.lower() else ""
                dur = f"{truncate(r.get('created_at'), 20)} → {truncate(r.get('completed_at'), 20)}"
                meta = f"{status}{flag} · jour {r.get('package_date') or '—'} · cleanup {r.get('cleanup_eligible')} · {dur}"
                st.markdown(card_html("close-day", str(r.get("close_day_id") or ""), truncate(r.get("error_text"), 160), meta, tight=True), unsafe_allow_html=True)
                chips = _v19_json_chips(r, ["result_json"])
                if chips:
                    st.markdown(chips, unsafe_allow_html=True)


def render_v19_counters(db_path: str, filters: DashFilters) -> None:
    st.markdown('<div class="section-title">Compteurs live V19</div>', unsafe_allow_html=True)
    st.caption("Interventions H1 livrées / receipts, intents routés — recoupe `/metrics`. Absent = table non présente.")
    existing = set(list_tables_cached(db_path))
    counter_specs = [
        ("Événements visuels", "visual_events_v19"),
        ("Assets preuve visuelle", "visual_evidence_assets_v19"),
        ("Interventions livrées", "brainlive_intervention_deliveries"),
        ("Outcomes interventions", "brainlive_intervention_outcomes_v188"),
        ("Receipts UI (ui outcomes)", "ui_interaction_outcomes_v19"),
        ("Hypothèses de vie", "brainlive_life_hypotheses"),
        ("Prédictions V19", "predictions_v19"),
        ("Sessions live", "brainlive_sessions"),
    ]
    cols = st.columns(4)
    for i, (label, table) in enumerate(counter_specs):
        if table in existing:
            val = fmt_num(count_table_cached(db_path, table))
        else:
            val = "absent"
        cols[i % 4].metric(label, val)


def render_v19_block(db_path: str, filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">🛰️ V19 — ce que la mémoire produit maintenant</div>', unsafe_allow_html=True)
    st.caption("Vues dédiées V19, lecture seule stricte. Toute table absente s'affiche « absent », jamais une erreur.")
    render_v19_counters(db_path, filters)
    render_v19_hypotheses(db_path, filters, limit)
    render_v19_life_model(db_path, filters, limit)
    render_v19_visual(db_path, filters, limit)
    render_v19_world(db_path, filters, limit)
    render_v19_sessions(db_path, filters, limit)


def render_data_coverage(infos: list[TableInfo]) -> None:
    st.markdown('<div class="section-title">Couverture des données</div>', unsafe_allow_html=True)
    rows = []
    for section in CORE_TABLES.keys():
        section_infos = [i for i in infos if i.section == section]
        rows.append({"famille": section, "tables": len(section_infos), "tables non vides": sum(1 for i in section_infos if i.count > 0), "lignes": sum(i.count for i in section_infos)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_shadow_report(report_path: str) -> None:
    st.markdown('<div class="section-title">Audit owner / qualité</div>', unsafe_allow_html=True)
    if not report_path:
        st.caption(
            "Aucun rapport shadow sélectionné. Le Dashboard n’exécute jamais l’audit lui-même."
        )
        return
    path = Path(report_path).expanduser().resolve()
    if not path.is_file():
        st.warning(f"Rapport shadow introuvable : {path}")
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        st.error(f"Rapport shadow illisible : {exc}")
        return
    summary = report.get("summary") or {}
    application = report.get("application") or {}
    cols = st.columns(5)
    cols[0].metric("Candidats", summary.get("candidates", 0))
    cols[1].metric("Confirmés", summary.get("confirmed", 0))
    cols[2].metric("À revoir", summary.get("needs_human", 0))
    cols[3].metric("Coût", f"{float(summary.get('actual_cost_eur') or 0):.4f} €")
    cols[4].metric("Écritures canoniques", application.get("canonical_updates", 0))
    st.caption(
        "Décision DeepSeek → validation codée → opérations bornées. "
        f"Backup : {application.get('backup_db') or 'aucune application'}"
    )
    candidates = {
        str(item.get("candidate_id")): item
        for item in report.get("candidates") or []
    }
    findings = report.get("findings") or []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("verdict") == "not_issue":
            continue
        candidate = candidates.get(str(finding.get("candidate_id"))) or {}
        verdict = str(finding.get("verdict") or "needs_human")
        st.markdown(
            card_html(
                verdict,
                str(candidate.get("title") or candidate.get("kind") or "Constat"),
                str(finding.get("reason") or candidate.get("reason") or ""),
                f"{candidate.get('kind') or 'audit'} · {finding.get('recommended_action') or 'review'}",
                tight=True,
            ),
            unsafe_allow_html=True,
        )
        with st.expander("Preuves et cibles", expanded=False):
            st.json({
                "refs": candidate.get("refs") or [],
                "evidence": candidate.get("evidence"),
                "suggested_action": candidate.get("suggested_action"),
            })
    with st.expander("Rapport brut et appels", expanded=False):
        st.json({
            "source": report.get("source_db"),
            "source_sha256_before": report.get("source_sha256_before"),
            "source_sha256_after": report.get("source_sha256_after"),
            "calls": report.get("calls") or [],
            "application": application,
        })


def render_technical_audit(
    db_path: str, infos: list[TableInfo], filters: DashFilters, limit: int
) -> None:
    existing = {info.name: info for info in infos}
    technical = [table for table in sorted(TECHNICAL_TABLES) if table in existing]
    with st.expander("🔧 Audit technique — lineage, checkpoints, manifests", expanded=False):
        st.caption(
            "Ces lignes prouvent le fonctionnement du pipeline; elles ne sont jamais "
            "présentées comme des souvenirs certains."
        )
        for table in technical:
            st.markdown(f"**{table}** — {existing[table].count} ligne(s)")
            if existing[table].count:
                df = load_rows_filtered_cached(
                    db_path, table, min(limit, 20), filters.person_id,
                    filters.date_start, filters.date_end, 0.0, "", "",
                )
                st.dataframe(pretty_df(df), use_container_width=True, hide_index=True)


def render_debug(db_path: str, infos: list[TableInfo], filters: DashFilters, limit: int) -> None:
    st.markdown('<div class="section-title">Mode debug — toutes les tables</div>', unsafe_allow_html=True)
    st.caption("Chaque table existante est accessible. Le chargement reste en lecture seule.")
    all_sections = sorted(set(i.section for i in infos))
    section_filter = st.multiselect("Filtrer par famille", all_sections, default=[])
    only_non_empty = st.checkbox("Afficher seulement les tables non vides", value=True)
    name_filter = st.text_input("Filtrer par nom de table", placeholder="ex: v14_8, voice, prediction...")
    rows = []
    for i in infos:
        if section_filter and i.section not in section_filter:
            continue
        if only_non_empty and i.count == 0:
            continue
        if name_filter and name_filter.lower() not in i.name.lower():
            continue
        rows.append({"section": i.section, "table": i.name, "rows": i.count, "columns": len(i.columns), "schema": ", ".join(i.columns[:18])})
    df = pd.DataFrame(rows).sort_values(["section", "table"]) if rows else pd.DataFrame()
    st.dataframe(df, use_container_width=True, hide_index=True)
    names = [r["table"] for r in rows]
    if names:
        selected = st.selectbox("Ouvrir une table", names)
        if selected:
            apply_person = st.checkbox("Appliquer filtre person_id à cette table", value=False)
            df2 = load_rows_filtered_cached(db_path, selected, max(limit, 80), filters.person_id if apply_person else "", filters.date_start, filters.date_end, filters.min_confidence, filters.person_query, filters.status_query)
            st.caption(f"{selected} — colonnes: {', '.join(get_columns_cached(db_path, selected))}")
            st.dataframe(pretty_df(df2), use_container_width=True, hide_index=True)
            with st.expander("JSON brut des premières lignes", expanded=False):
                try:
                    st.json(json.loads(df2.head(12).to_json(orient="records", force_ascii=False)))
                except Exception:
                    st.code(df2.head(12).to_string())


def setup_sidebar(args: argparse.Namespace) -> tuple[str, DashFilters, int, bool, CliConfig, str]:
    st.sidebar.markdown("### Base & filtres")
    candidates = find_candidate_dbs()
    default_db = args.db or (str(candidates[0]) if candidates else "")
    db_path = st.sidebar.text_input("Chemin SQLite", value=default_db, placeholder="/chemin/vers/memory.db")
    if candidates:
        picked = st.sidebar.selectbox("Bases détectées", ["—"] + [str(p) for p in candidates], index=0)
        if picked != "—":
            db_path = picked
    person_id = st.sidebar.text_input("Person ID", value=args.person_id or DEFAULT_PERSON_ID)
    c1, c2 = st.sidebar.columns(2)
    start = c1.date_input("Depuis", value=None)
    end = c2.date_input("Jusqu’à", value=None)
    min_conf = st.sidebar.slider("Confiance min.", 0.0, 1.0, 0.0, 0.05)
    person_query = st.sidebar.text_input("Filtre personne/speaker", placeholder="Max, SPEAKER_01…")
    status_query = st.sidebar.text_input("Filtre statut/priorité", placeholder="queued, active, high…")
    limit = st.sidebar.slider("Lignes par table", min_value=3, max_value=120, value=max(3, min(args.limit, 50)), step=1)
    compact = st.sidebar.toggle("Mode compact", value=True)
    filters = DashFilters(person_id=person_id, date_start=start.isoformat() if start else "", date_end=end.isoformat() if end else "", min_confidence=float(min_conf), person_query=person_query.strip(), status_query=status_query.strip())
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Audit shadow (lecture)")
    shadow_report = st.sidebar.text_input(
        "Rapport JSON", value=args.shadow_report or "",
        placeholder="tools/harness/_run/owner-shadow-....json",
    )
    st.sidebar.caption(
        "Aucun bouton d’écriture ni CLI n’existe dans ce Dashboard."
    )
    cli = CliConfig(False, False, "", args.project_root, 0)
    return db_path, filters, limit, compact, cli, shadow_report


def main() -> None:
    args = parse_args()
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="wide", initial_sidebar_state="collapsed")
    render_css()
    db_path, filters, limit, compact, cli, shadow_report = setup_sidebar(args)
    if not db_path:
        st.warning("Indique le chemin de la base SQLite MemoryLight dans la barre latérale.")
        return
    try:
        conn = connect_readonly(db_path)
        conn.close()
    except Exception as exc:
        st.error(f"Impossible d’ouvrir la base en lecture seule: {exc}")
        return
    render_hero(db_path, filters.person_id, filters, cli)
    infos = collect_table_infos(db_path)
    infos_by_name = {i.name: i for i in infos}
    render_metric_cards(infos, db_path, filters)
    render_selfmodel_front(db_path, filters)
    render_today_block(db_path, filters)
    render_certainty_panel(db_path, infos, filters, limit)
    render_reliability_panel(db_path, filters)
    render_timeline_graph(db_path, infos, filters, limit)
    st.markdown("---")
    # E50: the V19 block — what the memory produces NOW (read-only views on the
    # real V19 tables; anything absent renders as "absent", never an error).
    render_v19_block(db_path, filters, limit)
    st.markdown("---")
    render_shadow_report(shadow_report)
    render_technical_audit(db_path, infos, filters, limit)
    render_search(db_path, infos, limit)
    render_evidence_view(db_path, filters, limit)
    st.markdown("---")
    st.markdown('<div class="section-title">Toutes les couches du cerveau</div>', unsafe_allow_html=True)
    st.caption("Une seule page : le self-model reste visible en haut, les couches profondes s’ouvrent ici, et le debug complet reste en bas.")
    for section, tables in CORE_TABLES.items():
        render_section(db_path, filters, section, tables, infos_by_name, limit, compact)
    st.markdown("---")
    render_data_coverage(infos)
    render_debug(db_path, infos, filters, limit)


if __name__ == "__main__":
    main()
