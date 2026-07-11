# HANDOFF GLOBAL — MemOs / MLOmega V19

**Document cumulatif de reprise.**  
**Version initiale :** consolidation des sessions du 3–7 juillet 2026 et du 8–10 juillet 2026.  
**Dernière session intégrée :** session du 8–10 juillet 2026.  
**But :** transmettre l’état global du projet à un nouvel agent sans relire toutes les conversations ni tous les anciens handoffs.

---

## 1. Fonction de ce document

Ce fichier maintient l’état global de MemOs au fil des sessions.

À chaque nouvelle clôture, il doit être mis à jour ainsi :

1. lire le nouveau `handoffLastSession` ;
2. comparer ses affirmations aux cartes et documents récents ;
3. identifier ce qui change réellement l’état global ;
4. ajouter la nouvelle session dans l’historique condensé ;
5. résoudre les contradictions avec les anciennes sessions ;
6. retirer des problèmes ouverts ce qui a été résolu ;
7. conserver les éléments encore `to_verify` ;
8. mettre à jour la prochaine action ;
9. produire un nouveau `HANDOFF_GLOBAL.md` propre et directement réutilisable.

Ce document ne remplace pas :

- le checkout Git courant ;
- les tests relancés ;
- les artefacts réellement présents ;
- le `handoffLastSession` le plus récent ;
- les cartes techniques ;
- les guides spécialisés du dépôt.

Ordre de confiance :

```text
checkout réel
  > tests et builds datés exécutés sur ce checkout
  > artefacts présents avec hash
  > documents actuels du dépôt
  > HANDOFF_GLOBAL.md
  > handoffLastSession
  > conversations et déclarations d’agents
```

Le `handoffLastSession` le plus récent garde le détail et le contexte chaud.  
Le présent fichier conserve l’état consolidé, les décisions durables, les capacités actuelles, les problèmes encore ouverts et l’historique condensé.

---

## 2. Sources consolidées

### Session 1 — 3 au 7 juillet 2026

- Projet cité : MLOmega V19, ensuite rattaché à MemOs.
- Socle historique : `MLOmega_V18_8_1_Evidence_Connected`.
- Travaux principaux : audit V18.8, conception V19, E21→E47, Unity PhoneOnly, APK Android, audio/ASR/KWS, gestes, provisioning et close-day multi-session.
- État final rapporté : E47 fusionné sur `main`, APK PhoneOnly v2 produite, validation S25 encore ouverte.

### Session 2 — 8 au 10 juillet 2026

- Projet : MemOs / MLOmega V19.
- Travaux principaux : E48-A, E48-B, E49, E50, E51, E52, E53 Phase A, E54, E55, E56, E58, E59 et audit/corrections E60.
- État final rapporté : majorité des raccordements E60 corrigés, cartes mises à jour par delta, APK existantes probablement antérieures aux derniers patches, validation matérielle encore ouverte.

### Limite commune

Ces sources proviennent d’exports de conversations. Elles rapportent des commandes, éditions, tests, builds et commits, mais ne contiennent pas à elles seules le checkout final vérifié.

---

## 3. Statuts utilisés

- `verified_checkout` : visible dans le checkout réellement inspecté.
- `tested` : traversé par un test identifié et daté.
- `reported` : annoncé dans une session, sans vérification indépendante actuelle.
- `to_verify` : présence, branchement ou comportement à confirmer dans le checkout.
- `device_to_verify` : validation réelle Android, PhoneOnly ou XREAL manquante.
- `partially_proven` : code et tests partiels présents, mais une frontière runtime ou matérielle reste ouverte.
- `deferred` : volontairement reporté.
- `obsolete` : remplacé ou probablement antérieur à des patches plus récents.
- `mismatch` : documentation, carte ou promesse fonctionnelle en contradiction avec le code ou le runtime constaté.

Règle importante :

> Une capacité peut être présente dans le code et testée isolément sans être réellement raccordée au chemin produit.

Aucune affirmation `reported` ne doit déclencher une refonte avant inspection ciblée du checkout.

---

## 4. Métadonnées à vérifier au prochain démarrage

À remplir depuis le dépôt réel :

```text
Racine Git :
Remote :
Branche :
HEAD :
Working tree :
Dernier commit :
Date de vérification :
APK PhoneOnly présente :
APK XREAL présente :
Hashes :
Dernier test Android réel :
Dernier test XREAL réel :
Dernier close-day réel :
```

Commandes minimales :

```powershell
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline -30
git remote -v
```

Vérifier aussi :

```powershell
Get-ChildItem apps\xr-mobile\build\android\*.apk -ErrorAction SilentlyContinue |
  Select-Object Name,Length,LastWriteTime

Get-FileHash apps\xr-mobile\build\android\mlomega-phoneonly.apk -Algorithm SHA256 -ErrorAction SilentlyContinue
Get-FileHash apps\xr-mobile\build\android\mlomega-xreal-g1.apk -Algorithm SHA256 -ErrorAction SilentlyContinue
```

Ne pas reset, clean, changer de branche ou supprimer des fichiers avant cette inspection.

---

## 5. Vision produit consolidée

MemOs est une mémoire personnelle locale avec assistance live.

Le système doit pouvoir :

- capter de l’audio continu ;
- capter de la vision/caméra ;
- produire observations, événements et preuves ;
- conserver une mémoire durable ;
- représenter personnes, objets, lieux, routines, relations et engagements ;
- fournir du contexte immédiat via BrainLive ;
- produire des modèles longitudinaux via Brain2 et Life Model ;
- afficher une aide contextuelle sur téléphone puis lunettes ;
- consolider les sessions en fin de journée ;
- rester honnête sur la confiance, les preuves et les limites matérielles.

La première cible de vérité est PhoneOnly sur Android, idéalement Galaxy S25. Le PC porte les traitements lourds.

XREAL réutilise l’essentiel du backend, des contrats et de l’app Unity avec un build et un adaptateur dédiés.

Le projet ne doit pas devenir une démonstration figée. Les comportements doivent venir des observations, de la mémoire, des preuves et des contrats réels.

---

## 6. Architecture consolidée

```text
Téléphone Android / lunettes XREAL
  ├─ caméra, micro, gestes, UI
  ├─ réflexes locaux, ASR/KWS, traduction
  ├─ WebRTC audio/vidéo
  ├─ DataChannel
  └─ HTTP / SessionHub
              ↓
Services live PC
  ├─ SessionHub / signaling / ingress
  ├─ AudioRT / VisionRT
  ├─ WorldBrain / ChangeAttention
  ├─ BrainLive / intents / aide E53
  ├─ delivery UI / TTS / receipts
  ├─ archivage / clips / rétention
  └─ sélection des preuves
              ↓
Cœur mémoire MLOmega
  ├─ SQLite
  ├─ Qdrant
  ├─ observations / événements / preuves
  ├─ BrainLive / Brain2
  ├─ consolidation
  ├─ close-day
  └─ Life Model
```

### Zones principales

| Zone | Emplacements principaux |
|---|---|
| Mémoire canonique | `src/mlomega_audio_elite/` |
| Services PC live | `services/live-pc/` |
| Contrats | `packages/contracts/` |
| Unity PhoneOnly/XREAL | `apps/xr-mobile/Assets/Scripts/` |
| Plugins Kotlin | `apps/xr-mobile/android/` |
| Configuration | `configs/` |
| Modèles | `models/`, `scripts/fetch_models_v19.py` |
| Build et exploitation | `scripts/`, README et guides racine |
| Companion web | `apps/companion-web/` |

### Documents techniques associés

- `README.md` : installation et lancement général.
- `FIRST_TRY_ANDROID.md` : première session et validation device.
- `E46D_STATE.md` : historique Unity/Android E46-D.
- `docs/EXECUTOR_BUILD_GUIDE.md` : commandes de build et étapes E.
- `docs/DECISIONS.md` : décisions techniques durables.
- `docs/PROD_BACKLOG.md` : travaux différés.
- `OUTSIDE_ACCESS.md` : LAN/Tailscale et usage extérieur.
- `REPO_MAP.md` : architecture narrative.
- `repo_graph.json` : recherche structurée tables, flows et modules.
- `CALL_TRACE_PROOF.md` : chemins critiques lisibles.
- `call_trace_graph.json` : appels structurés.

Les cartes doivent être interrogées par recherche ciblée, jamais lues intégralement par défaut.

---

## 7. Invariants non négociables

1. Pas de démonstrations ni de scénarios métier codés en dur.
2. La mémoire reste continue, même hors fenêtre de commande.
3. Le wake word gate les commandes et intents, jamais l’audio ni l’ingestion mémoire.
4. En mode WebRTC, un seul accès microphone est autorisé.
5. L’ASR local reçoit le même PCM que le transport WebRTC.
6. Chaîne de vérité : `frame → observation → preuve → événement → mémoire`.
7. Toute UI exprime vérité, confiance et ancienneté.
8. Pas de nom de personne si l’identité est faible.
9. Pas de flèche spatiale si la pose ou la carte sont douteuses.
10. Pas d’assistance de conduite présentée comme certifiée.
11. Pas de suppression silencieuse d’un média encore référencé comme preuve.
12. Le cloud reste facultatif, visible et séparé.
13. Pas de VLM lourd sur chaque frame.
14. Le live doit préserver latence, batterie, chauffe et VRAM.
15. PhoneOnly et les sessions réelles priment sur les nouvelles options hypothétiques.
16. Un test unitaire, JVM, EditMode ou PC ne prouve pas automatiquement le chemin matériel.
17. Ne jamais marquer Android, PhoneOnly, XREAL, JNI, WebRTC ou DataChannel `proven` sans preuve correspondant à la frontière réelle.
18. Ne pas lancer le close-day sur une simple perte réseau, un `OnDisable`, un `OnDestroy` ou une déconnexion WebRTC.
19. Ne pas utiliser `git add -A` dans ce dépôt ; ajouter des chemins explicites.
20. Les secrets, `.env`, modèles, SDK local XREAL, logs et archives de conversation ne doivent pas être commités.

---

## 8. État global consolidé

### 8.1 Socle mémoire et live

Le socle V18.8 puis V19 est rapporté comme comprenant :

- ingestion audio et vision ;
- stockage SQLite ;
- événements et preuves ;
- BrainLive ;
- Brain2 ;
- mémoire longitudinale ;
- replay ;
- consolidation ;
- Life Model ;
- VisionRT ;
- WorldBrain ;
- contrats de transport et UI ;
- delivery d’intents ;
- PhoneOnly Unity ;
- scénarios et tests de simulation.

Statut global : `reported` à `partially_proven` selon les flows. Le checkout et les cartes doivent être consultés pour le détail.

### 8.2 E21→E38

Rapporté comme construit :

- fondations V19 ;
- contrats ;
- simulateurs ;
- transport ;
- UI PhoneOnly ;
- cache de scène ;
- VisionRT ;
- WorldBrain ;
- mémoire et intents ;
- context packs ;
- replay ;
- traitement audio nocturne ;
- fusion audio/vision ;
- auto-confirmation d’hypothèses.

E38 avait été annoncé avec 181 tests verts. Cela ne constitue pas une preuve matérielle.

### 8.3 E46-D — Unity / PhoneOnly / APK

Rapporté :

- Unity 6000.0 ;
- SDK Android 34 ;
- NDK r23b ;
- JDK 17 ;
- Gradle 8.7 ;
- CMake 3.22.1 ;
- IL2CPP ARM64 ;
- minSdk 29 ;
- targetSdk 34 ;
- AAR reconstruits ;
- scène PhoneOnly générée ;
- APK produite ;
- 59/59 tests Unity EditMode ;
- commit `6d2d38a`.

Correction durable :

- sérialisation JSON centralisée pour éviter les transformations silencieuses de timestamps ISO sous culture française.

Les artefacts E46-D sont historiques et `obsolete`.

### 8.4 E47-A — Audio, ASR, KWS et wake word initial

Architecture rapportée :

```text
JavaAudioDeviceModule WebRTC
        ↓ même PCM
MicAudioFanout
  ├─ WebRTC → PC → mémoire
  └─ sherpa local → VAD / ASR / KWS
```

Comportements attendus :

- un seul micro ;
- fan-out PCM ;
- ASR local ;
- KWS ;
- sous-titres locaux ;
- fenêtre de commande ;
- `is_command=true` dans la fenêtre ;
- audio et mémoire continus hors fenêtre.

Le wake word historique par défaut était `omega`. La session suivante l’a remplacé par une configuration runtime par défaut `viki`.

### 8.5 E47-B — Gestes

Rapporté :

- paume : ouvrir le menu ;
- balayage : masquer l’UI ;
- pincement : zoom ;
- scheduler d’activation ;
- MediaPipe autour de 12 fps.

La session E60 a ensuite révélé que des composants Reflex pouvaient exister sans être réellement levés dans la scène ou le runtime produit.

Les raccordements ont été rapportés corrigés, mais restent `device_to_verify`.

### 8.6 E47-C — Modèles, gating et multi-session

Endpoints rapportés :

```text
GET /models/device/manifest
GET /models/device/{name}
```

Modèles :

- ASR FR ;
- ASR EN ;
- KWS ;
- hand landmarker ;
- gesture recognizer.

Politique :

- `open` : transcripts finaux utilisables par les intents ;
- `gated` : seuls les segments `is_command=true` vont aux intents ;
- mémoire continue dans les deux modes.

Multi-session :

```powershell
python scripts\run_phoneonly_close_day.py --allow-rerun
```

L’implémentation initiale a ensuite été durcie dans E60 pour relire l’état depuis la base plutôt que dépendre uniquement de la mémoire du processus.

### 8.7 E48-A — Confort PhoneOnly

Rapporté :

- téléchargement des modèles dans l’app ;
- vérification de hash ;
- stockage applicatif ;
- progression et erreurs ;
- LAN prioritaire ;
- fallback Tailscale ;
- traduction live device ;
- comportement dégradé si modèles manquants.

Statut : `partially_proven`, validation device et extérieur encore ouverte.

### 8.8 E48-B — ChangeAttention

Rapporté :

- détection de changement de zone ou d’état ;
- anti-bruit ;
- vérité prudente ;
- cue discret via le delivery existant ;
- pas de flèche précise si la qualité de carte est faible.

Statut : tests ciblés rapportés, validation terrain ouverte.

### 8.9 E49 — XREAL réel

Rapporté :

- SDK XREAL local non commité ;
- tarball local injecté temporairement ;
- defines XREAL ;
- adaptateur réel ;
- build dédié ;
- APK `mlomega-xreal-g1.apk` ;
- commit `821885e`.

Le build XREAL reste distinct. Le manifest commité doit rester propre après les modifications temporaires de build.

Statut : `device_to_verify`.

### 8.10 E50 — Dashboard mémoire

Rapporté :

- dashboard en lecture seule ;
- inspection des événements ;
- personnes, objets, lieux et routines ;
- preuves ;
- sorties close-day ;
- diagnostic des premières sessions réelles ;
- commit `3defe56`.

Le dashboard ne remplace pas une base remplie par une vraie session.

### 8.11 E51 — Welcome / installateur guidé

Rapporté :

- choix PhoneOnly ou XREAL ;
- vérification environnement ;
- aide modèles ;
- aide réseau ;
- choix de fonctions ;
- profil utilisateur ;
- parcours guidé.

Statut : test neuf utilisateur encore ouvert.

### 8.12 E52 — README

Le README a été réécrit pour servir de page d’entrée :

- architecture ;
- prérequis ;
- installation ;
- lancement PC ;
- modèles ;
- APK ;
- première session ;
- extérieur ;
- liens vers guides.

Les commandes doivent rester cohérentes avec les scripts et les packages actuels.

### 8.13 E53 Phase A — Aide universelle

#### Moteur PC rapporté

- module `services/live-pc/help_mode.py` ;
- compréhension de demandes « aide-moi à… » ;
- plan en micro-actions ;
- étape courante et aperçu N+1 ;
- keyframe/VLM initial si disponible ;
- liens avec tracks VisionRT ;
- contrôles suivant, terminé, répète, pause, reprise et arrêt ;
- watchdog ;
- persistance dans `help_mode_tasks` ;
- reprise de tâche.

#### Unity / TaskAtoms rapportés

- `task_panel` ;
- `task_anchor` ;
- composants pour instruction, outil, zone, validation, erreur, progression et aide ;
- utilisation des tracks `SceneCache` si réellement localisés.

Preuves rapportées :

- 62 tests ciblés avec non-régression ;
- commits `dcc4af4` et `98e9adf`.

Limites :

- petites pièces ;
- vis ;
- étapes fines ;
- validation automatique ambiguë ;
- qualité de l’ancrage ;
- performance et ergonomie device.

Statut : `partially_proven`, usage réel `device_to_verify`.

### 8.14 E54 — Stockage et rétention

Rapporté :

- pas de vidéo brute infinie ;
- keyframes et clips sélectionnés ;
- tiers chaud, tiède et froid ;
- budgets disque ;
- conservation des preuves référencées ;
- nettoyage best-effort ;
- erreurs visibles ;
- commit `f6bdc4b`.

Les erreurs de rétention ne doivent pas casser le close-day, mais ne doivent pas être masquées.

### 8.15 E55 — Clips vidéo replay

Rapporté initialement :

- `ClipRecorder` ;
- tests isolés ;
- frames reçues ;
- clips courts ;
- horodatage et provenance ;
- intégration replay/preuves ;
- commit `3f2106d`.

Lors de l’audit E60, le composant était présent mais non instancié dans le chemin production.

Les dernières cartes de navigation indiqueraient qu’E60 final construit et démarre désormais `ClipRecorder`, puis le transmet à l’ingress.

Statut consolidé :

> raccordement final `reported`, à confirmer dans le checkout ; comportement réel `device_to_verify`.

### 8.16 E56 — VLM nocturne et environnement cœur

Rapporté :

- environnement Python cœur séparé ;
- VLM lourd réservé au différé ;
- Qdrant ;
- keyframes/clips ;
- pas de concurrence permanente avec VisionRT ;
- scripts de lancement et diagnostic ;
- commit `a79cacd`.

Décision durable : préserver la RTX 3070 et la boucle live ; déplacer l’analyse profonde après la session.

### 8.17 E58 — Wake word runtime

Rapporté :

- source de vérité dans le profil PC ;
- défaut `viki` ;
- commande `set_wake_word` ;
- DataChannel PC→Unity ;
- `DeviceCommandHandler` ;
- `AsrBridge.SetWakeWord` ;
- JNI/Kotlin ;
- acknowledgement `device_command_result` ;
- retry côté PC ;
- détection dans la transcription ASR française ;
- commit `3ba5a66`.

Le wake word ouvre une fenêtre de commande, sans interrompre l’audio ni la mémoire.

Statut : tests unitaires rapportés, `device_to_verify`.

### 8.18 E59 — Manipulation des panneaux

Rapporté :

- `PanelManipulator.cs` ;
- `IManipulablePanel.cs` ;
- `ManipulablePanelRegistry.cs` ;
- déplacement ;
- redimensionnement ;
- fermeture ;
- minimisation ;
- restauration ;
- position/taille conservées durant la session ;
- aspect ratio vidéo verrouillé ;
- coexistence avec le zoom `LensWindow` ;
- 8 nouveaux tests ;
- Unity 76/76 ;
- commit `2f86ddc`.

Les éléments ancrés à des objets, tels que `task_anchor` ou `PersonTag`, ne doivent pas devenir des fenêtres libres.

Statut : `device_to_verify`.

### 8.19 E60 — Audit préproduction et raccordements

L’audit a confirmé un problème méthodologique majeur :

> plusieurs composants existaient et passaient des tests isolés sans être raccordés au vrai chemin produit.

Bloquants trouvés à ce moment :

- signaux Reflex non levés en production ;
- menu absent de la scène ;
- TTS non activé ou non consommé ;
- `ClipRecorder` non instancié ;
- mauvais application ID PhoneOnly ;
- scène non régénérée automatiquement ;
- garde de fin de session fragile ;
- multi-session dépendant de mémoire processus ;
- orientation mal propagée ;
- sinks PCM non détachés ;
- wake word sans ack/retry robuste ;
- `pose_valid` absent ;
- vision lourde dans la boucle asyncio ;
- `GpuArbiter` dormant ;
- erreurs BrainLive masquées ;
- close-day sans attente robuste ;
- IDs objets non persistants ;
- journée visuelle en UTC ;
- manifeste close-day circulaire.

Corrections rapportées :

- `PhoneOnlyReflexSignalSource` ;
- menu ajouté à la scène ;
- TTS activé et `TtsAudioPlayer` ajouté ;
- fallback micro ;
- `allow_rerun` relu depuis la DB ;
- orientation et `pose_valid` ;
- détachement PCM ;
- wake word ack/retry ;
- vision lourde déplacée dans `asyncio.to_thread` ;
- watchdog close-day ;
- IDs d’entités stables ;
- journée Europe/Paris ;
- manifeste close-day relu depuis les tables ;
- appId PhoneOnly corrigé ;
- génération de scène forcée ;
- documentation E60.

Les dernières cartes indiqueraient aussi :

- `ClipRecorder` construit et démarré ;
- `ClipRecorder` transmis à l’ingress ;
- `GpuArbiter` construit.

Statuts consolidés :

- câblage `ClipRecorder` : `reported`, `to_verify` ;
- câblage `GpuArbiter` : `reported`, `to_verify` ;
- garde `ActiveBaseUrl` dans `EndExplicitly` : `to_verify` ;
- matrice matérielle : `device_to_verify`.

---

## 9. Tests et validations rapportés

Ces résultats couvrent des dates et périmètres différents.

| Périmètre | Résultat rapporté |
|---|---:|
| E38 | 181 tests verts |
| V19 E46-D | 207 passés, 2 ignorés |
| V18 ciblé | 5/5 |
| Unity EditMode E46-D | 59/59 |
| E47 JVM | 42 |
| E47 pytest | 226 |
| E53 ciblé | 62 |
| E59 nouveaux tests | 8 |
| Unity EditMode après E59 | 76/76 |

Ces chiffres ne prouvent pas :

- une installation Android ;
- le transport réel téléphone→PC ;
- les gestes réels ;
- XREAL ;
- un close-day sur données vécues ;
- que les APK correspondent au dernier `HEAD`.

Les tests E60 exacts doivent être retrouvés dans Git, les logs ou le dernier handoff de session.

---

## 10. Artefacts connus

### APK E46-D

```text
Fichier : apps/xr-mobile/build/android/mlomega-phoneonly.apk
Taille : environ 54,6 Mo
SHA-256 : 31762C5032947FFFACE94BC3F4F096366518B83D0BE7C86831C3D60AD9C53445
Commit : 6d2d38a
Statut : obsolete
```

### APK E47 v2

```text
Fichier : apps/xr-mobile/build/android/mlomega-phoneonly.apk
Taille : environ 54,6 Mo
SHA-256 : BCC6899740582026B964FB6B43127405374241CA91EECFFD22C3E0AB13315A0C
Commit : db1e426
Statut : obsolete
```

### PhoneOnly v5

```text
SHA-256 rapporté :
952543A0E0F6EE8A10A783E8BF26F86F8A1CA9BD42F62471AE5D23198B8CEDD5

Statut :
obsolete jusqu’à preuve qu’elle a été reconstruite après tous les patches E60.
```

### XREAL v3

```text
APK distincte.
SDK XREAL inclus localement.
Statut : obsolete jusqu’au rebuild post-E60 et à la validation physique.
```

### Artefacts attendus

- APK PhoneOnly reconstruite depuis le `HEAD` final ;
- APK XREAL reconstruite depuis le même état fonctionnel ;
- package vérifié ;
- taille vérifiée ;
- signature vérifiée ;
- SHA-256 enregistrés ;
- correspondance commit/artefact documentée.

---

## 11. Problèmes actuellement ouverts

### 11.1 Vérité Git

- identifier la racine réelle ;
- confirmer remote, branche et `HEAD` ;
- lister le working tree ;
- identifier les changements intentionnels ;
- exclure logs, modèles, SDK XREAL, `.env`, APK et archives.

### 11.2 Raccordements E60

À vérifier dans le checkout :

- `ClipRecorder` construit ;
- `ClipRecorder` démarré ;
- `ClipRecorder` transmis à l’ingress ;
- `GpuArbiter` construit ;
- `GpuArbiter` réellement utilisé ;
- garde `ActiveBaseUrl` dans `EndExplicitly`.

### 11.3 Builds finaux

- régénérer la scène PhoneOnly ;
- reconstruire PhoneOnly ;
- reconstruire XREAL ;
- vérifier appId/package ;
- vérifier manifest Unity propre ;
- enregistrer hashes et commit source.

### 11.4 PhoneOnly réel

À tester :

- installation ;
- permissions ;
- pairing ;
- audio WebRTC ;
- vidéo WebRTC ;
- micro unique ;
- ASR local ;
- wake word `viki` ;
- commande gated ;
- mémoire continue hors wake word ;
- sous-titres ;
- traduction ;
- gestes ;
- menu ;
- zoom ;
- panneaux E59 ;
- TTS ;
- E53 ;
- ChangeAttention ;
- reconnexion ;
- arrière-plan/veille ;
- fin explicite ;
- close-day.

### 11.5 XREAL réel

À tester :

- détection matériel ;
- caméra ;
- pose ;
- rendu ;
- UIIntent ;
- gestes ;
- E53 anchors ;
- panneaux ;
- reconnexion ;
- chauffe ;
- latence ;
- reprise après débranchement.

### 11.6 Mémoire réelle

- terminer une session vécue ;
- lancer un vrai close-day ;
- inspecter la DB ;
- inspecter événements et preuves ;
- vérifier clips et rétention ;
- vérifier dashboard ;
- mesurer la qualité du Life Model ;
- documenter les frictions.

### 11.7 Graphes de navigation

Les cartes actuelles ont reçu un delta daté, pas une régénération complète.

À terme :

- rescanner le dépôt ;
- fusionner les nouveaux flows dans les structures principales ;
- éviter l’accumulation de clés `session_delta_*` ;
- conserver les statuts de preuve ;
- valider JSON ;
- ne pas prétendre à une preuve matérielle.

### 11.8 Backup

Toujours différé :

- `memory.db` ;
- keyframes ;
- clips ;
- audio ;
- médias de preuve ;
- sauvegarde chiffrée ;
- destination externe ou NAS ;
- test de restauration.

### 11.9 TTS entièrement offline

Le TTS connecté PC→Unity a été rapporté raccordé. Un TTS entièrement hors ligne sur téléphone reste différé ou à confirmer selon le checkout.

### 11.10 Tailscale extérieur

Code et documentation rapportés. Usage extérieur réel encore à valider.

---

## 12. Décisions durables

### PhoneOnly d’abord

Le téléphone est le premier terrain de vérité. Les nouvelles fonctions ne doivent pas remplacer la validation réelle.

### Mémoire continue

Le wake word ne coupe jamais l’audio, la transcription destinée à la mémoire ou l’ingestion.

### Micro unique

WebRTC possède l’unique capture microphone. Les fonctions locales consomment le même flux PCM.

### Preuve avant mémoire

Aucune frame ne devient directement une mémoire canonique.

### VLM lourd différé

Le live utilise des traitements budgétés. L’analyse lourde se fait après session.

### Vérité UI

Confiance, fraîcheur, qualité de carte et preuve doivent conditionner ce qui est affiché.

### Close-day

La fin manuelle reste voulue. Un watchdog couvre les interruptions graves, sans transformer chaque perte réseau en clôture.

### Rétention

Les erreurs de nettoyage ne cassent pas la consolidation, mais restent visibles. Une preuve référencée ne doit pas être supprimée silencieusement.

### XREAL

SDK local non commité, build dédié, manifest propre après build.

### Aide universelle

La version réaliste repose sur :

- plan PC ;
- checklist ;
- étape courante ;
- TaskAtoms ;
- surlignage objet/zone ;
- progression vocale ;
- confirmation semi-automatique.

La reconnaissance parfaite de chaque micro-geste ou petite pièce reste non fiable.

### RoadWorld

Seulement des cues prudents. Aucune autorisation de manœuvre, trajectoire sûre ou promesse de sécurité.

### Companion web

Le viewer iPhone affiche les cards, sous-titres, suggestions et receipts. Il ne capture pas la caméra ou le micro.

### Contrôle Git

Pas de `git add -A`. Pas de commit de secrets, modèles, SDK locaux, logs ou builds.

---

## 13. Prochaine action recommandée

Ne pas lancer E61 ni une nouvelle refonte.

Ordre recommandé :

1. inspecter Git et le working tree ;
2. lire le dernier `handoffLastSession` ;
3. vérifier `ClipRecorder`, `GpuArbiter` et `ActiveBaseUrl` ;
4. lancer les tests ciblés correspondants ;
5. vérifier les scripts et paramètres de build ;
6. régénérer la scène PhoneOnly ;
7. reconstruire PhoneOnly depuis le `HEAD` final ;
8. reconstruire XREAL depuis le même état ;
9. relever packages, tailles, signatures et hashes ;
10. installer sur S25 ou appareil Android de validation ;
11. exécuter la matrice PhoneOnly ;
12. exécuter la matrice XREAL si le matériel est disponible ;
13. terminer une session réelle ;
14. lancer un vrai close-day ;
15. inspecter mémoire, dashboard, clips et rétention ;
16. corriger les frictions observées avant toute nouvelle fonctionnalité.

### Critères de fin minimaux

La prochaine grande étape n’est considérée terminée que si :

- le `HEAD` est documenté ;
- le working tree est compris ;
- les APK correspondent au `HEAD` final ;
- les hashes sont enregistrés ;
- les raccordements E60 sont confirmés dans le checkout ;
- au moins la matrice PhoneOnly est réellement exécutée ;
- les erreurs sont documentées ;
- une fin de session est enregistrée ;
- un vrai close-day est tenté ;
- les résultats mémoire sont examinés ;
- aucune nouvelle fonction ne masque les problèmes terrain.

---

## 14. Commandes ciblées de reprise

### Git

```powershell
git status --short
git branch --show-current
git log --oneline -30
git rev-parse HEAD
git remote -v
```

### E60

```powershell
rg "ClipRecorder\(|GpuArbiter\(" services\live-pc
rg "ActiveBaseUrl|EndExplicitly" apps\xr-mobile\Assets\Scripts
rg "PhoneOnlyReflexSignalSource|TtsAudioPlayer|pose_valid" apps services packages
```

### E53

```powershell
rg "HelpTaskEngine|help_mode_tasks|task_panel|task_anchor" services apps tests
```

### E58

```powershell
rg "set_wake_word|device_command_result|WakeWordMatcher|viki" services apps configs tests
```

### E59

```powershell
rg "PanelManipulator|IManipulablePanel|ManipulablePanelRegistry" apps\xr-mobile
```

### Navigation

```powershell
rg "Delta 2026-07-10|session_delta_2026_07_10" REPO_MAP.md CALL_TRACE_PROOF.md repo_graph.json call_trace_graph.json
python -m json.tool repo_graph.json > $null
python -m json.tool call_trace_graph.json > $null
```

### Artefacts

```powershell
Get-ChildItem apps\xr-mobile\build\android\*.apk -ErrorAction SilentlyContinue
Get-ChildItem apps\xr-mobile\Assets\Plugins\Android -File -ErrorAction SilentlyContinue
Get-ChildItem models\device -Recurse -File -ErrorAction SilentlyContinue
```

Ne pas lancer de build Unity lourd avant de vérifier :

- version Unity ;
- licence ;
- SDK ;
- NDK ;
- JDK ;
- Gradle ;
- manifest ;
- packages ;
- AAR ;
- espace disque ;
- instance Unity déjà ouverte.

---

## 15. Historique condensé des sessions

### Session 1 — 3 au 7 juillet 2026

#### Baseline

La session part d’un audit du socle V18.8 et du guide V19.

Le socle est jugé sérieux pour :

- ingestion ;
- stockage ;
- preuves ;
- BrainLive ;
- deep audio/vision ;
- replay ;
- mémoire longitudinale.

Faiblesses identifiées :

- prédictions insuffisamment vérifiées ;
- calibration incomplète ;
- séparation hypothèse/fait à renforcer ;
- preuves persistantes à mieux relier.

#### Travaux

- plan V19 en trois lots ;
- E21→E38 ;
- audits et corrections Codex ;
- E46-D Unity/PhoneOnly ;
- E47 audio/ASR/KWS ;
- E47 gestes ;
- E47 modèles/gating/multi-session ;
- APK PhoneOnly v2 ;
- documentation de première session.

#### Décisions importantes

- pas de deuxième micro ;
- wake word sans coupure mémoire ;
- tests matériels avant E48 ;
- XREAL doit réutiliser l’architecture existante ;
- aide universelle réaliste en version A ;
- RoadWorld seulement informatif.

#### État laissé

- S25 non validé ;
- modèles à installer ;
- vraie session non faite ;
- close-day réel non fait ;
- E48 différé.

### Session 2 — 8 au 10 juillet 2026

#### Baseline

La session reprend le socle E46/E47 et cherche à rendre le produit plus utilisable avant le terrain.

#### Travaux

- E48-A modèles, Tailscale et traduction ;
- E48-B ChangeAttention ;
- E49 XREAL ;
- E50 dashboard ;
- E51 welcome ;
- E52 README ;
- E54 rétention ;
- E55 clips ;
- E56 VLM nocturne ;
- E58 wake word runtime ;
- E53 Phase A aide universelle ;
- E59 panneaux manipulables ;
- audit E60 ;
- corrections de raccordement ;
- mise à jour des quatre cartes.

#### Découverte principale

Les tests de composants n’assuraient pas leur présence dans le chemin production.

#### État laissé

- majorité des corrections E60 rapportées ;
- `ClipRecorder` et `GpuArbiter` rapportés raccordés dans les dernières cartes, à vérifier ;
- garde `ActiveBaseUrl` à vérifier ;
- APK v5/v3 probablement antérieures aux derniers patches ;
- rebuild final requis ;
- validation PhoneOnly/XREAL et close-day réel toujours ouverts.

---

## 16. Discipline de mise à jour du HANDOFF GLOBAL

À chaque nouvelle session :

1. lire le `HANDOFF_GLOBAL.md` courant ;
2. lire le nouveau `handoffLastSession` ;
3. comparer avec `REPO_MAP.md`, `repo_graph.json`, `CALL_TRACE_PROOF.md`, `call_trace_graph.json` et les documents récents fournis ;
4. donner priorité au checkout et aux cartes les plus récentes ;
5. mettre à jour l’état global, pas seulement ajouter du texte ;
6. retirer des problèmes ouverts ce qui est réellement résolu ;
7. conserver les anciens problèmes dans l’historique de leur session ;
8. ajouter la nouvelle session dans l’historique condensé ;
9. condenser progressivement les sessions les plus anciennes ;
10. ne pas recopier les derniers échanges réels dans le global ;
11. ne pas recopier toutes les commandes ou tous les commits si les guides ou Git les contiennent déjà ;
12. conserver les décisions encore actives ;
13. signaler toute contradiction entre handoff, cartes et checkout ;
14. préserver les statuts `reported`, `to_verify`, `device_to_verify`, `partially_proven` et `obsolete` ;
15. garder le document lisible et orienté reprise.

Le document peut être large, mais il ne doit pas croître sans limite.

L’état courant et les problèmes ouverts doivent rester faciles à trouver.  
Les anciennes sessions doivent être progressivement compressées.  
Les détails chauds et les derniers échanges restent dans les `handoffLastSession` archivés.

---

## 17. Archives à conserver

```text
handoffs/
  HANDOFF_GLOBAL.md
  2026-07-07_handoffLastSession.md
  2026-07-10_handoffLastSession.md
  YYYY-MM-DD_handoffLastSession.md
```

Conserver aussi les exports originaux de conversation, mais ne les lire que par recherche ciblée pour retrouver :

- une commande exacte ;
- une erreur ;
- un commit ;
- un résultat de test ;
- une décision ambiguë ;
- un rapport de sous-agent ;
- un échange utilisateur important.

Les archives ne remplacent jamais le checkout.

---

## 18. Message minimal pour le prochain agent

Tu reprends MemOs / MLOmega V19.

Le checkout Git courant est la source de vérité.

Commence par lire :

1. le `handoffLastSession` le plus récent ;
2. ce `HANDOFF_GLOBAL.md` ;
3. `REPO_MAP.md` uniquement pour l’orientation ;
4. les graphes JSON et preuves d’appels uniquement par recherches ciblées.

Vérifie immédiatement la branche, le `HEAD`, le working tree et les APK présentes.

La priorité actuelle est de confirmer les raccordements E60, reconstruire les APK depuis le `HEAD` final, puis exécuter une vraie matrice PhoneOnly/XREAL et un vrai close-day.

Ne lance pas de nouvelle grande fonctionnalité avant cette validation.

---

# Aide développeur : À ne pas supprimer

Trucs spécifiques à CE repo qu'un nouveau dev ne peut pas deviner. Vérifié sur machine réelle (Windows 11, Unity 6000.0.23f1, PS 5.1).

## Environnements Python (2, ne pas mélanger)
- `.venv` = CŒUR (torch cu121/WhisperX/pyannote) → exécute le **close-day nocturne** (`run_phoneonly_close_day.py`). Créé à la main : `python -m venv .venv` + `pip install -r requirements-v18_8-windows.lock.txt` (forcer Python 3.11 : `py -3.11`).
- `.venv-live` = LIVE (aiortc, sherpa, cv2…) → tout `pytest tests/v19` se lance avec `.venv-live\Scripts\python -m pytest`. Créé par `scripts/INSTALL_MLOMEGA_V19_WINDOWS.ps1` (transactionnel).

## Tests de non-régression (ciblés, jamais la suite complète sauf jalon)
- PC ciblé par zone : `tests/v19/test_e33_intents.py test_wake_word_gating.py` (routeur), `test_help_mode.py` (E53), `test_media_retention.py test_longitudinal_periods.py` (E54), `test_clip_recorder.py` (E55), `test_device_provisioning.py` (E47-C/48-A), `test_change_attention.py` (E48-B), `test_phoneonly_runtime.py`.
- Kotlin JVM + export AAR : `powershell -ExecutionPolicy Bypass -File scripts\BUILD_ANDROID_PLUGINS.ps1` (JDK17 + Gradle local `.tools\gradle-8.7`).
- Unity EditMode (suite ~76+) : `Unity.exe -batchmode -runTests -testPlatform EditMode -projectPath apps\xr-mobile -testResults out.xml -logFile out.log` (PAS de `-quit` avec `-runTests`).
- Règle passation : ne jamais croire un chiffre de tests sans le ré-exécuter et le dater.

## Builds Unity (pièges majeurs)
- **Unity.exe est une app GUI** : en PowerShell, `& Unity.exe …` NE BLOQUE PAS et `$LASTEXITCODE` reste vide → toujours `Start-Process -Wait -PassThru -NoNewWindow` et lire `.ExitCode`.
- **Une seule instance** sur le projet (lockfile `Temp/UnityLockfile`). Fermer toute fenêtre Unity avant un build headless.
- Licence : activée par login Unity Hub (interactif, une fois). Les lignes `[Licensing] Error Code 500/No ULF` dans les logs sont souvent NON fatales — le verdict = exit code + fin de log.
- APK phone : `-executeMethod MLOmega.XR.Editor.AndroidBuild.BuildApk` (env `MLOMEGA_PC_HOST/PORT`). APK lunettes : **2 passes** — `AndroidBuildXreal.PrepareDefines` PUIS `AndroidBuildXreal.BuildApk` (SDK dans `Packages/xreal-sdk/com.xreal.xr.tar.gz`, git-ignoré, fourni par l'utilisateur).
- **Après un build lunettes, reverter les artefacts avant commit** : `git checkout -- apps/xr-mobile/ProjectSettings/ProjectSettings.asset ProjectSettings/EditorBuildSettings.asset Packages/packages-lock.json Assets/XR/XRGeneralSettingsPerBuildTarget.asset Packages/manifest.json` — le manifest commité doit rester SANS `com.xreal.xr` (un clone sans SDK doit compiler).

## Unity/C# — conventions vitales
- **Cycle asmdef interdit UI↔Reflex** : Reflex référence UI ; UI ne référence JAMAIS Reflex → communiquer par événements sur `DeviceCommandHandler` (pattern `TranslateLiveRequested`/`SetWakeWordRequested`).
- Référencer l'assembly XREAL **par GUID** (`GUID:2b1cc58b5fab727499169f06e9336a3b`) — la réf par nom ne résout pas ici. Code SDK sous `#if XREAL_SDK_PRESENT`.
- **EditMode : `Awake()` ne tourne PAS via `AddComponent`** → dans les tests, injecter les configs par réflexion (voir `TaskAtomsCompositionTests` : `SceneCacheConfig.CreateDefault()` posé sur `_config`).
- Tout nouveau `.cs` doit avoir son `.cs.meta` avec GUID unique (2 lignes suffisent).
- Les composants UIIntent s'enregistrent dans `UIComponentRegistry` (table statique) — pas besoin de toucher la scène pour un nouveau composant admis par le broker.

## PowerShell (PS 5.1)
- **Tout `.ps1` contenant des accents/— doit être UTF-8 AVEC BOM** (sinon lu en ANSI → guillemets parasites → parse error). Réécrire via `[IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($true)))` — l'outil d'édition standard retire le BOM.
- Pas de `&&` ni ternaire ; pour `git commit`, préférer plusieurs `-m` aux here-strings (apostrophes = pièges).

## Git — quoi ne JAMAIS committer
`.env` (secrets, clé OpenAI), `configs/user_profile.yaml`, `models/` et `apps/xr-mobile/Assets/StreamingAssets/models/` (poids régénérés), `build/android/*.apk`, `Packages/xreal-sdk/`, `Oldconversation/`, logs/xml de build. `git add` explicite, jamais `-A`.

## Ports occupés (ne pas réutiliser)
8710 SessionHub · 6333/6334 Qdrant · 11434 Ollama · **8766 interdit** (Phone Bridge historique) · 8704/8706 profils sim · 8720 dashboard · 8776 · 8601.

## Modèles & config
- `scripts/fetch_models_v19.py --device` (`.venv-live`) : télécharge + **épingle les sha256 au premier fetch** dans `configs/MODEL_MANIFEST.yaml` (pattern PENDING_FETCH). VLM jour=moondream, nuit=`MLOMEGA_OFFLINE_VLM_MODEL` (.env).
- Wake word : `wake_word:` dans `user_profile.yaml` (défaut viki), poussé au device à la connexion — pas de rebuild. Le mot est entendu par l'ASR **français**.

## Discipline documentaire (le contrat du repo)
Chaque étape close = case cochée dans `docs/PROD_BACKLOG.md` + ADR dans `docs/DECISIONS.md` + section dans `docs/EXECUTOR_BUILD_GUIDE.md` (+ delta dans REPO_MAP/CALL_TRACE si contrat/flow/table change). `Oldconversation/MLOmega_V19_reconstitution_complete.md` : JAMAIS en entier, grep ciblé uniquement. Le début de `PROD_BACKLOG.md` a un mojibake historique : ne pas « réparer » en masse (diff illisible).

## Debugging live (les URLs qui sauvent)
- `http://<PC>:8710/health` = pairing_ready · `/ready` = chaîne IA complète · `/metrics` = compteurs live (conversation_turns, h1_candidates, wake_word_policy, turns_gated_out, drops clips…) · `/session/status` = état session/close-day.
- Dashboard mémoire lecture seule : `scripts\RUN_DASHBOARD.ps1` → http://localhost:8720 (SQLite mode=ro, jamais d'écriture).
- La fenêtre de `RUN_MLOMEGA_V19.ps1` EST le journal live — la laisser ouverte.
- Base : chemin dans `MLOMEGA_DB` (.env) ; timezone produit via `MLOMEGA_LOCAL_TZ` (défaut Europe/Paris).

## LLM/VLM — subtilités
- `num_predict` ≠ fenêtre de contexte : Ollama live = `num_ctx 4096`, post-stop = `16384` ; toute sortie `done_reason=length` est REJETÉE atomiquement (jamais de JSON partiel promu).
- Le routeur LLM parle en JSON strict via `complete_json(system, user, schema_hint=…)` — nouveau intent = enum du schema + few-shot + règle grammaire.
- **Ordre des règles grammaire du routeur = piège récurrent** : les règles spécifiques AVANT les génériques (« traduis en direct » avant « traduis », « aide-moi à » avant find/what_is, owner_enroll avant set_tts). Les contrôles de tâche active (« c'est fait », « répète ») passent par un PRÉ-routeur actif seulement si une tâche help tourne.

## Device/Kotlin — subtilités
- Les modules `services/live-pc/*.py` se chargent ENTRE EUX par chemin de fichier (`_load("nom", "fichier.py")`) — pas de package : imports relatifs interdits.
- L'AAR sherpa embarque `libonnxruntime.so` mais PAS l'API Java → l'API vient de `mlomega-onnxruntime.aar` (version alignée 1.17.1). Ne pas monter la version d'un seul côté.
- KWS sherpa = anglais → le wake word est détecté dans la TRANSCRIPTION ASR FR (`WakeWordMatcher.kt`), pas par le KWS. Traduction offline = OPUS-MT int8 via le provisioning (6 entrées manifest).
- aiortc DÉCODE les frames (pas de passthrough H.264) : l'enregistreur de clips ré-encode en CPU libx264 (subprocess priorité basse, file drop-on-full — le live ne doit JAMAIS être bloqué par l'encode).
- Un seul micro : `JavaAudioDeviceModule` fan-out → sherpa consomme `asPcmSink()` ; ne JAMAIS ouvrir un 2ᵉ AudioRecord en présence WebRTC.

## Close-day / mémoire — règles
- Fin de session = LE BOUTON « Terminer » (une déconnexion ne consolide pas) ; recovery durable via `phoneonly_session_recovery_v19` + watchdog.
- `cleanup_eligible` = AUTORISATION de purge, jamais une action. La purge réelle = `media_retention` (budget 100 Go, un média référencé par une preuve n'est JAMAIS supprimé ; WAV→Opus après re-transcription).
- 2ᵉ session du même jour : reopen via `--allow-rerun` (état lu en DB, pas en mémoire process).
- Invariants non négociables : mémoire continue (le wake word ne gate QUE le routage) ; frame→observation→preuve→événement→mémoire ; truth_level partout ; pas de démo en dur ; dégradé honnête.

## Pièges d'audit déjà vécus (ne pas re-tomber dedans)
- Un composant « testé » n'est pas « branché » : vérifier le CONSTRUCTEUR en prod (ClipRecorder/GpuArbiter l'ont appris) et l'appelant réel (RaiseSignal).
- La scène commitée ≠ le builder : `AndroidBuild.EnsureScene` régénère désormais TOUJOURS la scène — ne pas revenir en arrière.
- Vérifier l'`applicationIdentifier` de l'APK produite (`com.mlomega.xr.phoneonly`) — l'héritage d'un vieux ProjectSettings a déjà produit un mauvais package.
- Grep « pattern factory » : chercher `X(` rate `factory = mod.X` — chercher aussi le nom nu.
