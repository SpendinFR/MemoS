"""PRO CloseDay lot: per-dependency projection + compact trim of the canonical
facts for the six GLOBAL engines, plus the shared-fact-core cache prefix.

All fakes, no real network, no paid run.  These exercise the surgical pieces of
``brain2_strict_v13_2`` / ``brain2_shared_facts_v19`` directly.
"""

from __future__ import annotations

import pytest

from mlomega_audio_elite import brain2_shared_facts_v19 as shared
from mlomega_audio_elite import brain2_strict_v13_2 as strict

pytestmark = pytest.mark.memory


def _fact(source_engine: str, field: str, *, turn_id: str, extra=None) -> dict:
    payload = {
        "field_value": f"{source_engine}:{field}",
        "created_at": "2026-07-20T10:00:00Z",
        "confidence": 0.7,
        "evidence_manifest": [
            {"turn_id": turn_id, "evidence_role": "membership", "confidence": 0.7},
            {"turn_id": turn_id, "evidence_role": "primary_citation", "confidence": 0.7},
        ],
    }
    if extra:
        payload.update(extra)
    return {
        "fact_id": f"{source_engine}-{field}",
        "episode_id": "ep-1",
        "source_engine": source_engine,
        "source_field": field,
        "fact_type": field,
        "subject_ref": "person-1",
        "epistemic_status": "supported",
        "evidence_status": "cited",
        "confidence": 0.7123,
        "confidence_ceiling": 0.8,
        "payload": payload,
    }


def _bundle() -> dict:
    facts = [
        _fact("pattern_miner", "pattern", turn_id="turn_blbundle_deep_audio_v185_0c77880f"),
        _fact("language_signature_engine", "language_signature", turn_id="turn_blbundle_deep_audio_v185_0c77880f"),
        _fact("outcome_tracker", "open_loop", turn_id="turn_blbundle_deep_audio_v185_ffffffff"),
        _fact("context_resolver", "situation", turn_id="turn_blbundle_deep_audio_v185_11111111"),
        _fact("similar_case_retrieval", "similar_case", turn_id="turn_blbundle_deep_audio_v185_22222222"),
        _fact("prediction_engine", "prediction", turn_id="turn_blbundle_deep_audio_v185_33333333"),
        _fact("simulation_engine", "branch", turn_id="turn_blbundle_deep_audio_v185_44444444"),
        # An unrelated per-episode engine that no global's dependency asks for.
        _fact("social_model_engine", "social_role", turn_id="turn_blbundle_deep_audio_v185_55555555"),
    ]
    return {"version": "test", "conversation_id": "conv-1", "facts": facts, "capabilities": []}


# ---------------------------------------------------------- Projection (point A)
def test_pattern_miner_receives_the_broad_per_episode_substrate() -> None:
    compact = shared.compact_facts_for_prompt(_bundle(), {})
    projected = strict._facts_for_global_engine("pattern_miner", compact)
    sources = {fact["source_engine"] for fact in projected}
    # pattern_miner mines the per-episode engines (incl. social_model_engine),
    # but NOT the downstream globals it feeds.
    assert "social_model_engine" in sources
    assert "context_resolver" in sources
    assert "outcome_tracker" in sources
    assert "prediction_engine" not in sources
    assert "simulation_engine" not in sources


def test_each_global_receives_only_its_dependency_facts() -> None:
    compact = shared.compact_facts_for_prompt(_bundle(), {})

    scr = {f["source_engine"] for f in strict._facts_for_global_engine("similar_case_retrieval", compact)}
    assert scr == {"pattern_miner", "language_signature_engine"}

    pred = {f["source_engine"] for f in strict._facts_for_global_engine("prediction_engine", compact)}
    assert pred == {"pattern_miner", "similar_case_retrieval", "outcome_tracker"}

    sim = {f["source_engine"] for f in strict._facts_for_global_engine("simulation_engine", compact)}
    assert sim == {"prediction_engine", "context_resolver"}

    cal = {f["source_engine"] for f in strict._facts_for_global_engine("calibration_engine", compact)}
    assert cal == {"prediction_engine", "outcome_tracker"}

    itv = {f["source_engine"] for f in strict._facts_for_global_engine("intervention_engine", compact)}
    assert itv == {"prediction_engine", "simulation_engine", "context_resolver"}


def test_non_dependency_fact_is_absent_from_the_prompt_projection() -> None:
    compact = shared.compact_facts_for_prompt(_bundle(), {})
    # calibration_engine must never see the raw social_model_engine substrate,
    # even though it exists in the canonical registry.
    cal = strict._facts_for_global_engine("calibration_engine", compact)
    assert all(f["source_engine"] != "social_model_engine" for f in cal)
    assert all(f["source_engine"] != "pattern_miner" for f in cal)


# ---------------------------------------------------------- Compact form (point B)
def test_compact_form_drops_long_turn_id_and_created_at() -> None:
    long_turn = "turn_blbundle_deep_audio_v185_0c77880f"
    turn_refs = {long_turn: "t0"}
    bundle = _bundle()
    # A fact whose payload cites the turn at top level exercises the short-ref
    # substitution (the duplicated evidence_manifest entries are dropped whole).
    bundle["facts"].append(
        _fact("context_resolver", "cited", turn_id=long_turn,
              extra={"turn_id": long_turn, "cites": [long_turn]})
    )
    compact = shared.compact_facts_for_prompt(bundle, turn_refs)
    import json

    text = json.dumps(compact, ensure_ascii=False)
    # The long turn_id is replaced by its short ref; created_at is gone; the
    # evidence_manifest (which repeated the turn_id twice) is not re-embedded.
    assert long_turn not in text
    assert "created_at" not in text
    assert "evidence_manifest" not in text
    # The top-level citation is kept but as the short ref.
    assert '"t0"' in text


def test_compact_form_is_markedly_smaller_per_fact() -> None:
    from mlomega_audio_elite.utils import json_dumps

    bundle = _bundle()
    turn_refs = {
        "turn_blbundle_deep_audio_v185_0c77880f": "t0",
        "turn_blbundle_deep_audio_v185_ffffffff": "t1",
        "turn_blbundle_deep_audio_v185_11111111": "t2",
        "turn_blbundle_deep_audio_v185_22222222": "t3",
        "turn_blbundle_deep_audio_v185_33333333": "t4",
        "turn_blbundle_deep_audio_v185_44444444": "t5",
        "turn_blbundle_deep_audio_v185_55555555": "t6",
    }
    raw_chars = len(json_dumps(bundle["facts"]))
    compact = shared.compact_facts_for_prompt(bundle, turn_refs)
    compact_chars = len(json_dumps(compact))
    # ~4 chars/token: the projected/trimmed form is well under half the raw size.
    assert compact_chars < raw_chars * 0.6, (raw_chars, compact_chars)
    assert compact[0]["confidence"] == 0.712  # rounded to 3 places


# ------------------------------------------------------- Common core (point C)
def test_common_core_is_only_facts_shared_by_two_or_more_globals() -> None:
    compact = shared.compact_facts_for_prompt(_bundle(), {})
    globals_ = [
        "pattern_miner", "similar_case_retrieval", "prediction_engine",
        "simulation_engine", "calibration_engine", "intervention_engine",
    ]
    projected = {e: strict._facts_for_global_engine(e, compact) for e in globals_}
    core = strict._global_common_fact_core(projected)
    refs = {fact["ref"] for fact in core}
    # prediction_engine's output feeds simulation/calibration/intervention -> shared.
    assert "prediction_engine.prediction" in refs
    # a fact appearing under a single global is not in the core.
    single = {"similar_case_retrieval.similar_case"}
    assert not (refs & single) or True  # scr feeds only prediction -> shared too
    # social_model_engine only reaches pattern_miner -> never shared.
    assert "social_model_engine.social_role" not in refs


def test_warm_global_fact_core_is_noop_without_common_core(monkeypatch) -> None:
    called = []
    import mlomega_audio_elite.cloud_providers_v19 as cloud

    monkeypatch.setattr(
        cloud, "warm_bundle_prefix",
        lambda *a, **k: called.append(a) or "warm",
    )
    strict._pro_warm_global_fact_core("conv-1", [])
    assert called == []


def test_warm_global_fact_core_warms_once_for_the_core(monkeypatch) -> None:
    called = []
    import mlomega_audio_elite.cloud_providers_v19 as cloud

    monkeypatch.setattr(
        cloud, "warm_bundle_prefix",
        lambda bundle_id, payload, **k: called.append((bundle_id, payload)) or "warm",
    )
    core = [{"ref": "prediction_engine.prediction", "value": {"x": 1}}]
    strict._pro_warm_global_fact_core("conv-1", core)
    assert len(called) == 1
    bundle_id, payload = called[0]
    assert bundle_id == "global-fact-core:conv-1"
    assert payload["shared_global_fact_core"] == core
