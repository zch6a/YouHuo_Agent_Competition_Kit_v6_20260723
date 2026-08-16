"""`/api/v1` —— 山水版老人端前端的后端门面。

这一层是「前端优先」的产物：界面先定稿，后端按它已经写死的契约补接口
（见 `backend/static/app/docs/BACKEND_INTEGRATION.md`）。

**它是门面，不是第二套业务。** 每一个接口都往下调真实服务：

    POST /payments/{id}/teach-back  →  TeachBackVerifier.verify（真的核对金额）
    POST /payments/{id}/execute     →  真实任务状态机 + 家人二次确认
    GET  /payments/{id}/certificate →  真实审计链（database.list_audit，按事务过滤）
    GET  /records                   →  真实审计流水

为什么翻译放在后端而不是改前端：那十个页面的 `assets/js/api-client.js` 里路径是
写死的，改前端等于把 Codex 的产出重写一遍。翻译放在这里，前端一行不用动，
而业务逻辑仍然只有一份。

**没有的数据就说没有。** 天气、空气、体感、睡眠、位置凭证、设备凭证这些后端
确实没有，一律回 `null`，由前端决定怎么显示——不编。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from .models import (
    AuthContext,
    ChatRequest,
    ReminderStatus,
    RiskLevel,
    SessionState,
    TaskRecord,
    TaskStatus,
    TaskType,
)
from .teach_back import TeachBackOutcome, TeachBackVerifier

#: 演示用的老人身份。这一版前端不带令牌（它的 `api-client.js` 走 cookie），
#: 所以身份在服务端固定到演示家庭的老人，与 `/v2/auth/demo` 用的是同一套数据。
_DEMO_ELDER = "elder-demo"

#: 点头的那个家人。查库定的，不是猜的：
#:   elder-demo / daughter-demo / son-demo / system-demo（家庭 fam-demo）
#: 取「女儿」这一个，因为凭证上要写清是**谁**点的头——写一个不存在的人比不写更糟。
_DEMO_FAMILY = "daughter-demo"

#: 家人点头之后写的那条审计。用大写下划线，和主引擎那套保持一致，
#: 这样记录页的翻译表能认出它（那张表的 key 是查库查出来的，见 `_WORDS`）。
_EV_FAMILY_APPROVED = "FAMILY_APPROVED_AND_EXECUTED"

#: 这一笔水费是**演示数据**，金额与单位跟现有 demo seed 一致。
#: 真接上营业厅之后换成查询即可，前端契约不变。
_WATER_BILL = {
    "id": "water-current",
    "type": "水费支付",
    "amount_cents": 6840,
    "company": "示例自来水公司",
    "account_tail": "1234",
    "month": "本月",
}

#: 审计事件类型。前端不认这些字符串，它们只在后端之间用。
_EV_PREPARED = "app.payment.prepared"
_EV_TEACH_BACK = "app.payment.teach_back"
_EV_AWAITING_FAMILY = "app.payment.awaiting_family"
_EV_SOS = "app.emergency.requested"


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


def build_app_router(db, engine, v4_store=None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["elder-app"])

    def _ctx() -> AuthContext:
        ctx = db.auth_context_for_actor(_DEMO_ELDER)
        if ctx is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="演示数据还没有铺好。",
            )
        return ctx

    def _task_or_404(ctx: AuthContext, task_id: str) -> TaskRecord:
        task = db.get_task(task_id)
        if task is None or task.family_id != ctx.family_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="没有找到这件事。"
            )
        return task

    # ---- 档案 ---------------------------------------------------------------

    @router.get("/profile")
    def profile() -> dict[str, Any]:
        ctx = _ctx()
        return {
            "name": ctx.display_name,
            # 「陪伴您 N 天」后端没有建档日期这个字段，不编。
            "days": None,
            # 天气 / 空气 / 体感同理：宁可界面上少一行。
            "weather": None,
            "air": None,
            "comfort": None,
        }

    # ---- 今日日程 -----------------------------------------------------------

    @router.get("/agenda")
    def agenda() -> dict[str, Any]:
        """首页那两张卡（「接下来」和「今日安排」）的真实数据源。

        原稿这两张卡是写死的——「14:00 心内科复诊 · 和睦家医院 2号楼3层」「08:00
        吃降压药」。那是稿子，不是这位老人的事。这里改成读真实提醒表。

        `place` 后端没有这个字段，回 null；界面上宁可不显示地点，也不编一个医院。
        """
        ctx = _ctx()
        now = datetime.now(UTC)
        today = now.date()
        items = []
        for r in db.list_reminders(ctx.family_id, limit=60):
            if r.elder_id != _DEMO_ELDER:
                continue
            due = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=UTC)
            if due.date() != today:
                continue
            done = r.status in {ReminderStatus.COMPLETED, ReminderStatus.ACKNOWLEDGED}
            items.append(
                {
                    "id": r.id,
                    "time": due.strftime("%H:%M"),
                    "title": r.title,
                    "done": done,
                    "status": "已完成" if done else "待进行",
                    "at": due.isoformat(),
                }
            )
        items.sort(key=lambda x: x["time"])

        # 「接下来」= 今天**还没做**的第一件。
        #
        # 第一版要求「时间还在此刻之后」，结果傍晚打开首页时这张卡是空的——
        # 而那两件事只是过了点、并没有做完。对一位老人来说，一件过点还没吃的药
        # 恰恰是最该摆在「接下来」的东西，不是该被藏起来的东西。
        # 优先取还没到点的；都过点了就取最早那一件，并标出来它已经过点。
        undone = [it for it in items if not it["done"]]
        ahead = [it for it in undone if it["at"] > now.isoformat()]
        pick = (ahead or undone or [None])[0]
        nxt = None
        if pick is not None:
            overdue = pick["at"] <= now.isoformat()
            nxt = {
                "time": pick["time"],
                "title": pick["title"],
                "place": None,          # 后端没有地点字段——不编一个医院出来
                "note": "这一件已经过点了。" if overdue else None,
                "overdue": overdue,
            }
        return {"next": nxt, "today": items, "count": len(items)}

    # ---- 健康概览（「我的」那一屏）------------------------------------------

    @router.get("/health-summary")
    def health_summary() -> dict[str, Any]:
        """「我的」页那一排健康数字的真实来源。

        原稿这里写死了「今日健康 良好 / 心率 72 次每分 / 血压 120/78 / 睡眠 7.5 小时」。
        后端的实情是：有一张 `health_events_v4` 事件表（真的记了什么就有什么），
        **没有**体征快照，也**完全没有**睡眠这一项。

        所以这里回的是「记到了什么」，不是「他现在怎么样」——这两件事差得很远，
        而把后者编出来正是这个产品最不该做的。取不到的一律 null。
        """
        ctx = _ctx()
        metrics: list[dict[str, Any]] = []
        events = []
        if v4_store is not None:
            try:
                from .models import ActorRole

                events = v4_store.list_health_events(
                    ctx.family_id, _DEMO_ELDER, ActorRole.ELDER
                )
            except Exception:
                events = []

        latest: dict[str, Any] = {}
        for e in events:                       # 已按时间倒序，第一条即最新
            kind = str(getattr(e, "kind", "")) or "其他"
            if kind not in latest:
                latest[kind] = e

        for kind, e in list(latest.items())[:4]:
            payload = getattr(e, "payload", None) or {}
            value = payload.get("value") or payload.get("text") or getattr(e, "title", "")
            metrics.append(
                {
                    "label": getattr(e, "title", kind),
                    "value": str(value) if value else None,
                    "unit": payload.get("unit"),
                    "at": e.event_at.isoformat() if getattr(e, "event_at", None) else None,
                }
            )

        return {
            # 「今日健康 良好」是一句结论。后端没有做这个判断的依据，就不下这个结论。
            "overall": None,
            "metrics": metrics,
            "recorded": len(events),
            "note": None if metrics else "还没有记到身体数据。",
        }

    # ---- 账单 ---------------------------------------------------------------

    @router.get("/bills/water/current")
    def current_water_bill() -> dict[str, Any]:
        """当前这一笔水费。

        `paidAt` 原先是写死的 `None`——于是凭证页和成功页的「完成时间 / 支付时间」
        两行**永远是空的**，而且看不出是「还没付」还是「接口没给」。
        现在去查这个家庭最近一笔真的走完的缴费事务：付掉了就给真时间，
        没付掉就仍然是 null（那时它本来就该空着）。
        """
        ctx = _ctx()
        b = _WATER_BILL
        paid_at = None
        for task in db.list_tasks(ctx.family_id, limit=60):
            if (
                task.task_type is TaskType.BILL_PAYMENT
                and task.status is TaskStatus.COMPLETED
            ):
                when = task.updated_at
                if when:
                    paid_at = when.strftime("%Y-%m-%d %H:%M")
                break
        return {
            "id": b["id"],
            "type": b["type"],
            "amount": _yuan(b["amount_cents"]),
            "company": b["company"],
            "accountTail": b["account_tail"],
            "month": b["month"],
            "paidAt": paid_at,
        }

    # ---- 语音会话 -----------------------------------------------------------

    @router.post("/voice/sessions")
    def open_voice_session(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """开一个真实会话；带了 `utterance` 就真的过一遍语义引擎。"""
        ctx = _ctx()
        now = datetime.now(UTC)
        # 字段名是 `session_id` 不是 `id`；`StrictModel` 是 extra="forbid"，
        # 传错一个键就直接 500，不会静默忽略。
        session = SessionState(
            session_id=f"sess-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_DEMO_ELDER,
            created_at=now,
            updated_at=now,
        )
        db.create_session(session)

        understood = None
        utterance = (body or {}).get("utterance")
        if utterance:
            reply = engine.handle(
                ctx, ChatRequest(session_id=session.session_id, text=str(utterance))
            )
            # `ChatResponse` 的字段是 `message` / `code` / `task_status`，没有 `reply`。
            understood = {
                "reply": reply.message,
                "code": str(reply.code),
                "taskId": reply.task_id,
                "taskStatus": str(reply.task_status) if reply.task_status else None,
                "taskType": (reply.data or {}).get("task_type"),
            }
        return {"id": session.session_id, "status": "listening", "understood": understood}

    # ---- 支付：准备 / 复述 / 执行 --------------------------------------------

    @router.post("/payments/prepare")
    def prepare_payment(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """建一件**真的**缴费事务，并把复述提示词一并给前端。

        风险取 HIGH：`TeachBackVerifier.requires_teach_back` 只在 `BILL_PAYMENT`
        且 risk >= 3 时要求复述——这正是这一版演示要展示的那条线。
        """
        ctx = _ctx()
        b = _WATER_BILL
        slots = {
            "bill_type": b["type"].replace("支付", ""),
            "amount_cents": b["amount_cents"],
            "company": b["company"],
            "account_tail": b["account_tail"],
            "month": b["month"],
        }
        now = datetime.now(UTC)
        task = TaskRecord(
            id=f"pay-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_DEMO_ELDER,
            task_type=TaskType.BILL_PAYMENT,
            status=TaskStatus.AWAITING_ELDER_CONFIRMATION,
            risk_level=RiskLevel.HIGH,
            slots=slots,
            semantic_key=f"bill:{b['id']}:{b['amount_cents']}",
            created_at=now,
            updated_at=now,
        )
        db.create_task(task)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_PREPARED,
            entity_id=task.id,
            payload={"amount_cents": b["amount_cents"], "company": b["company"]},
        )
        return {
            "id": task.id,
            "status": "awaiting_teach_back",
            "amount": _yuan(b["amount_cents"]),
            "prompt": TeachBackVerifier.build_prompt(TaskType.BILL_PAYMENT, slots),
        }

    @router.post("/payments/{payment_id}/teach-back")
    def teach_back(payment_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """真的核对老人念出来的金额。念错就停——这一条是整个产品的支点。"""
        ctx = _ctx()
        task = _task_or_404(ctx, payment_id)
        text = str((body or {}).get("text") or "")
        check = TeachBackVerifier.verify(task.task_type, task.slots, text, required=True)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_TEACH_BACK,
            entity_id=task.id,
            payload={
                "outcome": str(check.outcome),
                "expected": check.expected_display,
                "heard": check.heard_display,
            },
        )
        words = {
            TeachBackOutcome.VERIFIED: "念对了，可以继续。",
            TeachBackOutcome.MISMATCH: "听到的金额和账单上的不一样，先停下。",
            TeachBackOutcome.NOT_RESTATED: "没有听到您把金额念出来，请再说一遍。",
            TeachBackOutcome.NOT_REQUIRED: "这一件不需要复述。",
        }
        return {
            "ok": check.passed,
            "matched": check.passed,
            "outcome": str(check.outcome),
            "expected": check.expected_display,
            "heard": check.heard_display,
            "message": words.get(check.outcome, ""),
        }

    @router.post("/payments/{payment_id}/execute")
    def execute_payment(payment_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """推进这件事。

        **不会因为前端调了就直接扣钱。** 高风险缴费要家人点头，所以这里把状态推到
        「等家人确认」并写审计。前端拿到 `awaiting_family` 就该照实显示。
        """
        ctx = _ctx()
        task = _task_or_404(ctx, payment_id)
        if task.status is TaskStatus.COMPLETED:
            return {"ok": True, "status": "paid", "certificateId": task.id}

        # 复述必须先过：查这一件事的审计链里有没有一条 verified。
        events = db.list_audit(ctx.family_id, limit=200, entity_id=task.id)
        verified = any(
            e.event_type == _EV_TEACH_BACK
            and (e.payload or {}).get("outcome") == str(TeachBackOutcome.VERIFIED)
            for e in events
        )
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="还没有通过复述确认，不能继续。",
            )

        moved = task.model_copy(
            update={
                "status": TaskStatus.AWAITING_FAMILY_APPROVAL,
                "updated_at": datetime.now(UTC),
            }
        )
        db.update_task(moved)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_AWAITING_FAMILY,
            entity_id=task.id,
            payload={"amount_cents": task.slots.get("amount_cents")},
        )
        return {
            "ok": True,
            "status": "awaiting_family",
            "certificateId": task.id,
            "message": "已提交，等家里第二个人点头之后才会真的付。",
        }

    @router.post("/payments/{payment_id}/family-approve")
    def family_approve(payment_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """家人点头，这一笔才真的走完。

        没有这一步，链条就停在 `awaiting_family` 永远不动——凭证页会一直显示
        「等家人点头」，而演示里没有任何办法把它推完。那不是"安全"，那是断掉。

        **这是家人的动作，不是老人的。** 所以身份取家人，写进审计的也是家人的
        `actor_id`——凭证上「谁点的头」必须是真的。老人自己点不动这一步。
        """
        ctx = _ctx()
        task = _task_or_404(ctx, payment_id)
        if task.status is TaskStatus.COMPLETED:
            return {"ok": True, "status": "paid", "certificateId": task.id}
        if task.status is not TaskStatus.AWAITING_FAMILY_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="这一笔还没有走到等家人确认这一步。",
            )

        approver = db.auth_context_for_actor(_DEMO_FAMILY)
        if approver is None or approver.family_id != ctx.family_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="这个家庭还没有登记可以确认的家人。",
            )

        done = task.model_copy(
            update={"status": TaskStatus.COMPLETED, "updated_at": datetime.now(UTC)}
        )
        db.update_task(done)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=approver.actor_id,          # 家人，不是老人
            event_type=_EV_FAMILY_APPROVED,
            entity_id=task.id,
            payload={
                "amount_cents": task.slots.get("amount_cents"),
                "approved_by": approver.display_name,
            },
        )
        return {
            "ok": True,
            "status": "paid",
            "certificateId": task.id,
            "approvedBy": approver.display_name,
            "message": f"{approver.display_name}已确认，这一笔办好了。",
        }

    # ---- 记录 ---------------------------------------------------------------

    #: 事件类型 → 给人看的说法。
    #:
    #: 界面上不许出现 `app.payment.teach_back` 这种内部枚举——这一条是这个项目的
    #: 硬约束，而记录页是最容易漏的地方（它直接把流水铺开给老人看）。
    #: 认不出来的事件一律说「办了一件事」，不把原始字符串漏到屏幕上。
    #: 这张表是**查库查出来的**，不是读代码猜的。
    #:
    #: 我在这里连错两版：先写 `task.created` 这种点号命名，再改成 `task_completed`
    #: 这种小写下划线（那是从源码里 grep 到的字面量）。而库里真正存的是
    #: **全大写下划线** `TASK_CREATED` / `TEACH_BACK_VERIFIED`。
    #: 两版都「看起来正常」——记录页照样渲染，每一条都落到兜底的「办了一件事」，
    #: 八条里零条翻译对，而屏幕上完全看不出哪里不对。
    #: 最后是 `SELECT event_type, COUNT(*) FROM audit_events GROUP BY 1` 定的案。
    _WORDS: dict[str, tuple[str, str, str]] = {
        # 主引擎写的（大写，来自库里的实际取值）
        "TASK_CREATED": ("开始办一件事", "服务", "record_request"),
        "ELDER_CONFIRMED": ("您确认了", "支付", "record_confirm"),
        "TEACH_BACK_VERIFIED": ("复述核对通过", "支付", "record_confirm"),
        "FAMILY_APPROVAL_RECORDED": ("家人已点头", "支付", "record_family"),
        "FAMILY_APPROVED_AND_EXECUTED": ("家人同意后已办好", "支付", "record_water"),
        "NOTIFICATION_CREATED": ("发出一条通知", "服务", "record_request"),
        "DEMO_SEEDED": ("演示数据已就绪", "服务", "record_request"),
        "TASK_REJECTED": ("这件事被拒绝了", "支付", "record_confirm"),
        "APPROVAL_REQUIRED": ("等家人点头", "支付", "record_family"),
        "REMINDER_DUE": ("到点提醒", "健康", "record_confirm"),
        "REMINDER_ESCALATED": ("没人应答，已通知家人", "健康", "record_family"),
        # 本门面自己写的（小写点号，与上面刻意不同名，便于区分来源）
        "app.payment.prepared": ("发起申请", "支付", "record_request"),
        "app.payment.teach_back": ("复述确认", "支付", "record_confirm"),
        "app.payment.awaiting_family": ("等家人确认", "支付", "record_family"),
        "app.emergency.requested": ("紧急呼叫", "服务", "record_family"),
    }

    _OUTCOME_WORDS = {
        "verified": "念对了",
        "mismatch": "念的金额对不上，已停下",
        "not_restated": "没有把金额念出来",
        "not_required": "这一件不用复述",
    }

    @router.get("/records")
    def records(type: str | None = Query(default=None)) -> dict[str, Any]:
        """真实审计流水，翻成人话之后再给前端。"""
        ctx = _ctx()
        events = db.list_audit(ctx.family_id, limit=80)
        items = []
        for e in reversed(events):
            title, kind, icon = _WORDS.get(
                e.event_type, ("办了一件事", "服务", "record_request")
            )
            payload = e.payload or {}
            note = ""
            if e.event_type == "app.payment.teach_back":
                note = _OUTCOME_WORDS.get(str(payload.get("outcome")), "")
                if payload.get("heard") and payload.get("expected"):
                    note += f"（听到 {payload['heard']}，账单是 {payload['expected']}）"
            elif payload.get("amount_cents") is not None:
                note = f"金额 ¥{_yuan(int(payload['amount_cents']))}"
            when = e.created_at
            items.append(
                {
                    "id": e.id,
                    "title": title,
                    "note": note,
                    "kind": kind,
                    "icon": icon,
                    "time": when.strftime("%H:%M") if when else "",
                    "at": when.isoformat() if when else None,
                    "entityId": e.entity_id,
                }
            )
        if type and type not in {"全部", "all"}:
            items = [i for i in items if i["kind"] == type]
        return {"items": items, "total": len(items)}

    # ---- 凭证 ---------------------------------------------------------------

    @router.get("/payments/{payment_id}/certificate")
    def certificate(payment_id: str) -> dict[str, Any]:
        """一件事的**完整**审计链。

        `list_audit` 带 `entity_id` 走 SQL 过滤，拿到的是这一件事从头到尾的每一步，
        而不是最近 200 条里恰好属于它的那几条。凭证的全部价值就是「每一步都在」。
        """
        ctx = _ctx()
        task = _task_or_404(ctx, payment_id)
        events = db.list_audit(ctx.family_id, limit=500, entity_id=payment_id)
        chain = [
            {
                "action": e.event_type,
                "at": e.created_at.isoformat() if e.created_at else None,
                "by": e.actor_id,
                "digest": (e.event_hash[:12] + "…") if e.event_hash else None,
            }
            for e in reversed(events)
        ]
        return {
            "id": payment_id,
            "amount": _yuan(int(task.slots.get("amount_cents", 0) or 0)),
            "company": task.slots.get("company"),
            "status": str(task.status),
            # 整条链是否没被动过——真的重算一遍哈希。
            "chainValid": db.verify_audit_chain(ctx.family_id),
            "chain": chain,
            # 稿子上的「凭证要素」：有真值的给真值，没有的给 null。
            # 界面上宁可少一格，也不摆一个编出来的位置或设备。
            "elements": {
                "voiceTeachBack": next(
                    (c["digest"] for c in chain if c["action"] == _EV_TEACH_BACK), None
                ),
                "location": None,
                "device": None,
                # 给人看的时刻，不是 ISO 原始串。
                # 界面上直接甩一个 `2026-08-16T18:09:04.118210+00:00` 出来，
                # 对一位老人等于没说。
                "time": (
                    datetime.fromisoformat(chain[-1]["at"]).strftime("%Y-%m-%d %H:%M:%S")
                    if chain and chain[-1]["at"]
                    else None
                ),
            },
        }

    # ---- 紧急呼叫 -----------------------------------------------------------

    @router.post("/emergency/call")
    def emergency_call(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """记一次真实的紧急呼叫。不会真的拨号——那要电话能力，这里只留证据。"""
        ctx = _ctx()
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_SOS,
            entity_id=f"sos-{uuid.uuid4().hex[:10]}",
            payload={"source": (body or {}).get("source", "elder-app")},
        )
        return {
            "ok": True,
            "status": "contacting",
            "message": "已记录这次呼叫，并按顺序联系紧急联系人。",
        }

    return router
