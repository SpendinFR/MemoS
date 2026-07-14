"""NightStageAdapter - the common contract every nightly LLM stage implements.

E64-A defines the CONTRACT only. The generic executor (token-aware windowing,
durable checkpoints, retry, recursive subdivision on truncation) is E64-C and is
deliberately NOT in this file yet. A stage adapter exposes its business logic
(source query, local prompt, output validation, merge, persist, coverage) behind
these methods; the future executor drives budget/retry/checkpoint/resume around
them so no business prompt re-implements the mechanics.

This module also ships a small, fully deterministic helper that later waves
reuse unchanged: ``estimate_tokens_for_text`` (conservative, tokenizer-pluggable).

The anti-loss coverage manifest is NOT here: it lives in ``coverage.py``
(``CoverageReport`` + ``build_coverage_report``), which recomputes coverage by
RE-READING the persisted outputs from the DB. ``verify_coverage`` below returns
that rich report - there is deliberately no simplified in-memory manifest, so a
stage cannot be declared green from ids a function merely returned.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from .evidence_ref import EvidenceRef

if TYPE_CHECKING:
    from .coverage import CoverageReport


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


# A tokenizer is a callable text -> token count. Kept pluggable so E64-C can pass
# the real model tokenizer; the default is a conservative char-ratio estimate
# that never under-counts a typical Qwen/Latin+accent payload.
Tokenizer = Callable[[str], int]

# Qwen's tokenizer is materially denser on nested JSON, identifiers and French
# punctuation than the old prose-oriented 3.5 estimate. Real E64-F requests on
# the production 9B model measured ~24.3k tokens where declared unit accounting
# predicted ~17k. 2.5 is deliberately conservative until a provider tokenizer
# is injected; over-estimating creates an extra safe window, under-estimating
# spends a full call that can only end at the context boundary.
_DEFAULT_CHARS_PER_TOKEN = 2.5


def estimate_tokens_for_text(text: str, *, tokenizer: Tokenizer | None = None) -> int:
    """Deterministic token estimate for a text blob.

    With no tokenizer, uses a conservative chars/token ratio (2.5) and rounds UP,
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
        self, con: Any, ctx: StageContext, expected: Sequence[EvidenceRef]
    ) -> "CoverageReport":
        """Return the RICH coverage manifest, recomputed by RE-READING the DB.

        Implementations MUST derive the covered refs from the persisted outputs
        (``coverage.covered_refs_from_outputs_table``) and build the report with
        ``coverage.build_coverage_report`` - never from ids returned in memory by
        an earlier step. A non-empty ``missing`` MUST block the stage, and an atom
        only counts as representing its parents when the atom itself is cited in a
        persisted output.
        """
