from __future__ import annotations

import sqlite3

from mlomega_audio_elite.prediction_policy_v19 import durable_prediction_allowed


def _database() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        """CREATE TABLE prediction_cases(
             case_id TEXT PRIMARY KEY, episode_id TEXT, person_id TEXT,
             usable_for_prediction INTEGER
           )"""
    )
    con.executemany(
        "INSERT INTO prediction_cases VALUES(?,?,?,?)",
        [
            ("case-good", "episode-good", "me", 1),
            ("case-unusable", "episode-unusable", "me", 0),
            ("case-other", "episode-other", "other", 1),
        ],
    )
    return con


def test_high_confidence_without_precedent_is_not_durable():
    con = _database()
    assert not durable_prediction_allowed(
        con, {"confidence": 0.99, "why": ["plausible"]}, person_id="me",
    )


def test_only_existing_usable_owner_precedent_is_durable():
    con = _database()
    assert durable_prediction_allowed(
        con, {"similar_cases": [{"case_id": "case-good"}]}, person_id="me",
    )
    assert durable_prediction_allowed(
        con, {"similar_cases": [{"episode_id": "episode-good"}]}, person_id="me",
    )
    assert not durable_prediction_allowed(
        con, {"similar_cases": [{"case_id": "case-unusable"}]}, person_id="me",
    )
    assert not durable_prediction_allowed(
        con, {"similar_cases": [{"case_id": "case-other"}]}, person_id="me",
    )
