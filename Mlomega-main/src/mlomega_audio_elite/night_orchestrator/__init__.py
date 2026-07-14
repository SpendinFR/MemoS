"""E64 nightly LLM orchestrator - lossless, transversal infrastructure.

This package is ADDITIVE. E64-A (this + evidence_ref/stage_adapter) defines the
common contract; E64-B (vision_atoms/audio_atoms/multimodal_timeline/loaders)
defines the DETERMINISTIC, LOSSLESS pre-LLM reduction. Neither wires anything
into the existing close-day path yet - that is E64-C (token-aware windowing +
durable checkpoints) and E64-F (per-wave migration). Nothing here modifies a
business prompt and nothing here deletes or samples evidence: the raw evidence
tables are read-only inputs and every produced atom references all of the raw
rows it represents.

Design invariants (mirror docs/PROD_BACKLOG.md E64):
- No evidence loss: reduction only groups; every source row id is covered by
  exactly one atom's ``source_refs``.
- Total provenance: every atom and EvidenceRef carries stable source ids + a
  content digest.
- Ids never depend on an LLM attempt: ``evidence_id`` derives from
  ``(source_table, source_pk)`` only.
"""

from .evidence_ref import EvidenceRef, content_digest, make_ref
from .stage_adapter import (
    NightStageAdapter,
    StageContext,
    WindowSpec,
    estimate_tokens_for_text,
)
from .vision_atoms import (
    VisionChangeAtom,
    reduce_vision_observations,
    reduce_vision_timeline,
)
from .audio_atoms import AudioTurnAtom, build_audio_atoms
from .multimodal_timeline import TimelineEntry, build_timeline
from .window_planner import PlanUnit, PlannedWindow, plan_windows, subdivide
from .executor import (
    LLMCallResult,
    ModelBudget,
    StageResult,
    StageScope,
    WindowResult,
    run_windows,
)
from .merge_tree import (
    MergeItem,
    OverlapResult,
    all_evidence,
    default_combine,
    group_by,
    hierarchical_merge,
    resolve_overlap,
)
from .coverage import (
    CoverageReport,
    build_coverage_report,
    covered_refs_from_outputs_table,
    stage_stats,
)
from .ollama_window_llm import OllamaWindowLLM
from .prompt_projection import project_opaque_ref_lists
from .hierarchical_json import build_evidence_leaf_index, run_hierarchical_json

__all__ = [
    "EvidenceRef",
    "content_digest",
    "make_ref",
    "NightStageAdapter",
    "StageContext",
    "WindowSpec",
    "estimate_tokens_for_text",
    "VisionChangeAtom",
    "reduce_vision_observations",
    "reduce_vision_timeline",
    "AudioTurnAtom",
    "build_audio_atoms",
    "TimelineEntry",
    "build_timeline",
    "PlanUnit",
    "PlannedWindow",
    "plan_windows",
    "subdivide",
    "LLMCallResult",
    "ModelBudget",
    "StageResult",
    "StageScope",
    "WindowResult",
    "run_windows",
    "MergeItem",
    "OverlapResult",
    "resolve_overlap",
    "hierarchical_merge",
    "group_by",
    "default_combine",
    "all_evidence",
    "CoverageReport",
    "build_coverage_report",
    "covered_refs_from_outputs_table",
    "stage_stats",
    "OllamaWindowLLM",
    "project_opaque_ref_lists",
    "build_evidence_leaf_index",
    "run_hierarchical_json",
]
