$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"
# 这个脚本里全是裸 `python`。机器上装了 Miniconda，它在 PATH 里排在前面且没有本项目
# 的依赖，于是整套验证会以 ModuleNotFoundError 收场，而失败原因看起来像代码坏了。
# 项目自带的 .venv 在就用它，别让调用方每次手动前置 PATH。
$Venv = Join-Path $Root ".venv/Scripts"
if (Test-Path $Venv) { $env:Path = "$Venv;$env:Path" }
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
  # 上一行只解析、不执行（`node --check`），所以它对运行时错误是全盲的：care.js 和
  # trust.js 的 `const state = { …, elderId: state.elderId }` 语法完全合法，运行时
  # 却在第一条语句就抛 ReferenceError，两个页面上每个按钮都是死的，而它一直是绿的。
  # 下面这一行把页面真的加载起来再问浏览器有没有抛东西。两个都要留着。
  Write-Host "START page_runtime_v6"; python backend/scripts/check_page_runtime.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS page_runtime_v6"
  Write-Host "START arkts_v6"; python backend/scripts/check_arkts.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS arkts_v6"
  Write-Host "START accessibility_v6"; python backend/scripts/check_contrast.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS accessibility_v6"
  # Focus Mode 的几何是确定性的：三组构造好的卡直接喂给 renderGlassBox，
  # 不依赖"这次有没有真的缴过费"。上面那些闸门在这个缺陷上全是绿的。
  Write-Host "START focus_geometry_v6"; python backend/scripts/check_focus_geometry.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS focus_geometry_v6"
  # 载入期不许跳。这一条只在**桌面**视口显形（手机上位移落在首屏折线以下、
  # 不计入 CLS），而这个项目其余的浏览器闸门都以手机为主。
  Write-Host "START layout_stability_v6"; python backend/scripts/check_layout_stability.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS layout_stability_v6"
  # 每一页在**每一个宽度**下走不走得出去。`test_every_screen_has_some_way_out`
  # 查的是 markup 里有没有 `class="tabbar"`，从不问那个出口在哪个宽度下可见——
  # 同一份 markup 在两个宽度下一个能走一个走不了，只有在浏览器里按宽度各量一次
  # 才测得到。变异证明见 frontend_redesign/final-polish/MUTATION_PROOF_EXITS.md。
  Write-Host "START exits_v6"; python backend/scripts/check_exits.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }; Write-Host "PASS exits_v6"
  Remove-Item -Force -ErrorAction SilentlyContinue data/youhuo.db, data/youhuo.db-wal, data/youhuo.db-shm, data/youhuo.db.audit.key
  python backend/scripts/check_artifacts_v6.py; if ($LASTEXITCODE) { exit $LASTEXITCODE }
  Write-Host "ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED"
} *>&1 | Tee-Object $Log
if ($LASTEXITCODE) { exit $LASTEXITCODE }
