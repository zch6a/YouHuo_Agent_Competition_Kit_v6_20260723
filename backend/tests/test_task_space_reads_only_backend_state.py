"""Task Space 只翻译后端状态，不自己攒一个状态机。

## 守的是什么

计划书第九至十三节把 Focus Mode 重定义成 Task Space：老人说完一句之后，屏幕上出现的
是**这件事本身**（多少钱、给谁、办到哪一步、现在要她做什么），不是一串聊天气泡。

而这里最容易长歪的地方不是样式，是**状态**。架构约束写死在模块头上：

    Conversation engine owns state. Task Space owns presentation.

一旦 Task Space 开始写 `if (localTaskState === …)`，前端就有了第二个状态机；
半年之后它和后端那个一定会漂移，而漂移的表现是「界面说等家人确认，后端已经办完了」
——这种缺陷没有任何闸门抓得到，因为两边各自都自洽。

所以这条闸门按**源码形状**判：分支只许读后端给的字段。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RAW = (ROOT / "backend" / "static" / "task-space.js").read_text(encoding="utf-8")


def _strip_comments(js: str) -> str:
    """先剥注释再判。

    第一版没剥，于是这条闸门抓到了**我自己那句注释**——「一处都不读 `task_id`」里
    的那五个字符。这个项目本轮已经四次遇到同一类：检查器命中的是解释文字，
    不是代码。而它给出的结论（「Task Space 读了 task_id」）和真实情况正好相反。

    仪器数的必须是代码在做什么，不是注释在说什么。
    """
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", js, flags=re.M)


#: 剥掉注释之后的代码。所有断言都对着它，除了那条专门检查注释的（没有）。
SOURCE = _strip_comments(_RAW)

#: 后端在 `/v2/chat` 响应里给出的、Task Space 允许读的字段。
BACKEND_FIELDS = {"code", "task_status", "message", "data", "teach_back",
                  "task_type", "amount_yuan", "amount_cents", "slots", "period",
                  "authority", "heard", "expected", "approver_name", "family_name"}


def _view_kind_body() -> str:
    body = SOURCE[SOURCE.index("export function viewKindOf"):]
    return body[: body.index("\n}")]


def test_the_module_keeps_no_state_of_its_own() -> None:
    """没有模块级可变状态。

    `let` / `var` 在模块顶层就是一个状态槽。纯渲染函数不需要它——需要的时候说明
    这个模块开始记事了，而它一记事就成了第二个状态机的开头。
    """
    top_level = [line for line in SOURCE.split("\n")
                 if re.match(r"^(let|var)\s+\w+", line)]
    assert not top_level, f"模块顶层有可变状态：{top_level}"


def test_every_branch_reads_a_backend_field() -> None:
    """`viewKindOf` 的每个分支都必须从后端字段取值。

    判据：那个函数体里出现的每一个属性访问，都要在 `BACKEND_FIELDS` 里。
    出现别的名字说明它开始读自己攒的东西了。
    """
    reads = set(re.findall(r"\.(\w+)", _view_kind_body())) - {"data"}
    stray = reads - BACKEND_FIELDS
    assert not stray, (
        f"`viewKindOf` 读了后端没给的字段：{sorted(stray)}\n"
        "  分支只许读 code / task_status / data.*。自己攒的字段是第二个状态机的开头。"
    )


def test_an_unknown_state_renders_nothing_rather_than_guessing() -> None:
    """认不出的状态必须回 `null`，让调用处退回聊天视图。

    多一个没见过的状态码就渲染出一个像模像样、内容是编的页面，比不渲染糟得多——
    她会照着一个假页面去做决定。
    """
    assert re.search(r"return\s+null\s*;?\s*$", _view_kind_body().strip()), (
        "`viewKindOf` 的兜底不是 `return null`——认不出的状态会掉进某个分支里"
    )


def test_no_raw_identifier_reaches_the_screen() -> None:
    """`task_id` 之类不许出现在这一屏。

    那串东西给数据库看，而读屏软件会把它整串念出来。这个项目已经因为
    「当前任务：task-cf917fee2790476500fb」栽过一次。
    """
    assert "task_id" not in SOURCE, "Task Space 读了 task_id"
    assert "approval_digest" not in SOURCE, "Task Space 读了 approval_digest"


def test_unknown_task_type_says_something_human() -> None:
    """任务类型认不出时说「这件事」，不许兜底成英文枚举。

    `TASK_WORD[x] || x` 那种写法会把 `bill_payment` 直接印在屏幕上——
    而「界面上不许出现英文枚举值」是这个项目的硬约束。

    **判据搬家了，性质没变。** 这一条原先在这个文件里找
    `TASK_WORD[...] || '这件事'`，而那张表已经收敛进 `common.js`
    （四份表里的 `appointment` / `medication` 都不是后端的值，挂号任务从来没被
    认出来过）。逐项对照：

      旧：本文件里有一行 `TASK_WORD[x] || '这件事'`
      新：本文件**调用**共享的 `taskWord()`，而兜底与「表里不许有英文/不许发明键」
          由 `common.js` 和 `test_task_words_cover_the_real_enums.py` 保证——
          后者拿 `models.py` 的枚举核对，比在一个文件里找一行字符串强
    """
    assert re.search(r"window\.YouHuo\.taskWord\(", SOURCE), (
        "Task Space 不再用共享的 `taskWord()` 了——"
        "任务类型的说法必须只有一份，否则它会再漂一次"
    )
    common = (ROOT / "backend" / "static" / "common.js").read_text(encoding="utf-8")
    assert re.search(r"TASK_WORD\[[^\]]+\]\s*\|\|\s*'这件事'", common), (
        "共享的 `taskWord()` 兜底不是「这件事」——检查 common.js"
    )


def test_all_four_views_from_the_plan_exist() -> None:
    """计划书第十至十三节的四态都要有分支：普通任务 / 歧义 / 等家属 / 完成。"""
    for kind in ("ambiguous", "waiting", "done", "task"):
        assert f"'{kind}'" in SOURCE, f"少了 {kind} 这一态"


def test_the_module_is_a_pure_render_function() -> None:
    """不许自己发请求、不许自己读 DOM 之外的东西。

    纯函数是 Focus 几何那道确定性闸门能建起来的原因：三组构造好的数据直接喂给它，
    不碰缴费、不依赖数据库历史或执行顺序。Task Space 要保持同一个性质。
    """
    for forbidden in ("fetch(", "api(", "localStorage", "sessionStorage",
                      "addEventListener", "setTimeout"):
        assert forbidden not in SOURCE, (
            f"Task Space 里出现了 `{forbidden}`——它就不再是纯渲染了，"
            "确定性闸门也就没法直接喂数据给它"
        )
