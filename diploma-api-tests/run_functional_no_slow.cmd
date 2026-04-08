@echo off
setlocal

set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_functional_no_slow.ps1" -Quiet
exit /b %ERRORLEVEL%
