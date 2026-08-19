"""service worker 不许缓存任何「权威状态」的读。

## 这道门为什么必须是「从路由表推出来」的

`sw.js` 里 `isApi()` 那段注释写着：

    Matching /v\\d+/ means a future version cannot reintroduce the bug by being
    forgotten here.

那句话是在 `/v7/*` 整层漏掉之后写的。而它**还是又发生了一次**：`/api/v1`
（老人端门面，50 个端点）以 `/api/` 开头，`^\\/(v\\d+|…)` 一个都不匹配，
于是整层被当外壳缓存，走 stale-while-revalidate。

实测（同一个访客、真实状态 59 → 59 → 0）：

    GET /api/v1/privacy/data     →  0     ← 上一次的
    POST erase/preview           →  59    ← POST 不走缓存，是真的
    POST erase                   →  真删了 59 条（库里核实过）
    GET /api/v1/privacy/data     →  59    ← 又是上一次的

屏幕上：老人删完自己的数据，页面告诉他一条都没删。

**一条写在注释里的规则挡不住这类回归**，因为下一层 API 的前缀是什么，
写注释的人不知道。所以这道门不读注释、也不硬编码前缀清单——
它从 `app.routes` 拿到**这个应用实际在服务的每一条 API 路由**，
逐条问 `isApi()` 认不认。加一层新 API 而忘了改 `isApi()`，它当场红。
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest

SW = Path(__file__).resolve().parents[1] / "static" / "sw.js"


def _is_api_pattern() -> re.Pattern[str]:
    """把 `sw.js` 里那个正则原样搬到 Python 里。

    **不重写一份等价的**：重写的那份和真正跑在浏览器里的那份会分叉，
    而分叉的方向恰好是「测试绿、线上漏」。这个项目为「同一件事两处实现」
    付过代价（字号语速和 SOS 各有两套，两边各自往返都绿，跨子系统才红）。
    """
    src = io.open(SW, encoding="utf-8").read()
    m = re.search(r"function isApi\(url\)\s*\{\s*return\s*/(.+?)/\.test", src, re.S)
    assert m, "sw.js 里找不到 isApi() 的正则——它被改写了，这道门要跟着改"
    # JS 正则里的 `\/` 在 Python 里就是 `/`
    return re.compile(m.group(1).replace(r"\/", "/"))


def _api_routes() -> list[str]:
    """这个应用**实际在服务**的 API 路由，从路由表拿，不从源码猜。"""
    os.environ.setdefault("YOUHUO_DEMO_STATE", "empty")
    from youhuo.api import create_app

    app = create_app()
    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
        if not methods or not path.startswith("/"):
            continue
        # 页面路由和静态资源不是 API，它们**本来就该**被缓存——
        # 那是这个 worker 存在的理由（地铁上也能翻）。
        if path in {"/", "/elder", "/elder2", "/elder3", "/family", "/family2",
                    "/family3", "/care", "/trust", "/judge", "/stage", "/app"}:
            continue
        # 带后缀的都是静态文件，哪怕它是用一条路由发出去的
        # （`/favicon.ico`、`/sw.js`、`/manifest.webmanifest` 都是）。
        # 它们**本来就该**被缓存——那正是这个 worker 存在的理由。
        #
        # 判据用「末段带不带点」而不是列一张名单：名单会漏，
        # 而这道门存在的全部理由就是「上一次靠人记的名单漏了一整层」。
        #
        # 不写 `\.\w{2,5}$`：`/manifest.webmanifest` 的后缀有 11 个字符，
        # 会被那个上限漏掉——我第一版就是这么写的，它当场把 manifest 报成了
        # 「权威状态」。一个为了防漏而写的判据，自己先漏了一个。
        if path.startswith("/static") or "." in path.rsplit("/", 1)[-1]:
            continue
        out.append(path)
    return sorted(set(out))


def test_every_api_route_the_app_serves_is_excluded_from_the_cache() -> None:
    pattern = _is_api_pattern()
    leaked = [p for p in _api_routes() if not pattern.match(p)]
    assert not leaked, (
        f"这些 API 路由会被 service worker 当外壳缓存（共 {len(leaked)} 条）：\n  "
        + "\n  ".join(leaked[:20])
        + ("\n  …" if len(leaked) > 20 else "")
        + "\n\n  它们返回的是权威状态。stale-while-revalidate 会先把**上一次的响应**"
          "\n  交出去——老人删完自己的数据，页面会告诉他一条都没删。"
          "\n  改 `sw.js` 的 `isApi()` 把这一层加进去，**并且升 VERSION**："
          "\n  activate 只删 key 不等于 VERSION 的缓存，不升就救不回已经装好的那批。"
    )


def test_the_shell_never_lists_an_api_route() -> None:
    """外壳清单里不许出现 API 路由。

    上面那条守的是**运行时**（`isApi()` 会不会把它放行到缓存）；这条守的是
    **安装时**。两条都要：`install` 阶段的 `cache.add(url)` 不经过 `isApi()`，
    所以哪怕运行时判对了，一条写进 `SHELL` 的 API 路由照样会在装机那一刻被
    缓存下来，然后被 `caches.match` 命中。

    ── 这里原本还有第三条断言，已经删掉，理由值得留下 ──

    那一条查「版本号上面那段注释提没提 `isApi`」。变异测试证明它是假门：
    `head` 是 `const VERSION` 之前的**全部内容**，而 v8 那段更老的注释里
    本来就写着「改了 isApi() 也救不回已经装好的那批」——一条无关的旧注释
    就能满足它，把最新那条注释改成「改了点东西」它照样绿。

    「一段注释是否解释了一次改动」不是机器能判的事。留着它只会让这个文件
    看起来有三道门而其实有两道，而那比只有两道更危险。
    """
    src = io.open(SW, encoding="utf-8").read()
    shell = re.search(r"const SHELL = \[(.*?)\];", src, re.S)
    assert shell, "sw.js 里找不到 SHELL 清单"
    pattern = _is_api_pattern()
    listed = re.findall(r"'([^']+)'", shell.group(1))
    leaked = [u for u in listed if pattern.match(u)]
    assert not leaked, (
        "外壳清单里列了 API 路由：" + "、".join(leaked)
        + "\n  `install` 的 `cache.add()` 不经过 `isApi()`——写进清单就是"
          "\n  在装机那一刻把权威状态缓存下来，之后每次都会被 caches.match 命中。")
