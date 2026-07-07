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

if ($LivePhone) {
  Import-DotEnv
  $Python = Resolve-Python
  if (-not $Python) { Write-Host "[FAIL] Aucun interpreteur Python." -ForegroundColor Red; exit 1 }
  & $Python -c "import aiortc, aiohttp, av, fastapi, uvicorn, numpy, python_multipart, dotenv, faster_whisper, webrtcvad, onnxruntime, rapidocr_onnxruntime"
  if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] Dependances live manquantes dans $Python" -ForegroundColor Red; exit 2 }
  $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -Unique
  Write-Host "[OK] Runtime PhoneOnly reel (aucun fake device)." -ForegroundColor Green
  foreach ($address in $addresses) {
    Write-Host "     Android: http://${address}:$Port" -ForegroundColor Cyan
    Write-Host "     Health : http://${address}:$Port/health"
    Write-Host "     Metrics: http://${address}:$Port/metrics"
  }
  Write-Host "[INFO] Ce lancement ne prouve pas le build Unity/Gradle ni le flux materiel Android." -ForegroundColor Yellow
  & $Python (Join-Path $ProjectRoot "services\live-pc\sessionhub_http.py") --host $BindHost --port $Port --person-id $PersonId
  exit $LASTEXITCODE
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

Write-Host "Usage: .\scripts\RUN_MLOMEGA_V19.ps1 -SimOnly | -LivePhone [-BindHost 0.0.0.0] [-Port 8710]" -ForegroundColor Cyan
exit 0
