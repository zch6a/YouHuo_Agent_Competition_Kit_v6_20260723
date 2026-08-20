"""前端写死的每一条接口路径，`app.routes` 上都要有。

## 这条判据是从我自己犯的两个错来的

    elder3.js   reminderAction(id, 'done')            真名是 complete   → 404
    family3.js  /v2/reminders/{id}/cancel             它在 /api/v1 上   → 404

两个都是「看起来完全正常」的错：控件绑了、监听跑了、请求发出去了，
只有服务器那一头回 404，而回执被 `catch` 吃成一句温和的中文。
死控件巡检也抓不到——它点的是第一步，第二步的按钮根本没被点到。
**「这一屏没有死控件」和「这一屏每个动作都成立」是两件事。**

## 为什么从 `test_design_three_is_wired.py` 挪到这里

原来那一条只扫 `elder3.js` / `family3.js`。同样的错在 `elder.js`（设计一二
共用，86 KB，全仓最大的接线）里一样会发生，而它不在扫描范围内——
一个按文件名手工维护的范围，是这个项目栽过的坑（Gate 1-3 参数化在一个
手工维护的状态字段上，只跑到 28 个组件里的 1 个，全绿）。

所以这里**不列文件名**：`static/*.js` 全扫。新加一份接线自动进范围。

## 两条，缺一不可

第二条（`test_the_parser_sees_every_api_call`）钉的是**仪器自己的盲区**。
第一条只认得字面量；写成 `api(url)` 就整条溜过去，而**溜过去和通过在
汇总里长得一模一样**。所以任何一个第一参数不是字面量的 `api()` 调用，
都要让这条判据变红——绕过检查必须是一件要显式承认的事。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "static"

# `api` 这个名字本身的定义/转发处。第一参数是形参 `path`，不是路径。
_FORWARDS = "path"

# `${cond ? 'a' : 'b'}` —— 两个分支都要展开。
# 不展开的话它退化成 `X`，而 `X` 配不上任何一条路由的字面段，
# 于是一个**完全正确**的写法会被报成缺陷（我第一版就是这样）。
_TERNARY = re.compile(
    r"""\$\{[^{}]*\?\s*(['"])([^'"]+)\1\s*:\s*(['"])([^'"]+)\3\s*\}""")


def _src(name: str) -> str:
    """读一份脚本，**先剥注释**。

    这些文件的注释里逐字写着 `/v2/reminders/{id}/done` 这类**已知是错的**
    路径（那是在解释缺陷长什么样）。不剥的话这条判据会去检查自己的说明文档，
    然后正确地报一堆假缺陷。
    """
    text = io.open(STATIC / name, encoding="utf-8").read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.M)


def _wiring() -> list[str]:
    names = sorted(p.name for p in STATIC.glob("*.js"))
    assert names, "static 下一个 .js 都没有——这条判据在空转"
    return names


def _literals(js: str) -> list[str]:
    """每一处 `api(<字面量>` 的原始路径。

    分三种引号各写一条，**不是**一条 `[^`'"]+` 通吃：模板字面量里
    合法地含 `'`（`${approve ? 'approve' : 'decline'}`），通吃的那种写法
    会在第一个 `'` 处截断，把半截路径拿去比对。
    """
    out = []
    for m in re.finditer(r"""api\(\s*(?:`(/[^`]*)`|'(/[^']*)'|"(/[^"]*)")""", js):
        out.append(m.group(1) or m.group(2) or m.group(3))
    return out


def _expand(raw: str, actions: set[str]) -> list[str]:
    """一条原始字面量 → 它能产生的每一条具体路径。"""
    paths = [raw]
    while True:
        grew, changed = [], False
        for p in paths:
            m = _TERNARY.search(p)
            if not m:
                grew.append(p)
                continue
            changed = True
            grew.append(p[: m.start()] + m.group(2) + p[m.end():])
            grew.append(p[: m.start()] + m.group(4) + p[m.end():])
        paths = grew
        if not changed:
            break

    # `/v2/reminders/${id}/${action}` 的动作名是变量。用同一份文件里
    # `reminderAction(id, '…')` 传进去的字面量展开——**恰恰是写错动作名
    # 这一类**否则会溜掉，而那正是这条判据存在的理由。
    if actions:
        grew = []
        for p in paths:
            if p.endswith("${action}"):
                grew += [p[: -len("${action}")] + a for a in sorted(actions)]
            else:
                grew.append(p)
        paths = grew

    return [re.sub(r"\$\{[^}]*\}", "X", p).split("?")[0] for p in paths]


@pytest.fixture()
def routes(tmp_path) -> list[str]:
    from youhuo.api import create_app

    app = create_app(tmp_path / "routes.db", demo_mode=True)
    paths = [r.path for r in app.routes if getattr(r, "path", "")]
    assert paths, "一条路由都没数到——这条判据在空转"
    return paths


def _known(routes: list[str], path: str) -> bool:
    want = [p for p in path.strip("/").split("/") if p]
    for r in routes:
        have = [p for p in r.strip("/").split("/") if p]
        if len(have) != len(want):
            continue
        if all(h.startswith("{") or h == w for h, w in zip(have, want)):
            return True
    return False


def test_every_endpoint_the_wiring_calls_really_exists(routes) -> None:
    bad: list[str] = []
    seen = 0
    for name in _wiring():
        js = _src(name)
        actions = set(re.findall(r"reminderAction\([^,]+,\s*'(\w+)'", js))
        if name in ("elder.js", "elder3.js"):
            # 这两份都有 `/v2/reminders/${id}/${action}`。数不到动作名的话，
            # 那条路径会退化成 `/v2/reminders/X/X`——而 `X` 配不上任何路由，
            # 于是它会**红在错误的理由上**，掩盖「动作名写错了」这一类。
            assert actions, f"{name} 里一个 `reminderAction(id, '…')` 都没数到——展开这一段在空转"
        for raw in _literals(js):
            for path in _expand(raw, actions):
                seen += 1
                if not _known(routes, path):
                    bad.append(
                        f"{name}: {path}" + (f"（来自 {raw}）" if path != raw else ""))
    assert not bad, "接线里这些路径在 `app.routes` 上不存在：\n  " + "\n  ".join(bad)
    # 数量下限：低于这个数说明抽取器坏了，而坏掉的抽取器也是「0 个不存在」。
    assert seen >= 100, f"只抽到 {seen} 条路径，抽取器多半坏了"


def test_the_parser_sees_every_api_call() -> None:
    """任何一个第一参数不是字面量的 `api()` 调用都要让这条变红。

    上面那条只认得字面量。`const u = …; api(u)` 会**整条溜过去**，
    而溜过去和通过在汇总里长得一模一样——这个项目已经因为
    「没测到被当成通过」栽过一次（死控件巡检 10 个被静默跳过，
    汇总显示「死控件 0」）。
    """
    dynamic: list[str] = []
    for name in _wiring():
        js = _src(name)
        for m in re.finditer(r"\bapi\(\s*", js):
            head = js[: m.start()]
            if head.rstrip().endswith("function"):
                continue                      # 定义处，不是调用
            rest = js[m.end():]
            if rest[:1] in ("`", "'", '"'):
                continue                      # 字面量，上面那条管
            if re.match(rf"{_FORWARDS}\b", rest):
                continue                      # 转发处：`api(path, options, 'elder')`
            line = js[: m.start()].count("\n") + 1
            dynamic.append(f"{name}:{line} api({rest[:40].splitlines()[0]}…")
    assert not dynamic, (
        "这些 `api()` 调用的路径不是字面量，上面那条判据看不见它们：\n  "
        + "\n  ".join(dynamic)
        + "\n改成字面量，或者在这里显式记一笔为什么不能。")


def test_the_pending_medication_flow_is_wired(routes) -> None:
    """「家人加的药等老人点头」这三个端点，老人端**真的有人在调**。

    它们是补齐的，补完之后全仓没有任何前端调用——端点齐了，流程还是断的，
    而两边界面都正常：女儿加的钙片永远停在待确认，老人看不见也点不了。
    「端点存在」和「这条流程通了」是两件事，这条钉的是后者。

    两份接线都要有：`elder.js` 是设计一二共用的，`elder3.js` 是设计三。
    """
    for name in ("elder.js", "elder3.js"):
        js = _src(name)
        paths = {p for raw in _literals(js) for p in _expand(raw, set())}
        for want in ("/api/v1/medications/pending",
                     "/api/v1/medications/X/approve",
                     "/api/v1/medications/X/decline"):
            assert want in paths, f"{name} 没有调 {want}——这条流程在这一端还是断的"
            assert _known(routes, want), f"{want} 不在 app.routes 上"
