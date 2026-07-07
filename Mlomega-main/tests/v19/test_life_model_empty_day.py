from __future__ import annotations


def test_canonical_life_model_abstains_without_owner_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))

    from mlomega_audio_elite import brain2_life_model_v15_10 as life_model

    monkeypatch.setattr(
        life_model,
        "collect_canonical_evidence",
        lambda *args, **kwargs: {
            "person_id": "empty-person",
            "completeness": {"missing_owner_proof": True},
        },
    )

    def forbidden_llm(*args, **kwargs):
        raise AssertionError("LLM must not run without owner-scoped evidence")

    monkeypatch.setattr(life_model, "synthesize_canonical_life_model", forbidden_llm)
    result = life_model.build_brain2_canonical_life_model("empty-person", use_llm=True)

    assert result["status"] == "abstained_no_owner_evidence"
    assert result["canonical_model"] == {"abstained": True, "reason": "missing_owner_proof"}
