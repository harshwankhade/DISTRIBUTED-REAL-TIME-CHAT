$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$logs = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

Push-Location $projectRoot
try {
    & $python -m server.migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }

    & $python -m server.retire_legacy_admin
    if ($LASTEXITCODE -ne 0) { throw "Legacy administrator cleanup failed." }

    Write-Host "Users can register in the Tkinter client. No administrator seed is required."

    $llm = Start-Process -FilePath $python -ArgumentList "-m", "llm_server" `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "llm.stdout.log") `
        -RedirectStandardError (Join-Path $logs "llm.stderr.log")
    $chat = Start-Process -FilePath $python -ArgumentList "-m", "server" `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "chat.stdout.log") `
        -RedirectStandardError (Join-Path $logs "chat.stderr.log")

    @{ llm_pid = $llm.Id; chat_pid = $chat.Id } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logs "milestone1-pids.json")

    Start-Sleep -Seconds 2
    if ($llm.HasExited) { throw "LLM server exited. See logs\llm.stderr.log." }
    if ($chat.HasExited) { throw "Chat server exited. See logs\chat.stderr.log." }

    Write-Host "Milestone 1 services started. Logs are under logs\."
    Write-Host "Opening the Tkinter client. Run scripts\start_client.cmd --gui for more users."
    Start-Process -FilePath $python -ArgumentList "-m", "client", "--gui" `
        -WorkingDirectory $projectRoot
} finally {
    Pop-Location
}
