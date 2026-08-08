from __future__ import annotations

import base64
import binascii
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .utils import clean_user_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutineFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class RoutineCategory(StrEnum):
    LIFE = "life"
    MEDICATION = "medication"
    MEDICAL = "medical"
    PAYMENT = "payment"
    SOCIAL = "social"


class RoutineStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class OccurrenceStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    OVERDUE = "overdue"


class RoutineCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    category: RoutineCategory = RoutineCategory.LIFE
    frequency: RoutineFrequency
    interval: int = Field(default=1, ge=1, le=24)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    time_local: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    start_date: date
    escalation_after_minutes: int = Field(default=60, ge=5, le=10080)
    positive_message: str = Field(default="这件事已经完成了，我们做得可真棒！", max_length=120)

    @field_validator("title", "positive_message")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        result = sorted(set(value))
        if any(day < 0 or day > 6 for day in result):
            raise ValueError("weekdays must use Monday=0 through Sunday=6")
        return result

    @model_validator(mode="after")
    def validate_frequency_fields(self) -> "RoutineCreate":
        if self.frequency == RoutineFrequency.WEEKLY and not self.weekdays:
            raise ValueError("weekly routine requires at least one weekday")
        if self.frequency != RoutineFrequency.WEEKLY and self.weekdays:
            raise ValueError("weekdays are only valid for weekly routines")
        if self.frequency == RoutineFrequency.MONTHLY and self.day_of_month is None:
            raise ValueError("monthly routine requires day_of_month")
        if self.frequency != RoutineFrequency.MONTHLY and self.day_of_month is not None:
            raise ValueError("day_of_month is only valid for monthly routines")
        return self


class RoutineRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    title: str
    category: RoutineCategory
    frequency: RoutineFrequency
    interval: int
    weekdays: list[int]
    day_of_month: int | None
    time_local: str
    timezone: str
    start_date: date
    next_due_at: datetime
    escalation_after_minutes: int
    positive_message: str
    status: RoutineStatus
    created_by: str
    created_at: datetime
    updated_at: datetime


class RoutineOccurrence(StrictModel):
    id: str
    routine_id: str
    family_id: str
    elder_id: str
    due_at: datetime
    status: OccurrenceStatus
    reminder_id: str | None = None
    completed_at: datetime | None = None
    created_at: datetime


class RoutineMaterializeRequest(StrictModel):
    now: datetime
    horizon_days: int = Field(default=45, ge=1, le=366)


class EmotionLabel(StrEnum):
    POSITIVE = "positive"
    CALM = "calm"
    LONELY = "lonely"
    LOW_MOOD = "low_mood"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    URGENT = "urgent"


class EmotionAnalyzeRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="voice", min_length=1, max_length=40)
    store_event: bool = True

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=2000)


class EmotionAnalysis(StrictModel):
    label: EmotionLabel
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    distress: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_categories: list[str] = Field(default_factory=list)
    should_pause_task: bool
    should_notify_family: bool
    user_message: str
    privacy_safe_note: str


class EmotionEvent(StrictModel):
    id: str
    family_id: str
    elder_id: str
    label: EmotionLabel
    valence: float
    arousal: float
    distress: float
    confidence: float
    source: str
    text_digest: str
    privacy_safe_note: str
    created_at: datetime


class PrivacyReport(StrictModel):
    id: str
    family_id: str
    elder_id: str
    report_type: str
    period_start: date
    period_end: date
    summary: dict[str, Any]
    generated_at: datetime
    privacy_guarantee: str


class MemorySensitivityV4(StrEnum):
    NORMAL = "normal"
    PERSONAL = "personal"
    HIGH = "high"


class ShareScope(StrEnum):
    PRIVATE = "private"
    FAMILY_SUMMARY = "family_summary"
    FAMILY_SHARED = "family_shared"


class ItemCategory(StrEnum):
    KEY = "key"
    MEDICATION = "medication"
    DOCUMENT = "document"
    BANKBOOK = "bankbook"
    CONTACT = "contact"
    OTHER = "other"


class ItemMemoryCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=80)
    category: ItemCategory
    location_text: str = Field(min_length=1, max_length=240)
    notes: str = Field(default="", max_length=500)
    sensitivity: MemorySensitivityV4 = MemorySensitivityV4.PERSONAL
    scope: ShareScope = ShareScope.PRIVATE
    photo_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("label", "location_text", "notes")
    @classmethod
    def clean_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=500)


class ItemMemoryRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    label: str
    category: ItemCategory
    location_text: str
    notes: str
    sensitivity: MemorySensitivityV4
    scope: ShareScope
    photo_sha256: str | None
    created_by: str
    consented_by: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ItemSearchResponse(StrictModel):
    query: str
    matches: list[ItemMemoryRecord]
    spoken_answer: str


class ContactCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    relation: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    notes: str = Field(default="", max_length=300)
    scope: ShareScope = ShareScope.FAMILY_SHARED

    @field_validator("display_name", "relation", "notes")
    @classmethod
    def clean_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=300)


class ContactRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    display_name: str
    relation: str
    phone_masked: str | None
    notes: str
    scope: ShareScope
    face_template_digest: str | None
    consented_by: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class FaceImageRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    image_b64: str = Field(min_length=4, max_length=2_800_000)

    def image_bytes(self) -> bytes:
        try:
            raw = base64.b64decode(self.image_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 image") from exc
        if not raw or len(raw) > 2_000_000:
            raise ValueError("image must be between 1 byte and 2 MB")
        return raw


class FaceEnrollmentRequest(FaceImageRequest):
    contact_id: str = Field(min_length=1, max_length=128)


class FaceMatchResult(StrictModel):
    matched: bool
    contact: ContactRecord | None
    confidence: float = Field(ge=0, le=1)
    engine: str
    production_ready: bool
    warning: str




class ConsentDecisionRequest(StrictModel):
    record_id: str = Field(min_length=1, max_length=128)
    approve: bool

class MedicalDocumentKind(StrEnum):
    CHECKUP_REPORT = "checkup_report"
    DISCHARGE_NOTE = "discharge_note"
    PRESCRIPTION = "prescription"
    APPOINTMENT_NOTICE = "appointment_notice"


class MedicalReportAnalyzeRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    kind: MedicalDocumentKind
    text: str = Field(min_length=1, max_length=12000)
    source_name: str = Field(default="拍照OCR", max_length=120)
    create_followup_reminder: bool = False

    @field_validator("text", "source_name")
    @classmethod
    def clean_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=12000)


class MedicalReportAnalysis(StrictModel):
    document_id: str | None = None
    kind: MedicalDocumentKind
    dates: list[str]
    measurements: list[dict[str, Any]]
    terms: list[dict[str, str]]
    follow_up_date: str | None
    summary_for_elder: str
    caution_flags: list[str]
    review_required: bool = True
    source_digest: str


class HealthEventKind(StrEnum):
    CHECKUP = "checkup"
    VISIT = "visit"
    MEDICATION = "medication"
    NOTE = "note"


class HealthEventCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    kind: HealthEventKind
    title: str = Field(min_length=1, max_length=120)
    event_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual", max_length=80)
    scope: ShareScope = ShareScope.FAMILY_SUMMARY

    @field_validator("title", "source")
    @classmethod
    def clean_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)


class HealthEventRecord(HealthEventCreate):
    id: str
    family_id: str
    created_at: datetime


class MedicationPlanCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    normalized_name: str = Field(min_length=1, max_length=120)
    dose_text: str = Field(min_length=1, max_length=120)
    times_local: list[str] = Field(min_length=1, max_length=8)
    start_date: date
    end_date: date | None = None
    stock_units: float = Field(default=0, ge=0, le=100000)
    units_per_dose: float = Field(default=1, gt=0, le=1000)
    source: str = Field(default="manual", max_length=80)

    @field_validator("display_name", "normalized_name", "dose_text", "source")
    @classmethod
    def clean_fields(cls, value: str) -> str:
        return clean_user_text(value, max_length=120)

    @field_validator("times_local")
    @classmethod
    def validate_times(cls, value: list[str]) -> list[str]:
        unique = sorted(set(value))
        for item in unique:
            if len(item) != 5 or item[2] != ":" or not item[:2].isdigit() or not item[3:].isdigit():
                raise ValueError("times_local must use HH:MM")
            hour, minute = int(item[:2]), int(item[3:])
            if hour > 23 or minute > 59:
                raise ValueError("invalid time")
        return unique

    @model_validator(mode="after")
    def validate_dates(self) -> "MedicationPlanCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        return self


class MedicationPlanRecord(MedicationPlanCreate):
    id: str
    family_id: str
    active: bool
    created_at: datetime
    updated_at: datetime


class DoseStatus(StrEnum):
    TAKEN = "taken"
    SKIPPED = "skipped"
    MISSED = "missed"


class DoseRecordRequest(StrictModel):
    scheduled_at: datetime
    status: DoseStatus
    note: str = Field(default="", max_length=240)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return clean_user_text(value, max_length=240)


class DoseRecord(StrictModel):
    id: str
    plan_id: str
    scheduled_at: datetime
    status: DoseStatus
    recorded_at: datetime
    note: str


class InventoryForecast(StrictModel):
    plan_id: str
    stock_units: float
    units_per_day: float
    days_remaining: float | None
    estimated_depletion_date: date | None
    alert_level: str


class InteractionCheckRequest(StrictModel):
    medication_names: list[str] = Field(min_length=2, max_length=20)

    @field_validator("medication_names")
    @classmethod
    def normalize_names(cls, value: list[str]) -> list[str]:
        return [clean_user_text(item, max_length=120).casefold() for item in value]


class InteractionFinding(StrictModel):
    medication_a: str
    medication_b: str
    severity: str
    message: str
    source: str
    evidence_level: str


class InteractionCheckResult(StrictModel):
    normalized_medications: list[str]
    findings: list[InteractionFinding]
    database_scope: str
    requires_pharmacist_review: bool = True
    warning: str


class SafetyPolicyUpdate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    inactivity_minutes: int = Field(default=720, ge=30, le=10080)
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lon: float | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int = Field(default=1500, ge=100, le=100000)
    notify_community: bool = False

    @model_validator(mode="after")
    def coordinates_pair(self) -> "SafetyPolicyUpdate":
        if (self.home_lat is None) != (self.home_lon is None):
            raise ValueError("home_lat and home_lon must be provided together")
        return self


class ActivityHeartbeatRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    kind: str = Field(default="interaction", min_length=1, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InactivityEvaluationRequest(StrictModel):
    now: datetime


class SOSRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    message: str = Field(default="老人主动呼救", max_length=240)
    include_community: bool = True
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationPingRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(default=50, ge=0, le=10000)
    occurred_at: datetime
    source: str = Field(default="device", max_length=40)


class GeofenceResult(StrictModel):
    inside_home_area: bool | None
    distance_from_home_m: float | None
    alert_created: bool
    accuracy_warning: bool
    message: str


class POIKind(StrEnum):
    HOSPITAL = "hospital"
    PHARMACY = "pharmacy"
    MARKET = "market"


class POIRecord(StrictModel):
    name: str
    kind: POIKind
    latitude: float
    longitude: float
    distance_m: float
    navigation_instruction: str
    source: str = "demo_catalog"


class DeviceRegisterRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=40)
    brand: str = Field(min_length=1, max_length=80)
    device_name: str = Field(min_length=1, max_length=120)
    push_capable: bool = True


class DeviceRecord(DeviceRegisterRequest):
    family_id: str
    trust_level: str
    last_seen_at: datetime
    registered_at: datetime


class AssistanceRequestCreate(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    requested_capabilities: list[str] = Field(min_length=1, max_length=10)
    expires_in_minutes: int = Field(default=15, ge=1, le=120)


class AssistanceRequestRecord(StrictModel):
    id: str
    family_id: str
    elder_id: str
    requested_by: str
    requested_capabilities: list[str]
    status: str
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None


class MonthlyReportRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)


class CareGraphNode(StrictModel):
    id: str
    kind: str
    label: str
    occurred_at: datetime
    risk: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CareGraphEdge(StrictModel):
    source: str
    target: str
    relation: str


class CareGraph(StrictModel):
    elder_id: str
    nodes: list[CareGraphNode]
    edges: list[CareGraphEdge]
    generated_at: datetime


class CapabilityStatus(StrictModel):
    capability: str
    state: str
    implementation: str
    production_dependency: str | None
    safety_boundary: str
