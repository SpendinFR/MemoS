from __future__ import annotations

"""Loopback-only foundation service for optional augmented-reality modules."""

import argparse
import json
import os
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on"}
KNOWN_FEATURES = (
    "object_menus",
    "action_recognition",
    "semantic_sound",
    "contextual_knowledge",
    "enhanced_zoom",
    "ar_measurement",
)
MEMORY_ACCESS = {
    # Future modules consume existing product APIs; this isolated service never
    # opens memory.db or invents a parallel memory writer.
    "object_menus": "read_worldbrain_memoryquery",
    "action_recognition": "validated_event_writer_only",
    "semantic_sound": "validated_event_writer_only",
    "contextual_knowledge": "read_hotcontext_no_personal_write",
    "enhanced_zoom": "none",
    "ar_measurement": "none",
}
MAX_BODY_BYTES = 32_768
MAX_SESSIONS = 16


def normalise_preferences(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported schema_version")
    session_id = str(payload.get("session_id") or "").strip()
    person_id = str(payload.get("person_id") or "").strip()
    if not session_id or len(session_id) > 160:
        raise ValueError("session_id is required and bounded")
    if not person_id or len(person_id) > 160:
        raise ValueError("person_id is required and bounded")
    master = payload.get("master_enabled")
    features = payload.get("features")
    if not isinstance(master, bool) or not isinstance(features, dict):
        raise ValueError("master_enabled/features have invalid types")
    unknown = sorted(set(features) - set(KNOWN_FEATURES))
    if unknown:
        raise ValueError("unknown feature(s): " + ",".join(unknown))
    clean_features: dict[str, bool] = {}
    for feature in KNOWN_FEATURES:
        value = features.get(feature, False)
        if not isinstance(value, bool):
            raise ValueError(f"feature {feature} must be boolean")
        clean_features[feature] = value
    return {
        "schema_version": 1,
        "session_id": session_id,
        "person_id": person_id,
        "master_enabled": master,
        "features": clean_features,
        "probe": payload.get("probe") if isinstance(payload.get("probe"), dict) else {},
        "sent_at_ms": int(payload.get("sent_at_ms") or 0),
    }


class PreferenceState:
    """Bounded, in-memory session preferences. Never writes the memory DB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def apply(self, payload: Any) -> dict[str, Any]:
        clean = normalise_preferences(payload)
        session_id = clean["session_id"]
        with self._lock:
            self._sessions.pop(session_id, None)
            self._sessions[session_id] = clean
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        # Foundation lot: no perception module is implemented yet. Preferences
        # are accepted, but active_features remains honestly empty.
        return {
            "status": "accepted",
            "detail": "foundation ready; perception modules not installed",
            "active_features": [],
        }

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


def capability_manifest(*, enabled: bool, session_count: int = 0) -> dict[str, Any]:
    return {
        "service": "mlomega-augmented-reality",
        "schema_version": 1,
        "enabled": bool(enabled),
        "status": "ready" if enabled else "disabled",
        "session_count": int(session_count),
        "capabilities": {feature: False for feature in KNOWN_FEATURES},
        "memory_access": dict(MEMORY_ACCESS),
        "writes_memory_db": False,
    }


def build_handler(state: PreferenceState, *, enabled: bool) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MLOmegaAugmentedReality/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/health", "/v1/capabilities"}:
                self._json(404, {"status": "not_found"})
                return
            self._json(
                200,
                capability_manifest(enabled=enabled, session_count=state.count()),
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/preferences":
                self._json(404, {"status": "not_found"})
                return
            if not enabled:
                self._json(503, {"status": "disabled"})
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise ValueError("invalid request size")
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                self._json(200, state.apply(payload))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._json(400, {"status": "rejected", "detail": str(exc)[:300]})

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    enabled = os.environ.get("MLOMEGA_AUGMENTED_REALITY", "0").strip().lower() in TRUE_VALUES
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("the augmented-reality service is loopback-only")
    if args.probe:
        print(json.dumps(capability_manifest(enabled=enabled), ensure_ascii=False))
        return 0
    if not enabled:
        print("MLOMEGA_AUGMENTED_REALITY is off; service not started")
        return 3
    state = PreferenceState()
    server = ThreadingHTTPServer((args.host, args.port), build_handler(state, enabled=True))
    print(f"augmented-reality ready on http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
