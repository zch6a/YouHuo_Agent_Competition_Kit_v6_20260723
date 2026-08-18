"""老人端的同意记忆：看得见、点得了头、撤得回。

## 为什么此前没有

「同意记忆 + 可核验的代办」是这个产品的核心主张。v3 那一侧
（`/v3/memories/*`）是完整的，而且规则明确：

    家属可以**提**       api.py:662
    只有老人能**批准**   api.py:678「只有老人本人可以批准长期记忆」
    只有老人能**撤销**   api.py:694

也就是说这条流程**按设计必须在老人端完成**——而老人端一个入口都没有。
女儿提的那条会永远停在 `proposed`，老人看不见、也点不了头，
**两边界面都正常，不报任何错**。这和用药计划是同一个形状的洞。

顺带量到：种子里同意记忆 **0 条**。招牌功能连演示数据都没有。

## 这里钉的是守卫，不是 200

「可撤回」是「同意」成立的前提。撤不回的记忆不叫同意记忆，叫记录。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"
ELDER = "elder-demo"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "mem.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def family_headers(client: TestClient) -> dict[str, str]:
    token = client.post("/v2/auth/demo", json={"actor_id": "daughter-demo"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _propose(client: TestClient, headers: dict, key: str,
             value=None, sensitivity="preference", scope="family_shared") -> str:
    r = client.post("/v3/memories/propose", headers=headers, json={
        "elder_id": ELDER, "key": key, "value": value or {"说明": "示例"},
        "sensitivity": sensitivity, "scope": scope,
        "purpose": f"记住{key}，用于日常提醒。",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "proposed", "家属提的应当是待确认，这条判据的前提不成立"
    return r.json()["id"]


# ---------------------------------------------------------------- 家人提，老人点头


def test_a_memory_the_family_proposed_waits_for_the_elder(client, family_headers) -> None:
    """还没点头的**不能**混进「已经记住的」。

    混进去就是在说「它已经记住了」，而老人根本没同意过。
    """
    _propose(client, family_headers, "爱喝的茶")
    body = client.get(f"{V1}/memories").json()
    assert [m["key"] for m in body["pending"]] == ["爱喝的茶"]
    assert body["items"] == [], "没点头的跑进了生效列表"
    assert body["count"] == 0 and body["pendingCount"] == 1
    assert "等您点头" in body["message"]


def test_approving_moves_it_into_the_active_list(client, family_headers) -> None:
    mid = _propose(client, family_headers, "爱喝的茶")
    r = client.post(f"{V1}/memories/{mid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已记住"
    body = client.get(f"{V1}/memories").json()
    assert [m["key"] for m in body["items"]] == ["爱喝的茶"]
    assert body["pending"] == []


def test_declining_does_not_record_it(client, family_headers) -> None:
    mid = _propose(client, family_headers, "怕吵")
    assert client.post(f"{V1}/memories/{mid}/decline").json()["status"] == "没有记"
    body = client.get(f"{V1}/memories").json()
    assert body["count"] == 0 and body["pendingCount"] == 0


def test_deciding_twice_is_a_conflict_not_a_silent_success(client, family_headers) -> None:
    """已经处理过的再点一次，不能说成「刚刚记下了」。"""
    mid = _propose(client, family_headers, "爱喝的茶")
    client.post(f"{V1}/memories/{mid}/approve")
    again = client.post(f"{V1}/memories/{mid}/approve")
    assert again.status_code == 409
    assert "已经处理" in again.json()["detail"]


def test_a_memory_that_is_not_yours_is_a_404(client) -> None:
    for verb in ("approve", "decline", "forget"):
        r = client.post(f"{V1}/memories/memory-nope/{verb}")
        assert r.status_code == 404, f"{verb} 回的是 {r.status_code}"


# ---------------------------------------------------------------- 撤得回


def test_forgetting_actually_removes_it(client, family_headers) -> None:
    """**「可撤回」是「同意」成立的前提。** 撤不回的记忆不叫同意记忆，叫记录。"""
    mid = _propose(client, family_headers, "爱喝的茶")
    client.post(f"{V1}/memories/{mid}/approve")
    assert client.get(f"{V1}/memories").json()["count"] == 1

    r = client.post(f"{V1}/memories/{mid}/forget")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已忘掉"
    body = client.get(f"{V1}/memories").json()
    assert body["count"] == 0
    assert "爱喝的茶" not in [m["key"] for m in body["items"]]


def test_a_forgotten_memory_is_gone_from_the_v3_surface_too(client, family_headers) -> None:
    """撤回要在**整个系统**里生效，不只是这一屏。

    只在门面里过滤掉，等于「界面上看不见但它还在」——那是这套机制
    最不能有的东西。
    """
    mid = _propose(client, family_headers, "爱喝的茶")
    client.post(f"{V1}/memories/{mid}/approve")
    client.post(f"{V1}/memories/{mid}/forget")

    token = client.post("/v2/auth/demo", json={"actor_id": ELDER}).json()["access_token"]
    v3 = client.get(f"/v3/memories/{ELDER}", headers={"Authorization": f"Bearer {token}"})
    assert v3.status_code == 200
    assert "爱喝的茶" not in [m["key"] for m in v3.json()], "v3 那一侧还看得见"


# ---------------------------------------------------------------- 说人话


def test_the_screen_never_shows_raw_enum_values(client, family_headers) -> None:
    """界面上不许出现 `preference` / `family_shared` 这种。"""
    mid = _propose(client, family_headers, "爱喝的茶",
                   sensitivity="sensitive", scope="private")
    client.post(f"{V1}/memories/{mid}/approve")
    item = client.get(f"{V1}/memories").json()["items"][0]
    for raw in ("preference", "personal", "sensitive",
                "private", "family_summary", "family_shared"):
        assert raw not in item["sensitivity"], f"敏感度显示成了 {item['sensitivity']}"
        assert raw not in item["scope"], f"可见范围显示成了 {item['scope']}"
    assert item["sensitivity"] == "敏感信息"
    assert item["scope"] == "只有我看得到"


def test_the_value_is_flattened_not_dumped_as_json(client, family_headers) -> None:
    """`value` 是自由 JSON，直接 `str(dict)` 会让老人看到大括号和引号。"""
    mid = _propose(client, family_headers, "爱喝的茶",
                   value={"茶": "龙井", "浓淡": "淡一点"})
    client.post(f"{V1}/memories/{mid}/approve")
    detail = client.get(f"{V1}/memories").json()["items"][0]["detail"]
    for junk in ("{", "}", "'", '"'):
        assert junk not in detail, f"细节里出现了 {junk!r}：{detail}"
    assert "龙井" in detail and "淡一点" in detail


def test_it_says_when_it_remembers_nothing(client) -> None:
    """空态要说清楚是「什么都没记」，不是「没加载出来」。"""
    body = client.get(f"{V1}/memories").json()
    assert body["count"] == 0
    assert "什么都没" in body["message"]


def test_every_memory_says_why_it_is_kept(client, family_headers) -> None:
    """`purpose` 是这套机制的核心：记一样东西必须说得出用途。"""
    mid = _propose(client, family_headers, "爱喝的茶")
    client.post(f"{V1}/memories/{mid}/approve")
    item = client.get(f"{V1}/memories").json()["items"][0]
    assert item["purpose"].strip(), "记住了一件事却说不出为什么"


def test_it_reports_how_long_the_memory_lasts(client, family_headers) -> None:
    """记忆有期限，到期自动忘掉——这一屏要看得见还剩多久。"""
    mid = _propose(client, family_headers, "爱喝的茶")
    client.post(f"{V1}/memories/{mid}/approve")
    item = client.get(f"{V1}/memories").json()["items"][0]
    assert item["expiresAt"], "没有过期时间"
    assert isinstance(item["daysLeft"], int) and item["daysLeft"] > 0


# ---------------------------------------------------------------- P0 与记录


def test_reading_the_screen_never_changes_a_memory(client, family_headers) -> None:
    """渲染一屏不许产生业务变更。"""
    _propose(client, family_headers, "爱喝的茶")
    db = client.app.state.db

    def rows() -> list[tuple]:
        return db._conn.execute(
            "SELECT id, status FROM memory_items ORDER BY id").fetchall()

    before = [tuple(r) for r in rows()]
    for _ in range(5):
        client.get(f"{V1}/memories")
    assert [tuple(r) for r in rows()] == before, "读了几屏，记忆的状态变了"


def test_the_records_page_has_a_sentence_for_every_memory_event(client, family_headers) -> None:
    """走完一遍，记录页不许出现兜底文案。

    加一个事件类型必须同时加一条 `_WORDS`，否则记录页落到「办了一件事」——
    而那一行看起来完全正常。
    """
    a = _propose(client, family_headers, "爱喝的茶")
    b = _propose(client, family_headers, "怕吵")
    client.post(f"{V1}/memories/{a}/approve")
    client.post(f"{V1}/memories/{b}/decline")
    client.post(f"{V1}/memories/{a}/forget")

    items = client.get(f"{V1}/records", params={"limit": 300}).json()["items"]
    assert items, "记录页是空的，这条判据不成立"
    assert not [i for i in items if i["title"] == "办了一件事"], (
        "有记忆相关的事件类型没登记进 `_WORDS`"
    )
    titles = {i["title"] for i in items}
    assert "家人想让优活记一件事" in titles
    assert "让优活忘掉一条" in titles
