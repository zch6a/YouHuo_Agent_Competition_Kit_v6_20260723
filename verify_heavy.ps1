$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"
# 同 verify_all.ps1：这里全是裸 `python`，机器上的 Miniconda 排在 PATH 前面且没有本
# 项目的依赖，整套重验证会以 ModuleNotFoundError 收场，看起来却像代码坏了。
$Venv = Join-Path $Root ".venv/Scripts"
if (Test-Path $Venv) { $env:Path = "$Venv;$env:Path" }
New-Item -ItemType Directory -Force -Path (Join-Path $Root "reports") | Out-Null
$Log = Join-Path $Root "reports/verify_heavy_v6.txt"
& {
  python backend/scripts/run_mass_audit_v5.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_chaos_v5.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_load_v6.py --requests 5000 --concurrency 100 --output reports/load_v6_5000.json; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_http_smoke_v6.py --output reports/http_smoke_v6.json; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Remove-Item -Force -ErrorAction SilentlyContinue data/youhuo.db, data/youhuo.db-wal, data/youhuo.db-shm, data/youhuo.db.audit.key
  python backend/scripts/check_artifacts_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "ALL V6 HEAVY VERIFICATION STAGES PASSED"
} *>&1 | Tee-Object $Log
if ($LASTEXITCODE) { exit $LASTEXITCODE }
