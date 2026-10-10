param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[1-9][0-9]*$')][string]$UserId,
    [string]$BotUsername = 'hermes_2eq47xdksbp5xcxn_bot'
)
$ErrorActionPreference = 'Stop'
# Enter the token and allowed user ID in Hermes first. Never pass the token in argv.
& "$PSScriptRoot\ermclip.ps1" connect-telegram --user-id $UserId --bot-username $BotUsername
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot\stop-worker.ps1"
$deadline = [DateTime]::UtcNow.AddSeconds(30)
while ((Get-ScheduledTask -TaskName 'ERMCLIP Local Worker').State -eq 'Running') {
    if ([DateTime]::UtcNow -gt $deadline) { throw 'Worker stop is still pending. Start the existing task after it stops.' }
    Start-Sleep -Seconds 1
}
Start-ScheduledTask -TaskName 'ERMCLIP Local Worker'
Write-Output 'Notifications are enabled. Use Hermes Messaging to start its existing gateway.'
