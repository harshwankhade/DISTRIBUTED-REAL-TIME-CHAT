@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m llm_server %*
) else (
    python -m llm_server %*
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
