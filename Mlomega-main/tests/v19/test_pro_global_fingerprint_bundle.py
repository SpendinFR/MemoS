"""PRO CloseDay: the GLOBAL engines receive the EPISODE FINGERPRINT, never the
~25k-token transcript (Codex correction 3).

All fakes, no real network, no paid run.  These exercise the surgical pieces of
``brain2_strict_v13_2`` directly so they never touch a model backend.

The bug this pins: ``_conversation_engine_bundle`` (with its full ``turns``
transcript) used to be serialised into every GLOBAL engine prompt via
``bundle=bundle`` at the PRO fan-out, pushing ``similar_case_retrieval``'s field
windows to 25122 / 24973 tokens — 546 over the 24576 input budget — so the stage
quarantined with ``single unit exceeds input budget`` and attempts=0.  The globals
synthesise from their PROJECTED inputs (direct parents / per-dependency facts /
similar_case prior), so they only need the compact fingerprint.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from mlomega_audio_elite import brain2_strict_v13_2 as strict
from mlomega_audio_elite.night_orchestrator import (
    LLMCallResult,
    estimate_tokens_for_text,
)
from mlomega_audio_elite.utils import json_dumps

pytestmark = pytest.mark.memory


_SECRET_TRANSCRIPT = "SECRET-HUMAN-TRANSCRIPT-DO-NOT-SHIP-TO-GLOBALS"

_GLOBAL_ENGINES = (
    "pattern_miner",
    "similar_case_retrieval",
    "prediction_engine",
    "simulation_engine",
    "calibration_engine",
    "intervention_engine",
)


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE episodes(episode_id TEXT, start_time TEXT)")
    con.execute("INSERT INTO episodes VALUES('ep-1','2026-07-20T00:00:00Z')")
    return con


def _fat_conversation_bundle() -> dict:
    """A ``_conversation_engine_bundle``-shaped dict with a big transcript.

    ~25k tokens of ``turns`` so the raw bundle, if serialised into an engine
    prompt, blows the 24576 input budget — exactly the quarantine cause.
    """

    turns = [
        {
            "turn_id": f"turn_blbundle_deep_audio_v185_{i:08x}",
            "speaker": "William",
            "text": f"{_SECRET_TRANSCRIPT} chunk {i} " + ("mot " * 40),
        }
        for i in range(240)
    ]
    return {
        "analysis_scope": "conversation_human_evidence",
        "conversation": {
            "conversation_id": "conv-1",
            "participants": ["William", "Marie"],
            "started_at": "2026-07-20T00:00:00Z",
        },
        "turns": turns,
        "episodes": [
            {
                "episode_id": "ep-1",
                "episode_type": "conversation",
                "topic": "organisation du week-end",
                "situation_summary": "un projet commun a caler",
                "trigger_summary": "un desaccord sur l'horaire",
                "outcome_summary": "compromis partiel",
                "unresolved_tension": "qui conduit",
            }
        ],
        "sensor_route_manifest": {
            "policy": "raw sensor evidence remains in Vision/WorldBrain/Silent Life",
            "sensor_episode_count": 0,
        },
    }


class _ConformingWindowLLM:
    """Fake DeepSeek that returns a schema-conforming output for any global.

    It parses the field task schema out of the rendered prompt and echoes each
    requested business field back with a minimal valid value, plus the common
    evidence / counter_evidence / confidence fields.  It also records every
    prompt it saw so the test can assert the transcript is absent and each prompt
    is under budget.
    """

    model = "fake-conforming-deepseek"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt, *, output_budget: int):
        raw = prompt.get("prompt") if isinstance(prompt, dict) else prompt
        self.prompts.append(raw if isinstance(raw, str) else json_dumps(raw))
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        schema = payload.get("schema") or {}
        data: dict = {}
        for field in schema:
            if field == "confidence":
                data[field] = 0.5
            elif field in ("evidence", "counter_evidence"):
                data[field] = []
            else:
                # Every business field is a list of objects in these contracts.
                data[field] = [{"ref": f"{field}-0"}]
        return LLMCallResult(ok=True, data=data)


def _run_global(engine: str, bundle: dict, llm: _ConformingWindowLLM, **prior_extra):
    con = _mem_con()
    prior = {"direct_dependencies": {}, **prior_extra}
    return strict._run_engine_partitioned(
        con,
        engine=engine,
        episode_id="ep-1",
        person_id="me",
        bundle=bundle,
        prior=prior,
        window_llm=llm,
    )


# ------------------------------------------------ the compact bundle itself
def test_global_engine_bundle_drops_the_transcript_and_is_tiny() -> None:
    fat = _fat_conversation_bundle()
    compact = strict._global_engine_bundle(fat)
    text = json_dumps(compact)
    # The transcript / turns are gone entirely.
    assert _SECRET_TRANSCRIPT not in text
    assert "turns" not in compact
    # It keeps the fingerprint the contracts reference.
    assert compact["participants"] == ["William", "Marie"]
    assert compact["episodes"][0]["topic"] == "organisation du week-end"
    # And it is a few dozen tokens, not 25k.
    assert estimate_tokens_for_text(text) < 512, estimate_tokens_for_text(text)


def test_raw_conversation_bundle_would_blow_the_budget() -> None:
    # Sanity: the fat bundle really is over the budget when serialised, so the
    # shrink is load-bearing and not a no-op on a small fixture.
    fat = _fat_conversation_bundle()
    assert estimate_tokens_for_text(json_dumps(fat)) > 24576


# ---------------------------- a global engine gets the fingerprint, not turns
@pytest.mark.parametrize("engine", _GLOBAL_ENGINES)
def test_global_engine_prompt_has_no_transcript_and_is_under_budget(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    fat = _fat_conversation_bundle()
    # This is what the fan-out now passes for the globals.
    compact = strict._global_engine_bundle(fat)
    llm = _ConformingWindowLLM()
    out = _run_global(engine, compact, llm)
    assert isinstance(out, dict)
    assert llm.prompts, "the engine must have issued at least one field task"
    budget = strict._pro_engine_input_budget(None)
    for prompt in llm.prompts:
        assert _SECRET_TRANSCRIPT not in prompt
        assert "turn_blbundle_deep_audio_v185" not in prompt
        assert estimate_tokens_for_text(prompt) < budget, (
            engine,
            estimate_tokens_for_text(prompt),
            budget,
        )


# -------------------- the 6 globals validate their contract with the fingerprint
@pytest.mark.parametrize("engine", _GLOBAL_ENGINES)
def test_each_global_validates_its_output_contract(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    compact = strict._global_engine_bundle(_fat_conversation_bundle())
    out = _run_global(engine, compact, _ConformingWindowLLM())
    schema = strict.ENGINE_SCHEMAS[engine]
    # Every business field of the contract is present and typed in the merged
    # output — the engine validated & merged its output from the fingerprint.
    for field in schema:
        assert field in out, (engine, field)
    assert isinstance(out["confidence"], (int, float))
    for business in schema:
        if business in ("evidence", "counter_evidence", "confidence"):
            continue
        assert isinstance(out[business], list), (engine, business)


# -------------------------- similar_case's minimal prior also stays transcript-free
def test_similar_case_prior_from_compact_bundle_is_under_budget() -> None:
    con = _mem_con()
    compact = strict._global_engine_bundle(_fat_conversation_bundle())
    pattern_output = {
        "confirmed_patterns": [
            {"pattern_type": "loop", "pattern_key": f"k{i}", "title": f"T{i}"}
            for i in range(30)
        ],
        "signals": [],
        "candidate_patterns": [],
    }
    prior = strict._similar_case_prior(
        con, person_id="me", conversation_id="conv-1",
        bundle=compact, pattern_output=pattern_output,
    )
    text = json_dumps(prior)
    assert _SECRET_TRANSCRIPT not in text
    assert "facts" not in prior
    assert prior["episode_fingerprint"]["participants"] == ["William", "Marie"]
    assert estimate_tokens_for_text(text) < 24576


# --------------------------- the PER-EPISODE bundle keeps its transcript intact
def test_per_episode_bundle_still_carries_its_turns() -> None:
    # The compact shrink is applied ONLY to the globals; the per-episode engines
    # analyse the episode content, so their bundle keeps its turns.  Prove the
    # helper is a projection of the same bundle, not a mutation of it.
    fat = _fat_conversation_bundle()
    _ = strict._global_engine_bundle(fat)
    assert len(fat["turns"]) == 240
    assert fat["turns"][0]["text"].startswith(_SECRET_TRANSCRIPT)
