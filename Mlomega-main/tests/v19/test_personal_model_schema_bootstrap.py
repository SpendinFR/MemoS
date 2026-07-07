from __future__ import annotations


def test_v18_personal_model_builder_bootstraps_its_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))

    from mlomega_audio_elite.brainlive_personal_model_v15_9 import (
        build_brain2_live_personal_model,
    )
    from mlomega_audio_elite.db import connect

    result = build_brain2_live_personal_model("empty-person", use_llm=False)
    assert result["status"] == "raw_only_llm_disabled"
    with connect() as con:
        row = con.execute(
            "SELECT status FROM brainlive_personal_model_exports WHERE export_id=?",
            (result["export_id"],),
        ).fetchone()
    assert row is not None
