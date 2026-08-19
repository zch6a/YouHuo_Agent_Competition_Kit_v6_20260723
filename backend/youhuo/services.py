from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

from .database import Database
from .models import ActorRole, AuthContext, ReminderRecord, ReminderStatus, ToolResult
from .privacy import redact_text
from .security import SafetyPolicy
from .utils import combine_date_time, new_id


def _period_words(period: str) -> str:
    """`2026-07` → `7 月`。

    这句话会被念给一位视力在下降的老人听。`2026-07` 是给机器看的写法——
    `speech.js` 会把它读成什么不好说，而屏幕上它也是一串需要她自己翻译的字符。
    她关心的只是"哪个月"，而账单永远是当年的。

    认不出格式就原样返回：宁可露出原值，也不要把一个没预料到的字符串猜成某个月份。
    """
    parts = str(period or "").split("-")
    if len(parts) == 2 and parts[1].isdigit():
        return f"{int(parts[1])} 月"
    return str(period or "")


def _date_words(value: str) -> str:
    """`2026-07-28` → `7 月 28 日`。理由同 `_period_words`。"""
    parts = str(value or "").split("-")
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return f"{int(parts[1])} 月 {int(parts[2])} 日"
    return str(value or "")


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class AuthService:
    def __init__(self, clock: Clock, ttl: timedelta = timedelta(hours=8)) -> None:
        self.clock = clock
        self.ttl = ttl

    def login_demo(self, db: Database, actor_id: str) -> tuple[str, AuthContext, datetime]:
        actor = db.auth_context_for_actor(actor_id)
        if actor is None:
            raise ValueError("未知的演示账户。")
        now = self.clock.now()
        expires_at = now + self.ttl
        token = secrets.token_urlsafe(36)
        db.store_auth_token(token, actor.actor_id, now, expires_at)
        db.append_audit(actor.family_id, actor.actor_id, "DEMO_LOGIN", actor.actor_id, {"expires_at": expires_at.isoformat()})
        return token, actor, expires_at


class HospitalService:
    """Typed, deterministic hospital adapter used for the offline competition demo.

    The adapter mirrors the boundary of a real provider: only validated typed
    parameters reach the write method, and provider strings are never treated as
    executable instructions.
    """

    _catalog: dict[str, dict[str, dict[str, list[str]]]] = {
        "第一医院": {
            "骨科": {"王医生": ["09:00", "14:00"], "李医生": ["10:30", "15:30"]},
            "内科": {"陈医生": ["09:30", "14:30"], "赵医生": ["11:00", "16:00"]},
        },
        "第二医院": {
            "骨科": {"周医生": ["08:30", "13:30"], "孙医生": ["10:00", "15:00"]},
            "内科": {"吴医生": ["09:00", "14:00"], "郑医生": ["10:30", "15:30"]},
        },
    }

    _symptom_map: tuple[tuple[tuple[str, ...], str], ...] = (
        (("膝盖", "骨头", "腰疼", "腿疼", "扭伤", "关节"), "骨科"),
        (("咳嗽", "发烧", "头晕", "胃疼", "乏力"), "内科"),
    )

    def suggest_department(self, text: str) -> str | None:
        for words, department in self._symptom_map:
            if any(word in text for word in words):
                return department
        return None

    @property
    def hospitals(self) -> list[str]:
        return list(self._catalog)

    def departments(self, hospital: str) -> list[str]:
        return list(self._catalog.get(hospital, {}))

    def doctors(self, hospital: str, department: str) -> dict[str, list[str]]:
        return dict(self._catalog.get(hospital, {}).get(department, {}))

    def validate(self, slots: dict[str, Any], *, today: date) -> ToolResult:
        required = ["hospital", "department", "doctor", "appointment_date", "appointment_time"]
        missing = [name for name in required if not slots.get(name)]
        if missing:
            return ToolResult(ok=False, code="MISSING_FIELDS", data={"missing": missing}, user_message="挂号信息还不完整。")
        hospital = str(slots["hospital"])
        department = str(slots["department"])
        doctor = str(slots["doctor"])
        appointment_time = str(slots["appointment_time"])
        try:
            appointment_date = date.fromisoformat(str(slots["appointment_date"]))
        except ValueError:
            return ToolResult(ok=False, code="INVALID_DATE", user_message="就诊日期格式不正确。")
        if appointment_date < today:
            return ToolResult(ok=False, code="PAST_DATE", user_message="不能预约已经过去的日期。")
        if hospital not in self._catalog:
            return ToolResult(ok=False, code="UNKNOWN_HOSPITAL", user_message="暂未找到这家医院。")
        if department not in self._catalog[hospital]:
            return ToolResult(ok=False, code="UNKNOWN_DEPARTMENT", user_message="这家医院暂未提供该科室。")
        if doctor not in self._catalog[hospital][department]:
            return ToolResult(ok=False, code="UNKNOWN_DOCTOR", user_message="暂未找到这位医生。")
        if appointment_time not in self._catalog[hospital][department][doctor]:
            return ToolResult(ok=False, code="INVALID_SLOT", user_message="该医生在这个时间没有可用号源。")
        return ToolResult(ok=True, code="VALID", data={k: slots[k] for k in required}, user_message="挂号信息校验通过。")

    def book(self, db: Database, *, family_id: str, elder_id: str, slots: dict[str, Any], today: date) -> ToolResult:
        validation = self.validate(slots, today=today)
        if not validation.ok:
            return validation
        appointment_id = new_id("appt")
        ok = db.insert_appointment(
            {
                "id": appointment_id,
                "family_id": family_id,
                "elder_id": elder_id,
                "hospital": str(slots["hospital"]),
                "department": str(slots["department"]),
                "doctor": str(slots["doctor"]),
                "appointment_date": str(slots["appointment_date"]),
                "appointment_time": str(slots["appointment_time"]),
            }
        )
        if not ok:
            return ToolResult(ok=False, code="DUPLICATE_APPOINTMENT", user_message="这个时间的挂号已经存在，不需要重复办理。")
        return ToolResult(
            ok=True,
            code="BOOKED",
            data={"appointment_id": appointment_id, **validation.data},
            user_message=(
                f"已经挂好{slots['appointment_date']} {slots['appointment_time']}，"
                f"地点是{slots['hospital']}{slots['department']}{slots['doctor']}。"
            ),
        )


#: 账单类型 → 收费单位。`bills` 表**没有单位这一列**（只有
#: id/family_id/bill_type/period/amount_cents/due_date/paid/paid_at），
#: 而屏幕上要写「向谁交的钱」。这是演示数据的一部分，接真营业厅之后从查询里取。
#:
#: 放在这里而不是门面层，是因为**槽位是在这里填的**。原先这张表只存在于
#: `app_api.py` 的路由工厂里，后果是：`/api/v1/payments/prepare` 建的那一笔
#: 凭证上有收款方，而**语音建的那一笔没有**——`lookup()` 的 data 里没有这一项，
#: 而 `engine.py:725` 的 `task.slots.update(lookup.data)` 就是引擎填槽的全部来源。
#: 语音是这个产品的主路径，凭证上「向谁交的钱」那一格恰恰最不能空。
#: 实测（三条路径各办一笔）：种子 None、按钮 示例供电公司、语音 None。
BILL_COMPANY = {
    "水费": "示例自来水公司",
    "电费": "示例供电公司",
    "燃气费": "示例燃气公司",
}


class BillingService:
    def lookup(self, db: Database, family_id: str, bill_type: str) -> ToolResult:
        row = db.unpaid_bill(family_id, bill_type)
        if not row:
            # Distinguish "already settled" from "no such bill". Both mean there is
            # nothing to execute, but only the first is the design §1.2 duplicate
            # case, and neither may be reported to the elder as a completed task.
            settled = db.latest_paid_bill(family_id, bill_type)
            if settled:
                return ToolResult(
                    ok=False,
                    code="BILL_ALREADY_PAID",
                    data={"bill_id": settled["id"], "period": settled["period"]},
                    user_message=f"{settled['period']}的{bill_type}已经缴过了，这次不用再交。",
                )
            return ToolResult(ok=False, code="NO_UNPAID_BILL", user_message=f"没有查到未缴的{bill_type}。")
        amount = int(row["amount_cents"]) / 100
        return ToolResult(
            ok=True,
            code="UNPAID_BILL",
            data={
                "bill_id": row["id"],
                "bill_type": row["bill_type"],
                "period": row["period"],
                "amount_cents": row["amount_cents"],
                "due_date": row["due_date"],
                # 认不出来的类型就不写这一项：界面上宁可少一行，也不编一个单位。
                # 写 `""` 是错的——那会让「取到了，是空的」和「没取到」变成同一件事，
                # 而家人审批页对后者显示的是「还没有取到」。
                **({"company": BILL_COMPANY[row["bill_type"]]}
                   if row["bill_type"] in BILL_COMPANY else {}),
            },
            user_message=(
                f"查到{_period_words(row['period'])}的{row['bill_type']}是{amount:.2f}元，"
                f"截止日期是{_date_words(row['due_date'])}。"
            ),
        )

    def create_payment_request(self, slots: dict[str, Any], *, task_id: str) -> ToolResult:
        if not slots.get("bill_id") or slots.get("amount_cents") is None:
            return ToolResult(ok=False, code="MISSING_BILL", user_message="还没有选定账单。")
        payment_request_id = new_id("payreq")
        payload = "youhuo-demo://family-pay?" + urlencode(
            {
                "request_id": payment_request_id,
                "task_id": task_id,
                "bill_id": slots["bill_id"],
                "amount_cents": slots["amount_cents"],
            }
        )
        return ToolResult(
            ok=True,
            code="PAYMENT_REQUEST_CREATED",
            data={
                "payment_request_id": payment_request_id,
                "bill_id": slots["bill_id"],
                "amount_cents": slots["amount_cents"],
                "payment_payload": payload,
            },
            user_message="支付请求已经发给家人，优活不会自动扣款。",
        )

    def settle(self, db: Database, family_id: str, bill_id: str) -> ToolResult:
        if db.mark_bill_paid(family_id, bill_id):
            return ToolResult(ok=True, code="PAID", data={"bill_id": bill_id}, user_message="账单已经由家人确认支付。")
        return ToolResult(ok=False, code="ALREADY_PAID_OR_MISSING", user_message="账单可能已经支付，或者账单不存在。")


class ReminderService:
    def create(
        self,
        db: Database,
        *,
        family_id: str,
        elder_id: str,
        title: str,
        due_at: datetime,
        created_by: str,
        source: str,
        escalation_after_minutes: int = 30,
    ) -> ToolResult:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=UTC)
        record = ReminderRecord(
            id=new_id("rem"),
            family_id=family_id,
            elder_id=elder_id,
            title=title,
            due_at=due_at.astimezone(UTC),
            escalation_after_minutes=escalation_after_minutes,
            status=ReminderStatus.SCHEDULED,
            source=source,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        if not db.insert_reminder(record):
            return ToolResult(ok=False, code="REMINDER_CONFLICT", user_message="同一时间的同一提醒已经存在。")
        return ToolResult(
            ok=True,
            code="REMINDER_CREATED",
            data={"reminder_id": record.id, "title": record.title, "due_at": record.due_at.isoformat()},
            user_message=f"已经设置提醒：{title}，时间是{record.due_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M')}。",
        )

    def create_from_parts(
        self,
        db: Database,
        *,
        family_id: str,
        elder_id: str,
        title: str,
        due_date: str,
        due_time: str,
        created_by: str,
    ) -> ToolResult:
        # 老人说"明天上午九点"，说的是**他所在时区**的九点。
        #
        # 这里原先是 `.replace(tzinfo=UTC)`——把 09:00 这个墙上时间直接盖一个 UTC 标签，
        # 存进库的于是是 09:00Z，也就是北京时间 17:00。同一屏上聊天气泡说"时间是
        # 2026-08-11 09:00"，而待办卡渲染出来是"8月11日 17:00"：两处对同一件事说了两个
        # 时间。连带 due 判定、提前提醒的 24h/12h/1h 阶梯、超时升级，全部晚 8 小时触发。
        #
        # `combine_date_time` 现在返回带本地偏移的 ISO 串，解析出来就是 aware，
        # 只需换算到 UTC 存储。
        due_at = datetime.fromisoformat(combine_date_time(due_date, due_time)).astimezone(UTC)
        return self.create(
            db,
            family_id=family_id,
            elder_id=elder_id,
            title=title,
            due_at=due_at,
            created_by=created_by,
            source="elder_voice",
        )


class NotificationService:
    def send(
        self,
        db: Database,
        *,
        family_id: str,
        recipient_role: ActorRole,
        event_type: str,
        message: str,
        entity_id: str | None = None,
    ) -> ToolResult:
        safe = redact_text(SafetyPolicy.sanitize_untrusted_text(message))
        record = db.add_notification(family_id, recipient_role, event_type, safe, entity_id)
        db.append_audit(
            family_id,
            "system-demo" if family_id == "fam-demo" else "system",
            "NOTIFICATION_CREATED",
            entity_id,
            {"notification_id": record.id, "recipient_role": recipient_role.value, "event_type": event_type},
        )
        return ToolResult(
            ok=True,
            code="NOTIFIED",
            data={"notification_id": record.id},
            user_message="提醒已经发送。",
        )


class SchedulerService:
    """Deterministic proactive reminder and family-escalation loop.

    The design brief asks for an advance-notice ladder before the due time
    (T-24h, T-12h, T-1h) followed by the due-time reminder and, only if the elder
    never responds, a family relay request. Every rung is claimed exactly once in
    the database, so ticking more often never produces duplicate nagging.
    """

    #: Lead times in minutes, coarsest first. T-24h / T-12h / T-1h per design §5.3.
    ADVANCE_LEAD_MINUTES: tuple[int, ...] = (24 * 60, 12 * 60, 60)

    @staticmethod
    def _remaining_label(due_at: datetime, now: datetime) -> str:
        """Describe the real remaining time, not the rung that triggered the notice.

        The rung decides *when* to speak; if the scheduler runs late, or several
        rungs come due at once, naming the rung would tell the elder something
        false ("还有24小时" three hours before the appointment).
        """
        minutes = max(1, round((due_at - now).total_seconds() / 60))
        if minutes >= 120:
            return f"还有约{round(minutes / 60)}小时"
        if minutes >= 60:
            return "还有约1小时"
        return f"还有约{minutes}分钟"

    def _advance_notices(
        self,
        db: Database,
        notifications: NotificationService,
        now: datetime,
        *,
        family_id: str | None,
    ) -> int:
        """Fire advance rungs whose lead time has been reached but not yet sent.

        When several rungs come due at once - a device that was offline, or a
        reminder created inside the horizon - every passed rung is consumed but
        the elder hears a single notice describing the real remaining time.
        """
        horizon = max(self.ADVANCE_LEAD_MINUTES)
        sent = 0
        for reminder in db.upcoming_reminders(now, horizon, family_id=family_id):
            already = set(db.sent_advance_notices(reminder.id))
            reached = [
                lead
                for lead in self.ADVANCE_LEAD_MINUTES
                if lead not in already and now >= reminder.due_at - timedelta(minutes=lead)
            ]
            claimed = [lead for lead in reached if db.record_advance_notice(reminder.id, lead, now)]
            if not claimed:
                continue
            notifications.send(
                db,
                family_id=reminder.family_id,
                recipient_role=ActorRole.ELDER,
                event_type="reminder_advance_notice",
                entity_id=reminder.id,
                message=f"提前提醒：{self._remaining_label(reminder.due_at, now)}就到「{reminder.title}」了。",
            )
            sent += 1
        return sent

    def tick(
        self,
        db: Database,
        notifications: NotificationService,
        now: datetime,
        *,
        family_id: str | None = None,
    ) -> dict[str, int]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        notified = 0
        escalated = 0
        advance_notified = self._advance_notices(db, notifications, now, family_id=family_id)
        for reminder in db.due_reminders(now, family_id=family_id):
            if reminder.status == ReminderStatus.SCHEDULED:
                notifications.send(
                    db,
                    family_id=reminder.family_id,
                    recipient_role=ActorRole.ELDER,
                    event_type="reminder_due",
                    entity_id=reminder.id,
                    message=f"待办提醒：{reminder.title}。",
                )
                if db.update_reminder_status(reminder.id, ReminderStatus.NOTIFIED, "notified_at", now):
                    notified += 1
                continue
            if reminder.status == ReminderStatus.NOTIFIED:
                threshold = reminder.due_at + timedelta(minutes=reminder.escalation_after_minutes)
                if now >= threshold:
                    notifications.send(
                        db,
                        family_id=reminder.family_id,
                        recipient_role=ActorRole.FAMILY,
                        event_type="reminder_escalated",
                        entity_id=reminder.id,
                        message=f"老人待办「{reminder.title}」到期后仍未确认完成，请及时联系。",
                    )
                    if db.update_reminder_status(reminder.id, ReminderStatus.ESCALATED, "escalated_at", now):
                        escalated += 1
        return {"notified": notified, "escalated": escalated, "advance_notified": advance_notified}


@dataclass
class Services:
    clock: Clock
    auth: AuthService
    hospital: HospitalService
    billing: BillingService
    reminder: ReminderService
    notification: NotificationService
    scheduler: SchedulerService

    @classmethod
    def build(cls, clock: Clock | None = None) -> "Services":
        resolved = clock or SystemClock()
        return cls(
            clock=resolved,
            auth=AuthService(resolved),
            hospital=HospitalService(),
            billing=BillingService(),
            reminder=ReminderService(),
            notification=NotificationService(),
            scheduler=SchedulerService(),
        )
