from __future__ import annotations

import base64
import binascii
from datetime import UTC, date, datetime, timedelta
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
    """例程的一次发生。

    `positive_message` 是例程建的时候填的那句鼓励话，存在
    `recurring_routines` 上（一条例程一句）。它此前**到不了调用方**：
    `V4FeatureStore.complete_occurrence` 的 SQL 明明 `JOIN` 出了
    `r.positive_message`，函数里一次都没用，而这个模型也没有这个字段——于是
    老人做完一件事，那句本该说给她听的话在服务端被丢掉了。实测：把它设成一个
    含标记的串，完成响应、`/v2/reminders`、`/api/v1/agenda` 里都找不到那个标记，
    唯一能看到它的是 `GET /v4/routines/{elder}`（例程本身，不是发生）。

    不做成 `str | None`：`recurring_routines.positive_message` 是 `NOT NULL`，
    `routine_occurrences.routine_id` 是指向它的外键，`PRAGMA foreign_keys=ON`
    （见 `Database.__init__`），而且例程没有删除路径（`set_routine_status`
    只改状态，注释里写明了原因）。所以这句话一定在，可选类型只会让调用方
    以为它可能缺，然后写一个永远走不到的兜底。
    """

    id: str
    routine_id: str
    family_id: str
    elder_id: str
    due_at: datetime
    status: OccurrenceStatus
    positive_message: str
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
    """一位亲友的档案。

    ## 这里**故意**没有 `phone_digest`

    `contact_profiles_v4.phone_digest` 原先只写不读（写在 `seed_demo` 和
    `create_contact`，`_row_contact` 不取，全仓零 SELECT），而
    `UNIQUE(elder_id,display_name,relation)` 又只管名字和关系——于是同一个电话
    号码换个称呼就能再登记一遍，实测名单上出现两位「*******8111」。
    现在 `create_contact` 用它去重了（见 `V4FeatureStore._mask_phone` 的说明），
    它承重了。

    但它不上这条响应。手机号只有十一位、号段还是固定的，sha256 反查是毫秒级的
    事——把摘要发出去等于把号码发出去，`phone_masked` 那层掩码就白做了。
    它是一个只在服务端做等值比较的内部键，留在库里，不进接口。
    """

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


class MedicalDocumentRecord(StrictModel):
    """一份已经整理好的就医单据，**按 `document_id` 取回来的样子**。

    `/v4/medical-reports/analyze` 一直把 `document_id` 回给客户端，而在这个模型
    出现之前，全仓对 `medical_documents_v4` 的唯一 SELECT 是去重用的
    `WHERE source_digest`——`extracted_json` 和 `simplified_json` 两列写进去就
    再没有人读。实测：拿着回来的 id 试 `/v4/medical-reports/{id}`、
    `/v4/medical-documents/{id}`、`/v4/documents/{id}` 全是 404，而库里那条
    `simplified_json` 装着可用的摘要正文。也就是说那个 id 是个悬空引用。

    ## 这里**没有**原文

    只有 `source_digest`（摘要），没有 `text`。原文本来就没入库——
    `save_medical_document` 存的是解析结果，不是那张单据的字。这一点不要「补上」：
    就医单据的原文是这个仓库里最敏感的一类文本，而它现在连一次都不落盘。

    ## 取回的范围

    路由那一侧走 `ensure_target`，也就是**本人或本家庭**，与创建它的
    `/v4/medical-reports/analyze` 同一把尺子（那个端点家属也能调——家属替老人
    拍单据是真实场景）。跨家庭一律 404 而不是 403：403 会把「这个 id 存在」
    说出去。

    ## 不绕过删除

    读的就是 `medical_documents_v4` 本表，不做第二份缓存。`/v5/privacy` 把
    `medical_documents` 列成可删类别，`privacy_erase` 是真的
    `DELETE FROM medical_documents_v4`；实测删完这条 GET 就是 404。
    """

    id: str
    elder_id: str
    kind: MedicalDocumentKind
    source_name: str
    source_digest: str
    dates: list[str]
    measurements: list[dict[str, Any]]
    follow_up_date: str | None
    terms: list[dict[str, str]]
    summary_for_elder: str
    caution_flags: list[str]
    review_required: bool
    created_at: datetime


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
    """还能吃几天，以及**该说的那句话**。

    ## 后三个字段是为了让阈值只存在一处

    `alert_level` 的阈值在 `InventoryService.forecast` 里：不足 2 天 critical、
    不足 7 天 warning。`v4_api` 拿 critical/warning 去发家属通知。
    而 `backend/static/care.js` 的 `daysLeft()` 用 JS 把「还能吃几天」重算了一遍，
    红字阈值写的是 `days <= 3`。实测同一份计划（11 片、每天 2 片）：

        后端 days_remaining=5.5、alert_level=warning  → 发了家属通知
        care.js floor(11/2)=5、5 <= 3 为假           → 屏幕上是普通灰字

    也就是说家属手机上响了，老人屏幕上说「还够 5 天」，看不出任何异常。
    两个阈值各自都说得通，问题在于它们是两个。

    所以后端把**结论**发出来，前端不必再自己定阈值：

    - `whole_days_remaining`：该说出口的那个整数（向下取整，和 care.js 原来
      算出的 5 一致——差的从来不是这个数，是阈值）。
    - `should_highlight`：屏幕上是否该标红。前端不要再自己写
      `alert_level in {...}`；那个集合归后端。
    - `message`：该说的那句话。语音是这个产品的主界面，这句话同时给屏幕和播报。

    `alert_level` 保留原样：它是机器判断，已经有三个消费方
    （`v4_api` 的通知、`care_voice.answer_medication_stock`、
    `app_api._STOCK_WORDS`），不动。
    """

    plan_id: str
    stock_units: float
    units_per_day: float
    days_remaining: float | None
    estimated_depletion_date: date | None
    alert_level: str
    whole_days_remaining: int | None = None
    should_highlight: bool = False
    message: str = ""


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


#: 允许设备时钟往前偏多少。真机时钟会漂，卡死在"不得晚于此刻"会拒掉正常心跳；
#: 但放开到无限，一条心跳就能把无交互预警永久关掉（见下）。
CLOCK_SKEW_ALLOWANCE = timedelta(minutes=5)


class ActivityHeartbeatRequest(StrictModel):
    """一条「她还在动」的心跳。

    ## 这里**没有** `metadata`，是故意的

    原来有一个 `metadata: dict[str, Any]`。它落在
    `activity_events_v4.metadata_json`，而那一列**全仓零 SELECT**：
    `evaluate_inactivity` 只取 `occurred_at`。实测带 `{"room":"客厅"}` 的心跳
    入库了，`/v4/safety/inactivity/evaluate` 的响应里没有它，扫遍其余路由也
    没有第二个人读。

    删掉而不是「把它带出来」，是因为它没有生产者，也没有可诚实交付的消费者：

    - 全仓没有一个调用方送过它。`backend/scripts/device_probe.py`、
      `backend/scripts/verify_features_v6.py`、`backend/static/proof-demos.js`、
      现有全部判据，送的都是 `{elder_id, kind, occurred_at}`。
      `HARDWARE.md` 给板子写的请求体也是这三个字段。
    - 「最后一次活动在哪个房间」这件事**这块板子给不出来**。
      `HARDWARE.md` 上的存在雷达是 HLK-LD2410C-P，一块板一个位置，出的是
      「有没有人 / 距离」。房间是多点部署才有的维度，现在没有第二个点。
      为它留一个字段，等于把一个永远是 `{}` 的洞留在家属那一屏上。
    - 它是个无上界的口子。实测 40 KB 的 `metadata` 照收照存，任意深嵌套也收。
      而心跳是老人端写、家属端读的：把这个 blob 端到家属面前，就是在这个
      到处是 `ShareScope` 和本人同意的仓库里，开一条不带范围、不带同意的
      明文通道（情绪那边正是为了这个只存 `text_digest`）。

    删掉之后 `extra="forbid"` 会**把这件事说出来**：送 `metadata` 从「200，
    然后数据消失」变成 422。这个端点本来就是严的——实测多送一个
    `distance_cm` 今天就是 422，`metadata` 只是当时唯一那个「收下再扔掉」的口子。
    真要把雷达的距离读数接进来，该做的是加一个说得出名字、有人读的字段，
    不是往一个无人读的 blob 里塞。
    """

    elder_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    kind: str = Field(default="interaction", min_length=1, max_length=40)

    @field_validator("occurred_at")
    @classmethod
    def reject_future_activity(cls, value: datetime) -> datetime:
        """活动心跳不能来自未来。

        `evaluate_inactivity` 取的是 `ORDER BY occurred_at DESC LIMIT 1`，然后算
        `(now - last)`。一条未来时间戳会让这个差值一直是负数，于是
        `inactive_minutes >= threshold` 永远为假——**这位老人的无交互预警从此不再
        触发**，而且界面上没有任何迹象，看起来只是"一直很正常"。

        演示播种那边已经因为同一个原因加了 `if moment > horizon: continue`；但那只
        堵住了一个写入者。这张表的另一个写入口是这个公开端点，任何客户端 POST 一条
        2099 年的心跳就能关掉报警。检测逻辑严过写入逻辑是没有意义的。
        """
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if moment > datetime.now(UTC) + CLOCK_SKEW_ALLOWANCE:
            raise ValueError("occurred_at 不能是未来时间")
        return value


class InactivityEvaluationRequest(StrictModel):
    now: datetime


class SOSRequest(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    message: str = Field(default="老人主动呼救", max_length=240)
    include_community: bool = True
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationPingRequest(StrictModel):
    """一次位置上报。

    `accuracy_m` 是这次定位的精度，单位米。**不知道就不要填**（留空或传
    `null`），**不要补 0**：0 的意思是「精确到米」，不是「没有这个数」。

    留空时后端既不判断她在不在活动范围内、也不会自动报警，而是回一条精度
    告警交给家属去看——这是 `youhuo-location-safety` 的「边界不确定时不自动
    报警」。填了真实值才会正常判断；离围栏 100 米以上一定报警，与精度无关。

    这段话必须留在类的 docstring 里：它会随 `generate_openapi_v6.py` 进入
    小艺读的那份契约（判据
    `test_a_location_without_accuracy_does_not_raise_an_alarm.py` 直接检查
    生成出来的 JSON）。这个仓库全部 model 里 `Field(description=…)` 是 0 处，
    契约上的字段说明**只有**这条路。
    """

    elder_id: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    #: 这次定位有多准，单位米。**`None` 表示这台设备没报精度**，
    #: 不是「精度很好」。以前这里 `default=50`：字段不传就当成 50 米——
    #: 一个后端并不知道、却足以决定要不要给家属报警的数。围栏 1000 米、
    #: 她在围栏外 1 米时，`accuracy_m=0`（鸿蒙端取不到精度时补的那个值）
    #: 是整张实测表里**唯一报警**的一行，而任何真实精度都不报警。
    #: 见 `LocationSafety.evaluate_geofence` 的 docstring。
    accuracy_m: float | None = Field(default=None, ge=0, le=10000)
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
    """一次「家人想帮我一下」的请求与老人的答复。

    ## 这条记录**不驱动任何远程动作**，这一版做不到

    `requested_capabilities` 的四个名字（查看当前这一步 / 语音指导 /
    控件高亮 / 低风险表单提交）在全仓只出现在
    `create_assistance_request` 的白名单校验里。实测：家属请求、老人同意、
    `status` 变成 approved，然后什么都不会发生——**没有任何能力闸门读它**。

    判定是这一版交付不了，理由不是「没排上」，是三样东西都不在：

    1. **没有服务端到老人设备的通道。** 语音指导和控件高亮都要把一条指令推到
       她那块屏上。全仓运行时没有 WebSocket、没有 SSE、没有推送（`websocket`
       只出现在 CDP 巡检脚本里）。`devices_v4.push_capable` 写进去了，
       全仓零 SELECT。`CapabilityMatrix` 自己就把 Push Kit 列成
       `production_dependency`——也就是还没有。
    2. **「代为提交表单」是这个仓库特意禁止的方向。** 低风险表单提交等于家属
       在老人名下动作。`/v4/medications/decide`、`/v4/routine-occurrences` 的
       完成、复查日入日历，每一处都写着「只有老人本人可以」。为远程协助开一个
       例外，是把已经修过一次的缺陷再做一遍。
    3. **「查看当前这一步」家属现在就能看，不需要授权。**
       `GET /v4/care-graph/{elder_id}` 和 `GET /v4/routine-occurrences/{elder_id}`
       对绑定家属是无条件开放的。把它挂到这条同意上，要么是授予一个已经有的
       权限（装饰），要么是把现有访问收回去（回归）。两个都不是修。

    所以不发明一条远程控制通道。这条记录留下来的是它真正能承担的东西：**一次
    有范围、有期限、可查询的口头协助约定的留痕**。通知的措辞按这个改了
    （见 `v4_api.create_assistance`），`/v4/capabilities` 里也加了一条说明它
    到底做到哪一步（见 `CapabilityMatrix`）。

    ## `status` 现在会真的到期

    在这之前 `expires_at` 是一列纯装饰：全仓对这张表的唯一读取是 decide 自己那
    句 `WHERE id=?`，所以一条 approved 会永远停在 approved。实测把
    `expires_at` 拨到 2020 年，`status` 照旧是 approved。
    `list_assistance_requests` 现在会把过期的 pending/approved 落成 expired，
    `GET /v4/assistance/{elder_id}` 是第一个读它的人。
    """

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
