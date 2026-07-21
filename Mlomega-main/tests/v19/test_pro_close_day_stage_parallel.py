"""PRO CloseDay Task 1/2/3 — post-motor stage parallelism, DAG, shared cache core.

All fakes, no real network, no paid run, no GPU.  These exercise the surgical
scheduler in ``v18_close_day`` and the shared global-fact-core cache prefix in
``brain2_strict_v13_2`` directly, so they never touch a model backend.

Coverage:
  * non-regression: the level-parallel scheduler produces byte-for-byte the same
    written rows as the sequential path (same starting DB);
  * DAG proof: every stage that writes a table read by another is scheduled in a
    strictly earlier level than its consumer;
  * WAL + separate connections proven (each stage opens its own db.connect());
  * cache: the common global-fact core is placed in ONE shared prefix whose
    digest is identical for every global engine of an episode;
  * without MLOMEGA_PRO_CLOSEDAY the scheduler stays sequential (byte-for-byte).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from mlomega_audio_elite import v18_close_day as cd
from mlomega_audio_elite import brain2_strict_v13_2 as strict
from mlomega_audio_elite.db import connect, write_transaction
from mlomega_audio_elite.governance_v18 import (
    Scope,
    begin_or_resume_run,
    ensure_v18_schema,
)

pytestmark = pytest.mark.memory


# ----------------------------------------------------------------- DAG shape ----
def test_post_motor_levels_cover_exactly_the_nine_stages() -> None:
    flat = [name for level in cd._POST_MOTOR_STAGE_LEVELS for name in level]
    assert sorted(flat) == sorted(
        {
            "visual_consolidation",
            "longitudinal",
            "coordination",
            "life_model",
            "outcome_resolution",
            "life_model_v19",
            "prediction_emission",
            "self_schema",
            "live_ready",
        }
    )
    # No stage appears twice.
    assert len(flat) == len(set(flat))


def test_post_motor_dag_is_topologically_valid() -> None:
    """A producer stage is scheduled STRICTLY earlier than any stage that reads
    a table it writes in the close-day.  These edges were proven by reading each
    ``run_*`` function's SQL (see the module docstring in ``v18_close_day``)."""
    # REAL read->write dependency edges among the nine post-motor stages.
    deps = {
        "visual_consolidation": set(),
        "longitudinal": set(),
        "coordination": set(),
        "life_model": {"coordination", "longitudinal"},
        "outcome_resolution": {"visual_consolidation"},
        "life_model_v19": {"visual_consolidation", "outcome_resolution"},
        "prediction_emission": {"life_model_v19"},
        "self_schema": {"life_model_v19", "outcome_resolution", "longitudinal"},
        "live_ready": {"longitudinal", "coordination", "life_model"},
    }
    level_of = {
        name: idx
        for idx, level in enumerate(cd._POST_MOTOR_STAGE_LEVELS)
        for name in level
    }
    for stage, parents in deps.items():
        for parent in parents:
            assert level_of[parent] < level_of[stage], (
                f"{stage} (level {level_of[stage]}) reads a table written by "
                f"{parent} (level {level_of[parent]}) but is not scheduled after it"
            )


def test_no_two_stages_in_a_level_write_the_same_table() -> None:
    """Stages that run in the SAME wave must not write a common table (otherwise
    the parallel writers would race on content, not merely serialise)."""
    # Write-sets proven by reading each stage's SQL.  (Read-only w.r.t. shared
    # tables is fine; only WRITE overlap inside a level is disallowed.)
    writes = {
        "visual_consolidation": {"visual_events_v19", "brain2_spatial_routine_models"},
        "longitudinal": {
            "confirmed_patterns", "candidate_patterns", "prediction_cases",
            "brain2_observed_cases_v17", "brain2_global_life_patterns_v17",
        },
        "coordination": {
            "brainlive_day_packages", "brainlive_brain2_reconciliations",
            "brainlive_context_snapshots_v1512", "brain2_life_model_lifecycle",
        },
        "life_model": {"brain2_life_model_strata", "brain2_life_model_item_lifecycle"},
        "outcome_resolution": {"prediction_outcomes_v19", "predictions_v19"},
        "life_model_v19": {"life_model_entries_v19"},
        "prediction_emission": {"predictions_v19"},
        "self_schema": {"self_schema_v19"},
        "live_ready": {"brainlive_personal_model_exports", "brainlive_live_relevance_index"},
    }
    for level in cd._POST_MOTOR_STAGE_LEVELS:
        for i, a in enumerate(level):
            for b in level[i + 1:]:
                assert not (writes[a] & writes[b]), (
                    f"{a} and {b} share a wave but both write {writes[a] & writes[b]}"
                )


def test_sequential_order_is_the_exact_historic_sequence() -> None:
    # The non-PRO path MUST replay the historic order byte-for-byte.  Historically
    # live_ready ran LAST (after prediction_emission/self_schema), even though its
    # DAG level is earlier — the level order must NOT leak into sequential mode.
    assert cd._POST_MOTOR_SEQUENTIAL_ORDER == (
        "visual_consolidation",
        "longitudinal",
        "coordination",
        "life_model",
        "outcome_resolution",
        "life_model_v19",
        "prediction_emission",
        "self_schema",
        "live_ready",
    )
    # Same set as the DAG levels, but a DIFFERENT order (live_ready moved to tail).
    flat_levels = [n for lvl in cd._POST_MOTOR_STAGE_LEVELS for n in lvl]
    assert set(flat_levels) == set(cd._POST_MOTOR_SEQUENTIAL_ORDER)
    assert tuple(flat_levels) != cd._POST_MOTOR_SEQUENTIAL_ORDER


def test_sequential_scheduler_calls_stages_in_historic_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, db = _fresh_run(tmp_path, monkeypatch, "order")
    called: list[str] = []

    def make(name: str):
        def _fn() -> dict:
            called.append(name)
            return {"status": "completed", "stage": name}
        return _fn

    fns = {name: make(name) for name in cd._POST_MOTOR_SEQUENTIAL_ORDER}
    cd._run_post_motor_stages(
        run_id=run_id, stage_fns=fns, execution_lease=_FakeLease(), parallel=False
    )
    assert tuple(called) == cd._POST_MOTOR_SEQUENTIAL_ORDER


# --------------------------------------------------- scheduler non-regression ----
_STAGE_NAMES = list(cd._POST_MOTOR_SEQUENTIAL_ORDER)


class _FakeLease:
    """Heartbeat is a no-op; ``_run_post_motor_stages`` only calls heartbeat.

    ``acquired=False`` makes ``heartbeat_execution_lease`` return immediately.
    """

    acquired = False


def _make_stage_fns(db_path: Path, record: dict[str, list]):
    """Each fake stage opens its OWN db.connect() and writes one durable row into
    a per-stage table, mirroring the real stages' own-connection contract."""

    def make(name: str):
        def _fn() -> dict:
            # Each stage its OWN connection (proves separate connections + WAL).
            with connect(db_path) as con, write_transaction(con):
                con.execute(
                    f"CREATE TABLE IF NOT EXISTS stage_{name}"
                    "(k TEXT PRIMARY KEY, thread TEXT, journal TEXT)"
                )
                journal = con.execute("PRAGMA journal_mode").fetchone()[0]
                con.execute(
                    f"INSERT OR REPLACE INTO stage_{name} VALUES(?,?,?)",
                    (name, threading.current_thread().name, journal),
                )
            record.setdefault(name, []).append(threading.current_thread().name)
            time.sleep(0.02)  # give overlapping stages a chance to race
            return {"status": "completed", "stage": name, "journal": journal}

        return _fn

    return {name: make(name) for name in _STAGE_NAMES}


def _fresh_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str) -> tuple[str, Path]:
    db = tmp_path / f"{key}.db"
    monkeypatch.setenv("MLOMEGA_HOME", str(tmp_path))
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    ensure_v18_schema()
    run_id, _ = begin_or_resume_run(
        pipeline_name="close_day_parallel_test",
        scope=Scope(person_id="me", mode="maintenance"),
        input_manifest={"test": key},
        idempotency_key=f"parallel-test:{key}",
    )
    return run_id, db


def _written_rows(db: Path) -> dict[str, tuple]:
    rows: dict[str, tuple] = {}
    with sqlite3.connect(db) as con:
        for name in _STAGE_NAMES:
            cur = con.execute(f"SELECT k, journal FROM stage_{name}")
            rows[name] = tuple(sorted(cur.fetchall()))
    return rows


def test_parallel_scheduler_matches_sequential_written_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sequential run.
    seq_run, seq_db = _fresh_run(tmp_path, monkeypatch, "seq")
    seq_record: dict[str, list] = {}
    seq_results = cd._run_post_motor_stages(
        run_id=seq_run,
        stage_fns=_make_stage_fns(seq_db, seq_record),
        execution_lease=_FakeLease(),
        parallel=False,
    )
    # Parallel run from an equivalent fresh starting DB.
    par_run, par_db = _fresh_run(tmp_path, monkeypatch, "par")
    par_record: dict[str, list] = {}
    par_results = cd._run_post_motor_stages(
        run_id=par_run,
        stage_fns=_make_stage_fns(par_db, par_record),
        execution_lease=_FakeLease(),
        parallel=True,
    )

    # THE non-regression assertion: identical stage outputs and identical written
    # rows (only the recording thread name may differ).
    assert set(seq_results) == set(par_results) == set(_STAGE_NAMES)
    for name in _STAGE_NAMES:
        assert seq_results[name]["status"] == par_results[name]["status"] == "completed"
    assert _written_rows(seq_db) == _written_rows(par_db)


def test_wal_active_and_stages_use_separate_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, db = _fresh_run(tmp_path, monkeypatch, "wal")
    record: dict[str, list] = {}
    results = cd._run_post_motor_stages(
        run_id=run_id,
        stage_fns=_make_stage_fns(db, record),
        execution_lease=_FakeLease(),
        parallel=True,
    )
    # Every stage saw WAL journalling on its OWN connection.
    for name in _STAGE_NAMES:
        assert results[name]["journal"].lower() == "wal"


def test_a_multi_stage_level_actually_runs_on_multiple_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, db = _fresh_run(tmp_path, monkeypatch, "threads")
    record: dict[str, list] = {}
    cd._run_post_motor_stages(
        run_id=run_id,
        stage_fns=_make_stage_fns(db, record),
        execution_lease=_FakeLease(),
        parallel=True,
    )
    # Level 0 has three stages; a parallel wave must dispatch them on worker
    # threads (never all on the main thread).
    level0 = cd._POST_MOTOR_STAGE_LEVELS[0]
    worker_threads = {
        record[name][0]
        for name in level0
        if record[name][0].startswith("mlomega-closeday-stage")
    }
    assert len(worker_threads) >= 2, "a 3-stage level must use >=2 worker threads"


def test_parallel_stage_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, db = _fresh_run(tmp_path, monkeypatch, "fail")
    record: dict[str, list] = {}
    fns = _make_stage_fns(db, record)

    def _boom() -> dict:
        raise RuntimeError("stage exploded")

    fns["longitudinal"] = _boom  # a level-0 stage fails
    with pytest.raises(Exception):
        cd._run_post_motor_stages(
            run_id=run_id, stage_fns=fns, execution_lease=_FakeLease(), parallel=True
        )


# ------------------------------------------------------------- PRO gating ----
def test_stage_parallel_gated_off_without_pro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY", raising=False)
    assert cd._pro_closeday_parallel_stages() is False


def test_stage_parallel_on_under_pro_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.delenv("MLOMEGA_PRO_CLOSEDAY_STAGE_PARALLEL", raising=False)
    assert cd._pro_closeday_parallel_stages() is True


def test_stage_parallel_subflag_can_force_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY", "1")
    monkeypatch.setenv("MLOMEGA_PRO_CLOSEDAY_STAGE_PARALLEL", "0")
    assert cd._pro_closeday_parallel_stages() is False


# ---------------------------------------------------- Task 3: shared cache core ----
def test_global_fact_core_prefix_shares_one_digest_for_all_engines() -> None:
    # A common core shared by >=2 engines is placed in ONE shared prefix; the
    # digest must be identical no matter which engine rides it.
    common_core = [
        {"ref": "cap:ep1:0", "text": "user woke at 7am", "source_engine": "capture_engine"},
        {"ref": "ctx:ep1:1", "text": "at home kitchen", "source_engine": "context_resolver"},
    ]
    digests = set()
    for _engine in ("pattern_miner", "prediction_engine", "intervention_engine"):
        ctx = strict._pro_global_fact_core_prefix("conv-1", common_core)
        with ctx:
            from mlomega_audio_elite.cloud_providers_v19 import current_bundle_prefix

            prefix = current_bundle_prefix()
            assert prefix is not None
            assert prefix.bundle_id == "global-fact-core:conv-1"
            digests.add(prefix.digest)
    assert len(digests) == 1, "the shared core prefix must be byte-for-byte identical"


def test_global_fact_core_prefix_is_noop_without_common_core() -> None:
    from mlomega_audio_elite.cloud_providers_v19 import current_bundle_prefix

    with strict._pro_global_fact_core_prefix("conv-empty", []):
        # No common core => nullcontext => no prefix is set.
        assert current_bundle_prefix() is None


def test_warm_and_ride_use_identical_payload() -> None:
    # The warmed payload (what primes the cache) and the ridden prefix payload
    # (what the engines actually send) must be the same bytes so the digest hits.
    common_core = [{"ref": "x:1", "text": "abc", "source_engine": "capture_engine"}]
    warmed_payload = strict._global_fact_core_payload("conv-9", common_core)
    ctx = strict._pro_global_fact_core_prefix("conv-9", common_core)
    with ctx:
        from mlomega_audio_elite.cloud_providers_v19 import (
            cloud_bundle_prefix,
            current_bundle_prefix,
        )

        ridden = current_bundle_prefix()
        assert ridden is not None
        # Recompute the warm digest the same way cloud_bundle_prefix does.
        with cloud_bundle_prefix("global-fact-core:conv-9", warmed_payload) as warm_ctx:
            assert warm_ctx.digest == ridden.digest


# ------------------------------------------------- Task 2: fan-out widths / DAG ----
def test_fanout_widths_are_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The per-level wave starts at MLOMEGA_PRO_FANOUT_INITIAL and grows toward
    # MLOMEGA_CLOUD_MAX_IN_FLIGHT — prove both env knobs are honoured by the
    # source (they gate real concurrency, not a hard-coded small number).
    src = Path(strict.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("MLOMEGA_PRO_FANOUT_INITIAL", "4")' in src
    assert 'os.environ.get("MLOMEGA_CLOUD_MAX_IN_FLIGHT", "12")' in src
    # The wave doubles each pass (initial_width -> max_width), so a level with
    # many independent per-episode tasks ramps to the ceiling instead of staying
    # at the small initial width.
    assert "wave_width = min(max_width, wave_width * 2)" in src


def test_simulation_and_calibration_dependency_is_preserved() -> None:
    # SAFETY (fail-safe): the task asked whether simulation ∥ calibration can run
    # together.  The REAL DAG says calibration_engine depends on BOTH
    # prediction_engine AND simulation_engine, so they are NOT independent and must
    # stay sequenced — parallelising them would delete a real dependency.  This
    # guard fails loudly if anyone removes that edge.
    assert strict._ENGINE_DIRECT_DEPS["calibration_engine"] == (
        "prediction_engine", "simulation_engine",
    )
    assert strict._ENGINE_DIRECT_DEPS["simulation_engine"] == ("prediction_engine",)
    # intervention depends on calibration + prediction (chain tail), never on the
    # raw pattern/similar outputs.
    assert strict._ENGINE_DIRECT_DEPS["intervention_engine"] == (
        "calibration_engine", "prediction_engine",
    )


def test_global_fact_core_prefix_skips_when_core_too_big(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from mlomega_audio_elite.cloud_providers_v19 import current_bundle_prefix

    # A tiny ceiling forces the skip branch (parity with the warm's own skip).
    monkeypatch.setenv("MLOMEGA_PRO_WARM_MAX_TOKENS", "1")
    common_core = [
        {"ref": f"r{i}", "text": "some fact text " * 5, "source_engine": "capture_engine"}
        for i in range(20)
    ]
    with strict._pro_global_fact_core_prefix("conv-big", common_core):
        assert current_bundle_prefix() is None


def test_shared_core_prefix_pays_one_warm_for_all_global_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End-to-end: under the ONE shared global-fact-core prefix, the first engine
    # call buys the cache warm and every later engine call rides it — proving the
    # common core is a SHARED cache prefix, not re-warmed per engine.
    from mlomega_audio_elite import cloud_providers_v19 as cloud

    monkeypatch.setenv("MLOMEGA_DB", str(tmp_path / "cloud.db"))
    monkeypatch.setenv("MLOMEGA_CLOUD_MODE", "pro")
    monkeypatch.setenv("MLOMEGA_CLOUD_DAILY_BUDGET_EUR", "5")
    monkeypatch.setenv("MLOMEGA_CLOUD_ON_BUDGET", "stop")
    monkeypatch.setenv("MLOMEGA_CLOUD_USD_PER_EUR", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    cloud._BUNDLE_WARM_RESPONSES.clear()

    warms: list[dict] = []
    reals: list[dict] = []

    def fake_json_request(url, payload, **kwargs):
        # A warm-only request carries the warm prompt as its LAST user message and
        # never carries the engine prompt "TASK" (json_schema appends a trailing
        # system message, so we cannot rely on messages[-1]).
        user_contents = [
            m["content"] for m in payload["messages"] if m.get("role") == "user"
        ]
        is_warm = bool(user_contents) and user_contents[-1] == cloud._WARM_PROMPT
        if is_warm:
            warms.append(payload)
            content = '{"bundle_loaded":true}'
        else:
            reals.append(payload)
            content = '{"ok":true}'
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        }, 200, 0

    monkeypatch.setattr(cloud, "_json_request", fake_json_request)

    common_core = [
        {"ref": "cap:0", "text": "shared substrate", "source_engine": "capture_engine"},
    ]
    with strict._pro_global_fact_core_prefix("conv-e2e", common_core):
        for _engine in ("pattern_miner", "prediction_engine", "intervention_engine"):
            cloud.deepseek_chat_json(
                system="ENGINE", prompt="TASK", json_schema={"type": "object"},
                max_output_tokens=32, timeout=5,
            )

    assert len(reals) == 3, "each global engine still makes its own real call"
    assert len(warms) == 1, "the shared core prefix is warmed exactly once"
    # Every real call carried the identical canonical core prefix as message[1].
    prefixes = {payload["messages"][1]["content"] for payload in reals}
    assert len(prefixes) == 1, "all engines share one byte-for-byte core prefix"
