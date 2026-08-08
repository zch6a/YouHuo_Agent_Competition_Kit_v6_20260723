#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/backend"
mkdir -p reports
{
  echo "START mass_audit_v5_regression"; python backend/scripts/run_mass_audit_v5.py; echo "PASS mass_audit_v5_regression"
  echo "START saga_chaos_regression"; python backend/scripts/run_chaos_v5.py; echo "PASS saga_chaos_regression"
  echo "START real_uvicorn_load_v6"; python backend/scripts/run_load_v6.py --requests 5000 --concurrency 100 --output reports/load_v6_5000.json; echo "PASS real_uvicorn_load_v6"
  echo "START real_http_smoke_v6"; python backend/scripts/run_http_smoke_v6.py --output reports/http_smoke_v6.json; echo "PASS real_http_smoke_v6"
  rm -f data/youhuo.db data/youhuo.db-wal data/youhuo.db-shm data/youhuo.db.audit.key
  echo "START artifact_check_v6"; python backend/scripts/check_artifacts_v6.py; echo "PASS artifact_check_v6"
  echo "ALL V6 HEAVY VERIFICATION STAGES PASSED"
} 2>&1 | tee reports/verify_heavy_v6.txt
