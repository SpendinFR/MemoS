# À TESTER — toutes les fonctionnalités et tous les scénarios MLOmega

Ce document est la checklist de recette produit. Il couvre le chemin PhoneOnly,
le Galaxy S24 avec XREAL One Pro + Eye, le Live/UltraLive, BrainLive, Memory,
CloseDay Full/Lite, le mode PRO, le Prélude AR et les situations de panne.

Il ne remplace pas le guide de démarrage :

- S24 + XREAL : [`FIRST_TRY_XREAL_S24.md`](FIRST_TRY_XREAL_S24.md) ;
- S24 seul : [`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md).

## 0. Règle de validation

Une commande reconnue ou une ligne `accepted` ne suffit pas. Une fonction est
validée seulement si son effet réel est observable :

1. la demande est produite ;
2. elle traverse le transport ou le chemin local attendu ;
3. elle est interprétée par le bon consommateur ;
4. le résultat est affiché, exécuté ou écrit durablement ;
5. le receipt terminal est `completed`, `displayed`, `acted` ou un échec
   explicite ;
6. un rejeu réseau ne produit pas le même effet deux fois.

Légende recommandée :

- `[ ]` non testé ;
- `[x]` testé et réussi ;
- `MATÉRIEL` exige le S24/One Pro/Eye ;
- `LONGITUDINAL` exige plusieurs jours de vraies données ;
- `ATTENDU` est une abstention honnête, pas un échec ;
- `DIFFÉRÉ` n'est pas livré et ne doit pas être vendu comme fonctionnel.

Pour chaque anomalie, noter : heure locale, profil Local/PRO, Full/Lite,
commande exacte, résultat visible, état PC, capture d'écran, extrait de log et
session ID.

## 1. Matrice minimale à couvrir

| Chemin | Commande PC | Ce qu'il valide |
|---|---|---|
| XREAL Local Lite | `.\START_XREAL_S24.cmd` | chemin quotidien rapide, AR, services locaux |
| XREAL Local Full | `.\START_XREAL_S24.cmd -MemoryProfile full` | CloseDay historique complet |
| XREAL PRO Lite | `.\START_XREAL_S24.cmd -Pro -MemoryProfile lite` | Groq/Gemini/DeepSeek avec budget |
| XREAL PRO Full | `.\START_XREAL_S24.cmd -Pro -MemoryProfile full` | chaîne cloud historique |
| PhoneOnly Local Lite | `.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality -MemoryProfile lite` | rollback sans lunettes |
| PhoneOnly Local Full | `.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality -MemoryProfile full` | non-régression historique |

Le test physique initial peut se limiter à XREAL Local Lite, XREAL PRO Lite et
PhoneOnly Local Full. Les autres combinaisons sont des contrôles de
non-régression, pas six journées obligatoires.

## 2. Préparation et démarrage

### 2.1 Une fois sur le S24 et les lunettes

- [ ] One Pro et Eye ont reçu toutes les mises à jour via
  <https://www.xreal.com/ota/>.
- [ ] ControlGlasses 1.1.0 est installé.
- [ ] Tailscale est installé, connecté au même tailnet que le PC et autorisé en
  arrière-plan.
- [ ] Optimisation batterie désactivée pour MLOmega, ControlGlasses et
  Tailscale.
- [ ] MLOmega a caméra, micro, localisation précise, appareils à proximité,
  notifications et overlay.
- [ ] Débogage USB activé, `adb devices` affiche `device`.
- [ ] APK XREAL installée :
  `adb install -r apps\xr-mobile\build\android\mlomega-xreal.apk`.
- [ ] `adb shell pm path com.mlomega.xr.glasses` retourne un chemin.
- [ ] L'app est lancée depuis ControlGlasses, jamais depuis DeX.
- [ ] Eye est détectée ; sinon l'app indique honnêtement `pose-only`.

### 2.2 Démarrage PC

Depuis la racine :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
.\START_XREAL_S24.cmd
```

Attendre :

- [ ] Ollama répond ou est démarré automatiquement.
- [ ] Qdrant est prêt.
- [ ] service AR `127.0.0.1:8791` prêt.
- [ ] `pairing_ready=true`.
- [ ] `ai_ready=true`.
- [ ] <http://localhost:8710/ready> répond en HTTP 200.
- [ ] aucun check HF/Pyannote, CUDA/cuDNN, modèle, VLM, disque ou DB n'est rouge.

### 2.3 Connexion produit

- [ ] Ouvrir MLOmega sur le S24 seulement après le vert PC.
- [ ] Accepter la permission USB Eye.
- [ ] Observer `Paired`, puis `Connected`.
- [ ] Vérifier que les compteurs audio et vidéo progressent dans `/metrics`.
- [ ] Vérifier Eye active, orientation correcte et pose suivie.
- [ ] Débrancher/rebrancher une fois : reconnexion sans deuxième peer ni double
  audio.

## 3. Première identité du propriétaire

Dire :

> Viki, configure ma voix.

Puis parler naturellement pendant la capture demandée.

- [ ] Le badge indique que VIKI écoute.
- [ ] L'app demande suffisamment de parole au lieu de réussir à vide.
- [ ] La configuration termine avec succès.
- [ ] Les tours suivants du porteur sont attribués à `person_id=me`.
- [ ] Une autre personne n'est pas renommée `me`.
- [ ] Une voix incertaine reste inconnue.
- [ ] Une nouvelle session reconnaît à nouveau le propriétaire.

Alternatives reconnues : « configure ma voix », « c'est moi qui parle »,
« set up my voice ».

Les analyses personnelles profondes ne sont pas interprétables avant cette
étape.

## 4. Wake word, écoute, sous-titres et réponse vocale

- [ ] Dire « Viki » : badge `VIKI ● écoute`, puis carte `Je t'écoute…`.
- [ ] Le transcript final apparaît comme compris.
- [ ] Une commande sans wake word suit la politique configurée sans être
  arbitrairement routée.
- [ ] Une conversation ambiante reste mémorisable sans déclencher une commande
  gated.
- [ ] Sous-titres partiels se mettent à jour sans dupliquer le final.
- [ ] Le texte final conserve le bon locuteur et les timestamps de capture.
- [ ] Une réponse à voix haute produit réellement du son sur le S24.
- [ ] PC perdu à froid : wake word/ASR Reflex local indiquent honnêtement le
  niveau disponible.
- [ ] Écran éteint/arrière-plan : mesurer ce qui continue réellement ; noter
  toute suspension Android au lieu de la masquer.

## 5. Gestes et panneaux XREAL

Les gestes produit sont exactement :

- `OPEN_PALM_MENU` ;
- `SWIPE_HIDE` ;
- `PINCH_BEGIN` ;
- `PINCH_UPDATE` ;
- `PINCH_END`.

### 5.1 Menu

- [ ] Paume ouverte : ouvre le menu.
- [ ] « Viki, ouvre le menu » : ouvre le même menu.
- [ ] Regard/dwell une seconde : surligne la bonne ligne.
- [ ] Pinch sur une ligne : exécute cette ligne une seule fois.
- [ ] Swipe hide : cache toute l'UI.
- [ ] Ligne `Fermer` : ferme le menu sans arrêter la capture.
- [ ] `Page suivante`, `Page précédente`, `Retour` naviguent dans Réglages AR.

### 5.2 Manipulation

- [ ] Pinch sur le corps d'un panneau : grab puis déplacement.
- [ ] Le halo/ombre indique le drag.
- [ ] Relâcher : snap doux et position stable.
- [ ] Poignée resize : change la taille dans ses bornes.
- [ ] Pastille/minimiser : réduit puis restaure le panneau.
- [ ] Croix : ferme le panneau visé uniquement.
- [ ] La position d'un panneau persiste lorsqu'il est rouvert.
- [ ] Un pinch de zoom dans la vue ne déplace pas accidentellement un panneau.
- [ ] Deux panneaux proches ne reçoivent pas tous les deux le même pinch.

### 5.3 Lignes principales du menu

Tester chaque ligne :

- [ ] `FreeGuy` ;
- [ ] `Minimal` ;
- [ ] `Cacher` ;
- [ ] `Privé` ;
- [ ] `Maps` ;
- [ ] `YouTube` ;
- [ ] `Mémoire` ;
- [ ] `Ma voix` ;
- [ ] `Replay` ;
- [ ] `Sherlock` ;
- [ ] `Écran virtuel` ;
- [ ] `Traduire` ;
- [ ] `Mode payant` ;
- [ ] `Mode local` ;
- [ ] `Augmenté` ;
- [ ] `Réglages AR` ;
- [ ] `Fermer`.

Le menu et la voix doivent appeler le même handler et produire le même effet.

## 6. Commandes vocales de référence

### 6.1 Gate B — 13 commandes obligatoires

Les dire au cours d'une session réaliste :

| # | Commande | Résultat terminal attendu |
|---:|---|---|
| 1 | « qui est cette personne » | PersonTag/CardProfil ou inconnu honnête |
| 2 | « retiens demain je dois racheter des piles » | fait durable sourcé |
| 3 | « retiens rendez-vous avec Karim jeudi 15h chez le dentiste » | intention/rendez-vous durable |
| 4 | « c'est quoi ça » | carte objet liée au focus |
| 5 | « c'est quoi cet objet » | même chemin, aucun label inventé |
| 6 | « où sont mes clés » | visible ou dernière observation datée |
| 7 | « où est mon téléphone » | visible ou dernière observation datée |
| 8 | « lis le texte » | OCR réel du crop |
| 9 | « traduis le texte » | traduction affichée |
| 10 | « qu'est-ce qui a changé dans la pièce » | changements sourcés ou aucun changement |
| 11 | « aide-moi à faire un café » | TaskPanel naturel |
| 12 | « étape suivante » | avance le même plan |
| 13 | « interroge ma mémoire : qui est Karim ? » | recherche Memory et carte terminale |

- [ ] 13 commandes envoyées.
- [ ] 13 traces `accepted`.
- [ ] 13 états visibles `completed|failed|cancelled_session_end`.
- [ ] aucune commande perdue silencieusement.
- [ ] aucun effet exécuté deux fois après reconnexion.

### 6.2 Commandes supplémentaires

- [ ] « what is this ».
- [ ] « read this ».
- [ ] « trouve mes lunettes ».
- [ ] « où est le chien ».
- [ ] « zoom ».
- [ ] « traduis-le en anglais ».
- [ ] « traduis en direct » puis « arrête la traduction ».
- [ ] « cache tout » / « hide everything ».
- [ ] « pause privée » puis reprise explicite.
- [ ] « ouvre Maps vers Lyon ».
- [ ] « ouvre YouTube lofi ».
- [ ] « mode local ».
- [ ] « mode payant ».
- [ ] « rejoue 14h30 ».

## 7. Vision, objets et WorldBrain

### 7.1 « C'est quoi ça ? »

- [ ] Regarder un objet isolé et demander ce que c'est.
- [ ] La carte correspond à l'objet focalisé, pas au plus gros objet de l'image.
- [ ] Niveau de vérité visible : observé/reconnu/probable/inféré.
- [ ] Un détecteur vide entraîne une réponse inconnue ou un VLM ciblé, jamais
  une géométrie inventée.
- [ ] Deux objets proches : le bon track est inspecté.

### 7.2 « Où sont mes lunettes ? »

- [ ] Lunettes visibles : contour/UI sur leur position actuelle.
- [ ] Lunettes absentes : dernière observation, âge et lieu.
- [ ] XREAL avec carte spatiale qualifiée : flèche/distance.
- [ ] PhoneOnly sans 6DoF : carte seulement, aucune fausse flèche.
- [ ] Déplacer les lunettes : dernière position mise à jour.
- [ ] Deux paires : demander clarification ou distinguer les tracks.
- [ ] Souvenir ancien : âge visible, pas de présent fictif.

### 7.3 « Qu'est-ce qui a changé ici ? »

Préparer une première visite, déplacer ou retirer un objet, revenir.

- [ ] Première visite : aucune fausse comparaison.
- [ ] Apparition détectée.
- [ ] Disparition détectée.
- [ ] Déplacement détecté.
- [ ] Changement sous seuil : silence.
- [ ] Bbox invalide : rejet, pas d'événement.
- [ ] La carte cite avant/après et provenance.

### 7.4 Reconstruction

- [ ] Plusieurs objets restent distincts au tracking.
- [ ] Rotation Eye/capture-only ne tourne pas la carte.
- [ ] Perte/relocalisation ne fusionne pas deux lieux.
- [ ] PhoneOnly affiche son niveau 2D/lieu.
- [ ] XREAL n'affiche bearing/zones métriques qu'avec qualité suffisante.

### 7.5 Capture-only verticale

- [ ] Accrocher les lunettes verticalement sans les porter.
- [ ] Le bandeau affiche `capture-only`.
- [ ] Chaque frame conserve sa rotation réelle.
- [ ] VisionRT détecte dans le bon sens.
- [ ] OCR lit un texte droit après correction.
- [ ] L'absence d'affichage porté n'est pas prise pour un échec de capture.

## 8. OCR, texte du monde et traduction

### 8.1 OCR ponctuel

- [ ] Afficher un texte stable pendant cinq secondes.
- [ ] « lis le texte » lit le crop focalisé, pas tout l'écran.
- [ ] Nombres, prix et ponctuation sont conservés.
- [ ] Texte tourné : rotation correcte.
- [ ] Aucun texte : erreur visible, pas de succès vide.

### 8.2 Traduction ponctuelle

- [ ] « traduis-le en anglais » traduit le dernier OCR.
- [ ] Le message `translate_text` arrive au modèle Reflex Android.
- [ ] Le sous-titre est réellement rafraîchi.
- [ ] Langue/modèle absent : indisponibilité explicite.

### 8.3 Traduction continue

- [ ] « traduis en direct » active le toggle.
- [ ] Seuls les finals sont traduits.
- [ ] Deux locuteurs restent séparés.
- [ ] Un résultat tardif ne remplace pas un texte plus récent.
- [ ] « arrête la traduction » coupe le mode.

### 8.4 Monde sous-titré

Activer `Texte du monde`.

- [ ] Pancarte.
- [ ] Ticket/prix.
- [ ] Menu.
- [ ] Badge.
- [ ] Notice.
- [ ] Plaque de rue.
- [ ] Contrat.
- [ ] Médicament.
- [ ] Même track+texte ne génère pas des cartes en boucle.
- [ ] Le texte utile entre dans `world_text_observations_v19`.
- [ ] Sans GPS qualifié, le texte reste mémorisé sans fausse comparaison locale.
- [ ] Après au moins trois prix historiques au même lieu, une anomalie réelle
  génère une carte sourcée.

## 9. Mode aide naturel

- [ ] Dire « aide-moi » au milieu d'une action, sans plan préalable.
- [ ] Si la tâche est ambiguë, VIKI demande ce que l'utilisateur veut faire.
- [ ] « aide-moi à faire un café » crée un TaskPanel adapté.
- [ ] « étape suivante » avance.
- [ ] « répète » répète l'étape.
- [ ] pause/reprise conserve le même plan.
- [ ] fin ferme proprement le plan.
- [ ] Le panneau suit son ancre/objet quand possible.
- [ ] Une réponse LLM lente n'immobilise pas audio/vidéo.
- [ ] Dire « un », « deux » dans une conversation n'est pas interprété comme une
  logique métier codée.

## 10. Personnes, CardProfil et identité

- [ ] Personne connue : nom seulement au-dessus du seuil.
- [ ] CardProfil affiche relation, derniers sujets/promesses et provenance.
- [ ] Inconnu : ID provisoire, jamais un nom inventé.
- [ ] Nommer/promouvoir un inconnu : backfill des références canoniques.
- [ ] Même personne sur plusieurs sessions : même personne canonique.
- [ ] Deux inconnus simultanés : pas de fusion.
- [ ] « ce n'est pas Maxime » retire immédiatement le nom erroné.
- [ ] Face/voix contradictoires : nom masqué sous le seuil.
- [ ] Nouvelle coupe/vêtement : « changement possible » avec avant/après,
  jamais certitude à cause d'un angle ou d'une lumière.

## 11. BrainLive, HotContext et suggestions

### 11.1 Intervention pertinente

Créer auparavant un précédent réel, puis revenir auprès de la même personne et
du même sujet.

- [ ] HotContext charge owner, personne, lieu et sujet.
- [ ] Une suggestion pertinente apparaît en ContextCard avec texte et source.
- [ ] Situation voisine mais non pertinente : silence.
- [ ] Cooldown empêche la répétition.
- [ ] `dismissed` empêche un rappel immédiat.
- [ ] `acted` est conservé.
- [ ] Reconnexion réseau : même `ui_intent_id`, aucun doublon.

### 11.2 Exemple conflit

- [ ] Après plusieurs preuves, arriver sur un sujet ayant réellement produit une
  boucle connue.
- [ ] La carte formule un risque conditionnel, pas une certitude.
- [ ] Elle cite le précédent utile.
- [ ] Une seule occurrence ou un fait `watch_only` ne déclenche pas d'alerte
  profonde.

## 12. Mémoire et Brain2 — requêtes finales

Ces tests nécessitent des données réelles correspondantes. Une abstention est
correcte si la DB ne possède pas les preuves.

### 12.1 Timeline spatiale

> Où étais-je le 22 février 2022 ?

- [ ] Timeline matin/après-midi/soir.
- [ ] Intervalles contigus fusionnés.
- [ ] Trous marqués non observés.
- [ ] Aucun lieu extrapolé entre deux captures.

### 12.2 Dernière rencontre

> Qu'a dit Karim la dernière fois que je l'ai vu ?

- [ ] Identité canonique Karim.
- [ ] Dernière rencontre, pas simple meilleur score vectoriel.
- [ ] Date, résumé et courtes citations.
- [ ] Présence visuelle/vocale distinguée d'un échange vocal distant.

### 12.3 Historique d'un sujet

> Combien de fois Maxime m'a-t-il parlé de ce sujet ?

- [ ] Nombre de conversations/mentions distinctes calculé par code.
- [ ] Aucun comptage des chunks ou résumés dérivés.
- [ ] Évolution de position et contre-exemples.
- [ ] Dernier tour cité.

### 12.4 Analyse d'un conflit

> Pourquoi je me suis embrouillé avec Maxime hier ?

- [ ] Interaction correcte sélectionnée.
- [ ] État avant observé.
- [ ] Séquence factuelle et point de bascule.
- [ ] Après-coup.
- [ ] Hypothèses séparées des faits.
- [ ] Aucune intention psychologique inventée.

### 12.5 Dernier attribut/prix

> Combien coûtait la baguette la dernière fois ?

- [ ] Produit, commerce/lieu, valeur, unité et date.
- [ ] Modalité `ocr|heard|vlm`.
- [ ] Preuve image ou tour.
- [ ] Clarification si produit et prix n'étaient pas liés dans la même preuve.

### 12.6 Prédictions

> Prédit-moi ce qui va m'arriver dans les prochains jours et semaines.

- [ ] Plusieurs horizons.
- [ ] Précédents et preuves.
- [ ] Confiance et conditions d'invalidation.
- [ ] `watch_only` jamais présenté comme certain.
- [ ] Une seule journée provoque une abstention sur les « boucles » profondes.

### 12.7 Expression actuelle

> Quelle est mon expression favorite du moment ?

- [ ] Fenêtre temporelle explicite.
- [ ] Paroles de `me` uniquement.
- [ ] Déduplication des artefacts dérivés.
- [ ] Comparaison à la période précédente.
- [ ] Exemples cités.

### 12.8 Question floue

> C'était quoi le truc dont je parlais il y a deux semaines avec Maxime ?

- [ ] Personne et période sont des filtres durs.
- [ ] Au plus trois épisodes candidats.
- [ ] Indice distinctif par candidat.
- [ ] Clarification si deux candidats restent plausibles.

### 12.9 Recul longitudinal

> Comment ai-je réussi à faire ça ?

- [ ] But → choix → actions → résultats.
- [ ] Plusieurs épisodes sourcés.
- [ ] Contre-exemples.
- [ ] Observation et interprétation séparées.
- [ ] Refus d'inventer une profondeur sur une minute.

## 13. Replay

- [ ] « rejoue 14h30 » sélectionne 14:30–14:45 en heure locale.
- [ ] Timeline avec texte non vide.
- [ ] Images/MP4 se chargent par route authentifiée.
- [ ] `VirtualScreen` affiche le média.
- [ ] Seek/play/pause fonctionnent.
- [ ] Replay s'arrête et libère la surface.
- [ ] « rejoue la scène avec Karim où j'ai dit attention derrière » trouve un
  candidat sémantique, affiche date/intervalle, puis lance le même Replay.
- [ ] Aucun timestamp n'est inventé si plusieurs candidats restent possibles.

## 14. Privacy, hors-ligne et applications

### 14.1 Pause privée

- [ ] « pause privée » ou ligne `Privé`.
- [ ] Caméra, micro, ASR et transport réellement libérés.
- [ ] Aucun nouvel événement Memory pendant la pause.
- [ ] Reprise uniquement après action explicite.
- [ ] Reprise sans double sink PCM ni double peer.

### 14.2 PC inaccessible

- [ ] Menu, zoom, wake word/ASR et traduction locale disponibles selon la
  capability affichée.
- [ ] Mémoire/BrainLive marqués indisponibles.
- [ ] Aucune réponse fabriquée.
- [ ] Retour PC : reconnexion et reprise sans redémarrage complet si possible.

### 14.3 Apps

- [ ] « ouvre Maps vers Lyon » ouvre Maps avec destination.
- [ ] « ouvre YouTube lofi » ouvre YouTube/recherche.
- [ ] App package autorisée : ouverture.
- [ ] Package inconnu : erreur visible.
- [ ] `Écran virtuel` n'est pas vendu comme TV/cast.
- [ ] TV/cast/remote reste `DIFFÉRÉ`.

## 15. Réglages AR et commandes VIKI

Ouvrir `Menu → Réglages AR`. Un point vert signifie actif. Un switch armé mais
sans provider reste `SYNCHRO`/`ATTENTE` ; ce n'est pas une réussite.

Commandes génériques :

- « Viki, active … »
- « Viki, désactive … »

Après chaque commande :

- [ ] badge `VIKI ● écoute` ;
- [ ] transcript final ;
- [ ] carte `activé`, `désactivé` ou `indisponible` ;
- [ ] le menu reflète le même état ;
- [ ] activer une fonction enfant active aussi `AR globale` ;
- [ ] désactiver FreeGuy ne désactive pas les autres fonctions choisies.

## 16. Scénarios des 24 fonctions AR publiques

### 16.1 AR globale

Phrase : « Viki, active la réalité augmentée ».

- [ ] Active le master et le service PC.
- [ ] OFF retire immédiatement toutes les projections augmentées.
- [ ] Memory/Live continuent indépendamment.

### 16.2 Menus objets

Phrase : « Viki, active les menus objets ».

- [ ] Regarder un objet stable ouvre une carte liée au bon track.
- [ ] Nom, état, mémoire connue et actions possibles sont sourcés.
- [ ] Pinch inspecte le vrai `track_id`.
- [ ] Objet Home Assistant configuré : état lu, action proposée, deuxième pinch
  de confirmation, état terminal relu.
- [ ] Objet non configuré : aucune action domotique inventée.

### 16.3 Reconnaissance d'actions

Phrase : « Viki, active la reconnaissance d'actions ».

Tester : s'asseoir, se lever, prendre, poser, entrer, sortir, préparer une
boisson.

- [ ] Une image isolée n'écrit rien.
- [ ] Action, sujet, objet, intervalle, confiance et frames sont conservés.
- [ ] `prendre` reste probable sans corroboration.
- [ ] `prendre` n'est jamais transformé en `manger`.

### 16.4 Sons sémantiques

Phrase : « Viki, active les sons sémantiques ».

- [ ] Son classé avec confiance et timestamp.
- [ ] UI discrète, pas une carte par chunk.
- [ ] Son ambigu : inconnu/probable.
- [ ] Le S24 garde une latence UltraLive et ne bloque pas l'audio ASR.
- [ ] Localisation directionnelle absente sans vrai réseau micro.

### 16.5 Connaissances contextuelles

Phrase : « Viki, active les connaissances contextuelles » ou
« active le mode contextuel ».

- [ ] Demande/focus explicite interroge le Kiwix PC.
- [ ] Carte courte avec source.
- [ ] Cooldown automatique de 90 secondes.
- [ ] Plusieurs mots de conversation n'ouvrent pas des cartes en rafale.
- [ ] Kiwix indisponible : erreur visible.

### 16.6 Mesure AR

Phrase : « Viki, active la mesure AR ».

- [ ] Choisir deux points réels.
- [ ] Hit Depth valide requis.
- [ ] Distance/mesure et incertitude affichées.
- [ ] Aucun hit : aucune fausse mesure.
- [ ] Mesurer un objet connu avec un mètre réel et noter l'erreur.

### 16.7 Navigation monde

Phrase : « Viki, active la navigation monde », puis « ouvre Maps vers … ».

- [ ] GPS et boussole/accuracy visibles.
- [ ] Route OSRM récupérée quand disponible.
- [ ] Grandes flèches 3D suivent la polyline.
- [ ] Embranchements et distance sont lisibles.
- [ ] Portail de destination affiché.
- [ ] Écart de plus de 25 m : recalcul.
- [ ] Perte réseau : `CAP DIRECT`, jamais faux turn-by-turn.
- [ ] Demi-tour et sortie de route.
- [ ] Entrée dans un bâtiment : transition vers navigation intérieure si connue.

### 16.8 Labels du monde

Phrase : « Viki, active les labels du monde ».

- [ ] Objet/bâtiment/POI porte un label stable.
- [ ] Classe visuelle distinguée d'un POI cartographique.
- [ ] Sans pose spatiale valide : pas de label prétendument ancré.
- [ ] Densité/LOD empêchent l'empilement illisible.

### 16.9 Ancres persistantes

Phrase : « Viki, active les ancres persistantes ».

- [ ] Pose tracking requise avant sauvegarde.
- [ ] Redémarrer l'app et revenir au lieu.
- [ ] Ancre réellement relocalisée : contenu réapparaît.
- [ ] Ancre non résolue : rien à l'ancienne position.
- [ ] Changement de `world_map_id` ne mélange pas deux lieux.

### 16.10 Occlusion Depth

Phrase : « Viki, active l'occlusion ».

- [ ] Une UI placée derrière un objet réel est masquée.
- [ ] Elle réapparaît en déplaçant la tête.
- [ ] Absence de Depth : capability indisponible, pas de masque fictif.
- [ ] Aucun clignotement excessif sur les bords.

### 16.11 Style FreeGuy

Phrase : « Viki, active le style Free Guy ».

- [ ] Style néon/halo/fresnel sur les surfaces monde.
- [ ] La frame Eye originale envoyée à Vision/Memory reste inchangée.
- [ ] OFF restaure immédiatement le rendu normal.

### 16.12 Futurs de foule

Phrase : « Viki, active les mouvements de foule ».

- [ ] Plusieurs personnes mobiles produisent des trajectoires fantômes.
- [ ] Plusieurs futurs possibles restent probabilistes.
- [ ] Tracks perdus expirent au lieu de continuer dans le mur.
- [ ] Une personne immobile ne génère pas de trajectoire dramatique.

### 16.13 Clavier spatial

Phrase : « Viki, active le clavier spatial ».

- [ ] Plan/surface Depth valide.
- [ ] Grille correctement ancrée sur la surface.
- [ ] Doigt/pinch sélectionne une touche.
- [ ] Debounce empêche les frappes doubles.
- [ ] Aucun plan : indisponible.

### 16.14 Vision mouvement

Phrase : « Viki, active la vision événementielle ».

- [ ] Seuls les changements/mouvements ressortent visuellement.
- [ ] Caméra immobile : bruit borné.
- [ ] Mouvement rapide : visible.
- [ ] Ce filtre visuel ne modifie pas les frames Memory.
- [ ] « désactive la vision événementielle » retire l'effet.

### 16.15 Lancer ludique

Phrase : « Viki, active le lancer ludique ».

- [ ] Objet léger/papier en main détecté.
- [ ] L'utilisateur choisit/ping la cible.
- [ ] Main, objet, gravité et cible alimentent la trajectoire.
- [ ] Pointillés restent un aperçu ludique, pas un calcul de sécurité.
- [ ] Perte main/Depth : aperçu retiré.
- [ ] Ne jamais tester avec arme, projectile dangereux ou personne.

### 16.16 Carte radio

Phrase : « Viki, active la carte radio ».

- [ ] Permissions appareils à proximité accordées.
- [ ] Wi-Fi/Bluetooth deviennent une visualisation abstraite datée.
- [ ] Aucun appareil n'est prétendu localisé en 3D sans mesure adéquate.
- [ ] Identifiants radio salés/hachés.
- [ ] Désactivation arrête le scan et retire les overlays.

### 16.17 Profils studio

Phrase : « Viki, active les profils studio ».

- [ ] Release configurée et code demandé au lancement.
- [ ] Mauvais code bloque la capability.
- [ ] Personne candidate : carte `candidat à confirmer`.
- [ ] Recherche Web limitée à une tentative par track.
- [ ] Aucune identité n'est automatiquement promue.
- [ ] Aucun profil hors release/consentement.

### 16.18 Aura pouls expérimentale

Phrase : « Viki, active l'aura pouls ».

- [ ] Sujet immobile, éclairage stable et visage assez grand.
- [ ] Avec `-StudioReleaseId` validé : fonctionne sans fiche individuelle et sans
  nommer le visage; la ROI anonyme expire avec le run.
- [ ] Période de calibration visible.
- [ ] Aura marquée expérimentale avec qualité.
- [ ] Mouvement/lumière variable : abstention.
- [ ] Aucun « stress », émotion ou diagnostic déduit du pouls.

### 16.19 Effets monde automatiques

Phrase : « Viki, active les effets monde automatiques ».

- [ ] Trois observations et ray-hit Depth avant effet.
- [ ] Vitrine → écran transparent.
- [ ] Voiture → traînée holographique arrière.
- [ ] Panneau/enseigne → néon/hologramme.
- [ ] Bâtiment → balise.
- [ ] Objet proche → annotation.
- [ ] Maximum douze surfaces FreeGuy.
- [ ] IDs stables, TTL court, pooling.
- [ ] OFF retire les effets.
- [ ] Effets éphémères jamais écrits en Memory.

### 16.20 Texte du monde

Voir section 8.4.

### 16.21 Navigation intérieure

Phrase : « Viki, active la navigation intérieure ».

- [ ] Marcher dans un lieu : graphe construit depuis la pose XREAL.
- [ ] Dire « nomme cet endroit comme cuisine ».
- [ ] Redémarrer puis revenir : radio/magnétique reconnaissent seulement le
  départ, sans inventer des coordonnées.
- [ ] « ouvre Maps vers cuisine » réutilise le chemin appris.
- [ ] Perte de localisation et précision affichées.
- [ ] Ce mode n'est jamais appelé GPS indoor.

### 16.22 Planétarium

Phrase : « Viki, active le planétarium ».

- [ ] GPS ≤ 50 m, cap ≤ 30°, nord calibré, pose tracking.
- [ ] Étoiles/planètes/constellations suivent l'orientation.
- [ ] Date/heure changée : positions cohérentes.
- [ ] Gate absent : abstention visible.
- [ ] Aucune écriture Memory automatique.

### 16.23 Météo contextuelle

Phrase : « Viki, active la météo contextuelle ».

- [ ] Widget discret correspondant au lieu.
- [ ] Aucun appel plus fréquent que dix minutes.
- [ ] Cache durable quinze minutes.
- [ ] Hors réseau : dernière valeur datée `stale`.
- [ ] Aucune valeur ancienne présentée comme actuelle.

### 16.24 Aide contexte social/juridique

Phrase : « active le mode juridique ».

- [ ] Le pays est France/FR.
- [ ] Au plus huit tours récents deviennent une requête globale.
- [ ] Article principal et au plus deux alternatives.
- [ ] Source Légifrance, statut et date d'effet.
- [ ] Pertinence faible : abstention.
- [ ] Cooldown six secondes.
- [ ] Expiration après quinze minutes.
- [ ] « arrête le mode juridique » coupe l'écoute.
- [ ] Rien n'est écrit dans la mémoire personnelle.
- [ ] La carte dit assistance, jamais conseil juridique certain.

## 17. FreeGuy combiné et charge

Activer :

1. FreeGuy ;
2. navigation monde ;
3. labels ;
4. effets automatiques ;
5. futurs de foule.

Sur une marche extérieure de vingt minutes :

- [ ] UI réellement stéréo et monde, pas écran 2D.
- [ ] Flèches et portail restent au bon endroit.
- [ ] 6 à 12 surfaces automatiques.
- [ ] Labels, enseignes et effets ne se chevauchent pas excessivement.
- [ ] Occlusion fonctionne.
- [ ] FPS reste acceptable.
- [ ] Température S24 notée à 0, 10 et 20 min.
- [ ] Batterie consommée notée.
- [ ] Aucun drop audio pendant le rendu.
- [ ] Aucun VLM live n'affame Whisper/YOLOX.
- [ ] Master OFF retire tout instantanément.

## 18. Sherlock

Dire « active le mode Sherlock » ou choisir `Sherlock`.

- [ ] Aucune table/capture avant activation explicite.
- [ ] Capture Eye PNG lossless avec parent, timestamp, dimensions et SHA.
- [ ] Crop choisi garde bbox et source.
- [ ] Timeline limitée et capture au plus toutes les cinq secondes.
- [ ] Changements, OCR, actions T1 et Replay rejoignent la timeline.
- [ ] Rehaussement affiche original et candidat côte à côte.
- [ ] Détail créé uniquement par rehaussement n'est pas une observation.
- [ ] Comparaison pixel/SSIM/ORB retourne similarité, pas identité/culpabilité.
- [ ] « qui a mangé le chocolat ? » peut réunir disparition, prise et images,
  mais s'abstient sans preuve de l'action `manger`.
- [ ] Média s'affiche dans VirtualScreen par route authentifiée.
- [ ] Session expire après vingt minutes.
- [ ] « supprime l'enquête » retire lignes et médias.

## 19. CloseDay Lite

Démarrer avec :

```powershell
.\START_XREAL_S24.cmd -MemoryProfile lite
```

- [ ] Tous les finals du buffer sont archivés lossless.
- [ ] Conversations séparées sur vraie frontière, silence > 4 min, plafond
  20 min ou 48 000 caractères.
- [ ] Une extraction owner-centrée par épisode borné.
- [ ] Actions T1 utiles incluses.
- [ ] OCR/prix/adresses/notices utiles inclus.
- [ ] États/lieux, changements, dernière position, Deep Vision et Sherlock utiles
  inclus.
- [ ] Météo, ciel, radio, navigation et effets FreeGuy exclus.
- [ ] Une observation unique de préférence/routine/émotion reste `watch`.
- [ ] Episodes, preuves, relations, faits Lite et Life Model écrits.
- [ ] Export live et index de pertinence disponibles au lendemain.
- [ ] Reprise avec même digest ne repaye pas l'extraction.
- [ ] `memory_lite_close_day_runs_v19.status=completed`.

## 20. CloseDay Full

Démarrer avec :

```powershell
.\START_XREAL_S24.cmd -MemoryProfile full
```

- [ ] Deep Audio terminé.
- [ ] Deep Vision : `selected = readable = analyzed`.
- [ ] Fenêtres Brain2 lossless ou quarantaine explicite.
- [ ] Capacités obligatoires non bypassées.
- [ ] Personnes/relations V14.
- [ ] coordination/réconciliation.
- [ ] V17 longitudinal/outcomes.
- [ ] Life Model/Self Schema.
- [ ] prédictions et live-ready.
- [ ] manifeste relu depuis les sorties réelles.
- [ ] maintenance/rétention terminales.
- [ ] `close_day=completed`.

## 21. Mode PRO et budget

- [ ] Clés DeepSeek, Groq et Gemini seulement dans `.env`.
- [ ] Groq traite l'audio durable ; aucun segment perdu.
- [ ] Gemini traite les keyframes réellement sélectionnées.
- [ ] DeepSeek conserve les contrats JSON.
- [ ] Cache hit/miss et coûts écrits dans `cloud_cost_ledger_v19`.
- [ ] Le plafond `1.50 EUR` bloque avant dépassement.
- [ ] `CloudOnBudget=stop` n'effectue aucun fallback payant implicite.
- [ ] Une reprise réutilise checkpoints Groq/Gemini/DeepSeek.
- [ ] Local reste inchangé après un run PRO.

## 22. Fin de session et recovery

Toujours utiliser :

> Terminer la session et lancer CloseDay

- [ ] `/session/end` répond rapidement.
- [ ] transport et médias sont arrêtés.
- [ ] job recovery durable créé.
- [ ] commandes encore en vol deviennent terminales ou annulées honnêtement.
- [ ] fine-intel se vide en arrière-plan.
- [ ] CloseDay attend les drains requis.
- [ ] `end_session=completed`.
- [ ] `close_day=completed`.

Ne jamais swipe l'app pour une fin normale.

### 22.1 Pannes à provoquer une fois

- [ ] Couper le Wi-Fi 30 secondes, garder Tailscale : continuité ou reconnexion.
- [ ] Couper LAN et Tailscale, puis restaurer : pas de double peer.
- [ ] Perdre un receipt : redelivery même ID, effet unique.
- [ ] Appuyer deux fois sur Terminer : une seule finalisation.
- [ ] Fermer le PC après `/session/end`, puis relancer RUN : recovery avant
  CloseDay.
- [ ] Ollama arrêté au démarrage : lanceur le réveille ou bloque avec correction.
- [ ] Qdrant arrêté : RUN le démarre ou bloque proprement.
- [ ] VLM indisponible : manifeste refuse un faux `complete`.
- [ ] Disque presque plein : préflight bloque avant capture.
- [ ] Proxy loopback mort : retiré/bloqué avant HF.
- [ ] Modèle cloud en 429 : retry/backoff borné, budget inchangé.

Ne provoque pas un disque réellement plein ni une corruption de la DB de
production. Utiliser une DB de test pour les injections destructives.

## 23. Dashboard et audit owner

Après CloseDay :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
```

- [ ] Dashboard annonce le chemin exact de la DB.
- [ ] Son SHA ne change pas pendant la lecture.
- [ ] Cards humaines, pas seulement IDs techniques.
- [ ] Timeline audio/vision lisible.
- [ ] Images et clips ouvrables.
- [ ] Faits, hypothèses et prédictions visuellement distincts.
- [ ] Owner, personnes, relations, lieux et sources lisibles.
- [ ] Aucun bbox invalide ou résumé vide présenté comme information.

L'audit owner est manuel, après un CloseDay terminé, idéalement un jour OFF.
Exécuter d'abord `--plan-only`, lire coût et résumé, puis seulement
`--execute --apply-safe`. Les commandes complètes sont dans
[`FIRST_TRY_XREAL_S24.md`](FIRST_TRY_XREAL_S24.md).

- [ ] Backup créé.
- [ ] `quick_check=ok`.
- [ ] Aucun SQL libre fourni au LLM.
- [ ] Doublons sûrs traités.
- [ ] Contradictions et ambiguïtés laissées sourcées si non décidables.
- [ ] Rapport visible dans le Dashboard.

## 24. Les 16 scénarios historiques du simulateur

Commande non matérielle :

```powershell
.\.venv\Scripts\python.exe scripts\run_scenarios_v19.py
```

Scénarios :

- [ ] `life_memory` — keyframes/événements entrent dans Memory ;
- [ ] `person_profile` — personne promue et delivery ;
- [ ] `conversational` — transcript vers intervention ;
- [ ] `translation` — compatibilité traduction PC uniquement ;
- [ ] `what_is_this` — carte du bon track ;
- [ ] `zoom_ocr` — crop OCR réel ;
- [ ] `assist_task` — étape TaskCard ;
- [ ] `find_object` — dernière observation ;
- [ ] `navigation` — aucune flèche sans qualité ;
- [ ] `worldbrain_changes` — moved/disappeared persistés ;
- [ ] `sherlock` — trace observable, jamais certitude ;
- [ ] `replay` — médias retrouvables ;
- [ ] `free_guy` — décoratif basse priorité ;
- [ ] `floating_screen` — écran virtuel admis ;
- [ ] `ultra_live_reflex` — cue proximité haute priorité ;
- [ ] `capture_only` — rotation et OCR.

Pour les scénarios transport clés :

```powershell
.\.venv\Scripts\python.exe scripts\run_scenarios_v19.py --webrtc
```

Ce simulateur ne remplace pas la recette physique.

## 25. Scène vidéo physique de cinq minutes

Filmer :

1. 0:00–1:30 : conversation avec une personne visible, un fait et une promesse ;
2. 1:30–2:30 : table avec lunettes/téléphone/clés ; poser puis déplacer les clés ;
3. 2:30–3:00 : texte stable cinq secondes ;
4. 3:00–4:00 : marcher dans plusieurs pièces puis revenir après changement ;
5. 4:00–5:00 : préparer un café et demander de l'aide.

Cette seule vidéo doit exercer :

- [ ] diarisation/owner ;
- [ ] mémoire et relations ;
- [ ] détection/last-seen ;
- [ ] OCR/traduction ;
- [ ] ChangeAttention ;
- [ ] aide ;
- [ ] clips E55 ;
- [ ] Deep Audio ;
- [ ] Deep Vision ;
- [ ] CloseDay Lite ou Full ;
- [ ] Dashboard.

## 26. Cas d'ambiguïté et d'épistémologie

- [ ] Deux personnes de même apparence.
- [ ] Deux objets de même classe.
- [ ] « pas celles-là ».
- [ ] correction de nom.
- [ ] correction de lieu.
- [ ] objet caché puis réapparu.
- [ ] souvenir ancien.
- [ ] non observé.
- [ ] probable.
- [ ] contradictoire.

Chaque état doit avoir un rendu différent. Une confiance faible ne produit ni
nom certain, ni flèche, ni causalité, ni action domotique.

## 27. Fonctions volontairement différées

Ne pas attendre ces capacités dans l'APK actuelle :

- `enhanced_zoom` Real-ESRGAN temps réel : le crop/pinch de base fonctionne,
  mais le super-zoom public est masqué ;
- filtre temporel transformant une rue en autre époque ;
- reconstruction 3D historique/gaussian splatting ;
- face swap, beauté et remplacement de vêtements ;
- RF-Pose à travers les murs ;
- vraie caméra acoustique sans réseau de microphones ;
- TV/cast/remote réel ;
- ARCore Geospatial/VPS combiné au provider XREAL ;
- identification automatique non consentie ou « base policière » ;
- diagnostic médical, émotion/stress certains.

Une entrée `ATTENTE` correspondant à cette liste est correcte. Il ne faut pas la
contourner par un faux résultat.

## 27 bis. APK World Atelier et FreeGuy ancré

Suivre `FIRST_TRY_XREAL_WORLD_ATELIER.md`, puis vérifier :

- [ ] l'Atelier démarre sans pairing PC, micro, capture Eye WebRTC ni Memory ;
- [ ] le pupitre et les presets sont de vrais éléments world-space/stéréo, pas une
  fenêtre Android 2D ;
- [ ] hit Depth absent : `ANCRER` refuse, aucune pose n'est inventée ;
- [ ] sol et mur : position, verticale, rotation et resize sont conservés ;
- [ ] un logo PNG/JPEG valide apparaît dans son volume 3D, un asset trop gros est
  refusé ;
- [ ] l'export contient un mapping natif pour chaque GUID et refuse tout mapping
  absent ;
- [ ] l'APK produit importe le paquet sans accès à la DB de l'Atelier ;
- [ ] après redémarrage et retour au lieu, seules les ancres réellement
  `Tracking` réapparaissent ;
- [ ] `FreeGuy ancré` fonctionne seul ;
- [ ] `FreeGuy dynamique` fonctionne seul ;
- [ ] les deux modes se composent sans doublons, head-lock ni dépassement
  thermique ;
- [ ] `Importer monde` et `VIKI, importe mon monde ancré` ouvrent le même picker ;
- [ ] Local/PRO, Memory, Eye et CloseDay gardent leurs résultats historiques.

## 28. Verdict final matériel

Le gate est vert seulement si :

- [ ] installation et démarrage en une commande ;
- [ ] Eye, 6DoF, mains, stéréo et orientation réels ;
- [ ] 13/13 commandes terminales ;
- [ ] gestes/menu/panneaux ;
- [ ] OCR/traduction/aide ;
- [ ] objet/last-seen/ChangeAttention ;
- [ ] Memory et Replay ;
- [ ] HotContext/suggestion ;
- [ ] fonctions AR choisies avec leurs gates honnêtes ;
- [ ] navigation/ancres/occlusion ;
- [ ] vingt minutes de FreeGuy sans chauffe ou latence inacceptable ;
- [ ] fin/recovery ;
- [ ] CloseDay du profil choisi ;
- [ ] Dashboard lisible ;
- [ ] aucune régression PhoneOnly ;
- [ ] aucun faux succès.

### Fiche de résultat

```text
Date/heure :
Téléphone / Android / One UI :
Firmware One Pro / Eye :
APK + SHA-256 :
Mode : XREAL|PhoneOnly
Live : Local|PRO
Memory : Lite|Full
Session ID :
Fonction/scénario :
Commande/geste exact :
Résultat attendu :
Résultat observé :
Receipt terminal :
Capture/log :
DB/preuve :
Verdict : PASS|FAIL|ATTENDU|DIFFÉRÉ
```
