[CmdletBinding()]
param(
  [string]$CorpusUrl = "https://download.kiwix.org/zim/wikipedia/wikipedia_fr_top_mini_2026-04.zim"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolsRoot = Join-Path $ProjectRoot ".tools\kiwix"
$CorpusRoot = Join-Path $ProjectRoot "storage\kiwix"
$Archive = Join-Path $ToolsRoot "kiwix-tools_win-x86_64-3.8.1.zip"
$ToolsUrl = "https://ftp.fau.de/kiwix/release/kiwix-tools/kiwix-tools_win-x86_64-3.8.1.zip"
$CorpusName = [IO.Path]::GetFileName(([Uri]$CorpusUrl).AbsolutePath)
$CorpusPath = Join-Path $CorpusRoot $CorpusName

New-Item -ItemType Directory -Force -Path $ToolsRoot,$CorpusRoot | Out-Null

if (-not (Test-Path -LiteralPath $Archive)) {
  Write-Host "[..] Telechargement kiwix-tools Windows (~18 Mo)..." -ForegroundColor Cyan
  Invoke-WebRequest -Uri $ToolsUrl -OutFile $Archive -UseBasicParsing
}

$KiwixServe = Get-ChildItem -LiteralPath $ToolsRoot -Filter "kiwix-serve.exe" -Recurse -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $KiwixServe) {
  Write-Host "[..] Extraction kiwix-tools..." -ForegroundColor Cyan
  Expand-Archive -LiteralPath $Archive -DestinationPath $ToolsRoot -Force
  $KiwixServe = Get-ChildItem -LiteralPath $ToolsRoot -Filter "kiwix-serve.exe" -Recurse |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $KiwixServe) {
  Write-Host "[FAIL] kiwix-serve.exe absent de l'archive officielle." -ForegroundColor Red
  exit 2
}

if (-not (Test-Path -LiteralPath $CorpusPath)) {
  Write-Host "[..] Telechargement du corpus Wikipedia FR top/mini (~131 Mo)..." -ForegroundColor Cyan
  Invoke-WebRequest -Uri $CorpusUrl -OutFile $CorpusPath -UseBasicParsing
}

Write-Host "[..] Verification SHA-256 du corpus..." -ForegroundColor Cyan
$ChecksumResponse = Invoke-WebRequest -Uri ($CorpusUrl + ".sha256") -UseBasicParsing
$Expected = [regex]::Match([string]$ChecksumResponse.Content, "[A-Fa-f0-9]{64}").Value.ToUpperInvariant()
if (-not $Expected) {
  Write-Host "[FAIL] Checksum officiel Kiwix illisible." -ForegroundColor Red
  exit 2
}
$Observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $CorpusPath).Hash.ToUpperInvariant()
if ($Expected -ne $Observed) {
  Write-Host "[FAIL] SHA-256 corpus invalide; fichier conserve pour diagnostic." -ForegroundColor Red
  exit 2
}

& (Join-Path $PSScriptRoot "CONFIGURE_AUGMENTED_REALITY.ps1") `
  -Mode kiwix -KiwixExe $KiwixServe -Zim $CorpusPath
exit $LASTEXITCODE
