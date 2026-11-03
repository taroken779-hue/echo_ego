@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -Model qwen3
set "setup_exit=%errorlevel%"
pause
exit /b %setup_exit%
