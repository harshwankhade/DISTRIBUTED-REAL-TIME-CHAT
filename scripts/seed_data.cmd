@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m server.seed %*
) else (
    python -m server.seed %*
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
