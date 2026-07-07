# MLOmega V19 — Exocortex personnel local-first

Une mémoire de vie totale, vivante et prédictive. Le téléphone (puis les lunettes XR) capture
audio + vidéo en continu ; le PC (RTX 3070) comprend en direct — objets, personnes, lieux,
conversations — et affiche suggestions, profils et rappels sur l'écran ; la nuit, tout est
consolidé (transcription HQ, diarisation, Brain2, Life Model) pour détecter tes routines,
tes patterns cachés et prédire ta vie court/moyen/long terme. **Tout en local** — le cloud
(OpenAI/Gemini) est un mode opt-in explicite.

Trois couches : **Ultra-Live** (réflexes sur l'appareil : wake word, gestes, sous-titres,
zoom — marche PC coupé) · **Live contextuel** (PC : vision, identité, mémoire chaude,
suggestions BrainLive) · **Mémoire profonde** (close-day nocturne : consolidation + prédictions).

---

## Prérequis

- Windows 11 + GPU NVIDIA (cible : RTX 3070 8 Go), driver récent (`nvidia-smi` OK)
- Python 3.11 (64-bit) · Git · ffmpeg (`winget install Gyan.FFmpeg`)
- [Ollama](https://ollama.com) installé (les modèles sont tirés à l'installation)
- Téléphone Android (cible : Galaxy S25) sur le même Wi-Fi que le PC
- Pour compiler l'APK : Unity 6 LTS (6000.0.23f1) + licence Personal (login Unity Hub)

## Installation (PC)

```powershell
git clone https://github.com/SpendinFR/MemoS.git
cd MemoS\Mlomega-main

# 1. Environnements Python (cœur + live)
python -m venv .venv
.venv\Scripts\pip install -r requirements-v18_8-windows.lock.txt     # torch cu121, whisperx, pyannote… (long)
powershell -ExecutionPolicy Bypass -File scripts\INSTALL_MLOMEGA_V19_WINDOWS.ps1   # crée .venv-live

# 2. Qdrant natif (sans Docker) — binaire dans tools\qdrant\ (cf. scripts\START_QDRANT.ps1)
# 3. Modèles
ollama pull qwen2.5:7b-instruct-q4_K_M ; ollama pull qwen2.5:3b-instruct-q4_K_M ; ollama pull moondream ; ollama pull qwen3-vl:8b
.venv-live\Scripts\python scripts\fetch_models_v19.py            # détecteur, visage, TTS
.venv-live\Scripts\python scripts\fetch_models_v19.py --device   # modèles téléphone (ASR/gestes)

# 4. Configuration
copy MLOmega_V18_8_1_Evidence_Connected\.env.core-v18_8.template .env   # puis remplir chemins + HF_TOKEN
powershell -ExecutionPolicy Bypass -File scripts\setup_profile.ps1       # profil (affichage, LLM, endpoints…)

# 5. Vérifier
powershell -ExecutionPolicy Bypass -File scripts\DOCTOR_MLOMEGA_V19.ps1 -Full
```

## Lancer une session

```powershell
# PC (3 commandes)
powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
ollama serve   # si pas déjà en service
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

Téléphone : installer `apps\xr-mobile\build\android\mlomega-phoneonly.apk`
(`adb install -r ...`), pousser les modèles une fois
(`adb push models\device\. /sdcard/Android/data/com.mlomega.xr/files/models/`),
ouvrir l'app → pairing automatique. Parle naturellement (« c'est quoi ça ? »,
« retiens : c'est Karim », « où est mon téléphone ? ») ; paume = menu ; en fin de
session, le bouton **Terminer** déclenche automatiquement la consolidation (close-day).

➡️ **Guide complet de première session : [`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md)**
(toutes les commandes vocales, gestes, checklist, dépannage).

## Compiler l'APK soi-même

```powershell
powershell -ExecutionPolicy Bypass -File scripts\BUILD_ANDROID_PLUGINS.ps1   # AAR Kotlin (JDK17+Gradle 8.7)
$env:MLOMEGA_PC_HOST="<IP-du-PC>"; $env:MLOMEGA_PC_PORT="8710"
& "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe" -batchmode -quit `
  -projectPath apps\xr-mobile -executeMethod MLOmega.XR.Editor.AndroidBuild.BuildApk -logFile -
# → apps\xr-mobile\build\android\mlomega-phoneonly.apk
```

Prérequis build : Android SDK 34 + NDK 23.1.7779620 + CMake 3.22.1 (via `sdkmanager`), JDK 17,
Gradle 8.7 — détails dans `E46D_STATE.md`.

## Aller plus loin

- **Dehors (4G/5G)** : tunnel Tailscale — guide `docs/OUTSIDE_ACCESS.md`
- **Lunettes XREAL** : même app, ajouter le SDK XREAL (gate G1) — `apps/xr-mobile/README.md`
- **Architecture & historique complet** : `docs/EXECUTOR_HANDOFF.md`, `docs/EXECUTOR_BUILD_GUIDE.md`,
  `docs/DECISIONS.md`, `docs/PROD_BACKLOG.md`

## État (2026-07-07)

E1→E38 + E46/E47 livrés : pipeline complet capture→compréhension→mémoire→prédiction,
identité visage+voix, langage naturel multi-tour, wake word configurable, gestes, offline ASR,
proactivité, replay, mode dehors. 226 tests Python + 59 tests Unity + 42 tests JVM verts.
Reste : validation device S25, TTS hors-ligne, client auto des modèles, test final close-day (E30).
