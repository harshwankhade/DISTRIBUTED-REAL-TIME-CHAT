$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pidFile = Join-Path $projectRoot "logs\milestone1-pids.json"
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No Milestone 1 PID file was found."
    exit 0
}

$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($processId in @($saved.llm_pid, $saved.chat_pid)) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        Stop-Process -Id $processId
        Write-Host "Stopped process $processId."
    }
}
Remove-Item -LiteralPath $pidFile
