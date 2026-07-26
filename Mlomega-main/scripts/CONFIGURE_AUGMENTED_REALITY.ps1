[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("status", "kiwix", "device", "studio")]
  [string]$Mode,
  [string]$KiwixExe = "",
  [string]$Zim = "",
  [string]$Label = "",
  [string]$EntityId = "",
  [string]$HomeAssistantUrl = "http://homeassistant.local:8123",
  [string]$ReleaseId = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv-live\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
  Write-Host "[FAIL] Aucun Python MLOmega disponible." -ForegroundColor Red
  exit 2
}
$Configurator = Join-Path $ProjectRoot "scripts\configure_augmented_reality.py"

switch ($Mode) {
  "status" {
    & $Python $Configurator status
  }
  "kiwix" {
    if (-not $KiwixExe -or -not $Zim) {
      Write-Host "[FAIL] Fournis -KiwixExe et -Zim." -ForegroundColor Red
      exit 2
    }
    & $Python $Configurator kiwix-config --executable $KiwixExe --zim $Zim
  }
  "device" {
    if (-not $Label -or -not $EntityId) {
      Write-Host "[FAIL] Fournis -Label et -EntityId." -ForegroundColor Red
      exit 2
    }
    & $Python $Configurator device-add --label $Label --entity-id $EntityId --base-url $HomeAssistantUrl
  }
  "studio" {
    if (-not $ReleaseId) {
      Write-Host "[FAIL] Fournis -ReleaseId." -ForegroundColor Red
      exit 2
    }
    & $Python $Configurator studio-init --release-id $ReleaseId
  }
}
exit $LASTEXITCODE
