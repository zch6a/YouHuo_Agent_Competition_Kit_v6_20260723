from __future__ import annotations

from datetime import UTC, datetime

import pytest

from youhuo.models import RiskLevel, TaskRecord, TaskStatus, TaskType
from youhuo.orchestration import (
    ConversationTaskInterleaver,
    DelegationPolicy,
    TaskPlanner,
    TaskVerifier,
    VerificationEvidence,
)


@pytest.mark.parametrize("task_type", list(TaskType))
def test_task_graph_is_valid_dag(task_type):
    graph = TaskPlanner.plan(task_type)
    ids = [node.id for node in graph.nodes]
    assert len(ids) == len(set(ids))
    assert graph.terminal_node == ids[-1]
    known: set[str] = set()
    for node in graph.nodes:
        assert set(node.depends_on).issubset(known)
        known.add(node.id)
    assert len(graph.graph_digest) == 64


@pytest.mark.parametrize("task_type", list(TaskType))
def test_task_graph_digest_is_deterministic(task_type):
    assert TaskPlanner.plan(task_type).graph_digest == TaskPlanner.plan(task_type).graph_digest


def test_next_nodes_respects_dependencies():
    graph = TaskPlanner.plan(TaskType.REMINDER)
    assert [n.id for n in TaskPlanner.next_nodes(graph, [])] == ["collect"]
    assert [n.id for n in TaskPlanner.next_nodes(graph, ["collect"])] == ["review"]


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (RiskLevel.INFORMATION, "autonomous_information"),
        (RiskLevel.LOW, "assisted"),
        (RiskLevel.SENSITIVE, "elder_confirmed"),
        (RiskLevel.HIGH, "family_handoff"),
    ],
)
def test_delegation_levels(risk, expected):
    result = DelegationPolicy.decide(TaskType.REMINDER, risk, tool_is_reversible=True)
    assert result.autonomy_level == expected


def test_delegation_high_amount_uses_quorum():
    result = DelegationPolicy.decide(TaskType.BILL_PAYMENT, RiskLevel.HIGH, amount_cents=12_650)
    assert result.family_approvals_required == 2
    assert result.autonomy_level == "family_quorum"


def test_delegation_ambiguity_requires_preview():
    result = DelegationPolicy.decide(TaskType.HOSPITAL_REGISTRATION, RiskLevel.SENSITIVE, ambiguity=0.5)
    assert result.dry_run_required and result.elder_confirmation_required
    assert any("歧义" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    ("text", "mixed", "task_fragment", "social_fragment"),
    [
        ("优活，帮我交水费，对了我孙子昨天来电话了", True, "水费", "孙子"),
        ("请提醒我明天下午吃药", False, "提醒", None),
        ("我孙女最近回来了", False, "我孙女", None),
        ("挂号；另外天气真好", True, "挂号", "天气"),
    ],
)
def test_interleaving(text, mixed, task_fragment, social_fragment):
    result = ConversationTaskInterleaver.split(text)
    assert result.mixed_intent is mixed
    assert task_fragment in result.primary_task_text
    if social_fragment:
        assert any(social_fragment in item for item in result.deferred_social_text)


def make_task(task_type: TaskType, risk: RiskLevel, slots=None):
    now = datetime(2026, 7, 23, tzinfo=UTC)
    return TaskRecord(
        id="task-x",
        family_id="fam-demo",
        elder_id="elder-demo",
        task_type=task_type,
        status=TaskStatus.EXECUTING,
        risk_level=risk,
        slots=slots or {},
        semantic_key="key",
        created_at=now,
        updated_at=now,
    )


def test_verifier_accepts_appointment_evidence():
    task = make_task(TaskType.HOSPITAL_REGISTRATION, RiskLevel.SENSITIVE)
    report = TaskVerifier.verify(
        task,
        VerificationEvidence(
            tool_code="BOOKED",
            tool_ok=True,
            observed_state={"appointment_id": "appt-1", "doctor": "王医生"},
            requested_state={"doctor": "王医生"},
        ),
    )
    assert report.accepted and len(report.proof_digest) == 64


def test_verifier_rejects_claim_without_state():
    task = make_task(TaskType.REMINDER, RiskLevel.LOW)
    report = TaskVerifier.verify(
        task,
        VerificationEvidence(tool_code="OK", tool_ok=True, observed_state={}, requested_state={}),
    )
    assert not report.accepted
    assert any("完成证据" in v for v in report.violations)


def test_verifier_rejects_state_mismatch():
    task = make_task(TaskType.HOSPITAL_REGISTRATION, RiskLevel.SENSITIVE)
    report = TaskVerifier.verify(
        task,
        VerificationEvidence(
            tool_code="BOOKED",
            tool_ok=True,
            observed_state={"appointment_id": "a", "doctor": "李医生"},
            requested_state={"doctor": "王医生"},
        ),
    )
    assert not report.accepted and "状态不一致：doctor" in report.violations


def test_verifier_requires_high_risk_confirmations():
    task = make_task(TaskType.BILL_PAYMENT, RiskLevel.HIGH, {"bill_id": "b"})
    report = TaskVerifier.verify(
        task,
        VerificationEvidence(tool_code="PAID", tool_ok=True, observed_state={"bill_id": "b"}),
    )
    assert not report.accepted
    assert "缺少老人确认" in report.violations and "缺少家属批准" in report.violations


def test_verifier_rejects_identity_bypass():
    task = make_task(TaskType.FORM_ASSISTANCE, RiskLevel.SENSITIVE)
    report = TaskVerifier.verify(
        task,
        VerificationEvidence(
            tool_code="FORM", tool_ok=True, observed_state={"identity_bypass": True}
        ),
    )
    assert not report.accepted
