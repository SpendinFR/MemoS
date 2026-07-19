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

### Gate PRO : préflight et harnais dans le même environnement

Le reçu profond contient un fingerprint exact. Pour un Gate PRO détaché, le wrapper doit
poser toutes les variables, lancer le préflight puis le harnais **dans le même script
PowerShell**. Un préflight exécuté dans un autre terminal peut être entièrement vert mais
sera refusé par SessionHub (`deep_preflight_receipt mismatch`). Le budget du fingerprint
doit également être identique à `--cloud-budget-eur`.

```powershell
$env:MLOMEGA_GPU_PHASE_ORCHESTRATION="1"
$env:MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING="1"
$env:MLOMEGA_PRO_CLOSEDAY="1"
$env:MLOMEGA_CLOUD_MODE="pro"
$env:MLOMEGA_PRO_TEXT_MODEL="deepseek-v4-pro"
$env:MLOMEGA_DEEP_AUDIO_TRANSCRIBER="groq"
$env:MLOMEGA_GROQ_WHISPER_MODEL="whisper-large-v3"
$env:MLOMEGA_CLOUD_VLM_PROVIDER="gemini"
$env:MLOMEGA_GEMINI_VLM_MODEL="gemini-3.1-flash-lite"
$env:MLOMEGA_CLOUD_DAILY_BUDGET_EUR="1.48"
$env:MLOMEGA_CLOUD_ON_BUDGET="stop"

Remove-Item Env:OPENAI_API_KEY,Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY `
  -ErrorAction SilentlyContinue

.\.venv-live\Scripts\python.exe scripts\check_phoneonly_readiness.py `
  --person-id me --deep
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Lancer run_harness.py --pro ici, sans ouvrir un nouveau shell et avec :
# --cloud-budget-eur 1.48 --cloud-on-budget stop
```

Champs qui doivent correspondre : personne, backend/URL/alias/contexte P1, modèle live,
VLM, orchestration GPU, flag PRO, modèles DeepSeek/Groq/Gemini, budget et politique. Ne pas
éditer le reçu pour les aligner : recréer le reçu avec le véritable environnement du run.

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

## 11. Préflight : échecs connus et correction

Le code de sortie harnais **3** avec `server not pairing_ready` signifie que SessionHub a
bien démarré mais qu'au moins un check de la chaîne IA est rouge. Ce code ne désigne pas un
check particulier. Si le log du harnais tronque le JSON avant le champ rouge, relancer le
préflight direct ci-dessous : il donne le rapport complet et ne lance aucune capture.

```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
.\.venv-live\Scripts\python.exe scripts\check_phoneonly_readiness.py --person-id me --deep
```

Ne pas modifier le code tant que le nom exact du check `ok: false` n'est pas connu.

| Check/symptôme | Cause habituelle | Vérification et correction |
|---|---|---|
| Proxy `127.0.0.1:9`, loopback mort, timeout HF/cloud | Variable proxy héritée d'un runner isolé | `Get-ChildItem Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY`; supprimer les trois variables pour le processus avec la commande ci-dessus. `RUN_MLOMEGA_V19.ps1` retire déjà les blackholes connus. |
| `hf_pyannote_access_cache=false` | Token absent/mauvais compte, licence gated non acceptée ou cache incomplet | Mettre `MLOMEGA_HF_TOKEN=...` dans `.env`; accepter `pyannote/speaker-diarization-3.1` et `pyannote/segmentation-3.0` avec le même compte; puis `.\.venv\Scripts\python.exe scripts\PREFETCH_FIRSTTRY_MODELS.py`. Le préflight produit ne télécharge rien. |
| `night_asr_cache=false` | Snapshot Faster-Whisper nocturne absent/incomplet | Exécuter `.\.venv\Scripts\python.exe scripts\PREFETCH_FIRSTTRY_MODELS.py`, puis relancer le préflight; ne pas attendre la fin d'une session pour télécharger. |
| `llm_process_consistency=false` avec backend Ollama | Ancien `llama-server` encore sur le port 8080 et VRAM occupée | Vérifier `Invoke-RestMethod http://127.0.0.1:8080/props`. Fermer le serveur orphelin ou utiliser la configuration llama.cpp complète. Pour un run normal, laisser l'orchestrateur démarrer/arrêter P1. |
| Alias P1 incorrect | `model_alias` servi différent de `MLOMEGA_LLAMACPP_MODEL` | Comparer `/props` avec `MLOMEGA_LLAMACPP_MODEL`; redémarrer via l'orchestrateur avec l'alias exact. Ne pas accepter `generic`, un ancien P1/P3 ou changer les checkpoints pour contourner le mismatch. |
| `llm_context_budget=false` | Contexte du serveur différent de `MLOMEGA_OLLAMA_CONTEXT_POSTSTOP`/configuration P1 | Lire `default_generation_settings.n_ctx` dans `/props`; redémarrer P1 avec le contexte attendu. Ne pas baisser les budgets métier pour faire verdir le check. |
| `llm_json_contract=false` | Mauvais modèle, thinking actif, endpoint/format JSON incorrect | Vérifier alias et contexte, puis laisser le préflight refaire son probe anti-thinking/JSON. Ne pas assouplir le schéma ni accepter une sortie texte. |
| Ollama indisponible/modèle absent | Application Ollama arrêtée ou modèle non installé | Vérifier `Invoke-RestMethod http://127.0.0.1:11434/api/ps` et `ollama list`; ouvrir/démarrer Ollama puis relancer le préflight. Ne pas charger manuellement 4B, 9B et VLM ensemble. |
| `qdrant=false` | Service 6333 arrêté | `& .\scripts\START_QDRANT.ps1 -TimeoutSec 30`, puis `Invoke-RestMethod http://127.0.0.1:6333/collections`. RUN effectue déjà ce démarrage. |
| VLM/9B encore résident | Un probe précédent a laissé Qwen-VL ou un 9B dans Ollama | Vérifier `Invoke-RestMethod http://127.0.0.1:11434/api/ps`. Fermer l'autre job et relancer le préflight : `prepare_live_gpu` doit évincer tout sauf le 4B live. Ne pas lancer un Gate concurrent. |
| `prepare_live_gpu=false` ou VRAM insuffisante | P1/VLM orphelin, autre application GPU ou caches Python lourds | Exécuter `nvidia-smi`; fermer le processus concurrent, puis relancer. Le seuil P1 local est normalement 6000 MiB libres (`MLOMEGA_P1_MIN_FREE_VRAM_MB`); ne pas le réduire uniquement pour passer le gate. |
| `preflight_receipt` absent/périmé/mismatch | Aucun `--deep`, reçu de plus de 24 h, autre personne/modèle/backend/budget | Ne pas éditer `storage/runtime/phoneonly_readiness.json`. Relancer `check_phoneonly_readiness.py --person-id me --deep` avec exactement l'environnement du futur serveur. Le reçu contient un fingerprint et le TTL par défaut vaut 86400 s. |
| `torch_cuda_execution=false` ou cuDNN absent | Mauvais venv, PATH CUDA incomplet ou pilote/torch incohérent | Utiliser `.venv` pour le préflight nocturne et lancer le produit par `RUN_MLOMEGA_V19.ps1`, qui prépare les DLL. Corriger l'installation; ne pas basculer silencieusement le pipeline sur CPU. |
| `db=false` | `MLOMEGA_DB` absent, mauvais fichier ou SQLite invalide | Vérifier la DB exacte du run et `PRAGMA quick_check`; ne jamais pointer le harnais/dashboard vers une DB différente pour obtenir un vert. |

Ordre conseillé après un code `3` : préflight direct → lire le premier check rouge → appliquer
une seule correction de la table → relancer uniquement le préflight → lancer le Gate une
seule fois lorsqu'il est entièrement vert.

## 12. Incidents déjà rencontrés pendant les runs

Ces symptômes ont déjà coûté des relances longues. Les comportements corrects sont
désormais codés; leur retour indique d'abord un mauvais lancement, une concurrence externe
ou une régression à isoler — pas une raison d'abaisser les gates.

| Symptôme observé | Cause déjà rencontrée | Réaction correcte |
|---|---|---|
| Harnais code `3`, JSON de `/health` coupé après ~800 caractères | Le rapport final est tronqué avant le check rouge | Ne pas deviner. Lancer le préflight direct `--deep`, qui imprime tous les checks. Le code `3` signifie seulement « jamais pairing_ready ». |
| 10–50 tests live rouges instantanément | Toute la suite lancée avec `.venv` | Relancer `tests/v19` ou les suites PhoneOnly avec `.venv-live`. Une absence de `webrtcvad`/aiortc est un mauvais venv, pas un bug produit. |
| Port 8710/8730 occupé ou résultats d'un ancien run | SessionHub/harness précédent encore vivant | `Get-NetTCPConnection -LocalPort 8710,8730 -ErrorAction SilentlyContinue`; identifier le PID propriétaire. Ne jamais tuer un processus sans vérifier sa commande et ne jamais partager une DB entre deux runs. |
| `/session/end` paraît bloqué plusieurs minutes | Ancienne frontière attendait receipts/fine-intel/ASR avant de répondre | Le produit actuel répond après le drain brut court et crée un job durable; surveiller `/session/status`, `current_stage`, `inflight_seconds` et la recovery. Ne pas simplement augmenter les timeouts ni lancer CloseDay manuellement en parallèle. |
| File audio énorme, chunks perdus, ASR en retard | VLM ou P1 occupait la VRAM pendant le live | Vérifier `/api/ps`, port 8080 et `nvidia-smi`; `prepare_live_gpu` doit laisser uniquement le 4B live. Ne pas agrandir la file pour masquer la famine GPU. |
| HTTP 404 pendant fine-intel/drain | Client destiné à Ollama avait hérité de l'alias P1/llama.cpp | Les consommateurs live doivent construire `OllamaJsonClient(backend="ollama", model=<4B live>)`. Ne pas créer/modifier un alias Ollama portant le nom P1 pour contourner le 404. |
| Commande mémoire/aide finit après fermeture, réponse supprimée | Appel live parti par erreur sur P1 nocturne ou modèle trop lent | Le live doit rester Ollama 4B avec override limité au worker; contrôler traces `accepted → completed|failed`, `response_suppressed` et latence. Ne pas envoyer DeepSeek/P1 dans le live via une variable globale. |
| `--pro` lancé mais aucun ledger/cloud ou P1 local traite toute la nuit | Flag CLI non propagé à `MLOMEGA_PRO_CLOSEDAY=1` | Vérifier le rapport de lancement et l'environnement enfant. Utiliser les commandes RUN/harness de cette fiche; ne pas simuler PRO en posant seulement `MLOMEGA_LLM_BACKEND=deepseek`. |
| Checkpoints se collisionnent ou portent un modèle `generic` | Alias modèle absent/non déterministe dans la clé de checkpoint | Stopper avant reprise payante. L'alias exact P1/DeepSeek doit participer aux digests; ne jamais renommer manuellement des checkpoints. |
| DeepSeek affiche 454k tokens pour cinq minutes | Somme logique du même préfixe envoyé à plusieurs moteurs | Lire `cache_hit_tokens` et `cache_miss_tokens` dans `cloud_cost_ledger_v19`. Majoritairement hit = attendu et peu coûteux; majoritairement miss = préfixe/warm-up cassé. Ne pas juger sur le total seul. |
| Plusieurs gros appels DeepSeek miss en même temps | Tous les moteurs sont partis avant propagation du warm-up | Un warm-up par épisode, puis une seule barrière de propagation, ensuite fan-out 8–12. Vérifier les hits réels; réduire le fan-out/backoff sur 429, sans fusionner plusieurs moteurs en un gros JSON. |
| Ligne cloud reste `reserved` après kill | Crash avant que le provider marque l'envoi | La recovery libère seulement un `reserved` dont la non-émission est prouvée. `in_flight` sans réponse devient `uncertain` et reste compté. Ne jamais éditer le ledger à la main. |
| DeepSeek/Gemini/Groq 429 ou 5xx | Charge fournisseur ou trop de requêtes simultanées | Laisser le sémaphore et le backoff exponentiel agir; ne pas lancer un deuxième Gate. Un appel déjà possiblement envoyé reste compté conservativement. |
| JSON LLM tronqué, `finish_reason=length` ou contrat rejeté | Sortie trop grande ou modèle ayant omis une preuve obligatoire | Rejet intégral, réparation ciblée puis split/merge lossless et checkpoint. Ne jamais appliquer un JSON partiel, réduire la couverture ou augmenter aveuglément le timeout. |
| Gemini/Qwen-VL sélectionne N images mais en analyse moins | JSON vide/tronqué, pixel absent ou writer non persisté | Exiger toujours `selected = readable = analyzed`. Réparation/retry borné; aucune frame ne disparaît pour obtenir `complete=1`. |
| Qwen-VL retourne `response` vide mais beaucoup de `thinking` | Comportement déjà observé sur un build Ollama malgré `think:false` | Le parser produit connaît ce cas et valide toujours le JSON strict. S'il réapparaît sous une nouvelle version, diagnostiquer le payload brut/quarantaine; ne pas accepter `{}` comme succès. |
| CloseDay DB `completed` mais processus exit 1 | Ancien stdout Windows CP1252 échouait après le commit Unicode | Vérifier d'abord le statut durable et les manifests. Le CLI actuel force UTF-8; le retour de ce symptôme est une régression d'encodage, pas une autorisation à rejouer toute la nuit. |
| Dashboard montre données anciennes/incohérentes | `MLOMEGA_DB` pointe vers une autre DB | Fermer/repartir avec la commande section 7 et afficher le chemin résolu. Ne jamais corriger les writers en observant la mauvaise base. |
| Run repris recalcule tout | IDs/digests/modèle/contexte différents, ou mauvaise DB | Comparer le run ID, conversation ID, modèle exact, prompt hash et DB. Une reprise saine réutilise les checkpoints `completed`; ne pas copier les lignes entre DB. |
| Unity semble « bloqué » ou `$LASTEXITCODE` vide | Unity GUI lancé avec `&` ou sans attente | Utiliser `Start-Process -Wait -PassThru -NoNewWindow`; une seule instance/projet. Pour tests EditMode, ne pas ajouter `-quit`. |
| Unity affiche des erreurs Licensing mais produit l'APK | Bruit client licence 500/ULF/cache | Verdict = exit code + fin du log. Si `Build succeeded`, ne pas diagnostiquer une panne de licence. Si `No valid Unity Editor license`, ouvrir Hub connecté puis relancer. |
| Build XREAL : manifest JSON invalide ou namespace XREAL absent | Manifest altéré ou passe `PrepareDefines` non exécutée | Repartir d'un manifest JSON propre après inspection, vérifier le tarball, exécuter PrepareDefines puis BuildApk. Reverter ensuite seulement les artefacts listés en section 8. |

Quand un incident n'est pas dans ces tables : conserver DB/logs/exit code, ouvrir le premier
traceback ou le premier check rouge, puis ajouter le nouveau cas ici après correction et
preuve. L'objectif est qu'une panne comprise une fois ne coûte jamais une deuxième enquête.
