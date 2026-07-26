@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\START_XREAL_S24.ps1" %*
set "MLOMEGA_EXIT=%ERRORLEVEL%"
if not "%MLOMEGA_EXIT%"=="0" (
  echo.
  echo MLOmega s'est arrete avec le code %MLOMEGA_EXIT%.
  pause
)
exit /b %MLOMEGA_EXIT%
