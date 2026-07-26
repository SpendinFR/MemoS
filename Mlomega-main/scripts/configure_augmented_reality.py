from __future__ import annotations

"""Small operator-only configurator for optional Augmented Reality providers.

The generated files are local and gitignored.  This script does not modify the
Unity project, the memory database, or either Local/PRO CloseDay path.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"
DEVICE_REGISTRY_PATH = PROJECT_ROOT / "configs" / "augmented_devices.local.json"
STUDIO_CONFIG_PATH = PROJECT_ROOT / "configs" / "augmented_studio.local.json"
STUDIO_ITERATIONS = 240_000


def _safe_env_value(value: str) -> str:
    value = str(value).strip()
    if not value or any(char in value for char in "\r\n\""):
        raise ValueError("environment value is empty or contains an unsafe character")
    return value


def set_dotenv_value(
    name: str, value: str, *, path: Path | None = None
) -> None:
    path = path or DOTENV_PATH
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", name):
        raise ValueError(f"invalid environment name: {name}")
    value = _safe_env_value(value)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f'{name}="{value}"'
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    updated: list[str] = []
    replaced = False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return raw


def _write_local_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _dotenv_snapshot(path: Path = DOTENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"").strip("'")
    return values


def _home_assistant_url_allowed(raw: str) -> bool:
    parsed = urllib.parse.urlparse(raw.rstrip("/"))
    if parsed.scheme == "https" and bool(parsed.hostname):
        return True
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def configure_device(args: argparse.Namespace) -> int:
    label = str(args.label or "").strip()
    entity = str(args.entity_id or "").strip()
    base_url = str(args.base_url or "").strip().rstrip("/")
    if len(label) < 2:
        raise ValueError("device label is required")
    if not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", entity):
        raise ValueError("Home Assistant entity must look like light.salon")
    if not _home_assistant_url_allowed(base_url):
        raise ValueError("Home Assistant URL must be HTTPS or a local/private HTTP URL")
    token_env = args.token_env or (
        "MLOMEGA_HOME_ASSISTANT_TOKEN_"
        + re.sub(r"[^A-Z0-9]+", "_", entity.upper()).strip("_")
    )
    token = os.environ.get("MLOMEGA_AR_SETUP_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("Token longue duree Home Assistant: ").strip()
    if len(token) < 16:
        raise ValueError("Home Assistant token is missing or unexpectedly short")

    registry = _load_json_object(DEVICE_REGISTRY_PATH)
    entry = {
        "adapter": "home_assistant",
        "base_url": base_url,
        "ha_entity_id": entity,
        "token_env": token_env,
    }
    # Both keys point to the same adapter contract: VisionRT may know the durable
    # entity id, while ML Kit commonly supplies only the spoken/display label.
    registry[label.casefold()] = entry
    registry[entity] = entry
    _write_local_json(DEVICE_REGISTRY_PATH, registry)
    set_dotenv_value("MLOMEGA_AR_DEVICE_REGISTRY", str(DEVICE_REGISTRY_PATH))
    set_dotenv_value(token_env, token)
    print(f"[OK] Appareil '{label}' -> {entity} ajoute.")
    print("[OK] L'action Marche/arret exigera toujours une confirmation dans l'UI.")
    return 0


def configure_kiwix(args: argparse.Namespace) -> int:
    executable = Path(args.executable).expanduser().resolve()
    zim = Path(args.zim).expanduser().resolve()
    if not executable.is_file():
        raise ValueError(f"kiwix-serve executable not found: {executable}")
    if executable.name.casefold() not in {"kiwix-serve", "kiwix-serve.exe"}:
        raise ValueError("the executable must be kiwix-serve or kiwix-serve.exe")
    if not zim.is_file() or zim.suffix.casefold() != ".zim":
        raise ValueError(f"ZIM corpus not found: {zim}")
    set_dotenv_value("MLOMEGA_KIWIX_EXE", str(executable))
    set_dotenv_value("MLOMEGA_KIWIX_ZIM", str(zim))
    set_dotenv_value("MLOMEGA_KIWIX_URL", "http://127.0.0.1:8792")
    print(f"[OK] Kiwix configure avec {zim.name}.")
    print("[OK] RUN demarrera et arretera kiwix-serve automatiquement.")
    return 0


def _studio_code_from_operator(*, confirm: bool) -> str:
    preset = os.environ.get("MLOMEGA_AR_SETUP_CODE", "").strip()
    if preset:
        return preset
    code = getpass.getpass("Code studio (6 a 12 chiffres): ").strip()
    if confirm:
        repeated = getpass.getpass("Confirme le code studio: ").strip()
        if not hmac.compare_digest(code, repeated):
            raise ValueError("studio codes do not match")
    return code


def _validate_studio_code_shape(code: str) -> None:
    if not re.fullmatch(r"\d{6,12}", code):
        raise ValueError("studio code must contain 6 to 12 digits")


def configure_studio(args: argparse.Namespace) -> int:
    release_id = str(args.release_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{3,79}", release_id):
        raise ValueError("release id must contain 4-80 safe characters")
    code = _studio_code_from_operator(confirm=True)
    _validate_studio_code_shape(code)
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), salt, STUDIO_ITERATIONS
    )
    _write_local_json(
        STUDIO_CONFIG_PATH,
        {
            "version": 1,
            "release_id": release_id,
            "iterations": STUDIO_ITERATIONS,
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "digest_b64": base64.b64encode(digest).decode("ascii"),
        },
    )
    set_dotenv_value("MLOMEGA_AR_STUDIO_CONFIG", str(STUDIO_CONFIG_PATH))
    print(f"[OK] Release studio '{release_id}' configuree.")
    print("[OK] Un seul code ouvre les profils Web pour toute cette session de tournage.")
    return 0


def check_studio(args: argparse.Namespace) -> int:
    path = Path(
        os.environ.get("MLOMEGA_AR_STUDIO_CONFIG", str(STUDIO_CONFIG_PATH))
    ).expanduser()
    config = _load_json_object(path)
    release_id = str(args.release_id or "").strip()
    if config.get("version") != 1 or config.get("release_id") != release_id:
        print("[FAIL] Release studio inconnue.", file=sys.stderr)
        return 3
    code = os.environ.get("MLOMEGA_AR_STUDIO_CODE", "").strip()
    if not code:
        code = getpass.getpass("Code studio: ").strip()
    try:
        _validate_studio_code_shape(code)
        iterations = int(config["iterations"])
        salt = base64.b64decode(str(config["salt_b64"]), validate=True)
        expected = base64.b64decode(str(config["digest_b64"]), validate=True)
    except (KeyError, TypeError, ValueError):
        print("[FAIL] Configuration studio invalide.", file=sys.stderr)
        return 3
    actual = hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), salt, iterations
    )
    if not hmac.compare_digest(actual, expected):
        print("[FAIL] Code studio refuse.", file=sys.stderr)
        return 3
    print(f"[OK] Release studio '{release_id}' autorisee pour cette session.")
    return 0


def show_status(_args: argparse.Namespace) -> int:
    devices = _load_json_object(DEVICE_REGISTRY_PATH)
    studio = _load_json_object(STUDIO_CONFIG_PATH)
    dotenv = _dotenv_snapshot()
    unique_entities = {
        value.get("ha_entity_id")
        for value in devices.values()
        if isinstance(value, dict) and value.get("ha_entity_id")
    }
    print(
        "Kiwix exe : "
        + (
            os.environ.get("MLOMEGA_KIWIX_EXE")
            or dotenv.get("MLOMEGA_KIWIX_EXE")
            or "non configure"
        )
    )
    print(
        "Kiwix ZIM : "
        + (
            os.environ.get("MLOMEGA_KIWIX_ZIM")
            or dotenv.get("MLOMEGA_KIWIX_ZIM")
            or "non configure"
        )
    )
    print(f"Domotique : {len(unique_entities)} appareil(s) configure(s)")
    print(f"Studio    : {studio.get('release_id') or 'non configure'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    device = commands.add_parser("device-add")
    device.add_argument("--label", required=True)
    device.add_argument("--entity-id", required=True)
    device.add_argument("--base-url", required=True)
    device.add_argument("--token-env", default="")
    device.set_defaults(handler=configure_device)

    kiwix = commands.add_parser("kiwix-config")
    kiwix.add_argument("--executable", required=True)
    kiwix.add_argument("--zim", required=True)
    kiwix.set_defaults(handler=configure_kiwix)

    studio = commands.add_parser("studio-init")
    studio.add_argument("--release-id", required=True)
    studio.set_defaults(handler=configure_studio)

    studio_check = commands.add_parser("studio-check")
    studio_check.add_argument("--release-id", required=True)
    studio_check.set_defaults(handler=check_studio)

    status = commands.add_parser("status")
    status.set_defaults(handler=show_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
