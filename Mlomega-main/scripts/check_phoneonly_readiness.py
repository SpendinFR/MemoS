from __future__ import annotations

"""Strict preflight for RUN_MLOMEGA_V19 -LivePhone.

Unlike /health (pairing readiness), this command exits non-zero unless the whole
local AI chain required by FirstTry is available. It constructs the real YOLOX
CUDA session and loads the configured Whisper model when --deep is requested.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "services" / "live-pc"
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(*, person_id: str, deep: bool) -> dict[str, Any]:
    http = _load("phoneonly_readiness_http", LIVE / "sessionhub_http.py")
    report = dict(http._probe_ai_chain(person_id=person_id))
    checks = dict(report.get("checks") or {})

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
    print(json.dumps(report, ensure_ascii=False))
    if report["ready"]:
        print("[OK] PhoneOnly full-chain readiness passed.", file=sys.stderr)
        return 0
    print(
        "[FAIL] PhoneOnly not production-ready: " + ", ".join(report.get("failed") or []),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
