"""手机框里只有产品，手机框外才有证明。

这是这一轮重构唯一能用数字判定成败的一条判据。

现在这个前端把**整个比赛项目**塞进了手机里。实测基线（改之前）：

    elder    0
    family   1     演示×1
    care    11     演示×7、测试×2、能力矩阵×1、接口×1
    trust   14     演示×7、Saga×3、接口×2、ASR×1、OCR×1
    ─────────
    合计    26

第一版这个扫描器报的是 **42**，多出的 16 处全是它自己的假命中，三类：
`.needs-server` 里那个必须原样输入的文件名 `run_demo.ps1` 被 `Demo` 命中（而那一段
只在应用坏掉时才显示）；模板字符串里的 `${p.approval_digest}` 被 `digest` 命中（那是
代码不是字，屏幕上是「确认摘要 37a6e9eb6009…」）；以及我给 `${…}` 用的占位符本身含
中文，把 `/v6/profiles/${ELDER_ID}` 变成了"含中文的用户文案"。

三类都修在**仪器**里，不是修在产品里。仪器数的必须是用户看见的那件事。

框外三页有工程词是**对的**——那里就该讲 API、Benchmark 和评委。

一位老人打开这个 App，不该看到「演示恶意文档金额」、「加载能力矩阵」、
「Saga」、`approval_digest`。她需要看到的只有三件事：今天发生了什么、现在该做什么、
结果可信吗。剩下的复杂度由系统承担，不由她承担。

## 这条闸门怎么判

`<body data-surface>` 是分界线：

    app        elder / family / care / trust —— 手机框里的真实产品，一个禁用词都不许有
    platform   index / judge / stage         —— 手机框外的展示与工程平台，不查

只数**用户看得见的东西**：剥掉 HTML 注释、`<script>`、`<svg>`，留下标签之间的文字、
`aria-label`、`title`，外加 JS 里**含中文的字符串字面量**（那些是 `addBubble` /
`renderResult` / `setStatus` 的文案来源，会直接写到屏幕上）。

不数：id、class、注释、接口路径、变量名。那些用户看不见，而且改掉它们只会破坏 DOM
契约——`#voiceOutput` 这个 id 留着无害，「演示确认/取消冲突」这句话不行。
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

from youhuo.surfaces import SURFACES as _SURFACES

PAGES = [info.page for info in _SURFACES.values()]

#: `<script src>` 与 ES `import` 的路径，**原样**捕获，解析交给 `_resolve_script`。
#:
#: 第一版把 `/static/` 焊死在正则里、并且只允许 `[\w.-]+`（不含斜杠）。那对根目录
#: 上的老六页成立，对山水版那十个页面一条都不成立：它们躺在
#: `backend/static/app/pages/` 子目录里，写的是 `../assets/js/app.js`。
#: 于是 `app/pages/home.html` 推出来的是**空列表**——而空列表正是
#: `test_the_scan_loads_every_script_the_page_actually_loads` 的 docstring 描述的
#: 那种失败：闸门"跑了"，只扫 HTML，一个 JS 文案都不看，然后全绿。
#: 这一次它没有安静地全绿，只因为那条守卫先炸了——它就是为这一刻写的。
#:
#: 所以路径的**形状**不再由正则决定。正则只负责"这里引了一个 .js"，
#: 引的是哪个文件是 `_resolve_script` 的事——下一种写法（`./`、带 query 串、CDN）
#: 再出现时，改的是一个有名字的函数，不是一条谁也不敢碰的正则。
_SRC_RE = re.compile(r'<script\b[^>]*\bsrc="([^"\s>]+\.js)"')
_IMPORT_RE = re.compile(r"""\bfrom\s+['"]([^'"\n]+\.js)['"]""")


def _resolve_script(src: str, base: str) -> str | None:
    """把一处引用解析成 STATIC 下的相对路径（POSIX），供 `STATIC / name` 直接用。

    `base` 是**写下这处引用的那份文件**在 STATIC 下的路径。相对路径必须相对它算，
    不能相对 STATIC 根：同一串 `../assets/js/app.js`，写在
    `app/pages/home.html` 里是 `app/assets/js/app.js`，写在根目录的页面里则指向
    static 之外。基准弄错了不会报错，只会静默地少扫一个文件。

    返回 `None` = "这不是 static 里的一个文件"，直接丢掉：外链 CDN、
    `/static/` 以外的绝对路径、以及 `..` 爬出 STATIC 的路径。丢掉而不是当成一个
    不存在的文件名塞进队列，是为了让"解析失败"和"文件不存在"保持可分——后者
    是产品问题（页面引了一个不存在的脚本），前者是仪器问题。
    """
    src = src.split("?", 1)[0].split("#", 1)[0].strip()
    if not src or "://" in src or src.startswith("//"):
        return None
    if src.startswith("/static/"):
        rel = src[len("/static/"):]
    elif src.startswith("/"):
        return None
    else:
        rel = posixpath.join(posixpath.dirname(base.replace("\\", "/")), src)
    rel = posixpath.normpath(rel)
    if rel.startswith("../") or rel in ("..", ".") or posixpath.isabs(rel):
        return None
    return rel


def _declared_scripts(page: str) -> list[str]:
    """这一页 `<script src>` 里**直接写出来**的那些，已解析成 STATIC 下的路径。

    单独拆出来是给守卫断言用的：它要拿"页面声明加载了什么"去核对"清单里有什么"，
    而这两边必须是同一套写法。守卫那边自己再跑一遍裸正则的话，两种路径写法就会
    对不上，而那条断言会因为**仪器内部不一致**报红，跟产品无关。
    """
    html = (STATIC / page).read_text(encoding="utf-8")
    out: list[str] = []
    for src in _SRC_RE.findall(html):
        name = _resolve_script(src, page)
        if name and name not in out:
            out.append(name)
    return out


def _scripts_for(page: str) -> list[str]:
    """这一页**真正加载**的 JS。文案有一半在 JS 里，只扫 HTML 会漏掉一半。

    原先这里是一张手写的表，而它漏了 `common.js` —— 一个被**四个 app 页面全部加载**、
    里面装着 `FIELD_LABEL`（六十多条后端字段名到中文的翻译）和 `VERDICT` 两套
    用户可见中文的文件。也漏了 `identity.js` 和 `sheet.js`。

    手写的表会漂移：页面加一个 `<script>`，没有任何东西提醒你回来同步这张表，
    而漏掉的那个文件从此**永远**在这条闸门的视野之外——安静地少测，结果看起来和
    通过一模一样。从 HTML 自己的 `<script src>` 读就不会漂，再跟着 ES `import`
    走（`elder.js` 的 `speech.js` / `glassbox.js` 是这么进来的）。

    `import` 的基准是**那个脚本自己**，不是页面：`a/b.js` 里的 `./c.js` 是
    `a/c.js`。跟着 import 走一层就换一次基准，所以队列里存的是已经解析好的路径。
    """
    seen: list[str] = []
    queue = _declared_scripts(page)
    while queue:
        name = queue.pop(0)
        if name in seen or not (STATIC / name).is_file():
            continue
        seen.append(name)
        source = (STATIC / name).read_text(encoding="utf-8")
        for target in _IMPORT_RE.findall(source):
            resolved = _resolve_script(target, name)
            if resolved:
                queue.append(resolved)
    return seen


PAGE_SCRIPTS = {page: _scripts_for(page) for page in PAGES}

#: 大纲第一节点名的禁止项，加几个同类。
#:
#: 分两组是因为判定方式不同：ASCII 词不区分大小写地找，中文词按原样找。
BANNED_ASCII = [
    "OpenAPI", "Benchmark", "Runtime", "Monitoring", "N-best", "C4-AI",
    "Saga", "Policy", "ASR", "OCR", "Demo", "digest", "hash", "audit", "JSON",
]
#: 第二批（本轮加）是从**实际漏过去的那一批**倒推出来的一整类，不是又想到几个词。
#:
#: 这条闸门一直报 0，而屏幕上活着的是「语义层：离线确定性」和「语音：离线本地合成」
#: ——就长在老人端「我的」页那一段「优活怎么保护您」里，旁边三个兄弟写的是
#: 「一次只问一件事」「不会自动扣钱」。闸门看不见它们，只因为这几个词当初没进名单。
#:
#: 一份**从观测到的基线倒推**出来的名单只能挡住已经犯过的错。所以这一批按"这个词
#: 属于哪一侧的词汇表"来选，而不是按"我见过它泄漏"：说给写代码的人听的（语义 /
#: 后端 / 字段 / 参数 / 置信度 / 引擎 / 架构 / 协议 / 状态码）一律不进手机框。
#:
#: 刻意**不**收的两个，理由要写下来，否则下一个人会以为是漏了：
#:   - 「权限」——这是安卓和 iOS 自己的说法。老人端那句「让家人帮您在手机设置里
#:     打开麦克风权限」必须和她手机上看到的字一样，换成别的说法反而找不到。
#:   - 「授权」——「家人授权」是中文里本来就有的说法，不是行话。
BANNED_CJK = [
    "评委", "测试", "证据板", "能力矩阵", "演示", "接口", "工程", "调试", "原始响应",
    "语义", "确定性", "模型", "合成", "槽位", "部署", "架构", "算法", "缓存",
    "状态码", "协议", "后端", "前端", "日志", "字段", "参数", "置信度", "引擎",
]
#: 版本号前缀。`v4` 到 `v7` 单独处理：要避开 `v4` 出现在版本号文本里的合法情形，
#: 所以只在它后面跟斜杠或行界时算命中（`/v4/routines`、`v6 能力`）。
BANNED_VERSION = re.compile(r"\bv[4-7]\b")

#: `API` 单独一条：三个字母太短，`rapid`、`capability` 里都有。必须按词边界找。
BANNED_API = re.compile(r"\bAPIs?\b", re.I)


def _visible_text(html: str) -> str:
    """用户在屏幕上读到的那些字。

    剥的顺序有讲究：注释要先剥，否则注释里的 `<script>` 会把后面的正文一起吃掉。

    `.needs-server` 那一段也剥掉。它是**给开发者看的失败提示**，只在四个样式表
    404 时才出现（双击 HTML 打开），内容是「运行 run_demo.ps1」——里面的
    `run_demo.ps1` 是一个必须原样输入的文件名，被 `Demo` 命中过一次。
    一段只在应用坏掉时才显示的排障说明，不是产品界面。
    """
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<svg\b.*?</svg>", " ", html, flags=re.S | re.I)
    html = re.sub(r'<p class="needs-server">.*?</p>', " ", html, flags=re.S)
    labels = " ".join(re.findall(r'aria-label="([^"]*)"', html))
    titles = " ".join(re.findall(r'title="([^"]*)"', html))
    placeholders = " ".join(re.findall(r'placeholder="([^"]*)"', html))
    body = re.sub(r"<[^>]+>", " ", html)
    return f"{body} {labels} {titles} {placeholders}"


def _js_user_facing_strings(js: str) -> str:
    """JS 里会写到屏幕上的文案。

    判据是"含中文"。这个项目的界面全是中文，所以一个含中文的字符串字面量几乎一定是
    给用户看的；而纯 ASCII 的字面量是选择器、接口路径、事件名——那些不该数。

    这个判据会漏掉一种情况：纯英文的用户文案。但这个项目本来就禁止界面上出现英文枚举
    （`test_voice_orb_states` / `check_judge_story` 各守一半），所以那种字符串不该存在。

    模板字符串里的 `${…}` 要先挖掉，因为**那是代码不是字**。第一版没挖，于是
    `确认摘要 ${short(p.approval_digest)}` 被 `digest` 命中、
    `这 ${audit.events.length} 条记录` 被 `audit` 命中——一共四处 digest、三处 audit，
    而屏幕上真正出现的是「确认摘要 37a6e9eb6009…」和「这 6 条记录」，一个英文都没有。
    仪器数的必须是用户看见的那件事，不是源码里出现的字符。
    """
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    js = re.sub(r"^\s*//.*$", " ", js, flags=re.M)
    # `console.*` 的实参不是文案，是给开发者看的。
    #
    # 这一段是跟着上面那个"从 HTML 推脚本"的修复一起加的：脚本清单变全之后，
    # `speech.js` 的 `console.warn(\`离线语音在第 N 句失败，回落到浏览器语音\`)`
    # 会被当成用户文案数进来。它一个像素都不会出现在屏幕上。
    # 这份文件开头那句话对两个方向都成立——仪器数的必须是用户看见的那件事，
    # 那么用户看不见的，仪器也不该数。
    js = re.sub(r"\bconsole\.\w+\([^()]*(?:\([^()]*\)[^()]*)*\)", " ", js)
    # 占位符**不能含中文**。第一版用「〔值〕」，结果 `/v6/profiles/${ELDER_ID}` 被替换成
    # `/v6/profiles/〔值〕`，于是这条纯 ASCII 的接口路径突然"含中文"、被当成用户文案，
    # 反倒多报了六处 v4–v7。仪器自己给自己造了一批假命中。
    js = re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "@@", js)
    found: list[str] = []
    for quote in ("'", '"', "`"):
        found += re.findall(rf"{quote}([^{quote}\n]{{2,}}){quote}", js)
    return " ".join(s for s in found if re.search(r"[一-鿿]", s))


def _surface(page: str) -> str:
    html = (STATIC / page).read_text(encoding="utf-8")
    hit = re.search(r"<body[^>]*\bdata-surface=\"(\w+)\"", html)
    assert hit, f"{page} 的 <body> 没有 data-surface——分界线不存在，这条闸门无从判断"
    return hit.group(1)


def _leaks(page: str, overrides: dict[str, str] | None = None) -> dict[str, int]:
    """`overrides` 让变异测试在内存里换掉某个脚本的源码。

    第一版是真的写回磁盘再 `finally` 还原。那样一来 pytest 被 Ctrl-C 打断就会把
    源文件留在变异后的状态——一个"验证代码没坏"的测试不该有能力弄坏代码。
    """
    overrides = overrides or {}
    html = (STATIC / page).read_text(encoding="utf-8")
    text = _visible_text(html)
    for script in PAGE_SCRIPTS[page]:
        source = overrides.get(script) or (STATIC / script).read_text(encoding="utf-8")
        text += " " + _js_user_facing_strings(source)

    hits: dict[str, int] = {}
    for word in BANNED_ASCII:
        n = len(re.findall(re.escape(word), text, re.I))
        if n:
            hits[word] = n
    for word in BANNED_CJK:
        n = text.count(word)
        if n:
            hits[word] = n
    for pattern, label in ((BANNED_VERSION, "v4–v7"), (BANNED_API, "API")):
        n = len(pattern.findall(text))
        if n:
            hits[label] = n
    return hits


#: 从 `youhuo.surfaces` 推，不再手写两张名单。
#:
#: 三表面重构之后 `data-surface` 的取值从 `app|platform` 变成
#: `consumer|presentation|professional`，而 `index.html` 从 platform 挪到了 consumer
#: （它是消费者的入口，不是给评委看的展示面）。手写名单在这种改动下会**静默地**
#: 把某一页留在旧的那一组里——这份文件自己在 `:66-69` 批评过的正是这件事。
_SURFACE_OF = {info.page: info.surface for info in _SURFACES.values()}
_SHELL_OF = {info.page: info.shell for info in _SURFACES.values()}

#: 手机框里：一个禁用词都不许有。
#:
#: 判据是 **shell**，不是 surface。`index.html` 也是 `consumer`，但它的 shell 是
#: `entry`——它是门，不是 App。门可以写出它通向哪里（「演示与可信技术 →」），
#: 那不是工程词泄漏进产品，那就是边界本身。门另有一条更窄的规则，见
#: `test_the_entry_page_only_names_other_surfaces_in_the_doorway`。
#:
#: **`app` 为什么在这里面。** 山水版（`backend/static/app/`）就是老人本人打开的那个
#: App——它比 `elder` 更是"手机框里"。把它留在外面，这条闸门会在**新前端上线之后**
#: 继续报绿，而绿的原因不是它干净，是没人看过它：`app/pages/home.html` 的
#: surface 是 `consumer`（所以不在 PLATFORM_PAGES 里），shell 是 `app`（所以不在
#: APP_PAGES 里）——它会同时掉出两张名单，一个字都不被扫。
#:
#: 这正是这份文件从第一行起反复说的那件事："安静地少测和通过在结果里长得一模一样"。
#: 上一次它是 `common.js`，这一次是一整套前端。加进来立刻红了两处（见
#: `test_the_app_surface_speaks_no_engineering` 的失败信息）——那两处在屏幕上活着，
#: 而闸门此前从未看见过它们。
APP_SHELLS = {"elder", "family", "app"}
APP_PAGES = [p for p in PAGES if _SHELL_OF[p] in APP_SHELLS]
#: 手机框外：**必须**有那些词，否则这条闸门是空的。
PLATFORM_PAGES = [p for p in PAGES if _SURFACE_OF[p] != "consumer"]
#: 入口页，单独一条规则。
ENTRY_PAGES = [p for p in PAGES if _SHELL_OF[p] == "entry"]


def test_every_page_declares_which_side_of_the_frame_it_is_on():
    """七个页面必须都有 data-surface，而且三个表面都不能是空的。

    少了这个标记，下面那条断言会静默跳过那一页——而"跳过"和"通过"在结果里长得一样。

    值从 `app|platform` 换成 `consumer|presentation|professional` 之后，这里也从
    「两边」变成「三边」。`youhuo.surfaces` 是唯一事实源，
    `test_surface_registry.py` 负责钉住它和 HTML 标记一致；这里只确认三组都非空。
    """
    for page in PAGES:
        assert _surface(page) == _SURFACE_OF[page], (
            f"{page} 标的是 {_surface(page)}，而登记表说 {_SURFACE_OF[page]}"
        )
    assert APP_PAGES, "App Shell 页面一个都没有——下面那批参数化会整批消失"
    assert PLATFORM_PAGES, "手机框外一个页面都没有——反向断言会变成空的"
    assert ENTRY_PAGES, "入口页没有了？那条更窄的规则会静默跳过"


@pytest.mark.parametrize("page", ENTRY_PAGES)
def test_the_entry_page_only_names_other_surfaces_in_the_doorway(page: str) -> None:
    """入口页可以写出它通向哪里，但只能写在门里。

    `index.html` 是 `consumer` 表面、`entry` 外壳——它是门，不是 App。所以
    「演示与可信技术 →」「在电脑上演示 →」这两句不算工程词泄漏，它们**就是边界本身**：
    一扇门说出自己通向哪儿是它的职责。

    但这个豁免必须有边界，否则「入口页」会变成一个什么都能塞的口袋。判据是结构：
    那些字只许出现在 `.landing-demo` 里。那两个 `<p>` 上方的注释已经写明了理由
    （「它对老人和家属都没有意义，只有在电脑上做答辩、录屏或截图的人才需要它」），
    这条断言把那句注释变成机器守得住的东西。

    去掉 `.landing-demo` 之后**剩下的部分**必须和 App Shell 一样干净。
    """
    html = (STATIC / page).read_text(encoding="utf-8")
    doorway = re.findall(r'<p class="landing-demo">.*?</p>', html, re.S)
    assert doorway, (
        f"{page} 里没有 `.landing-demo`——要么门的写法变了，要么它真的没有通往"
        "另外两个表面的入口。前者要改这条断言，后者是产品问题。"
    )
    without_doorway = re.sub(r'<p class="landing-demo">.*?</p>', " ", html, flags=re.S)
    text = _visible_text(without_doorway)
    for script in PAGE_SCRIPTS[page]:
        text += " " + _js_user_facing_strings((STATIC / script).read_text(encoding="utf-8"))

    hits = {w: text.count(w) for w in BANNED_CJK if w in text}
    hits |= {w: n for w in BANNED_ASCII
             if (n := len(re.findall(re.escape(w), text, re.I)))}
    assert not hits, (
        f"{page} 在**门以外**的地方有工程词：{hits}\n"
        "  门（`.landing-demo`）可以点名另外两个表面，门以外的部分不行。"
    )


@pytest.mark.parametrize("page", APP_PAGES)
def test_the_app_surface_speaks_no_engineering(page: str):
    """手机框里的页面，用户看得见的地方一个禁用词都不许有。

    改之前的实测基线：elder 2、family 6、care 13、trust 21，合计 42。

    山水版（`app/pages/home.html`）是第五个进来的，它此前从未被扫过——见
    `APP_SHELLS` 上面那段。它进来的第一次运行就红了，红在 `app.js` 的两个 `toast`。
    """
    hits = _leaks(page)
    total = sum(hits.values())
    detail = "、".join(f"{w}×{n}" for w, n in sorted(hits.items(), key=lambda kv: -kv[1]))
    assert not hits, (
        f"{page} 在用户看得见的地方有 {total} 处工程词：{detail}\n"
        "  手机框里只放产品。这些内容属于 /stage 或 /judge——搬过去，不要删掉。"
    )


def test_the_scan_loads_every_script_the_page_actually_loads():
    """脚本清单必须是从 HTML 推出来的，而且必须包含那个共享文件。

    这一条守 `_scripts_for` 本身。它要是因为 `<script>` 的写法变了而匹配不到，
    返回的是空列表——于是这条闸门"跑了"，只扫 HTML，一个 JS 文案都不看，
    然后**全绿**。安静地少测和通过在结果里长得一模一样。

    `common.js` 单独点名，因为它就是原先那张手写表漏掉的那一个：四个 app 页面
    全部加载它，而它里面有 `FIELD_LABEL`（六十多条）和一句 `summary.textContent`。
    闸门补上它的第一次运行就在四个页面上各抓到 3 处——那些字在屏幕上活了很久。
    """
    for page in PAGES:
        scripts = PAGE_SCRIPTS[page]
        assert scripts, f"{page} 一个脚本都没推出来——<script src> 的正则跟 HTML 对不上了"
        for name in _declared_scripts(page):
            assert name in scripts, f"{page} 加载了 {name}，但清单里没有"

    # 两种 `src` 写法都必须真的被解析过一遍，否则上面那圈"非空"可以靠另一种写法
    # 蒙混过去：老六页全绿，而子目录里的十页各推出空列表——那正是这一条要挡的。
    assert _resolve_script("/static/common.js", "elder.html") == "common.js"
    assert _resolve_script("../assets/js/app.js", "app/pages/home.html") == (
        "app/assets/js/app.js"
    ), "子目录页面的相对路径没有解析到 static 下的真实文件"

    for page in APP_PAGES:
        # `common.js` 是**老六页那一套**的共享文件。山水版（shell `app`）是另一套
        # 前端，有它自己的 `app/assets/js/`，不加载也不该加载 common.js。
        # 判据因此按"这一页真的声明了它"来核对，而不是无条件要求每个 app 页都有——
        # 后者会在山水版身上报一条与产品无关的红。要守的东西没变：**页面加载了的
        # 共享文件，一个都不许漏出清单**，而这正是 `common.js` 当初被漏掉的那件事。
        shared = [s for s in _declared_scripts(page) if s.endswith("common.js")]
        for name in shared:
            assert name in PAGE_SCRIPTS[page], (
                f"{page} 的清单里没有 {name}。它被这一页加载，"
                "里面装着用户看得见的中文——漏掉它，这条闸门就有一整块盲区。"
            )
    assert any("common.js" in PAGE_SCRIPTS[p] for p in APP_PAGES), (
        "一个 app 页面都没扫到 common.js——它被老六页全部加载，"
        "整批消失说明清单又断了一次"
    )
    assert "speech.js" in PAGE_SCRIPTS["elder.html"], (
        "elder.js 用 ES import 引入 speech.js，跟着 import 走的那一步断了"
    )


def test_the_widened_vocabulary_catches_what_actually_shipped():
    """变异测试：把真的显示过的那两句放回去，闸门必须红。

    这两句在屏幕上活着的时候，这条闸门报的是 **0 处**——因为「语义」「确定性」
    「合成」当时都不在名单里。名单是从观测到的基线倒推的，所以它只认得已经犯过的错。

    第三条变异针对的是**另一半**盲区：把同一句话放进 `common.js`。那个文件当时
    根本不在扫描范围内，所以无论写什么词，闸门都看不见。
    """
    elder = (STATIC / "elder.js").read_text(encoding="utf-8")
    common = (STATIC / "common.js").read_text(encoding="utf-8")

    assert not _leaks("elder.html"), "基线不干净，下面的变异说明不了任何事"

    shipped = "pill.textContent = status.available ? '说话不出这台手机' : '用手机自带的声音念';"
    assert shipped in elder, "变异锚点在 elder.js 里找不到了"
    mutations = {
        "语音那一条（真的显示过的原文）": (
            "elder.js", elder.replace(
                shipped,
                "pill.textContent = status.available ? '语音：离线本地合成' : '语音：浏览器语音';",
                1)),
        "语义那一条（真的显示过的原文）": (
            "elder.js", elder.replace(shipped, shipped + "\n  pill.title = '语义层：离线确定性';", 1)),
        "同一句话搬进共享文件": (
            "common.js", common.replace(
                "    decision: '判定', reasons: '理由',",
                "    decision: '语义层判定', reasons: '理由',", 1)),
    }
    for label, (script, mutated) in mutations.items():
        source = common if script == "common.js" else elder
        assert mutated != source, f"变异 `{label}` 没打进去，锚点对不上"
        assert _leaks("elder.html", {script: mutated}), f"变异 `{label}` 没有被抓到"


def test_the_scan_actually_reads_text():
    """扫描器必须真的扫到了正文。

    一个"跑了但一个字都没读到"的检查，和没有这个检查是一回事，而它在结果里看起来
    一模一样地绿。

    判据是**每一页自己的 `<h1>` 文字必须出现在提取结果里**，而不是一个拍脑袋的字数下限。
    第一版设的是"≥80 个中文字"，而首页只有 64 个——它刻意稀疏（两个入口加一句话），
    于是一个正确的页面被判成"正则把正文剥掉了"。h1 是每一页一定有、一定可见、一定
    在 `<body>` 里的东西，用它当探针不需要猜数字。

    **两边必须用同一套空白规范。** 这里原先把标题里的标签替换成空串，而
    `_visible_text` 把标签替换成空格——`<h1>上午好，<span data-bind="profile.name">
    </span> 👋</h1>` 于是变成两个只差空格数的字符串，包含判定失败。老六页的 h1 里
    没有嵌套元素，所以这个不一致一直没显形；山水版首页进到这批里的第一次运行就撞上
    了。它是**仪器自己的假命中**，不是产品缺陷：那句标题在提取结果里好好地待着。
    判据一点没松——整句标题（含那个 emoji）仍然必须原样出现在正文里。
    """
    def collapse(s: str) -> str:
        return " ".join(s.split())

    for page in APP_PAGES + PLATFORM_PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        assert h1, f"{page} 没有 h1"
        heading = collapse(re.sub(r"<[^>]+>", " ", h1.group(1)))
        text = collapse(_visible_text(html))
        assert heading and heading in text, (
            f"{page} 的标题「{heading}」没出现在提取结果里——剥标签的正则把正文一起剥掉了"
        )


def test_the_platform_surface_is_where_the_engineering_words_live():
    """反向：框外三页必须**真的**有那些词。

    这一条防的是一种很省事的"通过"方式：把工程内容从 app 面删掉而不是搬走，于是两边
    都干净了，而产品也不再能证明自己。大纲第 46 节写得很清楚——不得 silent delete。

    所以框外必须留有痕迹。数字设得很低（≥6），因为这里要的是"存在"，不是"多少"。
    """
    total = 0
    per_page: dict[str, int] = {}
    for page in PLATFORM_PAGES:
        n = sum(_leaks(page).values())
        per_page[page] = n
        total += n
    assert total >= 6, (
        f"手机框外只找到 {total} 处工程词（{per_page}）。"
        "工程内容是被删掉了还是被搬走了？搬走才对——删掉的话产品就不能证明自己了。"
    )


# ---------------------------------------------------------------------------
# 原始标识符（运行时才出现的那一半）
#
# 上面那条闸门扫的是**源码里的字**：HTML 的可见文本，加上 JS 里含中文的字符串字面量。
# 它因此看不见一整类泄漏——**运行时从接口拼出来的标识符**。
#
# 实际发生过一次：`/family` 的任务卡底下有一行灰字，屏幕上是
# `task-cf917fee2790476500fb`。源码里那一行是 `line(div, t.id, 'meta')` ——
# 没有中文字面量，没有禁用词，一个字都不沾 `textContent`。上面那条闸门报 0 处，
# 视觉审查在截图上逐像素读出了它。
#
# 这是这一份文件开头那句话的另一半：「仪器数的必须是用户看见的那件事」。用户看见的
# 是屏幕上那串字，不是源码里出现的字符——反过来也成立，源码里干净不等于屏幕上干净。
#
# 判据因此建在**渲染点**上而不是字面量上：找到每一处"要把一段文字写到屏幕上"的写法，
# 看那段文字里有没有读一个原始标识符字段。
# ---------------------------------------------------------------------------

#: 会把一段文字写到屏幕上的写法。
#:
#: 前三条是 DOM 自己的，后三条是这个项目自己的帮手函数。**少了后三条这条闸门就抓不到
#: 真正发生过的那一次**：family.js 印任务 ID 走的是 `line(div, t.id, 'meta')`，
#: elder.js 把它念给老人听走的是 `setStatus(\`当前任务：${data.task_id}…\`)`。
#: 一条只认 `textContent` / `innerText` 的闸门在这两处上都是绿的。
_TEXT_SINKS = (
    r"\.textContent\s*=",
    r"\.innerText\s*=",
    r"createTextNode\(",
    r"\bline\(",
    r"\bsetStatus\(",
    r"\baddBubble\(",
)
_SINK_RE = re.compile("|".join(_TEXT_SINKS))

#: 这几个帮手必须真的存在。改名之后闸门会安静地少认一类渲染点，而"少认"和"没有泄漏"
#: 在结果里长得一模一样——`test_the_identifier_scan_reaches_the_render_sites` 守这一条。
_HELPER_DEFINITIONS = ("function line(", "function setStatus(", "function addBubble(")

#: 屏幕上不该出现的字段。`id` 和任何 `*_id`，加上审计事件码与确认摘要。
#:
#: 数的是"读了这个字段"，不是"字段叫什么"：`api(\`/v6/tasks/${data.task_id}/glass-box\`)`
#: 里也有 `.task_id`，但那是拼接口路径，不是往屏幕上写——所以只在渲染点里面找。
_RAW_IDENTIFIER = re.compile(r"\.(?:id|[a-z]+_id|event_type|approval_digest)\b")

#: app 面加载的全部脚本，从 PAGE_SCRIPTS 推出来而不是另抄一份名单。
APP_SCRIPTS = sorted({s for page in APP_PAGES for s in PAGE_SCRIPTS[page]})


def _strip_js_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", js, flags=re.M)


def _rendered_expressions(js: str) -> list[str]:
    """每一处"这段文字要写到屏幕上"的表达式原文。

    调用式的写法（`line(` / `setStatus(` / `createTextNode(`）按括号配对取到实参结束，
    赋值式的（`.textContent =`）取到分号。取整条表达式而不是整行，是因为 elder.js 那处
    是一个跨三行的三元表达式——按行取会把条件和分支切开，而 ID 在分支里。
    """
    js = _strip_js_comments(js)
    out: list[str] = []
    for match in _SINK_RE.finditer(js):
        start = match.end()
        if match.group(0).endswith("("):
            depth, i = 1, start
            while i < len(js) and depth:
                if js[i] == "(":
                    depth += 1
                elif js[i] == ")":
                    depth -= 1
                i += 1
            out.append(js[start:i])
        else:
            end = js.find(";", start)
            out.append(js[start: end if end != -1 else len(js)])
    return out


def _identifier_leaks(source: str) -> list[str]:
    """渲染点里读了原始标识符的那几处。

    先剪掉三种**正当**用法，判据与 `test_the_family_page_never_prints_a_raw_event_code`
    保持一致：两个翻译函数的入参，以及以事件码/状态码当下标的查表。剩下的每一处都是
    原始标识符在往屏幕上走。
    """
    leaks: list[str] = []
    for expression in _rendered_expressions(source):
        cleaned = re.sub(r"\b(?:actorName|auditLabel)\([^()]*\)", "«译»", expression)
        cleaned = re.sub(r"\b[A-Z_]+\[[^\]]*\.(?:event_type|status)\]", "«查表»", cleaned)
        # 三元表达式的**条件**不是输出。
        #
        # `setStatus(data.task_id ? '正在办：缴费' : '…')` 里读了 `.task_id`，但读它是
        # 为了判断"有没有在办事"，屏幕上一个字符都不会出现。第一版没剪这一段，于是
        # 把 elder.js 那处**已经修好**的代码又报成泄漏——一条会在修好之后继续红的
        # 断言，比没有这条断言更糟：它会训练人去改断言而不是改代码。
        #
        # 只剪到第一个 `?` 为止，而且要求它后面不是 `.`（`a?.b` 是可选链，不是三元）。
        # 分支里读 ID 照样会被抓到，因为分支在 `?` 之后。
        cleaned = re.sub(r"^[^?]*\?(?!\.)", "«判断»", cleaned, count=1)
        if _RAW_IDENTIFIER.search(cleaned):
            leaks.append(" ".join(expression.split())[:160])
    return leaks


#: `elder.js` 曾经带一个 `xfail(strict=True)` 挂在这里。
#:
#: 这条闸门刚建起来时，它第一次跑就在 elder.js 的
#: `setStatus(data.task_id ? \`当前任务：${data.task_id}…\`)` 上红了——屏幕上、
#: 以及**读屏软件念出来**的是「当前任务：task-cf917fee2790476500fb。」，
#: 而受众是一位视力在下降的老人。同一个缺陷先在 /family 的任务卡上被视觉审查抓到，
#: 这条闸门顺着同一条规则把老人端也点了出来。
#:
#: 标记已经摘掉，缺陷已修：状态行现在说「正在办：缴费」，类型经 `TASK_TYPE_WORD`
#: 翻译，认不出的说「这件事」而不兜底成原始值。`strict=True` 正是为了逼出这一步
#: ——修好之后它会报 XPASS 而不是安静变绿，否则 elder.js 会永久留在闸门外面。
@pytest.mark.parametrize("script", APP_SCRIPTS)
def test_the_app_surface_never_renders_a_raw_identifier(script: str) -> None:
    """手机框里的脚本不许把原始标识符写到屏幕上。

    上面那条闸门只看源码里的字，看不见运行时拼出来的东西：`line(div, t.id, 'meta')`
    在源码里没有一个禁用词，在屏幕上是 `task-cf917fee2790476500fb`。

    一位来看爸爸今天怎么样的人，不需要一个能 grep 的主键；逐条原始记录在 /trust，
    那里才是它的地方。
    """
    leaks = _identifier_leaks((STATIC / script).read_text(encoding="utf-8"))
    assert not leaks, (
        f"{script} 把原始标识符渲染到了屏幕上（{len(leaks)} 处）：\n  "
        + "\n  ".join(leaks)
        + "\n  手机框里只放「哪件事、到哪一步」。原始标识符属于 /trust。"
    )


def test_the_identifier_scan_reaches_the_render_sites() -> None:
    """扫描器必须真的找到了渲染点，而且认得这个项目的帮手函数。

    一个"跑了但一个渲染点都没找到"的检查，和没有这个检查是一回事，而它在结果里
    看起来一模一样地绿。这一页最厚的两个脚本各有五十来个渲染点，所以判据不是拍
    脑袋的下限，而是"两个主脚本都必须上双位数"。

    同时钉住三个帮手函数**还叫这个名字**。它们被改名之后，`_SINK_RE` 会安静地少
    认一整类渲染点——而 family.js 和 elder.js 那两次泄漏走的正是这一类。
    """
    counts = {
        script: len(_rendered_expressions((STATIC / script).read_text(encoding="utf-8")))
        for script in APP_SCRIPTS
    }
    for script in ("elder.js", "family.js"):
        assert counts[script] >= 10, (
            f"{script} 只找到 {counts[script]} 个渲染点（全部：{counts}）——"
            "取表达式的正则跟这个文件的写法对不上了"
        )

    everything = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(STATIC.glob("*.js"))
    )
    for definition in _HELPER_DEFINITIONS:
        assert definition in everything, (
            f"闸门认的帮手 `{definition}` 在整个 static 目录里找不到定义了。"
            "改名的话 _TEXT_SINKS 要跟着改，否则这一类渲染点从此不再被检查。"
        )


def test_the_identifier_scan_catches_the_leak_that_actually_shipped() -> None:
    """变异测试：把出过事的那四种写法打回去，闸门必须每一种都抓到。

    这一条防的是把 `_TEXT_SINKS` 收窄成只认 `textContent` / `innerText`——那样写出来
    的闸门在 family.js 和 elder.js 那两次泄漏上都是绿的，而它看起来和这一条一样。
    第一种就是当时真的上线了的那一行，一个字都没改。
    """
    js = (STATIC / "family.js").read_text(encoding="utf-8")
    assert not _identifier_leaks(js), "基线不干净，下面的变异说明不了任何事"

    anchor = "  if (t.status === NEEDS_FAMILY && t.approval_digest) {"
    title = "title.textContent = t.summary || t.task_type;"
    step = "  div.appendChild(step);"
    mutations = {
        "line() 帮手（真的上线过的那一行）": (anchor, "  line(div, t.id, 'meta');\n" + anchor),
        "textContent 直写": (title, "title.textContent = t.id;"),
        "模板串里拼进去": (title, "title.textContent = `${t.summary}（${t.id}）`;"),
        "createTextNode": (step, step + " div.appendChild(document.createTextNode(t.id));"),
    }
    for label, (needle, replacement) in mutations.items():
        assert needle in js, f"变异 `{label}` 的锚点在 family.js 里找不到了，这条变异没打进去"
        assert _identifier_leaks(js.replace(needle, replacement, 1)), (
            f"变异 `{label}` 没有被抓到——闸门漏掉了一种真实发生过或同类的泄漏写法"
        )
