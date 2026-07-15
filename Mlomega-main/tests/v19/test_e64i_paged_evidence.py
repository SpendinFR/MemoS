from __future__ import annotations

import json
import sqlite3

import pytest

from mlomega_audio_elite.night_orchestrator.paged_evidence import (
    read_query_pages,
)
from mlomega_audio_elite.night_orchestrator.vision_atoms import (
    reduce_vision_observations,
)


def _source_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("CREATE TABLE source_items(item_id TEXT PRIMARY KEY, state TEXT, value INTEGER)")
    con.executemany(
        "INSERT INTO source_items(item_id,state,value) VALUES(?,?,?)",
        [(f"item-{index:03d}", "same", index) for index in range(11)],
    )
    con.commit()
    return con


def test_paginator_reads_cap_plus_one_and_proves_exact_manifest():
    con = _source_db()
    result = read_query_pages(
        con, stage_name="test", person_id="me", source_family="items",
        select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
        page_size=5,
    )

    assert len(result.rows) == 11
    assert result.manifest["source_count"] == 11
    assert result.manifest["included_count"] == 11
    assert result.manifest["page_count"] == 3
    assert result.manifest["complete"] is True


def test_paginator_reuses_only_atomically_committed_page_after_restart():
    con = _source_db()
    calls: list[tuple[str, ...]] = []

    def transform(rows, state):
        calls.append(tuple(row["item_id"] for row in rows))
        return {"ids": [row["item_id"] for row in rows]}, int(state or 0) + len(rows)

    def kill_after_first_commit(point, info):
        if point == "after_commit_before_next_page" and info["page_index"] == 0:
            raise RuntimeError("simulated kill")

    with pytest.raises(RuntimeError, match="simulated kill"):
        read_query_pages(
            con, stage_name="restart", person_id="me", source_family="items",
            select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
            page_size=5, transform=transform, initial_state=0,
            collect_rows=False, failpoint=kill_after_first_commit,
        )
    assert len(calls) == 1

    resumed = read_query_pages(
        con, stage_name="restart", person_id="me", source_family="items",
        select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
        page_size=5, transform=transform, initial_state=0,
        collect_rows=False,
    )

    # Page zero was committed with output+state and is not transformed twice.
    assert len(calls) == 3
    assert resumed.final_state == 11
    assert resumed.manifest["complete"] is True


def test_uncommitted_transform_replays_and_changed_page_invalidates_cache():
    con = _source_db()
    calls = 0

    def transform(rows, state):
        nonlocal calls
        calls += 1
        return [row["value"] for row in rows], state

    def kill_before_commit(point, info):
        if point == "after_transform_before_commit" and info["page_index"] == 0:
            raise RuntimeError("before commit")

    with pytest.raises(RuntimeError, match="before commit"):
        read_query_pages(
            con, stage_name="invalidate", person_id="me", source_family="items",
            select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
            page_size=5, transform=transform, failpoint=kill_before_commit,
        )
    assert calls == 1
    read_query_pages(
        con, stage_name="invalidate", person_id="me", source_family="items",
        select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
        page_size=5, transform=transform,
    )
    assert calls == 4  # failed page + all three pages

    con.execute("UPDATE source_items SET value=999 WHERE item_id='item-003'")
    con.commit()
    read_query_pages(
        con, stage_name="invalidate", person_id="me", source_family="items",
        select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
        page_size=5, transform=transform,
    )
    assert calls == 5  # only the changed first page is transformed again


def test_vision_state_crossing_page_boundary_remains_one_event():
    con = _source_db()
    result = read_query_pages(
        con, stage_name="vision", person_id="me", source_family="vision",
        select_sql="SELECT x.*,x.item_id AS __page_pk FROM source_items x",
        page_size=5,
    )
    observations = [
        {
            "observation_id": row["item_id"],
            "created_at": f"2026-07-14T10:00:{index:02d}Z",
            "scene_summary": row["state"],
            "objects_json": "[]", "visible_text_json": "[]",
        }
        for index, row in enumerate(result.rows)
    ]

    atoms = reduce_vision_observations(observations)

    assert len(atoms) == 1
    assert atoms[0].count == 11
    assert list(atoms[0].source_refs) == [f"item-{index:03d}" for index in range(11)]


def _configure_product_db(tmp_path, monkeypatch):
    db_path = tmp_path / "paged-product.db"
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(db_path))
    monkeypatch.setenv("MLOMEGA_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("MLOMEGA_E64_SHARED_FACTS", "1")
    from mlomega_audio_elite.brainlive_brain2_coordination_v15_12 import (
        ensure_coordination_schema,
    )
    from mlomega_audio_elite.brainlive_v15 import ensure_brainlive_schema

    ensure_brainlive_schema()
    ensure_coordination_schema()
    return db_path


def test_coordination_crosses_old_vision_and_binding_caps(tmp_path, monkeypatch):
    db_path = _configure_product_db(tmp_path, monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.brainlive_brain2_coordination_v15_12 import (
        collect_day_evidence,
        collect_brain2_forecast_evidence,
        compile_brain2_forecasts_to_live_bindings,
        create_brainlive_day_package,
    )
    now = "2026-07-14T10:00:00+00:00"
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO brainlive_sessions(
                   live_session_id,person_id,started_at,ended_at,status,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            ("session-cap", "me", now, "2026-07-14T11:00:00+00:00", "closed", now, now),
        )
        for index in range(201):
            frame_id = f"frame-{index:03d}"
            con.execute(
                """INSERT INTO vision_frames(
                       frame_id,person_id,live_session_id,captured_at,created_at
                   ) VALUES(?,?,?,?,?)""",
                (frame_id, "me", "session-cap", now, now),
            )
            con.execute(
                """INSERT INTO vision_scene_observations(
                       observation_id,frame_id,live_session_id,model,scene_summary,
                       people_count,objects_json,visible_text_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (f"obs-{index:03d}", frame_id, "session-cap", "fixture", "salon", 1, "[]", "[]", now),
            )
        for index in range(161):
            con.execute(
                """INSERT INTO predictions(
                       prediction_id,created_at,person_id,prediction_target,horizon,
                       current_context,predicted_value,probability,confidence,status,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (f"pred-{index:03d}", now, "me", f"target {index}", "H1", "test", "value", 0.7, 0.7, "open", now),
            )
        con.commit()

    day = collect_day_evidence("me", package_date="2026-07-14", limit=50)
    assert len(day["vision_change_atoms"]) == 1
    assert day["vision_change_atoms"][0]["count"] == 201
    assert len(day["vision_change_atoms"][0]["source_refs"]) == 201
    assert day["source_manifests"]["vision_observations"]["page_count"] == 5
    package = create_brainlive_day_package(
        "me", package_date="2026-07-14", limit=50,
    )
    assert package["source_counts"]["vision_observations"] == 201
    with connect(db_path) as con:
        stored = con.execute(
            "SELECT vision_json,source_manifest_json FROM brainlive_day_packages WHERE package_id=?",
            (package["package_id"],),
        ).fetchone()
    assert len(json.loads(stored["vision_json"])) == 1
    assert json.loads(stored["source_manifest_json"])["vision_observations"]["source_count"] == 201

    forecasts = collect_brain2_forecast_evidence("me", limit=40)
    assert len(forecasts["predictions_short_and_next"]) == 161
    manifest = forecasts["_source_manifests"]["predictions_short_and_next"]
    assert manifest["source_count"] == manifest["included_count"] == 161
    assert manifest["page_count"] == 5
    compiled = compile_brain2_forecasts_to_live_bindings("me", limit=40)
    assert compiled["bindings_created"] == 161


def test_life_collector_crosses_old_120_cap_without_self_evidence(tmp_path, monkeypatch):
    db_path = _configure_product_db(tmp_path, monkeypatch)
    from mlomega_audio_elite.db import connect
    from mlomega_audio_elite.brain2_life_model_v15_10 import (
        collect_canonical_evidence,
    )
    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        collect_life_model_delta,
        prepare_life_checkpoint_delta,
    )
    now = "2026-07-14T10:00:00+00:00"
    with connect(db_path) as con:
        con.executemany(
            """INSERT INTO behavior_signals(
                   signal_id,person_id,signal_type,signal_value,status,
                   confidence,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            [
                (f"signal-{index:03d}", "me", "observed", f"value {index}",
                 "isolated_signal", 0.6, now, now)
                for index in range(121)
            ],
        )
        con.executemany(
            """INSERT INTO brain2_personal_routine_models(
                   routine_id,person_id,routine_name,confidence,status,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                (f"routine-{index:03d}", "me", f"routine {index}", 0.6,
                 "active", now, now)
                for index in range(121)
            ],
        )
        con.commit()

    canonical = collect_canonical_evidence(
        "me", period_start="2026-07-14T00:00:00+00:00",
        period_end="2026-07-15T00:00:00+00:00", limit=40,
    )
    assert len(canonical["self_and_internal"]["behavior_signals"]) == 121
    manifest = canonical["evidence_page_manifests"]["self_and_internal.behavior_signals"]
    assert manifest["source_count"] == manifest["included_count"] == 121
    assert manifest["page_count"] == 4

    from mlomega_audio_elite.brain2_life_model_updater_v15_13 import (
        load_current_life_model,
    )
    current = load_current_life_model("me", limit=40)
    assert len(current["canonical_layers"]["routine"]) == 121
    assert current["source_manifests"]["canonical_layers.routine"]["page_count"] == 4

    delta = collect_life_model_delta(
        "me", period_start="2026-07-14T00:00:00+00:00",
        period_end="2026-07-15T00:00:00+00:00", limit=40,
    )
    assert "brain2_canonical_life_model" not in delta
    _, checkpoint = prepare_life_checkpoint_delta("me", delta)
    assert checkpoint["family_counts"]["self_and_internal.behavior_signals"] == 121
