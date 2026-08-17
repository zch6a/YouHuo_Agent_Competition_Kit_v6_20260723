"""`/api/v1` 这一层的契约测试。

## 为什么现在才有，以及为什么必须有

这一层有 **25 个端点，而套件里此前对它零覆盖**。查过：只有三个测试文件提到
`app_api`，而那三个都是把它当成**契约来源**去读（比如核对 `data-bind` 的字段名
在后端存不存在），没有一个真的调用过它。

所有验证都活在会话临时目录的驱动脚本里。那些脚本每次都跑绿，但它们不进套件——
换句话说，**只要没人手动跑，这 25 个端点可以在任何一次改动里悄悄坏掉。**

这件事在「前端可能整套作废」之后变得要命：前端一换，那些驱动脚本连同它们
验的界面一起失效，而后端将失去唯一的守卫。所以这份文件守的是**接口本身**，
不涉及任何页面、任何选择器、任何 DOM。

## 覆盖的是「条件」，不是「200」

这一层的价值全在守卫上：没复述不许推进、老人推不动家人那一步、
钱没付掉凭证不许说成功、结掉的账单不许再付。逐条钉住的是这些，
而不是「接口通不通」——一个一路 200 的支付流程恰恰是最危险的那种。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"


@pytest.fixture()
def client(tmp_path):
    """带演示数据的实例。

    `seed_baseline_history=True` 等价于 `YOUHUO_DEMO_STATE=normal`——不开的话
    `demo_state` 落到 `empty`，一条提醒、一张账单都不种，于是下面一半的断言会
    "通过"，而通过的原因是**没有数据可测**。这个坑我在驱动脚本里踩过一次：
    `/reminders` 回 0 条，差点被当成产品缺陷去修。
    """
    app = create_app(tmp_path / "app_api.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


def _pay_to(client: TestClient, step: str, bill_id: str | None = None) -> str:
    """把一笔缴费推到指定阶段，返回事务号。"""
    body = {"billId": bill_id} if bill_id else {}
    task = client.post(f"{V1}/payments/prepare", json=body).json()
    pid = task["id"]
    if step == "prepared":
        return pid
    amount = task["amount"]
    client.post(f"{V1}/payments/{pid}/teach-back", json={"text": f"确认支付 {amount} 元"})
    if step == "verified":
        return pid
    client.post(f"{V1}/payments/{pid}/execute", json={})
    if step == "awaiting_family":
        return pid
    client.post(f"{V1}/payments/{pid}/family-approve", json={})
    return pid


# ---- 仪器自检 --------------------------------------------------------------

def test_the_demo_data_is_actually_seeded(client: TestClient) -> None:
    """先证明这套夹具里真的有数据可测。

    没有这一条，下面每一条「列表里应该有 X」都可以因为**列表是空的**而变成
    空断言——那正是 `all()` 对空集合恒为真的那类陷阱。
    """
    assert client.get(f"{V1}/bills").json()["count"] >= 3
    assert client.get(f"{V1}/reminders").json()["count"] >= 3
    assert client.get(f"{V1}/contacts").json()["count"] >= 2


# ---- 支付：守卫，不是流程 ---------------------------------------------------

def test_execute_is_refused_before_the_elder_restates_the_amount(client: TestClient) -> None:
    pid = _pay_to(client, "prepared")
    r = client.post(f"{V1}/payments/{pid}/execute", json={})
    assert r.status_code == 409, r.text
    assert "复述" in r.json()["detail"]


def test_the_elder_cannot_stand_in_for_the_family(client: TestClient) -> None:
    """老人自己推不动家人那一步。这是双人确认的全部意义。"""
    pid = _pay_to(client, "verified")
    r = client.post(f"{V1}/payments/{pid}/family-approve", json={})
    assert r.status_code == 409, r.text
    assert "等家人确认" in r.json()["detail"]


def test_restating_the_wrong_amount_stops_the_payment(client: TestClient) -> None:
    pid = _pay_to(client, "prepared")
    r = client.post(f"{V1}/payments/{pid}/teach-back", json={"text": "确认支付 100.00 元"})
    body = r.json()
    assert body["matched"] is False
    assert body["expected"] != body["heard"]
    # 念错之后**仍然**推不动。
    assert client.post(f"{V1}/payments/{pid}/execute", json={}).status_code == 409


def test_the_certificate_never_claims_success_before_it_happens(client: TestClient) -> None:
    """本项目的 P0：渲染凭证绝不许宣称一笔并未发生的交易。"""
    pid = _pay_to(client, "awaiting_family")
    cert = client.get(f"{V1}/payments/{pid}/certificate").json()
    assert cert["status"] == "awaiting_family_approval"
    assert cert["paidAt"] is None
    assert cert["approvedBy"] is None


def test_a_finished_payment_names_who_approved_it(client: TestClient) -> None:
    pid = _pay_to(client, "done")
    cert = client.get(f"{V1}/payments/{pid}/certificate").json()
    assert cert["status"] == "completed"
    assert cert["approvedBy"], "凭证上必须写清是谁点的头"
    assert cert["paidAt"]
    assert cert["chainValid"] is True
    # 链上要有家人那一条——办这件事的不是老人一个人。
    assert any(step["by"] != "elder-demo" for step in cert["chain"])


def test_the_audit_chain_keeps_the_failed_restatement(client: TestClient) -> None:
    """念错的那一次不许被抹掉。凭证的价值就在于它记的是发生过的事。"""
    pid = _pay_to(client, "prepared")
    client.post(f"{V1}/payments/{pid}/teach-back", json={"text": "确认支付 100.00 元"})
    client.post(f"{V1}/payments/{pid}/teach-back", json={"text": "确认支付 68.40 元"})
    chain = client.get(f"{V1}/payments/{pid}/certificate").json()["chain"]
    restatements = [s for s in chain if s["action"] == "app.payment.teach_back"]
    assert len(restatements) == 2, f"念错那一次不见了：{chain}"


# ---- 账单 ------------------------------------------------------------------

def test_every_bill_is_payable_not_just_water(client: TestClient) -> None:
    """这一层曾经只暴露一张写死的水费，而库里有三张。"""
    bills = client.get(f"{V1}/bills").json()
    kinds = {b["type"] for b in bills["items"]}
    assert {"水费", "电费", "燃气费"} <= kinds, kinds
    electric = next(b for b in bills["items"] if b["type"] == "电费")
    task = client.post(f"{V1}/payments/prepare", json={"billId": electric["id"]}).json()
    assert task["amount"] == electric["amount"], "指名电费，办出来的却是别的金额"


def test_restating_another_bills_amount_does_not_pass(client: TestClient) -> None:
    """付电费时念水费的金额——这条路在只能付水费的时候根本不存在。"""
    bills = client.get(f"{V1}/bills").json()["items"]
    electric = next(b for b in bills if b["type"] == "电费")
    water = next(b for b in bills if b["type"] == "水费")
    pid = client.post(f"{V1}/payments/prepare", json={"billId": electric["id"]}).json()["id"]
    r = client.post(f"{V1}/payments/{pid}/teach-back",
                    json={"text": f"确认支付 {water['amount']} 元"}).json()
    assert r["matched"] is False


def test_paying_a_bill_actually_settles_it(client: TestClient) -> None:
    """付完之后账单要真的结掉，而且**不能再付一次**。

    这一层曾经只把任务标成 COMPLETED 就返回：凭证说成功，`bills.paid` 还是 0。
    """
    before = client.get(f"{V1}/bills").json()
    water = next(b for b in before["items"] if b["type"] == "水费")
    assert water["paid"] is False

    _pay_to(client, "done")

    after = client.get(f"{V1}/bills").json()
    water2 = next(b for b in after["items"] if b["id"] == water["id"])
    assert water2["paid"] is True, "钱付了，账单还欠着"
    assert water2["paidAt"]
    assert after["unpaidCount"] == before["unpaidCount"] - 1

    again = client.post(f"{V1}/payments/prepare", json={"billId": water["id"]})
    assert again.status_code == 409, "结掉的账单又被拿来付了一次"


def test_the_legacy_water_route_still_answers(client: TestClient) -> None:
    """加了 `/bills` 和 `/bills/{id}` 之后，这条老端点不许失效。

    它是账单详情页一直在用的数据源，删它或改它的形状都会静默断掉一整页。

    **这条判据的理由被变异测试改写过。** 原来写的是「它必须排在
    `/bills/{bill_id}` 前面，否则 `water` 会被当成 bill_id 吃掉」——
    我没验就写下了那句。真把一条 `/bills/{bill_id}` 塞到前面，它照样 200：
    `/bills/water/current` 是三段路径，而路径参数只匹配一段。
    那个顺序风险**不存在**；这条判据守的是「老端点还在」，仅此而已。
    """
    r = client.get(f"{V1}/bills/water/current")
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "水费支付"


def test_an_unknown_bill_is_a_404_not_a_500(client: TestClient) -> None:
    """顺带守住一件真会发生的事：`/bills/{id}` 不许变成什么都接的兜底。

    变异测试里往前面塞一条无脑返回 `{"id": …}` 的同形路由时，红的正是这一条——
    它是这一组里唯一能发现「路由被影子吃掉」的断言。
    """
    assert client.get(f"{V1}/bills/bill-does-not-exist").status_code == 404


# ---- 提醒 ------------------------------------------------------------------

def test_reminders_speak_chinese_not_enum_values(client: TestClient) -> None:
    """界面上不许出现英文枚举值——所以翻译发生在这一层，不在前端。"""
    items = client.get(f"{V1}/reminders").json()["items"]
    assert items
    assert all(i["kind"] in {"用药", "就医", "健康", "其他"} for i in items)
    assert all(i["status"] in {"待进行", "已完成", "已取消"} for i in items)


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("吃降压药", "用药"),
        ("吃钙片", "用药"),      # 只认「药」字的话它会掉进「其他」——实测踩过
        ("维生素两粒", "用药"),
        ("心内科复诊", "就医"),
        ("量血压", "健康"),
        ("给孙子打电话", "其他"),
        ("看照片", "其他"),      # 反例：不许被「片」误伤
    ],
)
def test_reminder_kind_is_recognised_from_the_title(client: TestClient, title, kind) -> None:
    made = client.post(f"{V1}/reminders", json={"title": title, "time": "07:30"}).json()
    assert made["item"]["kind"] == kind, f"「{title}」被归成了 {made['item']['kind']}"


def test_a_created_reminder_really_lands_in_the_list(client: TestClient) -> None:
    before = client.get(f"{V1}/reminders").json()["count"]
    made = client.post(f"{V1}/reminders", json={"title": "吃钙片", "time": "07:30"})
    assert made.status_code == 200, made.text
    assert client.get(f"{V1}/reminders").json()["count"] == before + 1


def test_a_reminder_needs_a_title_and_a_readable_time(client: TestClient) -> None:
    assert client.post(f"{V1}/reminders", json={"title": ""}).status_code == 400
    assert client.post(f"{V1}/reminders",
                       json={"title": "测试", "time": "晚一点"}).status_code == 400


def test_done_and_cancel_change_the_real_status(client: TestClient) -> None:
    rid = client.post(f"{V1}/reminders", json={"title": "量血压", "time": "09:00"}
                      ).json()["item"]["id"]
    assert client.post(f"{V1}/reminders/{rid}/done").json()["status"] == "已完成"
    rid2 = client.post(f"{V1}/reminders", json={"title": "吃钙片", "time": "09:00"}
                       ).json()["item"]["id"]
    assert client.post(f"{V1}/reminders/{rid2}/cancel").json()["status"] == "已取消"
    assert client.post(f"{V1}/reminders/rem-nope/done").status_code == 404


def test_a_cancelled_reminder_leaves_todays_agenda(client: TestClient) -> None:
    """取消掉的不许还挂在首页「接下来」上。

    **阳性对照在前**：先证明它确实进过「接下来」，否则「取消后不见了」
    可能只是因为它从来没在过。
    """
    from datetime import UTC, datetime, timedelta
    soon = (datetime.now(UTC) + timedelta(minutes=45)).isoformat()
    rid = client.post(f"{V1}/reminders", json={"title": "吃钙片", "at": soon}
                      ).json()["item"]["id"]
    nxt = client.get(f"{V1}/agenda").json()["next"]
    assert nxt and nxt["title"] == "吃钙片", "阳性对照不成立，下面那条断言没有意义"

    client.post(f"{V1}/reminders/{rid}/cancel")
    agenda = client.get(f"{V1}/agenda").json()
    assert not (agenda["next"] and agenda["next"]["title"] == "吃钙片")
    assert "吃钙片" not in [i["title"] for i in agenda["today"]]


def test_an_unknown_kind_returns_an_empty_list_not_an_error(client: TestClient) -> None:
    """筛选按钮点出 500 比点出空列表糟得多。"""
    r = client.get(f"{V1}/reminders", params={"kind": "不存在的类别"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


# ---- 就医安排 --------------------------------------------------------------

def test_an_appointment_also_creates_a_reminder(client: TestClient) -> None:
    """只写 appointments 表是不够的：那张表没有任何东西会到点叫老人。"""
    made = client.post(f"{V1}/appointments", json={
        "hospital": "市中心医院", "department": "心内科",
        "date": "2026-08-20", "time": "10:30"})
    assert made.status_code == 200, made.text
    assert made.json()["reminderId"], "记下了安排，却没有任何东西会到点提醒"
    titles = [i["title"] for i in
              client.get(f"{V1}/reminders", params={"kind": "就医"}).json()["items"]]
    assert any("市中心医院" in t for t in titles), titles


def test_an_appointment_needs_a_hospital_and_a_date(client: TestClient) -> None:
    assert client.post(f"{V1}/appointments", json={"department": "心内科"}).status_code == 400
    assert client.post(f"{V1}/appointments", json={"hospital": "某医院"}).status_code == 400


def test_appointment_status_is_chinese(client: TestClient) -> None:
    client.post(f"{V1}/appointments", json={"hospital": "某医院", "date": "2026-08-20"})
    items = client.get(f"{V1}/appointments").json()["items"]
    assert items
    assert all(a["status"] in {"已预约", "已取消", "已完成"} for a in items)


# ---- 紧急呼叫 --------------------------------------------------------------

def test_the_emergency_button_actually_notifies_someone(client: TestClient) -> None:
    """按了不会叫人的紧急按钮，是这个 App 里最不能有的东西。"""
    before = client.get(f"{V1}/notifications", params={"role": "家人"}).json()["count"]
    r = client.post(f"{V1}/emergency/call", json={"source": "test"}).json()
    assert r["notified"], "没有任何人被通知"
    after = client.get(f"{V1}/notifications", params={"role": "家人"}).json()["count"]
    assert after > before, "返回里说通知了，通知表却没多"


def test_the_emergency_call_reaches_the_primary_contact(client: TestClient) -> None:
    """联系人页写着「第一个联系」的那位，必须就是真的被联系的那位。

    实测出过反例：`list_actors` 按名字排，通知发给了「儿子」，
    而 `/contacts` 把「女儿」标成 primary。紧急时联系错人代价最大。
    """
    primary = next(c["name"] for c in client.get(f"{V1}/contacts").json()["items"]
                   if c["primary"])
    assert client.post(f"{V1}/emergency/call", json={}).json()["notified"] == [primary]


def test_family_notifications_do_not_leak_into_the_elders_own_list(client: TestClient) -> None:
    client.post(f"{V1}/emergency/call", json={})
    assert client.get(f"{V1}/notifications").json()["count"] == 0


def test_a_notification_can_be_read_only_once(client: TestClient) -> None:
    client.post(f"{V1}/emergency/call", json={})
    nid = client.get(f"{V1}/notifications", params={"role": "家人"}).json()["items"][0]["id"]
    assert client.post(f"{V1}/notifications/{nid}/read").status_code == 200
    assert client.post(f"{V1}/notifications/{nid}/read").status_code == 404


# ---- 联系人 / 档案 / 设置 --------------------------------------------------

def test_contacts_never_invent_a_phone_number(client: TestClient) -> None:
    """`actors` 表没有电话这一列。编一个出来，老人真按下去会拨错人。"""
    items = client.get(f"{V1}/contacts").json()["items"]
    assert items
    assert all(c["phone"] is None for c in items)
    assert all(c["role"] in {"家人", "系统", "本人"} for c in items)
    assert all(c["id"] != "elder-demo" for c in items), "老人自己不该在联系人里"


def test_the_profile_reports_days_but_never_invents_weather(client: TestClient) -> None:
    """有依据的给值，没依据的给 null——两者都要，而且不能反过来。"""
    p = client.get(f"{V1}/profile").json()
    assert isinstance(p["days"], int) and p["days"] >= 1   # 取自审计链第一条
    assert p["weather"] is None and p["air"] is None       # 后端确实没有这些
    assert p["name"]


def test_settings_survive_a_round_trip_and_are_clamped(client: TestClient) -> None:
    assert client.get(f"{V1}/settings").json()["saved"] is False
    client.put(f"{V1}/settings", json={"fontScale": 1.3, "voiceSpeed": 0.8})
    got = client.get(f"{V1}/settings").json()
    assert (got["fontScale"], got["voiceSpeed"], got["saved"]) == (1.3, 0.8, True)
    assert client.put(f"{V1}/settings", json={"fontScale": 9.9}).json()["fontScale"] == 1.6
    assert client.put(f"{V1}/settings", json={"fontScale": "大一点"}).status_code == 400


# ---- 记录 ------------------------------------------------------------------

def test_no_action_falls_through_to_the_generic_wording(client: TestClient) -> None:
    """记录页每一行都要说清是哪件事。

    兜底文案「办了一件事」出现，就意味着某个事件类型没进翻译表——
    而那一行在屏幕上**看起来完全正常**，这是它危险的地方。
    """
    _pay_to(client, "done")
    client.post(f"{V1}/reminders", json={"title": "吃钙片", "time": "08:00"})
    client.post(f"{V1}/appointments", json={"hospital": "某医院", "date": "2026-09-01"})
    client.put(f"{V1}/settings", json={"fontScale": 1.2})
    client.post(f"{V1}/emergency/call", json={})

    titles = [i["title"] for i in client.get(f"{V1}/records").json()["items"]]
    assert titles
    assert "办了一件事" not in titles, f"有事件类型没进翻译表：{titles}"
