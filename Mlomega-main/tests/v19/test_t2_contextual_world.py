from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


overlay_mod = _load(
    "test_t2_contextual_overlays",
    "services/augmented-reality/contextual_overlays.py",
)
service_mod = _load(
    "test_t2_augmented_service",
    "services/augmented-reality/service.py",
)
assist_mod = _load(
    "test_t2_contextual_assist",
    "services/live-pc/contextual_assist.py",
)
router_mod = _load(
    "test_t2_intent_router",
    "services/live-pc/intent_router.py",
)
bridge_mod = _load(
    "test_t2_augmented_bridge",
    "services/live-pc/augmented_reality_bridge.py",
)


class _Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self.raw[:limit]


def _location(**extra):
    return {
        "session_id": "t2-session",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "horizontal_accuracy_m": 8.0,
        **extra,
    }


def test_weather_is_opt_in_bounded_and_cached(tmp_path):
    calls = []

    def opener(url, timeout):
        calls.append((url, timeout))
        return _Response(
            {
                "latitude": 48.86,
                "longitude": 2.35,
                "timezone": "Europe/Paris",
                "current": {
                    "time": "2026-07-26T12:00",
                    "temperature_2m": 24.1,
                    "apparent_temperature": 25.0,
                    "precipitation": 0.0,
                    "weather_code": 1,
                    "wind_speed_10m": 9.0,
                },
                "current_units": {
                    "temperature_2m": "°C",
                    "apparent_temperature": "°C",
                    "precipitation": "mm",
                    "weather_code": "wmo code",
                    "wind_speed_10m": "km/h",
                },
            }
        )

    provider = overlay_mod.OpenMeteoWeatherProvider(
        cache_path=tmp_path / "weather.json",
        opener=opener,
    )
    first = provider.card(_location())
    second = provider.card(_location())

    assert first["component"] == "context_card"
    assert first["content"]["source"] == overlay_mod.OPEN_METEO_ENDPOINT
    assert first["truth_level"] == "observed"
    assert second["content"]["stale"] is False
    assert len(calls) == 1


def test_planetarium_requires_real_north_and_emits_tracking_space():
    provider = overlay_mod.LocalPlanetariumProvider()
    intent = provider.dome(
        _location(
            tracking_position={"x": 1.0, "y": 1.7, "z": -2.0},
            north_calibrated=True,
            world_north_yaw_deg=12.0,
            heading_accuracy_deg=7.0,
            calibration_id="xreal-calibration-1",
            captured_at_utc="2026-07-26T22:00:00+02:00",
        )
    )

    assert intent["component"] == "sky_dome"
    assert intent["anchor"]["coordinate_space"] == "tracking_local"
    assert 1 <= len(intent["content"]["bodies"]) <= 32
    assert intent["content"]["memory_write"] is False

    bad = _location(
        tracking_position={"x": 0, "y": 0, "z": 0},
        north_calibrated=False,
        world_north_yaw_deg=0,
        heading_accuracy_deg=4,
        calibration_id="c",
    )
    try:
        provider.dome(bad)
        raise AssertionError("uncalibrated north was accepted")
    except ValueError as exc:
        assert "north" in str(exc)


def test_global_legi_search_filters_expired_and_reranks_current_articles():
    payload = {
        "rows": [
            {
                "row": {
                    "doc_id": "LEGIARTI000000000001",
                    "status": "ABROGE",
                    "title": "Ancien texte contrôle",
                    "text": "Ancienne règle sur le contrôle d'identité.",
                }
            },
            {
                "row": {
                    "doc_id": "LEGIARTI000000000002",
                    "status": "VIGUEUR",
                    "start": "2024-01-01",
                    "end": "2999-01-01",
                    "title": "Contrôle d'identité",
                    "chunk_text": (
                        "Le contrôle d'identité doit être réalisé dans les "
                        "conditions prévues par le présent article."
                    ),
                }
            },
            {
                "row": {
                    "doc_id": "LEGIARTI000000000003",
                    "status": "VIGUEUR",
                    "start": "2020-01-01",
                    "end": "2999-01-01",
                    "title": "Justification du contrôle",
                    "chunk_text": (
                        "La personne peut demander le motif applicable au "
                        "contrôle et les références de la procédure."
                    ),
                }
            },
        ]
    }
    opened = []
    provider = overlay_mod.FrenchLegalCorpusProvider(
        opener=lambda url, timeout: (
            opened.append((url, timeout)) or _Response(payload)
        )
    )
    result = provider.lookup(
        "Pendant ce contrôle d'identité, pouvez-vous préciser le motif ?"
    )

    assert result["provider"] == "legi-global-search"
    assert result["status"] == "VIGUEUR"
    assert result["source"].startswith(
        "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI"
    )
    assert result["relevance"] >= 0.20
    assert result["matched_terms"]
    assert result["alternatives"]
    assert "dataset=AgentPublic%2Flegi" in opened[0][0]


def test_context_assist_is_explicit_bounded_and_profiles_natural_commands():
    emitted = []
    submitted = []

    class Bridge:
        def feature_active(self, feature):
            return feature == "legal_context"

        def submit_context_assist(
            self, payload, *, session_id, on_intent
        ):
            submitted.append((payload, session_id))
            return {"status": "pending"}

    assist = assist_mod.ContextualAssistSession(
        bridge=Bridge(),
        session_id="live-1",
        emit_ui_intent=emitted.append,
        cooldown_s=3,
    )
    router = router_mod.IntentRouter(
        context_assist=assist,
        emit_ui_intent=emitted.append,
    )

    started = router.on_transcript("active le mode juridique")
    assert started["handled"] is True
    assert assist.active is True and assist.profile == "legal"
    assert assist.ingest(
        "Pouvez-vous préciser le motif de ce contrôle d'identité ?"
    )["status"] == "pending"
    assert submitted[0][0]["explicit_session"] is True
    assert submitted[0][0]["profile"] == "legal"
    assert len(submitted[0][0]["recent_turns"]) <= 8

    router.on_transcript("arrête le mode juridique")
    assert assist.active is False
    assert assist.ingest("Cette phrase ne doit jamais sortir.") == {
        "status": "inactive"
    }

    router.on_transcript("active le mode contextuel")
    assert assist.profile == "social"


def test_service_legal_card_uses_global_source_without_memory_write():
    class Legal:
        available = True

        def lookup(self, _query):
            return {
                "summary": "Texte applicable vérifié.",
                "source": "https://www.legifrance.gouv.fr/codes/article_lc/X",
                "dataset_source": overlay_mod.LEGI_DATASET_SOURCE,
                "doc_id": "X",
                "status": "VIGUEUR",
                "start_date": "2024-01-01",
                "retrieved_at_utc": "2026-07-26T10:00:00+00:00",
                "relevance": 0.8,
                "matched_terms": ["contrôle"],
                "alternatives": [],
                "cache_state": "network",
            }

    state = service_mod.PreferenceState()
    state.legal_knowledge = Legal()
    features = {feature: False for feature in service_mod.KNOWN_FEATURES}
    features["legal_context"] = True
    applied = state.apply(
        {
            "schema_version": 1,
            "session_id": "legal-1",
            "person_id": "me",
            "master_enabled": True,
            "features": features,
            "probe": {},
        }
    )
    assert applied["active_features"] == ["legal_context"]
    card = state.contextual_assist(
        {
            "session_id": "legal-1",
            "profile": "legal",
            "explicit_session": True,
            "recent_turns": ["Quel est le motif de ce contrôle ?"],
        }
    )
    assert card["content"]["source_status"] == "VIGUEUR"
    assert card["content"]["memory_write"] is False
    assert card["content"]["not_legal_advice"] is True
    assert card["evidence_refs"][0].startswith(
        "https://www.legifrance.gouv.fr/"
    )


def test_context_assist_crosses_real_loopback_bridge_boundary():
    class Legal:
        available = True

        def lookup(self, _query):
            return {
                "summary": "Article global pertinent.",
                "source": "https://www.legifrance.gouv.fr/codes/article_lc/Y",
                "dataset_source": overlay_mod.LEGI_DATASET_SOURCE,
                "doc_id": "Y",
                "status": "VIGUEUR",
                "start_date": "2024-01-01",
                "retrieved_at_utc": "2026-07-26T10:00:00+00:00",
                "relevance": 0.82,
                "matched_terms": ["contrôle"],
                "alternatives": [],
                "cache_state": "network",
            }

    state = service_mod.PreferenceState()
    state.legal_knowledge = Legal()
    server = service_mod.ThreadingHTTPServer(
        ("127.0.0.1", 0), service_mod.build_handler(state, enabled=True)
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    bridge = bridge_mod.AugmentedRealityBridge(
        enabled=True,
        base_url=f"http://127.0.0.1:{server.server_port}",
        timeout_s=1.0,
    )
    ready = threading.Event()
    delivered = threading.Event()
    intents = []
    try:
        features = {feature: False for feature in bridge_mod.KNOWN_FEATURES}
        features["legal_context"] = True
        bridge.submit_preferences(
            {
                "schema_version": 1,
                "master_enabled": True,
                "features": features,
                "probe": {},
            },
            session_id="loopback-legal",
            person_id="me",
            on_status=lambda _status: ready.set(),
        )
        assert ready.wait(2)
        assert bridge.feature_active("legal_context")
        bridge.submit_context_assist(
            {
                "profile": "legal",
                "explicit_session": True,
                "recent_turns": ["Quel est le motif de ce contrôle ?"],
            },
            session_id="loopback-legal",
            on_intent=lambda intent: (intents.append(intent), delivered.set()),
        )
        assert delivered.wait(2)
        assert intents[0]["content"]["source_status"] == "VIGUEUR"
        assert bridge.metrics()["context_assist_cards"] == 1
    finally:
        bridge.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_context_assist_provider_failure_is_visible_not_silent():
    bridge = bridge_mod.AugmentedRealityBridge(enabled=False)
    intents = []
    bridge._deliver_context_assist_result(
        {"status": "unavailable", "detail": "temporary corpus failure"},
        intents.append,
        session_id="legal-down",
    )

    assert intents[0]["component"] == "context_card"
    assert intents[0]["content"]["kind"] == "context_assist_unavailable"
    assert "ne pas proposer" in intents[0]["content"]["text"]
    assert intents[0]["content"]["memory_write"] is False
