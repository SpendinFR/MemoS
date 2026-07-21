from __future__ import annotations

"""E64-I2 canonical facts emitted once and reused by downstream projections.

This module does not infer cognition.  It losslessly records validated engine
sections, exposes their semantic fields as typed facts, and records empty valid
capabilities.  The latter is important: downstream stages may distinguish
"not analysed" from "analysed, no supported result" without sending the raw
conversation to the LLM again.
"""

import os
import re
from typing import Any, Mapping, Sequence

from .db import connect, init_db, upsert
from .evidence_quality_v19 import (
    OWNER_ALIASES,
    UNCITED_CEILING,
    conversation_baseline_language,
    evidence_ceiling,
    evidence_ceiling_enabled,
    language_quarantine,
    owner_attribution_allowed,
    turn_evidence_quality,
)
from .utils import json_dumps, json_loads, now_iso, sha256_bytes, stable_id


SHARED_FACT_VERSION = "e64-i2-shared-facts-v2-sensor-routing"
SHARED_FACT_ENV = "MLOMEGA_E64_SHARED_FACTS"

_PURPOSE_FACT_TYPES: dict[str, set[str]] = {
    "people_identity": {
        "capture_quality", "situation", "resolved_reference", "missing_context",
        "relationship_update", "social_role", "social_loop", "contradiction",
    },
    "open_loops": {
        "situation", "resolved_reference", "missing_context", "contradiction",
        "choice", "choice_bias", "intention_outcome", "open_loop",
        "trajectory_warning", "escape_condition", "intervention_candidate",
    },
    "interpersonal": {
        "situation", "resolved_reference", "missing_context", "contradiction",
        "internal_state_before", "internal_state_during", "internal_state_after",
        "dominant_emotion", "secondary_emotion", "thought_hypothesis",
        "state_transition", "relationship_update", "social_role", "social_loop",
        "causal_link", "non_causal_correlation", "intention_outcome", "open_loop",
    },
    "outcome_resolution": {
        "situation", "resolved_reference", "missing_context", "contradiction",
        "intention_outcome", "open_loop",
    },
    "subtopic_segmentation": {
        "situation", "resolved_reference", "missing_context",
    },
    "proactive_interventions": {
        "contradiction", "intention_outcome", "open_loop", "prediction",
        "trajectory_warning", "escape_condition", "intervention_candidate",
        "calibration_update",
    },
}

_PURPOSE_CAPABILITY_ENGINES: dict[str, set[str]] = {
    "people_identity": {
        "capture_engine", "context_resolver", "contradiction_engine",
        "episode_builder", "social_model_engine",
    },
    "open_loops": {
        "choice_model_engine", "context_resolver", "contradiction_engine",
        "episode_builder", "intervention_engine", "outcome_tracker",
    },
    "interpersonal": {
        "causality_engine", "context_resolver", "contradiction_engine",
        "episode_builder", "internal_state_engine", "outcome_tracker",
        "social_model_engine",
    },
    "outcome_resolution": {
        "context_resolver", "contradiction_engine", "episode_builder",
        "outcome_tracker",
    },
    "subtopic_segmentation": {"context_resolver", "episode_builder"},
    "proactive_interventions": {
        "calibration_engine", "contradiction_engine", "intervention_engine",
        "outcome_tracker", "prediction_engine",
    },
}

_PURPOSES_USING_SENSOR_SEMANTICS = {
    "interpersonal", "autonomous_candidates", "pattern_mirror",
    "proactive_interventions",
}

_COMMON_FIELDS = {"evidence", "counter_evidence", "confidence"}

FIELD_FACT_TYPES: dict[tuple[str, str], str] = {
    ("episode_builder", "conversation_episode"): "conversation_episode",
    ("episode_builder", "subthemes"): "conversation_subtheme",
    ("episode_builder", "missing_context"): "missing_context",
    ("capture_engine", "capture_quality"): "capture_quality",
    ("capture_engine", "prosody_events"): "prosody_event",
    ("language_signature_engine", "word_predictions"): "language_prediction",
    ("language_signature_engine", "phrase_templates"): "language_template",
    ("language_signature_engine", "style_state"): "language_style",
    ("context_resolver", "situation"): "situation",
    ("context_resolver", "resolved_references"): "resolved_reference",
    ("context_resolver", "missing_context"): "missing_context",
    ("internal_state_engine", "state_before"): "internal_state_before",
    ("internal_state_engine", "state_during"): "internal_state_during",
    ("internal_state_engine", "state_after"): "internal_state_after",
    ("internal_state_engine", "dominant_emotion"): "dominant_emotion",
    ("internal_state_engine", "secondary_emotions"): "secondary_emotion",
    ("internal_state_engine", "thought_hypotheses"): "thought_hypothesis",
    ("internal_state_engine", "state_transitions"): "state_transition",
    ("social_model_engine", "relationship_updates"): "relationship_update",
    ("social_model_engine", "social_roles"): "social_role",
    ("social_model_engine", "conflict_loops"): "social_loop",
    ("causality_engine", "causal_hypotheses"): "causal_link",
    ("causality_engine", "correlations_not_causes"): "non_causal_correlation",
    ("contradiction_engine", "contradictions"): "contradiction",
    ("contradiction_engine", "model_revisions_needed"): "model_revision",
    ("pattern_miner", "signals"): "pattern_signal",
    ("pattern_miner", "candidate_patterns"): "pattern_candidate",
    ("pattern_miner", "confirmed_patterns"): "pattern_confirmed",
    ("choice_model_engine", "choices"): "choice",
    ("choice_model_engine", "predicted_choice_biases"): "choice_bias",
    ("outcome_tracker", "intention_outcome_links"): "intention_outcome",
    ("outcome_tracker", "open_loops"): "open_loop",
    ("similar_case_retrieval", "similar_cases"): "similar_case",
    ("similar_case_retrieval", "clusters"): "case_cluster",
    ("prediction_engine", "predictions"): "prediction",
    ("prediction_engine", "target_scores"): "prediction_target_score",
    ("simulation_engine", "branches"): "simulation_branch",
    ("simulation_engine", "future_scenarios"): "future_scenario",
    ("calibration_engine", "calibration"): "calibration",
    ("calibration_engine", "model_updates"): "calibration_update",
    ("intervention_engine", "trajectory_warnings"): "trajectory_warning",
    ("intervention_engine", "escape_conditions"): "escape_condition",
    ("intervention_engine", "interventions"): "intervention_candidate",
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS brain2_shared_fact_runs_v19 (
  run_id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  person_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  source_digest TEXT,
  status TEXT NOT NULL,
  engine_count INTEGER NOT NULL DEFAULT 0,
  capability_count INTEGER NOT NULL DEFAULT 0,
  fact_count INTEGER NOT NULL DEFAULT 0,
  uncited_fact_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shared_fact_runs_conversation
  ON brain2_shared_fact_runs_v19(conversation_id, episode_id, status);

CREATE TABLE IF NOT EXISTS brain2_shared_engine_sections_v19 (
  section_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  engine_name TEXT NOT NULL,
  applies INTEGER NOT NULL,
  applicability_reason TEXT,
  output_json TEXT,
  output_digest TEXT,
  validation_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(run_id, engine_name),
  FOREIGN KEY(run_id) REFERENCES brain2_shared_fact_runs_v19(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shared_sections_conversation
  ON brain2_shared_engine_sections_v19(conversation_id, engine_name, validation_status);

CREATE TABLE IF NOT EXISTS brain2_shared_capabilities_v19 (
  capability_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  section_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  engine_name TEXT NOT NULL,
  field_name TEXT NOT NULL,
  fact_type TEXT NOT NULL,
  applies INTEGER NOT NULL,
  evaluation_status TEXT NOT NULL,
  applicability_reason TEXT,
  confidence REAL NOT NULL DEFAULT 0.0,
  output_digest TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(run_id, engine_name, field_name),
  FOREIGN KEY(run_id) REFERENCES brain2_shared_fact_runs_v19(run_id) ON DELETE CASCADE,
  FOREIGN KEY(section_id) REFERENCES brain2_shared_engine_sections_v19(section_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shared_capabilities_lookup
  ON brain2_shared_capabilities_v19(conversation_id, engine_name, field_name, evaluation_status);

CREATE TABLE IF NOT EXISTS brain2_shared_facts_v19 (
  fact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  section_id TEXT NOT NULL,
  capability_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  source_engine TEXT NOT NULL,
  source_field TEXT NOT NULL,
  fact_type TEXT NOT NULL,
  subject_ref TEXT,
  epistemic_status TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,
  confidence_ceiling REAL NOT NULL DEFAULT 0.0,
  payload_json TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES brain2_shared_fact_runs_v19(run_id) ON DELETE CASCADE,
  FOREIGN KEY(section_id) REFERENCES brain2_shared_engine_sections_v19(section_id) ON DELETE CASCADE,
  FOREIGN KEY(capability_id) REFERENCES brain2_shared_capabilities_v19(capability_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shared_facts_lookup
  ON brain2_shared_facts_v19(conversation_id, fact_type, source_engine);

CREATE TABLE IF NOT EXISTS brain2_shared_fact_evidence_v19 (
  evidence_link_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL,
  turn_id TEXT NOT NULL,
  citation_role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(fact_id, turn_id, citation_role),
  FOREIGN KEY(fact_id) REFERENCES brain2_shared_facts_v19(fact_id) ON DELETE CASCADE,
  FOREIGN KEY(turn_id) REFERENCES turns(turn_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shared_fact_evidence_turn
  ON brain2_shared_fact_evidence_v19(turn_id, fact_id);
"""

_SCHEMA_READY: set[str] = set()


def shared_facts_enabled() -> bool:
    # E64-I completed a real PhoneOnly minute through the complete CloseDay
    # manifest.  The canonical path is now the product default; operators retain
    # an explicit emergency rollback with MLOMEGA_E64_SHARED_FACTS=0.
    return os.environ.get(SHARED_FACT_ENV, "1").strip() != "0"


def _pro_shared_fact_backfill_enabled() -> bool:
    """Whether missing empty LIST-typed schema keys are backfilled (PRO only).

    Gated behind ``MLOMEGA_PRO_CLOSEDAY``: the cloud (DeepSeek no-think) path omits
    empty list keys the local 9B always emits.  Without the flag the local strict
    validation is unchanged (byte-for-byte hard raise on any missing key).
    """
    return os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def ensure_shared_fact_schema(con: Any | None = None) -> None:
    if con is not None:
        database_row = con.execute("PRAGMA database_list").fetchone()
        database_key = str(database_row[2] if database_row else "connection")
        if database_key not in _SCHEMA_READY:
            con.executescript(_SCHEMA)
            _SCHEMA_READY.add(database_key)
        return
    init_db()
    with connect() as owned:
        owned.executescript(_SCHEMA)
        owned.commit()
        database_row = owned.execute("PRAGMA database_list").fetchone()
        _SCHEMA_READY.add(str(database_row[2] if database_row else "connection"))


def _digest(value: Any) -> str:
    return sha256_bytes(json_dumps(value).encode("utf-8"))


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _compact_context_addenda_for_prompt(value: Any) -> dict[str, Any]:
    """Keep every selected semantic observation, never provider payload blobs."""
    if not isinstance(value, Mapping):
        return {}
    entries: list[dict[str, Any]] = []
    for raw_entry in value.get("entries") or []:
        if not isinstance(raw_entry, Mapping):
            continue
        full_text = str(raw_entry.get("text") or "")
        parts = full_text.split(" | ")
        semantic_parts = parts[:1]
        for part in parts[1:]:
            if part.startswith(("activit\u00e9_visible=", "lieu_probable=", "spatial=")):
                semantic_parts.append(part)
        entry = {
            key: raw_entry.get(key) for key in (
                "addendum_id", "source_table", "source_id", "event_time",
                "evidence_role", "metadata_sha256",
            ) if raw_entry.get(key) is not None
        }
        entry["text"] = " | ".join(semantic_parts)
        entry["full_text_digest"] = _digest(full_text)
        entries.append(entry)
    raw_budget = dict(value.get("budget") or {})
    omitted = list(raw_budget.get("omitted_refs") or [])
    return {
        "entries": entries,
        "budget": {
            "included_items": len(entries),
            "context_incomplete": bool(omitted),
            "omitted_manifest": {
                "count": len(omitted), "digest": _digest(omitted),
            },
        },
        "evidence_role_policy": value.get("evidence_role_policy"),
        "durable_source": "brain2_context_addenda_v18",
    }


_INLINE_TURN_CITATION = re.compile(r"\s*\(turn_ids?\s*:\s*[^)]*\)", re.IGNORECASE)


def _semantic_summary(value: Any) -> str:
    return _INLINE_TURN_CITATION.sub("", str(value or "")).strip()


def _compact_conversation_outline(
    parent: Any, subthemes: Sequence[Any],
) -> dict[str, Any]:
    compact_parent: dict[str, Any] | None = None
    if isinstance(parent, Mapping):
        compact_parent = {
            key: parent.get(key) for key in (
                "episode_id", "episode_type", "start_turn_id", "end_turn_id",
                "start_time", "end_time", "participants", "channel", "topic",
                "outcome_summary", "unresolved_tension", "confidence",
            ) if parent.get(key) is not None
        }
        summary = str(parent.get("situation_summary") or "")
        if summary:
            compact_parent["situation_summary_manifest"] = {
                "digest": _digest(summary),
                "represented_by": "subthemes[].summary",
            }
    compact_subthemes: list[dict[str, Any]] = []
    for raw in subthemes:
        if not isinstance(raw, Mapping):
            continue
        compact = {
            key: raw.get(key) for key in (
                "subtheme_id", "ordinal", "subtheme_type", "title", "summary",
                "start_turn_id", "end_turn_id", "participants",
                "outcome_summary", "unresolved_tension", "confidence",
            ) if raw.get(key) is not None
        }
        compact["summary"] = _semantic_summary(raw.get("summary"))
        memberships = list(raw.get("turn_ids") or [])
        evidence = list(raw.get("evidence_turn_ids") or [])
        compact["membership_manifest"] = {
            "count": len(memberships), "digest": _digest(memberships),
        }
        compact["evidence_manifest"] = {
            "count": len(evidence), "digest": _digest(evidence),
            "durable_source": "episode_subtheme_evidence_v19",
        }
        compact_subthemes.append(compact)
    return {"parent": compact_parent, "subthemes": compact_subthemes}


def _meaningful(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_meaningful(item) for item in value)
    return True


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return [value] if _meaningful(value) else []


def _subject_ref(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in (
        "known_person_id", "other_person_id", "person_id", "main_person",
        "speaker_label", "person_hint", "target_person_id", "source_person_hint",
    ):
        candidate = value.get(key)
        if isinstance(candidate, (str, int)) and str(candidate).strip():
            return str(candidate).strip()
    return None


def _candidate_refs(value: Any) -> list[str]:
    refs: list[str] = []

    def visit(item: Any, *, evidence_context: bool = False) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_context = evidence_context or key in {
                    "turn_id", "evidence_turn_id", "evidence_turn_ids", "evidence",
                    "evidence_ids", "source_turn_id",
                }
                if key_context:
                    visit(child, evidence_context=True)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child, evidence_context=evidence_context)
        elif evidence_context and isinstance(item, (str, int)) and str(item).strip():
            refs.append(str(item).strip())

    visit(value)
    return list(dict.fromkeys(refs))


def _run_id(conversation_id: str, episode_id: str) -> str:
    return stable_id("shared-fact-run-v19", SHARED_FACT_VERSION, conversation_id, episode_id)


def _ensure_run(
    con: Any, *, person_id: str, conversation_id: str, episode_id: str
) -> str:
    ensure_shared_fact_schema(con)
    run_id = _run_id(conversation_id, episode_id)
    now = now_iso()
    existing = con.execute(
        "SELECT created_at FROM brain2_shared_fact_runs_v19 WHERE run_id=?", (run_id,)
    ).fetchone()
    upsert(con, "brain2_shared_fact_runs_v19", {
        "run_id": run_id,
        "version": SHARED_FACT_VERSION,
        "person_id": person_id,
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "source_digest": None,
        "status": "building",
        "engine_count": 0,
        "capability_count": 0,
        "fact_count": 0,
        "uncited_fact_count": 0,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }, "run_id")
    return run_id


def record_engine_output(
    con: Any,
    *,
    person_id: str,
    conversation_id: str,
    episode_id: str,
    engine_name: str,
    output: Mapping[str, Any],
    schema: Mapping[str, Any],
    applicability_reason: str,
) -> dict[str, Any]:
    """Persist one validated section and return its lossless canonical payload."""

    run_id = _ensure_run(
        con, person_id=person_id, conversation_id=conversation_id, episode_id=episode_id
    )
    missing = set(schema) - set(output)
    if missing:
        # PRO (cloud) tolerance — applies uniformly to EVERY engine through this
        # single validation chokepoint, not per engine.  DeepSeek in no-think mode
        # emits terse JSON and OMITS list-valued keys whose value is empty (e.g.
        # contradiction_engine dropping empty ``contradictions`` /
        # ``model_revisions_needed``), where the local 9B always emits ``[]``.
        # That is a shape difference, NOT data loss: an omitted findings-list means
        # "no items".  In PRO we backfill those missing LIST-typed schema keys with
        # ``[]`` so a terse-but-valid cloud output never hard-blocks the close-day.
        # A missing NON-list key (scalar/object) still signals a real structural
        # failure and raises.  The local path keeps the strict raise byte-for-byte.
        if _pro_shared_fact_backfill_enabled():
            backfilled = dict(output)
            unrecoverable: set[str] = set()
            for key in missing:
                if isinstance(schema[key], list):
                    backfilled[key] = []
                else:
                    unrecoverable.add(key)
            if unrecoverable:
                raise ValueError(
                    f"shared_fact_invalid_output:{engine_name}:{sorted(unrecoverable)}"
                )
            output = backfilled
        else:
            raise ValueError(f"shared_fact_invalid_output:{engine_name}:{sorted(missing)}")
    now = now_iso()
    canonical = json_loads(json_dumps(dict(output)), {})
    section_id = stable_id("shared-fact-section-v19", run_id, engine_name)
    output_digest = _digest(canonical)
    upsert(con, "brain2_shared_engine_sections_v19", {
        "section_id": section_id,
        "run_id": run_id,
        "person_id": person_id,
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "engine_name": engine_name,
        "applies": 1,
        "applicability_reason": applicability_reason,
        "output_json": json_dumps(canonical),
        "output_digest": output_digest,
        "validation_status": "valid",
        "created_at": now,
        "updated_at": now,
    }, "section_id")
    con.execute("DELETE FROM brain2_shared_facts_v19 WHERE section_id=?", (section_id,))
    engine_confidence = _clamp(canonical.get("confidence"))
    common_refs = _candidate_refs({
        "evidence": canonical.get("evidence"),
        "counter_evidence": canonical.get("counter_evidence"),
    })
    turn_meta_rows = list(con.execute(
        "SELECT turn_id, person_id, metadata_json FROM turns WHERE conversation_id=?",
        (conversation_id,),
    ))
    valid_turn_ids = {str(row["turn_id"]) for row in turn_meta_rows}
    turn_person_by_id = {
        str(row["turn_id"]): (row["person_id"] if "person_id" in row.keys() else None)
        for row in turn_meta_rows
    }
    turn_metadata_by_id = {
        str(row["turn_id"]): row["metadata_json"] for row in turn_meta_rows
    }
    ceiling_active = evidence_ceiling_enabled()
    baseline_language = (
        conversation_baseline_language(list(turn_metadata_by_id.values()))
        if ceiling_active else None
    )
    for field_name in schema:
        if field_name in _COMMON_FIELDS:
            continue
        value = canonical.get(field_name)
        meaningful = _meaningful(value)
        fact_type = FIELD_FACT_TYPES.get((engine_name, field_name), field_name)
        capability_id = stable_id(
            "shared-capability-v19", run_id, engine_name, field_name
        )
        upsert(con, "brain2_shared_capabilities_v19", {
            "capability_id": capability_id,
            "run_id": run_id,
            "section_id": section_id,
            "person_id": person_id,
            "conversation_id": conversation_id,
            "episode_id": episode_id,
            "engine_name": engine_name,
            "field_name": field_name,
            "fact_type": fact_type,
            "applies": 1,
            "evaluation_status": "produced" if meaningful else "empty_valid",
            "applicability_reason": applicability_reason,
            "confidence": engine_confidence,
            "output_digest": _digest(value),
            "created_at": now,
            "updated_at": now,
        }, "capability_id")
        if not meaningful:
            continue
        for ordinal, item in enumerate(_items(value)):
            if not _meaningful(item):
                continue
            payload_digest = _digest(item)
            fact_id = stable_id(
                "shared-fact-v19", run_id, engine_name, field_name, ordinal, payload_digest
            )
            item_confidence = _clamp(item.get("confidence")) if isinstance(item, Mapping) else 0.0
            confidence = item_confidence if item_confidence else engine_confidence
            refs = list(dict.fromkeys([*_candidate_refs(item), *common_refs]))
            cited = [ref for ref in refs if ref in valid_turn_ids]
            evidence_status = "cited" if cited else "uncited_model_output"
            subject_ref = _subject_ref(item)
            if engine_name == "capture_engine" and field_name == "capture_quality":
                epistemic_status = "system_observation"
            elif field_name == "missing_context":
                epistemic_status = "known_missing"
            else:
                epistemic_status = "inferred" if confidence > 0 else "inferred_unscored"

            if ceiling_active:
                # OBS-29 central policy: a conclusion never exceeds the quality
                # of its real cited evidence, an unenrolled voice never becomes
                # the owner, and an isolated off-language fragment is quarantined
                # (kept raw, flagged) rather than promoted.
                turn_qualities = []
                for ref in cited:
                    quality = turn_evidence_quality(
                        turn_metadata_by_id.get(ref),
                        person_id=turn_person_by_id.get(ref),
                        baseline_language=baseline_language,
                    )
                    quality["turn_id"] = ref
                    turn_qualities.append(quality)
                ceiling_info = evidence_ceiling(confidence, turn_qualities)
                ceiling = ceiling_info["ceiling"]
                quarantine_cause = language_quarantine(turn_qualities)
                owner_claimed = (
                    subject_ref is not None
                    and str(subject_ref).strip().lower() in OWNER_ALIASES
                )
                if quarantine_cause:
                    evidence_status = "quarantined"
                    epistemic_status = "quarantined_low_quality"
                    ceiling = min(ceiling, UNCITED_CEILING)
                elif owner_claimed and not owner_attribution_allowed(turn_qualities):
                    # A model output that attributes an owner trait to a voice
                    # that was never enrolled is demoted, not silently trusted.
                    evidence_status = "owner_attribution_blocked"
                    epistemic_status = "unresolved_owner"
                    subject_ref = None
                    ceiling = min(ceiling, UNCITED_CEILING)
            else:
                ceiling = confidence if cited else min(confidence, 0.49)

            upsert(con, "brain2_shared_facts_v19", {
                "fact_id": fact_id,
                "run_id": run_id,
                "section_id": section_id,
                "capability_id": capability_id,
                "person_id": person_id,
                "conversation_id": conversation_id,
                "episode_id": episode_id,
                "source_engine": engine_name,
                "source_field": field_name,
                "fact_type": fact_type,
                "subject_ref": subject_ref,
                "epistemic_status": epistemic_status,
                "evidence_status": evidence_status,
                "confidence": confidence,
                "confidence_ceiling": ceiling,
                "payload_json": json_dumps(item),
                "payload_digest": payload_digest,
                "created_at": now,
                "updated_at": now,
            }, "fact_id")
            for ref in cited:
                upsert(con, "brain2_shared_fact_evidence_v19", {
                    "evidence_link_id": stable_id(
                        "shared-fact-evidence-v19", fact_id, ref, "model_citation"
                    ),
                    "fact_id": fact_id,
                    "turn_id": ref,
                    "citation_role": "model_citation",
                    "created_at": now,
                }, "evidence_link_id")
    row = con.execute(
        "SELECT output_json FROM brain2_shared_engine_sections_v19 WHERE section_id=?",
        (section_id,),
    ).fetchone()
    rebuilt = json_loads(row["output_json"], {}) if row else {}
    if rebuilt != canonical:
        raise ValueError(f"shared_fact_roundtrip_mismatch:{engine_name}")
    return rebuilt


def record_engine_not_applicable(
    con: Any,
    *,
    person_id: str,
    conversation_id: str,
    episode_id: str,
    engine_name: str,
    schema: Mapping[str, Any],
    reason: str,
) -> None:
    run_id = _ensure_run(
        con, person_id=person_id, conversation_id=conversation_id, episode_id=episode_id
    )
    now = now_iso()
    section_id = stable_id("shared-fact-section-v19", run_id, engine_name)
    upsert(con, "brain2_shared_engine_sections_v19", {
        "section_id": section_id,
        "run_id": run_id,
        "person_id": person_id,
        "conversation_id": conversation_id,
        "episode_id": episode_id,
        "engine_name": engine_name,
        "applies": 0,
        "applicability_reason": reason,
        "output_json": None,
        "output_digest": None,
        "validation_status": "not_applicable",
        "created_at": now,
        "updated_at": now,
    }, "section_id")
    con.execute("DELETE FROM brain2_shared_facts_v19 WHERE section_id=?", (section_id,))
    for field_name in schema:
        if field_name in _COMMON_FIELDS:
            continue
        capability_id = stable_id(
            "shared-capability-v19", run_id, engine_name, field_name
        )
        upsert(con, "brain2_shared_capabilities_v19", {
            "capability_id": capability_id,
            "run_id": run_id,
            "section_id": section_id,
            "person_id": person_id,
            "conversation_id": conversation_id,
            "episode_id": episode_id,
            "engine_name": engine_name,
            "field_name": field_name,
            "fact_type": FIELD_FACT_TYPES.get((engine_name, field_name), field_name),
            "applies": 0,
            "evaluation_status": "not_applicable",
            "applicability_reason": reason,
            "confidence": 0.0,
            "output_digest": None,
            "created_at": now,
            "updated_at": now,
        }, "capability_id")


def record_episode_structure(
    con: Any,
    *,
    person_id: str,
    conversation_id: str,
    episode_id: str,
) -> dict[str, Any]:
    """Project the already validated I1 parent/subthemes into the fact layer."""

    episode_row = con.execute(
        "SELECT * FROM episodes WHERE episode_id=? AND source_conversation_id=?",
        (episode_id, conversation_id),
    ).fetchone()
    if not episode_row:
        raise ValueError(f"shared_fact_episode_missing:{episode_id}")
    episode = dict(episode_row)
    episode_metadata = json_loads(episode.get("metadata_json"), {})
    subthemes: list[dict[str, Any]] = []
    table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_subthemes_v19'"
    ).fetchone()
    if table:
        for row in con.execute(
            "SELECT * FROM episode_subthemes_v19 WHERE episode_id=? ORDER BY ordinal",
            (episode_id,),
        ):
            item = dict(row)
            evidence_rows = [
                dict(evidence) for evidence in con.execute(
                    """SELECT turn_id,evidence_role,confidence
                       FROM episode_subtheme_evidence_v19
                       WHERE subtheme_id=? ORDER BY turn_id,evidence_role""",
                    (item["subtheme_id"],),
                )
            ]
            item["turn_ids"] = list(dict.fromkeys(
                str(evidence["turn_id"]) for evidence in evidence_rows
                if evidence["evidence_role"] == "membership"
            ))
            item["evidence_turn_ids"] = list(dict.fromkeys(
                str(evidence["turn_id"]) for evidence in evidence_rows
                if evidence["evidence_role"] == "primary_citation"
            ))
            item["evidence_manifest"] = evidence_rows
            subthemes.append(item)
    output = {
        "conversation_episode": {
            key: episode.get(key) for key in (
                "episode_id", "episode_type", "start_time", "end_time",
                "start_turn_id", "end_turn_id", "participants_json", "channel",
                "topic", "situation_summary", "trigger_summary", "outcome_summary",
                "unresolved_tension", "confidence", "truth_status",
            )
        },
        "subthemes": subthemes,
        "missing_context": episode_metadata.get("missing_context") or [],
        "evidence": [
            str(row["turn_id"]) for row in con.execute(
                "SELECT turn_id FROM episode_evidence WHERE episode_id=? ORDER BY created_at",
                (episode_id,),
            ) if row["turn_id"]
        ],
        "counter_evidence": [],
        "confidence": _clamp(episode.get("confidence")),
    }
    return record_engine_output(
        con,
        person_id=person_id,
        conversation_id=conversation_id,
        episode_id=episode_id,
        engine_name="episode_builder",
        output=output,
        schema={
            "conversation_episode": {}, "subthemes": [], "missing_context": [],
            "evidence": [], "counter_evidence": [], "confidence": 0.0,
        },
        applicability_reason="validated_e64i_parent_and_subthemes",
    )


def finish_episode_fact_run(con: Any, *, conversation_id: str, episode_id: str) -> dict[str, int]:
    run_id = _run_id(conversation_id, episode_id)
    sections = int(con.execute(
        "SELECT COUNT(*) AS c FROM brain2_shared_engine_sections_v19 WHERE run_id=?",
        (run_id,),
    ).fetchone()["c"])
    capabilities = int(con.execute(
        "SELECT COUNT(*) AS c FROM brain2_shared_capabilities_v19 WHERE run_id=?",
        (run_id,),
    ).fetchone()["c"])
    facts = int(con.execute(
        "SELECT COUNT(*) AS c FROM brain2_shared_facts_v19 WHERE run_id=?",
        (run_id,),
    ).fetchone()["c"])
    uncited = int(con.execute(
        """SELECT COUNT(*) AS c FROM brain2_shared_facts_v19
           WHERE run_id=? AND evidence_status='uncited_model_output'""",
        (run_id,),
    ).fetchone()["c"])
    digests = [
        str(row["output_digest"] or "not_applicable")
        for row in con.execute(
            """SELECT output_digest FROM brain2_shared_engine_sections_v19
               WHERE run_id=? ORDER BY engine_name""",
            (run_id,),
        )
    ]
    con.execute(
        """UPDATE brain2_shared_fact_runs_v19
           SET source_digest=?, status='complete', engine_count=?, capability_count=?,
               fact_count=?, uncited_fact_count=?, updated_at=? WHERE run_id=?""",
        (_digest(digests), sections, capabilities, facts, uncited, now_iso(), run_id),
    )
    return {
        "engines": sections, "capabilities": capabilities,
        "facts": facts, "uncited_facts": uncited,
    }


def compact_fact_bundle(con: Any, conversation_id: str) -> dict[str, Any]:
    ensure_shared_fact_schema(con)
    facts = []
    for row in con.execute(
        """SELECT fact_id,episode_id,source_engine,source_field,fact_type,subject_ref,
                  epistemic_status,evidence_status,confidence,confidence_ceiling,payload_json
           FROM brain2_shared_facts_v19
           WHERE conversation_id=? ORDER BY episode_id,source_engine,source_field,fact_id""",
        (conversation_id,),
    ):
        item = dict(row)
        item["payload"] = json_loads(item.pop("payload_json"), None)
        facts.append(item)
    capabilities = [
        dict(row) for row in con.execute(
            """SELECT episode_id,engine_name,field_name,fact_type,applies,evaluation_status,
                      applicability_reason,confidence
               FROM brain2_shared_capabilities_v19
               WHERE conversation_id=? ORDER BY episode_id,engine_name,field_name""",
            (conversation_id,),
        )
    ]
    return {
        "version": SHARED_FACT_VERSION,
        "conversation_id": conversation_id,
        "facts": facts,
        "capabilities": capabilities,
    }


def _table_rows(
    con: Any, table: str, *, where: str = "", params: Sequence[Any] = (), limit: int = 40
) -> list[dict[str, Any]]:
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return []
    suffix = f" WHERE {where}" if where else ""
    rows = [dict(row) for row in con.execute(
        f"SELECT * FROM {table}{suffix} ORDER BY rowid DESC LIMIT ?", (*params, int(limit))
    )]
    # Stable identifiers and semantic values are retained. Repeated bookkeeping
    # timestamps and raw provider blobs stay in their source tables.
    for row in rows:
        for key in list(row):
            if key in {"created_at", "updated_at", "raw_json", "metadata_json"} or any(
                marker in key.lower() for marker in ("embedding", "vector", "centroid")
            ):
                row.pop(key, None)
    return rows


def _prompt_payload_value(
    value: Any, turn_ref_by_id: Mapping[str, str] | None = None
) -> Any:
    """Remove storage duplication while retaining every semantic value."""

    if isinstance(value, list):
        return [_prompt_payload_value(item, turn_ref_by_id) for item in value]
    if isinstance(value, str) and turn_ref_by_id and value in turn_ref_by_id:
        return turn_ref_by_id[value]
    if not isinstance(value, Mapping):
        return value
    current_turn_id = value.get("turn_id")
    current_turn_ref = (
        turn_ref_by_id.get(str(current_turn_id))
        if turn_ref_by_id and current_turn_id is not None else None
    )
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"created_at", "updated_at", "evidence_manifest"}:
            continue
        # Exact transcript text is already present once in `turns`.  Evidence
        # objects for the current conversation retain the lossless short turn
        # reference plus all non-duplicated roles/scores.
        if current_turn_ref and key in {"text", "evidence_text", "value"}:
            continue
        if key == "metadata_json":
            metadata = json_loads(item, {})
            if isinstance(metadata, Mapping):
                for metadata_key in (
                    "boundary_reason", "episode_contract", "membership_count",
                    "primary_citation_count",
                ):
                    if metadata_key in metadata:
                        result[metadata_key] = _prompt_payload_value(
                            metadata[metadata_key], turn_ref_by_id
                        )
            continue
        if key.endswith("_json") and isinstance(item, str):
            decoded = json_loads(item, item)
            result[key[:-5]] = _prompt_payload_value(decoded, turn_ref_by_id)
            continue
        result["turn_ref" if key == "turn_id" and current_turn_ref else key] = (
            current_turn_ref
            if key == "turn_id" and current_turn_ref
            else _prompt_payload_value(item, turn_ref_by_id)
        )
    return result


def _prompt_facts(
    fact_bundle: Mapping[str, Any], turn_ref_by_id: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = [
        {
            "source": f"{fact['source_engine']}.{fact['source_field']}",
            "type": fact["fact_type"],
            "subject": fact.get("subject_ref"),
            "status": fact["epistemic_status"],
            "evidence_status": fact["evidence_status"],
            "confidence": fact["confidence"],
            "confidence_ceiling": fact["confidence_ceiling"],
            "value": _prompt_payload_value(fact.get("payload"), turn_ref_by_id),
        }
        for fact in fact_bundle.get("facts", [])
    ]
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for capability in fact_bundle.get("capabilities", []):
        key = (str(capability["episode_id"]), str(capability["engine_name"]))
        group = grouped.setdefault(key, {
            "engine": key[1],
            "produced": [], "empty_valid": [], "not_applicable": [], "invalid": [],
            "reason": capability.get("applicability_reason"),
        })
        status = str(capability.get("evaluation_status") or "invalid")
        bucket = status if status in {"produced", "empty_valid", "not_applicable"} else "invalid"
        group[bucket].append(str(capability["field_name"]))
    compact_groups: list[dict[str, Any]] = []
    for group in grouped.values():
        populated = [
            key for key in ("produced", "empty_valid", "not_applicable", "invalid")
            if group[key]
        ]
        if len(populated) == 1:
            compact_groups.append({
                "engine": group["engine"],
                "verdict": populated[0],
                "reason": group["reason"],
            })
        else:
            compact_groups.append({
                key: value for key, value in group.items()
                if key in {"engine", "reason"} or value
            })
    return facts, compact_groups


def conversation_turn_refs(con: Any, conversation_id: str) -> dict[str, str]:
    """Stable ``turn_id -> t0..tN`` map for one conversation.

    Codex cost point B: the compact fact form replaces the LONG ``turn_id``
    (~45 chars, repeated twice per fact via ``evidence_manifest``) with a short
    ordinal ref.  The map is built from the same ``turns`` ordering the stage
    projections use, so refs are identical byte-for-byte across projections.
    """

    return {
        str(row["turn_id"]): f"t{ordinal}"
        for ordinal, row in enumerate(
            con.execute(
                "SELECT turn_id FROM turns WHERE conversation_id=? ORDER BY idx",
                (conversation_id,),
            )
        )
    }


# Verbose provenance/bookkeeping keys that repeat identically across facts (the
# episode/section/run identity already travels once in the fact envelope) or that
# only duplicate what a downstream engine can re-read from DB.  They are dropped
# from the payload VALUE sent to the prompt; the complete payload stays lossless
# in ``brain2_shared_facts_v19.payload_json``.  Codex point B (going further than
# the ~23k core toward ~8-12k): ~60-100 tok/fact instead of the full payload.
_PAYLOAD_PROVENANCE_KEYS = frozenset({
    "episode_id", "source_episode_id", "conversation_id", "person_id",
    "run_id", "section_id", "capability_id", "fact_id", "source_id",
    "source_table", "source_field", "source_engine", "provenance",
    "created_at", "updated_at", "evidence_manifest", "metadata_sha256",
    "digest", "payload_digest", "output_digest", "full_text_digest",
    "schema_version", "version",
})

# Per-fact value string cap: an essential semantic value, not a re-embedded
# transcript.  Long strings are kept as a bounded semantic head plus a manifest
# so nothing is silently truncated (the full text remains in DB).
_COMPACT_VALUE_STRING_CAP = 400


def _essential_payload_value(value: Any, refs: Mapping[str, str]) -> Any:
    """Trim a fact payload to its essential semantic value for the prompt.

    Drops the repeated provenance/bookkeeping keys (already carried once by the
    fact envelope / recoverable from DB), replaces long turn ids by short refs,
    and bounds very long free-text strings with a lossless manifest.  Never
    fabricates: absent means absent, the authoritative payload stays in DB.
    """

    if isinstance(value, list):
        return [_essential_payload_value(item, refs) for item in value]
    if isinstance(value, str):
        if refs and value in refs:
            return refs[value]
        if len(value) > _COMPACT_VALUE_STRING_CAP:
            return {
                "head": value[:_COMPACT_VALUE_STRING_CAP],
                "full_len": len(value),
                "digest": _digest(value),
            }
        return value
    if not isinstance(value, Mapping):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in _PAYLOAD_PROVENANCE_KEYS:
            continue
        result[key] = _essential_payload_value(item, refs)
    return result


def compact_facts_for_prompt(
    fact_bundle: Mapping[str, Any],
    turn_ref_by_id: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Serialise canonical facts into the COMPACT prompt form (Codex point B).

    Unlike :func:`_prompt_facts` (which drops provenance for the stage prompt),
    this keeps ``source_engine`` so a caller can PROJECT facts per dependent
    engine (Codex point A).  Everything else is the trimmed form:

    * a short ``f0..fN`` fact ref plus a short ``ep`` episode ref, so the long
      ``episode_id`` (repeated once per fact) travels a single time in
      ``episode_index`` — see :func:`compact_fact_registry`;
    * short turn refs instead of long ``turn_id``s;
    * the ``evidence_manifest`` dropped (every role/turn already lives once in DB
      and in the payload's own evidence lists) plus every other repeated
      provenance/bookkeeping key (``_PAYLOAD_PROVENANCE_KEYS``);
    * bounded free-text (long strings become a head + digest manifest);
    * subject + type + essential value + rounded confidence only.

    The full evidence stays authoritative in ``brain2_shared_facts_v19``.
    """

    refs = turn_ref_by_id or {}
    compact: list[dict[str, Any]] = []
    for fact in fact_bundle.get("facts", []):
        confidence = fact.get("confidence")
        item = {
            "ref": f"{fact['source_engine']}.{fact['source_field']}",
            "source_engine": fact["source_engine"],
            "episode_id": fact.get("episode_id"),
            "type": fact["fact_type"],
            "subject": fact.get("subject_ref"),
            "status": fact["epistemic_status"],
            "evidence_status": fact["evidence_status"],
            "confidence": round(float(confidence), 3) if confidence is not None else None,
            "value": _essential_payload_value(fact.get("payload"), refs),
        }
        compact.append({key: value for key, value in item.items() if value is not None})
    return compact


def compact_fact_registry(
    fact_bundle: Mapping[str, Any],
    turn_ref_by_id: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The ~8-12k canonical fact CORE (Codex point 2): short refs, deduped ids.

    Wraps :func:`compact_facts_for_prompt` and factorises the repeated ``episode_id``
    (one long string per fact) into a single ``episode_index`` (``ep0..epN``),
    assigns every fact a short ``id`` (``f0..fN``), and drops the verbose
    ``epistemic_status``/``evidence_status`` label pair down to single-letter
    status codes.  Callers that only need the projection by ``source_engine``
    keep using the list form; this registry is what feeds the prompt / the shared
    cache prefix so the common core lands near ~60-100 tok/fact.

    The projected list still carries ``source_engine`` so
    ``_facts_for_global_engine`` keeps working unchanged.
    """

    facts = compact_facts_for_prompt(fact_bundle, turn_ref_by_id)
    episode_index: dict[str, str] = {}
    registry: list[dict[str, Any]] = []
    for ordinal, fact in enumerate(facts):
        episode_id = fact.get("episode_id")
        episode_ref = None
        if episode_id is not None:
            episode_ref = episode_index.get(str(episode_id))
            if episode_ref is None:
                episode_ref = f"ep{len(episode_index)}"
                episode_index[str(episode_id)] = episode_ref
        # ``ref`` already encodes ``source_engine.source_field`` and ``type`` is
        # ``source_field`` — both are recoverable from ``ref``, so the registry
        # (prompt-facing core) drops the duplicates.  The projection by
        # ``source_engine`` uses the list form, which keeps them.
        entry = {
            "id": f"f{ordinal}",
            "ref": fact["ref"],
        }
        if episode_ref is not None:
            entry["ep"] = episode_ref
        if fact.get("subject") is not None:
            entry["subject"] = fact["subject"]
        # Single-letter epistemic/evidence status codes drop two repeated verbose
        # labels to two characters without losing the distinction.
        status = str(fact.get("status") or "")
        evidence_status = str(fact.get("evidence_status") or "")
        if status:
            entry["s"] = status[:1]
        if evidence_status:
            entry["e"] = evidence_status[:1]
        if fact.get("confidence") is not None:
            entry["c"] = fact["confidence"]
        if "value" in fact:
            entry["v"] = fact["value"]
        registry.append({key: value for key, value in entry.items() if value is not None})
    return {
        "episode_index": {ref: episode_id for episode_id, ref in episode_index.items()},
        "facts": registry,
    }


def compact_stage_input(
    con: Any,
    conversation_id: str,
    *,
    person_id: str,
    purpose: str,
) -> dict[str, Any]:
    """Build one bounded semantic input without hiding any conversation turn.

    The raw rows remain authoritative in SQLite.  This projection keeps exact
    text, speaker, person, ordering and timestamps once; engine facts and their
    empty/produced verdicts are referenced separately instead of embedding the
    same historical tables in every prompt.
    """

    fact_bundle = compact_fact_bundle(con, conversation_id)
    conversation_row = con.execute(
        "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
    ).fetchone()
    if not conversation_row:
        raise ValueError(f"conversation introuvable: {conversation_id}")
    conversation = dict(conversation_row)
    conversation = {
        key: conversation.get(key) for key in (
            "conversation_id", "title", "started_at", "ended_at", "channel",
            "participants_json", "speaker_map_json", "relationship_context_json",
        )
    }
    conversation.pop("title", None)
    for json_key in ("participants_json", "speaker_map_json", "relationship_context_json"):
        if json_key in conversation:
            conversation[json_key[:-5]] = json_loads(conversation.pop(json_key), None)
    conversation_started_at = str(conversation.get("started_at") or "9999-12-31")
    from .v18_brain2_context import conversation_context_addenda
    raw_context_addenda = conversation_context_addenda(
        con, conversation_id=conversation_id, person_id=person_id,
        # The reader itself is capped at 120 active rows.  Request them all,
        # then remove provider metadata before the orchestrator budgets text.
        max_items=120, max_chars=240000,
    )
    context_addenda = _compact_context_addenda_for_prompt(raw_context_addenda)
    has_deep_context = any(
        str(entry.get("source_table") or "")
        == "brainlive_deep_vision_observations_v161"
        for entry in context_addenda.get("entries") or []
        if isinstance(entry, Mapping)
    )
    if has_deep_context and purpose not in _PURPOSES_USING_SENSOR_SEMANTICS:
        available_entries = list(context_addenda.get("entries") or [])
        context_addenda = {
            "entries": [],
            "available_manifest": {
                "count": len(available_entries),
                "digest": _digest(available_entries),
                "routed_to": [
                    "visual_consolidation", "worldbrain", "silent_life",
                ],
                "reason": f"sensor_semantics_outside_{purpose}_responsibility",
            },
            "evidence_role_policy": context_addenda.get("evidence_role_policy"),
            "durable_source": "brain2_context_addenda_v18",
        }
    turns: list[dict[str, Any]] = []
    sensor_turns: list[dict[str, Any]] = []
    speaker_resolutions: dict[str, dict[str, Any]] = {}
    all_turn_rows = list(con.execute(
        """SELECT turn_id,idx,speaker_label,person_id,start_s,end_s,text,metadata_json
           FROM turns WHERE conversation_id=? ORDER BY idx""",
        (conversation_id,),
    ))
    parsed_turn_rows: list[tuple[Any, dict[str, Any], bool]] = []
    for row in all_turn_rows:
        metadata = json_loads(row["metadata_json"], {})
        metadata = metadata if isinstance(metadata, dict) else {}
        is_sensor = (
            str(metadata.get("evidence_role") or "")
            == "system_observation_not_user_speech"
        )
        parsed_turn_rows.append((row, metadata, is_sensor))
        if is_sensor:
            sensor_turns.append({
                "turn_id": row["turn_id"], "idx": row["idx"],
                "start_s": row["start_s"], "end_s": row["end_s"],
                "text_digest": _digest(str(row["text"] or "")),
                "kind": metadata.get("kind"),
            })
    included_rows = [
        (row, metadata) for row, metadata, is_sensor in parsed_turn_rows
        if not (is_sensor and has_deep_context)
    ]
    turn_ref_by_id = {
        str(row["turn_id"]): f"t{ordinal}"
        for ordinal, (row, _metadata) in enumerate(included_rows)
    }
    turn_id_by_ref = {ref: turn_id for turn_id, ref in turn_ref_by_id.items()}
    for row, metadata in included_rows:
        turn = dict(row)
        turn["turn_id"] = turn_ref_by_id[str(turn["turn_id"])]
        turn.pop("metadata_json", None)
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        resolution = (
            source.get("offline_speaker_resolution")
            if isinstance(source, Mapping) else None
        )
        if isinstance(resolution, Mapping):
            resolution_key = str(
                resolution.get("cluster_id") or resolution.get("person_id")
                or turn.get("person_id") or turn.get("speaker_label")
            )
            speaker_resolutions[resolution_key] = {
                key: resolution.get(key) for key in (
                    "cluster_id", "decision", "duration_s", "known_score",
                    "person_id", "speaker_label",
                )
            }
        turn["source_quality"] = {
            "evidence_role": metadata.get("evidence_role") if isinstance(metadata, Mapping) else None,
            "kind": metadata.get("kind") if isinstance(metadata, Mapping) else None,
        }
        turns.append(turn)

    current_people = list(dict.fromkeys(
        str(turn.get("person_id")) for turn in turns if turn.get("person_id")
    ))
    identity_history = {
        "speaker_profiles": _table_rows(con, "speaker_profiles", limit=24),
        "voice_clusters": _table_rows(con, "voice_clusters", limit=24),
        "identity_hypotheses": _table_rows(
            con, "v14_5_people_identity_hypotheses",
            where="conversation_id<>?", params=(conversation_id,), limit=24,
        ),
        "relationship_cards": _table_rows(
            con, "v14_5_relationship_inference_cards",
            where="conversation_id<>?", params=(conversation_id,), limit=24,
        ),
        "relationship_models": _table_rows(
            con, "relationship_models",
            where="(person_a=? OR person_b=?) AND updated_at<?",
            params=(person_id, person_id, conversation_started_at), limit=24,
        ),
    }
    open_loop_history = {
        "active_open_loops": _table_rows(
            con, "v14_5_personal_open_loops",
            where="person_id=? AND current_status NOT IN ('resolved','contradicted') AND updated_at<?",
            params=(person_id, conversation_started_at), limit=40,
        ),
        "active_questions": _table_rows(
            con, "v14_5_active_questions",
            where="person_id=? AND status='open' AND updated_at<?",
            params=(person_id, conversation_started_at), limit=40,
        ),
    }
    interpersonal_history = {
        "people_context_profiles": _table_rows(
            con, "v14_5_people_context_profiles", where="person_id=?",
            params=(person_id,), limit=24,
        ),
        "relationship_state_models": _table_rows(
            con, "v14_6_relationship_state_models",
            where="person_id=? AND updated_at<?",
            params=(person_id, conversation_started_at), limit=24,
        ),
        "open_social_aftereffects": _table_rows(
            con, "v14_6_social_aftereffects",
            where="person_id=? AND status='open' AND updated_at<?",
            params=(person_id, conversation_started_at), limit=24,
        ),
    }
    history: dict[str, Any] = {}
    if purpose == "people_identity":
        history = identity_history
    elif purpose == "open_loops":
        history = open_loop_history
    elif purpose == "interpersonal":
        current_identity_history = {
            **identity_history,
            "identity_hypotheses": _table_rows(
                con, "v14_5_people_identity_hypotheses", limit=24
            ),
            "relationship_cards": _table_rows(
                con, "v14_5_relationship_inference_cards", limit=24
            ),
        }
        history = {**current_identity_history, **interpersonal_history}
    elif purpose in {"autonomous_candidates", "pattern_mirror"}:
        current_episode_ids = {
            str(fact.get("episode_id")) for fact in fact_bundle.get("facts", [])
            if fact.get("episode_id")
        }

        def without_current_episode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                row for row in rows
                if not row.get("episode_id")
                or str(row.get("episode_id")) not in current_episode_ids
            ]

        history = {
            "prior_candidate_patterns": without_current_episode(
                _table_rows(con, "candidate_patterns", where="person_id=?", params=(person_id,), limit=40)
            ),
            "confirmed_patterns": without_current_episode(
                _table_rows(con, "confirmed_patterns", where="person_id=?", params=(person_id,), limit=40)
            ),
            "known_loops": without_current_episode(
                _table_rows(con, "loop_patterns", where="person_id=?", params=(person_id,), limit=40)
            ),
            "prior_predictions": without_current_episode(
                _table_rows(con, "predictions", where="person_id=?", params=(person_id,), limit=40)
            ),
        }
        if purpose == "pattern_mirror":
            history.update({
                "prior_mirror_cards": _table_rows(
                    con, "v14_pattern_mirror_cards",
                    where="person_id=? AND (conversation_id IS NULL OR conversation_id<>?)",
                    params=(person_id, conversation_id), limit=30,
                ),
                "prior_long_horizon_threads": _table_rows(
                    con, "v14_long_horizon_threads", where="person_id=?",
                    params=(person_id,), limit=30,
                ),
            })
    current_stage_evidence: dict[str, Any] = {
        "speaker_matches": _table_rows(
            con, "speaker_matches", where="conversation_id=?",
            params=(conversation_id,), limit=80,
        ),
        "voice_observations": _table_rows(
            con, "voice_observations", where="conversation_id=?",
            params=(conversation_id,), limit=80,
        ),
    }
    if purpose == "interpersonal":
        current_stage_evidence["utterance_analyses"] = _table_rows(
            con, "utterance_analyses", where="conversation_id=?",
            params=(conversation_id,), limit=180,
        )
    prompt_facts, capability_manifest = _prompt_facts(fact_bundle, turn_ref_by_id)
    parent_outline = next(
        (fact["value"] for fact in prompt_facts if fact["type"] == "conversation_episode"),
        None,
    )
    subtheme_outline = [
        fact["value"] for fact in prompt_facts if fact["type"] == "conversation_subtheme"
    ]
    prompt_facts = [
        fact for fact in prompt_facts
        if fact["type"] not in {"conversation_episode", "conversation_subtheme"}
    ]
    selected_types = _PURPOSE_FACT_TYPES.get(purpose)
    if selected_types is not None:
        prompt_facts = [
            fact for fact in prompt_facts if fact.get("type") in selected_types
        ]
    selected_engines = _PURPOSE_CAPABILITY_ENGINES.get(purpose)
    if selected_engines is not None:
        capability_manifest = [
            capability for capability in capability_manifest
            if capability.get("engine") in selected_engines
        ]
    history = _prompt_payload_value(history, turn_ref_by_id)
    current_stage_evidence = _prompt_payload_value(
        current_stage_evidence, turn_ref_by_id
    )
    result = {
        "projection_version": SHARED_FACT_VERSION,
        "purpose": purpose,
        "conversation": conversation,
        "turns": turns,
        "current_people_refs": current_people,
        "speaker_resolutions": list(speaker_resolutions.values()),
        "current_stage_evidence": current_stage_evidence,
        "context_addenda": context_addenda,
        "conversation_outline": _compact_conversation_outline(
            parent_outline, subtheme_outline
        ),
        "facts": prompt_facts,
        "capabilities": capability_manifest,
        "history": history,
        "lossless_turn_manifest": {
            "source_count": len(turns),
            "included_count": len(turns),
            "omitted_turn_ids": [],
        },
        "_turn_id_map": turn_id_by_ref,
    }
    if sensor_turns:
        result["raw_sensor_manifest"] = {
            "count": len(sensor_turns),
            "digest": _digest(sensor_turns),
            "represented_by": (
                "context_addenda.entries"
                if has_deep_context and purpose in _PURPOSES_USING_SENSOR_SEMANTICS
                else (
                    "visual_consolidation+worldbrain+silent_life"
                    if has_deep_context else
                    "turns[evidence_role=system_observation_not_user_speech]"
                )
            ),
            "durable_source": "turns",
        }
    return result


def expand_turn_refs(value: Any, turn_id_by_ref: Mapping[str, str]) -> Any:
    """Restore durable turn ids in a model result produced from short refs."""

    if isinstance(value, list):
        return [expand_turn_refs(item, turn_id_by_ref) for item in value]
    if isinstance(value, Mapping):
        return {
            key: expand_turn_refs(item, turn_id_by_ref)
            for key, item in value.items()
        }
    if isinstance(value, str) and value in turn_id_by_ref:
        return turn_id_by_ref[value]
    return value


def can_reuse_empty_v14_open_loops(con: Any, conversation_id: str) -> tuple[bool, str]:
    """Return true only for a complete parent analysis with a valid empty verdict."""

    ensure_shared_fact_schema(con)
    episodes = [
        dict(row) for row in con.execute(
            "SELECT episode_id,metadata_json FROM episodes WHERE source_conversation_id=?",
            (conversation_id,),
        )
    ]
    parent_ids = []
    for episode in episodes:
        metadata = json_loads(episode.get("metadata_json"), {})
        source = str(metadata.get("episode_source") or "")
        if metadata.get("coverage_status") == "complete" and (
            "e64i" in source or "e64-i" in source
        ):
            parent_ids.append(str(episode["episode_id"]))
    if len(parent_ids) != 1:
        return False, "requires_one_e64i_complete_parent"
    rows = [
        dict(row) for row in con.execute(
            """SELECT field_name,evaluation_status,applies
               FROM brain2_shared_capabilities_v19
               WHERE conversation_id=? AND episode_id=? AND engine_name='outcome_tracker'
                 AND field_name IN ('intention_outcome_links','open_loops')""",
            (conversation_id, parent_ids[0]),
        )
    ]
    by_field = {str(row["field_name"]): row for row in rows}
    if set(by_field) != {"intention_outcome_links", "open_loops"}:
        return False, "outcome_capabilities_incomplete"
    if any(not int(row["applies"]) for row in rows):
        return False, "outcome_tracker_not_applicable"
    if any(row["evaluation_status"] != "empty_valid" for row in rows):
        return False, "outcome_tracker_has_candidates_or_invalid"
    run = con.execute(
        """SELECT status FROM brain2_shared_fact_runs_v19
           WHERE conversation_id=? AND episode_id=?""",
        (conversation_id, parent_ids[0]),
    ).fetchone()
    if not run or run["status"] != "complete":
        return False, "shared_fact_run_incomplete"
    return True, "v13_outcome_tracker_complete_empty"


def empty_v14_open_loop_output(reason: str) -> dict[str, Any]:
    return {
        "new_or_updated_open_loops": [],
        "loop_updates": [],
        "active_questions": [],
        "solution_candidates": [],
        "next_best_actions": [],
        "missing_context": [],
        "confidence": 0.0,
        "shared_fact_reuse": {
            "version": SHARED_FACT_VERSION,
            "reason": reason,
            "source_engine": "outcome_tracker",
        },
    }
