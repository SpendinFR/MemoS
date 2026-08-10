<#
.SYNOPSIS
  Preflight PC reproductible du Lab XREAL avant de brancher les lunettes.

.DESCRIPTION
  Nettoie les anciens VirtualDisplays MLOmega, desactive DeX, relance Shizuku
  par ADB si necessaire, efface logcat puis lance l'activite XR officielle.
  Le runtime Lab refait les controles critiques sans PC au demarrage.
#>
[CmdletBinding()]
param(
  [string]$Serial = "192.168.1.134:5555",
  [string]$Package = "com.mlomega.xr.worldatelierlabv16cropcinema",
  [switch]$EnableTailscaleAlwaysOn,
  [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adb)) {
  throw "adb introuvable: $adb"
}

if ($Serial -match ":") {
  & $adb connect $Serial | Write-Host
}
if ((& $adb -s $Serial get-state 2>$null) -ne "device") {
  throw "S24 non joignable par adb: $Serial"
}

Write-Host "[1/6] Nettoyage des traces et de l'ancienne session Lab" -ForegroundColor Cyan
& $adb -s $Serial logcat -c
& $adb -s $Serial shell am force-stop $Package

$processes = & $adb -s $Serial shell ps -A
foreach ($line in $processes) {
  if ($line -notmatch "com\.mlomega\.xr\..*:mlomega_(trusted|app_slot_)") {
    continue
  }
  $columns = ($line.Trim() -split "\s+")
  if ($columns.Count -lt 2 -or $columns[1] -notmatch "^\d+$") { continue }
  & $adb -s $Serial shell kill $columns[1] 2>$null
}

Write-Host "[2/6] DeX libere l'ecran XREAL" -ForegroundColor Cyan
foreach ($scope in @("system", "global", "secure")) {
  & $adb -s $Serial shell settings put $scope dex_on_external_display 0
}

Write-Host "[3/6] Shizuku" -ForegroundColor Cyan
$shizuku = (& $adb -s $Serial shell ps -A) -join "`n"
if ($shizuku -notmatch "shizuku_server") {
  & $adb -s $Serial shell sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh
  Start-Sleep -Milliseconds 800
  $shizuku = (& $adb -s $Serial shell ps -A) -join "`n"
}
if ($shizuku -notmatch "shizuku_server") {
  throw "Shizuku n'a pas demarre. Ouvre Shizuku et utilise Demarrer via debogage sans fil."
}
Write-Host "  Shizuku actif" -ForegroundColor Green

Write-Host "[4/6] Tailscale" -ForegroundColor Cyan
$tailscaleInstalled = (& $adb -s $Serial shell pm path com.tailscale.ipn 2>$null) -match "package:"
if ($tailscaleInstalled -and $EnableTailscaleAlwaysOn) {
  & $adb -s $Serial shell settings put secure always_on_vpn_app com.tailscale.ipn
  & $adb -s $Serial shell settings put secure always_on_vpn_lockdown 0
  & $adb -s $Serial shell monkey -p com.tailscale.ipn 1 | Out-Null
  Write-Host "  Tailscale configure en VPN permanent sans verrouillage." -ForegroundColor Green
} elseif ($tailscaleInstalled) {
  $alwaysOn = (& $adb -s $Serial shell settings get secure always_on_vpn_app).Trim()
  Write-Host "  Installe; VPN permanent=$alwaysOn"
} else {
  Write-Warning "Tailscale n'est pas installe sur le S24."
}

Write-Host "[5/6] Verification finale" -ForegroundColor Cyan
$remaining = (& $adb -s $Serial shell ps -A) |
  Select-String "mlomega_trusted|mlomega_app_slot"
if ($remaining) {
  Write-Warning "Des services MLOmega anciens restent visibles; le preflight interne v22 les reapera."
}

if (-not $NoLaunch) {
  Write-Host "[6/6] Lancement NRXRActivity" -ForegroundColor Cyan
  & $adb -s $Serial shell am start -n "$Package/ai.nreal.activitylife.NRXRActivity"
  Write-Host "Branche maintenant les lunettes si elles ne le sont pas deja." -ForegroundColor Green
} else {
  Write-Host "[6/6] Lancement ignore (-NoLaunch)." -ForegroundColor DarkGray
}
