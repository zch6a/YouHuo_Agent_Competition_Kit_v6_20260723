from __future__ import annotations

from youhuo.models import ActorRole, FamilyApprovalRequest, ResponseCode, TaskStatus
from .helpers import confirm_bill, chat


def test_bill_requires_elder_then_family(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "帮我交水费")
    assert first.code == ResponseCode.NEED_ELDER_CONFIRMATION
    # Paying requires restating the amount, not a bare "确认办理".
    second = confirm_bill(engine, elder, session, first.message)
    assert second.code == ResponseCode.NEED_FAMILY_APPROVAL
    assert second.approval_digest
    final = engine.approve(
        family,
        FamilyApprovalRequest(task_id=second.task_id, approve=True, approval_digest=second.approval_digest),
    )
    assert final.code == ResponseCode.TASK_COMPLETED
    assert db.unpaid_bill("fam-demo", "水费") is None


def test_family_can_reject_payment(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交电费")
    pending = confirm_bill(engine, elder, session, asked.message)
    rejected = engine.approve(
        family,
        FamilyApprovalRequest(task_id=pending.task_id, approve=False, approval_digest=pending.approval_digest, reason="金额待核实"),
    )
    assert rejected.code == ResponseCode.TASK_CANCELLED
    assert db.unpaid_bill("fam-demo", "电费") is not None


def test_hospital_complete_flow(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "帮我挂明天下午两点第一医院骨科王医生的号")
    assert first.code == ResponseCode.NEED_ELDER_CONFIRMATION
    final = chat(engine, elder, session, "确认")
    assert final.code == ResponseCode.TASK_COMPLETED
    task = db.get_task(first.task_id)
    assert task and task.status == TaskStatus.COMPLETED
    assert task.result["appointment_id"].startswith("appt-")


def test_hospital_incremental_flow(env):
    db, engine, elder, family, session = env
    r1 = chat(engine, elder, session, "我膝盖疼，帮我挂号")
    assert "医院" in r1.message
    r2 = chat(engine, elder, session, "第一医院")
    assert "医生" in r2.message
    r3 = chat(engine, elder, session, "王医生")
    assert "日期" in r3.message
    r4 = chat(engine, elder, session, "明天")
    assert "时间" in r4.message
    r5 = chat(engine, elder, session, "下午两点")
    assert r5.code == ResponseCode.NEED_ELDER_CONFIRMATION
    r6 = chat(engine, elder, session, "确认办理")
    assert r6.code == ResponseCode.TASK_COMPLETED


def test_reminder_voice_flow(env):
    db, engine, elder, family, session = env
    r1 = chat(engine, elder, session, "提醒我明天上午九点复诊")
    assert r1.code == ResponseCode.NEED_ELDER_CONFIRMATION
    r2 = chat(engine, elder, session, "确认")
    assert r2.code == ResponseCode.TASK_COMPLETED
    reminders = db.list_reminders("fam-demo")
    assert len(reminders) == 1
    assert reminders[0].title == "复诊"


def test_form_assistance_never_bypasses_face_auth(env):
    db, engine, elder, family, session = env
    r1 = chat(engine, elder, session, "帮我完成人脸认证和填写选项")
    assert r1.code == ResponseCode.NEED_ELDER_CONFIRMATION
    r2 = chat(engine, elder, session, "确认办理")
    assert r2.code == ResponseCode.NEED_FAMILY_APPROVAL
    r3 = engine.approve(family, FamilyApprovalRequest(task_id=r2.task_id, approve=True, approval_digest=r2.approval_digest))
    assert r3.data["identity_bypass"] is False


def test_hospital_booking_creates_calendar_reminder(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "帮我挂明天下午两点第一医院骨科王医生的号")
    assert response.code.value == "need_elder_confirmation"
    final = chat(engine, elder, session, "确认办理")
    assert final.code.value == "task_completed"
    task = db.get_task(final.task_id)
    assert task.result["calendar_status"] == "created"
    assert task.result["calendar_reminder_id"]
    reminders = db.list_reminders("fam-demo")
    assert any(item.id == task.result["calendar_reminder_id"] for item in reminders)


def test_family_approval_notifies_elder(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    pending = confirm_bill(engine, elder, session, asked.message)
    result = engine.approve(
        family,
        FamilyApprovalRequest(
            task_id=pending.task_id,
            approve=True,
            approval_digest=pending.approval_digest,
        ),
    )
    assert result.code.value == "task_completed"
    notices = db.list_notifications("fam-demo", ActorRole.ELDER)
    assert any(item.event_type == "task_completed" for item in notices)
