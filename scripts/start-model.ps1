$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
& "$projectRoot\.venv\Scripts\python.exe" -m ermclip.local_runtime
exit $LASTEXITCODE
