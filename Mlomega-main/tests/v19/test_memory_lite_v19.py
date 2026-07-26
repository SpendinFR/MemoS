from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mlomega_audio_elite.brainlive_v15 import BRAINLIVE_SCHEMA
from mlomega_audio_elite.db import connect, init_db
from mlomega_audio_elite.memory_lite_v19 import run_memory_lite_close_day
from mlomega_audio_elite.utils import json_dumps


def _seed(db):
    init_db(db)
    start = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)
    with connect(db) as con:
        con.executescript(BRAINLIVE_SCHEMA)
        con.execute(
            """INSERT INTO speaker_profiles(
                 person_id,display_name,is_user,aliases_json,notes,created_at)
               VALUES('me','William',1,'[]',NULL,?)""",
            (start.isoformat(),),
        )
        con.execute(
            """INSERT INTO brainlive_sessions(
                 live_session_id,person_id,started_at,ended_at,status,session_title,
                 active_location_hint,active_people_json,active_conversation_id,
                 current_mode,h0_goal,h1_goal,h2_goal,metadata_json,created_at,updated_at)
               VALUES('lite-session','me',?,?,'ended','test','cuisine',
                      '["maxime"]',NULL,'conversation',NULL,NULL,NULL,'{}',?,?)""",
            (
                start.isoformat(),
                (start + timedelta(minutes=2)).isoformat(),
                start.isoformat(),
                start.isoformat(),
            ),
        )
        rows = [
            ("t1", "me", "William", "Je vais préparer un café.", 0),
            ("t2", "maxime", "Maxime", "Prends la baguette, elle coûte 1,20 euro.", 20),
            ("t3", "me", "William", "D'accord, je la prendrai cet après-midi.", 40),
            ("t4", "maxime", "Maxime", "On se retrouve ensuite.", 60),
        ]
        for index, (turn_id, person_id, label, text, offset) in enumerate(rows):
            at = start + timedelta(seconds=offset)
            con.execute(
                """INSERT INTO brainlive_turn_buffer(
                     live_turn_id,live_session_id,conversation_id,timestamp_start,
                     timestamp_end,speaker_label,speaker_person_id,speaker_confidence,
                     text_partial,text_final,asr_confidence,is_final,metadata_json,created_at)
                   VALUES(?,'lite-session','live-conversation',?,?,?,?,0.95,NULL,?,
                          0.92,1,'{}',?)""",
                (
                    turn_id,
                    at.isoformat(),
                    (at + timedelta(seconds=3)).isoformat(),
                    label,
                    person_id,
                    text,
                    at.isoformat(),
                ),
            )
        con.execute(
            """CREATE TABLE live_action_candidates_v19(
                 action_event_id TEXT PRIMARY KEY,person_id TEXT,live_session_id TEXT,
                 action_type TEXT,subject_track_id TEXT,subject_label TEXT,
                 object_track_id TEXT,object_label TEXT,started_at TEXT,ended_at TEXT,
                 confidence REAL,truth_level TEXT,status TEXT,model TEXT,
                 source_frame_ids_json TEXT,evidence_refs_json TEXT,detail_json TEXT,
                 created_at TEXT)"""
        )
        con.execute(
            """INSERT INTO live_action_candidates_v19 VALUES(
                 'action-1','me','lite-session','place',NULL,'William',NULL,'tasse',
                 ?,?,0.72,'probable','candidate','temporal','[]','[]','{}',?)""",
            (
                (start + timedelta(seconds=8)).isoformat(),
                (start + timedelta(seconds=12)).isoformat(),
                start.isoformat(),
            ),
        )
        con.execute(
            """CREATE TABLE world_text_observations_v19(
                 text_observation_id TEXT PRIMARY KEY,person_id TEXT,live_session_id TEXT,
                 observed_at TEXT,place_key TEXT,category TEXT,text TEXT,
                 normalized_text TEXT,comparison_key TEXT,numeric_value REAL,
                 currency TEXT,source TEXT,source_frame_id TEXT,target_track_id TEXT,
                 latitude REAL,longitude REAL,location_accuracy_m REAL,confidence REAL,
                 truth_level TEXT,evidence_refs_json TEXT,detail_json TEXT)"""
        )
        con.execute(
            """INSERT INTO world_text_observations_v19 VALUES(
                 'ocr-1','me','lite-session',?,'boulangerie','menu_price',
                 'Baguette 1,20 EUR','baguette 1 20 eur','baguette',1.2,'EUR',
                 'ocr','frame-1',NULL,NULL,NULL,NULL,0.91,'observed','[]','{}')""",
            ((start + timedelta(seconds=25)).isoformat(),),
        )
        con.execute(
            """INSERT INTO brainlive_world_states(
                 world_state_id,live_session_id,person_id,state_time,where_am_i,
                 who_is_active_json,what_is_happening,probable_activity_json,
                 active_emotional_state,active_mode,audio_context_json,
                 visual_context_json,evidence_json,counter_evidence_json,
                 confidence,created_at)
               VALUES('world-1','lite-session','me',?,'cuisine','[]',
                      'William prépare un café','[]',NULL,'home','{}','{}','[]','[]',
                      0.84,?)""",
            (
                (start + timedelta(seconds=10)).isoformat(),
                start.isoformat(),
            ),
        )
        con.commit()


class _Analysis:
    def __init__(self):
        self.calls = 0

    def __call__(self, payload, **_kwargs):
        self.calls += 1
        refs = [item["ref"] for item in payload["turns"]]
        extra = [item["ref"] for item in payload["additional_evidence"]]
        return {
            "episode": {
                "title": "Café et course",
                "topic": "organisation",
                "summary": "William prépare un café puis accepte d'acheter la baguette.",
                "outcome": "Achat prévu cet après-midi.",
                "unresolved": "",
                "confidence": 0.88,
            },
            "subthemes": [
                {
                    "title": "Baguette",
                    "summary": "Maxime indique le prix et William accepte.",
                    "turn_ids": ["t2", "t3"],
                    "confidence": 0.9,
                }
            ],
            "owner_memories": [
                {
                    "kind": "goal",
                    "statement": "William prévoit d'acheter une baguette cet après-midi.",
                    "confidence": 0.9,
                    "status": "observed",
                    "evidence_refs": refs[1:3],
                    "activation_contexts": ["cet après-midi"],
                    "live_use": "rappeler si William passe près d'une boulangerie",
                },
                {
                    "kind": "fact",
                    "statement": "La baguette observée coûte 1,20 EUR.",
                    "confidence": 0.91,
                    "status": "observed",
                    "evidence_refs": [ref for ref in extra if ref.startswith("world_text")],
                    "activation_contexts": ["boulangerie"],
                    "live_use": "répondre aux questions de prix",
                },
                {
                    "kind": "place",
                    "statement": "William était dans la cuisine pendant la préparation du café.",
                    "confidence": 0.84,
                    "status": "observed",
                    "evidence_refs": [ref for ref in extra if ref.startswith("brainlive_world_states")],
                    "activation_contexts": ["cuisine"],
                    "live_use": "répondre aux questions de lieu",
                },
            ],
            "relationships": [
                {
                    "other_person_id": "maxime",
                    "summary": "Maxime et William coordonnent une course.",
                    "owner_response": "William accepte.",
                    "other_response": "Maxime propose le rendez-vous.",
                    "recurring_topics": ["organisation"],
                    "confidence": 0.82,
                    "evidence_refs": refs[1:],
                }
            ],
            "live_hooks": [
                {
                    "kind": "suggestion",
                    "summary": "Achat de baguette encore ouvert.",
                    "activation_contexts": ["proximité boulangerie", "cet après-midi"],
                    "recommended_action": "rappel bref si pertinent",
                    "confidence": 0.8,
                    "evidence_refs": refs[1:3],
                }
            ],
        }


def test_lite_is_lossless_owner_centred_and_resume_safe(tmp_path):
    db = tmp_path / "memory.db"
    _seed(db)
    analysis = _Analysis()

    result = run_memory_lite_close_day(
        person_id="me",
        live_session_id="lite-session",
        package_date="2026-07-26",
        db_path=db,
        analyse=analysis,
    )

    assert result["status"] == "completed"
    assert result["memory_profile"] == "lite"
    assert result["calls"] == 1
    assert analysis.calls == 1
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM brainlive_turn_buffer").fetchone()[0] == 4
        assert con.execute(
            "SELECT COUNT(*) FROM turns WHERE conversation_id LIKE 'memory_lite_conversation_%'"
        ).fetchone()[0] == 4
        assert con.execute(
            "SELECT COUNT(*) FROM episodes WHERE episode_type='memory_lite_owner_episode'"
        ).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM memory_lite_facts_v19").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM relationship_models").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM interaction_episodes").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM life_model_entries_v19 WHERE source_table='memory_lite_facts_v19'"
        ).fetchone()[0] == 3
        export = con.execute(
            "SELECT status,live_ready_json FROM brainlive_personal_model_exports"
        ).fetchone()
        assert export["status"] == "lite_ready"
        assert "Achat de baguette encore ouvert" in export["live_ready_json"]
        assert con.execute(
            "SELECT COUNT(*) FROM brainlive_live_relevance_index"
        ).fetchone()[0] >= 3

    resumed = run_memory_lite_close_day(
        person_id="me",
        live_session_id="lite-session",
        package_date="2026-07-26",
        db_path=db,
        analyse=analysis,
    )
    assert resumed["resumed_close_day"] is True
    assert analysis.calls == 1


def test_lite_discards_uncited_claims_and_keeps_probable_t1_as_evidence(tmp_path):
    db = tmp_path / "memory.db"
    _seed(db)

    def analyse(payload, **_kwargs):
        action_ref = next(
            item["ref"]
            for item in payload["additional_evidence"]
            if item["ref"].startswith("live_action_candidates")
        )
        return {
            "episode": {
                "title": "Action",
                "topic": "café",
                "summary": "Une action probable est visible.",
                "outcome": "",
                "unresolved": "",
                "confidence": 0.6,
            },
            "subthemes": [],
            "owner_memories": [
                {
                    "kind": "routine",
                    "statement": "William prépare toujours un café.",
                    "confidence": 0.9,
                    "status": "observed",
                    "evidence_refs": [action_ref],
                    "activation_contexts": [],
                    "live_use": "",
                },
                {
                    "kind": "identity",
                    "statement": "Hallucination sans preuve.",
                    "confidence": 1.0,
                    "status": "observed",
                    "evidence_refs": ["fake:missing"],
                    "activation_contexts": [],
                    "live_use": "",
                },
            ],
            "relationships": [],
            "live_hooks": [],
        }

    run_memory_lite_close_day(
        person_id="me",
        live_session_id="lite-session",
        package_date="2026-07-26",
        db_path=db,
        analyse=analyse,
    )
    with connect(db) as con:
        rows = con.execute(
            "SELECT statement,status,evidence_refs_json FROM memory_lite_facts_v19"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "watch"
    assert "live_action_candidates_v19:action-1" in rows[0]["evidence_refs_json"]


def test_lite_promotes_repeated_pattern_without_duplicate_life_rows(tmp_path):
    db = tmp_path / "memory.db"
    _seed(db)

    def routine(payload, **_kwargs):
        ref = payload["turns"][0]["ref"]
        return {
            "episode": {
                "title": "Café",
                "topic": "routine",
                "summary": "William parle de préparer un café.",
                "outcome": "",
                "unresolved": "",
                "confidence": 0.8,
            },
            "subthemes": [],
            "owner_memories": [
                {
                    "kind": "routine",
                    "statement": "William prépare un café le matin.",
                    "confidence": 0.78,
                    "status": "observed",
                    "evidence_refs": [ref],
                    "activation_contexts": ["matin"],
                    "live_use": "anticiper la préparation du café",
                }
            ],
            "relationships": [],
            "live_hooks": [],
        }

    run_memory_lite_close_day(
        person_id="me", live_session_id="lite-session",
        package_date="2026-07-26", db_path=db, analyse=routine,
    )
    next_day = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    with connect(db) as con:
        con.execute(
            """INSERT INTO brainlive_sessions(
                 live_session_id,person_id,started_at,ended_at,status,session_title,
                 active_location_hint,active_people_json,active_conversation_id,
                 current_mode,h0_goal,h1_goal,h2_goal,metadata_json,created_at,updated_at)
               VALUES('lite-session-2','me',?,?,'ended','test-2','cuisine',
                      '[]',NULL,'conversation',NULL,NULL,NULL,'{}',?,?)""",
            (
                next_day.isoformat(),
                (next_day + timedelta(minutes=1)).isoformat(),
                next_day.isoformat(),
                next_day.isoformat(),
            ),
        )
        con.execute(
            """INSERT INTO brainlive_turn_buffer(
                 live_turn_id,live_session_id,conversation_id,timestamp_start,
                 timestamp_end,speaker_label,speaker_person_id,speaker_confidence,
                 text_partial,text_final,asr_confidence,is_final,metadata_json,created_at)
               VALUES('day2-turn','lite-session-2','day2-conversation',?,?,
                      'William','me',0.98,NULL,'Je prépare mon café.',0.96,1,'{}',?)""",
            (
                next_day.isoformat(),
                (next_day + timedelta(seconds=3)).isoformat(),
                next_day.isoformat(),
            ),
        )
        con.commit()
    run_memory_lite_close_day(
        person_id="me", live_session_id="lite-session-2",
        package_date="2026-07-27", db_path=db, analyse=routine,
    )

    with connect(db) as con:
        rows = con.execute(
            """SELECT status,evidence_refs_json FROM life_model_entries_v19
               WHERE statement='William prépare un café le matin.'"""
        ).fetchall()
        latest = con.execute(
            """SELECT live_ready_json FROM brainlive_personal_model_exports
               WHERE live_session_id='lite-session-2'"""
        ).fetchone()
    assert len(rows) == 1
    assert rows[0]["status"] == "confirmed"
    assert "brainlive_turn_buffer:t1" in rows[0]["evidence_refs_json"]
    assert "brainlive_turn_buffer:day2-turn" in rows[0]["evidence_refs_json"]
    assert "William prépare un café le matin." in latest["live_ready_json"]
