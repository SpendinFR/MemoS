from __future__ import annotations


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

    with phase("post_stop_context_test"):
        assert llm.OllamaJsonClient().require_json("system", "prompt", {"ok": True}) == {"ok": True}
    assert captured[-1]["options"]["num_ctx"] == 16384
    assert captured[-1]["options"]["num_predict"] == 4096


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

