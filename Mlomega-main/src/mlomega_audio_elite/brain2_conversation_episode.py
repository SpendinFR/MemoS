"""E64-I mini-plan 1: one durable conversation episode with ordered subthemes.

This module is deliberately opt-in while the v5 EpisodeBuilder remains the
production rollback path.  It changes the semantic unit, not the evidence:
every cognitive turn belongs to exactly one ordered subtheme, every subtheme
cites primary turns, and the parent episode keeps the complete turn union.
Sensor observations remain separate context and can never become attributed
speech or psychology.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Mapping, Sequence

from .brain2_episode_windowing import (
    _partition_cognitive_and_sensor_turns,
    _prompt_turn,
)
from .night_orchestrator import OllamaWindowLLM, estimate_tokens_for_text


CONVERSATION_EPISODE_BUILD_VERSION = "13.2.0-e64i-conversation-subthemes-v2"

CONVERSATION_EPISODE_SCHEMA: dict[str, Any] = {
    "conversation_episode": {
        "title": "",
        "situation_summary": "",
        "participants": [],
        "location": None,
        "channel": None,
        "confidence": 0.0,
        "subthemes": [
            {
                "subtheme_type": "planning|relationship|identity|work|media|other",
                "title": "",
                "summary": "",
                "boundary_reason": "conversation_start|new_goal|new_question|new_person|new_domain|explicit_transition",
                "participants": [],
                "turn_ids": [],
                "evidence_turn_ids": [],
                "outcome": None,
                "unresolved_tension": None,
                "confidence": 0.0,
            }
        ],
    },
    "missing_context": [],
    "confidence": 0.0,
}

CONVERSATION_EPISODE_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conversation_episode": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 120},
                "situation_summary": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "location": {"type": ["string", "null"]},
                "channel": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "subthemes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subtheme_type": {
                                "type": "string",
                                "enum": [
                                    "planning", "relationship", "identity", "work",
                                    "media", "technical", "other",
                                ],
                            },
                            "title": {"type": "string", "maxLength": 100},
                            "summary": {"type": "string"},
                            "boundary_reason": {
                                "type": "string",
                                "enum": [
                                    "conversation_start", "new_goal", "new_question",
                                    "new_person", "new_domain", "explicit_transition",
                                ],
                            },
                            "participants": {
                                "type": "array", "items": {"type": "string"}
                            },
                            "turn_ids": {
                                "type": "array", "items": {"type": "string"}
                            },
                            "evidence_turn_ids": {
                                "type": "array", "items": {"type": "string"}
                            },
                            "outcome": {"type": ["string", "null"]},
                            "unresolved_tension": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "subtheme_type", "title", "summary", "boundary_reason", "participants",
                            "turn_ids", "evidence_turn_ids", "confidence",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "title", "situation_summary", "participants", "confidence",
                "subthemes",
            ],
            "additionalProperties": False,
        },
        "missing_context": {"type": "array", "items": {}},
        "confidence": {"type": "number"},
    },
    "required": ["conversation_episode", "missing_context"],
    "additionalProperties": False,
}

SEGMENTATION_SCHEMA: dict[str, Any] = {
    "segments": [
        {
            "ordinal": 0,
            "title_hint": "",
            "end_turn_id": "",
            "boundary_reason": "conversation_start|new_goal|new_person|new_domain|explicit_transition",
        }
    ],
    "missing_context": [],
}

SEGMENTATION_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordinal": {"type": "integer", "minimum": 0},
                    "title_hint": {"type": "string", "maxLength": 100},
                    "end_turn_id": {"type": "string"},
                    "boundary_reason": {
                        "type": "string",
                        "enum": [
                            "conversation_start", "new_goal", "new_person",
                            "new_domain", "explicit_transition",
                        ],
                    },
                },
                "required": [
                    "ordinal", "title_hint", "end_turn_id",
                    "boundary_reason",
                ],
                "additionalProperties": False,
            },
        },
        "missing_context": {"type": "array", "items": {}},
    },
    "required": ["segments", "missing_context"],
    "additionalProperties": False,
}

SUBTHEME_DETAIL_SCHEMA: dict[str, Any] = {
    "conversation_episode": {
        "title": "",
        "situation_summary": "",
        "participants": [],
        "location": None,
        "channel": None,
        "confidence": 0.0,
        "subthemes": [
            {
                "ordinal": 0,
                "subtheme_type": "planning|relationship|identity|work|media|technical|other",
                "title": "",
                "summary": "",
                "participants": [],
                "evidence_turn_ids": [],
                "outcome": None,
                "unresolved_tension": None,
                "confidence": 0.0,
            }
        ],
    },
    "missing_context": [],
    "confidence": 0.0,
}

SUBTHEME_DETAIL_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conversation_episode": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 120},
                "situation_summary": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "location": {"type": ["string", "null"]},
                "channel": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "subthemes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ordinal": {"type": "integer", "minimum": 0},
                            "subtheme_type": {
                                "type": "string",
                                "enum": [
                                    "planning", "relationship", "identity", "work",
                                    "media", "technical", "other",
                                ],
                            },
                            "title": {"type": "string", "maxLength": 100},
                            "summary": {"type": "string"},
                            "participants": {
                                "type": "array", "items": {"type": "string"}
                            },
                            "evidence_turn_ids": {
                                "type": "array", "items": {"type": "string"}
                            },
                            "outcome": {"type": ["string", "null"]},
                            "unresolved_tension": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "ordinal", "subtheme_type", "title", "summary",
                            "participants", "evidence_turn_ids", "confidence",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "title", "situation_summary", "participants", "confidence",
                "subthemes",
            ],
            "additionalProperties": False,
        },
        "missing_context": {"type": "array", "items": {}},
        "confidence": {"type": "number"},
    },
    "required": ["conversation_episode", "missing_context"],
    "additionalProperties": False,
}

_SEGMENTATION_MISSION = (
    "Découpe uniquement les frontières thématiques de cette conversation continue. "
    "Retourne seulement la FIN de chaque segment. Le premier commence au premier tour, "
    "chaque suivant commence automatiquement après la fin précédente, et la dernière "
    "fin est le dernier tour. Tous les tours sont ainsi couverts exactement une fois. "
    "Une question qui précise la personne, "
    "la cause ou l'action du sujet courant reste dans le même segment. Commence un "
    "nouveau segment seulement lorsque le but change réellement: vérification d'identité "
    "ou d'interlocuteur, nouvelle personne sans lien avec l'échange, nouveau domaine, "
    "nouvelle activité, ou transition explicite. Un acquiescement/filler appartient au "
    "segment voisin qu'il clôt ou ouvre; il ne crée pas un segment. Ne résume et "
    "n'analyse aucune psychologie: retourne seulement les fins et un titre indicatif."
)

_DETAIL_MISSION = (
    "Les frontières ci-dessous sont verrouillées. Produis exactement un détail par "
    "ordinal sans déplacer, fusionner ni omettre de segment. Résume tous les tours non "
    "phatiques de chaque segment et cite les turn_ids qui prouvent les faits/questions. "
    "Les titres sont courts et humains, sans préfixe technique. Ne déduis aucune "
    "psychologie et conserve l'incertitude de locuteur/ASR. Construis aussi un seul "
    "épisode parent qui résume la conversation sans transformer un propos d'inconnu en "
    "fait sur l'utilisateur."
)

_MISSION = (
    "Construis UN épisode parent pour cette conversation continue, puis découpe-le "
    "en sous-thèmes sémantiques ordonnés. Un sous-thème regroupe un échange cohérent "
    "(par exemple Karim, identification de l'interlocuteur, métier, Netflix), pas une "
    "phrase isolée. Commence un nouveau sous-thème dès que le but sémantique change: "
    "nouvelle question qui n'est pas un suivi direct, vérification d'identité ou "
    "d'interlocuteur, nouvelle personne, nouveau domaine/activité, ou transition "
    "explicite. Ne fusionne pas deux sujets seulement parce qu'ils sont proches dans "
    "le temps. Le résumé d'un sous-thème doit couvrir tous ses tours non phatiques; "
    "s'il faudrait deux titres reliés par 'et/puis', sépare-le. Chaque turn_id de "
    "human_turn_ids doit apparaître exactement une "
    "fois dans subthemes[].turn_ids, dans l'ordre et dans un intervalle contigu. "
    "evidence_turn_ids est un sous-ensemble non vide des turn_ids qui prouve le résumé; "
    "ne réutilise jamais une citation pour deux affirmations incompatibles. Les éléments "
    "sensor_context sont seulement du contexte observé: ne les attribue jamais à une "
    "personne et ne les place pas dans turn_ids. Les titres sont courts, humains, "
    "sans préfixe technique ni copie du titre source. Garde l'incertitude ASR/locuteur, "
    "n'invente ni état psychologique ni issue. Réponds uniquement selon le schéma."
)


class ConversationEpisodeContractError(RuntimeError):
    """The model output cannot be made lossless without inventing semantics."""


def conversation_episode_enabled() -> bool:
    """Use the lossless conversation parent by default; ``=0`` is rollback."""
    return os.environ.get("MLOMEGA_E64_CONVERSATION_EPISODES", "1") != "0"


def _unique_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if item is not None and str(item)))


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def normalize_segmentation(
    output: Any,
    cognitive_turns: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Expand boundary-only output into an exact, gap-free turn partition."""
    if not isinstance(output, Mapping) or not isinstance(output.get("segments"), list):
        raise ConversationEpisodeContractError("segmentation_root_invalid")
    ordered_ids = [
        str(turn.get("turn_id"))
        for turn in cognitive_turns
        if turn.get("turn_id") is not None
    ]
    position = {turn_id: index for index, turn_id in enumerate(ordered_ids)}
    segments: list[dict[str, Any]] = []
    next_start = 0
    for expected_ordinal, raw in enumerate(output.get("segments") or []):
        if not isinstance(raw, Mapping):
            raise ConversationEpisodeContractError("segmentation_item_invalid")
        try:
            ordinal = int(raw.get("ordinal"))
        except (TypeError, ValueError):
            raise ConversationEpisodeContractError("segmentation_ordinal_invalid")
        start_id = str(raw.get("start_turn_id") or "")
        end_id = str(raw.get("end_turn_id") or "")
        if ordinal != expected_ordinal or end_id not in position:
            raise ConversationEpisodeContractError("segmentation_boundary_invalid")
        # The production contract emits end boundaries only.  Exact starts are
        # deterministic: first turn, then the item after the previous end.
        # Legacy outputs carrying a start remain accepted for replay/rollback.
        start = position[start_id] if start_id in position else next_start
        end = position[end_id]
        # Small models often repeat the previous segment's inclusive end as
        # the next inclusive start (A..B, B..C).  The ordered end boundaries
        # still define the exact same semantic partition; canonicalising that
        # overlap to B+1 loses no turn and invents no boundary.  A real gap or
        # a non-increasing end remains a hard failure because repairing either
        # would assign speech to a topic the model did not choose.
        if start < next_start and end >= next_start:
            start = next_start
        if start != next_start or end < start:
            raise ConversationEpisodeContractError("segmentation_gap_overlap_or_order")
        title = str(raw.get("title_hint") or "").strip()
        reason = str(raw.get("boundary_reason") or "").strip()
        if not title or not reason:
            raise ConversationEpisodeContractError("segmentation_semantics_missing")
        turn_ids = ordered_ids[start:end + 1]
        segments.append({
            "ordinal": ordinal,
            "title_hint": title,
            "boundary_reason": reason,
            "start_turn_id": turn_ids[0],
            "end_turn_id": turn_ids[-1],
            "turn_ids": turn_ids,
        })
        next_start = end + 1
    if not segments or next_start != len(ordered_ids):
        raise ConversationEpisodeContractError("segmentation_not_lossless")
    return segments


def combine_segment_details(
    output: Any,
    segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach immutable segmentation membership to the semantic detail output."""
    if not isinstance(output, Mapping) or not isinstance(
        output.get("conversation_episode"), Mapping
    ):
        raise ConversationEpisodeContractError("detail_root_invalid")
    parent = dict(output["conversation_episode"])
    details = parent.get("subthemes")
    if not isinstance(details, list) or len(details) != len(segments):
        raise ConversationEpisodeContractError("detail_cardinality_mismatch")
    by_ordinal: dict[int, Mapping[str, Any]] = {}
    for detail in details:
        if not isinstance(detail, Mapping):
            raise ConversationEpisodeContractError("detail_item_invalid")
        try:
            ordinal = int(detail.get("ordinal"))
        except (TypeError, ValueError):
            raise ConversationEpisodeContractError("detail_ordinal_invalid")
        if ordinal in by_ordinal:
            raise ConversationEpisodeContractError("detail_duplicate_ordinal")
        by_ordinal[ordinal] = detail
    combined: list[dict[str, Any]] = []
    for segment in segments:
        ordinal = int(segment["ordinal"])
        if ordinal not in by_ordinal:
            raise ConversationEpisodeContractError("detail_missing_ordinal")
        detail = dict(by_ordinal[ordinal])
        detail.pop("ordinal", None)
        detail["turn_ids"] = list(segment["turn_ids"])
        detail["boundary_reason"] = segment["boundary_reason"]
        combined.append(detail)
    parent["subthemes"] = combined
    return {
        "conversation_episode": parent,
        "missing_context": list(output.get("missing_context") or []),
        "confidence": output.get("confidence", parent.get("confidence", 0.0)),
    }


def normalize_conversation_episode(
    output: Any,
    cognitive_turns: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate exact membership and adapt the parent to the historic writer.

    Membership coverage is stricter than the window manifest: every cognitive
    turn must occur once, in one contiguous subtheme.  We reject gaps/duplicates
    instead of silently assigning a sentence to a topic selected by code.
    """
    if not isinstance(output, Mapping):
        raise ConversationEpisodeContractError("root_not_object")
    raw_parent = output.get("conversation_episode")
    if not isinstance(raw_parent, Mapping):
        raise ConversationEpisodeContractError("conversation_episode_missing")

    ordered_ids = [
        str(turn.get("turn_id"))
        for turn in cognitive_turns
        if turn.get("turn_id") is not None
    ]
    if not ordered_ids:
        raise ConversationEpisodeContractError("no_cognitive_turns")
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ConversationEpisodeContractError("duplicate_source_turn_id")
    position = {turn_id: index for index, turn_id in enumerate(ordered_ids)}

    raw_subthemes = raw_parent.get("subthemes")
    if not isinstance(raw_subthemes, list) or not raw_subthemes:
        raise ConversationEpisodeContractError("subthemes_missing")

    subthemes: list[dict[str, Any]] = []
    assigned: list[str] = []
    previous_end = -1
    for ordinal, raw in enumerate(raw_subthemes):
        if not isinstance(raw, Mapping):
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_not_object")
        turn_ids = _unique_strings(raw.get("turn_ids"))
        if not turn_ids or any(turn_id not in position for turn_id in turn_ids):
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_invalid_membership")
        positions = [position[turn_id] for turn_id in turn_ids]
        if positions != list(range(min(positions), max(positions) + 1)):
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_non_contiguous")
        if positions[0] <= previous_end:
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_overlap_or_order")
        previous_end = positions[-1]

        evidence = _unique_strings(raw.get("evidence_turn_ids"))
        if not evidence or any(turn_id not in turn_ids for turn_id in evidence):
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_invalid_evidence")
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        if not title or not summary:
            raise ConversationEpisodeContractError(f"subtheme_{ordinal}_missing_semantics")
        assigned.extend(turn_ids)
        subthemes.append({
            "ordinal": ordinal,
            "subtheme_type": str(raw.get("subtheme_type") or "other"),
            "title": title,
            "summary": summary,
            "boundary_reason": str(raw.get("boundary_reason") or "").strip(),
            "participants": _unique_strings(raw.get("participants")),
            "turn_ids": turn_ids,
            "evidence_turn_ids": evidence,
            "start_turn_id": turn_ids[0],
            "end_turn_id": turn_ids[-1],
            "outcome": str(raw.get("outcome")).strip() if raw.get("outcome") else None,
            "unresolved_tension": (
                str(raw.get("unresolved_tension")).strip()
                if raw.get("unresolved_tension") else None
            ),
            "confidence": _confidence(raw.get("confidence")),
        })

    if assigned != ordered_ids:
        missing = [turn_id for turn_id in ordered_ids if turn_id not in assigned]
        duplicates = sorted({turn_id for turn_id in assigned if assigned.count(turn_id) > 1})
        raise ConversationEpisodeContractError(
            f"membership_not_lossless:missing={missing}:duplicates={duplicates}"
        )

    title = str(raw_parent.get("title") or "").strip()
    summary = str(raw_parent.get("situation_summary") or "").strip()
    if not title or len(title) > 120 or not summary:
        raise ConversationEpisodeContractError("parent_missing_semantics")
    participants = _unique_strings(raw_parent.get("participants"))
    if not participants:
        participants = list(dict.fromkeys(
            participant
            for subtheme in subthemes
            for participant in subtheme["participants"]
        ))
    confidence = _confidence(raw_parent.get("confidence", output.get("confidence")))
    parent = {
        "episode_type": "conversation",
        "start_turn_id": ordered_ids[0],
        "end_turn_id": ordered_ids[-1],
        "participants": participants,
        "location": raw_parent.get("location"),
        "channel": raw_parent.get("channel"),
        "topic": title,
        "situation_summary": summary,
        "confidence": confidence,
        "importance_score": confidence,
        "evidence_turn_ids": ordered_ids,
        "subthemes": subthemes,
        "episode_contract": CONVERSATION_EPISODE_BUILD_VERSION,
    }
    return {
        "episodes": [parent],
        "missing_context": list(output.get("missing_context") or []),
        "confidence": confidence,
    }


def _source_quality_gaps(cognitive_turns: Sequence[Mapping[str, Any]]) -> list[str]:
    """Expose deterministic acquisition limits instead of asking the LLM to notice them."""
    unknown_speakers = False
    for turn in cognitive_turns:
        person_id = str(turn.get("person_id") or "")
        if person_id.startswith("UNKNOWN_VOICE_"):
            unknown_speakers = True
            break
        metadata = turn.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        source = metadata.get("source") if isinstance(metadata, Mapping) else None
        resolution = (
            source.get("offline_speaker_resolution")
            if isinstance(source, Mapping) else None
        )
        if isinstance(resolution, Mapping) and str(resolution.get("decision")) == "unknown_cluster":
            unknown_speakers = True
            break
    return ["speaker_identity_unenrolled"] if unknown_speakers else []


def _render_lossless_prompt(
    safe_prompt: Callable[[dict[str, Any]], str],
    payload: dict[str, Any],
) -> str:
    """Reject the legacy reference-only envelope for this semantic stage."""
    rendered = safe_prompt(payload)
    try:
        parsed = json.loads(rendered)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, Mapping) and parsed.get("context_incomplete"):
        raise ConversationEpisodeContractError("prompt_compaction_rejected")
    return rendered


def build_conversation_episode_v6(
    con: Any,
    conversation_id: str,
    *,
    bundle: Mapping[str, Any],
    safe_prompt: Callable[[dict[str, Any]], str],
    materialize: Callable[[Any, str, dict[str, Any]], int],
    system: str,
    window_llm: Any | None = None,
    input_budget: int | None = None,
    output_budget: int | None = None,
) -> dict[str, Any]:
    """Execute boundary detection then semantic detail as two bounded calls.

    Oversized conversations fail before inference.  Windowed subtheme fragments
    are the next I1.3 increment; silently falling back to lossy prompt compaction
    would make the timing prototype meaningless.
    """
    turns = list(bundle.get("turns") or [])
    cognitive_turns, sensor_turns = _partition_cognitive_and_sensor_turns(turns)
    if not cognitive_turns:
        return {
            "episodes": 0, "subthemes": 0, "calls": 0,
            "input_tokens": 0, "elapsed_seconds": 0.0,
        }
    projected_turns = [_prompt_turn(turn) for turn in cognitive_turns]
    sensor_context = [_prompt_turn(turn) for turn in sensor_turns]
    segmentation_payload = {
        "mission": _SEGMENTATION_MISSION,
        "contract": {
            "human_turn_ids": [turn.get("turn_id") for turn in projected_turns],
            "membership_rule": "exactly_once_contiguous_ordered",
        },
        "turns": [
            {
                key: turn.get(key)
                for key in (
                    "turn_id", "idx", "speaker_label", "person_id", "start_s",
                    "end_s", "text",
                )
            }
            for turn in projected_turns
        ],
        "schema": SEGMENTATION_SCHEMA,
    }
    segmentation_prompt = _render_lossless_prompt(safe_prompt, segmentation_payload)
    if output_budget is None:
        try:
            output_budget = max(
                512, int(os.environ.get("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "4096"))
            )
        except ValueError:
            output_budget = 4096
    if input_budget is None:
        try:
            context = int(os.environ.get("MLOMEGA_OLLAMA_CONTEXT_POSTSTOP", "16384"))
        except ValueError:
            context = 16384
        input_budget = max(1000, context - int(output_budget) - 768)
    segmentation_tokens = estimate_tokens_for_text(segmentation_prompt)
    if segmentation_tokens > int(input_budget):
        raise ConversationEpisodeContractError(
            f"input_budget_exceeded:{segmentation_tokens}>{int(input_budget)}"
        )

    injected_llm = window_llm
    if injected_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        segmentation_llm = OllamaWindowLLM(
            system=system,
            schema_hint=SEGMENTATION_SCHEMA,
            format_schema=SEGMENTATION_FORMAT_SCHEMA,
            timeout=timeout,
        )
    else:
        segmentation_llm = injected_llm
    started = time.perf_counter()
    segmentation_result = segmentation_llm.generate(
        {
            "prompt": segmentation_prompt,
            "schema_hint": SEGMENTATION_SCHEMA,
            "format_schema": SEGMENTATION_FORMAT_SCHEMA,
        },
        output_budget=min(1536, int(output_budget)),
    )
    if not getattr(segmentation_result, "ok", False):
        raise ConversationEpisodeContractError(
            "segmentation_llm_failed:"
            f"{getattr(segmentation_result, 'error_kind', None)}:"
            f"{getattr(segmentation_result, 'finish_reason', None)}"
        )
    segments = normalize_segmentation(segmentation_result.data, cognitive_turns)

    by_id = {str(turn.get("turn_id")): turn for turn in projected_turns}
    detail_payload = {
        "mission": _DETAIL_MISSION,
        "conversation": dict(bundle.get("conversation") or {}),
        "segments": [
            {
                **dict(segment),
                "turns": [by_id[turn_id] for turn_id in segment["turn_ids"]],
            }
            for segment in segments
        ],
        "sensor_context": sensor_context,
        "schema": SUBTHEME_DETAIL_SCHEMA,
    }
    detail_prompt = _render_lossless_prompt(safe_prompt, detail_payload)
    detail_tokens = estimate_tokens_for_text(detail_prompt)
    if detail_tokens > int(input_budget):
        raise ConversationEpisodeContractError(
            f"input_budget_exceeded:{detail_tokens}>{int(input_budget)}"
        )
    if injected_llm is None:
        detail_llm = OllamaWindowLLM(
            system=system,
            schema_hint=SUBTHEME_DETAIL_SCHEMA,
            format_schema=SUBTHEME_DETAIL_FORMAT_SCHEMA,
            timeout=timeout,
        )
    else:
        detail_llm = injected_llm
    detail_result = detail_llm.generate(
        {
            "prompt": detail_prompt,
            "schema_hint": SUBTHEME_DETAIL_SCHEMA,
            "format_schema": SUBTHEME_DETAIL_FORMAT_SCHEMA,
        },
        output_budget=int(output_budget),
    )
    elapsed = time.perf_counter() - started
    if not getattr(detail_result, "ok", False):
        raise ConversationEpisodeContractError(
            "detail_llm_failed:"
            f"{getattr(detail_result, 'error_kind', None)}:"
            f"{getattr(detail_result, 'finish_reason', None)}"
        )
    combined = combine_segment_details(detail_result.data, segments)
    normalized = normalize_conversation_episode(combined, cognitive_turns)
    normalized["missing_context"] = list(dict.fromkeys([
        *normalized.get("missing_context", []),
        *_source_quality_gaps(cognitive_turns),
    ]))
    count = materialize(con, conversation_id, normalized)
    return {
        "episodes": count,
        "subthemes": len(normalized["episodes"][0]["subthemes"]),
        "calls": 2,
        "input_tokens": segmentation_tokens + detail_tokens,
        "segmentation_input_tokens": segmentation_tokens,
        "detail_input_tokens": detail_tokens,
        "elapsed_seconds": round(elapsed, 4),
        "output": normalized,
    }
