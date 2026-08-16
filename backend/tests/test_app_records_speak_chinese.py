"""记录页不许把内部事件名漏到屏幕上，也不许整页落到兜底文案。

这一条是连错两版换来的。`/api/v1/records` 要把审计事件翻成人话，而我写翻译表时：

  第一版 `task.created`      —— 点号命名，凭印象写的
  第二版 `task_completed`    —— 小写下划线，从源码里 grep 到的字面量
  库里真正存的 `TASK_CREATED` —— **全大写下划线**

两版都「看起来正常」：记录页照常渲染，每一条都落到兜底的「办了一件事」，
八条里零条翻译对，而屏幕上完全看不出哪里不对——一个全是兜底的列表，和一个
翻译正确的列表，在截图里长得一模一样。

所以这里不测「有没有兜底」，测两件能证伪的事：
  1. 界面上不许出现 `TASK_CREATED` / `app.payment.prepared` 这种内部枚举
     （这是这个项目的硬约束：界面上不许出现英文枚举值）
  2. 后端**真的会写**的那些事件类型，翻译表里必须都有——漏一个，那一条就会
     静默变成「办了一件事」
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "youhuo" / "app_api.py"


def _words_table() -> dict[str, tuple[str, str, str]]:
    """把 `_WORDS` 从源码里解析出来，不导入模块（它需要 db/engine）。"""
    text = SRC.read_text(encoding="utf-8")
    start = text.index("_WORDS: dict[str, tuple[str, str, str]] = {")
    body = text[start:]
    end = body.index("\n    }")
    body = body[: end]
    out = {}
    for m in re.finditer(r'"([^"]+)":\s*\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)', body):
        out[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    return out


def test_the_table_is_not_empty() -> None:
    """自证：解析器真的读到了东西。

    一个解析失败返回空 dict 的探针，会让下面每一条断言都轻松通过。
    """
    table = _words_table()
    assert len(table) >= 10, f"只解析出 {len(table)} 条，解析器大概没在工作"


def test_no_internal_enum_reaches_the_screen() -> None:
    """翻译出来的标题必须是中文，不能是内部枚举。"""
    offenders = [
        f"{key} → {title}"
        for key, (title, _kind, _icon) in _words_table().items()
        if not re.search(r"[一-龥]", title)
    ]
    assert not offenders, f"这些事件翻出来的标题里没有中文：{offenders}"


def test_every_event_the_backend_writes_has_a_translation() -> None:
    """后端会写的每一种事件类型，翻译表里都要有。

    漏掉的那一条不会报错，它会静默显示成「办了一件事」——而记录页正是老人
    用来确认「这件事真的按我说的办了」的地方。
    """
    table = _words_table()
    # 库里实际出现过的取值（大写下划线），加上本门面自己写的那几个。
    written = {
        "TASK_CREATED",
        "ELDER_CONFIRMED",
        "TEACH_BACK_VERIFIED",
        "FAMILY_APPROVAL_RECORDED",
        "FAMILY_APPROVED_AND_EXECUTED",
        "NOTIFICATION_CREATED",
        "DEMO_SEEDED",
        "app.payment.prepared",
        "app.payment.teach_back",
        "app.payment.awaiting_family",
        "app.emergency.requested",
    }
    missing = sorted(written - set(table))
    assert not missing, (
        f"这些事件没有中文说法，记录页上会显示成兜底的「办了一件事」：{missing}"
    )


@pytest.mark.parametrize("kind", ["支付", "健康", "服务"])
def test_every_filter_tab_has_something_to_show(kind: str) -> None:
    """记录页那四个筛选页签（全部/支付/健康/服务）都要能筛到东西。

    分类是在翻译表里定死的；如果某一类一条都没有，那个页签点下去就是空的，
    而用户看不出是「真的没有」还是「筛坏了」。
    """
    kinds = {k for _t, k, _i in _words_table().values()}
    assert kind in kinds, f"没有任何事件属于「{kind}」这一类，那个页签会永远是空的"
