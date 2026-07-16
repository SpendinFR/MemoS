import importlib.util
import sys
import warnings
from pathlib import Path

import pytest

pytestmark = pytest.mark.transport


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gpu_arbiter = load("v19_gpu_arbiter", "services/live-pc/gpu_arbiter.py")


def _arbiter_with_snapshot(total_mb, used_mb, available=True, **kw):
    arb = gpu_arbiter.GpuArbiter(**kw)
    snap = gpu_arbiter.GpuSnapshot(total_mb=total_mb, used_mb=used_mb, available=available)
    arb.snapshot = lambda: snap  # type: ignore[assignment]
    return arb


def test_budgets_loaded_from_rtx3070_profile_ratio():
    arb = gpu_arbiter.GpuArbiter()
    # rtx3070.yaml sets gpu.max_live_vram_ratio: 0.90
    assert arb.max_used_ratio == pytest.approx(0.90)
    assert "vlm" in arb.job_budgets_mb and "live_llm" in arb.job_budgets_mb


def test_request_grants_tracker_even_without_gpu():
    arb = _arbiter_with_snapshot(0, 0, available=False)
    res = arb.request("tracker")
    assert res["grant"] is True
    assert arb.request("detector")["grant"] is True
    assert arb.request("asr")["grant"] is True
    res_vlm = arb.request("vlm")
    assert res_vlm["grant"] is False


def test_request_denies_low_priority_under_global_pressure():
    arb = _arbiter_with_snapshot(8192, 7800, max_used_ratio=0.90)
    # detector is protected by the priority floor; vlm/ocr are refused.
    assert arb.request("detector")["grant"] is True
    assert arb.request("vlm")["grant"] is False
    assert "gpu_vram_pressure" in arb.degraded_reasons


def test_request_denies_when_job_does_not_fit_under_live_ceiling():
    arb = _arbiter_with_snapshot(8192, 4000, max_used_ratio=0.99,
                                 job_budgets_mb={"live_llm": 5000})
    res = arb.request("live_llm")
    assert res["grant"] is False
    assert res["reason"] == "insufficient_vram_headroom"
    assert res["budget_mb"] == 5000
    assert res["projected_used_mb"] == 9000


def test_request_grants_ocr_when_its_incremental_footprint_fits():
    # ASR + detector already use more than the OCR footprint itself. This is
    # normal: only used + OCR footprint versus the live ceiling matters.
    arb = _arbiter_with_snapshot(8192, 3000, max_used_ratio=0.90,
                                 job_budgets_mb={"ocr": 768})
    res = arb.request("ocr")
    assert res["grant"] is True
    assert res["projected_used_mb"] == 3768
    assert res["live_limit_mb"] == 7372


def test_verify_ollama_unload_warns_when_still_resident():
    arb = _arbiter_with_snapshot(8192, 6000)
    arb._ollama_ps = lambda base_url, timeout=8.0: [{"name": "qwen3.5:9b"}]  # type: ignore[assignment]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = arb.verify_ollama_unload("qwen3.5:9b")
    assert res["unloaded"] is False
    assert res["still_resident"] is True
    assert any(issubclass(w.category, RuntimeWarning) for w in caught)


def test_verify_ollama_unload_ok_when_not_resident():
    arb = _arbiter_with_snapshot(8192, 1000)
    arb._ollama_ps = lambda base_url, timeout=8.0: []  # type: ignore[assignment]
    res = arb.verify_ollama_unload("qwen3.5:9b", before_used_mb=6000)
    assert res["unloaded"] is True
    assert res["freed_mb"] == 5000
