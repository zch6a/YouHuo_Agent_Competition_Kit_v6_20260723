"""入口页上的四个设计对照入口：在、指对地方、够得着、而且没顶掉身份卡。

## 为什么单独一条

老人端和家人端各有两套界面，首页要能直接进到其中任意一套对着看。这四条链接
是那件事在产品里唯一的痕迹——没有它们，两套设计仍然都在服务器上跑着，但从
入口页走不过去，而**「走不过去」在任何现有闸门里都是绿的**：

  * `test_tabbar.test_the_landing_page_has_no_tab_bar` 只查 `/elder` `/family`
    `/judge` 三个 href 在不在，这四条一条不在它眼里；
  * 控件清单会照实记下「index.html 从 8 个控件变回 4 个」，然后
    `test_control_inventory_is_the_fact_source` 只要求清单**新鲜**，不要求它
    不变小——重新生成一次，删除就被记录成了事实；
  * 对比度、溢出、可达性三道闸门量的都是「屏幕上有的东西对不对」，
    一个不存在的入口不占像素，它们一律报绿。

## 这份文件守的四件事

1. 四条都在，href 与名字都对；
2. 它们排在身份卡**之后**——这既是版面决定（入口页的主问题是「今天您是谁」），
   也是控件清单的依赖：清单按文档顺序给重复的 `href=` 编号，排到前面会把
   身份卡的稳定身份从 `href=/elder` 挤成 `href=/elder#2`；
3. 它们**不是桌面专属**。`/stage` `/judge` 那两道门套着 `.landing-wide`
   （≥761px 才显示），理由是那两页在窄屏上没有意义；而这四套本身就是手机界面，
   在 320px 上把它们藏起来，等于在最需要对比的那块屏幕上没有入口；
4. 命中区够得着：`<a>` 默认是行内元素，`min-height` 对它无效——本项目在这一条上
   栽过四次，所以这里查的是「它先变成了 flex/grid 容器」，不只是「写了 min-height」。

真浏览器里的几何与点击由 CDP 单独量过（七个视口 × 明暗两套，四条最小 240×79，
命中测试全部落在链接自己身上）。这里只钉住静态部分——那部分才是会被下一次编辑
悄悄改坏的部分。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: 期望的四条：`(id, href, 屏幕上的名字)`。顺序就是它们该有的排列顺序。
#:
#: 这里钉的是「链接指向那个地址」，**不是**「那个地址返回 200」。
#:
#: 路由存不存在是 `youhuo/surfaces.py` 的事，`test_surface_registry` 已经逐条对过
#: 登记表与实际路由。在这里再查一遍 HTTP 状态，只会让这条判据在另一个 agent 正在
#: 建那一页的中途报红，而报的不是入口页的问题。两条判据各守一半，接缝在登记表上。
EXPECTED = [
    ("designElderOne", "/elder", "老人端设计一"),
    ("designElderTwo", "/elder2", "老人端设计二"),
    ("designFamilyOne", "/family", "家人端设计一"),
    ("designFamilyTwo", "/family2", "家人端设计二"),
]


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _css() -> str:
    return (STATIC / "landing.css").read_text(encoding="utf-8")


def _section() -> str:
    """`.yh-designs` 那一段，注释已剥。

    **必须先剥注释**：这一节上面那段说明里逐字写着 `href=/elder`、`/elder2`，
    不剥的话「链接还在不在」这件事会被它自己的说明文档回答成「在」。
    这个项目已经有三条断言栽在「命中了我自己的注释」上。
    """
    html = re.sub(r"<!--.*?-->", " ", _html(), flags=re.S)
    hit = re.search(r'<section class="yh-designs".*?</section>', html, re.S)
    assert hit, (
        "index.html 里找不到 `.yh-designs` 这一节——要么四个设计入口被整段删了，"
        "要么它换了写法。前者是产品问题，后者要改这条判据。"
    )
    return hit.group(0)


def _rule(selector: str) -> str:
    """landing.css 里某条规则的花括号内容。"""
    css = re.sub(r"/\*.*?\*/", " ", _css(), flags=re.S)
    hit = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert hit, f"landing.css 里找不到 `{selector}` 这条规则"
    return hit.group(1)


def test_the_scan_actually_found_the_section() -> None:
    """先证明这条判据看得见东西。

    下面每一条都在断言「某样东西在」。如果 `_section()` 因为写法变了而返回一段
    空白，它们会一起报红——那是好的。但如果它返回的是**整个文件**（正则写松了），
    它们会一起报绿，而绿的原因是判据没在缩小范围。所以这里两头都钉。
    """
    section = _section()
    assert 500 < len(section) < 4000, (
        f"`.yh-designs` 抽出来 {len(section)} 字符——太短说明没抽到内容，"
        "太长说明正则吃过了 `</section>`，判据的范围已经不是这一节了"
    )
    assert "yh-choose" not in section, "抽出来的片段里混进了身份卡那一节，范围不对"
    assert section.count("<a ") == len(EXPECTED), (
        f"这一节里有 {section.count('<a ')} 条链接，期望 {len(EXPECTED)} 条"
    )


@pytest.mark.parametrize("el_id,href,name", EXPECTED, ids=[e[0] for e in EXPECTED])
def test_the_design_entry_is_there_and_points_where_it_says(el_id, href, name) -> None:
    """四条链接：id、href、屏幕上的名字，三样都对。

    三样一起查是有理由的。只查 href：两条设计入口和两张身份卡指向同一个地址，
    删掉「老人端设计一」不会让 `href="/elder"` 从文件里消失。只查名字：改错
    href 之后名字还在，点下去去了别处。只查 id：它不出现在屏幕上。
    """
    section = _section()
    tag = re.search(r'<a\b[^>]*\bid="%s"[^>]*>' % re.escape(el_id), section)
    assert tag, f"`.yh-designs` 里没有 #{el_id}——这一条入口没了"
    assert 'href="%s"' % href in tag.group(0), (
        f"#{el_id} 的目标不是 {href}：{tag.group(0)}"
    )
    names = re.findall(r'<span class="yh-design-name">([^<]+)</span>', section)
    assert name in names, f"屏幕上没有「{name}」这个名字，实际有：{names}"


def test_the_two_role_entries_survived() -> None:
    """加东西不许顶掉原来的东西。

    入口页的主问题是「今天您是谁」，那两张身份卡是它唯一的答案。这一条和
    `test_tabbar.test_the_landing_page_has_no_tab_bar` 有重叠，但那一条查的是
    「文件里有没有这个 href」——而现在文件里有**四个** `/elder`、`/family`
    的出现点，删掉身份卡它照样绿。这里查的是带 `.role-pick` 类的那两个。
    """
    html = re.sub(r"<!--.*?-->", " ", _html(), flags=re.S)
    picks = re.findall(r'<a\b[^>]*\bclass="[^"]*\brole-pick\b[^"]*"[^>]*>', html)
    assert len(picks) == 2, f"身份卡不是两张了，找到 {len(picks)} 张：{picks}"
    hrefs = sorted(re.search(r'href="([^"]+)"', p).group(1) for p in picks)
    assert hrefs == ["/elder", "/family"], f"身份卡指向变了：{hrefs}"


def test_the_design_entries_come_after_the_role_entries() -> None:
    """顺序不只是版面，控件清单的稳定身份依赖它。

    `build_control_inventory.py` 按文档顺序给重复的 `href=` 编号，第一个拿
    无后缀的键。身份卡是既有控件，它的键必须保持 `href=/elder`；把这一节挪到
    它前面，清单里会读成「身份卡消失了、多出一个 href=/elder#2」——一次纯粹的
    版面调整会被记录成一次控件删除。

    这四条现在各自带 `id`，所以事实上不再参与编号；这条断言守的是那件事**不要
    倒退**，以及入口页的主次顺序本身。
    """
    html = re.sub(r"<!--.*?-->", " ", _html(), flags=re.S)
    choose = html.index('<section class="yh-choose"')
    designs = html.index('<section class="yh-designs"')
    assert choose < designs, (
        "设计对照入口排到了身份卡前面。入口页只问一件事——「今天您是谁」，"
        "四个设计入口是次要层级；而且这个顺序还钉着控件清单里身份卡的稳定身份。"
    )


def test_the_design_entries_are_not_desktop_only() -> None:
    """它们必须在窄屏上也在。

    `/stage` `/judge` 那两道门套着 `.landing-wide`（`pages.css` 里 ≥761px 才显示），
    理由写在 index.html 里：那两页在窄屏上没有意义。这四条不一样——它们通向的
    就是手机界面，而 320×568 正是这个项目唯一发现过真实布局缺陷的那一档。
    在那块屏幕上把入口藏起来，等于在最需要对比的地方没有入口。
    """
    html = re.sub(r"<!--.*?-->", " ", _html(), flags=re.S)
    # ① 结构上没被 `.landing-wide` 包住。
    for wide in re.findall(r'<div class="landing-wide">.*?</div>', html, re.S):
        assert "yh-designs" not in wide, "设计对照入口被塞进了只在桌面显示的 `.landing-wide`"
    # ② 样式上没有任何一条规则把它整段藏掉。
    #
    #    判据不能只找 `display: none`：`visibility: hidden` 和把高度压成 0 是同样
    #    的效果。但那两种在这一层里没有先例，写进来只会让判据看起来更全面而不更严。
    #    这里只挡最可能出现的那一种——「照着 .landing-wide 抄一条媒体查询」。
    css = re.sub(r"/\*.*?\*/", " ", _css(), flags=re.S)
    for selector, body in re.findall(r"([^\n{}]*?)\s*\{([^{}]*)\}", css):
        if "yh-design" not in selector:
            continue
        assert not re.search(r"display\s*:\s*none", body), (
            f"landing.css 的 `{selector.strip()}` 把设计入口藏起来了：{body.strip()[:60]}"
        )


#: 令牌名 → 像素值。只收这一条判据要用到的两个，从 tokens.css 里读，不抄死。
def _tap_tokens() -> dict[str, int]:
    tokens = re.sub(r"/\*.*?\*/", " ", (STATIC / "tokens.css").read_text(encoding="utf-8"),
                    flags=re.S)
    out = {}
    for name in ("--tap", "--tap-key"):
        hit = re.search(re.escape(name) + r"\s*:\s*(\d+)px", tokens)
        assert hit, f"tokens.css 里没有 {name} 了——这条判据失去依据，先修判据"
        out[name] = int(hit.group(1))
    return out


def test_each_design_entry_can_actually_be_48px_tall() -> None:
    """`min-height` 对行内元素无效——这是本项目栽过四次的那一条。

    `<a>` 默认 `display: inline`，那种盒子的高度完全由行盒决定，`min-height`
    整条被忽略。也就是说「写了 min-height: 56px」和「命中区有 56px」是两件事，
    而只查前者的判据会在下一次有人把 `display: flex` 删掉时继续报绿。

    所以两件事一起查：先是块级/弹性盒（`min-height` 才有意义），然后那个值
    ≥48px（触控下限，比 Apple 的 44 高，理由是目标用户手抖）。
    """
    body = _rule(".yh-design-link")
    display = re.search(r"(?<![-\w])display\s*:\s*([\w-]+)", body)
    assert display, "`.yh-design-link` 没有声明 display——它还是行内元素，min-height 无效"
    assert display.group(1) in ("flex", "inline-flex", "grid", "inline-grid", "block"), (
        f"`.yh-design-link` 的 display 是 {display.group(1)}，"
        "行内元素上 min-height 会被整条忽略"
    )

    raw = re.search(r"min-height\s*:\s*([^;]+)", body)
    assert raw, "`.yh-design-link` 没有 min-height——命中区高度只由文案长度决定"
    value = raw.group(1).strip()
    token = re.fullmatch(r"var\((--tap(?:-key)?)\)", value)
    px = _tap_tokens()[token.group(1)] if token else int(re.fullmatch(r"(\d+)px", value).group(1))
    assert px >= 48, f"`.yh-design-link` 的 min-height 只有 {px}px，触控下限是 48"
