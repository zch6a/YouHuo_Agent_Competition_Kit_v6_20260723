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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from .memory_vault import (
    MemoryItem,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)
from .security import SafetyPolicy
from .utils import semantic_hash
from .models import (
    AuthContext,
    ChatRequest,
    ReminderRecord,
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
#: 提醒与设置。**加一个事件类型就必须同时加一条 `_WORDS`**——否则记录页会
#: 落到兜底文案「办了一件事」，而那一行看起来完全正常，没有任何东西会报红。
_EV_REMINDER_CREATED = "app.reminder.created"
_EV_REMINDER_DONE = "app.reminder.completed"
_EV_REMINDER_CANCELLED = "app.reminder.cancelled"
_EV_SETTINGS_CHANGED = "app.settings.changed"


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
            # 取消掉的不在今天的安排里。
            #
            # 原来只把 COMPLETED / ACKNOWLEDGED 当成"办完了"，于是一条**已取消**的
            # 提醒既不算完成、也没被排除，照样进「今日安排」，还能被挑成「接下来」。
            # 实测的样子：在用药页取消「吃钙片」，那一条当场变成「已取消」，
            # 而首页顶上仍然写着「07:30 吃钙片」——同一条提醒，两个屏幕两种说法。
            if r.status is ReminderStatus.CANCELLED:
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

        # 槽位**从真实账单查询里来**，不在这里手工拼一份。
        #
        # 原来这里是手写的 5 个键，没有 `bill_id`。后果只在跨端时才显形：
        # 这一笔在旧家人端 `/v2/tasks` 里看得见（同一张任务表），女儿点「同意」，
        # 审批通过、状态推到 `executing`，**然后 `billing.settle` 抛 KeyError('bill_id')
        # 挂在半路**——一笔卡在「执行中」的钱，两端都显示不出它到底怎么了。
        #
        # `engine.py:725` 的写法就是 `task.slots.update(lookup.data)`。照它来，
        # 这一层才真的是门面而不是第二套业务——那正是这个文件开头写的话。
        # 查不到就退回本地那份演示账单：宁可少一个字段，也不要在这里编一个 bill_id
        # 让 `settle` 拿着去结一笔不存在的账。
        slots: dict[str, Any] = {
            "bill_type": b["type"].replace("支付", ""),
            "amount_cents": b["amount_cents"],
            "company": b["company"],
            "account_tail": b["account_tail"],
            "month": b["month"],
        }
        lookup = None
        try:
            lookup = engine.services.billing.lookup(db, ctx.family_id, slots["bill_type"])
        except Exception:  # noqa: BLE001 —— 查询挂了不该让老人点不动按钮
            lookup = None
        if lookup is not None and getattr(lookup, "ok", False) and lookup.data:
            slots.update(lookup.data)

        now = datetime.now(UTC)
        task = TaskRecord(
            id=f"pay-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_DEMO_ELDER,
            task_type=TaskType.BILL_PAYMENT,
            status=TaskStatus.AWAITING_ELDER_CONFIRMATION,
            risk_level=RiskLevel.HIGH,
            slots=slots,
            # 语义键跟着真实 bill_id 走，这样查重才和主引擎认的是同一件事。
            semantic_key=f"bill:{slots.get('bill_id') or b['id']}:{slots['amount_cents']}",
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
        if check.outcome is TeachBackOutcome.VERIFIED:
            # 复述核对通过，在语义上**就是**老人的确认——所以在这里就把
            # `elder_confirmed` 落进槽位，和 `engine.py:882` 那两行一致。
            #
            # 不落的后果只在跨端时显形：这一笔在旧家人端看得见、女儿点得动，
            # 审批还会返回 200——然后 `TaskVerifier.verify` 查
            # `slots["elder_confirmed"]` 查不到，判「缺少老人确认」，把任务打成
            # `failed`。老人**明明念对了**，链上也有 verified 那一条，
            # 却因为门面少写一个槽位，被判成没确认过。
            done = task.model_copy(update={"slots": {
                **task.slots,
                "elder_confirmed": True,
                "elder_confirmation_hash": semantic_hash(["elder-confirmation", text]),
            }})
            db.update_task(done)
            task = db.get_task(task.id) or done
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
                "approval_digest": None,
                "updated_at": datetime.now(UTC),
            }
        )
        db.update_task(moved)

        # 审批摘要。**这一段照 `engine.py:893-899` 的两步来，顺序不能换。**
        #
        # 实测发现的缺口：这一笔在旧家人端 `/v2/tasks` 里**看得见**（同一张任务表、
        # 同一个 `bill_payment`），但 `approval_digest` 是 null，而
        # `/v2/family/approve` 要求它是字符串——于是女儿在 `/family` 上点「同意」
        # 收到 422。两块屏幕看的是同一笔事务，却只有一块能推动它。
        #
        # 为什么必须先写、再读回来、再算：摘要要盖在**持久化之后**的任务上
        # （版本号已经 +1）。在内存里的副本上算，`engine.py:1046` 那次重算会对不上，
        # 审批当场被判成「摘要不符」——那是一条防篡改判据，不该被自己人绊倒。
        # 第二次写 `bump_version=False`，否则版本又变了，摘要再次失效。
        stored = db.get_task(task.id) or moved
        stored.approval_digest = SafetyPolicy.approval_digest(stored)
        db.update_task(stored, bump_version=False)

        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_AWAITING_FAMILY,
            entity_id=task.id,
            payload={"amount_cents": task.slots.get("amount_cents"),
                     "approval_digest": stored.approval_digest},
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
        "app.reminder.created": ("加了一条提醒", "健康", "record_confirm"),
        "app.reminder.completed": ("办好了一件事", "健康", "record_confirm"),
        "app.reminder.cancelled": ("取消了一条提醒", "健康", "record_confirm"),
        "app.settings.changed": ("改了设置", "服务", "record_request"),
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
        # 谁点的头。**两条路径都要认。**
        #
        # 这一笔可以由两个地方批准：山水版自己的 `/api/v1/.../family-approve`
        # （写 `FAMILY_APPROVED_AND_EXECUTED`，payload 里带 `approved_by`），
        # 或者旧家人端 `/family` 的「同意」按钮（走 `/v2/family/approve`，
        # 它把批准人写进 `slots["family_approver"]`）。实测两块屏幕看的是
        # **同一笔事务**，所以只认自己那条事件，就会在女儿从 `/family` 点头时
        # 把「谁点的头」显示成空——而凭证上这一格恰恰是最不能空的。
        approved_by = None
        for e in reversed(events):
            who = (e.payload or {}).get("approved_by")
            if who:
                approved_by = who
                break
        if approved_by is None:
            approver_id = task.slots.get("family_approver")
            if approver_id:
                row = db.actor(approver_id)
                approved_by = row["display_name"] if row else approver_id

        return {
            "id": payment_id,
            "amount": _yuan(int(task.slots.get("amount_cents", 0) or 0)),
            "company": task.slots.get("company"),
            "status": str(task.status),
            "approvedBy": approved_by,
            # 办完的时刻。没办完就是 null——不拿「现在」冒充「办好的时候」。
            "paidAt": (
                task.updated_at.strftime("%Y-%m-%d %H:%M")
                if task.status is TaskStatus.COMPLETED and task.updated_at
                else None
            ),
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

    # ---- 提醒：用药 / 就医 / 其他 -------------------------------------------
    #
    # `reminders` 表**没有类型字段**（只有 title / due_at / status / source），
    # 所以类别只能从标题认。这不是猜：`seed_demo_reminders` 写进去的就是
    # 「吃降压药」「心内科复诊」这种，语音引擎建的提醒也走同一批词。
    # 认不出来的一律归「其他」——不硬塞进某一类，否则界面上「用药提醒」里会
    # 冒出一件跟药无关的事，而那比少一条更糟。

    # 顺序有意义：先匹配到的先算。「复诊前准备病历」既有「复诊」也没有药，
    # 归就医；而「取药」两个词都沾，按这个顺序归用药——去医院取的还是药。
    _KIND_WORDS: dict[str, tuple[str, ...]] = {
        # 只写「药」不够：实测新建「吃钙片」被归成了「其他」——钙片、胶囊、
        # 维生素都是用药，却一个「药」字都没有。**不能只写「片」**，
        # 那会把「看照片」也算进来。所以逐个写完整词。
        "用药": ("药", "服药", "吃药", "钙片", "含片", "胶囊", "维生素",
                 "冲剂", "滴眼", "胰岛素", "降压", "降糖", "输液", "打针"),
        "就医": ("复诊", "门诊", "挂号", "看病", "医院", "体检", "检查", "取号"),
        "健康": ("量血压", "测血糖", "血压", "血糖", "体重", "散步", "锻炼", "运动"),
    }

    def _kind_of(title: str) -> str:
        for kind, words in _KIND_WORDS.items():
            if any(w in title for w in words):
                return kind
        return "其他"

    def _reminder_view(r: Any, now: datetime) -> dict[str, Any]:
        due = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=UTC)
        done = r.status in {ReminderStatus.COMPLETED, ReminderStatus.ACKNOWLEDGED}
        cancelled = r.status == ReminderStatus.CANCELLED
        return {
            "id": r.id,
            "title": r.title,
            "kind": _kind_of(r.title),
            "time": due.strftime("%H:%M"),
            "date": due.strftime("%m月%d日"),
            "at": due.isoformat(),
            "done": done,
            "cancelled": cancelled,
            # 界面上不出现英文枚举值——这里就把状态翻成人话，前端直接显示。
            "status": "已取消" if cancelled else ("已完成" if done else "待进行"),
            "overdue": (not done) and (not cancelled) and due < now,
        }

    def _my_reminders(ctx: AuthContext) -> list[Any]:
        return [
            r for r in db.list_reminders(ctx.family_id, limit=200)
            if r.elder_id == _DEMO_ELDER
        ]

    @router.get("/reminders")
    def reminders(kind: str | None = Query(default=None)) -> dict[str, Any]:
        """用药提醒 / 就医安排 / 今日事项 三个界面共用的真实数据源。

        `kind` 取「用药」「就医」「其他」，不传就是全部。传一个不认识的值回空表，
        不报错——界面上一个筛选按钮点出 500 比点出空列表糟得多。
        """
        ctx = _ctx()
        now = datetime.now(UTC)
        items = [_reminder_view(r, now) for r in _my_reminders(ctx)]
        if kind:
            items = [it for it in items if it["kind"] == kind]
        return {
            "items": items,
            "count": len(items),
            "kinds": sorted({it["kind"] for it in items}),
        }

    @router.post("/reminders")
    def create_reminder(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """老人自己加一条提醒。**真的写进提醒表**，不是回一个 ok 就算了。

        时间用 `HH:MM`（今天）或完整 ISO 串。给的时间已经过点就顺延到明天——
        对一位老人来说「设 8 点吃药」在 9 点设，意思显然是明天 8 点，
        而不是一条建出来就已经过期的提醒。
        """
        body = body or {}
        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="还没有说要提醒什么。")

        now = datetime.now(UTC)
        raw = str(body.get("at") or body.get("time") or "").strip()
        due = None
        if raw:
            try:
                if len(raw) <= 5 and ":" in raw:
                    hh, mm = (int(x) for x in raw.split(":", 1))
                    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if due < now:
                        due = due + timedelta(days=1)
                else:
                    due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="这个时间看不懂，请再说一遍。")
        if due is None:
            due = now + timedelta(hours=1)

        ctx = _ctx()
        record = ReminderRecord(
            id=f"rem-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_DEMO_ELDER,
            title=title,
            due_at=due,
            escalation_after_minutes=int(body.get("escalationAfterMinutes") or 30),
            status=ReminderStatus.SCHEDULED,
            source="elder-app",
            created_by=ctx.actor_id,
            created_at=now,
        )
        if not db.insert_reminder(record):
            raise HTTPException(status_code=409, detail="这一条没能存下来，请再试一次。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_CREATED,
            entity_id=record.id,
            payload={"title": title, "due_at": due.isoformat()},
        )
        return {"ok": True, "item": _reminder_view(record, now),
                "message": f"记好了，{due.strftime('%H:%M')} 提醒您{title}。"}

    @router.post("/reminders/{reminder_id}/done")
    def complete_reminder(reminder_id: str) -> dict[str, Any]:
        """办完了。写的是真状态，记录页当场就能看到这一条。"""
        ctx = _ctx()
        now = datetime.now(UTC)
        existing = db.get_reminder(reminder_id)
        if existing is None or existing.family_id != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这一条提醒。")
        if not db.update_reminder_status(
                reminder_id, ReminderStatus.COMPLETED, "completed_at", now):
            raise HTTPException(status_code=409, detail="这一条现在改不了。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_DONE,
            entity_id=reminder_id,
            payload={"title": existing.title},
        )
        return {"ok": True, "id": reminder_id, "status": "已完成",
                "message": f"好的，{existing.title}已经记成办好了。"}

    @router.post("/reminders/{reminder_id}/cancel")
    def cancel_reminder(reminder_id: str) -> dict[str, Any]:
        ctx = _ctx()
        existing = db.get_reminder(reminder_id)
        if existing is None or existing.family_id != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这一条提醒。")
        if not db.cancel_reminder(reminder_id, ctx.family_id, _DEMO_ELDER):
            raise HTTPException(status_code=409, detail="这一条现在取消不了。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_CANCELLED,
            entity_id=reminder_id,
            payload={"title": existing.title},
        )
        return {"ok": True, "id": reminder_id, "status": "已取消",
                "message": f"已经把「{existing.title}」取消了。"}

    # ---- 紧急联系人 ----------------------------------------------------------

    #: 家庭角色 → 界面上的称呼。库里的 `role` 只有 elder/family/system 三个值，
    #: 而屏幕上不许出现英文枚举值。`display_name` 本身就是「女儿」「儿子」，
    #: 所以称呼直接用它，这张表只兜底 role。
    _ROLE_WORDS = {"family": "家人", "system": "系统", "elder": "本人"}

    @router.get("/contacts")
    def contacts() -> dict[str, Any]:
        """紧急联系人。真的读家庭成员表，不是三行写死的卡片。

        **没有电话号码这个字段。** `actors` 表只有 id / family_id / role /
        display_name。所以这里回 `phone: null`，由界面决定怎么显示——
        编一个号码出来，老人真按下去会拨错人。
        """
        ctx = _ctx()
        people = []
        for row in db.list_actors(ctx.family_id):
            if row["id"] == _DEMO_ELDER:
                continue
            people.append({
                "id": row["id"],
                "name": row["display_name"],
                "role": _ROLE_WORDS.get(row["role"], "家人"),
                "phone": None,
                "primary": row["id"] == _DEMO_FAMILY,
            })
        return {"items": people, "count": len(people)}

    # ---- 设置：字号与语音 ----------------------------------------------------
    #
    # 存在 `memory_items` 里，`sensitivity='preference'`。这不是借地方放东西：
    # 那张表的枚举里本来就有 `preference`，而「记住老人的偏好、并且可撤回」
    # 正是这个产品的同意记忆机制。设置项走它，等于自动获得撤回与审计。

    _PREF_KEY = "elder_app_settings"
    _PREF_DEFAULTS = {"fontScale": 1.0, "voiceSpeed": 1.0, "highContrast": False}

    def _pref_item(ctx: AuthContext):
        for item in db.list_memories(ctx.family_id, _DEMO_ELDER):
            if item.key == _PREF_KEY and item.status != MemoryStatus.REVOKED:
                return item
        return None

    @router.get("/settings")
    def get_settings() -> dict[str, Any]:
        ctx = _ctx()
        item = _pref_item(ctx)
        values = dict(_PREF_DEFAULTS)
        if item is not None and isinstance(item.value, dict):
            values.update(item.value)
        return {**values, "saved": item is not None}

    @router.put("/settings")
    def put_settings(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """改字号 / 语速。**真的存下来**，换一页、重开都还在。"""
        body = body or {}
        ctx = _ctx()
        now = datetime.now(UTC)
        values = dict(_PREF_DEFAULTS)
        item = _pref_item(ctx)
        if item is not None and isinstance(item.value, dict):
            values.update(item.value)
        for key, cast in (("fontScale", float), ("voiceSpeed", float),
                          ("highContrast", bool)):
            if key in body:
                try:
                    values[key] = cast(body[key])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{key} 这个值看不懂。")
        # 字号夹在能用的范围里。前端滑到 3 倍会让整屏只剩两个字。
        values["fontScale"] = min(max(float(values["fontScale"]), 0.9), 1.6)
        values["voiceSpeed"] = min(max(float(values["voiceSpeed"]), 0.6), 1.6)

        if item is None:
            item = MemoryItem(
                id=f"mem-{uuid.uuid4().hex[:12]}",
                family_id=ctx.family_id,
                elder_id=_DEMO_ELDER,
                key=_PREF_KEY,
                value=values,
                sensitivity=MemorySensitivity.PREFERENCE,
                scope=MemoryScope.PRIVATE,
                purpose="记住这位老人的字号与语音偏好，用于渲染界面与朗读。",
                status=MemoryStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=3650),
                consent_actor_id=ctx.actor_id,
            )
            db.create_memory(item)
        else:
            db.update_memory(item.model_copy(update={"value": values, "updated_at": now}))
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_SETTINGS_CHANGED,
            entity_id=_PREF_KEY,
            payload=values,
        )
        return {**values, "saved": True, "message": "设置已经记住了。"}

    # ---- 通知 ---------------------------------------------------------------

    @router.get("/notifications")
    def notifications() -> dict[str, Any]:
        """给老人看的通知。读真表，取不到就是空表，不编。"""
        ctx = _ctx()
        items = []
        try:
            from .models import ActorRole
            rows = db.list_notifications(ctx.family_id, ActorRole.ELDER, 50)
        except Exception:
            rows = []
        for n in rows:
            created = getattr(n, "created_at", None)
            items.append({
                "id": getattr(n, "id", None),
                "title": getattr(n, "title", None) or getattr(n, "body", ""),
                "body": getattr(n, "body", None),
                "at": created.isoformat() if created else None,
                "time": created.strftime("%m月%d日 %H:%M") if created else None,
            })
        return {"items": items, "count": len(items)}

    return router
