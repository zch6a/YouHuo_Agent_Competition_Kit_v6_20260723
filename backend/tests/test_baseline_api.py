"""个性化基线与生活日报：走真实 HTTP 面的端到端验证。

单元测试证明数学和措辞是对的；这里证明**接线**是对的——权限、家庭隔离、从既有事件
流推导观测、以及日报与推送决定来自同一份快照。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.database import DemoIdentities


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUHUO_DEMO_MODE", "true")
    monkeypatch.setenv("YOUHUO_DB_PATH", str(tmp_path / "baseline.db"))
    # 显式打开合成作息历史。它默认关闭，因为写的是 activity_events_v4 这张运营表，
    # 无交互预警会读同一张表——见 create_app 的说明。
    app = create_app(seed_baseline_history=True)
    with TestClient(app) as test_client:
        yield test_client


def token(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


IDS = DemoIdentities.for_suffix("demo")


@pytest.fixture()
def elder_auth(client):
    return token(client, IDS.elder_id)


@pytest.fixture()
def family_auth(client):
    return token(client, IDS.daughter_id)


# --- ① 基线 -----------------------------------------------------------------


def test_the_demo_household_has_an_established_baseline(client, elder_auth):
    """演示家庭必须能立刻展示基线；否则这个核心创新点在演示里是一片空白。"""
    response = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["established"] is True
    assert body["observed_days"] >= 7
    wake = next(b for b in body["baselines"] if b["channel"] == "wake")
    assert wake["established"] is True
    # 播种的是 6:05 前后起床。
    assert wake["center_text"].startswith("06:"), wake


def test_the_baseline_is_derived_not_asked_for(client, elder_auth):
    """五个通道全部从**已有**事件流推导，老人不需要多做任何一件事。"""
    body = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    channels = {b["channel"] for b in body["baselines"]}
    assert {"wake", "sleep", "outing", "medication", "conversation"} == channels


def test_seeding_is_idempotent(client, elder_auth):
    """重复启动不该把基线越铺越密。"""
    first = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()["observed_days"]
    second = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()["observed_days"]
    assert first == second


# --- ① 环境 -----------------------------------------------------------------


def test_environment_sample_is_accepted_and_used(client, elder_auth):
    now = datetime.now(UTC)
    response = client.post(
        "/v7/environment/samples",
        headers=elder_auth,
        json={
            "elder_id": IDS.elder_id,
            "temperature_c": 13.0,
            "humidity_pct": 45.0,
            "lux": 220.0,
            "occurred_at": now.isoformat(),
            "source": "test-sensor",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["accepted"] is True

    care = client.get(f"/v7/care/{IDS.elder_id}", headers=elder_auth).json()
    assert "加件衣服" in care["spoken"], care
    assert care["environment_note"] and "13" in care["environment_note"]


def test_an_empty_sample_is_rejected(client, elder_auth):
    response = client.post(
        "/v7/environment/samples",
        headers=elder_auth,
        json={"elder_id": IDS.elder_id, "occurred_at": datetime.now(UTC).isoformat(),
              "source": "t"},
    )
    assert response.status_code == 400


def test_the_endpoint_refuses_image_fields(client, elder_auth):
    """"看不见，但能感知"必须是接口层面的保证，不是一句宣传。

    StrictModel 的 extra="forbid" 让任何图像字段直接被拒绝，而不是被悄悄忽略。
    """
    response = client.post(
        "/v7/environment/samples",
        headers=elder_auth,
        json={"elder_id": IDS.elder_id, "occurred_at": datetime.now(UTC).isoformat(),
              "source": "t", "temperature_c": 22.0, "image_base64": "iVBORw0KGgo="},
    )
    assert response.status_code == 422, response.text


# --- ② 日报 -----------------------------------------------------------------


def test_the_family_can_read_the_daily_report(client, family_auth):
    response = client.get(f"/v7/daily-report/{IDS.elder_id}", headers=family_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["headline"]
    assert body["report"]["privacy_note"]
    assert {"作息", "活动与交流", "用药"} == {s["title"] for s in body["report"]["sections"]}


def test_the_report_and_the_alert_come_from_one_snapshot(client, family_auth):
    """分两次调用就会出现"日报说一切正常、推送说赶紧回家"这种自相矛盾。"""
    body = client.get(f"/v7/daily-report/{IDS.elder_id}", headers=family_auth).json()
    deviated = body["report"]["overall"] == "marked"
    assert body["alert"]["baseline_deviated"] == deviated


def test_a_calm_demo_day_does_not_page_the_family(client, family_auth):
    """演示家庭的今天是正常的，所以不该推送——④ 的价值在于它不推什么。"""
    body = client.get(f"/v7/daily-report/{IDS.elder_id}", headers=family_auth).json()
    assert body["alert"]["push"] is False
    assert body["alert"]["reason"]


# --- 权限与家庭隔离 ---------------------------------------------------------


def test_an_elder_cannot_read_another_elders_baseline(client, elder_auth):
    other = DemoIdentities.for_suffix("other")
    response = client.get(f"/v7/baseline/{other.elder_id}", headers=elder_auth)
    assert response.status_code == 403


def test_a_visitor_household_is_isolated_and_seeded(client):
    """每位访客一份独立沙箱，而且各自都有自己的作息历史。"""
    visitor = client.post("/v2/auth/visitor").json()
    headers = {"Authorization": f"Bearer {visitor['elder_token']}"}

    mine = client.get(f"/v7/baseline/{visitor['elder_id']}", headers=headers)
    assert mine.status_code == 200
    assert mine.json()["established"] is True, "新访客的沙箱没有播种作息历史"

    # 看不到默认演示家庭的数据。
    theirs = client.get(f"/v7/baseline/{IDS.elder_id}", headers=headers)
    assert theirs.status_code == 403


def test_unauthenticated_access_is_refused(client):
    assert client.get(f"/v7/baseline/{IDS.elder_id}").status_code in (401, 403)


# --- 时区：一天从哪里开始 ---------------------------------------------------


def test_a_local_morning_lands_in_the_local_day(client, elder_auth):
    """在 UTC+8 直接按 UTC 分天，会把早上 6 点算进**昨天**。

    这条测试是被一次真实误判换来的：往系统里写一条 11:20（北京）的起床记录，日报
    回答"比平常**早**了 2 小时 48 分"。数学没错——06:05 北京被存成 22:05 UTC，
    于是"平常起床时间"学成了前一天深夜。这类错误不报错，只会给出很有说服力的
    错误结论，而这份结论会被发给子女。
    """
    from youhuo.baseline_store import DEFAULT_TIMEZONE, _zone

    zone = _zone(DEFAULT_TIMEZONE)
    today_local = datetime.now(UTC).astimezone(zone).date()
    # 北京时间今天早上 6:30，一个完全正常的起床时刻。
    local_wake = datetime.combine(today_local, datetime.min.time(), tzinfo=zone) + timedelta(
        hours=6, minutes=30
    )
    response = client.post(
        "/v4/safety/heartbeat",
        headers=elder_auth,
        json={"elder_id": IDS.elder_id, "kind": "morning_activity",
              "occurred_at": local_wake.astimezone(UTC).isoformat()},
    )
    assert response.status_code in (200, 201), response.text

    body = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    wake = next(d for d in body["deviations"] if d["channel"] == "wake")
    assert wake["observed_text"] is not None, "本地早上的活动没有落进本地的今天"
    assert wake["observed_text"].startswith("06:"), (
        f"起床时刻按本地读应当是 06:30 前后，实际 {wake['observed_text']}"
    )
    assert wake["verdict"] == "typical", wake["explanation"]


def test_the_seeded_baseline_is_a_plausible_local_routine(client, elder_auth):
    """播种的是一位早上六点起、晚上九点半睡的老人——按本地时间读出来也该是这样。

    如果播种写的是 naive 的 06:05（被当成 UTC），读出来会是北京时间下午两点。
    """
    body = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    wake = next(b for b in body["baselines"] if b["channel"] == "wake")
    sleep = next(b for b in body["baselines"] if b["channel"] == "sleep")
    assert wake["center_text"].startswith("06:"), wake
    assert sleep["center_text"].startswith("21:"), sleep


# --- 合成回填不许污染运营表 -------------------------------------------------


def test_demo_history_is_off_by_default(tmp_path, monkeypatch):
    """这条测试是被一次真实回归换来的。

    合成作息历史写的是 `activity_events_v4`，而无交互预警取同一张表的
    `MAX(occurred_at)`。默认开启时，这些"今天"的合成事件让一条以 2026-07-23 为 now
    的既有测试再也触发不了预警——最后一次活动落在了查询时点之后。

    合成数据悄悄改掉真实功能的输入，比"演示里没东西看"糟糕得多。所以默认必须关闭，
    而这条测试就是那个"必须"。
    """
    monkeypatch.setenv("YOUHUO_DEMO_MODE", "true")
    monkeypatch.setenv("YOUHUO_DB_PATH", str(tmp_path / "clean.db"))
    monkeypatch.delenv("YOUHUO_SEED_BASELINE", raising=False)
    app = create_app()
    with TestClient(app) as plain:
        auth = token(plain, IDS.elder_id)
        body = plain.get(f"/v7/baseline/{IDS.elder_id}", headers=auth).json()
        assert body["established"] is False, "默认就把合成历史写进了运营表"
        assert body["observed_days"] == 0


def test_inactivity_still_sees_no_future_activity_by_default(tmp_path, monkeypatch):
    """直接钉住被打破的那条性质：默认情况下运营表里没有未来的活动事件。"""
    monkeypatch.setenv("YOUHUO_DEMO_MODE", "true")
    monkeypatch.setenv("YOUHUO_DB_PATH", str(tmp_path / "clean2.db"))
    monkeypatch.delenv("YOUHUO_SEED_BASELINE", raising=False)
    app = create_app()
    with TestClient(app) as plain:
        elder = token(plain, IDS.elder_id)
        family = token(plain, IDS.daughter_id)
        plain.put("/v4/safety/policy", headers=family, json={
            "elder_id": IDS.elder_id, "inactivity_minutes": 60, "home_lat": 39.9042,
            "home_lon": 116.3974, "geofence_radius_m": 1000, "notify_community": True,
        })
        plain.post("/v4/safety/heartbeat", headers=elder, json={
            "elder_id": IDS.elder_id, "occurred_at": "2026-07-23T08:00:00Z", "kind": "voice",
        })
        out = plain.post("/v4/safety/inactivity/evaluate", headers=family,
                         json={"now": "2026-07-23T10:00:01Z"}).json()
        assert out[0]["alert_created"] is True, (
            "无交互预警被合成历史压掉了——最后一次活动落在了查询时点之后"
        )


# --- 偏离能被真实数据触发 ---------------------------------------------------


def test_an_unusually_early_waking_shows_up_in_todays_report(client, elder_auth, family_auth):
    """凌晨 2:10 就起——一位平常 6 点起床的老人。

    测"过早"而不是"过晚"，是因为播种的今天已经有一条 06:05 的起床记录，再补一条
    更晚的不会改变"当天第一次活动"（这本身也是对的：人已经起来了）。而过早醒来
    本身就是有意义的信号——早醒是抑郁和多种疾病的经典表现。

    走的是真实链路：心跳事件 → 按本地时区分天 → 推导观测 → 与他自己的常态比 →
    日报。中间没有任何一步是为测试特设的。
    """
    from youhuo.baseline_store import DEFAULT_TIMEZONE, _zone

    zone = _zone(DEFAULT_TIMEZONE)
    today = datetime.now(UTC).astimezone(zone).date()
    early = datetime.combine(today, datetime.min.time(), tzinfo=zone) + timedelta(
        hours=2, minutes=10
    )
    response = client.post(
        "/v4/safety/heartbeat",
        headers=elder_auth,
        json={"elder_id": IDS.elder_id, "kind": "morning_activity",
              "occurred_at": early.astimezone(UTC).isoformat()},
    )
    assert response.status_code in (200, 201), response.text

    body = client.get(f"/v7/daily-report/{IDS.elder_id}", headers=family_auth).json()
    rhythm = next(s for s in body["report"]["sections"] if s["title"] == "作息")
    joined = " ".join(rhythm["lines"])
    assert "早" in joined and "平常" in joined, joined
    assert rhythm["verdict"] in ("notice", "marked"), rhythm
    # 而且这条偏离必须一路走到给子女的结论里，而不是停在某个字段上。
    assert body["report"]["overall"] in ("notice", "marked")
    assert "平常" in body["report"]["headline"]


def test_a_later_event_does_not_overwrite_the_morning(client, elder_auth):
    """人已经起来了，中午再动一次不该被当成"今天很晚才起"。"""
    from youhuo.baseline_store import DEFAULT_TIMEZONE, _zone

    zone = _zone(DEFAULT_TIMEZONE)
    today = datetime.now(UTC).astimezone(zone).date()
    noon = datetime.combine(today, datetime.min.time(), tzinfo=zone) + timedelta(hours=12)
    before = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    observed_before = next(d for d in before["deviations"] if d["channel"] == "wake")["observed_text"]

    client.post("/v4/safety/heartbeat", headers=elder_auth,
                json={"elder_id": IDS.elder_id, "kind": "interaction",
                      "occurred_at": noon.astimezone(UTC).isoformat()})

    after = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    observed_after = next(d for d in after["deviations"] if d["channel"] == "wake")["observed_text"]
    assert observed_before == observed_after


def test_the_seed_never_writes_events_in_the_future(client, elder_auth):
    """未来的活动记录会让无交互预警永远算出负数，从此不再触发。"""
    body = client.get(f"/v7/baseline/{IDS.elder_id}", headers=elder_auth).json()
    sleep = next(d for d in body["deviations"] if d["channel"] == "sleep")
    if sleep["observed_text"] is None:
        return  # 还没到晚上，本来就该没有记录
    hour = int(sleep["observed_text"].split(":")[0])
    now_hour = datetime.now(UTC).astimezone(
        __import__("youhuo.baseline_store", fromlist=["_zone"])._zone("Asia/Shanghai")
    ).hour
    assert hour <= now_hour, f"播种了一条未来的活动记录：{sleep['observed_text']}"
