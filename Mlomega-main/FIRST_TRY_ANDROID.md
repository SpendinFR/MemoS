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
adb push models\device\. /sdcard/Android/data/com.mlomega.xr/files/models/
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
