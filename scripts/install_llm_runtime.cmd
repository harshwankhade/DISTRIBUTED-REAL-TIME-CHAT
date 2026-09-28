@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r requirements-llm.txt
) else (
    python -m pip install -r requirements-llm.txt
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
