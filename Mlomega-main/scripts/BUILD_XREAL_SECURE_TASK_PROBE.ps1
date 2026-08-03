param(
    [string]$NdkRoot = "C:\Users\wabad\AppData\Local\Android\Sdk\ndk\23.1.7779620"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo "scripts\xreal-compat\native\SecureTaskSurfaceProbe.cpp"
$outDir = Join-Path $repo "scripts\xreal-compat\native\arm64-v8a"
$output = Join-Path $outDir "libmlomega_secure_task_probe.so"
$clang = Join-Path $NdkRoot "toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android29-clang++.cmd"

if (-not (Test-Path -LiteralPath $clang)) {
    throw "Android NDK compiler not found: $clang"
}
if (-not (Test-Path -LiteralPath $source)) {
    throw "Native probe source not found: $source"
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
& $clang `
    -std=c++17 `
    -O2 `
    -fPIC `
    -shared `
    $source `
    -landroid `
    -ldl `
    -llog `
    -o $output
if ($LASTEXITCODE -ne 0) {
    throw "Native probe compilation failed with exit code $LASTEXITCODE"
}

Write-Host "[OK] $output"
