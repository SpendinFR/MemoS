# E46-D — État de reprise Android/Unity

Branche: `feat/v19-e46d-android` (depuis origin/main 1ee8927). Foyer projet: `Mlomega-main/`.
Une ligne par étape, mise à jour APRÈS chaque succès. Reprendre où c'était.

## Environnement constaté au (re)démarrage
- Unity Editor 6000.0.23f1 installé: `C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe`.
- Unity Hub: `C:\Program Files\Unity Hub\Unity Hub.exe`. Modules Hub headless: `android`, `android-sdk-ndk-tools`, `android-open-jdk`.
- AndroidPlayer présent MAIS sous-modules embarqués SDK/NDK/OpenJDK ABSENTS.
- Toolchain externe OK: JDK17 `C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot`; Android SDK `%LOCALAPPDATA%\Android\Sdk` (platform-34, build-tools 33.0.1/34.0.0/35.0.0, platform-tools/adb) — NDK ABSENT du SDK externe; Gradle local `.tools\gradle-8.7\bin\gradle.bat`.

## Étapes
- [x] 1. Toolchain Android externe complet: SDK android-34 + build-tools + platform-tools + **NDK r23b (23.1.7779620)** installé via sdkmanager (Unity 6000.0 le requiert) + JDK17 + Gradle 8.7. Env vars User posés (ANDROID_HOME/SDK_ROOT/NDK_ROOT/NDK_HOME/JAVA_HOME). Hub install-modules REFUSÉ (éditeur hors-Hub). Licence Unity batchmode = BLOQUÉE (voir section BLOCAGE). AndroidBuild.cs (étape 5) configurera `AndroidExternalToolsSettings` explicitement.
- [x] 2. Plugins Android reconstruits (BUILD SUCCESSFUL, testDebugUnitTest+exportUnityRelease verts). Export vers `apps/xr-mobile/Assets/Plugins/Android`. Dédup Kotlin/annotations OK (jars dupliqués absents). SHA-256:
    - mlomega-livetransport.aar: `19d04664b305f050cc77e46d8d51a3d2b4b55d9badd5564620901b83db14a715`
    - mlomega-reflexvision.aar: `c1b128cdd9bd7a9f7040fe3e5f4f7b81b307a091d117b7419bd392604f558ed1`
    - sherpa-onnx-1.12.10.aar: `f51f59368674faee85b655129c52f9e87beef287bf22f35d023bab83becad74c` (= pin DECISIONS)
- [ ] 3. Import Unity batchmode + tests EditMode verts (UPM/XREAL/asmdef/manifest OK).
- [ ] 4. Scène PhoneOnly (PhoneOnlySceneBuilder.BuildScene) vérifiée.
- [ ] 5. Build APK reproductible (Editor/AndroidBuild.cs) — SHA-256 + chemin.
- [x] 6. Triage constats d'audit — confrontés au checkout courant. TOUS RÉFUTÉS (déjà corrects, aucun fix code requis) :
    1. Conversion aiortc PCM: `gateway._audio_frame_to_mono` gère packed/planar, int/float, downmix mono, préserve l'échelle, retourne le vrai sample_rate. Réel, pas un stub.
    2. Gel/drain + flush: `phoneonly_runtime.end_session_only` = stop_accepting_media → drain_audio(Queue.join + idle) → flush_audio → close_transport → end_session strict → conversation end strict → release. Ordre correct.
    3. Callback audio en vol: `gateway._drain_audio` compte `_audio_inflight` + `_audio_idle` ; `drain_audio` attend join() ET idle.
    4. Arrêt ingress/vidéo: `stop_accepting_media` teardown tous les peers ; `close_transport` ferme ingress + attend video_task.
    5. ID BrainLive unique: core `start_live_session` = `stable_id("blsess", person_id, now, title, uuid4().hex)` → unique par session ; WorldBrain le reçoit.
    6. CloseDay env cœur: `_run_close_day` lance subprocess `.venv/Scripts/python.exe` (cœur), existence vérifiée. Séparation live(.venv-live)/post-stop(.venv) respectée.
    7. Archive VAD indép. ASR: `audiort._notify_segment` archive sur asr_refused, asr_error (avant raise), status non-ok, empty_transcript. Chaque segment VAD-final archivé.
    8. PersonId: person_id threadé comme str cohérent (pipeline→worldbrain→conversation→closeday). Pas de bug.
    9. Renouvellement token Kotlin: `LiveTransportPlugin.updateCredentials` mute signalingUrl/sessionId/token ; `establish()` les relit à chaque reconnect.
    10. ICE/reconnect/teardown: non-trickle `iceGatheringComplete.await()` ; `teardownPeer` avant reconnect (dispose complet track/source/dc/peer) ; `connectLoop` rebuild peer frais.
    11. Texture Unity↔WebRTC: `UnityFrameCapturer.onTextureFrame` poste sur `helper.handler` (GL thread) → TextureBufferImpl OES ; fallback I420 alloue JavaI420Buffer + copie plans indép.
  + Invariant `turns.created_at`: RÉFUTÉ. `v18_life_model.py` L82 `"turns":(...,("start_s",))` (pas de fallback created_at, contrairement aux autres tables) ; L260 dérive `occurred_at = conversation.started_at + start_s`. Aucune dép réelle à turns.created_at.
- [x] 7. Suites finales:
    - V19 complète (`.venv-live`, `pytest tests/v19`): **207 passed, 2 skipped, 0 failed** (210s). Améliore l'état d'arrêt (206/2/1 failed). Skips = Ollama réel + OPENAI_API_KEY absents (attendu).
    - V18 ciblé (`.venv` cœur, pytest installé — dev tool, cœur intact): `test_v18_life_model_turn_time.py` + `test_v18_4_close_day_and_phone_bridge.py` = **5 passed, 0 failed**. Inclut `test_owner_scoped_turn_query_uses_conversation_time_not_turn_created_at` (invariant turns.created_at) VERT.
    - Grep dép réelle `turns.created_at`: AUCUNE (seuls des `c.created_at`/created_at d'autres tables en fallback). Cœur V18.8 NON modifié.

## Étapes bloquées (licence Unity interactive)
- [ ] 3. Import Unity batchmode + tests EditMode — BLOQUÉ (licence). Prêt: manifest.json PhoneOnly propre (aucune réf `file:` XREAL, commentaire seul → import OK sans tarball). Plugins Android + AAR déjà exportés.
- [ ] 4. Scène PhoneOnly (PhoneOnlySceneBuilder.BuildScene) — BLOQUÉ (licence). Scène source vérifiée statiquement: SessionPairing, EyeCaptureSource+PhoneCameraPreview, LiveTransportBridge, UIRuntime, UIReceiptTransportSink, SceneDelta/commandes, PhoneOnlySessionCoordinator (fin explicite) tous câblés.
- [ ] 5. Build APK — BLOQUÉ (licence). LIVRÉ: `Assets/Scripts/Editor/AndroidBuild.cs` (méthode `MLOmega.XR.Editor.AndroidBuild.BuildApk`): configure SDK/NDK r23b/JDK17/Gradle externes, IL2CPP+ARM64, minSdk29/targetSdk34, define `MLOMEGA_PHONE_ONLY`, endpoint via env MLOMEGA_PC_HOST/PORT, sortie `build/android/mlomega-phoneonly.apk`. À lancer après activation licence:
    `& "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe" -batchmode -quit -projectPath apps\xr-mobile -executeMethod MLOmega.XR.Editor.AndroidBuild.BuildApk -logFile -`

## BLOCAGE INTERACTIF — Licence Unity
Batchmode a échoué: `No valid Unity Editor license found. Please activate your license.` (exit 1).
Causes log: `No ULF license found`, `com.unity.editor.headless was not found`, 0 entitlements.
IMPACT: étapes 3 (import/tests EditMode), 4 (BuildScene), 5 (APK) sont BLOQUÉES tant que la
licence n'est pas activée. L'activation Unity 6 Personal exige un login Unity ID interactif.
ACTION UTILISATEUR (une ligne): ouvre Unity Hub, connecte-toi à ton compte Unity ID et active une
licence Personal (Preferences > Licenses > Add > Get a free personal license), OU
`Unity.exe -batchmode -manualLicenseFile <fichier.ulf> -quit` avec un .ulf obtenu via
https://license.unity3d.com/manual (upload du .alf généré par `-createManualActivationFile`).
Le reste (plugins Android, triage audit, suites Python) n'en dépend pas et est traité.

## Journal
- Hub `install-modules` REFUSÉ: éditeur non installé via Hub → `No modules found for this editor`.
  Contournement: NDK installé via sdkmanager + config outils externes dans les prefs Unity.
- NDK r23b (23.1.7779620) installé via sdkmanager (requis par Unity 6000.0). [voir étape 1]
