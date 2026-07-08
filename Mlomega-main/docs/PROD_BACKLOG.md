# PROD_BACKLOG â€” MLOmega V19, complÃ©tion produit (E31â†’E36)

Issu de l'audit d'alignement visionâ†”livrÃ© du 2026-07-04. Principe directeur : **brancher l'existant avant de construire du neuf** â€” le cÅ“ur V18.8 contient dÃ©jÃ  la rÃ©activitÃ© conversationnelle (hot capsule, relation packs, open loops, interventions proactives H1), les modÃ¨les relationnels et la correction mÃ©moire ; plusieurs Â« gaps Â» sont des tuyaux manquants, pas des capacitÃ©s manquantes. MÃªme discipline que E1â†’E29 : une Ã©tape = une branche = une PR, push au fil de l'eau, tests rÃ©els exÃ©cutÃ©s ici quand c'est du PC, ADR dans DECISIONS.md.

## E39 - Invariant V18 `turns` (FAIT - 2026-07-06)

- [x] Supprimer toute dependance declaree a `turns.created_at` et `turns.absolute_start`.
- [x] Utiliser uniquement `turns.start_s`, present dans le schema reel.
- [x] Ajouter un test source/schema de non-regression.
- [x] Garder le changement post-stop preexistant separe du lot PhoneOnly.

## E40 - Identifiant BrainLive unique (FAIT - 2026-07-06)

- [x] Separer l'identifiant transport de l'identifiant BrainLive.
- [x] Construire ConversationBridge avant les writers WorldBrain.
- [x] Aligner WorldBrain, SceneAdapter, keyframes, audio, replay et briefing.
- [x] Refuser une divergence d'identifiants au demarrage.
- [x] Valider les writers durables par test d'integration.

## E41 - Barriere de fin live (FAIT PC - 2026-07-06)

- [x] Geler les nouveaux medias et fermer les peers avant le drain.
- [x] Attendre la queue et le callback audio en vol.
- [x] Flusher le dernier segment VAD par le chemin final normal.
- [x] Archiver le VAD meme sans transcript ASR.
- [x] Propager les erreurs de fermeture en mode strict.
- [x] Fermer ingress/video et liberer les modeles/caches live avant CloseDay.
- [ ] Valider l'ordre avec le microphone Android reel (E46).

## E42 - PCM Opus et DataChannel thread-safe (FAIT PC - 2026-07-06)

- [x] Gerer PyAV packed et planar a partir du format/layout reels.
- [x] Downmixer `s16/stereo` packed vers mono sans changer l'echelle.
- [x] Conserver une queue audio bornee avec comptage des drops.
- [x] Marshaler les UIIntent du worker audio vers l'event loop aiortc.
- [x] Tester avec une vraie `av.AudioFrame` et verifier le thread DataChannel.

## E43 - Job CloseDay authentifie et reprise-safe (FAIT PC - 2026-07-06)

- [x] Separer fin live et execution CloseDay.
- [x] Ajouter `/session/status` et `/session/close-day`, authentifies.
- [x] Rendre end/retry idempotents et limiter a un task par session.
- [x] Executer le worker CloseDay avec `.venv`, pas `.venv-live`.
- [x] Charger `.env` et transmettre le vrai `PersonId` au runtime.
- [x] Conserver la reprise durable native des stages V18.
- [x] Refuser une seconde session transport dans le meme processus operateur.
- [ ] Rejouer un CloseDay complet non mocke en E46.

## E44 - Android PhoneOnly transport (SOURCE FAITE - 2026-07-06)

- [x] Envoyer FrameEnvelope sur le DataChannel avant la frame.
- [x] Ajouter un fallback CPU I420 reel ; ne pas pretendre au zero-copy EGL.
- [x] Attendre ICE gathering sans trickle ICE.
- [x] Teardown avant reconnect et dispose synchrone.
- [x] Propager token et endpoint renouveles vers Kotlin.
- [x] Re-resoudre LAN/tunnel apres perte du PC.
- [x] Autoriser explicitement le HTTP LAN du profil local.
- [x] Ajouter build/test/export AAR et dependances Unity.
- [x] Rendre XREAL optionnel pour ouvrir/build PhoneOnly.
- [ ] Compiler Gradle et valider sur Android en E46.

## E45 - Scene PhoneOnly separee (FAIT SOURCE - 2026-07-06)

- [x] Retirer tout forçage PhoneOnly du builder G1 XREAL.
- [x] Creer un builder `PhoneOnly.unity` distinct.
- [x] Creer un asset config PhoneOnly distinct et editable.
- [x] Brancher permissions, capture, pairing, transport et fin explicite.
- [x] Tester statiquement la separation G1/PhoneOnly.
- [ ] Ouvrir et compiler les deux scenes dans Unity en E46.

## E46 - Validation/compilation finale (PC AVANCE, ANDROID A FAIRE - 2026-07-06)

- [x] Suite V18 complete : 110 passed.
- [x] Suite V19 deterministe large : 190 passed, 1 skipped, 1 deselected lourd.
- [x] Corriger les dependances API manquantes dans installateur/live venv.
- [x] Installer CUDA 12/cuBLAS/cuDNN dans `.venv-live` et valider AudioRT GPU.
- [x] Conserver le fallback AudioRT CPU comme securite, pas comme chemin nominal.
- [x] Mesurer les WAV (4,525 s/4,890 s) et le vrai faster-whisper GPU (0,34 s inference).
- [x] Mettre Ollama a jour et installer Qwen3.5 4B live + 9B deep.
- [x] Valider le contrat Ollama reel sous 12 s et separer tests deterministes/integration.
- [x] Garder le modele resident par phase et le liberer une seule fois a la frontiere deep.
- [x] Executer un CloseDay reel et conserver son verdict `blocked`.
- [x] Reprendre le meme run durable avec `--force`, sans duplication.
- [x] Corriger `life_model_blocked`, puis obtenir CloseDay `completed` et cleanup eligible.
- [ ] Implementer/valider la traduction live Android ; `translation_hot` ne traduit rien actuellement.
- [x] Verifier le failover offer : URL active LAN/Tailscale deja branchee dans le checkout.
- [x] Separer `/live` liveness et `/health` readiness PhoneOnly avec 503 indisponible.
- [x] Ajouter TTL/rotation/purge token et grace renew-only pour reprendre le meme session_id.
- [ ] Terminer l'audit transversal Brain/nightly/config/routes/legacy avant compilation.
- [ ] Installer JDK 17, Gradle 8.7, Android SDK/adb et Unity 6000.0.23f1.
- [ ] Construire/tester/exporter les AAR Kotlin.
- [ ] Ouvrir les scenes, lancer les tests Unity et construire l'APK.
- [ ] Executer Android -> PC reel, puis Terminer -> CloseDay completed.

## E31 â€” Conversation live â†’ BrainLive V18.8 (LE branchement prioritaire)

**Constat** : audiort produit les transcripts (sous-titres) mais la boucle BrainLive du cÅ“ur ne les reÃ§oit pas â€” le moteur d'interventions conversationnelles existe (v18_8_live_policy, hotloop, turn buffer) et n'entend pas la conversation V19.
**Faire** : injecter les segments finaux d'audiort dans le chemin d'entrÃ©e live du cÅ“ur (turn buffer / live session â€” lire `brainlive_realtime_v15_2`/`brainlive_hotloop_v15_6`/`v18_8_live_policy.plan_live_dispatch` pour le point d'entrÃ©e exact ; ADR) avec `live_session_id` V19 partagÃ© ; laisser le debounce/policy existant produire les candidats H1 â†’ queue â†’ delivery_adapter â†’ lunettes. RÃ©sultat attendu : parler d'un sujet Y avec X dÃ©clenche rappels/suggestions issus de la mÃ©moire â€” la capacitÃ© V18.8, dans le monde XR.
**Test** : transcript simulÃ© mentionnant un sujet prÃ©sent dans la mÃ©moire de test â†’ intervention en queue avec evidence â†’ viewer.

## E32 â€” IdentitÃ© multi-indice (visage + voix + enrollment)

**Constat** : aucune reco faciale ; voice_identity existe mais nocturne seulement ; Â« personne connue Â» n'existe donc pas en live â†’ scÃ©narios 2/3 bloquÃ©s.
**Faire** : embeddings faciaux locaux ONNX (ArcFace/InsightFace-like, licence vÃ©rifiÃ©e, MODEL_MANIFEST) sur crops person de VisionRT ; brancher `voice_identity`/`voice_embeddings` du cÅ“ur au flux audiort ; **enrollment vocal** (Â« retiens : c'est Sarah Â» â†’ capture visage+voix â†’ entitÃ© nommÃ©e + graine de relation pack) ; fusion multi-indice (visage+voix+contexte) avec seuil Â§17.2 (pas de nom sous confiance) ; correction vocale (Â« non, ce n'est pas Paul Â» â†’ `memory_correction` existant).
**Test** : enrollment simulÃ© â†’ re-reconnaissance sur nouvelle frame/voix â†’ PersonTag nommÃ© + ContextCard relation pack.

## E33 â€” IntentRouter vocal, actions device, mode payant

**Constat** : aprÃ¨s wake word, seuls des cas codÃ©s (oÃ¹-est/what_is/ocr) ; pas de multi-tour ; pas de lancement d'apps ; `llm: openai/gemini` = config sans client.
**Faire** : routeur d'intentions gÃ©nÃ©ral (grammaire locale rapide + repli parsing LLM live lÃ©ger pour le reste), **multi-tour** (contexte de la derniÃ¨re commande/rÃ©ponse/cible : Â« et Ã§a ? Â», Â« zoom dessus Â», Â« traduis-le Â») ; actions Android (Intents : Maps navigation, YouTube, app arbitraire, volume/luminositÃ© lunettes via one-xr si utile) ; **toggles UI Ã  la voix** (Â« cache tout Â», Â« mode Free Guy Â», Â« pause privÃ©e Â») branchÃ©s au broker/density + cÃ¢bler le geste balayage Kotlinâ†’Unity dÃ©jÃ  Ã©mis ; **mode payant** : clients OpenAI/Gemini/Anthropic derriÃ¨re `LLMProvider`/`VisionModelProvider` (bascule vocale Â« mode payant Â» / retour local, indicateur StatusBar cloud actif, estimation de coÃ»t par requÃªte affichÃ©e, politique de donnÃ©es du profil respectÃ©e).
**Test** : chaÃ®ne voix simulÃ©e â†’ intent routÃ© â†’ action/toggle ; bascule cloud opt-in mockÃ©e + rÃ©elle si clÃ© fournie.
**Ajout inventaire cÅ“ur (2026-07-04)** : intent Â« interroge ma mÃ©moire Â» â†’ brancher le routeur Brain2 riche (`brain2_router_v14_2.ask_brain2`, aujourd'hui CLI-only) plutÃ´t que le `/query` simple d'api.py â€” poser une question Ã  sa mÃ©moire depuis les lunettes.

## E34 â€” ProactivitÃ© rÃ©elle & hot context device

**Constat** : les prÃ©dictions nocturnes ne sont pas injectÃ©es dans le live ; `entities_hot` du tÃ©lÃ©phone ne reÃ§oit que la vision ; 3 situations proactives seulement.
**Faire** : charger les prÃ©dictions/attentions du jour (life model store + outcomes) dans le HotSceneContext du scene_adapter â†’ suggestions proactives contextuelles (Â« tu voulais racheter X Â», routine dÃ©viÃ©e, promesse due) ; **prefetch des relation packs** vers le SceneCache device Ã  la reconnaissance d'une personne (latence zÃ©ro pour la ContextCard) ; **briefing du matin** (premiÃ¨re session du jour â†’ carte rÃ©sumÃ© : agenda dÃ©duit, prÃ©dictions, choses Ã  ne pas oublier).
**Test** : prÃ©diction du jour en base â†’ scÃ¨ne correspondante simulÃ©e â†’ suggestion proactive en queue ; briefing gÃ©nÃ©rÃ© Ã  l'ouverture de session.
**Ajouts inventaire cÅ“ur (2026-07-04) â€” moteurs nocturnes Ã  consommer EN LIVE (P1)** : (a) `proactive_interventions_v14_7` â€” gÃ©nÃ©rÃ© la nuit seulement aujourd'hui, Ã  consulter/dÃ©clencher en session ; (b) `v18_predictive_retrieval` â€” la rÃ©cupÃ©ration prÃ©dictive dense doit enrichir le contexte live, pas seulement la calibration nocturne ; (c) `microscope`/`discourse_context` â€” l'analyse fine du discours (fils de sujets, actes de parole) doit tourner sur les tours live d'E31, pas seulement sur l'import batch ; (d) P2 : exposer en session les questions de `clarification_inbox_v14_8` gÃ©nÃ©rÃ©es la nuit (le systÃ¨me pose SA question au bon moment).

## E35 â€” Sorties : voix, correction, replay

**Faire** : **TTS local** (sherpa-onnx TTS, mÃªme dÃ©pendance que l'ASR) pour les rÃ©ponses courtes (Â« c'est quoi Ã§a Â» en conduite/capture-only, confirmations) avec toggle voix/silence ; endpoint **replay** (clips/keyframes par plage horaire depuis les tables existantes) â†’ `VirtualScreen` (composant dÃ©jÃ  prÃªt) et companion-web ; correction vocale cÃ¢blÃ©e bout en bout.
**Test** : requÃªte Â« rejoue 14h30 Â» simulÃ©e â†’ clip servi â†’ VirtualScreen intent.

## E36 â€” Ops de prod

**Faire** : accÃ¨s hors-maison (Tailscale/WireGuard documentÃ© + testÃ© : le live contextuel dehors passe par le VPN, latence mesurÃ©e, politique dÃ©gradÃ©e explicite sinon) ; ~~**backup automatique chiffrÃ©** de la mÃ©moire (SQLite + mÃ©dias evidence â†’ destination configurable, planifiÃ©, testÃ© en restauration)~~ **DIFFÃ‰RÃ‰ (dÃ©cision utilisateur 2026-07-05 â€” usage perso, gÃ©rÃ© manuellement)** ; quotas stockage surveillÃ©s par doctor ; profil temporaire d'inconnu via VLM (description apparence â†’ entitÃ© provisoire non nommÃ©e, fusionnable Ã  l'enrollment).

**PrioritÃ© utilisateur (2026-07-05)** : l'usage principal est DEHORS (tÃ©lÃ©phone en 4G/5G, PC Ã  la maison derriÃ¨re NAT) â†’ l'accÃ¨s hors-maison est **LE** livrable. Le backup chiffrÃ© est reportÃ© (gÃ©rÃ© Ã  la main).

## Puis : les deux finals

- **E30-A (PC, sans matÃ©riel)** : close-day rÃ©el complet â€” Qdrant + Ollama allumÃ©s, vie synthÃ©tique injectÃ©e, 10 stages chronomÃ©trÃ©s < 6 h sur RTX 3070, journal gpu_phase, doctor -Memory, benchs publiÃ©s.
- **E30-B (matÃ©riel)** : gates G1â†’G8 rÃ©els (Unity + SDK XREAL + S25), bench LAN rÃ©el, session 3 h, capture-only sur second tÃ©lÃ©phone, compilation Kotlin/Unity de E22-E26.


## E37 â€” Nuit complÃ¨te + owner (FAIT â€” audit de clÃ´ture 2026-07-05)

Faille critique rÃ©parÃ©e : l'audio brut V19 n'Ã©tait pas archivÃ© â†’ le nocturne (WhisperX+pyannote+attribution voixâ†’personID) n'avait rien Ã  traiter. Segments VAD archivÃ©s + events `speech_segment` au format Phone Bridge exact ; bundle bi-modal audio+vision prouvÃ© ; owner enrÃ´lable en V19 (Â« configure ma voix Â») ; `memory_owner_id` garanti sur la chaÃ®ne vision ; garde-fou pose placeholder.

## E38 â€” Intelligence fine (FAIT â€” 2026-07-05, branche feat/v19-e38-fine-intel)

(a) **Auto-confirmation d'hypothÃ¨ses d'identitÃ©** : prÃ©nom entendu dans la conversation â†’ associÃ© Ã  la personne prÃ©sente ; observations rÃ©pÃ©tÃ©es multi-sessions renforcent l'hypothÃ¨se Â« ? boulanger Â» ; promotion automatique probableâ†’observed Ã  seuil avec preuves ; rÃ©solution automatique des hypothÃ¨ses `clarification_inbox_v14_8`/`UNKNOWN_VOICE` quand les signaux convergent (sans enrollment manuel â€” l'enrollment reste le raccourci).
(b) **Changements d'attributs bi-modaux** : apparence des personnes connues inter-sessions (coiffure/vÃªtements â€” Â« PersonX a changÃ© de coupe Â») ; texte/prix par lieu : OCR mÃ©morisÃ© comparÃ© Ã  la re-visite ET croisÃ© avec les faits ENTENDUS en conversation au mÃªme endroit (Â« hier c'Ã©tait pas ce prix Â» â€” vu ou entendu). Nouveau type ChangeEvent `attribute_changed`.
(c) **Routineâ†’objet** : l'approche d'une entitÃ© liÃ©e Ã  une routine fait remonter proactivement le last-seen de l'objet associÃ© (TV â†’ tÃ©lÃ©commande), depuis `brain2_spatial_routine_models` + co-occurrences.

## ADR Â§E37 (complÃ©ment â€” session coupÃ©e avant la doc)

- Format `speech_segment` : dÃ©couvert dans le cÅ“ur (writer du Phone Bridge dans la chaÃ®ne sensor_fusion/service V15) et reproduit Ã  l'identique par `audio_archive.py` â€” colonnes/payload conformes Ã  ce que lisent `bundles_require_deep_audio` et `collect_live_raw_timeline`.
- SubtilitÃ© assembleur : `audio_timeline_json` se remplit via les tours texte (`brainlive_turn_buffer`, modality audio_text) tandis que le dÃ©clencheur deep audio lit les events `speech_segment` â€” les deux coexistent dans le mÃªme bundle (bridge conversationnel E31 + archive E37), c'est le fonctionnement nominal V18.8 reproduit.
- Conflit routeur corrigÃ© : patterns `owner_enroll` enregistrÃ©s AVANT `set_tts` (le `\bparle\b` du toggle TTS avalait Â« c'est moi qui parle Â»).
- Quota audio : ligne ajoutÃ©e au doctor `-Quota` ; purge par le close-day comme le tampon-jour.

## E46-C — Contexte/reprise/UI PhoneOnly (2026-07-07)

- [x] Mesurer la fenêtre Ollama réelle : 4096 par défaut malgré 262144 natifs Qwen3.5.
- [x] Fixer `num_ctx=16384` pour le post-stop et vérifier Qwen3.5:9b 100% GPU.
- [x] Prouver le découpage CloseDay par bundles et conversations checkpointées.
- [x] Rejeter atomiquement toute sortie `done_reason=length`.
- [x] Persister session/token Android par AES-GCM + Android Keystore et reprendre par renew.
- [x] Autoriser une nouvelle session mono-appareil uniquement après end + CloseDay completed.
- [x] Afficher la caméra et les composants UI réels dans la scène PhoneOnly, sans demo driver.
- [x] Consommer les `scene_delta` dans SceneCache/LocalTrackStore.
- [x] Relier la queue H1 BrainLive au DataChannel et les UIReceipt au writer V18.8.
- [x] Activer identity/replay/stranger/fine-intel dans le runtime PhoneOnly.
- [x] Relier « c'est quoi ça ? » à la dernière frame réelle, bornée à une frame.
- [ ] Embarquer et valider les modèles reflex Android, le partage micro et la traduction live locale.
- [ ] Valider gestes, cartes personne, commandes vocales et receipts sur téléphone réel.

## E46-D — POINT DE REPRISE OBLIGATOIRE (arrêt du 2026-07-07)

Terminé factuellement :

- [x] Installer JDK 17 et Gradle 8.7; détecter le SDK Android système.
- [x] Corriger les erreurs de compilation Kotlin réellement rencontrées.
- [x] Épingler l'AAR officiel sherpa-onnx v1.12.10 et retirer JitPack.
- [x] Construire/tester `livetransport` et `reflexvision`, puis exporter les AAR/dépendances vers Unity.
- [x] Installer et vérifier Unity Editor 6000.0.23f1.
- [x] Arrêter les travaux et confirmer qu'aucun processus Unity/UnitySetup ne reste actif.

Tâche interrompue : préflight Unity/Android du point 8, avant import Unity et génération APK.

Reprise 2026-07-07 (session E46-D, branche `feat/v19-e46d-android`) :

- [x] Android Build Support : Hub `install-modules` refusé (éditeur hors-Hub). Contourné — NDK r23b (23.1.7779620) installé via sdkmanager, SDK/JDK17/Gradle externes configurés (`AndroidBuild.cs` pose SDK/NDK/JDK dans les prefs au build).
- [x] Licence Unity vérifiée batchmode → **BLOQUÉE** : `No valid Unity Editor license found` (activation login interactif requise). Documenté dans `E46D_STATE.md`.
- [x] Build AAR reproductible relancé, hashes enregistrés (livetransport `19d04664…`, reflexvision `c1b128cd…`, sherpa `f51f5936…`). Dédup Kotlin OK.
- [ ] Import Unity + tests EditMode — **bloqué licence**. Manifest PhoneOnly propre (aucune réf `file:` XREAL). Prêt à lancer post-activation.
- [ ] Scène PhoneOnly — **bloqué licence**. Source vérifiée statiquement (tous composants câblés).
- [x] Revalidation ponts audit : les 11 constats confrontés au checkout courant → **tous réfutés (déjà corrects)**. Détail dans `E46D_STATE.md`. Aucun fix code requis.
- [x] Build Android IL2CPP ARM64 : méthode `Editor/AndroidBuild.cs` livrée (minSdk29/targetSdk34, define `MLOMEGA_PHONE_ONLY`, endpoint via env). APK **bloqué licence** ; commande d'exécution documentée.
- [x] Suites : V19 **207 passed / 2 skipped / 0 failed** (scénario traduction obsolète corrigé). V18 ciblé **5 passed** (turns.created_at invariant vert). Aucune dép réelle `turns.created_at`. Cœur V18.8 non modifié.
- [ ] Téléphone réel via `adb` — bloqué en amont par l'APK (licence).
- [ ] Déconnexion seule vs fin explicite + CloseDay sur device — bloqué en amont.
- [ ] Gates séparés (traduction Android, partage micro, reflex/gestes, TTS, multi-sessions) — non traités (hors périmètre point d'arrêt).

Non validé à cet arrêt (bloqué par la licence Unity, pas par le code) : compilation Unity, tests EditMode, APK, `adb`, téléphone réel, audio/UI matériels, CloseDay depuis Android.
Action débloquante : activer une licence Unity Personal via Unity Hub (login Unity ID), puis relancer étapes 3→5.

## E46-D — FAIT (clôture 2026-07-07)

Licence Unity activée par l'utilisateur : étapes 3→7 toutes terminées. Import Unity + premier passage compilateur (10 familles de fixes, dont ContractJson/ParseObject `DateParseHandling` — timestamps ISO corrompus par la culture) → **EditMode 59/59**. Scène PhoneOnly générée et câblée. **APK `mlomega-phoneonly.apk` livré : 54,6 Mo, SHA-256 `31762C5032947FFFACE94BC3F4F096366518B83D0BE7C86831C3D60AD9C53445`**, IL2CPP/ARM64, minSdk29, `MLOMEGA_PHONE_ONLY`, endpoint LAN. Triage audit 11/11 réfutés + invariant `turns.created_at` réfuté. Suites : V19 207/2 skip/0 fail, V18 ciblé 5/5. Détail complet dans `E46D_STATE.md` et `EXECUTOR_BUILD_GUIDE.md` section E46-D.

Reste ouvert (hors périmètre E46-D, à ne pas confondre avec « fait ») :
- [ ] Test device S25 réel (imminent) : `adb`, install APK, caméra/micro, session live, vérification vidéo/audio/UI/cartes/commandes.
- [ ] Gates produit Android-local NON FAITS (décision 2026-07-07 : premier build livré sans) : ASR/traduction/gestes/TTS locaux, arbitrage micro partagé avec WebRTC, sémantique multi-sessions/jour.
- [ ] E30-A / close-day : décision utilisateur — à valider EN SESSION RÉELLE, pas en synthétique.
- [ ] E30-B.

## E47 — Gates Android-local (FAIT — 2026-07-07, validation device en attente)
Arbitrage micro unique (JavaAudioDeviceModule fan-out, samples identiques prouvés), wake word configurable = fenêtre de commande (`is_command`, capture jamais coupée), gestes MediaPipe activés (12 fps throttle, palm/swipe/pinch câblés bout-en-bout — dont le gap E26 pinch→zoom jamais abonné), provisioning PC (`/models/device/*`), gating routeur `open|gated` (défaut open), multi-sessions/jour (`--allow-rerun`, ADR §E47C). APK v2 : SHA BCC68997…5A0C. **Restes** : client de téléchargement des modèles côté app (manuel via adb en attendant), TTS device (différé), validation S25.

---

# Plan d'actions E48→E52 (établi 2026-07-08, reprise post-passation)

Même discipline que E31→E47 : une étape = petits changements testés, ADR dans DECISIONS.md, push au fil de l'eau sur `main`, cocher les cases APRÈS succès réel. La validation device S25 (première vraie session + close-day) reste le juge de paix transversal — elle peut s'intercaler à tout moment.

## E48-A — Confort produit : modèles device, dehors, traduction live (À FAIRE)

1. **Client de téléchargement des modèles dans l'app** (remplace l'`adb push` manuel) — **[x] code fait (e48a-1, 2026-07-08), validation device en attente** :
   - [x] Au premier lancement (ou si `getExternalFilesDir()/models/` incomplet) : `GET /models/device/manifest` (endpoints PC e47c déjà livrés, token session) → download de chaque modèle manquant, SHA-256 vérifié via `X-Model-Sha256`, écriture atomique (tmp+rename), reprise si coupure, extraction tar.bz2 + normalisation des noms sherpa. `ModelProvisioner`/`DeviceModelManifest` (livetransport) + `ModelProvisioningBridge` Unity après pairing ; re-arm des bridges au prochain lancement (ADR §E48-A — pas de re-arm à chaud, invariant micro unique). Tests JVM 56/56 (dont 14 nouveaux), AAR reconstruits.
   - [x] UI : progression discrète `dl:<modèle> NN%` via StatusBar ; dégradé honnête si modèle absent (garde-fous AsrBridge/GestureBridge), jamais un crash.
   - [x] **Décision poids (mesures réelles 2026-07-08)** : archives = ASR FR 380 Mo + ASR EN 296 Mo + KWS 16,8 Mo + MediaPipe 15,5 Mo ≈ **710 Mo** → tout embarquer ferait un APK ~750 Mo (vs 54,6 Mo) : REFUSÉ. Compromis retenu : **embarquer les petits** (KWS + 2 tasks MediaPipe + silero_vad ~2 Mo, +35 Mo → APK ~90 Mo) via StreamingAssets copiés au 1er lancement, pour wake word + gestes out-of-the-box ; les 2 ASR streaming restent téléchargés par le client ci-dessus (Wi-Fi LAN, une fois). Option futur : n'embarquer/télécharger que la langue active + variante int8 si dispo.
   - [x] Gap découvert et corrigé : `silero_vad.onnx` (requis par AsrKwsService — gate tout le flux ASR/KWS) manquait de la section `device:` du manifeste → ajouté (MIT, hash épinglé) + embarqué APK.
   - Test (device réel, à faire) : device vierge → premier lancement → manifest lu, ASR téléchargés sha-OK, sous-titres offline actifs sans adb ; copie StreamingAssets au 1er lancement sans écraser un download.
2. **Tailscale opérationnel (mode dehors)** — le code failover existe (E36/E44), c'est de la CONFIG + VALIDATION (guide `docs/OUTSIDE_ACCESS.md`) :
   - [ ] Installer Tailscale PC + S25, même compte (§2-3) ; relever l'IP `100.x` du PC.
   - [ ] Renseigner la liste ordonnée d'endpoints LAN d'abord, Tailscale ensuite : `configs/user_profile.yaml` (§4.1) + asset `MLOmegaConfig` Unity (§4.2) → rebuild APK avec la liste (ou champ éditable).
   - [ ] Valider la détection automatique déjà codée : même Wi-Fi → `active_link=lan` (rapide, 720p) ; 4G/5G → bascule tunnel `active_endpoint=tailscale`, `active_link=wan` (540p) ; retour maison → re-bascule LAN. Checklist complète §8 sur vraie 4G.
   - Test : les 6 cases de la checklist §8 d'OUTSIDE_ACCESS.md cochées sur 4G réelle.
3. **Traduction live continue = RÉFLEXE DEVICE** (décision utilisateur 2026-07-08 : sur le téléphone, PAS de PC — doit marcher offline comme les sous-titres ; reste E46 : `translation_hot` ne traduit rien ; le « traduis-le » à la demande E33 côté PC existe et reste inchangé) — **[x] code fait (e48a-3, 2026-07-08), validation device en attente** :
   - [x] Moteur choisi (ADR §E48-A) : **ONNX Runtime + OPUS-MT Helsinki-NLP fr-en/en-fr int8** (exports Xenova, Apache-2.0, ~100 Mo/direction, provisionnés comme les ASR — 6 entrées manifeste). ML Kit rejeté (GMS + ToS « embedded devices »), Bergamot/CTranslate2 rejetés (pas de portage Android). Tokenizer Marian pur Kotlin (testé round-trip JVM), decode greedy KV-cache validé par test d'intégration desktop sur les vrais modèles.
   - [x] `OfflineTranslator`/`OfflineTranslatorBridge` (reflexvision) : finals uniquement, sessions lazy, libération après 60 s d'inactivité, une direction résidente ; `TranslateBridge` Unity (fil AsrBridge→SubtitleSkill) → traduction affichée sous le sous-titre original + `translation_hot` (SceneCache §9.1). Dégradé honnête (modèle absent → original seul).
   - [x] Toggle : menu « Traduire » + intents PC « traduis en direct » / « stop traduction » (grammaire AVANT le translate générique + LLM + high-confidence) → `device_command translate_live` (on/off/flip). Tests JVM 77/77 (les 2 modules), pytest ciblés 43/43.
   - [x] **GAP MAJEUR découvert et corrigé au passage** : la couche réflexe (AsrBridge, GestureBridge, WakeWordGate, ReflexScheduler, 5 skills, LocalIntentSource) n'était JAMAIS ajoutée à la scène PhoneOnly par `PhoneOnlySceneBuilder` — le wake word/gestes/sous-titres offline d'E47 (APK v2) n'avaient aucun hôte runtime. Builder corrigé ; la scène doit être RÉGÉNÉRÉE au prochain build APK.
   - Test (device réel, à faire) : PC coupé, segment final EN → traduction FR affichée offline ; toggle on/off ; pas de traduction sur partiels.

## E48-B — ChangeAttention live (RECADRÉ 2026-07-08 : HandAction déplacé en E53)

Décision utilisateur 2026-07-08 : le mode aide universel « soit on le fait bien, soit on ne le fait pas » — la version A (checklist voix) est jugée insuffisante, la version complète (ancrage spatial temps réel + validation auto) n'est pas viable aujourd'hui (voir E53). E48-B se réduit donc à ChangeAttention live.

1. **ChangeAttentionSkill live** (la brique détection existe — E28 WorldBrain + E38 attributs — mais nocturne ; il manquait le cue instantané) — **[x] FAIT (e48b, 2026-07-08)** :
   - [x] `services/live-pc/change_attention.py` branché dans `LivePipeline._on_scene_delta` (aux côtés de WorldBrain, config profil `change_attention:`) : sortie de zone → état figé ; ré-entrée → comparaison des entités mémorisées vs courantes → cue sobre via la queue H1 existante (scene_adapter → v18_delivery, AUCUNE nouvelle queue). Chemin cross-session best-effort par `place_hint` (lecture `scene_session_summaries_v19`).
   - [x] Anti-bruit : seuil d'écart, cooldown par zone, UN cue max par ré-entrée, silence si map_quality faible, silence à la première visite. Métriques `/metrics`.
   - [x] Tests : `test_change_attention.py` 6/6 + non-régression fichiers touchés = 50/50. ADR DECISIONS.md §E48-B.
   - Limite documentée (ADR) : le cue est surtout INTRA-session (`zone-N` de la carte de pose, stable en session seulement) ; le cross-session s'activera quand un `place_hint` stable sera fourni en live — même limite que `ReflexSignal.ZoneChange` device.
   - (Réserve non décidée, notée pour plus tard : les 4 petits réflexes proposés — « on t'appelle » via KWS prénom, checklist de sortie porte/objets, obstacle tête baissée, minuteur contextuel.)

## E49 — Lunettes XREAL (gate G1 matériel) (À FAIRE)

- [ ] Obtenir le SDK XREAL (compte développeur utilisateur) et le déposer dans le projet Unity (le manifest PhoneOnly reste propre — la réf XREAL redevient active seulement pour ce build).
- [ ] `XrealDeviceAdapter` (écrit depuis E22) : compiler, rendu stéréo, caméra Eye = `EyeCaptureSource` ; mêmes contrats/SceneCache/skills (aucun fork de code produit).
- [ ] Rebuild APK profil lunettes ; gates G1 réels : affichage stéréo, caméra Eye, pose, sessions longues, budget batterie.
- [ ] Plan B documenté si l'accès caméra Eye coince (handoff §risques) : one-xr + caméra S25 en attendant.
- Test : session réelle lunettes → mêmes scénarios que FIRST_TRY_ANDROID (PersonTag, sous-titres, gestes) en stéréo.

## E50 — Dashboard mémoire lecture seule (intégrer + adapter MemoryLight) (À FAIRE)

Source : `memorylight_dashboard_readonly` v2 (Streamlit une page, SQLite `mode=ro`, verrou ECRIRE pour les rares actions CLI) — ZIP utilisateur `C:\Users\wabad\Downloads\memorylight_dashboard_readonly_v2_verified.zip`.

**FAIT (e50, 2026-07-08) — validation visuelle utilisateur en attente.** Port **8720** (vérifié sans collision : 8710/6333/6334/11434/8766/8704/8706/8776/8601 exclus). Lancement : `scripts\RUN_DASHBOARD.ps1` → http://localhost:8720. Smoke test headless : HTTP 200, zéro exception, base réelle en mode=ro. Schémas V19 inspectés dans la vraie base (pas devinés). Chat rebranché tel quel : `v14-ask`/`v14-answer` existent toujours dans la CLI cœur (→ `ask_brain2`), commande par défaut `python -m mlomega_audio_elite.cli` (pas d'install globale requise). Télémétrie Streamlit coupée.

- [x] Intégrer la source sous `apps/memory-dashboard/` + `scripts/RUN_DASHBOARD.ps1` (pointe `.env`/memory.db du projet, `--person-id` du profil) ; dépendances dans `.venv-live` (install idempotente).
- [x] Adapter les requêtes aux schémas réellement présents dans la base V19 (les tables v14/v18 existantes restent lisibles telles quelles ; tout ce qui n'existe pas s'affiche « absent », pas d'erreur).
- [x] **Vues V19 ajoutées** (bloc « 🛰️ V19 — ce que la mémoire produit maintenant » : compteurs, hypothèses `brainlive_life_hypotheses`+evidence, Life Model `life_model_entries_v19`/`self_schema_v19`/`predictions_v19`+outcomes+`calibration_scores`, visuel `visual_events_v19`+`visual_evidence_assets_v19`, monde `world_entity_links_v19`/`brain2_spatial_routine_models`/`scene_session_summaries_v19`, sessions `brainlive_sessions`+`v18_close_day_runs` avec flag reopened) :
  - hypothèses en attente / auto-confirmées / réfutées (E38) avec leurs preuves ;
  - Life Model V19 : entrées typées, historique/transitions, prédictions + `verification_spec` + outcomes (verified/refuted) + calibration ;
  - événements visuels + chaîne de preuve (visual_events/evidence_assets) et entités/lieux/routines WorldBrain (dont attributs bi-modaux changés) ;
  - sessions live + close-day runs/stages (multi-sessions du jour, `reopened`, durées) ;
  - compteurs live utiles (interventions H1 livrées/receipts, intents routés/gated — recoupe `/metrics`).
- [ ] Rebrancher le chat sur le routeur Brain2 actuel (`ask_brain2` / CLI du cœur) au lieu de v14-ask si la signature a bougé ; garder le verrou écriture.
- Test : dashboard lancé sur la base réelle post-première-session → chaque section s'affiche sans erreur ; aucune écriture DB (mode=ro prouvé).

## E51 — Installateur / guide de bienvenue interactif (n'importe qui installe en 2 clics) (À FAIRE)

Un assistant unique (`scripts/WELCOME_MLOMEGA.ps1`, réutilise `setup_profile.ps1`/`INSTALL_MLOMEGA_V19_WINDOWS.ps1`/`DOCTOR` existants — ne PAS réécrire l'install, l'orchestrer) qui déroule dans l'ordre :

- [ ] 1. Matériel : « Avez-vous des lunettes ? » Oui → choix XREAL uniquement (Spectacles/Meta plus tard) / Non → mode PhoneOnly. Puis « Quel téléphone ? » → Android (S25/OnePlus… même APK).
- [ ] 2. Scan machine (GPU/VRAM/RAM/disque via nvidia-smi & co) → proposer le set de modèles adapté (les plus utiles seulement, ex. Qwen3.5 4b live + 9b deep sur 8 Go VRAM ; dégradé sinon) ; option API cloud (OpenAI/Gemini) = opt-in avec saisie de clé.
- [ ] 3. Token Hugging Face demandé (pyannote) avec lien direct + contrôle de validité.
- [ ] 4. Installation complète sans erreur bête : venvs (.venv + .venv-live, locks existants), ffmpeg, Qdrant natif, Ollama + pulls des modèles choisis, `fetch_models_v19.py` (+ `--device`), `.env` généré, `setup_profile` rempli des réponses, DOCTOR -Full en garde-fou final.
- [ ] 5. Lancement PC guidé (les 3 commandes, ou un `START_ALL` qui les enchaîne) → health vert affiché.
- [ ] 6. Téléphone : où prendre l'APK, `adb install` OU copie manuelle, permissions, pairing auto ; si lunettes : connexion XREAL à l'app.
- [ ] 7. Choix du mot d'éveil (« comment appeler l'assistant ? ») — avertir : PAS un mot trop courant (faux déclenchements) ; écrit dans la config. Inclut le chantier « wake word runtime » (demande utilisateur 2026-07-08) : aujourd'hui le mot est cuit dans l'APK (`_wakeWord` de l'asset) ; le rendre configurable sans rebuild — choisi à l'install, poussé par le PC au pairing (message contrôle → `KeywordEncoder` runtime, l'encodeur le permet déjà).
- [ ] 8. Mini-tutoriel : ce que le système sait faire, commandes vocales clés, gestes, où voir les suggestions.
- [ ] 9. Comment quitter proprement (LE BOUTON Terminer → close-day) et pourquoi.
- [ ] 10. Le lendemain : comment relancer le matin, changer de modèles, commandes utiles de contrôle (DOCTOR, `/metrics`, `/session/status`, dashboard E50, où vit memory.db + conseil backup manuel).
- Test : dry-run complet sur machine « propre » simulée (ou VM) → zéro étape manuelle non guidée ; chaque échec d'étape donne une consigne claire, pas une stacktrace.

## E53 — Mode aide universel, version complète (DIFFÉRÉ — décision 2026-07-08)

« Aide-moi à faire X » (cuisiner, monter un meuble, réparer, coder…) fait BIEN, pas à moitié. Analyse coût/viabilité du 2026-07-08 :

- **Coût cloud vision** : force brute (1 image haute résolution/0,5 s, modèle frontier) ≈ 20-40 $/h de tâche ; architecture événementielle (keyframes sur changement de scène/main active) ≈ 2-6 $/h. Le coût n'est PAS le bloqueur.
- **Bloqueurs réels (état de l'art 2026-07)** : (1) latence cloud 1-3 s → coordonnées mortes sur caméra de tête, l'ancrage doit passer par keyframe cloud + tracker LOCAL qui colle l'ancre au présent ; (2) pointage spatial fin des VLM non fiable (« le trou B4 » → erreurs fréquentes ; flèche fausse = pire que rien, invariant de vérité) ; (3) validation auto d'étape fiable seulement sur le grossier (~85-90 % cuisine, non fiable assemblage fin).
- **Ce qui marche déjà très bien** : scan de notice page par page (extraction d'étapes ~95 %), recherche de plan sur internet, plan typé.

**Architecture cible actée** (à implémenter quand les VLM auront progressé sur le pointage spatial, ou en acceptant les limites) :
- [ ] Acquisition du plan : « as-tu un plan/une notice ? » → scan page par page (VLM document) OU recherche internet → plan d'étapes TYPÉES (objets, minuteur, zoom utile, next_action/next_intent).
- [ ] Banque d'UI par famille de tâche (cuisine : timer+ingrédients ; assemblage : pièce+zone ; réparation : outil+zone ; etc.) — choisie par le type du plan, pas codée en dur par tâche.
- [ ] Ancrage live : keyframes cloud événementielles (changement de scène / main active / demande) → ancre sémantique → tracker local (StableTrack) la maintient entre keyframes.
- [ ] Validation hybride : auto-suggérée avec confiance (« on dirait que c'est fait ? »), confirmée à la voix ; jamais d'auto-validation silencieuse sur du fin.
- [ ] Mode payant obligatoire pour la vision (opt-in, coût affiché — mécanique E33 existante) ; tâche persistée dans les open loops (reprise au briefing).
- Gate de viabilité avant de lancer : un banc d'essai pointage spatial (10 scènes réelles S25) où le VLM du moment atteint ≥ 90 % de localisation correcte d'objet désigné — sinon on attend.

## E54 — Rétention médias & budget disque (EN COURS — 2026-07-08)

Constat (audit 2026-07-08) : dans le checkout, **rien n'est purgé automatiquement** (le close-day calcule `cleanup_eligible` = autorisation, jamais une suppression) → le disque grossit sans limite (jusqu'à ~4 Go/jour audio + keyframes/clips). Et **bug réel** : les keyframes sont écrits dans des fichiers temp système (`kf_*.jpg`) référencés en base — un nettoyage de %TEMP% les perd alors que la base croit les avoir. Décision utilisateur : **tout garder, budget 100 Go**, pouvoir rejouer clips/audio à tout moment.

- [x] **Patch longitudinal week/month** (FAIT — `v18_close_day.py` `_due_longitudinal_periods`) : le close-day déclenche le rollup `week` le dimanche (fin de semaine ISO) et `month` le dernier jour du mois, sur la période complète, `run_periodic_mirror_layer=True` (parité avec le scheduler nightly V15/V18 que le chemin PhoneOnly n'invoquait pas). Idempotent. 6 tests (`test_longitudinal_periods.py`).
- [x] **Fix keyframes hors temp** (e54, 2026-07-08) : `visionrt.default_keyframe_sink` écrit dans un dossier média géré et persistant (`MLOMEGA_MEDIA`/`storage/media/keyframes/AAAA-MM-JJ/` via helpers `media_root()`/`keyframe_dir()`), plus de `tempfile` ; `vision_frames.image_path` pointe ce chemin stable. Rétro-compat : anciens chemins temp lus tels quels.
- [x] **Transcodage audio post-close-day** (e54) : `media_retention.transcode_audio_chunks` — WAV `brainlive_audio_segments_v154` → Opus `libopus 24k` (~÷10) via ffmpeg après re-transcription ; repointe les chemins base, garde le sha d'origine (lu sur `brainlive_sensor_events`) en métadonnée `speaker_json.transcode`. Réversible/désactivable (`transcode_audio`), dégradé honnête si ffmpeg absent.
- [x] **Purge des non-référencés âgés** (e54) : `media_retention.purge_unreferenced` — supprime UNIQUEMENT les médias qu'AUCUNE preuve ne cite (scan délimité de tous les `evidence_refs_json`/`evidence_json` + FK `visual_events_v19.asset_id` + lien `speech_segment` audio) ET plus vieux que `retention_days` (90 j). Référencé jamais supprimé.
- [x] **Budget global 100 Go avec éviction protégée** (e54) : `media_retention.enforce_budget` — au-delà de `total_gb`, évince le plus ancien NON-référencé d'abord ; ne touche jamais au référencé ; dépassement 100 % référencé → WARN, pas de suppression. Module dédié (`services/live-pc/media_retention.py`) sur les tables réelles, câblé au close-day PhoneOnly après `cleanup.eligible` (best-effort, ne fait jamais échouer le close-day).
- [x] **`storage_quota` dans les profils** (e54) : bloc ajouté à `configs/profiles/rtx3070.yaml` (`total_gb:100`, `warn_gb:80`, `fail_gb:95`, `retention_days:90`, `transcode_audio:true`, day-buffer) + `configs/user_profile.yaml` (commenté). DOCTOR `-Quota` lit ces valeurs (user_profile puis rtx3070 puis défauts ; ajout `total_gb`, seuils relevés 80/95).
- [x] Tests ciblés (e54) : `test_media_retention.py` 7/7 (référencé jamais sélectionné, purge d'âge protège le référencé, éviction budget oldest-first, dépassement référencé → WARN, no-op sous quota, transcode réversible ffmpeg réel + no-op désactivé). Non-régression fichiers touchés 26 passed (.venv) + visionrt 5/5 (.venv-live). ADR DECISIONS.md §E54.

## E55 — Enregistrement des clips vidéo + tiering (FAIT — 2026-07-08, validation session réelle en attente)

Objectif : pouvoir « rejouer la scène » en VRAIE vidéo (pas seulement le diaporama de keyframes actuel). Décisions utilisateur (2026-07-08) :
- **Encodage CPU, GPU intact — MAIS jamais au détriment du live** (contrainte dure) : le passthrough pur est IMPOSSIBLE (aiortc décode les frames avant de nous les livrer, `gateway.py _consume_track`, `track.recv()` → PyAV déjà décodé ; récupérer le H.264 brut demanderait de forker aiortc). On ré-encode donc les frames DÉJÀ décodées pour la vision (pas de décodage en plus, seul l'encode s'ajoute). Encode **libx264 CPU** (le GPU reste 100 % pour vision+LLM). **Garantie non négociable** : l'encode ne doit JAMAIS ralentir BrainLive/VisionRT/ASR → file bornée avec DROP-on-full (le producteur live ne bloque jamais), encodeur **ffmpeg en process séparé à priorité basse**, auto-pause si surcharge persistante. Si la garantie ne tient pas → on n'active pas. Coût nocturne vidéo = 0. PAS de NVENC (GPU), PAS d'AV1.
- **Tiering intelligent** : on ne garde pas tout en vidéo. Un segment « intéressant » (conversation active, mouvement/looming, événement/changement, ou référencé par une preuve) est conservé comme clip ; un segment « ennuyeux » est rétrogradé → on supprime le fichier clip et on ne garde que ses keyframes déjà extraits (timelapse gratuit). Décision = métadonnée + suppression fichier (instantané), pas de calcul lourd.
- **Budget** : les clips vivent dans `visual_evidence_assets_v19` (asset_kind='clip') que le replay lit DÉJÀ, et sont soumis au budget/éviction de E54 (protège le référencé, évince le vieux non-référencé). Cible ~100 Go strict → en pratique ~2-3 h/jour de clips + keyframes pour le reste (maths 2026-07-08 : 720 h ne rentrent pas en bonne qualité à 100 Go ; le tiering garde la vidéo là où elle a de la valeur).

À faire :
- [x] Enregistreur live dans l'ingress WebRTC (`services/live-pc/` — gateway/transport/live_pipeline) : mux du flux entrant vers `storage/media/clips/AAAA-MM-JJ/<session>_<t>.mp4|webm` selon le codec reçu, segmenté (clips 1-5 min), best-effort (une erreur d'écriture ne coupe jamais la session ni la capture).
- [x] Indexation dans `visual_evidence_assets_v19` (asset_kind='clip', captured_at, sha256, uri, window) — de sorte que `replay_service` les serve sans changement.
- [x] Tiering au close-day (ou en fin de session) : marquer chaque segment keep/drop selon conversation/mouvement/événement/référence ; drop = suppression fichier + ligne. Réutilise la collecte « non-référencé » de E54.
- [x] Config profil : `clip_recording: {enabled, segment_seconds, keep_boring_days}` ; défaut activé, passthrough.
- [x] Tests : segment écrit+indexé, tiering garde l'intéressant/droppe l'ennuyeux non-référencé, replay retrouve un clip, best-effort (écriture qui échoue ≠ crash). ADR DECISIONS.md.

Note : quel que soit le disque, le moteur s'adapte au budget — 100 Go = ~3 h/jour de clips ; un SSD externe 1 To = ~8 h/jour sur 6 mois (option matérielle recommandée mais non requise).

**Vérif coût CPU (mesure ffmpeg réelle, 2026-07-08, machine 12 cœurs)** : encoder 120 s de vidéo prend 2,1 s en 540p/12fps veryfast 1 Mbps → **~1,8 % d'un seul cœur en continu** (720p/15fps = ~3,8 %). Zéro GPU (le live tourne sur le GPU : VisionRT/ASR/LLM). Condition utilisateur « si ça bloque le live on le fait pas » → levée : coût négligeable, ressource disjointe du live, + file drop-on-full/priorité basse en garde-fou. GO confirmé.

## E52 — README complet du projet (FAIT — 2026-07-09)

`README.md` réécrit en document d'accueil complet : vision, ce que ça fait par domaine (live + nuit), architecture 3 couches + schéma de flux, matrice matériel, installation (renvoi E51 à venir + manuel), lancement, dashboard E50, compilation APK, mode dehors, invariants vérité/vie privée, doc, état daté (2026-07-09) + roadmap honnête (E49/E51/E53 + SSD 1 To). Rien promis de non validé (session S25 = « en attente »).

- [x] Réécrire `README.md` en vrai document d'accueil détaillé : vision (exocortex mémoire de vie), architecture complète (3 couches + schéma flux téléphone↔PC↔nuit), tout ce que le système fait AUJOURD'HUI (capacités par domaine : mémoire, identité, vision, voix, gestes, proactivité, replay, dehors, multi-sessions), matrice matériel (PhoneOnly / XREAL / capture-only / viewer iPhone), installation (renvoi E51), première session (renvoi FIRST_TRY), dashboard (renvoi E50), invariants de vérité/vie privée, état des tests datés, roadmap honnête (fait / différé / futur).
- [ ] Le README actuel (f7b2b1d) devient la base ; ne rien promettre de non validé (S25 tant que pas fait = « en attente de validation device »).
- Test : relecture utilisateur — un inconnu comprend le projet et sait par où commencer sans lire une autre doc.
