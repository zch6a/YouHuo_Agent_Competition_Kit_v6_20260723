"""照护页那两段在演示家庭里必须有内容，而「可以试试」里只许放真的建议。

## 缺口是量出来的

打 `care.js` 真正调用的那几个接口（路径逐条抄自源码，不猜）：

    今天  /v7/daily-report/{id}    ✓ overall=typical，3 段分项
    用药  /v4/medications/{id}     ✓ 1 个计划
    身体  /v4/health/events/{id}   ✗ 0 条
    心情  /v4/reports/emotion/{id} ✗ event_count=0
    安全  /v4/safety/policy/{id}   ✓（联系人档案是 0，另计）

原因不是数据落在窗口外——`list_health_events` 根本没有时间窗。是这两张表
**从来没被种过**：`v4_store.seed_demo()` 只种安全策略和一位社区网格员。

## 上一次尝试是怎么死的

KNOWN_ISSUES 记着：上一个 agent 做这件事时，**它自己写的测试报「情绪趋势是编造
出来的上升」**。所以这一份种子刻意是**稳定**的（七天里六天平静、一天孤单），
趋势报 `stable_or_insufficient`——演示数据可以有内容，但不能替产品把结论编出来。

它还警告过一个陷阱：合成回填写 `activity_events_v4`，而无交互预警读那张表的
`MAX(occurred_at)`。**这里一行都不碰那张表**，那个陷阱不适用。

## 「可以试试」那一栏

补上数据之后立刻显形了一个既有缺陷：`safe_suggestions` 收的是每条情绪事件的
`privacy_safe_note`，而 `calm` 那一句是「未检测到明显情绪风险信号。」——一句
**陈述**。于是「可以试试：」下面挂着一条根本不是建议的话。
空态掩盖的不只是布局。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app


@pytest.fixture()
def visitor(tmp_path):
    """一位**全新访客**——评委走的正是这条路，不是默认演示家庭。"""
    app = create_app(tmp_path / "care.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as client:
        sandbox = client.post("/v2/auth/visitor", json={}).json()
        yield client, sandbox


def test_the_body_section_is_not_empty(visitor):
    client, sandbox = visitor
    fam = {"Authorization": f"Bearer {sandbox['family_token']}"}
    events = client.get(f"/v4/health/events/{sandbox['elder_id']}", headers=fam).json()
    assert events, "照护页「身体」段在演示家庭里是空的——评委打开就是一片空白"
    for event in events:
        assert event["event_at"] <= date.today().isoformat() + "T23:59:59", (
            f"种子写了一条**未来**的健康记录：{event['title']} @ {event['event_at']}"
        )


def test_the_mood_section_is_not_empty(visitor):
    client, sandbox = visitor
    fam = {"Authorization": f"Bearer {sandbox['family_token']}"}
    end = date.today()
    start = end - timedelta(days=13)
    report = client.get(
        f"/v4/reports/emotion/{sandbox['elder_id']}"
        f"?period_start={start}&period_end={end}", headers=fam).json()
    summary = report["summary"]
    assert summary["event_count"] > 0, "照护页「心情」段在演示家庭里是空的"
    assert summary["label_counts"], "有事件却没有类别统计——那一栏会是空的"


def test_the_seeded_mood_is_stable_not_an_invented_recovery(visitor):
    """种子不许编一个「情绪逐日好转」的故事。

    这正是上一次尝试死掉的地方：它自己的测试报「情绪趋势是编造出来的上升」。
    演示数据可以有内容，但**不能替产品把结论编出来**——一条好转曲线是这个产品
    最不该伪造的东西。
    """
    client, sandbox = visitor
    fam = {"Authorization": f"Bearer {sandbox['family_token']}"}
    end = date.today()
    start = end - timedelta(days=13)
    summary = client.get(
        f"/v4/reports/emotion/{sandbox['elder_id']}"
        f"?period_start={start}&period_end={end}", headers=fam).json()["summary"]
    assert summary["trend"] != "distress_decreasing", (
        "种出来的情绪趋势是「比上两周松快一些」——那是编出来的好转，"
        "而这份演示数据并没有任何真实的改善过程支撑它"
    )


def test_suggestions_only_contain_actual_suggestions(visitor):
    """「可以试试」里不许出现「未检测到明显情绪风险信号。」这种陈述句。

    它是 `calm` 的 `privacy_safe_note`，真实分析器给的。混进建议栏之后，
    屏幕上「可以试试：」下面挂着一条不是建议的话——补上演示数据之前，
    这一段是空的，所以没人看得见。
    """
    client, sandbox = visitor
    fam = {"Authorization": f"Bearer {sandbox['family_token']}"}
    end = date.today()
    start = end - timedelta(days=13)
    summary = client.get(
        f"/v4/reports/emotion/{sandbox['elder_id']}"
        f"?period_start={start}&period_end={end}", headers=fam).json()["summary"]
    suggestions = summary["safe_suggestions"]
    assert suggestions, "一周里有孤单记录，却一条建议都没有"
    for line in suggestions:
        assert "建议" in line, (
            f"「可以试试」里混进了一句不是建议的话：{line}"
        )


def test_a_real_deployment_gets_no_demo_history(tmp_path):
    """开关关掉（真实部署的默认值）时，一条演示历史都不许种。

    这条和上面几条同等重要：演示数据是给演示的，真实用户不该被塞。
    """
    app = create_app(tmp_path / "real.db", demo_mode=True, seed_baseline_history=False)
    with TestClient(app) as client:
        sandbox = client.post("/v2/auth/visitor", json={}).json()
        fam = {"Authorization": f"Bearer {sandbox['family_token']}"}
        events = client.get(
            f"/v4/health/events/{sandbox['elder_id']}", headers=fam).json()
        assert events == [], f"真实部署被塞了 {len(events)} 条演示健康记录"
