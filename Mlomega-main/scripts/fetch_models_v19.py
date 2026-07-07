from __future__ import annotations

"""Fetch + verify V19 model weights declared in configs/MODEL_MANIFEST.yaml.

Downloads every manifest entry that carries a ``url`` + ``sha256`` into its
``path`` (default under ``models/``, git-ignored), verifying the checksum. Idempotent:
a file already present with the right sha256 is skipped.

Usage:
    python scripts/fetch_models_v19.py            # fetch ONNX weights (detector + face)
    python scripts/fetch_models_v19.py --argos    # + install Argos en<->fr packs
    python scripts/fetch_models_v19.py --device   # + fetch Android device-local models (E47-C)
    python scripts/fetch_models_v19.py --check     # verify only, no download

Fetched ONNX assets: YOLOX-Nano detector (E27), YuNet face detector + SFace face
embedder (E32 identity). All are sha256-pinned in the manifest.

faster-whisper (`asr`) and the VLM/LLM (`ollama`) are not fetched here: the
first is pulled into the HuggingFace cache by faster-whisper on first use, the
second via `ollama pull`. This keeps the script to reproducible, sha-verified
static assets (handoff §4.1 / ADR §E27).
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs" / "MODEL_MANIFEST.yaml"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    import yaml

    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    return data.get("models", {}) if isinstance(data, dict) else {}


def _load_device() -> dict:
    """Android device-local model entries (top-level ``device:`` key, E47-C)."""
    import yaml

    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    return data.get("device", {}) if isinstance(data, dict) else {}


def _fetchable(models: dict) -> list[tuple[str, dict]]:
    out = []
    for name, spec in models.items():
        if isinstance(spec, dict) and spec.get("url") and spec.get("sha256"):
            out.append((name, spec))
    return out


def fetch_all(*, check_only: bool = False) -> int:
    models = _load_manifest()
    errors = 0
    for name, spec in _fetchable(models):
        path = ROOT / spec.get("path", f"models/{name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        expected = spec["sha256"]
        if path.exists():
            actual = _sha256(path)
            if actual == expected:
                print(f"[ok]   {name}: {path.name} present, sha256 verified")
                continue
            print(f"[warn] {name}: {path.name} sha256 mismatch (have {actual[:12]}…)")
            if check_only:
                errors += 1
                continue
        elif check_only:
            print(f"[miss] {name}: {path} absent ({spec['license']})")
            errors += 1
            continue

        url = spec["url"]
        print(f"[get]  {name}: {url} -> {path} ({spec['license']})")
        try:
            urllib.request.urlretrieve(url, path)  # noqa: S310 - manifest-pinned URL
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"[fail] {name}: download error: {exc}")
            errors += 1
            continue
        actual = _sha256(path)
        if actual != expected:
            print(f"[fail] {name}: sha256 mismatch after download (got {actual})")
            errors += 1
        else:
            print(f"[ok]   {name}: downloaded + sha256 verified ({spec['license']})")
    return errors


def install_argos(pairs: list[tuple[str, str]] | None = None) -> int:
    """Install Argos Translate language packages (offline NMT, MIT/CTranslate2)."""
    try:
        from argostranslate import package
    except Exception as exc:  # pragma: no cover
        print(f"[fail] argostranslate not installed: {exc}")
        return 1
    pairs = pairs or [("en", "fr"), ("fr", "en"), ("zh", "fr")]
    print("[argos] updating package index…")
    package.update_package_index()
    available = package.get_available_packages()
    errors = 0
    for src, tgt in pairs:
        match = next((p for p in available if p.from_code == src and p.to_code == tgt), None)
        if match is None:
            print(f"[argos] no package {src}->{tgt} in index (skipped)")
            continue
        installed = {(p.from_code, p.to_code) for p in package.get_installed_packages()}
        if (src, tgt) in installed:
            print(f"[argos] {src}->{tgt} already installed")
            continue
        try:
            print(f"[argos] installing {src}->{tgt} …")
            package.install_from_path(match.download())
        except Exception as exc:  # pragma: no cover
            print(f"[argos] {src}->{tgt} install failed: {exc}")
            errors += 1
    return errors


def _fetchable_archives(models: dict) -> list[tuple[str, dict]]:
    """Entries distributed as an archive (E35 TTS voices): archive + extract_to."""
    out = []
    for name, spec in models.items():
        if isinstance(spec, dict) and spec.get("archive") and spec.get("extract_to"):
            out.append((name, spec))
    return out


def fetch_archives(*, check_only: bool = False) -> int:
    """Fetch + verify + extract archive-distributed models (sherpa TTS voices).

    The archive is sha256-verified against ``archive_sha256`` (recorded on the
    first successful fetch when the manifest pins ``PENDING_FETCH``), then
    extracted so the entry's ``path`` (the .onnx inside) exists. Idempotent: a
    voice whose ``path`` already exists is skipped."""
    import bz2
    import tarfile

    models = _load_manifest()
    errors = 0
    for name, spec in _fetchable_archives(models):
        path = ROOT / spec.get("path", "")
        if path.exists():
            print(f"[ok]   {name}: {path.name} already extracted")
            continue
        if check_only:
            print(f"[miss] {name}: {path} absent ({spec.get('license')})")
            errors += 1
            continue
        url = spec["archive"]
        expected = str(spec.get("archive_sha256") or "")
        extract_to = ROOT / str(spec["extract_to"])
        extract_to.mkdir(parents=True, exist_ok=True)
        archive_path = extract_to / Path(url).name
        print(f"[get]  {name}: {url} -> {archive_path} ({spec.get('license')})")
        try:
            urllib.request.urlretrieve(url, archive_path)  # noqa: S310 - manifest-pinned URL
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"[fail] {name}: download error: {exc}")
            errors += 1
            continue
        actual = _sha256(archive_path)
        if expected and expected != "PENDING_FETCH" and actual != expected:
            print(f"[fail] {name}: archive sha256 mismatch (got {actual})")
            errors += 1
            continue
        if expected == "PENDING_FETCH":
            print(f"[pin]  {name}: record archive_sha256: {actual}")
        try:
            with tarfile.open(fileobj=bz2.BZ2File(archive_path), mode="r:") as tar:
                tar.extractall(extract_to)  # noqa: S202 - manifest-pinned archive
        except Exception as exc:  # pragma: no cover
            print(f"[fail] {name}: extract error: {exc}")
            errors += 1
            continue
        if path.exists():
            print(f"[ok]   {name}: extracted + voice present ({spec.get('license')})")
        else:
            print(f"[warn] {name}: extracted but {path} not found (check path in manifest)")
            errors += 1
    return errors


def _pin_sha256(name: str, spec: dict, key: str, actual: str) -> None:
    """Persist a freshly-computed sha256 back into the manifest (PENDING_FETCH).

    Device provisioning artefacts pin their hash on first successful fetch, so the
    SessionHub ``/models/device`` endpoint always serves a hash-matched file (the
    same pattern the E35 TTS archives use). We rewrite only the single
    ``PENDING_FETCH`` line for this entry to avoid reformatting the YAML."""
    text = MANIFEST.read_text(encoding="utf-8")
    needle = f"{key}: PENDING_FETCH"
    if needle not in text:
        return
    # Replace the first PENDING_FETCH occurrence that belongs to this entry: locate
    # the entry header, then the next matching key line after it.
    lines = text.splitlines()
    entry_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith(f"{name}:")), None)
    if entry_idx is None:
        return
    for i in range(entry_idx + 1, len(lines)):
        if lines[i].strip() == f"{key}: PENDING_FETCH":
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = f"{indent}{key}: {actual}"
            MANIFEST.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
            return


def fetch_device(*, check_only: bool = False) -> int:
    """Fetch + verify the Android device-local models (E47-C provisioning).

    Handles both single-file entries (``url`` — MediaPipe .task bundles) and
    archive entries (``archive`` + ``extract_to`` — sherpa-onnx .tar.bz2 ASR/KWS
    models). sha256 is ``PENDING_FETCH`` until the first successful fetch, when it
    is computed, verified on subsequent runs, and pinned back into the manifest so
    the provisioning endpoint serves a hash-matched artefact. Idempotent: an entry
    whose ``path`` already exists AND matches its pinned sha256 is skipped."""
    import bz2
    import tarfile

    device = _load_device()
    errors = 0
    for name, spec in device.items():
        if not isinstance(spec, dict):
            continue
        path = ROOT / spec.get("path", f"models/device/{name}")
        is_archive = bool(spec.get("archive"))
        url = spec.get("archive") if is_archive else spec.get("url")
        if not url:
            continue
        sha_key = "archive_sha256" if is_archive else "sha256"
        expected = str(spec.get(sha_key) or "")
        pinned = expected and expected != "PENDING_FETCH"

        if path.exists():
            # Archive entries verify the extracted directory's presence only (the
            # archive itself is not retained); single files verify the pinned sha.
            if is_archive or not pinned:
                print(f"[ok]   {name}: {path.name} present ({spec.get('license')})")
                continue
            actual = _sha256(path)
            if actual == expected:
                print(f"[ok]   {name}: {path.name} present, sha256 verified")
                continue
            print(f"[warn] {name}: {path.name} sha256 mismatch (have {actual[:12]}…)")
            if check_only:
                errors += 1
                continue
        elif check_only:
            print(f"[miss] {name}: {path} absent ({spec.get('license')})")
            errors += 1
            continue

        if is_archive:
            extract_to = ROOT / str(spec["extract_to"])
            extract_to.mkdir(parents=True, exist_ok=True)
            archive_path = extract_to / Path(url).name
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            archive_path = path
        print(f"[get]  {name}: {url} -> {archive_path} ({spec.get('license')})")
        try:
            urllib.request.urlretrieve(url, archive_path)  # noqa: S310 - manifest-pinned URL
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"[fail] {name}: download error: {exc}")
            errors += 1
            continue
        actual = _sha256(archive_path)
        if pinned and actual != expected:
            print(f"[fail] {name}: {sha_key} mismatch (got {actual})")
            errors += 1
            continue
        if not pinned:
            print(f"[pin]  {name}: record {sha_key}: {actual}")
            _pin_sha256(name, spec, sha_key, actual)
        if is_archive:
            try:
                with tarfile.open(fileobj=bz2.BZ2File(archive_path), mode="r:") as tar:
                    tar.extractall(extract_to)  # noqa: S202 - manifest-pinned archive
            except Exception as exc:  # pragma: no cover
                print(f"[fail] {name}: extract error: {exc}")
                errors += 1
                continue
        if path.exists():
            print(f"[ok]   {name}: ready ({spec.get('license')})")
        else:
            print(f"[warn] {name}: fetched but {path} not found (check path in manifest)")
            errors += 1
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch + verify V19 model weights.")
    ap.add_argument("--check", action="store_true", help="verify only, no download")
    ap.add_argument("--argos", action="store_true", help="also install Argos Translate packs")
    ap.add_argument("--tts", action="store_true", help="also fetch sherpa-onnx TTS voices (E35)")
    ap.add_argument("--device", action="store_true", help="also fetch Android device-local models (E47-C)")
    args = ap.parse_args()
    errors = fetch_all(check_only=args.check)
    if args.tts or not args.check:
        errors += fetch_archives(check_only=args.check)
    # Device provisioning weights are large and Android-only; fetch them only on
    # explicit --device (or a --check pass, which just reports their presence).
    if args.device or args.check:
        errors += fetch_device(check_only=args.check)
    if args.argos and not args.check:
        errors += install_argos()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
