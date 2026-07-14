from __future__ import annotations

"""Bounded, non-mutating preflight for the real nocturnal CloseDay environment."""

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import struct
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    # Reported later through the real core imports; do not hide the other checks.
    pass


def _present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _probe_llm_context(
    configured_context: int,
    *,
    backend: str | None = None,
    base_url: str | None = None,
    timeout_s: float = 3.0,
) -> tuple[bool, dict[str, Any]]:
    """Prove that the post-stop budget matches the running llama.cpp slot.

    The orchestration budget is a total prompt+response window.  Letting it
    silently differ from the server context caused useful 13k prompts to be
    split into five calls even though the running server accepted 24k.  Ollama
    owns its per-request ``num_ctx`` and therefore does not need this external
    server check.
    """
    selected = (backend or os.environ.get("MLOMEGA_LLM_BACKEND", "ollama")).strip().lower()
    detail: dict[str, Any] = {
        "backend": selected,
        "configured_poststop_context": int(configured_context),
    }
    if selected != "llamacpp":
        detail["status"] = "not_applicable_per_request_context"
        return True, detail

    root = (
        base_url
        or os.environ.get("MLOMEGA_LLAMACPP_BASE_URL")
        or "http://127.0.0.1:8080"
    ).rstrip("/")
    detail["base_url"] = root
    try:
        with urllib.request.urlopen(f"{root}/props", timeout=timeout_s) as response:
            props = json.loads(response.read().decode("utf-8"))
        settings = props.get("default_generation_settings") or {}
        server_context = int(settings.get("n_ctx") or 0)
        detail.update(
            {
                "server_context": server_context,
                "model_alias": props.get("model_alias"),
                "source": "/props.default_generation_settings.n_ctx",
            }
        )
        if server_context <= 0:
            detail["error"] = "running llama.cpp did not expose a positive n_ctx"
            return False, detail
        matches = server_context == int(configured_context)
        if not matches:
            detail["error"] = "orchestrator/server context mismatch"
        return matches, detail
    except Exception as exc:
        detail["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return False, detail


def run() -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool, detail: Any) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    record(
        "python311_64",
        sys.version_info[:2] == (3, 11) and struct.calcsize("P") * 8 == 64,
        {"version": sys.version.split()[0], "bits": struct.calcsize("P") * 8, "executable": sys.executable},
    )
    required = ("torch", "whisperx", "pyannote.audio", "speechbrain")
    missing = [name for name in required if not _present(name)]
    record("deep_audio_imports", not missing, {"required": required, "missing": missing})

    cfg = None
    try:
        from mlomega_audio_elite.config import get_settings
        from mlomega_audio_elite.v18_close_day import close_brainlive_day  # noqa: F401
        import mlomega_audio_elite.brainlive_offline_deep_audio_v18_5  # noqa: F401
        import mlomega_audio_elite.brainlive_offline_deep_vision_v16_1  # noqa: F401

        cfg = get_settings()
        record(
            "close_day_imports",
            True,
            {"whisperx": cfg.enable_whisperx, "pyannote": cfg.enable_pyannote,
             "device": cfg.whisperx_device, "model": cfg.whisperx_model},
        )
    except Exception as exc:
        record("close_day_imports", False, f"{type(exc).__name__}: {str(exc)[:300]}")

    if cfg is None:
        record("llm_context_budget", False, "settings unavailable; context equality unproved")
    else:
        context_ok, context_detail = _probe_llm_context(cfg.ollama_context_poststop)
        record("llm_context_budget", context_ok, context_detail)

    token = os.environ.get("MLOMEGA_HF_TOKEN") or os.environ.get("HF_TOKEN")
    token_ok = bool(token and not token.startswith("__") and len(token.strip()) >= 8)
    record("hf_token", token_ok, "present" if token_ok else "MLOMEGA_HF_TOKEN/HF_TOKEN absent or placeholder")

    entrypoint = ROOT / "scripts" / "run_phoneonly_close_day.py"
    record("entrypoint", entrypoint.is_file(), str(entrypoint))
    record("ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg"))

    db_raw = os.environ.get("MLOMEGA_DB")
    if not db_raw:
        record("db", False, "MLOMEGA_DB missing")
    else:
        db = Path(db_raw).expanduser()
        try:
            if not db.is_file():
                raise FileNotFoundError(f"configured database does not exist: {db}")
            con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
            quick = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            record("db", quick == "ok", {"path": str(db.resolve()), "quick_check": quick})
        except Exception as exc:
            record("db", False, f"{type(exc).__name__}: {str(exc)[:300]}")

    media_raw = os.environ.get("MLOMEGA_MEDIA")
    if not media_raw:
        record("media_root", False, "MLOMEGA_MEDIA missing")
    else:
        media = Path(media_raw).expanduser()
        try:
            record(
                "media_root",
                media.is_dir() and os.access(media, os.R_OK | os.W_OK),
                {"path": str(media.resolve()), "exists": media.is_dir(), "writable": os.access(media, os.W_OK)},
            )
        except OSError as exc:
            record("media_root", False, f"{type(exc).__name__}: {str(exc)[:300]}")

    failed = [name for name, check in checks.items() if not check["ok"]]
    return {"ready": not failed, "checks": checks, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MLOmega CloseDay environment preflight")
    parser.add_argument("--json", action="store_true", help="kept for an explicit machine-readable invocation")
    parser.parse_args(argv)
    report = run()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
