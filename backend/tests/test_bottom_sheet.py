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
    assert re.search(r'<span>[^<]*待办[^<]*</span>', trigger.group(0)), "触发器缺少文字标签"


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
    wide = CSS[CSS.index("@media (min-width: 761px) {"):]
    wide = wide[: wide.index("\n}")]
    assert "position: static" in wide, "宽屏必须回到静态侧栏"
    assert "transform: none" in wide
    assert ".sheet-trigger" in wide and "display: none" in wide, "宽屏不该显示触发器"


def test_focus_is_returned_when_the_sheet_closes():
    assert "lastFocus" in JS, "关闭后应把焦点还给触发按钮"
