from __future__ import annotations

"""Bounded capability implementations for the isolated AR service.

No function in this module opens the memory database. Inputs are already-bounded
product snapshots and outputs are UI contracts or explicit adapter results.
Optional model/corpus integrations are loaded only after their feature is enabled.
"""

import html
import hashlib
import ipaddress
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_TEXT = 2_000
MAX_ACTIONS = 5
TRUE_VALUES = {"1", "true", "yes", "on"}


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _safe_id(value: Any, limit: int = 160) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or "").strip())
    return cleaned[:limit]


def _screen_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        w = float(value.get("w", value.get("width")))
        h = float(value.get("h", value.get("height")))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(lambda n: n == n and abs(n) != float("inf"), (x, y, w, h))):
        return None
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


@dataclass(frozen=True)
class ObjectAction:
    action_id: str
    label: str
    kind: str
    requires_confirmation: bool = False
    state_change: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "kind": self.kind,
            "requires_confirmation": self.requires_confirmation,
            "state_change": self.state_change,
        }


class ObjectActionRegistry:
    """Produces only actions backed by a known product or configured adapter."""

    def __init__(self, configured_devices: dict[str, Any] | None = None) -> None:
        self._devices = (
            dict(configured_devices)
            if configured_devices is not None
            else self._load_devices()
        )

    @staticmethod
    def _load_devices() -> dict[str, Any]:
        path = os.environ.get("MLOMEGA_AR_DEVICE_REGISTRY", "").strip()
        if not path:
            return {}
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("AR device registry must be an object")
        return raw

    def actions_for(self, snapshot: dict[str, Any]) -> list[ObjectAction]:
        actions: list[ObjectAction] = []
        entity_id = _safe_id(snapshot.get("entity_id"))
        label = _text(snapshot.get("label"), 160)
        if snapshot.get("manual_ref") or label:
            actions.append(ObjectAction("manual", "Manuel court", "manual"))
        if entity_id:
            actions.append(ObjectAction("history", "Historique", "history"))
        if _safe_id(snapshot.get("app_id")):
            actions.append(ObjectAction("open_app", "Ouvrir l’app", "open_app"))
        device = self._match_device(entity_id, label)
        if device:
            # Never expose a static registry state as current truth. The explicit
            # toggle reads Home Assistant before acting and reads it again before
            # the terminal UI receipt is emitted.
            actions.append(
                ObjectAction("toggle", "Marche / arrêt", "toggle", True, True)
            )
        return actions[:MAX_ACTIONS]

    def configured_device(self, entity_id: str, label: str) -> dict[str, Any] | None:
        return self._match_device(_safe_id(entity_id), _text(label, 160))

    def _match_device(self, entity_id: str, label: str) -> dict[str, Any] | None:
        for key in (entity_id, label.lower()):
            value = self._devices.get(key) if key else None
            if not isinstance(value, dict) or value.get("adapter") != "home_assistant":
                continue
            token_env = _safe_id(value.get("token_env"))
            if (
                _text(value.get("base_url"), 500)
                and _text(value.get("ha_entity_id"), 160)
                and token_env
                and os.environ.get(token_env, "")
            ):
                return dict(value)
        return None


def build_object_profile_card(
    payload: dict[str, Any],
    *,
    registry: ObjectActionRegistry,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("object snapshot must be an object")
    session_id = _safe_id(payload.get("session_id"))
    source_id = _safe_id(payload.get("source_frame_id"))
    track_id = _safe_id(payload.get("target_track_id"))
    focus_id = _safe_id(payload.get("focus_id"))
    entity_id = _safe_id(payload.get("entity_id"))
    label = _text(payload.get("label"), 160)
    bbox = _screen_bbox(payload.get("bbox"))
    if not session_id or not source_id or not (track_id or focus_id) or not label or bbox is None:
        raise ValueError("visible object requires session/frame/focus/label/bbox")
    if str(payload.get("visibility") or "visible") != "visible":
        raise ValueError("object profile cards require current visibility")

    actions = registry.actions_for(payload)
    facts = []
    category = _text(payload.get("category"), 80)
    device_labels = []
    for item in list(payload.get("device_labels") or [])[:3]:
        if not isinstance(item, dict):
            continue
        text = _text(item.get("label"), 80)
        try:
            score = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if text and 0.0 <= score <= 1.0:
            device_labels.append({"label": text, "confidence": round(score, 3)})
    brand = _text(payload.get("brand"), 80)
    model = _text(payload.get("model"), 120)
    if brand or model:
        facts.append(" ".join(part for part in (brand, model) if part))
    summary = _text(payload.get("summary"), 420)
    if not summary:
        summary = category or (
            f"ML Kit local : {device_labels[0]['label']}."
            if device_labels
            else "Objet reconnu dans la scène actuelle."
        )
    intent = {
        "type": "ui_intent",
        "contracts_version": "v19.0",
        "ui_intent_id": f"ar-object-{session_id}-{track_id or focus_id}",
        "producer": "visionrt",
        "source_frame_id": source_id,
        "target_track_id": track_id or None,
        "entity_id": entity_id or None,
        "component": "object_profile_card",
        "anchor": {"type": "screen_bbox", "bbox": bbox},
        "content": {
            "kind": "object_profile",
            "title": label,
            "category": category,
            "summary": summary,
            "facts": facts,
            "device_labels": device_labels,
            "manual_ref": _text(payload.get("manual_ref"), 500),
            "app_id": _safe_id(payload.get("app_id")),
            "actions": [action.payload() for action in actions],
            "visibility": "visible",
        },
        "truth_level": "observed",
        "confidence": max(0.0, min(float(payload.get("confidence") or 0.0), 1.0)),
        "priority": 0.82,
        "ttl_ms": 3_500,
        "ui_hint": {"focus": "object_profile", "interactive": bool(actions)},
        "evidence_refs": [
            item
            for item in (
                _text(payload.get("evidence_ref"), 500),
                f"frame:{source_id}",
            )
            if item
        ],
    }
    return intent


class HomeAssistantAdapter:
    """Minimal allowlisted Home Assistant REST adapter with terminal state check."""

    def execute(self, device: dict[str, Any], action: str) -> dict[str, Any]:
        base_url = str(device.get("base_url") or "").rstrip("/")
        entity = _text(device.get("ha_entity_id"), 160)
        token_env = _safe_id(device.get("token_env"))
        if not self._base_url_allowed(base_url):
            raise ValueError("home assistant base_url is not allowlisted")
        token = os.environ.get(token_env, "") if token_env else ""
        if not entity or not token:
            raise ValueError("home assistant entity/token is not configured")
        current = self._state(base_url, entity, token)
        target = "on" if action == "power_on" else "off"
        if action == "toggle":
            target = "off" if current == "on" else "on"
        if current == target:
            return {"status": "completed", "state": current, "changed": False}
        domain = entity.split(".", 1)[0]
        service = "turn_on" if target == "on" else "turn_off"
        self._request(
            f"{base_url}/api/services/{domain}/{service}",
            token,
            method="POST",
            body={"entity_id": entity},
        )
        final = self._state(base_url, entity, token)
        if final != target:
            raise RuntimeError(f"terminal state mismatch: expected {target}, got {final}")
        return {"status": "completed", "state": final, "changed": True}

    @staticmethod
    def _base_url_allowed(base_url: str) -> bool:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme == "https" and bool(parsed.hostname):
            return True
        if parsed.scheme != "http" or not parsed.hostname:
            return False
        host = parsed.hostname.casefold()
        if host == "localhost" or host.endswith(".local"):
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_loopback or address.is_private

    def _state(self, base_url: str, entity: str, token: str) -> str:
        data = self._request(
            f"{base_url}/api/states/{urllib.parse.quote(entity, safe='.')}",
            token,
            method="GET",
        )
        return _text(data.get("state"), 32).lower()

    @staticmethod
    def _request(
        url: str,
        token: str,
        *,
        method: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            raw = response.read(64_001)
        if len(raw) > 64_000:
            raise ValueError("home assistant response too large")
        parsed = json.loads(raw.decode("utf-8") or "{}")
        return parsed if isinstance(parsed, dict) else {}


def execute_object_action(
    payload: dict[str, Any],
    *,
    registry: ObjectActionRegistry,
    home_assistant: HomeAssistantAdapter | None = None,
) -> dict[str, Any]:
    action = _safe_id(payload.get("action_id"))
    entity_id = _safe_id(payload.get("entity_id"))
    label = _text(payload.get("label"), 160)
    if action not in {"manual", "history", "open_app", "power_on", "power_off", "toggle"}:
        raise ValueError("unknown object action")
    if action in {"power_on", "power_off", "toggle"}:
        if payload.get("confirmed") is not True:
            return {"status": "confirmation_required", "action_id": action}
        device = registry.configured_device(entity_id, label)
        if not device:
            raise ValueError("no configured device adapter")
        result = (home_assistant or HomeAssistantAdapter()).execute(device, action)
        return {
            "action_id": action,
            "label": label,
            "entity_id": entity_id or None,
            **result,
        }
    return {
        "status": "delegated",
        "action_id": action,
        "entity_id": entity_id or None,
        "label": label,
        "manual_ref": _text(payload.get("manual_ref"), 500),
        "app_id": _safe_id(payload.get("app_id")),
        "bbox": _screen_bbox(payload.get("bbox")),
    }


def clean_kiwix_extract(raw_html: str, *, limit: int = 520) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _text(html.unescape(text), limit)


class KiwixKnowledgeProvider:
    """Queries an operator-owned local Kiwix server; never the public network."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("MLOMEGA_KIWIX_URL", "")
        ).rstrip("/")

    @property
    def available(self) -> bool:
        return self.base_url.startswith(("http://127.0.0.1:", "http://localhost:"))

    def lookup(self, topic: str) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("local Kiwix endpoint is not configured")
        query = urllib.parse.quote(_text(topic, 160))
        url = f"{self.base_url}/search?pattern={query}"
        with urllib.request.urlopen(url, timeout=2.0) as response:
            raw = response.read(128_001)
        if len(raw) > 128_000:
            raise ValueError("Kiwix response too large")
        summary = clean_kiwix_extract(raw.decode("utf-8", errors="replace"))
        if not summary:
            raise LookupError("no local knowledge result")
        return {"title": _text(topic, 160), "summary": summary, "source": url}


class ContextualKnowledgeGate:
    def __init__(
        self,
        *,
        cooldown_s: float = 900.0,
        global_auto_cooldown_s: float = 90.0,
        provider: KiwixKnowledgeProvider | None = None,
    ) -> None:
        self.cooldown_s = max(30.0, float(cooldown_s))
        self.global_auto_cooldown_s = max(30.0, float(global_auto_cooldown_s))
        self.provider = provider or KiwixKnowledgeProvider()
        self._seen: dict[tuple[str, str], float] = {}
        self._last_auto_by_session: dict[str, float] = {}

    @property
    def available(self) -> bool:
        return self.provider.available

    def maybe_card(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        session_id = _safe_id(payload.get("session_id"))
        topic = _text(payload.get("topic"), 160)
        explicit = payload.get("explicit") is True
        novel = payload.get("novel") is True
        if not session_id or len(topic) < 3 or not (explicit or novel):
            return None
        key = (session_id, topic.casefold())
        now = time.monotonic()
        if (
            not explicit
            and now - self._last_auto_by_session.get(session_id, -1e12)
            < self.global_auto_cooldown_s
        ):
            return None
        if not explicit and now - self._seen.get(key, -1e12) < self.cooldown_s:
            return None
        result = self.provider.lookup(topic)
        self._seen[key] = now
        if not explicit:
            self._last_auto_by_session[session_id] = now
        return {
            "type": "ui_intent",
            "contracts_version": "v19.0",
            "ui_intent_id": (
                f"ar-knowledge-{session_id}-"
                f"{hashlib.sha256('|'.join(key).encode('utf-8')).hexdigest()[:16]}"
            ),
            "producer": "ultralive",
            "component": "context_card",
            "anchor": {"type": "head_locked", "side": "right"},
            "content": {
                "kind": "contextual_knowledge",
                "title": result["title"],
                "text": result["summary"],
                "source": result["source"],
            },
            "truth_level": "remembered",
            "confidence": 1.0,
            "priority": 0.45,
            "ttl_ms": 12_000,
            "ui_hint": {"dismissible": True},
            "evidence_refs": [result["source"]],
        }
