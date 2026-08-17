"""控件清单：从代码生成，不从文档抄。

## 为什么必须有这个东西

`frontend_redesign/ia/08_click_map.md` 是本项目名义上的行为事实源，但它
**只覆盖 41 / 119 个控件**（四个 app 小节里共 41 个唯一 `#id`，`/family` 只登记了
两个，其余用中文标签描述而抽取器只认反引号里的 `#id`）。而且它是**手写**的、
**单向**被读一次（`test_no_control_was_silently_deleted.py:177`），文件缺失时还是
`pytest.skip`。后果：删一个控件 + 顺手删掉它在文档里那一行 = 全绿。

产品架构重构要把控件跨页面重新组织，而现有那道「控件没被静默删除」的闸门把
`now` 算成**四个 app 页面 id 的并集**，对 app → app 的搬迁恒为绿。没有一份完备的、
机器生成的清单，「禁止 Silent Delete」这条纪律是不可执行的。

## 机械事实 vs 人的判断，分开放

这份脚本**只推导能推导的**：

    id · 标签 · 所在文件 · 所在 [data-panel] · handler 文件 · handler 函数 ·
    该函数体内调用的接口 · interaction_type · 是否带 hidden

而 `surface` / `shell` / `module` / `visibility` 是**分类决定**，不是从代码里读得出来的
事实。自动猜它们会得到一份看起来权威、实际是编的表——这正是这个项目反复栽过的那种
失败（声明了不等于生效、读到的值不等于决定结果的值）。所以分类放在
`CLASSIFICATION` 里由人填，**没填的控件脚本直接报失败并逐个点名**。

第一次跑必然是 119 个未分类。那不是 bug，那就是这一阶段要做的工作本身。

## 用法

    python backend/scripts/build_control_inventory.py           # 生成并检查
    python backend/scripts/build_control_inventory.py --diff    # 只比对，不写文件
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
import posixpath
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from youhuo.surfaces import PAGE_TO_ROUTE, surface_of  # noqa: E402

STATIC = ROOT / "backend" / "static"
OUT_JSON = ROOT / "frontend_redesign" / "ia" / "11_control_inventory.json"
OUT_MD = ROOT / "frontend_redesign" / "ia" / "11_control_inventory.md"

#: 老六页（外加 `/app` 的主页）由路由表给出，山水版那一套**按目录取**。
#:
#: 只写 `list(PAGE_TO_ROUTE)` 的后果实测如下：`surfaces.py` 只登记了
#: `/app → app/pages/home.html` 一条，于是这份自称「事实源」的清单
#: **17 个 app 页面里只覆盖了 1 个**。加了七个新页面、四十多个按钮之后，
#: 清单总数一动不动——而「数字没变」在结果里和「没有新东西」长得一样。
#:
#: 为什么不把十七页全登记进 `SURFACES`：那张表记的是**路由**，
#: 而这些是 `/app` 这一个 shell 内部的页面，不是十七个 URL 入口。
#: 登记进去会让一批按路由遍历的闸门去访问不存在的 URL。
_APP_PAGES = sorted(
    str(p.relative_to(STATIC)).replace("\\", "/")
    for p in (STATIC / "app" / "pages").glob("*.html")
)
PAGES = list(dict.fromkeys(list(PAGE_TO_ROUTE) + _APP_PAGES))

#: `check_page_runtime.py` 在真浏览器里**按到**的数量（它只按 `button, summary`）。
#:
#: 放在这里是为了让静态清单和运行时对上账。第一次对账就发现两个缺口：
#:   ① 运行时比静态多 10 个 —— elder +3、judge +6、trust +1、stage +1，
#:      那些是 JS `createElement('button')` 建出来的（提醒的「我知道了/已完成」、
#:      任务卡的「同意/拒绝」之类），**根本不在 HTML 里**，所以静态扫描永远看不见；
#:   ② family −1 —— 有一个静态控件运行时够不到（多半是空列表下的 `<summary>`）。
#: 这两个缺口都会让"控件搬对了"变成不可验证，必须在 A2 之前有结论。
RUNTIME_PRESSES = {"index.html": 0, "elder.html": 28, "family.html": 6, "care.html": 5,
                   "trust.html": 1, "judge.html": 29, "stage.html": 50}

#: 什么算一个「控件」。
#:
#: 比 `check_page_runtime.py:915` 的 `button, summary` 宽：那道闸门只按得动这两种，
#: 但清单要记的是**用户能操作的每一样东西**，否则 `<select>`（语速、字号两个无障碍
#: 控件就是 select）和 `<input>` 会整类不在册。
CONTROL_TAGS = {"button", "summary", "select", "input", "textarea", "a", "form"}

#: 正则只负责认出「这里引了一个 .js」，**路径长什么样不写在里面**。
#:
#: 原来是 `src="/static/([\w.-]+\.js)"`：`/static/` 焊死、字符类还不含斜杠。
#: 后果是子目录里的页面（`app/pages/*.html` 用的是 `../assets/js/app.js`）
#: 一律解析成空清单——十个页面的脚本从此在视野之外，而闸门全绿。
#: 同一条坏正则在 `test_app_surface_speaks_no_engineering.py` 里已经修过一次，
#: 那次的报告明确写着「这里还有第二份拷贝，而且是**静默**返回空」。就是这一份。
_SRC_RE = re.compile(r'<script\b[^>]*\bsrc="([^"\s>]+\.js)"')
_IMPORT_RE = re.compile(r"""\bfrom\s+['"]([^'"\n]+\.js)['"]""")


def _resolve_script(src: str, base: str) -> str | None:
    """把一处引用解析成 STATIC 下的相对路径；解析不到就丢弃。

    `base` 是**写下这处引用的那份文件**。基准必须是引用方自己而不是 STATIC 根：
    `app/pages/home.html` 里的 `../assets/js/app.js` 要落到 `app/assets/js/app.js`，
    同一串字写在根目录页面里会指到 static 之外。
    """
    if src.startswith(("http://", "https://", "//")):
        return None
    if src.startswith("/static/"):
        rel = src[len("/static/"):]
    elif src.startswith("/"):
        return None
    else:
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(base), src))
    if rel.startswith(".."):
        return None
    return rel if (STATIC / rel).is_file() else None


def scripts_for(page: str) -> list[str]:
    """这一页真正加载的 JS：`<script src>` 加上跟着 ES `import` 走的闭包。

    照抄 `test_app_surface_speaks_no_engineering.py:59-80`。那里的注释记着为什么不能
    用手写清单：漏掉的文件从此永远在视野之外，而"安静地少测"和"通过"长得一样。
    """
    html = (STATIC / page).read_text(encoding="utf-8")
    seen: list[str] = []
    queue = [(ref, page) for ref in _SRC_RE.findall(html)]
    while queue:
        ref, base = queue.pop(0)
        name = _resolve_script(ref, base)
        if name is None or name in seen:
            continue
        seen.append(name)
        # 跟着 import 走时，基准换成那个脚本自己。
        queue += [(r, name) for r in _IMPORT_RE.findall((STATIC / name).read_text(encoding="utf-8"))]
    return seen


#: 稳定身份的取键顺序。前面的优先。
#:
#: 每一条都必须是「改样式不会变、改布局不会变、但这个控件还是这个控件」的东西。
#: 刻意**不用** class（`.secondary` 改成 `.ghost` 就断）、**不用**位置（重构必然变）、
#: **不用**可见文字（文案轮会全改一遍，而这个项目已经有一轮专门改文案的 Phase）。
_KEY_ATTRS = ("id", "data-section", "data-text", "data-run", "data-jump",
              "data-sheet-open", "data-sheet-close", "data-panel", "name",
              # 下面这批是山水版那一套的词汇。原来这张表**只有老前端的属性**，
              # 于是新前端 63 个控件被判成「没有稳定身份」——它们当然有身份，
              # 只是用的是另一套属性名。一份把「我这张表没列到」写成
              # 「这个控件没身份」的清单，会让人去补一堆本来就有的 id。
              #
              # 刻意**不含 `data-action`**：它太泛（`close-modal` 一页出现两次），
              # 放在这里会顶掉 `id=sosModal/button` 这种更有信息量的祖先身份。
              # 它作为最后的兜底放在 `_stable_key` 末尾。
              "data-service", "data-to", "data-do", "data-kind",
              "data-font-scale", "data-voice-speed", "data-contrast",
              "data-open", "data-close", "data-goback", "data-sos", "data-label")

#: 能给后代提供身份的祖先属性。
#:
#: 评委页七拍里那 7 个「看这一拍的证据」`<summary>` 文字**完全相同**，所以文字分不开它们；
#: 但它们各自住在 `article.beat[data-beat="01".."07"]` 里，于是
#: `data-beat=03/summary` 就是一个稳定且唯一的身份。
_ANCESTOR_KEY_ATTRS = ("data-beat", "data-panel", "id")


def _stable_key(tag: str, attrs: dict[str, str], ancestors: list[dict[str, str]]) -> str:
    for attr in _KEY_ATTRS:
        value = attrs.get(attr)
        if value:
            return f"{attr}={value}"
        # 布尔属性（`data-sheet-open` 常写成不带值）也算一个身份。
        if attr in attrs:
            return attr
    if tag == "a" and attrs.get("href"):
        # 导航链接由 `test_tabbar.py` 的 EXPECTED_HREFS 按 href 钉顺序与目标，
        # 所以 href 对它们是一个真身份，不是退路。
        return f"href={attrs['href']}"
    # 自己没有身份，就从最近一个有身份的祖先借。
    for parent in reversed(ancestors):
        for attr in _ANCESTOR_KEY_ATTRS:
            if parent.get(attr):
                return f"{attr}={parent[attr]}/{tag}"
    # 最后兜底：`data-action`。放在祖先之后而不是 `_KEY_ATTRS` 里，
    # 是因为它一页里会重复（`close-modal` 两个弹窗各一个），而
    # `id=sosModal/button` 这种祖先身份更能说明「是哪一个」。
    # 但对返回箭头（`data-action="back"`，一页只有一个、又没有 id 也没有
    # 带身份的祖先）来说，它是唯一可用的稳定身份——没有它，十七页的返回键
    # 会全部被判成「无身份」。
    if attrs.get("data-action"):
        return f"data-action={attrs['data-action']}"
    return ""


class ControlScanner(HTMLParser):
    """带祖先栈的扫描器。

    **不用正则找 `[data-panel]` 祖先**：正则没有嵌套概念，而"这个控件落在哪个分区里"
    正是本轮迁移矩阵要断言的东西——判据本身靠猜是不行的。`html.parser` 是标准库，
    没有新依赖，而它给的 start/end 事件足够维护一个栈。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.body: dict[str, str] = {}
        self.controls: list[dict] = []
        #: `<input>` `<br>` 这些没有闭合标签，进不了栈，否则栈会越堆越深。
        self.void = {"input", "img", "br", "hr", "meta", "link", "source", "use", "path"}

    def _ancestor(self, attr: str) -> str | None:
        for _tag, attrs in reversed(self.stack):
            if attr in attrs:
                return attrs[attr]
        return None

    def _record(self, tag: str, attrs: dict[str, str]) -> None:
        if tag not in CONTROL_TAGS:
            return
        # `<a>` 只在真的能点的时候算（`<a>` 没有 href 就是个锚点）。
        if tag == "a" and "href" not in attrs:
            return
        # 隐藏的类型不是控件（`<input type="hidden">`）。
        if tag == "input" and attrs.get("type") == "hidden":
            return
        self.controls.append({
            "id": attrs.get("id") or "",
            "tag": tag,
            "type": attrs.get("type", ""),
            "classes": attrs.get("class", ""),
            "panel": self._ancestor("data-panel") or "",
            "section": attrs.get("data-section", ""),
            "shell_hook": self._ancestor("data-shell") or "",
            "hidden": "hidden" in attrs or "hidden" in self._hidden_ancestors(),
            "href": attrs.get("href", ""),
            "aria_label": attrs.get("aria-label", ""),
            "text_hint": "",
            # 稳定身份：迁移矩阵拿它当键，**不是只拿 `id`**。
            #
            # 实测 145 个控件里只有 57 个带 id，88 个没有——而按 id 追踪意味着那 88 个
            # 搬走或消失都不会有任何东西发现。但它们里绝大多数**有别的稳定标识**：
            # `care` 的五个分区键是 `data-section`、老人端的快捷句是 `data-text`、
            # 评委页的七拍是 `data-run`、抽屉开关是 `data-sheet-open`。
            #
            # 所以键的优先级写清楚，让"能追踪"覆盖到几乎全部控件，而不是靠给 88 个元素
            # 硬加 id（那是为了让闸门开心去改产品，方向反了）。
            "key": _stable_key(tag, attrs, [a for _t, a in self.stack]),
        })

    def _hidden_ancestors(self) -> list[str]:
        return ["hidden" for _t, a in self.stack if "hidden" in a]

    def handle_starttag(self, tag: str, attrs) -> None:
        got = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "body":
            self.body = got
        self._record(tag, got)
        if tag not in self.void:
            self.stack.append((tag, got))

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._record(tag, {k: (v if v is not None else "") for k, v in attrs})

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        """给最近一个控件补一句可见文字，方便人读这份清单。"""
        text = " ".join(data.split())
        if text and self.controls and not self.controls[-1]["text_hint"]:
            self.controls[-1]["text_hint"] = text[:18]


# --- handler 归属 -----------------------------------------------------------

_FUNC_HEAD = re.compile(
    r"(?:^|\n)\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
    r"|(?:^|\n)\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
)
_API_CALL = re.compile(r"""\b(?:api|fetch)\(\s*[`'"]([^`'"]+)[`'"]""")
_LISTEN = re.compile(r"""addEventListener\(\s*['"](\w+)['"]""")


def enclosing_function(source: str, at: int) -> str:
    """`at` 这个位置落在哪个函数里。

    向前找最近的函数头。找不到就说 `(顶层)`——那本身是有用的信息：顶层绑定在这个项目
    里出过事（搬走一个控件之后旧脚本顶层还 `byId('x').addEventListener`，
    TypeError 把整页绑定一起弄死，`test_no_control_was_silently_deleted.py:147-164`
    就是为这个建的）。
    """
    best = "(顶层)"
    for match in _FUNC_HEAD.finditer(source[:at]):
        best = match.group(1) or match.group(2) or best
    return best


def function_body(source: str, at: int) -> str:
    """包含 `at` 的那个函数体，用大括号配对取。

    用来把接口调用归属到控件，而不是笼统地说"这个文件里出现过这些接口"。
    取不到就退回整个文件的一小段窗口——宁可范围偏大，也不要报一个空列表让人以为
    这个控件不碰接口。
    """
    start = source.rfind("{", 0, at)
    if start < 0:
        return source[max(0, at - 400): at + 400]
    depth, i = 0, start
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start: i + 1]
        i += 1
    return source[start:]


def trace(control_id: str, page_scripts: list[str], bodies: dict[str, str],
          key: str = "") -> dict:
    """在这一页加载的脚本里找这个控件，回答「谁绑的、怎么绑的、调了什么接口」。

    **不能只找 id。** 第一版只找 id，于是 62 个控件被报成"没人绑"——而它们全都绑着，
    只是走的不是 id：

        `data-text=帮我交水费`   →  elder.js  `querySelectorAll('[data-text]')`
        `data-section=today`     →  common.js `initSections` 按 `.seg` 委托
        `data-run=runOpen`       →  judge.js  按 `[data-run]` 委托
        `data-sheet-close`       →  sheet.js  按属性委托
        `id=stageRoles/button`   →  stage.js  按容器委托

    属性委托是这个项目的主要绑定方式之一（严格 CSP 下没有内联 onclick，委托很自然）。
    一份把"我只会查 id"报成"这个控件没人绑"的清单，会让人去修一个不存在的问题。
    """
    fallbacks: list[str] = []
    if key and "=" in key:
        attr, _value = key.split("=", 1)
        if attr.startswith("data-"):
            # `[data-text]` 这种属性选择器，以及裸属性名。
            fallbacks += [f"[{attr}]", attr]
        elif attr == "id" and "/" in key:
            # 祖先借来的身份：`id=stageRoles/button` → 去找容器 `stageRoles`。
            fallbacks.append(key.split("=", 1)[1].split("/")[0])
    elif key.startswith("data-"):
        fallbacks += [f"[{key}]", key]
    if not control_id and not fallbacks:
        return {"handler_file": "", "handler": "", "interaction_type": "", "apis": []}
    # `'mic'` 和 `'#mic'` 两种都要认。
    #
    # 第一版只认前者，结果 22 个控件报"追不到 handler"——里面有 `#mic` `#send` `#text`，
    # 而它们当然有 handler：这一页用的是 `document.querySelector('#mic')`，id 在源码里
    # 带着井号。一份把「我的正则没匹配上」写成「这个控件没人绑」的清单，
    # 比没有清单更危险，因为它会让人去修一个不存在的问题。
    needles = []
    if control_id:
        needles.append(re.compile(rf"""['"]#?{re.escape(control_id)}['"]"""))
    needles += [re.compile(re.escape(f)) for f in fallbacks]

    for needle in needles:
        for name in page_scripts:
            source = bodies[name]
            hit = needle.search(source)
            if not hit:
                continue
            body = function_body(source, hit.end())
            window = source[hit.end(): hit.end() + 600]
            listen = _LISTEN.search(window)
            return {
                "handler_file": name,
                "handler": enclosing_function(source, hit.start()),
                "interaction_type": listen.group(1) if listen else "",
                "apis": sorted({p for p in _API_CALL.findall(body) if p.startswith("/")}),
            }
    return {"handler_file": "", "handler": "", "interaction_type": "", "apis": []}


def infer_interaction(control: dict, traced: dict) -> str:
    """没在 JS 里找到监听器时，按标签给一个诚实的默认值。"""
    if traced["interaction_type"]:
        return traced["interaction_type"]
    if control["tag"] == "summary":
        return "details-toggle"
    if control["tag"] == "form":
        return "submit"
    if control["tag"] == "a":
        return "navigate"
    if control["tag"] in {"select", "textarea"} or control["type"] in {"range", "number"}:
        return "change"
    if control["tag"] == "button" and control["classes"].find("seg") >= 0:
        return "click"
    return ""


# --- 分类（人填，不许猜）----------------------------------------------------

# --- 分类：能推的推，推不出的才声明 -----------------------------------------
#
# `surface` 与 `shell` **完全由页面决定**，从 `youhuo.surfaces` 读，不在这里抄第二遍
# ——抄一遍就会有两个版本各自漂移。
#
# `module` 与 `visibility` 按下面的规则推导。规则写在代码里、能被审计，
# 这和"随手猜一个填进去"不是一回事：规则错了会**整类**错，看得出来；
# 猜出来的值是一个个孤立的编造，看起来还很像真的。
#
# 推不出来的、或者规则给错了的，进 `OVERRIDES`。

#: 落在任何 `[data-panel]` 之外的控件属于哪个模块。
#:
#: 这些是**外壳**上的东西（页头的返回、底部导航、Focus Mode 的输入行），
#: 它们不属于任何一格内容，而是承载所有格的那层框。
SHELL_MODULE = "shell"


def derive_module(control: dict) -> str:
    if control["panel"]:
        return control["panel"]
    return SHELL_MODULE


def derive_visibility(control: dict, surface: str) -> str:
    """能见度：什么时候这个控件会出现在人面前。

    顺序有讲究——先判表面（整页只给一类人看），再判是否需要状态才出现，
    最后才判主次。反过来的话，一个藏在 `[hidden]` 里的演示按钮会被标成
    `hidden-until-state`，而它真正的性质是"这一页不给消费者看"。
    """
    if surface == "presentation":
        return "presentation-only"
    if surface == "professional":
        return "professional-only"
    if control["hidden"]:
        return "hidden-until-state"
    if "secondary" in control["classes"]:
        return "secondary"
    return "primary"


#: 规则给错了的那几个。`key → (module, visibility)`，`None` 表示沿用推导值。
#:
#: 空着不是"还没填"——是"规则目前没有例外"。加一行之前先问：这一个真的是例外，
#: 还是上面那条规则本身写错了？后者要改规则，不是在这里打补丁。
OVERRIDES: dict[str, tuple[str | None, str | None]] = {}


def main() -> int:
    diff_only = "--diff" in sys.argv
    # 键用**相对 STATIC 的路径**，不是文件名。
    #
    # 原来是 `{p.name: ...}` 配 `STATIC.glob("*.js")`——只收根目录、还按裸文件名索引。
    # 山水版的脚本住在 `app/assets/js/` 下，`scripts_for()` 现在解析出的是
    # `app/assets/js/config.js` 这样的路径，拿它去查裸文件名的表当场 KeyError。
    # 按文件名索引还有个更安静的坑：两个目录里同名的 `config.js` 会互相覆盖，
    # 而覆盖之后追踪到的 handler 属于另一份文件——不报错，只是答案是错的。
    bodies = {
        str(p.relative_to(STATIC)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in STATIC.rglob("*.js")
    }

    rows: list[dict] = []
    for page in PAGES:
        scanner = ControlScanner()
        scanner.feed((STATIC / page).read_text(encoding="utf-8"))
        page_scripts = scripts_for(page)
        declared_surface = scanner.body.get("data-surface", "")
        info = surface_of(page)
        if declared_surface != info.surface:
            print(f"FAIL inventory: {page} 的 data-surface 是 {declared_surface!r}，"
                  f"而登记表说 {info.surface!r} —— 先让两边一致再谈清单")
            return 1
        for control in scanner.controls:
            traced = trace(control["id"], page_scripts, bodies, control["key"])
            module, visibility = OVERRIDES.get(control["key"], (None, None))
            rows.append({
                "key": control["key"],
                "id": control["id"],
                "tag": control["tag"],
                "text": control["text_hint"] or control["aria_label"],
                "source_file": page,
                # 山水版内部页面没有各自的路由——它们全都由 `/app` 这一个 URL 承载。
                # 记 `/app` 而不是编一个 `/app/pages/xxx`：后者会让人以为
                # 那是个能访问的地址。哪一页由 `source_file` 记着。
                "route": PAGE_TO_ROUTE.get(page, "/app"),
                "panel": control["panel"],
                "hidden": control["hidden"],
                "surface": info.surface,
                "shell": info.shell,
                "module": module or derive_module(control),
                "visibility": visibility or derive_visibility(control, info.surface),
                "handler_file": traced["handler_file"],
                "handler": traced["handler"],
                "interaction_type": infer_interaction(control, traced),
                "apis": traced["apis"],
            })

    keyed = [r for r in rows if r["key"]]
    keyless = [r for r in rows if not r["key"]]
    unclassified = [r for r in keyed if not r["surface"] or not r["visibility"]]
    unbound = [r for r in keyed if not r["handler_file"] and r["tag"] != "a"]

    # 键必须在页内唯一，否则矩阵会把两个控件当成一个。
    #
    # 实测有 14 个重复，分三类，每一类的意思不一样：
    #   ① `#stageRoles` 里五个兄弟按钮全靠祖先借身份 → 它们自己没有任何标识；
    #   ② `/family` 有两个 `href=/trust`（正文行内链接 + 卡片链接）→ 两个真控件，
    #      同一个目标；
    #   ③ `/care` 的 `href=/`（页头返回 + 底部导航首页）→ 同上。
    #
    # 这些不是"编号一下就完了"的小事：**它们现在没有稳定身份**，搬走了没人发现。
    # 所以这里给一个带序号的临时键让清单能用，同时把它们单独点名——
    # 重构时给它们加上真正的 `data-*` 钩子，这份名单就会自己变空。
    needs_hook: list[dict] = []
    counts: dict[str, int] = {}
    for row in keyed:
        where = f"{row['source_file']}:{row['key']}"
        counts[where] = counts.get(where, 0) + 1
        if counts[where] > 1:
            row["key"] = f"{row['key']}#{counts[where]}"
            needs_hook.append(row)
    # 第一个也要点名——它和后面那些一样没有自己的身份。
    first_of_dupes = {w for w, n in counts.items() if n > 1}
    for row in keyed:
        if f"{row['source_file']}:{row['key']}" in first_of_dupes:
            needs_hook.insert(0, row)

    print(f"控件总数 {len(rows)}：可追踪 {len(keyed)}，**无稳定身份 {len(keyless)}**")
    print(f"（其中带 id 的只有 {sum(1 for r in rows if r['id'])} 个——"
          "所以矩阵的键不能只用 id）")
    print(f"\n{'页面':<14}{'全部':>5}{'btn/sum':>9}{'可追踪':>8}{'运行时':>7}{'差额':>6}")
    for page in PAGES:
        page_rows = [r for r in rows if r["source_file"] == page]
        pressable = [r for r in page_rows if r["tag"] in ("button", "summary")]
        runtime = RUNTIME_PRESSES.get(page, 0)
        delta = runtime - len(pressable)
        mark = ("  ← JS 动态建的" if delta > 0
                else "  ← 有静态控件运行时够不到" if delta < 0 else "")
        print(f"  {page:<12}{len(page_rows):>5}{len(pressable):>9}"
              f"{sum(1 for r in page_rows if r['key']):>8}{runtime:>7}{delta:>+6}{mark}")

    by_attr: dict[str, int] = {}
    for row in keyed:
        by_attr[row["key"].split("=")[0]] = by_attr.get(row["key"].split("=")[0], 0) + 1
    print("\n身份来自：" + "、".join(f"{a} {n}" for a, n in
                                sorted(by_attr.items(), key=lambda kv: -kv[1])))

    if keyless:
        print(f"\n⚠ {len(keyless)} 个控件没有任何稳定身份 —— 它们搬走或消失，"
              "**不会有任何东西发现**：")
        for row in keyless:
            print(f"    {row['source_file']:<14}{row['tag']:<9}"
                  f"panel={row['panel'] or '—':<10}{row['text'][:18]}")

    if needs_hook:
        print(f"\n⚠ {len(needs_hook)} 个控件靠序号才区分得开 —— 它们自己没有标识，"
              "重构时要补 `data-*` 钩子：")
        for row in needs_hook:
            print(f"    {row['source_file']:<14}{row['key']:<34}{row['text'][:16]}")

    payload = json.dumps({"count": len(rows), "controls": rows},
                         ensure_ascii=False, indent=2)

    if diff_only:
        # 比对模式：落盘的清单必须和现在重新生成的一致。
        #
        # 这一条防的是「改了 HTML 却没重新生成清单」——那样迁移矩阵断言的是一份过期的
        # 事实，而它会**全绿**。这个项目已经为同一个形状建过一次闸门（重型报告的源码
        # 指纹），理由一样：读一份产物不等于看到了当前的事实。
        if not OUT_JSON.is_file():
            print(f"FAIL inventory --diff: {OUT_JSON.name} 还不存在，先跑一次生成")
            return 1
        if OUT_JSON.read_text(encoding="utf-8") != payload:
            old = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            old_keys = {f"{c['source_file']}:{c['key']}" for c in old["controls"]}
            new_keys = {f"{r['source_file']}:{r['key']}" for r in rows}
            print("FAIL inventory --diff: 落盘的清单和代码不一致——重新生成。")
            if new_keys - old_keys:
                print(f"  代码里新增：{sorted(new_keys - old_keys)[:10]}")
            if old_keys - new_keys:
                print(f"  代码里消失：{sorted(old_keys - new_keys)[:10]}")
            if old_keys == new_keys:
                print("  键集合相同，说明变的是某个控件的属性（panel / handler / 接口 / 分类）")
            return 1
        print("PASS inventory --diff: 落盘的清单与代码一致")
        return 0

    if not diff_only:
        OUT_JSON.write_text(payload, encoding="utf-8")
        _write_md(rows, keyed, keyless, unclassified, unbound)
        print(f"\n已写出 {OUT_JSON.relative_to(ROOT).as_posix()} 与 "
              f"{OUT_MD.relative_to(ROOT).as_posix()}")

    if unclassified:
        print(f"\nFAIL inventory: {len(unclassified)} 个控件还没有分类。")
        print("  分类是人的判断，脚本不猜——猜出来的表看起来权威，实际是编的。")
        print("  逐个填进 CLASSIFICATION：")
        for row in unclassified[:12]:
            print(f"    {row['id']:<22} {row['source_file']:<14} "
                  f"panel={row['panel'] or '—':<10} {row['text'][:14]}")
        if len(unclassified) > 12:
            print(f"    …… 还有 {len(unclassified) - 12} 个")
        return 1

    # 说清楚检查了什么、没检查什么。
    #
    # 这一行原先写「都能追到 handler」，而 `unbound` 只是算出来放进 md，从没被断言过
    # ——一句 PASS 不该声称一件没验的事。这个项目本轮已经三次栽在"仪器说的比它做的多"。
    print(f"\nPASS inventory: {len(rows)} 个控件都有稳定身份与分类"
          f"（{len(needs_hook)} 个靠序号，见上）")
    if unbound:
        print(f"  另有 {len(unbound)} 个控件在这一页加载的脚本里找不到对它的引用："
              + "、".join(r["key"] for r in unbound))
        print("  这不一定是缺陷——`#openExtras` 就是由 `[data-sheet-open]` 属性选择器绑的，"
              "不经 id。但每一个都要有解释。")
    return 0


def _write_md(rows, named, anonymous, unclassified, unbound) -> None:
    lines = [
        "# 控件清单（机器生成，不要手改）",
        "",
        "由 `backend/scripts/build_control_inventory.py` 从代码生成。",
        "**这份文件替代 `08_click_map.md` 成为控件层面的事实源**——那一份只覆盖 "
        "41 / 119 个控件，且是手写、单向、缺文件时 skip 的。",
        "",
        f"| 总数 | {len(rows)} |",
        "|---|---|",
        f"| 有 id | {len(named)} |",
        f"| 无 id（匿名控件，无法被矩阵追踪） | {len(anonymous)} |",
        f"| 未分类 | {len(unclassified)} |",
        f"| 追不到 handler（非 `<a>`） | {len(unbound)} |",
        "",
    ]
    if anonymous:
        lines += [
            "## 无 id 的控件",
            "",
            "迁移矩阵按 id 追踪，所以**没有 id 的控件搬走之后没有任何东西能发现**。",
            "重构时要么给它们 id，要么在这里写明为什么不需要追踪。",
            "",
            "| 页面 | 标签 | panel | 文字 |",
            "|---|---|---|---|",
        ]
        for row in anonymous:
            lines.append(f"| {row['source_file']} | {row['tag']} | "
                         f"{row['panel'] or '—'} | {row['text'][:20]} |")
        lines.append("")

    lines += [
        "## 全部控件",
        "",
        "| id | 页面 | panel | 标签 | 交互 | handler | 接口 | surface | shell | module | visibility |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in named:
        apis = "<br>".join(row["apis"]) or "—"
        lines.append(
            f"| `#{row['id']}` | {row['source_file'].removesuffix('.html')} "
            f"| {row['panel'] or '—'} | {row['tag']} | {row['interaction_type'] or '—'} "
            f"| {row['handler_file'] or '—'}:{row['handler'] or '—'} | {apis} "
            f"| {row['surface'] or '**?**'} | {row['shell'] or '**?**'} "
            f"| {row['module'] or '**?**'} | {row['visibility'] or '**?**'} |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
