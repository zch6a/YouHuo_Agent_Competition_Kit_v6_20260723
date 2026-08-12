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
  # 上一行只解析、不执行（`node --check`），对运行时错误是全盲的：care.js/trust.js 的
  # `const state = { …, elderId: state.elderId }` 语法合法，运行时第一条语句就抛
  # ReferenceError，两页所有按钮全死，而它一直是绿的。下面这行把页面真的加载起来。
  echo "START page_runtime_v6"; python backend/scripts/check_page_runtime.py; echo "PASS page_runtime_v6"
  echo "START arkts_v6"; python backend/scripts/check_arkts.py
  echo "START accessibility_v6"; python backend/scripts/check_contrast.py
  echo "START focus_geometry_v6"; python backend/scripts/check_focus_geometry.py; echo "PASS focus_geometry_v6"
  echo "START layout_stability_v6"; python backend/scripts/check_layout_stability.py; echo "PASS layout_stability_v6"
  rm -f data/youhuo.db data/youhuo.db-wal data/youhuo.db-shm data/youhuo.db.audit.key
  echo "START artifact_check_v6"; python backend/scripts/check_artifacts_v6.py; echo "PASS artifact_check_v6"
  echo "ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED"
} 2>&1 | tee reports/verify_all_v6.txt
