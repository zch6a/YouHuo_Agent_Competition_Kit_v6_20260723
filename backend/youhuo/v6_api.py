from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import Database
from .models import ActorRole, AuthContext
from .tts import NeuralVoice
from .utils import clean_user_text
from .v6_models import (
    CompetitionEvidenceBoard,
    InteractionPlan,
    InteractionPlanRequest,
    InteractionProfile,
    InteractionProfileUpdate,
    RelianceCard,
    RelianceCardRequest,
    SafePreview,
    SafePreviewRequest,
    SemanticFrame,
    SemanticParseRequest,
    StudyObservation,
    StudyObservationCreate,
    StudySession,
    StudySessionCreate,
    StudySummary,
    TaskGlassBox,
    TaskGlassBoxRequest,
)
from .v6_services import (
    CognitiveLoadGovernor,
    CompetitionEvidenceService,
    RelianceCardService,
    SafePreviewService,
    SemanticGateway,
    StudySummaryService,
    TaskGlassBoxService,
)
from .v6_store import V6FeatureStore


#: How fast an older observation stops counting. 0.7 means the most recent
#: attempt carries ~3x the weight of one three attempts ago, so support eases
#: off within a few good turns instead of holding a grudge.
_RECENCY_DECAY = 0.7

#: A wrong number is stronger evidence of misunderstanding than simply not
#: restating, which is often just not knowing what was expected.
_MISS_WEIGHT = {"mismatch": 1.0, "not_restated": 0.5, "verified": 0.0}


def _difficulty_from(summary: dict) -> float:
    """Recency-weighted 0-1 difficulty from observed teach-back outcomes.

    With no observations the difficulty is zero, so a new elder is never
    pre-judged as struggling.
    """
    signals = summary.get("recent_signals") or []
    if not signals:
        return 0.0
    weighted_miss = 0.0
    total_weight = 0.0
    for index, signal in enumerate(signals):
        weight = _RECENCY_DECAY ** index
        weighted_miss += weight * _MISS_WEIGHT.get(signal, 0.0)
        total_weight += weight
    return round(min(1.0, weighted_miss / total_weight), 6) if total_weight else 0.0


class SpeechSynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=300)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)

    @field_validator("text")
    @classmethod
    def clean(cls, value: str) -> str:
        return clean_user_text(value, max_length=300)


def build_v6_router(
    db: Database,
    store: V6FeatureStore,
    current_actor: Callable[..., AuthContext],
    voice: NeuralVoice | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v6", tags=["v6 age-inclusive agent and competition evidence"])

    def require_elder_access(actor: AuthContext, elder_id: str) -> None:
        if actor.role == ActorRole.ELDER and actor.actor_id != elder_id:
            raise HTTPException(status_code=403, detail="只能访问自己的适老交互数据。")
        if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
            raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")

    @router.get("/profiles/{elder_id}", response_model=InteractionProfile)
    def get_profile(elder_id: str, actor: AuthContext = Depends(current_actor)) -> InteractionProfile:
        require_elder_access(actor, elder_id)
        return store.get_profile(actor.family_id, elder_id)

    @router.put("/profiles/{elder_id}", response_model=InteractionProfile)
    def update_profile(
        elder_id: str,
        payload: InteractionProfileUpdate,
        actor: AuthContext = Depends(current_actor),
    ) -> InteractionProfile:
        require_elder_access(actor, elder_id)
        if payload.elder_id != elder_id:
            raise HTTPException(status_code=400, detail="路径中的老人ID与请求内容不一致。")
        if actor.role == ActorRole.FAMILY and payload.teach_back_high_risk is False:
            raise HTTPException(status_code=403, detail="家属不能替老人关闭高风险复述确认。")
        profile = store.upsert_profile(actor.family_id, actor, payload)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "INTERACTION_PROFILE_UPDATED",
            elder_id,
            {
                "version": profile.version,
                "speech_rate": profile.speech_rate,
                "max_options": profile.max_options,
                "max_sentence_chars": profile.max_sentence_chars,
                "teach_back_high_risk": profile.teach_back_high_risk,
            },
        )
        return profile

    @router.post("/interaction/plan", response_model=InteractionPlan)
    def interaction_plan(
        payload: InteractionPlanRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> InteractionPlan:
        require_elder_access(actor, payload.elder_id)
        profile = store.get_profile(actor.family_id, payload.elder_id)
        # Difficulty comes from stored teach-back outcomes, never from the
        # client: a caller must not be able to talk the governor into relaxing.
        summary = db.comprehension_summary(actor.family_id, payload.elder_id)
        payload = payload.model_copy(
            update={"comprehension_difficulty": _difficulty_from(summary)}
        )
        plan = CognitiveLoadGovernor.plan(profile, payload)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "COGNITIVE_LOAD_PLAN_CREATED",
            payload.elder_id,
            {
                "mode": plan.mode,
                "score": plan.cognitive_load_score,
                "teach_back": plan.require_teach_back,
                "visible_options": len(plan.visible_options),
                "plan_digest": plan.plan_digest,
            },
        )
        return plan

    @router.post("/reliance/card", response_model=RelianceCard)
    def reliance_card(
        payload: RelianceCardRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> RelianceCard:
        require_elder_access(actor, payload.elder_id)
        card = RelianceCardService.build(payload)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "RELIANCE_CARD_CREATED",
            payload.elder_id,
            {"card_digest": card.card_digest, "risk_level": payload.risk_level, "action": payload.action},
        )
        return card

    @router.post("/actions/preview", response_model=SafePreview)
    def safe_preview(
        payload: SafePreviewRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SafePreview:
        require_elder_access(actor, payload.elder_id)
        preview = SafePreviewService.preview(payload)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "SAFE_ACTION_PREVIEWED",
            payload.elder_id,
            {
                "action": payload.action,
                "decision": preview.authorization.decision.value,
                "preview_digest": preview.preview_digest,
                "stripped_fields": preview.authorization.stripped_fields,
            },
        )
        return preview

    @router.post("/tasks/{task_id}/glass-box", response_model=TaskGlassBox)
    def task_glass_box(
        task_id: str,
        payload: TaskGlassBoxRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> TaskGlassBox:
        """Glass-box card and safe preview for one real task (design §4.3)."""
        task = db.get_task(task_id)
        if task is None or task.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="任务不存在或不属于当前家庭。")
        require_elder_access(actor, task.elder_id)
        glass_box = TaskGlassBoxService.build(
            task,
            payload.heard_text,
            family_approvals=db.count_approval_votes(task.id),
        )
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "RELIANCE_CARD_CREATED",
            task.id,
            {
                "card_digest": glass_box.card.card_digest,
                "risk_level": int(task.risk_level),
                "action": glass_box.action_label,
                "policy_action": glass_box.policy_action,
                "preview_decision": glass_box.preview.authorization.decision.value if glass_box.preview else None,
            },
        )
        return glass_box

    @router.post("/semantic/parse", response_model=SemanticFrame)
    def semantic_parse(
        payload: SemanticParseRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SemanticFrame:
        require_elder_access(actor, payload.elder_id)
        frame = SemanticGateway.parse(payload)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "SEMANTIC_FRAME_PARSED",
            payload.elder_id,
            {
                "intent": frame.intent,
                "confidence": frame.confidence,
                "needs_clarification": frame.needs_clarification,
                "parser_source": frame.parser_source,
                "model_used": frame.model_used,
                "frame_digest": frame.frame_digest,
                "safety_flags": frame.safety_flags,
            },
        )
        return frame

    @router.post("/studies/sessions", response_model=StudySession)
    def create_study_session(
        payload: StudySessionCreate,
        actor: AuthContext = Depends(current_actor),
    ) -> StudySession:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="只有项目研究人员/家属演示角色可以登记知情同意实验。")
        try:
            session = store.create_study_session(actor.family_id, actor, payload)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "USER_STUDY_SESSION_CREATED",
            session.id,
            {"participant_code": session.participant_code, "role": session.role.value, "consent_version": session.consent_version},
        )
        return session

    @router.get("/studies/sessions", response_model=list[StudySession])
    def list_study_sessions(actor: AuthContext = Depends(current_actor)) -> list[StudySession]:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="用户实验记录只向授权研究角色开放。")
        return store.list_study_sessions(actor.family_id)

    @router.post("/studies/observations", response_model=StudyObservation)
    def add_study_observation(
        payload: StudyObservationCreate,
        actor: AuthContext = Depends(current_actor),
    ) -> StudyObservation:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="用户实验记录只向授权研究角色开放。")
        try:
            observation = store.add_observation(actor.family_id, actor, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "USER_STUDY_OBSERVATION_ADDED",
            observation.id,
            {
                "session_id": observation.session_id,
                "scenario": observation.scenario,
                "success": observation.success,
                "duration_seconds": observation.duration_seconds,
            },
        )
        return observation

    @router.get("/studies/summary", response_model=StudySummary)
    def study_summary(actor: AuthContext = Depends(current_actor)) -> StudySummary:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="用户实验汇总只向授权研究角色开放。")
        return StudySummaryService.summarize(
            store.list_study_sessions(actor.family_id),
            store.list_observations(actor.family_id),
        )

    @router.get("/comprehension/{elder_id}")
    def comprehension(elder_id: str, actor: AuthContext = Depends(current_actor)) -> dict:
        """Observed teach-back outcomes driving the interaction governor.

        Outcome labels only - never what the elder said - so the family can see
        that support is adapting without reading the conversation.
        """
        require_elder_access(actor, elder_id)
        summary = db.comprehension_summary(actor.family_id, elder_id)
        difficulty = _difficulty_from(summary)
        # The raw signal list is an implementation detail of the weighting.
        summary.pop("recent_signals", None)
        return {
            **summary,
            "difficulty": difficulty,
            "adapting": difficulty >= 0.34,
            "note": "按时间衰减加权，最近几次表现权重最高；仅记录复述结果标签，"
                    "不保存老人说过的原话。样本很少时不足以代表长期能力。",
        }

    @router.get("/speech/voice")
    def speech_voice(actor: AuthContext = Depends(current_actor)) -> dict:
        """Whether an offline neural voice is available; the client degrades if not."""
        del actor
        return voice.status() if voice else {
            "available": False, "engine": None, "model": None,
            "package_installed": False, "model_present": False, "load_error": None,
            "fallback": "browser_speech_synthesis",
            "note": "未启用离线本地合成，使用浏览器语音。",
        }

    @router.post(
        "/speech/synthesize",
        responses={200: {"content": {"audio/wav": {}}, "description": "16-bit PCM WAV"}},
    )
    def speech_synthesize(
        payload: SpeechSynthesizeRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> Response:
        """Synthesize one already-normalised clause locally. Never leaves the machine."""
        del actor
        if voice is None or not voice.available:
            raise HTTPException(status_code=503, detail="离线语音未启用，请使用浏览器语音。")
        try:
            wav, sample_rate = voice.synthesize(payload.text, payload.speed)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=wav,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "X-Sample-Rate": str(sample_rate)},
        )

    @router.get("/competition/evidence", response_model=CompetitionEvidenceBoard)
    def competition_evidence(actor: AuthContext = Depends(current_actor)) -> CompetitionEvidenceBoard:
        del actor
        return CompetitionEvidenceService.board()

    return router
