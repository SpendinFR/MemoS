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
from .night_orchestrator import (
    ModelBudget,
    OllamaWindowLLM,
    PlanUnit,
    PlannedWindow,
    StageScope,
    estimate_tokens_for_text,
    run_windows,
)
from .night_orchestrator import checkpoint_store as cp
from .night_orchestrator.evidence_ref import content_digest


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


SEGMENTATION_STAGE_NAME = "brain2_conversation_segmentation"
DETAIL_STAGE_NAME = "brain2_conversation_detail"
CONVERSATION_ADAPTER_VERSION = "e64i-conversation-window-v1"
SEGMENTATION_PROMPT_VERSION = "v6-segmentation-boundaries-unchanged-v1"
DETAIL_PROMPT_VERSION = "v6-detail-locked-segments-unchanged-v1"


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


def _conversation_overlap() -> int:
    """Bounded read-only context carried at each segmentation window head."""
    try:
        return max(0, int(os.environ.get("MLOMEGA_E64_CONVERSATION_OVERLAP", "3")))
    except ValueError:
        return 3


def _conversation_target_turns() -> int:
    """Soft cap on primary turns per segmentation window (budget still governs)."""
    try:
        return max(1, int(os.environ.get("MLOMEGA_E64_CONVERSATION_TARGET_TURNS", "40")))
    except ValueError:
        return 40


def _segmentation_turn_projection(turn: Mapping[str, Any]) -> dict[str, Any]:
    """The exact fields the segmentation prompt shows for one turn."""
    return {
        key: turn.get(key)
        for key in (
            "turn_id", "idx", "speaker_label", "person_id", "start_s",
            "end_s", "text",
        )
    }


def _segmentation_units(projected_turns: Sequence[Mapping[str, Any]]) -> list[PlanUnit]:
    """One PlanUnit per ordered cognitive turn, budgeted on its prompt slice.

    ``ref_id`` is the durable ``turn_id`` and ``ts`` its ordinal, so windows carry
    the temporal order the boundary contract depends on. ``content_digest`` covers
    the exact fields shown to the model, so a corrected transcript keeping the same
    id never resumes a stale boundary checkpoint.
    """
    units: list[PlanUnit] = []
    for index, turn in enumerate(projected_turns):
        slice_ = _segmentation_turn_projection(turn)
        ref = str(turn.get("turn_id"))
        tokens = estimate_tokens_for_text(
            json.dumps(slice_, ensure_ascii=False, sort_keys=True, default=str)
        ) + 24
        units.append(
            PlanUnit(
                ref_id=ref,
                tokens=tokens,
                ts=str(turn.get("idx", index)),
                content_digest=content_digest(slice_),
            )
        )
    return units


def normalize_window_segmentation(
    output: Any,
    window: PlannedWindow,
    ordered_ids: Sequence[str],
) -> list[dict[str, Any]] | None:
    """Local, provenance-scoped boundary partition of ONE window's primary turns.

    The model only ever sees/labels boundaries for this window's primary turns
    (overlap turns are read-only context). We reconstruct the exact local
    partition here: every emitted end must land on a primary turn, ends are
    strictly ordered, and the final end is forced to the window's last primary
    turn so windows abut with neither gap nor duplicate. Returning ``None`` marks
    a contract failure so the executor subdivides/quarantines - never a text merge.

    Each local segment carries provenance the global reassembly needs to avoid an
    artificial thematic cut at a window edge: ``window_first`` on the segment that
    opens the window, ``window_last`` on the one that closes it, and
    ``window_boundary_forced`` on that last segment when the window edge did NOT
    coincide with a real semantic boundary emitted by the model. A window edge is
    "forced" when the code had to override the model's last end to reach the
    window's final primary turn (the model's last real boundary was earlier), OR
    when the model itself closed the window on that turn but marked it a
    continuation (``conversation_start`` boundary_reason) rather than a fresh
    theme. Either way the theme spills into the next window and the reassembly may
    fuse the two fragments BY PROVENANCE (never by text).
    """
    if not isinstance(output, Mapping) or not isinstance(output.get("segments"), list):
        return None
    position = {turn_id: index for index, turn_id in enumerate(ordered_ids)}
    primary_ids = [unit.ref_id for unit in window.primary_units]
    if not primary_ids or any(pid not in position for pid in primary_ids):
        return None
    primary_positions = [position[pid] for pid in primary_ids]
    if primary_positions != list(range(primary_positions[0], primary_positions[-1] + 1)):
        # plan_windows keeps primary units contiguous; a non-contiguous window is
        # a planning invariant break, not something to repair by text.
        return None
    lo, hi = primary_positions[0], primary_positions[-1]
    # A window that opens strictly after the whole conversation's first turn opens
    # in the middle of the ordered turns; its first segment may continue a theme
    # carried in the overlap context (provenance the reassembly checks per edge).
    window_opens_mid = lo > 0
    segments: list[dict[str, Any]] = []
    next_start = lo
    for expected_ordinal, raw in enumerate(output.get("segments") or []):
        if not isinstance(raw, Mapping):
            return None
        end_id = str(raw.get("end_turn_id") or "")
        if end_id not in position:
            return None
        end = position[end_id]
        # A boundary can only end on one of THIS window's primary turns and must
        # advance strictly. Anything else is the model straying into overlap
        # context or repeating a boundary - reject rather than silently coerce.
        if end < next_start or end > hi:
            return None
        title = str(raw.get("title_hint") or "").strip()
        reason = str(raw.get("boundary_reason") or "").strip()
        if not title or not reason:
            return None
        segments.append({
            "end_turn_id": ordered_ids[end],
            "title_hint": title,
            "boundary_reason": reason,
        })
        next_start = end + 1
    if not segments:
        return None
    # The window is a hard segment end: force the last local segment to close on
    # the window's final primary turn so the next window starts exactly after it.
    model_closed_on_edge = segments[-1]["end_turn_id"] == ordered_ids[hi]
    if not model_closed_on_edge:
        segments[-1] = {**segments[-1], "end_turn_id": ordered_ids[hi]}
    # Provenance: the edge is a forced (non-semantic) cut when either the code had
    # to override the model's last end, or the model closed the window itself but
    # tagged it a continuation rather than a genuinely new theme.
    boundary_forced = (not model_closed_on_edge) or (
        segments[-1].get("boundary_reason") == "conversation_start"
    )
    # The first local segment continues from the overlap when the model opened it
    # with a continuation marker instead of a new-theme reason (only meaningful
    # when the window itself opens mid-conversation).
    first_is_continuation = window_opens_mid and (
        segments[0].get("boundary_reason") == "conversation_start"
    )
    segments[0] = {**segments[0], "window_first": True, "window_first_continuation": first_is_continuation}
    segments[-1] = {
        **segments[-1],
        "window_last": True,
        "window_boundary_forced": boundary_forced,
    }
    return segments


def _fuse_forced_window_edges(
    end_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Drop forced window-edge ends that split ONE theme across two windows.

    ``end_records`` are the per-window local segments already ordered globally by
    their end position. Adjacent records straddle a window edge exactly when the
    left one carries ``window_last`` and the right one ``window_first``. That edge
    is an ARTIFICIAL cut of a single theme when the left end is
    ``window_boundary_forced`` (the window closed it only because the window ended,
    not because the model saw a new theme) AND the right segment opened as a
    continuation (``window_first_continuation``). Removing the left record fuses
    the two fragments: the right segment now inherits the earlier start, so
    ``normalize_segmentation`` rebuilds one contiguous segment covering both.

    The decision is pure provenance (window role + the model's own boundary_reason
    markers) and the union of turns: no text similarity, no dedup, and a genuine
    semantic boundary at a window edge (not forced, or the next head is a new
    theme) is left exactly where the model put it.
    """
    kept: list[dict[str, Any]] = []
    records = list(end_records)
    for index, record in enumerate(records):
        nxt = records[index + 1] if index + 1 < len(records) else None
        is_forced_edge = bool(record.get("window_last")) and bool(
            record.get("window_boundary_forced")
        )
        next_continues = (
            nxt is not None
            and bool(nxt.get("window_first"))
            and bool(nxt.get("window_first_continuation"))
        )
        if is_forced_edge and next_continues:
            # Fuse: skip this forced end so the next segment spans both fragments.
            continue
        kept.append(dict(record))
    return kept


def _run_segmentation_windows(
    con: Any,
    *,
    units: Sequence[PlanUnit],
    projected_turns: Sequence[Mapping[str, Any]],
    ordered_ids: Sequence[str],
    safe_prompt: Callable[[dict[str, Any]], str],
    window_llm: Any,
    model_budget: ModelBudget,
    scope_person: str,
    scope_date: str,
    model_name: str,
    overlap: int,
    target_units: int,
) -> tuple[list[dict[str, Any]], int]:
    """Windowed pass 1: assemble a global contiguous partition BY CODE.

    Each window emits boundaries only for its primary turns; the local partitions
    are concatenated in window order (their end boundaries are strictly ordered
    across the whole conversation because primary turns partition the order
    exactly once). ``normalize_segmentation`` then rebuilds the exact global
    membership from that ordered end list. Returns ``(segments, window_count)``.
    """
    by_id = {str(turn.get("turn_id")): turn for turn in projected_turns}

    def _render(window: PlannedWindow) -> Mapping[str, Any]:
        primary_ids = {unit.ref_id for unit in window.primary_units}
        payload = {
            "mission": _SEGMENTATION_MISSION,
            "contract": {
                "human_turn_ids": [unit.ref_id for unit in window.primary_units],
                "context_only_turn_ids": [
                    unit.ref_id for unit in window.units if unit.ref_id not in primary_ids
                ],
                "membership_rule": "exactly_once_contiguous_ordered",
                "instruction": (
                    "Ne place des frontières (end_turn_id) QUE pour les tours de "
                    "human_turn_ids. Les tours context_only sont seulement du "
                    "contexte de lecture: n'y place jamais de frontière. La "
                    "dernière frontière est le dernier tour de human_turn_ids."
                ),
            },
            "turns": [
                {
                    **_segmentation_turn_projection(by_id[unit.ref_id]),
                    "window_role": (
                        "primary_output" if unit.ref_id in primary_ids else "context_only"
                    ),
                }
                for unit in window.units
                if unit.ref_id in by_id
            ],
            "schema": SEGMENTATION_SCHEMA,
        }
        return {
            "prompt": _render_lossless_prompt(safe_prompt, payload),
            "schema_hint": SEGMENTATION_SCHEMA,
            "format_schema": SEGMENTATION_FORMAT_SCHEMA,
        }

    def _normalize(output: Any, window: PlannedWindow) -> Any:
        return normalize_window_segmentation(output, window, ordered_ids)

    def _validate(output: Any) -> bool:
        return isinstance(output, list) and bool(output)

    def _decorate(output: Any, primary: Sequence[PlanUnit]) -> dict[str, Any]:
        return {
            "schema_version": "e64i.conversation.segmentation.window.v1",
            "primary_refs": [unit.ref_id for unit in primary],
            "segments": output,
        }

    scope = StageScope(
        person_id=scope_person,
        package_date=scope_date,
        stage_name=SEGMENTATION_STAGE_NAME,
        adapter_version=CONVERSATION_ADAPTER_VERSION,
        prompt_version=SEGMENTATION_PROMPT_VERSION,
        model=model_name,
    )
    stage = run_windows(
        list(units),
        con=con,
        scope=scope,
        llm=window_llm,
        budget=model_budget,
        render=lambda window_units: {"prompt": ""},
        render_window=_render,
        validate=_validate,
        normalize_window_output=_normalize,
        decorate_output=_decorate,
        target_units=target_units,
        overlap=overlap,
        prompt_overhead_tokens=_segmentation_prompt_overhead(safe_prompt),
        subdivide_on_length=True,
    )
    if not stage.all_completed:
        raise ConversationEpisodeContractError(
            "segmentation_windows_incomplete:"
            f"quarantined={len(stage.quarantined)}:"
            f"states={sorted({w.state for w in stage.windows})}"
        )
    window_keys = {w.window_key for w in stage.windows}
    persisted = cp.load_outputs(
        con,
        person_id=scope_person,
        package_date=scope_date,
        stage_name=SEGMENTATION_STAGE_NAME,
        window_keys=window_keys,
    )
    # Reassemble by PROVENANCE, not by window_index: recursive subdivision remaps
    # child indices (parent*1000+i), which can collide across windows and is
    # therefore unsafe to sort on. Every emitted end lands on a primary turn and
    # primaries partition the order exactly once, so sorting the ends by their
    # global turn position yields the exact, unambiguous global order.
    position = {turn_id: index for index, turn_id in enumerate(ordered_ids)}
    end_records: list[dict[str, Any]] = []
    for row in persisted:
        envelope = row.get("output") if isinstance(row, dict) else None
        local = envelope.get("segments") if isinstance(envelope, dict) else None
        if isinstance(local, list):
            end_records.extend(local)
    end_records.sort(key=lambda record: position.get(str(record.get("end_turn_id")), -1))
    # Heal artificial thematic cuts at window edges BY PROVENANCE (never by text).
    # A single theme that spans two windows is closed twice: the window it started
    # in emits a forced edge (``window_boundary_forced``) at its last primary turn,
    # and the next window opens a continuation-marked first segment
    # (``window_first_continuation``). Dropping the forced edge record fuses the
    # two fragments into one contiguous segment for the next window's continuation;
    # ``normalize_segmentation`` then extends that segment back over both fragments.
    # A real semantic boundary at a window edge is NOT forced (or the next window's
    # head opens an explicitly new theme), so it is preserved untouched.
    healed_records = _fuse_forced_window_edges(end_records)
    # Rebuild the exact global membership from the ordered end boundaries.
    global_output = {
        "segments": [
            {
                "ordinal": ordinal,
                "title_hint": record["title_hint"],
                "end_turn_id": record["end_turn_id"],
                "boundary_reason": record["boundary_reason"],
            }
            for ordinal, record in enumerate(healed_records)
        ],
        "missing_context": [],
    }
    cognitive_view = [{"turn_id": turn_id} for turn_id in ordered_ids]
    segments = normalize_segmentation(global_output, cognitive_view)
    return segments, len(stage.windows)


def _segmentation_prompt_overhead(safe_prompt: Callable[[dict[str, Any]], str]) -> int:
    """Fixed prompt scaffolding cost for one empty segmentation window."""
    return estimate_tokens_for_text(
        safe_prompt({
            "mission": _SEGMENTATION_MISSION,
            "contract": {
                "human_turn_ids": [],
                "context_only_turn_ids": [],
                "membership_rule": "exactly_once_contiguous_ordered",
                "instruction": "",
            },
            "turns": [],
            "schema": SEGMENTATION_SCHEMA,
        })
    )


def _detail_units(
    segments: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[PlanUnit]:
    """One PlanUnit per LOCKED segment - a segment is never split across a batch."""
    units: list[PlanUnit] = []
    for segment in segments:
        turns = [by_id[turn_id] for turn_id in segment["turn_ids"]]
        payload = {**dict(segment), "turns": turns}
        tokens = estimate_tokens_for_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        ) + 32
        units.append(
            PlanUnit(
                ref_id=f"seg{int(segment['ordinal'])}",
                tokens=tokens,
                ts=str(int(segment["ordinal"])),
                content_digest=content_digest(payload),
            )
        )
    return units


def _run_detail_windows(
    con: Any,
    *,
    detail_units: Sequence[PlanUnit],
    segments: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    conversation: Mapping[str, Any],
    sensor_context: Sequence[Mapping[str, Any]],
    safe_prompt: Callable[[dict[str, Any]], str],
    window_llm: Any,
    model_budget: ModelBudget,
    scope_person: str,
    scope_date: str,
    model_name: str,
    output_budget: int,
) -> dict[str, Any]:
    """Windowed pass 2: detail LOCKED segments in bounded batches of whole segments.

    A batch = N entire segments whose combined tokens fit the budget; a segment is
    never cut in two. Each batch reuses the unchanged v6 detail prompt/schema over
    its own segments. Per-batch outputs are combined into the single parent by
    ordinal via ``combine_segment_details`` (no text merge).
    """
    seg_by_ref = {f"seg{int(seg['ordinal'])}": seg for seg in segments}

    def _batch_segments(window: PlannedWindow) -> list[Mapping[str, Any]]:
        return [seg_by_ref[unit.ref_id] for unit in window.primary_units if unit.ref_id in seg_by_ref]

    def _render(window: PlannedWindow) -> Mapping[str, Any]:
        batch = _batch_segments(window)
        payload = {
            "mission": _DETAIL_MISSION,
            "conversation": dict(conversation or {}),
            "segments": [
                {
                    **dict(segment),
                    "turns": [by_id[turn_id] for turn_id in segment["turn_ids"]],
                }
                for segment in batch
            ],
            "sensor_context": list(sensor_context),
            "schema": SUBTHEME_DETAIL_SCHEMA,
        }
        return {
            "prompt": _render_lossless_prompt(safe_prompt, payload),
            "schema_hint": SUBTHEME_DETAIL_SCHEMA,
            "format_schema": SUBTHEME_DETAIL_FORMAT_SCHEMA,
        }

    def _normalize(output: Any, window: PlannedWindow) -> Any:
        # Validate cardinality/ordinals against ONLY this batch's segments, but
        # keep each detail's ordinal so batches reassemble by provenance. The
        # authoritative membership attachment stays in the final
        # ``combine_segment_details`` over ALL locked segments. The per-batch
        # parent fields are carried through so the conversation-opening batch can
        # anchor the single parent (never a text merge across batches).
        if not isinstance(output, Mapping) or not isinstance(
            output.get("conversation_episode"), Mapping
        ):
            return None
        batch = _batch_segments(window)
        parent = output["conversation_episode"]
        details = parent.get("subthemes")
        if not isinstance(details, list) or len(details) != len(batch):
            return None
        expected_ordinals = {int(seg["ordinal"]) for seg in batch}
        seen: set[int] = set()
        kept: list[dict[str, Any]] = []
        for detail in details:
            if not isinstance(detail, Mapping):
                return None
            try:
                ordinal = int(detail.get("ordinal"))
            except (TypeError, ValueError):
                return None
            if ordinal not in expected_ordinals or ordinal in seen:
                return None
            seen.add(ordinal)
            kept.append(dict(detail))
        return {
            "min_ordinal": min(expected_ordinals),
            "parent": {
                key: parent.get(key)
                for key in ("title", "situation_summary", "participants", "location", "channel", "confidence")
            },
            "subthemes": kept,
            "missing_context": list(output.get("missing_context") or []),
        }

    def _validate(output: Any) -> bool:
        return (
            isinstance(output, Mapping)
            and isinstance(output.get("subthemes"), list)
            and bool(output["subthemes"])
        )

    def _decorate(output: Any, primary: Sequence[PlanUnit]) -> dict[str, Any]:
        return {
            "schema_version": "e64i.conversation.detail.window.v1",
            "primary_refs": [unit.ref_id for unit in primary],
            **output,
        }

    scope = StageScope(
        person_id=scope_person,
        package_date=scope_date,
        stage_name=DETAIL_STAGE_NAME,
        adapter_version=CONVERSATION_ADAPTER_VERSION,
        prompt_version=DETAIL_PROMPT_VERSION,
        model=model_name,
    )
    stage = run_windows(
        list(detail_units),
        con=con,
        scope=scope,
        llm=window_llm,
        budget=model_budget,
        render=lambda window_units: {"prompt": ""},
        render_window=_render,
        validate=_validate,
        normalize_window_output=_normalize,
        decorate_output=_decorate,
        # One segment per unit; batches close on the token budget, never a fixed
        # count, and a single oversized segment gets its own (possibly quarantined)
        # window rather than being split.
        target_units=max(1, len(detail_units)),
        overlap=0,
        prompt_overhead_tokens=_detail_prompt_overhead(safe_prompt, conversation),
        subdivide_on_length=True,
    )
    if not stage.all_completed:
        raise ConversationEpisodeContractError(
            "detail_windows_incomplete:"
            f"quarantined={len(stage.quarantined)}:"
            f"states={sorted({w.state for w in stage.windows})}"
        )
    window_keys = {w.window_key for w in stage.windows}
    persisted = cp.load_outputs(
        con,
        person_id=scope_person,
        package_date=scope_date,
        stage_name=DETAIL_STAGE_NAME,
        window_keys=window_keys,
    )
    subthemes_by_ordinal: dict[int, Mapping[str, Any]] = {}
    anchor_parent: dict[str, Any] | None = None
    anchor_min = None
    participants_union: list[str] = []
    missing_union: list[Any] = []
    for row in persisted:
        envelope = row.get("output") if isinstance(row, dict) else None
        if not isinstance(envelope, dict):
            continue
        batch_subthemes = envelope.get("subthemes")
        if isinstance(batch_subthemes, list):
            for detail in batch_subthemes:
                if isinstance(detail, Mapping) and "ordinal" in detail:
                    subthemes_by_ordinal[int(detail["ordinal"])] = detail
        parent = envelope.get("parent")
        if isinstance(parent, Mapping):
            participants_union.extend(_unique_strings(parent.get("participants")))
            # Anchor the single parent on the batch that opens the conversation
            # (lowest ordinal, i.e. contains segment 0), by provenance not text.
            batch_min = envelope.get("min_ordinal")
            if isinstance(batch_min, int) and (anchor_min is None or batch_min < anchor_min):
                anchor_min = batch_min
                anchor_parent = dict(parent)
        missing_union.extend(list(envelope.get("missing_context") or []))
    ordered_details = [
        subthemes_by_ordinal[int(segment["ordinal"])]
        for segment in segments
        if int(segment["ordinal"]) in subthemes_by_ordinal
    ]
    parent_fields = anchor_parent or {}
    detail_output = {
        "conversation_episode": {
            "title": parent_fields.get("title") or "",
            "situation_summary": parent_fields.get("situation_summary") or "",
            "participants": list(dict.fromkeys(participants_union)),
            "location": parent_fields.get("location"),
            "channel": parent_fields.get("channel"),
            "confidence": parent_fields.get("confidence", 0.0),
            "subthemes": ordered_details,
        },
        "missing_context": list(dict.fromkeys([str(m) for m in missing_union if m is not None])),
    }
    return combine_segment_details(detail_output, segments)


def _detail_prompt_overhead(
    safe_prompt: Callable[[dict[str, Any]], str],
    conversation: Mapping[str, Any],
) -> int:
    """Fixed prompt scaffolding cost for one empty detail batch."""
    return estimate_tokens_for_text(
        safe_prompt({
            "mission": _DETAIL_MISSION,
            "conversation": dict(conversation or {}),
            "segments": [],
            "sensor_context": [],
            "schema": SUBTHEME_DETAIL_SCHEMA,
        })
    )


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
    person_id: str | None = None,
    package_date: str | None = None,
) -> dict[str, Any]:
    """Execute boundary detection then semantic detail as bounded calls.

    When the complete compacted projection fits the input budget the historic
    two-call path is used UNCHANGED (identical prompts and schemas). When either
    pass would exceed the model context, the E64 orchestrator windows that pass
    over token-aware windows of the ORDERED turns/segments: boundaries are emitted
    per primary window and reassembled into one gap-free partition BY CODE, and
    locked segments are detailed in bounded batches of whole segments. Every
    window is checkpointed via ``run_windows`` so a resume repays none of them.
    There is no silent v5 fallback: any failure is an explicit, retryable error.
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

    injected_llm = window_llm
    timeout = None
    if injected_llm is None:
        try:
            timeout = float(os.environ.get("MLOMEGA_V13_ENGINE_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
    # Owner/day scope the durable checkpoint rows. Windows never repay on resume.
    # Windowing is only attempted when the production caller supplies an owner and
    # a package date: those are the checkpoint scope the durable resume needs. A
    # caller that omits them keeps the historic fail-closed contract (an oversized
    # conversation raises ``input_budget_exceeded`` before any inference) instead
    # of silently degrading to an un-resumable run.
    can_window = person_id is not None and package_date is not None
    scope_person = str(person_id or "unknown_owner")
    scope_date = str(package_date or conversation_id)
    model_name = str(getattr(injected_llm, "model", None) or "ollama-json")
    model_budget = ModelBudget(
        context_window=int(input_budget) + int(output_budget) + 768,
        output_reserve=int(output_budget),
        safety_margin=768,
    )
    by_id = {str(turn.get("turn_id")): turn for turn in projected_turns}
    ordered_ids = [str(turn.get("turn_id")) for turn in projected_turns]

    started = time.perf_counter()
    windowed_segmentation = 0
    windowed_detail = 0

    # ---- Pass 1: segmentation (single call if it fits, else windowed) ----
    if segmentation_tokens <= int(input_budget):
        if injected_llm is None:
            segmentation_llm = OllamaWindowLLM(
                system=system,
                schema_hint=SEGMENTATION_SCHEMA,
                format_schema=SEGMENTATION_FORMAT_SCHEMA,
                timeout=timeout,
            )
        else:
            segmentation_llm = injected_llm
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
        segmentation_calls = 1
    elif not can_window:
        raise ConversationEpisodeContractError(
            f"input_budget_exceeded:{segmentation_tokens}>{int(input_budget)}"
        )
    else:
        seg_llm = injected_llm or OllamaWindowLLM(
            system=system,
            schema_hint=SEGMENTATION_SCHEMA,
            format_schema=SEGMENTATION_FORMAT_SCHEMA,
            timeout=timeout,
        )
        segments, windowed_segmentation = _run_segmentation_windows(
            con,
            units=_segmentation_units(projected_turns),
            projected_turns=projected_turns,
            ordered_ids=ordered_ids,
            safe_prompt=safe_prompt,
            window_llm=seg_llm,
            model_budget=model_budget,
            scope_person=scope_person,
            scope_date=scope_date,
            model_name=model_name,
            overlap=_conversation_overlap(),
            target_units=_conversation_target_turns(),
        )
        segmentation_calls = windowed_segmentation

    # ---- Pass 2: detail (single call if it fits, else batched) ----
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
    if detail_tokens <= int(input_budget):
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
        if not getattr(detail_result, "ok", False):
            raise ConversationEpisodeContractError(
                "detail_llm_failed:"
                f"{getattr(detail_result, 'error_kind', None)}:"
                f"{getattr(detail_result, 'finish_reason', None)}"
            )
        combined = combine_segment_details(detail_result.data, segments)
        detail_calls = 1
    elif not can_window:
        raise ConversationEpisodeContractError(
            f"input_budget_exceeded:{detail_tokens}>{int(input_budget)}"
        )
    else:
        detail_llm = injected_llm or OllamaWindowLLM(
            system=system,
            schema_hint=SUBTHEME_DETAIL_SCHEMA,
            format_schema=SUBTHEME_DETAIL_FORMAT_SCHEMA,
            timeout=timeout,
        )
        combined = _run_detail_windows(
            con,
            detail_units=_detail_units(segments, by_id),
            segments=segments,
            by_id=by_id,
            conversation=dict(bundle.get("conversation") or {}),
            sensor_context=sensor_context,
            safe_prompt=safe_prompt,
            window_llm=detail_llm,
            model_budget=model_budget,
            scope_person=scope_person,
            scope_date=scope_date,
            model_name=model_name,
            output_budget=int(output_budget),
        )
        # Batch count is not re-derivable without the planner; report the number
        # of durable detail windows for the current run's checkpoint scope.
        windowed_detail = len(_detail_units(segments, by_id))
        detail_calls = windowed_detail

    elapsed = time.perf_counter() - started
    normalized = normalize_conversation_episode(combined, cognitive_turns)
    normalized["missing_context"] = list(dict.fromkeys([
        *normalized.get("missing_context", []),
        *_source_quality_gaps(cognitive_turns),
    ]))
    count = materialize(con, conversation_id, normalized)
    return {
        "episodes": count,
        "subthemes": len(normalized["episodes"][0]["subthemes"]),
        "calls": segmentation_calls + detail_calls,
        "segmentation_calls": segmentation_calls,
        "detail_calls": detail_calls,
        "windowed_segmentation": windowed_segmentation,
        "windowed_detail": windowed_detail,
        "input_tokens": segmentation_tokens + detail_tokens,
        "segmentation_input_tokens": segmentation_tokens,
        "detail_input_tokens": detail_tokens,
        "elapsed_seconds": round(elapsed, 4),
        "output": normalized,
    }
