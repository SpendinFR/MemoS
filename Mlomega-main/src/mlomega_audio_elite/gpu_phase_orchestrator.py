from __future__ import annotations

"""Per-phase GPU arbitration for the PhoneOnly close-day (E64-i chantier 2).

The 9B "P1" text model (llama.cpp ``llama-server``, ~7 GB VRAM) must NEVER stay
resident while the real-time capture or the Deep Vision (Qwen3-VL via Ollama)
phase needs the GPU.  This module owns the single P1 subprocess and exposes the
phase sequence used by the post-stop / close-day runner:

    preflight  : start P1 -> prove it answers -> STOP it (proves availability
                 sequentially, never coexistence). Ends with P1 stopped.
    live       : Ollama 4B only. P1 must be stopped.
    text       : release the live Ollama models (keep_alive=0), START P1.
    vision     : STOP P1, hand the GPU to Qwen3-VL (Ollama).
    text again : restart P1 only if a later text stage requires it.

Everything is injectable (subprocess spawner + HTTP prober) so tests run with no
real llama-server and no real Ollama.  The canonical P1 command matches
docs/EXECUTOR_BUILD_GUIDE.md; the binary and model are overridable through
``MLOMEGA_LLAMACPP_SERVER_EXE`` / ``MLOMEGA_LLAMACPP_MODEL_GGUF``.
"""

import json
import os
import subprocess
import time
import urllib.request
from typing import Any, Callable, Optional

from .runtime_v18_7 import record_phase_event

# Defaults mirror the canonical command in docs/EXECUTOR_BUILD_GUIDE.md (~l.1186).
_DEFAULT_P1_EXE = r"C:\Users\wabad\llama-test\bin\llama-server.exe"
_DEFAULT_P1_MODEL = r"C:\Users\wabad\llama-test\models\Qwen3.5-9B-Q4_K_M.gguf"
_DEFAULT_P1_ALIAS = "qwen9b-p1-24k-mlomega"
_DEFAULT_P1_HOST = "127.0.0.1"
_DEFAULT_P1_PORT = 8080
_DEFAULT_P1_CTX = 24576


def p1_server_exe() -> str:
    return os.environ.get("MLOMEGA_LLAMACPP_SERVER_EXE", _DEFAULT_P1_EXE)


def p1_model_gguf() -> str:
    return os.environ.get("MLOMEGA_LLAMACPP_MODEL_GGUF", _DEFAULT_P1_MODEL)


def p1_alias() -> str:
    return os.environ.get("MLOMEGA_LLAMACPP_ALIAS", _DEFAULT_P1_ALIAS)


def p1_host() -> str:
    return os.environ.get("MLOMEGA_LLAMACPP_HOST", _DEFAULT_P1_HOST)


def p1_port() -> int:
    try:
        return int(os.environ.get("MLOMEGA_LLAMACPP_PORT", str(_DEFAULT_P1_PORT)))
    except ValueError:
        return _DEFAULT_P1_PORT


def p1_ctx() -> int:
    try:
        return int(os.environ.get("MLOMEGA_LLAMACPP_CTX", str(_DEFAULT_P1_CTX)))
    except ValueError:
        return _DEFAULT_P1_CTX


def p1_base_url() -> str:
    return f"http://{p1_host()}:{p1_port()}"


def p1_command() -> list[str]:
    """The canonical, env-overridable llama-server launch command for P1."""
    return [
        p1_server_exe(),
        "-m", p1_model_gguf(),
        "--alias", p1_alias(),
        "-c", str(p1_ctx()),
        "--parallel", "1",
        "--cont-batching",
        "-ngl", "99",
        "--flash-attn", "on",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "--jinja",
        "--chat-template-kwargs", '{"enable_thinking":false}',
        "--reasoning-budget", "0",
        "-n", "4096",
        "--host", p1_host(),
        "--port", str(p1_port()),
    ]


def _default_spawn(command: list[str]) -> Any:
    # A detached-enough process whose stdout/stderr do not block. The caller owns
    # its lifecycle explicitly (start -> stop), never the interpreter exit.
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(p1_server_exe()) or None,
    )


def _http_get_json(url: str, *, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class P1UnavailableError(RuntimeError):
    """Raised when P1 could not start, expose /props, or pass the anti-thinking probe."""


class GpuPhaseOrchestrator:
    """Owns the single P1 subprocess and the serial GPU phase transitions."""

    def __init__(
        self,
        *,
        spawn: Callable[[list[str]], Any] | None = None,
        props_probe: Callable[[], dict[str, Any]] | None = None,
        anti_thinking_probe: Callable[[], dict[str, Any]] | None = None,
        ollama_unload: Callable[..., None] | None = None,
        release_live_models: Callable[[], None] | None = None,
        ready_timeout_s: float = 120.0,
        poll_interval_s: float = 0.5,
    ) -> None:
        self._spawn = spawn or _default_spawn
        self._props_probe = props_probe or self._default_props_probe
        self._anti_thinking_probe = anti_thinking_probe or self._default_anti_thinking_probe
        self._ollama_unload = ollama_unload or self._default_ollama_unload
        self._release_live_models = release_live_models or self._default_release_live_models
        self.ready_timeout_s = max(1.0, float(ready_timeout_s))
        self.poll_interval_s = max(0.01, float(poll_interval_s))
        self._proc: Any | None = None
        self.probe_calls = 0

    # -- default real transports (never touched in tests) ------------------
    def _default_props_probe(self) -> dict[str, Any]:
        return _http_get_json(p1_base_url() + "/props", timeout=5.0)

    def _default_anti_thinking_probe(self) -> dict[str, Any]:
        return _http_post_json(
            p1_base_url() + "/v1/chat/completions",
            {
                "model": p1_alias(),
                "messages": [{"role": "user", "content": 'Return exactly {"ok":true} as JSON.'}],
                "max_tokens": 32,
                "stream": False,
            },
            timeout=30.0,
        )

    @staticmethod
    def _default_ollama_unload(*, model: str) -> None:
        from .llm import ollama_unload

        ollama_unload(model=model)

    @staticmethod
    def _default_release_live_models() -> None:
        from .runtime_v18_7 import release_live_model_caches

        release_live_model_caches()

    # -- P1 lifecycle -------------------------------------------------------
    @property
    def p1_running(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        poll = getattr(proc, "poll", None)
        return poll is None or poll() is None

    def start_p1(self) -> dict[str, Any]:
        """Start P1, wait for /props (alias+n_ctx), then run the anti-thinking probe."""
        if self.p1_running:
            return {"status": "already_running", "alias": p1_alias()}
        record_phase_event("p1_start_requested", alias=p1_alias(), model=p1_model_gguf())
        self._proc = self._spawn(p1_command())
        props = self._await_props()
        probe = self._run_anti_thinking_probe()
        record_phase_event("p1_ready", alias=p1_alias(), n_ctx=props.get("n_ctx"))
        return {"status": "ready", "props": props, "anti_thinking": probe}

    def _await_props(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.ready_timeout_s
        last_error: Optional[str] = None
        while time.monotonic() < deadline:
            if not self.p1_running:
                raise P1UnavailableError("P1 process exited before /props was reachable")
            try:
                props = self._props_probe() or {}
            except Exception as exc:  # transport not up yet
                last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                time.sleep(self.poll_interval_s)
                continue
            alias = str(props.get("alias") or (props.get("default_generation_settings") or {}).get("alias") or "")
            n_ctx = props.get("n_ctx") or (props.get("default_generation_settings") or {}).get("n_ctx")
            if alias and alias == p1_alias() and int(n_ctx or 0) >= p1_ctx():
                return dict(props)
            last_error = f"props mismatch alias={alias!r} n_ctx={n_ctx!r}"
            time.sleep(self.poll_interval_s)
        self.stop_p1()
        raise P1UnavailableError(f"P1 /props not ready in {self.ready_timeout_s}s: {last_error}")

    def _run_anti_thinking_probe(self) -> dict[str, Any]:
        self.probe_calls += 1
        try:
            result = self._anti_thinking_probe() or {}
        except Exception as exc:
            self.stop_p1()
            raise P1UnavailableError(
                f"P1 anti-thinking probe failed: {type(exc).__name__}: {str(exc)[:200]}"
            ) from exc
        finish = None
        choices = result.get("choices") if isinstance(result, dict) else None
        if isinstance(choices, list) and choices:
            finish = (choices[0] or {}).get("finish_reason")
        if str(finish or "") != "stop":
            self.stop_p1()
            raise P1UnavailableError(
                f"P1 anti-thinking probe did not finish=stop (got {finish!r}) -- reasoning leaked"
            )
        return dict(result)

    def stop_p1(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        proc = self._proc
        if proc is None:
            return {"status": "not_running"}
        record_phase_event("p1_stop_requested", alias=p1_alias())
        try:
            if getattr(proc, "poll", lambda: None)() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout_s)
                except Exception:
                    kill = getattr(proc, "kill", None)
                    if kill is not None:
                        kill()
                        try:
                            proc.wait(timeout=timeout_s)
                        except Exception:
                            pass
        finally:
            self._proc = None
        record_phase_event("p1_stopped", alias=p1_alias())
        return {"status": "stopped"}

    # -- phase transitions --------------------------------------------------
    def enter_preflight(self) -> dict[str, Any]:
        """Prove P1 availability SEQUENTIALLY, then leave it STOPPED."""
        start = self.start_p1()
        stop = self.stop_p1()
        assert not self.p1_running, "preflight must leave P1 stopped"
        return {"phase": "preflight", "p1": start, "p1_stopped": stop}

    def enter_live(self) -> dict[str, Any]:
        """Capture phase: Ollama 4B only. P1 must not be resident."""
        stopped = self.stop_p1() if self.p1_running else {"status": "not_running"}
        assert not self.p1_running, "P1 must never be active during live capture"
        return {"phase": "live", "p1_stopped": stopped}

    def enter_text(self) -> dict[str, Any]:
        """Nightly text phase: release live Ollama models, then start P1."""
        self._release_live_models()
        for model in self._live_ollama_models():
            try:
                self._ollama_unload(model=model)
            except Exception as exc:
                record_phase_event("ollama_unload_failed", model=model, error=str(exc)[:200])
        started = self.start_p1()
        return {"phase": "text", "p1": started, "released_live": True}

    def enter_vision(self) -> dict[str, Any]:
        """Deep Vision phase: STOP P1 so Qwen3-VL (Ollama) owns the GPU."""
        stopped = self.stop_p1() if self.p1_running else {"status": "not_running"}
        assert not self.p1_running, "P1 must never be active during Deep Vision"
        return {"phase": "vision", "p1_stopped": stopped}

    @staticmethod
    def _live_ollama_models() -> list[str]:
        from .config import get_settings

        settings = get_settings()
        models = {
            str(settings.ollama_live_model or "").strip(),
            str(os.environ.get("MLOMEGA_VLM_MODEL") or "").strip(),
        }
        return sorted(m for m in models if m)

    def __enter__(self) -> "GpuPhaseOrchestrator":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # A phase orchestrator must never leak P1 across the process boundary.
        self.stop_p1()


__all__ = [
    "GpuPhaseOrchestrator",
    "P1UnavailableError",
    "p1_command",
    "p1_base_url",
    "p1_server_exe",
    "p1_model_gguf",
    "p1_alias",
]
