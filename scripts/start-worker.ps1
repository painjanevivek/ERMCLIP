$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
& "$projectRoot\.venv\Scripts\python.exe" -m ermclip.local_runtime
if ($LASTEXITCODE -ne 0) { throw 'The configured local model did not start.' }
$healthPath = Join-Path $projectRoot 'state\health.json'
if (Test-Path -LiteralPath $healthPath) {
    $workerHealth = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
    $ageSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $workerHealth.time
    if ($workerHealth.status -eq 'running' -and $ageSeconds -lt 15) { Write-Output 'ERMCLIP is already running.'; exit 0 }
}
$process = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSScriptRoot\ermclip.ps1`"",'worker') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
Write-Output "Worker launcher PID: $($process.Id). Run scripts/ermclip.ps1 health to check the worker."
