@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
set "setup_exit=%errorlevel%"
if not "%setup_exit%"=="0" pause
exit /b %setup_exit%
