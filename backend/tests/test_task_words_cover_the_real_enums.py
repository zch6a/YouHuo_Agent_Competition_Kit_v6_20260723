"""任务类型与状态的中文说法，必须照后端枚举写。

## 这条判据是被什么换来的

任务**类型**词表在 `elder.js`、`task-space.js`、`task-detail.js`、`trust.js` 里各有
一份，三处注释各自写着「这是第三份 / 第四份，要在 Phase C 收敛到一处」。收敛的
理由不是整洁——**它们已经漂了**：

    后端 TaskType（models.py）  hospital_registration / bill_payment
                                / reminder / form_assistance
    前端三份表里写的             appointment / bill_payment / medication

`appointment` 与 `medication` 不是后端的值（`engine.py:769` 放进聊天响应
`data.task_type` 的就是 `TaskType` 枚举本身），所以那两个键永远命中不了；而三个
真实类型里有三个不在表里。实测后果：一件挂号任务在老人端的状态行是
「正在办**这件事**」，而不是「正在办：**挂号**」。

**它躲过了「界面不许出现枚举值」那道闸门**，因为兜底是中文——泄漏的不是英文，
是具体性。同一形状这个项目栽过一次：`family.js` 的 `EMOTION_LABEL` 缺三个值、
多三个后端没有的值，把最要紧的 `urgent` 印成了英文。

## 类型收敛，状态**不**收敛——这是一个判断，不是遗漏

任务类型的说法与读者无关：一件缴费对老人和家人都叫「缴费」。所以它收进
`common.js`，一处定义。

任务**状态**不是：同一个 `awaiting_elder_confirmation`，
`family.js` 说「等老人复述确认」（家人在读别人的事），
`task-detail.js` 说「等您确认」（老人在读自己的事）。
把它们合成一张表会让其中一边说错话。所以状态表按受众各留一份，
这份文件转而要求**每一份都覆盖全部 7 个状态、且不发明后端没有的键**。

事实源是 `youhuo/models.py` 的枚举本身，不是手抄清单——手抄的表会漂，
这份文件存在的理由就是它们漂过。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from youhuo.models import TaskStatus, TaskType

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
COMMON = STATIC / "common.js"

TYPE_VALUES = {t.value for t in TaskType}
STATUS_VALUES = {s.value for s in TaskStatus}

#: 只属于任务类型 / 状态、不会和别的枚举撞名的键。
#:
#: `completed` / `cancelled` / `failed` **不在**这里：`ReminderStatus` 也有它们，
#: 而 `elder.js` 的 `REMINDER_STATUS` 是一张完全正当的、另一套枚举的表。
#: 第一版检测器没有这条，于是它把那张表也点了名——按那个误报去合并，
#: 会把两套词汇混成一套，正是这份文件在批评的那个错。
DISTINCTIVE = {
    "bill_payment", "hospital_registration", "form_assistance",
    "collecting", "awaiting_elder_confirmation", "awaiting_family_approval",
    "executing",
}


def _tables_in(source: str) -> list[tuple[str, dict[str, str], int]]:
    """把一份 JS 里所有 `const X = {...}` 的表抽出来。

    三种排版都要认，而每一种都是被一次真实的漏检换来的：

      ① 多行 `const X = {\\n  a: '…',\\n};`
      ② **单行** `const X = {a: '…', b: '…'};`
         第一版正则要求 `^};` 独占一行，于是 `task-space.js` 那张写成一行的表
         整份漏掉——一个只认某种排版的检测器，等于给「换个写法就能绕过」发许可。
      ③ **有缩进的**（`common.js` 的表在 IIFE 里，缩进两格）
         第一版把 `const` 锚在行首，于是共享表一张都读不到，而失败信息是
         「后端有 TaskType.bill_payment，而 common.js 的 TASK_WORD 里没有它」
         ——一句指着错误方向的话，而那个键明明就在那儿。
    """
    found = []
    for match in re.finditer(r"^[ \t]*const (\w+) = \{(.*?)\};", source, re.S | re.M):
        name, body = match.group(1), match.group(2)
        # 值可以是字符串，也可以是 `['字', 'tone']` 这样的数组——取第一个字符串。
        entries = dict(re.findall(r"(\w+):\s*\[?\s*'([^']*)'", body))
        if entries:
            found.append((name, entries, source[: match.start()].count("\n") + 1))
    return found


def _shared(name: str) -> dict[str, str]:
    """common.js 里那张共享表。解析不到就报红，不是返回空表。"""
    tables = {n: e for n, e, _ in _tables_in(COMMON.read_text(encoding="utf-8"))}
    assert name in tables, f"common.js 里找不到 `const {name}`——它被改名或删掉了"
    assert tables[name], f"`{name}` 解析出来是空的——这份文件会全部空转"
    return tables[name]


@pytest.mark.parametrize("value", sorted(TYPE_VALUES))
def test_every_task_type_has_a_chinese_word(value: str) -> None:
    words = _shared("TASK_WORD")
    assert value in words, (
        f"后端有 TaskType.{value}，而 common.js 的 TASK_WORD 里没有它。\n"
        f"  表里现有：{sorted(words)}\n"
        "  少一个键不会报错、也不会漏英文——只会让那类任务在屏幕上退成「这件事」。"
    )
    assert not re.search(r"[A-Za-z]", words[value]), (
        f"TaskType.{value} 的说法里有英文：{words[value]}"
    )


def test_the_shared_type_table_invents_nothing() -> None:
    """多出来的键比缺键更隐蔽：它看起来像「这个类型我们处理了」，而它永远不会命中。

    `appointment` 和 `medication` 就是这样在三份表里活了很久。
    """
    extra = sorted(set(_shared("TASK_WORD")) - TYPE_VALUES)
    assert not extra, (
        f"common.js 的 TASK_WORD 里有后端没有的键：{extra}\n"
        "  它们永远不会命中，而表看起来像已经处理了那些情况。"
    )


def test_no_page_keeps_a_private_type_table() -> None:
    """页面脚本里不许再各自定义一份任务**类型**表。

    这一条才是防回归的那一条：上面几条只保证共享的那份是对的，
    而缺陷的形状是「有人又在自己文件里写了一份」。
    """
    offenders = []
    for path in sorted(STATIC.glob("*.js")):
        if path.name == "common.js":
            continue
        for name, entries, line in _tables_in(path.read_text(encoding="utf-8")):
            if set(entries) & (DISTINCTIVE & TYPE_VALUES):
                offenders.append(f"{path.name}:{line} const {name} = {sorted(entries)}")
    assert not offenders, (
        "这些文件里还各自留着一份任务类型表：\n    " + "\n    ".join(offenders) + "\n"
        "  用 `window.YouHuo.taskWord()`，不要再抄一份——"
        "三份表已经漂到有两个键永远命中不了。"
    )


def test_every_audience_status_table_covers_all_seven() -> None:
    """状态表按受众各留一份，但每一份都必须认全 7 个状态、且不发明键。

    不合并是有意的（见模块 docstring）：同一个 `awaiting_elder_confirmation`，
    家人端说「等老人复述确认」，老人端说「等您确认」。合成一张会让一边说错话。
    合并的是**要求**，不是文字。
    """
    problems = []
    for path in sorted(STATIC.glob("*.js")):
        for name, entries, line in _tables_in(path.read_text(encoding="utf-8")):
            keys = set(entries)
            # 认「这是一张任务状态表」的判据：它带着只有任务状态才有的键。
            # 这样 `REMINDER_STATUS`（scheduled/notified/…）不会被卷进来。
            if not (keys & (DISTINCTIVE & STATUS_VALUES)):
                continue
            # 而且它的值必须是**给人读的字**。
            #
            # `elder.js` 的 `byState` 也按任务状态建键，但它的值是语音球的内部
            # 动画状态名（`confirming` / `executing` / `idle`）——那些英文是故意的，
            # 不是文案。这条判据问的是「用户读到的字对不对」，所以值里没有中文的
            # 表根本不在它的管辖范围内。
            #
            # 这个误报是在检测器变强（开始能看见缩进的表）之后立刻冒出来的。
            # 按误报去改 `byState` 会把一组状态标识符翻译成中文，然后动画全部失效。
            chinese = sum(1 for w in entries.values() if re.search(r"[一-鿿]", w))
            if chinese * 2 < len(entries):
                continue
            missing = sorted(STATUS_VALUES - keys)
            extra = sorted(keys - STATUS_VALUES)
            if missing:
                problems.append(f"{path.name}:{line} {name} 少了 {missing}")
            if extra:
                problems.append(f"{path.name}:{line} {name} 多了后端没有的 {extra}")
            for key, word in entries.items():
                if key in STATUS_VALUES and re.search(r"[A-Za-z]", word):
                    problems.append(f"{path.name}:{line} {name}[{key}] 里有英文：{word}")
    assert not problems, "状态表和后端枚举对不上：\n    " + "\n    ".join(problems)
