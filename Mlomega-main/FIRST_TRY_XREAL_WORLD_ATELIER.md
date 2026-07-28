# Première utilisation — XREAL World Atelier

Ce guide crée un décor FreeGuy/Blade Runner dans l'APK Atelier, l'exporte, puis
le charge dans l'APK XREAL principale. Les deux applications restent séparées :
l'Atelier n'ouvre ni micro, ni Eye WebRTC, ni Memory, ni session PC.

## 1. Installer les deux APK

Depuis `apps\xr-mobile`, S24 branché en USB et débogage USB autorisé :

```powershell
adb install -r build\android\mlomega-xreal-world-atelier.apk
adb install -r build\android\mlomega-xreal.apk
```

Packages attendus :

- Atelier : `com.mlomega.xr.worldatelier`;
- produit : `com.mlomega.xr.glasses`.

Les deux doivent être lancés depuis ControlGlasses avec la One Pro/Eye branchée,
pas dans DeX et pas comme une application 2D ordinaire.

## 2. Créer un monde

1. Lance **MLOmega World Atelier** depuis ControlGlasses.
2. Attends `ANCRAGE PRÊT`. Tant que le mesh Depth ou le provider d'ancres XREAL
   manque, le bouton d'ancrage refuse proprement l'opération.
3. Sur le pupitre 3D, choisis une catégorie puis un preset. Le catalogue combine
   plus de 3 000 variations : enseignes, néons, vitrines, écrans, portails,
   totems, drones, hologrammes géants, flèches, particules et widgets maison.
4. Saisis titre/sous-titre, ajuste taille et rotation. Pour un logo personnel,
   utilise `IMPORTER LOGO` et choisis un PNG/JPEG de moins de 512 Kio.
5. Regarde la surface réelle visée et touche `ANCRER DANS LE MONDE`. Le contenu
   n'est sauvegardé qu'après hit Depth, ancre suivie et sauvegarde XREAL réussie.
6. Déplace-toi et recommence. `ANNULER DERNIER` efface aussi l'ancre native.
   `RECENTRER PUPITRE` rapproche seulement le pupitre d'édition; il ne déplace
   jamais les contenus déjà ancrés.

Les contenus sont world-space : ils gardent position, hauteur, orientation et
échelle. Aucun fallback ne les colle au regard si la relocalisation est perdue.

## 3. Exporter

Touche `EXPORTER MONDE`, choisis un fichier avec le sélecteur Android, puis
conserve le `.json`. Le paquet contient :

- carte et poses des contenus;
- paramètres visuels et logos bornés;
- GUID et fichiers de mapping natifs XREAL;
- SHA-256 du paquet, des images et des mappings.

Un mapping manquant, trop gros ou illisible bloque l'export : ne contourne pas
ce refus, sinon l'autre APK ne pourrait pas relocaliser le décor.

## 4. Importer dans l'APK produit

1. Lance l'APK `MLOmega XREAL` normale.
2. Ouvre le menu et touche `Importer monde`, ou dis :
   `VIKI, importe mon monde ancré`.
3. Choisis le paquet exporté.
4. Active `FreeGuy ancré`, ou dis :
   `VIKI, active le mode FreeGuy ancré`.

L'APK installe les mappings dans son propre stockage, recharge les ancres, puis
n'affiche que celles revenues en état `Tracking`. Pour cumuler les décors
persistants avec les effets VisionRT éphémères, active aussi
`FreeGuy dynamique`. Les deux modes sont indépendants.

## 5. Preuve matérielle obligatoire

Avant de considérer une carte terminée :

1. ancre 3 objets proches et 2 contenus mur/façade;
2. marche jusqu'à les sortir du champ;
3. ferme complètement les deux APK;
4. redémarre le S24 et les lunettes;
5. importe/recharge puis reviens au même endroit;
6. vérifie position, hauteur, rotation, échelle, occlusion et absence de
   head-lock;
7. teste 20 minutes avec 6–12 contenus visibles et note FPS/chauffe/batterie.

La compilation et les tests logiciels valident le format et les refus; seul ce
test valide la relocalisation réelle du firmware XREAL.

## 6. Rebuild développeur

Ferme toute fenêtre Unity. Depuis `apps\xr-mobile` :

```powershell
$u = "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines', `
  '-logFile',"$pwd\xreal-prep.log" -Wait -PassThru -NoNewWindow
"prep=$($p.ExitCode)"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.BuildCreatorApk', `
  '-logFile',"$pwd\world-atelier-build.log" -Wait -PassThru -NoNewWindow
"atelier=$($p.ExitCode)"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.', `
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.BuildApk', `
  '-logFile',"$pwd\xreal-build.log" -Wait -PassThru -NoNewWindow
"produit=$($p.ExitCode)"
```

Sorties :

- `build\android\mlomega-xreal-world-atelier.apk`;
- `build\android\mlomega-xreal.apk`.

Après le build, restaurer uniquement les artefacts Unity injectés par la passe
XREAL (`Packages/manifest.json`, `packages-lock.json`, réglages XR/ProjectSettings)
selon le runbook. Ne jamais utiliser `git add -A`.
