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
    "/trust":  RouteSurface("consumer",     "family",   "care",  "trust.html"),
    "/stage":  RouteSurface("presentation", "stage",    None,   "stage.html"),
    "/judge":  RouteSurface("professional", "evidence", None,   "judge.html"),
}

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
