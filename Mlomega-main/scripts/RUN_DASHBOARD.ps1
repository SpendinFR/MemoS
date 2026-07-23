# MLOmega V19 - E50
# Lance le dashboard memoire lecture seule (apps/memory-dashboard) sur le port 8720.
# - installe streamlit/pandas dans .venv-live s'ils manquent (idempotent)
# - pose MLOMEGA_DB depuis le .env du projet si absent de l'environnement
param(
    [int]$Port = 8720,
    [string]$Database = "",
    [string]$ShadowReport = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv-live\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv-live introuvable ($py) - lance d'abord scripts\INSTALL_MLOMEGA_V19_WINDOWS.ps1" }

# Dependances (idempotent, rapide si deja presentes)
& $py -c "import streamlit, pandas" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[dashboard] installation de streamlit/pandas dans .venv-live..."
    & $py -m pip install --quiet -r (Join-Path $root "apps\memory-dashboard\requirements.txt")
}

# MLOMEGA_DB depuis le .env si non defini (l'app le refait aussi, ceinture+bretelles)
if (-not $env:MLOMEGA_DB) {
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        $line = Select-String -Path $envFile -Pattern '^\s*MLOMEGA_DB\s*=' | Select-Object -First 1
        if ($line) { $env:MLOMEGA_DB = ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'") }
    }
}
if ($Database) { $env:MLOMEGA_DB = $Database }
if ($env:MLOMEGA_DB) { Write-Host "[dashboard] base : $env:MLOMEGA_DB (lecture seule stricte)" }
else { Write-Host "[dashboard] MLOMEGA_DB non defini - indique la base dans la barre laterale." }

Write-Host "[dashboard] http://localhost:$Port"
$app = Join-Path $root "apps\memory-dashboard\app.py"
$args = @("-m", "streamlit", "run", $app, "--server.port", "$Port", "--server.headless", "true")
$shaBefore = $null
if ($env:MLOMEGA_DB -and (Test-Path -LiteralPath $env:MLOMEGA_DB)) {
    $shaBefore = (Get-FileHash -LiteralPath $env:MLOMEGA_DB -Algorithm SHA256).Hash
    Write-Host "[dashboard] SHA avant : $shaBefore"
    $args += @("--", "--db", $env:MLOMEGA_DB)
    if ($ShadowReport) { $args += @("--shadow-report", $ShadowReport) }
}
try {
    & $py @args
}
finally {
    if ($shaBefore) {
        $shaAfter = (Get-FileHash -LiteralPath $env:MLOMEGA_DB -Algorithm SHA256).Hash
        Write-Host "[dashboard] SHA apres : $shaAfter"
        if ($shaAfter -ne $shaBefore) {
            throw "La base a change pendant la session Dashboard; preuve lecture seule invalidee."
        }
        Write-Host "[dashboard] preuve lecture seule : SHA identique"
    }
}
