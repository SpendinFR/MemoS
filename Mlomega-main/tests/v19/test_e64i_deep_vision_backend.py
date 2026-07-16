from __future__ import annotations

"""E64-I4.2 Deep Vision backend: model resolution, strict JSON, cache, status.

These tests exercise the REAL backend choke point (``_deep_vlm_json``) and the
V18 override (``v18_poststop_outputs.install_deep``) with a FAKE Ollama transport
so no network/model is touched.  The only real qwen3-vl:8b call in I4.2 is the
manual single-image proof documented in the handoff, not here.

Proven here:
* the offline VLM model resolves to a real VLM (qwen3-vl:8b), never the text
  ``settings.ollama_model``;
* ``think: false`` is present in the Ollama payload (the Qwen empty-JSON trap);
* invalid/empty VLM JSON is an explicit failure, never cached, never applied;
* the cache is keyed by sha256(image)+model+prompt_version: a 2nd call on the
  same image makes ZERO network calls; a prompt-version bump forces a miss;
* honest status: selected>0 and analyzed==0 is never 'ok'.
"""

import json

import pytest

from mlomega_audio_elite import brainlive_offline_deep_vision_v16_1 as base


def _valid_vlm_response() -> dict:
    return {
        "scene_summary_detailed": "a person at a desk with a screen",
        "observed_activity": "computer_work",
        "activity_confidence": 0.4,
        "objects": ["person", "screen"],
        "exact_visual_evidence": ["visible keyboard", "monitor on"],
        "uncertainty": ["cannot confirm the task"],
    }


@pytest.fixture()
def img(tmp_path):
    p = tmp_path / "frame.jpg"
    # A tiny non-empty file; the fake transport never decodes it.
    p.write_bytes(b"\xff\xd8\xff\xe0not-a-real-jpeg-but-bytes")
    return p


def _install_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "backend.db"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_ENABLE_OLLAMA", "true")
    # No offline VLM override set -> must fall back to the VLM default, not text.
    for k in ("MLOMEGA_OFFLINE_VLM_MODEL", "MLOMEGA_VLM_HEAVY_MODEL", "MLOMEGA_VLM_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_resolves_real_vlm_not_text_model(monkeypatch):
    for k in ("MLOMEGA_OFFLINE_VLM_MODEL", "MLOMEGA_VLM_HEAVY_MODEL", "MLOMEGA_VLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert base._resolve_offline_vlm_model() == base.DEFAULT_OFFLINE_VLM_MODEL == "qwen3-vl:8b"
    # An explicit override still wins.
    monkeypatch.setenv("MLOMEGA_OFFLINE_VLM_MODEL", "qwen3-vl:4b")
    assert base._resolve_offline_vlm_model() == "qwen3-vl:4b"
    assert base._resolve_offline_vlm_model("explicit:1b") == "explicit:1b"


def test_payload_has_think_false_and_format_json(monkeypatch, tmp_path, img):
    _install_env(monkeypatch, tmp_path)
    captured = {}

    def fake_generate(payload, **kwargs):
        captured.update(payload)
        return {"response": json.dumps(_valid_vlm_response()), "eval_count": 220}

    monkeypatch.setattr(base, "ollama_generate", fake_generate)
    data = base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert captured["think"] is False
    assert captured["format"] == "json"
    assert captured["model"] == "qwen3-vl:8b"
    assert data["observed_activity"] == "computer_work"
    assert data["_cache_hit"] is False
    assert data["_output_tokens"] == 220


def test_invalid_empty_json_is_explicit_failure_not_cached(monkeypatch, tmp_path, img):
    _install_env(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_generate(payload, **kwargs):
        calls["n"] += 1
        return {"response": "{}", "eval_count": 0}  # the empty-JSON trap

    monkeypatch.setattr(base, "ollama_generate", fake_generate)
    with pytest.raises(base.EliteLLMError):
        base._deep_vlm_json(str(img), model=None, timeout=5.0)
    # A second attempt must still hit the network (nothing invalid was cached).
    with pytest.raises(base.EliteLLMError):
        base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert calls["n"] == 2


def test_cache_hit_makes_zero_network_calls(monkeypatch, tmp_path, img):
    _install_env(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_generate(payload, **kwargs):
        calls["n"] += 1
        return {"response": json.dumps(_valid_vlm_response()), "eval_count": 200}

    monkeypatch.setattr(base, "ollama_generate", fake_generate)

    first = base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert first["_cache_hit"] is False
    assert calls["n"] == 1

    # Same image + model + prompt version -> cache hit, zero new network calls.
    second = base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert second["_cache_hit"] is True
    assert calls["n"] == 1
    assert second["observed_activity"] == first["observed_activity"]


def test_cache_misses_when_prompt_version_changes(monkeypatch, tmp_path, img):
    _install_env(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_generate(payload, **kwargs):
        calls["n"] += 1
        return {"response": json.dumps(_valid_vlm_response()), "eval_count": 200}

    monkeypatch.setattr(base, "ollama_generate", fake_generate)

    base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert calls["n"] == 1
    # Bump the prompt version: the previously cached answer is stale -> miss.
    monkeypatch.setattr(base, "DEEP_VISION_PROMPT_VERSION", base.DEEP_VISION_PROMPT_VERSION + "-bumped")
    out = base._deep_vlm_json(str(img), model=None, timeout=5.0)
    assert out["_cache_hit"] is False
    assert calls["n"] == 2


def test_cache_misses_on_different_model(monkeypatch, tmp_path, img):
    _install_env(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_generate(payload, **kwargs):
        calls["n"] += 1
        return {"response": json.dumps(_valid_vlm_response()), "eval_count": 200}

    monkeypatch.setattr(base, "ollama_generate", fake_generate)
    base._deep_vlm_json(str(img), model="qwen3-vl:8b", timeout=5.0)
    base._deep_vlm_json(str(img), model="qwen3-vl:4b", timeout=5.0)
    assert calls["n"] == 2  # different model -> different cache key -> real call


def _seed_bundle(tmp_path):
    img = tmp_path / "kf.jpg"
    img.write_bytes(b"\xff\xd8\xffbytes")
    return {
        "bundle_id": "b1", "person_id": "me", "package_date": "2026-07-16",
        "live_session_id": "s1", "brain2_conversation_id": None, "title": "t",
        "place_json": "{}", "status": "assembled",
        "vision_timeline_json": json.dumps([
            {"source_table": "vision_scene_observations", "source_id": "o0", "frame_id": "f0",
             "image_path": str(img), "time": "2026-07-16T10:00:00+00:00",
             "objects": [{"label": "person", "track_id": "t1"}], "people_count": 1,
             "visible_text": [], "summary": "a"},
        ]),
    }


def test_override_status_honest_when_selected_but_none_analyzed(monkeypatch, tmp_path):
    """Codex I4.2 point 6: selected>0 and analyzed==0 is never 'ok'."""
    _install_env(monkeypatch, tmp_path)
    from mlomega_audio_elite import v18_poststop_outputs as ov

    bundle = _seed_bundle(tmp_path)
    monkeypatch.setattr(
        ov, "strict_many",
        lambda con, sql, params=(), purpose=None: [bundle] if "brainlive_event_bundles_v1514" in sql else [],
    )
    monkeypatch.setattr(base, "_image_exists", lambda p: bool(p))

    def boom(*a, **k):
        raise base.EliteLLMError("vlm unavailable")

    monkeypatch.setattr(base, "_deep_vlm_json", boom)

    funcs = ov.install_deep(base)
    out = funcs["run_offline_deep_vision_for_bundles"](
        person_id="me", package_date="2026-07-16", live_session_id="s1",
        append_to_brain2=False, use_vlm=True,
    )
    assert out["selected_keyframes"] > 0
    assert out["analyzed_keyframes"] == 0
    assert out["status"] != "ok"
    assert out["status"] in {"retryable_error", "failed"}
    assert out["model"] == "qwen3-vl:8b"  # resolved to a real VLM, not the text model

    # The durable run row the I0.4 gate reads must expose the same honest status.
    from mlomega_audio_elite.db import connect
    with connect() as con:
        row = con.execute(
            "SELECT selected_keyframes, analyzed_keyframes, status FROM brainlive_deep_vision_runs_v161 WHERE run_id=?",
            (out["run_id"],),
        ).fetchone()
    assert row["selected_keyframes"] > 0 and row["analyzed_keyframes"] == 0
    assert str(row["status"]).lower() != "ok"
