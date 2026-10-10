$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'ERMCLIP Local Worker' -ErrorAction SilentlyContinue
if ($task) {
    # A submission can arrive while the idle worker is releasing its model.
    # Wait for that task to leave Running before requesting its next run.
    $healthPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'state\health.json'
    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    while ($task.State -eq 'Running' -and [DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $healthPath) {
            $health = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
            $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $health.time
            if ($health.status -eq 'running' -and $age -lt 15) {
                # Give an imminent idle shutdown a chance to finish first.
                Start-Sleep -Seconds 1
                $task = Get-ScheduledTask -TaskName $task.TaskName
                $health = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
                if ($task.State -eq 'Running' -and $health.status -eq 'running') { exit 0 }
                continue
            }
        }
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $task.TaskName
    }
    if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName $task.TaskName }
} else {
    # A fresh clone without a registered task still uses the same idle release.
    $root = Split-Path -Parent $PSScriptRoot
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',('"' + "$PSScriptRoot\run-service.ps1" + '"')) -WorkingDirectory $root -WindowStyle Hidden
}
