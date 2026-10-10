$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:UV_CACHE_DIR = Join-Path $projectRoot 'cache\uv'
& uv pip install --python $pythonPath 'torch==2.8.0+cpu' --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU Torch installation failed.' }
& uv pip install --python $pythonPath 'python_speech_features==0.6' 'scipy>=1.11,<2'
if ($LASTEXITCODE -ne 0) { throw 'Audio feature installation failed.' }
& $pythonPath "$PSScriptRoot\install-speaker-models.py"
if ($LASTEXITCODE -ne 0) { throw 'Speaker model asset verification failed.' }
Write-Output 'Local CPU speaker tracking is ready. No paid API is used.'
