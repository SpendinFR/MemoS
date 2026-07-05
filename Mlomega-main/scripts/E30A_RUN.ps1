<#
E30A_RUN.ps1 — autonomous overnight E30-A run (seed 30 days + real close-day).

The user launches this and lets it run for the night:
  powershell -ExecutionPolicy Bypass -File scripts\E30A_RUN.ps1

Phases (each guarded; a failure is logged and the run continues):
  (a) preflight  : load .env, start Qdrant (START_QDRANT.ps1) + Ollama serve if
                   down, quick DOCTOR (non-fatal).
  (b)+(c) seed + REAL close-day : scripts\e30a_runner.py in the CORE .venv
                   (torch/whisperx) with use_llm=True for 3 representative days,
                   stage timing captured in a JSON summary.
  (d) doctor -Memory : final memory/quotas snapshot.
  (e) report      : E30A_REPORT.md (durations per stage/day + counters) and the
                   full console transcript in E30A_RUN.log.

PowerShell 5.1 compatible: no '&&', no ternary operators.
#>
[CmdletBinding()]
param(
  [int]$Days = 30,
  [switch]$SkipSeed
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $ProjectRoot

$LogPath = Join-Path $ProjectRoot "E30A_RUN.log"
$ReportPath = Join-Path $ProjectRoot "E30A_REPORT.md"
$SummaryJson = Join-Path $ProjectRoot "E30A_summary.json"
$CorePython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LivePython = Join-Path $ProjectRoot ".venv-live\Scripts\python.exe"
$OllamaExe = "C:\Users\wabad\AppData\Local\Programs\Ollama\ollama.exe"

# Fresh transcript each run.
"E30A_RUN transcript - $(Get-Date -Format o)" | Set-Content -Encoding UTF8 $LogPath

function Log([string]$m) {
  $line = "[{0}] {1}" -f (Get-Date -Format o), $m
  Write-Host $line
  Add-Content -Path $LogPath -Value $line
}
function Run-Logged([scriptblock]$block, [string]$what) {
  Log "==> $what"
  try {
    $out = & $block 2>&1 | Out-String
    if ($out) { Add-Content -Path $LogPath -Value $out; Write-Host $out }
    Log "<== $what : done"
    return $true
  } catch {
    Log "<== $what : ERROR $($_.Exception.Message)"
    return $false
  }
}

Log "E30-A run start (Days=$Days, SkipSeed=$SkipSeed). Foyer=$ProjectRoot"

# --- Load .env into the process (MLOMEGA_* + HF_TOKEN) ---
$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
      $kv = $line -split "=", 2
      $name = $kv[0].Trim()
      $val = $kv[1].Trim()
      if ($name) { Set-Item -Path "env:$name" -Value $val }
    }
  }
  Log ".env charge (MLOMEGA_DB=$($env:MLOMEGA_DB))"
} else {
  Log "ATTENTION: .env absent - le runner tournera avec les defauts (person=me)."
}
if (-not $env:MLOMEGA_PERSON_ID) { $env:MLOMEGA_PERSON_ID = "me" }

# --- (a) Preflight: Qdrant ---
$qdrantUp = $false
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:6333/healthz" -TimeoutSec 3 -UseBasicParsing
  $qdrantUp = ($r.StatusCode -eq 200)
} catch { $qdrantUp = $false }
if (-not $qdrantUp) {
  Run-Logged { & (Join-Path $ScriptDir "START_QDRANT.ps1") } "Preflight: demarrage Qdrant" | Out-Null
} else {
  Log "Preflight: Qdrant deja actif sur 6333."
}

# --- (a) Preflight: Ollama ---
$ollamaUp = $false
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 4 | Out-Null
  $ollamaUp = $true
} catch { $ollamaUp = $false }
if (-not $ollamaUp) {
  if (Test-Path $OllamaExe) {
    Log "Preflight: Ollama down -> lancement 'ollama serve' en arriere-plan."
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $ProjectRoot "ollama_serve.log") `
      -RedirectStandardError (Join-Path $ProjectRoot "ollama_serve.err.log") | Out-Null
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
      try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null; $ollamaUp = $true; break } catch {}
      Start-Sleep -Milliseconds 800
    }
    Log "Preflight: Ollama up=$ollamaUp apres serve."
  } else {
    Log "ATTENTION: ollama.exe introuvable ($OllamaExe). Le close-day use_llm echouera."
  }
} else {
  Log "Preflight: Ollama deja actif sur 11434."
}

# --- (a) Preflight: quick doctor (non-fatal) ---
Run-Logged { & (Join-Path $ScriptDir "DOCTOR_MLOMEGA_V19.ps1") } "Preflight: doctor rapide" | Out-Null

# --- (b)+(c) seed + REAL close-day, core venv ---
if (-not (Test-Path $CorePython)) {
  Log "FATAL: .venv cor absent ($CorePython). Impossible de lancer le close-day reel."
} else {
  $env:PYTHONPATH = "$ProjectRoot\src;$ProjectRoot;$env:PYTHONPATH"
  $runnerArgs = @((Join-Path $ScriptDir "e30a_runner.py"), "--person", $env:MLOMEGA_PERSON_ID, "--days", "$Days", "--out", $SummaryJson)
  if ($SkipSeed) { $runnerArgs += "--skip-seed" }
  Run-Logged { & $CorePython @runnerArgs } "Seed 30j + close-day REEL (use_llm=True, core .venv)" | Out-Null
}

# --- (d) doctor -Memory final ---
Run-Logged { & (Join-Path $ScriptDir "DOCTOR_MLOMEGA_V19.ps1") -Memory -Quota } "Doctor -Memory final" | Out-Null

# --- (e) E30A_REPORT.md from the JSON summary ---
Log "Generation du rapport E30A_REPORT.md"
$reportBuilder = @'
import json, sys
from pathlib import Path
summ = Path(sys.argv[1]); out = Path(sys.argv[2])
lines = ["# E30-A report", ""]
if not summ.exists():
    out.write_text("# E30-A report\n\nAucun resume JSON produit (le runner a echoue avant l ecriture). Voir E30A_RUN.log.\n", encoding="utf-8")
    print("no summary json"); sys.exit(0)
d = json.loads(summ.read_text(encoding="utf-8"))
lines += [f"- person_id: `{d.get('person_id')}`  |  days: {d.get('days')}  |  db: `{d.get('db_path')}`",
          f"- started: {d.get('started_at')}  ->  finished: {d.get('finished_at')}",
          f"- python: {d.get('python')} ({d.get('executable')})", ""]
seed = d.get("seed", {})
lines += ["## Seed (vie synthetique 30j)"]
if seed.get("skipped"): lines.append("- skipped (--skip-seed)")
elif seed.get("ok"):
    lines.append(f"- OK en {seed.get('seconds')}s")
    for k, v in (seed.get("result") or {}).items(): lines.append(f"  - {k}: {v}")
else:
    lines.append(f"- ECHEC ({seed.get('seconds')}s): {seed.get('error')}")
lines.append("")
lines += ["## Close-day REEL (use_llm=True)"]
for cd in d.get("close_days", []):
    lines.append(f"### Jour {cd.get('package_date')}")
    if cd.get("ok"):
        lines.append(f"- status: **{cd.get('status')}** en **{cd.get('seconds')}s** (run_id={cd.get('run_id')}, cleanup_eligible={cd.get('cleanup_eligible')})")
        stages = cd.get("stages") or {}
        if stages:
            lines.append("- stages:")
            for sn, sv in stages.items(): lines.append(f"  - `{sn}`: {sv}")
    else:
        lines.append(f"- ECHEC en {cd.get('seconds')}s: {cd.get('error')}")
    lines.append("")
def counter_table(title, c):
    out = [f"## {title}"]
    if not c: out.append("- (aucun)"); return out
    for k, v in c.items(): out.append(f"- {k}: {v}")
    out.append("")
    return out
lines += counter_table("Compteurs AVANT", d.get("counters_before", {}))
lines += counter_table("Compteurs APRES", d.get("counters_after", {}))
# Error roll-up
errs = []
if not seed.get("ok") and not seed.get("skipped"): errs.append(f"seed: {seed.get('error')}")
for cd in d.get("close_days", []):
    if not cd.get("ok"): errs.append(f"close-day {cd.get('package_date')}: {cd.get('error')}")
lines += ["## Erreurs"]
lines += [f"- {e}" for e in errs] if errs else ["- aucune"]
lines += ["", "Log console complet: E30A_RUN.log"]
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("report written", out)
'@
$builderPath = Join-Path $ProjectRoot "E30A_build_report.py"
$reportBuilder | Set-Content -Encoding UTF8 $builderPath
Run-Logged { & $CorePython $builderPath $SummaryJson $ReportPath } "Ecriture E30A_REPORT.md" | Out-Null
Remove-Item -Force $builderPath -ErrorAction SilentlyContinue

Log "E30-A run TERMINE. Rapport: $ReportPath  |  Log: $LogPath"
Write-Host "`nE30-A termine. Voir $ReportPath et $LogPath" -ForegroundColor Green
exit 0
