"""底部 Sheet：手机上把非对话内容移出主屏。

交互规则直接取自 Framework7 的 sheet-class.js（移动端 Web 被抄得最多的那个 sheet）：

    if ((timeDiff < 300 && diff > 20) || (timeDiff >= 300 && diff > height / 2))

300ms 内的轻扫只需 20px；慢拖必须越过一半高度。这套组合既不粘手也不敏感，而且
恰好适合这个受众：刻意关闭几乎不费力，而犹疑游移的手指不会误关。

这里钉住三件容易在后续改动中悄悄坏掉的事：
1. Sheet 不能只能用手势打开——**必须有一个带文字的按钮**；只有手势的界面第一个
   淘汰的就是这个受众；
2. 关闭状态用 transform 移出屏幕，而不是 display:none——对比度审计要测这些控件的
   计算颜色，隐藏它们会悄悄缩小那张安全网，而不是响亮地失败；
3. 宽屏必须退回原来的侧栏，不能残留 sheet 的样式。
"""

from __future__ import annotations

import re
from pathlib import Path

from .helpers import read_stylesheet

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
HTML = (STATIC / "elder.html").read_text(encoding="utf-8")
CSS = read_stylesheet()
JS = (STATIC / "sheet.js").read_text(encoding="utf-8")


# --- the sheet is never gesture-only -------------------------------------


def test_a_labelled_button_opens_the_sheet():
    assert 'data-sheet-open' in HTML, "没有打开 Sheet 的触发器"
    trigger = re.search(r'<button[^>]*data-sheet-open.*?</button>', HTML, re.S)
    assert trigger, "触发器不是 button"
    # A real word, not just an icon: an icon-only control is unlabelled for both
    # a screen reader and a 78-year-old.
    #
    # 原判据是「标签里必须含"待办"」。抽屉换了用途之后这条红了——它现在装的是
    # 「更多说法」（想不出怎么开口时的例子），待办搬去了首页的「今天」。
    #
    # 那个词从来不是这条断言要守的东西：它守的是**这个控件有没有可读的名字**，
    # 因为一个只有图标的控件对读屏软件和一位 78 岁的用户都等于没有名字。
    # 所以判据改成"有一段非空的中文文字标签"，不再钉某一个词。
    label = re.search(r'<span>([^<]+)</span>', trigger.group(0))
    assert label, "触发器缺少文字标签"
    assert re.search(r"[一-鿿]", label.group(1)), (
        f"触发器的标签里没有中文：{label.group(1)!r}"
    )


def test_the_trigger_reports_its_state():
    trigger = re.search(r'<button[^>]*data-sheet-open[^>]*>', HTML).group(0)
    assert 'aria-expanded' in trigger
    assert 'aria-controls="extrasSheet"' in trigger


def test_the_handle_is_a_real_button_with_a_name():
    handle = re.search(r'<button[^>]*class="sheet-handle"[^>]*>', HTML)
    assert handle, "拖动把手必须是 button，键盘用户才能用"
    assert 'aria-label' in handle.group(0)
    assert 'data-sheet-close' in handle.group(0)


def test_escape_and_backdrop_also_close():
    assert "'Escape'" in JS
    assert re.search(r"backdrop\.addEventListener\('click'", JS)


# --- the Framework7 dismissal rule ---------------------------------------


def test_flick_and_drag_thresholds_match_the_reference():
    assert "FLICK_MS = 300" in JS, "轻扫时间窗应为 300ms（Framework7）"
    assert "FLICK_PX = 20" in JS, "轻扫距离应为 20px（Framework7）"
    # Slow drag must commit past half the sheet.
    assert re.search(r"offset > sheet\.offsetHeight / 2", JS), "慢拖阈值应为一半高度"


def test_only_the_handle_starts_a_drag():
    """Dragging from the body would fight the scrollable list inside."""
    assert "closest('.sheet-handle')" in JS


def test_drag_is_downward_only():
    assert re.search(r"Math\.max\(0,\s*event\.clientY - startY\)", JS)


# --- closed state stays measurable --------------------------------------


def test_closed_sheet_is_moved_not_hidden():
    """display:none would remove these controls from the contrast audit."""
    block = CSS[CSS.index(".rail.sheet {"):]
    rule = block[: block.index("}")]
    assert "translate3d(0, 100%, 0)" in rule, "关闭状态应用 transform 移出屏幕"
    assert "display: none" not in rule, "不能用 display:none 关闭"


def test_closed_sheet_is_inert_for_assistive_tech():
    """Moved off-screen is still focusable unless it is marked inert."""
    assert "setAttribute('inert'" in JS
    assert "removeAttribute('inert')" in JS


def test_sheet_settles_with_the_overdamped_token():
    block = CSS[CSS.index(".rail.sheet {"):]
    rule = block[: block.index("}")]
    assert "var(--dur-sheet)" in rule and "var(--ease-out)" in rule, (
        "过渡应使用来自 gorhom/bottom-sheet 的 250ms 过阻尼令牌"
    )


def test_dur_sheet_is_250ms():
    assert "--dur-sheet: 250ms" in CSS


# --- wide screens keep the sidebar --------------------------------------


def test_wide_viewport_reverts_to_the_sidebar():
    """宽屏上抽屉回到它一直是的那个侧栏。

    原写法取的是**第一个** `@media (min-width: 761px)` 块。老人端改成四 Tab 之后，
    样式表里多了一个同宽度的块（那一个让 Tab 在宽屏上变成顶部横排），而它排在前面
    ——于是这条断言去一个跟抽屉毫无关系的块里找 `transform: none`，红了。

    这不是抽屉坏了，是这条断言假设"这个宽度的块只有一个"。找**含 `.rail.sheet` 的
    那一个**，不靠出现顺序。
    """
    blocks = [
        CSS[m.start():][: CSS[m.start():].index("\n}")]
        for m in re.finditer(r"@media \(min-width: 761px\) \{", CSS)
    ]
    assert blocks, "样式表里没有 min-width: 761px 的块"
    wide = next((b for b in blocks if ".rail.sheet" in b), None)
    assert wide, (
        f"{len(blocks)} 个 min-width: 761px 的块里没有一个提到 .rail.sheet"
        "——宽屏上抽屉不再变回侧栏了"
    )
    assert "position: static" in wide, "宽屏必须回到静态侧栏"
    assert "transform: none" in wide
    assert ".sheet-trigger" in wide and "display: none" in wide, "宽屏不该显示触发器"


def test_focus_is_returned_when_the_sheet_closes():
    assert "lastFocus" in JS, "关闭后应把焦点还给触发按钮"
