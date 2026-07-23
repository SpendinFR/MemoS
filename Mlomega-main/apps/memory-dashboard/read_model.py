from __future__ import annotations

"""Pure read-model adapters for the Streamlit dashboard.

No database access lives here.  These functions turn heterogeneous V18/V19 rows
into human semantics without guessing from a table name.
"""

import json
import math
from typing import Any, Mapping


TECHNICAL_TABLES = {
    "artifact_lineage_v176",
    "brain2_life_model_checkpoints",
    "brain2_life_model_consumed_sources",
    "brain2_shared_fact_runs_v19",
    "brain2_shared_engine_sections_v19",
    "brain2_shared_capabilities_v19",
    "cloud_cost_ledger_v19",
    "night_llm_call_telemetry_v19",
    "night_llm_windows_v19",
    "night_llm_coverage_v19",
    "v18_output_manifests",
    "v18_close_day_capability_manifests",
    "v18_context_manifests",
    "v18_external_sync_manifest",
    "v18_pipeline_output_manifests",
    "v18_predictive_case_vector_manifest",
    "v18_sync_manifest",
    "vector_sync_manifest",
    "vector_sync_manifest_v18",
    "owner_quality_shadow_runs_v19",
    "owner_quality_shadow_decisions_v19",
}

CERTAINTY_TABLES = {
    # Facts/observations: explicit contracts only.
    "memory_cards": "fact",
    "memory_facets": "fact",
    "self_model_facts": "fact",
    "life_events": "fact",
    "action_outcomes": "fact",
    "choice_episodes": "fact",
    "brain2_shared_facts_v19": "fact",
    "visual_events_v19": "fact",
    # Hypotheses/patterns: never promoted merely because status is non-empty.
    "brainlive_life_hypotheses": "hypothesis",
    "brain2_life_model_watch_candidates": "hypothesis",
    "candidate_patterns": "hypothesis",
    "thought_hypotheses": "hypothesis",
    "causal_hypotheses": "hypothesis",
    "v14_blindspot_hypotheses": "hypothesis",
    "life_model_entries_v19": "hypothesis",
    "self_schema_v19": "hypothesis",
    # Forward-looking contracts.
    "predictions_v19": "prediction",
    "predictions": "prediction",
    "prediction_cases": "prediction",
    "future_scenarios": "prediction",
    "v14_trajectory_forecasts": "prediction",
    "simulation_branches": "prediction",
}

_SEMANTIC_KEYS = (
    "statement", "situation_summary", "canonical_summary", "summary",
    "scene_summary_detailed", "relationship_state_summary", "overall_reading",
    "content", "description", "prediction", "hypothesis", "reason", "rationale",
    "observed_activity", "location_hint", "topic", "title", "expression",
)


def parse_json(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def certainty_bucket(table: str, row: Mapping[str, Any]) -> str | None:
    """Return a semantic bucket or None; unknown/technical tables never become facts."""

    if table in TECHNICAL_TABLES:
        return None
    bucket = CERTAINTY_TABLES.get(table)
    if bucket != "fact":
        return bucket
    status = " ".join(
        str(row.get(key) or "").casefold()
        for key in ("status", "truth_status", "epistemic_status", "evidence_status")
    )
    if any(token in status for token in ("hypoth", "inferred", "candidate", "watch")):
        return "hypothesis"
    if any(token in status for token in ("quarant", "invalid", "contradict", "obsolete")):
        return None
    return "fact"


def semantic_text(row: Mapping[str, Any], *, fallback: str = "") -> str:
    for key in _SEMANTIC_KEYS:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    for key in (
        "payload_json", "observation_json", "entity_json", "evidence_json",
        "verification_spec_json", "qwen_json",
    ):
        parsed = parse_json(row.get(key))
        if isinstance(parsed, dict):
            nested = semantic_text(parsed)
            if nested:
                return nested
    return fallback


def human_title(table: str, row: Mapping[str, Any]) -> str:
    if table == "brain2_life_model_watch_candidates":
        identity = str(row.get("identity_key") or "élément non nommé")
        kind = str(row.get("candidate_kind") or "watch")
        return f"{kind} · {identity}"
    if table == "brain2_shared_facts_v19":
        return str(row.get("fact_type") or row.get("source_field") or "fait")
    if table == "visual_events_v19":
        entity = parse_json(row.get("entity_json"), {})
        return str(entity.get("label") or row.get("event_type") or "événement visuel")
    semantic = semantic_text(row)
    if semantic:
        return semantic
    return str(row.get("title") or row.get("name") or "Élément sans libellé")


def life_watch_view(row: Mapping[str, Any]) -> dict[str, Any]:
    evidence = parse_json(row.get("evidence_json"), [])
    evidence = evidence if isinstance(evidence, list) else []
    return {
        "title": human_title("brain2_life_model_watch_candidates", row),
        "status": str(row.get("status") or "watching"),
        "occurrences": int(row.get("occurrence_count") or 0),
        "independent_sources": int(row.get("independent_count") or 0),
        "first_seen_at": row.get("first_seen_at"),
        "last_seen_at": row.get("last_seen_at"),
        "promoted_to": row.get("promoted_target_id"),
        "sources": evidence,
        "watch_id": row.get("watch_id"),
    }


def bbox_audit(
    observation: Any,
    *,
    frame_width: float | None = None,
    frame_height: float | None = None,
) -> dict[str, Any]:
    parsed = parse_json(observation, {})
    bbox = parsed.get("bbox") if isinstance(parsed, dict) else None
    if not isinstance(bbox, list) or len(bbox) != 4:
        return {"present": False, "valid": None, "label": "no_bbox"}
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return {"present": True, "valid": False, "label": "bbox_invalid_legacy", "bbox": bbox}
    finite = all(math.isfinite(value) for value in (x1, y1, x2, y2))
    ordered = x2 > x1 and y2 > y1
    non_negative = min(x1, y1, x2, y2) >= 0
    in_frame = True
    if frame_width and frame_width > 0:
        in_frame = in_frame and x2 <= frame_width
    if frame_height and frame_height > 0:
        in_frame = in_frame and y2 <= frame_height
    valid = finite and ordered and non_negative and in_frame
    return {
        "present": True,
        "valid": valid,
        "label": "bbox_valid" if valid else "bbox_invalid_legacy",
        "bbox": [x1, y1, x2, y2],
        "finite": finite,
        "ordered": ordered,
        "non_negative": non_negative,
        "in_frame": in_frame,
    }


def deep_vision_view(row: Mapping[str, Any]) -> dict[str, Any]:
    objects = parse_json(row.get("objects_json"), [])
    people = parse_json(row.get("people_presence_json"), {})
    text = parse_json(row.get("visible_text_json"), [])
    uncertainty = parse_json(row.get("uncertainty_json"), [])
    return {
        "title": str(row.get("scene_summary_detailed") or "Observation visuelle"),
        "activity": row.get("observed_activity"),
        "activity_confidence": row.get("activity_confidence"),
        "location": row.get("location_hint"),
        "objects": objects if isinstance(objects, list) else [],
        "people": people if isinstance(people, dict) else {},
        "visible_text": text if isinstance(text, list) else [],
        "uncertainty": uncertainty if isinstance(uncertainty, list) else [],
        "frame_time": row.get("frame_time"),
        "sample_reason": row.get("sample_reason"),
        "frame_id": row.get("frame_id"),
        "image_path": row.get("image_path"),
        "status": row.get("status"),
        "model": row.get("model"),
    }
