"""这一层借记忆表存的东西，不许出现在「优活替您记着什么」里。

## 这道门从哪来

老人拖了一下字号滑块，然后打开「我的 · 优活替我记着什么」。实测：

    优活替您记着 1 件事。哪一条不想让它记了，随时可以忘掉。
      key      elder_app_settings
      detail   voiceSpeaker：0
      daysLeft 3649

`/api/v1/settings` 把发音人和配色存进了**记忆表**（键 `elder_app_settings`），
而 `/api/v1/memories` 列的就是这张表，没有任何过滤。

三件事一起坏了：

  · 两个英文内部标识印在老人屏幕上——「界面上不许出现英文枚举值」是硬约束
  · 那句话下面就是「忘掉」。她按一下，`revoke` 把这一条置成 REVOKED，
    `_pref_item` 从此跳过它，**她自己的发音人和配色就没了**。
    一个破坏性动作，挂在一张说的是别的事情的屏幕上。
  · 「优活替您记着 1 件事」这句话本身是假的——它一件事都没替她记，
    那一条是这一层自己的存储。

## 判据

只把它从列表里滤掉是不够的：同意/拒绝/忘掉三条路按 id 收参数，
id 在审计里就有。所以四条路都要堵，而且**设置本身必须还在**——
把设置一起弄丢的"修法"能让前三条全绿。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.app_api import _INTERNAL_MEMORY_KEYS

V1 = "/api/v1"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "prefs.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


def _save_a_setting(client: TestClient) -> None:
    r = client.put(f"{V1}/settings", json={"fontScale": 1.4, "voiceSpeaker": 1})
    assert r.status_code == 200, r.text


def _propose(client: TestClient, key: str, value: str) -> str:
    """走真接口提一条待确认的记忆（`/v3/memories/propose` 是家人端那条路）。"""
    token = client.post("/v2/auth/demo",
                        json={"actor_id": "daughter-demo"}).json()["access_token"]
    r = client.post("/v3/memories/propose",
                    headers={"Authorization": "Bearer " + token},
                    json={"elder_id": "elder-demo", "key": key, "value": value,
                          "sensitivity": "preference", "purpose": "到点了提醒她带钥匙"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_saving_a_setting_does_not_become_a_memory(client: TestClient) -> None:
    """存一次设置之后，那张列表必须还是空的。"""
    before = client.get(f"{V1}/memories").json()
    assert before["count"] == 0, f"演示数据里本来就有记忆，这道门测不到东西：{before}"

    _save_a_setting(client)

    after = client.get(f"{V1}/memories").json()
    keys = [m["key"] for m in after["items"] + after["pending"]]
    assert not (set(keys) & set(_INTERNAL_MEMORY_KEYS)), (
        f"存了一次设置，「优活替您记着什么」里就多出了 {keys}。"
        "那是这一层的存储细节，不是她同意过的记忆。")
    assert after["count"] == 0, (
        f"屏幕上写着「{after['message']}」，而她一件事都没让它记。")


def test_nothing_on_that_list_speaks_english(client: TestClient) -> None:
    """那张列表上一个英文标识都不许有。

    单独一条，因为上面那条可以被「把 key 改个中文名照样列出来」满足——
    而真正的问题是这一条根本不该在这张列表上。

    **列表必须先有东西。** 第一版只存了一次设置就来查：修好之后列表是空的，
    下面那个循环一次都不执行，这条判据于是空转通过——而它声称在检查的那件事
    一个字符都没被看过。空过和通过在结果里长得一模一样。
    """
    _save_a_setting(client)
    _propose(client, "早上散步的时间", "每天上午九点")
    body = client.get(f"{V1}/memories").json()
    listed = body["items"] + body["pending"]
    assert listed, "列表是空的，这条判据什么都没检查到"
    for item in listed:
        for field in ("key", "detail", "purpose"):
            text = str(item.get(field) or "")
            assert not any(c.isascii() and c.isalpha() for c in text), (
                f"记忆列表的 `{field}` 上出现了英文：{text!r}")


def test_forgetting_cannot_erase_her_settings(client: TestClient) -> None:
    """就算拿到了 id，「忘掉」也不许作用在设置上。

    这是这道门最要紧的一条：`forget` 不可逆，而 id 在审计里就有。
    """
    _save_a_setting(client)
    saved = client.get(f"{V1}/settings").json()
    assert saved["voiceSpeaker"] == 1, saved

    # 直接从库里拿那一条的 id——模拟 id 从别处泄漏（审计里就有）。
    memory_id = next(
        (m.id for m in client.app.state.db.list_memories("fam-demo", "elder-demo")
         if m.key in _INTERNAL_MEMORY_KEYS), None)
    assert memory_id, "取不到那一条设置的 id，这道门什么都没测到"

    for path in (f"{V1}/memories/{memory_id}/forget",
                 f"{V1}/memories/{memory_id}/decline",
                 f"{V1}/memories/{memory_id}/approve"):
        r = client.post(path, json={})
        assert r.status_code == 404, (
            f"{path} 回了 {r.status_code}——这三条路不许作用在设置上。")

    # 最要紧的一句：设置还在。
    still = client.get(f"{V1}/settings").json()
    assert still["voiceSpeaker"] == 1, (
        f"她的发音人被抹掉了：存的时候是 1，现在是 {still['voiceSpeaker']}。")


def test_a_real_memory_still_shows_and_can_be_forgotten(client: TestClient) -> None:
    """真正的记忆一条都不许被这道过滤误伤。

    没有这一条，把 `/memories` 改成永远返回空列表也能让上面三条全绿——
    而「可撤回」是「同意」成立的前提，是这套机制的关键动作。
    """
    item_id = _propose(client, "早上散步的时间", "每天上午九点")

    pending = client.get(f"{V1}/memories").json()
    assert any(m["key"] == "早上散步的时间" for m in pending["pending"]), pending

    assert client.post(f"{V1}/memories/{item_id}/approve", json={}).status_code == 200
    active = client.get(f"{V1}/memories").json()
    assert any(m["key"] == "早上散步的时间" for m in active["items"]), active

    assert client.post(f"{V1}/memories/{item_id}/forget", json={}).status_code == 200
    gone = client.get(f"{V1}/memories").json()
    assert not any(m["key"] == "早上散步的时间" for m in gone["items"]), gone
