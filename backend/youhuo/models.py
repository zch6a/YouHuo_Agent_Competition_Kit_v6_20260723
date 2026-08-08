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
