@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m client %*
) else (
    python -m client %*
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
