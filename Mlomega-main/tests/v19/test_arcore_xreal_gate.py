from tools.arcore_xreal_gate.validate_report import validate_report


def _passing_report():
    return {
        "schema_version": "mlomega.ar.provider_gate.v1",
        "run_id": "ar-gate-test",
        "expected_provider": "xreal_provider",
        "verdict": "pass",
        "ar_session_running_ratio": 1.0,
        "eye_frames_start": 10,
        "eye_frames_end": 1810,
        "provider": {
            "ProviderBoundary": "xreal_provider",
            "SimultaneousActiveLoaderCount": 1,
            "XrealSdkCompiled": True,
            "ArFoundationLoaded": True,
            "ConfiguredLoaderCandidates": [
                "Unity.XR.XREAL.XREALXRLoader",
                "UnityEngine.XR.ARCore.ARCoreLoader",
            ],
        },
    }


def test_configured_arcore_candidate_is_not_misreported_as_coexistence():
    verdict = validate_report(_passing_report())

    assert verdict["ok"] is True
    assert verdict["architecture"] == (
        "xreal_provider_primary_arcore_excluded_from_product"
    )


def test_gate_rejects_missing_eye_or_multiple_active_loaders():
    report = _passing_report()
    report["eye_frames_end"] = report["eye_frames_start"]
    report["provider"]["SimultaneousActiveLoaderCount"] = 2

    verdict = validate_report(report)

    assert verdict["ok"] is False
    assert "xreal_eye_not_progressing" in verdict["failures"]
    assert "multiple_simultaneous_xr_loaders" in verdict["failures"]
