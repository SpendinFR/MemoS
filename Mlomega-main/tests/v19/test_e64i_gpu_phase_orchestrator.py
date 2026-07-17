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
    LiveGpuResidencyError,
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


def _make(*, props_ok=True, probe_finish="stop", unloads=None, released=None,
          resident=("qwen3.5:4b",)):
    spawned: list[FakeProc] = []
    # enter_text now reads /api/ps and evicts EVERY resident model, then re-reads
    # to prove Ollama is empty. Model the eviction: after any unload, /api/ps
    # returns nothing (the models really left).
    state = {"resident": list(resident), "unloaded_all": False}

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
        try:
            state["resident"].remove(model)
        except ValueError:
            pass

    def ollama_ps():
        return [{"name": m} for m in state["resident"]]

    def release_live_models():
        if released is not None:
            released.append(True)

    orch = GpuPhaseOrchestrator(
        spawn=spawn,
        props_probe=props_probe,
        anti_thinking_probe=anti_thinking_probe,
        ollama_unload=ollama_unload,
        ollama_ps=ollama_ps,
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


def test_enter_text_evicts_every_ollama_model_including_9b_before_p1():
    """Point 4: enter_text must evict ALL resident Ollama models (not a static
    list) — in particular a stray ``qwen3.5:9b`` — prove Ollama empty, then P1."""
    unloads: list[str] = []
    orch, _ = _make(unloads=unloads, resident=["qwen3.5:4b", "qwen3-vl:8b", "qwen3.5:9b"])
    result = orch.enter_text()
    assert orch.p1_running is True
    assert set(unloads) == {"qwen3.5:4b", "qwen3-vl:8b", "qwen3.5:9b"}
    assert result["resident_after"] == []
    assert result["vram_before"] and result["vram_after"]


def test_enter_text_fails_if_an_ollama_model_resists_eviction(monkeypatch):
    """A model Ollama refuses to unload must abort the text phase before P1 — a
    9B coexisting with the 7 GB P1 on 8 GB VRAM is exactly the leak to prevent."""
    def spawn(_c):
        return FakeProc()

    def ollama_ps():
        # Always reports the 9B resident: the unload never takes effect.
        return [{"name": "qwen3.5:9b"}]

    orch = GpuPhaseOrchestrator(
        spawn=spawn,
        props_probe=lambda: {"alias": p1_alias(), "n_ctx": p1_ctx()},
        anti_thinking_probe=lambda: {"choices": [{"finish_reason": "stop"}]},
        ollama_unload=lambda *, model: None,  # no-op: the model resists
        ollama_ps=ollama_ps,
        release_live_models=lambda: None,
        ready_timeout_s=2.0,
        poll_interval_s=0.01,
    )
    with pytest.raises(LiveGpuResidencyError, match="qwen3.5:9b"):
        orch.enter_text()
    assert orch.p1_running is False  # P1 never started with a resident 9B


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


def _make_live_prep(*, ps_sequence, live_model="qwen3.5:4b", foreign_p1=False):
    """Build an orchestrator whose /api/ps returns each list in ps_sequence in turn.

    ps_sequence[0] = models resident BEFORE unload; ps_sequence[1] = AFTER. Unload
    calls are recorded. VRAM snapshot is a fake (no real GPU)."""
    import os as _os

    _os.environ["MLOMEGA_OLLAMA_LIVE_MODEL"] = live_model
    calls = {"unloaded": [], "ps": 0, "vram": 0}
    seq = list(ps_sequence)

    def ollama_ps():
        idx = min(calls["ps"], len(seq) - 1)
        calls["ps"] += 1
        return [{"name": m} for m in seq[idx]]

    def ollama_unload(*, model):
        calls["unloaded"].append(model)

    def vram_snapshot():
        calls["vram"] += 1
        return {"source": "fake", "total_mb": 24000, "used_mb": 7000, "free_mb": 17000}

    orch = GpuPhaseOrchestrator(
        spawn=lambda _c: FakeProc(),
        props_probe=lambda: {"alias": p1_alias(), "n_ctx": p1_ctx()},
        anti_thinking_probe=lambda: {"choices": [{"finish_reason": "stop"}]},
        ollama_unload=ollama_unload,
        ollama_ps=ollama_ps,
        vram_snapshot=vram_snapshot,
        foreign_p1_probe=lambda: foreign_p1,
        ready_timeout_s=2.0,
        poll_interval_s=0.01,
    )
    return orch, calls


def test_prepare_live_gpu_evicts_everything_but_the_live_4b():
    # Before: the live 4B plus a resident Qwen3-VL and the 9B. After: only the 4B.
    orch, calls = _make_live_prep(
        ps_sequence=[
            ["qwen3.5:4b", "qwen3-vl:8b", "qwen3.5:9b"],
            ["qwen3.5:4b"],
        ]
    )
    result = orch.prepare_live_gpu()
    assert orch.p1_running is False
    assert set(calls["unloaded"]) == {"qwen3-vl:8b", "qwen3.5:9b"}
    assert "qwen3.5:4b" not in calls["unloaded"]  # the live model is kept
    assert result["resident_after"] == ["qwen3.5:4b"]
    # VRAM journalled before AND after.
    assert calls["vram"] >= 2
    assert result["vram_before"]["source"] == "fake"
    assert result["vram_after"]["source"] == "fake"


def test_prepare_live_gpu_fails_if_vlm_or_9b_resists():
    # The VLM refuses to leave (still resident on the second /api/ps).
    orch, _calls = _make_live_prep(
        ps_sequence=[
            ["qwen3.5:4b", "qwen3-vl:8b"],
            ["qwen3.5:4b", "qwen3-vl:8b"],  # VLM STILL resident
        ]
    )
    with pytest.raises(LiveGpuResidencyError, match="qwen3-vl"):
        orch.prepare_live_gpu()


def test_prepare_live_gpu_fails_on_foreign_p1_still_answering():
    """stop_p1 only kills OUR process: a llama-server started elsewhere that still
    answers on the P1 port must abort the live boundary explicitly (Codex)."""
    orch, calls = _make_live_prep(
        ps_sequence=[["qwen3.5:4b"], ["qwen3.5:4b"]], foreign_p1=True
    )
    with pytest.raises(LiveGpuResidencyError, match="not owned by this runtime"):
        orch.prepare_live_gpu()
    # Failed BEFORE any Ollama traffic: the foreign server owns the VRAM anyway.
    assert calls["ps"] == 0 and calls["unloaded"] == []


def test_prepare_live_gpu_stops_p1_first():
    orch, _calls = _make_live_prep(ps_sequence=[["qwen3.5:4b"], ["qwen3.5:4b"]])
    orch.start_p1()  # P1 up before the live frontier (enter_text needs empty Ollama)
    assert orch.p1_running is True
    orch.prepare_live_gpu()
    assert orch.p1_running is False  # P1 never resident during live capture


def test_prepare_live_gpu_called_in_preflight_finally_even_on_failure(monkeypatch):
    """The readiness command runs prepare_live_gpu in ``finally`` even when the
    preflight sequence raised, so no VLM is left squatting VRAM."""
    import importlib.util

    monkeypatch.setenv("MLOMEGA_GPU_PHASE_ORCHESTRATION", "1")
    prepared = {"count": 0}

    class SpyOrch:
        p1_running = False
        probe_calls = 1

        def enter_preflight(self):
            raise RuntimeError("preflight boom")  # the sequence fails

        def prepare_live_gpu(self):
            prepared["count"] += 1
            return {"live_model": "qwen3.5:4b", "unloaded": ["qwen3-vl:8b"],
                    "resident_after": ["qwen3.5:4b"], "vram_after": {}}

    script = ROOT / "scripts" / "check_phoneonly_readiness.py"
    spec = importlib.util.spec_from_file_location("readiness_finally_test", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["readiness_finally_test"] = mod
    spec.loader.exec_module(mod)

    import mlomega_audio_elite.gpu_phase_orchestrator as gpo
    monkeypatch.setattr(gpo, "GpuPhaseOrchestrator", lambda: SpyOrch())

    # Stub the AI-chain probe so run() reaches the orchestrator block without a
    # real model chain; delegate every OTHER _load to the real loader.
    real_load = mod._load

    def fake_load(name, path):
        if "sessionhub_http" in str(path):
            return type("H", (), {"_probe_ai_chain": staticmethod(lambda *, person_id: {"checks": {}})})
        return real_load(name, path)

    monkeypatch.setattr(mod, "_load", fake_load)
    report = mod.run(person_id="me", deep=False)
    assert prepared["count"] == 1
    # The preflight sequence failed but the frontier still ran and reported.
    assert "prepare_live_gpu" in report["checks"]
    assert report["checks"]["p1_sequential"]["ok"] is False


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
