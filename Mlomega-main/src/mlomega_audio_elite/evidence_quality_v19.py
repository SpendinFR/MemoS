from __future__ import annotations

"""E64-I0.2 central evidence-quality confidence ceiling (OBS-29).

A conclusion may never exceed the quality of the *real* evidence that supports
it.  Before this module `confidence_ceiling` was derived from the model output
plus a flat cited/uncited discount.  That let a model claim 0.95 on a fact whose
only citation was a turn transcribed by ASR at 0.20 word alignment, or attribute
an owner trait to a voice that was never enrolled.

This module is the single, always-central policy.  It reads the durable
provenance already present in `turns.metadata_json` (WhisperX word alignment
scores under `source.words[].score`, offline speaker/owner resolution under
`source.offline_speaker_resolution`, and any language signal) and derives, per
cited turn, a bounded evidence-quality score.  A fact's ceiling is the *best*
supporting evidence (a conclusion never exceeds its strongest proof), and only
*independent* corroboration — evidence drawn from distinct turns and distinct
audio sources, not the same turn recopied — may lift that ceiling in a small,
documented, capped way.

No engine gets a private compactor: every producer calls the same functions.
The raw turn stays durable in SQLite; nothing is deleted or dedup'd by text.
"""

import math
import os
from typing import Any, Mapping, Sequence

from .utils import json_loads


EVIDENCE_CEILING_ENV = "MLOMEGA_E64_EVIDENCE_CEILING"

# Ceiling applied to a fact with no real cited turn evidence (model output only).
# This preserves the pre-existing uncited discount so legacy behaviour for
# uncited facts is unchanged.
UNCITED_CEILING = 0.49

# A single independent, high-quality corroborating turn may lift the ceiling by
# this much above the best individual evidence, and never past this hard cap.
# Corroboration is a bonus for reproducibility, not a licence to exceed the
# quality of any single proof by an unbounded amount.
CORROBORATION_BONUS = 0.10
CORROBORATION_HARD_CAP = 0.95
# Independent corroborating turns are only counted as such when their own
# evidence quality clears this bar, so noise cannot "corroborate" itself.
CORROBORATION_MIN_QUALITY = 0.60

# Owner / self attribution requires a positive voice resolution.  These are the
# offline_speaker_resolution.decision values that mean "this voice was matched to
# an enrolled profile".  Anything else (unknown_cluster, missing) is unenrolled.
POSITIVE_OWNER_DECISIONS = {"known_person_match", "known_voice_match"}

# Owner aliases mirror the daily projection: a non-enrolled voice may never
# resolve to any of these.
OWNER_ALIASES = {"me", "user", "utilisateur", "william", "will", "owner", "self"}

# Language coherence: the conversation baseline language.  A fact whose only
# evidence is a short, low-confidence fragment in a language incoherent with the
# baseline is quarantined (kept in the DB, flagged, never promoted).
QUARANTINE_MAX_ALIGNMENT = 0.55
QUARANTINE_MAX_WORDS = 4


def evidence_ceiling_enabled() -> bool:
    """Always-on quality correction with an explicit legacy rollback.

    OBS-29 is a correctness fix, not an opt-in feature, so the policy is the
    product default.  Operators keep a single emergency switch
    (MLOMEGA_E64_EVIDENCE_CEILING=0) that restores the pre-I0.2 cited/uncited
    ceiling for a controlled rollback.
    """

    return os.environ.get(EVIDENCE_CEILING_ENV, "1").strip() != "0"


def _clamp(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(result):
        return 0.0
    return max(0.0, min(1.0, result))


def _iter_words(source: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the WhisperX aligned words, preferring the top-level copy."""

    words = source.get("words")
    if isinstance(words, list) and words:
        return [word for word in words if isinstance(word, Mapping)]
    metadata = source.get("whisperx_metadata")
    segment = metadata.get("whisperx_segment") if isinstance(metadata, Mapping) else None
    seg_words = segment.get("words") if isinstance(segment, Mapping) else None
    if isinstance(seg_words, list):
        return [word for word in seg_words if isinstance(word, Mapping)]
    return []


def _alignment_quality(words: Sequence[Mapping[str, Any]]) -> tuple[float, int]:
    """Mean WhisperX word alignment score, and the word count.

    WhisperX word `score` is the alignment/ASR confidence per word.  The mean is
    a conservative proxy for how well the transcript is grounded in the audio.
    Empty/scoreless words contribute a 0.0 quality so silence never inflates a
    ceiling.
    """

    scores: list[float] = []
    for word in words:
        if "score" in word:
            scores.append(_clamp(word.get("score")))
    if not words:
        return 0.0, 0
    if not scores:
        # Words present but no alignment score at all: unknown quality, treat as
        # weak evidence rather than assuming it is perfect.
        return 0.0, len(words)
    return sum(scores) / len(scores), len(words)


def _language_signal(source: Mapping[str, Any]) -> str | None:
    """Best-effort language code carried by the turn, when producers emit one.

    The audit clone carries no explicit language field, but the deep-audio
    producer processes with a declared language and future rows may transport a
    detected language.  We look in the documented places and stay None-safe.
    """

    for key in ("language", "detected_language", "language_code", "lang", "lang_code"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    metadata = source.get("whisperx_metadata")
    if isinstance(metadata, Mapping):
        for key in ("language", "detected_language", "language_code"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    return None


def turn_evidence_quality(
    metadata: Mapping[str, Any] | str | None,
    *,
    person_id: str | None = None,
    baseline_language: str | None = None,
) -> dict[str, Any]:
    """Derive the real evidence quality of one turn from its provenance.

    Returns a dict with the transported ASR/alignment/diarization/owner/language
    attributes and a single bounded `quality` score (max reachable ceiling for a
    fact whose best proof is this turn).
    """

    if isinstance(metadata, str):
        metadata = json_loads(metadata, {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    source = metadata.get("source")
    if not isinstance(source, Mapping):
        source = {}

    words = _iter_words(source)
    alignment, word_count = _alignment_quality(words)

    resolution = source.get("offline_speaker_resolution")
    if not isinstance(resolution, Mapping):
        resolution = {}
    decision = str(resolution.get("decision") or "").strip().lower()
    known_score = _clamp(resolution.get("known_score"))
    owner_enrolled = decision in POSITIVE_OWNER_DECISIONS

    # Diarisation quality: an enrolled positive match is trustworthy in
    # proportion to its known_score; an unknown cluster is a valid *segmentation*
    # but not a validated identity, so its speaker attribution is capped.
    if owner_enrolled:
        diarization_quality = max(0.5, known_score)
    elif decision == "unknown_cluster":
        diarization_quality = 0.5
    elif decision:
        diarization_quality = 0.4
    else:
        # No offline resolution recorded at all: treat speaker attribution as
        # weak but do not zero out transcript quality.
        diarization_quality = 0.3

    # Audio-source identity, used to judge *independent* corroboration: two
    # evidence slots that trace to the same bundle/event are the same proof.
    source_event_ids = source.get("source_event_ids")
    source_id = None
    if isinstance(source_event_ids, list) and source_event_ids:
        source_id = str(source_event_ids[0])
    elif source.get("bundle_id"):
        source_id = str(source.get("bundle_id"))
    elif source.get("deep_audio_artifact_id"):
        source_id = str(source.get("deep_audio_artifact_id"))

    language = _language_signal(source)
    language_confidence = _clamp(source.get("language_confidence")) if source else 0.0

    # A turn's overall evidence quality is bounded by its transcript grounding
    # (alignment) — a conclusion cannot be more certain than the words it rests
    # on.  A turn that carries NO provenance at all (empty metadata, e.g. a
    # non-audio or legacy turn) has *unknown* quality, not zero quality: it must
    # not silently collapse an otherwise valid conclusion.  Such turns are
    # marked quality_known=False and do not cap the ceiling.
    asr_confidence = _clamp(source.get("asr_confidence"))
    has_signal = bool(word_count) or bool(asr_confidence) or bool(decision)
    if word_count:
        transcript_quality = alignment
    elif asr_confidence:
        transcript_quality = asr_confidence
    else:
        transcript_quality = 0.0
    if word_count:
        quality = min(transcript_quality, max(diarization_quality, 0.0))
    else:
        quality = transcript_quality

    incoherent_language = bool(
        baseline_language
        and language
        and language != baseline_language
        and alignment <= QUARANTINE_MAX_ALIGNMENT
        and word_count <= QUARANTINE_MAX_WORDS
    )

    return {
        "asr_alignment": round(alignment, 4),
        "asr_confidence": round(asr_confidence, 4) if asr_confidence else None,
        "word_count": word_count,
        "diarization_decision": decision or None,
        "diarization_known_score": round(known_score, 4),
        "diarization_quality": round(diarization_quality, 4),
        "owner_enrolled": owner_enrolled,
        "resolved_person_id": str(resolution.get("person_id")) if resolution.get("person_id") else (str(person_id) if person_id else None),
        "source_id": source_id,
        "language": language,
        "language_confidence": round(language_confidence, 4) if language_confidence else None,
        "baseline_language": baseline_language,
        "incoherent_language": incoherent_language,
        "quality_known": has_signal,
        "quality": round(_clamp(quality), 4),
    }


def conversation_baseline_language(turn_metadata: Sequence[Any]) -> str | None:
    """Majority language across a conversation's turns, when any is transported."""

    counts: dict[str, int] = {}
    for metadata in turn_metadata:
        if isinstance(metadata, str):
            metadata = json_loads(metadata, {})
        if not isinstance(metadata, Mapping):
            continue
        source = metadata.get("source")
        if not isinstance(source, Mapping):
            continue
        language = _language_signal(source)
        if language:
            counts[language] = counts.get(language, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def evidence_ceiling(
    model_confidence: float,
    turn_qualities: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the confidence ceiling of a fact from its cited turn qualities.

    Rule (documented, central):
      * A fact with no cited turn evidence keeps the flat uncited ceiling.
      * best = max quality over cited turns.  A conclusion may not exceed its
        strongest single proof.
      * Independent corroboration: additional cited turns that are themselves of
        high quality (>= CORROBORATION_MIN_QUALITY) and come from *distinct*
        turns and distinct audio sources add CORROBORATION_BONUS each, capped at
        CORROBORATION_HARD_CAP and never more than (best + one bonus rounded up
        by extra independent proofs).
      * The ceiling is finally clamped by the model's own asserted confidence:
        the policy only ever *lowers* a claim to match its evidence, it never
        invents certainty the model did not assert.
    """

    model_confidence = _clamp(model_confidence)
    if not turn_qualities:
        ceiling = min(model_confidence, UNCITED_CEILING)
        return {
            "ceiling": round(ceiling, 4),
            "best_evidence_quality": 0.0,
            "independent_corroboration": 0,
            "cited_count": 0,
            "capped_by": "uncited_model_output",
        }

    # Only turns that carry a real ASR/alignment/diarisation signal cap the
    # ceiling.  A cited turn with no provenance at all (legacy/non-audio) is
    # evidence of citation but not a measured quality bound, so it keeps the
    # model's asserted confidence rather than collapsing it to zero.
    measured = [item for item in turn_qualities if item.get("quality_known")]
    if not measured:
        return {
            "ceiling": round(model_confidence, 4),
            "best_evidence_quality": None,
            "independent_corroboration": 0,
            "cited_count": len(turn_qualities),
            "capped_by": "cited_quality_unmeasured",
        }
    turn_qualities = measured

    qualities = [_clamp(item.get("quality")) for item in turn_qualities]
    best = max(qualities)

    # Count independent corroboration: reliable turns beyond the strongest, drawn
    # from distinct turn ids AND distinct audio sources so the same turn recopied
    # into two evidence slots cannot pretend to be two proofs.
    seen_turns: set[str] = set()
    seen_sources: set[str] = set()
    independent = 0
    # Sort so the single strongest proof anchors `best` and the rest may
    # corroborate.
    ordered = sorted(turn_qualities, key=lambda item: _clamp(item.get("quality")), reverse=True)
    for index, item in enumerate(ordered):
        quality = _clamp(item.get("quality"))
        turn_id = str(item.get("turn_id") or "")
        source_id = str(
            item.get("source_id")
            or item.get("bundle_id")
            or item.get("resolved_person_id")
            or turn_id
        )
        if index == 0:
            # anchor proof
            if turn_id:
                seen_turns.add(turn_id)
            if source_id:
                seen_sources.add(source_id)
            continue
        if quality < CORROBORATION_MIN_QUALITY:
            continue
        if turn_id and turn_id in seen_turns:
            continue
        if source_id and source_id in seen_sources:
            # same audio source: not independent corroboration
            continue
        independent += 1
        if turn_id:
            seen_turns.add(turn_id)
        if source_id:
            seen_sources.add(source_id)

    corroborated = min(
        CORROBORATION_HARD_CAP,
        best + CORROBORATION_BONUS * independent,
    )
    ceiling = min(model_confidence, corroborated)
    capped_by = (
        "model_confidence" if ceiling >= corroborated and model_confidence < corroborated
        else "best_evidence" if independent == 0
        else "independent_corroboration"
    )
    return {
        "ceiling": round(_clamp(ceiling), 4),
        "best_evidence_quality": round(best, 4),
        "independent_corroboration": independent,
        "cited_count": len(turn_qualities),
        "capped_by": capped_by,
    }


def owner_attribution_allowed(turn_qualities: Sequence[Mapping[str, Any]]) -> bool:
    """A subject may be the owner only if a cited turn has an enrolled voice."""

    return any(bool(item.get("owner_enrolled")) for item in turn_qualities)


def language_quarantine(turn_qualities: Sequence[Mapping[str, Any]]) -> str | None:
    """Return a quarantine cause when every cited proof is an incoherent fragment.

    The whole fact is quarantined only when it has cited evidence and *all* of it
    is an isolated, low-confidence, off-baseline-language fragment.  A fact with
    even one coherent proof is not quarantined by this rule.
    """

    if not turn_qualities:
        return None
    if all(bool(item.get("incoherent_language")) for item in turn_qualities):
        return "incoherent_language_fragment"
    return None
