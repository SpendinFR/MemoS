# EXECUTOR_BUILD_GUIDE — MLOmega V19, construction pas à pas

Complément d'exécution de `docs/EXECUTOR_HANDOFF.md`. Le handoff dit **quoi** construire et pourquoi ; ce guide dit **comment**, étape par étape, avec les signatures réelles du code existant (extraites du dépôt le 2026-07-03 — recopiées, pas paraphrasées). Les références « guide §x » (TTL SceneCache, skills, composants UI, chaînes de scénarios, gates, tests, règles de vérité) résolvent dans `docs/GUIDE_V19_REFERENCE.md`. En cas de divergence entre ce guide et le code réel, **le code réel fait foi** : lire le module, consigner la divergence dans `docs/DECISIONS.md`, continuer.

Conventions : `E<n>` = étape ; chaque étape a Objectif / Créer / Brancher / Valider. Ne pas sauter d'étape. Chemins relatifs à la racine du monorepo V19 ; le cœur = `src/mlomega_audio_elite/`.

---

## E61 — Clôture pré-production (EN COURS — 2026-07-11)

La checklist canonique des **26 corrections finales** et leur découpage E61-A→E se trouvent dans `docs/PROD_BACKLOG.md` §E61. La distribution APK historique devient E61-F. Même discipline que E60 : code réellement appelé, preuve ciblée, documentation mise à jour avant chaque commit, puis gate S25 transversal.

### E61-A — Life Model, prédictions, Self Schema et temps local (code clos)

Le producteur n'est pas un nouveau prompt parallèle : `run_life_model_v19_stage` projette idempotemment les neuf familles du magasin canonique V15.10/V15.13 déjà construit par le stage nocturne `life_model`. Chaque entrée V19 porte table/id/version source et evidence refs ; une base neuve n'attend plus le seed de `synthetic_life`. Les prédictions migrent avec `source_entry_id`. Une réfutation contredit cette entrée précise, jamais une autre ligne partageant le même texte. Le watcher ne crée un label de similarité V18 que si le `verification_spec` fournit une paire anchor/similar explicitement reliée ; sinon l'audit conserve `no_causal_case_pair` sans pollution.

`rebuild_self_schema` supprime les projections sorties du set actif et n'admet un `causal_edge` que si son appartenance owner est prouvée via ses vraies lignes source. Replay, Life Model V19 et horizons de prédiction partent de la journée civile `MLOMEGA_LOCAL_TZ` et interrogent ensuite des bornes UTC semi-ouvertes ; les heures explicites du spec sont enfin consommées. Le manifeste CloseDay vérifie aussi les IDs nouvellement projetés. Des warnings sémantiques signalent désormais des entrées canoniques/éligibles sans sortie V19 et un rollup week/month dû mais absent, sans transformer une journée réellement vide en échec.

Validation ciblée : **29 passed, 1 skipped** (provider TTS local absent), sur `test_e61_memory_integrity`, Life Model V19, replay E35, scénario mémoire E16→E20 et preuve manifeste CloseDay.

### E61-B — Sorties utilisateur PhoneOnly (code clos, validation Unity à relancer)

Replay transporte uniquement des refs bornées. `/replay/media/{kind}/{asset_id}` exige les credentials SessionHub, résout le fichier par le `ReplayService` actif et `UIRuntime` ajoute ces credentials à chaque chargement image/MP4 avant d'alimenter `VirtualScreen.SetSurfaceTexture`. LensWindow réutilise directement la texture adapter et calcule son crop GPU par `RawImage.uvRect` depuis `anchor.center` + `content.zoom` ; la valeur reçue par JSON (`JArray`) et la valeur Reflex locale (`List<object>`) suivent le même lecteur.

Le menu calcule sa ligne réelle par intersection viewport→plan→`RectTransform`. `PanelManipulator` laisse les lignes d'action non réclamées, tout en gardant titre/bords/corners déplaçables. Les actions PC montent par `device_intent` et appellent `IntentRouter.on_device_action`; Replay/Mémoire arment un vrai tour naturel suivant, sans transcript synthétique. Privacy est un état de capture : caméra adapter stoppée, transport WebRTC disposé (micro libéré), ASR/gestes/skills coupés, watchdog PC suspendu ; la reprise reconstruit WebRTC avec les mêmes IDs et un bouton local reste disponible quand les capteurs sont coupés.

Validation : **66 passed, 1 deselected** sur IntentRouter/replay/runtime. Le test cloud réel a été exclu car la clé présente tente le proxy de test fermé `127.0.0.1:9`. Unity CLI n'a pas atteint l'import : licence Hub absente/périmée (`No valid Unity Editor license found`, exit 1). Après reconnexion Hub, relancer uniquement `E33MenuDeviceTests`, puis les builds/gates S25 globaux.

### E61-C — Companion, XREAL produit et reconnexion (code clos)

`delivery_adapter.create_app` sert `apps/companion-web` et possède sa propre boucle de dispatch 500 ms, liée au lifespan. `RUN -LivePhone` démarre ce serveur caché sur 8706, vérifie `/health`, publie son URL et le tue dans le `finally` du SessionHub. Le resolver JS comprend le health E60 et SessionHub autorise uniquement les GET cross-origin nécessaires. Le resolver Python accepte `ready`, `pairing_ready` et `full_ready` tant que le booléen pairing est vrai.

Le build lunettes ne livre plus la scène de gate. `PhoneOnlySceneBuilder.BuildXrealScene` construit `XrealProduct.unity` depuis le même graphe produit, avec config/adaptateur XREAL et sans preview téléphone. Le coordinateur transport accepte tout adapter réel ; les permissions Android sont demandées avant capture XREAL. `AndroidBuildXreal` régénère cette scène, embarque les modèles Reflex, injecte l'endpoint dans `MLOmegaXreal.asset` et sort `mlomega-xreal.apk`. `G1Gate.unity` reste disponible pour isoler Eye/pose/stéréo. Sur le PC, `AiortcIngress.handle_offer_sdp` est protégé par un lock : ancien peer fermé, canaux/PTS remis à zéro, puis seulement nouveau peer installé.

Validation ciblée : **33 passed**, parse PowerShell et py_compile verts. Unity n'est pas relancé car la licence Hub a déjà échoué avant import au lot B ; après reconnexion, exécuter les deux passes XREAL puis les gates matériel.

### E61-D — Atomicité, ownership média et API historique (code clos)

`end_session_only` crée le marqueur durable `phoneonly_session_recovery_v19` alors que la ligne BrainLive est encore active, avant `pipeline.end_session` et `ConversationBridge.end_session`. Un kill après le passage à `ended` laisse donc déjà un job pending que `startup_recovery` sait reprendre. Le CloseDay normal marque ce même job completed/error ; il n'existe plus de fenêtre « ended mais invisible au recovery ».

`vision_frames.person_id` est une migration additive : owner de la session pour l'historique live, `unscoped_legacy` pour les lignes impossibles à attribuer. Les writers core/V19 le remplissent explicitement. Replay filtre et résout par cet owner. `MediaRetention` applique le même filtre aux colonnes de preuve, keyframes, assets clips, FK visuelles, segments/sensor events audio, transcodage et suppressions : le budget est celui du propriétaire demandé, pas celui de toute la base.

`mlomega_audio_elite.api` est une compatibilité V18, pas un serveur V19. Son startup exige maintenant `MLOMEGA_ENABLE_LEGACY_API=1`, son titre/health déclarent la dépréciation et orientent vers SessionHub :8710, dashboard :8720 et CLI. Validation : **65 passed** sur runtime/recovery, replay, rétention, API, VisionRT et nightly E37.

### E61-E — Installation, Doctor et builders hermétiques (code clos)

Le gate nocturne n'est plus une présence de fichier. `scripts/check_close_day_preflight.py`, lancé par Doctor et par le `/ready` profond avec `.venv`, importe la chaîne deep réelle et vérifie token HF, ffmpeg, entrypoint, DB configurée en lecture seule et racine `MLOMEGA_MEDIA` existante/inscriptible. Il ne crée aucun chemin pour rendre son propre test vert. Doctor importe `.env` sans remplacer les variables opérateur, réserve `.venv-live` aux contrats/live et `.venv` aux contrôles mémoire/CloseDay, et n'utilise plus `data/memory.db`/`data/evidence`. Les snippets SQL Windows sont passés avec des guillemets préservés : la table delivery et l'enrôlement owner ne sont plus des WARN vides.

`INSTALL_MLOMEGA_V19_WINDOWS.ps1` conserve `.venv-live.previous` après la bascule. En autonome, seul un `DOCTOR -Full` vert autorise sa suppression et le message final ; en orchestration `-SkipDoctor`, WELCOME en devient le propriétaire. WELCOME résout et valide un Python **3.11 64-bit** avant de créer `.venv`, complète les chemins media/evidence, initialise la DB configurée, restaure le venv précédent sur erreur/FAIL et sort non-zéro. PhoneOnly retire toujours `XREAL_SDK_PRESENT`; XREAL retire toujours `MLOMEGA_PHONE_ONLY`. Validation : parse PowerShell vert, **41 tests ciblés**, préflight réel `ready=true`, `DOCTOR -Full` **0 FAIL / 4 WARN** explicites. Les APK existantes ne sont pas revendiquées comme rebâties par ce lot ; elles restent soumises au gate matériel transversal.

### E61-F — Distribution APK guidée (code/build clos, Release en cours)

`GET_PHONEONLY_APK.ps1` résout la dernière Release `SpendinFR/MemoS`, exige `mlomega-phoneonly.apk` et son sidecar `.sha256`, télécharge vers un nom temporaire et ne remplace la destination qu'après comparaison cryptographique. Une APK locale reste prioritaire ; une absence de réseau sans APK est un FAIL guidé, jamais une fausse installation réussie. `BUILD_XREAL_ASSISTED.ps1` reste strictement local : SDK propriétaire vérifié, Unity 6000.0.23f1, deux passes ordonnées avec `Start-Process -Wait -PassThru`, endpoint choisi injecté, licence/compile différenciées et snapshot/restauration des artefacts Unity. WELCOME choisit automatiquement le bon chemin lorsque l'APK manque et affiche toujours le hash final.

Le premier rebuild E61 a réfuté la compilation présumée verte de Replay : `VideoPlayer`, `UnityWebRequestTexture` et `DownloadHandlerTexture` existaient dans le code mais leurs modules builtin n'étaient pas activés dans le player UI. `com.unity.modules.video`, `com.unity.modules.unitywebrequesttexture` et les références asmdef correspondantes sont désormais explicites. Preuves réelles : PhoneOnly exit 0, **94 759 838 octets**, SHA-256 `C569EE4596B7E47B755FB8AA027E242577F48C140F6EBD1378C84DCE0EFB975B`; XREAL produit deux passes exit 0, SHA-256 `945F5D38AC9E3FB72A905B371A5BF20BA2144672D2AB61111A31EB774D360DDF`; **12 tests distribution/install** verts.

## E63 — Harnais d'intégration bout-en-bout (FAIT — 2026-07-11)

Faux device XR (`tools/harness/`) qui rejoue une session complète contre le vrai code PC en WebRTC réel, sans modifier aucun fichier produit (fichiers neufs uniquement). Toujours lancer avec `.venv-live\Scripts\python` (aiortc/cv2/sherpa). Le serveur produit est démarré sur un **port de test dédié (8730 par défaut)**, jamais 8710/8766, et sa base est une sqlite scratch (`MLOMEGA_DB` → `tools/harness/_run/harness_memory.db`), donc un run ne touche jamais `memory.db`.

Commandes exactes (depuis la racine du repo) :

```
REM Session minimale complète (mp4 synthétique mire+bip, sans close-day) — chemin PASS validé
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --duration 26 --synth-seconds 30

REM Contre un vrai mp4 avec parole (transcripts/turns réels)
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --media chemin\clip.mp4 --duration 40

REM Vraie vidéo de test 5 min alignée sur le scénario dédié + close-day complet (LOURD, GPU)
REM --duration doit dépasser la durée réelle du mp4 (301.6s pour la vidéo WhatsApp de test → 320).
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --media chemin\video5min.mp4 --scenario tools\harness\scenarios\real_video_session.json --duration 320 --with-close-day

REM S'attacher à un serveur déjà lancé (ex. le vrai 8710) au lieu d'en spawner un
.venv-live\Scripts\python tools\harness\run_harness.py --attach --host 127.0.0.1 --port 8710 --db <base-de-ce-serveur>

REM Device seul (serveur déjà up)
.venv-live\Scripts\python tools\harness\fake_xr_device.py --port 8730 --out device_report.json

REM Assertions seules contre une base
.venv-live\Scripts\python tools\harness\assertions.py --db tools\harness\_run\harness_memory.db --json

REM Passe chaos (chaque scénario sur son propre serveur+DB)
.venv-live\Scripts\python tools\harness\chaos.py --port 8742 --scenarios net_drop_reconnect,double_end,ollama_down
.venv-live\Scripts\python tools\harness\chaos.py --port 8746 --scenarios kill_before_close_day --with-recovery-close-day
```

Prérequis mode minimal : `ffmpeg` sur le PATH (mp4 synthétique) ; **pas de GPU/Ollama/Qdrant requis** (`/health` renvoie `ai_ready=false` mais `pairing_ready=true` suffit au pairing/offer, le harnais l'attend). Le close-day complet (`--with-close-day`) est le seul chemin qui exige la chaîne IA + le core `.venv` + GPU.

Résultat exécution réelle : run minimal = **ALL PASS** (session enregistrée+terminée, audio traversé, 1 clip indexé, 8 intents joués) ; chaos `net_drop_reconnect`, `double_end`, `ollama_down` verts. La passe vraie vidéo du 2026-07-12 a ensuite trouvé et corrigé plusieurs défauts que le synthétique court ne voyait pas : callback DataChannel bloquant la boucle aiortc au premier transcript, connexions SQLite AttributeMemory/HypothesisEngine utilisées cross-thread, faux succès de fermeture avant drain et recovery incapable de reprendre un run `blocked`. Après correction, les **301 s** du MP4 traversent WebRTC avec **14 857 chunks audio** et 2 tours. Tests ciblés : **31 passés**.

État précis du passage nocturne réel (2026-07-12) : le scope gated du token HF a été corrigé et les modèles Pyannote sont provisionnés. Les gaps Windows CUDA/SpeechBrain, transaction vocale SQLite, mot WhisperX non aligné et owner Brain2 explicite sont corrigés. Preuve réelle Deep Audio : **40 tours**, WhisperX `large-v3` CUDA float16, alignement, Pyannote diarization=true et SpeechBrain ECAPA actifs ; le stage Deep Audio est `completed` sans erreur.

Le verdict `--with-close-day` complet reste **OUVERT au stage Brain2**. L'export raffiné contient 40 tours audio et 945 pseudo-tours visuels frame-par-frame (985 entrées, prompt 1,6 M caractères). Qwen termine par `finish_reason=length`. Aucun plafonnement destructif n'est conservé : les essais max-6/échantillonnage ont été retirés. Avant toute nouvelle relance, définir une orchestration nocturne lossless par fenêtres de 40–50 preuves, checkpoints, fusion de frontières et vérification de couverture, puis l'appliquer transversalement aux stages LLM. La base `.mlomega_audio_elite/memory.db` contient les données de ce run de test et un CloseDay `blocked` ; l'utilisateur prévoit de la vider. Dashboard non lancé tant que la chaîne n'est pas verte. Handoff exhaustif : `tools/harness/BUGS_FOUND.md` OBS-8 à OBS-13.

### E64-F — rectification Codex et état du run réel (2026-07-12)

Le premier câblage F contournait l'exécuteur E64-C malgré un planificateur visible. Il est corrigé : EpisodeBuilder passe par `run_windows` + `OllamaWindowLLM`, committe checkpoints/outputs validés, subdivise `truncated_output`, reprend par digest de contenu et relit la couverture depuis la vraie table. Le manifeste développe les atomes vision jusqu'aux 945 observations sources ; la fixture 40+945 prouve 985 refs. Fusion de frontière partielle par clé structurelle + preuve commune, aucune dédup texte. **60 tests E64 + 13 régressions = 73 verts.** Détails ADR E64-F rectifié.

La tentative réelle suivante a traversé les 301 s de média (**15 077 chunks, 30 tours, 3 clips**) mais a échoué AVANT CloseDay : `/session/end` timeout, BrainLive encore `active`, aucune table `night_llm_*`. L'attente totale d'environ 40 min inclut 30 min de polling harnais inutile sur `close_day=not_started`; elle ne constitue pas encore une mesure de performance nocturne. Conserver `tools/harness/_run/harness_memory.db`, diagnostiquer la phase exacte du drain, puis lancer la startup recovery sur cette même DB — ne pas rejouer la vidéo. Dashboard seulement après checkpoints/manifeste réels verts. OBS-14.

La recovery a ensuite atteint EpisodeBuilder réel et validé cinq fenêtres, mais l'inspection en cours de run a empêché un second faux test long : l'export raffiné avait 1 433 tours, car 709 `vision_frames` brutes alternaient avec 698 observations et cassaient toutes les plages. Correctif E64-B/F : raw frame rattachée comme preuve temporelle, seules les observations sémantiques définissent l'état. Mesure réelle après ré-export : **1 407 refs → 132 atomes → 162 tours avec les 30 tours audio**, sans perte. `real_video_session.json`/ASR VIKI inchangé. L'artifact Deep Audio dépend désormais aussi du digest de ce contexte, donc l'ancien raffinement ne peut pas être repris silencieusement. OBS-15.

**À clore avant FirstTry utilisateur (E64-F0).** Le test a révélé deux différences d'environnement qu'un opérateur ne doit jamais découvrir après capture : faux proxy `127.0.0.1:9` transmis à Hugging Face, et commande Deep Audio directe sans les chemins cuDNN (`cudnn_ops_infer64_8.dll`) pourtant préparés par le vrai entrypoint CloseDay. `RUN_MLOMEGA_V19.ps1`/Doctor/readiness doivent partager un bootstrap unique avec les subprocess et bloquer avant SessionHub si proxy HF, scope/cache gated ou chargement CUDA/cuDNN réel échoue. Suivi non coché dans `PROD_BACKLOG` ; rappel ajouté à `FIRST_TRY_ANDROID.md`.

La recovery a ensuite révélé et corrigé une collision de ré-export : une conversation base neuve et un ancien export Deep Audio pouvaient rester tous deux `exported`, ce qui provoquait `assembly/export cardinality mismatch`. L'assembleur supersède désormais toutes les anciennes lignes actives avant la nouvelle activation, désactive leurs scopes et invalide leurs descendants ; l'historique reste conservé. Test E37 dédié vert.

**EpisodeBuilder v4 — mesure réelle, pas une réduction de fonctionnalité.** Le payload avait 130 806 tokens pour 158 tours car un même mot WhisperX figurait dans `turn.text`, `source.words` et `whisperx_segment.words`, et une scène figurait dans le texte puis dans `representative`. La projection LLM conserve le texte exact (donc aussi les répétitions réellement prononcées), locuteur/personne, bornes, objets/actions/OCR, qualité d'alignement et un digest ; les tableaux bruts restent dans la DB et dans le manifeste. Résultat : 68 343 tokens (-47,8 %), 1 407 refs vision toujours couvertes. Un vrai JSON Schema Ollama borne la forme, extrait les preuves `{turn_id,text}` vers l'ID durable et rejette les épisodes sans preuve primaire. Chaque appel lit deux tours de contexte précédent mais ne produit que pour deux tours primaires. Mesure `qwen3.5:9b`, phase post-stop/16k : 68,8 s à froid puis 8,7 s à chaud, `finish=stop`, épisodes cohérents ; les essais accidentels `qwen3.5:4b`/4k sont invalides pour la performance nocturne et explicitement exclus. **53 tests ciblés verts.** Le CloseDay complet et le dashboard restent ouverts.

**Reprise EpisodeBuilder validée, V13 aval encore ouvert.** Les 79 fenêtres v4 ont toutes fini au premier essai. Un bug de versionnement chargeait aussi les outputs v2 du même `stage_name`; merge et couverture sont maintenant filtrés par les clés feuilles exactes du run courant. Manifeste relu : 1 433 attendues, 26 audio couvertes, 1 407 vision représentées, zéro missing/quarantaine. Le premier writer aval a ensuite prouvé une autre frontière LLM : `capture_engine` avait inventé un `turn_id` et cassait la FK. Toutes les FK pilotées par les payloads V13 sont vérifiées contre leurs parents ; les 16 moteurs sont commit/repris individuellement par hash de prompt. **57 tests ciblés verts.** Volume mesuré : 19 épisodes × 16 = 304 appels ; ne pas supprimer de passes sans arbitrage, mais mesurer le débit avant certification.

**Verdict performance V13 : non viable en l'état.** Le découpage générique du schéma `internal_state_engine` (10 champs→4 tâches, fusion 10/10) élimine `finish=length`, et la projection prompt ramène 13 665→7 038 tokens sans retirer preuves/détails durables. Mesure réelle 9B : 195,8 s pour ce seul moteur/épisode. Les 304 appels V13 de la fixture précèdent encore Life Model/longitudinal. Ne pas lancer aveuglément le CloseDay complet : migrer vers moteur→batches d'épisodes token-aware et une applicabilité explicite (les épisodes capteur restent Vision/WorldBrain, pas psychologie), puis re-mesurer.

### E64-F — passation exécutable après refonte Codex (PAUSE 2026-07-13)

Le diagnostic « 304 appels » a été traité sans supprimer les moteurs. EpisodeBuilder v5 route 132 atomes capteur vers Vision/WorldBrain/Silent Life et conserve 12 épisodes humains. V13 exécute maintenant un pack par épisode : le bundle est sérialisé une fois, chaque moteur garde son schéma/writer, et les groupes de champs deviennent les seules unités de subdivision. Applicabilité : capture/language/context/causality pour tout épisode humain ; internal/social/contradiction/choice/outcome seulement sur les types/participants compatibles ; les six moteurs globaux restent conversation-scopés.

La projection LLM ne contient plus les copies techniques WhisperX/vision. Les données brutes et refs restent en DB/manifeste ; texte, temps, speaker/person, alignement, segmentation, objets/actions/OCR restent au prompt. Mesure du cas difficile : 6 836→5 128 tokens, 104,1→28,75 s en Qwen3.5:9b/16k, six moteurs et huit groupes complets. Les 12 packs locaux ont été `completed`; un seul `finish=length` a été résolu par deux enfants sans partiel.

Corrections de reprise indispensables déjà en code :

1. `run_windows` inclut le digest de la requête rendue complète dans sa clé ; une modification du contexte commun ne reprend plus une sortie ancienne.
2. Les fonctions V13 forcent `phase("post_stop_brain2_v13")`; un appel direct ne tombe plus silencieusement sur 4B/4k.
3. `_stable_episode_source_bundle` exclut les lignes dérivées déjà matérialisées ; les sorties antérieures passent seulement par `prior_engine_outputs`. Une reprise ne peut plus se nourrir de ses propres writers.
4. `hierarchical_json.py` fenêtre des capsules d'épisodes et garde leur couverture transitive. `length` sur preuve subdivise les capsules ; `length` sur merge remonte au caller, qui sépare les groupes de schémas. Une fusion sans progrès bloque immédiatement.
5. La relecture reste filtrée par les `window_key` exactes. Ne jamais agréger par `stage_name` seul.

**Commande de reprise conseillée (depuis `Mlomega-main`, une seule instance) :** utiliser le même entrypoint/harness CloseDay en phase post-stop, avec `MLOMEGA_DB=tools/harness/_run/harness_memory.db`, `MLOMEGA_OLLAMA_MODEL=qwen3.5:9b`, contexte post-stop 16 384 et sortie 4 096. Avant : `Get-Process python` doit être vide. Pendant : ne pas interrompre le wrapper sans tuer aussi son enfant Python. Après : relancer exactement V13 et prouver zéro nouvel appel/checkpoint/matérialisation.

**État exact à la pause :** 43 tests centraux verts, puis **98 tests élargis passés** (E64 A–F, E37, budget Ollama, longitudinal et multi-session CloseDay ; 2 warnings SWIG seulement) + `py_compile` des modules V13/projection/executor/hierarchy. La première fenêtre globale réelle (10 capsules, 10 463 tokens) est verte. La fusion combinée a atteint `length`; le fallback par groupes de schémas est testé avec faux LLM, mais pas encore validé jusqu'au manifeste réel. Les trois anciens Python orphelins ont été arrêtés. Le dernier `profiles[...] is None` était un `return` déplacé lors de l'ajout du bundle stable ; corrigé et couvert par test, pas rejoué en réel.

**Ne pas faire :** ne pas rejouer la vidéo, ne pas réduire le nombre de moteurs/épisodes, ne pas échantillonner les preuves, ne pas accepter un dashboard partiel, ne pas utiliser les timings 01:24–01:52 comme benchmark (runners concurrents). Reprendre la DB pour la correction fonctionnelle ; faire ensuite une exécution fraîche séparée pour la performance.

**Suite obligatoire :** global V13 12/12 + six moteurs + couverture verte → rerun idempotent zéro appel → V14/Silent Life → coordination/Life Model/longitudinal/live-ready → CloseDay complet → dashboard. Le détail case par case et les métriques sont dans `PROD_BACKLOG` §E64-F « checkpoint de pause Codex » ; bugs dans `tools/harness/BUGS_FOUND.md` OBS-20 à OBS-24.

## E60 — Corrections d'intégration pré-production (EN COURS — 2026-07-10)

La checklist canonique des **32 corrections** se trouve dans `docs/PROD_BACKLOG.md` §E60. Une case y représente la correction code/test ciblé ; la matrice S25 reste un gate transversal unique. Exécution imposée : petit lot cohérent → appel produit prouvé → tests ciblés du bon arbre → mise à jour simultanée du guide et du backlog → commit.

Décision utilisateur E60 : le pairing initial **reste sans secret préalable** (réseau personnel LAN/Tailscale + token de session). Aucun durcissement par code/PIN n'est à implémenter dans ce lot.

### E60 — Lot Android A (code clos, validation Unity verte, rebuild APK ouvert)

Le runtime PhoneOnly possède désormais un producteur réel de signaux baseline (`PhoneOnlyReflexSignalSource`) : ASR/wake/subtitle et détection gestes sont chauffés pendant `XrSessionState.Running`, puis restent soumis au scheduler/budget. Le builder instancie aussi le menu réel sur un GameObject enfant (pour que sa fermeture ne désactive jamais la racine), son contrôleur geste/commande, sa surface `GlassPanel` manipulable et `OrientationGuard`. `AndroidBuild` force `com.mlomega.xr.phoneonly`, `runInBackground`, et régénère systématiquement la scène au lieu de réutiliser un YAML ancien. `PhoneOnlySessionCoordinator` conserve une URL immuable pour end/status, refuse proprement une clôture sans endpoint et tient `NeverSleep` seulement pendant Running/Suspended.

Validation : compilation Roslyn directe des `.rsp` Unity dans l'ordre Transport → UI → Reflex → Editor → Tests, **tous OK** ; tests E60 ajoutés pour les baselines ASR/gestures et la vraie surface menu. Après rafraîchissement de la licence Personal via Unity Hub, le runner réel termine à **80/80 EditMode**. Le menu a ensuite reçu halo/rim, ombre et snap doux, validés dans le lot G. Les lignes de bruit ULF/licensing ne sont pas utilisées comme verdict : fin de processus et XML NUnit le sont. Régénération scène/APK reste à faire ; S25 demeure le gate produit transversal.

### E60 — Lot audio B (code clos, validation device au gate transversal)

`PhoneOnlyRuntime` construit désormais TTS et pousse le wake word dès l'ouverture du DataChannel. La commande porte un ID ; Unity renvoie `device_command_result` et le PC ne marque le mot livré qu'après ack positif. Le gating route le `device_transcript` exact et dédupliqué, jamais le tour PC suivant. `TtsAudioPlayer` décode uniquement RIFF PCM16 borné et joue via `AudioSource`. `AsrBridge` choisit `ownMicrophone=true` hors transport, redémarre proprement vers le fan-out WebRTC connecté, conserve son sink et appelle `DetachPcmFeed` avant libération.

Preuves : `test_wake_word_gating.py` + `test_e35_outputs.py` = **26 passed** ; build Gradle complet réussi et `mlomega-reflexvision.aar` reconstruit ; compilation Roslyn des assemblies Editor et Android réussie ; suite Unity globale **80/80 EditMode**. L'AAR ONNX retouché mécaniquement par le build a été restauré et n'entre pas dans le commit. Lecture audio, switch micro et reconnexion/ack appartiennent maintenant à la matrice S25 globale, pas à des cases code artificiellement ouvertes.

### E60 — Lot PC live C (raccords critiques branchés, charge/GPU partiels)

`PhoneOnlyRuntime` ouvre d'abord la session BrainLive, construit `ClipRecorder` avec cet ID durable, le passe au vrai `AiortcIngress` et le stoppe avant toute lecture CloseDay. Le RTP audio conserve désormais une fenêtre UTC issue de PTS/time_base (ré-ancrage à chaque track/reconnexion), avec fallback horloge explicitement marqué ; AudioRT la propage aux archives et aux tours BrainLive. La file PCM passe de 32 chunks (~0,6 s) à 3000 (~60 s, profondeur/pic/drops métrés) et les traitements IntentRouter/identité/BrainLive/LLM sont déportés dans un worker sémantique ordonné et borné. Les échecs BrainLive sont retentés trois fois puis visibles dans `pipeline_recent_errors`/statut runtime ; WorldBrain et AudioArchive remontent aussi leurs erreurs. Les `seg_*.wav` ne sont plus créés pour l'archive seule et les temporaires identité/setup sont supprimés après usage.

La vision synchrone (détecteur, tracker, WorldBrain, keyframes) est attendue via `asyncio.to_thread` derrière la file latest=1, donc signaling/FastAPI restent sur l'event loop. `LiveDiscourse.close()` ne retourne plus avant drain + barrière + `join` ; un timeout échoue la fin de session et bloque CloseDay. `GpuArbiter` est maintenant construit en produit, protège tracker/détecteur/ASR même sans NVML, et alimente périodiquement `update_degraded` avec les drops de la fenêtre courante. Le provider CUDA réel, initialement non disponible, est corrigé et validé dans le lot D ci-dessous.

Preuves : suites ciblées distinctes **50 passed**, puis SessionHub/WebRTC/E27/E31/multi-session **24 passed, 1 skipped** (Ollama réel opt-in). Nouveaux tests : recorder injecté dans l'ingress puis fermé, PTS espacé conservé et callback timing, timestamp AudioRT→BrainLive, worker sémantique non bloquant, retry/erreur observable, WAV temporaire supprimé, vision hors thread asyncio et LiveDiscourse joint. Le code de la case 16 est clos ; sa mesure longue de drops appartient au gate S25. Les anciens constats 19/20 sont clos par le lot suivant.

### E60 — Lot durabilité/GPU D (raccords et environnement réels validés)

Le manager PhoneOnly ne déduit plus `allow_rerun` d'un compteur de processus : avant chaque nouvelle session il lit la ligne durable `v18_close_day_runs` du propriétaire et de la journée locale. Un test crée un manager neuf après un CloseDay `completed` et vérifie que `--allow-rerun` sera armé. Le contrat `FrameEnvelope` porte maintenant `pose_valid` depuis le schéma JSON source jusqu'au C# généré et à sa copie Newtonsoft Unity ; `EyeCaptureSource` affecte `StampedPose.IsTracking`, donc la caméra PhoneOnly (untracked) n'alimente jamais la qualité SpatialRT avec `(0,0,0)`.

L'environnement GPU a été validé par création de session, pas par nom de provider. ORT GPU 1.27 listait CUDA mais exigeait réellement CUDA13 et retombait CPU ; l'installateur épingle désormais **onnxruntime-gpu 1.22.0** compatible CUDA12/cuDNN9, ajoute `nvidia-cuda-runtime-cu12` + `nvidia-cufft-cu12` aux dépendances déjà présentes, restaure le wheel GPU après le conflit de dépendance RapidOCR, et VisionRT précharge les DLL NVIDIA du venv. Le Doctor échoue désormais si une vraie `InferenceSession` YOLOX ne conserve pas `CUDAExecutionProvider`. Résultat sur la machine cible : `['CUDAExecutionProvider','CPUExecutionProvider']`, `on_gpu=True`.

Enfin, les frontières d'écriture live ne sont plus silencieuses : retry BrainLive, WorldBrain, spatial, keyframes, AudioArchive, attributs/hypothèses, change-attention/routines et callbacks visuels alimentent tous le compteur et `pipeline_recent_errors`; une erreur keyframe est testée explicitement. Validation : pytest ciblé **51 passed**, Unity batchmode **80/80 EditMode**, scripts PowerShell parsés, Doctor Vision **0 FAIL, 2 WARN** (Ollama/Qdrant non démarrés). Ces deux WARN alimentent le prochain lot readiness ; ils ne sont pas présentés comme un état production prêt.

### E60 — Lot recovery/readiness E (fermeture de secours et faux-ready supprimés)

`AiortcIngress` expose l'âge de la dernière frame audio/vidéo. Le manager ferme puis lance CloseDay après une inactivité média bornée (5 min par défaut) et le lifespan FastAPI effectue le même drain au shutdown normal. Pour le kill brutal, le démarrage inscrit chaque ancienne session `brainlive_sessions(active, live_xr)` dans la table de service `phoneonly_session_recovery_v19`, la marque ended, puis reprend CloseDay. L'état pending/error est durable : si le processus retombe entre end et nuit, le démarrage suivant reprend la même ligne ; si le manifeste CloseDay couvre déjà ce `live_session_id`, il ne relance pas. Une recovery running/error refuse la création du runtime WebRTC. Tests : échec nuit simulé → marker error/attempt=1 → nouveau processus → completed/attempt=2 ; watchdog inactif → end+CloseDay une seule fois.

La santé a trois contrats distincts : `/live` prouve seulement le processus, `/health` retourne 200 lorsque le transport peut pairer et expose `pairing_ready`, `ai_ready`, recovery et chaque check, tandis que `/ready` exige toute la chaîne et retourne 503 sinon. Le probe profond s'exécute hors event loop après la recovery et vérifie DB, `.venv` nocturne, modèles device, ffmpeg, disque, vraie session YOLOX CUDA, chargement Whisper `small` sur CUDA, synthèse TTS, Ollama et Qdrant. `RUN_MLOMEGA_V19.ps1 -LivePhone` exécute le même gate avant de démarrer le serveur et donne les commandes correctives au lieu d'annoncer FirstTry prêt.

Validation : suites ciblées **39 passed**, puis rerun lifespan/readiness **29 passed**. Preflight profond réel : DB, venv nuit, 12 modèles device, ffmpeg, disque, YOLOX CUDA, Whisper CUDA et TTS sherpa verts ; sortie non-zéro attendue pour `ollama,qdrant` actuellement arrêtés. Ce refus est le comportement correct. `FIRST_TRY_ANDROID.md` documente désormais `/health` vs `/ready` et le redémarrage des deux services.

### E60 — Lot durabilité nocturne F (identité, temps et preuves réelles)

`WorldBrain` installe un registre owner-scoped `worldbrain_entity_registry_v19`. Un tracker reste propre à sa session, tandis que l'entité promue reçoit un ID stable indépendant du transport ; un objet unique type+label est repris à la session suivante et plusieurs objets homonymes occupent des slots distincts, réassociés prudemment par bbox. Il ne s'agit pas d'une fausse promesse de ré-identification biométrique : l'heuristique ne dépasse jamais les signaux réellement disponibles au détecteur.

`v19_visual_consolidation` calcule la fenêtre semi-ouverte de la journée civile dans `MLOMEGA_LOCAL_TZ` (`Europe/Paris` par défaut), puis la convertit en UTC pour les requêtes. Le créneau night/morning/afternoon/evening est lui aussi calculé après conversion locale ; les tests couvrent les deux instants de bord à minuit et le décalage été.

Le manifeste CloseDay n'utilise plus `observed=list(expected)`. L'attendu contient les dix markers statiques et tous les IDs annoncés ; l'observé est reconstruit en relisant `v18_pipeline_stages`, en validant le statut sémantique, puis en cherchant chaque ID dans sa table réelle avec le même `person_id`. Une ligne absente laisse le manifeste incomplet et interdit le cleanup. Enfin, clip tiering et MediaRetention restent best-effort après un CloseDay valide, mais leur rapport est persisté dans `phoneonly_close_day_maintenance_v19` et remonte au runtime (`close_day_maintenance=completed|warning|error`) au lieu de disparaître avec le subprocess.

Validation : **25/25** tests cœur/durabilité dans `.venv` et **41/41** tests runtime/SessionHub dans `.venv-live`. La preuve négative couvre explicitement le cas « stage retourne un summary_id mais aucune ligne n'existe » : le manifeste refuse l'observé jusqu'à insertion réelle. E60-30 est clos côté code ; la preuve téléphone→Live→BrainLive→CloseDay reste dans le gate S25 transversal.

### E60 — Lot raccord E53/menu G (contrat produit aligné)

`PhoneOnlyRuntime` active maintenant HelpTaskEngine. Le panneau passe par H1 en conservant `task_panel`, le contenu structuré attendu par Unity et un `ui_intent_id` stable ; un enqueue réussi n'est plus doublé par un push direct. Les ancres utilisent le vrai renderer UIIntent, pas un message hot sans consommateur, et gardent un ID stable entre le préchargement ghost et leur promotion current. Les gestes inter-objets transportent les tracks source/cible ; Unity les résout dans SceneCache, préconstruit les ghosts invisibles puis les rend visibles lors du refresh. `UIIntentBroker` retransmet les refreshs même-ID à UIRuntime. La reprise Help persiste dans la base produit avec accès multi-thread et est réémise à la reconnexion DataChannel.

Le mode reste naturel : la grammaire reconnaît seulement « mode aide » et les contrôles de navigation. La description libre suivante — tâche complète, blocage en cours ou action unique — est envoyée telle quelle au LLM, enrichie une seule fois du contexte visuel ; aucun plan « un/deux » ni tâche générique n'existe en production. Le prompt interdit explicitement de recommencer depuis le début lorsque l'utilisateur décrit un blocage en cours. Le `MenuPanel` construit en scène est réellement manipulable ; le feedback de prise associe rim/halo, ombre et légère élévation, puis la libération effectue un snap doux face caméra sur grille locale.

Preuves : **50/50** tests Python ciblés (`help_mode`, DeliveryAdapter H1, runtime PhoneOnly) et **22/22** Unity EditMode (`PanelManipulation`, `TaskAtomsComposition`, refresh broker), exit Unity 0 et XML NUnit `Passed`.

---

## E39 - Invariant temporel V18 `turns` restaure (2026-07-06)

**[x] Fait et teste.** Le schema reel est l'autorite : `turns` ne possede ni `created_at` ni `absolute_start`. Le registre conversationnel de `v18_life_model.py` utilise desormais uniquement `start_s`, le seul offset temporel stocke sur un tour. `tests/v19/test_v18_turn_schema_invariant.py` verrouille le schema et la declaration source. Le bootstrap post-stop deja present dans le diff de `v18_close_day.py` reste separe de E39 et n'est pas revendique comme changement PhoneOnly.

## E40 - Identifiant BrainLive unique (2026-07-06)

**[x] Fait et teste.** `LivePipeline` distingue maintenant `session_id` transport et `live_session_id` BrainLive. ConversationBridge est ouvert ou lie avant WorldBrain ; WorldBrain, SceneAdapter, MorningBriefing, ReplayService, AudioArchive et les keyframes PhoneOnly recoivent tous le meme identifiant BrainLive. Une divergence explicite entre bridge et pipeline echoue immediatement. Validation : 23 tests E27/E28/E31/PhoneOnly verts, dont un test qui inspecte chaque writer durable.

## E41 - Arret atomique, drain et liberation live (2026-07-06)

**[x] Fait et teste sur PC.** La fin explicite gele d'abord l'ingress et ferme les peers producteurs, attend `Queue.join()` et le callback audio en vol, execute `AudioRT.flush()` par le meme chemin de finals, ferme le transport/video task, puis termine WorldBrain et ConversationBridge en mode strict. Les references ASR/traduction/detecteur et les caches live du coeur sont liberees avant CloseDay. Chaque segment VAD appelle l'archive meme si ASR est refuse, indisponible, vide ou leve une erreur. Test d'ordre : `audio_done -> flush -> pipeline_end`; 8 tests PhoneOnly verts. La suite AudioRT modele reel reste une validation E46 car CUDA est incomplet sur cette machine.

## E42 - PCM Opus et frontiere event-loop (2026-07-06)

**[x] Fait et teste sur PC.** Le gateway convertit explicitement les `AudioFrame` PyAV packed ou planar selon `frame.format.is_planar` et le nombre de canaux. Le cas aiortc reel `s16/stereo` packed `(1, 960)` produit 480 echantillons mono `int16` correctement downmixes, sans promotion float non normalisee. Les envois DataChannel demandes depuis le worker ASR sont replanifies par `loop.call_soon_threadsafe` sur l'event loop aiortc et ne retirent plus le canal. Validation : 13 tests PhoneOnly/WebRTC verts avec frame PyAV reelle et assertion du thread d'envoi.

## E43 - End-session et CloseDay asynchrone reprise-safe (2026-07-06)

**[x] Fait et teste sur PC.** `POST /session/end` execute uniquement la barriere de fin, puis demarre un job CloseDay sans garder la requete Android ouverte pendant les phases lourdes. `POST /session/status` expose l'etat authentifie ; `POST /session/close-day` relance idempotemment un job echoue. Un seul task CloseDay existe par session. En production le job est lance par `.venv/Scripts/python.exe` via `run_phoneonly_close_day.py`; la reprise durable reste celle du coeur (`v18_pipeline_stages`, lease et idempotency close-day). `-PersonId` est transmis au serveur et `.env` est charge par le launcher. La politique mono-session refuse tout autre session_id jusqu'au redemarrage operateur, evitant un second CloseDay du meme jour. Validation HTTP/runtime : 17 tests verts.

## E44 - Pont Android transport complet en source (2026-07-06)

**[x] Source branchee, compilation reservee E46.** Unity envoie le `FrameEnvelope` JSON avant chaque frame. Le chemin PhoneOnly par defaut est un fallback CPU I420 fonctionnel et borne par la cadence, sans supposer un partage EGL avec Unity ; le chemin texture optionnel est poste sur le handler GL libwebrtc. Kotlin attend ICE gathering pour le signaling non-trickle, teardown le peer avant reconnexion, ferme synchronement avant dispose et accepte les credentials/endpoint renouveles. SessionPairing re-resout LAN/tunnel apres echec clock-sync. Le manifeste autorise explicitement le HTTP LAN de maintenance. `BUILD_ANDROID_PLUGINS.ps1` compile/teste/exporte les AAR et leurs dependances runtime vers Unity ; PhoneOnly ouvre sans tarball XREAL proprietaire. Validation statique + runtime PC : 13 tests verts. Aucun AAR n'est revendique construit avant E46.

## E45 - Scene PhoneOnly distincte du gate G1 (2026-07-06)

**[x] Fait en source.** `G1SceneBuilder` est revenu a la scene gate XREAL sans config ni coordinateur PhoneOnly forces. `PhoneOnlySceneBuilder` cree separement `Assets/Scenes/PhoneOnly.unity` et `MLOmegaPhoneOnly.asset`, avec PermissionGate, adapter PhoneOnly, pairing, pose/capture, transport et action de fin. Le profil PhoneOnly est place en tete des Build Settings uniquement par son propre menu. Validation statique : 5 tests, dont absence de `PhoneOnlySessionCoordinator` dans G1.

## E46 - Validation finale et compilation (EN COURS - 2026-07-06)

**PC valide.** Suite V18 complete contre `src/` racine : **110 passed**. Suite V19 large sans le test ASR CPU de plus de 5 minutes et sans le scenario LLM reel non deterministe : **190 passed, 1 skipped, 1 deselected**. Les 2 tests E31 concernes repassent en mode degrade Ollama-off. `python-multipart` et `python-dotenv` ont ete ajoutes a l'environnement et a l'installateur ; AudioRT bascule CUDA vers CPU si cuBLAS manque. Syntaxes Python/PowerShell/JSON et `git diff --check` sont valides.

**E46-A GPU/ASR/Ollama/CloseDay valide sur PC.** Les DLL CUDA 12 et cuDNN 9 sont installees dans `.venv-live` et chargees explicitement par AudioRT. Les WAV de test durent 4,525 s et 4,890 s ; faster-whisper `small` reste sur `device=cuda`, inference mesuree 0,34 s apres chargement, suite AudioRT 5/5 en 7,30 s. Argos n'est plus sur le chemin PhoneOnly PC par defaut : le PC transcrit pour BrainLive/archive ; Android sherpa produit le sous-titre reflexe. Le moteur de traduction Android n'existe pas encore et reste un lien Unity/XR a construire.

Ollama a ete mis a jour de 0.15.2 a 0.31.1. Les modeles officiels `qwen3.5:4b` (live) et `qwen3.5:9b` (deep) sont installes. Le 4B resident est 100 % GPU ; le contrat BrainLive reel passe en 8,66 s. Le 9B deep occupe 5,6 Go, 100 % GPU ; chargement froid 63,2 s, petite generation chaude 0,22 s. Ollama reste resident pendant une phase et n'est libere qu'a la frontiere CloseDay. Les sorties structurees utilisent `think:false`, un vrai JSON Schema, des champs facultatifs normalises localement et aucun fragment tronque n'est applique. Tests E31 : 3 deterministes en 7,16 s ; integration reelle explicite 1/1 en 8,99 s.

Le CloseDay durable `run_v18_bbb49c10275b436580dd2fdbb91b9138` a ete repris sans purge. Les causes successives ont ete corrigees factuellement : budget deep distinct, phase 9B conservee entre stages, abstention sans preuve proprietaire, bootstrap de `brainlive_personal_model_exports`. Verdict final : `completed`, `cleanup.eligible=true`, dix stages observes/attendus identiques. Preuve concise : `E46_close_day_completed.json`. L'ancien `E46_close_day_summary.json` reste l'historique du premier verdict blocked, pas l'etat final.

**Compilation Android non encore executee.** L'utilisateur a autorise l'installation de JDK 17, Gradle, Android SDK/adb et Unity. Aucun AAR/APK ni validation materielle n'est encore revendique ; la compilation vient apres les audits readiness/TTL/failover et dependances transversales.

**E46-B readiness/failover/tokens valide sur PC.** L'ancien constat d'URL statique est obsolete : `LiveTransportBridge.StartAndroid` et `RefreshCredentials` construisent `/webrtc/offer` depuis `SessionPairing.ActiveBaseUrl`, donc un pairing Tailscale n'offre plus vers l'IP LAN. `/live` est maintenant la liveness simple ; `/health` est la readiness PhoneOnly et renvoie 503 si signaling aiortc ou runtime/ingress manque. Android ne selectionne donc plus un serveur incapable de negocier WebRTC. Les tokens ont un TTL serveur de 600 s, rotation atomique et `expires_at_utc`; apres expiration toutes les routes renvoient 401. Seul `/session/renew` accepte l'ancien token pendant une grace bornee de reprise reseau, puis session/token sont purges. Validation : 35 tests SessionHub/HTTP/failover/runtime verts.

## 1. Les deux chaînes existantes (à connaître par cœur avant de coder)

### 1.1 Chaîne live de delivery (existante, à réutiliser telle quelle)

```
candidat d'intervention (H1)
  → v18_delivery.enqueue_delivery(...)        # point d'entrée UNIQUE, dédup + cooldown
  → table brainlive_intervention_delivery_queue (delivery_status='queued')
  → [V19 : delivery_adapter la consomme et pousse vers les renderers]
  → v18_8_live_policy.record_delivery_feedback(...)     # delivered/displayed/seen/acted/dismissed/ignored/failed
  → v18_8_live_policy.materialize_intervention_outcome_observation(...)  # réconciliation Brain2
```

### 1.2 Chaîne nocturne (existante — noms de stage réels du close-day)

```
close_brainlive_day(person_id=..., ...)          # v18_close_day.py
  stage "post_stop"      → run_brainlive_post_stop_deep_flow :
       assembly    → brainlive_event_assembler_v15_14.run_brainlive_event_assembly
                     (timeline brute multi-capteurs → bundles brainlive_event_bundles_v1514,
                      plafond 25 min via MLOMEGA_BRAINLIVE_MAX_BUNDLE_MINUTES)
       deep_audio  → brainlive_offline_deep_audio_v18_5.run_offline_deep_audio_for_bundles
                     (précédé de release_live_model_caches())
       deep_vision → brainlive_offline_deep_vision_v16_1.run_offline_deep_vision_for_bundles
                     (≤12 keyframes/bundle depuis vision_timeline_json, VLM par keyframe,
                      sortie brainlive_deep_vision_observations_v161, le tout sous
                      gpu_phase("post_stop_deep_vision", release_before=True, release_after=True))
  stage "longitudinal"   → brain2_longitudinal_cases_v17.run_longitudinal_consolidation
  stage "coordination"   → brainlive_brain2_coordination_v15_12.run_brainlive_brain2_coordination
  stage "life_model"     → brain2_life_model_updater_v15_13.run_brain2_life_model_update
  stage "live_ready"     → brainlive_personal_model_v15_9.build_brain2_live_personal_model
  puis record_output_manifest + assert_cleanup_eligible(required_stages=[les 5 ci-dessus])
```

Checkpoints/reprise : table générique `v18_pipeline_stages` (une ligne par `(run_id, stage_name)`, status ∈ running/completed/failed/retryable_error/skipped) + `v18_close_day_runs` (unique `(person_id, package_date)`). `_run_stage()` saute un stage déjà `completed`.

### 1.3 Comment la vidéo du jour est consolidée la nuit en V19 (décision de conception)

La nuit ne « regarde » **jamais** la vidéo image par image. Ce qui entre dans la consolidation nocturne est déjà curé pendant le jour :

1. **Keyframes** : le sélecteur de keyframes du PC (score de changement de scène, handoff §3.6) enregistre chaque keyframe retenue comme ligne `vision_frames` (`insert_only`, table immuable) avec `capture_mode='xr_keyframe'`, `live_session_id`, `image_path`, `image_sha256` + une ligne `raw_assets` pour le fichier. **Conséquence clé : l'assembleur de bundles et le deep vision existants les prennent en charge sans modification** — la chaîne assembly → deep_vision → Brain2 fonctionne telle quelle, la seule différence est que `vision_timeline_json` contient des keyframes choisies au lieu de photos périodiques.
2. **Clips de preuve** : sélectionnés en live par MemoryBridge (déclencheurs handoff §Lot 2) → `visual_evidence_assets_v19` + `visual_events_v19` (nouvelles tables).
3. **Résumés de session** : WorldBrain écrit `scene_session_summaries_v19` à la fin de chaque session.
4. **Tampon-jour** (optionnel) : sert uniquement au replay du jour ; il est **purgé** au close-day après extraction des clips retenus — il n'est jamais analysé exhaustivement.
5. La sélection uniforme actuelle (`select_keyframes_for_bundle` : premier/milieu/dernier + espacement régulier, max 12) reste le filet de sécurité ; comme les frames candidates sont déjà des keyframes de changement de scène, l'échantillonnage uniforme échantillonne du signal, plus du bruit.

Nouvelles phases nocturnes V19 (E15) insérées dans le close-day existant : `visual_consolidation` (changes/last-seen → `visual_events_v19`), `outcome_resolution` (auto-vérification des prédictions), `prediction_emission`, `self_schema`.

---

## 2. Référence de la surface d'intégration (signatures réelles)

### 2.1 `v18_delivery.py`

```python
def enqueue_delivery(*, live_session_id: str, source_key: str, candidate: Mapping[str, Any],
                     decision_run_id: str | None = None, hot_intervention_id: str | None = None,
                     tick_id: str | None = None, con: Any | None = None,
                     schema_ready: bool = False) -> dict[str, Any]
# retour: {"status": "skipped"|"suppressed"|"deduplicated"|"queued", "delivery_id": str|None, ...}
def ensure_delivery_schema() -> None
```
`candidate` — champs lus : au moins un de `message`/`text`/`say`/`intervention_message` ; `decision` ∈ `{"queue","speak_now","proactive","notify"}` ; optionnels `action_type`, `cooldown_key`, `recommended_timing`, `candidate_id`, `urgency`/`priority`/`expected_gain` (clampé 0..1).
Queue : `brainlive_intervention_delivery_queue(delivery_id PK, live_session_id, tick_id, candidate_id, horizon, message, action_type DEFAULT 'notify', delivery_status DEFAULT 'queued', priority REAL, evidence_json, created_at, delivered_at, displayed_at, seen_at, feedback_at, feedback_type, feedback_note, updated_at)`.
Dédup : `brainlive_intervention_delivery_dedupes` — clé = `stable_id("v18_delivery", person_id, live_session_id, source_key, fingerprint)` → **`source_key` est obligatoire et significatif**.

### 2.2 `v18_8_live_policy.py`

```python
def record_delivery_feedback(*, delivery_id: str, feedback_type: str, feedback_source: str,
                             note: str | None = None, evidence: Mapping[str, Any] | None = None,
                             observed_at: str | None = None) -> dict[str, Any]
# feedback_type ∈ {"delivered","displayed","seen","acted","dismissed","ignored","failed"} sinon ValueError
def materialize_intervention_outcome_observation(*, delivery_id: str, outcome_status: str,
                             observed_later_summary: str | None = None, did_help: bool | None = None,
                             evidence: Mapping[str, Any] | None = None,
                             observed_at: str | None = None) -> dict[str, Any]
# outcome_status ∈ {"observation_pending","feedback_explicit","reconciled_helped","reconciled_not_helped","unresolved"}
```
Tables : `brainlive_intervention_feedback_events_v188`, `brainlive_intervention_outcomes_v188` (UNIQUE `(delivery_id, outcome_status)`).

### 2.3 `v18_context.py` — ⚠️ pattern de patch

`build_active_context` **n'est pas défini ici** : l'original vit dans `brainlive_v15.py`
(`build_active_context(live_session_id: str, *, active_people=None, refresh_minutes=10, limit=20) -> dict`)
et `v18_context.install(module)` le remplace par un wrapper. Le wrapper lit `raw["context"]["visual_context"]` (issu de `vision_scene_observations`) et `raw["context"]["world_state"]` (dernière ligne de `brainlive_world_states`) et les aplatit en `ContextItem` (importance 0.8).
**Point d'extension** : ajouter un champ dans le mapping `_FIELD_TABLE` (`champ → table source`) de `v18_context.py`, et alimenter la table source correspondante. **Interdit** : re-patcher par-dessus, modifier le wrapper.

### 2.4 `v18_hot_capsule.py`

```python
def build_hot_capsule_payload(*, episode, manifest, fused, route, target_ms: int) -> tuple[dict, dict]
```
Budget entrée : `hot_input_budget(manifest)` — défaut 12 000 chars (env `MLOMEGA_V18_HOT_CAPSULE_MAX_CHARS`, borné 1500-20000) ; sortie 900 tokens (env `MLOMEGA_V18_HOT_OUTPUT_TOKENS`, 160-1400). Réduction itérative `_reduce_once` avec journal `manifest.omitted_refs`.
**Règle** : tout champ V19 (scène/focus/traduction) doit être comptabilisé par `_measure()` et réductible — jamais de clé hors budget.

### 2.5 `auto_verification_v14_4.py`

```python
def auto_verify_latent_outcome_predictions(*, conversation_id=None, person_id=None, limit=50,
                                           min_confidence=0.55, skip_already_verified=True) -> dict
def ensure_v14_4_schema() -> None
def autopilot_coverage() -> dict ; def audit_v14_4(*, persist=True) -> dict
```
Source : table `latent_outcome_links` (créée par `brain2_flow_v13_3.ensure_brain2_flow_schema`), jointe à `predictions` via `lol.source_id = p.prediction_id` (`source_table='predictions'`). Tables de sortie : `v14_4_auto_verify_runs`, `v14_4_auto_verify_links`, `v14_4_autopilot_coverage`.

### 2.6 `v18_predictive_retrieval.py`

```python
def ensure_predictive_schema() -> None
def get_predictive_backend() -> DensePredictiveBackend        # .retrieve / .sync_cases / .score_pair
def register_verified_similarity_label(*, person_id, anchor_case_id, similar_case_id, label,
        label_source, verified_at, source_revision=None, notes=None, metadata=None) -> dict
# label_source CHECK ∈ ('human_verified','strict_verifier','import_verified')
def calibrate_predictive_similarity(*, person_id, backend=None, min_samples=None,
        min_validation_precision=None) -> CalibrationResult
def current_calibration(*, person_id, embedding_revision) -> CalibrationResult | None
```
Contraintes : `similar_case_id` antérieur à `anchor_case_id` ; calibration = split chronologique train/validation, statut `accepted` seulement si précision validation ≥ seuil. **L'outcome watcher V19 étiquette avec `label_source='strict_verifier'`.**

### 2.7 `v18_life_model.py`

`_DIRECT_EVIDENCE_SOURCES: dict[str, tuple[str, str, tuple[str, ...]]]` — format `table → (colonne_pk, colonne_owner, colonnes_temps_candidates)`, ex. `"brainlive_world_states": ("world_state_id", "person_id", ("state_time", "created_at"))`. 34 tables. Existent aussi `_CONVERSATION_EVIDENCE_SOURCES` et `_SESSION_EVIDENCE_SOURCES` (résolution owner via `brainlive_sessions`).
**Toute table V19 servant de preuve doit être ajoutée à l'un de ces trois dicts**, sinon `ScopeError("evidence table is not approved")`.
`v18_life_model.py` est une **librairie de gouvernance** (pas un orchestrateur) : `validate_stratum_evidence`, `install_canonical(module)`, `install_updater(module, canonical_module)`.

### 2.8 `db.py`

Pattern : `db.py` porte un `SCHEMA` central appliqué par `init_db()` (`executescript`, cache `_INITIALIZED_DB_PATHS`) ; **les modules périphériques définissent chacun leur propre `SCHEMA` DDL + `ensure_*_schema()` lazy** appelé en tête de leurs fonctions publiques. → Les tables V19 vivent dans leurs modules (`v19_*.py`) avec `ensure_v19_*_schema()`, `CREATE TABLE IF NOT EXISTS` additifs. Ne pas toucher au `SCHEMA` central.
Helpers : `connect()`, `write_transaction(con, *, immediate=True)`, `upsert(con, table, values, pk)` (refuse `IMMUTABLE_FACT_TABLES`), `insert_only(...)`.
⚠️ `vision_frames` est dans `IMMUTABLE_FACT_TABLES` → **`insert_only` uniquement**.
Schémas utiles (définis dans `brainlive_v15.py`) :
- `vision_frames(frame_id PK, source_asset_id, conversation_id, live_session_id, captured_at NOT NULL, image_path, image_sha256, width, height, device_source, capture_mode DEFAULT 'manual', metadata_json, created_at)`
- `vision_scene_observations(observation_id PK, frame_id FK NOT NULL, live_session_id, conversation_id, model NOT NULL, scene_summary, location_hint, people_count, spatial_context, social_context_hint, visible_text_json, objects_json, risks_json, affordances_json, possible_user_activities_json, personal_relevance_json, confidence, raw_json, created_at)`
- `brainlive_world_states(world_state_id PK, live_session_id FK NOT NULL, person_id NOT NULL, state_time NOT NULL, where_am_i, who_is_active_json, what_is_happening, probable_activity_json, active_emotional_state, active_mode, audio_context_json, visual_context_json, evidence_json, counter_evidence_json, confidence, created_at)`
- `brainlive_active_contexts(...)` (⚠️ nom réel, pas `active_contexts`)
- `raw_assets(asset_id PK, type, path, sha256, captured_at, source, metadata_json, created_at)`

### 2.9 `api.py`

FastAPI, instance globale `app` (fallback `app=None` si absent), **pas d'APIRouter, pas d'auth**, `init_db()` au startup. Style à répliquer :
```python
@app.post("/ingest/transcript")
async def upload_transcript(file: UploadFile = File(...)):
    ...
    return {"conversation_id": conv_id}
```

### 2.10 `ingest.py`

```python
def ingest_transcript(data: dict, source_path: Path | None = None) -> str   # entrée canonique
```
`_resolve_memory_owner(...)` exige `metadata.memory_owner_id` (ou `owner_person_id`/`person_id`) explicite, sinon `ScopeError`. Scope enregistré via `governance_v18.register_conversation_scope_in_transaction(...)`. **Tout ingest V19 fournit `memory_owner_id` explicitement.**

### 2.11 `v18_close_day.py` / runtime

```python
def close_brainlive_day(*, person_id, live_session_id=None, service_run_id=None, package_date=None,
                        use_llm=True, force=False, post_stop_result=None) -> dict
def close_day_status(*, person_id, package_date=None)
```
Ajout d'une phase (liste **en dur**, pas de registre) : (1) `def do_xxx(): ...` dans le corps, (2) `_run_stage(run_id=run_id, name="xxx", fn=do_xxx)` à la bonne position, (3) ajouter le nom dans `_status_ok()` et `_stage_identifier()`, (4) l'ajouter dans `expected=[...]` et `required_stages=[...]` de `assert_cleanup_eligible`.
GPU : `gpu_phase(name, *, release_before=False, release_after=True)` (context manager), `release_live_model_caches()`, `ollama_unload(model=...)` dans `llm.py`.
⚠️ **Piège d'import** : plusieurs modules importent `from .runtime_v18_7 import ...` alors que les définitions vivent aussi dans `runtime_v18_8.py`. Ne pas « corriger » à la volée : suivre l'import existant du module qu'on étend, consigner dans DECISIONS.md.

### 2.12 Deep vision (chaîne à réutiliser en E14)

```python
def run_offline_deep_vision_for_bundles(person_id="me", *, package_date=None, live_session_id=None,
        model=None, timeout_per_image=None, max_keyframes_per_bundle: int = 12,
        transcript_char_threshold=None, limit_bundles=200, append_to_brain2=True,
        fail_on_vlm_error=False, use_vlm=True) -> dict
def select_keyframes_for_bundle(bundle: dict, *, max_keyframes: int = 12, silent_bias=True) -> list[dict]
```
Entrée : bundles `brainlive_event_bundles_v1514.vision_timeline_json` ; VLM choisi par priorité `model` > `MLOMEGA_OFFLINE_VLM_MODEL` > `MLOMEGA_VLM_HEAVY_MODEL` > `MLOMEGA_VLM_MODEL` > `settings.ollama_model`, appelé via `ollama_generate` (base64, `format:"json"`, temp 0.0), déchargé via `ollama_unload`. Sorties : `brainlive_deep_vision_runs_v161`, `brainlive_deep_vision_observations_v161`, `brainlive_deep_vision_brain2_exports_v161`.
CLI : `brainlive-close-day`, `brainlive-resume-close-day`, `brainlive-deep-vision-run/-audit`, `brainlive-deep-audio-run/-audit`, `brain2-life-model-update`.

---

## 3. Étapes — LOT 1 (Fondation)

**[x] E1. Squelette monorepo.**
Statut : terminé — commit : 173184f (import) + 4598428 (référence restaurée à l'état pristine) — tests : suite V18 108/108 contre `src/` racine. Créer l'arborescence handoff §3.1 ; copier `MLOmega_V18_8_1_Evidence_Connected` → `src/` + fichiers racine nécessaires ; vérifier que `pytest tests/test_v18_8_1_evidence_connected.py` passe AVANT toute modification (baseline). Geler `runtime_v18_7`/`operations_v18_7` (en-tête « gelé, ne pas diverger de v18_8 »).

**[x] E2. Contrats.**
Statut : terminé — commit : 173184f + 4598428 (fix `priority` int→float 0..1 partout ; POCOs C# générés avec champs via `generate_csharp.py`) — tests : test_contracts + test_csharp_generator verts. `packages/contracts/schemas/*.schema.json` (8 contrats handoff §3.4, champ `contracts_version` partout) → modèles pydantic v2 générés/écrits dans `packages/contracts/python/` → stubs C# dans `csharp/`. Test round-trip python→JSON→python pour chaque contrat. Aucune dépendance vers le cœur ni vers un SDK.

**[x] E3. SessionHub**
Statut : terminé — commit : 2d2a7d8 — tests : test_sessionhub (ClockSync offset/RTT validés numériquement). (`services/live-pc/sessionhub.py`). Sessions (`session_id` = uuid horodaté, jamais réutilisé), ClockSync (échange de timestamps monotones, offset stocké par session), token de session éphémère émis à l'appairage (remplace le token statique pour le canal XR ; le bridge V18.8 existant garde le sien). Test : deux clients simulés, offsets cohérents.

**[x] E4. VideoIngress + gateway** (`services/live-pc/gateway.py`). Interface `VideoIngress` (async itérateur de `(frame_bgr, FrameEnvelope)`), impl `AiortcIngress`. Queue = 1 : variable « dernière frame » + compteur de drops, jamais de liste. Bench intégré : P50/P95 décodage. Test : `webrtc_frame_queue_bounded`.
Statut : terminé — commit : 4598428 (vrai `AiortcIngress` WebRTC ; le stub initial 2d2a7d8 renommé `IterableIngress`) — tests : test_transport + test_transport_webrtc 3/3 (boucle aiortc réelle) ; bench réel P95 décodage 0,81 ms (8c24192).

**[x] E5. fake_xr_device** (`simulators/fake_xr_device.py`). Client aiortc qui rejoue un MP4 + JSONL de pose ; options : fps, perte réseau simulée, rotation 90° (mode capture-only). Produit des `FrameEnvelope` valides (frame_id croissants, monotonic ns).
Statut : terminé — commit : 4598428 (rejeu MP4+pose réel en H.264 via aiortc, options fps/loss/rotate90 ; scénario de test dans `simulators/scenarios/`) — tests : test_transport_webrtc 3/3.

**[x] E6. delivery_adapter** (`services/live-pc/delivery_adapter.py`). Boucle : lit `brainlive_intervention_delivery_queue` (`delivery_status='queued'`, tri priority desc) → convertit en `UIIntent` (`producer='brainlive'`, `component='context_card'` par défaut, `evidence_refs` depuis `evidence_json`, `delivery_id` reporté) → push WebSocket/DataChannel vers renderers connectés → à l'accusé : `record_delivery_feedback(delivery_id=..., feedback_type='delivered', feedback_source='xr_adapter')` puis relaie chaque `UIReceipt` (`displayed/seen/acted/dismissed`) vers la même fonction. Les UIIntent d'UltraLive/VisionRT ne passent **pas** par cette queue (réflexes directs) ; seul BrainLive H1 y passe. Lire `v18_delivery.py` en entier avant (fonction de poll existante à réutiliser si présente).
Statut : terminé — commit : 2d2a7d8 + 4598428 (priority float clampée 0..1) — tests : test_delivery_adapter + démo intégration jusqu'à `brainlive_intervention_feedback_events_v188`.

**[x] E7. companion-web** (`apps/companion-web/`). Une page : WebSocket vers delivery_adapter, rendu des UIIntent (cards/sous-titres/contours sur flux optionnel), clic → UIReceipt. Sert de renderer de référence pour tous les tests.
Statut : terminé — commit : 2d2a7d8 — tests : receipts displayed/dismissed vérifiés via la démo SimOnly.

**[x] E8. GpuArbiter + degraded** (`services/live-pc/gpu_arbiter.py`, `degraded.py`). NVML (pynvml) : VRAM totale/utilisée par phase ; API `request(job_class) -> grant/deny/preempt` selon priorités handoff §4.1 ; vérification post-`ollama_unload` (re-mesure VRAM, alerte si pas libérée). États dégradés → événements poussés aux renderers (StatusBar).
Statut : terminé — commit : 4598428 (budgets par classe + `verify_ollama_unload` /api/ps + machine à états degraded réelle) — tests : test_gpu_arbiter 5/5, test_degraded verts.

**[x] E9. Scripts + profil.** `INSTALL_MLOMEGA_V19_WINDOWS.ps1` (préflight, `.venv-live`, MODEL_MANIFEST, ne touche pas `.venv`), `setup_profile.ps1` (questions → `configs/user_profile.yaml`, cf. handoff §3.5), `RUN_MLOMEGA_V19.ps1 -SimOnly|-Xr`, `DOCTOR_MLOMEGA_V19.ps1` (ports, GPU, Qdrant, Ollama, contrats, queue delivery, profil), `BENCH_V19.ps1`. Ports V19 : préfixe 87xx hors 8766.
Statut : terminé — commit : 4598428 (INSTALL transactionnel réel, DOCTOR avec checks GPU/Qdrant/Ollama/contrats, setup_profile interactif + -Defaults) — tests : test_scripts_profile vert ; DOCTOR exécuté sur machine cible : OK, 4 WARN, 0 FAIL (RTX 3070 détectée).

**[x] E10. Checkpoint Lot 1.**
Statut : terminé — commit : 8c24192 — tests : tests/v19 40/40 ; V18 108/108 ; bench WebRTC réel machine cible : P95 décodage 0,81 ms < 33 ms (critère tenu, cf. `docs/BENCH_RESULTS.md`). `pytest tests/v19 -m "contracts or transport"` vert ; `pytest tests/test_v18_*` vert inchangé ; démo : `RUN -SimOnly` → fake device → UIIntent test → companion-web → receipt visible dans `brainlive_intervention_feedback_events_v188`. Bench ingress consigné dans `docs/BENCH_RESULTS.md`. **Revue avant Lot 2.**

---

## 4. Étapes — LOT 2 (Mémoire profonde)

**[x] E11. Tables V19** (`src/mlomega_audio_elite/v19_visual_store.py`). SCHEMA propre + `ensure_v19_visual_schema()` (pattern §2.8) : `visual_evidence_assets_v19`, `visual_events_v19`, `world_entity_links_v19`, `scene_session_summaries_v19`, `ui_interaction_outcomes_v19` (colonnes : handoff §Lot 2 + toujours `person_id`, `live_session_id`, temps UTC + `created_at`). Puis **enregistrer chaque table de preuve dans `_DIRECT_EVIDENCE_SOURCES`** (format §2.7) — ex. `"visual_events_v19": ("visual_event_id", "person_id", ("occurred_at", "created_at"))`. Test : insertion + `validate_stratum_evidence` accepte une ref vers ces tables.
Statut : terminé — commit : 6f61715 + 4598428 (3 tables brain2_*_models ajoutées + evidence sources) — tests : test_memory_v19 verts (validate_stratum_evidence accepte les refs v19).

**[x] E12. Endpoints** (`api.py`, style §2.9, additif en fin de fichier) : `/ingest/visual-event` (EvidenceEvent JSON → `visual_events_v19` + asset), `/ingest/scene-summary`, `/memory/correction-visual`, `/xr/session-health`, `/evidence/request-clip`. Chaque payload porte `memory_owner_id` explicite (règle §2.10).
Statut : terminé — commit : 4e6c03f — tests : endpoints FastAPI via TestClient, 422 si `memory_owner_id` absent.

**[x] E13. MemoryBridge + EvidenceStore** (`services/live-pc/memory_bridge.py`, `evidence_store.py`). Déclencheurs de sélection (handoff §Lot 2) → clip depuis ring buffer/tampon-jour → sha256 → POST `/ingest/visual-event`. Tampon-jour : encodage basse résolution continu, purge au close-day, quota doctor.
Statut : terminé — commit : 9be3afa + 4598428 — tests : test_memory_v19 (e13) vert ; déclencheurs enrichis + tampon-jour purgé par la consolidation.

**[x] E14. Pont keyframes → chaîne nocturne existante** (le pont central du projet). Le sélecteur de keyframes PC enregistre chaque keyframe : (1) fichier image → `raw_assets` ; (2) ligne `vision_frames` via **`insert_only`** (`capture_mode='xr_keyframe'`, `live_session_id`, `image_sha256`) — cf. §1.3. Vérifier ensuite avec le simulateur que `run_brainlive_event_assembly` intègre ces frames dans `vision_timeline_json` d'un bundle et que `run_offline_deep_vision_for_bundles` les analyse (si l'assembleur ne lit pas `vision_frames` pour la timeline vision, lire `collect_live_raw_timeline` et brancher au bon endroit — ADR obligatoire). Test : session simulée → bundle → deep vision → `brainlive_deep_vision_observations_v161` non vide.
Statut : terminé — commit : 9be3afa (`v19_keyframes.py` : insert_only, capture_mode='xr_keyframe', raw_assets) — tests : test_memory_v19 vert ; chaîne bundle→deep vision avec VLM réel = vérification différée au close-day final (décision utilisateur).

**[x] E15. Nouvelles phases close-day** (`v18_close_day.py`, pattern exact §2.11 — seule modification autorisée de ce fichier). Après `post_stop`, avant `longitudinal` : stage `visual_consolidation` (module `v19_visual_consolidation.py` : ChangeEvents WorldBrain → `visual_events_v19` ; résumés session → `scene_session_summaries_v19` ; purge tampon-jour après extraction). Après `life_model` : stages `outcome_resolution`, `prediction_emission`, `self_schema` (E16-E18). Chaque stage ajouté dans `_status_ok()`, `_stage_identifier()`, `expected`, `required_stages`. Test : `brainlive-close-day` complet sur données simulées, `close_day_status` liste les 9 stages `completed` ; relance = tous `resumed_stage`.
Statut : terminé — commit : 9be3afa + 4598428 (stage `life_model_v19` ajouté entre `outcome_resolution` et `prediction_emission` — 10 stages au total) — tests : pattern 4-endroits audité conforme §2.11 ; V18 108/108.

**[x] E16. Outcome watcher** (`v19_outcome_watcher.py`). Prédictions ouvertes (avec `verification_spec`) × preuves du jour (transcripts, `visual_events_v19`, GPS, routines) → résolution `verified/refuted/expired/unverifiable` + evidence_refs de résolution → écrit `prediction_outcomes_v19` ; alimente la calibration via `register_verified_similarity_label(..., label_source='strict_verifier')` (contrainte §2.6 : le cas similaire doit être antérieur à l'ancre) ; appelle `auto_verify_latent_outcome_predictions` pour la voie conversationnelle existante. Échantillon d'audit journalisé.
Statut : terminé — commit : 9be3afa + 4598428 + 8c24192 (fix verrou SQLite : labels de calibration différés hors transaction) — tests : test_prediction_auto_verified_by_observation vert (outcome `verified` + label `strict_verifier` sans entrée utilisateur).

**[x] E17. Prediction emission + Life Model durable** (`v19_prediction_loop.py`, `v19_life_model_store.py`). Life Model V19 = magasin d'entrées typées (handoff Lot 2 : dimensions × axes temporels, statuts `active/weakening/contradicted/superseded`, historique). Mise à jour = deltas LLM en 3 étapes contractées (réutiliser `llm_contracts_v15_18`), appliquées par le store — jamais de régénération complète. L'updater V15.13 existant continue de tourner (stage `life_model`) ; le store V19 le complète, il ne le remplace pas (ADR si conflit). Émission : 3-7 prédictions avec `verification_spec`, pénalité si invérifiable.
Statut : terminé — commit : 4598428 (store branché au close-day, deltas incrémentaux, transitions weakening/contradicted) — tests : test_life_model_update_is_incremental + test_life_model_entry_weakens_without_confirmation verts.

**[x] E18. Self schema** (`v19_self_schema.py`). Projection depuis life model store + patterns confirmés + `causal_edges` + `prediction_outcomes_v19` → table `self_schema_v19` (entrées : type aime/veut/a_fait/causal/conditionnel, evidence_refs, taux d'occurrence). Endpoint `GET /self-schema` + projection compacte dans le hot capsule (E19).
Statut : terminé — commit : 9be3afa + 4598428 — tests : test_self_schema_conditional_pattern_has_evidence vert (occurrence_rate + evidence_refs obligatoires).

**[x] E19. Hot capsule + contexte visuel.** (1) `v19_visual_context.py` : pousse l'état WorldBrain courant dans `brainlive_world_states` (schéma §2.8) et les observations dans `vision_scene_observations` — le wrapper `v18_context` les reprend automatiquement ; ajouter les champs nouveaux (`self_schema_hot`, `scene_focus`) dans `_FIELD_TABLE`. (2) Extension `v18_hot_capsule` : champs additifs comptabilisés par `_measure()` et réductibles (§2.4). Test : hot capsule avec scène simulée respecte le budget et journalise les omissions.
Statut : terminé — commit : 4598428 (`v19_visual_context` réécrit sur les vraies tables `brainlive_v15` — schéma shadow supprimé, cf. DECISIONS 2026-07-04) — tests : test v19_visual_context contre les tables réelles vert ; budget hot capsule respecté.

**[x] E20. Vie synthétique** (`simulators/synthetic_life.py`) : 30 jours générés (routines, déplacements, objets, rencontres, conversations) injectés par les endpoints → close-day par jour → au moins une routine détectée, une prédiction `verified`, une `refuted`, un pattern conditionnel dans le self schema. C'est le test d'acceptation du lot.
Statut : terminé — commit : 4598428 (générateur seedé 30 jours : personnes/conversations/lieux/objets déplacés/routines à ~80% d'adhérence/événements rares) — tests : scénarios alimentent les 4 tests nommés, tous verts.

**[x] E21. Checkpoint Lot 2.** `pytest tests/v19 -m memory` vert ; tests V18 verts ; close-day complet < 6h réelles sur RTX 3070 (données synthétiques) avec journal `gpu_phase` ; doctor `-Memory` vert. **Revue avant Lot 3.**
Statut : terminé — commit : 8c24192 — tests : tests/v19 40/40 ; V18 108/108 ; doctor OK (4 WARN services éteints). **Exception actée (décision utilisateur 2026-07-04) : le close-day réel complet avec Ollama/Qdrant allumés est différé après le Lot 3, en test final de bout en bout.**

---

## 5. Étapes — LOT 3 (Live/XR/mobile)

**E22. Gate G1 matériel (peut démarrer dès la fin du Lot 1, en parallèle du Lot 2).** Unity 6 LTS + XREAL SDK 3.1.0, sample officiel sur S25 réel : Eye RGB, pose, rendu stéréo, permissions (`RECORD_AUDIO`, `FOREGROUND_SERVICE_MEDIA_PROJECTION`), coupure/reprise. Si la caméra Eye est inaccessible : plan B `one-xr` (pose) + caméra S25 (même pipeline), ADR, et continuer.

**E23. App Unity noyau.** `XRDeviceAdapter` (interface C#) + `XrealDeviceAdapter`, `SimulatedDeviceAdapter`, `PhoneOnlyAdapter` ; `XrSessionController`, `EyeCaptureSource` (frame_id + monotonic), `PosePublisher`, `ClockSync` (protocole E3).
Statut : code livré — commit : 6c67d5d — tests : EditMode écrits (exécution à la première ouverture Unity) ; validation matérielle couplée au gate G1. Contrats synchronisés dans `apps/xr-mobile/Assets/Scripts/Contracts/` (Newtonsoft, cf. ADR DECISIONS §E23) + outil de sync Editor ; `ClockSync` reproduit numériquement `sessionhub.py` (offsets -5ms/+8ms de `tests/v19/test_sessionhub.py`) ; `PhoneOnlyAdapter` = cible téléphone-only de premier rang (`IsStereo=false`) ; sélection d'adaptateur via `MLOmegaConfig` alignée sur `configs/user_profile.yaml`. Pas de [x] (validation Unity/matériel utilisateur après ouverture).

**E24. Transport mobile.** Plugin Kotlin `LiveTransportPlugin` (GetStream webrtc-android) : H.264 low-latency + Opus 20 ms + DataChannel fiable/ordonné (contrats E2 sérialisés JSON), reconnexion, bitrate adaptatif. Valider contre le gateway E4 : frame_id/pose intacts côté PC, UIIntent retour affiché sur le bon track.
Statut : code livré — commit `feat(v19-e24)` — tests : `pytest tests/v19` 50/50 verts (dont `test_sessionhub_http` 8/8, `test_transport_webrtc` unifié 4/4, `test_e24_roundtrip` : frame_id/pose intacts + UIIntent renvoyé avec le bon `target_track_id` + UIReceipt jusqu'à `record_delivery_feedback`) ; V18 inchangés. Serveur HTTP SessionHub (`sessionhub_http.py`, port 8710) + signaling unifié `POST /webrtc/offer` (token exigé) réutilisé par `fake_xr_device` et le futur client Android. Plugin Android (`apps/xr-mobile/android/livetransport/`, GetStream **1.3.10** épinglée) + bridge Unity `LiveTransportBridge.cs`. **Compilation Android + validation S25 différées matériel** (pas d'Android SDK ici ; ADR `docs/DECISIONS.md` §E24). Pas de [x] (validation matériel utilisateur).

**E25. SceneCache + UIIntentBroker + UIRuntime.** Sous-caches et TTL (guide V19 §9.1), priorités de rendu (handoff Lot 3), design system liquid glass — chaque composant émet ses `UIReceipt` vers le DataChannel (repris par delivery_adapter E6 pour la voie BrainLive). StatusBar permanente.
Statut : code livré — commit `feat(v19-e25)` — tests : EditMode écrits (exécution à la première ouverture Unity ; pas d'Unity dans cet environnement) ; validation visuelle éditeur + matériel différée. `SceneCache` (6 sous-caches + `SceneCacheConfig`, §9.1) + `UIIntentBroker` (échelle §13.2, TTL, fade track perdu, densité, dédup, `ui_intent_drop_reason` §15.3) déjà mergés ; ce lot ajoute : shader URP `LiquidGlass.shader` (verre translucide + rim d'accent de vérité + grain) alimenté par un flou Kawase dual-filter dans une `ScriptableRendererFeature` RenderGraph (`GlassBlurFeature`, texture globale partagée `_MLOmegaGlassBlur`, fallback translucide plat si absente — ADR §E25) ; `UITheme` (tokens) ; les 10 composants §13.1 (`ObjectOutline`, `PersonTag`, `Subtitle`, `LensWindow`, `OffscreenArrow`, `ContextCard`, `TaskCard`, `VirtualScreen`, `CorrectionChip`, `StatusBar`) sur base `UIComponentBase` (cycle admit→display→fade→recycle + receipts §13.3 : `displayed` à l'affichage, `seen` après dwell prudent, `acted`/`dismissed`/`corrected` ; vérité §17.2 : badge « probable », âge last-seen, étiquette hypothèse, pas de nom sous seuil d'identité, pas de flèche sous seuil de carte) ; `UIRuntime` (mapping composant→type + pooling + ancrage SceneCache + sink) ; `UIReceiptTransportSink` (file bornée `ReceiptOutbox`, flush à la reconnexion, drop du plus ancien) ; `Editor/E25SceneBuilder.cs` (scène démo + `E25DemoDriver` injectant un intent de chaque composant). Tests EditMode : `UIComponentRegistryTests`, `UITruthTests`, `UIReceiptLifecycleTests`, `UIReceiptOutboxTests`. **Compilation Unity + validation visuelle éditeur/S25 différées** (pas d'éditeur Unity ici). Pas de [x] (validation Unity/matériel utilisateur après ouverture).

**E26. Ultra-Live device.** `ReflexScheduler` + skills : StableTrack, LensWindow (zoom gestes), MotionProximity, FocusSearch ; `GesturePipeline` MediaPipe (pincer=zoom, paume=menu, balayage=cacher) ; `AsrKwsService` sherpa-onnx (VAD + zipformer FR/EN + wake word configurable). Test clé : PC coupé → zoom/tracks/gestes/wake word intacts.
Statut : code livré — commits : f027975 (Kotlin reflexvision : MediaPipe gestes + sherpa-onnx ASR/KWS, machine à états JVM-testée) + 9b49201 (couche reflex Unity : scheduler §9.3, 6 skills via broker, LocalTrackStore + TemplateTracker NCC, bridges avec sim éditeur) + tests/docs (ce commit) — tests : JVM Kotlin (GestureStateMachine, KeywordEncoder) + EditMode `ReflexOfflineTests` (test clé offline : transport déconnecté → intents toujours émis ; mapping scheduler ; TemplateTracker sur motif synthétique ; agrégation ReflexEvent avec flush immédiat en critique) — écrits, exécution au premier clic Unity ; compilation Kotlin + validation S25 différées matériel.

**[x] E27. VisionRT + AudioRT PC** (`services/live-pc/visionrt.py`, `audiort.py`). Détecteur ONNX adaptatif 5-15 fps + tracker toutes frames (politique handoff §3.6, cadences en config) ; OCR ROI ; VLM crop un job à la fois via GpuArbiter ; sortie `SceneDelta` liée à `source_frame_id`. AudioRT : VAD + faster-whisper streaming + LID + traduction → `UIIntent subtitle` partiels/finaux sans LLM.
Statut : terminé — commits `feat(v19-e27): ...` (branche `feat/v19-e27-visionrt-audiort`) — tests : **exécutés et verts sur la machine cible** (E27 sans dépendance matériel externe). `tracking.py` ByteTrack maison (2-passes IoU + Kalman) ; `visionrt.py` YOLOX-nano ONNX Apache-2.0 (Megvii, sha256-épinglé, détecteur réel P50 9,9 ms / P95 10,5 ms CPU), cadence adaptative motion-driven (106/300 frames détecteur au bench), OCR ROI rapidocr, VLM crop un-job Ollama (dégradé `vlm_unavailable` testé Ollama éteint), keyframes → `v19_keyframes` (pont E14), SceneDelta liée `source_frame_id` + focus `what_is/find/ocr` → UIIntent §17.2 ; `audiort.py` webrtcvad + faster-whisper small int8 **sur RTX 3070 (device=cuda, ~200-380 ms/segment)** + Argos Translate fr↔en (MIT, sans LLM, fr→en vérifié) + sous-titres réflexe DataChannel direct ; `live_pipeline.py` orchestration + dégradé §3.6 + `/metrics`. GpuArbiter : classe `asr` dédiée ajoutée au plancher réflexe protégé + budgets profil. Tests : `test_tracking`, `test_visionrt` (détection person réelle + cadence + keyframe→`vision_frames`), `test_audiort` (VAD + whisper réel + traduction), `test_e27_pipeline` (fake_xr_device→pipeline→SceneDelta `source_frame_id` cohérent via WebRTC réel + `what_is` dégradé Ollama off). **`pytest tests/v19 -q` = 66/66 verts ; V18 108/108 inchangés.** Bench `--vision` réel dans `docs/BENCH_RESULTS.md`. Modèles fetch via `scripts/fetch_models_v19.py` (models/ git-ignoré), manifest à jour (URL/sha/licence).

**[x] E28. WorldBrain + spatial** (`worldbrain.py`, `spatial.py` impl `SpatialMapProvider` V19.A). Entities/observations/relations/last-seen/ChangeEvents/map_quality ; keyframe selector (E14 branché) ; `brainlive_scene_adapter.py` → HotSceneContext → politique BrainLive existante → `enqueue_delivery` (§2.1, `source_key` = scène+sujet).
Statut : terminé — commits `feat(v19-e28): ...` (branche `feat/v19-e28-worldbrain`) — tests : **exécutés et verts sur la machine cible** (E28 sans dépendance matériel). `worldbrain.py` : promotion track→`WorldEntity` (≥3 obs confirmées ≥ conf 0.35, seuils config ; 1 bbox faible → pas d'entité), `Observation`/`Relation` (on_top_of/near/holds géométriques)/`ChangeEvent` (appeared/disappeared/moved before-after)/`SceneSession`, last-seen avec âge ; persistance sur les **vraies** tables (last-seen+changes → `visual_events_v19` via `store_visual_event` owner-scopé ; résumé session → `scene_session_summaries_v19` ; état courant → `brainlive_world_states`/`vision_scene_observations` via `v19_visual_context`) + SQLite service-local pour la session (aucune table cœur). `spatial.py` `PoseKeyframeMap` V19.A : zones par clustering de poses, bearings relatifs, **map_quality mesurée** (densité×fraîcheur×cohérence), `bearing_to`→None sous seuil (jamais de fausse flèche). `brainlive_scene_adapter.py` : `HotSceneContext` budget dur + omissions traçables ; situations §12.4 (personne connue/objet retrouvé/tâche active) → **`enqueue_delivery` direct** (`decision='notify'`, `source_key` scène+sujet, evidence) → `delivery_adapter` E6. Câblage `live_pipeline.py` (VisionRT→WorldBrain, pose→spatial, transcript→adapter, end_session, métriques `/metrics`). ADR §E28 (promotion, seuils map_quality, choix `enqueue_delivery` vs hot-loop). Tests : `test_e28_worldbrain.py` (12 cas : promotion/rejet bbox faible, last-seen+âge, moved, relations, holds, map_quality basse→bearing None, bearing qualifié, persistance réelle visual_events_v19 + brainlive_world_states, résumé session, scene_adapter→queue `brainlive_intervention_delivery_queue` avec source_key/evidence, budget HotSceneContext). **`pytest tests/v19 -q` = 78/78 verts ; V18 inchangés.** Seuils par défaut : `promote_min_observations=3`, `promote_min_confidence=0.35`, `min_map_quality_for_bearing=0.35`, `hot_budget_chars=4000`.

**[x] E29. Scénarios + capture-only.** Les 16 scénarios contre `simulators/scenarios/` + companion-web d'abord, matériel ensuite ; `OrientationGuard` (rotation IMU) + profil `phone_only` de bout en bout.
Statut : terminé — commits : 240b448 (pack 16 scénarios + runner in-process/webrtc + rotation PC) + ce commit (OrientationGuard Unity, loader de profil §3.5, e2e phone_only, fix WebSocket delivery_adapter) — tests : `test_e29_scenarios` 3/3 (16/16 scénarios PASS contre le vrai pipeline ; profil validé ; phone_only → queue → viewer → receipt en table) ; transport 23/23 après fix. **Périmètre honnête** : chaînes LIVE prouvées en simulation ; la profondeur mémoire/LLM des scénarios dépendants de Brain2/Qwen relève du test final close-day (E30 fusionnée, décision utilisateur). Partie Unity (OrientationGuard) : compilation différée matériel comme E22-E26.

**[x] E31. Conversation live → BrainLive V18.8** (`services/live-pc/conversation_bridge.py`, câblage `live_pipeline.py`). Le branchement prioritaire du PROD_BACKLOG : les segments FINAUX d'AudioRT entrent dans le **vrai** point d'entrée conversationnel du cœur — `brainlive_v15.ingest_live_turn` → `brainlive_turn_buffer` (session partagée V19 via `start_live_session`, `speaker_label` générique, timestamps UTC ; identité en E32) — puis `ConversationBridge.tick()` appelle la politique de debounce existante `v18_8_live_policy.plan_live_dispatch` et, si dispatch dû, le hot loop existant `optimized_hot_brainlive_cycle` (H1 → `enqueue_delivery` → queue → `delivery_adapter` E6 → device). **Brancher, pas reconstruire** : aucune modification de `src/`, aucune policy/queue parallèle. Cadences = défauts cœur (`MLOMEGA_BRAINLIVE_LLM_*`), surchargeables par le XR sans changer les défauts. Métriques `conversation_turns`/`h1_candidates`/`hot_cycles` sur `/metrics`.
Statut : terminé — branche `feat/v19-e31-conversation-live` — tests : `test_e31_conversation` 3/3 (wiring : segment final simulé → tour dans `brainlive_turn_buffer` avec session/timestamps corrects ; réactivité : mémoire amorcée + transcript sur le sujet → candidat H1 dans `brainlive_intervention_delivery_queue` **avec evidence** ; bout-en-bout : candidat → viewer WebSocket + receipts `delivered`/`displayed` en table, pattern E29 phone_only). Frontière LLM : run Ollama réel si un modèle est servi, sinon monkeypatch **uniquement** de `OllamaJsonClient.require_json` (frontière de service externe) avec un JSON valide `HOT_UNIFIED_SCHEMA` référençant un vrai item du manifeste — le validateur strict d'evidence tourne quand même (ADR §E31). **`pytest tests/v19 -q` = 84 passed** ; cœur `src/` inchangé ; V18 non touchée. Latence transcript→suggestion : 1er tour immédiat, puis fenêtre audio ≈45s / silence ≥12s / max 90s (fenêtres policy), hot cycle ≈12s.

**[x] E32. Identité multi-indice (visage + voix + enrollment + correction)** (`services/live-pc/face_identity.py`, `voice_identity_live.py`, `identity_fusion.py`, `enrollment_watcher.py`, câblage `live_pipeline.py`). **Visage** : YuNet (`cv2.FaceDetectorYN`, MIT) + SFace (`cv2.FaceRecognizerSF`, Apache-2.0), ONNX épinglés `url+sha256` au `MODEL_MANIFEST.yaml`, fetch via `scripts/fetch_models_v19.py` ; crop person → détection → alignCrop → embedding 128-D → cosine contre galerie **SQLite service-local** (`face_people`/`face_embeddings`, à côté du cœur, aucune table cœur ajoutée) ; job classe "ocr" via GpuArbiter si GPU, CPU sinon. **Voix** : `voice_identity_live.py` réutilise **les primitives du cœur** `voice_identity.enroll_voice`/`match_voice` (ECAPA SpeechBrain, tables `voice_embeddings`/`speaker_profiles` partagées avec le flow nocturne/CLI `voice-pending`) quand la stack est importable ; sinon embedder de substitution injecté (chemin live prouvé, ECAPA réel validé au close-day final). Le speaker résolu alimente `speaker_person_id`/`speaker_label` du tour **avant** `conversation_bridge.ingest_segment` (le champ E31 « identité en E32 » branché). **Fusion** : `identity_fusion.py` combine visage + voix + persistance de track → au-dessus du seuil, nomme l'entité person WorldBrain (name + person_id sur l'entité → SceneDelta → PersonTag) et amorce `scene_adapter.known_people` → le déclencheur ContextCard existant (`p.identified and p.name`) s'active naturellement ; indices contradictoires (visage ≠ voix) → **anonyme** (§17.2, jamais de nom incertain). **Enrollment vocal** : `enrollment_watcher.py`, pré-routeur autonome (le routeur général = E33), regex FR/EN robustes « retiens[,:]? c'est X » / « souviens-toi de X » / « remember (this is) X » → capture meilleur crop visage récent + segment voix → enrôle les deux galeries + UIIntent « Enregistré : X » ; « non, ce n'est pas X » / « oublie X » / « forget X » → suspend le label (fusion + WorldBrain) + trace durable via le **vrai** `memory_correction.revise_memory` (best-effort si cible mémoire) + UIIntent. **Câblage** : crops person → face à cadence économe (nouveau track ou toutes N=30 frames, pas chaque frame) ; segments finaux → voix → bridge ; transcripts → enrollment ; métriques `identity_matches`/`named_entities`/`enrollments`/`corrections`/`face_matches` sur `/metrics`. **Brancher, pas reconstruire** : aucune modification de `src/` (appels uniquement) ; recherche d'identité 100 % locale.
Statut : terminé — branche `feat/v19-e32-identity` — tests : `test_e32_identity` 11/11 dont le **vrai** pipeline YuNet+SFace sur un visage domaine public (`skimage.data.astronaut()`) : enrollment image A → match du même visage sous variation de luminosité simulée → entité nommée + PersonTag ; visage inconnu/crop vide → anonyme (§17.2) ; fusion visage+voix concordants / voix seule au-dessus du seuil → nommé ; contradiction → anonyme ; persistance de track ; enrollment vocal regex → galerie voix (embedder substitut) + galerie visage + UIIntent « Enregistré : Sarah » ; correction → label suspendu partout + `memory_correction.revise_memory` réellement appelé (monkeypatch de la frontière DB, cible `atomic_memories`). Les tests visage skippent proprement si les poids sont absents (suite verte sur checkout nu). **`pytest tests/v19 -q` = 95 passed** ; cœur `src/` inchangé ; V18 non touchée. Seuils par défaut : SFace cosine `0.363`, ECAPA cosine `0.72`, `min_name_confidence=0.45`, `both_agree_bonus=0.15`, cadence identité `30` frames. **Réserve** : la voix réelle ECAPA (SpeechBrain/torchaudio) n'est pas dans cet env système → chemin live testé via embedder de substitution ; validation ECAPA réelle au close-day final.

**[x] E33. IntentRouter vocal + actions device + mode payant + menu UI** (`services/live-pc/intent_router.py`, `memory_query.py`, `llm_providers.py`, câblage `live_pipeline.py` ; Unity `Assets/Scripts/UI/DeviceCommandHandler.cs`, `UI/Components/MenuPanel.cs`, `Transport/AppLauncherBridge.cs`, `Reflex/MenuGestureController.cs`, densité `UIIntentBroker` ; Kotlin `reflexvision/AppLauncher.kt`). **Routeur PC** : grammaire d'abord (regex/mots-clés FR+EN, déterministe, offline) pour what_is / find(cible) / ocr / traduis(-le/langue) / zoom / cache tout / affiche tout / mode Free Guy / minimal / pause privée / menu / ouvre (maps [destination] | youtube [requête] | app [package]) / mode payant [openai|gemini] / mode local / rejoue [heure] / demande mémoire (« interroge ma mémoire », « rappelle-moi », « qu'est-ce que je… ») ; **multi-tour** : contexte court-TTL (25 s) de la dernière commande/cible → « zoom dessus », « traduis-le », « et ça ? » résolvent sur la dernière cible track/bbox ; **repli LLM** : parse JSON strict via le LLM live (Ollama), sinon « je n'ai pas compris : … » honnête. Chaque intent routé vers son handler EXISTANT (visionrt focus, toggles→device_command, ask_memory, LLM switch) — **aucune logique métier dupliquée**. L'`enrollment_watcher` E32 est **absorbé** comme pré-routeur du routeur (identité pré-routée avant la grammaire générale ; tests E32 intacts). **Mémoire** (`memory_query.py`) : intent mémoire → **le routeur Brain2 riche du cœur** `brain2_router_v14_2.ask_brain2` (comme le CLI `v14-ask`, pas le `/query` simple) → ContextCard (`truth_level=remembered` + evidence refs) ; Ollama éteint → repli honnête `retrieval.search` sans LLM (`inferred`), sinon « mémoire profonde indisponible ». **Providers** (`llm_providers.py`) : interface `LLMProvider` + `OllamaProvider` (réutilise `OllamaJsonClient` du cœur) + **`OpenAIProvider`/`GeminiProvider` réels** (HTTP direct, `response_format=json_object` / `responseMimeType=application/json`, clé par env `OPENAI_API_KEY`/`GEMINI_API_KEY`, endpoints/modèles/coûts **configurables** dans `configs/cloud_llm.yaml`) ; **bascule runtime** « mode payant [openai|gemini] » / « mode local » : cloud JAMAIS par défaut ni sans opt-in ; `cloud_data_policy=local_only` → refus poli ; table de coûts affichée dans la réponse (« mode payant activé (openai) — ~0,01–0,03 €/question ») + event StatusBar `cloud_mode` vers le device. **Device par DataChannel** : messages `device_command` (`set_ui_mode{hide_all,minimal,normal,freeguy}`, `open_app{maps,youtube,package}`, `privacy_pause`, `open_menu`, `replay`) PC→Unity ; côté Unity `DeviceCommandHandler` exécute : toggles → `UIIntentBroker.SetDensity` (**modes de densité nommés ajoutés** ; `hide_all` ne garde QUE le StatusBar standalone + privacy §13.2-1), privacy → StatusBar, open_app → `AppLauncherBridge` → Kotlin `AppLauncher` (Intents réels : `google.navigation:`/`geo:` Maps, `vnd.youtube:`/ACTION_VIEW YouTube, `getLaunchIntentForPackage` générique). **Menu UI** (`MenuPanel.cs` + registre) : ouvert par geste paume (déjà émis par GestureBridge — **câblé** via `MenuGestureController`) ou voix « menu » ; grille Modes/Apps/Mémoire/Replay/Écran virtuel/Mode payant/Fermer ; sélection gaze+dwell OU pincement → **le même `device_command` que la voix (une seule voie d'exécution)** + UIReceipt. **Câblé aussi** : balayage→cacher l'UI (le gap connu : l'événement Kotlin `SwipeHide` existait, le handler Unity manquait). Métriques `intents_routed`/`intent_unknown`/`grammar_hits`/`multiturn_hits`/`llm_fallbacks`/`cloud_mode`/`cloud_active` sur `/metrics`. **Brancher, pas reconstruire** : aucune modification de `src/` ; tests E32 verts (watcher absorbé proprement).
Statut : terminé — branche `feat/v19-e33-intent-menu` — tests PC : `test_e33_intents` 30/30 (grammaire ≥15 commandes FR/EN → bon intent+params ; multi-tour « c'est quoi ça » puis « zoom dessus »/« traduis-le » → même cible ; toggles → device_command émis ; open_app maps/youtube/package → message correct ; ask_memory → `ask_brain2` appelé (frontière LLM mockée comme E31) → ContextCard + evidence ; dégradé sans LLM → honnête ; mode payant : `local_only` → refus ; permissif + clé factice → `OpenAIProvider` appelé (HTTP mocké) + coût dans la réponse + event StatusBar `cloud_mode` ; provider réel exécuté seulement si `OPENAI_API_KEY` présent, skip sinon ; enrollment absorbé par le routeur). **`pytest tests/v19 -q` = 125 passed, 1 skipped** ; cœur `src/` inchangé ; V18 non touchée. Choix cloud (ADR §E33) : OpenAI `/chat/completions` défaut `gpt-5.4-mini` ~0,01–0,03 €/q ; Gemini `:generateContent` défaut `gemini-2.5-flash` ~0,005–0,02 €/q ; endpoints stables, modèles configurables dans le yaml. **Réserves Unity** (habituelles, pas d'éditeur Unity ici) : tests EditMode `E33MenuDeviceTests` écrits (MenuPanel grille + sélection→command+receipt ; `hide_all` ne garde que le StatusBar ; set_ui_mode→densité broker ; swipe→hide câblé ; palm→toggle menu ; registre MenuPanel) — exécution à la première ouverture Unity ; compilation Kotlin `AppLauncher` + validation S25 différées matériel.

**[x] E34. Proactivité réelle & hot context device** (`services/live-pc/proactive_context.py`, `predictive_retrieval_live.py`, `live_discourse.py`, `morning_briefing.py` ; extensions `brainlive_scene_adapter.py`/`identity_fusion.py`/`intent_router.py`/`live_pipeline.py` ; Unity `Assets/Scripts/Scene/EntityHotUpdate.cs`, `Scene/SceneCache.cs`, `UI/EntityHotUpdateHandler.cs`). **Routeur NL-first** (inversion E33) : raccourci grammaire haute-confiance UNIQUEMENT quand l'ordre *commence* par un mot-clé exact (`pat.match`), sinon **parse LLM live d'abord** (langage naturel : « tu peux me montrer ce que j'ai fait vers 14h ? » → replay), grammaire lenient en **filet** si LLM indisponible ; E33 intact. **Prédictions→live** : `proactive_context.py` charge les prédictions OUVERTES du jour (`predictions_v19`) + interventions nocturnes (`v14_7_intervention_queue`) + clarifications (`v14_8` queued) → HotSceneContext (section compacte, budget) ; **3 nouvelles situations §12.4** dans le scene adapter : prédiction du jour matchée (par le **prédicat même de l'outcome watcher** `_event_matches`) → « tu voulais racheter X », intervention pertinente → delivery, question de clarification en contexte CALME (jamais pendant une conversation) → ContextCard (réponse vocale par le chemin conversation existant). **Récupération dense live** (`predictive_retrieval_live.py`) : `get_predictive_backend().retrieve` sur le sujet courant → section « expériences similaires » ; Qdrant éteint → WARN, dégradé propre. **Discours fin live** (`live_discourse.py`) : tours finaux → worker daemon → `ingest.ingest_transcript` (microscope/discours cœur → tables existantes, aucune nouvelle table) ; file bornée, jamais bloquant. **Prefetch relation pack** : `identity_fusion` nomme une personne → `entity_hot_update` (relation pack compact depuis `build_active_context`) par DataChannel → Unity `SceneCache.SubmitEntityHotUpdate` → ContextCard depuis le cache local. **Briefing du matin** (`morning_briefing.py`) : première session du jour (détectée sur `brainlive_sessions`) → UNE carte « Bonjour — aujourd'hui : … » via `enqueue_delivery` `source_key=briefing:date` (dédup naturelle). **Brancher, pas reconstruire** : cœur `src/` inchangé (appels uniquement) ; anti-spam (dédup/cooldown) ; ingestion jamais bloquée. Métriques `proactive_predictions`/`proactive_interventions`/`clarifications_asked`/`similar_experiences`/`entity_hot_updates`/`discourse_turns`/`discourse_flushes`/`briefings_enqueued` sur `/metrics`.
Statut : terminé — branche `feat/v19-e34-proactivity` — tests PC : `test_e34_proactivity` 10/10 (prédiction ouverte + scène qui matche → suggestion en queue avec evidence, non-match → rien ; clarification + contexte calme → délivrée / conversation active → supprimée ; retrieval dense mocké frontière Qdrant → section présente / Qdrant éteint → dégradé ; briefing 1re session → carte unique / 2e session → dédupliquée ; `entity_hot_update` émis à l'identification, idempotent ; routeur NL-first phrase naturelle → LLM mocké → bon intent / haute-confiance instantanée sans LLM / LLM éteint → filet lenient). **`pytest tests/v19 -q` = 135 passed, 1 skipped** ; cœur `src/` inchangé ; V18 non touchée ; E31-E33 verts. ADR §E34 (NL-first, matching prédiction↔scène par `_event_matches`, cadences proactives, budget). **Réserves Unity** habituelles : EditMode (`EntityHotUpdateHandler`, `SceneCache.SubmitEntityHotUpdate`) exécuté à la première ouverture Unity, différé matériel.

**[x] E35. Sorties : voix, correction, replay** (`services/live-pc/tts_local.py`, `replay_service.py` ; extensions `intent_router.py`/`enrollment_watcher.py`/`worldbrain.py`/`brainlive_scene_adapter.py`/`live_pipeline.py` ; `configs/MODEL_MANIFEST.yaml`+`scripts/fetch_models_v19.py` ; Unity `Scene/EntityHotUpdate.cs`, `Scene/SceneCache.cs`, `UI/EntityHotUpdateHandler.cs` ; web `apps/companion-web/app.js`). **TTS local** : `TTSProvider` unique — `SherpaTTS` (sherpa-onnx OfflineTts, voix Piper/VITS FR+EN référencées url+sha+MIT dans le manifest, non committées, fetch `--tts`) en primaire, repli `Pyttsx3TTS`/`WindowsSapiTTS` (SAPI) derrière la MÊME interface ; `speak(text,lang)->WAV` valide ; message `tts_audio` base64 **borné** sur le DataChannel (trop long → carte texte) ; déclenchement sur réponses courtes quand profil `tts: on` (défaut off) ou « réponds à voix haute » (intent `set_tts` → toggle local `pipeline.set_tts`) ; le viewer web joue le blob audio. **Replay bout-en-bout** : `ReplayService.replay(time)` parse l'heure parlée (E33 `replay`) → plage → assemble keyframes (`vision_frames`), clips (`visual_evidence_assets_v19`), events (`visual_events_v19`), transcript (`turns` via `started_at+start_s`) → `replay_bundle` → UIIntent `virtual_screen` (refs images/clips **bornées**, jamais d'octets bruts) + timeline ContextCard ; router `replay` → service si câblé, sinon device_command ; app.js séquence les images. **Correction objet/lieu bout-en-bout** : `worldbrain.suspend_label`/`suspend_zone` (label corrigé absent des snapshots ET des SceneDeltas suivants — jamais re-promu ; zone effacée de `place_hint`/`active_zone`) ; grammaire scène dans `enrollment_watcher` (« ce n'est pas mon téléphone » → objet, « on n'est pas au bureau » → lieu ; possessifs ajoutés aux stop-names → « ce n'est pas Paul » reste identité) + trace `revise_memory` + confirmation carte. **Hot context généralisé (§9.1, demande utilisateur)** : le scene adapter pousse les 4 types — `spatial_hot_update` (zone reconnue + map_quality + last-seens + **routine du lieu** depuis `brain2_spatial_routine_models`), `entity_hot_update` kind=object (objet durable + relations), `task_hot_update` (but/étape/outils) — dédup par sujet/session, budget par message ; Unity : `SubmitSpatialHotUpdate`/`SubmitTaskHotUpdate` + `ApplyHotUpdate` object-aware (additif, E34 intact), `EntityHotUpdateHandler` réclame les 3 nouveaux types. **Brancher, pas reconstruire** : cœur `src/` inchangé (appels uniquement) ; audio/vidéo jamais non-bornés sur le DataChannel ; E31-E34 verts. Métriques `spatial_hot_updates`/`object_hot_updates`/`task_hot_updates` sur l'adapter.
Statut : terminé — branche `feat/v19-e35-outputs` — tests PC : `test_e35_outputs` 13/13 (TTS provider réel → WAV valide mono 16-bit non vide → message `tts_audio` borné ; replay plage seedée → bundle correct + `virtual_screen`+timeline ; « rejoue 14h30 » via routeur, frontière LLM mockée → bundle de la bonne plage ; correction objet → label suspendu, absent des SceneDeltas suivants + `revise_memory` tracé ; correction lieu → zone effacée ; « ce n'est pas Paul » reste identité ; hot généralisé → les 4 types émis avec routine du lieu, dédup par session ; personne jamais poussée par le chemin objet). **`pytest tests/v19 -q` = 148 passed, 1 skipped** ; cœur `src/` inchangé ; V18 non touchée ; E31-E34 verts. ADR §E35 (choix TTS/voix/licences, transport replay par refs, généralisation hot). **Réserves Unity** habituelles : EditMode (`SceneCache.SubmitSpatialHotUpdate`/`SubmitTaskHotUpdate`, `EntityHotUpdateHandler`) exécuté à la première ouverture Unity, différé matériel ; voix TTS téléchargées par `fetch_models_v19.py --tts` (sha256 épinglé au premier fetch).

**[x] E36. Ops de prod : accès hors-maison + quotas stockage + profil d'inconnu VLM** (`services/live-pc/endpoint_resolver.py`, `stranger_profile.py` ; extensions `degraded.py`/`live_pipeline.py`/`sessionhub_http.py`/`simulators/fake_xr_device.py` ; Unity `MLOmegaConfig.cs`+`SessionPairing.cs` ; Kotlin `SignalingClient.kt` ; web `apps/companion-web/app.js` ; `scripts/DOCTOR_MLOMEGA_V19.ps1` ; `docs/OUTSIDE_ACCESS.md`). **Backup chiffré DIFFÉRÉ** (décision utilisateur 2026-07-05 — usage perso, géré manuellement ; noté dans PROD_BACKLOG). **Accès hors-maison (LE livrable)** : la config accepte une LISTE ordonnée d'endpoints PC (`endpoints: [{name:lan,host:192.168…}, {name:tailscale,host:100.x…}]`) ; `EndpointResolver` sonde `/health` **dans l'ordre** (LAN d'abord), bascule (**failover**) sur le premier joignable, et **re-teste le premier à la reconnexion** (retour maison → retour LAN) ; aucun endpoint joignable → verdict **`pc_unreachable`** propre (le chemin réflexe device tourne quand même, jamais d'exception). Câblé Python (`fake_xr_device --endpoints` + `pipeline.resolve_endpoints`), Unity (`MLOmegaConfig` liste additive + `SessionPairing` sonde `/health` et bascule), Kotlin (`SignalingClient` liste + failover), companion-web (`?endpoints=…`). **WebRTC à travers le tunnel** : en VPN Tailscale l'IP `100.x` est vue comme **host candidate** ICE → média direct **sans TURN/relais** (local-first) ; serveur bind `0.0.0.0` par défaut (option `bind_host` profil), token de session = barrière (déjà en place). **Dégradation WAN** : profils réseau **lan/wan distincts** (`degraded.py`) — WAN tolère la latence 4G (seuil relevé) et **abaisse la résolution vidéo cible** (720p→540p) sans toucher les cadences détecteur PC (locales) ni les réflexes device (indépendants du PC) ; métriques `active_endpoint`/`active_link`/`target_video_height` sur `/metrics`. **Doc opérateur** `docs/OUTSIDE_ACCESS.md` : Tailscale pas-à-pas (PC Windows + Android), récupération IP `100.x`, remplissage profil, **checklist de validation 4G réelle**, alternatives (WireGuard manuel, port forwarding déconseillé), rappel dégradé honnête. **Quotas stockage doctor** (`-Quota`) : tailles réelles DB SQLite / `models/` / evidence keyframes+clips / tampon-jour, seuils WARN/FAIL configurables (profil `storage_quota`), suggestion de purge (close-day purge déjà le tampon — référencé). **Profil temporaire d'inconnu via VLM** (`stranger_profile.py`) : person track anonyme persistant (`> stable_seconds`, config) → **UN** crop → VLM local (chemin `VlmCrop` existant, un-job, dégradé honnête si Ollama off) → description structurée (apparence/tenue/âge/indice de rôle « tablier → probably baker ») → entité provisoire WorldBrain **`truth_level=inferred`, JAMAIS un nom** + `entity_hot_update` « ? boulanger » (hypothèse §17.2) ; **fusionnable** : enrollment E32 ensuite → `fuse_into_named` folde la description dans l'entité nommée (description conservée en attribut, `truth_level=observed`). Dédup : **max 1 profil VLM par track par session**. **Brancher, pas reconstruire** : cœur `src/` inchangé (appels uniquement) ; jamais de nom inventé ; pas de TURN par défaut ; backup non implémenté ; E31-E35 verts.
Statut : terminé — branche `feat/v19-e36-ops` — tests PC : `test_e36_ops` 15/15 (failover : LAN up → LAN ; LAN down → bascule endpoint 2 ; les deux down → `pc_unreachable` propre ; reconnexion → retour au premier ; session+`/health` complets via le 2e endpoint, deux SessionHubs localhost sur des ports différents ; profils wan distincts + override config ; stranger : track anonyme persistant → VLM mocké format réel → entité `inferred` « ? baker » + hot_update sans nom → enrollment → fusion dans l'entité nommée, description conservée ; jamais deux profils VLM pour un track ; VLM off → dégradé honnête, aucune description inventée ; jamais de nom extrait ; doctor `-Quota` exécuté → sortie quotas DB/models/evidence/tampon-jour, 0 FAIL). **`pytest tests/v19 -q` = 163 passed, 1 skipped** ; cœur `src/` inchangé ; V18 non touchée ; E31-E35 verts. ADR §E36 (choix failover, seuils wan, format profil provisoire). **Validation 4G réelle à faire par l'utilisateur** avec la checklist `docs/OUTSIDE_ACCESS.md` (health depuis 4G, session via tunnel, latence attendue, retour LAN au retour maison). **Réserves Unity** habituelles : EditMode (`SessionPairing` failover, `MLOmegaConfig` liste) exécuté à la première ouverture Unity, différé matériel ; compilation Kotlin `SignalingClient` différée matériel.

**[x] E37. Nuit complète + owner** (`services/live-pc/audio_archive.py`, `owner_setup.py` ; extensions `live_pipeline.py`/`intent_router.py`/`conversation_bridge.py`/`v19_keyframes` writers/`gateway.py`). **La faille critique réparée** : les segments VAD d'audiort sont archivés en WAV + events `speech_segment` dans `brainlive_sensor_events` au **format exact du Phone Bridge V18.8** (retrouvé dans le cœur, pas inventé) → le pipeline nocturne complet (WhisperX HQ + diarisation pyannote + attribution voix→personID) se rallume sans modification du moteur. **Complémentarité audio+vision prouvée** : session simulée parole+keyframes → UN bundle avec `audio_timeline_json` ET `vision_timeline_json` non vides → `bundles_require_deep_audio()` True. **Owner V19** : « configure ma voix » / « c'est moi qui parle » (voix + menu, patterns owner_enroll AVANT set_tts — conflit `parle` corrigé) → `enroll_voice(is_user=True)` galerie partagée nuit/live → tours du porteur attribués owner ; doctor WARN si voix owner non enrôlée. **Vision owner** : `memory_owner_id` garanti sur toute la chaîne visuelle (keyframe sans person_id = impossible). **Garde-fou pose** : `pose_valid=False` sur les enveloppes placeholder — jamais consommées par spatial/SceneDelta.
Statut : terminé — branche `feat/v19-e37-nightly-owner` — tests : `test_e37_nightly` 7/7 (format speech_segment conforme assembleur+deep audio ; bundle bi-modal ; owner_enroll routé y c. reformulations ; attribution owner sur tours suivants ; keyframe ownerless rejetée ; pose placeholder ignorée) ; **`pytest tests/v19 -q` = 170 passed, 1 skipped** ; cœur `src/` inchangé. Réserve : run WhisperX/pyannote complet sur l'audio archivé = close-day E30-A (stack GPU du cœur).

**[x] E38. Intelligence fine** (`services/live-pc/hypothesis_engine.py`, `attribute_memory.py`, `routine_associations.py` ; extensions `worldbrain.py`/`live_pipeline.py`). **Tout générique — AUCUN exemple codé en dur** (pas de lexique de prénoms, pas de pattern « prix », aucune paire objet/routine ; les exemples ne vivent que dans les tests). **§1 Hypothèses d'identité auto-confirmées** : signal prénom-adressé par **extraction LLM générique** (JSON strict, frontière injectable mockable — pas de regex de noms) ; heuristique documentée nom→personne (locuteur précédent/track actif) ; store multi-sessions SQLite service-local (occurrences {session, source, confidence, evidence}) où concordance renforce / contradiction affaiblit ; promotion auto à seuils configurables (`min_occurrences` × `min_sessions` × `min_cumulative_confidence`) → attribut `observed` sur l'entité WorldBrain + **UIIntent d'annonce jamais silencieux** (« J'ai déduit : c'est probablement … — corrige-moi ») ; correction vocale E32 casse l'hypothèse ; pont clarification_inbox (lit `v14_5_people_identity_hypotheses`, résout côté service avec provenance `machine_convergence` — **cœur non modifié**, ADR sur le choix). **§2 Attributs bi-modaux** : store générique d'observations `(sujet, attribut, valeur, source: ocr|vlm|heard)` alimenté par OCR ROI (scission `clé: valeur` générique), attributs VLM, et faits ENTENDUS (extraction LLM générique — pas de pattern « prix ») ; diff inter-sessions même sujet+attribut → nouveau `ChangeEvent` **`attribute_changed`** (before/after + **sources des deux côtés** : un VU peut contredire un ENTENDU) persisté dans `visual_events_v19` ; apparence des personnes connues via **le même mécanisme** (descripteur VLM → diff = `attribute_changed`, pas de chemin spécial). **§3 Routine→objet appris** : co-occurrences comptées depuis `brain2_spatial_routine_models` + `visual_events_v19` (score = cooccurrence / fréquence totale objet) → approche d'une zone/entité dont l'objet associé dépasse le seuil → **push proactif du last-seen** (réutilise `push_object_hot`) + suggestion discrète si l'objet n'est pas visible ; aucune paire en dur. **§4 Câblage** : tours → hypothesis_engine + attribute_memory ; OCR/VLM → attribute_memory ; approche zone → routine_associations ; métriques `hypotheses_active`/`auto_promotions`/`clarifications_resolved`/`attribute_changes`/`routine_pushes`.
Statut : terminé — branche `feat/v19-e38-fine-intel` — tests : `test_e38_fine_intel` 11/11 (promotion 3 tours/2 sessions + annonce ; contradiction → pas de promotion ; correction → cassée ; pont clarification sans toucher le cœur ; scène ambiguë → drop ; attribut OCR→ENTENDU bi-modal ; apparence personne ; routine→objet le bon et pas un autre + dédup + pas de suggestion si visible ; valeurs arbitraires variées) ; **`pytest tests/v19 -q` = 181 passed, 1 skipped** ; cœur `src/` inchangé. Réserve : les extractions LLM tournent sur le LLM local en prod (dégradation honnête si Ollama absent).

**E30. Checkpoint final.** Gates G1→G8 réels ; benchs P50/P95 publiés (`docs/BENCH_RESULTS.md`) ; session 3h sans fuite VRAM ; doctor `-Full -Xr -Vision -World -Delivery` vert ; tests V18 verts ; démo capture-only sur second téléphone.

---

## 6. Pièges connus (résumé — chacun a déjà coûté une erreur à quelqu'un)

1. `build_active_context` est patché (`install`), l'original est dans `brainlive_v15` → étendre via `_FIELD_TABLE`, jamais re-patcher.
2. `vision_frames` est immuable → `insert_only`, jamais `upsert`.
3. Tout ingest sans `memory_owner_id` explicite → `ScopeError`.
4. Toute preuve d'une table non listée dans les trois dicts de `v18_life_model` → `ScopeError`.
5. Les stages du close-day sont une liste en dur : 4 endroits à modifier (fn, `_status_ok`, `_stage_identifier`, `expected`/`required_stages`).
6. Plusieurs modules importent `runtime_v18_7` (pas `v18_8`) → suivre l'import du module étendu, ne pas « réparer ».
7. `enqueue_delivery` exige `source_key` significatif (clé de dédup) et `decision` dans l'ensemble autorisé.
8. `label_source` de la calibration est contraint par CHECK SQL → `strict_verifier` pour l'outcome watcher.
9. Les champs ajoutés au hot capsule doivent passer par `_measure()`/réduction — une clé hors budget casse le contrat d'omission traçable.
10. `ollama_unload` peut échouer silencieusement → le GpuArbiter re-mesure la VRAM après chaque unload.
11. Le nom réel est `brainlive_active_contexts`, pas `active_contexts` ; les sorties deep vision vont dans `brainlive_deep_vision_observations_v161`, pas `vision_scene_observations`.
12. La table de queue delivery s'appelle `brainlive_intervention_delivery_queue` — ne pas en créer une seconde.

## E46-C — Fenêtre LLM, reprise Android et UI PhoneOnly (SOURCE + TESTS PC — 2026-07-07)

- Le post-stop est déjà découpé par `assemble_event_bundles` : bundles non chevauchants, coupure sur silence/scène/lieu et limite de 25 minutes. Le flow post-stop checkpoint chaque conversation séparément.
- Qwen3.5:9b expose 262144 tokens natifs, mais Ollama le chargeait avec `CONTEXT=4096`. `OllamaJsonClient` transmet maintenant `num_ctx=4096` en live et `num_ctx=16384` en post-stop. Mesure RTX 3070 : Qwen3.5:9b reste 100% GPU à 16384.
- La sortie post-stop reste plafonnée à 4096. `done_reason=length` rejette tout le résultat ; aucun JSON partiel n'est écrit et les preuves restent en base.
- Session/token Android sont chiffrés AES-GCM par Android Keystore. Après crash, `SessionPairing` renouvelle le même `session_id`; les credentials sont effacés après CloseDay `completed` ou refus du renew.
- Le mono-runtime accepte une nouvelle session seulement après fin explicite et CloseDay terminé. Une session concurrente reste refusée.
- `segments_finals` lit désormais `AudioRT.finals_emitted`, indépendamment des tours BrainLive.
- La scène PhoneOnly instancie maintenant la prévisualisation caméra, `SceneCache`, `LocalTrackStore`, `TransportIntentSource`, `UIIntentBroker`, `UIRuntime`, `StatusBar`, receipts, hot updates, `SceneDeltaTransportHandler` et commandes device. Aucun driver de démo n'est inclus.
- Le runtime PC active désormais identité, replay, stranger profiles et intelligence fine. Il conserve exactement la dernière frame pour les commandes déictiques telles que « c'est quoi ça ? ».
- La queue H1 BrainLive est maintenant consommée par un `DeliveryAdapter` DataChannel. Une absence de canal ne marque jamais une carte comme livrée; elle reste queued jusqu'à reconnexion. Les `UIReceipt` retournent au writer V18.8.
- Tests ciblés : budget Ollama, runtime PhoneOnly, câblage Android, SessionHub/E36, queue H1→DataChannel et dernière frame voix→VisionRT sont verts.
- Reste séparé : traduction locale Android, modèles reflex embarqués et gestes matériels. Leur code existe mais ils ne sont pas déclarés validés avant assets/build/téléphone.

## E46-D — Point d'arrêt contrôlé Android/Unity (2026-07-07)

Travail effectivement terminé avant l'arrêt demandé :

- Microsoft OpenJDK 17.0.19 et Gradle 8.7 local ont été installés; le SDK Android système contient au moins la plateforme 34, build-tools 34.0.0 et `adb`.
- `scripts/BUILD_ANDROID_PLUGINS.ps1` sélectionne JDK 17, SDK Android et Gradle local, puis nettoie les doublons Kotlin/annotations avant import Unity.
- Les erreurs Kotlin réelles révélées par Gradle ont été corrigées : KDoc imbriqué, callbacks SDP retournant un booléen, et conversion YUV WebRTC indépendante dans `UnityFrameCapturer`.
- La dépendance sherpa-onnx Android officielle v1.12.10 a été épinglée localement (SHA-256 `F51F59368674FAEE85B655129C52F9E87BEEF287BF22F35D023BAB83BECAD74C`) après l'échec JitPack 401.
- Les tests/builds Gradle des modules `livetransport` et `reflexvision` ont réussi; leurs AAR et dépendances ont été exportés dans `apps/xr-mobile/Assets/Plugins/Android`.
- Unity Editor 6000.0.23f1 est installé dans `C:\Program Files\Unity\Hub\Editor\6000.0.23f1`; version du binaire vérifiée : `6000.0.23.1853284`.
- Le dossier Unity `AndroidPlayer` existe, mais son contrôle immédiat ne trouve ni `SDK`, ni `NDK`, ni `OpenJDK` embarqués. Android Build Support doit donc être considéré partiel tant que ces sous-modules ne sont pas installés ou qu'un SDK/JDK externe n'est pas configuré explicitement.
- Aucun processus `Unity`/`UnitySetup` n'était encore actif au point d'arrêt. Aucune compilation Unity/APK n'a été lancée.

Tests exécutés avant l'arrêt : suites ciblées PhoneOnly/SessionHub/UI/LLM vertes; build/test JVM des deux plugins vert. La suite V19 complète avait donné `206 passed, 2 skipped, 1 failed`; l'unique scénario de traduction PC obsolète a été corrigé mais la suite complète n'a pas été relancée. Le contrôle historique V18 a donné `110 passed, 1 failed`; l'échec exige exactement 5 étapes CloseDay alors que V19 en expose 10. L'invariant interdisant `turns.created_at` a passé, mais le rapport d'audit signale encore une référence de fallback dans `v18_life_model.py` à examiner avant toute certification.

### Tâche interrompue et reprise exacte

La tâche active était le préflight final du point 8 : obtenir un projet Unity importable, compiler la scène PhoneOnly, produire un APK, puis préparer le test matériel. À la prochaine session, reprendre dans cet ordre :

1. Vérifier l'installation Unity et compléter Android Build Support (`SDK`, `NDK`, `OpenJDK`) ou configurer explicitement les outils externes déjà installés; vérifier la licence Unity en batchmode.
2. Relancer `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\BUILD_ANDROID_PLUGINS.ps1` et conserver les hashes des AAR exportés.
3. Importer le projet Unity en batchmode et lancer les tests EditMode; traiter toutes les erreurs UPM/XREAL, asmdef, manifest et dépendances Android avant de construire une scène.
4. Rejouer `PhoneOnlySceneBuilder.BuildScene`; vérifier dans la scène générée `SessionPairing`, capture caméra, transport, renderer UI, receipts et action explicite de fin.
5. Ajouter/valider une méthode Editor reproductible de build Android : target Android, IL2CPP, ARM64, min/target SDK, profil PhoneOnly et endpoint LAN/Tailscale; construire l'APK.
6. Avant le test matériel, trier les constats d'audit encore ouverts : conversion audio aiortc réelle, gel/drain et `AudioRT.flush()`, callback audio en vol, arrêt ingress/video, ID BrainLive unique dans WorldBrain, exécution CloseDay dans l'environnement cœur, archivage VAD indépendant du succès ASR, `PersonId`, token renouvelé côté Kotlin, ICE/reconnexion/teardown, et chemin texture Unity↔WebRTC.
7. Refaire les suites V19 complètes et le contrôle V18 ciblé après ces corrections; ne pas modifier le cœur V18.8 sans preuve, et supprimer toute dépendance réelle à `turns.created_at`.
8. Connecter un téléphone Android par `adb`, installer l'APK, accorder caméra/micro, démarrer `-LivePhone`, puis vérifier vidéo, Opus→PCM→AudioRT, BrainLive, keyframes/WAV, UI/cartes/commandes et métriques.
9. Tester perte réseau/reprise sans CloseDay, puis l'action explicite `Terminer la session et lancer CloseDay`; vérifier drain borné, `end_session` une fois, vrai `live_session_id`, CloseDay idempotent et progression Android.
10. Résoudre séparément les gates produit non encore validés : traduction live locale Android, arbitrage d'un micro partagé avec WebRTC, modèles reflex/gestes, TTS et sémantique de plusieurs sessions le même jour.

État honnête au point d'arrêt : AAR construits, Editor Unity installé, mais aucun import Unity, test EditMode, APK, installation `adb` ou test Android→PC n'a encore été réalisé.

### 2026-07-07 — Clôture E46-D : licence activée, étapes 1→7 TOUTES terminées

- [x] 1. Toolchain Android externe complet : NDK r23b (23.1.7779620) + SDK android-34 + build-tools + platform-tools + JDK17 + Gradle 8.7 + **CMake 3.22.1** ajouté via sdkmanager (manquait pour IL2CPP). Env vars User posées (ANDROID_HOME/SDK_ROOT/NDK_ROOT/NDK_HOME/JAVA_HOME). Statut : terminé — commit à venir — pas de suite dédiée (config outils).
- [x] 2. AAR construits/exportés vers `apps/xr-mobile/Assets/Plugins/Android`, dédup Kotlin/annotations OK. SHA-256 : `mlomega-livetransport.aar` 19d04664b305f050cc77e46d8d51a3d2b4b55d9badd5564620901b83db14a715, `mlomega-reflexvision.aar` c1b128cdd9bd7a9f7040fe3e5f4f7b81b307a091d117b7419bd392604f558ed1, `sherpa-onnx-1.12.10.aar` f51f59368674faee85b655129c52f9e87beef287bf22f35d023bab83becad74c (= pin DECISIONS). Statut : terminé — tests Gradle `testDebugUnitTest`+`exportUnityRelease` verts.
- [x] 3. Licence Unity activée par l'utilisateur (Personal, login Unity ID interactif). Import Unity batchmode + premier passage compilateur réel : 10 familles de fixes, dont 2 critiques —
  - **ContractJson DateParseHandling** : `JsonSerializerSettings` sans `DateParseHandling.None` laissait Json.NET parser les timestamps ISO en `DateTime` selon la culture locale, corrompant les valeurs à la sérialisation/désérialisation.
  - **ParseObject/JObject.Parse** : même piège de culture sur le chemin de parsing brut (`JObject.Parse`), corrigé en cohérence avec ContractJson.
  - Autres fixes : manifest `_comment_xreal` sorti de `dependencies` (référence commentée mal placée bloquait le résolveur UPM) ; module Audio manifest/WebCamTexture activé ; alias `Pose` de contrat renommé (collision avec `UnityEngine.Pose`) ; structs SceneCache renommés en `*Entry` (collision CS0102 entre types imbriqués) ; GlassPanel passé en matériau par instance (UGUI partageait un matériau global, tout panneau changeait la teinte de tous) ; usings Editor nettoyés + `Scene` qualifié (ambiguïté `UnityEngine.SceneManagement.Scene`) ; broker Cfg passé en lazy-init (ordre de boot EditMode vs runtime) ; FlushNow agrégé au tour finalisé (évite un flush partiel en cours de tour) ; CMake 3.22.1 installé (requis IL2CPP absent du toolchain externe).
  - Statut : terminé — **EditMode : 59/59 verts**.
- [x] 4. Scène PhoneOnly générée : `PhoneOnly.unity` + `MLOmegaPhoneOnly.asset` + `SceneCacheConfig` + `UITheme` (assets de config) — racines Session/Phone Camera/EventSystem, câblage vérifié (SessionPairing, EyeCaptureSource+PhoneCameraPreview, LiveTransportBridge, UIRuntime, UIReceiptTransportSink, SceneDelta/commandes, PhoneOnlySessionCoordinator). Statut : terminé.
- [x] 5. Build APK reproductible via `Editor/AndroidBuild.cs` (`MLOmega.XR.Editor.AndroidBuild.BuildApk`) : **`build/android/mlomega-phoneonly.apk` — 54,6 Mo — SHA-256 `31762C5032947FFFACE94BC3F4F096366518B83D0BE7C86831C3D60AD9C53445`** — IL2CPP/ARM64, minSdk29/targetSdk34, define `MLOMEGA_PHONE_ONLY`, endpoint LAN (192.168.1.199:8710) injecté via env. Statut : terminé.
- [x] 6. Triage audit : 11/11 constats réfutés (déjà corrects, aucun fix code requis) + invariant `turns.created_at` réfuté (`v18_life_model` ordonne par `start_s`, jamais `created_at`). Détail inchangé, voir `E46D_STATE.md`. Statut : terminé.
- [x] 7. Suites finales : V19 complète **207 passed, 2 skipped, 0 failed** ; V18 ciblé **5 passed, 0 failed** (inclut `test_owner_scoped_turn_query_uses_conversation_time_not_turn_created_at` vert). Cœur V18.8 non modifié. Statut : terminé.

Install device : `adb install -r apps\xr-mobile\build\android\mlomega-phoneonly.apk`. Reste ouvert (hors périmètre E46-D) : test S25 réel, gates produit Android-local (ASR/traduction/gestes/TTS locaux, arbitrage micro, sémantique multi-sessions/jour) non faits par décision explicite du 2026-07-07 (premier build livré sans), E30-A/close-day (à faire en session réelle, pas synthétique — décision utilisateur), E30-B.


---

## E47 — Gates Android-local : autonomie du téléphone (À FAIRE, après le premier test device)

**Pourquoi c'est une étape séparée** (décision 2026-07-07) : le premier APK n'active pas l'ASR/gestes/TTS locaux — deux micros concurrents (AudioRecord sherpa + WebRTC) sans arbitrage sont interdits, et les modèles embarqués n'ont jamais tourné sur un vrai S25. Les AAR (sherpa-onnx 1.12.10, MediaPipe tasks-vision 0.10.29) sont DÉJÀ dans l'APK — E47 les active, il ne réinstalle rien.

**Livrables :**
1. **Arbitrage micro (le cœur de l'étape)** : UNE seule source audio — option A (préférée) : le flux micro WebRTC existant est dupliqué côté Kotlin (callback audio du track local AVANT envoi) et nourrit sherpa-onnx (VAD+ASR+KWS) en parallèle de l'envoi PC — zéro second AudioRecord ; option B (repli si l'API GetStream ne l'expose pas proprement) : un AudioRecord unique possédé par nous, fan-out vers (a) une source WebRTC custom et (b) sherpa. Choisir après lecture de l'API du track audio GetStream, ADR obligatoire. **[x] option A — fait (e47a)** : `JavaAudioDeviceModule` explicite (`.setSamplesReadyCallback`, source `VOICE_RECOGNITION`) passé à `PeerConnectionFactory.builder().setAudioDeviceModule(...)` ; les MÊMES samples PCM16 sont fan-outés via `MicAudioFanout` vers un `PcmFeed` ; `AsrKwsService` refactoré consomme `asPcmSink()` (plus de second AudioRecord ; ancien AudioRecord gardé en mode legacy `ownMicrophone=true` sans WebRTC) ; câblage Unity `AsrBridge→LiveTransportBridge.AttachPcmFeed`. Tests JVM `MicAudioFanoutTest` (6, fan-out reçoit les mêmes samples byte-for-byte).
2. **Provisioning des modèles device** : zipformer streaming FR+EN + KWS (wake word) + tasks MediaPipe (hand_landmarker, gesture_recognizer) copiés au premier lancement depuis le PC (endpoint de download servi par sessionhub, sha vérifié, stockage app) — pas de poids dans l'APK (taille). **[x] côté PC — fait (e47c)** : manifeste `device:` + `fetch_models_v19.py --device` + endpoints `GET /models/device/manifest` et `GET /models/device/{name}` (token session, sha vérifié) ; reste Kotlin : download au premier lancement + stockage app.
3. **Activation gestes** : frames caméra (déjà capturées pour WebRTC) partagées vers GesturePipeline (LIVE_STREAM) sous budget scheduler E26 ; câbler les événements palm/swipe/pinch déjà attendus côté Unity (MenuGestureController existant). **[x] — fait (e47b)** : `GestureBridge` s'abonne à `EyeCaptureSource.OnFrame`, downscale 256 px + throttle 10-15 fps (`FrameThrottle` autoritaire côté natif) → `Texture→Bitmap ARGB_8888` (JNI) → `pushFrame` ; alimenté uniquement quand le `ReflexScheduler` a activé le pipeline (§9.4). Chaîne événements : palm/swipe/pinch-commit déjà via `MenuGestureController` ; **pinch→zoom `LensWindowSkill` désormais câblé** (le handler existait mais n'était abonné nulle part) via `ReflexScheduler`. Modèles depuis `getExternalFilesDir()/models/`. Tests JVM : `FrameThrottleTest` (drop/clamp) + `GesturePipelineActivationTest` (on-demand). Reste device : compile hardware + un geste par type sur S25.
4. **Wake word** : KWS sherpa actif → WakeWordGate Unity (existant) passe du mode « tout écouté » (build 1, PC-side) au mode gated : hors session de commande, l'ASR PC continue (mémoire de vie) mais le ROUTAGE d'intents exige le mot d'éveil — politique configurable dans MLOmegaConfig. **[x] côté PC — fait (e47c)** : `wake_word_policy: open|gated` (profil, défaut open) dans `live_pipeline.py` ; en gated seuls les tours `is_command` (flag DataChannel / fenêtre wake-word armée par contrôle) sont routés en intents, TOUS les tours vont en mémoire (conversation_bridge), tour sans flag = compat open ; `phoneonly_runtime` arme la fenêtre sur message contrôle ; 7 tests. Reste device : KWS sherpa → envoi du flag `is_command`. **[x] côté device — fait (e47a)** : wake word = mot choisi (`MLOmegaConfig.WakeWord`, défaut « omega », encodé par `KeywordEncoder`) ; hit KWS → `AsrKwsService.openCommandWindow()` (fenêtre `commandWindowMs` configurable) ; capture JAMAIS coupée (tout l'audio continue au PC), le mot ne gate QUE le routage ; les finaux dans la fenêtre → `onTranscript(..., isCommand=true)` → `LiveTransportBridge.SendTranscriptSegment` (champ additif `is_command` du message `device_transcript` DataChannel). Tests JVM `CommandWindowTest` (6, timing) + `KeywordEncoderTest` (mot custom).
5. **TTS device (optionnel)** : voix sherpa locale pour le mode sans-PC ; le TTS PC (E35) reste le défaut connecté.
6. **Multi-sessions/jour (PC, Python — pas de rebuild Android)** : close_brainlive_day est déjà keyé (person_id, package_date) avec stages repris — définir/tester : session 2 du même jour → le close-day du jour REJOUE les stages sur les données cumulées (resume) ou complète ; garantir idempotence assembler/bundles sur re-run ; test v19 dédié. **[x] — fait (e47c)** : `close_brainlive_day` court-circuite si la ligne du jour `v18_close_day_runs` est `completed` (AVANT `force`) → chemin reopen service-side additif `run_phoneonly_close_day.py --allow-rerun` (UPDATE ciblé `status='reopened'`, cœur non modifié) ; l'appel suivant crée un run NEUF via `begin_or_resume_run` (lookup actif-only ignore le run completed) et rejoue les stages sur les données cumulées, idempotent par `stable_id`+upsert ; `SinglePhoneRuntimeManager` arme `allow_rerun` sur la 2e session du jour ; 6 tests. ADR détaillé DECISIONS.md §E47C.
7. **Rebuild + validation device** : `AndroidBuild.BuildApk` (incrémental, ~5-10 min toolchain chaud) ; tests device : wake word, un geste par type, sous-titres offline (PC coupé), pas de conflit micro (WebRTC + sherpa simultanés stables 10 min).

**Estimation** : une étape standard (une session de travail), la moitié Kotlin/Unity, le point 6 en Python pur. Recompilation : APK uniquement, incrémentale ; rien côté PC sauf point 6.

**E47 — CLÔTURE (2026-07-07)** : livrables 1-4 et 6 tous [x] (voir lignes ci-dessus, tags e47a/e47b/e47c) ; livrable 5 (TTS device) DIFFÉRÉ volontairement — le TTS PC (E35) couvre le mode connecté, la voix locale viendra avec le mode sans-PC complet ; livrable 7 : **APK v2 rebuild OK — 54,6 Mo — SHA-256 BCC6899740582026B964FB6B43127405374241CA91EECFFD22C3E0AB13315A0C** (AAR fan-out micro + gestes + KWS inclus, tests JVM 42 verts, pytest 226 verts après réconciliation du test wiring/ContractJson). **Validation device S25 à faire par l'utilisateur** : wake word, un geste par type, sous-titres PC coupé, micro simultané WebRTC+sherpa stable 10 min. ⚠️ Provisioning téléphone : les endpoints PC existent (`/models/device/*`) mais le CLIENT de téléchargement côté app n'est pas encore écrit — pour ce build, pousser les modèles à la main : `python scripts\fetch_models_v19.py --device` puis `adb push models\device\. /sdcard/Android/data/<package>/files/models/` (follow-up court noté au backlog).

---

## E48→E52 — Plan d'actions (2026-07-08)

Les étapes suivantes sont définies et suivies dans **`PROD_BACKLOG.md`** (section « Plan d'actions E48→E52 ») : **E48-A** confort produit ; **E48-B** réflexes restants (HandAction → mode aide universel version A, ChangeAttention live) ; **E49** lunettes XREAL (gate G1) ; **E50** dashboard mémoire lecture seule (intégration MemoryLight adapté V19) ; **E51** installateur/guide de bienvenue interactif ; **E52** README complet. Au fil de l'exécution, chaque étape close reçoit sa section détaillée ici (comme E46-D/E47) + ADR dans `DECISIONS.md`.

---

## E48-A — Confort produit : modèles device, dehors, traduction live (EN COURS — 2026-07-08)

**Livrables :**
1. **Client de téléchargement des modèles dans l'app** (remplace l'`adb push` manuel). **[x] — fait (e48a-1)** : `ModelProvisioner`/`DeviceModelManifest`/`ModelProvisioningCallbacks` (livetransport — seul module avec endpoint+token+OkHttp) : GET manifest → download des manquants → sha-256 vérifié (`X-Model-Sha256`) → écriture atomique `.part`+rename → extraction tar.bz2 (commons-compress) + normalisation des noms sherpa ; tâche de fond, jamais bloquant ; Unity `ModelProvisioningBridge` déclenché après pairing, progression `dl:<modèle> NN%` sur la StatusBar, re-arm des bridges au prochain lancement (pas de re-arm à chaud — invariant micro unique, ADR §E48-A) ; dégradé honnête (garde-fous AsrBridge/GestureBridge). Petits modèles embarqués dans l'APK via `AndroidBuild` → StreamingAssets → copie au 1er lancement (`StreamingAssetsModelInstaller`) : KWS + 2 tasks MediaPipe + silero_vad (~35 Mo, APK ~90 Mo) ; les 2 ASR streaming (296/380 Mo) restent téléchargés. **Gap corrigé** : `silero_vad.onnx` (gate de tout le flux ASR/KWS) manquait du manifeste device — ajouté (MIT), épinglé, embarqué.
2. **Tailscale / mode dehors** : install PC+téléphone (OUTSIDE_ACCESS.md §2-3), endpoints ordonnés LAN→100.x (profil + asset Unity §4), validation checklist §8 sur vraie 4G. Le failover est déjà codé (E36/E44) — étape de CONFIG + VALIDATION. **[x] côté PC — fait (e48a-2)** : Tailscale installé (winget) et connecté — PC `pc-will` = `100.113.42.19` ; endpoints ordonnés lan(192.168.1.199)→tailscale(100.113.42.19) posés dans `configs/user_profile.yaml` ET `MLOmegaPhoneOnly.asset` (`_endpoints`, pris au prochain build APK). **Reste utilisateur** : installer Tailscale sur le S25 (Play Store, MÊME compte), activer le VPN, puis checklist §8 sur vraie 4G après le rebuild APK.
3. **Traduction live continue = réflexe device, offline** (décision utilisateur 2026-07-08). **[x] — fait (e48a-3)** : ONNX Runtime + OPUS-MT fr-en/en-fr int8 (Xenova, Apache-2.0, ~100 Mo/direction, 6 entrées manifeste provisionnées comme le reste) ; `MarianTokenizer` pur Kotlin ; `OfflineTranslator` greedy KV-cache (finals only, lazy, idle-release 60 s, 1 direction résidente) ; `OfflineTranslatorBridge` JNI ; `TranslateBridge` Unity → traduction sous le sous-titre + `translation_hot` ; toggle menu « Traduire » + intents « traduis en direct »/« stop traduction » → `device_command translate_live`. Coexistence ORT : API Java 1.17.1 alignée sur la .so sherpa, exportée `mlomega-onnxruntime.aar`. Détail ADR §E48-A-3.
4. **RÉPARATION couche réflexe PhoneOnly** (découverte e48a-3) : `PhoneOnlySceneBuilder` n'ajoutait aucun composant réflexe à la scène — les gates E47 de l'APK v2 n'avaient pas d'hôte runtime. Builder corrigé (LocalIntentSource+bootstrap, AsrBridge, GestureBridge, WakeWordGate, 5 skills, TranslateBridge, ReflexScheduler câblé). **[x] source ; scène à régénérer au prochain build.**

**Tests (2026-07-08)** : JVM **77/77** (livetransport 27, reflexvision 50 — dont test d'intégration desktop qui traduit une vraie phrase sur les modèles réels) ; pytest ciblés intents/provisioning/gating **43/43** (1 skip clé OpenAI). AAR : livetransport `8092BF62…`, reflexvision `1B756886…`, onnxruntime `67704465…`.

**Reste pour clore E48-A** : livrable 2 (login Tailscale + S25 + endpoints + checklist 4G) ; régénérer la scène + rebuild APK v3 (décision : APRÈS E48-B, un seul rebuild + mise à jour FIRST_TRY_ANDROID) ; validation device S25.

---

## E48-B — ChangeAttention live (FAIT — 2026-07-08 ; HandAction recadré en E53)

Périmètre recadré (décision utilisateur 2026-07-08) : le mode aide universel version A est rejeté (« soit on le fait bien, soit on ne le fait pas ») — la version complète part en **E53** au backlog avec l'analyse coût/viabilité (2-6 $/h événementiel vs 20-40 $/h force brute ; bloqueurs : latence cloud sur caméra de tête, pointage spatial fin des VLM non fiable, validation auto fiable seulement sur le grossier) et un gate d'entrée mesurable (banc pointage spatial ≥ 90 % sur 10 scènes S25).

**Livré (e48b)** : `services/live-pc/change_attention.py` — cue instantané « quelque chose a changé ici » à la ré-entrée d'une zone (PC-side, zéro coût téléphone). Sortie de zone → état d'entités figé ; ré-entrée → diff vs mémorisé → UIIntent point-d'intérêt priorité basse via la queue H1 existante. Anti-bruit strict : seuil, cooldown par zone, un cue max/ré-entrée, silence si map_quality faible ou première visite. Config profil `change_attention:` (défauts dataclass), métriques `/metrics`. Tests 6/6 + non-régression 50/50. Limite honnête (ADR §E48-B) : cue surtout intra-session tant qu'aucun `place_hint` stable n'existe en live ; chemin cross-session prêt (lecture `scene_session_summaries_v19`).

### E48 — CLÔTURE (2026-07-08) : APK v3 construit, tests Unity verts

Scène PhoneOnly **régénérée** (`PhoneOnlySceneBuilder.BuildScene`) avec la couche réflexe complète (réparation du gap E47) + TranslateBridge. Cycle d'assemblies UI↔Reflex résolu : `DeviceCommandHandler` expose l'événement `TranslateLiveRequested` (UI ne peut pas référencer Reflex — Reflex référence déjà UI) ; l'asmdef Editor référence désormais Reflex. Wake word aligné « omega » (valeur des docs), endpoints lan→tailscale dans l'asset, `_translateLiveDefault` sérialisé. **Tests EditMode : 59/59 verts** (premier check réel du C# E48). **APK v3 : `build/android/mlomega-phoneonly.apk` — 90,1 Mo — SHA-256 `172394C67CBD451523E10D8CB6EF9140C8210D1BA0843BE5E7B7EA713199846B`** — IL2CPP/ARM64, KWS+MediaPipe+silero_vad embarqués (StreamingAssets, git-ignoré, régénéré au build depuis `models/device/`), endpoint LAN 192.168.1.199:8710 injecté. `FIRST_TRY_ANDROID.md` §v3 à jour (checklist 15-19). Piège d'outillage documenté : Unity.exe est une app GUI — PowerShell `&` n'attend pas et laisse `$LASTEXITCODE` vide ; utiliser `Start-Process -Wait -PassThru` pour un exit code fiable en batchmode. Reste : validation device S25 (première vraie session) + checklist Tailscale 4G.

---

## E50 — Dashboard mémoire lecture seule (FAIT — 2026-07-08, validation visuelle utilisateur en attente)

MemoryLight Dashboard 2.0 intégré et adapté sous **`apps/memory-dashboard/`** (Streamlit une page, SQLite strict `mode=ro`, verrou « ECRIRE » pour les rares actions CLI). **Utilisation : `powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1` → http://localhost:8720** (port vérifié sans collision avec 8710/6333/6334/11434/8766/8704/8706/8776/8601 ; deps installées dans `.venv-live` à la volée ; `MLOMEGA_DB` lu depuis le `.env`). C'est l'outil pour LIRE ce que la mémoire a produit après un close-day : bloc « 🛰️ V19 » ajouté — compteurs, hypothèses E38 (en attente/confirmées/réfutées + preuves), Life Model typé + prédictions/`verification_spec`/outcomes/calibration, événements visuels + chaîne de preuve sha-256, entités/lieux/routines, sessions live + close-day runs (flag `reopened` multi-sessions). Schémas inspectés dans la base réelle ; toute table absente s'affiche « absent », jamais une stacktrace. Chat mémoire rebranché tel quel (`v14-ask` → `ask_brain2`, CLI `python -m mlomega_audio_elite.cli`). Smoke test headless : HTTP 200, zéro exception. Télémétrie Streamlit désactivée (local-first). Détail : `apps/memory-dashboard/README.md`.

---

## E54 — Rétention médias & budget disque (FAIT — 2026-07-08)

Constat : rien n'était purgé automatiquement (le close-day calcule `cleanup_eligible` = autorisation, pas une action) → disque sans limite ; et les keyframes vivaient dans `%TEMP%` (perdus au nettoyage Windows). Livré :
- **Patch longitudinal week/month** (`src/mlomega_audio_elite/v18_close_day.py` `_due_longitudinal_periods`) : le close-day PhoneOnly ne faisait que `period="day"` ; il déclenche désormais aussi `week` (dimanche, fin de semaine ISO) et `month` (dernier jour du mois) sur la période complète, `run_periodic_mirror_layer=True` (parité avec le scheduler nightly V15/V18 jamais invoqué en PhoneOnly). Idempotent. `tests/v19/test_longitudinal_periods.py` (6).
- **`services/live-pc/media_retention.py`** : keyframes hors temp (`storage/media/keyframes/AAAA-MM-JJ/` via `visionrt.media_root`, env `MLOMEGA_MEDIA`) ; transcode WAV→Opus post-close-day (~÷10, ffmpeg, réversible, guardé) ; purge des non-référencés + âgés (`retention_days`, défaut 90) ; **budget global** (`total_gb: 100`) avec éviction du plus ancien NON-référencé d'abord, le référencé JAMAIS supprimé (WARN si tout le dépassement est référencé). « Référencé » = match par token délimité sur toutes les colonnes evidence/observation (bug substring d'id court attrapé par test). Câblé best-effort au close-day après le gate `cleanup.eligible` (`scripts/run_phoneonly_close_day.py`).
- **`storage_quota:`** dans `configs/profiles/rtx3070.yaml` (+ commentaire `user_profile.yaml`), lu par `DOCTOR -Quota` (seuils 80/95/100 Go). Tests `test_media_retention.py` (7, dont transcode ffmpeg réel) + `test_visionrt.py` (5). ADR §E54.

## E55 — Enregistrement clips vidéo + tiering (FAIT — 2026-07-08, validation session réelle en attente)

« Rejouer la scène » en VRAIE vidéo (avant : diaporama de keyframes seulement). Passthrough H.264 impossible (aiortc livre des frames déjà décodées) → on ré-encode les frames déjà décodées pour la vision (pas de décodage en plus), en **CPU libx264 veryfast** (GPU 100 % vision/LLM ; coût mesuré ~1,8 % d'un cœur en 540p/12fps). **Garantie « ne ralentit jamais le live » par construction** : file bornée DROP-on-full (`ClipRecorder.offer` non bloquant), encodeur ffmpeg en subprocess priorité basse (Windows `BELOW_NORMAL`/POSIX `nice(15)`, confirmé `psutil`), auto-pause sur drops persistants, best-effort total (erreur avalée, désactivé = no-op). Câblage minimal dans `gateway.py _consume_track` (après le `to_ndarray(bgr24)` existant), rien d'autre du live touché. Clips sous `storage/media/clips/AAAA-MM-JJ/`, segmentés (`segment_seconds` 120 s), indexés dans `visual_evidence_assets_v19` via les writers cœur → **`replay_service` les sert sans modification**. Tiering close-day (`tier_clips_close_day`) réutilise l'inventaire E54 : garde référencé/événement-dans-la-fenêtre, droppe l'ennuyeux jeune non-référencé, le reste tombe au budget E54. Bloc `clip_recording:` dans `rtx3070.yaml` (`enabled`, `segment_seconds`, `target_fps` 12, `height` 540, `bitrate_kbps` 1000, `queue_max_frames`, `drop_pause_threshold`, `keep_boring_days`). Tests `test_clip_recorder.py` (6, dont ffmpeg RÉEL : MP4 encodé + retrouvé par la requête replay). ADR §E55. Budget : 100 Go ≈ 3 h/jour de clips ; SSD 1 To ≈ 8 h/jour sur 6 mois (recommandé, non requis).

---

## E51 — Installateur / guide de bienvenue (FAIT — 2026-07-09)

`scripts/WELCOME_MLOMEGA.ps1` (+ `WELCOME.md`) : assistant en 9 étapes qui ORCHESTRE les scripts existants (INSTALL/setup_profile/fetch_models/START_QDRANT/RUN/DOCTOR) — n'en réécrit aucun. Modes interactif / `-Defaults` / `-DryRun`. **Encodage : UTF-8 AVEC BOM obligatoire** (PS 5.1 lit sinon en ANSI et casse sur `—`/accents → guillemet parasite → parse error) ; valider via `Parser::ParseFile` + `-DryRun`. Question du mot d'éveil volontairement ABSENTE (cuit dans l'APK = « omega » ; reviendra avec le chantier « wake word runtime »). Branche XREAL = placeholder honnête E49 (l'install PC est identique). Aucun fichier existant modifié. ADR §E51.

## E56 — VLM lourd de nuit (V19) + installateur one-click complété (FAIT — 2026-07-09)

**VLM.** Live (jour) = `moondream` (léger, à la demande). NUIT = deep vision (`brainlive_offline_deep_vision_v16_1`) sur les keyframes SÉLECTIONNÉS par bundle (~12/bundle), VLM VISION lourd chargé pour la phase puis déchargé — jamais sur la vidéo/clips (ceux-ci = replay utilisateur). Gap V19 corrigé : le manifeste ne déclarait que moondream ; ajout de `vlm_heavy` (`configs/MODEL_MANIFEST.yaml`, défaut `qwen2.5vl:7b`, phase nocturne). WELCOME détecte le tag `qwen2.5vl*` via `ollama list` (fallback `qwen2.5vl:7b`), tire moondream + le lourd, et pose `MLOMEGA_VLM_MODEL` (léger) + `MLOMEGA_OFFLINE_VLM_MODEL`/`MLOMEGA_VLM_HEAVY_MODEL` (lourd) dans `.env` ; dégradé <6 Go VRAM → nuit ramenée au léger.

**One-click.** Deux trous comblés dans WELCOME : (4a0) création du `.venv` COEUR (`python -m venv` + `requirements-v18_8-windows.lock.txt` : torch cu121/whisperx/pyannote — moteur du close-day nocturne que l'installateur `.venv-live` ne créait pas), idempotent, signalé comme l'étape la plus longue ; (4a1) provisioning Qdrant (release GitHub `v1.12.6` `qdrant-x86_64-pc-windows-msvc.zip` → `tools\qdrant\` + `config.yaml` généré), best-effort. Prérequis non auto-installables (Python 3.11, appli Ollama) : détectés et guidés. Dry-run exit 0. ADR §E56.

> Note VLM : le modèle de nuit se change dans `.env` (`MLOMEGA_OFFLINE_VLM_MODEL` / `MLOMEGA_VLM_HEAVY_MODEL`) — c'est ce que le runtime lit (ordre : `OFFLINE_VLM_MODEL` → `VLM_HEAVY_MODEL` → `VLM_MODEL` → défaut). Défaut actuel `qwen2.5vl`. Pour repasser sur `qwen3-vl:8b` : `ollama pull qwen3-vl:8b` puis mettre ces deux vars à `qwen3-vl:8b` (et `vlm_heavy.default` du manifeste pour la doc/l'installateur).

---

## E49 — Lunettes XREAL (SDK 3.1.0 intégré + APK buildée — 2026-07-09)

SDK propriétaire fourni par l'utilisateur → `apps/xr-mobile/Packages/xreal-sdk/` (git-ignoré). **Adaptateur recâblé sur l'API réelle** (le stub E22 visait des noms inexistants) : `XREALRGBCameraTexture.CreateSingleton()`, `StartCapture/StopCapture`, callback `OnRGBCameraUpdate`, `GetTimeStamp`, `GetDeviceType`, tracking `InputDevices.isTracked`. `Core.asmdef` référence l'assembly XREAL par **GUID** (warning inoffensif si SDK absent, code compilé out par `XREAL_SDK_PRESENT`). Build : `Assets/Scripts/Editor/AndroidBuildXreal.cs` (menu `MLOmega > XREAL`, ou `-executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildApk`) — **injecte la dép SDK au build** (le manifest commité reste XREAL-free → clones PhoneOnly OK), pose le define, active le loader XREAL (XR Plug-in Management), IL2CPP/ARM64, appId `com.mlomega.xr.glasses`, scène G1Gate → `build/android/mlomega-xreal-g1.apk` (~191 Mo). **EditMode + IL2CPP OK, APK produite, loader assigné.** Deux APK : PhoneOnly + lunettes, même code. Reste : gates G1 sur lunettes physiques. ADR §E49.

**Comment builder l'APK lunettes** (résumé) : déposer `com.xreal.xr.tar.gz` dans `apps/xr-mobile/Packages/xreal-sdk/`, puis `& "<Unity.exe>" -batchmode -quit -projectPath apps\xr-mobile -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines` (import SDK + define) puis `...AndroidBuildXreal.BuildApk` (compile + APK). Piège rencontré : la réf asmdef vers XREAL doit être par GUID (par nom ne résout pas ici) ; les noms d'API du SDK 3.1.0 diffèrent de NRSDK — inspecter le tarball avant de coder.

## E58 — Wake word par ASR français + changeable sans rebuild (FAIT — 2026-07-09)

Le KWS sherpa est anglais (« viki »→« vaïki »). Remplacé : détection du mot dans la **transcription de l'ASR français** (déjà sur l'appareil), défaut **« viki »**, changeable sans rebuild.
- **Device** : `WakeWordMatcher.kt` (normalise sans accents/ponctuation + Levenshtein tolérant selon longueur), branché dans `AsrKwsService.decodeSegment` (final ASR → `openCommandWindow`) ; `setWakeWord(String)` runtime. KWS anglais laissé en place (inoffensif). Tests JVM.
- **Unity** : `MLOmegaConfig._wakeWord="viki"` + ASR défaut Fr ; `AsrBridge.SetWakeWord` (appliqué même si le service démarre après) ; `DeviceCommandHandler` action `set_wake_word` → événement `SetWakeWordRequested`.
- **PC** : `LivePipeline.wake_word` (profil, défaut viki) + `push_wake_word()` (idempotent) envoyé à la 1re réception DataChannel (`PhoneOnlyRuntime._on_receipt`). Tests verts (push + 19 live pipeline).
- **Installateur** : question « comment appeler l'assistant ? » ré-ajoutée (défaut viki, mot rare), écrit `wake_word:` dans `user_profile.yaml`.
- **Latence** : aucune ajoutée — l'ASR tournait déjà ; le matcher scanne juste le texte final. **Changer le mot** : `configs/user_profile.yaml` → effectif à la session suivante, zéro rebuild. APK v4 (PhoneOnly) embarque le matcher ; l'APK lunettes (E49) est antérieure — la rebuilder pour l'inclure. ADR §E58.

## E53 Phase A — « Viki mode aide » (FAIT — 2026-07-10, validation device en attente)

« Viki, mode aide » → coup d'œil VLM initial (devine le problème depuis la scène) → plan de **micro-actions** (1 action = 1 geste, gpt-5.4-mini si mode payant avec coût live, sinon LLM local ; notice via VLM doc) → guidage pas-à-pas : `task_panel` (plan, fantôme N+1 pré-poussé = 0 latence) + `task_anchor` (ancres objets). PC : `services/live-pc/help_mode.py` (machine à états, grounding tracks par `label_en`, watchdog pas-de-progrès avec escalade indice local→cloud, persistance/reprise) + intents dans `intent_router.py` (pré-routeur actif : « c'est fait »/« répète »/« étape suivante »/pause/reprends/termine jamais volés hors tâche). Unity : `UI/Components/TaskAtoms/` — 12 atomes glass composables (ObjectAnchorRing qui SUIT le track, TrajectoryGesture arc/circular/linear/pulse, TimerRing, QuantityChip, SelectionHighlight, TaskDirectionalArrow, ChecklistCard, InstructionCard, CautionCue, ZoomInset, TaskPanel, TaskProgressBar) + 2 composants registre E25. Tests : PC 62 verts (23 help_mode + non-régression), EditMode TaskAtoms 9/9. Clé OpenAI : question WELCOME (étape 2, cloud opt-in) l'explique. Reste Phase A : détecteur objets on-device (mode dehors sans PC) ; Phases B/C plus tard. ADR §E53.

## E59 — Window management gestuel (FAIT — 2026-07-10, validation device en attente)

Grab-drag / resize / fermer / réduire des panneaux à la main. Zéro Kotlin (la position du pincement était déjà exposée : `GestureCallbacks.screenX/screenY`). `PanelManipulator` (Reflex) + registre opt-in `IManipulablePanel` + `PanelPlacementStore` (persistance par type). Désambiguïsation par claim au `PINCH_BEGIN` (hit panneau = grab/resize/boutons ✕–/pastille ; sinon le pinch-zoom LensWindow marche comme avant). VirtualScreen = cible prioritaire (aspect verrouillé) ; les ancrés-objet jamais manipulables. Scène : builder câble le manipulator. Tests EditMode 8 nouveaux, suite 76/76. Restes : MenuPanel (pas de géométrie propre), halo de drag (polish). ADR §E59.

## Phases futures — NON FAITES (à traiter plus tard)

- [ ] **Configuration du wake word (runtime, sans rebuild)** : aujourd'hui le mot d'éveil est cuit dans l'APK (`_wakeWord` de `MLOmegaPhoneOnly.asset`, défaut « omega ») et ne se change qu'en rebuildant. À faire : le rendre choisi à l'installation et poussé par le PC au pairing (message contrôle → `KeywordEncoder` runtime, l'encodeur le permet déjà) ; réintégrer alors la question « comment appeler l'assistant ? » (retirée de WELCOME/E51) avec l'avertissement « pas un mot trop courant ». Réf. backlog E51.
- [ ] **Gates G1 XREAL sur lunettes physiques (E49 — CODE FAIT, matériel en attente)** : l'intégration SDK + l'adaptateur + le build lunettes sont faits (voir E49 ci-dessus, APK produite). Reste, quand l'utilisateur aura les lunettes : valider affichage stéréo, caméra Eye (RGB), pose 6DoF, sessions longues, batterie, et le plan B pose-only si l'Eye est absente. Réf. backlog E49.

---

## E64-F — état exécutable après le premier CloseDay complet (2026-07-14)

La reprise scratch a terminé sans rejouer le média ni les stages déjà clos : run `run_v18_65bdecb7404f4e05abe16cf843f124e4`, dix stages CloseDay `completed`, manifeste observé/attendu `complete=1`, cleanup/tiering/rétention/maintenance `ok`. La dernière reprise n'a exécuté que `live_ready` puis le manifeste et le cleanup (7,7 s); ne jamais présenter ce chiffre comme le temps de toute la nuit. Le run complet contient les pauses et corrections de développement et n'est pas un benchmark.

Backend de diagnostic réellement utilisé (le défaut produit reste Ollama) :

```powershell
$env:MLOMEGA_LLM_BACKEND = "llamacpp"
$env:MLOMEGA_LLAMACPP_BASE_URL = "http://127.0.0.1:8080"
$env:MLOMEGA_LLAMACPP_MODEL = "qwen9b-p1-24k-mlomega"
$env:MLOMEGA_OLLAMA_CONTEXT_POSTSTOP = "24576"
$env:MLOMEGA_POSTSTOP_LLM_MAX_OUTPUT_TOKENS = "4096"
```

Le serveur validé était Qwen3.5 9B Q4_K_M avec `--ctx-size 24576 --parallel 1 --cont-batching --gpu-layers auto --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 --no-cache-prompt --reasoning off --jinja --metrics --perf`. Ne pas copier ce profil dans FIRST_TRY avant la décision E64-H; il sert à obtenir des mesures contrôlables et du JSON strict.

Corrections structurantes à connaître :

- le runner hiérarchique mesure la requête complète, décode les colonnes JSON persistées, sépare les responsabilités de sortie, borne la projection dérivée et planifie 45 unités utiles sous limite token dure;
- Life Model résout toute preuve vers une vraie ligne owner-scopée avant une écriture atomique; les sections consultatives restent dans l'export mais ne polluent plus les tables canoniques;
- `live_ready` compile désormais le Life Model canonique par code et conserve ses preuves. Le LLM n'est appelé que pour une ancienne DB dépourvue de modèle canonique;
- le script CloseDay imprime un JSON ASCII-safe sous Windows, donc un caractère Unicode ne peut plus faire échouer un run déjà terminé.

Verdicts ouverts à ne pas masquer :

- Deep Vision : 1 image sélectionnée, 0 analysée, 1 quarantinée après 84,132 s (`JSONDecodeError`), mais le stage historique retourne `status=ok`. Vague 2 NON validée;
- ASR : huit tours présents mais confiance 0 et fragments grec/russe probablement hallucinés; les sorties aval trop affirmatives ne valent pas vérité;
- coordination/réconciliation : certaines contradictions sont déduites de l'absence de preuve visuelle; corriger le gate épistémique;
- FIRST_TRY : le lock Python n'est pas encore aligné avec la version `transformers` requise par Qwen3 embedder; HF gated/proxy, Qdrant et CUDA/cuDNN doivent être vérifiés avant capture;
- le dashboard et le gate 5 min complet restent ouverts. La DB `_audit` est une preuve de développement, pas une base produit à conserver.

Pour poursuivre : lire `docs/PROD_BACKLOG.md` §E64-H et `tools/harness/BUGS_FOUND.md` OBS-25 à OBS-31. Aucun nouveau média avant d'avoir terminé l'audit coût/qualité et décidé quels appels sont réellement sémantiques, déterministes, redondants ou réutilisables.

---

## E64-H — audit terminé et passation E64-I (2026-07-14)

Le rapport autoritaire est `docs/E64_H_COST_QUALITY_AUDIT.md`. Il contient le tableau
des 169 appels du chemin final, les cardinalités, l'inspection qualitative des épisodes
et du Life Model, les calculs huit heures local/DeepSeek, les images et les hypothèses.
Ne pas refaire le run complet pour retrouver ces nombres : les bases scratch et essais
abandonnés ne sont pas un benchmark propre.

Trois états doivent rester distincts :

1. avant E64 : 1,6 M caractères/985 pseudo-tours, troncature, puis architecture
   intermédiaire 304 appels V13 sans finir la chaîne;
2. actuel après E64 : chaîne finissable, 169 appels/83 min sur la fixture auditée,
   mais EpisodeBuilder fragile, caps coordination/Life et faux verts;
3. cible E64-I : faits typés partagés, responsabilités fusionnées sans perte, environ
   884 appels pour une projection 8 h au lieu de 19 469, à prouver par tests.

Bugs bloquants ajoutés dans `tools/harness/BUGS_FOUND.md` OBS-34 à OBS-38 : épisodes
cross-topic, coordination coupée à 200, Life Model coupé à 120 par famille, cause exacte
du faux vert Qwen3-VL, surpromotion de 92 objets et manifeste tolérant les abstentions.

Ordre de travail :

1. appliquer I0 (gates vérité) puis I1 (EpisodeBuilder), car optimiser des épisodes
   faux amplifierait plus vite une mémoire fausse;
2. créer le contrat de faits typés I2 et seulement ensuite fusionner les appels
   compatibles; garder toutes les tables/writers et la provenance;
3. remplacer les caps 200/120 par pagination/atomes/manifeste I3;
4. corriger et rebenchmarker Qwen3-VL I4 (`think=false`, JSON strict, statut, cache);
5. comparer 9B/4B par tâche I5/I6; aucune substitution globale;
6. exécuter cinq minutes, 1 h puis 8 h et décider le backend I7.

Le `visual_consolidation` postérieur à Deep Vision est déterministe et ne rappelle pas
le VLM : ne pas le supprimer comme doublon. Le backend llama.cpp direct est un outil de
mesure opt-in; ne pas modifier le défaut FIRST_TRY avant I7. DeepSeek Pro ne résout pas
le chemin actuel (~68 EUR/jour texte seul) et reste au mieux un critique borné après
refonte. Le plan à cocher est `docs/PROD_BACKLOG.md` §E64-I.

---

## E64-I — reprise après mini-plan 1 (2026-07-14)

Le prototype `brain2_conversation_episode.py` est **shadow/opt-in**, jamais activé par
défaut. Ne pas refaire les trois essais : le verdict retenu est la passe deux appels sur
une copie de `tools/harness/_audit/one_minute_memory_v1.db` : 2 appels, 15 956 tokens,
41,50 s, 1 parent, 6 sous-thèmes et 26/26 appartenances. Baseline EpisodeBuilder :
4 appels, 20 210 tokens, 229,9 s, 10 épisodes. Détails et seuils dans §E64-I du backlog.

Architecture retenue : appel segmentation (bornes uniquement), puis appel détail sur
segments immuables. `episode_subthemes_v19` contient l'ordre/résumé; la table evidence
sépare `membership` de `primary_citation`. Le parent conserve tous les tours et expose
`subtheme_types`; `_engine_applies_to_episode` les lit pour ne jamais sauter un moteur
V13 conditionnel. `_episode_bundle` transmet aussi les sous-thèmes au pack aval.

État de validation : 54 tests ciblés E64-F/I verts. Le flag
`MLOMEGA_E64_CONVERSATION_EPISODES=1` reste OFF tant que (a) les grandes conversations
ne sont pas fenêtrées/checkpointées sans perte, et (b) le pack V13 parent n'a pas été
mesuré réellement. Prochaine action utile : I2 prototype sur ce parent, compter appels,
tokens, sorties/writers et comparer au lot baseline. Ne pas repolir les six sous-thèmes
avant cette mesure : la finesse du modèle est séparable de la cardinalité architecturale.

---

## E64-I2 — passation exacte du chantier en pause (2026-07-14)

Le chantier est volontairement arrêté après le noyau et avant un nouveau run nocturne.
Deux flags sont nécessaires pour le shadow; **aucun n'est activé par défaut** :

```powershell
$env:MLOMEGA_E64_CONVERSATION_EPISODES = "1"
$env:MLOMEGA_E64_SHARED_FACTS = "1"
```

Fichiers d'architecture à lire, dans cet ordre :

1. `brain2_shared_facts_v19.py` : schéma canonique, capacités, preuves, projection
   compacte et règle très stricte de réemploi open-loops;
2. `brain2_strict_v13_2.py` : seul pont V13 production modifié; la sortie validée est
   persistée puis relue avant le writer historique;
3. `night_orchestrator/prompt_projection.py` : registre central des buts de stage et
   raccourcissement réversible des refs de tours;
4. `night_orchestrator/hierarchical_json.py` : projection avant fenêtre et registre
   central des deux responsabilités interpersonnelles;
5. `people_openloops_v14_5.py` et `interpersonal_state_v14_6.py` : seulement les règles
   métier restantes; ne pas y remettre des compactages de prompt locaux;
6. `tests/v19/test_e64i_shared_facts.py` : contrat minimal de non-perte.

Preuve acquise : le parent minute a produit les sept sections V13 applicables en un
appel Qwen (19 452 tokens, 22,656 s, 7/7, missing=0). Les 60 tests ciblés suivants sont
verts :

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  tests/v19/test_e64i_shared_facts.py `
  tests/v19/test_e64i_conversation_episode.py `
  tests/v19/test_e64f_brain2_blocks.py `
  tests/v19/test_e64f_wiring.py -q
```

DB shadow de preuve (temporaire, jamais à committer) :
`%LOCALAPPDATA%\Temp\e64i-minute-shadow-2pass-20260714-163846.db`, conversation
`conv_blbundle_deep_audio_v185_a72ef4f29870fadb`, parent
`episode_fbb572184b0a06ed`.

La prochaine exécution ne doit pas relancer Life Model ni tout CloseDay. Sur une copie
de cette DB : exécuter identité puis interpersonnel, relire
`night_prompt_projections_v19` et `night_llm_windows_v19`, vérifier les tables V14 et
que chaque ref courte a retrouvé son `turn_id`. L'open-loop sans appel n'est accepté que
si le manifeste V13 contient `outcome_tracker.open_loops=valid_empty`. Comparer les
sorties à la baseline, notamment les dix champs interpersonnels; un JSON vert mais un
champ absent est un échec.

Après ce gate seulement : étendre le registre central à Pattern Mirror/clarification,
V14.7, coordination, réconciliation, Life et longitudinal; établir la matrice
champ→producteur→preuve→writer→consommateur; traiter les caps 200/120 en I3; puis
harnais 5 min et dashboard. Ne pas annoncer le temps huit heures depuis les seules
réductions statiques. Le test élargi `test_e64_night_orchestrator.py` possède par ailleurs
une assertion ancienne de ratio caractères/tokens (attend 3,5 alors que la politique
documentée est 2,5); elle est hors de ce diff et ne doit pas entraîner une modification
opportuniste de l'estimateur pendant I2.

### Reprise I2 — procédure opératoire R1 à R4

Cette procédure complète le backlog autoritaire. Le gain majeur ne demande pas de
réécrire tous les V13–V19 : il vise d'abord trois agrégateurs dans
`brainlive_brain2_coordination_v15_12.py` et un dans
`brain2_life_model_updater_v15_13.py`. Les tables et writers actuels restent le contrat
de compatibilité.

**R1, preuve V14 courte.** Dupliquer la DB shadow; conserver une copie baseline. Avec
les deux flags opt-in, exécuter seulement :

```python
from mlomega_audio_elite.people_openloops_v14_5 import run_v14_5_post_conversation
from mlomega_audio_elite.interpersonal_state_v14_6 import run_v14_6_post_conversation

run_v14_5_post_conversation(CONVERSATION_ID, person_id="me")
run_v14_6_post_conversation(CONVERSATION_ID, person_id="me")
```

Ne pas réutiliser les mêmes DB baseline/shadow pour éviter que l'historique de la
première exécution pollue la seconde. Exporter avant/après les lignes
`night_prompt_projections_v19`, `night_llm_windows_v19`, `v14_5_*` et `v14_6_*`.
L'absence justifiée de loop est un résultat; l'absence d'un champ interpersonnel est une
régression. Conserver les sorties brutes Qwen et les digests, sans les committer.

**R2, extension centrale.** Ajouter un constructeur unique de paquet journalier dans
la couche de faits partagés : pagination par PK/date, capacités et preuves, état du
dernier checkpoint, aucun `LIMIT` sémantique. Dans `_STAGE_PURPOSES` enregistrer
exactement `coordination_day_package`, `coordination_watch_bindings`,
`coordination_reconciliation` et `life_model_patch`. Dans le registre des
responsabilités hiérarchiques, déclarer leurs sous-schémas de sortie. Le déroulement
doit rester : projection commune une fois → groupes de sortie conditionnels → merge
validé → refs durables restaurées → writer historique. Ne jamais refaire la projection
par groupe de sortie.

Répartition de responsabilité :

| Stage | Code déterministe d'abord | LLM encore légitime | Table relue après writer |
|---|---|---|---|
| `coordination_day_package` | chronologie, regroupement des traces, compteurs, liens prediction/intervention/outcome | résumé d'une ambiguïté non portée par les faits | `brainlive_day_packages` |
| `coordination_watch_bindings` | mapping prediction/forecast/warning/hook vers horizon et source durable | routage réellement indécidable seulement | `brain2_live_watch_bindings` |
| `coordination_reconciliation` | génération des paires comparables par cible/personne/horizon/temps | verdict sémantique sur collision réelle | `brainlive_brain2_reconciliations` |
| `life_model_patch` | delta depuis checkpoint, dédup par source, modèle courant et états de cycle de vie | interprétation/promotion des nouveautés ambiguës | `brain2_life_model_patch_runs`, opérations, strata, lifecycle et tables canoniques |

Les appels déterministes ne doivent pas être déclarés réussis par simple absence de
LLM : valider leur schéma, leur manifeste et leurs FK exactement comme une sortie
modèle. Pour Life, conserver les neuf couches du `PATCH_SCHEMA`; découper une sortie
trop large dans l'orchestrateur, jamais en supprimant une couche. Pour réconciliation,
l'absence de frame ou d'outcome est `unknown/too_early`, pas une contradiction.

**R3, équivalence.** Ajouter une fixture/matrice qui relie chaque champ des quatre
schémas aux faits sources et aux tables finales. Comparer baseline/shadow sur les mêmes
preuves : présence des responsabilités, IDs, owners, dates, evidence/counter-evidence,
confidence ceilings, statuts et nombres de lignes. La prose peut varier; une capacité,
une preuve ou un writer manquant ne le peut pas. Faire ensuite un deuxième run shadow :
les checkpoints doivent empêcher tout appel déjà validé et ne créer aucun doublon.

**R4, totalité.** Seulement après équivalence, remplacer `limit=200` du paquet jour,
`limit=160` des bindings, `limit=120` de la réconciliation et `limit=120` du Life Model
par un lecteur paginé commun. Une page doit porter clé de reprise et digest; le manifeste
global additionne toutes les pages. Tester au moins `cap+1`, plusieurs pages, kill après
sortie avant commit, kill après commit avant marker et événement traversant la frontière.
Augmenter les nombres ou envoyer toutes les lignes dans un prompt unique est interdit.

Le gate final de cette reprise est un seul harnais cinq minutes, après R1–R4 : comparer
au total historique de 169 appels, vérifier le dashboard et recalculer les volumes 1 h/
8 h. Avant ce gate, ni les 1,5 M tokens ni les 3–6 M ne sont des résultats certifiés.

### Checkpoint d'exécution R1/R2 — 2026-07-15

R1 est terminé sur clones séparés. Baseline V14 : 20 appels, 293 495 tokens d'entrée
estimés, 569 s. Shadow I2 : 3 appels, 36 898 tokens, 136 s. Les dix sorties
interpersonnelles et les IDs restaurés ont été relus; le shadow s'abstient d'inventer
« Maxime » comme identité. `contract_normalization.py` est désormais la frontière entre
les dictionnaires structurés du runner et les writers historiques V14.5/V14.6.

R2 coordination est déterministe et validé sur clone : `compiled_ready`, 13 bindings
actionnables, deux bindings obsolètes désactivés, zéro source non résolue et aucune paire
de réconciliation réelle à soumettre au modèle. Fichiers centraux à lire :
`night_orchestrator/daily_fact_projection.py`, `prompt_projection.py`, puis
`brainlive_brain2_coordination_v15_12.py`.

R2 Life et sa frontière de vérité sont validés :

- le payload réel est passé de 484 915 à 10 845 tokens; les neuf couches sont présentes
  comme index, tandis que la DB conserve le raw complet;
- une première observation owner-scopée est compilée dans
  `brain2_life_model_watch_candidates`, sans appel LLM ni objet canonique. Preuve sur
  clone : 1,18 s, zéro `life_model_patch` window, occurrence=1/independent=1;
- une source identique rejouée est idempotente; une deuxième source/épisode indépendant
  rend le candidat `promotion_ready`;
- tout patch doit citer une nouvelle ligne durable exacte. Une création insuffisamment
  répétée est forcée `very_recent/candidate/watch_only`; une réponse qui recycle un ancien
  fait est refusée en entier;
- le writer V18 a été exercé avec une opération valide : modèle canonique et lifecycle
  partagent la PK `b2action_*`; aucune moitié de patch n'est appliquée;
- les tables `brain2_life_model_consumed_sources` et `brain2_life_model_checkpoints`
  enregistrent la révision exacte de chaque source par digest. Sur le clone checkpoint,
  le premier passage consomme 21 révisions; le replay immédiat donne
  `compiled_no_life_delta`, source_count=0, watch occurrence=1 et zéro appel LLM. Une
  même PK modifiée est volontairement retraitée;
- le préflight CloseDay interroge `/props` pour llama.cpp et refuse serveur absent,
  `n_ctx` illisible ou différent de `MLOMEGA_OLLAMA_CONTEXT_POSTSTOP`. Validation réelle :
  budget configuré 24 576, serveur 24 576, alias `qwen9b-p1-24k-mlomega`, ready vert;
- **82 tests** élargis E64/I2/Life/CloseDay/préflight sont verts.

Ne pas relancer Qwen pour une première occurrence : c'est désormais un bug si une telle
occurrence ouvre une fenêtre LLM. Le test Qwen 9B en une fenêtre a répondu en 15,3 s mais
a choisi un ancien fait sans citer le nouvel outcome; la validation l'a bloqué. Ce
résultat justifie le compilateur de watch, pas une nouvelle retouche fixture du prompt.
Une promotion réellement ambiguë pourra être confiée à un modèle plus fort (dont
DeepSeek), toujours derrière le même contrat de preuve.

R2 est clos. Prochaine action exacte : R3, matrice
champ→fait→preuve→writer→consommateur et comparaison baseline/shadow. Ne traiter les
caps 200/160/120 qu'après cette équivalence.

Attention configuration : le serveur de mesure tourne avec `ctx-size=24576`, tandis que
le défaut orchestrateur reste 16384. Il faut donc définir
`MLOMEGA_OLLAMA_CONTEXT_POSTSTOP=24576` pour ce serveur. Le préflight compare maintenant
la valeur au `n_ctx` réel de `/props`; 16 384 contre 24 576 est un échec bloquant, et non
plus cinq subdivisions silencieuses d'un payload rendu de 13 326 tokens.

### Checkpoint R3 — équivalence exécutable (2026-07-15)

R3 ne compare pas la prose Qwen caractère par caractère. Le contrat versionné
`night_orchestrator/equivalence_contract.py` relie chaque responsabilité à ses faits,
sa politique de preuve, son writer et ses consommateurs. Il suit explicitement les
wrappers V18 jusque dans la fonction `old_*` qui effectue la lecture SQL; le nom public
d'une fonction n'est pas accepté comme preuve. Résultat : 18/18 responsabilités des
schémas day package/watch/reconciliation/Life sont couvertes.

La première comparaison des clones R1 a correctement échoué : malgré 10/10 champs et
une couverture de refs shadow à 100 %, V14.6 avait persisté 0,85/0,90 pour un locuteur
toujours inconnu, à partir d'une minute. Le JSON brut reste dans le journal, mais les
huit writers conversationnels plafonnent maintenant une observation isolée à 0,65.
Le replay du vrai output shadow dans `e64i-r3-writerproof-20260715.db` conserve les huit
familles et toutes les preuves, avec max=0,65; la comparaison finale est verte.

Preuve runtime séparée, sans nouveau CloseDay :

- coordination `e64i-r2-coordination-20260715-001235.db` : package
  `bldaypkg_fd732c6ed4b1f5a3` `compiled_ready`, 7/7 champs, run
  `b2blrun_0340609821e0884a` `ok`, 13 bindings actifs, zéro source invalide et zéro
  réconciliation nouvelle faute de paire comparable;
- Life `e64i-r2-checkpoint-proof-20260715-0220.db` : 21 sources exactes consommées,
  zéro absente, replay source_count=0, un watch occurrence=1/independent=1;
- 87 tests E64/I2/Life/CloseDay/préflight/R3 verts.

R3 est clos, mais les deux flags restent désactivés. La prochaine action est R4/I3 :
remplacer les caps 200/160/120 par pagination complète et reprise atomique, puis seulement
mesurer le harnais cinq minutes et le gain global.

### Checkpoint d'exécution R4/I3 — 2026-07-15

R4 est clos côté code et tests; le harnais cinq minutes reste le gate I7 distinct. Le
lecteur commun est `night_orchestrator/paged_evidence.py`. Chaque SELECT doit exposer une
clé unique `__page_pk`; le lecteur fait du keyset, jamais `OFFSET`, et persiste dans
`night_evidence_page_runs_v19` / `night_evidence_pages_v19` le digest d'entrée, la sortie
transformée et l'état après page dans le même commit. Une reprise relit la source : elle
ne réutilise une page que si PK, cardinalité et digest sont identiques. Un manifeste ne
devient `complete` que pour `source_count == included_count`.

Frontières réellement migrées :

- `collect_day_evidence` : `limit` est la taille de page. La vision est ordonnée par
  `(created_at, observation_id)`, réduite avant accumulation, refusionnée entre pages et
  stockée dans le paquet sous forme de `VisionChangeAtom`. Les observations exactes
  restent dans leur table; `source_manifest_json` donne leur couverture.
- `collect_brain2_forecast_evidence` et le wrapper V18 : toutes les sources owner/live
  éligibles sont parcourues; le filtre lifecycle/projection expose aussi combien de lignes
  brutes ont été exclues. Le compilateur ne reçoit aucun manifest comme fausse source.
- `collect_canonical_evidence`, `collect_life_model_delta` et
  `load_current_life_model` : tous paginés. Les tours sont scannés entièrement mais seuls
  les IDs cités par observed/internal/shared facts sont matérialisés vers Life. Les neuf
  couches canoniques sont l'état courant chargé séparément et sont retirées du delta pour
  interdire l'auto-confirmation.

Bug de branchement découvert : l'installateur canonique V18 consultait
`module.CANONICAL_TABLES`, absent de `brain2_life_model_v15_10.py`; le feed courant avait
donc neuf dictionnaires vides. `v18_life_model.py` possède maintenant le mapping explicite
vers les tables réelles. Preuve clone : `9/4/9/22/12/9/10/9/8` lignes par couche. La clé
de reprise Life digère désormais le contenu du modèle courant; deux états de même taille
ne partagent plus un checkpoint.

Tests à conserver : `tests/v19/test_e64i_paged_evidence.py` couvre 201 observations,
161 bindings, 121 sources Life, 121 routines courantes, kill avant commit, kill après
commit, invalidation d'une seule page modifiée et continuité d'événement. Suite R1–R4
élargie : **93 passed**. Clone : 199 observations, quatre pages, un atome/199 refs;
26 manifests Life complets. Ne pas activer `MLOMEGA_E64_CONVERSATION_EPISODES` ni
`MLOMEGA_E64_SHARED_FACTS` sur cette seule preuve. Action suivante : un run frais vidéo
cinq minutes, vérifier 698/698 (ou le nouveau total source exact), appels/tokens/temps,
CloseDay/recovery et dashboard; aucune projection 1 h/8 h avant ce chiffre.

## E64-I / I0.5 — passation finale du 2026-07-15

Le nouveau chemin conversation/faits partagés est ON par défaut; rollback uniquement par
`MLOMEGA_E64_CONVERSATION_EPISODES=0` et/ou `MLOMEGA_E64_SHARED_FACTS=0`. Le registre
central `night_orchestrator/prompt_projection.py` interdit désormais tout stage produit
non classé. Ne corriger aucun futur dépassement dans un prompt métier isolé : ajouter sa
politique et sa projection au registre, puis tester couverture/manifeste.

Le live PhoneOnly n'effectue plus la sémantique fine lourde dans le worker audio. La file
durable est `live_fine_intel_queue_v19` (`services/live-pc/deferred_fine_intel.py`). Le
CloseDay attend son drain; la recovery la reprend. Pour diagnostiquer une fermeture :
relire `fine_intel_pending`, `fine_intel_model_calls`, `deferred_semantics` et les lignes
de cette table avant de toucher au timeout.

### Commandes de reprise environnement

Depuis la racine `Mlomega-main` :

```powershell
# Téléchargement explicite seulement si le gate indique un cache HF incomplet
.\.venv\Scripts\python.exe scripts\PREFETCH_FIRSTTRY_MODELS.py

# Gate cœur seul (aucun téléchargement)
.\.venv\Scripts\python.exe scripts\check_close_day_preflight.py --json

# Gate FirstTry complet; RUN appelle exactement celui-ci avant SessionHub
.\.venv-live\Scripts\python.exe scripts\check_phoneonly_readiness.py --person-id me --deep
```

État machine au checkpoint : HF gated/cache, ASR, Transformers, `.venv`, DB/media,
Qdrant, torch CUDA et chargement réel cuDNN 8 sont verts. Trois échecs sont attendus et
guidés tant que l'opérateur n'a pas choisi : `.env` sélectionne Ollama mais Ollama est
arrêté; un llama-server alias `qwen9b-p1-24k-mlomega`, contexte 24576, tourne encore sur
8080; les VLM Ollama ne peuvent donc pas être sondés. Soit arrêter ce serveur et lancer
Ollama, soit déclarer explicitement backend/alias/contexte llama.cpp; dans les deux cas
Ollama reste nécessaire à `moondream` et `qwen3-vl:8b`. Ne démarrer aucune capture tant
que le rapport n'est pas `ready=true`.

Tests : 23 ciblés hermétique/installation/multi-session verts. La suite cœur a donné
92 verts/1 skip; huit tests PhoneOnly ont échoué uniquement parce qu'ils ont été lancés
dans `.venv` sans aiortc/webrtcvad. Les relancer dans `.venv-live`; la relance longue a
été interrompue à la demande utilisateur. Ne pas attribuer ces huit erreurs au code et
ne pas annoncer pour autant le gate live vert.

Suite produit autoritaire : fermer I0.1–I0.4, puis I0.6, I4 et I7 Gate B selon le détail
dans `PROD_BACKLOG.md`. Le dernier vrai CloseDay est complet mais Deep Vision est encore
1 sélection/0 analyse/1 quarantaine et aucune voix owner n'était enrôlée; aucune promesse
1 h/8 h n'est acquise.

### Rectification de reprise immédiate

I2 et I0.3 sont clos; I1.1/I1.2/I1.4/I1.7 sont clos. Ne refaire ni R1–R4 ni l'audit des
anciens moteurs. Avant d'ouvrir I4, trois incréments courts restent obligatoires : I0.2
(qualité ASR/diarisation/langue/alignement → plafond des faits), I0.4 (capacité obligatoire
→ gate du manifeste final), et I1.3 (conversation longue fenêtrée/reprise, sans
`input_budget_exceeded`). Puis persister le profil llama.cpp P1/24576 + Ollama VLM et
exécuter seulement readiness + tests séparés par venv. La ligne de reprise détaillée et
les fichiers/tests attendus sont dans `PROD_BACKLOG.md`, checkpoint 2026-07-15, étapes
1–4. Une fois ces trois cases vertes, reprendre directement **I4.1**.

### Lot prérequis I0.2/I0.4/I1.3 — FAIT (2026-07-15, après la passation ci-dessus)

Les trois incréments sont livrés et testés (24 nouveaux tests + 53 non-régression, tout
en fakes, aucun CloseDay) :

- **I0.2** : `evidence_quality_v19.py` (qualité par preuve) + plafond réel dans
  `brain2_shared_facts_v19.py`. Diagnostiquer un fait plafonné : lire
  `confidence_ceiling` et `evidence_status` (`cited|uncited_model_output|quarantined|
  owner_attribution_blocked`) dans les faits partagés.
- **I0.4** : gate des capacités dans `v18_close_day.py` +
  `night_orchestrator/capability_manifest.py`. Diagnostiquer un run `blocked` : lire
  `v18_close_day_capability_manifests` (`blocking_json` nomme la capacité et la cause).
  Rollback d'urgence : `MLOMEGA_E64_CAPABILITY_GATE=0`.
- **I1.3** : conversations longues fenêtrées dans `brain2_conversation_episode.py` via
  `run_windows` (checkpoints `night_llm_windows_v19`, stats `windowed_*` dans le retour).
  Aucun `input_budget_exceeded` si `person_id`+`package_date` sont passés (fait par
  `brain2_strict_v13_2`).

Tests du lot : `.venv\Scripts\python.exe -m pytest -q tests\v19\test_e64i_evidence_quality.py
tests\v19\test_e64i_capability_manifest.py tests\v19\test_e64i_long_conversation.py`.
Reprise produit suivante : validation courte (backend persisté + readiness) puis **I4.1**.

### I1.5/I1.6 — FAIT (2026-07-16) + commande llama-server P1 canonique

**I1.5** : fusion par provenance aux bords de fenêtre forcés (`_fuse_forced_window_edges`
dans `brain2_conversation_episode.py`) — un thème traversant deux fenêtres n'est plus
coupé artificiellement ; une vraie frontière au bord reste une frontière. 20 tests verts.

**I1.6** : gate réel de la minute en conditions produit (voir suivi PROD_BACKLOG) :
2 appels, 15 772 tokens, 32,6 s, 1 parent + 4 sous-thèmes, Karim/Netflix séparés,
26/26, zéro FK inventée.

**PIÈGE OPÉRATEUR (coûte une troncature systématique si oublié)** : lancer le
llama-server P1 avec `--reasoning-budget 0` seul NE désactive PAS le thinking de
Qwen3.5 — le modèle brûle ses 4096 tokens de sortie en raisonnement caché et chaque
appel JSON finit `length`. La commande canonique complète :

```powershell
& "C:\Users\wabad\llama-test\bin\llama-server.exe" `
  -m "C:\Users\wabad\llama-test\models\Qwen3.5-9B-Q4_K_M.gguf" `
  --alias qwen9b-p1-24k-mlomega -c 24576 --parallel 1 --cont-batching `
  -ngl 99 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 `
  --jinja --chat-template-kwargs '{\"enable_thinking\":false}' `
  --reasoning-budget 0 -n 4096 --host 127.0.0.1 --port 8080
```

Vérification rapide avant tout run : `Invoke-RestMethod http://127.0.0.1:8080/props`
doit donner l'alias exact et `n_ctx=24576`, et une requête JSON triviale doit finir
`stop` avec `reasoning_content` vide.

### I4 Deep Vision — gate produit final (2026-07-16)

Le gate n'est vert que sur la triple preuve durable :
`selected_keyframes == readable_keyframes == analyzed_keyframes`. Lire ces colonnes dans
`brainlive_deep_vision_runs_v161`; le manifeste final les recopie dans la capacité
`deep_vision`. Toute différence bloque `complete=1`.

La sélection nocturne peut choisir une frame que le sélecteur live n'avait pas écrite en
JPEG. Ce n'est plus une perte : le runtime cherche le clip E55 de la même session couvrant
`frame_time`, extrait automatiquement la frame par ffmpeg, écrit sous
`$MLOMEGA_MEDIA\keyframes\AAAA-MM-JJ\deep_materialized\`, puis met à jour
`raw_assets` et `deep_vision_keyframe_materializations_v19` sans modifier le
`vision_frames` brut. La provenance se lit directement dans cette table additive
(clip, SHA, fenêtre, offsets, clamp). MediaRetention l'inventorie comme une keyframe.
Événements utiles : `deep_vision_keyframe_materialized`,
`deep_vision_keyframe_materialization_failed`,
`deep_vision_keyframe_registration_failed`. Une absence de clip ou de ffmpeg devient
`blocked_selected_pixels_unavailable`; ne jamais contourner en diminuant le compteur.

Tests ciblés sans réseau VLM :

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests\v19\test_e64i_deep_vision_selection.py `
  tests\v19\test_e64i_deep_vision_backend.py `
  tests\v19\test_e64i_visual_reuse.py `
  tests\v19\test_e64i_capability_manifest.py `
  tests\v19\test_close_day_output_proof.py `
  tests\v19\test_media_retention.py
```

Résultat de clôture : **52 passed**. Le test matérialisation utilise un vrai MP4/ffmpeg
mais un transport VLM fake; la qualité réelle Qwen3-VL reste la mesure antérieure 20/20.

### I0.6 + I6 — raccords produit fermés (2026-07-16)

Le prochain travail n'est plus un audit statique spatial : exécuter **I7 Gate B** en deux
temps, d'abord le scénario VIKI live inchangé (hot context, interaction, suggestion,
help mode et recherche spatiale), puis seulement le CloseDay complet et le dashboard.

Raccords à diagnostiquer si le gate échoue :

- connecté : `device_transcript` → `IntentRouter` → `_route_vision_focus` →
  `WorldBrain.find_entity_record` → `spatial.answer_find` → UI intent;
- hors connexion : `AsrBridge.Transcript` → `ReflexScheduler` → `FocusSearchSkill`;
- proactivité : `_on_scene_delta` → `BrainLiveSceneAdapter.evaluate_periodic` et, pour
  l'apparence nommée, `observe_named_appearance` → `AttributeMemory` →
  `evaluate_situations` → file H1;
- télémétrie nocturne : `night_llm_call_telemetry_v19`. Toute fenêtre réellement appelée
  doit avoir une ligne, y compris erreur; une reprise checkpoint porte `cache_hit=1`.

La cadence scène de 2 s est une cadence mémoire/proactivité, **pas** la cadence de rendu
VisionRT/UI. Ne pas la remonter à 30 FPS pour faire fonctionner outlines/flèches : ceux-ci
restent sur les événements immédiats. La dernière position et l'historique ont des rôles
différents : registre durable actualisé versus événements immuables.

Validations déjà exécutées — ne pas les refaire avant Gate B :

```powershell
# PC live/vision/proactivité : 128 passed
.venv-live\Scripts\python.exe -m pytest -q tests\v19\test_e28_worldbrain.py `
  tests\v19\test_e33_scene_delta.py tests\v19\test_e34_proactivity.py `
  tests\v19\test_e35_intent_router.py tests\v19\test_e36_ops.py `
  tests\v19\test_e38_attribute_memory.py tests\v19\test_phoneonly_runtime.py

# I6 final : 38 passed (75 au lot élargi précédent)
.venv\Scripts\python.exe -m pytest -q tests\v19\test_e64c_executor.py `
  tests\v19\test_e64i_shared_facts.py

# Unity ciblé : 13/13 passed, résultat apps/xr-mobile/i06-reflex.xml
```

Le test Unity a écrit `i06-reflex.xml`, artefact local à ne jamais ajouter au commit. Le
S25 et les APK ne sont pas certifiés par ces tests; ils appartiennent aux gates I7.

### I7 Gate B — état exact après la passe fonctionnelle du 2026-07-16

Ne relancez pas le CloseDay long pour « vérifier » les commandes. La session de référence
est `blsess_b155c05464f08c85` dans `tools/harness/_run/gateb_memory_v2.db`; son run
`run_v18_66f56f15fc154e948827d4f4d53e9236` est `completed`. Le Deep Vision autoritaire
`v18deepvisionrun_20639d09a5894690` porte `selected/readable/analyzed=16/16/16`; capability
et output manifests sont complets. La dernière reprise a consommé les checkpoints au lieu
de repayer la chaîne.

Le scénario exact `tools/harness/scenarios/real_video_session.json` contient treize
commandes. Elles ont un handler et un effet vérifiés 13/13. Le runtime pousse en plus un
`command_execution_trace`; `FakeXrDevice` collecte `command_execution_traces`,
`downlink_type_counts` et `meaningful_downlinks`. Une future exécution doit comparer ces
treize traces aux treize événements : `intents_routed=13` seul est insuffisant.

Corrections du gate à préserver :

- `GpuArbiter.request` raisonne en headroom projetée; ne rétablir ni la comparaison
  `used_mb > job_budget_mb` ni le faux refus OCR;
- `WorldBrain.ingest_scene_delta` propage la zone active de `PoseKeyframeMap`; sans elle,
  ChangeAttention reste à zéro même si les changements sont stockés;
- `EnrollmentWatcher` ne capture pas les phrases générales `retiens ...`; seule une
  utterance complète de nom ou une forme explicite d'identité peut enrôler;
- `traduis le texte` est un flux à deux frontières : OCR PC, puis device command
  `translate_text` vers `DeviceCommandHandler`/`TranslateBridge`. RapidOCR s'abstient
  honnêtement; le fallback `qwen3-vl:4b` est JSON contraint et classé `probable`;
- le capability manifest prend le `run_id` Deep Vision de `post_stop`, afin de ne pas
  additionner une ancienne tentative bloquée et la tentative autoritaire réparée.

Commandes de validation courte (pas de CloseDay) :

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
& .\.venv-live\Scripts\python.exe -m pytest tests\v19\test_e27_pipeline.py tests\v19\test_e33_intents.py tests\v19\test_phoneonly_runtime.py tests\v19\test_gpu_arbiter.py tests\v19\test_change_attention.py tests\v19\test_wake_word_gating.py tests\v19\test_help_mode.py tests\v19\test_e64i_capability_manifest.py tests\v19\test_e61_memory_integrity.py -q
```

Résultat observé : 147 verts (146 au lot, puis le callback produit VIKI ajouté et vert).
Unity ciblé : filtre
`MLOmega.XR.Tests.E33MenuDeviceTests`, 10/10. Le prochain travail I7 n'est pas de réparer
les treize commandes : c'est (a) S25 pour le Kotlin/offline/receipts et (b) un run cinq
minutes **one-shot sur DB fraîche** pour mesurer appels/tokens/temps et le seuil ×5. Ne
benchmarkez pas `gateb_memory_v2.db` : ses 154 lignes de télémétrie cumulent les reprises
et erreurs corrigées pendant le chantier.
