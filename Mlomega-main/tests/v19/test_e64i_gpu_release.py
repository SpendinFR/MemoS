from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def test_voice_identity_gpu_cache_is_explicitly_releasable():
    from mlomega_audio_elite import voice_identity

    class FakeEmbedder:
        classifier = object()

    first = FakeEmbedder()
    second = FakeEmbedder()
    voice_identity._EMBEDDER_CACHE.clear()
    voice_identity._EMBEDDER_CACHE[("a", "cuda")] = first
    voice_identity._EMBEDDER_CACHE[("b", "cuda")] = second

    assert voice_identity.release_voice_identity_cache() == 2
    assert voice_identity._EMBEDDER_CACHE == {}
    assert first.classifier is None
    assert second.classifier is None
