"""CHANTIER 2 — one cache warm-up per unique episode, then a single settle wait.

Fakes only.  These prove the warm-up dedup and the single-settle barrier without
any real DeepSeek call or wall-clock wait.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mlomega_audio_elite import cloud_budget_v19 as budget  # noqa: F401 (schema side effects)
from mlomega_audio_elite import cloud_providers_v19 as cloud
from mlomega_audio_elite import brain2_strict_v13_2 as strict


@pytest.fixture
def cloud_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cloud.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.50")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    # Reset the process-wide warm-cache so digests do not leak between tests.
    cloud._BUNDLE_WARM_RESPONSES.clear()
    return db


def _fake_warm_only(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    sent: list[dict] = []

    def fake_json_request(url, payload, **kwargs):
        sent.append(payload)
        return {
            "choices": [{"message": {"content": '{"bundle_loaded":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    return sent


def test_warm_bundle_prefix_is_deduplicated_by_digest(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _fake_warm_only(monkeypatch)
    bundle = {"episode": {"episode_id": "ep-1"}, "turns": [{"text": "bonjour"}]}
    cloud.warm_bundle_prefix("ep-1", bundle, timeout=5)
    cloud.warm_bundle_prefix("ep-1", bundle, timeout=5)  # resume / repeat
    assert len(sent) == 1  # one paid warm-up for one digest


def test_pro_warm_episodes_one_per_unique_episode_single_settle(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_DEEPSEEK_CACHE_SETTLE_S", "0")  # no wall-clock wait in tests
    sent = _fake_warm_only(monkeypatch)
    sleeps: list[float] = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))

    monkeypatch.setenv("MLOMEGA_PRO_PREFIX_PRIME_OBS", "2")
    episodes = [
        ("ep-1", {"episode": {"episode_id": "ep-1"}}),
        ("ep-2", {"episode": {"episode_id": "ep-2"}}),
        ("ep-1", {"episode": {"episode_id": "ep-1"}}),  # duplicate: no extra priming
    ]
    strict._pro_warm_episode_prefixes(episodes)
    # The full-shape priming persists each UNIQUE episode's ENGINE prefix (a
    # request carrying the assistant warm + engine system), not the short warm.
    # The duplicate ep-1 is deduped, so exactly two unique episode bundles are
    # primed (each bundle is the 2nd/user message of a full-shape request).
    primed_bundles = {
        payload["messages"][1]["content"]
        for payload in sent
        if any(msg.get("role") == "assistant" for msg in payload["messages"])
    }
    assert len(primed_bundles) == 2  # ep-1 and ep-2; the duplicate added no priming
    # Settle is 0 in tests, so no wall-clock sleep, but never one-per-episode.
    assert sleeps == []


def test_pro_warm_episodes_waits_once_after_all_warmups(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_DEEPSEEK_CACHE_SETTLE_S", "3")
    _fake_warm_only(monkeypatch)
    sleeps: list[float] = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))
    strict._pro_warm_episode_prefixes([
        ("ep-1", {"episode": {"episode_id": "ep-1"}}),
        ("ep-2", {"episode": {"episode_id": "ep-2"}}),
    ])
    # ONE settle wait total, not one per episode.
    assert sleeps == [3.0]


def test_warmup_is_inert_without_episodes(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _fake_warm_only(monkeypatch)
    sleeps: list[float] = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))
    strict._pro_warm_episode_prefixes([])
    assert sent == [] and sleeps == []
