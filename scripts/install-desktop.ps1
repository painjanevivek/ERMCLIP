param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonWindowless = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$launcherPath = Join-Path $PSScriptRoot 'launch-ermclip.py'
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'ERMCLIP.lnk'
$taskName = 'ERMCLIP Local Pages'
$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    if ($existing.TargetPath -ne $pythonWindowless -or $existing.Arguments -ne ('"' + $launcherPath + '"')) {
        throw 'A different ERMCLIP shortcut exists. It was not changed.'
    }
}
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    Write-Output 'Removed the desktop shortcut and page sign-in task. The editing worker task remains installed.'
    exit 0
}
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'Run scripts/setup.ps1 first. The windowless Python executable is missing.' }
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -c 'import webview'
if ($LASTEXITCODE -ne 0) { throw 'Install the desktop package with: uv pip install --python .venv/Scripts/python.exe -e ".[desktop]"' }
$taskAction = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('"' + $launcherPath + '" --background') -WorkingDirectory $projectRoot
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$taskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Description 'Start only the small ERMCLIP loopback UI service at sign-in. Models stay unloaded until an editing job starts.' -Force | Out-Null
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonWindowless
$shortcut.Arguments = '"' + $launcherPath + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
$shortcut.Description = 'Open the native ERMCLIP window. Import a video and create shorts in five steps.'
$shortcut.Save()
Start-ScheduledTask -TaskName $taskName
Write-Output "Installed $shortcutPath. The shortcut opens a native desktop window. Only the UI service starts at sign-in."
exit 0
