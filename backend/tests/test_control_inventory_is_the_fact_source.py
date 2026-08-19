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

# `functools` 和 `re` 都是补的。改这个文件的那一轮被中断在半途，
# 新写的判据用了它们而 import 没跟上。
#
# 后果不是「这一个文件报错」，是 **pytest 收集阶段直接中断**，2000 多条测试
# 一条都跑不了。半途中断的编辑最危险的形态就是这种：它不在自己那一格里失败，
# 而是把整个门堵上——而「全都没跑」和「全都通过」在退出码之外看起来很像。
import functools
import json
import re
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


def test_the_consumer_surface_has_no_unplanned_app_shell() -> None:
    """Consumer 侧的 App Shell 必须是**声明过的**那几个。

    原文是「只允许 Elder 与 Family 两套壳 —— 本轮的核心约束」。
    2026-08 起多了第三套：`app`，即山水版老人端（`backend/static/app/`）。

    这不是漂移，是产品所有者拍板的方向变更：界面先定稿、后端按它的契约补接口，
    新前端自带十个页面、五槽底栏和自己的样式体系，通过 `/api/v1` 门面接同一个
    后端（复述核验、任务状态机、审计链都只有一份）。它长期会取代 `/elder`，
    但迁移期间两套并存。

    所以这条判据没有被删掉、也没有放宽成「随便几个」——它仍然拦住**没写进这里**
    的第四套壳。加壳这件事必须来这里写一句为什么，而不是悄悄多出来一个。
    """
    #: 每一项都要有出处，不能只是「让它变绿」。
    DECLARED = {
        "elder",   # 老人端（既有实现）
        "family",  # 家人端 / 照护 / 可信中心共用
        "entry",   # `/` 门厅——是门不是 App
        "app",     # 山水版老人端，迁移期与 elder 并存
    }
    shells = {c["shell"] for c in _load() if c["surface"] == "consumer"}
    extra = sorted(shells - DECLARED)
    assert not extra, (
        f"Consumer 侧出现了没有声明过的 App Shell：{extra}。"
        "多一套壳意味着多一套导航、多一套样式、多一批判据要覆盖——"
        "要加就在这条判据的 DECLARED 里写清楚它是什么、为什么存在。"
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
MIGRATIONS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    # Phase C 的第一次搬迁，而且它正是这条判据升级要抓的那一路：**app → app**。
    #
    # 「趋势」从 /family 的一级分区搬进 /care 的照护档案。旧判据（四页 id 的并集）
    # 对这一路恒为绿——搬完之后 `data-section=trend` 仍然在四页之一里。
    # 新判据比的是 `(文件, panel)` 二元组，所以它看得见。
    #
    # 为什么搬：它读 `/v4/reports/emotion`，而 /care 已经有「心情」那一格读同一个
    # 端点（不同窗口）。两者是同一件事的今天与这一周。
    #
    # 搬迁时还修掉了一件事：family.js 那份 `EMOTION_LABEL` 缺 positive /
    # low_mood / urgent、多出后端没有的 sad / happy / distressed，于是这一格会把
    # 最要紧的 `urgent` 印成英文码。care.js 里已有修好的 `EMOTION_WORD`，用了那份。
    "data-section=trend": (("family.html", ""), ("care.html", "")),
}


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


#: 各列当前的填充数，作为**下界**。参考产品研究那一轮量出来的。
#:
#: 为什么要有这张表：清单报告「145/145 可追踪」，那句话**只对身份成立**。
#: 而这一轮矩阵的升级点是「dst 是 `(文件, panel)` 二元组，判据是**相等**」，
#: 它依赖的 `panel` 列只填了 55/145。对另外 90 个控件，判据在拿
#: `(file, "")` 和 `(file, "")` 比——**panel 那一半是惰性的**。
#:
#: 这和这个项目反复踩的是同一个坑：读到的那个值不一定是决定结果的那个值。
#: 「145 个控件全部可追踪」是真的，但可追踪 ≠ 位置可比较。
_COVERAGE_FLOOR = {
    "key": 145,
    "source_file": 145,
    "surface": 145,
    "shell": 145,
    "module": 145,
    "visibility": 145,
    "panel": 55,
    "interaction_type": 102,
    "handler_file": 117,
    "handler": 117,
    # 从 5 抬到 8。抬它的理由写在 `_REACHES_THE_BACKEND` 上面那一段。
    #
    # 为什么是 8 而不是 9：落盘清单里现在有 **9** 个控件的 `apis` 非空，但其中
    # `stage.html:id=stageEscape` 那一条是**假的**——它挂着八个端点，而
    # `stage.js:275` 里它的全部行为是 `() => setClean(false)`，一个请求都不发。
    # 把 9 钉成下限，就等于要求那个归属错误**永远别被修好**：谁修好了 `function_body()`
    # 的过度归属，这一条就红。那和这一轮要治的「罚进步」是同一个病。
    "apis": 8,
}


def _is_filled(control: dict, column: str) -> bool:
    value = control.get(column)
    if isinstance(value, list):
        return len(value) > 0
    return bool(value) and str(value).strip() != ""


@pytest.mark.parametrize("column", sorted(_COVERAGE_FLOOR))
def test_no_inventory_column_gets_emptier(column: str) -> None:
    """每一列的填充数只许涨，不许跌。

    加这条是因为空列是**静默**的失效：矩阵会照着一列空值去断言「位置相等」，
    然后全绿。这正是它替换掉的那份手写点击地图的毛病——缺文件就 `pytest.skip`。
    """
    controls = _load()
    filled = sum(1 for c in controls if _is_filled(c, column))
    floor = _COVERAGE_FLOOR[column]
    assert filled >= floor, (
        f"`{column}` 列的填充数从 {floor} 掉到 {filled}。"
        "清单是矩阵的事实源，一列变空会让依赖它的断言静默变成恒真。"
    )


# --- apis 这一列：下限 + 名单，不是上限 --------------------------------------
#
# 上一版这里是一条**上限**：`len(with_api) <= 8`。于是这一轮把 /family 的
# 「加一条提醒」三个输入从本地 toast 真接到 `POST /v2/family/reminders` 之后，
# 计数从 6 涨到 9，闸门**变红**——它罚的是进步。它自己的报错信息也承认这一点，
# 让越过阈值的人把它改成正向断言。这一段就是那次改写。
#
# 换成什么：
#   ① `_REACHES_THE_BACKEND` —— 一张**核过的**「控件 → 端点」表，逐条断言它
#      **还**打得到。接通更多控件不会让它红；**弄断**表里任何一条会。
#   ② `_UNBOUND_BUT_EXPLAINED` —— 「这一页的脚本里找不到对它的引用」那一批的
#      具名白名单，每一条写清是被什么绑的；解释不了的单独列进 `_NOTHING_BINDS_THEM`。
#   ③ `_why_there_is_no_edge()` —— 剩下没有端点的控件按**结构性**理由分类，
#      分类判据从代码里算出来，不是手写的状态字段。

#: 一个正则，回答「这份脚本里到底有没有一处打后端」。
#:
#: 三种调用形态都要认，少认一种就会把「接了」读成「没接」：
#:   `api('/v2/...')`        老六页（common.js 的 `api()` 直接 `fetch(path)`）
#:   `fetch('/...')`         少数直接 fetch 的地方
#:   `YouhuoAPI.get('/...')` 山水版 `/app` 那一套（api-client.js 里
#:                           `fetch(cfg.apiBase + path)`，apiBase = `/api/v1`）
#:
#: 第三种是清单的 `apis` 列**完全看不见**的：`build_control_inventory.py` 的
#: `_API_CALL` 只认前两种，而 `/app` 的 35 处后端调用全走第三种。所以
#: 「`apis` 为空」在 `/app` 上根本不能读成「没接后端」。
_BACKEND_CALL = re.compile(
    r"""\b(?:api|fetch)\(\s*[`'"]/|\bYouhuoAPI\.(?:get|post|put|request)\("""
)


@functools.lru_cache(maxsize=1)
def _scripts_with_no_backend_call() -> frozenset[str]:
    """全文件一处后端调用都没有的脚本。绑在它们上的控件是**证得出来**的纯本地 UI。"""
    static = ROOT / "backend" / "static"
    return frozenset(
        str(p.relative_to(static)).replace("\\", "/")
        for p in static.rglob("*.js")
        if not _BACKEND_CALL.search(p.read_text(encoding="utf-8"))
    )


@functools.lru_cache(maxsize=None)
def _scripts_of(page: str) -> tuple[str, ...]:
    """这一页真正加载的脚本。用生成器自己那份实现，不在这里抄第二遍。"""
    sys.path.insert(0, str(BUILDER.parent))
    import build_control_inventory  # noqa: PLC0415

    return tuple(build_control_inventory.scripts_for(page))


def _where(control: dict) -> str:
    return f"{control['source_file']}:{control['key']}"


#: **核过的**「控件 → 端点」边：`页面:稳定身份 → 这个控件参与的那个端点`。
#:
#: 这张表是**下限**，判据是「这条边还在不在」。
#:
#: 每一条都是读着 JS 核出来的，**不是照抄清单的 `apis` 列**。为什么不能照抄：
#: 那一列记的是「抽取器在 handler 的花括号块里看见了一个字面端点」，而它会**多报**。
#: 现成的例子就是第 9 条：`stage.html:id=stageEscape` 在清单里挂着八个端点
#: （`/v2/tasks` `/v5/sagas` `/v3/delegation/preview` …），而 `stage.js:275` 里
#: 它的全部行为是
#:
#:     escape.addEventListener('click', () => setClean(false));
#:
#: 一个请求都不发。它挂着八个端点，只是因为 `stage.js:19` 那句
#: `getElementById('stageEscape')` 落在整份文件那个 IIFE 的花括号里，于是
#: `function_body()` 把**整份 stage.js** 的端点都算给了它。
#: 照抄那一列 = 把一条假边钉成判据 = 将来谁修好归属谁就红。所以这里只有 8 条。
_REACHES_THE_BACKEND: dict[str, str] = {
    # /family「加一条提醒」表单的三个输入。三个都在 `createReminder()` 的函数体里
    # 被读走，同一个函数里 `api('/v2/family/reminders', {method: 'POST'})`
    # （family.js:248-273），提交口是 `#reminderForm` 的 submit（family.js:683）。
    #
    # 这三个就是让旧上限变红的那三个：它们这一轮才从「只弹一句本地 toast」
    # 接到真后端。旧闸门把这件事读成越界，新闸门把它读成**必须守住的三条边**。
    "family.html:id=reminderTitle": "/v2/family/reminders",
    "family.html:id=reminderDue": "/v2/family/reminders",
    "family.html:id=escalation": "/v2/family/reminders",
    # family-v6.html 是同一套表单的第二份 DOM，它也加载 family.js，所以同一个
    # `createReminder` 绑的是六个控件而不是三个。两份都要守：只修好一份，
    # 另一份的用户看到的还是那个假成功。
    "family-v6.html:id=reminderTitle": "/v2/family/reminders",
    "family-v6.html:id=reminderDue": "/v2/family/reminders",
    "family-v6.html:id=escalation": "/v2/family/reminders",
    # /stage 的两个演示输入框。文本框的值直接进 POST 的 body——
    # proof-demos.js:473-482 的 `emotionDemo` 与 :485-494 的 `medicalDemo`。
    # 它们在演示台上，但打的是真端点，所以是真边。
    "stage.html:id=emotionText": "/v4/emotions/analyze",
    "stage.html:id=medicalText": "/v4/medical-reports/analyze",
}


@pytest.mark.parametrize("where", sorted(_REACHES_THE_BACKEND))
def test_a_control_that_reaches_the_backend_still_does(where: str) -> None:
    """正向断言：这些控件必须**还**打得到它那个端点。

    方向是这一条判据的全部意义：

        接通一个新控件  → 这张表不管它 → **绿**（旧的上限判据在这里是红的）
        弄断表里一条边  → 它的 `apis` 空掉 → **红**

    上限判据两件事都做反了。
    """
    endpoint = _REACHES_THE_BACKEND[where]
    control = next((c for c in _load() if _where(c) == where), None)
    assert control is not None, (
        f"`{where}` 在清单里没有了。它是一条核过的「控件 → 端点」边，"
        "控件不在了这条边也就不在了。\n"
        "  如果是搬走了，在 `MIGRATIONS` 里声明，并把这张表里的页面改掉；\n"
        "  如果是删掉了，那 `/v2/family/reminders` 这条链路少了一个入口。"
    )
    assert endpoint in control["apis"], (
        f"`{where}` 原来打到 `{endpoint}`，现在它的 apis 是 {control['apis'] or '空'}。\n"
        f"  绑它的是 {control['handler_file'] or '（这一页的脚本里没有引用它）'}"
        f"::{control['handler'] or '—'}。\n"
        "  这条判据是**下限**：多接一个端点不会让它红，只有**弄断**才会。"
    )


@pytest.mark.parametrize("where", sorted(_REACHES_THE_BACKEND))
def test_a_declared_edge_is_verifiable_in_the_source_not_only_in_the_artifact(
    where: str,
) -> None:
    """上面那条判据读的是**产物**；这一条去代码里核同一件事。

    只读产物是不够的：清单是脚本生成的，脚本的归属会多报（`#stageEscape` 那八个
    端点就是），也会漏报（`/app` 的 35 处 `YouhuoAPI.*` 一处都看不见）。
    一张照着产物抄出来的表，等于把抽取器的毛病抄成了判据。

    这里核的是：那个端点字面上**真的**写在绑这个控件的那份脚本里。
    """
    endpoint = _REACHES_THE_BACKEND[where]
    page, _key = where.split(":", 1)
    sources = [
        (ROOT / "backend" / "static" / name).read_text(encoding="utf-8")
        for name in _scripts_of(page)
    ]
    assert any(endpoint in text for text in sources), (
        f"`{where}` 声明打到 `{endpoint}`，但 {page} 加载的脚本"
        f"（{'、'.join(_scripts_of(page)) or '一个都没有'}）里找不到这个字面端点。\n"
        "  要么端点改名了（那就改这张表），要么这条边已经断了。"
    )


def test_the_declared_edges_do_not_contradict_the_local_only_scripts() -> None:
    """两张表不许打架。

    如果一个控件被声明成「打到某个端点」，而绑它的那份脚本里**一处后端调用都没有**，
    那两张表至少有一张是错的。这一条把它们钉在一起，免得各自漂移。
    """
    local_only = _scripts_with_no_backend_call()
    controls = {_where(c): c for c in _load()}
    contradictions = [
        f"{where}（绑它的 {controls[where]['handler_file']} 全文件没有后端调用）"
        for where in sorted(_REACHES_THE_BACKEND)
        if where in controls and controls[where]["handler_file"] in local_only
    ]
    assert not contradictions, (
        "这些控件被声明成打到后端，但绑它们的脚本里一处后端调用都没有：\n  "
        + "\n  ".join(contradictions)
    )


#: 「这一页加载的脚本里找不到对它的引用」那 16 个，逐个查过的结论。
#:
#: `值` 是**真正把它绑上去的那个钩子**——必须能在这一页加载的脚本里找到这个字面串。
#: 判据不是「我写了一句解释」，而是「解释里指的那个钩子代码里真的有」。
#:
#: 为什么这批会被报成「没人绑」：`trace()` 拿**稳定身份里那个属性**去脚本里搜，
#: 而 `_KEY_ATTRS` 挑身份时 `id` / `data-kind` / `data-label` / `data-jump` 都排在
#: `data-action` 前面。于是身份取到了 `id=homeVoiceStart`，脚本里却只有
#: `data-action="voice-start"`——两边说的是同一个按钮，用的是不同的名字。
#: 这**不是**控件的缺陷，是「查得到」和「绑上了」之间的落差。
_UNBOUND_BUT_EXPLAINED: dict[str, tuple[str, str]] = {
    # ---- 属性委托：身份取了 id / data-kind / data-label，绑定走的是 data-action ----
    "app/pages/home.html:id=homeVoiceStart": (
        "voice-start",
        "`<button id=\"homeVoiceStart\" data-action=\"voice-start\">`，由 app.js:361 "
        "那个 `[data-action]` 全局委托接住，:364 是它的分支。身份用了 id，绑定用的是 "
        "data-action —— 两个名字，同一个按钮。",
    ),
    "app/pages/certificate.html:data-label=完整凭证": (
        "cert-detail",
        "`<button data-action=\"cert-detail\" data-label=\"完整凭证\">`，同一个 "
        "`[data-action]` 委托，分支在 app.js:452。`data-label` 只是给清单看的标签。",
    ),
    **{
        f"app/pages/records.html:data-kind={kind}": (
            "records-filter",
            "记录页的四个筛选键都带 `data-action=\"records-filter\"`，"
            "app.js:425-429 读的是 `el.dataset.kind`。脚本里从来不会出现 "
            "`[data-kind]` 这个字面串，所以按属性名去搜必然搜不到。",
        )
        for kind in ("全部", "支付", "健康", "服务")
    },
    # ---- 属性 / class 委托：脚本按选择器绑，不经 id ----
    "elder.html:id=openExtras": (
        "data-sheet-open",
        "sheet.js:30 `document.querySelectorAll('[data-sheet-open]')`。"
        "这一条正是生成器自己那句提示里举的例子。",
    ),
    **{
        f"stage.html:data-jump={n:02d}": (
            "beat-jump",
            "stage.js:532-548 在 document 上按 `.beat-jump` 这个 **class** 委托，"
            "取值走 `btn.dataset.jump`。身份属性是 `data-jump`，绑定钩子是 class，"
            "所以按属性名搜不到。",
        )
        for n in range(1, 8)
    },
    **{
        f"family-v3.html:id={ident}": (
            "data-app",
            "家人端设计三顶部那两个切换（家人端 / 照护中心）。绑定是**属性委托**："
            "`script-01.js:3` 的 `querySelectorAll('[data-app]')`，`family3.js` 里"
            "读照护数据那一处也是 `$$('[data-app]')`。id 是后加的，只为了让这份清单"
            "认得出它们是两个不同的控件——原先两条身份都是空的，连彼此都分不开。",
        )
        for ident in ("appFamily", "appCare")
    },
    # ---- 表单字段：按 name 取值，脚本里不会出现这个属性名 ----
    **{
        f"family-v3.html:name={field}{suffix}": (
            "FormData",
            "家人端设计三两个 `.flow-editor` 里的时间/事项输入。`family3.js` 的 "
            "submit 处理用 `new FormData(fresh)` 再 `fd.get('time')` / "
            "`fd.get('title')` 取值——按 **name** 读，脚本里永远不会出现 "
            "`name=time` 这个字面串，所以按属性名去搜必然搜不到。"
            "和 `records.html` 那四个 `data-kind` 是同一个形状。",
        )
        for field in ("time", "title")
        for suffix in ("", "#2")
    },
    # ---- 原生行为：本来就不需要 JS ----
    "stage.html:id=directorDeck/summary": (
        "",
        "`<details id=\"directorDeck\">` 的 `<summary>`。开合是 HTML 原生行为，"
        "不需要任何脚本 —— 「没有脚本引用它」在这里是**正确**的状态。",
    ),
}

#: 查不出解释的那些：**没有任何脚本绑它**。这不是白名单，是缺陷登记。
#:
#: 这一条不允许被读成「已解释」。它留在这里是为了让它**有名字**、并且让下一个
#: 冒出来的死控件立刻变红，而不是混在 16 个「其实都绑着」里没人看得出来。
_NOTHING_BINDS_THEM: dict[str, str] = {
    "stage.html:id=directorToggle": (
        "`<button class=\"stage-pick\" id=\"directorToggle\" aria-expanded=\"false\" "
        "aria-controls=\"directorDeck\">导演台</button>`（stage.html:63）。"
        "全仓库的 .js 里**没有任何一处**出现 `directorToggle`。它顶着 `.stage-pick`，"
        "但 stage.js 的三处 `.stage-pick` 委托分别挂在 `#stageRoles` / `#stageSizes` / "
        "`#stageLines` 上，而这个按钮住在 header 的 `.stage-depth` 里，一个都够不着；"
        "另外两处 document 级委托认的是 `.beat-jump` 与 `[data-run]`，也都不是它。"
        "严格 CSP 下没有内联 onclick，所以确实没有别的路。\n"
        "  后果：点它什么都不发生，`aria-expanded=\"false\"` 是一句永远为假的承诺，"
        "`aria-controls` 指着的 `<details id=\"directorDeck\">` 只能靠它自己的 "
        "`<summary>` 打开——正因为 summary 能开，这一页看起来一点都不坏。\n"
        "  修法（属于 stage.html / stage.js，不属于这份测试）：要么给它绑上开合并"
        "同步 `aria-expanded`，要么删掉这个按钮、只留 `<summary>`。"
    ),
}


def _unbound(controls: list[dict]) -> list[dict]:
    """这一页加载的脚本里找不到对它的引用的控件。

    `<a>` 不算：链接不需要脚本也能跳。这和生成器 `main()` 里那句
    「另有 N 个控件……找不到对它的引用」算的是同一批。
    """
    return [c for c in controls if not c["handler_file"] and c["tag"] != "a"]


def test_every_unbound_control_has_a_written_explanation() -> None:
    """「没人绑」的每一个都要有名字和理由——包括「其实是缺陷」这个理由。

    生成器打印这批的时候写着「这不一定是缺陷……但每一个都要有解释」。
    那句话此前没有任何东西在执行：打印完就没了，多一个少一个都不会有人知道。
    这条判据把它变成闸门。
    """
    named = set(_UNBOUND_BUT_EXPLAINED) | set(_NOTHING_BINDS_THEM)
    unexplained = sorted(_where(c) for c in _unbound(_load()) if _where(c) not in named)
    assert not unexplained, (
        f"{len(unexplained)} 个控件在这一页加载的脚本里找不到对它的引用，"
        "而且没有登记过：\n  "
        + "\n  ".join(unexplained)
        + "\n\n  逐个查清楚它到底被什么绑着——这个项目里最常见的答案是**属性委托**："
        "\n  `[data-action]`（/app 全局分发表）、`[data-sheet-open]`（sheet.js）、"
        "\n  `.beat-jump` / `[data-run]`（stage.js）、`.seg`（common.js 的 initSections）。"
        "\n  查得到就写进 `_UNBOUND_BUT_EXPLAINED`（值是那个钩子的字面串，下一条判据会核）；"
        "\n  真的什么都没绑，写进 `_NOTHING_BINDS_THEM` —— 那是一个死控件，要报出去。"
    )


@pytest.mark.parametrize("where", sorted(_UNBOUND_BUT_EXPLAINED))
def test_the_explanation_points_at_a_hook_that_is_really_there(where: str) -> None:
    """解释不能只是一句话，它指的那个钩子必须在这一页的脚本里找得到。

    不核这一步的话，白名单就是「写一句话就能让门变绿」——那正是这一轮在治的病。
    """
    hook, _why = _UNBOUND_BUT_EXPLAINED[where]
    page, _key = where.split(":", 1)
    control = next((c for c in _load() if _where(c) == where), None)
    assert control is not None, (
        f"`{where}` 已经不在清单里了。白名单不许留幽灵条目——"
        "控件没了就把这一行删掉。"
    )
    if not hook:
        # 空钩子 = 「原生行为，本来就不需要 JS」。这个说法只对 `<summary>` 这类
        # 天生可交互的标签成立，所以核的是标签而不是脚本。
        assert control["tag"] in {"summary", "details"}, (
            f"`{where}` 的解释是「原生行为不需要脚本」，但它是 <{control['tag']}>，"
            "不是 <summary>。<button> 没有原生开合——没有脚本它就是死的。"
        )
        return
    sources = [
        (ROOT / "backend" / "static" / name).read_text(encoding="utf-8")
        for name in _scripts_of(page)
    ]
    assert any(hook in text for text in sources), (
        f"`{where}` 的解释说它由 `{hook}` 绑定，但 {page} 加载的脚本"
        f"（{'、'.join(_scripts_of(page)) or '一个都没有'}）里找不到这个串。\n"
        "  要么钩子改名了（改这张表），要么这个控件**真的**已经没人绑了"
        "（那它该进 `_NOTHING_BINDS_THEM`）。"
    )


def test_the_dead_control_list_does_not_grow_silently() -> None:
    """死控件只许变少。

    `_NOTHING_BINDS_THEM` 是缺陷登记，不是豁免：新增一个要在这里写下它的名字，
    这条判据本身不会因为「登记了」就变绿——上面那条覆盖判据才是门，这一条守的是
    **不许在登记表里悄悄多一行**。
    """
    #: 查清楚的那一轮里，确认「什么都没绑」的只有这一个。
    KNOWN = {"stage.html:id=directorToggle"}
    added = sorted(set(_NOTHING_BINDS_THEM) - KNOWN)
    assert not added, (
        f"死控件登记表多了 {len(added)} 条：{added}。\n"
        "  往这张表里加名字**不是**修好它。先确认它真的什么都没绑"
        "（属性委托、class 委托、原生行为都排除掉），确认之后请把它报出去，"
        "并同步更新这条判据里的 KNOWN。"
    )


def _why_there_is_no_edge(control: dict) -> str:
    """一个没有端点的控件，为什么事实源里没有它那条边。

    四个理由，判据全部是**结构性的**、从代码里算出来的，没有一个是手写的状态字段
    ——这个项目在「按一个手工维护的字段分类，然后整类空过」上栽过。
    """
    if control["tag"] == "a":
        # 换页面本身不打后端，目标页自己拉自己的数据。
        # 这不是猜的：全清单 70 个没有端点的 `<a>`，有端点的 `<a>` 是 0 个。
        return "navigate"
    if not control["handler_file"]:
        # 没有任何脚本引用它。逐个查过，见 `_UNBOUND_BUT_EXPLAINED` /
        # `_NOTHING_BINDS_THEM`。
        return "unbound"
    if control["handler_file"] in _scripts_with_no_backend_call():
        # 绑它的那份脚本里一处后端调用都没有 —— 它是**证得出来**的纯本地 UI。
        # 现在落在这一类的是 elder-v6-a/b.js、family-v6-a/b.js、sheet.js：
        # 换分区、开抽屉、把一句快捷话填进输入行。
        return "local-only"
    # 剩下的：绑它的脚本确实打后端，但端点在 handler **调用的下一层函数**里，
    # 而 `function_body()` 只看 handler 自己那对花括号。
    #     elder.js:1031  `#send` → `send()` → `postChat()` → `api('/v2/chat')`（:469）
    #     judge.js:63    `#txnRefresh` → `onRefresh()` → `api('/v2/tasks?limit=100')`（:261）
    #     app.js         `[data-action]` 分发表 → `YouhuoAPI.post(...)`，而 `_API_CALL`
    #                    连 `YouhuoAPI.` 这种形态都不认（/app 的 35 处调用全在视野外）
    # 这一类**不能**读成「没接后端」，只能读成「事实源里没有这条边」。
    return "one-hop-away"


#: 四个理由各自至少要覆盖到一个控件。
#:
#: 加这一条是因为「判据跑过了」和「判据管到了东西」是两回事：一条谁都不匹配的分支
#: 是死作用域，它会安静地跟着整套判据一起变绿。
_EVERY_REASON = ("navigate", "unbound", "local-only", "one-hop-away")


def test_every_control_without_an_edge_has_a_structural_reason() -> None:
    """没有端点的控件，每一个都要落进四个理由之一。

    这张名单是**下限判据的配套说明**：它回答「为什么 `_REACHES_THE_BACKEND` 只有
    8 条而不是 376 条」。

    最要紧的一句写在这里：**`apis` 为空不等于「没接后端」**。
    376 个控件里 367 个没有端点，而其中 253 个属于 `one-hop-away` ——
    它们大多**接着后端**，只是抽取器跟不过去那一跳。拿这一列去数「还有多少没接」，
    数出来的是抽取器的能力，不是产品的进度。

    方向上和上限判据相反：接通一个控件，它就从这批里消失，这条判据不会红。
    """
    reasons = {_why_there_is_no_edge(c) for c in _load() if not _is_filled(c, "apis")}
    unknown = sorted(reasons - set(_EVERY_REASON))
    assert not unknown, f"出现了没登记过的理由：{unknown}"


@pytest.mark.parametrize("reason", _EVERY_REASON)
def test_no_reason_is_dead_scope(reason: str) -> None:
    """每个理由都要真的匹配到控件。

    判据算在**整份清单**上而不是只算在「没有端点」的那批上：否则谁把
    `local-only` 里最后一个控件接上了后端，这一条就红——又是罚进步。
    """
    hits = sum(1 for c in _load() if _why_there_is_no_edge(c) == reason)
    assert hits, (
        f"`{reason}` 这个理由一个控件都没匹配到。一条谁都不匹配的分支是死作用域，"
        "它跟着整套判据一起变绿，看不出来。先确认它还成立，不成立就删掉它。"
    )


def test_a_declared_move_must_be_detectable_by_the_criterion() -> None:
    """声明的搬迁必须是这个判据**测得出来**的那种。

    `panel` 空了 90 个，所以存在一类搬迁：同一个文件内、两侧 panel 都为空——
    这时 `(file, panel)` 两侧完全相等，断言恒真，等于没测。
    B–H 每加一行 MIGRATIONS 都要先过这一关。
    """
    inert = [
        key for key, (src, dst) in MIGRATIONS.items()
        if src[0] == dst[0] and not src[1] and not dst[1]
    ]
    assert not inert, (
        f"这些搬迁声明是判据测不出来的：{inert}。"
        "同文件、两侧 panel 均为空 ⇒ `(file, panel)` 相等恒成立。"
        "要么给源和目标标上 `data-panel`，要么这次搬迁本来就没有跨越任何边界。"
    )
