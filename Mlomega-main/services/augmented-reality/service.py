from __future__ import annotations

"""Loopback-only foundation service for optional augmented-reality modules."""

import argparse
import json
import os
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from capabilities import (  # noqa: E402
    ContextualKnowledgeGate,
    ObjectActionRegistry,
    build_object_profile_card,
    execute_object_action,
)
from consented_profiles import ConsentedProfileRegistry  # noqa: E402
from public_profile_discovery import PublicProfileDiscovery  # noqa: E402

TRUE_VALUES = {"1", "true", "yes", "on"}
KNOWN_FEATURES = (
    "object_menus",
    "action_recognition",
    "semantic_sound",
    "contextual_knowledge",
    "enhanced_zoom",
    "ar_measurement",
    "street_navigation",
    "world_labels",
    "persistent_anchors",
    "depth_occlusion",
    "world_styling",
    "trajectory_forecast",
    "spatial_keyboard",
    "event_vision",
    "ballistic_preview",
    "radio_field",
    "consented_people",
    "pulse_aura",
    "automatic_world_fx",
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
    "street_navigation": "none",
    "world_labels": "read_visionrt_worldbrain_no_write",
    "persistent_anchors": "read_worldbrain_no_write",
    "depth_occlusion": "none",
    "world_styling": "none",
    "trajectory_forecast": "none",
    "spatial_keyboard": "none",
    "event_vision": "none",
    "ballistic_preview": "none",
    "radio_field": "none",
    "consented_people": "read_enrolled_identity_and_explicit_consent_registry",
    "pulse_aura": "none_no_biometric_persistence",
    "automatic_world_fx": "none_ephemeral_device_only",
}
MAX_BODY_BYTES = 262_144
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

    def __init__(
        self,
        *,
        object_registry: ObjectActionRegistry | None = None,
        knowledge: ContextualKnowledgeGate | None = None,
        profile_registry: ConsentedProfileRegistry | None = None,
        public_discovery: PublicProfileDiscovery | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.object_registry = object_registry or ObjectActionRegistry()
        self.knowledge = knowledge or ContextualKnowledgeGate()
        self.profile_registry = profile_registry or ConsentedProfileRegistry.from_env()
        self.public_discovery = public_discovery or PublicProfileDiscovery()

    def capabilities(self) -> dict[str, bool]:
        return {
            "object_menus": True,
            "action_recognition": False,
            # Provider code is installed. Per-session activation additionally
            # requires the device probe to confirm the provisioned YAMNet file.
            "semantic_sound": True,
            "contextual_knowledge": bool(self.knowledge.available),
            # Base crop is device-local and does not need this service. The
            # optional super-resolution provider is not advertised until installed.
            "enhanced_zoom": False,
            # Measurement remains unavailable until the active XR provider exposes
            # valid depth/intrinsics/pose on the physical gate.
            "ar_measurement": False,
            # Lot 2 renderers exist, but these capabilities remain unavailable
            # until the physical provider proves calibrated pose/VPS/depth.
            "street_navigation": False,
            # World labels are 3D-only: no screen-space fallback. The provider
            # must prove calibrated tracking-local poses before activation.
            "world_labels": False,
            "persistent_anchors": False,
            "depth_occlusion": False,
            "world_styling": False,
            # Lot 3 renderers/contracts are installed, but none is advertised
            # before its real pose/depth/hand/radio producer passes hardware.
            "trajectory_forecast": False,
            "spatial_keyboard": False,
            "event_vision": False,
            "ballistic_preview": False,
            "radio_field": False,
            "consented_people": bool(
                self.profile_registry.supports("profile_card")
                or self.public_discovery.available
            ),
            "pulse_aura": self.profile_registry.supports("physiology"),
            # Rendered entirely on the XREAL device after a proven Depth hit.
            "automatic_world_fx": False,
        }

    def apply(self, payload: Any) -> dict[str, Any]:
        clean = normalise_preferences(payload)
        session_id = clean["session_id"]
        with self._lock:
            self._sessions.pop(session_id, None)
            self._sessions[session_id] = clean
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        available = self.capabilities()
        available = self._available_for(clean, available)
        active = [
            feature
            for feature in KNOWN_FEATURES
            if clean["master_enabled"]
            and clean["features"].get(feature) is True
            and available.get(feature) is True
        ]
        return {
            "status": "ready",
            "detail": "enabled features are backed by installed providers",
            "active_features": active,
        }

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def feature_active(self, session_id: str, feature: str) -> bool:
        with self._lock:
            state = self._sessions.get(str(session_id))
            if not state:
                return False
            return bool(
                state.get("master_enabled")
                and state.get("features", {}).get(feature)
                and self._available_for(state).get(feature)
            )

    def _available_for(
        self,
        state: dict[str, Any],
        base: dict[str, bool] | None = None,
    ) -> dict[str, bool]:
        available = dict(base or self.capabilities())
        probe = state.get("probe") if isinstance(state.get("probe"), dict) else {}
        semantic_model = probe.get(
            "semantic_sound_model_available",
            probe.get("SemanticSoundModelAvailable", False),
        )
        available["semantic_sound"] = bool(
            available.get("semantic_sound") and semantic_model is True
        )
        return available

    def object_card(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        session_id = str(payload.get("session_id") or "")
        if not self.feature_active(session_id, "object_menus"):
            raise PermissionError("object_menus is not active for this session")
        return build_object_profile_card(payload, registry=self.object_registry)

    def object_action(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        session_id = str(payload.get("session_id") or "")
        if not self.feature_active(session_id, "object_menus"):
            raise PermissionError("object_menus is not active for this session")
        return execute_object_action(payload, registry=self.object_registry)

    def contextual_knowledge(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        session_id = str(payload.get("session_id") or "")
        if not self.feature_active(session_id, "contextual_knowledge"):
            raise PermissionError("contextual_knowledge is not active for this session")
        return self.knowledge.maybe_card(payload)

    def consented_person(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        session_id = str(payload.get("session_id") or "")
        profile_enabled = self.feature_active(session_id, "consented_people")
        pulse_enabled = self.feature_active(session_id, "pulse_aura")
        if not profile_enabled and not pulse_enabled:
            raise PermissionError(
                "consented_people/pulse_aura is not active for this session"
            )
        result = self.profile_registry.project(
            payload,
            profile_enabled=profile_enabled,
            pulse_enabled=pulse_enabled,
        )
        if (
            result.get("status") == "no_consent"
            and profile_enabled
            and payload.get("face_jpeg_b64")
        ):
            return self.public_discovery.discover(payload)
        return result


def capability_manifest(
    *,
    enabled: bool,
    session_count: int = 0,
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "service": "mlomega-augmented-reality",
        "schema_version": 1,
        "enabled": bool(enabled),
        "status": "ready" if enabled else "disabled",
        "session_count": int(session_count),
        "capabilities": capabilities or {feature: False for feature in KNOWN_FEATURES},
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
                capability_manifest(
                    enabled=enabled,
                    session_count=state.count(),
                    capabilities=state.capabilities() if enabled else None,
                ),
            )

        def do_POST(self) -> None:  # noqa: N802
            routes = {
                "/v1/preferences": state.apply,
                "/v1/object-card": state.object_card,
                "/v1/object-action": state.object_action,
                "/v1/contextual-knowledge": state.contextual_knowledge,
                "/v1/consented-person": state.consented_person,
            }
            handler = routes.get(self.path)
            if handler is None:
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
                result = handler(payload)
                self._json(
                    200,
                    {"status": "no_result"} if result is None else result,
                )
            except PermissionError as exc:
                self._json(409, {"status": "inactive", "detail": str(exc)[:300]})
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._json(400, {"status": "rejected", "detail": str(exc)[:300]})
            except Exception as exc:
                # Optional providers (Kiwix/Home Assistant) may disappear after
                # readiness. Return a bounded, explicit terminal result instead
                # of dropping the HTTP connection and making the UI look stuck.
                self._json(
                    503,
                    {
                        "status": "unavailable",
                        "detail": (
                            f"{exc.__class__.__name__}: {str(exc)}"
                        )[:300],
                    },
                )

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
        probe_state = PreferenceState() if enabled else None
        print(json.dumps(
            capability_manifest(
                enabled=enabled,
                capabilities=probe_state.capabilities() if probe_state else None,
            ),
            ensure_ascii=False,
        ))
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
