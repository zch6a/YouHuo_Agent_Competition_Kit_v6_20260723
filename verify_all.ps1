$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "reports") | Out-Null
# SQLite WAL mode leaves -wal/-shm sidecars holding committed rows. Deleting only
# the .db lets a previous run replay into the "clean" database, and deleting the
# audit key alongside it makes the surviving audit rows fail chain verification.
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Root "data/youhuo.db"), (Join-Path $Root "data/youhuo.db-wal"), (Join-Path $Root "data/youhuo.db-shm"), (Join-Path $Root "data/youhuo.db.audit.key")
$Log = Join-Path $Root "reports/verify_all_v6.txt"
& {
  Write-Host "START compile_v6"; python -m compileall -q backend; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS compile_v6"
  Write-Host "START openapi_v6"; python backend/scripts/generate_openapi_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS openapi_v6"
  python -m coverage erase
  Write-Host "START pytest_v6"; python -m coverage run -m pytest -q backend/tests | Tee-Object reports/pytest_v6.txt; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS pytest_v6"
  Write-Host "START coverage_v6"; python -m coverage report --include="backend/youhuo/*" --fail-under=80 | Tee-Object reports/coverage_v6.txt; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS coverage_v6"
  python backend/scripts/run_elderbench.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_elderbench_v4.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_elderbench_v5.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_voicebench_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/run_mass_audit_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/scan_secrets.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  python backend/scripts/validate_contracts_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "START feature_audit_v6"; python backend/scripts/run_feature_audit.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS feature_audit_v6"
  Write-Host "START browser_javascript_v6"; python backend/scripts/check_browser_js.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "START arkts_v6"; python backend/scripts/check_arkts.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS arkts_v6"
  Write-Host "START accessibility_v6"; python backend/scripts/check_contrast.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS accessibility_v6"
  Remove-Item -Force -ErrorAction SilentlyContinue data/youhuo.db, data/youhuo.db-wal, data/youhuo.db-shm, data/youhuo.db.audit.key
  python backend/scripts/check_artifacts_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED"
} *>&1 | Tee-Object $Log
if ($LASTEXITCODE) { exit $LASTEXITCODE }
