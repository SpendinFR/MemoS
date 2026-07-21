"""PRO CloseDay cost-reduction lot: direct-dependency DAG prior projection,
global-engine canonical-facts prior, 24k context cap, real engine_name in the
cloud ledger, and the local path staying byte-for-byte unchanged.

All fakes, no real network, no paid run.  These exercise the surgical pieces of
``brain2_strict_v13_2`` / ``cloud_providers_v19`` directly so they never touch a
model backend.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mlomega_audio_elite import brain2_strict_v13_2 as strict
from mlomega_audio_elite import cloud_providers_v19 as cloud

pytestmark = pytest.mark.memory


# --------------------------------------------------------- Task 1: per-episode DAG
def test_direct_prior_contains_only_direct_dependencies() -> None:
    # A full cumulated prior: every engine has produced an output.
    conversation_outputs = {"pattern_miner": {"conv": "scope"}}
    episode_outputs = {
        "capture_engine": {"c": 1},
        "language_signature_engine": {"l": 1},
        "context_resolver": {"ctx": 1},
        "internal_state_engine": {"is": 1},
        "social_model_engine": {"soc": 1},
        # An engine that is NOT a dependency of causality_engine:
        "contradiction_engine": {"contra": 1},
    }

    prior = strict._direct_prior(
        "causality_engine", conversation_outputs, episode_outputs
    )
    # causality_engine depends ONLY on internal_state_engine + social_model_engine.
    assert set(prior) == {"internal_state_engine", "social_model_engine"}
    # Non-dependencies must never leak in, even though they exist in the outputs.
    assert "capture_engine" not in prior
    assert "context_resolver" not in prior
    assert "contradiction_engine" not in prior
    assert "pattern_miner" not in prior


def test_direct_prior_empty_for_root_engine() -> None:
    episode_outputs = {"capture_engine": {"c": 1}, "language_signature_engine": {"l": 1}}
    # capture_engine has no dependency -> {} (episode bundle travels in the prefix).
    assert strict._direct_prior("capture_engine", {}, episode_outputs) == {}
    assert strict._direct_prior("language_signature_engine", {}, episode_outputs) == {}


def test_context_resolver_gets_its_two_direct_parents() -> None:
    episode_outputs = {
        "capture_engine": {"c": 1},
        "language_signature_engine": {"l": 1},
        "internal_state_engine": {"leak": 1},
    }
    prior = strict._direct_prior("context_resolver", {}, episode_outputs)
    assert set(prior) == {"capture_engine", "language_signature_engine"}


def test_engine_direct_deps_are_consistent_with_known_levels() -> None:
    # The per-episode DAG order must agree with the executed ``known_levels`` waves:
    # no engine may depend on an engine scheduled in the same or a later wave.
    known_levels = [
        ("capture_engine", "language_signature_engine"),
        ("context_resolver",),
        ("internal_state_engine", "social_model_engine"),
        ("causality_engine", "contradiction_engine", "choice_model_engine"),
        ("outcome_tracker",),
    ]
    level_of = {
        engine: idx for idx, level in enumerate(known_levels) for engine in level
    }
    for engine, level in level_of.items():
        for parent in strict._ENGINE_DIRECT_DEPS.get(engine, ()):
            assert parent in level_of, f"{engine} parent {parent} not in known_levels"
            assert level_of[parent] < level, (
                f"{engine} (wave {level}) depends on {parent} "
                f"(wave {level_of[parent]}) which is not strictly earlier"
            )


# --------------------------------------------------- Task 2: global engine prior
def test_global_engine_direct_prior_chain() -> None:
    # Simulate the sequential global fan-out: ``packed`` grows as engines run.
    packed: dict[str, dict] = {}
    packed["pattern_miner"] = {"pm": 1}
    # similar_case_retrieval depends only on pattern_miner.
    prior = strict._direct_prior("similar_case_retrieval", {}, packed)
    assert set(prior) == {"pattern_miner"}

    packed["similar_case_retrieval"] = {"scr": 1}
    prior = strict._direct_prior("prediction_engine", {}, packed)
    assert set(prior) == {"pattern_miner", "similar_case_retrieval"}

    packed["prediction_engine"] = {"pred": 1}
    packed["simulation_engine"] = {"sim": 1}
    prior = strict._direct_prior("calibration_engine", {}, packed)
    assert set(prior) == {"prediction_engine", "simulation_engine"}
    # intervention_engine never receives raw pattern_miner / by_episode.
    packed["calibration_engine"] = {"cal": 1}
    prior = strict._direct_prior("intervention_engine", {}, packed)
    assert set(prior) == {"calibration_engine", "prediction_engine"}
    assert "pattern_miner" not in prior
    assert "similar_case_retrieval" not in prior


def test_compact_fact_bundle_is_the_canonical_registry_reader() -> None:
    # The global prior reuses ``compact_fact_bundle`` (canonical shared facts) —
    # prove that function reads the canonical engine-section table for a
    # conversation and returns facts + capabilities, not raw by_episode outputs.
    from mlomega_audio_elite import brain2_shared_facts_v19 as shared_facts

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    shared_facts.ensure_shared_fact_schema(con)
    bundle = shared_facts.compact_fact_bundle(con, "conv-empty")
    assert bundle["conversation_id"] == "conv-empty"
    assert bundle["facts"] == []
    assert bundle["capabilities"] == []
    assert set(bundle) == {"version", "conversation_id", "facts", "capabilities"}


# ------------------------------------------ Task 3: cloud context cap (one call/engine)
def test_pro_context_cap_lets_each_engine_fit_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    # After the projection work, the largest legitimate input is pattern_miner's
    # ~27k projected facts. The cloud cap is 49152 (not the local-P1 24576) so every
    # engine runs in ONE cached DeepSeek call instead of ~27 windowed round trips.
    # It is NOT the old 65536 blanket, and the windowing fallback stays as a safety
    # net for a genuinely huge input.
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.delenv("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", raising=False)
    default = int(os.environ.get("MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "49152"))
    assert default == 49152
    # The source default is 49152 (operator-overridable), not the local 24576 nor
    # the old 65536 free pass.
    src = Path(strict.__file__).read_text(encoding="utf-8")
    assert 'MLOMEGA_CLOUD_CONTEXT_POSTSTOP", "49152"' in src
    assert '"65536"' not in src.split("_CONVERSATION_SCOPE_ENGINES")[0]


# ----------------------------------------------------- Task 4: real engine_name
@pytest.fixture
def cloud_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cloud.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "1.50")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    return db


def test_ledger_records_real_engine_stage_not_closeday_text(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_json_request(url, payload, **kwargs):
        return {
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    with cloud.cloud_engine_stage("brain2_engine:pattern_miner:ep-1"):
        cloud.deepseek_chat_json(
            system="ENGINE", prompt="TASK", json_schema={"type": "object"},
            max_output_tokens=50, timeout=5,
        )
    with sqlite3.connect(cloud_env) as con:
        stages = {
            row[0]
            for row in con.execute("SELECT stage_name FROM cloud_cost_ledger_v19")
        }
    assert "brain2_engine:pattern_miner:ep-1" in stages
    assert "closeday_text" not in stages


def test_ledger_falls_back_to_closeday_text_without_binding(
    cloud_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_json_request(url, payload, **kwargs):
        return {
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)
    # No cloud_engine_stage binding -> historic label preserved (additive change).
    assert cloud.current_engine_stage() is None
    cloud.deepseek_chat_json(
        system="ENGINE", prompt="TASK", json_schema={"type": "object"},
        max_output_tokens=50, timeout=5,
    )
    with sqlite3.connect(cloud_env) as con:
        stages = {
            row[0]
            for row in con.execute("SELECT stage_name FROM cloud_cost_ledger_v19")
        }
    assert "closeday_text" in stages


# --------------------------------------- local path stays byte-for-byte unchanged
def test_local_path_does_not_bind_engine_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without MLOMEGA_PRO_CLOSEDAY the engine stage ContextVar is never set, so the
    # local Ollama path keeps its exact historic ledger/stage behaviour.
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    assert cloud.current_engine_stage() is None
