<#
RUN_MLOMEGA_V19 — launcher.

  -SimOnly : run the Lot 1 SimOnly checkpoint demo (simonly_demo_v19.py) in the
             correct venv (.venv-live if present, else .venv, else PATH python).
             Verifies configs/user_profile.yaml first; offers setup if missing.
  -Xr      : honest message "Lot 3 requis" and a non-zero exit code.

PowerShell 5.1 compatible: no '&&', no ternary operators.
#>
[CmdletBinding()]
param(
  [switch]$SimOnly,
  [Alias("PhoneOnly")][switch]$LivePhone,
  [switch]$Xr,
  [switch]$Pro,
  [ValidateSet("pro", "flash")][string]$ProTextModel = "pro",
  [ValidateSet("stop", "flash", "local")][string]$CloudOnBudget = "stop",
  [double]$CloudBudgetEur = 1.50,
  [string]$PersonId = "me",
  [string]$BindHost = "0.0.0.0",
  [int]$Port = 8710
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $ProjectRoot

function Resolve-Python {
  $live = Join-Path $ProjectRoot ".venv-live\Scripts\python.exe"
  if (Test-Path $live) { return $live }
  $core = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (Test-Path $core) { return $core }
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  return $null
}

if ($Xr) {
  Write-Host "[FAIL] Mode -Xr indisponible : le live XR (XREAL/S25/Unity) est le Lot 3 requis." -ForegroundColor Red
  Write-Host "        Aucun materiel n'est pilote par ce script. Utilise -SimOnly pour le chemin valide Lot 1." -ForegroundColor Yellow
  exit 3
}

function Import-DotEnv {
  $path = Join-Path $ProjectRoot ".env"
  if (-not (Test-Path $path)) { return }
  foreach ($line in Get-Content $path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
    $parts = $trimmed.Split("=", 2)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
  }
}

function Remove-KnownBlackholeProxy {
  foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) { continue }
    $candidate = $value
    if (-not $candidate.Contains("://")) { $candidate = "http://$candidate" }
    try {
      $uri = [Uri]$candidate
      if (($uri.Host -in @("127.0.0.1", "localhost", "::1")) -and $uri.Port -eq 9) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
        Write-Host "[WARN] Proxy black-hole $name retire avant FirstTry." -ForegroundColor Yellow
      }
    }
    catch {
      # Le preflight Python donnera le diagnostic guide et bloquera proprement.
    }
  }
}

function Initialize-CoreCudaPath {
  $directories = New-Object System.Collections.Generic.List[string]
  foreach ($venv in @(".venv", ".venv-live")) {
    foreach ($relative in @(
      "Lib\site-packages\nvidia\cudnn\bin",
      "Lib\site-packages\nvidia\cublas\bin",
      "Lib\site-packages\nvidia\cuda_runtime\bin",
      "Lib\site-packages\nvidia\cuda_nvrtc\bin",
      "Lib\site-packages\torch\lib"
    )) {
      $path = Join-Path (Join-Path $ProjectRoot $venv) $relative
      if ((Test-Path $path) -and -not $directories.Contains($path)) { $directories.Add($path) }
    }
  }
  if ($directories.Count -gt 0) {
    $prefix = [string]::Join([IO.Path]::PathSeparator, $directories)
    [Environment]::SetEnvironmentVariable("PATH", $prefix + [IO.Path]::PathSeparator + $env:PATH, "Process")
  }
}

if ($LivePhone) {
  Import-DotEnv
  if ($Pro) {
    $env:MLOMEGA_CLOUD_MODE = "pro"
    $env:MLOMEGA_PRO_CLOSEDAY = "1"
    if ($ProTextModel -eq "flash") { $env:MLOMEGA_PRO_TEXT_MODEL = "deepseek-v4-flash" }
    else { $env:MLOMEGA_PRO_TEXT_MODEL = "deepseek-v4-pro" }
    $env:MLOMEGA_DEEP_AUDIO_TRANSCRIBER = "groq"
    if (-not $env:MLOMEGA_GROQ_WHISPER_MODEL) { $env:MLOMEGA_GROQ_WHISPER_MODEL = "whisper-large-v3" }
    $env:MLOMEGA_CLOUD_VLM_PROVIDER = "gemini"
    if (-not $env:MLOMEGA_GEMINI_VLM_MODEL) { $env:MLOMEGA_GEMINI_VLM_MODEL = "gemini-3.1-flash-lite" }
    $env:MLOMEGA_CLOUD_DAILY_BUDGET_EUR = [string]$CloudBudgetEur
    $env:MLOMEGA_CLOUD_ON_BUDGET = $CloudOnBudget
    Write-Host "[PRO] CloseDay cloud opt-in: DeepSeek/$($env:MLOMEGA_PRO_TEXT_MODEL), Groq Whisper, Gemini Flash-Lite; live Ollama unchanged; budget $CloudBudgetEur EUR." -ForegroundColor Cyan
  }
  Remove-KnownBlackholeProxy
  Initialize-CoreCudaPath
  # Orchestration GPU par phase active par defaut en production (preflight teste
  # P1 puis l'arrete; live = Ollama seul; nuit = P1/VLM en sequence). "0" = rollback.
  if (-not $env:MLOMEGA_GPU_PHASE_ORCHESTRATION) { $env:MLOMEGA_GPU_PHASE_ORCHESTRATION = "1" }
  # Le preflight publie un recu atomique; SessionHub le valide et ne recharge
  # jamais Whisper/YOLOX en concurrence avec la capture.
  if (-not $env:MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING) { $env:MLOMEGA_REQUIRE_AI_READY_FOR_PAIRING = "1" }
  $Python = Resolve-Python
  if (-not $Python) { Write-Host "[FAIL] Aucun interpreteur Python." -ForegroundColor Red; exit 1 }
  & $Python -c "import aiortc, aiohttp, av, fastapi, uvicorn, numpy, python_multipart, dotenv, faster_whisper, webrtcvad, onnxruntime, rapidocr_onnxruntime"
  if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] Dependances live manquantes dans $Python" -ForegroundColor Red; exit 2 }
  $startQdrant = Join-Path $ScriptDir "START_QDRANT.ps1"
  if (-not (Test-Path $startQdrant)) {
    Write-Host "[FAIL] START_QDRANT.ps1 introuvable." -ForegroundColor Red
    exit 4
  }
  Write-Host "[..] Demarrage/verif Qdrant local..." -ForegroundColor Cyan
  & $startQdrant -TimeoutSec 30
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Qdrant local n'est pas pret; voir qdrant.log/qdrant.err.log." -ForegroundColor Red
    exit 4
  }
  Write-Host "[..] Preflight strict PhoneOnly (DB, modeles, CUDA, ASR, TTS, Ollama, Qdrant, disque, CloseDay)..." -ForegroundColor Cyan
  & $Python (Join-Path $ProjectRoot "scripts\check_phoneonly_readiness.py") --person-id $PersonId --deep
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] FirstTry refuse de demarrer avec une chaine IA incomplete." -ForegroundColor Red
    Write-Host "       Lis les lignes [FIX] ci-dessus : proxy/HF gated+cache, backend JSON," -ForegroundColor Yellow
    Write-Host "       VLM, CUDA/cuDNN, disque, Qdrant et venv sont verifies avant capture." -ForegroundColor Yellow
    exit 4
  }
  $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -Unique
  Write-Host "[OK] Runtime PhoneOnly reel (aucun fake device)." -ForegroundColor Green
  foreach ($address in $addresses) {
    Write-Host "     Android: http://${address}:$Port" -ForegroundColor Cyan
    Write-Host "     Health : http://${address}:$Port/health"
    Write-Host "     Ready  : http://${address}:$Port/ready"
    Write-Host "     Metrics: http://${address}:$Port/metrics"
    Write-Host "     Companion: http://${address}:8706/"
  }
  Write-Host "[INFO] Ce lancement ne prouve pas le build Unity/Gradle ni le flux materiel Android." -ForegroundColor Yellow
  $companion = Start-Process -FilePath $Python -ArgumentList @(
    (Join-Path $ProjectRoot "services\live-pc\delivery_adapter.py"), "--host", $BindHost, "--port", "8706"
  ) -WindowStyle Hidden -PassThru
  $companionReady = $false
  for ($i = 0; $i -lt 20; $i++) {
    try {
      $probe = Invoke-WebRequest -Uri "http://127.0.0.1:8706/health" -UseBasicParsing -TimeoutSec 1
      if ($probe.StatusCode -eq 200) { $companionReady = $true; break }
    }
    catch { Start-Sleep -Milliseconds 250 }
  }
  if (-not $companionReady) {
    if ($companion -and -not $companion.HasExited) { Stop-Process -Id $companion.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "[FAIL] Companion-web n'a pas démarré sur http://127.0.0.1:8706/." -ForegroundColor Red
    exit 5
  }
  try {
    & $Python (Join-Path $ProjectRoot "services\live-pc\sessionhub_http.py") --host $BindHost --port $Port --person-id $PersonId
    $serverCode = $LASTEXITCODE
  }
  finally {
    if ($companion -and -not $companion.HasExited) { Stop-Process -Id $companion.Id -Force -ErrorAction SilentlyContinue }
  }
  exit $serverCode
}

if ($SimOnly) {
  $Python = Resolve-Python
  if (-not $Python) { Write-Host "[FAIL] Aucun interpreteur Python (.venv-live/.venv/PATH). Lance scripts\INSTALL_MLOMEGA_V19_WINDOWS.ps1." -ForegroundColor Red; exit 1 }
  Write-Host "[OK]   Interpreteur: $Python" -ForegroundColor Green

  $profilePath = Join-Path $ProjectRoot "configs\user_profile.yaml"
  if (-not (Test-Path $profilePath)) {
    Write-Host "[WARN] configs\user_profile.yaml absent. Generation d'un profil par defaut (phone_only)." -ForegroundColor Yellow
    & (Join-Path $ScriptDir "setup_profile.ps1") -Defaults -Display companion_web -Capture none | Out-Null
  }
  if (Test-Path $profilePath) { Write-Host "[OK]   Profil: $profilePath" -ForegroundColor Green }

  Write-Host "[..]   Demarrage SimOnly : fake device -> UIIntent -> companion-web simulator -> UIReceipt." -ForegroundColor Cyan
  & $Python (Join-Path $ScriptDir "simonly_demo_v19.py")
  $code = $LASTEXITCODE
  if ($code -eq 0) { Write-Host "[OK]   SimOnly termine (receipt persiste dans les tables feedback V18.8)." -ForegroundColor Green }
  else { Write-Host "[FAIL] SimOnly a echoue (code $code)." -ForegroundColor Red }
  exit $code
}

Write-Host "Usage: .\scripts\RUN_MLOMEGA_V19.ps1 -SimOnly | -LivePhone [-Pro] [-CloudBudgetEur 1.50] [-CloudOnBudget stop|flash|local]" -ForegroundColor Cyan
exit 0
