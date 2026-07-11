from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_installer_keeps_rollback_until_doctor_and_blocks_failures() -> None:
    source = _text("scripts/INSTALL_MLOMEGA_V19_WINDOWS.ps1")
    swap = source.index('Rename-Item -Path $VenvLiveNew -NewName ".venv-live"')
    doctor = source.index('"DOCTOR_MLOMEGA_V19.ps1"', swap)
    delete_after_doctor = source.index("Remove-Item -Recurse -Force $VenvLiveOld", doctor)
    assert swap < doctor < delete_after_doctor
    assert 'Fail "Doctor V19 final en echec' in source
    assert ".venv-live.previous conserve" in source


def test_welcome_resolves_python311_and_rolls_back_on_doctor_fail() -> None:
    source = _text("scripts/WELCOME_MLOMEGA.ps1")
    assert "function Resolve-Python311" in source
    assert "py -3.11" in source
    assert "& $python311 -m venv $coreVenv" in source
    assert "& python -m venv $coreVenv" not in source
    assert "Restore-LiveVenv" in source
    assert 'FailWelcome "DOCTOR a signale un FAIL critique' in source


def test_doctor_uses_configured_roots_and_core_preflight() -> None:
    source = _text("scripts/DOCTOR_MLOMEGA_V19.ps1")
    assert "Import-DotEnv" in source
    assert "check_close_day_preflight.py" in source
    assert "& $CorePython $preflight" in source
    assert "Invoke-PythonCode $MemoryPython $dbCode" in source
    assert "$env:MLOMEGA_MEDIA" in source
    assert "data\\memory.db" not in source
    assert "data\\evidence" not in source


def test_phone_builder_removes_xreal_define_and_xreal_removes_phone_define() -> None:
    phone = _text("apps/xr-mobile/Assets/Scripts/Editor/AndroidBuild.cs")
    xreal = _text("apps/xr-mobile/Assets/Scripts/Editor/AndroidBuildXreal.cs")
    assert '.Replace("XREAL_SDK_PRESENT;", "")' in phone
    assert '.Replace("XREAL_SDK_PRESENT", "")' in phone
    assert '.Replace("MLOMEGA_PHONE_ONLY;", "")' in xreal
    assert '.Replace("MLOMEGA_PHONE_ONLY", "")' in xreal


def test_close_day_preflight_does_not_create_missing_paths(monkeypatch, tmp_path: Path) -> None:
    path = ROOT / "scripts" / "check_close_day_preflight.py"
    spec = importlib.util.spec_from_file_location("e61_close_day_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing_db = tmp_path / "not-created" / "memory.db"
    missing_media = tmp_path / "not-created-media"
    monkeypatch.setenv("MLOMEGA_DB", str(missing_db))
    monkeypatch.setenv("MLOMEGA_MEDIA", str(missing_media))
    report = module.run()

    assert not report["ready"]
    assert not report["checks"]["db"]["ok"]
    assert not report["checks"]["media_root"]["ok"]
    assert not missing_db.parent.exists()
    assert not missing_media.exists()
