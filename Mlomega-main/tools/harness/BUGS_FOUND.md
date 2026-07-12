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

## OBS-5 — HARNESS media/transport drops at ~20s (OUVERT — 2026-07-12) — HANDOFF

**Severity:** blocks the full-length `--with-close-day` validation (the session is
starved to ~20s → close-day returns `blocked`, never `completed`). This is a
**harness-side (aiortc) defect, NOT a product bug** — the product server log is
clean on every run (no rejection, no teardown initiated server-side).

### Exact symptom (reproducible on EVERY run)
- `audio_chunks_received` plateaus at ~1000 (≈20s of 20ms Opus frames) although
  the media is 301.6s. `scenario_events_sent` = 2 of 13 (only t=20 and t=45 fire;
  the connection is gone before t=70).
- The fake device raises, on its own asyncio loop, roughly at t≈20–48s:
  `ConnectionError: Cannot send encrypted data, not connected`
  from `aiortc/rtcsctptransport.py::_transmit → rtcdtlstransport.py::_send_data`.
  → the DTLS/SCTP transport on the FAKE DEVICE side closed; the next
  `FrameEnvelope` DataChannel send then fails and the scenario loop stops.
- `peer_state_log` (in the device report) shows: `connecting → connected` at ~t0,
  then `closed` at ~t0+20–48s. No product/server error in `server.log`.

### What was RULED OUT (do not re-chase)
1. **The video file.** Same ~20s stall with the original WhatsApp VFR mp4 AND a
   clean ffmpeg re-encode (`-c:v libx264 -profile:v baseline -pix_fmt yuv420p -r 24
   -c:a aac -ar 48000`, saved as `tools/harness/_run/real_video_clean.mp4`).
2. **The DB.** Same stall with a fresh scratch DB and after wiping
   `harness_memory.db*`. The scratch DB is NOT the cause.
3. **MediaPlayer queue interlock (single-player theory).** Split into two separate
   `MediaPlayer` instances (audio from one, video from the other) in
   `fake_xr_device.py` — did NOT fix it. (Change kept; it is correct hygiene.)
4. **`disconnected` treated as terminal.** Already fixed earlier (only
   `failed`/`closed` set `_stop`); not the cause of the ~20s drop.

### LEADING HYPOTHESIS (next agent: start here)
The fake device's **outbound video encoding** (aiortc RTCRtpSender encoding 720p
frames) starves the device's own asyncio loop, so ICE **consent-freshness** STUN
checks aren't sent/answered in time and aiortc tears the connection down after a
few missed cycles (~20s). Evidence for: the drop is on the DEVICE side, timing is
consistent regardless of file, and server `/metrics` polls stay prompt (server
loop is NOT starved). **Cheapest thing to try first:** re-encode the media to
low resolution + low fps (e.g. `-vf scale=480:-2 -r 10`) so the sender's encoder
is cheap, and/or cap the sender via `RTCRtpSender.setParameters` if exposed. If a
low-res clip streams the full 301s, the hypothesis is confirmed.
Secondary ideas: pin the video sender to a worker thread; check the installed
aiortc version for a known consent-freshness issue; try `MediaPlayer(..., decode=False)`
is not applicable (server needs decoded frames). Also consider sending video at a
lower height by pre-scaling — the pipeline only needs enough resolution to detect.

### Files touched THIS session (for whoever picks this up)
Product (committed `93fb568`, the 3 real bugs — DONE, tested, 49 passed):
- `services/live-pc/live_pipeline.py` — `end_session` split; new
  `end_session_after_drain_timeout` / `_end_session_after_drain` (OBS-2).
- `services/live-pc/phoneonly_runtime.py` — `end_session_only` swallows drain
  `TimeoutError` around `flush_audio` / `end_session` / `release_live_resources`,
  still triggers close-day (OBS-2).
- `services/live-pc/worldbrain.py` — `_init_service_db(check_same_thread=False)` +
  `self._db_lock` RLock around every `_svc_db` access (OBS-3).
- `services/live-pc/hypothesis_engine.py` — `_safe_confidence` helper (OBS-4).

Harness (committed `93fb568`, media stall still OPEN):
- `tools/harness/fake_xr_device.py` — two separate `MediaPlayer` instances
  (`player_v`, `player_a`, stored in `self._players`, stopped in the finally
  block). This is where the ~20s fix must land (see hypothesis above).

### How to reproduce (Qdrant + Ollama must be up)
```
Remove-Item tools\harness\_run\harness_memory.db* -Force
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 `
  --media "<any mp4>" --scenario tools\harness\scenarios\real_video_session.json `
  --duration 80        # short, no close-day: watch audio_chunks stop at ~1000
```
Inspect `tools/harness/_run/device_report.json` → `peer_state_log`, `errors`,
`audio_chunks_received`, `scenario_events_sent`, and `tools/harness/_run/server.log`.

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
