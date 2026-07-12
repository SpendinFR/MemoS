# E63 harness — product observations (NOT fixed, per E63 rules)

The harness rule is: new files only, never touch a product file. Anything the
harness surfaces about the product is recorded here for a separate owner to
triage. None of these blocked a full minimal end-to-end run (the harness passes
ALL base assertions), so they are robustness/ordering notes, not crashes.

## OBS-1 — Live DeliveryAdapter reads `brainlive_intervention_delivery_queue` before it is created (fresh DB)

**Severity:** low (degrades cleanly, does not crash, does not fail the session).

**Where:** `services/live-pc/delivery_adapter.py` (queries the table), schema owned
by `src/mlomega_audio_elite/v18_delivery.py` (line ~13, `CREATE TABLE IF NOT
EXISTS brainlive_intervention_delivery_queue`).

**Symptom:** on a first-ever session against a brand-new `memory.db`, the runtime
status `recent_errors` fills with (observed 20x in one 26s session):

```
"no such table: brainlive_intervention_delivery_queue"
```

**Cause:** the live `DeliveryAdapter` in `services/live-pc` reads/writes that queue
table during the delivery loop, but the table is only created by the core
`v18_delivery` module's schema, which is not run at live-pipeline startup on a
fresh DB — it is created later (close-day / core `.venv` init). The live path has
no eager `CREATE TABLE IF NOT EXISTS` for it.

**Impact:** the error is caught and pushed to `recent_errors` (the delivery loop
swallows it via `except Exception`), so proactive/help interventions are silently
dropped for the very first live session on a new install until something else
creates the table. Subsequent sessions (after the first close-day) are fine.

**Repro:**
```
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --duration 26 --synth-seconds 30
```
then inspect the emitted `tools/harness/_run/device_report.json` →
`server_metrics_active.recent_errors`.

**Suggested fix (for the owner, not applied here):** have the live pipeline /
DeliveryAdapter run the `brainlive_intervention_delivery_queue` `CREATE TABLE IF
NOT EXISTS` (or call the shared schema) at startup, the same way
`phoneonly_runtime._RECOVERY_SCHEMA` is ensured before use.

## OBS-2 — /session/end 500 on drain timeout (CORRIGÉ — 2026-07-12)

**Severity:** blocker (the whole end-of-session + close-day never ran).

**Where:** `services/live-pc/live_pipeline.py` `drain_final_processing`
(`raise TimeoutError("final turn processing did not drain in 30.0s")`) →
`services/live-pc/phoneonly_runtime.py` `end_session_only` call site.

**Symptom (real-video run 2026-07-11):** `POST /session/end` → HTTP 500,
`end_session: error`, `close_day: not_started`, `recovery: not_started`. The
drain TimeoutError propagated out of `pipeline.end_session(strict=True)`, flipped
`end_status` to `error`, and close-day was never triggered.

**Fix:** the end of session must NEVER fail because the final-turn worker did not
drain — the turns are already durable in the DB and close-day reprocesses them.
`end_session_only` now catches `TimeoutError` around the three drain-bearing
calls (`flush_audio`, `pipeline.end_session`, `release_live_resources`), records
it in the pipeline errors + `recent_errors`, and continues (best-effort
post-drain flush via new `live_pipeline.end_session_after_drain_timeout`, which
runs the discourse/WorldBrain summary without re-draining). The drain semantics
themselves are unchanged. New regression:
`tests/v19/test_phoneonly_runtime.py::test_drain_timeout_never_fails_end_session_and_still_closes_day`.
Committed in the E63 real-video fix pass.

## OBS-3 — WorldBrain service SQLite used cross-thread (CORRIGÉ — 2026-07-12)

**Severity:** grave (dead scene ingestion; 50+ errors/session).

**Where:** `services/live-pc/worldbrain.py` `_init_service_db` + all `self._svc_db`
uses; called from the vision worker threads via
`live_pipeline.py:_on_scene_delta → worldbrain.ingest_scene_delta`.

**Symptom:** `worldbrain.ingest_scene_delta: SQLite objects created in a thread
can only be used in that same thread` — 54 occurrences in the real-video run;
scene entities/changes were never persisted.

**Fix (minimal):** `sqlite3.connect(..., check_same_thread=False)` + a
`threading.RLock` (`self._db_lock`) held around every `self._svc_db` access
(`_persist_entity`, the session-changes insert, `record_attribute_change`). No
broader refactor. New regression:
`tests/v19/test_e28_worldbrain.py::test_ingest_scene_delta_is_thread_safe`.

## OBS-4 — hypothesis_engine.note_turn crashes on dirty LLM confidence (CORRIGÉ — 2026-07-12)

**Severity:** minor (one turn's addressee hypothesis dropped, reported).

**Where:** `services/live-pc/hypothesis_engine.py` `note_turn`
(`float(signal.get("confidence") or 0.0)`).

**Symptom:** `hypothesis_engine.note_turn: could not convert string to float:
'}}0'` — a local LLM leaked a malformed JSON fragment into the confidence field.

**Fix:** new `_safe_confidence` helper wraps the coercion in try/except, falls
back to `0.0`, counts `metrics["signal_parse_errors"]`, and reports the parse
failure once (`_reported_conf_parse_error`). Existing tests unchanged.

## Notes that are NOT bugs (expected, documented so future runs don't chase them)

- **`ai_ready=false` / `/health` 200 with `pairing_ready=true`.** Expected on a
  dev box without GPU+YOLOX+Ollama+Qdrant all green. Pairing/offer only needs
  `pairing_ready`, which the harness waits for. Nothing to fix.
- **`brainlive turns = 0` with synthetic media.** The synthetic MP4 is a 440 Hz
  sine (no speech), so WhisperX emits no word finals and no conversation turns are
  written. The scripted `device_transcript` intents DO route
  (`intents_routed=1`, `turns_routed=1`) but device-command routing does not
  create brainlive turn rows. Use a real-speech MP4 via `--media` to get turns.
- **`device_commands_received=0` / `wake_word_acked=false`.** `push_wake_word()`
  only sends a `set_wake_word` device_command when a wake word is configured in
  `configs/user_profile.yaml`. With no profile wake word it is a no-op, so the
  fake device never gets a command to ack. Not a bug; configure a wake word to
  exercise that path.
