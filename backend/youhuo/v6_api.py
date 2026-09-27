from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import Database
from .deciders import ROUTE_THRESHOLDS, decide_chain
from .cloud_voice import VoiceChain, media_type_of
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


#: 这几个开关只有老人本人能关——家属可以看，可以打开，不能关。
#:
#: 键是 `InteractionProfileUpdate` 上的字段名，值是说给人听的名字。
#: 单独列成一张表，是因为原先那道守卫只点了 `teach_back_high_risk`
#: 一个名字，兄弟 `repeat_sensitive` 从旁边过去了（实测家属关得掉）。
ELDER_ONLY_SAFETY_FLAGS: dict[str, str] = {
    "teach_back_high_risk": "高风险复述确认",
    "repeat_sensitive": "听不清时的重复确认",
}
_ELDER_ONLY_SAFETY_FLAGS = ELDER_ONLY_SAFETY_FLAGS


class DecideRequest(BaseModel):
    """把老人的一句话交给决策链。**只问判断，不执行任何动作。**

    这个端点是只读的：它跑一遍四个决策器、按阈值路由出三态，
    然后把**完整的概率分布**和**用了哪根线**一起交回来。
    要不要真的去办，由调用方拿这个结果自己决定——
    决策器不碰数据库、不发请求、不改任何状态。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    task_type: str | None = None
    risk_level: int | None = Field(default=None, ge=1, le=4)
    has_errand_slot: bool = False
    elder_said_not_to: bool = False
    urgent: bool = False

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        #: 走和别处同一个清洗函数（NFKC + 去控制字符），**上限和 Field 一致**。
        #: `clean_user_text` 的 `max_length` 是 keyword-only 且必填——
        #: 第一版漏了它，端点一调用就 TypeError。
        return clean_user_text(value, max_length=200)


class DecideResponse(BaseModel):
    """一条链的完整结果。**概率分布一起交出去**，不是只给一个结论。

    Jev 文档里那句："完整概率都给你了，可以自己算"——所以这里给的是
    `intent_probabilities` 这样的整张表，而不只是 `intent` 一个词。
    调用方想换一种 confidence 定义、或者想按自己的水位卡，都拿得到原料。
    """

    headline: str
    intent: str
    intent_confidence: float
    intent_probabilities: dict[str, float]
    risk: str
    risk_confidence: float
    risk_probabilities: dict[str, float]
    grasp: float
    interrupt: str
    interrupt_probabilities: dict[str, float]
    action_key: str
    triage: str
    thresholds: tuple[float | None, float]
    notes: list[str]


def build_v6_router(
    db: Database,
    store: V6FeatureStore,
    current_actor: Callable[..., AuthContext],
    voice: VoiceChain | NeuralVoice | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v6", tags=["v6 age-inclusive agent and competition evidence"])

    def require_elder_access(actor: AuthContext, elder_id: str) -> None:
        if actor.role == ActorRole.ELDER and actor.actor_id != elder_id:
            raise HTTPException(status_code=403, detail="只能访问自己的适老交互数据。")
        if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
            raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")

    @router.post("/decide", response_model=DecideResponse)
    def decide(
        payload: DecideRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> DecideResponse:
        """跑一遍决策链，把判断过程和依据一起交回来。

        **这是只读的**：不落库、不发外部请求、不改任何状态。
        它回答的是"该怎么处理这句话"，不是"去办这件事"。

        放在 `/v6` 而不是新开一个前缀，是因为它服务的正是这一版
        「适老交互」那条线——小优每次开口之前先过一遍这里。
        """
        chain = decide_chain(
            payload.text,
            task_type=payload.task_type,
            risk_level=payload.risk_level,
            has_errand_slot=payload.has_errand_slot,
            elder_said_not_to=payload.elder_said_not_to,
            urgent=payload.urgent,
        )
        return DecideResponse(
            headline=chain.headline,
            intent=chain.intent.choice,
            intent_confidence=chain.intent.confidence,
            intent_probabilities=dict(chain.intent.probabilities),
            risk=chain.risk.score,
            risk_confidence=chain.risk.confidence,
            risk_probabilities=dict(chain.risk.probabilities),
            grasp=chain.grasp.value,
            interrupt=chain.interrupt.choice,
            interrupt_probabilities=dict(chain.interrupt.probabilities),
            action_key=chain.action_key,
            triage=chain.triage.value,
            thresholds=ROUTE_THRESHOLDS.get(
                chain.action_key, ROUTE_THRESHOLDS["pay_bill"]),
            notes=list(chain.notes),
        )

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
        #: 「只有老人本人能关」的那一族开关。**一张表，不是一个名字。**
        #:
        #: 原先这里写的是 `payload.teach_back_high_risk is False`——点了一个成员的
        #: 名字，它的兄弟 `repeat_sensitive` 就从旁边过去了。实测家属
        #: `PUT {repeat_sensitive: false}` 回 200，而那个字段在
        #: `v6_services.py` 里是承重的：
        #:
        #:     require_repeat = bool(profile.repeat_sensitive and (low_confidence or ...))
        #:
        #: 也就是家属替老人关掉了「听不清的时候要她再说一遍」——
        #: 高风险步骤上防误听的那一层。
        #:
        #: 以后再加这一类开关，加进这张表就自动受管；漏加会红在下面那条判据上。
        #: **守的是那条性质，不是一个角色的名字。**
        #:
        #: 原先这一行问的是 `actor.role == ActorRole.FAMILY`，而它要保护的
        #: 性质是「只有老人本人能关」。上面那段注释记着同一个形状在**字段**
        #: 那一轴上修过——点一个成员的名字，它的兄弟就从旁边过去，所以改成
        #: 了一张表。**角色这一轴当时还点着一个名字。**
        #:
        #: 实测：`POST /v2/auth/demo {"actor_id": "system-demo"}` 在演示模式下
        #: 谁都拿得到（而演示模式正是交给评委的那一档），SYSTEM 的
        #: `role != FAMILY`，于是它替老人把这两个开关都关掉了——关掉的是
        #: 「听不清要她再说一遍」和「高风险要复述确认」。
        #:
        #: 打开仍然谁都可以：这道门防的是**替她放松**，不是替她收紧。
        for flag in _ELDER_ONLY_SAFETY_FLAGS:
            if actor.role != ActorRole.ELDER and getattr(payload, flag) is False:
                raise HTTPException(
                    status_code=403,
                    detail=f"只有老人本人可以关闭{_ELDER_ONLY_SAFETY_FLAGS[flag]}。",
                )
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
        """Whether a natural voice is available; the client degrades if not.

        `where` 说明声音从哪来：`cloud`（晓晓，要念的话会发到微软语音服务）、
        `local`（离线模型）、`none`（用手机自己的声音）。页面按它写那枚「怎么保护您」的小标签，
        不许在云端合成时还说「不出这台手机」。
        """
        del actor
        return voice.status() if voice else {
            "available": False, "where": "none", "engine": None, "model": None,
            "package_installed": False, "model_present": False, "load_error": None,
            "fallback": "browser_speech_synthesis",
            "note": "未启用离线本地合成，使用浏览器语音。",
        }

    @router.post("/speech/warm", status_code=204)
    def speech_warm(actor: AuthContext = Depends(current_actor)) -> Response:
        """她按下麦克风 / 开始打字时页面调一下：服务器趁她说话的工夫把念话那条连接开好。

        连接闲 60 秒就会被服务端断，留不住；而从她开口到回答出来有好几秒。握手
        （实测国内 1.3 秒）放进这几秒里，第一句就不用再等。只开连接，不发任何文字。
        """
        del actor
        cloud = getattr(voice, "cloud", None)
        if cloud is not None:
            cloud.prewarm()
        return Response(status_code=204)

    @router.post(
        "/speech/synthesize",
        responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}},
                         "description": "云端晓晓回 MP3；离线模型回 16 位 PCM WAV"}},
    )
    def speech_synthesize(
        payload: SpeechSynthesizeRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> Response:
        """Synthesize one already-normalised sentence.

        先云端晓晓（MP3），再离线模型（WAV）。**Content-Type 按实际字节写**：
        原先写死 `audio/wav`，换成云端之后等于给 MP3 贴 WAV 的标签。
        """
        del actor
        if voice is None or not voice.available:
            raise HTTPException(status_code=503, detail="好听的声音暂时用不上，请使用浏览器语音。")
        try:
            audio, sample_rate = voice.synthesize(payload.text, payload.speed)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=audio,
            media_type=media_type_of(audio),
            headers={"Cache-Control": "no-store", "X-Sample-Rate": str(sample_rate)},
        )

    @router.get("/competition/evidence", response_model=CompetitionEvidenceBoard)
    def competition_evidence(actor: AuthContext = Depends(current_actor)) -> CompetitionEvidenceBoard:
        del actor
        return CompetitionEvidenceService.board()

    return router
