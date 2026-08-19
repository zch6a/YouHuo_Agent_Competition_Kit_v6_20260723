"""三个产品表面，以及每条路由属于哪一个。

## Surface describes user intent, not URL

七个 URL 保留不变，但它们不再等于七个一级产品页面。`/family` `/care` `/trust`
**都属于同一个 Surface、同一个 Shell**——它们是同一个 App 的不同 deep link，
不是三个网站。

    Route  →  Surface  →  Shell  →  Module  →  Panel

    /trust  →  consumer      →  family    →  transaction       →  receipt
    /judge  →  professional  →  evidence  →  transaction audit →  timeline

**不许把 `URL == Surface` 写回测试里。** 那正是这次重构要拆掉的东西。

## 为什么要有这个文件

七条路由的字面量原先散在 **8 个文件**里各写一遍，没有共享源：

    api.py:248-295        七个 FileResponse
    api.py:152            _LOCK_EXEMPT_PATHS      ← 已漏掉 /stage
    static/sw.js          SHELL 数组
    scripts/check_page_runtime.py:52
    scripts/check_contrast.py:27
    scripts/check_layout_stability.py:47
    scripts/shoot_pages.py:71
    tests/test_mobile_reachability.py:36           ← 已漏掉 /stage
    tests/test_pwa_shell.py:97 / :739 / :782       ← 739 与 782 已漏掉 /stage

`/stage` 已经在四处被漏掉。加一个新表面而不改这八处，多数闸门会**静默地不覆盖它**
——正是 `test_app_surface_speaks_no_engineering.py:66-69` 批评过的"手写表会漂"。
"""
from __future__ import annotations

from typing import Literal, NamedTuple

Surface = Literal["consumer", "presentation", "professional"]
#: `app` 是山水版老人端那一套（`backend/static/app/`）。
#:
#: 它必须是**自己的 shell**，不能塞进现有任何一个：
#:   · 记成 `entry` → 门厅专属的断言会套上来（要求有 `.landing-demo` 那两道门），
#:     而它是 App 主页不是门，那条断言对它没有意义。我第一版就是这么错的。
#:   · 记成 `elder` → 老人端 shell 的断言要求四格标签栏，而它是五槽（中间是语音）。
#: 一个页面属于哪个 shell，决定了哪一批判据会作用在它身上——这个字段不是标签，
#: 是选择器。
Shell = Literal["elder", "family", "stage", "evidence", "entry", "app"]


class RouteSurface(NamedTuple):
    surface: Surface
    shell: Shell
    #: 这一页在它那个 Shell 里是哪一格。`None` = 它就是 Shell 的根。
    entry: str | None
    page: str


#: 唯一的事实源。加路由只改这里。
SURFACES: dict[str, RouteSurface] = {
    "/":       RouteSurface("consumer",     "entry",    None,   "index.html"),
    "/elder":  RouteSurface("consumer",     "elder",    None,   "elder.html"),
    # 老人端**设计二**。和 `/elder` 并行，共用同一份 `elder.js`。
    # shell 仍是 `elder`：surface 描述的是意图不是 URL，而这两页服务的是同一个人、
    # 同一套四格（首页 / 记录 / 家人 / 我的）。归进别的 shell 会让老人端那一批
    # 判据整批绕开它——「掉出所有名单」和「通过」在结果里长得一模一样。
    "/elder2": RouteSurface("consumer",     "elder",    None,   "elder-v6.html"),
    "/family": RouteSurface("consumer",     "family",   "today", "family.html"),
    # 家人端**设计二**。和 `/family` 并行，供比较；业务逻辑共用 family.js/care.js。
    #
    # 它是**四屏合一**的壳（今天/待办/照护/我的都在一个文档里），而设计一把照护
    # 拆到独立的 `/care`。所以它的 entry 是 `today`、shell 仍是 `family`——
    # surface 描述的是意图，不是 URL，这一点是这个文件开头就写明的。
    "/family2": RouteSurface("consumer",    "family",   "today", "family-v6.html"),
    # `/care` 与 `/trust` 是 family shell 的两个 deep link，不是独立网站。
    "/care":   RouteSurface("consumer",     "family",   "care",  "care.html"),
    # `/trust` 的 entry 原先写的是 `"care"`，和这个文件**自己第 11 行的文档**矛盾
    # （那里写的是 `/trust → family → transaction → receipt`）。照护和一张事务凭证
    # 不是一件事，标成「照护」会让底部导航指着一个和这一页无关的格子。
    #
    # 凭证属于**待办**：`09_consumer_app_architecture.md` 把待办定义成
    # 「待我确认 / 进行中 / 已完成」，一笔办完的事就在那里面。
    "/trust":  RouteSurface("consumer",     "family",   "todo",  "trust.html"),
    # 山水版老人端。它是**另一套前端**（`backend/static/app/`），有自己的十个页面、
    # 自己的样式与脚本，通过 `/api/v1` 门面接同一个后端。
    #
    # 为什么也登记在这里：这张表是「app 真正在服务哪些路由」的唯一事实源，
    # `test_surface_registry` 拿它和实际路由逐条对，漏登记就报红——而那正是它抓到
    # 这一条的原因。它归 consumer 表面（读它的是老人本人），shell 是它自己的 `app`
    # ——见上面 `Shell` 那段：shell 决定哪一批判据作用在它身上，塞进 `entry` 或
    # `elder` 都会把不适用的断言套上来。
    "/app":    RouteSurface("consumer",     "app",      None,   "app/pages/home.html"),
    "/stage":  RouteSurface("presentation", "stage",    None,   "stage.html"),
    "/judge":  RouteSurface("professional", "evidence", None,   "judge.html"),
}

#: 每条路由的**默认分区名**（`data-panel` 的值），`None` = 这一页没有分区。
#:
#: 为什么单独一张表：`RouteSurface.entry` 是**导航格名**，`data-panel` 是**分区名**，
#: 两者是不同的命名空间。`/care` 的 entry 是 `care`，而它的默认分区叫 `today`——
#: 把这两个当成一个，就会算出 `#care` 这个不存在的锚点（那个 bug 真的发生过，
#: 见 `href_from()`）。`/family` 那边两者恰好都是 `today`，所以它掩盖了这件事。
DEFAULT_PANEL: dict[str, str | None] = {
    "/":       None,
    "/elder":  "home",
    "/elder2": "home",
    "/family": "today",
    "/family2": "today",
    "/care":   "today",
    "/trust":  None,    # 一张凭证没有分区
    "/stage":  "product",
    "/judge":  None,
}


class NavItem(NamedTuple):
    #: 这一格在 shell 里的名字。和 `RouteSurface.entry` 是同一套词。
    entry: str
    #: 给人看的字。四个字以内——底部四格，再长就折行。
    label: str
    #: **哪个文档承载这一格**。
    #:
    #: 不写成 `href`：那样会漏掉一半情况。从 `/care` 上点「待办」不可能是页内切换——
    #: `/care` 根本没有 `todo` 那个面板。所以链接目标取决于**你现在在哪个文档**：
    #: 承载它的文档就是自己 ⇒ 页内切换（`#panel`）；不是自己 ⇒ 跨文档
    #: （`owner#panel`）。`href_from()` 算这件事。
    owner: str
    #: 这一格在**它的 owner 文档里**对应哪个 `data-panel`。
    #:
    #: 和 `entry` 分开，因为它们是两个命名空间：「照护」这一格的 entry 是 `care`
    #: （shell 里的格名），而它在 `care.html` 里落到的分区是 `today`。
    #: hash 必须命名分区——`initSections` 拿 hash 去找 `[data-panel]`。
    panel: str


#: Family App 的底部导航，**四项，永远四项**。
#:
#: 为什么定义在这里：`09_consumer_app_architecture.md` 记着一次真实事故——
#: 底部导航条目数在页面之间变（elder 4 项、family/care 3 项、trust 无），
#: 而三份 markup 各写一遍必然漂。这里是那份唯一的清单，闸门拿它核对三个文档。
#:
#: **为什么仍然是三份 markup，而不是用 JS 渲染一份。**
#: 参考产品研究的结论是「导航定义一次，写成 JS 数组渲染进三个文档」
#: （Folk Care 的三套导航都是声明式数据数组）。但那和 Phase C 的判据 ① 冲突：
#: 导航必须在**服务器发出的 HTML** 里就带好正确的激活态。JS 渲染整条导航的话，
#: 首屏会先闪一下「没有导航」——比闪错激活项更糟，那是布局跳动。
#: 而这个项目没有构建步骤、也不做服务端模板（不迁移技术栈）。
#: 所以：markup 复制三份，**由闸门保证它们一致**——漂移才是「定义一次」真正要
#: 解决的风险，而闸门直接解决它。
FAMILY_NAV: tuple[NavItem, ...] = (
    NavItem("today", "今天", "/family", "today"),
    NavItem("todo", "待办", "/family", "todo"),
    # entry 是 `care`，落点是 care.html 的 `today` 分区——这一对不同名的值就是
    # 上面 `panel` 那段注释说的两个命名空间。
    NavItem("care", "照护", "/care", "today"),
    NavItem("mine", "我的", "/family", "mine"),
)


def href_from(item: NavItem, current_route: str) -> str:
    """站在 `current_route` 这一页，这一格的链接该写什么。

    **hash 里写的一律是 `item.panel`（分区名），不是 `item.entry`（导航格名）。**
    这两个曾经被当成一个，代价是「照护」被算成 `#care`——而 `care.html` 根本没有叫
    `care` 的分区（它的分区是 today/med/body/mood/safety/trend）。那个 hash 会让
    `initSections` 退回默认分区，或者更糟：被 `resolve()` 的 id 兜底解析成别的东西。
    `/family` 那边 entry 与 panel 恰好都叫 `today`，所以这个错误只在 `/care` 一条
    路径上显形，三份 markup 各写一遍时谁也不会去核对。
    `test_every_nav_cell_lands_somewhere_real` 现在钉住它。

    三条规则：

    ① 承载它的文档就是当前这一页 ⇒ 写 `#panel`，**页内切换**。
       不写裸路由：那会整页重载，而用户点的是同一个文档里的另一个分区——
       重载会丢掉滚动位置、重跑一遍所有请求。
    ② 跨文档、而且这一格就是那个文档的**默认分区** ⇒ 写裸路由，不带 hash。
    ③ 跨文档、不是默认分区 ⇒ 写 `owner#panel`。不带 hash 会落到那个文档的
       默认分区，而用户点的是「待办」。
    """
    if item.owner == current_route:
        return f"#{item.panel}"
    if item.panel == DEFAULT_PANEL.get(item.owner):
        return item.owner
    return f"{item.owner}#{item.panel}"


def nav_for(current_route: str) -> tuple[tuple[NavItem, str, bool], ...]:
    """这一页的底部四格：`(项, href, 是不是当前项)`。

    「是不是当前项」按 `SURFACES[route].entry` 判，不按 URL——`/trust` 的 entry 是
    `todo`，所以站在一张凭证上时高亮的是「待办」，那是它真正所属的模块。
    """
    here = SURFACES[current_route].entry
    return tuple((item, href_from(item, current_route), item.entry == here)
                 for item in FAMILY_NAV)

#: 反查：文件名 → 路由。清单脚本按文件遍历，需要这个方向。
PAGE_TO_ROUTE: dict[str, str] = {info.page: route for route, info in SURFACES.items()}

ROUTES: tuple[str, ...] = tuple(SURFACES)
PAGES: tuple[str, ...] = tuple(info.page for info in SURFACES.values())


def surface_of(page_or_route: str) -> RouteSurface:
    """接受 `/elder` 或 `elder.html` 两种写法，省得每个调用方各自转换。"""
    if page_or_route in SURFACES:
        return SURFACES[page_or_route]
    route = PAGE_TO_ROUTE.get(page_or_route)
    if route is not None:
        return SURFACES[route]
    # 山水版那一套的**内部页面**。
    #
    # `app/pages/*.html` 有十七个，但它们不是十七个路由——它们全都住在 `/app`
    # 这一个 shell 里，靠 `app.js` 的 `ROUTES` 互相跳转。所以它们共享 `/app`
    # 的 surface 与 shell，`entry` 记成各自的文件名（那才是它们彼此的区别）。
    #
    # 为什么不把它们逐个登记进 `SURFACES`：那张表记的是**服务器发得出的路由**，
    # 有一批闸门按它遍历去真的访问 URL。登记进去等于声称有十七个 URL 入口，
    # 而实际只有 `/app` 一个——那些闸门会去敲十六个 404，然后把 404 报成产品缺陷。
    if page_or_route.startswith("app/pages/") and page_or_route.endswith(".html"):
        base = SURFACES["/app"]
        return RouteSurface(base.surface, base.shell,
                            page_or_route.rsplit("/", 1)[-1][: -len(".html")],
                            page_or_route)
    raise KeyError(f"{page_or_route!r} 不在 SURFACES 里——新页面要先在这里登记")
