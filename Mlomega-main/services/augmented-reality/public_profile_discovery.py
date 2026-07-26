from __future__ import annotations

"""Real, opt-in Web profile discovery for a filmed unknown face.

Google Cloud Vision Web Detection supplies matching pages/entities for the
actual face crop.  Sherlock may then expand a username already present in those
results.  Neither tool is treated as proof of identity: the resulting card is a
PROBABLE candidate and never writes to the face gallery or memory.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Callable


MAX_IMAGE_BYTES = 180_000
MAX_WEB_RESULTS = 8
SOCIAL_HOSTS = {
    "github.com",
    "instagram.com",
    "linkedin.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}


class PublicProfileDiscovery:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        release_id: str | None = None,
        opener: Callable[..., Any] | None = None,
        sherlock_command: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.environ.get("MLOMEGA_GOOGLE_VISION_API_KEY", "")
        ).strip()
        self.release_id = (
            release_id
            if release_id is not None
            else os.environ.get("MLOMEGA_AR_STUDIO_RELEASE_ID", "")
        ).strip()
        self._opener = opener or urllib.request.urlopen
        configured = (
            sherlock_command
            if sherlock_command is not None
            else os.environ.get("MLOMEGA_SHERLOCK_COMMAND", "")
        ).strip()
        self.sherlock_command = configured or (shutil.which("sherlock") or "")

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.release_id)

    def discover(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            return {
                "status": "unavailable",
                "detail": "Google Vision key or studio release id is missing",
            }
        encoded = str(payload.get("face_jpeg_b64") or "")
        try:
            image = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("face_jpeg_b64 is invalid") from exc
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise ValueError("face image is empty or exceeds bound")
        detection = self._detect_web(image)
        pages = detection.get("pagesWithMatchingImages") or []
        entities = detection.get("webEntities") or []
        labels = detection.get("bestGuessLabels") or []
        sources = _normalise_pages(pages)
        candidate = _best_candidate(labels, entities, sources)
        handles = _handles_from_sources(sources)
        if self.sherlock_command and handles:
            sources = _merge_sources(
                sources,
                self._run_sherlock(handles[0]),
            )
        score = max(
            [float(item.get("score") or 0.0) for item in entities[:10]]
            or [0.0]
        )
        confidence = min(0.69, max(0.25, score))
        if not candidate and not sources:
            return {"status": "no_match", "release_id": self.release_id}
        return {
            "status": "candidate",
            "profile_intent": {
                "type": "ui_intent",
                "contracts_version": "v19.0",
                "ui_intent_id": (
                    f"web-profile:{payload.get('session_id')}:"
                    f"{payload.get('target_track_id')}"
                ),
                "producer": "ultralive",
                "source_frame_id": str(payload.get("source_frame_id") or ""),
                "target_track_id": str(payload.get("target_track_id") or ""),
                "entity_id": str(payload.get("entity_id") or ""),
                "component": "person_profile_card",
                "anchor": {
                    "type": "track",
                    "bbox": payload.get("person_bbox") or {},
                },
                "content": {
                    "kind": "public_web_candidate",
                    "name": candidate or "Candidat Web",
                    "summary": (
                        "Correspondance Web à confirmer — aucune identité "
                        "n'est écrite en mémoire."
                    ),
                    "public_sources": sources[:MAX_WEB_RESULTS],
                    "identity_method": "google_vision_web_detection",
                    "identity_confidence": round(confidence, 4),
                    "release_id": self.release_id,
                    "requires_confirmation": True,
                },
                "truth_level": "probable",
                "confidence": round(confidence, 4),
                "priority": 0.55,
                "ttl_ms": 12000,
                "evidence_refs": [
                    f"studio-release:{self.release_id}",
                    f"frame:{payload.get('source_frame_id') or 'unknown'}",
                ],
            },
        }

    def _detect_web(self, image: bytes) -> dict[str, Any]:
        body = json.dumps(
            {
                "requests": [
                    {
                        "image": {"content": base64.b64encode(image).decode("ascii")},
                        "features": [
                            {"type": "WEB_DETECTION", "maxResults": MAX_WEB_RESULTS}
                        ],
                    }
                ]
            },
            separators=(",", ":"),
        ).encode("utf-8")
        url = (
            "https://vision.googleapis.com/v1/images:annotate?key="
            + urllib.parse.quote(self.api_key, safe="")
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with self._opener(request, timeout=12.0) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Google Vision response exceeds bound")
        decoded = json.loads(raw.decode("utf-8"))
        responses = decoded.get("responses") if isinstance(decoded, dict) else None
        if not isinstance(responses, list) or not responses:
            raise ValueError("Google Vision returned no response")
        first = responses[0]
        if isinstance(first, dict) and first.get("error"):
            raise RuntimeError(
                str((first.get("error") or {}).get("message") or "Vision error")[:300]
            )
        web = first.get("webDetection") if isinstance(first, dict) else None
        return web if isinstance(web, dict) else {}

    def _run_sherlock(self, handle: str) -> list[dict[str, str]]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{2,64}", handle):
            return []
        try:
            completed = subprocess.run(
                [
                    self.sherlock_command,
                    handle,
                    "--print-found",
                    "--no-color",
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        urls = re.findall(r"https?://[^\s\]]+", completed.stdout or "")
        return [
            {
                "provider": urllib.parse.urlparse(url).netloc.lower()[:80],
                "handle": handle,
                "url": url[:500],
                "verification": "username_only",
            }
            for url in urls[:MAX_WEB_RESULTS]
        ]


def _normalise_pages(pages: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in pages if isinstance(pages, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        parsed = urllib.parse.urlparse(url)
        out.append(
            {
                "provider": parsed.netloc.lower()[:80],
                "handle": _handle_from_url(url),
                "url": url[:500],
                "verification": "matching_image_page",
            }
        )
        if len(out) >= MAX_WEB_RESULTS:
            break
    return out


def _best_candidate(
    labels: Any,
    entities: Any,
    sources: list[dict[str, str]],
) -> str:
    for item in labels if isinstance(labels, list) else []:
        label = str(item.get("label") or "").strip() if isinstance(item, dict) else ""
        if label and len(label) <= 120:
            return label
    for item in entities if isinstance(entities, list) else []:
        description = (
            str(item.get("description") or "").strip()
            if isinstance(item, dict)
            else ""
        )
        if description and len(description.split()) >= 2 and len(description) <= 120:
            return description
    return sources[0]["handle"] if sources and sources[0].get("handle") else ""


def _handle_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if host in SOCIAL_HOSTS and parts:
        if host == "youtube.com" and parts[0] in {"watch", "channel", "c"}:
            return parts[-1][:64]
        return parts[0].lstrip("@")[:64]
    return ""


def _handles_from_sources(sources: list[dict[str, str]]) -> list[str]:
    return list(
        dict.fromkeys(
            source["handle"]
            for source in sources
            if source.get("handle")
        )
    )


def _merge_sources(
    first: list[dict[str, str]],
    second: list[dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in [*first, *second]:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
        if len(out) >= MAX_WEB_RESULTS:
            break
    return out
