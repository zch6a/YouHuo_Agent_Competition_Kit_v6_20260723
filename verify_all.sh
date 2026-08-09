#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/backend"
mkdir -p reports
rm -f data/youhuo.db data/youhuo.db-wal data/youhuo.db-shm data/youhuo.db.audit.key
{
  echo "START compile_v6"; python -m compileall -q backend; echo "PASS compile_v6"
  echo "START openapi_v6"; python backend/scripts/generate_openapi_v6.py; echo "PASS openapi_v6"
  python -m coverage erase
  echo "START pytest_v6"; python -m coverage run -m pytest -q backend/tests | tee reports/pytest_v6.txt; echo "PASS pytest_v6"
  echo "START coverage_v6"; python -m coverage report --include='backend/youhuo/*' --fail-under=80 | tee reports/coverage_v6.txt; echo "PASS coverage_v6"
  echo "START elderbench_v3"; python backend/scripts/run_elderbench.py; echo "PASS elderbench_v3"
  echo "START elderbench_v4"; python backend/scripts/run_elderbench_v4.py; echo "PASS elderbench_v4"
  echo "START elderbench_v5"; python backend/scripts/run_elderbench_v5.py; echo "PASS elderbench_v5"
  echo "START voicebench_v6"; python backend/scripts/run_voicebench_v6.py; echo "PASS voicebench_v6"
  echo "START mass_audit_v6"; python backend/scripts/run_mass_audit_v6.py; echo "PASS mass_audit_v6"
  echo "START secret_scan_v6"; python backend/scripts/scan_secrets.py; echo "PASS secret_scan_v6"
  echo "START contracts_v6"; python backend/scripts/validate_contracts_v6.py; echo "PASS contracts_v6"
  echo "START feature_audit_v6"; python backend/scripts/run_feature_audit.py; echo "PASS feature_audit_v6"
  echo "START browser_javascript_v6"; python backend/scripts/check_browser_js.py
  echo "START arkts_v6"; python backend/scripts/check_arkts.py
  echo "START accessibility_v6"; python backend/scripts/check_contrast.py
  rm -f data/youhuo.db data/youhuo.db-wal data/youhuo.db-shm data/youhuo.db.audit.key
  echo "START artifact_check_v6"; python backend/scripts/check_artifacts_v6.py; echo "PASS artifact_check_v6"
  echo "ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED"
} 2>&1 | tee reports/verify_all_v6.txt
