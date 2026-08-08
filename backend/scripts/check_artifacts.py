from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    checks: dict[str, bool] = {}
    required = [
        "README.md", "PACKAGE_INDEX.md", "competition_materials/03_800字作品介绍.md",
        "docs/13_V3_INNOVATION.md", "docs/14_ELDERBENCH.md",
        "harmonyos/entry/src/main/ets/pages/TrustCenterPage.ets",
        "xiaoyi/a2a/agent_card.json", "xiaoyi/skills/youhuo-task-guard/SKILL.md",
        "mcp/tool_manifest.json",
    ]
    checks["required_files"] = all((ROOT / item).is_file() for item in required)

    yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))
    checks["openapi_yaml"] = True
    for rel in [
        "xiaoyi/workflows/youhuo_workflow.json", "xiaoyi/a2a/agent_card.json",
        "mcp/tool_manifest.json", "harmonyos/entry/src/main/resources/base/profile/main_pages.json",
    ]:
        json.loads((ROOT / rel).read_text(encoding="utf-8"))
    checks["json_contracts"] = True

    manifest = json.loads((ROOT / "mcp/tool_manifest.json").read_text(encoding="utf-8"))
    high = next(item for item in manifest["tools"] if item["name"] == "youhuo.execute_high_risk")
    checks["mcp_high_risk_disabled"] = high["enabled"] is False and high["requires_human_confirmation"] is True

    pages = json.loads((ROOT / "harmonyos/entry/src/main/resources/base/profile/main_pages.json").read_text(encoding="utf-8"))
    checks["trust_center_registered"] = "pages/TrustCenterPage" in pages["src"]

    for rel in [
        "xiaoyi/skills/youhuo-task-guard/SKILL.md",
        "xiaoyi/skills/wuyou-companion-privacy/SKILL.md",
        "xiaoyi/skills/youhuo-document-firewall/SKILL.md",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Purpose" in text and "Policy" in text or "Mandatory policy" in text
    checks["skill_contracts"] = True

    result = {"passed": all(checks.values()), "checks": checks}
    output = ROOT / "reports/artifact_check_v3.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
