"""家人端设计二（`/family2`）自己的四道闸门。

这一页有一个别的页面都没有的形状：**标记是自己的，业务逻辑是别人的**。
它加载 `family.js` / `care.js`（设计一那一份），但只引 `family-v6.css` 一张表——
设计一的样式住在四层全局表里，这一页一层都没引。

于是有一整类缺陷，现有的闸门一条都碰不到：

  * `test_app_surface_speaks_no_engineering` 只禁一张具名词表
    （audit / digest / Demo / Saga / JSON …）。屏幕上印着 `FAMILY · CARE`、
    `NEED · YOU`、`DAILY · REPORT` 这些纯装饰的英文小标题，一个都不在表里，
    闸门全绿——而一位六十岁的用户读不出 `FAMILY`，它只是噪音。
  * `test_no_undefined_custom_properties` 只读那四层（`LAYERS` 是写死的四个文件名）。
    `family-v6.css` 里那条 `height:var(--h)`——`--h` 全站没有声明过——
    从来没有被任何仪器看见过。CSS 不报错，它把整条声明**丢掉**。
  * 所有静态闸门读的都是**注水前**的 HTML。而这一页真正的样子是注水**后**的：
    实测活 DOM 里有 38 个类名在 `family-v6.css` 里一条规则都没有，
    「需要您确认」那张带朱印的卡在真数据到达之后会变成两个灰色系统按钮。
  * 而 `javascript:void(0)` 在 `script-src 'self'` 下是被 CSP 拦掉的：
    按下去不是「暂时没做」，是控制台一条违规、屏幕上什么都不发生。

四条判据都只读这一页自己的四个文件，不依赖 `family.js`——那份不归这一页管，
被别人改动时这里不该跟着变红。代价写在 `test_the_hydrated_markup_is_styled`
的注释里：它认的是一份**写死的**清单，`family.js` 新增类名时它不会自动发现。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

HTML = STATIC / "family-v6.html"
CSS = STATIC / "family-v6.css"
SHELL_JS = STATIC / "family-v6-a.js"
MASCOT_JS = STATIC / "family-v6-b.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────────
# 1. 屏幕上不许有英文
# ────────────────────────────────────────────────────────────────────────────

#: 读得出、而且换成中文反而更难认的：计量单位。别的都算噪音。
#:
#: 「大小写不敏感」不是靠 `re.I` 实现的，是靠**根本不匹配具体的词**：
#: 判据是「可见位置上出现了拉丁字母」。上一轮就是按小写搜的，
#: `FAMILY · CARE` 因此活了下来。
_UNIT_OK = {"mmhg", "mg", "g", "ml", "kpa", "kg", "cm", "mmol", "l"}
_LATIN_RUN = re.compile(r"[A-Za-z]+")


def _visible_copy() -> list[tuple[str, str]]:
    """`family-v6.html` 里会印到屏幕上的每一段字。

    标签之间的文字 + `<title>` + 那几个会被朗读或显示出来的属性。
    注释、`<script>`、`<svg>` 的内部（路径数据全是字母）都排除。
    """
    source = _read(HTML)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.S)
    source = re.sub(r"<script\b.*?</script>", " ", source, flags=re.S)
    source = re.sub(r"<svg\b.*?</svg>", " ", source, flags=re.S)
    out: list[tuple[str, str]] = []
    for match in re.finditer(r">([^<]+)<", source):
        text = match.group(1).strip()
        if text:
            out.append(("标签之间", text))
    for match in re.finditer(
        r'(?:aria-label|title|placeholder|alt)="([^"]*)"', source
    ):
        if match.group(1).strip():
            out.append(("属性", match.group(1)))
    return out


def _latin_hits(text: str) -> list[str]:
    return [w for w in _LATIN_RUN.findall(text) if w.lower() not in _UNIT_OK]


def test_no_latin_letters_in_visible_copy() -> None:
    bad: list[str] = []
    for where, text in _visible_copy():
        hits = _latin_hits(text)
        if hits:
            bad.append(f"{where}：{' '.join(text.split())[:70]}   ← {hits[:4]}")
    assert not bad, (
        f"屏幕上有 {len(bad)} 处英文：\n  " + "\n  ".join(bad)
        + "\n  界面上不许出现英文枚举值或装饰性英文小标题。"
        "一位六十岁的用户读不出 FAMILY，它只是噪音。"
    )


def test_the_css_prints_no_english_either() -> None:
    """`content:"…"` 也会印到屏幕上，而它不在 HTML 里。

    这一页用 `content` 画了七个字（朱印的「签」「信」，底栏四个字，
    「查看全部」前面的加减号）。一个只读 HTML 的扫描器看不见它们。
    """
    body = re.sub(r"/\*.*?\*/", " ", _read(CSS), flags=re.S)
    bad = [m.group(1) for m in re.finditer(r'content\s*:\s*"([^"]+)"', body)
           if _latin_hits(m.group(1))]
    assert not bad, f"CSS 的 content 里有英文会印到屏幕上：{bad}"


def test_the_dock_glyphs_say_the_same_thing_as_the_tab_labels() -> None:
    """底栏那四个大字画在 CSS 的 `content` 里，四个分区名写在 HTML 里。

    两处必须说同一件事，而没有任何东西在核对——四个字只存在于 CSS，所有读 HTML
    的闸门对它们是全盲的，连上一条「CSS 不许印英文」也只管拉丁字母。

    真出过错：这张表里原先另有一套从老人端抄来的 `.dock button:nth-child(n)`，
    写的是「今 记 亲 我」。分区是「今天 待办 照护 我的」，第二、三个字都不对。
    它没显示出来，只因为另一套同名规则排在后面、同特异度后写覆盖先写——
    也就是说它离显示出来只差「有人删掉了后面那四行」。

    判据不要求「只许声明一次」（媒体查询里改一次是合理的），要求的是
    **所有声明同一个位置的规则必须给出同一个字，而那个字要出自这一格的分区名**。
    无论哪一条规则最终生效，屏幕都是对的。

    判据是「取自分区名」，不是「分区名的头一个字」——后者是我第一版写的，
    它自己当场就红了：四个字是「今 办 护 我」，而分区名是「今天 待办 照护 我的」，
    「办」「护」都是第二个字。两侧都量过才定的这条线：
      * 最宽的**该过**：办∈待办、护∈照护、今∈今天、我∈我的
      * 最窄的**该拦**：记∉待办、亲∉照护 —— 正是真出过的那两个错字
    """
    html = _read(HTML)
    nav = re.search(r'<nav[^>]*\bclass="[^"]*\bfamily-tabs\b[^"]*"[^>]*>(.*?)</nav>',
                    html, re.S)
    assert nav, "找不到底栏 `<nav class=\"dock family-tabs\">`"
    labels = [re.findall(r"<span[^>]*>([^<]*)</span>", button)[-1].strip()
              for button in re.findall(r"<button\b.*?</button>", nav.group(1), re.S)]
    assert len(labels) == 4 and all(labels), f"底栏读出来的分区名不对：{labels}"

    body = re.sub(r"/\*.*?\*/", " ", _read(CSS), flags=re.S)
    declared: dict[int, set[str]] = {}
    for match in re.finditer(
        r"([^{}]*button:nth-child\((\d)\)[^{}]*\.nav-icon::before)\s*\{"
        r'\s*content\s*:\s*"([^"]*)"',
        body,
    ):
        declared.setdefault(int(match.group(2)), set()).add(match.group(3))

    assert sorted(declared) == [1, 2, 3, 4], (
        f"只解析到底栏第 {sorted(declared)} 个位置的字形——正则跟这张表对不上了，"
        "而一条什么都没读到的判据是恒绿的"
    )
    wrong = []
    for n, glyphs in sorted(declared.items()):
        label = labels[n - 1]
        if len(glyphs) > 1:
            wrong.append(f"第 {n} 格「{label}」被声明成了好几个字：{sorted(glyphs)}")
            continue
        glyph = next(iter(glyphs))
        if glyph not in label:
            wrong.append(f"第 {n} 格是「{label}」，CSS 画的却是「{glyph}」")
    assert not wrong, (
        "底栏的字和分区名对不上：\n  " + "\n  ".join(wrong)
        + "\n  那四个字取自分区名，而它们只活在 CSS 的 content 里——"
        "读 HTML 的闸门一条都看不见。"
    )
    # 自证：这条判据认得出真出过的那两个错字，也不会误伤现在这四个。
    assert "记" not in "待办" and "亲" not in "照护"
    assert "办" in "待办" and "护" in "照护"


def test_the_english_scan_reads_real_copy_and_catches_a_plant() -> None:
    """自证。

    一个「跑了但一个字都没读到」的扫描器和没有这个扫描器是一回事，
    而它在结果里一样地绿。这个项目为这个形状付过多次代价。
    """
    copy = _visible_copy()
    assert len(copy) > 60, f"只读到 {len(copy)} 段可见文案，扫描器大概没在工作"
    joined = " ".join(t for _, t in copy)
    for anchor in ("需要您确认", "待办与提醒", "照护中心", "我的与可信记录"):
        assert anchor in joined, f"扫描器没读到「{anchor}」，选择器不对"
    # 认得出它要找的东西——大写、小写、混写都算。
    assert _latin_hits("FAMILY · CARE")
    assert _latin_hits("family · care")
    assert _latin_hits("Daily Report")
    # 而这些不该被抓到：
    assert not _latin_hits("128 / 78 mmHg")
    assert not _latin_hits("氨氯地平 5mg · 1片")


# ────────────────────────────────────────────────────────────────────────────
# 2. 标题
# ────────────────────────────────────────────────────────────────────────────

def test_the_title_is_a_product_name() -> None:
    """`<title>` 是这一页在标签栏、书签和主屏图标上的名字。

    上线时它写的是「优活 · 四屏 V6.0 老人端同源风格预览」：带版本号、带
    「预览」，而且说的是**老人端**——这是家人端。三样都是内部说法漏到了外面。
    """
    match = re.search(r"<title>([^<]*)</title>", _read(HTML))
    assert match, "没有 <title>"
    title = match.group(1).strip()
    assert title, "<title> 是空的"
    assert not _latin_hits(title), f"标题里有英文：{title!r}"
    for word in ("预览", "老人端", "同源", "风格"):
        assert word not in title, f"标题里不该出现「{word}」：{title!r}"
    assert not re.search(r"[Vv]?\d+\.\d+", title), f"标题里带版本号：{title!r}"
    assert "家人" in title, f"标题要说清这是哪一端：{title!r}"


# ────────────────────────────────────────────────────────────────────────────
# 3. 这张表自己的 var() 都要有声明
# ────────────────────────────────────────────────────────────────────────────

def test_every_var_reference_in_this_sheet_resolves() -> None:
    """`test_no_undefined_custom_properties` 的 `LAYERS` 是写死的四个文件名，
    这一页的样式表不在里面——所以那条闸门看不见这里。

    `height:var(--h)` 就是这么活下来的：`--h` 从来没有被声明过，
    那条 `height` 在计算值阶段整条失效，而 CSS 一声不吭。
    """
    body = re.sub(r"/\*.*?\*/", " ", _read(CSS), flags=re.S)
    declared = set(re.findall(r"(--[\w-]+)\s*:", body))
    used = set(re.findall(r"var\(\s*(--[\w-]+)\s*[,)]", body))
    # 这张表只引用三个令牌（`--ink` / `--kai` / `--sans`），颜色全是字面量。
    # 门槛就照实际写：定得比实际高，闸门会在「一切正常」的时候变红；
    # 定成 0，它就退化成一条永远绿的断言。真正的自证在下一条里种。
    assert len(declared) >= 10, f"只读到 {len(declared)} 个声明，扫描器大概没在工作"
    assert used, "一处 var() 都没读到，扫描器大概没在工作"
    missing = sorted(used - declared)
    assert not missing, (
        f"这些自定义属性被引用但没有声明：{missing}\n"
        "  CSS 不报错——它把整条声明丢掉，所以这类错误只能靠看截图或这条断言发现。"
    )


def test_the_var_scan_catches_a_planted_undefined_token() -> None:
    """自证：把当初那一条种回去，判据必须当场变红。

    `--h` 是真的在这张表里活过的：`.care-chart i{…;height:var(--h)}`。
    """
    planted = _read(CSS) + "\n.planted{height:var(--h)}\n"
    declared = set(re.findall(r"(--[\w-]+)\s*:", planted))
    used = set(re.findall(r"var\(\s*(--[\w-]+)\s*[,)]", planted))
    assert "--h" in used - declared, "种进去的坏引用没被抓到，正则不对"
    # 带兜底的不算问题——它明确说了「没有就用这个」。
    assert not re.findall(r"var\(\s*(--[\w-]+)\s*\)", "var(--stage-top-h, 0px)")


# ────────────────────────────────────────────────────────────────────────────
# 4. 注水之后的标记也要有样式
# ────────────────────────────────────────────────────────────────────────────

#: `family.js` / `care.js` 会写进这一页的类名，按结构分。
#:
#: 为什么写死而不从 `family.js` 里推：那份文件是设计一的，不归这一页管。
#: 从它身上推会让「别人改了他们自己的文件」变成「我这一页红了」。
#: 代价说清楚：`family.js` 新增一个类名时，这条闸门不会自动发现——
#: 发现它的办法是打开 `/family2` 看一眼，那本来就是唯一可靠的办法。
#:
#: 这份清单来自一次真实测量：注水后的活 DOM 里，38 个类名在这张表里
#: 一条规则都没有。下面是其中会影响**版面**的那些（纯配色的语气类不列）。
HYDRATED_CLASSES = [
    # 需要您确认 / 其他正在办的事
    "task", "status-chip",
    # 待办日历
    "calendar-day", "calendar-entry",
    # 可信记录
    "audit-row", "audit-what",
    # 生活日报
    "report-section", "report-more", "pill",
    # 照护结论
    "report-verdict", "report-badge",
    # 照护各分区
    "care-block", "care-block-head", "care-lines", "care-item", "care-item-head",
    "care-actions", "care-form", "care-field", "care-period",
    "digest", "digest-row",
    # 提示条：`notify()` 把 `notice-line` 整个换成 `notice`
    "notice", "meta",
]

#: 静态标记里就有、但同样一条规则都没有过的。`back-link` 是这一页唯一的退出口，
#: 上线时它是浏览器默认的蓝色下划线，21px 高，压在圆角机身最上沿。
STATIC_CLASSES = ["back-link", "metric-row-one"]


def _rules() -> list[tuple[str, str]]:
    """(选择器, 声明块)。只看选择器里的类名，不看声明块——
    否则 `background:...` 里的词会被当成类名。"""
    body = re.sub(r"/\*.*?\*/", " ", _read(CSS), flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body)]


def _styled_class_names() -> set[str]:
    return {c for sel, _ in _rules() for c in re.findall(r"\.([A-Za-z][\w-]*)", sel)}


def _has_a_base_rule(cls: str) -> bool:
    """这个类名有没有一条**基础**规则——不是只在伪类里出现。

    变异测试抓出来的漏洞：把 `.back-link{…}` 改名之后，
    `.back-link:hover{color:…}` 还在，于是「这个类名出现过」依然成立，
    而元素在默认状态下是彻底没有样式的（浏览器默认的蓝色下划线）。
    判据因此改成：至少有一条规则里，这个类名后面**不是**冒号，
    而且那条规则真的有声明。
    """
    bare = re.compile(rf"\.{re.escape(cls)}(?![\w-])(?!\s*:)")
    return any(bare.search(sel) and decl.strip() for sel, decl in _rules())


def test_the_hydrated_markup_is_styled() -> None:
    missing = [c for c in HYDRATED_CLASSES + STATIC_CLASSES
               if not _has_a_base_rule(c)]
    assert not missing, (
        f"这些类名会出现在屏幕上，但 `family-v6.css` 里一条规则都没有：{missing}\n"
        "  这一页只引这一张表——设计一的四层全局表它一层都没引。没有规则\n"
        "  就是浏览器默认样式：16px 的段落、灰色的系统按钮，和这一页其余部分\n"
        "  完全不是一套东西。静态闸门看不见这一层，因为它们读的是注水前的 HTML。"
    )


def test_the_style_scan_can_tell_styled_from_unstyled() -> None:
    """自证：这条判据分得清「有规则」和「没规则」。"""
    styled = _styled_class_names()
    assert len(_rules()) > 150, f"只切出 {len(_rules())} 条规则，解析大概坏了"
    assert len(styled) > 60, f"只认出 {len(styled)} 个类名，选择器解析大概坏了"
    assert _has_a_base_rule("task") and _has_a_base_rule("digest-row")
    assert not _has_a_base_rule("这个类名当然不存在")
    # 只在伪类里出现不算「有样式」——变异测试就是从这里漏过去的。
    assert not _has_a_base_rule("back-link-DEAD")
    assert "这个类名当然不存在" not in styled
    assert "todo-item" not in styled, (
        "`.todo-item` 的标记已经删掉了（待办面板里那份写死的「今天」和上面\n"
        "  真日历打架）。样式还留着的话，下一个人会以为这一页还有那个列表。"
    )


# ────────────────────────────────────────────────────────────────────────────
# 5. 每个入口都得真的去得了某个地方
# ────────────────────────────────────────────────────────────────────────────

def test_no_control_leads_nowhere() -> None:
    """`javascript:void(0)` 在这个站上是**被拦下的**，不是「暂时没做」。

    响应头是 `script-src 'self'`，没有 unsafe-inline。按下去的结果是控制台
    一条 CSP 违规、屏幕上什么都不发生。「我的 · 其他」那四个入口原先全是这个。
    """
    source = _read(HTML)
    hrefs = re.findall(r'<a\b[^>]*\bhref="([^"]*)"', source)
    assert len(hrefs) >= 5, f"只读到 {len(hrefs)} 个链接，正则大概没匹配上"

    dead = [h for h in hrefs if h.strip().lower().startswith("javascript:")
            or h.strip() in ("", "#")]
    assert not dead, f"这些链接哪儿都去不了：{dead}"

    from youhuo.surfaces import SURFACES

    anchors = set(re.findall(r'\bid="([\w-]+)"', source))
    anchors |= set(re.findall(r'\bdata-panel="([\w-]+)"', source))
    for href in hrefs:
        if href.startswith("#"):
            assert href[1:] in anchors, (
                f"锚点 {href} 在这一页上没有对应的元素或分区"
            )
        elif href.startswith("/"):
            assert href in SURFACES, (
                f"{href} 不是一条真路由。SURFACES 是路由的唯一事实源。"
            )


# ────────────────────────────────────────────────────────────────────────────
# 6. 外壳不许替后端说话
# ────────────────────────────────────────────────────────────────────────────

#: 这些控件的处理器归 `family.js` / `care.js`。
#:
#: 起因是一次真实的、两边都「成功」的失败：`family-v6-a.js` 也给
#: `#reminderForm` 绑了 submit。经典脚本在解析时执行、模块脚本在解析完之后执行，
#: 所以外壳那一条**排在** `createReminder` 前面：它先 `e.target.reset()`，
#: 等真正那一条去读 `#reminderTitle.value` 时已经是空串，于是走进
#: 「事项还没填」分支，一个请求都不发。而外壳同时往 `#notices` 写了一句
#: 「已加入待办，会同步到他的手机」——在零请求的情况下印在屏幕上。
DATA_OWNED = ["reminderForm", "reminderTitle", "reminderDue", "escalation",
              "refresh", "notices", "familyNotice", "famUpdated", "chain",
              "tasks", "audit", "calendar", "dailyReport"]


def test_the_shell_script_never_touches_data_controls() -> None:
    shell = re.sub(r"^\s*//.*$", " ", _read(SHELL_JS), flags=re.M)
    shell = re.sub(r"/\*.*?\*/", " ", shell, flags=re.S)
    caught = [name for name in DATA_OWNED
              if re.search(rf"""['"#]{re.escape(name)}['"\]]""", shell)]
    assert not caught, (
        f"外壳脚本碰了这些控件：{caught}\n"
        "  它们的处理器在 family.js / care.js 里。外壳再绑一次，两个处理器会\n"
        "  按注册顺序都跑——而外壳注册在前，它对 DOM 做的任何事都发生在真正\n"
        "  那一条读取输入之前。"
    )
    # 自证：这条判据认得出它要找的东西。
    assert re.search(r"""['"#]reminderForm['"\]]""",
                     "document.getElementById('reminderForm')")
    assert re.search(r"""['"#]refresh['"\]]""", "byId('#refresh')")


def test_the_shell_still_does_its_own_job() -> None:
    """上一条只说「不许碰什么」。一条只会变绿的禁令挡不住「整个文件被删空」。

    这里查的是**绑定**，不是选择器。变异测试抓出来的漏洞：把
    `careBtns.forEach(b=>b.addEventListener('click',…))` 整行删掉之后，
    定义 `careBtns` 的那一行还在，于是「文件里有 `.care-seg button`」
    依然成立——而照护页的七个分区一个都点不动了。
    """
    shell = re.sub(r"^\s*//.*$", " ", _read(SHELL_JS), flags=re.M)
    shell = re.sub(r"/\*.*?\*/", " ", shell, flags=re.S)
    for needed in ("data-section", "care-seg", "data-care-target"):
        assert needed in shell, f"外壳脚本里找不到 {needed}——它该管的事没在管"
    #: 底栏切面板、照护二级分区、概览行跳转、锚点跟随——四件事，四个绑定。
    bindings = re.findall(r"addEventListener\(\s*['\"](\w+)", shell)
    assert bindings.count("click") >= 3, (
        f"外壳只绑了 {bindings.count('click')} 个 click。"
        "底栏、照护分区、概览行各要一个——少一个就是一整排控件点不动。"
    )
    assert "hashchange" in bindings, (
        "没有 hashchange：`#ovSafety` 这种深链只会打开照护面板，"
        "停在概览，不会切到它指的那一节。"
    )


#: 机身高 + 舞台上下内边距 ≤ 视口。两处必须一起变，所以它们共用一个令牌。
#:
#: 漂移过一次：`.preview-stage{padding:20px}` 配 `.phone{height:min(920px,100dvh)}`，
#: 于是 900px 高的桌面上机身算出 900px、连边距 940px，整页多出 40px 滚动，
#: 机身底部那圈圆角和投影被视口下沿切掉。实测 1280×900 越界 20px、1280×700 越界
#: 40px（后者是 `min-height:720px` 兜的底，那一档本来就该滚）。
#:
#: 为什么静态闸门此前碰不到：两个值各自都完全合法，错的是它们的**关系**。
#: 而 960px 以上的屏幕自然装得下——开发机上一次都看不出来。
def test_the_phone_fits_inside_its_own_stage() -> None:
    body = re.sub(r"/\*.*?\*/", " ", _read(CSS), flags=re.S)

    token = re.search(r"--stage-pad\s*:\s*(\d+)px", body)
    assert token, "`--stage-pad` 没有声明——机身和舞台又变回两个会各自漂移的字面量了"

    stage = re.search(r"\.preview-stage\s*\{([^}]*)\}", body)
    assert stage, "找不到 `.preview-stage` 规则"
    assert "var(--stage-pad)" in stage.group(1), (
        "`.preview-stage` 的 padding 没有走 `--stage-pad`：\n  "
        + " ".join(stage.group(1).split())
        + "\n  写成字面量的话，改了它而忘了改机身高度就是一道谁都看不见的溢出。"
    )

    phone = re.search(r"\.phone\s*\{([^}]*)\}", body)
    assert phone, "找不到 `.phone` 规则"
    height = re.search(r"height\s*:\s*([^;]+)", phone.group(1))
    assert height, "`.phone` 没有 height"
    expr = " ".join(height.group(1).split())
    assert "100dvh" in expr, f"`.phone` 的高度不再跟着视口走：{expr!r}"
    assert re.search(r"calc\(\s*100dvh\s*-\s*var\(--stage-pad\)\s*\*\s*2\s*\)", expr), (
        f"`.phone` 的高度上限没有减掉舞台上下两条边距：{expr!r}\n"
        "  机身高 + 上下 padding 必须装得进视口，否则整页多一道滚动条，"
        "而被切掉的正是机身底部的圆角和投影——在 960px 以上的屏幕上看不出来。"
    )


def test_no_copy_promises_something_that_never_happens() -> None:
    """这一页不许说它没做的事。

    `family-v6-a.js` 曾写着「演示版不会真的同步到设备」，而接上真接线之后
    按钮真的会同步；改完真接线之后它又反过来写「已加入待办，会同步到他的
    手机」——那一句是在**零请求**的情况下印出来的。两次都是外壳替后端
    说了话。这个产品的全部主张是「说到做到、每一步可核验」。
    """
    for path in (HTML, SHELL_JS, MASCOT_JS):
        body = _read(path)
        if path.suffix == ".js":
            body = re.sub(r"^\s*//.*$", " ", body, flags=re.M)
            body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        else:
            body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
        for word in ("演示版", "模拟", "假数据", "仅供演示", "尚未接入"):
            assert word not in body, f"{path.name} 里出现了「{word}」"
