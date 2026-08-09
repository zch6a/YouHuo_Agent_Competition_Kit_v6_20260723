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
        "docs/19_V4_COMPLETE_FEATURES.md", "docs/20_MEDICAL_AND_BIOMETRIC_SAFETY.md",
        "docs/21_PRODUCTION_INTEGRATION_GAPS.md", "docs/22_V4_DEMO_SCRIPT.md",
        "docs/23_V4_JUDGE_QA.md", "evaluation/elderbench_v4.jsonl",
        "backend/static/care.html", "backend/static/care.js",
        "harmonyos/entry/src/main/ets/pages/CareHubPage.ets",
        "harmonyos/entry/src/main/ets/pages/HealthArchivePage.ets",
        "harmonyos/entry/src/main/ets/pages/SafetyPage.ets",
        # LocationSafetyAdapter.ets 已删除：16 行、零 `@kit.` 引用、无人 import，
        # 只有一个经纬度范围判断。围栏判定的真实实现在后端 LocationSafety。
        "xiaoyi/plugin_openapi_v4.generated.json",
        "xiaoyi/skills/youhuo-emotion-pause/SKILL.md",
        "xiaoyi/skills/youhuo-health-guard/SKILL.md",
        "xiaoyi/skills/youhuo-location-safety/SKILL.md",
        "mcp/tool_manifest.json",
    ]
    checks["required_files"] = all((ROOT / item).is_file() for item in required)

    yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))
    checks["openapi_yaml"] = True
    json_contracts = [
        "xiaoyi/plugin_openapi_v4.generated.json", "xiaoyi/workflows/youhuo_workflow.json",
        "xiaoyi/a2a/agent_card.json", "mcp/tool_manifest.json",
        "harmonyos/entry/src/main/resources/base/profile/main_pages.json",
        "reports/mass_audit_v4_500000.json", "reports/elderbench_v4.json",
    ]
    for rel in json_contracts:
        json.loads((ROOT / rel).read_text(encoding="utf-8"))
    checks["json_contracts"] = True

    generated_openapi = json.loads((ROOT / "xiaoyi/plugin_openapi_v4.generated.json").read_text(encoding="utf-8"))
    required_paths = {
        "/v4/routines", "/v4/emotions/analyze", "/v4/medical-reports/analyze",
        "/v4/medications/interactions/check", "/v4/location/ping",
        "/v4/reports/monthly", "/v4/capabilities",
    }
    checks["generated_openapi_v4"] = required_paths.issubset(generated_openapi["paths"])

    manifest = json.loads((ROOT / "mcp/tool_manifest.json").read_text(encoding="utf-8"))
    high = next(item for item in manifest["tools"] if item["name"] == "youhuo.execute_high_risk")
    checks["mcp_high_risk_disabled"] = high["enabled"] is False and high["requires_human_confirmation"] is True

    pages = json.loads((ROOT / "harmonyos/entry/src/main/resources/base/profile/main_pages.json").read_text(encoding="utf-8"))
    required_pages = {"pages/TrustCenterPage", "pages/CareHubPage", "pages/HealthArchivePage", "pages/SafetyPage"}
    checks["harmonyos_v4_pages_registered"] = required_pages.issubset(set(pages["src"]))

    skill_paths = list((ROOT / "xiaoyi/skills").glob("*/SKILL.md"))
    checks["skill_count"] = len(skill_paths) >= 6
    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        if "Policy" not in text and "policy" not in text:
            raise AssertionError(f"Skill lacks policy section: {path}")
    checks["skill_contracts"] = True

    mass = json.loads((ROOT / "reports/mass_audit_v4_500000.json").read_text(encoding="utf-8"))
    elder = json.loads((ROOT / "reports/elderbench_v4.json").read_text(encoding="utf-8"))
    checks["audit_report_passed"] = mass["failed"] == 0 and mass["passed"] == 500000
    checks["elderbench_report_passed"] = elder["failed"] == 0 and elder["passed"] == 120

    # A distributable package must not include runtime databases or generated audit keys.
    checks["no_runtime_database"] = not (ROOT / "data/youhuo.db").exists()
    checks["no_generated_audit_key"] = not (ROOT / "data/youhuo.db.audit.key").exists()

    result = {"passed": all(checks.values()), "checks": checks}
    output = ROOT / "reports/artifact_check_v4.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
