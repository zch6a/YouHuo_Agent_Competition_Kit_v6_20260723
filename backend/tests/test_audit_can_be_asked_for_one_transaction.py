"""`/v2/audit?entity_id=` 只回那一件事的链，而且不因此削弱别的东西。

## 为什么加这个参数

可信中心那份凭证要的是**一件事的完整链**，而它原先只能「取最近 200 条，再在
客户端按 `entity_id` 筛」。那两件事不一样：一个家庭用久了，第 201 条之前的事务
就再也拼不出完整的链——**而页面上看不出来**。它会渲染出一份少了前几步的凭证，
而凭证的全部价值就是「每一步都在」。这类缺陷不会报错、不会崩，只会安静地少几行。

## 这份文件同时守三件事

  ① 过滤真的发生在服务端，而且 limit 作用在**这一件事**上
  ② 它是**加法**：不给参数时行为和以前一模一样
  ③ 它没有变成一条跨家庭读取的路——过滤发生在 `family_id` 之内
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "audit.db", demo_mode=True)
    with TestClient(app) as c:
        yield c


def _token(client: TestClient, actor: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_two_tasks(client: TestClient, elder: dict[str, str]) -> list[str]:
    """造两件不同的事，好证明过滤真的在分辨它们。"""
    ids = []
    for text in ("帮我交这个月的水费", "我想去医院挂个号"):
        session = client.post("/v2/sessions", json={}, headers=elder).json()["session_id"]
        r = client.post("/v2/chat", json={"session_id": session, "text": text},
                        headers=elder).json()
        assert r.get("task_id"), f"「{text}」没有立起任务，这条测试造不出被测状态：{r}"
        ids.append(r["task_id"])
    return ids


def test_it_returns_only_that_transaction(client):
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    first, second = _make_two_tasks(client, elder)

    got = client.get(f"/v2/audit?entity_id={first}", headers=family).json()
    entities = {e["entity_id"] for e in got["events"]}
    assert entities == {first}, f"要的是一件事的链，回来的却有 {entities}"

    other = client.get(f"/v2/audit?entity_id={second}", headers=family).json()
    assert {e["entity_id"] for e in other["events"]} == {second}
    assert got["events"] != other["events"], "两件事回来的链一样——过滤没生效"


def test_without_the_parameter_nothing_changed(client):
    """不给参数就和以前一样：整条家庭链。

    加参数最容易出的事故不是新路径写错，是**旧路径被顺手改坏**。
    """
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    ids = _make_two_tasks(client, elder)

    everything = client.get("/v2/audit", headers=family).json()
    entities = {e["entity_id"] for e in everything["events"]}
    for task_id in ids:
        assert task_id in entities, f"不带参数时少了 {task_id} 的事件"


def test_the_limit_applies_to_that_transaction_not_the_whole_family(client):
    """limit 要作用在这一件事的事件上。

    这正是「取 200 条再自己筛」和「让服务端筛」的区别——前者的 limit 被别的事务
    的流水吃掉。这里用 `limit=1` 把区别放大：如果过滤发生在取完之后，
    这一件事很可能一条都剩不下。
    """
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    first, _second = _make_two_tasks(client, elder)

    one = client.get(f"/v2/audit?limit=1&entity_id={first}", headers=family).json()
    assert len(one["events"]) == 1, f"limit=1 应当回一条，回了 {len(one['events'])}"
    assert one["events"][0]["entity_id"] == first


def test_chain_self_check_still_covers_the_whole_chain(client):
    """`chain_valid` 必须仍然是**整条**家庭链的自校验，不是过滤后子集的。

    这是实现时踩得到的那个坑：一条被截出来的子序列里 `prev_hash` 本来就接不上，
    拿它做自校验会永远报「链断了」——而这一页最重要的那句话就是「链是完整的」。
    """
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    first, _ = _make_two_tasks(client, elder)

    filtered = client.get(f"/v2/audit?entity_id={first}", headers=family).json()
    assert filtered["chain_valid"] is True, (
        "按事务过滤之后 chain_valid 变成了假——它被算在子集上了"
    )
    # 而子集本身确实接不上，这正是不能拿它自校验的理由。
    events = filtered["events"]
    if len(events) > 1:
        assert any(cur["prev_hash"] != prev["event_hash"]
                   for prev, cur in zip(events, events[1:])), (
            "子集里每一条都首尾相接——那说明这个家庭只有这一件事，"
            "这条测试没有造出它要说明的情况"
        )


def test_it_is_not_a_way_to_read_another_family(client):
    """过滤发生在 `family_id` 之内：拿别人的 id 来问，什么也拿不到。"""
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    _make_two_tasks(client, elder)

    got = client.get("/v2/audit?entity_id=task:someone-elses", headers=family).json()
    assert got["events"] == [], "用一个不属于这个家庭的 id 竟然拿到了事件"


def test_the_elder_still_cannot_read_the_audit(client):
    """权限一行没动：完整审计仍然只对绑定家属开放。"""
    elder = _token(client, "elder-demo")
    r = client.get("/v2/audit?entity_id=task:whatever", headers=elder)
    assert r.status_code == 403, f"老人拿到了完整审计：{r.status_code}"
