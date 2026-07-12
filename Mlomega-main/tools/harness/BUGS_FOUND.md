# E63 harness — observations produit et état des corrections

La première passe E63 consignait seulement les observations. La passe de finition
du 2026-07-12 a été explicitement autorisée à corriger les défauts produit ;
chaque entrée ci-dessous indique donc son état réel.

## OBS-1 — Delivery queue absente sur une DB neuve (CORRIGÉ — 2026-07-12)

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

**Fix :** le DeliveryAdapter initialise désormais son schéma avant la première
lecture. Le run minimal sur DB neuve ne perd plus les suggestions de la première
session.

## OBS-2 — CloseDay dépassait le worker final après un timeout (CORRIGÉ — 2026-07-12)

**Severity:** blocker (BrainLive était fermé pendant que des tours continuaient à arriver).

**Where:** `services/live-pc/live_pipeline.py` `drain_final_processing`
(`raise TimeoutError("final turn processing did not drain in 30.0s")`) →
`services/live-pc/phoneonly_runtime.py` `end_session_only` call site.

**Symptom réel (run vidéo 5 min du 2026-07-12):** le correctif initial avalait
le timeout de drain, marquait BrainLive terminé et lançait CloseDay alors que le
worker final écrivait encore. Les erreurs suivantes apparaissaient ensuite :
`conversation.ingest_segment: cannot ingest turn into non-active live session`.

**Fix final:** le drain s'attend réellement (budget produit 300 s). Un timeout
reste un échec de fermeture retryable : BrainLive n'est pas terminé, `ended`
reste faux et CloseDay demeure `not_started`. Le raccourci dangereux
`end_session_after_drain_timeout` est supprimé. Régression :
`test_drain_timeout_blocks_brainlive_end_and_close_day`.

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

## OBS-5 — WebRTC tombait au premier device_transcript (~20 s) (CORRIGÉ — 2026-07-12)

**Severity:** blocker produit. Le symptôme ressemblait à un défaut média du faux
device, mais la cause était dans le serveur PC.

Au premier `device_transcript` scénarisé, le callback DataChannel appelait
`PhoneOnlyRuntime._on_receipt` synchroniquement sur la boucle aiortc. Le routage
Intent/VLM pouvait bloquer assez longtemps pour faire expirer le consentement ICE
et fermer DTLS. Un scénario sans commande tenait 60 s ; le même média avec la
commande tombait à 20 s, preuve discriminante.

**Fix :** `gateway.py` planifie les receipts, les sérialise et exécute le callback
synchrone via `asyncio.to_thread`. La fermeture draine ces tâches avant de couper
le média. Le faux device sépare aussi réellement l'audio et la vidéo du MP4 en
fichiers mono-track temporaires (hygiène déterministe, pas la cause racine).

**Preuve après fix :** le vrai scénario a traversé les 301 s du MP4 avec
**14 857 chunks audio** et 2 tours conversationnels. Le test ciblé
`test_slow_device_command_does_not_block_webrtc_event_loop` couvre la frontière.

## OBS-6 — AttributeMemory/HypothesisEngine SQLite cross-thread (CORRIGÉ — 2026-07-12)

Le worker final utilise ces moteurs hors du thread de construction. Leurs
connexions SQLite levaient `SQLite objects created in a thread...`, masquant la
mémoire fine malgré un transport vert. Connexions ouvertes avec
`check_same_thread=False` et chaque accès protégé par un `RLock`, même politique
que WorldBrain.

## OBS-7 — Une reprise CloseDay `blocked` ne pouvait pas reprendre (CORRIGÉ — 2026-07-12)

La récupération durable retrouvait correctement le job, mais ne passait
`allow_rerun/force` que si un CloseDay était déjà `completed`. Un run `blocked`
était donc refusé par `assert_run_resumable` à chaque redémarrage. Une recovery
est désormais toujours un retry explicite (`allow_rerun=True`) ; le script ne
réouvre un jour completed que s'il existe réellement.

## Validation complète encore bloquée par la configuration machine

Le CloseDay atteint WhisperX/Pyannote et CUDA, puis Hugging Face répond **403**
sur `pyannote/speaker-diarization-3.1`: le token doit autoriser les dépôts publics
gated et le compte doit avoir accepté les conditions du modèle. Ce n'est pas
contourné : la validation `--with-close-day` reste ouverte jusqu'à ce droit.

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
