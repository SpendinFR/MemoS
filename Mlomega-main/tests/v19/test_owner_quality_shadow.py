from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _db(path: Path) -> Path:
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE brain2_shared_facts_v19(
              fact_id TEXT PRIMARY KEY, person_id TEXT, conversation_id TEXT,
              episode_id TEXT, source_engine TEXT, source_field TEXT,
              fact_type TEXT, subject_ref TEXT, epistemic_status TEXT,
              evidence_status TEXT, confidence REAL, confidence_ceiling REAL,
              payload_json TEXT, payload_digest TEXT
            );
            CREATE TABLE brain2_shared_fact_evidence_v19(
              fact_id TEXT, turn_id TEXT
            );
            CREATE TABLE predictions_v19(
              prediction_id TEXT PRIMARY KEY, person_id TEXT, statement TEXT,
              confidence REAL, evidence_refs_json TEXT,
              verification_spec_json TEXT
            );
            """
        )
        for fact_id, confidence, payload in (
            ("f1", 0.9, '{"statement":"William aime le café"}'),
            ("f2", 0.8, '{"statement":"William aime le café"}'),
            ("f3", 0.7, '{"statement":"William évite le café"}'),
        ):
            con.execute(
                """INSERT INTO brain2_shared_facts_v19 VALUES(
                   ?,'me','c1','e1','pattern_miner','preference','preference',
                   'me','inferred','cited',?,0.5,?,?)""",
                (fact_id, confidence, payload, hashlib.sha256(payload.encode()).hexdigest()),
            )
        con.execute(
            "INSERT INTO brain2_shared_fact_evidence_v19 VALUES('f1','t1')"
        )
        con.execute(
            """INSERT INTO predictions_v19 VALUES(
               'p1','me','William boira un café',0.6,'[]','{}')"""
        )
    return path


def test_plan_is_zero_call_read_only_and_stratified(tmp_path):
    from tools.harness.owner_quality_shadow import build_plan

    source = _db(tmp_path / "memory.db")
    before = _sha(source)
    plan = build_plan(
        source,
        owner_id="me",
        owner_name="William",
        model="deepseek-v4-pro",
        budget_eur=1.0,
        batch_size=8,
        max_candidates=20,
    )
    assert _sha(source) == before
    assert plan["mode"] == "plan_only_zero_calls"
    assert plan["source_unchanged"] is True
    assert plan["quote"]["deterministic_candidates"] >= 4
    assert plan["quote"]["estimated_cost_eur_max"] < 1.0
    assert plan["scan"]["inventory"]["vision_calls_planned"] == 0


def test_validated_apply_clamps_only_code_whitelist_and_keeps_backup(tmp_path):
    from tools.harness.owner_quality_shadow import _apply_validated_report

    source = _db(tmp_path / "memory.db")
    before = _sha(source)
    report = {
        "source_unchanged": True,
        "source_sha256_before": before,
        "plan_digest": "plan-1",
        "provider": {"model": "deepseek-v4-pro"},
        "owner": {"person_id": "me"},
        "candidates": [{
            "candidate_id": "c1",
            "kind": "confidence_above_evidence_ceiling",
            "refs": [{"table": "brain2_shared_facts_v19", "id": "f1"}],
            "evidence": {"confidence": 0.9, "confidence_ceiling": 0.5},
        }],
        "findings": [{
            "candidate_id": "c1",
            "verdict": "confirmed",
            "reason": "plafond prouvé",
            "recommended_action": "confidence_review",
            "keep_refs": [],
            "merge_refs": [],
        }],
    }
    applied = _apply_validated_report(source, tmp_path / "report.json", report)
    assert applied["canonical_updates"] == 1
    assert Path(applied["backup_db"]).is_file()
    with sqlite3.connect(applied["backup_db"]) as backup:
        assert backup.execute(
            "SELECT confidence FROM brain2_shared_facts_v19 WHERE fact_id='f1'"
        ).fetchone()[0] == 0.9
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    with sqlite3.connect(source) as con:
        assert con.execute(
            "SELECT confidence FROM brain2_shared_facts_v19 WHERE fact_id='f1'"
        ).fetchone()[0] == 0.5
        run = con.execute(
            "SELECT status,canonical_updates_count FROM owner_quality_shadow_runs_v19"
        ).fetchone()
        assert run == ("completed", 1)
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_model_cannot_target_a_row_outside_candidate():
    from tools.harness.owner_quality_shadow import _validated_actions

    report = {
        "candidates": [{
            "candidate_id": "c1",
            "kind": "exact_duplicate_canonical_fact",
            "refs": [
                {"table": "brain2_shared_facts_v19", "id": "f1"},
                {"table": "brain2_shared_facts_v19", "id": "f2"},
            ],
        }],
        "findings": [{
            "candidate_id": "c1",
            "verdict": "confirmed",
            "reason": "duplicate",
            "recommended_action": "merge_proposal",
            "keep_refs": ["brain2_shared_facts_v19:f-outside"],
            "merge_refs": [],
        }],
    }
    try:
        _validated_actions(report)
    except RuntimeError as exc:
        assert "hors candidat" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("une cible LLM hors candidat doit être refusée")
