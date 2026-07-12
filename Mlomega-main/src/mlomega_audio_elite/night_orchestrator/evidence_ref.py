"""EvidenceRef - stable, owner-scoped, LLM-attempt-independent evidence handle.

An ``EvidenceRef`` is the single currency the nightly orchestrator passes around.
It points back to one immutable source row (or one derived atom) and carries a
content digest so change-detection and coverage checks never need to re-read the
LLM. The ``evidence_id`` is derived ONLY from ``(source_table, source_pk)`` so it
is identical across runs, retries and machines - it never depends on a model
output. The ``digest`` captures the content and is what an atom compares to
decide whether state changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..utils import sha256_bytes, stable_id

# Modalities and payload kinds are open vocabularies but these are the ones E64-B
# produces / consumes today. Kept as plain strings (no enum) to stay trivially
# JSON-serialisable and forward compatible.
MODALITIES = ("audio", "vision", "event", "derived")


def _canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no NaN, stable across runs/machines."""
    import json

    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False
    )


def content_digest(payload: Any) -> str:
    """Stable sha256 hex of any JSON-able payload (dict/list/str/number).

    Used to detect content change between two observations of the same logical
    entity and to fingerprint an atom's covered content. Two structurally equal
    payloads always digest identically; key order does not matter.
    """
    if isinstance(payload, (bytes, bytearray)):
        return sha256_bytes(bytes(payload))
    if isinstance(payload, str):
        return sha256_bytes(payload.encode("utf-8"))
    return sha256_bytes(_canonical_json(payload).encode("utf-8"))


@dataclass(frozen=True)
class EvidenceRef:
    """Immutable pointer to one source row or one derived atom.

    ``evidence_id`` is deterministic from ``(source_table, source_pk)``.
    ``parent_refs`` links a derived ref (e.g. a VisionChangeAtom) to the raw
    evidence ids it represents, giving transitive provenance to the source rows.
    """

    evidence_id: str
    source_table: str
    source_pk: str
    modality: str
    payload_kind: str
    digest: str
    timestamp: str | None = None
    person_id: str | None = None
    parent_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.modality not in MODALITIES:
            # Do not raise on an unknown modality (forward compat), but keep the
            # known set discoverable. A typo is caught by tests, not runtime.
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_table": self.source_table,
            "source_pk": self.source_pk,
            "modality": self.modality,
            "payload_kind": self.payload_kind,
            "digest": self.digest,
            "timestamp": self.timestamp,
            "person_id": self.person_id,
            "parent_refs": list(self.parent_refs),
        }


def make_ref(
    *,
    source_table: str,
    source_pk: str,
    modality: str,
    payload_kind: str,
    payload: Any,
    timestamp: str | None = None,
    person_id: str | None = None,
    parent_refs: Sequence[str] | None = None,
) -> EvidenceRef:
    """Build an EvidenceRef with a deterministic id and content digest.

    ``source_pk`` MUST be unique within ``source_table`` (a primary key); the
    ``evidence_id`` is ``stable_id("evref", source_table, source_pk)`` so it is
    collision-free and independent of ``payload`` and of any LLM attempt.
    """
    evidence_id = stable_id("evref", source_table, source_pk)
    return EvidenceRef(
        evidence_id=evidence_id,
        source_table=source_table,
        source_pk=str(source_pk),
        modality=modality,
        payload_kind=payload_kind,
        digest=content_digest(payload),
        timestamp=timestamp,
        person_id=person_id,
        parent_refs=tuple(parent_refs or ()),
    )


def refs_cover(expected: Sequence[EvidenceRef], produced: Sequence[EvidenceRef]) -> set[str]:
    """Return the set of expected evidence_ids transitively covered by produced.

    A produced (derived) ref covers an expected id when the expected id appears
    in its ``parent_refs`` (or it *is* that expected ref). Used by the coverage
    manifest (E64-A helper, consumed fully in E64-E).
    """
    covered: set[str] = set()
    expected_ids = {r.evidence_id for r in expected}
    for ref in produced:
        if ref.evidence_id in expected_ids:
            covered.add(ref.evidence_id)
        for parent in ref.parent_refs:
            if parent in expected_ids:
                covered.add(parent)
    return covered
