from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bridge_mod = _load(
    "test_augmented_reality_bridge",
    ROOT / "services" / "live-pc" / "augmented_reality_bridge.py",
)
service_mod = _load(
    "test_augmented_reality_service",
    ROOT / "services" / "augmented-reality" / "service.py",
)


def _payload(**overrides):
    payload = {
        "type": "augmented_reality_preferences",
        "schema_version": 1,
        "master_enabled": True,
        "features": {
            feature: feature in {"object_menus", "semantic_sound"}
            for feature in bridge_mod.KNOWN_FEATURES
        },
        "probe": {"coexistence_verdict": "unproven_physical_gate"},
        "sent_at_ms": 123,
    }
    payload.update(overrides)
    return payload


def test_mode_off_creates_no_worker_or_network(monkeypatch):
    monkeypatch.delenv("MLOMEGA_AUGMENTED_REALITY", raising=False)
    bridge = bridge_mod.AugmentedRealityBridge.from_env()
    statuses = []

    result = bridge.submit_preferences(
        _payload(),
        session_id="transport-1",
        person_id="me",
        on_status=statuses.append,
    )

    assert bridge.enabled is False
    assert bridge.worker_created is False
    assert result["status"] == "disabled"
    assert statuses == [
        {
            "status": "disabled",
            "detail": "MLOMEGA_AUGMENTED_REALITY is off",
        }
    ]
    assert bridge.metrics()["failed"] == 0


def test_contract_rejects_unknown_or_non_boolean_features():
    bad = _payload()
    bad["features"]["surprise_model"] = True
    try:
        bridge_mod.normalise_preferences(
            bad, session_id="transport-1", person_id="me"
        )
        raise AssertionError("unknown feature was accepted")
    except ValueError as exc:
        assert "unknown" in str(exc)

    bad = _payload()
    bad["features"]["semantic_sound"] = "yes"
    try:
        bridge_mod.normalise_preferences(
            bad, session_id="transport-1", person_id="me"
        )
        raise AssertionError("non-boolean feature was accepted")
    except ValueError as exc:
        assert "boolean" in str(exc)


def test_foundation_service_is_bounded_and_claims_no_memory_writer():
    state = service_mod.PreferenceState()
    normalised = bridge_mod.normalise_preferences(
        _payload(), session_id="transport-1", person_id="me"
    )
    result = state.apply(normalised)
    manifest = service_mod.capability_manifest(
        enabled=True,
        session_count=state.count(),
        capabilities=state.capabilities(),
    )

    assert result["status"] == "ready"
    assert result["active_features"] == ["object_menus"]
    assert state.count() == 1
    assert manifest["writes_memory_db"] is False
    assert manifest["capabilities"]["object_menus"] is True
    assert manifest["capabilities"]["semantic_sound"] is True
    assert manifest["memory_access"]["object_menus"] == "read_worldbrain_memoryquery"
    assert manifest["memory_access"]["enhanced_zoom"] == "none"


def test_semantic_sound_activates_only_after_device_model_probe():
    state = service_mod.PreferenceState()
    cold = bridge_mod.normalise_preferences(
        _payload(), session_id="transport-cold", person_id="me"
    )
    assert state.apply(cold)["active_features"] == ["object_menus"]

    ready_payload = _payload(
        probe={
            "coexistence_verdict": "single_active_loader_architecture",
            "SemanticSoundModelAvailable": True,
        }
    )
    ready = bridge_mod.normalise_preferences(
        ready_payload, session_id="transport-ready", person_id="me"
    )
    assert state.apply(ready)["active_features"] == [
        "object_menus",
        "semantic_sound",
    ]


def test_contextual_knowledge_auto_cards_have_global_and_topic_cooldowns():
    class Provider:
        available = True

        def lookup(self, topic):
            return {
                "title": topic,
                "summary": "Résumé local et sourcé.",
                "source": "http://127.0.0.1:8081/article",
            }

    gate = service_mod.ContextualKnowledgeGate(provider=Provider())
    first = gate.maybe_card({
        "session_id": "s1", "topic": "calcul quantique", "novel": True
    })
    second = gate.maybe_card({
        "session_id": "s1", "topic": "fusion nucléaire", "novel": True
    })
    explicit = gate.maybe_card({
        "session_id": "s1", "topic": "fusion nucléaire", "explicit": True
    })

    assert first["content"]["kind"] == "contextual_knowledge"
    assert second is None
    assert explicit["content"]["title"] == "fusion nucléaire"


def test_enabled_bridge_reaches_loopback_service_without_blocking_caller():
    state = service_mod.PreferenceState()
    server = service_mod.ThreadingHTTPServer(
        ("127.0.0.1", 0), service_mod.build_handler(state, enabled=True)
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    done = threading.Event()
    statuses = []
    bridge = bridge_mod.AugmentedRealityBridge(
        enabled=True,
        base_url=f"http://127.0.0.1:{server.server_port}",
        timeout_s=1.0,
    )
    try:
        immediate = bridge.submit_preferences(
            _payload(),
            session_id="transport-1",
            person_id="me",
            on_status=lambda status: (statuses.append(status), done.set()),
        )
        assert immediate["status"] == "pending"
        assert done.wait(2.0)
        assert statuses[0]["status"] == "ready"
        assert statuses[0]["active_features"] == ["object_menus"]
        assert state.count() == 1
        assert bridge.metrics()["accepted"] == 1
    finally:
        bridge.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2.0)


def test_service_probe_is_honest_when_disabled(monkeypatch, capsys):
    monkeypatch.setenv("MLOMEGA_AUGMENTED_REALITY", "0")
    assert service_mod.main(["--probe"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "disabled"
    assert payload["writes_memory_db"] is False
    assert not any(payload["capabilities"].values())


def test_object_card_is_visible_bounded_and_only_exposes_backed_actions():
    state = service_mod.PreferenceState()
    normalised = bridge_mod.normalise_preferences(
        _payload(), session_id="transport-1", person_id="me"
    )
    state.apply(normalised)
    card = state.object_card({
        "session_id": "transport-1",
        "source_frame_id": "frame-9",
        "focus_id": "focus-2",
        "entity_id": "mug-1",
        "label": "mug",
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "visibility": "visible",
        "confidence": 0.88,
        "device_labels": [{"label": "Drinkware", "confidence": 0.92}],
    })

    assert card["component"] == "object_profile_card"
    assert card["anchor"]["bbox"] == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    assert card["content"]["device_labels"][0]["label"] == "Drinkware"
    actions = {item["action_id"] for item in card["content"]["actions"]}
    assert actions == {"manual", "history"}
    assert card["ttl_ms"] == 3500


def test_object_state_change_requires_confirmation_and_configured_adapter(
    monkeypatch,
):
    registry = service_mod.ObjectActionRegistry(configured_devices={})
    try:
        service_mod.execute_object_action(
            {
                "action_id": "power_on",
                "entity_id": "lamp-1",
                "label": "lamp",
                "confirmed": True,
            },
            registry=registry,
        )
        raise AssertionError("unconfigured state-changing action was accepted")
    except ValueError as exc:
        assert "configured" in str(exc)

    configured = service_mod.ObjectActionRegistry(configured_devices={
        "lamp-1": {
            "adapter": "home_assistant",
            "base_url": "http://127.0.0.1:8123",
            "ha_entity_id": "light.living_room",
            "token_env": "MLOMEGA_HOME_ASSISTANT_TOKEN",
        }
    })
    monkeypatch.setenv("MLOMEGA_HOME_ASSISTANT_TOKEN", "test-token")
    actions = configured.actions_for({"entity_id": "lamp-1", "label": "lamp"})
    state_actions = [item for item in actions if item.state_change]
    assert [(item.action_id, item.requires_confirmation) for item in state_actions] == [
        ("toggle", True)
    ]


def test_product_launcher_keeps_augmented_reality_opt_in_and_cleans_it_up():
    launcher = Path("scripts/RUN_MLOMEGA_V19.ps1").read_text(encoding="utf-8")
    assert "[switch]$AugmentedReality" in launcher
    assert 'MLOMEGA_AUGMENTED_REALITY = "0"' in launcher
    assert "services\\augmented-reality\\service.py" in launcher
    assert launcher.index("check_phoneonly_readiness.py") < launcher.index(
        "services\\augmented-reality\\service.py"
    )
    assert "Stop-Process -Id $augmentedRealityProcess.Id" in launcher
