"""标了「只有我看得到」的东西，家人读不到——在 `/api/v1` 这一层也读不到。

## 实测到的形状

老人自己记一条 `scope=private` 的长期记忆（「老伴的忌日 / 十月初三，那天她
不想被打扰」），然后：

    老人 GET /api/v1/memories    老伴的忌日  只有我看得到  十月初三，…
    女儿 GET /api/v1/memories    老伴的忌日  只有我看得到  十月初三，…   ← 泄露
    女儿 GET /v3/memories/{id}   （空）                                ← 这一层是对的

屏幕上那一格印着**「只有我看得到」**，而它正被别人看着。

## 成因：门面照抄了调用，没照抄视角

`memory_vault.list_visible` 的规则是 `viewer_role == "elder"` 给全部，
否则只给 `family_summary` / `family_shared`。`/api/v1` 那一行把 `viewer_role`
**写死成 `"elder"`**，而 `_elder_of(ctx)` 又把家人令牌解析成「她家那位老人」。
`api.py:786` 同一件事传的是 `viewer_role=actor.role.value`。

`/health-summary` 是同一个错的另一处：`list_health_events(..., ActorRole.ELDER)`
写死，于是 `if viewer_role == FAMILY: 滤掉 PRIVATE` 永远不生效。

和上一轮那五个「本人同意」被绕过是**同一个形状、同一个 `_elder_of()`**。
所以这一份判据不只钉那两行，还钉**两层之间不许分叉**：同一个家人，
`/api/v1` 能看到的不许比 `/v3` 多。

## 为什么每一条都要配一条「该看见的仍然看得见」

一律返回空也能让「私密项不外泄」全绿，而那会把家人端整个关掉。
这个项目已经为这件事写过一次判据（用药那条：家人 403 / **本人可以**）。
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

PRIVATE_KEY = "老伴的忌日"
PRIVATE_DETAIL = "十月初三，那天她不想被打扰"
SHARED_KEY = "喜欢的电台"


@pytest.fixture()
def client(tmp_path):
    from youhuo.api import create_app

    app = create_app(tmp_path / "priv.db", demo_mode=True)
    with TestClient(app) as c:
        yield c


def _tok(client: TestClient, actor: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _remember(client, headers, key, value, scope) -> str:
    """提一条并让老人点头——`list_visible` 只给 ACTIVE，不点头这条判据是空转的。"""
    r = client.post("/v3/memories/propose", headers=headers, json={
        "elder_id": "elder-demo", "key": key, "value": value,
        "sensitivity": "preference", "scope": scope,
        "purpose": "判据用",
    })
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    ok = client.post(f"/api/v1/memories/{mid}/approve",
                     headers=_tok(client, "elder-demo"))
    assert ok.status_code == 200, ok.text
    return mid


def test_the_family_cannot_read_a_private_memory(client: TestClient) -> None:
    elder, family = _tok(client, "elder-demo"), _tok(client, "daughter-demo")
    _remember(client, elder, PRIVATE_KEY, PRIVATE_DETAIL, "private")

    mine = client.get("/api/v1/memories", headers=elder)
    assert mine.status_code == 200, mine.text
    keys = [i["key"] for i in mine.json()["items"]]
    assert PRIVATE_KEY in keys, "老人自己都看不到，那是把功能关掉了，不是保护她"

    theirs = client.get("/api/v1/memories", headers=family)
    assert theirs.status_code == 200, theirs.text
    leaked = [i for i in theirs.json()["items"] if i["key"] == PRIVATE_KEY]
    assert not leaked, (
        f"家人读到了老人标「只有我看得到」的记忆：{leaked}\n"
        "那一格的文案就叫「只有我看得到」。")
    blob = theirs.text
    assert PRIVATE_DETAIL not in blob, "正文出现在家人拿到的响应里了"


def test_a_family_shared_memory_is_still_visible_to_the_family(client: TestClient) -> None:
    """上面那条不许靠「一律返回空」通过。"""
    elder, family = _tok(client, "elder-demo"), _tok(client, "daughter-demo")
    _remember(client, elder, SHARED_KEY, "交通广播", "family_shared")

    theirs = client.get("/api/v1/memories", headers=family)
    keys = [i["key"] for i in theirs.json()["items"]]
    assert SHARED_KEY in keys, (
        "标了 family_shared 的也读不到——那是把家人端整个关掉了")


def test_a_pending_private_proposal_is_not_family_visible(client: TestClient) -> None:
    """待确认那一段是**直接查库**的，`list_visible` 的范围过滤够不到它。

    少了单独那一句过滤，一条老人自己提的私密项在她点头之前全家可见、
    点头之后反而藏起来——越是没定的事越公开，正好反了。
    """
    elder, family = _tok(client, "elder-demo"), _tok(client, "daughter-demo")
    r = client.post("/v3/memories/propose", headers=elder, json={
        "elder_id": "elder-demo", "key": PRIVATE_KEY, "value": PRIVATE_DETAIL,
        "sensitivity": "sensitive", "scope": "private", "purpose": "判据用",
    })
    assert r.status_code == 200, r.text

    mine = client.get("/api/v1/memories", headers=elder).json()
    assert mine["pendingCount"] == 1, "老人自己都看不到这条待确认，她没法点头"

    theirs = client.get("/api/v1/memories", headers=family)
    pend = [i["key"] for i in theirs.json()["pending"]]
    assert PRIVATE_KEY not in pend, f"待确认的私密项泄露给家人了：{pend}"
    assert PRIVATE_DETAIL not in theirs.text


def test_the_two_layers_do_not_disagree_for_the_same_viewer(client: TestClient) -> None:
    """同一个家人，`/api/v1` 能看到的不许比 `/v3` 多。

    这一条比逐条列举更耐用：以后再加一种 scope，只要两层的规则分叉就会红。
    """
    elder, family = _tok(client, "elder-demo"), _tok(client, "daughter-demo")
    _remember(client, elder, PRIVATE_KEY, PRIVATE_DETAIL, "private")
    _remember(client, elder, SHARED_KEY, "交通广播", "family_shared")

    deep = client.get("/v3/memories/elder-demo", headers=family)
    assert deep.status_code == 200, deep.text
    allowed = {m["key"] for m in deep.json()}
    facade = {i["key"] for i in client.get(
        "/api/v1/memories", headers=family).json()["items"]}

    assert allowed, "深层给家人的是空集——这条判据在空转"
    assert facade <= allowed, (
        f"门面比深层多给了：{sorted(facade - allowed)}\n"
        "两层对同一个人给出不同的可见范围，宽的那一层就是缺陷。")


def test_the_family_health_summary_leaves_out_private_events(client: TestClient) -> None:
    elder, family = _tok(client, "elder-demo"), _tok(client, "daughter-demo")
    now = datetime.now(UTC).isoformat()
    made = client.post("/v4/health/events", headers=elder, json={
        "elder_id": "elder-demo", "kind": "checkup", "title": "私密体征",
        "event_at": now, "payload": {"label": "血压", "value": "128/82"},
        "scope": "private",
    })
    assert made.status_code == 200, made.text
    shared = client.post("/v4/health/events", headers=elder, json={
        "elder_id": "elder-demo", "kind": "checkup", "title": "可共享体征",
        "event_at": now, "payload": {"label": "体重", "value": "62.5"},
        "scope": "family_summary",
    })
    assert shared.status_code == 200, shared.text

    mine = client.get("/api/v1/health-summary", headers=elder)
    assert mine.status_code == 200, mine.text
    assert "私密体征" in mine.text or "血压" in mine.text, (
        "老人自己那一屏也没有——那是把功能关掉了")

    theirs = client.get("/api/v1/health-summary", headers=family)
    assert theirs.status_code == 200, theirs.text
    assert "私密体征" not in theirs.text, "家人读到了标私密的身体记录"
    assert "可共享体征" in theirs.text or "体重" in theirs.text, (
        "连 family_summary 的都没给——那不是保护，是关掉")
