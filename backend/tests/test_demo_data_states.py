"""三个数据状态，以及 `normal` 那条证据链必须是完整的。

## 为什么这不是锦上添花

空态**掩盖布局问题**。实测：一旦老人端首页真的有待办，
`test_the_typing_route_is_in_the_first_screen_on_every_viewport` 就红了
（320×568 差 139px、667×375 差 306px、两个宽屏被 `button.tab.seg` 盖住）。
也就是说现在那套首页布局**是因为应用是空的才装得下**。

同一件事的另一面：`/v2/auth/visitor` 给每个浏览器开一个全新家庭，而它以前一条待办都
不种——所以**每一位**打开演示链接的人，第一屏都是「今天没有要办的事。」

## 三个状态

    empty      什么都不种。**pytest 默认**——一整批对话流程测试依赖
               「这个家庭一开始没有待办」（取消按名字找待办、裸「嗯」确认、
               访客隔离计数）。上一次把待办塞进 `seed_demo()` 当场红了 12 条。
    normal     3 条提醒 + 一笔**完整证据链**的已完成缴费 + 21 天作息基线。
    attention  normal 之上再有需要注意的偏离。

## 为什么 `normal` 那笔缴费必须是完整链

只写一行 `tasks.status='completed'` 的话，Trust Receipt 和 Audit 都会拿到一条**残缺**
的链，而那两页的全部价值就是链本身——UI 看起来完成了，证据却拼不出来。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from youhuo.database import Database, DemoIdentities

#: `trust.js` 的 `RECEIPT_STEPS` 认得的那些事件类型。
#:
#: 认不出的类型会走凭证的兜底（「系统留下一条记录」），而那条兜底是给**未来新增**
#: 事件类型留的降级路径，不是给种子数据用的。种出一条走兜底的链，
#: 等于让这一页对自己最重要的证据说「我也不知道这是什么」。
RECEIPT_KNOWN_EVENTS = {
    "TASK_CREATED", "TEACH_BACK_VERIFIED", "TEACH_BACK_REJECTED", "ELDER_CONFIRMED",
    "FAMILY_APPROVAL_RECORDED", "FAMILY_APPROVED_AND_EXECUTED", "FAMILY_REJECTED",
    "FAMILY_APPROVED_EXECUTION_FAILED", "NOTIFICATION_CREATED",
}


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "states.db")
    yield database
    database.close()


def _chain(database: Database, family_id: str) -> list[tuple[str, datetime]]:
    rows = database._conn.execute(
        "SELECT event_type, created_at FROM audit_events WHERE family_id=? ORDER BY id",
        (family_id,)).fetchall()
    return [(r[0], datetime.fromisoformat(r[1])) for r in rows]


def test_the_scenario_seeds_a_chain_the_receipt_can_actually_read(db: Database) -> None:
    ids = db.seed_demo("t")
    made = db.seed_demo_scenario(ids, "completed_bill_payment")
    assert made >= 6, f"只种了 {made} 拍——一次缴费的经过讲不完整"

    events = [e for e, _t in _chain(db, ids.family_id) if e != "DEMO_SEEDED"]
    unknown = [e for e in events if e not in RECEIPT_KNOWN_EVENTS]
    assert not unknown, (
        f"这些事件类型凭证认不出来，会被渲染成「系统留下一条记录」：{unknown}"
    )
    # 一次缴费的骨架：提出 → 复述核对 → 本人确认 → 家人同意并执行。
    for required in ("TASK_CREATED", "TEACH_BACK_VERIFIED", "ELDER_CONFIRMED",
                     "FAMILY_APPROVED_AND_EXECUTED"):
        assert required in events, f"链里缺了 {required} —— 这一步没有证据"


def test_the_chain_timestamps_look_like_they_really_happened(db: Database) -> None:
    """时间戳必须有真实间隔——这一条是 Evidence Platform 的可信度本身。

    改之前实测：六条时间戳全落在 **20 毫秒**内，「家人点了同意」与「他确认了这一笔」
    相隔 **8 毫秒**。可信中心唯一的工作就是让人相信这件事真实发生过，
    而那串时间戳当场把它否掉了。

    修法是让事件在**产生时**就带间隔（`append_audit(created_at=…)`），
    **不是**在前端把显示值改写成好看的样子。三个表面读的是同一份事实，
    一旦其中一个开始美化，它们就不再是同一份了。
    """
    ids = db.seed_demo("t")
    db.seed_demo_scenario(ids, "completed_bill_payment")
    stamps = [t for e, t in _chain(db, ids.family_id) if e != "DEMO_SEEDED"]
    assert len(stamps) >= 6

    span = (stamps[-1] - stamps[0]).total_seconds()
    assert span >= 60, f"整条链只跨了 {span:.3f} 秒——读起来不像真的发生过"

    gaps = [(stamps[i + 1] - stamps[i]).total_seconds() for i in range(len(stamps) - 1)]
    assert min(gaps) >= 5, (
        f"最小间隔只有 {min(gaps):.3f} 秒。相邻两步之间至少要有人能反应过来的时间——"
        f"全部间隔：{[round(g, 1) for g in gaps]}"
    )


def test_the_chain_still_verifies_after_backdating(db: Database) -> None:
    """带自定义时间戳的事件，哈希链必须照样验得过。

    `created_at` 参与 `canonical` 串的哈希，所以传时间进去不等于绕过链——
    这一条把「安全性没有削弱」从注释变成断言。
    """
    ids = db.seed_demo("t")
    db.seed_demo_scenario(ids, "completed_bill_payment")
    assert db.verify_audit_chain(ids.family_id) is True, (
        "种完场景之后审计链验不过了——那这份演示数据比没有更糟"
    )


def test_seeding_twice_does_not_duplicate(db: Database) -> None:
    """幂等。刷几次页面就堆出两条缴费经过的话，凭证会自相矛盾。"""
    ids = db.seed_demo("t")
    first = db.seed_demo_scenario(ids, "completed_bill_payment")
    second = db.seed_demo_scenario(ids, "completed_bill_payment")
    assert first > 0 and second == 0, f"第二次又种了 {second} 拍"


def test_an_unknown_scenario_is_refused(db: Database) -> None:
    ids = db.seed_demo("t")
    with pytest.raises(ValueError, match="没有这个场景"):
        db.seed_demo_scenario(ids, "whatever")


def test_pytest_runs_in_the_empty_state_by_default() -> None:
    """默认必须是 `empty`。

    这一条守的是一次真实的教训：上一次把三条待办塞进 `seed_demo()`（**测试也在用**的
    那个种子函数）当场红了 12 条——「取消」按名字找待办、裸「嗯」确认、访客隔离计数，
    全都依赖「这个家庭一开始没有待办」。层选错了。
    """
    assert not os.getenv("YOUHUO_DEMO_STATE"), (
        "测试环境里设了 YOUHUO_DEMO_STATE——那会让一批对话流程测试的前提改变"
    )
    assert os.getenv("YOUHUO_SEED_BASELINE", "false").lower() != "true", (
        "测试环境里打开了 YOUHUO_SEED_BASELINE，等价于 normal 态"
    )
