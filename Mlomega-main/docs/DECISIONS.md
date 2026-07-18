# DECISIONS

## 2026-07-11 — E61-F : APK téléphone vérifiée, SDK lunettes jamais redistribué (ADR)

**Deux distributions, deux contraintes.** PhoneOnly est un artefact redistribuable : WELCOME le récupère depuis la dernière GitHub Release uniquement si le clone n'en possède pas, exige un sidecar SHA-256 et effectue une bascule atomique après vérification. L'APK publiée conserve le profil cible `192.168.1.199:8710`; une IP différente exige un build local explicitement injecté, elle n'est pas cachée derrière un pairing prétendument générique. XREAL embarque un SDK propriétaire et ne doit jamais être uploadée : WELCOME appelle un build local assisté en deux passes et restaure les artefacts projet sans dépendre de `git checkout`.

**Un build est une preuve de dépendances.** Le rebuild E61 a échoué avant IL2CPP sur les modules builtin Video et UnityWebRequestTexture absents, bien que les types existent dans le code et l'asmdef. Ils sont maintenant déclarés dans manifest/lock/asmdef. Les hashes ne sont documentés qu'après deux exits Unity réels à zéro ; le vieux `mlomega-xreal-g1.apk` reste diagnostic et n'est jamais renommé en produit.

## 2026-07-11 — E61-E : une installation n'est validée qu'après le vrai cœur nocturne (ADR)

**FAIL atomique, chemins explicites.** L'existence de `.venv\Scripts\python.exe` ne prouve ni WhisperX/pyannote, ni le token HF, ni la DB réellement utilisée. Le readiness profond et `DOCTOR -Full` exécutent donc la même sonde bornée dans `.venv`; cette sonde ouvre SQLite en lecture seule et ne crée aucun fichier pour s'auto-valider. `.env` est la source des chemins produit, les overrides process restent prioritaires et aucun fallback `data/*` n'est autorisé. Evidence brute et médias replay sont deux racines distinctes.

**Rollback jusqu'au dernier gate.** `.venv-live.previous` est une sauvegarde transactionnelle, pas un déchet de swap : elle reste présente jusqu'à la fin de WELCOME/Doctor, est restaurée sur erreur, puis supprimée uniquement après zéro FAIL. WARN reste non bloquant ; FAIL interdit tout message de succès et impose un code non-zéro. WELCOME crée le cœur avec un interpréteur explicitement vérifié 3.11/64-bit et initialise les chemins/DB configurés avant Doctor. Les builders Unity nettoient symétriquement le define de la cible opposée afin que PhoneOnly et XREAL ne dépendent plus de reverts Git manuels.

## 2026-07-11 — E61-D : recovery écrit avant la fin, média propriétaire par schéma (ADR)

**Le job précède l'état ended.** Écrire un marqueur seulement au prochain démarrage ne couvre pas une session déjà marquée ended. PhoneOnly persiste donc son recovery CloseDay avant toute mutation de fin BrainLive ; la fin normale et la reprise manipulent la même ligne durable.

**L'owner d'une frame n'est plus caché dans JSON.** `vision_frames.person_id` est la clé requêtable commune aux writers, replay et rétention. Les lignes historiques liées à une session héritent de son owner ; l'inattribuable est isolé, jamais attribué implicitement à `me`. La rétention ne scanne ni ne supprime les preuves d'un autre owner. L'ancienne FastAPI `mlomega_audio_elite.api` reste importable pour tests/migrations mais ne démarre qu'avec un opt-in legacy explicite ; elle n'est jamais un fallback de SessionHub.

## 2026-07-11 — E61-C : G1 est un diagnostic, l'APK XREAL porte le produit (ADR)

**Une APK de gate ne peut pas être annoncée comme produit.** `G1Gate.unity` reste la surface minimale pour diagnostiquer loader, Eye, pose et stéréo. Le builder distribué cible désormais `XrealProduct.unity`, générée depuis le même graphe que PhoneOnly mais avec `XrAdapterKind.Xreal`, sans preview plate. Elle embarque pairing, transport, UI, Reflex, menu, aide, replay et modèles device. Le nom `mlomega-xreal.apk` évite de confondre ce produit avec l'ancien artefact historique `-g1`.

**Un transport session = un peer courant.** Une re-offer ferme d'abord le peer précédent sous lock, retire ses DataChannels et remet l'origine PTS à zéro. Garder deux peers pour « faciliter » la reconnexion mélangeait audio et timestamps. Companion-web est, lui, un vrai second renderer : process lancé par RUN, assets servis par le serveur WS et dispatch continu ; SimOnly n'est plus son seul appelant.

## 2026-07-11 — E61-B : média hors DataChannel, actions structurées et privacy dure (ADR)

**Les octets replay restent en HTTP authentifié.** Le DataChannel ne porte que les refs bornées du bundle. SessionHub vérifie session+token, le service replay résout l'ID durable et Unity séquence les textures/vidéos dans le composant déjà admis. Le zoom local n'attend pas un crop PC : `RawImage.uvRect` recadre la texture adapter sur GPU à partir du centre/facteur Reflex.

**Un choix menu n'est pas une fausse phrase.** Les actions qui appartiennent au PC montent comme `device_intent{action,...}` et entrent dans les mêmes méthodes de l'unique `IntentRouter`. Quand une valeur manque (question mémoire ou heure replay), le routeur arme un tour multi-turn et consomme la prochaine parole naturelle. Les modes UI/apps/traduction/privacy restent locaux.

**Privacy libère réellement les capteurs.** Désactiver seulement les icônes ou tracks était insuffisant. L'adapter caméra est stoppé, WebRTC est disposé afin de rendre le micro, Reflex est forcé à l'arrêt et le watchdog connaît la pause. Comme aucun capteur vocal/gestuel ne peut logiquement réveiller un système qui les a libérés, le device expose un bouton local explicite de reprise ; la session transport/BrainLive durable n'est ni remplacée ni clôturée.

## 2026-07-11 — E61-A : un seul producteur nocturne, projections V19 sourcées (ADR)

**Ne pas ajouter un second cerveau.** Le Life Model canonique V15.10/V15.13 possède déjà la collecte de preuves owner-scopée, le contrat LLM patch-only et la quarantaine des sorties sans evidence. E61-A branche donc ce magasin réel vers `life_model_entries_v19` au lieu de créer un nouveau prompt. La projection est typée, idempotente sur `source_updated_at`, conserve `source_table/source_id` et n'invente aucun statement. Les tests qui appellent directement `apply_life_model_delta` restent utiles comme tests unitaires, mais ne sont plus la condition de fonctionnement produit.

**Calibration = causalité explicite ou abstention.** Une prédiction visuelle vérifiée ne prouve pas que les deux derniers observed cases sont similaires. Le watcher n'appelle désormais `register_verified_similarity_label` que si son spec fournit `calibration_case_pair{anchor_case_id,similar_case_id}` ; le validateur V18 garde ses contrôles owner/ordre temporel. Sans paire, le résultat est `no_causal_case_pair`, pas un faux label. `predictions_v19.source_entry_id` devient le lien durable utilisé lors d'une réfutation.

**Rebuild signifie rebuild.** `self_schema_v19` est la projection courante : après upsert des sources actives, les anciennes projections du même owner absentes du nouveau set sont retirées. Les `causal_edges`, historiquement sans colonne owner, ne sont admises qu'après résolution sûre de leurs endpoints vers des tables dont `person_id`/`memory_owner_id` correspond ; une causalité non prouvable est omise.

**Temps utilisateur d'abord.** Une heure parlée et une `package_date` représentent le temps civil `MLOMEGA_LOCAL_TZ` (Europe/Paris par défaut). Les requêtes persistantes restent UTC. Les fenêtres sont semi-ouvertes et traversent correctement DST/minuit ; `horizon_start_hour/end_hour` ne sont plus des champs décoratifs.

## 2026-07-10 — E59 : window management gestuel (grab/resize/close/minimise à la main) (ADR)

Le flux de position du pincement existait déjà (`GestureCallbacks.screenX/screenY` sur begin/update/end, projection des landmarks MediaPipe) : aucun changement Kotlin, la manipulation est purement Unity. Un `PanelManipulator` (assembly Reflex, comme MenuGestureController — Reflex→UI une seule direction, pas de cycle asmdef) consomme le même stream pinch que LensWindow. Désambiguïsation par hit-test world-space au `PINCH_BEGIN` contre un registre opt-in `IManipulablePanel` : hit sur un panneau = grab/resize/bouton **et le pincement est « claimé »** ; hit sur rien = non-claimé = le zoom LensWindow existant n'est jamais volé (le ReflexScheduler exécute le manipulator avant le lens et coupe le zoom si `HasClaim` — propriétaire unique, indépendant de l'ordre de souscription). Opt-in explicite : VirtualScreen (cible prioritaire, aspect ratio verrouillé, placement restauré à la réouverture) et les cards flaggées ; les éléments ancrés-objet n'implémentent pas l'interface et suivent le monde. Clamp de resize **proportionnel** sous aspect-lock (le bord ne distord pas la fenêtre vidéo). Placement mémorisé par type via `PanelPlacementStore` (session courante — délibérément PAS le `ui_state` du SceneCache, qui impose un TTL et ne stocke pas de transforms). Budget §9.4 tenu (pipeline gestes on-demand inchangé, pas d'alloc par frame). EditMode 8/8 nouveaux, suite complète 76/76.

## 2026-07-10 — E53 Phase A : « Viki mode aide » (moteur PC + UI bank Unity) (ADR)

**Plan = MICRO-ACTIONS (décision utilisateur).** Chaque step du TaskPlan est UNE action atomique = UN geste affichable (« verse la farine dans le bol »), jamais une étape composite — imposé par `_PLAN_SYSTEM`/`_DOC_PROMPT`. Un plan d'une seule action est légitime (aide ponctuelle en pleine activité).

**Coup d'œil scène initial.** Au démarrage de l'aide, UN appel VLM (`_guess_scene_context`, keyframe courante) devine le problème/les objets visibles et le contexte est injecté dans le prompt du plan → le plan colle à ce que l'utilisateur a réellement devant lui. Best-effort (échec = plan depuis la description seule), event-driven (jamais par frame).

**Latence par construction.** Le fantôme de N+1 est pré-poussé à l'entrée dans N (`task_panel.ghost_next` + anchors fantômes) → transition 0 latence ; le cloud (gpt-5.4-mini via le LLMRouter E33, coût affiché) ne sert qu'au plan + à UN indice visuel d'escalade (watchdog pas-de-progrès : indice local d'abord, cloud seulement si mode payant + `allow_cloud_hints`). Grounding : `label_en` des objets matché aux tracks WorldBrain/VisionRT, `track_id` joint au `task_anchor` — l'ancrage temps réel reste 100 % device.

**Routeur.** Grammaire help AVANT les règles génériques (piège translate_live) ; contrôles de tâche (« c'est fait », « répète », « étape suivante », pause/reprends/termine) via un PRÉ-ROUTEUR actif seulement quand une tâche tourne (paused inclus pour « reprends ») → jamais volés hors tâche. Multi-tour : « mode aide » seul → question → la description arrive au tour suivant. Persistance sqlite additive (reprise inter-sessions).

**UI bank Unity.** 12 atomes glass data-driven sous `UI/Components/TaskAtoms/` + 2 composants registre E25 (`task_panel` famille plan, `task_anchor` = cerveau de composition : compose les atomes selon le content, suit le track en temps réel, perte→recherche→réacquisition, hors-champ→flèche, multi-candidats→SelectionHighlight, fantôme promu sans recréation). Un seul owner émetteur de receipts par intent (la voie E25) ; les atomes sont des MonoBehaviour purs pilotés par le renderer. Aucun changement de scène requis (le registre est statique, UIRuntime instancie génériquement). Piège EditMode documenté : Awake ne tourne pas via AddComponent → config SceneCache injectée par réflexion dans les tests. Tests : PC 23 + non-régression = 62 verts ; EditMode TaskAtoms 9/9.

**Raccord produit E60.** Help est activé explicitement par PhoneOnly. H1 conserve le type `task_panel` au lieu de rabattre la livraison sur `context_card`; le panneau et chaque ancre ont un ID déterministe par tâche/étape/objet. Les ancres sont des UIIntents consommés par Unity, pas un nouveau type hot sans abonné. Le ghost N+1 est préconstruit mais invisible, puis un refresh même-ID le promeut sans recréation ; les trajectoires source→cible utilisent les `track_id` réellement groundés. Un enqueue H1 réussi est l'unique envoi du panneau ; le direct ne sert qu'au fallback/dedup de reconnexion. La persistance Help partage la base produit avec verrou multi-thread. « mode aide » n'impose aucun plan : la description naturelle suivante, même en plein milieu d'une tâche ou limitée à une action, est transmise au LLM et le plan commence au blocage déclaré.

## 2026-07-09 — E58 : wake word par transcription ASR française, changeable sans rebuild (ADR)

**Pourquoi pas le KWS ni la voix.** Le KWS sherpa embarqué est entraîné en anglais → un mot français (« viki », « jarvis ») est matché en phonèmes anglais (« vaïki »/« djarviss »), inutilisable pour un francophone. L'enrôlement vocal résoudrait la prononciation mais = nouveau modèle lourd + speaker-dépendant + ré-enregistrer pour changer. Décision : **détecter le mot dans la transcription de l'ASR français** qui tourne déjà sur l'appareil (sous-titres/mémoire) → prononciation naturelle, aucun modèle nouveau, coût quasi nul, changeable en tapant le mot.

**Détection.** `WakeWordMatcher` (Kotlin pur, testé JVM) : normalise (minuscules, sans accents/ponctuation) et match par token avec tolérance d'édition (Levenshtein, budget selon longueur — exact pour les mots courts, ±1-2 pour les longs) pour absorber les variantes ASR (« vicky »/« viqui »). Branché dans `AsrKwsService.decodeSegment` sur le FINAL ASR → `openCommandWindow` (gate le ROUTAGE seulement ; capture jamais coupée). Le KWS anglais reste en place mais inoffensif. Conséquence assumée : l'ASR par défaut passe en **français** (le mot est entendu dans la langue de l'ASR) ; choisir un mot **rare** (on scanne tout le discours → un mot courant = faux déclenchements).

**Changeable sans rebuild.** Source de vérité = `wake_word` du profil PC (défaut « viki »). Le PC le **pousse** au device (`device_command set_wake_word`) à la première réception DataChannel (`PhoneOnlyRuntime._on_receipt`, idempotent/session) → `AsrBridge.SetWakeWord` → natif `setWakeWord` (appliqué même si le service démarre après). Changer le mot = éditer `configs/user_profile.yaml`, effectif à la session suivante, zéro rebuild. L'installateur redemande « comment appeler l'assistant ? » (défaut viki, conseil mot rare). Câblage Unity par événement `DeviceCommandHandler.SetWakeWordRequested` (UI ne peut pas référencer Reflex — cycle). Tests : matcher JVM + `test_push_wake_word_sends_set_wake_word_command_once` + 19 tests live pipeline verts. APK v4 embarque le matcher.

## 2026-07-09 — E49 : support lunettes XREAL (SDK 3.1.0 intégré, APK buildée) (ADR)

**Intégration SDK sans casser PhoneOnly.** Le SDK XREAL 3.1.0 est propriétaire (~248 Mo) : déposé sous `apps/xr-mobile/Packages/xreal-sdk/` (git-ignoré) et **non commité**. Le `manifest.json` commité reste XREAL-free — sinon un clone PhoneOnly sans le tarball aurait une résolution de package cassée (erreur UPM, bloque même PhoneOnly). La dépendance `com.xreal.xr` file: est **injectée au build** par `AndroidBuildXreal.EnsureXrealPackage` (et retirée du commit). `Core.asmdef` référence l'assembly XREAL par **GUID** (`2b1cc58b…`) — sur un clone sans SDK, référence non résolue = simple warning, et le code XREAL (sous `XREAL_SDK_PRESENT`, define off en PhoneOnly) est compilé out. Idem defines/config XR (loader) : générés au build lunettes, jamais commités.

**Adaptateur recâblé sur l'API RÉELLE du SDK 3.1.0.** L'`XrealDeviceAdapter` (écrit à l'aveugle en E22) visait des noms d'API inexistants — corrigés après inspection du tarball : `RGBCameraTexture`→`XREALRGBCameraTexture` (un `SingletonMonoBehaviour`, accès via `CreateSingleton()`), `Play/Stop`→`StartCapture/StopCapture`, `DidUpdateThisFrame`→callback `OnRGBCameraUpdate`, `GetFrameTimestampNs`→`GetTimeStamp()`, `GetDeviceName`→`GetDeviceType()`, tracking via `UnityEngine.XR.InputDevices` (isTracked) plutôt qu'une API interne. C'était LE risque de la passation (« l'API du SDK pourrait ne pas coller au stub ») — levé : compile 0 erreur.

**Build lunettes.** `AndroidBuildXreal` : injecte la dép, pose `XREAL_SDK_PRESENT` (retire `MLOMEGA_PHONE_ONLY`), active le loader `Unity.XR.XREAL.XREALXRLoader` pour Android via `XRPackageMetadataStore.AssignLoader` (+ `XRGeneralSettingsPerBuildTarget` créé si absent), IL2CPP/ARM64, minSdk29/target34, appId `com.mlomega.xr.glasses`, scène `G1Gate`. Résultat : EditMode compile OK, IL2CPP OK, **`mlomega-xreal-g1.apk` (~191 Mo) produite**, loader assigné. Deux APK distincts : `mlomega-phoneonly.apk` (téléphone) et `mlomega-xreal-g1.apk` (lunettes), même code. Reste : gates G1 réels sur lunettes physiques (matériel non encore en possession de l'utilisateur).

## 2026-07-09 — E56 : VLM lourd de nuit (V19) + installateur one-click complété (ADR)

**VLM live vs nuit.** Le VLM live (jour) est `moondream` — léger, une vignette à la fois, à la demande. La deep-vision de NUIT (`brainlive_offline_deep_vision_v16_1`) tourne un VLM VISION lourd sur les keyframes SÉLECTIONNÉS par bundle (~12/bundle), chargé pour cette seule phase puis `ollama_unload`. Elle N'analyse PAS la vidéo ni les clips E55 (ceux-ci servent au replay utilisateur). Résolution du modèle : param → `MLOMEGA_OFFLINE_VLM_MODEL` → `MLOMEGA_VLM_HEAVY_MODEL` → `MLOMEGA_VLM_MODEL` → `settings.ollama_model`. Le template V18.8 pointait `qwen3-vl:8b`, mais le manifeste V19 ne déclarait que `moondream` → gap. Décision : entrée `vlm_heavy` dans `MODEL_MANIFEST.yaml`, défaut **`qwen2.5vl:7b`** (le modèle vision que l'utilisateur utilise déjà) ; l'installateur détecte le tag exact et pose les vars d'env. Profil dégradé (<6 Go VRAM) → VLM nuit ramené sur le léger.

**Installateur one-click complété.** Deux trous rendaient WELCOME non « one-click » : (1) le `.venv` COEUR (moteur du close-day nocturne : torch/whisperx/pyannote) n'était pas créé — `INSTALL_MLOMEGA_V19_WINDOWS.ps1` ne crée que `.venv-live` et ne touche jamais `.venv` ; (2) le binaire Qdrant n'était pas provisionné — `START_QDRANT.ps1` attend `tools\qdrant\qdrant.exe` et échoue sinon. WELCOME crée désormais le `.venv` cœur (`python -m venv` + lock, idempotent, étape la plus longue signalée) et télécharge Qdrant `v1.12.6` (release GitHub) + génère son `config.yaml`, en best-effort. Restent des prérequis non auto-installables (Python 3.11, appli Ollama) : détectés et guidés, jamais installés en douce. Dry-run exit 0.

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

## 2026-07-12 — E64-C : fenêtrage token-aware & checkpoints durables (ADR)

**Contexte.** Le premier vrai passage nocturne a bloqué Brain2 (bundle 1.6M chars, `finish_reason=length`, OBS-13). E64-A/B ont posé le contrat commun (`NightStageAdapter`, `EvidenceRef`) et la réduction déterministe lossless (472 observations → 120 atomes). E64-C ajoute l'exécuteur générique qui découpe le travail en fenêtres bornées et le rend reprenable, SANS toucher aux prompts métier ni au close-day (câblage = E64-F).

**Noms de tables figés (n'en créer aucune autre).** `night_llm_windows_v19` (une ligne par (sous-)fenêtre : état, tentatives, tokens d'entrée, budget de sortie, erreur, digest de sortie, timestamps) et `night_llm_window_outputs_v19` (sorties VALIDÉES, PK `(window_key, output_digest)`, idempotent). Schéma dans `src/mlomega_audio_elite/night_orchestrator/checkpoint_store.py`.

**Clé idempotente.** `window_key = "nlw_" + sha256(person|day|stage|input_digest|window_index|adapter_version|prompt_version|model)[:24]`. Elle ne dépend JAMAIS d'une sortie LLM. Changer d'adaptateur, de prompt, de modèle ou d'entrée crée une nouvelle unité de travail (nouvelle ligne) ; rejouer à l'identique reprend la même ligne. Preuve : `test_window_key_is_idempotent_and_scope_sensitive`.

**Fenêtrage.** Cible 40–50 unités utiles, mais coupé plus tôt par le budget de tokens réel (`ModelBudget.max_input_tokens = context_window − output_reserve − safety_margin`) ou une frontière dure (scène/épisode). Chevauchement borné en tête de fenêtre (`overlap_refs`, marqué, non primaire) pour ne pas couper une action ; le merge dédupliquera par refs sources. Invariant testé : chaque unité est primaire dans EXACTEMENT une fenêtre.

**Politiques d'échec (jamais de partiel appliqué).** Sur `finish_reason=length` (ou JSON/contrat invalide côté modèle) : subdivision RÉCURSIVE de l'entrée (`subdivide`, moitié/moitié) — jamais augmenter `num_predict` indéfiniment ; parent marqué `subdivided` (repris sans rappeler le LLM), une unité seule irréductible qui tronque encore → `quarantined`. Sur budget dépassé : subdivision, ou quarantaine d'une unité seule surdimensionnée (appel refusé avant émission). Sur sortie `ok` mais invalide au contrat : une réparation bornée (1 retry) puis quarantaine. Sur timeout/Ollama down : retry backoff borné puis état `error` (retryable, non appliqué, repris au prochain run). Thinking désactivé pour les contrats JSON ; budget d'entrée et de sortie réservés séparément.

**Découplage & tests.** L'exécuteur (`run_windows`) prend des callables `render`/`validate` + un `WindowLLM` (le vrai `OllamaJsonClient` sera enveloppé en E64-F) ; aucun prompt métier ici. 13 tests (`tests/v19/test_e64c_executor.py`) couvrent : cible vs budget, losslessness du plan, marqueurs overlap, frontière dure, complétion+checkpoints, reprise sans double sortie, subdivision récursive couvrant tout, quarantaine d'une troncature irréductible, refus d'une unité surdimensionnée, réparation bornée puis quarantaine, retry transitoire puis reprise, clé idempotente. Total E64 : 27 tests verts. **Prochaine étape = E64-F vague 1** : adaptateur EpisodeBuilder/Brain2 câblant cet exécuteur pour débloquer OBS-13.

## 2026-07-12 — E64-D/E : fusion hiérarchique & manifeste anti-perte (ADR)

**Contexte.** Sur consigne de Codex (le planificateur), D (fusion) et E (couverture) sont livrés AVANT E64-F : sans eux, brancher Brain2 réel pourrait « marcher » tout en perdant ou dupliquant des preuves. Faits avec le faux `WindowLLM` ; toujours additif, non câblé au close-day, aucun prompt métier touché.

**E64-D — fusion hiérarchique déterministe** (`src/mlomega_audio_elite/night_orchestrator/merge_tree.py`). Les sorties par fenêtre sont pliées PAR CODE le long d'un arbre déterministe (fenêtres → scène/bundle → conversation → journée), jamais en reconcaténant tout dans un nouveau prompt géant. `MergeItem` porte `semantic_key`, `evidence_refs`, plage temporelle, `parent_items`. `resolve_overlap` déduplique le chevauchement voulu de E64-C : deux items fusionnent SEULEMENT si même `semantic_key` ET (leurs `evidence_refs` s'intersectent OU leurs plages temporelles se recouvrent) — JAMAIS sur le texte ; le survivant absorbe les `evidence_refs` du doublon (provenance préservée). La MÉCANIQUE (groupement trié, dédup, ordre de pli) est commune ; l'adaptateur ne fournit que sa règle métier `combine` (le `default_combine` unionne les preuves et ne perd rien).

**E64-E — manifeste de couverture anti-perte** (`coverage.py`). Chaque preuve attendue tombe dans exactement un seau : `covered` (citée directement), `represented_by_atom` (couverte transitivement via `parent_refs` d'un atome — ex. un `VisionChangeAtom` pour 400 observations), `overlap_deduplicated` (repliée dans un survivant), `quarantined` (avec cause), `missing` (→ bloque le stage). « Bruit/redondant » n'a jamais le droit de disparaître : il est représenté par un atome parent ou quarantiné avec cause. La couverture est calculée en RELISANT les sorties persistées dans `night_llm_window_outputs_v19` (`covered_refs_from_outputs_table` + un `extract_refs` métier), jamais sur des IDs simplement renvoyés en mémoire. `stage_stats` agrège tokens/tentatives/troncatures par stage depuis `night_llm_windows_v19` (pas de nouvelle table) pour Doctor/dashboard.

**Tests.** 10 tests (`tests/v19/test_e64de_merge_coverage.py`) : dédup par preuve partagée (union), NON-dédup sur texte seul, clé sémantique différente jamais fusionnée, pli scène→journée lossless, refs transitives préservées après dédup, les cinq seaux du manifeste + `missing` qui bloque, chaque id dans un seul seau (covered l'emporte), relecture depuis la table (pas les IDs renvoyés), `stage_stats` agrégé. **Total E64 = 37 tests verts.** Prochaine étape = E64-F vague 1 (Ollama réel + EpisodeBuilder/Brain2).

## 2026-07-12 — E64-F vague 1 : EpisodeBuilder fenêtré (débloque OBS-13) (ADR)

**Contexte.** Validé par Codex : garder le prompt V13, l'exécuter par fenêtres autonomes, fusionner les sorties structurées avec preuve de couverture persistée, flag de rollback. Trois morceaux, tous dans le vrai chemin nocturne, gardés par `MLOMEGA_E64_NIGHT_ORCHESTRATOR` (défaut ON ; `=0` restaure l'ancien comportement).

**Constat.** Réduction seule insuffisante : 945→~120 atomes vision + 40 audio ≈ 160 tours ≈ 64K tokens > `num_ctx` Brain2 (16384). Il faut réduire ET fenêtrer.

**Morceau 1 — réduction au producteur.** `brainlive_event_assembler_v15_14.py::_pseudo_turns_for_bundle` émettait 1 pseudo-tour `context_vision_raw` par observation (~945). Désormais (flag ON) `_vision_pseudo_turns` collapse les observations consécutives de même état en 1 pseudo-tour par `VisionChangeAtom` (via `reduce_vision_timeline`) ; forme/`speaker_label`/`evidence_role` inchangés (Brain2 lit à l'identique, juste moins nombreux), `metadata.source_refs` garde tous les `observation_id` (lossless), frames brutes conservées. Fallback sûr sur toute erreur → comportement legacy.

**Morceau 2 — EpisodeBuilder fenêtré.** `brain2_strict_v13_2.py::_ensure_episodes_strict` : si orchestrateur ON ET les tours ne tiennent pas dans un appel (`should_window`), délègue à `brain2_episode_windowing.build_episodes_windowed` ; sinon chemin legacy (1 appel) inchangé. Le module fenêtre les tours (`plan_windows`, ~45 tours, overlap 3, budget `MLOMEGA_E64_WINDOW_INPUT_TOKENS`=9000), exécute le **même prompt/`system`/schéma V13** (`_safe_prompt_payload` + `_llm_require_json`) par fenêtre autonome, fusionne les épisodes par ensemble de `evidence_turn_ids` identiques (dédup overlap par preuve, jamais texte), matérialise une fois (`_materialize_episodes_from_qwen`). Le texte de mission V13 est extrait en constante `_EPISODE_MISSION` partagée par les deux chemins (aucune modification de prompt). Limite connue : un épisode qui chevauche une frontière de fenêtre peut être scindé (overlap 3 couvre l'identique, pas le partiel) — acceptable vague 1, coverage reste complète.

**Morceau 3 — preuve de couverture persistée + flag.** Nouvelle table `night_llm_coverage_v19` (`coverage.persist_coverage`) : expected/covered/missing par (person, jour, stage, conversation). `build_episodes_windowed` crédite la couverture aux tours PRIMAIRES des fenêtres (overlap = copie) ; un `missing` non vide lève (stage bloqué), jamais de perte silencieuse. Rollback : `MLOMEGA_E64_NIGHT_ORCHESTRATOR=0`.

**Tests.** 7 tests `tests/v19/test_e64f_wiring.py` (réduction flag on/off/changement, `should_window`, builder fenêtré multi-fenêtres + fusion + couverture persistée 120/120, couverture complète même à 0 épisode, dédup preuve) + 8 briques `test_e64f_brain2_blocks.py`. Non-régression : `test_e37_nightly.py` + `test_ollama_context_budget.py` = 13 verts. **Total E64 = 54 verts.** RESTE : validation run réel bout-en-bout (harnais `--with-close-day` sur la vraie vidéo) — le code est fait et testé avec un faux LLM, la preuve Ollama réelle + dashboard est l'étape suivante.

## 2026-07-12 — E64-F vague 1 : rectification du branchement et premier run réel interrompu avant F

**Pourquoi le premier statut « fait » était trop rapide.** Le commit `ccec994` utilisait le planificateur, mais appelait le LLM directement. Il contournait `run_windows`, `OllamaWindowLLM`, les checkpoints, la subdivision et les retries E64-C. Sa couverture créditait les entrées planifiées en mémoire au lieu de relire une sortie durable : un appel vide pouvait sembler vert. Ce chemin n'est plus autoritaire.

**Contrat corrigé.** EpisodeBuilder utilise maintenant `run_windows` et le vrai adaptateur Ollama. Une sortie ne devient couvrante qu'après validation puis écriture atomique dans `night_llm_window_outputs_v19` avec son manifeste primaire ; `covered_refs_from_outputs_table` la relit. Les observations représentées par un `VisionChangeAtom` sont développées transitivement via `metadata_json.source.source_refs`, ce qui permet un manifeste attendu de 985 preuves (40 tours + 945 observations), même si le prompt ne contient qu'environ 160 unités. Une fenêtre error/quarantine bloque toute matérialisation. `truncated_output` réel déclenche la subdivision. Les transitions de checkpoint sont commités, la clé dépend du digest du payload réel et le stage est isolé par conversation.

**Fusion/reprise.** Deux épisodes de fenêtres voisines peuvent avoir des ensembles de preuves partiellement différents : ils fusionnent seulement si une clé métier structurelle compatible ET une intersection de preuves/plage l'établissent, jamais sur le texte. Les refs sont unionnées. Les épisodes finis portent `episode_source=STRICT_VERSION` et `coverage_status=complete` afin qu'une reprise idempotente les reconnaisse.

**Preuves automatisées.** 60 tests E64, puis 13 régressions nocturnes/contexte : **73 verts**. Cas nouveaux : checkpoint visible après fermeture/réouverture SQLite, digest modifié sous ID stable, erreur Ollama `truncated_output`, échec non crédité/non matérialisé, 985 preuves sources et épisode partiel traversant une frontière.

**Premier essai réel après correction.** Le run vidéo du 2026-07-12 a validé le transport live (301 s, 15 077 chunks audio, 30 tours, 3 clips) mais PAS E64-F : `/session/end` a expiré, BrainLive est resté `active`, `close_day=not_started`, aucune table `night_llm_*` n'a été créée. Les logs montrent des flushs LiveDiscourse LLM invalides/tronqués et le statut de fermeture ne nomme pas encore le drain responsable. La base scratch est conservée pour startup recovery. Décision : ne pas relancer la vidéo ni le dashboard ; réparer/observer la frontière de fermeture, reprendre la même DB, puis juger F sur les checkpoints réels.

## 2026-07-12 — E64-B/F : frames brutes = preuves, pas changements cognitifs

**Mesure réelle qui invalide le premier reducer.** La nouvelle capture porte 1 407 lignes vision : 709 `vision_frames` brutes (sans objets, résumé unique contenant le nom du JPG) et 698 `vision_scene_observations`. Elles alternent dans `vision_timeline_json`. Le reducer les comparait toutes comme des états : raw vide → observation détectée → raw vide, donc 1 407 atomes unitaires. Envoyer ce flux aurait créé au moins 32 fenêtres racines de 45 unités pour cinq minutes.

## 2026-07-12 — E64-F EpisodeBuilder v4 : contexte conservé, sortie bornée (ADR)

**Décision.** Ne pas échantillonner les preuves et ne pas attendre un `finish=length` coûteux. Séparer le payload durable de sa projection LLM : les IDs opaques et les copies exactes WhisperX/vision sont remplacés dans le prompt par `count+digest`, tandis que les lignes brutes restent inchangées et sont développées par la couverture. Une répétition réellement prononcée reste dans `turn.text`; seules ses copies techniques `source.words`/`whisperx_segment.words` sont compactées. Les informations non dupliquées restent visibles (speaker/person, temps, objets, activités, OCR, pertinence, scores d'alignement).

**Responsabilité de fenêtre.** EpisodeBuilder utilise deux tours primaires par sortie et deux tours précédents comme contexte lisible. Le `window_contract` interdit de produire un épisode uniquement depuis `context_only`; la normalisation réapplique cette règle par code. Le contexte évite la baisse de qualité observée sur deux tours isolés, mais le JSON reste proportionnel à deux primaires. La mission V13 et tous ses champs métier restent présents. Adaptateur `e64f-episode-window-v4`; changer la projection change le digest et empêche toute reprise d'un résultat ancien incompatible.

**Contrat de sortie.** Le template historique ne suffisait pas : Qwen copiait parfois les turns complets dans `evidence_turn_ids` et créait des épisodes de méta-commentaire sans preuve. Ollama reçoit désormais un vrai JSON Schema ; la normalisation extrait les `turn_id` cités, filtre les références hors fenêtre, exige au moins une preuve primaire et convertit les scalaires avant SQLite. Aucun fragment ni épisode sans preuve n'est matérialisé.

**Mesures.** 158 tours réels : 130 806 → 68 343 tokens (-47,8 %), sans perte des 1 407 refs vision. Le test intermédiaire 4B/4k a été invalidé après inspection d'`ollama ps`; seule la phase post-stop 9B/16k fait foi. Fenêtre réelle froide : 68,8 s, chaude : 8,7 s, toutes deux `finish=stop` et contenu cohérent. Le planificateur retire aussi le coût fixe mission+schéma avant de construire les fenêtres. 53 tests ciblés verts. Gate encore ouvert : CloseDay complet, couverture finale et Dashboard.

## 2026-07-12 — E64-F : versionner la relecture et checkpoint chaque moteur V13 (ADR)

**Isolation de version.** `stage_name` est une identité métier, pas une frontière d'adaptateur : les sorties v2 restent auditées sous le même nom que v4. Couverture et merge doivent donc relire uniquement les `window_key` feuilles produites/reprises par l'exécution courante. Une sortie d'ancien adaptateur ne peut plus créditer une preuve ni entrer dans le résultat courant.

**Frontière writer.** Un identifiant généré par le LLM n'est jamais une preuve que son parent existe. Chaque FK V13 dynamique est validée avant writer ; les turns doivent en plus appartenir à la conversation. Une référence optionnelle inconnue devient NULL, une observation qui exige cette preuve (prosodie/boundary) est ignorée. Une barrière commune inspecte aussi `PRAGMA table_info/foreign_key_list` pour les 16 moteurs : objets/listes vers TEXT deviennent du JSON déterministe (contenu conservé), les nombres sont extraits seulement d'un scalaire explicite. Les parents déterministes créés par code restent inchangés.

**Reprise fine.** EpisodeBuilder couvert est commité avant la matrice V13. Chaque couple `(episode,engine,prompt_hash)` commit ensuite atomiquement sortie validée + projections. Une reprise recharge `v13_engine_outputs` seulement si run status `ok`, validation `valid` et hash identique ; elle réinjecte la sortie dans le contexte des moteurs suivants sans rappeler Ollama. Cela conserve les 16 passes mais supprime les replays après crash. Le coût restant (19×16 appels sur la fixture) est un sujet de performance, pas une autorisation à supprimer des moteurs.

**Découpage de sortie, puis limite constatée.** Les champs métier d'un moteur sont des unités E64 : au plus 3 par appel, 2 pour un schéma large, preuves/confiance communes, checkpoints et fusion déterministe. `internal_state_engine` restitue ainsi ses 10 champs au lieu d'un fragment `length`. Les diagnostics `missing_context` détaillés restent dans les outputs de fenêtre et l'épisode porte count+digest ; les tours utilisent la projection lossless. Malgré cela, la mesure 9B est 195,8 s pour un seul moteur/épisode. Décision : ce splitter reste le filet anti-perte ; la production doit passer à une matrice moteur→fenêtres d'épisodes, et non épisode→16 appels. L'applicabilité par modalité ne supprime pas un moteur : elle empêche une inférence psychologique sur un événement exclusivement capteur, déjà traité par Vision/WorldBrain.

**Décision lossless.** Une `vision_frames` brute ne constitue pas un changement sémantique. Elle est rattachée à l'observation sémantique temporellement la plus proche, puis conservée dans `source_refs`/`frame_refs` de l'atome. Seules les observations sémantiques ouvrent/ferment les plages. Si une timeline ne contient que des frames brutes, elles deviennent une plage de preuves unique plutôt que des événements pilotés par noms de fichiers. Aucun fichier, ID, hash ou observation n'est supprimé.

**Preuves.** Sur la DB scratch réelle : 1 407 entrées → **132 `VisionChangeAtom`**, 1 407 `source_refs` uniques, max 207 observations sémantiques dans une plage ; export produit immuable : **162 tours (132 vision + 30 audio)** contre 1 433. Tests dédiés : interleaving raw/semantic, camera-only, provenance exacte ; 35 ciblés verts et 44 avec E37.

**Invalidation aval.** L'identité d'un artifact Deep Audio inclut désormais le digest du contexte Brain2 réduit, en plus des WAV et du profil. Une évolution du reducer ne peut donc plus reprendre silencieusement une conversation raffinée construite avec l'ancien contexte, même si l'audio n'a pas changé.

## 2026-07-13 — E64-F : packs d'épisodes, hiérarchie bornée et reprise stable (ADR DE PASSATION)

**Pourquoi la matrice a été remplacée.** La matrice historique exécutait jusqu'à 16 requêtes par épisode et resérialisait le même contexte à chaque moteur. Sur la fixture, 19 épisodes (dont 8 capteur-only) donnaient 304 appels avant Life Model. La décision retenue n'enlève aucun moteur : EpisodeBuilder v5 sépare les preuves humaines des observations système, puis chaque épisode humain exécute en un pack tous les moteurs réellement applicables. Chaque moteur conserve son propre schéma et son propre writer. Les événements exclusivement capteur restent intégralement couverts par Vision/WorldBrain/Silent Life et ne sont plus transformés artificiellement en psychologie utilisateur.

**Pack local.** L'unité de subdivision est `(engine, groupe_de_champs)`. Le chemin rapide sérialise l'épisode une fois et demande toutes les responsabilités applicables dans l'ordre Brain2. Si Qwen atteint `length`, `run_windows` divise ces responsabilités et le merge par code restitue exactement chaque champ, unionne evidence/counter-evidence et agrège la confiance. Le contrat vérifie toutes les clés avant writer. Sur la fixture réelle, EpisodeBuilder produit 12 épisodes humains ; les 12 packs locaux ont atteint `completed` en 9B/16k. Un seul pack a dérivé à `length` et ses deux enfants ont couvert les six moteurs.

**Bundle source immuable.** Un pack ne lit jamais comme entrée les tables qu'il vient de matérialiser (`situations`, `states`, `thoughts`, `causes`, etc.). Son bundle commun contient épisode, conversation, tours projetés et contexte stable ; les emplacements hérités de sorties sont maintenus vides pour conserver la forme. Les dépendances validées circulent uniquement dans `prior_engine_outputs`. Sans cette séparation, chaque writer changeait le hash du prompt suivant et une reprise se nourrissait de ses propres sorties.

**Projection sans perte.** Les lignes brutes restent immuables et la couverture continue de développer leurs parents. Le LLM reçoit le texte exact, temps, speaker/person, qualité d'alignement, segmentation et sémantique vision/OCR. Les listes mot-à-mot WhisperX dupliquées, IDs de bundle, digests opaques et copies de `representative` n'ont aucune valeur cognitive et restent hors prompt. Le cas difficile est passé de 6 836 à 5 128 tokens ; en run 9B chaud, 104,1 s avant projection contre 28,75 s après, avec les mêmes 6 moteurs et 8 groupes validés.

**Clé de reprise.** `PlanUnit.content_digest` ne suffit pas lorsque le prompt contient un contexte commun. `run_windows` digère maintenant la requête rendue complète et combine ce digest au digest planifié avant de calculer `window_key`. Changer bundle, règles, schéma ou prior invalide donc le checkpoint. Test dédié : mêmes unités et même scope, contexte commun différent ⇒ nouvelle clé et nouvel appel ; contexte identique ⇒ reprise sans appel.

**Phase modèle.** Les fonctions V13 nocturnes entrent elles-mêmes dans `phase("post_stop_brain2_v13")` pour construire et appeler le client. Garder le modèle en VRAM n'entretient aucun historique conversationnel : chaque requête Ollama est stateless, `think=false`, sans champ `context`. Le garde interne empêche en revanche qu'un outil direct sélectionne le modèle live 4B/4k tout en utilisant un budget planificateur 16k.

**Hiérarchie transversale.** `run_hierarchical_json` reçoit des collections sous forme de feuilles stables, les traite par fenêtres, puis fusionne des sorties validées en conservant les parent refs transitives. Pour les six moteurs globaux V13, la feuille est une capsule d'épisode contenant résumé, IDs de preuves et sorties locales complètes. Une petite conversation peut rendre tous les moteurs ensemble ; une longue journée fenêtre les capsules. Si le schéma combiné est trop grand, l'adaptateur partage les responsabilités par groupes de schémas, jamais les preuves.

**Politique `length` par frontière.** Sur une fenêtre de preuves, `length` autorise la subdivision des preuves. Sur un niveau de fusion, les entrées sont déjà des sorties full-schema : les subdiviser indéfiniment recrée le même JSON et peut boucler. `run_windows(subdivide_on_length=False)` remonte donc immédiatement ce signal au merge ; l'adaptateur partage alors les schémas. Un ancien checkpoint `subdivided` est promu en quarantaine explicite lors de cette reprise afin de ne pas redriven ses enfants. Un fan-in qui ne réduit pas son nombre de sorties échoue aussi immédiatement.

**Migration des vagues 2/3 en code.** Les helpers V14/post-stop, Silent Life, coordination BrainLive↔Brain2, bootstrap/updater Life Model, live-ready et Pattern Mirror périodique utilisent le runner hiérarchique lorsqu'un contexte de stage est fourni. Les appels interactifs conservent leur voie directe. Deep Vision reste une image VLM bornée et checkpointée par image : l'envelopper de nouveau n'apporterait rien. Les stages déterministes ne sont pas transformés en appels LLM. Cette migration n'est pas déclarée produit tant que le run réel n'a pas traversé V14, Life Model et longitudinal.

**État au commit.** 43 tests centraux verts, puis **98 tests élargis passés** (E64 A–F, E37, budget Ollama, longitudinal, multi-session CloseDay) et compilation des quatre modules centraux. La première fenêtre globale réelle (10 capsules, 10 463 tokens) est verte, mais la fusion combinée a atteint `length`. Le fallback réel par groupes de schémas n'a pas été mené jusqu'au manifeste final avant la pause. Le gate Vague 1 reste donc ouvert. Les temps observés pendant trois runners Python orphelins ne sont pas des benchmarks ; l'exécution suivante doit garantir un seul process et prouver une seconde reprise sans nouvel appel.

## 2026-07-14 — E64-F : premier CloseDay complet, preuve stricte et projection live déterministe

**Preuve de chaîne.** La DB scratch `tools/harness/_audit/one_minute_memory_v1.db` a finalement terminé le run `run_v18_65bdecb7404f4e05abe16cf843f124e4`. Les dix stages CloseDay sont `completed`; le manifeste `v18_pipeline_output_manifests` a relu les sorties durables et porte `complete=1`; tiering, rétention et maintenance sont `ok`. Le temps global du run (plusieurs heures avec pauses, corrections et reprises) n'est PAS un benchmark. Seules les durées de fenêtres/stages isolés seront utilisées dans E64-H.

**Backend direct, sans changement de défaut produit.** `OllamaJsonClient` accepte désormais `MLOMEGA_LLM_BACKEND=llamacpp` avec endpoint OpenAI-compatible et modèle explicites. La validation a utilisé `llama-server` sur Qwen3.5 9B Q4_K_M, `ctx-size=24576`, `parallel=1`, continuous batching, GPU auto, flash-attention, cache K/V q8, `reasoning off`, Jinja/JSON, sortie 4096. Cette voie est opt-in pour instrumentation/benchmark; Ollama reste le défaut tant que l'audit comparatif n'a pas tranché.

**Prévention transversale.** `run_hierarchical_json` mesure la requête réellement rendue, développe les listes JSON persistées en feuilles au lieu de répéter un blob, sépare les responsabilités de sortie avant un appel condamné à tronquer, ne mélange pas objet sémantique et union lossless, et impose un budget de cardinalité à la projection dérivée. Les preuves sources restent dans leurs tables et dans le manifeste. Le planificateur utilise de nouveau 45 unités utiles par fenêtre; le token budget reste la limite dure. Toute modification de ces règles versionne adapter/prompt et ne peut reprendre un ancien faux vert.

**Life Model : preuve puis écriture.** Le schéma exige des références `{source_table,source_id}`. Les identifiants `nightleaf_*` sont résolus déterministiquement vers la feuille originale, puis validés owner/scope contre la table réelle; le nom de table proposé par le modèle n'est jamais cru. La matérialisation valide l'ensemble avant la première écriture, exclut les sections consultatives des tables canoniques, et reste atomique. Le CLI sérialise en ASCII sûr pour ne plus transformer un succès en échec CP1252 sous Windows.

**Live-ready n'est pas une nouvelle inférence.** Une fois V15.10 disponible, les routines, lieux, besoins, expressions, trajectoires, relations, hooks et règles existent déjà avec preuves. Les renvoyer dans 303 k caractères à Qwen a créé des dizaines d'appels et une sortie moins fidèle. Décision : compiler ces lignes par code vers `LIVE_READY_SCHEMA`, conserver le raw feed complet dans l'export, et garder le LLM uniquement comme fallback pour une DB legacy sans modèle canonique. Cela ne retire aucun moteur cognitif : cela supprime une reformulation redondante après la vraie inférence. Sur le run réel, `live_ready` passe en ~2,1 s.

**Gates encore ouverts.** Deep Vision ne peut pas être considéré vert quand toutes les images sélectionnées sont quarantinées; ASR à confiance nulle et réconciliation basée sur absence de preuve doivent bloquer ou réduire fortement la confiance; les bypass diagnostics V13.4/V14 ne valent pas validation produit; FIRST_TRY doit prévalider HF/proxy, Qdrant, CUDA/cuDNN, versions Python et modèles. E64-H mesure ensuite chaque moteur avant toute fusion, remplacement 4B ou décision DeepSeek.

## 2026-07-14 — E64-H/I : décision de refonte de cardinalité avant choix cloud

**Mesure.** Le premier chemin final traversé, après les optimisations E64 déjà livrées,
effectue 169 appels texte, environ 1,119 M tokens d'entrée estimés, 218 k de sortie et
83 min de calcul sur la fixture auditée. Avant E64, le bundle de 1,6 M caractères/985
pseudo-tours ne terminait pas ; l'architecture intermédiaire demandait 304 appels V13
seulement. E64 a donc bien supprimé une première explosion, mais pas l'amplification
métier restante : 26 tours → 10 épisodes fragiles → ~324 lignes V13 → 92 objets Life
Model actifs.

**Décision.** Ne pas remplacer globalement Qwen9B par Qwen4B et ne pas envoyer la nuit
actuelle entière à DeepSeek. Construire d'abord un contrat de faits typés avec preuve
source : une inférence chère est produite une fois puis réutilisée pour matérialiser les
tables V13/V14/coordination/Life compatibles. Les capacités et preuves restent, les
ré-inférences disparaissent. EpisodeBuilder, causalité, interne, relations,
réconciliation et promotion Life restent 9B. Le 4B n'est éligible qu'aux tâches
structurelles/faible risque après test de couverture et de verdict identiques.

**Vision.** VisionRT live et Qwen3-VL nocturne sont complémentaires. Le stage ultérieur
`visual_consolidation` ne fait pas un second appel VLM : il consolide par code. On garde
donc la passe lourde, mais on corrige `think=false`/JSON/statut, met en cache par hash
image+modèle+prompt et sélectionne les vrais changements avec manifeste. Mesure cinq
minutes : 11 images, 82,9 s à froid puis ~18,36 s/image à chaud; toutes les sorties du
run actuel sont invalides, donc le benchmark qualité reste ouvert.

**Économie.** La projection actuelle huit heures est ~159,4 h texte plus 5,4–23,5 h
vision. La cible architecturale estimée est 2–3 h texte + ~3,9 h vision pour une journée
continuellement événementielle, à prouver sur fixtures longues. DeepSeek Pro appliqué
au chemin actuel coûterait environ 68,24 EUR/jour texte seul; après refonte environ
1,78 EUR sans cache. Le cloud peut devenir un critique borné des cas incertains, pas un
substitut à une cardinalité incorrecte.

**Plan autoritaire.** `docs/PROD_BACKLOG.md` §E64-I. Mesures, hypothèses, tableau par
moteur, analyse qualité et tarifs : `docs/E64_H_COST_QUALITY_AUDIT.md`. Bugs nouveaux :
`tools/harness/BUGS_FOUND.md` OBS-34 à OBS-38.

## 2026-07-14 — E64-I2 : faits canoniques et cardinalité pilotée par l'orchestrateur

**Décision d'architecture.** Les modules métier restent propriétaires de leur mission,
schéma et writer. La cardinalité n'est plus corrigée fichier par fichier :
`night_orchestrator.prompt_projection` choisit une projection de stage unique avant les
fenêtres et sépare ensuite les responsabilités de sortie. Ajouter un moteur à I2 doit
donc étendre le registre central et la projection de faits, pas introduire un nouveau
résumé local divergent.

**Contrat de vérité.** Une sortie V13 n'est réutilisable qu'après validation de schéma et
round-trip canonique. Elle est conservée losslessly, puis exposée sous forme de faits
typés, capacités (`produced`, `valid_empty`, `not_applicable`) et liens vers les tours.
Une liste vide validée est une information; une capacité non exécutée n'en est pas une.
Le writer historique consomme la sortie canonique relue afin de préserver les tables et
consommateurs existants. Les embeddings vocaux, médias et IDs durables restent dans la
base; seuls les blobs sans valeur sémantique pour le stage ne sont pas recopiés au
prompt. Les références courtes sont réversibles et restaurées avant écriture.

**Réemploi borné.** Le V14 open-loops peut s'abstenir d'appeler le modèle uniquement si
un parent I1 complet et l'outcome tracker V13 prouvent un résultat vide valide. Identité
et interpersonnel conservent tous les tours et reçoivent seulement les faits pertinents;
les lignes historiques issues de la conversation courante sont exclues pour éviter une
boucle d'auto-confirmation. Le stage interpersonnel garde ses dix champs, répartis par
l'orchestrateur en deux responsabilités de sortie : aucun champ métier n'est supprimé.

**État de preuve à la pause.** Le pack V13 parent réel a couvert 7/7 responsabilités en
un appel (19 452 tokens, 22,656 s, missing=0). La projection centrale finale est testée
structurellement, avec 60 tests ciblés verts; les dernières mesures pré-compactage final
étaient 31 067→8 684 tokens pour identité et 37 578→11 186 pour interpersonnel. Le run
Qwen réel de ces stages et l'extension coordination/réconciliation/Life restent ouverts.
Le flag `MLOMEGA_E64_SHARED_FACTS` demeure donc désactivé par défaut.

## 2026-07-14 — E64-I mini-plan 1 : parent conversationnel + frontières séparées (ADR)

**Décision.** Une conversation continue n'est plus destinée à devenir une collection
d'épisodes concurrents. Le prototype opt-in produit un seul parent et des sous-thèmes
ordonnés. Les preuves ne sont pas résumées hors base : les 26 tours appartiennent chacun
à exactement un sous-thème durable, les citations primaires sont distinctes et le parent
porte leur union. Les observations capteur restent du contexte séparé.

**Pourquoi deux appels et non un.** Le premier essai réel en une requête était rapide
(1 appel, 12 472 tokens, 35,48 s), mais Qwen avait placé quatre questions substantielles
dans un sous-thème dont le résumé ne les couvrait pas. Retoucher un prompt fixture par
fixture aurait donné un faux gain. Le contrat retenu sépare : (1) bornes contiguës et
lossless uniquement; (2) détail sémantique sur ces bornes verrouillées. Le second modèle
ne peut plus déplacer les tours. Cette séparation reste dans le gate ≤2 appels.

**Mesure shadow.** Sur une copie de la minute autoritaire : 2 appels, 15 956 tokens
d'entrée estimés, 41,50 s, 1 parent + 6 sous-thèmes, 26/26 appartenances. Par rapport à
EpisodeBuilder actuel (4 appels, 20 210 tokens, 229,9 s, 10 épisodes) : −50 % appels,
−21,05 % entrée, −81,95 % temps (×5,54), −90 % parents. Six sous-thèmes au lieu des
quatre approximatifs restent une sur-fragmentation légère, pas une perte de preuve.

**Compatibilité et non-régression.** Le chemin est derrière
`MLOMEGA_E64_CONVERSATION_EPISODES=1`, défaut OFF. Les tables v19 stockent sous-thèmes,
appartenances et citations. Le bundle V13 contient ces sous-thèmes; l'applicabilité des
moteurs conditionnels utilise l'union de leurs types, afin que le conteneur
`episode_type=conversation` ne coupe pas internal/social/contradiction/choice/outcome.
La projection E64 commune conserve à nouveau l'état vision, les manifests count+digest
et la résolution offline du locuteur; les IDs opaques restent seulement en base.

**Limite et suite.** I1 n'est pas production-ready : fenêtres/checkpoints longs et
mesure réelle du pack V13 parent restent ouverts; la cible −50 % tokens n'est pas atteinte.
I2 est néanmoins autorisé car le multiplicateur faux 10 parents a disparu. Ne pas annoncer
un temps huit heures avant d'avoir mesuré les subdivisions du pack et supprimé les
ré-inférences V14/coordination/Life via le contrat de faits partagé.

## 2026-07-15 — E64-I2 : première occurrence Life compilée, promotion seulement sur répétition

**Séparer observation et trait.** Une ligne `action_outcomes`, un événement non verbal ou
une phrase ne devient pas immédiatement une préférence, un besoin ou un hook de William.
La première source exacte est persistée dans `brain2_life_model_watch_candidates` avec
son owner, sa table, sa PK, son épisode et son temps. Le replay de la même PK est
idempotent. Deux groupes épisode/source indépendants rendent le candidat
`promotion_ready`; eux seuls, un fait de soi explicite ou un pattern longitudinal
confirmé peuvent ouvrir le jugement sémantique Life.

**Le modèle ne choisit pas ses preuves.** Une opération doit citer au moins une nouvelle
preuve durable du delta courant. Les références sont résolues contre la table réelle et
le scope owner. Une création sans répétition suffisante est forcée
`very_recent/candidate/watch_only`, même si le modèle réclame 0,95 ou
`strong_live_hook`. La réponse entière est refusée si une opération recycle seulement un
ancien fait. Ainsi, le fait local « est-ce Maxime ? » peut rester une bonne observation
de contexte sans devenir une vérité longitudinale.

**Pourquoi ne pas reprompter Qwen.** Sur le clone réel, le payload Life a été réduit de
484 915 à 10 845 tokens en gardant les neuf couches et les manifests. Qwen 9B a pourtant
associé l'outcome test à un ancien fait et omis la nouvelle PK, y compris dans une fenêtre
unique. Le garde a bloqué toute écriture. Décision : ne pas ajouter des règles verbales
fixture par fixture; compiler les cas mécaniques et réserver les promotions ambiguës à
un modèle plus capable, local ou DeepSeek, sous le même validateur.

**Entrée commune et contexte.** Le registre journalier partagé et les lignes owner-scopées
sont projetés une fois. Les tours sans lien explicite restent durables mais ne sont pas
rejoués au Life updater. Les faits des autres personnes restent dans leurs modèles
Person/Relationship; seuls les éléments liés au même fait owner peuvent servir de
contexte causal. Le writer historique reste le contrat de compatibilité, et sa PK
`b2action_*` est désormais identique à celle du lifecycle.

**Checkpoint par révision durable.** `period_start/period_end` borne le run, mais la
consommation est désormais enregistrée par `(person_id, source_table, source_id, digest)`
dans `brain2_life_model_consumed_sources`, avec synthèse familiale dans
`brain2_life_model_checkpoints`. Le checkpoint n'avance qu'après writer réussi. Un replay
exact ne repaye rien; une modification tardive de la même PK change le digest et repasse.
V17 longitudinal, outcome resolution V19, store Life V19, prédictions, Self Schema et
`live_ready` restent des consommateurs déterministes; ils ne deviennent pas
artificiellement des appels LLM.

**Budget modèle cohérent et bloquant.** Un serveur llama.cpp à 24 576 et un orchestrateur
resté à 16 384 produisent des subdivisions inutiles et séparent le nouvel outcome de
l'état courant : cinq appels à 16 k contre un appel de 13 326 tokens rendus à 24 k.
`check_close_day_preflight.py` lit donc le `n_ctx` réel de `/props` et exige l'égalité
exacte avec `MLOMEGA_OLLAMA_CONTEXT_POSTSTOP`; serveur absent, valeur illisible ou
mismatch rendent le ready faux. La preuve réelle est verte à 24 576 des deux côtés. Ce
réglage ne remplace ni la projection ni les caps paginés à traiter en I3.

## 2026-07-15 — E64-I/R3 : équivalence par responsabilité, prudence séparée du contenu

**Le nom d'un consommateur n'est pas une preuve.** La matrice R3 couvre les 18 champs de
responsabilité des quatre contrats et suit les wrappers production V18 jusque dans leurs
délégués `old_*` qui exécutent réellement le SQL. Un champ doit avoir des faits sources,
une règle de preuve, un writer et au moins un consommateur réel. La formulation peut
changer; cette chaîne ne peut pas disparaître.

**Une conversation conserve son détail sans devenir un pattern sûr.** Le premier audit
shadow avait amélioré la provenance, mais persistait 0,85 pour un modèle relationnel et
0,90 pour une boucle concernant un locuteur encore inconnu. Décision : conserver le JSON,
les huit familles V14.6 et leurs refs, mais plafonner à 0,65 la confiance durable produite
par une seule conversation. La promotion au-delà appartient au longitudinal sur preuves
indépendantes, pas à Qwen au premier passage.

**Preuve.** Le vrai output shadow a été rejoué dans les writers : huit familles, max 0,65,
10/10 responsabilités et refs complètes. Les clones R2 donnent aussi 7/7 champs day,
13/13 bindings résolus, coordination ok, Life 21→0 au replay et aucune source consommée
manquante. 87 tests sont verts. Les flags restent OFF jusqu'à la pagination R4 et à la
mesure globale; R3 ne transforme pas une fixture minute en certification huit heures.

## 2026-07-15 — E64-I/R4 : une limite borne la page, jamais la vérité

**Décision de lecture.** Les caps coordination/Life ne sont pas augmentés : leur argument
`limit` devient `page_size`. Le lecteur commun parcourt par clé stable, digère chaque page
et ne déclare le stage complet qu'après égalité entre compte source et compte inclus. La
sortie transformée et l'état après page partagent le commit du marker. Après crash, une
page est relue puis réutilisée uniquement si son contenu est identique; une ligne révisée
invalide la page concernée. Les deux côtés du commit et une frontière d'événement sont
injectés en test.

**Décision mémoire/provenance.** La vision est triée par temps+PK et réduite en atomes à
l'intérieur de chaque page; deux atomes de même état aux bords sont fusionnés et leurs
transitions recalculées globalement. Les refs exactes restent attachées et la table raw
reste l'autorité. Life scanne tous les tours owner/date-scopés, mais n'accumule que ceux
cités par une preuve durable observed/internal/shared; les autres restent couverts par le
manifest et requêtables en DB. On réduit donc le working set, pas la couverture.

**État courant ≠ nouvelle preuve.** L'audit runtime a découvert que l'installateur V18
lisait un `CANONICAL_TABLES` absent du module canonique V15.10 : les neuf couches étaient
silencieusement vides. Le mapping explicite est désormais dans V18 et le clone relit
`9/4/9/22/12/9/10/9/8` lignes. Ces lignes alimentent l'index d'état courant mais sont
retirées du delta; elles ne peuvent pas se citer elles-mêmes pour une promotion. Le digest
de reprise couvre leur contenu complet plutôt que les seuls compteurs.

**Preuves et limite du verdict.** 201 observations passent en cinq pages et un atome,
161 prédictions deviennent 161 bindings, 121 signaux Life et 121 routines passent en
quatre pages. Le clone réel donne 199/199 observations, quatre pages, un atome et 26
manifests Life complets. **93 tests** R1–R4 sont verts. Cela clôt R4/I3, pas I7 : flags OFF,
temps 1 h/8 h non annoncé avant le harnais vidéo cinq minutes et la relecture dashboard.

## 2026-07-15 — E64-I : activation contrôlée, frontière live différée et politiques d'entrée fermées

**Activation.** Les flags `MLOMEGA_E64_CONVERSATION_EPISODES` et
`MLOMEGA_E64_SHARED_FACTS` passent ON par défaut après traversée d'un vrai CloseDay
(`run_v18_3e3194ad94f044afa2443ba11ff81520`, dix stages et manifeste complet). La valeur
explicite `0` reste le rollback. Cette décision remplace les mentions historiques « flags
OFF » ci-dessus; elle ne transforme pas la preuve en validation Deep Vision, owner voice
ou téléphone réel.

**Une politique avant toute fenêtre.** Le registre `prompt_projection` est désormais
fail-closed pour les stages produit V13/V14/V18/Life/Brain2/coordination/silent. Chaque
stage déclare `conversation`, `daily` ou `specialized`; un nouveau nom produit sans
politique lève avant le LLM. Le but est d'empêcher définitivement le retour d'un moteur
isolé qui repasse tours et sorties brutes puis laisse le fenêtrage multiplier l'erreur.
La donnée source reste en DB/manifeste; seule sa projection de travail est centralisée.

**Frontière live.** Le hot path persiste immédiatement le tour et les artefacts nécessaires
à BrainLive, mais ne lance plus plusieurs analyses sémantiques lourdes séquentielles par
segment. Ces travaux entrent dans `live_fine_intel_queue_v19`, avec batch borné, statut,
tentatives et validation exacte des `turn_id`. La fermeture suit : drain audio/finals →
flush live → traitement/reprise du backlog sémantique → CloseDay. Une erreur n'est ni
avalée ni changée en succès; recovery repart de la file durable.

**Correctifs issus du run.** Pattern Mirror conversation-local est une projection
déterministe/0 appel; le raisonnement de pattern reste au cycle longitudinal. Le writer
proactif normalise les objets JSON avant SQLite TEXT. `compiled_watch_only` et
`compiled_no_life_delta` sont des fins Life valides et observables.

## 2026-07-15 — I0.5 : FirstTry hermétique, preuve d'usage et zéro téléchargement tardif

**Décision de frontière processus.** Un contrôle exécuté dans un enfant ne modifie pas
le PATH de son parent. `RUN_MLOMEGA_V19.ps1` prépare donc proxy et répertoires DLL avant
tout spawn; `runtime_environment_v19.py` refait la même opération dans SessionHub,
recovery et le worker manuel. Les handles `add_dll_directory` restent vivants et
`cudnn_ops_infer64_8.dll` est chargée par `WinDLL`. L'existence du fichier seule n'est
plus une preuve.

**Gate bloquant avant capture.** La readiness prouve le compte HF via `whoami`, l'accès
aux fichiers gated de diarization/segmentation, la présence locale des configs ET poids,
le cache ASR nocturne complet, Python 3.11/.venv, Transformers 4.52–4.x, torch CUDA par
un vrai calcul, Qdrant, espace disque, DB/media, backend+alias+contexte, et exécute une
requête JSON stricte sur le LLM sélectionné ainsi qu'une image+JSON sur chaque VLM
configuré. Un proxy explicite non joignable bloque; seul le black-hole loopback:9 connu
est supprimé. Un llama-server actif alors qu'Ollama est sélectionné bloque pour éviter
le conflit VRAM. Le préflight ne télécharge jamais.

**Provisionnement séparé.** `PREFETCH_FIRSTTRY_MODELS.py` est l'unique action explicite
guidée pour les téléchargements gated/cache. Sur la machine, l'ancien cache Pyannote
semblait présent mais les snapshots diarization/segmentation ne contenaient que README.
Le nouveau contrôle l'a refusé; après préchargement, compte `BALLSoHigh712`, accès 3/3,
Pyannote 3/3 et `faster-whisper-large-v3` sont prouvés. Le dernier rapport échoue encore
volontairement sur l'état externe : Ollama arrêté, serveur P1:24k orphelin sur 8080 et
VLM donc indisponibles. On corrige/configure ces services puis on relance; on ne baisse
pas le gate pour obtenir un faux vert.

**Rectification de statut.** I0.3 est clos : absence sans outcome ignorée, contradiction
sur outcome négatif explicite seulement, Life watch puis deux groupes indépendants. I2
est clos avec R2/R3/R4 et le registre fail-closed. I0.2 et I0.4 ne sont pas clos : le
transport de la confiance et le recensement des capacités existent, mais ni le plafond
transversal par qualité source ni le veto final sur capacité dégradée ne sont encore
généralisés. I1 n'est pas entièrement clos non plus : une conversation hors budget lève
encore au lieu d'être fenêtrée. Ces trois incréments précèdent I4; aucun rerun R1–R4.

## 2026-07-15 — Lot prérequis I0.2 / I0.4 / I1.3 (ADR — ferme la ligne de reprise avant I4)

**I0.2 — plafond de confiance par qualité des preuves (OBS-29).** Nouveau module central
`evidence_quality_v19.py` : chaque preuve citée porte confiance ASR, alignement
(mots WhisperX), diarisation, résolution de locuteur (avec `source_id` d'indépendance)
et langue. `brain2_shared_facts_v19.py` calcule le `confidence_ceiling` d'un fait depuis
ses PREUVES CITÉES, plus depuis la sortie du modèle. Règles : une conclusion ne dépasse
pas sa meilleure preuve ; seule une corroboration de sources INDÉPENDANTES (segments/
bundles distincts, pas le même tour recopié) relève le plafond ; voix non enrôlée →
`owner_attribution_blocked` (jamais attribuée à William) ; fragment linguistique
incohérent → `evidence_status=quarantined` avec cause, raw durable. Statuts additifs
(aucun consommateur ne branche sur les valeurs exactes). Tests 7 + 32 non-régression.

**I0.4 — gate du manifeste de capacités (OBS-38).** `night_orchestrator/capability_manifest.py`
(additif) + branchement chirurgical dans `v18_close_day.py` après `semantic_warnings`,
AVANT le manifeste de sortie et `assert_cleanup_eligible`. 13 capacités obligatoires
recensées depuis les stages réels (deep_audio, deep_vision relu dans
`brainlive_deep_vision_runs_v161`, event_assembly, brain2_v13_v14, visual_consolidation,
longitudinal, coordination, life_model, outcome_resolution, life_model_v19,
prediction_emission, self_schema, live_ready). Verdicts passants
`product_validated|valid_empty|not_applicable` (les deux derniers exigent une
applicabilité prouvée) ; bloquants `degraded|abstained|bypassed|failed` → `StageGateError`
non-retryable AVANT `completed`/cleanup, run `blocked` avec cause lisible. Deep Vision
sélectionné>0 & analysé=0 → `failed` (le faux-vert type). `compiled_watch_only`/
`compiled_no_life_delta` = succès Life. Persistance `v18_close_day_capability_manifests`
(UNIQUE(run_id), upsert) + copie dans `result_json`. Rollback d'urgence
`MLOMEGA_E64_CAPABILITY_GATE=0`. Tests 10 + 10 non-régression.

**I1.3 — conversations longues fenêtrées.** `build_conversation_episode_v6` ne lève plus
`input_budget_exceeded` : quand une passe dépasse le budget, elle passe par
`run_windows`/checkpoints E64 (`night_llm_windows_v19`). Segmentation : fenêtres
token-aware sur tours ordonnés (overlap lecture seule), chaque fenêtre n'émet des
frontières QUE pour ses tours primaires, la dernière fin est ancrée au dernier primaire,
puis assemblage PAR CODE en partition globale contiguë sans trou (tri par provenance des
tours, pas par window_index — la subdivision récursive remappe les index). Détail : lots
de segments ENTIERS (un segment n'est jamais coupé), parent unique ancré au lot d'ordinal
minimal. Reprise : zéro nouvel appel sur relance. Aucun fallback v5 silencieux
(`segmentation_windows_incomplete`/`detail_windows_incomplete` explicites et retryables).
Cas court : chemin historique octet pour octet (2 appels, mêmes prompts). Garde-fou :
fenêtrage seulement si `person_id`+`package_date` fournis (scope checkpoints) — l'appelant
`brain2_strict_v13_2.py` les passe désormais. Tests 7 + 11 non-régression.

**Hors périmètre noté.** `test_e64_night_orchestrator.py::test_estimate_tokens_rounds_up_and_honours_tokenizer`
est stale (attend l'ancien ratio 3.5 ; `_DEFAULT_CHARS_PER_TOKEN=2.5` volontaire) —
échec pré-existant, pas une régression du lot. Reprise produit : validation courte
(backend persisté + readiness + tests par venv), puis I4.1.

## 2026-07-16 — Lot I1.5/I1.6 : frontière thématique par provenance et gate réel produit (ADR)

**I1.5 — coupure thématique artificielle prouvée puis corrigée.** Le fenêtrage I1.3
forçait la dernière fin de chaque fenêtre au dernier tour primaire : un thème traversant
la frontière de deux fenêtres était systématiquement coupé en deux sous-thèmes (test
rouge : 13 segments au lieu des 10 thèmes réels, fragments aux trois bords de fenêtre).
Correction PAR PROVENANCE, sans toucher prompt ni schéma : `normalize_window_segmentation`
distingue une fin forcée par le bord (`window_boundary_forced`, raison de continuation)
d'une vraie frontière sémantique ; `_fuse_forced_window_edges` fusionne au réassemblage
un segment à fin forcée avec le segment de continuation qui ouvre la fenêtre suivante.
Jamais de similarité de texte. Une vraie frontière tombant sur un bord reste une
frontière ; le mécanisme couvre aussi les bords de sous-division récursive ; le
sous-thème fusionné porte l'union des tours, bornes réelles, un seul ordinal ; reprise
0 appel. 20 tests verts.

**I1.6 — gate re-cadré par Codex : la minute en conditions produit NORMALES.** Le cas
fenêtré forcé appartient à I1.5 (FakeLLM) ; I1.6 mesure le chemin normal avec le vrai
9B. Run réel (llama.cpp P1/24k, thinking off, clone d'audit, hors CloseDay) :
**2 appels, 15 772 tokens d'entrée, 32,6 s, 1 parent + 4 sous-thèmes, Karim/Netflix
séparés, couverture 26/26 exactement une fois, zéro FK inventée, aucune erreur
budget/length.** Contre baseline (4 appels, 20 210 tokens, 229,9 s, 10 épisodes
défectueux) : appels ×2, temps −86 %, qualité supérieure (4 sous-thèmes ≈ référence
humaine ; le shadow en donnait 6). Restant honnête : la cible « entrée ≤50 % » n'est
pas atteinte (78 %) — même niveau que le shadow ; c'est la projection d'entrée, à
retravailler via les mesures I2/I7, pas via ce gate.

**Découverte opérationnelle (bloquait tout run réel).** Sur ce build llama-server,
`--reasoning-budget 0` seul ne désactive PAS le thinking de Qwen3.5 : chaque appel JSON
partait en 4096 tokens de raisonnement caché et finissait `length` (prouvé sur une
requête triviale : `reasoning_content` rempli, `content` vide). Il faut AUSSI
`--chat-template-kwargs {"enable_thinking":false}`. Commande canonique + probe de
vérification dans EXECUTOR_BUILD_GUIDE. Conséquence pour I4/I7 : tout benchmark fait
avec un serveur mal lancé est invalide par construction — vérifier le probe avant de
mesurer.

## 2026-07-16 — I4.1 : sélection Deep Vision avec couverture (ADR)

**Cause racine du faux « 1 sélectionnée / 0 analysée ».** La sélection réelle vivait dans
`brainlive_offline_deep_vision_v16_1.select_keyframes_for_bundle` (appelée par l'override
`v18_poststop_outputs.install_deep`) : un QUOTA d'échantillonnage régulier
(`max_keyframes=12`, indices espacés) qui droppait silencieusement les autres frames sans
aucune couverture — sur la session 5 min réelle, 472 frames sur 473 disparaissaient avant
même le VLM.

**Politique centrale.** `night_orchestrator/deep_vision_selection.py` : keyframe sur
changement réel d'état (nouvel `VisionChangeAtom` du réducteur testé — jamais le jitter
de confiance), OCR (`visible_text`), demande utilisateur réelle (marqueur per-frame ou
focus lu dans `brainlive_sensor_events`/`brainlive_raw_timeline_v1514`), et intervalle
de sécurité `MLOMEGA_DEEP_VISION_SAFETY_INTERVAL_S` (défaut 60 s). Le cap historique
n'existe plus comme troncature ; un plafond pathologique optionnel (OFF par défaut)
rétrograde l'excédent en frames représentées, sans perte.

**Couverture prouvée.** Table additive `deep_vision_frame_coverage_v19`
(`person/date/bundle/frame` PK, idempotente au rerun) : chaque frame non sélectionnée
pointe sa keyframe/atome représentatif ; `coverage_manifest()` exige 100 %
(sélectionnée | représentée), zéro orpheline. Mesure sur clones scratch : 5 min =
473→121 keyframes + 352 représentées (473/473) ; minute statique = 1 keyframe (200/200).
Writers `brainlive_deep_vision_runs_v161` et gate de capacités I0.4 inchangés.

**Décision reportée à I4.2 (pas une réduction arbitraire).** Les 120 atomes incluent le
churn de track-ids ; en label-set track-agnostique la session vaut ~78 changements.
Le choix (politique label-set ou regroupement de micro-transitions) sera tranché avec la
vraie passe VLM et ses mesures, jamais pour « faire baisser le compteur » sans preuve.

## 2026-07-16 — I4.4 final : sélection sémantique = pixels lisibles = analyses (ADR)

**Faux GO découvert après le gate réel.** Les 20 images du gate avaient été préparées
manuellement depuis la vidéo. En produit, la sélection nocturne parcourt toute la timeline,
alors que le writer live VisionRT ne conserve que ses propres keyframes clairsemées.
L'ancien raccord persistait bien toutes les sélections dans
`deep_vision_frame_coverage_v19`, puis supprimait silencieusement celles dont le JPEG
n'existait pas. Une journée pouvait ainsi déclarer `1 sélectionnée/1 analysée` alors que
la couverture en demandait 20.

**Décision de preuve.** Une keyframe sémantique sélectionnée doit avoir des pixels. Si le
JPEG live manque, le post-stop retrouve le clip E55 indexé de la même session dont la
fenêtre couvre `frame_time`, extrait cette image par ffmpeg dans le media root géré, puis
l'enregistre dans `raw_assets` et `deep_vision_keyframe_materializations_v19`. Le fait
brut `vision_frames` reste immuable; la reprise réhydrate le chemin dérivé par cette table.
La provenance conserve clip id/URI/SHA,
fenêtre, offset demandé/effectif et éventuel clamp temporel. Nom stable, extraction et
upserts idempotents. L'absence de clip/ffmpeg ou toute extraction/écriture défectueuse
bloque le bundle avant VLM; aucune réduction implicite du nombre sélectionné.

**Triple gate durable.** `brainlive_deep_vision_runs_v161` porte désormais
`selected_keyframes`, `readable_keyframes`, `analyzed_keyframes`. I0.4 n'accorde
`product_validated` que si les trois sont égaux. Une ancienne table/run sans preuve
`readable` ne peut pas être considérée produit. Validation ciblée avec un vrai MP4 E55 :
deux sélections, un JPEG live et un manquant → extraction automatique et `2=2=2`; sans
clip → `blocked`, `2/1/0`. La preuve VLM réelle 20/20 d'I4.4 reste valable pour la qualité;
ce lot ferme son dernier raccord produit sans repayer le réseau VLM.

## 2026-07-16 — E64-I0.6/I6 : spatial durable branché, proactivité déclenchée et appels explicables

**Spatial.** Une requête « où est X ? » ne dépend plus de la seule frame courante. Le
chemin connecté relit d'abord le registre durable owner-scopé de WorldBrain, préfère une
entité visible de la session active, puis la dernière observation inter-session. La
réponse expose état, fraîcheur, confiance et provenance; l'absence reste inconnue et ne
fabrique ni position ni flèche. Les observations historiques ne sont pas écrasées : le
registre porte le dernier état, `visual_events_v19` conserve la trajectoire. En mode
Reflex seul, le transcript ASR final déclenche le skill local; en mode connecté il ne
duplique pas le routage PC.

**Cadences.** Les 2 secondes concernent uniquement la reconstruction mémoire et
l'évaluation proactive périodique. Elles ne remplacent pas le flux VisionRT/UI par frame :
outlines, couleurs, flèches, gestes, sous-titres et focus explicite restent événementiels.
Le `BrainLiveSceneAdapter`, auparavant construit mais jamais évalué en PhoneOnly, est
maintenant appelé. L'apparence d'une personne durablement nommée est décrite une fois par
track/session; un vrai changement inter-session alimente AttributeMemory puis la file H1.
Aucun changement n'est inventé à partir d'une absence.

**Conditionnement nocturne et observabilité.** Le 9B d'identité ne tourne que si la
résolution est absente, ambiguë ou contradictoire. Les calculs exactement mappables
restent déterministes. L'exécuteur nocturne persiste désormais une ligne par tentative
et par cache hit dans `night_llm_call_telemetry_v19`, avec raison, faits lus/produits,
modèle, tokens fournisseur, latence et verdict. Cette table est la source du compteur
I7; un appel produit nocturne non représenté lors du Gate B sera un échec de mesure, pas
un succès silencieux.

## 2026-07-16 — I7 Gate B : une commande n'est réussie que si son effet est prouvé (ADR)

**Décision de preuve.** `intents_routed` n'est plus une preuve fonctionnelle. Chaque
transcript device final marqué commande produit un `command_execution_trace` corrélé au
`segment_id`, contenant intent, request, commande Android et effet compact. Le harnais
conserve ces traces et les downlinks significatifs. Le gate porte sur les treize phrases
exactes du scénario, pas sur des alias de test plus faciles.

**Raccords découverts.** (1) `GpuArbiter` comparait la VRAM totale déjà utilisée au petit
budget d'un job OCR : dès qu'un modèle occupait plus de 768 Mio, l'OCR était toujours
refusé. L'admission compare maintenant `used + coût_job` au plafond GPU. (2) La carte
spatiale calculait bien `active_zone`, mais WorldBrain ne la recopiait jamais :
ChangeAttention n'avait donc aucune zone. (3) le watcher d'enrôlement interprétait
« retiens demain… » et « retiens rendez-vous… » comme des prénoms; la forme courte
`retiens <nom>` exige désormais l'utterance entière, les faits généraux vont à BrainLive.
(4) le flag `translate` était ignoré par VisionRT. La traduction visuelle est désormais
OCR sur le PC puis texte vers le modèle offline Android par `translate_text`; le PC ne
duplique pas le moteur de traduction du téléphone.

**OCR honnête.** RapidOCR garde le chemin rapide. Seulement s'il ne lit rien, une demande
explicite utilise `qwen3-vl:4b` avec JSON contraint, `think=false` et lecture du canal
`thinking` propre à ce build Ollama. La sortie VLM est `probable` à 0,5, jamais une lecture
`observed`. La vraie frame difficile du scénario a produit du texte en 7,05 s; ce n'est
pas présenté comme la latence normale d'un crop net ni comme une transcription parfaite.

**CloseDay et manifeste.** Le capability manifest vérifie le run Deep Vision référencé
par le post-stop courant, pas la somme de toutes les tentatives historiques de la journée.
Le run autoritaire 16/16/16 rend le CloseDay complet même si une tentative antérieure
avait été bloquée 16/9/0. Les tentatives restent en base pour audit.

**Portée du GO.** Les fonctions PC et le contrat Unity sont clos (147 tests PC, Unity
10/10, CloseDay complet). L'exécution réelle du traducteur Kotlin, les receipts et la
latence/rendu restent un gate S25. Le run de travail avec retries n'autorise aucune
projection de débit : I7 Gate B global attend encore un passage one-shot propre pour le
seuil ×5.

## 2026-07-18 — Gate B one-shot : frontières GPU prouvées et interactions live non bloquantes (ADR)

**Un préflight lourd ne doit pas être rejoué par `/health`.** Le préflight profond prouve
séquentiellement P1 puis l'arrête, chauffe le vrai 4B live, vérifie qu'il est le seul
résident Ollama et écrit un receipt atomique fingerprinté (backend, URLs/alias, contextes,
modèles live/VLM, orchestration, personne). SessionHub valide ce receipt sans recharger
les modèles GPU à chaque health poll; en production orchestrée, un receipt absent/périmé
ou incohérent bloque le pairing. `RUN_MLOMEGA_V19.ps1 -LivePhone` impose donc
`MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING=1`. Le rollback explicite reste disponible pour le
développement non produit.

**La VRAM est une frontière de processus, pas un `empty_cache` optimiste.** Deep Audio
WhisperX/Pyannote/identité tourne par défaut dans `deep_audio_subprocess.py`; la sortie de
ce processus libère réellement CUDA avant Deep Vision/P1. Les caches ECAPA, PyTorch et
objets pipeline sont relâchés aux frontières. `enter_text` évince Ollama puis exige au
moins 6000 MiB libres avant P1 (`MLOMEGA_P1_MIN_FREE_VRAM_MB`, rollback configurable) :
un 9B partiellement offloadé n'est plus accepté comme un succès. Le VLM live utilise
`keep_alive=0`; le post-stop reste séquentiel Deep Audio → Deep Vision → texte.

**Aucune sémantique fine ne doit bloquer le worker audio.** Le deferred fine-intel
persiste les entrées, extrait par batch, répare uniquement un identifiant opaque quand le
mapping est univoque, journalise les rejets de contrat et échoue autrement. Le compilateur
autonome V18 transforme les sorties strictement mappables par code; le passage
interpersonnel partage une projection et merge des responsabilités disjointes au lieu de
repayer le même contexte. Ces choix expliquent le one-shot : 20 appels / 147 072 tokens
entrée / 841 s, contre 169 / 1,119 M / 83 min sur la baseline (comparaison de cardinalité,
pas encore une extrapolation huit heures).

**Une commande live ne peut retenir le canal ordonné.** Les ordres explicites capteur,
OCR, traduction et mémoire ont une grammaire haute confiance; le langage indirect reste
LLM-first. Le mode Aide renvoie immédiatement `planning`, calcule en worker, conserve les
contrôles arrivés entre-temps et est attendu avant changement de phase GPU. Une fermeture
de dernière étape incrémente le compteur d'avancement avant `done`.

**Brain2 live garde la profondeur, mais pas les planners redondants.** Pour la seule forme
non ambiguë `qui est X / who is X`, la route relation/raw/vector est déterministe. Toutes
les preuves restent persistées; le prompt reçoit huit preuves pertinentes/adjacentes avec
provenance et un contrat spécialisé faits/inférences/preuves/manque, puis un unique appel
4B synthétise. Les autres questions continuent le routeur Brain2 complet. Mesure réelle :
80 candidats/363 193 caractères et 83–87 s auparavant; réponse Brain2 grounded en 7,95 s
à chaud après correction. Ce n'est ni un fallback retrieval-only ni une suppression des
couches mémoire.

**Portée du verdict.** `gateb-clean-20260718-141124` est le premier one-shot harnais
entièrement vert : live sans drop, médias durables, CloseDay/recovery/manifests complets,
Deep Vision 7=7=7 et gain chaîne >×5. Les correctifs Aide/Mémoire ont été prouvés ensuite
en réel et par 109 tests courts. Un dernier one-shot sur le HEAD exact reste exigé pour
regrouper les treize effets corrigés et la nuit dans le même rapport; ensuite Dashboard,
Gate qualité William, Gate C synthétique, S25 puis Gate D.
