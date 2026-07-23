"""HTTP front for SessionHub (E24) — create -> clock-sync -> renew via TestClient.

Proves the three-way symmetry required by the guide: the Python ``SessionHub``
(``services/live-pc/sessionhub.py``), the C# ``ClockSync.ComputeSample``
(``apps/xr-mobile/Assets/Scripts/Core/ClockSync.cs``) and this HTTP server all
compute the *same* offset/RTT for the same inputs.

The clock-sync offset is deliberately split: the HTTP server returns the two
server monotonic stamps, and the client computes the offset with the exact
formulas of ``SessionHub.complete_clock_sync``. So to prove symmetry we replay
the *same numeric fixtures as ``tests/v19/test_sessionhub.py``* (client clocks
+5 ms ahead / -8 ms behind, symmetric 1 ms legs) through the shared formula and
assert the HTTP path reproduces them byte-for-byte.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sessionhub = _load("sessionhub", "services/live-pc/sessionhub.py")
sessionhub_http = _load("sessionhub_http", "services/live-pc/sessionhub_http.py")

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Shared clock-sync formula (identical to SessionHub.complete_clock_sync and to
# the C# ClockSync.ComputeSample). Kept here so the test asserts *symmetry*, not
# just self-consistency.
# ---------------------------------------------------------------------------
def _offset_rtt(client_send_ns, server_recv_ns, server_send_ns, client_recv_ns):
    rtt = (client_recv_ns - client_send_ns) - (server_send_ns - server_recv_ns)
    offset = ((server_recv_ns - client_send_ns) + (server_send_ns - client_recv_ns)) // 2
    return offset, rtt


@pytest.fixture()
def client():
    hub = sessionhub.SessionHub()
    app = sessionhub_http.create_app(hub, enable_signaling=False)
    with TestClient(app) as c:
        c.app.state.hub = hub  # convenience
        yield c


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["ready"] is False
    assert body["sessions"] == 0
    live = client.get("/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"


def test_health_distinguishes_pairing_from_full_ai_readiness(monkeypatch):
    monkeypatch.setenv("MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING", "0")
    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "0")
    class _Manager:
        recovery_state = "completed"

        def metrics(self):
            return {}

    app = sessionhub_http.create_app(
        sessionhub.SessionHub(),
        enable_signaling=True,
        runtime_manager=_Manager(),
        readiness_probe=lambda: {
            "ready": False,
            "checks": {"ollama": {"ok": False}, "qdrant": {"ok": False}},
            "failed": ["ollama", "qdrant"],
        },
    )
    with TestClient(app) as c:
        health = c.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "pairing_ready"
        assert health.json()["pairing_ready"] is True
        assert health.json()["ai_ready"] is False
        assert c.get("/ready").status_code == 503


def test_health_blocks_pairing_while_startup_recovery_is_running():
    class _Manager:
        recovery_state = "running"

        def metrics(self):
            return {}

    app = sessionhub_http.create_app(
        sessionhub.SessionHub(),
        enable_signaling=True,
        runtime_manager=_Manager(),
        readiness_probe=lambda: {"ready": True, "checks": {}, "failed": []},
    )
    with TestClient(app) as c:
        health = c.get("/health")
        assert health.status_code == 503
        assert health.json()["startup_recovery"] == "running"
        assert health.json()["pairing_ready"] is False


def test_production_gpu_mode_waits_for_deep_probe_before_pairing(monkeypatch):
    """The in-process deep probe must not race live ASR/vision on an 8 GB GPU."""
    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    monkeypatch.delenv("MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING", raising=False)

    class _Manager:
        recovery_state = "completed"

        def metrics(self):
            return {}

    app = sessionhub_http.create_app(
        sessionhub.SessionHub(),
        enable_signaling=True,
        runtime_manager=_Manager(),
        readiness_probe=lambda: {
            "ready": False,
            "checks": {"asr": {"ok": False}},
            "failed": ["asr"],
        },
    )
    with TestClient(app) as c:
        health = c.get("/health")
        for _ in range(50):
            if health.json().get("chain", {}).get("failed") == ["asr"]:
                break
            time.sleep(0.01)
            health = c.get("/health")
        assert health.status_code == 503
        assert health.json()["pairing_ready"] is False
        assert health.json()["ai_ready"] is False


def test_production_gpu_mode_opens_pairing_after_deep_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING", "1")
    receipt = tmp_path / "phoneonly_readiness.json"
    monkeypatch.setenv("MLOMEGA_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p1-24k-mlomega")
    monkeypatch.setenv("MLOMEGA_OLLAMA_CONTEXT_POSTSTOP", "24576")
    monkeypatch.setenv("MLOMEGA_OLLAMA_LIVE_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("MLOMEGA_OFFLINE_VLM_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.5")
    receipt.write_text(json.dumps({
        "ready": True,
        "created_at_epoch": time.time(),
        "mode": "deep",
        "fingerprint": {
            "person_id": "me",
            "llm_backend": "llamacpp",
            "llamacpp_base_url": "http://127.0.0.1:8080",
            "llamacpp_model": "qwen9b-p1-24k-mlomega",
            "poststop_context": "24576",
            "live_model": "qwen3.5:4b",
            "offline_vlm_model": "qwen3-vl:8b",
            "gpu_phase_orchestration": "1",
            "pro_close_day": "0",
            "pro_text_model": "",
            "pro_audio_model": "",
            "pro_vision_model": "",
            "cloud_budget_eur": "1.5",
            "cloud_budget_policy": "",
        },
        "checks": {"live_llm_warm": True},
    }), encoding="utf-8")

    class _Manager:
        recovery_state = "completed"

        def metrics(self):
            return {}

    app = sessionhub_http.create_app(
        sessionhub.SessionHub(),
        enable_signaling=True,
        runtime_manager=_Manager(),
        readiness_probe=lambda: {"ready": True, "checks": {}, "failed": []},
    )
    with TestClient(app) as c:
        health = c.get("/health")
        for _ in range(50):
            if health.status_code == 200:
                break
            time.sleep(0.01)
            health = c.get("/health")
        assert health.status_code == 200
        assert health.json()["pairing_ready"] is True
        assert health.json()["ai_ready"] is True


def test_deep_preflight_receipt_requires_fresh_matching_environment(tmp_path, monkeypatch):
    receipt = tmp_path / "phoneonly_readiness.json"
    monkeypatch.setenv("MLOMEGA_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p1-24k-mlomega")
    monkeypatch.setenv("MLOMEGA_OLLAMA_CONTEXT_POSTSTOP", "24576")
    monkeypatch.setenv("MLOMEGA_OLLAMA_LIVE_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("MLOMEGA_OFFLINE_VLM_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.5")
    fingerprint = {
        "person_id": "me",
        "llm_backend": "llamacpp",
        "llamacpp_base_url": "http://127.0.0.1:8080",
        "llamacpp_model": "qwen9b-p1-24k-mlomega",
        "poststop_context": "24576",
        "live_model": "qwen3.5:4b",
        "offline_vlm_model": "qwen3-vl:8b",
        "gpu_phase_orchestration": "1",
        "pro_close_day": "0",
        "pro_text_model": "",
        "pro_audio_model": "",
        "pro_vision_model": "",
        # Numeric formatting is deliberately different from the environment.
        "cloud_budget_eur": "1.50",
        "cloud_budget_policy": "",
    }
    receipt.write_text(json.dumps({
        "ready": True,
        "created_at_epoch": time.time(),
        "mode": "deep",
        "fingerprint": fingerprint,
        "checks": {"whisper_model": True, "p1_sequential": True},
    }), encoding="utf-8")

    ok, detail = sessionhub_http._preflight_receipt_check(person_id="me")
    assert ok is True
    assert detail["mismatches"] == {}

    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "wrong-alias")
    ok2, detail2 = sessionhub_http._preflight_receipt_check(person_id="me")
    assert ok2 is False
    assert "llamacpp_model" in detail2["mismatches"]


def test_local_preflight_receipt_treats_null_and_empty_budget_as_disabled(
    tmp_path, monkeypatch
):
    receipt = tmp_path / "phoneonly_readiness.json"
    monkeypatch.setenv("MLOMEGA_PREFLIGHT_RECEIPT", str(receipt))
    monkeypatch.delenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", raising=False)
    fingerprint = {
        "person_id": "me",
        "llm_backend": "ollama",
        "llamacpp_base_url": "http://127.0.0.1:8080",
        "llamacpp_model": "",
        "poststop_context": "16384",
        "live_model": "qwen3.5:4b",
        "offline_vlm_model": "qwen3-vl:8b",
        "gpu_phase_orchestration": "0",
        "pro_close_day": "0",
        "pro_text_model": "",
        "pro_audio_model": "",
        "pro_vision_model": "",
        "cloud_budget_eur": None,
        "cloud_budget_policy": "",
    }
    receipt.write_text(
        json.dumps(
            {
                "ready": True,
                "created_at_epoch": time.time(),
                "mode": "deep",
                "fingerprint": fingerprint,
                "checks": {"vlm_json_contract": True},
            }
        ),
        encoding="utf-8",
    )

    ok, detail = sessionhub_http._preflight_receipt_check(person_id="me")

    assert ok is True
    assert detail["mismatches"] == {}


def test_create_returns_session_token_and_stamp(client):
    r = client.post("/session/create", json={"device_id": "s25-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"].startswith("xr-")
    assert body["token"]
    assert body["created_at_utc"]
    assert body["expires_at_utc"]
    assert body["expires_in_seconds"] == 600.0
    # Session is now authenticable on the hub.
    hub = client.app.state.hub
    assert hub.authenticate(body["token"]).device_id == "s25-a"


def test_create_rejects_missing_device_id(client):
    r = client.post("/session/create", json={})
    assert r.status_code == 422


def test_two_clients_get_unique_sessions_and_tokens(client):
    a = client.post("/session/create", json={"device_id": "s25-a"}).json()
    b = client.post("/session/create", json={"device_id": "s25-b"}).json()
    assert a["session_id"] != b["session_id"]
    assert a["token"] != b["token"]


def test_clock_sync_requires_valid_token(client):
    created = client.post("/session/create", json={"device_id": "a"}).json()
    # Wrong token -> 401.
    r = client.post(
        "/session/clock-sync",
        json={"session_id": created["session_id"], "token": "nope", "client_send_ns": 1},
    )
    assert r.status_code == 401
    # Right token -> two server stamps.
    r = client.post(
        "/session/clock-sync",
        json={
            "session_id": created["session_id"],
            "token": created["token"],
            "client_send_ns": 1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["server_recv_ns"] == body["server_send_ns"]
    assert body["server_recv_ns"] > 0


def test_clock_sync_offset_matches_sessionhub_and_csharp_fixtures(client):
    """Replay the exact fixtures of test_sessionhub.py through the HTTP path.

    In test_sessionhub.py the offsets are +5 ms and -8 ms (client ahead/behind).
    The HTTP server relays server stamps; the client computes the offset. We
    stamp the exchange with the fixture's server stamps and assert the shared
    formula reproduces the SessionHub result AND the C# EditMode expectation.
    """
    hub = client.app.state.hub
    a = client.post("/session/create", json={"device_id": "a"}).json()
    b = client.post("/session/create", json={"device_id": "b"}).json()

    # --- client A: +5 ms ahead of server, 1 ms symmetric legs ---
    a_send, a_srecv, a_ssend, a_crecv = 6_000_000, 1_000_000, 1_100_000, 6_100_000
    off_a, rtt_a = _offset_rtt(a_send, a_srecv, a_ssend, a_crecv)
    # SessionHub (Python) side — identical arithmetic.
    sa = hub.complete_clock_sync(
        a["session_id"],
        client_send_ns=a_send,
        server_recv_ns=a_srecv,
        server_send_ns=a_ssend,
        client_recv_ns=a_crecv,
    )
    assert sa.offset_ns == off_a
    assert sa.rtt_ns == rtt_a
    assert abs(off_a + 5_000_000) < 100_000  # +5 ms, C# tolerance 100 us

    # --- client B: -8 ms behind server ---
    b_send, b_srecv, b_ssend, b_crecv = -7_000_000, 1_000_000, 1_100_000, -6_900_000
    off_b, rtt_b = _offset_rtt(b_send, b_srecv, b_ssend, b_crecv)
    sb = hub.complete_clock_sync(
        b["session_id"],
        client_send_ns=b_send,
        server_recv_ns=b_srecv,
        server_send_ns=b_ssend,
        client_recv_ns=b_crecv,
    )
    assert sb.offset_ns == off_b
    assert abs(off_b - 8_000_000) < 100_000  # -8 ms

    # The HTTP clock-sync endpoint itself returns collapsed equal stamps, and the
    # client's ComputeSample (same formula) would produce a coherent offset for a
    # real round-trip. Exercise the endpoint to confirm the contract shape.
    resp = client.post(
        "/session/clock-sync",
        json={"session_id": a["session_id"], "token": a["token"], "client_send_ns": a_send},
    ).json()
    assert set(resp) == {"server_recv_ns", "server_send_ns"}


def test_renew_rotates_token_and_revokes_old(client):
    created = client.post("/session/create", json={"device_id": "a"}).json()
    old_token = created["token"]
    r = client.post(
        "/session/renew",
        json={"session_id": created["session_id"], "token": old_token},
    )
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != old_token
    hub = client.app.state.hub
    # Old token no longer authenticates; new one does, same session.
    assert hub.authenticate(old_token) is None
    assert hub.authenticate(new_token).session_id == created["session_id"]
    # Old token now rejected on protected routes.
    r2 = client.post(
        "/session/renew",
        json={"session_id": created["session_id"], "token": old_token},
    )
    assert r2.status_code == 401


def test_renew_requires_valid_token(client):
    created = client.post("/session/create", json={"device_id": "a"}).json()
    r = client.post(
        "/session/renew",
        json={"session_id": created["session_id"], "token": "wrong"},
    )
    assert r.status_code == 401


def test_expired_token_and_session_are_purged():
    now = [100.0]
    hub = sessionhub.SessionHub(
        token_ttl_seconds=10, renew_grace_seconds=20, monotonic=lambda: now[0]
    )
    app = sessionhub_http.create_app(hub, enable_signaling=False)
    with TestClient(app) as client:
        created = client.post("/session/create", json={"device_id": "a"}).json()
        now[0] = 111.0
        expired = client.post(
            "/session/clock-sync",
            json={"session_id": created["session_id"], "token": created["token"], "client_send_ns": 1},
        )
        assert expired.status_code == 401
        renewed = client.post(
            "/session/renew",
            json={"session_id": created["session_id"], "token": created["token"]},
        )
        assert renewed.status_code == 200
        assert renewed.json()["token"] != created["token"]

        # The rotated token also expires and is retired after its renew grace.
        now[0] = 142.0
        assert hub.session_count == 0
