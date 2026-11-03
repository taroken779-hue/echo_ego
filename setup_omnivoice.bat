@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -Model omnivoice
set "setup_exit=%errorlevel%"
pause
exit /b %setup_exit%
