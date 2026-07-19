from __future__ import annotations

import json
import sqlite3
import wave
from pathlib import Path

import pytest

from mlomega_audio_elite import cloud_budget_v19 as budget
from mlomega_audio_elite import cloud_providers_v19 as cloud


@pytest.fixture
def cloud_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cloud.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.50")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    return db


def test_budget_reservation_is_durable_and_enforces_cap(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "0.10")
    first = budget.reserve_cloud_cost(
        provider="fake", model="m", stage_name="one", worst_case_eur=0.06, tariff={}
    )
    with pytest.raises(budget.CloudBudgetExceeded):
        budget.reserve_cloud_cost(
            provider="fake", model="m", stage_name="two", worst_case_eur=0.05, tariff={}
        )
    budget.reconcile_cloud_cost(first, actual_eur=0.02, input_tokens=10)
    second = budget.reserve_cloud_cost(
        provider="fake", model="m", stage_name="two", worst_case_eur=0.05, tariff={}
    )
    budget.reconcile_cloud_cost(second, actual_eur=0.01)
    summary = budget.cloud_budget_summary()
    assert summary["committed_eur"] == pytest.approx(0.03)
    with sqlite3.connect(cloud_env) as con:
        assert con.execute("SELECT COUNT(*) FROM cloud_cost_ledger_v19").fetchone()[0] == 2


def test_deepseek_reuses_exact_bundle_prefix_and_preserves_prompts(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads: list[dict] = []

    def fake_json_request(url, payload, **kwargs):
        payloads.append(payload)
        is_warm = any("Acknowledge this evidence" in item.get("content", "") for item in payload["messages"])
        # The actual call also contains the warm exchange; distinguish by its
        # historical engine system message.
        is_actual = any(item == {"role": "system", "content": "ORIGINAL-SYSTEM"} for item in payload["messages"])
        content = '{"answer":"ok"}' if is_actual else '{"bundle_loaded":true}'
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 80 if is_actual else 0,
                "prompt_cache_miss_tokens": 20 if is_actual else 100,
                "completion_tokens": 5,
            },
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    bundle = {"turns": [{"turn_id": "t1", "text": "bonjour"}], "bundle_id": "b1"}
    with cloud.cloud_bundle_prefix("b1", bundle):
        outer1 = cloud.deepseek_chat_json(
            system="ORIGINAL-SYSTEM", prompt="ORIGINAL-PROMPT-1",
            json_schema={"type": "object"}, max_output_tokens=100, timeout=5,
        )
        outer2 = cloud.deepseek_chat_json(
            system="ORIGINAL-SYSTEM-2", prompt="ORIGINAL-PROMPT-2",
            json_schema={"type": "object"}, max_output_tokens=100, timeout=5,
        )
    assert json.loads(outer1["choices"][0]["message"]["content"]) == {"answer": "ok"}
    assert len(payloads) == 3  # one paid warm-up, then two engines
    canonical = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert all(payload["messages"][1]["content"] == canonical for payload in payloads)
    assert payloads[1]["messages"][:4] == payloads[2]["messages"][:4]
    assert {"role": "system", "content": "ORIGINAL-SYSTEM"} in payloads[1]["messages"]
    assert {"role": "user", "content": "ORIGINAL-PROMPT-1"} in payloads[1]["messages"]


def test_deepseek_episode_contexts_share_one_warmup(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads: list[dict] = []

    def fake_json_request(url, payload, **kwargs):
        payloads.append(payload)
        actual = any(item.get("content") == "ENGINE" for item in payload["messages"])
        content = '{"answer":"ok"}' if actual else '{"bundle_loaded":true}'
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    bundle = {"episode": {"episode_id": "ep-1"}, "turns": [{"text": "bonjour"}]}
    for _ in range(2):
        with cloud.cloud_bundle_prefix("ep-1", bundle):
            cloud.deepseek_chat_json(
                system="ENGINE", prompt="TASK", json_schema={"type": "object"},
                max_output_tokens=100, timeout=5,
            )
    warm = [
        payload for payload in payloads
        if any("Acknowledge this evidence" in item.get("content", "") for item in payload["messages"])
        and not any(item.get("content") == "ENGINE" for item in payload["messages"])
    ]
    assert len(warm) == 1
    assert len(payloads) == 3


def test_cloud_bundle_projection_keeps_lossless_manifests_without_raw_duplication() -> None:
    from mlomega_audio_elite.brainlive_poststop_deep_flow_v15_15 import (
        _compact_cloud_bundle_row,
    )

    vision = [
        {
            "source_id": f"obs-{idx}", "source_table": "vision_scene_observations",
            "frame_id": f"frame-{idx}", "time": f"2026-07-19T00:00:{idx:02d}+00:00",
            "objects": [{"label": "glasses", "track_id": "same"}],
        }
        for idx in range(20)
    ]
    raw = [{"raw_id": f"raw-{idx}", "opaque": "X" * 500} for idx in range(20)]
    row = {
        "bundle_id": "bundle-1", "person_id": "me",
        "vision_timeline_json": json.dumps(vision),
        "raw_timeline_json": json.dumps(raw),
        "world_state_timeline_json": "[]", "audio_timeline_json": "[]",
        "transcript_json": "[]", "diarization_json": "[]",
        "outcome_timeline_json": "[]", "intervention_timeline_json": "[]",
        "prediction_timeline_json": "[]", "affordance_timeline_json": "[]",
        "participants_json": "[]", "place_json": "{}", "source_counts_json": "{}",
    }
    projected = _compact_cloud_bundle_row(row)
    encoded = json.dumps(projected)
    assert "X" * 500 not in encoded
    assert projected["raw_timeline_manifest"]["count"] == 20
    assert sum(atom["source_manifest"]["count"] for atom in projected["vision_atoms"]) == 20
    assert sum(atom["frame_manifest"]["count"] for atom in projected["vision_atoms"]) == 20


def test_deepseek_budget_policy_falls_back_to_flash_before_send(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "0.00005")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "flash")
    sent_models: list[str] = []

    def fake_json_request(url, payload, **kwargs):
        sent_models.append(payload["model"])
        return {
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    cloud._deepseek_request(
        messages=[{"role": "user", "content": "small JSON request"}],
        model="deepseek-v4-pro", max_output_tokens=100, timeout=5,
        stage_name="budget_test", json_schema={"type": "object"},
    )
    assert sent_models == ["deepseek-v4-flash"]
    assert budget.cloud_budget_summary()["rows"][0]["model"] == "deepseek-v4-flash"


def _write_wav(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))


def test_groq_transcription_keeps_timestamp_segments(
    cloud_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "tape.wav"
    _write_wav(wav)
    requests = []

    def fake_request(request, **kwargs):
        requests.append(request)
        return json.dumps({
            "text": "bonjour", "language": "fr",
            "segments": [{"id": 0, "start": 0.0, "end": 0.9, "text": "bonjour"}],
        }).encode(), 200, 0

    monkeypatch.setattr(cloud, "_request", fake_request)
    result = cloud.groq_transcribe(wav, language="fr")
    assert result["segments"][0]["start"] == 0.0
    assert requests and requests[0].get_header("Authorization") == "Bearer test-groq"
    summary = budget.cloud_budget_summary()
    assert summary["rows"][0]["audio_seconds"] == pytest.approx(1.0)


def test_groq_normalizes_language_name_for_whisperx_alignment(
    cloud_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "french-label.wav"
    _write_wav(wav)

    def fake_request(request, **kwargs):
        return json.dumps({
            "text": "bonjour", "language": "French",
            "segments": [{"id": 0, "start": 0.0, "end": 0.9, "text": "bonjour"}],
        }).encode(), 200, 0

    monkeypatch.setattr(cloud, "_request", fake_request)
    result = cloud.groq_transcribe(wav, language="fr")
    assert result["language"] == "fr"
    assert result["provider_language"] == "French"


def test_gemini_structured_vision_is_metered(
    cloud_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"not-decoded-by-adapter")
    seen: list[dict] = []

    def fake_json_request(url, payload, **kwargs):
        seen.append(payload)
        return {
            "candidates": [{"content": {"parts": [{"text": '{"scene":"table"}'}]}}],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 15},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    data, meta = cloud.gemini_vision_json(
        image, system="system", prompt="prompt",
        schema={"type": "object", "properties": {"scene": {"type": "string"}}, "required": ["scene"]},
        max_output_tokens=100, timeout=5,
    )
    assert data == {"scene": "table"}
    assert meta["model"] == "gemini-3.1-flash-lite"
    assert seen[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert budget.cloud_budget_summary()["rows"][0]["images"] == 1


def test_default_llm_backend_does_not_enter_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mlomega_audio_elite import llm

    monkeypatch.delenv("MLOMEGA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("MLOMEGA_ENABLE_OLLAMA", "true")
    called = []

    def fake_ollama(payload, **kwargs):
        called.append(payload)
        return {"response": '{"ok":true}', "done": True, "done_reason": "stop"}

    monkeypatch.setattr(llm, "ollama_generate", fake_ollama)
    client = llm.OllamaJsonClient(base_url="http://local.invalid", model="local")
    assert client.require_json("s", "p", {"ok": True}) == {"ok": True}
    assert client.backend == "ollama"
    assert len(called) == 1
