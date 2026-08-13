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


def test_the_elder_tabs_never_compete_with_the_composer():
    """老人端有标签栏，但它和输入行不许同时在场。

    这条断言原先是 `assert 'class="tabbar"' not in elder.html`，理由写在里面：
    "老人端是一整屏对话，底部是输入框；标签栏会挤掉发送按钮"。那个理由当时是**对的**
    ——实测 320×568 下 `#chat` 的高度已经是 0px，再塞一条 64px 的栏，输入行会被推出屏幕。

    重构把那个前提拆掉了：首页不再是对话屏。对话与输入行搬进 Focus Mode，而
    `body[data-focus="on"]` 下标签栏是 `display: none`。两者不再争同一块地方。

    所以断言从"不许有标签栏"改成"不许同时在场"——守的还是同一件事：**输入行不能被
    挤掉**。放宽成"允许有标签栏"就把这条断言变成了空的；钉住互斥才是原来那个理由。
    """
    html = (STATIC / "elder.html").read_text(encoding="utf-8")
    assert 'class="tabbar elder-tabs"' in html, "老人端应有四个页内 Tab"
    # 输入行在 Focus Mode 里，标签栏在 Focus Mode 下必须被藏掉。
    assert re.search(
        r'body\[data-focus="on"\][^{]*\.elder-tabs[^{]*\{[^}]*display:\s*none',
        CSS, re.S,
    ) or re.search(
        r'body\[data-focus="on"\][^{]*\{[^}]*display:\s*none[^}]*\}',
        CSS,
    ), "Focus Mode 下必须隐藏标签栏，否则它又会和输入行争底部那一块"
    # 反向：输入行必须真的在 Focus Mode 那一段里，不能还留在首页。
    focus_start = html.index('class="elder-focus"')
    focus_end = html.index('data-panel="log"')
    focus_block = html[focus_start:focus_end]
    for control in ('id="text"', 'id="send"', 'id="chat"'):
        assert control in focus_block, (
            f"{control} 不在 Focus Mode 里——它留在首页就会和标签栏争底部"
        )


# --- 样式侧的三个约束 -----------------------------------------------------


def test_no_wide_viewport_rule_hides_a_shell_primary_nav():
    """宽屏下不许有任何规则把某个壳的主导航藏掉。

    ## 这条测试换过一次**政策**，不只是判据（2026-08-13）

    它原来叫 `test_the_bar_is_only_a_phone_affordance`，断言两件事：
    ① 存在一条在 ≥761px 隐藏跨页拇指栏的规则；② 那条规则藏不到老人端的页内栏。

    ①**的前提是假的**。它依赖「家人端和照护端宽屏上由 `.back-link` 顶上」，
    而实测：

        family.html   back-link **0 个**
        care.html     back-link 1 个 → /
        trust.html    back-link 1 个 → /

    所以 900×900 打开 `/family`：底部栏被藏、没有返回链接，而 manifest 是
    `display: standalone`——没有地址栏，iOS 上也没有系统返回手势。**一条真正的
    死路**，和 `pages.css` 那条注释自己描述过的那次一模一样。

    而 `test_every_screen_has_some_way_out` 没抓到它：那条判据查的是 markup 里
    有没有 `class="tabbar"`——family.html 有，于是算「有出口」。它从不问
    「这个出口在哪个宽度下可见」。

    ②**保留并放宽**。Phase C 之后家人端那条栏也是壳的主导航（今天/待办/照护/我的），
    而且是**混合**的：今天/待办/我的 走 `#hash` 页内切换，照护走 `/care` 跨文档。
    原来那个「跨页 vs 页内」的判据因此不再能把它归到任何一边。真正的判据是
    「**这条栏是不是这个壳的主导航**」——两条都是，所以两条都不该在宽屏消失。

    覆盖的性质没有减少，是加强了：从「不许藏老人端那一条」变成「不许藏任何一条」。

    ## 原判据踩过的两个坑，判法照旧保留

    ① 「块里同时出现 `.tabbar` 和 `display: none` 两个子串」——它们可以在**不同的
       规则**里。实测反例：`.tabbar { min-width: 1200px }` 加
       `.sheet-trigger { display: none }`，两个子串都在、测试通过，而桌面上标签栏
       可见且宽 1200px。所以要求的是 `.tabbar` **自己那条规则**。
    ② 只取**第一个** `@media (min-width: 761px)` 块——样式表里有多个同宽度的块，
       断言会跑到一个不管这件事的块里去。所以扫**所有**这个宽度的块。
    """
    # 去注释**必须在解析之前**。变异测试抓到过这一条：只把
    # `/* .tabbar:not(.elder-tabs) { display: none; } */` 写进注释，这条断言就红，
    # 而样式表里根本没有那条规则。而上面那段 `pages.css` 的注释**恰好**在解释
    # 为什么删掉它——不去注释的话，这条测试会被那段解释永久卡红。
    #
    # 同一个坑这个项目踩过四次以上（测试匹配到自己写的注释），同一个会话里
    # 下面那条 `test_the_bar_clears_the_home_gesture_area` 也刚补过。
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    blocks = [
        css[m.start():][: css[m.start():].index("\n}")]
        for m in re.finditer(r"@media \(min-width: 761px\) \{", css)
    ]
    assert blocks, "样式表里没有 min-width: 761px 的块"
    rules = [
        (" ".join(sel.split()), body)
        for wide in blocks
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", wide)
    ]
    # 任何一条在宽屏下把 `.tabbar` 设成 `display: none` 的规则都不许存在。
    #
    # 判据是「这条规则管不管得到某条 `.tabbar`」，不是「选择器里有没有 elder-tabs
    # 这几个字」。所以 `.tabbar:not(.elder-tabs)` 也算——它正是那条造成 `/family`
    # 死路的规则，字面上含有 `elder-tabs` 却恰恰藏掉了另一条主导航。
    hides = [
        sel for sel, body in rules
        if re.search(r"(?<![-\w])\.tabbar(?![-\w])", sel)
        and re.search(r"display\s*:\s*none", body)
    ]
    assert not hides, (
        f"这些规则在 ≥761px 下把标签栏藏掉了：{hides}\n"
        "  Phase C 之后两个壳的 `.tabbar` 都是**主导航**：老人端四格（首页/记录/"
        "家人/我的），家人端四格（今天/待办/照护/我的）。藏掉任何一条都会让那个壳\n"
        "  在宽屏下失去导航，而 `.back-link` 顶不上——实测 family.html 的 back-link\n"
        "  是 0 个，且 manifest 是 display:standalone（无地址栏、iOS 无返回手势）。\n"
        "  宽屏上正确的做法是改形态（`position: static` 的横排），不是隐藏。"
    )
    # 反向：`.tabbar` 在这个宽度下必须**真的被改过形态**，不能什么都不做。
    # 少了这一条，把上面那条隐藏规则删掉就能变绿，而底部拇指栏会原样留在
    # 1440px 的窗口底部——那正是这条测试最初存在的理由。
    restyled = [
        sel for sel, body in rules
        if re.search(r"(?<![-\w])\.tabbar(?![-\w])", sel)
        and re.search(r"position\s*:\s*static", body)
    ]
    assert restyled, (
        "≥761px 下没有任何规则把 `.tabbar` 从固定拇指栏改成静态横排。"
        "拇指栏钉在 1440px 窗口底部是一个被搁在桌面上的手机语汇——"
        f"这些块里 .tabbar 的规则是：{[s for s, _ in rules if '.tabbar' in s]}"
    )


def test_the_bar_clears_the_home_gesture_area():
    """钉在底部那条栏必须避开 home 指示条。

    ## 判据从「字符串首次出现」改成「在它该在的 media query 里找」

    原写法是 `CSS[CSS.index("  .tabbar {"):]`——按 `.tabbar {` 在文件里**第一次
    出现**的位置取规则。它对 media query 一无所知，所以它读到哪条规则完全取决于
    两条规则在文件里的先后。

    2026-08-13 它就是这样红的：宽屏那一段的选择器从 `.elder-tabs` 放宽成 `.tabbar`
    之后，文件里第一个 `  .tabbar {` 变成了 ≥761px 那条（约 751 行，而底部钉住那条
    在 2300 行之后）。于是这条断言去一条 `position: static` 的规则里找
    `env(safe-area-inset-bottom)`，当然找不到——而被测的那件事根本没变。

    「规则的位置决定它生不生效」这件事在这个项目里咬过四次。判据必须说清它问的是
    **哪个 media query 里**的规则：底部钉住的形态住在 `max-width: 760px`。
    """
    # 去注释**必须在解析之前**。第一版没做，于是注释里的 `{` `}` 把规则正则撕碎，
    # 报出来的「选择器」里有一条是 `')` 会把目标顶到滚动容器的 顶边…`——
    # 一段中文注释被当成了选择器。
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

    # 扫**所有** `max-width: 760px` 的块，不是第一个。这个样式表里有好几个同宽度的
    # 块，而第一个里根本没有 `.tabbar`——上一版就是这样红的，和被测的事情无关。
    blocks = [
        css[m.start():][: css[m.start():].index("\n}")]
        for m in re.finditer(r"@media \(max-width: 760px\) \{", css)
    ]
    assert blocks, "样式表里没有 max-width: 760px 的块"
    rules = {
        " ".join(sel.split()): body
        for block in blocks
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block)
    }
    rule = rules.get(".tabbar")
    assert rule is not None, (
        f"`max-width: 760px` 块里没有 `.tabbar` 自己那条规则。"
        f"块里的选择器有：{sorted(rules)[:12]}"
    )
    assert "env(safe-area-inset-bottom)" in rule, (
        f"标签栏必须避开 home 指示条，而这条规则里没有 safe-area：{rule.strip()[:160]}"
    )
    assert "position: fixed" in rule and "bottom: 0" in rule, (
        f"窄屏下它必须是钉在底部的：{rule.strip()[:160]}"
    )


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
    # 第三条通道：图标同时变粗。
    #
    # 这一条原先写的是 `\.tab\.is-current svg \{[^}]*stroke-width` —— 而那正是这个
    # 函数自己的 docstring 警告的那件事：**选择器在，不等于它画得出东西**。
    # 那条断言绿了很久，期间图标一次都没有真的变粗过：`icons/tabs.svg` 的每个
    # `<symbol>` 自带 `stroke-width="1.8"`，而 `<use>` 影子树里元素**自身的表现属性**
    # 赢过从宿主继承下来的值，所以 CSS 那个 2.3 从来没有生效。
    # 实测（拿真实 sprite 光栅化）：宿主默认与宿主 2.3 的墨量都是 2698，一模一样；
    # 删掉 symbol 上的 1.8 之后才变成 3348。
    #
    # 所以判据换成缺一不可的两条：CSS 里要有加粗规则，**并且** sprite 不许自己钉死线宽。
    assert re.search(r"\.tab\.is-current\s+\.tab-icon\s*\{[^}]*stroke-width", stripped), (
        "当前项的图标应当同时变粗，作为第三条通道"
    )
    sprite = (STATIC / "icons" / "tabs.svg").read_text(encoding="utf-8")
    assert 'stroke-width="' not in sprite, (
        "tabs.svg 的 symbol 自己写了 stroke-width——它会盖掉 CSS 的加粗规则，\n"
        "  「当前 Tab 图标变粗」这条通道于是又变成死的，而上面那条断言照样绿。\n"
        "  线宽只能有一个来源：CSS。sprite 只留形状。"
    )
