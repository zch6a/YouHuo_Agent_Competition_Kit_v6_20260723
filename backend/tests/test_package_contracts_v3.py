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


def test_harmonyos_trust_center_is_reachable() -> None:
    """信任中心必须在 App 里够得着，而不是"登记在一个 JSON 里"。

    这条原先断言 "pages/TrustCenterPage" in main_pages.json。它一直是绿的，而那段
    时间里这个页面全工程无人 import——「可信」标签挂的是两行占位文字，评委点进去
    什么也没有。登记表只说明文件存在过。
    """
    page = ROOT / "harmonyos/entry/src/main/ets/pages/TrustCenterPage.ets"
    assert page.is_file()
    index = (ROOT / "harmonyos/entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8")
    assert "from './TrustCenterPage'" in index, "Index 没有引入信任中心"
    assert "TrustCenterPage()" in index, "信任中心被引入了却没有被渲染"


def test_competition_description_stays_under_800_chinese_chars_roughly() -> None:
    text = (ROOT / "competition_materials/03_800字作品介绍.md").read_text(encoding="utf-8")
    body = "".join(line for line in text.splitlines() if not line.startswith("#"))
    assert len(body.replace("\n", "")) <= 800


def test_trust_page_names_the_trust_innovations() -> None:
    """这四项可信主张必须写在产品里，而不是只写在文档里。

    此前这条断言钉在 `index.html` 上。首页改成角色选择页之后那些术语被移走了——
    但断言守的意图是对的，只是钉错了页面：`自主权包络` / `证明式完成` / `同意记忆`
    / `家庭共识` 是工程词汇，它们属于可信中心，不属于一位老人或他子女看到的第一屏。
    所以这条测试迁到 `/trust`，不是删掉。
    """
    text = (ROOT / "backend/static/trust.html").read_text(encoding="utf-8")
    for term in ["自主权包络", "证明式完成", "同意记忆", "家庭共识"]:
        assert term in text, f"可信中心没有提到「{term}」"


def test_landing_page_is_a_role_chooser_not_a_directory() -> None:
    """首页只问"你是谁"，不列目录。

    重构前它是 390px 下 8574px 的项目目录：六张导航卡、九个工程术语、一整块工程证据
    区，而视觉权重最高的卡片是「五分钟决赛导览」。
    """
    text = (ROOT / "backend/static/index.html").read_text(encoding="utf-8")
    assert 'href="/elder"' in text and 'href="/family"' in text
    for engineering_term in ["自主权包络", "证明式完成", "同意记忆", "家庭共识",
                             "OpenAPI", "Saga", "C4-AI"]:
        assert engineering_term not in text, f"首页不该出现工程术语「{engineering_term}」"


def test_optional_mcp_not_core_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"mcp' not in pyproject
