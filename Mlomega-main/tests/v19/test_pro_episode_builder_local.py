"""CHANTIER 1 — EpisodeBuilder stays on the local P1/llama.cpp client in PRO.

The nightly PRO subprocess sets ``MLOMEGA_LLM_BACKEND=deepseek`` for the cognitive
engines.  These tests prove EpisodeBuilder is NOT sent to DeepSeek: it is built
with an explicit ``llamacpp`` client, and without the PRO flag the local path is
byte-for-byte unchanged (no injected window_llm, no client override).
"""

from __future__ import annotations

import pytest

from mlomega_audio_elite import brain2_strict_v13_2 as strict


def test_forces_local_only_when_pro_and_cloud_text_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # No PRO flag: never force local (local path stays byte-for-byte).
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "deepseek")
    assert strict._episode_builder_forces_local() is False

    # PRO but local backend (e.g. dev without cloud): nothing to override.
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "ollama")
    assert strict._episode_builder_forces_local() is False

    # PRO + inherited DeepSeek text backend: EpisodeBuilder must be forced local.
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "deepseek")
    assert strict._episode_builder_forces_local() is True


def test_local_episode_window_llm_is_llamacpp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_ENABLE_OLLAMA", "true")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p1-24k-mlomega")
    # Even with a DeepSeek text backend in the environment, the EXPLICIT backend
    # arg wins and the episode client never becomes a cloud client.
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "deepseek")
    window_llm = strict._build_local_episode_window_llm()
    assert window_llm._client.backend == "llamacpp"
    assert window_llm._client.base_url == "http://127.0.0.1:8080"
    assert window_llm._client.model == "qwen9b-p1-24k-mlomega"


class _EmptyResult:
    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _FakeCon:
    """Minimal connection: no existing episodes, all writes are no-ops."""

    def execute(self, *args, **kwargs):
        return _EmptyResult()

    def commit(self):
        pass


def _fake_bundle_capture(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch the conversation episode builder to record its window_llm arg."""
    captured: dict = {}

    def fake_build_conversation_episode_v6(con, conversation_id, **kwargs):
        captured["window_llm"] = kwargs.get("window_llm")
        return {"episodes": 1, "subthemes": 1, "calls": 2, "output": {}}

    def fake_enabled() -> bool:
        return True

    import mlomega_audio_elite.brain2_conversation_episode as ce

    monkeypatch.setattr(ce, "build_conversation_episode_v6", fake_build_conversation_episode_v6)
    monkeypatch.setattr(ce, "conversation_episode_enabled", fake_enabled)
    # Neutralise the DB-touching helpers so we test only the client wiring.
    monkeypatch.setattr(strict, "_conversation_bundle", lambda con, cid: {"conversation": {}, "turns": []})
    monkeypatch.setattr(strict, "_default_user", lambda con, cid, explicit_person_id=None: "me")
    monkeypatch.setattr(strict, "_record_engine", lambda *a, **k: "run")
    return captured


def test_pro_injects_local_window_llm_into_episode_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_ENABLE_OLLAMA", "true")
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "deepseek")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p1-24k-mlomega")
    captured = _fake_bundle_capture(monkeypatch)

    strict._ensure_episodes_strict(con=_FakeCon(), conversation_id="c1", person_id="me")

    window_llm = captured["window_llm"]
    assert window_llm is not None, "PRO must inject an explicit episode client"
    assert window_llm._client.backend == "llamacpp", "EpisodeBuilder must never be DeepSeek in PRO"


def test_local_path_injects_no_window_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_ENABLE_OLLAMA", "true")
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    monkeypatch.delenv("MLOMEGA_LLM_BACKEND", raising=False)
    captured = _fake_bundle_capture(monkeypatch)

    strict._ensure_episodes_strict(con=_FakeCon(), conversation_id="c1", person_id="me")

    # Byte-for-byte: the optional param stays None so the historic implicit
    # OllamaWindowLLM/OllamaJsonClient is constructed exactly as before.
    assert captured["window_llm"] is None
