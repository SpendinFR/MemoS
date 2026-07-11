from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_unity_modules_required_by_replay_player_are_enabled() -> None:
    manifest = json.loads((ROOT / "apps/xr-mobile/Packages/manifest.json").read_text(encoding="utf-8-sig"))
    deps = manifest["dependencies"]
    assert deps["com.unity.modules.video"] == "1.0.0"
    assert deps["com.unity.modules.unitywebrequesttexture"] == "1.0.0"
    asmdef = json.loads(
        (ROOT / "apps/xr-mobile/Assets/Scripts/UI/MLOmega.XR.UI.asmdef").read_text(encoding="utf-8-sig")
    )
    assert "UnityEngine.VideoModule" in asmdef["references"]
    assert "UnityEngine.UnityWebRequestTextureModule" in asmdef["references"]


def test_welcome_routes_missing_apks_to_release_or_assisted_build() -> None:
    source = (ROOT / "scripts/WELCOME_MLOMEGA.ps1").read_text(encoding="utf-8-sig")
    assert "GET_PHONEONLY_APK.ps1" in source
    assert "BUILD_XREAL_ASSISTED.ps1" in source
    assert "mlomega-xreal.apk" in source
    assert "Get-FileHash" in source


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell distribution scripts are Windows-only")
@pytest.mark.parametrize(
    ("script", "needle", "args"),
    [
        ("GET_PHONEONLY_APK.ps1", "SHA-256", ["-Destination", "missing-phone.apk"]),
        ("BUILD_XREAL_ASSISTED.ps1", "PrepareDefines -> BuildApk", ["-PcHost", "192.0.2.10"]),
    ],
)
def test_distribution_helpers_dry_run_without_network_or_unity(script: str, needle: str, args: list[str]) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell unavailable")
    proc = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / script), *args, "-DryRun"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, output
    assert needle in output
