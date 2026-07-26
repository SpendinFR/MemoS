from __future__ import annotations

"""Explicit-consent profile projection for the optional AR process.

This module deliberately does not discover or name strangers.  Identity comes
from the product's enrolled YuNet/SFace gallery.  Public handles are displayed
only when the filmed person signed the corresponding scope and the source was
entered in the bounded registry.  The registry is not ``memory.db`` and this
module never writes personal memory.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_PEOPLE = 128
MAX_SOURCES = 8
ALLOWED_SCOPES = {"profile_card", "public_sources", "physiology"}
ALLOWED_PROVIDERS = {
    "website",
    "instagram",
    "x",
    "twitter",
    "youtube",
    "tiktok",
    "linkedin",
    "github",
    "reddit",
    "other",
}


@dataclass(frozen=True)
class ConsentedPerson:
    person_id: str
    display_name: str
    consent_id: str
    signed_at: str
    scopes: frozenset[str]
    summary: str
    sources: tuple[dict[str, str], ...]


class ConsentedProfileRegistry:
    """Read-only allowlist of people and consented public profile fields."""

    def __init__(self, people: dict[str, ConsentedPerson] | None = None) -> None:
        self._people = dict(people or {})

    @classmethod
    def from_env(cls) -> "ConsentedProfileRegistry":
        raw = os.environ.get("MLOMEGA_AR_CONSENTED_PEOPLE", "").strip()
        if not raw:
            return cls()
        return cls.from_path(raw)

    @classmethod
    def from_path(cls, path: str | Path) -> "ConsentedProfileRegistry":
        resolved = Path(path).expanduser().resolve()
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 1:
            raise ValueError("consented people registry requires schema_version=1")
        entries = payload.get("people")
        if not isinstance(entries, list) or len(entries) > MAX_PEOPLE:
            raise ValueError("consented people registry has invalid people list")
        people: dict[str, ConsentedPerson] = {}
        for raw_entry in entries:
            person = _normalise_person(raw_entry)
            if person.person_id in people:
                raise ValueError(f"duplicate consented person_id: {person.person_id}")
            people[person.person_id] = person
        return cls(people)

    @property
    def available(self) -> bool:
        return bool(self._people)

    def supports(self, scope: str) -> bool:
        return any(scope in person.scopes for person in self._people.values())

    def get(self, person_id: str) -> ConsentedPerson | None:
        return self._people.get(str(person_id or "").strip())

    def project(
        self,
        payload: dict[str, Any],
        *,
        profile_enabled: bool,
        pulse_enabled: bool,
    ) -> dict[str, Any]:
        person_id = str(payload.get("person_id") or "").strip()
        person = self.get(person_id)
        confidence = float(payload.get("identity_confidence") or 0.0)
        if person is None:
            return {"status": "no_consent", "person_id": person_id}
        if confidence < 0.45:
            return {
                "status": "identity_below_threshold",
                "person_id": person_id,
            }

        result: dict[str, Any] = {
            "status": "ready",
            "person_id": person_id,
            "consent_id": person.consent_id,
        }
        if profile_enabled and "profile_card" in person.scopes:
            sources = (
                list(person.sources)
                if "public_sources" in person.scopes
                else []
            )
            result["profile_intent"] = {
                "type": "ui_intent",
                "contracts_version": "v19.0",
                "ui_intent_id": (
                    f"consented-profile:{payload.get('session_id')}:{person_id}"
                ),
                "producer": "ultralive",
                "source_frame_id": str(payload.get("source_frame_id") or ""),
                "target_track_id": str(payload.get("target_track_id") or ""),
                "entity_id": str(payload.get("entity_id") or ""),
                "component": "person_profile_card",
                "anchor": {
                    "type": "track",
                    "bbox": _bounded_bbox(payload.get("person_bbox")),
                },
                "content": {
                    "kind": "consented_person_profile",
                    "name": person.display_name,
                    "summary": person.summary,
                    "public_sources": sources,
                    "identity_method": str(
                        payload.get("identity_method") or "enrolled_face"
                    )[:48],
                    "identity_confidence": round(confidence, 4),
                    "consent_id": person.consent_id,
                    "consent_signed_at": person.signed_at,
                    "verified_sources_only": True,
                },
                "truth_level": "observed",
                "confidence": round(confidence, 4),
                "priority": 0.58,
                "ttl_ms": 7000,
                "evidence_refs": [
                    f"consent:{person.consent_id}",
                    f"frame:{payload.get('source_frame_id') or 'unknown'}",
                ],
            }

        if pulse_enabled and "physiology" in person.scopes:
            face_bbox = _bounded_bbox(payload.get("face_bbox"))
            if face_bbox:
                result["bio_roi"] = {
                    "type": "bio_roi",
                    "schema_version": 1,
                    "session_id": str(payload.get("session_id") or "")[:160],
                    "source_frame_id": str(payload.get("source_frame_id") or ""),
                    "target_track_id": str(payload.get("target_track_id") or ""),
                    "person_id": person_id,
                    "display_name": person.display_name,
                    "face_bbox": face_bbox,
                    "rotation": int(payload.get("rotation") or 0),
                    "mirrored": bool(payload.get("mirrored")),
                    "identity_confidence": round(confidence, 4),
                    "consent_id": person.consent_id,
                    "signal": "rppg_experimental",
                    "persist": False,
                    "ttl_ms": 5000,
                }
        return result

    @staticmethod
    def project_anonymous_studio_pulse(
        payload: dict[str, Any],
        *,
        studio_release_id: str,
    ) -> dict[str, Any]:
        """Authorise a transient ROI for a code-validated studio run.

        The ROI deliberately carries no identity or profile data and is never
        persisted.  The release id is used only as the short-lived consent
        token required by the device bridge.
        """
        release_id = str(studio_release_id or "").strip()[:160]
        face_bbox = _bounded_bbox(payload.get("face_bbox"))
        if not release_id or not face_bbox:
            return {"status": "face_unavailable"}
        return {
            "status": "ready",
            "bio_roi": {
                "type": "bio_roi",
                "schema_version": 1,
                "session_id": str(payload.get("session_id") or "")[:160],
                "source_frame_id": str(payload.get("source_frame_id") or ""),
                "target_track_id": str(payload.get("target_track_id") or ""),
                "face_bbox": face_bbox,
                "rotation": int(payload.get("rotation") or 0),
                "mirrored": bool(payload.get("mirrored")),
                "consent_id": f"studio:{release_id}",
                "signal": "rppg_experimental",
                "persist": False,
                "identity_required": False,
                "ttl_ms": 5000,
            },
        }


def _normalise_person(raw: Any) -> ConsentedPerson:
    if not isinstance(raw, dict):
        raise ValueError("consented person entry must be an object")
    person_id = str(raw.get("person_id") or "").strip()
    display_name = str(raw.get("display_name") or "").strip()
    consent_id = str(raw.get("consent_id") or "").strip()
    signed_at = str(raw.get("signed_at") or "").strip()
    if not all((person_id, display_name, consent_id, signed_at)):
        raise ValueError(
            "consented person requires person_id/display_name/consent_id/signed_at"
        )
    if any(len(value) > 160 for value in (person_id, display_name, consent_id)):
        raise ValueError("consented person identity field exceeds bound")
    if raw.get("revoked") is True:
        raise ValueError(f"revoked consent must be removed: {person_id}")
    scopes_raw = raw.get("scopes")
    if not isinstance(scopes_raw, list):
        raise ValueError(f"consent scopes missing for {person_id}")
    scopes = frozenset(str(item).strip() for item in scopes_raw)
    if not scopes or not scopes <= ALLOWED_SCOPES:
        raise ValueError(f"invalid consent scopes for {person_id}")
    sources_raw = raw.get("public_sources") or []
    if not isinstance(sources_raw, list) or len(sources_raw) > MAX_SOURCES:
        raise ValueError(f"invalid public_sources for {person_id}")
    sources: list[dict[str, str]] = []
    for item in sources_raw:
        if not isinstance(item, dict):
            raise ValueError(f"invalid public source for {person_id}")
        provider = str(item.get("provider") or "").strip().lower()
        handle = str(item.get("handle") or "").strip()
        url = str(item.get("url") or "").strip()
        verified_at = str(item.get("verified_at") or "").strip()
        if (
            provider not in ALLOWED_PROVIDERS
            or not handle
            or not verified_at
            or not (url.startswith("https://") or url.startswith("http://"))
        ):
            raise ValueError(f"unverified public source for {person_id}")
        sources.append(
            {
                "provider": provider,
                "handle": handle[:120],
                "url": url[:500],
                "verified_at": verified_at[:64],
            }
        )
    return ConsentedPerson(
        person_id=person_id,
        display_name=display_name,
        consent_id=consent_id,
        signed_at=signed_at[:64],
        scopes=scopes,
        summary=str(raw.get("summary") or "").strip()[:500],
        sources=tuple(sources),
    )


def _bounded_bbox(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    try:
        x = max(0.0, min(1.0, float(raw.get("x"))))
        y = max(0.0, min(1.0, float(raw.get("y"))))
        w = max(0.0, min(1.0 - x, float(raw.get("w"))))
        h = max(0.0, min(1.0 - y, float(raw.get("h"))))
    except (TypeError, ValueError):
        return {}
    return (
        {"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)}
        if w > 0.0 and h > 0.0
        else {}
    )
