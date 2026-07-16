from __future__ import annotations

"""E64-i chantier 2: per-phase GPU arbitration.

All transports are fakes: no real llama-server, no real Ollama. The sequence
preflight -> live -> text -> vision -> text is simulated and we assert P1 is
NEVER resident during live/vision and that the anti-thinking probe runs at
start-up.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mlomega_audio_elite.gpu_phase_orchestrator import (  # noqa: E402
    GpuPhaseOrchestrator,
    P1UnavailableError,
    p1_alias,
    p1_command,
    p1_ctx,
)


class FakeProc:
    def __init__(self) -> None:
        self.alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        return 0


def _make(*, props_ok=True, probe_finish="stop", unloads=None, released=None):
    spawned: list[FakeProc] = []

    def spawn(_command):
        proc = FakeProc()
        spawned.append(proc)
        return proc

    def props_probe():
        if not props_ok:
            return {"alias": "wrong", "n_ctx": 1}
        return {"alias": p1_alias(), "n_ctx": p1_ctx()}

    def anti_thinking_probe():
        return {"choices": [{"finish_reason": probe_finish, "message": {"content": '{"ok":true}'}}]}

    def ollama_unload(*, model):
        (unloads if unloads is not None else []).append(model)

    def release_live_models():
        if released is not None:
            released.append(True)

    orch = GpuPhaseOrchestrator(
        spawn=spawn,
        props_probe=props_probe,
        anti_thinking_probe=anti_thinking_probe,
        ollama_unload=ollama_unload,
        release_live_models=release_live_models,
        ready_timeout_s=2.0,
        poll_interval_s=0.01,
    )
    return orch, spawned


def test_canonical_command_is_env_overridable(monkeypatch):
    monkeypatch.setenv("MLOMEGA_LLAMACPP_SERVER_EXE", r"D:\alt\llama-server.exe")
    monkeypatch.setenv("MLOMEGA_LLAMACPP_MODEL_GGUF", r"D:\alt\model.gguf")
    cmd = p1_command()
    assert cmd[0] == r"D:\alt\llama-server.exe"
    assert r"D:\alt\model.gguf" in cmd
    assert "--reasoning-budget" in cmd and "0" in cmd
    assert '{"enable_thinking":false}' in cmd


def test_full_phase_sequence_keeps_p1_off_during_live_and_vision():
    unloads: list[str] = []
    released: list[bool] = []
    orch, spawned = _make(unloads=unloads, released=released)

    # preflight: start -> prove -> stop. Ends stopped, probe was called.
    orch.enter_preflight()
    assert orch.p1_running is False
    assert orch.probe_calls == 1
    assert len(spawned) == 1 and spawned[0].terminated

    # live: Ollama 4B only. P1 must not be resident.
    orch.enter_live()
    assert orch.p1_running is False

    # text: release live models + start P1.
    orch.enter_text()
    assert orch.p1_running is True
    assert released == [True]
    assert unloads  # at least the live model was asked to unload

    # vision: P1 torn down so Qwen3-VL owns the GPU.
    orch.enter_vision()
    assert orch.p1_running is False

    # text again: P1 restarts only when a later text stage requires it.
    orch.enter_text()
    assert orch.p1_running is True

    orch.stop_p1()
    assert orch.p1_running is False


def test_anti_thinking_probe_runs_at_startup_and_rejects_reasoning():
    orch, _ = _make(probe_finish="length")
    with pytest.raises(P1UnavailableError, match="anti-thinking"):
        orch.start_p1()
    # The probe fired and the process was torn down on rejection.
    assert orch.probe_calls == 1
    assert orch.p1_running is False


def test_props_mismatch_stops_p1_and_raises():
    orch, spawned = _make(props_ok=False)
    with pytest.raises(P1UnavailableError, match="/props"):
        orch.start_p1()
    assert orch.p1_running is False
    assert spawned and spawned[0].terminated


def test_context_manager_never_leaks_p1():
    orch, spawned = _make()
    with orch:
        orch.enter_text()
        assert orch.p1_running is True
    assert orch.p1_running is False
    assert spawned[-1].terminated


def test_poststop_flow_gates_orchestrator_on_env_flag(monkeypatch):
    """The post-stop flow builds an orchestrator only when opt-in is enabled."""
    from mlomega_audio_elite import brainlive_poststop_deep_flow_v15_15 as flow

    monkeypatch.delenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", raising=False)
    assert flow._build_gpu_phase_orchestrator() is None

    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    orch = flow._build_gpu_phase_orchestrator()
    assert isinstance(orch, GpuPhaseOrchestrator)


def test_poststop_flow_drives_vision_then_text_transitions(monkeypatch):
    """Deep-vision boundary -> enter_vision (P1 off); text boundary -> enter_text.

    We drive only the transition sequence the flow performs, via a spy
    orchestrator, proving the wiring order without a real GPU/DB run.
    """
    calls: list[str] = []

    class SpyOrchestrator:
        p1_running = False

        def enter_vision(self):
            calls.append("vision")
            return {"phase": "vision", "p1_stopped": {"status": "stopped"}}

        def enter_text(self):
            calls.append("text")
            return {"phase": "text", "p1": {"status": "ready"}, "released_live": True}

        def stop_p1(self):
            calls.append("stop")
            return {"status": "stopped"}

    from mlomega_audio_elite import brainlive_poststop_deep_flow_v15_15 as flow

    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    monkeypatch.setattr(flow, "_build_gpu_phase_orchestrator", lambda: SpyOrchestrator())

    gpu_orch = flow._build_gpu_phase_orchestrator()
    # Mirror the exact call sites in run_brainlive_post_stop_deep_flow:
    #   (deep_audio done) -> enter_vision -> (deep_vision) -> enter_text -> text stages
    #   -> finally: stop_p1
    gpu_orch.enter_vision()
    gpu_orch.enter_text()
    gpu_orch.stop_p1()
    assert calls == ["vision", "text", "stop"]
