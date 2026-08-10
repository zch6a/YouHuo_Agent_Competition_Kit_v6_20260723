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

from .helpers import read_stylesheet

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
CSS = read_stylesheet()

# (页面文件, 该页在标签栏里应当高亮的 href)
#
# index.html 不在这里：它已经不是"控制台页面"，而是一张角色选择页——只问"你是老人
# 还是家人"，然后送你去对应的那一端。一张只有两个动作的选择页不需要常驻导航，给它
# 加一条反而是在说"这里还有别处可去"。它的"没有标签栏"由
# test_the_landing_page_has_no_tab_bar 单独钉住。
# trust 与 judge 也不在这里：可信实验室和评委导览是工程世界，把它们放进老人与家属
# 的动线上，和把「评委」做成一格标签是同一个错误。它们仍可直达，用返回链接回首页。
PAGES = [
    ("family.html", "/family"),
    ("care.html", "/care"),
]
EXPECTED_HREFS = ["/", "/family", "/care"]


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


def test_the_landing_page_has_no_tab_bar():
    """角色选择页只问一件事，不该有常驻导航。

    它此前是一份项目目录：六张导航卡 + 五格标签栏，而视觉权重最高的那张卡是「五分钟
    决赛导览」。一个真实用户在那一页上没有任何可以完成的事。现在它只有两个入口，给它
    一条标签栏等于在说"这里还有别处可去"——而那正是要去掉的那个信息层级。
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="tabbar"' not in html
    # 但它必须有那两个入口，否则这一页什么用也没有。
    assert 'href="/elder"' in html and 'href="/family"' in html
    # 以及评委能找到演示的那一行。
    assert 'href="/judge"' in html


def test_the_demo_entry_is_not_in_any_consumer_navigation():
    """评委演示不得出现在老人或家属的动线上。

    `/judge` 仍然可直达（评委拿到地址就能进），但它不能是消费者导航里的一格。
    """
    for page in ("index.html", "elder.html", "family.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        match = re.search(r'<nav class="tabbar".*?</nav>', html, re.S)
        if match:
            assert "/judge" not in match.group(0), f"{page} 的标签栏里还有评委入口"


def test_every_screen_has_some_way_out():
    """没有标签栏的那一屏，返回链接就不能藏。

    这条测试是被一次真实的死路换来的：底部标签栏取代了「← 返回首页」，于是
    `.back-link { display: none }` 一刀切地藏掉了所有返回链接——包括老人端，
    而老人端**故意没有**标签栏。结果是手机上那一屏没有任何出口，而落在里面的
    正是最没办法自己绕出去的那位用户。
    """
    for page in STATIC.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        if "back-link" not in html:
            continue          # 本来就没有返回链接的页面不在讨论范围
        # 隐藏规则现在锚在 body[data-nav="tabbar"] 上，而不是"不是 app-frame 的页面"。
        # 换判据是因为 trust 和 judge 退出了标签栏：按旧规则它们会既没有标签栏、
        # 返回链接又在手机上被藏掉，正好又造出一条死路——而这条测试当初就是被一条
        # 真实死路换来的。现在的规则是自洽的：**只有真的有标签栏的页面**才允许藏
        # 返回链接，因为只有它们提供了替代出口。
        if 'data-nav="tabbar"' in html:
            assert 'class="tabbar"' in html, (
                f"{page.name} 声称有标签栏（data-nav）却没有渲染它——返回链接会被藏掉"
            )
            continue
        assert 'class="tabbar"' not in html, (
            f"{page.name} 有标签栏却没标 data-nav，返回链接不会被藏，两条导航并存"
        )
    # 隐藏规则本身必须是限定过的，不能是一刀切。
    assert 'body[data-nav="tabbar"] .back-link' in CSS, (
        "返回链接的隐藏规则没有限定范围——没有标签栏的屏幕会变成死路"
    )
    assert not re.search(r"^\s*\.back-link\s*\{\s*display:\s*none", CSS, re.M), (
        "存在一条一刀切隐藏 .back-link 的规则"
    )


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
