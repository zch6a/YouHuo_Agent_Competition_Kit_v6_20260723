from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import Database
from .models import ActorRole, AuthContext, ReminderRecord, ReminderStatus
from .privacy import task_view
from .utils import new_id
from .v4_models import (
    AssistanceRequestCreate,
    AssistanceRequestRecord,
    CapabilityStatus,
    CareGraph,
    CareGraphEdge,
    CareGraphNode,
    ConsentDecisionRequest,
    ContactCreate,
    ContactRecord,
    DeviceRecord,
    DeviceRegisterRequest,
    DoseRecord,
    DoseRecordRequest,
    EmotionAnalyzeRequest,
    EmotionAnalysis,
    FaceEnrollmentRequest,
    FaceImageRequest,
    FaceMatchResult,
    GeofenceResult,
    HealthEventCreate,
    HealthEventRecord,
    InteractionCheckRequest,
    InteractionCheckResult,
    InventoryForecast,
    ItemMemoryCreate,
    ItemMemoryRecord,
    ItemSearchResponse,
    LocationPingRequest,
    MedicalDocumentRecord,
    MedicalReportAnalysis,
    MedicalReportAnalyzeRequest,
    MedicationPlanCreate,
    MedicationPlanRecord,
    MonthlyReportRequest,
    POIKind,
    POIRecord,
    PrivacyReport,
    RoutineCreate,
    RoutineMaterializeRequest,
    RoutineOccurrence,
    RoutineRecord,
    SafetyPolicyUpdate,
    SOSRequest,
    ActivityHeartbeatRequest,
    InactivityEvaluationRequest,
)
from .v4_services import (
    CapabilityMatrix,
    DemoPOICatalog,
    EmotionAnalyzer,
    FaceTemplateService,
    FamilyAttentionBudget,
    HealthFHIRExporter,
    InventoryService,
    LocationSafety,
    MedicalReportInterpreter,
    MedicationKnowledgeBase,
)
from .v4_store import V4FeatureStore


ActorDependency = Callable[..., AuthContext]

#: 就医单据的四种，翻成人话。
#:
#: `MedicalDocumentKind` 的取值是英文标识（`checkup_report` …），
#: 而它此前被直接拼进健康事件的标题里，家属那一屏上就出现
#: 「checkup_report资料整理」。加一类就要在这里加一条——认不出来的落到
#: 「就医」而不是原样显示，那样至少不会把一个数据库枚举摆到人眼前。
_DOC_KIND_WORDS: dict[str, str] = {
    "checkup_report": "体检报告",
    "discharge_note": "出院小结",
    "prescription": "处方",
    "appointment_notice": "就诊通知",
}


def build_v4_router(
    db: Database,
    store: V4FeatureStore,
    current_actor: ActorDependency,
    medication_kb: MedicationKnowledgeBase,
) -> APIRouter:
    router = APIRouter(prefix="/v4", tags=["YouHuo v4 care platform"])

    def ensure_target(actor: AuthContext, elder_id: str, *, family_allowed: bool = True) -> None:
        if actor.role == ActorRole.ELDER:
            if actor.actor_id != elder_id:
                raise HTTPException(status_code=403, detail="只能访问自己的数据。")
            return
        if actor.role == ActorRole.FAMILY and family_allowed:
            if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
                raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")
            return
        raise HTTPException(status_code=403, detail="当前角色无权访问该功能。")

    def safe_call(func: Callable[[], Any]) -> Any:
        try:
            return func()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # -------------------- recurring routines and monthly事务闭环 --------------------
    @router.post("/routines", response_model=RoutineRecord)
    def create_routine(payload: RoutineCreate, actor: AuthContext = Depends(current_actor)) -> RoutineRecord:
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_routine(actor.family_id, actor.actor_id, payload))
        #: `elder_id` 是给**她那一屏**用的（`privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
        #: 实体号是 `routine-…`，归属判断解析不出来。这是**第二条**建固定安排的路，
        #: `/api/v1/routines` 那条已经带上了——两条都得带，补一条不算补。
        db.append_audit(actor.family_id, actor.actor_id, "ROUTINE_CREATED", record.id, {
            "frequency": record.frequency.value, "category": record.category.value,
            "elder_id": record.elder_id,
        })
        return record

    @router.get("/routines/{elder_id}", response_model=list[RoutineRecord])
    def list_routines(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[RoutineRecord]:
        ensure_target(actor, elder_id)
        return store.list_routines(actor.family_id, elder_id)

    @router.post("/routines/materialize")
    def materialize_routines(
        payload: RoutineMaterializeRequest, actor: AuthContext = Depends(current_actor)
    ) -> dict[str, int]:
        if actor.role not in {ActorRole.FAMILY, ActorRole.SYSTEM}:
            raise HTTPException(status_code=403, detail="循环事务调度仅允许家属或系统触发。")
        result = store.materialize_routines(actor.family_id, payload.now, payload.horizon_days)
        db.append_audit(actor.family_id, actor.actor_id, "ROUTINES_MATERIALIZED", None, result)
        return result

    @router.get("/routine-occurrences/{elder_id}", response_model=list[RoutineOccurrence])
    def list_occurrences(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[RoutineOccurrence]:
        ensure_target(actor, elder_id)
        return store.list_occurrences(actor.family_id, elder_id)

    @router.post("/routine-occurrences/{occurrence_id}/complete", response_model=RoutineOccurrence)
    def complete_occurrence(occurrence_id: str, actor: AuthContext = Depends(current_actor)) -> RoutineOccurrence:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="循环事务应由老人本人确认完成。")
        record = safe_call(lambda: store.complete_occurrence(actor.family_id, actor.actor_id, occurrence_id))
        db.append_audit(actor.family_id, actor.actor_id, "ROUTINE_OCCURRENCE_COMPLETED", occurrence_id, {})
        return record

    # -------------------- privacy-preserving emotional companion --------------------
    @router.post("/emotions/analyze", response_model=EmotionAnalysis,
                 operation_id="analyzeEmotion")
    def analyze_emotion(payload: EmotionAnalyzeRequest, actor: AuthContext = Depends(current_actor)) -> EmotionAnalysis:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        analysis = EmotionAnalyzer.analyze(payload.text)
        if payload.store_event:
            event = store.add_emotion_event(actor.family_id, payload.elder_id, payload.text, payload.source, analysis)
            db.append_audit(actor.family_id, actor.actor_id, "EMOTION_SIGNAL_RECORDED", event.id, {
                "label": analysis.label.value, "distress_band": round(analysis.distress, 1),
                "raw_text_stored": False,
            })
        if analysis.should_notify_family:
            decision = FamilyAttentionBudget.decide("urgent_emotion")
            if decision.deliver_now:
                db.add_notification(
                    actor.family_id, ActorRole.FAMILY, "urgent_emotion",
                    "老人刚说了一句需要马上确认的话，请尽快联系。", payload.elder_id,
                )
        return analysis

    @router.get("/reports/emotion/{elder_id}", response_model=PrivacyReport)
    def emotion_report(
        elder_id: str,
        period_start: date = Query(),
        period_end: date = Query(),
        actor: AuthContext = Depends(current_actor),
    ) -> PrivacyReport:
        ensure_target(actor, elder_id)
        if period_end < period_start or (period_end - period_start).days > 31:
            raise HTTPException(status_code=422, detail="情绪报告周期必须为1至32天。")
        return store.generate_emotion_report(actor.family_id, elder_id, period_start, period_end)

    # -------------------- consent-first item memory --------------------
    @router.post("/items", response_model=ItemMemoryRecord)
    def create_item(payload: ItemMemoryCreate, actor: AuthContext = Depends(current_actor)) -> ItemMemoryRecord:
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_item(actor.family_id, actor.actor_id, payload, actor.role))
        event = "ITEM_MEMORY_ACTIVATED" if record.status == "active" else "ITEM_MEMORY_PROPOSED"
        #: `elder_id` 给她那一屏用。事件名在上一行按状态二选一：
        #: 家人记的是 `PROPOSED`（等她点头），她自己记的直接是 `ACTIVATED`。
        db.append_audit(actor.family_id, actor.actor_id, event, record.id, {
            "category": record.category.value, "scope": record.scope.value,
            "elder_id": record.elder_id,
        })
        if record.status == "proposed":
            db.add_notification(actor.family_id, ActorRole.ELDER, "item_consent_required", "家人建议新增一条实物备忘，请您确认。", record.id)
        return record

    @router.post("/items/decide", response_model=ItemMemoryRecord)
    def decide_item(payload: ConsentDecisionRequest, actor: AuthContext = Depends(current_actor)) -> ItemMemoryRecord:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以批准实物备忘。")
        record = safe_call(lambda: store.decide_item(actor.family_id, actor.actor_id, payload.record_id, payload.approve))
        db.append_audit(actor.family_id, actor.actor_id, "ITEM_MEMORY_DECIDED", record.id, {"approved": payload.approve})
        return record

    @router.get("/items/{elder_id}", response_model=ItemSearchResponse)
    def search_items(
        elder_id: str,
        q: str = Query(min_length=1, max_length=80),
        actor: AuthContext = Depends(current_actor),
    ) -> ItemSearchResponse:
        ensure_target(actor, elder_id)
        matches = store.search_items(actor.family_id, elder_id, q, actor.role)
        active = [item for item in matches if item.status == "active"]
        if not active:
            answer = f"没有找到已获得您同意保存的「{q}」备忘。"
        elif len(active) == 1:
            answer = f"{active[0].label}放在{active[0].location_text}。"
        else:
            answer = "我找到了几条相关备忘：" + "；".join(f"{item.label}在{item.location_text}" for item in active[:5])
        return ItemSearchResponse(query=q, matches=matches, spoken_answer=answer)

    # -------------------- consented contact/face memory --------------------
    @router.post("/contacts", response_model=ContactRecord)
    def create_contact(payload: ContactCreate, actor: AuthContext = Depends(current_actor)) -> ContactRecord:
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_contact(actor.family_id, actor.actor_id, payload, actor.role))
        db.append_audit(actor.family_id, actor.actor_id, "CONTACT_PROFILE_CREATED", record.id, {
            "status": record.status, "scope": record.scope.value, "elder_id": record.elder_id})
        if record.status == "proposed":
            db.add_notification(actor.family_id, ActorRole.ELDER, "contact_consent_required", "家人建议新增一位亲友档案，请您确认。", record.id)
        return record

    @router.post("/contacts/decide", response_model=ContactRecord)
    def decide_contact(payload: ConsentDecisionRequest, actor: AuthContext = Depends(current_actor)) -> ContactRecord:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以批准亲友档案。")
        record = safe_call(lambda: store.decide_contact(actor.family_id, actor.actor_id, payload.record_id, payload.approve))
        db.append_audit(actor.family_id, actor.actor_id, "CONTACT_PROFILE_DECIDED", record.id, {"approved": payload.approve})
        return record

    @router.get("/contacts/{elder_id}", response_model=list[ContactRecord])
    def list_contacts(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[ContactRecord]:
        ensure_target(actor, elder_id)
        return store.list_contacts(actor.family_id, elder_id, actor.role)

    @router.post("/contacts/faces/enroll", response_model=ContactRecord)
    def enroll_face(payload: FaceEnrollmentRequest, actor: AuthContext = Depends(current_actor)) -> ContactRecord:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        try:
            image = payload.image_bytes()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        digest = FaceTemplateService.template(image)
        record = safe_call(lambda: store.enroll_face_digest(actor.family_id, payload.elder_id, payload.contact_id, digest))
        db.append_audit(actor.family_id, actor.actor_id, "FACE_DEMO_TEMPLATE_ENROLLED", record.id, {
            "engine": FaceTemplateService.ENGINE_NAME, "raw_image_stored": False,
        })
        return record

    @router.post("/contacts/faces/match", response_model=FaceMatchResult)
    def match_face(payload: FaceImageRequest, actor: AuthContext = Depends(current_actor)) -> FaceMatchResult:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        try:
            digest = FaceTemplateService.template(payload.image_bytes())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        contact = store.match_face_digest(actor.family_id, payload.elder_id, digest)
        return FaceMatchResult(
            matched=contact is not None,
            contact=contact,
            confidence=1.0 if contact else 0.0,
            engine=FaceTemplateService.ENGINE_NAME,
            production_ready=False,
            warning="当前只验证是否与已登记的同一张图片完全一致，不是真实生物识别，不得用于身份认证。",
        )

    # -------------------- medical reports and longitudinal health archive --------------------
    @router.post("/medical-reports/analyze", response_model=MedicalReportAnalysis,
                 operation_id="analyzeMedicalReport")
    def analyze_medical_report(
        payload: MedicalReportAnalyzeRequest, actor: AuthContext = Depends(current_actor)
    ) -> MedicalReportAnalysis:
        ensure_target(actor, payload.elder_id)
        analysis = MedicalReportInterpreter.analyze(kind=payload.kind, text=payload.text)
        doc_id = store.save_medical_document(actor.family_id, payload.elder_id, payload.source_name, analysis)
        analysis = analysis.model_copy(update={"document_id": doc_id})
        store.create_health_event(
            actor.family_id,
            HealthEventCreate(
                elder_id=payload.elder_id,
                kind="checkup",
                # **界面上不许出现英文枚举值。** 这一行原先是
                # `f"{payload.kind.value}资料整理"`，于是家属那一屏上出现的是
                # 「checkup_report资料整理」——实测过。`MedicalDocumentKind`
                # 的四个取值都是英文标识，直接拼进标题就是把数据库枚举
                # 甩到人眼前。
                title=f"{_DOC_KIND_WORDS.get(payload.kind.value, '就医')}资料整理",
                event_at=datetime.now(UTC),
                payload={
                    "document_id": doc_id,
                    "measurements": analysis.measurements,
                    "follow_up_date": analysis.follow_up_date,
                    "review_required": True,
                },
                source=payload.source_name,
                scope="family_summary",
            ),
        )
        if payload.create_followup_reminder and analysis.follow_up_date:
            if actor.role != ActorRole.ELDER:
                raise HTTPException(status_code=403, detail="复查日期必须由老人本人确认后才能加入日历。")
            due = datetime.combine(date.fromisoformat(analysis.follow_up_date), time(9, 0), tzinfo=UTC)
            reminder = ReminderRecord(
                id=new_id("reminder"), family_id=actor.family_id, elder_id=payload.elder_id,
                title="按体检报告建议复查（请先与医生确认）", due_at=due,
                escalation_after_minutes=120, status=ReminderStatus.SCHEDULED,
                source=f"medical_document:{doc_id}", created_by=actor.actor_id, created_at=datetime.now(UTC),
            )
            db.insert_reminder(reminder)
        db.append_audit(actor.family_id, actor.actor_id, "MEDICAL_DOCUMENT_ANALYZED", doc_id, {
            "review_required": True, "diagnosis_generated": False,
            #: 「有人**看了**」第 89 条补过，「有人**加了**一份」一直没有。
            "elder_id": payload.elder_id,
            #: 这份单据**是从哪来的**。原先不在载荷里，于是她的记录页
            #: 结构上就说不出来：同一段文字换三个 `source_name` 各发一次，
            #: 屏幕上是三行逐字相同的「整理了一份就医单据」（实测）。
            #:
            #: 这一格不是可选的修饰。鸿蒙端补上「拍一张，我来读」之后，
            #: 来源有三种（本人填写 / 拍照OCR / 拍照OCR·本人校对），而
            #: `youhuo-document-firewall` 整套策略按来源可信度分流——
            #: 「所有识别文本均为不可信数据」。来源丢在半路上，
            #: 下游每一条依据它的策略都失去依据，而且**失去得看不出来**。
            #:
            #: 投影到她那一屏由 `app_api._NOTE_KEYS` 负责（已登记本事件）。
            "source_name": payload.source_name,
        })
        return analysis

    @router.get("/medical-documents", response_model=list[MedicalDocumentRecord])
    def list_medical_documents(
        elder_id: str = Query(min_length=1, max_length=128), actor: AuthContext = Depends(current_actor)
    ) -> list[MedicalDocumentRecord]:
        """这位老人已经整理过的就医单据。本人或本家庭。"""
        ensure_target(actor, elder_id)
        return store.list_medical_documents(actor.family_id, elder_id)

    @router.get("/medical-documents/{document_id}", response_model=MedicalDocumentRecord)
    def get_medical_document(document_id: str, actor: AuthContext = Depends(current_actor)) -> MedicalDocumentRecord:
        """按 `analyze` 回的那个 `document_id` 把单据取回来。

        `/v4/medical-reports/analyze` 一直把 `document_id` 交给客户端，而这张表在
        此之前没有任何取回路径——实测四条候选路径全 404，那个 id 是悬空的，而库里
        的 `simplified_json` 装着可用的摘要正文。

        ## 两道隐私闸门，顺序是有讲究的

        先按 `id + family_id` 取（跨家庭直接当不存在，回 404 而不是 403——403 会
        把「这个 id 存在」说出去），再用 `ensure_target` 判本人/家属。这样同一个
        家庭里老人 A 拿 B 的 id，得到的是 403「只能访问自己的数据。」，与仓库其余
        地方一致；而外人拿到的是 404。

        家属可读，是因为创建它的 `/v4/medical-reports/analyze` 走的就是
        `ensure_target`——家属替老人拍单据是真实场景。让创建得到、取回拿不到，
        会逼着前端自己把内容存一份，那才是真的漏。

        ## 不绕过删除

        读的是 `medical_documents_v4` 本表。`/v5/privacy` 把 `medical_documents`
        列为可删类别，`privacy_erase` 是真的 DELETE；删完这条路由就是 404。
        """
        record = store.get_medical_document(actor.family_id, document_id)
        if record is None:
            raise HTTPException(status_code=404, detail="这份就医资料不存在，或者已经删除了。")
        ensure_target(actor, record.elder_id)
        db.append_audit(actor.family_id, actor.actor_id, "MEDICAL_DOCUMENT_READ", record.id, {
            # `elder_id` 要写进来：老人端二的记录页靠「载荷里点名了她」才敢把
            # **别人做的**这条留给她看（`privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
            # 少了它，家属取走她的就医单据，她那一屏一个字都没有。
            # 和 `BREAK_GLASS_VIEWED` 是同一处形状。
            "elder_id": record.elder_id,
            "kind": record.kind.value,
        })
        return record

    @router.post("/health/events", response_model=HealthEventRecord)
    def create_health_event(payload: HealthEventCreate, actor: AuthContext = Depends(current_actor)) -> HealthEventRecord:
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_health_event(actor.family_id, payload))
        db.append_audit(actor.family_id, actor.actor_id, "HEALTH_EVENT_CREATED", record.id, {
            "kind": record.kind.value, "scope": record.scope.value,
            #: `elder_id` 是给**她那一屏**用的。这是记身体数据的
            #: **第二条**路（家人替她记），`/api/v1/health/events` 那条
            #: 已经带上了——两条都得带。
            "elder_id": payload.elder_id,
        })
        return record

    @router.get("/health/events/{elder_id}", response_model=list[HealthEventRecord])
    def list_health_events(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[HealthEventRecord]:
        ensure_target(actor, elder_id)
        return store.list_health_events(actor.family_id, elder_id, actor.role)

    @router.get("/health/fhir/{elder_id}")
    def export_fhir(elder_id: str, actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        ensure_target(actor, elder_id)
        health, meds = store.raw_health_rows(actor.family_id, elder_id)
        return HealthFHIRExporter.bundle(elder_id=elder_id, health_events=health, medication_plans=meds)

    # -------------------- medication plans, adherence, stock and interaction guard --------------------
    @router.post("/medications", response_model=MedicationPlanRecord)
    def create_medication(payload: MedicationPlanCreate, actor: AuthContext = Depends(current_actor)) -> MedicationPlanRecord:
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_medication_plan(actor.family_id, payload, actor.role))
        event = "MEDICATION_PLAN_ACTIVATED" if record.active else "MEDICATION_PLAN_PROPOSED"
        #: `elder_id` 是给**她那一屏**用的（`privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
        #: 实体号是 `medplan-…`，归属判断解析不出来；这两种事又都可能是家属做的，
        #: 少了这个字段，家人给她加的用药计划在她自己那一屏上不存在。
        db.append_audit(actor.family_id, actor.actor_id, event, record.id,
                        {"source": record.source, "elder_id": record.elder_id})
        if not record.active:
            db.add_notification(actor.family_id, ActorRole.ELDER, "medication_consent_required", "家人补充了一条用药计划，请您核对后确认。", record.id)
        return record

    @router.post("/medications/decide", response_model=MedicationPlanRecord)
    def decide_medication(payload: ConsentDecisionRequest, actor: AuthContext = Depends(current_actor)) -> MedicationPlanRecord:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以激活家属补充的用药计划。")
        record = safe_call(lambda: store.approve_medication_plan(actor.family_id, actor.actor_id, payload.record_id, payload.approve))
        db.append_audit(actor.family_id, actor.actor_id, "MEDICATION_PLAN_DECIDED", payload.record_id, {"approved": payload.approve})
        return record

    @router.get("/medications/{elder_id}", response_model=list[MedicationPlanRecord])
    def list_medications(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[MedicationPlanRecord]:
        ensure_target(actor, elder_id)
        return store.list_medication_plans(actor.family_id, elder_id)

    @router.post("/medications/{plan_id}/doses", response_model=DoseRecord)
    def record_dose(
        plan_id: str, payload: DoseRecordRequest, actor: AuthContext = Depends(current_actor)
    ) -> DoseRecord:
        if actor.role not in {ActorRole.ELDER, ActorRole.FAMILY}:
            raise HTTPException(status_code=403, detail="只有老人或绑定家属可以记录服药状态。")
        plan = store.get_medication_plan(plan_id)
        if not plan or plan.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="用药计划不存在。")
        if actor.role == ActorRole.ELDER and plan.elder_id != actor.actor_id:
            raise HTTPException(status_code=403, detail="只能记录自己的服药状态。")
        if not plan.active:
            raise HTTPException(status_code=409, detail="用药计划尚未获得老人确认。")
        return safe_call(lambda: store.record_dose(actor.family_id, actor.actor_id, plan_id, payload))

    @router.get("/medications/{plan_id}/inventory", response_model=InventoryForecast)
    def medication_inventory(plan_id: str, actor: AuthContext = Depends(current_actor)) -> InventoryForecast:
        """这份药还能吃几天，**以及该说的那句话**。

        `message` / `should_highlight` / `whole_days_remaining` 是后端算好的结论，
        前端直接用。加它们的原因：`backend/static/care.js` 的 `daysLeft()` 用 JS
        把天数重算了一遍，红字阈值自己定成 `days <= 3`，而后端 warning 的线是
        7 天。实测同一份计划（11 片、每天 2 片）：后端 `alert_level` 是 warning、
        发了家属通知，屏幕上却是普通灰字「还够 5 天」——家属手机响了，老人这边
        看不出任何异常。阈值现在只在 `InventoryService` 里有一份。

        care.js 那一侧还要有人去接：把 `daysLeft()` 和 `days <= 3` 删掉，改读这
        三个字段。那个文件不在这次的改动范围里。
        """
        plan = store.get_medication_plan(plan_id)
        if not plan or plan.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="用药计划不存在。")
        ensure_target(actor, plan.elder_id)
        forecast = InventoryService.forecast(
            plan_id=plan.id, stock_units=plan.stock_units, units_per_dose=plan.units_per_dose,
            doses_per_day=len(plan.times_local), today=datetime.now(UTC).date(),
        )
        if forecast.should_highlight:
            # 这是一个 GET，而它写通知。刷新一次列表就多一条。
            # 实测连打 5 次这个端点，家属收件箱里躺着 5 条一模一样的
            # 「钙片库存预计不足，请核对补充。」——库存并没有变化，变化的只是
            # 她刷了几次。所以同一份计划只要还有一条没读的，就不再补第二条。
            #
            # 按 `entity_id` 而不是按消息文本去重：文本里带药名，改一次话术就
            # 会让去重悄悄失效。
            already_waiting = any(
                note.event_type == "medication_inventory" and note.entity_id == plan.id and note.read_at is None
                for note in db.list_notifications(actor.family_id, ActorRole.FAMILY, limit=200)
            )
            if not already_waiting:
                db.add_notification(
                    actor.family_id, ActorRole.FAMILY, "medication_inventory",
                    f"{plan.display_name}{forecast.message}", plan.id,
                )
        return forecast

    @router.post("/medications/interactions/check", response_model=InteractionCheckResult,
                 operation_id="checkMedicationInteractions")
    def check_interactions(
        payload: InteractionCheckRequest, actor: AuthContext = Depends(current_actor)
    ) -> InteractionCheckResult:
        result = medication_kb.check(payload.medication_names)
        db.append_audit(actor.family_id, actor.actor_id, "MEDICATION_INTERACTION_DEMO_CHECK", None, {
            "medication_count": len(result.normalized_medications), "finding_count": len(result.findings),
            "clinical_decision_made": False,
        })
        return result

    # -------------------- home safety, inactivity, SOS, location and navigation --------------------
    @router.put("/safety/policy")
    def update_safety_policy(payload: SafetyPolicyUpdate, actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        ensure_target(actor, payload.elder_id)
        result = safe_call(lambda: store.upsert_safety_policy(actor.family_id, payload))
        db.append_audit(actor.family_id, actor.actor_id, "SAFETY_POLICY_UPDATED", payload.elder_id, {
            "geofence_enabled": payload.home_lat is not None, "notify_community": payload.notify_community,
        })
        return result

    @router.get("/safety/policy/{elder_id}")
    def get_safety_policy(elder_id: str, actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        ensure_target(actor, elder_id)
        return store.get_safety_policy(actor.family_id, elder_id)

    @router.post("/safety/heartbeat")
    def heartbeat(payload: ActivityHeartbeatRequest, actor: AuthContext = Depends(current_actor)) -> dict[str, str]:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        # 不再传 `payload.metadata`：那个字段已经从模型里去掉了，
        # 理由见 `v4_models.ActivityHeartbeatRequest` 的 docstring。
        event_id = safe_call(lambda: store.add_activity(actor.family_id, payload.elder_id, payload.kind, payload.occurred_at))
        return {"event_id": event_id, "status": "recorded"}

    @router.post("/safety/inactivity/evaluate")
    def inactivity_evaluate(
        payload: InactivityEvaluationRequest, actor: AuthContext = Depends(current_actor)
    ) -> list[dict[str, Any]]:
        if actor.role not in {ActorRole.FAMILY, ActorRole.SYSTEM}:
            raise HTTPException(status_code=403, detail="无交互巡检仅允许家属或系统触发。")
        return store.evaluate_inactivity(actor.family_id, payload.now)

    @router.post("/safety/sos")
    def sos(payload: SOSRequest, actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        policy = store.get_safety_policy(actor.family_id, payload.elder_id)
        contacts = store.safety_contacts(
            actor.family_id, payload.elder_id,
            include_community=bool(payload.include_community and policy.get("notify_community")),
        )
        message = "老人主动呼救，请立即联系确认。"
        if payload.latitude is not None and payload.longitude is not None:
            message += " 已附带经老人授权的本次位置。"
        db.add_notification(actor.family_id, ActorRole.FAMILY, "sos", message, payload.elder_id)
        db.append_audit(actor.family_id, actor.actor_id, "SOS_TRIGGERED", payload.elder_id, {
            "community_escalation_count": sum(1 for item in contacts if item["contact_role"] == "community"),
            "location_included": payload.latitude is not None,
        })
        return {
            "family_notified": True,
            "community_escalation_prepared": any(item["contact_role"] == "community" for item in contacts),
            "contacts": contacts,
            "message": "求助已进入最高优先级接力流程。比赛原型不会自动拨打公共紧急电话。",
        }

    @router.post("/location/ping", response_model=GeofenceResult,
                 operation_id="evaluateLocationSafety")
    def location_ping(payload: LocationPingRequest, actor: AuthContext = Depends(current_actor)) -> GeofenceResult:
        ensure_target(actor, payload.elder_id, family_allowed=False)
        store.add_location(
            actor.family_id, payload.elder_id, payload.latitude, payload.longitude,
            payload.accuracy_m, payload.occurred_at, payload.source,
        )
        policy = store.get_safety_policy(actor.family_id, payload.elder_id)
        result = LocationSafety.evaluate_geofence(
            latitude=payload.latitude, longitude=payload.longitude, accuracy_m=payload.accuracy_m,
            home_lat=policy.get("home_lat"), home_lon=policy.get("home_lon"),
            radius_m=int(policy.get("geofence_radius_m", 1500)),
        )
        if result.alert_created:
            decision = FamilyAttentionBudget.decide("geofence_exit")
            if decision.deliver_now:
                db.add_notification(actor.family_id, ActorRole.FAMILY, "geofence_exit", result.message, payload.elder_id)
                #: **告诉了家人，就要给她留一行。**
                #:
                #: 隔壁 SOS 那一路是这么做的：通知家人 + 写 `SOS_TRIGGERED`，
                #: 她的记录上于是有「您按了紧急求助，已经通知家人。」。
                #: 这一路原先只发通知：实测她走到 14 公里外，家人收到
                #: 「检测到设备超出已授权的日常活动范围…」，而她自己那一屏
                #: **一行都没有**。同一件事（把她的情况告诉家人），两种做法。
                #:
                #: 只在**真发出去**的时候写（`deliver_now`）：注意力预算把这一条
                #: 压下去的时候，家人并没有被打扰，也就没什么要告诉她的。
                #: 每次定位都写才是另一个方向的错——她的记录会被位置刷满，
                #: 底下那条判据专门钉住「在范围内不写」。
                db.append_audit(
                    actor.family_id, actor.actor_id, "GEOFENCE_ALERT_RAISED",
                    payload.elder_id,
                    {"elder_id": payload.elder_id,
                     "distance_m": int(result.distance_from_home_m)},
                )
        return result

    @router.get("/navigation/nearby", response_model=list[POIRecord])
    def nearby_poi(
        latitude: float = Query(ge=-90, le=90),
        longitude: float = Query(ge=-180, le=180),
        kind: POIKind = Query(),
        actor: AuthContext = Depends(current_actor),
    ) -> list[POIRecord]:
        del actor
        return DemoPOICatalog.nearby(latitude=latitude, longitude=longitude, kind=kind)

    # -------------------- cross-brand account/device and bounded remote assistance --------------------
    @router.post("/devices", response_model=DeviceRecord)
    def register_device(payload: DeviceRegisterRequest, actor: AuthContext = Depends(current_actor)) -> DeviceRecord:
        if payload.actor_id != actor.actor_id:
            raise HTTPException(status_code=403, detail="只能登记当前登录账户正在使用的设备。")
        record = safe_call(lambda: store.register_device(actor.family_id, payload))
        db.append_audit(actor.family_id, actor.actor_id, "DEVICE_REGISTERED", record.device_id, {
            "platform": record.platform, "brand": record.brand, "trust": record.trust_level,
        })
        return record

    @router.get("/devices", response_model=list[DeviceRecord])
    def list_devices(actor: AuthContext = Depends(current_actor)) -> list[DeviceRecord]:
        return store.list_devices(actor.family_id)

    @router.post("/assistance", response_model=AssistanceRequestRecord)
    def create_assistance(
        payload: AssistanceRequestCreate, actor: AuthContext = Depends(current_actor)
    ) -> AssistanceRequestRecord:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="只有绑定家属可以请求远程协助。")
        ensure_target(actor, payload.elder_id)
        record = safe_call(lambda: store.create_assistance_request(
            actor.family_id, actor.actor_id, payload.elder_id,
            payload.requested_capabilities, payload.expires_in_minutes,
        ))
        # 这句话原先是「家人请求短时远程协助，请您确认。」——它承诺了这一版做不到的事。
        #
        # 那四个能力名（查看当前这一步 / 语音指导 / 控件高亮 / 低风险表单提交）在全仓
        # 只出现在白名单校验里，没有任何能力闸门读这条同意。实测：请求、同意、
        # status 变 approved，然后什么都不会发生。老人读到「远程协助」，合理的理解是
        # 女儿接下来能在她屏幕上做点什么；而她点完同意，屏幕上不会有任何变化。
        #
        # 为什么不是补上那条通道，而是改措辞：见 `AssistanceRequestRecord` 的注释
        # （没有服务端到设备的推送/长连接；代为提交是这个仓库特意禁止的方向；
        # 「查看当前这一步」家属现在就能看，不需要授权）。
        #
        # 改成说实话：说清有效期、说清系统不会替家属动手，并且**不说**它会做什么。
        minutes = max(1, int((record.expires_at - record.created_at).total_seconds() // 60))
        db.add_notification(
            actor.family_id, ActorRole.ELDER, "assistance_consent_required",
            f"家人想在接下来 {minutes} 分钟里帮您弄一件事，问您同不同意。"
            "同意只是记下这次约定，优活不会替家人动您的屏幕、也不会替您提交任何东西；"
            "真要帮忙还是得通电话。",
            record.id,
        )
        #: **请求这一步也要留痕**，不只留她的回答。
        #:
        #: 原先这里只发一条通知就返回了：审计链上只有她点头之后的
        #: `ASSISTANCE_DECIDED`。于是她读自己的记录，看到的是
        #: 「决定了一次远程协助」——**前面没有任何人问过她**，
        #: 一个回答凭空出现，看不出是谁提的、什么时候提的。
        #: 这个形状本仓修过一次（记忆提议那一批），这一处漏了。
        #:
        #: `elder_id` 是给她那一屏用的：实体号是 `assist-…`，归属判断解析不出来，
        #: 而动作人是家属，不带上她就会被「动作不是她做的」丢掉
        #: （见 `privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
        db.append_audit(
            actor.family_id, actor.actor_id, "ASSISTANCE_REQUESTED", record.id,
            {"elder_id": payload.elder_id, "minutes": minutes},
        )
        return record

    @router.post("/assistance/decide", response_model=AssistanceRequestRecord)
    def decide_assistance(
        payload: ConsentDecisionRequest, actor: AuthContext = Depends(current_actor)
    ) -> AssistanceRequestRecord:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以批准远程协助。")
        record = safe_call(lambda: store.decide_assistance(
            actor.family_id, actor.actor_id, payload.record_id, payload.approve,
        ))
        db.append_audit(actor.family_id, actor.actor_id, "ASSISTANCE_DECIDED", record.id, {
            "approved": payload.approve, "capabilities": record.requested_capabilities,
        })
        return record

    @router.get("/assistance/{elder_id}", response_model=list[AssistanceRequestRecord])
    def list_assistance(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[AssistanceRequestRecord]:
        """这户人家的远程协助请求，老人和绑定家属都能查。

        在这条路由之前，`assistance_requests_v4` 是一张只写表：唯一的读取是
        `decide_assistance` 自己那句 `WHERE id=?`。实测 `GET /v4/assistance` 是
        405、`GET /v4/assistance/{id}` 是 404，零 UI 消费方。两个后果：老人点完
        同意查不到自己同意了什么，以及 `expires_at` 永远不生效（把一条 approved
        的到期时间拨到 2020 年，status 照旧是 approved）。

        这里按 `elder_id` 取而不是按 `request_id`：`request_id` 只有刚发过请求的
        那一端知道，而需要「我同意过什么」这份清单的是老人。过期在
        `list_assistance_requests` 里落库。
        """
        ensure_target(actor, elder_id)
        return store.list_assistance_requests(actor.family_id, elder_id)

    # -------------------- reports, care graph and capability truth table --------------------
    @router.post("/reports/monthly", response_model=PrivacyReport,
                 operation_id="generateMonthlyReport")
    def monthly_report(payload: MonthlyReportRequest, actor: AuthContext = Depends(current_actor)) -> PrivacyReport:
        ensure_target(actor, payload.elder_id)
        return store.monthly_report(actor.family_id, payload.elder_id, payload.year, payload.month)

    @router.get("/care-graph/{elder_id}", response_model=CareGraph)
    def care_graph(elder_id: str, actor: AuthContext = Depends(current_actor)) -> CareGraph:
        ensure_target(actor, elder_id)
        nodes: list[CareGraphNode] = []
        edges: list[CareGraphEdge] = []
        for task in db.list_tasks(actor.family_id, limit=100):
            if task.elder_id != elder_id:
                continue
            view = task_view(task)
            node_id = f"task:{task.id}"
            nodes.append(CareGraphNode(
                id=node_id, kind="task", label=view.summary, occurred_at=task.created_at,
                risk=str(int(task.risk_level)), metadata={"status": task.status.value, "type": task.task_type.value},
            ))
        for occurrence in store.list_occurrences(actor.family_id, elder_id)[:100]:
            node_id = f"routine:{occurrence.id}"
            nodes.append(CareGraphNode(
                id=node_id, kind="routine_occurrence", label="循环事务", occurred_at=occurrence.due_at,
                risk="low", metadata={"status": occurrence.status.value, "routine_id": occurrence.routine_id},
            ))
        for event in store.list_health_events(actor.family_id, elder_id, actor.role)[:100]:
            node_id = f"health:{event.id}"
            nodes.append(CareGraphNode(
                id=node_id, kind="health", label=event.title, occurred_at=event.event_at,
                risk="sensitive", metadata={"kind": event.kind.value, "scope": event.scope.value},
            ))
        for plan in store.list_medication_plans(actor.family_id, elder_id)[:50]:
            node_id = f"medication:{plan.id}"
            nodes.append(CareGraphNode(
                id=node_id, kind="medication", label=plan.display_name, occurred_at=plan.created_at,
                risk="sensitive", metadata={"active": plan.active, "times": plan.times_local},
            ))
        # Conservative relation generation: link health events to active medication plans, without exposing raw medical text.
        health_ids = [node.id for node in nodes if node.kind == "health"]
        medication_ids = [node.id for node in nodes if node.kind == "medication"]
        for health_id in health_ids[-20:]:
            for medication_id in medication_ids[-20:]:
                edges.append(CareGraphEdge(source=health_id, target=medication_id, relation="contextual_health_management"))
        return CareGraph(elder_id=elder_id, nodes=nodes[:300], edges=edges[:400], generated_at=datetime.now(UTC))

    @router.get("/capabilities", response_model=list[CapabilityStatus])
    def capabilities(actor: AuthContext = Depends(current_actor)) -> list[CapabilityStatus]:
        del actor
        return [CapabilityStatus.model_validate(item) for item in CapabilityMatrix.all()]

    return router
