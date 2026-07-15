# E63 harness — observations produit et état des corrections

La première passe E63 consignait seulement les observations. La passe de finition
du 2026-07-12 a été explicitement autorisée à corriger les défauts produit ;
chaque entrée ci-dessous indique donc son état réel.

## OBS-1 — Delivery queue absente sur une DB neuve (CORRIGÉ — 2026-07-12)

**Severity:** low (degrades cleanly, does not crash, does not fail the session).

**Where:** `services/live-pc/delivery_adapter.py` (queries the table), schema owned
by `src/mlomega_audio_elite/v18_delivery.py` (line ~13, `CREATE TABLE IF NOT
EXISTS brainlive_intervention_delivery_queue`).

**Symptom:** on a first-ever session against a brand-new `memory.db`, the runtime
status `recent_errors` fills with (observed 20x in one 26s session):

```
"no such table: brainlive_intervention_delivery_queue"
```

**Cause:** the live `DeliveryAdapter` in `services/live-pc` reads/writes that queue
table during the delivery loop, but the table is only created by the core
`v18_delivery` module's schema, which is not run at live-pipeline startup on a
fresh DB — it is created later (close-day / core `.venv` init). The live path has
no eager `CREATE TABLE IF NOT EXISTS` for it.

**Impact:** the error is caught and pushed to `recent_errors` (the delivery loop
swallows it via `except Exception`), so proactive/help interventions are silently
dropped for the very first live session on a new install until something else
creates the table. Subsequent sessions (after the first close-day) are fine.

**Repro:**
```
.venv-live\Scripts\python tools\harness\run_harness.py --port 8730 --duration 26 --synth-seconds 30
```
then inspect the emitted `tools/harness/_run/device_report.json` →
`server_metrics_active.recent_errors`.

**Fix :** le DeliveryAdapter initialise désormais son schéma avant la première
lecture. Le run minimal sur DB neuve ne perd plus les suggestions de la première
session.

## OBS-2 — CloseDay dépassait le worker final après un timeout (CORRIGÉ — 2026-07-12)

**Severity:** blocker (BrainLive était fermé pendant que des tours continuaient à arriver).

**Where:** `services/live-pc/live_pipeline.py` `drain_final_processing`
(`raise TimeoutError("final turn processing did not drain in 30.0s")`) →
`services/live-pc/phoneonly_runtime.py` `end_session_only` call site.

**Symptom réel (run vidéo 5 min du 2026-07-12):** le correctif initial avalait
le timeout de drain, marquait BrainLive terminé et lançait CloseDay alors que le
worker final écrivait encore. Les erreurs suivantes apparaissaient ensuite :
`conversation.ingest_segment: cannot ingest turn into non-active live session`.

**Fix final:** le drain s'attend réellement (budget produit 300 s). Un timeout
reste un échec de fermeture retryable : BrainLive n'est pas terminé, `ended`
reste faux et CloseDay demeure `not_started`. Le raccourci dangereux
`end_session_after_drain_timeout` est supprimé. Régression :
`test_drain_timeout_blocks_brainlive_end_and_close_day`.

## OBS-3 — WorldBrain service SQLite used cross-thread (CORRIGÉ — 2026-07-12)

**Severity:** grave (dead scene ingestion; 50+ errors/session).

**Where:** `services/live-pc/worldbrain.py` `_init_service_db` + all `self._svc_db`
uses; called from the vision worker threads via
`live_pipeline.py:_on_scene_delta → worldbrain.ingest_scene_delta`.

**Symptom:** `worldbrain.ingest_scene_delta: SQLite objects created in a thread
can only be used in that same thread` — 54 occurrences in the real-video run;
scene entities/changes were never persisted.

**Fix (minimal):** `sqlite3.connect(..., check_same_thread=False)` + a
`threading.RLock` (`self._db_lock`) held around every `self._svc_db` access
(`_persist_entity`, the session-changes insert, `record_attribute_change`). No
broader refactor. New regression:
`tests/v19/test_e28_worldbrain.py::test_ingest_scene_delta_is_thread_safe`.

## OBS-4 — hypothesis_engine.note_turn crashes on dirty LLM confidence (CORRIGÉ — 2026-07-12)

**Severity:** minor (one turn's addressee hypothesis dropped, reported).

**Where:** `services/live-pc/hypothesis_engine.py` `note_turn`
(`float(signal.get("confidence") or 0.0)`).

**Symptom:** `hypothesis_engine.note_turn: could not convert string to float:
'}}0'` — a local LLM leaked a malformed JSON fragment into the confidence field.

**Fix:** new `_safe_confidence` helper wraps the coercion in try/except, falls
back to `0.0`, counts `metrics["signal_parse_errors"]`, and reports the parse
failure once (`_reported_conf_parse_error`). Existing tests unchanged.

## OBS-5 — WebRTC tombait au premier device_transcript (~20 s) (CORRIGÉ — 2026-07-12)

**Severity:** blocker produit. Le symptôme ressemblait à un défaut média du faux
device, mais la cause était dans le serveur PC.

Au premier `device_transcript` scénarisé, le callback DataChannel appelait
`PhoneOnlyRuntime._on_receipt` synchroniquement sur la boucle aiortc. Le routage
Intent/VLM pouvait bloquer assez longtemps pour faire expirer le consentement ICE
et fermer DTLS. Un scénario sans commande tenait 60 s ; le même média avec la
commande tombait à 20 s, preuve discriminante.

**Fix :** `gateway.py` planifie les receipts, les sérialise et exécute le callback
synchrone via `asyncio.to_thread`. La fermeture draine ces tâches avant de couper
le média. Le faux device sépare aussi réellement l'audio et la vidéo du MP4 en
fichiers mono-track temporaires (hygiène déterministe, pas la cause racine).

**Preuve après fix :** le vrai scénario a traversé les 301 s du MP4 avec
**14 857 chunks audio** et 2 tours conversationnels. Le test ciblé
`test_slow_device_command_does_not_block_webrtc_event_loop` couvre la frontière.

## OBS-6 — AttributeMemory/HypothesisEngine SQLite cross-thread (CORRIGÉ — 2026-07-12)

Le worker final utilise ces moteurs hors du thread de construction. Leurs
connexions SQLite levaient `SQLite objects created in a thread...`, masquant la
mémoire fine malgré un transport vert. Connexions ouvertes avec
`check_same_thread=False` et chaque accès protégé par un `RLock`, même politique
que WorldBrain.

## OBS-7 — Une reprise CloseDay `blocked` ne pouvait pas reprendre (CORRIGÉ — 2026-07-12)

La récupération durable retrouvait correctement le job, mais ne passait
`allow_rerun/force` que si un CloseDay était déjà `completed`. Un run `blocked`
était donc refusé par `assert_run_resumable` à chaque redémarrage. Une recovery
est désormais toujours un retry explicite (`allow_rerun=True`) ; le script ne
réouvre un jour completed que s'il existe réellement.

## OBS-8 — Token HF sans scope public gated (CONFIG CORRIGÉE — 2026-07-12)

Le compte avait bien accès à `pyannote/speaker-diarization-3.1`, mais le token
fine-grained `py` réellement lu par `.env` annonçait
`canReadGatedRepos=false` et `permissions=[]` pour ce modèle. Le scope a été
activé par l'utilisateur ; `whoami` renvoie maintenant `true` et Pyannote 3.1,
segmentation 3.0 et WeSpeaker se téléchargent. Ne pas confondre « accès accordé
au compte » et « scope accordé au token ».

## OBS-9 — SpeechBrain ECAPA exigeait un privilège symlink Windows (CORRIGÉ — 2026-07-12)

`EncoderClassifier.from_hparams(savedir=...)` tente de collecter ses checkpoints
par symlinks. Un compte Windows normal lève `WinError 1314`. Le backend utilise
désormais le cache Hugging Face directement (`savedir=None`) sous Windows et la
stratégie COPY lorsque disponible. Validation réelle : ECAPA chargé, CUDA actif,
aucun mode vocal simplifié.

## OBS-10 — Résolution vocale auto-verrouillait SQLite (CORRIGÉ — 2026-07-12)

`resolve_speakers_for_audio` détenait une transaction puis `ensure_speaker`
ouvrait une seconde connexion en écriture : `database is locked`. Le writer
réutilise maintenant la connexion/transaction appelante. Cela ne dépend pas de
l'enrôlement owner : le profil du run avait `require_self_voice=false`, donc les
voix inconnues doivent être clusterisées sans bloquer.

## OBS-11 — Un mot WhisperX non aligné bloquait tous les tours (CORRIGÉ — 2026-07-12)

WhisperX peut conserver un token sans `start/end`. Le validateur rejetait alors
les 40 tours (`turn 2 word 8 lacks bounds`). Le texte reste intact dans
l'utterance et la preuve brute ; seul le token sans bornes est exclu de la liste
des mots horodatés. Une utterance entièrement non alignée hérite des bornes du
segment, sans inventer de timestamp mot-à-mot. Validation réelle : **40 tours**,
`large-v3`, CUDA float16, alignement, Pyannote et SpeechBrain tous actifs.

## OBS-12 — Brain2 refusait même le person_id explicite (CORRIGÉ — 2026-07-12)

`_default_user` appelait le garde anti-owner-implicite avant de tester
`explicit_person_id`, puis EpisodeBuilder reperdait le `person_id` reçu du
CloseDay. Le contrôle accepte désormais immédiatement l'ID explicite et le
propage au builder ; l'absence d'ID continue d'échouer fermement.

## OBS-13 — Explosion du prompt Brain2 / sortie LLM tronquée (OUVERT — ARRÊT VOLONTAIRE)

Le premier vrai passage nocturne atteint maintenant Brain2, mais la conversation
raffinée contient **985 pseudo-tours** : **40 tours Deep Audio utiles + 945
`vision_context`**, pratiquement une observation par frame/détection. Le bundle
EpisodeBuilder mesure **1 595 361 caractères**. Il ne doit ni être envoyé en un
seul prompt, ni être réduit arbitrairement.

Un second défaut a été identifié et corrigé sans perte : `_safe_prompt_payload`
cherchait uniquement `payload["bundle"]`, alors qu'EpisodeBuilder fournit
`payload["conversation_bundle"]`; en dépassement, le LLM recevait donc une
enveloppe vide et inventait des épisodes. Le fallback conserve maintenant les
références de la bonne clé et échoue s'il ne peut pas produire une enveloppe
valide. Les appels JSON désactivent aussi le thinking Qwen et retentent une fois
à 8192 tokens, sans jamais appliquer une sortie partielle.

**Important :** les essais provisoires « échantillonner 16 frames », « maximum 6
épisodes » et « 8 éléments par liste » ont été **retirés avant commit**. Ils
auraient pu perdre de la granularité et ne constituent pas la correction.

La correction de fond doit être décidée avant de reprendre : traitement durable
par fenêtres de 40–50 éléments, réduction des frames en changements/tracks sans
supprimer leurs preuves, références vers les lignes sources, checkpoints par
fenêtre, fusion des frontières, déduplication/idempotence et validation de
couverture finale. Il faut appliquer cette politique à tous les stages LLM de la
nuit, pas corriger EpisodeBuilder seul. Le CloseDay réel reste `blocked` au stage
Brain2 ; le dashboard n'a volontairement pas été lancé comme si le run était vert.

## OBS-14 — Le run réel post-E64 n'a jamais atteint CloseDay (OUVERT)

**Symptôme mesuré.** La vidéo de 301 s passe entièrement : 15 077 chunks audio,
30 tours BrainLive, 7 239 frames reçues et 3 clips indexés. En revanche le POST
`/session/end` expire ; la session reste `active`, `end_session=error`,
`close_day=not_started`, aucun job `phoneonly_session_recovery_v19` et aucune
table `night_llm_*`. Ce run ne valide donc ni E64-F ni le dashboard.

**Faux coût de 30 minutes identifié.** Après le timeout de `/session/end`,
`run_harness.py --with-close-day` continue de poller CloseDay pendant 1 800 s
même lorsque son état reste explicitement `not_started`. Cette attente ne mesure
pas la nuit : elle masque l'échec de fermeture et doit s'arrêter immédiatement.

**Indices produit.** `recent_errors` contient des `TimeoutError` rendus en chaînes
vides et des échecs répétés de `close_transport`; le log montre aussi que
LiveDiscourse sollicite Ollama en arrière-plan avec cartes invalides/tronquées.
La phase exacte (drain receipts/audio/final ou transport) n'est pas enregistrée :
instrumenter le statut par phase avant de choisir le correctif, ne pas simplement
augmenter le timeout. La base `tools/harness/_run/harness_memory.db` est conservée
et récupérable par `recover_abandoned_phoneonly_sessions`, sans rejouer le média.

**Contexte vidéo uniquement pour interpréter la vision — scénario ASR inchangé.**
Canapé/ami jusqu'à 1:30 ; table téléphone/lunettes puis clés à 2:00 ; texte fixé
2:30–2:38 ; changements de pièces et retour table jusqu'à 3:20 ; lunettes
déplacées vers 3:34 ; machine à café 3:57–4:10 ; terrasse puis seconde personne
à 4:24 jusqu'à la fin. Cette description ne doit pas modifier
`scenarios/real_video_session.json`.

## OBS-15 — Le reducer alternait frames brutes et observations (CORRIGÉ — 2026-07-12)

La reprise a enfin atteint E64-F réel : Ollama 9B a validé cinq fenêtres et
subdivisé correctement les entrées/sorties trop longues, sans matérialiser de
partiel. La DB a alors révélé que la conversation contenait encore **1 433
tours**, dont **1 407 atomes vision unitaires**. Continuer aurait créé au moins
32 fenêtres racines pour cinq minutes ; le run a été arrêté volontairement, les
checkpoints validés restant durables.

Cause : `vision_timeline_json` mélange 709 lignes `vision_frames` brutes (aucun
objet, résumé unique = nom du JPG) et 698 `vision_scene_observations`. Leur
alternance raw-vide/détection/raw-vide cassait chaque plage. Une frame brute est
maintenant rattachée temporellement comme preuve à l'observation sémantique la
plus proche ; elle reste dans `source_refs/frame_refs` mais n'ouvre plus un
événement cognitif. Preuve réelle : **1 407 refs uniques → 132 atomes**, export
produit **162 tours = 132 vision + 30 audio**. Le scénario VIKI est inchangé.

L'artifact Deep Audio inclut aussi le digest du contexte réduit dans son identité,
pour ne jamais reprendre l'ancienne conversation raffinée sous prétexte que les
WAV n'ont pas changé.

## OBS-16 — Deux exports actifs du même bundle bloquaient la recovery (CORRIGÉ — 2026-07-12)

Après ré-export E64, la nouvelle conversation base et l'ancien export Deep Audio
pouvaient rester simultanément `exported`. La reprise échouait alors avec
`assembly/export cardinality mismatch`, bien que chaque export soit valide pris
isolément. L'assembleur supersède désormais TOUTES les anciennes lignes actives
du bundle avant d'activer la nouvelle version, désactive leurs scopes et invalide
leurs descendants. L'historique n'est pas supprimé. Un test E37 reproduit deux
anciens exports actifs et prouve qu'un seul reste autoritaire.

## OBS-17 — EpisodeBuilder développait trop de JSON par fenêtre (CORRIGÉ EN CODE, RUN COMPLET OUVERT)

Le run 9B réel a produit plusieurs fenêtres valides mais une fenêtre de 5 035
tokens d'entrée a consommé 180 s puis fini `length`; attendre la troncature avant
de subdiviser est un gaspillage. Le payload transportait aussi des copies
techniques exactes : mots WhisperX présents trois fois et scène vision présente
dans le texte puis `representative`. Aucun mot prononcé, aucun atome et aucune
preuve n'ont été supprimés : la projection LLM garde texte exact, locuteur,
timestamps, objets/actions/OCR, scores et digests ; les listes brutes restent en
DB pour la couverture. Mesure vraie : 130 806 → 68 343 tokens (-47,8 %).

Le contrat utilise maintenant un JSON Schema Ollama réel (`evidence_turn_ids`
= chaînes), normalise les rares objets `{turn_id,text}`, refuse un épisode sans
preuve primaire et sépare contexte lu / responsabilité de sortie : overlap 2
`context_only`, cible 2 `primary_output`. Mesure autoritaire en phase post-stop,
`qwen3.5:9b`, contexte 16k : 68,8 s à froid puis 8,7 s à chaud, sorties complètes
et cohérentes. Les benchmarks accidentels 4B/4k ont été identifiés via `ollama ps`
et ne sont PAS retenus. Reste : reprise complète, manifeste vert et dashboard.

## OBS-18 — Les sorties d'anciens adaptateurs contaminaient le merge (CORRIGÉ — 2026-07-12)

Les 79 fenêtres v4 ont toutes fini au premier essai, mais la relecture finale
filtrait seulement `(person,jour,stage_name)`. Les dix sorties v2 conservées pour
audit entraient donc dans le merge v4 : dicts `location/channel` anciens puis
erreur SQLite, et surtout risque de couverture faussement verte. `load_outputs`
accepte désormais l'ensemble exact des clés feuilles du run courant ; couverture
et matérialisation passent obligatoirement ces clés. Preuve réelle après reprise :
**1 433 attendues = 26 audio couvertes + 1 407 vision représentées, 0 missing,
0 quarantaine** ; compteur v4 inchangé à 79 tentatives, donc aucun rappel Ollama.

## OBS-19 — Les FK inventées par V13 bloquaient après EpisodeBuilder (CORRIGÉ EN CODE, REPRISE OUVERTE)

Le premier moteur aval `capture_engine` a renvoyé un `turn_id` absent et le writer
l'a envoyé directement dans `audio_prosody_events.turn_id` : `FOREIGN KEY
constraint failed`. Audit du bloc complet : limites de tours, liens d'épisodes,
pensées, transitions d'état, outcome/intention et cas similaires avaient la même
classe de risque. Les FK venant du LLM sont maintenant acceptées uniquement si le
parent existe (et, pour un turn, appartient à la conversation) ; un événement
prosodique sans tour valide est ignoré, une FK optionnelle invalide devient NULL.
`thought_type` absent reçoit le type neutre `hypothesis` exigé par la table. Une
barrière unique, commune aux 16 writers, sérialise en JSON déterministe tout
objet/liste destiné à une colonne TEXT (ex. `place_explicit`, `channel`, `stakes`),
normalise les scalaires numériques et vérifie les FK déclarées par `PRAGMA`.

Autre gap révélé : les 16 moteurs V13 par épisode étaient dans une seule transaction.
Une erreur tardive rejouait tous les appels précédents. Chaque moteur + ses writers
est maintenant commit atomiquement ; reprise par `(engine,episode,prompt hash)` et
sortie validée. Test négatif FK + reprise exacte vert. Volume observé restant à
arbitrer sans supprimer de passes : 19 épisodes v4 × 16 moteurs = 304 appels.
Suite ciblée complète après splitter de champs : 57 tests verts.

## OBS-20 — V13 aval n'est pas dimensionné pour une journée (OUVERT — ARCHITECTURE À BATCHER)

Après EpisodeBuilder v4, la fixture produit 19 épisodes (dont 8 purement visuels)
et V13 lance 16 moteurs par épisode : **304 appels avant Life Model/longitudinal**.
Le premier `internal_state_engine` monolithique a tronqué. La protection E64 par
champs est maintenant fonctionnelle : schéma 10 champs traité en 4 sous-tâches,
10/10 clés fusionnées, zéro partiel. Le prompt a aussi été ramené de 13 665 à
7 038 tokens en sortant du prompt les diagnostics globaux `missing_context` et
les copies de métadonnées de tours ; détails et preuves restent durables.

Mesure 9B réelle : **195,8 s pour un seul internal_state d'un épisode** (forte
variance : 79 s, 2,7 s, puis appels longs). Cette protection évite la perte mais
ne rend pas le produit viable : 5 min prendraient probablement 45–90 min et une
journée plusieurs jours. Correction de fond suivante : boucle moteur→batch
d'épisodes token-aware, résultats owner/episode-scopés, moteurs psychologiques non
appliqués aux seuls événements capteur, sans supprimer les tables ni les preuves.

### Mise à jour OBS-20 — refonte code faite, gate réel encore ouvert (2026-07-13)

La refonte Codex remplace finalement la matrice par un pack **par épisode humain**,
plus cohérent que moteur→batches : même preuve sérialisée une fois, tous les moteurs
applicables présents sous des schémas séparés, subdivision par responsabilités si
la sortie dérive. EpisodeBuilder v5 : 12 épisodes humains, 132 atomes capteur routés
vers Vision/WorldBrain/Silent Life, 1 407 refs vision toujours couvertes. Première
preuve réelle : 12 packs locaux `completed`; 11 directs, un subdivisé en deux.
Cas difficile : 6 836→5 128 tokens et 104,1→28,75 s en 9B/16k, sans champ/moteur
supprimé. Le statut reste ouvert tant que global V13, V14, Life Model et CloseDay
ne sont pas verts sur une exécution unique.

## OBS-21 — Un checkpoint ignorait le contexte commun rendu (CORRIGÉ — 2026-07-13)

`night_llm_windows_v19.input_digest` venait des `PlanUnit` seulement. Modifier le
bundle commun, le prior ou la projection sans changer les unités pouvait reprendre
une ancienne sortie `completed` en 0,04 s : faux vert. `run_windows` rend maintenant
la requête avant le lookup, digère sa forme exacte et combine ce digest avec celui
du plan. Test : mêmes unités/scope + shared context différent ⇒ nouvelle clé et
nouvel appel ; même contexte ⇒ reprise sans appel.

## OBS-22 — Appel V13 direct pouvait utiliser 4B/4k avec un budget 16k (CORRIGÉ — 2026-07-13)

Le modèle et `num_ctx` sont choisis selon le `ContextVar runtime_phase`, pas une
variable shell arbitraire. Un benchmark direct hors `phase(post_stop)` a chargé
`qwen3.5:4b`, contexte 4 096, alors que le planner acceptait 6 836 tokens : mesure
invalide et risque de prompt tronqué par le provider. Les runners V13 construisent
et appellent désormais le client sous `post_stop_brain2_v13`. `ollama ps`/`api/ps`
a confirmé ensuite Qwen3.5:9b, contexte 16 384. Garder le modèle en VRAM ne garde
aucun historique de prompt : les appels restent stateless et `think=false`.

## OBS-23 — V13 se nourrissait de ses propres tables matérialisées (CORRIGÉ EN CODE, REPRISE RÉELLE OUVERTE)

`_episode_bundle` expose les tables `situations/states/thoughts/causes/...`. Après
un pack réussi, le prochain build les relisait dans son bundle source, changeait le
hash et rappelait Ollama ; les nouveaux writers modifiaient encore l'entrée. La
reprise n'était donc pas stable. `_stable_episode_source_bundle` garde seulement
épisode/conversation/tours/contexte et des slots dérivés vides ; les dépendances
circulent exclusivement dans `prior_engine_outputs`. Test ciblé vert. Le dernier
échec `profiles[...] is None` venait de l'insertion mécanique de cette fonction
avant le return de `_episode_evidence_profile`; return replacé et test total ajouté.
À prouver encore : un run V13 réel, puis le même run immédiatement, zéro appel et
zéro ligne métier supplémentaire.

## OBS-24 — Une fusion full-schema pouvait subdiviser sans réduire le problème (CORRIGÉ EN CODE, RUN GLOBAL OUVERT)

Le runner hiérarchique divisait les **entrées** sur tout `finish=length`, y compris
au merge. Or chaque entrée de merge est déjà une sortie full-schema : créer deux
fusions full-schema puis les refusionner peut reproduire le même JSON jusqu'à la
profondeur maximale. Politique séparée : feuilles de preuves ⇒ subdivision ; merge
⇒ `subdivide_on_length=False`, quarantaine/signal immédiat au caller, puis split des
responsabilités `(engine,groupe_de_champs)`. Détection supplémentaire si le fan-in
ne diminue pas. Tests faux LLM verts, y compris reprise d'un ancien parent
`subdivided`. Preuve réelle partielle : fenêtre globale 10 capsules/10 463 tokens
verte ; schéma combiné a atteint `length`. Le split réel par schémas et la
couverture finale 12/12 restent le premier travail du prochain agent.

## Incident de validation 2026-07-13 — timings concurrents NON AUTORITAIRES

Trois interruptions du wrapper PowerShell ont laissé leurs enfants Python
continuer en arrière-plan. Plusieurs anciennes versions ont alors sollicité le
même Ollama et écrit des checkpoints dans la même DB entre 01:24 et 01:52. Les
processus ont été identifiés par heure/PID puis arrêtés ; aucun Python ne tournait
à la pause. Les clés exactes empêchent leurs outputs d'anciens inputs de créditer
le run courant, mais ces timings ne mesurent pas la production. Pour la suite :
un seul runner, ne jamais interrompre sans tuer l'enfant, DB actuelle pour reprise
fonctionnelle puis DB fraîche séparée pour benchmark.

## OBS-25 — Le runner générique répétait des blobs JSON et sous-estimait le vrai prompt (CORRIGÉ — 2026-07-14)

Plusieurs tables stockent des collections dans des colonnes `*_json`. Le runner les
traitait comme une chaîne indivisible, donc recopiait parfois la même collection dans
chaque fenêtre. En parallèle, la décision de « tout tient » ne comptait pas toutes les
enveloppes/schémas de la requête réellement envoyée. Correction commune : décoder les
collections persistées en feuilles stables, budgéter la requête rendue complète, puis
versionner le checkpoint. Une couverture relue en DB reste obligatoire; aucun élément
source n'est échantillonné.

## OBS-26 — Les grands schémas faisaient tronquer puis refusionner le même JSON (CORRIGÉ — 2026-07-14)

V14/Life Model/live-ready demandaient plusieurs collections riches dans une seule
sortie. Qwen pouvait atteindre `length`; une subdivision des preuves produisait ensuite
plusieurs sorties full-schema presque aussi grandes à refusionner. Le runner sépare
maintenant les responsabilités de sortie, isole les objets sémantiques des collections
fusionnables losslessly, impose un budget explicite à la projection dérivée et utilise
45 unités utiles par fenêtre sous limite token dure. Les preuves brutes et contradictions
restent durables; seuls les doublons réels sont fusionnés.

## OBS-27 — Life Model acceptait de fausses références et écrivait avant le verdict global (CORRIGÉ — 2026-07-14)

Le modèle renvoyait parfois `nightleaf_*` avec un nom logique de table qui n'était pas
la vraie table/PK. Le writer pouvait aussi matérialiser le sous-ensemble valide avant de
lever sur les lignes invalides, puis la reprise changeait de mode bootstrap→patch.
Correction : schéma de preuve structuré, résolution déterministe de la feuille vers la
ligne source originale, validation owner/scope sur la DB réelle, validation de tout le
lot avant la première écriture et exclusion des rubriques consultatives des tables
canoniques. Le run réel a matérialisé 92 objets uniques, couverture `missing=0`. La
cardinalité/qualité de ces 92 objets reste auditée dans OBS-30.

## OBS-28 — Deep Vision est faux-vert quand toutes ses images échouent (OUVERT — BLOQUE VAGUE 2)

Preuve DB réelle : `selected_keyframes=1`, `analyzed_keyframes=0`, observation
`quarantined_vlm_error`, erreur `Expecting value: line 1 column 1`, latence **84 132 ms**,
mais `brainlive_deep_vision_runs_v161.status='ok'`. Le CloseDay reprend alors cette
sortie et continue. À corriger : statut `failed/retryable/degraded` selon politique,
compteur minimum d'images analysées, JSON strict du backend VLM et réutilisation d'une
analyse profonde existante quand image+digest+modèle sont identiques. Ne pas multiplier
80 s par image tant que ce gate n'est pas fiable.

## OBS-29 — ASR confiance nulle alimente pourtant des conclusions certaines (OUVERT)

La conversation raffinée contient huit tours mais la coordination résume explicitement
une confiance ASR à `0.0` et interprète des fragments grec/russe probablement issus du
bruit. Des hooks et alertes relationnelles à confiance 0.85–0.98 sont néanmoins créés.
À corriger transversalement : propager la qualité ASR/diarisation aux moteurs aval,
interdire une confiance dérivée supérieure à la qualité de preuve sans corroboration,
et mettre en quarantaine les changements de langue incohérents au lieu de les traiter
comme faits. La validation voix réelle/enrôlée reste nécessaire.

## OBS-30 — Réconciliation par absence de preuve et surproduction cognitive (OUVERT)

La réconciliation a marqué des hypothèses `contradicted` parce que la vision ne les
confirmait pas, alors que « non observé » n'est pas « faux ». Elle produit aussi des
formulations de danger/conflit trop affirmatives. Le bootstrap Life Model matérialise
92 objets sur cette petite fixture (dont 22 besoins), signe de duplication ou de
sur-interprétation possible. À corriger avant base utilisateur : verdict `unknown` sur
absence, exigence de contre-preuve positive pour `contradicted`, plafond de confiance
épistémique, dédup sémantique contrôlée et revue qualité contre la transcription/vidéo.
Ne pas réduire arbitrairement les objets : mesurer d'abord recouvrement et provenance.

## OBS-31 — `live_ready` repayaient le LLM pour reformuler le modèle canonique (CORRIGÉ — 2026-07-14)

Le feed réel faisait **302 900 caractères** : 101 lignes canoniques (162 643 chars),
80 observations vision (53 337), relations (50 034), coordination et anciennes tables.
Le LLM relisait ces données pour produire quasiment les mêmes routines/lieux/besoins,
causant des dizaines d'appels et fusions. Correction : compilateur déterministe vers
`LIVE_READY_SCHEMA`, preuves et raw feed conservés, LLM seulement en fallback legacy.
Stage réel final ~2,1 s; aucune fonctionnalité cognitive n'est retirée puisque l'inférence
a déjà eu lieu dans V15.10.

## OBS-32 — Environnement FirstTry encore non hermétique (OUVERT / PARTIEL)

Le run a nécessité HF gated accessible, Qdrant, chemins CUDA/cuDNN et une version
`transformers` plus récente pour l'embedder Qwen3. Le venv local est passé à 4.57.6,
mais le lock Windows du repo n'est pas encore aligné. Le proxy loopback mort rencontré
précédemment et les subprocess manuels ne partagent pas toujours le bootstrap du vrai
runner. FIRST_TRY/RUN/Doctor doivent échouer avant capture avec diagnostic précis si
HF, modèle gated, Qdrant, DLL CUDA/cuDNN, espace disque, version Python ou backend
LLM/VLM ne sont pas prêts.

## OBS-33 — Premier CloseDay complet obtenu, mais gates diagnostics encore ouverts (PARTIEL)

Le run `run_v18_65bdecb7404f4e05abe16cf843f124e4` a dix stages `completed`, manifeste
observé/attendu `complete=1`, cleanup/tiering/rétention/maintenance `ok`. V13 local et
global (`roota/rootb`) ont été traversés. Cependant d'anciens parents combinés restent
quarantinés pour audit, Deep Vision est faux-vert, et certains checkpoints V13.4/V14
avaient été fermés manuellement comme `AUDIT ONLY`. Ce run prouve la traversée du chemin
configuré, pas encore l'équivalence de tous les moteurs ni le gate téléphone/5 min.

## OBS-34 — EpisodeBuilder croise les sujets et amplifie de fausses mémoires (OUVERT — BLOQUANT QUALITÉ)

Audit de la première chaîne complète : 26 tours deviennent 10 épisodes, tous avec le
même `start_time`, sans `end_time`, et 7/10 avec confiance/importance à zéro. Un
`self_reflection` associe « Maxime ? », « C'est toi ? » à une réponse finale sans
rapport ; un `planning` mélange le rendez-vous Karim et Netflix. Des preuves sont
réutilisées par des épisodes incompatibles. Les moteurs aval amplifient ensuite cette
fragmentation : environ 324 lignes V13 et 92 objets Life Model actifs. Correction :
frontières temporelles et thématiques, citation primaire exclusive/cohérente, merge
uniquement sur continuité réelle, puis test contre les quatre sujets humains de la
référence. Ne pas masquer le problème en plafonnant le nombre d'épisodes.

## OBS-35 — Coordination coupait silencieusement la vision après 200 lignes (CORRIGÉ — R4, GATE 5 MIN OUVERT)

`collect_day_evidence(limit=200)` lit `vision_scene_observations` brutes et
`_session_rows` applique `_compact(..., max_rows or limit)` avant le fenêtrage. La
vidéo de cinq minutes contient déjà 698 observations : 498 disparaissent du paquet de
coordination et aucun manifeste aval ne peut les recréer. Correction : alimenter la
coordination par les `VisionChangeAtom` lossless + parents, fenêtrer toutes les unités,
et prouver la couverture des observations sources. Le `LIMIT` ne peut servir qu'à une
page/reprise explicitement parcourue, jamais à déclarer une journée complète.

Correction R4 : keyset+manifest complet, réduction vision par page et fusion aux
frontières. Tests 201/201 en cinq pages et clone réel 199/199 en quatre pages, un atome
dans les deux cas. Le paquet persiste atomes+`source_manifest_json`, pas les observations
dupliquées. La vidéo référence doit encore prouver son total exact dans I7.

## OBS-36 — Life Model coupait chaque famille aux 120 premières lignes (CORRIGÉ — R4)

CloseDay appelle `run_brain2_life_model_update(... limit=120)` ; V15.10 et l'override
V18 multiplient `LIMIT ?`, `_compact(rows, limit)` et `rows[:limit]` sur épisodes,
tours, observations, relations et prédictions. C'est une sélection silencieuse par
ordre SQL, pas une réduction sémantique ni une pagination. Correction : collecteur
lossless paginé, faits typés/atomes avec provenance et manifeste complet ; l'updater
travaille ensuite par fenêtres/promotions. Augmenter 120 déplace seulement la panne.

Correction R4 : collecteur V18, bridge BrainLive, état courant et lifecycle utilisent le
même lecteur paginé. `limit` ne coupe plus les résultats. Les tours non cités sont scannés
et manifestés mais ne gonflent pas le prompt. Tests 121 signaux et 121 routines courantes
en quatre pages; kill/restart avant et après commit couvert.

## Mise à jour OBS-28 — cause Deep Vision confirmée (OUVERT)

Le module de base possède un meilleur gate, mais `v18_poststop_outputs.install_deep`
remplace le runner en production. Cet override garde `terminal_status="ok"` lorsque
toutes les erreurs VLM ordinaires sont mises en quarantaine. En parallèle, le payload
Qwen3-VL demande `format=json` et `num_predict=900` mais pas `think=false`. Sur cinq
minutes : 11 images sélectionnées, 0 analysée, 11 JSON vides/invalides ; le stage reste
vert. Correction : `think=false`, schéma/JSON validé, `analyzed>0` ou statut
`failed|retryable|degraded` explicite, puis cache par hash image+modèle+prompt.

## OBS-37 — Une minute bootstrap devient 92 objets canoniques actifs (OUVERT — SURPROMOTION)

Le Life Model transforme des faits ponctuels (« rendez-vous avec Karim », vigilance
sociale) en routines et produit notamment 22 besoins et 9 trajectoires émotionnelles,
dont une `anxiety_to_relief` insuffisamment soutenue. Ce n'est pas qu'un doublon texte :
les sorties actives seront consommées par BrainLive. Correction : état `watch` au
premier indice, promotion seulement sur répétition ou sources indépendantes, dédup
sémantique transitive par provenance et plafond de confiance par qualité de preuve.

## OBS-38 — Le manifeste final accepte des moteurs bypassés ou abstentionnistes (OUVERT)

Le CloseDay complet contient des checkpoints V13.4/V14 clôturés `AUDIT ONLY`, Deep
Vision faux-vert et une similarité V17 `abstained` après accès refusé au cache de
l'embedder. Le contrat de stage prouve la traversée, pas que chaque capacité requise a
produit une sortie produit. Correction : chaque sous-moteur déclare
`product_validated`, `degraded`, `abstained` ou `failed`; le manifeste final agrège ces
gates et interdit `complete=1` lorsqu'une capacité obligatoire n'est pas validée.

Le détail quantitatif et le plan de refonte sont dans
`docs/E64_H_COST_QUALITY_AUDIT.md`.

## OBS-39 — La projection compacte retirait des signaux sémantiques (CORRIGÉ — 2026-07-14)

Les tests E64-F existants ont révélé que `_prompt_turn` ne conservait plus `state` des
atomes vision et remplaçait les manifests source/frame par leur seul compteur. La
résolution offline du locuteur était aussi renommée, cassant le contrat partagé attendu.
Correction : état compact, manifests `{count,digest}` et
`offline_speaker_resolution` restent dans le prompt; les listes d'IDs et mots WhisperX
dupliqués restent hors prompt mais durables en DB. Ce défaut était antérieur à I1 et
aurait transformé une optimisation de tokens en perte de qualité.

## OBS-40 — Un parent `conversation` désactivait des moteurs V13 (CORRIGÉ — 2026-07-14)

Le premier contrat E64-I réduisait 10 épisodes à un parent de type `conversation`, mais
`_engine_applies_to_episode` décidait internal/social/contradiction/choice/outcome sur le
seul `episode_type`. Plusieurs capacités auraient donc été sautées malgré des sous-thèmes
compatibles. Le writer conserve maintenant `subtheme_types`, le bundle transmet les
sous-thèmes et l'applicabilité travaille sur l'union parent+sous-thèmes. Test explicite :
les neuf capacités locales restent appelables lorsque les types le justifient.

## OBS-41 — I1 gagne ×5,54 mais n'est pas encore un chemin long (OUVERT / PARTIEL)

Mesure shadow deux passes : 2 appels, 15 956 tokens entrée, 41,50 s, 1 parent + 6
sous-thèmes et 26/26 tours, contre 4 appels/20 210 tokens/229,9 s/10 épisodes. Le gain
temps est réel, mais une conversation dépassant le budget échoue volontairement avant
appel : le fenêtrage checkpointé des frontières/détails n'est pas encore implémenté.
Le flag reste OFF. Le pack V13 parent peut aussi subdiviser ses 7–9 responsabilités;
son nombre réel d'appels doit être mesuré avant toute extrapolation huit heures.

## OBS-42 — Les stages aval repaient les tours et leurs propres sorties (PARTIELLEMENT CORRIGÉ — I2 EN COURS)

La mesure réelle a montré que V14 identité, open-loops et interpersonnel reconstruisent
chacun un gros payload depuis les mêmes tours, les mêmes sorties V13 et parfois des
lignes historiques produites par la conversation courante. Le runner hiérarchique
fenêtre ensuite ces duplications : le JSON reste techniquement borné, mais le modèle
repaye la même preuve et peut auto-confirmer sa propre conclusion. Une première
projection locale n'a réduit l'identité que de 31 036 à 22 644 tokens; elle a été
rejetée comme correction cosmétique.

Correction partielle livrée derrière `MLOMEGA_E64_SHARED_FACTS=1` : sorties V13
canoniques lossless, faits typés, manifeste `produced|valid_empty|not_applicable`, refs
de tours courtes et réversibles, tous les tours conservés, exclusion du feedback de la
conversation courante et projection appliquée une seule fois par l'orchestrateur. Les
mesures structurelles avant le dernier compactage étaient identité 31 067→8 684 et
interpersonnel 37 578→11 186 tokens. L'open-loop ne saute son LLM que si un résultat
vide V13 est réellement validé. 60 tests ciblés sont verts.

Reste bloquant avant activation : faire le run Qwen réel identité/interpersonnel,
comparer toutes les sorties/writers, puis appliquer le même contrat central à
coordination, réconciliation, Life et longitudinal. Tant que cette équivalence n'est
pas prouvée, le flag reste OFF et les gains statiques ne valent pas gain produit.

Mise à jour 2026-07-15 : le run V14 réel passe de 20 à 3 appels, de 293 495 à
36 898 tokens et de 569 à 136 s, avec writers et refs restaurés. Coordination est
désormais compilée par code; Life est traité par OBS-43. Restent avant activation le
contrat d'équivalence complet R3, la pagination R4 et le harnais cinq minutes.

## OBS-43 — Life utilisait un outcome comme permis d'inventer un autre trait (CORRIGÉ — R2 CLOS)

Sur un clone owner-scopé, l'ajout d'un seul `action_outcomes` déclenchait Life. Qwen 9B
ignorait cette nouvelle ligne, recyclait « Maxime/Karim/clarification » depuis les tours
ou le modèle courant, puis proposait deux traits à 0,95/`strong_live_hook`. Le premier run
était en outre fragmenté en cinq appels parce que le serveur llama.cpp utilisait 24 576
tokens et l'orchestrateur son défaut 16 384. Le validateur V18 a mis les opérations en
quarantaine; aucune écriture canonique partielle n'a eu lieu.

Correction architecturale : le registre Life partagé est de nouveau réellement appelé;
les tours non cités par un fait owner restent hors prompt; toute opération doit citer une
nouvelle PK durable du delta. Surtout, une première observation est compilée sans LLM
dans `brain2_life_model_watch_candidates`. Rejouer la même PK n'incrémente rien; deux
épisodes/sources indépendants donnent `promotion_ready`. Avant ce seuil, aucune ligne
canonique n'est créée. Preuve réelle : 1,18 s, zéro fenêtre LLM, watch exact sur
`action_outcomes/outcome-owner-test`. 82 tests ciblés/élargis verts après ajout des
contrats checkpoint et préflight.

Le delta est maintenant durable : 21 révisions exactes ont été consommées au premier run
de preuve, puis zéro au replay (`compiled_no_life_delta`), sans incrémenter le watch ni
ouvrir de fenêtre LLM. Le digest permet de retraiter une révision tardive de la même PK.
Le préflight llama.cpp compare en outre le contexte post-stop au `n_ctx` réel : 24 576 =
24 576 est vert; serveur absent, contexte illisible ou mismatch bloquent le ready. Une
promotion ambiguë doit rester validée par provenance et peut être déléguée à DeepSeek;
ne pas contourner le garde en repromptant Qwen jusqu'à obtenir un JSON plaisant.

## OBS-44 — Une minute donnait 0,85/0,90 à un modèle relationnel non identifié (CORRIGÉ — R3)

La comparaison exécutable baseline/shadow a d'abord échoué alors que les refs et les dix
champs étaient présents : le shadow persistait une relation à 0,85 et une boucle à 0,90
pour `UNKNOWN_VOICE_002`, parfois libellé « suspected Maxime ». Ce n'était pas une perte
de champ mais une baisse de prudence, et ces lignes sont directement relues par le feed
BrainLive.

Correction : le raw model reste journalisé et aucune famille n'est supprimée, mais les
huit writers V14.6 issus d'une conversation isolée plafonnent leur confiance durable à
0,65. La répétition indépendante/longitudinale reste le seul chemin de promotion. Le
vrai JSON shadow a été rejoué : huit familles écrites, max 0,65, couverture de preuve
100 %, comparaison R3 verte. La matrice suit en outre 18/18 responsabilités jusque dans
les consumers SQL réels; 87 tests élargis sont verts.

## OBS-45 — Les neuf couches Life courantes étaient absentes du feed V18 (CORRIGÉ — R4)

`install_canonical()` cherchait `CANONICAL_TABLES` sur
`brain2_life_model_v15_10.py`, qui expose le schéma JSON mais pas cette table de mapping
(elle n'existait que dans l'updater). La boucle utilisait `getattr(...,{})` et réussissait
donc silencieusement avec zéro couche. Sur le clone, le forecast pouvait voir routines/
besoins via un autre chemin tandis que Life recevait un dictionnaire courant vide.

V18 porte maintenant le mapping explicite vers les neuf tables et les lit par pages. La
preuve runtime est `9/4/9/22/12/9/10/9/8`. Pour éviter l'effet inverse, ces lignes sont
chargées comme état courant puis retirées du delta de nouvelles preuves : elles ne peuvent
pas s'auto-confirmer. Le checkpoint digère le contenu courant, pas seulement sa
cardinalité. Suite R1–R4 : 93 tests verts.

## Notes that are NOT bugs (expected, documented so future runs don't chase them)

- **`ai_ready=false` / `/health` 200 with `pairing_ready=true`.** Expected on a
  dev box without GPU+YOLOX+Ollama+Qdrant all green. Pairing/offer only needs
  `pairing_ready`, which the harness waits for. Nothing to fix.
- **`brainlive turns = 0` with synthetic media.** The synthetic MP4 is a 440 Hz
  sine (no speech), so WhisperX emits no word finals and no conversation turns are
  written. The scripted `device_transcript` intents DO route
  (`intents_routed=1`, `turns_routed=1`) but device-command routing does not
  create brainlive turn rows. Use a real-speech MP4 via `--media` to get turns.
- **`device_commands_received=0` / `wake_word_acked=false`.** `push_wake_word()`
  only sends a `set_wake_word` device_command when a wake word is configured in
  `configs/user_profile.yaml`. With no profile wake word it is a no-op, so the
  fake device never gets a command to ack. Not a bug; configure a wake word to
  exercise that path.
