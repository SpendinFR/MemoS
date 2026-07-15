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
import sys
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
        self.metrics: dict[str, int] = {
            "enqueued": 0,
            "model_calls": 0,
            "turns_extracted": 0,
            "turns_applied": 0,
            "reused_extractions": 0,
            "failures": 0,
        }
        self._ensure_schema()

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
            self.metrics["enqueued"] += 1
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
        batches = 0
        while max_batches is None or batches < max_batches:
            extracted = self._load_rows("extracted", self.batch_size)
            if extracted:
                self.metrics["reused_extractions"] += len(extracted)
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

    def _extract_batch(self, rows: Sequence[Mapping[str, Any]]) -> None:
        payloads = [json.loads(str(row["payload_json"])) for row in rows]
        prompt = json.dumps(
            {"turns": [{"turn_id": p["turn_id"], "text": p["text"]} for p in payloads]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            result = self.llm.complete_json(
                _SYSTEM,
                prompt,
                schema_hint=_SCHEMA,
                max_output_tokens=self.max_output_tokens,
            )
            self.metrics["model_calls"] += 1
            items = result.get("turns") if isinstance(result, Mapping) else None
            if not isinstance(items, list):
                raise ValueError("fine-intel batch result has no turns array")
            expected = [str(p["turn_id"]) for p in payloads]
            by_id: dict[str, Mapping[str, Any]] = {}
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError("fine-intel batch contains a non-object result")
                turn_id = str(item.get("turn_id") or "")
                if not turn_id or turn_id in by_id:
                    raise ValueError("fine-intel batch has missing/duplicate turn_id")
                by_id[turn_id] = item
            if set(by_id) != set(expected):
                raise ValueError("fine-intel batch output cardinality/IDs do not match input")

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
            self.metrics["turns_extracted"] += len(expected)
        except Exception as exc:
            self.metrics["failures"] += 1
            with self._connect() as con, write_transaction(con):
                for row in rows:
                    con.execute(
                        """UPDATE live_fine_intel_queue_v19
                           SET attempts=attempts+1,last_error=? WHERE turn_id=?""",
                        (f"{type(exc).__name__}: {str(exc)[:500]}", str(row["turn_id"])),
                    )
            raise

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
            self.metrics["turns_applied"] += 1


__all__ = ["DeferredFineIntel"]


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
            from mlomega_audio_elite.llm import OllamaJsonClient

            self.client = OllamaJsonClient()

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
        llm=llm or _CoreClientAdapter(),
        hypothesis_engine=hypothesis,
        attribute_memory=attributes,
        batch_size=int(__import__("os").environ.get("MLOMEGA_LIVE_FINE_INTEL_BATCH", "8")),
        max_output_tokens=int(
            __import__("os").environ.get("MLOMEGA_LIVE_FINE_INTEL_MAX_OUTPUT_TOKENS", "4096")
        ),
    )
    return processor.process_pending()


__all__.append("process_deferred_fine_intel_backlog")
