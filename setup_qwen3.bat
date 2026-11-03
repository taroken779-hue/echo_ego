@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_qwen3.ps1"
set "setup_exit=%errorlevel%"
pause
exit /b %setup_exit%
