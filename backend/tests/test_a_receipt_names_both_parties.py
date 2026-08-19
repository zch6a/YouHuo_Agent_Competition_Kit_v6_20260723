"""凭证上必须写清**向谁交的钱**和**谁点的头**。

## 这道门从哪来

演示台右栏那四个字里有一个是「证」：「办完给一张凭证，每一步都对得上」。
把三条会产出凭证的路径各办一笔，读同一个接口：

    种子铺的那一笔（已完成）   收款方 None            谁点的头 None
    按钮路径 /api/v1/prepare   收款方 示例供电公司     ——
    语音路径 /v2/chat（主路径） 收款方 None            ——

三条路径，两条的收款方是空的，其中一条是**这个产品的主路径**。
而演示家庭里唯一那笔办完的钱，两格都空。

## 三个独立成因

① `BillingService.lookup` 的 data 里没有 `company`。引擎填槽的全部来源就是
   `task.slots.update(lookup.data)`（`engine.py:725`），所以语音建的支付
   槽位里没有收款方。按钮路径之所以有，是因为 `/api/v1/payments/prepare`
   在合并 lookup 之前**自己先塞了一份**——而那张对照表当时是门面层的局部变量。

② 种子的 slots 里没有 `company`，也没有引擎批准时会写的那三个槽位
   （`family_approved` / `family_approver` / `family_approval_count`，
   见 `engine.py:1125-1127`）。凭证的「谁点的头」两条读法都落空：
   payload 里的 `approved_by`（山水版那条路径写的）没有，
   `slots["family_approver"]`（引擎那条写的）也没有。

③ 收款方有**两个名字**。种子的审计载荷写「北京自来水公司」——这个字符串
   代码库里没有任何东西会产出——而账单页、凭证页、家人审批页读的都是
   `示例自来水公司`。两个名字同时在屏幕上：可信中心印前者（`trust.js:197`
   读 `p.authority`），凭证页印后者。

## 判据

守的是性质，不是实现：**一笔办完的钱，凭证要说得出向谁交的、谁批的；
一笔没办完的，两格都不许有值。** 第二半和第一半一样重要——
把两格填成常量能让上半条永远绿，而那正是这一层的 P0 明令禁止的
（渲染凭证绝不许宣称一笔并未发生的交易）。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.services import BILL_COMPANY

V1 = "/api/v1"
YOUHUO = Path(__file__).resolve().parents[1] / "youhuo"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "receipt.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def attention_client(tmp_path, monkeypatch):
    """`attention` 态才有那笔停在「等家属点头」的缴费（`api.py:127`）。

    `normal` 的定义是「一切如常」，一件悬着的缴费不属于如常，所以它只在
    `attention` 下播。用 monkeypatch 而不是改上面那个夹具：那一笔**不该**
    出现在 normal 里，把它拉进来会掩盖这个语义差别。
    """
    monkeypatch.setenv("YOUHUO_DEMO_STATE", "attention")
    app = create_app(tmp_path / "receipt-attention.db", demo_mode=True)
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, actor_id: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _pay_by_voice(client: TestClient) -> str:
    """走**主路径**办一笔水费，一路到办完，返回事务号。

    这条路径此前一条凭证判据都没有：`test_app_api_contract` 里那几条
    全部经由 `/api/v1/payments/prepare`，而那一层自己会塞 `company`，
    所以它永远看不见 `lookup()` 少了这一项。
    """
    elder = _login(client, "elder-demo")
    family = _login(client, "daughter-demo")
    sid = client.post("/v2/sessions", headers=elder, json={}).json()["session_id"]

    said = client.post("/v2/chat", headers=elder,
                       json={"session_id": sid, "text": "帮我交这个月的水费"}).json()
    task_id = said["task_id"]
    assert task_id, f"语音没建出任务：{said}"
    client.post("/v2/chat", headers=elder,
                json={"session_id": sid, "text": "确认支付68.40元"})

    # 摘要在**列表**项上，`family.js:190` 读的就是这个。
    tasks = client.get("/v2/tasks", headers=family).json()
    items = tasks if isinstance(tasks, list) else tasks.get("items", [])
    row = next((t for t in items if t.get("id") == task_id), None)
    assert row and row.get("approval_digest"), f"取不到审批摘要：{row}"
    approved = client.post("/v2/family/approve", headers=family, json={
        "task_id": task_id, "approve": True,
        "approval_digest": row["approval_digest"],
        "reason": "家属已核对任务摘要"})
    assert approved.status_code == 200, approved.text
    return task_id


def test_a_voice_paid_bill_names_who_was_paid(client: TestClient) -> None:
    """语音办完的那一笔，凭证要写清向谁交的钱。

    这是主路径。它此前拿到的是 `None`——因为 `lookup()` 不回 `company`，
    而引擎填槽只认 `lookup.data`。
    """
    task_id = _pay_by_voice(client)
    elder = _login(client, "elder-demo")
    cert = client.get(f"{V1}/payments/{task_id}/certificate", headers=elder).json()

    assert cert["status"] == "completed", cert
    assert cert["company"], (
        "语音办完的这一笔，凭证上「向谁交的钱」是空的。"
        "`BillingService.lookup` 的 data 里要有 `company`——"
        "`engine.py` 的 `task.slots.update(lookup.data)` 是引擎填槽的**全部**来源。")
    assert cert["company"] in BILL_COMPANY.values(), (
        f"凭证上的收款方 {cert['company']!r} 不在 `BILL_COMPANY` 里。"
        "屏幕上出现了一个没有任何代码会产出的名字。")
    assert cert["approvedBy"], "凭证上必须写清是谁点的头"


def test_the_seeded_finished_payment_fills_both_boxes(client: TestClient) -> None:
    """演示家庭里唯一那笔办完的钱，两格都要有值。

    评委看到的就是这一笔。它此前两格都是空的，而两个值就躺在它自己的链里：
    链上有一条「女儿 · FAMILY_APPROVED_AND_EXECUTED」，载荷里带着收款方。
    """
    elder = _login(client, "elder-demo")
    cert = client.get(f"{V1}/payments/task-seed-bill-demo/certificate",
                      headers=elder).json()

    assert cert["status"] == "completed", cert
    assert cert["company"], (
        "种子那笔已完成的缴费，凭证上「向谁交的钱」是空的。"
        "种子的 slots 要和真实引擎一样带 `company`。")
    assert cert["approvedBy"], (
        "种子那笔已完成的缴费，凭证上「谁点的头」是空的——"
        "而它的链上就有一条「女儿 · 批准并执行」。"
        "种子要写 `slots['family_approver']`，引擎批准时写的就是它"
        "（`engine.py:1126`）。")
    # 链上确实有家人那一条，否则「谁点的头」有值反而是在撒谎。
    assert any(step["action"] == "FAMILY_APPROVED_AND_EXECUTED"
               for step in cert["chain"]), cert["chain"]


def test_an_unfinished_payment_names_nobody(attention_client: TestClient) -> None:
    """还没办完的那一笔，「谁点的头」必须是空的。

    这一条和上面两条一样重要。把两格填成常量能让上面两条永远绿，
    而那正是这一层的 P0 明令禁止的：渲染凭证绝不许宣称一笔并未发生的交易。

    补 `family_approver` 那个改动的真实风险就在这里：它要是加到了
    `awaiting_family_approval` 那个场景上，这一笔就会在没人批准的情况下
    说出一个批准人。
    """
    client = attention_client
    elder = _login(client, "elder-demo")
    cert = client.get(f"{V1}/payments/task-seed-await-demo/certificate",
                      headers=elder).json()

    assert cert["status"] == "awaiting_family_approval", cert
    assert cert["approvedBy"] is None, (
        f"这一笔还在等家人点头，而凭证说是 {cert['approvedBy']!r} 批的。")
    assert cert["paidAt"] is None, "还没办完，不许有办好的时刻"


def test_the_company_is_this_bill_s_company(client: TestClient) -> None:
    """收款方要跟着**这一张**账单走，不是一个常量。

    没有这一条，上面两条都能被「写死一个 `BILL_COMPANY` 里的名字」满足——
    那时电费的凭证上会印着自来水公司，而两条判据一个都不会红。
    """
    elder = _login(client, "elder-demo")
    bills = client.get(f"{V1}/bills", headers=elder).json()["items"]
    electric = next((b for b in bills if "电" in str(b.get("type"))), None)
    assert electric, f"演示账单里没有电费：{[b.get('type') for b in bills]}"

    pid = client.post(f"{V1}/payments/prepare", headers=elder,
                      json={"billId": electric["id"]}).json()["id"]
    cert = client.get(f"{V1}/payments/{pid}/certificate", headers=elder).json()
    assert cert["company"] == BILL_COMPANY["电费"], (
        f"电费的凭证上印的是 {cert['company']!r}，"
        f"而这一张的收款方是 {BILL_COMPANY['电费']!r}。")


def test_one_bill_has_exactly_one_collecting_company() -> None:
    """收款方只能有一个名字。

    静态判：种子和演示常量里出现的所有「××公司」，都必须是 `BILL_COMPANY`
    里的值。原先种子写「北京自来水公司」，而这个名字代码库里没有任何东西
    会产出——它只在演示数据里存在，却被 `trust.js:197` 印在可信中心上，
    和凭证页印的那个不是同一个。
    """
    known = set(BILL_COMPANY.values())
    offenders: list[str] = []
    for path in sorted(YOUHUO.glob("*.py")):
        src = io.open(path, encoding="utf-8").read()
        # 只看字符串字面量里的公司名，注释里提到旧名字（解释这道门为什么存在）不算。
        src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
        for name in re.findall(r"['\"]([一-鿿]{2,12}公司)['\"]", src):
            if name not in known:
                offenders.append(f"{path.name}: {name}")
    assert not offenders, (
        f"这些收款方名字不在 `BILL_COMPANY` 里：{offenders}。\n"
        "  屏幕上同一笔钱会出现两个收款方——可信中心读审计载荷里的那个，"
        "凭证页读 `BILL_COMPANY` 里的那个。")
