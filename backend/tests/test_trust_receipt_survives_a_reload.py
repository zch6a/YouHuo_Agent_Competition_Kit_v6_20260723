"""凭证必须在第二次打开这一页时还在。

`/trust` 整页就只有一份凭证。它原先无条件新办一次缴费，而后端对同一张账单是**幂等**
的（那是对的产品行为）：

    POST /v2/chat 「帮我交这个月的水费」
    → {"code": "duplicate_blocked", "message": "这笔账单已经在办理或已经完成，不会重复提交。"}

于是第一次打开好的，第二次打开整页只有一句「账单金额没读到，不能凭空造一份凭证」。
更糟的一种：任何一次半途而废（关掉标签页、网断了）留下一件停在"等他确认"的任务，
那件任务把这个家庭的这张账单**永久**挡住——这一页从此再也出不来凭证。

三道浏览器闸门当时全绿，因为它们每一次都用一个全新的访客沙箱。而一位评委刷新一次
页面就会看到那句失败。**闸门走的路和人走的路不是同一条**——这个项目栽在这上面
不止一次（run_demo 的端口、file:// 下的黑屏）。

所以这条测试的判据就是"第二次"：同一个家庭连着渲染两次，两次都必须拿到一份凭证。
它不开浏览器——`renderReceipt` 的逻辑在 JS 里，这里复刻它调用的那串接口，
用同一个家庭跑两遍。逻辑漂移会被 `test_the_receipt_reads_the_chain_before_it_pays`
那条静态断言接住。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "receipt.db")
    with TestClient(app) as c:
        yield c


def _token(client: TestClient, actor: str) -> str:
    r = client.post("/v2/auth/demo", json={"actor_id": actor})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _render_once(client: TestClient, elder: str, family: str) -> dict:
    """复刻 renderReceipt 的接口序列，返回它渲染时用到的那件任务。

    返回空 dict 表示"这一次出不来凭证"——也就是页面上那句失败。
    """
    fam = {"Authorization": f"Bearer {family}"}
    eld = {"Authorization": f"Bearer {elder}"}

    # 先读链。
    bills = [
        t for t in client.get("/v2/tasks?limit=100", headers=fam).json()
        if t["task_type"] == "bill_payment"
    ]
    if bills:
        task = max(bills, key=lambda t: str(t["updated_at"]))
    else:
        # 链上什么都没有：真的办一次。
        session = client.post("/v2/sessions", json={}, headers=eld).json()["session_id"]
        first = client.post(
            "/v2/chat", json={"session_id": session, "text": "帮我交这个月的水费"}, headers=eld,
        ).json()
        amount = (first.get("data") or {}).get("amount_yuan")
        if not amount:
            m = re.search(r"(\d+\.\d{2})\s*元", first.get("message", ""))
            amount = m.group(1) if m else None
        if not amount:
            return {}
        confirmed = client.post(
            "/v2/chat",
            json={"session_id": session, "text": f"确认支付{amount}元"},
            headers=eld,
        ).json()
        if not confirmed.get("approval_digest"):
            return {}
        client.post(
            "/v2/family/approve",
            json={
                "task_id": confirmed["task_id"], "approve": True,
                "approval_digest": confirmed["approval_digest"],
            },
            headers=fam,
        )
        task = next(
            t for t in client.get("/v2/tasks?limit=100", headers=fam).json()
            if t["id"] == confirmed["task_id"]
        )

    audit = client.get("/v2/audit?limit=200", headers=fam).json()
    mine = [e for e in audit.get("events", []) if e["entity_id"] == task["id"]]
    return task if mine else {}


def test_the_receipt_is_still_there_on_the_second_visit(client):
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")

    first = _render_once(client, elder, family)
    assert first, "第一次打开就出不来凭证"
    assert first["status"] == "completed", f"第一次那笔没办成：{first['status']}"

    second = _render_once(client, elder, family)
    assert second, (
        "第二次打开出不来凭证。同一张账单不会重复提交（对的），"
        "所以凭证不能依赖「每次载入都新办成一笔」。"
    )
    assert second["id"] == first["id"], "第二次显示的应该还是同一次缴费"


def test_a_stranded_confirmation_does_not_poison_the_page(client):
    """一件停在"等他确认"的任务不能把这一页永久堵死。

    这是实测撞到的那一种：关掉标签页、网断了、或者只是探测脚本跑了一半——留下一件
    `awaiting_elder_confirmation`，而它让这张账单从此 `duplicate_blocked`。
    在改之前，这个家庭的 `/trust` 从那一刻起再也出不来凭证。
    """
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    eld = {"Authorization": f"Bearer {elder}"}

    # 只走第一步就撒手：这就是"半途而废"。
    session = client.post("/v2/sessions", json={}, headers=eld).json()["session_id"]
    first = client.post(
        "/v2/chat", json={"session_id": session, "text": "帮我交这个月的水费"}, headers=eld,
    ).json()
    assert first.get("task_status") == "awaiting_elder_confirmation", first

    # 现在新办会被幂等挡住——先确认这个前提还成立，否则这条测试在守一个不存在的问题。
    again = client.post(
        "/v2/chat",
        json={
            "session_id": client.post("/v2/sessions", json={}, headers=eld).json()["session_id"],
            "text": "帮我交这个月的水费",
        },
        headers=eld,
    ).json()
    assert again.get("code") == "duplicate_blocked", (
        f"后端不再幂等拦重复账单了，这条测试的前提没了：{again}"
    )

    # 而这一页仍然要出得来凭证——那件停住的任务本身就是链上的真实记录。
    task = _render_once(client, elder, family)
    assert task, "有一件停在等确认的任务时，这一页出不来凭证"
    assert task["status"] != "completed", "这一笔确实没办完，凭证不该说它办好了"


def test_the_receipt_reads_the_chain_before_it_pays():
    """静态判据：`renderReceipt` 必须先读任务列表，才允许去 `/v2/chat`。

    上面两条跑的是我复刻的接口序列，不是 trust.js 本身。这一条把两者钉在一起：
    真实代码里"先读链"必须出现在"新办一次"之前。少了它，上面两条会在 JS 改回
    无条件新办之后继续全绿。
    """
    js = (STATIC / "trust.js").read_text(encoding="utf-8")
    body = js[js.index("async function renderReceipt()"):]
    read = body.find("/v2/tasks")
    pay = body.find("/v2/chat")
    assert read != -1, "renderReceipt 不再读任务列表了"
    assert pay != -1, "renderReceipt 不再有真的办一次的那条路了"
    assert read < pay, (
        "renderReceipt 又变成先去 /v2/chat 新办一次了。"
        "同一张账单会被幂等挡住，第二次打开这一页就只剩一句失败。"
    )
    # 而"真的办一次"必须还在：全新沙箱里那条路是评委第一次打开时走的。
    assert "确认支付" in body, "复述确认那一步不能省——它就是这个产品的主张"