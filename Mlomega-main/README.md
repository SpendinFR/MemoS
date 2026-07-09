# MLOmega V19 — Exocortex personnel local-first

> Une **mémoire de vie** totale, vivante et prédictive. Ton téléphone (puis des lunettes XR)
> capture audio + vidéo en continu ; ton PC comprend en direct — objets, personnes, lieux,
> conversations — et t'affiche suggestions, profils et rappels ; la nuit, tout est consolidé
> pour apprendre tes routines, tes patterns cachés et t'aider à anticiper ta vie.
> **Tout tourne en local.** Le cloud (OpenAI/Gemini) n'est qu'un mode **opt-in explicite**.

MLOmega n'est pas un assistant qui invente : chaque chose affichée est **sourcée par une
observation réelle**, avec un niveau de vérité. Pas de nom de personne si l'identité est
incertaine, pas de flèche si la carte est douteuse, pas de démo scriptée.

---

## 1. Ce que ça fait, concrètement

**En direct (pendant une session)**
- **Sous-titres** de ce qui se dit (streaming), **traduction live** FR↔EN offline sur le téléphone.
- **Personnes** : un tag suit une personne détectée (anonyme tant que non identifiée) ; « **retiens : c'est Karim** » l'enrôle (visage + voix) → nom + fiche relationnelle ; « non, ce n'est pas Karim » corrige durablement.
- **Vision à la demande** : « **c'est quoi ça ?** », « **lis le texte** » (OCR), « **traduis-le** », « **zoom** ».
- **Objets** : « **où est mon téléphone ?** » → contour si visible, sinon « dernier vu » avec l'âge.
- **Mémoire** : « **interroge ma mémoire : qu'ai-je dit sur… ?** », « **rappelle-moi ce que je devais faire** ».
- **Replay** : « **rejoue 14h** » → la scène de la tranche horaire (keyframes + clips vidéo + transcript).
- **Suggestions proactives** : si tu réévoques un sujet/une promesse en mémoire, une carte apparaît d'elle-même (sourcée).
- **Contrôle** voix + gestes : menu (paume), cacher l'UI (balayage), zoom (pincement), lancer Maps/YouTube, mode voix (TTS), bascule cloud.
- **Cue de changement** : en revenant dans une zone connue, « quelque chose a changé ici » (discret, anti-bruit).

**La nuit (close-day, au clic sur « Terminer »)**
- Re-transcription HQ (WhisperX) + diarisation (pyannote), attribution voix→personne.
- Consolidation **Brain2** + **Life Model** : faits / hypothèses / prédictions séparés, avec preuves et calibration.
- Rollups **jour / semaine / mois** (routines, patterns, prédictions vérifiées vs réfutées).

**Autonomie & vie privée**
- Marche **PC coupé** en mode réflexe (sous-titres, wake word, gestes tournent sur le téléphone).
- **Mémoire continue** : le mot d'éveil ne coupe jamais l'écoute ni l'enregistrement — il ne fait que *gater les commandes*.
- Rétention médias plafonnée (budget disque), rien de référencé par une preuve n'est jamais supprimé.

## 2. Architecture — trois couches

```
        TÉLÉPHONE (S25 / +tard lunettes XREAL)                     PC (RTX 3070, à la maison)
  ┌───────────────────────────────────────────┐           ┌──────────────────────────────────────┐
  │ caméra + micro (1 seul accès micro)        │  WebRTC   │ Live contextuel :                      │
  │ ── Ultra-Live (réflexes, marche PC coupé) ─┤◄────────► │  VisionRT (détection/tracking/OCR ROI) │
  │   wake word · gestes · sous-titres ·       │  audio+   │  identité visage+voix · WorldBrain     │
  │   traduction live · zoom                   │  vidéo    │  mémoire chaude · suggestions H1       │
  │ ── rendu UI (cards, tags, sous-titres) ────┤  +        │  IntentRouter (commandes NL)           │
  └───────────────────────────────────────────┘  UIIntent └───────────────┬────────────────────────┘
                                                                           │ à la fin de session
                                                            ┌──────────────▼────────────────────────┐
                                                            │ Mémoire profonde (close-day nocturne)  │
                                                            │  transcription HQ · diarisation ·      │
                                                            │  Brain2 · Life Model · jour/semaine/mois│
                                                            └────────────────────────────────────────┘
```

Règle d'or : une frame ne devient **jamais** un souvenir directement — elle passe par
`observation → preuve → événement → mémoire`. Le PC envoie des **UIIntent sémantiques**
(pas des pixels imposés) ; le téléphone garde ses tracks locaux et choisit le rendu.

## 3. Matériel supporté

| Cible | État | Note |
|---|---|---|
| **PhoneOnly** (Android, S25 / OnePlus…) | ✅ APK v3 livré | le premier vrai terrain |
| **Lunettes XREAL** | 🔜 adaptateur écrit, SDK à déposer (E49) | même app, rendu stéréo + caméra Eye |
| **Capture-only + viewer iPhone** | ✅ | lunettes/caméra capturent, tu vérifies dans Safari (`apps/companion-web/`) |
| Snap Spectacles / autres | ⏳ futur | contrats indépendants du matériel, prévus pour ça |

## 4. Installation (PC)

> **Le plus simple — l'assistant guidé** ([WELCOME.md](WELCOME.md)) : il fait tout dans
> l'ordre (scan matériel, `.venv` cœur + `.venv-live`, ffmpeg, Qdrant, modèles Ollama dont
> les VLM live + nuit, modèles device, `.env`, profil, DOCTOR), puis explique le lancement,
> le téléphone et l'entretien :
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\WELCOME_MLOMEGA.ps1
> #  -DryRun pour voir le déroulé sans rien installer · -Defaults pour non interactif
> ```
> Prérequis qu'il ne peut pas poser à ta place : **Python 3.11 64-bit** et l'**appli Ollama**
> (il les détecte et te guide). Aucun **Unity** requis pour utiliser l'app — Unity ne sert
> qu'à *recompiler* l'APK (§7).

Ou l'installation **manuelle**, étape par étape :

```powershell
git clone https://github.com/SpendinFR/MemoS.git
cd MemoS\Mlomega-main

# 1. Environnements Python (cœur + live)
python -m venv .venv
.venv\Scripts\pip install -r requirements-v18_8-windows.lock.txt      # torch cu121, whisperx, pyannote… (long)
powershell -ExecutionPolicy Bypass -File scripts\INSTALL_MLOMEGA_V19_WINDOWS.ps1   # crée .venv-live

# 2. Qdrant natif (sans Docker) — cf. scripts\START_QDRANT.ps1
# 3. Modèles — LLM live + deep + VLM live (moondream) + VLM VISION de nuit (qwen2.5vl)
ollama pull qwen3.5:4b ; ollama pull qwen3.5:9b ; ollama pull moondream ; ollama pull qwen2.5vl:7b
.venv-live\Scripts\python scripts\fetch_models_v19.py            # détecteur, visage, TTS
.venv-live\Scripts\python scripts\fetch_models_v19.py --device   # modèles téléphone (ASR/KWS/gestes/VAD/traduction)

# 4. Configuration
copy MLOmega_V18_8_1_Evidence_Connected\.env.core-v18_8.template .env   # remplir chemins + HF_TOKEN (pyannote)
powershell -ExecutionPolicy Bypass -File scripts\setup_profile.ps1       # profil (affichage, LLM, endpoints…)

# 5. Vérifier
powershell -ExecutionPolicy Bypass -File scripts\DOCTOR_MLOMEGA_V19.ps1 -Full
```

**Prérequis** : Windows 11 · GPU NVIDIA (cible RTX 3070 8 Go, `nvidia-smi` OK) · Python 3.11 64-bit ·
Git · ffmpeg (`winget install Gyan.FFmpeg`) · [Ollama](https://ollama.com) · un token
Hugging Face (pyannote) · téléphone Android sur le même Wi-Fi (première session).

## 5. Lancer une session

```powershell
powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
ollama serve   # si pas déjà en service
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

**Téléphone** : installer l'APK (`adb install -r apps\xr-mobile\build\android\mlomega-phoneonly.apk`),
ouvrir l'app → **pairing automatique** ; les gros modèles ASR se **téléchargent tout seuls** au
premier lancement (les petits sont déjà dans l'APK). Parle naturellement ; en fin de session,
le bouton **« Terminer »** déclenche la consolidation nocturne (close-day).

➡️ **Guide complet de première session : [`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md)**
(toutes les commandes, gestes, checklist, dépannage).

## 6. Lire ta mémoire — dashboard

Après un close-day, pour voir ce que ta mémoire a produit (hypothèses, Life Model,
prédictions vérifiées, preuves visuelles, routines, sessions) — **en lecture seule** :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1   # → http://localhost:8720
```

## 7. Compiler l'APK soi-même

```powershell
powershell -ExecutionPolicy Bypass -File scripts\BUILD_ANDROID_PLUGINS.ps1   # AAR Kotlin (JDK17 + Gradle 8.7)
$env:MLOMEGA_PC_HOST="<IP-du-PC>"; $env:MLOMEGA_PC_PORT="8710"
& "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe" -batchmode -quit `
  -projectPath apps\xr-mobile -executeMethod MLOmega.XR.Editor.AndroidBuild.BuildApk -logFile -
# → apps\xr-mobile\build\android\mlomega-phoneonly.apk
```

Prérequis build : Android SDK 34 + NDK 23.1.7779620 + CMake 3.22.1 (via `sdkmanager`), JDK 17,
Gradle 8.7 — détails dans `E46D_STATE.md`.

## 8. Dehors (4G/5G)

Le PC reste à la maison derrière la box ; le téléphone le rejoint par un **tunnel Tailscale**
(rien à ouvrir sur Internet). Endpoints essayés dans l'ordre **LAN → Tailscale**, bascule
automatique. Installe Tailscale sur le PC **et** le téléphone (même compte) → guide
[`docs/OUTSIDE_ACCESS.md`](docs/OUTSIDE_ACCESS.md).

## 9. Invariants (non négociables)

- **Mémoire continue** : le wake word gate les commandes, jamais la capture ni l'ingestion.
- **Chaîne de preuve** : frame → observation → preuve → événement → mémoire.
- **Vérité & prudence** : `truth_level` sur toute sortie ; pas de nom sous seuil d'identité ; pas d'assistance de conduite présentée comme sûre.
- **Un seul micro** sur le téléphone (fan-out, jamais un 2ᵉ `AudioRecord`).
- **Local-first** : le cloud est opt-in explicite ; aucun média référencé par une preuve n'est purgé.

## 10. Documentation

- [`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md) — ta première session, pas à pas.
- [`docs/OUTSIDE_ACCESS.md`](docs/OUTSIDE_ACCESS.md) — mode dehors (Tailscale).
- [`docs/EXECUTOR_BUILD_GUIDE.md`](docs/EXECUTOR_BUILD_GUIDE.md) — journal de construction, étape par étape (E1→E55).
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — décisions techniques (ADR).
- [`docs/PROD_BACKLOG.md`](docs/PROD_BACKLOG.md) — ce qui reste / différé / futur.
- `apps/memory-dashboard/README.md` · `E46D_STATE.md` · `docs/EXECUTOR_HANDOFF.md`.

## 11. État (2026-07-09)

**Livré** : pipeline complet capture→compréhension→mémoire→prédiction ; identité visage+voix ;
langage naturel multi-tour ; wake word (mode `open`/`gated`) ; gestes ; sous-titres + **traduction
live offline** ; proactivité ; replay ; mode dehors (Tailscale) ; **téléchargement auto des modèles**
dans l'app ; **cue de changement** (E48-B) ; **dashboard mémoire** (E50) ; **rétention médias + budget
disque 100 Go** et rollups jour/semaine/mois (E54) ; **enregistrement de clips vidéo** pour le replay,
sans jamais ralentir le live (E55). APK v3 : `mlomega-phoneonly.apk` (IL2CPP/ARM64).
Tests : Python + Unity EditMode 59/59 + JVM verts (re-exécutés au fil des étapes).

**En attente de validation** : première **session réelle S25** (installer l'APK v3, une vraie session,
un vrai close-day) — c'est le prochain jalon, tout le reste est prêt pour ça.

**Roadmap** : E49 lunettes XREAL (déposer le SDK) · E51 installateur guidé 2 clics ·
E53 mode aide universel (différé — attend des VLM de pointage spatial fiables) · E55+ clips :
un SSD externe 1 To recommandé pour garder ~8 h/jour de vidéo.
