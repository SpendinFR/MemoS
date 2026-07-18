from __future__ import annotations


def test_llamacpp_backend_uses_openai_json_schema(monkeypatch):
    from mlomega_audio_elite import llm

    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"ok":true}'},
                }
            ]
        }

    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "qwen-test")
    monkeypatch.setattr(llm, "llamacpp_chat_json", fake_chat)

    client = llm.OllamaJsonClient()
    assert client.require_json("system", "prompt", {"ok": True}) == {"ok": True}
    assert client.backend == "llamacpp"
    assert captured["model"] == "qwen-test"
    assert captured["json_schema"]["required"] == ["ok"]


def test_llamacpp_length_is_reported_as_truncation(monkeypatch):
    from mlomega_audio_elite import llm

    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "llamacpp")
    monkeypatch.setattr(
        llm,
        "llamacpp_chat_json",
        lambda **kwargs: {
            "choices": [
                {"finish_reason": "length", "message": {"content": '{"ok":'}}
            ]
        },
    )
    result = llm.OllamaJsonClient().generate_json("system", "prompt", {"ok": True})
    assert result.ok is False
    assert result.error_kind == "truncated_output"
    assert result.finish_reason == "length"


def test_ollama_uses_distinct_total_context_windows(monkeypatch):
    from mlomega_audio_elite import llm
    from mlomega_audio_elite.runtime_v18_7 import phase

    captured: list[dict] = []

    def fake_generate(payload, **_kwargs):
        captured.append(payload)
        return {"done": True, "done_reason": "stop", "response": '{"ok":true}'}

    monkeypatch.setattr(llm, "ollama_generate", fake_generate)
    monkeypatch.setenv("MLOMEGA_OLLAMA_CONTEXT_LIVE", "4096")
    monkeypatch.setenv("MLOMEGA_OLLAMA_CONTEXT_POSTSTOP", "16384")

    assert llm.OllamaJsonClient().require_json("system", "prompt", {"ok": True}) == {"ok": True}
    assert captured[-1]["options"]["num_ctx"] == 4096
    assert captured[-1]["options"]["num_predict"] == 900
    assert captured[-1]["think"] is False

    with phase("post_stop_context_test"):
        assert llm.OllamaJsonClient().require_json("system", "prompt", {"ok": True}) == {"ok": True}
    assert captured[-1]["options"]["num_ctx"] == 16384
    assert captured[-1]["options"]["num_predict"] == 4096


def test_live_ollama_transport_does_not_reuse_nightly_retry_backoffs(monkeypatch):
    from mlomega_audio_elite import llm
    from mlomega_audio_elite.runtime_v18_7 import phase

    seen: list[int | None] = []

    def fake_retry(operation, **kwargs):
        seen.append(kwargs.get("max_retries"))
        return {"done": True, "response": '{}'}

    monkeypatch.setattr(llm, "retry_operation", fake_retry)
    payload = {"model": "qwen3.5:4b", "prompt": "x", "stream": False}
    llm.ollama_generate(payload, timeout=1, component="live-test")
    assert seen[-1] == 0

    with phase("post_stop_test"):
        llm.ollama_generate(payload, timeout=1, component="night-test")
    assert seen[-1] == llm.get_settings().poststop_retry_max


def test_truncated_json_is_never_applied(monkeypatch):
    from mlomega_audio_elite import llm

    monkeypatch.setattr(
        llm,
        "ollama_generate",
        lambda *_args, **_kwargs: {
            "done": True,
            "done_reason": "length",
            "response": '{"ok":',
        },
    )
    result = llm.OllamaJsonClient().generate_json("system", "prompt", {"ok": True})
    assert result.ok is False
    assert result.data == {}
    assert result.error_kind == "truncated_output"


def test_strict_brain2_retries_truncation_once_with_larger_budget(monkeypatch):
    from mlomega_audio_elite import brain2_strict_v13_2 as strict
    from mlomega_audio_elite.llm import LLMTruncatedOutputError

    calls: list[int | None] = []

    class FakeClient:
        def require_json(self, *_args, max_output_tokens=None, **_kwargs):
            calls.append(max_output_tokens)
            if len(calls) == 1:
                raise LLMTruncatedOutputError("length")
            return {"ok": True}

    monkeypatch.setattr(strict, "OllamaJsonClient", FakeClient)
    monkeypatch.setenv("MLOMEGA_V13_TRUNCATION_RETRY_TOKENS", "8192")
    assert strict._llm_require_json("context_resolver", "prompt", {"ok": True}) == {
        "ok": True
    }
    assert calls == [None, 8192]


def test_safe_prompt_fallback_keeps_conversation_bundle_references():
    from mlomega_audio_elite.brain2_strict_v13_2 import _safe_prompt_payload
    import json

    prompt = json.loads(_safe_prompt_payload({
        "mission": "segment",
        "conversation_bundle": {
            "turns": [{"turn_id": "t1", "text": "x" * 1000}]
        },
        "schema": {"episodes": []},
    }, max_chars=900))
    assert prompt["context_incomplete"] is True
    assert prompt["bundle_source_refs"]["turns"][0]["turn_id"] == "t1"

