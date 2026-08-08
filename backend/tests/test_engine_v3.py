from __future__ import annotations

from youhuo.models import ChatRequest, FamilyApprovalRequest, ResponseCode, TaskStatus

from .helpers import confirm_bill, chat


def test_mixed_input_stores_task_graph_and_deferred_topic(env):
    db, engine, elder, _, session = env
    response = chat(engine, elder, session, "帮我交水费，对了我孙子昨天来电话了")
    task = db.get_task(response.task_id)
    assert task is not None
    assert len(task.slots["task_graph_digest"]) == 64
    assert any("孙子" in topic for topic in task.deferred_topics)


def test_completed_reminder_contains_verification_proof(env):
    db, engine, elder, _, session = env
    first = chat(engine, elder, session, "提醒我明天下午3点吃药")
    done = chat(engine, elder, session, "确认办理")
    assert first.code == ResponseCode.NEED_ELDER_CONFIRMATION
    assert done.code == ResponseCode.TASK_COMPLETED
    task = db.get_task(done.task_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.result["verification"]["accepted"] is True
    assert len(task.result["verification"]["proof_digest"]) == 64


def test_high_amount_bill_requires_two_family_approvals(env):
    db, engine, elder, daughter, session = env
    son = db.auth_context_for_actor("son-demo")
    assert son is not None
    start = chat(engine, elder, session, "帮我交电费")
    assert start.code == ResponseCode.NEED_ELDER_CONFIRMATION
    waiting = confirm_bill(engine, elder, session, start.message)
    assert waiting.data["required_family_approvals"] == 2
    first = engine.approve(
        daughter,
        FamilyApprovalRequest(task_id=waiting.task_id, approve=True, approval_digest=waiting.approval_digest),
    )
    assert first.code == ResponseCode.NEED_FAMILY_APPROVAL
    assert first.data == {"approval_count": 1, "required_approvals": 2}
    second = engine.approve(
        son,
        FamilyApprovalRequest(task_id=waiting.task_id, approve=True, approval_digest=waiting.approval_digest),
    )
    assert second.code == ResponseCode.TASK_COMPLETED
    assert db.count_approval_votes(waiting.task_id) == 2


def test_same_family_member_cannot_fill_two_quorum_votes(env):
    _, engine, elder, daughter, session = env
    asked = chat(engine, elder, session, "帮我交电费")
    waiting = confirm_bill(engine, elder, session, asked.message)
    first = engine.approve(
        daughter,
        FamilyApprovalRequest(task_id=waiting.task_id, approve=True, approval_digest=waiting.approval_digest),
    )
    again = engine.approve(
        daughter,
        FamilyApprovalRequest(
            task_id=waiting.task_id,
            approve=True,
            approval_digest=waiting.approval_digest,
            request_id="different-request",
        ),
    )
    assert first.code == ResponseCode.NEED_FAMILY_APPROVAL
    assert again.code == ResponseCode.NEED_FAMILY_APPROVAL
    assert "已经确认过" in again.message
