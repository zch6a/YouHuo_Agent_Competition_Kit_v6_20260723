r"""老人端两个覆盖层必须实现同一组无障碍行为。

## 为什么是两份实现而不是一份

`sheet.js` 是「更多说法」那个抽屉，而它在 ≥761px 会**变成一根常驻侧栏**
（`isDrawer()` 问 CSS「触发器还看得见吗」）。事务详情层在任何宽度下都是模态，
共用一个模块就得给那个双形态再加一个开关——而 `sheet.js` 是这一页最精细的
无障碍代码，它的注释里记着一次真实事故：

    「此前这里无条件按抽屉处理……于是 ≥761px 时侧栏照样渲染出来、看起来完全正常，
     而里面十几个控件全被 inert + aria-hidden 打死……且**没有任何恢复路径**」

所以选择两份实现。代价是它们会漂移——这个文件就是那个代价的抵押品：
**任何一份少掉一个行为，这里红。**

## 四个行为，每一个都对应一类真实故障

| 行为 | 少了它会怎样 |
|---|---|
| 背后整体 `inert` | 背板拦得住鼠标，拦不住 Tab。键盘用户会 Tab 进一个被完全盖住的输入框 |
| 焦点存取 | 关掉之后焦点掉回 `<body>`，键盘用户丢失位置，读屏用户不知道回到了哪 |
| Escape | 键盘用户没有不用找按钮的出路 |
| 真按钮做出口 | `sheet.js` 自己的注释：「Gesture-only UI fails this audience first」 |
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: 两份实现各自在哪个文件里。`sheet.js` 是独立模块；详情层的控制器住在 `elder.js`
#: 里（它要用那一页的 `api()` 和记录列表，拆出去只是多一个文件）。
IMPLEMENTATIONS = {
    "sheet.js（更多说法抽屉）": "sheet.js",
    "elder.js（事务详情层）": "elder.js",
}


def _source(name: str) -> str:
    text = (STATIC / name).read_text(encoding="utf-8")
    # 去注释保留换行。这里尤其要紧：两个文件的注释都**大段讨论** inert 和焦点，
    # 不去掉的话每一条断言都会被注释喂饱，然后全绿——而这个项目已经有过四次
    # 「测试匹配到了我自己写的那条注释」。
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


@pytest.mark.parametrize("label,filename", sorted(IMPLEMENTATIONS.items()))
def test_it_makes_the_layers_behind_inert(label: str, filename: str) -> None:
    source = _source(filename)
    assert re.search(r"""setAttribute\(\s*['"]inert['"]""", source), (
        f"{label} 没有给背后的层加 `inert`。"
        "背板拦得住鼠标，拦不住 Tab——键盘用户会 Tab 进一个被完全盖住的输入框。"
    )
    assert re.search(r"""removeAttribute\(\s*['"]inert['"]""", source), (
        f"{label} 只加 `inert` 不摘。关掉之后整页就再也点不动了。"
    )
    # 判据不是「出现过 inert」，而是它作用在**背后那些层**上。两份实现都用同一个
    # 选择器找它们（`main > *, .elder-layout > *`），这是它们唯一共享的约定。
    assert "main > *" in source or ".elder-layout > *" in source, (
        f"{label} 没有枚举背后的层——`inert` 大概只加在了自己身上，那不隔离任何东西。"
    )


@pytest.mark.parametrize("label,filename", sorted(IMPLEMENTATIONS.items()))
def test_it_saves_and_restores_focus(label: str, filename: str) -> None:
    source = _source(filename)
    assert "document.activeElement" in source, (
        f"{label} 打开时没记住焦点在哪。关掉之后焦点会掉回 <body>："
        "键盘用户丢失位置，读屏用户不知道自己回到了哪。"
    )
    assert re.search(r"\.focus\(\s*\{\s*preventScroll:\s*true\s*\}\s*\)", source), (
        f"{label} 的 `.focus()` 没有 `preventScroll: true`。"
        "不加它，聚焦会把页面滚到那个元素——而它此刻可能在一层覆盖之下。"
    )


@pytest.mark.parametrize("label,filename", sorted(IMPLEMENTATIONS.items()))
def test_escape_closes_it(label: str, filename: str) -> None:
    source = _source(filename)
    assert re.search(r"""['"]Escape['"]""", source), (
        f"{label} 不响应 Escape。键盘用户必须有一条不用找按钮的出路。"
    )


def test_each_overlay_has_a_real_button_as_its_exit() -> None:
    """出口是真 `<button>`，而且有可读的文字。

    `sheet.js` 自己的注释写着「The sheet is never gesture-only: it opens and closes
    from a real labelled button. Gesture-only UI fails this audience first.」
    详情层照这条办：它连甩动关闭都没有，出口就是底部那个按钮。
    """
    html = (STATIC / "elder.html").read_text(encoding="utf-8")

    # 抽屉：把手是带 aria-label 的按钮
    assert re.search(
        r"<button[^>]*class=['\"]sheet-handle['\"][^>]*data-sheet-close[^>]*aria-label=",
        html,
    ), "「更多说法」抽屉的收起按钮不见了，或者不再带 aria-label"

    # 详情层：底部一个有文字的按钮
    exit_button = re.search(
        r"<button[^>]*id=['\"]taskDetailClose['\"][^>]*>(.*?)</button>", html, re.S)
    assert exit_button, "事务详情层没有 #taskDetailClose 这个出口按钮"
    words = exit_button.group(1).strip()
    assert words and not re.search(r"[A-Za-z]", words), (
        f"详情层出口按钮的文字是 {words!r}——要么是空的（读屏念不出来），"
        "要么有英文（这一页的读者是一位老人，而老人端还会念出来）"
    )


def test_the_detail_layer_is_a_dialog_and_starts_closed() -> None:
    """详情层在 HTML 里就是关着的，而且报得出自己是个对话框。

    起始状态写在 HTML 而不是等 JS 跑：`elder.js` 是 `type="module"`，
    它的执行晚于首次绘制。少了 `inert` / `aria-hidden`，在 JS 跑起来之前
    这一层是可 Tab 的、读屏能念的——一个用户还没打开就已经存在的模态。
    """
    html = (STATIC / "elder.html").read_text(encoding="utf-8")
    layer = re.search(r"<aside[^>]*id=['\"]taskDetail['\"][^>]*>", html)
    assert layer, "找不到 #taskDetail"
    tag = layer.group(0)
    assert 'role="dialog"' in tag, f"少了 role=dialog：{tag}"
    assert 'aria-modal="true"' in tag, f"少了 aria-modal：{tag}"
    assert "aria-labelledby=" in tag, f"没有可读的名字（aria-labelledby）：{tag}"
    assert 'aria-hidden="true"' in tag, f"初始状态不是关着的（aria-hidden）：{tag}"
    assert re.search(r"\binert\b", tag), f"初始状态没有 inert：{tag}"


def test_the_detail_backdrop_is_not_the_sheet_backdrop() -> None:
    """详情层的背板不能复用 `.sheet-backdrop`。

    `.sheet-backdrop` 的样式**整段**写在 `@media (max-width: 760px)` 里，
    并且在 `min-width: 761px` 被 `display: none`——那个抽屉在宽屏变成常驻侧栏，
    所以它不需要背板。而详情层在任何宽度下都是模态：复用那个类的结果是
    它在桌面上**没有背板**，一个静默失效的模态。
    """
    html = (STATIC / "elder.html").read_text(encoding="utf-8")
    backdrop = re.search(r"<div[^>]*id=['\"]detailBackdrop['\"][^>]*>", html)
    assert backdrop, "找不到 #detailBackdrop"
    assert "sheet-backdrop" not in backdrop.group(0), (
        "详情层的背板复用了 `.sheet-backdrop`——那个类在 ≥761px 是 display:none，"
        "于是这一层在桌面上没有背板。"
    )

    pages = (STATIC / "pages.css").read_text(encoding="utf-8")
    # 它自己的样式必须在全局作用域。判据：`.detail-backdrop` 与 `.detail-layer`
    # 的规则出现在文件里任何 `@media` 块**之外**。
    stripped = re.sub(r"/\*.*?\*/", "", pages, flags=re.S)
    depth = 0
    in_media = 0
    offenders = []
    i = 0
    while i < len(stripped):
        if stripped.startswith("@media", i):
            in_media = depth + 1
        ch = stripped[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if in_media and depth < in_media:
                in_media = 0
        for selector in (".detail-backdrop", ".detail-layer"):
            if stripped.startswith(selector, i) and in_media:
                offenders.append(selector)
        i += 1
    assert not offenders, (
        f"这些规则被写进了 @media 里：{sorted(set(offenders))}。"
        "详情层在任何宽度下都是模态，它的样式必须在全局作用域——"
        "这个项目在「规则的位置决定它生不生效」上咬过四次。"
    )
