@echo off
setlocal
pushd "%~dp0.."
python -m server %*
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%

