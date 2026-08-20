"""替她做的决定不算她同意。

## 这道门从哪来

这个产品的两句招牌话：

    「同意记忆」——优活要记住一件事，得她点头
    「家属补的药」——女儿加的药，要她本人同意才开始吃

底层两处都在执行它：

    /v3/memories/decide      `actor.role != ELDER → 403 只有老人本人可以批准长期记忆。`
    /v4/medications/decide   `actor.role != ELDER → 403 只有老人本人可以激活家属补充的用药计划。`

而 `/api/v1`（老人端门面）那一层**照抄了调用，没照抄守卫**，并且传的是
`_elder_of(ctx)`——家人令牌会被解析成「她家那位老人」，于是底层那句
「只有本人」的校验，被一个不属于调用者的 id 满足了。

实测（女儿的令牌，修之前）：

    /v3/memories/decide               403  只有老人本人可以批准长期记忆。
    /api/v1/memories/{id}/approve     200  好，我记住「早上散步的时间」了
    /api/v1/memories/{id}/forget      200  好，「早上散步的时间」我不再记着了
    /api/v1/medications/{id}/approve  200  好，钙片从今天开始按计划吃。

五个决定，家人都能替她做。**而两边界面都正常，审计里还老老实实记着是女儿干的**
——记录是诚实的，控制不在了。

## 判据

三件事一起钉，缺一条这道门都能被绕过：

  · 家人做这五个决定 → 403
  · **老人自己做同一件事 → 成**（否则「一律 403」也能让上面那条绿，
    而那会把这条流程整个关掉——它本来就只有老人这一端能完成）
  · 底层那两条原有的 403 不许消失（守卫要在两层都在，不是搬家）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "consent.db", demo_mode=True,
                     seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


def _head(client: TestClient, actor_id: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _a_plan_waiting_for_her(client: TestClient) -> str:
    """女儿加一份药。家属建的计划 `active=False`，等她点头。"""
    fam = _head(client, "daughter-demo")
    r = client.post("/v4/medications", headers=fam, json={
        "elder_id": "elder-demo", "display_name": "钙片",
        "normalized_name": "钙片", "dose_text": "一次一片",
        "times_local": ["08:30"], "start_date": "2026-08-20",
        "stock_units": 30, "units_per_dose": 1,
    })
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["active"] is False, (
        "家属建的计划一入库就是 active——那这条「等她点头」的流程根本不存在，"
        "下面所有判据都在测一件没发生的事。")
    return plan["id"]


def _a_memory_waiting_for_her(client: TestClient) -> str:
    fam = _head(client, "daughter-demo")
    r = client.post("/v3/memories/propose", headers=fam, json={
        "elder_id": "elder-demo", "key": "早上散步的时间",
        "value": "每天上午九点", "sensitivity": "preference",
        "purpose": "到点了提醒她带钥匙"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_the_family_cannot_approve_a_medication_for_her(client: TestClient) -> None:
    plan_id = _a_plan_waiting_for_her(client)
    fam = _head(client, "daughter-demo")
    for action in ("approve", "decline"):
        r = client.post(f"{V1}/medications/{plan_id}/{action}", headers=fam)
        assert r.status_code == 403, (
            f"女儿调 `/medications/{{id}}/{action}` 拿到 {r.status_code}：{r.text[:120]}\n"
            "  家属补的药要她本人点头才开始吃——这是这条流程存在的全部理由。")


def test_the_family_cannot_decide_a_memory_for_her(client: TestClient) -> None:
    memory_id = _a_memory_waiting_for_her(client)
    fam = _head(client, "daughter-demo")
    for action in ("approve", "decline", "forget"):
        r = client.post(f"{V1}/memories/{memory_id}/{action}", headers=fam)
        assert r.status_code == 403, (
            f"女儿调 `/memories/{{id}}/{action}` 拿到 {r.status_code}：{r.text[:120]}\n"
            "  「可撤回」是「同意」成立的前提，所以撤回也只能是本人。")


def test_she_can_still_decide_it_herself(client: TestClient) -> None:
    """**阳性对照。** 一律 403 也能让上面两条绿，而那会把流程整个关掉。

    这条流程按设计**只有老人这一端能完成**（`/v4/medications/decide` 只认
    ELDER）。所以「家人不行」必须配上「本人可以」，否则女儿加的药就永远
    停在待确认——那正是这一整条流程当初要修的问题。
    """
    plan_id = _a_plan_waiting_for_her(client)
    elder = _head(client, "elder-demo")

    pending = client.get(f"{V1}/medications/pending", headers=elder).json()
    assert any(i["id"] == plan_id for i in pending["items"]), (
        f"她那一侧看不到这份等她点头的药：{pending}")

    ok = client.post(f"{V1}/medications/{plan_id}/approve", headers=elder)
    assert ok.status_code == 200, ok.text
    assert ok.json()["active"] is True, ok.json()

    after = client.get(f"{V1}/medications/pending", headers=elder).json()
    assert not any(i["id"] == plan_id for i in after["items"]), (
        "点过头了，它还挂在「等您确认」里。")

    memory_id = _a_memory_waiting_for_her(client)
    got = client.post(f"{V1}/memories/{memory_id}/approve", headers=elder)
    assert got.status_code == 200, got.text
    assert client.post(f"{V1}/memories/{memory_id}/forget",
                       headers=elder).status_code == 200


def test_the_lower_layer_still_refuses_too(client: TestClient) -> None:
    """守卫要在**两层**都在，不是从底层搬到门面。

    没有这一条，「把 `/v3` 和 `/v4` 的 403 删掉、只留门面那道」也能让
    上面全绿——而那样任何一个不经门面的调用方都能绕过去。
    """
    fam = _head(client, "daughter-demo")
    memory_id = _a_memory_waiting_for_her(client)
    r = client.post("/v3/memories/decide", headers=fam,
                    json={"memory_id": memory_id, "approve": True})
    assert r.status_code == 403, f"/v3/memories/decide 放行了家人：{r.status_code}"

    plan_id = _a_plan_waiting_for_her(client)
    r = client.post("/v4/medications/decide", headers=fam,
                    json={"record_id": plan_id, "approve": True})
    assert r.status_code == 403, f"/v4/medications/decide 放行了家人：{r.status_code}"
