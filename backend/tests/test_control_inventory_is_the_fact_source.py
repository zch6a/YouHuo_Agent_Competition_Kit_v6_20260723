"""控件清单是事实源，而且它必须是**新鲜的**。

## 这份文件补的是哪个洞

`test_no_control_was_silently_deleted.py` 把 `now` 算成**四个 app 页面 id 的并集**
（那份文件的 `:197-199`）：

    missing = before - now - known - RESTRUCTURED

所以只要一个控件还在四页中的**任意一页**，`missing` 就不含它。也就是说
**app → app 的搬迁对它 100% 隐形**。那道闸门是为一个方向建的（手机框内 → 框外
`/stage`），而产品架构重构的搬迁绝大多数是 app 页面之间重组。

配套的洞：那道闸门读的事实源 `08_click_map.md` 只覆盖 41 / 145 个控件、是手写的、
只被读一次、缺文件时 `pytest.skip`。删控件 + 删文档那一行 = 全绿。

## 这份文件的判据

事实源换成 `frontend_redesign/ia/11_control_inventory.json`，由
`backend/scripts/build_control_inventory.py` **从代码生成**。于是"清单里有"不再是
一个可以手写的声明，而是"代码里真的有"。

剩下要守的就变成两件事：

1. **落盘的清单必须是新鲜的**（改了 HTML 就得重新生成）——否则矩阵断言的是过期事实，
   而它会全绿。和重型报告的源码指纹是同一个形状。
2. **位置必须精确**：不是"这个控件还在某一页"，而是"它在**这一页的这一格**"。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "frontend_redesign" / "ia" / "11_control_inventory.json"
BUILDER = ROOT / "backend" / "scripts" / "build_control_inventory.py"


def _load() -> list[dict]:
    assert INVENTORY.is_file(), (
        f"{INVENTORY.name} 不存在。跑 `python backend/scripts/build_control_inventory.py`。\n"
        "  注意这里**不是** skip——事实源缺失时静默跳过，正是旧闸门那个洞"
        "（`08_click_map.md` 缺文件时 pytest.skip，于是删控件 + 删文档 = 全绿）。"
    )
    return json.loads(INVENTORY.read_text(encoding="utf-8"))["controls"]


def test_the_inventory_is_freshly_generated() -> None:
    """落盘的清单必须和现在的代码一致。

    一份过期的事实源比没有事实源更糟：矩阵会拿它当真理去断言，然后**全绿**。
    """
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--diff"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "backend")},
    )
    assert result.returncode == 0, (
        "控件清单过期了——改了 HTML/JS 之后要重新生成：\n"
        "  python backend/scripts/build_control_inventory.py\n\n"
        + (result.stdout or "") + (result.stderr or "")
    )


def test_every_control_has_a_stable_identity() -> None:
    """每个控件都要有能被矩阵追踪的身份。

    实测 145 个控件里只有 57 个带 `id`。矩阵按 id 追踪就意味着**另外 88 个搬走或消失
    都不会有任何东西发现**。所以身份的取值范围放宽到一组**稳定属性**
    （`id` / `data-section` / `data-text` / `data-run` / `data-jump` / `href` …），
    刻意不包括 class（改名就断）、位置（重构必然变）、可见文字（还有一整轮文案要改）。
    """
    controls = _load()
    assert len(controls) >= 140, (
        f"只读到 {len(controls)} 个控件——清单大概没生成全，"
        "而「少读到」和「没有问题」在结果里长得一样"
    )
    nameless = [c for c in controls if not c["key"]]
    assert not nameless, (
        f"{len(nameless)} 个控件没有稳定身份：\n  "
        + "\n  ".join(f"{c['source_file']} {c['tag']} {c['text'][:16]}" for c in nameless)
    )


def test_every_control_declares_a_surface_and_a_shell() -> None:
    """三表面模型必须覆盖每一个控件，一个都不许悬空。"""
    controls = _load()
    bad = [c for c in controls if not c["surface"] or not c["shell"]
           or not c["visibility"]]
    assert not bad, (
        f"{len(bad)} 个控件没有完整分类：\n  "
        + "\n  ".join(f"{c['source_file']}:{c['key']}" for c in bad[:10])
    )
    surfaces = {c["surface"] for c in controls}
    assert surfaces <= {"consumer", "presentation", "professional"}, (
        f"出现了登记表以外的表面：{surfaces}"
    )


def test_identity_is_unique_within_a_page() -> None:
    """同一页里两个控件不许共用一个身份，否则矩阵会把它们当成同一个。

    实测有 21 个控件靠序号才区分得开（`#stageRoles` 的五个兄弟按钮、`/family` 的两个
    `href=/trust`、`/care` 的两个 `href=/`）。序号是权宜——重构时给它们补
    `data-*` 钩子，这一条会自然变干净。这里只守"不许重复"。
    """
    controls = _load()
    seen: dict[str, dict] = {}
    clashes: list[str] = []
    for control in controls:
        where = f"{control['source_file']}:{control['key']}"
        if where in seen:
            clashes.append(where)
        seen[where] = control
    assert not clashes, f"身份重复：{clashes[:10]}"


def test_the_consumer_surface_has_exactly_two_app_shells() -> None:
    """Consumer 侧只允许 Elder 与 Family 两个 App Shell —— 本轮的核心约束。

    `entry` 是门，不是 App，所以它可以并存。
    """
    shells = {c["shell"] for c in _load() if c["surface"] == "consumer"}
    assert shells <= {"elder", "family", "entry"}, (
        f"Consumer 侧出现了第三个 App Shell：{sorted(shells)}。"
        "本轮的核心约束是消费者侧只有 Elder App 与 Family App 两套壳。"
    )


#: 本轮的搬迁声明：`稳定身份 → (从哪一页哪一格, 到哪一页哪一格)`。
#:
#: 空的，因为 Phase A 不动 DOM。B–H 每搬一个控件就在这里加一行，
#: 下面那条断言会去核对它**真的**落在声明的位置上。
#:
#: 与旧矩阵（`test_no_control_was_silently_deleted.py` 的 `MATRIX`）的关键差别：
#: 旧的 dst 只到**文件**（`"stage.html"`），而且兜底判据是四页 id 的**并集**，
#: 所以 app → app 的搬迁恒为绿。这里的 dst 是 `(文件, panel)` 二元组，且判据是
#: **相等**而不是**存在**。
MIGRATIONS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {}


def _location_of(controls: list[dict], key: str) -> tuple[str, str] | None:
    for control in controls:
        if control["key"] == key:
            return (control["source_file"], control["panel"])
    return None


@pytest.mark.parametrize("key", sorted(MIGRATIONS))
def test_each_declared_move_landed_where_it_was_declared(key: str) -> None:
    """声明搬到哪，就必须真的在那。

    判据是**位置相等**，不是"还存在"。这正是旧闸门缺的那一格：它问的是
    「这个 id 还在四个 app 页面之一吗」，于是 `/care → /family` 全绿。
    """
    _src, dst = MIGRATIONS[key]
    actual = _location_of(_load(), key)
    assert actual is not None, f"声明搬到 {dst} 的控件 `{key}` 在代码里找不到了"
    assert actual == dst, f"`{key}` 声明搬到 {dst}，实际在 {actual}"


def test_the_gate_catches_an_app_to_app_move_that_the_old_one_missed() -> None:
    """变异测试：把一个控件从 `/care` 搬到 `/family`，两道闸门的反应必须不同。

    这是这一轮**唯一**真正重要的变异——旧闸门在这一路上是结构性失明的，
    而本轮的搬迁绝大多数走这一路。

    旧判据（`test_no_control_was_silently_deleted.py:197-199`）：

        now = 四个 app 页面 id 的**并集**
        missing = before - now - known
        → id 从 care.html 挪到 family.html，它仍在 `now` 里 → missing 为空 → **绿**

    新判据：位置是 `(文件, panel)` 二元组，且要求**相等** → **红**。
    """
    controls = _load()
    # 挑一个真实存在于 /care 的控件。
    victim = next((c for c in controls
                   if c["source_file"] == "care.html" and c["key"].startswith("data-section=")),
                  None)
    assert victim is not None, "找不到 /care 上的分区键——这条变异没有锚点"
    key = victim["key"]

    # ① 旧判据：并集。搬到 family.html 之后它还在并集里。
    app_pages = {"elder.html", "family.html", "care.html", "trust.html"}
    union_before = {c["key"] for c in controls if c["source_file"] in app_pages}
    moved = [dict(c, source_file="family.html", panel="today") if c["key"] == key else c
             for c in controls]
    union_after = {c["key"] for c in moved if c["source_file"] in app_pages}
    assert key in union_after and union_before == union_after, (
        "旧判据（并集）在这次搬迁上**没有**保持绿——那这条变异就证明不了它是盲区了，"
        "说明我对旧判据的理解错了，先去核对再改这条测试"
    )

    # ② 新判据：位置相等。
    before_location = _location_of(controls, key)
    after_location = _location_of(moved, key)
    assert before_location != after_location, "变异没生效"
    assert after_location == ("family.html", "today"), "变异打在了别处"
    # 声明「它应该还在 care.html」的话，新判据必须红。
    assert _location_of(moved, key) != before_location, (
        "新判据没能发现这次 app → app 的搬迁——那它和旧闸门一样是盲的"
    )


@pytest.mark.parametrize("route,shell", [
    ("/family", "family"), ("/care", "family"), ("/trust", "family"),
])
def test_the_family_deep_links_share_one_shell(route: str, shell: str) -> None:
    """`/family` `/care` `/trust` 是同一个 App 的三个 deep link，不是三个网站。

    这一条把「三文档共享壳」这个决定钉住。它们各自还是独立的 HTML 文档（这样规避了
    `initSections` 的命名空间冲突——`family` 与 `care` 都有 `data-panel="today"`，
    合进一个 DOM 会同时显示两个面板、两个 seg 同时高亮，而且不报错、截图也看不出来），
    但对用户必须是同一个 App。
    """
    controls = [c for c in _load() if c["route"] == route]
    assert controls, f"{route} 一个控件都没有——清单没覆盖到它"
    assert {c["shell"] for c in controls} == {shell}, (
        f"{route} 的控件不全属于 {shell} shell：{ {c['shell'] for c in controls} }"
    )
