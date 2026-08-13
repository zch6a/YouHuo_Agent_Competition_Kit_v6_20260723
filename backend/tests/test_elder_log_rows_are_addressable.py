"""老人端「记录」的每一行要能指向它说的那件事。

## 为什么需要这个字段

`.log-item` 现在是纯 `<div>`：`who` / `time` / `what` 三段文字，点不动，
也没有任何地址。于是「上个月的水费交了没」这句话没有落点——语音能表达的东西
比底部导航四格多得多，而参考产品里（MediMate 的 `Nutrition` 是
`tabBarButton: () => null` 的隐藏目的地、注释写着 `navigable via voice`）
语音正是用来扩展可达面的。要指向一笔事务，它得先有地址。

`entity_id` 本来就在端点手里：`api.py` 的 `entity_belongs_to_elder(event.entity_id)`
拿它做权限过滤，然后丢掉。所以这是把已有的事实带出来，不是新造一个。

## 名字为什么是 `about_id` 而不是 `entity_id`

审计事件那边叫 `entity_id`。而这个模型是同一份事实的**叙事投影**——
两侧本来就该用不同的词汇（Folk Care 的 `AuditEvent` 与 `ActivityFeedItem`
是两张表，同一个事件写两条记录）。混用会让人以为这两个模型能互相替代。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from youhuo.models import AuditEvent
from youhuo.privacy import elder_activity_entries

ELDER = "elder-1"
BASE = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)


def _event(row: int, event_type: str, entity_id: str | None,
           actor_id: str = ELDER) -> AuditEvent:
    return AuditEvent(
        id=row,
        family_id="fam-1",
        actor_id=actor_id,
        event_type=event_type,
        entity_id=entity_id,
        payload={},
        created_at=BASE + timedelta(seconds=row),
        # 字段名是从 models.py 抄来的，不是猜的：第一版写了 `digest` / `prev_digest`，
        # 而 `StrictModel` 的 `extra="forbid"` 当场拦下——真名是 `prev_hash` / `event_hash`。
        prev_hash="0" * 64,
        event_hash="1" * 64,
    )


def _project(events: list[AuditEvent]):
    """所有 `task-*` 都算这位老人自己的，把权限那一层从这几条测试里排除掉。"""
    return elder_activity_entries(
        events,
        entity_belongs_to_elder=lambda eid: True if eid else None,
        elder_id=ELDER,
    )


def _allowed_task_event_type() -> str:
    """从 allow-list 里挑一个会产出 `kind='task'` 的事件类型。

    不硬编码事件名：那张表改一个字，这几条测试就会以「一条记录都没有」的形式
    静默失效，而那看起来和「功能正常但没有数据」一模一样。
    """
    from youhuo.privacy import _ELDER_ACTIVITY_LABELS

    for event_type, (_who, kind) in _ELDER_ACTIVITY_LABELS.items():
        if kind == "task":
            return event_type
    raise AssertionError(
        "allow-list 里没有任何产出 kind='task' 的事件类型——"
        "「记录」这一页因此不可能有内容，先去核对 _ELDER_ACTIVITY_LABELS"
    )


def test_every_task_row_carries_the_thing_it_is_about() -> None:
    event_type = _allowed_task_event_type()
    entries = _project([
        _event(1, event_type, "task-aaa"),
        _event(2, event_type, "task-bbb"),
    ])
    assert entries, "投影出来一条都没有——那下面的断言什么都没测到"
    for entry in entries:
        assert entry.about_id, (
            f"这一行没有主体：{entry.who} / {entry.what}。"
            "语音要能指向它，它就必须有地址。"
        )


def test_two_different_transactions_are_not_collapsed_into_one_line() -> None:
    """同一句话 + 不同事务 = 两行，不是一行。

    `_ELDER_ACTIVITY_TEXT` 是每个事件类型一句**固定**的话，所以连着办两笔缴费，
    两笔的同一步骤会产出逐字相同的 `who` + `what`。旧的去重只比这两个字段，
    于是相邻时第二笔会安静消失——一位老人办了两件事，记录里只剩一件。

    实测过这个形状：一次沙箱里两笔事务各产出「您复述并确认了这件事。」
    和「开始为您办理一件事。」，逐字相同。
    """
    event_type = _allowed_task_event_type()
    entries = _project([
        _event(1, event_type, "task-first"),
        _event(2, event_type, "task-second"),   # 相邻，且文案与上一条完全相同
    ])
    subjects = [e.about_id for e in entries]
    assert len(entries) == 2, (
        f"两笔不同的事务被折叠成了 {len(entries)} 行：{subjects}。"
        "去重的判据必须带上 about_id。"
    )
    assert set(subjects) == {"task-first", "task-second"}, subjects


def test_the_same_transaction_repeating_still_collapses() -> None:
    """同一笔事务重试产生的重复行，仍然要折叠成一条。

    这是上一条的反面。少了这一条，把 about_id 加进判据之后就可以简单地
    「不再折叠任何东西」，而那会让一次重试在页面上变成三行同样的话——
    去重本来是为了这个才存在的。
    """
    event_type = _allowed_task_event_type()
    entries = _project([
        _event(1, event_type, "task-same"),
        _event(2, event_type, "task-same"),
        _event(3, event_type, "task-same"),
    ])
    assert len(entries) == 1, f"同一笔事务的重复行没有折叠：{[e.about_id for e in entries]}"


def test_rows_without_a_subject_still_render() -> None:
    """取不到主体的行照样要显示，只是点不动。

    `about_id` 可选是有意的：allow-list 里有些事件本来就不挂在任务或提醒上。
    把它做成必填会让那些行整个消失——那是 silent delete。
    """
    event_type = _allowed_task_event_type()
    entries = _project([_event(1, event_type, None)])
    assert len(entries) == 1, "没有主体的行被丢掉了"
    assert entries[0].about_id is None
    assert entries[0].what, "这一行没有可读的内容"


def test_the_elder_log_never_renders_the_subject_as_text() -> None:
    """`about_id` 只进 `dataset`，永远不渲染成文字。

    它是 `task-2a2728fe86f54c06b52e` 这种东西。手机框里只放「哪件事、到哪一步」，
    原始标识符属于 `/judge`。这一条与
    `test_the_app_surface_never_renders_a_raw_identifier` 是同一条纪律，
    这里从**字段名**这一侧再钉一次：那道闸门认的是渲染点的表达式形状，
    而 `entry.about_id` 是一个它没见过的新名字。
    """
    source = (Path(__file__).resolve().parents[2]
              / "backend" / "static" / "elder.js").read_text(encoding="utf-8")
    sinks = [
        r"textContent\s*=\s*[^;\n]*\babout_id\b",
        r"\bline\s*\([^)]*\babout_id\b",
        r"addBubble\s*\([^)]*\babout_id\b",
        r"speak\s*\([^)]*\babout_id\b",
    ]
    hits = [s for s in sinks if re.search(s, source)]
    assert not hits, (
        f"elder.js 把 about_id 渲染成了文字（命中 {hits}）。"
        "它只能进 dataset 或链接目标。"
    )
