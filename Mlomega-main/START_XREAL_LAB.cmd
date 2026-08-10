@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\PREFLIGHT_XREAL_LAB.ps1" %*
if errorlevel 1 pause
exit /b %errorlevel%
