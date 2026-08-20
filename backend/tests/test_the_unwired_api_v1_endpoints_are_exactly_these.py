"""`/api/v1` 上没有任何客户端在调的那一组，必须**恰好**是下面这一份清单。

## 为什么是「恰好」，不是「不超过」

这份清单在两个方向上都会红，而两个方向都真的发生过：

  · **新增孤儿**：又加了一条端点、没画入口 → 它不在清单里 → 红。
    这个项目已经因为「后端有、前端没画」栽过三次（同意记忆停在 proposed、
    用药计划停在待确认、`/api/v1` 那五条隐私与情绪接口），
    三次都是**两边界面都正常、不报任何错**。
  · **接通了却没更新清单**：清单里还留着一条其实已经有人调的 → 红。
    `KNOWN_ISSUES.md` 里那份手写的「九个端点」清单就是这么烂掉的：
    九个里有五个早就接上了，而文档还在说没有。一个只会在一个方向上红的
    判据，本身就是下一份过期清单。

## 这不是「31 个功能缺失」

多数能力在 `/v2` `/v4` 上有等价入口且确实接通了。这一条量的是
**`/api/v1` 这个翻译层比任何客户端实际需要的大出一倍**——
而每一条没人走的路径都是没被任何真实调用验证过的代码。

顺带钉住一件容易被拿来解释掉的事：**鸿蒙那一端也不调它**。
`harmonyos/.../ApiClient.ets` 打的全是 `/v2/*`，整个 ArkTS 工程里
`/api/v1` 一次都没出现。所以「那层是给 App 用的」这个说法是不成立的。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
STATIC = BACKEND / "static"
ARKTS = BACKEND.parent / "harmonyos"

#: 没有任何客户端在调的 `/api/v1` 端点。`(方法, 路径)`。
#: 接通了哪一条，就把它从这里删掉——这一步是**故意**要人动手的。
UNWIRED = frozenset({
    ("GET", "/api/v1/appointments"),
    ("POST", "/api/v1/appointments"),
    ("POST", "/api/v1/appointments/{appointment_id}/cancel"),
    ("GET", "/api/v1/bills"),
    ("GET", "/api/v1/bills/water/current"),
    ("GET", "/api/v1/bills/{bill_id}"),
    ("PUT", "/api/v1/contacts/{contact_id}/phone"),
    ("POST", "/api/v1/emergency/call"),
    ("GET", "/api/v1/health-summary"),
    ("GET", "/api/v1/medications"),
    ("GET", "/api/v1/memories"),
    ("POST", "/api/v1/memories/{memory_id}/approve"),
    ("POST", "/api/v1/memories/{memory_id}/decline"),
    ("POST", "/api/v1/memories/{memory_id}/forget"),
    ("GET", "/api/v1/notifications"),
    ("POST", "/api/v1/notifications/{notification_id}/read"),
    ("POST", "/api/v1/payments/prepare"),
    ("POST", "/api/v1/payments/{payment_id}/execute"),
    ("POST", "/api/v1/payments/{payment_id}/family-approve"),
    ("POST", "/api/v1/payments/{payment_id}/teach-back"),
    ("GET", "/api/v1/reminders"),
    ("POST", "/api/v1/reminders"),
    ("PATCH", "/api/v1/reminders/{reminder_id}"),
    ("POST", "/api/v1/reminders/{reminder_id}/done"),
    ("GET", "/api/v1/routines"),
    ("POST", "/api/v1/routines"),
    ("POST", "/api/v1/routines/{routine_id}/pause"),
    ("POST", "/api/v1/routines/{routine_id}/resume"),
    ("POST", "/api/v1/speech"),
    ("GET", "/api/v1/speech/status"),
    ("POST", "/api/v1/voice/sessions"),
})

_TERNARY = re.compile(
    r"""\$\{[^{}]*\?\s*(['"])([^'"]+)\1\s*:\s*(['"])([^'"]+)\3\s*\}""")


def _strip(text: str) -> str:
    """注释里逐字写着好几条路径（那是在解释缺陷长什么样）。不剥的话，
    这条判据会把说明文档当成调用，然后正确地报告「都接通了」。"""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.M)


def _expand(raw: str) -> list[str]:
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
    return [re.sub(r"\$\{[^}]*\}", "{}", p).split("?")[0] for p in paths]


def _called() -> set[str]:
    """前端真的打出去的路径。两种写法都收：`api(<字面量>` 和裸的 `'/api/v1/…'`。"""
    out: set[str] = set()
    files = 0
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in (".js", ".html"):
            continue
        files += 1
        src = _strip(io.open(path, encoding="utf-8", errors="replace").read())
        for m in re.finditer(
                r"""api\(\s*(?:`(/[^`]*)`|'(/[^']*)'|"(/[^"]*)")""", src):
            out.update(_expand(m.group(1) or m.group(2) or m.group(3)))
        for m in re.finditer(r"""['"`](/api/v1/[^'"`\s]*)['"`]""", src):
            out.update(_expand(m.group(1)))
    assert files >= 40, f"只扫到 {files} 个前端文件——抽取器多半坏了"
    return out


def _matches(route: str, call: str) -> bool:
    a = [x for x in route.strip("/").split("/") if x]
    b = [x for x in call.strip("/").split("/") if x]
    if len(a) != len(b):
        return False
    return all(x.startswith("{") or y == "{}" or x == y for x, y in zip(a, b))


@pytest.fixture()
def v1_routes(tmp_path) -> set[tuple[str, str]]:
    from youhuo.api import create_app

    app = create_app(tmp_path / "orphan.db", demo_mode=True)
    routes = {
        (method, r.path)
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1")
        for method in (getattr(r, "methods", set()) - {"HEAD", "OPTIONS"})
    }
    assert len(routes) >= 40, f"只数到 {len(routes)} 条 /api/v1 路由——这条判据在空转"
    return routes


def test_the_unwired_set_is_exactly_the_documented_one(v1_routes) -> None:
    calls = _called()
    assert len(calls) >= 30, f"只抽到 {len(calls)} 条调用路径——抽取器多半坏了"

    unwired = {(m, p) for (m, p) in v1_routes
               if not any(_matches(p, c) for c in calls)}

    newly_orphaned = sorted(unwired - UNWIRED)
    newly_wired = sorted(UNWIRED - unwired)
    assert not newly_orphaned, (
        "这些 `/api/v1` 端点没有任何客户端在调，而清单里没有它们：\n  "
        + "\n  ".join(f"{m:6} {p}" for m, p in newly_orphaned)
        + "\n端点存在不等于这条流程通了。画入口，或者把它加进 UNWIRED 并说明为什么。")
    assert not newly_wired, (
        "这些端点已经有人调了，`UNWIRED` 却还留着它们：\n  "
        + "\n  ".join(f"{m:6} {p}" for m, p in newly_wired)
        + "\n把它们从清单里删掉——过期的清单就是下一份假通过。")


def test_the_harmony_client_does_not_use_this_layer() -> None:
    """「那一层是给鸿蒙 App 用的」这个说法必须是假的，否则上面那条整条无意义。

    真要有一天 ArkTS 开始打 `/api/v1`，这条会红——那时上面那份清单必须
    把 ArkTS 侧的调用也算进来，否则它会把有人用的端点报成孤儿。
    """
    if not ARKTS.exists():
        pytest.skip("这份仓库里没有 harmonyos/")
    hits = []
    files = 0
    for path in sorted(ARKTS.rglob("*.ets")):
        files += 1
        src = _strip(io.open(path, encoding="utf-8", errors="replace").read())
        if "/api/v1" in src:
            hits.append(path.name)
    assert files >= 5, f"只扫到 {files} 个 .ets——这条判据在空转"
    assert not hits, (
        f"ArkTS 开始打 `/api/v1` 了（{hits}）——"
        "上面那条孤儿判据现在会误报，得把鸿蒙侧的调用一起算进去")
