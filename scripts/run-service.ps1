$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
& "$projectRoot\.venv\Scripts\python.exe" -m ermclip.local_runtime
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
# Stay attached so Task Scheduler can detect and restart a worker failure.
& "$projectRoot\.venv\Scripts\python.exe" -m ermclip worker
exit $LASTEXITCODE
