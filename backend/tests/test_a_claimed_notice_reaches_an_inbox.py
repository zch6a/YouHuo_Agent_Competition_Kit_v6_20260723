"""链上说「已通知」，收件箱里就得真有那一条。

## 这道门从哪来

演示家庭那笔已完成的缴费，审计链上有两拍写着「已创建通知」——一条给家属
（请核对后确认），一条给老人（办好了）。实测两边的收件箱：

    /api/v1/notifications   count=0
    /v2/notifications       n=0

链上说通知发过了，收件箱里一条都没有。两边都不报错，两边看起来都正常。

## 成因

真实路径 `NotificationService.send`（`services.py:334`）做**两件**事：
先 `db.add_notification` 落一条通知行，再写审计、并把 `notification_id`
带进载荷。种子只做了后一半——它直接 `append_audit`，从没建过通知行。

这和这个文件邻居那道门（凭证少两格）是同一类：**演示数据的形状必须和真实
引擎一样**。`database.py` 里那段关于 `attempts` 的注释早就把这条规矩写下来了，
而它自己在下面几行又漏了一次。

## 判据

守的是性质：**一条 `NOTIFICATION_CREATED` 审计，必须对应一条真通知**，
并且收件人要对——给家属的不许落进老人的收件箱。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.models import ActorRole

V1 = "/api/v1"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUHUO_DEMO_STATE", "attention")
    app = create_app(tmp_path / "notice.db", demo_mode=True)
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, actor_id: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _notices(client: TestClient, headers: dict[str, str]) -> list[dict]:
    body = client.get("/v2/notifications", headers=headers).json()
    return body if isinstance(body, list) else body.get("items", [])


def test_every_claimed_notice_exists(client: TestClient) -> None:
    """审计链上每一拍「已通知」，都要有一条真通知行对应。"""
    elder = _login(client, "elder-demo")
    family = _login(client, "daughter-demo")

    claimed = 0
    for task_id in ("task-seed-bill-demo", "task-seed-await-demo"):
        cert = client.get(f"{V1}/payments/{task_id}/certificate",
                          headers=elder).json()
        claimed += sum(1 for s in cert["chain"]
                       if s["action"] == "NOTIFICATION_CREATED")
    assert claimed, "演示种子的链上一拍「已通知」都没有——这道门什么都没测到"

    delivered = len(_notices(client, elder)) + len(_notices(client, family))
    assert delivered >= claimed, (
        f"链上说发了 {claimed} 条通知，两边收件箱加起来只有 {delivered} 条。\n"
        "  `NotificationService.send` 做的是两件事：落一条通知行，"
        "再写审计。种子只做了后一半。")


def test_a_notice_lands_in_the_right_inbox(client: TestClient) -> None:
    """给家属的不许落进老人的收件箱，反过来也一样。

    没有这一条，上面那条可以被「把两条都塞给同一个人」满足——
    而收件人写错，在屏幕上就是老人收到一句「请在家属端核对后确认」。
    """
    elder = _login(client, "elder-demo")
    family = _login(client, "daughter-demo")

    for role, headers in ((ActorRole.ELDER, elder), (ActorRole.FAMILY, family)):
        for item in _notices(client, headers):
            assert item["recipient_role"] == role.value, (
                f"{role.value} 的收件箱里出现了发给 "
                f"{item['recipient_role']} 的通知：{item['message']!r}")

    kinds = {n["event_type"] for n in _notices(client, family)}
    assert "approval_required" in kinds, (
        f"家属没收到「请核对后确认」。收到的是：{sorted(kinds)}")
    kinds = {n["event_type"] for n in _notices(client, elder)}
    assert "task_completed" in kinds, (
        f"老人没收到「办好了」。收到的是：{sorted(kinds)}")


def test_no_two_notices_read_exactly_the_same(client: TestClient) -> None:
    """屏幕上不许出现两条读起来一模一样的通知。

    补上通知行之后实测家人端（430×932，把面板切过去读 textContent）：

        需要您接力确认 老人请求办理：支付2026-07水费 68.40元。… 2026/8/19 19:27:38
        需要您接力确认 老人请求办理：支付2026-07水费 68.40元。… 2026/8/19 19:27:38

    一字不差，连秒都一样。两笔演示缴费本来就是同一张 2026-07 水费
    （一笔办完、一笔在等），而 `day_offset`——那个为错开它们而声明的字段——
    **两处声明、零处读取**。读的人只会把这当成重复推送的缺陷。

    钉的是「读起来不一样」，不是「时间戳不一样」：把两条的正文改得能分辨
    也算修好了。屏幕上分得清就行。
    """
    family = _login(client, "daughter-demo")
    seen: list[tuple[str, str]] = []
    for n in _notices(client, family):
        # 家人端渲染的就是这两样：正文 + 到秒的时刻。
        key = (n["message"], n["created_at"][:19])
        assert key not in seen, (
            f"家人那一屏上有两条完全一样的通知：{key[0]!r} @ {key[1]}")
        seen.append(key)


def test_the_two_seeded_payments_do_not_share_a_day(client: TestClient) -> None:
    """两笔演示缴费的证据链不许落在同一天。

    这是上面那条的成因，单独钉：可信中心把两笔的事件按时间排在一起，
    同一天同一分钟的话，一条链读起来像是两个人在同一秒各点了一次头。
    """
    elder = _login(client, "elder-demo")
    days: dict[str, set[str]] = {}
    for task_id in ("task-seed-bill-demo", "task-seed-await-demo"):
        cert = client.get(f"{V1}/payments/{task_id}/certificate",
                          headers=elder).json()
        days[task_id] = {s["at"][:10] for s in cert["chain"] if s["at"]}
        assert days[task_id], f"{task_id} 的链上没有时间戳"
    a, b = days["task-seed-bill-demo"], days["task-seed-await-demo"]
    assert not (a & b), (
        f"两笔缴费的事件落在同一天：{sorted(a & b)}。"
        "`day_offset` 就是为错开它们而存在的——它此前是个从不被读的死字段。")


def test_a_notice_is_dated_when_it_happened(client: TestClient) -> None:
    """通知的时刻要和它那一拍对得上，不是播种的时刻。

    两者差着的是「这条通知是那天发的」和「这条通知是数据库建好那一刻发的」。
    可信中心把审计和通知排在一起，时刻对不上就自相矛盾。
    """
    elder = _login(client, "elder-demo")
    cert = client.get(f"{V1}/payments/task-seed-bill-demo/certificate",
                      headers=elder).json()
    beats = sorted(s["at"] for s in cert["chain"]
                   if s["action"] == "NOTIFICATION_CREATED")
    assert beats, cert["chain"]

    notices = sorted(n["created_at"] for n in _notices(client, elder)
                     if n["entity_id"] == "task-seed-bill-demo")
    assert notices, "老人那条通知不见了"
    # 落在这一笔的拍子区间里就算对上——不比字符串，时区表示可能不同。
    from datetime import datetime
    lo = min(datetime.fromisoformat(b) for b in beats)
    hi = max(datetime.fromisoformat(b) for b in beats)
    for raw in notices:
        when = datetime.fromisoformat(raw)
        assert lo <= when <= hi, (
            f"通知的时刻 {when} 不在这一笔的两拍「已通知」之间（{lo} .. {hi}）——"
            "它是按播种的时刻落的，不是按那一拍。")
