@echo off
setlocal
pushd "%~dp0.."
echo User accounts are now created with Register in the Tkinter client.
echo The legacy administrator seed command is retired.
set "task_exit_code=0"
popd
exit /b %task_exit_code%
