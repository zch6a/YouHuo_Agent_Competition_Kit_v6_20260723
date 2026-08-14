"""可信页顶部的事务凭证：它必须是真办出来的，而且必须说人话。

这一页原先是六张能力演示卡：每张能证明一件事，但要评委自己把六件事拼成一次完整的
办事经过。凭证反过来——先给一次真实缴费的全过程，六张卡再作为它每一环的单独证明。

凭证唯一的价值在于"这件事真的发生过、而且留下了可核验的痕迹"。所以这一组断言守的
是**它没有退化成一张画出来的图**：

1. 数据从审计链来，不是写死在 JS 里的样例。
2. 每一个会出现在凭证上的事件类型都有中文说法；认不出的类型不许把枚举名印到正文。
3. 后端确实会为一次缴费产出凭证需要的那几条记录（这条在真实引擎上跑，不看前端）。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"


def _trust_js() -> str:
    return (STATIC / "trust.js").read_text(encoding="utf-8")


def _receipt_steps() -> dict[str, str]:
    """`RECEIPT_STEPS` 里声明了说法的事件类型 → 它的 `who`。"""
    text = _trust_js()
    block = re.search(r"^const RECEIPT_STEPS = \{\n(.*?)^\};$", text, re.S | re.M)
    assert block, "trust.js 里找不到 `const RECEIPT_STEPS`——凭证的翻译层被改名或删掉了"
    steps = dict(re.findall(r"^  ([A-Z_]+): \{[^\n]*?\n?\s*who: '([^']+)'", block.group(1), re.M))
    assert steps, "凭证翻译层解析出来是空的——行格式变了，这个文件的断言会全部空转"
    return steps


def test_the_receipt_reads_the_audit_chain_rather_than_a_canned_example():
    """凭证必须去读 `/v2/audit`，并且按 `entity_id` 挑出这一件任务。

    一份不查链的"凭证"就是一张插图。这条钉住的是数据来源本身，不是渲染。
    """
    js = _trust_js()
    assert "/v2/audit" in js, "凭证没有读审计链"
    # 「只画这一件事的链」这条性质**还在，保证它的地方换了**。
    #
    # 旧断言找的是客户端过滤 `entity_id === taskId`。那种做法是「取最近 200 条再
    # 自己筛」——一个家庭用久了，第 201 条之前的事务就再也拼不出完整的链，而页面
    # 看不出来：它会渲染一份少了前几步的凭证。所以筛选移到了服务端
    # （`api.py::list_audit` 这一轮新增的 `entity_id` 参数），limit 因此作用在
    # 这一件事的事件上，而不是整个家庭的流水上——比旧写法强，不是弱。
    assert "entity_id=" in js, (
        "凭证没有按任务向服务端要链，会把整条家庭流水都画出来"
    )
    assert "chain_valid" in js, "凭证没有展示链自校验的结果——那正是它可信的理由"


def test_the_receipt_never_runs_the_payment():
    """凭证渲染**不许**去办一笔缴费。

    这一条是上一条的反面，而上一条（`test_the_receipt_actually_runs_the_payment`）
    把一个 P0 写成了需求：它要求 `/v2/sessions`、`/v2/chat`、`/v2/family/approve`
    出现在 `trust.js` 里，理由是「只查已有任务而不办，在一个刚起的库上会渲染空白」。

    「会渲染空白」的正确答案是**说它是空的**，不是「那我现在帮你办一笔出来」。
    打开一张只读的凭证会凭空发起一笔缴费，而那段代码自己的注释写着触发条件是
    「评委第一次打开这一页时走的那一条」。

    逐项对照（判据覆盖不许变弱）：

      旧：三个写接口必须在 → 新：三个写接口都不许在
      旧：`确认支付` 必须在前端    → 复述确认是**后端**的事，由下面
          `test_backend_produces_everything_the_receipt_needs` 在真实引擎上验
          （`TEACH_BACK_VERIFIED` 的 expected == heard == amount），比查一个
          前端字符串强得多
      新增：空数据时必须给出空态文案，而不是留一片白
    """
    # 剥注释再查：这个修复要求把被删掉的那三个路径写进注释解释清楚，
    # 而不剥注释的判据会在注释里读到它们。
    from .helpers import strip_js_comments

    js = strip_js_comments(_trust_js())
    for path in ("/v2/sessions", "/v2/chat", "/v2/family/approve"):
        assert path not in js, (
            f"凭证页又出现了 {path}——渲染一张凭证不许改动任何一笔业务事务"
        )
    assert "还没有可以出示的凭证" in js, (
        "没有数据时这一页要说「还没有可以出示的凭证」，不能留一片白"
    )


def test_a_failed_receipt_does_not_claim_success():
    """办不成的时候，这一块必须说办不成。

    这一页的全部内容就是"只有真办成了才说办成了"。一个在失败时仍然画出一张漂亮
    时间轴的凭证，比没有凭证更糟。
    """
    js = _trust_js()
    assert "receiptFailed" in js, "凭证没有失败分支"
    assert "这一次没能办成" in js, "失败时没有说清楚发生了什么"
    # 状态徽章必须跟着任务的真实状态走，不能写死成"已办好"。
    assert "task.status === 'completed'" in js, "凭证的状态徽章没有看任务的真实状态"


def test_every_receipt_step_speaks_chinese():
    """凭证正文里不许出现事件枚举名。

    `NOTIFICATION_CREATED` 这样的标识符印在正文里，等于把"我们没给这个事件写说明"
    的内部状态直接展示给评委。原始类型在下面那个哈希折叠里——那里全是标识符，
    它属于那里。
    """
    js = _trust_js()
    steps = _receipt_steps()
    assert len(steps) >= 6, f"凭证只认得 {len(steps)} 种事件：{sorted(steps)}"
    for name, who in steps.items():
        assert not re.search(r"[A-Za-z]", who), f"「{name}」的 who 里有英文：{who}"

    # 认不出的类型走兜底分支，而兜底分支不许把 event_type 拼进正文。
    #
    # 从**时间轴那个循环**里面开始找，不是从文件开头。
    # 原写法是整份文件上的第一个 `} else {`——`renderReceipt` 前面新增一个分支
    # （"链上已经有这件事就读它，否则真的办一次"）之后，它匹配到的是那一个，
    # 于是这条断言去一段跟未知事件毫无关系的代码里找中文说法，红了。
    # 这不是兜底分支坏了，是这条断言假设"文件里第一个 else 就是它要找的那个"。
    loop = js.index("for (const event of mine)")
    fallback = re.search(r"} else \{(.*?)\n    \}", js[loop:], re.S)
    assert fallback, "找不到未知事件的兜底分支"
    assert "event.event_type" not in fallback.group(1), (
        "兜底分支把事件枚举名印到了凭证正文里"
    )
    assert "系统留下一条记录" in fallback.group(1), "兜底分支没有给出中文说法"


def test_unknown_events_are_still_shown():
    """认不出的事件也要出现在凭证上。

    链上有十条、凭证上有五行，而没有任何东西说得出差额去哪了——那恰恰是凭证最不该
    有的性质。所以渲染循环不许 `continue`。
    """
    js = _trust_js()
    loop = re.search(r"for \(const event of mine\) \{(.*?)\n    list\.appendChild", js, re.S)
    assert loop, "找不到凭证的渲染循环"
    assert "continue" not in loop.group(1), "渲染循环里有 continue——有事件会被静默丢掉"


def test_backend_produces_everything_the_receipt_needs(tmp_path):
    """在真实引擎上走一遍：凭证要的那几条记录后端确实会产出。

    前端断言只能证明"代码打算这么做"。这一条证明"后端真的给得出"——凭证上那三个
    可核验的点（金额来自账单、复述通过、家人同意的摘要和老人确认的是同一个）
    必须在审计链里真的存在。
    """
    app = create_app(tmp_path / "receipt.db", demo_mode=True)
    with TestClient(app) as client:
        def token(actor: str) -> dict[str, str]:
            r = client.post("/v2/auth/demo", json={"actor_id": actor})
            assert r.status_code == 200
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        elder, family = token("elder-demo"), token("daughter-demo")
        session = client.post("/v2/sessions", json={}, headers=elder).json()["session_id"]
        first = client.post(
            "/v2/chat", json={"session_id": session, "text": "帮我交这个月的水费"}, headers=elder
        ).json()
        amount = (first.get("data") or {}).get("amount_yuan")
        assert amount, "账单金额没回来，凭证的第一行就无从谈起"

        confirmed = client.post(
            "/v2/chat",
            json={"session_id": session, "text": f"确认支付{amount}元"},
            headers=elder,
        ).json()
        digest = confirmed.get("approval_digest")
        assert digest, "没有确认摘要，凭证证明不了「家人同意的和他确认的是同一笔」"
        task_id = confirmed["task_id"]

        approved = client.post(
            "/v2/family/approve",
            json={"task_id": task_id, "approve": True, "approval_digest": digest},
            headers=family,
        ).json()
        assert approved["code"] == "task_completed"

        audit = client.get("/v2/audit?limit=200", headers=family).json()
        assert audit["chain_valid"] is True, "审计链自校验没过"
        mine = [e for e in audit["events"] if e["entity_id"] == task_id]
        kinds = {e["event_type"] for e in mine}
        for required in ("TASK_CREATED", "TEACH_BACK_VERIFIED", "ELDER_CONFIRMED",
                         "FAMILY_APPROVED_AND_EXECUTED"):
            assert required in kinds, f"审计链里没有 {required}，凭证少一环：{sorted(kinds)}"

        # 凭证声称的那三个可核验的点，逐个在链上验。
        teach = next(e for e in mine if e["event_type"] == "TEACH_BACK_VERIFIED")
        assert teach["payload"]["expected"] == teach["payload"]["heard"] == amount, (
            "复述记录里的金额和账单对不上"
        )
        elder_digest = next(
            e for e in mine if e["event_type"] == "ELDER_CONFIRMED"
        )["payload"]["approval_digest"]
        family_digest = next(
            e for e in mine if e["event_type"] == "FAMILY_APPROVED_AND_EXECUTED"
        )["payload"]["approval_digest"]
        assert elder_digest == family_digest, (
            "家人同意的摘要和老人确认的不是同一个——凭证上那句话就是假的"
        )

        # 每一条都带着上一条的哈希，否则"改一条后面全部对不上"是空话。
        chain = audit["events"]
        for prev, cur in zip(chain, chain[1:]):
            assert cur["prev_hash"] == prev["event_hash"], (
                f"链断在 {cur['event_type']}：prev_hash 不是上一条的 event_hash"
            )

        # 老人说的原话不在链上。凭证专门写了这一句，它必须是真的。
        blob = str(audit["events"])
        assert "帮我交这个月的水费" not in blob, (
            "老人的原话进了审计链——凭证上「他说的原话不在链上」那一句就成了假话"
        )
