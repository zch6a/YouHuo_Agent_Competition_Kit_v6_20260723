r"""把 `backend/static/app/` 那十个新页面拉进判据网里。

**这些页面此前完全没有闸门。** 现有的 UI 判据（`test_no_emoji_as_icons.py`、
`test_control_inventory_is_the_fact_source.py`、`test_app_css_layers_stay_scoped.py`
……）扫的都是 `backend/static/*.html` 那六七个老页面，它们的 `PAGES` 是写死的文件名
列表。新页面在 `backend/static/app/pages/` 这个**下一层目录**里，于是一条判据都扫不到。

后果已经发生过一次：一个 `💧` 混进新页面，`test_no_emoji_as_icons.py` 从头到尾是绿的
——不是因为它判错了，是因为它根本没读那个文件。整套 1000+ 条断言全绿，而屏幕上有硬约束
第七条的违规。这就是「判据覆盖面」本身要被断言的理由。

这个文件守六件事，每一件都对应一类**屏幕上看不出来、测试也不会响**的故障：

  1. emoji —— 硬约束第七条，判据与老页面那条**逐字节相同**（见 `test_the_emoji_rule_…`）
  2. `data-action` 必须有处理分支 —— 否则按钮按下去静默地什么都不发生
  3. `data-bind` 的字段必须是后端真的会返回的 —— 打错一个字母那一处永远空白且不报错
  4. `data-bind` 元素里不许留写死的兜底值 —— 接口一挂，屏幕上留着一个像真的的假金额
  5. 引用的美术文件必须存在 —— 404 的 `<img>` 在截图里只是一块空白
  6. 十个页面都在，且都加载 `app.js` —— 少一个 `<script>`，整页的按钮和绑定全是死的

**这个文件只读不写。** 它不修页面、不修其它判据。发现的存量违规如实变红，
由页面的负责人决定是修页面还是调判据。
"""

from __future__ import annotations

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "static" / "app"
PAGES_DIR = APP / "pages"
APP_JS = APP / "assets" / "js" / "app.js"
APP_API = ROOT / "backend" / "youhuo" / "app_api.py"
EMOJI_GATE = Path(__file__).with_name("test_no_emoji_as_icons.py")

#: 这十个页面**逐个写死**，不是 `glob` 出来的。
#:
#: 为什么不 glob：glob 的失败模式是「文件没了 → 参数化出 9 个用例 → 9 个全绿」。
#: 一个页面被误删，判据反而更安静。写死之后，少一个文件立刻是一条红。
#: 而多出来的页面由 `test_no_page_escapes_this_gate` 兜住——那正是这一轮要修的
#: 「新东西落在判据之外」本身。
PAGES = [
    "home.html",
    "voice-listening.html",
    "recognition.html",
    "bill-detail.html",
    "voice-confirm.html",
    "payment-success.html",
    "records.html",
    "services.html",
    "certificate.html",
    "profile.html",
]

#: `app.js` 的 `hydrate()` 把三个接口的响应装进这三个顶层分组，再交给 `bindData()`：
#:
#:     bindData({profile: …, bill: …, agenda: …})
#:
#: 所以 `data-bind="bill.amount"` 的合法性 = 「`GET /bills/water/current` 的返回里
#: 有没有 `amount`」。这张表把分组名映射回 `app_api.py` 里的路由；
#: `test_the_bind_groups_are_the_ones_this_gate_knows_about` 会校验它没有和 `app.js` 脱节。
BIND_GROUP_ROUTES = {
    "profile": "GET /profile",
    "bill": "GET /bills/water/current",
    "agenda": "GET /agenda",
}

#: Emoji 与彩色象形符号的码位区间。
#:
#: **这段是从 `test_no_emoji_as_icons.py` 原样抄过来的**，一个字符都没改——
#: 任务要求「用同样的判据作用到新页面上」，而两套页面用两套 emoji 定义，
#: 就等于两条不同的硬约束。`test_the_emoji_rule_is_byte_identical_to_the_old_gate`
#: 会在每次跑的时候重新对一遍：那边一改，这边立刻红，而不是悄悄分叉。
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # 杂项象形、表情、交通、补充象形
    "\U0001F000-\U0001F0FF"   # 麻将、扑克
    "☀-➿"           # 杂项符号与装饰符（☀ ⚠ ✂ ❤ …）
    "⬀-⯿"           # 杂项符号与箭头里的实心块
    "️"                  # 变体选择符 16：把前一个字符渲染成 emoji
    "⃣"                  # 组合围栏键帽（1️⃣）
    "]"
)

#: HTML 里不需要闭合标签的元素。`data-bind` 的取文范围要靠标签栈算，
#: 不把这些排除掉，栈会一路错位，后面每一个元素的「内文」都是错的。
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

#: 页面里对美术资源的引用。故意**不**绑定到某个属性名（`src` / `srcset` / `href` /
#: CSS 的 `url()` 都可能出现）——只要文本里出现了一条指向 `../art/` 的路径，
#: 它就该是一个真实存在的文件。
_ART_REF = re.compile(r"\.\./art/[A-Za-z0-9_./-]+?\.(?:png|webp|jpe?g|svg|gif)")


# ---- 读取与解析 --------------------------------------------------------------


def _read(page: str) -> str:
    return (PAGES_DIR / page).read_text(encoding="utf-8")


def _strip_comments(source: str) -> str:
    """剥 HTML 注释。

    这个项目已经有三条断言栽在「命中了我自己的注释」上（见 `test_no_emoji_as_icons.py`
    的模块注释）。注释里写什么都不上屏，所以扫描之前一律先剥掉。
    """
    return re.sub(r"<!--.*?-->", " ", source, flags=re.S)


def _visible_html(page: str) -> str:
    """页面上**会被人看到**的文本：标签之间的文字 + 三个会被读屏念出来的属性。

    与 `test_no_emoji_as_icons.py::_visible_html` 同构（同样剥注释、剥 `<script>`，
    同样取 `aria-label|title|alt`），只是换了目录。
    """
    source = _strip_comments(_read(page))
    source = re.sub(r"<script\b.*?</script>", " ", source, flags=re.S)
    labels = " ".join(re.findall(r'(?:aria-label|title|alt)="([^"]*)"', source))
    between = " ".join(re.findall(r">([^<]+)<", source))
    return between + " " + labels


def _line_of(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


class _BindCollector(HTMLParser):
    """收集每一个 `[data-bind]` 元素的字段名、行号，以及它标签之间的文字。

    用真正的标签栈而不是正则：`<b data-bind="x">68.40</b>` 好抓，
    `<div data-bind="x"><span>68.40</span></div>` 正则就抓不全了，而后者一样是
    「接口挂了屏幕上还有个假金额」。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[list] = []
        self.found: list[tuple[str, int, str]] = []   # (字段名, 行号, 内文)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VOID_TAGS:
            return
        self._stack.append([tag, dict(attrs).get("data-bind"), self.getpos()[0], []])

    def handle_startendtag(self, tag: str, attrs) -> None:
        d = dict(attrs)
        if d.get("data-bind") is not None:
            self.found.append((d["data-bind"], self.getpos()[0], ""))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                frame = self._stack.pop(i)
                del self._stack[i:]          # 丢掉未闭合的内层，别让栈永久错位
                if frame[1] is not None:
                    self.found.append((frame[1], frame[2], "".join(frame[3])))
                return

    def handle_data(self, data: str) -> None:
        for frame in self._stack:
            frame[3].append(data)


def _binds(page: str) -> list[tuple[str, int, str]]:
    parser = _BindCollector()
    parser.feed(_strip_comments(_read(page)))
    return parser.found


def _actions(page: str) -> list[tuple[str, int]]:
    source = _strip_comments(_read(page))
    return [
        (m.group(1), _line_of(source, m.start()))
        for m in re.finditer(r'data-action="([^"]+)"', source)
    ]


def _art_refs(page: str) -> list[tuple[str, int]]:
    source = _strip_comments(_read(page))
    return [(m.group(0), _line_of(source, m.start())) for m in _ART_REF.finditer(source)]


def _script_sources(page: str) -> list[str]:
    return re.findall(r'<script[^>]*\bsrc="([^"]+)"', _strip_comments(_read(page)))


# ---- 从 app.js 里读出「哪些 action 真的有分支」 --------------------------------


def _js_without_comments() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", source, flags=re.M)


def _handled_actions() -> set[str]:
    """`app.js` 的全局点击分发器里，`a === "…"` 命中的那些字符串。

    分发器长这样（`app.js` 第 157 行起）：

        document.addEventListener("click", async e => {
          const el = e.target.closest("[data-action]"); if (!el) return;
          const a = el.dataset.action;
          if (a === "nav") { … } if (a === "back") { … } …
        })

    所以「有没有处理分支」就等价于「`a === "x"` 这个比较存不存在」。
    先剥注释——注释里提到某个 action 不会让按钮动起来。
    """
    return set(re.findall(r'\ba\s*===\s*"([^"]+)"', _js_without_comments()))


def _bind_groups_in_app_js() -> set[str]:
    """`bindData({profile: …, bill: …, agenda: …})` 里的三个分组名。"""
    match = re.search(r"bindData\(\{(.*?)\}\)", _js_without_comments(), re.S)
    assert match, (
        f"{APP_JS.name} 里找不到 `bindData({{…}})` 调用。"
        "这个判据靠它认出 data-bind 的顶层分组；调用改名了，下面几条断言就是空转的。"
    )
    return set(re.findall(r"(\w+)\s*:", match.group(1)))


# ---- 从 app_api.py 里读出后端契约 ---------------------------------------------


def _routes() -> dict[str, ast.FunctionDef]:
    """路由字符串 → 处理函数的 AST 节点。

    静态解析而不是 import：import `app_api` 要连库、要 seed 演示数据，
    而这里只想知道「返回的字典里有哪些键」——那是源码里就写着的事实。
    """
    tree = ast.parse(APP_API.read_text(encoding="utf-8"))
    out: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and deco.func.attr in {"get", "post", "put", "delete"}
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
            ):
                out[f"{deco.func.attr.upper()} {deco.args[0].value}"] = node
    return out


def _dict_keys(node: ast.AST) -> set[str]:
    return {
        k.value
        for k in getattr(node, "keys", [])
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _contract(route: str) -> tuple[set[str], set[str]]:
    """(顶层字段, 这个接口里出现过的所有字段)。

    顶层 = 所有 `return {...}` 字面量的键的并集，也就是 `data-bind="bill.X"` 里的 X。
    深层 = 函数体内**任何**字典字面量的键，供 `agenda.next.time` 这种两级路径用
    （`next` 的内容是函数里另一处 `nxt = {...}` 拼的）。

    深层这一步刻意宽松：它抓不出「把 `next.place` 挂到了 `today` 上」这种错配，
    但它抓得出**打错字**——而打错字正是这一条要防的东西（打错的那一处永远空白，
    `bindData` 拿到 `undefined` 就写空串，屏幕上和「后端没这个数据」一模一样）。
    """
    routes = _routes()
    assert route in routes, (
        f"{APP_API.name} 里没有 `{route}` 这个路由了。判据里的 BIND_GROUP_ROUTES "
        f"和后端已经脱节——先确认接口是改名了还是删了。现有路由：{sorted(routes)}"
    )
    fn = routes[route]
    top: set[str] = set()
    deep: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            top |= _dict_keys(node.value)
        if isinstance(node, ast.Dict):
            deep |= _dict_keys(node)
    return top, deep


# ---- 判据 1：十个页面都在，且都加载 app.js -----------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_the_page_exists(page: str) -> None:
    """防的是：页面被删/改名，而所有判据参数化随之缩水，一片安静地全绿。"""
    path = PAGES_DIR / page
    assert path.is_file(), (
        f"{page} 不在 {PAGES_DIR} 里。\n"
        f"  这十个页面是老人端的全部界面，少一个就是一条走不通的路。\n"
        f"  目录里现有：{sorted(p.name for p in PAGES_DIR.glob('*.html'))}"
    )


def test_no_page_escapes_this_gate() -> None:
    """防的就是这一整个文件存在的理由：新加的页面落在判据之外。

    `PAGES` 是写死的。有人新建一个 `settings.html` 而不登记，上面每一条参数化判据
    都不会扫它——和 `💧` 那次一模一样：判据全绿，页面上有违规。这里让「多出来一个
    没登记的页面」本身变成一条红。
    """
    on_disk = {p.name for p in PAGES_DIR.glob("*.html")}
    unlisted = sorted(on_disk - set(PAGES))
    assert not unlisted, (
        f"{PAGES_DIR} 下有 {len(unlisted)} 个页面没有登记进这个判据的 PAGES："
        f"{unlisted}\n"
        "  没登记 = 下面每一条（emoji / data-action / data-bind / 美术文件）都不会扫它。\n"
        "  把文件名加进本文件顶部的 PAGES 列表即可。"
    )


@pytest.mark.parametrize("page", PAGES)
def test_the_page_loads_app_js(page: str) -> None:
    """防的是：漏一行 `<script>`，整页的按钮和数据绑定全是死的。

    `app.js` 一个文件同时负责三件事——底部导航的注入（`mountGlobalNav`）、
    全局点击分发（每一个 `data-action`）、以及数据回填（每一个 `data-bind`）。
    它没加载，页面**看起来完全正常**：静态的版式、图片、文字一个不少，
    只是没有导航栏、按不动、所有绑定位置永远空着。
    """
    srcs = _script_sources(page)
    resolved = {(PAGES_DIR / s).resolve() for s in srcs}
    assert APP_JS.resolve() in resolved, (
        f"{page} 没有加载 assets/js/app.js。\n"
        f"  它现在加载的是：{srcs or '（一个 <script src> 都没有）'}\n"
        "  没有 app.js，这一页的底部导航不会注入、每一个 data-action 按钮按下去"
        "什么都不发生、每一个 data-bind 位置永远空白——而页面截图看不出任何异常。"
    )


# ---- 判据 2：不许出现 emoji ---------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_no_emoji_in_page_text(page: str) -> None:
    """硬约束第七条，作用到新页面上。

    判定与 `test_no_emoji_as_icons.py` 完全一致，理由也一样：
    字形由系统决定（鸿蒙 / iOS / Windows 三种画法）、读屏软件会念出来
    （「放大镜 这件事我准备这样办」）、而且它通常不携带信息。
    """
    text = _visible_html(page)
    hits = []
    for m in _EMOJI.finditer(text):
        around = text[max(0, m.start() - 24): m.end() + 24].replace("\n", " ").strip()
        hits.append(f"U+{ord(m.group()):04X} {m.group()!r} 附近：…{around}…")
    assert not hits, (
        f"{page} 的可见文本里有 {len(hits)} 处 emoji：\n  " + "\n  ".join(hits) + "\n"
        "  硬约束第七条：不用 emoji 当图标。字形由系统决定（三个平台三种画法），"
        "读屏软件会念出来，而且它通常不携带信息。用内联 SVG，或者去掉。\n"
        f"  （`{APP.name}/art/` 下已经有一整套同风格的描边图，优先用那些。）"
    )


def test_the_emoji_rule_is_byte_identical_to_the_old_gate() -> None:
    """防的是：两套页面用两套 emoji 定义，于是「同一条硬约束」悄悄分叉。

    老页面的判据在 `test_no_emoji_as_icons.py`。任务要求这里「用同样的判据」。
    抄一份很容易，让它**保持**一样很难——所以每次跑都重新对一遍源码里的正则。
    那边收紧了（比如把 `→` 也算进去），这边立刻红，而不是继续用老定义放行。
    """
    assert EMOJI_GATE.is_file(), f"找不到老判据 {EMOJI_GATE}，无法确认两边同源"
    tree = ast.parse(EMOJI_GATE.read_text(encoding="utf-8"))
    theirs = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "_EMOJI" for t in node.targets)
            and isinstance(node.value, ast.Call)
        ):
            theirs = ast.literal_eval(node.value.args[0])
    assert theirs is not None, (
        f"{EMOJI_GATE.name} 里已经没有 `_EMOJI = re.compile(...)` 了。"
        "老判据改了结构，这边的副本无从对齐——请一并更新。"
    )
    assert theirs == _EMOJI.pattern, (
        "新页面用的 emoji 判据和老页面的**不一样了**：\n"
        f"  老（{EMOJI_GATE.name}）：{theirs!r}\n"
        f"  新（本文件 _EMOJI）  ：{_EMOJI.pattern!r}\n"
        "  同一条硬约束不能有两个定义。把本文件的 _EMOJI 同步成老判据里那一份。"
    )


# ---- 判据 3：每个 data-action 都要有处理分支 ---------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_every_data_action_has_a_handler(page: str) -> None:
    """防的是：一个按下去什么都不发生的按钮，而屏幕上看不出来。

    `app.js` 的分发器在最后是 `catch(err){…toast("操作失败…")}`，但**没匹配上任何
    分支的 action 根本走不到 catch**——它安安静静地穿过整条 if 链，函数返回，
    没有 toast、没有 console、没有报错。对老人来说就是「这个按钮坏了但没人知道」。
    """
    handled = _handled_actions()
    missing = sorted(
        {(a, line) for a, line in _actions(page) if a not in handled},
        key=lambda x: x[1],
    )
    assert not missing, (
        f"{page} 有 {len(missing)} 个 data-action 在 assets/js/app.js 里没有处理分支：\n  "
        + "\n  ".join(f'第 {line} 行 data-action="{a}"' for a, line in missing)
        + "\n  这些按钮按下去会静默地什么都不发生——不报错、不 toast、不跳转。\n"
        f"  app.js 目前认得的是：{sorted(handled)}"
    )


def test_the_action_scanner_actually_found_the_handlers() -> None:
    """自证：一条「集合差为空」的断言，在提取器返回空集时也会绿。

    这个项目栽过同一类跟头（`test_no_emoji_as_icons.py` 注释里那次虚报）。
    如果 `_handled_actions()` 因为 app.js 改了写法而返回空集，
    上面那条会变成「所有 action 都缺处理分支」——那是变红，尚可发现；
    但如果页面侧的 `_actions()` 返回空，就会**全绿**。两头都钉死。
    """
    handled = _handled_actions()
    assert len(handled) >= 10, f"从 app.js 只解析出 {len(handled)} 个 action，提取器大概没在工作"
    assert {"nav", "back", "teach-back"} <= handled, (
        f"app.js 里连 nav / back / teach-back 都没解析到：{sorted(handled)}"
    )
    # 实测：十页共 77 个 data-action，单页最多 13。门槛 30 卡在两者之间，
    # 所以「只扫到了一两个页面」会红，正常增删按钮不会。
    total = sum(len(_actions(p)) for p in PAGES)
    assert total >= 30, f"十个页面一共只扫到 {total} 个 data-action（实测应为 ~77），扫描器大概没在工作"


# ---- 判据 4：data-bind 的字段必须是后端真的会返回的 ---------------------------


def test_the_bind_groups_are_the_ones_this_gate_knows_about() -> None:
    """防的是：`app.js` 新增了第四个分组，而这条判据对它一无所知却继续全绿。

    `BIND_GROUP_ROUTES` 是本文件手写的「分组 → 接口」映射。它是下一条断言的全部依据，
    一旦和 `app.js` 里 `bindData({...})` 的实际分组脱节，新分组下的所有字段
    就会被下面那条**跳过**（未知分组 = 不检查），静默失去覆盖。
    """
    actual = _bind_groups_in_app_js()
    assert actual == set(BIND_GROUP_ROUTES), (
        f"app.js 的 bindData() 分组是 {sorted(actual)}，"
        f"本判据只认得 {sorted(BIND_GROUP_ROUTES)}。\n"
        "  多出来的分组下的 data-bind 字段现在没有任何人在校验。"
        "请把新分组和它对应的后端路由补进本文件的 BIND_GROUP_ROUTES。"
    )


@pytest.mark.parametrize("page", PAGES)
def test_every_data_bind_field_exists_in_the_backend_contract(page: str) -> None:
    """防的是：字段名打错一个字母，那一处就**永远空白且不报错**。

    `app.js::bindData` 是这么取值的：

        const val = el.dataset.bind.split(".").reduce((o,k)=>(o==null?undefined:o[k]), data);
        el.textContent = (val === undefined || val === null) ? "" : String(val);

    `undefined` 和「后端确实回了 null」走的是同一条路，都写空串。所以
    `data-bind="bill.amoun"` 的表现和「这个月没有账单」一模一样——
    不抛异常、不进 console、截图上就是干净的一片空。

    契约从 `backend/youhuo/app_api.py` 的 AST 里读，不是这里手抄一份白名单。
    """
    top_level = {g: _contract(r) for g, r in BIND_GROUP_ROUTES.items()}
    bad: list[str] = []
    for field, line, _ in _binds(page):
        parts = field.split(".")
        group = parts[0]
        if group not in top_level:
            bad.append(
                f'第 {line} 行 data-bind="{field}"：顶层分组 `{group}` 不是 '
                f"app.js 会装填的三个之一（{sorted(top_level)}），这一处永远取不到值"
            )
            continue
        top, deep = top_level[group]
        if len(parts) >= 2 and parts[1] not in top:
            bad.append(
                f'第 {line} 行 data-bind="{field}"：`{BIND_GROUP_ROUTES[group]}` '
                f"的返回里没有 `{parts[1]}` 这个字段（有的是 {sorted(top)}）"
            )
            continue
        for deeper in parts[2:]:
            if deeper not in deep:
                bad.append(
                    f'第 {line} 行 data-bind="{field}"：`{BIND_GROUP_ROUTES[group]}` '
                    f"整个接口里都没有 `{deeper}` 这个键"
                )
                break
    assert not bad, (
        f"{page} 有 {len(bad)} 处 data-bind 指向后端不会返回的字段：\n  "
        + "\n  ".join(bad)
        + f"\n  这些位置在真机上会**永远空白**，而且不报错——和「今天没有数据」"
        f"长得一模一样。契约在 {APP_API.relative_to(ROOT).as_posix()}。"
    )


def test_the_contract_scanner_actually_read_the_backend() -> None:
    """自证：契约提取器要是解析不出东西，上面那条会「一个字段都不合法」——

    那还好，是红的。但反过来，如果它把**每一个**字段都当成合法（比如 `deep`
    误收成了全模块的键），上面那条就会永远绿。所以这里同时钉住两头：
    真字段必须在，编出来的字段必须不在。
    """
    profile_top, _ = _contract("GET /profile")
    bill_top, _ = _contract("GET /bills/water/current")
    agenda_top, agenda_deep = _contract("GET /agenda")

    # 认得出真的：
    assert {"name", "days", "weather"} <= profile_top, profile_top
    assert {"amount", "company", "accountTail", "paidAt"} <= bill_top, bill_top
    assert {"next", "today"} <= agenda_top, agenda_top
    assert {"time", "title", "place", "note"} <= agenda_deep, agenda_deep
    # 编出来的必须落空（否则这条判据是个橡皮图章）：
    assert "amoun" not in bill_top
    assert "sleepHours" not in profile_top
    assert "hospital" not in agenda_deep


# ---- 判据 5：data-bind 元素里不许留写死的兜底值 -------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_data_bind_elements_carry_no_hardcoded_fallback(page: str) -> None:
    """防的是这个产品最不能犯的错：**接口挂了，屏幕上留着一个看起来正常的假金额。**

    `<b data-bind="bill.amount">68.40</b>` 在真机上有两种命运：
    请求成功 → JS 覆盖成真金额，谁也看不出问题；请求失败或超时 →
    `hydrate()` 的 `catch` 吞掉异常，`bindData` 根本没跑，那个 `68.40` 原样留在屏幕上。
    一位老人对着一个并不存在的账单按下「确认支付」。

    `app.js` 的注释里已经记过这件事的上一轮（「HTML 里那些 "68.40"/"李叔" 的兜底文本
    在请求失败时会原样留在屏幕上」）——那次是靠改 JS 兜的，但 HTML 里再加一个新的
    兜底值依然没有任何东西拦得住。这条就是那个拦。

    正确写法：`<b data-bind="bill.amount"></b>`。空着就是空着。
    """
    bad = [
        (field, line, inner.strip())
        for field, line, inner in _binds(page)
        if inner.strip()
    ]
    assert not bad, (
        f"{page} 有 {len(bad)} 个 data-bind 元素里写死了兜底内容：\n  "
        + "\n  ".join(
            f'第 {line} 行 data-bind="{f}" 里写着 {t[:60]!r}' for f, line, t in bad
        )
        + "\n  接口一挂（hydrate() 的 catch 会静默吞掉异常），这些字就原样留在屏幕上，"
        "看起来和真数据毫无区别。\n"
        '  改成空元素：<b data-bind="bill.amount"></b>。'
    )


# ---- 判据 6：引用的美术文件必须存在 ------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_every_referenced_art_file_exists(page: str) -> None:
    """防的是：一个 404 的 `<img>` 在截图里只是「那块留白是设计」。

    这些页面的视觉几乎全部由 `art/` 下的 PNG 承担（山、云、水纹、印章、图标）。
    浏览器对缺图不吭声，`alt` 又大多是空串（它们是装饰图），所以少一张图的现场
    就是一块和留白难以区分的空。改文件名、挪目录、`.png` 写成 `.webp`——
    这三种改动都不会有任何东西报警。
    """
    missing = [
        (ref, line)
        for ref, line in _art_refs(page)
        if not (PAGES_DIR / ref).is_file()
    ]
    assert not missing, (
        f"{page} 引用了 {len(missing)} 个不存在的美术文件：\n  "
        + "\n  ".join(f"第 {line} 行 {ref}" for ref, line in missing)
        + f"\n  浏览器对缺图不报错，装饰图的 alt 又是空串——现场只是一块留白。\n"
        f"  实际目录：{(APP / 'art').relative_to(ROOT).as_posix()}"
    )


def test_app_js_own_art_references_exist() -> None:
    """`app.js` 自己也引美术文件，而且是**每一页都会用到**的那张。

    `mountGlobalNav()` 往十个页面都注入同一段底部导航，中间那颗语音球是
    `<img src="../art/png/nav_voice_control.png">`。它没了，十个页面的主入口
    同时变成空白——但没有任何一个页面文件里出现过这个路径，所以上面那条按页扫的
    判据一辈子也碰不到它。
    """
    source = _js_without_comments()
    refs = sorted({m.group(0) for m in _ART_REF.finditer(source)})
    assert refs, (
        f"{APP_JS.name} 里一条 ../art/ 引用都没解析到——它至少应该有底部导航的语音球。"
        "提取器或 app.js 的写法变了。"
    )
    missing = [r for r in refs if not (PAGES_DIR / r).is_file()]
    assert not missing, (
        f"assets/js/app.js 引用了 {len(missing)} 个不存在的美术文件：{missing}\n"
        "  它注入到全部十个页面，所以这是十处同时缺图。"
    )


def test_the_art_scanner_actually_found_references() -> None:
    """自证：`_ART_REF` 写错的那天，「缺失列表为空」会变成一条永远绿的断言。"""
    # 实测：十页共 95 条引用，单页最多 26（services.html）。门槛 60 卡在两者之间。
    total = sum(len(_art_refs(p)) for p in PAGES)
    assert total >= 60, f"十个页面一共只扫到 {total} 条 ../art/ 引用（实测应为 ~95），扫描器大概没在工作"
    assert not (PAGES_DIR / "../art/png/这个文件不存在.png").is_file()


# ---- 自证：扫描器读到了东西，而且认得它要找的东西 -----------------------------


def test_the_scan_reads_the_text_and_catches_a_planted_emoji() -> None:
    """一条永远断言「没有」的检查，在正则写错的那一天会继续绿。

    尤其是这一条：`💧` 那次之所以漏，**不是**因为正则不认得 💧，而是因为
    没有任何判据读那个文件。所以这里同时验两件事——读到了内容，且认得内容。

    两个阈值都是**量出来的**，不是拍的（凭记忆拍的阈值会放行它本该拦的那一档）：

      * 实测总量 2834 字符；单页最多 1157（`services.html`）。
        门槛取 1500——正好卡在「只读到了一个页面」（≤1157）和现状（2834）之间，
        所以「参数化缩水成一页」会红，而正常的文案增删不会。
      * 实测单页最少 110 字符（`records.html`），最多 1157。
        门槛取 50——足够低，不会因为某一页删掉两行字就误报；
        足够高，能抓住「某一页的提取返回空」这种局部失效（那才是 💧 那次的形状）。

    注意这些页面的可见文本比老页面短得多（老判据用的是 4000）：它们的字节几乎全是
    行内 `style`，中文又密。这不是提取器漏读，上面的实测分布已经确认过。
    """
    per_page = {p: len(_visible_html(p)) for p in PAGES}
    total = sum(per_page.values())
    assert total > 1500, f"十个页面一共只读到 {total} 个字符（实测应为 ~2834），扫描器大概没在工作"
    thin = {p: n for p, n in per_page.items() if n < 50}
    assert not thin, (
        f"这些页面几乎没读到可见文本：{thin}\n"
        "  单页提取失效不会让上面的 emoji 判据变红——它会安静地通过。"
    )

    # 认得出来的（第一个就是这次漏网的那个）：
    assert _EMOJI.search("💧 这个月的水费")
    assert _EMOJI.search("🔍 这件事我准备这样办")
    assert _EMOJI.search("⚠ 需要您确认")
    assert _EMOJI.search("1️⃣ 第一步")
    assert _EMOJI.search("🛡️ 确认无误后")
    # 不该被抓的（排版符号与中文标点，不是 emoji）：
    assert not _EMOJI.search("在电脑上看完整证明 →")
    assert not _EMOJI.search("「今天没有要办的事」")
    assert not _EMOJI.search("68.40 元 · 已办好")


def test_the_bind_scanner_actually_found_the_bindings() -> None:
    """自证：`_binds()` 返回空列表的话，上面两条 data-bind 判据都会全绿。"""
    # 实测：十页共 29 个 data-bind，单页最多 8（home.html），三页一个都没有。
    # 门槛 20 卡在 8 和 29 之间。
    total = sum(len(_binds(p)) for p in PAGES)
    assert total >= 20, f"十个页面一共只扫到 {total} 个 data-bind（实测应为 29），扫描器大概没在工作"
    # 解析器要真的能取到标签之间的文字，否则「兜底值」那条判据永远抓不到东西。
    parser = _BindCollector()
    parser.feed(
        '<div><b data-bind="bill.amount">68.40</b>'
        '<i data-bind="bill.company"></i>'
        '<p data-bind="profile.name"><span>李叔</span></p></div>'
    )
    got = {f: t.strip() for f, _, t in parser.found}
    assert got == {"bill.amount": "68.40", "bill.company": "", "profile.name": "李叔"}, got
