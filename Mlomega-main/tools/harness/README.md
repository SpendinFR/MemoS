# E63 — End-to-end integration harness

A fake XR device that replays a full session against the **real** PC code
(`services/live-pc/sessionhub_http.py` + `phoneonly_runtime.py`) over real WebRTC,
plus a chaos pass that injects faults. **All files here are new; no product file
is modified.** The harness is a pure network client — it never imports the product
modules for the live flow (it only reads the product SQLite directly for the
after-the-fact assertions).

## What it does

1. **Pairing** — `POST /session/create {device_id}` → `{session_id, token}`.
2. **WebRTC** — `POST /webrtc/offer {sdp, type, session_id, token}` pushing a real
   audio track + video track from an MP4 (aiortc `MediaPlayer`, native real-time
   pacing) and a reliable DataChannel.
3. **DataChannel messages** (schemas copied verbatim from the Unity client):
   `FrameEnvelope` (video metadata), `device_command_result` (ack for the PC's
   `set_wake_word` push), `device_transcript` (final ASR segments, `is_command`
   tagged so the PC IntentRouter routes them).
4. **Scenario** — an ordered list of `(t, message)` events
   (`scenarios/basic_session.json`), then a clean `POST /session/end` that triggers
   close-day.
5. **Assertions** — read the product SQLite directly and report PASS/FAIL: session
   recorded, session ended, audio pipeline ran, video clip indexed in
   `visual_evidence_assets_v19`, scripted intents driven (+ close-day + recovery
   with `--with-close-day`).

## Prerequisites

- Use the **`.venv-live`** interpreter for everything here (aiortc / cv2 / sherpa).
  The close-day subprocess uses the core `.venv` on its own; you do not invoke it.
- `ffmpeg` on `PATH` (only needed when you don't pass `--media`; it builds a
  synthetic mire+bip MP4).
- **Minimal mode needs NO GPU / Ollama / Qdrant.** The server's `/health` reports
  `ai_ready=false` without them, but pairing/offer only need `pairing_ready=true`,
  which the harness waits for. The heavy nightly close-day (`--with-close-day`) is
  the only part that needs the full AI chain + core `.venv` + GPU.
- Ports: the harness uses a dedicated **test port (default 8730)**, never 8710
  (real SessionHub), never 8766 (forbidden). Chaos uses 8734/+1 by default.

The orchestrator spawns the server with `MLOMEGA_DB` pointed at a **scratch DB**
(`tools/harness/_run/harness_memory.db`), so a run never touches the real
`memory.db`.

## Run it (copy-paste, from repo root)

Minimal full session (synthetic media, no close-day) — the validated PASS path:

```
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --duration 26 --synth-seconds 30
```

Against a real MP4 with speech (gets real transcripts/turns):

```
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --media path\to\clip.mp4 --duration 40
```

Attach to an already-running server (e.g. the real 8710) instead of spawning:

```
.venv-live\Scripts\python tools\harness\run_harness.py --attach --host 127.0.0.1 --port 8710 --db <that-server's-db>
```

Full nightly consolidation too (HEAVY: WhisperX GPU + core `.venv`, off by default):

```
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --with-close-day --duration 30
```

Just the device (server already up), writing its own report:

```
.venv-live\Scripts\python tools\harness\fake_xr_device.py --port 8730 --out device_report.json
```

Assertions standalone against a DB:

```
.venv-live\Scripts\python tools\harness\assertions.py --db tools\harness\_run\harness_memory.db --json
```

## Chaos pass

```
.venv-live\Scripts\python tools\harness\chaos.py --port 8742 --scenarios net_drop_reconnect,double_end,ollama_down
```

Each scenario runs on its own fresh server + DB (the mono-device policy keeps a
runtime active until its close-day finishes, so sharing a server would 409).

- `net_drop_reconnect` — cut the peer mid-session (no `/session/end`), reconnect;
  the BrainLive session id must stay stable (peer drop never ends BrainLive).
- `double_end` — call `/session/end` twice; the second must be idempotent.
- `ollama_down` — server started with `OLLAMA_HOST` → dead port; the live loop
  must degrade (grammar/local routing) and still end cleanly.
- `kill_before_close_day` — end a session, `kill -9` the server before close-day,
  relaunch; startup recovery must drive the pending
  `phoneonly_session_recovery_v19` job. Add `--with-recovery-close-day` to run the
  heavy close-day and assert `completed`; otherwise it asserts the durable
  recovery boundary exists after the kill.

## Scenario format (`scenarios/*.json`)

```json
{ "events": [
  { "t": 2.0, "kind": "transcript", "text": "c'est quoi ca", "is_command": true },
  { "t": 8.0, "kind": "device_intent", "action": "owner_enroll" },
  { "t": 9.0, "kind": "raw", "payload": { "type": "privacy_state", "paused": true } }
] }
```

`t` is seconds after the DataChannel opens. `kind`: `transcript` (default) →
`device_transcript`; `device_intent` → menu-style `device_intent`; `raw` → sent
verbatim.

## Product observations

Anything the harness surfaces about the product is in `BUGS_FOUND.md` (not fixed,
per E63 rules). Outputs land under `tools/harness/_run/` and `_chaos/` (server
logs, device reports) and are git-ignored / not committed.
