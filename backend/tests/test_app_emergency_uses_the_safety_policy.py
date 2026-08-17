"""紧急呼叫要走产品自己的安全策略。

## 此前的样子

这个 App 里有**两套 SOS**：

    /api/v1/emergency/call   这一层自己写的  → 只找家庭成员发一条通知
    /v4/safety/sos           产品的安全子系统 → 按策略把社区网格员放进接力名单

前者完全不读 `safety_policies_v4`，于是 `notify_community` 这个开关
**从来没有被读过**，社区网格员永远不在名单里——而「家人没接就升级到社区」
正是那份策略存在的理由。两套并行，其中一套必然是错的。

## 这里钉的是策略被读到了，不是「接口通不通」

一个一路 200 的紧急呼叫恰恰是最危险的那种：它看起来什么都对。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"
ELDER = "elder-demo"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "sos.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def elder_headers(client: TestClient) -> dict[str, str]:
    token = client.post("/v2/auth/demo", json={"actor_id": ELDER}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _policy(client: TestClient, headers: dict) -> dict:
    r = client.get(f"/v4/safety/policy/{ELDER}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _set_policy(client: TestClient, headers: dict, **changes) -> None:
    body = {k: v for k, v in _policy(client, headers).items()
            if k not in ("family_id", "updated_at")}
    body.update(changes)
    r = client.put("/v4/safety/policy", headers=headers, json=body)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- 阳性对照


def test_the_demo_household_actually_has_a_community_contact(client, elder_headers) -> None:
    """先证明这个家庭里**有**社区网格员，而且策略是开的。

    没有这一条，下面每一条都可能因为「这个家庭本来就没有社区联系人」
    而假绿：名单里没有社区，判据通过，但原因完全不同。
    """
    assert _policy(client, elder_headers)["notify_community"] is True
    contacts = client.post("/v4/safety/sos", headers=elder_headers,
                           json={"elder_id": ELDER}).json()["contacts"]
    assert any(c["contact_role"] == "community" for c in contacts), (
        "演示家庭里没有社区联系人，这一组判据不成立"
    )


# ---------------------------------------------------------------- 名单


def test_the_escalation_chain_includes_the_community_worker(client) -> None:
    r = client.post(f"{V1}/emergency/call", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["communityPrepared"] is True, "策略说要通知社区，名单里却没有"
    assert "社区" in [c["role"] for c in body["escalation"]]


def test_turning_the_policy_off_takes_the_community_out_of_the_chain(client, elder_headers) -> None:
    """`notify_community=False` 时社区不许出现在名单上。

    这条判据分辨的是「读了策略」和「不管策略一律加上社区」——
    两者在默认演示数据上表现一模一样。
    """
    _set_policy(client, elder_headers, notify_community=False)
    body = client.post(f"{V1}/emergency/call", json={}).json()
    assert body["communityPrepared"] is False
    assert "社区" not in [c["role"] for c in body["escalation"]]
    assert "社区网格员" not in body["message"]


def test_the_chain_is_ordered_by_priority(client, elder_headers) -> None:
    """名单按 priority 排。紧急时第一个联系谁，不能靠调用方自己再排一遍。

    顺序由 `v4_store.safety_contacts` 的 `ORDER BY priority` 提供，这一层不再排。
    第一版这里排了一遍，变异证明那句 `sorted()` 永远改变不了结果——
    于是判据也咬不到任何东西。现在它守的是真正提供顺序的那个地方。

    默认演示家庭只有一个联系人，一个元素怎么排都有序，判据形同虚设。
    所以先造第二个，且**故意按插入顺序反着来**。
    """
    db = client.app.state.db
    db._conn.execute(
        """INSERT INTO safety_contacts_v4(id,family_id,elder_id,name,contact_role,
                                          channel,address_masked,priority,enabled)
           VALUES(?,?,?,?,?,?,?,?,1)""",
        ("contact-first-demo", "fam-demo", ELDER, "大女儿", "family",
         "phone", "***-***-0001", 1),
    )
    db._conn.commit()

    chain = client.post(f"{V1}/emergency/call", json={}).json()["escalation"]
    assert len(chain) >= 2, f"造了第二个联系人却只拿到 {len(chain)} 个，判据不成立"
    assert [c["priority"] for c in chain] == sorted(c["priority"] for c in chain), (
        f"名单没按优先级排：{[(c['name'], c['priority']) for c in chain]}"
    )
    assert chain[0]["name"] == "大女儿"


def test_the_chain_shows_the_masked_column_not_some_other_field(client) -> None:
    """联系方式取的是 `address_masked` 那一列。

    `safety_contacts_v4` 里根本没有未打码的号码列，所以这一层泄露不了完整号码。
    真正会发生的错是**取错列**——把名字或渠道塞进联系方式那一格，
    界面上就会显示「社区网格员：社区网格员」。
    """
    chain = client.post(f"{V1}/emergency/call", json={}).json()["escalation"]
    assert chain, "名单是空的，这条判据不成立"
    for c in chain:
        assert "*" in c["contact"], f"联系方式那一格取错了列：{c}"
        assert c["contact"] != c["name"]
        assert c["contact"] not in ("phone", "sms", "app")


# ---------------------------------------------------------------- 话不能说过头


def test_it_never_claims_the_community_was_already_called(client) -> None:
    """名单上有，和已经打过，是两件事。

    这个原型不自动拨号，v4 那一侧也只是 `community_escalation_prepared`。
    在紧急场景里把「准备好了」说成「已经联系了」，是给一个假保证。
    """
    message = client.post(f"{V1}/emergency/call", json={}).json()["message"]
    for lie in ("已经通知社区", "已通知社区", "社区已联系", "已经联系了社区"):
        assert lie not in message, f"说过头了：{message}"
    assert "也在名单上" in message


# ---------------------------------------------------------------- 证据链


def test_the_audit_row_records_whether_the_policy_was_consulted(client) -> None:
    """审计里要写清这次呼叫准备了几级接力。

    事后要能回答「那天按下去之后，社区到底在不在名单里」——
    只写一句「紧急呼叫」回答不了。
    """
    client.post(f"{V1}/emergency/call", json={})
    db = client.app.state.db
    rows = [r[0] for r in db._conn.execute(
        "SELECT payload_json FROM audit_events WHERE event_type='app.emergency.requested'")]
    assert rows, "没有写下紧急呼叫的审计"
    payload = json.loads(rows[-1])
    assert payload["community_escalation_prepared"] is True
    assert payload["escalation_count"] >= 1


def test_a_broken_policy_lookup_does_not_break_the_call(client, monkeypatch) -> None:
    """名单取不到，呼叫本身也必须成立。

    紧急按钮不能因为一个附带信息查不到就失败——那会让老人以为没按上。
    """
    store = client.app.state.v4_store

    def boom(*_a, **_k):
        raise RuntimeError("策略表炸了")

    monkeypatch.setattr(store, "get_safety_policy", boom)
    r = client.post(f"{V1}/emergency/call", json={})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["escalation"] == []
    assert r.json()["communityPrepared"] is False


def test_the_throttle_still_holds_with_the_chain_attached(client) -> None:
    """连点两下仍然只叫一次人，但名单每次都要给。

    名单是这一屏要显示的东西；第二次按下去不给名单，界面会突然空掉，
    看起来像出错了。
    """
    first = client.post(f"{V1}/emergency/call", json={}).json()
    second = client.post(f"{V1}/emergency/call", json={}).json()
    assert first["notified"], "第一次没通知到任何人，这条判据不成立"
    assert second["notified"] == [], "一分钟内重复推送了"
    assert second["escalation"] == first["escalation"], "第二次名单空了"
