# Première utilisation — Galaxy S24 + XREAL One Pro + Eye

Ce guide est le chemin opérateur courant pour utiliser MLOmega avec :

- un PC Windows qui exécute le Live, BrainLive et CloseDay ;
- un Samsung Galaxy S24 comme hôte Android ;
- des XREAL One Pro avec le module XREAL Eye ;
- l'APK `apps\xr-mobile\build\android\mlomega-xreal.apk`.

Le S24 exécute Unity/XREAL, l'interface, la capture Eye, WebRTC et les réflexes
locaux. Les traitements lourds restent sur le PC. Le profil livré essaie le PC
dans cet ordre :

1. LAN : `192.168.1.199:8710` ;
2. Tailscale : `100.113.42.19:8710`.

L'APK courante est `com.mlomega.xr.glasses`, SHA-256
`24CB3942B389EEC5B9E37F06839A43827A1B6D6B18FAE014CA2CA585448DECB3`
(222 260 749 octets, build Unity final du 26 juillet 2026).

Après l'installation, la checklist exhaustive de validation est
[`A_TESTER_ALL_FEATURES_SCENARIOS.md`](A_TESTER_ALL_FEATURES_SCENARIOS.md).
Elle décrit chaque commande, geste, mode AR, scénario Memory/UltraLive et la
preuve attendue. Le présent fichier reste le guide de démarrage quotidien.

## 1. Préparation unique du S24 et des lunettes

### 1.1 Firmware One Pro + Eye — obligatoire

Le 6DoF du SDK XREAL 3.1 exige le dernier firmware. Avant d'utiliser le S24 :

1. monte l'XREAL Eye sur les One Pro ;
2. sur le PC Windows, ouvre **Chrome 89 ou plus récent** ;
3. ouvre <https://www.xreal.com/ota/> ;
4. branche les lunettes au PC avec le câble XREAL d'origine ;
5. autorise l'accès USB dans Chrome, puis applique toutes les mises à jour
   proposées pour les lunettes/Eye ;
6. attends la confirmation finale avant de débrancher.

Ne commence pas le gate MLOmega si le site OTA ne reconnaît pas les lunettes ou
si une mise à jour reste en attente.

### 1.2 Applications et permissions du S24

1. Depuis la page officielle <https://developer.xreal.com/download/>, installe
   **ControlGlasses 1.1.0** sur le S24. MyGlasses est l'application du Beam Pro
   et ne remplace pas ControlGlasses sur téléphone.
2. Installe Tailscale sur le S24, connecte-le au même tailnet que le PC et
   laisse le VPN actif.
3. Dans Paramètres > Applications, retire l'optimisation batterie pour
   MLOmega, ControlGlasses et Tailscale. Pour MLOmega, autorise caméra, micro,
   localisation précise, appareils à proximité, notifications et affichage
   par-dessus les autres apps. Laisse Tailscale utiliser le VPN en arrière-plan.
4. Active les options développeur et le débogage USB sur le S24.
5. Pour le premier gate, note la version Android/One UI et évite une mise à jour
   majeure entre l'installation et le test : XREAL certifie le S24 avec le SDK
   3.0, tandis que le SDK 3.1 utilisé par MLOmega est officiellement testé sur
   Beam Pro et S25. Le S24 n'est pas déclaré incompatible, mais Eye/6DoF doit
   être prouvé physiquement.

Sur le PC :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
adb devices
adb install -r apps\xr-mobile\build\android\mlomega-xreal.apk
adb shell pm path com.mlomega.xr.glasses
```

`adb devices` doit montrer le S24 avec l'état `device`. Accepte l'empreinte RSA
sur le S24 si Android la demande.

Branchement quotidien :

1. ouvre ControlGlasses sur le S24 ;
2. branche les One Pro au S24 avec le câble XREAL d'origine et accepte la
   permission USB ;
3. lance MLOmega depuis ControlGlasses, pas depuis une ancienne icône APK ni
   depuis Samsung DeX ;
4. vérifie que l'Eye est bien détectée. Sans Eye, l'app reste volontairement en
   mode pose-only et aucune vidéo lunettes n'est envoyée.

Le S24 n'a qu'un port USB-C. Pour une session longue, utilise un XREAL Hub ou un
adaptateur alimenté qui conserve explicitement le DisplayPort USB-C. Teste
d'abord dix minutes : un hub de charge ordinaire peut alimenter le téléphone
mais couper la vidéo ou l'accès Eye.

Le mode capture-only vertical est prévu : la rotation des lunettes est portée
avec chaque frame et corrigée avant Vision/OCR. Si les lunettes sont accrochées
verticalement, le bandeau doit indiquer `capture-only`.

### 1.3 Base fraîche — uniquement avant la première production

Si la base courante ne contient que les anciens essais et doit être supprimée,
arrête d'abord RUN, le dashboard et tout processus MLOmega. Depuis la racine :

```powershell
$db = ".mlomega_audio_elite\memory.db"
if (Test-Path $db) {
  Copy-Item $db "$db.before-first-production.bak"
}
Remove-Item -LiteralPath $db -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$db-wal","$db-shm" -Force -ErrorAction SilentlyContinue
Test-Path $db
```

Le résultat doit être `False`; le prochain RUN recrée la base.
Ne supprime jamais la DB après le début d'une vraie capture. En cas de
CloseDay interrompu, conserve DB et médias puis relance RUN : la recovery
reprend le travail durable.

## 2. Lancer le PC — une commande, mode Local Lite recommandé

Ferme toute ancienne instance de MLOmega, puis ouvre PowerShell :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
.\START_XREAL_S24.cmd
```

Cette commande est le chemin quotidien recommandé. Elle :

1. réveille Ollama si son service local ne répond pas ;
2. sélectionne `MemoryProfile=lite` ;
3. appelle le lanceur produit avec `-LivePhone -AugmentedReality` ;
4. démarre/vérifie Qdrant, Kiwix configuré, le service AR et SessionHub ;
5. exécute le préflight profond avant d'autoriser l'appairage.

Elle ne lance ni l'app Android ni CloseDay à ta place : ouvre MLOmega seulement
après le vert PC, puis utilise le bouton de fin dans l'app.

Tu peux aussi double-cliquer `START_XREAL_S24.cmd` dans l'Explorateur : sans
option, il lance exactement **Local + Lite + AR**. La fenêtre reste ouverte si
le préflight échoue afin d'afficher la correction.

Pour garder le CloseDay historique complet :

```powershell
.\START_XREAL_S24.cmd -MemoryProfile full
```

Pour voir la commande résolue sans rien démarrer :

```powershell
.\START_XREAL_S24.cmd -DryRun
```

RUN effectue le préflight profond : DB, modèles, Hugging Face/Pyannote,
CUDA/cuDNN, Whisper, YOLOX, VLM, Ollama, Qdrant, espace disque et environnement
CloseDay. Ne contourne pas un check rouge : suis la ligne `[FIX]`. Attends :

- `pairing_ready=true` ;
- `ai_ready=true` ;
- `http://localhost:8710/ready` en HTTP 200.

Garde cette console ouverte pendant toute la capture et tout CloseDay. Le
pare-feu Windows doit autoriser Python sur le réseau privé et le port TCP 8710.

Le lanceur bas niveau `RUN_MLOMEGA_V19.ps1` conserve **Full par défaut** pour la
compatibilité. Le nouveau raccourci S24/XREAL choisit explicitement **Lite** :
archive lossless des tours, une analyse owner-centrée bornée par épisode et
projection des faits utiles T1/vision/Sherlock. Ce sélecteur ne change ni le
Live, ni les fonctions lunettes, ni Local/PRO.

`-AugmentedReality` démarre aussi le service isolé sur
`http://127.0.0.1:8791`; RUN doit afficher qu'il est prêt. Sans ce flag,
Memory/BrainLive restent utilisables, mais les fonctions augmentées PC sont
volontairement inertes.

Commande bas niveau de secours, équivalente au raccourci Local Lite :

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality `
  -MemoryProfile lite -BindHost 0.0.0.0 -Port 8710
```

## 3. Lancer le PC — mode PRO optionnel

Le mode PRO ne change pas le Live : l'interaction reste locale. Il remplace
seulement les traitements lourds après la fin par DeepSeek, Groq Whisper et
Gemini VLM, avec budget dur.

Dans `.env`, renseigne sans jamais committer les clés :

```text
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

Puis :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
.\START_XREAL_S24.cmd -Pro -MemoryProfile lite `
  -ProTextModel pro -CloudBudgetEur 1.50 -CloudOnBudget stop
```

Pour réduire le coût au prix d'une analyse moins profonde, remplace
`-ProTextModel pro` par `-ProTextModel flash`. `-CloudOnBudget stop` est le
choix sûr : aucune dépense au-delà du plafond. Pour PRO avec toute la chaîne
historique, remplace `lite` par `full`. Le Live reste local dans les deux cas.

## 4. Vérifier LAN et Tailscale avant la capture

Sur le S24, dans un navigateur :

- à la maison : `http://192.168.1.199:8710/ready` ;
- hors du LAN : `http://100.113.42.19:8710/ready`.

La page doit indiquer la chaîne IA prête. Si le LAN échoue mais Tailscale
répond, l'app bascule sur Tailscale. Si les deux échouent :

```powershell
tailscale status
tailscale ip -4
Test-NetConnection 127.0.0.1 -Port 8710
```

Vérifie aussi que le S24 et le PC sont dans le même tailnet et que le S24
n'utilise pas un exit node qui bloque le LAN.

## 5. Première session sur le S24

1. Lance d'abord le PC et attends le préflight vert.
2. Ouvre ControlGlasses, branche Eye + One Pro, puis lance MLOmega depuis
   ControlGlasses.
3. Accorde caméra, micro et overlay à la première demande.
4. Attends `Paired`, puis `Connected`. Lors du premier démarrage, laisse les
   modèles ASR finir leur téléchargement (`dl: ... 100 %`).
5. Première commande obligatoire : **« Viki, configure ma voix »**, puis parle
   naturellement pendant la capture demandée. Le porteur doit devenir
   `person_id=me`; n'utilise pas les conclusions personnelles avant cet
   enrôlement.

Contrôle rapide conseillé :

- sous-titres et wake word « Viki » ;
- « c'est quoi ça ? », « lis le texte », « traduis-le » ;
- « où sont mes lunettes ? » : contour si visibles, sinon dernière observation
  honnête ;
- « ouvre le menu », paume, pinch/zoom et déplacement d'un panneau ;
- « aide-moi à faire un café », puis « étape suivante » ;
- une requête mémoire après avoir dit un fait dans la session ;
- UI stéréo stable, Eye active et pose 6DoF sans faux saut.

Pour les fonctions FreeGuy, ouvre **Menu → Réglages AR**. Active d'abord
**AR globale**, puis uniquement les fonctions voulues : navigation, labels,
ancres, occlusion, style FreeGuy, mesure, clavier, lancer, etc. Tous les
interrupteurs sont OFF au premier démarrage afin de protéger FPS, batterie et
lisibilité. `ACTIF` signifie que le capteur/provider requis est réellement
disponible; `SYNCHRO`, `OFF` ou une erreur ne doivent pas être forcés.

La navigation extérieure utilise la route réseau lorsqu'elle est disponible,
puis un cap GPS/boussole honnête comme fallback; ce n'est pas du VPS Google. Si
pose, GPS ou boussole ne sont pas qualifiés, l'app affiche l'indisponibilité et
ouvre Maps. ARCore Geospatial n'est volontairement pas chargé en même temps que
le loader XREAL avant le gate matériel A2c.

Pour un lieu intérieur, active **Navigation intérieure**, accorde Localisation
précise et Appareils à proximité, puis marche normalement : la pose XREAL trace
le chemin, tandis que Wi-Fi/BLE/magnétique servent seulement à reconnaître un
lieu déjà parcouru. Dis par exemple **« nomme cet endroit comme cuisine »**.
Plus tard, **« ouvre Maps vers cuisine »** affiche le chemin appris. `ATTENTE`
signifie que pose ou permissions manquent; ce mode n'est jamais présenté comme
un GPS indoor.

**Planétarium** exige une pose suivie, GPS <= 50 m et cap <= 30°; sinon il
s'abstient. **Météo contextuelle** est facultative et n'appelle Open-Meteo qu'au
plus toutes les dix minutes. Pour l'aide globale France, active **Aide contexte
social/juridique**, puis dis **« active le mode juridique »**. Le PC cherche dans
LEGI, cite Légifrance et s'arrête avec **« arrête le mode juridique »** ou après
15 minutes d'inactivité. Internet est requis pour LEGI; le mode contextuel
général utilise le Kiwix local.

### Connaissance hors ligne, domotique et profils studio

E2 tourne sur le **PC**, pas sur le S24 : le téléphone/lunettes ne reçoivent que
la petite carte UI. Sur cette machine, `kiwix-tools 3.8.1` et le corpus
`wikipedia_fr_top_mini_2026-04.zim` sont installés et vérifiés par SHA-256. Pour
réinstaller proprement :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\INSTALL_KIWIX_FR.ps1
```

RUN démarre Kiwix sur `127.0.0.1:8792` avant le service AR, refuse un endpoint
configuré mais mort, puis l'arrête à la fin. Une demande explicite contourne le
cooldown; les cartes automatiques restent bornées à une toutes les 90 secondes.

Pour ajouter un objet Home Assistant, récupère d'abord son `entity_id` dans
**Paramètres → Appareils et services → Entités**, puis crée un jeton longue durée
dans ton profil Home Assistant. Exemple pour `light.salon` :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\CONFIGURE_AUGMENTED_REALITY.ps1 `
  -Mode device -Label "lampe salon" -EntityId "light.salon" `
  -HomeAssistantUrl "http://homeassistant.local:8123"
```

La commande demande le jeton sans l'afficher, le conserve seulement dans `.env`
et crée le registre local ignoré par Git. Ensuite : regarde la lampe, ouvre sa
carte objet, sélectionne **Marche / arrêt**, puis confirme par un second pinch.
MLOmega lit l'état avant, commande Home Assistant et relit l'état terminal.

Le mode **Profils studio** est volontairement simple : un seul code ouvre la
release entière, sans créer une fiche préalable pour chaque acteur. Configuration
unique :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\CONFIGURE_AUGMENTED_REALITY.ps1 `
  -Mode studio -ReleaseId "release-film-2026-001"
```

Choisis le code à 6–12 chiffres lorsqu'il est demandé. Ajoute aussi la clé Web
Detection dans `.env` :

```text
MLOMEGA_GOOGLE_VISION_API_KEY=...
```

Puis lance le tournage :

```powershell
.\START_XREAL_S24.cmd `
  -StudioReleaseId release-film-2026-001
```

RUN demande le code avant la capture. Un mauvais code ou une release inconnue
bloque le mode studio. La recherche Web reste limitée à une tentative par track,
affiche **candidat à confirmer** et ne modifie jamais l'identité faciale ni la
mémoire automatiquement.

État des trois raccords :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\CONFIGURE_AUGMENTED_REALITY.ps1 -Mode status
```

Les scénarios vocaux complets restent décrits dans
[`A_TESTER_ALL_FEATURES_SCENARIOS.md`](A_TESTER_ALL_FEATURES_SCENARIOS.md).
Ils utilisent les mêmes routes PC, BrainLive et UI sur le S24.

Pour observer le runtime depuis le PC :

```powershell
Invoke-RestMethod http://localhost:8710/metrics |
  ConvertTo-Json -Depth 8
```

On doit voir progresser audio, vidéo, commandes et effets device. Une commande
`accepted` n'est pas à elle seule une preuve : son état terminal doit être
`completed` ou un échec explicite.

## 6. Terminer proprement et lancer CloseDay

Ne swipe pas l'app et ne débranche pas les lunettes pour terminer.

Sur l'écran du S24/MLOmega, touche :

**« Terminer la session et lancer CloseDay »**

Ce bouton :

1. envoie `POST /session/end` avec le token de session ;
2. arrête capture et transport ;
3. scelle les données durables ;
4. déclenche la finalisation BrainLive, Deep Audio/Deep Vision et CloseDay ;
5. laisse le travail lourd continuer sur le PC.

Le bouton Android reçoit vite l'accusé ; cela ne signifie pas encore que la
mémoire nocturne est terminée. Surveille la console PC et :

```powershell
Invoke-RestMethod http://localhost:8710/metrics |
  ConvertTo-Json -Depth 8
```

Attends successivement :

- `end_session = completed` ;
- `close_day = running`, puis `completed` ;
- maintenance `completed` ou un warning expliqué.

`/session/status` est une route **POST authentifiée** utilisée par l'app : ne la
teste pas en collant simplement son URL dans un navigateur.

Si le S24 ou le PC crashe, conserve la DB et les logs puis relance exactement
la même commande RUN. La recovery reprend le job durable et bloque CloseDay
plutôt que de déclarer un faux succès. Ne lance pas manuellement un second
CloseDay sur une session encore active.

Quand `close_day=completed`, arrête le serveur par `Ctrl+C`, quitte MLOmega dans
ControlGlasses et débranche les lunettes.

## 7. Ouvrir le Dashboard

Après CloseDay :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
```

Ouvre <http://localhost:8720>. Le script lit `MLOMEGA_DB` depuis `.env`, affiche
le chemin exact et vérifie que le SHA de la DB n'a pas changé : le Dashboard est
strictement en lecture seule.

Pour une DB précise :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1 `
  -Database "C:\chemin\vers\memory.db"
```

Ferme le Dashboard avec `Ctrl+C`.

## 8. Audit owner/qualité — manuel, jour OFF

Cet audit n'est pas un CloseDay supplémentaire. Il relit la base terminée,
prépare un devis, demande à DeepSeek Pro seulement les arbitrages ambigus, crée
un backup, puis applique uniquement des opérations sûres codées. Il ne donne
jamais du SQL libre au modèle.

Depuis la racine :

```powershell
$line = Select-String -Path .env -Pattern '^\s*MLOMEGA_DB\s*=' |
  Select-Object -First 1
$db = (($line.Line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
if (-not [IO.Path]::IsPathRooted($db)) {
  $db = Join-Path $pwd $db
}
$db = (Resolve-Path $db).Path

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$plan = "tools\harness\_run\owner-shadow-$stamp-plan.json"
$report = "tools\harness\_run\owner-shadow-$stamp-report.json"

.\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
  --db $db --owner-id me --owner-name William `
  --plan-only --text-backend deepseek --deepseek-model deepseek-v4-pro `
  --vision-backend existing --budget-eur 1.00 --out $plan
```

Lis le résumé global et le coût estimé dans `$plan`. Si le devis est cohérent :

```powershell
.\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
  --db $db --owner-id me --owner-name William `
  --execute --plan $plan --apply-safe `
  --text-backend deepseek --deepseek-model deepseek-v4-pro `
  --vision-backend existing --budget-eur 1.00 --out $report
```

Résultat attendu : `mode=execute_applied_safe`, chemin du backup et
`quick_check=ok`. Pour afficher aussi le rapport :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1 `
  -Database $db -ShadowReport $report
```

Ne lance cet audit qu'après un CloseDay terminé, idéalement une fois par semaine
ou un jour OFF, pas après chaque session.

## 9. Diagnostic lunettes/S24

Avec le S24 relié en ADB :

```powershell
adb logcat |
  Select-String 'XrealDeviceAdapter|Eye capture|LiveTransport|tracking|SessionPairing'
```

À vérifier :

- `Eye capture started` : caméra Eye réellement ouverte ;
- transport `Connected` ;
- aucune erreur shader/YUV ;
- aucune pose positionnelle valide avant un vrai tracking 6DoF.

Problèmes courants :

- **Pairing bloqué** : vérifie `/ready` depuis le S24, pare-feu, LAN/Tailscale,
  puis relance d'abord le PC.
- **Eye absente** : remonte le module, repasse l'OTA PC, utilise le câble
  d'origine et redémarre le S24.
- **UI noire ou non stéréo** : lance depuis ControlGlasses et non depuis le
  launcher Android ou DeX ; vérifie USB et permission overlay.
- **Téléchargement modèle bloqué** : garde l'app au premier plan et le S24
  alimenté jusqu'à la fin de `dl:`.
- **CloseDay `error`/`blocked`** : ne supprime rien ; relance RUN pour recovery et
  conserve la console ainsi que la DB.

Références constructeur :

- SDK/tested devices : <https://developer.xreal.com/download/>
- démarrage XREAL SDK : <https://docs.xreal.com/Getting%20Started%20with%20XREAL%20SDK>
- guide XREAL Eye : <https://tutorials.xreal.com/docs/accessories/eye/>
- compatibilité SDK et ControlGlasses :
  <https://developer.xreal.com/download/>
- sortie filaire Samsung S24/DeX :
  <https://www.samsung.com/us/support/answer/ANS10001972/>
- Tailscale Android : <https://tailscale.com/docs/install/android>

## 10. Rebuild développeur uniquement

L'utilisateur normal installe l'APK déjà produite. Après une modification
Unity/XREAL, ferme toute fenêtre Unity et exécute les deux passes depuis
`apps\xr-mobile` :

```powershell
$u = "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe"
$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines', `
  '-logFile',"$pwd\xreal-prep.log" -Wait -PassThru -NoNewWindow
"prep=$($p.ExitCode)"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.BuildApk', `
  '-logFile',"$pwd\xreal-build.log" -Wait -PassThru -NoNewWindow
"build=$($p.ExitCode)"
```

Un exit code 0 n'est pas suffisant : le log doit finir par un build réussi sans
exception XREAL/JSON. L'APK finale doit lancer
`ai.nreal.activitylife.NRXRActivity` et contenir les endpoints LAN/Tailscale.

## Piloter les modes du Prélude avec VIKI

Le menu et la voix modifient exactement les mêmes switches. Exemples :

- `VIKI, active le mode FreeGuy`;
- `VIKI, désactive le mode FreeGuy`;
- `VIKI, active les mouvements de foule`;
- `VIKI, active la vision événementielle`;
- `VIKI, désactive les sons sémantiques`.

La séquence visible attendue est : badge `VIKI ● écoute`, carte
`Je t'écoute…`, sous-titre du texte reconnu, puis carte
`activé`, `désactivé` ou `indisponible`. Si la dernière carte indique
`indisponible`, ne pas considérer la fonction comme active : sa capacité
matérielle/provider manque réellement.

FreeGuy peut rester actif pendant les trajectoires de foule ou une autre
fonction ponctuelle. Le runtime partage un seul provider spatial, déduplique
les surfaces, expire les éléments par TTL et plafonne FreeGuy à 12 surfaces.
Pour le premier test physique, activer les fonctions progressivement plutôt
que tout le menu : la fluidité et la température finales doivent encore être
mesurées sur S24 + XREAL Eye.
