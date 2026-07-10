# FIRST TRY ANDROID — Ta première session MLOmega (PhoneOnly)

Guide complet de la première session réelle : lancement PC + téléphone, tout ce que tu peux
dire et tester aujourd'hui, comment voir les suggestions, comment quitter.
Build : `mlomega-phoneonly.apk` (54,6 Mo) — endpoint injecté `192.168.1.199:8710`.

---

## 1. Lancement — côté PC (3 commandes)

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1
# Ollama : doit tourner (vérifie avec: ollama list — le modèle du .env doit apparaître)
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

La 3ᵉ commande lance TOUT (SessionHub + pipeline vision/audio + identité + delivery) en un
seul process. Laisse la fenêtre ouverte : c'est aussi ton journal en direct.

**Pré-vols :** `http://localhost:6333/healthz` → ok ; première fois : Windows demande
d'autoriser Python sur le réseau **privé** → accepte (port 8710 entrant).

## 2. Lancement — côté téléphone

1. Installe l'APK (`adb install -r apps\xr-mobile\build\android\mlomega-phoneonly.apk` ou copie le fichier et ouvre-le).
2. Ouvre l'app → accorde **micro** et **caméra**.
3. **Rien d'autre à faire** : pairing automatique vers le PC. La StatusBar (bandeau discret)
   affiche l'état : `Paired` puis `Connected`.
4. À la connexion de ta **première session du jour** : la carte **« Bonjour — aujourd'hui... »**
   (briefing du matin) doit apparaître. Jour 1 elle sera quasi vide — normal, ta mémoire naît.

## 3. Comment quitter (IMPORTANT)

**Le bouton « Terminer la session et lancer CloseDay » à l'écran.** Ce clic :
draine l'audio/vidéo proprement → termine la session → **déclenche automatiquement le
close-day sur le PC** (la consolidation nocturne complète : re-transcription HQ, diarisation,
Brain2, Life Model, prédictions). Suis son avancement dans la fenêtre PC ou via
`http://localhost:8710/session/status`.

⚠️ Fermer l'app sans le bouton (swipe/crash) NE termine PAS la session (résilience voulue :
tu peux rouvrir et reprendre la même session). Seul le bouton clôt et consolide.

---

## 4. Tout ce que tu peux dire (parle naturellement — pas de mot d'éveil dans ce build, le PC écoute toute la session)

### ⭐ À faire EN PREMIER
| Dis | Effet |
|---|---|
| « **Configure ma voix** » (puis parle ~10 s) | T'enrôle comme OWNER — tes paroles iront sous ton personID (et la nuit re-vérifie) |

### Vision / scène
| Dis | Effet attendu à l'écran |
|---|---|
| « **C'est quoi ça ?** » (vise un objet) | ContextCard avec le label (moondream si Ollama, sinon dégradé honnête) |
| « **Où est mon téléphone ?** » (ou clés/sac) | Contour si visible, sinon carte « dernier vu » avec l'âge |
| « **Lis le texte** » (vise un texte) | OCR affiché |
| « **Traduis-le** » | Traduction du dernier texte/parole ciblé |
| « **Zoom** » | LensWindow sur la zone visée |

### Personnes (le grand test)
| Dis / fais | Effet |
|---|---|
| Cadre une personne | **PersonTag anonyme** qui la suit (jamais de nom inventé) |
| Reste sur elle ~10 s (Ollama actif) | Possible « **? boulanger** »-style : hypothèse d'apparence/rôle |
| « **Retiens : c'est Karim** » | Enrollment visage+voix → PersonTag « Karim » + ContextCard profil |
| « **Non, ce n'est pas Karim** » | Correction durable, le nom saute |
| Reparle de Karim plus tard dans la session | La mémoire conversationnelle l'apprend (relations naissantes) |

### Mémoire (jour 1 : teste sur CE QUE TU AS DIT DANS LA SESSION — l'historique se construit)
| Dis | Effet |
|---|---|
| « **Interroge ma mémoire : qu'est-ce que j'ai dit sur [sujet évoqué il y a 10 min] ?** » | Réponse ContextCard sourcée (routeur Brain2) |
| « **Rappelle-moi ce que je devais faire** » | Ce qu'il a capté comme intentions/promesses |
| « **Rejoue 14h** » (après avoir capturé à 14h) | Diaporama VirtualScreen de la plage horaire |

### Suggestions automatiques (tu ne demandes rien — elles ARRIVENT)
- **Pendant une conversation** : si tu évoques un sujet/une promesse déjà en mémoire →
  une **ContextCard suggestion** apparaît d'elle-même (la boucle BrainLive H1). Jour 1 :
  rare (mémoire vide) ; le test réaliste : parle d'un truc, change de sujet 15 min, r'évoque-le.
- **Proactif** : prédiction du jour qui matche la scène, question de clarification posée
  dans un moment calme. Ces cards portent leurs sources (evidence).
- **Où les voir** : elles s'affichent SEULES à l'écran (priorité 6 du broker). Pour vérifier
  la tuyauterie : `http://localhost:8710/metrics` (compteurs `conversation_turns`,
  `h1_candidates`, `hypotheses_active`) et la table delivery dans les logs PC.
- **Latence normale** : la suggestion conversationnelle arrive 15-45 s après la parole
  (fenêtre de la policy — c'est voulu, pas un bug).

### Contrôle de l'UI / apps / modes
| Dis | Effet |
|---|---|
| « **Cache tout** » | Ne garde que la StatusBar |
| « **Affiche tout** » / « **mode Free Guy** » | Densité max |
| « **Ouvre le menu** » | MenuPanel (modes, apps, mémoire, replay...) |
| « **Ouvre Maps vers [destination]** » | Google Maps navigation (vraie app) |
| « **Lance YouTube [recherche]** » | YouTube |
| « **Mode payant avec OpenAI** » / « **mode local** » | Bascule cloud (refusée poliment si profil local_only) |
| « **Réponds à voix haute** » / « **tais-toi** » | TTS on/off (synthétisé PC, joué au téléphone) |

### Multi-tour (contexte 25 s)
« C'est quoi ça ? » … puis « **zoom dessus** » … puis « **traduis-le** » → même cible.

---

## 5. Ce qui NE marche PAS dans ce build (prévu E47, ne cherche pas un bug)
- **Wake word** (« Hey MLOmega ») — tout est écouté pendant la session, sans mot d'éveil.
- **Gestes** (pincer/paume/balayage) — utilise la voix ou le tap.
- **Autonomie sans PC** — coupe le PC = plus de sous-titres/reco (l'Ultra-Live local arrive en E47).
- **Dehors sans Tailscale** — cette session = même Wi-Fi que le PC.

## 6. Checklist de session (coche mentalement)
1. ☐ Briefing du matin reçu à la connexion
2. ☐ « Configure ma voix » fait
3. ☐ what_is sur 3 objets différents
4. ☐ PersonTag suit une personne ; enrollment « c'est X » ; correction « non c'est pas X »
5. ☐ Question mémoire sur un sujet évoqué plus tôt dans la session
6. ☐ Une suggestion spontanée reçue (r'évoque un sujet après 15 min)
7. ☐ « Où est mon téléphone » après l'avoir posé hors champ
8. ☐ Un toggle UI + « ouvre Maps »
9. ☐ `/metrics` regardé une fois (compteurs qui bougent)
10. ☐ **Fin par LE BOUTON** → close-day `running` → `completed` (fenêtre PC)

## 7. Si ça coince
- App bloquée sur Pairing → PC lancé ? `http://192.168.1.199:8710/health` depuis le
  navigateur du téléphone. Pare-feu Windows → autoriser Python (privé).
- Pas de réponse aux commandes → fenêtre PC : les transcripts défilent ? Sinon micro/permission.
- « c'est quoi ça » répond « indisponible » → Ollama éteint (`ollama serve`) — le reste marche.
- Close-day en erreur → il est repris automatiquement au prochain déclenchement (stages checkpointés) ;
  garde la sortie PC, on lira ensemble.

**Au réveil du close-day : ta mémoire aura ses premières routines candidates, entités, et
peut-être sa première prédiction. C'est là que tout commence.**

---

# MISE À JOUR — APK v2 (E47 : wake word, gestes, offline)

**Nouvel APK** : même fichier `mlomega-phoneonly.apk` (54,6 Mo, SHA-256 `BCC68997…5A0C`) — réinstalle par-dessus (`adb install -r ...`).

## ⚠️ Avant la session : pousser les modèles device (une fois)
```powershell
python scripts\fetch_models_v19.py --device
adb push models\device\. /sdcard/Android/data/com.mlomega.xr.phoneonly/files/models/
```
(Le nom exact du package est visible via `adb shell pm list packages | findstr mlomega`. Client de téléchargement automatique = prochain petit ajout.)

## 🆕 Nouveautés à tester

### Wake word (TON mot)
- Par défaut la politique est **open** : tu parles naturellement comme avant, pas de mot requis.
- Pour tester le mode gated : mets `wake_word_policy: gated` dans `configs\user_profile.yaml` (PC) → seules les phrases dites **après ton mot d'éveil** (défaut « omega », changeable dans MLOmegaConfig Unity) deviennent des commandes : « **omega… c'est quoi ça ?** ». Tout le reste continue d'alimenter ta mémoire — rien ne s'arrête jamais d'écouter.
- Fenêtre de commande : ~quelques secondes après le mot (configurable), StatusBar « à l'écoute ».

### Gestes (activés à la demande — lève la main devant la caméra)
| Geste | Effet |
|---|---|
| **Paume ouverte** tenue | Ouvre/ferme le menu |
| **Balayage latéral** | Cache toute l'UI |
| **Pincement** (pouce-index) | Zoom continu dans la LensWindow (dis « zoom » d'abord) |

### Sous-titres OFFLINE (le test d'autonomie)
Coupe le PC (ou le Wi-Fi) en pleine session → **les sous-titres continuent** (ASR sherpa local). Reconnecte → tout reprend.

### Multi-sessions le même jour
Tu peux maintenant faire 2-3 sessions dans la journée : chaque « Terminer la session » relance un close-day qui **reconsolide tout le jour** (plus de skip silencieux).

## Checklist ajoutée
11. ☐ « omega » (mode gated) → StatusBar écoute → commande routée ; phrase sans le mot → PAS routée mais bien en mémoire
12. ☐ Paume → menu ; balayage → UI cachée ; pinch → zoom
13. ☐ PC coupé → sous-titres toujours là ; retour PC → reconnexion auto
14. ☐ 2e session du jour → close-day relancé (`--allow-rerun` visible dans les logs PC)

---

# MISE À JOUR — APK v3 (E48 : modèles auto, traduction live, mode dehors, cue changement)

**Nouvel APK** : même fichier `mlomega-phoneonly.apk` (90,1 Mo — les petits modèles sont dedans) — réinstalle par-dessus (`adb install -r ...`). SHA-256 : `172394C67CBD451523E10D8CB6EF9140C8210D1BA0843BE5E7B7EA713199846B`.

⚠️ **v3 répare un bug invisible de v2** : la couche réflexe (wake word, gestes, sous-titres offline) n'était pas câblée dans la scène — ces features E47 ne pouvaient pas démarrer sur v2. **Refais les tests 11-13 sur v3** : c'est la première fois qu'ils peuvent vraiment passer.

## 🆕 Plus d'`adb push` : les modèles s'installent tout seuls
- Les petits modèles (wake word, gestes, VAD) sont **dans l'APK** → marchent dès l'installation.
- Les 2 gros modèles de reconnaissance vocale (~680 Mo) se **téléchargent automatiquement** depuis le PC au premier lancement (Wi-Fi conseillé) — suis la ligne `dl:<modèle> NN%` dans la StatusBar. En attendant la fin du download, les sous-titres offline restent indisponibles (dégradé normal, rien ne plante).
- Le `adb push models\device\.` manuel marche toujours si tu préfères.

## 🆕 Traduction live (offline, sur le téléphone)
- **Menu** (paume) → « **Traduire** » pour activer/couper, ou à la voix : « **traduis en direct** » / « **stop traduction** » (la voix passe par le PC ; hors connexion, utilise le menu).
- Effet : chaque phrase finale dans l'autre langue s'affiche **traduite sous le sous-titre original**. FR↔EN. Marche PC coupé.
- **Wake word (E58, APK v4)** : défaut « **viki** », **détecté dans l'ASR français** (prononciation naturelle — dis « viki », pas « vaïki »). Change-le **quand tu veux sans rebuild** : édite `wake_word:` dans `configs\user_profile.yaml` → poussé au téléphone à la prochaine session. Choisis un mot **rare** (on scanne tout ce que tu dis → un mot courant = faux déclenchements).

## 🆕 Mode dehors (Tailscale)
- L'app essaie maintenant les endpoints **dans l'ordre : LAN → Tailscale** (`100.113.42.19`, déjà dans le build).
- À faire une fois sur le téléphone : Play Store → **Tailscale** → connexion avec **le même compte** que le PC (contact.phonelib@) → activer le VPN. Ensuite : dehors en 4G/5G tout marche via le tunnel ; retour maison → re-bascule LAN automatique.
- Guide complet + checklist 4G : `docs/OUTSIDE_ACCESS.md` §8.

## 🆕 Cue de changement (ChangeAttention)
- Pendant une session, si tu quittes une zone puis y reviens et qu'un objet a disparu/changé → petite carte discrète « quelque chose a changé ici ». Anti-bruit volontaire : un seul cue par retour, cooldown, silence si la carte spatiale est incertaine. Jour 1 : rare (les zones se construisent).

## Checklist ajoutée (v3)
15. ☐ Premier lancement → `dl:` visible dans la StatusBar → download des ASR terminé → sous-titres offline OK **sans adb push**
16. ☐ Menu → « Traduire » → phrase en anglais → traduction française sous le sous-titre (puis teste PC coupé)
17. ☐ « traduis en direct » à la voix → activé ; « stop traduction » → coupé
18. ☐ Tailscale actif sur le tél, Wi-Fi coupé (4G) → `http://100.113.42.19:8710/health` répond → session dehors OK (`active_endpoint = tailscale` sur `/metrics`)
19. ☐ Quitte une pièce, déplace un objet, reviens → cue « quelque chose a changé »

---

# MISE À JOUR — APK v5 (E53 mode aide + E59 fenêtres à la main)

**Nouvel APK** : même fichier `mlomega-phoneonly.apk` (90,2 Mo) — réinstalle par-dessus (`adb install -r ...`). SHA-256 : `952543A0E0F6EE8A10A783E8BF26F86F8A1CA9BD42F62471AE5D23198B8CEDD5`. (APK lunettes v3 rebuildée aussi : `mlomega-xreal-g1.apk`, 191,5 Mo — mêmes nouveautés.)

## 🆕 « Viki, mode aide » (E53) — l'assistant de tâche pas-à-pas
- Dis « **viki… mode aide** » (ou « **aide-moi à faire des crêpes** » directement). Viki jette UN coup d'œil à la scène (elle devine le contexte), te demande la tâche si besoin, puis génère un **plan de micro-actions** (1 action = 1 geste).
- À l'écran : le **panneau de tâche** (fait ✓ / en cours / suivant en fantôme) + des **ancres sur les objets** (anneau qui SUIT l'objet même si tu le déplaces, **trajectoire animée du geste** : verser=arc, visser=cercle, essuyer=va-et-vient, appuyer=pulse), minuteur, quantités, « prends celui-là » si plusieurs candidats, flèche si l'objet est hors-champ.
- Avance à la voix : « **c'est fait** », « **étape suivante** », « **répète** », « **pause la tâche** », « **reprends la tâche** », « **termine la tâche** ». Si tu n'avances plus, Viki propose un indice toute seule.
- **Cloud opt-in** : avec ta clé OpenAI dans `.env` + « mode payant », le plan et les indices visuels passent par gpt-5.4-mini (coût affiché). Sans clé : LLM local, honnête.

## 🆕 Fenêtres à la main (E59)
- **Pince SUR un panneau** (fenêtre vidéo/replay en premier) → il colle à ta main → déplace-le où tu veux, relâche pour poser.
- **Pince sur un COIN** → redimensionne (la vidéo garde ses proportions).
- Boutons glass au coin : **✕** ferme, **–** réduit en pastille (re-pince la pastille pour restaurer). Position/taille mémorisées.
- Le pincement AILLEURS que sur un panneau = zoom, comme avant. Les éléments collés aux objets (tags personnes, ancres de tâche) ne se déplacent pas — ils suivent le monde.

## Checklist ajoutée (v5)
20. ☐ « viki… aide-moi à [tâche simple] » → coup d'œil scène → plan de micro-actions → panneau + ancre/geste sur l'objet
21. ☐ « c'est fait » → l'étape suivante s'affiche instantanément (fantôme pré-calculé)
22. ☐ Ne rien faire ~90 s pendant une tâche → un indice arrive tout seul
23. ☐ « rejoue 14h » → pince la fenêtre vidéo → déplace-la ; pince un coin → redimensionne ; « – » → pastille → re-pince → restaurée
24. ☐ Pince hors panneau → le zoom marche comme avant

## 👓 Lunettes XREAL (E49 — à valider sur matériel)

L'app lunettes est une **APK séparée** : `mlomega-xreal-g1.apk` (~191 Mo), à builder toi-même
(le SDK XREAL est propriétaire, non redistribué). Build : dépose `com.xreal.xr.tar.gz` dans
`apps\xr-mobile\Packages\xreal-sdk\`, puis le menu Unity **MLOmega > XREAL** (ou
`-executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildApk`).

Utilisation (flux prévu — à confirmer sur tes vraies lunettes) :
1. Installe l'APK lunettes sur le **téléphone** : `adb install -r apps\xr-mobile\build\android\mlomega-xreal-g1.apk`.
2. **Branche les lunettes XREAL en USB-C** au téléphone (les lunettes = écran + caméra Eye ;
   le calcul reste sur le téléphone). Le téléphone doit sortir la vidéo en USB-C (DisplayPort).
3. Lance l'app → **rendu stéréo** dans les lunettes, la **caméra Eye** devient la source vidéo.
   Tout le reste (PC, mémoire, commandes, gestes) est **identique au mode téléphone**.
4. Si l'Eye est absente/indisponible sur ton unité (One vs One Pro), l'app reste en **pose-only**
   (pas de capture vidéo lunettes) sans planter — c'est le plan B intégré.

⚠️ Non encore validé sur lunettes physiques : affichage stéréo réel, caméra Eye, pose 6DoF,
batterie sur session longue. Le code compile et l'APK est produite ; la validation terrain
se fera quand tu auras les lunettes.

## 📊 Après le close-day : LIS ta mémoire (dashboard)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
```
→ **http://localhost:8720** : hypothèses en attente/confirmées, modèle de vie, prédictions
et leurs vérifications, preuves visuelles, zones/routines, et le détail de tes close-days —
en lecture seule. C'est là que tu verras ce que ta première session a réellement produit.
