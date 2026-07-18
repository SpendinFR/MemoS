from __future__ import annotations

"""Process isolation for the heavyweight post-stop Deep Audio phase.

WhisperX, Pyannote and SpeechBrain retain native CUDA allocations after their
Python objects have been deleted.  On an 8 GB RTX 3070 that prevents the next
llama.cpp P1 phase from being fully GPU-resident.  Running the unchanged Deep
Audio implementation in a child process gives the OS an authoritative resource
boundary: process exit releases every native allocation.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def run_deep_audio_isolated(
    *,
    person_id: str,
    package_date: str,
    live_session_id: str | None,
    language: str,
    max_bundle_audio_seconds: float | None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Run the real V18.5 Deep Audio function in a disposable Python process."""
    timeout = float(timeout_s or os.environ.get("MLOMEGA_DEEP_AUDIO_PROCESS_TIMEOUT_S", "3600"))
    with tempfile.TemporaryDirectory(prefix="mlomega-deep-audio-") as tmp:
        result_path = Path(tmp) / "result.json"
        command = [
            sys.executable,
            "-m",
            "mlomega_audio_elite.deep_audio_subprocess",
            "--worker",
            "--person-id", str(person_id),
            "--package-date", str(package_date),
            "--language", str(language),
            "--result-file", str(result_path),
        ]
        if live_session_id:
            command += ["--live-session-id", str(live_session_id)]
        if max_bundle_audio_seconds is not None:
            command += ["--max-bundle-audio-seconds", str(float(max_bundle_audio_seconds))]

        env = os.environ.copy()
        src = str(ROOT / "src")
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0 or not result_path.exists():
            detail = (completed.stderr or completed.stdout or "deep-audio worker produced no result")[-3000:]
            raise RuntimeError(
                f"isolated Deep Audio failed (exit={completed.returncode}): {detail.strip()}"
            )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("isolated Deep Audio result is not a JSON object")
        return payload


def _worker(args: argparse.Namespace) -> int:
    from .runtime_environment_v19 import configure_windows_cuda_dlls

    ok, detail = configure_windows_cuda_dlls(ROOT)
    if not ok:
        raise RuntimeError(f"Deep Audio CUDA/cuDNN environment invalid: {detail}")

    from .brainlive_offline_deep_audio_v18_5 import run_offline_deep_audio_for_bundles

    result = run_offline_deep_audio_for_bundles(
        person_id=args.person_id,
        package_date=args.package_date,
        live_session_id=args.live_session_id,
        language=args.language,
        max_bundle_audio_seconds=args.max_bundle_audio_seconds,
    )
    path = Path(args.result_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--package-date", required=True)
    parser.add_argument("--live-session-id")
    parser.add_argument("--language", default="fr")
    parser.add_argument("--max-bundle-audio-seconds", type=float)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args(argv)
    if not args.worker:
        parser.error("this module is an internal --worker entry point")
    return _worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
