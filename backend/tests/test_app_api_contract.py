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


# ---- 身份：这一层此前根本没有 ----------------------------------------------
#
# `/api/v1` 原来无条件返回 `elder-demo` 的数据，身份写死在源码里。演示时看不出
# 问题（只有一个家庭），但那意味着：真部署出去，**任何人**访问都会拿到演示家庭的
# 账单、支付和整条审计链。下面这一组守的是新加的三条路，以及最要紧的那条性质——
# 跨家庭不可见。

def _login(client: TestClient, actor_id: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_a_valid_token_decides_who_the_request_is_about(client: TestClient) -> None:
    got = client.get(f"{V1}/profile", headers=_login(client, "elder-demo")).json()
    assert got["name"] == "王爷爷"


def test_a_family_token_sees_the_elders_data(client: TestClient) -> None:
    """家人拿令牌进来，看的仍然是老人的日程和账单——这一层是老人端的门面。

    写死 `elder-demo` 的时候，这个区别根本无法表达。
    """
    fam = _login(client, "daughter-demo")
    assert client.get(f"{V1}/agenda", headers=fam).status_code == 200
    assert client.get(f"{V1}/reminders", headers=fam).json()["count"] >= 3


def test_a_bad_token_is_401_and_never_falls_back_to_the_demo_elder(client: TestClient) -> None:
    """**这一条是这组里最重要的。**

    过期或伪造的令牌静默退回演示身份，比完全没有鉴权更糟：
    调用方以为自己登录着，实际在操作别人的数据，而屏幕上一切正常。
    """
    # 这个假令牌有两条约束，都是踩出来的：
    #
    # ① 只能是 ASCII——HTTP 头就是这么规定的。第一版拿中文当假令牌，
    #    httpx 在**发出去之前**就抛了 UnicodeEncodeError，断言压根没执行到。
    # ② 必须短于 24 个字符。`scan_secrets.py` 的规则是
    #    `Bearer\s+[A-Za-z0-9._-]{24,}`，第二版写了 27 个字符的假串，
    #    于是**密钥扫描当场报红**——这个仓库有过审计密钥进公开库的前科，
    #    那道扫描不能为了迁就一个测试去放宽。
    #
    # 长度和这条测试要验的东西无关：`resolve_auth_token` 查不到就是 None，
    # 走的是同一条 401 分支。
    r = client.get(f"{V1}/profile", headers={"Authorization": "Bearer bad-token"})
    assert r.status_code == 401, f"无效令牌被放行了：{r.status_code} {r.text[:120]}"
    assert "王爷爷" not in r.text


def test_without_a_token_a_non_demo_deployment_refuses(tmp_path) -> None:
    """没有令牌时退回演示老人，**只有演示模式下才允许**。

    非演示部署下，这一层不许把任何人的数据发给一个没有身份的请求。
    """
    app = create_app(tmp_path / "prod.db", demo_mode=False, seed_baseline_history=True)
    with TestClient(app) as c:
        r = c.get(f"{V1}/profile")
        assert r.status_code == 401, f"非演示模式下无令牌被放行：{r.status_code}"


def test_one_family_cannot_see_another_familys_data(client: TestClient) -> None:
    """跨家庭不可见。

    这条性质在身份写死的时候**不存在**——那时所有人看的都是同一个家庭。
    用 `/v2/auth/visitor` 开一个全新家庭，确认它看不到演示家庭的账单，
    而且账单 id 也取不到。
    """
    visitor = client.post("/v2/auth/visitor", json={})
    if visitor.status_code != 200:
        pytest.skip(f"这个部署没有访客沙箱：{visitor.status_code}")
    token = visitor.json().get("elder_token")
    assert token, f"访客沙箱没给令牌：{sorted(visitor.json())}"
    theirs = {"Authorization": "Bearer " + token}

    demo_bills = client.get(f"{V1}/bills").json()["items"]
    assert demo_bills, "演示家庭一张账单都没有，下面的对比没有意义"

    their_bills = client.get(f"{V1}/bills", headers=theirs).json()
    demo_ids = {b["id"] for b in demo_bills}
    their_ids = {b["id"] for b in their_bills["items"]}
    assert not (demo_ids & their_ids), f"看到了别的家庭的账单：{demo_ids & their_ids}"

    # 直接按 id 取也不行——列表过滤住了不等于详情也过滤住了。
    r = client.get(f"{V1}/bills/{demo_bills[0]['id']}", headers=theirs)
    assert r.status_code == 404, f"跨家庭按 id 取到了账单：{r.status_code}"


def test_the_security_scheme_shows_up_in_openapi(client: TestClient) -> None:
    """新前端要看得出这些端点接受 Bearer。"""
    spec = client.get("/openapi.json").json()
    assert "HTTPBearer" in spec.get("components", {}).get("securitySchemes", {})


# ---- OpenAPI：契约要能被工具消费 -------------------------------------------

def test_every_endpoint_documents_what_it_returns(client: TestClient) -> None:
    """`/api/v1` 不许有端点返回一个没有字段的 `object`。

    这一层的 25 个端点原先全部注解成 `dict[str, Any]`，FastAPI 生成出来的是：

        {"additionalProperties": true, "type": "object", "title": "Response Profile …"}

    **有名字，零字段。** 对照老接口那批：171 个模型，字段清清楚楚，
    而其中属于 `/api/v1` 的一个都没有。任何人想按 OpenAPI 生成客户端
    （新前端、鸿蒙端、第三方），拿到的是 25 个 `object`。

    这条判据在「前端可能整套作废」之后尤其要紧：新前端唯一能依据的东西
    就是这份 schema。
    """
    spec = client.get("/openapi.json").json()
    bare = []
    for path, ops in spec["paths"].items():
        if not path.startswith(V1):
            continue
        for method, op in ops.items():
            schema = (op.get("responses", {}).get("200", {})
                        .get("content", {}).get("application/json", {}).get("schema", {}))
            # 有 `$ref` 就是指向一个具名模型；否则必须自带 properties。
            if "$ref" not in schema and not schema.get("properties"):
                bare.append(f"{method.upper()} {path}")
    assert not bare, (
        f"{len(bare)} 个端点没有描述自己的返回值：\n  " + "\n  ".join(bare) +
        "\n把返回注解从 `dict[str, Any]` 换成 `app_schemas` 里的模型。"
    )


def test_the_instrument_can_actually_see_the_endpoints(client: TestClient) -> None:
    """上面那条如果一个端点都没读到，会**恒为真**。先证明它读到了。"""
    spec = client.get("/openapi.json").json()
    v1 = [p for p in spec["paths"] if p.startswith(V1)]
    assert len(v1) >= 20, f"只在 OpenAPI 里看到 {len(v1)} 条 /api/v1 路径"
    models = [k for k in spec.get("components", {}).get("schemas", {}) if k.startswith("App")]
    assert len(models) >= 25, f"只注册了 {len(models)} 个 App* 模型"


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


def test_both_bill_endpoints_talk_about_the_same_bill(client: TestClient) -> None:
    """`/bills/water/current` 和 `/bills` 必须说的是同一张。

    实测过它们**不是**：前者返回硬编码的 `water-current`，后者返回真 id
    `bill-water-2026-07-demo`。客户端拿前者的 id 去 `GET /bills/{id}` 当场 404——
    两条路说的是同一件事，id 却对不上。
    """
    water = client.get(f"{V1}/bills/water/current").json()
    listed = next(b for b in client.get(f"{V1}/bills").json()["items"] if b["type"] == "水费")
    assert water["id"] == listed["id"], f"{water['id']} vs {listed['id']}"
    assert water["amount"] == listed["amount"]
    # id 要真的取得到——这才是「同一张」的意思。
    assert client.get(f"{V1}/bills/{water['id']}").status_code == 200


def test_an_unpaid_bill_has_no_payment_time(client: TestClient) -> None:
    """**这一条是这组里最要紧的。**

    原先 `paidAt` 去扫「任意一笔已完成的缴费事务」取时间，而演示种子里本来就有
    一笔（`task-seed-bill-demo`）。于是一张**没付的**账单，显示着另一笔交易的
    支付时间——和凭证页写死「交易成功」是同一类错误：宣称一件没发生的事。
    """
    water = client.get(f"{V1}/bills/water/current").json()
    listed = next(b for b in client.get(f"{V1}/bills").json()["items"] if b["type"] == "水费")
    assert listed["paid"] is False, "这条判据要求水费一开始是未缴的"
    assert water["paidAt"] is None, f"没付的账单带着支付时间：{water['paidAt']}"


def test_paying_updates_both_endpoints_together(client: TestClient) -> None:
    _pay_to(client, "done")
    water = client.get(f"{V1}/bills/water/current").json()
    listed = next(b for b in client.get(f"{V1}/bills").json()["items"] if b["type"] == "水费")
    assert listed["paid"] is True
    assert water["paidAt"], "付完了，老端点还说没付"
    assert water["id"] == listed["id"]


def test_preparing_without_a_bill_id_uses_the_real_water_bill(client: TestClient) -> None:
    """不指名时用的必须是真表里那张，不是源码里那个编出来的 id。"""
    listed = next(b for b in client.get(f"{V1}/bills").json()["items"] if b["type"] == "水费")
    pid = client.post(f"{V1}/payments/prepare", json={}).json()["id"]
    cert = client.get(f"{V1}/payments/{pid}/certificate").json()
    assert cert["amount"] == listed["amount"]
    # 办完之后结掉的必须**就是**那一张。
    client.post(f"{V1}/payments/{pid}/teach-back", json={"text": f"确认支付 {listed['amount']} 元"})
    client.post(f"{V1}/payments/{pid}/execute", json={})
    client.post(f"{V1}/payments/{pid}/family-approve", json={})
    after = next(b for b in client.get(f"{V1}/bills").json()["items"] if b["id"] == listed["id"])
    assert after["paid"] is True, "不指名时办的那一笔，没有结掉真表里那张水费"


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


def test_a_reminder_can_be_moved_without_faking_two_events(client: TestClient) -> None:
    """改时间必须是**一件事**。

    此前只能建/办好/取消，想把八点挪到九点唯一的办法是取消再建——
    记录里于是留下「取消了一条提醒 + 加了一条提醒」两行，而实际发生的是一件事。
    审计链要能说清真正发生了什么。
    """
    rid = client.post(f"{V1}/reminders", json={"title": "吃钙片", "time": "08:00"}
                      ).json()["item"]["id"]
    r = client.patch(f"{V1}/reminders/{rid}", json={"time": "09:00"})
    assert r.status_code == 200, r.text

    moved = next(i for i in client.get(f"{V1}/reminders").json()["items"] if i["id"] == rid)
    assert moved["time"] == "09:00", f"时间没改动：{moved['time']}"
    assert moved["status"] == "待进行", "改个时间不该把状态也动了"

    titles = [i["title"] for i in client.get(f"{V1}/records").json()["items"]]
    assert "改了提醒的时间" in titles
    assert "取消了一条提醒" not in titles, "改时间被记成了「取消 + 新建」"


def test_a_finished_reminder_cannot_be_rescheduled(client: TestClient) -> None:
    """已经结束的事改不了——改它等于篡改记录。

    **同时钉住那句话，不只是状态码。** 这一条防了两层：Python 里的状态判断，
    以及 `update_reminder_fields` 的 SQL 里那句 `AND status='scheduled'`。
    变异测试时把 Python 那层拆掉，状态码照样 409（SQL 兜住了），断言纹丝不动——
    也就是说它只证明了「拦住了」，没证明「拦得对」。

    两层给的话不一样：上面那层说「已经结束了，**可以另外加一条**」，
    SQL 兜底只说「现在改不了」。对一位老人来说，差别在于他知不知道下一步做什么。
    """
    rid = client.post(f"{V1}/reminders", json={"title": "量血压", "time": "08:00"}
                      ).json()["item"]["id"]
    client.post(f"{V1}/reminders/{rid}/done")
    r = client.patch(f"{V1}/reminders/{rid}", json={"time": "09:00"})
    assert r.status_code == 409
    assert "另外加一条" in r.json()["detail"], (
        f"拦住了，但没告诉他下一步能做什么：{r.json()['detail']}"
    )


def test_rescheduling_reuses_the_same_time_parser(client: TestClient) -> None:
    """建和改必须用同一套解析。

    两处各写一遍，迟早有一处忘了「过点顺延」——而那一处建出来的提醒永远不会响。
    """
    rid = client.post(f"{V1}/reminders", json={"title": "吃钙片", "time": "08:00"}
                      ).json()["item"]["id"]
    assert client.patch(f"{V1}/reminders/{rid}", json={"time": "晚一点"}).status_code == 400


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


def test_cancelling_an_appointment_also_kills_its_reminder(client: TestClient) -> None:
    """**这一条是这组里最要紧的。**

    建安排时同时建了一条到点提醒（不建的话没有任何东西会叫老人）。
    只取消一半，老人到点还是会被提醒去一个已经取消了的门诊——那比不提醒更糟。
    """
    made = client.post(f"{V1}/appointments", json={
        "hospital": "市中心医院", "department": "心内科",
        "date": "2026-08-20", "time": "10:30"}).json()
    # 阳性对照：先证明那条提醒确实建出来了。
    titles = [i["title"] for i in client.get(f"{V1}/reminders").json()["items"]]
    assert any("市中心医院" in t for t in titles), "提醒压根没建，下面的断言没有意义"

    r = client.post(f"{V1}/appointments/{made['id']}/cancel")
    assert r.status_code == 200, r.text

    appt = next(a for a in client.get(f"{V1}/appointments").json()["items"]
                if a["id"] == made["id"])
    assert appt["status"] == "已取消"
    left = [i for i in client.get(f"{V1}/reminders").json()["items"]
            if "市中心医院" in i["title"] and i["status"] == "待进行"]
    assert not left, f"门诊取消了，到点还是会提醒：{left}"


def test_an_appointment_cannot_be_cancelled_twice(client: TestClient) -> None:
    made = client.post(f"{V1}/appointments", json={"hospital": "某医院", "date": "2026-09-01"}).json()
    assert client.post(f"{V1}/appointments/{made['id']}/cancel").status_code == 200
    assert client.post(f"{V1}/appointments/{made['id']}/cancel").status_code == 409


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


# ---- 手抖点两下 ------------------------------------------------------------
#
# 老人手抖、以为没反应、网络慢了再按一次——重复点击是这一端最常见的操作，
# 不是边角情况。实测过每个写接口连点两次留下了什么：加提醒和建安排被唯一键
# 意外挡住了（409），另外四处全都留下了重复。

def test_double_tapping_execute_does_not_duplicate_the_chain(client: TestClient) -> None:
    """**这一条是这组里最要紧的。**

    审计链是这个产品的全部价值。连点两下 execute 会让链上出现**两条**
    `app.payment.awaiting_family`——看链的人会以为老人确认了两遍。
    """
    pid = _pay_to(client, "verified")
    first = client.post(f"{V1}/payments/{pid}/execute", json={})
    second = client.post(f"{V1}/payments/{pid}/execute", json={})
    assert first.status_code == second.status_code == 200
    chain = client.get(f"{V1}/payments/{pid}/certificate").json()["chain"]
    awaiting = [s for s in chain if s["action"] == "app.payment.awaiting_family"]
    assert len(awaiting) == 1, f"同一步在链上出现了 {len(awaiting)} 次：{chain}"


def test_double_tapping_prepare_reuses_the_same_payment(client: TestClient) -> None:
    """同一张账单不许同时有两笔在飞。

    实测连点两下拿到两个不同的事务号。老人接着在其中一笔上复述、
    另一笔永远悬着，而「我的账单」上那张仍然未缴。
    """
    a = client.post(f"{V1}/payments/prepare", json={}).json()
    b = client.post(f"{V1}/payments/prepare", json={}).json()
    assert a["id"] == b["id"], f"建了两笔：{a['id']} / {b['id']}"
    assert a["amount"] == b["amount"]


def test_double_tapping_a_reading_records_it_once(client: TestClient) -> None:
    """一分钟内同一项同一个值，当成手抖。

    血压量两次是正常的，所以不能一律拒绝——但一分钟内同一项同一个**读数**，
    只可能是重复提交：真的量了两次，第二次的数字几乎不会一模一样。
    """
    client.post(f"{V1}/health/events", json={"type": "血压", "value": "128/82"})
    client.post(f"{V1}/health/events", json={"type": "血压", "value": "128/82"})
    assert client.get(f"{V1}/health-summary").json()["recorded"] == 1
    # 值不同 = 真的又量了一次，必须记下来。
    client.post(f"{V1}/health/events", json={"type": "血压", "value": "131/85"})
    assert client.get(f"{V1}/health-summary").json()["recorded"] == 2


def test_the_first_emergency_call_always_notifies(client: TestClient) -> None:
    """**阳性对照，而且是被一个真 bug 逼出来的。**

    加「一分钟内不重复推送」时，我把检查写在了本次审计**之后**——
    于是它查到自己刚写的那一条，`recent_sos` 恒为真，紧急呼叫从此
    **一条通知都不发**。接口照样 200，审计照样有记录，只是没人被叫。
    一个防重复的改动，把这个 App 里最要紧的功能整个关掉了。

    所以「第二次不重复」那条断言必须配这一条：只证明「没重复」，
    等于给「一次都不发」发了通行证。
    """
    r = client.post(f"{V1}/emergency/call", json={}).json()
    assert r["notified"], "第一次呼叫就没有通知任何人"
    assert client.get(f"{V1}/notifications", params={"role": "家人"}).json()["count"] == 1


def test_double_tapping_sos_does_not_spam_the_family(client: TestClient) -> None:
    """真出事时家人手机上应该是一条清楚的呼叫，不是一串重复消息。

    重复本身会让人以为是系统故障，从而降低这条通知的可信度。
    但**呼叫本身照记**——审计链上每一次按下都在。
    """
    client.post(f"{V1}/emergency/call", json={})
    second = client.post(f"{V1}/emergency/call", json={}).json()
    assert client.get(f"{V1}/notifications", params={"role": "家人"}).json()["count"] == 1
    assert "120" in second["message"], "第二次要告诉他更急的话该打 120"
    calls = [i for i in client.get(f"{V1}/records").json()["items"] if i["title"] == "紧急呼叫"]
    assert len(calls) == 2, f"按了两次，链上只记了 {len(calls)} 次"


# ---- 幂等键：和「连点两下」是两件事 -----------------------------------------
#
# 「连点两下」那一批守的是**业务语义**：同一件事不许发生两次，不管请求长什么样。
# 这里守的是**传输层**：同一个请求被重发（客户端超时重试、代理重投），
# 应当拿回第一次那个答案，而不是再执行一次。
#
# 两者都要。业务判断挡不住「同一个请求发两遍但状态还没落库」的竞态；
# 幂等键挡不住「用户真的按了两次不同的请求」。

def test_replaying_a_request_returns_the_first_answer(client: TestClient) -> None:
    key = {"Idempotency-Key": "req-0001"}
    a = client.post(f"{V1}/reminders", headers=key, json={"title": "吃钙片", "time": "07:30"})
    b = client.post(f"{V1}/reminders", headers=key, json={"title": "吃钙片", "time": "07:30"})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json(), "重放拿到的不是第一次那个答案"
    assert b.headers.get("Idempotency-Replayed") == "true"


def test_the_replay_really_skips_the_handler(client: TestClient) -> None:
    """**阳性对照，而且换过一次端点。**

    第一版用 `/health/events` 数「记了几条」，变异测试时把重放整个关掉——
    它**纹丝不动**。原因是那个端点自己有一分钟业务去重，
    幂等关不关它都只记一条。也就是说那条断言测的是业务层，不是幂等层。

    `/reminders` 分辨得开：`UNIQUE(elder_id,title,due_at)` 让第二次撞唯一键。

        幂等开着 → 200（重放第一次那个答案，压根没进处理器）
        幂等关掉 → 409（真的执行了，撞在唯一键上）

    状态码不同，这一条才真的在看「有没有第二次执行」。
    """
    key = {"Idempotency-Key": "req-0002"}
    body = {"title": "吃钙片", "time": "07:30"}
    first = client.post(f"{V1}/reminders", headers=key, json=body)
    second = client.post(f"{V1}/reminders", headers=key, json=body)
    assert first.status_code == 200
    assert second.status_code == 200, (
        f"第二次真的进了处理器（撞唯一键 {second.status_code}），说明没有重放"
    )
    assert second.json()["item"]["id"] == first.json()["item"]["id"]

    # 反面：不带 key 发同样的内容，就该撞唯一键——这证明上面那个 200 不是白来的。
    assert client.post(f"{V1}/reminders", json=body).status_code == 409


def test_the_same_key_with_a_different_payload_is_a_conflict(client: TestClient) -> None:
    """**这一条才是幂等键的价值所在。**

    同一个编号配不同的内容，说明调用方把编号复用了——那时候悄悄执行第二次，
    或者悄悄回第一次的答案，都是错的：前者重复扣钱，后者让调用方以为
    第二件事办了而其实没办。必须报冲突。
    """
    key = {"Idempotency-Key": "req-0003"}
    assert client.post(f"{V1}/reminders", headers=key,
                       json={"title": "吃钙片", "time": "07:30"}).status_code == 200
    r = client.post(f"{V1}/reminders", headers=key,
                    json={"title": "量血压", "time": "09:00"})
    assert r.status_code == 409, f"复用编号配不同内容被放行了：{r.status_code}"
    assert "编号" in r.json()["detail"]


def test_the_same_key_on_a_different_endpoint_is_a_conflict(client: TestClient) -> None:
    """指纹带上路径：同一个 key 用在两个端点上，不许把 A 的响应回给 B。"""
    key = {"Idempotency-Key": "req-0004"}
    client.post(f"{V1}/reminders", headers=key, json={"title": "吃钙片", "time": "07:30"})
    r = client.post(f"{V1}/health/events", headers=key,
                    json={"title": "吃钙片", "time": "07:30"})
    assert r.status_code == 409


def test_a_failed_request_is_not_pinned_by_its_key(client: TestClient) -> None:
    """失败不许把 key 钉死：修好参数重试要能成功。

    **这条性质成立，但不是靠代码里那个 `2xx` 判断成立的。**
    这一层的失败都走 `HTTPException`，它让路由处理器抛出而不是返回，
    缓存那一行根本执行不到——拿探针包了 `save_idempotent_response` 验过，
    失败请求期间它一次都没被调用。

    所以对应的变异（「失败也缓存」）**咬不到这一条**，那不是判据的问题：
    那段代码目前是死的。写在这里，是免得下一个人以为这条路径已经被覆盖了。
    """
    key = {"Idempotency-Key": "req-0005"}
    bad = client.post(f"{V1}/reminders", headers=key, json={"title": ""})
    assert bad.status_code == 400
    good = client.post(f"{V1}/reminders", headers=key, json={"title": "吃钙片", "time": "07:30"})
    assert good.status_code == 200, "修好参数重试，却被上一次的失败钉住了"


def test_without_a_key_nothing_changes(client: TestClient) -> None:
    """不带这个头的请求走原来的路——幂等是**可选**的，不是强制的。

    强制的话，任何一个没实现这个头的调用方（包括现有前端）会当场全挂。
    """
    a = client.post(f"{V1}/health/events", json={"type": "体重", "value": "62.5"})
    assert a.status_code == 200
    assert "Idempotency-Replayed" not in a.headers


# ---- 联系人 / 档案 / 设置 --------------------------------------------------

def test_contacts_never_invent_a_phone_number(client: TestClient) -> None:
    """`actors` 表没有电话这一列。编一个出来，老人真按下去会拨错人。"""
    items = client.get(f"{V1}/contacts").json()["items"]
    assert items
    assert all(c["phone"] is None for c in items)
    assert all(c["role"] in {"家人", "系统", "本人"} for c in items)
    assert all(c["id"] != "elder-demo" for c in items), "老人自己不该在联系人里"


def test_an_existing_database_gets_the_new_column(tmp_path) -> None:
    """迁移的价值全在**升级路径**上，而全新的库测不出它。

    `CREATE TABLE IF NOT EXISTS` 对已经存在的表什么都不做。只改建表语句的话，
    新建的库有新列，而任何一个已经跑过的库（开发机、演示部署、竞赛机上那份）
    永远停在旧结构 —— 然后代码按新列去查，当场 `no such column`。

    这里手工造一个**旧结构**的库（`actors` 没有 `phone`），再用当前的
    `Database` 打开它，确认列被补上、而且原有的数据还在。
    """
    import sqlite3

    from youhuo.database import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE families(id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
        CREATE TABLE actors(
            id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL REFERENCES families(id),
            role TEXT NOT NULL CHECK(role IN ('elder','family','system')),
            display_name TEXT NOT NULL
        );
        INSERT INTO families VALUES ('fam-old','老库家庭');
        INSERT INTO actors VALUES ('elder-old','fam-old','elder','旧库老人');
        """
    )
    conn.commit()
    before = {r[1] for r in conn.execute("PRAGMA table_info(actors)")}
    conn.close()
    assert "phone" not in before, "夹具没造出旧结构，这条测试没有意义"

    db = Database(path)
    try:
        after = {r[1] for r in db._conn.execute("PRAGMA table_info(actors)")}
        assert "phone" in after, f"旧库没有被补上 phone 列：{sorted(after)}"
        # 原有数据不许在迁移里丢掉。
        row = db.actor("elder-old")
        assert row is not None and row["display_name"] == "旧库老人"
        assert row["phone"] is None
        # 补上之后要真的能写。
        assert db.set_actor_phone("elder-old", "fam-old", "13800001111")
        assert db.actor("elder-old")["phone"] == "13800001111"
    finally:
        db.close()


def test_a_family_member_can_register_an_emergency_phone(client: TestClient) -> None:
    """`actors` 原先根本没有电话这一列——这是这个仓库的第一次 `ALTER TABLE`。"""
    fam = _login(client, "daughter-demo")
    r = client.put(f"{V1}/contacts/son-demo/phone", headers=fam, json={"phone": "138 0000 1111"})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "13800001111", "空格和横杠要清掉"
    listed = next(c for c in client.get(f"{V1}/contacts", headers=fam).json()["items"]
                  if c["id"] == "son-demo")
    assert listed["phone"] == "13800001111", "列表里没跟着变"
    # 清掉
    assert client.put(f"{V1}/contacts/son-demo/phone", headers=fam,
                      json={"phone": ""}).json()["phone"] is None


def test_the_elder_cannot_change_an_emergency_phone(client: TestClient) -> None:
    """紧急联系人的号码是紧急时真会被拨出去的东西。

    让老人端自己改它，等于把最后一道人工兜底交给最容易被诱导的一方——
    而这个产品的整条设计线就是「高风险动作要第二个人点头」。
    """
    elder = _login(client, "elder-demo")
    r = client.put(f"{V1}/contacts/son-demo/phone", headers=elder, json={"phone": "13800001111"})
    assert r.status_code == 403, f"老人改动了紧急联系电话：{r.status_code}"


def test_a_nonsense_phone_is_refused(client: TestClient) -> None:
    fam = _login(client, "daughter-demo")
    assert client.put(f"{V1}/contacts/son-demo/phone", headers=fam,
                      json={"phone": "打给我女儿"}).status_code == 400


def test_a_phone_cannot_be_set_across_families(client: TestClient) -> None:
    visitor = client.post("/v2/auth/visitor", json={})
    if visitor.status_code != 200:
        pytest.skip("这个部署没有访客沙箱")
    theirs = {"Authorization": "Bearer " + visitor.json()["family_token"]}
    r = client.put(f"{V1}/contacts/son-demo/phone", headers=theirs, json={"phone": "13800001111"})
    assert r.status_code == 404, f"跨家庭写入了紧急联系电话：{r.status_code}"


def _audit_blob(client: TestClient) -> str:
    """审计表里所有 payload 拼成一串。

    **不要用 `/records` 来验「秘密没进审计」。** 实测：`/records` 输出的是
    `id/title/note/kind/icon/time/at/entityId`，`note` 恒为空串，
    **payload 一个字都不输出**。也就是说，拿 `/records` 的响应去 grep 一个号码，
    无论审计表里存了什么都会绿——那是一条声称守着隐私、实际什么都没看的测试，
    比没有更糟。我写的头两条就是这样，靠变异测试才发现（变体把读数写进审计，
    对应断言纹丝不动）。
    """
    db = client.app.state.db
    rows = db._conn.execute("SELECT payload_json FROM audit_events").fetchall()
    return " ".join(str(r[0]) for r in rows)


def test_the_audit_never_stores_the_phone_number_itself(client: TestClient) -> None:
    """审计链会被导出、会被人看，而号码是 PII。

    记「谁给谁登记了」足够回答「这个号码哪来的」，不需要把号码本身留在链上。
    """
    fam = _login(client, "daughter-demo")
    client.put(f"{V1}/contacts/son-demo/phone", headers=fam, json={"phone": "13800001111"})
    assert "13800001111" not in _audit_blob(client), "号码被写进审计 payload 了"
    assert "登记了紧急联系电话" in client.get(f"{V1}/records", headers=fam).text, \
        "这件事没有留下任何痕迹"


# ---- 身体数据：此前只能读，没有任何地方能写 --------------------------------

def test_health_summary_starts_empty_and_says_so(client: TestClient) -> None:
    """**阳性对照**：先证明它一开始确实是空的。

    不先证明这一点，下面「记了一条之后就有了」可能只是因为它本来就有。
    """
    got = client.get(f"{V1}/health-summary").json()
    assert got["metrics"] == []
    assert got["recorded"] == 0
    assert got["note"], "空的时候要说一句话，不能只留白"
    assert got["overall"] is None, "后端没有下结论的依据，就不许下结论"


def test_recording_a_vital_makes_it_show_up(client: TestClient) -> None:
    r = client.post(f"{V1}/health/events", json={"type": "血压", "value": "128/82"})
    assert r.status_code == 200, r.text
    assert r.json()["unit"] == "mmHg", "血压的默认单位没带上"

    after = client.get(f"{V1}/health-summary").json()
    assert after["recorded"] == 1
    assert after["metrics"], "记进去了却读不出来"
    m = after["metrics"][0]
    assert m["label"] == "血压" and m["value"] == "128/82" and m["unit"] == "mmHg"
    assert after["note"] is None, "有数据了就不该再说「还没有记到」"


def test_a_blood_pressure_stays_one_string(client: TestClient) -> None:
    """「128/82」不是一个数。

    拆成两个数字字段的话，它和「体重 62.5」就没法用同一条路径记，
    而老人念出来的就是这两种形状。
    """
    client.post(f"{V1}/health/events", json={"type": "体重", "value": "62.5"})
    client.post(f"{V1}/health/events", json={"type": "血压", "value": "128/82"})
    values = {m["label"]: m["value"] for m in client.get(f"{V1}/health-summary").json()["metrics"]}
    assert values["血压"] == "128/82"
    assert values["体重"] == "62.5"


def test_recording_a_vital_needs_a_type_and_a_value(client: TestClient) -> None:
    assert client.post(f"{V1}/health/events", json={"value": "128/82"}).status_code == 400
    assert client.post(f"{V1}/health/events", json={"type": "血压"}).status_code == 400


def test_an_unknown_measurement_is_not_forced_into_a_category(client: TestClient) -> None:
    """认不出来的按「随手记一笔」处理。

    一条归错类的健康记录，比一条没归类的更难发现——它会安静地混进
    某一类的统计里，而没有任何东西显得不对。
    """
    r = client.post(f"{V1}/health/events", json={"type": "今天走了几步", "value": "3200"})
    assert r.status_code == 200
    assert r.json()["unit"] is None, "不认识的项不该被安上一个单位"


def test_the_audit_never_stores_the_reading_itself(client: TestClient) -> None:
    """体征是健康隐私，而审计链会被导出、会被人看。

    链上记「记了哪一项、什么时候」，足够回答「这条数据哪来的」。
    """
    client.post(f"{V1}/health/events", json={"type": "血糖", "value": "6.7"})
    assert "6.7" not in _audit_blob(client), "血糖读数被写进审计 payload 了"
    assert "记了一次身体数据" in client.get(f"{V1}/records").text, "这件事没有留下任何痕迹"


def test_a_reading_without_a_single_value_does_not_echo_its_own_title(client: TestClient) -> None:
    """拿不到读数时要**留空**，不能把标题填进去当值。

    实测的样子（访客沙箱自带的演示事件，payload 里存的是
    `systolic`/`diastolic` 这类结构化字段，本来就没有 `value`）：
    屏幕上是「早晨量了血压：132/84 —— 早晨量了血压：132/84」，标签和值同一串字。
    兜底把「这条记录没有单一读数」显示成了「读数等于它的标题」。
    """
    visitor = client.post("/v2/auth/visitor", json={})
    if visitor.status_code != 200:
        pytest.skip("这个部署没有访客沙箱")
    theirs = {"Authorization": "Bearer " + visitor.json()["elder_token"]}
    metrics = client.get(f"{V1}/health-summary", headers=theirs).json()["metrics"]
    assert metrics, "访客沙箱没有演示健康事件，这条判据没有依据"
    same = [m for m in metrics if m["value"] is not None and m["value"] == m["label"]]
    assert not same, f"标签和值是同一串字：{same}"


def test_health_events_do_not_leak_across_families(client: TestClient) -> None:
    """守的是「看不到我的」，**不是**「它那边是空的」。

    第一版断言 `recorded == 0`，红了——实测那 3 条是访客沙箱**自己种的**演示数据
    （`fam-ve55450bee234`），它并没有看到我的 128/82。
    「新沙箱一开始一定是空的」这个前提早就不成立了，而这个仓库的
    `verify_features_v6.py:162-176` 里**逐字写着**同一个教训。我还是踩了。

    空列表也能是「接口坏了返回空」，所以正确的判据有两条：
    ① 看不到我这条读数；② 它看到的每一条都属于它自己。
    """
    client.post(f"{V1}/health/events", json={"type": "血压", "value": "128/82"})
    visitor = client.post("/v2/auth/visitor", json={})
    if visitor.status_code != 200:
        pytest.skip("这个部署没有访客沙箱")
    theirs = {"Authorization": "Bearer " + visitor.json()["elder_token"]}
    got = client.get(f"{V1}/health-summary", headers=theirs).json()
    assert "128/82" not in [m["value"] for m in got["metrics"]], "看到了别的家庭的读数"
    assert "血压" not in [m["label"] for m in got["metrics"] if m["value"] == "128/82"]


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

def test_records_paginate_after_filtering_not_before(client: TestClient) -> None:
    """分页必须在**筛选之后**做。

    反过来（先切一页再按类别筛）会给出一个随类别变化、看起来像 bug 的结果：
    选「支付」只剩两条，而库里有二十条——因为这一页里恰好只有两条是支付。
    老人不会理解这件事，而它和「真的只有两条」在屏幕上长得一模一样。
    """
    _pay_to(client, "done")
    for i in range(6):
        client.post(f"{V1}/reminders", json={"title": f"吃药{i}", "time": "08:00"})

    everything = client.get(f"{V1}/records", params={"limit": 500}).json()
    assert everything["total"] > 6, "记录太少，分页测不出东西"

    first = client.get(f"{V1}/records", params={"limit": 3}).json()
    assert len(first["items"]) == 3
    assert first["count"] == 3
    assert first["total"] == everything["total"], "total 应该是筛完的总数，不是这一页的条数"
    assert first["hasMore"] is True

    second = client.get(f"{V1}/records", params={"limit": 3, "offset": 3}).json()
    assert [i["id"] for i in second["items"]] != [i["id"] for i in first["items"]], \
        "第二页和第一页是同一批"

    # 关键：按类别筛之后，total 要是**那一类的总数**，而不是「前一页里恰好有几条」。
    paid = client.get(f"{V1}/records", params={"type": "支付", "limit": 2}).json()
    paid_all = client.get(f"{V1}/records", params={"type": "支付", "limit": 500}).json()
    assert paid["total"] == paid_all["total"] == len(paid_all["items"])
    assert paid["total"] >= len(paid["items"])


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
