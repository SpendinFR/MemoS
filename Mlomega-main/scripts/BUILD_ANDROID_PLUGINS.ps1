[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$modules = @("livetransport", "reflexvision")
$jdk17 = "C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot"
if (-not (Test-Path (Join-Path $jdk17 "bin\java.exe"))) { throw "JDK 17 absent: $jdk17" }
$env:JAVA_HOME = $jdk17
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$localGradle = Join-Path $Root ".tools\gradle-8.7\bin\gradle.bat"

foreach ($module in $modules) {
  $dir = Join-Path $Root "apps\xr-mobile\android\$module"
  $wrapper = Join-Path $dir "gradlew.bat"
  if (Test-Path $wrapper) { $gradle = $wrapper }
  elseif (Test-Path $localGradle) { $gradle = $localGradle }
  elseif (Get-Command gradle -ErrorAction SilentlyContinue) { $gradle = "gradle" }
  else { throw "Gradle absent. Installe Gradle 8.7/JDK 17 ou genere gradlew dans $dir" }
  Push-Location $dir
  try {
    if ($Clean) { & $gradle clean }
    & $gradle testDebugUnitTest exportUnityRelease
    if ($LASTEXITCODE -ne 0) { throw "Build Android $module echoue ($LASTEXITCODE)" }
  } finally { Pop-Location }
}

$out = Join-Path $Root "apps\xr-mobile\Assets\Plugins\Android"
# Each standalone module resolves its own dependency graph. When both graphs are
# copied into Unity, keep only the highest resolved Kotlin/AndroidX annotation
# artifacts or the final Gradle app build sees duplicate classes.
@(
  "kotlin-stdlib-1.9.24.jar",
  "kotlin-stdlib-jdk7-1.9.10.jar",
  "kotlin-stdlib-jdk8-1.9.10.jar",
  "annotation-jvm-1.8.0.jar"
) | ForEach-Object {
  $duplicate = Join-Path $out $_
  if (Test-Path $duplicate) { Remove-Item -LiteralPath $duplicate -Force }
}
if (-not (Test-Path (Join-Path $out "mlomega-livetransport.aar"))) { throw "AAR livetransport absent" }
if (-not (Test-Path (Join-Path $out "mlomega-reflexvision.aar"))) { throw "AAR reflexvision absent" }
Write-Host "[OK] Plugins Android et dependances exportes vers $out" -ForegroundColor Green
