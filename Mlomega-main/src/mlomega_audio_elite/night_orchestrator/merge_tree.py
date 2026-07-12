"""E64-D hierarchical merge - deterministic fold, overlap dedup by evidence.

Per-window outputs are merged UP a deterministic tree (windows -> scene/bundle ->
conversation -> day) by pure code, never by re-concatenating every output into a
new giant prompt. The overlap that E64-C intentionally carried at window
boundaries is resolved here: two items are duplicates only when they share a
stable SEMANTIC key AND their evidence sets (or time ranges) overlap - NEVER on
text alone. The survivor absorbs the duplicate's evidence refs, so provenance to
the source rows is preserved transitively.

The MECHANIC (grouping, dedup, fold order) is common; a stage adapter provides
only its business ``combine`` rule (compatible adjacent episodes, entities by
durable id, contradictions kept, ordered timelines).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class MergeItem:
    """One mergeable output unit with full provenance."""

    item_id: str
    semantic_key: str  # stable business key (episode kind + normalized subject...), NOT text
    evidence_refs: frozenset[str]
    time_start: str = ""
    time_end: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    parent_items: tuple[str, ...] = ()  # item_ids folded into this one

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "semantic_key": self.semantic_key,
            "evidence_refs": sorted(self.evidence_refs),
            "time_start": self.time_start,
            "time_end": self.time_end,
            "payload": dict(self.payload),
            "parent_items": list(self.parent_items),
        }


@dataclass(frozen=True)
class OverlapResult:
    survivors: tuple[MergeItem, ...]
    dropped_to_survivor: Mapping[str, str]  # dropped item_id -> survivor item_id


def _ranges_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    if not (a_start and b_start):
        return False
    a_end = a_end or a_start
    b_end = b_end or b_start
    return a_start <= b_end and b_start <= a_end


def resolve_overlap(items: Sequence[MergeItem]) -> OverlapResult:
    """Deterministically dedupe overlap duplicates by evidence + semantic key.

    Two items merge iff same ``semantic_key`` AND (evidence sets intersect OR time
    ranges overlap). The survivor is the earliest (by time_start then item_id);
    it absorbs the duplicate's ``evidence_refs`` and time span. Never text-based.
    """
    ordered = sorted(items, key=lambda i: (i.time_start, i.item_id))
    survivors: list[MergeItem] = []
    dropped: dict[str, str] = {}
    for item in ordered:
        match: int | None = None
        for idx, surv in enumerate(survivors):
            if surv.semantic_key != item.semantic_key:
                continue
            shares_evidence = bool(surv.evidence_refs & item.evidence_refs)
            overlaps_time = _ranges_overlap(
                surv.time_start, surv.time_end, item.time_start, item.time_end
            )
            if shares_evidence or overlaps_time:
                match = idx
                break
        if match is None:
            survivors.append(item)
        else:
            surv = survivors[match]
            survivors[match] = MergeItem(
                item_id=surv.item_id,
                semantic_key=surv.semantic_key,
                evidence_refs=surv.evidence_refs | item.evidence_refs,
                time_start=min(surv.time_start, item.time_start) if item.time_start else surv.time_start,
                time_end=max(surv.time_end or surv.time_start, item.time_end or item.time_start),
                payload=surv.payload,
                parent_items=surv.parent_items + (item.item_id,),
            )
            dropped[item.item_id] = surv.item_id
    return OverlapResult(survivors=tuple(survivors), dropped_to_survivor=dropped)


def group_by(
    items: Sequence[MergeItem], key_fn: Callable[[MergeItem], str]
) -> list[tuple[str, list[MergeItem]]]:
    """Deterministic grouping: groups sorted by key, members keep input order."""
    groups: dict[str, list[MergeItem]] = {}
    for item in items:
        groups.setdefault(key_fn(item), []).append(item)
    return [(k, groups[k]) for k in sorted(groups)]


def default_combine(key: str, members: Sequence[MergeItem]) -> MergeItem:
    """Lossless default fold: union evidence, span time, keep children payloads.

    A stage adapter overrides this with its business merge; the default never
    loses a reference (it unions everything and records parents).
    """
    evidence: frozenset[str] = frozenset().union(*(m.evidence_refs for m in members)) if members else frozenset()
    starts = [m.time_start for m in members if m.time_start]
    ends = [m.time_end or m.time_start for m in members if (m.time_end or m.time_start)]
    return MergeItem(
        item_id=f"merge_{key}",
        semantic_key=key,
        evidence_refs=evidence,
        time_start=min(starts) if starts else "",
        time_end=max(ends) if ends else "",
        payload={"children": [m.to_dict() for m in members]},
        parent_items=tuple(m.item_id for m in members),
    )


def hierarchical_merge(
    items: Sequence[MergeItem],
    *,
    level_key_fns: Sequence[Callable[[MergeItem], str]],
    combine: Callable[[str, Sequence[MergeItem]], MergeItem] = default_combine,
    resolve_first: bool = True,
) -> list[MergeItem]:
    """Fold outputs up a deterministic tree (finest level first).

    ``level_key_fns`` are ordered from the finest grouping (e.g. scene/bundle) to
    the coarsest (e.g. conversation, then day). Overlap is resolved at the leaf
    level first (``resolve_first``). No level ever builds a giant prompt; each
    ``combine`` is a pure function and MUST union evidence (the default does).
    """
    current = list(resolve_overlap(items).survivors) if resolve_first else list(items)
    for key_fn in level_key_fns:
        merged: list[MergeItem] = []
        for key, members in group_by(current, key_fn):
            merged.append(combine(key, members))
        current = merged
    return current


def all_evidence(items: Sequence[MergeItem]) -> set[str]:
    """Transitive union of evidence refs across a set of (possibly merged) items."""
    out: set[str] = set()
    for item in items:
        out |= set(item.evidence_refs)
    return out
