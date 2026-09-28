@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m server.retire_legacy_admin
) else (
    python -m server.retire_legacy_admin
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
