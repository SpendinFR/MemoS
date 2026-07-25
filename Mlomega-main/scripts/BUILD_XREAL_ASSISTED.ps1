<# Two-pass XREAL product build with endpoint injection and artifact restoration. #>
[CmdletBinding()]
param(
  [string]$PcHost = '192.168.1.199',
  [ValidateRange(1,65535)][int]$PcPort = 8710,
  [string]$UnityExe = 'C:\Program Files\Unity\Hub\Editor\6000.0.23f1\Editor\Unity.exe',
  [string]$ProjectPath,
  [switch]$ProviderGate,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path
if (-not $ProjectPath) { $ProjectPath = Join-Path $ProjectRoot 'apps\xr-mobile' }
$ProjectPath = [IO.Path]::GetFullPath($ProjectPath)
$ApkName = if ($ProviderGate) { 'mlomega-xreal-provider-gate.apk' } else { 'mlomega-xreal.apk' }
$LogPrefix = if ($ProviderGate) { 'xreal-provider-gate' } else { 'xreal' }
$Apk = Join-Path $ProjectPath ('build\android\' + $ApkName)
$PrepLog = Join-Path $ProjectPath ($LogPrefix + '-prep.log')
$BuildLog = Join-Path $ProjectPath ($LogPrefix + '-build.log')

if ($DryRun) {
  $profile = if ($ProviderGate) { 'isolated provider gate' } else { 'product' }
  Write-Host "[DRY] XREAL two-pass $profile build: $UnityExe" -ForegroundColor Magenta
  Write-Host "[DRY] PrepareDefines -> BuildApk; endpoint=$PcHost`:$PcPort; output=$Apk" -ForegroundColor Magenta
  Write-Host "[DRY] ProjectSettings/manifest/lock/scenes/config sont restaures apres le build." -ForegroundColor Magenta
  exit 0
}

if (-not (Test-Path $UnityExe)) { throw "Unity 6000.0.23f1 introuvable: $UnityExe" }
$Sdk = Join-Path $ProjectPath 'Packages\xreal-sdk\com.xreal.xr.tar.gz'
if (-not (Test-Path $Sdk)) {
  throw "SDK XREAL proprietaire absent: $Sdk. Telecharge le SDK 3.1.0 depuis ton compte developpeur XREAL."
}
if (Get-Process Unity -ErrorAction SilentlyContinue) {
  throw "Une instance Unity est ouverte. Ferme-la avant le build batchmode (Temp/UnityLockfile)."
}

$snapshotRoot = Join-Path $env:TEMP ('mlomega-xreal-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $snapshotRoot | Out-Null
$files = @(
  'Packages\manifest.json', 'Packages\packages-lock.json',
  'ProjectSettings\ProjectSettings.asset', 'ProjectSettings\EditorBuildSettings.asset',
  'ProjectSettings\QualitySettings.asset',
  'Assets\XR\XRGeneralSettingsPerBuildTarget.asset',
  'Assets\XR\Resources.meta',
  'Assets\XR\Resources\XRSimulationRuntimeSettings.asset',
  'Assets\XR\Resources\XRSimulationRuntimeSettings.asset.meta',
  'Assets\XR\UserSimulationSettings.meta',
  'Assets\XR\UserSimulationSettings\Resources.meta',
  'Assets\XR\UserSimulationSettings\Resources\XRSimulationPreferences.asset',
  'Assets\XR\UserSimulationSettings\Resources\XRSimulationPreferences.asset.meta',
  'Assets\Scenes\PhoneOnly.unity', 'Assets\Scenes\PhoneOnly.unity.meta',
  'Assets\Scenes\XrealProduct.unity', 'Assets\Scenes\XrealProduct.unity.meta',
  'Assets\Scenes\Generated.meta',
  'Assets\Scenes\Generated\AugmentedRealityProviderGate.unity',
  'Assets\Scenes\Generated\AugmentedRealityProviderGate.unity.meta',
  'Assets\Config\MLOmegaPhoneOnly.asset', 'Assets\Config\MLOmegaPhoneOnly.asset.meta',
  'Assets\Config\MLOmegaXreal.asset', 'Assets\Config\MLOmegaXreal.asset.meta'
)
$existed = @{}
foreach ($file in $files) {
  $source = Join-Path $ProjectPath $file
  $existed[$file] = Test-Path $source
  if ($existed[$file]) {
    $copy = Join-Path $snapshotRoot $file
    New-Item -ItemType Directory -Path (Split-Path -Parent $copy) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $copy -Force
  }
}

$oldHost = $env:MLOMEGA_PC_HOST
$oldPort = $env:MLOMEGA_PC_PORT
$oldProviderGate = $env:MLOMEGA_XREAL_PROVIDER_GATE
$savedPath = $env:Path
[Environment]::SetEnvironmentVariable('PATH',$null,[EnvironmentVariableTarget]::Process)
[Environment]::SetEnvironmentVariable('Path',$savedPath,[EnvironmentVariableTarget]::Process)
$env:MLOMEGA_PC_HOST = $PcHost
$env:MLOMEGA_PC_PORT = [string]$PcPort
if ($ProviderGate) {
  $env:MLOMEGA_XREAL_PROVIDER_GATE = '1'
} else {
  Remove-Item Env:MLOMEGA_XREAL_PROVIDER_GATE -ErrorAction SilentlyContinue
}

function Run-UnityPass([string]$Method, [string]$Log) {
  $p = Start-Process -FilePath $UnityExe -ArgumentList @(
    '-batchmode','-quit','-projectPath',$ProjectPath,
    '-executeMethod',$Method,'-logFile',$Log
  ) -Wait -PassThru -NoNewWindow
  if ($p.ExitCode -ne 0) {
    $tail = if (Test-Path $Log) { (Get-Content -LiteralPath $Log -Tail 80) -join "`n" } else { 'log absent' }
    if ($tail -match 'No valid Unity Editor license') {
      throw "Licence Unity invalide/expiree. Ouvre Unity Hub connecte une fois, puis relance."
    }
    throw "Unity $Method a echoue (exit $($p.ExitCode)). Log: $Log`n$tail"
  }
}

try {
  Set-Location $ProjectPath
  Write-Host "[INFO] XREAL passe 1/2: SDK + define" -ForegroundColor Cyan
  Run-UnityPass 'MLOmega.XR.Editor.AndroidBuildXreal.PrepareDefines' $PrepLog
  $profile = if ($ProviderGate) { 'gate provider isole' } else { 'APK produit' }
  Write-Host "[INFO] XREAL passe 2/2: $profile" -ForegroundColor Cyan
  Run-UnityPass 'MLOmega.XR.Editor.AndroidBuildXreal.BuildApk' $BuildLog
  if (-not (Test-Path $Apk)) { throw "Unity exit 0 mais APK absente: $Apk" }
  $hash = (Get-FileHash -LiteralPath $Apk -Algorithm SHA256).Hash
  Write-Host "[OK] APK XREAL $profile`: $Apk (SHA-256 $hash)" -ForegroundColor Green
} finally {
  Set-Location $ProjectRoot
  if ($null -eq $oldHost) { Remove-Item Env:MLOMEGA_PC_HOST -ErrorAction SilentlyContinue } else { $env:MLOMEGA_PC_HOST = $oldHost }
  if ($null -eq $oldPort) { Remove-Item Env:MLOMEGA_PC_PORT -ErrorAction SilentlyContinue } else { $env:MLOMEGA_PC_PORT = $oldPort }
  if ($null -eq $oldProviderGate) { Remove-Item Env:MLOMEGA_XREAL_PROVIDER_GATE -ErrorAction SilentlyContinue } else { $env:MLOMEGA_XREAL_PROVIDER_GATE = $oldProviderGate }
  foreach ($file in $files) {
    $target = Join-Path $ProjectPath $file
    $copy = Join-Path $snapshotRoot $file
    if ($existed[$file]) { Copy-Item -LiteralPath $copy -Destination $target -Force }
    elseif (Test-Path $target) { Remove-Item -LiteralPath $target -Force }
  }
  $resolvedSnapshot = (Resolve-Path -LiteralPath $snapshotRoot).Path
  $resolvedTemp = (Resolve-Path -LiteralPath $env:TEMP).Path
  if ($resolvedSnapshot.StartsWith($resolvedTemp,[StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedSnapshot -Recurse -Force
  }
}
