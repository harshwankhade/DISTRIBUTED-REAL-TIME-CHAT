$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pidFile = Join-Path $projectRoot "logs\milestone1-pids.json"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$processIds = [System.Collections.Generic.HashSet[int]]::new()
if (Test-Path -LiteralPath $pidFile) {
    $saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    foreach ($savedId in @($saved.llm_pid, $saved.chat_pid)) {
        if ($null -ne $savedId) { [void]$processIds.Add([int]$savedId) }
    }
}

Push-Location $projectRoot
try {
    $configuredPorts = & $python -c "from common.config import load_settings; s=load_settings(); print(f'{s.chat_endpoint.port},{s.llm_endpoint.port}')"
    if ($LASTEXITCODE -ne 0) { throw "Could not read configured service ports." }
} finally {
    Pop-Location
}

$ports = $configuredPorts.Trim().Split(",") | ForEach-Object { [int]$_ }
foreach ($line in (netstat.exe -ano -p tcp)) {
    $parts = $line.Trim() -split '\s+'
    if ($parts.Count -ge 5 -and $parts[0] -eq "TCP" -and $parts[3] -eq "LISTENING") {
        foreach ($port in $ports) {
            if ($parts[1].EndsWith(":$port")) {
                [void]$processIds.Add([int]$parts[4])
            }
        }
    }
}

$stopped = 0
foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        if ($process.ProcessName -like "python*") {
            try {
                Stop-Process -Id $processId -ErrorAction Stop
                $stopped += 1
                Write-Host "Stopped Python service process $processId."
            } catch {
                if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                    throw
                }
                Write-Host "Process $processId had already exited."
            }
        } else {
            Write-Warning "Port owner $processId is not Python; it was not stopped."
        }
    }
}
if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile
}
if ($stopped -eq 0) {
    Write-Host "No running Milestone 1 service processes were found."
}
