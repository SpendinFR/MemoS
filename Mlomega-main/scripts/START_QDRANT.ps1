<#
START_QDRANT.ps1 — start the native Windows Qdrant binary for MLOmega V19.

No Docker: runs tools\qdrant\qdrant.exe with tools\qdrant\config.yaml (storage
under storage\qdrant, git-ignored). Idempotent: if Qdrant already answers on
6333 it does nothing. Starts detached in the background and waits for /healthz.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts\START_QDRANT.ps1

PowerShell 5.1 compatible: no '&&', no ternary operators.
#>
[CmdletBinding()]
param([int]$TimeoutSec = 30)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Exe = Join-Path $ProjectRoot "tools\qdrant\qdrant.exe"
$Config = Join-Path $ProjectRoot "tools\qdrant\config.yaml"
$Health = "http://127.0.0.1:6333/healthz"

function Test-QdrantUp {
  try {
    $r = Invoke-WebRequest -Uri $Health -TimeoutSec 3 -UseBasicParsing
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

if (Test-QdrantUp) {
  Write-Host "[OK] Qdrant deja actif sur 6333." -ForegroundColor Green
  exit 0
}

if (-not (Test-Path $Exe)) { throw "qdrant.exe introuvable: $Exe (voir INSTALL_STATE etape 4)." }
if (-not (Test-Path $Config)) { throw "config.yaml introuvable: $Config." }

# Qdrant resolves storage_path relative to its working directory: set it to the
# project root so ./storage/qdrant/... lands in the foyer.
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "storage\qdrant") | Out-Null
$env:QDRANT__SERVICE__HTTP_PORT = "6333"

# Windows treats environment names case-insensitively, but some launchers can
# still hand PowerShell a process block containing both `Path` and `PATH`.
# Start-Process then builds a case-insensitive dictionary and aborts with
# "key already added" before Qdrant is even spawned. Keep the canonical Windows
# spelling locally; the value is identical and the parent environment is not
# modified by this script process.
$pathKeys = @([Environment]::GetEnvironmentVariables("Process").Keys | Where-Object { $_ -ieq "Path" })
if (($pathKeys -contains "Path") -and ($pathKeys -contains "PATH")) {
  Remove-Item Env:PATH -ErrorAction SilentlyContinue
}

Write-Host "==> Demarrage de Qdrant (natif Windows, sans Docker)..." -ForegroundColor Cyan
$log = Join-Path $ProjectRoot "qdrant.log"
$proc = Start-Process -FilePath $Exe `
  -ArgumentList @("--config-path", $Config) `
  -WorkingDirectory $ProjectRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $log `
  -RedirectStandardError (Join-Path $ProjectRoot "qdrant.err.log") `
  -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  if (Test-QdrantUp) {
    Write-Host "[OK] Qdrant demarre (PID $($proc.Id)), /healthz 200 sur 6333." -ForegroundColor Green
    exit 0
  }
  Start-Sleep -Milliseconds 700
}

Write-Host "[FAIL] Qdrant n'a pas repondu sur /healthz apres ${TimeoutSec}s. Voir $log" -ForegroundColor Red
exit 1
