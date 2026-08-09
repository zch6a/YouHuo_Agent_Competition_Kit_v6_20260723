from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from .utils import clean_user_text
from .v5_models import ActionAuthorization, DataFact


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerbosityMode(StrEnum):
    CONCISE = "concise"
    STANDARD = "standard"
    GENTLE = "gentle"


class ConfirmationStyle(StrEnum):
    YES_NO = "yes_no"
    TEACH_BACK = "teach_back"
    FAMILY_RELAY = "family_relay"


class InteractionProfileUpdate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    speech_rate: float = Field(default=0.88, ge=0.6, le=1.2)
    verbosity: VerbosityMode = VerbosityMode.GENTLE
    max_options: int = Field(default=3, ge=1, le=3)
    max_sentence_chars: int = Field(default=42, ge=16, le=90)
    repeat_sensitive: bool = True
    teach_back_high_risk: bool = True
    font_scale: float = Field(default=1.25, ge=1.0, le=1.8)
    hearing_support: bool = False
    dialect_hint: str | None = Field(default=None, max_length=32)

    @field_validator("dialect_hint")
    @classmethod
    def clean_dialect(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_user_text(value, max_length=32)
        return cleaned or None


class InteractionProfile(InteractionProfileUpdate):
    family_id: str
    updated_by: str
    updated_at: datetime
    version: int = Field(ge=1)


class InteractionPlanRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=3000)
    options: list[str] = Field(default_factory=list, max_length=8)
    risk_level: int = Field(default=1, ge=1, le=4)
    asr_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    recent_retries: int = Field(default=0, ge=0, le=10)
    current_step: str | None = Field(default=None, max_length=160)
    reversible: bool = True
    force_teach_back: bool = False
    #: Observed difficulty from this elder's recent verified teach-backs, 0-1.
    #: The server fills this in from stored evidence; clients may leave it at 0.
    comprehension_difficulty: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        return clean_user_text(value, max_length=3000)

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str]) -> list[str]:
        return [clean_user_text(item, max_length=80) for item in value if clean_user_text(item, max_length=80)]


class InteractionPlan(StrictModel):
    mode: str
    speak_text: str
    visual_text: str
    visible_options: list[str]
    hidden_option_count: int = Field(ge=0)
    speech_rate: float
    font_scale: float
    require_repeat_confirmation: bool
    require_teach_back: bool
    confirmation_style: ConfirmationStyle
    cognitive_load_score: float = Field(ge=0.0, le=1.0)
    turn_budget: int = Field(ge=1, le=5)
    next_expected_response: str
    rationale: list[str]
    #: Echoed so the interaction plan is auditable end to end.
    comprehension_difficulty: float = 0.0
    plan_digest: str


class SourceEvidence(StrictModel):
    label: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=80)
    trusted: bool = False
    verified: bool = False

    @field_validator("label", "source")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)


class RelianceCardRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    heard_text: str = Field(min_length=1, max_length=1000)
    goal: str = Field(min_length=1, max_length=500)
    current_step: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=80)
    risk_level: int = Field(default=1, ge=1, le=4)
    reversible: bool = True
    confirmations: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=16)
    next_step: str = Field(min_length=1, max_length=300)

    @field_validator("heard_text", "goal", "current_step", "action", "next_step")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=1000)


class RelianceCard(StrictModel):
    title: str
    heard: str
    goal: str
    current_step: str
    action_summary: str
    data_sources: list[dict[str, Any]]
    who_decides: str
    reversible: bool
    next_step: str
    confidence_message: str
    warning: str | None
    card_digest: str


class SafePreviewRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    facts: list[DataFact] = Field(default_factory=list, max_length=64)
    ambiguity: float = Field(default=0.0, ge=0.0, le=1.0)
    user_confirmed: StrictBool = False
    family_approvals: StrictInt = Field(default=0, ge=0, le=10)
    reversible: StrictBool = True
    emergency: StrictBool = False

    @field_validator("goal", "action")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=500)


class SafePreview(StrictModel):
    authorization: ActionAuthorization
    plain_summary: str
    will_do: list[str]
    will_not_do: list[str]
    required_humans: list[str]
    rollback_plan: str
    data_use_summary: list[str]
    preview_digest: str


class TaskGlassBoxRequest(StrictModel):
    heard_text: str = Field(min_length=1, max_length=1000)

    @field_validator("heard_text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=1000)


class TaskGlassBox(StrictModel):
    """Reliance card plus safe preview built from the authoritative task record.

    Assembling this on the server keeps policy arguments and raw slots off the
    client, and stops the elder-facing card from showing internal status enums.
    """

    task_id: str
    action_label: str
    policy_action: str | None
    card: RelianceCard
    preview: SafePreview | None


class SemanticFrame(StrictModel):
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    slots: dict[str, Any] = Field(default_factory=dict)
    needs_clarification: bool
    clarification_prompt: str | None
    parser_source: str
    model_used: bool
    safety_flags: list[str] = Field(default_factory=list)
    frame_digest: str


class SemanticParseRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    current_task: str | None = Field(default=None, max_length=80)
    permit_remote_model: bool = False

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=2000)


class StudyRole(StrEnum):
    ELDER = "elder"
    FAMILY = "family"
    OBSERVER = "observer"


class StudySessionCreate(StrictModel):
    participant_code: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    role: StudyRole
    consent_version: str = Field(min_length=1, max_length=32)
    age_band: str | None = Field(default=None, max_length=32)
    device_type: str = Field(default="phone", max_length=32)
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("age_band", "device_type", "notes")
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_user_text(value, max_length=300)
        return cleaned or None


class StudySession(StudySessionCreate):
    id: str
    family_id: str
    created_by: str
    created_at: datetime
    status: str


class StudyObservationCreate(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    scenario: str = Field(min_length=1, max_length=120)
    success: bool
    duration_seconds: float = Field(ge=0.0, le=7200)
    clarification_count: int = Field(default=0, ge=0, le=100)
    assistance_count: int = Field(default=0, ge=0, le=100)
    perceived_ease: int = Field(ge=1, le=5)
    trust_calibration: int = Field(ge=1, le=5)
    comments: str | None = Field(default=None, max_length=500)

    @field_validator("scenario", "comments")
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_user_text(value, max_length=500)
        return cleaned or None


class StudyObservation(StudyObservationCreate):
    id: str
    family_id: str
    created_by: str
    created_at: datetime


class StudySummary(StrictModel):
    session_count: int
    observation_count: int
    task_success_rate: float
    median_duration_seconds: float
    mean_clarifications: float
    mean_assistance: float
    mean_perceived_ease: float
    mean_trust_calibration: float
    caution: str


class CompetitionEvidenceItem(StrictModel):
    dimension: str
    score_weight: int
    readiness: str
    evidence: list[str]
    remaining_gap: list[str]


class CompetitionEvidenceBoard(StrictModel):
    competition: str
    project_version: str
    items: list[CompetitionEvidenceItem]
    top_three_story: list[str]
    hard_no_claims: list[str]
    generated_at: datetime
