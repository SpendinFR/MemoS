from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


actions_mod = _load(
    "test_t1_temporal_actions",
    "services/live-pc/temporal_action_recognizer.py",
)
text_mod = _load(
    "test_t1_world_text",
    "services/live-pc/world_text_memory.py",
)
resolver_mod = _load(
    "test_t1_structured_resolver",
    "src/mlomega_audio_elite/structured_memory_resolver_v19.py",
)
service_mod = _load(
    "test_t1_augmented_service",
    "services/augmented-reality/service.py",
)


def _delta(frame: str, *, person=True, cup_box=None):
    entities = []
    if person:
        entities.append(
            {
                "track_id": "person-1",
                "kind": "object",
                "label": "person",
                "bbox": [100, 100, 400, 650],
                "confidence": 0.9,
            }
        )
    if cup_box is not None:
        entities.append(
            {
                "track_id": "cup-1",
                "kind": "object",
                "label": "cup",
                "bbox": cup_box,
                "confidence": 0.88,
            }
        )
    return {
        "source_frame_id": frame,
        "frame_width": 1000,
        "frame_height": 800,
        "entities": entities,
    }


def test_temporal_actions_persist_lossless_candidates_for_sherlock(tmp_path):
    db = tmp_path / "memory.db"
    recognizer = actions_mod.TemporalActionRecognizer(
        person_id="me", live_session_id="live-1", db_path=db
    )
    start = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
    emitted = []
    sequence = [
        _delta("f1", cup_box=[500, 300, 550, 350]),
        _delta("f2", cup_box=[500, 300, 550, 350]),
        _delta("f3", cup_box=[350, 300, 400, 350]),  # hand/person overlap
        _delta("f4", cup_box=[520, 400, 570, 450]),  # release
        _delta("f5", cup_box=[520, 400, 570, 450]),
        _delta("f6", cup_box=[520, 400, 570, 450]),
        _delta("f7", person=False, cup_box=[520, 400, 570, 450]),
    ]
    for index, delta in enumerate(sequence):
        emitted.extend(
            recognizer.ingest(
                delta,
                monotonic_s=float(index),
                observed_at=start + timedelta(seconds=index),
            )
        )

    types = {item["action_type"] for item in emitted}
    assert {"enter_scene", "take_object", "place_object", "exit_scene"} <= types
    take = next(item for item in emitted if item["action_type"] == "take_object")
    assert take["subject_track_id"] == "person-1"
    assert take["object_track_id"] == "cup-1"
    assert take["truth_level"] == "probable"
    assert take["status"] == "candidate"
    assert len(take["source_frame_ids"]) >= 3

    with sqlite3.connect(db) as con:
        rows = con.execute(
            """SELECT action_type,truth_level,status,evidence_refs_json
               FROM live_action_candidates_v19 ORDER BY ended_at"""
        ).fetchall()
    assert {row[0] for row in rows} >= types
    assert all(row[1:3] == ("probable", "candidate") for row in rows)
    assert all("frame:" in row[3] for row in rows)


def test_temporal_actions_abstain_on_one_weak_frame(tmp_path):
    recognizer = actions_mod.TemporalActionRecognizer(
        person_id="me", live_session_id="live-weak", db_path=tmp_path / "m.db"
    )
    assert (
        recognizer.ingest(
            _delta("weak", cup_box=None),
            monotonic_s=0.0,
        )
        == []
    )
    with sqlite3.connect(tmp_path / "m.db") as con:
        count = con.execute(
            "SELECT COUNT(*) FROM live_action_candidates_v19"
        ).fetchone()[0]
    assert count == 0


def _ocr(frame: str, text: str):
    return {
        "type": "ui_intent",
        "source_frame_id": frame,
        "target_track_id": "sign-1",
        "content": {
            "kind": "ocr",
            "text": text,
            "source": "rapidocr",
            "lines": [{"text": text, "confidence": 0.94}],
        },
        "truth_level": "observed",
        "confidence": 0.94,
        "evidence_refs": [f"frame:{frame}"],
    }


def test_world_text_is_durable_queryable_and_alerts_only_with_history(tmp_path):
    db = tmp_path / "memory.db"
    memory = text_mod.WorldTextMemory(
        person_id="me", live_session_id="live-price", db_path=db
    )
    start = datetime(2026, 7, 20, 8, tzinfo=timezone.utc)
    for index, price in enumerate(("1,10 €", "1,20 €", "1,15 €")):
        observation, anomaly = memory.record(
            _ocr(f"prior-{index}", f"Baguette tradition {price}"),
            request={"kind": "ocr"},
            place_key="Boulangerie du centre",
            observed_at=start + timedelta(days=index),
        )
        assert observation is not None
        assert anomaly is None

    observation, anomaly = memory.record(
        _ocr("current", "Baguette tradition 2,10 €"),
        request={"kind": "ocr"},
        place_key="Boulangerie du centre",
        observed_at=start + timedelta(days=4),
    )
    assert observation["numeric_value"] == 2.10
    assert anomaly is not None
    assert anomaly["sample_count"] == 3
    assert anomaly["reference_value"] == 1.15
    card = memory.anomaly_intent(anomaly, text=observation["text"])
    assert card["truth_level"] == "inferred"
    assert "3 observations" in card["content"]["text"]

    duplicate, duplicate_anomaly = memory.record(
        _ocr("current", "Baguette tradition 2,10 €"),
        request={"kind": "ocr"},
        place_key="Boulangerie du centre",
        observed_at=start + timedelta(days=4),
    )
    assert duplicate is None and duplicate_anomaly is None

    answer = resolver_mod.StructuredMemoryResolver(
        person_id="me", db_path=db
    ).resolve("C'était combien le prix de la baguette la dernière fois ?")
    assert answer is not None
    assert answer["kind"] == "world_text_value"
    assert "2.10 €" in answer["text"]
    assert answer["evidence_refs"][0].startswith(
        "world_text_observations_v19:"
    )


def test_t1_capabilities_are_opt_in_and_backed():
    state = service_mod.PreferenceState()
    features = {feature: False for feature in service_mod.KNOWN_FEATURES}
    features["action_recognition"] = True
    features["world_text"] = True
    result = state.apply(
        {
            "schema_version": 1,
            "session_id": "t1",
            "person_id": "me",
            "master_enabled": True,
            "features": features,
            "probe": {},
        }
    )
    assert result["active_features"] == [
        "action_recognition",
        "world_text",
    ]
