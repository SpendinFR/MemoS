"""E64-F wave 1 - windowed EpisodeBuilder around the UNCHANGED V13 prompt.

The single Brain2 episode_builder call over a whole day's conversation truncates
(OBS-13). This module keeps the exact V13 prompt/schema and instead runs it over
autonomous windows of turns (E64-C planning), then merges the structured episode
outputs (E64-D overlap dedup) and persists a coverage proof (E64-E). It does NOT
build a giant prompt, does NOT alter the V13 prompt text, and loses no turn: the
windows partition the turns (+bounded overlap) and coverage blocks on any gap.

The reusable V13 helpers (``conversation_bundle``, ``safe_prompt``, ``llm_call``,
``materialize``) are injected by ``brain2_strict_v13_2`` so this module never
imports it back (no cycle).
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Callable, Mapping, Sequence

from .night_orchestrator import (
    MergeItem,
    ModelBudget,
    OllamaWindowLLM,
    PlanUnit,
    PlannedWindow,
    StageScope,
    build_coverage_report,
    covered_refs_from_outputs_table,
    estimate_tokens_for_text,
    project_opaque_ref_lists,
    resolve_overlap,
    run_windows,
)
from .night_orchestrator import checkpoint_store as cp
from .night_orchestrator.coverage import persist_coverage
from .night_orchestrator.evidence_ref import content_digest

STAGE_NAME = "brain2_episodes"

# Real Ollama structured-output contract. STRICT_EPISODE_SCHEMA is the historic
# business template shown to Brain2; this JSON Schema constrains decoding so the
# model cannot replace evidence IDs with verbose copied turn objects or invent
# extra meta fields until num_predict is exhausted.
EPISODE_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "episode_type": {"type": "string"},
                    "start_turn_id": {"type": ["string", "null"]},
                    "end_turn_id": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "participants": {"type": "array", "items": {}},
                    "location": {"type": ["string", "null"]},
                    "channel": {"type": ["string", "null"]},
                    "topic": {"type": ["string", "null"]},
                    "situation_summary": {"type": "string"},
                    "trigger": {"type": ["string", "null"]},
                    "user_state_before": {},
                    "speech_or_action": {"type": ["string", "null"]},
                    "target_person": {"type": ["string", "null"]},
                    "target_reaction": {"type": ["string", "null"]},
                    "user_state_after": {},
                    "outcome": {"type": ["string", "null"]},
                    "unresolved_tension": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "evidence_turn_ids": {
                        "type": "array", "items": {"type": "string"},
                    },
                    "evidence_texts": {
                        "type": "array", "items": {"type": "string"},
                    },
                },
                "required": ["episode_type", "situation_summary", "evidence_turn_ids"],
                "additionalProperties": False,
            },
        },
        "counter_evidence": {"type": "array", "items": {}},
        "missing_context": {"type": "array", "items": {}},
        "confidence": {"type": "number"},
    },
    "required": ["episodes", "missing_context"],
    "additionalProperties": False,
}


def _source_coverage(
    turns: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, list[str]]]:
    """Expand vision atom turns back to their raw observation evidence.

    Ordinary audio/context turns remain direct evidence. A reduced vision turn
    is the atom ID and its ``metadata_json.source.source_refs`` are the raw
    observations it represents. This is what lets the final manifest prove the
    original 985 inputs rather than merely the ~160 reduced prompt units.
    """
    expected: list[str] = []
    atom_parents: dict[str, list[str]] = {}
    for i, turn in enumerate(turns):
        turn_id = str(turn.get("turn_id") or f"idx{turn.get('idx', i)}")
        metadata = turn.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        refs = source.get("source_refs") if isinstance(source, Mapping) else None
        if source and source.get("vision_change_atom") and isinstance(refs, list):
            parents = [str(ref) for ref in refs if ref]
            if parents:
                atom_parents[turn_id] = parents
                expected.extend(parents)
                continue
        expected.append(turn_id)
    return list(dict.fromkeys(expected)), atom_parents


def _turn_metadata(turn: Mapping[str, Any]) -> Mapping[str, Any]:
    value = turn.get("metadata_json")
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _is_sensor_only_turn(turn: Mapping[str, Any]) -> bool:
    """Use the producer contract, never text heuristics, to route sensor evidence."""
    metadata = _turn_metadata(turn)
    return (
        str(metadata.get("evidence_role") or "")
        == "system_observation_not_user_speech"
    )


def _partition_cognitive_and_sensor_turns(
    turns: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    cognitive: list[Mapping[str, Any]] = []
    sensor: list[Mapping[str, Any]] = []
    for turn in turns:
        (sensor if _is_sensor_only_turn(turn) else cognitive).append(turn)
    return cognitive, sensor


def cognitive_prompt_turns(
    turns: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Shared E64 projection for every cognitive nocturnal stage."""
    cognitive, _sensor = _partition_cognitive_and_sensor_turns(turns)
    return [_prompt_turn(turn) for turn in cognitive]


def _sensor_routing_coverage(
    turns: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, list[str]], set[str]]:
    expected, atom_parents = _source_coverage(turns)
    direct_turn_ids = {
        str(turn.get("turn_id"))
        for turn in turns
        if turn.get("turn_id") and str(turn.get("turn_id")) not in atom_parents
    }
    return expected, atom_parents, set(atom_parents) | direct_turn_ids


def orchestrator_enabled() -> bool:
    """E64 night orchestrator flag. Default ON; set MLOMEGA_E64_NIGHT_ORCHESTRATOR=0 to roll back."""
    return os.environ.get("MLOMEGA_E64_NIGHT_ORCHESTRATOR", "1") != "0"


def _poststop_input_budget() -> int:
    """Token budget for the TURNS in one window (leaves room for prompt+output)."""
    try:
        return max(1000, int(os.environ.get("MLOMEGA_E64_WINDOW_INPUT_TOKENS", "9000")))
    except ValueError:
        return 9000


def _prompt_turn(turn: Mapping[str, Any]) -> dict[str, Any]:
    """Project one turn for the LLM without altering durable provenance.

    Brain2 still sees the atom ID, semantic text, timestamps and state. Only the
    opaque raw observation/frame ID arrays are replaced by count+digest
    manifests. `_source_coverage` continues to read the untouched turns.
    """
    opaque_fields = {
        "source_refs", "frame_refs", "source_event_ids",
        "reconciles_live_turn_ids",
    }
    projected = project_opaque_ref_lists(dict(turn), field_names=opaque_fields)
    metadata = projected.get("metadata_json")
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, Mapping):
            prompt_metadata = project_opaque_ref_lists(
                parsed, field_names=opaque_fields
            )
            source = prompt_metadata.get("source")
            if isinstance(source, dict):
                # The full word list is already represented exactly by the turn
                # text + start/end timestamps. WhisperX also embeds the same word
                # list a second time. Preserve alignment quality/span as semantic
                # metadata, not thousands of duplicate JSON tokens.
                words = source.pop("words", None)
                whisperx = source.pop("whisperx_metadata", None)
                if isinstance(words, list) and words:
                    scores = [
                        float(word["score"])
                        for word in words
                        if isinstance(word, Mapping) and word.get("score") is not None
                    ]
                    source["word_alignment"] = {
                        "count": len(words),
                        "start": next((w.get("start") for w in words if isinstance(w, Mapping)), None),
                        "end": next((w.get("end") for w in reversed(words) if isinstance(w, Mapping)), None),
                        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
                        "min_score": round(min(scores), 4) if scores else None,
                        "digest": content_digest(words),
                    }
                if isinstance(whisperx, Mapping):
                    source["segmentation"] = {
                        "level": whisperx.get("segmentation_level"),
                        "version": whisperx.get("segmentation_version"),
                    }
                if not source.get("live_speaker_hints"):
                    source.pop("live_speaker_hints", None)

                # For vision atoms, `turn.text` already contains summary,
                # location, spatial context, objects, affordances and possible
                # activities. Keep only representative fields not encoded there.
                representative = source.get("representative")
                if source.get("vision_change_atom") and isinstance(representative, Mapping):
                    extras = {
                        key: representative.get(key)
                        for key in ("visible_text", "personal_relevance")
                        if representative.get(key)
                    }
                    if extras:
                        source["representative_extras"] = extras
                    source.pop("representative", None)
            # The model needs semantic capture quality, not storage addresses.
            # Durable provenance remains untouched in the source turn and in the
            # independent coverage manifest.  Keep only meaning-bearing metadata
            # in the prompt so a long WhisperX segment cannot dominate every
            # downstream engine input.
            semantic_top = {
                key: prompt_metadata.get(key)
                for key in ("kind", "evidence_role", "time", "end_time")
                if prompt_metadata.get(key) is not None
            }
            source = prompt_metadata.get("source")
            if isinstance(source, Mapping) and source.get("word_alignment"):
                alignment = dict(source.get("word_alignment") or {})
                alignment.pop("digest", None)
                resolution = source.get("offline_speaker_resolution")
                if isinstance(resolution, Mapping):
                    resolution = {
                        key: resolution.get(key)
                        for key in (
                            "decision", "person_id", "speaker_label",
                            "known_score", "duration_s",
                        )
                        if resolution.get(key) is not None
                    }
                semantic_top["source"] = {
                    "local_start_s": source.get("local_start_s"),
                    "local_end_s": source.get("local_end_s"),
                    "offline_speaker_resolution": resolution,
                    "word_alignment": alignment,
                    "segmentation": source.get("segmentation"),
                    "source_event_count": (
                        source.get("source_event_ids_manifest") or {}
                    ).get("count"),
                    "reconciled_live_turn_count": (
                        source.get("reconciles_live_turn_ids_manifest") or {}
                    ).get("count"),
                }
                prompt_metadata = semantic_top
            elif isinstance(source, Mapping) and source.get("vision_change_atom"):
                semantic_top["source"] = {
                    key: source.get(key)
                    for key in (
                        "vision_change_atom", "count", "first_seen", "last_seen", "state",
                        "representative_extras",
                    )
                    if source.get(key) is not None
                }
                semantic_top["source"]["source_refs_manifest"] = (
                    source.get("source_refs_manifest") or {}
                )
                semantic_top["source"]["frame_refs_manifest"] = (
                    source.get("frame_refs_manifest") or {}
                )
                prompt_metadata = semantic_top
            projected["metadata_json"] = json.dumps(
                prompt_metadata, ensure_ascii=False, sort_keys=True
            )
    return projected


def _turn_units(turns: Sequence[Mapping[str, Any]]) -> tuple[list[PlanUnit], dict[str, Mapping[str, Any]]]:
    units: list[PlanUnit] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for i, t in enumerate(turns):
        ref = str(t.get("turn_id") or f"idx{t.get('idx', i)}")
        prompt_turn = _prompt_turn(t)
        # Budget and checkpoint the exact LLM-facing projection. The untouched
        # source refs remain in `turns` for the independent coverage proof.
        payload_digest = content_digest(prompt_turn)
        tokens = estimate_tokens_for_text(str(prompt_turn)) + 24
        units.append(
            PlanUnit(
                ref_id=ref, tokens=tokens, ts=str(t.get("idx", i)),
                content_digest=payload_digest,
            )
        )
        by_id[ref] = prompt_turn
    return units, by_id


def should_window(turns: Sequence[Mapping[str, Any]], *, budget_tokens: int | None = None) -> bool:
    """True when the turns would not comfortably fit one V13 call.

    Small conversations keep the legacy single-call path (behaviour unchanged);
    only oversized ones are windowed, minimising blast radius.
    """
    budget = budget_tokens or _poststop_input_budget()
    # The legacy one-shot path serialises the complete turn, including metadata.
    # Looking only at `text` previously let a short transcript with enormous raw
    # vision/WhisperX metadata bypass the projection/windowing path.
    total = sum(estimate_tokens_for_text(str(dict(t))) + 24 for t in turns)
    return total > budget


def _dedupe_episodes(episodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge compatible episodes that share overlap evidence.

    The semantic key uses structural business fields, never summaries/text. Two
    compatible episodes collapse only if E64-D also proves evidence or time
    overlap; partially different evidence sets across adjacent windows therefore
    merge correctly and keep their union.
    """
    items: list[MergeItem] = []
    payloads: dict[str, dict[str, Any]] = {}
    for i, ep in enumerate(episodes):
        if not isinstance(ep, dict):
            continue
        ev = [str(x) for x in (ep.get("evidence_turn_ids") or []) if x]
        participants = sorted(
            str(x).strip().casefold()
            for x in (ep.get("participants") or [])
            if str(x).strip()
        )
        key = "|".join([
            "episode",
            str(ep.get("episode_type") or "other").strip().casefold(),
            ",".join(participants),
            str(ep.get("target_person") or "").strip().casefold(),
            str(ep.get("channel") or "").strip().casefold(),
            str(ep.get("location") or "").strip().casefold(),
        ])
        item_id = f"ep{i}"
        payloads[item_id] = dict(ep)
        items.append(
            MergeItem(
                item_id=item_id,
                semantic_key=key,
                evidence_refs=frozenset(ev),
                time_start=str(ep.get("start_time") or ep.get("start_turn_id") or ""),
                time_end=str(ep.get("end_time") or ep.get("end_turn_id") or ""),
                payload={"item_id": item_id},
            )
        )
    survivors = resolve_overlap(items).survivors
    merged: list[dict[str, Any]] = []
    for surv in survivors:
        ep = payloads[surv.payload["item_id"]]
        # Preserve the union of evidence turns discovered across duplicates.
        if surv.evidence_refs:
            ep["evidence_turn_ids"] = sorted(surv.evidence_refs)
        merged.append(ep)
    return merged


def _scalar_text(value: Any) -> str | None:
    """Coerce an optional schema scalar without leaking dicts into SQLite."""
    if value is None or value == "" or value == {} or value == []:
        return None
    if isinstance(value, Mapping):
        for key in ("name", "label", "text", "value", "person_id", "turn_id"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item) or None
    return str(value)


def _normalise_episode_output(
    output: Any,
    units: Sequence[PlanUnit],
    primary_units: Sequence[PlanUnit] | None = None,
) -> dict[str, Any] | None:
    """Repair harmless Qwen shape drift, while rejecting unsupported claims.

    Qwen may echo evidence as ``{turn_id, text}`` despite the V13 template
    requesting IDs. Extracting the cited durable ID is lossless. Episodes with
    no valid citation in the current window are excluded: they must never become
    memory merely because the model emitted meta-commentary.
    """
    if not isinstance(output, Mapping):
        return None
    allowed = {unit.ref_id for unit in units}
    primary = {
        unit.ref_id for unit in (primary_units if primary_units is not None else units)
    }
    episodes: list[dict[str, Any]] = []
    for raw in output.get("episodes") or []:
        if not isinstance(raw, Mapping):
            continue
        refs: list[str] = []
        for evidence in raw.get("evidence_turn_ids") or []:
            ref = evidence.get("turn_id") if isinstance(evidence, Mapping) else evidence
            if ref and str(ref) in allowed:
                refs.append(str(ref))
        refs = list(dict.fromkeys(refs))
        if not refs or not primary.intersection(refs):
            continue
        episode = dict(raw)
        episode["evidence_turn_ids"] = refs
        start = _scalar_text(episode.get("start_turn_id"))
        end = _scalar_text(episode.get("end_turn_id"))
        episode["start_turn_id"] = start if start in allowed else refs[0]
        episode["end_turn_id"] = end if end in allowed else refs[-1]
        for field in (
            "episode_type", "start_time", "end_time", "location", "channel",
            "topic", "situation_summary", "trigger", "speech_or_action",
            "target_person", "target_reaction", "outcome", "unresolved_tension",
        ):
            episode[field] = _scalar_text(episode.get(field))
        if not episode.get("situation_summary") and not episode.get("topic"):
            continue
        episodes.append(episode)
    return {
        "episodes": episodes,
        "counter_evidence": list(output.get("counter_evidence") or []),
        "missing_context": list(output.get("missing_context") or []),
        "confidence": output.get("confidence", 0.0),
    }


def build_episodes_windowed(
    con: Any,
    conversation_id: str,
    *,
    bundle: Mapping[str, Any],
    person_id: str,
    package_date: str,
    safe_prompt: Callable[[dict[str, Any]], str],
    materialize: Callable[[Any, str, dict[str, Any]], int],
    mission: str,
    schema: dict[str, Any],
    system: str,
    window_llm: Any | None = None,
    model_name: str | None = None,
    context_window: int | None = None,
    output_budget: int | None = None,
    budget_tokens: int | None = None,
    target_turns: int | None = None,
    overlap: int | None = None,
) -> dict[str, Any]:
    """Run the V13 episode prompt per window, merge episodes, persist coverage.

    Returns a summary dict incl. ``episodes`` (materialised count), ``windows``
    and ``coverage_ok``. Raises if any turn is left uncovered (missing).
    """
    turns = list(bundle.get("turns") or [])
    cognitive_turns, sensor_turns = _partition_cognitive_and_sensor_turns(turns)
    units, by_id = _turn_units(cognitive_turns)

    # Sensor observations are not dialogue and must not independently create
    # psychological/narrative episodes.  They remain durably routed to
    # Vision/WorldBrain/Silent Life and a bounded local slice is exposed as
    # context for nearby human speech.  Their raw parents are still proven by a
    # separate deterministic coverage manifest below.
    sensor_prompt_turns = [_prompt_turn(turn) for turn in sensor_turns]
    ordered_sensor = sorted(
        sensor_prompt_turns, key=lambda turn: int(turn.get("idx") or 0)
    )
    sensor_neighbors_by_turn: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        primary_idx = int(by_id[unit.ref_id].get("idx") or 0)
        before = [turn for turn in ordered_sensor if int(turn.get("idx") or 0) <= primary_idx]
        after = [turn for turn in ordered_sensor if int(turn.get("idx") or 0) >= primary_idx]
        selected: dict[str, dict[str, Any]] = {}
        for turn in ((before[-1] if before else None), (after[0] if after else None)):
            if turn:
                selected[str(turn.get("turn_id") or turn.get("idx"))] = turn
        sensor_neighbors_by_turn[unit.ref_id] = list(selected.values())
    units = [
        PlanUnit(
            ref_id=unit.ref_id,
            tokens=unit.tokens + sum(
                estimate_tokens_for_text(json.dumps(turn, ensure_ascii=False)) + 8
                for turn in sensor_neighbors_by_turn.get(unit.ref_id, [])
            ),
            boundary=unit.boundary,
            ts=unit.ts,
            content_digest=content_digest({
                "turn": by_id[unit.ref_id],
                "sensor_context": sensor_neighbors_by_turn.get(unit.ref_id, []),
            }),
        )
        for unit in units
    ]
    if not units:
        sensor_expected, sensor_atom_parents, sensor_covered = _sensor_routing_coverage(sensor_turns)
        sensor_report = build_coverage_report(
            stage_name="brain2_sensor_routing",
            expected_ids=sensor_expected,
            covered_refs=sensor_covered,
            atom_parent_index=sensor_atom_parents,
        )
        persist_coverage(
            con, person_id=person_id, package_date=package_date,
            source_ref=conversation_id, report=sensor_report,
        )
        con.commit()
        if not sensor_report.ok:
            raise RuntimeError(
                f"brain2 sensor routing incomplete: missing={len(sensor_report.missing)}"
            )
        return {
            "episodes": 0,
            "windows": 0,
            "coverage_ok": True,
            "sensor_routing_ok": True,
            "cognitive_turns": 0,
            "sensor_turns": len(sensor_turns),
            "merged_from": 0,
        }

    # EpisodeBuilder's verbose structured output is the limiting side of this
    # stage. Real qwen3.5:9b telemetry showed four units exhausting the 4096-token
    # answer budget in 66.6 s, while two scoped units completed in 8.3 s and
    # 6.7 s. Start at that measured safe output responsibility; overlap remains
    # readable context and is not credited as primary output.
    if target_turns is None:
        try:
            target_turns = max(
                1, int(os.environ.get("MLOMEGA_E64_EPISODE_TARGET_TURNS", "8"))
            )
        except ValueError:
            target_turns = 8
    if overlap is None:
        try:
            overlap = max(0, int(os.environ.get("MLOMEGA_E64_EPISODE_OVERLAP", "2")))
        except ValueError:
            overlap = 2

    from .config import get_settings

    cfg = get_settings()
    if output_budget is None:
        try:
            output_budget = max(256, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096")))
        except ValueError:
            output_budget = 4096
    safety_margin = 768
    if budget_tokens is not None:
        # Test/diagnostic override means the desired maximum INPUT budget.
        context_window = int(budget_tokens) + int(output_budget) + safety_margin
    context_window = int(context_window or cfg.ollama_context_poststop)
    model_budget = ModelBudget(
        context_window=context_window,
        output_reserve=int(output_budget),
        safety_margin=safety_margin,
    )

    if window_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        window_llm = OllamaWindowLLM(
            system=system, schema_hint=schema,
            format_schema=EPISODE_FORMAT_SCHEMA, timeout=timeout,
        )
    model_name = str(model_name or getattr(window_llm, "model", "injected-window-llm"))
    scoped_stage = f"{STAGE_NAME}:{conversation_id}"

    def _render_scoped(
        window_units: Sequence[PlanUnit],
        primary_units: Sequence[PlanUnit],
    ) -> Mapping[str, Any]:
        primary_ids = {unit.ref_id for unit in primary_units}
        win_turns = []
        for unit in window_units:
            if unit.ref_id not in by_id:
                continue
            prompt_turn = dict(by_id[unit.ref_id])
            prompt_turn["window_role"] = (
                "primary_output" if unit.ref_id in primary_ids else "context_only"
            )
            win_turns.append(prompt_turn)
        win_bundle = dict(bundle)
        win_bundle["turns"] = win_turns
        primary_indices = [
            int(by_id[unit.ref_id].get("idx") or 0)
            for unit in primary_units if unit.ref_id in by_id
        ]
        if primary_indices and sensor_prompt_turns:
            # Temporal join, not arbitrary sampling: for every spoken primary
            # turn retain its immediately preceding and following sensor state.
            # This captures the scene around the utterance while the full sensor
            # timeline remains routed and covered independently.
            selected: dict[str, dict[str, Any]] = {}
            for primary_idx in primary_indices:
                primary_id = next(
                    (
                        unit.ref_id for unit in primary_units
                        if int(by_id[unit.ref_id].get("idx") or 0) == primary_idx
                    ),
                    None,
                )
                for turn in sensor_neighbors_by_turn.get(primary_id or "", []):
                    selected[str(turn.get("turn_id") or turn.get("idx"))] = turn
            # Context only: never primary output, never an invented statement.
            win_bundle["sensor_context"] = sorted(
                selected.values(), key=lambda turn: int(turn.get("idx") or 0)
            )
        else:
            win_bundle["sensor_context"] = []
        window_contract = {
            "primary_turn_ids": [unit.ref_id for unit in primary_units],
            "context_only_turn_ids": [
                unit.ref_id for unit in window_units if unit.ref_id not in primary_ids
            ],
            "instruction": (
                "Use every turn as context, but emit only episodes supported by "
                "at least one primary_output turn. Never emit an episode based "
                "only on context_only turns. evidence_turn_ids must contain IDs, "
                "never copied turn objects."
            ),
        }
        return {"prompt": safe_prompt(
            {
                "mission": mission,
                "window_contract": window_contract,
                "conversation_bundle": win_bundle,
                "schema": schema,
            }
        )}

    def render(window_units: Sequence[PlanUnit]) -> Mapping[str, Any]:
        return _render_scoped(window_units, window_units)

    def render_planned_window(window: PlannedWindow) -> Mapping[str, Any]:
        return _render_scoped(window.units, window.primary_units)

    def normalise_planned_window(output: Any, window: PlannedWindow) -> Any:
        return _normalise_episode_output(
            output, window.units, primary_units=window.primary_units
        )

    def validate(output: Any) -> bool:
        if not isinstance(output, dict):
            return False
        episodes = output.get("episodes")
        missing = output.get("missing_context")
        if not isinstance(episodes, list) or not isinstance(missing, list):
            return False
        return all(
            isinstance(ep, dict)
            and isinstance(ep.get("evidence_turn_ids", []), list)
            for ep in episodes
        )

    def durable_envelope(output: Any, primary: Sequence[PlanUnit]) -> dict[str, Any]:
        # This manifest is written atomically WITH a validated model output. It
        # proves which primary evidence entered that durable result; overlap refs
        # remain copies and are intentionally not credited twice.
        return {
            "schema_version": "e64f.brain2.window.v2",
            "evidence_refs": [u.ref_id for u in primary],
            "result": output,
        }

    empty_bundle = dict(bundle)
    empty_bundle["turns"] = []
    prompt_overhead = estimate_tokens_for_text(
        safe_prompt({
            "mission": mission,
            "window_contract": {
                "primary_turn_ids": [], "context_only_turn_ids": [],
                "instruction": (
                    "Use every turn as context, but emit only episodes supported "
                    "by at least one primary_output turn."
                ),
            },
            "conversation_bundle": empty_bundle,
            "schema": schema,
        })
    )
    stage = run_windows(
        units,
        con=con,
        scope=StageScope(
            person_id=person_id,
            package_date=package_date,
            stage_name=scoped_stage,
            adapter_version="e64f-episode-window-v5-cognitive-routing",
            prompt_version="v13-episode-mission-unchanged-v1",
            model=model_name,
        ),
        llm=window_llm,
        budget=model_budget,
        render=render,
        render_window=render_planned_window,
        validate=validate,
        normalize_window_output=normalise_planned_window,
        decorate_output=durable_envelope,
        target_units=target_turns,
        overlap=overlap,
        prompt_overhead_tokens=prompt_overhead,
        sleeper=time.sleep,
    )

    # Anti-loss proof comes ONLY from validated outputs re-read from the durable
    # output table. It never trusts the planner's in-memory primary list.
    current_window_keys = {window.window_key for window in stage.windows}
    covered = covered_refs_from_outputs_table(
        con,
        person_id=person_id,
        package_date=package_date,
        stage_name=scoped_stage,
        extract_refs=lambda stored: stored.get("evidence_refs", [])
        if isinstance(stored, dict) else (),
        window_keys=current_window_keys,
    )
    expected, atom_parent_index = _source_coverage(cognitive_turns)
    quarantined = {
        source_ref: (window.error_text or "quarantined")
        for window in stage.quarantined
        for ref in window.primary_refs
        for source_ref in atom_parent_index.get(ref, [ref])
    }
    report = build_coverage_report(
        stage_name=STAGE_NAME,
        expected_ids=expected,
        covered_refs=covered,
        atom_parent_index=atom_parent_index,
        quarantined_reasons=quarantined,
    )
    persist_coverage(
        con, person_id=person_id, package_date=package_date,
        source_ref=conversation_id, report=report,
    )

    sensor_expected, sensor_atom_parents, sensor_covered = _sensor_routing_coverage(sensor_turns)
    # Deterministic routing is itself the durable result: every sensor atom is
    # already materialized as a turn and points to all of its raw parents.
    sensor_report = build_coverage_report(
        stage_name="brain2_sensor_routing",
        expected_ids=sensor_expected,
        covered_refs=sensor_covered,
        atom_parent_index=sensor_atom_parents,
    )
    persist_coverage(
        con, person_id=person_id, package_date=package_date,
        source_ref=conversation_id, report=sensor_report,
    )
    con.commit()
    if not report.ok or not sensor_report.ok or not stage.all_completed:
        raise RuntimeError(
            "brain2_episodes incomplete: "
            f"missing={len(report.missing)} quarantined={len(stage.quarantined)} "
            f"states={[w.state for w in stage.windows]}"
        )

    persisted = cp.load_outputs(
        con, person_id=person_id, package_date=package_date, stage_name=scoped_stage,
        window_keys=current_window_keys,
    )
    all_eps: list[Mapping[str, Any]] = []
    missing_context: list[Any] = []
    for row in persisted:
        envelope = row.get("output") if isinstance(row, dict) else None
        out = envelope.get("result") if isinstance(envelope, dict) else None
        if isinstance(out, dict):
            all_eps.extend(x for x in (out.get("episodes") or []) if isinstance(x, dict))
            missing_context.extend(out.get("missing_context") or [])

    merged = _dedupe_episodes(all_eps)
    count = materialize(con, conversation_id, {"episodes": merged, "missing_context": missing_context})
    return {
        "episodes": count,
        "windows": len(stage.windows),
        "coverage_ok": report.ok,
        "sensor_routing_ok": sensor_report.ok,
        "cognitive_turns": len(cognitive_turns),
        "sensor_turns": len(sensor_turns),
        "merged_from": len(all_eps),
    }
