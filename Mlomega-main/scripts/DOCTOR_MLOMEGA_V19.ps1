<#
DOCTOR_MLOMEGA_V19 — real health checks for the V19 live services.

Emits [OK]/[WARN]/[FAIL] per check and a non-zero exit code if any FAIL.
WARN never fails the run. Flags select subsets:

  -Full      : run everything below
  -Memory    : delivery queue table + DB checks
  -Xr        : XR readiness (WARN "non testable sans lunettes" — never a fake OK)
  -Vision    : GPU/detector readiness
  -Delivery  : delivery queue table accessible
  -Quota     : storage footprint (DB / models / evidence / day-buffer) vs profile thresholds

With no flags, the base checks always run (Python, .venv-live, contracts,
GPU probe, Qdrant, Ollama, profile).

PowerShell 5.1 compatible: no '&&', no ternary operators.
#>
[CmdletBinding()]
param(
  [switch]$Full, [switch]$Memory, [switch]$Xr, [switch]$Vision, [switch]$World, [switch]$Delivery, [switch]$Quota
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $ProjectRoot

# The production launchers consume the repository .env. Doctor must inspect the
# same paths/configuration, while preserving variables explicitly supplied by the
# caller (CI, one-shot diagnostics, or an operator override).
function Import-DotEnv([string]$Path) {
  if (-not (Test-Path $Path)) { return $false }
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^\s*(?:#|$)') { continue }
    if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { continue }
    $key = $matches[1]
    $value = $matches[2].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($key, 'Process'))) {
      [Environment]::SetEnvironmentVariable($key, $value, 'Process')
    }
  }
  return $true
}
$DotEnvLoaded = Import-DotEnv (Join-Path $ProjectRoot '.env')

$script:Failures = 0
$script:Warnings = 0
function Check-Ok([string]$m)   { Write-Host "[OK]   $m" -ForegroundColor Green }
function Check-Warn([string]$m) { Write-Host "[WARN] $m" -ForegroundColor Yellow; $script:Warnings++ }
function Check-Fail([string]$m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:Failures++ }
function Section([string]$m)    { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Invoke-PythonCode([string]$Exe, [string]$Code) {
  # Windows' native argv parser removes quotes from a direct here-string passed
  # to python -c. Escape them once so SQL/string literals reach Python intact.
  & $Exe -c ($Code.Replace('"', '\"')) 2>$null
}

$runAll = $Full
$doVision  = $Full -or $Vision
$doMemory  = $Full -or $Memory -or $Delivery
$doDelivery = $Full -or $Delivery -or $Memory
$doXr      = $Full -or $Xr
$doQuota   = $Full -or $Quota

# Live contracts use .venv-live. Memory/CloseDay checks use the distinct core
# .venv and never silently claim that a PATH interpreter proves the night chain.
$LivePython = Join-Path $ProjectRoot ".venv-live\Scripts\python.exe"
$CorePython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = $null
if (Test-Path $LivePython) { $Python = $LivePython }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python" }

Section "Base"
if ($DotEnvLoaded) { Check-Ok ".env charge (variables explicites conservees)" }
elseif ($Full) { Check-Fail ".env absent: impossible de verifier les chemins/configs produit" }
else { Check-Warn ".env absent: les controles partiels utilisent seulement l'environnement explicite" }

# --- Python + version ---
if ($Python) {
  $ver = (& $Python -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null | Select-Object -First 1)
  if ($ver -like "3.11*") { Check-Ok "Python $ver" } else { Check-Warn "Python $ver (3.11 recommande pour la parite avec le coeur)" }
} else {
  Check-Fail "Aucun interpreteur Python trouve (.venv-live ni PATH)."
}

# --- .venv-live importable ---
if (Test-Path $LivePython) {
  $probe = & $LivePython -c "import importlib.util as u; mods=['fastapi','pydantic','pynvml']; miss=[m for m in mods if u.find_spec(m) is None]; opt='aiortc' if u.find_spec('aiortc') else ''; print('MISS='+','.join(miss)); print('AIORTC='+('yes' if opt else 'no'))" 2>$null
  $missLine = ($probe | Where-Object { $_ -like "MISS=*" }) -replace "MISS=",""
  $aiortcLine = ($probe | Where-Object { $_ -like "AIORTC=*" }) -replace "AIORTC=",""
  if ([string]::IsNullOrWhiteSpace($missLine)) { Check-Ok ".venv-live importable (fastapi, pydantic, pynvml)" }
  else { Check-Fail ".venv-live: modules manquants: $missLine" }
  if ($aiortcLine -eq "yes") { Check-Ok "aiortc present" } else { Check-Warn "aiortc absent (transport WebRTC indisponible; simulateur/contrats restent OK)" }
  $ortProviders = (& $LivePython -c "import json,onnxruntime as o; print(json.dumps(o.get_available_providers()))" 2>$null | Select-Object -Last 1)
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ortProviders)) {
    Check-Fail "ONNX Runtime non importable dans .venv-live"
  } elseif ((Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and $ortProviders -notmatch "CUDAExecutionProvider") {
    Check-Fail "GPU NVIDIA present mais VisionRT ONNX reste CPU. Providers: $ortProviders"
  } else {
    Check-Ok "ONNX Runtime providers: $ortProviders"
  }
  $detectorModel = Join-Path $ProjectRoot "models\yolox_nano.onnx"
  if ((Get-Command nvidia-smi -ErrorAction SilentlyContinue) -and (Test-Path $detectorModel)) {
    $sessionProviders = (& $LivePython -c "import json,onnxruntime as o; o.preload_dlls(directory='') if hasattr(o,'preload_dlls') else None; s=o.InferenceSession(r'$detectorModel',providers=['CUDAExecutionProvider','CPUExecutionProvider']); print(json.dumps(s.get_providers()))" 2>$null | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or $sessionProviders -notmatch "CUDAExecutionProvider") {
      Check-Fail "Le provider CUDA est liste mais une vraie session YOLOX retombe CPU: $sessionProviders"
    } else {
      Check-Ok "Session YOLOX reelle sur CUDA: $sessionProviders"
    }
  } elseif (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Check-Warn "Modele YOLOX absent: impossible de prouver une vraie session ONNX CUDA"
  }
} else {
  Check-Warn ".venv-live absent: lance scripts\INSTALL_MLOMEGA_V19_WINDOWS.ps1 (checks contrats via python systeme)."
}

# --- Real bounded CloseDay preflight in the core environment ---
if ($Full -or $Memory) {
  $preflight = Join-Path $ScriptDir 'check_close_day_preflight.py'
  if (-not (Test-Path $CorePython)) {
    Check-Fail ".venv coeur absent: CloseDay nocturne indisponible"
  } elseif (-not (Test-Path $preflight)) {
    Check-Fail "Preflight CloseDay introuvable: $preflight"
  } else {
    $preflightOutput = @(& $CorePython $preflight --json 2>$null)
    if ($LASTEXITCODE -eq 0) {
      Check-Ok "CloseDay reel: imports profonds, token HF, DB/media et ffmpeg prets"
    } else {
      $detail = ($preflightOutput | Select-Object -Last 1)
      Check-Fail "CloseDay reel non pret: $detail"
    }
  }
}

# --- Contracts round-trip (8 schemas) ---
if ($Python) {
  & $Python (Join-Path $ScriptDir "validate_contracts_v19.py") | Out-Null
  if ($LASTEXITCODE -eq 0) { Check-Ok "Contrats V19: 8 schemas round-trip" }
  else { Check-Fail "Contrats V19: le round-trip a echoue (relance scripts\validate_contracts_v19.py pour le detail)" }
} else {
  Check-Fail "Contrats V19 non verifiables sans interpreteur Python."
}

# --- GPU via nvidia-smi ---
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  $g = @(& nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>$null)
  if ($LASTEXITCODE -eq 0 -and $g) {
    foreach ($row in $g) {
      $p = $row -split ','
      if ($p.Count -ge 3) { Check-Ok "GPU $($p[0].Trim()): $($p[1].Trim()) Mo total, $($p[2].Trim()) Mo libres" }
    }
  } else { Check-Warn "nvidia-smi present mais sans etat GPU utilisable (mode CPU degrade)" }
} else {
  Check-Warn "nvidia-smi absent: mode CPU degrade (pas de VisionRT/VLM GPU)"
}

# --- Qdrant on 6333 ---
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections" -TimeoutSec 4 | Out-Null
  Check-Ok "Qdrant joignable sur 6333"
} catch { Check-Warn "Qdrant injoignable sur 6333 (memoire vectorielle indisponible; demarre docker compose Qdrant)" }

# --- Ollama on 11434 ---
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 4 | Out-Null
  Check-Ok "Ollama joignable sur 11434"
} catch { Check-Warn "Ollama injoignable sur 11434 (LLM live/deep indisponible)" }

# --- user_profile.yaml present + valid ---
$profilePath = Join-Path $ProjectRoot "configs\user_profile.yaml"
if (Test-Path $profilePath) {
  if ($Python) {
    $vp = & $Python -c "import sys,yaml; d=yaml.safe_load(open(r'$profilePath',encoding='utf-8')); req=['display','capture','llm','vision','asr','cloud_data_policy']; miss=[k for k in req if k not in (d or {})]; print('MISS='+','.join(miss))" 2>$null
    $pMiss = ($vp | Where-Object { $_ -like "MISS=*" }) -replace "MISS=",""
    if ([string]::IsNullOrWhiteSpace($pMiss)) { Check-Ok "configs\user_profile.yaml present et valide" }
    else { Check-Fail "configs\user_profile.yaml incomplet (cles manquantes: $pMiss). Relance scripts\setup_profile.ps1" }
  } else { Check-Ok "configs\user_profile.yaml present (validation YAML sautee sans Python)" }
} else {
  Check-Warn "configs\user_profile.yaml absent. Lance: scripts\setup_profile.ps1 (ou -Defaults)"
}

# --- Vision subset ---
if ($doVision) {
  Section "Vision"
  $rtx = Join-Path $ProjectRoot "configs\profiles\rtx3070.yaml"
  if (Test-Path $rtx) { Check-Ok "Profil VisionRT configs\profiles\rtx3070.yaml present" }
  else { Check-Fail "configs\profiles\rtx3070.yaml absent (cadences detecteur/queue introuvables)" }
}

# --- Delivery / Memory subset ---
if ($doMemory -or $doDelivery) {
  Section "Delivery / Memory"
  $MemoryPython = $null
  if (Test-Path $CorePython) { $MemoryPython = $CorePython }
  elseif ($Python) { $MemoryPython = $Python }
  if ($MemoryPython) {
    $dbCode = @"
import os, sqlite3, sys
db = os.environ.get('MLOMEGA_DB')
if not db or not os.path.exists(db):
    print('NODB'); sys.exit(0)
try:
    con = sqlite3.connect(db)
    row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='brainlive_intervention_delivery_queue'").fetchone()
    print('TABLE_OK' if row else 'TABLE_MISSING')
except Exception as e:
    print('ERR:'+str(e))
"@
    $dbProbe = Invoke-PythonCode $MemoryPython $dbCode
    if ($dbProbe -like "TABLE_OK*") { Check-Ok "Table brainlive_intervention_delivery_queue accessible" }
    elseif ($dbProbe -like "NODB*") { Check-Warn "MLOMEGA_DB absent/non initialise: table delivery non verifiable (normal avant premiere capture)" }
    elseif ($dbProbe -like "TABLE_MISSING*") { Check-Warn "DB presente mais table delivery absente (sera creee par ensure_delivery_schema au premier usage)" }
    else { Check-Warn "Verification table delivery: $dbProbe" }

    # E37 §3: owner (wearer) voice enrolled? The night + live speaker attribution need
    # an is_user=1 speaker with a voice embedding. WARN (not FAIL) with the command.
    $ownerCode = @"
import os, sqlite3, sys
db = os.environ.get('MLOMEGA_DB')
if not db or not os.path.exists(db):
    print('NODB'); sys.exit(0)
try:
    con = sqlite3.connect(db)
    def has(t):
        return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone())
    if not (has('speaker_profiles') and has('voice_embeddings')):
        print('NO_VOICE_TABLES'); sys.exit(0)
    row = con.execute("SELECT 1 FROM speaker_profiles sp JOIN voice_embeddings ve ON ve.person_id=sp.person_id WHERE sp.is_user=1 LIMIT 1").fetchone()
    print('OWNER_OK' if row else 'OWNER_MISSING')
except Exception as e:
    print('ERR:'+str(e))
"@
    $ownerProbe = Invoke-PythonCode $MemoryPython $ownerCode
    if ($ownerProbe -like "OWNER_OK*") { Check-Ok "Voix du porteur enrolee (is_user=1) - attribution owner active" }
    elseif ($ownerProbe -like "NODB*" -or $ownerProbe -like "NO_VOICE_TABLES*") { Check-Warn "Voix du porteur non verifiable (DB/voix pas encore initialisee). Dis « configure ma voix » a la premiere session." }
    elseif ($ownerProbe -like "OWNER_MISSING*") { Check-Warn "Voix du porteur NON enrolee. Dis « configure ma voix » (ou menu -> Ma voix) pour l'attribution owner (nuit + live)." }
    else { Check-Warn "Verification voix porteur: $ownerProbe" }
  } else { Check-Warn "Table delivery non verifiable sans Python." }
}

# --- XR subset (never a fake OK) ---
if ($doXr) {
  Section "XR"
  Check-Warn "XR non testable sans lunettes (XREAL/S25 requis; gate G1 = Lot 3). Utilise le mode -SimOnly / phone_only."
}

# --- Storage quotas subset (E36 §2) ---
if ($doQuota) {
  Section "Stockage / quotas"

  # Thresholds come from the storage_quota block (E54): user_profile.yaml first,
  # then configs\profiles\rtx3070.yaml, then these coded defaults. Decision
  # (2026-07-08): keep everything, 100 GB budget.
  $warnGb = 80.0
  $failGb = 95.0
  $bufWarnGb = 2.0
  $bufFailGb = 5.0
  $rtxProfile = Join-Path $ProjectRoot 'configs\profiles\rtx3070.yaml'
  if ($Python) {
    $q = & $Python -c @"
import yaml
def load(p):
    try:
        return yaml.safe_load(open(p, encoding='utf-8')) or {}
    except Exception:
        return {}
sq = {}
for p in (r'$profilePath', r'$rtxProfile'):
    d = load(p)
    block = (d.get('storage_quota') or {}) if isinstance(d, dict) else {}
    if block:
        sq = block
        break
def g(k, dflt):
    v = sq.get(k)
    return str(v) if v is not None else str(dflt)
# warn/fail default to warn_gb/total_gb so a profile with only total_gb still works.
print('WARN_GB=' + g('warn_gb', 80))
print('FAIL_GB=' + g('fail_gb', g('total_gb', 95)))
print('TOTAL_GB=' + g('total_gb', 100))
print('BUF_WARN_GB=' + g('day_buffer_warn_gb', 2))
print('BUF_FAIL_GB=' + g('day_buffer_fail_gb', 5))
"@ 2>$null
    foreach ($line in $q) {
      if ($line -like 'WARN_GB=*')     { $warnGb = [double]($line -replace 'WARN_GB=','') }
      elseif ($line -like 'FAIL_GB=*') { $failGb = [double]($line -replace 'FAIL_GB=','') }
      elseif ($line -like 'TOTAL_GB=*') { $totalGbBudget = [double]($line -replace 'TOTAL_GB=','') }
      elseif ($line -like 'BUF_WARN_GB=*') { $bufWarnGb = [double]($line -replace 'BUF_WARN_GB=','') }
      elseif ($line -like 'BUF_FAIL_GB=*') { $bufFailGb = [double]($line -replace 'BUF_FAIL_GB=','') }
    }
  }

  function Dir-SizeBytes([string]$path) {
    if (-not (Test-Path $path)) { return -1 }
    $sum = (Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { return 0 }
    return [long]$sum
  }
  function Fmt-Gb([long]$b) { if ($b -lt 0) { return 'absent' } return ('{0:N2} Go' -f ($b / 1GB)) }

  # Use only configured production roots. A guessed fallback can make Doctor
  # inspect an unrelated empty database/tree and produce a false green.
  $dbPath = $env:MLOMEGA_DB
  if (-not $dbPath) {
    Check-Fail "MLOMEGA_DB absent de l'environnement/.env"
    $dbBytes = 0
  } elseif (Test-Path $dbPath) {
    $dbBytes = (Get-Item -LiteralPath $dbPath).Length
    Check-Ok "DB SQLite: $(Fmt-Gb $dbBytes) ($dbPath)"
  } else {
    Check-Warn "DB SQLite absente ($dbPath) - normal avant la premiere capture."
    $dbBytes = 0
  }

  # models/ - pinned ONNX weights (should be stable, informational).
  $modelsBytes = Dir-SizeBytes (Join-Path $ProjectRoot 'models')
  if ($modelsBytes -ge 0) { Check-Ok "models/: $(Fmt-Gb $modelsBytes)" }
  else { Check-Warn "models/ absent (lance scripts\fetch_models_v19.py)" }

  # Raw audio/day buffer and media assets are deliberately distinct roots.
  $evRoot = $env:MLOMEGA_EVIDENCE
  if (-not $evRoot) {
    if ($env:MLOMEGA_RAW) { $evRoot = Join-Path $env:MLOMEGA_RAW 'evidence' }
    else { Check-Fail "MLOMEGA_EVIDENCE/MLOMEGA_RAW absent de l'environnement/.env" }
  }
  $mediaRoot = $env:MLOMEGA_MEDIA
  if (-not $mediaRoot) { Check-Fail "MLOMEGA_MEDIA absent de l'environnement/.env" }
  $kfBytes = if ($mediaRoot) { Dir-SizeBytes (Join-Path $mediaRoot 'keyframes') } else { -1 }
  $clipBytes = if ($mediaRoot) { Dir-SizeBytes (Join-Path $mediaRoot 'clips') } else { -1 }
  # E37 §1: archived live speech segments (WAV) feeding the nightly deep-audio pass.
  $audBytes = if ($evRoot) { Dir-SizeBytes (Join-Path $evRoot 'audio') } else { -1 }
  $bufBytes = if ($evRoot) { Dir-SizeBytes (Join-Path $evRoot 'day_buffer') } else { -1 }
  $kf = if ($kfBytes -lt 0) { 0 } else { $kfBytes }
  $cl = if ($clipBytes -lt 0) { 0 } else { $clipBytes }
  $au = if ($audBytes -lt 0) { 0 } else { $audBytes }
  $bf = if ($bufBytes -lt 0) { 0 } else { $bufBytes }
  Check-Ok "evidence/keyframes: $(Fmt-Gb $kfBytes) | clips: $(Fmt-Gb $clipBytes) | audio: $(Fmt-Gb $audBytes)"

  # Total tracked footprint (DB + models + evidence) against warn/fail thresholds.
  $totalBytes = [long]$dbBytes + [long]([Math]::Max(0, $modelsBytes)) + [long]$kf + [long]$cl + [long]$au + [long]$bf
  $totalGb = $totalBytes / 1GB
  if ($totalGb -ge $failGb) {
    Check-Fail ("Empreinte totale {0:N2} Go >= seuil FAIL {1} Go. Purge conseillee: close-day (tampon-jour) + rotation evidence/clips." -f $totalGb, $failGb)
  } elseif ($totalGb -ge $warnGb) {
    Check-Warn ("Empreinte totale {0:N2} Go >= seuil WARN {1} Go (FAIL a {2} Go). Surveille evidence/clips." -f $totalGb, $warnGb, $failGb)
  } else {
    Check-Ok ("Empreinte totale {0:N2} Go (WARN {1} Go / FAIL {2} Go)." -f $totalGb, $warnGb, $failGb)
  }

  # Day buffer: the close-day purge already empties it (EvidenceStore.purge_day_buffer);
  # flag it when it grows past its own thresholds so the operator runs a close-day.
  $bufGb = $bf / 1GB
  if ($bufGb -ge $bufFailGb) {
    Check-Fail ("Tampon-jour {0:N2} Go >= FAIL {1} Go. Lance un close-day (purge_day_buffer vide ce tampon)." -f $bufGb, $bufFailGb)
  } elseif ($bufGb -ge $bufWarnGb) {
    Check-Warn ("Tampon-jour {0:N2} Go >= WARN {1} Go. Un close-day le purgera (EvidenceStore.purge_day_buffer)." -f $bufGb, $bufWarnGb)
  } else {
    Check-Ok ("Tampon-jour {0:N2} Go (WARN {1} / FAIL {2} Go) - purge au close-day." -f $bufGb, $bufWarnGb, $bufFailGb)
  }
}

# --- Summary ---
Write-Host ""
if ($script:Failures -gt 0) {
  Write-Host "DOCTOR V19: $($script:Failures) FAIL, $($script:Warnings) WARN." -ForegroundColor Red
  exit 1
} else {
  Write-Host "DOCTOR V19: OK ($($script:Warnings) WARN, 0 FAIL)." -ForegroundColor Green
  exit 0
}
