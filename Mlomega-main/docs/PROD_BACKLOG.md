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

## E49 — Lunettes XREAL (gate G1) (CODE FAIT — 2026-07-09 ; validation sur lunettes physiques en attente)

SDK XREAL 3.1.0 fourni par l'utilisateur, intégré et APK lunettes **buildée** (`mlomega-xreal-g1.apk`, ~191 Mo).

- [x] SDK déposé dans `apps/xr-mobile/Packages/xreal-sdk/com.xreal.xr.tar.gz` (git-ignoré — propriétaire) ; le manifest COMMITÉ reste XREAL-free (un clone PhoneOnly sans SDK compile ; la dép `com.xreal.xr` est injectée AU BUILD par `AndroidBuildXreal`).
- [x] `XrealDeviceAdapter` **recâblé sur l'API réelle du SDK 3.1.0** (l'ancien code E22 visait des noms supposés) : `XREALRGBCameraTexture.CreateSingleton()` (pas `new RGBCameraTexture`), `StartCapture/StopCapture` (pas Play/Stop), callback `OnRGBCameraUpdate` (pas `DidUpdateThisFrame`), `GetTimeStamp` (pas `GetFrameTimestampNs`), `GetDeviceType` (pas `GetDeviceName`), tracking via `UnityEngine.XR.InputDevices` (API standard). `Core.asmdef` référence l'assembly XREAL par GUID (warning inoffensif sur un clone sans SDK, code compilé out par le define).
- [x] Build lunettes reproductible : `AndroidBuildXreal.cs` (menu `MLOmega > XREAL`) — injecte la dép SDK, pose le define `XREAL_SDK_PRESENT` (retire `MLOMEGA_PHONE_ONLY`), active le **loader XREAL** pour Android (XR Plug-in Management), IL2CPP/ARM64, appId `com.mlomega.xr.glasses`, build la scène G1Gate → `build/android/mlomega-xreal-g1.apk`. **EditMode compile OK, IL2CPP OK, APK produite.**
- [x] Installateur (WELCOME) : branche lunettes → APK lunettes (comment la builder) au lieu du placeholder.
- [ ] **Gates G1 RÉELS sur lunettes physiques (en attente du matériel)** : affichage stéréo, caméra Eye (RGB → YUV→RGB shader), pose 6DoF, sessions longues, budget batterie. Plan B si l'Eye est absente (One vs One Pro) : pose-only (déjà géré dans l'adaptateur).
- Test device : session réelle lunettes → mêmes scénarios que FIRST_TRY_ANDROID (PersonTag, sous-titres, gestes) en stéréo.

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

## E51 — Installateur / guide de bienvenue interactif (FAIT — 2026-07-09, install réelle sur machine propre en attente)

`scripts/WELCOME_MLOMEGA.ps1` (+ `WELCOME.md` à la racine) : assistant unique qui ORCHESTRE les scripts existants (n'en réécrit aucun). 3 modes : interactif (défaut), `-Defaults` (valeurs sûres, non bloquant), `-DryRun` (déroule sans rien installer). UTF-8 **avec BOM** (PS 5.1). Params des scripts appelés vérifiés dans le code réel. Dry-run exécuté → exit 0, déroulé des 9 étapes validé (détection RTX 3070 8 Go OK, set de modèles adapté).

- [x] 1. Matériel : lunettes XREAL / Non (PhoneOnly). **Branche XREAL honnête** : enregistre le choix + explique « support E49 à venir, dépose ton SDK puis rebuild ; en attendant PhoneOnly », l'install PC reste identique. Téléphone → Android (même APK).
- [x] 2. Scan machine (nvidia-smi VRAM / RAM / disque) → set de modèles selon la VRAM (≥8 Go : qwen3.5:4b + 9b + moondream ; 6-8 / <6 / CPU = dégradés proposés). Cloud opt-in OpenAI/Gemini avec saisie de clé (écrite dans `.env`, jamais loguée) + politique de données.
- [x] 3. Token Hugging Face (pyannote) : liens directs (compte, conditions du modèle, token read), contrôle du format `hf_`, écrit dans `.env` (WARN honnête si absent).
- [x] 4. Installation complète idempotente : `INSTALL_MLOMEGA_V19_WINDOWS.ps1 -SkipDoctor`, check/winget ffmpeg, `ollama pull` des modèles choisis, `fetch_models_v19.py --device`, `.env` généré depuis le template (placeholders `__PROJECT_ROOT__`/`__HF_TOKEN__`/`__PHONE_TOKEN__` substitués, token téléphone auto), `setup_profile.ps1` alimenté par les réponses, `DOCTOR -Full` en garde-fou. Chaque étape : Test-Path + message clair + reprise, jamais de stacktrace brute.
- [x] 5. Lancement PC guidé (START_QDRANT + rappel `ollama serve` + RUN_MLOMEGA_V19 `-LivePhone -BindHost 0.0.0.0 -Port 8710`) + rappels pare-feu (port 8710 réseau privé) et même Wi-Fi.
- [x] 6. Téléphone : APK (adb `install -r` ou copie), permissions micro/caméra, pairing auto, téléchargement auto des modèles device ; branche lunettes = placeholder E49. Choix enregistrés dans `configs/welcome_choices.txt`.
- [x] 7. ~~Choix du mot d'éveil~~ **RETIRÉ (décision utilisateur 2026-07-09)** : le mot est cuit dans l'APK (« omega »), non modifiable sans rebuild. La question reviendra seulement avec le chantier **« wake word runtime »** (mot choisi à l'install, poussé par le PC au pairing → `KeywordEncoder` runtime). Le mini-tuto mentionne juste « omega » (mode gated).
- [x] 8. Mini-tutoriel : ce que fait le système, commandes vocales clés, gestes (paume/balayage/pincement), où voir les suggestions.
- [x] 9. Comment quitter (LE BOUTON Terminer → close-day) et pourquoi (consolidation ; une déconnexion ne consolide pas).
- [x] 10. Le lendemain : relancer, changer de modèles, commandes de contrôle (DOCTOR, `/metrics`, `/session/status`, dashboard `RUN_DASHBOARD.ps1` → :8720, où vit `memory.db` + conseil backup manuel).
- [x] Test : dry-run complet exécuté (exit 0), zéro étape non guidée, chaque échec donne une consigne claire. **Reste** : une install réelle de bout en bout sur machine propre (non exécutée ici — trop lourd/destructif) ; le chantier « wake word runtime » (branche 7).

## E56 — VLM lourd de nuit (V19) + trous one-click de l'installateur (FAIT — 2026-07-09)

Deux constats de l'audit 2026-07-09 : (a) le VLM lourd de nuit (deep vision sur keyframes de bundle) était réglé pour `qwen3-vl:8b` dans le template V18.8, mais **le manifeste V19 ne déclarait que `moondream`** et l'installateur ne tirait que le léger → la deep-vision de nuit retombait sur moondream (ou pire un modèle texte). (b) WELCOME ne créait pas le `.venv` cœur (moteur du close-day nocturne) ni ne provisionnait Qdrant → pas vraiment « one-click ».

- [x] **Manifeste** : entrée `vlm_heavy` ajoutée (`configs/MODEL_MANIFEST.yaml`) — VLM VISION de nuit, `qwen2.5vl:7b` par défaut (modèle installé par l'utilisateur), phase nocturne, à côté de `vlm: moondream` (live). Rappel : la deep-vision tourne sur les keyframes sélectionnés par bundle (~12/bundle), pas sur la vidéo ; le modèle est chargé pour cette phase puis déchargé.
- [x] **WELCOME — VLM léger + lourd** : détecte le tag exact `qwen2.5vl*` via `ollama list` (fallback `qwen2.5vl:7b`), tire moondream (live) **et** le VLM lourd (nuit), et pose `MLOMEGA_VLM_MODEL` (leger) + `MLOMEGA_OFFLINE_VLM_MODEL`/`MLOMEGA_VLM_HEAVY_MODEL` (lourd) dans `.env`. En profil dégradé (<6 Go VRAM), le VLM nuit retombe sur le léger.
- [x] **WELCOME — `.venv` cœur** : sous-étape 4a0 — crée `.venv` (Python 3.11) + `pip install -r requirements-v18_8-windows.lock.txt` (torch cu121/whisperx/pyannote) si absent, idempotent, avertit que c'est l'étape la plus longue. Sans lui la consolidation nocturne était impossible.
- [x] **WELCOME — Qdrant** : sous-étape 4a1 — télécharge la release GitHub `v1.12.6` (`qdrant-x86_64-pc-windows-msvc.zip`) dans `tools\qdrant\` si absent + génère `config.yaml` (storage local, port 6333), best-effort avec fallback clair.
- [x] Dry-run WELCOME exit 0 ; les 3 sous-étapes + le pull des 2 VLM apparaissent. Prérequis restants non auto-installables (honnête) : Python 3.11 et l'appli Ollama (WELCOME les détecte et guide). ADR §E56.

## E58 — Wake word par ASR français + changeable sans rebuild (FAIT — 2026-07-09 ; validation S25 en attente)

Constat : le KWS sherpa est entraîné en **anglais** → « viki » matché « vaïki », « jarvis » « djarviss » — inutilisable pour un francophone. Et le mot était cuit dans l'APK (rebuild pour changer). Décision utilisateur : détecter le mot dans la **transcription de l'ASR français** (déjà sur l'appareil), défaut **« viki »**, changeable **n'importe quand sans rebuild**.

- [x] **Device (Kotlin)** : `WakeWordMatcher.kt` (match tolérant — normalisation sans accents/ponctuation + distance d'édition selon longueur), branché dans `AsrKwsService.decodeSegment` sur le final ASR → `openCommandWindow` (le KWS anglais reste inoffensif, non supprimé). `setWakeWord(String)` runtime. Tests JVM `WakeWordMatcherTest`.
- [x] **Unity** : défaut `MLOmegaConfig._wakeWord = "viki"` + ASR par défaut **Fr** (le mot est entendu dans la langue de l'ASR) ; `AsrBridge.SetWakeWord` (natif, appliqué même si le service démarre après) ; `DeviceCommandHandler` action `set_wake_word` → événement `SetWakeWordRequested` (AsrBridge s'abonne, pas de cycle asmdef).
- [x] **PC** : `LivePipeline.wake_word` lu du profil (défaut viki) + `push_wake_word()` (idempotent/session) envoyé en `device_command set_wake_word` à la 1re réception DataChannel (`PhoneOnlyRuntime._on_receipt`). Tests : `test_push_wake_word_sends_set_wake_word_command_once` (+ 19 tests live pipeline verts, rien cassé).
- [x] **Installateur** : question « comment appeler l'assistant ? » ré-ajoutée (défaut viki, conseil « mot RARE »), écrit `wake_word:` dans `user_profile.yaml`. Dry-run OK.
- [x] APK v4 rebuild (embarque le matcher). **Change le mot n'importe quand** : édite `wake_word:` dans `configs/user_profile.yaml` → poussé à la prochaine session, zéro rebuild.
- [ ] Validation S25 : dire « viki » → fenêtre de commande s'ouvre ; changer le mot dans le profil → nouvelle session le prend. ADR §E58.

## E59 — Manipulation des fenêtres/panneaux à la main (FAIT — 2026-07-10, commit 2f86ddc ; validation device en attente)

Constat : paume (menu) / balayage (cacher) / pincement (zoom) existaient, mais pas la manipulation directe des affichages. Découverte : la POSITION du pincement était déjà exposée par le Kotlin (`GestureCallbacks.screenX/screenY` sur begin/update/end) → **zéro changement natif**, tout est Unity.

- [x] **Grab-drag** : `PINCH_BEGIN` sur un panneau manipulable (hit-test contre le registre opt-in `IManipulablePanel`) → le pincement est « claimé », le panneau colle au point de pincement et suit la main ; relâcher = posé. Pincement AILLEURS = non-claimé → le zoom LensWindow existant n'est JAMAIS volé (le ReflexScheduler exécute le manipulator avant le lens et coupe le zoom sur claim).
- [x] **Resize** : pincement sur un coin → redimensionne, clamp min/max **proportionnel** (l'aspect ratio de la fenêtre vidéo survit, pas de distorsion).
- [x] **Fermer / réduire** : boutons glass ✕ / – au coin (pinch-tap) ; – réduit en **pastille rappelable** (pinch-tap = restaurer). Balayage global « cache tout » inchangé.
- [x] **Cible prioritaire** : `VirtualScreen` (vidéo/replay — aspect verrouillé, placement restauré à la réouverture) ; `ContextCard` en opt-in ; les éléments **ancrés-objet** (task_anchor, PersonTag) ne sont jamais manipulables (ils suivent le monde). Placement/taille persistés par type (`PanelPlacementStore`, session).
- [x] Budget §9.4 tenu (pipeline gestes on-demand, zéro alloc/frame). Tests : 8 nouveaux EditMode, **suite complète 76/76**, zéro régression. ADR §E59.
- Restes : MenuPanel (surface logique sans géométrie propre — trivial quand il portera un GlassPanel) ; halo visuel pendant le drag (polish UI séparé) ; validation device.

## E61 — Clôture pré-production : 26 corrections finales + distribution APK (À FAIRE)

Source de vérité : audit statique transversal du checkout réel, relu et classé par le développeur le 2026-07-11. Une case ne sera cochée qu'après correction du chemin produit et preuve ciblée de la frontière concernée. Les points mono-propriétaire restent à scoper proprement mais sont de priorité basse ; l'absence de secret de pairing reste une décision assumée hors de ce lot.

### E61-A — Life Model, prédictions, Self Schema et temps local

- [x] **01 — Producteur Life Model V19 réel** : produire des `life_model_entries_v19` nouvelles depuis les faits/deltas nocturnes du jour, avec evidence refs et contrat LLM strict ; ne plus dépendre d'un amorçage par test/simulateur.
- [x] **10 — Calibration prédictive causale** : ne plus étiqueter arbitrairement les deux derniers observed cases ; relier une vérification/réfutation à la vraie paire de cas concernée, sinon enregistrer un skip explicite sans modifier la calibration V18.
- [x] **11 — Self Schema réellement reconstruit** : retirer/invalider les projections dont la source Life Model/pattern n'est plus active au lieu de faire uniquement des upserts.
- [x] **12 — Causalités owner-scopées** : empêcher les `causal_edges` d'une autre personne d'entrer dans `self_schema_v19` ; si la table reste sans `person_id`, prouver l'appartenance via les lignes sources.
- [x] **13 — Lien durable prédiction → entrée source** : persister `source_entry_id` dans `predictions_v19` et l'utiliser pour les contradictions, jamais l'égalité fragile du texte `statement`.
- [x] **14 — Temps civil cohérent** : interpréter replay, journée Life Model et horizons de prédiction dans `MLOMEGA_LOCAL_TZ` puis convertir en UTC, y compris DST et bords de minuit.
- [x] **15 — Sorties nocturnes vides observables** : conserver la preuve non circulaire, mais produire au minimum un warning/gate sémantique lorsque des entrées éligibles existent et qu'un stage Life Model/prédiction/Self Schema retourne zéro sortie ; vérifier aussi les rollups week/month dus.

**Avancement E61-A (2026-07-11 — code clos)** : le stage V19 projette désormais, de façon idempotente et sourcée, les neuf familles du magasin canonique V15.10/V15.13 réellement produit la nuit ; aucun seed V19 n'est nécessaire. Les prédictions portent leur `source_entry_id`, la calibration n'écrit un label que si le spec fournit une vraie paire de cas causale, le Self Schema retire ses sources invalidées et ne garde que les causalités dont l'owner est prouvé. Replay/Life Model/horizons utilisent la journée civile `MLOMEGA_LOCAL_TZ` convertie en UTC. CloseDay relit aussi les entrées projetées et conserve des warnings sémantiques pour sorties vides/rollups non observés. Validation ciblée : **29 passed, 1 skipped TTS local indisponible** (`test_e61_memory_integrity`, Life Model, replay E35, mémoire E16→E20, preuve CloseDay).

### E61-B — Sorties utilisateur PhoneOnly

- [x] **02 — Replay média bout-en-bout** : ajouter les routes tokenisées `/replay/media/{kind}/{id}`, résolution owner/session, lecteur images/vidéos Unity et chargement réel dans `VirtualScreen.SetSurfaceTexture`; jamais d'octets média sur le DataChannel.
- [x] **03 — LensWindow = vrai zoom** : fabriquer/résoudre le crop texture depuis centre+facteur, l'afficher dans `LensWindow.SetContentTexture` et conserver le chemin local PC coupé.
- [x] **04 — Sélection réelle du MenuPanel** : produire l'index sur gaze ou position de pincement par hit-test des lignes, avec dwell/pinch réellement déclenchables dans la scène produit.
- [x] **05 — Actions menu vers le routeur PC** : raccorder Mémoire, Ma voix, Replay, Écran virtuel et mode payant/local à une commande montante consommée par l'unique `IntentRouter`; conserver les actions purement device en local.
- [x] **06 — Confidentialité effective** : `privacy_pause` doit stopper/suspendre caméra, micro, ASR et émission transport, puis reprendre proprement sans double propriétaire ; le StatusBar reflète l'état réel et non l'inverse.

**Avancement E61-B (2026-07-11 — code clos)** : les bundles replay restent bornés sur le DataChannel puis leurs refs sont résolues par une route HTTP authentifiée ; `UIRuntime` séquence images et MP4 dans le vrai `VirtualScreen`. LensWindow applique un `uvRect` centre/zoom sur la texture capture vivante, donc le grossissement est un crop GPU réel, y compris local. Le pinch menu est désormais hit-testé sur le `RectTransform` des lignes et ces zones ne sont plus volées par `PanelManipulator`. Les cinq actions PC montent comme `device_intent` structuré ; Mémoire et Replay demandent naturellement la question/l'heure au tour vocal suivant. Enfin privacy stoppe caméra, WebRTC/micro et Reflex, suspend le watchdog PC, puis reprend la même session via un bouton local explicite. Validation PC ciblée : **66 passed, 1 test cloud réel désélectionné**. Le runner Unity a été lancé mais s'est arrêté avant import/compilation (`No valid Unity Editor license found`, exit 1) : rafraîchir Unity Hub puis relancer E33/S25 ; les cases représentent le code clos, pas le gate téléphone.

### E61-C — Companion, lunettes et reconnexion

- [x] **07 — Companion-web produit continu** : servir réellement les assets web, démarrer le WebSocket delivery, lancer la boucle `dispatch_once` continue et prouver navigateur réel → receipt, sans remplacer le viewer par SimOnly.
- [x] **08 — XREAL produit honnête** : fournir une scène/build lunettes portant la chaîne produit complète, ou limiter explicitement l'APK à G1 et corriger toutes les promesses README/FIRST_TRY ; ne jamais appeler le gate G1 « identique au téléphone ».
- [x] **18 — Re-offer WebRTC mono-peer** : lors d'une renégociation, fermer/remplacer l'ancien peer ou isoler strictement les tracks ; empêcher audio dupliqué, plusieurs downlinks et origine PTS partagée entre anciens/nouveaux tracks.
- [x] **19 — Resolver Python aligné sur `/health`** : accepter le contrat courant `pairing_ready/full_ready` et couvrir le failover fake-device/outils sans affecter Unity.

**Avancement E61-C (2026-07-11 — code clos)** : `RUN -LivePhone` lance aussi le serveur companion :8706, vérifie son health, sert les vrais assets et arrête proprement le process avec SessionHub ; son lifespan dépile la queue toutes les 500 ms, même sans reconnexion. Le navigateur accepte le health `pairing_ready/full_ready` avec CORS GET. Le builder XREAL régénère maintenant `XrealProduct.unity` avec pairing, capture, WebRTC, SceneCache/UI, Reflex, menu/aide/replay et modèles embarqués ; `G1Gate` reste un diagnostic séparé, l'artefact produit devient `mlomega-xreal.apk`. Chaque re-offer est sérialisée, ferme l'ancien peer/canaux avant de réinitialiser PTS, et le resolver Python reconnaît le contrat health E60. Validation ciblée : **33 passed** + parse PowerShell/py_compile. Compilation/build Unity à relancer après reconnexion Hub ; aucune APK nouvelle n'est revendiquée dans ce lot.

### E61-D — Durabilité, ownership et surfaces historiques

- [x] **09 — Reprise atomique end-session → CloseDay** : créer durablement le marqueur/job de recovery avant ou dans la même transaction que le passage BrainLive à `ended`, afin qu'un kill dans cette fenêtre soit repris.
- [x] **16 — Replay keyframes owner-scopé** : rattacher `vision_frames` à la personne/session avant sélection ; aucune image d'un autre owner dans un bundle.
- [x] **17 — MediaRetention owner-scopée** : filtrer inventaire, références, transcodage, tiering, purge et quota par propriétaire/session malgré le mode `me` actuel.
- [x] **26 — API V18 historique explicitement dépréciée** : marquer `mlomega_audio_elite.api` comme surface legacy non lancée, documenter les remplaçants CLI/dashboard/SessionHub et empêcher qu'une route dormante soit prise pour un chemin produit.

**Avancement E61-D (2026-07-11 — code clos)** : le job `phoneonly_session_recovery_v19` est désormais committé avant le premier appel capable de passer BrainLive à `ended`; le CloseDay normal le clôt et le recovery de démarrage reprend aussi une session déjà ended. `vision_frames` migre avec `person_id`, backfillé via `brainlive_sessions` et isolé en `unscoped_legacy` sinon ; tous les writers, replay bundle et route média utilisent cet owner. MediaRetention filtre inventaire, evidence, FK clips, audio, transcodage, purge et quota par owner, de sorte qu'un autre propriétaire ne protège ni ne perd les médias courants. Enfin `mlomega_audio_elite.api` émet une dépréciation et refuse son startup sans `MLOMEGA_ENABLE_LEGACY_API=1`; SessionHub/dashboard/CLI sont indiqués comme remplaçants. Validation ciblée : **65 passed**.

### E61-E — Installation, Doctor et builds reproductibles (code clos)

- [x] **20 — Préflight CloseDay réel** : exécuter avec `.venv` une sonde bornée des imports/configs nocturnes, WhisperX/pyannote/token HF et entrypoint `run_phoneonly_close_day`, pas seulement tester l'existence de `python.exe`.
- [x] **21 — Doctor sur le vrai env et la vraie base** : charger `.env`, utiliser `MLOMEGA_DB/MLOMEGA_MEDIA`, exécuter les contrôles cœur avec `.venv` et refuser les fallbacks silencieux vers `data/memory.db`/`data/evidence`.
- [x] **22 — Rollback `.venv-live` réellement disponible** : conserver `.venv-live.previous` jusqu'à la fin de toutes les étapes critiques/Doctor, restaurer sur échec, puis seulement supprimer la sauvegarde.
- [x] **23 — FAIL Doctor bloquant** : distinguer WARN acceptés et FAIL critiques ; un FAIL final doit rendre INSTALL/WELCOME non-zéro et interdire le message « installation terminée ».
- [x] **24 — Python 3.11 explicite dans WELCOME** : créer `.venv` avec l'interpréteur 3.11 64-bit résolu (`py -3.11`/chemin vérifié), jamais le premier `python` du PATH.
- [x] **25 — Builders Unity hermétiques** : le build PhoneOnly retire `XREAL_SDK_PRESENT`, le build XREAL retire `MLOMEGA_PHONE_ONLY`, et chaque cible reconstruit sans dépendre d'un revert Git préalable.

**Avancement E61-E (2026-07-11 — code clos)** : `check_close_day_preflight.py` tourne dans le vrai `.venv` et refuse toute création/fallback implicite ; il vérifie Python 3.11/64-bit, dépendances deep audio, imports CloseDay, token HF, entrypoint, ffmpeg, SQLite en lecture seule et racine média configurée. `/ready` exécute cette sonde bornée au lieu de regarder seulement `python.exe`. Doctor charge `.env` sans écraser les overrides, sépare interpréteurs live/cœur et chemins evidence/media, et ses requêtes SQLite conservent désormais leurs guillemets sous Windows. WELCOME résout explicitement Python 3.11, initialise les vraies racines/DB, garde le venv précédent jusqu'au Doctor et restaure sur toute erreur ; INSTALL/WELCOME sortent non-zéro au premier FAIL. Les deux builders retirent le define de l'autre cible. Validation : parse PowerShell des trois scripts, **41 passed**, préflight cœur réel `ready=true`, puis `DOCTOR -Full` **0 FAIL / 4 WARN** (Qdrant/Ollama volontairement arrêtés, voix owner à enrôler, XR matériel non branché). Aucun APK n'est rebâti dans ce lot de scripts/builders ; le gate S25 reste transversal.

### E61-F — Distribution APK via WELCOME

Constat (2026-07-10) : les APK sont git-ignorées (artefacts locaux, ~90+191 Mo) → un utilisateur qui CLONE le repo n'a aucun APK ; WELCOME affiche un chemin vide et l'utilisateur devrait builder lui-même (Unity + licence = irréaliste pour un non-dev). Solution long terme, tout passe par WELCOME :

- [ ] **APK PhoneOnly = GitHub Release** : publier `mlomega-phoneonly.apk` en asset de Release (PAS dans git) à chaque build significatif, avec SHA-256 dans les notes. WELCOME (étape téléphone) : si l'APK locale est absente → `Invoke-WebRequest` de la dernière Release (même mécanique que le download Qdrant), vérif SHA-256, puis guide `adb install -r`/copie. Nuance endpoint : l'APK publiée embarque un endpoint LAN par défaut — documenter que le pairing sonde la liste d'endpoints du profil (et/ou publier une APK « generic » dont l'endpoint est configurable au premier lancement — à trancher à l'implémentation).
- [x] **APK lunettes = JAMAIS publiée** (SDK XREAL propriétaire embarqué). À la place, WELCOME branche lunettes = **build assisté local** : (1) guider le dépôt de `com.xreal.xr.tar.gz` dans `Packages/xreal-sdk/` (lien compte dev XREAL), (2) vérifier Unity 6000.0.23f1 + licence (détecter, guider l'activation Hub sinon), (3) lancer lui-même les 2 passes (`AndroidBuildXreal.PrepareDefines` puis `BuildApk`) avec suivi de progression et messages d'erreur clairs, (4) installer l'APK produite. L'utilisateur ne tape aucune commande Unity.
- [x] **Config XREAL par WELCOME** : les choix lunettes (endpoints, wake word, profil display xreal) déjà posés par l'assistant doivent alimenter le build assisté (endpoint injecté via `MLOMEGA_PC_HOST/PORT`, asset MLOmegaConfig) — zéro édition manuelle d'asset.
- [x] Idempotent + dégradé honnête : pas de réseau → chemin local seulement ; pas d'Unity → PhoneOnly Release proposée, lunettes expliquées comme nécessitant Unity ; jamais de demi-échec silencieux.
- [x] Test : dry-run WELCOME sur checkout SANS APK → propose le download Release (phone) / le build assisté (lunettes) sans erreur.

**Avancement E61-F (2026-07-11 — code/build clos, publication Release en cours)** : WELCOME appelle un downloader dédié lorsque l'APK PhoneOnly est absente ; il exige les deux assets APK+sidecar, compare SHA-256 avant bascule et échoue honnêtement hors réseau. Pour XREAL, le helper deux-passes vérifie SDK/Unity/instance ouverte, injecte l'endpoint choisi, distingue licence expirée/compile, produit `mlomega-xreal.apk` et restaure exactement les artefacts Unity préexistants. Le rebuild final a découvert deux dépendances réellement absentes du player E61-B (`com.unity.modules.video` et `unitywebrequesttexture`) ; manifest, lock et asmdef sont corrigés. APK PhoneOnly fraîche : **94 759 838 octets**, SHA-256 `C569EE4596B7E47B755FB8AA027E242577F48C140F6EBD1378C84DCE0EFB975B`. APK XREAL produit fraîche : SHA-256 `945F5D38AC9E3FB72A905B371A5BF20BA2144672D2AB61111A31EB774D360DDF`. Validation : deux builds Unity exit 0, parse PowerShell, **12 tests ciblés**. La première case sera cochée uniquement après création et relecture de la Release distante.

## E53 — Mode aide universel « Viki mode aide » (ARCHI VALIDÉE 2026-07-09 — à implémenter par phases)

« Aide-moi à faire X » (cuisiner, monter un meuble, réparer…) fait BIEN. **Périmètre : tâches PHYSIQUES au niveau OBJET+GESTE.** Les tâches écran/logiciel sont écartées (décision utilisateur : trop long) ; le geste sub-objet fin (« LA vis B4 ») reste la frontière (Phase C, plus tard).

### Le flux (UX cible)
« **Viki, mode aide** » → tu décris le problème → Viki : « *t'as une notice/un plan, ou je t'en fais un ?* » → si notice : elle la **scanne** (VLM document, extraction ~95 %) ; sinon : **recherche web** + génère → **plan d'étapes TYPÉES**. Puis on avance **ensemble** : elle suit où tu en es, te montre le prochain geste, et **proactivement** te débloque. Mode **opt-in cloud (gpt5.4-mini)** avec **coût affiché en live** (mécanique E33).

### La règle d'or latence : séparer le lent du rapide (jamais le cloud dans la boucle d'affichage)
| Couche | Latence | Qui | Rythme |
|---|---|---|---|
| **Plan** (les étapes) | lent OK (~1-2 s) | cloud gpt5.4-mini | 1 fois au début |
| **Reconnaissance d'objet** (« où est le bol », le QUOI+où sémantique) | **~100-250 ms** | **PC RTX 3070 en LAN** (YOLOX/VisionRT, workhorse) ; dehors via **Tailscale** (un peu + haut, viable) | continu (4-10/s) |
| **Ancrage de l'UI** (collée au réel quand la tête bouge) | temps réel | **téléphone** (tracker local StableTrack, optical flow) | chaque frame, on-device |
| **Vérif « fait » / « bloqué » / hors-plan** | 1-2 s | cloud, **event-driven** | quelques appels/tâche |

Principes qui tuent la latence :
- **Ancrage SÉMANTIQUE, jamais coordonnées cloud fixes** : le cloud/PC dit « bol » ; le **téléphone reconnaît/track le bol et pose l'UI dessus en temps réel** → l'UI reste collée même quand tu bouges (lunettes = tête mobile). Ré-acquisition après sortie de champ : PC re-détecte (LAN rapide) ou petit détecteur on-device.
- **Étape N+1 PRÉ-CALCULÉE** pendant l'étape N (on a le plan) → transition **0 latence perçue**. Le cloud 1-2 s ne mord que sur l'**imprévu** (hors-plan).
- **Cloud déclenché par le LOCAL** : signaux locaux (changement de scène / main active / pas de progrès / hésitation) → on n'appelle gpt5.4 que là. Proactif ET pas cher (quelques centimes/tâche, pas 1 img/s H24).

### L'UI bank (beau ≠ « surligner ») — des ATOMES qui se composent
PAS 12 tâches codées en dur : ~12 **atomes glass réutilisables** qui se **combinent** pour couvrir un **ensemble OUVERT** de tâches (cuisine, montage, réparation, jardinage, brancher un appareil, instrument, sport, soin…). Chaque tâche = un assemblage d'atomes piloté par l'étape typée (`action`, `objet`, `quantité`, `zone`, `geste`, `next`). Extensible si un domaine le demande. Atomes :
- **ancre-objet** (anneau/contour **qui SUIT l'objet** — si tu prends/déplaces le bol, l'UI le suit en temps réel, jamais collée à un point fixe) · **trajectoire/geste** · chip quantité/mesure · **anneau-minuteur** · panneau d'étapes (fait/en cours/suivant) · flèche directionnelle (objet hors-champ) · encart zoom · checklist · carte-instruction · cue d'attention/danger · **sélection** (« prends celui-là parmi plusieurs ») · barre de progression.
- **Primitive « geste » = TRAJECTOIRE animée** (beau + tractable, PAS une main 3D) : tracé glowing qui se dessine, ancré sur l'objet — verser = arc bouteille→bol ; visser/tourner = flèche circulaire ; essuyer = va-et-vient ; appuyer = pulse. La **main-fantôme réaliste** = option premium plus tard.

### À implémenter (par phases — « bien ou pas du tout ») — **PHASE A FAITE (2026-07-10, commits dcc4af4 + 98e9adf ; validation device en attente)**
- [x] **Schéma d'étape typée** figé (TaskPlan/TaskStep : action, objects[name/label_en/role/quantity], gesture{kind,from,to}, timer, caution, done_when). **Évolution utilisateur intégrée : chaque step = UNE MICRO-ACTION = UN GESTE affichable** (les étapes composites sont interdites par le prompt).
- [x] **Acquisition du plan** (`help_mode.py`) : intents « (viki) mode aide » / « aide-moi à X » (grammaire AVANT les règles génériques + high-confidence + LLM schema + multi-tour description) → **UN coup d'œil VLM initial sur la keyframe courante** (devine le problème/objets visibles → le plan colle à la scène réelle, utile en plein milieu d'une activité) → plan LLM (local ou gpt-5.4-mini si mode payant, coût affiché E33) ; chemin notice = `plan_from_document` (VLM doc). Persistance sqlite additive + reprise (« reprends la tâche »).
- [x] **Moteur de tâche PC** : machine à états (advance/repeat/go_to/pause/resume/finish à la voix — pré-routeur actif pour ne jamais voler « c'est fait » hors tâche), **pré-push fantôme de N+1** (0 latence perçue), émission `task_panel`/`task_anchor` par la queue H1/hot existante, tick câblé sur la cadence scène.
- [ ] **Reco objet on-device** (détecteur MediaPipe/ONNX léger, mode dégradé dehors sans PC) — SEUL reste de Phase A ; le chemin principal (PC VisionRT LAN) est câblé.
- [x] **Ancrage device** : grounding PC joint `track_id` par `label_en` → `ObjectAnchorRing` SUIT le track en temps réel (perte → mode recherche → réacquisition ; hors-champ → `TaskDirectionalArrow`).
- [x] **UI bank glass** : 12 atomes composables livrés (`TaskAtoms/`) + 2 composants registre E25 (`task_panel`, `task_anchor` = cerveau de composition). Trajectoire-geste animée arc/circular/linear/pulse. EditMode 9/9.
- [x] **Proactif** : watchdog pas-de-progrès (indice local, puis UN indice visuel cloud si payant+autorisé). Validation voix (« c'est fait ») ; auto-validation fine = Phase C.
- [x] **Coût live** : gpt-5.4-mini opt-in via LLMRouter E33 (clé demandée dans WELCOME, fallback local honnête).
- **Phasage** : **A** = objet+geste physique (cuisine/rangement/branchement) fait bien → **B** = tâches d'assemblage (pièces/repères) → **C** = geste fin sub-objet (attend les VLM spatiaux). Refs d'inspi : HoloAssist (dataset AR assistance MS), IKEA Place / overlays « how-to » AR, Set-of-Mark/OmniParser pour le grounding par éléments.
- Gate qualité avant de livrer une phase : sur 10 scènes réelles S25, ancrage objet correct ≥ 90 % et transition d'étape < 300 ms perçue.

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

## E60 — Corrections d'intégration pré-production (EN COURS — 2026-07-10)

Source de vérité : appels réellement présents dans le checkout. Une case cochée signifie désormais **correction code terminée et test ciblé vert** ; la validation S25 n'est plus répétée dans chaque case et reste le gate produit transversal explicite en fin de section. Les choix de conception acceptés sont conservés, avec les durcissements demandés.

- [x] **01 — Déclenchement Reflex production** : produire les `ReflexSignal` réels et prouver le démarrage automatique d'ASR, wake word, sous-titres, gestes, traduction et skills, sans injection de test.
- [x] **02 — Menu PhoneOnly + finition E59** : construire le `MenuPanel` dans la scène avec une vraie surface `GlassPanel`, raccorder `MenuGestureController`/`MenuRequested`, le rendre manipulable avec bornes réelles et ajouter halo/ombre glass + snap doux pendant grab/resize.
- [x] **03 — TTS PhoneOnly bout-en-bout** : activer le TTS dans le runtime, consommer `tts_audio` dans Unity et jouer le WAV borné, avec repli texte honnête.
- [ ] **04 — APK et scène reproductibles** : imposer `com.mlomega.xr.phoneonly`, aligner `adb`/FIRST_TRY et reconstruire la scène même si elle existe afin d'embarquer réellement les composants récents (dont E53/E59).
- [x] **05 — ClipRecorder productisé** : `PhoneOnlyRuntime` construit/démarre le recorder avec l'ID BrainLive, le fournit à l'ingress aiortc, puis le stoppe/joint avant CloseDay ; tests produit + encode/index/replay E55 prouvent la file bornée sans back-pressure live.
- [x] **06 — Reflex offline à froid** : utiliser le micro natif `ownMicrophone=true` quand le PC/PCM WebRTC est absent, puis basculer sans double `AudioRecord` quand le transport revient.
- [x] **07 — Fin de session null-safe** : protéger `ActiveBaseUrl`, perte réseau et état `Paired` obsolète afin que `EndExplicitly()` reste utilisable et observable.
- [x] **08 — Multi-session/jour durable** : `SinglePhoneRuntimeManager` relit la ligne `v18_close_day_runs(person_id, journée locale)` ; une instance neuve après restart arme `allow_rerun` si le jour est déjà `completed`, avec test sur base persistée.
- [x] **09 — Chemin vidéo téléphone performant** : activer le chemin texture/native prévu, conserver la conversion CPU comme fallback E44 et mesurer thread Unity, chauffe, batterie et latence S25.
- [x] **10 — Rotation capture réelle** : instancier/raccorder `OrientationGuard` et appliquer rotation/mirror au flux transmis à VisionRT/gestes, pas seulement à l'aperçu.
- [x] **11 — Continuité arrière-plan** : activer `runInBackground`, empêcher la veille pendant une session active et gérer pause/reprise/wake lock sans laisser tourner hors session.
- [x] **12 — Cycle de vie PCM** : conserver le sink attaché, appeler `DetachPcmFeed` à la désactivation/reconnexion et garantir un propriétaire unique.
- [x] **13 — Push wake word fiable** : envoyer dès l'ouverture DataChannel, marquer après succès/ack et réessayer de façon bornée après course ou reconnexion.
- [x] **14 — `pose_valid` bout-en-bout** : champ ajouté au schéma source puis au C# généré/copie Unity ; `EyeCaptureSource` sérialise `StampedPose.IsTracking`, PhoneOnly envoie donc false et le garde Python exclut la pose de SpatialRT.
- [x] **15 — Gating corrélé** : relier `is_command` au transcript PC correspondant par ID/timestamps ; conserver explicitement le mode compatibilité `open` sans autoriser la phrase suivante par erreur.
- [x] **16 — Audio sans perte sous charge** : découpler capture et traitements Whisper/identité/IntentRouter/BrainLive, dimensionner/backpressurer honnêtement et mesurer les drops en conversation continue.
- [x] **17 — Timestamps audio réels** : le PTS/time_base WebRTC est ancré par track à l'UTC, traverse AudioRT et alimente archives + `ConversationBridge.ingest_segment(timestamp_start/end/duration_s)` ; fallback `receive_clock`/`processing_clock` est explicite.
- [x] **18 — Vision hors boucle asyncio** : détection/tracking/WorldBrain/SQLite/keyframes passent par `asyncio.to_thread` derrière la file vidéo latest=1 ; test de frontière prouve un thread distinct de l'event loop.
- [x] **19 — GPU réellement arbitré** : `GpuArbiter` est construit et `update_degraded` reçoit VRAM+drops de fenêtre ; install pin ORT GPU 1.22/CUDA12 + runtime/cuFFT/cuBLAS/cuDNN, préchargement DLL, Doctor ouvre une vraie session YOLOX. Validation réelle : `['CUDAExecutionProvider','CPUExecutionProvider']`, `on_gpu=True`.
- [x] **20 — Erreurs BrainLive visibles** : ingestion BrainLive retentée trois fois puis remontée ; WorldBrain, spatial, keyframes, archives, attributs/hypothèses et callbacks visuels alimentent `pipeline_recent_errors`/métriques au lieu d'être silencieux.
- [x] **21 — Fermeture LiveDiscourse jointe** : les lots pleins sont différés sans perte, le close pose une barrière ordonnée, draine puis `join` le worker ; timeout lève une erreur et interdit CloseDay.
- [x] **22 — CloseDay de secours** : activité média horodatée + watchdog d'inactivité, lifespan shutdown drainé, et reprise startup durable dans `phoneonly_session_recovery_v19` ; une coupure entre end et CloseDay reste retryable sans double consolidation.
- [x] **23 — Lanceur avec readiness** : `RUN -LivePhone` exécute le préflight strict avant SessionHub et refuse avec commandes correctives si DB/venv nuit/modèles/CUDA/Whisper/TTS/Ollama/Qdrant/ffmpeg/disque ne sont pas prêts.
- [x] **24 — `/health` honnête** : `/live` = liveness, `/health` expose séparément `pairing_ready` et `ai_ready`, `/ready` retourne 503 tant que la chaîne profonde asynchrone n'est pas complète ; recovery startup bloque le pairing.
- [x] **25 — Pairing sans secret conservé (audit original 24, décision utilisateur)** : aucun secret/code préalable ajouté. Le modèle LAN/Tailscale personnel + token de session reste volontairement inchangé ; ne pas rouvrir ce point comme bug E60.
- [x] **26 — Aucun `seg_*.wav` perdu dans `%TEMP%`** : aucun temp n'est créé pour l'archive seule ; les WAV nécessaires à l'identité/setup sont supprimés après consommation, tandis qu'AudioArchive écrit sa copie dans le stockage média géré.
- [x] **27 — Identité objet durable** : registre owner-scoped `worldbrain_entity_registry_v19`, IDs indépendants du transport/session, réassociation prudente type+label+bbox et slots distincts pour objets homonymes ; tests sur restart et deux objets identiques.
- [x] **28 — Journée visuelle locale** : bornes civiles `MLOMEGA_LOCAL_TZ` (Europe/Paris par défaut) converties en fenêtre UTC semi-ouverte, créneaux matin/après-midi/soir calculés en heure locale et tests aux deux bords de minuit.
- [x] **29 — Manifeste CloseDay non circulaire** : contrat statique des dix stages, relecture de leurs checkpoints et vérification owner-scoped de chaque ID dans sa vraie table ; manifeste incomplet bloque `cleanup_eligible`.
- [x] **30 — Rétention observable faite, preuve device ouverte** : tiering/transcode/purge/quota sont persistés dans `phoneonly_close_day_maintenance_v19` et remontent comme `completed|warning|error` au runtime sans invalider le CloseDay ; reste à produire la preuve téléphone→Live→BrainLive→CloseDay sur S25.
- [x] **31 — E53 activé et contrat PC→Unity aligné** : activation PhoneOnly réelle ; `task_panel`/`task_anchor`, liste d'étapes, IDs stables, persistance, watchdog et H1/hot sans doublon, test traversant DataChannel puis registre Unity.
- [x] **32 — E58 fiable de bout en bout** : accepter E58 seulement lorsque les points 13 et 15 passent avec mauvais mot, mot changé, expiration, reconnexion et parole ambiante.

**Gate final E60** : APK reconstruite depuis la scène générée, puis matrice S25 réelle FirstTryAndroid (LAN, perte/reconnexion, arrière-plan/écran éteint, mauvais token, second device, wake word changé, Reflex/gestes/traduction, TTS, clips, E53, BrainLive et CloseDay/reprise même jour). Aucun test synthétique ne clôt ce gate matériel.

**Avancement lot Android A (2026-07-10, code clos ; 04 attend le rebuild APK)** : `PhoneOnlyReflexSignalSource` émet réellement les baselines speech+gestures pendant une session ; le builder ajoute MenuPanel glass + MenuGestureController + OrientationGuard ; le menu est `IManipulablePanel` avec bornes, halo/rim, ombre et snap doux ; le package PhoneOnly est forcé et la scène est toujours régénérée ; fin de session null-safe et veille interdite seulement pendant la session. Compilation Roslyn avec les `.rsp` Unity réels : Transport/UI/Reflex/Editor/Tests OK. Runner Unity réel après rafraîchissement de la licence Hub : **80/80 EditMode**, puis **22/22** ciblés manipulation/E53/refresh. Les messages `[Licensing] Error Code 500`/ULF du log n'ont pas été pris comme verdict : résultat XML et fin de processus font foi. Le rebuild APK reste le dernier livrable code/build avant le gate S25 transversal.

**Avancement lot audio B (2026-07-10, code clos ; validation device au gate transversal)** : PhoneOnly active le provider TTS et Unity consomme/joue le WAV `tts_audio` borné ; ASR choisit micro autonome sans PC puis bascule vers le PCM WebRTC sans double `AudioRecord`, en conservant/détachant le sink ; wake word poussé à l'ouverture, identifié, acquitté par Unity et retenté tant que non confirmé ; le transcript Android exact est routé en mode gated et le transcript PC correspondant reste mémoire-only. Validation : pytest ciblé **26 passed** ; Gradle/Kotlin + AAR reconstruits ; Roslyn Editor **et Android** OK ; suite Unity globale **80/80 EditMode**. Le S25 reste le gate matériel transversal.

**Avancement lot PC live C (2026-07-10 — 05/16/17/18/21/26 code clos ; 19/20 clos par le lot D ci-dessous)** : le recorder E55 est enfin construit sur le vrai runtime et fermé avant la nuit ; l'audio aiortc dispose d'environ 60 s de tampon borné, transmet l'horloge PTS et déporte les traitements sémantiques ordonnés hors du worker PCM ; BrainLive retente trois fois et remonte ses erreurs, WorldBrain/archive remontent les leurs ; la vision synchrone quitte asyncio ; LiveDiscourse est une vraie barrière jointe ; les WAV d'identité temporaires sont nettoyés. Validation sur fichiers distincts : **50 passed**, puis routes SessionHub/WebRTC/E27/E31/multi-session **24 passed, 1 skipped** (Ollama réel opt-in). La mesure longue audio/drops appartient au gate S25 transversal.

**Avancement lot durabilité/GPU D (2026-07-10 — 08/14/19/20 clos)** : le restart du service ne perd plus l'information multi-session/jour ; `pose_valid` est un vrai champ contractuel généré et PhoneOnly sérialise false ; les erreurs des writers live/visuels sont comptées et remontées. Le premier essai GPU a volontairement réfuté le faux positif « provider listé » : ORT 1.27 réclamait CUDA13 et la session YOLOX retombait CPU. Pin corrigé à **ORT GPU 1.22.0/CUDA12**, dépendances runtime+cuFFT ajoutées, DLL préchargées et Doctor durci pour construire le modèle réel. Résultat machine : session YOLOX `CUDAExecutionProvider`, `on_gpu=True`. Validation : Python **51 passed**, Unity réel **80/80 EditMode**, parse PowerShell OK, `DOCTOR -Vision` **0 FAIL / 2 WARN** (Qdrant et Ollama arrêtés — traité au lot readiness, pas masqué).

**Avancement lot recovery/readiness E (2026-07-10 — 22/23/24 clos)** : le bouton reste le chemin normal, mais silence média prolongé ferme/drain/CloseDay ; un arrêt uvicorn fait de même ; un kill brutal laisse une ligne de recovery durable, reprise au démarrage suivant même si BrainLive avait déjà été marqué ended. L'état `running/error` interdit un nouveau WebRTC. Le health ne confond plus pairing et IA ; le probe profond est asynchrone pour ne pas bloquer Android et charge réellement YOLOX, Whisper CUDA et TTS. `RUN -LivePhone` lance ce gate avant le serveur. Validation : **39 passed**, rerun lifespan **29 passed** ; preflight profond machine = YOLOX CUDA, Whisper `small` CUDA, TTS sherpa, DB/modèles/ffmpeg/disque/venv nuit OK, refus attendu uniquement sur **Ollama et Qdrant arrêtés**. FIRST_TRY donne les commandes de correction ; aucun faux prêt.

**Avancement lot durabilité nocturne F (2026-07-10 — 27/28/29/30 code clos ; preuve S25 au gate transversal)** : WorldBrain ne fabrique plus d'ID à partir du `live_session_id` et conserve un registre propriétaire inter-session avec slots homonymes ; la consolidation visuelle prend la journée civile Europe/Paris, y compris DST, puis convertit ses bornes en UTC ; CloseDay construit son attendu depuis le contrat des dix stages mais son observé uniquement après relecture des checkpoints et des lignes owner-scoped dans leurs tables. Les maintenances média gardent le choix best-effort, tout en écrivant durablement leurs erreurs/warnings et en les exposant dans `/metrics`. Validation : **25 passed** cœur/durabilité et **41 passed** dans `.venv-live` (aiortc/CUDA), dont preuve négative d'un ID retourné mais absent de sa table.

**Avancement lot raccord E53/menu G (2026-07-10 — 02/31 clos)** : PhoneOnly active réellement HelpTaskEngine. Le panneau H1 conserve `component=task_panel`, son contrat `steps/status/progress/ghost_next`, son TTL et son ID stable ; il n'est plus doublé par le renderer direct. Les ancres partent en vrais `UIIntent task_anchor`, avec IDs stables ghost→current, grounding source/cible et promotion invisible en place côté Unity. Le broker notifie désormais UIRuntime lors d'un refresh même-ID. La persistance utilise la base produit et supporte le worker sémantique. « mode aide » attend ensuite n'importe quelle description libre (y compris un blocage en milieu de tâche ou une seule action) ; seules les phrases d'entrée/contrôle sont routées, aucun plan générique n'est codé en dur. Le `MenuPanel` réel possède en plus halo/rim, ombre et snap doux. Validation : **50/50 Python** et **22/22 Unity EditMode ciblés**.

## E63 — Harnais d'intégration bout-en-bout + passe chaos (FAIT — 2026-07-11 ; fichiers neufs uniquement, aucun fichier produit modifié)

Un faux device XR (`tools/harness/`) rejoue une session complète contre le VRAI code PC (`services/live-pc/sessionhub_http.py` + `phoneonly_runtime.py`) en WebRTC réel, puis vérifie l'empreinte DB. Client réseau pur : jamais d'import des modules produit pour le flux, lecture directe de la sqlite pour les assertions. Règle absolue respectée : **nouveaux fichiers seulement**, tout ce qui est découvert du produit est noté dans `tools/harness/BUGS_FOUND.md`, rien n'est corrigé.

- [x] **Protocole appris depuis le code** (jamais deviné) : pairing `POST /session/create`, signalisation unifiée `POST /webrtc/offer`, fin `POST /session/end` (déclenche close-day), `/session/status`, `/health` (`pairing_ready`/`ai_ready`), `/metrics`. Schémas DataChannel copiés du client Unity : `FrameEnvelope` (+`pose_valid`), `device_command_result` (ack du `set_wake_word` poussé par le PC), `device_transcript` (`is_command` route via IntentRouter).
- [x] **`fake_xr_device.py`** : pairing HTTP, `RTCPeerConnection` aiortc, `MediaPlayer(mp4)` poussant audio+vidéo au cadencement natif temps réel, DataChannel avec envoi périodique de FrameEnvelope/pose statique valide, réponse aux device_command, et scénario scripté `(t, message)` puis fin de session propre. CLI : `--media` (sinon mire+bip synthétique 60s via ffmpeg), `--host/--port`, `--scenario`, `--end-session/--no-end-session`, `--duration`.
- [x] **`scenarios/basic_session.json`** : intents principaux (what_is, où est X, lis le texte, enrôlement « retiens c'est Karim », question mémoire, rejoue, cache tout/affiche tout).
- [x] **`assertions.py`** : session enregistrée, session terminée proprement, pipeline audio traversé, clip vidéo indexé dans `visual_evidence_assets_v19`, intents scriptés joués ; avec `--with-close-day` : stages close-day `completed` + recovery `phoneonly_session_recovery_v19` `completed`. Rapport PASS/FAIL, code retour non-zéro si échec.
- [x] **`run_harness.py`** : démarre le serveur produit en subprocess (`.venv-live`, port test, `MLOMEGA_DB` sur base scratch) OU `--attach` sur un serveur déjà lancé ; joue le device, replie `/metrics`, exécute les assertions, tue proprement. Close-day lourd derrière `--with-close-day` (off par défaut).
- [x] **`chaos.py`** : (a) coupure réseau brutale + reconnexion → session BrainLive stable ; (b) kill -9 avant close-day → reprise recovery au redémarrage ; (c) Ollama éteint (env vers port mort) → dégradation propre sans crash ; (d) double fin de session → idempotence. Chaque scénario sur son propre serveur+DB (la politique mono-device garde le runtime actif jusqu'à la fin du close-day → un 409 sinon).
- [x] **Exécution réelle minimale prouvée** : `run_harness.py --port 8730 --duration 26 --synth-seconds 30` → **ALL PASS** (session enregistrée+terminée, audio traversé — 96 chunks + 1 segment de parole archivé, 1 clip indexé, 8 intents joués). `intents_routed=1`, `turns_routed=1`, `grammar_hits=1`. Pas de GPU requis en mode minimal (`ai_ready=false`, `pairing_ready=true` suffit).
- [x] **Observation produit notée (non corrigée)** — OBS-1 dans `BUGS_FOUND.md` : la première session sur une DB neuve remplit `recent_errors` de `no such table: brainlive_intervention_delivery_queue` (la table du `DeliveryAdapter` live n'est créée qu'au niveau du module core `v18_delivery`, pas au démarrage du pipeline live). Dégrade proprement (erreur avalée), interventions proactives silencieusement perdues à la 1re session seulement.

### Vidéo de test réelle (à filmer par l'utilisateur)

Découpage exact à respecter au tournage ; le scénario `tools/harness/scenarios/real_video_session.json` est déjà aligné sur ces timestamps (à lancer avec `run_harness.py --media <video.mp4> --scenario real_video_session.json --duration 305 --with-close-day`). **Wake word et gestes = NON testables par le harnais (device-side), réservés à la session réelle OnePlus.** La ligne « viki aide-moi » est délivrée par le harnais comme un `device_transcript` help_start à ~4:00 (t=240), en remplacement du chemin wake-word on-device.

- **0:00–1:30** conversation avec une personne visible (faits mémorisables : « demain je dois racheter des piles », « rendez-vous avec Karim jeudi 15h chez le dentiste », une promesse) → diarisation, mémoire, entités, Life Model, PersonTag.
- **1:30–2:30** table d'objets (téléphone, clés, bouteille, livre, tasse), panoramique lent 3–4 s/objet, puis poser les clés et les sortir du champ → détection, what_is, where_is (dernier vu).
- **2:30–3:00** texte en gros plan stable 5 s → OCR, lis le texte, traduis-le.
- **3:00–4:00** marche dans 2–3 pièces, retour dans la première avec un objet déplacé → tracking, changement de scène, ChangeAttention.
- **4:00–5:00** activité manuelle en vue subjective (ex. préparer un café) ; à ~4:00 l'utilisateur dit « viki aide-moi » → le scénario envoie le final ASR help_start à ce timestamp, coup d'œil VLM sur cette scène.

### Run vidéo réelle + close-day complet (2026-07-12)

Premier run du harnais contre une vraie vidéo (WhatsApp 301.6s, H.264 baseline + AAC) avec `--with-close-day`. Ce run a révélé 4 bugs (3 produit + 1 harnais), tous corrigés :

- **Produit — /session/end 500 (bloquant)** : `live_pipeline.drain_final_processing` lève `TimeoutError` quand le worker de tours finaux ne draine pas en 30s ; l'appelant `phoneonly_runtime.end_session_only` laissait remonter → HTTP 500, `close_day: not_started`, `recovery: not_started`. **Fix** : la fin de session ne peut plus échouer sur un timeout de drain — `end_session_only` attrape le `TimeoutError` autour des trois appels drainants (`flush_audio`, `end_session`, `release_live_resources`), le journalise, et continue (flush best-effort post-drain via le nouveau `end_session_after_drain_timeout`). Sémantique du drain inchangée. Détail OBS-2 dans `tools/harness/BUGS_FOUND.md`.
- **Produit — WorldBrain SQLite cross-thread (grave)** : `worldbrain._init_service_db` ouvrait la connexion sans `check_same_thread=False` ; `ingest_scene_delta` est appelé depuis les threads vision → 54 erreurs « SQLite objects created in a thread… », ingestion de scène morte. **Fix minimal** : `connect(..., check_same_thread=False)` + `threading.RLock` (`self._db_lock`) autour de tous les accès `self._svc_db`. OBS-3.
- **Produit — hypothesis_engine.note_turn (mineur)** : `float()` sur une confidence LLM sale (`'}}0'`) crashait le tour. **Fix** : helper `_safe_confidence` (try/except → 0.0, compteur `signal_parse_errors`, reporté une fois). OBS-4.
- **Harnais — flux média coupé à ~20s (NON RÉSOLU au 2026-07-12)** : sur chaque run avec `--with-close-day`, le média s'arrête à ~20s (≈1000 chunks audio) quel que soit le fichier (WhatsApp VFR original ET réencodé H.264/AAC CFR) et quel que soit le nombre de `MediaPlayer` (un seul, ou deux séparés audio/vidéo). Cause identifiée mais pas encore corrigée : la couche transport DTLS/SCTP d'aiortc côté faux device tombe à ~20s (`ConnectionError: Cannot send encrypted data, not connected`), ce qui coupe le média puis les événements scriptés. **Le log serveur est propre** (aucun rejet côté produit) → défaut côté harnais (aiortc), pas côté produit ; piste probable = famine de la boucle asyncio serveur pendant l'inférence vision (YOLOX) retardant les checks de consent ICE. Améliorations harnais déjà en place (non suffisantes) : `disconnected` non traité comme terminal ; deux `MediaPlayer` séparés ; logging non-silencieux des tasks. **Conséquence** : session affamée (~20s au lieu de 301s) → close-day `blocked` faute de données (assembly incomplet), jamais `completed`. À reprendre.

Non-régression ciblée verte (`tests/v19/test_e28_worldbrain.py`, `test_phoneonly_runtime.py`, `test_e27_pipeline.py`, `test_e34_proactivity.py` = 49 passed).

**Gate final E63** : exécution minimale (mp4 synthétique, sans close-day) = FAITE et verte. Run `--with-close-day` contre la vraie vidéo 5 min = **PARTIEL** : les 3 bugs produit ci-dessus sont corrigés et testés (la fin de session ne plante plus, WorldBrain thread-safe, parse LLM blindé), MAIS le close-day complet n'est PAS encore validé de bout en bout à cause du blocage média harnais à ~20s. OUVERT.

### Rectification E63 après simulation longue (2026-07-12)

La conclusion ci-dessus est désormais historique. La basse résolution et les deux `MediaPlayer` n'étaient pas la cause du décrochage à 20 s : le premier `device_transcript` exécutait IntentRouter/VLM synchroniquement dans la boucle aiortc, jusqu'à faire expirer ICE/DTLS. Les receipts sont maintenant sérialisés hors boucle et drainés à la fermeture. Preuve : le MP4 de 301 s traverse avec **14 857 chunks audio**. Le correctif provisoire qui avalait le timeout de drain était lui aussi faux (CloseDay dépassait encore le worker final) ; il est remplacé par un drain réel de 300 s et un échec fermé/retryable, sans BrainLive/CloseDay prématuré. Détails autoritaires : `tools/harness/BUGS_FOUND.md` OBS-2 à OBS-13 et `docs/EXECUTOR_BUILD_GUIDE.md` E63.

ASR nocturne réel prouvé jusqu'au bout de Deep Audio : WhisperX `large-v3` CUDA float16, alignement, Pyannote et SpeechBrain ECAPA, **40 tours**, stage `completed`. Le scénario scripté Viki/Help Mode à t=240 n'est **pas encore certifié fonctionnel** : le run interrompu n'a pas écrit son rapport final et aucune ligne `help_mode_tasks` n'est présente. Le harnais injecte un `device_transcript` et ne valide jamais le wake word on-device ; ces deux gates restent distincts.

## E64 — Orchestrateur nocturne LLM lossless et transversal (EN COURS — PASSATION 2026-07-13)

### Problème confirmé

Le premier passage nocturne réel atteint Brain2 avec une conversation raffinée de **985 pseudo-tours** : 40 tours Deep Audio et 945 observations `vision_context` frame-par-frame. Le bundle EpisodeBuilder fait **1 595 361 caractères** ; Qwen termine par `finish_reason=length`. Les preuves visuelles ne doivent ni être envoyées brutes dans un prompt unique, ni être supprimées/échantillonnées arbitrairement. Les essais provisoires « max 6 épisodes / max 8 éléments / 16 frames » ont été retirés avant commit.

Le problème est transversal : tout stage nocturne qui concatène un jour, une conversation, des frames, des épisodes ou les sorties de stages précédents peut dépasser son contexte ou sa sortie. E64 doit fournir une seule infrastructure de budget/fenêtrage/reprise/couverture. Chaque famille de stage fournit un adaptateur de domaine (requête source, prompt local, merge), mais ne réimplémente jamais l'orchestration.

### Invariants non négociables

- [ ] **Aucune perte de preuve** : lignes audio/vision/événements brutes immuables ; aucune limite `N premiers`, aucun sampling silencieux, aucune suppression pour rendre un prompt vert.
- [ ] **Provenance totale** : toute sortie LLM cite les `evidence_id`/table/digest sources ; une agrégation vidéo garde la liste ou le manifeste des frames/tracks qu'elle représente.
- [ ] **Aucun prompt hors budget** : estimation réelle prompt + schéma + sortie avant appel ; marge fixe sous le contexte du modèle, jamais dépendante d'un nombre d'éléments supposé.
- [ ] **Aucun partiel appliqué** : `length`, timeout, JSON invalide ou contrat invalide n'écrit aucune sortie cognitive active.
- [ ] **Reprise exactement une fois** : kill/restart reprend la fenêtre incomplète sans rejouer les fenêtres validées ni doubler épisodes/tours/sorties.
- [ ] **Owner/session corrects** : `person_id` toujours explicite ; transport session, BrainLive session et journée civile restent séparés.
- [ ] **CloseDay honnête** : un stage n'est `completed` qu'après relecture de ses sorties et un manifeste de couverture complet.

### E64-A — Inventaire et contrat commun des stages

- [x] Remonter avec `rg` tous les appels nocturnes LLM/VLM (`OllamaJsonClient`, `ollama_generate`, helpers `_llm_*`, Deep Vision, Brain2/V13, coordination, Life Model, longitudinal, reconciliation/live-ready). Produire une matrice : stage, table(s) source, unité atomique, ordre temporel, modèle/contexte, schéma de sortie, writer, stratégie de merge, comportement actuel sur troncature.
- [x] Créer un contrat `NightStageAdapter` commun : `stage_name`, `load_evidence`, `estimate_tokens`, `build_window_prompt`, `validate_window_output`, `merge_outputs`, `persist_outputs`, `verify_coverage`. Les prompts métier existants restent derrière ces adaptateurs ; l'exécuteur générique porte budget, retry, checkpoint et reprise.
- [x] Définir `EvidenceRef` stable et owner-scopé : `evidence_id`, `source_table`, `source_pk`, `modality`, `timestamp`, `digest`, `payload_kind`, `parent_refs`. L'ID ne dépend jamais d'une tentative LLM.

### E64-B — Réduction déterministe avant LLM, sans perte

- [x] **Audio** : tours atomiques WhisperX conservés intégralement avec timestamps, speaker/person et refs WAV/source ; aucun redécoupage au milieu d'un tour.
- [x] **Vision** : transformer les frames répétitives en `VisionChangeAtom` déterministes : apparition/disparition, changement de label/attribut, déplacement de track, changement de zone/scène, OCR, keyframe, interaction. Chaque atome référence toutes les observations/frame IDs couvertes ; les frames brutes restent en DB/replay.
- [x] Les états identiques consécutifs deviennent une plage `[first_seen,last_seen,count,digest,source_refs]`, pas 300 pseudo-tours. Un changement réel ouvre un nouvel atome ; la confiance seule ne crée pas un événement cognitif si l'identité/état ne change pas.
- [x] Joindre audio et vision par temps/BrainLive session dans une timeline multimodale ordonnée. Aucun aplatissement « une frame = un tour de conversation ».

> **Suivi E64-A/B (notes, n'altèrent pas le texte des étapes) — livrés 2026-07-12, commit 03f5b50 :**
> - Package additif NON câblé au close-day : `src/mlomega_audio_elite/night_orchestrator/` (`evidence_ref`, `stage_adapter`, `vision_atoms`, `audio_atoms`, `multimodal_timeline`, `loaders`). Aucun prompt métier touché, aucune preuve supprimée.
> - E64-A : matrice des stages dans `docs/E64_NIGHT_STAGE_INVENTORY.md` ; `EvidenceRef.evidence_id = stable_id("evref", source_table, source_pk)` (jamais depuis un LLM) ; `NightStageAdapter` = contrat seul, exécuteur générique reporté à E64-C.
> - E64-B : preuve sur la vraie DB (run vidéo 5 min, blsess_e28e0d554f2fd667) — 472 observations vision → 120 atomes 100% lossless, 60 segments audio → 60 tours intacts, timeline 180 entrées.
> - Nouvelle preuve réelle 2026-07-12 (`blsess_aa0ef66764807c62`) : la timeline contenait 709 `vision_frames` brutes alternées avec 698 `vision_scene_observations`. Le premier reducer traitait les deux comme des états et produisait **1 407 atomes pour 1 407 refs**. Correction : les frames brutes sont rattachées temporellement comme preuves aux observations sémantiques et ne cassent plus les plages. Résultat produit réel : **1 407 refs → 132 atomes**, toutes uniques et couvertes ; export Brain2 **162 tours = 132 vision + 30 audio live**. Aucun changement au scénario ASR/VIKI.
> - Tests : 14 verts (`tests/v19/test_e64_night_orchestrator.py`) + 49 non-régression E63.


### E64-C — Fenêtrage token-aware et checkpoints durables

- [x] Planifier des fenêtres cibles de **40–50 unités utiles**, mais les couper selon le budget de tokens réel, les limites de scène/épisode et le contexte modèle. Le nombre 40–50 est une cible, jamais une règle qui perd des éléments.
- [x] Chevauchement borné aux frontières (par ex. 3–5 unités ou une courte durée) avec marqueurs `primary|overlap`, afin de ne pas couper une action/conversation ; le merge élimine ensuite les doublons par refs sources.
- [x] Persister `night_llm_windows_v19` et `night_llm_window_outputs_v19` (noms à figer en ADR) avec clé idempotente `(person,day,stage,input_digest,window_index,adapter_version,prompt_version,model)`, état, tentatives, budget, timestamps, erreur et output digest.
- [x] Sur `finish_reason=length`, subdiviser récursivement la fenêtre et reprendre ; sur timeout/Ollama down, retry backoff ; sur JSON/contrat invalide, une réparation bornée puis quarantaine explicite. Jamais augmenter indéfiniment `num_predict` ni accepter le fragment.
- [x] Désactiver le thinking pour les contrats JSON ; réserver séparément contexte d'entrée et budget de sortie. Refuser l'appel si la somme estimée dépasse la fenêtre du modèle.

> **Suivi E64-C (notes, n'altèrent pas le texte des étapes) — livré 2026-07-12 :**
> - Modules additifs NON câblés au close-day : `window_planner.py` (`plan_windows`/`subdivide`), `checkpoint_store.py` (tables `night_llm_windows_v19` / `night_llm_window_outputs_v19`), `executor.py` (`run_windows`, `ModelBudget`, `WindowLLM`). Aucun prompt métier touché.
> - ADR (noms de tables figés + clé idempotente + politiques d'échec) : `docs/DECISIONS.md` § « 2026-07-12 — E64-C ».
> - Politiques prouvées : subdivision récursive sur troncature (couvre tout, jamais de partiel), quarantaine d'une unité irréductible/surdimensionnée, réparation bornée puis quarantaine, retry backoff transitoire puis reprise, thinking off + budgets entrée/sortie séparés.
> - Tests : 13 verts (`tests/v19/test_e64c_executor.py`) — total E64 = 27 verts. **Prochaine étape = E64-F vague 1** (adaptateur EpisodeBuilder/Brain2 câblant l'exécuteur, débloque OBS-13).

### E64-D — Fusion hiérarchique et frontières

- [x] Fusionner les sorties par arbre déterministe (fenêtres → scène/bundle → conversation → journée), pas en reconcaténant toutes les sorties dans un nouveau prompt géant.
- [x] Chaque adaptateur définit seulement ses règles métier de merge : épisodes adjacents compatibles, entités/relations par ID durable, contradictions conservées, timelines ordonnées. La mécanique de réduction/checkpoint reste commune.
- [x] Résoudre les doublons d'overlap par ensemble d'`evidence_id`, plage temporelle et clé sémantique stable ; ne jamais dédupliquer uniquement sur le texte.
- [ ] Une fusion LLM éventuelle reçoit des résumés bornés + manifestes, jamais les preuves brutes déjà traitées ; elle conserve les références transitives jusqu'aux lignes sources.

### E64-E — Manifeste de couverture anti-perte

- [x] Pour chaque stage, produire `expected_evidence`, `covered_evidence`, `represented_by_atom`, `overlap_deduplicated`, `quarantined_with_reason`, `missing`. `missing` non vide bloque le stage.
- [x] Relire les sorties depuis leurs vraies tables avant de déclarer la couverture ; ne jamais utiliser les IDs simplement retournés par les fonctions comme preuve.
- [x] Garantir : chaque preuve attendue est soit directement citée, soit couverte transitivement par un atome/une fenêtre, soit quarantinée avec cause vérifiable. « Bruit/redondant » doit avoir un parent représentatif, pas disparaître.
- [ ] Enregistrer statistiques tokens/latence/retries/troncatures par stage et afficher les gaps dans Doctor/dashboard.

> **Suivi E64-D/E (notes, n'altèrent pas le texte des étapes) — livré 2026-07-12 :**
> - Modules additifs NON câblés au close-day : `merge_tree.py` (`resolve_overlap`, `hierarchical_merge`, `MergeItem`) et `coverage.py` (`build_coverage_report`, `covered_refs_from_outputs_table`, `stage_stats`). Aucun prompt métier touché. ADR dans `docs/DECISIONS.md` § « 2026-07-12 — E64-D/E ».
> - E64-D : fusion déterministe par arbre (fenêtres→scène→conversation→journée), dédup overlap par `evidence_id`/plage temporelle/`semantic_key` (JAMAIS le texte), refs unionnées dans le survivant. **1 case laissée décochée** : « fusion LLM éventuelle » — non implémentée car le merge est 100 % déterministe (pas de prompt LLM de fusion) ; la contrainte tient par construction. Si un adaptateur ajoute plus tard une fusion LLM, elle devra passer des résumés bornés + manifestes (à cocher à ce moment-là).
> - E64-E : manifeste à 5 seaux (covered / represented_by_atom / overlap_deduplicated / quarantined_with_reason / missing) avec `missing` qui bloque ; couverture relue depuis `night_llm_window_outputs_v19` (pas les IDs renvoyés). **1 case laissée décochée** : `stage_stats` PRODUIT bien les stats tokens/tentatives/troncatures, mais leur AFFICHAGE dans Doctor/dashboard n'est pas encore câblé (tâche UI séparée).
> - Tests : 10 verts (`tests/v19/test_e64de_merge_coverage.py`) — total E64 = 37 verts. **Prochaine étape = E64-F vague 1** (Ollama réel + EpisodeBuilder/Brain2, débloque OBS-13).

### E64-F — Migration transversale, par vagues

- [x] **Vague 1** : EpisodeBuilder + moteurs Brain2/V13. Le run scratch réel du 2026-07-14 a traversé les packs locaux et globaux (`roota/rootb`), matérialisé V13, puis atteint un CloseDay `completed`; aucun prompt V13 ne lit directement les frames brutes. La qualité métier reste auditée séparément ci-dessous.
- [ ] **Vague 2** : Deep Vision, conversation post-stop et Silent Life ; réutiliser les mêmes fenêtres/atoms au lieu de refaire une sélection indépendante.
- [ ] **Vague 3** : coordination BrainLive↔Brain2, Life Model, longitudinal, reconciliation, live-ready, prédictions/outcomes/self-schema pour tout appel LLM identifié en E64-A. **Chemin configuré réellement traversé le 2026-07-14**, mais case laissée ouverte jusqu'à l'audit exhaustif des appels hors orchestrateur et aux corrections qualité OBS-28/29.
- [ ] Les stages déterministes sans LLM restent inchangés mais publient leurs `EvidenceRef`/manifestes dans le même protocole.

> **Suivi E64-F vague 1 — code corrigé 2026-07-12 (fenêtres Ollama réelles validées ; run complet encore ouvert) :**
> - Règle Codex respectée : prompt V13 conservé, exécuté par fenêtres autonomes, sorties fusionnées avec preuve de couverture persistée, flag de rollback `MLOMEGA_E64_NIGHT_ORCHESTRATOR` (défaut ON, `=0` = legacy).
> - **Morceau 1** — `brainlive_event_assembler_v15_14.py::_vision_pseudo_turns` : 1 pseudo-tour par `VisionChangeAtom` au lieu de ~945 par observation (via `reduce_vision_timeline`), forme/`speaker_label`/`evidence_role` inchangés, `metadata.source_refs` garde tous les `observation_id`, fallback legacy sûr.
> - **Morceau 2 corrigé après contre-audit** — le premier câblage `ccec994` appelait directement `plan_windows` + `_llm_require_json` et contournait donc E64-C. Le chemin produit passe désormais par `run_windows` + `OllamaWindowLLM` : budgets entrée/sortie, vraie classification `truncated_output→length`, subdivision, retries, quarantaine, checkpoints et reprise. Les checkpoints sont commités à chaque transition durable et `input_digest` inclut le contenu réel, pas seulement les IDs. Le prompt/system/schéma V13 reste inchangé.
> - **Morceau 3 corrigé** — chaque sortie validée est persistée avec son manifeste de preuves primaires ; la couverture est ensuite RELUE depuis `night_llm_window_outputs_v19`. Les parents des atomes vision sont développés : la fixture 40 tours + 945 observations prouve bien **985 preuves sources**, pas seulement ~160 unités réduites. Un échec/timeout n'est ni crédité ni matérialisé.
> - **Frontières** — les épisodes partiels compatibles fusionnent par clé métier structurelle + intersection de preuves (jamais texte, pas seulement ensembles identiques). Les épisodes matérialisés portent `episode_source` + `coverage_status=complete`, donc une reprise ne les détruit/recrée pas.
> - Tests : **60 E64 verts** ; avec `test_e37_nightly.py` + `test_ollama_context_budget.py`, **73 verts**. Cela couvre aussi checkpoint réellement survivant après réouverture SQLite, changement de digest sous même ID, mapping du vrai `truncated_output`, 985 preuves et frontière partielle.
> - **Tentative réelle 2026-07-12 à ne pas surinterpréter** : les 301 s de vidéo ont traversé le live (15 077 chunks, 30 tours, 3 clips), mais la fermeture a échoué AVANT création du job recovery/CloseDay (`end_session=error`, `close_day=not_started`, aucune table `night_llm_*`). E64-F n'a donc pas encore été exercé par Ollama. La base scratch est conservée et doit être reprise par la recovery sans rejouer la vidéo. Dashboard interdit avant cette preuve.
> - **Rectification réelle après recovery** : le nouvel export immuable porte 158 tours (132 atomes vision + 26 tours Deep Audio) et représente toujours les 1 407 refs vision brutes. Le prompt EpisodeBuilder ne transporte plus les listes d'IDs opaques ni les copies exactes WhisperX/vision : le texte prononcé (répétitions incluses), speaker/person, timestamps, objets/actions/OCR, scores d'alignement et digests restent présents ; les listes originales restent en DB et la couverture les développe après le LLM. Mesure : **130 806 → 68 343 tokens (-47,8 %)**, sans sampling ni limite cognitive.
> - **Sortie bornée par responsabilité** : le modèle voit 2 tours précédents `context_only` + 2 tours `primary_output`, mais n'écrit que des épisodes soutenus par un primaire. Le vrai JSON Schema Ollama interdit les preuves copiées comme objets ; la normalisation extrait les `turn_id`, refuse les épisodes sans citation primaire et empêche les dicts d'atteindre SQLite. Qwen3.5:9b/16k réel : fenêtre froide 68,8 s, puis fenêtre chaude **8,7 s**, toutes deux `finish=stop`, contenu cohérent. Le test 4B/4k intermédiaire n'est pas une mesure nocturne et n'est pas retenu.
> - **Planificateur corrigé** : le coût fixe mission+schéma est retiré du budget AVANT planification ; plus de parent voué à `input exceeds budget`. Adaptateur `e64f-episode-window-v4`, cible mesurée 2 primaires + overlap 2 ; la subdivision récursive reste le filet de sécurité. **53 tests ciblés verts** (E64 + ré-export E37). Run complet/recovery/dashboard toujours non cochés.
> - **Reprise réelle suivante** : 79/79 fenêtres v4 `completed`, 79 tentatives, zéro retry/length/quarantaine. La relecture mélangeait toutefois les anciens outputs v2 au merge v4 ; elle est désormais restreinte aux clés feuilles courantes. Manifeste réel : **1 433/1 433** (26 audio directes + 1 407 vision transitives), zéro missing.
> - **Writers V13 durcis** : barrière schéma commune aux 16 writers (objets/listes → JSON lossless pour TEXT, scalaires numériques bornés, FK vérifiées par `PRAGMA` et, pour un turn, appartenance conversation). Les 16 moteurs par épisode sont checkpoints atomiquement par hash de prompt ; une erreur au moteur N ne rejoue plus 1..N-1. **57 tests ciblés verts**, dont FK/objets imbriqués négatifs, splitter de champs et reprise exacte. Le volume actuel (**19 épisodes × 16 = 304 appels**) reste à mesurer/arbitrer sans supprimer de passe ; gate complet toujours ouvert.
> - **Mesure de débit qui interdit de clore F** : `internal_state_engine` tronquait en monolithe ; le splitter générique par champs restitue 10/10 clés en 4 tâches et ramène son prompt 13 665→7 038 tokens, mais prend **195,8 s pour un épisode** en 9B. 304 appels ne sont que V13, avant Life Model. À faire : inverser la matrice en moteur→batches d'épisodes planifiés par tokens, garder l'owner/episode/provenance, et réserver les moteurs psychologiques aux épisodes humains/interactionnels (les événements capteur restent couverts par Vision/WorldBrain). Aucun moteur ni preuve supprimé ; exécution au bon niveau.

#### E64-F — checkpoint de pause Codex 2026-07-13 (autoritaire pour la reprise)

**Architecture livrée dans le working tree de ce commit :**

- [x] Router les 132 atomes vision/capteur hors de la psychologie primaire, avec manifeste transitif conservant les 1 407 refs brutes ; garder les 26 tours Deep Audio humains, sans dédupliquer leurs répétitions parlées.
- [x] EpisodeBuilder v5 produit sur la fixture réelle **12 épisodes humains** (client_request 3, conflict 1, emotional_reaction 2, planning 3, relationship_tension 1, self_reflection 2) et zéro épisode technique/capteur ; les épisodes psychologiques n'ont pas été supprimés.
- [x] Remplacer la matrice locale « moteur × épisode » par **un pack cohérent par épisode** : tous les moteurs applicables et tous leurs schémas restent présents ; les groupes de champs sont fusionnés par code, et `length` subdivise les responsabilités sans supprimer preuve/champ/moteur.
- [x] Applicabilité explicite : capture/language/context/causality sur chaque épisode humain ; internal/social/contradiction/choice/outcome seulement quand le type et les participants peuvent réellement les soutenir ; les six moteurs transversaux restent conversation-scopés.
- [x] Projection prompt lossless : texte exact, timestamps, speaker/person, score d'alignement, segmentation, contenu vision/OCR restent visibles ; mots WhisperX dupliqués, IDs/digests opaques et copies de `representative` restent en DB/manifeste mais ne sont plus répétés au LLM. Cas difficile mesuré **6 836→5 128 tokens** et **104,1→28,75 s** en 9B/16k, tous les 6 moteurs/8 groupes complets.
- [x] Checkpoint E64-C corrigé : la clé inclut désormais le digest de la **requête rendue complète** (bundle/règles/schéma/prior), pas uniquement les unités planifiées. Un changement de contexte commun ne peut plus reprendre une ancienne sortie verte.
- [x] Forcer la phase interne `post_stop_brain2_v13` lors de la construction et de l'appel du client : un appel direct/outillage ne peut plus sélectionner silencieusement le modèle live 4B/4k alors que le planificateur budgète 16k.
- [x] Bundle local source stable : épisode+tours+contexte immuables ; les tables matérialisées ne se réinjectent jamais dans leur propre prompt. Les dépendances passent uniquement par `prior_engine_outputs`. Cela empêche le hash de changer après chaque writer.
- [x] Hiérarchie générique `hierarchical_json.py` migrée dans les helpers nocturnes non bornés : V14 post-stop, Silent Life, coordination, Life Model/bootstrap/updater/live-ready, Pattern Mirror week/month et wrappers V18. Deep Vision reste volontairement une image VLM checkpointée par appel, pas re-fenêtrée artificiellement.
- [x] Politique de frontière distincte : `length` sur feuilles de preuves ⇒ subdiviser les capsules ; `length` sur une **fusion** ⇒ remonter à l'adaptateur et diviser les schémas/moteurs. Détection de fan-in sans progrès ; aucun arbre de douze fusions identiques.
- [x] Tests ciblés au point de pause : **43 verts** (`test_e64c_executor.py` + `test_e64f_brain2_blocks.py`) et `py_compile` vert sur `brain2_strict_v13_2.py`, projection, exécuteur et hiérarchie. Validation élargie avant commit : **98 passed** (E64 A–F, E37, budget Ollama, longitudinal, multi-session CloseDay), 2 warnings SWIG de dépréciation.

**Preuve réelle acquise, mais à ne pas confondre avec le gate final :**

- [x] Les 12 packs locaux ont atteint `completed` sur Qwen3.5:9b/16k lors de la première exécution unique. Onze packs sont passés directement ; un run Qwen a dérivé jusqu'à `finish=length`, puis ses deux enfants ont couvert les six responsabilités. Aucun partiel promu.
- [x] Première fenêtre globale : 10 capsules d'épisodes dans 10 463 tokens, sortie validée. Les capsules restantes et les fusions ont prouvé le déclenchement des subdivisions.
- [x] **V13 réel terminé sur la fixture scratch** : le run 9B réel a prouvé `roota/rootb`, la matérialisation des moteurs globaux, les packs locaux et le passage au stage V14 puis au CloseDay. Les anciens parents combinés `quarantined` restent auditables mais ne créditent pas le résultat courant.
- [ ] **Revalider la reprise stable** après le dernier correctif `_stable_episode_source_bundle` : lancer V13 une fois avec un seul processus, puis une seconde fois et prouver zéro nouvel appel local. Le dernier `profiles[...] is None` provenait d'un `return` déplacé pendant l'édition ; corrigé et couvert, mais pas rejoué en réel après la pause.
- [ ] Les mesures globales entre 01:24 et 01:52 ne sont **pas** des benchmarks : interrompre le wrapper PowerShell a laissé trois Python orphelins solliciter Ollama et écrire des checkpoints simultanément. Ils ont été tués ; aucun processus Python ne tournait au moment de la pause. La DB scratch reste utile pour l'audit/reprise grâce aux clés exactes, mais faire une exécution fraîche séparée pour la performance.

**Ordre obligatoire pour le prochain agent :**

1. [ ] Rejouer les 43 tests ciblés, puis la suite E64/V13 élargie déjà utilisée auparavant ; ne lancer aucun nouveau média.
2. [ ] Vérifier `Get-Process python` et n'avoir qu'un seul runner. Reprendre `tools/harness/_run/harness_memory.db` en phase post-stop ; ne jamais lancer deux writers sur cette DB.
3. [ ] Finir le pack global réel : attendre la séparation par schémas, vérifier chaque moteur transversal, `night_llm_coverage_v19.ok=1`, 12/12 capsules, zéro missing/quarantaine finale.
4. [ ] Relancer immédiatement V13 sur la même entrée et prouver la reprise : zéro appel Ollama local/global supplémentaire et aucune ligne métier doublée.
5. [ ] Exécuter ensuite seulement le flux V14/post-stop (vague 2), puis coordination/Life Model/longitudinal/live-ready (vague 3). Vérifier les manifests à chaque frontière avant le stage suivant ; corriger le premier vrai échec, pas contourner un moteur.
6. [ ] Lancer le CloseDay/harness complet jusqu'à `completed`, puis seulement le dashboard. Inspecter épisodes/personnes/événements vidéo/Life Model/prédictions/preuves ; ne pas présenter le dashboard d'une nuit partielle.
7. [ ] Mesurer sur une exécution fraîche : temps EpisodeBuilder, V13 local, V13 global, V14, Life Model/longitudinal. Objectif de conception : **1 h de capture ≤ 1 h de consolidation** ; la fixture 5 min doit rester proche du temps de capture, sans sampling cognitif.

### E64-F0 — Frontière fermeture révélée avant le premier run F réel

- [ ] Identifier précisément quel drain (`device receipts`, audio ingress, final worker ou transport) dépasse son budget ; le statut doit nommer la phase et l'exception, jamais enregistrer une chaîne vide.
- [x] Empêcher le harnais `--with-close-day` de poller CloseDay pendant 30 minutes lorsque `end_session` a déjà échoué ou que `close_day=not_started`.
- [x] Reprendre la base scratch existante sans rejouer le média : run `run_v18_65bdecb7404f4e05abe16cf843f124e4` terminé le 2026-07-14, dix stages `completed`, manifeste observé/attendu `complete=1`, cleanup autorisé.
- [ ] **FIRST_TRY/RUN hermétique** : avant SessionHub, détecter un proxy loopback/mort (`127.0.0.1:9`) au lieu de le transmettre à HF ; vérifier compte + scope gated + cache Pyannote ; préparer le même `PATH` CUDA/cuDNN pour TOUS les subprocess (dont recovery/commandes manuelles) et charger réellement `cudnn_ops_infer64_8.dll`. Un échec bloque avant la capture avec correction guidée ; ne jamais découvrir HF/cuDNN après cinq minutes de session.

> **Checkpoint de reprise réel avant optimisation** : E64-F a effectivement atteint Ollama 9B et prouvé 5 sorties `completed`, subdivisions entrée/sortie et absence de matérialisation partielle. Le run a été volontairement arrêté quand la DB a révélé 1 433 tours (dont 1 407 faux atomes unitaires) : continuer aurait exigé ≥32 fenêtres racines. Ces checkpoints restent pour audit sous l'ancien `conversation_id` et ne contaminent pas le nouvel export immuable.
>
> **Correctif de ré-export** : une nouvelle conversation base et l'ancien export Deep Audio pouvaient rester simultanément `exported`, puis faire échouer la reprise par `assembly/export cardinality mismatch`. Avant d'activer le nouvel export, l'assembleur supersède désormais toutes les anciennes lignes actives du bundle, désactive leurs scopes et invalide leurs descendants. Test de ré-export multiple ajouté ; aucune conversation historique n'est supprimée.

**Référence humaine de la vidéo (documentation de diagnostic uniquement ; NE PAS modifier le scénario ASR/VIKI)** : 0:00–1:30 ami/canapé et conversation ; 1:30–2:00 lever + table avec lunettes/téléphone ; 2:00 clés posées puis regard table/tête tournée ; 2:30–2:38 texte fixé ; 2:38–3:20 changements de pièces puis retour salon/table ; 3:34 lunettes déplacées près du meuble ; 3:57–4:10 machine à café ; 4:10 terrasse ; 4:24–fin seconde personne et conversation. Cette vérité sert à interpréter la fragmentation vision ; `tools/harness/scenarios/real_video_session.json` reste inchangé.

#### E64-F — validation réelle de chaîne et corrections de finisseur (2026-07-14)

- [x] Un seul run autoritaire a traversé `post_stop → visual_consolidation → longitudinal → coordination → life_model → outcome_resolution → life_model_v19 → prediction_emission → self_schema → live_ready`. Run : `run_v18_65bdecb7404f4e05abe16cf843f124e4`; manifeste final `complete=1`; rétention/tiering/maintenance `ok`.
- [x] Le client LLM supporte un backend direct llama.cpp **opt-in** (`MLOMEGA_LLM_BACKEND=llamacpp`) sans changer le défaut Ollama. Validation : Qwen3.5 9B Q4_K_M, contexte 24 576, sortie 4 096, `reasoning off`, JSON/Jinja, une seule requête parallèle. Cette configuration sert à mesurer et déboguer; le choix production attend l'audit E64-H.
- [x] Prévention transversale des prompts non bornés : budget sur requête rendue complète, décodage des colonnes `*_json` persistées en vraies feuilles, split des responsabilités de sortie, garde de cardinalité de projection, fenêtres denses de 45 unités avec limite token dure, checkpoints versionnés, couverture relue en DB.
- [x] Life Model durci : références de preuve structurées et résolues vers la vraie ligne owner-scopée; Unicode CLI Windows sûr; matérialisation atomique (aucune moitié écrite avant une erreur); les sections consultatives ne deviennent plus de faux objets canoniques. Le run a produit 92 objets canoniques actifs avec couverture `missing=0`.
- [x] `live_ready` ne repaie plus un LLM pour reformuler 303 k caractères déjà compilés par V15.10. Le compilateur déterministe mappe les objets canoniques et leurs preuves vers l'index BrainLive; fallback LLM conservé pour une DB legacy sans modèle canonique. Stage réel : ~2,1 s; reprise finale complète + manifeste/cleanup : 7,7 s.
- [ ] **Vague 2 non close** : Deep Vision a retourné `status=ok` malgré `selected=1`, `analyzed=0`, `quarantined=1`; l'unique image a consommé 84 132 ms puis JSON invalide. Corriger le statut/gate et le backend VLM avant toute extrapolation (OBS-28).
- [ ] **Qualité non certifiée** : ASR stocké à confiance 0 avec fragments grec/russe probablement faux; coordination a transformé l'absence de preuve vision en contradiction et produit des conclusions trop certaines; Life Model a produit 92 objets sur une petite fixture. Ces sorties ne doivent pas être présentées comme vérité utilisateur avant OBS-29/30.
- [ ] **Bootstrap FirstTry non hermétique** : aligner le lock `transformers` avec la version Qwen3 réellement requise, vérifier HF gated/proxy, Qdrant, CUDA/cuDNN et backend LLM/VLM avant capture; aucun téléchargement/découverte d'environnement après la session.

### E64-H — audit coût/qualité avant décision locale ou cloud (AUDIT TERMINÉ — 2026-07-14)

- [x] Mesurer le chemin final en excluant les essais abandonnés : **169 appels**, environ **1,119 M tokens d'entrée**, **218 k tokens de sortie** et **83,0 min de calcul texte** sur la fixture auditée. Détail par groupe, cardinalités et limites de la télémétrie dans `docs/E64_H_COST_QUALITY_AUDIT.md`.
- [x] Classer les passes : 9B à préserver pour nuance humaine; 4B uniquement structure/faible risque; construction/compilation/retrieval/calibration sans issue à rendre déterministes ou conditionnels; V13/V14/coordination/Life à faire consommer une même couche de faits/provenance plutôt qu'à ré-inférer.
- [ ] Tester les regroupements/fusions proposés contre les sorties réelles et la référence humaine; comparer 9B/4B par stage, jamais globalement, avec JSON strict et couverture identique. Cette case devient le gate d'implémentation E64-I, pas une hypothèse cochée par l'audit.
- [x] Auditer la vision : PhoneOnly ne paie qu'un VLM lourd nocturne; VisionRT live et Qwen3-VL sont complémentaires, puis `visual_consolidation` travaille par code. Cinq minutes : 11 images, 82,9 s à froid puis ~18,36 s/image à chaud; 11/11 sorties invalides. Cache uniquement par hash image+modèle+prompt et sélection par changements couverts.
- [x] Extrapoler 8 h : chemin actuel post-E64 ~**19 469 appels / 159,4 h texte**, plus **5,4 h VLM chaud** ou **23,5 h à 80 s/image**. Refonte proposée : ordre de grandeur **2–3 h texte + ~3,9 h VLM** sur une journée continuellement événementielle, à prouver. DeepSeek Pro sans refonte : ~**68,24 EUR/jour** texte seul; après refonte ~**1,78 EUR** sans cache.

**Verdict H** : les gains E64 sont réels (l'ancien chemin 1,6 M caractères/985 pseudo-tours ne terminait pas; l'étape intermédiaire demandait déjà 304 appels V13). Mais le chemin terminé actuel amplifie 26 tours en 10 épisodes fragiles, ~324 lignes V13 et 92 objets Life Model. Ne pas basculer tout en 4B ou DeepSeek. Corriger vérité/cardinalité et tester la refonte ci-dessous sans supprimer preuve ni capacité.

### E64-I — refonte sémantique à qualité conservée (PLAN D'EXÉCUTION — 2026-07-14)

**Pourquoi cette refonte est obligatoire.** La mesure autoritaire n'est pas une estimation de prompt : sur la minute auditée, 26 tours Deep Audio ont produit 10 épisodes, puis **169 appels / 1,119 M tokens d'entrée estimés / 218 k de sortie / 83 min de calcul texte / 92 objets Life Model actifs**. L'extrapolation actuelle à huit heures (19 469 appels, 159 h texte, hors VLM) est donc non viable. La cible précédente de 884 appels et 2–3 h texte est une **hypothèse de dimensionnement**, pas une promesse : le premier prototype ci-dessous doit prouver au moins un gain ×5 avant qu'on extrapole la refonte entière. L'objectif produit reste `1 h capturée ≤ 1 h consolidée`; le premier passage peut accepter jusqu'à 8 h pour une journée de 8 h, mais jamais 159 h masquées par un manifeste vert.

**Invariants non négociables (la vitesse ne peut pas les acheter).**

- [ ] Les tours, frames, observations, WAV/MP4 et sorties de moteurs restent durables et immuables; une réduction de prompt garde un manifeste transitoire vers **100 %** des parents bruts.
- [ ] Aucun échantillonnage, `LIMIT`, `rows[:N]`, résumé ou déduplication textuelle ne peut être crédité comme couverture; seuls pagination complète, atomes lossless et doublons prouvés par identité/provenance sont admis.
- [ ] Chaque capacité métier, schéma, writer et preuve V13/V14/V15/V17/V18/V19 reste disponible. Une inférence déjà faite peut être réutilisée ou compilée par code; une inférence distincte ne peut pas disparaître pour faire baisser le compteur.
- [ ] Qwen 9B reste la référence des tâches humaines nuancées. Ni 4B, ni cloud, ni réduction du nombre de sorties ne passe sans comparaison aveugle sur les mêmes preuves et le même contrat.
- [ ] Un stage `completed` ne vaut pas produit : chaque sous-moteur expose `product_validated`, `degraded`, `abstained` ou `failed`, avec la cause et la couverture relue en base.

#### I0 — vérité avant optimisation (bloque toute certification)

- [x] **I0.1 Deep Vision** : dans l'override réellement appelé, forcer `think=false`, JSON strict et `analyzed_keyframes > 0` lorsque des images sont sélectionnées; zéro analyse devient `retryable|degraded|failed`, jamais `ok` (OBS-28).

> **Suivi I0.1 — fermé par I4.2 + I4.4 (2026-07-16), conformément au plan (« I0.1 Deep Vision sera fermé par I4.2/I4.4 »)** : think=false + JSON strict validé + modèle VLM réel (I4.2, commit cadc777) ; selected>0/analyzed=0 → jamais ok + couverture non persistée → failed + gate prouvé dans les deux sens sur run réel 20/20 (I4.4).
- [x] **I0.2 Qualité des preuves** : propager confiance ASR, diarisation, langue et alignement jusqu'aux faits; une confiance dérivée ne dépasse pas sa meilleure preuve sans corroboration indépendante; fragments linguistiques incohérents en quarantaine (OBS-29).
- [x] **I0.3 Épistémologie** : `non_observed` reste `unknown`; seul un fait positif incompatible peut donner `contradicted`; toute promotion Life Model commence `watch` et exige répétition ou sources indépendantes (OBS-30/37). Preuves : `build_reconciliation_candidates` ignore l'absence/non-outcome, compile seulement les statuts positifs explicites; Life écrit `watching` puis `promotion_ready` après deux groupes indépendants; tests `test_e64i_daily_projection.py`.
- [x] **I0.4 Manifeste de capacité** : agréger les verdicts des sous-moteurs et interdire `complete=1` si une capacité obligatoire est bypassée, abstentionniste ou faux-verte (OBS-38).
- [x] **I0.5 Préflight FirstTry** : avant capture, vérifier HF gated/proxy, Qdrant, Ollama/llama.cpp, modèle/format JSON, version `transformers`, CUDA/cuDNN, VLM, disque et venv nocturne; aucun téléchargement ou diagnostic tardif après `end_session` (OBS-32). Clos en code le 2026-07-15; l'état opérateur courant reste volontairement bloqué tant qu'Ollama n'est pas démarré et que le llama-server P1 orphelin n'est pas arrêté ou déclaré comme backend.
- [x] **I0.6 Recherche spatiale produit** : distinguer ingestion et consommation. VisionRT/WorldBrain stockent bien des positions, mais `FocusSearchSkill.Locate`, `spatial.answer_find` et `VisionRtRequestSender` ne sont pas appelés/assignés en production; brancher « où est X ? » sur la dernière observation durable, avec fraîcheur/confiance et fallback honnête. Le focus de frame courante ne vaut pas dernière position connue.

> **Suivi I0.6 — FAIT 2026-07-16.** Le flux connecté réel est maintenant
> `device_transcript → IntentRouter → LivePipeline._route_vision_focus →
> WorldBrain.find_entity_record → spatial.answer_find → UI intent`. Le registre durable
> `worldbrain_entity_registry_v19` est owner-scopé et relu à travers les sessions : la
> dernière observation actualise l'état courant, tandis que l'historique immuable reste
> dans `visual_events_v19`. La réponse distingue `visible` et `remembered`, porte
> fraîcheur/confiance/source et retourne un inconnu honnête sans inventer de direction.
> Hors connexion, le transcript ASR final déclenche réellement `FocusSearchSkill` via
> `ReflexScheduler`; lorsqu'une session PC est active, le PC reste autoritaire et Unity
> ne double pas la commande.
>
> Le pont proactif qui était dormant est fermé : `_on_scene_delta` appelle désormais
> `BrainLiveSceneAdapter.evaluate_periodic` (cadence mémoire configurable, 2 s par
> défaut), sans modifier le rendu UI événementiel par frame. Les personnes déjà connues
> passent aussi dans le VLM d'apparence une fois par track/session; cheveux, vêtements,
> chaussures et autres attributs alimentent `AttributeMemory`, puis un changement durable
> ouvre le H1 avec provenance. Le dédoublonnage d'attributs inclut maintenant
> `(subject, attribute)` : plusieurs attributs issus de la même crop ne s'écrasent plus.
> Validation : 128 tests live/vision/proactivité verts dans `.venv-live`, 13/13 tests
> Unity EditMode Reflex verts, dont le vrai pont ASR hors-ligne. Le S25 reste le gate
> matériel I7, pas une condition pour considérer le raccord code terminé.

#### I1 — mini-plan 1 : un épisode conversationnel, des sous-thèmes ordonnés

- [x] **I1.0 Baseline figée** : DB `tools/harness/_audit/one_minute_memory_v1.db`, 1 bundle actif, 26 tours Deep Audio utiles, 10 épisodes défectueux, EpisodeBuilder 4 appels / 20 210 tokens entrée estimés / 3 420 sortie / 229,9 s. Défauts : mêmes débuts, fins nulles, citations réutilisées entre sujets et mélange Karim/Netflix (OBS-34). Ne pas relancer la nuit pour retrouver cette baseline.
- [x] **I1.1 Contrat sémantique v6** : une conversation continue devient **un parent conversationnel**, contenant des sous-thèmes ordonnés et cités. Créer un autre parent seulement sur frontière dure prouvée : changement de conversation/session, silence long configuré, changement d'interaction/personnes, action/lieu indépendant ou fin explicite — jamais « un mot = un épisode » ni une durée arbitraire.
- [x] **I1.2 Sous-thème durable** : stocker pour chaque sous-thème ordre, titre/résumé, bornes de tours, participants, état d'issue, confiance et refs primaires. Chaque tour humain appartient à exactement un sous-thème primaire; il peut être contexte d'un voisin mais ne peut pas soutenir deux affirmations incompatibles. Le parent porte l'union 26/26 et les événements capteur restent des liens contextuels séparés, jamais de la psychologie attribuée à William.
- [x] **I1.3 Appel borné sans troncature** : envoyer la projection compacte complète si elle tient; sinon produire des fragments de sous-thèmes par fenêtres puis assembler le parent par code/provenance. Ne pas demander plusieurs épisodes full-schema par tranche. Préflight sur taille d'entrée **et** cardinalité de sortie; aucun premier appel voué à `length`.
- [x] **I1.4 Compatibilité et migration** : versionner prompt, schéma, checkpoint et writer; exécuter d'abord en shadow sur une copie de DB. Conserver le chemin v5 pour comparaison/rollback jusqu'au verdict. Les consommateurs V13 lisent le parent et ses sous-thèmes; aucun ancien checkpoint v5 ne peut valider une sortie v6. Shadow puis vrai CloseDay effectués; v6 ON par défaut, rollback explicite `=0`.
- [x] **I1.5 Tests structuraux** : 26/26 tours couverts, ordre/bornes réels, un tour primaire dans un seul sous-thème, frontière traversant deux fenêtres fusionnée une fois, aucun merge par texte, aucune FK inventée, capteur-only sans épisode psychologique, reprise sans nouvel appel ni doublon.
- [x] **I1.6 Gate réel stop/go** : sur la minute, viser **1 parent + environ 4 sous-thèmes**, Karim et Netflix séparés, toutes les assertions relisibles dans les tours, ASR incertain visible; **≤2 appels**, entrée ≤50 % des 20 210 tokens, sortie ≤3 420 tokens et temps chaud ≤50 % des 229,9 s. `GO` seulement si couverture=100 % et qualité au moins égale; `STOP/REDESIGN` si gain appels <×2 sur EpisodeBuilder, gain projeté chaîne <×5, ou une preuve/capacité manque.

> **Suivi I1.5/I1.6 — FAIT 2026-07-16 (notes, texte des étapes intouché) :**
> - **I1.5** : la coupure thématique artificielle aux bords de fenêtre était RÉELLE (test rouge d'abord : 13 sous-thèmes au lieu de 10, fragments parasites à t8/t17/t23). Correction par PROVENANCE dans `brain2_conversation_episode.py` : `normalize_window_segmentation` marque `window_boundary_forced` (fin forcée par le bord, raison de continuation) vs vraie frontière sémantique ; `_fuse_forced_window_edges` fusionne au réassemblage un segment à fin forcée avec le segment de continuation de la fenêtre suivante (jamais par texte). Cas de contrôle : une vraie frontière au bord de fenêtre reste une frontière ; fusion validée aussi aux bords de sous-division récursive ; reprise 0 appel. Tests : +2 dans `test_e64i_long_conversation.py` → 20 verts avec `test_e64i_conversation_episode.py`.
> - **I1.6 (re-cadré par Codex 2026-07-16 : la minute en conditions PRODUIT normales, pas de budget réduit — le cas fenêtré forcé appartient à I1.5)** : run réel Qwen3.5 9B llama.cpp P1/24k, thinking désactivé, clone de `one_minute_memory_v1.db`, hors CloseDay. Mesures : **2 appels (1 segmentation + 1 détail), 15 772 tokens d'entrée, 32,6 s (vs réf 41,5 s), 1 parent + 4 sous-thèmes** (réf humaine ~4 sujets ; le shadow 2026-07-14 en donnait 6), **Karim (#0) et Netflix (#3) séparés**, couverture **26/26 primaire exactement une fois**, zéro FK inventée (tours/bornes/évidence), aucune erreur budget/length. Gain appels ×2 vs baseline (4), temps −86 % vs baseline (229,9 s). **Cible « entrée ≤50 % » toujours non atteinte (78 %)** — même niveau que le shadow (−21 %) ; c'est la part incompressible de la projection actuelle, à retraiter par les mesures I2/I7, pas par ce gate.
> - **Découverte opérationnelle importante** : le llama-server P1 lancé avec `--reasoning-budget 0` SEUL laisse Qwen3.5 « penser » (4096 tokens de raisonnement → finish=length même sur une requête triviale). Il faut AUSSI `--chat-template-kwargs {"enable_thinking":false}`. Commande complète consignée dans EXECUTOR_BUILD_GUIDE.
- [x] **I1.7 Projection après mesure uniquement** : mesure acquise puis I2 a mutualisé les packs; le vrai CloseDay a traversé le nouveau parent. La promesse 8 h reste interdite jusqu'à I7.

**Résultat réel mini-plan 1 — shadow 9B/llama.cpp (2026-07-14, non activé en production).**

- [x] Contrat v2 implémenté derrière `MLOMEGA_E64_CONVERSATION_EPISODES=1` (défaut `0`) : deux tâches bornées, d'abord frontières seules, puis détail sur segments verrouillés. Le deuxième appel ne peut ni déplacer ni fusionner les tours; le writer matérialise un parent, des sous-thèmes ordonnés, l'appartenance exacte et les citations primaires dans `episode_subthemes_v19` / `episode_subtheme_evidence_v19`.
- [x] Mesure sur une **copie** de `one_minute_memory_v1.db`, Qwen3.5 9B llama.cpp 24k : **2 appels, 15 956 tokens entrée estimés (3 284 segmentation + 12 672 détail), 41,50 s, 1 parent + 6 sous-thèmes, 26/26 tours distincts**. Baseline : 4 appels, 20 210 tokens, 229,9 s, 10 épisodes. Gains prouvés : appels −50 %, entrée −21,05 %, temps −81,95 % / **×5,54**, épisodes parents −90 %. `speaker_identity_unenrolled` est ajouté par code; aucun fait n'est attribué à William.
- [x] Le premier essai monolithique (1 appel, 12 472 tokens, 35,48 s) a prouvé le débit mais mal placé quatre tours substantifs; il est rejeté comme voie produit. La séparation frontières/détail ajoute ~6 s mais supprime cette liberté au second appel. Le résultat deux passes est sémantiquement complet; 6 sous-thèmes au lieu d'environ 4 signale encore une légère sur-fragmentation du 9B, améliorable sans changer l'architecture.
- [x] Deux pertes de qualité silencieuses antérieures à I1 ont été corrigées dans la projection commune : `state` des atomes vision, manifeste count+digest des refs et `offline_speaker_resolution` restent visibles au LLM, sans recopier les listes opaques.
- [x] Pont V13 corrigé : le parent `episode_type=conversation` expose ses `subtheme_types` et les sous-thèmes au bundle. L'applicabilité des moteurs est calculée sur l'union parent+sous-thèmes; capture, langue, contexte, causalité, social, interne, contradiction, choix et outcome ne peuvent pas disparaître à cause du nouveau conteneur. Test explicite vert.
- [ ] **Gate I1 non clos** : la cible entrée ≤50 % n'est pas atteinte (−21 %), le comportement long doit encore produire/fusionner des segments par fenêtres checkpointées, et le nombre réel de subdivisions du pack V13 parent n'a pas été benchmarké. Ne pas activer le flag ni extrapoler huit heures. Le gain de temps est néanmoins supérieur au seuil ×2 EpisodeBuilder et la réduction du multiplicateur 10→1 autorise le prototype I2.
- [ ] **Projection honnête** : le pack local V13 passe statiquement de 10 parents à 1 parent, mais peut demander plusieurs appels si ses 7–9 responsabilités dépassent la sortie. V14/coordination/Life continuent aujourd'hui à ré-inférer; le mini-plan 1 seul ne transforme donc pas 169 appels en 17. I2 doit mesurer le pack parent, produire les faits une fois et démontrer le gain chaîne ≥×5 avant tout calcul 8 h.

#### I2 — faits typés partagés, une inférence chère payée une fois

- [x] **I2.1 Inventaire exécutable** : registre central + matrice d'équivalence R3 couvrent les responsabilités V13/V14/coordination/réconciliation/Life et refusent tout nouveau stage produit non classé.
- [x] **I2.2 Contrat commun** : faits typés/capacités versionnés, preuves, plafonds et writers historiques sont matérialisés dans `brain2_shared_*_v19`.
- [x] **I2.3 Pack sémantique parent** : pack parent V13 réel 7/7 groupes, projection payée une fois, splits par responsabilités et couverture complète.
- [x] **I2.4 Portée conversation/jour** : V14 et projection journalière consomment faits/sous-thèmes; le feedback courant est exclu.
- [x] **I2.5 Réconciliation/coordination/Life** : coordination compilée, ambiguïtés seules au LLM; Life consomme delta+état, premier indice en watch, reprise durable.
- [x] **I2.6 Équivalence** : R3 couvre 18/18 responsabilités, writers et consommateurs; R4 supprime les caps. Nouveau chemin ON par défaut après vrai CloseDay.

**Checkpoint I2 — pause et passation du 2026-07-14.** Le flag
`MLOMEGA_E64_SHARED_FACTS=1` reste opt-in et vaut `0` par défaut. Le chemin produit
historique est donc inchangé tant que la validation shadow suivante n'est pas close.

- [x] **I2.2a — noyau canonique implémenté** : les sorties V13 validées sont écrites
  losslessly dans `brain2_shared_engine_sections_v19`, projetées en faits typés et liens
  de preuve, et accompagnées d'un manifeste de capacités distinguant `produced`,
  `valid_empty` et `not_applicable`. Les plafonds de confiance et statuts épistémiques
  restent explicites. La sortie canonique relue alimente ensuite le writer historique
  V13 : le dashboard, BrainLive et les API existantes ne sont pas contournés.
- [x] **I2.3a — pack parent V13 mesuré** : sur le parent shadow de la minute de référence,
  capture/langue/contexte/social/causalité/choix/outcome ont été traités en **1 appel
  Qwen 9B, 19 452 tokens d'entrée, 22,656 s, 7/7 groupes couverts, missing=0**. Interne
  et contradiction étaient réellement non applicables aux sous-thèmes, et non sautés
  silencieusement. Avec les deux appels I1, ce bloc coûte 3 appels/~64,16 s contre
  14 appels/~19,36 min pour l'ancien EpisodeBuilder+V13 sur la même référence.
- [x] **I2.4a — cardinalité centralisée pour le premier trio V14** :
  `run_hierarchical_json` appelle une projection commune avant tout split. Identité,
  open loops et interpersonnel reçoivent tous les tours une fois, les faits V13 utiles,
  l'outline parent/sous-thèmes et des références courtes réversibles; les embeddings
  vocaux restent en base mais ne sont pas recopiés au prompt. Le stage interpersonnel
  expose centralement deux responsabilités sémantiques au lieu d'entretenir un split
  privé. Le V14 open-loops peut éviter l'appel uniquement si le V13 outcome tracker a
  validé une liste vide sur l'unique parent complet.
- [x] **Prévention qualité/tests ciblés** : aucune déduplication de texte ni suppression
  de tour; `lossless_turn_manifest.omitted_turn_ids=[]`; les IDs courts sont restaurés
  avant writer; le feedback historique de la conversation en cours est exclu pour ne
  pas réinjecter sa propre sortie. **60 tests ciblés verts** (I1/I2/E64-F), compilation
  comprise. Une première projection locale insuffisante (31 036→22 644 tokens identité)
  a été rejetée; la politique centrale améliorée mesurait avant le dernier compactage
  31 067→8 684 pour identité et 37 578→11 186 pour interpersonnel. Ces mesures sont
  structurelles, pas encore un verdict Qwen aval.
- [ ] **I2.1 reste partiel** : l'inventaire exécutable couvre le pack V13 et le trio
  V14 ci-dessus. Pattern Mirror/clarification/V14.7, coordination, réconciliation,
  Life Model, longitudinal et leurs writers doivent encore être classés champ par champ.
- [ ] **I2.2b reste à faire** : étendre le contrat commun aux producteurs hors V13 et
  prouver, writer par writer, que les projections historiques restent équivalentes.
- [x] **I2.4b — V14 réel validé sur clones** : baseline 20 appels / 293 495 tokens
  d'entrée estimés / 569 s; shadow I2 3 appels / 36 898 tokens / 136 s, soit −85 %
  appels, −87,4 % entrée et −76,1 % temps. Les refs de tours sont restaurées, les dix
  responsabilités interpersonnelles passent par les writers, et l'identité reste
  `UNKNOWN` au lieu de promouvoir « Maxime » sans preuve. Les retours structurés du
  runner sont normalisés avant les writers V14.5/V14.6; une liste vide open-loop n'est
  réutilisée que si la capacité V13 est réellement `valid_empty`.
- [ ] **I2.5/I2.6 restent ouverts** : étendre la politique dans l'orchestrateur et le
  registre de faits — pas par compactages ad hoc dans chaque moteur — puis construire
  la matrice d'équivalence coordination/réconciliation/Life. Ensuite seulement relancer
  le harnais 5 min, le dashboard et recalculer la projection 8 h.

**Feuille de reprise obligatoire — les quatre prochaines étapes réelles.** Elles sont
séquentielles : ne pas lancer tout CloseDay entre chacune et ne pas considérer une
réduction statique de JSON comme une validation modèle.

- [x] **R1 — valider le premier aval V14 avec le vrai 9B.** Travailler sur deux copies
  identiques de la DB minute : baseline flags OFF, shadow avec
  `MLOMEGA_E64_CONVERSATION_EPISODES=1` et `MLOMEGA_E64_SHARED_FACTS=1`. Appeler
  uniquement `run_v14_5_post_conversation` puis `run_v14_6_post_conversation`, pas Life
  ni CloseDay complet. Les stages attendus sont `v14_people_identity`,
  `v14_people_open_loops` et `v14_interpersonal_state`. Relire
  `night_prompt_projections_v19` et `night_llm_windows_v19` pour appels/tokens/temps,
  puis les tables `v14_5_*` et `v14_6_*`. Vérifier : tous les IDs de tours restaurés,
  toutes les listes du schéma présentes, dix responsabilités interpersonnelles écrites,
  aucune identité inventée et aucun feedback de la conversation courante. Open-loops
  peut faire zéro appel seulement avec `outcome_tracker.open_loops=valid_empty`.
  **STOP** si la projection entraîne plus d'appels, un champ/writer vide par régression,
  une preuve invalide ou une conclusion moins prudente; sinon consigner le gain réel.
  **Verdict acquis** : GO shadow avec les mesures I2.4b ci-dessus; aucune activation par
  défaut avant l'équivalence globale R3.

- [x] **R2 — raccorder les quatre seuls agrégateurs LLM journaliers à I2.** Le runner
  `brainlive_brain2_coordination_v15_12.py` possède trois stages orchestrés :
  `coordination_day_package`, `coordination_watch_bindings` et
  `coordination_reconciliation`; `brain2_life_model_updater_v15_13.py` ajoute
  `life_model_patch`. Construire une projection journalière centrale et paginée depuis
  les faits/capacités I2, avec digest, PK sources, bornes temporelles et verdict de
  couverture. Enregistrer ces quatre buts dans `prompt_projection`, puis leurs groupes
  de responsabilités dans `hierarchical_json`; ne pas créer quatre compacteurs locaux.
  Détail obligatoire par stage :
  - `coordination_day_package` : compiler d'abord par code moments observés, prédictions,
    interventions, silences et outcomes vers `DAY_PACKAGE_SCHEMA`; appeler le 9B
    seulement pour un résumé ambigu réellement absent des faits. Writer conservé :
    `brainlive_day_packages`;
  - `coordination_watch_bindings` : tester une compilation déterministe des prédictions,
    warnings, forecasts et hooks existants vers `WATCH_BINDING_SCHEMA`. Cette passe ne
    doit créer aucune nouvelle psychologie; le LLM ne reste que si une décision de
    routage non déterminable est prouvée. Writer : `brain2_live_watch_bindings`;
  - `coordination_reconciliation` : construire par code les paires comparables
    prédiction/outcome (cible, personne, horizon et temps), puis envoyer seulement les
    collisions/ambiguïtés au 9B. `non_observed` reste `unknown`, jamais `contradicted`.
    Writer : `brainlive_brain2_reconciliations`;
  - `life_model_patch` : fournir le delta de faits depuis le dernier checkpoint et le
    modèle courant comme état, pas toute la journée brute. Conserver toutes les couches
    routine/place/action preference/need/expression/trajectory/contextual self/live
    hook/affordance. L'orchestrateur peut séparer les sorties par responsabilité, mais
    la projection d'entrée commune n'est payée qu'une fois. Premier indice=`watch`;
    promotion uniquement sur répétition ou preuves indépendantes. Writers :
    `brain2_life_model_patch_*`, strata, lifecycle et tables canoniques existantes.
  V17 longitudinal, outcome watcher V19, store Life V19, émission de prédictions,
  Self Schema et `live_ready` restent des consommateurs déterministes tant qu'un appel
  réel distinct n'est pas démontré : ne pas les faire passer artificiellement au LLM.

  **R2 — état réel au 2026-07-15 :**
  - [x] Projection journalière centrale ajoutée pour les quatre buts. Le paquet jour,
    les bindings et les paires exactes de réconciliation sont compilés par code. Sur le
    clone réel : paquet `compiled_ready`, 13 bindings actionnables, deux anciennes
    sources désactivées, zéro source non résolue, réconciliation `no_candidates` et
    zéro appel LLM ajouté.
  - [x] Life reçoit les neuf couches comme index courant et un delta owner-scopé; le
    payload réel passe de **484 915 à 10 845 tokens** sans supprimer les lignes brutes.
    Le registre partagé, devenu inatteignable après un mauvais placement de fonction,
    est restauré. Les tours sans lien avec un fait durable restent en DB/manifeste et ne
    peuvent plus devenir arbitrairement une préférence de William.
  - [x] Premier indice compilé sans LLM dans
    `brain2_life_model_watch_candidates` : preuve réelle 1,18 s, zéro fenêtre LLM,
    `action_outcomes/outcome-owner-test` → `watching`, aucune ligne canonique. Rejouer la
    même source reste à 1 occurrence; deux épisodes/sources indépendants donnent
    `promotion_ready`. Une opération canonique V18 simulant la promotion a écrit la même
    PK `b2action_*` dans modèle et lifecycle, avec preuves owner-scopées.
  - [x] Garde de patch : chaque opération doit citer une nouvelle preuve durable du
    delta; une création insuffisamment répétée est forcée `very_recent/candidate/
    watch_only`, jamais `strong_live_hook`. Deux sorties Qwen ayant recyclé d'anciens
    faits ont été refusées intégralement, sans écriture partielle.
  - [x] Checkpoint durable par `(person_id, source_table, source_id, digest)` : les sources
    ne sont consommées qu'après writer réussi, un replay exact produit
    `compiled_no_life_delta`, et une révision tardive de la même PK est retraitée grâce
    au digest. Preuve clone : 21 révisions consommées au premier passage, zéro au second,
    occurrence watch inchangée à 1 et aucune fenêtre LLM.
  - [x] Préflight contexte réel : en backend llama.cpp,
    `check_close_day_preflight.py` lit `/props.default_generation_settings.n_ctx` et exige
    l'égalité exacte avec `MLOMEGA_OLLAMA_CONTEXT_POSTSTOP`. Preuve sur le serveur actif :
    24 576 = 24 576, alias `qwen9b-p1-24k-mlomega`, `ready=True`. Serveur absent, contexte
    illisible ou mismatch bloquent le ready. Une promotion ambiguë reste derrière la
    validation stricte et pourra utiliser DeepSeek; ne pas repolir le prompt Qwen 9B.

- [x] **R3 — prouver l'équivalence avant activation.** Construire une matrice versionnée
  `champ de schéma → fait/capacité source → preuve → writer historique → consommateur`.
  Exécuter baseline et shadow sur des clones, puis comparer par sens et provenance, pas
  par égalité de formulation. Exigences : chaque champ ancien encore justifié existe,
  chaque champ nouveau pointe vers une vraie source owner/date-scopée, aucune capacité
  ne passe de `produced|valid_empty|not_applicable` à « absente », aucun writer/API/
  dashboard/BrainLive n'est contourné, et la reprise ne repaye aucun appel validé.
  Mesurer appels, input/output tokens, latence et lignes écrites par stage. Garder les
  flags OFF si la couverture n'est pas 100 %, si le gain global I1+I2 n'atteint pas ×5
  contre les 169 appels, ou si la prudence épistémique baisse.

  **R3 — verdict réel au 2026-07-15 :**
  - [x] `equivalence_contract.py` couvre les **18/18 responsabilités** des quatre schémas
    et suit les wrappers V18 jusque dans leur fonction `old_*`/requête SQL réelle. Aucun
    champ, writer ou consommateur déclaré ne manque.
  - [x] Comparaison V14 baseline/shadow : 10/10 responsabilités, couverture de preuve
    shadow 100 % sur profils/modèles/boucles. Le premier verdict était rouge car un
    locuteur non résolu recevait 0,85 de confiance relationnelle et 0,90 de boucle sur une
    seule minute. Le writer conserve toutes les sorties mais borne désormais les huit
    familles conversationnelles à 0,65; replay du vrai JSON shadow : huit familles
    réécrites, max=0,65, comparaison finale sans régression.
  - [x] Preuve runtime sur les deux clones R2 : paquet `compiled_ready` avec 7/7 champs;
    13 bindings actifs et zéro source physique invalide; coordination `ok`, zéro paire
    comparable; Life 21 sources consommées, zéro absente, replay à zéro et un watch
    idempotent. **87 tests** élargis verts.
  - [x] Les flags restent OFF : R3 prouve l'équivalence et la prudence, pas encore la
    totalité au-delà des caps. L'activation et le nouveau chiffre global appels/tokens/
    temps attendent R4/I3 et le harnais cinq minutes.

- [x] **R4 — retirer les caps sans créer de prompts géants.** Une fois R3 verte,
  remplacer les limites de coordination `200/160/120` et le `limit=120` Life par des
  pages complètes à clé stable, checkpoints atomiques et manifests
  `{source_count,included_count,digest,first_pk,last_pk}`. La page limite la RAM, jamais
  la vérité; toutes les pages doivent être parcourues ou le stage reste incomplet.
  Ajouter des tests dépassant chaque ancien cap, un kill/restart entre pages et une
  frontière d'événement traversant deux pages. Ensuite seulement relancer le harnais
  cinq minutes et le dashboard : ce run donnera le premier nouveau total autoritaire
  appels/tokens/temps, puis les projections 1 h/8 h local et DeepSeek.

  **R4 — preuve structurelle au 2026-07-15 (le benchmark cinq minutes reste I7) :**
  - [x] `night_orchestrator/paged_evidence.py` lit chaque source par keyset stable,
    journalise atomiquement digest+sortie+état de page et refuse un manifeste lorsque
    `source_count != included_count`. Une page déjà commitée n'est réutilisée que si son
    contenu relu a le même digest; une modification de ligne invalide seulement sa page.
  - [x] Coordination : `limit=200/160/120` signifie désormais taille de page. Les
    observations vision sont réduites dans chaque page, puis les atomes adjacents sont
    refusionnés avec recalcul des transitions à la frontière. Le paquet stocke les
    atomes+manifest, pas une deuxième copie de toutes les observations. Preuve synthétique
    au-delà des caps : **201 observations → 5 pages → 1 atome/201 refs**, puis
    **161 prédictions → 161 bindings**, sans LLM.
  - [x] Life : collecteur V18 canonique, bridge BrainLive, modèle courant et lifecycle
    parcourent toutes les pages; les couches canoniques courantes sont l'état du modèle,
    jamais un delta autorisé à s'auto-confirmer. Les tours sont tous parcourus mais seuls
    ceux cités par une preuve durable sont accumulés pour le prompt. Preuve : **121
    behavior signals** et **121 routines courantes** en quatre pages chacun.
  - [x] Reprise : tests kill après transformation/avant commit et après commit/avant page
    suivante; le premier recalcule la page, le second reprend sa sortie+état sans double
    traitement. Une scène identique traversant une frontière reste un seul événement.
  - [x] Gap découvert pendant R4 : V18 cherchait `CANONICAL_TABLES` dans le module V15.10
    qui ne l'expose pas; les neuf couches du modèle courant étaient donc vides dans ce
    feed. Mapping V18 explicite branché et prouvé sur clone réel :
    `9/4/9/22/12/9/10/9/8` lignes. Le digest de reprise Life couvre maintenant le contenu
    courant, pas seulement ses compteurs.
  - [x] Clone réel : 199 observations couvertes en quatre pages et un atome; forecast
    multi-page complet; 26 manifests Life tous complets. Suite élargie : **93 tests
    passés**. Les flags restent OFF jusqu'au harnais cinq minutes et aux métriques I7.

#### I3 — totalité d'une journée sans caps silencieux

- [x] **I3.1 Coordination** : remplacer `collect_day_evidence(limit=200)` et `_compact(...200)` par pagination complète des `VisionChangeAtom` + parents; tests 201/201 et clone 199/199. Le gate vidéo doit encore confirmer 698/698 (OBS-35 corrigé en code, I7 ouvert).
- [x] **I3.2 Life Model** : supprimer les `LIMIT 120`/`rows[:120]` comme sémantique; collecteur, bridge, état courant et lifecycle paginés, manifests par famille et tests 121/121 (OBS-36 corrigé).
- [x] **I3.3 Mémoire bornée** : journal page+digest+sortie+état par clé stable; vision réduite avant accumulation, tours Life non cités non accumulés; reprise exacte testée avant/après commit. Les listes sémantiques finales restent les sorties métier, jamais des copies arbitrairement tronquées du raw.

#### I4 — vision lourde : analyser moins de pixels, pas moins d'événements

- [x] **I4.1 Sélection avec couverture** : keyframe sur changement de scène/objet/action/personne, OCR, demande utilisateur et intervalle de sécurité; chaque frame écartée pointe vers la keyframe/atome représentatif. Les 11 images de la vidéo référence servent de baseline, pas de quota arbitraire.

> **Suivi I4.1 — FAIT 2026-07-16 (notes, texte intouché) :**
> - **Cause racine trouvée** du « 1 sélectionnée/0 analysée » : `select_keyframes_for_bundle` (module de base, appelé par l'override `install_deep`) était un QUOTA d'échantillonnage régulier (`max_keyframes=12`, `candidates[i]`) qui droppait silencieusement toute autre frame sans couverture — sur les DB réelles, 472 frames sur 473 perdues.
> - Nouvelle politique centrale `night_orchestrator/deep_vision_selection.py` : keyframe sur (a) nouvel `VisionChangeAtom` (changement réel, jitter de confiance jamais), (b) OCR (`visible_text`), (c) demande utilisateur réelle (marqueur ou focus dans `brainlive_sensor_events`/`raw_timeline`), (d) intervalle de sécurité `MLOMEGA_DEEP_VISION_SAFETY_INTERVAL_S` (60 s). Plus de `rows[:N]` ; plafond pathologique optionnel (OFF) qui RÉTROGRADE en représentées, ne jette jamais.
> - Couverture : table additive `deep_vision_frame_coverage_v19` (PK person/date/bundle/frame, idempotente) — chaque frame écartée pointe sa keyframe/atome ; manifeste 100 %.
> - Mesure (clones scratch, DBs sources intactes) : **5 min réel = 473 frames → 121 keyframes (120 changement + 1 sécurité) + 352 représentées = 473/473, 0 orpheline** (ancienne politique : 1 keyframe, 472 perdues) ; **minute statique = 1 keyframe, 200/200** — le contraste attendu. Writers (`brainlive_deep_vision_runs_v161`) et gate I0.4 inchangés.
> - Tests : 11 nouveaux (`test_e64i_deep_vision_selection.py`) + 46 non-rég verts (1 échec pré-existant tokenizer confirmé via stash).
> - **Point ouvert pour I4.2** : 120 atomes reflètent le churn de track-ids ; 121 keyframes × ~80 s/image serait cher. Option à trancher avec la vraie passe VLM : politique « label-set » track-agnostique (78 changements) ou regroupement des micro-transitions — décision I4.2, pas une réduction arbitraire.
- [x] **I4.2 Backend et cache** : Qwen3-VL 8B local, `think=false`, format strict, budget sortie mesuré; cache seulement par `sha(image)+modèle+version prompt`. Un retry ne repaye pas une image déjà validée.

> **Suivi I4.2 — FAIT 2026-07-16 (notes, texte intouché) — inclut l'arbitrage Codex sur la sélection :**
> - **Sélection (option b Codex)** : signature d'état track-agnostique (multiset de labels + people_count + texte + lieu/scène ; churn de track_id seul = 0 keyframe) + regroupement des micro-transitions (`MLOMEGA_DEEP_VISION_MICRO_TRANSITION_WINDOW_S`, défaut 2,5 s ; flip bref A→B→A = flicker droppé). Mesure clone 5 min : **120 → 44 keyframes** (window 1 s = 69 ; 5 s = 28), couverture **100 %** (428 représentées, 0 orphelin). Limite documentée : les observations réelles ne portent pas de bbox → un pur déplacement à labels constants n'ouvre pas de keyframe (frame couverte quand même). Le réducteur lossless `vision_atoms.py` est INCHANGÉ (provenance/couverture).
> - **Backend réel (`v18_poststop_outputs.install_deep`)** : l'override retombait sur `settings.ollama_model` = **qwen3.5:9b TEXTE** sans var d'env — corrigé par `_resolve_offline_vlm_model()` (défaut `qwen3-vl:8b`, jamais le modèle texte). `think:false` explicite. **Découverte critique** : sur ce build Ollama, qwen3-vl:8b renvoie le JSON dans le champ `thinking` et laisse `response` VIDE même avec think:false+format:json → lecture de secours ajoutée, l'analyse n'est plus perdue en « JSON vide ». Validation stricte (objet sans champs requis = échec explicite, jamais appliqué ni caché).
> - **Cache** `deep_vision_vlm_cache_v19` : clé `sha256(image)+modèle exact+DEEP_VISION_PROMPT_VERSION` ; hit prouvé = **8 ms, 0 appel réseau** ; bump de version prompt ou autre modèle = miss.
> - **Statut honnête** : sélectionnées>0 & analysées=0 → `retryable_error/failed` (jamais ok), partiel → `degraded` — aligné sur le gate I0.4.
> - **Appel réel unique prouvé** (vraie keyframe de la session 5 min) : JSON valide décrivant la vraie scène (personne sur canapé gris, polo blanc, lampe...), froid **15 539 ms**, sortie **665 tokens** (num_predict 900 OK).
> - Tests : 14 sélection (2 adaptés volontairement au regroupement, justifiés) + 7 backend (nouveau `test_e64i_deep_vision_backend.py`) + 10 capability manifest verts ; régression large 72 verts (1 échec pré-existant tokenizer).
> - **Pour I4.4 (assigné par Codex, non corrigé ici)** : `except: pass` avalant les erreurs de persistance de couverture — `brainlive_offline_deep_vision_v16_1.py` lignes 482-486 — devra empêcher un manifeste faussement complet.
- [x] **I4.3 Réemploi** : VisionRT live fournit détection/tracking; Deep Vision ajoute la sémantique aux keyframes; `visual_consolidation` réutilise ces sorties par code et n'est pas supprimé comme faux doublon.

> **Suivi I4.3 — FAIT 2026-07-16 (notes, texte intouché) :**
> - **Raccord tracé** : VisionRT écrit `visual_events_v19` (bbox dans `observation_json`, frame joignable via `visual_evidence_assets_v19`) ; Deep Vision (post_stop, AVANT visual_consolidation dans l'ordre close-day) écrit `brainlive_deep_vision_observations_v161` + cache. `run_visual_consolidation` ne lisait RIEN de Deep Vision.
> - **Réemploi par code** : passe additive `reuse_deep_vision_outputs` dans `v19_visual_consolidation.py` — jointure person/date/bundle/frame des observations VLM validées avec les events VisionRT, table additive `visual_consolidation_deep_reuse_v19` avec `source_refs` vers l'analyse d'origine. **Zéro appel VLM** ; writers/`summary_id` historiques intacts.
> - **Limite I4.2 comblée** : `load_visionrt_frame_positions` injecte les bbox de `visual_events_v19` dans la sélection → un déplacement majeur à labels constants ouvre une keyframe (`MLOMEGA_DEEP_VISION_SPATIAL_MOVE_THRESHOLD`, défaut 0.20).
> - **Fallbacks explicites** : pas d'observations validées → `status=absent` ; observation sans bbox → `reused_no_position` (dégradé documenté, jamais silencieux ni faux-complet). **Zéro doublon** au rejeu (upsert par `reuse_id` stable).
> - Tests : 5 nouveaux (`test_e64i_visual_reuse.py`) — réemploi 0 réseau, mouvement conservé, 2 fallbacks, idempotence — + suite e64i complète **111 verts** (3 skips env pré-existants). Vidéo complète/CloseDay non relancés (réservés I4.4).
>
> **Correction contre-audit Codex (2026-07-16) — 3 raccords fermés :**
> - **Bbox pixels normalisées** : VisionRT émet des bbox en PIXELS ; `_spatial_signature` supposait du 0–1 (tout clampé → déplacements invisibles en réel). Fix : `load_frame_dimensions` (priorités documentées : vision_frames.width/height → metadata_json → en-tête PNG/JPEG du keyframe stocké, qui est le même buffer que le détecteur) + `normalize_frame_positions` (une frame sans dimensions résolubles = SKIP explicite + phase event `deep_vision_position_dims_unavailable`, jamais de clamp silencieux). Test en pixels réalistes 1280×720 : le déplacement majeur ouvre bien une keyframe.
> - **Sémantiques consommées par les writers historiques** : le réemploi tourne désormais AVANT l'agrégation ; les activités/localisations VLM validées alimentent le résumé `scene_session_summaries_v19` (`observed_activities`, `deep_vision_locations`, refs vers les analyses d'origine) ET les routines/mouvements : un événement VisionRT sans lieu live prend la localisation Deep Vision de sa frame comme lieu (avec ref `deep_vision_location_hint` dans la provenance de la routine). Plus un simple compteur.
> - **Multi-objets par frame** : `vrt_by_frame` ne gardait qu'une ligne — toutes les détections d'une frame sont conservées (identité de frame via les refs `frame:<id>` réelles de worldbrain), le réemploi référence CHAQUE événement.
> - Tests : +3 (`test_pixel_bboxes_normalised...`, `test_multi_object_frame...`, `test_deep_semantics_feed_summary_and_routines`) → 8/8 réemploi, 42 verts sur les chemins touchés.
- [x] **I4.4 Gate** : 11/11 images référence valides ou dégradation explicite; comparer événements humains/OCR/objets à la vérité de la vidéo. Mesurer froid, chaud, images/heure et temps GPU avant projection.

> **Suivi I4.4 — FAIT 2026-07-16, VERDICT GO (réserve VRAM) :**
> - **Directive 1** : `except: pass` de persistance de couverture remplacé par `DeepVisionCoveragePersistError` structurée, consommée par les DEUX runners (base + override V18) → run `blocked_coverage_persist_failed`, VLM jamais rappelé sur couverture invérifiable, capacité I0.4 `failed`, `complete=1` interdit. Test `test_coverage_persist_failure_blocks_run_and_gate`.
> - **Probe + 11 moments de vérité** (frames extraites de la vidéo référence par ffmpeg aux offsets réels ; mapping temps validé : captured_at ↔ 301,67 s de vidéo) : **10 corrects, 1 partiel (machine à café en plan trop serré, sous-engagement honnête), 0 halluciné, 0 JSON vide**. OCR réel lu (listes horaires, « Midea »).
> - **Run complet** : sélection recalculée sur le clone = **20 keyframes** (le vrai chiffre post-I4.3 — les positions VisionRT injectées ont affiné le regroupement vs les 44 estimées en I4.2), 453 représentées, **473/473 couvertes, 0 orphelin** ; 19 frames re-matérialisées par ffmpeg à leur offset (reconstruction des mêmes pixels, documentée) ; à froid `ok, selected=20, analyzed=20, quarantined=0` ; **2e passage 2,1 s, 0 appel réseau** (cache). Gate vérifié dans les deux sens (run propre → `product_validated` ; ligne stale 1/0 → `degraded`).
> - **Mesures** : froid moyenne 17,3 s, **p50 16,7 s, p95 27,1 s**, cache 2-8 ms, **~208 images/heure**, VRAM pic **7891/8192 MiB**. Projection à densité observée (walkthrough dense, pire cas) : 1 h ≈ 238 keyframes ≈ 1,1 h VLM série ; 8 h ≈ 1907 ≈ 9,2 h série — une journée réelle est bien plus statique ; sélection NON réduite pour verdir.
> - **Réserve opérationnelle** : 8 Go ne tiennent PAS P1 9B + qwen3-vl:8b simultanément (un llama-server s'est même relancé seul pendant le gate) → le pass VLM doit être séquentiel avec P1 ARRÊTÉ (`Get-Process llama-server | Stop-Process -Force`), relance ensuite via la commande canonique du BUILD_GUIDE.
> - 40/40 tests verts. Stage ciblé seulement, CloseDay complet non lancé. I0.1 fermé par I4.2+I4.4 comme prévu au plan.
>
> **Contre-audit final I4.4 — chemin produit brut fermé (2026-07-16)** : le gate
> précédent avait rematérialisé manuellement 19 JPEG par ffmpeg. Le code produit
> persistait bien 20 sélections dans `deep_vision_frame_coverage_v19`, mais
> `select_keyframes_for_bundle` supprimait ensuite silencieusement les chemins
> absents : un run brut pouvait donc annoncer `1 sélectionnée / 1 analysée` et
> redevenir vert. Correction : chaque sélection sans JPEG live est maintenant
> extraite automatiquement du clip E55 indexé qui couvre son `frame_time`, vers
> `MLOMEGA_MEDIA/keyframes/<jour>/deep_materialized/`, puis enregistrée dans
> `raw_assets` + la table additive `deep_vision_keyframe_materializations_v19`
> (le fait brut immuable `vision_frames` n'est jamais réécrit), avec SHA,
> dimensions, clip/source/offset/fenêtre
> et clamp temporel dans la provenance. Sortie stable et rejeu idempotent.
> Absence de clip/ffmpeg, extraction vide ou enregistrement DB impossible produit
> `blocked_selected_pixels_unavailable` : aucun VLM partiel n'est lancé pour le
> bundle. `brainlive_deep_vision_runs_v161` persiste désormais la triple preuve
> `selected_keyframes/readable_keyframes/analyzed_keyframes`; le manifeste I0.4
> exige leur égalité exacte et refuse aussi tout ancien run dépourvu de preuve
> `readable`. Test produit : 2 sélections, 1 JPEG live, 1 JPEG absent disponible
> uniquement dans un vrai MP4 E55 généré par ffmpeg → extraction automatique,
> provenance durable et `2=2=2`; sans clip → run `blocked`, `2/1/0`. Validation
> ciblée complète : **52 verts** (dont MediaRetention), aucun appel VLM réseau ajouté (transport fake ;
> la preuve qualité réelle 20/20 du gate précédent reste inchangée). **I4.4 est
> maintenant fermé sur le vrai chemin produit, pas seulement sur des pixels
> préparés manuellement.**

#### I5 — modèle et backend choisis par tâche, après preuve

- [ ] Garder le 9B pour EpisodeBuilder, états internes, causalité, social, réconciliation et promotion Life; tester le 4B uniquement sur chronologie/normalisation, formulation de clarification et ranking.
- [ ] Pour chaque candidat 4B : mêmes entrées/schéma, JSON strict, couverture identique, comparaison des confusions de locuteurs/contradictions/nuances. Le gain benchmarké 1,34× ne justifie aucune baisse globale.
- [ ] Comparer Ollama et llama.cpp sans confondre vitesse et quantité de sortie : tokens utiles, constats, JSON valide et qualité par seconde. Tester P1/P2/P3 seulement si la VRAM laisse BrainLive intact.
- [ ] Évaluer DeepSeek Pro après I1–I4 : critique final des seuls cas incertains ou backend nocturne candidat. Mesurer qualité, latence et coût sur le graphe réel; budget visé ≤2 EUR/jour, jamais calculé sur une cardinalité encore fausse.

#### I6 — déclenchement conditionnel et calculs déterministes

- [x] Embeddings/reranker sans LLM; `similar-case` seulement avec candidats; calibration seulement après issue; identity 9B seulement si cluster/noms ambigus; clarification seulement sur champ réellement manquant.
- [x] Assemblage, couverture, statistiques prosodiques/langue, n-grams, projections et `live_ready` restent déterministes. Un LLM ne reformule pas une table canonique qu'un writer peut mapper exactement.
- [x] Enregistrer la raison de chaque appel (`why_called`, facts lus/produits, cache hit, tokens, latence) pour prouver qu'un jour calme coûte moins sans rater un événement.

> **Suivi I6 — FAIT EN CODE 2026-07-16, mesure globale réservée à I7.** L'audit du
> chemin produit confirme retrieval embeddings + cross-encoder sans générateur,
> similar-case seulement après hits, calibration après issue et clarification seulement
> sur manque actionnable. `people_openloops_v14_5` possède désormais un garde explicite
> `identity_ambiguity_reasons` : un locuteur durablement résolu produit le contrat vide
> valide à zéro appel; voix inconnue, contradiction ou cluster non résolu conserve le 9B.
> Assemblage, coverage, prosodie/langue, n-grams, projection et compilation `live_ready`
> restent des writers/calculs déterministes.
>
> Chaque tentative réellement orchestrée et chaque reprise de checkpoint écrit maintenant
> `night_llm_call_telemetry_v19` : stage/fenêtre/attempt, modèle, `why_called`, refs et
> digest des faits lus, résumé structuré des faits produits, cache hit, budgets, tokens
> fournisseur entrée/sortie, latence, finish reason, outcome et erreur. Les réponses
> llama.cpp/Ollama propagent les compteurs réels au lieu d'une estimation seule. Tests
> I6/E64 ciblés : 75 verts au lot complet, puis 38/38 après le dernier patch fournisseur.
> I7 doit encore prouver sur cinq minutes qu'aucun appel nocturne produit ne contourne
> cette table; ce contrôle de mesure ne rouvre pas les règles I6 déjà codées.

#### I7 — validation progressive et décision de production

- [x] **Gate A — minute shadow** : I1 réel versus baseline, puis estimation aval recalculée depuis les cardinalités observées. Clos par I1.6 : 2 appels, 15 772 tokens d'entrée, 32,6 s, 1 parent + 4 sous-thèmes, Karim/Netflix séparés et 26/26 tours couverts.
- [ ] **Gate B — cinq minutes** : scénario VIKI inchangé + vidéo de référence; chaîne complète, dashboard, preuves audio/vision, reprise et comparaison qualité. Cible intermédiaire : appels réduits ≥×5 contre chemin mesuré, aucune capacité perdue.

> **Suivi Gate B fonctionnel — 2026-07-16 (commande/chaîne CLOSES, benchmark propre encore ouvert) :**
> - Session réelle `blsess_b155c05464f08c85` : 5 min audio+vidéo, 33 finals/turns
>   conversationnels, 13 transcripts de commande, 13 intents connus, zéro `unknown`.
>   Le faux compteur « routé = exécuté » est supprimé : chaque commande émet maintenant
>   un `command_execution_trace` corrélé (segment, request, device_command et effet), et
>   le fake device conserve les payloads significatifs au lieu du seul total downlink.
> - Les **13 phrases exactes** de `real_video_session.json` traversent leur handler :
>   identification de personne, deux souvenirs explicites, deux focus `what_is`, deux
>   recherches spatiales, OCR, traduction du texte, changements de scène, démarrage puis
>   avancement du mode aide, et requête mémoire. Preuve contractuelle : matrice exacte
>   13/13; les deux `retiens ...` ne sont plus volés par l'enrôlement de personne.
> - Ponts réparés pendant ce gate : admission OCR VRAM calculée en headroom (et non
>   `used_mb < budget_du_job`), `active_zone` spatial réellement propagé à WorldBrain/
>   ChangeAttention, et `traduis le texte` converti en OCR PC puis `translate_text` vers
>   le traducteur Reflex offline Android. RapidOCR reste prioritaire; sur la vraie frame
>   difficile il s'abstient et le fallback structuré `qwen3-vl:4b` lit du texte en 7,05 s,
>   avec vérité `probable` (jamais faussement `observed`).
> - CloseDay repris sans repayer les stages validés : run
>   `run_v18_66f56f15fc154e948827d4f4d53e9236` `completed`; Deep Vision autoritaire
>   `v18deepvisionrun_20639d09a5894690` = **16 sélectionnées = 16 lisibles = 16
>   analysées**; capability manifest et output manifest `complete=1`, aucun blocker.
>   Le manifeste cible désormais le `run_id` Deep Vision du post-stop courant : un ancien
>   run bloqué de la même journée ne peut plus invalider la réparation autoritaire.
> - Validation : **147 tests PC** élargis verts (146 + le test final des callbacks
>   produit VIKI), matrice ciblée finale 3/3, **Unity
>   E33 10/10** (inclut le consommateur `translate_text`). Le téléphone S25 doit encore
>   confirmer modèles offline, rendu/latence et receipts matériels; la case Gate B globale
>   reste ouverte uniquement parce qu'un **run propre one-shot** doit mesurer le gain ≥×5
>   sans mélanger les retries de mise au point (la DB de travail contient 154 tentatives
>   télémétrées issues des reprises, donc n'est pas un benchmark temporel valide).
- [ ] **Gate C — une heure synthétique réaliste** : alternance silence/conversation/déplacements/OCR/personnes, chaos réseau/LLM/VLM/disque et reprise. Prouver `1 h capture ≤1 h consolidation` sur la RTX 3070 ou mesurer précisément l'écart.
- [ ] **Gate D — huit heures** : base fraîche, multi-session/jour, aucun cap, mémoire/VRAM bornées, manifeste complet, reprise idempotente, coût cloud si utilisé. Seulement ici annoncer le temps d'une nuit.
- [ ] **Décision stop/go** : si I1+I2 ne donnent pas au moins ×5 sans perte, ne pas poursuivre les micro-optimisations; comparer architecture cloud/hybride ou matériel. Si les gates passent, fixer le backend FIRST_TRY et rendre ses préflights bloquants.

### I7-FINAL — ordre autoritaire des derniers gates (S25 volontairement en étape 4)

> **Règle pour l'exécuteur et le vérificateur.** Suivre 1→2→3→4→5. Ne pas lancer
> Gate C parce que Gate B « a déjà marché après plusieurs reprises » : la DB Gate B de
> mise au point n'est pas un benchmark. Ne pas utiliser le S25 pour déboguer une chaîne PC
> qui échoue déjà avec le faux device. Inversement, aucun test fake ne certifie Kotlin,
> permissions Android, wake word, micro/caméra, écran éteint ou receipts matériels.
> Chaque étape produit une DB et un rapport nouveaux; jamais `memory.db` utilisateur.

#### Étape finale 1 — Gate B propre, one-shot, même vidéo cinq minutes

- [x] **1.1 Préflight sans capture.** Fermer toute ancienne instance SessionHub/Unity;
  démarrer les services puis exiger `ready=true`. Depuis la racine :

  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
  .\.venv-live\Scripts\python.exe scripts\check_phoneonly_readiness.py --person-id me --deep
  ```

  STOP si le second processus sort non-zéro : corriger le check nommé (HF gated/cache,
  proxy, Qdrant, Ollama/llama.cpp et contexte, CUDA/cuDNN, VLM, disque ou venv nuit).
  Ne jamais lancer cinq minutes « pour voir » avec un préflight rouge. Ne pas changer de
  backend ou de modèle entre le preflight et le run.

> **Suivi Étape finale 1 — tentative one-shot du 2026-07-16 22:04 : ÉCHEC, preuve conservée, corrigé (notes, texte intouché) :**
> - Preuve : `tools/harness/_run/gateb-clean-20260716-220422.db/.json` + `device_report.json`. Préflight `ready=true` complet ; 13/13 commandes envoyées, 61 segments audio, 3 clips E55 — mais `/session/end` a TIMEOUT côté client (~300 s aiohttp par défaut) pendant que le drain `live_fine_intel_queue_v19` restait à 35/36 `pending` : **le llama-server P1 (~7 Go) occupait la VRAM pendant le live, le modèle live Ollama 4B ne pouvait pas tourner → drain bloqué**. Et la 13e trace (« interroge ma mémoire qui est Karim ») manquait — ask_memory bloqué avant émission.
> - **Décision Codex appliquée (commit ci-dessous), 4 chantiers** : (1) `/session/end` répond VITE (médias + drain brut + job recovery durable) puis draine le fine-intel EN ARRIÈRE-PLAN, `run_close_day` gate sur cette tâche (`phoneonly_runtime.py`) ; (2) `gpu_phase_orchestrator.py` — P1 jamais chargé pendant le live : préflight teste P1 puis L'ARRÊTE (`check_phoneonly_readiness.py` check `p1_sequential`), texte nocturne = décharge Ollama→P1, Deep Vision = stop P1→Qwen3-VL, câblé dans `brainlive_poststop_deep_flow_v15_15.py`, **gated par `MLOMEGA_GPU_PHASE_ORCHESTRATION=1`** (défaut inchangé) ; (3) traces doubles `accepted` (au routage) puis `completed|failed` (après effet) dans `live_pipeline.py` — une commande bloquée n'est plus invisible ; (4) `--end-timeout` configurable (900 s) sur le POST /session/end du harnais.
> - Tests : 41 verts `.venv-live` (dont 6 nouveaux) + orchestrateur GPU 7 + manifest 12 + close-day/multi-session/gpu_arbiter/backend verts `.venv`. **Le prochain one-shot doit poser `MLOMEGA_GPU_PHASE_ORCHESTRATION=1`** et le préflight finit avec P1 arrêté.

- [x] **1.2 Run neuf.** Retrouver le MP4 de référence réel; ne pas substituer une vidéo
  synthétique ni modifier `real_video_session.json`. Le timestamp rend DB/rapport uniques,
  donc aucune suppression de l'ancienne preuve :

  ```powershell
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $video = (Resolve-Path 'CHEMIN\VERS\LA_VIDEO_REFERENCE_5MIN.mp4').Path
  $db = "$pwd\tools\harness\_run\gateb-clean-$stamp.db"
  $report = "$pwd\tools\harness\_run\gateb-clean-$stamp.json"
  .\.venv-live\Scripts\python.exe tools\harness\run_harness.py `
    --port 8730 --db $db --media $video `
    --scenario tools\harness\scenarios\real_video_session.json `
    --duration 305 --with-close-day --out $report
  ```

  Une seule exécution autorisée. Si elle échoue, garder DB/log/report, expliquer la cause
  et corriger; ne pas relancer dans la même DB pour fabriquer un vert.

> **Suivi Étape finale 1 — série one-shots 2026-07-17 (runs #3/#4/#5, chaque preuve conservée dans `tools/harness/_run/`, texte intouché) :**
> - **#3** (`gateb-clean-20260717-111325` / `-115157`) : drain fine-intel en 404 — le client Ollama sans `model=` explicite retombait sur l'alias P1 sous `MLOMEGA_LLM_BACKEND=llamacpp`. Fix : `OllamaJsonClient(backend="ollama")` sur tout le tier live (commit 43208fd).
> - **#4** (`gateb-clean-20260717-121607`) : 13/13 commandes `accepted`, terminaux complets (12 completed + 1 `cancelled_session_end` honnête), 2 UI intents — mais drain fine-intel tronqué `finish_reason=length` (drainé en phase live : num_ctx 4096). Fix : drain enveloppé dans `phase("post_stop_fine_intel")` (commit 36d4049).
> - **#5** (`gateb-clean-20260717-123305`) : régression AMONT — live dégradé (6808 chunks, 1965 drops, pic file 3000, `audio_inflight=1` = un unique callback audio bloqué), `/session/end` 500 car le TimeoutError du drain brut partait AVANT la création du job recovery. Verdict Codex : le vrai trou est `GpuPhaseOrchestrator.enter_live()` qui ne décharge rien et n'est appelé nulle part en production.
> - **Plan correctif Codex 7 points — points 2 à 6 appliqués (ce commit)** : (2) vraie frontière `prepare_live_gpu()` (stop P1 → `/api/ps` → éviction de tout modèle sauf le 4B live → re-vérification, ÉCHEC si VLM/9B résiste, log modèles+VRAM), appelée en `finally` du préflight ET au démarrage réel de `PhoneOnlyRuntime.start()` ; (3) job recovery durable créé AVANT le drain audio brut dans `end_session_only` ; (4) recovery fine-intel avec client explicite `base_url`/`model` live/`backend="ollama"` ; (5) annulation réelle des commandes interactives — `cancel_event` token vérifié au chokepoint d'effet `_push_intent` (UIIntent/TTS refusés, compteur `command_effects_suppressed`) + le drain ATTEND la fin réelle des workers avant CloseDay (timeouts LLM/VLM des handlers tous finis) ; (6) télémétrie worker audio `current_stage`/`inflight_seconds` (resample→vad→asr→archive) dans `audiort.py`, surfacée `/metrics` + device report.
> - Tests : orchestrateur GPU 11 verts `.venv` ; `.venv-live` 55/56 — **1 échec non tranché** `test_offer_creates_runtime_and_end_is_authenticated` (`close_day` encore `running` après 0,5 s de poll ; reproduit seul ; environnement Ollama/P1 pourtant propre) — à trancher avant/pendant le replay 60 s.
> - **Point 7 Codex = OBLIGATOIRE avant tout Gate B #6** : replay 60 s, GO seulement si aucun modèle lourd dans `/api/ps` au démarrage, `audio_chunks_dropped=0`, file finale 0, pic proche des runs sains (<1000), aucun callback audio bloqué, job recovery créé avant toute attente faillible. Interdits : allonger le timeout du drain brut, agrandir la file audio.

> **Suivi Étape finale 1 — fermeture réserves Codex + replay 60 s GO + run #6 du 2026-07-17 23:33 (preuves conservées, texte intouché) :**
> - **Réserves Codex fermées (ce commit)** : test HTTP fake hermétisé (`_release_core_live_caches` monkeypatché — c'était bien lui : 56/56 verts ensuite) ; `prepare_live_gpu()` échoue explicitement si un llama-server ÉTRANGER répond encore sur 8080 (`foreign_p1_probe` injectable + test, échec avant tout trafic Ollama) ; succès de la frontière hors de `recent_errors` (attribut `prepare_live_gpu_result`) ; gate d'annulation ajouté à `_push_device_command` (couvre `set_tts`) ; **worker interactif encore vivant après le budget total → `TimeoutError`, CloseDay bloqué** (plus jamais « continue pendant qu'un thread peut écrire »). Tests : 12 verts `.venv`, 56 verts `.venv-live`.
> - **Préflight profond vert** (p1_sequential ok, prepare_live_gpu ok). Le premier échec `p1_sequential` était un llama-server manuel résiduel sur 8080 — validation grandeur nature du scénario « P1 étranger ».
> - **Replay 60 s (`replay60-20260717-230644`) : GO, 7/7 critères** — 0 drop / file finale 0 / pic 115 / callback `idle`, `inflight=0.0 s` / Ollama vide + 8080 fermé au départ / job recovery 21:08:10.997 PUIS scellement 21:08:12.215 / aucun faux completed (drain honnêtement `running`). Le FAIL harnais `session_ended: 0` est une course de snapshot (assertion lue avant le scellement d'arrière-plan — DB : `status=ended`). Résidu observé APRÈS le post-stop du replay : **qwen3.5:9b résident dans Ollama** (source à identifier — la frontière l'évince au start suivant, mais quelque chose charge le 9B via Ollama en post-stop sous backend llamacpp).
> - **Run #6 (`gateb-clean-20260717-233354`) : ÉCHEC net d'une SEULE couche, tout l'amont enfin vert.** Live parfait : 10965 chunks, **0 drop**, file finale 0, **pic 611** (plage saine 624–670), callback `idle`. 13/13 événements → **13 accepted + 13 completed + 1 cancelled_session_end** en DB, 2 UI intents. Session scellée. Fine-intel **36/36 completed** (les bugs #3/#4 sont morts). Deep audio ok, **Deep Vision 9/9/9 selected=readable=analyzed**. CloseDay `blocked` — gate lossless honnête : `detail_windows_incomplete:quarantined=1`. Cause unique : fenêtre `brain2_conversation_detail` index 6 (`nlw_c8a2f6f26b89cd9ca5b0148e`, 12 203 tokens in, budget out 4096) : **2 tentatives `contract_rejected`, finish=stop, sorties identiques (962 tokens)** → quarantaine. Télémétrie texte totale : 8 appels (6 validated + 2 rejected), ~53,5k tokens in / ~4,5k out — à comparer au baseline 169 appels/1,119 M quand le run sera vert.
> - **Deux trous d'observabilité/robustesse pour décision Codex** : (a) le MOTIF précis du rejet de contrat n'est pas persisté (`error_text="invalid output (contract)"`, `facts_produced={}`, pas de sortie brute) ; (b) le retry est déterministe (même input, même sortie rejetée au token près) donc le 2e essai ne peut jamais réussir. Ne pas relancer avant l'arbitrage.

> **Suivi Étape finale 1 — plan Codex post-#6 appliqué + REPRISE DB #6 : CloseDay et recovery COMPLETED (2026-07-18, texte intouché) :**
> - **Plan Codex 5 points livré** (commits 7b6ef5b + celui-ci) : (1) rejets de contrat persistés (`night_llm_contract_rejections_v19` : sortie brute/parsée, digests, règle/chemin JSON/attendu/reçu, tokens, stratégie) + un retry strictement identique (même input_digest+output_digest+violations) NE PART JAMAIS ; (2) échelle déterministe sans température : réparation locale (syntaxe) → prompt de réparation ciblé (violations citées) → split en 2 sous-fenêtres contiguës + merge + verify_coverage lossless → quarantaine seulement après ; (3) test faux-LLM « 2× la même sortie invalide → le 2e appel ne part jamais » (compteur) ; (4) `enter_text()` évince TOUS les résidents Ollama, vérifie vide, échec explicite sinon, PUIS P1 + traçage phase/modèle/backend/caller de chaque requête `OllamaJsonClient` — consommateur 9B-via-Ollama identifié : `OllamaProvider._core_client(model=None)` retombait sur `settings.ollama_model` en phase post-stop → épinglé au 4B live ; (5) `cancelled_session_end` → `cancel_requested` NON terminal + colonne additive `response_suppressed=1` sur le terminal.
> - **Requeue des quarantaines héritées (ce commit)** : la 1re reprise ne retentait PAS la fenêtre (quarantaine = état terminal à la reprise). Fix executor : une fenêtre quarantinée `invalid output (contract)` SANS ligne d'audit de rejet (= antérieure à l'échelle, l'état exact de la DB #6) est re-pilotée quand une stratégie alternative existe ; une quarantaine post-échelle reste terminale. Test dédié (3 runs : quarantaine → requeue+résolution → terminal). Piège commande : `run_phoneonly_close_day.py` sans `--package-date` prend la date du JOUR (passé minuit → close-day du 18 introuvable) — toujours passer `--package-date 2026-07-17` en reprise.
> - **REPRISE RÉUSSIE sur la DB #6** (`gateb-clean-20260717-233354`, logs `-resume*.log/.exit` conservés) : les 6 fenêtres vertes reprises par checkpoint (6 `checkpoint_reuse`, zéro appel repayé), Deep Audio/Deep Vision réutilisés (même run post-stop `run_v18_5439b…`), la fenêtre 6 re-pilotée : 1 appel audité — **vraie règle violée enfin visible : `detail_normalized_output_none` (normalize_detail_window_output → None)** — puis interdiction du retry identique → split en enfants 6001/6002 tous deux `completed`, parent `subdivided contract_rejection_resolved_by_split`. Flow post-stop `ok`, **CloseDay `completed` (00:17:41), recovery `completed` (00:26:52, via `recover_abandoned_phoneonly_sessions` produit)**, manifests output/capability complets, maintenance `completed`. Ligne `blocked` résiduelle du 2026-07-18 = la 1re reprise sans `--package-date` (preuve conservée, inoffensive).
> - Télémétrie nuit cumulée sur la DB : 22 `validated` + 2 rejets historiques ≈ 24 appels, ~227k tokens in / ~31k out — vs baseline 169 appels / 1,119 M tokens (≈×7 appels, ≈×5 tokens). Mesure formelle 1.4 réservée au prochain one-shot propre.

> **Suivi Étape finale 1 — one-shot complet du 2026-07-18 14:11 + fermeture des deux latences live (preuve conservée, code final à rejouer une fois) :**
> - **Run neuf réellement complet** : `tools/harness/_run/gateb-clean-20260718-141124.db/.json` et `device_report.json`, harnais `ok=true`, huit checks sur huit. Live : 11 883 chunks, zéro drop audio, pic file 282, 63 segments archivés, 3 clips E55, 333 frames détecteur, 13 événements, 13 intents, zéro `unknown`, session et peer fermés. Nuit : CloseDay/recovery/maintenance/fine-intel `completed`; Deep Vision **7 sélectionnées = 7 lisibles = 7 analysées**, 338 frames couvertes, zéro orpheline; manifests complets, aucune capacité obligatoire perdue.
> - **Mesure autoritaire de ce one-shot** : CloseDay **841 s (14 min 01)**, 20 appels LLM validés, **147 072 tokens entrée / 29 216 sortie**, somme des inférences ~571 s. Contre baseline 169 appels / 1,119 M / 83 min : gain ×8,45 sur les appels, ×7,6 sur l'entrée et ×5,9 sur la durée. La case 1.4 est close; ce n'est pas encore une projection 1 h/8 h.
> - Le rapport a révélé quatre libellés explicites laissés au classifieur 4B : deux `what_is` devenaient `replay`, `lis le texte` devenait Maps, et la mémoire tardive était annulée à la fermeture. La grammaire de haute confiance traite désormais uniquement les formes explicites `what_is|ocr|translate|ask_memory`; le langage indirect reste LLM-first. Le replay live ciblé `gateb-live-proof-20260718-144532` prouve les quatre routes corrigées, 11 796 chunks, zéro drop et 13 accepted; son snapshot précède la terminaison de la treizième commande, visible ensuite `completed` en DB.
> - **Mode Aide** : le plan LLM synchrone retenait le DataChannel ordonné 60 s; `étape suivante` ne pouvait arriver qu'après le timeout. En produit seulement, génération désormais asynchrone, carte `help_planning` immédiate, contrôles reçus pendant le calcul mis en file, dernière étape comptée, et frontière GPU/fermeture attend le worker. Preuve réelle 4B : retour **1 ms**, plan valide en 64,9 s sur machine occupée, contrôle appliqué, index 1/2, zéro rejet. La latence du modèle reste visible mais l'Ultralive n'est plus gelé.
> - **Requête mémoire explicite** : l'ancien `qui est Karim` payait cinq appels et envoyait 80 candidats/363 193 caractères au 4B, puis tronquait ou finissait en ~83–87 s. Le fast path n'est activé que pour une identité explicite : route relation/raw/vector déterministe, candidats complets persistés, projection prompt bornée (8 preuves avec IDs/temps/texte), puis **une synthèse Brain2** spécialisée fait/inférence/preuve. Preuve réelle sur la DB : **7,95 s à chaud**, réponse grounded sur le rendez-vous du 14, source Brain2; aucun moteur profond n'est supprimé pour les autres questions.
> - Tests courts après corrections : **109 passed** (`test_help_mode.py`, `test_e33_intents.py`, `test_phoneonly_runtime.py`). Les deux fichiers Unity déjà modifiés localement restent hors de ce lot. **Seule réserve Gate B** : refaire à la reprise un unique one-shot avec ce HEAD pour obtenir les 13 effets et la nuit dans le même rapport final; ne pas repayer ce run maintenant. Puis ouvrir le Dashboard (1.5).

> **Suivi Étape finale 1 — one-shots exact-HEAD du 2026-07-18 17:40 et 18:11 : fonctionnel clos, une réserve VLM ouverte :**
> - `gateb-clean-20260718-174037` a fermé toute la nuit (18 appels validés, 118 802 tokens entrée, 19 338 sortie, 774,6 s, zéro rejet, Deep Vision 15=15=15, 433/433 couvertes), mais a exposé un faux vert outillage : 13 terminaux durables en DB contre seulement 12 effets reçus par le device. La commande mémoire tardive avait pris 83 s et terminé après fermeture (`response_suppressed=1`). Cause : le Brain2 live héritait du backend global nocturne `llamacpp` et chargeait P1 pendant la capture. Correction : override `ContextVar` limité au worker live, tout Brain2 live reste sur le 4B Ollama chaud; jamais de mutation process-wide. Mini-gate réel : Brain2 11,6 s, `fast_person_routes=1`, source Brain2. Le harnais exige désormais, pour la matrice complète, 13 accepted + 13 terminaux visibles/completed/handled, zéro suppressed/unknown. Tests : 83 live + 40 core verts.
> - `gateb-clean-20260718-181143` prouve la correction : 13/13 effets visibles avant fermeture, aucun `cancel_requested`, 11 706 chunks, zéro drop, pic 348, Aide plan+advance, mémoire Brain2 terminée. **Verdict fonctionnel 1.3 = GO.** Le Gate B global reste STOP : Deep Vision a sélectionné/lisait 7/7 mais analysé 6; une réponse `qwen3-vl:8b` était un JSON tronqué (`Unterminated string ... char 2946`), observation quarantinée, post-stop/CloseDay bloqués honnêtement et recovery en erreur. Prochaine reprise : ajouter une réparation/retry VLM bornée et auditée pour `invalid_json` (jamais réduire la couverture), reprendre cette DB seulement comme preuve de correction, puis faire un one-shot neuf pour le GO global et 1.5 Dashboard.

> **Suivi Gate B après retrait de l'activation qualité owner — 2026-07-18 21:56.**
> Le run frais `tools/harness/_run/gateb-rollback-20260718-215615.db` confirme le chemin
> produit restauré : 10 429 chunks audio, zéro drop, 63 segments, 3 clips et 13/13
> commandes terminées. Le premier post-stop a bloqué avant Brain2 sur un cas latent :
> WhisperX avait émis un tour entièrement situé dans une plage de silence synthétique du
> tape Deep Audio. Le tour sans aucun chevauchement avec un morceau audio source est
> désormais exclu de Brain2 mais conservé intégralement dans
> `metadata.source_audio_quarantine`; les tours réellement sourcés restent inchangés et
> une transcription entièrement non sourcée reste bloquante. La reprise du même
> `live_session_id=blsess_9386c1ee6906b2a5` a ensuite terminé Deep Audio, Deep Vision
> **15=15=15**, Brain2 V13/V14, coordination, longitudinal, Life Model, maintenance et les
> deux manifests (`complete=1`, `cleanup_eligible=1`). La recovery produit a reconnu ce
> CloseDay déjà couvert en 1,5 s et est passée `completed`, sans rejouer les moteurs.
> Le statut CLI Windows est maintenant imprimable en UTF-8; l'ancien exit 1 provenait
> uniquement de CP1252 après la réussite durable. Cette preuve est volontairement qualifiée
> **live frais + reprise nocturne**, pas nouveau benchmark one-shot; la mesure autoritaire
> de performance reste le one-shot vert `gateb-clean-20260718-141124`.

- [x] **1.3 Verdict fonctionnel.** Exiger dans le rapport : 13 événements envoyés, 13
  `command_execution_trace` corrélées aux textes exacts, `handled=true`, zéro `unknown`,
  aucun effet `error`; vérifier les payloads, pas seulement `intents_routed=13`. Exiger
  audio réel, clip E55, turns BrainLive, OCR non vide ou abstention explicite, recherche
  spatiale honnête, aide start+advance, deux faits mémorisés et requête mémoire. Toute
  commande « routée » sans UI/device/effect = FAIL.

- [x] **1.4 Verdict nocturne et performance.** Exiger CloseDay `completed`, recovery
  `completed`, output/capability manifests complets, Deep Vision
  `selected=readable=analyzed`, zéro capacité obligatoire `degraded|bypassed|failed`,
  aucune page/cap silencieux. Relever dans `night_llm_call_telemetry_v19` appels validés,
  retries, checkpoint reuse, tokens entrée/sortie, latence par stage et durée post-stop.
  Comparer au baseline autoritaire de la fixture auditée (169 appels / 1,119 M tokens /
  83 min), en signalant que ce n'est pas exactement la même durée si la cardinalité
  diffère. GO intermédiaire seulement si aucune capacité ne baisse et gain chaîne ≥×5;
  sinon STOP et décision architecture/modèle, pas une nouvelle micro-optimisation aveugle.

- [ ] **1.5 Dashboard sur la DB du run uniquement.** Dans une deuxième console :

  ```powershell
  $env:MLOMEGA_DB = $db
  .\scripts\RUN_DASHBOARD.ps1
  # ouvrir http://localhost:8720
  ```

  Vérifier épisodes/parents/sous-thèmes, tours sources, personnes, événements visuels,
  Life Model, prédictions/outcomes, preuves et absence de doublons. Conserver captures et
  jugement humain dans le rapport Gate B; le dashboard ne doit jamais écrire la DB.

#### Étape finale 2 — profil CloseDay PRO optionnel et auditeur shadow borné

> **Principe non négociable.** Le chemin validé reste le défaut et le rollback : Ollama 4B
> pour le live, llama.cpp/P1 pour le texte nocturne, WhisperX local et Qwen3-VL 8B. Le
> profil cloud n'existe qu'avec `-Pro` / `--pro` et ne change jamais le live : seul le
> sous-processus CloseDay reçoit DeepSeek. Le choix arrêté le 19 juillet 2026 est
> DeepSeek V4 Pro non-thinking pour le texte, Groq `whisper-large-v3` pour la transcription
> nocturne et Gemini `gemini-3.1-flash-lite` pour les keyframes. MiniMax et Together sont
> écartés de cette première intégration afin de ne pas maintenir quatre branches.

- [x] **2.1 Providers PRO branchés sans perdre le local (code, contrats et micro-appels
  fournisseurs réels verts; Gate B PRO ouvert).** `RUN_MLOMEGA_V19.ps1 -LivePhone -Pro`,
  `run_harness.py --pro` et `run_phoneonly_close_day.py --pro` sélectionnent le profil.
  Sans flag, aucune variable cloud n'est posée et les blocs Ollama/llama.cpp historiques
  sont inchangés. Le SessionHub garde `MLOMEGA_LLM_BACKEND=ollama` pendant la capture;
  `_run_close_day_subprocess` applique DeepSeek uniquement dans la copie d'environnement
  du worker nocturne. Test de frontière réel au niveau subprocess ajouté.

  **Implémentation autoritaire du lot :**

  - `cloud_budget_v19.py` crée `cloud_cost_ledger_v19`. Chaque requête réserve sous
    `BEGIN IMMEDIATE`, puis réconcilie tokens cache hit/miss, sortie, secondes audio,
    images, latence, HTTP, retries, tarif et euros. Budget par défaut **1,50 EUR/jour**;
    `stop|flash|local`; aucune clé, donnée ou prompt dans la table;
    `/metrics` et le résultat CloseDay exposent le résumé courant sans muter la DB;
  - `cloud_providers_v19.py` utilise uniquement la bibliothèque standard. DeepSeek V4 Pro
    conserve chaque system/prompt historique intact, désactive thinking, exige JSON et
    place d'abord un bundle canonique stable. Un warm-up par bundle construit le préfixe;
    les moteurs suivants réutilisent exactement les mêmes messages initiaux. Le cache est
    compté depuis l'usage fournisseur, jamais supposé. Backoff 429/5xx et sémaphore par
    défaut à 12 (`MLOMEGA_CLOUD_MAX_IN_FLIGHT`, max 40);
  - Groq remplace seulement la transcription Whisper dans Deep Audio. Alignment WhisperX,
    Pyannote, SpeechBrain, assemblage et writers restent locaux. Les WAV >24 MiB deviennent
    un FLAC lossless temporaire afin de rester sous la limite d'upload; le fichier est
    supprimé en `finally`;
  - Gemini remplace seulement l'appel Qwen3-VL. Sélection de keyframes, cache image,
    provenance, validation, writers et égalité `selected=readable=analyzed` restent les
    mêmes. Modèle exact : `gemini-3.1-flash-lite` (le 2.5 est refusé aux nouveaux comptes
    même si son endpoint catalogue répond encore); le preflight exige aussi la méthode
    `generateContent`;
  - le préflight authentifie les trois APIs et vérifie les IDs de modèles avant capture,
    sans appel payant et sans exposer les secrets. Les clés vont dans `.env` ignoré :
    `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`;
  - preuves sans réseau : `test_cloud_pro_v19.py` 9/9, suites Deep Audio/Vision/GPU 31/31,
    runtime PhoneOnly 43/43. Micro-appels réels : DeepSeek JSON strict, Groq WAV 12 s →
    1 segment, Gemini image → JSON structuré (1 115 tokens entrée/11 sortie). Le premier
    Gate B `--pro` a ensuite révélé le blocage EpisodeBuilder décrit en 2.1-B; ne pas
    déclarer la qualité fournisseur avant la preuve bout-en-bout finale.

- [ ] **2.1-B — EpisodeBuilder local validé, puis moteurs parallèles en PRO, sans toucher au
  local par défaut.** Passation autoritaire : `docs/PRO_CLOSEDAY_HANDOFF.md`. État mesuré du run
  `gateb-pro-20260719-185246` : Groq et Gemini 18/18/18 passent; projection DeepSeek
  532 041→49 026 tokens et cache réel ~50 304 tokens hit/appel; réponses de détail riches
  mais rejetées par `detail_normalized_output_none`, donc zéro épisode matérialisé et
  fan-out moteur non atteint. Décision : ne plus demander EpisodeBuilder à DeepSeek.
  Exécuter exactement l'EpisodeBuilder P1/llama.cpp déjà validé, commit des épisodes, arrêt
  P1, puis un warm-up DeepSeek par épisode et fan-out 8→12 des couples épisode×moteur avec
  connexions séparées, barrières du DAG réel et writers ordonnés. Un appel reste distinct
  par moteur; aucune fusion de schémas. Test faux-P1/faux-DeepSeek, reprise checkpointée,
  puis un Gate B neuf ≤120 s post-stop. Le chemin sans `--pro` garde impérativement
  `episode-pack-v2`, ses providers et son ordre actuel.

  Avant ce run payant, fermer aussi la récupération des réservations cloud interrompues :
  persister l'identité du run et la frontière `reserved → in_flight` avant HTTP; seule une
  absence d'envoi prouvée autorise `released`, tandis qu'un appel possiblement envoyé reste
  `uncertain` et compté au pire cas. Tests crash/concurrence/idempotence obligatoires. Ne
  jamais supprimer manuellement les réservations du run interrompu pour récupérer du
  budget. Détails et commandes dans `docs/PRO_CLOSEDAY_HANDOFF.md`.

> **Suivi 2.1-B — chantiers livrés + série Gate B PRO du 2026-07-20 (preuves conservées, texte intouché) :**
> - **Chantiers 1-3 livrés** (b860486 + 2be9334 + 5a6d376, 122+ tests verts, baseline locale 84 inchangée) : EpisodeBuilder épinglé llamacpp en PRO (client explicite + `llm_client_override`, 3 voies) ; frontière physique `pro_local_text_phase()` (éviction → P1 vérifié → build+commit → stop P1 en `finally`) ; `warm_bundle_prefix` idempotent + UNE attente settle ; OBS-70 fermé (`run_id`/`worker_id`/`sent_at`, `reserved→in_flight` avant HTTP, recovery `released` seulement sur non-émission prouvée, sinon `uncertain`).
> - **Trois pièges opérateur fermés en route** : (a) `--pro` ne posait pas `MLOMEGA_PRO_CLOSEDAY=1` (reprise CLI directe → EpisodeBuilder reparti à DeepSeek, 0,0127 € de preuve) ; (b) label modèle `ollama-json` générique dans les clés de fenêtres = collision avec l'essai DeepSeek → fallback canonique `p1_alias()` ; (c) reçu `deep_preflight_receipt` : le préflight doit tourner dans le MÊME processus/env que le harnais (fingerprint budget/modèles/orchestration) — intégré au lanceur.
> - **Run 012416** : live 13/13 + Groq/Gemini completed + ZÉRO ligne DeepSeek EpisodeBuilder — mais `segmentation_llm_failed:unavailable` : la branche `text_cloud` d'`enter_text` (backend deepseek = pas de P1) court-circuitait la frontière épisodes → fix `enter_text(force_local_p1=True)` (5a6d376, test dans les deux sens).
> - **Run 014448** : P1 démarré par la frontière (ready en 6 s), UN appel segmentation (~10 s) → **`segmentation_not_lossless`** : la segmentation 9B single-call n'a pas couvert les 137 tours du flux Groq (fillers de queue omis). Vérif structurelle demandée par Codex faite AVANT tout code : AUCUN bug d'assemblage Groq (63 segments audio + ~68 tours des deux côtés, PRO 69 / local 68 ; l'assemblage reste local). Cause unique = le single-call n'est pas lossless par construction (exige une frontière sur le dernier tour) ; le chemin fenêtré force le dernier segment sur le dernier tour primaire = lossless par construction.
> - **Segmentation unifiée (83f5486, 128 verts)** : en PRO, toute segmentation passe par `_run_segmentation_windows` même si ça tient en un appel ; ce chemin reçoit désormais `describe_contract_violation`/`resolve_contract_rejection` (hérite de l'échelle de l'exécuteur : rejet audité, retry identique interdit, split contigu → merge lossless → quarantaine). Local sans flag byte-for-byte inchangé. Device non prouvé (`device:11000:11900`) tranché : chaîne accepted→completed OK, la commande « etape suivante » a juste été classée `unknown` par le 4B → variance de routage live (one-off, non-bloquant ; 012416 faisait 13/13+2 sur le même scénario).
> - **Reprise 014448 (checkpoints, Groq/Gemini non repayés) : segmentation ENFIN `completed` lossless — nouveau bloqueur EN AVAL sur le DÉTAIL.** `detail_windows_incomplete:quarantined=1` : la fenêtre détail 4 = **un seul segment de ~41 tours à 14662 tokens > budget**, `attempts=0` → `single unit exceeds input budget` → quarantaine (un segment unique ne peut pas être coupé par le `subdivide` du planner, qui halve les unités primaires). Cause : le fenêtrage produit des segments plus GROSSIERS que le single-call — quand le 9B émet peu de frontières internes dans une fenêtre de ~40 tours, la frontière forcée collapse la fenêtre entière en UN segment (lossless mais trop gros pour un appel détail). Le local single-call voyait les 137 tours d'un coup → frontières fines → jamais ce mur. **Fan-out DeepSeek toujours pas traversé** (0 appel : bloque avant). Budget jour ≈ 0,026 €.
> - **Option A tranchée par Codex, implémentée (efaa367 + 972c831 + fa738a2, 157+ verts)** : (1) chemin over-budget de l'exécuteur → si le `subdivide` du planner ne peut pas halve une unité unique, appeler le resolver de l'étage (découpe par tours), motif `single_unit_exceeds_input_budget` + splits audités ; (2) check de succès des resolvers détail+segmentation compte les LEAVES à toute profondeur (un enfant subdivisé n'est pas un leaf) — le split multi-niveau ne quarantine plus le parent ; (3) réassemblage détail trié par position globale du 1er tour (depth-safe, plus de collision `part_index`) ; (4) quarantaine over-budget NON-finale à la reprise (budget hors clé de checkpoint, re-drive idempotent).
> - **JALON : PREMIÈRE traversée complète du fan-out DeepSeek (reprise 014448, 2026-07-20).** EpisodeBuilder P1 local abouti (segmentation lossless + détail avec segment de 41 tours découpé par ses tours, 1 épisode) ; **les 16 moteurs cognitifs ont produit une sortie via DeepSeek** (capture/langage/contexte/état interne/social/causalité/contradiction/choix/outcome/pattern/cas similaires/prédiction/simulation/calibration/intervention). Coût jour 0,096 € (deepseek 12 appels/158k tok, gemini 17, groq 1) sous plafond 1,44. ZÉRO ligne `episode_builder` au ledger.
> - **Nouveau bloqueur (le plus profond) + fix** : `pattern_miner field tasks quarantined ×3`, `single unit exceeds input budget` ~29082 tokens. Cause : `_run_engine_partitioned` plafonnait `context_window` à `ollama_context_poststop` (24k P1 local) MÊME en PRO, alors que le préfixe bundle épisode (~29k, la conversation entière en préfixe cache) dépasse 24k et DeepSeek gère 128k. Fix : budget = contexte cloud réel en PRO (`MLOMEGA_CLOUD_CONTEXT_POSTSTOP`, défaut 65536), local inchangé.
> - **POINT DE VIGILANCE pour Codex : `cache_hit_tokens=0` (tous miss) sur les 12 appels DeepSeek de ce run.** Le warm-up/cache par épisode n'a pas mordu (attendu : « cache hit réel par épisode »). Coût/perf, pas correctness — à investiguer (1 seul épisode → 1 warm-up puis 12 appels moteurs devraient hit le préfixe ; soit le warm-up n'a pas tourné à la reprise, soit le préfixe n'est pas aligné octet pour octet entre warm-up et appels moteurs, soit la barrière settle a été sautée en reprise). Ne pas déclarer GATE B PRO GO tant que le cache ne mord pas et que la chaîne globale (pattern→intervention) n'a pas fini.
>
> **★★★ MILESTONE 2026-07-21 : GATE B PRO COMPLET — ALL PASS, CloseDay `completed` de bout en bout (run propre gateb-pro-20260721-114834, DB fraîche). ★★★**
> - **Chaîne PRO entière validée** : live 13/13 effets prouvés → Groq Deep Audio → Gemini Deep Vision 12 → EpisodeBuilder P1 local → 16 moteurs DeepSeek → v14_people → v14_clarification_inbox → life_model → coordination → … → **CloseDay completed + recovery completed**. Harnais E63 : **ALL PASS**.
> - **Qualité vérifiée (vraies réponses DeepSeek, grounded, honnêtes)** : épisode fidèle (Karim/le 14/avertissement/réparation objet/Maxime import-export bateau+voiture/Netflix/Nolan/Grèce antique) ; language_signature cite les turn_id exacts ; pattern_miner trouve « Casual Planning with Warning » ; prediction_engine assume l'incertitude (conf 0,333 + counter_evidence, zéro hallucination) ; life_model `operations:[]` conservateur (pas de trait durable sur 5 min sans preuve répétée — invariant respecté).
> - **Chiffres run PROPRE À FROID (5 min, ledger vierge)** : coût **0,326 €** (deepseek 0,305 / gemini 0,013 / groq 0,008), cache DeepSeek **17 %** (froid — vs 92-97 % en warm sur reprises), close-day **~14 min** (le fan-out warm faisait ~80 s). 29 appels DeepSeek, 20,9 s/appel.
> - **Série de fixes « limites P1 local appliquées au cloud » (tous gated PRO, local byte-for-byte inchangé)** : DAG dépendances directes + projection faits par dépendance + empreinte globale (transcript retiré) → 1,47M → ~250k tokens ; registre canonique 32k→9k (~100 tok/fait, `case_ids` retiré) ; **plafond contexte 24k→56k + sortie 4096→8192** = **1 appel/moteur au lieu de 27 fenêtres** (LA cause de lenteur) ; warm/probe cache fiable (2 warms + probe, fan-out gated sur `prompt_cache_hit_tokens>0`) ; quarantaines over-budget ET length re-pilotées à la reprise ; engine_name réel au ledger. Fixes Codex intégrés : v14_people (plafond épistémique 16), clarification_inbox (output cloud 8k). life_model : abstention d'une opération sans preuve durable owner-scoped au lieu de bloquer (autorisation utilisateur, gated PRO, local garde le raise dur).
> - **no-think CONFIRMÉ actif** sur DeepSeek (`thinking:{type:disabled}`) et Gemini (`thinkingBudget:0`) — les dépassements de sortie venaient de la verbosité d'un modèle plus gros que le 9B, pas d'un raisonnement caché.
> - **RESTE pour la prod (le seul manque) : point 10 Codex — budget dur 1,50 €/jour + fallback local.** Extrapolation : une journée dense (~20-40 épisodes) dépasserait probablement 1,50 € à froid (1ᵉʳ épisode froid ~0,33 €, suivants warm ~0,05 €). Le budget dur + bascule P1 local garantit le plafond. Optionnel : vérifier le warm-up inter-épisodes dans un même close-day.
>
> **★★★ MILESTONE 2026-07-23 : GATE B PRO FLASH SOUS 0,10 € — ALL PASS, DB FRAÎCHE. ★★★**
> - Preuve : `tools/harness/_run/gateb-pro-target-20260723-143534.db` (artefact ignoré, conservé localement). Live réel rejoué 305 s, **13/13 effets de commandes prouvés**, 2 UI intents, 63 segments, 3 clips; Deep Audio, Deep Vision **11=11=11**, EpisodeBuilder P1 local, V13/V14/V17/V18/Life, manifests, maintenance, **CloseDay completed et recovery completed**. Harnais E63 : **ALL PASS**.
> - Coût réel complet : **0,0575646 €**, sous un plafond dur fixé à **0,10 €** (`stop`) : DeepSeek Flash 26 appels / 251 105 tokens entrée / 38 075 sortie = 0,0378854 €; Gemini 11 images = 0,0123231 €; Groq 305 s = 0,0073561 €. Aucun fallback, aucune capacité retirée.
> - Cause du gain : le wrapper PRO ajoutait à chaque moteur une copie conversationnelle d'environ 60k tokens alors que les moteurs Brain2 recevaient déjà leur bundle d'épisode ou leur projection canonique. Le cache DeepSeek « best effort » ne persistait pas ce tronc entre schémas variables (prouvé par micro-tests réels). Le chemin normal retire donc **uniquement ce doublon de transport**; prompts métier, schémas, projections, writers et chemin local sont inchangés. Rollback explicite : `MLOMEGA_PRO_REDUNDANT_CONVERSATION_PREFIX=1`.
> - Temps de référence à préserver : **406,069 s de CloseDay**, **463,475 s de la fin de session au CloseDay completed**, 469,071 s jusqu'à recovery completed. Le coût et la correction fonctionnelle sont **GO**; l'objectif temps « post-live ≤300 s » reste **OUVERT**. Toute optimisation suivante doit battre ce jalon sans régression et sans remettre le préfixe redondant.
> - Tests ciblés avant le one-shot : **107 verts** sur providers/budget crash-safe, fan-out/DAG/projections, segmentation et exécuteur. Le run complet constitue la preuve produit, pas les seuls tests.
>
> **★★★ MILESTONE 2026-07-23 16:00 : LOT LATENCE PRO — ALL PASS SOUS 0,10 €, CIBLE 300 S NON ATTEINTE. ★★★**
> - Preuve fraîche : `tools/harness/_run/gateb-pro-final2-20260723-160047.db`. Live 305 s, **13/13 effets**, 2 UI, 63 segments, 3 clips, Deep Vision **26=26=26**, tous les moteurs et manifests, CloseDay/maintenance/recovery `completed`; harnais **ALL PASS**.
> - Coût complet **0,088460618 €** : Flash 45 appels/396 212 tokens entrée/49 907 sortie = 0,052312972 €; Gemini 26 images = 0,028791867 €; Groq 287,66 s = 0,007355779 €. Aucun fallback.
> - Temps honnête : `post_stop` **379,299 s**, CloseDay **388,229 s**, fin live→recovery **402,590 s**. Les 26 keyframes du walkthrough dense (24 `scene_object_person_change` + 2 `safety_interval`, contre 13+2 puis 6+3 sur les runs précédents) ont placé Deep Vision à 106,880 s; aucun quota n'a été augmenté. Deep Audio 43,226 s est entièrement masqué par le chevauchement. **Le gate ≤300 s reste ouvert**, sans droit de réduire les preuves pour le cocher.
> - Livré, PRO-only : EpisodeBuilder Flash opt-in avec contrats/writers inchangés; Deep Audio↔Gemini concurrents; fine-intel Flash en lots concurrents avec writes ordonnés; V17 cases chevauché avec V14. Sans `MLOMEGA_PRO_CLOSEDAY`, le chemin local reste historique.
> - OBS contrat fermé : un identifiant visuel `v18deepaddendum_*` cité en plus des vrais tours dans `evidence_turn_ids` faisait bloquer le parent après des fenêtres pourtant complètes. La normalisation garde uniquement les vrais tours du segment, préserve la provenance visuelle séparément et refuse toujours zéro preuve vocale. Reprise checkpointée du run `gateb-pro-final-20260723-154417` ensuite `completed`.
> - Qualité Flash : meilleure abstention et promotions Life Model conservatrices; les relations de voix inconnues restent à auditer après enrôlement vocal. Prochaine étape décidée par l'utilisateur : audit shadow, puis éventuelle comparaison MiniMax M3, sans remplacement du local/PRO validé.

  **Texte DeepSeek :**

  - préflight obligatoire de `DEEPSEEK_API_KEY`, endpoint, modèle, JSON strict, contexte,
    latence et solde/budget; jamais écrire la clé dans DB/log/rapport;
  - adapter V4 à l'interface `WindowLLM` et à l'orchestrateur existant : mêmes prompts,
    schémas, fenêtres, merge, checkpoints, couverture et writers; aucune version parallèle
    des moteurs V13/V14/V17/V18/Life;
  - `deepseek-v4-pro` est le défaut PRO pour mesurer le saut maximal de qualité sans
    routage opaque. `deepseek-v4-flash` est sélectionnable explicitement ou utilisé lorsque
    la politique budgétaire vaut `flash` et que la réservation Pro dépasserait le plafond;
  - le live/Ultralive reste sur Ollama 4B local. Une panne cloud pendant une nuit marquée
    `--deepseek` est `blocked/retryable`; aucun mélange silencieux cloud/local. Un fallback
    local éventuel exige un flag distinct et doit être inscrit dans le capability manifest;
  - ne jamais créer un faux `--deepseek-vlm` tant que l'API officielle reste text-only.

  **Alternative MiniMax M3 (écartée pour ce lot, historique seulement) :** ajouter `--minimax`, mutuellement exclusif avec
  `--deepseek`. Le profil utilise M3 pour le texte et `API-vlm`/M3 multimodal pour la
  vision, sans modifier prompts, schemas, writers ou gates. L'offre Plus actuelle est
  20 $/mois pour ~1,7 B tokens M3 et un quota multimodal partagé. Aucun dépassement payant
  si la Subscription Key n'a ni Credits ni clé Pay-As-You-Go associée : vérifier
  `/v1/token_plan/remains` avant et pendant CloseDay, puis bloquer/reprendre localement à
  quota nul. Quotas 5 h/hebdomadaires et throttling imposent checkpoint/retry; le local
  reste le défaut et le secours. M3 et DeepSeek Pro sont du même niveau général mesuré,
  très au-dessus du Qwen 9B local attendu; le shadow doit seulement prouver JSON, preuves,
  qualité centrée William, temps et consommation sur notre charge réelle.

  **Vision Together optionnelle (écartée; les calculs ci-dessous restent historiques) :**

  - adapter l'endpoint OpenAI-compatible Together à l'interface Deep Vision existante,
    modèle initial `Qwen/Qwen3.5-9B`, reasoning désactivé, même prompt, même JSON Schema,
    mêmes keyframes, mêmes writers et même gate `selected=readable=analyzed`; aucune
    seconde chaîne visuelle;
  - `--together-vlm` remplace uniquement l'inférence Qwen3-VL nocturne. VisionRT live,
    sélection déterministe, clips E55, matérialisation, couverture et cache de résultats
    restent locaux. Une panne cloud est `blocked/retryable`, jamais une analyse vide;
  - préflight obligatoire de `TOGETHER_API_KEY`, modèle réellement image-capable, petite
    image de probe, JSON strict, rate-limit courant et budget; clé absente ou modèle retiré
    = refus avant capture. La clé ne va ni en DB, ni en log, ni dans le manifeste;
  - tarification conservatrice au 19 juillet 2026 : 0,17 $/M tokens input et 0,25 $/M
    output. Together facture une image par tuiles de 560 px, au plus 4 × 1 601 = 6 404
    tokens. Avec ~665 tokens JSON observés, une keyframe coûte environ 0,00125 $ /
    0,00110 € avant marge. Retenir **0,0013 €/image** dans la réservation avec marge 15 %;
  - projection à vérifier, pas à vendre comme acquise : 7–15 keyframes/5 min donnent
    84–180 appels/h et ~0,11–0,23 €/h; le walkthrough I4 dense (~208 images/h) donne
    ~0,27 €/h. Une journée de dix heures peut donc dépasser 1 € rien qu'en vision : le
    plafond doit arrêter avant envoi, jamais après facturation;
  - ne pas déclarer Together « moins cher » sans mesure. Contrôle officiel à la même date :
    Gemini 3.1 Flash-Lite facture 0,25 $/M input et 1,50 $/M output, mais seulement 258
    tokens par tuile 768×768. Avec le JSON observé (~665 tokens), il vaut environ
    0,00106–0,00126 $/frame en standard, donc proche ou légèrement moins cher que Together;
    son batch publié divise ces tarifs par deux. Together garde l'avantage d'une sortie
    six fois moins chère et d'un modèle Qwen proche du local. Le verdict porte sur
    **€/JSON accepté**, qualité et latence murale, pas sur le prix input isolé;
  - le cache Together n'est pas présumé : `Qwen/Qwen3.5-9B` ne présente pas actuellement
    de tarif cached-input officiel et chaque image change. Persister les éventuels
    `cached_tokens`, mais budgéter chaque keyframe comme un miss complet;
  - l'appel standard est retenu pour la première intégration. Le Batch API peut finir de
    petits lots en quelques minutes et offre jusqu'à 50 % seulement sur modèles éligibles;
    ne pas compter cette remise ni sa latence avant confirmation que ce modèle précis est
    éligible. Le mode batch, s'il est ajouté, conserve `custom_id=frame_id`, inspecte le
    fichier d'erreurs et réassemble dans l'ordre déterministe des keyframes.

  **Gestion du temps requête/retour :** avant activation, faire un shadow Together puis
  Gemini sur les 20 vraies keyframes I4.4, puis seulement le gagnant sur toutes celles du
  run 30 min. Mesurer séparément upload/base64,
  time-to-first-byte, génération JSON, validation et latence bout-en-bout; publier p50,
  p95, maximum, 429/5xx et retries. Tester concurrence 1/2/3/4 avec `AsyncTogether` : les
  frames indépendantes peuvent partir en parallèle, mais les résultats sont persistés par
  ordre `(timestamp, frame_id)`. Choisir la plus petite concurrence qui réduit le mur sans
  429; timeout borné et deux retries jitter maximum. Gemini reçoit le même test de
  concurrence et un test batch distinct; son batch ne devient pas le défaut si le retour
  est trop tardif pour la fenêtre nocturne. Le GO exige : qualité ≥ Qwen3-VL 8B local sur
  les 11 moments de vérité, 0 JSON vide, couverture 100 %, coût projeté sous le plafond et
  temps total mesuré inférieur au local (p50 local observé ~16–17 s/image). Ne conserver
  qu'un provider VLM cloud en production; l'autre reste un adaptateur shadow, pas une
  troisième branche à maintenir.

  **Gate A/B avant activation produit.** Sur des clones d'une même DB, comparer texte
  local/Flash/Pro-hybride/MiniMax M3 et vision locale/Together/Gemini/MiniMax, chacun
  isolément puis ensemble :
  sorties champ par champ, preuves, abstentions, contradictions, promotions, nombre
  d'appels, cache, tokens, latence et coût. GO seulement si toutes les capacités/manifests
  restent complètes, aucune preuve n'est perdue, qualité humaine au moins égale et reprise
  idempotente. Le provider doit persister dans
  `night_llm_call_telemetry_v19` : backend, modèle, thinking, cache hit/miss tokens,
  input/output, images/tuiles, latence détaillée, concurrence, retries, coût calculé et
  snapshot de tarif.

  **Plafond quotidien dur multi-provider.** Défaut
  `MLOMEGA_CLOUD_DAILY_BUDGET_EUR=1.50` (alias de compatibilité temporaire
  `MLOMEGA_DEEPSEEK_DAILY_BUDGET_EUR`), partagé par DeepSeek/MiniMax, le VLM cloud,
  CloseDay et outils
  shadow. Avant chaque appel, réserver atomiquement le pire coût input+output+image; après
  réponse, réconcilier avec l'usage réellement retourné. Le cache DeepSeek est un gain
  mesuré, jamais supposé : premier appel miss,
  hit uniquement sur préfixe strictement identique, sortie toujours payante. Si l'appel
  dépasserait le plafond, arrêter avant envoi avec état explicite; ne jamais tronquer une
  capacité pour tenir le budget. Baseline réelle cinq minutes : 18–20 appels,
  118 802–147 072 tokens in, 19 338–29 216 out. Projection sans cache V4 Pro :
  ~0,30–0,59 € pour une heure normale, ~0,72–0,94 € pour une heure aussi dense que la
  vidéo, ~1,80–2,35 € pour 60 min de parole; Flash : ~0,10–0,19 €, ~0,23–0,30 € et
  ~0,58–0,75 €. Ajouter une marge de tokenizer/tarif de 15 % au stop/go.

- [x] **2.2 Outil owner/qualité shadow : usage, coût et autorité strictement bornés.** Les
  fichiers existants `owner_quality_gate.py`, `owner_quality_truth.json`,
  `owner_context_v19` et `prediction_policy_v19` restent hors produit. Le précédent essai
  de raccord aux writers/compilateurs a régressé Brain2 et a été restauré exactement au
  parent `7d417be`; ne pas le réintroduire indirectement. Contrat :

  - `owner_quality_shadow.py` est un nouvel outil manuel; l'ancien
    `owner_quality_gate.py` et ses prompts restent intacts. La source est ouverte en `ro`
    pendant le devis et les appels, et l'inférence travaille sur un clone neuf;
  - premier passage obligatoire `--plan-only`, **sans aucun appel** : inventorier par
    stage moteur les items candidats, appels prévus, tokens input/output réservés,
    keyframes et tuiles image, checkpoints/cache réutilisables, coût min/max par provider
    et estimation murale. Afficher ce devis avant toute demande payante;
  - exécution uniquement avec `--execute --plan <devis>`. Le texte est audité par
    `deepseek-v4-pro`; la vision réutilise les observations persistées
    (`--vision-backend existing`) et ne repaye aucune image. Pas de tâche planifiée chaque
    nuit et pas d'appel en arrière-plan sans commande;
  - journaliser chaque appel/retour : stage, digest sans donnée sensible, provider/modèle,
    cache/checkpoint hit, tokens texte/image/output, heure départ, TTFB, heure retour,
    validation JSON, retry, statut HTTP et coût. Le résumé rapproche **prévu vs réel** et
    explique tout écart; une ligne sans réponse n'est jamais comptée comme succès;
  - mesurer doublons, contradictions possibles, faits sans preuve, promotions trop rapides,
    prédictions invérifiables, dépassements de plafond de confiance et remplissage de
    schéma. Les anomalies SQL certaines ne consomment aucun appel; seuls les cas ambigus
    partent par petits lots vers Pro;
  - `--apply-safe` ne donne jamais du SQL au modèle. DeepSeek classe uniquement les IDs du
    devis; toute cible hors candidat est refusée. Le code sauvegarde la DB, vérifie le SHA,
    ouvre une transaction et n'autorise que deux effets : clamp déterministe
    `confidence<=confidence_ceiling`, et overlays durables
    `owner_quality_shadow_*_v19` pour masquer dans le Dashboard les doublons exacts/fillers.
    Aucun fait n'est supprimé, aucune preuve n'est perdue, les cas ambigus restent annotés.
    `foreign_key_check` + `quick_check` sont obligatoires; toute erreur restaure le backup;
  - partager le ledger/plafond cloud de 1 €/jour entre DeepSeek et le VLM cloud. Si le CloseDay
    a consommé le budget, le shadow ne part pas; override manuel séparé avec estimation
    affichée avant accord. La réservation est atomique avant chaque appel et libérée ou
    réconciliée au retour, afin que des appels parallèles ne dépassent jamais ensemble le
    plafond;
  - devis réel sans appel sur `gateb-pro-final2-20260723-160047` : 399 tables, 99 faits,
    26 observations Deep Vision réutilisées, 100 candidats dont 83 déterministes et
    seulement 17 à soumettre à DeepSeek, soit 3 appels, ~13 103 tokens entrée, 3 600 sortie
    réservée et **0,008882 € maximum avec marge 15 %**. Ce résultat remplace l'ancienne
    projection erronée qui rejouait 18 moteurs complets. Usage conseillé : manuel le jour
    OFF/hebdomadaire, jamais après chaque CloseDay;

  Interface cible, sans modifier l'ancienne commande locale :

  ```powershell
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $plan = "tools\harness\_run\owner-shadow-$stamp-plan.json"
  $report = "tools\harness\_run\owner-shadow-$stamp-report.json"
  .\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
    --db $db --owner-id me --owner-name William `
    --plan-only --text-backend deepseek --deepseek-model deepseek-v4-pro `
    --vision-backend existing --budget-eur 1.00 --out $plan
  # Lire le devis global, pas chaque ligne; puis lancer l'arbitre + application bornée :
  .\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
    --db $db --owner-id me --owner-name William `
    --execute --plan $plan --apply-safe `
    --text-backend deepseek --deepseek-model deepseek-v4-pro `
    --vision-backend existing --budget-eur 1.00 --out $report
  ```

  Le ledger partagé tient compte du coût CloseDay déjà engagé le même jour. Le rapport
  rapproche prévu/réel et donne le backup exact; le Dashboard sait le lire.

#### Étape finale 3 — Dashboard humain et spatial fiable, puis chaos réel 30 minutes

> **Remplace l'ancien Gate C synthétique d'une heure.** Ne pas construire une vidéo d'une
> heure ni boucler douze fois la fixture cinq minutes. L'objectif est d'abord de rendre la
> mémoire lisible sans écriture, fermer le trou bbox découvert, puis utiliser une vraie
> vidéo de 30 min proche du S25 pour les seules frontières chaos encore non prouvées.

- [x] **3.1 Dashboard lecture seule réellement humain.** Conserver SQLite en mode `ro` et
  supprimer/désactiver en production tout contrôle CLI d'écriture. Vérifier le SHA de la
  DB avant/après une session Dashboard. Remplacer l'heuristique « nom de table contient
  model/fact ⇒ fait sûr » par une whitelist sémantique et des adaptateurs par contrat :

  - `artifact_lineage_v176`, checkpoints, consumed_sources, manifests et IDs techniques
    vont dans un expander **Audit technique**, jamais dans « Sûr / hypothèse / prédiction »;
  - Life watch affiche `identity_key`, `candidate_kind`, occurrences, sources datées,
    statut/promotion et preuve; un `watch_id` reste un détail copiable, pas le titre;
  - faits/hypothèses/prédictions affichent statement, perspective, confiance, précédents,
    evidence refs et outcome. Ne jamais classer par défaut une ligne inconnue comme sûre;
  - JSON brut, hashes et IDs restent disponibles sous expander pour audit, mais aucune
    carte principale ne doit se réduire à un ID ou « Pas de résumé disponible » si un
    champ sémantique existe.

- [x] **3.2 Vue visuelle utile, sans rappel VLM.** Joindre `visual_events_v19`, assets,
  `brainlive_deep_vision_observations_v161` et réemploi/consolidation existants. Afficher
  miniature, résumé détaillé, activité, lieu, personnes, objets, OCR, incertitude,
  timestamp, raison de keyframe et provenance SHA. La DB finale actuelle prouve que
  **26/26** observations possèdent déjà un résumé lisible; elles sont maintenant rendues
  directement, avec miniature et incertitude.
  Un événement bbox sans résumé est présenté comme géométrie technique liée à son résumé
  Deep Vision, pas comme une carte mémoire vide.

- [ ] **3.3 Fermer le bug spatial avant toute nouvelle preuve qualité.** Sur la DB
  `gateb-rollback-20260718-215615`, 196 bbox sont affichables mais **66 sont inversées et
  90 contiennent une coordonnée négative**; 85 valeurs invalides appartiennent à
  `change_moved`. Ce n'est pas cosmétique et peut créer faux mouvements/keyframes.

  - à la frontière VisionRT, exiger valeurs finies, réordonner min/max, clamp aux vraies
    dimensions du frame détecteur, rejeter aire nulle/dégénérée et conserver la bbox brute
    dans un audit/quarantaine;
  - transporter avec chaque SceneDelta `frame_width`, `frame_height`, orientation et espace
    de coordonnées. WorldBrain ignore une bbox invalide pour mouvement/relations sans
    supprimer le label/détection sourcé;
  - la normalisation nocturne utilise les dimensions **du frame détecteur**, jamais celles
    de la miniature matérialisée. Dans la preuve actuelle, les miniatures 304×540 ne sont
    pas le même espace que les détections ~576×1024 malgré l'ancien commentaire;
  - ne pas réécrire silencieusement les anciennes DB : le Dashboard les marque
    `bbox_invalid_legacy`. Les nouvelles sessions doivent produire zéro bbox négative,
    inversée ou hors cadre et zéro `change_moved` dérivé d'une bbox rejetée;
  - tests portrait/paysage, rotation/mirror, tracker hors cadre, matériel 576×1024 puis
    miniature 304×540, multi-objets et déplacement réel. Rejouer le sélecteur sur clone :
    variation de keyframes expliquée par scènes réelles, pas par géométrie invalide.

- [x] **3.4 Gate Dashboard sans régression.** Sur la DB courante : 26 résumés
  Deep Vision lisibles, lunettes/téléphone/table retrouvables, Life watch compréhensible,
  lineage masqué par défaut, preuves ouvrables, aucune écriture et aucun appel LLM/VLM.
  Adaptateurs purs testés sur tables techniques/inconnues, Life watch, JSON visuel et bbox
  legacy; aucune requête LLM/VLM. `RUN_DASHBOARD.ps1` calcule le SHA avant/après et échoue
  s'il change. Corriger aussi
  `RUN_DASHBOARD.ps1` pour Windows PowerShell UTF-8 : la commande documentée doit ouvrir
  8720 sans passer par le lancement Python direct utilisé lors de l'audit.

- [ ] **3.5 Une seule vidéo réelle 30 min, proche de la sortie S25.** Utiliser un vrai
  enregistrement continu, jamais un montage bouclé : conserver résolution, orientation,
  fps, codec, audio et SHA; produire un `ffprobe` manifeste. Cible utile : 5–10 min de
  conversation, plages statiques, déplacements, personne, objet déplacé et court OCR. Le
  fake device conserve le même WebRTC/PC/CloseDay, mais ce run ne certifie toujours pas
  caméra/micro/Kotlin Android (Étape 4). Mesurer capture, drops, parole réelle, appels,
  tokens, cache, keyframes sélectionnées/lisibles/analysées, temps Deep Audio/Vision/texte,
  coût DeepSeek éventuel et durée jusqu'à CloseDay.

- [ ] **3.6 Chaos uniquement sur les frontières encore inconnues, sans empiler les runs.**
  Dans ce même run 30 min, scénariser et horodater : coupure réseau puis reconnexion en
  milieu de session; tentative mauvais token/second device pendant la session; après ACK
  `/session/end`, arrêt brutal SessionHub/PC puis relance de RUN et recovery. Exiger même
  BrainLive ID durable, nouveau peer unique, aucun chunk/tour/clip dupliqué, aucune commande
  attribuée au mauvais appareil, un seul CloseDay, checkpoints repris, recovery et
  manifests complets. Une panne disque se teste séparément par fault injection sur DB/
  média temporaire — ne jamais remplir le vrai disque.

  Ne pas repayer les chaos déjà prouvés par les runs Gate B : backend 404, P1/VLM résident
  et famine VRAM, proxy/HF/cuDNN préflight, sortie LLM tronquée/contrat rejeté, JSON VLM
  invalide, commandes en vol à la fermeture, drain différé, quarantaine/requeue,
  checkpoints et CloseDay bloqué puis repris. Le rapport final distingue temps actif,
  durée de panne et reprise; il ne transforme pas un run chaos en benchmark nominal.

#### Étape finale 3BIS — ALL SCENARIOS FINALE PASSE

> **Verdict du contre-audit ciblé du checkout au 2026-07-19 : pas encore GO pour tous
> les scénarios ci-dessous.** Les données et moteurs existent en grande partie, mais un
> résultat exact ne peut pas être déduit du seul fait que `MemoryQuery`, une table ou un
> `UIIntent` existe. Légende : **OK CODE** = appel productif remonté jusqu'au consommateur
> (la preuve matérielle reste en Étape 4); **PARTIEL** = les preuves sont écrites mais la
> requête/réponse attendue n'est pas garantie; **GAP** = frontière ou consommateur absent.
> Interdiction de demander au LLM de compter, choisir « le dernier » ou reconstruire une
> journée à partir d'un petit top-k vectoriel : les faits exacts sont calculés par SQL/code,
> le LLM ne reçoit ensuite qu'un paquet sourcé à expliquer.

##### 3BIS.0 — Ponts transversaux à fermer avant le scénario par scénario

- [ ] **Contrat ContextCard canonique, preuve écran et receipts. — GAP bloquant.**
  `BrainLiveSceneAdapter._enqueue()` écrit bien dans
  `brainlive_intervention_delivery_queue` et `PhoneOnlyRuntime._delivery_loop()` la draine,
  mais `delivery_adapter.delivery_row_to_ui_intent()` émet actuellement
  `content.message` alors que Unity `ContextCard.Bind()` ne lit que `text|body` : une
  suggestion BrainLive, ChangeAttention ou changement d'apparence peut arriver sous forme
  de carte vide. Le même défaut existe pour la timeline Replay (`summary` sans `text`) et
  `VisionRT what_is` (`label` sans `text`). Canonicaliser à la frontière PC une fois :
  `content.text`, `title`, `kind`, metadata utile, `truth_level`, confiance, TTL et preuves;
  conserver les champs typés additifs. Test de contrat Python→JSON→C# sur le vrai
  `ContextCard`, avec receipt `displayed`, texte non vide et `ui_intent_id` stable.

- [ ] **Vraie CardProfil consommant le cache relationnel. — GAP.** L'identification pousse
  réellement `entity_hot_update` et Unity le stocke dans `SceneCache.EntitiesHot`, mais
  aucun composant produit n'appelle `TryGetRelationPack`; `PersonTag` n'affiche que le nom
  porté par son UIIntent. Ajouter une surface `profile_card` ou une ouverture explicite du
  `PersonTag` qui relit le pack par `entity_id` : nom seulement au-dessus du seuil,
  relation, derniers sujets/promesses, changements d'apparence hypothétiques, date et
  provenance. Rafraîchir le même ID, ne jamais créer une carte à chaque frame.

- [ ] **Identité durable des attributs humains. — GAP.** `AttributeMemory` et le VLM
  d'apparence sont branchés, mais l'observation est aujourd'hui indexée par l'`entity_id`
  WorldBrain de la silhouette. Ce slot peut désigner une autre personne à la session
  suivante. Après fusion face/voix, indexer les attributs par `canonical_person_id`, garder
  l'entity/track comme provenance et rattacher les observations provisoires lors de
  l'enrôlement. Deux personnes simultanées et une personne revenant à une autre position
  ne doivent jamais partager coupe/vêtements.

- [ ] **Registre de requêtes mémoire structurées dans `MemoryQuery`. — GAP transversal.**
  Le chemin produit actuel est réel (`IntentRouter` → `MemoryQuery.ask` →
  `brain2_router_v14_2` → ContextCard), mais le routeur général ne lit pas comme sources
  structurées `scene_session_summaries_v19`, `attribute_memory_observations`, la position
  WorldBrain et toutes les chronologies visuelles. Ajouter des résolveurs bornés
  `temporal_spatial`, `last_encounter`, `topic_history`, `conflict_evidence`,
  `latest_attribute`, `current_language`, `fuzzy_episode` et `semantic_replay`. Résoudre
  alias→personne canonique, dates civiles Europe/Paris et unités avant le LLM. Chaque paquet
  porte toutes les lignes retenues, les compteurs calculés, citations ouvrables et la raison
  d'abstention.

- [ ] **SLA mémoire live honnête. — PARTIEL.** Seul « qui est X » a un raccourci
  déterministe; les autres questions peuvent encore payer planification/fusion/réponse sur
  le 4B live. Mesurer chaque résolveur. Cible : fait SQL immédiat ≤2 s; synthèse ≤15 s avec
  carte « recherche en cours » non bloquante; timeout/annulation traçables. Une réponse
  tardive après fin de session est supprimée honnêtement, jamais présentée comme réussie.

##### 3BIS.1 — Mémoire / BrainLive : statut des scénarios demandés

- [ ] **« Où étais-je le 22 février 2022 ? » — GAP.** Les résumés de session/place et
  événements peuvent contenir la réponse, mais le routeur mémoire ne fait pas la jointure
  date locale→sessions→lieux. Le résolveur `temporal_spatial` doit renvoyer une timeline
  matin/après-midi/soir, fusionner les intervalles contigus et dire « non observé » pour les
  trous; jamais extrapoler un lieu entre deux captures.

- [ ] **« Qu'a dit Karim la dernière fois que je l'ai vu ? » — PARTIEL.** Tours,
  conversations, épisodes et packs relationnels sont recherchables, mais aucun appel ne
  sélectionne explicitement la dernière rencontre de Karim. `last_encounter` doit joindre
  identité canonique, présence visuelle/vocale, intervalle de conversation, résumé et tours
  exacts; fournir date, résumé et courtes citations, ou préciser si seul un échange vocal
  sans présence visuelle est prouvé.

- [ ] **« Combien de fois Maxime m'a parlé de ce sujet ? » — GAP.** Un top-k sémantique ne
  prouve ni le nombre total ni l'évolution d'une position. `topic_history` doit résoudre le
  sujet flou, compter les conversations/mentions distinctes sans compter les chunks ou
  résumés dérivés, construire la chronologie des positions avec contre-exemples et citer le
  dernier tour. Le LLM explique la chronologie; il ne calcule jamais le compteur.

- [ ] **« Pourquoi je me suis embrouillé avec Maxime hier ? » — PARTIEL.** Brain2 possède
  états, turning points, impacts, couplings, boucles relationnelles et tours, donc le moteur
  d'analyse existe. Il manque un paquet `conflict_evidence` limité à la bonne interaction :
  état observé avant, séquence factuelle, point de bascule, après-coup et hypothèses
  explicitement séparées. Aucune intention cachée ou cause psychologique ne devient un fait.

- [ ] **« Quel était le prix de la baguette la dernière fois ? » — GAP.** OCR, faits
  entendus et `AttributeMemory` enregistrent réellement des valeurs, mais cette table n'est
  pas consommée par `MemoryQuery`. `latest_attribute` doit joindre produit, commerce/lieu,
  valeur, unité, date, modalité (`ocr|heard|vlm`) et preuve image/tour; si « baguette » et
  « prix » n'ont pas été liés dans la même preuve, demander clarification au lieu de
  rapprocher deux souvenirs.

- [x] **« Prédit-moi les prochains jours/semaines » — OK CODE, qualité à prouver.** Les
  prédictions V13/V19, trajectoires V14, Life Model et précédents/outcomes sont routés; les
  prédictions ouvertes sont aussi relues en live. Le gate 3BIS exige plusieurs horizons,
  preuves et précédents, confiance calibrée, conditions d'invalidation et zéro candidat
  `watch_only` présenté comme certain. Une DB d'un seul jour doit s'abstenir de prédire une
  « boucle » non répétée.

- [ ] **« Mon expression favorite du moment ? » — PARTIEL.** `personal_language_patterns`,
  `language_ngrams` et `phrase_templates` sont routés, mais le classement courant n'est pas
  calculé. `current_language` doit compter les expressions du propriétaire dans une fenêtre
  explicite, dédupliquer tours/artefacts dérivés, comparer à la période précédente et citer
  des exemples; ne jamais inclure les paroles de Maxime/Karim.

- [ ] **Question floue « le truc d'il y a deux semaines avec Maxime… » — PARTIEL.** La
  recherche vectorielle et les routes personne/temps existent, mais le top-k peut mélanger
  dates et interlocuteurs. `fuzzy_episode` doit appliquer personne+période comme filtres
  durs, proposer au plus trois épisodes candidats avec indice distinctif, puis demander une
  clarification si deux restent plausibles.

- [x] **« Comment ai-je réussi à faire ça ? » — OK MOTEURS, gate longitudinal requis.**
  Choix, intentions, outcomes, patterns V17, Self/Life Model et contre-exemples sont
  disponibles au routeur pour une synthèse globale. Accepter seulement une explication qui
  relie but→choix→actions→résultats sur plusieurs épisodes sourcés, distingue observation et
  recul, et refuse la profondeur artificielle sur une minute ou une seule journée.

- [ ] **Replay. — PARTIEL/GAP sémantique.** Le replay par heure/date est réellement
  branché : bundle borné, route HTTP authentifiée, images/MP4 et `VirtualScreen` Unity.
  Corriger d'abord la timeline vide décrite en 3BIS.0. « Rejoue la scène où j'étais avec X
  et où j'ai dit attention derrière » n'est pas pris en charge : la grammaire et
  `ReplayService` exigent une heure. `semantic_replay` doit retrouver l'intervalle par
  personne+phrase+événement, afficher le candidat/date, puis appeler le ReplayService
  existant; jamais inventer un timestamp.

##### 3BIS.2 — UltraLive : statut des scénarios demandés

- [ ] **Alerte avant une boucle/conflit connu — PARTIEL et UI actuellement cassée.** Les
  prédictions/interventions nocturnes sont chargées au démarrage, le contexte contient
  personne, dernier transcript et lieu, et la queue H1 est réellement drainée. Le matching
  d'intervention reste lexical et la carte peut être vide (3BIS.0). Après correction,
  utiliser des conditions typées personne canonique+sujet+état+lieu, seuil/cooldown et
  contre-preuve. Tester une intervention pertinente, une situation voisine qui doit rester
  silencieuse et le feedback dismiss/acted qui empêche la répétition.

- [ ] **« Qu'est-ce qui a changé ici ? » — PARTIEL.** La commande explicite retourne les
  `recent_changes` de WorldBrain avec texte; ChangeAttention compare aussi deux visites et
  sait formuler « lunettes ne semble plus là ». Mais son passage automatique par H1 subit
  le bug de carte vide, et PhoneOnly sans 6DoF dépend d'un `place_hint` fiable. Après fix,
  prouver avant/après, apparition/disparition/déplacement, silence première visite, silence
  sous seuil et aucun faux changement issu d'une bbox invalide (3.3).

- [x] **« Où sont les lunettes ? » — OK CODE avec limite spatiale honnête.** Le chemin
  commande→WorldBrain cherche d'abord le registre durable owner-scopé, renvoie visibilité
  actuelle ou dernière observation+âge+lieu, puis l'UI. Sur PhoneOnly, aucune pose 6DoF :
  carte de dernière position seulement; flèche/distance uniquement sur lunettes quand la
  map quality passe le seuil. Gate : deux objets identiques, objet déplacé, objet absent,
  observation périmée et aucune flèche fausse.

- [ ] **Nouvelle coupe/vêtement d'une personne connue — GAP de fiabilité.** Le crop VLM,
  `AttributeMemory`, `attribute_changed` et la queue existent, mais l'identité de stockage
  et l'affichage CardProfil ne sont pas sûrs (3BIS.0). Réparer ces deux frontières, borner
  le VLM live sans affamer Whisper/YOLOX/4B, puis tester Maxime sur deux sessions et une
  deuxième personne témoin. Afficher « changement possible » avec avant/après et preuve,
  jamais « nouvelle coupe » sur un simple angle/lumière différents.

- [x] **Zoom live — OK CODE.** Pinch→`LensWindowSkill`→UIIntent local→`LensWindow` utilise
  la vraie texture courante et `RawImage.uvRect` pour le crop GPU; le centre et le facteur
  évoluent pendant le pinch. Étape 4 vérifie geste, orientation, suivi de l'ancre, conflit
  avec manipulation de panneau et absence de readback CPU.

- [x] **OCR + traduction ponctuelle UI — OK CODE.** OCR travaille sur le frame PC,
  `translate_text` traverse le DataChannel et le modèle Reflex Android rafraîchit le
  sous-titre; absence de texte/langue non supportée est explicite. Prouver texte réel,
  nombres/prix, rotation et receipt; aucun succès si la traduction n'a pas été affichée.

- [x] **Traduction directe anglais↔français — OK CODE.** `translate_live` active le
  `TranslateBridge`, seules les finales passent dans le modèle device et le même sous-titre
  est rafraîchi sans bloquer la capture. Tester start/stop, changement de locuteur,
  partiels, résultat tardif supersédé et modèles absents.

- [x] **Mode aide naturel + UI — OK CODE.** Description libre, demande de précision,
  start/next/repeat/pause/resume/finish, TaskPanel/ancrages et watchdog sont branchés. Le
  gate matériel doit démarrer au milieu d'une action sans plan initial, suivre l'objet,
  survivre à une réponse LLM lente et ne jamais transformer « un/deux » en logique métier.

- [ ] **WorldBrain/reconstruction — PARTIEL.** Détections, tracks, changements, registre
  durable, places, relations, hot caches et consolidation sont actifs. PhoneOnly reste une
  reconstruction 2D/lieu sans pose; le niveau 3D, bearing et zones métriques appartient au
  chemin XREAL. Afficher le niveau de capacité réel dans l'UI et tester relocalisation,
  rotation, multi-objet et disparition; ne jamais appeler « carte 3D » un historique de
  bbox.

- [ ] **HotContext/interactions/suggestions — PARTIEL.** Le contexte compact, la recherche
  de précédents, les sorties nocturnes et le delivery loop sont branchés, mais 3BIS.0 rend
  encore certaines cartes invisibles et la pertinence n'a pas traversé un scénario avec
  passé réel. Gate : contexte owner+personne+lieu+sujet, suggestion visible et sourcée,
  silence non pertinent, cooldown, feedback et reprise réseau sans doublon.

- [x] **Mains, menu et Apps Maps/YouTube — OK CODE.** GestureBridge→MenuGestureController
  résout réellement la ligne par point viewport; dwell/pinch appelle le même
  `DeviceCommandHandler` que la voix. Maps/YouTube traversent Kotlin AppLauncher. Vérifier
  paume, sélection de chaque ligne, grab/resize/snap, commande vocale et receipt sur S25/
  XREAL. **TV/cast/remote n'est pas implémenté** : `VirtualScreen` vide n'est pas une app TV;
  ajouter un provider/contrat de source si « TV » signifie flux/cast réel.

- [ ] **Toutes les CardProfil à jour — GAP.** Voir 3BIS.0 : cache oui, rendu profil non.
  Tester identification, relation pack, changement, correction « ce n'est pas Maxime »,
  inconnu puis promotion et backfill; le nom disparaît immédiatement sous le seuil ou sur
  contradiction face/voix.

##### 3BIS.3 — Cas UltraLive supplémentaires indispensables

- [ ] **Épistémologie UI :** inconnu, non observé, souvenir ancien, probable et observation
  ont des rendus distincts; âge/provenance visibles; aucune carte vide; une bbox/identité
  faible ne devient jamais une flèche ou un nom.
- [ ] **Corrections et ambiguïtés :** deux lunettes/deux personnes, « pas celles-là », nom
  corrigé, lieu corrigé, objet caché/réapparu; aucune fusion irréversible ni propagation à
  la mauvaise personne.
- [ ] **Privacy et hors-ligne :** pause libère caméra, micro, ASR et transport puis reprise
  explicite; PC perdu conserve zoom/menu/ASR/wake word/traduction locale, marque les
  fonctions mémoire indisponibles et ne fabrique aucune réponse.
- [ ] **Charge et concurrence :** conversation+OCR+zoom+help+suggestion pendant tracking;
  files, VRAM, température et latence restent bornées, priorité UI correcte et aucun modèle
  VLM live ne provoque de drop audio.
- [ ] **Cycle UI complet :** chaque scénario prouve `produced→sent→parsed→admitted→displayed`
  puis `seen|acted|dismissed`; perte réseau entre deux états, redelivery même ID et aucun
  double effet. Les compteurs PC seuls ne ferment jamais la capacité.

##### 3BIS.4 — Harnais de décision avant le S25

- [ ] Ajouter une fixture versionnée `final_all_scenarios` avec au moins deux jours, lieux
  matin/après-midi, William owner enrôlé, Karim et Maxime canoniques, sujets récurrents,
  prix OCR+audio, conflit avec état avant/après, expressions, intentions/outcomes,
  prédictions, lunettes déplacées, apparence changée et phrase Replay. Les données
  synthétiques sont étiquetées et ne corroborent jamais le Life Model réel.
- [ ] Exécuter les requêtes par la vraie entrée `IntentRouter`/`MemoryQuery`, pas en appelant
  les tables directement. Assertions exactes sur compte/date/personne/valeur, couverture
  des preuves et abstention; comparaison locale puis provider cloud éventuel sur le même
  paquet structuré. Un meilleur modèle ne compense pas un résolveur absent.
- [ ] Pour UltraLive, envoyer les vrais JSON produits par Python dans les parseurs C# et le
  broker/runtime Unity; capturer payload et receipts pour chaque scénario. Un test Python
  de queue ou un EditMode avec UIIntent écrit à la main ne prouve pas la frontière.
- [ ] **GO 3BIS** seulement si tous les GAP ci-dessus sont fermés, chaque réponse attendue
  est factuellement obtenue ou s'abstient correctement, zéro carte vide, zéro confusion de
  personne, replay média lisible, suggestions non intrusives et aucun appel/latence non
  borné. Ensuite seulement construire l'APK et passer à l'Étape 4.

#### Étape finale 4 — vrai Samsung S25, APK fraîche et identité owner réelle

- [ ] **4.1 Rebuild PhoneOnly obligatoire.** Le commit `de39fef` modifie le C# Unity
  (`translate_text`) : l'ancienne APK ne contient pas le pont. Fermer Unity, puis depuis
  `apps\xr-mobile` :

  ```powershell
  $u = 'C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe'
  $env:MLOMEGA_PC_HOST = '192.168.1.199'; $env:MLOMEGA_PC_PORT = '8710'
  $p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
    '-executeMethod','MLOmega.XR.Editor.AndroidBuild.BuildApk', `
    '-logFile',"$pwd\apk-phone.log" -Wait -PassThru -NoNewWindow
  "exit=$($p.ExitCode)"
  Get-FileHash .\build\android\mlomega-phoneonly.apk -Algorithm SHA256
  ```

  GO seulement sur exit 0 + `Build succeeded` et APK fraîche. Les warnings licence 500 ne
  sont pas le verdict. Reverter uniquement les artefacts Unity générés documentés; ne pas
  écraser des modifications utilisateur de scène. Installer :

  ```powershell
  adb install -r .\build\android\mlomega-phoneonly.apk
  adb shell pm path com.mlomega.xr.phoneonly
  ```

- [ ] **4.2 PC réellement prêt avant ouverture de l'app.** Depuis la racine, même Wi-Fi,
  port 8710 privé autorisé :

  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
  .\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
  ```

  RUN exécute le preflight profond : aucun contournement manuel si rouge. Garder cette
  console ouverte; elle est le journal live.

- [ ] **4.3 Première action = enrôlement propriétaire.** Dire « configure ma voix » ou
  Menu → Ma voix, suivre la capture, puis vérifier en DB que les tours du porteur portent
  `speaker_person_id=me`/alias William et que l'autre personne reste distincte. Répéter
  avec une phrase hors commande; aucune attribution owner par simple texte/contexte. Sans
  cette preuve, toutes les conclusions personnelles du dashboard sont non certifiées.

- [ ] **4.4 Checklist matérielle minimale.** Vérifier réellement, avec rendu/receipt :
  wake word Viki; ASR/sous-titres Reflex PC joignable puis PC coupé; micro WebRTC+ASR sans
  conflit 10 min; caméra/rotation; `what_is`; clés/lunettes visibles puis déplacées et
  dernière position connue; OCR puis `translate_text` offline; personne connue/inconnue;
  ChangeAttention après retour dans une zone; mode aide start/next au milieu d'une tâche;
  deux `retiens ...` puis requête mémoire; privacy pause libérant caméra/micro; perte Wi-Fi
  et reconnexion sans double audio; arrière-plan/écran éteint 10 min; fin explicite avec
  drain→archive→BrainLive→CloseDay. Toute réponse doit être observée à l'écran ou prouvée
  par receipt/trace, jamais déduite d'un compteur PC.

- [ ] **4.5 Contrôle lendemain/dashboard.** Exiger CloseDay/manifeste complet puis lancer
  le dashboard sur cette DB. Contrôler perspective William, séparation des autres,
  souvenirs, positions, clips/replay, Life watch sans psychologie inventée et prédictions
  avec précédents. Conserver APK hash, version Android, réseau, températures, batterie,
  latences, logs et anomalies. S25 GO ne ferme pas Gate D capacité huit heures.

#### Étape finale 5 — Gate D huit heures et décision production

- [ ] **5.1 Deux preuves, sans demander huit heures de tournage.** (a) test capacité
  accéléré sur une journée temporelle de 8 h/multi-session issue du générateur Gate C;
  (b) soak temps réel overnight avec faux device, puis un pilote réel longue durée après
  le S25 court. Les répétitions synthétiques restent liées à leur source et ne corroborent
  jamais un trait. Ajouter un outil `tools/harness/run_gate_d_day.py` qui crée DB neuve,
  sessions matin/midi/soir, redémarrage PC entre deux sessions et rapport final.

- [ ] **5.2 Critères finaux.** Aucun cap silencieux; tous les événements couverts;
  mémoire/VRAM/disque bornés; multi-session/jour consolidé; CloseDay/recovery idempotents;
  rétention et archives relues; owner/relations corrects; temps et éventuel coût cloud
  mesurés. Seulement après Gate D annoncer une durée nocturne et fixer backend/modèles/
  contextes FIRST_TRY.

- [ ] **5.3 Verdict Codex indépendant.** Relire rapports B/qualité/C/S25/D et le code des
  frontières réellement exercées. GO production uniquement si zéro blocker fonctionnel,
  qualité propriétaire non régressive, SLA accepté et cas négatifs prouvés. Sinon produire
  une liste bornée de corrections avec preuve; ne pas rouvrir un audit intégral ni cocher
  une capacité au nom d'une classe, d'une route ou d'un test isolé.

#### Checkpoint Codex — activation I1/I2, frontière live et FirstTry hermétique (2026-07-15)

- [x] **Ancien chemin nocturne fermé transversalement.** `prompt_projection.py` porte une politique d'entrée centrale pour tous les préfixes produit V13/V14/V18/Life/Brain2/coordination/silent. Un nouveau stage produit non enregistré lève avant le modèle au lieu de repasser silencieusement les tours/blobs bruts. Les cas spécialisés (`engine_fields`, `engine_batch`, packs épisode/global, sensor routing) sont explicitement classés; aucun compacteur privé n'est ajouté moteur par moteur.
- [x] **I1/I2 activés après le vrai CloseDay.** `MLOMEGA_E64_CONVERSATION_EPISODES` et `MLOMEGA_E64_SHARED_FACTS` valent désormais ON par défaut; `=0` reste le rollback d'urgence. Le run réel `run_v18_3e3194ad94f044afa2443ba11ff81520` / session `blsess_31312ceee48f3925` a terminé les dix stages, manifeste relu complet, tiering/rétention/maintenance OK. Cette preuve ne ferme ni Deep Vision (1 sélectionnée, 0 analysée, 1 quarantinée) ni l'enrôlement owner absent.
- [x] **Sémantique lourde retirée du hot path PhoneOnly.** Le tour/transcript et ses écritures immédiates restent durables; hypothèses, attributs et discours fins sont mis dans `live_fine_intel_queue_v19`, traités par lots bornés et validés par cardinalité/`turn_id`. `/session/end` draine audio/turns, puis le backlog durable; CloseDay ne démarre qu'après ce drain. Une recovery reprend le même backlog, sans recalcul lourd par segment ni perte silencieuse.
- [x] **Correctifs découverts pendant le vrai run.** Pattern Mirror local conversationnel ne repaye plus 25 fenêtres/>335 k tokens pour inventer de la psychologie; le miroir long-horizon reste périodique. Proactive V14 normalise dict/list avant les colonnes SQLite TEXT. Les statuts Life `compiled_watch_only` et `compiled_no_life_delta` sont des succès explicites, pas de faux échecs CloseDay.
- [x] **FirstTry/RUN hermétique.** Bootstrap unique `runtime_environment_v19.py` partagé par RUN, SessionHub, recovery et entrypoint manuel. Le parent PowerShell prépare le PATH CUDA commun; chaque Python le revalide et charge réellement `.venv/.../cudnn_ops_infer64_8.dll`. Le gate vérifie : proxy configuré joignable (seul loopback:9 est nettoyé), compte HF réel + accès gated aux trois repos Pyannote + fichiers de poids complets en cache, ASR nocturne complet, Python 3.11/.venv exact, `transformers>=4.52,<5`, exécution torch CUDA, Qdrant, DB/media/disque (20 Go par défaut), backend/alias/contexte LLM, requête JSON stricte réelle, VLM live+lourd avec image/JSON réel, modèles device, YOLOX/ASR/TTS live. Aucun probe ne télécharge; `PREFETCH_FIRSTTRY_MODELS.py` est l'action explicite guidée hors RUN.
- [x] **Preuve machine du préflight.** Compte HF `BALLSoHigh712` et accès gated 3/3 prouvés. L'ancien cache ne contenait que les README pour diarization/segmentation : le nouveau gate l'a refusé, puis le script explicite a préchargé Pyannote 3/3 et `Systran/faster-whisper-large-v3`. cuDNN 8 est chargé réellement. Le rapport global passe toutes ces vérifications et échoue seulement sur trois états externes cohérents : backend déclaré Ollama arrêté, llama-server P1:24k orphelin sur 8080, VLM Ollama indisponibles. C'est le comportement produit attendu avant capture, pas un ready vert artificiel.
- [x] **Tests conclusifs de ce checkpoint.** 23 tests hermétiques/installation/multi-session verts; suite cœur élargie : 92 verts, 1 skip, 8 échecs attendus car `test_phoneonly_runtime` avait été lancé par erreur dans `.venv` sans aiortc/webrtcvad au lieu de `.venv-live`. La relance live a été interrompue à la demande utilisateur; ne pas présenter ces huit erreurs d'environnement comme régressions code.

**Reprise exacte, dans cet ordre :**

1. [x] **Backend choisi pour la reprise** : llama.cpp P1 alias `qwen9b-p1-24k-mlomega`, contexte 24576 pour le post-stop; Ollama démarré et modèles `qwen3.5:4b/9b`, `moondream`, `qwen3-vl:8b` présents pour live/VLM. Il reste à rendre ces trois variables persistantes dans l'environnement de RUN et à obtenir le ready complet.
2. [x] **PRÉREQUIS AVANT I4 — court, aucun CloseDay** : (a) plafonner transversalement les faits par ASR/diarisation/langue/alignement et quarantiner les changements linguistiques incohérents (I0.2/OBS-29); (b) agréger les capacités obligatoires dans le manifeste final et bloquer `complete=1` sur bypass/degraded/abstained/faux-vert (I0.4/OBS-38); (c) fenêtrer/fusionner les conversations dépassant le budget au lieu de lever `input_budget_exceeded` (I1.3), avec reprise et couverture exacte.

> **Suivi lot prérequis I0.2/I0.4/I1.3 — FAIT 2026-07-15 (notes, texte des étapes intouché) :**
> - **I0.2** : nouveau module central `src/mlomega_audio_elite/evidence_quality_v19.py` (qualité par preuve : ASR/mots WhisperX, diarisation, résolution locuteur avec `source_id` pour juger l'indépendance, langue) + application dans `brain2_shared_facts_v19.py` : `confidence_ceiling` calculé depuis les vraies preuves citées, corroboration = sources indépendantes seulement, voix non enrôlée → `owner_attribution_blocked`, fragments linguistiques incohérents → `evidence_status=quarantined` (raw durable). Statuts additifs, aucun consommateur cassé. Tests `tests/v19/test_e64i_evidence_quality.py` (7) + non-régression shared_facts/daily_projection (32) verts.
> - **I0.4** : module additif `night_orchestrator/capability_manifest.py` + gate chirurgical dans `v18_close_day.py` (après `semantic_warnings`, avant manifeste de sortie et `assert_cleanup_eligible`). 13 capacités obligatoires recensées depuis le code réel ; verdicts `product_validated|valid_empty|not_applicable` (passants) vs `degraded|abstained|bypassed|failed` (bloquent `complete=1` ET cleanup, run → `blocked` avec cause lisible). Deep Vision relu dans `brainlive_deep_vision_runs_v161` : sélectionné>0 & analysé=0 → `failed`. `compiled_watch_only`/`compiled_no_life_delta` = succès. Persistance table `v18_close_day_capability_manifests` + `result_json`. Rollback `MLOMEGA_E64_CAPABILITY_GATE=0`. Tests `test_e64i_capability_manifest.py` (10) + non-régression close_day_output_proof/multi_session (10) verts.
> - **I1.3** : `brain2_conversation_episode.py` — les deux passes v6 (segmentation puis détail) passent par `run_windows`/checkpoints E64 quand le prompt dépasse le budget : fenêtres token-aware sur tours ordonnés, frontières émises pour les primaires seuls puis assemblées PAR CODE en partition contiguë sans trou (tri par provenance, pas par window_index), détail par lots de segments ENTIERS, reprise sans nouvel appel, aucun fallback v5 silencieux (`segmentation_windows_incomplete`/`detail_windows_incomplete` explicites). Cas court = chemin historique octet pour octet (2 appels). Appelant `brain2_strict_v13_2.py` passe `person_id`/`package_date` (scope checkpoints). Tests `test_e64i_long_conversation.py` (7) + non-régression conversation_episode (11) verts.
> - Note : 1 échec pré-existant hors périmètre détecté — `test_e64_night_orchestrator.py::test_estimate_tokens_rounds_up_and_honours_tokenizer` attend l'ancien ratio 3.5 chars/token alors que `stage_adapter._DEFAULT_CHARS_PER_TOKEN=2.5` (valeur volontaire) ; test stale, pas une régression du lot.
3. [ ] **Validation courte des prérequis** : persister `MLOMEGA_LLM_BACKEND=llamacpp`, `MLOMEGA_LLAMACPP_MODEL=qwen9b-p1-24k-mlomega`, `MLOMEGA_OLLAMA_CONTEXT_POSTSTOP=24576`; exécuter `check_phoneonly_readiness.py --deep`, puis `test_phoneonly_runtime.py` dans `.venv-live` et E64/I dans `.venv`. La suite cœur est déjà 92 verte; ne lancer aucun média/CloseDay ici.
4. [ ] **REPRISE PRODUIT ENSUITE = I4.1**, puis I4.2–I4.4 et I7 Gate B cinq minutes. I0.1 Deep Vision sera fermé par I4.2/I4.4; I0.6 spatial reste séparé. Mesurer appels/tokens/temps/dashboard avant toute projection 1 h/8 h.

### E64-G — Tests préventifs obligatoires

- [ ] Fixture « 5 min réelle » : 40 tours audio + 945 observations vision ; **100 % des 985 preuves présentes au manifeste**, zéro prompt hors budget, aucune limite arbitraire du nombre final d'épisodes.
- [ ] Fixture longue 8 h et multi-session/jour : plusieurs milliers d'atomes, mémoire bornée, fenêtres/checkpoints stables, mêmes résultats après reprise.
- [ ] Test de frontières : un événement commence fin fenêtre N et finit début N+1 ; un seul épisode final, toutes les refs couvertes.
- [ ] Chaos paramétré sur **chaque stage LLM** : `length`, timeout, Ollama down, JSON sale, kill après output avant commit, kill après commit avant stage marker, disque plein. Vérifier reprise exacte et aucune sortie partielle active.
- [ ] Test de non-régression petit dataset : résultats métier équivalents au chemin direct lorsque l'entrée tient dans une fenêtre.
- [ ] Mesurer tokens/latence/VRAM et imposer un plafond ; aucun stage ne doit pouvoir générer un prompt non borné par construction.

### Gate de clôture E64

- [ ] Audit E64-A complet : aucun appel LLM nocturne hors orchestrateur commun, sauf exception documentée/testée.
- [ ] Run harnais 5 min `--with-close-day` : transport, Viki scripté, Deep Audio, Brain2 et tous stages nocturnes `completed`; recovery `completed`; manifeste sans missing.
- [ ] Rejouer le même jour puis redémarrer entre fenêtres : idempotence et multi-session prouvées.
- [ ] Lancer ensuite le dashboard et vérifier visuellement épisodes, personnes, événements vidéo, Life Model, prédictions et preuves sources.
- [ ] Gate appareil séparé : wake word Viki/ASR device, gestes et flux caméra/micro OnePlus/S25 restent à valider sur matériel réel ; le `device_transcript` du harnais ne les remplace pas.
