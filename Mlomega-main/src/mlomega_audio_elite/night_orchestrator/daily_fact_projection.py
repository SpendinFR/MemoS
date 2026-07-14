from __future__ import annotations

"""E64-I2 daily fact projections and deterministic coordination compilers.

Raw rows stay durable in their source tables.  These helpers remove duplicated
transport/storage representations, keep semantic fields and provenance, and compile
mechanical coordination products without asking an LLM to copy existing JSON.
"""

from datetime import datetime
import re
from typing import Any, Iterable, Mapping, Sequence

from ..utils import json_dumps, json_loads
from .evidence_ref import content_digest
from .vision_atoms import reduce_vision_timeline


PROJECTION_VERSION = "e64-i2-daily-facts-v1"

_DUPLICATE_OR_BINARY_FIELDS = {
    "raw_json", "raw_timeline_json", "raw_evidence_json", "qwen_output_json",
    "embedding", "embedding_json", "voice_embedding", "voice_embedding_json",
    "source_path", "chunk_path", "raw_audio_path", "audio_path", "video_path",
}


def _decode_json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json_loads(value, default)
    return value if value is not None else default


def _semantic_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return semantic_row(value)
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    if isinstance(value, str) and key.endswith("_json"):
        decoded = json_loads(value, value)
        return _semantic_value(decoded, key=key[:-5])
    return value


def semantic_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        name = str(key)
        if name in _DUPLICATE_OR_BINARY_FIELDS:
            continue
        target = name[:-5] if name.endswith("_json") else name
        out[target] = _semantic_value(value, key=name)
    return out


def _manifest(rows: Sequence[Any]) -> dict[str, Any]:
    return {
        "source_count": len(rows),
        "included_count": len(rows),
        "digest": content_digest(rows),
        "omitted_source_ids": [],
    }


def _row_id(row: Mapping[str, Any]) -> str | None:
    for key in (
        "prediction_id", "case_id", "scenario_id", "warning_id", "forecast_id",
        "watch_id", "hook_id", "routine_id", "need_model_id", "trajectory_model_id",
        "affordance_pref_id", "outcome_id", "evaluation_id", "intervention_id",
        "event_id", "live_turn_id", "observation_id", "bundle_id", "export_id",
    ):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _project_vision(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for row in rows:
        timeline.append({
            "source_id": row.get("observation_id"),
            "source_table": "vision_scene_observations",
            "frame_id": row.get("frame_id"),
            "time": row.get("created_at"),
            "summary": row.get("scene_summary"),
            "location_hint": row.get("location_hint"),
            "people_count": row.get("people_count"),
            "spatial_context": row.get("spatial_context"),
            "social_context_hint": row.get("social_context_hint"),
            "visible_text": _decode_json(row.get("visible_text_json"), []),
            "objects": _decode_json(row.get("objects_json"), []),
            "risks": _decode_json(row.get("risks_json"), []),
            "affordances": _decode_json(row.get("affordances_json"), []),
            "possible_user_activities": _decode_json(
                row.get("possible_user_activities_json"), []
            ),
            "personal_relevance": _decode_json(
                row.get("personal_relevance_json"), {}
            ),
            "confidence": row.get("confidence"),
        })
    return [atom.to_dict() for atom in reduce_vision_timeline(timeline)]


def _project_bundle(row: Mapping[str, Any], *, turns_present: bool) -> dict[str, Any]:
    projected = {
        key: row.get(key)
        for key in (
            "bundle_id", "person_id", "package_date", "live_session_id",
            "start_time", "end_time", "bundle_kind", "title",
            "brain2_conversation_id", "status",
        )
    }
    projected["participants"] = _decode_json(row.get("participants_json"), [])
    projected["place"] = _decode_json(row.get("place_json"), {})
    transcript = _decode_json(row.get("transcript_json"), [])
    projected["transcript_manifest"] = _manifest(transcript)
    if not turns_present:
        projected["transcript"] = transcript
    vision = _decode_json(row.get("vision_timeline_json"), [])
    projected["vision_atoms"] = [
        atom.to_dict() for atom in reduce_vision_timeline(vision)
    ]
    for name in (
        "diarization", "audio_timeline", "world_state_timeline",
        "prediction_timeline", "intervention_timeline", "outcome_timeline",
        "affordance_timeline", "source_counts",
    ):
        projected[name] = _decode_json(row.get(f"{name}_json"), [] if name != "source_counts" else {})
    return projected


def load_daily_shared_registry(
    con: Any, *, person_id: str, package_date: str
) -> dict[str, Any]:
    table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='brain2_shared_fact_runs_v19'"
    ).fetchone()
    if not table:
        return {"facts": [], "capabilities": [], "source_manifest": _manifest([])}
    conversation_ids = [
        str(row[0])
        for row in con.execute(
            "SELECT conversation_id FROM conversations WHERE substr(started_at,1,10)=?",
            (package_date,),
        )
    ]
    if not conversation_ids:
        return {"facts": [], "capabilities": [], "source_manifest": _manifest([])}
    placeholders = ",".join("?" for _ in conversation_ids)
    params = (person_id, *conversation_ids)
    facts = [
        semantic_row(dict(row))
        for row in con.execute(
            f"""SELECT fact_id,conversation_id,episode_id,source_engine,source_field,
                       fact_type,subject_ref,epistemic_status,evidence_status,
                       confidence,confidence_ceiling,payload_json
                FROM brain2_shared_facts_v19
                WHERE person_id=? AND conversation_id IN ({placeholders})
                ORDER BY source_engine,source_field,fact_id""",
            params,
        )
    ]
    for fact in facts:
        fact["evidence_turn_ids"] = [
            str(row[0])
            for row in con.execute(
                "SELECT turn_id FROM brain2_shared_fact_evidence_v19 WHERE fact_id=? ORDER BY turn_id",
                (fact.get("fact_id"),),
            )
        ]
    capabilities = [
        semantic_row(dict(row))
        for row in con.execute(
            f"""SELECT capability_id,conversation_id,episode_id,engine_name,field_name,
                       fact_type,applies,evaluation_status,applicability_reason,confidence
                FROM brain2_shared_capabilities_v19
                WHERE person_id=? AND conversation_id IN ({placeholders})
                ORDER BY engine_name,field_name""",
            params,
        )
    ]
    return {
        "facts": facts,
        "capabilities": capabilities,
        "source_manifest": _manifest([f.get("fact_id") for f in facts]),
    }


def project_day_evidence(
    raw: Mapping[str, Any], *, shared_registry: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    turns = list(raw.get("turns") or [])
    sections: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    for name, value in raw.items():
        if not isinstance(value, list):
            continue
        rows = [dict(item) for item in value if isinstance(item, Mapping)]
        manifests[name] = _manifest(rows)
        if name == "vision_observations":
            sections["vision_change_atoms"] = _project_vision(rows)
        elif name == "event_bundles":
            sections[name] = [
                _project_bundle(row, turns_present=bool(turns)) for row in rows
            ]
        elif name == "sensor_events":
            projected_rows = []
            for row in rows:
                item = semantic_row(row)
                payload = item.get("payload")
                if isinstance(payload, dict) and turns:
                    payload = dict(payload)
                    payload.pop("transcript_text", None)
                    item["payload"] = payload
                projected_rows.append(item)
            sections[name] = projected_rows
        else:
            sections[name] = [semantic_row(row) for row in rows]
    return {
        "projection_version": PROJECTION_VERSION,
        "package_date": raw.get("package_date"),
        "period_start": raw.get("period_start"),
        "period_end": raw.get("period_end"),
        "sections": sections,
        "shared_registry": dict(shared_registry or {}),
        "source_manifests": manifests,
    }


def compile_day_package(
    raw: Mapping[str, Any], projected: Mapping[str, Any]
) -> dict[str, Any]:
    sections = projected.get("sections") or {}
    turns = sections.get("turns") or []
    facts = ((projected.get("shared_registry") or {}).get("facts") or [])
    moments = [
        {
            "source_table": "brainlive_turn_buffer",
            "source_id": row.get("live_turn_id"),
            "timestamp": row.get("timestamp_start") or row.get("created_at"),
            "speaker_label": row.get("speaker_label"),
            "content": row.get("text_final") or row.get("text_partial"),
            "asr_confidence": row.get("asr_confidence"),
            "epistemic_status": (
                "uncertain_asr" if float(row.get("asr_confidence") or 0.0) < 0.3
                else "observed"
            ),
        }
        for row in turns
        if row.get("text_final") or row.get("text_partial")
    ]
    prediction_lessons = [
        {"source_table": name, "source": row}
        for name in ("prediction_outcomes", "outcome_evaluations")
        for row in (sections.get(name) or [])
    ]
    intervention_lessons = [
        {"source_table": name, "source": row}
        for name in ("intervention_candidates", "hot_interventions")
        for row in (sections.get(name) or [])
    ]
    model_candidates = [
        {
            "fact_id": fact.get("fact_id"),
            "fact_type": fact.get("fact_type"),
            "epistemic_status": fact.get("epistemic_status"),
            "confidence": fact.get("confidence"),
            "confidence_ceiling": fact.get("confidence_ceiling"),
            "payload": fact.get("payload"),
            "evidence_turn_ids": fact.get("evidence_turn_ids") or [],
        }
        for fact in facts
    ]
    counts = {
        name: manifest.get("source_count", 0)
        for name, manifest in (projected.get("source_manifests") or {}).items()
    }
    return {
        "day_summary": (
            f"{counts.get('live_sessions', 0)} session(s), "
            f"{counts.get('turns', 0)} turn(s), "
            f"{counts.get('sensor_events', 0)} sensor event(s), "
            f"{counts.get('vision_observations', 0)} vision observation(s); "
            "semantic facts and raw provenance are attached."
        ),
        "important_live_moments": moments,
        "prediction_lessons": prediction_lessons,
        "intervention_lessons": intervention_lessons,
        "silence_lessons": [
            {"source_table": "brainlive_missed_opportunity_cards", "source": row}
            for row in (sections.get("missed_opportunities") or [])
        ],
        "model_update_candidates": model_candidates,
        "questions_for_brain2": [],
    }


def _json_field(row: Mapping[str, Any], *names: str, default: Any) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return _decode_json(row.get(name), default)
        json_name = f"{name}_json"
        if json_name in row and row.get(json_name) not in (None, ""):
            return _decode_json(row.get(json_name), default)
    return default


def _normalize_horizon(value: Any) -> str:
    raw = str(value or "H1").strip().lower()
    return {
        "now": "H0", "immediate": "H0", "next": "H0", "h0": "H0",
        "short": "H1", "short_term": "H1", "h1": "H1",
        "medium": "H2", "medium_term": "H2", "h2": "H2",
        "day": "day", "week": "week", "long": "long", "long_term": "long",
    }.get(raw, "H1")


def compile_watch_bindings(
    evidence: Mapping[str, Any], *, section_table_map: Mapping[str, str]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    explicitly_watchable = {
        "predictions_short_and_next", "future_scenarios", "trajectory_warnings",
        "v14_trajectory_forecasts", "v14_forecast_watch_queue",
        "brain2_live_prediction_hooks",
    }
    for section, raw_rows in evidence.items():
        # Prediction cases are historical training examples, while generic Life
        # rows are context.  Turning either into a live hook would invent a new
        # activation policy and flood BrainLive.  Only already-actionable source
        # contracts are compiled here.
        if str(section) not in explicitly_watchable:
            continue
        source_table = str(section_table_map.get(section, section))
        for raw in raw_rows if isinstance(raw_rows, list) else []:
            if not isinstance(raw, Mapping):
                continue
            row = semantic_row(raw)
            if str(row.get("use_policy") or "").lower() in {
                "do_not_use", "forbidden", "never_use"
            }:
                continue
            source_id = _row_id(raw)
            if not source_id:
                continue
            target = (
                row.get("hook_name") or row.get("prediction_target")
                or row.get("trajectory_name") or row.get("routine_name")
                or row.get("need_or_expectation") or row.get("affordance_type")
                or row.get("title") or source_id
            )
            items.append({
                "source_table": source_table,
                "source_id": source_id,
                "hook_name": str(target),
                "horizon": _normalize_horizon(row.get("horizon")),
                "domain": row.get("domain") or row.get("life_domain") or "unknown",
                "active_person_hint": row.get("active_person_hint") or row.get("person_hint"),
                "risk_type": row.get("risk_type") or "unknown",
                "user_common_bad_move": row.get("user_common_bad_move") or "",
                "recommended_micro_move": row.get("recommended_micro_move") or "",
                "do_not_say": _json_field(raw, "do_not_say", default=[]),
                "intervention_mode": row.get("intervention_mode") or "watch",
                "use_policy": row.get("use_policy") or "watch_only",
                "activation_conditions": _json_field(
                    raw, "activation_conditions", default=[]
                ) or ([{"current_context": row.get("current_context")}] if row.get("current_context") else []),
                "predicts": _json_field(raw, "predicts", default={}) or {
                    "target": row.get("prediction_target"),
                    "value": row.get("predicted_value"),
                    "probability": row.get("probability"),
                },
                "watch_signals": _json_field(raw, "watch_signals", "metadata", default=[]),
                "proactive_options": _json_field(
                    raw, "proactive_options", "intervention_options", default=[]
                ),
                "silence_policy": _json_field(raw, "silence_policy", default={}),
                "evidence": _json_field(
                    raw, "evidence", "evidence_cases", default=[]
                ),
                "counter_evidence": _json_field(raw, "counter_evidence", default=[]),
                "confidence": row.get("confidence") or row.get("probability") or 0.0,
            })
    return items


def project_forecast_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    for name, value in evidence.items():
        rows = [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []
        sections[str(name)] = [semantic_row(row) for row in rows]
        manifests[str(name)] = _manifest(rows)
    return {
        "projection_version": PROJECTION_VERSION,
        "sections": sections,
        "source_manifests": manifests,
    }


def project_reconciliation_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    projected = {
        "mission": payload.get("mission"),
        "candidate_pairs": [
            semantic_row(item) for item in (payload.get("candidate_pairs") or [])
            if isinstance(item, Mapping)
        ],
        "recent_reconciliations": [
            semantic_row(item) for item in (payload.get("recent_reconciliations") or [])
            if isinstance(item, Mapping)
        ],
        "projection_version": PROJECTION_VERSION,
    }
    projected["source_manifest"] = {
        "candidate_pairs": _manifest(projected["candidate_pairs"]),
        "recent_reconciliations": _manifest(projected["recent_reconciliations"]),
    }
    return projected


def build_reconciliation_candidates(
    live_package: Mapping[str, Any], brain2_evidence: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    brain2_by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for section, rows in brain2_evidence.items():
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and _row_id(row):
                brain2_by_id[str(_row_id(row))] = (str(section), row)
    live_rows: list[tuple[str, Mapping[str, Any]]] = []
    for column, table in (
        ("outcomes_json", "brainlive_prediction_outcomes"),
        ("interventions_json", "brainlive_intervention_candidates"),
    ):
        for row in _decode_json(live_package.get(column), []):
            if not isinstance(row, Mapping):
                continue
            # A forecast merely being active/pending is not an observed outcome.
            # Intervention candidates are comparable only once their own result
            # has been recorded explicitly.
            if column == "interventions_json" and not (
                row.get("outcome_status") or row.get("result")
            ):
                continue
            if isinstance(row, Mapping):
                live_rows.append((table, row))
    exact: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for live_table, live in live_rows:
        linked = None
        for key in (
            "brain2_source_id", "prediction_id", "source_prediction_id",
            "forecast_id", "hook_id", "source_id",
        ):
            candidate = live.get(key)
            if candidate and str(candidate) in brain2_by_id:
                linked = str(candidate)
                break
        if not linked:
            # Forecasts/interventions without an explicit outcome are not evidence
            # of confirmation or contradiction.  They are intentionally ignored.
            continue
        section, brain2 = brain2_by_id[linked]
        status = str(
            live.get("outcome_status") or live.get("result")
            or live.get("status") or ""
        ).lower()
        if status in {"success", "succeeded", "confirmed", "completed", "true"}:
            verdict = "confirmed"
        elif status in {"failure", "failed", "contradicted", "false", "wrong"}:
            verdict = "contradicted"
        elif status in {"pending", "open", "active", "too_early"}:
            verdict = "too_early"
        else:
            ambiguous.append({
                "live_source_table": live_table,
                "live_source": semantic_row(live),
                "brain2_source_table": section,
                "brain2_source": semantic_row(brain2),
            })
            continue
        exact.append({
            "live_source_table": live_table,
            "live_source_id": _row_id(live) or str(live.get("source_id") or linked),
            "brain2_source_table": section,
            "brain2_source_id": linked,
            "verdict": verdict,
            "verdict_confidence": live.get("confidence") or 0.8,
            "what_brainlive_thought": semantic_row(brain2),
            "what_happened": semantic_row(live),
            "what_brain2_knows": semantic_row(brain2),
            "learning_delta": {"compiled_from_explicit_outcome": True},
        })
    return exact, ambiguous


def _prompt_provenance(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(name): _prompt_provenance(child, key=str(name))
            for name, child in semantic_row(value).items()
        }
    if isinstance(value, list):
        projected = [_prompt_provenance(item, key=key) for item in value]
        if key in {
            "evidence", "counter_evidence", "evidence_ids", "source_ids",
            "evidence_case_ids", "turn_ids",
        } and len(projected) > 5:
            return {
                "count": len(projected),
                "digest": content_digest(projected),
                "sample": projected[:5],
            }
        return projected
    return value


_LIFE_ROW_NOISE = {
    "person_id", "created_at", "updated_at", "export_id",
}
_LIFE_EVIDENCE_FIELDS = {
    "evidence", "counter_evidence", "evidence_ids", "source_ids",
    "evidence_case_ids", "turn_ids", "outcomes",
}
_LIFE_IDENTITY_FIELDS = {
    "routine_name", "place_key", "action_or_choice", "need_or_expectation",
    "expression_or_style", "trajectory_name", "context_key", "hook_name",
    "affordance_type",
}
_LIFE_STOP_WORDS = {
    "avec", "dans", "pour", "sans", "cette", "comme", "mais", "plus",
    "moins", "tout", "tous", "toute", "that", "this", "with", "from",
    "have", "will", "model", "active", "unknown", "candidate", "person",
    "confidence", "status", "observed", "source", "brainlive", "brain2",
}


def _life_terms(value: Any) -> set[str]:
    text = json_dumps(value).lower()
    return {
        term for term in re.findall(r"[\w\-']+", text, flags=re.UNICODE)
        if len(term) >= 4 and term not in _LIFE_STOP_WORDS
        and not term.isdigit()
    }


def _compact_life_evidence(value: Any) -> Any:
    projected = _prompt_provenance(value)
    if isinstance(projected, list):
        return {
            "count": len(projected),
            "digest": content_digest(projected),
            "sample": projected[:2],
        }
    return projected


def _compact_life_row(row: Mapping[str, Any], *, index_only: bool) -> dict[str, Any]:
    semantic = semantic_row(row)
    out: dict[str, Any] = {}
    for key, value in semantic.items():
        if key in _LIFE_ROW_NOISE:
            continue
        if key in _LIFE_EVIDENCE_FIELDS:
            if not index_only:
                out[key] = _compact_life_evidence(value)
            continue
        if index_only:
            if (
                key.endswith("_id") or key in _LIFE_IDENTITY_FIELDS
                or key in {
                    "status", "confidence", "horizon", "domain", "use_policy",
                    "routine_type", "kind", "risk_type", "truth_status",
                }
            ):
                out[key] = value
            continue
        out[key] = _prompt_provenance(value, key=key)
    return out


def _project_current_life_model(
    current: Mapping[str, Any], *, delta_hint: Mapping[str, Any]
) -> dict[str, Any]:
    """Expose the whole model as an index and full detail only when relevant.

    The updater is a patcher, not a nightly re-summarizer.  It must know every
    existing identity to avoid duplicate creates, but unrelated historical
    evidence does not belong in today's prompt.  Raw canonical rows remain in
    SQLite; digests and selected ids make the projection auditable.
    """

    delta_terms = _life_terms(delta_hint)
    delta_text = json_dumps(delta_hint).lower()
    layer_indexes: dict[str, list[dict[str, Any]]] = {}
    candidate_details: dict[str, list[dict[str, Any]]] = {}
    selection: dict[str, Any] = {}
    ranked_global: list[tuple[int, str, str, Mapping[str, Any]]] = []
    for layer, rows in (current.get("canonical_layers") or {}).items():
        layer_name = str(layer)
        valid_rows = [row for row in rows if isinstance(row, Mapping)]
        indexes = [_compact_life_row(row, index_only=True) for row in valid_rows]
        layer_indexes[layer_name] = indexes
        candidate_details[layer_name] = []
        for row, index in zip(valid_rows, indexes):
            identity = {
                key: value for key, value in index.items()
                if key.endswith("_id") or key in _LIFE_IDENTITY_FIELDS
            }
            row_terms = _life_terms(identity)
            score = len(row_terms & delta_terms)
            direct_ids = [
                str(value) for key, value in index.items()
                if key.endswith("_id") and value
            ]
            if any(identity.lower() in delta_text for identity in direct_ids):
                score += 1000
            if score:
                ranked_global.append(
                    (score, content_digest(index), layer_name, row)
                )
        selection[layer_name] = {
            "total_rows": len(valid_rows),
            "selected_rows": 0,
            "selected_digests": [],
            "layer_digest": content_digest(valid_rows),
            "selection_rule": "direct_target_id_only_full_detail; semantic index always present",
        }
    ranked_global.sort(key=lambda item: (-item[0], item[1]))
    direct = [item for item in ranked_global if item[0] >= 1000]
    semantic = [item for item in ranked_global if item[0] < 1000]
    selected_global = direct
    for _, digest, layer_name, row in selected_global:
        candidate_details[layer_name].append(
            _compact_life_row(row, index_only=False)
        )
        selection[layer_name]["selected_rows"] += 1
        selection[layer_name]["selected_digests"].append(digest)
    lifecycle = [
        _compact_life_row(row, index_only=True)
        for row in (current.get("lifecycle") or [])
        if isinstance(row, Mapping)
    ]
    return {
        "person_id": current.get("person_id"),
        "canonical_index": layer_indexes,
        "delta_relevant_details": candidate_details,
        "selection_manifest": selection,
        "lifecycle": lifecycle,
        "strata_manifest": {
            str(name): {
                "digest": content_digest(value),
                "layer_counts": {
                    str(layer): len(rows) if isinstance(rows, list) else 0
                    for layer, rows in (value or {}).items()
                } if isinstance(value, Mapping) else {},
            }
            for name, value in (current.get("strata") or {}).items()
        },
        "latest_export": _prompt_provenance(current.get("latest_export") or {}),
    }


def _project_life_bridge(
    bridge: Mapping[str, Any], *, turns_present: bool, owner_person_id: str,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    def rows(*names: str) -> list[Any]:
        combined: list[Any] = []
        for name in names:
            value = bridge.get(name)
            if isinstance(value, list):
                combined.extend(value)
        return combined
    packages = []
    for package in rows("day_packages", "brainlive_day_packages"):
        if not isinstance(package, Mapping):
            continue
        packages.append({
            "package_id": package.get("package_id"),
            "package_date": package.get("package_date"),
            "period_start": package.get("period_start"),
            "period_end": package.get("period_end"),
            "status": package.get("status"),
            "source_counts": _decode_json(package.get("source_counts_json"), {}),
            "raw_sections_manifest": {
                name: len(_decode_json(package.get(f"{name}_json"), []))
                for name in (
                    "turns", "sensor_events", "context_snapshots", "predictions",
                    "interventions", "outcomes", "vision", "event_bundles",
                )
            },
        })
    projected["day_packages"] = packages
    aliases = {
        str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
    }
    projected["reconciliations"] = [
        _prompt_provenance(row)
        for row in rows("reconciliations", "brainlive_brain2_reconciliations")
        if isinstance(row, Mapping)
        and str(row.get("person_id") or owner_person_id).strip().lower() in aliases
        and str(row.get("verdict") or "").lower() in {
            "confirmed", "contradicted", "partially_confirmed",
        }
    ]
    # Context snapshots and event bundles remain durable source material.  Life
    # receives their canonical facts/outcomes, not another copy of the day.
    projected["context_snapshots"] = []
    projected["event_bundles"] = []
    projected["silent_nonverbal_candidates_v160"] = [
        _prompt_provenance(row)
        for row in rows(
            "silent_nonverbal_candidates_v160",
            "brainlive_silent_event_candidates_v160",
        )
        if isinstance(row, Mapping)
        and str(row.get("person_id") or owner_person_id).strip().lower() in aliases
    ]
    projected["source_manifests"] = {
        str(name): _manifest(list(rows) if isinstance(rows, list) else [])
        for name, rows in bridge.items()
    }
    return projected


def _project_life_language(
    language: Mapping[str, Any], *, owner_person_id: str,
    short_ref_by_turn_id: Mapping[str, str],
    relevant_turn_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Keep only speech cited by a durable Life delta.

    Raw turns remain in SQLite and in the source manifest.  Replaying every
    sentence merely because another row triggered a Life update lets the model
    turn unrelated conversation into owner traits.  Language-specific upstream
    models remain represented by their manifests; exact turns are included here
    only when an owner-scoped fact/outcome explicitly cites them.
    """

    out: dict[str, Any] = {}
    turns = []
    owner_aliases = {
        str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
    }
    metadata_values: list[Any] = []
    conversation_ids: list[str] = []
    raw_turns = [
        row for row in (language.get("turns_recent") or [])
        if isinstance(row, Mapping)
    ]
    for row in raw_turns:
        if not isinstance(row, Mapping):
            continue
        turn_id = str(row.get("turn_id") or "")
        conversation_id = str(row.get("conversation_id") or "")
        if conversation_id:
            conversation_ids.append(conversation_id)
        if relevant_turn_ids is not None and turn_id not in relevant_turn_ids:
            continue
        item = {
            key: row.get(key) for key in (
                "idx", "speaker_label", "person_id", "start_s", "end_s", "text",
            )
        }
        item["turn_ref"] = short_ref_by_turn_id.get(turn_id, turn_id)
        item["source_table"] = "turns"
        item["source_id"] = item["turn_ref"]
        previous = str(row.get("previous_turn_id") or "")
        item["previous_turn_ref"] = short_ref_by_turn_id.get(previous, previous) or None
        metadata = _decode_json(row.get("metadata_json"), {})
        if metadata:
            metadata_values.append(metadata)
        item["owner_scope"] = (
            "owner_verified"
            if str(row.get("person_id") or "").strip().lower() in owner_aliases
            else "context_other_or_unresolved"
        )
        turns.append(item)
    out["turns_recent"] = turns
    out["turn_transport_manifest"] = {
        "source_count": len(raw_turns),
        "included_count": len(turns),
        "conversation_count": len(set(conversation_ids)),
        "conversation_digest": content_digest(sorted(set(conversation_ids))),
        "metadata_count": len(metadata_values),
        "metadata_digest": content_digest(metadata_values),
        "omitted_count": len(raw_turns) - len(turns),
        "omitted_digest": content_digest([
            str(row.get("turn_id") or "") for row in raw_turns
            if str(row.get("turn_id") or "") not in (relevant_turn_ids or set())
        ]) if relevant_turn_ids is not None else content_digest([]),
    }
    for name, rows in language.items():
        if name == "turns_recent":
            continue
        if name in {"personal_language_patterns", "phrase_templates"}:
            material = list(rows) if isinstance(rows, list) else []
            out[f"{name}_manifest"] = {
                **_manifest(material),
                "prompt_inclusion": "excluded_until_owner_evidence_is_explicit",
            }
            continue
        if isinstance(rows, list):
            out[str(name)] = [
                {
                    key: _prompt_provenance(value, key=key)
                    for key, value in semantic_row(row).items()
                    if key not in _LIFE_ROW_NOISE and key != "metadata"
                }
                for row in rows if isinstance(row, Mapping)
            ]
        else:
            out[str(name)] = _prompt_provenance(rows, key=str(name))
    return out


def _project_life_registry(
    registry: Mapping[str, Any], *, owner_person_id: str,
    short_ref_by_turn_id: Mapping[str, str],
) -> dict[str, Any]:
    """Keep canonical facts once and replace schema-capability rows by a census."""

    facts: list[dict[str, Any]] = []
    owner_aliases = {
        str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
    }
    raw_facts = [raw for raw in (registry.get("facts") or []) if isinstance(raw, Mapping)]
    owner_facts = [
        raw for raw in raw_facts
        if str(raw.get("subject_ref") or "").strip().lower() in owner_aliases
    ]
    owner_episode_ids = {str(raw.get("episode_id")) for raw in owner_facts if raw.get("episode_id")}
    owner_conversation_ids = {
        str(raw.get("conversation_id")) for raw in owner_facts if raw.get("conversation_id")
    }
    for raw in raw_facts:
        if not isinstance(raw, Mapping):
            continue
        owner_scoped = str(raw.get("subject_ref") or "").strip().lower() in owner_aliases
        causal_context = bool(
            (raw.get("episode_id") and str(raw.get("episode_id")) in owner_episode_ids)
            or (
                raw.get("conversation_id")
                and str(raw.get("conversation_id")) in owner_conversation_ids
            )
        )
        if not owner_scoped and not causal_context:
            continue
        payload = dict(raw.get("payload") or {}) if isinstance(raw.get("payload"), Mapping) else raw.get("payload")
        if isinstance(payload, dict):
            evidence_ids = list(payload.get("evidence_turn_ids") or [])
            payload.pop("evidence_manifest", None)
            payload.pop("evidence_turn_ids", None)
            payload.pop("turn_ids", None)
            payload.pop("created_at", None)
            payload.pop("updated_at", None)
        else:
            evidence_ids = []
        if not evidence_ids:
            evidence_ids = list(raw.get("evidence_turn_ids") or [])
        evidence_refs = [
            short_ref_by_turn_id.get(str(turn_id), str(turn_id))
            for turn_id in evidence_ids
        ]
        facts.append({
            key: raw.get(key) for key in (
                "fact_id", "conversation_id", "episode_id", "source_engine",
                "source_field", "fact_type", "subject_ref", "epistemic_status",
                "evidence_status", "confidence", "confidence_ceiling",
            )
        } | {
            "payload": payload,
            "owner_scope": (
                "owner_verified"
                if owner_scoped else "causal_context_other_person"
            ),
            "evidence_turn_ids": evidence_refs,
            "evidence_manifest": {
                "count": len(evidence_ids), "digest": content_digest(evidence_ids),
            },
        })
    capability_counts: dict[str, int] = {}
    capabilities = [
        row for row in (registry.get("capabilities") or [])
        if isinstance(row, Mapping)
    ]
    for row in capabilities:
        key = ":".join((
            str(row.get("engine_name") or "unknown"),
            str(row.get("evaluation_status") or "unknown"),
        ))
        capability_counts[key] = capability_counts.get(key, 0) + 1
    return {
        "facts": facts,
        "fact_manifest": {
            **_manifest(facts),
            "source_count": len(raw_facts),
            "omitted_count": len(raw_facts) - len(facts),
            "omitted_digest": content_digest([
                raw.get("fact_id") for raw in raw_facts
                if raw.get("fact_id") not in {fact.get("fact_id") for fact in facts}
            ]),
        },
        "capability_census": capability_counts,
        "capability_manifest": _manifest(capabilities),
        "source_manifest": registry.get("source_manifest") or _manifest(facts),
    }


def _owner_relevance_hint(projected_delta: Mapping[str, Any]) -> dict[str, Any]:
    language = projected_delta.get("language") if isinstance(projected_delta.get("language"), Mapping) else {}
    registry = projected_delta.get("shared_registry") if isinstance(projected_delta.get("shared_registry"), Mapping) else {}
    bridge = projected_delta.get("brainlive_bridge_delta") if isinstance(projected_delta.get("brainlive_bridge_delta"), Mapping) else {}
    observed = projected_delta.get("observed_life") if isinstance(projected_delta.get("observed_life"), Mapping) else {}
    return {
        "owner_turns": [
            row for row in (language.get("turns_recent") or [])
            if isinstance(row, Mapping) and row.get("owner_scope") == "owner_verified"
        ],
        "owner_internal": projected_delta.get("self_and_internal") or {},
        "owner_observed": [
            row for rows in observed.values()
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, Mapping) and row.get("owner_scope") == "owner_verified"
        ],
        "owner_facts": [
            fact for fact in (registry.get("facts") or [])
            if isinstance(fact, Mapping) and fact.get("owner_scope") == "owner_verified"
        ],
        "owner_nonverbal": (
            bridge.get("silent_nonverbal_candidates_v160")
            or bridge.get("brainlive_silent_event_candidates_v160") or []
        ),
        "observed_outcomes": (
            bridge.get("reconciliations")
            or bridge.get("brainlive_brain2_reconciliations") or []
        ),
    }


def _life_relevant_turn_ids(
    delta: Mapping[str, Any], registry: Mapping[str, Any], *, owner_person_id: str,
) -> set[str]:
    """Return turn ids explicitly cited by owner-scoped durable evidence."""

    aliases = {
        str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
    }
    relevant: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in {"turn_id", "turn_ref"} and child:
                    relevant.add(str(child))
                elif key in {"turn_ids", "evidence_turn_ids"} and isinstance(child, list):
                    relevant.update(str(item) for item in child if item)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    observed = delta.get("observed_life") if isinstance(delta.get("observed_life"), Mapping) else {}
    for rows in observed.values():
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            owner_values = [
                row.get(key) for key in ("subject_person_id", "user_person_id", "person_id")
                if row.get(key)
            ]
            if any(str(value).strip().lower() in aliases for value in owner_values):
                collect(row)

    internal = delta.get("self_and_internal") if isinstance(delta.get("self_and_internal"), Mapping) else {}
    for rows in internal.values():
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping):
                collect(row)

    for fact in registry.get("facts") or []:
        if not isinstance(fact, Mapping):
            continue
        if str(fact.get("subject_ref") or "").strip().lower() in aliases:
            collect(fact)
    return relevant


def project_life_patch_payload(
    payload: Mapping[str, Any], *, shared_registry: Mapping[str, Any] | None = None,
    owner_person_id: str = "me",
) -> dict[str, Any]:
    current = payload.get("current_life_model") or {}
    delta = payload.get("new_delta_evidence") or {}
    language_raw = delta.get("language") if isinstance(delta, Mapping) and isinstance(delta.get("language"), Mapping) else {}
    ordered_turn_ids = [
        str(row.get("turn_id"))
        for row in (language_raw.get("turns_recent") or [])
        if isinstance(row, Mapping) and row.get("turn_id")
    ]
    short_ref_by_turn_id = {
        turn_id: f"t{index}" for index, turn_id in enumerate(ordered_turn_ids)
    }
    registry = shared_registry or {}
    relevant_turn_ids = _life_relevant_turn_ids(
        delta if isinstance(delta, Mapping) else {}, registry,
        owner_person_id=owner_person_id,
    )
    owner_aliases = {
        str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
    }
    observed_raw = (
        delta.get("observed_life")
        if isinstance(delta, Mapping) and isinstance(delta.get("observed_life"), Mapping)
        else {}
    )
    owner_observed_rows = [
        row for rows in observed_raw.values()
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping)
        and any(
            str(row.get(key) or "").strip().lower() in owner_aliases
            for key in ("subject_person_id", "user_person_id", "person_id")
        )
    ]
    owner_episode_ids = {
        str(row.get("episode_id")) for row in owner_observed_rows if row.get("episode_id")
    }
    projected_delta = {}
    if isinstance(delta, Mapping):
        for name, value in delta.items():
            if name == "brainlive_bridge_delta":
                continue
            if name == "language" and isinstance(value, Mapping):
                projected_delta[str(name)] = _project_life_language(
                    value, owner_person_id=owner_person_id,
                    short_ref_by_turn_id=short_ref_by_turn_id,
                    relevant_turn_ids=relevant_turn_ids,
                )
            elif name == "observed_life" and isinstance(value, Mapping):
                projected_delta[str(name)] = {}
                for section, rows in value.items():
                    if not isinstance(rows, list):
                        projected_delta[str(name)][str(section)] = _prompt_provenance(rows)
                        continue
                    projected_rows = []
                    for row in rows:
                        if not isinstance(row, Mapping):
                            continue
                        item = _prompt_provenance(row)
                        item["source_table"] = str(section)
                        item["source_id"] = _row_id(row) or row.get("choice_id") or row.get("intention_id") or row.get("interaction_id")
                        owner_values = [
                            row.get(key) for key in (
                                "subject_person_id", "user_person_id", "person_id",
                            ) if row.get(key)
                        ]
                        owner_scoped = any(
                            str(v).strip().lower() in owner_aliases for v in owner_values
                        )
                        causal_context = bool(
                            row.get("episode_id")
                            and str(row.get("episode_id")) in owner_episode_ids
                        )
                        if not owner_scoped and not causal_context:
                            continue
                        item["owner_scope"] = (
                            "owner_verified"
                            if owner_scoped else "causal_context_other_person"
                        )
                        projected_rows.append(item)
                    projected_delta[str(name)][str(section)] = projected_rows
            elif name == "self_and_internal" and isinstance(value, Mapping):
                language = delta.get("language") if isinstance(delta.get("language"), Mapping) else {}
                owner_aliases = {
                    str(owner_person_id).strip().lower(), "me", "user", "utilisateur", "william",
                }
                owner_turn_ids = {
                    str(row.get("turn_id"))
                    for row in (language.get("turns_recent") or [])
                    if isinstance(row, Mapping) and row.get("turn_id")
                    and str(row.get("person_id") or "").strip().lower() in owner_aliases
                }
                projected_delta[str(name)] = {
                    str(section): [
                        _prompt_provenance(row)
                        for row in rows if isinstance(row, Mapping)
                        and str(row.get("turn_id") or "") in owner_turn_ids
                    ] if isinstance(rows, list) else _prompt_provenance(rows)
                    for section, rows in value.items()
                }
            else:
                projected_delta[str(name)] = _prompt_provenance(
                    value, key=str(name)
                )
    if isinstance(delta, Mapping) and isinstance(delta.get("brainlive_bridge_delta"), Mapping):
        turns_present = bool(
            ((delta.get("language") or {}).get("turns_recent") or [])
            if isinstance(delta.get("language"), Mapping) else False
        )
        projected_delta["brainlive_bridge_delta"] = _project_life_bridge(
            delta["brainlive_bridge_delta"], turns_present=turns_present,
            owner_person_id=owner_person_id,
        )
    projected_delta["shared_registry"] = _project_life_registry(
        registry, owner_person_id=owner_person_id,
        short_ref_by_turn_id=short_ref_by_turn_id,
    )
    projected_current = (
        _project_current_life_model(
            current, delta_hint=_owner_relevance_hint(projected_delta)
        )
        if isinstance(current, Mapping) else {}
    )
    return {
        "mission": payload.get("mission"),
        "output_cardinality": dict(payload.get("output_cardinality") or {}),
        "current_life_model": projected_current,
        "new_delta_evidence": projected_delta,
        "update_rules": list(payload.get("update_rules") or []),
        "projection_version": PROJECTION_VERSION,
        "source_manifest": {
            "current_digest": content_digest(current),
            "delta_digest": content_digest(delta),
        },
        "_turn_id_map": {
            short_ref: turn_id
            for turn_id, short_ref in short_ref_by_turn_id.items()
        },
    }
