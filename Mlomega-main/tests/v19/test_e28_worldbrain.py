"""E28 — WorldBrain + spatial provider + scene adapter (real persistence).

All checks run on the PC side with a temp SQLite DB (no hardware):

* track→entity promotion (3 confirmed observations → WorldEntity; a single weak
  bbox never becomes an entity);
* last-seen with age;
* ChangeEvent ``moved`` when an entity's bbox shifts significantly;
* geometric relations (near / on_top_of / holds);
* map_quality below threshold → ``bearing_to`` returns None (no false arrow);
* real persistence: last-seen → ``visual_events_v19``; world_state →
  ``brainlive_world_states``;
* scene_adapter: a known person in scene → ``enqueue_delivery`` really called →
  ``brainlive_intervention_delivery_queue`` holds the candidate with
  source_key/evidence;
* HotSceneContext respects the character budget.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


worldbrain = _load("v19_worldbrain", "services/live-pc/worldbrain.py")
spatial = _load("v19_spatial", "services/live-pc/spatial.py")
scene_adapter = _load("v19_scene_adapter", "services/live-pc/brainlive_scene_adapter.py")


def _delta(frame_id, entities, *, map_quality=0.0):
    return {
        "session_id": "s-e28",
        "source_frame_id": frame_id,
        "entities": entities,
        "relations": [],
        "changes": [],
        "map_quality": map_quality,
        "evidence_refs": [f"frame:{frame_id}"],
    }


def _ent(track_id, label, bbox, conf=0.7, kind="object"):
    return {"track_id": track_id, "kind": kind, "label": label, "bbox": bbox,
            "confidence": conf, "visibility": 1.0, "age": 1}


def _wb(tmp_path, monkeypatch, **kw):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    wb = worldbrain.WorldBrain(
        person_id="me", live_session_id="s-e28", db_path=db_path,
        publish_world_state=kw.get("publish_world_state", True),
    )
    return wb, db_path


# --------------------------------------------------------------------------- promotion
def test_track_promoted_after_confirmed_observations(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    # 2 confirmed hits: not yet promoted (needs 3).
    wb.ingest_scene_delta(_delta("f1", [_ent("t1", "cup", [10, 10, 30, 40])]))
    wb.ingest_scene_delta(_delta("f2", [_ent("t1", "cup", [10, 10, 30, 40])]))
    assert wb.entities == {}
    # 3rd confirmed hit promotes it.
    out = wb.ingest_scene_delta(_delta("f3", [_ent("t1", "cup", [10, 10, 30, 40])]))
    assert out["promoted"], "track should be promoted after 3 confirmed observations"
    assert len(wb.entities) == 1
    e = next(iter(wb.entities.values()))
    assert e.label == "cup" and e.lifecycle == "confirmed"


def test_entity_id_survives_live_session_restart(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    config = worldbrain.WorldBrainConfig(
        promote_min_observations=1, promote_min_confidence=0.3
    )
    first = worldbrain.WorldBrain(
        person_id="me", live_session_id="session-one", db_path=db_path,
        config=config, publish_world_state=False,
    )
    first_id = first.ingest_scene_delta(
        _delta("one", [_ent("tracker-a", "mug", [10, 10, 30, 30])])
    )["promoted"][0]

    second = worldbrain.WorldBrain(
        person_id="me", live_session_id="session-two", db_path=db_path,
        config=config, publish_world_state=False,
    )
    second_id = second.ingest_scene_delta(
        _delta("two", [_ent("tracker-z", "mug", [12, 11, 32, 31])])
    )["promoted"][0]

    assert second_id == first_id
    assert "session-one" not in first_id and "session-two" not in second_id


def test_homonymous_objects_keep_distinct_durable_slots(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    config = worldbrain.WorldBrainConfig(
        promote_min_observations=1, promote_min_confidence=0.3
    )
    first = worldbrain.WorldBrain(
        person_id="me", live_session_id="s1", db_path=db_path,
        config=config, publish_world_state=False,
    )
    ids_first = first.ingest_scene_delta(_delta("f", [
        _ent("left", "cup", [0, 0, 20, 20]),
        _ent("right", "cup", [200, 0, 220, 20]),
    ]))["promoted"]
    assert len(set(ids_first)) == 2

    second = worldbrain.WorldBrain(
        person_id="me", live_session_id="s2", db_path=db_path,
        config=config, publish_world_state=False,
    )
    ids_second = second.ingest_scene_delta(_delta("g", [
        _ent("new-right", "cup", [198, 0, 218, 20]),
        _ent("new-left", "cup", [2, 0, 22, 20]),
    ]))["promoted"]
    assert set(ids_second) == set(ids_first)


def test_single_weak_bbox_never_promotes(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    # A single low-confidence bbox seen many times stays below the floor.
    for i in range(5):
        wb.ingest_scene_delta(_delta(f"w{i}", [_ent("weak", "book", [0, 0, 5, 5], conf=0.10)]))
    assert wb.entities == {}, "weak low-confidence detection must not become an entity"


# --------------------------------------------------------------------------- last-seen
def test_last_seen_with_age_and_disappearance(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    wb.config.stale_after_seconds = 0.0  # any absence marks last_seen immediately
    for f in ("a", "b", "c"):
        wb.ingest_scene_delta(_delta(f, [_ent("t1", "phone", [0, 0, 20, 20])]))
    assert len(wb.entities) == 1
    # Next frame without t1 → disappeared / last_seen.
    out = wb.ingest_scene_delta(_delta("d", [_ent("t2", "chair", [50, 50, 90, 90], conf=0.7)]))
    e = next(iter(wb.entities.values()))
    assert e.lifecycle == "last_seen"
    assert any(c["type"] == "disappeared" for c in out["changes"])
    ls = wb.last_seen()
    assert any(x["age_seconds"] >= 0.0 for x in ls)


# --------------------------------------------------------------------------- moved
def test_change_event_moved(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    for f in ("a", "b", "c"):
        wb.ingest_scene_delta(_delta(f, [_ent("t1", "mug", [10, 10, 30, 30])]))
    # Same track, bbox shifted far → moved.
    out = wb.ingest_scene_delta(_delta("d", [_ent("t1", "mug", [200, 200, 220, 220])]))
    assert any(c["type"] == "moved" for c in out["changes"]), out["changes"]
    moved = next(c for c in out["changes"] if c["type"] == "moved")
    assert moved["before"] and moved["after"], "moved must carry before/after evidence"


# --------------------------------------------------------------------------- relations
def test_geometric_relations(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    wb.config.promote_min_observations = 1  # simplify: entities immediately
    # A laptop on top of a table (laptop higher on screen, horizontal overlap).
    table = _ent("tbl", "dining table", [0, 100, 200, 160])
    laptop = _ent("lap", "laptop", [40, 40, 120, 100])
    out = wb.ingest_scene_delta(_delta("r1", [table, laptop]))
    preds = {r["predicate"] for r in out["relations"]}
    assert "near" in preds or "on_top_of" in preds, out["relations"]


def test_holds_relation(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    wb.config.promote_min_observations = 1
    person = _ent("p", "person", [0, 0, 100, 300])
    phone = _ent("ph", "cell phone", [40, 120, 70, 160])
    out = wb.ingest_scene_delta(_delta("h1", [person, phone]))
    preds = {r["predicate"] for r in out["relations"]}
    assert "holds" in preds, out["relations"]


# --------------------------------------------------------------------------- spatial
def test_map_quality_low_returns_no_bearing():
    pm = spatial.PoseKeyframeMap()
    # A single scattered pose → very low quality → no arrow.
    pm.observe_pose("a", {"position": [0, 0, 0], "rotation": [0, 0, 0, 1]}, now=100.0)
    pm.note_entity("e1", "a", {"position": [5, 0, 5], "rotation": [0, 0, 0, 1]})
    assert pm.map_quality(now=100.0) < pm.config.min_map_quality_for_bearing
    assert pm.bearing_to("e1", now=100.0) is None


def test_bearing_when_map_qualifies():
    pm = spatial.PoseKeyframeMap()
    for i in range(30):
        pm.observe_pose(f"f{i}", {"position": [0, 0, 0], "rotation": [0, 0, 0, 1]}, now=100.0 + i * 0.01)
    pm.note_entity("e1", "f29", {"position": [2.0, 0, 0], "rotation": [0, 0, 0, 1]})
    b = pm.bearing_to("e1", now=100.3)
    assert b is not None
    assert abs(b["bearing_deg"] - 90.0) < 1.0  # entity to the right
    assert b["distance"] == 2.0


# --------------------------------------------------------------------------- persistence
def test_last_seen_persisted_to_visual_events_and_world_state(tmp_path, monkeypatch):
    wb, db_path = _wb(tmp_path, monkeypatch)  # publish_world_state=True
    for f in ("a", "b", "c"):
        wb.ingest_scene_delta(_delta(f, [_ent("t1", "book", [10, 10, 30, 30])], map_quality=0.5))

    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        vevents = con.execute(
            "SELECT event_type, person_id FROM visual_events_v19 WHERE person_id='me'"
        ).fetchall()
        assert vevents, "WorldBrain must persist last-seen into visual_events_v19"
        assert any(r["event_type"] == "entity_last_seen" for r in vevents)

        wstates = con.execute(
            "SELECT person_id, visual_context_json FROM brainlive_world_states WHERE person_id='me'"
        ).fetchall()
        assert wstates, "WorldBrain must publish current world_state into brainlive_world_states"


def test_end_session_writes_summary(tmp_path, monkeypatch):
    wb, db_path = _wb(tmp_path, monkeypatch, publish_world_state=False)
    for f in ("a", "b", "c"):
        wb.ingest_scene_delta(_delta(f, [_ent("t1", "lamp", [0, 0, 20, 20])]))
    sid = wb.end_session(place_hint="office")
    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        row = con.execute(
            "SELECT place_hint FROM scene_session_summaries_v19 WHERE scene_summary_id=?", (sid,)
        ).fetchone()
        assert row and row["place_hint"] == "office"


def test_focus_search_rehydrates_latest_owner_sighting_across_sessions(tmp_path, monkeypatch):
    """A fresh PhoneOnly process must answer from durable memory, not RAM."""
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    config = worldbrain.WorldBrainConfig(
        promote_min_observations=1, promote_min_confidence=0.3
    )
    first = worldbrain.WorldBrain(
        person_id="me", live_session_id="session-salon", db_path=db_path,
        config=config, publish_world_state=False,
    )
    first.ingest_scene_delta(
        _delta("glasses-1", [_ent("track-old", "lunettes", [10, 10, 40, 30], conf=0.83)])
    )
    first.end_session(place_hint="salon")

    fresh_process = worldbrain.WorldBrain(
        person_id="me", live_session_id="session-next", db_path=db_path,
        config=config, publish_world_state=False,
    )
    remembered = fresh_process.find_entity_record("où sont mes lunettes ?")
    assert remembered is not None
    assert remembered["visible"] is False
    assert remembered["label"] == "lunettes"
    assert remembered["place_hint"] == "salon"
    assert remembered["confidence"] == pytest.approx(0.83)
    assert remembered["source"] == "durable_registry"
    assert remembered["evidence"] == [
        f"worldbrain_entity_registry_v19:{remembered['entity_id']}"
    ]

    # A later real sighting updates the latest state while visual_events keeps
    # the prior observed history.  It is never collapsed into a fake single fact.
    fresh_process.ingest_scene_delta(
        _delta("glasses-2", [_ent("track-new", "lunettes", [200, 40, 240, 70], conf=0.91)])
    )
    current = fresh_process.find_entity_record("mes lunettes")
    assert current is not None and current["visible"] is True
    assert current["last_session_id"] == "session-next"
    assert current["last_bbox"] == [200.0, 40.0, 240.0, 70.0]

    from mlomega_audio_elite.db import connect
    with connect(db_path) as con:
        history = con.execute(
            """SELECT COUNT(*) FROM visual_events_v19
               WHERE person_id='me' AND event_type='entity_last_seen'"""
        ).fetchone()[0]
    assert history >= 2


# --------------------------------------------------------------------------- scene adapter
def test_scene_adapter_enqueues_delivery_for_known_person(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))

    wb = worldbrain.WorldBrain(person_id="me", live_session_id="s-e28", db_path=db_path,
                               publish_world_state=False)
    wb.config.promote_min_observations = 1
    # A confirmed person track.
    for f in ("a", "b"):
        wb.ingest_scene_delta(_delta(f, [_ent("p1", "person", [0, 0, 100, 300], conf=0.8)]))
    entity_id = next(iter(wb.entities))

    adapter = scene_adapter.BrainLiveSceneAdapter(
        person_id="me", live_session_id="s-e28", worldbrain=wb, db_path=db_path,
        known_people={entity_id: {"name": "Alice", "relation": "amie"}},
    )
    ctx = adapter.build_context()
    results = adapter.evaluate_situations(ctx)
    assert any(r.get("status") == "queued" for r in results), results

    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        rows = con.execute(
            "SELECT message, evidence_json FROM brainlive_intervention_delivery_queue "
            "WHERE live_session_id='s-e28'"
        ).fetchall()
        assert rows, "delivery must land in the queue"
        assert any("Alice" in (r["message"] or "") for r in rows)
        dedupes = con.execute(
            "SELECT candidate_fingerprint FROM brainlive_intervention_delivery_dedupes"
        ).fetchall()
        assert dedupes, "delivery must have a source_key-based dedup entry"


def test_hot_scene_context_respects_budget(tmp_path, monkeypatch):
    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    wb.config.promote_min_observations = 1
    # Flood many entities so the budget must drop some into omissions.
    ents = [_ent(f"t{i}", f"obj{i}", [i, i, i + 10, i + 10]) for i in range(40)]
    wb.ingest_scene_delta(_delta("flood", ents))
    cfg = scene_adapter.SceneAdapterConfig(hot_budget_chars=1200, max_visible_entities=40)
    ctx = scene_adapter.build_hot_scene_context(
        session_id="s-e28", world=wb.snapshot(), config=cfg
    )
    import json

    assert len(json.dumps(ctx, default=str)) <= cfg.hot_budget_chars + 200
    assert ctx["omissions"], "over-budget fields must be logged as omissions, not silently dropped"
    assert ctx["session_id"] == "s-e28" and ctx["as_of"]


def test_ingest_scene_delta_is_thread_safe(tmp_path, monkeypatch):
    """Regression: the service-local SQLite connection is created on the init
    thread but ingest_scene_delta runs from the vision worker threads. Before the
    fix this raised "SQLite objects created in a thread can only be used in that
    same thread" 50+ times per session and killed scene ingestion. The connection
    must allow cross-thread use and serialize all access under a lock."""
    import threading

    wb, _ = _wb(tmp_path, monkeypatch, publish_world_state=False)
    wb.config.promote_min_observations = 1
    errors: list[str] = []

    def worker(worker_id: int) -> None:
        # Non-overlapping, well-separated bboxes per worker so promotions do not
        # merge across workers — the point is that every persist crosses a thread
        # boundary and must not raise the cross-thread SQLite error.
        base = worker_id * 1000
        try:
            for i in range(20):
                x = base + i * 40
                wb.ingest_scene_delta(
                    _delta(
                        f"w{worker_id}-f{i}",
                        [_ent(f"w{worker_id}-t{i}", "cup", [x, 0, x + 20, 20])],
                    )
                )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The regression: NO "SQLite objects created in a thread ..." error from any
    # of the 4 worker threads. Before the fix this raised on every persist.
    assert not errors, f"ingest_scene_delta raised from worker threads: {errors}"
    # Entities were promoted + persisted across the thread boundary (durable
    # registry may merge same-label slots, so assert a healthy count, not exact).
    assert len(wb.entities) >= 40
