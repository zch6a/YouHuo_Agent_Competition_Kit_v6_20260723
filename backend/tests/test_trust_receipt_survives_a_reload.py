"""凭证必须在第二次打开这一页时还在——而且这一页**永远不许自己去办一笔**。

## 这一页的两段历史

**第一段。** `/trust` 整页就只有一份凭证，它原先无条件新办一次缴费，而后端对同一张
账单是**幂等**的（那是对的产品行为）：

    POST /v2/chat 「帮我交这个月的水费」
    → {"code": "duplicate_blocked", "message": "这笔账单已经在办理或已经完成，不会重复提交。"}

于是第一次打开好的，第二次打开整页只有一句「账单金额没读到，不能凭空造一份凭证」。
更糟的一种：任何一次半途而废（关掉标签页、网断了）留下一件停在"等他确认"的任务，
那件任务把这个家庭的这张账单**永久**挡住——这一页从此再也出不来凭证。

三道浏览器闸门当时全绿，因为它们每一次都用一个全新的访客沙箱。而一位评委刷新一次
页面就会看到那句失败。**闸门走的路和人走的路不是同一条**。

**第二段（2026-08-14）。** 上面那次修复只改了"什么时候办"，没有改"办不办"：链上
没有账单时它仍然会真的走一遍缴费——建会话、说「帮我交这个月的水费」、复述确认、
再调 `/v2/family/approve`。**打开一张只读的凭证会凭空发起一笔缴费。**
那条路现在删了，契约由 `test_receipt_is_read_only.py` 钉住。

## 这份文件的判据随之改了形状

`_render_once()` 是 `renderReceipt` 的接口序列复刻。旧版里它也带着那条缴费路径，
所以在 JS 已经删掉之后，下面两条测试**照样绿**——它们测的是复刻，不是页面。
一份和被测对象漂开的复刻，比没有测试更糟：它会一直报平安。

所以复刻也改成只读，而"那一笔缴费"由**测试自己**去办：那本来就是用户的动作，
不是页面的动作。这一改还让第二条判据更强了——停在等确认的那件任务，现在是
只读渲染真的从任务列表里读到的。
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


def _pay_once(client: TestClient, elder: str, family: str) -> str:
    """老人办一笔水费，家人点头。**这是用户的动作，不是这一页的动作。**

    以前这段藏在 `_render_once` 里，也就是"渲染顺手办一笔"。分出来之后，两件事
    在测试里也各归各位：谁办的，和这一页看到了什么。
    """
    eld = {"Authorization": f"Bearer {elder}"}
    fam = {"Authorization": f"Bearer {family}"}
    session = client.post("/v2/sessions", json={}, headers=eld).json()["session_id"]
    first = client.post(
        "/v2/chat", json={"session_id": session, "text": "帮我交这个月的水费"}, headers=eld,
    ).json()
    amount = (first.get("data") or {}).get("amount_yuan")
    if not amount:
        m = re.search(r"(\d+\.\d{2})\s*元", first.get("message", ""))
        amount = m.group(1) if m else None
    assert amount, f"账单金额没回来，这条测试的前提就不成立：{first}"
    confirmed = client.post(
        "/v2/chat", json={"session_id": session, "text": f"确认支付{amount}元"}, headers=eld,
    ).json()
    digest = confirmed.get("approval_digest")
    assert digest, f"没有确认摘要：{confirmed}"
    client.post(
        "/v2/family/approve",
        json={"task_id": confirmed["task_id"], "approve": True, "approval_digest": digest},
        headers=fam,
    )
    return confirmed["task_id"]


def _render_once(client: TestClient, family: str) -> dict:
    """复刻 `renderReceipt` 的接口序列。**只读。**

    返回空 dict 表示"这一次出不来凭证"——也就是页面上那句「还没有可以出示的凭证。」
    注意它只需要家人令牌：这一页不再需要老人身份去说话。
    """
    fam = {"Authorization": f"Bearer {family}"}
    bills = [
        t for t in client.get("/v2/tasks?limit=100", headers=fam).json()
        if t["task_type"] == "bill_payment"
    ]
    if not bills:
        return {}
    task = max(bills, key=lambda t: str(t["updated_at"]))
    audit = client.get("/v2/audit?limit=200", headers=fam).json()
    mine = [e for e in audit.get("events", []) if e["entity_id"] == task["id"]]
    return task if mine else {}


def test_the_receipt_is_still_there_on_the_second_visit(client):
    """办过一笔之后，连着打开两次都要看得见它。

    守的仍然是最初那条：同一张账单不会重复提交（对的），所以凭证不能依赖
    「每次载入都新办成一笔」。区别只在于现在这一页**根本不办**，那一笔是上面
    `_pay_once` 里由用户办的。
    """
    elder, family = _token(client, "elder-demo"), _token(client, "daughter-demo")
    paid = _pay_once(client, elder, family)

    first = _render_once(client, family)
    assert first, "办完之后第一次打开就出不来凭证"
    assert first["id"] == paid
    assert first["status"] == "completed", f"那一笔没办成：{first['status']}"

    second = _render_once(client, family)
    assert second, "第二次打开出不来凭证"
    assert second["id"] == first["id"], "第二次显示的应该还是同一次缴费"


def test_an_empty_chain_shows_nothing_rather_than_paying(client):
    """链上什么都没有的时候，这一页给出的是空，不是一笔新缴费。

    这是被删掉那条路径的触发条件，也是它的注释自己写的那个场景：
    「全新沙箱里的路径，也就是评委第一次打开这一页时走的那一条」。

    判据是**任务数量不变**：只读渲染前后，这个家庭的任务列表必须一样长。
    渲染一次就多出一笔缴费，正是这条契约要禁止的事。
    """
    family = _token(client, "daughter-demo")
    fam = {"Authorization": f"Bearer {family}"}

    before = client.get("/v2/tasks?limit=100", headers=fam).json()
    assert not [t for t in before if t["task_type"] == "bill_payment"], (
        "这个夹具里一开始就有缴费任务，这条测试造不出被测状态"
    )

    assert _render_once(client, family) == {}, "空链上不该有凭证"

    after = client.get("/v2/tasks?limit=100", headers=fam).json()
    assert len(after) == len(before), (
        f"渲染一次凭证之后任务多了 {len(after) - len(before)} 件——"
        "这一页又开始自己办事了"
    )


def test_a_stranded_confirmation_does_not_poison_the_page(client):
    """一件停在"等他确认"的任务不能把这一页永久堵死。

    这是实测撞到的那一种：关掉标签页、网断了、或者只是探测脚本跑了一半——留下一件
    `awaiting_elder_confirmation`，而它让这张账单从此 `duplicate_blocked`。
    在改之前，这个家庭的 `/trust` 从那一刻起再也出不来凭证。

    改成只读之后这一条更强了：那件停住的任务是渲染**真的从任务列表里读到**的，
    而不是复刻里那条缴费路径的副产品。
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
    task = _render_once(client, family)
    assert task, "有一件停在等确认的任务时，这一页出不来凭证"
    assert task["status"] != "completed", "这一笔确实没办完，凭证不该说它办好了"


def test_render_receipt_reads_and_never_writes():
    """静态判据：`renderReceipt` 只读任务与审计链，不碰任何写接口。

    这一条取代了原先的 `test_the_receipt_reads_the_chain_before_it_pays`
    ——那一条断言的是「先读链，**再**去 /v2/chat 新办一次」，也就是把缺陷本身
    写成了需求。逐项对照：

      旧：`/v2/tasks` 出现在 `/v2/chat` 之前   → 新：`/v2/chat` 根本不许出现
      旧：`确认支付` 必须还在 renderReceipt 里 → 复述确认是**后端**的事，
          由 test_trust_receipt.py::test_backend_produces_everything_the_receipt_needs
          在真实引擎上验（TEACH_BACK_VERIFIED 的 expected == heard == amount），
          比查一个前端字符串强

    更广的那条（整个 trust.js 不许有写方法）在 `test_receipt_is_read_only.py`。
    这一条只盯 `renderReceipt` 的函数体，因为那里是缺陷发生的地方。
    """
    # **剥注释再查。** 这个修复本身要求把「这里原先有一段 /v2/family/approve，
    # 删了，理由是……」写进注释里，于是不剥注释的判据会在注释里读到那个路径、
    # 报一个不存在的缺陷。实测就是这样红的。
    from .helpers import strip_js_comments

    js = strip_js_comments((STATIC / "trust.js").read_text(encoding="utf-8"))
    body = js[js.index("async function renderReceipt()"):]

    assert "/v2/tasks" in body, "renderReceipt 不再读任务列表了"
    assert "/v2/audit" in body, "renderReceipt 不再读审计链了——那份凭证就成了插图"
    for path in ("/v2/sessions", "/v2/chat", "/v2/family/approve"):
        assert path not in body, (
            f"renderReceipt 里又出现了 {path}。渲染一张凭证不许创建、推进、批准、"
            "执行、重试或改动任何一笔业务事务——没有数据就说「还没有可以出示的凭证」。"
        )
