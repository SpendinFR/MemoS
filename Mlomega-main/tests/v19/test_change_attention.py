"""E48-B §2 — ChangeAttentionSkill live: instant "something changed here" cue.

Real PC-side checks (no hardware). ``ChangeAttention`` is fed synthetic
``WorldBrain.snapshot()``-shaped dicts directly (unit-level on the module, the
same style as ``test_e28_worldbrain.py``), plus one integration check through a
real ``BrainLiveSceneAdapter`` + ``v18_delivery`` queue to prove the cue rides the
EXISTING delivery path (no new queue).

Anti-noise invariants under test:

* first visit to a zone → silence (nothing to compare against yet);
* re-entry with an entity gone → exactly one cue;
* re-entry with no material change → silence;
* low ``map_quality`` on re-entry → silence even if the state actually changed;
* cooldown → a second qualifying re-entry within the window stays silent.
"""

from __future__ import annotations

import importlib.util
import sys
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


change_attention = _load("v19_change_attention", "services/live-pc/change_attention.py")
worldbrain = _load("v19_worldbrain", "services/live-pc/worldbrain.py")
scene_adapter = _load("v19_scene_adapter", "services/live-pc/brainlive_scene_adapter.py")


def _snap(zone, entities, *, map_quality=0.8):
    """A minimal WorldBrain.snapshot()-shaped dict for the entities under test."""
    return {
        "active_zone": zone,
        "map_quality": map_quality,
        "entities": [
            {"label": label, "lifecycle": "confirmed", "entity_id": f"ent-{label}",
             "evidence": [f"frame:{label}"]}
            for label in entities
        ],
    }


class _FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# --------------------------------------------------------------------------- first visit
def test_first_visit_is_silent():
    ca = change_attention.ChangeAttention(live_session_id="s1")
    result = ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    assert result is None
    assert ca.metrics["silenced_first_visit"] == 1
    assert ca.metrics["cues_emitted"] == 0


# --------------------------------------------------------------------------- reentry, disappeared object
def test_reentry_with_disappeared_object_emits_one_cue():
    clock = _FakeClock()
    ca = change_attention.ChangeAttention(live_session_id="s1", now_fn=clock)
    # First visit to zone-1: cup + phone present.
    ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    # Leave the zone (enter a different one).
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(1.0)
    # Re-enter zone-1: the phone is gone.
    result = ca.on_scene_snapshot(_snap("zone-1", ["cup"]))
    assert result is not None, "a net disappearance on re-entry must fire a cue"
    assert result["disappeared"] == ["phone"]
    assert result["appeared"] == []
    assert ca.metrics["cues_emitted"] == 1
    # A further re-entry with the SAME (already-cued) state must not fire again.
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(1.0)
    again = ca.on_scene_snapshot(_snap("zone-1", ["cup"]))
    assert again is None, "no material change since the last cue → silence"
    assert ca.metrics["cues_emitted"] == 1


def test_worldbrain_propagates_spatial_active_zone_into_product_snapshot(tmp_path):
    class _Spatial:
        zone = "zone-1"

        def map_quality(self):
            return 0.8

        def active_zone(self):
            return self.zone

    spatial = _Spatial()
    wb = worldbrain.WorldBrain(
        person_id="me", live_session_id="s-spatial", db_path=tmp_path / "memory.db",
        spatial=spatial, publish_world_state=False,
    )
    delta = {"source_frame_id": "f1", "entities": [], "map_quality": 0.0}

    wb.ingest_scene_delta(delta)
    assert wb.snapshot()["active_zone"] == "zone-1"
    assert wb.snapshot()["map_quality"] == pytest.approx(0.8)

    spatial.zone = "zone-2"
    wb.ingest_scene_delta({**delta, "source_frame_id": "f2"})
    assert wb.snapshot()["active_zone"] == "zone-2"


# --------------------------------------------------------------------------- reentry, no change
def test_reentry_without_change_is_silent():
    clock = _FakeClock()
    ca = change_attention.ChangeAttention(live_session_id="s1", now_fn=clock)
    ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(1.0)
    result = ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    assert result is None
    assert ca.metrics["silenced_below_threshold"] == 1
    assert ca.metrics["cues_emitted"] == 0


# --------------------------------------------------------------------------- low map_quality
def test_low_map_quality_silences_even_a_real_change():
    clock = _FakeClock()
    cfg = change_attention.ChangeAttentionConfig(min_map_quality=0.5)
    ca = change_attention.ChangeAttention(live_session_id="s1", now_fn=clock, config=cfg)
    ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"], map_quality=0.9))
    ca.on_scene_snapshot(_snap("zone-2", ["chair"], map_quality=0.9))
    clock.advance(1.0)
    # The phone really is gone, but map_quality on re-entry is below the floor.
    result = ca.on_scene_snapshot(_snap("zone-1", ["cup"], map_quality=0.1))
    assert result is None, "low map_quality must silence a change cue — no spatial claim"
    assert ca.metrics["silenced_low_quality"] == 1
    assert ca.metrics["cues_emitted"] == 0


# --------------------------------------------------------------------------- cooldown
def test_cooldown_suppresses_second_cue_within_window():
    clock = _FakeClock()
    cfg = change_attention.ChangeAttentionConfig(cooldown_seconds=60.0)
    ca = change_attention.ChangeAttention(live_session_id="s1", now_fn=clock, config=cfg)
    ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(1.0)
    first = ca.on_scene_snapshot(_snap("zone-1", ["cup"]))  # phone gone → cue
    assert first is not None
    assert ca.metrics["cues_emitted"] == 1

    # Leave and come back with a NEW change (cup gone too) well within cooldown.
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(5.0)  # << 60s cooldown
    second = ca.on_scene_snapshot(_snap("zone-1", []))
    assert second is None, "cooldown must suppress a second cue for the same zone"
    assert ca.metrics["silenced_cooldown"] == 1
    assert ca.metrics["cues_emitted"] == 1

    # After the cooldown elapses, a further net change may cue again.
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(61.0)
    third = ca.on_scene_snapshot(_snap("zone-1", []))
    assert third is not None
    assert ca.metrics["cues_emitted"] == 2


# --------------------------------------------------------------------------- delivery integration
def test_cue_delivered_through_existing_scene_adapter_queue(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))

    wb = worldbrain.WorldBrain(person_id="me", live_session_id="s-e48b", db_path=db_path,
                                publish_world_state=False)
    adapter = scene_adapter.BrainLiveSceneAdapter(
        person_id="me", live_session_id="s-e48b", worldbrain=wb, db_path=db_path,
    )
    adapter._ensure_session()  # brainlive_sessions row must exist for enqueue_delivery
    clock = _FakeClock()
    ca = change_attention.ChangeAttention(
        person_id="me", live_session_id="s-e48b", db_path=db_path,
        scene_adapter=adapter, now_fn=clock,
    )
    ca.on_scene_snapshot(_snap("zone-1", ["cup", "phone"]))
    ca.on_scene_snapshot(_snap("zone-2", ["chair"]))
    clock.advance(1.0)
    result = ca.on_scene_snapshot(_snap("zone-1", ["cup"]))
    assert result is not None
    assert result.get("status") == "queued", result

    from mlomega_audio_elite.db import connect

    with connect(db_path) as con:
        rows = con.execute(
            "SELECT message FROM brainlive_intervention_delivery_queue WHERE live_session_id='s-e48b'"
        ).fetchall()
        assert rows, "the cue must land in the SAME delivery queue as other suggestions"
        assert any("changé" in (r["message"] or "") for r in rows)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
