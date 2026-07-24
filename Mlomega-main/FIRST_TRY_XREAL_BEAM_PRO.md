# Première utilisation — XREAL One Pro + Eye + Beam Pro

Ce guide est le chemin opérateur courant pour utiliser MLOmega avec :

- un PC Windows qui exécute le Live, BrainLive et CloseDay ;
- un XREAL Beam Pro comme hôte Android ;
- des XREAL One Pro avec le module XREAL Eye ;
- l'APK `apps\xr-mobile\build\android\mlomega-xreal.apk`.

Le Beam exécute Unity/XREAL, l'interface, la capture Eye, WebRTC et les réflexes
locaux. Les traitements lourds restent sur le PC. Le profil livré essaie le PC
dans cet ordre :

1. LAN : `192.168.1.199:8710` ;
2. Tailscale : `100.113.42.19:8710`.

L'APK courante est `com.mlomega.xr.glasses`, SHA-256
`EFA4AEC207CA2BFB1602FDDB39D348447F75B560DE475A8CE1D4160405C891C9`.

## 1. Préparation unique du Beam et des lunettes

1. Mets à jour le Beam Pro et l'application XREAL **MyGlasses**
   (appelée ControlGlasses sur certaines versions).
2. Monte le module Eye sur les One Pro, puis mets à jour le firmware des
   lunettes et de l'Eye. Au besoin, utilise l'outil officiel
   <https://www.xreal.com/ota>.
3. Installe Tailscale sur le Beam, connecte-le au même tailnet que le PC et
   laisse le VPN actif. Le Beam Wi-Fi a besoin d'un Wi-Fi ou d'un partage de
   connexion dehors ; le modèle 5G peut utiliser son réseau mobile.
4. Dans Android, retire l'optimisation batterie pour MLOmega, MyGlasses et
   Tailscale. Autorise caméra, micro et affichage par-dessus les autres apps.
5. Active les options développeur et le débogage USB sur le Beam.

Sur le PC :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
adb devices
adb install -r apps\xr-mobile\build\android\mlomega-xreal.apk
adb shell pm path com.mlomega.xr.glasses
```

`adb devices` doit montrer le Beam avec l'état `device`. Accepte l'empreinte RSA
sur le Beam si Android la demande.

Branchement quotidien :

1. branche les One Pro au port lunettes du Beam avec le câble d'origine ;
2. branche l'alimentation sur l'autre port USB-C si la session doit durer ;
3. lance MLOmega depuis MyGlasses, pas depuis une ancienne icône APK ;
4. vérifie que l'Eye est bien détectée. Sans Eye, l'app reste volontairement en
   mode pose-only et aucune vidéo lunettes n'est envoyée.

Le mode capture-only vertical est prévu : la rotation des lunettes est portée
avec chaque frame et corrigée avant Vision/OCR. Si les lunettes sont accrochées
verticalement, le bandeau doit indiquer `capture-only`.

## 2. Lancer le PC — mode Local

Ferme toute ancienne instance de MLOmega, puis ouvre PowerShell :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
ollama list
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

Le lanceur démarre/vérifie Qdrant lui-même. Ollama doit déjà répondre ; s'il est
arrêté, ouvre l'application Ollama ou lance `ollama serve`, puis relance RUN.

RUN effectue le préflight profond : DB, modèles, Hugging Face/Pyannote,
CUDA/cuDNN, Whisper, YOLOX, VLM, Ollama, Qdrant, espace disque et environnement
CloseDay. Ne contourne pas un check rouge : suis la ligne `[FIX]`. Attends :

- `pairing_ready=true` ;
- `ai_ready=true` ;
- `http://localhost:8710/ready` en HTTP 200.

Garde cette console ouverte pendant toute la capture et tout CloseDay. Le
pare-feu Windows doit autoriser Python sur le réseau privé et le port TCP 8710.

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
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -Pro -ProTextModel pro `
  -CloudBudgetEur 1.50 -CloudOnBudget stop `
  -BindHost 0.0.0.0 -Port 8710
```

Pour réduire le coût au prix d'une analyse moins profonde, remplace
`-ProTextModel pro` par `-ProTextModel flash`. `-CloudOnBudget stop` est le
choix sûr : aucune dépense au-delà du plafond.

## 4. Vérifier LAN et Tailscale avant la capture

Sur le Beam, dans un navigateur :

- à la maison : `http://192.168.1.199:8710/ready` ;
- hors du LAN : `http://100.113.42.19:8710/ready`.

La page doit indiquer la chaîne IA prête. Si le LAN échoue mais Tailscale
répond, l'app bascule sur Tailscale. Si les deux échouent :

```powershell
tailscale status
tailscale ip -4
Test-NetConnection 127.0.0.1 -Port 8710
```

Vérifie aussi que le Beam et le PC sont dans le même tailnet et que le Beam
n'utilise pas un exit node qui bloque le LAN.

## 5. Première session sur le Beam

1. Lance d'abord le PC et attends le préflight vert.
2. Branche Eye + One Pro, puis ouvre MLOmega depuis MyGlasses.
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

Les scénarios vocaux complets restent décrits dans
[`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md). Ils utilisent les mêmes routes
PC, BrainLive et UI sur le Beam.

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

Sur l'écran du Beam/MLOmega, touche :

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

Si le Beam ou le PC crashe, conserve la DB et les logs puis relance exactement
la même commande RUN. La recovery reprend le job durable et bloque CloseDay
plutôt que de déclarer un faux succès. Ne lance pas manuellement un second
CloseDay sur une session encore active.

Quand `close_day=completed`, arrête le serveur par `Ctrl+C`, quitte MLOmega dans
MyGlasses et débranche les lunettes.

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

## 9. Diagnostic lunettes/Beam

Avec le Beam relié en ADB :

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

- **Pairing bloqué** : vérifie `/ready` depuis le Beam, pare-feu, LAN/Tailscale,
  puis relance d'abord le PC.
- **Eye absente** : remonte le module, mets firmware/MyGlasses à jour, utilise le
  câble d'origine et redémarre le Beam.
- **UI noire ou non stéréo** : lance depuis MyGlasses et non depuis le launcher
  Android ; vérifie les permissions overlay.
- **Téléchargement modèle bloqué** : garde l'app au premier plan et le Beam
  alimenté jusqu'à la fin de `dl:`.
- **CloseDay `error`/`blocked`** : ne supprime rien ; relance RUN pour recovery et
  conserve la console ainsi que la DB.

Références constructeur :

- SDK/tested devices : <https://developer.xreal.com/download/>
- démarrage XREAL SDK : <https://docs.xreal.com/Getting%20Started%20with%20XREAL%20SDK>
- guide XREAL Eye : <https://tutorials.xreal.com/docs/accessories/eye/>
- Beam Pro : <https://us.shop.xreal.com/products/xreal-beam-pro>
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
