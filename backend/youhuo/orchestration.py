from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from .models import RiskLevel, TaskRecord, TaskType
from .utils import canonical_json, clean_user_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeKind(StrEnum):
    COLLECT = "collect"
    CLARIFY = "clarify"
    REVIEW = "review"
    CONFIRM = "confirm"
    EXECUTE = "execute"
    VERIFY = "verify"
    NOTIFY = "notify"
    REMEMBER = "remember"


class GraphNode(StrictModel):
    id: str
    kind: NodeKind
    label: str
    depends_on: list[str] = Field(default_factory=list)
    required_slots: list[str] = Field(default_factory=list)
    risk_gate: RiskLevel = RiskLevel.INFORMATION
    tool_name: str | None = None
    human_role: str | None = None


class TaskGraph(StrictModel):
    task_type: TaskType
    version: str = "3.0"
    nodes: list[GraphNode]
    terminal_node: str
    graph_digest: str


class DelegationDecision(StrictModel):
    autonomy_level: str
    elder_confirmation_required: bool
    family_approvals_required: int
    dry_run_required: bool
    reversible_only: bool
    reasons: list[str]


class VerificationEvidence(StrictModel):
    tool_code: str
    tool_ok: bool
    observed_state: dict[str, Any] = Field(default_factory=dict)
    requested_state: dict[str, Any] = Field(default_factory=dict)
    side_effect_receipt: str | None = None


class VerificationReport(StrictModel):
    accepted: bool
    violations: list[str] = Field(default_factory=list)
    proof_digest: str
    user_safe_summary: str


class InterleavingResult(StrictModel):
    primary_task_text: str
    deferred_social_text: list[str] = Field(default_factory=list)
    mixed_intent: bool
    confidence: float = Field(ge=0, le=1)


class TaskPlanner:
    """Deterministic task graph generator.

    The graph is deliberately independent from any LLM. A language model may
    propose slot values, but it cannot remove confirmation, verification or
    notification gates from the authoritative graph.
    """

    _SPECS: dict[TaskType, list[GraphNode]] = {
        TaskType.HOSPITAL_REGISTRATION: [
            GraphNode(id="collect_symptom", kind=NodeKind.COLLECT, label="收集症状或科室偏好"),
            GraphNode(id="collect_hospital", kind=NodeKind.COLLECT, label="选择医院", depends_on=["collect_symptom"], required_slots=["hospital"]),
            GraphNode(id="collect_department", kind=NodeKind.COLLECT, label="选择科室", depends_on=["collect_hospital"], required_slots=["department"]),
            GraphNode(id="collect_schedule", kind=NodeKind.COLLECT, label="选择医生与时间", depends_on=["collect_department"], required_slots=["doctor", "appointment_date", "appointment_time"]),
            GraphNode(id="review", kind=NodeKind.REVIEW, label="逐项朗读预约摘要", depends_on=["collect_schedule"]),
            GraphNode(id="elder_confirm", kind=NodeKind.CONFIRM, label="老人确认", depends_on=["review"], risk_gate=RiskLevel.SENSITIVE, human_role="elder"),
            GraphNode(id="book", kind=NodeKind.EXECUTE, label="提交挂号", depends_on=["elder_confirm"], risk_gate=RiskLevel.SENSITIVE, tool_name="hospital.book"),
            GraphNode(id="verify", kind=NodeKind.VERIFY, label="核验预约回执与数据库状态", depends_on=["book"]),
            GraphNode(id="calendar", kind=NodeKind.EXECUTE, label="创建就诊提醒", depends_on=["verify"], tool_name="calendar.create"),
            GraphNode(id="notify", kind=NodeKind.NOTIFY, label="向老人播报并同步家属", depends_on=["calendar"]),
        ],
        TaskType.BILL_PAYMENT: [
            GraphNode(id="collect_bill", kind=NodeKind.COLLECT, label="识别账单", required_slots=["bill_type"]),
            GraphNode(id="query", kind=NodeKind.EXECUTE, label="查询账单与重复支付状态", depends_on=["collect_bill"], tool_name="billing.query"),
            GraphNode(id="review", kind=NodeKind.REVIEW, label="朗读账期、金额和截止日", depends_on=["query"]),
            GraphNode(id="elder_confirm", kind=NodeKind.CONFIRM, label="老人确认账单", depends_on=["review"], risk_gate=RiskLevel.HIGH, human_role="elder"),
            GraphNode(id="family_confirm", kind=NodeKind.CONFIRM, label="家属核对并支付", depends_on=["elder_confirm"], risk_gate=RiskLevel.HIGH, human_role="family"),
            GraphNode(id="settle", kind=NodeKind.EXECUTE, label="确认支付结果", depends_on=["family_confirm"], risk_gate=RiskLevel.HIGH, tool_name="billing.settle"),
            GraphNode(id="verify", kind=NodeKind.VERIFY, label="核验已支付状态、金额与回执", depends_on=["settle"]),
            GraphNode(id="notify", kind=NodeKind.NOTIFY, label="双端同步结果", depends_on=["verify"]),
        ],
        TaskType.REMINDER: [
            GraphNode(id="collect", kind=NodeKind.COLLECT, label="收集事项和时间", required_slots=["title", "due_date", "due_time"]),
            GraphNode(id="review", kind=NodeKind.REVIEW, label="朗读提醒摘要", depends_on=["collect"]),
            GraphNode(id="confirm", kind=NodeKind.CONFIRM, label="老人确认", depends_on=["review"], risk_gate=RiskLevel.LOW, human_role="elder"),
            GraphNode(id="create", kind=NodeKind.EXECUTE, label="创建提醒", depends_on=["confirm"], tool_name="calendar.create"),
            GraphNode(id="verify", kind=NodeKind.VERIFY, label="核验提醒已落库", depends_on=["create"]),
            GraphNode(id="notify", kind=NodeKind.NOTIFY, label="到期提醒与超时升级", depends_on=["verify"]),
        ],
        TaskType.FORM_ASSISTANCE: [
            GraphNode(id="collect", kind=NodeKind.COLLECT, label="识别表单目标与敏感字段"),
            GraphNode(id="review", kind=NodeKind.REVIEW, label="逐项解释将要填写的信息", depends_on=["collect"]),
            GraphNode(id="confirm", kind=NodeKind.CONFIRM, label="老人确认开始辅助", depends_on=["review"], risk_gate=RiskLevel.SENSITIVE, human_role="elder"),
            GraphNode(id="assist", kind=NodeKind.EXECUTE, label="逐项语音辅助", depends_on=["confirm"], tool_name="form.assist"),
            GraphNode(id="identity", kind=NodeKind.CONFIRM, label="本人完成验证码或人脸认证", depends_on=["assist"], risk_gate=RiskLevel.HIGH, human_role="elder"),
            GraphNode(id="verify", kind=NodeKind.VERIFY, label="核验未绕过身份认证", depends_on=["identity"]),
        ],
    }

    @classmethod
    def plan(cls, task_type: TaskType) -> TaskGraph:
        nodes = [node.model_copy(deep=True) for node in cls._SPECS[task_type]]
        payload = {"task_type": task_type.value, "nodes": [n.model_dump(mode="json") for n in nodes]}
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return TaskGraph(task_type=task_type, nodes=nodes, terminal_node=nodes[-1].id, graph_digest=digest)

    @classmethod
    def next_nodes(cls, graph: TaskGraph, completed: Iterable[str]) -> list[GraphNode]:
        done = set(completed)
        return [node for node in graph.nodes if node.id not in done and set(node.depends_on).issubset(done)]


class DelegationPolicy:
    """Compute a bounded autonomy envelope for a task.

    The output is an explanation-friendly policy decision, not a model guess.
    """

    @staticmethod
    def decide(
        task_type: TaskType,
        risk: RiskLevel,
        *,
        amount_cents: int = 0,
        ambiguity: float = 0.0,
        tool_is_reversible: bool = False,
    ) -> DelegationDecision:
        reasons: list[str] = []
        approvals = 0
        dry_run = risk >= RiskLevel.SENSITIVE
        elder = risk >= RiskLevel.LOW
        reversible_only = risk >= RiskLevel.SENSITIVE

        if risk >= RiskLevel.HIGH:
            approvals = 1
            reasons.append("资金或身份类任务必须由绑定家属接力")
        if amount_cents >= 10_000:
            approvals = max(approvals, 2)
            reasons.append("金额达到100元的演示双家属阈值")
        if ambiguity >= 0.35:
            elder = True
            dry_run = True
            reasons.append("需求存在歧义，必须先澄清并预览")
        if risk >= RiskLevel.SENSITIVE and not tool_is_reversible:
            reasons.append("不可逆操作需要执行前预览与执行后核验")
        if risk == RiskLevel.INFORMATION:
            level = "autonomous_information"
        elif task_type == TaskType.REMINDER and risk <= RiskLevel.LOW:
            level = "assisted"
        elif approvals >= 2:
            level = "family_quorum"
        elif approvals == 1:
            level = "family_handoff"
        elif elder:
            level = "elder_confirmed"
        else:
            level = "autonomous_information"
        if not reasons:
            reasons.append("任务处于低风险且可撤销范围")
        return DelegationDecision(
            autonomy_level=level,
            elder_confirmation_required=elder,
            family_approvals_required=approvals,
            dry_run_required=dry_run,
            reversible_only=reversible_only and not tool_is_reversible,
            reasons=reasons,
        )


class ConversationTaskInterleaver:
    """Split task-bearing clauses from social clauses without losing either.

    This is the executable form of the project's “刚性任务锁”: the system keeps
    the actionable clause in the foreground and stores social clauses for later.
    """

    _TASK_MARKERS = (
        "挂号", "医院", "医生", "水费", "电费", "燃气费", "缴费", "交费", "账单",
        "提醒", "日历", "待办", "填表", "填写", "认证", "验证码", "支付",
    )
    _SOCIAL_MARKERS = (
        "孙子", "孙女", "孩子", "昨天", "以前", "小时候", "最近", "聊天", "电视", "天气", "想念",
    )

    @classmethod
    def split(cls, text: str) -> InterleavingResult:
        normalized = clean_user_text(text, max_length=2000)
        clauses = [c.strip(" ，,。！？!?；;") for c in re.split(r"[。！？!?；;]|[，,](?=(?:哦|对了|还有|另外|顺便))", normalized) if c.strip()]
        task_parts: list[str] = []
        social_parts: list[str] = []
        unknown: list[str] = []
        for clause in clauses:
            has_task = any(marker in clause for marker in cls._TASK_MARKERS)
            has_social = any(marker in clause for marker in cls._SOCIAL_MARKERS)
            if has_task and not has_social:
                task_parts.append(clause)
            elif has_social and not has_task:
                social_parts.append(clause)
            elif has_task and has_social:
                # Keep the entire ambiguous clause in the task foreground; it is safer
                # than dropping actionable content. A copy is also deferred for recovery.
                task_parts.append(clause)
                social_parts.append(clause)
            else:
                unknown.append(clause)
        if not task_parts and unknown:
            task_parts.append(unknown.pop(0))
        social_parts.extend(unknown)
        primary = "，".join(task_parts) if task_parts else normalized
        mixed = bool(task_parts and social_parts)
        confidence = 0.95 if mixed else (0.82 if task_parts else 0.55)
        return InterleavingResult(
            primary_task_text=primary[:1000],
            deferred_social_text=[part[:240] for part in social_parts if part],
            mixed_intent=mixed,
            confidence=confidence,
        )


class TaskVerifier:
    """State/evidence verifier inspired by state-based agent benchmarks.

    A task is considered complete only when the authoritative state matches the
    requested state. Natural-language success claims are ignored.
    """

    _REQUIRED_RESULT_KEYS: dict[TaskType, set[str]] = {
        TaskType.HOSPITAL_REGISTRATION: {"appointment_id"},
        TaskType.BILL_PAYMENT: {"bill_id"},
        TaskType.REMINDER: {"reminder_id"},
        TaskType.FORM_ASSISTANCE: {"identity_bypass"},
    }

    @classmethod
    def verify(cls, task: TaskRecord, evidence: VerificationEvidence) -> VerificationReport:
        violations: list[str] = []
        if not evidence.tool_ok:
            violations.append("工具返回失败")
        required = cls._REQUIRED_RESULT_KEYS[task.task_type]
        missing = sorted(required.difference(evidence.observed_state))
        if missing:
            violations.append("缺少完成证据：" + "、".join(missing))
        for key, requested in evidence.requested_state.items():
            if key in evidence.observed_state and evidence.observed_state[key] != requested:
                violations.append(f"状态不一致：{key}")
        if task.task_type == TaskType.FORM_ASSISTANCE and evidence.observed_state.get("identity_bypass") is not False:
            violations.append("身份认证边界被突破")
        if task.risk_level >= RiskLevel.HIGH:
            if not task.slots.get("elder_confirmed"):
                violations.append("缺少老人确认")
            if not task.slots.get("family_approved"):
                violations.append("缺少家属批准")
        receipt_material = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "tool_code": evidence.tool_code,
            "tool_ok": evidence.tool_ok,
            "observed": evidence.observed_state,
            "requested": evidence.requested_state,
            "side_effect_receipt": evidence.side_effect_receipt,
            "violations": violations,
        }
        proof = hashlib.sha256(canonical_json(receipt_material).encode("utf-8")).hexdigest()
        accepted = not violations
        summary = "已通过状态核验。" if accepted else "未通过状态核验：" + "；".join(violations)
        return VerificationReport(accepted=accepted, violations=violations, proof_digest=proof, user_safe_summary=summary)
