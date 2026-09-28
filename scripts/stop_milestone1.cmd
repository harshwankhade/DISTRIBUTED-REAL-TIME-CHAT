@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_milestone1.ps1"
exit /b %ERRORLEVEL%
