from __future__ import annotations

"""Non-blocking bridge to the isolated augmented-reality service.

The default path is intentionally inert: when ``MLOMEGA_AUGMENTED_REALITY`` is
not true, constructing the bridge creates no executor, thread or network call.
"""

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


TRUE_VALUES = {"1", "true", "yes", "on"}
KNOWN_FEATURES = {
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
}
MAX_PREFERENCES_BYTES = 32_768
MAX_FEATURE_REQUEST_BYTES = 262_144


class AugmentedRealityBridge:
    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str = "http://127.0.0.1:8791",
        timeout_s: float = 0.75,
        public_lookup_timeout_s: float = 55.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.base_url = str(base_url).rstrip("/")
        self.timeout_s = max(0.1, min(float(timeout_s), 3.0))
        self.public_lookup_timeout_s = max(
            5.0, min(float(public_lookup_timeout_s), 70.0)
        )
        self._executor: ThreadPoolExecutor | None = None
        self._public_executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._active_features: set[str] = set()
        self._inflight: set[str] = set()
        self._metrics = {
            "enabled": self.enabled,
            "submitted": 0,
            "accepted": 0,
            "failed": 0,
            "rejected": 0,
            "dropped_busy": 0,
            "object_cards": 0,
            "object_actions": 0,
            "knowledge_cards": 0,
            "person_profiles": 0,
        }
        if self.enabled:
            self._validate_loopback_endpoint()
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="mlomega-augmented-reality"
            )
            # A consented public lookup may spend up to 12 s in Web Detection and
            # 35 s in Sherlock.  It must never block preferences, Kiwix or object
            # cards on the regular low-latency worker.
            self._public_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="mlomega-augmented-public"
            )

    @classmethod
    def from_env(cls) -> "AugmentedRealityBridge":
        return cls(
            enabled=os.environ.get("MLOMEGA_AUGMENTED_REALITY", "0")
            .strip()
            .lower()
            in TRUE_VALUES,
            base_url=os.environ.get(
                "MLOMEGA_AUGMENTED_REALITY_URL", "http://127.0.0.1:8791"
            ),
            timeout_s=float(
                os.environ.get("MLOMEGA_AUGMENTED_REALITY_TIMEOUT_S", "0.75")
            ),
            public_lookup_timeout_s=float(
                os.environ.get("MLOMEGA_AR_PUBLIC_LOOKUP_TIMEOUT_S", "55")
            ),
        )

    @property
    def worker_created(self) -> bool:
        """Diagnostic used by the mode-OFF non-regression gate."""

        return self._executor is not None

    def submit_preferences(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        person_id: str,
        on_status: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        try:
            normalised = normalise_preferences(
                payload, session_id=session_id, person_id=person_id
            )
        except ValueError as exc:
            self._increment("rejected")
            status = {"status": "rejected", "detail": str(exc)[:300]}
            if on_status is not None:
                on_status(status)
            return status

        self._increment("submitted")
        if not self.enabled or self._executor is None:
            status = {
                "status": "disabled",
                "detail": "MLOMEGA_AUGMENTED_REALITY is off",
            }
            if on_status is not None:
                on_status(status)
            return status

        self._executor.submit(self._post_preferences, normalised, on_status)
        return {"status": "pending", "detail": "preference update queued"}

    def feature_active(self, feature: str) -> bool:
        with self._lock:
            return str(feature) in self._active_features

    def submit_object_focus(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        on_intent: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        return self._submit_feature(
            "object_card",
            "object_menus",
            "/v1/object-card",
            {"session_id": session_id, **dict(payload or {})},
            lambda result: self._deliver_ui_result(
                result, on_intent, metric="object_cards"
            ),
        )

    def submit_object_action(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        on_result: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        return self._submit_feature(
            "object_action",
            "object_menus",
            "/v1/object-action",
            {"session_id": session_id, **dict(payload or {})},
            lambda result: self._deliver_result(
                result, on_result, metric="object_actions"
            ),
        )

    def submit_contextual_knowledge(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        on_intent: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        topic = str((payload or {}).get("topic") or "").strip()
        key = "knowledge:" + topic.casefold()[:120]
        return self._submit_feature(
            key,
            "contextual_knowledge",
            "/v1/contextual-knowledge",
            {"session_id": session_id, **dict(payload or {})},
            lambda result: self._deliver_ui_result(
                result, on_intent, metric="knowledge_cards"
            ),
        )

    def submit_consented_person(
        self,
        payload: dict[str, Any],
        *,
        session_id: str,
        on_result: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        if not (
            self.feature_active("consented_people")
            or self.feature_active("pulse_aura")
        ):
            return {"status": "inactive", "feature": "consented_people"}
        person_id = str((payload or {}).get("person_id") or "").strip()
        track_id = str((payload or {}).get("target_track_id") or "").strip()
        return self._submit_feature(
            f"consented-person:{person_id}:{track_id}",
            (
                "consented_people"
                if self.feature_active("consented_people")
                else "pulse_aura"
            ),
            "/v1/consented-person",
            {"session_id": session_id, **dict(payload or {})},
            lambda result: self._deliver_result(
                result, on_result, metric="person_profiles"
            ),
            executor=self._public_executor,
            request_timeout_s=self.public_lookup_timeout_s,
        )

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._metrics)

    def close(self) -> None:
        executor = self._executor
        public_executor = self._public_executor
        self._executor = None
        self._public_executor = None
        with self._lock:
            self._active_features.clear()
            self._inflight.clear()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if public_executor is not None:
            public_executor.shutdown(wait=False, cancel_futures=True)

    def _post_preferences(
        self,
        payload: dict[str, Any],
        on_status: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        try:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            request = urllib.request.Request(
                self.base_url + "/v1/preferences",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read(MAX_PREFERENCES_BYTES + 1)
            if len(raw) > MAX_PREFERENCES_BYTES:
                raise ValueError("augmented-reality response exceeds size limit")
            decoded = json.loads(raw.decode("utf-8"))
            status = {
                "status": str(decoded.get("status") or "accepted"),
                "detail": str(decoded.get("detail") or ""),
                "active_features": list(decoded.get("active_features") or []),
            }
            with self._lock:
                self._active_features = {
                    str(item)
                    for item in status["active_features"]
                    if str(item) in KNOWN_FEATURES
                }
            self._increment("accepted")
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            self._increment("failed")
            status = {"status": "unavailable", "detail": str(exc)[:300]}
        if on_status is not None:
            on_status(status)

    def _submit_feature(
        self,
        key: str,
        feature: str,
        path: str,
        payload: dict[str, Any],
        callback: Callable[[dict[str, Any]], None],
        executor: ThreadPoolExecutor | None = None,
        request_timeout_s: float | None = None,
    ) -> dict[str, Any]:
        selected_executor = executor or self._executor
        if not self.enabled or selected_executor is None:
            return {"status": "disabled"}
        if not self.feature_active(feature):
            return {"status": "inactive", "feature": feature}
        with self._lock:
            if key in self._inflight or len(self._inflight) >= 4:
                self._metrics["dropped_busy"] += 1
                return {"status": "dropped_busy", "feature": feature}
            self._inflight.add(key)
            self._metrics["submitted"] += 1

        def run() -> None:
            try:
                callback(
                    self._post_json(
                        path,
                        payload,
                        timeout_s=request_timeout_s,
                    )
                )
                self._increment("accepted")
            except Exception as exc:
                self._increment("failed")
                callback({"status": "unavailable", "detail": str(exc)[:300]})
            finally:
                with self._lock:
                    self._inflight.discard(key)

        selected_executor.submit(run)
        return {"status": "pending", "feature": feature}

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(body) > MAX_FEATURE_REQUEST_BYTES:
            raise ValueError("augmented-reality request exceeds size limit")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(
            request,
            timeout=self.timeout_s if timeout_s is None else timeout_s,
        ) as response:
            raw = response.read(MAX_PREFERENCES_BYTES + 1)
        if len(raw) > MAX_PREFERENCES_BYTES:
            raise ValueError("augmented-reality response exceeds size limit")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("augmented-reality response must be an object")
        return result

    def _deliver_ui_result(
        self,
        result: dict[str, Any],
        callback: Callable[[dict[str, Any]], None],
        *,
        metric: str,
    ) -> None:
        if result.get("type") != "ui_intent":
            return
        self._increment(metric)
        callback(result)

    def _deliver_result(
        self,
        result: dict[str, Any],
        callback: Callable[[dict[str, Any]], None],
        *,
        metric: str,
    ) -> None:
        self._increment(metric)
        callback(result)

    def _validate_loopback_endpoint(self) -> None:
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError(
                "augmented-reality service must use an HTTP loopback endpoint"
            )

    def _increment(self, key: str) -> None:
        with self._lock:
            self._metrics[key] = int(self._metrics[key]) + 1


def normalise_preferences(
    payload: dict[str, Any], *, session_id: str, person_id: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("preferences payload must be an object")
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported augmented-reality schema_version")
    master = payload.get("master_enabled")
    if not isinstance(master, bool):
        raise ValueError("master_enabled must be boolean")
    features = payload.get("features")
    if not isinstance(features, dict):
        raise ValueError("features must be an object")
    unknown = sorted(set(features) - KNOWN_FEATURES)
    if unknown:
        raise ValueError("unknown augmented-reality feature(s): " + ",".join(unknown))
    bounded: dict[str, bool] = {}
    for feature in sorted(KNOWN_FEATURES):
        value = features.get(feature, False)
        if not isinstance(value, bool):
            raise ValueError(f"feature {feature} must be boolean")
        bounded[feature] = value
    probe = payload.get("probe")
    if probe is not None and not isinstance(probe, dict):
        raise ValueError("probe must be an object or null")
    result = {
        "schema_version": 1,
        "session_id": str(session_id)[:160],
        "person_id": str(person_id)[:160],
        "master_enabled": master,
        "features": bounded,
        "probe": probe or {},
        "sent_at_ms": int(payload.get("sent_at_ms") or 0),
    }
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_PREFERENCES_BYTES:
        raise ValueError("preferences payload exceeds size limit")
    return result
