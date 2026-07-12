"""NightStageAdapter - the common contract every nightly LLM stage implements.

E64-A defines the CONTRACT only. The generic executor (token-aware windowing,
durable checkpoints, retry, recursive subdivision on truncation) is E64-C and is
deliberately NOT in this file yet. A stage adapter exposes its business logic
(source query, local prompt, output validation, merge, persist, coverage) behind
these methods; the future executor drives budget/retry/checkpoint/resume around
them so no business prompt re-implements the mechanics.

This module also ships two small, fully deterministic helpers that E64-A can
already test and that later waves reuse unchanged:
- ``estimate_tokens_for_text`` : conservative, tokenizer-pluggable estimate.
- ``compute_coverage`` : the anti-loss manifest (expected vs covered vs
  quarantined vs missing); a non-empty ``missing`` MUST block a stage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .evidence_ref import EvidenceRef


@dataclass(frozen=True)
class StageContext:
    """Everything a stage needs to locate its evidence, owner-scoped."""

    person_id: str
    package_date: str
    live_session_id: str | None = None
    db_path: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowSpec:
    """One planned unit of work handed to the LLM (built in E64-C).

    Defined here so adapters can type ``build_window_prompt`` against a stable
    shape now. ``primary``/``overlap`` marks boundary items so the merge step can
    dedupe by source refs rather than by text.
    """

    stage_name: str
    window_index: int
    primary_refs: tuple[str, ...]
    overlap_refs: tuple[str, ...] = field(default_factory=tuple)
    input_digest: str = ""


@dataclass(frozen=True)
class CoverageManifest:
    """E64-E anti-loss manifest. ``ok`` is False whenever ``missing`` is non-empty."""

    stage_name: str
    expected: tuple[str, ...]
    covered: tuple[str, ...]
    quarantined: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "expected_count": len(self.expected),
            "covered_count": len(self.covered),
            "quarantined_count": len(self.quarantined),
            "missing_count": len(self.missing),
            "missing": list(self.missing),
            "ok": self.ok,
        }


def compute_coverage(
    *,
    stage_name: str,
    expected: Sequence[str],
    covered: Sequence[str],
    quarantined: Sequence[str] = (),
) -> CoverageManifest:
    """Deterministic coverage manifest.

    An expected evidence id is satisfied when it is either covered (directly or
    transitively) or explicitly quarantined with a reason recorded elsewhere.
    Anything left is ``missing`` and MUST block the stage. Quarantine never wins
    over coverage: an id counted as covered is not also reported missing.
    """
    expected_set = list(dict.fromkeys(str(e) for e in expected))
    covered_set = {str(c) for c in covered}
    quarantined_set = {str(q) for q in quarantined}
    missing = tuple(
        e for e in expected_set if e not in covered_set and e not in quarantined_set
    )
    return CoverageManifest(
        stage_name=stage_name,
        expected=tuple(expected_set),
        covered=tuple(sorted(covered_set & set(expected_set))),
        quarantined=tuple(sorted(quarantined_set & set(expected_set))),
        missing=missing,
    )


# A tokenizer is a callable text -> token count. Kept pluggable so E64-C can pass
# the real model tokenizer; the default is a conservative char-ratio estimate
# that never under-counts a typical Qwen/Latin+accent payload.
Tokenizer = Callable[[str], int]

_DEFAULT_CHARS_PER_TOKEN = 3.5


def estimate_tokens_for_text(text: str, *, tokenizer: Tokenizer | None = None) -> int:
    """Deterministic token estimate for a text blob.

    With no tokenizer, uses a conservative chars/token ratio (3.5) and rounds UP,
    so a real prompt is never silently under-budgeted. E64-C replaces the default
    with the model's own tokenizer via ``tokenizer=``.
    """
    if tokenizer is not None:
        return int(tokenizer(text))
    if not text:
        return 0
    import math

    return int(math.ceil(len(text) / _DEFAULT_CHARS_PER_TOKEN))


class NightStageAdapter(ABC):
    """Contract for a nightly LLM/VLM stage.

    The generic executor (E64-C) calls these in order:
      load_evidence -> (plan windows) -> build_window_prompt / validate_window_output
      -> merge_outputs -> persist_outputs -> verify_coverage.
    Implementations keep their existing business prompt inside
    ``build_window_prompt``; they never re-implement budgeting or checkpoints.
    """

    #: short unique stage name, e.g. "brain2_episodes", "deep_vision".
    stage_name: str = "unnamed_stage"

    @abstractmethod
    def load_evidence(self, ctx: StageContext) -> list[EvidenceRef]:
        """Return the owner-scoped, time-ordered evidence for this stage."""

    @abstractmethod
    def estimate_tokens(self, refs: Sequence[EvidenceRef]) -> int:
        """Estimate the prompt-token cost of rendering these refs."""

    @abstractmethod
    def build_window_prompt(self, ctx: StageContext, window: WindowSpec) -> Mapping[str, Any]:
        """Render ONE window into a concrete prompt payload (business prompt lives here)."""

    @abstractmethod
    def validate_window_output(self, output: Any) -> bool:
        """True only if the output honours the stage contract (no partial applied)."""

    @abstractmethod
    def merge_outputs(self, outputs: Sequence[Any]) -> Any:
        """Deterministically merge per-window outputs (business merge rules here)."""

    @abstractmethod
    def persist_outputs(self, ctx: StageContext, merged: Any) -> Any:
        """Write merged outputs to the stage's real tables."""

    @abstractmethod
    def verify_coverage(
        self, ctx: StageContext, expected: Sequence[EvidenceRef], produced: Sequence[EvidenceRef]
    ) -> CoverageManifest:
        """Re-read persisted outputs and prove every expected evidence is covered."""
