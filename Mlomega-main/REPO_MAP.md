# REPO_MAP — MLOmega V19 — V4

Carte logique V4 du dépôt, destinée à orienter un agent avant une tâche importante. Cette édition fusionne les chemins E53/E58/E59/E60 dans les sections natives au lieu de conserver un patch delta séparé.

Ce fichier n’est pas une preuve que le code fonctionne. Il indique où regarder, quels contrats relier, quels tests existent, et quels pièges éviter. Avant toute modification, lire les fichiers réels concernés dans le checkout courant.

## 0. Règles de lecture

- Le checkout est la source de vérité.
- Les docs, noms de fichiers, noms de branches, intitulés d’étapes ou noms “live/phoneonly/runtime” ne prouvent pas qu’un flux est réellement branché.
- Pour valider un flux, remonter les appels réels : entrée → appelant → payload → thread/process/env → sortie → test.
- Ne jamais confondre `session_id` transport/WebRTC avec `live_session_id` BrainLive.
- Ne jamais ajouter de dépendance à `turns.created_at` : cette colonne n’est pas un contrat valide pour `turns`.
- Ne jamais déclarer PhoneOnly matériel validé sans test Android réel.
- Ne jamais lancer CloseDay sur perte réseau, `OnDisable`, `OnDestroy`, crash ou WebRTC disconnected.

## 1. Vue système

```text
Téléphone Android / lunettes XREAL
  Unity C#
    caméra / micro / UI / pairing / scene cache
      ↕ JNI
  Kotlin plugins
    livetransport : WebRTC audio+vidéo+DataChannel, provisioning modèles
    reflexvision : ASR/KWS, gestes, traduction offline, app launcher
      ↕ WebRTC + HTTP
PC V19
  SessionHub HTTP
  aiortc ingress
  PhoneOnlyRuntime
  LivePipeline
    VisionRT → WorldBrain → SceneAdapter → DeliveryAdapter → UIIntent
    AudioRT → ConversationBridge → BrainLive turns
    AudioArchive / keyframes / clips / visual evidence
      ↕ SQLite + médias + Qdrant + Ollama
Core mémoire
  V18.8 BrainLive / Brain2 / Life Model / governance
  CloseDay durable
  V19 visual, predictions, self schema, retention
```

Couche par couche :

- Téléphone : capture et rendu. En mode PhoneOnly, le téléphone est le capteur réel et affiche aussi l’UI.
- PC live : compréhension temps réel, génération d’intents, archive, métriques.
- Cœur mémoire : vérité durable, BrainLive, Brain2, CloseDay, gouvernance des preuves.
- Nuit / post-stop : consolidation lourde, deep audio, deep vision, longitudinal, Life Model.

## 2. Structure du dépôt

### Racine

- `README.md` — document d’accueil produit.
- `WELCOME.md` — usage de l’assistant d’installation.
- `.env` — configuration runtime locale. Attention : contient potentiellement des secrets.
- `pyproject.toml`, `pytest.ini`, `requirements*.txt` — packaging et dépendances.
- `FIRST_TRY_ANDROID.md` — procédure premier essai Android.
- `INSTALL_STATE.md`, `E46D_STATE.md`, `E46_close_day_completed.json` — états/preuves de travaux.
- `REPO_MAP.md`, `repo_graph_v4.json` — cette carte et sa version structurée.

### `src/mlomega_audio_elite/`

Cœur mémoire V18/V19. Contient le schéma SQLite, ingestion, BrainLive, Brain2, CloseDay, Life Model, sync vectorielle, gouvernance, routines nocturnes.

Ne pas le traiter comme un package neuf : beaucoup de modules V13→V18 sont encore actifs et utilisés par V19.

### `services/live-pc/`

Runtime PC live V19. C’est le pont entre le téléphone et le cœur mémoire :

- HTTP/session/signaling ;
- aiortc ;
- VisionRT ;
- AudioRT ;
- WorldBrain ;
- PhoneOnly runtime ;
- delivery UI ;
- retention/clip recording.

### `apps/xr-mobile/`

Projet Unity Android/XR :

- C# runtime Unity ;
- scènes PhoneOnly/G1/E25 ;
- build APK ;
- Android plugins ;
- assets config ;
- tests EditMode.

### `apps/xr-mobile/android/livetransport/`

Plugin Kotlin WebRTC :

- PeerConnection ;
- audio track Opus ;
- video track ;
- DataChannel ;
- signaling `/webrtc/offer` ;
- fan-out micro ;
- credentials ;
- provisioning modèles.

### `apps/xr-mobile/android/reflexvision/`

Plugin Kotlin réflexes locaux :

- ASR/KWS sherpa ;
- wake word ;
- command window ;
- MediaPipe gestures ;
- ONNX Runtime traduction offline ;
- app launcher.

### `packages/contracts/`

Contrats JSON :

- schemas JSON ;
- modèles Python ;
- modèles C# générés.

Tout changement de contrat doit vérifier Python + Unity C# + DataChannel + tests de génération.

### `scripts/`

Entrées Windows :

- installation ;
- lancement ;
- build Android ;
- récupération modèles ;
- scénarios ;
- Qdrant ;
- CloseDay worker ;
- dashboard.

### `configs/`

Profils et modèles :

- `MODEL_MANIFEST.yaml` — modèles PC et device.
- `profiles/rtx3070.yaml` — profil nominal RTX 3070.
- `profiles/sim.yaml` — simulation.
- `profiles/degraded.yaml` — mode dégradé.
- `user_profile.yaml` — overrides locaux.
- `cloud_llm.yaml` — clients cloud opt-in.

### `tests/v19/`

Tests Python V19, organisés par lots E24→E56 et par composant.

### `simulators/`

Fake XR / scénarios synthétiques. Utile pour tests PC, mais jamais preuve de PhoneOnly matériel.

### `apps/memory-dashboard/`

Dashboard Streamlit lecture seule sur la mémoire.

### `apps/companion-web/`

Viewer web simple. Ne pas confondre avec app Android réelle.

### `MLOmega_V18_8_1_Evidence_Connected/`

Snapshot/référence V18.8 avec scripts/docs/tests legacy.

## 3. Entrées de lancement

### Runtime PhoneOnly PC

Fichier : `scripts/RUN_MLOMEGA_V19.ps1`

Modes :

- `-LivePhone` / alias `-PhoneOnly` : runtime PC réel, aucun fake device.
- `-SimOnly` : démo fake device → UIIntent → companion/web/receipt.
- `-Xr` : explicitement indisponible dans ce script.

Chemin nominal :

```powershell
scripts\START_QDRANT.ps1
ollama serve
scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

Le script vérifie notamment `aiortc`, `av`, `fastapi`, `uvicorn`, `faster_whisper`, `onnxruntime`, `rapidocr_onnxruntime`, `dotenv`.

### Build plugins Android

Fichier : `scripts/BUILD_ANDROID_PLUGINS.ps1`

Rôle :

- build/test `livetransport` ;
- build/test `reflexvision` ;
- export AAR vers Unity ;
- déduplique Kotlin/annotation jars.

À vérifier après changement Kotlin :

- `testDebugUnitTest` ;
- `exportUnityRelease` ;
- AAR copiés dans `apps/xr-mobile/Assets/Plugins/Android`.

### Build APK PhoneOnly

Fichier : `apps/xr-mobile/Assets/Scripts/Editor/AndroidBuild.cs`

Menu Unity :

- `MLOmega/Build PhoneOnly APK`

Rôle :

- configure Android ;
- IL2CPP/ARM64 ;
- min/target SDK ;
- define `MLOMEGA_PHONE_ONLY` ;
- scène PhoneOnly ;
- StreamingAssets modèles petits ;
- endpoint runtime ;
- application ID forcé `com.mlomega.xr.phoneonly` ;
- régénération systématique de la scène PhoneOnly avant build.

### Build scène PhoneOnly

Fichier : `apps/xr-mobile/Assets/Scripts/Editor/PhoneOnlySceneBuilder.cs`

Menu Unity :

- `MLOmega/Build PhoneOnly Scene`

Rôle :

- génère `PhoneOnly.unity` ;
- crée/relie config ;
- ajoute caméra, capture, pairing, transport, UI, reflex, provisioning, fin explicite.

À vérifier après chaque changement de scène :

- `SessionPairing` présent ;
- `PhoneOnlyAdapter` et `EyeCaptureSource` présents ;
- `LiveTransportBridge` présent ;
- `PhoneOnlySessionCoordinator` présent ;
- `AsrBridge`, `GestureBridge`, `TranslateBridge`, `ReflexScheduler` présents si gates device ;
- `UIIntentBroker`, `TransportIntentSource`, `SceneDeltaTransportHandler`, `UIReceiptTransportSink` présents ;
- `PhoneOnlyReflexSignalSource`, `MenuPanel`, `OrientationGuard`, `TtsAudioPlayer` et `PanelManipulator` présents ;
- pas de `E25DemoDriver` en prod PhoneOnly.

### Build XREAL

Fichiers :

- `apps/xr-mobile/Assets/Scripts/Editor/G1SceneBuilder.cs`
- `apps/xr-mobile/Assets/Scripts/Editor/AndroidBuildXreal.cs`
- `apps/xr-mobile/Assets/Scripts/Core/XrealDeviceAdapter.cs`

Menus Unity :

- `MLOmega/Build G1 Gate Scene`
- `MLOmega/XREAL/1. Prepare (SDK + define)`
- `MLOmega/XREAL/2. Build Glasses APK (G1)`

Attention :

- G1/XREAL est séparé de PhoneOnly.
- Le SDK XREAL propriétaire n’est pas censé être requis pour build PhoneOnly.

### Installation / onboarding

Fichier : `scripts/WELCOME_MLOMEGA.ps1`

Rôle :

- orchestre l’installation sans réécrire les scripts ;
- crée `.venv` cœur et `.venv-live` ;
- installe/guide ffmpeg, Qdrant, Ollama, modèles ;
- écrit `.env` et profil ;
- lance Doctor ;
- explique APK/téléphone/dashboard.

Modes :

- interactif ;
- `-Defaults` ;
- `-DryRun`.

### Qdrant

Fichier : `scripts/START_QDRANT.ps1`

Rôle :

- lance Qdrant natif Windows depuis `tools/qdrant`;
- storage local dans `storage/qdrant`;
- vérifie `/healthz` port 6333.

### Dashboard mémoire

Fichier : `scripts/RUN_DASHBOARD.ps1`

App :

- `apps/memory-dashboard/app.py`

Port :

- 8720.

Principe :

- SQLite en lecture seule ;
- pas de télémétrie Streamlit ;
- chat via CLI cœur si disponible.

### CloseDay PhoneOnly

Fichier : `scripts/run_phoneonly_close_day.py`

Rôle :

- worker lancé hors requête HTTP ;
- utilise `.venv` cœur, pas `.venv-live` ;
- appelle le CloseDay durable ;
- supporte reprise/idempotence et rerun contrôlé.

## 4. Services PC live

### `services/live-pc/sessionhub_http.py`

Fonctions clés :

- `create_app(...)`
- `load_device_manifest()`
- `build_device_manifest_payload()`
- `main()`

Routes :

- `GET /live` — processus vivant.
- `GET /health` — readiness PhoneOnly.
- `GET /metrics` — métriques SessionHub/runtime.
- `GET /models/device/manifest` — manifest modèles device.
- `GET /models/device/{name}` — artefact modèle device.
- `POST /session/create` — session/token.
- `POST /session/renew` — renew token/session.
- `POST /session/clock-sync` — échange horloge.
- `POST /webrtc/offer` — WebRTC SDP offer/answer.
- `POST /session/end` — fin live explicite.
- `POST /session/close-day` — relance/retry CloseDay.
- `POST /session/status` — statut authentifié.

Dépend de :

- `sessionhub.py`
- `gateway.py`
- `phoneonly_runtime.py`
- `configs/MODEL_MANIFEST.yaml`

Risques :

- `/health` ne doit pas répondre “ok” si aiortc/runtime/signaling indisponible.
- Les routes métier doivent vérifier session_id + token.
- `/session/renew` peut avoir une grâce ; les autres routes ne doivent pas accepter un token expiré.
- Un second téléphone ne doit pas écraser silencieusement le runtime actif.

Tests :

- `tests/v19/test_sessionhub_http.py`
- `tests/v19/test_device_provisioning.py`
- `tests/v19/test_phoneonly_runtime.py`

### `services/live-pc/sessionhub.py`

Rôle :

- session store mémoire ;
- token TTL ;
- renew ;
- clock sync ;
- auth.

À inspecter avec :

- expiration réelle ;
- purge ;
- rotation atomique ;
- comportement mauvais token / mauvais session_id.

Tests :

- `tests/v19/test_sessionhub.py`
- `tests/v19/test_sessionhub_http.py`

### `services/live-pc/gateway.py`

Classes/fonctions :

- `AiortcIngress`
- `LatestFrameQueue`
- `_EnvelopeMatcher`
- `_audio_frame_to_mono(frame)`
- `pump_latest`

Rôle :

- gère PeerConnection aiortc ;
- reçoit vidéo ;
- reçoit audio ;
- convertit audio PyAV → PCM mono ;
- maintient queue latest-frame ;
- envoie UIIntent sur DataChannel ;
- expose stats.

Frontières critiques :

- aiortc audio peut être packed ou planar.
- Opus décodé typique : `s16/stereo` packed.
- Conversion attendue : PCM mono `int16`, sample rate source conservé.
- Envoi DataChannel doit rester dans l’event loop aiortc.
- Déconnexion WebRTC ne doit pas lancer CloseDay.

Tests :

- `tests/v19/test_transport_webrtc.py`
- `tests/v19/test_phoneonly_runtime.py`

### `services/live-pc/phoneonly_runtime.py`

Classes :

- `DataChannelRenderer`
- `PhoneOnlyRuntime`
- `SinglePhoneRuntimeManager`

Méthodes clés :

- `PhoneOnlyRuntime.start()`
- `_delivery_loop()`
- `_on_datachannel_open()`
- `_on_receipt()`
- `_on_audio_chunk()`
- `end_session_only()`
- `run_close_day()` / `_run_close_day()`
- `_completed_close_day_exists()`
- watchdog CloseDay de secours
- `close_transport()` / `status()`
- `SinglePhoneRuntimeManager.get_or_create()`
- `SinglePhoneRuntimeManager.start_close_day()`

Rôle :

- crée/possède le runtime d’une session PhoneOnly ;
- construit le `ClipRecorder` et le `GpuArbiter` de production ;
- passe `clip_recorder` à `AiortcIngress` ;
- lie ingress + pipeline avec `enable_tts=True` ;
- consomme la queue H1/DeliveryAdapter ;
- pousse UIIntent, `device_command` et `tts_audio` sur DataChannel ;
- reçoit UIReceipt et `device_command_result` ;
- coordonne end_session et CloseDay worker ;
- vérifie les complétions CloseDay dans la DB et arme un watchdog après fin explicite.

Risques :

- `live_session_id` doit venir de `ConversationBridge`, pas du transport.
- CloseDay ne doit pas bloquer la requête HTTP.
- End doit être idempotent.
- Le watchdog ne doit jamais transformer une coupure réseau en fin de session.
- DataChannel pas ouvert : ne pas marquer faussement une delivery comme affichée ni perdre une commande wake-word non acquittée.

Tests :

- `tests/v19/test_phoneonly_runtime.py`
- `tests/v19/test_delivery_adapter.py`
- `tests/v19/test_multi_session_close_day.py`

### `services/live-pc/live_pipeline.py`

Classe :

- `LivePipeline`

Méthodes importantes :

- `run_video(...)`
- `on_audio_chunk(...)`
- `end_session(...)`
- `_on_scene_delta(...)`
- `_route_vision_focus(...)`
- `_push_intent(...)`
- `_push_device_command(...)`
- `push_wake_word(...)`
- `set_wake_word_policy(...)`
- `arm_command_window(...)`
- `_should_route_intent(...)`
- `create_metrics_app(...)`

Rôle :

- cœur du live PC ;
- consomme vidéo/audio ;
- appelle VisionRT hors boucle quand nécessaire via `asyncio.to_thread` ;
- gate la spatialisation sur `FrameEnvelope.pose_valid` ;
- appelle AudioRT et archive ;
- route transcripts vers ConversationBridge ;
- met à jour WorldBrain ;
- génère SceneDelta/UIIntent/device_command ;
- pousse le wake word runtime avec `command_id` et retry d’ack ;
- émet `tts_audio` quand `enable_tts=True` ;
- expose métriques.

À vérifier quand on touche :

- queue vidéo latest-only ;
- pose neutre jamais spatialisée ;
- frames reçues vs traitées vs dropped ;
- audio chunks/finals/turns ;
- commandes device acquittées/idempotentes ;
- keyframes / clips / archives ;
- fin stricte : freeze, drain, flush, close.

Tests :

- `tests/v19/test_e27_pipeline.py`
- `tests/v19/test_phoneonly_runtime.py`
- `tests/v19/test_visionrt.py`
- `tests/v19/test_audiort.py`
- `tests/v19/test_wake_word_gating.py`

### `services/live-pc/audiort.py`

Classes :

- `VadSegmenter`
- `WhisperTranscriber`
- `ArgosTranslator`
- `AudioRT`
- `AudioMetrics`

Fonctions :

- `to_mono_16k(samples, src_rate)`
- `_configure_windows_cuda_dlls()`

Rôle :

- VAD ;
- resampling 16 kHz ;
- faster-whisper ;
- final segments ;
- optional Argos translation ;
- callbacks vers pipeline.

Important :

- Le PC transcrit pour BrainLive/archive.
- Le sous-titre/traduction live offline téléphone relève de `reflexvision`.
- Le fallback CPU est une sécurité, pas une preuve du chemin nominal GPU.

Tests :

- `tests/v19/test_audiort.py`

### `services/live-pc/audio_archive.py`

Classes :

- `AudioArchive`
- `AudioArchiveConfig`
- `ArchiveResult`

Fonctions :

- `write_segment_wav(...)`
- `evidence_root()`

Rôle :

- écrit WAV/segments ;
- écrit les événements/preuves audio compatibles Phone Bridge/BrainLive.

Invariant :

- L’archive VAD doit se faire même si ASR échoue ou retourne vide.

### `services/live-pc/conversation_bridge.py`

Classe :

- `ConversationBridge`

Méthodes :

- `ensure_session()`
- `bind_session()`
- `ingest_segment()`
- `tick()`
- `end_session()`

Rôle :

- crée/lie la session BrainLive ;
- possède le vrai `live_session_id` durable ;
- transforme les finals audio en turns/live buffer ;
- déclenche hot context/H1.

Piège :

- C’est ce `live_session_id` que CloseDay et les writers durables doivent partager.

### `services/live-pc/visionrt.py`

Classes/fonctions :

- `VisionRT`
- `YoloxDetector`
- `AdaptiveCadence`
- `KeyframeSelector`
- `OcrRoi`
- `VlmCrop`
- `default_keyframe_sink(...)`

Rôle :

- détection ;
- cadence adaptative ;
- OCR ROI ;
- VLM crop ;
- keyframes persistantes ;
- SceneDelta.

Config :

- `configs/profiles/rtx3070.yaml` bloc `vision`.
- `configs/MODEL_MANIFEST.yaml` modèle `detector`, `vlm`.

### `services/live-pc/worldbrain.py`

Classes :

- `WorldBrain`
- `Observation`
- `WorldEntity`
- `Relation`
- `ChangeEvent`

Rôle :

- entités monde ;
- last-seen ;
- relations spatiales ;
- changements ;
- summaries de session ;
- IDs d’entité stables inter-sessions depuis E60 (`stable_id` sans transport `session_id`).

Tables liées :

- `visual_events_v19`
- `scene_session_summaries_v19`
- `world_entity_links_v19`
- `brain2_spatial_routine_models`

Invariant :

- une même entité observable ne doit pas changer d’ID uniquement parce que le transport a créé une nouvelle session.

### `services/live-pc/brainlive_scene_adapter.py`

Classes/fonctions :

- `BrainLiveSceneAdapter`
- `build_hot_scene_context(...)`

Rôle :

- convertit le monde live en HotSceneContext ;
- précharge relation packs ;
- pousse spatial/object/task hot updates ;
- alimente delivery H1.

### `services/live-pc/intent_router.py`

Classes :

- `IntentRouter`
- `IntentContext`
- `RoutedIntent`

Méthodes :

- `on_transcript(...)`
- pré-routeur des contrôles de mode aide
- `_match_grammar(...)`
- `_llm_parse(...)`
- `_dispatch(...)`
- `_do_help_start(...)`
- `_do_vision(...)`
- `_do_device(...)`
- `_do_replay(...)`
- `_do_ask_memory(...)`

Rôle :

- convertit phrases finales/commandes en actions ;
- support grammar locale + LLM fallback ;
- gère “c’est quoi ça ?”, OCR, replay, device commands, cloud/local mode, mémoire ;
- démarre `HelpTaskEngine` et pré-route les contrôles actifs (« c’est fait », « répète »…) avant le parseur générique.

Risques :

- wake word/gated : tout audio va en mémoire, mais le routage d’intent peut être conditionné par `is_command`.
- un contrôle de plan actif ne doit pas être reclassé comme une nouvelle demande générique.

### `services/live-pc/help_mode.py`

Classe :

- `HelpTaskEngine`

Chemin :

- `IntentRouter._do_help_start()`
- `HelpTaskEngine.start_from_description()`
- `_guess_scene_context()` (un coup d’œil VLM au démarrage)
- `llm_router.complete_json()`
- `_adopt_plan()`
- `_enqueue(task_panel)` + `_emit_hot(task_anchor)`

Rôle :

- plan de micro-actions ;
- machine à états et reprise ;
- ghost N+1 ;
- grounding sur tracks par `label_en` ;
- watchdog d’indices ;
- persistance dans `help_mode_tasks` ;
- panel H1 + ancre hot.

Statut :

- PC/tests : proven selon E53 ;
- rendu/grounding sur device : `to_verify`.

Invariant :

- une ancre non groundée doit dégrader en guidance panel, pas inventer une position.

### `services/live-pc/delivery_adapter.py`

Classes :

- `DeliveryAdapter`
- `RendererHub`
- `WebSocketRendererHub`

Fonctions :

- `delivery_row_to_ui_intent(...)`
- `create_app(...)`

Rôle :

- consomme `brainlive_intervention_delivery_queue`;
- convertit en UIIntent ;
- pousse vers renderer ;
- reçoit UIReceipt.

Tests :

- `tests/v19/test_delivery_adapter.py`

### `services/live-pc/change_attention.py`

Classe :

- `ChangeAttention`

Rôle :

- compare zone courante vs mémoire de zone ;
- émet cue discret “quelque chose a changé ici” ;
- cooldown et anti-bruit ;
- surtout intra-session tant que `place_hint` stable n’est pas fourni.

Tests :

- `tests/v19/test_change_attention.py`

### `services/live-pc/clip_recorder.py`

Rôle :

- enregistre clips vidéo live via ffmpeg CPU libx264 ;
- queue bornée drop-on-full ;
- indexe clips dans `visual_evidence_assets_v19` ;
- tiering keep/drop au CloseDay.

Wiring V4 :

- construit et démarré par `phoneonly_runtime` ;
- injecté dans `AiortcIngress` via `clip_recorder` ;
- reçoit les frames depuis `gateway._consume_track()` ;
- l’ancien mismatch « code présent mais non branché » est résolu statiquement.

Config :

- `configs/profiles/rtx3070.yaml` bloc `clip_recording`.

Tests :

- `tests/v19/test_clip_recorder.py`

Limite :

- capture Android réelle/replay complet : `to_verify`.

### `services/live-pc/media_retention.py`

Rôle :

- transcode audio post-close-day ;
- purge médias non référencés ;
- enforce budget disque ;
- ne supprime jamais les médias référencés par preuve.

Config :

- `configs/profiles/rtx3070.yaml` bloc `storage_quota`.

Tests :

- `tests/v19/test_media_retention.py`

## 5. Unity C# — runtime Android/XR

### Config

Fichier :

- `apps/xr-mobile/Assets/Scripts/Core/MLOmegaConfig.cs`

Types :

- `MLOmegaConfig`
- `PcEndpoint`
- `XrAdapterKind`
- `ReflexAsrLanguage`

Rôle :

- endpoints PC ;
- mode PhoneOnly/XREAL/sim ;
- paramètres capture ;
- wake word ;
- ASR/reflex ;
- config transport ;
- liens scène.

Asset principal :

- `apps/xr-mobile/Assets/Config/MLOmegaPhoneOnly.asset`

### Capture téléphone

Fichiers :

- `PhoneOnlyAdapter.cs`
- `EyeCaptureSource.cs`
- `PhoneCameraPreview.cs`
- `PosePublisher.cs`

Rôle :

- `PhoneOnlyAdapter` ouvre caméra arrière via `WebCamTexture`.
- `EyeCaptureSource` publie frames + `FrameEnvelope`.
- `PhoneCameraPreview` affiche caméra sur téléphone.
- `PosePublisher` fournit pose approximative si disponible.
- `FrameEnvelope.pose_valid` indique explicitement si cette pose est exploitable ; le PC refuse de spatialiser une pose neutre/invalide.

Flux :

```text
PhoneOnlyAdapter.TryGetLatestFrame()
  → EyeCaptureSource.Update()
  → EyeCaptureSource.OnFrame
  → LiveTransportBridge.HandleFrame()
  → Kotlin pushTexture/pushI420
```

### Pairing/session

Fichiers :

- `SessionPairing.cs`
- `SessionHubClient.cs`
- `ClockSync.cs`

Rôle :

- endpoints ordonnés LAN/Tailscale ;
- `/health` ;
- create/renew ;
- clock sync ;
- credentials persistés Android ;
- choix `ActiveBaseUrl`.

Piège :

- le transport doit construire `/webrtc/offer` depuis `ActiveBaseUrl`, pas une URL statique.

### Transport

Fichiers :

- `LiveTransportBridge.cs`
- `PhoneOnlySessionCoordinator.cs`

`LiveTransportBridge` :

- crée `LiveTransportPlugin` Kotlin ;
- transmet credentials/endpoint ;
- pousse frames texture ou CPU I420 ;
- envoie transcript device ;
- reçoit DataChannel messages ;
- expose stats/state ;
- supporte `DetachPcmFeed` au teardown ;
- sépare UIIntent, `device_command`, `device_command_result`, `tts_audio` et `scene_delta`.

`PhoneOnlySessionCoordinator` :

- attend pairing ;
- démarre transport ;
- distingue arrêt volontaire vs coupure ;
- envoie `/session/end` ;
- poll `/session/status` ;
- affiche bouton minimal `OnGUI` si configuré.

### Model provisioning

Fichiers :

- `ModelProvisioningBridge.cs`
- `StreamingAssetsModelInstaller.cs`

Rôle :

- copie petits modèles embarqués depuis StreamingAssets ;
- après pairing, télécharge modèles manquants depuis PC ;
- vérifie SHA ;
- expose progression à StatusBar ;
- ne re-arme pas à chaud les pipelines micro par sécurité.

### UI runtime

Fichiers :

- `UIIntentBroker.cs`
- `UIRuntime.cs`
- `TransportIntentSource.cs`
- `UIReceiptTransportSink.cs`
- `SceneDeltaTransportHandler.cs`
- `EntityHotUpdateHandler.cs`
- `DeviceCommandHandler.cs`
- `TtsAudioPlayer.cs` ;
- `PanelManipulator.cs`, `IManipulablePanel.cs`, `ManipulablePanelRegistry.cs` ;
- composants dans `UI/Components`, dont `TaskAtoms/`, `TaskPanelComponent` et `TaskAnchorComponent`.

Rôle :

- consomme UIIntent ;
- applique density/privacy ;
- rend sous-titres/cards/tags/task/lens/virtual screen ;
- renvoie receipts ;
- applique scene_delta dans SceneCache ;
- exécute `device_command` et renvoie `device_command_result` ;
- joue `tts_audio` ;
- rend `task_panel`/`task_anchor` ;
- manipule les panels par pinch claimé, sinon laisse le fallback LensWindow.

### Scene cache

Fichiers :

- `SceneCache.cs`
- `LocalTrackStore.cs`
- `EntityHotUpdate.cs`
- `TemplateTracker.cs`

Rôle :

- état local chaud ;
- tracks visuels ;
- entities/spatial/tasks/translation/ui ;
- vieillissement TTL ;
- point d’accrochage des UI.

## 6. Kotlin Android — livetransport

Répertoire :

- `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/`

### `LiveTransportPlugin.kt`

Méthodes clés :

- `start(...)`
- `stop()`
- `updateCredentials(...)`
- `sendContractMessage(...)`
- `attachPcmFeed(...)`
- `connectLoop()`
- `establish()`
- `addAudioTrack()`
- `addVideoTrack()`
- `createOfferSuspending()`
- `teardownPeer()`

Rôle :

- PeerConnection ;
- audio track ;
- video track ;
- DataChannel ;
- reconnect/backoff ;
- stats/adaptive bitrate/resolution ;
- envoie offer à PC.

### `LiveTransportConfig.kt`

Types :

- `LiveTransportConfig`
- `IceServerConfig`
- `VideoConfig`
- `AudioConfig`
- `BackoffConfig`
- `AdaptiveConfig`

Rôle :

- contrat config Unity → Kotlin.

### `SignalingClient.kt`

Rôle :

- résout endpoint ;
- `exchangeOffer(...)` vers `/webrtc/offer`.

### Vidéo

Fichiers :

- `VideoFrameFeeder.kt`
- `UnityPushVideoFeeder.kt`
- `UnityFrameCapturer.kt`
- `SdpCodecPreference.kt`

Rôle :

- reçoit texture ou I420 depuis Unity ;
- construit frames WebRTC ;
- préfère codec vidéo ;
- configure Opus ptime/DTX côté SDP.

### Audio / micro unique

Fichiers :

- `MicAudioFanout.kt`
- `PcmFeed.kt`

Rôle :

- décode samples PCM16 depuis le module audio WebRTC ;
- fan-out vers réflexes sans ouvrir un second micro.

Piège :

- un double `AudioRecord` WebRTC + sherpa est interdit pour le chemin nominal.

Tests :

- `MicAudioFanoutTest.kt`

### Credentials/session

Fichier :

- `SessionCredentialStore.kt`

Rôle :

- stocke session/token via Android Keystore/AES-GCM ;
- permet renew après redémarrage.

### Provisioning modèles

Fichiers :

- `ModelProvisioner.kt`
- `DeviceModelManifest.kt`
- `ModelProvisioningCallbacks.kt`

Rôle :

- récupère manifest PC ;
- télécharge modèles ;
- vérifie SHA ;
- extraction tar.bz2 ;
- atomic rename ;
- protège zip-slip ;
- normalise dossiers sherpa.

Tests :

- `ModelProvisionerCoreTest.kt`
- `DeviceModelManifestTest.kt`

## 7. Kotlin Android — reflexvision

Répertoire :

- `apps/xr-mobile/android/reflexvision/src/main/java/com/mlomega/xr/reflexvision/`

### ASR/KWS

Fichiers :

- `AsrKwsService.kt`
- `AsrKwsConfig.kt`
- `AsrKwsConfigFactory.kt`
- `AsrKwsCallbacks.kt`
- `WakeWordMatcher.kt`
- `CommandWindow.kt`
- `KeywordEncoder.kt`

Rôle :

- sherpa streaming ASR ;
- KWS anglais existant ;
- détection du wake word dans les finals ASR français via `WakeWordMatcher.matches()` ;
- VAD ;
- fenêtre de commande ;
- `setWakeWord` à chaud via JNI ;
- flag `is_command` pour le PC ;
- tout l’audio continue vers mémoire même hors commande.

Source de vérité :

- `configs/user_profile.yaml` clé `wake_word` ; défaut V4 : `viki`.

Tests :

- `CommandWindowTest.kt`
- `KeywordEncoderTest.kt`
- `WakeWordMatcherTest.kt`

Limite :

- modèle/device réel et changement runtime acquitté : `to_verify`.

### Gestes

Fichiers :

- `GesturePipeline.kt`
- `GestureStateMachine.kt`
- `GestureConfig.kt`
- `GestureCallbacks.kt`
- `FrameThrottle.kt`

Rôle :

- MediaPipe LIVE_STREAM ;
- hand landmarks ;
- palm/swipe/pinch ;
- throttle fps ;
- événements vers Unity.

Tests :

- `GesturePipelineActivationTest.kt`
- `GestureStateMachineTest.kt`
- `FrameThrottleTest.kt`

### Traduction offline

Fichiers :

- `OfflineTranslator.kt`
- `OfflineTranslatorBridge.kt`
- `MarianTokenizer.kt`

Rôle :

- ONNX Runtime ;
- OPUS-MT fr-en/en-fr ;
- finals ASR seulement ;
- lazy load ;
- idle release ;
- une direction résidente à la fois.

Tests :

- `OfflineTranslatorTest.kt`
- `OfflineTranslatorIntegrationTest.kt`
- `MarianTokenizerTest.kt`

### App launcher

Fichier :

- `AppLauncher.kt`

Rôle :

- ouvre Maps ;
- YouTube ;
- package Android.

## 8. Contrats partagés

Répertoire :

- `packages/contracts/schemas/`
- `packages/contracts/python/models.py`
- `packages/contracts/csharp/`
- `packages/contracts/generate_csharp.py`

Contrats :

- `FrameEnvelope` — metadata frame/capture ; champ additif `pose_valid` gate la spatialisation.
- `EvidenceEvent` — preuve/événement.
- `HotSceneContext` — contexte live pour UI/BrainLive.
- `LocalTrack` — track local device.
- `ReflexEvent` — signal réflexe device.
- `SceneDelta` — mise à jour scène.
- `UIIntent` — commande UI sémantique PC → device, incluant `task_panel`/`task_anchor`.
- `UIReceipt` — feedback device → PC.
- `device_command set_wake_word {word, command_id}` — PC → Unity/Kotlin.
- `device_command_result {command_id, action, ok}` — device → PC.
- `tts_audio` — audio TTS PC → consommateur Unity `TtsAudioPlayer`.

Tests :

- `tests/v19/test_contracts.py`
- `tests/v19/test_csharp_generator.py`
- `scripts/validate_contracts_v19.py`

Règle :

- Changer un champ impose de vérifier : schema JSON, modèle Python, modèle C#, parsing Unity, producteurs PC, consommateurs Unity/Kotlin éventuels, tests.
- Les types DataChannel non-UI ne doivent pas passer par le parseur `UIIntent`.

## 9. Cœur mémoire V18/V19

### Base / API

Fichiers :

- `src/mlomega_audio_elite/db.py`
- `src/mlomega_audio_elite/api.py`
- `src/mlomega_audio_elite/cli.py`

`api.py` expose l’API historique MemoryLight :

- `/health`
- `/ingest/transcript`
- `/ingest/audio`
- `/voice/enroll`
- `/voice/match`
- `/query`
- `/consolidate`
- `/ingest/visual-event`
- `/ingest/scene-summary`
- `/memory/correction-visual`
- `/xr/session-health`
- `/self-schema`
- `/evidence/request-clip`

Attention :

- Cette API historique n’est pas le SessionHub PhoneOnly.

### Delivery / live policy

Fichiers :

- `v18_delivery.py`
- `v18_8_live_policy.py`

Fonctions clés :

- `enqueue_delivery(...)`
- `record_delivery_feedback(...)`
- `materialize_intervention_outcome_observation(...)`
- `plan_live_dispatch(...)`
- `plan_image_capture(...)`

Tables :

- `brainlive_intervention_delivery_queue`
- `brainlive_intervention_delivery_dedupes`
- `brainlive_intervention_feedback_events_v188`
- `brainlive_intervention_outcomes_v188`
- `brainlive_live_dispatch_state_v188`
- `brainlive_image_work_queue_v188`
- `brainlive_live_visual_state_v188`

Règle :

- H1/delivery passe par la queue existante ; ne pas créer une queue parallèle sauf décision explicite.

### BrainLive session / turns

Fichiers importants :

- `brainlive_realtime_v15_2.py`
- `brainlive_hotloop_v15_6.py`
- `brainlive_daemon_v15_3.py`
- `conversation_bridge.py` côté live-pc.

Tables :

- `brainlive_sessions`
- `brainlive_turn_buffer`
- `brainlive_audio_chunks`
- `brainlive_signal_events`
- `brainlive_intervention_delivery_queue`

Invariant :

- Le temps d’un turn vient de `start_s` + contexte conversation/session. Pas de `turns.created_at`.

### CloseDay durable

Fichier :

- `v18_close_day.py`

Fonctions :

- `close_brainlive_day(...)`
- `close_day_status(...)`
- `_run_stage(...)`
- `_resolve_context(...)`

Tables :

- `v18_close_day_runs`
- `v18_pipeline_stages`

Rôle :

- orchestre post-stop + longitudinal + coordination + life model + stages V19 ;
- checkpoint/reprise ;
- idempotence par person/date/run/stages.

Piège :

- Ne pas purger/recréer un jour pour “réparer” un run sans décision explicite.

### Post-stop deep flow

Fichier :

- `brainlive_poststop_deep_flow_v15_15.py`

Fonction :

- `run_brainlive_post_stop_deep_flow(...)`

Phases :

- assembly ;
- export bundles ;
- deep audio ;
- deep vision ;
- Brain2/V15 ;
- silent life.

### Event assembly

Fichier :

- `brainlive_event_assembler_v15_14.py`

Fonctions :

- `collect_live_raw_timeline(...)`
- `assemble_event_bundles(...)`
- `export_event_bundles_to_brain2(...)`
- `run_brainlive_event_assembly(...)`

Tables :

- `brainlive_raw_timeline_v1514`
- `brainlive_event_bundles_v1514`
- `brainlive_brain2_event_exports_v1514`
- `brainlive_event_assembly_runs_v1514`

Rôle :

- transforme timeline multi-capteurs en bundles.
- limite de bundle contrôlée par config/env.

### Deep audio nocturne

Fichier :

- `brainlive_offline_deep_audio_v18_5.py`

Fonction :

- `run_offline_deep_audio_for_bundles(...)`

Tables :

- `brainlive_deep_audio_runs_v185`
- `brainlive_deep_audio_artifacts_v185`

Rôle :

- recolle les segments audio ;
- deep transcription/diarisation ;
- reconcile speaker ;
- export refined bundles.

### Deep vision nocturne

Fichier :

- `brainlive_offline_deep_vision_v16_1.py`

Fonctions :

- `select_keyframes_for_bundle(...)`
- `run_offline_deep_vision_for_bundles(...)`
- `append_deep_vision_context_turns_to_brain2(...)`

Tables :

- `brainlive_deep_vision_runs_v161`
- `brainlive_deep_vision_observations_v161`
- `brainlive_deep_vision_brain2_exports_v161`

Rôle :

- VLM lourd de nuit sur keyframes de bundles, pas vidéo brute exhaustive.

### Life Model / governance

Fichiers :

- `v18_life_model.py`
- `brain2_life_model_v15_10.py`
- `brain2_life_model_updater_v15_13.py`
- `v19_life_model_store.py`
- `v19_self_schema.py`

Rôle :

- preuves approuvées ;
- strates Life Model ;
- patchs ;
- V19 entries ;
- self schema.

Point dur :

- Toute nouvelle table servant de preuve doit être approuvée dans les sources de preuve. Sinon gouvernance doit refuser.

### LLM hardening

Fichier :

- `v18_runtime_hardening.py`

Fonctions :

- `ensure_llm_decision_run(...)`
- `claim_llm_decision_run(...)`
- `finish_llm_decision_run(...)`
- `validate_semantic_output(...)`
- `validate_resolvable_manifest_evidence(...)`

Tables :

- `v18_llm_decision_runs`
- `v18_llm_decision_attempts`
- `v18_episode_capsules`
- `v18_llm_evidence_requests`

Règle :

- Sortie LLM tronquée/partielle = rejet atomique, pas application partielle.

### V19 visual

Fichiers :

- `v19_visual_store.py`
- `v19_visual_context.py`
- `v19_keyframes.py`
- `worldbrain.py`
- `visionrt.py`

Tables :

- `visual_evidence_assets_v19`
- `visual_events_v19`
- `world_entity_links_v19`
- `scene_session_summaries_v19`
- `ui_interaction_outcomes_v19`
- `help_mode_tasks`
- `brain2_spatial_routine_models`
- `brain2_visual_task_models`
- `brain2_ui_preference_models`

Rôle :

- preuves visuelles ;
- résumés scène ;
- last-seen ;
- routines spatiales ;
- UI outcomes.

### V19 predictions/outcomes

Fichiers :

- `v19_prediction_loop.py`
- `v19_outcome_watcher.py`
- `v18_predictive_retrieval.py`

Tables :

- `predictions_v19`
- `prediction_outcomes_v19`
- `v18_predictive_case_vector_manifest`
- `v18_predictive_similarity_labels`
- `v18_predictive_similarity_calibrations`

Rôle :

- prédictions ;
- vérification/refutation ;
- calibration similarité ;
- Qdrant.

## 10. Modèles/configs

### `configs/MODEL_MANIFEST.yaml`

Entrées PC :

- `live_llm` — Ollama `qwen3.5:4b`.
- `deep_llm` — Ollama `qwen3.5:9b`.
- `vlm` — live VLM léger `moondream`.
- `vlm_heavy` — VLM nuit `qwen2.5vl:7b`.
- `detector` — YOLOX nano ONNX.
- `asr` — faster-whisper `small`, int8.
- `face_detector` — YuNet.
- `face_embedder` — SFace.
- `translate` — Argos PC optionnel.
- `tts_fr`, `tts_en` — sherpa/Piper voices.

Entrées device :

- `asr_stream_en`
- `asr_stream_fr`
- `kws_en`
- `hand_landmarker`
- `gesture_recognizer`
- `silero_vad`
- `translate_fr_en_*`
- `translate_en_fr_*`

Règles :

- Les gros modèles device ne sont pas censés gonfler l’APK ; provisioning via PC.
- Les petits modèles peuvent être embarqués/copied StreamingAssets.
- Hash SHA attendu côté manifest/provisioning.

### `configs/profiles/rtx3070.yaml`

Blocs importants :

- `video` — ports/résolution/fps.
- `vision` — cadence/detector/keyframes/OCR/VLM.
- `audio` — target sample rate, VAD, ASR.
- `storage_quota` — budget 100 Go, purge non référencée, transcode audio.
- `clip_recording` — clips CPU x264, queue bornée, segment.
- `gpu` — budgets VRAM.

### `.env`

Rôle :

- chemins ;
- tokens ;
- modèles/env overrides ;
- context Ollama ;
- HF token ;
- ports/host.

Ne pas l’écrire dans docs/logs. Ne pas supposer présent sur machine propre.

## 11. Flows détaillés

### A. Création session PhoneOnly

```text
Unity PhoneOnlyScene
  → PermissionGate
  → SessionPairing.OnEnable()
  → ResolveActiveEndpoint()
  → SessionHubClient /health
  → restore credentials Android
  → /session/renew si possible
  → sinon /session/create
  → /session/clock-sync
  → PairingState.Paired
  → PhoneOnlySessionCoordinator.TryStartTransport()
  → LiveTransportBridge.StartTransport()
```

Vérifications :

- `ActiveBaseUrl` doit être source de vérité.
- Les credentials renouvelés doivent être propagés à Kotlin.
- Failover réseau ne doit pas terminer la session.

### B. WebRTC setup

```text
LiveTransportBridge.BuildConfig()
  → LiveTransportPlugin.start(config)
  → LiveTransportPlugin.establish()
  → addAudioTrack()
  → addVideoTrack()
  → createOfferSuspending()
  → SignalingClient.exchangeOffer()
  → PC POST /webrtc/offer
  → sessionhub_http creates/gets runtime
  → AiortcIngress.handle_offer_sdp()
  → answer SDP
```

Vérifications :

- Opus track existe.
- Video track existe.
- DataChannel ouvert.
- ICE gathering non-trickle traité.
- reconnect tear down avant peer neuf.

### C. Vidéo live

```text
WebCamTexture
  → PhoneOnlyAdapter.TryGetLatestFrame()
  → EyeCaptureSource.OnFrame(frame,envelope pose_valid)
  → LiveTransportBridge.HandleFrame()
  → Kotlin UnityPushVideoFeeder
  → WebRTC video + FrameEnvelope DataChannel
  → gateway._consume_track(video)
      → ClipRecorder.offer() best-effort
      → envelope matcher
  → LatestFrameQueue
  → LivePipeline.run_video()
  → pose_valid gate
  → VisionRT.process_frame() via asyncio.to_thread si nécessaire
  → WorldBrain.ingest_scene_delta() (stable_id inter-session)
  → SceneAdapter/Delivery/UIIntent
  → DataChannel
  → Unity UIIntentBroker/SceneCache
```

À tester :

- frame reçue/traitée/dropped ;
- pose invalide non spatialisée ;
- keyframe et clip écrits ;
- stable entity ID après nouvelle session ;
- scene_delta consommé ;
- UI visible téléphone.

### D. Audio live

```text
Android microphone
  → WebRTC JavaAudioDeviceModule
  → MicAudioFanout same PCM
      ↘ AsrKwsService local reflex
      ↘ WebRTC Opus
  → aiortc audio track
  → gateway._audio_frame_to_mono()
  → LivePipeline.on_audio_chunk(samples, src_rate)
  → AudioRT.push_audio()
  → VAD segment
  → faster-whisper final
  → ConversationBridge.ingest_segment()
  → BrainLive turn buffer
  → AudioArchive.archive_segment()
```

E60 :

- `PhoneOnlyReflexSignalSource` active réellement le scheduler prod ;
- `DetachPcmFeed` nettoie le branchement ;
- `AsrBridge.ownMicrophone` est un fallback dégradé, jamais concurrent du fan-out nominal.

À prouver :

- micro Android → Opus → aiortc ;
- ASR local et PC ;
- turn BrainLive/WAV ;
- activation prod des réflexes ;
- pas de double micro.

### E. Réflexes device

Activation production :

```text
PhoneOnlyReflexSignalSource
  → ReflexScheduler.RaiseSignal
  → ASR / gestes / traduction / sous-titres / skills locaux
```

Wake word :

```text
MicAudioFanout PCM
  → AsrKwsService.decodeSegment()
  → WakeWordMatcher.matches(final FR) ou KWS existant
  → openCommandWindow + onWakeWord
  → final transcript is_command=true
  → LiveTransportBridge.SendTranscriptSegment()
  → PC IntentRouter si policy l’autorise
```

Configuration runtime :

```text
user_profile.yaml wake_word
  → LivePipeline.push_wake_word()
  → device_command set_wake_word + command_id
  → DeviceCommandHandler
  → AsrBridge.SetWakeWord
  → JNI setWakeWord
  → device_command_result
  → ack/retry PC
```

Gestes/panels :

```text
EyeCaptureSource.OnFrame
  → GestureBridge
  → GesturePipeline / GestureStateMachine
  → pinch(x,y)
  → PanelManipulator claim/hit-test
      ↘ IManipulablePanel move/resize/close/minimise
      ↘ sinon LensWindowSkill zoom
```

À valider sur device : modèles, wake word, changement runtime, sous-titres/traduction, gestes/panels, stabilité micro.

### F. UI / aide / TTS / receipts

Delivery classique :

```text
BrainLive/WorldBrain/IntentRouter
  → v18_delivery.enqueue_delivery()
  → brainlive_intervention_delivery_queue
  → PhoneOnlyRuntime._delivery_loop()
  → DataChannelRenderer.push(UIIntent)
  → LiveTransportBridge.OnNativeMessage()
  → TransportIntentSource → UIIntentBroker → UI components
  → UIReceiptTransportSink
  → PhoneOnlyRuntime._on_receipt()
  → v18_8_live_policy.record_delivery_feedback()
```

Mode aide :

```text
IntentRouter._do_help_start
  → HelpTaskEngine.start_from_description
  → one-shot VLM scene glance
  → LLM structured micro-plan
  → help_mode_tasks
  → task_panel (queue H1) + task_anchor (hot)
  → TaskAtoms / SceneCache.Tracks
```

TTS :

```text
LivePipeline(enable_tts=True)
  → tts_audio DataChannel
  → Unity TtsAudioPlayer
```

Pièges :

- pas de DataChannel = ne pas déclarer delivered/displayed ;
- une ancre non groundée ne doit pas inventer une position ;
- `tts_audio` et `device_command_result` ne sont pas des UIIntent.

### G. Fin explicite et CloseDay

```text
User clicks Terminer
  → PhoneOnlySessionCoordinator.EndExplicitly()
  → POST /session/end with session_id+token
  → PhoneOnlyRuntime.end_session_only()
  → ingress.stop_accepting_media()
  → drain audio/video callbacks
  → DetachPcmFeed
  → AudioRT.flush()
  → LivePipeline.end_session()
  → ConversationBridge.end_session()
  → DB-backed _completed_close_day_exists()
  → run_phoneonly_close_day.py in .venv
  → v18_close_day.close_brainlive_day()
  → /session/status polls progress
```

Fallback : watchdog CloseDay après fin explicite si le déclenchement normal a été perdu.

Non-déclencheurs : WebRTC disconnected, perte réseau, Android sleep, `OnDisable`, crash.

### H. CloseDay / nuit

```text
v18_close_day.close_brainlive_day()
  → post_stop
      → event assembler
      → deep audio
      → deep vision
  → longitudinal / coordination / life_model / live_ready
  → visual_consolidation (Europe/Paris)
  → outcome_resolution / prediction_emission / self_schema
  → manifest re-read des tables finales
  → media_retention / clip tiering best-effort
```

Règles :

- checkpoints `v18_pipeline_stages` ;
- idempotence et même-jour décidés par DB ;
- no partial LLM output ;
- preuves approuvées ;
- pas de purge automatique de preuve référencée.

## 12. Tables persistantes par domaine

### Live/session/audio

- `brainlive_sessions`
- `brainlive_turn_buffer`
- `brainlive_audio_chunks`
- `brainlive_signal_events`
- `turns`
- `audio_segments`
- `audio_preprocess_runs`
- `audio_timestamp_maps`

### Delivery/UI

- `brainlive_intervention_delivery_queue`
- `brainlive_intervention_delivery_dedupes`
- `brainlive_intervention_feedback_events_v188`
- `brainlive_intervention_outcomes_v188`
- `ui_interaction_outcomes_v19`

### CloseDay/stages

- `v18_close_day_runs`
- `v18_pipeline_stages`
- `brainlive_day_packages`
- `brainlive_event_bundles_v1514`
- `brainlive_raw_timeline_v1514`
- `brainlive_brain2_event_exports_v1514`

### Deep audio/vision

- `brainlive_deep_audio_runs_v185`
- `brainlive_deep_audio_artifacts_v185`
- `brainlive_deep_vision_runs_v161`
- `brainlive_deep_vision_observations_v161`
- `brainlive_deep_vision_brain2_exports_v161`

### Visual/world

- `vision_frames`
- `raw_assets`
- `visual_evidence_assets_v19`
- `visual_events_v19`
- `world_entity_links_v19`
- `scene_session_summaries_v19`
- `brain2_spatial_routine_models`
- `brain2_visual_task_models`
- `brain2_ui_preference_models`

### Identity

- `face_people`
- `face_embeddings`
- `self_voice_profile`
- `voice_clusters`
- `voice_observations`
- `voice_identity_revisions`
- `v14_5_people_identity_hypotheses`
- `v14_5_people_context_profiles`

### Life model / predictions

- `brain2_life_model_exports`
- `brain2_life_model_patch_runs`
- `brain2_life_model_patch_operations`
- `brain2_life_model_strata`
- `brain2_life_model_item_lifecycle`
- `life_model_entries_v19`
- `self_schema_v19`
- `predictions_v19`
- `prediction_outcomes_v19`

### LLM/governance

- `v18_llm_decision_runs`
- `v18_llm_decision_attempts`
- `v18_episode_capsules`
- `v18_llm_evidence_requests`
- `v18_capsule_prompt_renderings`
- `v18_rejected_llm_references`

### Vector/Qdrant

- `vector_sync_manifest`
- `vector_sync_manifest_v18`
- `v18_predictive_case_vector_manifest`
- `v18_predictive_similarity_labels`
- `v18_predictive_similarity_calibrations`
- Qdrant externe port 6333.

## 13. Tests et ce qu’ils couvrent

### Runtime PC / PhoneOnly

- `test_phoneonly_runtime.py` — runtime, end, CloseDay, metrics, delivery.
- `test_sessionhub_http.py` — HTTP, auth, session status, routes.
- `test_sessionhub.py` — session/token store.
- `test_transport_webrtc.py` — WebRTC/aiortc.
- `test_transport.py` — transport abstrait.
- `test_device_provisioning.py` — manifest/download modèles device.
- `test_wake_word_gating.py` — gated/open policy.

### Audio/vision/world

- `test_audiort.py` — VAD/ASR/flush.
- `test_visionrt.py` — detector/keyframe/focus.
- `test_e27_pipeline.py` — pipeline live.
- `test_e28_worldbrain.py` — worldbrain.
- `test_change_attention.py` — cue changement.
- `test_clip_recorder.py` — clips.
- `test_media_retention.py` — budget/purge/transcode.

### BrainLive / mémoire

- `test_e31_conversation.py`
- `test_e32_identity.py`
- `test_e33_intents.py`
- `test_e34_proactivity.py`
- `test_e35_outputs.py`
- `test_e36_ops.py`
- `test_e37_nightly.py`
- `test_e38_fine_intel.py`
- `test_multi_session_close_day.py`
- `test_longitudinal_periods.py`
- `test_life_model_v19.py`
- `test_life_model_empty_day.py`
- `test_personal_model_schema_bootstrap.py`
- `test_v18_turn_schema_invariant.py`

### Contracts/build/scripts

- `test_contracts.py`
- `test_csharp_generator.py`
- `test_scripts_profile.py`
- `test_ollama_context_budget.py`
- `test_gpu_arbiter.py`

### Kotlin JVM

`livetransport` :

- `SdpCodecPreferenceTest.kt`
- `ModelProvisionerCoreTest.kt`
- `MicAudioFanoutTest.kt`
- `DeviceModelManifestTest.kt`

`reflexvision` :

- `CommandWindowTest.kt`
- `KeywordEncoderTest.kt`
- `WakeWordMatcherTest.kt`
- `GesturePipelineActivationTest.kt`
- `GestureStateMachineTest.kt`
- `FrameThrottleTest.kt`
- `OfflineTranslatorTest.kt`
- `OfflineTranslatorIntegrationTest.kt`
- `MarianTokenizerTest.kt`

### Unity

Résultats présents :

- `editmode_results.xml`
- `apps/xr-mobile/editmode-e48.xml`

Tests Unity à relancer quand C#/scène/build changent.

## 14. État produit documenté dans le backlog

Lire `docs/PROD_BACKLOG.md`, `docs/EXECUTOR_BUILD_GUIDE.md`, `docs/DECISIONS.md` pour l’état exact, mais résumé de navigation :

- E39 — invariant `turns` sans `created_at`.
- E40 — `live_session_id` BrainLive unique.
- E41 — barrière de fin/drain/flush.
- E42 — PCM Opus/aiortc/event loop.
- E43 — end-session + CloseDay asynchrone.
- E44 — transport Android.
- E45 — scène PhoneOnly séparée.
- E46 — PC/GPU/Ollama/CloseDay/build APK.
- E47 — gates Android-local : micro fan-out, wake word, gestes, multi-sessions.
- E48-A — provisioning modèles app, Tailscale config, traduction live device, couche reflex PhoneOnly.
- E48-B — ChangeAttention live.
- E49 — XREAL code/build, validation lunettes physique en attente.
- E50 — dashboard mémoire lecture seule.
- E51 — assistant bienvenue/installateur.
- E52 — README complet.
- E53 — mode aide universel différé.
- E54 — rétention médias/budget disque.
- E55 — clips vidéo/tiering.
- E56 — VLM lourd nuit + trous one-click.

Toujours vérifier le checkout, car backlog peut être en avance/retard par rapport au code.

## 15. Fausses pistes connues

- `simulators/fake_xr_device.py` prouve SimOnly, pas PhoneOnly.
- `apps/companion-web/` n’est pas l’app Android.
- G1/XREAL n’est pas PhoneOnly.
- `/health` historique API core n’est pas `/health` SessionHub PhoneOnly.
- AAR présent dans Unity ne prouve pas que Unity l’appelle.
- Test JVM Kotlin ne prouve pas le JNI Unity.
- APK buildé ne prouve pas caméra/micro/permissions sur S25.
- `CloseDay completed` synthétique ne prouve pas l’action Android end→CloseDay.
- Modèle dans manifest ne prouve pas qu’il est téléchargé sur le téléphone.
- Fallback CPU ne prouve pas GPU nominal.
- Ollama pull ne prouve pas contexte `num_ctx` correct.

## 16. Checklist agent avant modification

1. `git status --short` : identifier changements existants utilisateur/Claude.
2. Lire `REPO_MAP.md` pour localiser.
3. Lire les fichiers réels concernés.
4. Remonter appelants avec `rg`.
5. Vérifier tests existants qui couvrent la frontière.
6. Si fix : patch minimal.
7. Ajouter test ciblé si le pont n’était pas prouvé.
8. Relancer seulement les tests pertinents + smoke cohérent.
9. Mettre à jour docs si étape produit close.

Questions à poser au code :

- Qui appelle cette fonction ?
- Cette route a-t-elle un consommateur ?
- Ce payload est-il le même côté Unity/Kotlin/Python ?
- L’ID utilisé est-il transport ou BrainLive ?
- Le code tourne-t-il en `.venv` ou `.venv-live` ?
- Le test utilise-t-il fake/sim ou chemin matériel ?
- Que se passe-t-il si réseau coupe ?
- Que se passe-t-il si DataChannel absent ?
- Que se passe-t-il si sortie LLM tronquée ?
- Que se passe-t-il si modèle absent ?

## 17. Commandes utiles

```powershell
# Lancement PC réel
powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
ollama serve
powershell -ExecutionPolicy Bypass -File scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710

# SimOnly, pas matériel
powershell -ExecutionPolicy Bypass -File scripts\RUN_MLOMEGA_V19.ps1 -SimOnly

# Build plugins Android
powershell -ExecutionPolicy Bypass -File scripts\BUILD_ANDROID_PLUGINS.ps1

# Fetch modèles
.venv-live\Scripts\python.exe scripts\fetch_models_v19.py
.venv-live\Scripts\python.exe scripts\fetch_models_v19.py --device

# Dashboard
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1

# Tests ciblés exemples
.venv-live\Scripts\python.exe -m pytest tests\v19\test_phoneonly_runtime.py tests\v19\test_sessionhub_http.py
.venv-live\Scripts\python.exe -m pytest tests\v19\test_audiort.py tests\v19\test_transport_webrtc.py
.venv\Scripts\python.exe -m pytest tests\v19\test_v18_turn_schema_invariant.py
```

## 18. Ce que cette map ne garantit pas

- Elle ne prouve pas qu’un build actuel passe.
- Elle ne prouve pas qu’un S25 réel a validé le chemin.
- Elle ne remplace pas les docs d’étapes.
- Elle ne remplace pas `rg` et la lecture du code.
- Elle ne couvre pas ligne par ligne tout le cœur legacy V13→V18.

Elle sert à éviter que l’agent parte du mauvais arbre, du mauvais script, du mauvais runtime ou d’un faux chemin simulé.

## 19. V4 — Index preuve / navigation technique

La V4 expose la couche structurée fusionnée dans `repo_graph_v4.json`.

Contenu du JSON V4 :

- `tables` : 404 entrées, dont les 403 tables du scan statique précédent et `help_mode_tasks` fusionnée depuis la vérification E53 du `CREATE TABLE`.
- `flows` : 16 flows prioritaires avec entrée, chemin, payloads, tables, tests, risques.
- `modules` : 152 entrées Python + modules Unity/Kotlin critiques, avec symboles, routes, tables lues/écrites, tests détectés.
- `routes` : routes FastAPI détectées.
- `critical_invariants` : invariants globaux.

Règle de confiance :

- Pour les 403 tables héritées, `created_by`, `important_columns`, `primary_key`, `foreign_keys` viennent du scan `CREATE TABLE`. Pour `help_mode_tasks`, l’existence du `CREATE TABLE` est vérifiée par la session E53, mais le détail des colonnes doit être rafraîchi depuis le checkout.
- `writers` / `readers` viennent d’un scan SQL statique `INSERT/UPDATE/DELETE/FROM/JOIN`.
- `tests` sont des correspondances statiques par nom de table/module dans les fichiers de test.
- `unknown` / `to_verify` signifie : pas prouvé par scan statique.
- Les appels dynamiques, SQL construit par string interpolation, wrappers installés à runtime et writes indirects peuvent être sous-détectés.

### 19.1 Requêtes rapides dans `repo_graph_v4.json`

```powershell
# Voir une table
.venv-live\Scripts\python.exe -c "import json; j=json.load(open('repo_graph_v4.json',encoding='utf-8')); print([t for t in j['tables'] if t['name']=='brainlive_turn_buffer'][0])"

# Voir un flow
.venv-live\Scripts\python.exe -c "import json; j=json.load(open('repo_graph_v4.json',encoding='utf-8')); print([f for f in j['flows'] if f['id']=='live_audio'][0])"

# Voir un module
.venv-live\Scripts\python.exe -c "import json; j=json.load(open('repo_graph_v4.json',encoding='utf-8')); print([m for m in j['modules'] if m.get('module')=='services/live-pc/live_pipeline.py'][0])"
```

### 19.2 Tables critiques — exemples humains

Le catalogue complet est dans `repo_graph_v4.json.tables`. Ci-dessous : les tables à inspecter en premier sur PhoneOnly/BrainLive/CloseDay.

#### `turns`

```txt
table: turns
  created_by:
    - src/mlomega_audio_elite/db.py:<module>
  important_columns:
    - turn_id TEXT PRIMARY KEY
    - conversation_id TEXT NOT NULL
    - idx INTEGER NOT NULL
    - speaker_label TEXT
    - person_id TEXT
    - start_s REAL
    - end_s REAL
    - text TEXT NOT NULL
  foreign_keys:
    - FOREIGN KEY(conversation_id...)
  writers:
    - unknown by static scan
  readers:
    - services/live-pc/replay_service.py:_transcript
    - src/mlomega_audio_elite/behavior_v12.py:...
    - src/mlomega_audio_elite/vector_sync.py:...
  used_by_flows:
    - live_audio
    - memory_query
  tests:
    - tests/v19/test_v18_turn_schema_invariant.py
  risks:
    - must_not_depend_on_created_at
    - use start_s / conversation time
```

#### `brainlive_turn_buffer`

```txt
table: brainlive_turn_buffer
  created_by:
    - src/mlomega_audio_elite/brainlive_v15.py:<module>
  important_columns:
    - live_turn_id TEXT PRIMARY KEY
    - live_session_id TEXT NOT NULL
    - conversation_id TEXT
    - timestamp_start TEXT
    - timestamp_end TEXT
    - speaker_label TEXT
    - speaker_person_id TEXT
  readers:
    - src/mlomega_audio_elite/brainlive_event_assembler_v15_14.py:collect_live_raw_timeline
    - src/mlomega_audio_elite/brainlive_offline_deep_audio_v18_5.py:_find_live_turn_ids
    - src/mlomega_audio_elite/brainlive_realtime_v15_2.py:build_perception_snapshot
  used_by_flows:
    - live_audio
    - wake_word_command_routing
    - explicit_end_session
    - close_day
  tests:
    - tests/v19/test_e31_conversation.py
  risks:
    - live_session_id must be BrainLive durable id, not transport session_id
```

#### `brainlive_intervention_delivery_queue`

```txt
table: brainlive_intervention_delivery_queue
  created_by:
    - src/mlomega_audio_elite/brainlive_daemon_v15_3.py:<module>
    - src/mlomega_audio_elite/v18_delivery.py:<module>
  important_columns:
    - delivery_id TEXT PRIMARY KEY
    - live_session_id TEXT NOT NULL
    - candidate_id TEXT
    - message TEXT
    - action_type TEXT DEFAULT 'notify'
    - delivery_status TEXT DEFAULT 'queued'
  readers:
    - services/live-pc/delivery_adapter.py:poll_queued
    - src/mlomega_audio_elite/v18_8_live_policy.py:_delivery_row
  used_by_flows:
    - ui_delivery_receipt
  tests:
    - tests/v19/test_delivery_adapter.py
    - tests/v19/test_phoneonly_runtime.py
    - tests/v19/test_e31_conversation.py
  risks:
    - do not mark delivered/displayed without actual renderer/DataChannel success
    - live_session_id must be BrainLive durable id
```

#### `help_mode_tasks`

```txt
table: help_mode_tasks
  created_by:
    - services/live-pc/help_mode.py:<module>
  writers:
    - HelpTaskEngine._adopt_plan
  readers:
    - reprise/lookup du plan actif HelpTaskEngine
  used_by_flows:
    - help_mode
    - ui_delivery_receipt
  tests:
    - suite PC E53 (62 tests rapportés)
  risks:
    - le détail exact des colonnes doit être relu dans le checkout
    - ne pas casser la reprise du plan actif
    - ne pas inventer de grounding si le track manque
```

#### `v18_close_day_runs`

```txt
table: v18_close_day_runs
  created_by:
    - src/mlomega_audio_elite/v18_close_day.py:<module>
  important_columns:
    - close_day_id TEXT PRIMARY KEY
    - person_id TEXT NOT NULL
    - package_date TEXT NOT NULL
    - live_session_id TEXT
    - service_run_id TEXT
    - post_stop_run_id TEXT
    - status TEXT NOT NULL
    - cleanup_eligible INTEGER
  writers:
    - src/mlomega_audio_elite/v18_close_day.py:_save_close_day
  readers:
    - src/mlomega_audio_elite/v18_close_day.py:_load_existing_close_day
    - src/mlomega_audio_elite/operations_v18_8.py:recovery_status
  used_by_flows:
    - explicit_end_session
    - close_day
  tests:
    - tests/v19/test_multi_session_close_day.py
  risks:
    - idempotence/resume
    - do not purge/recreate runs casually
```

#### `v18_pipeline_stages`

```txt
table: v18_pipeline_stages
  created_by:
    - src/mlomega_audio_elite/governance_v18.py:<module>
  important_columns:
    - stage_id TEXT PRIMARY KEY
    - run_id TEXT NOT NULL
    - stage_name TEXT NOT NULL
    - required INTEGER
    - status TEXT
  writers:
    - src/mlomega_audio_elite/governance_v18.py:begin_or_resume_run
    - src/mlomega_audio_elite/governance_v18.py:start_stage
    - src/mlomega_audio_elite/governance_v18.py:finish_stage
  readers:
    - src/mlomega_audio_elite/governance_v18.py:assert_stages_complete
    - src/mlomega_audio_elite/brainlive_poststop_deep_flow_v15_15.py:run_brainlive_post_stop_deep_flow
  used_by_flows:
    - close_day
  risks:
    - idempotence/reprise
    - stale lease recovery
```

#### `vision_frames`

```txt
table: vision_frames
  created_by:
    - src/mlomega_audio_elite/brainlive_v15.py:<module>
  important_columns:
    - frame_id TEXT PRIMARY KEY
    - source_asset_id TEXT
    - conversation_id TEXT
    - live_session_id TEXT
    - captured_at TEXT NOT NULL
    - image_path TEXT
    - image_sha256 TEXT
  readers:
    - services/live-pc/replay_service.py:_keyframes
    - services/live-pc/media_retention.py:_keyframes
    - src/mlomega_audio_elite/brainlive_event_assembler_v15_14.py:collect_live_raw_timeline
    - src/mlomega_audio_elite/brainlive_offline_deep_vision_v16_1.py:_rehydrate_frame_paths
  used_by_flows:
    - live_video
    - visual_evidence_clips
    - close_day
  tests:
    - tests/v19/test_visionrt.py
    - tests/v19/test_media_retention.py
    - tests/v19/test_e37_nightly.py
  risks:
    - image_path must be persistent, not temp
    - referenced media must not be purged
```

#### `visual_events_v19`

```txt
table: visual_events_v19
  created_by:
    - src/mlomega_audio_elite/v19_visual_store.py:<module>
  important_columns:
    - visual_event_id TEXT PRIMARY KEY
    - person_id TEXT NOT NULL
    - live_session_id TEXT NOT NULL
    - event_type TEXT NOT NULL
    - occurred_at TEXT NOT NULL
    - asset_id TEXT
    - evidence_refs_json TEXT
  foreign_keys:
    - asset_id -> visual_evidence_assets_v19.visual_asset_id
  readers:
    - services/live-pc/replay_service.py:_events
    - services/live-pc/media_retention.py:_clip_fk_referenced
    - src/mlomega_audio_elite/v19_life_model_store.py:run_life_model_v19_stage
    - src/mlomega_audio_elite/v19_outcome_watcher.py:resolve_prediction_outcomes
  used_by_flows:
    - live_video
    - visual_evidence_clips
    - close_day
  tests:
    - tests/v19/test_memory_v19.py
    - tests/v19/test_media_retention.py
    - tests/v19/test_life_model_v19.py
  risks:
    - live_session_id must be BrainLive durable id
    - evidence media must be protected
```

#### `visual_evidence_assets_v19`

```txt
table: visual_evidence_assets_v19
  created_by:
    - src/mlomega_audio_elite/v19_visual_store.py:<module>
  important_columns:
    - visual_asset_id TEXT PRIMARY KEY
    - person_id TEXT NOT NULL
    - live_session_id TEXT NOT NULL
    - asset_kind TEXT NOT NULL
    - uri TEXT
    - sha256 TEXT
    - frame_id TEXT
    - clip_id TEXT
  readers:
    - services/live-pc/replay_service.py:_clips
    - services/live-pc/media_retention.py:_clips
    - services/live-pc/clip_recorder.py:_has_event_in_window
  used_by_flows:
    - live_video
    - visual_evidence_clips
  tests:
    - tests/v19/test_clip_recorder.py
  risks:
    - referenced media must not be purged
```

#### `brainlive_event_bundles_v1514`

```txt
table: brainlive_event_bundles_v1514
  created_by:
    - src/mlomega_audio_elite/brainlive_event_assembler_v15_14.py:<module>
  important_columns:
    - bundle_id TEXT PRIMARY KEY
    - person_id TEXT NOT NULL
    - package_date TEXT NOT NULL
    - live_session_id TEXT
    - start_time TEXT
    - end_time TEXT
    - bundle_kind TEXT NOT NULL
    - title TEXT
  writers:
    - src/mlomega_audio_elite/brainlive_event_assembler_v15_14.py:assemble_event_bundles
    - src/mlomega_audio_elite/brainlive_offline_deep_audio_v18_5.py:_export_refined_bundle
  readers:
    - src/mlomega_audio_elite/brainlive_offline_deep_audio_v18_5.py:run_offline_deep_audio_for_bundles
    - src/mlomega_audio_elite/brainlive_offline_deep_vision_v16_1.py:run_offline_deep_vision_for_bundles
    - src/mlomega_audio_elite/brain2_life_model_updater_v15_13.py:collect_life_model_delta
  used_by_flows:
    - close_day
  tests:
    - tests/v19/test_e37_nightly.py
```

#### `life_model_entries_v19`

```txt
table: life_model_entries_v19
  created_by:
    - src/mlomega_audio_elite/v19_life_model_store.py:<module>
  important_columns:
    - entry_id TEXT PRIMARY KEY
    - person_id TEXT NOT NULL
    - dimension TEXT NOT NULL
    - temporal_axis TEXT NOT NULL
    - statement TEXT NOT NULL
    - confidence REAL NOT NULL
    - status TEXT NOT NULL
    - evidence_refs_json TEXT
  writers:
    - src/mlomega_audio_elite/v19_life_model_store.py:_set_status
  readers:
    - src/mlomega_audio_elite/v19_prediction_loop.py:_candidate_entries
    - src/mlomega_audio_elite/v19_self_schema.py:rebuild_self_schema
    - src/mlomega_audio_elite/v19_life_model_store.py:run_life_model_v19_stage
  used_by_flows:
    - close_day
  tests:
    - tests/v19/test_life_model_v19.py
```

### 19.3 Flows V4 — traces concrètes

Les 16 flows complets sont dans `repo_graph_v4.json.flows`. IDs :

- `pairing_phoneonly`
- `webrtc_setup`
- `live_video`
- `live_audio`
- `wake_word_command_routing`
- `ui_delivery_receipt`
- `explicit_end_session`
- `close_day`
- `model_provisioning`
- `visual_evidence_clips`
- `memory_query`
- `contracts_python_csharp_kotlin`
- `help_mode`
- `reflex_activation`
- `tts_audio_delivery`
- `panel_manipulation`

Exemple critique :

```txt
flow: live_audio
  real_entry:
    - Android JavaAudioDeviceModule samples
    - aiortc audio track recv
  path:
    1. LiveTransportPlugin.kt:addAudioTrack
    2. MicAudioFanout.kt:dispatch
    3. gateway.py:AiortcIngress._consume_audio_track/_audio_frame_to_mono
    4. live_pipeline.py:LivePipeline.on_audio_chunk
    5. audiort.py:AudioRT.push_audio/flush
    6. conversation_bridge.py:ConversationBridge.ingest_segment
    7. audio_archive.py:AudioArchive.archive_segment
  payloads:
    - PCM16 samples
    - WebRTC Opus decoded AudioFrame
    - final transcript segment
    - speech_segment evidence
  tables_written:
    - brainlive_turn_buffer
    - brainlive_audio_chunks
    - turns
    - brainlive_signal_events
  output:
    - ASR final
    - BrainLive turn
    - WAV/speech archive
  tests:
    - tests/v19/test_audiort.py
    - tests/v19/test_transport_webrtc.py
    - tests/v19/test_e31_conversation.py
    - tests/v19/test_phoneonly_runtime.py
  risks:
    - Android mic → aiortc hardware boundary still requires real device proof
    - packed vs planar audio
    - archive must not depend on ASR success
    - flush order
```

Autre exemple :

```txt
flow: explicit_end_session
  real_entry:
    - User action Terminer
    - HTTP POST /session/end
  path:
    1. PhoneOnlySessionCoordinator.cs:EndExplicitly
    2. sessionhub_http.py:/session/end
    3. phoneonly_runtime.py:end_and_close_day/end_session_only
    4. gateway.py:stop_accepting_media/drain_audio
    5. live_pipeline.py:end_session
    6. audiort.py:flush
    7. conversation_bridge.py:end_session
  payloads:
    - session_id+token
    - end/status JSON
  tables_written:
    - brainlive_sessions
    - brainlive_turn_buffer
  tables_read:
    - v18_close_day_runs
  output:
    - live pipeline ended once
    - CloseDay job starts async
    - status pollable
  tests:
    - tests/v19/test_phoneonly_runtime.py
    - tests/v19/test_sessionhub_http.py
  risks:
    - network disconnect must not call this path
    - drain callbacks in flight
    - idempotence
```

### 19.4 Modules V4

`repo_graph_v4.json.modules` contient 152 entrées.

Chaque module a :

```txt
module
  role
  main_symbols
  called_by
  calls
  routes
  contracts
  tables.reads
  tables.writes
  tests
  invariants
```

Limite volontaire :

- `called_by` / `calls` est `unknown` pour beaucoup de modules Python, car un call graph fiable demanderait AST inter-fichiers + résolution dynamique.
- Les tables lues/écrites sont plus fiables, car extraites des SQL statiques.

Exemples à inspecter :

```txt
module: services/live-pc/live_pipeline.py
  main_symbols:
    - LivePipeline
    - LivePipeline.run_video
    - LivePipeline.on_audio_chunk
    - LivePipeline.end_session
  tables:
    reads/writes:
      - voir repo_graph_v4.json.modules[...].tables
  invariants:
    - drain/flush before CloseDay
    - latest-frame queue must not grow
    - live_session_id durability through ConversationBridge
```

```txt
module: services/live-pc/sessionhub_http.py
  routes:
    - /live
    - /health
    - /metrics
    - /models/device/manifest
    - /models/device/{name}
    - /session/create
    - /session/renew
    - /session/clock-sync
    - /webrtc/offer
    - /session/end
    - /session/close-day
    - /session/status
  invariants:
    - auth token on business routes
    - /health readiness, not fake OK
    - no silent runtime overwrite
```

### 19.5 Comment utiliser la V4 pour trouver les erreurs

Procédure :

1. Choisir le flow touché.
2. Ouvrir `repo_graph_v4.json.flows[id]`.
3. Lister `tables_written` et `tables_read`.
4. Pour chaque table, ouvrir `repo_graph_v4.json.tables[name]`.
5. Vérifier `writers/readers/tests`.
6. Si un writer attendu est absent ou `unknown`, remonter au code avec `rg`.
7. Si le test prouve seulement fake/sim/JVM, marquer matériel `to_verify`.
8. Si `called_by` est `unknown`, ne pas conclure que le module est appelé.

Exemples de vrais signaux d’alerte :

- Table écrite par aucun writer statique alors qu’un flow la promet.
- Route HTTP présente mais aucun flow ne la consomme.
- Module Unity présent mais absent du `PhoneOnlySceneBuilder`.
- Modèle dans manifest mais aucun provisioning/StreamingAssets ne l’amène sur device.
- Test qui mentionne la table mais ne traverse pas le flow réel.
- Table avec `live_session_id` alimentée par un transport `session_id`.
- Evidence media référencé sans chemin stable.

## 20. V4 — 24 chemins critiques à vérifier

Cette section ne remplace pas `repo_graph_v4.json`. Elle donne les 24 chemins à relire avant modification. Statuts :

- `proven` : prouvé par tests unitaires/intégration du checkout.
- `partially_proven` : prouvé côté PC/JVM/EditMode ou par statique, mais pas sur tout le chemin matériel.
- `to_verify` : lien non prouvé par test ou frontière réelle encore non validée.

### 1. PhoneOnly pairing

```txt
objectif:
  - Android choisit le bon PC LAN/Tailscale, crée/renouvelle session, obtient token et clock sync.
entrée réelle:
  - Unity SessionPairing.OnEnable()
  - SessionPairing.ResolveActiveEndpoint()
path:
  1. apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:OnEnable/ResolveActiveEndpoint/RenewOnce
  2. apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:CreateSession/RenewToken/ClockSync
  3. services/live-pc/sessionhub_http.py:/health,/session/create,/session/renew,/session/clock-sync
  4. services/live-pc/sessionhub.py
tables:
  reads: []
  writes: []
tests existants:
  - tests/v19/test_sessionhub.py
  - tests/v19/test_sessionhub_http.py
  - tests/v19/test_phoneonly_android_wiring.py
tests manquants:
  - test device LAN→Tailscale réel avec changement réseau.
  - test Android persistance token après redémarrage app.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_sessionhub.py tests\v19\test_sessionhub_http.py tests\v19\test_phoneonly_android_wiring.py
risques si modifié:
  - WebRTC peut partir vers une URL statique au lieu de l’endpoint actif.
  - token expiré accepté hors renew.
  - pairing OK en HTTP mais transport impossible.
```

### 2. WebRTC setup

```txt
objectif:
  - Créer PeerConnection audio+vidéo+DataChannel entre Android et PC.
entrée réelle:
  - LiveTransportBridge.StartTransport()
  - Kotlin LiveTransportPlugin.start()
  - POST /webrtc/offer
path:
  1. LiveTransportBridge.cs:StartAndroid/BuildConfig/RefreshCredentials
  2. LiveTransportPlugin.kt:start/connectLoop/establish/addAudioTrack/addVideoTrack
  3. SignalingClient.kt:exchangeOffer
  4. sessionhub_http.py:/webrtc/offer
  5. gateway.py:AiortcIngress.handle_offer_sdp
  6. phoneonly_runtime.py:SinglePhoneRuntimeManager.get_or_create
tables:
  reads: []
  writes: []
tests existants:
  - tests/v19/test_transport_webrtc.py
  - tests/v19/test_phoneonly_runtime.py
  - livetransport JVM tests
tests manquants:
  - test Android réel SDP/ICE/DataChannel sur Wi-Fi.
  - test reconnection Android après perte réseau réelle.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_transport_webrtc.py tests\v19\test_phoneonly_runtime.py
risques si modifié:
  - audio/video track présente en code mais pas négociée.
  - ICE non-trickle cassé.
  - second runtime écrase le premier.
```

### 3. live audio

```txt
objectif:
  - Micro Android → WebRTC Opus → aiortc AudioFrame → PCM mono → AudioRT → transcript final → BrainLive/archive.
entrée réelle:
  - Android JavaAudioDeviceModule samples.
  - aiortc audio track recv.
path:
  1. LiveTransportPlugin.kt:addAudioTrack
  2. MicAudioFanout.kt:dispatch
  3. gateway.py:AiortcIngress._consume_audio_track/_audio_frame_to_mono
  4. live_pipeline.py:LivePipeline.on_audio_chunk
  5. audiort.py:AudioRT.push_audio/flush
  6. conversation_bridge.py:ConversationBridge.ingest_segment
  7. audio_archive.py:AudioArchive.archive_segment
tables:
  reads:
    - brainlive_sessions
  writes:
    - brainlive_turn_buffer
    - brainlive_audio_chunks
    - turns
    - brainlive_signal_events
tests existants:
  - tests/v19/test_audiort.py
  - tests/v19/test_transport_webrtc.py
  - tests/v19/test_e31_conversation.py
  - tests/v19/test_phoneonly_runtime.py
tests manquants:
  - preuve matérielle Android mic → aiortc audio track → PCM.
  - test long 10 min WebRTC+sherpa sans double micro.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_audiort.py tests\v19\test_transport_webrtc.py tests\v19\test_e31_conversation.py tests\v19\test_phoneonly_runtime.py
risques si modifié:
  - confusion packed/planar PyAV.
  - archive audio dépendante du succès ASR.
  - flush final perdu.
  - double accès micro Android.
```

### 4. live video

```txt
objectif:
  - Caméra Android → WebRTC video → VisionRT/WorldBrain → keyframes/SceneDelta/UI.
entrée réelle:
  - EyeCaptureSource.OnFrame
  - aiortc video track recv
path:
  1. PhoneOnlyAdapter.cs:TryGetLatestFrame
  2. EyeCaptureSource.cs:Update/OnFrame
  3. LiveTransportBridge.cs:HandleFrame
  4. UnityPushVideoFeeder.kt:pushTextureFrame/pushI420Frame
  5. gateway.py:AiortcIngress._consume_track
  6. live_pipeline.py:LivePipeline.run_video
  7. visionrt.py:VisionRT.process_frame
  8. worldbrain.py:WorldBrain.ingest_scene_delta
tables:
  reads:
    - brain2_spatial_routine_models
    - scene_session_summaries_v19
  writes:
    - vision_frames
    - visual_events_v19
    - visual_evidence_assets_v19
    - scene_session_summaries_v19
    - worldbrain_session_entities
    - worldbrain_session_changes
tests existants:
  - tests/v19/test_visionrt.py
  - tests/v19/test_e27_pipeline.py
  - tests/v19/test_e28_worldbrain.py
  - tests/v19/test_phoneonly_runtime.py
tests manquants:
  - test Android réel caméra arrière → PC.
  - test UI téléphone montrant le SceneDelta reçu.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_visionrt.py tests\v19\test_e27_pipeline.py tests\v19\test_e28_worldbrain.py tests\v19\test_phoneonly_runtime.py
risques si modifié:
  - queue vidéo non bornée.
  - keyframes écrites dans un chemin non persistant.
  - scène Unity générée sans handler SceneDelta.
```

### 5. wake word / command routing

```txt
objectif:
  - Wake word ouvre une fenêtre commande ; tout final reste en mémoire ; la configuration runtime est acquittée.
entrée réelle:
  - AsrKwsService.decodeSegment final FR / KWS
  - LivePipeline.push_wake_word
path:
  1. WakeWordMatcher.matches → openCommandWindow/onWakeWord
  2. AsrBridge.OnNativeTranscript → device_transcript is_command
  3. LivePipeline.arm_command_window/_should_route_intent
  4. user_profile wake_word → device_command set_wake_word
  5. DeviceCommandHandler → AsrBridge.SetWakeWord → JNI
  6. device_command_result → ack/retry PC
tables:
  writes: [brainlive_turn_buffer]
tests existants:
  - tests/v19/test_wake_word_gating.py
  - CommandWindowTest.kt
  - WakeWordMatcherTest.kt
tests manquants:
  - device réel wake word + changement runtime acquitté.
statut:
  - partially_proven
risques si modifié:
  - couper la mémoire continue.
  - confondre type DataChannel et UIIntent.
  - retry non idempotent.
```

### 6. UIIntent delivery

```txt
objectif:
  - Intervention classique ou aide devient une UIIntent rendue sur téléphone.
entrée réelle:
  - v18_delivery.enqueue_delivery()
  - HelpTaskEngine task_panel/task_anchor
path:
  1. delivery queue / hot path
  2. DeliveryAdapter / DataChannelRenderer
  3. LiveTransportBridge.OnNativeMessage
  4. TransportIntentSource → UIIntentBroker
  5. UIComponentRegistry
  6. TaskPanelComponent/TaskAnchorComponent + TaskAtoms si mode aide
tables:
  reads/writes:
    - brainlive_intervention_delivery_queue
    - help_mode_tasks
tests existants:
  - tests/v19/test_delivery_adapter.py
  - tests/v19/test_phoneonly_runtime.py
  - E53 PC + EditMode suites rapportées
tests manquants:
  - rendu device réel, grounding anchor et reprise.
statut:
  - partially_proven
risques si modifié:
  - delivery marquée envoyée DataChannel fermé.
  - nom composant divergent du registry.
  - ancre non groundée spatialisée artificiellement.
```

### 7. UIReceipt feedback

```txt
objectif:
  - Le téléphone renvoie displayed/seen/acted/dismissed au PC, persisté dans la politique V18.8.
entrée réelle:
  - UIReceiptTransportSink.Send()
path:
  1. UIIntentBroker.cs / UI components
  2. UIReceiptTransportSink.cs:Send/TrySendOverBridge
  3. LiveTransportBridge.cs:SendContractMessage
  4. LiveTransportPlugin.kt:sendContractMessage
  5. phoneonly_runtime.py:_on_receipt
  6. v18_8_live_policy.py:record_delivery_feedback/materialize_intervention_outcome_observation
tables:
  reads:
    - brainlive_intervention_delivery_queue
  writes:
    - brainlive_intervention_feedback_events_v188
    - brainlive_intervention_outcomes_v188
tests existants:
  - tests/v19/test_delivery_adapter.py
  - tests/v19/test_phoneonly_runtime.py
tests manquants:
  - test Unity UI réel avec receipt visible puis DB vérifiée.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_delivery_adapter.py tests\v19\test_phoneonly_runtime.py
risques si modifié:
  - feedback perdu si transport down.
  - feedback incorrect sur mauvais delivery_id.
```

### 8. explicit end session

```txt
objectif:
  - L’action utilisateur explicite termine le live, drain/flush, puis démarre CloseDay async.
entrée réelle:
  - PhoneOnlySessionCoordinator.EndExplicitly()
  - POST /session/end
path:
  1. PhoneOnlySessionCoordinator.cs:EndExplicitly
  2. sessionhub_http.py:/session/end
  3. phoneonly_runtime.py:end_and_close_day/end_session_only
  4. gateway.py:stop_accepting_media/drain_audio
  5. live_pipeline.py:end_session
  6. audiort.py:flush
  7. conversation_bridge.py:end_session
tables:
  reads:
    - v18_close_day_runs
  writes:
    - brainlive_sessions
    - brainlive_turn_buffer
tests existants:
  - tests/v19/test_phoneonly_runtime.py
  - tests/v19/test_sessionhub_http.py
tests manquants:
  - test réel Android bouton Terminer → statut CloseDay.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_phoneonly_runtime.py tests\v19\test_sessionhub_http.py
risques si modifié:
  - déconnexion réseau assimilée à fin volontaire.
  - end_session appelé plusieurs fois.
  - CloseDay démarre avant drain.
```

### 9. CloseDay

```txt
objectif:
  - CloseDay après fin explicite, multi-session/jour et recovery corrects.
entrée réelle:
  - /session/end
  - /session/close-day
  - watchdog après end explicite
path:
  1. end_session_only capture live_session_id BrainLive
  2. _completed_close_day_exists lit v18_close_day_runs
  3. manager.start_close_day / watchdog
  4. run_phoneonly_close_day.py dans .venv
  5. v18_close_day stages
  6. visual consolidation Europe/Paris
  7. manifest relit tables finales
tables:
  reads/writes:
    - v18_close_day_runs
    - v18_pipeline_stages
    - tables BrainLive/vision/life model
statut:
  - partially_proven
risques si modifié:
  - session_id transport utilisé.
  - disconnect traité comme end.
  - compteur mémoire remplace la DB.
  - frontière de jour implicite/UTC.
```

### 10. visual evidence / clips

```txt
objectif:
  - Conserver keyframes/clips utiles et prouver le wiring runtime.
entrée réelle:
  - phoneonly_runtime construit ClipRecorder + GpuArbiter
  - gateway._consume_track
path:
  1. runtime → ingress_kwargs[clip_recorder]
  2. gateway._consume_track → recorder.offer
  3. VisionRT keyframe sink
  4. index assets/events
  5. media_retention / tiering
tables:
  reads/writes:
    - vision_frames
    - raw_assets
    - visual_evidence_assets_v19
    - visual_events_v19
tests existants:
  - tests/v19/test_clip_recorder.py
  - tests/v19/test_media_retention.py
  - tests/v19/test_visionrt.py
tests manquants:
  - clip Android réel rejouable ; pression GPU/device.
statut:
  - partially_proven
risques si modifié:
  - recorder débranché à nouveau.
  - live bloqué.
  - preuve référencée purgée.
```

### 11. model provisioning

```txt
objectif:
  - Téléphone obtient modèles device depuis PC, vérifie SHA, installe atomiquement.
entrée réelle:
  - ModelProvisioningBridge après PairingState.Paired
  - GET /models/device/manifest
path:
  1. StreamingAssetsModelInstaller.cs:Install
  2. ModelProvisioningBridge.cs:TryStart/StartAndroid
  3. ModelProvisioner.kt:start/provision/downloadOne/installVerified
  4. sessionhub_http.py:/models/device/manifest,/models/device/{name}
  5. configs/MODEL_MANIFEST.yaml:device
tables:
  reads: []
  writes: []
tests existants:
  - tests/v19/test_device_provisioning.py
  - ModelProvisionerCoreTest.kt
  - DeviceModelManifestTest.kt
tests manquants:
  - test device vierge → téléchargement complet → ASR/gestes/traduction actifs.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_device_provisioning.py
risques si modifié:
  - hash mismatch ignoré.
  - extraction zip-slip.
  - modèle absent mais UI prétend fonctionnelle.
```

### 12. memory query

```txt
objectif:
  - Répondre à une question mémoire depuis live/dashboard/API avec sources.
entrée réelle:
  - IntentRouter._do_ask_memory
  - dashboard chat
  - core API /query
path:
  1. services/live-pc/intent_router.py:_do_ask_memory
  2. src/mlomega_audio_elite/api.py:/query
  3. src/mlomega_audio_elite/brain2_router_v14_2.py:ask_brain2 (to_verify caller exact)
  4. apps/memory-dashboard/app.py (to_verify)
tables:
  reads:
    - atomic_memories
    - conversations
    - turns
    - conversation_discourse_maps
    - vector_sync_manifest
  writes:
    - v14_1_answer_packets
    - v14_2_answer_packets
tests existants:
  - tests/v19/test_e33_intents.py
  - tests/v19/test_memory_v19.py
tests manquants:
  - test live voix “interroge ma mémoire” → réponse UI sourcée.
  - test dashboard chat sur base réelle en lecture seule.
statut:
  - to_verify
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_e33_intents.py tests\v19\test_memory_v19.py
risques si modifié:
  - utiliser `/query` simple au lieu du routeur Brain2 riche.
  - écrire depuis dashboard supposé read-only.
```

### 13. contracts Python ↔ C# ↔ Kotlin

```txt
objectif:
  - Garder les payloads UIIntent/UIReceipt/SceneDelta/FrameEnvelope compatibles entre PC, Unity et Kotlin.
entrée réelle:
  - packages/contracts/schemas/*.schema.json
  - DataChannel JSON
path:
  1. packages/contracts/schemas/*.schema.json
  2. packages/contracts/python/models.py
  3. packages/contracts/csharp/*.cs
  4. packages/contracts/generate_csharp.py
  5. apps/xr-mobile/Assets/Scripts/Contracts/ContractJson.cs
  6. services/live-pc producers
  7. Unity consumers
tables:
  reads: []
  writes:
    - ui_interaction_outcomes_v19
    - visual_events_v19
tests existants:
  - tests/v19/test_contracts.py
  - tests/v19/test_csharp_generator.py
  - scripts/validate_contracts_v19.py
tests manquants:
  - test Kotlin DataChannel schema strict si Kotlin reste raw JSON.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_contracts.py tests\v19\test_csharp_generator.py
risques si modifié:
  - DateParseHandling/ISO timestamps cassés côté Unity.
  - champ ajouté Python non lu C#.
  - Kotlin raw JSON divergent.
```

### 14. SessionHub auth/token renew

```txt
objectif:
  - Authentifier routes métier, expirer tokens, renouveler uniquement via la route prévue.
entrée réelle:
  - /session/create
  - /session/renew
  - token sur /webrtc/offer,/session/end,/status,/models
path:
  1. sessionhub_http.py:create_app routes
  2. sessionhub.py session/token store
  3. SessionPairing.cs renew/create
  4. SessionCredentialStore.kt save/load/clear
tables:
  reads: []
  writes: []
tests existants:
  - tests/v19/test_sessionhub.py
  - tests/v19/test_sessionhub_http.py
tests manquants:
  - test Android token expiré puis renew après app sleep.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_sessionhub.py tests\v19\test_sessionhub_http.py
risques si modifié:
  - mauvais token accepté.
  - grace renew utilisable sur route métier.
  - token persistant jamais purgé.
```

### 15. DataChannel delivery

```txt
objectif:
  - Transporter UIIntent, UIReceipt, scene_delta, device_transcript, device_command sans faux succès.
entrée réelle:
  - WebRTC DataChannel open
  - DataChannelRenderer.push
  - LiveTransportBridge.OnNativeMessage
path:
  1. LiveTransportPlugin.kt:bindDataChannel/onMessage/sendContractMessage
  2. gateway.py:AiortcIngress.send_ui_intent
  3. phoneonly_runtime.py:DataChannelRenderer.push
  4. LiveTransportBridge.cs:OnNativeMessage
  5. TransportIntentSource.cs / SceneDeltaTransportHandler.cs / DeviceCommandHandler.cs
tables:
  reads:
    - brainlive_intervention_delivery_queue
  writes:
    - brainlive_intervention_feedback_events_v188
tests existants:
  - tests/v19/test_phoneonly_runtime.py
  - tests/v19/test_transport_webrtc.py
tests manquants:
  - test vrai DataChannel Android ↔ PC avec plusieurs types de messages.
statut:
  - partially_proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_phoneonly_runtime.py tests\v19\test_transport_webrtc.py
risques si modifié:
  - scene_delta parsé comme UIIntent.
  - envoi depuis mauvais thread/event loop.
  - delivery perdue au premier open tardif.
```

### 16. media retention / no purge of referenced proof

```txt
objectif:
  - Respecter budget disque sans supprimer de preuve référencée.
entrée réelle:
  - CloseDay cleanup eligible
  - media_retention run
path:
  1. scripts/run_phoneonly_close_day.py
  2. services/live-pc/media_retention.py:transcode_audio_chunks/purge_unreferenced/enforce_budget
  3. services/live-pc/clip_recorder.py:tier_clips_close_day
tables:
  reads:
    - visual_events_v19
    - visual_evidence_assets_v19
    - vision_frames
  writes:
    - media paths / metadata updates (voir repo_graph_v4.json)
tests existants:
  - tests/v19/test_media_retention.py
  - tests/v19/test_clip_recorder.py
tests manquants:
  - test sur vraie base longue avec clips/audio réels.
statut:
  - proven
commande:
  - .venv-live\Scripts\python.exe -m pytest tests\v19\test_media_retention.py tests\v19\test_clip_recorder.py
risques si modifié:
  - suppression de preuve référencée.
  - transcode casse chemin DB.
  - ffmpeg failure rend CloseDay failed au lieu de best-effort.
```

### 17. Qdrant/vector sync

```txt
objectif:
  - Synchroniser mémoire textuelle/cases vers Qdrant et interroger sans casser la mémoire durable.
entrée réelle:
  - scripts/START_QDRANT.ps1
  - vector_sync.sync_vectors
  - v18_predictive_retrieval backend
path:
  1. scripts/START_QDRANT.ps1
  2. src/mlomega_audio_elite/vector_sync.py:sync_vectors
  3. src/mlomega_audio_elite/v18_sync.py
  4. src/mlomega_audio_elite/v18_predictive_retrieval.py:get_predictive_backend
tables:
  reads:
    - atomic_memories
    - conversations
    - turns
    - vector_sync_manifest
    - v18_predictive_case_vector_manifest
  writes:
    - vector_sync_manifest
    - vector_sync_manifest_v18
    - v18_predictive_case_vector_manifest
tests existants:
  - tests/v19/test_memory_v19.py
  - tests/v19/test_e36_ops.py
tests manquants:
  - test Qdrant réel démarré + sync complet + requête.
statut:
  - to_verify
commande:
  - .venv\Scripts\python.exe -m pytest tests\v19\test_memory_v19.py tests\v19\test_e36_ops.py
risques si modifié:
  - tests passent avec backend mock/local mais Qdrant réel cassé.
  - points vectoriels désynchronisés de SQLite.
```

### 18. Life Model update

```txt
objectif:
  - Transformer preuves/bundles/outcomes en Life Model durable sans inventer.
entrée réelle:
  - CloseDay life_model stage
  - v19_life_model_store.run_life_model_v19_stage
path:
  1. v18_close_day.py:close_brainlive_day
  2. brain2_life_model_updater_v15_13.py:run_brain2_life_model_update
  3. v19_life_model_store.py:run_life_model_v19_stage/apply_life_model_delta
  4. v19_prediction_loop.py:emit_daily_predictions
  5. v19_self_schema.py:rebuild_self_schema
tables:
  reads:
    - brainlive_event_bundles_v1514
    - visual_events_v19
    - prediction_outcomes_v19
  writes:
    - life_model_entries_v19
    - brain2_life_model_patch_runs
    - brain2_life_model_patch_operations
    - predictions_v19
    - self_schema_v19
tests existants:
  - tests/v19/test_life_model_v19.py
  - tests/v19/test_life_model_empty_day.py
  - tests/v19/test_personal_model_schema_bootstrap.py
tests manquants:
  - test sur CloseDay réel Android avec preuves audio+vision.
statut:
  - partially_proven
commande:
  - .venv\Scripts\python.exe -m pytest tests\v19\test_life_model_v19.py tests\v19\test_life_model_empty_day.py tests\v19\test_personal_model_schema_bootstrap.py
risques si modifié:
  - preuve non approuvée acceptée.
  - LLM invente sans evidence refs.
  - empty day mal traité.
```

### 19. dashboard read-only

```txt
objectif:
  - Lire la mémoire sans écrire, afficher V19/BrainLive/CloseDay et chat mémoire.
entrée réelle:
  - scripts/RUN_DASHBOARD.ps1
  - apps/memory-dashboard/app.py
path:
  1. RUN_DASHBOARD.ps1
  2. apps/memory-dashboard/app.py
  3. SQLite URI mode=ro
  4. optional CLI core ask_brain2 to_verify
tables:
  reads:
    - brainlive_sessions
    - v18_close_day_runs
    - life_model_entries_v19
    - self_schema_v19
    - predictions_v19
    - visual_events_v19
    - visual_evidence_assets_v19
  writes:
    - should_be_none
tests existants:
  - aucun test pytest dédié identifié dans la map
tests manquants:
  - test automatisé mode=ro + interdiction écriture.
  - test chat routeur Brain2 signature actuelle.
statut:
  - to_verify
commande:
  - powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
risques si modifié:
  - écriture accidentelle dans dashboard.
  - requête SQL casse si table absente.
  - chat appelle mauvais CLI/routeur.
```

### 20. installer/onboarding

```txt
objectif:
  - Installer/guider et construire toujours la scène PhoneOnly V4 réelle.
entrée réelle:
  - scripts/WELCOME_MLOMEGA.ps1
  - AndroidBuild.cs
path:
  1. onboarding/install/doctor/run
  2. AndroidBuild force com.mlomega.xr.phoneonly
  3. régénère PhoneOnly scene à chaque build
  4. scène contient ReflexSignalSource/MenuPanel/OrientationGuard/TtsAudioPlayer/PanelManipulator
statut:
  - partially_proven
tests manquants:
  - install machine propre.
  - APK build/install S25 réel.
risques si modifié:
  - stale scene.
  - mauvais applicationId.
  - SimOnly confondu avec hardware.
```

### 21. help mode

```txt
objectif: plan micro-actions persistant + panel + ancre.
path:
  IntentRouter._do_help_start
  → HelpTaskEngine.start_from_description
  → one-shot VLM
  → LLM JSON
  → help_mode_tasks
  → task_panel/task_anchor
statut: partially_proven (device to_verify)
risques: VLM répété, contrôle actif mal routé, ancre inventée.
```

### 22. reflex activation production

```txt
objectif: le scheduler réflexe a un appelant prod.
path:
  PhoneOnlyReflexSignalSource
  → ReflexScheduler.RaiseSignal
  → ASR/gestes/traduction/skills
statut: partially_proven (device to_verify)
risques: retour au flow mort, double micro, signaux non idempotents.
```

### 23. TTS DataChannel

```txt
objectif: tts_audio possède un consommateur Unity.
path:
  LivePipeline(enable_tts=True)
  → tts_audio
  → LiveTransportBridge
  → TtsAudioPlayer
statut: partially_proven (playback device to_verify)
risques: type confondu avec UIIntent, blocage main thread.
```

### 24. panel manipulation

```txt
objectif: pinch manipule le panel ciblé sans casser le zoom fallback.
path:
  GestureBridge pinch(x,y)
  → PanelManipulator claim/hit-test
  → IManipulablePanel
  → sinon LensWindowSkill
statut: partially_proven (EditMode proven, device to_verify)
risques: mauvais espace coordonnées, double handling du pinch.
```
