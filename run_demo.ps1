$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"
if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" | Out-Null }
python -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8000 --app-dir backend
