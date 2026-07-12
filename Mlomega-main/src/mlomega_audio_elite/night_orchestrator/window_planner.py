"""E64-C window planner - token-aware, boundary-aware, lossless windowing.

Turns an ordered list of atomic units (audio turns, vision atoms, episodes...)
into ``WindowSpec`` windows. The target is 40-50 useful units per window, but
that is only a TARGET: a window is cut earlier when the real token budget would
be exceeded or when a hard boundary (scene/episode change) is reached. The number
40-50 never causes a unit to be dropped.

Bounded overlap (default 4 units) is carried at each window's head as
``overlap_refs`` (marked, not primary) so an action/conversation spanning a
boundary is never cut in half; the merge step later dedupes overlap by source
refs. Every unit is ``primary`` in EXACTLY ONE window - that is the planning-level
losslessness the tests enforce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .evidence_ref import content_digest
from .stage_adapter import WindowSpec


@dataclass(frozen=True)
class PlanUnit:
    """One atomic, orderable unit to be windowed."""

    ref_id: str
    tokens: int
    boundary: bool = False  # a hard boundary STARTS at this unit (opens a window)
    ts: str = ""
    # Stable digest of the actual payload represented by ref_id. Without it, a
    # corrected transcript retaining the same durable ID would incorrectly
    # resume an output produced from the old text.
    content_digest: str = ""


@dataclass(frozen=True)
class PlannedWindow:
    """A WindowSpec plus the concrete units (needed for recursive subdivision)."""

    spec: WindowSpec
    primary_units: tuple[PlanUnit, ...]
    overlap_units: tuple[PlanUnit, ...] = field(default_factory=tuple)
    input_tokens: int = 0
    oversized: bool = False  # a single unit alone exceeds the input budget

    @property
    def units(self) -> tuple[PlanUnit, ...]:
        return self.overlap_units + self.primary_units


def plan_windows(
    units: Sequence[PlanUnit],
    *,
    stage_name: str,
    max_input_tokens: int,
    target_units: int = 45,
    overlap: int = 4,
) -> list[PlannedWindow]:
    """Plan windows over ``units`` (already in temporal order).

    Cut rules for the CURRENT window (checked before adding unit i, window
    non-empty): close if it already holds ``target_units``; or if adding unit i
    would exceed ``max_input_tokens``; or if unit i is a hard boundary. A single
    unit whose own token cost exceeds ``max_input_tokens`` still gets its own
    window, flagged ``oversized`` (the executor subdivides its OUTPUT or
    quarantines it - the planner never drops it).
    """
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    windows: list[PlannedWindow] = []
    cur: list[PlanUnit] = []
    cur_tokens = 0

    def _close(primary: list[PlanUnit]) -> None:
        if not primary:
            return
        idx = len(windows)
        overlap_units: tuple[PlanUnit, ...] = ()
        if idx > 0 and overlap > 0:
            overlap_units = windows[idx - 1].primary_units[-overlap:]
        primary_ids = tuple(u.ref_id for u in primary)
        overlap_ids = tuple(u.ref_id for u in overlap_units)
        input_fingerprints = [
            {"ref_id": u.ref_id, "content_digest": u.content_digest or u.ref_id}
            for u in (*overlap_units, *primary)
        ]
        in_tokens = sum(u.tokens for u in overlap_units) + sum(u.tokens for u in primary)
        spec = WindowSpec(
            stage_name=stage_name,
            window_index=idx,
            primary_refs=primary_ids,
            overlap_refs=overlap_ids,
            input_digest=content_digest(input_fingerprints),
        )
        oversized = len(primary) == 1 and primary[0].tokens > max_input_tokens
        windows.append(
            PlannedWindow(
                spec=spec,
                primary_units=tuple(primary),
                overlap_units=overlap_units,
                input_tokens=in_tokens,
                oversized=oversized,
            )
        )

    for unit in units:
        if cur:
            hit_target = len(cur) >= target_units
            over_budget = cur_tokens + unit.tokens > max_input_tokens
            at_boundary = unit.boundary
            if hit_target or over_budget or at_boundary:
                _close(cur)
                cur, cur_tokens = [], 0
        cur.append(unit)
        cur_tokens += unit.tokens
    _close(cur)
    return windows


def subdivide(window: PlannedWindow, *, stage_name: str) -> list[PlannedWindow]:
    """Split one window's PRIMARY units in half for recursive retry on truncation.

    Overlap is recomputed as none for the sub-windows (they are internal to the
    parent window and merged back). Returns [] if the window holds a single unit
    (cannot subdivide further - caller must quarantine).
    """
    primary = list(window.primary_units)
    if len(primary) <= 1:
        return []
    mid = len(primary) // 2
    halves = [primary[:mid], primary[mid:]]
    out: list[PlannedWindow] = []
    for i, half in enumerate(halves):
        ids = tuple(u.ref_id for u in half)
        input_fingerprints = [
            {"ref_id": u.ref_id, "content_digest": u.content_digest or u.ref_id}
            for u in half
        ]
        spec = WindowSpec(
            stage_name=stage_name,
            window_index=window.spec.window_index * 1000 + i + 1,
            primary_refs=ids,
            overlap_refs=(),
            input_digest=content_digest(input_fingerprints),
        )
        out.append(
            PlannedWindow(
                spec=spec,
                primary_units=tuple(half),
                overlap_units=(),
                input_tokens=sum(u.tokens for u in half),
                oversized=len(half) == 1 and half[0].tokens > 0 and False,
            )
        )
    return out
