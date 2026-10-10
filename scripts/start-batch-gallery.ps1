$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$galleryRoot = Join-Path $projectRoot 'output\raj-shamani-batch'
if (-not (Test-Path -LiteralPath (Join-Path $galleryRoot 'index.html'))) { throw 'Finish the batch checks first.' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 8092 -ErrorAction SilentlyContinue
if ($listener) { Write-Output 'Local batch gallery already listens on port 8092.'; exit }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$galleryProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','http.server','8092','--bind','127.0.0.1','--directory',('"'+$galleryRoot+'"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'logs\batch-gallery.log') -RedirectStandardError (Join-Path $projectRoot 'logs\batch-gallery-error.log')
$galleryProcess.Id | Set-Content -LiteralPath (Join-Path $projectRoot 'state\batch-gallery.pid')
Write-Output 'http://127.0.0.1:8092/'
