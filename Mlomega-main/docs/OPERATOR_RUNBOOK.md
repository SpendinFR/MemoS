# MLOmega V19 — commandes opérateur sans pièges

Cette fiche est la référence courte pour lancer, tester et diagnostiquer MLOmega sur la
machine Windows cible. Elle évite les faux diagnostics causés par un mauvais environnement,
un processus GPU concurrent, un proxy mort ou une commande Unity non bloquante.

Toutes les commandes sauf la section Git partent de :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
```

## 1. Choisir le bon Python

| Usage | Interpréteur obligatoire |
|---|---|
| SessionHub, PhoneOnly, WebRTC, AudioRT, VisionRT, harnais, suite V19 complète | `.venv-live\Scripts\python.exe` |
| CloseDay, mémoire nocturne et tests core explicitement ciblés | `.venv\Scripts\python.exe` |
| Unity/Android | Unity Editor 6000.0.23f1, pas Python |

Règle : **ne jamais lancer tout `tests/v19` avec `.venv`**. Ce venv ne contient pas toutes
les dépendances live (`webrtcvad`, aiortc, etc.) et produit des dizaines de faux rouges.
La suite V19 complète se lance avec `.venv-live`, qui contient aussi le code `src`.

Symptôme typique d'une mauvaise commande : beaucoup de tests PhoneOnly/wake-word échouent
dès la construction d'`AudioRT` avec `ModuleNotFoundError: webrtcvad`. Cela ne prouve aucune
régression produit. Relancer avec `.venv-live` avant de modifier le code.

Toujours ouvrir le **premier traceback complet** avant de lire seulement les vingt dernières
lignes :

```powershell
.\.venv-live\Scripts\python.exe -m pytest <test> -vv --tb=long -x -p no:cacheprovider
```

## 2. Lancer le produit local

Le lanceur choisit `.venv-live` en priorité, vérifie toutes les dépendances, exécute le
préflight profond, prépare GPU/Ollama/P1 puis démarre Companion et SessionHub.

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -PersonId me -BindHost 0.0.0.0 -Port 8710
```

Ne pas démarrer manuellement P1 et plusieurs modèles Ollama avant cette commande :
l'orchestrateur GPU gère leur résidence par phase. Le CloseDay enfant utilise `.venv` de
façon intentionnelle; le live reste dans `.venv-live`.

Simulation sans téléphone :

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -SimOnly
```

## 3. Lancer le profil PRO

Les clés restent exclusivement dans `.env`, ignoré par Git :

```dotenv
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

Ne jamais mettre une clé dans une commande, un log, une DB, une documentation ou un commit.

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -Pro `
  -CloudBudgetEur 1.50 -CloudOnBudget stop `
  -PersonId me -BindHost 0.0.0.0 -Port 8710
```

Sans `-Pro`, aucun provider cloud ni fan-out PRO ne doit être actif. Avec `-Pro`, le live
reste local; seule la consolidation nocturne est cloud. `stop` est la politique recommandée
tant que le Gate PRO n'est pas validé.

Avant tout run payant, lire `docs/PRO_CLOSEDAY_HANDOFF.md`. Ne jamais effacer manuellement
une ligne `reserved`, `in_flight` ou `uncertain` du ledger cloud pour récupérer du budget.

## 4. Préflight et état du serveur

Préflight produit profond, avec le même Python que SessionHub :

```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
.\.venv-live\Scripts\python.exe scripts\check_phoneonly_readiness.py --person-id me --deep
```

Le lanceur `RUN_MLOMEGA_V19.ps1 -LivePhone` exécute déjà ce préflight. Il est inutile de le
doubler juste avant RUN, sauf diagnostic ciblé.

Préflight CloseDay direct, uniquement pour diagnostiquer l'environnement nocturne :

```powershell
.\.venv\Scripts\python.exe scripts\check_close_day_preflight.py --json
```

État HTTP après démarrage :

```powershell
Invoke-RestMethod http://127.0.0.1:8710/health
Invoke-RestMethod http://127.0.0.1:8710/ready
Invoke-RestMethod http://127.0.0.1:8710/metrics
```

`/health` prouve que le serveur répond; `/ready` et le reçu du préflight portent la preuve
IA complète. Ne pas confondre les deux.

## 5. Tests : commandes canoniques

Suite V19 complète :

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests\v19 -q -p no:cacheprovider
```

Ne pas masquer arbitrairement des tests avec `--ignore`/`--deselect`. Toute exclusion doit
être justifiée dans le rapport avec sa raison matérielle ou environnementale.

Smoke live critique — PhoneOnly, SessionHub, wake-word, TTS, commandes et spatialisation :

```powershell
.\.venv-live\Scripts\python.exe -m pytest `
  tests\v19\test_phoneonly_runtime.py `
  tests\v19\test_sessionhub_http.py `
  tests\v19\test_wake_word_gating.py `
  -q -p no:cacheprovider
```

Référence du 20 juillet 2026 : **70 tests verts** dans `.venv-live`. La même sélection
lancée par erreur dans `.venv` produisait 46 faux échecs.

Tests core/PRO sans réseau, explicitement compatibles avec `.venv` :

```powershell
Remove-Item Env:MLOMEGA_PRO_CLOSEDAY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest `
  tests\v19\test_cloud_pro_v19.py `
  tests\v19\test_e64i_conversation_episode.py `
  tests\v19\test_e64i_long_conversation.py `
  tests\v19\test_e64f_wiring.py `
  tests\v19\test_e64f_brain2_blocks.py `
  -q -p no:cacheprovider
```

Ne jamais conclure « préexistant » après avoir seulement stashé les modifications courantes :
cela compare au commit actuel, pas à son parent. Pour attribuer une régression, exécuter le
même test, avec le même venv, sur les deux commits dans un checkout/worktree propre.

## 6. Harnais produit

Le harnais doit toujours utiliser `.venv-live`; il démarre le vrai SessionHub et le vrai
transport. Les DB/logs sous `tools/harness/_run` sont des artefacts ignorés, jamais à
committer.

Gate local sur la vidéo de référence :

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
.\.venv-live\Scripts\python.exe tools\harness\run_harness.py `
  --port 8730 --with-close-day `
  --media tools\harness\_run\real_video_clean.mp4 `
  --scenario tools\harness\scenarios\real_video_session.json --duration 305 `
  --db "tools\harness\_run\gateb-local-$stamp.db" `
  --out "tools\harness\_run\gateb-local-$stamp.json"
```

Gate PRO, uniquement après tests fake/local verts et préflight cloud :

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
.\.venv-live\Scripts\python.exe tools\harness\run_harness.py `
  --pro --cloud-budget-eur 1.50 --cloud-on-budget stop `
  --port 8730 --with-close-day `
  --media tools\harness\_run\real_video_clean.mp4 `
  --scenario tools\harness\scenarios\real_video_session.json --duration 305 `
  --db "tools\harness\_run\gateb-pro-$stamp.db" `
  --out "tools\harness\_run\gateb-pro-$stamp.json"
```

Ne jamais lancer simultanément deux SessionHub/harness sur le même port ou la même DB.

## 7. Dashboard sur une DB précise

```powershell
$env:MLOMEGA_DB = (Resolve-Path 'tools\harness\_run\<run>.db').Path
.\.venv-live\Scripts\python.exe -m streamlit run `
  .\apps\memory-dashboard\app.py --server.port 8720 --server.headless true
```

Puis ouvrir `http://127.0.0.1:8720`. Vérifier la valeur de `MLOMEGA_DB` avant de juger les
résultats : un dashboard ouvert sur une ancienne DB est un faux diagnostic fréquent.

## 8. Unity : tests et APK

Depuis `apps\xr-mobile`, une seule instance Unity peut ouvrir le projet. Utiliser
`Start-Process -Wait -PassThru`; `& Unity.exe` peut rendre la main trop tôt. Pour EditMode,
ne pas ajouter `-quit` avec `-runTests`.

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main\apps\xr-mobile
$u = "C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe"

$p = Start-Process $u -ArgumentList '-batchmode','-runTests','-testPlatform','EditMode',`
  '-projectPath','.','-testResults',"$pwd\editmode.xml",'-logFile',"$pwd\editmode.log" `
  -Wait -PassThru -NoNewWindow
"tests_exit=$($p.ExitCode)"

$env:MLOMEGA_PC_HOST="192.168.1.199"
$env:MLOMEGA_PC_PORT="8710"
$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.',`
  '-executeMethod','MLOmega.XR.Editor.AndroidBuild.BuildApk',`
  '-logFile',"$pwd\apk-phone.log" -Wait -PassThru -NoNewWindow
"phone_exit=$($p.ExitCode)"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.',`
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines',`
  '-logFile',"$pwd\xreal-prep.log" -Wait -PassThru -NoNewWindow
"xreal_prep_exit=$($p.ExitCode)"

$p = Start-Process $u -ArgumentList '-batchmode','-quit','-projectPath','.',`
  '-executeMethod','MLOmega.XR.Editor.AndroidBuildXreal.BuildApk',`
  '-logFile',"$pwd\xreal-build.log" -Wait -PassThru -NoNewWindow
"xreal_build_exit=$($p.ExitCode)"
```

Verdict Unity : exit code et `Build succeeded`/`Scripts have compiler errors`. Les lignes
Licensing `Error Code 500`, `No ULF` ou `Token not found` peuvent être du bruit. Si le vrai
verdict est `No valid Unity Editor license`, ouvrir Unity Hub connecté puis relancer.

Après le build XREAL, reverter uniquement les artefacts générés prévus, jamais les sources :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE
git checkout -- `
  Mlomega-main/apps/xr-mobile/ProjectSettings/ProjectSettings.asset `
  Mlomega-main/apps/xr-mobile/ProjectSettings/EditorBuildSettings.asset `
  Mlomega-main/apps/xr-mobile/Packages/packages-lock.json `
  Mlomega-main/apps/xr-mobile/Packages/manifest.json `
  Mlomega-main/apps/xr-mobile/Assets/XR/XRGeneralSettingsPerBuildTarget.asset
```

Ne pas appliquer ce revert si l'un de ces fichiers contient une modification utilisateur
intentionnelle non liée au build; inspecter `git diff` d'abord.

## 9. Git dans ce dépôt mixte

La racine Git est le parent `ProjetMemobyFABLE`, pas `Mlomega-main` :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE
git status --short
git add Mlomega-main\chemin\fichier1 Mlomega-main\chemin\fichier2
git diff --cached --check
git diff --cached --stat
git commit -m "type(scope): titre"
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
git push origin main
```

Toujours des chemins explicites; **jamais `git add -A`**. Ne pas committer `.env`,
`Oldconversation`, logs, modèles, `_run`, artefacts Unity ou modifications d'un autre agent.

## 10. Ordre de diagnostic rapide

1. Confirmer le dossier et l'interpréteur réellement utilisés.
2. Lire le premier traceback, pas seulement le résumé final.
3. Vérifier port/DB/processus et absence de deuxième instance.
4. Vérifier proxy, puis le préflight approprié.
5. Reproduire un seul test avec le bon venv.
6. Comparer au parent uniquement avec même commande et environnement.
7. Modifier le code seulement après preuve que l'échec suit le diff.
