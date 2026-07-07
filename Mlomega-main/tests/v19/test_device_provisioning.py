"""Device-model provisioning endpoints (E47-C livrable 2).

The phone fetches its offline ASR/KWS + gesture models from the PC at first
launch through two SessionHub routes, both token-gated:

    GET /models/device/manifest           -> {models: [...], count}
    GET /models/device/{name}             -> the artefact (X-Model-Sha256 header)

These tests drive the real FastAPI app via TestClient against a temporary
MODEL_MANIFEST + a temporary models/device tree, and assert:
  * the manifest lists each device model with its sha256 + endpoint;
  * a valid token downloads the exact bytes, sha256-verified end to end;
  * a wrong/absent token is refused (401/422);
  * an unknown or not-yet-fetched model is 404.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
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

pytest.importorskip("fastapi")
pytest.importorskip("yaml")
from fastapi.testclient import TestClient  # noqa: E402

_TASK_BYTES = b"MEDIAPIPE-TASK-FAKE-WEIGHTS-" * 64
_TASK_SHA = hashlib.sha256(_TASK_BYTES).hexdigest()

_MANIFEST = """\
models:
  detector:
    provider: onnx_local
    default: yolox_nano.onnx
device:
  hand_landmarker:
    provider: mediapipe_device
    platform: android
    kind: hand_landmarker
    license: Apache-2.0
    path: models/device/hand_landmarker.task
    url: https://storage.googleapis.com/mediapipe-models/hand_landmarker.task
    sha256: PENDING_FETCH
  asr_stream_en:
    provider: sherpa_onnx_device
    platform: android
    kind: asr_streaming
    license: Apache-2.0
    path: models/device/sherpa-onnx-streaming-zipformer-en
    archive: https://example/sherpa-onnx-streaming-zipformer-en.tar.bz2
    archive_sha256: PENDING_FETCH
    extract_to: models/device
"""


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Point the module at a temp manifest + a temp models/device tree."""
    manifest = tmp_path / "configs" / "MODEL_MANIFEST.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(_MANIFEST, encoding="utf-8")
    device_dir = tmp_path / "models" / "device"
    device_dir.mkdir(parents=True, exist_ok=True)
    # hand_landmarker: a present single-file artefact.
    (device_dir / "hand_landmarker.task").write_bytes(_TASK_BYTES)
    # asr_stream_en: only the extracted dir exists, NO archive on disk yet →
    # artefact absent, so it must be reported unavailable / 404 on download.
    (device_dir / "sherpa-onnx-streaming-zipformer-en").mkdir()

    monkeypatch.setattr(sessionhub_http, "_ROOT", tmp_path)
    monkeypatch.setattr(sessionhub_http, "_MANIFEST_PATH", manifest)

    hub = sessionhub.SessionHub()
    app = sessionhub_http.create_app(hub, enable_signaling=False)
    with TestClient(app) as client:
        creds = client.post("/session/create", json={"device_id": "s25"}).json()
        yield client, creds


def test_manifest_lists_device_models_with_sha_and_endpoint(app_env):
    client, creds = app_env
    r = client.get(
        "/models/device/manifest",
        params={"session_id": creds["session_id"], "token": creds["token"]},
    )
    assert r.status_code == 200
    body = r.json()
    by_name = {m["name"]: m for m in body["models"]}
    assert body["count"] == 2
    hand = by_name["hand_landmarker"]
    assert hand["available"] is True
    assert hand["sha256"] == _TASK_SHA  # PENDING_FETCH resolved to on-disk hash
    assert hand["endpoint"] == "/models/device/hand_landmarker"
    assert hand["license"] == "Apache-2.0"
    assert hand["kind"] == "hand_landmarker"
    # The archive whose .tar.bz2 was never fetched is present but unavailable.
    assert by_name["asr_stream_en"]["available"] is False


def test_manifest_requires_token(app_env):
    client, creds = app_env
    # Missing token -> 422.
    assert client.get("/models/device/manifest").status_code == 422
    # Wrong token -> 401.
    bad = client.get(
        "/models/device/manifest",
        params={"session_id": creds["session_id"], "token": "nope"},
    )
    assert bad.status_code == 401


def test_download_streams_exact_bytes_sha_verified(app_env):
    client, creds = app_env
    r = client.get(
        "/models/device/hand_landmarker",
        params={"session_id": creds["session_id"], "token": creds["token"]},
    )
    assert r.status_code == 200
    assert r.content == _TASK_BYTES
    assert hashlib.sha256(r.content).hexdigest() == _TASK_SHA
    # The server advertises the same hash it computed, so the phone verifies.
    assert r.headers["X-Model-Sha256"] == _TASK_SHA


def test_download_requires_token(app_env):
    client, creds = app_env
    assert client.get("/models/device/hand_landmarker").status_code == 422
    bad = client.get(
        "/models/device/hand_landmarker",
        params={"session_id": creds["session_id"], "token": "wrong"},
    )
    assert bad.status_code == 401


def test_unknown_model_is_404(app_env):
    client, creds = app_env
    r = client.get(
        "/models/device/does_not_exist",
        params={"session_id": creds["session_id"], "token": creds["token"]},
    )
    assert r.status_code == 404


def test_not_provisioned_model_is_404(app_env):
    client, creds = app_env
    # asr_stream_en's archive was never fetched → artefact absent → 404.
    r = client.get(
        "/models/device/asr_stream_en",
        params={"session_id": creds["session_id"], "token": creds["token"]},
    )
    assert r.status_code == 404
