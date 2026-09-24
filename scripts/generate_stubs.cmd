@echo off
setlocal
pushd "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe scripts\generate_stubs.py
) else (
    python scripts\generate_stubs.py
)
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
