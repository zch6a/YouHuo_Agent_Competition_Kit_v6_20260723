"""老人端设计二（`/elder2`）：它和设计一共用同一份 `elder.js`，所以契约必须对得上。

## 这道闸门守的是哪一类失败

「装进去了」和「接上了」是两件事。这一页的 markup 来自一个 `fetch × 0` 的纯 UI 包，
业务逻辑来自仓库里那份 `elder.js`——两边只要有一处对不上，屏幕上看不出任何异样：

* **少一个 id** → `elder.js` 顶层某个 `document.querySelector('#x').addEventListener`
  抛 `Cannot read properties of null`。它是 `type="module"`，一处抛，**这一页整段
  逻辑不执行**：四个面板全是空壳，而版式看起来完全正常。
* **少一条样式** → 内容真的写进去了，渲染高度是 0。`elder.js:608` 用一整段注释记着
  这个形态的一次真实事故：系统正在等老人口头确认一笔 126.50 元的付款，玻璃盒
  确认卡写进了 `#relianceHost` 的 1181 个字符，而屏幕上什么都没有。
  这一页的类名有一半是 JS 在运行时建的（`.task` / `.log-item` / `.kin-person` /
  `.bubble` / `.task-space*` / `.reliance-*` / `.detail-*`），包自带的样式表里
  **一个都没有**——它只有它自己那份静态样例的类名。

所以这里的判据都是**从 `elder.js` 自己推出来的**，不是手抄一份清单。手抄的那份
会漂：`elder.js` 加一个 id，没有任何东西提醒你回来同步，而漏掉的那个从此永远在
视野之外——「安静地少测」和「通过」在结果里长得一模一样。

## 不在这里守的

渲染是不是好看、动效是不是舒服：没有仪器，得看。

## 这一页在**每一个**运行时仪器的名单之外

验收这一页的时候查了一遍，结果是它一个都不在：

    check_page_runtime.PAGES        / /elder /family /care /trust /judge /stage
    shoot_pages.PAGES               /elder /family /care /trust /judge / /stage
    check_contrast.PAGES            / /elder /family /care /trust /judge /stage
    test_mobile_reachability.PAGES  / /elder /family /care /trust /judge
    test_pwa_shell.PAGES            index elder family care trust judge

也就是说未捕获异常、4xx/5xx、横向溢出、对比度、七视口可达、PWA 头标签——
这一整套东西对 `/elder2` 一次都没跑过。那五份名单都不属于这一轮的文件，
所以下面自己带一个浏览器，只测**静态检查结构上看不见**的那两件事：

* 打字这条退路按下去到底有没有**写请求**发出。这是这一页最重要的一条判据，
  理由是设计一装完时界面全对而打字**零请求**——是驱动才发现的，
  任何数 id、数类名的检查都会说它是好的。
* 命中区的**实际像素**。CSS 里写着 `min-height: 48px` 和"量出来有 48px"是两件事，
  这一条本仓库在 `test_landing_design_entries` 里已经写过一次。而这一页真的因此
  漏过：`.segmented button` 只写了高度，档位名一个字的那两个（「慢」「大」）
  由文字撑宽，CDP 量出来是 **37×48**，同组里两个字的档位是 55 宽——
  肉眼、截图、以及任何读 CSS 源码的断言都看不出漏的是哪两个。
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from .helpers import strip_js_comments

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

HTML = (STATIC / "elder-v6.html").read_text(encoding="utf-8")
CSS = (STATIC / "elder-v6.css").read_text(encoding="utf-8")
ELDER_JS = strip_js_comments((STATIC / "elder.js").read_text(encoding="utf-8"))

#: `elder.js` 会 import 的那三个模块也在契约里——它们往 `#relianceHost`、
#: `#taskSpace`、`#taskDetailBody` 里建节点，类名同样要有样式。
RENDER_MODULES = ("glassbox.js", "task-space.js", "task-detail.js")


def _blank_html_comments(text: str) -> str:
    """注释抹空但保留换行。

    这一页的注释里逐字引用着 `#relianceHost`、`class="tabbar"`、`data-nav="tabbar"`
    这些东西——那正是这个项目要求的注释风格（写清楚为什么这样放）。不抹掉的话，
    下面每一条「这一页不许有 X」都会在自己的解释上报红。
    这个坑本仓库踩过四次以上。
    """
    return re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


BODY = _blank_html_comments(HTML)


def _ids_elder_js_needs() -> set[str]:
    """`elder.js` 真正会去取的那些 id。从它自己身上读，不手抄。"""
    found = set(re.findall(r"""querySelector\(\s*['"]#([A-Za-z][\w-]*)['"]""", ELDER_JS))
    found |= set(re.findall(r"""getElementById\(\s*['"]([A-Za-z][\w-]*)['"]""", ELDER_JS))
    return found


def test_the_scan_found_the_contract() -> None:
    """先证明扫到了东西。

    一个"跑了但一个 id 都没找到"的检查，和没有这个检查一样绿。
    施工图数出来是 41 个；这里留一点余量，只要求它没有塌成个位数。
    """
    ids = _ids_elder_js_needs()
    assert len(ids) >= 35, f"只从 elder.js 里扫到 {len(ids)} 个 id：{sorted(ids)}"
    for anchor in ("chat", "text", "status", "mic", "relianceHost", "kinList"):
        assert anchor in ids, f"{anchor} 没被扫到——elder.js 里取元素的写法变了"


@pytest.mark.parametrize("element_id", sorted(_ids_elder_js_needs()))
def test_the_page_carries_every_id_the_shared_logic_reads(element_id: str) -> None:
    """41 个 id 一个都不能少。

    `elder.js` 是 `type="module"`，它顶层就有一批
    `document.querySelector('#x').addEventListener(...)`——少一个就是
    `Cannot read properties of null`，而 module 的一处抛出会让**整段逻辑不执行**。
    结果不是"少一个功能"，是四个面板全部只剩静态壳，而版式看起来完全正常。
    """
    assert re.search(rf'id="{re.escape(element_id)}"', BODY), (
        f"`elder.js` 会读 `#{element_id}`，而 elder-v6.html 里没有它。"
    )


def _classes_the_logic_builds() -> set[str]:
    """`elder.js` 和它三个渲染模块在**运行时**建出来的类名。

    只取**第一个**词，那是基类；后面的词是修饰符（`notice warning` 的 `warning`、
    `bubble ${who}` 的 `user`/`agent`），它们由下面 `_TONE_CLASSES` 单独点名，
    判据也不一样——修饰符要的是 `.notice.warning` 这种复合选择器，
    单独一条 `.warning` 反而说明它没和基类绑在一起。

    `${...}` 先挖掉：那是代码不是类名。挖完会剩下 `task-space-` 这种半截词
    （来自 `` `task-space task-space-${kind}` ``），按"以连字符结尾"丢掉——
    仪器自己造出来的词不能当成产品缺陷报出去。
    """
    sources = [ELDER_JS] + [
        strip_js_comments((STATIC / name).read_text(encoding="utf-8"))
        for name in RENDER_MODULES
    ]
    names: set[str] = set()
    literals: list[str] = []
    for source in sources:
        cleaned = re.sub(r"\$\{[^{}]*\}", " ", source)
        literals += re.findall(r"""className\s*=\s*[`'"]([^`'"]*)[`'"]""", cleaned)
        # `task-space.js` / `task-detail.js` 的 `el(tag, className, text)` 帮手。
        literals += re.findall(
            r"""\bel\(\s*['"][a-z0-9]+['"]\s*,\s*[`'"]([^`'"]*)[`'"]""", cleaned)
    for literal in literals:
        words = literal.split()
        if not words:
            continue
        first = words[0]
        if re.fullmatch(r"[a-z][\w-]*", first) and not first.endswith("-"):
            names.add(first)
    return names


#: 只靠类名区分状态的那几个修饰符。它们缺了不会让内容消失，但会让
#: 「办好了」和「没办成」在屏幕上长得一样——而这一页的读者是一位老人。
_TONE_CLASSES = {
    "status-chip": ("done", "confirm", "relay", "cancelled"),
    "notice": ("good", "info", "warning"),
    "detail-status": ("good", "warning", "bad"),
    "bubble": ("user", "agent"),
}


def test_the_class_scan_found_something() -> None:
    """阳性对照：真的从渲染代码里扫到了类名。"""
    built = _classes_the_logic_builds()
    assert len(built) >= 12, f"只扫到 {len(built)} 个运行时类名：{sorted(built)}"
    for anchor in ("task", "log-item", "kin-person", "bubble", "reliance-card", "task-space"):
        assert anchor in built, f"{anchor} 没被扫到——渲染代码里建节点的写法变了"


@pytest.mark.parametrize("class_name", sorted(_classes_the_logic_builds()))
def test_every_class_the_logic_builds_has_a_rule(class_name: str) -> None:
    r"""JS 建出来的每一个类，这一页的样式表里都要有一条规则。

    这一页**不引** tokens/base/components/pages 四层，所以那四层里的定义在这里
    一条都不生效。缺一条的后果不是"样式差一点"——`.task` 没有规则时那一列是一堆
    没有间距的裸文本，`.reliance-card` 没有规则时确认卡混在气泡里认不出来，
    而最坏的一种（渲染高度 0）在截图上和"后端没返回"完全一样。

    判据只在**右边**加边界（`(?![-\w])`），左边不加：`.task button.secondary` 是
    一条**管得到** `.secondary` 的规则，而左边加了边界之后它匹配不上——第一版就是
    这么把一条真实存在的规则报成缺失的。右边的边界不能少，它挡的是拿 `.task` 去
    匹配 `.task-space`。
    """
    assert re.search(rf"\.{re.escape(class_name)}(?![-\w])", CSS), (
        f"`.{class_name}` 由 JS 在运行时建出来，而 elder-v6.css 里没有它的规则。"
    )


@pytest.mark.parametrize(
    "base,tone",
    [(base, tone) for base, tones in _TONE_CLASSES.items() for tone in tones],
)
def test_the_state_modifiers_are_visible(base: str, tone: str) -> None:
    assert re.search(rf"\.{re.escape(base)}\.{re.escape(tone)}(?![-\w])", CSS), (
        f"`.{base}.{tone}` 没有样式——两种状态在屏幕上会长得一样。"
    )


# --- 结构：分区、出口、Focus Mode ---------------------------------------------


def test_the_four_panels_and_their_segments_line_up() -> None:
    """`initSections` 第一句是 `querySelectorAll('.seg')`，**没有就静默返回**。

    这个坑设计一踩过一次、家人端设计二又踩过一次：四个面板永远打不开，
    而页面本身一个错都不报。
    """
    panels = re.findall(r'data-panel="(\w+)"', BODY)
    segs = re.findall(r'class="seg[^"]*"[^>]*data-section="(\w+)"'
                      r'|data-section="(\w+)"[^>]*class="seg[^"]*"', BODY)
    seg_names = [a or b for a, b in segs]
    assert panels == ["home", "log", "kin", "me"], f"分区是 {panels}"
    assert seg_names == panels, (
        f"带 `seg` 的切换按钮是 {seg_names}，而分区是 {panels}——"
        "`initSections` 按 `.seg` 找控件，对不上的那一格永远打不开"
    )
    # 反向：Focus Mode 那一层**不许**有 data-panel，否则它会被当成第五个分区 hidden 掉。
    focus = re.search(r'<section class="focus-layer"[^>]*>', BODY)
    assert focus and "data-panel" not in focus.group(0), (
        "Focus Mode 带了 data-panel，`initSections` 会把它当成第五格轮换掉"
    )


def test_this_page_does_not_promise_a_tab_bar_it_does_not_render() -> None:
    """`data-nav="tabbar"` 是向全局样式承诺「有底部标签栏，可以藏返回链接」。

    这一页连那套样式都没引，承诺兑现不了；而 manifest 是 `display: standalone`，
    没有地址栏、iOS 上也没有系统返回手势。结果会是一个走不出去的页面。
    出口在「我的」最后一行（`#leaveApp`），和设计一同一个位置。
    """
    assert 'data-nav="tabbar"' not in BODY
    assert 'class="tabbar"' not in BODY
    assert re.search(r'<a[^>]*id="leaveApp"[^>]*href="/"', BODY), "「我的」里没有那条出口"


def test_the_frame_opt_in_stays_with_the_conversation_screen() -> None:
    """`app-frame` 是 `elder.html` 独有的定高框架开关。

    `test_mobile_reachability::test_only_the_conversation_screen_opts_into_the_frame`
    断言的是 `framed == ["elder.html"]`——这一页沾上它，那条闸门会红，
    而红的原因不是这一页坏了，是它声明了一件自己不做的事。
    """
    assert "app-frame" not in BODY


def test_the_status_channel_is_not_buried_in_focus_mode() -> None:
    """`#status` 必须在 Focus Mode **外面**。

    设计一那边用一整段注释记着为什么：保存字号、刷新记录、首页待办加载失败
    都发生在 Focus Mode 之外。把它放进 `.focus-layer`，这些操作的反馈会写进一个
    默认隐藏的节点——用户一个字也看不到，而 `setStatus()` 每次都"成功"了。

    施工图把它排在 `#focusLayer` 里。这一条是有意的偏离，理由就是上面这一段。
    """
    layer = BODY.index('id="focusLayer"')
    # Focus Mode 这一层里没有嵌套的 `<section>`，所以它后面第一个 `</section>`
    # 就是它自己的闭合。这一条要是哪天不成立，下面那个断言会**放宽**而不是报红，
    # 所以先把前提钉住。
    layer_end = BODY.index("</section>", layer)
    assert BODY.count("<section", layer, layer_end) == 0, (
        "Focus Mode 里出现了嵌套的 <section>，下面那条判据的边界算错了"
    )
    assert not (layer < BODY.index('id="status"') < layer_end), (
        "`#status` 落在 Focus Mode 里了"
    )


def test_the_glass_box_lands_where_it_can_be_seen() -> None:
    """`#relianceHost` 必须在 Focus Mode **里面**，紧跟着对话。

    反过来那一半：`elder.js:608` 记着的真实事故是确认卡渲染进了一个高度为 0 的
    节点——系统在等老人确认一笔付款，屏幕上什么都没有。这一条钉住它的位置。
    """
    layer = BODY.index('id="focusLayer"')
    assert layer < BODY.index('id="chat"') < BODY.index('id="relianceHost"'), (
        "`#relianceHost` 不在 Focus Mode 里、或者排在了对话前面"
    )


@pytest.mark.parametrize("container", [
    "kinList", "activityLog", "reminders", "chat", "taskSpace", "relianceHost",
    "taskDetailBody", "status",
])
def test_the_data_containers_ship_empty(container: str) -> None:
    """承载真数据的容器在 HTML 里必须是空的。

    带着内容发出去的容器有两种坏法：JS 没跑时它是**假数据**；JS 跑了但接口返回空
    而 `replaceChildren()` 漏调时它被留在原地。两种情况屏幕上都在说谎，
    而这个包里那些容器原本装的是「女儿 · 张敏」「17:42 晚饭已经吃过」这种编出来的行。
    """
    match = re.search(
        rf'<(\w+)[^>]*id="{container}"[^>]*>(.*?)</\1>', BODY, re.S)
    assert match, f"找不到 #{container}"
    assert not match.group(2).strip(), (
        f"#{container} 在 HTML 里不是空的：{match.group(2).strip()[:120]!r}"
    )


def test_the_kin_panel_invents_no_one() -> None:
    """包里写死了三个人（女儿张敏、儿子张伟、邻居王叔）。

    这个产品**不编人名**——`renderKin()` 那一整段注释记着为什么：唯一那个人名
    不在任何数据里，而系统自己承认这个家庭有两位家人。
    """
    for invented in ("张敏", "张伟", "王叔", "张爷爷", "张建国", "李晴"):
        assert invented not in BODY, f"这一页还写着「{invented}」"
    for name in ("张敏", "张伟", "王叔", "张爷爷", "李晴"):
        for script in ("elder-v6-a.js", "elder-v6-b.js"):
            body = strip_js_comments((STATIC / script).read_text(encoding="utf-8"))
            assert name not in body, f"{script} 里还写着「{name}」"


def test_nothing_on_this_page_claims_the_weather() -> None:
    """包里顶栏印着「周二 · 17:25 / 26℃ · 微风」——日期写死，天气这个产品没有。

    屏幕上一句与事实无关的话，比一个工程词严重：这个产品的全部主张就是
    「说到做到、每一步可核验」。现在那两行由这台设备的真实时钟渲染。
    """
    assert "℃" not in BODY and "微风" not in BODY
    assert re.search(r'id="clockDay"', BODY) and re.search(r'id="clockTime"', BODY)
    js = (STATIC / "elder-v6-a.js").read_text(encoding="utf-8")
    assert "new Date()" in js, "时钟不是从真实时间来的"


def test_no_latin_kicker_survived_the_translation() -> None:
    """包里爱用全大写英文小标题当装饰（`ELDER · CARE`、`TODAY · FLOW`）。

    `test_app_surface_speaks_no_engineering` 只禁特定几个词，抓不到这一类。
    一位六十岁的用户读不出它们，它们只是噪音。

    判据按**屏幕上看得见的文字**算：剥掉注释、脚本、SVG，再找连续的大写拉丁词。
    """
    visible = re.sub(r"<script\b.*?</script>", " ", BODY, flags=re.S | re.I)
    visible = re.sub(r"<svg\b.*?</svg>", " ", visible, flags=re.S | re.I)
    visible = re.sub(r'<p class="needs-server">.*?</p>', " ", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    shouty = [w for w in re.findall(r"\b[A-Z][A-Z0-9·-]{2,}\b", visible)]
    assert not shouty, f"屏幕上还印着英文装饰：{sorted(set(shouty))}"


# --- 「我的」那两项：唯一一处真正的结构冲突 -----------------------------------


@pytest.mark.parametrize("control", ["speechRate", "fontScale"])
def test_the_segmented_control_really_carries_a_value(control: str) -> None:
    """`elder.js` 读 `.value`，而设计二的控件是三个按钮。

    这一页的解法是：按钮组在屏幕上，值挂在旁边一个 `hidden` 的 `<select>` 上，
    两边由 `elder-v6-a.js` 双向同步。三样东西缺一样，这个设置就是个摆设——
    而"拨了不算数的开关"正是这一页删掉「听力辅助」那一行的理由。
    """
    # `\bhidden\b` 在这里是错的：`aria-hidden="true"` 里也有 `hidden`，前面是连字符
    # （非词字符），`\b` 照样成立。变异测试抓到了——把 `hidden` 属性整个删掉，
    # 这条断言仍然绿。现在要求的是一个**独立的属性**：前面不是连字符或词字符，
    # 后面直接跟空白或标签结束。
    assert re.search(rf'<select id="{control}"[^>]*(?<![-\w])hidden(?=[\s/>])', BODY), (
        f"#{control} 不是一个 hidden 的 select"
    )
    assert re.search(rf'data-mirrors="{control}"', BODY), (
        f"没有按钮组声明自己镜像 #{control}"
    )
    adapter = strip_js_comments((STATIC / "elder-v6-a.js").read_text(encoding="utf-8"))
    assert "data-mirrors" in adapter, "适配层没有接这两个控件"
    # 反向那一半：服务端存的值写回按钮组。`select.value = x` 不派发 change，
    # 所以必须有人把 setter 包起来——少了它，刷新之后高亮永远停在默认档。
    assert "defineProperty" in adapter and "HTMLSelectElement" in adapter, (
        "适配层只做了「点按钮 → 写 select」这一半。另一半（服务端的值写回高亮）"
        "没有事件可听，需要在实例上包一层 setter。"
    )


def test_the_font_size_control_is_not_a_lie() -> None:
    """「文字大小」那一行写着「屏幕上的字会变大」。

    包里的字号全是死 px，`--elder-font-scale` 不接上去，那句话就是屏幕上的假话。
    """
    assert "--elder-font-scale" in CSS
    scaled = len(re.findall(r"calc\([\d.]+px \* var\(--fs\)\)", CSS))
    assert scaled >= 40, f"只有 {scaled} 处字号跟着 `--fs` 走，这个控件基本上不起作用"


# --- 小优不许挡住那条退路 -----------------------------------------------------


def test_the_mascot_cannot_swallow_the_only_fallback_input() -> None:
    """桌宠的画布是 112×180、`pointer-events: auto`，而且它会自己走动。

    CDP 实测：320×568 与 667×375 上，`#typeInstead` 的中心点
    `elementFromPoint` 命中的是这块画布。打字是语音失败时唯一的退路，
    而它会走——同一个视口连测两次可以一次绿一次红。

    两道防线都要在：只有 CSS 那条，768px 宽下它照样能走进手机框
    （对照实测 50 次采样里 26 次压在框上）；只有 JS 那条，手机上它无处可去。
    """
    # 判据必须是「`clampX` **用了**这条线」，不是「文件里有这个词」。
    # 变异测试抓到过：把 `clampX` 的下界改回 12、`keepOutLeft` 的定义原样留着，
    # 只查名字的那一版照样绿——而桌宠已经能走进手机框了（对照实测 50/50 次压在框上）。
    mascot_js = (STATIC / "elder-v6-b.js").read_text(encoding="utf-8")
    assert re.search(
        r"function clampX\([^)]*\)\s*\{\s*return Math\.max\(\s*keepOutLeft\(\)", mascot_js
    ), "`clampX` 的下界不是禁入线——桌宠可以走到手机框上面"
    assert re.search(
        r"@media \(min-width:702px\) and \(min-height:601px\)\{\s*"
        r"\.youhuo-robot-mascot\{display:block\}", CSS,
    ), "样式表里没有「框旁边放不下它就不显示」那一条"
    assert re.search(r"\.youhuo-robot-mascot\{[^}]*display:none", CSS, re.S), (
        "桌宠的默认状态不是隐藏——那条 media query 就成了摆设"
    )


# --- 脚本装配 -----------------------------------------------------------------


def test_the_shared_logic_is_loaded_as_a_module_and_in_the_right_order() -> None:
    """顺序和 `type="module"` 都是有代价换来的。

    ① `identity.js` → `common.js` 在前：后两者提供 `window.YouHuo`。
    ② `elder.js` 必须是 module：这一页同时加载两份经典脚本，同名顶层声明撞在一起是
       `SyntaxError: Identifier 'api' has already been declared`——**整个文件不执行**。
       家人端设计二就是这么栽的，四屏里有两屏是死的。
    """
    order = re.findall(r'<script([^>]*)src="/static/([\w.-]+)"', BODY)
    names = [name for _attrs, name in order]
    for expected in ("identity.js", "common.js", "elder.js",
                     "elder-v6-a.js", "elder-v6-b.js"):
        assert expected in names, f"这一页没有加载 {expected}"
    assert names.index("identity.js") < names.index("common.js") < names.index("elder.js")
    assert names.index("elder-v6-a.js") < names.index("elder.js"), (
        "适配层要在 elder.js 之前跑：它给两个 select 包 setter，"
        "包晚了 `applyProfile()` 的第一次写入就漏掉了"
    )
    module_attrs = next(attrs for attrs, name in order if name == "elder.js")
    assert 'type="module"' in module_attrs, "`elder.js` 不是 module"
    # 包自带的那份 `script-01.js` 也调 `initSections`，两份都在就会互相盖。
    for script in ("elder-v6-a.js", "elder-v6-b.js"):
        body = strip_js_comments((STATIC / script).read_text(encoding="utf-8"))
        assert "initSections" not in body, (
            f"{script} 里还有一份分区切换——两份都在，后跑的说了算，"
            "而这正是家人端设计二栽过的第二个坑"
        )


@pytest.mark.parametrize("asset", [
    "/elder2", "/static/elder-v6.html", "/static/elder-v6.css",
    "/static/elder-v6-a.js", "/static/elder-v6-b.js",
])
def test_the_offline_shell_covers_this_page(asset: str) -> None:
    """断网时这一页要能打开。

    `test_shell_covers_every_module` 只查 `.js`；HTML 与 CSS 漏了不会有任何东西说话，
    而缺 CSS 的后果是这一页退回没有布局的裸文档流。
    """
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    block = re.search(r"const SHELL = \[(.*?)\n\];", source, re.S)
    assert block, "sw.js 里找不到 SHELL"
    assert f"'{asset}'" in block.group(1), f"{asset} 不在外壳清单里"


def test_this_page_can_actually_install_the_shell_it_is_listed_in() -> None:
    """外壳清单里写着这一页，那这一页就得**自己装得上** service worker。

    上一条只查 `sw.js` 里有没有那五个字符串，而它一直是绿的——同时
    `elder-v6.html` 里既没有 `register-sw.js`，也没有 `rel="manifest"`，
    也没有 iOS 那三行。`sw.js` 的 VERSION 是**为这一页**从 v14 升到 v15 的，
    可这一页从来不会注册任何 worker：断网时它能不能打开，取决于用户此前有没有
    先访问过 `/elder` 或首页（同源的 worker 一旦装上就接管全站）。
    第一次就直接进 `/elder2` 的人拿不到任何缓存，而清单看起来一切正常。

    「声明了」和「够得着」是两件事，这一条钉的就是那道缝。
    `test_pwa_shell` 做的是同一件事，但它的 PAGES 是六个写死的文件名，
    这一页不在里面（`family-v6.html`、`stage.html` 也不在）。
    """
    # 用 BODY（注释已抹空）而不是原文：注释掉的那一行 `<script src=…>` 在原文里
    # 仍然匹配得上，而它一个字节都不会执行。
    assert re.search(r'<script[^>]*src="/static/register-sw\.js"', BODY), (
        "这一页不注册 service worker，而它自己躺在 sw.js 的外壳清单里"
    )
    assert "viewport-fit=cover" in BODY, "缺 viewport-fit=cover，安全区内边距全部解析成 0"


def test_this_page_does_not_claim_a_home_screen_identity_it_cannot_back() -> None:
    """有 `rel="manifest"` 就得付得起可安装页面的价钱。

    这一条是装 manifest 的时候当场撞出来的，不是推想的：
    `test_theme_color_matches_the_canvas` 把「这一页有没有 `rel="manifest"`」
    当作可安装页面的判据，然后要求 `theme-color` **深浅两套**都等于
    `tokens.css` 里的 `--bg`（`#f7f6f3` / `#0f0e0c`）。

    而这一页**根本不引 tokens.css**——它的纸是 `html,body{background:#eee8dd}`，
    而且整份样式表里一条 `prefers-color-scheme` 都没有。照着 `--bg` 写能让那条
    闸门变绿，代价正好是那条闸门存在的唯一理由：状态栏和页面之间横贯屏幕的接缝。

    所以判据是**耦合**，不是"必须有 manifest"或"必须没有"：
    要么不声明可安装，要么把两套状态栏颜色配齐并与画布对上。
    下一个人往这个 `<head>` 里顺手加一行 manifest 时，红的会是这一条，
    而它会直接说出代价——而不是让人去另一个文件里读一条参数化的失败。
    """
    css = (STATIC / "elder-v6.css").read_text(encoding="utf-8")
    schemes = sorted(re.findall(
        r'name="theme-color"\s+media="\(prefers-color-scheme:\s*(\w+)\)"', BODY))
    if re.search(r'<link[^>]*rel="manifest"', BODY):
        assert schemes == ["dark", "light"], (
            "这一页声明了 `rel=\"manifest\"`，于是进了 "
            "`test_theme_color_matches_the_canvas.INSTALLABLE`，那条闸门要求深浅两套 "
            f"theme-color 都等于 tokens.css 的 `--bg`；这一页只声明了 {schemes or '（无）'}。"
            "注意它不引 tokens.css，画布是 #eee8dd——照抄 --bg 是拿一个假颜色去骗一条"
            "测真颜色的检查。要装到主屏，先让这一页真的有两套配色。"
        )
    else:
        # 没有 manifest 的那一侧也要有判据，否则这条测试在当前状态下等于空过。
        assert "prefers-color-scheme" not in css, (
            "样式表已经有深色配色了，那就该把 manifest 和两套 theme-color 一起补上"
        )
        canvas = re.search(r"html,body\{[^}]*background:(#[0-9a-fA-F]{3,8})", css)
        assert canvas, "读不出这一页的画布色，下面那条判据没有可比的真值"
        assert re.search(
            rf'<meta\s+name="theme-color"\s+content="{canvas.group(1)}"', BODY, re.I), (
            f"浏览器地址栏那一条颜色要和这一页自己的画布 `{canvas.group(1)}` 一致——"
            "判据从样式表读，不抄一个十六进制值下来，改了画布这条会跟着红"
        )
    # `color-scheme: light dark` 同理：它会让浏览器把表单控件按深色画，
    # 而这张纸永远是浅色的。这一页的 `<select>` 是设置项的值载体。
    if "prefers-color-scheme" not in css:
        assert 'name="color-scheme"' not in BODY, (
            "样式表里一条 prefers-color-scheme 都没有，却声明支持深色"
        )


# --- 命中区：唯一说实话的仪器是浏览器 -----------------------------------------

#: 这一页的**主要操作**。判据 56，不是 48。
#:
#: 名单不是拍出来的，是拿同一支探针量设计一（`/elder`）得到的：
#: `#nextOpen` 72×56、`#typeInstead` 127×56、`#kinContact` 292×56、
#: `#saveProfile` 292×56、`#taskDetailClose` 358×56、`#repeatLast`/`#stepBack` 326×56。
#: 也就是说 56 是这个产品**已经在用**的档位，不是我新立的规矩；
#: 而这一页此前整批是 48/52——两张皮在"一位手抖的老人按不按得中"这一条上
#: 不是同一个产品。
PRIMARY_CONTROLS = (
    "nextOpen", "typeInstead", "kinContact", "saveProfile",
    "taskDetailClose", "send", "focusBack", "repeatLast", "stepBack",
)

#: 触控下限。48 而不是 Apple 的 44，理由写在 `test_landing_design_entries` 里：
#: 目标用户手抖。
TOUCH_FLOOR = 48
PRIMARY_FLOOR = 56


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _chrome() -> str | None:
    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    try:
        import shoot_pages  # type: ignore

        return shoot_pages.find_chrome()
    except Exception:
        return None


#: 每个可见控件的实际盒子，外加它是不是被别的东西盖住了。
_GEOMETRY = r"""
(() => {
  const rows = [];
  document.querySelectorAll('button, a[href], input, select, [role=button]').forEach(el => {
    if (!el.checkVisibility || !el.checkVisibility()) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    rows.push({
      id: el.id || '',
      cls: String(el.className || '').split(/\s+/).slice(0, 2).join('.'),
      txt: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 14),
      w: Math.round(r.width), h: Math.round(r.height),
    });
  });
  return JSON.stringify(rows);
})()
"""


def test_typing_reaches_the_backend_and_every_hit_area_is_big_enough(tmp_path):
    """一个真浏览器，两件静态检查结构上看不见的事。

    ① **打字这条退路真的发出写请求。** 设计一装完的时候界面全对、四个面板都有
       内容、一个错都不报，而打字**零请求**——`#send` 的处理器根本没挂上。
       数 id 的检查会说它是好的（id 确实都在），数类名的检查也会说它是好的。
       只有真的敲一句话进去、看网络层，才分得出"接上了"和"画出来了"。
       设计一验过的形状是 `POST /v2/chat` + `POST /v6/interaction/plan`。

    ② **命中区的实际像素。** 见文件头。`.segmented button` 只写了 `min-height`，
       「慢」「大」两个档位由文字撑宽到 37px——比这个项目的下限还小 11px，
       而 CSS 源码里那行 `min-height:48px` 读起来完全正确。

    量的是 390×844（这个产品的主要形态是装到主屏的 PWA）。七个视口那一套是
    `test_mobile_reachability` 的形状，它的 PAGES 里没有这一页；那份名单不属于
    这一轮的文件，所以这里只钉住静态检查够不到的部分。
    """
    chrome = _chrome()
    if not chrome:
        pytest.skip("找不到 Chrome，跳过真实浏览器测量")
    try:
        import websocket  # type: ignore
    except ImportError:
        pytest.skip("缺少 websocket-client")

    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    import shoot_pages  # type: ignore

    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        "YOUHUO_DB_PATH": str(tmp_path / "elder2.db"),
        # 必须量**装着东西**的那一页。空态会掩盖布局问题——这一条是设计一那边
        # 用一次真实的红换来的（三条待办一进来，「用打字说」就被顶出第一屏）。
        "YOUHUO_SEED_BASELINE": "true",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT / "backend"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cdp_port = _free_port()
    browser_proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*",
         # 一次性 profile。复用的 profile 会带着上一轮装好的 service worker，
         # 它是 stale-while-revalidate，于是这一轮量的是**上一版**的 CSS。
         # 本仓库为这件事栽过（一个复用的 Chrome profile 让同一个探针连报三次
         # "什么都没变"）。
         f"--user-data-dir={tmp_path / 'profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 本机请求一律绕开系统代理：这台机器上 HTTP_PROXY 指向 127.0.0.1:7897，
    # 而 urllib 不理会 NO_PROXY——就绪循环会挂死，然后把账算在服务器头上。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                opener.open(base + "/health", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.skip("后端没起来")

        ws_url = None
        for _ in range(60):
            try:
                with opener.open(f"http://127.0.0.1:{cdp_port}/json/version", timeout=2) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            pytest.skip("CDP 没起来")

        # `shoot_pages.CDP.send` 的读循环把**每一条不是自己那条 id 的消息直接丢掉**。
        # 对截图无所谓，对这里是全部内容：`#send` 的处理器是同步发出
        # `POST /v2/chat` 的，那条 `Network.requestWillBeSent` 恰好在
        # `Runtime.evaluate` 还在等回包的那几毫秒里到达，于是它落进 send() 的
        # 循环里被扔掉。第一版就是这样报的"打字发送之后没有 POST /v2/chat"——
        # 而页面是好的，漏的是仪器。`check_page_runtime.CDP` 为同一件事单独写过
        # 一个会留事件的版本，这里同样只是把消息接住。
        class KeepingCDP(shoot_pages.CDP):
            def __init__(self, url: str, websocket_mod) -> None:
                super().__init__(url, websocket_mod)
                self.events: list[dict] = []

            def send(self, method: str, **params):
                self.n += 1
                self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
                while True:
                    message = json.loads(self.ws.recv())
                    if message.get("id") == self.n:
                        if "error" in message:
                            raise RuntimeError(f"{method}: {message['error']}")
                        return message.get("result", {})
                    if "method" in message:
                        self.events.append(message)

        browser = KeepingCDP(ws_url, websocket)
        target = browser.send("Target.createTarget", url="about:blank")["targetId"]
        with opener.open(f"http://127.0.0.1:{cdp_port}/json/list", timeout=5) as r:
            tabs = json.loads(r.read())
        tab = KeepingCDP(
            next(t["webSocketDebuggerUrl"] for t in tabs if t["id"] == target), websocket
        )

        seen = tab.events

        def pump(seconds: float) -> None:
            deadline = time.monotonic() + seconds
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                tab.ws.settimeout(left)
                try:
                    message = json.loads(tab.ws.recv())
                except Exception:
                    break
                if "method" in message:
                    seen.append(message)
            tab.ws.settimeout(60)

        def js(expression: str):
            reply = tab.send("Runtime.evaluate", expression=expression, returnByValue=True)
            assert "exceptionDetails" not in reply, (
                f"探针自己抛了异常，这一页没有被真的量过：{reply['exceptionDetails']}"
            )
            return reply["result"].get("value")

        failures: list[str] = []
        try:
            tab.send("Page.enable")
            tab.send("Runtime.enable")
            tab.send("Network.enable")
            tab.send("Emulation.setDeviceMetricsOverride",
                     width=390, height=844, deviceScaleFactor=1, mobile=True)
            tab.send("Page.navigate", url=base + "/elder2")
            pump(6.0)

            # 阳性对照：共用逻辑真的跑起来了。它没跑的话下面两条测的都是一个空壳，
            # 而"一个都没量到"和"全部通过"在结果里长得一样。
            orb_states = js("Object.keys(window.__voiceOrbStates || {}).length") or 0
            assert orb_states >= 10, (
                f"`elder.js` 没有把状态表挂出来（{orb_states} 态）——"
                "共用逻辑这一页上没执行，下面的判据都测不到东西"
            )

            # ── ① 打字 → 写请求 ────────────────────────────────────────────
            js("document.getElementById('typeInstead').click()")
            pump(1.5)
            assert js("document.body.dataset.focus") == "on", (
                "按了「用打字说」没有进 Focus Mode，打字这条退路进不去"
            )
            seen.clear()
            js("(() => {const t = document.getElementById('text');"
               " t.value = '帮我交水费';"
               " t.dispatchEvent(new Event('input', {bubbles: true}));"
               " document.getElementById('send').click();})()")
            pump(9.0)

            writes = [
                (e["params"]["request"]["method"], e["params"]["request"]["url"][len(base):])
                for e in seen
                if e.get("method") == "Network.requestWillBeSent"
                and e["params"]["request"].get("method", "GET") != "GET"
                and e["params"]["request"].get("url", "").startswith(base)
            ]
            if not writes:
                failures.append(
                    "打字发送之后**一个写请求都没有**——这一页只是画出来了，没有接上。"
                    "设计一装完时就是这个形状：界面全对，打字零请求。"
                )
            for verb, path in (("POST", "/v2/chat"), ("POST", "/v6/interaction/plan")):
                if not any(m == verb and p.startswith(path) for m, p in writes):
                    failures.append(f"打字发送之后没有 {verb} {path}；实际发出的是 {writes}")

            # ── ② 命中区 ──────────────────────────────────────────────────
            js("document.getElementById('focusBack').click()")
            pump(1.0)
            measured = 0
            for section in ("home", "log", "kin", "me", "__focus"):
                if section == "__focus":
                    js("document.querySelector('.seg[data-section=\"home\"]').click()")
                    pump(0.8)
                    js("document.getElementById('typeInstead').click()")
                else:
                    js(f"document.querySelector('.seg[data-section=\"{section}\"]').click()")
                pump(1.4)
                for row in json.loads(js(_GEOMETRY)):
                    measured += 1
                    where = f"#{row['id']}" if row["id"] else f"{row['cls']}「{row['txt']}」"
                    if min(row["w"], row["h"]) < TOUCH_FLOOR:
                        failures.append(
                            f"{section} 的 {where} 命中区只有 {row['w']}×{row['h']}，"
                            f"下限是 {TOUCH_FLOOR}"
                        )
                    elif row["id"] in PRIMARY_CONTROLS and min(row["w"], row["h"]) < PRIMARY_FLOOR:
                        failures.append(
                            f"{section} 的主要操作 {where} 只有 {row['w']}×{row['h']}，"
                            f"主要操作的档位是 {PRIMARY_FLOOR}（设计一那批同名控件量出来都是 56）"
                        )
            # 量到的数量本身要断言。"跑了但一个控件都没量到"和"全部通过"
            # 在结果里长得一模一样——本仓库为这句话建过好几道闸门。
            assert measured >= 40, f"只量到 {measured} 个控件，这一页不止这些"
            pressed = {c for c in PRIMARY_CONTROLS}
            reached = set(json.loads(js(
                "JSON.stringify([...document.querySelectorAll('[id]')].map(e => e.id))"
            )))
            missing = sorted(pressed - reached)
            assert not missing, f"主要操作名单里这几个在页面上根本不存在：{missing}"
        finally:
            tab.close()
            browser.send("Target.closeTarget", targetId=target)

        assert not failures, "／elder2 驱动之后：\n  " + "\n  ".join(failures)
    finally:
        for proc in (browser_proc, server):
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
