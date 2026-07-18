from __future__ import annotations

import sqlite3

from mlomega_audio_elite.owner_context_v19 import build_owner_context, perspective_role


def _schema(con):
    con.executescript("""
    CREATE TABLE self_voice_profile(
      person_id TEXT PRIMARY KEY, display_name TEXT, is_user INTEGER,
      setup_status TEXT, created_at TEXT, updated_at TEXT);
    CREATE TABLE speaker_profiles(
      person_id TEXT PRIMARY KEY, display_name TEXT, is_user INTEGER,
      aliases_json TEXT, notes TEXT, created_at TEXT);
    CREATE TABLE voice_clusters(
      cluster_id TEXT PRIMARY KEY, canonical_person_id TEXT);
    """)


def test_unknown_voice_is_not_promoted_without_owner_profile():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    _schema(con)
    context = build_owner_context(con, "me")
    assert context["voice_identity_status"] == "not_enrolled"
    assert perspective_role("UNKNOWN_VOICE_001", context) == "unknown"
    assert perspective_role("person_max", context) == "other"


def test_canonical_profile_supplies_name_and_multiple_owner_clusters():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute("INSERT INTO self_voice_profile VALUES('me','William',1,'quality_fixture','n','n')")
    con.execute("INSERT INTO speaker_profiles VALUES('me','William',1,'[\"Will\"]',NULL,'n')")
    con.execute("INSERT INTO voice_clusters VALUES('voice-a','me')")
    con.execute("INSERT INTO voice_clusters VALUES('voice-b','me')")
    context = build_owner_context(con, "me")
    assert context["display_name"] == "William"
    assert context["voice_cluster_ids"] == ["voice-a", "voice-b"]
    assert perspective_role("voice-a", context) == "owner"
    assert perspective_role("Will", context) == "owner"
    assert perspective_role("Sarah", context) == "other"
