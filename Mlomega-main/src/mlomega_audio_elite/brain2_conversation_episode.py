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
from datetime import datetime, timezone
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
    WindowSpec,
    estimate_tokens_for_text,
    run_windows,
    subdivide,
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
CONVERSATION_ADAPTER_VERSION = "e64i-conversation-window-v4"
SEGMENTATION_PROMPT_VERSION = "v6-segmentation-boundaries-unchanged-v1"
DETAIL_PROMPT_VERSION = "v6-detail-locked-segments-unchanged-v4"


class ConversationEpisodeContractError(RuntimeError):
    """The model output cannot be made lossless without inventing semantics."""


def conversation_episode_enabled() -> bool:
    """Use the lossless conversation parent by default; ``=0`` is rollback."""
    return os.environ.get("MLOMEGA_E64_CONVERSATION_EPISODES", "1") != "0"


def _pro_closeday_enabled() -> bool:
    """PRO close-day mode forces the lossless windowed segmentation executor.

    The single-call segmentation path is not lossless by construction: it needs
    the model to emit an ``end`` boundary on the LAST turn, and the 9B used on the
    PRO close-day sometimes stops before the tail fillers, so ``next_start`` never
    reaches ``len(ordered_ids)`` and the run trips ``segmentation_not_lossless``.
    The windowed path forces the final segment onto the window's last primary turn
    (lossless by construction), so PRO routes through it even when the whole input
    would fit one call.

    This is an EXPLICIT close-day flag, deliberately independent of
    ``MLOMEGA_LLM_BACKEND``: the EpisodeBuilder runs in local llamacpp even in PRO,
    so the backend name would misclassify the run. Absent the flag the historic
    single-call path stays byte-for-byte unchanged.
    """
    value = os.environ.get("MLOMEGA_PRO_CLOSEDAY", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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


def split_segments_on_silence(
    segments: Sequence[Mapping[str, Any]],
    turns_by_id: Mapping[str, Mapping[str, Any]],
    *,
    threshold_s: float | None = None,
) -> list[dict[str, Any]]:
    """Refine semantic segments at proven long acquisition gaps.

    A model cannot honestly summarize two interactions separated by tens of
    seconds as one continuous subtheme merely because the recorder kept the
    same conversation row open.  This refinement is lossless and semantic-free:
    it uses only adjacent source timestamps and preserves every turn once.
    """
    if threshold_s is None:
        try:
            threshold_s = float(
                os.environ.get("MLOMEGA_CONVERSATION_SILENCE_SPLIT_S", "15")
            )
        except ValueError:
            threshold_s = 15.0
    threshold_s = max(5.0, float(threshold_s))

    refined: list[dict[str, Any]] = []
    for source in segments:
        source_ids = [str(item) for item in source.get("turn_ids") or []]
        if not source_ids:
            continue
        groups: list[list[str]] = [[source_ids[0]]]
        gaps: list[float] = [0.0]
        for turn_id in source_ids[1:]:
            previous = turns_by_id.get(groups[-1][-1], {})
            current = turns_by_id.get(turn_id, {})
            try:
                gap = float(current.get("start_s")) - float(previous.get("end_s"))
            except (TypeError, ValueError):
                gap = 0.0
            if gap >= threshold_s:
                groups.append([turn_id])
                gaps.append(gap)
            else:
                groups[-1].append(turn_id)

        for part_index, group in enumerate(groups):
            title = str(source.get("title_hint") or "Conversation")
            reason = str(source.get("boundary_reason") or "conversation_start")
            if part_index:
                title = f"Reprise après silence ({gaps[part_index]:.1f} s)"
                reason = "temporal_gap"
            refined.append({
                "ordinal": len(refined),
                "title_hint": title,
                "boundary_reason": reason,
                "start_turn_id": group[0],
                "end_turn_id": group[-1],
                "turn_ids": group,
                "source_ordinal": int(source.get("ordinal", len(refined))),
                "temporal_gap_s": gaps[part_index] if part_index else None,
            })
    return refined


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


def normalize_detail_window_output(
    output: Any,
    segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Bind a detail batch to its immutable planned segments.

    Small models commonly number a one-segment response from zero even when the
    locked source segment has a global ordinal greater than zero.  The window
    planner is the authority for membership, so a one-item response is safely
    rebound to that one planned ordinal.  A detail pass may also discover that
    one coarse segment contains several real subjects.  We accept that split
    only when its cited evidence is an exact, contiguous and ordered partition
    of every source turn; otherwise no membership is guessed.  Multi-segment
    batches remain strict because remapping several results could swap topics.
    """
    if not isinstance(output, Mapping) or not isinstance(
        output.get("conversation_episode"), Mapping
    ):
        return None
    batch = list(segments)
    if not batch:
        return None
    parent = output["conversation_episode"]
    details = parent.get("subthemes")
    if not isinstance(details, list) or not details:
        return None

    expected_ordinals = [int(segment["ordinal"]) for segment in batch]
    kept: list[dict[str, Any]] = []
    seen: set[int] = set()
    if len(batch) == 1 and len(details) > 1:
        source_segment = batch[0]
        source_turn_ids = [str(item) for item in source_segment.get("turn_ids") or []]
        source_turn_set = set(source_turn_ids)
        cited_partition: list[str] = []
        for detail in details:
            if not isinstance(detail, Mapping):
                return None
            # ``sensor_context`` entries carry durable addendum IDs, but the
            # public field is deliberately named ``evidence_turn_ids`` and the
            # final episode contract requires it to be a subset of membership.
            # Some capable VLM-backed models cite both kinds.  Keep every valid
            # speech citation, leave sensor provenance in its dedicated tables,
            # and still fail closed when no speech evidence remains.
            evidence = [
                item for item in _unique_strings(detail.get("evidence_turn_ids"))
                if item in source_turn_set
            ]
            if not evidence:
                return None
            cited_partition.extend(evidence)
        # This is proof, not a heuristic: every source turn is cited exactly
        # once, in source order.  Filler/gap assignment is deliberately refused.
        if cited_partition != source_turn_ids:
            return None
    elif len(details) != len(batch):
        return None

    for index, detail in enumerate(details):
        if not isinstance(detail, Mapping):
            return None
        normalized = dict(detail)
        if len(batch) == 1:
            source_segment = batch[0]
            ordinal = expected_ordinals[0]
            source_turn_ids = [
                str(item) for item in source_segment.get("turn_ids") or []
            ]
            evidence = [
                item for item in _unique_strings(detail.get("evidence_turn_ids"))
                if item in set(source_turn_ids)
            ]
            if not evidence:
                return None
            # A sub-segment produced by the deterministic contract-rejection split
            # carries its parent's ``_source_ordinal`` and a ``_part_base`` so the
            # halves of ONE locked segment reassemble in order (part_index unique
            # across the whole segment), never colliding at part_index 0.
            split_source = source_segment.get("_source_ordinal")
            part_base = source_segment.get("_part_base")
            normalized["ordinal"] = ordinal
            normalized["source_ordinal"] = (
                int(split_source) if split_source is not None else ordinal
            )
            normalized["part_index"] = (
                int(part_base) + index if part_base is not None else index
            )
            normalized["turn_ids"] = (
                evidence
                if len(details) > 1
                else source_turn_ids
            )
            normalized["evidence_turn_ids"] = evidence
            normalized["boundary_reason"] = (
                str(source_segment.get("boundary_reason") or "")
                if index == 0
                else "semantic_split_complete_evidence"
            )
        else:
            try:
                ordinal = int(detail.get("ordinal"))
            except (TypeError, ValueError):
                return None
            if ordinal not in expected_ordinals or ordinal in seen:
                return None
            source_segment = next(
                segment for segment in batch if int(segment["ordinal"]) == ordinal
            )
            source_turn_ids = [
                str(item) for item in source_segment.get("turn_ids") or []
            ]
            evidence = [
                item for item in _unique_strings(detail.get("evidence_turn_ids"))
                if item in set(source_turn_ids)
            ]
            if not evidence:
                return None
            normalized["source_ordinal"] = ordinal
            normalized["part_index"] = 0
            normalized["turn_ids"] = source_turn_ids
            normalized["evidence_turn_ids"] = evidence
            normalized["boundary_reason"] = str(
                source_segment.get("boundary_reason") or ""
            )
        seen.add(ordinal)
        kept.append(normalized)

    return {
        "min_ordinal": min(expected_ordinals),
        "parent": {
            key: parent.get(key)
            for key in (
                "title", "situation_summary", "participants", "location",
                "channel", "confidence",
            )
        },
        "subthemes": kept,
        "missing_context": list(output.get("missing_context") or []),
    }


def assemble_detail_window_outputs(
    persisted: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reassemble validated detail parts and prove full source-turn coverage."""
    parts: list[dict[str, Any]] = []
    parents: list[tuple[int, dict[str, Any]]] = []
    participants: list[str] = []
    missing: list[str] = []
    for row in persisted:
        envelope = row.get("output") if isinstance(row, Mapping) else None
        if not isinstance(envelope, Mapping):
            continue
        batch_min = envelope.get("min_ordinal")
        try:
            min_ordinal = int(batch_min)
        except (TypeError, ValueError):
            min_ordinal = 10**9
        parent = envelope.get("parent")
        if isinstance(parent, Mapping):
            parents.append((min_ordinal, dict(parent)))
            participants.extend(_unique_strings(parent.get("participants")))
        for raw in envelope.get("subthemes") or []:
            if not isinstance(raw, Mapping):
                continue
            detail = dict(raw)
            try:
                source_ordinal = int(
                    detail.get("source_ordinal", detail.get("ordinal"))
                )
                part_index = int(detail.get("part_index", 0))
            except (TypeError, ValueError):
                raise ConversationEpisodeContractError("detail_provenance_invalid")
            detail["source_ordinal"] = source_ordinal
            detail["part_index"] = part_index
            parts.append(detail)
        missing.extend(
            str(item) for item in envelope.get("missing_context") or []
            if item is not None
        )

    expected_turn_ids = [
        str(turn_id)
        for segment in segments
        for turn_id in segment.get("turn_ids") or []
    ]
    # Order parts by the GLOBAL position of their first source turn. This is
    # depth-safe: a segment split across multiple recursive levels produces parts
    # whose ``part_index`` arithmetic can collide, but each part's first turn has a
    # unique, totally-ordered global position. ``source_ordinal``/``part_index``
    # stay as a stable tiebreak for legacy one-level parts and empty-turn parts.
    _turn_pos = {turn_id: index for index, turn_id in enumerate(expected_turn_ids)}

    def _part_sort_key(item: Mapping[str, Any]) -> tuple[int, int, int]:
        turn_ids = [str(t) for t in item.get("turn_ids") or []]
        positions = [_turn_pos[t] for t in turn_ids if t in _turn_pos]
        first = min(positions) if positions else 10**9
        return (first, int(item["source_ordinal"]), int(item["part_index"]))

    parts.sort(key=_part_sort_key)
    actual_turn_ids = [
        str(turn_id)
        for detail in parts
        for turn_id in detail.get("turn_ids") or []
    ]
    if actual_turn_ids != expected_turn_ids:
        raise ConversationEpisodeContractError(
            "detail_window_membership_not_lossless"
        )
    if not parts:
        raise ConversationEpisodeContractError("detail_window_outputs_missing")

    for ordinal, detail in enumerate(parts):
        turn_ids = [str(item) for item in detail.get("turn_ids") or []]
        turn_set = set(turn_ids)
        speech_evidence = [
            item for item in _unique_strings(detail.get("evidence_turn_ids"))
            if item in turn_set
        ]
        if not speech_evidence:
            raise ConversationEpisodeContractError(
                f"detail_part_{ordinal}_missing_speech_evidence"
            )
        # Apply the same evidence type boundary while resuming older completed
        # window checkpoints.  This is what makes a fixed contract resumable
        # without paying the model again merely to remove a sensor addendum ID.
        detail["evidence_turn_ids"] = speech_evidence
        detail["ordinal"] = ordinal
        detail.pop("source_ordinal", None)
        detail.pop("part_index", None)
        participants.extend(_unique_strings(detail.get("participants")))

    parents.sort(key=lambda item: item[0])
    anchor = parents[0][1] if parents else {}
    titles = [str(item.get("title") or "").strip() for item in parts]
    summaries = [str(item.get("summary") or "").strip() for item in parts]
    title = " / ".join(item for item in titles if item)[:120]
    situation_summary = " ".join(item for item in summaries if item)
    confidence_values = [_confidence(item.get("confidence")) for item in parts]
    confidence = min(confidence_values) if confidence_values else 0.0
    return {
        "conversation_episode": {
            "title": title or str(anchor.get("title") or "Conversation"),
            "situation_summary": situation_summary or str(
                anchor.get("situation_summary") or ""
            ),
            "participants": list(dict.fromkeys(participants)),
            "location": next(
                (parent.get("location") for _, parent in parents if parent.get("location")),
                None,
            ),
            "channel": next(
                (parent.get("channel") for _, parent in parents if parent.get("channel")),
                None,
            ),
            "confidence": confidence,
            "subthemes": parts,
        },
        "missing_context": list(dict.fromkeys(missing)),
        "confidence": confidence,
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


def _sensor_kind(turn: Mapping[str, Any]) -> str:
    metadata = turn.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    return str(metadata.get("kind") or "") if isinstance(metadata, Mapping) else ""


def _preferred_sensor_context(
    sensor_context: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Use Deep Vision for visual semantics once it exists, without data loss.

    Raw VisionRT change atoms remain durable inputs to selection, Silent Life and
    the independent coverage manifest. Recopying all of them beside the richer
    VLM descriptions in every conversation-detail prompt added no information and
    hid the actual Deep Vision output. Non-visual sensor evidence is always kept.
    """

    deep = [turn for turn in sensor_context if _sensor_kind(turn) == "deep_vision_context"]
    if not deep:
        return list(sensor_context)
    return [
        turn
        for turn in sensor_context
        if _sensor_kind(turn) != "vision_context"
    ]


def _context_addenda_as_sensor(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project V18 context addenda into the explicit sensor lane, never dialogue."""

    envelope = bundle.get("context_addenda")
    entries = envelope.get("entries") if isinstance(envelope, Mapping) else None
    if not isinstance(entries, list):
        return []
    conversation = bundle.get("conversation")
    started_raw = conversation.get("started_at") if isinstance(conversation, Mapping) else None

    def parse(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    started = parse(started_raw)
    projected: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or not entry.get("text"):
            continue
        event_time = parse(entry.get("event_time"))
        relative_s = (
            max(0.0, (event_time - started).total_seconds())
            if event_time is not None and started is not None else None
        )
        source_table = str(entry.get("source_table") or "")
        kind = (
            "deep_vision_context"
            if source_table == "brainlive_deep_vision_observations_v161"
            else "context_addendum"
        )
        projected.append({
            "turn_id": str(entry.get("addendum_id") or f"context-addendum-{index}"),
            "idx": None,
            "speaker_label": "system_context",
            "person_id": None,
            "start_s": relative_s,
            "end_s": relative_s,
            "text": str(entry.get("text")),
            "metadata_json": json.dumps({
                "kind": kind,
                "evidence_role": "system_observation_not_user_speech",
                "time": entry.get("event_time"),
                "source_table": source_table,
                "source_id": entry.get("source_id"),
                "addendum_id": entry.get("addendum_id"),
                "scope": entry.get("scope"),
            }, ensure_ascii=False, sort_keys=True),
        })
    return projected


def _sensor_context_for_segments(
    sensor_context: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Route system evidence only to conversation segments it temporally touches."""

    try:
        margin = max(0.0, float(os.environ.get("MLOMEGA_E64_SENSOR_CONTEXT_MARGIN_S", "5")))
    except (TypeError, ValueError):
        margin = 5.0
    ranges: list[tuple[float, float]] = []
    for segment in segments:
        starts: list[float] = []
        ends: list[float] = []
        for turn_id in segment.get("turn_ids") or []:
            turn = by_id.get(str(turn_id)) or {}
            try:
                start = float(turn.get("start_s"))
                end = float(turn.get("end_s") if turn.get("end_s") is not None else start)
            except (TypeError, ValueError):
                continue
            starts.append(start)
            ends.append(max(start, end))
        if starts:
            ranges.append((min(starts) - margin, max(ends) + margin))
    if not ranges:
        return list(sensor_context)

    routed: list[Mapping[str, Any]] = []
    for sensor in sensor_context:
        try:
            start = float(sensor.get("start_s"))
            end = float(sensor.get("end_s") if sensor.get("end_s") is not None else start)
        except (TypeError, ValueError):
            # Evidence without a temporal coordinate cannot be safely assigned to
            # one subtheme, so keep it visible rather than silently discarding it.
            routed.append(sensor)
            continue
        end = max(start, end)
        if any(start <= upper and end >= lower for lower, upper in ranges):
            routed.append(sensor)
    return routed


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

    def _describe_violation(candidate: Any, window: PlannedWindow) -> Mapping[str, Any]:
        """Explain WHY ``normalize_window_segmentation`` rejected this window's output.

        The night executor persists this beside the raw output so the audit shows
        which segmentation contract failed on which window's primary turns. A None
        candidate means the local boundary partition could not be reconstructed
        (root missing/invalid, an end off the window's primary turns, a
        non-advancing end, or missing title/reason) - the same signal that the
        window must be split rather than re-asked identically."""
        primary_refs = [unit.ref_id for unit in window.primary_units]
        if candidate is None:
            return {
                "rule": "segmentation_window_normalized_none",
                "reason": "normalize_window_segmentation returned None",
                "primary_refs": primary_refs,
            }
        return {
            "rule": "segmentation_window_contract_rejected",
            "primary_refs": primary_refs,
        }

    def _resolve_rejection(window: PlannedWindow, ctx: Mapping[str, Any]) -> bool:
        """Deterministic escalation: split ONE segmentation window's primary turns
        into two contiguous halves, re-run each through this same executor, and let
        the executor + global reassembly re-verify lossless coverage.

        No temperature/seed change and no invented boundary: this reuses the
        planner's own ``subdivide`` (``window_index*1000+i+1`` child indices,
        primary turns halved contiguously, no overlap), so each child window emits
        boundaries only for its own primary turns and
        ``normalize_window_segmentation`` forces each child's last segment onto that
        child's last primary turn. The children therefore abut with neither gap nor
        duplicate, and the stage-scoped provenance reassembly rebuilds the exact
        global membership. A single-turn window cannot be split and is left to
        quarantine (fail-closed)."""
        subs = subdivide(window, stage_name=SEGMENTATION_STAGE_NAME)
        if not subs:
            return False  # irreducible: one turn cannot be halved
        drive = ctx["drive"]
        result = ctx["result"]
        # Snapshot BEFORE driving so a multi-level split is judged by its true
        # leaves (a child that itself subdivided is not a leaf; its deeper children
        # are). The final ``stage.all_completed`` stays the authoritative gate.
        pre_leaf_count = len(result.windows)
        for sub in subs:
            drive(sub)
        # Coverage is proven downstream by the global provenance reassembly; success
        # here = every LEAF produced under this split (at any depth) reached a
        # durable COMPLETED state. A quarantine anywhere in the subtree fails closed.
        descendants = result.windows[pre_leaf_count:]
        return bool(descendants) and all(
            w.state == cp.STATE_COMPLETED for w in descendants
        )

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
        describe_contract_violation=_describe_violation,
        resolve_contract_rejection=_resolve_rejection,
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
    sensor_context: Sequence[Mapping[str, Any]] = (),
) -> list[PlanUnit]:
    """One PlanUnit per LOCKED segment - a segment is never split across a batch."""
    units: list[PlanUnit] = []
    for segment in segments:
        turns = [by_id[turn_id] for turn_id in segment["turn_ids"]]
        payload = {
            **dict(segment),
            "turns": turns,
            "sensor_context": _sensor_context_for_segments(
                sensor_context, [segment], by_id
            ),
        }
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
                    **{k: v for k, v in segment.items() if not k.startswith("_")},
                    "turns": [by_id[turn_id] for turn_id in segment["turn_ids"]],
                }
                for segment in batch
            ],
            "sensor_context": _sensor_context_for_segments(
                sensor_context, batch, by_id
            ),
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
        batch = _batch_segments(window)
        return normalize_detail_window_output(output, batch)

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

    def _describe_violation(candidate: Any, window: PlannedWindow) -> Mapping[str, Any]:
        """Explain WHY normalize_detail_window_output rejected this batch's output.

        The night executor persists this beside the raw output so the audit shows
        the exact contract that failed (coverage / cardinality / evidence), which
        is also the signal that a segment must be split rather than re-asked."""
        batch = _batch_segments(window)
        if not isinstance(candidate, Mapping):
            episode = candidate if isinstance(candidate, Mapping) else None
            return {
                "rule": "detail_normalized_output_none",
                "reason": "normalize_detail_window_output returned None",
                "batch_ordinals": [int(s["ordinal"]) for s in batch],
            }
        return {
            "rule": "detail_contract_rejected",
            "batch_ordinals": [int(s["ordinal"]) for s in batch],
        }

    def _resolve_rejection(window: PlannedWindow, ctx: Mapping[str, Any]) -> bool:
        """Deterministic escalation: split ONE locked detail segment into two
        contiguous halves, detail each, and let the executor + assembly re-verify
        lossless coverage.  No temperature/seed change, no invented evidence: the
        two halves partition the segment's turn_ids exactly once, so the final
        ``assemble_detail_window_outputs`` still proves full source-turn coverage.
        A segment with a single turn cannot be split and is left to quarantine."""
        batch = _batch_segments(window)
        if len(batch) != 1:
            return False  # only mono-segment detail windows are split here
        segment = batch[0]
        turn_ids = [str(t) for t in segment.get("turn_ids") or []]
        if len(turn_ids) < 2:
            return False  # irreducible: one turn cannot be halved
        source_ordinal = int(segment.get("_source_ordinal", segment["ordinal"]))
        part_base = int(segment.get("_part_base", 0))
        mid = len(turn_ids) // 2
        halves = [turn_ids[:mid], turn_ids[mid:]]
        drive = ctx["drive"]
        base_index = int(window.spec.window_index)
        # Snapshot the leaves BEFORE driving so a multi-level split is judged by its
        # actual leaves (a half that itself had to subdivide is NOT a leaf; its own
        # deeper children are). Counting only direct COMPLETED children wrongly
        # quarantined a parent whose half needed a further split (Gate B 014448:
        # a ~41-turn coarse segment needs two split levels).
        result = ctx["result"]
        pre_leaf_count = len(result.windows)
        for half_index, half_turns in enumerate(halves):
            child_ref = f"{segment.get('_ref', 'seg' + str(segment['ordinal']))}#h{part_base + half_index}"
            child_segment = {
                **{k: v for k, v in segment.items()
                   if k not in ("turn_ids", "_ref", "_source_ordinal", "_part_base")},
                "ordinal": int(segment["ordinal"]),
                "turn_ids": half_turns,
                "start_turn_id": half_turns[0],
                "end_turn_id": half_turns[-1],
                "_ref": child_ref,
                "_source_ordinal": source_ordinal,
                "_part_base": part_base + half_index,
            }
            seg_by_ref[child_ref] = child_segment
            child_payload = {
                **{k: v for k, v in child_segment.items() if not k.startswith("_")},
                "turns": [by_id[t] for t in half_turns],
                "sensor_context": _sensor_context_for_segments(
                    sensor_context, [child_segment], by_id
                ),
            }
            child_tokens = estimate_tokens_for_text(
                json.dumps(child_payload, ensure_ascii=False, sort_keys=True, default=str)
            ) + 32
            child_unit = PlanUnit(
                ref_id=child_ref,
                tokens=child_tokens,
                ts=f"{source_ordinal}.{part_base + half_index}",
                content_digest=content_digest(child_payload),
            )
            child_spec = WindowSpec(
                stage_name=DETAIL_STAGE_NAME,
                # A stable, collision-free child index derived from the parent's.
                window_index=base_index * 1000 + part_base + half_index + 1,
                primary_refs=(child_ref,),
                overlap_refs=(),
                input_digest=content_digest([
                    {"ref_id": child_ref, "content_digest": child_unit.content_digest}
                ]),
            )
            child_window = PlannedWindow(
                spec=child_spec,
                primary_units=(child_unit,),
                overlap_units=(),
                input_tokens=child_tokens,
            )
            drive(child_window)
        # Coverage proof is enforced downstream by assemble_detail_window_outputs.
        # Success here = every LEAF produced under this split (at any depth) reached
        # a durable COMPLETED state; a quarantine anywhere in the subtree fails
        # closed. The final ``stage.all_completed`` remains the authoritative gate.
        descendants = result.windows[pre_leaf_count:]
        return bool(descendants) and all(
            w.state == cp.STATE_COMPLETED for w in descendants
        )

    scope = StageScope(
        person_id=scope_person,
        package_date=scope_date,
        stage_name=DETAIL_STAGE_NAME,
        adapter_version=CONVERSATION_ADAPTER_VERSION,
        prompt_version=DETAIL_PROMPT_VERSION,
        model=model_name,
    )
    parallel_workers = 1
    connection_factory = None
    if _pro_closeday_enabled() and len(detail_units) > 1:
        try:
            parallel_workers = max(
                1, min(6, int(os.environ.get("MLOMEGA_PRO_EPISODE_DETAIL_WORKERS", "3")))
            )
        except ValueError:
            parallel_workers = 3
        if parallel_workers > 1:
            # Reopen the EXACT database owned by the caller.  Tests and tools may
            # pass an in-memory/custom connection that is not ``settings.db_path``;
            # silently opening another DB would lose the checkpoint schema.  An
            # in-memory DB cannot be shared safely, so it keeps the sequential path.
            db_row = con.execute("PRAGMA database_list").fetchone()
            db_file = (
                db_row["file"]
                if db_row is not None and hasattr(db_row, "keys") and "file" in db_row.keys()
                else (db_row[2] if db_row is not None else "")
            )
            if db_file:
                from pathlib import Path
                from .db import connect as _connect

                db_path = Path(str(db_file))
                connection_factory = lambda: _connect(db_path)
            else:
                parallel_workers = 1
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
        describe_contract_violation=_describe_violation,
        resolve_contract_rejection=_resolve_rejection,
        # Exactly one locked segment per detail call.  Small JSON models reset
        # ordinals inside a local response; mixing seg6+seg7 in one batch made
        # that harmless local numbering ambiguous.  A mono-segment window is
        # rebound by immutable planner provenance and still fails closed on any
        # incomplete evidence split.
        target_units=1,
        overlap=0,
        prompt_overhead_tokens=_detail_prompt_overhead(safe_prompt, conversation),
        subdivide_on_length=True,
        parallel_workers=parallel_workers,
        connection_factory=connection_factory,
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
    return assemble_detail_window_outputs(persisted, segments)


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
    sensor_context = _preferred_sensor_context([
        *[_prompt_turn(turn) for turn in sensor_turns],
        *_context_addenda_as_sensor(bundle),
    ])
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
    # PRO close-day forces the windowed executor even when the whole input fits a
    # single call, because only the windowed path is lossless by construction (it
    # forces the last segment onto the window's last primary turn). The single-call
    # path is kept EXACTLY unchanged when PRO is absent. When PRO is set but the
    # caller gave no owner/day (``not can_window``) there is no durable checkpoint
    # scope to window against, so the historic fail-closed contract is preserved:
    # single-call if it fits, ``input_budget_exceeded`` otherwise.
    force_windowed_segmentation = _pro_closeday_enabled() and can_window
    route_windowed = force_windowed_segmentation or segmentation_tokens > int(input_budget)
    if not route_windowed:
        # segmentation_tokens <= input_budget here (route_windowed is False), so the
        # historic single-call path runs byte-for-byte identically to before.
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

    # The semantic pass may leave several physically separate interactions in
    # one coarse tail segment.  Refine only on an objective long silence before
    # asking the detail model; membership stays exact and source-ordered.
    segments = split_segments_on_silence(segments, by_id)

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
        "sensor_context": _sensor_context_for_segments(
            sensor_context, segments, by_id
        ),
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
            detail_units=_detail_units(segments, by_id, sensor_context),
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
        windowed_detail = len(_detail_units(segments, by_id, sensor_context))
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
