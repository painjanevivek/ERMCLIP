param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$projectRoot = (Split-Path -Parent $PSScriptRoot)
$taskName = 'ERMCLIP Local Worker'
if ($Remove) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; exit }
$taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\run-service.ps1`"" -WorkingDirectory $projectRoot
$taskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Settings $taskSettings -Description 'ERMCLIP editing engine. Started on demand by the app; releases the model after five minutes with no pending jobs.' -Force | Out-Null
Write-Output "Installed $taskName for on-demand editing. The model does not start at sign-in."
