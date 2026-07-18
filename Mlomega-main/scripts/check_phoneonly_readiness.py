from __future__ import annotations

"""Strict preflight for RUN_MLOMEGA_V19 -LivePhone.

Unlike /health (pairing readiness), this command exits non-zero unless the whole
local AI chain required by FirstTry is available. It constructs the real YOLOX
CUDA session and loads the configured Whisper model when --deep is requested.
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "services" / "live-pc"
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mlomega_audio_elite.runtime_environment_v19 import (
    probe_proxy_environment,
    sanitize_blackhole_proxy_env,
)

# The exact environment used by RUN must be checked.  Correct only the known
# isolated-runner black hole before any Hugging Face/Whisper imports occur.
REMOVED_BLACKHOLE_PROXIES = sanitize_blackhole_proxy_env()
READINESS_RECEIPT = ROOT / "storage" / "runtime" / "phoneonly_readiness.json"


def _receipt_fingerprint(*, person_id: str) -> dict[str, Any]:
    return {
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


def _write_readiness_receipt(report: dict[str, Any], *, person_id: str) -> None:
    """Publish an atomic receipt consumed by SessionHub's non-GPU health probe."""
    path = Path(os.environ.get("MLOMEGA_PREFLIGHT_RECEIPT", str(READINESS_RECEIPT)))
    if not report.get("ready"):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ready": True,
        "created_at_epoch": time.time(),
        "mode": report.get("mode"),
        "fingerprint": _receipt_fingerprint(person_id=person_id),
        "checks": {
            name: bool(check.get("ok"))
            for name, check in (report.get("checks") or {}).items()
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _warm_live_llm(orchestrator: Any) -> dict[str, Any]:
    """Load and prove the real live 4B after P1 has released the GPU.

    Merely listing an Ollama tag is not readiness: on the RTX 3070 a cold schema
    call measured over 60 s, so the first help request could fail although the
    preflight was green. This probe pays that cold start before pairing and leaves
    exactly the configured live model resident for capture.
    """
    from mlomega_audio_elite.config import get_settings
    from mlomega_audio_elite.llm import OllamaJsonClient

    settings = get_settings()
    model = str(settings.ollama_live_model or "").strip()
    if not model:
        raise RuntimeError("MLOMEGA_OLLAMA_LIVE_MODEL is empty")
    timeout_s = max(10.0, float(os.environ.get("MLOMEGA_LIVE_LLM_WARM_TIMEOUT_S", "120")))
    started = time.perf_counter()
    result = OllamaJsonClient(
        base_url=settings.ollama_base_url,
        model=model,
        backend="ollama",
    ).require_json(
        "Return strict JSON with one boolean field ok.",
        "Confirm live readiness.",
        {"ok": True},
        timeout=timeout_s,
        max_output_tokens=32,
    )
    resident = orchestrator._resident_model_names()
    foreign = [name for name in resident if not str(name).lower() == model.lower()]
    if result.get("ok") is not True or foreign or model.lower() not in {
        str(name).lower() for name in resident
    }:
        raise RuntimeError(
            f"live 4B warmup mismatch model={model!r} resident={resident!r} result={result!r}"
        )
    return {
        "model": model,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "resident_after": resident,
    }


def run(*, person_id: str, deep: bool) -> dict[str, Any]:
    http = _load("phoneonly_readiness_http", LIVE / "sessionhub_http.py")
    report = dict(http._probe_ai_chain(person_id=person_id))
    checks = dict(report.get("checks") or {})
    night_report = (checks.get("close_day_env") or {}).get("detail")
    if isinstance(night_report, dict) and isinstance(night_report.get("checks"), dict):
        for name, check in night_report["checks"].items():
            checks[f"night::{name}"] = check
    proxy_ok, proxy_detail = probe_proxy_environment()
    proxy_detail["removed_at_import"] = REMOVED_BLACKHOLE_PROXIES
    checks["proxy_environment"] = {
        "ok": proxy_ok,
        "detail": proxy_detail,
    }

    # E64-i chantier 2: when GPU phase orchestration is enabled, the preflight
    # proves the P1 text model is available SEQUENTIALLY (start -> /props ->
    # anti-thinking probe -> stop) instead of demanding it coexist with the live
    # Ollama/vision stack. It must finish with P1 STOPPED.
    if os.environ.get("MLOMEGA_GPU_PHASE_ORCHESTRATION", "0").strip().lower() in {"1", "true", "yes", "on"}:
        orchestrator = None
        try:
            from mlomega_audio_elite.gpu_phase_orchestrator import GpuPhaseOrchestrator

            orchestrator = GpuPhaseOrchestrator()
            preflight = orchestrator.enter_preflight()
            checks["p1_sequential"] = {
                "ok": not orchestrator.p1_running and orchestrator.probe_calls >= 1,
                "detail": {
                    "alias": (
                        (preflight.get("p1") or {}).get("props", {}).get("model_alias")
                        or (preflight.get("p1") or {}).get("props", {}).get("alias")
                    ),
                    "stopped_after_preflight": not orchestrator.p1_running,
                    "anti_thinking_probed": orchestrator.probe_calls,
                },
            }
        except Exception as exc:
            checks["p1_sequential"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        finally:
            # E64-i Gate B #5: the preflight loads P1 (and may leave a VLM/9B
            # resident from an earlier close). Before the live session can start,
            # the GPU MUST be handed to the 4B live model exclusively — run the
            # real frontier here in ``finally`` even when the preflight failed, so
            # the readiness command never returns with a VLM squatting VRAM.
            if orchestrator is not None:
                try:
                    prep = orchestrator.prepare_live_gpu()
                    checks["prepare_live_gpu"] = {
                        "ok": not prep.get("resident_after")
                        or all(
                            str(m).split(":")[0].strip().lower()
                            == str(prep.get("live_model") or "").split(":")[0].strip().lower()
                            for m in prep.get("resident_after") or []
                        ),
                        "detail": {
                            "live_model": prep.get("live_model"),
                            "unloaded": prep.get("unloaded"),
                            "resident_after": prep.get("resident_after"),
                            "vram_after": prep.get("vram_after"),
                        },
                    }
                    warm = _warm_live_llm(orchestrator)
                    checks["live_llm_warm"] = {"ok": True, "detail": warm}
                except Exception as exc:
                    checks["prepare_live_gpu"] = {
                        "ok": False,
                        "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                    }
                    checks["live_llm_warm"] = {
                        "ok": False,
                        "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                    }

    detector_path = ROOT / "models" / "yolox_nano.onnx"
    if detector_path.exists():
        try:
            vision = _load("phoneonly_readiness_vision", LIVE / "visionrt.py")
            detector = vision.YoloxDetector(detector_path)
            checks["yolox_session"] = {
                "ok": bool(detector.on_gpu),
                "detail": {"providers": detector.providers, "on_gpu": detector.on_gpu},
            }
        except Exception as exc:
            checks["yolox_session"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
    else:
        checks["yolox_session"] = {"ok": False, "detail": str(detector_path)}

    if deep:
        try:
            audio = _load("phoneonly_readiness_audio", LIVE / "audiort.py")
            transcriber = audio.WhisperTranscriber(model_size="small")
            model = transcriber._ensure()
            checks["whisper_model"] = {
                "ok": model is not None and transcriber.available,
                "detail": {"model": "small", "device": transcriber.device},
            }
            transcriber._model = None
        except Exception as exc:
            checks["whisper_model"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

        try:
            tts = _load("phoneonly_readiness_tts", LIVE / "tts_local.py")
            provider = tts.build_tts_provider()
            wav = provider.speak("Test audio", lang="fr")
            checks["tts"] = {
                "ok": bool(wav and wav[:4] == b"RIFF"),
                "detail": getattr(provider, "name", type(provider).__name__),
            }
        except Exception as exc:
            checks["tts"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            }

    required = list(checks)
    ready = all(bool(checks[name].get("ok")) for name in required)
    report.update(
        ready=ready,
        checks=checks,
        failed=[name for name in required if not checks[name].get("ok")],
        mode="deep" if deep else "quick",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict PhoneOnly production readiness")
    parser.add_argument("--person-id", default="me")
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args(argv)
    report = run(person_id=args.person_id, deep=bool(args.deep))
    _write_readiness_receipt(report, person_id=args.person_id)
    print(json.dumps(report, ensure_ascii=False))
    if report["ready"]:
        print("[OK] PhoneOnly full-chain readiness passed.", file=sys.stderr)
        return 0
    print(
        "[FAIL] PhoneOnly not production-ready: " + ", ".join(report.get("failed") or []),
        file=sys.stderr,
    )
    for name in report.get("failed") or []:
        detail = (report.get("checks") or {}).get(name, {}).get("detail")
        fix = detail.get("fix") if isinstance(detail, dict) else None
        if fix:
            print(f"[FIX] {name}: {fix}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
