# DECISIONS

## 2026-07-09 — E51 : installateur / guide de bienvenue (ADR)

`scripts/WELCOME_MLOMEGA.ps1` ORCHESTRE les scripts existants (INSTALL/setup_profile/fetch_models/START_QDRANT/RUN/DOCTOR) — il ne réimplémente aucune install ; params vérifiés dans le code réel avant appel. 3 modes : interactif, `-Defaults`, `-DryRun` (aucun processus lourd). Idempotent, tolérant (Test-Path + WARN + consigne de reprise, jamais de stacktrace brute) ; clés (HF/OpenAI/Gemini) écrites dans `.env`, jamais loguées.

**Encodage (piège PS 5.1).** Le fichier DOIT être UTF-8 **avec BOM** : sans BOM, PowerShell 5.1 lit un `.ps1` en ANSI/Windows-1252, mange les `—`/accents et un octet mal lu produit un guillemet parasite → erreur de parsing. Règle générale pour tout `.ps1` du projet contenant du non-ASCII. Validé par `Parser::ParseFile` (0 erreur) + dry-run exit 0.

**Mot d'éveil — question RETIRÉE (décision utilisateur).** Le mot est cuit dans l'APK (`_wakeWord`, « omega ») et non modifiable sans rebuild. On n'ajoute pas de fausse question à l'install ; le mini-tuto mentionne « omega » (gated). La question reviendra avec le chantier **« wake word runtime »** (backlog E51 : mot choisi à l'install → poussé par le PC au pairing → `KeywordEncoder` runtime).

**XREAL avant E49.** L'installateur pose la question lunettes et gère la branche XREAL en placeholder honnête (« dépose ton SDK puis rebuild ; PhoneOnly en attendant ») — l'install PC est identique, donc E49 ne remplira qu'une branche plus tard. Aucun fichier existant n'a été modifié (seuls `WELCOME_MLOMEGA.ps1` + `WELCOME.md` créés), donc zéro risque de régression sur le code livré.

## 2026-07-08 — E55 : enregistrement clips vidéo + tiering (ADR)

**Constat & décision.** Le replay ne servait qu'un diaporama de keyframes. Décision utilisateur : rejouer la scène en VRAIE vidéo, encode CPU (GPU 100 % vision/LLM), **mais jamais au détriment du live**. Le passthrough H.264 est impossible (aiortc livre des frames déjà décodées par PyAV dans `gateway._consume_track`), donc on ré-encode les frames déjà décodées pour la vision — seul l'encode s'ajoute, pas de décodage en plus. Coût CPU vérifié par bench (540p/12fps veryfast ≈ 1,8 % d'un cœur, ressource disjointe du GPU live) → GO.

**Garantie « ne ralentit jamais le live » par construction.** (1) File bornée `queue.Queue(queue_max_frames)` DROP-on-full : `ClipRecorder.offer()` fait `put_nowait`, file pleine → jette la frame + compteur, retourne immédiatement ; jamais de back-pressure. Décimation fps par `capture_ns` avant la copie. (2) Encodeur ffmpeg en PROCESS séparé (libx264 veryfast, stdin rawvideo bgr24) possédé par un thread daemon dédié, priorité basse au spawn (Windows `BELOW_NORMAL_PRIORITY_CLASS` ; POSIX `nice(15)`) confirmée via `psutil`. Zéro GPU (pas de NVENC/AV1). (3) Auto-pause sur drops persistants (fenêtre glissante > `drop_pause_threshold`) → suspend, logge, le live continue, reprise après accalmie. (4) Best-effort total : ffmpeg absent/crash/pipe/DB captés, comptés, jamais propagés ; l'`offer` côté gateway est sous try/except → recorder None/désactivé = no-op.

**Stockage & indexation.** Clips sous `<media_root>/clips/AAAA-MM-JJ/<session>_<t>.mp4` (réutilise `visionrt.media_root`, env `MLOMEGA_MEDIA` sinon `storage/media/`), segmentés (`segment_seconds`, défaut 120 s). À la clôture de chaque segment, indexation dans `visual_evidence_assets_v19` (`asset_kind='clip'`, `uri`, `sha256`, `captured_at`, `clip_id`, fenêtre en `metadata_json`) via les writers cœur existants (`ensure_v19_visual_schema` + `upsert`) — aucune modif du cœur. Les colonnes matchent la requête de `replay_service.assemble_bundle` → le replay les retrouve SANS changement. E54 (`media_retention.py`) reste seul responsable du budget/éviction.

**Tiering close-day.** `tier_clips_close_day` réutilise `MediaRetention.inventory()` (notion « référencé » E54, non réinventée) : clip GARDÉ s'il est référencé OU si un événement `visual_events_v19` tombe dans sa fenêtre ; clip jeune (`<= keep_boring_days`), ennuyeux, non-référencé → DROP (fichier + ligne). Les vieux clips ennuyeux sont laissés au budget E54. Câblé dans `scripts/run_phoneonly_close_day.py` au gate `cleanup.eligible`, avant la rétention E54, best-effort strict.

**Tests.** `tests/v19/test_clip_recorder.py` (6, dont ffmpeg RÉEL : MP4 encodé + retrouvé par la requête replay) + `test_media_retention.py` = 13 passed. **Réserve** : le chemin producteur `offer` depuis `_consume_track` et le coût CPU sous charge live continue ne sont validables qu'en vraie session WebRTC device (bench isolé fait).

## 2026-07-06 - E39 : `turns` sans colonne temporelle fictive

Decision : aucun code ne doit dependre de `turns.created_at` ou `turns.absolute_start`, colonnes absentes du schema. Une preuve directement issue d'un tour peut porter `start_s`, offset relatif a sa conversation ; l'instant absolu doit etre resolu par la conversation ou rester inconnu. Le diff preexistant de `v18_close_day.py` est conserve hors du perimetre E39.

## 2026-07-06 - E40 : identites transport et BrainLive non interchangeables

Decision : `session_id` identifie le transport WebRTC ; `live_session_id` identifie la session semantique durable. Tous les writers durables d'un runtime utilisent un unique `live_session_id`, cree ou lie par ConversationBridge avant leur construction. Aucun fallback writer vers l'identifiant transport n'est autorise quand un bridge conversationnel est actif.

## 2026-07-06 - E41 : barriere live vers post-stop

Decision : l'ordre obligatoire est `freeze producers -> drain queue et callback en vol -> flush VAD -> close transport -> end WorldBrain/ConversationBridge strict -> release live resources -> CloseDay`. Une queue vide seule n'est jamais une preuve de drain. L'archive du signal VAD est independante de la disponibilite ou du succes ASR.

## 2026-07-06 - E42 : audio packed et ownership asyncio

Decision : la forme ndarray seule ne determine pas les canaux PyAV ; le gateway utilise `format.is_planar` et `layout.channels`. Le dtype entier et son echelle sont conserves jusqu'a `AudioRT.to_mono_16k`. Toute operation aiortc/DataChannel appartient a l'event loop qui a negocie le peer ; un worker ASR ne peut que programmer l'envoi avec `call_soon_threadsafe`.

## 2026-07-06 - E43 : CloseDay hors requete et hors environnement live

Decision : `session/end` et CloseDay sont deux etats idempotents distincts. La route de fin repond apres le flush live puis lance le CloseDay en arriere-plan ; Android suit `session/status` et peut demander un retry explicite. Le calcul lourd s'execute dans `.venv`, jamais dans `.venv-live`. La durabilite et la reprise sont deleguees aux stages/leases du coeur existant, pas a une seconde orchestration. Pour eviter l'idempotence journaliere ambigue, le serveur mono-appareil ne remplace jamais sa session active sans redemarrage explicite.

## 2026-07-06 - E44 : fallback I420 avant zero-copy

Decision : un GLuint Unity n'est pas utilisable dans un EGL libwebrtc independant sans partage de contexte prouve. PhoneOnly utilise donc I420 CPU comme chemin initial verifiable ; zero-copy reste optionnel jusqu'au test EGL materiel. Le signaling est non-trickle et attend la collecte ICE. Les credentials Kotlin sont renouvelables en place. Les modules Gradle exportent AAR et dependances transitives vers Unity ; XREAL reste une dependance optionnelle du gate separe.

## 2026-07-06 - E45 : ne pas detourner le gate G1

Decision : G1 reste exclusivement le gate XREAL documente. PhoneOnly dispose de sa propre scene, de son propre asset de configuration et de son propre menu builder. Les deux scenes partagent les composants Core/Transport mais aucune ne force l'adaptateur de l'autre.

## 2026-07-06 - E46 : gate factuelle, aucun succes par documentation

Decision initiale conservee comme historique : les validations PC vertes ne valent pas compilation Android et un CloseDay `blocked` interdit le cleanup.

Mise a jour E46-A : CUDA/ASR ne repose plus sur le fallback CPU normal ; les wheels NVIDIA CUDA 12/cuBLAS/cuDNN sont une dependance de `.venv-live` et AudioRT les expose a CTranslate2 sous Windows. Le fallback CPU reste une securite, pas le chemin valide. L'ASR PC sert les transcripts finals BrainLive/archive ; le reflexe subtitle appartient a sherpa Android. La traduction Android n'est pas encore implementee ; Argos PC devient optionnel et hors chemin PhoneOnly par defaut.

Decision LLM : conserver Ollama, qui utilise deja un backend llama.cpp, tant qu'un benchmark identique ne prouve pas un gain d'un serveur direct. `qwen3.5:4b` est resident pendant le live ; `qwen3.5:9b` est resident pendant tous les stages LLM deep puis libere une seule fois a la fin du CloseDay. `think:false` est obligatoire pour les contrats JSON. Les champs non critiques peuvent etre omis puis normalises ; evidence, decision et scores restent valides semantiquement. Une sortie `finish_reason=length` est rejetee integralement, jamais appliquee partiellement.

Decision CloseDay : un jour sans preuve proprietaire produit une abstention vide et ne doit jamais appeler le LLM pour fabriquer une identite. Les builders V18 wrappers doivent appeler leur propre `ensure_*_schema` avant ecriture. Le meme run E46 est maintenant `completed`, cleanup eligible ; aucune purge ni nouveau jour artificiel.

Mise a jour E46-B : `/live` signifie seulement processus vivant ; `/health` signifie PhoneOnly pret et doit repondre 503 sans aiortc/signaling/runtime. Le choix LAN/Tailscale de `SessionPairing.ActiveBaseUrl` est l'unique source de l'URL offer et credentials Kotlin. Un token expire n'authentifie plus aucune route metier. Une grace bornee est admise uniquement sur `/session/renew` pour reprendre le meme `session_id` apres une coupure longue ; elle ne permet ni offer, ni status, ni end. Apres la grace la session est purgee.

- 2026-07-03: Lot 1 implements the V19 transport seam with a simulator-first `VideoIngress`. Real XREAL/S25 hardware gates remain blocked in this container and must be validated on device before marking Lot 3 hardware steps complete.
- 2026-07-03: E10 is not marked complete in this Linux container because the exact PowerShell command `scripts/RUN_MLOMEGA_V19.ps1 -SimOnly` cannot be executed (`pwsh`/`powershell` is absent). The underlying SimOnly path it wraps was validated with `python scripts/simonly_demo_v19.py`: fake device → BrainLive UIIntent → companion-web simulator receipt → `brainlive_intervention_feedback_events_v188`. V19 contracts/transport tests, the V18 baseline tests actually present under `MLOmega_V18_8_1_Evidence_Connected/tests`, and the simulator ingress bench were also validated. No hardware benchmark is claimed.
- 2026-07-03: The V18 deep-audio baseline now has a narrow WAV-only stitching fallback when `ffmpeg` is absent. It is limited to already-normalized WAV captures used by the baseline tests; production/non-WAV/trim/normalization paths still require `ffmpeg`.

## 2026-07-03 — Exécution E11→E30 : arrêt au checkpoint séquentiel

- Blocage réel restant : les critères de sortie E12→E30 ne peuvent pas être marqués terminés dans cette passe, car le guide interdit de sauter les checkpoints de lots et E12+ dépendent d'une validation progressive après E11.
- Fallback appliqué : ne marquer que l'étape réellement implémentée et testée (E11), laisser E12→E30 non cochées, et conserver les endpoints V19 additifs comme amorce non déclarée complète tant qu'ils ne disposent pas de leurs tests de sortie complets.
- Tâches indépendantes réalisées sans violer l'ordre : ajout additif des routes API V19 s'appuyant sur le store E11, sans marquer E12 comme terminée.


## 2026-07-03 — Après E12 : blocage séquentiel E13→E30

- Blocage réel restant : E13→E30 restent non cochées parce que le checkpoint E21 exige toute la chaîne mémoire (MemoryBridge/EvidenceStore, keyframes nocturnes, close-day, outcome watcher, prediction loop, self schema, vie synthétique) et le checkpoint final E30 exige ensuite des gates matériels G1→G8, benchs P50/P95, session 3h et doctor XR complet qui ne peuvent pas être validés dans ce conteneur sans S25/XREAL/Unity.
- Fallback appliqué : continuer uniquement les tâches indépendantes validables par simulateur/API, documenter ce blocage, et ne pas marquer E13+ comme terminées tant que leurs critères de sortie respectifs ne sont pas verts.
- État validé : E12 est terminé via endpoints FastAPI owner-scoped et test de persistance SQLite pour `/ingest/visual-event`, `/ingest/scene-summary`, `/memory/correction-visual`, `/xr/session-health` et `/evidence/request-clip`.


## 2026-07-03 — E21 non coché après E13→E20

- E13→E20 ont été implémentées et validées par simulateur/API dans ce conteneur : MemoryBridge/EvidenceStore, insertion keyframes `xr_keyframe`, phases close-day additives, outcome watcher, émission de prédictions vérifiables, self schema, contexte visuel hot capsule et vie synthétique 30 jours.
- Blocage réel restant pour E21 : le critère `close-day complet < 6h réelles sur RTX 3070 avec journal gpu_phase` ne peut pas être attesté dans ce conteneur sans RTX 3070 ni journée close-day réelle complète ; `scripts/DOCTOR_MLOMEGA_V19.ps1 -Memory` ne peut pas être exécuté tel quel car aucun runtime PowerShell (`pwsh`/`powershell`) n'est installé.
- Fallback appliqué : exécution des tests mémoire V19, de la suite V18 présente, et du simulateur de vie synthétique 30 jours ; E21 reste volontairement non coché, et E22 n'est pas démarrée.


## 2026-07-03 — Audit critique E13→E20 : cases retirées

- Correction appliquée : E13→E20 sont décochées parce que les critères d’acceptation exacts demandés (ring buffer/doctor quota, deep vision complet, close-day 9 stages repris, contexte récupéré via `v18_context`, 30 jours injectés via endpoints + close-day quotidien) ne sont pas démontrés par des tests d’intégration complets.
- Correction code : les prédictions et le self-schema V19 ne doivent plus inventer de phrases/confiances fixes ; l’émission lit désormais les entrées typées `life_model_entries_v19` avec `verification_spec`, l’outcome watcher gère `verified/refuted/expired/unverifiable` et appelle les ponts de vérification/calibration en best-effort sans fabriquer de labels.
- État : E21 reste non cochée ; E22 n’est pas démarrée.


## 2026-07-04 — Session de remédiation (audit + corrections post-Codex)

- **Dossier de référence restauré** : le commit « E10 checkpoint validation » avait modifié `MLOmega_V18_8_1_Evidence_Connected/` (fallback WAV dans `brainlive_offline_deep_audio_v18_5.py`) pour compenser l'absence de ffmpeg. Violation de la règle « référence intacte » : fichier restauré à l'état du premier commit, et **ffmpeg installé sur la machine** (winget Gyan.FFmpeg) — les 9 tests deep-audio passent contre le cœur pur.
- **Contrat UIIntent corrigé** : `priority` était typé `int` (modèle pydantic + schéma JSON + POCO C#) alors que le handoff le définit comme un float 0..1 (arbitrage de densité, ex. 0.92). Corrigé en `number` partout ; le hack `int(priority*100)` du delivery_adapter est remplacé par un clamp 0..1.
- **Outcome watcher — verrou SQLite** : `_try_register_calibration` ouvrait une seconde connexion pendant la transaction d'écriture (single-writer SQLite) → « database is locked » avalé en best-effort → aucun label `strict_verifier` enregistré. Les enregistrements de calibration sont différés après la fermeture de la transaction, puis l'`audit_json` de l'outcome est mis à jour.
- **GpuArbiter — sémantique des budgets** : le budget par classe s'applique uniquement aux charges à la demande (< priorité détecteur) ; tracker/détecteur sont le plancher résident (handoff §4.1) et ne sont jamais refusés pour cause de budget.
- **Générateur C#** : un scalaire non-required avec `default` déclaré n'est plus rendu nullable (ex. `FrameEnvelope.rotation` défaut 0 → `long`).
- **Correctif timezone G0 (prévu par le plan)** : `test_delivery_feedback_and_outcome_are_linked_into_brain2_raw_timeline` calculait `package_date` depuis l'horloge UTC alors que `_period_bounds` interprète un jour LOCAL → échec entre minuit et l'offset local. Le test dérive maintenant le jour local. Seule modification du dossier de référence, explicitement budgétée par le gate G0 (« correctif timezone test delivery »).
- **`run_life_model_v19_stage`** : appelle désormais `ensure_v19_visual_schema` (pattern lazy-ensure §2.8) avant d'interroger `visual_events_v19`.
- Validation finale : `tests/v19` 40/40 ; suite V18 108/108 (dont adaptive_live 6/6 après correctif timezone).


## 2026-07-04 — E22 G1 Unity (app XREAL minimale, gate G1)

Recherche ciblée effectuée sur la doc officielle XREAL (https://docs.xreal.com/) — 3 pages retenues :
« Getting Started with XREAL SDK », « Camera / Access RGB Camera », « Sample Code ». Ce qu'on
retient et qui guide l'implémentation `apps/xr-mobile/` :

- **Version Unity** : XREAL SDK 3.1.0 supporte Unity 2021.3 LTS, 2022.3 LTS et **6000.0.X LTS**
  (Unity 6 LTS). On cible Unity 6 LTS → `ProjectVersion.txt` = `6000.0.23f1`.
- **Import du SDK** : tarball UPM. `Window → Package Manager → Add package from tarball` →
  `com.xreal.xr.tar.gz`. Le SDK est **propriétaire** (téléchargé sur developer.xreal.com/download) :
  on ne le committe PAS. `Packages/manifest.json` le référence en `file:` vers
  `Packages/xreal-sdk/com.xreal.xr.tar.gz` (chemin ignoré par git, documenté dans le README).
- **XR Plug-in Management** : cocher le provider **« XREAL »** sous l'onglet Android
  (`Edit → Project Settings → XR Plug-in Management`). Reflété dans
  `ProjectSettings/XRPackageSettings.asset` et `Packages/manifest.json`
  (`com.unity.xr.management`).
- **Project Settings Android requis** (doc XREAL) :
  Default Orientation = **Landscape** (doc dit Portrait pour le sample générique, mais notre app
  stéréo XR impose Landscape Left — noté comme divergence assumée ci-dessous) ;
  Auto Graphics API = **désactivé**, Graphics API = **OpenGLES3** ; Scripting Backend = **IL2CPP** ;
  Target Architecture = **ARM64** ; Minimum API Level = **Android 10.0 (API 29)** ;
  Target API Level = Automatic ; VSync = Don't Sync ; multithreaded rendering **désactivé** si
  contenu Overlay.
- **Caméra RGB (Eye)** : classe `RGBCameraTexture` (namespace `Unity.XR.XREAL` en SDK 3.x ;
  ex-`NRRGBCamTexture` de NRSDK). Format **YUV_420_888 exclusivement** : `GetYUVFormatTextures()`
  renvoie 3 textures (Y, U, V) → conversion RGB par **shader** (pas de `GetRGBTexture()` natif).
  Cycle `Play()` / `Stop()`. **Seul l'accessoire Eye des XREAL One series** supporte la capture.
- **Permissions Android** (doc « Access RGB Camera ») : `RECORD_AUDIO` +
  `FOREGROUND_SERVICE_MEDIA_PROJECTION` sont **explicitement exigées** pour l'Eye. `CAMERA` non
  citée par cette page mais requise par convention Android pour tout accès caméra → on la déclare.
  `INTERNET` ajoutée pour le futur transport WebRTC (E24). Toutes demandées au runtime via
  `PermissionGate`.

Décisions de conception E22 :
- **Scène G1Gate.unity construite par script Editor** : écrire un `.unity` YAML valide à la main
  (GUIDs, fileIDs, refs de composants) est trop fragile sans Unity pour valider. On fournit
  `Assets/Scripts/Editor/G1SceneBuilder.cs` (menu `MLOmega/Build G1 Gate Scene`) qui construit et
  sauvegarde la scène en un clic. Choix documenté ici comme prévu par le plan.
- **Incertitude matérielle actée** (héritée du handoff §1.2.4) : la doc dit « One series » sans
  citer explicitement One Pro pour l'Eye. Si l'Eye est inaccessible sur le matériel réel → plan B
  `one-xr` (pose Kotlin natif, MIT) + caméra du S25. Documenté dans le README (checklist G1).
- **Divergence orientation assumée** : la doc XREAL sample recommande Portrait ; une app de rendu
  stéréo XR impose Landscape Left. On choisit Landscape (cohérent avec le rendu stéréo XREAL) et on
  le note ici.
- **Impossible de compiler ici** : aucun Unity/Android SDK dans ce conteneur. Le C# est écrit pour
  la fidélité doc + rigueur, non vérifié par compilation. La validation finale est **matérielle**
  (S25 + XREAL), via la checklist `apps/xr-mobile/README.md`. E22 n'est pas coché [x].


## 2026-07-04 — E23 App Unity noyau (contrats, session, capture, pose, clock-sync)

Section E23. Décisions et divergences consignées :

- **Sérialisation JSON = Newtonsoft.Json (package Unity officiel), pas System.Text.Json.**
  Les POCOs générés dans `packages/contracts/csharp/` ciblent `System.Text.Json`
  (`[JsonPropertyName]`) et utilisent un namespace *file-scoped* (C# 10). Unity 6
  n'embarque pas System.Text.Json et son compilateur par défaut ne garantit pas le
  namespace file-scoped. Choix : les copies Unity (`Assets/Scripts/Contracts/`) sont
  réécrites vers `Newtonsoft.Json` (`com.unity.nuget.newtonsoft-json`, package officiel
  éprouvé, IL2CPP-safe) avec `[JsonProperty]` + namespace *block-scoped*. C'est
  l'option la plus robuste pour Unity 6 et elle est **réversible** (un seul dossier
  synchronisé, régénérable). `Editor/SyncContracts.cs` (menu *MLOmega/Contracts/Sync
  from repo*) recopie depuis la racine du repo et applique la transformation, produisant
  une sortie identique aux copies committées (source de vérité intacte, jamais éditée à
  la main). En-tête « copie synchronisée — ne pas éditer » sur chaque fichier.
- **Collision `ReflexEvent`** : `packages/contracts/csharp/ReflexEvent.cs` ET
  `HotSceneContext.cs` déclarent chacun une classe `ReflexEvent` dans le même namespace.
  En Python/module isolé ce n'est pas un problème ; en Unity toutes les `.cs` compilent
  ensemble → doublon de type. Décision : la copie synchronisée de `HotSceneContext.cs`
  supprime le `ReflexEvent` imbriqué (le `SyncContracts` fait de même), `ReflexEvent.cs`
  reste la classe canonique. Divergence côté Unity uniquement, sans toucher aux sources.
- **Protocole ClockSync** : `services/live-pc/sessionhub.py` est aujourd'hui une classe
  in-process (`SessionHub`) sans serveur HTTP/WS (le front live-pc arrive en E24). Le
  client C# reproduit **exactement** la sémantique : `ClockSync.ComputeSample` applique
  les formules de `complete_clock_sync` — `rtt = (client_recv - client_send) -
  (server_send - server_recv)` et `offset = ((server_recv - client_send) + (server_send
  - client_recv)) // 2` avec **division plancher** (comme le `// 2` Python, y compris
  offsets négatifs). Le meilleur échantillon (RTT min) d'une rafale gagne, comme
  `current_offset_ns`. Les tests EditMode rejouent les mêmes entrées numériques que
  `tests/v19/test_sessionhub.py` (offsets -5 ms / +8 ms, tolérance 100 µs) pour prouver
  la symétrie client/serveur. Transport abstrait (`IClockSyncTransport`) ; l'impl HTTP
  (`SessionHubClient` + `HttpClockSyncTransport`, `UnityWebRequest`) mappe 1:1 les
  méthodes du `SessionHub` sur `POST /session/{create,renew,clock-sync}` — le serveur
  E24 n'aura qu'à exposer ces routes. Gestion d'erreurs réseau réelle (retry borné par
  config, état `Unsynced`), jamais d'exception propagée.
- **Extension d'interface `IXRDeviceAdapter`** : ajout de `IsStereo` et `FrameSource`
  (modification ciblée autorisée : on étend, on ne réécrit pas). Les trois adaptateurs
  les implémentent ; `XrSessionController` expose `IsStereo` pour que l'overlay/UI
  choisisse rig stéréo vs 2D plein écran. `PhoneOnlyAdapter` = `IsStereo=false`,
  `source=phone_camera`, pose identité — cible téléphone-only de premier rang (handoff
  §3.5), pas un fallback : une caméra absente passe en état `Error` (pas de frames
  fabriquées, contrairement au simulateur qui, lui, est un chemin de dev assumé).
- **Sélection d'adaptateur** : `MLOmegaConfig.Adapter` (`auto|xreal|simulated|phone_only`)
  mappé par `AdapterSelector` sur les couples `display`/`capture` de
  `configs/user_profile.yaml` (correspondance en commentaire dans `AdapterSelector.cs` et
  `MLOmegaConfig.cs`). `XrSessionController` utilise la config si assignée, sinon conserve
  le comportement E22 (simulateur en éditeur, XREAL sur device) — rétrocompatible.
- **Zéro alloc par frame** : `EyeCaptureSource` réutilise un `FrameEnvelope`, un `Pose` et
  leurs listes position/rotation ; `FormatFrameId` construit `f_<n>` via `stackalloc`
  (une seule allocation string, imposée par le contrat). Pose échantillonnée **à la
  capture** (`PosePublisher.SampleNow`), pas au rendu.
- **Impossible de compiler ici** (comme E22) : pas de SDK Unity/.NET dans cet
  environnement (seul le host `dotnet` runtime est présent, aucun SDK). Le C# est écrit
  pour la fidélité doc + rigueur et relu, non vérifié par compilation. Les tests EditMode
  sont écrits pour passer au premier clic dans le Test Runner. E23 n'est pas coché [x] :
  validation Unity/matériel par l'utilisateur, couplée au gate G1.

## 2026-07-04 — E24 Transport mobile (SessionHub HTTP, signaling unifié, plugin Android)

Section E24. Décisions et divergences consignées :

- **Serveur HTTP SessionHub** (`services/live-pc/sessionhub_http.py`) : app FastAPI
  qui **expose** la classe `SessionHub` existante sans la réécrire (chargée par
  `importlib` comme les tests). Routes/JSON **1:1** avec `SessionHubClient.cs` (E23) :
  `POST /session/create` → `{session_id, token, created_at_utc}` ;
  `POST /session/clock-sync {session_id, token, client_send_ns}` →
  `{server_recv_ns, server_send_ns}` (deux estampes monotones égales, comme
  `SessionHub` collapse `server_send_ns := server_recv_ns`) ; `POST /session/renew`
  → nouveau token (rotation + révocation de l'ancien) ; `GET /health`. Auth par le
  token éphémère (`SessionHub.authenticate`) sur renew/clock-sync → **401** si le
  couple `(session_id, token)` ne correspond pas. **Port 8710** = `MLOmegaConfig.cs
  SessionHubPort` (87xx, jamais 8766). L'offset reste calculé côté client
  (`ClockSync.ComputeSample`), le serveur ne renvoie que les estampes ; le test
  `tests/v19/test_sessionhub_http.py` **rejoue les fixtures numériques de
  `test_sessionhub.py`** (+5 ms / −8 ms) pour prouver la symétrie Python/C#/HTTP.
- **Piège FastAPI** : les symboles FastAPI (`Request`) sont importés **au niveau
  module**, pas dans `create_app`. FastAPI résout les annotations de route via
  `typing.get_type_hints` contre `__globals__` de la fonction (pas la closure) ; un
  `Request` local est mal interprété en paramètre de query → 422. Consigné car
  contre-intuitif.
- **Signaling unifié** (`POST /webrtc/offer`, servi par la même app 8710) : SDP offer
  in → SDP answer out, **token de session exigé**. Le cœur de négociation a été
  **extrait** de `AiortcIngress._handle_offer` vers `AiortcIngress.handle_offer_sdp`
  (extension, pas réécriture) ; l'ancienne route aiohttp `/offer` continue de
  fonctionner (rétrocompatible), le nouvel endpoint FastAPI la réutilise.
  `fake_xr_device` gagne un paramètre `token` optionnel : présent → il cible
  `/webrtc/offer` avec `{session_id, token}` (même surface que le futur client
  Android) ; absent → chemin `/offer` inchangé.
- **Downlink DataChannel** : `AiortcIngress` enregistre les DataChannels entrants et
  expose `send_ui_intent(json)` pour renvoyer un UIIntent au device ; le routage des
  messages montants distingue par forme (FrameEnvelope = `capture_monotonic_ns` ;
  sinon UIReceipt → callback `on_receipt`). Le test `test_e24_roundtrip.py` prouve le
  critère de fin E24 côté PC : frame_id/pose intacts, UIIntent renvoyé avec le bon
  `target_track_id`, UIReceipt remonté jusqu'à `record_delivery_feedback`
  (`brainlive_intervention_feedback_events_v188`).
- **Plugin Android** (`apps/xr-mobile/android/livetransport/`, lib Gradle autonome) :
  **GetStream `io.getstream:stream-webrtc-android:1.3.10`** — dernière version stable
  (vérifiée sur https://github.com/GetStream/webrtc-android/releases le 2026-07-04 ;
  coordonnée Maven confirmée via le README GetStream). Choix imposé par le handoff §4
  (seul binding libwebrtc largement maintenu) ; **figée** au premier build reproductible
  (risque roadmap Stream). Classes dans le package standard `org.webrtc` → le code est
  un binding libwebrtc portable si la source change.
- **Voie capture vidéo GetStream** : `VideoCapturer` custom (`UnityFrameCapturer`) piloté
  par un `SurfaceTextureHelper`, alimenté par un `VideoFrameFeeder`. Chemin **texture OES
  zéro-copie** privilégié (`TextureBufferImpl` sur le thread GL du helper, la frame reste
  sur le GPU jusqu'à l'encodeur H.264) ; **fallback ByteBuffer I420** (`JavaI420Buffer`)
  pour les modes sans texture partagée (capture-only). C'est la voie **documentée par
  GetStream/libwebrtc** pour injecter des frames externes (vs un `VideoSource` brut), d'où
  ce choix. `UnityPushVideoFeeder` = forme *push* JNI-friendly appelée depuis C#.
- **H.264 low-latency** : préférence codec **explicite dans le SDP** (`SdpCodecPreference`
  hisse les payloads H264 en tête de `m=video` et force
  `packetization-mode=1;profile-level-id=42e01f` — constrained-baseline, mono-NAL). Logique
  = transformation de chaîne pure → **testée hors device** (`SdpCodecPreferenceTest`,
  `./gradlew test`). Opus 20 ms micro : `minptime=20;usedtx=1;useinbandfec=1` + `a=ptime:20`.
- **Reconnexion & bitrate adaptatif** : backoff exponentiel **borné** (`BackoffConfig` :
  delay plafonné, jitter, max_attempts) ; adaptation pilotée par `getStats()` (fraction
  perdue + RTT depuis `remote-inbound-rtp`), tous les **seuils en config** (`AdaptiveConfig`,
  jamais en dur) → baisse `maxBitrateBps` + monte l'échelon `scaleResolutionDownBy`, remonte
  après N sondes saines. États `connected/degraded/reconnecting/disconnected` en callbacks
  vers Unity. Politique alignée sur GUIDE_V19_REFERENCE §8.4 « Transport vidéo dégradé ».
- **Config JNI** : les défauts de data-class Kotlin ne sont pas atteignables via
  `AndroidJavaObject` (JNI ne voit que le constructeur plein) → `LiveTransportConfigFactory.forUnity`
  (`@JvmStatic`) construit la config avec les seules valeurs que Unity varie.
- **Bridge Unity** (`Assets/Scripts/Transport/LiveTransportBridge.cs`) : wrapper
  `AndroidJavaObject` + `AndroidJavaProxy` (callbacks natifs), abonné à
  `EyeCaptureSource.OnFrame` (E23), pousse la texture œil (`GetNativeTexturePtr` → id OES),
  relaie UIIntent (désérialisé Newtonsoft) ↓ / UIReceipt ↑, re-émet l'état natif en
  événements C# marshalés sur le thread principal Unity. **Éditeur/Windows = mode
  DIRECT_PYTHON** : pas de plugin Android, transport no-op ; le côté PC est exercé par
  `simulators/fake_xr_device` (chemin `SimulatedDeviceAdapter`) contre le même
  `/webrtc/offer`. `MLOmegaConfig.WebrtcOfferUrl` ajouté (même host/port que le SessionHub).
- **Impossible de compiler l'Android ici** : pas d'Android SDK/Gradle dans cet
  environnement. Le Kotlin est écrit pour la fidélité à l'API GetStream/libwebrtc épinglée
  et relu ; la compilation + la validation S25 (gate matériel) sont différées. Seuls les
  tests PC (`test_sessionhub_http`, `test_transport_webrtc` unifié, `test_e24_roundtrip`)
  sont exécutés et verts ici.

## 2026-07-04 — E25 Design system liquid glass (UIRuntime, 10 composants, receipts)

Section E25 (seconde moitié ; `SceneCache`/`SceneCacheConfig` §9.1 et `UIIntentBroker`
§13.2/§15.3 déjà mergés dans une première passe). Décisions et divergences consignées :

- **Blur liquid glass = Kawase dual-filter dans une `ScriptableRendererFeature` URP 17
  (RenderGraph)** plutôt qu'un GrabPass (inexistant en URP) ou un flou par-panneau. Le
  flou de l'arrière-plan caméra est calculé **une seule fois par frame** dans
  `GlassBlurFeature` (`GlassKawaseBlur.shader`, down/up sur une petite chaîne demi-rés) et
  publié comme texture globale `_MLOmegaGlassBlur` (`SetGlobalTextureAfterPass`), que tous
  les panneaux `LiquidGlass.shader` échantillonnent en espace écran — coût du flou
  indépendant du nombre de panneaux. Kawase choisi pour un flou large et lisse en très peu
  de passes (crucial sur GPU mobile XR où il tourne chaque frame). **Fallback réel** : si la
  feature est absente (blur désactivé, Compatibility Mode, ou RendererData sans la feature),
  le mot-clé global `_HAS_BLUR_TEX` reste off et le shader retombe sur un verre translucide
  plat + rim + grain — un rendu de verre valide, jamais une erreur dure. Le rim est teinté
  par l'accent de niveau de vérité (`UITheme.AccentFor`), donc la bordure encode la vérité.
- **UGUI world-space en code, pas de prefabs** : chaque panneau est un `Canvas` world-space
  (1 unité = 1 m) construit par `GlassPanel` en C#, comme la scène est générée par
  `E25SceneBuilder` — mêmes raisons que G1/E24 (pas d'éditeur Unity ici pour valider le YAML
  de prefab/scène ; tout le design system reste relisible en un point).
- **StatusBar hors registre d'admission** : les 10 composants §13.1, mais StatusBar est une
  surface **permanente** (source « S25 », priorité rung 1 jamais comptée/plafonnée par le
  broker) → `MonoBehaviour` autonome head-locked, **pas** dans `UIComponentRegistry` (le
  runtime n'instancie que les 9 composants pilotés par intent). StatusBar **étend** le rôle
  de `G1StatusOverlay` (version glass glançable : cam/micro/réseau/PC/privacy/mode) **sans le
  casser** — le panneau diagnostic verbeux G1 reste pour le gate ; les deux coexistent.
- **Timer `seen` prudent** : `seen` n'est **jamais** émis à l'affichage — seulement après un
  dwell configurable (`UIComponentBase._seenDwellSeconds`, défaut 1,2 s) mesuré depuis la
  première frame visible. `seen` = exposition, pas compréhension (§13.3). `displayed` est émis
  une fois, dès que l'alpha du fade-in franchit le seuil visible ; `dismissed` **uniquement**
  sur suppression utilisateur explicite (les autres retraits — TTL/track perdu/éviction —
  fadent en silence, le broker ayant déjà journalisé le `ui_intent_drop_reason`).
- **Mapping composant→type** : `UIComponentRegistry` normalise la chaîne `component` du
  contrat (minuscule, alphanumérique) → type concret, avec quelques alias (`translation`→
  Subtitle §14.4, `lens`→LensWindow, `arrow`→OffscreenArrow). Statique et pur → testé sans
  éditeur.
- **Vérité §17.2 centralisée** : `TruthDescriptor` (struct pur) résout badge « probable »,
  âge last-seen humanisé (depuis `age_ms`/`last_seen_ms` de `content`/`ui_hint`), étiquette
  hypothèse (inferred), et accent. Règles dures appliquées par composant : `PersonTag`
  n'affiche **aucun nom** sous `IdentityNameConfidenceThreshold` ; `OffscreenArrow` ne dessine
  **rien** sous `MapQualityArrowThreshold` (« jamais de flèche sans qualité de carte », §14.6)
  ; `PersonTag` s'ancre **au-dessus** du bbox visage, jamais dessus.
- **Receipts qui ne se perdent pas** : `UIReceiptTransportSink` délègue à un `ReceiptOutbox`
  pur (file **bornée** FIFO ; drop du plus ancien au-delà de `maxPending`) ; flush à la
  reconnexion (`LiveTransportState.Connected`), ordre préservé, ne throw jamais (contrat
  `IReceiptSink`). Le seam pur rend la file testable sans WebRTC.
- **Drive déterministe pour les tests** : `UIComponentBase.Tick(now, dt)` est public (miroir
  de `SceneCache.Tick`/`UIIntentBroker.Tick`) pour que les tests EditMode avancent
  l'animation + la timeline de receipts sans player loop.
- **Impossible d'ouvrir Unity ici** : pas d'éditeur/compilateur Unity dans cet environnement.
  Le C#/HLSL est écrit pour l'API URP 17/RenderGraph et TMP (ugui 2.0) et relu ; la
  compilation, les tests EditMode et la validation visuelle éditeur/S25 sont différées à la
  première ouverture par l'utilisateur.


## 2026-07-04 — E26 Ultra-Live device (ADR)

- **Versions épinglées** (recherche ciblée, sources officielles) : MediaPipe `com.google.mediapipe:tasks-vision:0.10.29` (HandLandmarker + GestureRecognizer en LIVE_STREAM) ; sherpa-onnx Android via JitPack `com.github.k2-fsa:sherpa-onnx-android:1.12.10` (alternative : AAR JNI des releases GitHub, documentée dans le README du module). Modèles référencés, non committés : FR `sherpa-onnx-streaming-zipformer-fr-2023-04-14`, EN `sherpa-onnx-streaming-zipformer-en-2023-06-26`, KWS zipformer (URLs et chemins d''installation dans `apps/xr-mobile/android/reflexvision/README.md`).
- **TemplateTracker : NCC pur C#** (corrélation croisée normalisée sur texture sous-échantillonnée) plutôt que Burst/compute shader : déterministe, testable en EditMode sans dépendance, budget CPU suffisant sur la fenêtre sous-échantillonnée ; si le profiling device montre un coût trop élevé, migration Burst possible sans changer l''API.
- **Gestes : machine à états pure Kotlin** séparée du câblage MediaPipe → unit-testable en JVM sans device ; hystérésis + durée minimale contre les faux positifs, seuils dans un objet de config.
- **Scheduler** : détecteurs natifs (HandLandmarker, ASR) activés à la demande par le ReflexScheduler Unity (§9.4 — jamais tous en parallèle) ; budget de skills simultanées en config.
- **Aucun LLM/VLM dans ce chemin** (handoff §3.2) : tous les calculateurs sont locaux et spécialisés ; FocusSearch interroge VisionRT par DataChannel uniquement quand connecté, sinon réponse honnête locale.
- **ReflexEvents agrégés** par `aggregate_key` avec fenêtre glissante ; une sévérité `critical` est flushée immédiatement (test dédié).


## 2026-07-04 — E27 VisionRT + AudioRT PC (ADR)

Tout E27 est du Python testable sur la machine cible (RTX 3070) ; les tests sont
exécutés et verts ici (pas de dépendance matériel externe).

- **Détecteur : YOLOX-nano ONNX officiel Megvii** (release `0.1.1rc0`,
  `yolox_nano.onnx`, sha256 `c789161e…`, entrée + provenance dans
  `configs/MODEL_MANIFEST.yaml`). **Licence Apache-2.0** — choisi contre un
  YOLO-nano exporté via Ultralytics dont le poids exporté hériterait de l'AGPL-3.0.
  Sortie standard `[1,3549,85]` (4 bbox + obj + 80 classes COCO), décodée
  maison (grilles/strides, NMS numpy). ONNX Runtime : sélectionne
  `CUDAExecutionProvider` si présent, sinon CPU. Sur cette machine c'est la
  build CPU (les tests V18 en dépendent) — détecteur mesuré à P50 9,9 ms / P95
  10,5 ms, largement sous budget ; le chemin GPU est prêt sans changement de code.
  Tentative `onnxruntime-gpu` en venv isolé : provider CUDA détecté mais retombée
  CPU faute de cuDNN 9 apparié (friction packaging Windows) — non bloquant,
  budget déjà tenu.
- **Tracker : ByteTrack maison** (`services/live-pc/tracking.py`), sans
  dépendance lourde : Kalman vitesse-constante 8-dim par track + association IoU
  gloutonne en deux passes (haute puis basse confiance pour récupérer les
  occlusions courtes), ids courts stables (`t1`, `t2`…), `age`/`visibility`.
  `predict_only()` interpole entre deux passes détecteur (contrat §3.6). Tourne
  toutes les frames (CPU, ~140 fps brut).
- **Cadence détecteur adaptative 5-15 fps** pilotée par un score de mouvement
  inter-frames (delta luma moyen) + demande de focus ; bornes et seuils
  (`motion_low/high`) dans `configs/profiles/rtx3070.yaml`, jamais en dur.
  Vérifié : scène statique → 5 fps, mouvement → monte ; sur bench 300 frames le
  détecteur n'a tourné que sur 106 (le reste interpolé).
- **OCR : rapidocr_onnxruntime (Apache-2.0)** sur crop uniquement, plafond
  `max_roi_px`, jamais plein écran ; classe GPU `ocr`.
- **VLM crop : Ollama un-job-à-la-fois**, sémaphore 1, admission `vlm` via
  GpuArbiter, timeout court ; Ollama injoignable → `status:"vlm_unavailable"`,
  `truth_level:"inferred"`, jamais de blocage. Testé pour de vrai avec Ollama
  éteint (chemin dégradé honnête).
- **VAD : webrtcvad** (ADR) plutôt que silero-onnx : déjà dépendance, pas de
  poids ONNX supplémentaire, déterministe sur frames 10/20/30 ms, CPU pur donc
  jamais en concurrence GPU avec le détecteur.
- **ASR : faster-whisper `small` int8**, `device=cuda` si CTranslate2 CUDA
  dispo (c'est le cas ici — mesuré ~200-380 ms/segment sur la RTX 3070, sous le
  budget partiel < 1 s), sinon CPU. Détection de langue par whisper. **Classe GPU
  dédiée `asr`** ajoutée aux budgets du profil et au GpuArbiter, placée dans le
  plancher réflexe protégé (jamais budget-refusée — §3.6 « ne jamais toucher aux
  sous-titres »).
- **Traduction : Argos Translate (CTranslate2, MIT), sans LLM.** Paires en↔fr
  installées via `fetch_models_v19.py --argos` ; **zh→fr absent de l'index Argos**
  → non installé, dégradation honnête `no_pack` (noté au manifest). Vérifié
  fr→en de bout en bout.
- **Sous-titres = chemin réflexe** : `UIIntent subtitle` (partiel puis final)
  poussés directement via le DataChannel du gateway (`producer=ultralive`),
  jamais par la queue BrainLive (§3.2). Aucun LLM conversationnel dans ce chemin.
- **SceneDelta** liée à `source_frame_id`, entities[] (track_id/kind/label/bbox/
  confidence/visibility/age), changes[] appeared/disappeared, `expires_at` (TTL
  config). Poussée au device ET disponible en callback pour WorldBrain (E28).
- **Sélecteur de keyframes** (score histogramme + mouvement, espacement minimal)
  → `v19_keyframes.register_xr_keyframe` (insert_only `vision_frames`,
  `capture_mode='xr_keyframe'`) : le pont E14 vers la chaîne nocturne, en
  production live. Vérifié : keyframe → ligne `vision_frames` `xr_keyframe`.
- **Dégradé (`degraded.py`)** : `apply_action_level` mappe l'échelle §3.6 sur
  VisionRT — `detector_floor` clampe à `fps_min`, `pause_change_detection` gèle
  keyframes + changes, `refuse_vlm` refuse le VLM ; tracker et sous-titres jamais
  touchés. Métriques (`vision_infer_ms`, `ocr_ms`, `vlm_queue_depth`,
  `scene_delta_rate`, drops) exposées en `/metrics` (`live_pipeline.py`).

## 2026-07-04 — E28 WorldBrain + spatial + scene adapter (ADR)

Tout E28 est du Python testable sur la machine cible ; `pytest tests/v19 -q` =
78/78 verts (66 E27 + 12 E28), suite V18 inchangée. Le cœur `src/` n'est modifié
que par appels (aucune édition, aucun schéma parallèle — piège #11).

- **Promotion track→entité (§7.1)** : un track ne devient `WorldEntity` qu'après
  `promote_min_observations` (défaut **3**) sightings **confirmés** au-dessus de
  `promote_min_confidence` (défaut **0.35**). Une seule bbox faible ne promeut
  jamais (testé : 5 détections à conf 0.10 → 0 entité). Seuils en config
  (`WorldBrainConfig`, profil `worldbrain:`), jamais en dur.
- **Observations / relations / changes** : `Observation` datée et corrigeable
  (frame_id, track_id, state, model, confidence, evidence) ; `Relation`
  (`on_top_of`/`near`/`holds`) dérivée **géométriquement** des bboxes de la frame
  courante (relations frame-scoped, non persistées comme faits durables) ;
  `ChangeEvent` `appeared`/`disappeared`/`moved` avec before/after evidence
  (`moved` = décalage du centre > `moved_center_ratio`·diagonale ;
  `disappeared`/`last_seen` après `stale_after_seconds`).
- **Persistance en couches** : last-seen + changes → `visual_events_v19` via
  `store_visual_event` (`memory_owner_id` explicite) ; résumé de fin de session →
  `scene_session_summaries_v19` via `store_scene_summary` ; état courant →
  **vraies** tables `brainlive_world_states` / `vision_scene_observations` via
  `v19_visual_context.publish_visual_context` (reprises par le wrapper
  `v18_context`). Le bookkeeping de session vit dans un SQLite **service-local**
  léger (`worldbrain_session_*`) — **aucune nouvelle table dans le cœur**.
- **Spatial V19.A (`spatial.py`, `PoseKeyframeMap`)** : zones par clustering de
  positions de pose (rayon config) ; `bearing_to(entity)` = direction relative
  pose courante → pose de dernière observation (yaw quaternion→euler autour de
  l'axe up). **`map_quality` mesurée** = densité (nb de poses) × fraîcheur
  (décroissance exp sur `freshness_horizon_s`) × cohérence (compacité du nuage).
  **Règle absolue** : `bearing_to` retourne `None` si `map_quality <
  min_map_quality_for_bearing` (défaut **0.35**) — **jamais de fausse flèche**
  (testé : pose unique dispersée → mq 0.006 → bearing None ; nuage dense frais →
  mq 0.999 → bearing 90° à 2 m).
- **Point d'entrée BrainLive — choix : `enqueue_delivery` direct.**
  `brainlive_scene_adapter.py` construit périodiquement (cadence config,
  événementiel) un `HotSceneContext` conforme au contrat, budget **dur** en
  caractères (défaut 4000 ; over-budget → `omissions` traçables, esprit §2.4 ;
  log d'omission borné + compteur `+N_more` pour qu'un flot de champs droppés ne
  fasse pas exploser le budget lui-même). Puis, quand une **situation §12.4** le
  justifie (personne connue en scène au-dessus du seuil d'identité, objet perdu
  redevenu visible, tâche active), il construit le candidat et appelle
  **directement `v18_delivery.enqueue_delivery`** (`decision='notify'`,
  `source_key` = `scene:{session}:{sujet}` significatif = frontière de dédup,
  evidence refs). **Rationale** : le point d'entrée hot-loop
  (`v18_8_live_policy`/`brainlive_hotloop`) attend un bundle
  episode/manifest/fused/route produit par la chaîne d'assemblage offline — une
  scène live n'en a aucun. `enqueue_delivery` est la primitive H1 unique et
  documentée (handoff §8.1), elle porte dédup + cooldown, et c'est le choix
  **réversible** : un futur pas peut substituer le hot-loop sans changer le
  contrat de queue. Le `delivery_adapter` E6 achemine ensuite jusqu'aux lunettes.
  Avant l'enqueue, l'adapter garantit la ligne `brainlive_sessions` (via
  `publish_visual_context(world_state=None)`) pour que la résolution d'owner de
  `enqueue_delivery` réussisse.
- **§17.2 respecté** : pas de nom sous le seuil d'identité
  (`person_conf_threshold`), pas de flèche sous le seuil de carte. WorldBrain ne
  produit **aucun** profil psychologique ni sortie UI arbitraire (§ne-fait-pas du
  handoff) : il rapporte des faits, BrainLive décide.
- **Câblage `live_pipeline.py`** : `enable_worldbrain` branche
  VisionRT→WorldBrain (via le callback `_on_scene_delta`), pose→`PoseKeyframeMap`
  (dans `on_video_frame`), transcript final AudioRT→scene_adapter
  (`note_transcript`), `end_session()`→résumé+flush. Métriques `map_quality`,
  `last_seen_count`, `change_events`, `entities_promoted`, `hot_context_builds`,
  `deliveries_enqueued` exposées sur `/metrics`.


## 2026-07-04 — E29 clôture (phone_only e2e + fix WebSocket)

- **Bug de prod débusqué par le e2e** : `delivery_adapter.create_app` importait `WebSocket` localement ; avec `from __future__ import annotations`, FastAPI résout les annotations dans les globals du module → paramètre dégradé en query requis → toute connexion fermée en 1008. Le test E10 historique ne le voyait pas (hub testé avec un faux websocket). Fix : import fastapi au niveau module (fallback None si absent). Transport 23/23 re-validé.
- `services/live-pc/profile.py` : loader du profil §3.5 avec validation et repli sûr par valeur ; `renderer_route()` → websocket (phone_only/companion_web) ou datachannel (lunettes). `configs/user_profile.yaml` ajouté au .gitignore (fichier personnel généré par setup_profile).
- e2e phone_only : profil → `enqueue_delivery` (session bootstrapée par `publish_visual_context`, même primitive qu''E28) → WebSocket viewer (contrat companion-web exact) → receipts `delivered`+`displayed` persistés dans `brainlive_intervention_feedback_events_v188`.
- Périmètre E29 : chaînes live des 16 scénarios prouvées en simulation (in-process + 3 clés en WebRTC réel) ; profondeur mémoire/LLM différée au test final close-day (décision utilisateur).

## 2026-07-04 — E31 Conversation live → BrainLive V18.8 (le branchement prioritaire) (ADR)

Constat : le moteur conversationnel du cœur existe **en entier** (turn buffer, politique de debounce `v18_8_live_policy.plan_live_dispatch`, hot capsule/relation packs/open loops, hot loop H1 `brainlive_hotloop_v15_6`, queue de delivery consommée par `delivery_adapter` E6). Le seul manque : l'entrée. AudioRT produisait des sous-titres (voie réflexe DataChannel) mais rien n'écrivait les segments finaux dans le turn buffer.

Point d'entrée retenu (le VRAI, vérifié dans le code) : la fonction officielle d'ingestion **`brainlive_v15.ingest_live_turn(live_session_id, text, *, is_final, timestamp_start, timestamp_end, speaker_label, metadata)`** — source-addressable (map `v18_turn_source_map`, un retry met à jour le même tour logique), écrit dans **`brainlive_turn_buffer`**, exige une session `brainlive_sessions` **active** et un `person_id` réel. La réactivité vient ensuite de `plan_live_dispatch(audio_content=True)` (fenêtres `MLOMEGA_BRAINLIVE_LLM_*` : min 12s, audio_window 45s, max 90s) → si dispatch dû → `optimized_hot_brainlive_cycle(meaningful_signal=True)` (identity/place/context/fuse/route/predict) → `_record_hot_success` → `enqueue_delivery` (une décision proactive H1 `queue`) → queue → `delivery_adapter` → device. C'est exactement le chemin que `brainlive_service_v15_5.service_iteration` emprunte, sans son inbox fichiers.

Alternatives écartées :
1. **Lancer le daemon complet `brainlive_service_v15_5`** (boucle inbox) : rejeté — il surveille des répertoires de médias bruts et possède l'ordonnancement nightly/close-day, hors périmètre d'un pipeline XR live ; il imposerait aussi un modèle de fichiers là où V19 a déjà les segments en mémoire.
2. **Réutiliser le chemin `enqueue_delivery` direct d'E28 (scene adapter)** : rejeté pour la conversation — ce chemin est bon pour une situation de scène (personne connue/objet retrouvé/tâche) mais **court-circuite** le raisonnement conversationnel (capsule/mémoire/open loops) qui est précisément la capacité V18.8 attendue ici. On le laisse tel quel pour la scène (E28) et on branche le hot loop pour la conversation (E31).
3. **Un module additif `v19_conversation_ingest.py` dans le cœur (§2.8)** : inutile — l'entrée existante `ingest_live_turn` couvre exactement le besoin. Aucune modification de `src/` (INTERDIT respecté).

Décision `tick()` : le cœur du hot loop est l'unité réutilisable ; `ConversationBridge.tick()` l'expose pour un appel synchrone par `live_pipeline` juste après l'atterrissage d'un tour, au lieu de démarrer un daemon. Cadences inchangées (défauts cœur) ; surchargables par les `MLOMEGA_BRAINLIVE_LLM_*` si le XR exige plus court — noté, aucun défaut modifié.

Frontière LLM (test réactivité) : si Ollama sert un modèle (`/api/tags` non vide) → run réel. Sinon, **seule** la frontière de service externe `mlomega_audio_elite.llm.OllamaJsonClient.require_json` est monkeypatchée avec un JSON valide au schéma `HOT_UNIFIED_SCHEMA`, dont l'evidence **référence un vrai item du manifeste** (un tour `brainlive_turn_buffer` amorcé) — le validateur strict `_hot_output_contract`/`validate_resolvable_manifest_evidence` (allow-list manifeste + résolution DB owner/session/temps) tourne quand même. C'est une frontière de service, pas un stub de pipeline.

Livrables : `services/live-pc/conversation_bridge.py` (`ConversationBridge` : session partagée V19 via `start_live_session`, `ingest_segment` final → `ingest_live_turn`, `tick()` = politique + hot cycle, métriques) ; câblage `live_pipeline.py` (segment final AudioRT → `conversation.ingest_segment` ; métriques `conversation_turns`/`h1_candidates`/`hot_cycles` sur `/metrics` ; `enable_conversation`/`conversation_bridge` en paramètres). Tests `tests/v19/test_e31_conversation.py` (wiring turn buffer, réactivité mémoire→candidat H1 avec evidence, bout-en-bout WebSocket viewer réutilisant le pattern E29 phone_only). **`pytest tests/v19 -q` = 84 passed** ; cœur `src/` inchangé ; V18 non touchée.

Latence attendue transcript→suggestion (d'après les fenêtres de la policy) : le premier tour d'une session dispatche immédiatement (`last_dispatch_epoch==0`) ; ensuite un tour de parole (`audio_window`) déclenche après ≈45s d'accumulation, ou après le `min_interval` de 12s sur frontière de silence/changement sémantique, plafonné à 90s (`max_window`). Le hot cycle lui-même vise `target_ms≈12s`. XR peut raccourcir via `MLOMEGA_BRAINLIVE_LLM_AUDIO_WINDOW_S`/`MLOMEGA_BRAINLIVE_LLM_MIN_INTERVAL_S`.


## 2026-07-04 — E32 Identité multi-indice (visage + voix + enrollment + correction) (ADR)

Constat : aucune reconnaissance faciale live ; l'identité vocale du cœur (`voice_identity.py`, ECAPA SpeechBrain, tables `voice_embeddings`/`speaker_profiles`, flow `voice-pending`) existait mais n'était pas branchée au flux live ; « personne connue » n'existait donc pas en session → scénarios 2/3 bloqués. Les tuyaux d'accueil, eux, étaient déjà là : `worldbrain.py` promeut des entités person anonymes, et `brainlive_scene_adapter._identify_people`/`evaluate_situations` a déjà le déclencheur ContextCard `p.get("identified") and p.get("name")` qui n'attendait que de vrais noms. E32 fournit les cues et la fusion, sans rien reconstruire.

**Choix modèles + licences (visage).** OpenCV Zoo **YuNet** (`FaceDetectorYN`, `face_detection_yunet_2023mar.onnx`, ~230 Ko, **MIT**) pour la détection+landmarks, **SFace** (`FaceRecognizerSF`, `face_recognition_sface_2021dec.onnx`, MobileFaceNet loss SFace, **Apache-2.0**) pour l'embedding 128-D L2. Retenus plutôt qu'ArcFace/InsightFace parce que (1) les deux tournent via les classes **natives d'OpenCV** (`cv2.FaceDetectorYN`/`cv2.FaceRecognizerSF`) — zéro dépendance runtime au-delà d'`opencv-python` déjà requis par VisionRT ; `alignCrop`+`feature`+`match(...FR_COSINE)` sont fournis, pas de pré/post-traitement maison à maintenir ; (2) licences permissives sans taint copyleft (cohérent avec le rejet de l'export Ultralytics AGPL en E27) ; (3) minuscules → CPU suffit (SFace passe en job classe "ocr" via GpuArbiter si un GPU est libre, sinon CPU). Les deux poids sont épinglés `url + sha256 + license` au `MODEL_MANIFEST.yaml` et fetchés par `scripts/fetch_models_v19.py` (2 sources web, canoniques `github.com/opencv/opencv_zoo/raw/main/...`). Pipeline : crop person de VisionRT → YuNet (plus grand visage ≥ seuil) → `alignCrop` → SFace embedding → cosine contre galerie.

**Galerie visage = SQLite service-local**, à CÔTÉ du cœur (piège #11 : jamais de nouvelle table cœur) : `face_people(person_id, name)` + `face_embeddings(person_id, name, embedding, source, created_at)`. Le matching agrège le meilleur score par personne (plusieurs prises renforcent) et renvoie `None`/anonyme sous le seuil (§17.2). Embedder injectable → la logique de matching est testable sans les poids.

**Voix : réutiliser le cœur.** `voice_identity_live.py` appelle directement `voice_identity.enroll_voice`/`match_voice` quand la stack ECAPA est importable → **une seule galerie** partagée avec le flow nocturne/CLI (personne enrôlée la nuit reconnue live et inversement). Sélection automatique : cœur réel si importable, sinon embedder de substitution injecté (interface `embed_file(path)->list[float]`, matching cosine identique), sinon no-op « unknown » (ne bloque jamais le pipeline). Réserve honnête : SpeechBrain/torchaudio ne sont pas dans l'env système ici → le chemin live est prouvé avec le substitut, l'ECAPA réel est validé au close-day final. Le speaker résolu alimente `speaker_person_id`/`speaker_label` du tour **avant** `ingest_segment` (champ E31 laissé à None « identité en E32 », désormais branché).

**Seuils de fusion (config, jamais en dur).** SFace cosine `match_threshold=0.363` (défaut OpenCV Zoo, env `MLOMEGA_FACE_THRESHOLD`) ; ECAPA cosine `0.72` (miroir `MLOMEGA_VOICE_THRESHOLD` du cœur) ; `min_name_confidence=0.45` (plancher global pour afficher un nom, §17.2) ; `both_agree_bonus=0.15` (bonus quand visage+voix concordent). Règle de décision : concordance visage+voix (même person_id) → haute confiance nommée ; un seul cue fort au-dessus de son seuil → nommé à cette confiance ; **contradiction** (person_id différents) → **anonyme** (une contradiction n'est jamais résolue en devinette) ; rien au-dessus du seuil → anonyme. Persistance de track : une fois un `track_id` nommé, le nom reste collé pour la session (le visage n'est pas ré-embeddé chaque frame) mais ne surclasse jamais une contradiction live. Sur verdict confiant : nom écrit sur l'entité person WorldBrain (`person_id`/`person_name` → rentre dans le prochain SceneDelta → PersonTag device) **et** `scene_adapter.known_people[entity_id]` amorcé → le déclencheur §12.4 existant tire la ContextCard sans câblage supplémentaire.

**Enrollment vocal = pré-routeur spécifique et autonome** (le routeur général est E33 — gardé simple). Regex FR robustes + variantes EN : enroll « retiens[,:]? c'est X » / « souviens-toi de X » / « remember (this is) X » ; correction « (ce) n'est pas X » / « oublie X » / « no that's not X » / « forget X ». La correction est testée AVANT l'enroll (« pas X » ⊄ enroll) ; liste `_STOP_NAMES` filtre les faux noms grammaticaux. Enroll → capture meilleur crop visage récent du track person actif + segment voix → enrôle les deux galeries → UIIntent toast « Enregistré : X » ; correction → suspend le label (fusion track + entité WorldBrain + map scene_adapter) + trace durable via le **vrai** `memory_correction.revise_memory` (best-effort : `invalidate` sur un `atomic_memories` mentionnant le nom si une cible existe ; la suspension du label reste l'action opérante sinon) + UIIntent.

**Câblage économe.** Le visage tourne sur les crops person à cadence économe (nouveau track person OU toutes `identity_frame_interval=30` deltas, pas chaque frame) ; les segments finaux → voix → bridge ; les transcripts → enrollment_watcher (avant `ingest_segment`). Métriques `identity_matches`/`named_entities`/`identity_contradictions`/`enrollments`/`corrections`/`face_matches` sur `/metrics`.

Alternatives écartées : (1) **InsightFace/onnxruntime dédié** — dépendance runtime + poids plus lourds + pré-traitement maison, pour un gain de précision non nécessaire à l'échelle d'un outil personnel ; OpenCV natif suffit. (2) **Nouvelle table cœur pour les visages** — interdit (piège #11) ; galerie service-local comme WorldBrain. (3) **Réimplémenter l'embedding voix** — interdit et inutile, le cœur l'a déjà ; on branche `enroll_voice`/`match_voice`. (4) **Routeur d'intentions général maintenant** — c'est E33 ; le watcher reste un pré-routeur à deux intentions.

Livrables : `face_identity.py`, `voice_identity_live.py`, `identity_fusion.py`, `enrollment_watcher.py` ; câblage `live_pipeline.py` (`enable_identity`, cadence, embedders injectables) ; entrées `face_detector`/`face_embedder` du `MODEL_MANIFEST.yaml` + docstring `fetch_models_v19.py`. Tests `tests/v19/test_e32_identity.py` : **vrai** YuNet+SFace sur `skimage.data.astronaut()` (enroll → match sous relight → nommé ; inconnu → anonyme) ; fusion (concordance/voix seule → nommé, contradiction → anonyme, persistance track) ; voix substitut (enroll+match) ; enrollment vocal (regex → galeries + UIIntent) ; correction (label suspendu + `revise_memory` réellement appelé). Skip propre des cas visage si poids absents. **`pytest tests/v19 -q` = 95 passed** ; cœur `src/` inchangé ; V18 non touchée.

## 2026-07-05 — E33 IntentRouter vocal + actions device + mode payant + menu UI (ADR)

Constat : après le wake word, seuls des cas codés (où-est/what_is/ocr) ; pas de multi-tour ; pas de lancement d'apps ; `llm: openai/gemini` = config sans client ; le geste balayage Kotlin `SwipeHide` était émis mais sans handler Unity. E33 fait du wake-word→action une interface complète — la voix ET le menu — en **branchant l'existant** (handlers vision, broker/densité, gestes déjà émis, routeur Brain2 riche du cœur) derrière une seule voie d'exécution.

**Grammaire d'abord, LLM en repli (jamais l'inverse).** Le routeur (`intent_router.py`) résout un transcript final dans cet ordre : (1) **identité** (le pré-routeur E32 `enrollment_watcher` est **absorbé** comme premier handler → « retiens : c'est X » / « ce n'est pas X » ne passent jamais par la grammaire générale, et les tests E32 restent verts) ; (2) **grammaire** regex/mots-clés FR+EN, rapide, déterministe, **offline** — le cas commun ne dépend pas du LLM ; (3) **multi-tour** : un contexte court-TTL (25 s) de la dernière commande/cible (`track_id`/`bbox`) résout la deixis (« zoom dessus », « traduis-le », « et ça ? ») sur la dernière cible — un « zoom » nu après un « c'est quoi ça » garde le référent ; (4) **repli LLM** : parse JSON strict via le LLM live pour le reste, sinon UIIntent honnête « je n'ai pas compris : … ». Le routeur **ne duplique aucune logique métier** : il décide *quel* handler et *avec quels paramètres*, puis délègue à `vision_focus`/`on_device_command`/`ask_memory`/`llm_router.switch_*` — tous préexistants. Alternative écartée : LLM-first « il comprend tout » — rejeté (latence + coût + non-déterminisme sur des ordres simples ; la grammaire couvre le cas commun à coût nul et hors-ligne).

**Mémoire = le routeur Brain2 riche du cœur, pas `/query`.** `memory_query.py` appelle `brain2_router_v14_2.ask_brain2(question, person_id=…)` — **exactement comme le CLI `v14-ask`** (route naturelle → candidats SQL → recherche vectorielle → fusion/ranking → réponse LLM), au lieu du `/query` simple d'`api.py` (ajout inventaire cœur du backlog). Brain2 a besoin du LLM (son étape réponse est un appel JSON) : Ollama éteint → chemin dégradé **honnête** en deux temps — repli `retrieval.search` (hits vectoriels, **sans LLM**) si utilisable (`truth_level=inferred`, « souvenirs les plus proches »), sinon « mémoire profonde indisponible ». Réponse en ContextCard, `truth_level=remembered` pour une vraie réponse Brain2 (+ evidence refs extraits du packet), `inferred` pour le repli.

**Providers réels derrière une interface, cloud strictement opt-in.** `llm_providers.py` : `LLMProvider.complete_json(system,user,schema_hint)` → JSON strict ou `LLMUnavailable` (jamais de stub silencieux). `OllamaProvider` réutilise `OllamaJsonClient` du cœur (un seul contrat JSON), sinon `/api/generate` brut. `OpenAIProvider` (POST `/chat/completions`, `response_format={type:json_object}`) et `GeminiProvider` (POST `…/models/<m>:generateContent`, `responseMimeType=application/json`) sont **réels** (HTTP direct via `requests` si présent sinon `urllib`, clé par env `OPENAI_API_KEY`/`GEMINI_API_KEY` ou profil). **Endpoints/modèles/coûts configurables** dans `configs/cloud_llm.yaml` — choix : endpoints **stables et durables** (vérifiés web 2026-07), modèles par défaut récents **et surchargeables** sans changer le code : OpenAI `gpt-5.4-mini` (~0,01–0,03 €/q), Gemini `gemini-2.5-flash` (~0,005–0,02 €/q). `LLMRouter` démarre **toujours en local** ; « mode payant [openai|gemini] » n'active le cloud qu'avec une clé présente **et** une politique permissive : `cloud_data_policy=local_only` → **refus poli** (jamais de bascule sous local_only, jamais de cloud par défaut) ; la réponse de bascule porte la **fourchette de coût** (« mode payant activé (openai) — ~0,01–0,03 €/question ») et émet un event `cloud_mode`/`cloud_active` → StatusBar device. Alternative écartée : SDK officiels `openai`/`google-generativeai` — rejeté pour garder zéro nouvelle dépendance lourde et un contrôle direct du contrat JSON (les endpoints REST sont stables).

**Une seule voie d'exécution voix↔menu.** Les commandes device transitent par le **même DataChannel** que les UIIntents, en messages `device_command` (`set_ui_mode{hide_all,minimal,normal,freeguy}`, `open_app{maps,youtube,package}`, `privacy_pause`, `open_menu`, `replay`). Côté Unity, `LiveTransportBridge` réclame ces messages **avant** le parsing UIIntent (un `device_command` n'est pas un UIIntent) et les route à `DeviceCommandHandler` : toggles → `UIIntentBroker.SetDensity` (les **modes de densité nommés** sont ajoutés au broker — `hide_all` ne garde que le StatusBar standalone + la rung privacy §13.2-1, `minimal` garde les rungs 1-4, `freeguy`/`normal` tout ; refus à l'admission ET drop des intents actifs au passage en mode restreint) ; `privacy_pause` → StatusBar ; `open_app` → `AppLauncherBridge` → Kotlin `AppLauncher` (Intents **réels** : `google.navigation:`/`geo:` avec repli maps générique, `vnd.youtube:` avec repli ACTION_VIEW web, `getLaunchIntentForPackage`). Le **menu UI** (`MenuPanel`) est ouvert par le geste paume (déjà émis par `GestureBridge` — **câblé** par `MenuGestureController`) ou la voix « menu » ; chaque sélection (gaze+dwell OU pincement E26) construit un `DeviceCommand` et le passe au **même `DeviceCommandHandler.Execute`** que la voix — UNE voie d'exécution, jamais deux — puis émet un UIReceipt `acted`. Le **balayage→cacher** (gap connu : `SwipeHide` Kotlin existait, handler Unity manquant) est câblé dans `MenuGestureController` en routant le `hide_all` par la même voie que « cache tout ». Placement des fichiers : `DeviceCommandHandler`/`MenuPanel` dans l'assembly **UI** (référence Transport/Scene/Contracts — un lien Transport→UI serait un cycle) ; `AppLauncherBridge` dans **Transport** (JNI pur, sans dep UI) ; `MenuGestureController` dans **Reflex** (référence déjà UI + voit `GestureBridge`).

Livrables : `services/live-pc/intent_router.py`, `memory_query.py`, `llm_providers.py`, `configs/cloud_llm.yaml` ; câblage `live_pipeline.py` (`enable_intents`, `vision_focus_handler`, `_push_device_command`, métriques `intents_routed`/`intent_unknown`/`grammar_hits`/`multiturn_hits`/`llm_fallbacks`/`cloud_mode`/`cloud_active`) ; Unity `Assets/Scripts/UI/DeviceCommandHandler.cs`, `UI/Components/MenuPanel.cs`, densité `UIIntentBroker`, registre MenuPanel, `Transport/AppLauncherBridge.cs`, `Transport/LiveTransportBridge.cs` (event `MessageReceived` + claim device_command), `Reflex/MenuGestureController.cs` ; Kotlin `reflexvision/AppLauncher.kt`. Tests PC `tests/v19/test_e33_intents.py` (30) : grammaire ≥15 FR/EN ; multi-tour ; toggles/open_app → device_command ; ask_memory → `ask_brain2` appelé (frontière LLM mockée) → ContextCard + evidence ; dégradé honnête ; mode payant refusé sous `local_only`, appelé (HTTP mocké) + coût + event sous politique permissive, provider réel si clé env (skip sinon) ; enrollment absorbé. Tests EditMode `E33MenuDeviceTests` (menu grille+sélection→command+receipt ; `hide_all`→StatusBar seul ; set_ui_mode→densité ; swipe→hide câblé ; palm→toggle ; registre). **`pytest tests/v19 -q` = 125 passed, 1 skipped** ; cœur `src/` inchangé ; V18 non touchée. Réserves Unity habituelles (compilation/exécution EditMode à la première ouverture Unity ; compilation Kotlin + validation S25 différées matériel).

## 2026-07-05 — E34 Proactivité réelle & hot context device (ADR)

Constat : les moteurs nocturnes (prédictions du jour, interventions proactives, questions de clarification, récupération prédictive dense, discours fin) tournaient la nuit mais n'atteignaient jamais le live ; le `entities_hot` du device ne recevait que la vision ; seulement 3 situations proactives (§12.4). E34 **branche l'existant en live** — aucune modification de `src/` (appels uniquement).

**Langage naturel d'abord dans le routeur (inversion E33 demandée).** `intent_router.py` inverse la priorité : (a) **raccourci grammaire haute-confiance UNIQUEMENT** quand l'ordre *commence* par un mot-clé de contrôle exact (« menu », « cache tout », « zoom », « mode payant », « mode local »… — `pat.match`, pas `search`, après un lead-in de politesse optionnel) → instantané, hors-ligne, jamais de LLM ; (b) **tout le reste → parse LLM live d'abord** (catalogue d'intentions + exemples FR de phrases naturelles dans le prompt système, JSON strict via `LLMProvider`) : « tu peux me montrer ce que j'ai fait vers 14h ? » → `{intent:replay,time:14h}` ; (c) **grammaire lenient en FILET** seulement quand le LLM est indisponible (offline / non configuré) — la couverture E33 complète reste jouable sans modèle ; (d) la deixis multi-tour reste prioritaire quand l'énoncé est clairement un suivi. Choix : l'utilisateur parle naturellement, la nuance vit dans le LLM ; les ordres instrumentaux exacts restent à coût nul. Compat E33 : les commandes des tests E33 commencent toutes par leur mot-clé (haute-confiance) ou tombent dans le filet quand `llm=None` → **tests E33 inchangés, verts**.

**Prédictions↔scène par les MÊMES specs que l'outcome watcher.** `proactive_context.py` charge en live, au démarrage de session et périodiquement : les prédictions OUVERTES du jour (`predictions_v19`, `status='open'`, horizon du jour, avec leur `verification_spec`), les interventions nocturnes en attente (`proactive_interventions_v14_7.list_intervention_inbox` → `v14_7_intervention_queue` statuts `ready/pending/snoozed`), les questions de clarification en attente (`clarification_inbox_v14_8.list_clarifications` statut `queued`). Le matching prédiction↔scène réutilise **le prédicat même de l'outcome watcher** `v19_outcome_watcher._event_matches(event, spec)` : on fabrique un « event » `visual_events_v19`-shaped depuis le HotSceneContext courant (labels d'entités visibles + noms identifiés + transcript + place) et une prédiction ne tire en live que si elle serait vérifiée par ce qui est à l'écran / dit — cohérence stricte nuit↔live, zéro heuristique parallèle. Trois nouvelles situations proactives dans `brainlive_scene_adapter.evaluate_situations` : (a) prédiction du jour matchée (« tu voulais racheter X ») ; (b) intervention nocturne pertinente au contexte (match lexical léger sujet↔scène) → delivery ; (c) question de clarification posée **au bon moment** — seulement en contexte CALME (`due_clarification(conversation_active=False)`) : jamais pendant une conversation active (§2c), la réponse vocale repart par le chemin conversation existant (ConversationBridge → inbox nocturne). Tout passe par le **même `enqueue_delivery`** (dédup/cooldown par `source_key` scène+sujet). Anti-spam : dédup naturelle d'`enqueue_delivery` + `source_key` idempotent par item.

**Récupération dense en live, dégradé propre.** `predictive_retrieval_live.py` enveloppe `get_predictive_backend().retrieve(...)` : le moteur cœur attend un *observed case* comme ancre + un map de candidats — en live on n'a qu'un sujet (topic de conversation + entités en scène), donc on fabrique une **ancre live** (`embedding_text` = sujet) et on charge les `brain2_observed_cases_v17` de la personne comme `canonical_candidates`, puis on appelle le **vrai** `retrieve`. Résultat → section « expériences similaires » foldée dans le HotSceneContext (budget respecté, sinon `omissions`) que le LLM de la policy exploite. Qdrant éteint / reranker absent / table froide → `[]` + un WARN, **jamais de crash** (dégradé honnête).

**Discours fin en live, hors du chemin d'ingestion.** `live_discourse.py` : les tours finaux sont bufferisés (O(1), non-bloquant) puis, sur cadence (`min_turns` accumulés OU `min_interval_s`), un **worker daemon** flushe le batch par le point d'entrée officiel du cœur `ingest.ingest_transcript` — celui du batch import — qui fait tourner `ConversationMicroscope` (actes de parole / expressions / idées) + `ConversationDiscourse` (fils de sujets) et écrit dans les **tables cœur existantes** (`expression_signals`/`ideas`/`atomic_memories`/…). **Brancher, pas reconstruire** : aucune table nouvelle, aucune persistance réimplémentée. File bornée : si le worker prend du retard, les flushes les plus anciens sont *droppés* (WARN) — l'ingestion des tours ne peut jamais être back-pressurée par l'analyseur.

**Prefetch relation pack → device.** Quand `identity_fusion` (E32) nomme une personne, `_apply_identity` appelle `scene_adapter.prefetch_relation_pack` → un message `entity_hot_update` (person_id, name, relation pack compact : derniers sujets/promesses lus depuis `build_active_context().brain2_context.active_relationship_packs` — les tables relationnelles du cœur) est poussé par le **même DataChannel** (`_push_intent`). Côté Unity, `SceneCache.SubmitEntityHotUpdate` folde le pack dans `entities_hot` (store parallèle additif + rafraîchit le nom) ; `EntityHotUpdateHandler` (assembly UI) réclame le message brut par type comme `DeviceCommandHandler`. La ContextCard s'affiche depuis le cache local, latence zéro. Émis une fois par (entité, personne) par session (dédup `_prefetched_people`). `EntityHotUpdate` est un message **live-only** (pas un contrat de schéma généré) → placé dans l'assembly Scene, pas dans la copie Contracts auto-générée.

**Briefing du matin.** `morning_briefing.py` : « première session du jour » détectée sur la **vraie** table `brainlive_sessions` (aucune session antérieure aujourd'hui pour la personne, la session courante exclue par `live_session_id`) → UNE ContextCard « Bonjour — aujourd'hui : … » (prédictions courtes, interventions en attente, questions de clarification, top last-seen utiles téléphone/clés depuis le WorldBrain) via `enqueue_delivery` `source_key=briefing:<date>` → **dédup naturelle** (2e session le même jour → skip). Détection prudente : DB froide / indéterminable → pas de briefing (jamais de spam).

Câblage `live_pipeline.py` : `enable_proactivity` construit `ProactiveContext` + `PredictiveRetrievalLive` + `MorningBriefing`, câble le scene adapter (`proactive`, `predictive_retrieval`, `on_entity_hot_update=_push_intent`), refresh au démarrage ; `LiveDiscourse` sur les tours finaux si `enable_conversation` ; `deliver_morning_briefing()` à l'ouverture ; `end_session` ferme le discours. Métriques `proactive_predictions`/`proactive_interventions`/`clarifications_asked`/`similar_experiences`/`entity_hot_updates`/`discourse_turns`/`discourse_flushes`/`briefings_enqueued` sur `/metrics`.

Livrables : `services/live-pc/proactive_context.py`, `predictive_retrieval_live.py`, `live_discourse.py`, `morning_briefing.py` ; extensions `brainlive_scene_adapter.py` (proactive/similar folds + 3 situations + prefetch), `identity_fusion.py` (déclenche le prefetch), `intent_router.py` (NL-first), `live_pipeline.py` (câblage/métriques) ; Unity `Assets/Scripts/Scene/EntityHotUpdate.cs`, `Scene/SceneCache.cs` (SubmitEntityHotUpdate + relation pack), `UI/EntityHotUpdateHandler.cs`. Tests PC `tests/v19/test_e34_proactivity.py` (10) : prédiction ouverte en base + scène qui matche → suggestion en queue avec evidence (et non-match → rien) ; clarification en attente + contexte calme → délivrée / conversation active → supprimée ; retrieval dense mocké à la frontière Qdrant → section similaires présente / Qdrant éteint → dégradé propre ; briefing première session → carte unique / 2e session → dédupliquée ; `entity_hot_update` émis à l'identification (idempotent) ; routeur NL-first : phrase naturelle → parse LLM (frontière mockée) → bon intent / grammaire haute-confiance toujours instantanée sans LLM / LLM éteint → filet lenient. **INTERDITS respectés** : cœur `src/` inchangé (appels uniquement) ; anti-spam (dédup/cooldown `enqueue_delivery` + `source_key` idempotents) ; ingestion des tours jamais bloquée (discours en worker borné) ; E31-E33 verts. **`pytest tests/v19 -q` = 135 passed, 1 skipped**. Réserves Unity habituelles : compilation/exécution EditMode à la première ouverture Unity (`EntityHotUpdateHandler` / `SceneCache.SubmitEntityHotUpdate` différés matériel).

## 2026-07-05 — E35 Sorties : voix, correction, replay + hot context généralisé (ADR)

Constat : le live parlait aux yeux (cartes/contours) mais pas à voix haute ; « rejoue 14h30 » était routé (E33) sans service qui assemble le replay ; la correction vocale ne couvrait que l'identité (personne) ; le `entity_hot` du device n'avait été câblé que pour les personnes en E34 (le plan §9.1 prévoyait le mécanisme pour toutes les entités + spatial_hot + task_hot). E35 **branche l'existant en live** — cœur `src/` inchangé (appels uniquement), audio/vidéo jamais non-bornés sur le DataChannel.

**TTS local derrière une interface, sherpa d'abord, repli SAPI.** `tts_local.py` : `TTSProvider.speak(text, lang) -> WAV bytes`. `SherpaTTS` (sherpa-onnx `OfflineTts`, config VITS/Piper) est le chemin primaire — sherpa-onnx **s'installe** dans cet env (`pip sherpa-onnx`, 1.13.3) ; les voix Piper/VITS **FR** (`fr_FR-siwis-medium`) et **EN** (`en_US-amy-low`) sont référencées `archive`+`archive_sha256`+`license: MIT` dans `configs/MODEL_MANIFEST.yaml` (**non committées** ; `fetch_models_v19.py --tts` télécharge+vérifie+extrait le `.tar.bz2`, sha256 épinglé au premier fetch). Deux sources web consultées pour choisir les voix (ADR) : (1) la liste TTS du zoo **sherpa-onnx** (k2-fsa) — index canonique de voix offline vérifiées, chaque voix avec une archive directe ; (2) le catalogue **Piper voices** (rhasspy) — qualité + licence par voix. Repli quand les modèles sherpa sont absents / le paquet inutilisable, derrière la MÊME interface : `Pyttsx3TTS` (si installé) sinon `WindowsSapiTTS` (SAPI direct via `win32com` → `SpVoice`→`SpFileStream` WAV — **réel**, testé ici : WAV 22 kHz mono 16-bit non vide). `build_tts_provider` choisit sherpa si une voix est sur disque, sinon le repli — jamais d'exception, l'indisponibilité se révèle au `speak` (dégradé honnête). Le WAV part en message `tts_audio` **base64 borné** (`tts_audio_message`, cap `max_b64_chars` → réponse trop longue renvoie `None`, la carte texte porte déjà le texte) sur le même DataChannel ; le viewer web décode le blob et le joue (companion/phone). Déclenchement : `pipeline.speak_reply` sur les réponses courtes quand le profil `tts: on` (**nouveau champ, défaut off**) ou un `force` ; toggle voix/silence par intent `set_tts` (grammaire « réponds à voix haute »/« silence » + repli device_command menu) → `pipeline.set_tts` (toggle **local**, aussi forwardé pour la StatusBar). Alternative écartée : streamer l'audio brut sur le DataChannel — **interdit** (borné base64 uniquement).

**Replay = plage horaire visuelle depuis les tables réelles, PAS `v18_replay`.** `replay_service.py` : `ReplayService.replay(time)` parse l'heure parlée (« 14h30 »/« 14h »/« 14:30 » → fenêtre [t, t+15 min]) et assemble depuis les tables du cœur — keyframes `vision_frames` (`image_path`), clips `visual_evidence_assets_v19` (kind clip/video, `uri`), events `visual_events_v19`, transcript `turns` (temps absolu reconstruit `conversations.started_at + turns.start_s`, car `turns` stocke un offset, pas un timestamp) → `replay_bundle`. Livraison **deux voies, bornées** : (1) UIIntent `virtual_screen` dont le contenu est la **séquence de refs** images/clips (chemins/URIs + base URL locale servie par le HTTP existant) — le `VirtualScreen` Unity charge une texture par ref ; **jamais d'octets bruts** sur le DataChannel (interdit) ; le viewer web séquence les mêmes refs en diaporama `<img>` ; (2) une **timeline ContextCard** (compteurs + quelques lignes d'events). ADR — pourquoi PAS `v18_replay.replay_offline` : ce primitif est **conversation-scopé** (exige un `conversation_id`), turn-only, et fait tourner la chaîne lourde de gouvernance/manifest pour un replay de *raisonnement* historique isolé. E35 replay est *plage horaire visuelle* : keyframes+clips+events+transcript par fenêtre d'horloge, pour affichage sur lunettes. Entrées différentes (heure vs conversation), sortie différente (séquence d'images vs manifest de contexte) — on lit les vraies tables directement ; `v18_replay` reste pour le chemin offline qu'il sert. Le router `replay` dispatche vers le service quand câblé, sinon la voie device_command (l'UI replay du téléphone).

**Correction vocale objet/lieu, label suspendu durablement.** `worldbrain.suspend_label(label)` : chaque entité portant ce label est retirée maintenant, filtrée de **tout snapshot/SceneDelta suivant**, et **jamais re-promue** (garde dans la boucle d'ingestion : une observation d'un label suspendu est ignorée) — le mauvais label reste hors du monde pour la session. `worldbrain.suspend_zone(zone)` efface la zone de `place_hint`/`active_zone`. `enrollment_watcher` gagne `parse_scene_correction` (« ce n'est pas mon téléphone » → objet, « on n'est pas au bureau »/« ce n'est pas la cuisine » → lieu) **après** la correction de personne ; les déterminants/possessifs (mon/ma/le/la/un/au…) sont ajoutés aux `_STOP_NAMES` pour que « ce n'est pas mon téléphone » ne soit **pas** lu comme la personne « Mon » — « ce n'est pas Paul » reste identité (E32). Chaque correction trace `memory_correction.revise_memory` (invalidate, réutilisé jamais réimplémenté) quand une cible mémoire existe + confirme par carte. Le watcher est aussi construit **sans identité** (worldbrain seul) pour que la correction objet/lieu marche même sans reco faciale.

**Hot context généralisé — les 4 types (demande utilisateur, §9.1).** `brainlive_scene_adapter` étend le mécanisme `hot_update` (E34 n'avait câblé que les personnes) : (a) `push_spatial_hot` — zone de session reconnue → `spatial_hot_update` (zone, map_quality mesurée, last-seens utiles, + **routine du jour du lieu** depuis `brain2_spatial_routine_models` matchée par égalité/inclusion de place → « ici, d'habitude tu… ») → `SceneCache.spatial_hot` ; (b) `push_object_hot` — objet durable promu/retrouvé → `entity_hot_update` **kind=object** (last_seen, relations de frame) ; (c) `push_task_hot` — TaskCard/situation qui démarre (via `set_active_task`) → `task_hot_update` (but, étape, outils) → `SceneCache.task_hot` ; (d) routine incluse dans le pack du lieu (voir a). Cadence économe : **dédup par sujet/session** (`_pushed_zones`/`_pushed_objects`/`_pushed_tasks`), budget par message (`_emit_hot` refuse un message hors budget — jamais de push non borné). Côté Unity : `EntityHotUpdate.cs` gagne les messages `SpatialHotUpdate`/`TaskHotUpdate` + un champ `kind` ; `SceneCache` gagne `SubmitSpatialHotUpdate` (zone pack + routines dans `SpatialHotSubCache`, age-out) et `SubmitTaskHotUpdate` (slot task unique) + `EntitiesHotSubCache.ApplyHotUpdate` **object-aware** (Label/kind=object vs Name/person) — **additif, E34 intact** ; `EntityHotUpdateHandler` réclame les 3 nouveaux types par leur `type` comme `DeviceCommandHandler`.

Câblage `live_pipeline.py` : `enable_tts` construit le provider + `speak_reply` + toggle `set_tts` ; `enable_replay` construit `ReplayService` (câblé au router) ; le `enrollment_watcher` reçoit `worldbrain` (correction objet/lieu, même sans identité) ; le scene adapter émet les hot généralisés dans `evaluate_situations`/`set_active_task`. `app.js` joue les blobs `tts_audio` + rend le diaporama replay.

Livrables : `services/live-pc/tts_local.py`, `replay_service.py` ; extensions `intent_router.py` (replay→service, `set_tts`), `enrollment_watcher.py` (scene correction), `worldbrain.py` (suspend label/zone), `brainlive_scene_adapter.py` (hot généralisé), `live_pipeline.py` (câblage) ; `configs/MODEL_MANIFEST.yaml` (voix TTS) + `scripts/fetch_models_v19.py` (`--tts`) ; Unity `Scene/EntityHotUpdate.cs`, `Scene/SceneCache.cs`, `UI/EntityHotUpdateHandler.cs` ; web `apps/companion-web/app.js`. Tests PC `tests/v19/test_e35_outputs.py` (13). **INTERDITS respectés** : cœur `src/` inchangé (appels uniquement) ; audio/vidéo bornés (base64 cappé / refs, jamais d'octets bruts) ; E31-E34 verts. **`pytest tests/v19 -q` = 148 passed, 1 skipped**. Réserves Unity habituelles : EditMode (`SubmitSpatialHotUpdate`/`SubmitTaskHotUpdate`, `EntityHotUpdateHandler` généralisé) exécuté à la première ouverture Unity, différé matériel ; voix TTS téléchargées par `fetch_models_v19.py --tts` (sha256 épinglé au premier fetch).

## 2026-07-05 — E36 Ops de prod : accès hors-maison + quotas + profil d'inconnu VLM (ADR)

Constat / priorité utilisateur (2026-07-05) : l'usage principal est **DEHORS** (téléphone en 4G/5G, PC à la maison derrière NAT). L'accès hors-maison devient **LE** livrable. Le **backup chiffré est DIFFÉRÉ** (décision utilisateur — usage perso géré à la main ; noté dans PROD_BACKLOG, non implémenté). E36 **branche l'existant** — cœur `src/` inchangé (appels uniquement), pas de TURN/relais par défaut (local-first).

**Failover multi-endpoints, LAN d'abord, retour LAN au retour maison.** Un `endpoint_resolver.py` partagé prend une LISTE ORDONNÉE d'endpoints (`{name,host,port}`, LAN en premier puis tunnel type Tailscale `100.x`) et sonde `GET /health` **dans l'ordre** ; le premier qui répond `ok` devient l'`active_endpoint`. Choix : `resolve()` re-sonde **toujours depuis le haut** de la liste → dès que le LAN répond de nouveau (retour maison) il est repris automatiquement (return-LAN), et une bascule d'un endpoint vers un autre compte comme un *failover* (métrique). Aucun endpoint joignable → verdict **`pc_unreachable`** propre (jamais d'exception) : les chemins réflexes du device (Ultra-Live) ne dépendent pas du PC et continuent. Le resolver prend un `probe` injectable (défaut : petit `urllib GET /health`) → testable contre deux SessionHubs localhost sur des ports différents (LAN up → LAN ; port LAN fermé → bascule ; deux down → `pc_unreachable` ; premier revenu → retour). Câblé côté Python (`fake_xr_device --endpoints`, `pipeline.resolve_endpoints` qui fixe `active_endpoint`+`active_link`), Unity (`MLOmegaConfig` liste `Endpoints` **additive** — vide → l'ancien `PcHost` unique, rétrocompatible ; `SessionPairing.ResolveActiveEndpoint` sonde `/health` et (re)construit le `SessionHubClient` sur l'endpoint actif, re-résolution avant chaque tentative de create), Kotlin (`SignalingClient` : constructeur liste + `resolveEndpoint()` + `exchangeOffer` qui bascule sur le prochain endpoint si l'offer échoue), companion-web (`?endpoints=host,…` sonde `/health` → URL WebSocket).

**WebRTC à travers le tunnel sans TURN.** En VPN Tailscale/WireGuard, l'IP `100.x` du PC est **routable pour le téléphone** → aiortc/GetStream la présente comme un **host candidate** ICE ordinaire, donc le média passe **directement dans le tunnel, sans serveur TURN ni relais externe** (politique local-first, aucun relais tiers par défaut). Prérequis assurés : le SessionHub écoute sur **toutes les interfaces** (`0.0.0.0` par défaut ; option `bind_host` lue depuis le profil dans `sessionhub_http.main`) et le **token de session** reste la barrière (déjà en place — 401 sans token). Documenté dans `OUTSIDE_ACCESS.md`.

**Dégradation WAN : profils réseau lan/wan distincts.** `degraded.py` gagne `NetworkProfile` (par lien) + `default_network_profiles()` : le profil **WAN** relève le plafond de latence (400 ms vs 250 ms LAN — la RTT 4G/5G ne fait plus clignoter `network_degraded`) et **abaisse la résolution vidéo cible** (720p LAN → 540p WAN) pour ne pas saturer le tunnel ; `thresholds_for_link()` fabrique des `DegradedThresholds` dont **seules les limites réseau** suivent le lien — les seuils GPU/heartbeat restent la base (locaux, indépendants du lien). Choix explicite : **les cadences détecteur côté PC ne changent JAMAIS avec le lien** (elles tournent en local, pas sur le réseau) et les **chemins réflexes device ne dépendent pas du PC** (rappelé dans la doc). `network_profiles_from_config` fusionne un bloc `degraded.network` du profil rtx3070. Métriques `active_endpoint`/`active_link`/`target_video_height` sur `/metrics`.

**Profil temporaire d'inconnu via VLM (name-less, fusionnable).** `stranger_profile.py` : un `StrangerProfiler` chronomètre chaque person track **anonyme** (non nommé par `IdentityFusion`) et visible ; passé `stable_seconds` (config) et avec un crop dispo, il prend **UN** crop et appelle le **même** `VlmCrop.describe` un-job-à-la-fois (chemin VisionRT existant, dégradé honnête si Ollama off / GPU sous pression → aucune description inventée). La réponse (JSON `{appearance, clothing, age_apparent, role_hint}` — le prompt interdit tout nom personnel) est parsée en une **description** ; `description_label` fabrique un label hypothèse « ? boulanger » (préfixe `? ` = c'est une hypothèse, §17.2). Choix : l'entité person WorldBrain reçoit `description`/`description_attributes`/`description_truth_level=inferred` (**jamais** `person_name`), et un `entity_hot_update` (kind=person, `name:None`, `truth_level:inferred`) part vers le device → PersonTag « ? boulanger » stylée hypothèse. **Dédup strict : au plus 1 profil VLM par track par session** (`_profiled_tracks` marqué à l'entrée, avant l'appel VLM → un VLM busy/refusé ne re-tire pas frame après frame). **Fusion** (`fuse_into_named`) : si l'utilisateur enrôle ensuite (« retiens, c'est Karim »), le profil provisoire se **fond** dans l'entité nommée — `person_id`/`person_name` posés, **description conservée en attribut** (`truth_level` passe à `observed`), et un dernier `entity_hot_update` nommé **supersede** l'hypothèse « ? ». Câblé dans `live_pipeline` : `_run_stranger_profiles` après l'identité (un track fraîchement nommé est sauté) ; `_maybe_fuse_stranger` détecte l'enrollment dans le transcript et fusionne sur le track actif du watcher. Métriques `stranger_profiles`/`stranger_vlm_unavailable`/`stranger_fused` sur `/metrics`.

**Quotas stockage au doctor.** `DOCTOR_MLOMEGA_V19.ps1 -Quota` (inclus dans `-Full`) mesure les **tailles réelles** : DB SQLite (`MLOMEGA_DB`), `models/`, evidence keyframes+clips (`MLOMEGA_EVIDENCE`/`MLOMEGA_RAW`), **tampon-jour** (`day_buffer`) ; seuils WARN/FAIL **configurables** (profil `storage_quota` : `warn_gb`/`fail_gb`/`day_buffer_warn_gb`/`day_buffer_fail_gb`) avec **suggestion de purge** au dépassement. Le tampon-jour est déjà purgé par le close-day (`EvidenceStore.purge_day_buffer`) — le doctor le **référence** et flague quand il grossit pour que l'opérateur lance un close-day. WARN ne fait jamais échouer le run (parité avec le reste du doctor).

Livrables : `services/live-pc/endpoint_resolver.py`, `stranger_profile.py` ; extensions `degraded.py` (profils réseau lan/wan), `live_pipeline.py` (resolve/active_link/stranger/fusion/métriques), `sessionhub_http.py` (bind_host), `simulators/fake_xr_device.py` (`--endpoints`) ; Unity `MLOmegaConfig.cs` (liste `Endpoints` + `PcEndpoint`), `SessionPairing.cs` (résolution+failover) ; Kotlin `SignalingClient.kt` (liste+failover) ; web `apps/companion-web/app.js` (`?endpoints`) ; `scripts/DOCTOR_MLOMEGA_V19.ps1` (`-Quota`) ; `configs/user_profile.yaml` (exemples endpoints/bind_host/storage_quota) ; `docs/OUTSIDE_ACCESS.md`. Tests PC `tests/v19/test_e36_ops.py` (15). **INTERDITS respectés** : cœur `src/` inchangé (appels uniquement) ; nom de personne jamais inventé (description ≠ nom, toujours `inferred`) ; pas de TURN/relais par défaut (local-first) ; backup non implémenté (différé) ; E31-E35 verts. **`pytest tests/v19 -q` = 163 passed, 1 skipped**. Réserves Unity habituelles (compilation/EditMode `SessionPairing`/`MLOmegaConfig`, Kotlin `SignalingClient` différés matériel). **Validation 4G réelle à faire par l'utilisateur** avec la checklist `OUTSIDE_ACCESS.md`.

## 2026-07-05 — E38 Intelligence fine : hypothèses d'identité + attributs bi-modaux + routine→objet appris (ADR)

Règle d'or (exigence utilisateur) : **AUCUN exemple codé en dur**. Aucun lexique/regex de prénoms, aucun pattern « prix », aucune paire objet/routine en dur. Les mécanismes sont 100 % génériques ; les exemples ne vivent que dans les tests, qui utilisent des noms/valeurs/clés arbitraires et variés pour prouver la généricité. Cœur `src/` **inchangé** (lecture + appels uniquement).

**(§1) Auto-confirmation d'hypothèses d'identité (`hypothesis_engine.py`).** Signal prénom-adressé = **extraction LLM générique** sur les tours finaux (JSON strict `{addressed, name, addressee, confidence}` — le modèle lit le langage naturel, PAS de lexique de noms) ; la frontière LLM est **un unique callable injectable** (mocké en test au format réel). **Heuristique d'association nom→personne (documentée)** : « tu … , <nom> » s'adresse à qui on parle — d'ordinaire la personne qui vient de parler (locuteur précédent), avec priorité au hint d'addressee du LLM (previous/current speaker), repli sur le locuteur précédent, puis (si une seule personne présente) sur elle ; scène ambiguë (plusieurs présents, aucun signal de locuteur) → observation **abandonnée**, jamais de binding inventé. **Store multi-sessions** (SQLite service-local, jamais une table du cœur) : par hypothèse `{hypothesis_id, entity_id, attr_type (name|role|attribut libre), value, occurrences[{session, source: heard|vlm|context, confidence, evidence_ref, concordant}]}` — chaque observation concordante renforce, une valeur concurrente ou une correction **affaiblit** (pénalité configurable). **Seuils de promotion** (config) : `min_occurrences` observations concordantes ET `min_sessions` sessions distinctes (accumulation multi-sessions) ET `min_cumulative_confidence` cumulée → promotion `hypothesis→promoted` : l'attribut est écrit sur l'entité WorldBrain (`hypothesis_attributes[attr]` en `observed` ; un NAME promu devient `person_name`) et — **JAMAIS silencieusement** — un UIIntent discret annonce « J'ai déduit : c'est probablement <valeur> — corrige-moi si faux » (correctable, trace des evidence). En dessous du seuil : reste hypothèse affichée (§17.2). La **correction vocale E32** (« non, ce n'est pas X ») casse les hypothèses de l'entité (une promue devient `broken` + entité dé-nommée). L'enrollment manuel (fuse E32) reste le raccourci et prime. **Pont clarification_inbox** : l'engine LIT les hypothèses `v14_5_people_identity_hypotheses`/UNKNOWN_VOICE du cœur (via `list_clarifications`, reader injectable) ; quand un nom promu correspond à un item en attente, il **enregistre une résolution machine côté service** (table `hypothesis_engine_resolutions` + evidence). **Choix (ne modifie PAS le cœur)** : le `answer_clarification` du cœur interprète par LLM une **réponse parlée** de l'utilisateur et écrit `v14_8_clarification_answers`/`model_revisions` ; y injecter une résolution machine fabriquerait une fausse énonciation utilisateur. On documente donc la résolution côté service avec sa provenance `machine_convergence`, sans toucher au cœur — réversible et honnête.

**(§2) Changements d'attributs bi-modaux (`attribute_memory.py` + extension `worldbrain.py`).** Store générique d'**observations d'attributs** `(subject: entité|personne|lieu/zone, attribute: clé libre, value: valeur libre, source: ocr|vlm|heard, session, ts, evidence_ref)` — aucune clé de domaine. Alimenté par : **OCR ROI** (rattaché au lieu/zone courant ; un `clé: valeur` se scinde génériquement, un texte non-labellisé est stocké sous une clé de région stable — pas de pattern « prix »), **descriptions VLM** (attributs structurés déjà retournés par stranger_profile/what_is), **faits entendus** (extraction LLM générique `{states_fact, subject_hint, attribute, value, confidence}` — le modèle lit le NL, PAS de pattern « prix » ; `subject_resolver` mappe le hint libre vers une clé stable, repli sur le lieu courant). **Comparaison inter-sessions** : même `(subject, attribute)`, valeur différente d'une **autre session** → `WorldBrain.record_attribute_change` émet un nouveau `ChangeEvent` **`attribute_changed`** portant `before/after` **avec la source des deux côtés** (un VU peut contredire un ENTENDU et inversement — c'est le croisement bi-modal voulu) → persisté dans `visual_events_v19` (`truth_level=observed` si deux modalités distinctes, sinon `probable`) ; le scene_adapter peut le remonter proactivement. **Apparence des personnes connues** : à chaque rencontre, le descripteur VLM léger est stocké comme observations d'attributs de l'entité personne → diff inter-sessions = `attribute_changed` via **le même mécanisme** (pas de chemin spécial personnes).

**(§3) Routine→objet APPRIS (`routine_associations.py`).** Co-occurrences **apprises depuis les données** : pour chaque routine (`brain2_spatial_routine_models` : entity_key/place_key/time_slot) on compte les objets vus dans le même lieu depuis le flux `visual_events_v19` (events `entity_last_seen`). **Scoring** = `cooccurrence / total_sightings(objet)` (un objet fréquent partout marque moins qu'un objet spécifique au lieu) ; seuils `min_cooccurrence`/`min_score` configurables. En live : l'approche d'une zone/entité dont un objet associé dépasse `min_score` → **push proactif du last-seen** de l'objet (réutilise `push_object_hot` E35) + suggestion discrète (`routine_object_suggestion`) si l'objet n'est pas visible. Dédup par (lieu, objet) par session. **Aucune paire codée** — le scoring est un pur comptage sur les données stockées.

**(§4) Câblage `live_pipeline.py`** (drapeau `enable_fine_intel`, LLM injectable `fine_intel_llm`) : tours finaux → `hypothesis_engine.note_turn` (+ speaker/present persons résolus depuis WorldBrain) et `attribute_memory.note_turn` (faits entendus) ; OCR de `on_focus_request` → `attribute_memory.observe_ocr` ; descripteur VLM du stranger profiler → `observe_person_appearance` ; correction vocale → `break_hypotheses_for_entity` ; approche de zone dans `_on_scene_delta` → `routine_associations.on_approach`. Métriques `/metrics` : `hypotheses_active`, `auto_promotions`, `clarifications_resolved`, `attribute_changes`, `routine_pushes`.

Livrables : `services/live-pc/hypothesis_engine.py`, `attribute_memory.py`, `routine_associations.py` ; extensions `worldbrain.py` (ChangeEvent `attribute_changed` + `record_attribute_change`), `live_pipeline.py` (drapeau + câblage + métriques). Tests PC `tests/v19/test_e38_fine_intel.py` (11 : promotion 3 tours/2 sessions + annonce ; contradiction → pas de promotion ; correction → cassée ; pont clarification sans toucher le cœur ; scène ambiguë → drop ; attribut OCR→ENTENDU bi-modal ; apparence personne ; routine→objet le bon et pas un autre + dédup + pas de suggestion si visible ; valeurs arbitraires variées). **INTERDITS respectés** : cœur `src/` inchangé ; aucun lexique/regex de noms ou d'attributs ; promotion jamais silencieuse (UIIntent + trace) ; E31-E37 verts. **`pytest tests/v19 -q` = 181 passed, 1 skipped**. Réserve : les extractions LLM tournent sur le LLM local (router `mode local`) en prod — dégradation honnête (aucune hypothèse) si Ollama absent.

## 2026-07-07 — Contexte Qwen, reprise et UI PhoneOnly

`num_predict` n'est pas une fenêtre de contexte : le contexte Ollama contient prompt + sortie. Le profil retenu est 4096 tokens pour Qwen3.5:4b live et 16384 pour Qwen3.5:9b post-stop, avec sortie post-stop plafonnée à 4096. Une troncature fournisseur est un échec atomique, jamais une réponse partiellement promue.

La reprise après crash Android conserve le même `session_id` via un token chiffré Android Keystore et la grâce renew-only SessionHub. `OnDisable`, `OnDestroy` et la perte WebRTC ne suppriment pas ces credentials.

Le mode PhoneOnly est désormais aussi un renderer réel : caméra en fond, UIIntent PC, cache scène, composants UI, commandes device et receipts. Les messages bruts `scene_delta` ont leur handler propre et ne sont plus désérialisés comme UIIntent. Les interventions BrainLive passent par la queue canonique puis un DeliveryAdapter DataChannel; aucune duplication de queue n'est créée.

Les fonctions PC prévues pour l'expérience produit (`identity`, `replay`, `stranger_profiles`, `fine_intel`) sont activées explicitement dans `PhoneOnlyRuntime`. Une unique dernière frame, remplacée à chaque arrivée, sert aux questions déictiques; aucune file vidéo supplémentaire n'est créée.

ASR/traduction/gestes locaux Android restent un gate distinct : démarrer un second `AudioRecord` en parallèle du micro WebRTC sans arbitrage est interdit. Le premier build ne les activera pas implicitement tant que les modèles embarqués et le partage micro ne sont pas validés.

## 2026-07-07 — Toolchain Android reproductible et arrêt contrôlé

Décision : les plugins Android sont construits hors Unity avec JDK 17 + Gradle 8.7, puis exportés avec leurs dépendances dans `Assets/Plugins/Android`. Sherpa-onnx utilise l'AAR officiel v1.12.10 épinglé par SHA-256; JitPack n'est pas une source de build fiable pour ce composant. Le script retire les doublons de bibliothèques Kotlin/annotations pour éviter qu'Unity importe deux versions concurrentes.

Unity Editor 6000.0.23f1 est installé et vérifié. La simple présence de `AndroidPlayer` ne vaut pas validation Android : au point d'arrêt, les sous-dossiers embarqués `SDK`, `NDK` et `OpenJDK` sont absents. Aucun APK ni test matériel ne peut donc être déclaré sur cette seule installation.

Décision de reprise : avant compilation, les rapports d'audit doivent être confrontés au checkout courant et couverts par tests sur les frontières critiques, en priorité drain audio/flush, ID BrainLive unique, environnement séparé live/post-stop, renouvellement token/reconnexion Kotlin, conversion aiortc PCM et texture Unity/WebRTC. Les constats issus d'un état antérieur des fichiers ne sont pas automatiquement acceptés comme vérité.

L'arrêt demandé a interrompu le préflight Unity avant import du projet. Aucun installateur ou processus Unity ne reste actif. Le point de reprise détaillé et ordonné est enregistré dans `EXECUTOR_BUILD_GUIDE.md` section E46-D et suivi dans `PROD_BACKLOG.md`.

## 2026-07-07 (soir) — Reprise E46-D : licence Unity bloquante, toolchain complété, audit réfuté

Unity Editor 6000.0.23f1 a été installé hors Unity Hub ; par conséquent `Unity Hub --headless install-modules` refuse d'ajouter Android Build Support (`No modules found for this editor`). Décision : ne pas réinstaller l'éditeur via Hub, mais compléter le toolchain externe — NDK r23b (`23.1.7779620`, version attendue par Unity 6000.0) installé via `sdkmanager`, en plus du SDK système (android-34, build-tools, platform-tools/adb), JDK 17 et Gradle 8.7. `Editor/AndroidBuild.cs` pose SDK/NDK/JDK/Gradle dans les prefs Unity au moment du build ; aucun module Hub embarqué n'est requis.

La licence Unity a été vérifiée en batchmode : **échec bloquant** `No valid Unity Editor license found` (`No ULF license found`, 0 entitlement). L'activation Unity 6 Personal exige un login Unity ID interactif, impossible en headless. Conséquence : import Unity, tests EditMode, génération de scène et APK restent bloqués tant que l'utilisateur n'active pas une licence via Unity Hub. Tout ce qui ne dépend pas d'Unity a été mené à terme (plugins Android, triage audit, suites Python).

Triage des constats d'audit ouverts, confrontés au checkout courant : les 11 constats (conversion aiortc PCM, gel/drain + `AudioRT.flush()`, callback audio en vol, arrêt ingress/vidéo, ID BrainLive unique via `uuid4` dans `start_live_session`, CloseDay lancé dans `.venv` cœur, archive VAD indépendante de l'ASR, PersonId, renouvellement token Kotlin `updateCredentials`, ICE non-trickle/teardown/reconnect, chemin texture Unity↔WebRTC sur le GL thread) sont **tous réfutés** : le code actuel les implémente déjà correctement. Aucune correction service/apps n'était nécessaire. L'invariant interdisant `turns.created_at` tient (`v18_life_model` ordonne les turns par `start_s`, jamais `created_at`) ; couvert par `test_owner_scoped_turn_query_uses_conversation_time_not_turn_created_at`. Suites : V19 207/2 skip/0 fail, V18 ciblé 5/0 fail. Le cœur V18.8 n'a pas été modifié (pytest ajouté au `.venv` cœur uniquement comme outil de test).

## 2026-07-07 — E46-D clôture : premier passage compilateur Unity réel + APK PhoneOnly

L'utilisateur a activé une licence Unity Personal, débloquant les étapes 3→7. Import Unity + premier passage compilateur ont révélé 10 familles de fixes réels (aucun n'était anticipable sans compiler) :

- **ContractJson DateParseHandling** : les `JsonSerializerSettings` ne fixaient pas `DateParseHandling.None`, donc Json.NET parsait les timestamps ISO des contrats en `DateTime` selon la culture du runtime au lieu de les garder en chaîne — corruption silencieuse des horodatages à la ronde-trip sérialisation/désérialisation. Fix prioritaire car touche tout message contractuel horodaté.
- **ParseObject/JObject.Parse même piège** : le chemin de parsing brut appelait `JObject.Parse` sans le même garde-fou de culture, donc corrigible seulement en cohérence avec ContractJson — sinon les deux chemins auraient divergé sur les mêmes payloads.
- **Collision structs SceneCache `*Entry`** : deux structs imbriquées portaient le même nom court, provoquant CS0102 (membre dupliqué) — renommées avec suffixe `Entry` pour lever l'ambiguïté sans toucher au schéma sérialisé.
- **GlassPanel matériau par instance (UGUI)** : le composant partageait l'unique `Material` du Renderer entre toutes les instances UGUI ; changer la teinte d'un panneau retintait tous les panneaux à l'écran. Fix : matériau cloné par instance.
- **Broker Cfg lazy (EditMode/boot-order)** : le broker de configuration s'initialisait au chargement statique, avant que l'environnement EditMode (tests) ou le runtime (boot réel) n'ait posé ses dépendances ; passé en lazy-init pour désynchroniser du boot-order.
- **FlushNow agrégé au tour finalisé** : un flush immédiat pouvait couper un tour en cours d'écriture ; l'agrégation attend la finalisation du tour avant de flusher, évitant un état partiel visible.
- **Alias `Pose`** : le contrat définissait son propre type `Pose`, en collision de nom avec `UnityEngine.Pose` importé implicitement — renommé côté contrat pour lever l'ambiguïté de compilation.
- **Module Audio manifest** : le module Audio (WebCamTexture/micro) n'était pas déclaré dans le manifest Unity, bloquant l'accès caméra/micro en build ; activé explicitement.
- **`_comment_xreal` hors `dependencies`** : une entrée de manifest UPM censée être un commentaire était restée dans le bloc `dependencies` actif, faisant échouer la résolution de paquets — déplacée hors du bloc.
- **Usings Editor + `Scene` qualifié** : le code Editor important à la fois `UnityEditor.SceneManagement` et un type `Scene` métier provoquait une ambiguïté de nom ; qualification explicite du type `UnityEngine.SceneManagement.Scene`.
- **CMake 3.22.1** : absent du toolchain externe, requis par IL2CPP pour la compilation native ARM64 ; installé via `sdkmanager`.

Résultat : EditMode 59/59, scène PhoneOnly générée et câblée, APK `mlomega-phoneonly.apk` (54,6 Mo, SHA-256 `31762C5032947FFFACE94BC3F4F096366518B83D0BE7C86831C3D60AD9C53445`, IL2CPP/ARM64, minSdk29, `MLOMEGA_PHONE_ONLY`, endpoint LAN), triage audit 11/11 + invariant `turns.created_at` réfutés, V19 207/2/0 + V18 ciblé 5/5. Décision : le premier build est livré sans les gates produit Android-local (ASR/traduction/gestes/TTS locaux, arbitrage micro, sémantique multi-sessions/jour) — traités séparément après validation device.

## 2026-07-07 — §E47C : provisioning modèles device + gating wake word + multi-sessions/jour (PC)

Trois livrables côté PC/Python de l'étape E47 (le reste est Kotlin/Unity, agent A) — périmètre strict `services/live-pc/`, `scripts/`, `configs/`, `tests/v19/`, cœur `src/` en lecture/appels seulement.

**1. Provisioning des modèles device.** Nouvelle section `device:` dans `MODEL_MANIFEST.yaml` : zipformer streaming FR (`sherpa-onnx-streaming-zipformer-fr-2023-04-14`) + EN (`…-en-2023-06-26`), KWS wake word EN (`sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01`) — sources officielles k2-fsa/sherpa-onnx, Apache-2.0 ; MediaPipe `hand_landmarker.task` + `gesture_recognizer.task` depuis `storage.googleapis.com/mediapipe-models/…/float16/latest/`, Apache-2.0. Décision sha256 : `PENDING_FETCH` épinglé au premier fetch (même motif que les voix TTS E35) plutôt qu'un hash deviné — auditable et sûr (les .task `latest` évoluent). `fetch_models_v19.py --device` gère les deux formes (fichier `url` .task + archive `.tar.bz2`) et réécrit le hash épinglé dans le manifeste. Deux endpoints SessionHub token-gatés (token en query params, cohérent avec l'accès ephemeral existant) : `GET /models/device/manifest` (liste name/kind/license/sha256/endpoint, `available` selon présence sur PC) et `GET /models/device/{name}` (FileResponse + header `X-Model-Sha256` pour vérif device). Poids sous `models/device/` (git-ignored), jamais dans l'APK.

**2. Gating wake word (routage d'intents).** Profil `wake_word_policy: open|gated` (défaut **open**), lu par `LivePipeline`. La décision porte UNIQUEMENT sur le routage vers l'`IntentRouter` : `_handle_audio_intents` conserve inchangée l'ingestion mémoire (`conversation_bridge.ingest_segment`) et les signaux fine-intel/scene pour TOUS les tours. En `gated`, `_should_route_intent` route un tour final seulement s'il est marqué commande : flag inline `content["is_command"]=true`, ou fenêtre wake-word armée (`arm_command_window`, TTL 8 s, consommée en un tour, prioritaire sur un `is_command` False explicite). Un `is_command=false` explicite est écarté du routage ; un tour SANS aucun signal de gate reste routé (compat open — un device qui n'émet jamais le flag n'est jamais réduit au silence). Le flag arrive additivement par un message DataChannel de contrôle (agent A) que `PhoneOnlyRuntime._on_receipt` route AVANT le traitement UIReceipt. Métriques `/metrics` : `wake_word_policy`, `turns_routed`, `turns_gated_out`.

**3. Multi-sessions/jour — mécanisme reopen exact.** Constat clé : `close_brainlive_day` (cœur, lecture seule) court-circuite en tête (lignes ~349-351) si la ligne `v18_close_day_runs` du jour est `completed` → retour `resumed_close_day` AVANT même de consulter `force` ou `begin_or_resume_run`. `force=True` seul n'aide pas (jamais atteint). Décision : chemin reopen **service-side additif**, sans éditer le cœur — `run_phoneonly_close_day.py --allow-rerun` fait un `UPDATE` ciblé sur la SEULE ligne du jour de `v18_close_day_runs` (`status='reopened'`, `cleanup_eligible=0`, `completed_at=NULL`) via les helpers DB du cœur (`connect`/`write_transaction`). La ligne n'étant plus `completed`, l'appel `close_brainlive_day` suivant dépasse le court-circuit ; `begin_or_resume_run` (idempotency_key `close_day_v18_7:{person}:{day}`) ne trouve AUCUN run actif — son lookup ne matche que `status IN ('started','running')`, et l'ancien run est `completed`, sans contrainte UNIQUE sur `idempotency_key` — donc `INSERT OR IGNORE` crée un run NEUF (`resumed=False`) avec des stages frais, rejouant chaque étape sur les données CUMULÉES des deux sessions. Pourquoi reopen-par-statut plutôt que delete de la ligne ou `--force` : le delete perdrait l'audit du 1er run ; `--force` ne franchit pas le court-circuit (situé avant). Idempotence du re-run garantie par construction du cœur : chaque stage clé ses écritures sur `stable_id` + `upsert` (moves/routines `v19_visual_consolidation`, entrées `v19_life_model_store`, manifests), donc un rejeu met à jour les mêmes lignes sans dupliquer assembler/bundles. Câblage : `SinglePhoneRuntimeManager` compte les close-days complétés et arme `allow_rerun=True` sur toute session créée après un close-day du jour déjà complété ; `PhoneOnlyRuntime._run_close_day` ajoute alors `--allow-rerun` à la commande subprocess. Une session persistée après redémarrage process est couverte de toute façon par la vérification interne du script (no-op si la ligne du jour n'est pas `completed`).

**Tests (tests/v19, sous `.venv-live`).** `test_device_provisioning.py` (6) : manifeste, download exact sha-vérifié, gating token 401/422, 404 inconnu/non-provisionné. `test_wake_word_gating.py` (7) : open route tout, gated route seulement les commandes mais mémorise tout, compat sans flag, fenêtre latch + expiration, policy invalide → open, message contrôle runtime. `test_multi_session_close_day.py` (6) : reopen flip completed→reopened, no-op absent/non-completed, court-circuit bypassé, run neuf non-resumed via `begin_or_resume_run`, manager arme allow_rerun sur 2e session, commande subprocess porte --allow-rerun.

## 2026-07-08 — §E48-A livrable 1 : client de provisioning des modèles device (app) + embarquement des petits modèles

Premier livrable E48-A côté app (Kotlin/Unity) : remplacer l'`adb push models\device\.` manuel de E47 par un téléchargement automatique au pairing, et embarquer les petits modèles dans l'APK. Les endpoints PC (`GET /models/device/manifest`, `GET /models/device/{name}`) existent depuis E47-C et sont consommés tels quels.

**Placement du client — module `livetransport`.** Le client de provisioning (`ModelProvisioner`, `DeviceModelManifest`, `ModelProvisioningCallbacks`) vit dans `livetransport`, le SEUL module qui possède déjà l'endpoint + le token de session (`SessionCredentialStore`, `SignalingClient`, `PcEndpoint`) et un client OkHttp. `reflexvision` n'a ni HTTP ni token ; l'y placer aurait dupliqué ces deux dépendances. Le pur parsing/plan (`DeviceModelManifest`) est isolé sans import Android/OkHttp pour être testé sur la JVM (motif E47-A `MicAudioFanout`).

**Layout on-device = miroir de `models/device/` sous `getExternalFilesDir()/models/`.** Exactement la structure que produisait le `adb push` de E47 (cloturé, gestes validés dans ce dossier). Les archives sherpa `.tar.bz2` sont extraites en place (commons-compress, même comportement bz2+tar que `fetch_models_v19.py`), les `.task` MediaPipe déposés directement. Écriture atomique (fichier `.part` puis rename ; l'archive vérifiée avant extraction), sha-256 vérifié contre `X-Model-Sha256` (ou le manifeste), reprise = re-téléchargement d'un fichier incomplet (le `.part` est écrasé en écriture tronquante). Un modèle qui échoue n'interrompt pas les autres et ne casse jamais la session (dégradé honnête). Provisioning en tâche de fond (coroutine `Dispatchers.IO`), jamais bloquant pour le démarrage de session.

**Réconciliation des noms sherpa (`normalizeSherpaDir`).** Les archives sherpa livrent des onnx tagués époque (`encoder-epoch-99-avg-1-…onnx`) alors qu'`AsrKwsService` charge les noms canoniques `encoder.onnx`/`decoder.onnx`/`joiner.onnx`. Le provisioner copie la variante float (non-int8) de chaque rôle vers son nom canonique après extraction (idempotent, best-effort), pour que les modèles téléchargés soient réellement chargeables. `AsrKwsService` reste inchangé. `AsrBridge` a été repointé de `getFilesDir()/reflex/asr` (chemin E26 jamais validé device, incohérent avec le push E47) vers `getExternalFilesDir()/models/<dir sherpa par langue>` + KWS, cohérent avec `GestureBridge` et le layout réel.

**Embarquement — petits modèles seulement (décision poids E47/E48-A confirmée).** `AndroidBuild.cs` copie KWS + les 2 `.task` MediaPipe (~33 Mo) de `models/device/` du repo vers `Assets/StreamingAssets/models/` au build (absents = skip + warning, jamais d'échec de build ; test_wavs/README exclus). Un `index.txt` généré au build liste chaque fichier embarqué. Au premier lancement `StreamingAssetsModelInstaller` lit cet index et copie via `UnityWebRequest` (StreamingAssets étant dans le jar APK sur Android, non listable au runtime — voie standard) vers `files/models/`, sans jamais écraser un fichier déjà présent. Les 2 ASR streaming (~300-380 Mo) restent téléchargés. Ordre garanti : le `ModelProvisioningBridge` attend la fin de l'installer avant de calculer les manquants, donc les deux chemins ne se disputent jamais un même fichier.

**Re-arm à chaud : NON — report au prochain lancement (décision assumée).** Ré-armer sherpa/MediaPipe en cours de session obligerait à démonter puis reconstruire les graphes natifs (risque sur l'invariant micro unique, complexité). À la place : le provisioning tourne en fond, et à la prochaine activation du `ReflexScheduler` (idempotent) ou au prochain démarrage les modèles présents sont chargés. Garde-fou minimal ajouté : `AsrBridge.Activate`/`GestureBridge.Activate` remettent `IsRunning=false` si la construction native échoue (modèle encore absent), pour que le scheduler ré-essaie sans état bloqué et sans crash — la feature reste en dégradé honnête, la capture (uplink WebRTC) n'est jamais affectée.

**UI — réutilisation du `StatusBar`, pas de nouveau système.** Une ligne discrète `dl:<modèle> NN%` s'ajoute au `StatusBar` existant (surface permanente déjà pilotée par l'état live cam/mic/net/pc/batterie) tant que `ModelProvisioningBridge.IsProvisioning`. Aucun composant broker-admis inventé.

**Dépendances ajoutées à `livetransport`** : `org.apache.commons:commons-compress:1.21` (extraction tar.bz2, pur JVM, exporté au Plugins Unity), et en test `org.json:json:20240303` (le `org.json` Android des tests unitaires est un stub non mocké — la vraie impl permet de tester `DeviceModelManifest.parse` sur la JVM).

**Gap signalé (non corrigé, hors périmètre).** Le modèle Silero VAD (`silero_vad.onnx`) attendu par `AsrKwsService` n'est PAS dans la section `device:` du manifeste — il n'est donc ni téléchargeable ni embarqué. L'ASR device restera en dégradé honnête tant que ce modèle n'est pas ajouté au manifeste PC (ajout d'une entrée `silero_vad` dans `configs/MODEL_MANIFEST.yaml`, une ligne). Signalé à l'orchestrateur PC, pas corrigé ici (périmètre services PC).

**Tests JVM (livetransport, sans device).** `DeviceModelManifestTest` (7) : parsing, chemin installé = dir extrait nommé d'après le stem d'archive, sélection des manquants disponibles, exclusion des indisponibles même absents, phone complet → rien, tolérance JSON vide/malformé, strip suffixe archive. `ModelProvisionerCoreTest` (7) : `copyHashing` (bytes + sha256 + progression finale = total), `sha256Of`, rename atomique (+écrasement stale), extraction tar.bz2 reproduisant dir + fichiers, rejet zip-slip, reprise (partial écrasé). Total module 24 verts, suite JVM globale 56 verts.

*(Suivi : le gap silero_vad ci-dessus a été corrigé le jour même — entrée `silero_vad` ajoutée au manifeste device (MIT, hash épinglé) et modèle ajouté à la liste embarquée dans l'APK.)*

## 2026-07-08 — §E48-A-3 : traduction live device (ONNX Runtime + OPUS-MT) + réparation de la couche réflexe PhoneOnly

**Moteur (décision après comparatif sourcé).** La traduction live est un RÉFLEXE DEVICE (décision utilisateur : offline, comme les sous-titres). Retenu : **ONNX Runtime + Helsinki-NLP OPUS-MT `opus-mt-fr-en`/`opus-mt-en-fr`, exports ONNX int8 (Xenova, Apache-2.0)** — encodeur + décodeur mergé KV-cache + `tokenizer.json`, ~100 Mo par direction. Rejetés : ML Kit Translate (dépendance Google Play Services + ToS « embedded devices » ambiguë pour un wearable XR, packs hors de notre provisioning sha-256) ; Bergamot/Marian et Argos/CTranslate2 (aucun portage Android officiel — chantier NDK entier) ; NLLB distillé (licence CC-BY-NC + 6-8 Go RAM, hors budget réflexe).

**Risque 1 — coexistence ONNX Runtime.** L'AAR sherpa-onnx 1.12.10 embarque `libonnxruntime.so` (1.17.1) mais N'EXPOSE PAS l'API Java `ai.onnxruntime`. Résolution : dépendance `com.microsoft.onnxruntime:onnxruntime-android:1.17.1` (version alignée sur la .so sherpa), exportée vers Unity comme `mlomega-onnxruntime.aar` ; le doublon de lib native est dédupliqué au packaging (une seule copie identique embarquée).

**Risque 2 — SentencePiece.** Pas de binaire Android fiable pour les bindings JNI desktop. Résolution : **`MarianTokenizer` pur Kotlin** (unigram, chargé depuis le `tokenizer.json` des exports Xenova — pas de .spm binaire), couvert par tests JVM round-trip sur le vocabulaire réel.

**Décodage.** Greedy autoregressif sur le décodeur mergé (`use_cache_branch` false au pas 0, cache encodeur gelé ensuite, cache décodeur croissant), max 64 tokens, 2 threads intra-op ; tenseur BOOL construit par ByteBuffer + `OnnxJavaType.BOOL` (pas d'overload boolean-array dans l'API Java ORT). Le flux exact est validé par un test d'intégration desktop opt-in qui traduit une vraie phrase sur les modèles téléchargés (skippé si absents). Budget réflexe : finals UNIQUEMENT, sessions lazy, libération après 60 s d'inactivité, une seule direction résidente.

**Distribution.** 6 entrées `device:` du manifeste (une par fichier — réutilise le provisioning E47-C/E48-A-1 tel quel, aucun nouveau mécanisme), hashes épinglés au premier fetch. UI : `TranslateBridge` (Unity) comble le chaînon manquant AsrBridge→SubtitleSkill, la traduction s'affiche sous le sous-titre original et alimente `translation_hot` (expire au tour, §9.1). Toggle : menu « Traduire » (flip via `on` nullable) + intents PC « traduis en direct »/« stop traduction » enregistrés AVANT le `translate` générique (qui les avalerait) + entrées high-confidence + schéma LLM ; copie explicite du booléen `on` dans `_llm_parse` (la boucle falsy-skip perdait `on=False`).

**Réparation majeure découverte au câblage.** `PhoneOnlySceneBuilder` n'ajoutait AUCUN composant de la couche réflexe (AsrBridge, GestureBridge, WakeWordGate, ReflexScheduler, les 5 skills E26, LocalIntentSource) à la scène PhoneOnly — vérifié par GUID dans `PhoneOnly.unity` : les gates E47 de l'APK v2 (wake word, gestes, sous-titres offline) n'avaient aucun hôte runtime et ne pouvaient pas s'activer. Le builder ajoute désormais toute la couche (LocalIntentSource enregistrée au broker par un second E25SourceBootstrap, refs du scheduler assignées, le reste s'auto-câble en Awake ; `DeviceCommandHandler._translate` câblé). La scène doit être régénérée (`PhoneOnlySceneBuilder.BuildScene`) avant le prochain build APK. Constat cohérent avec la discipline de passation : ne pas croire un rapport de clôture sans le vérifier dans le checkout.

**Tests (2026-07-08).** JVM 77/77 (livetransport 27, reflexvision 50 — MarianTokenizerTest, OfflineTranslatorTest, OfflineTranslatorIntegrationTest incluse et exécutée sur les vrais modèles) ; pytest ciblés intents/provisioning/gating 43/43 (1 skip clé OpenAI).

## 2026-07-08 — E48-B §2 : ChangeAttentionSkill live (ADR)

Périmètre strict PC (`services/live-pc/change_attention.py` + câblage `live_pipeline.py`), cœur `src/` en lecture seule, aucun code device (le device se contente d'afficher l'UIIntent du cue, exactement comme documenté côté device pour `ReflexSignal.ZoneChange` — « WorldBrain/keyframe concern, not an on-device skill »).

**Identité de zone (limite honnête).** ``active_zone`` (id de cluster de pose ``zone-N`` de ``spatial.PoseKeyframeMap``) n'est stable qu'AU SEIN d'une session — c'est le chemin toujours actif pour détecter « tu as quitté ce coin et tu y reviens » pendant la même session. Aucun identifiant de zone stable inter-sessions n'existe aujourd'hui dans le live (``place_hint`` n'est renseigné qu'à ``end_session``, jamais en cours de session) ; plutôt que d'inventer une nouvelle table de zone persistante (interdit par la discipline), quand un ``place_hint`` stable est fourni par l'appelant, `ChangeAttention` va lire — en lecture seule — la dernière ligne `scene_session_summaries_v19` (déjà écrite par `WorldBrain.end_session`) correspondant à ce `place_hint` pour amorcer la mémoire de la zone dès la première entrée de la session courante. Sans `place_hint` correspondant, dégradation silencieuse vers le mode intra-session seul.

**Détection.** À chaque `SceneDelta` (même cadence que `WorldBrain.ingest_scene_delta`), `ChangeAttention.on_scene_snapshot` compare `active_zone` au tour précédent : changement de zone = sortie (l'état de la zone quittée est figé) ; retour à une zone déjà visitée cette session (ou amorcée depuis `scene_session_summaries_v19`) = ré-entrée à évaluer. L'état est un ensemble de labels d'entités `confirmed` (visibles, non périmées) ; le score d'écart = `|Δ| / |union|` (symmetric difference / union) — un objet apparu OU disparu compte, un remaniement total du set compte plus qu'un seul objet.

**Anti-bruit (invariants stricts, non négociables).** SILENCE total à la première visite d'une zone (rien à comparer) ; SILENCE si `map_quality` < seuil configuré (un cue de changement est une affirmation spatiale « ici » — une carte de mauvaise qualité ne peut pas honnêtement la soutenir, même principe que `bearing_to` en E28) ; SILENCE si le score d'écart n'atteint pas `min_change_score` ; cooldown par zone (`cooldown_seconds`) même si un nouveau changement réel survient ; UN SEUL cue par ré-entrée qualifiante (la mémoire de la zone est immédiatement remise à jour après le cue, donc la ré-entrée suivante compare contre l'état frais, pas contre l'ancien).

**Livraison.** Aucune nouvelle queue/broker : le cue est un candidat `context_card` (`priority=0.35`, délibérément bas — un point d'intérêt sobre, jamais une alerte) envoyé via `BrainLiveSceneAdapter._enqueue` → `v18_delivery.enqueue_delivery` → la queue canonique H1, exactement le chemin déjà utilisé par les autres suggestions de scène (E28/E35/E38). `truth_level` implicite du message est honnête : un diff d'ensemble est suggestif (« quelque chose a changé »), jamais une affirmation ferme sur l'objet précis en cause quand plusieurs labels diffèrent à la fois. Jamais de flèche spatiale précise — seulement le point d'intérêt textuel, avec les `evidence_refs` des entités en cause quand WorldBrain les a conservées.

**Config.** Nouvelle section de profil `change_attention:` (même mécanisme que `worldbrain:`/`fine_intel:`/`stranger:` — lu via `self.profile.get("change_attention", {})`, valeurs par défaut si absente) : `min_change_score` (0.34), `cooldown_seconds` (300), `min_map_quality` (0.35).

**Tests.** `tests/v19/test_change_attention.py` (6) : première visite → silence ; ré-entrée avec objet disparu → un cue puis silence si aucun changement supplémentaire ; ré-entrée sans changement → silence ; `map_quality` faible → silence même avec changement réel ; cooldown respecté puis cue de nouveau après expiration ; livraison réelle via `BrainLiveSceneAdapter`/`v18_delivery` → ligne dans `brainlive_intervention_delivery_queue`. `pytest tests/v19/test_change_attention.py tests/v19/test_e28_worldbrain.py tests/v19/test_e38_fine_intel.py tests/v19/test_e27_pipeline.py tests/v19/test_phoneonly_runtime.py tests/v19/test_wake_word_gating.py -q` = 55 passed (aucune régression sur WorldBrain/fine-intel/pipeline/PhoneOnly/wake-word touchés par le câblage).

**Réserve.** La comparaison inter-sessions par `place_hint` reste best-effort : tant que rien n'assigne un `place_hint` stable EN COURS de session (aucun mécanisme de ce type n'existe encore), le cue de changement est en pratique presque toujours intra-session (quitter/revenir dans la même session) — cohérent avec le point 2 du backlog qui documente cette même limite pour `ReflexSignal.ZoneChange`. Un futur zone-id stable inter-sessions (ex. re-localisation SLAM V19.B/C) pourra alimenter le même mécanisme sans le modifier.

## 2026-07-08 — E54 : rétention médias & budget disque (ADR)

**Constat.** Rien n'était purgé automatiquement (le close-day calcule `cleanup_eligible` = autorisation, jamais une suppression physique) → le disque grossit sans limite. Bug réel : `visionrt.default_keyframe_sink` écrivait les keyframes dans un `tempfile.NamedTemporaryFile('kf_*.jpg')` de `%TEMP%` puis en insérait le chemin temp dans `vision_frames.image_path` — un nettoyage système de `%TEMP%` orpheline des keyframes que la base croit encore présents. Décision utilisateur : **tout garder, budget 100 Go, rejouer clips/audio à tout moment**.

**Keyframes hors temp.** `default_keyframe_sink` écrit désormais dans un dossier média GÉRÉ et persistant : racine `MLOMEGA_MEDIA` sinon `storage/media/` sous le projet, sous-dossier `keyframes/AAAA-MM-JJ/` (helpers `media_root()`/`keyframe_dir()`). `vision_frames.image_path` pointe ce chemin stable. Rétro-compat : les anciens chemins temp déjà en base restent lus tels quels (le replay lit `image_path` verbatim, aucune migration). Le clip/audio n'a pas eu besoin du même correctif : les clips passent déjà par `visual_evidence_assets_v19.uri` (chemin choisi par l'appelant, pas un temp), l'audio par `evidence_root()` (`data/evidence/audio/`, déjà persistant depuis E37).

**Où vit « référencé » dans le schéma réel (inspecté, pas deviné).** La preuve est un ensemble de colonnes `evidence_refs_json`/`evidence_json`/`observation_json` réparties sur les tables V18/V19 (`visual_events_v19`, `scene_session_summaries_v19`, `world_entity_links_v19`, `brain2_spatial_routine_models`/`_visual_task_models`, `life_model_entries_v19`, `predictions_v19`, `prediction_outcomes_v19`, `self_schema_v19`, `brainlive_life_hypotheses`). Un keyframe y est cité soit comme chaîne `"frame:<frame_id>"` (worldbrain/visionrt), soit comme `{"source_id": "<id>"}` ; un clip via le FK `visual_events_v19.asset_id` OU son `visual_asset_id`/sha/uri dans un `evidence_refs` ; un WAV audio est la preuve deep-audio pointée par sa ligne `brainlive_sensor_events` `speech_segment` (`source_path`/`chunk_path`). La rétention agrège toutes ces colonnes en un blob texte et matche chaque token de média par occurrence DÉLIMITÉE (`(?<![a-z0-9])tok(?![a-z0-9])`) pour qu'un id court ne soit pas un faux positif substring d'un id long (`kf-old` ≠ `kf-oldref`).

**Module de rétention** (`services/live-pc/media_retention.py`, nouveau — module dédié plutôt qu'`EvidenceStore`, jamais instancié en prod et sans notion de « référencé » ni de tables réelles ; le module dédié opère directement sur `vision_frames`/`raw_assets`, `visual_evidence_assets_v19`, `brainlive_audio_segments_v154`+`brainlive_sensor_events`). Trois passes, toutes best-effort (aucune ne lève, aucune ne fait échouer le close-day) : (1) **transcodage audio** WAV→Opus via ffmpeg `libopus 24k` (~÷10), après la re-transcription nocturne, réversible : le sha d'origine (lu sur `brainlive_sensor_events`, la table de segments n'en porte pas) est conservé en métadonnée `speaker_json.transcode`, les chemins base repointés, le WAV supprimé seulement après un Opus non vide ; désactivable (`transcode_audio`), dégradé honnête si ffmpeg absent (WAV conservé, WARN). (2) **purge des non-référencés âgés** : un média non cité ET plus vieux que `retention_days` (90 j) est supprimé (fichier + lignes de table cohéremment ; pour l'audio, la ligne `speech_segment` liée est retirée aussi). (3) **budget global** : au-delà de `total_gb` (100), éviction du plus ancien NON-référencé d'abord ; le référencé n'est JAMAIS supprimé, même le plus vieux, même en dépassement ; si tout le dépassement est référencé → aucune suppression + WARN.

**Câblage.** La rétention est appelée dans `scripts/run_phoneonly_close_day.py` APRÈS `close_brainlive_day`, et UNIQUEMENT si `result["cleanup"]["eligible"]` est vrai (le gate posé par le pipeline une fois tous les stages faits, y compris la re-transcription deep-audio). Chargée par chemin de fichier (le module vit sous `services/live-pc/`, pas dans le package `src`). Best-effort strict : le code de sortie du script reste piloté par le seul statut du close-day ; une purge/transcode qui échoue renvoie un petit rapport d'erreur, jamais une exception.

**Profils & DOCTOR.** Bloc `storage_quota:` ajouté à `configs/profiles/rtx3070.yaml` (source pour la rétention : `total_gb:100`, `warn_gb:80`, `fail_gb:95`, `retention_days:90`, `transcode_audio:true`, `day_buffer_warn_gb/fail_gb`) et à `configs/user_profile.yaml` (source pour DOCTOR, commenté). DOCTOR `-Quota` lit maintenant ces valeurs : `user_profile.yaml` d'abord, `rtx3070.yaml` en repli, défauts codés ensuite ; ajout de `total_gb` (avec `fail_gb` par défaut = `total_gb`) et seuils par défaut relevés (80/95 Go) pour la décision 100 Go.

**Tests.** `tests/v19/test_media_retention.py` (7) sur le schéma réel : référencé jamais sélectionné (ni âge ni budget), non-référencé âgé purgé pendant que le référencé de même âge est gardé (lignes retirées cohéremment), éviction budget du plus ancien non-référencé d'abord, dépassement 100 % référencé → rien supprimé + WARN, no-op sous quota, transcode réversible (ffmpeg réel : sha d'origine conservé, chemins repointés, WAV supprimé après Opus ; skip marqué si ffmpeg absent) + no-op si désactivé. Non-régression fichiers touchés : `test_e37_nightly.py` + `test_visionrt.py` (assertion ajoutée : keyframe sous `MLOMEGA_MEDIA`, pas un temp) + `test_longitudinal_periods.py` + `test_multi_session_close_day.py` = 24 passed / 1 skip (cv2 hors `.venv`, vert dans `.venv-live`).

**Non vérifié / réserves.** Purge et budget testés sur keyframes (chemin le plus simple et le plus à risque) ; clips/audio couverts par l'inventaire et la logique de référence mais l'éviction budgétaire d'un vrai clip/audio n'a pas de test dédié (mêmes primitives `_delete_item`/`inventory`). Le transcode ffmpeg réel est prouvé ici (ffmpeg présent) mais pas sur un WAV issu d'une vraie session live (synthétique). La rétention n'est déclenchée qu'au close-day PhoneOnly ; un déclenchement manuel/DOCTOR n'est pas câblé (hors périmètre).
