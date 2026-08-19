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

渲染是不是好看、动效是不是舒服：没有仪器，得看。七个视口下打字入口够不够得到
是**运行时几何**，`test_mobile_reachability` 那一套在 `/elder` 上做同样的事；
这一页的数字由 CDP 单独量过，记在提交说明里。
"""
from __future__ import annotations

import re
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
    """JS 建出来的每一个类，这一页的样式表里都要有一条规则。

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
