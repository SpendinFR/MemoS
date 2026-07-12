"""E64-E anti-loss coverage manifest - prove every evidence is accounted for.

For each stage, every EXPECTED evidence id must end up in exactly one bucket:
- ``covered`` : directly cited by a produced output item;
- ``represented_by_atom`` : covered transitively through a derived atom's
  ``parent_refs`` (e.g. a VisionChangeAtom standing in for 400 observations);
- ``overlap_deduplicated`` : it lived in an overlap duplicate that was folded into
  a survivor (still covered, just not a separate item);
- ``quarantined`` : it sat in a quarantined window, WITH a recorded reason;
- ``missing`` : none of the above -> the stage MUST block.

"Noise / redundant" is never allowed to simply vanish: it is represented by a
parent atom or explicitly quarantined with a cause. Coverage is computed by
RE-READING the persisted outputs from their real table, never by trusting ids a
function happened to return.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import checkpoint_store as cp


@dataclass(frozen=True)
class CoverageReport:
    stage_name: str
    expected: tuple[str, ...]
    covered: tuple[str, ...]
    represented_by_atom: tuple[str, ...]
    overlap_deduplicated: tuple[str, ...]
    quarantined: tuple[tuple[str, str], ...]  # (evidence_id, reason)
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "expected_count": len(self.expected),
            "covered_count": len(self.covered),
            "represented_by_atom_count": len(self.represented_by_atom),
            "overlap_deduplicated_count": len(self.overlap_deduplicated),
            "quarantined_count": len(self.quarantined),
            "missing_count": len(self.missing),
            "missing": list(self.missing),
            "quarantined": [list(q) for q in self.quarantined],
            "ok": self.ok,
        }


def build_coverage_report(
    *,
    stage_name: str,
    expected_ids: Iterable[str],
    covered_refs: Iterable[str],
    atom_parent_index: Mapping[str, Iterable[str]] | None = None,
    overlap_deduplicated_refs: Iterable[str] = (),
    quarantined_reasons: Mapping[str, str] | None = None,
) -> CoverageReport:
    """Categorise every expected evidence id into exactly one bucket.

    ``atom_parent_index`` maps an atom/derived id -> the source evidence ids it
    represents; any expected id present there (and in a covered atom) counts as
    represented_by_atom. ``quarantined_reasons`` maps evidence_id -> reason.
    """
    expected = list(dict.fromkeys(str(e) for e in expected_ids))
    expected_set = set(expected)
    covered_set = {str(c) for c in covered_refs} & expected_set

    represented: set[str] = set()
    if atom_parent_index:
        for _atom_id, parents in atom_parent_index.items():
            for pid in parents:
                pid = str(pid)
                if pid in expected_set and pid not in covered_set:
                    represented.add(pid)

    overlap_dedup = ({str(x) for x in overlap_deduplicated_refs} & expected_set) - covered_set - represented

    quarantined_reasons = {str(k): v for k, v in (quarantined_reasons or {}).items()}
    quarantined = {
        eid: quarantined_reasons[eid]
        for eid in expected_set
        if eid in quarantined_reasons
        and eid not in covered_set
        and eid not in represented
        and eid not in overlap_dedup
    }

    accounted = covered_set | represented | overlap_dedup | set(quarantined)
    missing = tuple(e for e in expected if e not in accounted)

    return CoverageReport(
        stage_name=stage_name,
        expected=tuple(expected),
        covered=tuple(sorted(covered_set)),
        represented_by_atom=tuple(sorted(represented)),
        overlap_deduplicated=tuple(sorted(overlap_dedup)),
        quarantined=tuple(sorted(quarantined.items())),
        missing=missing,
    )


def covered_refs_from_outputs_table(
    con: Any,
    *,
    person_id: str,
    package_date: str,
    stage_name: str,
    extract_refs: Callable[[Any], Iterable[str]],
) -> set[str]:
    """Re-read persisted, VALIDATED outputs and extract their evidence refs.

    This is the anti-loss rule: coverage is proven from what actually landed in
    ``night_llm_window_outputs_v19`` (joined to completed windows), never from ids
    a function returned in memory. ``extract_refs`` pulls the evidence ids out of
    one stored output payload.
    """
    refs: set[str] = set()
    for row in cp.load_outputs(
        con, person_id=person_id, package_date=package_date, stage_name=stage_name
    ):
        for ref in extract_refs(row["output"]):
            refs.add(str(ref))
    return refs


def stage_stats(
    con: Any, *, person_id: str, package_date: str, stage_name: str
) -> dict[str, Any]:
    """Aggregate token/attempt/truncation stats for Doctor/dashboard.

    Derived from ``night_llm_windows_v19`` (no separate table): window counts by
    state, total attempts, summed input tokens, and how many windows hit a
    truncation (``length``) or had to be subdivided - the gaps to surface.
    """
    rows = con.execute(
        f"""SELECT state, attempts, input_tokens, error_text
              FROM {cp.WINDOWS_TABLE}
             WHERE person_id=? AND package_date=? AND stage_name=?""",
        (person_id, package_date, stage_name),
    ).fetchall()
    by_state: dict[str, int] = {}
    attempts = 0
    input_tokens = 0
    truncations = 0
    for state, att, toks, err in rows:
        by_state[state] = by_state.get(state, 0) + 1
        attempts += int(att or 0)
        input_tokens += int(toks or 0)
        if (err and "length" in err) or state == cp.STATE_SUBDIVIDED:
            truncations += 1
    return {
        "stage_name": stage_name,
        "windows": len(rows),
        "by_state": by_state,
        "total_attempts": attempts,
        "input_tokens": input_tokens,
        "truncations": truncations,
        "completed": by_state.get(cp.STATE_COMPLETED, 0),
        "quarantined": by_state.get(cp.STATE_QUARANTINED, 0),
        "error": by_state.get(cp.STATE_ERROR, 0),
    }
