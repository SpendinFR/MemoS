from __future__ import annotations

"""Explicit, bounded live contextual-assistance session.

This state machine performs no inference and opens no database. It only retains a
small rolling transcript while the wearer has explicitly activated the mode, then
submits it to the isolated AR service. Stopping or 15 minutes of inactivity clears
the buffer immediately.
"""

import re
import time
import uuid
from collections import deque
from typing import Any, Callable


_CONTROL = re.compile(
    r"\b(?:mode|assistance|aide)\s+(?:juridique|contexte|contextuelle)\b",
    re.IGNORECASE,
)


class ContextualAssistSession:
    def __init__(
        self,
        *,
        bridge: Any,
        session_id: str,
        emit_ui_intent: Callable[[dict[str, Any]], Any],
        inactivity_s: float = 900.0,
        cooldown_s: float = 6.0,
    ) -> None:
        self.bridge = bridge
        self.session_id = str(session_id)
        self.emit_ui_intent = emit_ui_intent
        self.inactivity_s = max(60.0, min(float(inactivity_s), 1800.0))
        self.cooldown_s = max(3.0, min(float(cooldown_s), 30.0))
        self.active = False
        self.profile = "legal"
        self._turns: deque[str] = deque(maxlen=8)
        self._last_activity = 0.0
        self._next_submit = 0.0

    def start(self, profile: str = "legal") -> dict[str, Any]:
        selected = "legal" if str(profile).strip().lower() != "social" else "social"
        if self.bridge is None or not self.bridge.feature_active("legal_context"):
            return self._card(
                "ASSISTANCE NON CONFIGURÉE",
                "Le corpus France global n’est pas joignable sur ce profil.",
                "context_assist_unavailable",
                confidence=1.0,
            )
        self.active = True
        self.profile = selected
        self._turns.clear()
        self._last_activity = time.monotonic()
        self._next_submit = self._last_activity
        return self._card(
            "AIDE CONTEXTUELLE ACTIVE",
            "Écoute bornée active. Je citerai la source et distinguerai faits, prudence et incertitude. Dis « arrête le mode juridique » pour couper.",
            "context_assist_started",
            confidence=1.0,
        )

    def stop(self) -> dict[str, Any]:
        was_active = self.active
        self.active = False
        self._turns.clear()
        return self._card(
            "AIDE CONTEXTUELLE ARRÊTÉE",
            "L’écoute contextuelle temporaire est coupée."
            if was_active
            else "Le mode était déjà arrêté.",
            "context_assist_stopped",
            confidence=1.0,
        )

    def ingest(self, text: str) -> dict[str, Any]:
        clean = " ".join(str(text or "").split())[:500]
        now = time.monotonic()
        if not self.active:
            return {"status": "inactive"}
        if now - self._last_activity > self.inactivity_s:
            intent = self.stop()
            intent["content"]["text"] = (
                "Le mode s’est arrêté automatiquement après inactivité."
            )
            self.emit_ui_intent(intent)
            return {"status": "expired"}
        self._last_activity = now
        if len(clean) < 5 or _CONTROL.search(clean):
            return {"status": "ignored_control"}
        self._turns.append(clean)
        if now < self._next_submit:
            return {"status": "cooldown"}
        self._next_submit = now + self.cooldown_s
        return self.bridge.submit_context_assist(
            {
                "profile": self.profile,
                "current_turn": clean,
                "recent_turns": list(self._turns),
                "explicit_session": True,
            },
            session_id=self.session_id,
            on_intent=self.emit_ui_intent,
        )

    def _card(
        self,
        title: str,
        text: str,
        kind: str,
        *,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "type": "ui_intent",
            "contracts_version": "v19.0",
            "ui_intent_id": str(uuid.uuid4()),
            "producer": "ultralive",
            "component": "context_card",
            "anchor": {"type": "head_locked", "side": "right"},
            "content": {
                "kind": kind,
                "title": title,
                "text": text,
                "memory_write": False,
            },
            "truth_level": "observed",
            "confidence": confidence,
            "priority": 0.82,
            "ttl_ms": 9000,
            "ui_hint": {"dismissible": True},
            "evidence_refs": ["device:explicit-context-assist"],
        }
