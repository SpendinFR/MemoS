"""E64-C durable checkpoints - night_llm_windows_v19 / _window_outputs_v19.

Every window the executor runs is checkpointed so a kill/restart resumes the
incomplete window WITHOUT replaying the validated ones and WITHOUT doubling
outputs. The idempotent key is a hash of
``(person, day, stage, input_digest, window_index, adapter_version,
prompt_version, model)`` - if any of those change (new adapter, new prompt, new
model, different input) it is a genuinely different unit of work and gets its own
row. Table names are frozen by the E64-C ADR in docs/DECISIONS.md.

This module ONLY manages the checkpoint tables. It never touches a business table
and applies no partial output (the executor decides what to persist as an output
row, and only for validated windows).
"""

from __future__ import annotations

import json
from typing import Any

from ..utils import now_iso, sha256_bytes

WINDOWS_TABLE = "night_llm_windows_v19"
OUTPUTS_TABLE = "night_llm_window_outputs_v19"
CALLS_TABLE = "night_llm_call_telemetry_v19"
REJECTIONS_TABLE = "night_llm_contract_rejections_v19"

# Terminal-ish states. Only "completed" and "quarantined" are durable end states
# the executor skips on resume; "planned"/"running"/"error" are re-attempted.
STATE_PLANNED = "planned"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_QUARANTINED = "quarantined"
STATE_ERROR = "error"
# A window that was split into sub-windows; the children carry the real work.
# It is not a leaf: resume re-enters it and re-drives its (checkpointed) children
# without calling the LLM for the parent again.
STATE_SUBDIVIDED = "subdivided"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {WINDOWS_TABLE}(
  window_key TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  window_index INTEGER NOT NULL,
  adapter_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER,
  output_budget INTEGER,
  error_text TEXT,
  output_digest TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_{WINDOWS_TABLE}_scope
  ON {WINDOWS_TABLE}(person_id, package_date, stage_name);
CREATE TABLE IF NOT EXISTS {OUTPUTS_TABLE}(
  window_key TEXT NOT NULL,
  output_digest TEXT NOT NULL,
  output_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(window_key, output_digest)
);
CREATE TABLE IF NOT EXISTS {CALLS_TABLE}(
  call_id TEXT PRIMARY KEY,
  window_key TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  model TEXT NOT NULL,
  why_called_json TEXT NOT NULL,
  facts_read_json TEXT NOT NULL,
  facts_produced_json TEXT NOT NULL,
  cache_hit INTEGER NOT NULL DEFAULT 0,
  estimated_input_tokens INTEGER,
  provider_input_tokens INTEGER,
  provider_output_tokens INTEGER,
  output_budget INTEGER,
  latency_ms INTEGER,
  outcome TEXT NOT NULL,
  finish_reason TEXT,
  error_kind TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{CALLS_TABLE}_scope
  ON {CALLS_TABLE}(person_id, package_date, stage_name, created_at);
CREATE TABLE IF NOT EXISTS {REJECTIONS_TABLE}(
  rejection_id TEXT PRIMARY KEY,
  window_key TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  person_id TEXT NOT NULL,
  package_date TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  model TEXT NOT NULL,
  strategy TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  output_digest TEXT NOT NULL,
  raw_output TEXT,
  parsed_output_json TEXT,
  violations_json TEXT NOT NULL,
  finish_reason TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{REJECTIONS_TABLE}_window
  ON {REJECTIONS_TABLE}(window_key, created_at);
CREATE INDEX IF NOT EXISTS idx_{REJECTIONS_TABLE}_digests
  ON {REJECTIONS_TABLE}(window_key, input_digest, output_digest);
"""


def ensure_schema(con: Any) -> None:
    con.executescript(_SCHEMA)


def window_key(
    *,
    person_id: str,
    package_date: str,
    stage_name: str,
    input_digest: str,
    window_index: int,
    adapter_version: str,
    prompt_version: str,
    model: str,
) -> str:
    """Deterministic idempotent key. Independent of any LLM attempt/output."""
    payload = "|".join(
        [
            person_id,
            package_date,
            stage_name,
            input_digest,
            str(window_index),
            adapter_version,
            prompt_version,
            model,
        ]
    )
    return "nlw_" + sha256_bytes(payload.encode("utf-8"))[:24]


def get_window(con: Any, key: str) -> dict[str, Any] | None:
    cur = con.execute(
        f"SELECT * FROM {WINDOWS_TABLE} WHERE window_key=?", (key,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def is_done(con: Any, key: str) -> bool:
    """True if this window reached a durable end state (skip on resume)."""
    row = get_window(con, key)
    return bool(row) and row["state"] in (STATE_COMPLETED, STATE_QUARANTINED)


def upsert_window(
    con: Any,
    *,
    key: str,
    person_id: str,
    package_date: str,
    stage_name: str,
    input_digest: str,
    window_index: int,
    adapter_version: str,
    prompt_version: str,
    model: str,
    state: str,
    input_tokens: int | None = None,
    output_budget: int | None = None,
) -> None:
    """Create the checkpoint row if absent; otherwise update its state.

    Creating never resets ``attempts``; the executor bumps attempts explicitly
    via ``bump_attempt``. This keeps resume idempotent.
    """
    now = now_iso()
    existing = get_window(con, key)
    if existing is None:
        con.execute(
            f"""INSERT INTO {WINDOWS_TABLE}(
                  window_key, person_id, package_date, stage_name, input_digest,
                  window_index, adapter_version, prompt_version, model, state,
                  attempts, input_tokens, output_budget, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)""",
            (
                key, person_id, package_date, stage_name, input_digest,
                window_index, adapter_version, prompt_version, model, state,
                input_tokens, output_budget, now, now,
            ),
        )
    else:
        con.execute(
            f"""UPDATE {WINDOWS_TABLE}
                SET state=?, input_tokens=COALESCE(?, input_tokens),
                    output_budget=COALESCE(?, output_budget), updated_at=?
                WHERE window_key=?""",
            (state, input_tokens, output_budget, now, key),
        )


def bump_attempt(con: Any, key: str) -> int:
    con.execute(
        f"UPDATE {WINDOWS_TABLE} SET attempts=attempts+1, updated_at=? WHERE window_key=?",
        (now_iso(), key),
    )
    row = get_window(con, key)
    return int(row["attempts"]) if row else 0


def mark_state(
    con: Any, key: str, state: str, *, error_text: str | None = None,
    output_digest: str | None = None,
) -> None:
    now = now_iso()
    completed = now if state in (STATE_COMPLETED, STATE_QUARANTINED) else None
    con.execute(
        f"""UPDATE {WINDOWS_TABLE}
            SET state=?, error_text=?, output_digest=COALESCE(?, output_digest),
                updated_at=?, completed_at=COALESCE(?, completed_at)
            WHERE window_key=?""",
        (state, error_text, output_digest, now, completed, key),
    )


def record_output(con: Any, key: str, output: Any) -> str:
    """Persist a VALIDATED window output (idempotent by digest). Returns digest."""
    from .evidence_ref import content_digest

    digest = content_digest(output)
    con.execute(
        f"""INSERT OR IGNORE INTO {OUTPUTS_TABLE}(
              window_key, output_digest, output_json, created_at)
            VALUES(?,?,?,?)""",
        (key, digest, json.dumps(output, ensure_ascii=False, sort_keys=True, default=str), now_iso()),
    )
    return digest


def record_call_telemetry(
    con: Any,
    *,
    window_key: str,
    attempt: int,
    person_id: str,
    package_date: str,
    stage_name: str,
    model: str,
    why_called: Any,
    facts_read: Any,
    facts_produced: Any,
    cache_hit: bool,
    estimated_input_tokens: int | None,
    provider_input_tokens: int | None,
    provider_output_tokens: int | None,
    output_budget: int | None,
    latency_ms: int | None,
    outcome: str,
    finish_reason: str | None = None,
    error_kind: str | None = None,
) -> str:
    """Persist one auditable model attempt (or one checkpoint reuse)."""
    from .evidence_ref import content_digest

    call_id = "nlcall_" + content_digest({
        "window_key": window_key,
        "attempt": int(attempt),
        "outcome": outcome,
        "cache_hit": bool(cache_hit),
    })[:24]
    con.execute(
        f"""INSERT OR IGNORE INTO {CALLS_TABLE}(
              call_id,window_key,attempt,person_id,package_date,stage_name,model,
              why_called_json,facts_read_json,facts_produced_json,cache_hit,
              estimated_input_tokens,provider_input_tokens,provider_output_tokens,
              output_budget,latency_ms,outcome,finish_reason,error_kind,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            call_id, window_key, int(attempt), person_id, package_date,
            stage_name, model,
            json.dumps(why_called, ensure_ascii=False, sort_keys=True, default=str),
            json.dumps(facts_read, ensure_ascii=False, sort_keys=True, default=str),
            json.dumps(facts_produced, ensure_ascii=False, sort_keys=True, default=str),
            1 if cache_hit else 0,
            estimated_input_tokens, provider_input_tokens, provider_output_tokens,
            output_budget, latency_ms, outcome, finish_reason, error_kind, now_iso(),
        ),
    )
    return call_id


def _raw_output_text(raw_output: Any) -> str:
    if isinstance(raw_output, str):
        return raw_output
    if raw_output is None:
        return ""
    return json.dumps(raw_output, ensure_ascii=False, sort_keys=True, default=str)


def content_output_digest(raw_output: Any) -> str:
    """Stable digest of a model's RAW output, used to detect an identical retry.

    Deterministic and canonical (sorted keys) so the same logical answer always
    produces the same digest regardless of dict ordering."""
    from .evidence_ref import content_digest

    return content_digest({"raw": _raw_output_text(raw_output)})


def record_contract_rejection(
    con: Any,
    *,
    window_key: str,
    attempt: int,
    person_id: str,
    package_date: str,
    stage_name: str,
    model: str,
    strategy: str,
    input_digest: str,
    raw_output: Any,
    parsed_output: Any,
    violations: Any,
    finish_reason: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> tuple[str, str]:
    """Durably persist ONE contract rejection so no rule/output/value is lost.

    Returns ``(rejection_id, output_digest)``. The digest is computed on the raw
    model output so the executor can detect and refuse a byte-identical retry.
    A rejection row is additive audit evidence: it is never overwritten and never
    consulted as a validated output.
    """
    from .evidence_ref import content_digest

    raw_text = _raw_output_text(raw_output)
    output_digest = content_output_digest(raw_output)
    rejection_id = "nlrej_" + content_digest({
        "window_key": window_key,
        "attempt": int(attempt),
        "output_digest": output_digest,
    })[:24]
    parsed_json = (
        json.dumps(parsed_output, ensure_ascii=False, sort_keys=True, default=str)
        if parsed_output is not None else None
    )
    con.execute(
        f"""INSERT OR IGNORE INTO {REJECTIONS_TABLE}(
              rejection_id,window_key,attempt,person_id,package_date,stage_name,
              model,strategy,input_digest,output_digest,raw_output,
              parsed_output_json,violations_json,finish_reason,prompt_tokens,
              completion_tokens,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rejection_id, window_key, int(attempt), person_id, package_date,
            stage_name, model, strategy, input_digest, output_digest, raw_text,
            parsed_json,
            json.dumps(violations, ensure_ascii=False, sort_keys=True, default=str),
            finish_reason, prompt_tokens, completion_tokens, now_iso(),
        ),
    )
    return rejection_id, output_digest


def window_has_contract_rejection(
    con: Any, *, window_key: str, input_digest: str
) -> bool:
    """True when this window already has a persisted rejection for this input.

    The prompt is a pure function of ``input_digest``; a temperature-0 retry with
    the same input is therefore proven identical, so an existing rejection is
    enough to forbid the retry before it is spent."""
    row = con.execute(
        f"""SELECT 1 FROM {REJECTIONS_TABLE}
             WHERE window_key=? AND input_digest=? LIMIT 1""",
        (window_key, input_digest),
    ).fetchone()
    return row is not None


def contract_rejection_seen(
    con: Any, *, window_key: str, input_digest: str, output_digest: str
) -> bool:
    """True when this exact (window, input, output) triplet was already rejected.

    Used to forbid a byte-identical retry: a second strictly-identical model call
    must never leave the host (economy + honesty)."""
    row = con.execute(
        f"""SELECT 1 FROM {REJECTIONS_TABLE}
             WHERE window_key=? AND input_digest=? AND output_digest=? LIMIT 1""",
        (window_key, input_digest, output_digest),
    ).fetchone()
    return row is not None


def load_outputs(
    con: Any,
    *,
    person_id: str,
    package_date: str,
    stage_name: str,
    window_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Re-read validated outputs for a stage (merge input / coverage source).

    ``stage_name`` alone is not a version boundary: old adapter/prompt/model
    checkpoints intentionally remain auditable under the same business stage.
    A current execution must therefore pass its exact leaf ``window_keys`` when
    outputs are used for coverage or materialisation.
    """
    cur = con.execute(
        f"""SELECT o.window_key, o.output_json
              FROM {OUTPUTS_TABLE} o
              JOIN {WINDOWS_TABLE} w ON w.window_key=o.window_key
             WHERE w.person_id=? AND w.package_date=? AND w.stage_name=?
               AND w.state=?
             ORDER BY w.window_index, o.output_digest""",
        (person_id, package_date, stage_name, STATE_COMPLETED),
    )
    out: list[dict[str, Any]] = []
    for window_key_, output_json in cur.fetchall():
        if window_keys is not None and window_key_ not in window_keys:
            continue
        out.append({"window_key": window_key_, "output": json.loads(output_json)})
    return out
