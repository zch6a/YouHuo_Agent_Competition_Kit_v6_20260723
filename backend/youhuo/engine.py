from __future__ import annotations

import os
import re
import threading
from datetime import UTC, datetime
from typing import Any

from .database import Database, IdempotencyConflict
from .deciders import _URGENT_WORDS, decide_chain
from .agent_brain import AgentBrain, FactResult
from .models import (
    ActorRole,
    AuthContext,
    ChatRequest,
    ChatResponse,
    FamilyApprovalRequest,
    FamilyReminderCreateRequest,
    Mode,
    ReminderStatus,
    ResponseCode,
    RiskLevel,
    SessionCreateRequest,
    SessionState,
    TaskRecord,
    TaskStatus,
    TaskType,
    ToolResult,
)
from .privacy import redact_payload
from .security import SafetyPolicy
from .orchestration import ConversationTaskInterleaver, DelegationPolicy, TaskPlanner, TaskVerifier, VerificationEvidence
from . import care_voice, companion
from .semantic_router import RoutingDecision, SemanticRouter, apply_advisory_slots
from .teach_back import TeachBackCheck, TeachBackOutcome, TeachBackVerifier
from .services import Services
from .v4_models import EmotionAnalysis
from .v4_models import EmotionLabel
from .v4_services import EmotionAnalyzer
from .utils import (
    combine_date_time,
    local_now,
    local_today,
    new_id,
    parse_relative_date,
    parse_time_text,
    request_fingerprint,
    semantic_hash,
)


def semantic_model_configured() -> bool:
    """True when an OpenAI-compatible endpoint is fully configured."""
    return all(os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))


#: Upper bound on the per-session conversational state the engine keeps in
#: memory. These maps are never persisted (companion continuity must not become
#: a stored transcript), so nothing evicts them but this: without a cap a
#: long-running server accumulates one entry per session forever.
_SESSION_STATE_LIMIT = 512


def _remember(store: dict[str, Any], key: str, value: Any) -> None:
    """Insert, evicting the oldest sessions once the cap is reached."""
    store.pop(key, None)  # re-insert so an active session moves to the newest end
    store[key] = value
    while len(store) > _SESSION_STATE_LIMIT:
        del store[next(iter(store))]


class EngineError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


#: 敏感表单的四类，和它们各自的槽位名。
#:
#: 键是句子里出现的词，值是 `SafetyPolicy.risk_for` 读的那个槽位。
#: **两边必须对得上**——原先这里认出四类却只写得出一个键，
#: 于是三类敏感表单在风险判定里等于没被认出来。
SENSITIVE_FORM_SLOTS: dict[str, str] = {
    "身份证": "id_card",
    "银行卡": "bank_card",
    "人脸": "face_verification",
    "医疗记录": "medical_record",
}
_SENSITIVE_FORM_SLOTS = SENSITIVE_FORM_SLOTS


class YouHuoEngine:
    """Deterministic state-machine core.

    Language models may be added as an *advisory* intent parser, but authorization,
    confirmations, duplicate blocking, tool execution, audit and family isolation
    remain outside the model. A process lock serializes state-changing demo calls;
    production deployments should additionally use a database-backed distributed
    lock or serializable transaction layer.
    """

    def __init__(self, db: Database, services: Services | None = None) -> None:
        self.db = db
        self.services = services or Services.build()
        self._lock = threading.RLock()
        # session_id -> companion context. In memory on purpose: companion
        # continuity must not become a stored transcript.
        self._companion_contexts: dict[str, companion.CompanionContext] = {}
        # session_id -> the parked social topic we offered to resume.
        self._pending_topics: dict[str, str] = {}
        # session_id -> the last line we spoke, so "再说一遍" has something to
        # repeat. Our own output, in memory only; never the elder's words.
        self._last_spoken: dict[str, str] = {}
        # session_id -> (reminder_id, title) just created, so a bare "算了" on the
        # very next turn undoes it. Cleared after one turn: "算了" much later
        # means something else, and cancelling the wrong reminder is silent.
        self._undoable_reminder: dict[str, tuple[str, str]] = {}
        # session_id -> (label, TaskType) for a second errand named in the same
        # breath ("顺便把水费也交了"), kept until the elder takes it up or moves on.
        self._pending_errands: dict[str, tuple[str, TaskType]] = {}
        # session_id -> 刚念给她听的那几条待办提醒的 id。
        #
        # 「要取消哪一条？**说出它的名字就行**」这句话问出口之后，她的下一句
        # 多半就只是一个名字（「量血压」「社区量血压」），里面既没有「取消」
        # 也没有「提醒」。原先那一句问完**什么都不记**，于是她的回答重新过
        # 一遍总分类器：实测「取消复诊前准备病历」被「复诊」带到挂号那一路，
        # 回的是「请选择医院，目前可用：第一医院、第二医院。」——她在取消
        # 一条提醒，屏幕上却让她挑医院。
        #
        # 和 `_pending_errands` 一样：她接上了就用掉，说了别的就丢掉。
        self._pending_reminder_pick: dict[str, tuple[str, ...]] = {}
        # Built lazily: only sessions that ask a care question pay for the
        # schema init, and engines in unit tests that never do stay cheap.
        self._v4: Any | None = None
        self._v6: Any | None = None
        # 小优的大脑（`agent_brain.py`）。没配 `YOUHUO_AGENT_API_KEY` 时是 None，
        # 整条对话逐字节回到原来的确定性行为。
        self.agent: AgentBrain | None = AgentBrain.from_env()
        # 模型把一件差事交回来时，引擎要**不带模型**再走一遍那句话。
        self._agent_suspended = False

    # ------------------------------------------------------------------ auth/session
    def demo_login(self, actor_id: str):
        return self.services.auth.login_demo(self.db, actor_id)

    def create_session(self, actor: AuthContext, payload: SessionCreateRequest) -> SessionState:
        if actor.role != ActorRole.ELDER:
            raise AuthorizationError("只有老人账户可以创建语音会话。")
        session_id = payload.session_id or new_id("session")
        existing = self.db.get_session(session_id)
        if existing:
            if existing.family_id != actor.family_id or existing.elder_id != actor.actor_id:
                raise AuthorizationError("会话不属于当前账户。")
            return existing
        now = self.services.clock.now()
        session = SessionState(
            session_id=session_id,
            family_id=actor.family_id,
            elder_id=actor.actor_id,
            mode=Mode.YOUHUO,
            created_at=now,
            updated_at=now,
        )
        self.db.create_session(session)
        self.db.append_audit(actor.family_id, actor.actor_id, "SESSION_CREATED", session_id, {"mode": session.mode.value})
        return session

    # ------------------------------------------------------------------ chat
    def handle(self, actor: AuthContext, request: ChatRequest) -> ChatResponse:
        if actor.role != ActorRole.ELDER:
            raise AuthorizationError("这个语音会话只有老人本人可以使用。")
        scope = f"chat:{actor.actor_id}:{request.session_id}"
        fingerprint = request_fingerprint({"session_id": request.session_id, "text": request.text})
        with self._lock:
            cached = self.db.get_idempotent_response(scope, request.request_id, fingerprint)
            if cached is not None:
                return ChatResponse.model_validate(cached)
            session = self._require_session(actor, request.session_id)
            response = self._handle_uncached(actor, session, request.text)
            self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
            return response

    def _handle_uncached(self, actor: AuthContext, session: SessionState, text: str) -> ChatResponse:
        signal = SafetyPolicy.detect_safety_signal(text)
        if signal:
            if signal.notify_family:
                self.services.notification.send(
                    self.db,
                    family_id=actor.family_id,
                    recipient_role=ActorRole.FAMILY,
                    event_type=signal.category,
                    entity_id=session.session_id,
                    message=f"优活听到老人可能{signal.family_word}，请尽快联系确认。",
                )
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "SAFETY_SIGNAL",
                session.session_id,
                {"category": signal.category, "severity": signal.severity},
            )
            return self._response(ResponseCode.SAFETY_ALERT, signal.message, session, ui={"theme": "warning", "speak": True})

        # ── 一般身体不适：把「把人连上人」那一层补上 ─────────────────────────
        #
        # 上面那一道管的是**紧急**——自伤、跌倒、中风征兆、诈骗，而且带一整套
        # 防误报守卫（它拦得住「电视剧里那人昏倒了」）。
        # 一般的不适它接不住，**实测**：「我有点不舒服」「我今天头晕」都返回
        # None——于是这两句话走完整个流程、屏幕上什么都不会发生。
        #
        # 决策器层（`deciders.py`）认得出这一类。这里只接**它认出来的那一支**，
        # 上面任何一条既有分支都没动：
        #
        #   · 不升级成"打急救电话"（那是上面那一道的事）
        #   · 但**要把人连上人**——这正是这一页对家人的承诺
        #
        # 整段包在 try 里：判断层绝不许拖垮对话主链。它算不出来的时候，
        # 这一页该照常走它原来的路，而不是整条断掉。
        # 照护问答的判断在这里算**一次**，下面身体不适那一支和正常路共用
        # （`test_the_two_call_sites_share_one_care_router` 钉的是「只有一处判断」）。
        # 从这里到正常路之间，改模式的分支都会提前返回，所以早算和晚算是一回事。
        care_guess = self._care_intent_for(session, text)
        try:
            unwell = decide_chain(text)
        except Exception:
            unwell = None
        # 两道门，都是整套回归量出来的（KNOWN_ISSUES 370）：
        #   · 手上有事在办：挂号问科室时她描述症状，是**被邀请的回答**，不是求助
        #     （`test_a_symptom_it_cannot_place_still_gets_an_answer`）；
        #   · 说的是别人：「隔壁他摔倒了，我扶不起来」。安全策略早有第三人称守卫，
        #     这一支原先没用，于是别人摔倒去叫了她的家人。
        busy_task = self.db.get_task(session.active_task_id) if session.active_task_id else None
        # 「手上有事」只在**正在问她问题**（COLLECTING）时才算：那时说症状是在回答
        # 「看哪个科」。原先凡是有一件没办完的事都算——实测一笔水费正等她念金额时，
        # 她说「我有点头晕」，家里人没收到任何通知，回给她的是「我没听出这一句是要办、
        # 要改，还是不办。这件事是：支付水费……」。那一刻没人在问她症状。
        busy = busy_task is not None and busy_task.status == TaskStatus.COLLECTING
        if (unwell is not None and unwell.intent.choice == "说自己不舒服"
                and not busy and not self._unwell_is_someone_elses(text)):
            self.services.notification.send(
                self.db,
                family_id=actor.family_id,
                recipient_role=ActorRole.FAMILY,
                event_type="elder_feels_unwell",
                entity_id=session.session_id,
                message="优活听到老人说身体不舒服，请抽空联系确认一下。",
            )
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "UNWELL_SIGNAL",
                session.session_id,
                {
                    "intent": unwell.intent.choice,
                    "intent_confidence": round(unwell.intent.confidence, 3),
                    "interrupt": unwell.interrupt.choice,
                },
            )
            # 「我膝盖疼」「我今天头晕」：照护问答**也**认得（SYMPTOM_MENTION）。
            # 这一支排在它前面，原先直接把它截走，于是照护那一句——「要我帮您挂个
            # 号吗」和危险信号那几条——再也说不出口（`test_bare_symptom_offers_
            # instead_of_booking` 红着）。两个分类器都认的一句，两件都做：家人照样
            # 通知（上面已发），照护那一句原样跟在后面。
            care_intent = care_guess
            if care_intent is care_voice.CareIntent.SYMPTOM_MENTION:
                answered = self._care_answer(actor, session, care_intent, text)
                # 「听着您不太舒服」要打头：屏幕会把长话剪到前两句，家人那一句要是
                # 排第一，她先看到的就不是对她自己的回应（`test_she_is_still_greeted_
                # before_the_alarm`）。
                merged = answered.message.replace(
                    "听着您不太舒服。", "听着您不太舒服，我这就提醒家里人给您打个电话。", 1)
                if merged == answered.message:
                    merged = "我这就提醒家里人给您打个电话。" + answered.message
                with self._lock:
                    _remember(self._last_spoken, session.session_id, merged)
                return answered.model_copy(update={
                    "code": ResponseCode.SAFETY_ALERT,
                    "message": merged,
                    "ui": {**answered.ui, "theme": "warning"},
                })
            return self._response(
                ResponseCode.SAFETY_ALERT,
                "我知道了，这就提醒家里人给您打个电话。"
                "要是哪里难受得厉害，您直接说，我帮您联系。",
                session,
                ui={"theme": "warning", "speak": True},
            )

        if SafetyPolicy.contains_prompt_injection(text):
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "SUSPICIOUS_INSTRUCTION_BLOCKED",
                session.session_id,
                {"text_hash": semantic_hash([text])},
            )
            return self._response(
                ResponseCode.SAFETY_ALERT,
                "这段话包含试图绕过确认或权限的指令，优活不会执行。您可以重新说明真实需求。",
                session,
                ui={"theme": "warning", "speak": True},
            )

        active_task = self.db.get_task(session.active_task_id) if session.active_task_id else None
        if active_task and active_task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}:
            session.active_task_id = None
            active_task = None
            self.db.update_session(session)

        # Emotion-aware task lock: explicit, explainable non-clinical signals may pause a
        # task without discarding its state. Emergency expressions were already handled
        # by SafetyPolicy above. The raw utterance is never copied into family-facing logs.
        emotion = EmotionAnalyzer.analyze(text)
        # 这一轮识别到的情绪要落库。此前这个结果只被读了 `should_pause_task` 一个
        # 字段就丢掉，于是真实部署里 `emotion_events` 永远是空的——细节见
        # `_record_emotion_signal` 的说明。写在分支之前：暂停任务的那一轮和只是
        # 聊两句的那一轮，记下来的价值是一样的。
        # 模型交回来的那一趟是同一轮话的改写，情绪在第一趟已经记过了；
        # 再记一次，「两周心情」的计数就会被这一层悄悄翻倍。
        if not self._agent_suspended:
            self._record_emotion_signal(actor, session, text, emotion)
        if active_task and emotion.should_pause_task and not self._wants_resume_task(text) and not self._is_cancel(text):
            session.mode = Mode.COMPANION
            self.db.update_session(session)
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "EMOTIONAL_TASK_PAUSE",
                active_task.id,
                {
                    "label": emotion.label.value,
                    "distress_band": round(emotion.distress, 1),
                    "raw_text_stored": False,
                    "task_state_preserved": True,
                    #: 这一支把她切进了陪伴模式（上面那行 `session.mode`）。
                    #: 不记下来，日志就重建不出她当时在哪个模式。
                    "mode": Mode.COMPANION.value,
                },
            )
            return self._response(
                ResponseCode.CHAT,
                emotion.user_message + " 原来的任务已经安全暂停；准备好后说「继续办事」即可恢复。",
                session,
                active_task,
                ui={"theme": "orange", "speak": True, "task_paused": True, "privacy": "不向家属展示聊天原文"},
                data={"emotion_label": emotion.label.value, "task_state_preserved": True},
            )

        # We offered to pick a parked topic back up last turn. Honour the answer
        # before anything else, otherwise a plain "好啊" falls through to the
        # errand menu and the offer was empty.
        with self._lock:
            pending_topic = self._pending_topics.get(session.session_id)
        if pending_topic and not active_task:
            if companion.declines_resume(text):
                with self._lock:
                    self._pending_topics.pop(session.session_id, None)
                return self._response(
                    ResponseCode.CHAT,
                    "好，那就先不聊。您随时想说，喊一声无忧伴就行。",
                    session,
                    ui={"theme": "blue", "speak": True},
                )
            if companion.accepts_resume(text):
                with self._lock:
                    self._pending_topics.pop(session.session_id, None)
                session.mode = Mode.COMPANION
                self.db.update_session(session)
                self.db.append_audit(
                    actor.family_id, actor.actor_id, "COMPANION_TOPIC_RESUMED",
                    session.session_id, {"had_parked_topic": True,
                                        "mode": Mode.COMPANION.value},
                )
                reply = self._companion_reply(pending_topic, session.session_id)
                return self._response(
                    ResponseCode.MODE_SWITCHED,
                    f"好，我们接着刚才的说。{reply}",
                    session,
                    ui={"theme": "orange", "speak": True, "privacy": "默认不向家属展示聊天全文"},
                    data={"resumed_topic": True},
                )
            # Anything else means they moved on; drop the offer silently.
            with self._lock:
                self._pending_topics.pop(session.session_id, None)

        if self._wants_companion(text):
            if active_task:
                return self._response(
                    ResponseCode.NEED_MORE_INFO,
                    "当前还有一件事情没有办完。您可以继续办理，明确说「取消任务」，或在心情不舒服时告诉我，我会安全暂停任务。",
                    session,
                    active_task,
                )
            if session.mode == Mode.COMPANION:
                # 她**已经在**无忧伴里了。这不是一次切换。
                #
                # 实测（一段真的聊下来的对话）：
                #     找无忧伴聊聊          -> 无忧伴来了。现在是橙色陪伴模式…
                #     我想我老伴了          -> 谢谢您愿意跟我说这些…
                #     他走了三年了…         -> 您刚才提到的这些，我一直记着在听…
                #     我们一九六三年在…结婚的 -> 我在听，您慢慢说，不着急。
                #     **隔壁王秀兰也总来陪我说话**
                #         -> code=mode_switched
                #            **无忧伴来了。现在是橙色陪伴模式，您可以慢慢聊。**
                #
                # 聊到第五句，它像刚进门一样打了个招呼。而 `companion.py`
                # 开头那段记着的结论正是：一位说了三句不同话的老人拿到三次
                # 同一句「我在听」，「对一次丧偶倾诉来说，这比什么都不说更糟」。
                # 这里更糟一点——它连的不是同一句，而是**开场那一句**。
                #
                # 三个后果，一个都不小：
                #   · 话头断了（`_FOLLOW_ON` 那套连贯性整轮被绕过）；
                #   · 审计里多写一条 `MODE_SWITCHED`——**记了一次没发生的
                #     切换**，而这个产品的卖点是那本账；
                #   · 这一支的 `ui` 里**没有** `privacy`，于是那句
                #     「默认不向家属展示聊天全文」在这一轮从屏幕上消失。
                #
                # 不去改 `wants_companion` 的词表：换个说法就又漏一个
                # （实测「孙子常来陪我」「有人陪着就好」「我想找个人陪」
                # 都不触发，只有「陪我说话」触发）。真正的不变量是
                # **「没发生的切换不许播报、也不许记账」**，按模式判。
                return self._response(
                    ResponseCode.CHAT,
                    self._companion_reply(text, session.session_id),
                    session,
                    ui={"theme": "orange", "speak": True,
                        "privacy": "默认不向家属展示聊天全文"},
                )
            session.mode = Mode.COMPANION
            self.db.update_session(session)
            self.db.append_audit(actor.family_id, actor.actor_id, "MODE_SWITCHED", session.session_id, {"mode": "companion"})
            return self._response(
                ResponseCode.MODE_SWITCHED,
                "无忧伴来了。现在是橙色陪伴模式，您可以慢慢聊。",
                session,
                ui={"theme": "orange", "speak": True},
            )

        if self._wants_youhuo(text) or self._wants_resume_task(text):
            session.mode = Mode.YOUHUO
            self.db.update_session(session)
            event = "EMOTIONAL_TASK_RESUMED" if active_task else "MODE_SWITCHED"
            self.db.append_audit(actor.family_id, actor.actor_id, event, active_task.id if active_task else session.session_id, {"mode": "youhuo"})
            if active_task:
                message = "已经恢复蓝色优活办事模式，原任务和已填写信息都还在。"
                # 「请继续回答下一步」原先是这句话的结尾——**而它没说下一步是什么**。
                #
                # 实测：她说「帮我交一下这个月的水费」-> 「…请您把金额说一遍，例如
                # 「确认支付68.40元」」；说「我心里难受」进无忧伴；陪两句；说
                # 「继续办事」-> 「…请继续回答下一步。」。`68.40` 从第一轮之后
                # 就再没出现过，而这一步要的正是逐字复述它。
                #
                # 所以把那一步的原话**逐字**说一遍（`_elder_confirm_ask`，
                # 和第一轮共用同一个方法）。只在**真的等她复述**时才说：
                # `requires_teach_back` 为假的那一支措辞是缴费专用的
                # （「生成家属支付请求」），套到一件挂号的事上就是一句错话。
                if (active_task.status == TaskStatus.AWAITING_ELDER_CONFIRMATION
                        and TeachBackVerifier.requires_teach_back(
                            active_task.task_type, int(active_task.risk_level),
                            profile_enabled=True)):
                    message += self._elder_confirm_ask(active_task)
                else:
                    message += "请继续回答下一步。"
            else:
                message = "已经切换到蓝色优活办事模式。请告诉我需要办理什么。"
            return self._response(
                ResponseCode.MODE_SWITCHED,
                message,
                session,
                active_task,
                ui={"theme": "blue", "speak": True, "task_paused": False},
                data={"task_state_preserved": bool(active_task)},
            )

        if active_task:
            if session.mode == Mode.COMPANION:
                if self._is_cancel(text):
                    return self._continue_task(actor, session, active_task, text)
                return self._response(
                    ResponseCode.CHAT,
                    self._companion_line(actor, session, text)[0]
                    + " 原任务仍安全暂停；说「继续办事」即可回到原步骤。",
                    session,
                    active_task,
                    ui={"theme": "orange", "speak": True, "task_paused": True, "privacy": "默认不向家属展示聊天全文"},
                    data={"task_state_preserved": True},
                )
            return self._continue_task(actor, session, active_task, text)

        routing = SemanticRouter.route(
            text,
            self._classify_task(text),
            elder_id=actor.actor_id,
            permit_remote_model=semantic_model_configured(),
        )
        if routing.model_used:
            self.db.append_audit(
                actor.family_id, actor.actor_id, "SEMANTIC_ROUTED", session.session_id, routing.audit_payload()
            )
        task_type = routing.task_type

        # Two defensible readings of the same sentence: clarify, never guess.
        if routing.needs_clarification:
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                routing.conflict_prompt or "我没有完全听清，请您慢一点再说一遍。",
                session,
                ui={"theme": "blue", "speak": True, "semantic_source": routing.parser_source},
                data={"semantic_basis": routing.basis},
            )

        # We offered to move on to the second errand the elder mentioned. As with
        # the companion topic, an offer that is not honoured is worse than none.
        with self._lock:
            offered_errand = self._pending_errands.get(session.session_id)
        if offered_errand and not active_task:
            label, errand_type = offered_errand
            if companion.accepts_resume(text) or self._is_yes(text):
                with self._lock:
                    self._pending_errands.pop(session.session_id, None)
                return self._start_errand(actor, session, errand_type, text)
            if companion.declines_resume(text) or self._is_no(text):
                with self._lock:
                    self._pending_errands.pop(session.session_id, None)
                return self._response(
                    ResponseCode.CHAT, f"好，{label}的事就先放着。您想办的时候再说一声。", session,
                    ui={"theme": "blue", "speak": True},
                )
            # Said something else entirely: drop the offer rather than let it
            # ambush a later "好".
            with self._lock:
                self._pending_errands.pop(session.session_id, None)

        # One-turn undo of the reminder we just announced. Consumed either way:
        # "算了" two minutes later is about something else.
        with self._lock:
            undoable = self._undoable_reminder.pop(session.session_id, None)
        if undoable and not active_task and self._is_cancel(text):
            reminder_id, title = undoable
            if self.db.cancel_reminder(reminder_id, actor.family_id, actor.actor_id):
                self.db.append_audit(
                    actor.family_id, actor.actor_id, "REMINDER_CANCELLED", reminder_id,
                    {"by": "elder_voice", "undo_of_last_turn": True},
                )
                return self._response(
                    ResponseCode.TASK_COMPLETED,
                    f"好，刚才那条提醒「{title}」已经取消了。",
                    session,
                    data={"cancelled_reminder_id": reminder_id},
                    ui={"theme": "blue", "speak": True},
                )

        # 上一句我们念了几条提醒、问她「要取消哪一条」。她这一句多半只是
        # 一个名字，所以在总分类器**之前**先拿这几条候选对一次。
        with self._lock:
            picking = self._pending_reminder_pick.pop(session.session_id, None)
        if picking and not active_task:
            hits = self._pick_reminder_from(actor, picking, text,
                                            many=True) or []
            if len(hits) == 1:
                return self._cancel_named_reminder(actor, session, hits[0])
            if len(hits) > 1:
                # 两条都对得上她说的那几个字。**不许猜**，回到列举那一支：
                # 那一支会说「有N条都对得上您说的，我分不出是哪一条」，
                # 并且把候选重新记上，让她再答一次。
                #
                # 原先这里只认「恰好一条」，多条就落回
                # `_wants_reminder_cancelled`——而她那一句里没有「提醒」，
                # 那道门进不来，最后落到通用菜单。**她答上了一句，
                # 拿到的是新手菜单。** 判据里那一条就是这么抓出来的。
                return self._cancel_recent_reminder(actor, session, text)
            # 说了别的就丢掉（上面已经 pop 了），不让它埋在那儿伏击后面一句。

        # "把刚才那个提醒取消掉" contains 提醒, so the errand classifier used to
        # read it as a request to *create* one and start asking which day. An
        # elder trying to undo something must not be handed a new task.
        if self._wants_reminder_cancelled(text):
            return self._cancel_recent_reminder(actor, session, text)

        # Voice reach for the care features. Deliberately only consulted where
        # the errand classifier found nothing, so it cannot shadow a real task:
        # "提醒我吃药" stays a reminder, "我今天吃药了吗" becomes an answer.
        care_intent = care_guess if task_type is None else None
        if care_intent is not None:
            return self._care_answer(actor, session, care_intent, text)

        if session.mode == Mode.COMPANION and task_type is None:
            line, agent_meta = self._companion_line(actor, session, text)
            return self._response(
                ResponseCode.CHAT,
                line,
                session,
                ui={"theme": "orange", "speak": True, "privacy": "默认不向家属展示聊天全文",
                    **({"agent": True} if agent_meta else {})},
                data={"agent": agent_meta} if agent_meta else None,
            )

        if task_type is None:
            # 她说了一句**明确的确认或取消**，而手上没有在办的事。原先这一句
            # 和一句完全听不懂的话拿到一模一样的通用菜单。实测六种说法全中：
            #     确认办理 / 确认 / 就这样办 / 取消任务 / 不办了 / 算了不用了
            #
            # 最要紧的是刚被 `duplicate_blocked` 拦下之后那一下（真实驱动）：
            #     「明天下午挂第一医院骨科」「王医生」「14:00」
            #         -> duplicate_blocked「相同时间的挂号已经存在，不会重复办理。」
            #     她紧接着说「确认办理」
            #         -> 「我在听。您可以说「帮我挂号」…」
            # **她没法从这句话判断号到底挂上了没有。** 对一句确认来说，
            # 既不肯定也不否定是最差的答案——默认读法是「成了」。
            #
            # 同一个形状这个仓库已经判过两次：`companion.py:9` 记着三句不同的
            # 话拿到三次「我在听」，结论是「比什么都不说更糟」；`engine.py:821`
            # 把它换到办事这一侧。这是第三处。
            nothing_pending = self._nothing_to_confirm(actor, text)
            if nothing_pending is not None:
                return self._response(
                    ResponseCode.CHAT,
                    nothing_pending,
                    session,
                    ui={"theme": "blue", "speak": True},
                    data={"nothing_awaiting_confirmation": True},
                )
            # 认不出来的话，先交给小优的大脑（`agent_brain.py`）：它可以查她的
            # 安排、用药、账单（原句念给她），把话改写成一件差事交回来走确认，
            # 或者就陪她说两句。没配模型、超时、熔断时返回 None，照旧给下面的菜单。
            agent_response = self._agent_turn(actor, session, text)
            if agent_response is not None:
                return agent_response
            # 这一句是**四种能力唯一的目录**：她没说清要办什么的时候，
            # 屏幕上就剩这一句告诉她这个 App 能做什么。
            #
            # 全 App 这样的目录有三处（这里、`v6_services._clarification`
            # 的 unknown 那一格、`elder.js` 的开场气泡），量过之后三处
            # 都缺同一条线：填表那一种**一个例子都没举**。而它的触发词
            # 只有四个（填表/填写/认证/选项），她不可能自己猜到。
            # 判据 `test_the_menu_names_everything_she_can_ask_for`
            # 钉住「每一种任务都要有一个真能触发它的例子」。
            #
            # 新例子排在逗号**前面**是量出来的，不是随手放的：这一句会被
            # `max_sentence_chars`（默认 42）剪掉后半截。加在句末实测剪到
            # 39 字，四个例子全在屏幕上；排到后面那两个问句之后就会被剪掉，
            # 那就是一次落了地却什么都没改变的修法。
            # （后面那两个问句本来就看不到，那笔账另记。）
            return self._response(
                ResponseCode.CHAT,
                "我在听。您可以说「帮我挂号」「查一下水费」「提醒我明天下午吃药」"
                "「帮我填表」，"
                "问「我今天吃药了吗」「我今天有什么事」，或者说「找无忧伴聊聊」。",
                session,
                ui={"theme": "blue", "speak": True},
            )

        left_companion = self._leave_companion_for_errand(actor, session)
        task = self._new_task(actor, task_type, text, routing=routing)
        self.db.create_task(task)
        session.active_task_id = task.id
        self.db.update_session(session)
        self.db.append_audit(
            actor.family_id,
            actor.actor_id,
            "TASK_CREATED",
            task.id,
            {
                "task_type": task.task_type.value,
                "risk": int(task.risk_level),
                "semantic_basis": routing.basis,
                "advisory_fields": task.slots.get("advisory_fields", []),
            },
        )
        # "帮我挂号，顺便把水费也交了" used to start the registration and drop the
        # bill without a word. The task lock is right to handle one at a time —
        # but it has to say so, or the elder believes both are under way.
        second = self._secondary_errand(text, task_type)
        response = self._continue_task(actor, session, task, text, initial=True)
        if left_companion:
            response = response.model_copy(update={
                "message": f"{self._LEFT_COMPANION_NOTICE} {response.message}"})
        if second is not None:
            label, second_type = second
            with self._lock:
                _remember(self._pending_errands, session.session_id, (label, second_type))
            return response.model_copy(update={
                "message": response.message + f" 另外{label}的事我记下了，这件办完再帮您办。",
                "data": {**response.data, "pending_errand": label},
            })
        return response

    #: 她上一句听到的是「无忧伴来了。现在是橙色陪伴模式」，下一句就成了
    #: 「请您把金额说一遍，例如「确认支付68.40元」」。颜色在这个设计里
    #: 就是她判断自己在哪个世界的依据，不能无声地换掉。
    #:
    #: 这里**不**接一句「想接着聊，喊一声无忧伴就行」——任务还在办的时候，
    #: `_wants_companion` 那一支回的是「当前还有一件事情没有办完」。
    #: 那就成了一句不兑现的承诺，而这个文件自己写过这条规矩：
    #: 「an offer that is not honoured is worse than none」。
    _LEFT_COMPANION_NOTICE = "这件事要在蓝色优活办事模式里办，我先从无忧伴切过来了。"

    def _leave_companion_for_errand(
        self, actor: AuthContext, session: SessionState
    ) -> bool:
        """她在无忧伴里说了一件办事的话，于是被带到优活。记一笔，并回答「刚才切了吗」。

        这里**不**问她「要不要切」：`test_task_request_in_companion_switches_to_youhuo`
        锁住的就是「说了办事的话就开单」，而让她为一句「帮我交水费」多答一轮
        也并不体面。缺的是另外两件事——**把这次切换记进审计**，和**告诉她**。

        审计那一侧尤其要紧。进无忧伴写了 `MODE_SWITCHED {"mode":"companion"}`，
        原先从这条路出来却一个字都不写，于是日志读下来是

            MODE_SWITCHED {"mode":"companion"}
            COMPANION_THEME_OBSERVED …
            TASK_CREATED {"task_type":"bill_payment","risk":4}

        ——「她在陪伴模式里创建了一件风险 4 的缴费任务」。而
        `wuyou-companion-privacy` 的 Policy 明写「不调用支付、挂号提交、
        身份和账户修改工具」。**日志凭空造出一次它自己的违规**，
        这比漏记一行更糟。
        """
        if session.mode == Mode.YOUHUO:
            return False
        previous = session.mode
        session.mode = Mode.YOUHUO
        self.db.update_session(session)
        self.db.append_audit(
            actor.family_id, actor.actor_id, "MODE_SWITCHED",
            session.session_id,
            {"mode": Mode.YOUHUO.value, "from": previous.value,
             "because": "errand_requested"},
        )
        return True

    def _start_errand(
        self, actor: AuthContext, session: SessionState, task_type: TaskType, text: str
    ) -> ChatResponse:
        """Open a task the elder already asked for, without re-parsing their reply.

        The accepting utterance is "好啊", which carries no slots. Seeding the task
        with the errand's own label ("缴费") keeps the record truthful without
        inventing a bill type or a hospital the elder never named.
        """
        left_companion = self._leave_companion_for_errand(actor, session)
        task = self._new_task(actor, task_type, self._ERRAND_LABELS[task_type])
        self.db.create_task(task)
        session.active_task_id = task.id
        self.db.update_session(session)
        self.db.append_audit(
            actor.family_id, actor.actor_id, "TASK_CREATED", task.id,
            {"task_type": task.task_type.value, "risk": int(task.risk_level), "from_pending_errand": True},
        )
        response = self._continue_task(actor, session, task, text, initial=True)
        if left_companion:
            return response.model_copy(update={
                "message": f"{self._LEFT_COMPANION_NOTICE} {response.message}"})
        return response

    # ------------------------------------------------------------------ task processing
    def _new_task(
        self,
        actor: AuthContext,
        task_type: TaskType,
        text: str,
        *,
        routing: RoutingDecision | None = None,
    ) -> TaskRecord:
        now = self.services.clock.now()
        interleaving = ConversationTaskInterleaver.split(text)
        slots: dict[str, Any] = {
            "task_graph_digest": TaskPlanner.plan(task_type).graph_digest,
            "interleaving_confidence": interleaving.confidence,
        }
        self._extract_slots(task_type, interleaving.primary_task_text, slots)
        if routing is not None and routing.advisory_slots:
            # Model values only fill gaps, and are recorded so the glass-box card
            # can show them as unverified rather than as confirmed facts.
            filled = apply_advisory_slots(slots, routing.advisory_slots)
            if filled:
                slots["advisory_fields"] = filled
        risk = SafetyPolicy.risk_for(task_type, slots)
        return TaskRecord(
            id=new_id("task"),
            family_id=actor.family_id,
            elder_id=actor.actor_id,
            task_type=task_type,
            status=TaskStatus.COLLECTING,
            risk_level=risk,
            slots=slots,
            semantic_key=semantic_hash([task_type.value, actor.family_id, "draft", now.date().isoformat(), text]),
            created_at=now,
            updated_at=now,
            deferred_topics=interleaving.deferred_social_text,
        )

    def _care_intent_for(
        self, session: SessionState, text: str
    ) -> care_voice.CareIntent | None:
        """这句话算不算一次照护问答。**两个调用点共用这一处判断。**

        调用点有两个：`_handle_uncached` 里那条正常的路，以及
        `_continue_task` 里「一笔付款正等家人点头」那一支。两处各写一遍的话，
        下面这条 COMPANION 例外只会写进一处——而这个仓库里
        「一个功能两条路、只修了一条」已经抓到五次以上。
        """
        care_intent = care_voice.classify(text)
        if care_intent is care_voice.CareIntent.SYMPTOM_MENTION and session.mode == Mode.COMPANION:
            # Mentioning an ache while chatting is a disclosure, not a service
            # request. 无忧伴 answers that better than a boundary statement does.
            return None
        return care_intent

    def _care_answer(
        self, actor: AuthContext, session: SessionState,
        care_intent: care_voice.CareIntent, text: str,
    ) -> ChatResponse:
        """把一次照护问答落进审计并包成回话。同上：一处定义，两处调用。"""
        answer = self._resolve_care_query(actor, session, care_intent, text)
        self.db.append_audit(
            actor.family_id,
            actor.actor_id,
            answer.audit_event,
            session.session_id,
            {"intent": care_intent.value, **answer.data},
        )
        return self._response(
            ResponseCode.CHAT,
            answer.message,
            session,
            ui={
                "theme": "orange" if session.mode == Mode.COMPANION else "blue",
                "speak": True,
                "care_intent": care_intent.value,
            },
            data={"care_intent": care_intent.value, **answer.data},
        )

    def _continue_task(
        self, actor: AuthContext, session: SessionState, task: TaskRecord, text: str, *, initial: bool = False
    ) -> ChatResponse:
        if self._is_cancel(text):
            return self._cancel_task(actor, session, task)

        if task.status == TaskStatus.AWAITING_ELDER_CONFIRMATION:
            if self._is_no(text):
                return self._cancel_task(actor, session, task)
            if self._is_yes(text):
                # A bare "好的" is agreement, not evidence of understanding. For
                # money the elder must restate the amount, and it is checked
                # against the authoritative value before anything happens.
                check = self._verify_teach_back(actor, task, text)
                if not check.passed:
                    return self._response(
                        ResponseCode.NEED_ELDER_CONFIRMATION,
                        check.prompt,
                        session,
                        task,
                        data={
                            "teach_back": check.outcome.value,
                            "teach_back_field": check.field_name,
                            "expected": check.expected_display,
                            "heard": check.heard_display,
                        },
                    )
                return self._after_elder_confirmation(actor, session, task, text)
            #: 等她确认的这一步，她说了**别的**。原先除了闲聊，一律回同一句
            #: 「我没听出这一句是要办、要改，还是不办」——实测一整串都被困住：
            #: 「帮我挂个号」「明天早上八点提醒我量血压」「今天几号」「我儿子电话多少」
            #: 「帮我联系家人」「最近老是一个人，挺闷的」。一件没办完的缴费，
            #: 不该让她问不了日子、找不到家人。
            #:
            #: 改法是**先照她说的办，再提一句还等着的那件事**；那件事的状态一点不动
            #: （还是等她念金额），不替她确认，也不替她取消。改动得了那件事的说法
            #: （「改成七十块」）仍然走下面的修改那一路，所以先问 `_proposed_edit`。
            #: 闲聊（「对了，我孙子昨天给我打电话了」）先认：那是在讲事，不是在问怎么联系人——
            #: 让照护层先看，它会把「打电话」读成一次联系人查询。
            if not self._looks_like_chitchat(text) and self._proposed_edit(task, text) is None:
                detour = self._answer_while_waiting(actor, session, task, text)
                if detour is not None:
                    return detour
            if self._looks_like_chitchat(text):
                if text not in task.deferred_topics:
                    task.deferred_topics.append(text[:180])
                    self.db.update_task(task)
                    task = self.db.get_task(task.id) or task
                return self._response(
                    ResponseCode.NEED_ELDER_CONFIRMATION,
                    #: 原先结尾是「请说『确认办理』或『取消任务』」——对缴费是错的
                    #: （这一步要她念金额，说「确认办理」拿回的是「我还需要确认您听清了金额」）。
                    f"刚才的话题已经暂存，办完后我们再接着聊。{self._still_waiting(task)}",
                    session,
                    task,
                    data={"deferred_topic_count": len(task.deferred_topics)},
                )
            # Everything is already collected and read back. An utterance that
            # is neither agreement, refusal nor a recognisable correction must
            # not be poured into the slots: "谢谢" used to become the reminder's
            # title, so the elder got a reminder called 谢谢 at the right time.
            edit = self._proposed_edit(task, text)
            if edit is None:
                #: 原先这一句是「**我没太听清**。这件事是：…」。
                #:
                #: 实测（一笔水费正等她确认，每句一个干净的库）12 句里
                #: **10 句**走到这里，全都得到那句话：
                #:
                #:     多少钱来着 / 这个月比上个月贵吗 / 我戴上眼镜再看看 /
                #:     水表在哪儿 / 上次是谁交的 / 六十八块四是吧 /
                #:     那就这样吧 / 哦 / 你先等等 / 我找找老花镜
                #:
                #: 最刺眼的那句见证：
                #:
                #:     确认支付六十八块四   -> **认得**，走到 need_family_approval
                #:     六十八块四         -> 「我没太听清」
                #:
                #: **同一串中文数字，包在「确认支付…」里它解析得出来。**
                #: 它听清了、也读懂了那个数，只是拿不准这一句是办、是改、
                #: 还是不办。（单说一串数字不算确认，这是对的——那可能是
                #: 她在念屏幕。错的只有那句回话。）
                #:
                #: 旁边那个 `data` 标志一直是诚实的：`unparsed_confirmation_reply`
                #: ——代码知道自己是 parse 不出来。只有对她说的那句话在撒谎。
                #:
                #: 措辞照本文件已有的先例 `_unrecognised_answer`：回显她刚说的
                #: 那几个字（截 20），再说真正没成的那件事。**回显本身就是
                #: 对旧措辞的反驳——能一字不差念回来，怎么会没听清。**
                said = text.strip()[:20]
                lead = f"「{said}」——" if said else ""
                return self._response(
                    ResponseCode.NEED_ELDER_CONFIRMATION,
                    f"{lead}我没听出这一句是要办、要改，还是不办。"
                    f"这件事是：{self._summary(task)}。"
                    #: **「确认办理」对缴费这一格是错的**——她照着说，
                    #: 拿回的是「我还需要确认您听清了金额」。
                    #: 说法取 `_elder_confirm_yes_form`，和这一步别处
                    #: 说的逐字相同。非缴费任务这一句**一字不变**。
                    f"对的话{self._elder_confirm_yes_form(task)}，"
                    "要改说「改成……」，不办说「取消任务」。",
                    session,
                    task,
                    data={"unparsed_confirmation_reply": True},
                )
            task.slots.update(edit)
            task.risk_level = SafetyPolicy.risk_for(task.task_type, task.slots)
            task.status = TaskStatus.COLLECTING
            self.db.update_task(task)
            self.db.append_audit(
                actor.family_id, actor.actor_id, "TASK_SLOT_CORRECTED", task.id,
                {"fields": sorted(edit), "at_confirmation": True},
            )
            task = self.db.get_task(task.id) or task
            return self._process_task(actor, session, task, changed=edit)

        if task.status == TaskStatus.AWAITING_FAMILY_APPROVAL:
            # 照护问答放过去。**这一支原先无条件吞掉整轮**，实测后果：
            #
            #     她：确认支付126.50元 -> awaiting_family_approval
            #     她：我今天吃药了吗 / 我今天有什么事 / 现在几点了 / 帮我联系家人
            #        -> 四句都回「已经向家人发送确认请求。」
            #     空对照：新开一个会话，同样四句 4/4 正常回答
            #
            # 而 `required_family_approvals = 2`，一位家属点头还不放；
            # `elder.js:122` 又把 session id 存在 localStorage、只在 400/403
            # 重建，所以**刷新页面拿回的是同一个锁住的会话**，她没有自救的路。
            #
            # 放行是安全的：`_resolve_care_query` 的 docstring 写着
            # 「Read-only except the elder's own profile」——它不动任何业务
            # 状态，唯一的写是她自己的语速/字号，而那恰恰最不该被锁住
            # （「我听不清」必须永远好用）。这一笔该等的照样等。
            #
            # 只放这一支。`AWAITING_ELDER_CONFIRMATION` 正等着她复述金额，
            # 放照护问答进去会和复述校验抢同一句话。
            care_intent = self._care_intent_for(session, text)
            if care_intent is not None:
                return self._care_answer(actor, session, care_intent, text)
            return self._response(
                ResponseCode.NEED_FAMILY_APPROVAL,
                # 原先这句话只说了「不会做什么」，没说她能做什么。
                "这一笔在等家人点头，家人确认之前优活不会动手。"
                "您可以问我别的事，不想办了就说「取消任务」。",
                session,
                task,
                data={"summary": self._summary(task)},
            )

        before = dict(task.slots)
        self._extract_slots(task.task_type, text, task.slots)
        task.risk_level = SafetyPolicy.risk_for(task.task_type, task.slots)
        # Any sentence mentioning 今天 or 明天 yields a date, so "今天天气真好"
        # used to silently move the appointment to today. A social aside only
        # counts as an answer when it changed something a date parser cannot
        # invent — a hospital, a doctor, a bill type.
        # 条件里原先只有 `_looks_like_chitchat`。而「今天几号」不是闲聊，
        # 它是一句 `ORIENTATION` 照护问句——**同一个道理，另一个兄弟成员
        # 溜过去了**。实测（`帮我挂号` 之后说「今天几号」）：
        #
        #     -> 好，日期改成2026-09-16。请选择医院，目前可用：…
        #
        # 她问今天几号，就诊日期被改成了今天。她**会**听到那半句
        # （所以不是无声的），但那不是她要的。
        #
        # 判据两侧都钉：问句不许改日期，而「明天」「上午九点」这种**真的
        # 在回答**的说法照样要改得动——把守卫放宽成「凡是带日期词的都不算」
        # 会把整条填槽路堵死。
        asking_not_answering = care_voice.classify(text) in self._NOT_AN_ANSWER
        if not initial and (self._looks_like_chitchat(text) or asking_not_answering):
            incidental_only = all(key in self._INCIDENTAL_SLOTS for key in task.slots if before.get(key) != task.slots[key])
            if incidental_only:
                task.slots = before
        useful_change = task.slots != before

        if not initial and not useful_change and self._looks_like_chitchat(text):
            if text not in task.deferred_topics:
                task.deferred_topics.append(text[:180])
                self.db.update_task(task)
                task = self.db.get_task(task.id) or task
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                "我先帮您办完这件事。刚才的话题已经暂存，办完后我们再接着聊，好吗？",
                session,
                task,
                data={"deferred_topic_count": len(task.deferred_topics)},
            )

        changed = {key: task.slots[key] for key in task.slots if before.get(key) != task.slots[key]}
        response = self._process_task(actor, session, task, changed=changed if not initial else None)

        # Two dead ends an elder hits often, both of which used to reply with the
        # unchanged question and no explanation of why nothing moved.
        if not initial and response.code == ResponseCode.NEED_MORE_INFO and not useful_change:
            if self._is_yes(text):
                return response.model_copy(update={
                    "message": "这件事还差一项没定下来，定完我再请您确认。" + response.message
                })
            if self._sounds_unsure(text):
                return response.model_copy(update={
                    "message": "没关系，不着急。" + response.message + "拿不准就先选第一个，之后也能改。"
                })
            # 第三种，而且是她最容易撞上的一种：她**真的回答了**正在被问的那个
            # 字段，而一个字都没认出来。上面那两支的注释写着「两种」，
            # 数下来是三种。
            #
            # 实测（说完「帮我挂号」之后逐个说，八种说法）：
            #     「第一医院」「第二医院」「去第一医院」 -> 好，医院改成…
            #     「北京协和医院」「协和」「第一」「一院」「市立医院」
            #         -> 五种都拿回**一字不差**的同一句
            #            「请选择医院，目前可用：第一医院、第二医院。」
            # 最刺眼的是「第一」：提示语自己就写着「第一医院、第二医院」。
            #
            # 同一趟里日期和时间**是有回执的**（「好，日期改成2026-09-17」），
            # 说明「我收到了 X」这套机器完全在；缺的是「我听见了，但那个不在
            # 名单里」。那个值连候选都没成为（`changed` 是空的），所以上面
            # `_describe_rejection` 也说不出话来。
            #
            # 「把同一句话原样再念一遍」这件事这个仓库已经判过一次：
            # `companion.py` 开头记着四个硬编码分支让一位说了三句不同话的老人
            # 拿到三次「我在听。您可以慢慢说，不着急。」，那段的结论是
            # 「对一次丧偶倾诉来说，这比什么都不说更糟」。同一个形状，
            # 换到办事这一侧。
            unheard = self._unrecognised_answer(response, text)
            if unheard:
                return response.model_copy(update={
                    "message": unheard + response.message})
        return response

    #: 这几种说的是**对话本身**，不是正在被问的那个字段，所以不给
    #: 「我没听出这是哪个…」那句话。任务锁着的时候它们本来也答不了
    #: （`_care_intent_for` 只在没有在办的事时才被问到，见 `:418`），
    #: 但那是另一件事，不该在这里被读成「她答错了」。
    #:
    #: `SYMPTOM_MENTION` **刻意不在这里**：问科室那一句自己写着
    #: 「也可以描述哪里不舒服」，所以说一句症状正是被邀请的回答。
    #: 它没被 `suggest_department` 认出来时，她必须听到一声，
    #: 否则就是原来那条死路。
    _NOT_AN_ANSWER = frozenset({
        care_voice.CareIntent.SPEAK_SLOWER,
        care_voice.CareIntent.SPEAK_FASTER,
        care_voice.CareIntent.HEARING_SUPPORT,
        care_voice.CareIntent.REPEAT,
        care_voice.CareIntent.CAPABILITY_HELP,
        care_voice.CareIntent.ORIENTATION,
        care_voice.CareIntent.MEDICATION_TODAY,
        care_voice.CareIntent.MEDICATION_STOCK,
        care_voice.CareIntent.MEDICATION_LIST,
        care_voice.CareIntent.HEALTH_RECENT,
        care_voice.CareIntent.SCHEDULE_TODAY,
        care_voice.CareIntent.CONTACT_REACH,
    })

    def _unrecognised_answer(self, response: ChatResponse, text: str) -> str:
        """她答了正在被问的那个字段而一个字都没认出来时，先说的那一句。

        字段名取 `response.data["missing"][0]`——那是**问题本身的出处**
        （`_process_hospital` / `_process_reminder` 把它放进 `data`），
        不在这里重算一遍「还缺什么」。重算等于给同一件事立两个出处，
        改一处忘一处的时候没有人会红。

        回话里带上她刚说的那几个字，**两个不同的错说法才会得到两句不同的话**；
        判据钉的正是这一点，而不是某一句措辞。截到 20 个字：这是回显，
        不是复述，没必要把一长句整段念回去。

        走到这里，闲聊已经被排除了：`:735` 那一支在「像闲聊且什么都没改」时
        就返回并把话题暂存了。所以「不是「好」、不是拿不准、又什么都没改」
        剩下的正是「她答了，而我没听懂」——不需要再加一个启发式去猜。
        """
        missing = (response.data or {}).get("missing") or []
        if not missing:
            return ""
        field = str(missing[0])
        #: 自由文本的槽位不该走到这里（什么都收），而
        #: 「我没听出这是哪个提醒内容」也不像一句人话。
        if field in self._FREE_TEXT_SLOTS:
            return ""
        label = self._CHANGE_LABELS.get(field)
        if not label:
            return ""
        if care_voice.classify(text) in self._NOT_AN_ANSWER:
            return ""
        said = text.strip()[:20]
        if not said:
            return ""
        return f"「{said}」——我没听出这是哪个{label}。"

    def _process_task(
        self,
        actor: AuthContext,
        session: SessionState,
        task: TaskRecord,
        *,
        changed: dict[str, Any] | None = None,
    ) -> ChatResponse:
        if task.task_type == TaskType.BILL_PAYMENT:
            response = self._process_bill(actor, session, task)
        elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
            response = self._process_hospital(actor, session, task)
        elif task.task_type == TaskType.REMINDER:
            response = self._process_reminder(actor, session, task)
        else:
            response = self._process_form(actor, session, task)

        # Say what changed. A correction that is applied silently leaves the
        # elder unable to tell whether "不对，我要后天" registered, and the next
        # thing they hear is the same question they were already stuck on.
        #
        # **只说真的改成了的那一项。** `changed` 是这一轮**提出**的改动，在上面
        # 那四个分支跑之前就算好了（`:696`）；而 `_process_hospital` 校验不过时
        # 会把那个槽位 `pop` 掉（`:933-942`）。两段各自都对，合起来说出一句假话：
        #
        #     她说「11点」——屏幕上一轮之前刚列过「陈医生（09:30、14:30）；
        #     赵医生（11:00、16:00）」，11:00 是它自己印出来的时间，属于另一位医生
        #     它回「好，时间改成11:00。该医生在这个时间没有可用号源。」
        #     而 current_slots 里根本没有 appointment_time
        #
        # 前半句说改好了、后半句说不行，**前半句是她会抓住的那半句**。
        #
        # 五种拒绝码逐个驱动过，只有 `INVALID_SLOT` 走得到这里：另外三种那个值
        # 压根没进槽位（`changed` 是空的），`PAST_DATE` 那一句里改掉的是时间、
        # 被驳回的是日期，所以「时间改成09:30」本来就是真话。
        applied = {key: value for key, value in (changed or {}).items()
                   if key in task.slots and task.slots[key] == value}
        # 槽位里**没有**了 = 被驳回。留一种情形什么都不说：槽位里有、但值和提出的
        # 不一样——那种情形两句话都是假的，而我没有量到它真的会发生，
        # 不编一句话去覆盖一个没见过的状态。
        rejected = {key: value for key, value in (changed or {}).items()
                    if key not in task.slots}
        acknowledgement = (self._describe_change(applied)
                           + self._describe_rejection(rejected))
        if acknowledgement:
            return response.model_copy(update={"message": f"{acknowledgement}{response.message}"})
        return response

    #: Slots worth reading back when the elder corrects one. Internal bookkeeping
    #: (digests, confidences, authoritative lookups) is deliberately absent.
    _CHANGE_LABELS = {
        "appointment_date": "日期", "appointment_time": "时间",
        "due_date": "日期", "due_time": "时间",
        "hospital": "医院", "department": "科室", "doctor": "医生",
        "title": "提醒内容", "bill_type": "账单",
    }

    @classmethod
    def _describe_change(cls, changed: dict[str, Any]) -> str:
        parts = [
            f"{label}改成{changed[key]}"
            for key, label in cls._CHANGE_LABELS.items()
            if key in changed
        ]
        return f"好，{'、'.join(parts)}。" if parts else ""

    @classmethod
    def _describe_rejection(cls, rejected: dict[str, Any]) -> str:
        """被驳回的那些，如实说没改成。

        紧跟在后面的就是驳回的理由（`validation.user_message`），所以这里
        只负责点出**是哪一项、她说的是什么**——「该医生在这个时间没有可用
        号源」这句话自己并没有说是哪个时间。

        用的是和 `_describe_change` **同一张** `_CHANGE_LABELS`：两句话必须
        用同一套说法，不然同一个槽位在肯定句和否定句里叫两个名字。
        """
        parts = [
            f"{label}没能改成{rejected[key]}"
            for key, label in cls._CHANGE_LABELS.items()
            if key in rejected
        ]
        return f"{'、'.join(parts)}。" if parts else ""

    #: Free text absorbs anything, so it may only be rewritten when the elder
    #: clearly said they were changing it. Structured slots are self-validating.
    #: Slots a date/time parser will happily extract from a sentence that was
    #: never an answer to anything.
    _INCIDENTAL_SLOTS = frozenset({"appointment_date", "appointment_time", "due_date", "due_time"})
    _FREE_TEXT_SLOTS = frozenset({"title", "form_goal"})
    _EDIT_MARKERS = ("改成", "改为", "换成", "改到", "不是", "不对", "应该是", "我要", "还是")

    def _proposed_edit(self, task: TaskRecord, text: str) -> dict[str, Any] | None:
        """The slot change this utterance actually asks for, or None.

        Called only once everything has been read back for confirmation, where
        the cost of misreading a stray word as content is a silently wrong task.
        """
        candidate = dict(task.slots)
        self._extract_slots(task.task_type, text, candidate)
        changed = {key: value for key, value in candidate.items() if task.slots.get(key) != value}
        if not changed:
            return None
        if not any(key in self._FREE_TEXT_SLOTS for key in changed):
            return changed
        if any(marker in text for marker in self._EDIT_MARKERS):
            return changed
        # Only free text changed and nothing signalled an edit: this is noise.
        structured = {k: v for k, v in changed.items() if k not in self._FREE_TEXT_SLOTS}
        return structured or None

    def _elder_confirm_ask(self, task: TaskRecord) -> str:
        """这一步还要她做什么。**一句话，两处共用。**

        原先这句话只写在 `_process_bill` 里一处，而情绪暂停之后的恢复语是

            「已经恢复蓝色优活办事模式，原任务和已填写信息都还在。请继续回答下一步。」

        实测那一串：她说「帮我交一下这个月的水费」拿到
        「…请您把金额说一遍，例如「确认支付68.40元」」，接着说「我心里难受」
        进无忧伴，陪两句，再说「继续办事」——**`68.40` 这个数字从第一轮之后
        就再没出现过**，而她所在那一步要的正是逐字复述它。一位刚刚情绪
        低落过的老人，得靠记性从三四轮之前把那句话捞回来。

        状态是好的（恢复后说出那句话直接进 `need_family_approval`），
        坏的只是那句话。所以抽成方法，让恢复语说**逐字相同**的一句——
        两处各写一份就会让她在同一个会话里听到两种说法。

        （顺带记一条：`/api/v1` 那条路的同一步走的是
        `TeachBackVerifier.build_prompt`，措辞和这里不一样。同一步、
        同一个受众、两句话——那是另一条，记在 KNOWN_ISSUES 里，
        不在这一改里顺手统一：要决定哪句胜出会牵动两侧的测试。）
        """
        teach_back = TeachBackVerifier.requires_teach_back(
            task.task_type, int(task.risk_level), profile_enabled=True
        )
        if not teach_back:
            #: 这一支只在缴费流程里到得了（`_process_bill` 上面几行无条件读
            #: `task.slots["amount_cents"]`），所以说「支付请求」是准的。
            #: 恢复语那一侧**按 `requires_teach_back` 为真才调**，
            #: 免得一件挂号的事被说成「生成家属支付请求」。
            #:
            #: **而它现在一行都跑不到。** `SafetyPolicy.risk_for` 对
            #: `BILL_PAYMENT` **无条件**回 HIGH(4)，而
            #: `requires_teach_back` 只要 `>= 3`——所以对缴费恒为真。
            #: 留着当守卫：哪天那个档位降下来，这一支会立刻上线，
            #: 那时它的措辞要重新读一遍。判据
            #: `test_the_fields_it_calls_critical_are_really_checked.py`
            #: 钉住「缴费恒 >= 3」，降了会红，红的那句话会指到这里。
            return "是否确认生成家属支付请求？请明确说「确认办理」或「取消任务」。"
        #: 复述那半句抽进 `_elder_confirm_yes_form`——**第三处**在用它。
        #: 拼回来这一句和原先逐字相同，判据钉住。
        return f"请您{self._elder_confirm_yes_form(task)}；不想办就说「取消任务」。"

    def _still_waiting(self, task: TaskRecord) -> str:
        """「那件事还等着您」——逐字用确认那一步本来的说法（`_elder_confirm_yes_form`）。"""
        return (f"另外，{self._summary(task)}这件事还等着您：请您{self._elder_confirm_yes_form(task)}；"
                "不办就说「取消任务」。")

    def _answer_while_waiting(
        self, actor: AuthContext, session: SessionState, task: TaskRecord, text: str
    ) -> ChatResponse | None:
        """等她确认时，她说了一件别的事：能答的先答，答完提一句还等着的那件。回 None 表示不认得。

        三类，按这个顺序：
          ① 另一件要办的事（挂号、提醒…）：记下来，这件办完再帮她办——和「帮我挂号，
             顺便交水费」同一套（`_pending_errands`，办完时会问「您刚才还说要办…，现在办吗？」）。
          ② 照护问答（几号、吃药没、谁的电话、联系家人）：照常回答。
          ③ 心里话（孤单、低落、着急、生气）：无忧伴接一句。
        """
        other = self._classify_task(text)
        if other is not None and other is not task.task_type and other in self._ERRAND_LABELS:
            label = self._ERRAND_LABELS[other]
            with self._lock:
                _remember(self._pending_errands, session.session_id, (label, other))
            return self._response(
                ResponseCode.NEED_ELDER_CONFIRMATION,
                f"{label}的事我记下了，这件办完再帮您办。{self._still_waiting(task)}",
                session,
                task,
                data={"pending_errand": label, "answered_while_waiting": "errand"},
            )
        care = self._care_intent_for(session, text)
        if care is not None:
            answered = self._care_answer(actor, session, care, text)
            return self._response(
                ResponseCode.NEED_ELDER_CONFIRMATION,
                f"{answered.message} {self._still_waiting(task)}",
                session,
                task,
                ui=answered.ui,
                data={**answered.data, "answered_while_waiting": "care"},
            )
        feeling = EmotionAnalyzer.analyze(text).label
        if feeling in {EmotionLabel.LONELY, EmotionLabel.LOW_MOOD, EmotionLabel.ANXIOUS, EmotionLabel.ANGRY}:
            reply = self._companion_line(actor, session, text)[0]
            return self._response(
                ResponseCode.NEED_ELDER_CONFIRMATION,
                f"{reply} {self._still_waiting(task)}",
                session,
                task,
                data={"answered_while_waiting": "feeling", "emotion_label": feeling.value},
            )
        return None

    def _elder_confirm_yes_form(self, task: TaskRecord) -> str:
        """**「答『是』要怎么说」，只此一处。**

        `_elder_confirm_ask` 的 docstring 写着「一句话，两处共用」，
        而实测有**第三处**没跟上：「我没听出这一句是要办、要改，还是不办」
        那一句无条件叫她说「确认办理」。驱动出来的那一串——

            她：68块4       -> 「…对的话说「确认办理」…」
            她：确认办理     -> 「我还需要确认您听清了金额。请您说一遍金额，
                              例如『确认支付68.40元』。」

        **产品给了一个它自己不收的说法**，而正确那句话就在上面几行。
        （「单说一串数字不算确认」是另一件事，那条记在 KNOWN_ISSUES
        第 289 条附近，是**有意**的决定，这一改不碰它。）

        缴费这一格要的是逐字复述金额；别的任务「确认办理」就够——
        所以这里按 `requires_teach_back` 分岔，**不按任务类型写死**。
        """
        if TeachBackVerifier.requires_teach_back(
            task.task_type, int(task.risk_level), profile_enabled=True
        ):
            amount = int(task.slots.get("amount_cents", 0) or 0) / 100
            return f"把金额说一遍，例如「确认支付{amount:.2f}元」"
        return "说「确认办理」"

    def _process_bill(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        bill_type = task.slots.get("bill_type")
        if not bill_type:
            self.db.update_task(task)
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                "您想查询或缴纳哪一种账单？可以说水费、电费或燃气费。",
                session,
                self.db.get_task(task.id) or task,
            )
        lookup = self.services.billing.lookup(self.db, actor.family_id, str(bill_type))
        if not lookup.ok:
            # Nothing was executed, so the task must not close as COMPLETED: an
            # elder who just asked to pay would hear a success signal for a
            # no-op. It is safely cancelled instead, and an already-settled bill
            # is reported as the duplicate it is.
            task.status = TaskStatus.CANCELLED
            task.result = lookup.data
            self.db.update_task(task)
            code = (
                ResponseCode.DUPLICATE_BLOCKED
                if lookup.code == "BILL_ALREADY_PAID"
                else ResponseCode.OK
            )
            return self._finish_task(session, task, lookup.user_message, code)
        task.slots.update(lookup.data)
        task.semantic_key = semantic_hash([task.task_type.value, task.slots["bill_id"]])
        duplicate = self.db.find_duplicate(task.family_id, task.semantic_key, exclude_task_id=task.id)
        if duplicate:
            task.status = TaskStatus.CANCELLED
            task.result = {"duplicate_task_id": duplicate.id}
            self.db.update_task(task)
            return self._finish_task(
                session,
                task,
                "这笔账单已经在办理或已经完成，不会重复提交。",
                ResponseCode.DUPLICATE_BLOCKED,
            )
        task.status = TaskStatus.AWAITING_ELDER_CONFIRMATION
        self.db.update_task(task)
        task = self.db.get_task(task.id) or task
        amount = int(task.slots["amount_cents"]) / 100
        # Design §4.2: do not just ask "confirm?". Ask the elder to say the
        # amount back, and tell them exactly what to say.
        teach_back = TeachBackVerifier.requires_teach_back(
            task.task_type, int(task.risk_level), profile_enabled=True
        )
        #: 这一句抽成方法了，因为**情绪暂停之后的恢复语也要说同一句**。
        #: 原先恢复语只有「请继续回答下一步。」——而这一步要求她逐字复述
        #: 那个金额，那个数字在第一轮之后就再没出现过（实测）。两处各写
        #: 一份措辞会让她在同一个会话里听到两种说法，所以共用这一个。
        ask = self._elder_confirm_ask(task)
        return self._response(
            ResponseCode.NEED_ELDER_CONFIRMATION,
            f"{lookup.user_message} {ask}",
            session,
            task,
            data={
                "amount_yuan": f"{amount:.2f}",
                "due_date": task.slots["due_date"],
                "teach_back_required": teach_back,
                # 下面三个是给 Task Space 的（老人端第十节：水费 / ¥68.40 / 给谁 / 哪个月）。
                #
                # 它们**本来就在** `task.slots` 里，只是没被带进响应，于是前端只能显示
                # 「这件事」而不是「缴费」——同一个缺口让状态行也一直说
                # 「正在办这件事」。那不是渲染错，是后端给的字段比屏幕上要说的话薄。
                #
                # 这是**加法**，不是重写 API 层（计划书第六十五节）：业务链、权限、
                # 确认门一行没动，只是把已经算出来的事实一起交出去。
                "task_type": task.task_type.value,
                "bill_type": task.slots.get("bill_type"),
                "period": task.slots.get("period"),
            },
        )

    def _process_hospital(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        missing = [
            key
            for key in ["hospital", "department", "doctor", "appointment_date", "appointment_time"]
            if not task.slots.get(key)
        ]
        if missing:
            self.db.update_task(task)
            task = self.db.get_task(task.id) or task
            prompts = {
                "hospital": f"请选择医院，目前可用：{'、'.join(self.services.hospital.hospitals)}。",
                "department": "请告诉我想挂哪个科室；也可以描述哪里不舒服，我只帮助选择科室，不做诊断。",
                "doctor": self._doctor_prompt(task),
                "appointment_date": "请告诉我就诊日期，例如明天或7月28日。",
                "appointment_time": self._time_prompt(task),
            }
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                prompts[missing[0]],
                session,
                task,
                data={"missing": missing, "current_slots": redact_payload(task.slots)},
            )
        task.semantic_key = semantic_hash(
            [
                task.task_type.value,
                task.elder_id,
                task.slots["hospital"],
                task.slots["department"],
                task.slots["appointment_date"],
                task.slots["appointment_time"],
            ]
        )
        duplicate = self.db.find_duplicate(task.family_id, task.semantic_key, exclude_task_id=task.id)
        if duplicate:
            task.status = TaskStatus.CANCELLED
            task.result = {"duplicate_task_id": duplicate.id}
            self.db.update_task(task)
            return self._finish_task(session, task, "相同时间的挂号已经存在，不会重复办理。", ResponseCode.DUPLICATE_BLOCKED)
        validation = self.services.hospital.validate(task.slots, today=local_today(self.services.clock.now()))
        if not validation.ok:
            task.status = TaskStatus.COLLECTING
            if validation.code in {"UNKNOWN_HOSPITAL"}:
                task.slots.pop("hospital", None)
            elif validation.code in {"UNKNOWN_DEPARTMENT"}:
                task.slots.pop("department", None)
            elif validation.code in {"UNKNOWN_DOCTOR"}:
                task.slots.pop("doctor", None)
            elif validation.code in {"INVALID_SLOT"}:
                task.slots.pop("appointment_time", None)
            elif validation.code in {"INVALID_DATE", "PAST_DATE"}:
                task.slots.pop("appointment_date", None)
            self.db.update_task(task)
            return self._response(ResponseCode.NEED_MORE_INFO, validation.user_message, session, self.db.get_task(task.id) or task)
        task.status = TaskStatus.AWAITING_ELDER_CONFIRMATION
        self.db.update_task(task)
        task = self.db.get_task(task.id) or task
        return self._response(
            ResponseCode.NEED_ELDER_CONFIRMATION,
            f"请确认：{self._summary(task)}。确认后我再正式提交。",
            session,
            task,
            data={"summary": self._summary(task)},
        )

    def _process_reminder(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        missing = [key for key in ["title", "due_date", "due_time"] if not task.slots.get(key)]
        if missing:
            self.db.update_task(task)
            task = self.db.get_task(task.id) or task
            prompt = {
                "title": "要提醒您做什么事情？",
                "due_date": "哪一天提醒？例如明天。",
                "due_time": "几点提醒？例如下午三点。",
            }[missing[0]]
            return self._response(ResponseCode.NEED_MORE_INFO, prompt, session, task, data={"missing": missing})
        task.semantic_key = semantic_hash(
            [task.task_type.value, task.elder_id, task.slots["title"], task.slots["due_date"], task.slots["due_time"]]
        )
        duplicate = self.db.find_duplicate(task.family_id, task.semantic_key, exclude_task_id=task.id)
        if duplicate:
            task.status = TaskStatus.CANCELLED
            task.result = {"duplicate_task_id": duplicate.id}
            self.db.update_task(task)
            return self._finish_task(session, task, "相同的提醒已经存在，不会重复创建。", ResponseCode.DUPLICATE_BLOCKED)
        task.status = TaskStatus.AWAITING_ELDER_CONFIRMATION
        self.db.update_task(task)
        task = self.db.get_task(task.id) or task
        # 她点头**之前**就得知道这个时刻已经过去了。
        #
        # 实测（本地 07:54）：「提醒我今天4点吃药」->
        # 「请确认：在2026-09-01 04:00提醒您「吃药」。」——三小时前。
        # 点完头还会说「已经设置提醒」。系统请她确认一个它守不住的承诺，
        # 而她可能只是把钟点说错了一位。
        #
        # 指给她这条路自己就支持的改法（`_proposed_edit`）。
        ask = (f"请确认：在{task.slots['due_date']} {task.slots['due_time']}"
               f"提醒您「{task.slots['title']}」。")
        try:
            when = datetime.fromisoformat(
                combine_date_time(task.slots["due_date"], task.slots["due_time"]))
        except (ValueError, KeyError):
            when = None
        if when is not None and when <= datetime.now(UTC):
            ask += "这个时间已经过去了，要改说「改成……」。"
        return self._response(
            ResponseCode.NEED_ELDER_CONFIRMATION,
            ask,
            session,
            task,
        )

    def _process_form(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        task.slots.setdefault("form_goal", "逐项语音辅助填写")
        task.semantic_key = semantic_hash([task.task_type.value, task.elder_id, task.slots.get("form_goal")])
        task.status = TaskStatus.AWAITING_ELDER_CONFIRMATION
        self.db.update_task(task)
        task = self.db.get_task(task.id) or task
        message = "我可以逐项朗读并填写表单，但不会绕过验证码或代替您完成人脸认证。是否开始辅助？"
        return self._response(ResponseCode.NEED_ELDER_CONFIRMATION, message, session, task)

    def _after_elder_confirmation(
        self, actor: AuthContext, session: SessionState, task: TaskRecord, confirmation_text: str
    ) -> ChatResponse:
        task.slots["elder_confirmed"] = True
        task.slots["elder_confirmation_hash"] = semantic_hash(["elder-confirmation", confirmation_text])
        if SafetyPolicy.requires_family_approval(task.risk_level):
            if task.task_type == TaskType.BILL_PAYMENT:
                payment = self.services.billing.create_payment_request(task.slots, task_id=task.id)
                if not payment.ok:
                    task.status = TaskStatus.FAILED
                    task.result = payment.data
                    self.db.update_task(task)
                    return self._finish_task(session, task, payment.user_message, ResponseCode.ERROR)
                task.slots.update(payment.data)
            task.status = TaskStatus.AWAITING_FAMILY_APPROVAL
            task.approval_digest = None
            self.db.update_task(task)
            task = self.db.get_task(task.id) or task
            task.approval_digest = SafetyPolicy.approval_digest(task)
            self.db.update_task(task, bump_version=False)
            task = self.db.get_task(task.id) or task
            # **先写「她确认了」，再叫家人。** 顺序不是随意的：
            #
            # 可信中心按链序渲染，而且显式印到毫秒。原先是先发通知再写
            # `ELDER_CONFIRMED`，于是真实引擎驱动出来的链是
            #
            #     …56.168537Z  NOTIFICATION_CREATED -> approval_required / family
            #     …56.170677Z  ELDER_CONFIRMED
            #
            # 女儿读到的是：家人先被叫去批一笔老人**还没确认**的钱——
            # 就在写着「您确认的和家人同意的必须是同一笔」的同一页上。
            #
            # 而**种子那一笔的顺序是对的**（ELDER_CONFIRMED 在通知之前），
            # 所以走一遍演示永远看不见这一条，只有真实引擎会反。
            self.db.append_audit(
                task.family_id,
                actor.actor_id,
                "ELDER_CONFIRMED",
                task.id,
                {"version": task.version, "approval_digest": task.approval_digest},
            )
            self.services.notification.send(
                self.db,
                family_id=task.family_id,
                recipient_role=ActorRole.FAMILY,
                event_type="approval_required",
                entity_id=task.id,
                message=f"老人请求办理：{self._summary(task)}。请您核对之后确认。",
            )
            delegation = DelegationPolicy.decide(
                task.task_type,
                task.risk_level,
                amount_cents=int(task.slots.get("amount_cents", 0) or 0),
                ambiguity=max(0.0, 1.0 - float(task.slots.get("interleaving_confidence", 1.0))),
                tool_is_reversible=False,
            )
            return self._response(
                ResponseCode.NEED_FAMILY_APPROVAL,
                "您确认好了。接下来要请家人也点一下头，家人同意之前不会真的去办。",
                session,
                task,
                data={
                    "summary": self._summary(task),
                    "required_family_approvals": delegation.family_approvals_required,
                    "delegation_level": delegation.autonomy_level,
                },
            )
        return self._execute_confirmed(actor, session, task)

    def _execute_confirmed(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        task.status = TaskStatus.EXECUTING
        self.db.update_task(task)
        if task.task_type == TaskType.HOSPITAL_REGISTRATION:
            result = self.services.hospital.book(
                self.db,
                family_id=task.family_id,
                elder_id=task.elder_id,
                slots=task.slots,
                today=local_today(self.services.clock.now()),
            )
            if result.ok:
                calendar = self.services.reminder.create_from_parts(
                    self.db,
                    family_id=task.family_id,
                    elder_id=task.elder_id,
                    title=f"前往{task.slots['hospital']}{task.slots['department']}就诊",
                    due_date=str(task.slots["appointment_date"]),
                    due_time=str(task.slots["appointment_time"]),
                    created_by=task.elder_id,
                )
                combined = dict(result.data)
                if calendar.ok:
                    combined["calendar_reminder_id"] = calendar.data["reminder_id"]
                    combined["calendar_status"] = "created"
                    message = result.user_message + " 已同步生成就诊提醒。"
                else:
                    combined["calendar_status"] = "conflict"
                    message = result.user_message + " 已有相同就诊提醒，未重复创建。"
                result = ToolResult(ok=True, code=result.code, data=combined, user_message=message)
        elif task.task_type == TaskType.REMINDER:
            result = self.services.reminder.create_from_parts(
                self.db,
                family_id=task.family_id,
                elder_id=task.elder_id,
                title=str(task.slots["title"]),
                due_date=str(task.slots["due_date"]),
                due_time=str(task.slots["due_time"]),
                created_by=actor.actor_id,
            )
        else:
            result = self._form_result(task)
        evidence = VerificationEvidence(
            tool_code=result.code,
            tool_ok=result.ok,
            observed_state=dict(result.data),
            requested_state={
                key: value
                for key, value in task.slots.items()
                if key in {"hospital", "department", "doctor", "appointment_date", "appointment_time", "bill_id", "title"}
            },
            side_effect_receipt=result.data.get("appointment_id") or result.data.get("reminder_id") or result.data.get("bill_id"),
        )
        verification = TaskVerifier.verify(task, evidence)
        task.status = TaskStatus.COMPLETED if result.ok and verification.accepted else TaskStatus.FAILED
        task.result = {**result.data, "verification": verification.model_dump(mode="json")}
        self.db.update_task(task)
        self.db.append_audit(
            task.family_id,
            "system-demo" if task.family_id == "fam-demo" else "system",
            "TASK_EXECUTED" if task.status == TaskStatus.COMPLETED else "TASK_FAILED",
            task.id,
            {
                "tool_code": result.code,
                "result": redact_payload(result.data),
                "verification_accepted": verification.accepted,
                "proof_digest": verification.proof_digest,
            },
        )
        code = ResponseCode.TASK_COMPLETED if task.status == TaskStatus.COMPLETED else ResponseCode.ERROR
        message = result.user_message if task.status == TaskStatus.COMPLETED else verification.user_safe_summary
        return self._finish_task(session, self.db.get_task(task.id) or task, message, code)

    @staticmethod
    def _form_result(task: TaskRecord):
        from .models import ToolResult

        return ToolResult(
            ok=True,
            code="FORM_ASSISTANCE_READY",
            data={"guidance": "step_by_step", "identity_bypass": False},
            user_message="已进入逐项语音辅助。验证码和人脸认证仍需由您本人完成。",
        )

    # ------------------------------------------------------------------ family approval/reminders
    def approve(self, actor: AuthContext, request: FamilyApprovalRequest) -> ChatResponse:
        if actor.role != ActorRole.FAMILY:
            raise AuthorizationError("只有绑定家属可以审批高风险任务。")
        scope = f"approve:{actor.actor_id}:{request.task_id}"
        fingerprint = request_fingerprint(request.model_dump(mode="json", exclude={"request_id"}))
        with self._lock:
            cached = self.db.get_idempotent_response(scope, request.request_id, fingerprint)
            if cached is not None:
                return ChatResponse.model_validate(cached)
            task = self.db.get_task(request.task_id)
            if task is None:
                raise EngineError("任务不存在。")
            if task.family_id != actor.family_id:
                raise AuthorizationError("任务不属于当前家庭。")
            if task.status != TaskStatus.AWAITING_FAMILY_APPROVAL:
                response = ChatResponse(
                    code=ResponseCode.ERROR,
                    message="任务已处理或当前不需要家属审批。",
                    mode=Mode.YOUHUO,
                    task_id=task.id,
                    task_status=task.status,
                    risk_level=task.risk_level,
                    ui={"theme": "warning", "speak": False},
                )
                self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
                return response
            current_digest = SafetyPolicy.approval_digest(task)
            expected = task.approval_digest
            if expected is None or expected != current_digest or request.approval_digest != current_digest:
                raise AuthorizationError("审批摘要与当前任务不一致，任务内容可能已变化，请刷新后重试。")
            if not request.approve:
                self.db.record_approval_vote(task.id, actor.actor_id, "reject", current_digest)
                task.status = TaskStatus.CANCELLED
                task.result = {"rejected_by": actor.actor_id, "reason": request.reason or ""}
                self.db.update_task(task)
                self.db.append_audit(task.family_id, actor.actor_id, "FAMILY_REJECTED", task.id, {"reason": request.reason or ""})
                self.services.notification.send(
                    self.db,
                    family_id=task.family_id,
                    recipient_role=ActorRole.ELDER,
                    event_type="task_rejected",
                    entity_id=task.id,
                    message="家人未批准本次高风险操作，任务已安全取消。",
                )
                self.db.clear_task_from_sessions(task.id, task.elder_id)
                response = ChatResponse(
                    code=ResponseCode.TASK_CANCELLED,
                    message="家属未批准，本次操作已安全取消。",
                    mode=Mode.YOUHUO,
                    task_id=task.id,
                    task_status=TaskStatus.CANCELLED,
                    risk_level=task.risk_level,
                    ui={"theme": "blue", "speak": False},
                )
            else:
                inserted = self.db.record_approval_vote(task.id, actor.actor_id, "approve", current_digest)
                if not inserted:
                    response = ChatResponse(
                        code=ResponseCode.NEED_FAMILY_APPROVAL,
                        message="这位家属已经确认过本次任务，请等待其他家属或任务执行结果。",
                        mode=Mode.YOUHUO,
                        task_id=task.id,
                        task_status=task.status,
                        risk_level=task.risk_level,
                        approval_digest=task.approval_digest,
                        ui={"theme": "blue", "speak": False},
                    )
                    self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
                    return response
                delegation = DelegationPolicy.decide(
                    task.task_type,
                    task.risk_level,
                    amount_cents=int(task.slots.get("amount_cents", 0) or 0),
                    ambiguity=max(0.0, 1.0 - float(task.slots.get("interleaving_confidence", 1.0))),
                    tool_is_reversible=False,
                )
                approval_count = self.db.count_approval_votes(task.id, "approve")
                required_approvals = max(1, delegation.family_approvals_required)
                if approval_count < required_approvals:
                    self.db.append_audit(
                        task.family_id, actor.actor_id, "FAMILY_APPROVAL_RECORDED", task.id,
                        {"approval_count": approval_count, "required_approvals": required_approvals},
                    )
                    self.services.notification.send(
                        self.db,
                        family_id=task.family_id,
                        recipient_role=ActorRole.FAMILY,
                        event_type="additional_approval_required",
                        entity_id=task.id,
                        message=f"本次操作已获得{approval_count}位家属确认，还需要{required_approvals - approval_count}位家属确认。",
                    )
                    response = ChatResponse(
                        code=ResponseCode.NEED_FAMILY_APPROVAL,
                        message=f"已记录确认，还需要{required_approvals - approval_count}位家属确认后才能执行。",
                        mode=Mode.YOUHUO,
                        task_id=task.id,
                        task_status=task.status,
                        risk_level=task.risk_level,
                        approval_digest=task.approval_digest,
                        ui={"theme": "blue", "speak": False},
                        data={"approval_count": approval_count, "required_approvals": required_approvals},
                    )
                    self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
                    return response
                task.status = TaskStatus.EXECUTING
                task.slots["family_approved"] = True
                task.slots["family_approver"] = actor.actor_id
                task.slots["family_approval_count"] = approval_count
                self.db.update_task(task)
                if task.task_type == TaskType.BILL_PAYMENT:
                    result = self.services.billing.settle(self.db, task.family_id, str(task.slots["bill_id"]))
                else:
                    result = self._form_result(task)
                evidence = VerificationEvidence(
                    tool_code=result.code,
                    tool_ok=result.ok,
                    observed_state=dict(result.data),
                    requested_state={"bill_id": task.slots.get("bill_id")} if task.task_type == TaskType.BILL_PAYMENT else {},
                    side_effect_receipt=result.data.get("bill_id"),
                )
                verification = TaskVerifier.verify(task, evidence)
                task.status = TaskStatus.COMPLETED if result.ok and verification.accepted else TaskStatus.FAILED
                task.result = {**result.data, "verification": verification.model_dump(mode="json")}
                self.db.update_task(task)
                self.db.append_audit(
                    task.family_id,
                    actor.actor_id,
                    "FAMILY_APPROVED_AND_EXECUTED" if task.status == TaskStatus.COMPLETED else "FAMILY_APPROVED_EXECUTION_FAILED",
                    task.id,
                    {
                        "approval_digest": expected,
                        "tool_code": result.code,
                        "verification_accepted": verification.accepted,
                        "proof_digest": verification.proof_digest,
                    },
                )
                self.services.notification.send(
                    self.db,
                    family_id=task.family_id,
                    recipient_role=ActorRole.ELDER,
                    event_type="task_completed" if task.status == TaskStatus.COMPLETED else "task_failed",
                    entity_id=task.id,
                    message=result.user_message if task.status == TaskStatus.COMPLETED else verification.user_safe_summary,
                )
                self.db.clear_task_from_sessions(task.id, task.elder_id)
                response = ChatResponse(
                    code=ResponseCode.TASK_COMPLETED if task.status == TaskStatus.COMPLETED else ResponseCode.ERROR,
                    message=result.user_message if task.status == TaskStatus.COMPLETED else verification.user_safe_summary,
                    mode=Mode.YOUHUO,
                    task_id=task.id,
                    task_status=task.status,
                    risk_level=task.risk_level,
                    ui={"theme": "blue", "speak": False},
                    data=redact_payload(task.result),
                )
            self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
            return response

    def create_family_reminder(self, actor: AuthContext, request: FamilyReminderCreateRequest) -> ChatResponse:
        if actor.role != ActorRole.FAMILY:
            raise AuthorizationError("只有绑定家属可以创建家庭待办。")
        if not self.db.actor_in_family(request.elder_id, actor.family_id, ActorRole.ELDER.value):
            raise AuthorizationError("老人账户不属于当前家庭。")
        scope = f"family-reminder:{actor.actor_id}:{request.elder_id}"
        fingerprint = request_fingerprint(request.model_dump(mode="json", exclude={"request_id"}))
        with self._lock:
            cached = self.db.get_idempotent_response(scope, request.request_id, fingerprint)
            if cached is not None:
                return ChatResponse.model_validate(cached)
            result = self.services.reminder.create(
                self.db,
                family_id=actor.family_id,
                elder_id=request.elder_id,
                title=request.title,
                due_at=request.due_at,
                created_by=actor.actor_id,
                source="family_app",
                escalation_after_minutes=request.escalation_after_minutes,
            )
            if result.ok:
                self.services.notification.send(
                    self.db,
                    family_id=actor.family_id,
                    recipient_role=ActorRole.ELDER,
                    event_type="family_reminder_created",
                    entity_id=str(result.data["reminder_id"]),
                    message=f"家人新增待办：{request.title}。",
                )
                self.db.append_audit(
                    actor.family_id,
                    actor.actor_id,
                    "FAMILY_REMINDER_CREATED",
                    str(result.data["reminder_id"]),
                    {"due_at": request.due_at.isoformat(), "escalation_after_minutes": request.escalation_after_minutes},
                )
            response = ChatResponse(
                code=ResponseCode.TASK_COMPLETED if result.ok else ResponseCode.DUPLICATE_BLOCKED,
                message=result.user_message,
                mode=Mode.YOUHUO,
                ui={"theme": "blue", "speak": False},
                data=redact_payload(result.data),
            )
            self.db.save_idempotent_response(scope, request.request_id, fingerprint, response.model_dump(mode="json"))
            return response

    def reminder_action(self, actor: AuthContext, reminder_id: str, action: str, request_id: str | None) -> ChatResponse:
        if actor.role != ActorRole.ELDER:
            raise AuthorizationError("只有老人账户可以确认或完成自己的提醒。")
        scope = f"reminder-action:{actor.actor_id}:{reminder_id}:{action}"
        fingerprint = request_fingerprint({"reminder_id": reminder_id, "action": action})
        with self._lock:
            cached = self.db.get_idempotent_response(scope, request_id, fingerprint)
            if cached is not None:
                return ChatResponse.model_validate(cached)
            reminder = self.db.get_reminder(reminder_id)
            if reminder is None:
                raise EngineError("提醒不存在。")
            if reminder.family_id != actor.family_id or reminder.elder_id != actor.actor_id:
                raise AuthorizationError("提醒不属于当前账户。")
            now = self.services.clock.now()
            if action == "acknowledge":
                if reminder.status in {ReminderStatus.COMPLETED, ReminderStatus.CANCELLED}:
                    message = "该提醒已经结束。"
                    code = ResponseCode.ERROR
                else:
                    self.db.update_reminder_status(reminder.id, ReminderStatus.ACKNOWLEDGED, "acknowledged_at", now)
                    message = "已确认收到提醒。"
                    code = ResponseCode.OK
            elif action == "complete":
                # 上面 `acknowledge` 那一支挡了 COMPLETED **和** CANCELLED，
                # 而这一支原先只挡了 COMPLETED——于是语音也能把一条已取消的
                # 提醒说成办完了。同一个洞在 `/api/v1/reminders/{id}/done` 上
                # 更宽（什么都没挡），现在守卫落到 `update_reminder_status`
                # 的 SQL 里，这里跟着把话说准。
                if reminder.status == ReminderStatus.COMPLETED:
                    message = "这件事已经完成，不需要重复操作。"
                    code = ResponseCode.DUPLICATE_BLOCKED
                elif reminder.status == ReminderStatus.CANCELLED:
                    message = "这件事已经取消了，不会再记成办好。要办的话重新说一次。"
                    code = ResponseCode.DUPLICATE_BLOCKED
                elif self.db.update_reminder_status(
                        reminder.id, ReminderStatus.COMPLETED, "completed_at", now):
                    # 排在**以后那一天**的，照样记成完成，但**不许夸**。
                    #
                    # 实测：老人在「明天上午去社区量血压」（8月30日）上按了「已完成」，
                    # 屏幕回的是「这件事已标记完成，我们做得可真棒。」——系统替一件
                    # 还没发生的事作了证，还夸了她。她的记录页上从此有一条
                    # 「办好了一件事」。
                    #
                    # 不拦是有理由的：「明天记得带病历」这类事今天真的可以先办好，
                    # 一刀切会把正当的提前完成也堵死。错的是那句夸奖。
                    # 所以把话说准，并且把日子说出来——让她看得出自己点的是哪一天的事。
                    due_local = local_now(
                        reminder.due_at if reminder.due_at.tzinfo
                        else reminder.due_at.replace(tzinfo=UTC))
                    if due_local.date() > local_now(now).date():
                        message = (
                            f"这件事排在{due_local.strftime('%m月%d日')}，"
                            "我先记成您提前办好了。")
                    else:
                        message = "这件事已标记完成，我们做得可真棒。"
                    code = ResponseCode.TASK_COMPLETED
                else:
                    # 走到这里说明状态在读和写之间变了（另一端同时动了它）。
                    # 不谎报成功——原先这里不看返回值，写不进去也照样说
                    # 「已标记完成」。
                    message = "这件事刚刚被别的地方改过了，请再看一眼。"
                    code = ResponseCode.DUPLICATE_BLOCKED
            else:
                raise EngineError("未知提醒操作。")
            self.db.append_audit(actor.family_id, actor.actor_id, f"REMINDER_{action.upper()}", reminder.id, {})
            response = ChatResponse(code=code, message=message, mode=Mode.YOUHUO, ui={"theme": "blue", "speak": True})
            self.db.save_idempotent_response(scope, request_id, fingerprint, response.model_dump(mode="json"))
            return response

    def scheduler_tick(self, actor: AuthContext, now: datetime) -> dict[str, int]:
        if actor.role not in {ActorRole.FAMILY, ActorRole.SYSTEM}:
            raise AuthorizationError("只有家属或系统可以触发演示调度。")
        family_scope = None if actor.role == ActorRole.SYSTEM else actor.family_id
        result = self.services.scheduler.tick(
            self.db,
            self.services.notification,
            now,
            family_id=family_scope,
        )
        self.db.append_audit(actor.family_id, actor.actor_id, "SCHEDULER_TICK", None, {"now": now.isoformat(), **result})
        return result

    # ------------------------------------------------------------------ teach-back
    def _verify_teach_back(self, actor: AuthContext, task: TaskRecord, text: str) -> TeachBackCheck:
        """Gate a side-effecting confirmation on demonstrated understanding.

        Every attempt is audited and recorded as a comprehension signal, so the
        interaction governor can adapt to how this elder is actually coping.
        """
        required = TeachBackVerifier.requires_teach_back(
            task.task_type, int(task.risk_level), profile_enabled=True
        )
        check = TeachBackVerifier.verify(task.task_type, task.slots, text, required=required)
        if check.outcome is TeachBackOutcome.NOT_REQUIRED:
            return check

        attempts = int(task.slots.get("teach_back_attempts", 0)) + 1
        task.slots["teach_back_attempts"] = attempts
        self.db.update_task(task, bump_version=False)

        self.db.append_audit(
            task.family_id,
            actor.actor_id,
            "TEACH_BACK_VERIFIED" if check.passed else "TEACH_BACK_REJECTED",
            task.id,
            {
                "outcome": check.outcome.value,
                "field": check.field_name,
                "attempts": attempts,
                # The values are the elder's own bill figures, already in the
                # family's audit scope; no new information is exposed.
                "expected": check.expected_display,
                "heard": check.heard_display,
            },
        )
        self.db.record_comprehension_event(
            family_id=task.family_id,
            elder_id=task.elder_id,
            task_id=task.id,
            signal=check.outcome.value,
            field_name=check.field_name,
            attempts=attempts,
        )
        return check

    # ------------------------------------------------------------------ extraction/helpers
    def _extract_slots(self, task_type: TaskType, text: str, slots: dict[str, Any]) -> None:
        if task_type == TaskType.BILL_PAYMENT:
            for name in ("水费", "电费", "燃气费"):
                if name in text:
                    slots["bill_type"] = name
                    break
            return
        if task_type == TaskType.HOSPITAL_REGISTRATION:
            for hospital in self.services.hospital.hospitals:
                if hospital in text:
                    slots["hospital"] = hospital
                    break
            suggested = self.services.hospital.suggest_department(text)
            if suggested:
                slots["department"] = suggested
            if slots.get("hospital"):
                for department in self.services.hospital.departments(str(slots["hospital"])):
                    if department in text:
                        slots["department"] = department
                        break
            hospital = slots.get("hospital")
            department = slots.get("department")
            if hospital and department:
                for doctor in self.services.hospital.doctors(str(hospital), str(department)):
                    if doctor in text or doctor.removesuffix("医生") in text:
                        slots["doctor"] = doctor
                        break
            parsed_date = parse_relative_date(text, local_today(self.services.clock.now()))
            if parsed_date:
                slots["appointment_date"] = parsed_date
            parsed_time = parse_time_text(text)
            if parsed_time:
                slots["appointment_time"] = parsed_time
            return
        if task_type == TaskType.REMINDER:
            parsed_date = parse_relative_date(text, local_today(self.services.clock.now()))
            parsed_time = parse_time_text(text)
            if parsed_date:
                slots["due_date"] = parsed_date
            if parsed_time:
                slots["due_time"] = parsed_time
            title = self._extract_reminder_title(text)
            if title:
                slots["title"] = title
            return
        #: 认出哪一类，就写**哪一类**的槽位。
        #:
        #: 原先这里只写 `face_verification`（句子里有「人脸」时）或者笼统的
        #: `sensitive_form`，而 `SafetyPolicy.risk_for` 读的是四个具体的键
        #: （`id_card` / `bank_card` / `face_verification` / `medical_record`）。
        #: 交集只有一个——另外三个键全仓没有任何地方写。实测后果：
        #:
        #:     「帮我填写银行卡的表单」   risk=3 -> 确认后直接 completed
        #:     「帮我填写身份证的表单」   risk=3 -> 直接 completed
        #:     「帮我填写医疗记录的表单」 risk=3 -> 直接 completed
        #:     「…人脸认证…」            risk=4 -> awaiting_family_approval
        #:
        #: 四类敏感表单，只有一类真的等家人点头。
        #: `sensitive_form` 继续写（`privacy.py` 在读它），
        #: 但它不再是唯一的信号。
        for word, slot in _SENSITIVE_FORM_SLOTS.items():
            if word in text:
                slots[slot] = True
        if any(k in text for k in _SENSITIVE_FORM_SLOTS):
            slots["sensitive_form"] = True
        slots["form_goal"] = text[:120]

    #: Words that mark a correction rather than being part of it. Without
    #: stripping these, "改成下午三点" retitles the reminder to 改成.
    _TITLE_NOISE = re.compile(r"改成|改为|换成|改到|不对|不是|应该是|而是|还是|我要|就是")

    @classmethod
    def _extract_reminder_title(cls, text: str) -> str | None:
        cleaned = text
        cleaned = re.sub(r"(优活[，, ]*)?(请|帮我)?(设置|创建|加一个)?(一个)?(提醒|日历|待办)", "", cleaned)
        cleaned = re.sub(r"(今天|明天|后天|大后天|下周[一二三四五六日天]|\d{1,2}月\d{1,2}日)", "", cleaned)
        cleaned = re.sub(r"(凌晨|早上|上午|中午|下午|傍晚|晚上)?[零〇一二两三四五六七八九十\d]{1,3}点(半|[零〇一二两三四五六七八九十\d]{1,3}分?)?", "", cleaned)
        cleaned = cls._TITLE_NOISE.sub("", cleaned)
        cleaned = cleaned.replace("别忘了", "").replace("提醒我", "").strip(" ，,。！!？?")
        # "不是复诊，是取药" — after stripping the markers the new content is what
        # follows the last separator, not the thing being corrected away.
        if "，" in cleaned or "," in cleaned:
            tail = re.split(r"[，,]", cleaned)[-1].strip()
            if tail:
                cleaned = tail
        cleaned = re.sub(r"^(是|要|得|去)+", "", cleaned).strip()
        if cleaned.startswith("我") and len(cleaned) > 1:
            cleaned = cleaned[1:].lstrip()
        if not cleaned or cleaned in {"我", "一下", "事情", "的", "了"}:
            return None
        return cleaned[:120]

    #: Ordered: explicit reminder language wins even when the reminder content
    #: mentions 复诊. Bare symptoms are deliberately absent from the hospital set
    #: — "我膝盖疼" is not a request to book anything, and care_voice offers
    #: instead of deciding for the elder. "我膝盖疼，帮我挂号" still matches 挂号.
    _TASK_KEYWORDS: dict[TaskType, tuple[str, ...]] = {
        #: 后五个是老人最常说的「叫我」式说法。原先没有它们，实测
        #: 「下周三记得叫我给孙子打个电话」被照护问答认成「联系家人」，
        #: 回一张联系人清单——她要的提醒没建，也没有任何一句话告诉她。
        TaskType.REMINDER: ("提醒", "日历", "待办", "别忘了",
                            "记得叫我", "记得喊我", "到时候叫我", "到时候喊我", "别让我忘"),
        TaskType.HOSPITAL_REGISTRATION: (
            "挂号", "看医生", "看病", "医院", "复诊",
            "挂个号", "专家号", "门诊", "看牙", "牙疼", "看眼", "眼科", "内科", "外科",
            "骨科", "心内科", "神经科", "皮肤科", "中医", "体检预约", "预约医生", "预约门诊",
        ),
        TaskType.BILL_PAYMENT: (
            "水费", "电费", "燃气费", "缴费", "交费", "账单",
            "煤气费", "取暖费", "物业费", "宽带费", "话费", "欠费", "要交的钱", "该交的钱",
        ),
        TaskType.FORM_ASSISTANCE: ("填表", "填写", "认证", "选项"),
    }

    @classmethod
    def _classify_task(cls, text: str) -> TaskType | None:
        for task_type, keywords in cls._TASK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return task_type
        return None

    @staticmethod
    def _wants_companion(text: str) -> bool:
        return companion.wants_companion(text)

    @staticmethod
    def _wants_youhuo(text: str) -> bool:
        return any(k in text for k in ["调用优活", "进入优活", "切换办事"])

    @staticmethod
    def _wants_resume_task(text: str) -> bool:
        return any(k in text for k in ["继续办事", "接着办", "恢复任务", "继续办理", "回到刚才的事"])

    #: Whole-utterance acknowledgements. These are matched exactly, never as
    #: substrings: "中" is agreement on its own but is also inside 中午, and "对"
    #: is inside 不对. An elder saying a bare "嗯" was previously not understood
    #: as agreement, and the utterance went on to overwrite the task's title.
    _BARE_YES = frozenset({
        "嗯", "嗯嗯", "恩", "中", "行", "行行", "成", "对", "对对", "是", "好", "好好",
        "要", "办", "同意", "没错", "就这样", "就这么办", "可以了", "ok", "okay",
    })

    @classmethod
    def _is_bare_yes(cls, text: str) -> bool:
        return text.strip().strip("，,。.！!？? ").casefold() in cls._BARE_YES

    #: 原先这八个词是 `_is_yes` 里的一个字面列表。拆成两半，
    #: **合起来逐字还是原来那八个**，所以 `_is_yes` 的行为一个字没变。
    #:
    #: 分开是为了另一支：她说了一句确认，而手上没有在等她确认的事
    #: （`_nothing_to_confirm`）。那一支只认 `_TASK_CONFIRM_WORDS`
    #: ——**明确在确认一件事**的说法；不认「可以/好的/没问题/是的」：
    #: 正等着一件事的时候那四个够用，单独说出来却判断不出她在确认什么，
    #: 而且它们是按**子串**匹配的（理由同 `_BARE_YES` 上面那段：
    #: 「好的」也躺在「今天天气好的」里面）。
    _TASK_CONFIRM_WORDS = ("确认办理", "确认", "办吧", "交吧")
    _VAGUE_AGREE_WORDS = ("可以", "好的", "没问题", "是的")

    @classmethod
    def _is_yes(cls, text: str) -> bool:
        normalized = text.replace(" ", "")
        if any(k in normalized for k in ["不确认", "不要", "不用", "不办", "算了", "取消"]):
            return False
        if cls._is_bare_yes(text):
            return True
        return any(k in normalized
                   for k in cls._TASK_CONFIRM_WORDS + cls._VAGUE_AGREE_WORDS)

    @staticmethod
    def _is_no(text: str) -> bool:
        normalized = text.replace(" ", "")
        return any(k in normalized for k in ["不确认", "不要", "不用", "不办", "算了", "取消"])

    #: Only a conjunction makes two errands out of one sentence. Without this,
    #: "提醒我明天交水费" — a single reminder — would look like a reminder plus a
    #: bill payment.
    _SECOND_ERRAND_MARKERS = ("顺便", "另外", "还有", "再帮我", "同时", "以及", "顺道")
    _ERRAND_LABELS = {
        TaskType.BILL_PAYMENT: "缴费",
        TaskType.HOSPITAL_REGISTRATION: "挂号",
        TaskType.REMINDER: "提醒",
        TaskType.FORM_ASSISTANCE: "填表",
    }

    @classmethod
    def _secondary_errand(cls, text: str, primary: TaskType) -> tuple[str, TaskType] | None:
        if not any(marker in text for marker in cls._SECOND_ERRAND_MARKERS):
            return None
        probe = cls._classify_task_ignoring(text, primary)
        if probe is None or probe is primary:
            return None
        return cls._ERRAND_LABELS[probe], probe

    @classmethod
    def _classify_task_ignoring(cls, text: str, primary: TaskType) -> TaskType | None:
        """Classify what is left once the primary errand's own words are gone."""
        stripped = text
        for keyword in cls._TASK_KEYWORDS.get(primary, ()):
            stripped = stripped.replace(keyword, "")
        return cls._classify_task(stripped)

    _CANCEL_VERBS = ("取消", "删掉", "删除", "去掉", "撤销", "不要了", "别提醒", "不用提醒")

    #: 「还没结束」的那几种状态。写在一处：原先这个集合在
    #: `_cancel_recent_reminder` 里就地写着，而同一个概念还要给 SQL 用，
    #: 抄第二遍迟早两处不一致。
    _PENDING_STATUSES = (ReminderStatus.SCHEDULED, ReminderStatus.NOTIFIED,
                         ReminderStatus.ACKNOWLEDGED)

    @classmethod
    def _wants_reminder_cancelled(cls, text: str) -> bool:
        if not any(k in text for k in ("提醒", "待办", "闹钟", "日程")):
            return False
        return any(verb in text for verb in cls._CANCEL_VERBS)

    def _cancel_recent_reminder(self, actor: AuthContext, session: SessionState, text: str) -> ChatResponse:
        """Cancel the elder's next pending reminder, naming it first.

        Deliberately conservative: it acts only when exactly one candidate is
        obvious, and otherwise reads the list back instead of guessing which one
        "刚才那个" meant. Cancelling the wrong reminder is a silent failure the
        elder would only discover by missing an appointment.
        """
        #: **在 SQL 里筛。** 原先取整个家庭最老的 100 条再在 Python 里筛
        #: 「她的 + 待办的」：家里的历史提醒攒过 100 条之后，那 100 条全是
        #: 过去的，筛完一条不剩，于是她听到「您现在没有待办提醒」——
        #: 而她明明有。实测垫 120 条历史后，库里有 2 条待办，听到的就是这句。
        pending = self.db.list_reminders(
            actor.family_id, limit=100,
            elder_id=actor.actor_id, statuses=self._PENDING_STATUSES)
        if not pending:
            return self._response(
                ResponseCode.OK, "您现在没有待办提醒，没有需要取消的。", session,
                ui={"theme": "blue", "speak": True},
            )
        # 原先这里是 `item.title in text`——**方向是反的**：要求整条标题
        # 一字不差地出现在她说的话里。于是她按提示只说一个名字
        # （「取消量血压的提醒」）永远对不上，因为「量血压」是**标题的一段**，
        # 不是反过来。`_pick_reminder_from` 两个方向都认。
        named = self._pick_reminder_from(actor, [item.id for item in pending],
                                         text, many=True)
        chosen = [item for item in pending if item.id in set(named or ())]
        target = chosen[0] if len(chosen) == 1 else (pending[0] if len(pending) == 1 else None)
        if target is None:
            # 念出来的钟点走老人所在时区。`due_at` 是 UTC 存储时刻，
            # 直接 strftime 会把 20:00 的提醒念成 12:00——实测语音读回的那两个
            # 钟点，在这个 App 的任何一屏上都不存在。
            shown = pending[:3]
            listed = "；".join(
                f"{local_now(item.due_at).strftime('%m月%d日 %H:%M')}{item.title}"
                for item in shown
            )
            # **说了有几条，就得把没念的那几条交代清楚。** 原先是
            # `您有{len(pending)}条提醒：{列出前三条}`——四条的时候她被告知
            # 有 4 条、只听到 3 条，而少掉的那一条恰好可能就是她要取消的
            # （实测家人刚加的「记得量血压」正是被截掉的那一条）。
            # 第 296 条修的是同一个形状：截断了就得说还剩几个。
            rest = len(pending) - len(shown)
            tail = f"还有{rest}条没念，想听我就接着念。" if rest else ""
            # 两条都带着她说的那几个字时，说清是**分不出来**，
            # 而不是把同一张单子再念一遍——那等于没回答。
            lead = (f"有{len(chosen)}条都对得上您说的，我分不出是哪一条。"
                    if chosen and len(chosen) > 1 else "")
            # 记住这几条候选：她下一句只说个名字也认得（见 `handle`）。
            with self._lock:
                self._pending_reminder_pick[session.session_id] = tuple(
                    item.id for item in pending)
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                f"{lead}您有{len(pending)}条提醒：{listed}。{tail}"
                f"要取消哪一条？说出它的名字就行。",
                session,
                data={"pending_reminders": len(pending)},
            )
        if not self.db.cancel_reminder(target.id, actor.family_id, actor.actor_id):
            return self._response(
                ResponseCode.OK, "这条提醒已经不在待办里了，不用再取消。", session,
                ui={"theme": "blue", "speak": True},
            )
        self.db.append_audit(
            actor.family_id, actor.actor_id, "REMINDER_CANCELLED", target.id, {"by": "elder_voice"},
        )
        return self._response(
            ResponseCode.TASK_COMPLETED,
            # 同上：取消时复述的那个「原定几点」也要是她听得懂的钟点。
            f"已经取消提醒：{target.title}，原定{local_now(target.due_at).strftime('%m月%d日 %H:%M')}。",
            session,
            data={"cancelled_reminder_id": target.id},
            ui={"theme": "blue", "speak": True},
        )

    #: 「取消」「提醒」这些词是她**怎么说**的，不是她要指的**哪一条**。
    #: 剥掉它们，剩下的才是她给的名字。
    _PICK_NOISE = (
        "取消", "删掉", "删除", "去掉", "撤销", "停掉", "不要", "别要",
        "那条", "这条", "那个", "这个", "一条", "第一条", "第二条", "第三条",
        "提醒", "待办", "闹钟", "日程",
    )

    @classmethod
    def _reminder_name_hint(cls, text: str) -> str:
        """把「取消量血压的提醒」剥成「量血压」。

        「的」**只从尾巴上去**，不全局删：一条叫「妈妈的药」的提醒，
        她说「取消妈妈的药」，全局删「的」会剥成「妈妈药」，
        反而对不上自己的标题。
        """
        core = text.strip()
        for word in cls._PICK_NOISE:
            core = core.replace(word, "")
        return core.strip().strip("了吧啊呢吗的，,。.！!？? 、")

    def _pick_reminder_from(self, actor: AuthContext,
                            candidates: list[str] | tuple[str, ...],
                            text: str, *, many: bool = False
                            ) -> list[str] | str | None:
        """她这一句指的是候选里的哪一条？

        **两个方向都认**：整条标题出现在她话里（「取消记得量血压」），
        或者她说的那几个字是标题的一段（「量血压」在「明天上午去社区量血压」
        里）。原先只认前一种——而提示语让她「说出它的名字」，
        照着做的人给的正是后一种。

        `many=False` 时恰好一条才回，否则回 `None`：取消错一条提醒是
        **静默失败**，她只会在错过一件事的时候才发现。
        """
        wanted = set(candidates or ())
        if not wanted:
            return None
        #: 候选 id 是**上一轮我们念给她听的那几条**，是一个已知的小集合。
        #: 按 id 去 SQL 里取，就没有任何窗口能把它挡在外面。
        #:
        #: 原先是取整个家庭最老的 100 条再对 id：历史一攒多，候选全在窗口
        #: 外，`hits` 是空的，于是她照着提示说出的名字落进通用菜单——实测
        #: 垫 120 条历史之后，她说「量血压」听到的是那段新手引导。
        #: 她照着提示回答了，拿到的是一个不相关的菜单。
        #:
        #: 这里**刻意不筛 status**：候选里那一条要是刚被办掉了，也应该由
        #: `_cancel_named_reminder` 说出「已经不在待办里了」，而不是让这一层
        #: 先把它滤掉、然后她落进通用分类器（那是个不回答）。
        pending = self.db.list_reminders(
            actor.family_id, limit=len(wanted),
            elder_id=actor.actor_id, reminder_ids=tuple(wanted))
        hint = self._reminder_name_hint(text)
        hits = [
            item.id
            for item in pending
            if item.title and (
                item.title in text or (len(hint) >= 2 and hint in item.title))
        ]
        if many:
            return hits
        return hits[0] if len(hits) == 1 else None

    def _cancel_named_reminder(self, actor: AuthContext,
                               session: SessionState,
                               reminder_id: str) -> ChatResponse:
        """她点了名的那一条，取消掉并复述。"""
        #: 这本来就是一次**按 id 的查找**，`get_reminder` 就在那儿。
        #:
        #: 原先是扫整个家庭最老的 100 条再对 id。历史一攒多，她点名那条
        #: 就不在窗口里，`record` 是 None——而下面那个 `or` 会**短路**，
        #: `cancel_reminder` 一次都不会被调用：她听到「这条提醒已经不在待办
        #: 里了，不用再取消」，而那条提醒**还在**，到点照样响。实测垫 120 条
        #: 历史之后正是这一句，而库里 status 还是 `scheduled`。
        #: 这正是本文件里反复说的那种静默失败：她只会在错过一件事的时候
        #: 才发现。
        #:
        #: 授权不依赖这次查找：`cancel_reminder` 自己按 family+elder+status
        #: 限定（见它的 docstring：「reachable by voice and so must scope
        #: itself to the caller's family and elder rather than trust the id」）。
        #: 这里再加一道家庭校验，是为了不把别人家那条的标题念出来。
        record = self.db.get_reminder(reminder_id)
        if record is not None and record.family_id != actor.family_id:
            record = None
        if record is None or not self.db.cancel_reminder(
                reminder_id, actor.family_id, actor.actor_id):
            return self._response(
                ResponseCode.OK, "这条提醒已经不在待办里了，不用再取消。",
                session, ui={"theme": "blue", "speak": True},
            )
        self.db.append_audit(
            actor.family_id, actor.actor_id, "REMINDER_CANCELLED", record.id,
            {"by": "elder_voice", "named": True},
        )
        return self._response(
            ResponseCode.TASK_COMPLETED,
            f"已经取消提醒：{record.title}，"
            f"原定{local_now(record.due_at).strftime('%m月%d日 %H:%M')}。",
            session,
            data={"cancelled_reminder_id": record.id},
            ui={"theme": "blue", "speak": True},
        )

    @staticmethod
    def _sounds_unsure(text: str) -> bool:
        """"我不知道" is an answer. Repeating the question at it is not a reply."""
        return any(k in text for k in [
            "不知道", "不清楚", "不懂", "说不好", "拿不准", "随便", "都行", "你看着办", "你决定",
        ])

    #: 「不办了」的各种自然说法。**用正则而不是字面子串**，理由见 `_is_cancel`。
    #:
    #: 那一条 `(?:不|别|不用|不想|甭)(?:想)?(?:办|交)(?:了|啦)` 覆盖
    #: 不办了 / 别办了 / 不用办了 / 我不想办了 / 这个月先不交了，
    #: 而**不会**碰到确认那一侧：「我想办这个月的水费」「办吧」「继续办事」
    #: 「接着办」「确认办理」里 `办` 后面都没有那个「了」。
    #: 判据 `test_she_can_say_no_in_her_own_words.py` 把这 15 个反例逐个钉住。
    #: 动词组原先只有 `办|交`。而「弄」是普通话里「办 / 处理」最常用的
    #: 口语动词之一，「整」在东北话里同样常用。实测八种说法漏六种：
    #: 「我不想弄了」「不弄了」「别弄了」「我不想搞了」「不想整了」
    #: 「这个我不弄了」——而「我不想办了」是认的。**语序不是问题**
    #: （四种语序用「办」全过），纯粹是动词。
    #:
    #: **那个紧跟在动词后面的「了」是全部安全性所在。** 它挡住的是：
    #: 「别弄坏了」「不想弄错」「别弄丢了」「别搞错了」「别整我了」
    #: 「不想搞卫生了」「我不会弄了」「别干活了太累」「不想做饭了」
    #: ——这些里面动词后面紧跟的都不是「了」。判据那 32 条阴性逐个钉住。
    _CANCEL_FORMS = (
        r"取消任务|停止办理|算了|"
        r"(?:不|别|不用|不想|甭)(?:想)?(?:办|交|弄|搞|整|做|干)(?:了|啦)"
    )
    #: 紧邻否定：她否定的是「取消」这件事本身，不是在取消。
    #: 「我不想取消任务」「不是算了的意思」「这事不能算了」都走这一道。
    _CANCEL_NEGATED = r"(?:不想|不要|不能|不可以|不是|没有|绝不|千万别|别)\s*$"

    @staticmethod
    def _is_cancel(text: str) -> bool:
        """她说「不办了」——用她自己的话说也算。

        ## 原先是四个字面子串

            ["取消任务", "停止办理", "不办了", "算了"]

        于是「我不**想**办了」不认得：那个「想」把连续的「不办了」打断了。
        实测（一笔水费正等她复述金额）：

            不办了            -> task_cancelled            听懂了
            算了，不办了       -> task_cancelled            听懂了
            先不办了吧         -> task_cancelled            听懂了
            **我不想办了**     -> need_elder_confirmation    没听懂
            我不想办了，心里堵  -> 同上
            这个月先不交了      -> 同上

        而回给她的是「**我没太听清**。这件事是：支付2026-07水费 68.40元。」
        ——它听得很清楚，只是不认这个说法，却把「没听清」归给了她；
        然后继续推一笔她刚刚拒绝的缴费。一句关于她的假话，加一笔她说过不办的钱。

        ## 反方向本来就有洞，所以两个方向一起改

            我不想取消任务   -> 原先**判成取消**（命中「取消任务」）
            不是算了的意思   -> 原先判成取消（命中「算了」）
            这事不能算了     -> 原先判成取消（命中「算了」）

        只放宽认得的说法而不加否定守卫，等于把一个缺陷换成另一个：
        她说「我不想取消任务」，系统给她取消了。

        ## 为什么不直接用 `SafetyPolicy._guarded_hit`

        那一套守卫更完整（从句切分、第三人称归属、紧邻否定、假设语气、
        过去叙述），但它是安全模块的私有件、且要求先做 NFKC 归一化。
        把一个安全关键件的调用面扩大，代价不成比例。这里只做紧邻否定
        这一道，而判据 `test_she_can_say_no_in_her_own_words.py` 把两个
        方向都钉死，所以两处守卫不会在要紧的用例上悄悄分叉。
        """
        for match in re.finditer(YouHuoEngine._CANCEL_FORMS, text):
            #: 只看紧挨着的一小段：整段前缀会让「不是说算了……算了吧」
            #: 里后一个真的取消被前面那个否定压掉。
            before = text[max(0, match.start() - 4): match.start()]
            if re.search(YouHuoEngine._CANCEL_NEGATED, before):
                continue
            return True
        return False

    @staticmethod
    def _looks_like_chitchat(text: str) -> bool:
        return companion.sounds_like_chitchat(text)

    # ------------------------------------------------------------ 语音可达层
    @property
    def v4(self):
        """Care-feature store over the same connection, built on first use."""
        if self._v4 is None:
            from .v4_store import V4FeatureStore

            self._v4 = V4FeatureStore(self.db)
        return self._v4

    @property
    def v6(self):
        if self._v6 is None:
            from .v6_store import V6FeatureStore

            self._v6 = V6FeatureStore(self.db)
        return self._v6

    def _record_emotion_signal(
        self, actor: AuthContext, session: SessionState, text: str, emotion: EmotionAnalysis
    ) -> None:
        """把这一轮识别到的情绪落进 `emotion_events`，家人端的「心情」才有真数据。

        ## 为什么必须在引擎里写

        `EmotionAnalyzer.analyze()` 每轮对话都跑，但此前只被读了
        `should_pause_task` 一个字段，结果随后丢弃。`emotion_events` 唯一的生产
        写入方是 `POST /v4/emotions/analyze`，而**网页老人端从不调它**——那条端点
        的调用方只有 `/stage` 的演示按钮和 ArkTS。于是真实部署里这张表永远是空的，
        两处「心情」界面（家人端照护页的「心情」段与「可以做的小事」、
        `GET /api/v1/emotions/review`）只在吃 `seed_demo_content` 的演示种子：
        **答辩机上有内容，真用起来永远空着，而两边都不报错。**

        ## 为什么不是每轮都写

        判据是 `evidence_categories` 非空——那是**分析器自己说「我确实识别到了
        东西」**的字段。中性对话（「帮我交水费」「今天有什么安排」）走 `calm`
        分支，`categories` 是空列表（`v4_services.py` 里它只在有命中词时 append）。
        用这个字段而不是自己定一个 distress 阈值：阈值是我凭空定的，而这个字段
        是分析器的判断。报告按类别计数并聚合趋势，把每轮中性对话都记下来会把
        分母灌满，趋势就成了噪声。

        ## 隐私边界

        `add_emotion_event` 只存 `text_digest`（SHA-256）与 `privacy_safe_note`，
        **原文一个字都不落库**。界面上那句「您和无忧伴聊过的话不会出现在这里」
        是对老人的承诺，审计里的 `raw_text_stored: False` 也必须仍然为真。
        所以 `text` 只是交给 store 去算摘要，绝不能绕过它自己往表里写别的列。

        ## 记账失败不能吃掉这一轮对话

        记心情是附带的簿记。写失败绝不能把一次正常的问答变成 500——老人看到的
        会是「助手坏了」，而坏掉的只是统计。所以兜住异常，但**记一条审计**：
        静默吞掉才是这个仓库真正栽过的形状。
        """
        if not emotion.evidence_categories:
            return
        try:
            event = self.v4.add_emotion_event(
                actor.family_id, actor.actor_id, text, "companion", emotion
            )
        except Exception as exc:  # noqa: BLE001 —— 见上面「记账失败不能吃掉这一轮对话」
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "EMOTION_SIGNAL_RECORD_FAILED",
                session.session_id,
                {"error_type": type(exc).__name__, "raw_text_stored": False},
            )
            return
        self.db.append_audit(
            actor.family_id,
            actor.actor_id,
            "EMOTION_SIGNAL_RECORDED",
            event.id,
            {
                "label": emotion.label.value,
                "distress_band": round(emotion.distress, 1),
                "evidence_categories": list(emotion.evidence_categories),
                "raw_text_stored": False,
                "session_id": session.session_id,
            },
        )

    def _resolve_care_query(
        self, actor: AuthContext, session: SessionState, intent: care_voice.CareIntent, text: str
    ) -> care_voice.CareAnswer:
        """Answer from authoritative state. Read-only except the elder's own profile."""
        now = self.services.clock.now()
        family_id, elder_id = actor.family_id, actor.actor_id

        if intent is care_voice.CareIntent.REPEAT:
            with self._lock:
                last = self._last_spoken.get(session.session_id)
            return care_voice.answer_repeat(last)

        if intent is care_voice.CareIntent.CAPABILITY_HELP:
            return care_voice.answer_capability_help()

        if intent is care_voice.CareIntent.ORIENTATION:
            return care_voice.answer_orientation(now=now)

        if intent is care_voice.CareIntent.SYMPTOM_MENTION:
            return care_voice.answer_symptom_mention()

        if intent in {
            care_voice.CareIntent.SPEAK_SLOWER,
            care_voice.CareIntent.SPEAK_FASTER,
            care_voice.CareIntent.HEARING_SUPPORT,
        }:
            profile = self.v6.get_profile(family_id, elder_id)
            answer = care_voice.adjust_profile(intent, profile)
            assert answer is not None  # the three intents above are exhaustive
            if answer.profile_update:
                from .v6_models import InteractionProfileUpdate

                merged = profile.model_dump(
                    exclude={"family_id", "updated_by", "updated_at", "version"}
                )
                merged.update(answer.profile_update)
                self.v6.upsert_profile(family_id, actor, InteractionProfileUpdate(**merged))
            return answer

        if intent is care_voice.CareIntent.MEDICATION_TODAY:
            plans = self.v4.list_medication_plans(family_id, elder_id)
            today = now.date()
            adherence = self.v4.medication_adherence(family_id, elder_id, today, today)
            return care_voice.answer_medication_today(plans=plans, adherence=adherence, now=now)

        if intent is care_voice.CareIntent.MEDICATION_STOCK:
            from .v4_services import InventoryService

            plans = [p for p in self.v4.list_medication_plans(family_id, elder_id) if p.active]
            named = care_voice.match_plans_by_name(plans, text)
            narrowed = bool(named)
            if narrowed:
                plans = named
            forecasts = [
                (
                    plan,
                    InventoryService.forecast(
                        plan_id=plan.id,
                        stock_units=plan.stock_units,
                        units_per_dose=plan.units_per_dose,
                        doses_per_day=len(plan.times_local),
                        today=now.date(),
                    ),
                )
                for plan in plans
            ]
            return care_voice.answer_medication_stock(
                forecasts=forecasts, text=text, narrowed=narrowed
            )

        if intent is care_voice.CareIntent.MEDICATION_LIST:
            return care_voice.answer_medication_list(
                plans=self.v4.list_medication_plans(family_id, elder_id)
            )

        if intent is care_voice.CareIntent.HEALTH_RECENT:
            events = self.v4.list_health_events(family_id, elder_id, ActorRole.ELDER)
            return care_voice.answer_health_recent(events=events, now=now)

        if intent is care_voice.CareIntent.SCHEDULE_TODAY:
            horizon = int(care_voice.SCHEDULE_HORIZON.total_seconds() // 60)
            reminders = [
                item
                for item in self.db.upcoming_reminders(now, horizon, family_id)
                if item.elder_id == elder_id
            ]
            return care_voice.answer_schedule_today(reminders=reminders, now=now)

        # CONTACT_REACH
        contacts = self.v4.list_contacts(family_id, elder_id, ActorRole.ELDER)
        return care_voice.answer_contact_reach(contacts=contacts, text=text)

    def _companion_context(self, session_id: str) -> companion.CompanionContext:
        """Short-term, in-process context only: labels and counts, no utterances.

        Deliberately not persisted. Design §6.2 permits short-term context but
        not a stored transcript, and keeping it in memory makes that structural
        rather than a promise.
        """
        with self._lock:
            context = self._companion_contexts.get(session_id)
            if context is None:
                context = companion.CompanionContext()
            _remember(self._companion_contexts, session_id, context)
            return context

    # ------------------------------------------------------------------ 小优的大脑
    #: 查询工具名 -> 照护问答的意图。**事实都从 `_resolve_care_query` 出**：那是
    #: 「只读、从权威状态回答」的现成接口，每一句都有判据守着。给模型另写一套
    #: 查询，迟早和老人端屏幕上的说法对不上。`unpaid_bills` 单独实现（照护问答里
    #: 没有账单那一类）。判据逐个核对 `agent_brain.FACT_TOOLS` 每个名字都在这里有实现。
    _AGENT_FACT_INTENTS: dict[str, care_voice.CareIntent] = {
        "schedule_today": care_voice.CareIntent.SCHEDULE_TODAY,
        "medication_today": care_voice.CareIntent.MEDICATION_TODAY,
        "medication_list": care_voice.CareIntent.MEDICATION_LIST,
        "medication_stock": care_voice.CareIntent.MEDICATION_STOCK,
        "health_recent": care_voice.CareIntent.HEALTH_RECENT,
        "family_contacts": care_voice.CareIntent.CONTACT_REACH,
        "today_date": care_voice.CareIntent.ORIENTATION,
    }

    def _agent_respond(
        self, actor: AuthContext, session: SessionState, text: str, *, companion: bool
    ) -> Any | None:
        """问一次大脑并记账。没配、交回引擎的那一趟、出任何错，都返回 None。"""
        if self.agent is None or self._agent_suspended:
            return None
        try:
            reply = self.agent.respond(
                session_id=session.session_id,
                text=text,
                companion=companion,
                now_text=self._agent_now_text(),
                display_name=actor.display_name,
                run_fact=lambda name, args: self._agent_fact(actor, session, name, args, text),
            )
        except Exception:
            return None
        if reply is None:
            return None
        # 只记用了哪些工具、耗时、交给了哪类差事——**不记原话**。
        self.db.append_audit(
            actor.family_id,
            actor.actor_id,
            "AGENT_TURN",
            session.session_id,
            {
                "mode": Mode.COMPANION.value if companion else Mode.YOUHUO.value,
                "source": reply.source,
                "tools": list(reply.tools),
                "handoff": reply.handoff_kind,
                "latency_ms": reply.latency_ms,
                "model": self.agent.config.model,
                "raw_text_stored": False,
            },
        )
        return reply

    def _agent_meta(self, reply: Any) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "source": reply.source,
            "tools": list(reply.tools),
            "model": self.agent.config.model if self.agent else None,
        }
        if reply.handoff_kind:
            meta["handoff"] = {"kind": reply.handoff_kind, "utterance": reply.handoff_utterance}
        return meta

    def _agent_turn(
        self, actor: AuthContext, session: SessionState, text: str, *, companion: bool = False
    ) -> ChatResponse | None:
        """引擎认不出的一句话，交给大脑。返回 None 表示照原来的路走。"""
        reply = self._agent_respond(actor, session, text, companion=companion)
        if reply is None:
            return None
        meta = self._agent_meta(reply)
        if reply.handoff_kind:
            # 模型只是把她的话改写成一件差事。办不办、怎么办，照旧由引擎和她本人定：
            # 不带模型再走一遍那句话，引擎自己的分类器说了算（它认成别的差事，
            # 就按它认的办；它也认不出，就给菜单，不再回头问模型）。
            self._agent_suspended = True
            try:
                handed = self._handle_uncached(actor, session, reply.handoff_utterance or text)
            finally:
                self._agent_suspended = False
            return handed.model_copy(update={
                "ui": {**handed.ui, "agent": True},
                "data": {**handed.data, "agent": meta},
            })
        if not reply.message:
            return None
        data: dict[str, Any] = {"agent": meta}
        if reply.source == "facts":
            # 查到的事实带上照护问答的意图，老人端就标「按待办回答」「按用药记录回答」
            # ——而不是「闲聊」。标成闲聊，等于告诉她（和评委）这句是随口说的。
            first = next((self._AGENT_FACT_INTENTS[t] for t in reply.tools
                          if t in self._AGENT_FACT_INTENTS), None)
            if first is not None:
                data["care_intent"] = first.value
        return self._response(
            ResponseCode.CHAT,
            reply.message,
            session,
            ui={"theme": "blue", "speak": True, "agent": True},
            data=data,
        )

    def _companion_line(
        self, actor: AuthContext, session: SessionState, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """无忧伴的一句话。模板照旧**先**算：它记主题、数轮次、决定要不要提议联系家人。"""
        template, offered = self._companion_reply_ex(text, session.session_id)
        if offered:
            # 孤独感持续出现时，模板这一句会提议联系家人。那是一条要照原样说出口的
            # 规矩，不交给模型改写。
            return template, None
        reply = self._agent_respond(actor, session, text, companion=True)
        if reply is None or reply.handoff_kind or not reply.message:
            return template, None
        return reply.message, self._agent_meta(reply)

    def _agent_fact(
        self, actor: AuthContext, session: SessionState, name: str, args: dict[str, Any], text: str
    ) -> FactResult | None:
        """大脑要查的一件事。返回的那句话会**原样**念给她听（agent_brain 第 2 条规矩）。"""
        if name == "unpaid_bills":
            return FactResult(self._unpaid_bills_line(actor))
        intent = self._AGENT_FACT_INTENTS.get(name)
        if intent is None:
            return None
        query = text
        if intent is care_voice.CareIntent.MEDICATION_STOCK and args.get("name"):
            query = str(args["name"])[:40]
        answer = self._resolve_care_query(actor, session, intent, query)
        self.db.append_audit(
            actor.family_id,
            actor.actor_id,
            answer.audit_event,
            session.session_id,
            {"intent": intent.value, "via": "agent", **answer.data},
        )
        return FactResult(answer.message)

    def _unpaid_bills_line(self, actor: AuthContext) -> str:
        try:
            rows = [row for row in self.db.list_bills(actor.family_id) if not row["paid"]]
        except Exception:
            return "账单这会儿查不到，您稍后再问我一次。"
        if not rows:
            return "现在没有要缴的账单。"
        parts: list[str] = []
        for row in rows[:3]:
            amount = int(row["amount_cents"] or 0) / 100
            due = str(row["due_date"] or "")
            when = ""
            if len(due) >= 10 and due[4] == "-" and due[5:7].isdigit() and due[8:10].isdigit():
                when = f"，{int(due[5:7])}月{int(due[8:10])}日前"
            parts.append(f"{row['bill_type']}{amount:.2f}元{when}")
        return "还没缴的有：" + "；".join(parts) + "。要缴哪一笔，跟我说一声就行。"

    @staticmethod
    def _unwell_is_someone_elses(text: str) -> bool:
        """这句「不舒服」说的是别人吗。复用安全策略那套第三人称判断。

        按**不适词所在的位置**判主语——「隔壁他摔倒了，我扶不起来」句末的主语是「我」，
        按句末判会判错；一个不适词都没有时按每个分句的句末判。用
        `test_someone_elses_emergency_does_not_page_her_family.py` 的两组语料标定过：
        她自己的 0 条误判，别人的 0 条漏判。
        """
        clauses = [c for c in re.split(r"[。！？；.!?;\n]+", text) if c.strip()]
        hits: list[bool] = []
        for clause in clauses:
            for word in _URGENT_WORDS:
                for match in re.finditer(re.escape(word), clause):
                    hits.append(SafetyPolicy._event_belongs_to_other_person(clause, match.start()))
        if hits:
            return all(hits)
        return bool(clauses) and all(
            SafetyPolicy._event_belongs_to_other_person(c, len(c)) for c in clauses)

    def _agent_now_text(self) -> str:
        now = local_now(self.services.clock.now())
        week = "一二三四五六日"[now.weekday()]
        return f"{now.month}月{now.day}日 星期{week} {now:%H:%M}"

    def _companion_reply(self, text: str, session_id: str = "") -> str:
        return self._companion_reply_ex(text, session_id)[0]

    def _companion_reply_ex(self, text: str, session_id: str = "") -> tuple[str, bool]:
        """同上，外加「这一句有没有提议联系家人」——大脑接手时要知道这个。"""
        if not session_id:
            reply, _, _ = companion.compose_reply(text, companion.CompanionContext())
            return reply, False
        context = self._companion_context(session_id)
        reply, theme, offered = companion.compose_reply(text, context)
        # Only the theme label is auditable; the family never sees chat content.
        self.db.append_audit(
            self.db.get_session(session_id).family_id if self.db.get_session(session_id) else "fam-demo",
            "system",
            "COMPANION_THEME_OBSERVED",
            session_id,
            {"theme": theme.value, "turn": context.turns, "suggested_contact": offered},
        )
        return reply, offered

    def _doctor_prompt(self, task: TaskRecord) -> str:
        hospital = task.slots.get("hospital")
        department = task.slots.get("department")
        if hospital and department:
            doctors = self.services.hospital.doctors(str(hospital), str(department))
            if doctors:
                return "可选医生和时间：" + "；".join(f"{d}（{'、'.join(times)}）" for d, times in doctors.items()) + "。"
        return "请选择医生。"

    def _time_prompt(self, task: TaskRecord) -> str:
        hospital = task.slots.get("hospital")
        department = task.slots.get("department")
        doctor = task.slots.get("doctor")
        if hospital and department and doctor:
            times = self.services.hospital.doctors(str(hospital), str(department)).get(str(doctor), [])
            if times:
                return f"{doctor}可选时间：{'、'.join(times)}。"
        return "请选择就诊时间。"

    @staticmethod
    def _summary(task: TaskRecord) -> str:
        if task.task_type == TaskType.BILL_PAYMENT:
            amount = int(task.slots.get("amount_cents", 0)) / 100
            return f"支付{task.slots.get('period', '')}{task.slots.get('bill_type', '账单')} {amount:.2f}元"
        if task.task_type == TaskType.HOSPITAL_REGISTRATION:
            return (
                f"预约{task.slots.get('appointment_date', '')} {task.slots.get('appointment_time', '')}，"
                f"{task.slots.get('hospital', '')}{task.slots.get('department', '')}{task.slots.get('doctor', '')}"
            )
        if task.task_type == TaskType.REMINDER:
            return f"在{task.slots.get('due_date', '')} {task.slots.get('due_time', '')}提醒「{task.slots.get('title', '')}」"
        return "逐项语音辅助填写表单"

    def _nothing_to_confirm(self, actor: AuthContext, text: str) -> str | None:
        """她在确认或取消，而手上没有在办的事——把这件事说清楚。

        返回 `None` 表示这句话既不是确认也不是取消，照旧走通用菜单
        ——这一支只在 `task_type is None` 那一支里问，所以它抢不走
        任何一件真的差事。

        「嗯」「就这么办」这类**整句**应答算确认（`_is_bare_yes`，
        整句比对，不是子串）；「可以」「好的」不算，见
        `_VAGUE_AGREE_WORDS` 上面那段。「就这样办」目前两边都不认
        ——那是 `_is_yes` 自己的口径问题，动它会一起改掉**真的在
        执行**那条路，所以留在 `KNOWN_ISSUES` 里单独一轮再说。
        """
        normalized = text.replace(" ", "")
        cancelling = self._is_cancel(text)
        confirming = (
            not cancelling
            and not self._is_no(text)
            and (self._is_bare_yes(text)
                 or any(w in normalized for w in self._TASK_CONFIRM_WORDS))
        )
        if not (cancelling or confirming):
            return None
        said = text.strip()[:20]
        lead = f"「{said}」——" if said else ""
        if confirming:
            head = f"{lead}现在没有在等您确认的事，所以我没有办任何事。"
        else:
            head = f"{lead}现在没有在办的事，没有需要取消的。"
        return (head + self._last_task_note(actor)
                + "要办什么直接说就行，比如「帮我挂号」「查一下水费」。")

    def _last_task_note(self, actor: AuthContext) -> str:
        """上一件事的**事实**状态，一句话，不做推断。没有就回空串。

        `duplicate_blocked` 那一下最需要这一句：被拦下的那一笔状态是
        `cancelled`，而**同样的事之前已经办成过一次**。只说「已经取消」
        会让她以为号没挂上——那是一句会误导人的真话。所以按
        `semantic_key` 再对一次，用的正是重复守卫自己用的那把钥匙。
        """
        mine = [t for t in self.db.list_tasks(actor.family_id, limit=20)
                if t.elder_id == actor.actor_id]
        if not mine:
            return ""
        last = mine[0]
        if last.status == TaskStatus.COMPLETED:
            return f"您上一件事已经办好了：{self._summary(last)}。"
        if last.status == TaskStatus.CANCELLED:
            same = next((t for t in mine
                         if t.semantic_key == last.semantic_key
                         and t.status == TaskStatus.COMPLETED), None)
            if same is not None:
                return ("上一次说的那件没有重复办，同样的事之前已经办好了："
                        f"{self._summary(same)}。")
            return f"上一次说的那件已经取消，没有办：{self._summary(last)}。"
        if last.status == TaskStatus.FAILED:
            return f"上一件事没有办成：{self._summary(last)}。"
        return ""

    def _cancel_task(self, actor: AuthContext, session: SessionState, task: TaskRecord) -> ChatResponse:
        task.status = TaskStatus.CANCELLED
        task.result = {"cancelled_by": actor.actor_id}
        self.db.update_task(task)
        self.db.append_audit(task.family_id, actor.actor_id, "TASK_CANCELLED", task.id, {})
        return self._finish_task(session, self.db.get_task(task.id) or task, "好的，本次任务已经取消。", ResponseCode.TASK_CANCELLED)

    def _finish_task(self, session: SessionState, task: TaskRecord, message: str, code: ResponseCode) -> ChatResponse:
        session.active_task_id = None
        self.db.update_session(session)
        data = redact_payload(task.result)
        # Arm a one-turn undo. An elder who hears "已经设置提醒：复诊" and
        # immediately says "算了，不要了" means that reminder, but by then the task
        # is closed and the words used to fall through to the errand menu.
        reminder_id = task.result.get("reminder_id") if isinstance(task.result, dict) else None
        if reminder_id and code == ResponseCode.TASK_COMPLETED:
            with self._lock:
                _remember(
                    self._undoable_reminder,
                    session.session_id,
                    (str(reminder_id), str(task.result.get("title") or task.slots.get("title") or "这条提醒")),
                )
        with self._lock:
            errand = self._pending_errands.get(session.session_id)
        if errand:
            message += f" 您刚才还说要办{errand[0]}，现在办吗？"
            data = {**data, "pending_errand": errand[0], "errand_offer": True}
        if task.deferred_topics:
            # Design §5.2: actually offer to pick the parked topic back up, and
            # remember the offer so a plain "好啊" is understood next turn.
            topic = task.deferred_topics[-1]
            with self._lock:
                _remember(self._pending_topics, session.session_id, topic)
            message += " " + companion.resume_offer(topic)
            data = {**data, "resume_offer": True}
        return self._response(code, message, session, task, data=data)

    def _require_session(self, actor: AuthContext, session_id: str) -> SessionState:
        session = self.db.get_session(session_id)
        if session is None:
            raise EngineError("会话不存在，请先创建会话。")
        if session.family_id != actor.family_id or session.elder_id != actor.actor_id:
            raise AuthorizationError("会话不属于当前账户。")
        return session

    def _response(
        self,
        code: ResponseCode,
        message: str,
        session: SessionState,
        task: TaskRecord | None = None,
        *,
        ui: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> ChatResponse:
        # Remember our own line so "再说一遍" can repeat it verbatim. Repeating a
        # repeat would nest the prefix, so that one case is skipped.
        if (data or {}).get("care_intent") != care_voice.CareIntent.REPEAT.value:
            with self._lock:
                _remember(self._last_spoken, session.session_id, message)

        # 有任务就带上它的类型——**在这里一次，不在每个分支各补一遍**。
        #
        # 原先只有缴费那一个分支往 `data` 里放 `task_type`（见 `_process_bill` 里
        # 那段注释：「后端给的字段比屏幕上要说的话薄」）。实测（打接口，不是猜）：
        #
        #     「帮我交这个月的水费」 → data.task_type = 'bill_payment'
        #     「我想去医院挂个号」   → data.task_type = None（走完四轮都没出现）
        #     「提醒我明天吃药」     → data.task_type = None
        #
        # 后果是老人端状态行说「正在办**这件事**」而不是「正在办：挂号」，
        # Task Space 的主体同样退成「这件事」。前端为此在四个文件里各写了一张
        # 任务类型词表，其中三张还写了 `appointment` / `medication` 这种后端没有的
        # 键——**写表的人没见过真实的值**。
        #
        # 补在 `_response()` 而不是补那两个分支：缺口本来就是「一个分支记得、
        # 别的分支忘了」造成的，再补两处只是把同一个陷阱留给第四个分支。
        # 这里不覆盖调用方已经给的值（缴费分支自己填的那个和这里算的一样，
        # 但显式优先仍然是对的规矩）。
        payload = dict(data or {})
        if task is not None:
            payload.setdefault("task_type", task.task_type.value)

        return ChatResponse(
            code=code,
            message=message,
            mode=session.mode,
            task_id=task.id if task else None,
            task_status=task.status if task else None,
            risk_level=task.risk_level if task else None,
            approval_digest=task.approval_digest if task else None,
            ui=ui or {"theme": "orange" if session.mode == Mode.COMPANION else "blue", "speak": True},
            data=payload,
        )


__all__ = ["YouHuoEngine", "EngineError", "AuthorizationError", "IdempotencyConflict"]
