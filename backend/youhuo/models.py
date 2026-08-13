from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .utils import clean_user_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mode(StrEnum):
    YOUHUO = "youhuo"
    COMPANION = "companion"


class ActorRole(StrEnum):
    ELDER = "elder"
    FAMILY = "family"
    SYSTEM = "system"


class TaskType(StrEnum):
    HOSPITAL_REGISTRATION = "hospital_registration"
    BILL_PAYMENT = "bill_payment"
    REMINDER = "reminder"
    FORM_ASSISTANCE = "form_assistance"


class TaskStatus(StrEnum):
    COLLECTING = "collecting"
    AWAITING_ELDER_CONFIRMATION = "awaiting_elder_confirmation"
    AWAITING_FAMILY_APPROVAL = "awaiting_family_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class RiskLevel(IntEnum):
    INFORMATION = 1
    LOW = 2
    SENSITIVE = 3
    HIGH = 4


class ResponseCode(StrEnum):
    OK = "ok"
    NEED_MORE_INFO = "need_more_info"
    NEED_ELDER_CONFIRMATION = "need_elder_confirmation"
    NEED_FAMILY_APPROVAL = "need_family_approval"
    TASK_COMPLETED = "task_completed"
    TASK_CANCELLED = "task_cancelled"
    DUPLICATE_BLOCKED = "duplicate_blocked"
    SAFETY_ALERT = "safety_alert"
    MODE_SWITCHED = "mode_switched"
    CHAT = "chat"
    ERROR = "error"


class TaskRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    task_type: TaskType
    status: TaskStatus
    risk_level: RiskLevel
    slots: dict[str, Any] = Field(default_factory=dict)
    semantic_key: str
    version: int = 1
    approval_digest: str | None = None
    created_at: datetime
    updated_at: datetime
    deferred_topics: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class TaskView(StrictModel):
    """Privacy-preserving task projection returned to clients.

    Internal state such as deferred companion topics, semantic hashes, raw slots,
    approval versioning and confirmation hashes never crosses the API boundary.
    """

    id: str
    elder_id: str
    task_type: TaskType
    status: TaskStatus
    risk_level: RiskLevel
    summary: str
    approval_digest: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ReminderRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    title: str
    due_at: datetime
    escalation_after_minutes: int = 30
    status: ReminderStatus
    source: str
    created_by: str
    created_at: datetime
    notified_at: datetime | None = None
    acknowledged_at: datetime | None = None
    completed_at: datetime | None = None
    escalated_at: datetime | None = None


class NotificationRecord(StrictModel):
    id: int
    family_id: str
    recipient_role: ActorRole
    event_type: str
    entity_id: str | None
    message: str
    created_at: datetime
    read_at: datetime | None = None


class SessionState(StrictModel):
    session_id: str
    family_id: str
    elder_id: str
    mode: Mode = Mode.YOUHUO
    active_task_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AuthContext(StrictModel):
    actor_id: str
    family_id: str
    role: ActorRole
    display_name: str


class DemoLoginRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=128)


class DemoLoginResponse(StrictModel):
    access_token: str
    token_type: str = "bearer"
    actor: AuthContext
    expires_at: datetime


class VisitorSandboxResponse(StrictModel):
    """One freshly seeded, isolated demo household for a login-free visitor.

    Both tokens are returned together so the elder and family views of the same
    sandbox work without a second round trip; they are demo tokens for a
    generated household, never credentials for a real account.
    """

    elder_id: str
    daughter_id: str
    son_id: str
    family_id: str
    elder_token: str
    family_token: str
    token_type: str = "bearer"
    actor: AuthContext
    expires_at: datetime


class SessionCreateRequest(StrictModel):
    session_id: str | None = Field(default=None, max_length=128)


class SessionCreateResponse(StrictModel):
    session_id: str
    family_id: str
    elder_id: str
    mode: Mode


class ChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=2000)


class ChatResponse(StrictModel):
    code: ResponseCode
    message: str
    mode: Mode
    task_id: str | None = None
    task_status: TaskStatus | None = None
    risk_level: RiskLevel | None = None
    approval_digest: str | None = None
    ui: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class FamilyApprovalRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=128)
    approve: bool
    approval_digest: str = Field(min_length=16, max_length=128)
    reason: str | None = Field(default=None, max_length=300)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class FamilyReminderCreateRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    due_at: datetime
    escalation_after_minutes: int = Field(default=30, ge=5, le=1440)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)


class ReminderActionRequest(StrictModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ReminderEvaluationRequest(StrictModel):
    now: datetime


class AuditEvent(StrictModel):
    id: int
    family_id: str
    actor_id: str
    event_type: str
    entity_id: str | None
    payload: dict[str, Any]
    created_at: datetime
    prev_hash: str
    event_hash: str


class ElderActivityEntry(StrictModel):
    """One line of the plain-language activity log shown on the elder home page.

    Design §4.4 gives the elder a log entry point, while §6.3 keeps companion
    chat transcripts out of any log. This projection therefore renders only
    allow-listed audit event types and never carries free-form conversation text.
    """

    id: int
    happened_at: datetime
    who: str
    what: str
    kind: str
    #: 这一行**说的是哪件事**——任务 id 或提醒 id，取不到时为 None。
    #:
    #: 为什么不叫 `entity_id`：审计事件那边叫 `entity_id`，而这个模型是同一个事实的
    #: **叙事投影**（`privacy.py` 的 allow-list 决定哪些事件配得上一行人话）。
    #: 两侧本来就该用不同的词汇，混用会让人以为这两个模型可以互相替代。
    #:
    #: 谁需要它：这一行现在是纯文本，点不动，语音也指不到它。而语音的表达空间没有
    #: 上限、底部导航只有四格，所以「上个月的水费交了没」必须能落到那笔事务本身——
    #: 它得先有个地址。**这个 id 只进 `dataset`，永远不渲染成文字**
    #: （`test_the_app_surface_never_renders_a_raw_identifier` 守这一条）。
    about_id: str | None = None


class ToolResult(StrictModel):
    """Typed tool output. External text is data and never executable instruction."""

    ok: bool
    code: str
    data: dict[str, Any] = Field(default_factory=dict)
    user_message: str


class LLMIntent(StrictModel):
    """Optional advisory structured output; never an authorization decision."""

    intent: str
    confidence: float = Field(ge=0, le=1)
    extracted_slots: dict[str, Any] = Field(default_factory=dict)
    rationale_short: str = Field(default="", max_length=240)
