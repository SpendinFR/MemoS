from __future__ import annotations

"""Bounded, non-mutating preflight for the real nocturnal CloseDay environment."""

import argparse
import base64
import importlib.metadata
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

from mlomega_audio_elite.runtime_environment_v19 import (
    configure_windows_cuda_dlls,
    probe_huggingface_pyannote,
    probe_proxy_environment,
    sanitize_blackhole_proxy_env,
)

REMOVED_BLACKHOLE_PROXIES = sanitize_blackhole_proxy_env()

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    # Reported later through the real core imports; do not hide the other checks.
    pass


CUDA_ENV_OK, CUDA_ENV_DETAIL = configure_windows_cuda_dlls(ROOT)


def _request_json(url: str, *, payload: dict[str, Any] | None = None, timeout_s: float = 10.0) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for part in value.split("."):
        digits = "".join(char for char in part if char.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers)


def _probe_transformers() -> tuple[bool, dict[str, Any]]:
    try:
        version = importlib.metadata.version("transformers")
        parsed = _version_tuple(version)
        ok = (4, 52) <= parsed < (5,)
        return ok, {
            "version": version,
            "required": ">=4.52,<5",
            "fix": None if ok else "Dans .venv: pip install 'transformers>=4.52,<5'.",
        }
    except Exception as exc:
        return False, {
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "fix": "Installe transformers>=4.52,<5 dans .venv.",
        }


def _ollama_tags(base_url: str, *, timeout_s: float = 4.0) -> tuple[set[str], dict[str, Any]]:
    root = base_url.rstrip("/")
    try:
        payload = _request_json(f"{root}/api/tags", timeout_s=timeout_s)
        installed = {
            str(item.get("name") or item.get("model") or "")
            for item in (payload.get("models") or []) if isinstance(item, dict)
        } - {""}
        return installed, {"base_url": root, "installed": sorted(installed)}
    except Exception as exc:
        return set(), {
            "base_url": root,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


def _probe_json_contract(cfg: Any, *, timeout_s: float = 120.0) -> tuple[bool, dict[str, Any]]:
    """Execute one tiny request through the selected post-stop backend."""

    backend = os.environ.get("MLOMEGA_LLM_BACKEND", "ollama").strip().lower()
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["mlomega-ready"]}},
        "required": ["status"],
        "additionalProperties": False,
    }
    detail: dict[str, Any] = {"backend": backend, "schema": "strict-enum-v1"}
    try:
        if backend == "llamacpp":
            root = os.environ.get("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
            model = os.environ.get("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p3-mlomega")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Return the requested JSON only."},
                    {"role": "user", "content": "Set status to mlomega-ready."},
                ],
                "stream": False,
                "temperature": 0.0,
                "max_tokens": 32,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "firsttry_ready", "strict": True, "schema": schema},
                },
            }
            outer = _request_json(f"{root}/v1/chat/completions", payload=payload, timeout_s=timeout_s)
            content = (((outer.get("choices") or [{}])[0].get("message") or {}).get("content"))
            detail.update(base_url=root, model=model)
        elif backend == "ollama":
            root = str(cfg.ollama_base_url).rstrip("/")
            model = str(cfg.ollama_model)
            payload = {
                "model": model,
                "prompt": "Return JSON with status exactly mlomega-ready.",
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_ctx": int(cfg.ollama_context_poststop), "num_predict": 32},
                "keep_alive": "0",
            }
            outer = _request_json(f"{root}/api/generate", payload=payload, timeout_s=timeout_s)
            content = outer.get("response")
            detail.update(base_url=root, model=model, done_reason=outer.get("done_reason"))
        else:
            raise ValueError(f"unsupported MLOMEGA_LLM_BACKEND={backend!r}")
        parsed = json.loads(str(content or ""))
        ok = parsed == {"status": "mlomega-ready"}
        detail["parsed"] = parsed
        if not ok:
            detail["error"] = "selected model did not honor the strict JSON contract"
        return ok, detail
    except Exception as exc:
        detail["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        detail["fix"] = (
            "Demarre le backend configure, verifie le modele exact et son support JSON schema; "
            "si llama.cpp est utilise, renseigne MLOMEGA_LLM_BACKEND=llamacpp et le bon alias."
        )
        return False, detail


# A valid one-pixel PNG. The call proves image plumbing + JSON, not visual quality.
_PREFLIGHT_PNG = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63606060f80f0001040100f51c2f950000000049454e44ae426082"
    )
).decode("ascii")


def _probe_vlm_contract(cfg: Any, *, timeout_s: float = 180.0) -> tuple[bool, dict[str, Any]]:
    """Prove every configured VLM exists and accepts image + strict JSON."""

    root = str(cfg.ollama_base_url).rstrip("/")
    models = list(dict.fromkeys(filter(None, (
        os.environ.get("MLOMEGA_VLM_MODEL") or "moondream",
        os.environ.get("MLOMEGA_OFFLINE_VLM_MODEL")
        or os.environ.get("MLOMEGA_VLM_HEAVY_MODEL")
        or "qwen3-vl:8b",
    ))))
    installed, tags_detail = _ollama_tags(root)
    if tags_detail.get("error"):
        return False, {
            "models": models,
            "missing": [],
            "tags": tags_detail,
            "probes": {},
            "fix": "Demarre Ollama puis relance le preflight; aucun modele n'est declare manquant sans inventaire reel.",
        }
    def present(name: str) -> bool:
        return name in installed or (":" not in name and f"{name}:latest" in installed)

    missing = [model for model in models if not present(model)]
    detail: dict[str, Any] = {"models": models, "missing": missing, "tags": tags_detail, "probes": {}}
    if missing:
        detail["fix"] = "Avant FirstTry: ollama pull " + " ; ollama pull ".join(missing)
        return False, detail
    ok = True
    for model in models:
        try:
            payload = {
                "model": model,
                "prompt": "Confirm that an image was supplied. Return JSON only.",
                "images": [_PREFLIGHT_PNG],
                "stream": False,
                # Match the real deep-vision product request exactly: it uses
                # Ollama's JSON mode, then validates the object itself.
                "format": "json",
                "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 32},
                "keep_alive": "0",
            }
            outer = _request_json(f"{root}/api/generate", payload=payload, timeout_s=timeout_s)
            parsed = json.loads(str(outer.get("response") or ""))
            model_ok = parsed.get("image_received") is True
            detail["probes"][model] = {"ok": model_ok, "parsed": parsed, "done_reason": outer.get("done_reason")}
            ok = ok and model_ok
        except Exception as exc:
            ok = False
            detail["probes"][model] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
    if not ok:
        detail["fix"] = "Repare Ollama/VLM avant capture; le modele doit accepter une image et un schema JSON strict."
    return ok, detail


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


def _probe_llm_process_consistency(*, timeout_s: float = 2.0) -> tuple[bool, dict[str, Any]]:
    """Catch an orphan llama-server or a configured alias that is not running."""

    backend = os.environ.get("MLOMEGA_LLM_BACKEND", "ollama").strip().lower()
    root = os.environ.get("MLOMEGA_LLAMACPP_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    detail: dict[str, Any] = {"selected_backend": backend, "llamacpp_base_url": root}
    try:
        props = _request_json(f"{root}/props", timeout_s=timeout_s)
        detail["llamacpp_running"] = True
        detail["running_alias"] = props.get("model_alias")
        detail["running_context"] = ((props.get("default_generation_settings") or {}).get("n_ctx"))
    except Exception as exc:
        props = None
        detail["llamacpp_running"] = False
        detail["llamacpp_probe"] = type(exc).__name__

    if backend == "ollama" and props is not None:
        detail["fix"] = (
            "Un llama-server non selectionne tourne encore sur 8080 et peut prendre la VRAM. "
            "Arrete-le, ou configure explicitement MLOMEGA_LLM_BACKEND=llamacpp, son alias et son contexte."
        )
        return False, detail
    if backend == "llamacpp":
        expected_alias = os.environ.get("MLOMEGA_LLAMACPP_MODEL", "qwen9b-p3-mlomega")
        detail["expected_alias"] = expected_alias
        ok = props is not None and str(props.get("model_alias") or "") == expected_alias
        if not ok:
            detail["fix"] = (
                "Demarre llama-server avec l'alias MLOMEGA_LLAMACPP_MODEL exact; "
                "aucun serveur absent ou ancien profil P1/P3 n'est accepte."
            )
        return ok, detail
    if backend != "ollama":
        detail["fix"] = "MLOMEGA_LLM_BACKEND doit valoir ollama ou llamacpp."
        return False, detail
    return True, detail


def run() -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, ok: bool, detail: Any) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    proxy_ok, proxy_detail = probe_proxy_environment()
    proxy_detail["removed_at_import"] = REMOVED_BLACKHOLE_PROXIES
    record("proxy_environment", proxy_ok, proxy_detail)

    record("cuda_dll_environment", CUDA_ENV_OK, CUDA_ENV_DETAIL)

    record(
        "python311_64",
        sys.version_info[:2] == (3, 11) and struct.calcsize("P") * 8 == 64,
        {"version": sys.version.split()[0], "bits": struct.calcsize("P") * 8, "executable": sys.executable},
    )
    expected_python = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    actual_python = Path(sys.executable).resolve()
    exact_venv = actual_python == expected_python
    record(
        "night_venv",
        exact_venv,
        {
            "expected": str(expected_python),
            "actual": str(actual_python),
            "fix": None if exact_venv else "Execute le preflight et CloseDay avec .venv\\Scripts\\python.exe.",
        },
    )
    transformers_ok, transformers_detail = _probe_transformers()
    record("transformers_version", transformers_ok, transformers_detail)
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
        record("llm_json_contract", False, "settings unavailable")
        record("vlm_json_contract", False, "settings unavailable")
    else:
        process_ok, process_detail = _probe_llm_process_consistency()
        record("llm_process_consistency", process_ok, process_detail)
        context_ok, context_detail = _probe_llm_context(cfg.ollama_context_poststop)
        record("llm_context_budget", context_ok, context_detail)
        llm_ok, llm_detail = _probe_json_contract(cfg)
        record("llm_json_contract", llm_ok, llm_detail)
        vlm_ok, vlm_detail = _probe_vlm_contract(cfg)
        record("vlm_json_contract", vlm_ok, vlm_detail)

    token = os.environ.get("MLOMEGA_HF_TOKEN") or os.environ.get("HF_TOKEN")
    hf_ok, hf_detail = probe_huggingface_pyannote(token=token)
    record("hf_pyannote_access_cache", hf_ok, hf_detail)

    if cfg is not None:
        try:
            from huggingface_hub import snapshot_download

            asr_repo = f"Systran/faster-whisper-{cfg.whisperx_model}"
            asr_path = snapshot_download(repo_id=asr_repo, local_files_only=True)
            required_asr = ("config.json", "model.bin", "tokenizer.json")
            missing_asr = [name for name in required_asr if not (Path(asr_path) / name).is_file()]
            if missing_asr:
                raise FileNotFoundError("incomplete ASR snapshot, missing: " + ", ".join(missing_asr))
            record("night_asr_cache", True, {"repo": asr_repo, "path": str(asr_path), "downloads_performed": False})
        except Exception as exc:
            record(
                "night_asr_cache",
                False,
                {
                    "model": getattr(cfg, "whisperx_model", None),
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    "fix": "Precharge le modele Faster-Whisper nocturne avant FirstTry.",
                },
            )

    try:
        import torch

        torch_ok = bool(torch.cuda.is_available())
        if torch_ok:
            probe = torch.ones((8,), device="cuda")
            total = float(probe.sum().item())
            del probe
            torch.cuda.empty_cache()
        else:
            total = 0.0
        record(
            "torch_cuda_execution",
            torch_ok and total == 8.0,
            {
                "available": torch_ok,
                "device": torch.cuda.get_device_name(0) if torch_ok else None,
                "torch_cuda": getattr(torch.version, "cuda", None),
                "cudnn": torch.backends.cudnn.version() if torch_ok else None,
                "kernel_result": total,
                "fix": None if torch_ok else "Repare le pilote NVIDIA et le torch CUDA de .venv.",
            },
        )
    except Exception as exc:
        record(
            "torch_cuda_execution", False,
            {"error": f"{type(exc).__name__}: {str(exc)[:240]}", "fix": "Reinstalle le torch CUDA epingle dans .venv."},
        )

    entrypoint = ROOT / "scripts" / "run_phoneonly_close_day.py"
    record("entrypoint", entrypoint.is_file(), str(entrypoint))
    record("ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg"))

    try:
        qdrant = _request_json("http://127.0.0.1:6333/collections", timeout_s=3.0)
        record("qdrant", qdrant.get("status") == "ok", qdrant)
    except Exception as exc:
        record(
            "qdrant", False,
            {"error": f"{type(exc).__name__}: {str(exc)[:180]}", "fix": "Lance scripts\\START_QDRANT.ps1 avant FirstTry."},
        )

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

    try:
        minimum_gb = max(1.0, float(os.environ.get("MLOMEGA_PREFLIGHT_MIN_DISK_GB", "20")))
        target = Path(media_raw).expanduser() if media_raw else ROOT
        free_gb = shutil.disk_usage(target if target.exists() else target.parent).free / (1024 ** 3)
        disk_ok = free_gb >= minimum_gb
        record(
            "capture_disk",
            disk_ok,
            {
                "path": str(target), "free_gb": round(free_gb, 2), "minimum_gb": minimum_gb,
                "fix": None if disk_ok else "Libere de l'espace ou ajuste explicitement MLOMEGA_PREFLIGHT_MIN_DISK_GB.",
            },
        )
    except Exception as exc:
        record("capture_disk", False, {"error": f"{type(exc).__name__}: {str(exc)[:180]}"})

    failed = [name for name, check in checks.items() if not check["ok"]]
    return {"ready": not failed, "checks": checks, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MLOmega CloseDay environment preflight")
    parser.add_argument("--json", action="store_true", help="kept for an explicit machine-readable invocation")
    parser.parse_args(argv)
    report = run()
    print(json.dumps(report, ensure_ascii=False))
    if not report["ready"]:
        for name in report["failed"]:
            detail = report["checks"].get(name, {}).get("detail")
            fix = detail.get("fix") if isinstance(detail, dict) else None
            if fix:
                print(f"[FIX] {name}: {fix}", file=sys.stderr)
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
