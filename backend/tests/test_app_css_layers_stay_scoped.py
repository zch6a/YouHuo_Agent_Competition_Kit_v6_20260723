"""每一页专属的 `app-*.css` 只能是**第五层**，不许悄悄变成第二套设计系统。

这一轮把三个页面的重构分给了三个并行的 agent，各写一个 `app-<page>.css`。
这种分工能避免文件冲突，但会带来另一个问题：三份文件各自发明一套卡片、
一套阴影、一套字号，最后页面之间看起来像三个产品。`landing.css` 已经开了
「一页一层」的先例，所以规则要在它长成第二套系统之前就立好。

这条判据管四件事：
  · 加载顺序：`app-*.css` 必须排在四层之后（层叠顺序 = 加载顺序，这个项目
    在「规则的位置决定它生不生效」上已经栽过四次）
  · 不许写死颜色：面色/墨色一律走令牌，否则深色模式必坏——首页刚栽过
  · 不许出现字阶里没有的字号（12px / 14px 这类）
  · 不许用 `!important` 去压四层：那等于把共享层架空
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
LAYERS = ("tokens.css", "base.css", "components.css", "pages.css")

#: 一页专属的第五层。`landing.css` 是既有的那一个。
PAGE_LAYERS = sorted(
    [p.name for p in STATIC.glob("app-*.css")] + ["landing.css"]
)


def _pages_loading(sheet: str) -> list[Path]:
    return [p for p in STATIC.glob("*.html") if f'href="/static/{sheet}"' in
            p.read_text(encoding="utf-8")]


@pytest.mark.parametrize("sheet", PAGE_LAYERS)
def test_page_layer_loads_after_the_four_shared_layers(sheet: str) -> None:
    """第五层必须排在四层之后——否则它写的每一条覆写都在同等特异性下输掉。"""
    for page in _pages_loading(sheet):
        html = page.read_text(encoding="utf-8")
        order = [m.group(1) for m in
                 re.finditer(r'<link[^>]+href="/static/([\w.-]+\.css)"', html)]
        assert sheet in order, f"{page.name} 没有加载 {sheet}"
        mine = order.index(sheet)
        for layer in LAYERS:
            if layer in order:
                assert order.index(layer) < mine, (
                    f"{page.name}：{sheet} 排在 {layer} 前面。"
                    "加载顺序就是层叠顺序，排前面等于这一层的覆写全部失效。"
                )


@pytest.mark.parametrize("sheet", PAGE_LAYERS)
def test_page_layer_has_no_hardcoded_surface_colour(sheet: str) -> None:
    """不许写死面色/墨色。

    首页正是这么坏的：画布、卡片、磁贴的底色全写死成浅色，文字却走令牌会翻转，
    深色模式下近白字压近白底，量出来 1.09:1，两张身份卡的标题一个字都看不见。
    """
    css = (STATIC / sheet).read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # 注释里可以出现色值
    offenders = []
    for m in re.finditer(r"(background|background-color|color|border-color)\s*:\s*([^;{}]+)", css):
        value = m.group(2)
        if "var(" in value or "currentColor" in value or "transparent" in value:
            continue
        if re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", value):
            # 纯白/纯黑的半透明叠加层是合法的（高光与遮罩），它们不随主题翻转
            if re.fullmatch(r"\s*rgba\(\s*(255,\s*255,\s*255|0,\s*0,\s*0)\s*,[^)]*\)\s*", value):
                continue
            offenders.append(f"{m.group(1)}: {value.strip()[:48]}")
    assert not offenders, (
        f"{sheet} 写死了颜色：{offenders[:6]}。"
        "面色和墨色必须走令牌，否则深色模式下必然出现「只翻文字不翻底」。"
    )


@pytest.mark.parametrize("sheet", PAGE_LAYERS)
def test_page_layer_stays_on_the_type_scale(sheet: str) -> None:
    """不许出现字阶里没有的字号。与 test_design_rulers 的那条同源。"""
    css = re.sub(r"/\*.*?\*/", "",
                 (STATIC / sheet).read_text(encoding="utf-8"), flags=re.S)
    offenders = []
    for m in re.finditer(r"font-size\s*:\s*([\d.]+)px", css):
        px = float(m.group(1))
        if px >= 16 or px in (13.0, 15.0):
            continue
        offenders.append(f"{px}px")
    assert not offenders, (
        f"{sheet} 有字阶外的字号：{offenders}。"
        "字阶只有 --text-xs(13，仅限元数据) 和 --text-sm(15)，中间没有一档。"
    )


@pytest.mark.parametrize("sheet", PAGE_LAYERS)
def test_page_layer_does_not_shout_important(sheet: str) -> None:
    """不许用 `!important` 压四层。

    第五层排在最后，同等特异性下本来就赢；需要 `!important` 只有两种可能：
    要么选择器写错了，要么正在跟共享层对着干——两种都该在这里停下来。
    唯一豁免是 `prefers-reduced-motion` 里那种「一次性掐掉所有动效」的写法。
    """
    css = (STATIC / sheet).read_text(encoding="utf-8")
    #: 花括号配平，不能靠 `\n\}` 收尾——landing.css 的 reduced-motion 整块写在
    #: **一行**里，那种写法下正则永远匹配不上，于是豁免形同虚设（第一版就是这样，
    #: 它把一个合法的写法报成了违规）。
    while True:
        m = re.search(r"@media[^{]*prefers-reduced-motion[^{]*\{", css)
        if not m:
            break
        i, depth = m.end(), 1
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        css = css[:m.start()] + css[i:]
    hits = re.findall(r"[^;{}]*!important", css)
    assert not hits, (
        f"{sheet} 用了 !important：{[h.strip()[:44] for h in hits[:5]]}。"
        "第五层已经排在最后，赢不了说明选择器不对，而不是需要更大声。"
    )
