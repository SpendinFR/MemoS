"""E27 AudioRT: VAD segmentation, faster-whisper transcription, translation."""

from __future__ import annotations

import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.vision

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "v19" / "fixtures"

for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audiort = _load("v19_audiort", "services/live-pc/audiort.py")
pytest.importorskip("webrtcvad")

from packages.contracts.python.models import UIIntent  # noqa: E402


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype="<i2"), rate


def test_resample_to_16k_mono():
    # 48 kHz stereo tone -> 16 kHz mono.
    t = np.linspace(0, 1, 48000, endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 16000).astype("<i2")
    stereo = np.stack([tone, tone], axis=1)
    mono = audiort.to_mono_16k(stereo, 48000)
    assert abs(len(mono) - 16000) <= 2
    assert mono.dtype == np.float32
    assert mono.max() <= 1.0 and mono.min() >= -1.0


def test_vad_segments_speech_not_silence():
    seg = audiort.VadSegmenter(audiort.VadConfig(aggressiveness=2, min_speech_ms=100))
    # 1s silence -> no segment
    silence = np.zeros(16000, dtype=np.float32)
    assert seg.push(silence) == []
    # Load real speech and confirm at least one segment is produced.
    if not (FIX / "speech_en.wav").exists():
        pytest.skip("speech fixture missing")
    samples, rate = _read_wav(FIX / "speech_en.wav")
    mono = audiort.to_mono_16k(samples, rate)
    seg2 = audiort.VadSegmenter(audiort.VadConfig(aggressiveness=2, min_speech_ms=150))
    got = seg2.push(mono)
    tail = seg2.flush()
    if tail is not None:
        got.append(tail)
    assert len(got) >= 1, "VAD produced no speech segment on real speech"


@pytest.fixture(scope="module")
def whisper_transcriber():
    tr = audiort.WhisperTranscriber(model_size="small")
    if tr._ensure() is None:
        pytest.skip("faster-whisper model unavailable")
    yield tr
    tr._model = None


@pytest.mark.skipif(not (FIX / "speech_en.wav").exists(), reason="speech fixture missing")
def test_whisper_transcribes_and_emits_subtitle(whisper_transcriber):
    samples, rate = _read_wav(FIX / "speech_en.wav")
    emitted: list[dict] = []
    rt = audiort.AudioRT(
        session_id="t", target_language="fr", on_intent=emitted.append,
        transcriber=whisper_transcriber,
    )
    out = rt.push_audio(samples, rate) + rt.flush()
    assert out, "no subtitle intents emitted"
    # Partial precedes final; both validate against the UIIntent contract.
    for intent in out:
        UIIntent.model_validate(intent)
        assert intent["component"] == "subtitle"
        assert intent["producer"] == "ultralive"  # reflex path, never brainlive
    assert any(i["content"]["final"] for i in out)
    finals = [i for i in out if i["content"]["final"] and i["content"]["status"] == "ok"]
    assert finals, out
    # The transcription contains recognisable words from the fixture phrase.
    text = " ".join(i["content"]["text"].lower() for i in finals)
    assert any(w in text for w in ("fox", "dog", "brown", "river")), text


def test_optional_translation_provider_is_not_on_phoneonly_critical_path():
    class _FrenchTranscriber:
        last_infer_ms = 1.0

        def transcribe(self, _segment):
            return {"status": "ok", "text": "bonjour", "language": "fr"}

    class _Translator:
        def translate(self, text, from_lang, to_lang):
            assert (text, from_lang, to_lang) == ("bonjour", "fr", "en")
            return {"status": "ok", "text": "hello"}

    rt = audiort.AudioRT(
        session_id="t", target_language="en", transcriber=_FrenchTranscriber(),
        translator=_Translator(), enable_translation=True,
    )
    out = rt._handle_segment(np.zeros(16000, dtype=np.float32))
    finals = [i for i in out if i["content"]["final"]]
    assert finals[0]["content"]["translated_text"] == "hello"
    assert finals[0]["content"]["target_language"] == "en"


def test_degraded_asr_refused_by_arbiter():
    class _DenyArbiter:
        def request(self, job_class):
            return {"grant": False, "reason": "test_deny"}

    rt = audiort.AudioRT(session_id="t", arbiter=_DenyArbiter())
    # Feed a speech-like segment directly through segment handling.
    seg = np.random.default_rng(0).uniform(-0.3, 0.3, 8000).astype(np.float32)
    out = rt._handle_segment(seg)
    assert out and out[0]["content"]["status"] == "asr_refused"
