from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.transport

ROOT = Path(__file__).resolve().parents[2]


def _harness():
    path = ROOT / "tools" / "harness" / "final_all_scenarios.py"
    spec = importlib.util.spec_from_file_location("final_all_scenarios_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_final_all_scenarios_crosses_real_product_boundaries(tmp_path):
    harness = _harness()
    db_path = tmp_path / "final-all-scenarios.db"
    harness.seed_fixture(db_path)

    report = harness.run_gate(db_path)

    assert report["status"] == "passed"
    memory = report["memory_scenarios"]
    assert set(memory) == {
        "where_date", "last_encounter", "topic_history", "conflict",
        "latest_price", "predictions", "expression", "fuzzy", "success",
        "semantic_replay",
    }
    assert all(row["component"] in {"context_card", "virtual_screen"} for row in memory.values())
    assert all(row["evidence_refs"] for row in memory.values())
    live = report["ultralive"]
    assert live["spatial_find"]["bearing"] is None
    assert live["deep_vision_last_seen"]["content"]["place_hint"] == "entrée"
    assert live["deep_vision_last_seen"]["bearing"] is None
    assert all(row["handled"] for row in live["commands"].values())
    assert live["help_flow"] == [
        "help_start", "help_start", "help_advance", "help_repeat", "help_stop",
    ]
    assert live["identity"]["person_id"] == "maxime"
    assert live["identity"]["relation_pack"][0]["summary"]
    assert live["proactive"]["prediction_matches"] >= 1
    assert live["proactive"]["intervention_matches"] >= 1
    assert live["proactive"]["queued"] >= 1
    assert live["change_attention"]["result"]["disappeared"] == ["phone"]
    assert live["change_attention"]["low_quality_silenced"] == 1
    assert live["appearance_change"]["entity_id"] == "person:maxime"
    assert live["appearance_cue_queued"] >= 1
    assert live["delivery"]["content"]["text"]
    assert live["receipt"] == "displayed"
    assert live["downlink_count"] >= 10
