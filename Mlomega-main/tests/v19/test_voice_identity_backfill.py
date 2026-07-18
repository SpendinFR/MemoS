from __future__ import annotations

import json


def _cluster(con, cluster_id: str) -> None:
    con.execute(
        """INSERT INTO voice_clusters(
             cluster_id,canonical_person_id,display_label,status,first_seen_at,last_seen_at,
             observation_count,total_duration_s,often_with_user_count,prompt_status,
             centroid_embedding_json,model,confidence,created_at,updated_at
           ) VALUES(?,NULL,?,'unknown','2026-07-01','2026-07-18',3,30,0,'not_needed',
                    '[1.0,0.0]','test',0.8,'2026-07-01','2026-07-18')""",
        (cluster_id, cluster_id),
    )


def test_multiple_unknown_clusters_converge_to_one_person(monkeypatch, tmp_path):
    db = tmp_path / "voice-backfill.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))

    from mlomega_audio_elite.db import connect, init_db
    from mlomega_audio_elite.voice_learning import (
        ensure_voice_learning_schema, name_unknown_voice,
    )

    init_db()
    ensure_voice_learning_schema()
    with connect() as con:
        _cluster(con, "UNKNOWN_VOICE_002")
        _cluster(con, "UNKNOWN_VOICE_003")
        con.execute(
            """CREATE TABLE IF NOT EXISTS brain2_shared_facts_v19(
                 fact_id TEXT PRIMARY KEY, subject_ref TEXT
               )"""
        )
        con.executemany(
            "INSERT INTO brain2_shared_facts_v19 VALUES(?,?)",
            [("f2", "UNKNOWN_VOICE_002"), ("f3", "UNKNOWN_VOICE_003")],
        )
        con.executemany(
            """INSERT INTO predictions(
                 prediction_id,created_at,person_id,prediction_target,horizon,current_context,
                 predicted_value,updated_at
               ) VALUES(?,'2026-07-18',?,'next_action','next','ctx','value','2026-07-18')""",
            [("p2", "UNKNOWN_VOICE_002"), ("p3", "UNKNOWN_VOICE_003")],
        )
        con.commit()

    first = name_unknown_voice("UNKNOWN_VOICE_002", "person_maxime", display_name="Maxime")
    second = name_unknown_voice("UNKNOWN_VOICE_003", "person_maxime", display_name="Maxime")

    with connect() as con:
        assert {
            row[0] for row in con.execute("SELECT DISTINCT subject_ref FROM brain2_shared_facts_v19")
        } == {"person_maxime"}
        assert {
            row[0] for row in con.execute("SELECT DISTINCT person_id FROM predictions")
        } == {"person_maxime"}
        assert con.execute(
            "SELECT COUNT(*) FROM voice_embeddings WHERE person_id='person_maxime'"
        ).fetchone()[0] == 2
        revisions = [
            json.loads(row[0]) for row in con.execute(
                "SELECT rows_updated_json FROM voice_identity_revisions ORDER BY created_at"
            )
        ]
    assert first["person_id"] == second["person_id"] == "person_maxime"
    assert sum(item["brain2_shared_facts_v19.subject_ref"] for item in revisions) == 2
    assert sum(item["predictions.person_id"] for item in revisions) == 2
