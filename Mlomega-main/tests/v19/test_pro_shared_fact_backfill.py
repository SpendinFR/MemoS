"""PRO shared-fact backfill: DeepSeek (no-think) omits empty LIST-typed schema
keys that the local 9B always emits.  In PRO (``MLOMEGA_PRO_CLOSEDAY``) those
missing list keys are backfilled with ``[]`` at the SINGLE validation chokepoint
(``record_engine_output``), so the tolerance applies uniformly to EVERY engine —
never patched engine by engine.  The local path keeps the strict hard raise
byte-for-byte, and a missing NON-list key still raises even in PRO.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _fixture_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "shared-facts-backfill.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_E64_SHARED_FACTS", "1")

    from mlomega_audio_elite.brain2_conversation_episode import (
        CONVERSATION_EPISODE_BUILD_VERSION,
    )
    from mlomega_audio_elite.brain2_strict_v13_2 import ensure_strict_v13_schema
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.utils import now_iso

    ensure_strict_v13_schema()
    now = now_iso()
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO conversations(
                   conversation_id,title,started_at,channel,participants_json,
                   speaker_map_json,relationship_context_json,raw_json,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("conv-bf", "fixture", now, "phoneonly", "[]", "{}", "{}", "{}", now),
        )
        con.execute(
            """INSERT INTO turns(
                   turn_id,conversation_id,idx,speaker_label,person_id,start_s,end_s,
                   text,previous_turn_id,metadata_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "t1", "conv-bf", 0, "SPEAKER_00", "UNKNOWN_VOICE_1", 0.0, 1.0,
                "J'ai rendez-vous demain.", None, "{}",
            ),
        )
        con.execute(
            """INSERT INTO episodes(
                   episode_id,episode_type,start_time,source_conversation_id,
                   start_turn_id,end_turn_id,participants_json,channel,topic,
                   situation_summary,confidence,truth_status,importance_score,
                   lifecycle_status,metadata_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "ep-bf", "conversation", now, "conv-bf", "t1", "t1",
                '["UNKNOWN_VOICE_1"]', "phoneonly", "rendez-vous",
                "Une conversation avec un projet de rendez-vous.", 0.8, "inferred",
                0.8, "active", json.dumps({
                    "episode_source": CONVERSATION_EPISODE_BUILD_VERSION,
                    "coverage_status": "complete",
                    "subtheme_types": ["planning"],
                }), now, now,
            ),
        )
        con.commit()
    return db_path


# The exact real-world failure: contradiction_engine emitted a terse output that
# omitted its two empty findings-lists.  Both are LIST-typed in the schema.
_TERSE_CONTRADICTION = {
    "confidence": 0.5,
    "counter_evidence": [],
    "evidence": ["t1"],
    # 'contradictions' and 'model_revisions_needed' intentionally OMITTED
}


def test_pro_backfills_missing_empty_list_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    schema = ENGINE_SCHEMAS["contradiction_engine"]
    missing = set(schema) - set(_TERSE_CONTRADICTION)
    assert missing == {"contradictions", "model_revisions_needed"}, missing

    with connect(db_path) as con:
        rebuilt = record_engine_output(
            con, person_id="me", conversation_id="conv-bf", episode_id="ep-bf",
            engine_name="contradiction_engine", output=dict(_TERSE_CONTRADICTION),
            schema=schema, applicability_reason="episode_has_contradiction_surface",
        )
        con.commit()
    # Lossless: the omitted findings-lists become [] (no items), nothing invented.
    assert rebuilt["contradictions"] == []
    assert rebuilt["model_revisions_needed"] == []
    # The keys the engine DID emit are untouched.
    assert rebuilt["confidence"] == 0.5
    assert rebuilt["evidence"] == ["t1"]


def test_pro_backfill_is_generic_across_engines(tmp_path, monkeypatch):
    """Same single chokepoint tolerates ANY engine's missing empty list keys."""
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    checked = 0
    with connect(db_path) as con:
        for engine_name, schema in ENGINE_SCHEMAS.items():
            list_keys = [k for k, v in schema.items() if isinstance(v, list)]
            if not list_keys:
                continue
            # Emit every non-list key with a valid value; drop ONE list key.
            dropped = list_keys[0]
            output = {}
            for k, v in schema.items():
                if k == dropped:
                    continue
                if isinstance(v, list):
                    output[k] = []
                elif isinstance(v, float):
                    output[k] = 0.5
                elif isinstance(v, bool):
                    output[k] = False
                elif isinstance(v, int):
                    output[k] = 0
                elif isinstance(v, dict):
                    output[k] = dict(v)
                else:
                    output[k] = ""
            rebuilt = record_engine_output(
                con, person_id="me", conversation_id="conv-bf", episode_id="ep-bf",
                engine_name=engine_name, output=output, schema=schema,
                applicability_reason=f"generic_backfill_{engine_name}",
            )
            assert rebuilt[dropped] == [], (engine_name, dropped, rebuilt.get(dropped))
            checked += 1
        con.commit()
    assert checked >= 3, f"expected several engines with list fields, got {checked}"


def test_local_still_hard_raises_on_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        with pytest.raises(ValueError) as exc:
            record_engine_output(
                con, person_id="me", conversation_id="conv-bf", episode_id="ep-bf",
                engine_name="contradiction_engine", output=dict(_TERSE_CONTRADICTION),
                schema=ENGINE_SCHEMAS["contradiction_engine"],
                applicability_reason="episode_has_contradiction_surface",
            )
    msg = str(exc.value)
    assert msg.startswith("shared_fact_invalid_output:contradiction_engine:")
    assert "contradictions" in msg and "model_revisions_needed" in msg


def test_pro_still_raises_on_missing_non_list_key(tmp_path, monkeypatch):
    """A missing scalar/object key is a real structural failure — still raises."""
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    db_path = _fixture_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    schema = ENGINE_SCHEMAS["contradiction_engine"]
    # Drop the scalar 'confidence' (non-list) → must still hard-raise even in PRO.
    bad = {k: ([] if isinstance(v, list) else v) for k, v in schema.items()}
    bad.pop("confidence")
    with connect(db_path) as con:
        with pytest.raises(ValueError) as exc:
            record_engine_output(
                con, person_id="me", conversation_id="conv-bf", episode_id="ep-bf",
                engine_name="contradiction_engine", output=bad, schema=schema,
                applicability_reason="episode_has_contradiction_surface",
            )
    assert "confidence" in str(exc.value)
