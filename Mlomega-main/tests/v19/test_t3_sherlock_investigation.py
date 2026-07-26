from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import sqlite3
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sherlock_mod = _load(
    "test_t3_sherlock", "services/live-pc/sherlock_investigation.py"
)
router_mod = _load("test_t3_router", "services/live-pc/intent_router.py")
pipeline_mod = _load("test_t3_pipeline", "services/live-pc/live_pipeline.py")


def _frame(offset: int = 0) -> np.ndarray:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[30 + offset : 110 + offset, 50:170] = (20, 180, 240)
    image[125:190, 180:285] = (190, 40, 80)
    return image


def _service(tmp_path: Path, emitted: list[dict] | None = None):
    return sherlock_mod.SherlockInvestigation(
        person_id="me",
        live_session_id="live-t3",
        db_path=tmp_path / "memory.db",
        evidence_root=tmp_path / "evidence",
        emit_ui_intent=(emitted.append if emitted is not None else None),
        auto_interval_s=2.0,
    )


def test_inactive_mode_creates_no_db_or_media(tmp_path):
    service = _service(tmp_path)
    assert service.capture(_frame())["status"] == "inactive"
    service.observe_frame(_frame())
    assert not (tmp_path / "memory.db").exists()
    assert not (tmp_path / "evidence").exists()


def test_capture_keeps_lossless_original_crop_hashes_and_provenance(tmp_path):
    emitted: list[dict] = []
    service = _service(tmp_path, emitted)
    started = service.start("Qui a mangé le chocolat ?")
    result = service.capture(
        _frame(),
        SimpleNamespace(frame_id="eye-42", captured_at_utc="2026-07-26T12:00:00+00:00"),
        bbox=[0.1, 0.1, 0.6, 0.7],
        reason="manual",
    )

    assert started["status"] == "active"
    assert result["status"] == "captured"
    assert result["original"]["width"] == 320
    assert result["selected"]["kind"] == "crop"
    assert result["selected"]["width"] == 160
    assert service.resolve_media_path(result["selected"]["evidence_id"]).is_file()
    with sqlite3.connect(tmp_path / "memory.db") as con:
        rows = con.execute(
            """SELECT evidence_kind,parent_evidence_id,source_frame_id,truth_level,
                      derivation_json,sha256
               FROM sherlock_evidence_v19 ORDER BY rowid"""
        ).fetchall()
    assert [row[0] for row in rows] == ["original", "crop"]
    assert rows[1][1] == result["original"]["evidence_id"]
    assert rows[0][2] == rows[1][2] == "eye-42"
    assert rows[0][3] == rows[1][3] == "observed"
    assert json.loads(rows[1][4])["operation"] == "pixel_crop"
    assert rows[0][5] != rows[1][5]
    assert emitted[-1]["component"] == "virtual_screen"


def test_enhancement_is_derived_and_original_remains_byte_identical(tmp_path):
    service = _service(tmp_path)
    service.start()
    captured = service.capture(_frame(), SimpleNamespace(frame_id="eye-1"), emit=False)
    source_path = Path(captured["selected"]["path"])
    source_bytes = source_path.read_bytes()

    result = service.enhance(captured["selected"]["evidence_id"])

    assert result["status"] == "enhanced"
    assert source_path.read_bytes() == source_bytes
    assert result["enhanced"]["truth_level"] == "enhanced_candidate"
    with sqlite3.connect(tmp_path / "memory.db") as con:
        row = con.execute(
            """SELECT parent_evidence_id,truth_level,derivation_json
               FROM sherlock_evidence_v19 WHERE evidence_kind='enhanced'"""
        ).fetchone()
    assert row[0] == captured["selected"]["evidence_id"]
    assert row[1] == "enhanced_candidate"
    assert json.loads(row[2])["source_sha256"] == captured["selected"]["sha256"]


def test_comparison_and_timeline_merge_t1_without_inventing_culprit(tmp_path):
    service = _service(tmp_path)
    service.start("Chocolat")
    first = service.capture(_frame(), SimpleNamespace(frame_id="f1"), emit=False)
    second = service.capture(_frame(25), SimpleNamespace(frame_id="f2"), emit=False)
    service.observe_change_attention(
        {
            "message": "Quelque chose a changé ici : chocolat ne semble plus là.",
            "zone": "cuisine",
            "appeared": [],
            "disappeared": ["chocolat"],
            "score": 0.8,
            "evidence_refs": ["frame:f1", "frame:f2"],
        }
    )
    with sqlite3.connect(tmp_path / "memory.db") as con:
        con.executescript(
            """
            CREATE TABLE live_action_candidates_v19(
              action_event_id TEXT PRIMARY KEY,person_id TEXT,live_session_id TEXT,
              action_type TEXT,subject_label TEXT,object_label TEXT,started_at TEXT,
              ended_at TEXT,confidence REAL,truth_level TEXT,evidence_refs_json TEXT,
              detail_json TEXT
            );
            """
        )
        con.execute(
            """INSERT INTO live_action_candidates_v19 VALUES(
                 'a1','me','live-t3','take','person','chocolat',
                 '2099-07-26T12:00:00+00:00','2099-07-26T12:00:03+00:00',
                 0.72,'probable','["frame:f2"]','{}')"""
        )

    compared = service.compare(
        first["selected"]["evidence_id"], second["selected"]["evidence_id"]
    )
    timeline = service.timeline()

    assert compared["status"] == "compared"
    assert compared["finding"]["truth_level"] == "probable"
    assert compared["finding"]["detail"]["no_identity_or_cause_inferred"] is True
    assert timeline["status"] == "ok"
    assert {event["kind"] for event in timeline["events"]} >= {
        "change_attention",
        "visual_comparison",
        "temporal_action",
    }
    assert not any("coupable" in event["text"].lower() for event in timeline["events"])


def test_delete_removes_rows_and_media_immediately(tmp_path):
    service = _service(tmp_path)
    session_id = service.start()["sherlock_session_id"]
    service.capture(_frame(), SimpleNamespace(frame_id="f1"), emit=False)
    directory = tmp_path / "evidence" / session_id
    assert directory.is_dir()

    assert service.delete()["status"] == "deleted"
    assert not directory.exists()
    with sqlite3.connect(tmp_path / "memory.db") as con:
        assert con.execute("SELECT COUNT(*) FROM sherlock_sessions_v19").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM sherlock_evidence_v19").fetchone()[0] == 0


def test_capture_hard_cap_is_enforced_before_writing_more_media(tmp_path):
    service = sherlock_mod.SherlockInvestigation(
        person_id="me",
        live_session_id="live-cap",
        db_path=tmp_path / "memory.db",
        evidence_root=tmp_path / "evidence",
        max_captures=2,
    )
    service.start()
    assert service.capture(_frame(), emit=False)["status"] == "captured"
    assert service.capture(_frame(5), emit=False)["status"] == "captured"
    assert service.capture(_frame(10), emit=False)["status"] == "cap_reached"
    with sqlite3.connect(tmp_path / "memory.db") as con:
        assert con.execute("SELECT COUNT(*) FROM sherlock_evidence_v19").fetchone()[0] == 2


def test_natural_voice_and_menu_share_one_sherlock_handler():
    calls: list[tuple[str, dict]] = []

    def handler(action, params):
        calls.append((action, params))
        return {"status": "active" if action in {"start", "toggle"} else "ok"}

    router = router_mod.IntentRouter(sherlock_handler=handler)
    assert router.on_transcript("active le mode Sherlock")["intent"] == "sherlock_start"
    assert router.on_transcript("capture cette trace")["intent"] == "sherlock_capture"
    assert router.on_transcript("compare les captures")["intent"] == "sherlock_compare"
    assert router.on_device_action("sherlock_toggle")["intent"] == "sherlock_toggle"
    assert [call[0] for call in calls] == ["start", "capture", "compare", "toggle"]


def test_real_pipeline_routes_eye_frame_scene_delta_and_t1_into_sherlock(tmp_path):
    pipe = pipeline_mod.LivePipeline(
        session_id="transport-t3",
        live_session_id="live-t3",
        person_id="me",
        db_path=tmp_path / "memory.db",
        enable_detector=False,
        enable_worldbrain=False,
        enable_conversation=False,
        enable_intents=True,
        enable_replay=True,
        user_profile={"display": "xreal_one_pro"},
    )
    started = pipe.intents.on_transcript("active le mode Sherlock")
    pipe._latest_frame_bgr = _frame()
    pipe._latest_envelope = SimpleNamespace(
        frame_id="eye-live", captured_at_utc="2026-07-26T14:00:00+00:00"
    )
    captured = pipe.intents.on_transcript("capture cette trace")
    pipe._on_scene_delta(
        {
            "session_id": "transport-t3",
            "source_frame_id": "eye-live",
            "frame_id": "eye-live",
            "entities": [
                {
                    "track_id": "person-1",
                    "kind": "object",
                    "label": "person",
                    "bbox": [10, 10, 100, 220],
                    "confidence": 0.9,
                }
            ],
            "relations": [],
            "changes": [],
            "evidence_refs": ["frame:eye-live"],
        }
    )

    assert started["handled"] is True
    assert captured["result"]["status"] == "captured"
    assert pipe._temporal_actions is not None
    with sqlite3.connect(tmp_path / "memory.db") as con:
        assert con.execute("SELECT COUNT(*) FROM sherlock_sessions_v19").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM sherlock_evidence_v19").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM sherlock_findings_v19 WHERE finding_kind='scene_delta'"
        ).fetchone()[0] == 1
    pipe.release_live_resources()
    with sqlite3.connect(tmp_path / "memory.db") as con:
        assert con.execute(
            "SELECT status FROM sherlock_sessions_v19"
        ).fetchone()[0] == "completed"
