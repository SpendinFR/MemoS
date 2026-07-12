"""Lossless projection of durable provenance into an LLM-facing payload.

Opaque database identifiers are essential to coverage, but hundreds of random
IDs carry no semantic information for a model.  Stage adapters can opt in to
this helper for known provenance fields.  The prompt receives a stable manifest
(count + digest), while the original payload remains untouched and is used by
the coverage ledger after the call.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Collection, Mapping

from .evidence_ref import content_digest


def project_opaque_ref_lists(
    payload: Any,
    *,
    field_names: Collection[str],
) -> Any:
    """Return a deep prompt projection with selected ID lists compacted.

    This is deliberately opt-in: a stage must name fields that are provenance
    only.  Semantic lists are therefore never compacted by a global heuristic.
    """
    selected = frozenset(str(name) for name in field_names)

    def _project(value: Any) -> Any:
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, child in value.items():
                name = str(key)
                if name in selected and isinstance(child, (list, tuple)):
                    refs = [str(ref) for ref in child if ref]
                    out[f"{name}_manifest"] = {
                        "count": len(refs),
                        "digest": content_digest(refs),
                    }
                else:
                    out[name] = _project(child)
            return out
        if isinstance(value, (list, tuple)):
            return [_project(item) for item in value]
        return deepcopy(value)

    return _project(payload)
