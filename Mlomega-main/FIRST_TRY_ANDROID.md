# Première utilisation — PhoneOnly sur Galaxy S24

Ce document est le guide opérateur courant. Les anciennes sections v1–v5 ont
été retirées : elles décrivaient des APK historiques et se contredisaient.

Pour les XREAL One Pro + Eye, utilise
[`FIRST_TRY_XREAL_S24.md`](FIRST_TRY_XREAL_S24.md).
Pour valider toutes les commandes, gestes, fonctions Memory/UltraLive et leurs
preuves, utilise ensuite
[`A_TESTER_ALL_FEATURES_SCENARIOS.md`](A_TESTER_ALL_FEATURES_SCENARIOS.md).

## 1. Ce qui tourne où

Le S24 exécute l'app Unity, la caméra arrière, WebRTC, l'interface, les gestes,
le wake word, les sous-titres et la traduction Reflex. Le PC exécute VisionRT,
AudioRT, BrainLive, la mémoire et CloseDay.

L'APK PhoneOnly courante :

- fichier : `apps\xr-mobile\build\android\mlomega-phoneonly.apk` ;
- package : `com.mlomega.xr.phoneonly` ;
- taille : 113 613 566 octets ;
- SHA-256 :
  `6863B26CFD12E007E61128B409917A380C9398EB97056FD76A8CDF81D9E12C54` ;
- endpoints embarqués : LAN `192.168.1.199:8710`, puis Tailscale
  `100.113.42.19:8710`.

## 2. Préparation unique du S24

1. Installe Tailscale et connecte le S24 au même tailnet que le PC.
2. Dans Paramètres > Applications, retire l'optimisation batterie pour MLOmega
   et Tailscale.
3. Active les options développeur et le débogage USB.
4. Depuis la racine du projet :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
adb devices
adb install -r apps\xr-mobile\build\android\mlomega-phoneonly.apk
adb shell pm path com.mlomega.xr.phoneonly
```

Accepte l'empreinte RSA sur le S24. Au premier lancement, autorise caméra,
micro, notifications et affichage par-dessus les autres applications.

## 3. Base réellement fraîche — première production seulement

Ferme RUN et le Dashboard. Si l'ancienne base ne contient que des tests :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
$db = ".mlomega_audio_elite\memory.db"
Remove-Item -LiteralPath $db -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$db-wal","$db-shm" -Force -ErrorAction SilentlyContinue
Test-Path $db
```

Le résultat doit être `False`. Le prochain RUN recrée la base. Ne répète jamais
cette étape après avoir commencé à enregistrer ta vraie mémoire.

## 4. Lancer le PC — Local

Ferme les anciens serveurs MLOmega, puis :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
ollama list
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710
```

RUN démarre/vérifie Qdrant lui-même. Ollama doit déjà répondre ; sinon ouvre
Ollama ou lance `ollama serve`, puis recommence.

Le préflight contrôle DB, modèles, Hugging Face/Pyannote, CUDA/cuDNN, Whisper,
YOLOX, VLM, Ollama, Qdrant, disque et environnement CloseDay. Ne contourne pas
un rouge : applique sa ligne `[FIX]`. Avant d'ouvrir l'app, exige :

- `pairing_ready=true` ;
- `ai_ready=true` ;
- <http://localhost:8710/ready> en HTTP 200.

Garde cette console ouverte pendant la capture et CloseDay. Autorise le port
TCP 8710 sur le réseau privé Windows.

Le profil mémoire est **Full par défaut**. Pour une nuit beaucoup plus courte,
owner-centrée, sans la chaîne complète V13–V18, ajoute
`-MemoryProfile lite`. Ce choix est indépendant de Local/PRO et se fait avant la
capture; revenir à Full consiste seulement à omettre l'option ou écrire
`-MemoryProfile full`.

Pour activer aussi les fonctions augmentées PC (Wikipédia hors ligne, cartes
objet et Home Assistant), ajoute `-AugmentedReality` :

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality `
  -MemoryProfile lite -BindHost 0.0.0.0 -Port 8710
```

Kiwix est exécuté sur le PC; le S24 reçoit seulement la carte courte. Les
commandes uniques d'installation Kiwix, d'ajout domotique et d'ouverture studio
par code sont dans
[`FIRST_TRY_XREAL_S24.md`](FIRST_TRY_XREAL_S24.md#connaissance-hors-ligne-domotique-et-profils-studio).

## 5. Lancer le PC — PRO optionnel

PRO ne change pas le Live local. Il utilise DeepSeek, Groq Whisper et Gemini
après la fin de session.

Les clés restent uniquement dans `.env` :

```text
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

Commande :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -Pro -ProTextModel pro `
  -MemoryProfile lite `
  -CloudBudgetEur 1.50 -CloudOnBudget stop `
  -BindHost 0.0.0.0 -Port 8710
```

`-CloudOnBudget stop` interdit tout dépassement. `-ProTextModel flash` est
moins coûteux mais moins profond. Remplace `lite` par `full` pour la chaîne
historique complète.

## 6. Vérifier le réseau depuis le S24

Dans le navigateur du S24 :

- même Wi-Fi : `http://192.168.1.199:8710/ready` ;
- dehors/5G avec Tailscale : `http://100.113.42.19:8710/ready`.

Une des deux routes doit répondre prête. Si aucune ne répond, vérifie le
pare-feu privé, Tailscale et :

```powershell
tailscale status
tailscale ip -4
Test-NetConnection 127.0.0.1 -Port 8710
```

## 7. Première session

1. Attends le préflight PC vert.
2. Ouvre MLOmega sur le S24.
3. Attends `Paired`, puis `Connected`.
4. Laisse les modèles ASR terminer leur premier téléchargement (`dl: 100 %`).
5. Dis **« Viki, configure ma voix »**, puis parle pendant la capture demandée.
   Cette étape est obligatoire pour que tes tours portent `person_id=me`.

Checklist courte :

- briefing du jour reçu ;
- wake word « Viki » et sous-titres ;
- « c'est quoi ça ? » sur plusieurs objets ;
- « où sont mes lunettes ? » visible, puis hors champ ;
- « lis le texte », puis « traduis-le » ;
- « ouvre le menu », paume, pinch/zoom et déplacement d'un panneau ;
- « aide-moi à faire un café », puis « étape suivante » ;
- « retiens que… », puis question mémoire sur ce fait ;
- une personne inconnue reste anonyme ; une identité n'est promue que par preuve
  ou correction utilisateur ;
- perte Wi-Fi puis reconnexion sans double audio ;
- PC inaccessible : Reflex/sous-titres locaux continuent honnêtement.

Le système mémorise toute parole durable. En politique wake-word gated, seules
les commandes sont bloquées sans « Viki » ; la conversation ordinaire continue
d'alimenter la mémoire.

Pour suivre le runtime :

```powershell
Invoke-RestMethod http://localhost:8710/metrics |
  ConvertTo-Json -Depth 8
```

Une commande `accepted` n'est pas une preuve suffisante : elle doit finir
`completed` ou produire un échec explicite.

## 8. Terminer et lancer CloseDay

Ne swipe pas l'app et ne force pas son arrêt.

Touche dans MLOmega :

**« Terminer la session et lancer CloseDay »**

Le bouton authentifie `/session/end`, arrête la capture, scelle BrainLive et
déclenche CloseDay. L'accusé Android arrive avant la fin des traitements lourds.
Surveille la console PC et `/metrics` jusqu'à :

- `end_session=completed` ;
- `close_day=running`, puis `completed` ;
- maintenance `completed` ou warning expliqué.

`/session/status` est une route POST authentifiée utilisée par l'app, pas une
page à ouvrir directement.

En cas de crash, ne supprime ni DB ni médias : relance la même commande RUN. La
recovery reprend le job durable et empêche un faux succès. Quand CloseDay est
terminé, arrête le serveur par `Ctrl+C`, puis ferme l'app.

## 9. Dashboard

Après CloseDay :

```powershell
cd C:\Users\wabad\Downloads\ProjetMemobyFABLE\Mlomega-main
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
```

Ouvre <http://localhost:8720>. Le Dashboard est en lecture seule et vérifie que
le SHA de la DB reste identique. Pour imposer une DB :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1 `
  -Database "C:\chemin\vers\memory.db"
```

## 10. Audit owner/qualité — manuel

Lance-le uniquement après un CloseDay terminé, idéalement une fois par semaine
ou un jour OFF :

```powershell
$line = Select-String -Path .env -Pattern '^\s*MLOMEGA_DB\s*=' |
  Select-Object -First 1
$db = (($line.Line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
if (-not [IO.Path]::IsPathRooted($db)) { $db = Join-Path $pwd $db }
$db = (Resolve-Path $db).Path

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$plan = "tools\harness\_run\owner-shadow-$stamp-plan.json"
$report = "tools\harness\_run\owner-shadow-$stamp-report.json"

.\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
  --db $db --owner-id me --owner-name William `
  --plan-only --text-backend deepseek --deepseek-model deepseek-v4-pro `
  --vision-backend existing --budget-eur 1.00 --out $plan
```

Lis le devis. S'il est cohérent :

```powershell
.\.venv\Scripts\python.exe tools\harness\owner_quality_shadow.py `
  --db $db --owner-id me --owner-name William `
  --execute --plan $plan --apply-safe `
  --text-backend deepseek --deepseek-model deepseek-v4-pro `
  --vision-backend existing --budget-eur 1.00 --out $report
```

Exige `mode=execute_applied_safe`, un backup indiqué et `quick_check=ok`.

## 11. Diagnostic PhoneOnly

```powershell
adb logcat |
  Select-String 'SessionPairing|LiveTransport|PhoneOnly|AsrBridge|Reflex'
```

Problèmes courants :

- pairing bloqué : vérifie `/ready` depuis le S24 ;
- aucune commande : vérifie micro, transcript PC et état terminal de la trace ;
- modèles : garde l'app au premier plan jusqu'à `dl: 100 %` ;
- arrière-plan : retire l'optimisation batterie et verrouille MLOmega si Samsung
  propose « applications jamais en veille » ;
- CloseDay rouge : conserve DB/logs et relance RUN pour recovery.

Les tests automatisés prouvent le code et les frontières simulées. Le premier
S24 réel reste nécessaire pour certifier caméra, micro, permissions, chauffe,
batterie et latence physique.
