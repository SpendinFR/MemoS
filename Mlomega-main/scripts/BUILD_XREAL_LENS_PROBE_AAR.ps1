param(
  [string]$PrivateLibrary = "",
  [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$module = Join-Path $root "apps\xr-mobile\android\xreal-lens-probe"
if (-not $PrivateLibrary) {
  $PrivateLibrary = Join-Path $root `
    "tmp_ControlGlasses31_decoded\lib\arm64-v8a\libnr_service.so"
}
if (-not $Output) {
  $Output = Join-Path $root `
    "apps\xr-mobile\Assets\Plugins\Android\xreal-private-lens-probe.aar"
}
$PrivateLibrary = [IO.Path]::GetFullPath($PrivateLibrary)
$Output = [IO.Path]::GetFullPath($Output)
if (-not (Test-Path -LiteralPath $PrivateLibrary -PathType Leaf)) {
  throw "libnr_service.so absent: $PrivateLibrary"
}
$expected = "D87965AAE92FC07A61F4A4542A88D698C406FC3849D9274248746B580E357135"
$actual = (Get-FileHash -LiteralPath $PrivateLibrary -Algorithm SHA256).Hash
if ($actual -ne $expected) {
  throw "Version libnr_service.so inconnue: $actual (attendu $expected)"
}

$jdk = "C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot"
$javac = Join-Path $jdk "bin\javac.exe"
$jar = Join-Path $jdk "bin\jar.exe"
if (-not (Test-Path -LiteralPath $javac)) { throw "javac absent: $javac" }
if (-not (Test-Path -LiteralPath $jar)) { throw "jar absent: $jar" }
$androidJar = Get-ChildItem `
  "C:\Users\wabad\AppData\Local\Android\Sdk\platforms" `
  -Directory -ErrorAction Stop |
  Sort-Object Name -Descending |
  ForEach-Object { Join-Path $_.FullName "android.jar" } |
  Where-Object { Test-Path -LiteralPath $_ } |
  Select-Object -First 1
if (-not $androidJar) { throw "android.jar absent" }

$work = Join-Path $root "tmp-xreal-lens-probe-aar"
if (Test-Path -LiteralPath $work) {
  Remove-Item -LiteralPath $work -Recurse -Force
}
$classes = Join-Path $work "classes"
$stage = Join-Path $work "aar"
$jni = Join-Path $stage "jni\arm64-v8a"
New-Item -ItemType Directory -Path $classes,$jni -Force | Out-Null

$sources = Get-ChildItem -LiteralPath (Join-Path $module "src\main\java") `
  -Recurse -Filter "*.java" -File | ForEach-Object FullName
& $javac -encoding UTF-8 -source 11 -target 11 `
  -classpath $androidJar -d $classes $sources
if ($LASTEXITCODE -ne 0) { throw "Compilation Java lens probe echouee" }

Push-Location $classes
try { & $jar cf (Join-Path $stage "classes.jar") . }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "Creation classes.jar echouee" }
Copy-Item -LiteralPath (Join-Path $module "AndroidManifest.xml") `
  -Destination (Join-Path $stage "AndroidManifest.xml")
Copy-Item -LiteralPath $PrivateLibrary `
  -Destination (Join-Path $jni "libnr_service.so")

$outDir = Split-Path -Parent $Output
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
if (Test-Path -LiteralPath $Output) { Remove-Item -LiteralPath $Output -Force }
Push-Location $stage
try { & $jar cf $Output . }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "Creation AAR lens probe echouee" }

Write-Host "[OK] AAR prive isole: $Output" -ForegroundColor Green
Write-Host "     libnr_service SHA256=$actual" -ForegroundColor DarkGray
