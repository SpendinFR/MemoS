"""CHANTIER 2 — the engine fan-out reaches real concurrency (max_concurrent >= 2).

Uses the SAME primitives the production fan-out uses in
``build_strict_v13_for_conversation``: a ``ThreadPoolExecutor`` wave, ``copy_context``
so each worker carries the exact bundle-prefix ContextVar, its own ``db.connect()``
connection, and one ``_run_engine_partitioned`` call per (episode, engine).  A
concurrency-measuring fake window_llm proves at least two engine calls overlap.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from pathlib import Path

import pytest

from mlomega_audio_elite.brain2_strict_v13_2 import _run_engine_partitioned
from mlomega_audio_elite.cloud_providers_v19 import cloud_bundle_prefix
from mlomega_audio_elite.night_orchestrator import LLMCallResult


class _ConcurrencyLLM:
    """A fake window LLM that records the peak number of overlapping calls."""

    model = "fake-concurrency-llm"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_concurrent = 0

    def generate(self, prompt, *, output_budget):
        with self._lock:
            self.active += 1
            self.max_concurrent = max(self.max_concurrent, self.active)
        try:
            time.sleep(0.05)  # hold the slot so overlaps are observable
            fields = list(prompt.get("schema_hint") or {})
            data = {}
            for field in fields:
                if field == "confidence":
                    data[field] = 0.8
                elif field in {"evidence", "counter_evidence", "secondary_emotions",
                               "thought_hypotheses", "state_transitions"}:
                    data[field] = [field]
                else:
                    data[field] = {"field": field}
            return LLMCallResult(ok=True, data=data)
        finally:
            with self._lock:
                self.active -= 1


def test_engine_fanout_runs_at_least_two_calls_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "fanout.db"
    monkeypatch.setenv("MLOMEGA_DB", str(db))
    with sqlite3.connect(db) as seed:
        seed.execute("CREATE TABLE episodes(episode_id TEXT PRIMARY KEY,start_time TEXT)")
        for i in range(4):
            seed.execute(
                "INSERT INTO episodes VALUES(?,?)",
                (f"ep{i}", "2026-07-12T10:00:00+00:00"),
            )
        seed.commit()

    llm = _ConcurrencyLLM()

    tasks = [
        {"episode_id": f"ep{i}", "engine": "capture_engine", "bundle": {"episode": {"episode_id": f"ep{i}"}}}
        for i in range(4)
    ]

    def run_engine_task(task):
        # Mirrors the production worker: own connection + exact prefix ContextVar.
        with sqlite3.connect(db) as worker_con:
            worker_con.row_factory = sqlite3.Row
            with cloud_bundle_prefix(str(task["episode_id"]), dict(task["bundle"])):
                return _run_engine_partitioned(
                    worker_con,
                    engine=str(task["engine"]),
                    episode_id=str(task["episode_id"]),
                    person_id="me",
                    bundle=task["bundle"],
                    prior={},
                    window_llm=llm,
                    context_window=16000,
                    output_budget=1000,
                )

    results = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="test-pro-engine") as pool:
        futures = {}
        for task in tasks:
            context = copy_context()
            fut = pool.submit(context.run, run_engine_task, task)
            futures[fut] = task["episode_id"]
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()

    assert len(results) == 4
    assert llm.max_concurrent >= 2, "PRO engine fan-out must run engines concurrently"
