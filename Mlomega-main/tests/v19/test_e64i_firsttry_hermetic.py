from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mlomega_audio_elite import runtime_environment_v19 as runtime_env


def _load_preflight():
    path = ROOT / "scripts" / "check_close_day_preflight.py"
    spec = importlib.util.spec_from_file_location("e64i_hermetic_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_blackhole_proxy_is_removed_but_real_proxy_is_preserved(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "localhost:9")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.test:8080")

    removed = runtime_env.sanitize_blackhole_proxy_env()

    assert {name.lower() for name in removed} == {"https_proxy", "http_proxy"}
    assert "HTTPS_PROXY" not in runtime_env.os.environ
    assert runtime_env.os.environ["ALL_PROXY"] == "http://proxy.example.test:8080"


def test_dead_explicit_proxy_fails_before_hf(monkeypatch):
    for name in runtime_env.PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8443")

    def refused(*_args, **_kwargs):
        raise ConnectionRefusedError("dead")

    monkeypatch.setattr(runtime_env.socket, "create_connection", refused)
    ok, detail = runtime_env.probe_proxy_environment(timeout_s=0.01)

    assert not ok
    assert detail["unreachable"] == ["proxy.example.test:8443"]
    assert "HTTP_PROXY" in detail["fix"]


def test_pyannote_cache_requires_weights_not_just_snapshot_directory(tmp_path, monkeypatch):
    snapshots = {repo: tmp_path / repo.replace("/", "--") for repo in runtime_env.PYANNOTE_REPOSITORIES}
    for path in snapshots.values():
        path.mkdir()

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.snapshot_download = lambda *, repo_id, **_kwargs: str(snapshots[repo_id])
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    ok, detail = runtime_env.probe_huggingface_pyannote(token="hf_valid_token", verify_remote=False)
    assert not ok
    assert "incomplete snapshot" in detail["cached"]["pyannote/segmentation-3.0"]

    for repo, names in runtime_env.PYANNOTE_REQUIRED_FILES.items():
        for name in names:
            (snapshots[repo] / name).write_bytes(b"cached")
    ok, detail = runtime_env.probe_huggingface_pyannote(token="hf_valid_token", verify_remote=False)
    assert ok
    assert detail["downloads_performed"] is False


def test_orphan_llamacpp_is_rejected_when_ollama_is_selected(monkeypatch):
    module = _load_preflight()
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "ollama")
    monkeypatch.setattr(
        module,
        "_request_json",
        lambda *_args, **_kwargs: {"model_alias": "old-p1", "default_generation_settings": {"n_ctx": 24576}},
    )

    ok, detail = module._probe_llm_process_consistency()

    assert not ok
    assert detail["running_alias"] == "old-p1"
    assert "VRAM" in detail["fix"]


def test_llamacpp_requires_exact_configured_alias(monkeypatch):
    module = _load_preflight()
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "expected-p3")
    monkeypatch.setattr(
        module,
        "_request_json",
        lambda *_args, **_kwargs: {"model_alias": "old-p1", "default_generation_settings": {"n_ctx": 24576}},
    )

    ok, detail = module._probe_llm_process_consistency()

    assert not ok
    assert detail["expected_alias"] == "expected-p3"


def test_selected_ollama_model_must_execute_strict_json(monkeypatch):
    module = _load_preflight()
    cfg = types.SimpleNamespace(
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen-test",
        ollama_context_poststop=16384,
    )
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "ollama")
    captured = {}

    def request(url, *, payload=None, timeout_s=0):
        captured.update(url=url, payload=payload, timeout_s=timeout_s)
        return {"response": json.dumps({"status": "mlomega-ready"}), "done_reason": "stop"}

    monkeypatch.setattr(module, "_request_json", request)
    ok, detail = module._probe_json_contract(cfg)

    assert ok
    assert detail["model"] == "qwen-test"
    assert captured["payload"]["format"]["additionalProperties"] is False
    assert captured["payload"]["options"]["num_ctx"] == 16384


def test_vlm_probe_uses_real_product_json_mode_and_all_configured_models(monkeypatch):
    module = _load_preflight()
    cfg = types.SimpleNamespace(ollama_base_url="http://127.0.0.1:11434")
    monkeypatch.setenv("MLOMEGA_VLM_MODEL", "vlm-live")
    monkeypatch.setenv("MLOMEGA_OFFLINE_VLM_MODEL", "vlm-night")
    monkeypatch.setattr(module, "_ollama_tags", lambda *_args, **_kwargs: ({"vlm-live", "vlm-night"}, {}))
    calls = []

    def request(url, *, payload=None, timeout_s=0):
        calls.append(payload)
        return {"response": json.dumps({"image_received": True}), "done_reason": "stop"}

    monkeypatch.setattr(module, "_request_json", request)
    ok, detail = module._probe_vlm_contract(cfg)

    assert ok
    assert set(detail["probes"]) == {"vlm-live", "vlm-night"}
    assert all(call["format"]["required"] == ["image_received"] and call["images"] for call in calls)
    assert all(call["format"]["additionalProperties"] is False for call in calls)
    assert all(call["options"]["num_predict"] >= 128 for call in calls)


def test_vlm_probe_accepts_deployed_qwen_json_in_thinking(monkeypatch):
    module = _load_preflight()
    cfg = types.SimpleNamespace(ollama_base_url="http://127.0.0.1:11434")
    monkeypatch.setenv("MLOMEGA_VLM_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("MLOMEGA_OFFLINE_VLM_MODEL", "qwen3-vl:8b")
    monkeypatch.setattr(
        module,
        "_ollama_tags",
        lambda *_args, **_kwargs: ({"qwen3-vl:8b"}, {}),
    )
    monkeypatch.setattr(
        module,
        "_request_json",
        lambda *_args, **_kwargs: {
            "response": "",
            "thinking": json.dumps({"image_received": True}),
            "done_reason": "stop",
        },
    )

    ok, detail = module._probe_vlm_contract(cfg)

    assert ok
    assert detail["probes"]["qwen3-vl:8b"]["parsed"] == {"image_received": True}
