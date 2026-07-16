from __future__ import annotations

"""E64-I0.4 product capability manifest (OBS-38).

The close-day stage contract proves traversal, not that each required product
capability produced a product output.  These tests prove the manifest tells the
truth: a fully-validated day can still reach ``complete=1``; a Deep Vision
false-green (keyframes selected but none analysed), an audit-only/bypassed
stage, a coordination ``abstained``, and an unproven ``valid_empty`` all block;
``compiled_watch_only`` / ``compiled_no_life_delta`` remain valid successes.

No LLM is used; the durable Deep Vision run row is seeded directly.
"""

import pytest

from mlomega_audio_elite.db import connect, write_transaction
from mlomega_audio_elite.utils import now_iso


def _seed_deep_vision_run(
    db_path, *, person_id="me", package_date="2026-07-10",
    scanned=1, selected=0, readable=None, analyzed=0, status="ok", run_id="dvrun-1",
):
    from mlomega_audio_elite.brainlive_offline_deep_vision_v16_1 import (  # noqa: F401
        VERSION,  # ensures the module (and its SCHEMA install) is importable
    )
    from mlomega_audio_elite.db import init_db

    init_db()
    with connect(db_path) as con, write_transaction(con):
        con.executescript(
            """CREATE TABLE IF NOT EXISTS brainlive_deep_vision_runs_v161(
                 run_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, package_date TEXT NOT NULL,
                 model TEXT, max_keyframes_per_bundle INTEGER DEFAULT 12, scanned_bundles INTEGER DEFAULT 0,
                 selected_keyframes INTEGER DEFAULT 0, readable_keyframes INTEGER DEFAULT 0,
                 analyzed_keyframes INTEGER DEFAULT 0,
                 appended_brain2_turns INTEGER DEFAULT 0, status TEXT NOT NULL, error_text TEXT,
                 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"""
        )
        con.execute(
            """INSERT INTO brainlive_deep_vision_runs_v161(
                 run_id,person_id,package_date,model,scanned_bundles,selected_keyframes,
                 readable_keyframes,analyzed_keyframes,status,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, person_id, package_date, "moondream", scanned, selected,
             selected if readable is None else readable, analyzed, status, now_iso(), now_iso()),
        )


def _all_validated_results():
    """A day where every capability produced (or is proven-empty for) a product output."""
    return {
        "post_stop": {
            "status": "completed",
            "assembly": {"bundles": 1, "raw_rows": 5, "incomplete": False},
            "v18_deep_audio": {"status": "ok"},
            "v16_deep_vision": {"status": "ok"},
            "brain2_processed": [{"conversation_id": "c1", "status": "ok"}],
        },
        "visual_consolidation": {"status": "completed", "summary_id": "s1"},
        "longitudinal": {"status": "completed"},
        "coordination": {"status": "ok", "package": {"status": "llm_ready"}, "bindings": {"status": "compiled_ready"}, "reconciliation": {"status": "no_candidates"}},
        "life_model": {"status": "llm_patch_ready"},
        "outcome_resolution": {"status": "completed", "outcome_ids": []},
        "life_model_v19": {"status": "completed", "confirmed": [], "contradicted": [], "weakened": []},
        "prediction_emission": {"status": "completed", "prediction_ids": []},
        "self_schema": {"status": "completed", "schema_entry_ids": []},
        "live_ready": {"status": "active"},
    }


def _build(db_path, monkeypatch, results, *, semantic_warnings=None, package_date="2026-07-10"):
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(db_path.parent))
    from mlomega_audio_elite.night_orchestrator.capability_manifest import build_capability_manifest
    return build_capability_manifest(
        person_id="me", package_date=package_date,
        stage_results=results, semantic_warnings=semantic_warnings,
    )


def _verdict(manifest, name):
    for cap in manifest["capabilities"]:
        if cap["capability"] == name:
            return cap["verdict"]
    raise AssertionError(f"capability {name} not in manifest")


# --------------------------------------------------------------------------- #


def test_all_capabilities_validated_allows_complete(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    manifest = _build(db, monkeypatch, _all_validated_results())
    assert manifest["complete"] is True
    assert manifest["blocking"] == []
    assert _verdict(manifest, "deep_audio") == "product_validated"
    assert _verdict(manifest, "life_model") == "product_validated"
    # Every recensed capability is present.
    names = {c["capability"] for c in manifest["capabilities"]}
    assert {
        "deep_audio", "deep_vision", "event_assembly", "brain2_v13_v14",
        "visual_consolidation", "longitudinal", "coordination", "life_model",
        "outcome_resolution", "life_model_v19", "prediction_emission",
        "self_schema", "live_ready",
    } <= names


def test_deep_vision_selected_but_none_analyzed_blocks(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    # Durable false-green: selected 3, analyzed 0, run says ok.
    _seed_deep_vision_run(db, selected=3, analyzed=0, status="ok")
    results = _all_validated_results()
    manifest = _build(db, monkeypatch, results)
    assert manifest["complete"] is False
    assert _verdict(manifest, "deep_vision") in {"degraded", "failed"}
    assert any(c["capability"] == "deep_vision" for c in manifest["blocking"])
    # The manifest names the exact blocking capability.
    assert "deep_vision" in (manifest["reason"] or "")


def test_deep_vision_all_analyzed_passes(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    _seed_deep_vision_run(db, selected=3, analyzed=3, status="ok")
    manifest = _build(db, monkeypatch, _all_validated_results())
    assert _verdict(manifest, "deep_vision") == "product_validated"
    assert manifest["complete"] is True


def test_deep_vision_retry_validates_only_post_stop_authoritative_run(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    _seed_deep_vision_run(
        db, run_id="dvrun-blocked", selected=16, readable=9,
        analyzed=0, status="blocked",
    )
    _seed_deep_vision_run(
        db, run_id="dvrun-repaired", selected=16, readable=16,
        analyzed=16, status="ok",
    )
    results = _all_validated_results()
    results["post_stop"]["v16_deep_vision"]["run_id"] = "dvrun-repaired"

    manifest = _build(db, monkeypatch, results)

    deep = next(c for c in manifest["capabilities"] if c["capability"] == "deep_vision")
    assert deep["verdict"] == "product_validated"
    assert deep["evidence"]["authoritative_run_id"] == "dvrun-repaired"
    assert deep["evidence"]["selected_keyframes"] == 16
    assert deep["evidence"]["readable_keyframes"] == 16
    assert deep["evidence"]["analyzed_keyframes"] == 16
    assert deep["evidence"]["run_statuses"] == ["ok"]
    assert manifest["complete"] is True


def test_deep_vision_selected_readable_analyzed_mismatch_blocks(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    # The historical false-green: coverage selected three semantic frames, but
    # only one sparse live JPEG existed and that one was analysed successfully.
    _seed_deep_vision_run(db, selected=3, readable=1, analyzed=1, status="ok")
    manifest = _build(db, monkeypatch, _all_validated_results())
    assert _verdict(manifest, "deep_vision") == "degraded"
    assert manifest["complete"] is False
    deep = next(c for c in manifest["capabilities"] if c["capability"] == "deep_vision")
    assert deep["evidence"]["selected_keyframes"] == 3
    assert deep["evidence"]["readable_keyframes"] == 1
    assert deep["evidence"]["analyzed_keyframes"] == 1


def test_audit_only_brain2_conversation_blocks(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    results = _all_validated_results()
    results["post_stop"]["brain2_processed"] = [
        {"conversation_id": "c1", "status": "ok"},
        {"conversation_id": "c2", "status": "audit_only"},
    ]
    manifest = _build(db, monkeypatch, results)
    assert manifest["complete"] is False
    assert _verdict(manifest, "brain2_v13_v14") == "bypassed"
    assert "brain2_v13_v14" in (manifest["reason"] or "")


def test_bypassed_deep_audio_with_retention_blocks(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    results = _all_validated_results()
    results["post_stop"]["v18_deep_audio"] = {"status": "skipped_requires_retention", "cleanup_blocked": True}
    manifest = _build(db, monkeypatch, results)
    assert manifest["complete"] is False
    assert _verdict(manifest, "deep_audio") == "bypassed"


def test_coordination_abstained_blocks(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    results = _all_validated_results()
    # A V17 similarity abstained after the embedder cache was refused surfaces
    # as an abstained coordination child (reconciliation).
    results["coordination"] = {
        "status": "ok",
        "package": {"status": "llm_ready"},
        "bindings": {"status": "compiled_ready"},
        "reconciliation": {"status": "abstained", "reason": "embedder cache access refused"},
    }
    manifest = _build(db, monkeypatch, results)
    assert manifest["complete"] is False
    assert _verdict(manifest, "coordination") == "abstained"
    assert "abstained" in (manifest["reason"] or "")


def test_valid_empty_without_proof_blocks_with_proof_passes(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    results = _all_validated_results()
    # self_schema empty WHILE eligible inputs exist -> false-green -> blocks.
    warn = [{"code": "self_schema_empty_with_eligible_inputs", "eligible_inputs": 4}]
    blocked = _build(db, monkeypatch, results, semantic_warnings=warn)
    assert blocked["complete"] is False
    assert _verdict(blocked, "self_schema") == "failed"

    # Same empty output but NO eligible inputs -> proven applicable -> passes.
    ok = _build(db, monkeypatch, results, semantic_warnings=[])
    assert _verdict(ok, "self_schema") == "valid_empty"
    assert ok["complete"] is True


def test_compiled_watch_only_and_no_life_delta_are_valid_successes(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    for status in ("compiled_watch_only", "compiled_no_life_delta"):
        results = _all_validated_results()
        results["life_model"] = {"status": status}
        manifest = _build(db, monkeypatch, results)
        assert _verdict(manifest, "life_model") == "valid_empty", status
        assert manifest["complete"] is True, status


def test_manifest_is_persisted_and_reloadable(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    from mlomega_audio_elite.governance_v18 import Scope, begin_or_resume_run
    from mlomega_audio_elite.night_orchestrator.capability_manifest import (
        build_capability_manifest,
        load_capability_manifest,
        persist_capability_manifest,
    )

    _seed_deep_vision_run(db, selected=2, analyzed=0, status="ok")
    run_id, _ = begin_or_resume_run(
        pipeline_name="brainlive_close_day",
        scope=Scope(person_id="me", mode="maintenance"),
        input_manifest={"t": 1},
        idempotency_key="cap-manifest-persist",
    )
    manifest = build_capability_manifest(
        person_id="me", package_date="2026-07-10", stage_results=_all_validated_results(),
    )
    persist_capability_manifest(run_id=run_id, person_id="me", package_date="2026-07-10", manifest=manifest)
    loaded = load_capability_manifest(run_id=run_id)
    assert loaded is not None
    assert loaded["complete"] is False
    assert any(c["capability"] == "deep_vision" for c in loaded["blocking"])


def test_gate_env_rollback_disables_block(tmp_path, monkeypatch):
    from mlomega_audio_elite.night_orchestrator.capability_manifest import capability_gate_enabled

    monkeypatch.delenv("MLOMEGA_E64_CAPABILITY_GATE", raising=False)
    assert capability_gate_enabled() is True
    monkeypatch.setenv("MLOMEGA_E64_CAPABILITY_GATE", "0")
    assert capability_gate_enabled() is False
