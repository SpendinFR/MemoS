from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def test_deep_audio_isolation_returns_worker_result_and_inherits_db_env(monkeypatch):
    from mlomega_audio_elite import deep_audio_subprocess as boundary

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        seen["env"] = dict(kwargs["env"])
        result_path = Path(command[command.index("--result-file") + 1])
        result_path.write_text(json.dumps({"status": "ok", "artifacts": ["a"]}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(boundary.subprocess, "run", fake_run)
    monkeypatch.setenv("MLOMEGA_DB", "memory-test.db")
    result = boundary.run_deep_audio_isolated(
        person_id="me",
        package_date="2026-07-18",
        live_session_id="blsess_test",
        language="fr",
        max_bundle_audio_seconds=600.0,
    )

    assert result == {"status": "ok", "artifacts": ["a"]}
    assert seen["command"][:3] == [sys.executable, "-m", "mlomega_audio_elite.deep_audio_subprocess"]
    assert "blsess_test" in seen["command"]
    assert seen["env"]["MLOMEGA_DB"] == "memory-test.db"
    assert str(ROOT / "src") in seen["env"]["PYTHONPATH"]


def test_deep_audio_isolation_fails_loudly_without_worker_result(monkeypatch):
    from mlomega_audio_elite import deep_audio_subprocess as boundary

    monkeypatch.setattr(
        boundary.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 7, stdout="", stderr="CUDA worker failed",
        ),
    )
    with pytest.raises(RuntimeError, match="exit=7.*CUDA worker failed"):
        boundary.run_deep_audio_isolated(
            person_id="me",
            package_date="2026-07-18",
            live_session_id=None,
            language="fr",
            max_bundle_audio_seconds=None,
        )
