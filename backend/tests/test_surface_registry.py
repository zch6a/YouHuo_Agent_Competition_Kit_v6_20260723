"""三个产品表面的登记表必须和真实的 app 一致。

七条路由的字面量原先散在 **8 个文件**里各写一遍，没有共享源，而 `/stage` 已经在
**四处**被漏掉（`api.py:152` 的锁豁免、`test_mobile_reachability.py:36`、
`test_pwa_shell.py:739` 与 `:782`）。后果不是报错，是**静默地不覆盖**——
那一页在那几道闸门下从来没有被检查过，而结果看起来和通过一模一样。

这份文件让「路由清单」只有一个来源（`youhuo.surfaces.SURFACES`），并且钉住它和
FastAPI 真正注册的东西相等。加一条新路由而忘了登记，这里会红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from youhuo.surfaces import PAGE_TO_ROUTE, ROUTES, SURFACES, surface_of

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"


def _html_routes_from_app() -> set[str]:
    """app 上真正注册的、返回 HTML 页面的 GET 路由。

    判据是「这条路由的处理函数返回一个 `.html` 文件」，而不是一张手写名单——
    否则这条测试就变成了它要防的那个东西。
    """
    from youhuo.api import create_app

    app = create_app()
    api_source = (ROOT / "backend" / "youhuo" / "api.py").read_text(encoding="utf-8")

    routes: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods or not path.startswith("/") or path.startswith("/static"):
            continue
        name = getattr(route, "name", "")
        if not name:
            continue
        # 处理函数体里出现 `xxx.html` 才算 HTML 页面路由。
        #
        # 窗口必须**在下一个装饰器处截断**。第一版取了 def 之后 400 个字符，
        # 结果窜进了下一个函数，把返回 `.webmanifest` 的 `/manifest.webmanifest`
        # 也算成了 HTML 页面——一条边界画错的探针，报出来的差异是它自己造的。
        start = api_source.find(f"def {name}(")
        if start < 0:
            continue
        rest = api_source[start:]
        end = rest.find("@app.", 1)
        body = rest[: end if end > 0 else len(rest)]
        if re.search(r"[\w-]+\.html", body):
            routes.add(path)
    return routes


def test_the_registry_matches_the_routes_the_app_actually_serves() -> None:
    actual = _html_routes_from_app()
    assert actual, (
        "一条 HTML 路由都没识别出来——这条测试正在空转。"
        "`api.py` 里返回页面的写法变了就要改 `_html_routes_from_app`，不要让它静默通过。"
    )
    declared = set(ROUTES)
    assert actual == declared, (
        f"登记表与 app 不一致。\n"
        f"  app 有而表里没有：{sorted(actual - declared)}\n"
        f"  表里有而 app 没有：{sorted(declared - actual)}\n"
        "  加路由只改 `youhuo/surfaces.py`，其余地方从它导入。"
    )


def test_every_declared_page_file_exists() -> None:
    for route, info in SURFACES.items():
        assert (STATIC / info.page).is_file(), f"{route} 指向的 {info.page} 不存在"


def test_the_three_surfaces_are_all_populated() -> None:
    """三个表面都不能是空的。

    反向断言：如果有人把所有页面都归进 `consumer`，上面那条相等断言照样绿，
    而三表面架构其实已经塌成一个了。
    """
    by_surface: dict[str, list[str]] = {}
    for route, info in SURFACES.items():
        by_surface.setdefault(info.surface, []).append(route)
    for surface in ("consumer", "presentation", "professional"):
        assert by_surface.get(surface), f"{surface} 这个表面下一条路由都没有"


def test_consumer_has_exactly_two_shells() -> None:
    """Consumer 侧只允许两个 App Shell，这是本轮的核心约束。

    `entry` 这一层不算 shell：`/family` `/care` `/trust` 是同一个 family shell 的
    三个 deep link，不是三套壳。`/` 是入口页，单独一个 shell。
    """
    shells = {info.shell for info in SURFACES.values() if info.surface == "consumer"}
    assert shells == {"elder", "family", "entry"}, (
        f"Consumer 侧的 shell 是 {sorted(shells)}，"
        "而本轮只允许 elder + family 两个 App Shell（外加入口页 entry）"
    )


def test_the_body_attribute_agrees_with_the_registry() -> None:
    """每一页 `<body data-surface>` 必须和登记表说的一致。

    这一条把 Python 侧的登记表和 HTML 侧的实际标记对上。两边分别正确但互相不一致，
    是这个项目最熟悉的失败形状。
    """
    mismatched: list[str] = []
    for route, info in SURFACES.items():
        html = (STATIC / info.page).read_text(encoding="utf-8")
        hit = re.search(r"<body[^>]*\bdata-surface=\"([\w-]+)\"", html)
        got = hit.group(1) if hit else "（没有 data-surface）"
        if got != info.surface:
            mismatched.append(f"{route}（{info.page}）标的是 {got}，登记表说 {info.surface}")
    assert not mismatched, "以下页面的 data-surface 与登记表不符：\n  " + "\n  ".join(mismatched)


@pytest.mark.parametrize("page", sorted(PAGE_TO_ROUTE))
def test_surface_of_accepts_both_spellings(page: str) -> None:
    """`surface_of()` 同时吃 `/elder` 和 `elder.html`，省得每个调用方各自转换。

    八个调用方各写一遍转换，就会有八个版本各自正确、各自不同——这个项目已经因为
    「同一件事写五遍」吃过亏（五份分叉的 `api()` / `login()` / `resolveIdentity()`）。
    """
    assert surface_of(page) is surface_of(PAGE_TO_ROUTE[page])
