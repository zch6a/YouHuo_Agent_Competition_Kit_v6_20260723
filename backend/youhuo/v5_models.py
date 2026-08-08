from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import clean_user_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataOrigin(StrEnum):
    USER_VOICE = "user_voice"
    USER_TEXT = "user_text"
    FAMILY = "family"
    TRUSTED_TOOL = "trusted_tool"
    UNTRUSTED_DOCUMENT = "untrusted_document"
    MODEL_INFERENCE = "model_inference"
    SYSTEM = "system"


class DataSensitivity(IntEnum):
    PUBLIC = 0
    PERSONAL = 1
    SENSITIVE = 2
    HIGH = 3


class TranscriptCandidate(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    engine: str = Field(default="unknown", min_length=1, max_length=64)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=2000)


class VoiceResolutionStatus(StrEnum):
    ACCEPTED = "accepted"
    CLARIFY = "clarify"
    BLOCKED = "blocked"


class VoiceTurnRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    candidates: list[TranscriptCandidate] = Field(min_length=1, max_length=8)
    expected_domain: str | None = Field(default=None, max_length=64)
    side_effect_possible: bool = False
    current_task_id: str | None = Field(default=None, max_length=128)


class VoiceTurnResolution(StrictModel):
    status: VoiceResolutionStatus
    resolved_text: str | None
    normalized_text: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguity: float = Field(ge=0.0, le=1.0)
    semantic_intent: str
    clarification_prompt: str | None
    safety_flags: list[str] = Field(default_factory=list)
    consensus_digest: str
    rationale: list[str] = Field(default_factory=list)


class DataFact(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    value: Any
    origin: DataOrigin
    sensitivity: DataSensitivity = DataSensitivity.PERSONAL
    purpose: str = Field(min_length=1, max_length=120)
    trusted_for_control: bool = False

    @field_validator("name", "purpose")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)


class AuthorizationDecision(StrEnum):
    ALLOW = "allow"
    CLARIFY = "clarify"
    REQUIRE_ELDER_CONFIRMATION = "require_elder_confirmation"
    REQUIRE_FAMILY_APPROVAL = "require_family_approval"
    DENY = "deny"


class ActionAuthorizeRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    facts: list[DataFact] = Field(default_factory=list, max_length=64)
    ambiguity: float = Field(default=0.0, ge=0.0, le=1.0)
    user_confirmed: bool = False
    family_approvals: int = Field(default=0, ge=0, le=10)
    reversible: bool = True
    emergency: bool = False

    @field_validator("goal", "action")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=500)


class ActionAuthorization(StrictModel):
    decision: AuthorizationDecision
    reasons: list[str]
    allowed_arguments: dict[str, Any]
    stripped_fields: list[str]
    required_confirmations: list[str]
    policy_version: str
    decision_digest: str
    purpose_bound: bool


class SagaKind(StrEnum):
    MEDICAL_APPOINTMENT = "medical_appointment"
    BILL_PAYMENT = "bill_payment"
    REPORT_FOLLOWUP = "report_followup"
    MEDICATION_REFILL = "medication_refill"


class SagaStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    CANCELLED = "cancelled"


class SagaStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"
    SKIPPED = "skipped"


class SagaCreateRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    kind: SagaKind
    goal: str = Field(min_length=1, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return clean_user_text(value, max_length=500)


class SagaStepRecord(StrictModel):
    id: str
    saga_id: str
    step_index: int
    name: str
    status: SagaStepStatus
    requires_human: bool
    reversible: bool
    compensation_name: str | None
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None


class SagaRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    kind: SagaKind
    goal: str
    status: SagaStatus
    current_step_index: int
    context: dict[str, Any]
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    steps: list[SagaStepRecord] = Field(default_factory=list)


class SagaOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    WAITING = "waiting"


class SagaAdvanceRequest(StrictModel):
    outcome: SagaOutcome
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class SyncSensitivity(StrEnum):
    NORMAL = "normal"
    PERSONAL = "personal"
    HIGH = "high"


class SyncOperationRequest(StrictModel):
    operation_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=128)
    field_name: str = Field(min_length=1, max_length=80)
    value: Any
    base_version: int = Field(ge=0)
    lamport_clock: int = Field(ge=1)
    sensitivity: SyncSensitivity = SyncSensitivity.NORMAL
    occurred_at: datetime

    @field_validator("entity_type", "entity_id", "field_name")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        return clean_user_text(value, max_length=128)


class SyncOutcome(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class SyncOperationResult(StrictModel):
    outcome: SyncOutcome
    entity_type: str
    entity_id: str
    field_name: str
    version: int
    value: Any | None
    conflict_id: str | None
    message: str


class SyncConflictRecord(StrictModel):
    id: str
    family_id: str
    entity_type: str
    entity_id: str
    field_name: str
    current_value: Any
    incoming_value: Any
    current_version: int
    incoming_base_version: int
    sensitivity: SyncSensitivity
    status: str
    created_at: datetime
    resolved_at: datetime | None


class SyncConflictResolutionRequest(StrictModel):
    conflict_id: str = Field(min_length=1, max_length=128)
    resolution: str = Field(pattern=r"^(keep_current|accept_incoming)$")


class BreakGlassRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=5, max_length=500)
    scopes: list[str] = Field(min_length=1, max_length=8)
    duration_minutes: int = Field(default=15, ge=1, le=60)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return clean_user_text(value, max_length=500)


class BreakGlassRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    requested_by: str
    reason: str
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None


class ProofEvent(StrictModel):
    sequence: int
    event_type: str
    actor_id: str
    created_at: datetime
    payload_digest: str
    event_hash: str


class TaskProofBundle(StrictModel):
    id: str
    task_id: str
    family_id: str
    generated_at: datetime
    task_snapshot_digest: str
    audit_chain_valid: bool
    merkle_root: str
    events: list[ProofEvent]
    proof_digest: str
    verification_version: str


class ProofVerifyRequest(StrictModel):
    bundle: TaskProofBundle


class ProofVerifyResult(StrictModel):
    valid: bool
    checks: dict[str, bool]
    message: str


class ExplanationCard(StrictModel):
    task_id: str
    summary: str
    current_status: str
    risk_level: int
    what_i_understood: list[str]
    why_this_action: list[str]
    data_used: list[dict[str, str]]
    confirmations: list[str]
    completion_evidence: list[str]
    reversible: bool
    undo_guidance: str
    stored_data: list[str]
    privacy_note: str


class PrivacyCategory(StrEnum):
    EMOTION_EVENTS = "emotion_events"
    LOCATION_HISTORY = "location_history"
    ITEM_MEMORIES = "item_memories"
    CONTACT_PROFILES = "contact_profiles"
    MEDICAL_DOCUMENTS = "medical_documents"
    HEALTH_EVENTS = "health_events"
    DEVICE_HISTORY = "device_history"


class PrivacyExportRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    categories: list[PrivacyCategory] = Field(default_factory=lambda: list(PrivacyCategory), min_length=1)


class PrivacyExportBundle(StrictModel):
    elder_id: str
    generated_at: datetime
    categories: list[PrivacyCategory]
    records: dict[str, list[dict[str, Any]]]
    manifest_digest: str
    note: str


class PrivacyEraseRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    categories: list[PrivacyCategory] = Field(min_length=1)
    execute: bool = False
    confirmation_phrase: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_confirmation(self) -> "PrivacyEraseRequest":
        if self.execute and self.confirmation_phrase != "我确认删除这些可删除数据":
            raise ValueError("执行删除时必须提供准确确认短语")
        return self


class PrivacyEraseResult(StrictModel):
    executed: bool
    elder_id: str
    categories: list[PrivacyCategory]
    affected_rows: dict[str, int]
    preserved_records: list[str]
    message: str


class TraceSpanCreate(StrictModel):
    trace_id: str = Field(min_length=1, max_length=128)
    span_id: str = Field(min_length=1, max_length=128)
    parent_span_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    started_at: datetime
    ended_at: datetime
    status: str = Field(pattern=r"^(ok|error|cancelled)$")
    attributes: dict[str, Any] = Field(default_factory=dict)


class MetricsSnapshot(StrictModel):
    generated_at: datetime
    counters: dict[str, int]
    rates: dict[str, float]
    audit_chain_valid: bool
    privacy_note: str
