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
- [ ] 6. Triage constats d'audit ouverts (confirmé/réfuté/corrigé + test).
- [ ] 7. Suites finales V19 complètes + contrôle V18 ciblé ; aucune dép turns.created_at.

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
