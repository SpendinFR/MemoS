"""E64-B audio reduction - keep every WhisperX turn intact, never re-split.

Audio is already atomic and cheap relative to vision, so E64-B does NOT collapse
it: each diarised turn / audio segment becomes one ``AudioTurnAtom`` preserving
its timestamps, speaker/person, transcript text and WAV source path. No turn is
merged with its neighbour and no turn is ever split in the middle. This keeps the
conversation faithful while the vision side is what gets collapsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..utils import stable_id
from .evidence_ref import content_digest


def _num(value: Any) -> float | None:
    if value is None or value == "None":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AudioTurnAtom:
    """One diarised turn / audio segment, preserved intact."""

    atom_id: str
    text: str
    start_s: float | None
    end_s: float | None
    absolute_start: str | None
    absolute_end: str | None
    speaker_label: str | None
    person_id: str | None
    digest: str
    source_refs: tuple[str, ...]  # segment_id / turn_id
    wav_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "absolute_start": self.absolute_start,
            "absolute_end": self.absolute_end,
            "speaker_label": self.speaker_label,
            "person_id": self.person_id,
            "digest": self.digest,
            "source_refs": list(self.source_refs),
            "wav_refs": list(self.wav_refs),
        }


def build_audio_atoms(segments: Iterable[Mapping[str, Any]]) -> list[AudioTurnAtom]:
    """One atom per audio segment/turn, time-ordered, nothing merged or split.

    Accepts rows shaped like ``brainlive_audio_segments_v154`` (segment_id,
    transcript_text, start_s/end_s, absolute_start/end, source_path) or ``turns``
    (turn_id, text, start_s/end_s, speaker_label, person_id).
    """
    rows = list(segments)
    atoms: list[AudioTurnAtom] = []
    for seg in rows:
        pk = str(
            seg.get("segment_id")
            or seg.get("turn_id")
            or seg.get("id")
            or ""
        )
        if not pk:
            continue
        text = str(seg.get("transcript_text") or seg.get("text") or "")
        wavs = [
            str(p)
            for p in (seg.get("source_path"), seg.get("chunk_path"))
            if p and p != "None"
        ]
        atoms.append(
            AudioTurnAtom(
                atom_id=stable_id("aatom", pk),
                text=text,
                start_s=_num(seg.get("start_s")),
                end_s=_num(seg.get("end_s")),
                absolute_start=(seg.get("absolute_start") or None),
                absolute_end=(seg.get("absolute_end") or None),
                speaker_label=(seg.get("speaker_label") or seg.get("speaker") or None),
                person_id=(seg.get("person_id") or None),
                digest=content_digest({"pk": pk, "text": text}),
                source_refs=(pk,),
                wav_refs=tuple(dict.fromkeys(wavs)),
            )
        )

    def _order(atom: AudioTurnAtom) -> tuple[Any, ...]:
        return (
            atom.absolute_start or "",
            atom.start_s if atom.start_s is not None else float("inf"),
            atom.atom_id,
        )

    atoms.sort(key=_order)
    return atoms
