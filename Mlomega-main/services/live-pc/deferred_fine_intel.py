from __future__ import annotations

"""Durable, batched fine-intelligence boundary for the PhoneOnly live path.

Raw/final turns must become durable immediately.  The former E38 wiring then paid
two synchronous LLM requests for *every* turn before BrainLive ingestion could
finish.  This queue stores the exact turn/context first and extracts addressed
names plus heard attribute facts once for a bounded batch.  Extraction and writer
checkpoints are separate so a crash never repays a completed model request and
source-addressed writers remain idempotent.
"""

import json
import importlib.util
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mlomega_audio_elite.db import connect, write_transaction


_SYSTEM = (
    "Analyze each ordered conversation turn independently. For every supplied "
    "turn_id, return exactly one result with the same turn_id. Extract two generic "
    "signals without guessing: (1) whether a physically present person is explicitly "
    "named/addressed; (2) whether the turn states a factual attribute/value about a "
    "present thing or the current place. Empty strings mean absent. Do not infer "
    "personality, emotion, routines, or unstated names. Return strict JSON only."
)

_SCHEMA = {
    "turns": [
        {
            "turn_id": "string",
            "addressed": False,
            "name": "string",
            "addressee": "previous_speaker|current_speaker|unknown",
            "address_confidence": 0.0,
            "states_fact": False,
            "subject_hint": "string",
            "attribute": "string",
            "value": "string",
            "fact_confidence": 0.0,
        }
    ]
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pro_cloud_fine_intel_enabled() -> bool:
    return (
        os.environ.get("MLOMEGA_PRO_CLOSEDAY", "0").strip().lower()
        in {"1", "true", "yes", "on"}
        and os.environ.get("MLOMEGA_PRO_FINE_INTEL_CLOUD", "1").strip().lower()
        not in {"0", "false", "no", "off"}
    )


class _FineIntelClientAdapter:
    """Strict fine-intel client with an explicit phase-owned backend."""

    def __init__(self, *, cloud: bool | None = None) -> None:
        from mlomega_audio_elite.config import get_settings
        from mlomega_audio_elite.llm import OllamaJsonClient

        use_cloud = _pro_cloud_fine_intel_enabled() if cloud is None else bool(cloud)
        if use_cloud:
            self.client = OllamaJsonClient(
                backend="deepseek",
                model=os.environ.get("MLOMEGA_DEEPSEEK_MODEL")
                or "deepseek-v4-flash",
            )
        else:
            settings = get_settings()
            self.client = OllamaJsonClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_live_model,
                backend="ollama",
            )

    def complete_json(
        self,
        system,
        user,
        *,
        schema_hint=None,
        timeout=None,
        max_output_tokens=None,
    ):
        if str(getattr(self.client, "backend", "")) == "deepseek":
            from mlomega_audio_elite.cloud_providers_v19 import cloud_engine_stage

            stage_context: Any = cloud_engine_stage("post_stop_fine_intel")
        else:
            from contextlib import nullcontext

            stage_context = nullcontext()
        with stage_context:
            return self.client.require_json(
                system,
                user,
                schema_hint=schema_hint,
                timeout=float(timeout or 60.0),
                max_output_tokens=max_output_tokens,
            )


def build_fine_intel_llm(*, cloud: bool | None = None) -> Any:
    """Factory shared by live finalization and crash recovery."""
    return _FineIntelClientAdapter(cloud=cloud)


class DeferredFineIntel:
    """Persist and process E38 turn analysis in bounded, replay-safe batches."""

    def __init__(
        self,
        *,
        person_id: str,
        live_session_id: str,
        db_path: str | Path | None,
        llm: Any,
        hypothesis_engine: Any,
        attribute_memory: Any,
        subject_resolver: Callable[[str | None], str | None] | None = None,
        batch_size: int = 8,
        max_attempts: int = 3,
        max_output_tokens: int = 4096,
    ) -> None:
        self.person_id = person_id or "me"
        self.live_session_id = str(live_session_id)
        self.db_path = Path(db_path) if db_path is not None else None
        self.llm = llm
        self.hypothesis_engine = hypothesis_engine
        self.attribute_memory = attribute_memory
        self.subject_resolver = subject_resolver
        self.batch_size = max(1, int(batch_size))
        self.max_attempts = max(1, int(max_attempts))
        self.max_output_tokens = max(256, int(max_output_tokens))
        self._metrics_lock = threading.Lock()
        self.metrics: dict[str, int] = {
            "enqueued": 0,
            "model_calls": 0,
            "turns_extracted": 0,
            "turns_applied": 0,
            "reused_extractions": 0,
            "contract_rejections": 0,
            "batch_splits": 0,
            "singleton_id_rebinds": 0,
            "failures": 0,
        }
        self._ensure_schema()

    def _metric_add(self, name: str, amount: int = 1) -> None:
        with self._metrics_lock:
            self.metrics[name] += int(amount)

    def _parallel_workers(self) -> int:
        client = getattr(self.llm, "client", self.llm)
        if not _pro_cloud_fine_intel_enabled() or str(
            getattr(client, "backend", "")
        ).strip().lower() != "deepseek":
            return 1
        try:
            return max(
                1,
                min(
                    8,
                    int(os.environ.get("MLOMEGA_PRO_FINE_INTEL_WORKERS", "6")),
                ),
            )
        except ValueError:
            return 6

    def _connect(self):
        return connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS live_fine_intel_queue_v19(
                    turn_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    live_session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    input_digest TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    extracted_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_live_fine_intel_pending_v19
                    ON live_fine_intel_queue_v19(person_id, live_session_id, status, created_at, turn_id);
                CREATE TABLE IF NOT EXISTS live_fine_intel_rejections_v19(
                    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL,
                    live_session_id TEXT NOT NULL,
                    expected_turn_ids_json TEXT NOT NULL,
                    observed_turn_ids_json TEXT NOT NULL,
                    raw_output_json TEXT,
                    error_text TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_live_fine_intel_rejections_session_v19
                    ON live_fine_intel_rejections_v19(person_id, live_session_id, rejection_id);
                """
            )

    def enqueue_turn(
        self,
        *,
        turn_id: str,
        text: str,
        speaker_entity: str | None,
        present_person_entities: Sequence[str] | None,
        default_subject: str | None,
        evidence_ref: str | None = None,
    ) -> bool:
        import hashlib

        payload = {
            "turn_id": str(turn_id),
            "text": str(text or "").strip(),
            "speaker_entity": speaker_entity,
            "present_person_entities": list(dict.fromkeys(present_person_entities or [])),
            "default_subject": default_subject,
            "evidence_ref": evidence_ref or f"brainlive_turn:{turn_id}",
        }
        if not payload["turn_id"] or not payload["text"]:
            return False
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._connect() as con, write_transaction(con):
            cur = con.execute(
                """INSERT OR IGNORE INTO live_fine_intel_queue_v19(
                       turn_id,person_id,live_session_id,payload_json,input_digest,status,created_at)
                   VALUES(?,?,?,?,?,'pending',?)""",
                (payload["turn_id"], self.person_id, self.live_session_id, raw, digest, _now()),
            )
        inserted = bool(cur.rowcount)
        if inserted:
            self._metric_add("enqueued")
        return inserted

    def pending_count(self) -> int:
        with self._connect() as con:
            row = con.execute(
                """SELECT COUNT(*) AS n FROM live_fine_intel_queue_v19
                   WHERE person_id=? AND live_session_id=? AND status<>'completed'""",
                (self.person_id, self.live_session_id),
            ).fetchone()
        return int(row["n"] if row else 0)

    def process_pending(self, *, max_batches: int | None = None) -> dict[str, Any]:
        """Drain extracted rows first, then pay at most one LLM call per batch."""
        workers = self._parallel_workers()
        if workers > 1:
            return self._process_pending_parallel(
                workers=workers, max_batches=max_batches
            )
        batches = 0
        while max_batches is None or batches < max_batches:
            extracted = self._load_rows("extracted", self.batch_size)
            if extracted:
                self._metric_add("reused_extractions", len(extracted))
                self._apply_rows(extracted)
                continue

            pending = self._load_rows("pending", self.batch_size, attempts_lt=self.max_attempts)
            if not pending:
                break
            batches += 1
            self._extract_batch(pending)
            self._apply_rows(self._load_rows_by_ids([str(r["turn_id"]) for r in pending]))

        remaining = self.pending_count()
        return {
            "status": "completed" if remaining == 0 else "pending",
            "remaining": remaining,
            "metrics": dict(self.metrics),
        }

    def _process_pending_parallel(
        self, *, workers: int, max_batches: int | None
    ) -> dict[str, Any]:
        """PRO-only parallel extraction; deterministic writers stay serialized."""
        batches = 0
        while max_batches is None or batches < max_batches:
            extracted = self._load_rows(
                "extracted", self.batch_size * max(1, workers)
            )
            if extracted:
                self._metric_add("reused_extractions", len(extracted))
                self._apply_rows(extracted)
                continue

            remaining_batches = (
                workers
                if max_batches is None
                else min(workers, max(0, int(max_batches) - batches))
            )
            if remaining_batches <= 0:
                break
            pending = self._load_rows(
                "pending",
                self.batch_size * remaining_batches,
                attempts_lt=self.max_attempts,
            )
            if not pending:
                break
            groups = [
                pending[index:index + self.batch_size]
                for index in range(0, len(pending), self.batch_size)
            ]
            batches += len(groups)
            errors: list[Exception] = []
            with ThreadPoolExecutor(
                max_workers=min(workers, len(groups)),
                thread_name_prefix="mlomega-pro-fine-intel",
            ) as pool:
                futures = {
                    pool.submit(self._extract_batch, group): group
                    for group in groups
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        errors.append(exc)
            ordered_ids = [str(row["turn_id"]) for row in pending]
            self._apply_rows(self._load_rows_by_ids(ordered_ids))
            if errors:
                raise errors[0]

        remaining = self.pending_count()
        return {
            "status": "completed" if remaining == 0 else "pending",
            "remaining": remaining,
            "metrics": dict(self.metrics),
            "parallel_workers": workers,
        }

    def _load_rows(
        self, status: str, limit: int, *, attempts_lt: int | None = None
    ) -> list[Mapping[str, Any]]:
        clause = " AND attempts<?" if attempts_lt is not None else ""
        params: list[Any] = [self.person_id, self.live_session_id, status]
        if attempts_lt is not None:
            params.append(int(attempts_lt))
        params.append(int(limit))
        with self._connect() as con:
            return list(
                con.execute(
                    """SELECT * FROM live_fine_intel_queue_v19
                       WHERE person_id=? AND live_session_id=? AND status=?"""
                    + clause
                    + " ORDER BY created_at,turn_id LIMIT ?",
                    tuple(params),
                ).fetchall()
            )

    def _load_rows_by_ids(self, turn_ids: Sequence[str]) -> list[Mapping[str, Any]]:
        if not turn_ids:
            return []
        marks = ",".join("?" for _ in turn_ids)
        with self._connect() as con:
            rows = con.execute(
                f"SELECT * FROM live_fine_intel_queue_v19 WHERE turn_id IN ({marks})",
                tuple(turn_ids),
            ).fetchall()
        by_id = {str(row["turn_id"]): row for row in rows}
        return [by_id[turn_id] for turn_id in turn_ids if turn_id in by_id]

    def _save_extracted(
        self,
        by_id: Mapping[str, Mapping[str, Any]],
        expected: Sequence[str],
    ) -> None:
        if not expected:
            return
        extracted_at = _now()
        with self._connect() as con, write_transaction(con):
            for turn_id in expected:
                con.execute(
                    """UPDATE live_fine_intel_queue_v19
                       SET status='extracted',result_json=?,attempts=attempts+1,
                           last_error=NULL,extracted_at=? WHERE turn_id=?""",
                    (
                        json.dumps(by_id[turn_id], ensure_ascii=False, sort_keys=True),
                        extracted_at,
                        turn_id,
                    ),
                )
        self._metric_add("turns_extracted", len(expected))

    def _record_contract_rejection(
        self,
        *,
        expected: Sequence[str],
        observed: Sequence[str],
        result: Any,
        error_text: str,
        strategy: str,
    ) -> None:
        try:
            raw = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            raw = repr(result)
        with self._connect() as con, write_transaction(con):
            con.execute(
                """INSERT INTO live_fine_intel_rejections_v19(
                       person_id,live_session_id,expected_turn_ids_json,
                       observed_turn_ids_json,raw_output_json,error_text,strategy,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    self.person_id,
                    self.live_session_id,
                    json.dumps(list(expected), ensure_ascii=False),
                    json.dumps(list(observed), ensure_ascii=False),
                    raw[:200000],
                    error_text[:1000],
                    strategy,
                    _now(),
                ),
            )
        self._metric_add("contract_rejections")

    def _mark_failed(self, rows: Sequence[Mapping[str, Any]], exc: Exception) -> None:
        self._metric_add("failures")
        with self._connect() as con, write_transaction(con):
            for row in rows:
                con.execute(
                    """UPDATE live_fine_intel_queue_v19
                       SET attempts=attempts+1,last_error=? WHERE turn_id=?""",
                    (f"{type(exc).__name__}: {str(exc)[:500]}", str(row["turn_id"])),
                )

    def _extract_batch(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        singleton_retry: int = 0,
    ) -> None:
        """Extract a batch losslessly, splitting only contract-mismatched rows.

        A small model can omit or mutate one opaque ``turn_id`` even when the
        semantic JSON is otherwise valid.  Failing the whole durable drain made
        CloseDay impossible (Gate B 20260718-112417).  Exact-ID results are now
        checkpointed immediately; unresolved rows are bisected down to a singleton.
        With one input and one output, rebinding the sole opaque ID is deterministic
        and cannot associate the semantics with another turn.  Zero/multiple
        singleton outputs remain a hard, audited failure after bounded retries.
        """
        if not rows:
            return
        payloads = [json.loads(str(row["payload_json"])) for row in rows]
        prompt = json.dumps(
            {"turns": [{"turn_id": p["turn_id"], "text": p["text"]} for p in payloads]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        system = _SYSTEM
        if len(payloads) == 1:
            system += (
                " CRITICAL SINGLE-TURN CONTRACT: return exactly one turns item and "
                f"copy this turn_id byte-for-byte: {payloads[0]['turn_id']}."
            )
        try:
            self._metric_add("model_calls")
            result = self.llm.complete_json(
                system,
                prompt,
                schema_hint=_SCHEMA,
                max_output_tokens=self.max_output_tokens,
            )
        except Exception as exc:
            self._mark_failed(rows, exc)
            raise

        expected = [str(p["turn_id"]) for p in payloads]
        items = result.get("turns") if isinstance(result, Mapping) else None
        mappings = [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []
        observed = [str(item.get("turn_id") or "") for item in mappings]
        counts = {turn_id: observed.count(turn_id) for turn_id in set(observed) if turn_id}
        by_id = {
            turn_id: item
            for turn_id, item in ((str(item.get("turn_id") or ""), item) for item in mappings)
            if turn_id in expected and counts.get(turn_id) == 1
        }

        exact = (
            isinstance(items, list)
            and len(items) == len(expected)
            and set(by_id) == set(expected)
        )
        if exact:
            self._save_extracted(by_id, expected)
            return

        missing = [turn_id for turn_id in expected if turn_id not in by_id]
        unexpected = sorted({turn_id for turn_id in observed if turn_id and turn_id not in expected})
        duplicates = sorted(turn_id for turn_id, count in counts.items() if count > 1)
        error_text = (
            "fine-intel batch contract mismatch: "
            f"missing={missing}, unexpected={unexpected}, duplicates={duplicates}, "
            f"non_objects={(len(items) - len(mappings)) if isinstance(items, list) else 'no_turns_array'}"
        )

        # One input + one semantic object has only one possible provenance.  The
        # model merely corrupted an opaque identifier; repair it deterministically.
        if len(expected) == 1 and isinstance(items, list) and len(mappings) == 1 and len(items) == 1:
            fixed = dict(mappings[0])
            fixed["turn_id"] = expected[0]
            self._record_contract_rejection(
                expected=expected,
                observed=observed,
                result=result,
                error_text=error_text,
                strategy="singleton_id_rebind",
            )
            self._metric_add("singleton_id_rebinds")
            self._save_extracted({expected[0]: fixed}, expected)
            return

        # Preserve every unambiguous exact-ID result; only unresolved turns are
        # repaid.  This is lossless and cheaper than throwing away a valid prefix.
        matched = [turn_id for turn_id in expected if turn_id in by_id]
        if matched:
            self._save_extracted(by_id, matched)
        unresolved = [row for row in rows if str(row["turn_id"]) not in by_id]
        strategy = "split_unresolved" if len(unresolved) > 1 else "retry_singleton"
        self._record_contract_rejection(
            expected=expected,
            observed=observed,
            result=result,
            error_text=error_text,
            strategy=strategy,
        )

        if len(unresolved) > 1:
            self._metric_add("batch_splits")
            mid = len(unresolved) // 2
            self._extract_batch(unresolved[:mid])
            self._extract_batch(unresolved[mid:])
            return
        if len(unresolved) == 1 and singleton_retry + 1 < self.max_attempts:
            self._extract_batch(unresolved, singleton_retry=singleton_retry + 1)
            return

        exc = ValueError(error_text)
        self._mark_failed(unresolved or rows, exc)
        raise exc

    def _apply_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            if str(row["status"]) != "extracted" or not row["result_json"]:
                continue
            payload = json.loads(str(row["payload_json"]))
            result = json.loads(str(row["result_json"]))
            evidence_ref = str(payload.get("evidence_ref") or f"brainlive_turn:{row['turn_id']}")

            if self.hypothesis_engine is not None:
                self.hypothesis_engine.apply_addressed_name_signal(
                    {
                        "addressed": bool(result.get("addressed")),
                        "name": str(result.get("name") or ""),
                        "addressee": str(result.get("addressee") or "unknown"),
                        "confidence": result.get("address_confidence", 0.0),
                    },
                    session=self.live_session_id,
                    speaker_entity=payload.get("speaker_entity"),
                    present_person_entities=payload.get("present_person_entities") or [],
                    evidence_ref=evidence_ref,
                )

            if self.attribute_memory is not None:
                self.attribute_memory.apply_heard_fact(
                    {
                        "states_fact": bool(result.get("states_fact")),
                        "subject_hint": str(result.get("subject_hint") or ""),
                        "attribute": str(result.get("attribute") or ""),
                        "value": str(result.get("value") or ""),
                        "confidence": result.get("fact_confidence", 0.0),
                    },
                    session=self.live_session_id,
                    subject_resolver=self.subject_resolver,
                    default_subject=payload.get("default_subject"),
                    evidence_ref=evidence_ref,
                )

            with self._connect() as con, write_transaction(con):
                con.execute(
                    """UPDATE live_fine_intel_queue_v19
                       SET status='completed',completed_at=?,last_error=NULL WHERE turn_id=?""",
                    (_now(), str(row["turn_id"])),
                )
            self._metric_add("turns_applied")


__all__ = ["DeferredFineIntel", "build_fine_intel_llm"]


def _load_service_sibling(name: str, filename: str):
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(name, here / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load live service module {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def process_deferred_fine_intel_backlog(
    *,
    person_id: str,
    live_session_id: str,
    db_path: str | Path | None = None,
    llm: Any = None,
) -> dict[str, Any]:
    """Recovery/CloseDay entrypoint independent from the live pipeline object."""

    class _CoreClientAdapter:
        def __init__(self) -> None:
            from mlomega_audio_elite.config import get_settings
            from mlomega_audio_elite.llm import OllamaJsonClient

            # Fine-intel is LIVE-tier semantics (Ollama 4B). Under the
            # process-wide llamacpp backend a default client would target the
            # stopped P1 server, or 404 the P1 alias against Ollama (proven on
            # Gate B 20260717-115157). Force the Ollama backend explicitly AND
            # pin the base URL (11434) + the LIVE 4B model. Gate B #5: recovery
            # runs inside the ``post_stop_fine_intel`` phase wrapper, so without an
            # explicit model the client would otherwise pick the post-stop 9B by
            # phase — the live batch must stay on the 4B it was enqueued for.
            settings = get_settings()
            self.client = OllamaJsonClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_live_model,
                backend="ollama",
            )

        def complete_json(
            self,
            system,
            user,
            *,
            schema_hint=None,
            timeout=None,
            max_output_tokens=None,
        ):
            return self.client.require_json(
                system,
                user,
                schema_hint=schema_hint,
                timeout=float(timeout or 60.0),
                max_output_tokens=max_output_tokens,
            )

    world_mod = _load_service_sibling("v19_recovery_worldbrain", "worldbrain.py")
    hyp_mod = _load_service_sibling("v19_recovery_hypothesis_engine", "hypothesis_engine.py")
    attr_mod = _load_service_sibling("v19_recovery_attribute_memory", "attribute_memory.py")
    world = world_mod.WorldBrain(
        person_id=person_id,
        live_session_id=live_session_id,
        db_path=db_path,
        service_db_path=db_path,
        publish_world_state=False,
    )
    hypothesis = hyp_mod.HypothesisEngine(
        person_id=person_id,
        llm=None,
        worldbrain=world,
        db_path=db_path,
        service_db_path=db_path,
    )
    attributes = attr_mod.AttributeMemory(
        person_id=person_id,
        worldbrain=world,
        llm=None,
        service_db_path=db_path,
    )
    processor = DeferredFineIntel(
        person_id=person_id,
        live_session_id=live_session_id,
        db_path=db_path,
        llm=llm or build_fine_intel_llm(),
        hypothesis_engine=hypothesis,
        attribute_memory=attributes,
        batch_size=int(__import__("os").environ.get("MLOMEGA_LIVE_FINE_INTEL_BATCH", "8")),
        max_output_tokens=int(
            __import__("os").environ.get("MLOMEGA_LIVE_FINE_INTEL_MAX_OUTPUT_TOKENS", "4096")
        ),
    )
    # Recovery drain is post-stop work: without the phase marker the client
    # would use the live num_ctx (4096) and truncate the batched request.
    try:
        from mlomega_audio_elite.runtime_v18_7 import phase
    except Exception:
        return processor.process_pending()
    with phase("post_stop_fine_intel"):
        return processor.process_pending()


__all__.append("process_deferred_fine_intel_backlog")
