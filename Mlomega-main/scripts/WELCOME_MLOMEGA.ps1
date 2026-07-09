<#
WELCOME_MLOMEGA.ps1 — assistant de bienvenue interactif MLOmega V19 (E51).

But : n'importe qui installe et lance MLOmega en suivant un assistant, sans
oublier une etape. Ce script N'IMPLEMENTE PAS l'install : il ORCHESTRE les
scripts existants (INSTALL_MLOMEGA_V19_WINDOWS.ps1, setup_profile.ps1,
fetch_models_v19.py, START_QDRANT.ps1, RUN_MLOMEGA_V19.ps1, DOCTOR) en posant
d'abord les bonnes questions.

Deroule 9 etapes (cf. docs/PROD_BACKLOG.md §E51) :
  1. Materiel (lunettes / telephone)
  2. Scan machine (GPU/VRAM/RAM/disque) -> set de modeles + cloud opt-in
  3. Token Hugging Face (pyannote)
  4. Installation complete (venvs, ffmpeg, Qdrant, Ollama, modeles, .env, profil, DOCTOR)
  5. Lancement PC guide
  6. Telephone (APK, adb, permissions, pairing)
  7. Mini-tutoriel
  8. Comment quitter (bouton Terminer -> close-day)
  9. Le lendemain (relancer, changer de modeles, commandes utiles, dashboard, backup)

Note : le mot d'eveil (E58) est demande a l'etape 4 : detecte dans l'ASR francais
(prononciation naturelle), pousse au telephone a la connexion, changeable quand on
veut (configs/user_profile.yaml) SANS rebuild. Defaut : 'viki'.

Chaque section est autonome et idempotente. En cas d'echec : message clair +
comment reprendre, jamais une stacktrace brute.

Modes :
  (defaut, interactif) : pose les questions (Read-Host) et execute reellement.
  -Defaults            : ne pose aucune question (valeurs sures) ; utile pour un
                         deroule non bloquant.
  -DryRun              : ne lance AUCUNE install/telechargement/serveur lourd ;
                         valide le deroule, les reponses, la detection materiel
                         et que chaque script appele existe avec les bons params.
                         Implique -Defaults sauf si tu passes des reponses.

PowerShell 5.1 compatible : pas de '&&', pas d'operateur ternaire.
#>
[CmdletBinding()]
param(
  [switch]$Defaults,
  [switch]$DryRun,
  [string]$PersonId = "me"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $ProjectRoot

if ($DryRun) { $Defaults = $true }

# ------------------------------------------------------------------------
# Helpers d'affichage + questions
# ------------------------------------------------------------------------
function Say([string]$m)      { Write-Host $m }
function Title([string]$m)    { Write-Host "`n============================================================" -ForegroundColor Cyan; Write-Host " $m" -ForegroundColor Cyan; Write-Host "============================================================" -ForegroundColor Cyan }
function Step([string]$n, [string]$m) { Write-Host "`n--- Etape $n : $m ---" -ForegroundColor Cyan }
function Ok([string]$m)       { Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn([string]$m)     { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Info([string]$m)     { Write-Host "[INFO] $m" -ForegroundColor Gray }
function DryNote([string]$m)  { Write-Host "[DRY]  $m" -ForegroundColor Magenta }
function Hint([string]$m)     { Write-Host "       $m" -ForegroundColor DarkGray }

function Ask([string]$Question, [string]$Default, [string[]]$Choices) {
  if ($Defaults) { return $Default }
  $hint = ""
  if ($Choices) { $hint = " [" + ($Choices -join "/") + "]" }
  $answer = Read-Host "$Question$hint (defaut: $Default)"
  if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
  if ($Choices -and ($Choices -notcontains $answer)) {
    Warn "Valeur non reconnue; on garde le defaut '$Default'."
    return $Default
  }
  return $answer
}
function AskYesNo([string]$Question, [string]$Default) {
  return (Ask $Question $Default @("oui", "non"))
}
function AskSecret([string]$Question) {
  if ($Defaults) { return "" }
  return (Read-Host $Question)
}

# Idempotent : ecrit/remplace une cle=valeur dans .env sans casser le reste.
function Set-EnvValue([string]$EnvPath, [string]$Key, [string]$Value) {
  if (-not (Test-Path $EnvPath)) { return }
  $lines = Get-Content -LiteralPath $EnvPath
  $found = $false
  $out = foreach ($line in $lines) {
    if ($line -match "^\s*$([regex]::Escape($Key))\s*=") { $found = $true; "$Key=$Value" }
    else { $line }
  }
  if (-not $found) { $out = @($out) + "$Key=$Value" }
  Set-Content -LiteralPath $EnvPath -Value $out -Encoding UTF8
}

$script:Notes = @()
function Remember([string]$m) { $script:Notes += $m }

# ------------------------------------------------------------------------
Title "Bienvenue dans MLOmega V19 — assistant d'installation et de demarrage"
Say   "Cet assistant t'accompagne du telechargement des modeles jusqu'a ta"
Say   "premiere session, puis te dit comment relancer le lendemain."
if ($DryRun)   { Warn "MODE DRY-RUN : rien de lourd n'est lance (pas d'install, de download, ni de serveur). On valide seulement le deroule." }
if ($Defaults -and -not $DryRun) { Info "Mode -Defaults : les questions prennent leurs valeurs sures automatiquement." }

# ========================================================================
# ETAPE 1 — MATERIEL
# ========================================================================
Step "1/9" "Materiel"
$glasses = AskYesNo "As-tu des lunettes de realite augmentee ?" "non"
$display = "phone_only"
$capture = "phone_camera"
if ($glasses -eq "oui") {
  $brand = Ask "Quelle marque ? (seul XREAL est supporte aujourd'hui)" "xreal" @("xreal", "autre")
  if ($brand -eq "xreal") {
    $display = "xreal_one_pro"
    $capture = "xreal_eye"
    Ok "Support XREAL disponible (E49 : adaptateur cable au SDK 3.1.0 + build lunettes prets)."
    Hint "L'APK lunettes (mlomega-xreal-g1.apk) se BUILDE toi-meme : le SDK XREAL est"
    Hint "proprietaire (non redistribue dans le repo). Depose com.xreal.xr.tar.gz dans"
    Hint "apps/xr-mobile/Packages/xreal-sdk/ puis lance le build lunettes (menu Unity"
    Hint "MLOmega > XREAL > 2, ou -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildApk)."
    Remember "Lunettes XREAL : builde l'APK via AndroidBuildXreal.BuildApk (SDK dans Packages/xreal-sdk/). Le reste de l'install PC est identique au PhoneOnly."
  } else {
    Warn "Marque non supportee (Meta/Spectacles plus tard). On part sur PhoneOnly."
  }
} else {
  Ok "Mode PhoneOnly (telephone seul, sans lunettes)."
}
$phone = Ask "Quel telephone ? (meme APK Android pour tous)" "android" @("android")
Ok "Materiel enregistre : display=$display, capture=$capture, telephone=$phone"

# ========================================================================
# ETAPE 2 — SCAN MACHINE + CHOIX MODELES + CLOUD OPT-IN
# ========================================================================
Step "2/9" "Scan de la machine et choix des modeles"

# --- GPU / VRAM via nvidia-smi ---
$vramMb = 0
$gpuName = ""
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  $rows = @(& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null)
  if ($LASTEXITCODE -eq 0 -and $rows) {
    $first = ($rows | Select-Object -First 1) -split ','
    if ($first.Count -ge 2) {
      $gpuName = $first[0].Trim()
      $vramMb = [int]($first[1].Trim())
      Ok "GPU : $gpuName, $vramMb Mo VRAM"
    }
  } else { Warn "nvidia-smi present mais sans etat GPU (mode CPU degrade)." }
} else {
  Warn "nvidia-smi absent : pas de GPU NVIDIA detecte (mode CPU degrade : pas de VisionRT/VLM GPU)."
}

# --- RAM ---
try {
  $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
  Ok "RAM : $ramGb Go"
} catch { $ramGb = 0; Warn "RAM non detectee." }

# --- Disque libre sur le lecteur du projet ---
$drive = (Get-Item $ProjectRoot).PSDrive
$freeGb = [math]::Floor($drive.Free / 1GB)
if ($freeGb -lt 20) { Warn "Disque $($drive.Name): $freeGb Go libres — c'est juste (modeles + memoire grossissent). 20+ Go conseilles." }
else { Ok "Disque $($drive.Name): $freeGb Go libres" }

# --- VLM lourd de NUIT (E56) : deep vision sur les keyframes des bundles ---
# Live = moondream (leger). NUIT = un VLM VISION lourd (qwen2.5vl), charge pour la
# seule phase deep-vision puis dechargé. On detecte le tag exact installe sur cette
# machine (fallback qwen2.5vl:7b) pour ne pas deviner.
$vlmLight = "moondream"
$vlmHeavy = "qwen2.5vl:7b"
try {
  $listed = @(ollama list 2>$null | ForEach-Object { ($_ -split '\s+')[0] })
  $foundVl = $listed | Where-Object { $_ -match '^qwen2\.5vl' } | Select-Object -First 1
  if ($foundVl) { $vlmHeavy = $foundVl; Info "VLM lourd detecte sur la machine : $vlmHeavy" }
} catch {}

# --- Recommandation set de modeles Ollama selon la VRAM ---
$ollamaModels = @("qwen3.5:4b", "qwen3.5:9b", $vlmLight, $vlmHeavy)
$degraded = $false
if ($vramMb -ge 8000) {
  Ok "VRAM >= 8 Go : set = qwen3.5:4b (live) + qwen3.5:9b (deep) + $vlmLight (VLM live) + $vlmHeavy (VLM nuit)."
} elseif ($vramMb -ge 6000) {
  Warn "VRAM 6-8 Go : deep 9b + VLM nuit tiennent en post-stop (charges/decharges par phase) mais serre. Set complet, surveille la VRAM."
} elseif ($vramMb -gt 0) {
  $degraded = $true
  $ollamaModels = @("qwen3.5:4b", $vlmLight)
  Warn "VRAM < 6 Go : profil degrade = qwen3.5:4b (live) + $vlmLight seulement (pas de 9b deep ni VLM lourd de nuit)."
  Remember "GPU sous 6 Go VRAM : profil degrade — le deep 9b et le VLM nuit peuvent ne pas tenir; envisage plus petit ou le cloud."
} else {
  $degraded = $true
  $ollamaModels = @("qwen3.5:4b")
  Warn "Pas de GPU : mode CPU tres degrade. Le live LLM tournera lentement; VisionRT/VLM GPU indisponibles."
  Remember "Pas de GPU : mode CPU degrade — usage reel limite. Un GPU NVIDIA 8 Go+ est recommande."
}
Info "Modeles Ollama a installer : $($ollamaModels -join ', ')"

# --- Cloud opt-in (OpenAI / Gemini) ---
$llm = "ollama_local"
$llmModel = "qwen3.5:4b"
$cloudPolicy = "local_only"
$openaiKey = ""
$geminiKey = ""
$wantCloud = AskYesNo "Veux-tu activer un LLM cloud en OPT-IN (OpenAI/Gemini) en plus du local ?" "non"
if ($wantCloud -eq "oui") {
  $provider = Ask "Quel fournisseur cloud ?" "openai" @("openai", "gemini")
  $llm = $provider
  if ($provider -eq "openai") {
    $llmModel = ""
    $openaiKey = AskSecret "Colle ta cle OpenAI (elle ira dans .env, jamais dans un log)"
  } else {
    $llmModel = ""
    $geminiKey = AskSecret "Colle ta cle Gemini (elle ira dans .env, jamais dans un log)"
  }
  $cloudPolicy = Ask "Politique de donnees cloud" "allow_transcripts" @("local_only", "allow_crops", "allow_transcripts")
  Ok "Cloud opt-in : $provider (cle stockee dans .env)."
  Remember "Cloud $provider active : la cle est dans .env; la StatusBar indiquera le cloud actif et le cout par requete (mecanique E33)."
} else {
  Ok "Pas de cloud : cloud_data_policy = local_only (tout reste sur ta machine)."
}

# ========================================================================
# ETAPE 3 — TOKEN HUGGING FACE (pyannote)
# ========================================================================
Step "3/9" "Token Hugging Face (diarisation pyannote, traitement de nuit)"
Say  "Le traitement de NUIT (WhisperX + pyannote) attribue les tours de parole"
Say  "aux bonnes personnes. pyannote exige un token Hugging Face GRATUIT et"
Say  "l'acceptation des conditions du modele :"
Hint "1) Cree/connecte un compte : https://huggingface.co/join"
Hint "2) Accepte les conditions : https://huggingface.co/pyannote/speaker-diarization-3.1"
Hint "3) Genere un token (role 'read') : https://huggingface.co/settings/tokens"
$hfToken = AskSecret "Colle ton token Hugging Face (format 'hf_...'; laisse vide pour le mettre plus tard)"
if ([string]::IsNullOrWhiteSpace($hfToken)) {
  Warn "Aucun token fourni. La NUIT (diarisation) sera degradee tant que MLOMEGA_HF_TOKEN n'est pas rempli dans .env."
  Remember "Token Hugging Face non fourni : renseigne MLOMEGA_HF_TOKEN dans .env avant la premiere nuit (diarisation pyannote)."
} elseif ($hfToken -notlike "hf_*") {
  Warn "Le token ne commence pas par 'hf_' — verifie qu'il est correct. Je l'enregistre quand meme."
} else {
  Ok "Token Hugging Face au bon format."
}

# ========================================================================
# ETAPE 4 — INSTALLATION COMPLETE
# ========================================================================
Step "4/9" "Installation complete (chaque sous-etape est idempotente)"

# --- 4a0. .venv COEUR (E56) : moteur du close-day nocturne (torch/whisperx/pyannote) ---
# Le close-day de NUIT tourne dans .venv (pas .venv-live). L'installateur transactionnel
# (4a) ne cree QUE .venv-live et ne touche jamais .venv — donc on cree le coeur ICI,
# sinon la consolidation nocturne serait impossible. Idempotent : saute si .venv existe.
Info "Sous-etape 4a0 : .venv coeur (moteur du close-day nocturne)."
$coreVenv = Join-Path $ProjectRoot ".venv"
$coreLock = Join-Path $ProjectRoot "requirements-v18_8-windows.lock.txt"
$corePip  = Join-Path $coreVenv "Scripts\pip.exe"
if (Test-Path (Join-Path $coreVenv "Scripts\python.exe")) {
  Ok ".venv coeur deja present : conserve tel quel (aucune reinstallation)."
} elseif (-not (Test-Path $coreLock)) {
  Warn "Lock coeur introuvable ($coreLock) : je ne peux pas creer .venv. Le close-day nocturne sera indisponible."
  Remember ".venv coeur non cree (lock absent) : la consolidation de nuit ne tournera pas."
} elseif ($DryRun) {
  DryNote "Creerait .venv coeur : python -m venv .venv  puis  .venv\Scripts\pip install -r requirements-v18_8-windows.lock.txt  (long : torch cu121/whisperx/pyannote)."
} else {
  Warn "Creation du .venv coeur : c'est l'etape LA PLUS LONGUE (torch cu121, whisperx, pyannote — plusieurs minutes / gros telechargement)."
  & python -m venv $coreVenv
  if ($LASTEXITCODE -ne 0) { Warn "Creation .venv coeur echouee. Verifie que Python 3.11 64-bit est installe (python --version)." ; Remember ".venv coeur : creation echouee, relance apres avoir installe Python 3.11." }
  else {
    & $corePip install --upgrade pip
    & $corePip install -r $coreLock
    if ($LASTEXITCODE -ne 0) { Warn "pip install (coeur) a signale un souci. Relance : .venv\Scripts\pip install -r requirements-v18_8-windows.lock.txt" ; Remember ".venv coeur : pip install a echoue en partie, relance la commande ci-dessus." }
    else { Ok ".venv coeur installe (moteur close-day pret)." }
  }
}

# --- 4a1. Qdrant natif (E56) : binaire + config, sans Docker ---
# START_QDRANT.ps1 attend tools\qdrant\qdrant.exe + config.yaml et ECHOUE s'ils manquent.
# On provisionne ici (release officielle GitHub v1.12.6, la version testee) si absent.
Info "Sous-etape 4a1 : Qdrant natif (memoire vectorielle, sans Docker)."
$qdrantDir = Join-Path $ProjectRoot "tools\qdrant"
$qdrantExe = Join-Path $qdrantDir "qdrant.exe"
$qdrantCfg = Join-Path $qdrantDir "config.yaml"
$qdrantVersion = "v1.12.6"
$qdrantUrl = "https://github.com/qdrant/qdrant/releases/download/$qdrantVersion/qdrant-x86_64-pc-windows-msvc.zip"
if (Test-Path $qdrantExe) {
  Ok "qdrant.exe deja present : conserve."
} elseif ($DryRun) {
  DryNote "Telechargerait Qdrant $qdrantVersion ($qdrantUrl) -> $qdrantDir, puis ecrirait config.yaml si absent."
} else {
  try {
    if (-not (Test-Path $qdrantDir)) { New-Item -ItemType Directory -Path $qdrantDir -Force | Out-Null }
    $zip = Join-Path $qdrantDir "qdrant.zip"
    Info "Telechargement de Qdrant $qdrantVersion ..."
    Invoke-WebRequest -Uri $qdrantUrl -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $qdrantDir -Force
    Remove-Item $zip -ErrorAction SilentlyContinue
    if (Test-Path $qdrantExe) { Ok "qdrant.exe provisionne." }
    else { Warn "Archive Qdrant extraite mais qdrant.exe introuvable — verifie $qdrantDir." ; Remember "Qdrant : binaire non trouve apres extraction, provisionne-le a la main (voir INSTALL_STATE)." }
  } catch {
    Warn "Telechargement de Qdrant impossible ($($_.Exception.Message)). Provisionne tools\qdrant\qdrant.exe a la main (release $qdrantVersion) ou via INSTALL_STATE."
    Remember "Qdrant non telecharge : mets tools\qdrant\qdrant.exe (release $qdrantVersion) puis relance START_QDRANT."
  }
}
if ((Test-Path $qdrantExe) -and -not (Test-Path $qdrantCfg) -and -not $DryRun) {
  $storage = (Join-Path $ProjectRoot "storage\qdrant") -replace '\\','/'
  $cfg = @("storage:", "  storage_path: $storage", "service:", "  host: 127.0.0.1", "  http_port: 6333")
  Set-Content -LiteralPath $qdrantCfg -Value $cfg -Encoding UTF8
  Ok "tools\qdrant\config.yaml genere (storage local, port 6333)."
}

# --- 4a. Environnement live .venv-live (via l'installateur transactionnel) ---
$installer = Join-Path $ScriptDir "INSTALL_MLOMEGA_V19_WINDOWS.ps1"
if (-not (Test-Path $installer)) { Warn "Introuvable : $installer — impossible d'installer .venv-live." }
else {
  Info "Sous-etape 4a : .venv-live (env live, cree transactionnellement ; .venv coeur intact)."
  if ($DryRun) {
    DryNote "Appellerait : $installer -SkipDoctor  (le DOCTOR final est lance en 4g)"
  } else {
    & $installer -SkipDoctor
    if ($LASTEXITCODE -ne 0) { Warn "L'installateur a signale un souci (code $LASTEXITCODE). Relis sa sortie ci-dessus; tu peux relancer $installer seul." }
    else { Ok ".venv-live installe." }
  }
}

# --- 4b. ffmpeg ---
Info "Sous-etape 4b : ffmpeg (stitching de clips/preuves, transcodage audio E54)."
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
  Ok "ffmpeg deja present."
} else {
  if ($DryRun) { DryNote "ffmpeg absent -> lancerait : winget install Gyan.FFmpeg" }
  else {
    $doFfmpeg = AskYesNo "ffmpeg absent. L'installer via winget (Gyan.FFmpeg) ?" "oui"
    if ($doFfmpeg -eq "oui" -and (Get-Command winget -ErrorAction SilentlyContinue)) {
      winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
      Info "Si ffmpeg n'est pas encore reconnu, ferme/rouvre le terminal (PATH)."
    } else {
      Warn "ffmpeg non installe : clips/preuves et transcodage audio seront degrades. Installe-le plus tard (winget install Gyan.FFmpeg)."
      Remember "ffmpeg absent : certaines fonctions media sont degradees jusqu'a son installation."
    }
  }
}

# --- 4c. Ollama + pulls des modeles choisis ---
Info "Sous-etape 4c : Ollama + telechargement des modeles ($($ollamaModels -join ', '))."
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Warn "Ollama introuvable. Installe-le : https://ollama.com/download puis relance cette etape."
  Remember "Ollama non installe : va sur https://ollama.com/download, puis 'ollama pull $($ollamaModels -join ' ; ollama pull ')'."
} else {
  if ($DryRun) {
    foreach ($m in $ollamaModels) { DryNote "Lancerait : ollama pull $m" }
  } else {
    foreach ($m in $ollamaModels) {
      Info "ollama pull $m ..."
      ollama pull $m
      if ($LASTEXITCODE -ne 0) { Warn "Echec du pull de $m (reseau ? nom ?). Relance : ollama pull $m" }
      else { Ok "$m pret." }
    }
  }
}

# --- 4d. fetch_models_v19.py (ONNX detecteur/visage + device) ---
Info "Sous-etape 4d : modeles ONNX (detecteur, visage) + modeles device Android."
$livePy = Join-Path $ProjectRoot ".venv-live\Scripts\python.exe"
$fetch = Join-Path $ScriptDir "fetch_models_v19.py"
if (-not (Test-Path $fetch)) { Warn "Introuvable : $fetch" }
elseif ($DryRun) {
  if (Test-Path $livePy) { DryNote "Lancerait : $livePy $fetch --device   (ONNX + modeles device Android)" }
  else { DryNote "Lancerait fetch_models_v19.py --device des que .venv-live existe (voir 4a)." }
} elseif (Test-Path $livePy) {
  & $livePy $fetch --device
  if ($LASTEXITCODE -ne 0) { Warn "Certains modeles n'ont pas ete recuperes (reseau ?). Relance : $livePy $fetch --device --check pour voir lesquels." }
  else { Ok "Modeles ONNX + device recuperes et verifies (sha256)." }
} else { Warn ".venv-live absent : fetch_models saute (relance apres 4a)." }

# --- 4e. .env genere depuis le template ---
Info "Sous-etape 4e : generation de .env (depuis le template V18.8)."
$envPath = Join-Path $ProjectRoot ".env"
$envTemplate = Join-Path $ProjectRoot "MLOmega_V18_8_1_Evidence_Connected\.env.core-v18_8.template"
if ($DryRun) {
  if (Test-Path $envPath) { DryNote ".env existe deja : mettrait a jour HF_TOKEN / cles cloud sans ecraser le reste." }
  else { DryNote "Genererait .env depuis $envTemplate (substitue __PROJECT_ROOT__, __HF_TOKEN__, __PHONE_TOKEN__)." }
} elseif (-not (Test-Path $envTemplate)) {
  Warn "Template .env introuvable : $envTemplate — je saute la generation .env."
} else {
  if (Test-Path $envPath) {
    Ok ".env deja present : je le conserve et ne mets a jour que les cles fournies."
  } else {
    $tpl = Get-Content -LiteralPath $envTemplate -Raw
    $phoneToken = [guid]::NewGuid().ToString("N")
    $tpl = $tpl.Replace("__PROJECT_ROOT__", $ProjectRoot)
    $tpl = $tpl.Replace("__PHONE_TOKEN__", $phoneToken)
    if ([string]::IsNullOrWhiteSpace($hfToken)) { $tpl = $tpl.Replace("__HF_TOKEN__", "") }
    else { $tpl = $tpl.Replace("__HF_TOKEN__", $hfToken) }
    Set-Content -LiteralPath $envPath -Value $tpl -Encoding UTF8
    Ok ".env genere (token telephone auto, chemins absolus)."
  }
  # Toujours (re)poser les valeurs sensibles fournies, sans stacktrace ni echo de la cle.
  if (-not [string]::IsNullOrWhiteSpace($hfToken)) { Set-EnvValue $envPath "MLOMEGA_HF_TOKEN" $hfToken; Ok "MLOMEGA_HF_TOKEN ecrit dans .env." }
  if (-not [string]::IsNullOrWhiteSpace($openaiKey)) { Set-EnvValue $envPath "OPENAI_API_KEY" $openaiKey; Ok "OPENAI_API_KEY ecrit dans .env." }
  if (-not [string]::IsNullOrWhiteSpace($geminiKey)) { Set-EnvValue $envPath "GEMINI_API_KEY" $geminiKey; Ok "GEMINI_API_KEY ecrit dans .env." }
  # E56 : VLM live (leger) + VLM nuit (lourd). Le template par defaut vise qwen3-vl:8b ;
  # on aligne sur le modele VISION reellement choisi/detecte (qwen2.5vl par defaut).
  if (-not $degraded) {
    Set-EnvValue $envPath "MLOMEGA_VLM_MODEL" $vlmLight
    Set-EnvValue $envPath "MLOMEGA_OFFLINE_VLM_MODEL" $vlmHeavy
    Set-EnvValue $envPath "MLOMEGA_VLM_HEAVY_MODEL" $vlmHeavy
    Ok "VLM configures dans .env : live=$vlmLight, nuit=$vlmHeavy."
  } else {
    Set-EnvValue $envPath "MLOMEGA_VLM_MODEL" $vlmLight
    Set-EnvValue $envPath "MLOMEGA_OFFLINE_VLM_MODEL" $vlmLight
    Set-EnvValue $envPath "MLOMEGA_VLM_HEAVY_MODEL" $vlmLight
    Warn "Profil degrade : VLM nuit ramene sur $vlmLight (le VLM lourd risque de ne pas tenir)."
  }
}

# --- 4f. setup_profile.ps1 alimente par les reponses ---
Info "Sous-etape 4f : profil de capacites (configs/user_profile.yaml)."
$setupProfile = Join-Path $ScriptDir "setup_profile.ps1"
if (-not (Test-Path $setupProfile)) { Warn "Introuvable : $setupProfile" }
else {
  $visionArg = "onnx_local"
  if ($degraded -and $vramMb -eq 0) { $visionArg = "onnx_local" }  # local reste correct; cloud vision non force ici
  $profileArgs = @(
    "-Defaults",
    "-Display", $display,
    "-Capture", $capture,
    "-Llm", $llm,
    "-LlmModel", $llmModel,
    "-Vision", $visionArg,
    "-Asr", "local",
    "-CloudDataPolicy", $cloudPolicy
  )
  if ($DryRun) {
    DryNote "Appellerait : $setupProfile $($profileArgs -join ' ')"
  } else {
    & $setupProfile @profileArgs
    if ($LASTEXITCODE -ne 0) { Warn "setup_profile a renvoye un code $LASTEXITCODE." }
    else { Ok "configs/user_profile.yaml ecrit depuis tes reponses." }
  }
}

# --- 4f2. Mot d'eveil (E58) : detecte dans l'ASR francais, changeable sans rebuild ---
Info "Sous-etape 4f2 : mot d'eveil (pour ouvrir une commande a la voix)."
Say  "Comment veux-tu appeler l'assistant ? Il est detecte dans la transcription"
Say  "FRANCAISE (prononciation naturelle) et pousse au telephone a la connexion"
Say  "-> changeable quand tu veux, SANS rebuilder l'APK."
Hint "Choisis un mot RARE et distinct (un mot courant = faux declenchements)."
Hint "Exemples : viki, jarvis, nyx. Defaut : viki."
$wake = Ask "Mot d'eveil" "viki"
$profileYaml = Join-Path $ProjectRoot "configs\user_profile.yaml"
if ($DryRun) {
  DryNote "Ecrirait wake_word: $wake dans configs\user_profile.yaml"
} elseif (Test-Path $profileYaml) {
  $wlines = Get-Content -LiteralPath $profileYaml | Where-Object { $_ -notmatch '^\s*wake_word\s*:' }
  $wlines += "wake_word: $wake"
  Set-Content -LiteralPath $profileYaml -Value $wlines -Encoding UTF8
  Ok "Mot d'eveil '$wake' enregistre (pousse au telephone a la connexion)."
}
Remember "Mot d'eveil = '$wake' : change-le quand tu veux dans configs\user_profile.yaml (pousse au device, pas de rebuild)."
# --- 4g. DOCTOR -Full en garde-fou final ---
Info "Sous-etape 4g : DOCTOR -Full (garde-fou : rien ne doit etre casse)."
$doctor = Join-Path $ScriptDir "DOCTOR_MLOMEGA_V19.ps1"
if (-not (Test-Path $doctor)) { Warn "Introuvable : $doctor" }
elseif ($DryRun) {
  DryNote "Lancerait : $doctor -Full  (WARN toleres, un FAIL indique quoi corriger)."
} else {
  & $doctor -Full
  if ($LASTEXITCODE -ne 0) { Warn "DOCTOR a signale au moins un FAIL. Corrige le point indique ci-dessus puis relance : $doctor -Full" }
  else { Ok "DOCTOR -Full : installation saine (WARN eventuels non bloquants)." }
}

# ========================================================================
# ETAPE 5 — LANCEMENT PC GUIDE
# ========================================================================
Step "5/9" "Lancement du PC (les 3 briques : Qdrant, Ollama, MLOmega)"
Say  "Ordre : (1) Qdrant (memoire vectorielle), (2) 'ollama serve' si pas deja"
Say  "en service, (3) le runtime MLOmega PhoneOnly."
$doLaunch = AskYesNo "Lancer le PC maintenant ?" "non"
if ($doLaunch -eq "oui" -and -not $DryRun) {
  $startQdrant = Join-Path $ScriptDir "START_QDRANT.ps1"
  if (Test-Path $startQdrant) { & $startQdrant } else { Warn "START_QDRANT.ps1 introuvable." }
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Warn "ollama introuvable pour 'ollama serve'." }
  else { Info "Verifie qu'Ollama tourne (souvent en service). Sinon, dans une autre fenetre : ollama serve" }
  Info "Runtime : dans une fenetre dediee, lance :"
  Hint ".\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710"
  Hint "Le health s'affichera : http://<IP-du-PC>:8710/health"
} else {
  DryNote "Commandes de lancement (a garder sous la main) :"
  Hint "powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1"
  Hint "ollama serve   # si pas deja en service"
  Hint ".\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710"
  Hint "Prets quand : http://<IP-du-PC>:8710/health repond OK."
}
Warn "A NE PAS OUBLIER (1re session) :"
Hint "- PC et telephone sur le MEME Wi-Fi."
Hint "- Pare-feu Windows : autorise le port 8710 sur le reseau PRIVE (sinon le telephone ne voit pas le PC)."
Hint "- Dehors (4G/5G) : passe par Tailscale — voir docs/OUTSIDE_ACCESS.md."
Remember "Pare-feu : ouvre le port 8710 (profil reseau prive) et garde PC+telephone sur le meme Wi-Fi pour la 1re session."

# ========================================================================
# ETAPE 6 — TELEPHONE
# ========================================================================
Step "6/9" "Telephone (APK, install, permissions, pairing)"
# E49/E58 : l'APK depend du choix materiel (lunettes vs telephone).
if ($display -eq "xreal_one_pro") {
  $apkPath = "apps\xr-mobile\build\android\mlomega-xreal-g1.apk"
  Say  "APK LUNETTES (XREAL) : $apkPath"
  Hint "(a builder via AndroidBuildXreal si absente — SDK dans Packages\xreal-sdk\)"
} else {
  $apkPath = "apps\xr-mobile\build\android\mlomega-phoneonly.apk"
  Say  "APK PhoneOnly : $apkPath"
}
Say  "Deux facons d'installer :"
Hint "A) Avec un cable + adb (developpeur) :  adb install -r `"$apkPath`""
Hint "B) Copie manuelle : transfere l'APK sur le telephone et ouvre-le (autorise l'install depuis cette source)."
Say  "Au 1er lancement de l'app :"
Hint "- Accorde les permissions MICRO et CAMERA (indispensables)."
Hint "- Le pairing avec le PC est automatique s'ils sont sur le meme Wi-Fi et le port 8710 ouvert."
Hint "- Au 1er lancement, l'app telecharge ses modeles device depuis le PC (ASR/KWS/traduction) — Wi-Fi LAN, une seule fois."
if ($display -eq "xreal_one_pro") {
  Hint "- Lunettes : installe l'APK ci-dessus, branche les lunettes en USB-C, lance l'app -> rendu stereo + camera Eye."
}

# --- Enregistrement des choix (pas de mot d'eveil : cuit dans l'APK) ---
$choiceFile = Join-Path $ProjectRoot "configs\welcome_choices.txt"
if (-not $DryRun) {
  $lines = @(
    "# Choix faits par l'assistant de bienvenue (E51) — $(Get-Date -Format o)",
    "display=$display",
    "capture=$capture",
    "phone=$phone",
    "llm=$llm",
    "cloud_data_policy=$cloudPolicy",
    "ollama_models=$($ollamaModels -join ',')"
  )
  Set-Content -LiteralPath $choiceFile -Value $lines -Encoding UTF8
  Ok "Choix enregistres : $choiceFile"
} else {
  DryNote "Ecrirait les choix dans $choiceFile"
}

# ========================================================================
# ETAPE 7 — MINI-TUTORIEL
# ========================================================================
Step "7/9" "Mini-tutoriel : que fait le systeme et comment l'utiliser"
Say  "Ce que MLOmega fait pour toi :"
Hint "- Memoire de vie : il se souvient des gens, lieux, objets, conversations."
Hint "- En direct : sous-titres, reconnaissance de personnes, rappels au bon moment."
Hint "- La nuit : il consolide la journee (qui, quoi, predictions pour demain)."
Say  "Mot d'eveil : dis ton mot (defaut 'viki') pour ouvrir une fenetre de commande."
Say  "Detecte dans l'ASR francais ; changeable quand tu veux (configs\user_profile.yaml)."
Say  "Commandes vocales cles (apres le mot d'eveil) :"
Hint "- 'configure ma voix'      -> t'enrole comme porteur (attribution correcte des tours)."
Hint "- 'retiens : c'est Sarah'  -> nomme la personne en face (visage + voix)."
Hint "- 'c'est quoi ca ?'        -> decrit ce que tu regardes."
Hint "- 'traduis en direct' / 'stop traduction' -> traduction FR<->EN offline sous le sous-titre."
Hint "- 'ou est <objet>' / 'rejoue 14h30' -> memoire spatiale / replay."
Say  "Gestes de la main :"
Hint "- Paume    : ouvrir/fermer le menu."
Hint "- Balayage : naviguer / cacher."
Hint "- Pincement: zoomer sur la cible."
Say  "Ou voir les suggestions : elles apparaissent discretement en surimpression"
Say  "(cartes de contexte / rappels), pilotees par la couche proactive."

# ========================================================================
# ETAPE 8 — COMMENT QUITTER PROPREMENT
# ========================================================================
Step "8/9" "Comment quitter (le bouton Terminer)"
Warn "Pour finir une session, utilise LE BOUTON 'Terminer' dans l'app."
Say  "Pourquoi c'est important : 'Terminer' declenche le CLOSE-DAY, l'etape qui"
Say  "CONSOLIDE la journee (diarisation de nuit, memoire, predictions). Une simple"
Say  "deconnexion NE consolide PAS : la memoire de la journee resterait incomplete."
Hint "Cote PC, le close-day tourne dans .venv (pas .venv-live) et peut prendre du temps."
Remember "Toujours finir par le bouton 'Terminer' (close-day). Une deconnexion seule ne consolide pas la journee."

# ========================================================================
# ETAPE 9 — LE LENDEMAIN
# ========================================================================
Step "9/9" "Le lendemain (relancer, controler, entretenir)"
Say  "Relancer le matin (dans l'ordre) :"
Hint "powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1"
Hint "ollama serve   # si pas deja en service"
Hint ".\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -BindHost 0.0.0.0 -Port 8710"
Say  "Changer de modeles :"
Hint "ollama pull <modele> ; puis edite configs\user_profile.yaml (llm_model) ou MLOMEGA_OLLAMA_MODEL dans .env."
Say  "Commandes de controle utiles :"
Hint "- Sante : .\scripts\DOCTOR_MLOMEGA_V19.ps1 -Full   (et -Quota pour le stockage)"
Hint "- Metriques live : http://<IP-du-PC>:8710/metrics"
Hint "- Etat session  : http://<IP-du-PC>:8710/session/status"
Hint "- Dashboard memoire (lecture seule) : .\scripts\RUN_DASHBOARD.ps1  -> http://localhost:8720"
Say  "Ta memoire vit dans memory.db :"
Hint "- Chemin : voir MLOMEGA_DB dans .env (par defaut .mlomega_audio_elite\memory.db)."
Hint "- CONSEIL : sauvegarde ce fichier a la main de temps en temps (le backup auto est differe, decision produit)."
Remember "memory.db = ta memoire. Sauvegarde-le manuellement (backup auto differe). Dashboard: scripts\RUN_DASHBOARD.ps1 (:8720)."

# ========================================================================
# RECAP
# ========================================================================
Title "Recapitulatif"
if ($script:Notes.Count -eq 0) {
  Ok "Rien de particulier a retenir : tout est pret."
} else {
  Warn "Points a garder en tete / a finir :"
  foreach ($n in $script:Notes) { Hint "- $n" }
}
Say ""
if ($DryRun) {
  DryNote "DRY-RUN termine : deroule des 9 etapes valide, aucun processus lourd lance."
} else {
  Ok "Assistant termine. Bon demarrage avec MLOmega V19 !"
}
Say "Documentation : README.md (accueil) | docs\OUTSIDE_ACCESS.md (dehors) | docs\PROD_BACKLOG.md (§E51)."
exit 0
