from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "mlomega.ar.provider_gate.v1"


def validate_report(
    report: dict[str, Any],
    *,
    required_provider: str = "xreal_provider",
) -> dict[str, Any]:
    failures: list[str] = []
    provider = report.get("provider") or {}
    if report.get("schema_version") != SCHEMA:
        failures.append("schema_mismatch")
    if report.get("verdict") != "pass":
        failures.append(f"device_gate_not_pass:{report.get('verdict', 'missing')}")
    if report.get("expected_provider") != required_provider:
        failures.append("expected_provider_mismatch")
    if provider.get("ProviderBoundary") != required_provider:
        failures.append("active_provider_mismatch")
    if int(provider.get("SimultaneousActiveLoaderCount") or 0) > 1:
        failures.append("multiple_simultaneous_xr_loaders")
    if required_provider == "xreal_provider":
        if not provider.get("XrealSdkCompiled"):
            failures.append("xreal_sdk_not_compiled")
        if not provider.get("ArFoundationLoaded"):
            failures.append("ar_foundation_not_loaded")
        if float(report.get("ar_session_running_ratio") or 0.0) < 0.9:
            failures.append("xreal_ar_session_not_stable")
        if int(report.get("eye_frames_end") or 0) <= int(
            report.get("eye_frames_start") or 0
        ):
            failures.append("xreal_eye_not_progressing")

    # Loader candidates are only an ordered configuration list. This validator
    # deliberately never upgrades their presence to simultaneous support.
    return {
        "schema_version": "mlomega.ar.provider_gate.verdict.v1",
        "run_id": report.get("run_id"),
        "provider": required_provider,
        "ok": not failures,
        "failures": failures,
        "architecture": (
            "xreal_provider_primary_arcore_excluded_from_product"
            if required_provider == "xreal_provider"
            else "single_provider_gate"
        ),
        "source_report_path": report.get("report_path"),
    }


def validate_paths(
    paths: Iterable[Path],
    *,
    required_provider: str = "xreal_provider",
) -> dict[str, Any]:
    verdicts = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        verdict = validate_report(payload, required_provider=required_provider)
        verdict["input"] = str(path.resolve())
        verdicts.append(verdict)
    return {
        "ok": bool(verdicts) and all(item["ok"] for item in verdicts),
        "reports": verdicts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate disposable XREAL/AR provider gate reports."
    )
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument(
        "--require-provider",
        default="xreal_provider",
        choices=("xreal_provider", "google_arcore_provider"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_paths(
        args.reports,
        required_provider=args.require_provider,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
