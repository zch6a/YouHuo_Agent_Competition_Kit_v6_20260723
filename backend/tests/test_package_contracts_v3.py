from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_project_version_is_v6() -> None:
    assert 'version = "6.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_required_v4_docs_exist() -> None:
    for rel in ["docs/19_V4_COMPLETE_FEATURES.md", "docs/20_MEDICAL_AND_BIOMETRIC_SAFETY.md", "docs/21_PRODUCTION_INTEGRATION_GAPS.md", "docs/22_V4_DEMO_SCRIPT.md", "docs/23_V4_JUDGE_QA.md"]:
        assert (ROOT / rel).is_file()


def test_xiaoyi_openapi_parses() -> None:
    assert yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))["openapi"]


def test_a2a_card_contract() -> None:
    card = json.loads((ROOT / "xiaoyi/a2a/agent_card.json").read_text(encoding="utf-8"))
    assert card["security"]["authoritative_backend_required"] is True
    assert card["task_state_mapping"]["completed"] == "TASK_STATE_COMPLETED"


def test_v4_skill_specs_exist_and_forbid_unsafe_actions() -> None:
    paths = list((ROOT / "xiaoyi/skills").glob("*/SKILL.md"))
    assert len(paths) >= 6
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "自动支付" in combined and "不可信" in combined and "完整聊天" in combined


def test_mcp_manifest_disables_high_risk_execution() -> None:
    data = json.loads((ROOT / "mcp/tool_manifest.json").read_text(encoding="utf-8"))
    high = next(item for item in data["tools"] if item["name"] == "youhuo.execute_high_risk")
    assert high["enabled"] is False
    assert high["requires_human_confirmation"] is True


def test_harmonyos_trust_center_registered() -> None:
    pages = json.loads((ROOT / "harmonyos/entry/src/main/resources/base/profile/main_pages.json").read_text(encoding="utf-8"))
    assert "pages/TrustCenterPage" in pages["src"]
    assert (ROOT / "harmonyos/entry/src/main/ets/pages/TrustCenterPage.ets").is_file()


def test_competition_description_stays_under_800_chinese_chars_roughly() -> None:
    text = (ROOT / "competition_materials/03_800字作品介绍.md").read_text(encoding="utf-8")
    body = "".join(line for line in text.splitlines() if not line.startswith("#"))
    assert len(body.replace("\n", "")) <= 800


def test_landing_page_mentions_trust_innovations() -> None:
    text = (ROOT / "backend/static/index.html").read_text(encoding="utf-8")
    for term in ["自主权包络", "证明式完成", "同意记忆", "家庭共识"]:
        assert term in text


def test_optional_mcp_not_core_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"mcp' not in pyproject
