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
Shell = Literal["elder", "family", "stage", "evidence", "entry"]


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
    "/family": RouteSurface("consumer",     "family",   "today", "family.html"),
    # `/care` 与 `/trust` 是 family shell 的两个 deep link，不是独立网站。
    "/care":   RouteSurface("consumer",     "family",   "care",  "care.html"),
    # `/trust` 的 entry 原先写的是 `"care"`，和这个文件**自己第 11 行的文档**矛盾
    # （那里写的是 `/trust → family → transaction → receipt`）。照护和一张事务凭证
    # 不是一件事，标成「照护」会让底部导航指着一个和这一页无关的格子。
    #
    # 凭证属于**待办**：`09_consumer_app_architecture.md` 把待办定义成
    # 「待我确认 / 进行中 / 已完成」，一笔办完的事就在那里面。
    "/trust":  RouteSurface("consumer",     "family",   "todo",  "trust.html"),
    "/stage":  RouteSurface("presentation", "stage",    None,   "stage.html"),
    "/judge":  RouteSurface("professional", "evidence", None,   "judge.html"),
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
    #: 承载它的文档就是自己 ⇒ 页内切换（`#entry`）；不是自己 ⇒ 跨文档
    #: （`owner#entry`）。`href_from()` 算这件事。
    owner: str


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
    NavItem("today", "今天", "/family"),
    NavItem("todo", "待办", "/family"),
    NavItem("care", "照护", "/care"),
    NavItem("mine", "我的", "/family"),
)


def href_from(item: NavItem, current_route: str) -> str:
    """站在 `current_route` 这一页，这一格的链接该写什么。

    两条规则，顺序要紧：

    ① 这一格就是承载它那个文档的**默认分区** ⇒ 写裸路由，不带 hash。
       这一条不只是为了好看。第一版没有它，于是「照护」被算成 `/care#care`——
       而 `/care` **没有**叫 `care` 的面板（它的面板是 today/med/body/mood/safety），
       那个 hash 会让 `initSections` 退回默认分区，或者更糟：被 `resolve()` 的
       id 兜底解析成别的东西。同一条规则顺带覆盖了 `/family` 的 `today`。
    ② 否则：承载它的文档是自己就写 `#entry`（页内切换），不是自己就写
       `owner#entry`（跨文档，并且带上 hash——不带会落到那个文档的默认分区，
       而用户点的是「待办」）。
    """
    if item.entry == SURFACES[item.owner].entry:
        return f"#{item.entry}" if item.owner == current_route else item.owner
    if item.owner == current_route:
        return f"#{item.entry}"
    return f"{item.owner}#{item.entry}"


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
    if route is None:
        raise KeyError(f"{page_or_route!r} 不在 SURFACES 里——新页面要先在这里登记")
    return SURFACES[route]
