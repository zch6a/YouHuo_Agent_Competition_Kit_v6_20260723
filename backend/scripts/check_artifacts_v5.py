from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    checks: dict[str, bool] = {}
    required = [
        "README.md", "PACKAGE_INDEX.md", "THIRD_PARTY_NOTICES.md",
        "competition_materials/03_800字作品介绍.md",
        "docs/24_V5_RESEARCH_AND_ARCHITECTURE.md",
        "docs/25_V5_SECURITY_ASSURANCE_CASE.md",
        "docs/26_V5_DEMO_SCRIPT.md", "docs/27_V5_JUDGE_QA.md",
        "evaluation/elderbench_v5.jsonl",
        "backend/youhuo/v5_models.py", "backend/youhuo/v5_services.py",
        "backend/youhuo/v5_store.py", "backend/youhuo/v5_api.py",
        "backend/static/trust.html", "backend/static/trust.js",
        "harmonyos/entry/src/main/ets/pages/AgentTrustLabPage.ets",
        "xiaoyi/plugin_openapi_v5.generated.json",
        "xiaoyi/skills/youhuo-voice-consensus/SKILL.md",
        "xiaoyi/skills/youhuo-purpose-bound-policy/SKILL.md",
        "xiaoyi/skills/youhuo-durable-saga/SKILL.md",
        "xiaoyi/skills/youhuo-break-glass/SKILL.md",
        "reports/pytest_v5.txt", "reports/coverage_v5.txt",
        "reports/elderbench_v5.json", "reports/mass_audit_v5_1000000.json",
        "reports/load_v5_5000.json", "reports/chaos_v5_400.json",
        "reports/http_smoke_v5.json", "reports/TEST_REPORT.md",
    ]
    checks["required_files"] = all((ROOT / item).is_file() for item in required)

    yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))
    checks["openapi_yaml"] = True
    json_files = [
        "xiaoyi/plugin_openapi_v5.generated.json", "xiaoyi/workflows/youhuo_workflow.json",
        "xiaoyi/a2a/agent_card.json", "mcp/tool_manifest.json",
        "harmonyos/entry/src/main/resources/base/profile/main_pages.json",
        "reports/elderbench_v5.json", "reports/mass_audit_v5_1000000.json",
        "reports/load_v5_5000.json", "reports/chaos_v5_400.json", "reports/http_smoke_v5.json",
    ]
    parsed = {rel: json.loads((ROOT / rel).read_text(encoding="utf-8")) for rel in json_files}
    checks["json_contracts"] = True

    openapi = parsed["xiaoyi/plugin_openapi_v5.generated.json"]
    required_paths = {
        "/v5/voice/resolve", "/v5/actions/authorize", "/v5/sagas",
        "/v5/sync/operations", "/v5/break-glass", "/v5/proofs/verify",
        "/v5/privacy/export", "/v5/privacy/erase", "/v5/metrics", "/v5/capability-truth",
    }
    checks["openapi_v5_paths"] = required_paths.issubset(openapi["paths"]) and len(openapi["paths"]) >= 80
    checks["openapi_version"] = openapi["info"]["version"] == "5.0.0"

    skill_paths = list((ROOT / "xiaoyi/skills").glob("*/SKILL.md"))
    checks["skill_count"] = len(skill_paths) >= 10
    checks["skill_policy_sections"] = all("Policy" in p.read_text(encoding="utf-8") or "policy" in p.read_text(encoding="utf-8") for p in skill_paths)

    pages = parsed["harmonyos/entry/src/main/resources/base/profile/main_pages.json"]["src"]
    checks["harmonyos_v5_page_registered"] = "pages/AgentTrustLabPage" in pages

    manifest = parsed["mcp/tool_manifest.json"]
    high = [item for item in manifest["tools"] if item["name"] in {"youhuo.execute_high_risk", "youhuo.open_break_glass"}]
    checks["generic_high_risk_disabled"] = bool(high) and all(item.get("enabled") is False and item.get("requires_human_confirmation") is True for item in high)

    elder = parsed["reports/elderbench_v5.json"]
    mass = parsed["reports/mass_audit_v5_1000000.json"]
    load = parsed["reports/load_v5_5000.json"]
    chaos = parsed["reports/chaos_v5_400.json"]
    smoke = parsed["reports/http_smoke_v5.json"]
    checks["elderbench_passed"] = elder["passed"] == 300 and elder["failed"] == 0
    checks["mass_audit_passed"] = mass["passed"] == 1_000_000 and mass["failed"] == 0
    checks["load_passed"] = load["successful"] == 5_000 and load["failed"] == 0
    checks["chaos_passed"] = chaos["scenarios"] == 400 and chaos["failed"] == 0
    checks["http_smoke_passed"] = smoke["passed"] is True and smoke["server"] == "real_uvicorn_loopback"

    checks["no_runtime_database"] = not (ROOT / "data/youhuo.db").exists()
    checks["no_generated_audit_key"] = not (ROOT / "data/youhuo.db.audit.key").exists()
    checks["no_env_file"] = not (ROOT / ".env").exists()

    result = {"version": "5.0.0", "passed": all(checks.values()), "checks": checks}
    output = ROOT / "reports/artifact_check_v5.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
