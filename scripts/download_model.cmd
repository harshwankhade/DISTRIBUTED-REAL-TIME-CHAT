@echo off
setlocal
pushd "%~dp0.."
if not exist "models" mkdir "models"
curl.exe -L --fail --continue-at - --output "models\qwen2.5-3b-instruct-q4_k_m.gguf" "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true"
set "task_exit_code=%ERRORLEVEL%"
popd
exit /b %task_exit_code%
