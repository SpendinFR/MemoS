"""Hermetic process environment shared by FirstTry, SessionHub and CloseDay.

The launcher, the live process and every recovery/manual CloseDay entrypoint must
see the same proxy and Windows DLL search path.  Checks in this module are
deliberately bounded and never download a model: FirstTry either proves that the
night can run from the local cache, or refuses capture with a useful fix.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse


PROXY_ENV_NAMES = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)
PYANNOTE_REPOSITORIES = (
    "pyannote/speaker-diarization-3.1",
    "pyannote/segmentation-3.0",
    "pyannote/wespeaker-voxceleb-resnet34-LM",
)
PYANNOTE_REQUIRED_FILES = {
    "pyannote/speaker-diarization-3.1": ("config.yaml",),
    "pyannote/segmentation-3.0": ("config.yaml", "pytorch_model.bin"),
    "pyannote/wespeaker-voxceleb-resnet34-LM": ("config.yaml", "pytorch_model.bin"),
}

# os.add_dll_directory handles must stay alive for the lifetime of the process.
_DLL_DIRECTORY_HANDLES: list[Any] = []
_LOADED_DLLS: list[Any] = []


def _parsed_proxy(value: str) -> tuple[str, int] | None:
    parsed = urlparse(value if "://" in value else f"http://{value}")
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return None
    try:
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    except (TypeError, ValueError):
        return None
    return host, port


def sanitize_blackhole_proxy_env() -> list[str]:
    """Remove only the known isolated-runner black hole (loopback port 9)."""

    removed: list[str] = []
    for name in PROXY_ENV_NAMES:
        value = str(os.environ.get(name) or "").strip()
        endpoint = _parsed_proxy(value) if value else None
        if endpoint and endpoint[0] in {"127.0.0.1", "localhost", "::1"} and endpoint[1] == 9:
            os.environ.pop(name, None)
            removed.append(name)
    return removed


def probe_proxy_environment(*, timeout_s: float = 1.0) -> tuple[bool, dict[str, Any]]:
    """Reject malformed or unreachable explicit proxies before any HF call."""

    removed = sanitize_blackhole_proxy_env()
    configured: dict[str, str] = {}
    endpoints: set[tuple[str, int]] = set()
    malformed: list[str] = []
    for name in PROXY_ENV_NAMES:
        value = str(os.environ.get(name) or "").strip()
        if not value:
            continue
        configured[name] = value
        endpoint = _parsed_proxy(value)
        if endpoint is None:
            malformed.append(name)
        else:
            endpoints.add(endpoint)

    unreachable: list[str] = []
    for host, port in sorted(endpoints):
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                pass
        except OSError:
            unreachable.append(f"{host}:{port}")
    ok = not malformed and not unreachable
    return ok, {
        "removed_known_blackhole": removed,
        "configured_names": sorted(configured),
        "malformed_names": malformed,
        "unreachable": unreachable,
        "policy": "loopback:9 removed; every other explicit proxy must accept TCP",
        "fix": (
            "Corrige/supprime HTTP_PROXY, HTTPS_PROXY et ALL_PROXY avant RUN; "
            "un proxy configure mais mort bloque volontairement FirstTry."
        ) if not ok else None,
    }


def _venv_site_packages(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Lib" / "site-packages"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return venv / "lib" / version / "site-packages"


def cuda_dll_directories(project_root: Path) -> list[Path]:
    """Return stable CUDA/cuDNN directories shared by live and core venvs."""

    root = Path(project_root).resolve()
    candidates: list[Path] = []
    # Core first: CloseDay must use its pinned cuDNN 8 for WhisperX/Pyannote.
    for venv_name in (".venv", ".venv-live"):
        site = _venv_site_packages(root / venv_name)
        for relative in (
            Path("nvidia/cudnn/bin"), Path("nvidia/cublas/bin"),
            Path("nvidia/cuda_runtime/bin"), Path("nvidia/cuda_nvrtc/bin"),
            Path("torch/lib"),
        ):
            path = (site / relative).resolve()
            if path.is_dir() and path not in candidates:
                candidates.append(path)
    return candidates


def configure_windows_cuda_dlls(
    project_root: Path,
    *,
    require_cudnn8: bool = True,
    load_cudnn: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """Prepare inherited PATH and prove the exact cuDNN 8 DLL can be loaded."""

    if os.name != "nt":
        return True, {"platform": os.name, "status": "not_applicable"}
    directories = cuda_dll_directories(project_root)
    current_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    normalized = {os.path.normcase(os.path.abspath(part)) for part in current_parts}
    prepend: list[str] = []
    for directory in directories:
        value = str(directory)
        if os.path.normcase(os.path.abspath(value)) not in normalized:
            prepend.append(value)
            normalized.add(os.path.normcase(os.path.abspath(value)))
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(value))
            except OSError:
                pass
    if prepend:
        os.environ["PATH"] = os.pathsep.join([*prepend, *current_parts])

    cudnn = next(
        (directory / "cudnn_ops_infer64_8.dll" for directory in directories
         if (directory / "cudnn_ops_infer64_8.dll").is_file()),
        None,
    )
    detail: dict[str, Any] = {
        "directories": [str(path) for path in directories],
        "path_prepend": prepend,
        "cudnn_ops_infer64_8": str(cudnn) if cudnn else None,
        "loaded": False,
    }
    if require_cudnn8 and cudnn is None:
        detail["fix"] = (
            "Reinstalle nvidia-cudnn-cu12 dans .venv (version cuDNN 8 compatible WhisperX), "
            "puis relance le preflight."
        )
        return False, detail
    if cudnn is not None and load_cudnn:
        try:
            handle = ctypes.WinDLL(str(cudnn))
            _LOADED_DLLS.append(handle)
            detail["loaded"] = True
        except OSError as exc:
            detail["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            detail["fix"] = (
                "Le fichier cuDNN existe mais ses dependances ne se chargent pas. "
                "Repare nvidia-cublas-cu12/nvidia-cudnn-cu12 dans .venv et verifie le pilote NVIDIA."
            )
            return False, detail
    return (not require_cudnn8 or bool(detail["loaded"])), detail


def _hf_json(url: str, *, token: str, timeout_s: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "mlomega-firsttry-preflight/19"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _hf_head(url: str, *, token: str, timeout_s: float) -> None:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "mlomega-firsttry-preflight/19"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        if int(getattr(response, "status", 200)) >= 400:
            raise OSError(f"HTTP {response.status}")


def probe_huggingface_pyannote(
    *,
    token: str | None,
    repositories: Iterable[str] = PYANNOTE_REPOSITORIES,
    timeout_s: float = 10.0,
    verify_remote: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """Prove HF identity, gated access and a complete local Pyannote cache."""

    value = str(token or "").strip()
    detail: dict[str, Any] = {
        "token_present": bool(value and not value.startswith("__") and len(value) >= 8),
        "account": None,
        "remote_access": {},
        "cached": {},
        "downloads_performed": False,
    }
    if not detail["token_present"]:
        detail["fix"] = (
            "Renseigne MLOMEGA_HF_TOKEN dans .env puis accepte les modeles "
            "pyannote/speaker-diarization-3.1 et pyannote/segmentation-3.0 sur Hugging Face."
        )
        return False, detail

    remote_ok = True
    if verify_remote:
        try:
            identity = _hf_json("https://huggingface.co/api/whoami-v2", token=value, timeout_s=timeout_s)
            detail["account"] = identity.get("name") or identity.get("fullname") or "authenticated"
        except Exception as exc:
            remote_ok = False
            detail["identity_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"

    repos = tuple(str(repo).strip() for repo in repositories if str(repo).strip())
    if verify_remote and remote_ok:
        for repo in repos:
            try:
                gated_file = PYANNOTE_REQUIRED_FILES.get(repo, ("config.yaml",))[0]
                _hf_head(
                    f"https://huggingface.co/{quote(repo, safe='/')}/resolve/main/{quote(gated_file)}",
                    token=value,
                    timeout_s=timeout_s,
                )
                detail["remote_access"][repo] = True
            except Exception as exc:
                remote_ok = False
                detail["remote_access"][repo] = f"{type(exc).__name__}: {str(exc)[:180]}"

    cache_ok = True
    try:
        from huggingface_hub import snapshot_download

        for repo in repos:
            try:
                path = snapshot_download(repo_id=repo, token=value, local_files_only=True)
                missing = [
                    filename for filename in PYANNOTE_REQUIRED_FILES.get(repo, ())
                    if not (Path(path) / filename).is_file()
                ]
                if missing:
                    raise FileNotFoundError("incomplete snapshot, missing: " + ", ".join(missing))
                detail["cached"][repo] = str(path)
            except Exception as exc:
                cache_ok = False
                detail["cached"][repo] = f"{type(exc).__name__}: {str(exc)[:180]}"
    except Exception as exc:
        cache_ok = False
        detail["cache_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"

    ok = remote_ok and cache_ok
    if not ok:
        detail["fix"] = (
            "Connecte-toi au bon compte HF, accepte les deux licences Pyannote, puis execute "
            ".venv\\Scripts\\python.exe scripts\\PREFETCH_FIRSTTRY_MODELS.py; le preflight RUN ne telecharge rien."
        )
    return ok, detail
