from __future__ import annotations

"""Canonical owner perspective shared by semantic engines.

Names are data, never prompt constants.  A missing voice enrollment remains
explicitly unknown; no speaker is promoted to the owner from text or context.
"""

from typing import Any, Mapping


GENERIC_OWNER_ALIASES = {"me", "user", "utilisateur", "owner", "self"}


def _table_exists(con: Any, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def build_owner_context(con: Any, person_id: str) -> dict[str, Any]:
    owner_id = str(person_id or "me")
    display_name: str | None = None
    aliases = set(GENERIC_OWNER_ALIASES)
    aliases.add(owner_id.casefold())
    voice_cluster_ids: list[str] = []
    setup_status = "not_enrolled"

    if _table_exists(con, "self_voice_profile"):
        row = con.execute(
            "SELECT display_name,setup_status FROM self_voice_profile WHERE person_id=?",
            (owner_id,),
        ).fetchone()
        if row:
            display_name = str(row["display_name"] or "").strip() or None
            setup_status = str(row["setup_status"] or "not_enrolled")
    if _table_exists(con, "speaker_profiles"):
        row = con.execute(
            "SELECT display_name,aliases_json,is_user FROM speaker_profiles WHERE person_id=?",
            (owner_id,),
        ).fetchone()
        if row:
            display_name = display_name or (str(row["display_name"] or "").strip() or None)
            try:
                import json
                aliases.update(
                    str(value).strip().casefold()
                    for value in json.loads(row["aliases_json"] or "[]")
                    if str(value).strip()
                )
            except (TypeError, ValueError):
                pass
    if display_name:
        aliases.add(display_name.casefold())
    if _table_exists(con, "voice_clusters"):
        voice_cluster_ids = [
            str(row[0]) for row in con.execute(
                "SELECT cluster_id FROM voice_clusters WHERE canonical_person_id=? ORDER BY cluster_id",
                (owner_id,),
            )
        ]

    enrolled = bool(voice_cluster_ids) or setup_status.casefold() in {
        "ready", "completed", "enrolled", "quality_fixture",
    }
    return {
        "person_id": owner_id,
        "display_name": display_name,
        "aliases": sorted(alias for alias in aliases if alias),
        "voice_cluster_ids": voice_cluster_ids,
        "voice_identity_status": "verified" if enrolled else "not_enrolled",
        "perspective_contract": {
            "owner_claims_require_owner_evidence": True,
            "other_people_models_remain_distinct": True,
            "unknown_voice_is_never_owner": True,
        },
    }


def owner_aliases(context: Mapping[str, Any] | None, person_id: str = "me") -> set[str]:
    values = set(GENERIC_OWNER_ALIASES)
    values.add(str(person_id or "me").casefold())
    if isinstance(context, Mapping):
        values.add(str(context.get("person_id") or "").casefold())
        values.add(str(context.get("display_name") or "").casefold())
        values.update(str(value).casefold() for value in context.get("aliases") or [])
        values.update(str(value).casefold() for value in context.get("voice_cluster_ids") or [])
    return {value for value in values if value}


def perspective_role(person_ref: Any, context: Mapping[str, Any] | None) -> str:
    value = str(person_ref or "").strip()
    if not value:
        return "unknown"
    folded = value.casefold()
    if folded in owner_aliases(context, str((context or {}).get("person_id") or "me")):
        return "owner"
    if folded.startswith(("unknown", "unresolved", "speaker_")):
        return "unknown"
    return "other"
