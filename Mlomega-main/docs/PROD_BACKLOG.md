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

- [ ] **I0.1 Deep Vision** : dans l'override réellement appelé, forcer `think=false`, JSON strict et `analyzed_keyframes > 0` lorsque des images sont sélectionnées; zéro analyse devient `retryable|degraded|failed`, jamais `ok` (OBS-28).
- [x] **I0.2 Qualité des preuves** : propager confiance ASR, diarisation, langue et alignement jusqu'aux faits; une confiance dérivée ne dépasse pas sa meilleure preuve sans corroboration indépendante; fragments linguistiques incohérents en quarantaine (OBS-29).
- [x] **I0.3 Épistémologie** : `non_observed` reste `unknown`; seul un fait positif incompatible peut donner `contradicted`; toute promotion Life Model commence `watch` et exige répétition ou sources indépendantes (OBS-30/37). Preuves : `build_reconciliation_candidates` ignore l'absence/non-outcome, compile seulement les statuts positifs explicites; Life écrit `watching` puis `promotion_ready` après deux groupes indépendants; tests `test_e64i_daily_projection.py`.
- [x] **I0.4 Manifeste de capacité** : agréger les verdicts des sous-moteurs et interdire `complete=1` si une capacité obligatoire est bypassée, abstentionniste ou faux-verte (OBS-38).
- [x] **I0.5 Préflight FirstTry** : avant capture, vérifier HF gated/proxy, Qdrant, Ollama/llama.cpp, modèle/format JSON, version `transformers`, CUDA/cuDNN, VLM, disque et venv nocturne; aucun téléchargement ou diagnostic tardif après `end_session` (OBS-32). Clos en code le 2026-07-15; l'état opérateur courant reste volontairement bloqué tant qu'Ollama n'est pas démarré et que le llama-server P1 orphelin n'est pas arrêté ou déclaré comme backend.
- [ ] **I0.6 Recherche spatiale produit** : distinguer ingestion et consommation. VisionRT/WorldBrain stockent bien des positions, mais `FocusSearchSkill.Locate`, `spatial.answer_find` et `VisionRtRequestSender` ne sont pas appelés/assignés en production; brancher « où est X ? » sur la dernière observation durable, avec fraîcheur/confiance et fallback honnête. Le focus de frame courante ne vaut pas dernière position connue.

#### I1 — mini-plan 1 : un épisode conversationnel, des sous-thèmes ordonnés

- [x] **I1.0 Baseline figée** : DB `tools/harness/_audit/one_minute_memory_v1.db`, 1 bundle actif, 26 tours Deep Audio utiles, 10 épisodes défectueux, EpisodeBuilder 4 appels / 20 210 tokens entrée estimés / 3 420 sortie / 229,9 s. Défauts : mêmes débuts, fins nulles, citations réutilisées entre sujets et mélange Karim/Netflix (OBS-34). Ne pas relancer la nuit pour retrouver cette baseline.
- [x] **I1.1 Contrat sémantique v6** : une conversation continue devient **un parent conversationnel**, contenant des sous-thèmes ordonnés et cités. Créer un autre parent seulement sur frontière dure prouvée : changement de conversation/session, silence long configuré, changement d'interaction/personnes, action/lieu indépendant ou fin explicite — jamais « un mot = un épisode » ni une durée arbitraire.
- [x] **I1.2 Sous-thème durable** : stocker pour chaque sous-thème ordre, titre/résumé, bornes de tours, participants, état d'issue, confiance et refs primaires. Chaque tour humain appartient à exactement un sous-thème primaire; il peut être contexte d'un voisin mais ne peut pas soutenir deux affirmations incompatibles. Le parent porte l'union 26/26 et les événements capteur restent des liens contextuels séparés, jamais de la psychologie attribuée à William.
- [x] **I1.3 Appel borné sans troncature** : envoyer la projection compacte complète si elle tient; sinon produire des fragments de sous-thèmes par fenêtres puis assembler le parent par code/provenance. Ne pas demander plusieurs épisodes full-schema par tranche. Préflight sur taille d'entrée **et** cardinalité de sortie; aucun premier appel voué à `length`.
- [x] **I1.4 Compatibilité et migration** : versionner prompt, schéma, checkpoint et writer; exécuter d'abord en shadow sur une copie de DB. Conserver le chemin v5 pour comparaison/rollback jusqu'au verdict. Les consommateurs V13 lisent le parent et ses sous-thèmes; aucun ancien checkpoint v5 ne peut valider une sortie v6. Shadow puis vrai CloseDay effectués; v6 ON par défaut, rollback explicite `=0`.
- [ ] **I1.5 Tests structuraux** : 26/26 tours couverts, ordre/bornes réels, un tour primaire dans un seul sous-thème, frontière traversant deux fenêtres fusionnée une fois, aucun merge par texte, aucune FK inventée, capteur-only sans épisode psychologique, reprise sans nouvel appel ni doublon.
- [ ] **I1.6 Gate réel stop/go** : sur la minute, viser **1 parent + environ 4 sous-thèmes**, Karim et Netflix séparés, toutes les assertions relisibles dans les tours, ASR incertain visible; **≤2 appels**, entrée ≤50 % des 20 210 tokens, sortie ≤3 420 tokens et temps chaud ≤50 % des 229,9 s. `GO` seulement si couverture=100 % et qualité au moins égale; `STOP/REDESIGN` si gain appels <×2 sur EpisodeBuilder, gain projeté chaîne <×5, ou une preuve/capacité manque.
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

- [ ] **I4.1 Sélection avec couverture** : keyframe sur changement de scène/objet/action/personne, OCR, demande utilisateur et intervalle de sécurité; chaque frame écartée pointe vers la keyframe/atome représentatif. Les 11 images de la vidéo référence servent de baseline, pas de quota arbitraire.
- [ ] **I4.2 Backend et cache** : Qwen3-VL 8B local, `think=false`, format strict, budget sortie mesuré; cache seulement par `sha(image)+modèle+version prompt`. Un retry ne repaye pas une image déjà validée.
- [ ] **I4.3 Réemploi** : VisionRT live fournit détection/tracking; Deep Vision ajoute la sémantique aux keyframes; `visual_consolidation` réutilise ces sorties par code et n'est pas supprimé comme faux doublon.
- [ ] **I4.4 Gate** : 11/11 images référence valides ou dégradation explicite; comparer événements humains/OCR/objets à la vérité de la vidéo. Mesurer froid, chaud, images/heure et temps GPU avant projection.

#### I5 — modèle et backend choisis par tâche, après preuve

- [ ] Garder le 9B pour EpisodeBuilder, états internes, causalité, social, réconciliation et promotion Life; tester le 4B uniquement sur chronologie/normalisation, formulation de clarification et ranking.
- [ ] Pour chaque candidat 4B : mêmes entrées/schéma, JSON strict, couverture identique, comparaison des confusions de locuteurs/contradictions/nuances. Le gain benchmarké 1,34× ne justifie aucune baisse globale.
- [ ] Comparer Ollama et llama.cpp sans confondre vitesse et quantité de sortie : tokens utiles, constats, JSON valide et qualité par seconde. Tester P1/P2/P3 seulement si la VRAM laisse BrainLive intact.
- [ ] Évaluer DeepSeek Pro après I1–I4 : critique final des seuls cas incertains ou backend nocturne candidat. Mesurer qualité, latence et coût sur le graphe réel; budget visé ≤2 EUR/jour, jamais calculé sur une cardinalité encore fausse.

#### I6 — déclenchement conditionnel et calculs déterministes

- [ ] Embeddings/reranker sans LLM; `similar-case` seulement avec candidats; calibration seulement après issue; identity 9B seulement si cluster/noms ambigus; clarification seulement sur champ réellement manquant.
- [ ] Assemblage, couverture, statistiques prosodiques/langue, n-grams, projections et `live_ready` restent déterministes. Un LLM ne reformule pas une table canonique qu'un writer peut mapper exactement.
- [ ] Enregistrer la raison de chaque appel (`why_called`, facts lus/produits, cache hit, tokens, latence) pour prouver qu'un jour calme coûte moins sans rater un événement.

#### I7 — validation progressive et décision de production

- [ ] **Gate A — minute shadow** : I1 réel versus baseline, puis estimation aval recalculée depuis les cardinalités observées.
- [ ] **Gate B — cinq minutes** : scénario VIKI inchangé + vidéo de référence; chaîne complète, dashboard, preuves audio/vision, reprise et comparaison qualité. Cible intermédiaire : appels réduits ≥×5 contre chemin mesuré, aucune capacité perdue.
- [ ] **Gate C — une heure synthétique réaliste** : alternance silence/conversation/déplacements/OCR/personnes, chaos réseau/LLM/VLM/disque et reprise. Prouver `1 h capture ≤1 h consolidation` sur la RTX 3070 ou mesurer précisément l'écart.
- [ ] **Gate D — huit heures** : base fraîche, multi-session/jour, aucun cap, mémoire/VRAM bornées, manifeste complet, reprise idempotente, coût cloud si utilisé. Seulement ici annoncer le temps d'une nuit.
- [ ] **Décision stop/go** : si I1+I2 ne donnent pas au moins ×5 sans perte, ne pas poursuivre les micro-optimisations; comparer architecture cloud/hybride ou matériel. Si les gates passent, fixer le backend FIRST_TRY et rendre ses préflights bloquants.

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
