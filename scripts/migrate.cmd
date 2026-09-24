@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m server.migrate
) else (
    python -m server.migrate
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%

