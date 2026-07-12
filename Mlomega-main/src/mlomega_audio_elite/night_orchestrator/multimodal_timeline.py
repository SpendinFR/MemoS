"""E64-B multimodal timeline - order audio + vision atoms by time, no flattening.

Joins the intact audio turns and the collapsed vision atoms into one ordered
timeline keyed on real timestamps. Crucially it does NOT turn a vision atom into
a conversation turn: each entry keeps its modality and its own atom, so a later
stage can build episodes over a faithful multimodal stream instead of over 945
pseudo-turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .audio_atoms import AudioTurnAtom
from .vision_atoms import VisionChangeAtom


@dataclass(frozen=True)
class TimelineEntry:
    modality: str  # "audio" | "vision"
    t: str  # sort timestamp (absolute_start for audio, first_seen for vision)
    atom_id: str
    atom: Any  # AudioTurnAtom | VisionChangeAtom

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "t": self.t,
            "atom_id": self.atom_id,
            "atom": self.atom.to_dict(),
        }


def build_timeline(
    audio_atoms: Sequence[AudioTurnAtom],
    vision_atoms: Sequence[VisionChangeAtom],
) -> list[TimelineEntry]:
    """Return audio+vision atoms as one deterministic, time-ordered timeline.

    Sort key is the atom's start timestamp; ties break by modality then atom_id
    so the order is stable across runs. Empty timestamps sort first (they are
    session-relative atoms without an absolute clock) but keep a stable id order.
    """
    entries: list[TimelineEntry] = []
    for atom in audio_atoms:
        entries.append(
            TimelineEntry(
                modality="audio",
                t=str(atom.absolute_start or ""),
                atom_id=atom.atom_id,
                atom=atom,
            )
        )
    for atom in vision_atoms:
        entries.append(
            TimelineEntry(
                modality="vision",
                t=str(atom.first_seen or ""),
                atom_id=atom.atom_id,
                atom=atom,
            )
        )
    entries.sort(key=lambda e: (e.t, e.modality, e.atom_id))
    return entries
