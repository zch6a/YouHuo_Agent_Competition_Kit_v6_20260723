"""Voice Orb 的状态表：声明、样式、可达性、可读标签，四者必须对齐。

这个控件是这个产品最重要的视觉资产，而它此前只有三态：JS 写 `processing` /
`listening` / `idle`，CSS 只认前两个。`error` 被折叠进 `idle`——失败了看起来像
"可以再按一次"；`speaking` 根本不存在——agent 正在念回答时屏幕显示的是空闲，老人
按下去打断的是它自己的话。

这一组断言守的不是"代码整齐"，是四种具体的腐蚀：

1. **声明了没样式**——状态表里加一个名字，CSS 里忘了写规则，屏幕上什么都不会变。
2. **有样式没声明**——CSS 里留着一条给早已删掉的状态用的规则，一直没人发现是死的。
3. **声明了到不了**——`ACTIVITY` 里躺着一个谁也不会写进去的状态。这个项目已经栽过
   一次："declared is not reachable"，两整页 Tab 通过了结构审计而实际是死的。
4. **两态说同一句话**——读屏用户看不到环，标签是他们唯一的通道；两态标签相同，
   对他们来说这两态就是同一个。

"关掉动效之后十一态仍然两两可辨"这一条**不在这里**——静态文本比对不了渲染结果。
那一条由 `backend/scripts/check_page_runtime.py` 的 `check_voice_orb_states` 在真实
浏览器里模拟 `prefers-reduced-motion: reduce` 之后逐态取计算样式指纹来测。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: `idle` 是**基态**——它就是 `.mic-dial` / `.mic-big` 的原样，没有也不该有覆盖规则。
#: 这是唯一的豁免，写在这里而不是藏在断言的条件里。
BASE_STATE = "idle"


def _elder_js() -> str:
    return (STATIC / "elder.js").read_text(encoding="utf-8")


def _activity_table() -> dict[str, dict[str, str]]:
    """把 elder.js 里的 `const ACTIVITY = {...}` 读成 Python 字典。

    只截到第一个顶格 `};`——`ACTIVITY` 后面紧跟着别的声明，贪婪匹配会把它们一起吃进来
    然后解析出一堆并不存在的状态。
    """
    text = _elder_js()
    block = re.search(r"^const ACTIVITY = \{\n(.*?)^\};$", text, re.S | re.M)
    assert block, "elder.js 里找不到 `const ACTIVITY = {...}`——状态表被改名或删掉了"
    table: dict[str, dict[str, str]] = {}
    for line in block.group(1).splitlines():
        row = re.match(
            r"\s*(\w+):\s*\{hint:\s*'([^']*)',\s*label:\s*'([^']*)'\}", line
        )
        if row:
            table[row.group(1)] = {"hint": row.group(2), "label": row.group(3)}
    assert table, "状态表解析出来是空的——行格式变了，这个文件的断言全部会变成空转"
    return table


def _styled_states() -> set[str]:
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)   # 注释里也写状态名
    return set(re.findall(r'body\[data-activity="(\w+)"\]', css))


def _reachable_states() -> set[str]:
    """JS 里真的会被写进 `data-activity` 的状态名。

    两个来源：直接传给 `setActivity` / `settleActivity` 的字面量，以及 `activityFor()`
    那两张映射表的值——一轮回复落在哪一态是从那里出来的。
    """
    text = _elder_js()
    reachable = set(re.findall(r"\bsett?le?Activity\('(\w+)'", text))
    reachable |= set(re.findall(r"\bsetActivity\('(\w+)'", text))
    body = re.search(r"^function activityFor\(data\) \{(.*?)^\}$", text, re.S | re.M)
    assert body, "找不到 activityFor()——回复到状态的映射被改名了，可达性这条会变成空转"
    reachable |= set(re.findall(r":\s*'(\w+)',", body.group(1)))
    reachable |= set(re.findall(r"\|\|\s*'(\w+)';", body.group(1)))
    return reachable


def test_orb_has_at_least_ten_states():
    """任务书点名十态。这里是十一——`speaking` 是任务书自己在问题陈述里点出的缺口。"""
    table = _activity_table()
    assert len(table) >= 10, f"Voice Orb 只有 {len(table)} 态：{sorted(table)}"
    assert "speaking" in table, "agent 说话时屏幕必须和空闲时不一样，否则老人会打断它"


def test_every_declared_state_has_a_visual_rule():
    missing = sorted(set(_activity_table()) - _styled_states() - {BASE_STATE})
    assert not missing, f"这些状态在 elder.js 里声明了，但 components.css 里没有任何规则：{missing}"


def test_every_styled_state_is_a_declared_state():
    """反向：CSS 里不许留着状态表里没有的名字。

    正向那条只能发现"少写了样式"。删掉状态表里的一行、CSS 规则忘了跟着删，正向
    照样绿——留下的那条规则从此永远不会命中，而没有任何东西说得出来。
    """
    orphans = sorted(_styled_states() - set(_activity_table()))
    assert not orphans, f"components.css 里这些状态在 elder.js 的状态表里不存在：{orphans}"


def test_every_declared_state_is_reachable():
    unreachable = sorted(set(_activity_table()) - _reachable_states())
    assert not unreachable, (
        f"这些状态声明了、也有样式，但 JS 里没有任何一条路径会写进去：{unreachable}"
    )


def test_no_two_states_say_the_same_thing():
    """读屏用户拿不到环的形状，只有这两行字。两态同词，对他们就是同一态。"""
    table = _activity_table()
    for field in ("hint", "label"):
        seen: dict[str, str] = {}
        for name, spec in table.items():
            twin = seen.setdefault(spec[field], name)
            assert twin == name, f"「{twin}」和「{name}」的 {field} 是同一句：{spec[field]}"


def test_state_words_are_things_an_elder_would_say():
    """标签里不许漏出工程词。

    最容易漏的是状态名本身：`processing` / `error` 这类词一旦顺手写进提示，屏幕上
    就出现了英文枚举值。这一页的读者是一位不认识这些词的老人。
    """
    for name, spec in _activity_table().items():
        for field in ("hint", "label"):
            text = spec[field]
            assert text.strip(), f"「{name}」的 {field} 是空的"
            leaked = re.findall(r"[A-Za-z]+", text)
            assert not leaked, f"「{name}」的 {field} 里有英文：{leaked} —— {text}"


def test_the_gate_reads_the_pages_own_state_list():
    """闸门必须从页面上取状态名，不能自己另存一份。

    `check_voice_orb_states` 逐个把状态写进 `data-activity` 再量样式。如果那份清单
    是脚本里手写的，两份清单会各自漂移——而漂移之后检查照样绿，它只是不再检查新加
    的那一态。
    """
    assert "window.__voiceOrbStates = ACTIVITY;" in _elder_js(), (
        "elder.js 没有把状态表挂出来，闸门会退化成检查一份自己写的清单"
    )
    gate = (ROOT / "backend" / "scripts" / "check_page_runtime.py").read_text(encoding="utf-8")
    assert "Object.keys(window.__voiceOrbStates" in gate, (
        "闸门没有从页面自己的状态表取名字——它在检查一份别处来的清单"
    )
    # 原先这条是"闸门里不许出现任何一个状态名"。它当场就红了，而且**是我写错了**：
    # `'error'` 出现在闸门里，是因为 CDP 客户端要读 `message['error']`——和状态名毫无
    # 关系。`error` / `success` / `idle` 这些词太普通，逐个禁掉只会禁到无关代码。
    #
    # 真正要防的是"有人把动态清单换成一份写死的"。写死的清单至少要三个名字才成其为
    # 清单，所以门槛设在三。
    hardcoded = sorted(
        name for name in _activity_table()
        if re.search(rf"""['"]{name}['"]""", gate)
    )
    assert len(hardcoded) < 3, (
        f"闸门里写死了状态名 {hardcoded}——看起来有人把动态清单换成了自己的一份"
    )
