from __future__ import annotations

"""Explicit one-time model download used only after a guided preflight failure."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mlomega_audio_elite.runtime_environment_v19 import (  # noqa: E402
    PYANNOTE_REPOSITORIES,
    probe_huggingface_pyannote,
    probe_proxy_environment,
)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass


def main() -> int:
    proxy_ok, proxy = probe_proxy_environment()
    if not proxy_ok:
        print(f"[FAIL] Proxy: {proxy}", file=sys.stderr)
        return 2
    token = os.environ.get("MLOMEGA_HF_TOKEN") or os.environ.get("HF_TOKEN")
    access_ok, access = probe_huggingface_pyannote(
        token=token,
        verify_remote=True,
        repositories=(),
    )
    if not access_ok:
        print(f"[FAIL] Compte/token HF: {access}", file=sys.stderr)
        return 2

    from huggingface_hub import snapshot_download
    from mlomega_audio_elite.config import get_settings

    for repo in PYANNOTE_REPOSITORIES:
        print(f"[..] Prechargement {repo}", file=sys.stderr)
        snapshot_download(repo_id=repo, token=token)
    asr_repo = f"Systran/faster-whisper-{get_settings().whisperx_model}"
    print(f"[..] Prechargement {asr_repo}", file=sys.stderr)
    snapshot_download(repo_id=asr_repo, token=token)

    ok, report = probe_huggingface_pyannote(token=token, verify_remote=True)
    if not ok:
        print(f"[FAIL] Cache incomplet apres telechargement: {report}", file=sys.stderr)
        return 2
    print("[OK] Compte gated et cache Pyannote/ASR prets pour FirstTry.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
