"""适配层自己说的话必须是真的。

`.claude/skills/youhuo-ui-constraints/SKILL.md` 是一份**给 AI 读的指令**：任何人要在这
个仓库里动 UI，先读它，然后按它的对照表把通用 UI skill 的建议翻译过来。

所以它比普通文档更危险。一份普通文档写错了，读者会困惑；这一份写错了，读者会**照着
错的做**——而它面向的读者恰好是最听话的那一类。

这一组断言守三件事：

1. 它引用的仓库内路径真的存在（今天已经写错过两次这类路径）
2. 它声称的 CSS 令牌真的在 tokens.css 里定义了
3. 它给出的触控下限、CSP 指令、四层顺序和仓库现状一致

`--domain` 取值、`python3` 不存在这类关于**外部 skill** 的事实不在这里测——它们是
另一台机器上的状态，仓库里的测试断言不了。那些是驱动出来的，写在文件里带"实测"字样。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "youhuo-ui-constraints" / "SKILL.md"
STATIC = ROOT / "backend" / "static"


def _text() -> str:
    assert SKILL.is_file(), f"适配层不见了：{SKILL}"
    return SKILL.read_text(encoding="utf-8")


def test_the_adaptation_skill_has_a_description_or_it_never_triggers():
    """没有 description 的 skill 永远不会被触发，而它在列表里看起来完全正常。"""
    text = _text()
    block = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    assert block, "SKILL.md 没有 frontmatter"
    fields = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", block.group(1), re.M))
    assert fields.get("name") == "youhuo-ui-constraints", f"name 不对：{fields.get('name')}"
    desc = fields.get("description", "")
    assert len(desc) > 120, f"description 只有 {len(desc)} 字，太短，触发不可靠"
    # 触发词：这些是它必须被叫起来的场合。
    for word in ("UI", "CSS", "组件", "配色", "动效", "无障碍"):
        assert word in desc, f"description 里没有触发词「{word}」"


def test_every_repo_path_it_mentions_exists():
    """它引用的仓库内路径必须真的存在。

    今天已经写错过两次这类路径：`VISUAL_SCORECARD.md` 指向一个不存在的截图目录，
    交付包 README 指向拍平之前的三层嵌套路径。一份指向不存在路径的说明，比没有说明
    更糟——读者会以为自己找错了地方。
    """
    text = re.sub(r"^---\r?\n.*?\r?\n---", "", _text(), count=1, flags=re.S)
    refs = set()
    for token in re.findall(r"`([^`\n]+)`", text):
        token = token.strip()
        if token.startswith(("backend/", "frontend_redesign/", ".claude/")) and "/" in token:
            refs.add(token)
    assert refs, "没有从 SKILL.md 里解析出任何仓库内路径——这条断言在空转"
    missing = sorted(r for r in refs if not (ROOT / r).exists())
    assert not missing, f"这些路径在仓库里不存在：{missing}"


def test_the_tokens_it_promises_are_really_defined():
    """对照表里承诺的每个 `var(--x)` 都要在 tokens.css 里有定义。

    这一条是翻译表的地基：如果它说「`p-4` 写成 `var(--space-4)`」而 `--space-4` 不存在，
    那条建议会让人写出一条无效声明——CSS 里无效声明是**静默丢弃**的。
    """
    text = _text()
    tokens = set(re.findall(r"var\((--[\w-]+)\)", text))
    assert len(tokens) >= 6, f"只解析出 {len(tokens)} 个令牌引用，太少，可能格式变了"
    defined = set(re.findall(r"^\s*(--[\w-]+)\s*:", (STATIC / "tokens.css").read_text(encoding="utf-8"), re.M))
    undefined = sorted(tokens - defined)
    assert not undefined, f"这些令牌 SKILL.md 里承诺了、tokens.css 里没有：{undefined}"


def test_the_touch_floor_it_states_matches_the_stylesheet():
    """它说 48px 是下限，那样式表里就必须真的是 48。

    这一条最要紧：通用 skill 建议的是 44px，适配层的全部作用就是把它顶回 48。
    如果哪天样式表降到 44 而这份文件还写着 48，AI 会拿着一份过期的"权威"去评审代码。
    """
    text = _text()
    assert "48" in text and "44" in text, "适配层没有同时提到 44 与 48（那是它存在的理由）"
    components = (STATIC / "components.css").read_text(encoding="utf-8")
    floors = [int(m) for m in re.findall(
        r"a,\s*button,\s*input,\s*textarea,\s*select\s*\{[^}]*?min-height:\s*(\d+)px",
        components, re.S)]
    assert floors, "components.css 里找不到全局触控下限那条规则"
    assert all(f >= 48 for f in floors), (
        f"样式表里的触控下限是 {floors}，而适配层写的是 48——两边对不上，改一边"
    )


def test_the_csp_it_quotes_matches_the_server():
    """它引用的**每一条** CSP 指令都必须和 api.py 真的发出去的一致。

    第一版只断言 `default-src 'self'` 和 `script-src 'self'` 各自在文件里**出现过**。
    变异测试当场证明那不够：把第二节那句改成 `script-src 'nonce-x'` 之后它照样绿，
    因为第六节还有一处正确的 `script-src 'self'`。一条"某处提到过就算"的断言，管不住
    另一处写错。

    现在反过来：把文件里每一段看起来像 CSP 的引用逐条拆开，每个指令都拿去 api.py 里核。
    一处写错，那一处就红。
    """
    text = _text()
    api = (ROOT / "backend" / "youhuo" / "api.py").read_text(encoding="utf-8")

    quoted = [t for t in re.findall(r"`([^`\n]+)`", text) if "-src " in t]
    assert quoted, "适配层里没有任何 CSP 引用——这条断言在空转"

    wrong: list[str] = []
    seen = 0
    for chunk in quoted:
        for directive in chunk.split(";"):
            directive = directive.strip()
            if not re.match(r"^[\w-]+-src\s+\S", directive):
                continue
            seen += 1
            if directive not in api:
                wrong.append(directive)
    assert seen >= 2, f"只解析出 {seen} 条 -src 指令，格式可能变了"
    assert not wrong, (
        f"适配层引用了 api.py 并不发送的策略：{sorted(set(wrong))}"
        "——照它做的人会以为可以用一条这个服务器不给的能力"
    )
    # 反向：这两条是这个项目的地基，必须被引用到。
    for directive in ("default-src 'self'", "script-src 'self'"):
        assert directive in text, f"适配层没有引用 {directive}"


def test_the_four_layer_order_it_states_is_the_real_load_order():
    """四层顺序写错，读者会把响应式覆盖放到错的位置，而那会静默输掉层叠。"""
    text = _text()
    assert "tokens → base → components → pages" in text, "四层顺序没有写出来"
    for page in ("elder.html", "trust.html", "judge.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        order = re.findall(r'<link rel="stylesheet" href="/static/(\w+)\.css"', html)
        assert order == ["tokens", "base", "components", "pages"], (
            f"{page} 的样式表加载顺序是 {order}，和适配层写的四层顺序不一致"
        )


def test_claude_md_points_at_the_adaptation_layer():
    """CLAUDE.md 是这个仓库自动加载的那一份，它必须把人引到适配层。

    适配层再准确，没人被引到它面前也等于不存在。
    """
    md = ROOT / "CLAUDE.md"
    assert md.is_file(), "仓库没有 CLAUDE.md，适配层不会有人读到"
    text = md.read_text(encoding="utf-8")
    assert ".claude/skills/youhuo-ui-constraints/SKILL.md" in text, (
        "CLAUDE.md 没有指向适配层"
    )
    # CLAUDE.md 自己引用的路径也要存在。
    refs = {t for t in re.findall(r"\(([^)\s]+\.md)\)", text) if not t.startswith("http")}
    missing = sorted(r for r in refs if not (ROOT / r).exists())
    assert not missing, f"CLAUDE.md 里这些路径不存在：{missing}"
