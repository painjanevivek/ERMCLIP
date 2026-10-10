param([string]$HermesHome = "$env:LOCALAPPDATA\hermes", [switch]$Remove)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $HermesHome 'config.yaml'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Hermes config.yaml was not found.' }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
# Keep source inside the project. Hermes scans the registered external skill directory.
& $pythonPath "$PSScriptRoot\register_hermes.py" $projectRoot $HermesHome $(if ($Remove) {'remove'} else {'install'})
if ($LASTEXITCODE -ne 0) { throw 'Hermes skill registration failed.' }
