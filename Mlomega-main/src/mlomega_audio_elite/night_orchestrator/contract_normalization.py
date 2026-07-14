from __future__ import annotations

"""Shape-safe projection from validated JSON contracts to legacy SQLite writers.

The hierarchical journal keeps the raw provider outputs.  This module only coerces
schema leaves for writers whose historical columns are scalar.  In particular, an
unexpected object is never stringified into a durable foreign/person identifier.
"""

from typing import Any, Mapping

from ..utils import json_dumps


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json_dumps(value)


def _identifier(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int)):
        candidate = str(value).strip()
        return candidate or None
    if isinstance(value, Mapping):
        for key in (
            "known_person_id", "suspected_person_id", "person_id",
            "voice_cluster_id", "loop_id", "id", "value",
        ):
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return str(candidate).strip()
    if isinstance(value, list) and len(value) == 1:
        return _identifier(value[0])
    return None


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "oui"}
    return False


def _leaf(value: Any, template: Any, field_name: str) -> Any:
    if template is None:
        return _identifier(value) if field_name.endswith("_id") else _text(value)
    if isinstance(template, bool):
        return _boolean(value)
    if isinstance(template, float):
        return _clamp(value)
    if isinstance(template, str):
        return _text(value, "")
    if isinstance(template, list):
        if value is None:
            return []
        return value if isinstance(value, list) else [value]
    return value


def normalize_contract_output(
    value: Mapping[str, Any], schema: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a writer-safe output while preserving extra provider fields."""

    normalized = dict(value)
    for section, template in schema.items():
        section_value = value.get(section)
        if isinstance(template, list) and template and isinstance(template[0], Mapping):
            records = section_value if isinstance(section_value, list) else []
            normalized_records: list[dict[str, Any]] = []
            for record in records:
                if not isinstance(record, Mapping):
                    continue
                projected = dict(record)
                for field_name, field_template in template[0].items():
                    projected[field_name] = _leaf(
                        record.get(field_name), field_template, field_name
                    )
                normalized_records.append(projected)
            normalized[section] = normalized_records
        else:
            normalized[section] = _leaf(section_value, template, section)
    return normalized
