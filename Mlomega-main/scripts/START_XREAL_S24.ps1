<#
.SYNOPSIS
  Point d'entree operateur unique pour Galaxy S24 + XREAL One Pro/Eye.

.DESCRIPTION
  Reveil Ollama si necessaire, puis delegue sans modifier le pipeline valide a
  RUN_MLOMEGA_V19.ps1 avec LivePhone + AugmentedReality. Le profil Memory Lite
  est le choix quotidien rapide; Full reste disponible explicitement.

  Exemples:
    .\scripts\START_XREAL_S24.ps1
    .\scripts\START_XREAL_S24.ps1 -MemoryProfile full
    .\scripts\START_XREAL_S24.ps1 -Pro -MemoryProfile lite
#>
[CmdletBinding()]
param(
  [ValidateSet("full", "lite")][string]$MemoryProfile = "lite",
  [switch]$Pro,
  [ValidateSet("pro", "flash")][string]$ProTextModel = "pro",
  [ValidateSet("stop", "flash", "local")][string]$CloudOnBudget = "stop",
  [double]$CloudBudgetEur = 1.50,
  [string]$StudioReleaseId = "",
  [string]$PersonId = "me",
  [string]$BindHost = "0.0.0.0",
  [int]$Port = 8710,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Runner = Join-Path $ScriptDir "RUN_MLOMEGA_V19.ps1"
Set-Location $ProjectRoot

function Test-OllamaReady {
  try {
    $null = Invoke-WebRequest `
      -UseBasicParsing `
      -Uri "http://127.0.0.1:11434/api/version" `
      -TimeoutSec 3
    return $true
  }
  catch {
    return $false
  }
}

function Resolve-OllamaExecutable {
  $command = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }

  $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path -LiteralPath $candidate) { return $candidate }
  return $null
}

function Test-DotEnvKey {
  param([Parameter(Mandatory = $true)][string]$Name)
  $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not [string]::IsNullOrWhiteSpace($processValue)) { return $true }
  $path = Join-Path $ProjectRoot ".env"
  if (-not (Test-Path -LiteralPath $path)) { return $false }
  foreach ($line in Get-Content -LiteralPath $path) {
    if ($line -match ("^\s*" + [Regex]::Escape($Name) + "\s*=\s*(.+?)\s*$")) {
      $value = $Matches[1].Trim().Trim('"').Trim("'")
      return -not [string]::IsNullOrWhiteSpace($value)
    }
  }
  return $false
}

$runArgs = @(
  "-LivePhone",
  "-AugmentedReality",
  "-MemoryProfile", $MemoryProfile,
  "-PersonId", $PersonId,
  "-BindHost", $BindHost,
  "-Port", [string]$Port
)
if ($Pro) {
  $runArgs += @(
    "-Pro",
    "-ProTextModel", $ProTextModel,
    "-CloudBudgetEur", [string]$CloudBudgetEur,
    "-CloudOnBudget", $CloudOnBudget
  )
}
if (-not [string]::IsNullOrWhiteSpace($StudioReleaseId)) {
  $runArgs += @("-StudioReleaseId", $StudioReleaseId)
}

Write-Host ""
Write-Host "MLOmega S24 + XREAL" -ForegroundColor Cyan
Write-Host "  Memory : $MemoryProfile"
Write-Host "  CloseDay: $(if ($Pro) { "PRO/$ProTextModel, plafond $CloudBudgetEur EUR" } else { "Local" })"
Write-Host "  AR PC  : activee"
Write-Host "  Port   : $BindHost`:$Port"
Write-Host ""

if ($DryRun) {
  Write-Host "[DRY-RUN] $Runner $($runArgs -join ' ')" -ForegroundColor Yellow
  exit 0
}

if (-not (Test-Path -LiteralPath $Runner)) {
  throw "Lanceur principal introuvable: $Runner"
}

if ($Pro) {
  $missing = @()
  foreach ($key in @("DEEPSEEK_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")) {
    if (-not (Test-DotEnvKey -Name $key)) { $missing += $key }
  }
  if ($missing.Count -gt 0) {
    throw "Mode PRO impossible: ajoute dans .env les cles manquantes: $($missing -join ', '). Ne les committe jamais."
  }
}

if (-not (Test-OllamaReady)) {
  $ollama = Resolve-OllamaExecutable
  if (-not $ollama) {
    throw "Ollama ne repond pas et ollama.exe est introuvable. Installe/ouvre Ollama puis relance cette commande."
  }
  Write-Host "[START] Ollama ne repond pas; demarrage du service..." -ForegroundColor Yellow
  Start-Process `
    -FilePath $ollama `
    -ArgumentList @("serve") `
    -WindowStyle Hidden | Out-Null

  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline -and -not (Test-OllamaReady)) {
    Start-Sleep -Seconds 1
  }
  if (-not (Test-OllamaReady)) {
    throw "Ollama n'a pas repondu en 30 s. Ouvre l'application Ollama, verifie le port 11434, puis relance."
  }
  Write-Host "[OK] Ollama repond." -ForegroundColor Green
}

Write-Host "[START] Preflight + Qdrant + AR + SessionHub..." -ForegroundColor Cyan
& $Runner @runArgs
exit $LASTEXITCODE
