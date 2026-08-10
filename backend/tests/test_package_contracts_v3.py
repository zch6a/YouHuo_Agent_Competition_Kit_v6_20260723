from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_project_version_is_v6() -> None:
    assert 'version = "6.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_required_v4_docs_exist() -> None:
    """必需文档必须真的有内容，不只是"文件在"。

    原先只查 `is_file()`：把 `docs/22_V4_DEMO_SCRIPT.md` 截断成 0 字节，测试通过。
    交付包里一份空的演示脚本比没有更糟——它让人以为那件事已经写过了。
    """
    for rel in ["docs/19_V4_COMPLETE_FEATURES.md", "docs/20_MEDICAL_AND_BIOMETRIC_SAFETY.md",
                "docs/21_PRODUCTION_INTEGRATION_GAPS.md", "docs/22_V4_DEMO_SCRIPT.md",
                "docs/23_V4_JUDGE_QA.md"]:
        path = ROOT / rel
        assert path.is_file(), f"{rel} 不存在"
        body = path.read_text(encoding="utf-8")
        # 除掉标题之后仍须有实质内容：一份只剩一行 `# 标题` 的文档等于没写。
        prose = "".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
        # 下限 200：实测最短的一份是 299（20_MEDICAL_AND_BIOMETRIC_SAFETY.md）。
        # 这条要判的是"不为空"，不是"够长"——定 400 就变成了要求这些文档增长，
        # 而我没有任何依据说它们该多长。
        assert len(prose.strip()) >= 200, (
            f"{rel} 去掉标题后只剩 {len(prose.strip())} 个字符——它是空的"
        )


def test_xiaoyi_openapi_parses() -> None:
    assert yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))["openapi"]


def test_a2a_card_contract() -> None:
    card = json.loads((ROOT / "xiaoyi/a2a/agent_card.json").read_text(encoding="utf-8"))
    assert card["security"]["authoritative_backend_required"] is True
    assert card["task_state_mapping"]["completed"] == "TASK_STATE_COMPLETED"


#: 禁止性语气。这些词出现，才说明那一段是在**划边界**而不是在**宣传能力**。
#:
#: 中文的否定不是一个封闭的词表：实测漏掉了「不包含聊天原文」这种写法（列举 不得/
#: 不能/不会/不向/不做 是徒劳的，`不` 后面可以接任何动词）。所以用 `不X` 的通式，
#: 再加上少数不带「不」的禁止词。
_PROHIBITION_RE = re.compile(
    r"不[一-鿿]|禁止|拒绝|永不|绝不|无权|除外|Forbidden|forbidden|must not|never",
)

#: 这些 `不X` 不是禁止语，是这个项目里的**类别名**。
#:
#: `不可信` 指的是数据来源的一个分类（OCR/VLM 文本视为不可信数据），不是"禁止"。
#: 审计给的那个反例正是靠它蒙过去的："…并把完整聊天记录上传给**不可信**的第三方。"
#: ——一句纯粹在宣传危险能力的话，因为里面有"不可信"三个字而被判成划了边界。
#: 通式 `不X` 的代价就在这里，所以要把当名词用的那几个减掉。
_NOT_A_PROHIBITION = ("不可信", "不一致", "不足", "不同", "不明", "不确定")


def _forbids(text: str) -> bool:
    for word in _NOT_A_PROHIBITION:
        text = text.replace(word, "")
    return bool(_PROHIBITION_RE.search(text))

#: 出现即高风险的能力词。它们只允许出现在禁止性语境里。
_DANGEROUS = ("自动支付", "代替支付", "代替人脸", "读取验证码", "完整聊天", "聊天原文",
              "完整医疗档案", "身份秘密")


def test_v4_skill_specs_exist_and_forbid_unsafe_actions() -> None:
    """每份技能说明都必须**划出边界**，而不是只提到过那几个词。

    这条原先把六份文件拼成一个字符串，查 `自动支付` / `不可信` / `完整聊天` 三个词
    出现过。语义方向完全没查——一份 SKILL.md 里写"本技能会自动支付账单，并把完整
    聊天记录上传给不可信的第三方"照样通过，而函数名里的 `forbid` 没有任何对应断言。
    这是这个包里最该说真话的六份文件：小艺技能说明是提交给平台的能力声明。

    现在两条判据：
    1. 每一份都必须至少有一处禁止性表述——没有边界的技能说明不是技能说明；
    2. 每一处高风险能力词都必须落在禁止性语境里：要么同一行有否定词，要么它所在的
       小节标题是禁止性的（`## Forbidden scopes` 这种）。
    """
    paths = sorted((ROOT / "xiaoyi/skills").glob("*/SKILL.md"))
    assert len(paths) >= 6, f"技能说明只有 {len(paths)} 份"

    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        name = path.parent.name
        assert any(_forbids(line) for line in lines), (
            f"{name}/SKILL.md 通篇没有一处禁止性表述——它只在宣传能力"
        )
        heading = ""
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                heading = line
            hits = [word for word in _DANGEROUS if word in line]
            if not hits:
                continue
            # 判据是**同一句之内**，不是"同一行随便什么位置"，也不是"必须在词之前"。
            #
            # "同一行任意位置"太松："本技能会自动支付账单，但不记录日志" 会算作划了
            # 边界。"必须在词之前"又太紧——中文的禁止可以在句首也可以在句尾，实测
            # 撞上了 "`execute_payment`、泄露陪聊、提交身份秘密、药物诊断永久禁止。"，
            # 那是完全正常的写法。句子才是这里真正的语义单位。
            clauses = re.split(r"[。；;!?！？]", line)
            in_context = (
                any(
                    any(word in clause for word in hits) and _forbids(clause)
                    for clause in clauses
                )
                or _forbids(heading)
            )
            assert in_context, (
                f"{name}/SKILL.md:{number} 提到 {hits} 却不在禁止性语境里"
                f"（所在小节：{heading.strip() or '（无标题）'}）：{line.strip()}"
            )


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
    # 注释掉的调用不算渲染。
    #
    # `// TrustCenterPage()` 留着 import 就能让这条测试通过——而它是为"页面全工程无人
    # import、标签挂着两行占位文字"那个缺陷换来的。改进之后仍然是全文子串匹配，
    # 于是同一类失效换个形式又回来了。先剥注释。
    body = re.sub(r"/\*.*?\*/", "", index, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    assert "from './TrustCenterPage'" in body, "Index 没有引入信任中心"
    assert "TrustCenterPage()" in body, "信任中心被引入了却没有被渲染（调用被注释掉了？）"


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
    # 注释不算"写在产品里"。
    #
    # 这条原先不剥 HTML 注释，而它的姐妹断言（test_pwa_shell 里查工程术语那条）剥了。
    # 于是把四个词从可见内容里全删、只留一行 `<!-- 自主权包络 证明式完成 … -->`
    # 就能通过——而这条守的恰恰是"必须写在产品里，而不是只写在文档里"。
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for term in ["自主权包络", "证明式完成", "同意记忆", "家庭共识"]:
        assert term in visible, f"可信中心没有提到「{term}」（只在注释里不算）"


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
    """mcp 只能是可选依赖，不能进 `[project] dependencies`。

    原先查的是"整个 pyproject 里任何位置都不许出现 `"mcp`"——一条注释里提到它就会红，
    而真把它加进 `[project] dependencies` 时如果写法稍有不同（比如 `mcp>=1.0` 不带
    引号前缀）反而漏掉。判据既过宽又过窄。现在解析 TOML，只判那一份清单。

    **不**顺带要求它登记在 `optional-dependencies` 里——我一开始那么写了，实测红：
    这个项目里 mcp 根本不是 Python 依赖，`mcp/tool_manifest.json` 是一份给外部
    运行时读的清单。断言一个不存在的要求，就是把测试变成许愿。
    """
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core = [str(item) for item in data.get("project", {}).get("dependencies", [])]
    offenders = [item for item in core if re.match(r"^\s*mcp\b", item)]
    assert not offenders, f"mcp 进了核心依赖：{offenders}"
