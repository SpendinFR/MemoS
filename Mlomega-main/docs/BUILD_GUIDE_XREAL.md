# Build guide XREAL — S24 + One Pro + Eye

Dernière mise à jour : 31 juillet 2026.

Ce document est le point de reprise technique autoritaire pour les deux APK
XREAL de MLOmega :

- produit : `apps/xr-mobile/build/android/mlomega-xreal.apk`,
  package `com.mlomega.xr.glasses` ;
- Atelier : `apps/xr-mobile/build/android/mlomega-xreal-world-atelier.apk`,
  package `com.mlomega.xr.worldatelier`.

Il ne certifie pas encore ces APK. Il consigne ce qui a réellement été observé
sur Galaxy S24 + XREAL One Pro + Eye, ce qui reste rouge, les commandes fiables
et les pistes déjà éliminées. Le chemin PhoneOnly, les runners Local/PRO,
Memory, BrainLive et CloseDay ne doivent pas être modifiés pendant ce chantier.

## 1. Verdict matériel au point de pause

### 1.1 Prouvé sur le matériel

- Le template XREAL officiel peut obtenir une vraie surface XR sur ce S24
  lorsque Samsung DeX est désactivé.
- Le SDK XREAL démarre et présente à environ 60 Hz.
- La pose 6DoF remonte réellement.
- l'XREAL Eye transmet des frames grayscale.
- l'IMU du contrôleur remonte.
- le menu Atelier peut rester world-locked/ancré pendant la session.
- l'APK Atelier compile, s'installe et entre dans sa scène XREAL via
  `ai.nreal.activitylife.NRXRActivity`.

Ces résultats invalident l'hypothèse « Android 16/S24 rend toute application
XREAL impossible ». Ils ne valident ni le rendu final ni l'interaction.

### 1.2 Encore rouge

- Le fond de la surface Atelier reste violet/magenta sur le matériel.
- Aucun clic n'a produit d'action : ni sélection du menu, ni fallback tactile
  essayé sur le S24.
- Le pointeur mains n'est pas fonctionnel.
- déplacement et redimensionnement du menu ne sont pas validés.
- persistance/relocalisation des ancres après redémarrage non validée.
- l'APK produit `mlomega-xreal.apk` n'a pas encore reçu puis traversé le même
  gate matériel corrigé. Ne pas lui appliquer en bloc les expérimentations de
  l'Atelier.

Le violet ne doit donc pas être présenté comme « seulement esthétique » : il
empêche de certifier le composite optique et peut masquer un mauvais matériau,
une mauvaise surface ou un objet plein écran. Le clic absent est un blocker
produit distinct.

## 2. Garde-fous : ne pas casser les autres produits

1. Toute modification de PlayerSettings, pipeline, XR loader, packages ou
   manifeste doit rester dans la portée temporaire
   `AndroidBuildXreal` et être restaurée en `finally`.
2. Le `Packages/manifest.json` commité reste sans SDK XREAL. Le SDK propriétaire
   est injecté uniquement pendant la passe XREAL.
3. Ne jamais committer les scènes, settings XR, samples, TextMesh Pro ou
   fichiers `ProjectSettings` générés par une passe Unity.
4. Ne pas toucher à `PhoneOnly.unity`, à son manifeste ou à son APK pour
   corriger XREAL.
5. Ne pas modifier les prompts, le pipeline PC, Local/PRO, Memory ou CloseDay.
6. Toute nouvelle dépendance d'interaction, notamment MRTK3, se teste d'abord
   dans un projet/spike isolé. Elle ne rentre pas directement dans l'APK
   produit.

## 3. Préparation du S24 : DeX doit réellement lâcher l'écran

Samsung DeX a été le premier faux chemin de la journée. Quand DeX détient
l'écran des lunettes, Android crée un bureau/fenêtre externe avec barre des
tâches. Ce n'est pas une surface XR valide, même si l'APK paraît ouverte.

### 3.1 Méthode opérateur

Avant de lancer une APK XREAL :

1. désactiver Samsung DeX dans les réglages rapides ou
   `Paramètres > Appareils connectés > Samsung DeX` ;
2. débrancher puis rebrancher les lunettes ;
3. ne pas accepter le bureau DeX, sa barre des tâches ou une simple recopie
   d'écran comme résultat ;
4. lancer l'activité XREAL/ControlGlasses, pas `UnityPlayerActivity`.

Le bouton physique X des lunettes n'est pas le bouton d'ancrage de l'Atelier :
pendant le test il a quitté le rendu 3D. Utiliser le bouton logiciel prévu dans
la scène.

### 3.2 Vérification ADB

Depuis PowerShell :

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"

& $adb shell settings put system dex_on_external_display 0
& $adb shell settings put global dex_on_external_display 0
& $adb shell settings put secure dex_on_external_display 0

& $adb shell dumpsys activity activities |
  Select-String "SecondaryLauncher|dexservice|mode=freeform|name=Desk"
```

Une tâche `com.honeyspace.dexservice.SecondaryLauncher`, `name=Desk` ou
`mode=freeform` signifie que DeX contrôle encore l'écran. Les trois clés ADB ne
remplacent pas toujours la désactivation manuelle One UI ; vérifier le résultat
plutôt que supposer que la commande a été honorée.

Sous DeX, les observations historiques étaient incohérentes :

- écran XREAL annoncé nativement en 640×480 ;
- override DeX 1600×900 ;
- SDK cherchant une surface 1920×1080 ou 3840×1080 ;
- `FLAG_EXTERNAL_DEX_HOSTING` et bureau secondaire présents.

Ne pas corriger ces symptômes en falsifiant la résolution du SDK.

## 4. ADB fiable après une passe Unity

Unity peut arrêter son propre serveur ADB. Après chaque build, relancer ADB
avant de conclure que l'installation est bloquée :

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
Stop-Process -Name adb -Force -ErrorAction SilentlyContinue
& $adb start-server
& $adb devices
```

Pour ADB Wi-Fi, l'adresse observée pendant cette session était
`192.168.1.134:5555`, mais elle n'est pas une constante produit :

```powershell
& $adb connect 192.168.1.134:5555
& $adb devices
```

Installer puis vérifier l'horodatage du package :

```powershell
& $adb install -r `
  ".\apps\xr-mobile\build\android\mlomega-xreal-world-atelier.apk"

& $adb shell dumpsys package com.mlomega.xr.worldatelier |
  Select-String "lastUpdateTime|versionName|versionCode"
```

Lancer par la bonne porte d'entrée :

```powershell
& $adb shell am force-stop com.mlomega.xr.worldatelier
& $adb shell am start -n `
  com.mlomega.xr.worldatelier/ai.nreal.activitylife.NRXRActivity
```

Pour le produit, remplacer le package par `com.mlomega.xr.glasses`. Ne jamais
lancer directement `com.unity3d.player.UnityPlayerActivity`.

## 5. Build reproductible

Fermer l'éditeur Unity avant la passe batch. Version utilisée :
Unity `6000.0.23f1`.

```powershell
$root = "C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main"
$project = Join-Path $root "apps\xr-mobile"
$unity = "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe"

& $unity -batchmode -quit `
  -projectPath $project `
  -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines `
  -logFile (Join-Path $root "xreal-prepare.log")

if ($LASTEXITCODE -ne 0) { throw "PrepareDefines failed" }
```

Atelier :

```powershell
& $unity -batchmode -quit `
  -projectPath $project `
  -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildCreatorApk `
  -logFile (Join-Path $root "xreal-atelier-build.log")

if ($LASTEXITCODE -ne 0) { throw "BuildCreatorApk failed" }
```

Produit :

```powershell
& $unity -batchmode -quit `
  -projectPath $project `
  -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildApk `
  -logFile (Join-Path $root "xreal-product-build.log")

if ($LASTEXITCODE -ne 0) { throw "BuildApk failed" }
```

Un APK fraîchement écrit et `Build succeeded` sont nécessaires. Un exit 0
accompagné d'une exception XREAL/JSON reste rouge.

### 5.1 Réglages de référence réellement utiles

Le template officiel ayant fonctionné sur le matériel est la référence, pas
une mémoire approximative des essais :

- Graphics API : OpenGLES3, pas Vulkan ;
- pipeline Built-in dans le template ;
- `Initialize XR on Startup = true` (`m_InitManagerOnStart: 1`) ;
- orientation Android : AutoRotation dans le template ;
- caméra : `Skybox`, aucun matériau de skybox, alpha de fond à zéro ;
- résolution de référence : 1920×1080 ;
- scène simple, canvas world-space ;
- activité `NRXRActivity`.

Important : le template officiel avait le multithreaded rendering actif et
fonctionnait. Ne le basculer ni à `true` ni à `false` sur la base d'une
recommandation générique ; faire un test A/B borné seulement si les autres
différences sont neutralisées.

La tentative `XRDisplaySubsystem.EnableRenderBackColor(false)` est désormais
appelée réellement et n'a pas supprimé le violet. C'est une condition possible
du see-through, pas la cause racine démontrée.

## 6. Patch « XREAL Pro HDMI » : historique et statut

Le début du diagnostic a essayé de faire reconnaître le nom EDID
`XREAL One Pro` par `GlassesDisplayPlugEvent` et de neutraliser le fond de
l'activité proxy. Le script actuel est
`scripts/PATCH_XREAL_S24_DISPLAY.ps1`.

Ce script :

- restaure d'abord les AAR officiels depuis le tarball XREAL ;
- remplace `DisplayModel.class` par un matcher EDID élargi ;
- remplace le layout de l'activité proxy par un fond optique noir ;
- vérifie le bytecode réinjecté.

Il est conservé comme compatibilité explicite et reproductible, mais son effet
n'est pas certifié comme solution du violet. Ne plus modifier ou repackager
ControlGlasses à la main : cela a multiplié les variables sans prouver le
composite. Utiliser l'application officielle sur le S24.

Le résultat déterminant a été obtenu sans faux appareil : une fois DeX
réellement désactivé, le template officiel a affiché son menu XR. Le prochain
diagnostic doit donc comparer notre scène/runtime au template, pas réécrire
encore le modèle HDMI.

## 7. Violet : cause racine fermée sur matériel

### 7.1 Faits observés

- capture matérielle : toute la surface stéréo est violet vif, le menu étant
  rendu par-dessus ;
- le menu peut être world-locked ;
- le framerate reste proche de 60 Hz ;
- la caméra Eye et la pose 6DoF continuent de remonter ;
- le template officiel, avec DeX désactivé, affiche un fond noir/transparent
  stable sur le même téléphone et les mêmes lunettes.

### 7.1.1 Verdict matériel du 31 juillet 2026

Le fond violet est **corrigé et vérifié dans les lunettes**. Il ne venait ni de
DeX, ni de la caméra, ni d'URP : `WorldCreatorController.MakeNeonFrame` créait
un `LineRenderer` fermé sous le Canvas XR world-space. En single-pass stéréo,
la bande générée traversait/remplissait les surfaces des yeux.

La preuve n'était pas seulement visuelle : le fond de la capture valait environ
`RGB(139, 51, 253)`, soit la couleur terminale exacte du cadre
`new Color(.55f, .2f, 1f, .95f)`. Le grand triangle cyan provenait de la même
géométrie. La suppression **totale** du cadre — sans bandes de remplacement —
a rendu le monde réel transparent tout en conservant le menu.

À ne pas régresser : ne jamais placer de `LineRenderer` décoratif sous le
Canvas du pupitre. Pour un contour futur, utiliser uniquement de petits
éléments UGUI séparés, après gate matériel.

### 7.2 Causes testées sans succès

- désactivation DeX seule ;
- `EnableRenderBackColor(false)` ;
- alpha caméra à zéro ;
- passage Atelier en Built-in ;
- remplacement des `Shader.Find("Universal Render Pipeline/Unlit")` par un
  shader runtime Built-in/URP inclus dans le build ;
- ajout d'un SubShader Built-in à `LiquidGlass` ;
- suppression du post-processing Atelier ;
- OpenGLES3 et MSAA désactivé ;
- différentes orientations/résolutions ;
- patch du layout proxy XREAL.

Ne pas refaire ces permutations une par une sans nouvelle mesure.

### 7.3 Logs encore significatifs

Au démarrage, conserver et corréler :

```text
Invalid perception runtime config
load external alg so failed
Failed to find display resolution for dp resolution 3840x1080
Faield to get display roi
```

Les premiers `FrameWait` peuvent échouer brièvement avant que le flux tourne.
Le verdict ne vient pas d'une ligne isolée : il faut corréler affichage,
render-pass, dimensions et objets visibles.

### 7.4 Protocole historique ayant permis le verdict

1. Lancer le template officiel et l'Atelier dos à dos avec DeX confirmé absent.
2. Ajouter à un build diagnostic minimal les mesures suivantes :
   `Screen.width/height`, caméra(s) active(s), clear flags/couleur, pipeline
   courant, nombre de render passes XREAL, texture/viewport de chaque
   `XRRenderPass`, displayId et activité courante.
3. Partir de la scène du template qui fonctionne et ajouter uniquement le
   pupitre Atelier, sans shaders produit.
4. Si ce minimal reste noir/transparent, réintroduire par couches :
   panneau opaque, texte, LiquidGlass, halo, catalogue, puis providers.
5. La première couche qui rend toute la cible violette donne la cause. La
   supprimer/corriger avant de reconstruire la scène complète.
6. Seulement après un Atelier transparent, reporter le profil prouvé vers
   `mlomega-xreal.apk` et refaire le même smoke matériel.

Ce protocole doit produire un verdict en quelques builds bornés. Il interdit
les changements simultanés de DeX, pipeline, résolution, shader et activité qui
ont rendu les essais précédents difficiles à interpréter.

## 8. Clic, pointeur, déplacement et redimensionnement

### 8.1 Statut matériel au 31 juillet 2026

Le clic contrôleur est désormais **réellement vert** dans l'Atelier. La cause
était une comparaison invalide dans `TryProjectDeckPointer` :
`WorldToScreenPoint` renvoyait les coordonnées de la cible XR paysage, puis le
code les bornait avec `Screen.width/height` du S24 portrait. La moitié du
pupitre pouvait donc être rejetée alors que le curseur restait visible.

Le hit `RectTransform` valide déjà les limites du pupitre : la seconde
comparaison a été supprimée. Test matériel réussi : menu transparent,
world-lock 6DoF et clic fonctionnel.

Restent ouverts : pinch main, déplacement/redimensionnement par pinch et
fallback tactile explicite. La présence d'un curseur ne suffira toujours pas à
les valider.

Le tactile du téléphone vise le display Android principal ; une UI rendue dans
une surface XR externe ne reçoit donc pas automatiquement les mêmes
coordonnées. Le fallback doit être un pont explicite, pas une promesse de
Unity Input System.

### 8.2 Ordre du prochain chantier interaction

1. Conserver le clic contrôleur vert comme référence et journaliser source,
   rayon, `pointerDown`, `pointerUp`, objet ciblé et action terminale.
2. Tester l'accès à l'image CPU de l'Eye via
   `ARCameraManager.TryAcquireLatestCpuImage`. Si des frames arrivent, brancher
   MediaPipe Hand Landmarker à cadence/résolution bornées.
3. Utiliser le regard/head-gaze pour viser et le **pinch de la main** pour
   press/release. Ne pas appeler ce geste « pinch Eye » : l'Eye est la caméra
   qui observe la main.
4. Ajouter sous le menu une poignée contextuelle regardée : pinch maintenu =
   déplacer/avancer/reculer ; poignée bas-gauche = resize borné. Le menu reste
   world-space et ne redevient pas head-locked pendant la manipulation.
5. Ajouter un fallback téléphone explicite : surface/touchpad sur le S24 qui
   envoie rayon normalisé + press/release à l'UI XR.
6. Gate matériel : 30 clics, sélection de catégories, drag, resize, recenter,
   suppression d'une ancre et 10 minutes sans dérive thermique bloquante.

### 8.3 Usage possible de MRTK3 XREAL

Le dépôt
`https://github.com/dengxian-xreal/MixedRealityToolkit-Unity-XREALSDK`
intègre XREAL à MRTK3/XRI et contient des briques d'UX, d'input 2D/3D et de
spatial manipulation. Il est pertinent pour :

- boutons et états de focus/press robustes ;
- `ObjectManipulator`/`BoundsControl` ou équivalents pour déplacer/resizer ;
- rayon contrôleur et modèle d'interaction unifié ;
- menus/slates world-space.

Il ne prouve pas que One Pro + Eye fournit du hand tracking natif. La stratégie
est donc :

1. cloner/ouvrir le sample séparément ;
2. tester contrôleur + bouton + manipulateur sur le matériel ;
3. inventorier seulement les packages/prefabs indispensables ;
4. intégrer une verticale minimale dans l'Atelier sous un define XREAL ;
5. conserver notre futur provider MediaPipe Eye comme source de mains si le
   `XRHandSubsystem` natif reste vide.

Ne jamais importer tout MRTK3 directement dans le projet principal avant ce
spike : il modifierait packages, Input System, EventSystem et shaders en même
temps, et rendrait PhoneOnly/runs impossibles à isoler.

### 8.4 Jalon matériel : pinch, clic 3D et manipulation verts

Validé physiquement le 31 juillet 2026 sur Galaxy S24 + XREAL One Pro + Eye :

- la caméra Eye fournit réellement les images couleur à Unity ;
- `HandLandmarker` tourne sur le S24 en GPU/LIVE_STREAM à 768 x 432 et 15 fps ;
- la main est détectée et le ratio pouce-index traverse réellement les seuils ;
- `PINCH_BEGIN`, `PINCH_UPDATE` et `PINCH_END` remontent jusqu'à Unity ;
- le pinch déclenche réellement les boutons regardés ;
- la poignée basse déplace le pupitre et la poignée bas-gauche le redimensionne ;
- le contrôleur/touchpad S24 reste disponible comme repli ;
- le pupitre reste world-space et peut être observé en se déplaçant autour.

Chaîne prouvée à conserver :

```text
XREAL Eye YUV_420_888
  -> shader CaptureBackgroundYUV compatible GLES3
  -> RGB 768 x 432
  -> MediaPipe HandLandmarker GPU
  -> ratio 3D thumb tip / index tip normalisé par wrist / index MCP
  -> EMA 0,5 + hystérésis 0,28/0,38 + debounce 3 frames/2 frames
  -> GestureBridge
  -> head-gaze pour viser
  -> collider 3D exact du Button/TMP_InputField
  -> pointerDown/pointerUp/pointerClick Unity
```

Deux causes racines ont été mesurées pendant le gate :

1. `SRGBToLinear` ne compilait pas sur GLES3 : le shader avait zéro programme
   Android et MediaPipe recevait une image magenta uniforme. Le shader local
   reprend désormais la passe officielle XREAL (`UnityCG`, plans Alpha8,
   `GammaToLinearSpace`) et le build doit annoncer `gles3 ... 6 programs`.
2. Un `GraphicRaycaster` 2D ne suffit pas pour un Canvas world-space rendu dans
   la cible XR alors que `Screen.width/height` décrit le S24. Chaque contrôle
   interactif possède donc une mince surface `BoxCollider`; un
   `Physics.RaycastNonAlloc` world-space sélectionne le vrai contrôle, sans
   approximation ni conversion écran. Ne pas retirer ces colliders.

Le pipeline natif XREAL Hands reste vide sur cette monture. La source main
validée est la caméra Eye + MediaPipe. `Xreal-tools` a servi de référence pour
la géométrie du pinch, sans reprendre son acquisition UVC brute qui entrerait
en conflit avec la session XREAL : https://github.com/nudou350/Xreal-tools.

Limites honnêtes du jalon : le pinch demande parfois environ 1 à 2 secondes et
le déplacement/redimensionnement fonctionne mais manque encore de fluidité et
de précision. Ces optimisations viennent après ce commit de référence : ne pas
changer simultanément modèle, acquisition Eye, seuils, raycast et UI.

Build et installation ayant servi au gate :

```powershell
& "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe" `
  -batchmode -quit `
  -projectPath "$PWD\apps\xr-mobile" `
  -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildCreatorApk `
  -logFile "$PWD\apps\xr-mobile\build\android\world-atelier-build.log"

$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb connect 192.168.1.134:5555
& $adb -s 192.168.1.134:5555 install -r `
  ".\apps\xr-mobile\build\android\mlomega-xreal-world-atelier.apk"
```

Preuve attendue dans `adb logcat` :

```text
MLOmegaEyePinch: HandLandmarker ready (GPU/LIVE_STREAM, 15.0 fps)
MLOmegaEyePinch: ... hand=true ratio=...
GestureBridge: native PINCH_BEGIN
XrealNativeHandPointer: pinch press: deckHit=True, hover=Button ...
```

Prochain lot borné, après ce jalon : réduire la latence d'engagement sans faux
clics, lisser la manipulation world-space, ajouter une poignée haute-droite de
réduction/fermeture, puis évaluer le geste paume ouverte pour rappeler le menu.

### 8.5 Jalon matériel controls-v2 : paume, réduction et manipulation

Gate réel One Pro + Eye/S24 validé le 31 juillet 2026 :

- la paume ouverte tenue rappelle réellement le pupitre ;
- la poignée haute-droite réduit réellement le pupitre ;
- le pinch engage en deux résultats MediaPipe au lieu de trois ;
- déplacement et resize sont interpolés à la cadence Unity plutôt qu'aux seuls
  retours du HandLandmarker ;
- la base caméra et les axes sont figés au début de la prise, ce qui supprime une
  partie des sauts observés pendant la manipulation ;
- clics et ancrage world-space du jalon `17e31dc` restent verts.

Les deux APK doivent rester disponibles pendant les réglages suivants :

- baseline : `mlomega-xreal-world-atelier-17e31dc.apk` ;
- candidate validée : `mlomega-xreal-world-atelier-controls-v2.apk`.

Limites mesurées, et non faux-verts : le chip réduit reste visible, le pinch
profond peut encore attendre deux inférences et un déplacement tenu ne suit pas
encore une grande rotation de tête. La v3 doit donc être une variante séparée :
réduction totalement invisible restaurée par paume, engagement immédiat seulement
pour un pinch très nettement fermé, et transport 360° de la pose initiale par le
delta de rotation de la tête. Le relâchement doit toujours laisser le pupitre
ancré dans le monde.

### 8.6 Jalon matériel controls-v3 : transport 360° et menu réellement masqué

Gate réel One Pro + Eye/S24 validé le 31 juillet 2026. Cette version devient le
rollback de référence avant toute optimisation supplémentaire :

- géométrie Eye conservée à la résolution matérielle prouvée de 768 px ;
- cadence Atelier seule portée à 20 fps, sans modifier la cadence du produit ;
- un pinch très nettement fermé peut engager dès le premier résultat, tandis
  qu'un pinch proche du seuil conserve la confirmation anti-faux-clic ;
- le pupitre tenu suit le delta de rotation de la tête sur 360°, puis reste
  ancré dans le monde au relâchement ;
- position, rotation et échelle sont interpolées à la cadence de rendu Unity ;
- Réduire masque maintenant tout le pupitre et une paume ouverte le restaure ;
- les frames Eye restent en RAM. La frame diagnostic unique est désactivée dans
  la scène validée : aucune image des mains n'est écrite sur disque ;
- clics, déplacement, resize, paume, transparence et ancrage 6DoF restent verts.

Artefact matériel validé, à ne jamais écraser :

```text
apps/xr-mobile/build/android/mlomega-xreal-world-atelier-controls-v3.apk
taille = 223801014 octets
sha256 = A5D42E8CCD6C815B9D249A4C20CA36EA17A359D8F0E5AB85B7A275E89EE67107
```

Limites honnêtes restantes : la manipulation saccade encore légèrement et le
pinch demande souvent environ une seconde en conditions réelles. Le prochain lot
doit donc rester une APK v4 séparée. Il peut ajouter un bouton Recentrer explicite
qui remet le pupitre droit face à l'utilisateur et un poing fermé de bascule des
gestes. Pour que le même poing puisse les réactiver, l'état désactivé doit garder
une veille HandLandmarker lente et bornée ; il ne doit jamais modifier la v3.

### 8.7 Jalon matériel controls-v4 : 25 fps, poing et recentrage

Gate réel One Pro + Eye/S24 validé le 31 juillet 2026. Le gain est matériellement
visible et toutes les fonctions de controls-v3 restent vertes :

- l'Atelier tourne à 25 fps de reconnaissance, toujours en 768 px ;
- le reliquat temporel du gate C# est conservé : 25 fps demandés ne retombent
  plus artificiellement à 15 fps sur une source Eye à 30 fps ;
- un pinch brut très profond peut engager avant la convergence de l'EMA, tandis
  que les pinchs ambigus gardent le filtrage anti-faux-clic ;
- déplacement et resize sont sensiblement plus rapides et fluides ;
- un poing fermé tenu bascule réellement gestes actifs/veille ;
- la veille conserve actuellement un sentinel HandLandmarker à 3 fps afin que
  le même poing puisse réactiver les gestes ;
- le bouton visible de recentrage remet réellement le pupitre face à
  l'utilisateur, et Réduire/paume restent fonctionnels.

Artefact matériel validé, à ne jamais écraser :

```text
apps/xr-mobile/build/android/mlomega-xreal-world-atelier-controls-v4.apk
taille = 223803706 octets
sha256 = 6B3F106E06197219141BC7EAD77D14E6C4FBB01B0C9D07DDED9DDDC479313F36
```

Raffinements à faire seulement dans une variante ultérieure, jamais directement
sur ce jalon :

1. sur l'APK produit plus chargée, conserver 25 fps uniquement lorsque les
   gestes sont actifs et mesurer température/batterie avant validation ;
2. réduire le sentinel de veille de 3 à 1 fps, masquer aussi rayon/curseur Eye,
   mais laisser le repli téléphone disponible lorsqu'il est réellement touché ;
3. afficher un toast world-space court `GESTES EN VEILLE` / `GESTES ACTIFS`, car
   le texte de statut dans le pupitre seul n'est pas suffisamment visible ;
4. pendant un transport 360°, appliquer le lacet de tête mais reconstruire la
   rotation du pupitre avec `Vector3.up`. Ne jamais persister le roll/pitch qui
   peut laisser le panneau incliné comme `/` après relâchement ;
5. la paume recentre déjà le pupitre dans la direction actuellement regardée,
   y compris vers le haut. Retirer le bouton `↻` visible devenu redondant, ou le
   remplacer par une affordance discrète révélée seulement par le regard.

## 9. APK produit : travail explicitement restant

Après correction et preuve de l'Atelier :

1. appliquer uniquement les réglages prouvés au scope `BuildApk` ;
2. vérifier que le profil réseau LAN/Tailscale reste présent ;
3. vérifier Eye, 6DoF, UI transparente et clic ;
4. vérifier que FreeGuy dynamique/ancré, Viki, Memory, capture et fin de session
   continuent de fonctionner ;
5. refaire un build PhoneOnly de non-régression seulement si le scope XREAL a
   touché un fichier partagé ;
6. ne cocher le matériel qu'après receipts/effets visibles.

Le fait que l'Atelier soit une APK séparée ne dispense pas ce second gate :
elles partagent des composants UI et un builder, mais pas la même scène ni la
même charge runtime.

## 10. Fichiers de build à ne pas committer

Après une passe Unity, contrôler au minimum :

```powershell
git status --short
git diff -- apps/xr-mobile/Packages
git diff -- apps/xr-mobile/ProjectSettings
git diff -- apps/xr-mobile/Assets/Plugins/Android/AndroidManifest.xml
git diff -- apps/xr-mobile/Assets/Scenes/PhoneOnly.unity
```

Résidus habituels à restaurer s'ils viennent bien de la passe courante :

- `Packages/manifest.json`, `Packages/packages-lock.json` ;
- `ProjectSettings/GraphicsSettings.asset`,
  `ProjectSettings/QualitySettings.asset`,
  `ProjectSettings/ProjectSettings.asset`,
  `ProjectSettings/EditorBuildSettings.asset`,
  `ProjectSettings/ShaderGraphSettings.asset` ;
- `Assets/XR/*`, `Assets/Settings/XREAL/*`, samples importés ;
- manifeste Android injecté ;
- scènes générées ;
- XML de tests, screenshots, APKs temporaires et dossiers `tmp_*`.

Ne pas restaurer un fichier simplement parce qu'il est sale : vérifier qu'il
s'agit d'un résidu de cette passe et pas d'une modification utilisateur.

## 11. Définition de fini

Le chantier XREAL n'est fini que lorsque :

- DeX est absent sans manipulation fragile ;
- Atelier et produit ont un fond optique transparent/noir, jamais violet ;
- le menu est stable en 6DoF ;
- contrôleur ou main réalise réellement focus/clic ;
- le fallback téléphone déclenche réellement la même action ;
- menu déplaçable/resizable ;
- création, suppression, export et recharge d'une map sont prouvés ;
- l'APK produit conserve ses ponts live/mémoire ;
- PhoneOnly et runners PC restent inchangés ;
- APKs, logs, versions et hashes du gate matériel sont conservés.

Au 31 juillet 2026, DeX/template, 6DoF, Eye, contrôleur IMU, framerate,
world-lock, transparence optique, clic Atelier, pinch main MediaPipe,
déplacement et redimensionnement sont verts sur S24 + One Pro + Eye. Restent
l'optimisation de latence/fluidité, les contrôles réduire/fermer et rappel par
paume, puis la parité de l'APK produit.
