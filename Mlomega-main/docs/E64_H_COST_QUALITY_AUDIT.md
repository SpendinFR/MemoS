# E64-H — Audit cardinalité, qualité, temps et coût de la nuit

Date de mesure : 2026-07-14. Ce document décrit le checkout et les bases scratch
réellement exécutés. Il ne transforme pas un stage `completed` en preuve produit.

## Verdict

Le premier CloseDay complet prouve que les dix stages peuvent atteindre leur fin et
que la reprise/checkpoint fonctionne. Il ne prouve pas encore que la mémoire obtenue
est juste, complète ou calculable chaque nuit.

Dans la forme mesurée, la chaîne texte locale n'est pas viable pour huit heures de
capture : même en affectant très généreusement le coût observé à des blocs de cinq
minutes, elle demanderait environ **19 469 appels**, **129 M tokens d'entrée estimés**,
**25,1 M tokens de sortie estimés** et **159 h de calcul texte**. La vision lourde
ajoute environ **5,4 h** avec le débit chaud observé, ou **23,5 h** si chaque image
coûte 80 s. Ce n'est donc pas un problème que llama.cpp ou un 4B peut résoudre seul.

Le chantier nécessaire est une refonte de cardinalité sans perte : une preuve brute
reste durable, mais une inférence sémantique ne doit être payée qu'une fois puis
réutilisée par les moteurs qui en ont besoin. Le 9B reste le modèle des tâches humaines
nuancées. Le 4B est réservé aux transformations structurelles à faible risque après
comparaison de couverture. DeepSeek Pro ne rend pas le chemin actuel économiquement
acceptable : environ **68 EUR/jour de référence** sans cache pour le texte seul.

## Périmètre et preuves réelles

- Base auditée : `tools/harness/_audit/one_minute_memory_v1.db`.
- Session : `blsess_cec36e48db0d00eb`.
- Conversation : `conv_blbundle_deep_audio_v185_a72ef4f29870fadb`.
- CloseDay : `run_v18_65bdecb7404f4e05abe16cf843f124e4`.
- Post-stop : `run_v18_0ab04a05379a4584be41fd144befe202`.
- Dix stages `completed`, manifeste final complet et maintenances `ok`.
- Environ 60,27 s de média, 26 tours Deep Audio, 200 frames, 199 observations,
  1 atome vision et 10 épisodes matérialisés.
- Base vidéo cinq minutes utilisée pour la cardinalité visuelle :
  `tools/harness/_run/harness_memory.db` ; 709 frames, 698 observations,
  11 keyframes lisibles, 12 épisodes.

Les essais anciens, parents abandonnés, retries de développement et runs concurrents
ont été exclus de la mesure. Les durées ci-dessous sont les appels sélectionnés du
chemin final, pas le temps mur de la journée de débogage.

## Mesure texte du chemin final

Les tokens d'entrée sont les estimations persistées par l'orchestrateur. Les tokens
de sortie sont estimés à partir des caractères (`caractères / 3`) car tous les anciens
providers n'ont pas persisté leur comptage natif. Ce sont des ordres de grandeur de
dimensionnement, pas des unités de facturation exactes.

| Groupe | Appels | Entrée estimée | Sortie estimée | Calcul |
|---|---:|---:|---:|---:|
| EpisodeBuilder | 4 | 20 210 | 3 420 | 229,9 s |
| V13 local | 10 | 35 325 | 17 468 | 931,9 s |
| V13 global | 3 | 22 142 | 6 555 | 178,2 s |
| V18 latent outcomes | 5 | 11 243 | 3 150 | 67,5 s |
| V14 people identity | 12 | 43 389 | 23 062 | 475,3 s |
| V14 open loops | 9 | 32 578 | 15 399 | 286,4 s |
| V14 proactive | 1 | 16 770 | 515 | 21,5 s |
| V14 interpersonal | 16 | 216 183 | 37 897 | 781,6 s |
| V14 clarification | 4 | 30 872 | 5 295 | 89,7 s |
| Coordination/day package | 32 | 158 915 | 22 612 | 381,1 s |
| Coordination/watch | 1 | 10 652 | 1 081 | 31,5 s |
| Réconciliation | 35 | 217 217 | 25 637 | 317,7 s |
| Life Model canonique | 37 | 303 696 | 56 113 | 1 189,5 s |
| **Total** | **169** | **1 119 192** | **218 203** | **4 981,7 s / 83,0 min** |

Le profil llama.cpp de mesure était Qwen3.5 9B Q4_K_M, contexte 24 576,
sortie 4 096, `--parallel 1`, flash attention, cache KV Q8, Jinja/JSON et raisonnement
désactivé. Les logs donnent environ 2 250 tokens/s pour le prompt et 57–61 tokens/s
pour la génération. Le backend est opt-in (`MLOMEGA_LLM_BACKEND=llamacpp`) ; Ollama
reste le défaut produit tant qu'une décision ultérieure ne le remplace pas.

## Qualité des résultats

### Ce qui fonctionne

- Le Deep Audio a produit un transcript globalement cohérent avec le scénario Viki.
- Les preuves brutes, parents d'atomes et checkpoints survivent à la reprise.
- Les writers refusent désormais les FK inventées et les références Life Model qui
  ne se résolvent pas vers une ligne owner-scopée réelle.
- `live_ready` compile par code le modèle canonique déjà produit au lieu de repayer
  un LLM sur environ 303 k caractères.
- Les dix stages, le manifeste et les maintenances atteignent réellement leur fin.

### Ce qui invalide encore la qualité produit

1. **EpisodeBuilder fragmente et mélange les sujets.** Les 26 tours ont produit
   10 épisodes alors que la conversation de référence contient environ quatre sujets
   cohérents. Tous commencent au même instant, les fins sont nulles et 7/10 portent
   confiance/importance à zéro. Un épisode `self_reflection` associe « Maxime ? »,
   « C'est toi ? » à une réponse finale sans rapport ; un épisode `planning` combine
   le rendez-vous avec Karim et le documentaire Netflix. Une même preuve est réutilisée
   par des épisodes incompatibles.

2. **L'erreur est amplifiée.** Les 10 épisodes deviennent environ 324 lignes V13,
   puis 92 objets canoniques actifs : 9 routines, 4 lieux, 9 actions, 22 besoins,
   12 expressions, 9 trajectoires émotionnelles, 10 éléments de soi contextuel,
   9 hooks et 8 préférences d'affordance. « Rendez-vous avec Karim » et une vigilance
   sociale ponctuelle sont promus comme routines ; une trajectoire
   `anxiety_to_relief` est inférée sans preuve suffisante.

3. **L'épistémologie est trop affirmative.** La confiance ASR est nulle/non propagée,
   mais des hooks relationnels sortent à 0,85–0,98. La réconciliation traite parfois
   « non observé par la caméra » comme « contredit ». Une absence de preuve doit rester
   `unknown`, sauf contre-preuve positive.

4. **Deep Vision est faux-vert.** Sur la minute : 1 image sélectionnée, 0 analysée,
   1 quarantinée après 84,132 s, mais le stage reste `ok`. Sur cinq minutes : 11/11
   images ont échoué en JSON et aucune n'a été analysée. L'override V18 conserve
   `terminal_status="ok"` pour les erreurs VLM ordinaires et le payload Qwen3-VL ne
   force pas `think=false`; les 900 tokens peuvent être consommés avant le JSON utile.

5. **V17 similarity a abstenu.** L'embedder Qwen3 a rencontré un accès refusé dans
   son cache local. Ce point peut être propre à l'environnement d'audit, mais une nuit
   `completed` ne doit pas masquer un moteur abstenu sans le rendre visible.

6. **Des caps silencieux perdent une journée longue.** La coordination lit directement
   `vision_scene_observations` et ne conserve que les 200 premières lignes. La vidéo
   cinq minutes en possède déjà 698. Le Life Model est appelé avec `limit=120` et de
   nombreuses familles font `LIMIT ?`/`rows[:limit]`. Le fenêtrage aval ne peut pas
   restaurer des preuves supprimées avant l'orchestrateur.

## Vision : doublon réel ou complément ?

Sur PhoneOnly, il n'y a pas deux appels identiques au même VLM lourd. Le jour utilise
VisionRT (détection/tracking) ; la nuit utilise Qwen3-VL sur des keyframes choisies pour
l'interprétation sémantique. Ces deux passes sont complémentaires. Une réutilisation
est correcte seulement si `sha(image) + modèle + version de prompt` sont identiques.

Le stage ultérieur `visual_consolidation` n'appelle ni VLM ni LLM : il relit par code
les événements/entités déjà produits pour fabriquer mouvements, routines spatiales et
résumé journalier. Il ne faut donc pas le supprimer comme « second Deep Vision » ; il
faut lui transmettre la première analyse profonde valide au lieu de réanalyser les
pixels. Le seul doublon potentiel futur est un même hash d'image envoyé deux fois au
VLM lourd, que le cache proposé doit empêcher.

La vidéo cinq minutes a sélectionné 11 images. Les latences étaient 82,929 s à froid,
puis environ 18,36 s/image à chaud (médiane 18,50 s), soit 266,5 s au total malgré
l'échec JSON. L'hypothèse « 80 s par image » est donc un pire cas froid, pas la moyenne
mesurée lorsque le modèle reste chargé. Le scénario humain décrit environ 8 changements
visuels réellement significatifs ; sélectionner les changements d'état, actions, OCR
et apparitions de personnes permettrait de retirer trois images redondantes sans perdre
un événement. Il faut le prouver par couverture, pas imposer un quota aveugle.

## Classification des passes et refonte proposée

### À garder en 9B

- EpisodeBuilder, après correction des frontières et des citations.
- État interne, causalité, contradiction, choix et issue.
- Relations/interpersonnel et réconciliation de vraies contradictions.
- Promotion vers le Life Model et synthèse longitudinale.

### À rendre déterministe ou à déclencher seulement sur candidats

- Assemblage, atomes vision, qualité prosodique, statistiques de langue et n-grams.
- Retrieval de cas similaires par embeddings/reranker ; LLM seulement si des matches
  pertinents existent.
- Calibration uniquement après observation d'une issue réelle, jamais au premier jour.
- Clarifications : file déterministe depuis les champs réellement manquants ; 4B
  optionnel uniquement pour reformuler naturellement la question.
- `live_ready`, consolidation visuelle, résolution d'issues, émission de prédictions,
  Self Schema et indexation finale lorsque leur entrée est déjà canonique.

### À fusionner sans supprimer de capacité

- Par épisode humain cohérent, une ou deux requêtes 9B de responsabilités compatibles
  peuvent produire les schémas aujourd'hui répartis entre contexte, état interne,
  social, causalité, contradiction, choix et issue. Les tables historiques restent
  matérialisées par code à partir de cette sortie typée.
- V13 interventions, V14 proactive, coordination hooks et Life hooks doivent partager
  une ontologie de candidats puis une seule couche de scoring/politique.
- People identity : clustering/noms par code, 9B uniquement sur ambiguïté.
- V14 open loops réutilise intentions/issues V13 au lieu de les ré-inférer.
- V14 interpersonal réutilise états sociaux/causaux V13 puis fait une synthèse
  cross-épisodes par paire de personnes.
- Coordination construit un paquet journalier déterministe à partir des faits typés ;
  le 9B n'intervient que sur de vraies collisions.
- Life Model promeut seulement des faits répétés ou corroborés par des sources
  indépendantes. Une première minute doit surtout produire des candidats `watch`,
  pas 92 vérités actives.

### Matrice des 16 moteurs V13

| Moteur | Décision proposée |
|---|---|
| `capture_engine` | Compiler par code depuis transcript, locuteur, timestamps, prosodie et assets. Aucun LLM. |
| `language_signature_engine` | Stats/ngrams/templates candidats par code; 4B éventuel pour libellé journalier. |
| `episode_builder` | Garder 9B et corriger les frontières/provenances avant toute autre optimisation. |
| `context_resolver` | Même appel 9B par épisode que les responsabilités humaines compatibles. |
| `internal_state_engine` | Garder 9B, conditionné aux épisodes humains et plafond épistémique. |
| `social_model_engine` | Garder 9B, partager faits/participants avec V14.6 au lieu de ré-inférer. |
| `causality_engine` | Garder 9B; même paquet sémantique que contexte/interne quand compatible. |
| `contradiction_engine` | Garder 9B uniquement avec deux affirmations/contre-preuves réelles. |
| `pattern_miner` | Candidats déterministes; promotion 9B au jour/semaine après répétition. |
| `choice_model_engine` | Garder 9B uniquement si options/choix existent dans l'épisode. |
| `outcome_tracker` | Lier intentions/issues par code; 9B seulement si l'issue est ambiguë. |
| `similar_case_retrieval` | Embeddings/reranker déterministes; aucun appel si zéro match pertinent. |
| `prediction_engine` | Un appel conversationnel seulement si preuves et horizon existent. |
| `simulation_engine` | Fusionner avec la prédiction concernée, pas un appel sur chaque épisode. |
| `calibration_engine` | Ne pas appeler sans outcome; score déterministe puis 9B sur ambiguïté. |
| `intervention_engine` | Ontologie/scoring commun avec V14.7, coordination et hooks Life. |

V14.5 identité/open-loops réutilise respectivement les clusters/noms et les
intentions/issues V13. V14.6 réutilise participants, social, interne et causalité puis
fait une synthèse cross-épisodes par paire. V14.7 consomme les candidats d'intervention
communs. V14.8 produit la file depuis les champs réellement manquants et peut réserver
un 4B à la formulation naturelle. Coordination et Life Model consomment les mêmes faits
typés, sans nouvelle lecture brute de toutes les tables.

### Place du 4B

Le benchmark local ne justifie pas de remplacer globalement le 9B. Sur 40 requêtes
identiques, llama.cpp P3 donne 4,51 min pour le 9B contre 3,36 min pour le 4B : seulement
1,34× plus rapide, avec plus de confusions de locuteurs, de fausses contradictions et
moins de nuances. Le 4B peut traiter chronologie/normalisation, reformulation de
clarification et ranking de candidats, sous le même schéma et la même couverture.
Chaque remplacement doit passer un test de sortie comparatif ; le gain principal vient
de la suppression des ré-inférences, pas d'une baisse générale de modèle.

### Perte de qualité visée

| Changement | Couverture/qualité visée | Risque à mesurer |
|---|---|---|
| Projection déterministe de faits déjà inférés | 0 % de perte source, 0 capacité retirée | erreur de mapping de schéma |
| Fusion de responsabilités compatibles avec le même 9B | 0 % de perte, cohérence potentiellement meilleure | interférence entre responsabilités |
| Déclenchement conditionnel | 0 % sur cas applicables | faux négatif de l'applicabilité |
| 4B sur structure/faible risque | 0 % sémantique attendu | benchmark général montre -0,5/10 |
| 11→~8 images significatives sur la référence | 0 événement humain perdu, pixels bruts gardés | changement subtil manqué |

Le chiffre honnête avant tests est donc : **objectif 0 %**, perte réelle inconnue. Une
fusion ou un routage qui perd une preuve, un verdict ou un événement reste refusé ; on
ne promet pas artificiellement « 0 % » avant la comparaison E64-I/G.

## Projection huit heures

### Ce que E64 a déjà gagné

Avant la refonte déjà livrée, la chaîne ne terminait pas et ne peut donc pas fournir
un temps total comparable : le bundle Brain2 faisait 1,6 M caractères et exposait
985 pseudo-tours (40 audio + 945 vision), puis finissait en `length`. Le premier
fenêtrage EpisodeBuilder a demandé 79 fenêtres ; l'architecture intermédiaire créait
19 épisodes × 16 moteurs, soit **304 appels pour V13 seulement**, avant V14, la
coordination et le Life Model. Un seul `internal_state_engine` avait pris 195,8 s.

E64 a déjà remplacé les 945 pseudo-tours vision par des atomes avec couverture
transitive, empêché les prompts/fusions non bornés, stabilisé les checkpoints,
réservé la psychologie aux épisodes humains, exécuté les responsabilités compatibles
en packs et rendu `live_ready` déterministe. C'est cette chaîne **après ces gains**
qui mesure maintenant 169 appels et 83 minutes sur la fixture auditée. La projection
« chemin actuel » ci-dessous n'est donc pas l'ancien code catastrophique : c'est le
meilleur chemin réellement terminé aujourd'hui, avant la prochaine refonte de faits
partagés et de cardinalité métier.

### Chemin actuel local

Pour respecter l'hypothèse utilisateur « 12 épisodes par cinq minutes », huit heures
représentent 96 blocs et 1 152 épisodes. Affecter le coût de la fixture auditée à chaque
bloc de cinq minutes est déjà optimiste, car la fixture ne dure qu'une minute :

- environ 19 469 appels texte ;
- 128,93 M tokens d'entrée estimés ;
- 25,14 M tokens de sortie estimés ;
- 9 565 minutes, soit **159,4 h de calcul texte** ;
- 11 images/5 min : 1 056 images ; **5,4 h** avec le profil chaud observé ou
  **23,5 h** à 80 s/image ;
- total de référence : **environ 165 h** avec VLM chaud, hors Deep Audio/embeddings.

Si chaque minute était aussi dense que la fixture, le plafond théorique dépasserait
81 000 appels et 660 h. Cette borne haute ne représente pas une journée normale, mais
elle montre que le code n'est pas borné par la quantité de sens utile.

### Chemin local refondu à qualité égale

Hypothèse de dimensionnement, à valider par E64-G : environ neuf appels sémantiques par
bloc événementiel de cinq minutes (EpisodeBuilder, quatre épisodes humains cohérents,
deux à trois synthèses conversation/globales), plus une vingtaine de promotions
journalières/longitudinales. Pour 8 h :

- environ 884 appels texte ;
- environ 3,54 M tokens d'entrée et 0,58 M de sortie ;
- **1,5 h de calcul idéal** d'après le benchmark, cible réaliste **2–3 h texte** avec
  dépendances, grandes sorties et reprises ;
- environ 768 images si les 8 vrais changements/5 min sont tous conservés : **3,9 h**
  au débit VLM chaud mesuré, à rebenchmarker avec JSON réellement valide ;
- total continu très événementiel : **environ 6–8 h** ; journée normale moins dense :
  ordre de grandeur **2–5 h**.

La cible `1 h capturée ≤ 1 h consolidée` devient plausible, pas prouvée. Elle exige la
correction VLM, le cache, une sélection sémantique, les caps lossless et une fixture
longue. Aucun chiffre ne doit être certifié avant ce test.

### DeepSeek Pro sans refonte

Tarifs officiels au 2026-07-14 : 0,435 USD/M tokens d'entrée hors cache,
0,003625 USD/M en cache et 0,87 USD/M en sortie. Avec 128,93 M entrée et 25,14 M
sortie, le texte actuel coûterait environ **77,95 USD / 68,24 EUR par journée** hors
vision. Même une entrée entièrement gratuite ne ferait pas tomber les 25,14 M tokens
de sortie sous 1 EUR. DeepSeek Flash serait encore environ **21,96 EUR**.

Après refonte, DeepSeek Pro coûterait environ **2,04 USD / 1,78 EUR** sans cache,
ou **1,12 EUR** avec 50 % d'entrée en cache. DeepSeek Flash serait environ 0,57 EUR,
mais sa qualité doit être comparée. DeepSeek n'est pas ici un backend VLM : la vision
locale reste à compter. Les limites de concurrence annoncées ne donnent pas un temps
de mur fiable ; un benchmark du graphe de dépendances est obligatoire.

Une estimation de temps, non un benchmark : avec 19 469 appels, 50–100 requêtes
simultanées et 20–60 s par appel, l'arithmétique brute donne 1,1–6,5 h ; les dépendances,
JSON vides/retries et barrières de stages rendent **2–8 h** plus honnête pour le chemin
actuel. Après refonte (environ 884 appels), le même calcul donne **0,5–2 h** de texte.
DeepSeek annonce une concurrence maximale de 500 pour Pro, mais cela ne prouve ni la
latence soutenue ni la qualité de ce graphe ; ces fourchettes restent à mesurer.

Sources tarifaires :

- <https://api-docs.deepseek.com/quick_start/pricing/>
- <https://api-docs.deepseek.com/guides/json_mode/>
- conversion 1 EUR = 1,1424 USD, taux BCE du 13 juillet 2026 :
  <https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html>

## Décision recommandée

Ne pas remplacer maintenant toute la nuit par DeepSeek et ne pas dégrader tous les
moteurs vers 4B. Réparer d'abord les faux verts et l'EpisodeBuilder, puis construire
une couche de faits typés/provenance réutilisable par tous les moteurs. Garder Qwen9B
pour la nuance et le VLM local pour les keyframes significatives. Si un budget cloud
est ajouté, utiliser DeepSeek Pro comme critique final sur les seuls candidats
incertains à forte valeur, avec plafond journalier de tokens, plutôt que sur chaque
fenêtre brute.

## Gates avant production

1. Deep Vision : `think=false`, JSON strict, statut non vert si zéro image analysée,
   cache image/modèle/prompt et benchmark chaud avec sorties valides.
2. EpisodeBuilder : frontières temporelles, preuves exclusives/cohérentes et test
   contre les quatre sujets humains de la référence.
3. Remplacer les caps 200/120 par atomes/manifeste complets et fenêtres lossless.
4. Propager ASR/diarisation et imposer les plafonds de confiance épistémique.
5. Unifier les faits/interventions et empêcher la promotion d'un exemple unique en
   routine/besoin stable.
6. Comparer sorties actuelles/refondues, 9B/4B, avec couverture identique.
7. Exécuter la fixture cinq minutes complète, puis 1 h et 8 h avec métriques natives
   provider : appels, tokens, temps, GPU, images, retries, couverture et qualité.

## Addendum I2 — mesure du premier pack partagé (2026-07-14)

Le premier résultat de refonte réduit réellement le multiplicateur EpisodeBuilder/V13,
mais ne valide pas encore la projection huit heures : deux appels I1 construisent le
parent, puis **un appel** produit les sept responsabilités V13 applicables en 19 452
tokens/22,656 s, avec couverture 7/7. L'ancien bloc correspondant demandait environ
14 appels et 19,36 min sur la même référence; le nouveau bloc observé totalise trois
appels et ~64,16 s. Ce gain local supérieur à ×18 autorise I2, il ne prouve pas que les
stages journaliers aval auront la même pente.

La duplication suivante a été localisée dans les payloads V14. Une première réduction
31 036→22 644 tokens a été refusée; elle répétait encore tours/faits/historique. La
projection centrale améliorée, avant son dernier compactage, mesurait 31 067→8 684 pour
identité et 37 578→11 186 pour interpersonnel, sans omettre de tour. Le prochain chiffre
autoritaire sera celui des appels Qwen et writers réels, pas ces seules tailles JSON.
Les estimations « 884 appels / 2–3 h texte » du présent audit restent donc des objectifs
de dimensionnement, inchangés et non certifiés.
