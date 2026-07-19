from __future__ import annotations

"""PRO physical P1 frontier around the LOCAL EpisodeBuilder (HANDOFF §A).

The client-level frontier (llamacpp forced for EpisodeBuilder) is proven in
``test_pro_episode_builder_local.py``. These tests prove the PHYSICAL half the
handoff requires before any real resume: evict Ollama -> start P1 -> build ->
commit -> stop P1 in ``finally`` before any DeepSeek call, and NO P1 start when
the episodes are already complete. All fakes; no subprocess, no network."""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mlomega_audio_elite.gpu_phase_orchestrator import (  # noqa: E402
    GpuPhaseOrchestrator,
    p1_alias,
    p1_ctx,
)

pytestmark = pytest.mark.memory


class FakeProc:
    def __init__(self):
        self.alive = True
        self.terminated = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def _orchestrator(events: list[str]) -> GpuPhaseOrchestrator:
    state = {"resident": ["qwen3.5:4b"]}

    def ollama_unload(*, model):
        events.append(f"unload:{model}")
        try:
            state["resident"].remove(model)
        except ValueError:
            pass

    def spawn(_command):
        events.append("p1_spawn")
        return FakeProc()

    return GpuPhaseOrchestrator(
        spawn=spawn,
        props_probe=lambda: {"alias": p1_alias(), "n_ctx": p1_ctx()},
        anti_thinking_probe=lambda: {"choices": [{"finish_reason": "stop"}]},
        ollama_unload=ollama_unload,
        ollama_ps=lambda: [{"name": m} for m in state["resident"]],
        release_live_models=lambda: None,
        ready_timeout_s=2.0,
        poll_interval_s=0.01,
    )


def test_pro_local_text_phase_starts_p1_then_always_stops_it():
    events: list[str] = []
    orch = _orchestrator(events)
    with orch.pro_local_text_phase():
        assert orch.p1_running is True          # P1 up for the episode build
        assert "unload:qwen3.5:4b" in events    # Ollama evicted first
        events.append("build")
    assert orch.p1_running is False             # stopped BEFORE any cloud call
    assert events.index("build") > events.index("p1_spawn")


def test_pro_local_text_phase_stops_p1_in_finally_on_build_failure():
    events: list[str] = []
    orch = _orchestrator(events)
    with pytest.raises(RuntimeError, match="episode build boom"):
        with orch.pro_local_text_phase():
            assert orch.p1_running is True
            raise RuntimeError("episode build boom")
    # The failure propagates (no silent cloud fallback) AND P1 is gone.
    assert orch.p1_running is False


def _episode_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE episodes(episode_id TEXT PRIMARY KEY,"
        " source_conversation_id TEXT, metadata_json TEXT)"
    )
    return con


def _accepted_source() -> str:
    from mlomega_audio_elite import brain2_strict_v13_2 as mod

    try:
        from mlomega_audio_elite.brain2_conversation_episode import (
            CONVERSATION_EPISODE_BUILD_VERSION,
            conversation_episode_enabled,
        )
        if conversation_episode_enabled():
            return CONVERSATION_EPISODE_BUILD_VERSION
    except Exception:
        pass
    return mod.EPISODE_BUILD_VERSION


def test_complete_episodes_predicate_gates_the_boundary():
    from mlomega_audio_elite.brain2_strict_v13_2 import (
        _conversation_has_complete_episodes,
    )

    con = _episode_db()
    # No episodes -> boundary needed.
    assert _conversation_has_complete_episodes(con, "conv1") is False
    # Partial coverage -> still needed (P1 will rebuild; the authoritative
    # clean-up stays in _ensure_episodes_strict).
    con.execute(
        "INSERT INTO episodes VALUES('ep1','conv1',?)",
        (f'{{"episode_source": "{_accepted_source()}", "coverage_status": "partial"}}',),
    )
    assert _conversation_has_complete_episodes(con, "conv1") is False
    # Complete + compatible -> NO P1 start (handoff: reuse checkpoints).
    con.execute(
        "INSERT INTO episodes VALUES('ep2','conv1',?)",
        (f'{{"episode_source": "{_accepted_source()}", "coverage_status": "complete"}}',),
    )
    assert _conversation_has_complete_episodes(con, "conv1") is True
    # Read-only: nothing was deleted by the predicate.
    assert con.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 2


def test_boundary_decision_requires_pro_and_deepseek_backend(monkeypatch):
    from mlomega_audio_elite.brain2_strict_v13_2 import _episode_builder_forces_local

    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "deepseek")
    assert _episode_builder_forces_local() is False  # local mode: never
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    assert _episode_builder_forces_local() is True
    monkeypatch.setenv("MLOMEGA_LLM_BACKEND", "ollama")
    assert _episode_builder_forces_local() is False  # no cloud inheritance -> no frontier
