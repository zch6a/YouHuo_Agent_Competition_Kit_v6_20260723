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
    """每个标签都要有可见文字。

    原先用 `re.findall(r"<a href=.*?</a>")` 取标签，要求 `href` **紧跟** `<a`。
    把标签写成 `<a class="tab" href="/">`（属性顺序完全合法）就一条都匹配不到，
    for 体一次都不执行——纯图标标签栏可以直接通过。所以先断言数量。
    """
    markup = bar(page)
    anchors = re.findall(r"<a\b[^>]*>.*?</a>", markup, re.S)
    assert len(anchors) == len(EXPECTED_HREFS), (
        f"{page} 只解析出 {len(anchors)} 个标签（应有 {len(EXPECTED_HREFS)} 个）"
        "——属性顺序变了吗？"
    )
    for anchor in anchors:
        label = re.search(r"<span[^>]*>([^<]+)</span>", anchor)
        assert label and label.group(1).strip(), f"{page} 有一个只有图标、没有文字的标签"
        assert "<svg" in anchor, f"{page} 的标签「{label.group(1)}」缺图标"


@pytest.mark.parametrize("page,_", PAGES)
def test_tab_icons_are_decorative_not_announced(page: str, _: str):
    """文字才是标签的名字；读屏软件再念一遍图形是纯噪音。

    这条同样可以整条空转：把 `<svg>` 全删掉（图标改成 CSS 背景），`re.findall`
    返回空列表，循环不执行。断言"至少有这么多个图标"是必需的。
    """
    svgs = re.findall(r"<svg[^>]*>", bar(page))
    assert len(svgs) == len(EXPECTED_HREFS), (
        f"{page} 的标签栏里有 {len(svgs)} 个图标，应有 {len(EXPECTED_HREFS)} 个"
    )
    for svg in svgs:
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
    checked = 0
    for page in STATIC.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        checked += 1
        # 「这一页没有返回链接」不是"不在讨论范围"，那正是这条测试要抓的事。
        #
        # 原先是 `if "back-link" not in html: continue`——把 elder.html 的返回链接整个
        # 删掉，这条测试通过。而它的 docstring 写的是"老人端**故意没有**标签栏，一刀切
        # 藏掉返回链接等于让最没办法自己绕出去的那位用户没有出口"。判据把"出口不存在"
        # 归成了"不适用"，恰好放过了它存在的唯一理由。
        #
        # 现在的规则：每一页都必须有**至少一个**离开这一页的办法——标签栏，或者返回
        # 链接。index.html 是角色选择页，它本身就是出口，两个身份入口即是。
        exits = []
        if "back-link" in html:
            exits.append("back-link")
        if 'class="tabbar"' in html:
            exits.append("tabbar")
        # 一条指向首页的链接就是出口，不管它穿什么类。
        #
        # 只认 `.back-link` 和 `.tabbar` 会把 `/stage` 判成死路——那一页的出口是
        # 「直接打开应用（不套框）→」，一个普通的 `<a href="/">`。判据挂在类名上，
        # 就会在下一个不用那两个类的页面上重演一次"没有出口"的误报；而给某一页
        # 开特例，等于把这条测试变回它最初那个"不在讨论范围就跳过"的形状。
        if re.search(r'<a[^>]*href="/"', html):
            exits.append("home-link")
        if page.name == "index.html":
            exits.append("role-chooser")     # 它自己就是首页，两个入口即出口
        assert exits, f"{page.name} 没有任何离开这一页的办法"
        if "back-link" not in html:
            continue          # 只有标签栏的页面，下面那条隐藏规则的讨论对它无意义
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
    assert checked >= 6, f"只检查了 {checked} 个页面——glob 还找得到它们吗？"
    # 隐藏规则本身必须是限定过的，不能是一刀切。
    assert 'body[data-nav="tabbar"] .back-link' in CSS, (
        "返回链接的隐藏规则没有限定范围——没有标签栏的屏幕会变成死路"
    )
    # 一刀切隐藏的形态不止一种。原正则要求 `.back-link` 后**紧跟** `{`、`display` 后
    # **没有空格**、而且只认 `display: none`。实测三条绕过：
    #   .back-link, .app-bar { display: none; }        逗号选择器
    #   .back-link { display : none; }                 冒号前有空格（合法 CSS）
    #   .back-link{visibility:hidden;position:absolute;left:-9999px}   换一种藏法
    # 现在按规则块解析：找出所有选择器里含 .back-link 且不带 [data-nav] 限定的规则，
    # 检查它有没有把元素藏起来（display/visibility/移出屏幕都算）。
    stripped = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    blanket = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", stripped):
        selector = " ".join(selector.split())
        if ".back-link" not in selector or "data-nav" in selector:
            continue
        hides = (
            re.search(r"display\s*:\s*none", body)
            or re.search(r"visibility\s*:\s*hidden", body)
            or re.search(r"(?:left|right)\s*:\s*-\d{4,}px", body)
        )
        if hides:
            blanket.append(selector)
    assert not blanket, f"这些规则一刀切地藏掉了返回链接：{blanket}"


def test_the_conversation_screen_has_no_tab_bar():
    html = (STATIC / "elder.html").read_text(encoding="utf-8")
    assert 'class="tabbar"' not in html, (
        "老人端是一整屏对话，底部是输入框；标签栏会挤掉发送按钮，"
        "也会把唯一为这位用户做的那一屏变成一个可以走开的地方"
    )


# --- 样式侧的三个约束 -----------------------------------------------------


def test_the_bar_is_only_a_phone_affordance():
    """宽屏上不该出现拇指栏。

    原判据是"这个 media 块里同时出现 `.tabbar` 和 `display: none` 两个子串"——它们
    可以在**不同的规则**里。实测反例：块内写 `.tabbar { min-width: 1200px; }` 加
    `.sheet-trigger { display: none; }`，两个子串都在，测试通过，而桌面上标签栏可见
    且宽 1200px——正好是 `shoot_pages.py` 注释里记着的那个溢出事故。
    现在要求的是 `.tabbar` **自己那条规则**里有 `display: none`。
    """
    wide = CSS[CSS.index("@media (min-width: 761px) {") :]
    wide = wide[: wide.index("\n}")]
    rules = [
        (" ".join(sel.split()), body)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", wide)
    ]
    hidden = [
        sel for sel, body in rules
        if re.search(r"(?<![-\w])\.tabbar(?![-\w])", sel)
        and re.search(r"display\s*:\s*none", body)
    ]
    assert hidden, f"宽屏不该出现拇指栏；这个块里 .tabbar 的规则是：{[s for s, _ in rules if '.tabbar' in s]}"


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
    # `count >= 2` 不够：两处都可以在别的地方。实测反例——把两处 `var(--tabbar-h)` 都
    # 挪进 `.tab`，让位留白硬写 `padding-bottom: 100px`，计数照样是 2，而那个 100px
    # 正是这条测试要防的那次"一屏内容底部被裁掉 100px"。
    # 现在分别要求：标签栏**自己**的高度用它，且**给栏让位的那条内边距**也用它。
    stripped = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    rules = [
        (" ".join(sel.split()), body)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", stripped)
    ]
    # 高度可以写在 `.tabbar` 上，也可以写在 `.tab` 上（每格撑起整条栏）——那是实现
    # 细节。真正会坏的是**这两个数字脱钩**，所以下面那条"让位留白"才是承重的断言。
    bar_height = [
        sel for sel, body in rules
        if re.search(r"(?<![-\w])\.tab(?:bar)?(?![-\w])", sel)
        and re.search(r"(?:min-)?height\s*:[^;]*var\(--tabbar-h\)", body)
    ]
    assert bar_height, "标签栏的高度没有引用 --tabbar-h"
    spacer = [
        sel for sel, body in rules
        if re.search(r"padding-bottom\s*:[^;]*var\(--tabbar-h\)", body)
    ]
    assert spacer, "给标签栏让位的那条内边距没有引用 --tabbar-h——两个数字又各写各的了"


def test_the_current_tab_is_not_signalled_by_colour_alone():
    """色觉障碍和单色屏下，只靠颜色的状态就是没有状态。

    选择器存在不等于指示条存在。实测反例：
    `.tab.is-current::before { display: none; content: ""; }` —— 子串在，指示条没了。
    所以要看那条规则的**内容**：它必须真的画出一个有尺寸的东西。
    """
    stripped = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    marker = re.search(r"\.tab\.is-current::before\s*\{([^}]*)\}", stripped)
    assert marker, "当前项需要一个非颜色的标记（指示条）"
    body = marker.group(1)
    assert not re.search(r"display\s*:\s*none", body), "指示条被 display:none 关掉了"
    assert re.search(r"(?:width|height|inset|inline-size|block-size)\s*:", body), (
        "指示条没有尺寸，画不出任何东西"
    )
    assert re.search(r"\.tab\.is-current svg \{[^}]*stroke-width", stripped), (
        "当前项的图标应当同时变粗，作为第三条通道"
    )
