from __future__ import annotations

import re
from typing import Any

from .models import AuditEvent, ElderActivityEntry, TaskRecord, TaskType, TaskView
from .utils import normalize_text


_PHONE = re.compile(r"(?<!\d)1[3-9]\d(?:[ -]?\d){8}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)")
_BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_CODE = re.compile(r"(?<!\d)\d(?:[ -]?\d){3,7}(?!\d)")
_SECRET_KEYS = {
    "password", "passwd", "pwd", "密码", "验证码", "校验码",
    "token", "access_token", "refresh_token", "api_key", "apikey",
    "secret", "client_secret", "identity_token", "face_template_digest",
}


def redact_text(text: str) -> str:
    value = _PHONE.sub("[手机号已脱敏]", text)
    value = _ID_CARD.sub("[身份证号已脱敏]", value)
    value = _BANK_CARD.sub("[银行卡号已脱敏]", value)
    # Only redact standalone verification-like codes when context implies a code.
    if any(word in value for word in ("验证码", "校验码", "短信码")):
        value = _CODE.sub("[验证码已脱敏]", value)
    return value


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            rendered = str(key)
            canonical = normalize_text(rendered).replace("-", "_").replace(" ", "_")
            result[rendered] = "[已隐藏]" if canonical in _SECRET_KEYS else redact_payload(item)
        return result
    if isinstance(value, list):
        return [redact_payload(v) for v in value]
    if isinstance(value, tuple):
        return [redact_payload(v) for v in value]
    return value


# Allow-list of audit events the elder may read, with the plain-language wording
# used on the elder home page. Anything absent here (scheduler ticks, semantic
# frames, per-turn cognitive plans, internal digests) is omitted rather than
# shown with a raw event name.
_ELDER_ACTIVITY_LABELS: dict[str, tuple[str, str]] = {
    "TASK_CREATED": ("优活", "task"),
    "ELDER_CONFIRMED": ("您", "task"),
    "TASK_EXECUTED": ("优活", "task"),
    "TASK_FAILED": ("优活", "task"),
    "TASK_CANCELLED": ("您", "task"),
    "FAMILY_APPROVAL_RECORDED": ("家人", "task"),
    "FAMILY_APPROVED_AND_EXECUTED": ("家人", "task"),
    "FAMILY_APPROVED_EXECUTION_FAILED": ("家人", "task"),
    "FAMILY_REJECTED": ("家人", "task"),
    "FAMILY_REMINDER_CREATED": ("家人", "reminder"),
    "REMINDER_ACKNOWLEDGE": ("您", "reminder"),
    "REMINDER_COMPLETE": ("您", "reminder"),
    "REMINDER_CANCELLED": ("您", "reminder"),
    "MODE_SWITCHED": ("您", "mode"),
    "EMOTIONAL_TASK_PAUSE": ("优活", "safety"),
    "SAFETY_SIGNAL": ("优活", "safety"),
    "SUSPICIOUS_INSTRUCTION_BLOCKED": ("优活", "safety"),
    # RELIANCE_CARD_CREATED and SAFE_ACTION_PREVIEWED are deliberately absent.
    # They fire automatically on every confirmation turn and the card is already
    # on screen, so logging them again crowded out the entries that describe
    # what was actually done. The family audit chain still records them in full.
    "DOCUMENT_ANALYZED": ("优活", "trust"),
    "INTERACTION_PROFILE_UPDATED": ("您", "profile"),
    # Care *queries* stay out: the log records what was done to the elder, and a
    # read-only question changed nothing. The two profile writes below did.
    "CARE_PROFILE_SPEECH_RATE": ("您", "profile"),
    "CARE_PROFILE_HEARING_SUPPORT": ("您", "profile"),
    "MEMORY_APPROVED": ("您", "privacy"),
    "MEMORY_REJECTED": ("您", "privacy"),
    "MEMORY_REVOKED": ("您", "privacy"),
}

_ELDER_ACTIVITY_TEXT: dict[str, str] = {
    "TASK_CREATED": "开始为您办理一件事。",
    "ELDER_CONFIRMED": "您复述并确认了这件事。",
    "TASK_EXECUTED": "事情已经办好，并核对过对方系统的状态。",
    "TASK_FAILED": "没有办成，已经安全停下，没有产生实际操作。",
    "TASK_CANCELLED": "您取消了这件事。",
    "FAMILY_APPROVAL_RECORDED": "家人确认了一次，还在等其他家人。",
    "FAMILY_APPROVED_AND_EXECUTED": "家人确认后已经办好。",
    "FAMILY_APPROVED_EXECUTION_FAILED": "家人确认了，但对方系统没有成功，已安全停下。",
    "FAMILY_REJECTED": "家人这次没有同意，已经取消。",
    "FAMILY_REMINDER_CREATED": "家人给您新增了一条待办。",
    "REMINDER_ACKNOWLEDGE": "您回应了一条待办提醒。",
    "REMINDER_COMPLETE": "您把一条待办标记成已完成。",
    "REMINDER_CANCELLED": "您取消了一条待办提醒。",
    "MODE_SWITCHED": "切换了优活办事和无忧伴陪伴模式。",
    "EMOTIONAL_TASK_PAUSE": "先陪您说说话，原来的事情已经安全暂停。",
    "SAFETY_SIGNAL": "识别到需要注意的情况，进入了安全提示。",
    "SUSPICIOUS_INSTRUCTION_BLOCKED": "拦下了一句想跳过确认的话，没有执行。",
    "DOCUMENT_ANALYZED": "检查了一份上传的单据，只作参考不直接采用。",
    "INTERACTION_PROFILE_UPDATED": "更新了您的语速和字号习惯。",
    "CARE_PROFILE_SPEECH_RATE": "您让优活调整了说话速度。",
    "CARE_PROFILE_HEARING_SUPPORT": "您打开了听力辅助：句子更短、语速更慢。",
    "MEMORY_APPROVED": "您同意优活记住一条信息。",
    "MEMORY_REJECTED": "您拒绝了一条记忆请求。",
    "MEMORY_REVOKED": "您撤销了一条已记住的信息。",
}


def elder_activity_entries(
    events: list[AuditEvent],
    *,
    entity_belongs_to_elder,
    elder_id: str,
) -> list[ElderActivityEntry]:
    """Project audit events into an elder-readable log, newest first.

    `entity_belongs_to_elder(entity_id)` resolves whether a task/reminder id is
    the elder's own; it returns None when the id is not an ownable entity, in
    which case the event is kept only if the elder is the actor.
    """
    entries: list[ElderActivityEntry] = []
    for event in events:
        label = _ELDER_ACTIVITY_LABELS.get(event.event_type)
        if label is None:
            continue
        owned = entity_belongs_to_elder(event.entity_id)
        if owned is False:
            continue
        if owned is None and event.actor_id != elder_id:
            continue
        who, kind = label
        entries.append(
            ElderActivityEntry(
                id=event.id,
                happened_at=event.created_at,
                who=who,
                what=_ELDER_ACTIVITY_TEXT[event.event_type],
                kind=kind,
                about_id=event.entity_id,
            )
        )
    entries.sort(key=lambda item: item.id, reverse=True)
    # Collapse runs of the same line: a retried turn should read as one event,
    # not as the same sentence repeated down the page.
    #
    # `about_id` 也要参与比较。少了它，**两笔不同的事务**只要产生同一句话就会被
    # 合并成一行——`_ELDER_ACTIVITY_TEXT` 是每个事件类型一句固定的话，所以连着
    # 办两次缴费，第二笔会安静地消失。原先这个字段还没有，所以看不出来；
    # 现在它在了，这一行就该修。
    #
    # `None` 参与比较是对的：两条都取不到主体时，它们确实无法区分，
    # 折叠成一条比显示两条一样的话更好。
    deduped: list[ElderActivityEntry] = []
    for entry in entries:
        if (deduped and deduped[-1].what == entry.what
                and deduped[-1].who == entry.who
                and deduped[-1].about_id == entry.about_id):
            continue
        deduped.append(entry)
    return deduped


def task_view(task: TaskRecord) -> TaskView:
    """Create an allow-listed client view without companion/deferred content."""
    slots = task.slots
    details: dict[str, Any] = {}
    if task.task_type == TaskType.BILL_PAYMENT:
        details = {
            "bill_type": slots.get("bill_type"),
            "period": slots.get("period"),
            "amount_yuan": f"{int(slots.get('amount_cents', 0)) / 100:.2f}" if slots.get("amount_cents") is not None else None,
            "due_date": slots.get("due_date"),
        }
        summary = (
            f"{details.get('period') or ''}{details.get('bill_type') or '生活账单'} "
            f"{details.get('amount_yuan') or '--'}元"
        ).strip()
    elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
        details = {
            "hospital": slots.get("hospital"),
            "department": slots.get("department"),
            "doctor": slots.get("doctor"),
            "appointment_date": slots.get("appointment_date"),
            "appointment_time": slots.get("appointment_time"),
        }
        summary = " ".join(str(v) for v in details.values() if v) or "医院挂号"
    elif task.task_type == TaskType.REMINDER:
        details = {
            "title": slots.get("title"),
            "due_date": slots.get("due_date"),
            "due_time": slots.get("due_time"),
        }
        summary = f"{details.get('due_date') or ''} {details.get('due_time') or ''} {details.get('title') or '待办提醒'}".strip()
    else:
        details = {
            "goal": redact_text(str(slots.get("form_goal", "逐项语音辅助填写"))),
            "requires_identity_guidance": bool(slots.get("face_verification")),
            "contains_sensitive_form": bool(slots.get("sensitive_form")),
        }
        summary = "逐项语音辅助填写"
    details = {key: redact_payload(value) for key, value in details.items() if value is not None}
    public_result = redact_payload(task.result)
    # Never expose arbitrary free-form/internal result fields to clients.
    if task.task_type == TaskType.BILL_PAYMENT:
        allowed_result = {k: public_result[k] for k in ("bill_id",) if isinstance(public_result, dict) and k in public_result}
    elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
        allowed_result = {
            k: public_result[k]
            for k in ("appointment_id", "calendar_reminder_id", "calendar_status")
            if isinstance(public_result, dict) and k in public_result
        }
    elif task.task_type == TaskType.REMINDER:
        allowed_result = {k: public_result[k] for k in ("reminder_id", "due_at") if isinstance(public_result, dict) and k in public_result}
    else:
        allowed_result = {k: public_result[k] for k in ("guidance", "identity_bypass") if isinstance(public_result, dict) and k in public_result}
    return TaskView(
        id=task.id,
        elder_id=task.elder_id,
        task_type=task.task_type,
        status=task.status,
        risk_level=task.risk_level,
        summary=summary,
        approval_digest=task.approval_digest if task.status.value == "awaiting_family_approval" else None,
        details=details,
        result=allowed_result,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
