from __future__ import annotations

import importlib.util
import json
import os
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "configure_augmented_reality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ar_operator_config", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sandbox_paths(module, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(
        module, "DEVICE_REGISTRY_PATH", tmp_path / "augmented_devices.local.json"
    )
    monkeypatch.setattr(
        module, "STUDIO_CONFIG_PATH", tmp_path / "augmented_studio.local.json"
    )


def test_device_add_writes_local_registry_and_secret_only_to_dotenv(
    tmp_path: Path, monkeypatch
):
    module = _load_module()
    _sandbox_paths(module, tmp_path, monkeypatch)
    token = "home-assistant-test-token-123456"
    monkeypatch.setenv("MLOMEGA_AR_SETUP_TOKEN", token)

    result = module.configure_device(
        Namespace(
            label="Lampe salon",
            entity_id="light.salon",
            base_url="http://homeassistant.local:8123",
            token_env="",
        )
    )

    assert result == 0
    registry = json.loads(module.DEVICE_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry["lampe salon"] == registry["light.salon"]
    assert registry["lampe salon"]["ha_entity_id"] == "light.salon"
    assert token not in module.DEVICE_REGISTRY_PATH.read_text(encoding="utf-8")
    dotenv = module.DOTENV_PATH.read_text(encoding="utf-8")
    assert "MLOMEGA_AR_DEVICE_REGISTRY=" in dotenv
    assert token in dotenv


def test_studio_one_code_gates_whole_release_without_plaintext_storage(
    tmp_path: Path, monkeypatch
):
    module = _load_module()
    _sandbox_paths(module, tmp_path, monkeypatch)
    monkeypatch.setenv("MLOMEGA_AR_SETUP_CODE", "260726")

    assert (
        module.configure_studio(Namespace(release_id="film-juillet-2026"))
        == 0
    )
    stored = module.STUDIO_CONFIG_PATH.read_text(encoding="utf-8")
    assert "260726" not in stored
    monkeypatch.setenv(
        "MLOMEGA_AR_STUDIO_CONFIG", str(module.STUDIO_CONFIG_PATH)
    )
    monkeypatch.setenv("MLOMEGA_AR_STUDIO_CODE", "260726")
    assert module.check_studio(Namespace(release_id="film-juillet-2026")) == 0
    monkeypatch.setenv("MLOMEGA_AR_STUDIO_CODE", "000000")
    assert module.check_studio(Namespace(release_id="film-juillet-2026")) == 3


def test_kiwix_config_requires_real_local_files(tmp_path: Path, monkeypatch):
    module = _load_module()
    _sandbox_paths(module, tmp_path, monkeypatch)
    executable = tmp_path / "kiwix-serve.exe"
    zim = tmp_path / "wikipedia_fr_all_mini.zim"
    executable.write_bytes(b"MZ")
    zim.write_bytes(b"ZIM")

    assert (
        module.configure_kiwix(
            Namespace(executable=str(executable), zim=str(zim))
        )
        == 0
    )
    dotenv = module.DOTENV_PATH.read_text(encoding="utf-8")
    assert str(executable.resolve()) in dotenv
    assert str(zim.resolve()) in dotenv
    assert 'MLOMEGA_KIWIX_URL="http://127.0.0.1:8792"' in dotenv


def test_product_launcher_keeps_optional_providers_gated_and_stops_kiwix():
    launcher = (ROOT / "scripts" / "RUN_MLOMEGA_V19.ps1").read_text(
        encoding="utf-8"
    )
    assert "studio-check --release-id $StudioReleaseId" in launcher
    assert "$env:MLOMEGA_AR_STUDIO_RELEASE_ID = $StudioReleaseId" in launcher
    assert "Start-Process -FilePath $kiwixExe" in launcher
    assert launcher.count("Stop-Process -Id $kiwixProcess.Id") >= 3
    assert "if ($AugmentedReality)" in launcher
    assert "if ($Pro)" in launcher


def test_kiwix_provider_resolves_first_article_instead_of_showing_search_boilerplate():
    capabilities_path = (
        ROOT / "services" / "augmented-reality" / "capabilities.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ar_capabilities_operator", capabilities_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class Response:
        def __init__(self, body: str):
            self.body = body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return self.body

    requested = []

    def opener(url, timeout):
        requested.append((url, timeout))
        if "/search?" in url:
            return Response(
                '<a href="/content/wiki/Intelligence_artificielle">result</a>'
            )
        return Response(
            "<p></p><p>L'intelligence artificielle est un ensemble de techniques "
            "qui permettent a des machines de realiser des taches complexes, "
            "avec des limites et des usages tres varies selon le domaine.</p>"
        )

    result = module.KiwixKnowledgeProvider(
        "http://127.0.0.1:8792", opener=opener
    ).lookup("intelligence artificielle")

    assert result["summary"].startswith("L'intelligence artificielle")
    assert result["source"].endswith("/content/wiki/Intelligence_artificielle")
    assert len(requested) == 2
