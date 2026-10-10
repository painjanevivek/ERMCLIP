param([string]$PythonPath, [switch]$DownloadModels)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $PythonPath) {
    $candidates = @(
        "$env:APPDATA\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe",
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    )
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $PythonPath) { throw 'Supply -PythonPath with a Python 3.11 or 3.12 executable.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $PythonPath -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$env:UV_CACHE_DIR = Join-Path $projectRoot 'cache\uv'
uv pip install --python .venv\Scripts\python.exe -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& "$PSScriptRoot\ermclip.ps1" init
if ($DownloadModels) {
    & .venv\Scripts\python.exe -c 'import json,pathlib; p=pathlib.Path("config/local.json"); c=json.loads(p.read_text()); c["allow_model_download"]=True; p.write_text(json.dumps(c,indent=2),encoding="utf-8")'
}
& "$PSScriptRoot\ermclip.ps1" schemas
& "$PSScriptRoot\ermclip.ps1" doctor --save
