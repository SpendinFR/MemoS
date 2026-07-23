# Passation CloseDay PRO — 19 juillet 2026

## Jalon validé le 23 juillet 2026

Le run frais `gateb-pro-target-20260723-143534` remplace les anciennes projections :
**ALL PASS**, CloseDay/recovery completed, coût complet **0,0575646 EUR** sous plafond
dur 0,10 EUR. La copie conversationnelle externe d'environ 60k tokens par appel est
désactivée par défaut car elle doublait les bundles/projections métier et son cache ne
se propageait pas entre schémas variables. Aucun prompt, schéma, writer ou chemin local
n'a été retiré. Rollback diagnostic : `MLOMEGA_PRO_REDUNDANT_CONVERSATION_PREFIX=1`.

Temps de référence : 406,069 s dans CloseDay, 463,475 s depuis la fin live. Le prochain
travail porte uniquement sur la latence et doit préserver ce résultat fonctionnel/coût.

## But et règle de sécurité

Le but du profil PRO est de conserver toute la qualité/provenance de CloseDay tout en
ramenant la consolidation post-live de la vidéo de référence de cinq minutes à **cinq minutes
maximum**.
Le chemin local est déjà validé en environ treize minutes et constitue le rollback.

Règle absolue : **sans `-Pro` / `--pro` / `MLOMEGA_PRO_CLOSEDAY=1`, aucun nouveau
ThreadPool, provider cloud, préfixe cloud, prompt transport ou ordre moteur ne doit être
exécuté.** Ne pas modifier le prompt métier local `episode-pack-v2`, ses groupements, ses
budgets ni ses writers pour faire réussir PRO. Tout changement commun doit avoir un test
prouvant le comportement local historique.

Ne jamais lancer un nouveau Gate B payant avant les tests faux-LLM/concurrence. Les clés
sont dans `.env`, ignoré par Git; ne jamais les imprimer, les déplacer dans une commande,
un rapport, une DB ou un commit.

## État exact livré au prochain agent

Le profil est additif et déjà branché de bout en bout :

- `RUN_MLOMEGA_V19.ps1 -LivePhone -Pro`, `run_harness.py --pro` et
  `run_phoneonly_close_day.py --pro` activent seulement le sous-processus nocturne;
- le live reste Ollama 4B. Le texte nocturne PRO utilise `deepseek-v4-pro`, Deep Audio
  utilise Groq `whisper-large-v3`, Deep Vision utilise `gemini-3.1-flash-lite`;
- `cloud_budget_v19.py` réserve avant envoi et mesure coût, tokens cache hit/miss, sorties,
  audio, images, latence, HTTP et retries; plafond produit initial 1,50 EUR/jour;
- le préflight PRO authentifie les trois fournisseurs avant capture et ne charge plus P1
  ou Qwen3-VL inutilement. Le préflight local garde ses contrôles P1/VRAM historiques;
- Groq conserve texte/timestamps et ne remplace que Whisper. WhisperX alignment,
  Pyannote et SpeechBrain restent locaux. Le label fournisseur `French` est maintenant
  conservé dans `provider_language` mais normalisé en `fr` pour WhisperX;
- Gemini remplace seulement l'inférence VLM. Sélection, matérialisation, cache, provenance,
  writers et égalité `selected=readable=analyzed` restent communs;
- DeepSeek possède un préfixe canonique, un warm-up partagé entre ContextVars concurrents,
  un sémaphore (12 par défaut, 40 maximum), retry/backoff 429/5xx et JSON strict;
- le préfixe brut fautif a été remplacé par une projection sémantique. Les timelines
  `raw/world/audio` restent intégralement en DB et apparaissent dans le prompt par
  `count+digest+durable_table`. Vision devient des change-atoms avec manifests exacts.
  Mesure fournisseur réelle : **532 041 → 49 026 tokens** pour le même bundle;
- dans `brain2_strict_v13_2.py`, la branche PRO prépare désormais **un appel distinct par
  moteur**, alors que le local continue `_run_episode_engine_pack` sans changement. Les
  appels PRO sont ordonnés par niveaux; chaque worker ouvre sa connexion SQLite et les
  writers historiques sont rejoués séquentiellement après barrière;
- un moteur PRO essaie son schéma complet dans un appel et ne subdivise ses champs qu'après
  un vrai échec longueur/contrat. Les moteurs globaux réellement dépendants restent
  séquentiels.

Ce fan-out moteur compile et ses composants ont leurs tests ciblés, mais **il n'a pas été
atteint par un run réel** : le premier raccord faisait également exécuter EpisodeBuilder
par DeepSeek et celui-ci a bloqué en amont. La décision retenue n'est plus de paralléliser
ce nouvel EpisodeBuilder cloud : il faut remettre **EpisodeBuilder seul sur le moteur local
déjà validé**, persister ses épisodes, puis réserver DeepSeek aux moteurs cognitifs. Ne
cocher ni Gate B PRO ni objectif deux minutes à partir des seuls tests unitaires.

## Preuves réelles conservées

DB/artefacts ignorés, à ne pas committer :

`tools/harness/_run/gateb-pro-20260719-185246.db`

Cette capture a prouvé : session live complète, Deep Audio Groq réussi, Deep Vision Gemini
18/18/18, puis arrêt manuel dans EpisodeBuilder. Mesures utiles :

- Groq : 272,8 s audio, environ 1,4 s, 0,00736 EUR;
- Gemini : 18 images, environ 2,84 s/image en série, environ 0,02035 EUR total;
- ancien préfixe DeepSeek : 532 041 tokens, environ 0,202 EUR par cache-miss;
- nouveau préfixe compact : 49 026 tokens, environ 0,01866 EUR au warm-up;
- cache DeepSeek réel : deux premiers appels immédiats encore miss pendant propagation,
  puis environ **50 304 tokens hit** par appel et 0,001–0,003 EUR/appel;
- les réponses DeepSeek de détail étaient sémantiquement bonnes : Karim/rendez-vous,
  Netflix, Sarah, café, locuteurs et incertitudes correctement distingués. Elles ne sont
  pas une preuve DB car le contrat les a rejetées avant matérialisation;
- au moment de l'arrêt : `episodes=0`, `v13_engine_outputs=0`. Aucun worker Python ne
  reste actif.

Le coût de cette DB inclut les essais de l'ancien préfixe géant et ne doit pas servir à
projeter le coût final. En production, le plafond quotidien est durable dans l'unique DB.
Dans le harnais, une nouvelle DB possède un nouveau ledger : additionner manuellement les
runs du jour et utiliser un plafond résiduel afin de ne pas contourner 1,50 EUR.

### Piège crash/budget à fermer avant le prochain run payant

Le ledger compte volontairement les lignes `status='reserved'` dans le coût engagé. En
l'état, un processus tué entre la réservation et la réconciliation peut cependant laisser
une réservation durable sans indiquer si la requête est partie. Ne jamais supprimer ou
réconcilier ces lignes à la main : cela pourrait sous-compter un appel réellement facturé.

Avant le prochain Gate B PRO, rendre cette frontière crash-safe de façon additive :

1. Ajouter au ledger un identifiant de run/worker et un état d'envoi durable (`sent_at` ou
   équivalent). La transaction `reserved` précède toujours l'appel réseau; l'état
   `in_flight` est persisté immédiatement avant l'envoi.
2. À la reprise, seule une réservation ancienne dont l'absence d'envoi est **prouvée** peut
   devenir `released`. Une requête possiblement partie devient `uncertain` et conserve son
   coût maximal dans le plafond quotidien.
3. Ne jamais libérer automatiquement une ligne `in_flight` sur la seule base de son âge.
   L'usage/réponse fournisseur, s'il est disponible, reste la source de réconciliation.
4. Tester : crash avant envoi → libérable; crash après marquage envoyé → `uncertain` et
   compté; reprise concurrente idempotente; aucun changement quand PRO est désactivé.

Les lignes `reserved` du run interrompu `gateb-pro-20260719-185246.db` sont donc des
preuves conservées, pas des données à nettoyer pour faire repasser le budget.

## Cause racine observée et décision de contournement produit

`build_conversation_episode_v6` produit d'abord une segmentation immuable, puis traite les
fenêtres `brain2_conversation_detail` avec `run_windows`. DeepSeek comprend souvent qu'un
segment grossier contient plusieurs sujets et renvoie plusieurs sous-thèmes. Le contrat
`normalize_detail_window_output` exige que leurs `evidence_turn_ids` forment une partition
exacte, contiguë, ordonnée et exhaustive de tous les tours sources. DeepSeek cite les tours
sémantiques mais omet parfois salutations/fillers : résultat bon sur le fond, rejet
`detail_normalized_output_none`, subdivision récursive, appels séquentiels nombreux.

Ne pas résoudre en : désactivant le gate, acceptant une couverture partielle, affectant un
tour manquant au sous-thème voisin, réduisant le nombre de tours, tronquant le transcript,
ou modifiant le prompt local. Ce serait un faux gain et casserait la preuve lossless.

La résolution produit choisie est plus simple : **DeepSeek ne construit pas les épisodes**.
La voie locale P1/llama.cpp, déjà validée sur cette fixture et checkpointée, matérialise une
fois les épisodes. DeepSeek reçoit ensuite chaque épisode durable comme préfixe commun et
exécute les moteurs qui l'analysent. Le défaut de sortie DeepSeek ci-dessus reste un test de
robustesse du provider, mais n'est plus un chantier bloquant du profil PRO.

## Chantier à réaliser

### A. Conserver EpisodeBuilder local dans le profil PRO

But : exécuter exactement l'EpisodeBuilder local validé, une seule fois par conversation,
puis basculer vers DeepSeek seulement après le commit des épisodes. Ne pas réécrire son
prompt, son schéma, son fenêtrage, son merge, ses checkpoints ou ses writers.

Implémentation recommandée :

1. Ajouter une injection explicite du client de construction à `_ensure_episodes_strict`
   puis `build_conversation_episode_v6(window_llm=...)`. En PRO, créer
   `OllamaJsonClient(backend="llamacpp", base_url=MLOMEGA_LLAMACPP_BASE_URL,
   model=MLOMEGA_LLAMACPP_MODEL)` enveloppé par `OllamaWindowLLM`. Ne jamais muter
   `MLOMEGA_LLM_BACKEND` globalement et ne jamais laisser le constructeur implicite choisir
   DeepSeek par héritage d'environnement.
2. Ajouter au `GpuPhaseOrchestrator` une frontière PRO explicite : arrêter/vider Ollama,
   démarrer P1, vérifier alias/contexte/anti-thinking, construire les épisodes, `commit`,
   puis arrêter P1 en `finally` avant les appels DeepSeek. Cette phase doit être ignorée si
   les épisodes complets compatibles existent déjà.
3. Conserver l'appel actuel `_ensure_episodes_strict` inchangé sans `MLOMEGA_PRO_CLOSEDAY`.
   Le nouveau paramètre est optionnel et vaut `None`; aucun comportement local ne change.
4. Le ledger cloud ne doit contenir aucune ligne `episode_builder`. Les statistiques V13
   doivent au contraire enregistrer le modèle local exact et `coverage_status=complete`.
5. Si EpisodeBuilder local échoue ou produit une couverture incomplète, arrêter avant tout
   fan-out DeepSeek. Ne jamais demander au cloud de reconstruire silencieusement les
   épisodes en fallback.

Tests obligatoires : sans flag, mêmes appels/digests/checkpoints qu'avant; avec PRO, fake
P1 appelé par EpisodeBuilder et fake DeepSeek jamais appelé avant le commit; épisodes déjà
complets = zéro appel P1; erreur P1 = zéro appel cloud; `stop_p1` exécuté en `finally`.

### B. Chauffer le cache par épisode, puis paralléliser les moteurs PRO

L'unité cloud n'est plus la fenêtre EpisodeBuilder : c'est le couple
`(episode_id, engine_name)`. Le bundle conversationnel brut reste durable en DB; le préfixe
DeepSeek commun est l'épisode compact déjà matérialisé.

Architecture attendue :

1. Charger tous les épisodes complets et leurs `_stable_episode_source_bundle` après la
   barrière/commit EpisodeBuilder. Calculer une fois leur digest; aucun thread ne relit ou
   ne modifie cette projection.
2. Émettre **un warm-up par épisode unique**, avec le préfixe canonique octet pour octet.
   Les warm-ups de plusieurs épisodes peuvent partir par vague bornée. Attendre ensuite une
   seule propagation de cache configurable (`MLOMEGA_DEEPSEEK_CACHE_SETTLE_S`, mesure
   actuelle ~25–30 s), pas 30 s par épisode.
3. Construire le DAG réel des couples `(episode, moteur)`. Les moteurs qui ne lisent que
   l'épisode immuable partent ensemble; ceux qui consomment réellement
   `prior_engine_outputs` attendent la barrière du niveau producteur. Ne pas considérer la
   simple position dans `ENGINE_ORDER` comme une dépendance sans tracer le consommateur,
   mais ne pas supprimer une dépendance réellement lue pour gagner quelques secondes.
4. Commencer à 8 requêtes en vol, augmenter au maximum à 12
   (`MLOMEGA_PRO_FANOUT_INITIAL`, `MLOMEGA_CLOUD_MAX_IN_FLIGHT`). Chaque requête garde un
   moteur, son prompt et son schéma : **interdiction de fusionner plusieurs moteurs dans un
   gros JSON**. Le sémaphore provider et le backoff exponentiel absorbent 429/5xx.
5. Chaque worker ouvre sa propre connexion via `db.connect()`. Aucun `Connection`, cursor,
   `StageResult`, dictionnaire de sorties mutable ou writer n'est partagé. Le worker rend
   une sortie validée temporaire; après la `Future` barrier, le thread principal trie par
   épisode/ordre moteur, écrit via les writers historiques et commit.
6. Le premier niveau peut couvrir plusieurs épisodes simultanément : il n'est pas
   nécessaire d'attendre la fin complète de l'épisode A avant d'analyser l'épisode B. Une
   barrière n'existe que pour une dépendance réelle ou avant la matérialisation ordonnée.
7. Checkpoints et prompt hashes restent compatibles avec la voie séquentielle PRO. Une
   reprise réutilise toute sortie `completed` et ne repaie ni warm-up inutile ni moteur
   validé. Une erreur n'autorise jamais la matérialisation d'un sous-ensemble obligatoire.
8. Après chaque niveau, vérifier que les cache hits fournisseur sont réels. Plusieurs
   misses après le warm-up doivent réduire le fan-out ou prolonger la barrière; ne jamais
   supposer le cache uniquement parce que le préfixe semble identique.

### C. Valider le fan-out moteur PRO déjà posé

Fichier : `src/mlomega_audio_elite/brain2_strict_v13_2.py`.

Comportement voulu :

- local : `_run_episode_engine_pack`, inchangé;
- PRO : `_run_engine_partitioned` une fois par moteur, bundle épisode placé une fois dans
  `cloud_bundle_prefix`, puis instructions/schéma moteur;
- niveaux actuels : capture+langage; contexte; état interne+social; causalité+
  contradiction+choix; outcome. Les épisodes d'un même niveau sont également indépendants;
- barrière et writers séquentiels entre niveaux;
- moteurs globaux pattern→similar case→prediction→simulation→calibration→intervention :
  appels distincts mais séquentiels, car leurs sorties se nourrissent réellement;
- `target_units=len(schema units)` en PRO : un appel par moteur normalement, subdivision
  seulement sur échec réel; local conserve ses petits groupes.

Ajouter un test faux-LLM qui mesure `max_concurrent_calls >= 2`, prouve un seul warm-up par
épisode, une sortie distincte pour chaque moteur applicable, l'ordre des niveaux, les
writers dans l'ordre historique, et zéro exécution de ce chemin sans flag PRO. Le code
actuel n'est pas déclaré validé tant que ce test et un passage réel ne l'ont pas traversé.

### D. Gate stop/go avant nouveau run payant

Tests ciblés depuis la racine :

```powershell
Remove-Item Env:MLOMEGA_PRO_CLOSEDAY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest `
  tests\v19\test_cloud_pro_v19.py `
  tests\v19\test_e64i_conversation_episode.py `
  tests\v19\test_e64i_long_conversation.py `
  tests\v19\test_e64f_wiring.py `
  tests\v19\test_e64f_brain2_blocks.py -q
```

Le test local doit passer sans réseau et ne doit créer aucun appel cloud/ThreadPool PRO.
Puis exécuter les mêmes tests spécifiques avec faux P1 + faux DeepSeek et
`MLOMEGA_PRO_CLOSEDAY=1`. Critères : EpisodeBuilder local seul, couverture 100 %, zéro
fenêtre obligatoire quarantinée, un warm-up par épisode, reprise zéro appel, concurrence
cloud prouvée, dépendances respectées et writers identiques.

Avant toute reprise réseau, exécuter aussi les tests crash du ledger décrits plus haut et
vérifier qu'aucune réservation ancienne n'est libérée sans preuve de non-envoi.

Reprise réelle économique sur les checkpoints existants (attention au budget déjà dépensé) :

```powershell
$env:MLOMEGA_DB = (Resolve-Path 'tools\harness\_run\gateb-pro-20260719-185246.db').Path
Remove-Item Env:OPENAI_API_KEY,Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts\run_phoneonly_close_day.py `
  --person-id me --live-session-id blsess_f55d5377a7a07ab8 `
  --pro --cloud-budget-eur 1.50 --cloud-on-budget stop
```

Cette reprise sert uniquement à matérialiser EpisodeBuilder par P1 puis prouver le fan-out
DeepSeek sans repayer Groq/Gemini. Elle ne donne pas un coût propre, car son ledger contient
l'ancien essai 532k. Le lanceur doit démarrer P1 pour la phase locale puis l'arrêter avant
le fan-out; si cette frontière n'est pas encore codée, ne pas lancer la reprise.

Après succès, faire **un seul** Gate B PRO neuf :

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Remove-Item Env:OPENAI_API_KEY,Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
.\.venv-live\Scripts\python.exe tools\harness\run_harness.py `
  --pro --cloud-budget-eur 1.50 --cloud-on-budget stop `
  --port 8730 --with-close-day `
  --media tools\harness\_run\real_video_clean.mp4 `
  --scenario tools\harness\scenarios\real_video_session.json --duration 305 `
  --db "tools\harness\_run\gateb-pro-$stamp.db" `
  --out "tools\harness\_run\gateb-pro-$stamp.json"
```

GO seulement si : live inchangé et 13/13; Groq/Deep Audio complet; Gemini
selected=readable=analyzed; EpisodeBuilder parent+sous-thèmes avec couverture 100 %;
chaque moteur applicable possède sa sortie séparée; aucune quarantaine obligatoire;
CloseDay/recovery/manifests completed; coût détaillé sous plafond; cache hits réels; et
temps post-stop mesuré ≤120 s. Sinon conserver le local comme production et documenter le
goulot exact, sans abaisser un gate.

Ensuite seulement exécuter le Gate B local déjà connu pour la non-régression finale. Ne pas
le relancer pendant le développement du fan-out.

## Fichiers à ne pas toucher/stager

Le working tree contient des modifications utilisateur hors lot :

- `apps/xr-mobile/Assets/Scenes/PhoneOnly.unity`;
- `apps/xr-mobile/Assets/XR/XRGeneralSettingsPerBuildTarget.asset`;
- `src/mlomega_audio_elite/brain2_life_model_updater_v15_13.py`;
- `src/mlomega_audio_elite/v18_brain2_context.py`;
- `Oldconversation/`, logs, modèles, `_run`, artefacts Unity et `.env`.

Toujours `git add` avec chemins explicites, jamais `git add -A`.
