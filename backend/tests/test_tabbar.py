"""底部标签栏：五个控制台页面的常驻导航。

这些页面原本用左上角的「← 返回首页」导航。那是网页的位置模型——"你从某处来，
这是回去的路"。应用的模型是"这些是你能去的地方，你现在在这一个"：常驻、在底部
拇指本来就搁着的位置、并且标出当前项。

这里钉住的都是容易在后续改动中悄悄坏掉、而且坏了没人会立刻发现的事：

1. 当前项必须**恰好一个**，而且必须是这一页。少一个，用户不知道自己在哪；多一个，
   更糟——两个高亮意味着导航在说谎。
2. 当前项写在 HTML 里，不由脚本赋值。CSP 禁内联脚本；而且脚本赋值的高亮会在首帧
   闪错一次，脚本挂了就一直错。
3. 每个标签必须有文字。纯图标标签对读屏软件和对老人都是无名的。
4. 老人端**故意没有**标签栏：那是一整屏的对话，底部是输入框；标签栏既会挤掉发送
   按钮，也会邀请一位 78 岁的用户离开唯一为她做的那一屏。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")

# (页面文件, 该页在标签栏里应当高亮的 href)
PAGES = [
    ("index.html", "/"),
    ("family.html", "/family"),
    ("care.html", "/care"),
    ("trust.html", "/trust"),
    ("judge.html", "/judge"),
]
EXPECTED_HREFS = ["/", "/family", "/care", "/trust", "/judge"]


def bar(page: str) -> str:
    html = (STATIC / page).read_text(encoding="utf-8")
    match = re.search(r'<nav class="tabbar".*?</nav>', html, re.S)
    assert match, f"{page} 没有底部标签栏"
    return match.group(0)


@pytest.mark.parametrize("page,_", PAGES)
def test_every_console_page_has_the_bar(page: str, _: str):
    assert bar(page)


@pytest.mark.parametrize("page,_", PAGES)
def test_the_bar_is_a_labelled_landmark(page: str, _: str):
    assert 'aria-label="主要分区"' in bar(page), "标签栏应是一个有名字的导航地标"


@pytest.mark.parametrize("page,_", PAGES)
def test_the_same_five_destinations_in_the_same_order(page: str, _: str):
    hrefs = re.findall(r'<a href="([^"]+)"', bar(page))
    assert hrefs == EXPECTED_HREFS, (
        f"{page} 的标签顺序或数量不对：{hrefs}。顺序在每一页都必须一致——"
        "位置就是肌肉记忆，换一页挪一格就等于没有导航"
    )


@pytest.mark.parametrize("page,expected", PAGES)
def test_exactly_one_tab_is_current_and_it_is_this_page(page: str, expected: str):
    markup = bar(page)
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', markup)
    assert len(current) == 1, f"{page} 有 {len(current)} 个当前项，必须恰好 1 个：{current}"
    assert current[0] == expected, f"{page} 高亮的是 {current[0]}，应该是 {expected}"


@pytest.mark.parametrize("page,expected", PAGES)
def test_the_visual_and_the_accessible_current_state_agree(page: str, expected: str):
    """`.is-current` 负责画，`aria-current` 负责读，两者必须指同一个标签。

    分开写就迟早会分开坏：一个改了另一个没改，读屏用户和视觉用户会看到不同的答案。
    """
    markup = bar(page)
    painted = re.findall(r'<a href="([^"]+)"[^>]*class="[^"]*is-current', markup)
    announced = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', markup)
    assert painted == announced == [expected], (
        f"{page}: 画出来的是 {painted}，读出来的是 {announced}"
    )


@pytest.mark.parametrize("page,_", PAGES)
def test_no_tab_is_icon_only(page: str, _: str):
    markup = bar(page)
    for anchor in re.findall(r"<a href=.*?</a>", markup, re.S):
        label = re.search(r"<span>([^<]+)</span>", anchor)
        assert label and label.group(1).strip(), f"{page} 有一个只有图标、没有文字的标签"
        assert "<svg" in anchor, f"{page} 的标签「{label.group(1)}」缺图标"


@pytest.mark.parametrize("page,_", PAGES)
def test_tab_icons_are_decorative_not_announced(page: str, _: str):
    """文字才是标签的名字；读屏软件再念一遍图形是纯噪音。"""
    for svg in re.findall(r"<svg[^>]*>", bar(page)):
        assert 'aria-hidden="true"' in svg, "标签栏里的图标必须 aria-hidden"


def test_the_conversation_screen_has_no_tab_bar():
    html = (STATIC / "elder.html").read_text(encoding="utf-8")
    assert 'class="tabbar"' not in html, (
        "老人端是一整屏对话，底部是输入框；标签栏会挤掉发送按钮，"
        "也会把唯一为这位用户做的那一屏变成一个可以走开的地方"
    )


# --- 样式侧的三个约束 -----------------------------------------------------


def test_the_bar_is_only_a_phone_affordance():
    wide = CSS[CSS.index("@media (min-width: 761px) {") :]
    wide = wide[: wide.index("\n}")]
    assert ".tabbar" in wide and "display: none" in wide, "宽屏不该出现拇指栏"


def test_the_bar_clears_the_home_gesture_area():
    block = CSS[CSS.index("  .tabbar {") :]
    rule = block[: block.index("}")]
    assert "env(safe-area-inset-bottom)" in rule, "标签栏必须避开 home 指示条"
    assert "position: fixed" in rule and "bottom: 0" in rule


def test_the_bar_height_is_a_single_token():
    """栏高和"给栏让出的留白"必须引用同一个值。

    这两个数字上一次各写各的时候，结果是一屏内容底部被裁掉 100px。
    """
    assert "--tabbar-h:" in CSS, "栏高应当是一个令牌"
    assert CSS.count("var(--tabbar-h)") >= 2, "栏高和让位留白都必须引用这个令牌"


def test_the_current_tab_is_not_signalled_by_colour_alone():
    """色觉障碍和单色屏下，只靠颜色的状态就是没有状态。"""
    assert ".tab.is-current::before" in CSS, "当前项需要一个非颜色的标记（指示条）"
    assert re.search(r"\.tab\.is-current svg \{[^}]*stroke-width", CSS), (
        "当前项的图标应当同时变粗，作为第三条通道"
    )
