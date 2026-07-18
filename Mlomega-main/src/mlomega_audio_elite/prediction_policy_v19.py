from __future__ import annotations

"""Evidence gate for durable nightly predictions.

The LLM may propose hypotheses freely in its audited engine output.  A proposal
is promoted to the canonical ``predictions`` table only when it cites an
existing empirical precedent that is explicitly usable for prediction.  This
policy intentionally does not apply to transient BrainLive/Ultralive H0 hints.
"""

from collections.abc import Mapping
from typing import Any


_PRECEDENT_KEYS = ("similar_cases", "evidence_cases", "precedent_refs")


def _precedent_ids(prediction: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in _PRECEDENT_KEYS:
        raw = prediction.get(key)
        values = raw if isinstance(raw, list) else ([raw] if raw else [])
        for value in values:
            if isinstance(value, str) and value.strip():
                ids.add(value.strip())
            elif isinstance(value, Mapping):
                for id_key in ("case_id", "episode_id", "source_id"):
                    ref = str(value.get(id_key) or "").strip()
                    if ref:
                        ids.add(ref)
    return ids


def durable_prediction_allowed(
    con: Any, prediction: Mapping[str, Any], *, person_id: str | None,
) -> bool:
    """Return true only for predictions backed by a durable usable case.

    Merely returning a high confidence or a prose ``why`` is not proof.  The
    referenced id must resolve to a canonical prediction case marked usable,
    owned by the same person (or deliberately unscoped).
    """

    refs = _precedent_ids(prediction)
    if not refs:
        return False
    marks = ",".join("?" for _ in refs)
    params: list[Any] = [*sorted(refs), person_id, person_id]
    row = con.execute(
        f"""SELECT 1 FROM prediction_cases
            WHERE case_id IN ({marks})
              AND COALESCE(usable_for_prediction,0)=1
              AND (person_id=? OR person_id IS NULL OR ? IS NULL)
            LIMIT 1""",
        tuple(params),
    ).fetchone()
    if row:
        return True
    # Some model contracts cite the observed episode rather than its case id.
    row = con.execute(
        f"""SELECT 1 FROM prediction_cases
            WHERE episode_id IN ({marks})
              AND COALESCE(usable_for_prediction,0)=1
              AND (person_id=? OR person_id IS NULL OR ? IS NULL)
            LIMIT 1""",
        tuple(params),
    ).fetchone()
    return bool(row)
