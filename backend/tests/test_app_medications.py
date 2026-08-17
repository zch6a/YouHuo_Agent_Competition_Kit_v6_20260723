"""老人端的用药：今天吃什么、吃了没、还剩几天、家人加的药点不点头。

## 为什么此前没有

v4 早就把用药计划、库存推算、服药记录做完了（`/v4/medications*`，6 个端点），
而 `/api/v1` 一个入口都没有。老人端只有「用药提醒」——一条到点响的提醒，
和「今天这几次吃了没」是两回事。产品自己的帮助词
（`care_voice.answer_capability_help`）已经在对老人承诺后面这两件事。

家人加药那条更糟：`create_medication_plan` 对家属建的计划是 `active=False`，
`/v4/medications/decide` **只允许老人本人**调用。所以这条流程按设计必须由
老人这一端完成，而老人这一端没有入口——女儿加的钙片永远停在待确认，
两边界面都正常，**不报任何错**。

## 不测种子里那份降压药

种子按 `taken = at_local(day, 8, jitter)` 铺今天，所以当地 8 点前那一格是待服用、
8 点后是已服用（`baseline_store.py:346` 的 horizon）。依赖它的判据会在早上红、
下午绿。这份文件里每一条都自建计划。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"
ELDER = "elder-demo"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "meds.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def family_headers(client: TestClient) -> dict[str, str]:
    token = client.post("/v2/auth/demo", json={"actor_id": "daughter-demo"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _propose(client: TestClient, headers: dict, name: str, times: list[str],
             stock: float = 30, per_dose: float = 1) -> str:
    """家人提一份用药计划，返回 plan_id。建出来是待确认的。"""
    r = client.post("/v4/medications", headers=headers, json={
        "elder_id": ELDER, "display_name": name, "normalized_name": name,
        "dose_text": "一次一片", "times_local": times,
        "start_date": "2026-08-01", "stock_units": stock, "units_per_dose": per_dose,
    })
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False, "家属建的计划应当等老人确认，这条判据的前提不成立"
    return r.json()["id"]


def _active(client: TestClient, headers: dict, name: str, times: list[str],
            stock: float = 30, per_dose: float = 1) -> str:
    plan_id = _propose(client, headers, name, times, stock, per_dose)
    assert client.post(f"{V1}/medications/{plan_id}/approve").status_code == 200
    return plan_id


def _plan_view(client: TestClient, plan_id: str) -> dict:
    body = client.get(f"{V1}/medications").json()
    hit = [p for p in body["plans"] if p["id"] == plan_id]
    assert hit, f"{plan_id} 不在今天的用药里"
    return hit[0]


def _slots(client: TestClient, plan_id: str) -> list[dict]:
    return [d for d in client.get(f"{V1}/medications").json()["doses"] if d["planId"] == plan_id]


# ------------------------------------------------------- 家人加的药，等老人点头


def test_a_plan_the_family_added_waits_for_the_elder(client, family_headers) -> None:
    _propose(client, family_headers, "钙片", ["09:00"])
    pending = client.get(f"{V1}/medications/pending").json()
    assert [i["name"] for i in pending["items"]] == ["钙片"]
    assert "钙片" in pending["message"]


def test_an_unapproved_plan_is_not_in_todays_doses(client, family_headers) -> None:
    """还没点头的药不许出现在「今天要吃的」里。

    出现了就是在让老人吃一份他没同意过的药。
    """
    _propose(client, family_headers, "钙片", ["09:00"])
    body = client.get(f"{V1}/medications").json()
    assert "钙片" not in [d["name"] for d in body["doses"]]
    assert "钙片" not in [p["name"] for p in body["plans"]]


def test_approving_puts_it_into_todays_doses(client, family_headers) -> None:
    plan_id = _propose(client, family_headers, "钙片", ["09:00"])
    r = client.post(f"{V1}/medications/{plan_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True
    assert [d["time"] for d in _slots(client, plan_id)] == ["09:00"]
    assert client.get(f"{V1}/medications/pending").json()["count"] == 0


def test_approving_twice_does_not_claim_it_just_happened(client, family_headers) -> None:
    """再点一次同意不算失败，但也不能说成「刚刚确认了」。"""
    plan_id = _propose(client, family_headers, "钙片", ["09:00"])
    client.post(f"{V1}/medications/{plan_id}/approve")
    again = client.post(f"{V1}/medications/{plan_id}/approve")
    assert again.status_code == 200
    assert "之前已经确认过" in again.json()["message"]


def test_declining_removes_it_and_does_not_start_dosing(client, family_headers) -> None:
    plan_id = _propose(client, family_headers, "鱼油", ["12:00"])
    r = client.post(f"{V1}/medications/{plan_id}/decline")
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert client.get(f"{V1}/medications/pending").json()["count"] == 0
    assert "鱼油" not in [d["name"] for d in client.get(f"{V1}/medications").json()["doses"]]


def test_deciding_a_plan_that_is_not_yours_is_a_404(client) -> None:
    assert client.post(f"{V1}/medications/plan-nope/approve").status_code == 404
    assert client.post(f"{V1}/medications/plan-nope/decline").status_code == 404


# ------------------------------------------------------- 记一次吃了 / 没吃


def test_recording_taken_reduces_the_stock(client, family_headers) -> None:
    plan_id = _active(client, family_headers, "钙片", ["09:00", "21:00"], stock=8, per_dose=2)
    before = _plan_view(client, plan_id)
    assert before["stockUnits"] == 8.0

    r = client.post(f"{V1}/medications/{plan_id}/taken", json={"time": "09:00"})
    assert r.status_code == 200, r.text
    assert r.json()["alreadyRecorded"] is False
    assert _plan_view(client, plan_id)["stockUnits"] == 6.0, "记了「吃了」库存没少"


def test_recording_skipped_leaves_the_stock_alone(client, family_headers) -> None:
    """没吃就是药还在。扣了库存就是在说他吃了。"""
    plan_id = _active(client, family_headers, "钙片", ["09:00"], stock=8, per_dose=2)
    r = client.post(f"{V1}/medications/{plan_id}/skipped", json={"time": "09:00"})
    assert r.status_code == 200, r.text
    assert _plan_view(client, plan_id)["stockUnits"] == 8.0, "记了「没吃」却扣了库存"
    assert _slots(client, plan_id)[0]["status"] == "没吃"


def test_tapping_the_same_slot_twice_does_not_double_count(client, family_headers) -> None:
    """连点两下不许扣两次库存。老人手抖是常态。"""
    plan_id = _active(client, family_headers, "钙片", ["09:00"], stock=8, per_dose=2)
    client.post(f"{V1}/medications/{plan_id}/taken", json={"time": "09:00"})
    second = client.post(f"{V1}/medications/{plan_id}/taken", json={"time": "09:00"})
    assert second.status_code == 200
    assert second.json()["alreadyRecorded"] is True
    assert _plan_view(client, plan_id)["stockUnits"] == 6.0, "第二下又扣了一次"


def test_recording_without_a_time_takes_the_earliest_unrecorded_slot(client, family_headers) -> None:
    """老人按的是「吃了」这个动作，不该要求他先选是哪一次。"""
    plan_id = _active(client, family_headers, "钙片", ["09:00", "21:00"])
    first = client.post(f"{V1}/medications/{plan_id}/taken", json={})
    assert first.json()["scheduledAt"].endswith("01:00:00+00:00"), "09:00 当地 = 01:00 UTC"
    second = client.post(f"{V1}/medications/{plan_id}/taken", json={})
    assert second.json()["scheduledAt"].endswith("13:00:00+00:00")


def test_recording_when_everything_is_done_says_so_instead_of_inventing_a_slot(
    client, family_headers
) -> None:
    """都记完了再点，要说「都记过了」，不能默默再记一条。

    默默记一条，记的是一件没发生的事，而且会再扣一次库存。
    """
    plan_id = _active(client, family_headers, "钙片", ["09:00"], stock=8, per_dose=2)
    client.post(f"{V1}/medications/{plan_id}/taken", json={})
    r = client.post(f"{V1}/medications/{plan_id}/taken", json={})
    assert r.status_code == 409
    assert "都记过了" in r.json()["detail"]
    assert _plan_view(client, plan_id)["stockUnits"] == 6.0


def test_a_time_that_is_not_in_the_plan_is_rejected(client, family_headers) -> None:
    plan_id = _active(client, family_headers, "钙片", ["09:00"])
    r = client.post(f"{V1}/medications/{plan_id}/taken", json={"time": "23:45"})
    assert r.status_code == 400
    assert "没有这个时间点" in r.json()["detail"]


def test_a_validation_error_is_not_reported_as_already_recorded(client, family_headers) -> None:
    """构造请求体失败不能被说成「这一格记过了」。

    实测过一次：`note=""` 触发了模型里「不能为空」的校验器，
    而端点回的是 409「已经记过了」——那一格根本还没记。
    这里钉住的是那一格**确实**被记下了，没有走进错误分支。
    """
    plan_id = _active(client, family_headers, "钙片", ["09:00"])
    r = client.post(f"{V1}/medications/{plan_id}/taken", json={})
    assert r.status_code == 200, f"记不下去：{r.text}"
    assert _slots(client, plan_id)[0]["status"] == "已服用"


# ------------------------------------------------------- 说的话要对


def test_still_pending_is_counted_by_missing_records_not_by_subtraction(tmp_path) -> None:
    """「还差几次」数的是**没有记录**的，不是 planned - taken。

    记成「没吃」的那一格是有记录的。用减法的话，两格全记过、其中一格没吃时
    会说「还差1次」——于是老人去找一次并不存在的药。

    `summary` 是**整屏**的话，不是单份计划的，所以这条判据必须跑在
    没有种子计划的实例上。用共享夹具的话，种子那份降压药今天那格
    当地 8 点前是待服用、8 点后是已服用（`baseline_store.py:346` 的 horizon），
    于是这条判据早上红、下午绿。第一版就是这么写的。
    """
    app = create_app(tmp_path / "sub.db", demo_mode=True, seed_baseline_history=False)
    with TestClient(app) as c:
        assert app.state.db._conn.execute(
            "SELECT COUNT(*) FROM medication_plans_v4"
        ).fetchone()[0] == 0, "这个实例里有别的计划，summary 会被它影响"
        token = c.post("/v2/auth/demo", json={"actor_id": "daughter-demo"}).json()["access_token"]
        plan_id = _active(c, {"Authorization": f"Bearer {token}"}, "钙片", ["09:00", "21:00"])
        c.post(f"{V1}/medications/{plan_id}/skipped", json={"time": "09:00"})
        c.post(f"{V1}/medications/{plan_id}/taken", json={"time": "21:00"})

        body = c.get(f"{V1}/medications").json()
        assert body["plannedCount"] == 2 and body["takenCount"] == 1
        assert body["pendingCount"] == 0, "两格都记过了，pendingCount 该是 0"
        assert all(not d["pending"] for d in body["doses"])
        assert "还差" not in body["summary"], f"全记过了还说「还差」：{body['summary']}"
        assert "没吃" in body["summary"], f"没说清那一次记的是没吃：{body['summary']}"


def test_it_never_claims_the_elder_did_not_take_it(client, family_headers) -> None:
    """没有记录 ≠ 没吃。这一层不许把「查不到」说成「您没吃」。"""
    _active(client, family_headers, "钙片", ["09:00"])
    summary = client.get(f"{V1}/medications").json()["summary"]
    assert "我只能看到记录" in summary
    assert "您没吃" not in summary and "你没吃" not in summary


def test_a_low_stock_plan_is_surfaced_on_its_own_line(client, family_headers) -> None:
    """快用完的药要单独说一句——埋在列表里老人看不见。"""
    _active(client, family_headers, "降糖药", ["09:00"], stock=30)   # 30 天，充足
    _active(client, family_headers, "钙片", ["09:00"], stock=3)      # 3 天
    body = client.get(f"{V1}/medications").json()
    assert body["stockWarning"] and "钙片" in body["stockWarning"], (
        f"3 天的药没有被单独提出来：{body['stockWarning']}"
    )
    assert "降糖药" not in body["stockWarning"], "充足的那份不该混进警告"


def test_the_warning_names_the_most_urgent_one_first(client, family_headers) -> None:
    _active(client, family_headers, "钙片", ["09:00"], stock=6)
    _active(client, family_headers, "降糖药", ["09:00"], stock=2)
    warning = client.get(f"{V1}/medications").json()["stockWarning"]
    assert "降糖药" in warning, f"更急的那个没排在前面：{warning}"


def test_with_no_plans_it_says_where_to_add_one(tmp_path) -> None:
    """一份计划都没有时说清楚去哪儿加。

    换一个 `seed_baseline_history=False` 的实例——那份降压药是基线演示数据
    种下的。第一版用访客沙箱，量出来沙箱**也**有那份计划（它走同一条种子），
    于是判据一直 skip。跳过的测试等于没测。
    """
    app = create_app(tmp_path / "bare.db", demo_mode=True, seed_baseline_history=False)
    with TestClient(app) as c:
        plans = app.state.db._conn.execute(
            "SELECT COUNT(*) FROM medication_plans_v4"
        ).fetchone()[0]
        assert plans == 0, "这个实例里也种了用药计划，这条判据要换个构造方式"
        body = c.get(f"{V1}/medications").json()
        assert body["doses"] == []
        assert body["plans"] == []
        assert body["pendingCount"] == 0
        assert "家属端" in body["summary"]


# ------------------------------------------------------- P0：读不许改


def test_reading_the_medication_screen_never_records_a_dose(client, family_headers) -> None:
    """渲染一屏不许产生业务变更。这一层的 P0。"""
    plan_id = _active(client, family_headers, "钙片", ["09:00"], stock=8, per_dose=2)
    db = client.app.state.db

    def dose_rows() -> int:
        return db._conn.execute("SELECT COUNT(*) FROM medication_doses_v4").fetchone()[0]

    before = dose_rows()
    for _ in range(5):
        client.get(f"{V1}/medications")
        client.get(f"{V1}/medications/pending")
    assert dose_rows() == before, "读了几屏就多出服药记录"
    assert _plan_view(client, plan_id)["stockUnits"] == 8.0, "读了几屏库存少了"


# ------------------------------------------------------- 记录页要认识它


def test_every_event_this_layer_can_write_has_a_human_sentence(client, family_headers) -> None:
    """走完一遍用药流程，记录页里不许出现兜底文案。

    `app_api.py` 自己写着：加一个事件类型就必须同时加一条 `_WORDS`，
    否则记录页落到「办了一件事」——**而那一行看起来完全正常，没有东西会报红**。
    这条判据就是那个「会报红的东西」。
    """
    plan_id = _propose(client, family_headers, "钙片", ["09:00", "21:00"])
    client.post(f"{V1}/medications/{plan_id}/approve")
    client.post(f"{V1}/medications/{plan_id}/taken", json={"time": "09:00"})
    client.post(f"{V1}/medications/{plan_id}/skipped", json={"time": "21:00"})
    other = _propose(client, family_headers, "鱼油", ["12:00"])
    client.post(f"{V1}/medications/{other}/decline")

    items = client.get(f"{V1}/records", params={"limit": 300}).json()["items"]
    assert items, "记录页是空的，这条判据不成立"
    generic = [i for i in items if i["title"] == "办了一件事"]
    assert not generic, (
        "有事件类型没登记进 `_WORDS`，记录页落到兜底文案："
        f"{sorted({i.get('id', '?') for i in generic})}"
    )
    titles = {i["title"] for i in items}
    assert "确认了一份用药计划" in titles
    assert "记了一次服药" in titles
