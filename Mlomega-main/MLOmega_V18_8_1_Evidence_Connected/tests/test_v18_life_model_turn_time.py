from __future__ import annotations

"""Regression tests for V18 close-day schema bootstrap and turn timestamps.

Run without pytest:
  python tests/test_v18_life_model_turn_time.py

The test database is intentionally left in the OS temp directory on Windows.
Some V18 helpers retain SQLite connection handles until interpreter shutdown;
the database is isolated and never points at a user database.
"""

import os
from pathlib import Path
import tempfile
import unittest


class V18TurnTimeIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="mlomega-v18-turn-time-"))
        self.previous_env = {
            key: os.environ.get(key)
            for key in ("MLOMEGA_HOME", "MLOMEGA_DB", "MLOMEGA_RAW")
        }
        os.environ["MLOMEGA_HOME"] = str(root)
        os.environ["MLOMEGA_DB"] = str(root / "memory.db")
        os.environ["MLOMEGA_RAW"] = str(root / "raw")

    def tearDown(self) -> None:
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_close_day_bootstraps_post_stop_schema_on_blank_database(self) -> None:
        from mlomega_audio_elite.db import connect
        from mlomega_audio_elite.v18_close_day import ensure_close_day_schema

        ensure_close_day_schema()
        con = connect()
        try:
            row = con.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='brainlive_post_stop_deep_flow_runs_v1515'"
            ).fetchone()
        finally:
            con.close()

        self.assertIsNotNone(row)

    def test_owner_scoped_turn_query_uses_conversation_time_not_turn_created_at(self) -> None:
        from mlomega_audio_elite.brain2_life_model_v15_10 import collect_canonical_evidence
        from mlomega_audio_elite.db import connect, init_db, write_transaction
        from mlomega_audio_elite.governance_v18 import ensure_v18_schema
        from mlomega_audio_elite.integrity_v176 import parse_iso_utc

        init_db()
        ensure_v18_schema()

        person_id = "test-person"
        started_at = "2026-06-15T10:00:00+00:00"
        recorded_at = "2026-06-15T10:01:00+00:00"

        con = connect()
        try:
            with write_transaction(con):
                columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(turns)")}
                self.assertNotIn("created_at", columns)

                con.execute(
                    "INSERT INTO conversations(conversation_id,started_at,created_at) VALUES(?,?,?)",
                    ("conversation-in-scope", started_at, started_at),
                )
                con.execute(
                    "INSERT INTO turns(turn_id,conversation_id,idx,start_s,end_s,text,metadata_json) "
                    "VALUES(?,?,?,?,?,?,?)",
                    ("turn-in-scope", "conversation-in-scope", 1, 30.0, 34.0, "Bonjour", "{}"),
                )
                con.execute(
                    "INSERT INTO v18_conversation_scopes("
                    "conversation_id,person_id,evidence_kind,evidence_json,active,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    ("conversation-in-scope", person_id, "manual", "{}", 1, recorded_at, recorded_at),
                )

                con.execute(
                    "INSERT INTO conversations(conversation_id,started_at,created_at) VALUES(?,?,?)",
                    ("conversation-other-owner", started_at, started_at),
                )
                con.execute(
                    "INSERT INTO turns(turn_id,conversation_id,idx,start_s,end_s,text,metadata_json) "
                    "VALUES(?,?,?,?,?,?,?)",
                    ("turn-other-owner", "conversation-other-owner", 2, 45.0, 50.0, "Privé", "{}"),
                )
        finally:
            con.close()

        feed = collect_canonical_evidence(
            person_id,
            period_start="2026-06-15T10:00:00+00:00",
            period_end="2026-06-15T10:05:00+00:00",
            limit=20,
        )
        turns = feed["language"]["turns_recent"]

        self.assertEqual([row["turn_id"] for row in turns], ["turn-in-scope"])
        self.assertEqual(
            parse_iso_utc(str(turns[0]["occurred_at"])),
            parse_iso_utc("2026-06-15T10:00:30+00:00"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
