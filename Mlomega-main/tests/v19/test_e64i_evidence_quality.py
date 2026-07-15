from __future__ import annotations

"""E64-I0.2 (OBS-29) evidence-quality confidence ceiling.

A conclusion may never exceed the quality of the real, cited audio evidence that
supports it.  These tests exercise the central policy end to end through the
shared-fact recorder (no per-engine logic, fakes only, MLOMEGA_DB monkeypatch).
"""

import json
from pathlib import Path

import pytest


def _base_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "evidence-quality.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_E64_SHARED_FACTS", "1")
    monkeypatch.setenv("MLOMEGA_E64_EVIDENCE_CEILING", "1")

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
            ("conv-eq", "fixture", now, "phoneonly", "[]", "{}", "{}", "{}", now),
        )
        con.execute(
            """INSERT INTO episodes(
                   episode_id,episode_type,start_time,source_conversation_id,
                   start_turn_id,end_turn_id,participants_json,channel,topic,
                   situation_summary,confidence,truth_status,importance_score,
                   lifecycle_status,metadata_json,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "ep-eq", "conversation", now, "conv-eq", None, None,
                '["UNKNOWN_VOICE_001"]', "phoneonly", "sujet",
                "Conversation de test.", 0.8, "inferred",
                0.8, "active", json.dumps({
                    "episode_source": CONVERSATION_EPISODE_BUILD_VERSION,
                    "coverage_status": "complete",
                }), now, now,
            ),
        )
        con.commit()
    return db_path


def _insert_turn(con, turn_id, *, person_id, text, metadata):
    con.execute(
        """INSERT INTO turns(
               turn_id,conversation_id,idx,speaker_label,person_id,start_s,end_s,
               text,previous_turn_id,metadata_json
           ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            turn_id, "conv-eq", int(turn_id[1:]) if turn_id[1:].isdigit() else 0,
            "SPEAKER_00", person_id, 0.0, 1.0, text, None, json.dumps(metadata),
        ),
    )


def _words(*scores):
    return [
        {"start": 0.1 * i, "end": 0.1 * i + 0.1, "score": s, "word": f"w{i}", "speaker": "SPEAKER_00"}
        for i, s in enumerate(scores)
    ]


def _deep_audio_meta(*, scores, decision, known_score, person_id, source_event_id,
                     language=None, text="phrase"):
    source = {
        "bundle_id": source_event_id,
        "words": _words(*scores),
        "source_event_ids": [source_event_id],
        "offline_speaker_resolution": {
            "decision": decision,
            "known_score": known_score,
            "person_id": person_id,
            "speaker_label": "SPEAKER_00",
        },
        "whisperx_metadata": {
            "original_text": text,
            "whisperx_segment": {"text": text, "words": _words(*scores)},
        },
    }
    if language is not None:
        source["language"] = language
    return {
        "kind": "deep_audio_transcript",
        "evidence_role": "deep_audio_whisperx_pyannote_speechbrain_transcript",
        "source": source,
    }


def _situation_output(*, confidence, main_person, evidence):
    return {
        "situation": {
            "situation_type": "conversation", "life_domain": "personal",
            "participants": [main_person], "main_person": main_person,
            "targets": ["sujet"], "place_explicit": None, "place_inferred": None,
            "social_context": "informal", "power_balance": "unknown",
            "stakes": "low", "constraints": [],
        },
        "resolved_references": [], "missing_context": [],
        "evidence": list(evidence), "counter_evidence": [], "confidence": confidence,
    }


def test_low_asr_cannot_produce_a_confident_active_fact(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        # Word alignment scores ~0.0: the transcript is barely grounded.
        _insert_turn(
            con, "t1", person_id="UNKNOWN_VOICE_001", text="?",
            metadata=_deep_audio_meta(
                scores=[0.0, 0.0, 0.0], decision="unknown_cluster",
                known_score=0.0, person_id="UNKNOWN_VOICE_001",
                source_event_id="ev-1",
            ),
        )
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.95, main_person="UNKNOWN_VOICE_001", evidence=["t1"]
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        row = con.execute(
            "SELECT confidence,confidence_ceiling,evidence_status "
            "FROM brain2_shared_facts_v19 WHERE fact_type='situation'"
        ).fetchone()
        con.commit()

    # The fact still exists (nothing deleted) but its ceiling is pinned to the
    # near-zero evidence quality — a 0.95 ACTIVE claim is impossible.
    assert row["confidence"] == 0.95
    assert row["confidence_ceiling"] < 0.1
    assert row["evidence_status"] == "cited"


def test_two_independent_reliable_proofs_lift_the_individual_ceiling(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        # Two reliable, enrolled-voice turns from DISTINCT audio sources.
        _insert_turn(
            con, "t1", person_id="person-x", text="oui",
            metadata=_deep_audio_meta(
                scores=[0.8, 0.82, 0.79], decision="known_person_match",
                known_score=0.85, person_id="person-x", source_event_id="ev-a",
            ),
        )
        _insert_turn(
            con, "t2", person_id="person-x", text="oui encore",
            metadata=_deep_audio_meta(
                scores=[0.78, 0.81, 0.8], decision="known_person_match",
                known_score=0.85, person_id="person-x", source_event_id="ev-b",
            ),
        )
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.95, main_person="person-x",
                evidence=["t1", "t2"],
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        two = con.execute(
            "SELECT confidence_ceiling FROM brain2_shared_facts_v19 WHERE fact_type='situation'"
        ).fetchone()["confidence_ceiling"]
        con.commit()

    # Single-proof best evidence is ~0.80 (alignment, since enrolled diarisation
    # 0.85 does not cap it) — independent corroboration from a distinct source
    # lifts the ceiling above the individual bound in a controlled, capped way.
    from mlomega_audio_elite.evidence_quality_v19 import (
        evidence_ceiling, turn_evidence_quality,
    )
    single = turn_evidence_quality(
        _deep_audio_meta(
            scores=[0.8, 0.82, 0.79], decision="known_person_match",
            known_score=0.85, person_id="person-x", source_event_id="ev-a",
        )
    )
    single["turn_id"] = "t1"
    individual = evidence_ceiling(0.95, [single])["ceiling"]
    assert two > individual
    assert two <= 0.95


def test_unenrolled_voice_never_becomes_the_owner(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        _insert_turn(
            con, "t1", person_id="UNKNOWN_VOICE_001", text="je pense que",
            metadata=_deep_audio_meta(
                scores=[0.9, 0.9, 0.9], decision="unknown_cluster",
                known_score=0.0, person_id="UNKNOWN_VOICE_001",
                source_event_id="ev-1",
            ),
        )
        # The model tries to attribute the trait to the owner ("me").
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.9, main_person="me", evidence=["t1"]
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        row = con.execute(
            "SELECT subject_ref,evidence_status,epistemic_status "
            "FROM brain2_shared_facts_v19 WHERE fact_type='situation'"
        ).fetchone()
        con.commit()

    # No positive voice resolution -> owner attribution is blocked, subject stays
    # unresolved (never silently promoted to William/owner).
    assert row["subject_ref"] is None
    assert row["evidence_status"] == "owner_attribution_blocked"
    assert row["epistemic_status"] == "unresolved_owner"


def test_enrolled_voice_keeps_the_owner_attribution(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        _insert_turn(
            con, "t1", person_id="me", text="je pense que",
            metadata=_deep_audio_meta(
                scores=[0.9, 0.9, 0.9], decision="known_person_match",
                known_score=0.88, person_id="me", source_event_id="ev-1",
            ),
        )
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.9, main_person="me", evidence=["t1"]
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        row = con.execute(
            "SELECT subject_ref,evidence_status FROM brain2_shared_facts_v19 "
            "WHERE fact_type='situation'"
        ).fetchone()
        con.commit()

    assert row["subject_ref"] == "me"
    assert row["evidence_status"] == "cited"


def test_incoherent_language_fragment_is_quarantined_and_raw_survives(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        # French baseline established by several coherent turns.
        for tid, ev in (("t1", "ev-1"), ("t2", "ev-2"), ("t3", "ev-3")):
            _insert_turn(
                con, tid, person_id="UNKNOWN_VOICE_001", text="bonjour ca va",
                metadata=_deep_audio_meta(
                    scores=[0.8, 0.8, 0.8], decision="unknown_cluster",
                    known_score=0.0, person_id="UNKNOWN_VOICE_001",
                    source_event_id=ev, language="fr",
                ),
            )
        # An isolated, low-confidence Greek fragment (noise) in a French context.
        _insert_turn(
            con, "t9", person_id="UNKNOWN_VOICE_001", text="ναι",
            metadata=_deep_audio_meta(
                scores=[0.18], decision="unknown_cluster", known_score=0.0,
                person_id="UNKNOWN_VOICE_001", source_event_id="ev-noise",
                language="el", text="ναι",
            ),
        )
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.7, main_person="UNKNOWN_VOICE_001", evidence=["t9"]
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        fact = con.execute(
            "SELECT evidence_status,epistemic_status,confidence_ceiling "
            "FROM brain2_shared_facts_v19 WHERE fact_type='situation'"
        ).fetchone()
        raw_turn = con.execute(
            "SELECT text FROM turns WHERE turn_id='t9'"
        ).fetchone()
        con.commit()

    # The fact is quarantined with an explicit cause status; the raw turn is
    # never deleted.
    assert fact["evidence_status"] == "quarantined"
    assert fact["epistemic_status"] == "quarantined_low_quality"
    assert fact["confidence_ceiling"] <= 0.49
    assert raw_turn["text"] == "ναι"


def test_raw_and_manifest_stay_complete_after_ceiling_policy(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import (
        finish_episode_fact_run, record_engine_output,
    )
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        for tid, ev in (("t1", "ev-1"), ("t2", "ev-2")):
            _insert_turn(
                con, tid, person_id="UNKNOWN_VOICE_001", text="phrase",
                metadata=_deep_audio_meta(
                    scores=[0.7, 0.7], decision="unknown_cluster",
                    known_score=0.0, person_id="UNKNOWN_VOICE_001",
                    source_event_id=ev, language="fr",
                ),
            )
        rebuilt = record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.8, main_person="UNKNOWN_VOICE_001",
                evidence=["t1", "t2"],
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        stats = finish_episode_fact_run(
            con, conversation_id="conv-eq", episode_id="ep-eq"
        )
        turn_count = con.execute(
            "SELECT COUNT(*) FROM turns WHERE conversation_id='conv-eq'"
        ).fetchone()[0]
        con.commit()

    # Lossless roundtrip preserved, every raw turn still present, and the
    # evidence links survived the quality policy.
    assert rebuilt["situation"]["main_person"] == "UNKNOWN_VOICE_001"
    assert turn_count == 2
    assert stats["facts"] >= 1


def test_legacy_rollback_flag_restores_flat_cited_ceiling(tmp_path, monkeypatch):
    db_path = _base_db(Path(tmp_path), monkeypatch)
    monkeypatch.setenv("MLOMEGA_E64_EVIDENCE_CEILING", "0")
    from mlomega_audio_elite.brain2_complete_v13 import ENGINE_SCHEMAS
    from mlomega_audio_elite.brain2_shared_facts_v19 import record_engine_output
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        _insert_turn(
            con, "t1", person_id="UNKNOWN_VOICE_001", text="?",
            metadata=_deep_audio_meta(
                scores=[0.0, 0.0], decision="unknown_cluster", known_score=0.0,
                person_id="UNKNOWN_VOICE_001", source_event_id="ev-1",
            ),
        )
        record_engine_output(
            con, person_id="me", conversation_id="conv-eq", episode_id="ep-eq",
            engine_name="context_resolver",
            output=_situation_output(
                confidence=0.95, main_person="UNKNOWN_VOICE_001", evidence=["t1"]
            ),
            schema=ENGINE_SCHEMAS["context_resolver"],
            applicability_reason="test",
        )
        row = con.execute(
            "SELECT confidence_ceiling,evidence_status FROM brain2_shared_facts_v19 "
            "WHERE fact_type='situation'"
        ).fetchone()
        con.commit()

    # Legacy path: cited -> ceiling equals confidence, no quality capping.
    assert row["confidence_ceiling"] == 0.95
    assert row["evidence_status"] == "cited"
