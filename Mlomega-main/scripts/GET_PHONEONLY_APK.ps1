<# Download the latest published PhoneOnly APK and verify its SHA-256 sidecar. #>
[CmdletBinding()]
param(
  [string]$Destination,
  [string]$Repository = 'SpendinFR/MemoS',
  [string]$AssetName = 'mlomega-phoneonly.apk',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
if (-not $Destination) {
  $Destination = Join-Path $ProjectRoot 'apps\xr-mobile\build\android\mlomega-phoneonly.apk'
}
$Destination = [IO.Path]::GetFullPath($Destination)
$Api = "https://api.github.com/repos/$Repository/releases/latest"
$HashAssetName = "$AssetName.sha256"

if ($DryRun) {
  Write-Host "[DRY] GitHub Release $Repository/latest -> $Destination" -ForegroundColor Magenta
  Write-Host "[DRY] Assets requis: $AssetName + $HashAssetName; SHA-256 verifie avant bascule." -ForegroundColor Magenta
  exit 0
}

if (Test-Path $Destination) {
  $existing = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
  Write-Host "[OK] APK locale conservee: $Destination (SHA-256 $existing)" -ForegroundColor Green
  exit 0
}

$directory = Split-Path -Parent $Destination
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$download = "$Destination.download"
$hashDownload = "$Destination.sha256.download"
try {
  Write-Host "[INFO] Lecture de la derniere Release GitHub $Repository ..." -ForegroundColor Cyan
  $release = Invoke-RestMethod -Uri $Api -Headers @{'User-Agent'='MLOmega-WELCOME'}
  $apkAsset = @($release.assets | Where-Object { $_.name -eq $AssetName }) | Select-Object -First 1
  $hashAsset = @($release.assets | Where-Object { $_.name -eq $HashAssetName }) | Select-Object -First 1
  if (-not $apkAsset -or -not $hashAsset) {
    throw "Release '$($release.tag_name)' incomplete: assets $AssetName/$HashAssetName absents."
  }
  Invoke-WebRequest -Uri $apkAsset.browser_download_url -OutFile $download -UseBasicParsing
  Invoke-WebRequest -Uri $hashAsset.browser_download_url -OutFile $hashDownload -UseBasicParsing
  $hashText = Get-Content -LiteralPath $hashDownload -Raw
  $match = [regex]::Match($hashText, '(?i)\b[0-9a-f]{64}\b')
  if (-not $match.Success) { throw "Sidecar SHA-256 invalide pour $AssetName." }
  $expected = $match.Value.ToUpperInvariant()
  $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToUpperInvariant()
  if ($actual -ne $expected) { throw "SHA-256 APK invalide: attendu=$expected observe=$actual" }
  Move-Item -LiteralPath $download -Destination $Destination -Force
  Write-Host "[OK] APK $($release.tag_name) verifiee: $Destination (SHA-256 $actual)" -ForegroundColor Green
} catch {
  Write-Host "[FAIL] Telechargement APK impossible: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "       Sans reseau, copie une APK verifiee a cet emplacement puis relance WELCOME." -ForegroundColor Yellow
  exit 2
} finally {
  Remove-Item -LiteralPath $download,$hashDownload -Force -ErrorAction SilentlyContinue
}

