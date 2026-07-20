"""PRO CloseDay prompt-volume shrink lot (Codex corrections 1-5).

All fakes, no real network, no paid run.  These exercise the surgical pieces of
``brain2_shared_facts_v19`` / ``brain2_strict_v13_2`` / ``cloud_providers_v19``
directly so they never touch a model backend.

Covers:
  * compact fact CORE ~<=100 tok/fact (correction 2);
  * similar_case_retrieval prior = pattern output + fingerprint + case index,
    NEVER the fact registry, and under 24k (correction 3);
  * lossless fallback: an over-budget fact list is windowed by source then merged
    without losing a ref (correction 4);
  * warm/probe: the fan-out does not start if cache_hit=0 at the probe, then does
    once the probe is hot (correction 5);
  * warm size guard: a large common core / episode prefix is NOT warmed twice
    (correction 1).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mlomega_audio_elite import brain2_shared_facts_v19 as shared
from mlomega_audio_elite import brain2_strict_v13_2 as strict
from mlomega_audio_elite import cloud_providers_v19 as cloud
from mlomega_audio_elite.night_orchestrator import estimate_tokens_for_text
from mlomega_audio_elite.utils import json_dumps

pytestmark = pytest.mark.memory


def _fact(source_engine: str, field: str, *, ordinal: int = 0, turn_id: str = "t-long-0") -> dict:
    payload = {
        "field_value": f"{source_engine}:{field}",
        "detail": "observation semantique essentielle bornee",
        "created_at": "2026-07-20T10:00:00Z",
        "episode_id": "ep-episode-identifier-long-0",
        "conversation_id": "conv-long-identifier-0",
        "person_id": "person-long-identifier-0",
        "confidence": 0.7,
        "evidence_manifest": [
            {"turn_id": turn_id, "evidence_role": "membership", "confidence": 0.7},
            {"turn_id": turn_id, "evidence_role": "primary_citation", "confidence": 0.7},
        ],
    }
    return {
        "fact_id": f"{source_engine}-{field}-{ordinal}",
        "episode_id": "ep-episode-identifier-long-0",
        "source_engine": source_engine,
        "source_field": field,
        "fact_type": field,
        "subject_ref": "person-1",
        "epistemic_status": "inferred",
        "evidence_status": "cited",
        "confidence": 0.7123,
        "confidence_ceiling": 0.8,
        "payload": payload,
    }


# --------------------------------------------------- Correction 2: compact core
def test_compact_registry_core_is_under_100_tokens_per_fact() -> None:
    facts = [_fact("context_resolver", "situation", ordinal=i) for i in range(30)]
    bundle = {"facts": facts, "capabilities": []}
    registry = shared.compact_fact_registry(bundle, {})
    assert len(registry["facts"]) == 30
    for entry in registry["facts"]:
        tokens = estimate_tokens_for_text(json_dumps(entry))
        assert tokens <= 100, (tokens, entry)


def test_compact_registry_factorises_the_repeated_episode_id() -> None:
    facts = [_fact("context_resolver", "situation", ordinal=i) for i in range(5)]
    bundle = {"facts": facts, "capabilities": []}
    registry = shared.compact_fact_registry(bundle, {})
    # The long episode id appears once, in the index, replaced by a short ref.
    assert registry["episode_index"] == {"ep0": "ep-episode-identifier-long-0"}
    assert all(entry.get("ep") == "ep0" for entry in registry["facts"])
    text = json_dumps(registry["facts"])
    assert "ep-episode-identifier-long-0" not in text
    # Provenance/bookkeeping keys never reach the per-fact value.
    assert "created_at" not in text
    assert "evidence_manifest" not in text
    assert "conversation_id" not in text
    assert "person_id" not in text


def test_compact_form_still_carries_source_engine_for_projection() -> None:
    # The projection by source_engine (correction A) must keep working.
    facts = [_fact("pattern_miner", "pattern"), _fact("social_model_engine", "role")]
    compact = shared.compact_facts_for_prompt({"facts": facts, "capabilities": []}, {})
    assert {f["source_engine"] for f in compact} == {"pattern_miner", "social_model_engine"}


# ---------------------------------- Correction 3: similar_case minimal prior
def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    return con


def test_similar_case_prior_has_only_pattern_output_fingerprint_and_case_index() -> None:
    con = _mem_con()
    bundle = {
        "conversation": {"participants": ["p1", "p2"]},
        "episodes": [
            {"episode_id": "ep-1", "topic": "rdv", "situation_summary": "un projet"},
        ],
        "turns": [{"turn_id": "t1", "text": "SECRET-TRANSCRIPT-TEXT"}],
    }
    pattern_output = {
        "confirmed_patterns": [
            {"pattern_type": "loop", "pattern_key": "k1", "title": "T", "usual_outcome": "o",
             "evidence": ["huge", "evidence", "list"], "counterexamples": ["x"]},
        ],
        "signals": [{"signal_type": "s", "signal_value": "v", "strength": 0.5}],
        "candidate_patterns": [],
    }
    prior = strict._similar_case_prior(
        con, person_id="me", conversation_id="conv-1",
        bundle=bundle, pattern_output=pattern_output,
    )
    assert set(prior) == {
        "projection", "note", "pattern_output_summary",
        "episode_fingerprint", "case_index",
    }
    text = json_dumps(prior)
    # NOT the 97-fact registry, and NOT the transcript.
    assert "facts" not in prior
    assert "SECRET-TRANSCRIPT-TEXT" not in text
    # pattern output is summarised (evidence lists dropped).
    assert "huge" not in text
    assert prior["pattern_output_summary"]["confirmed_patterns"][0]["pattern_key"] == "k1"
    # fingerprint carries the topic + participants.
    assert prior["episode_fingerprint"]["participants"] == ["p1", "p2"]
    assert prior["episode_fingerprint"]["episodes"][0]["topic"] == "rdv"


def test_similar_case_prior_stays_under_24k_with_many_patterns() -> None:
    con = _mem_con()
    bundle = {
        "conversation": {"participants": ["p1"]},
        "episodes": [{"episode_id": f"ep-{i}", "topic": f"t{i}"} for i in range(20)],
        "turns": [],
    }
    pattern_output = {
        "confirmed_patterns": [
            {"pattern_type": "loop", "pattern_key": f"k{i}", "title": f"T{i}",
             "usual_outcome": "o", "evidence": ["e"] * 50}
            for i in range(200)
        ],
        "candidate_patterns": [],
        "signals": [{"signal_type": "s", "signal_value": f"v{i}", "strength": 0.5} for i in range(200)],
    }
    prior = strict._similar_case_prior(
        con, person_id="me", conversation_id="conv-1",
        bundle=bundle, pattern_output=pattern_output,
    )
    tokens = estimate_tokens_for_text(json_dumps(prior))
    assert tokens < 24576, tokens


# --------------------------------- Correction 4: lossless fact windowing/merge
def test_window_facts_by_source_covers_every_ref_without_loss() -> None:
    facts = [
        {"id": "f0", "ref": "a.x", "source_engine": "a", "type": "x"},
        {"id": "f1", "ref": "a.x", "source_engine": "a", "type": "x"},
        {"id": "f2", "ref": "b.y", "source_engine": "b", "type": "y"},
        {"id": "f3", "ref": "b.z", "source_engine": "b", "type": "z"},
    ]
    windows = strict._window_facts_by_source(facts, max_facts_per_window=1)
    # Every fact lands in exactly one window; the union preserves all refs.
    flat = [f for window in windows for f in window]
    assert len(flat) == len(facts)
    assert {f["id"] for f in flat} == {"f0", "f1", "f2", "f3"}
    # Distinct (source, type) groups are never mixed into one window.
    for window in windows:
        keys = {(f["source_engine"], f["type"]) for f in window}
        assert len(keys) == 1


def test_merge_windowed_outputs_dedups_by_ref_and_averages_confidence() -> None:
    out_a = {
        "similar_cases": [{"id": "c1", "score": 0.5}, {"id": "c2", "score": 0.4}],
        "confidence": 0.6,
    }
    out_b = {
        "similar_cases": [{"id": "c2", "score": 0.4}, {"id": "c3", "score": 0.7}],
        "confidence": 0.8,
    }
    merged = strict._merge_windowed_fact_outputs([out_a, out_b])
    ids = [c["id"] for c in merged["similar_cases"]]
    # c2 appears once; no case lost.
    assert ids == ["c1", "c2", "c3"]
    assert merged["confidence"] == pytest.approx(0.7)


def test_partitioned_windows_input_facts_when_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # A tiny budget forces the input-fact windowing path; a fake window LLM
    # records how many distinct fact-window prompts it saw and returns the facts
    # it was given so the merge can be checked losslessly.
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "1200")
    monkeypatch.setenv("MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS", "256")

    projected = [
        {"id": f"f{i}", "ref": f"pattern_miner.p{i}", "source_engine": "pattern_miner",
         "type": f"type_{i % 3}", "v": {"detail": "x" * 80}}
        for i in range(12)
    ]

    seen_refs: list[set] = []

    from mlomega_audio_elite.night_orchestrator import LLMCallResult

    import json as _json

    class FakeWindowLLM:
        model = "fake-window-llm"

        def generate(self, prompt, *, output_budget: int):
            # The executor passes the render dict; ``prompt['prompt']`` is the
            # serialised engine prompt JSON string built by ``_engine_prompt``.
            raw = prompt.get("prompt") if isinstance(prompt, dict) else prompt
            payload = _json.loads(raw) if isinstance(raw, str) else (raw or {})
            facts = (
                payload.get("prior_engine_outputs", {})
                .get("shared_facts", {})
                .get("facts", [])
            )
            seen_refs.append({f["ref"] for f in facts})
            # Echo the received facts back as a business list so the merge is
            # observable, plus the required common fields.
            return LLMCallResult(
                ok=True,
                data={
                    "similar_cases": [{"id": f["ref"]} for f in facts],
                    "clusters": [],
                    "evidence": [],
                    "counter_evidence": [],
                    "confidence": 0.5,
                },
            )

    con = _mem_con()
    con.execute(
        "CREATE TABLE episodes(episode_id TEXT, start_time TEXT)"
    )
    con.execute("INSERT INTO episodes VALUES('ep-1','2026-07-20T00:00:00Z')")

    prior = {
        "direct_dependencies": {},
        "shared_facts": {
            "conversation_id": "conv-1",
            "projection": "per_dependency_source_engine",
            "facts": projected,
        },
    }
    result = strict._run_engine_partitioned(
        con,
        engine="similar_case_retrieval",
        episode_id="ep-1",
        person_id="me",
        bundle={"conversation": {}, "episodes": [], "turns": []},
        prior=prior,
        window_llm=FakeWindowLLM(),
        projected_facts=projected,
    )
    # The input was split into more than one window...
    assert len(seen_refs) > 1
    # ...the union of the windowed inputs is the full projected set (lossless)...
    union = set().union(*seen_refs)
    assert union == {f["ref"] for f in projected}
    # ...and the merged output carries every case ref exactly once.
    merged_ids = [c["id"] for c in result["similar_cases"]]
    assert sorted(merged_ids) == sorted(f["ref"] for f in projected)
    assert len(merged_ids) == len(set(merged_ids))


# --------------------------------------- Correction 5: warm/probe fan-out gate
@pytest.fixture
def cloud_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cloud.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "5.00")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    cloud._BUNDLE_WARM_RESPONSES.clear()
    return db


def test_probe_bundle_prefix_reports_cold_then_hot(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Two probe_bundle_prefix calls: the prefix carrying "COLD" reports hit=0 on
    # its probe, the one carrying "HOT" reports hit>0.  The probe is the LAST
    # request of the three (two warms then one probe) for a given prefix.
    per_prefix: dict[str, int] = {}

    def fake_json_request(url, payload, **kwargs):
        # messages[1] is the canonical prefix; label the prefix by its content.
        prefix = payload["messages"][1]["content"]
        per_prefix[prefix] = per_prefix.get(prefix, 0) + 1
        is_probe = per_prefix[prefix] == 3  # third request for this prefix
        hit = 0
        if is_probe:
            hit = 64 if "HOT" in prefix else 0
        return {
            "choices": [{"message": {"content": '{"bundle_loaded":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": hit,
                      "prompt_cache_miss_tokens": 100 - hit, "completion_tokens": 3},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    cold = cloud.probe_bundle_prefix("ep-1", {"tag": "COLD"}, timeout=5)
    assert cold["cache_hit"] is False and cold["hit_tokens"] == 0
    hot = cloud.probe_bundle_prefix("ep-2", {"tag": "HOT"}, timeout=5)
    assert hot["cache_hit"] is True and hot["hit_tokens"] == 64


def test_fanout_gate_is_false_when_probe_cold(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_json_request(url, payload, **kwargs):
        return {
            "choices": [{"message": {"content": '{"bundle_loaded":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 0,
                      "prompt_cache_miss_tokens": 100, "completion_tokens": 3},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    ready = strict._pro_probe_fanout_ready([("ep-1", {"episode": {"episode_id": "ep-1"}})])
    assert ready is False


def test_fanout_gate_is_true_when_probe_hot(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_json_request(url, payload, **kwargs):
        return {
            "choices": [{"message": {"content": '{"bundle_loaded":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 90,
                      "prompt_cache_miss_tokens": 10, "completion_tokens": 3},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    ready = strict._pro_probe_fanout_ready([("ep-1", {"episode": {"episode_id": "ep-1"}})])
    assert ready is True


def test_fanout_gate_skips_probe_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_PRO_FANOUT_PROBE", "0")
    # No network fake needed: the probe must be skipped entirely.
    assert strict._pro_probe_fanout_ready([("ep-1", {"episode": {"episode_id": "ep-1"}})]) is True


# ------------------------------------- Correction 1: never warm a big prefix 2x
def test_warm_global_fact_core_skips_when_core_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(cloud, "warm_bundle_prefix", lambda *a, **k: called.append(a) or "w")
    monkeypatch.setenv("MLOMEGA_PRO_WARM_MAX_TOKENS", "50")
    big_core = [
        {"ref": f"pattern_miner.p{i}", "value": {"detail": "x" * 200}} for i in range(20)
    ]
    strict._pro_warm_global_fact_core("conv-1", big_core)
    assert called == []  # too big -> skip rather than pay a big MISS twice


def test_warm_global_fact_core_warms_a_small_core(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(cloud, "warm_bundle_prefix", lambda *a, **k: called.append(a) or "w")
    monkeypatch.setenv("MLOMEGA_PRO_WARM_MAX_TOKENS", "12288")
    small_core = [{"ref": "prediction_engine.prediction", "value": {"x": 1}}]
    strict._pro_warm_global_fact_core("conv-1", small_core)
    assert len(called) == 1


def test_warm_episode_prefixes_skips_oversized_bundles(cloud_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_DEEPSEEK_CACHE_SETTLE_S", "0")
    monkeypatch.setenv("MLOMEGA_PRO_WARM_MAX_TOKENS", "50")
    sent = []

    def fake_json_request(url, payload, **kwargs):
        sent.append(payload)
        return {
            "choices": [{"message": {"content": '{"bundle_loaded":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    big = {"episode": {"episode_id": "ep-1"}, "turns": [{"text": "x" * 4000}]}
    strict._pro_warm_episode_prefixes([("ep-1", big)])
    assert sent == []  # oversized episode prefix is never warmed
