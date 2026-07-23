from __future__ import annotations

from pathlib import Path
import sys


DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "apps" / "memory-dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from read_model import (  # noqa: E402
    bbox_audit,
    certainty_bucket,
    deep_vision_view,
    human_title,
    life_watch_view,
)


def test_technical_and_unknown_tables_never_become_certain_facts():
    assert certainty_bucket("artifact_lineage_v176", {"status": "completed"}) is None
    assert certainty_bucket("totally_unknown_model_table", {"status": "verified"}) is None
    assert certainty_bucket("predictions_v19", {"status": "open"}) == "prediction"
    assert certainty_bucket(
        "brain2_shared_facts_v19", {"epistemic_status": "inferred"}
    ) == "hypothesis"


def test_life_watch_has_human_title_and_dated_sources():
    row = {
        "watch_id": "technical-id",
        "candidate_kind": "choice",
        "identity_key": "prendre du recul",
        "status": "watching",
        "occurrence_count": 2,
        "independent_count": 2,
        "evidence_json": (
            '[{"occurred_at":"2026-07-22T10:00:00Z",'
            '"source_table":"choice_episodes","source_id":"choice-1"}]'
        ),
    }
    view = life_watch_view(row)
    assert view["title"] == "choice · prendre du recul"
    assert view["occurrences"] == 2
    assert view["sources"][0]["source_id"] == "choice-1"
    assert human_title("brain2_life_model_watch_candidates", row) != "technical-id"


def test_deep_vision_is_human_and_legacy_bad_bbox_is_explicit():
    view = deep_vision_view({
        "scene_summary_detailed": "William regarde une table avec des lunettes.",
        "objects_json": '["table","lunettes"]',
        "visible_text_json": '["OUVERT"]',
        "people_presence_json": '{"people_count":1}',
        "uncertainty_json": '["modèle exact des lunettes"]',
    })
    assert "lunettes" in view["title"]
    assert view["objects"] == ["table", "lunettes"]
    assert view["visible_text"] == ["OUVERT"]
    bad = bbox_audit('{"bbox":[300,120,-10,500]}')
    assert bad["valid"] is False
    assert bad["label"] == "bbox_invalid_legacy"
    assert bbox_audit('{"bbox":[10,20,100,200]}', frame_width=304, frame_height=540)["valid"]
