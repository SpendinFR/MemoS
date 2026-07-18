from __future__ import annotations

"""V19 live-PC HTTP front for :class:`SessionHub` + unified WebRTC signaling.

This is the E24 HTTP server that fronts the in-process :class:`SessionHub`
(``services/live-pc/sessionhub.py``) *without rewriting it*. It exposes exactly
the routes/JSON the Unity ``SessionHubClient.cs`` (E23) already speaks:

    POST /session/create      {device_id}
         -> {session_id, token, created_at_utc}          (SessionHub.create_session)
    POST /session/clock-sync  {session_id, token, client_send_ns}
         -> {server_recv_ns, server_send_ns}             (begin/complete_clock_sync)
    POST /session/renew       {session_id, token}
         -> {token, created_at_utc}                      (re-issue ephemeral token)
    GET  /health              -> readiness snapshot

Auth: ``/session/renew`` and ``/session/clock-sync`` require the ephemeral
session token issued by ``/session/create`` (``SessionHub.authenticate``). A
mismatched ``(session_id, token)`` pair is refused with HTTP 401.

Clock-sync arithmetic stays split exactly as the C# client expects: the server
returns the two server monotonic stamps (``server_recv_ns`` / ``server_send_ns``)
and the client computes the offset/RTT with the *same formulas* as
``SessionHub.complete_clock_sync`` (proven numerically in
``tests/v19/test_sessionhub_http.py``). The server also records the sample on
the session (via ``complete_clock_sync``) so ``current_offset_ns`` is available
server-side for degraded-mode/health, using the client-relayed
``client_send_ns`` and a server-observed ``client_recv_ns`` estimate.

Unified media signaling: ``POST /webrtc/offer`` (SDP offer in -> SDP answer out)
requires a valid session token and delegates to a single shared
:class:`AiortcIngress`, so ``simulators/fake_xr_device`` and the future Android
``LiveTransportPlugin`` negotiate through one stable endpoint instead of the
ingress' own ad-hoc ``/offer`` port.

Run standalone::

    python services/live-pc/sessionhub_http.py            # port 8710 (matches
                                                           # MLOmegaConfig.cs)

Port 8710 is the SessionHub HTTP port hard-wired in
``apps/xr-mobile/Assets/Scripts/Core/MLOmegaConfig.cs`` (87xx range, never 8766).
"""

import sys
import time
import asyncio
import json
import os
import shutil
import subprocess
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

# Resolve the monorepo root so ``packages`` / sibling live-pc modules import
# whether launched as a script or loaded via importlib in tests.
_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
for _path in (_ROOT, _SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from mlomega_audio_elite.runtime_environment_v19 import (
    configure_windows_cuda_dlls,
    sanitize_blackhole_proxy_env,
)

_REMOVED_BLACKHOLE_PROXIES = sanitize_blackhole_proxy_env()
_CUDA_ENV_OK, _CUDA_ENV_DETAIL = configure_windows_cuda_dlls(_ROOT)
if not _CUDA_ENV_OK:
    raise RuntimeError(f"SessionHub CUDA/cuDNN environment invalid: {_CUDA_ENV_DETAIL}")

# ``sessionhub`` and ``gateway`` are sibling files in this non-package directory;
# load them by path so this module works under both plain execution and the
# importlib-based test harness used across tests/v19.
import importlib.util


def _load_sibling(name: str, filename: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_sessionhub = _load_sibling("sessionhub", "sessionhub.py")
SessionHub = _sessionhub.SessionHub
Session = _sessionhub.Session

# Gateway (aiortc) is optional; the SessionHub routes work without it. The
# /webrtc/offer route is only wired when aiortc is importable.
_gateway = _load_sibling("gateway", "gateway.py")

# Import FastAPI symbols at module scope. FastAPI resolves route annotations via
# typing.get_type_hints against the function's __globals__ (this module), not its
# closure — so ``Request`` MUST live here, not inside create_app, or the special
# Request parameter is mis-parsed as a query field.
try:
    from fastapi import FastAPI, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - only without API deps
    FastAPI = None  # type: ignore[assignment,misc]
    HTTPException = Exception  # type: ignore[assignment,misc]
    Request = Any  # type: ignore[assignment,misc]
    FASTAPI_AVAILABLE = False


DEFAULT_PORT = 8710  # MLOmegaConfig.cs SessionHubPort

# E47-C: the manifest key describing Android device-local models the phone fetches
# from the PC at first launch (offline ASR/KWS + gesture). Served by the
# /models/device provisioning endpoints below.
_MANIFEST_PATH = _ROOT / "configs" / "MODEL_MANIFEST.yaml"


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_device_manifest() -> dict[str, dict[str, Any]]:
    """Read the ``device:`` section of MODEL_MANIFEST.yaml (E47-C). {} if absent."""
    try:
        import yaml

        data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
        device = data.get("device", {}) if isinstance(data, dict) else {}
        return {str(k): v for k, v in device.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _device_artifact_path(spec: dict[str, Any]) -> Path | None:
    """The on-disk file the device downloads for a manifest entry.

    For a single-file entry (MediaPipe .task) it is ``path`` directly. For an
    archive entry (sherpa .tar.bz2) the phone receives the pre-fetched archive, so
    the served artefact is the archive next to the extracted directory (fetched by
    ``fetch_models_v19.py --device``). Returns None when nothing is on disk yet."""
    path = spec.get("path")
    if not path:
        return None
    resolved = _ROOT / str(path)
    if spec.get("archive"):
        extract_to = _ROOT / str(spec.get("extract_to") or "models/device")
        archive_file = extract_to / Path(str(spec["archive"])).name
        if archive_file.exists():
            return archive_file
        return None
    return resolved if resolved.exists() else None


def build_device_manifest_payload() -> dict[str, Any]:
    """Provisioning manifest served to the phone: one entry per device model with
    its name/kind/license/sha256 and a stable download ``endpoint``. Only entries
    whose artefact is present on the PC (already fetched) are marked available."""
    device = load_device_manifest()
    models = []
    for name, spec in device.items():
        artefact = _device_artifact_path(spec)
        is_archive = bool(spec.get("archive"))
        sha_key = "archive_sha256" if is_archive else "sha256"
        sha = str(spec.get(sha_key) or "")
        if sha == "PENDING_FETCH":
            # Prefer the real on-disk hash once fetched, so the phone can verify.
            sha = _sha256_file(artefact) if artefact is not None else ""
        entry = {
            "name": name,
            "kind": spec.get("kind"),
            "platform": spec.get("platform", "android"),
            "license": spec.get("license"),
            "format": "archive_tar_bz2" if is_archive else "file",
            "filename": Path(str(artefact)).name if artefact is not None else None,
            "sha256": sha or None,
            "available": artefact is not None,
            "endpoint": f"/models/device/{name}",
        }
        # E48-A: multi-file models (the OPUS-MT translation entries) land several
        # single-file artefacts into one per-model dir on the phone. ``target_subdir``
        # (additive, absent on every pre-E48-A entry) tells the client which
        # subdirectory under models/ to place the file in, reproducing the repo
        # layout. Pre-E48-A entries omit it → the phone keeps its flat placement.
        if spec.get("target_subdir"):
            entry["target_subdir"] = str(spec["target_subdir"])
        models.append(entry)
    return {"models": models, "count": len(models)}


def _url_ready(url: str, *, timeout: float = 0.5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - localhost only
            code = int(getattr(response, "status", 200))
        return 200 <= code < 500, f"http_{code}"
    except Exception as exc:
        return False, type(exc).__name__


def _ollama_models_ready(*, timeout: float = 0.8) -> tuple[bool, Any]:
    backend = os.environ.get("MLOMEGA_LLM_BACKEND", "ollama").strip().lower()
    required = [
        os.environ.get("MLOMEGA_OLLAMA_LIVE_MODEL", "qwen3.5:4b"),
        os.environ.get("MLOMEGA_VLM_MODEL", "moondream"),
        os.environ.get("MLOMEGA_OFFLINE_VLM_MODEL")
        or os.environ.get("MLOMEGA_VLM_HEAVY_MODEL")
        or "qwen3-vl:8b",
    ]
    if backend == "ollama":
        required.append(os.environ.get("MLOMEGA_OLLAMA_MODEL", "qwen3.5:9b"))
    required = list(dict.fromkeys(str(value).strip() for value in required if str(value).strip()))
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        installed = {
            str(item.get("name") or item.get("model"))
            for item in (payload.get("models") or []) if isinstance(item, dict)
        }
        def present(name: str) -> bool:
            return name in installed or (":" not in name and f"{name}:latest" in installed)

        missing = [name for name in required if not present(name)]
        return not missing, {
            "backend": backend, "required": required, "installed": sorted(installed), "missing": missing,
            "fix": ("ollama pull " + " ; ollama pull ".join(missing)) if missing else None,
        }
    except Exception as exc:
        return False, {
            "backend": backend, "required": required, "error": type(exc).__name__,
            "fix": "Demarre Ollama avant FirstTry (meme avec llama.cpp: le live et les VLM utilisent Ollama).",
        }


def _probe_ai_chain(*, person_id: str = "me", deep: bool = False) -> dict[str, Any]:
    """Bounded dependency snapshot for /health and strict /ready."""
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool, detail: Any) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    try:
        from mlomega_audio_elite.db import connect

        with connect() as con:
            con.execute("SELECT 1").fetchone()
        record("db", True, "sqlite_readable")
    except Exception as exc:
        record("db", False, f"{type(exc).__name__}: {str(exc)[:160]}")

    core_python = _ROOT / ".venv" / "Scripts" / "python.exe"
    close_day_preflight = _ROOT / "scripts" / "check_close_day_preflight.py"
    if not core_python.exists() or not close_day_preflight.exists():
        record(
            "close_day_env",
            False,
            {"python": str(core_python), "preflight": str(close_day_preflight)},
        )
    elif deep:
        try:
            proc = subprocess.run(
                [str(core_python), str(close_day_preflight), "--json"],
                cwd=str(_ROOT),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=float(os.environ.get("MLOMEGA_PREFLIGHT_TIMEOUT_S", "600")),
                check=False,
            )
            raw = (proc.stdout or "").strip().splitlines()
            detail: Any = json.loads(raw[-1]) if raw else {"stderr": (proc.stderr or "")[-500:]}
            record("close_day_env", proc.returncode == 0, detail)
        except Exception as exc:
            record("close_day_env", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    else:
        record("close_day_env", True, str(core_python))
    detector = _ROOT / "models" / "yolox_nano.onnx"
    record("detector_model", detector.exists(), str(detector))
    record("ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg"))

    try:
        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(directory="")
        providers = list(ort.get_available_providers())
        if deep and detector.exists():
            session = ort.InferenceSession(
                str(detector), providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
            )
            providers = list(session.get_providers())
        record("onnx_cuda", "CUDAExecutionProvider" in providers, providers)
    except Exception as exc:
        record("onnx_cuda", False, f"{type(exc).__name__}: {str(exc)[:160]}")

    try:
        import importlib.util as importlib_util

        record("asr", importlib_util.find_spec("faster_whisper") is not None, "faster_whisper")
    except Exception as exc:
        record("asr", False, type(exc).__name__)

    if deep and checks.get("asr", {}).get("ok"):
        try:
            audio_mod = _load_sibling("v19_readiness_audiort", "audiort.py")
            transcriber = audio_mod.WhisperTranscriber(model_size="small")
            model = transcriber._ensure()
            record(
                "asr",
                model is not None and transcriber.available,
                {"model": "small", "device": transcriber.device},
            )
            transcriber._model = None
        except Exception as exc:
            record("asr", False, f"{type(exc).__name__}: {str(exc)[:160]}")

        try:
            tts_mod = _load_sibling("v19_readiness_tts", "tts_local.py")
            provider = tts_mod.build_tts_provider()
            wav = provider.speak("Test audio", lang="fr")
            record("tts", bool(wav and wav[:4] == b"RIFF"), getattr(provider, "name", type(provider).__name__))
        except Exception as exc:
            record("tts", False, f"{type(exc).__name__}: {str(exc)[:160]}")

    ollama_ok, ollama_detail = _ollama_models_ready()
    qdrant_ok, qdrant_detail = _url_ready("http://127.0.0.1:6333/collections")
    record("ollama", ollama_ok, ollama_detail)
    record("qdrant", qdrant_ok, qdrant_detail)

    try:
        free_gb = shutil.disk_usage(_ROOT).free / (1024 ** 3)
        record("disk", free_gb >= 2.0, {"free_gb": round(free_gb, 2), "minimum_gb": 2.0})
    except Exception as exc:
        record("disk", False, type(exc).__name__)

    try:
        device_specs = load_device_manifest()
        missing = [name for name, spec in device_specs.items() if _device_artifact_path(spec) is None]
        record("device_models", not missing, {"count": len(device_specs), "missing": missing})
    except Exception as exc:
        record("device_models", False, f"{type(exc).__name__}: {str(exc)[:160]}")

    required = (
        "db", "close_day_env", "detector_model", "ffmpeg", "onnx_cuda",
        "asr", "ollama", "qdrant", "disk", "device_models",
    )
    if deep:
        required = (*required, "tts")
    ready = all(checks.get(name, {}).get("ok") for name in required)
    return {
        "ready": ready,
        "person_id": person_id,
        "checks": checks,
        "failed": [name for name in required if not checks.get(name, {}).get("ok")],
    }


def _preflight_receipt_check(*, person_id: str) -> tuple[bool, dict[str, Any]]:
    """Validate the strict external preflight without loading GPU models again."""
    path = Path(os.environ.get(
        "MLOMEGA_PREFLIGHT_RECEIPT",
        str(_ROOT / "storage" / "runtime" / "phoneonly_readiness.json"),
    ))
    ttl_s = float(os.environ.get("MLOMEGA_PREFLIGHT_RECEIPT_TTL_S", "86400"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age_s = max(0.0, time.time() - float(payload.get("created_at_epoch") or 0.0))
        fingerprint = dict(payload.get("fingerprint") or {})
        expected = {
            "person_id": person_id,
            "llm_backend": os.environ.get("MLOMEGA_LLM_BACKEND", "ollama"),
            "llamacpp_base_url": os.environ.get("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080"),
            "llamacpp_model": os.environ.get("MLOMEGA_LLAMACPP_MODEL", ""),
            "poststop_context": os.environ.get("MLOMEGA_OLLAMA_CONTEXT_POSTSTOP", "16384"),
            "live_model": os.environ.get("MLOMEGA_OLLAMA_LIVE_MODEL", "qwen3.5:4b"),
            "offline_vlm_model": (
                os.environ.get("MLOMEGA_OFFLINE_VLM_MODEL")
                or os.environ.get("MLOMEGA_VLM_HEAVY_MODEL")
                or "qwen3-vl:8b"
            ),
            "gpu_phase_orchestration": os.environ.get("MLOMEGA_GPU_PHASE_ORCHESTRATION", "0"),
        }
        mismatches = {
            key: {"expected": value, "observed": fingerprint.get(key)}
            for key, value in expected.items()
            if str(fingerprint.get(key)) != str(value)
        }
        checks = dict(payload.get("checks") or {})
        ok = bool(
            payload.get("ready")
            and payload.get("mode") == "deep"
            and checks
            and all(checks.values())
            and age_s <= ttl_s
            and not mismatches
        )
        return ok, {
            "path": str(path),
            "age_s": round(age_s, 1),
            "ttl_s": ttl_s,
            "mode": payload.get("mode"),
            "mismatches": mismatches,
            "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        }
    except Exception as exc:
        return False, {
            "path": str(path),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "fix": "run scripts/check_phoneonly_readiness.py --deep before SessionHub",
        }


def create_app(
    hub: "SessionHub | None" = None,
    ingress: Any | None = None,
    *,
    enable_signaling: bool = True,
    runtime_manager: Any | None = None,
    person_id: str = "me",
    readiness_probe: Callable[[], dict[str, Any]] | None = None,
):
    """Build the FastAPI app fronting ``hub`` and (optionally) media signaling.

    Parameters
    ----------
    hub:
        The :class:`SessionHub` to expose. A fresh one is created if omitted.
    ingress:
        An :class:`AiortcIngress` used for ``/webrtc/offer``. If omitted and
        aiortc is available, one is created lazily on first offer. Injected in
        tests to assert frame delivery.
    enable_signaling:
        When False, ``/webrtc/offer`` is not registered (SessionHub-only server).
    """
    if not FASTAPI_AVAILABLE:  # pragma: no cover - only without API deps
        raise RuntimeError("fastapi is required for sessionhub_http.create_app()")

    hub = hub or SessionHub()
    if runtime_manager is None and ingress is None and enable_signaling and _gateway.AIORTC_AVAILABLE:
        runtime_mod = _load_sibling("phoneonly_runtime", "phoneonly_runtime.py")
        runtime_manager = runtime_mod.SinglePhoneRuntimeManager(person_id=person_id)

    @asynccontextmanager
    async def _lifespan(application: Any):
        manager = application.state.runtime_manager
        if manager is not None and hasattr(manager, "startup_recovery"):
            application.state.recovery_task = asyncio.create_task(manager.startup_recovery())
        if manager is not None and hasattr(manager, "start_watchdog"):
            manager.start_watchdog()
        if enable_signaling:
            async def _readiness_after_recovery() -> dict[str, Any]:
                if application.state.recovery_task is not None:
                    await asyncio.gather(application.state.recovery_task, return_exceptions=True)
                return await asyncio.to_thread(readiness_probe)

            application.state.readiness_task = asyncio.create_task(_readiness_after_recovery())
        try:
            yield
        finally:
            recovery_task = application.state.recovery_task
            if recovery_task is not None:
                await asyncio.gather(recovery_task, return_exceptions=True)
            readiness_task = application.state.readiness_task
            if readiness_task is not None:
                await asyncio.gather(readiness_task, return_exceptions=True)
            manager = application.state.runtime_manager
            if manager is not None and hasattr(manager, "shutdown"):
                await manager.shutdown()
            elif application.state.ingress is not None and hasattr(application.state.ingress, "close"):
                await application.state.ingress.close()

    app = FastAPI(title="MLOmega V19 SessionHub HTTP", lifespan=_lifespan)
    # companion-web can probe this :8710 health from its :8706 origin while
    # resolving LAN/Tailscale endpoints. No cross-origin mutation is enabled.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.hub = hub
    app.state.ingress = ingress
    app.state.runtime_manager = runtime_manager
    app.state.recovery_task = None
    app.state.readiness_cache = None
    app.state.readiness_cache_at = 0.0
    app.state.readiness_task = None
    if readiness_probe is None:
        def _production_readiness_probe() -> dict[str, Any]:
            # Never run the heavy GPU probe in SessionHub: /health refreshes every
            # five minutes and would otherwise contend with live Whisper/YOLOX.
            report = dict(_probe_ai_chain(person_id=person_id, deep=False))
            checks = dict(report.get("checks") or {})
            if os.environ.get(
                "MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING",
                os.environ.get("MLOMEGA_GPU_PHASE_ORCHESTRATION", "0"),
            ).strip().lower() in {"1", "true", "yes", "on"}:
                receipt_ok, receipt_detail = _preflight_receipt_check(person_id=person_id)
                checks["deep_preflight_receipt"] = {"ok": receipt_ok, "detail": receipt_detail}
            report["checks"] = checks
            report["ready"] = all(bool(check.get("ok")) for check in checks.values())
            report["failed"] = [name for name, check in checks.items() if not check.get("ok")]
            return report

        readiness_probe = _production_readiness_probe

    def _authenticate(session_id: str, token: str) -> "Session":
        session = hub.authenticate(token)
        if session is None or session.session_id != session_id:
            raise HTTPException(status_code=401, detail="invalid session token")
        return session

    @app.get("/live")
    async def live() -> dict[str, Any]:
        return {"status": "alive", "sessions": hub.session_count}

    @app.get("/health")
    async def health():
        signaling = bool(enable_signaling) and _gateway.AIORTC_AVAILABLE
        runtime_ready = app.state.runtime_manager is not None or app.state.ingress is not None
        manager = app.state.runtime_manager
        recovery_state = getattr(manager, "recovery_state", "completed") if manager is not None else "completed"
        now = time.monotonic()
        readiness_task = app.state.readiness_task
        if readiness_task is not None and readiness_task.done():
            try:
                app.state.readiness_cache = readiness_task.result()
            except Exception as exc:
                app.state.readiness_cache = {
                    "ready": False,
                    "checks": {},
                    "failed": ["readiness_probe"],
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            app.state.readiness_cache_at = now
            app.state.readiness_task = None
        if enable_signaling and app.state.readiness_task is None and (
            app.state.readiness_cache is None or (now - app.state.readiness_cache_at) >= 300.0
        ):
            app.state.readiness_task = asyncio.create_task(asyncio.to_thread(readiness_probe))
        chain = dict(app.state.readiness_cache or {
            "ready": False,
            "checks": {},
            "failed": ["readiness_probe_running" if enable_signaling else "signaling_disabled"],
        })
        base_pairing_ready = bool(signaling and runtime_ready and recovery_state == "completed")
        # A minimal/dev SessionHub may still expose pairing while optional AI is
        # unavailable.  Production PhoneOnly is stricter: its startup deep probe
        # loads Whisper/YOLOX and must finish BEFORE the offer starts the live
        # runtime.  Gate B 20260718-112417 proved that pairing while this probe was
        # still loading GPU models starved the audio callback (queue 3000, drops).
        # GPU phase orchestration therefore implies the strict gate unless an
        # operator explicitly opts out; legacy/minimal tests keep the old default.
        require_ai_for_pairing = os.environ.get(
            "MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING",
            os.environ.get("MLOMEGA_GPU_PHASE_ORCHESTRATION", "0"),
        ).strip().lower() in {"1", "true", "yes", "on"}
        ai_ready = bool(base_pairing_ready and chain.get("ready"))
        pairing_ready = bool(base_pairing_ready and (ai_ready or not require_ai_for_pairing))
        payload = {
            "status": "full_ready" if ai_ready else ("pairing_ready" if pairing_ready else "unavailable"),
            # Backward-compatible field: ``ready`` means safe to pair/offer, not
            # that every optional/AI dependency is healthy.
            "ready": pairing_ready,
            "pairing_ready": pairing_ready,
            "ai_ready": ai_ready,
            "sessions": hub.session_count,
            "signaling": signaling,
            "runtime": runtime_ready,
            "startup_recovery": recovery_state,
            "chain": chain,
        }
        if not pairing_ready:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.get("/ready")
    async def full_ready():
        result = await health()
        if hasattr(result, "body"):
            return result
        if not result.get("ai_ready"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content=result)
        return result

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        manager = app.state.runtime_manager
        if manager is not None:
            return manager.metrics()
        active = app.state.ingress
        return {"mode": "signaling_only", "active": active.stats() if hasattr(active, "stats") else None}

    def _authenticate_query(session_id: str | None, token: str | None) -> "Session":
        """Token check for GET provisioning routes (token via query params)."""
        if not session_id or not token:
            raise HTTPException(status_code=422, detail="session_id and token are required")
        return _authenticate(session_id, token)

    @app.get("/models/device/manifest")
    async def device_manifest(request: Request) -> dict[str, Any]:
        """E47-C: the device-local model manifest (offline ASR/KWS + gesture).

        Session token required (query params). Returns one entry per device model
        with its sha256 + a download endpoint so the phone provisions itself at
        first launch and verifies each artefact before use (guide E47 §2)."""
        q = request.query_params
        _authenticate_query(q.get("session_id"), q.get("token"))
        return build_device_manifest_payload()

    @app.get("/models/device/{name}")
    async def device_model(name: str, request: Request):
        """E47-C: stream one device-local model artefact (sha256 in the manifest).

        Session token required (query params). 404 if the model name is unknown or
        the artefact has not been fetched on the PC yet (run
        ``fetch_models_v19.py --device``)."""
        from fastapi.responses import FileResponse

        q = request.query_params
        _authenticate_query(q.get("session_id"), q.get("token"))
        device = load_device_manifest()
        spec = device.get(name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown device model: {name}")
        artefact = _device_artifact_path(spec)
        if artefact is None:
            raise HTTPException(
                status_code=404,
                detail=f"device model {name} not provisioned on PC (run fetch_models_v19.py --device)",
            )
        return FileResponse(
            path=str(artefact),
            filename=artefact.name,
            media_type="application/octet-stream",
            headers={"X-Model-Sha256": _sha256_file(artefact)},
        )

    @app.get("/replay/media/{kind}/{asset_id}")
    async def replay_media(kind: str, asset_id: str, request: Request):
        """Stream a bounded replay image/clip; refs never cross the DataChannel."""
        from fastapi.responses import FileResponse

        q = request.query_params
        _authenticate_query(q.get("session_id"), q.get("token"))
        if kind not in {"frame", "clip"}:
            raise HTTPException(status_code=404, detail="unknown replay media kind")
        manager = app.state.runtime_manager
        runtime = manager.get(q.get("session_id")) if manager is not None else None
        replay = getattr(getattr(runtime, "pipeline", None), "replay", None)
        if replay is None or not hasattr(replay, "resolve_media_path"):
            raise HTTPException(status_code=404, detail="replay service unavailable")
        path = replay.resolve_media_path(kind, asset_id)
        if path is None:
            raise HTTPException(status_code=404, detail="replay media not found")
        return FileResponse(path=str(path), filename=path.name,
                            headers={"Cache-Control": "private, max-age=60"})

    @app.post("/session/create")
    async def create_session(request: Request) -> dict[str, Any]:
        body = await request.json()
        device_id = body.get("device_id")
        if not device_id or not isinstance(device_id, str):
            raise HTTPException(status_code=422, detail="device_id (str) is required")
        session = hub.create_session(device_id)
        return {
            "session_id": session.session_id,
            "token": session.token,
            "created_at_utc": session.created_at_utc,
            "expires_at_utc": session.token_expires_at_utc,
            "expires_in_seconds": hub.token_ttl_seconds,
        }

    @app.post("/session/renew")
    async def renew_token(request: Request) -> dict[str, Any]:
        body = await request.json()
        session_id = body.get("session_id")
        token = body.get("token")
        if not session_id or not token:
            raise HTTPException(status_code=422, detail="session_id and token are required")
        session = hub.renew_token(session_id, token)
        if session is None:
            raise HTTPException(status_code=401, detail="invalid session token")
        new_token = session.token
        return {
            "token": new_token,
            # renew keeps the session id; refresh the timestamp so the client can
            # track token age. Matches SessionHubClient.RenewToken expectations.
            "created_at_utc": _now_iso(),
            "expires_at_utc": session.token_expires_at_utc,
            "expires_in_seconds": hub.token_ttl_seconds,
        }

    @app.post("/session/clock-sync")
    async def clock_sync(request: Request) -> dict[str, Any]:
        body = await request.json()
        session_id = body.get("session_id")
        token = body.get("token")
        client_send_ns = body.get("client_send_ns")
        if not session_id or not token or client_send_ns is None:
            raise HTTPException(
                status_code=422,
                detail="session_id, token and client_send_ns are required",
            )
        _authenticate(session_id, token)

        # One monotonic instant stamps both recv and send: the server is a single
        # point on its own clock for this exchange, exactly as SessionHub collapses
        # server_send_ns := server_recv_ns when unspecified. The C# client defaults
        # server_send := server_recv when the two are equal, so returning the same
        # value keeps the client math (ClockSync.ComputeSample) identical.
        server_stamp = hub.begin_clock_sync()

        # Record the sample server-side so current_offset_ns is available for
        # degraded-mode/health. client_recv_ns is unknown to the server, so we use
        # the same server_stamp as a lower-bound placeholder (the authoritative
        # offset is the client's; this is a coarse server-side mirror only).
        try:
            hub.complete_clock_sync(
                session_id,
                client_send_ns=int(client_send_ns),
                server_recv_ns=server_stamp,
                server_send_ns=server_stamp,
                client_recv_ns=int(client_send_ns),
            )
        except (KeyError, TypeError, ValueError):
            # A bad client_send_ns must not 500 the health of the exchange; the
            # stamps are still valid and the client owns the real computation.
            pass

        return {"server_recv_ns": server_stamp, "server_send_ns": server_stamp}

    if enable_signaling and _gateway.AIORTC_AVAILABLE:

        @app.post("/webrtc/offer")
        async def webrtc_offer(request: Request) -> dict[str, Any]:
            body = await request.json()
            session_id = body.get("session_id")
            token = body.get("token")
            sdp = body.get("sdp")
            sdp_type = body.get("type")
            if not sdp or not sdp_type:
                raise HTTPException(status_code=422, detail="sdp and type are required")
            if not session_id or not token:
                raise HTTPException(
                    status_code=422, detail="session_id and token are required"
                )
            _authenticate(session_id, token)

            manager = app.state.runtime_manager
            if manager is not None:
                try:
                    runtime = await manager.get_or_create(session_id)
                except RuntimeError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                active = runtime.ingress
                app.state.ingress = active
            else:
                active = app.state.ingress
                if active is None:
                    active = _gateway.AiortcIngress(session_id=session_id)
                    await active.start()
                    app.state.ingress = active
            answer_sdp, answer_type = await active.handle_offer_sdp(sdp, sdp_type)
            return {"sdp": answer_sdp, "type": answer_type}

        @app.post("/session/end")
        async def end_session(request: Request) -> dict[str, Any]:
            body = await request.json()
            session_id = body.get("session_id")
            token = body.get("token")
            if not session_id or not token:
                raise HTTPException(status_code=422, detail="session_id and token are required")
            _authenticate(session_id, token)
            manager = app.state.runtime_manager
            runtime = manager.get(session_id) if manager is not None else None
            if runtime is None:
                raise HTTPException(status_code=404, detail="session runtime not found")
            # Explicit authenticated action only. Peer disconnect/track end never
            # reaches this path and therefore never ends BrainLive or CloseDay.
            status = await runtime.end_session_only()
            if status.get("end_session") != "completed":
                raise HTTPException(status_code=500, detail=status)
            manager.start_close_day(session_id)
            return runtime.status()

        @app.post("/session/close-day")
        async def close_day(request: Request) -> dict[str, Any]:
            body = await request.json()
            session_id = body.get("session_id")
            token = body.get("token")
            if not session_id or not token:
                raise HTTPException(status_code=422, detail="session_id and token are required")
            _authenticate(session_id, token)
            manager = app.state.runtime_manager
            runtime = manager.get(session_id) if manager is not None else None
            if runtime is None:
                raise HTTPException(status_code=404, detail="session runtime not found")
            if not runtime.ended:
                raise HTTPException(status_code=409, detail="session/end must complete first")
            manager.start_close_day(session_id)
            return runtime.status()

        @app.post("/session/status")
        async def session_status(request: Request) -> dict[str, Any]:
            body = await request.json()
            session_id = body.get("session_id")
            token = body.get("token")
            if not session_id or not token:
                raise HTTPException(status_code=422, detail="session_id and token are required")
            _authenticate(session_id, token)
            manager = app.state.runtime_manager
            runtime = manager.get(session_id) if manager is not None else None
            if runtime is None:
                raise HTTPException(status_code=404, detail="session runtime not found")
            return runtime.status()

    return app


def _reissue_token(hub: "SessionHub", session: "Session") -> str:
    """Rotate the ephemeral token for ``session`` in place.

    Uses only public ``secrets``/existing hub state; the old token is revoked so
    a renewed client must present the new token. We do not rewrite SessionHub —
    we operate on its exposed mappings the same way ``create_session`` does.
    """
    return hub.rotate_token(session)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MLOmega V19 SessionHub HTTP server")
    # E36 §1: bind on ALL interfaces by default so a VPN-tunnel (Tailscale 100.x)
    # peer can reach the SessionHub the same way a LAN peer does; the ephemeral
    # session token is the access barrier (already in place). Override with
    # ``--host`` or the profile's ``bind_host`` for a stricter bind.
    parser.add_argument(
        "--host", default=None,
        help="interface to bind (default: profile bind_host, else 0.0.0.0 — all interfaces)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--person-id", default="me")
    parser.add_argument(
        "--no-signaling",
        action="store_true",
        help="disable the /webrtc/offer media signaling route",
    )
    args = parser.parse_args(argv)

    import uvicorn

    host = args.host or _bind_host_from_profile() or "0.0.0.0"
    app = create_app(enable_signaling=not args.no_signaling, person_id=args.person_id)
    uvicorn.run(app, host=host, port=args.port)


def _bind_host_from_profile() -> str | None:
    """Read ``bind_host`` from configs/user_profile.yaml (E36 §1). Absent → None."""
    try:
        import yaml

        p = _ROOT / "configs" / "user_profile.yaml"
        if not p.exists():
            return None
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        host = data.get("bind_host")
        return str(host) if host else None
    except Exception:
        return None


if __name__ == "__main__":
    main()
