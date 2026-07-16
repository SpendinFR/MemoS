from __future__ import annotations

"""E64-i chantier 4: the harness /session/end call uses a configurable timeout."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tools" / "harness" / "fake_xr_device.py"


def _load():
    spec = importlib.util.spec_from_file_location("e64i_fake_xr_device", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_end_timeout_cli_flag_is_parsed_with_generous_default(monkeypatch):
    device_mod = _load()
    parsed = {}

    class _Recorder(device_mod.FakeXrDevice):
        def __init__(self, **kwargs):
            parsed.update(kwargs)
            # Do not run the real constructor / network client.

    monkeypatch.setattr(device_mod, "FakeXrDevice", _Recorder)
    monkeypatch.setattr(device_mod, "synth_media_mp4", lambda *_a, **_k: Path("x.mp4"))
    monkeypatch.setattr(device_mod, "load_scenario", lambda _p: [])

    import asyncio

    async def _fake_run(self):
        return {"errors": []}

    monkeypatch.setattr(_Recorder, "run", _fake_run, raising=False)

    # Default: generous 900 s.
    assert _parse(device_mod, []).end_timeout == 900.0

    # Override propagates through to the device constructor.
    ns = _parse(device_mod, ["--end-timeout", "42"])
    assert ns.end_timeout == 42.0
    asyncio.run(device_mod._amain(ns))
    assert parsed["end_timeout"] == 42.0


def _parse(device_mod, argv):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8730)
    parser.add_argument("--media", default=None)
    parser.add_argument("--scenario", default=str(device_mod.DEFAULT_SCENARIO))
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--session-id", dest="session_id", default="e63-harness")
    parser.add_argument("--end-session", dest="end_session", action="store_true", default=True)
    parser.add_argument("--no-end-session", dest="end_session", action="store_false")
    parser.add_argument("--end-timeout", type=float, default=900.0)
    parser.add_argument("--synth-seconds", type=int, default=60)
    parser.add_argument("--synth-dir", default=None)
    parser.add_argument("--out", default=None)
    return parser.parse_args(argv)


def test_end_timeout_stored_on_device_instance():
    device_mod = _load()
    device = device_mod.FakeXrDevice(
        host="127.0.0.1", port=8730, media=Path("x.mp4"),
        scenario=[], device_id="d", end_timeout=123.0,
    )
    assert device.end_timeout == 123.0
