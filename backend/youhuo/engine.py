from __future__ import annotations

import os
import re
import threading
from datetime import UTC, datetime
from typing import Any

from .database import Database, IdempotencyConflict
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
from .v4_services import EmotionAnalyzer
from .utils import (
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
        # Built lazily: only sessions that ask a care question pay for the
        # schema init, and engines in unit tests that never do stay cheap.
        self._v4: Any | None = None
        self._v6: Any | None = None

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
            raise AuthorizationError("只有老人账户可以使用老人端语音会话。")
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
                    message=f"老人端检测到{signal.category}风险，请尽快联系确认。",
                )
            self.db.append_audit(
                actor.family_id,
                actor.actor_id,
                "SAFETY_SIGNAL",
                session.session_id,
                {"category": signal.category, "severity": signal.severity},
            )
            return self._response(ResponseCode.SAFETY_ALERT, signal.message, session, ui={"theme": "warning", "speak": True})

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
                    session.session_id, {"had_parked_topic": True},
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
            message = (
                "已经恢复蓝色优活办事模式，原任务和已填写信息都还在。请继续回答下一步。"
                if active_task
                else "已经切换到蓝色优活办事模式。请告诉我需要办理什么。"
            )
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
                    self._companion_reply(text, session.session_id)
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

        # "把刚才那个提醒取消掉" contains 提醒, so the errand classifier used to
        # read it as a request to *create* one and start asking which day. An
        # elder trying to undo something must not be handed a new task.
        if self._wants_reminder_cancelled(text):
            return self._cancel_recent_reminder(actor, session, text)

        # Voice reach for the care features. Deliberately only consulted where
        # the errand classifier found nothing, so it cannot shadow a real task:
        # "提醒我吃药" stays a reminder, "我今天吃药了吗" becomes an answer.
        care_intent = care_voice.classify(text) if task_type is None else None
        if care_intent is care_voice.CareIntent.SYMPTOM_MENTION and session.mode == Mode.COMPANION:
            # Mentioning an ache while chatting is a disclosure, not a service
            # request. 无忧伴 answers that better than a boundary statement does.
            care_intent = None
        if care_intent is not None:
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

        if session.mode == Mode.COMPANION and task_type is None:
            return self._response(
                ResponseCode.CHAT,
                self._companion_reply(text, session.session_id),
                session,
                ui={"theme": "orange", "speak": True, "privacy": "默认不向家属展示聊天全文"},
            )

        if task_type is None:
            return self._response(
                ResponseCode.CHAT,
                "我在听。您可以说「帮我挂号」「查一下水费」「提醒我明天下午吃药」，"
                "问「我今天吃药了吗」「我今天有什么事」，或者说「找无忧伴聊聊」。",
                session,
                ui={"theme": "blue", "speak": True},
            )

        if session.mode != Mode.YOUHUO:
            session.mode = Mode.YOUHUO
            self.db.update_session(session)
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
        if second is not None:
            label, second_type = second
            with self._lock:
                _remember(self._pending_errands, session.session_id, (label, second_type))
            return response.model_copy(update={
                "message": response.message + f" 另外{label}的事我记下了，这件办完再帮您办。",
                "data": {**response.data, "pending_errand": label},
            })
        return response

    def _start_errand(
        self, actor: AuthContext, session: SessionState, task_type: TaskType, text: str
    ) -> ChatResponse:
        """Open a task the elder already asked for, without re-parsing their reply.

        The accepting utterance is "好啊", which carries no slots. Seeding the task
        with the errand's own label ("缴费") keeps the record truthful without
        inventing a bill type or a hospital the elder never named.
        """
        if session.mode != Mode.YOUHUO:
            session.mode = Mode.YOUHUO
        task = self._new_task(actor, task_type, self._ERRAND_LABELS[task_type])
        self.db.create_task(task)
        session.active_task_id = task.id
        self.db.update_session(session)
        self.db.append_audit(
            actor.family_id, actor.actor_id, "TASK_CREATED", task.id,
            {"task_type": task.task_type.value, "risk": int(task.risk_level), "from_pending_errand": True},
        )
        return self._continue_task(actor, session, task, text, initial=True)

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
            if self._looks_like_chitchat(text):
                if text not in task.deferred_topics:
                    task.deferred_topics.append(text[:180])
                    self.db.update_task(task)
                    task = self.db.get_task(task.id) or task
                return self._response(
                    ResponseCode.NEED_ELDER_CONFIRMATION,
                    "这件事正在等您确认。刚才的话题已经暂存，办完后我们再接着聊。请说「确认办理」或「取消任务」。",
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
                return self._response(
                    ResponseCode.NEED_ELDER_CONFIRMATION,
                    f"我没太听清。这件事是：{self._summary(task)}。"
                    "对的话说「确认办理」，要改说「改成……」，不办说「取消任务」。",
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
            return self._response(
                ResponseCode.NEED_FAMILY_APPROVAL,
                "已经向家人发送确认请求。优活不会在家人确认前执行高风险操作。",
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
        if not initial and self._looks_like_chitchat(text):
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
        return response

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
        acknowledgement = self._describe_change(changed or {})
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
        ask = (
            f"请您把金额说一遍，例如「确认支付{amount:.2f}元」；不想办就说「取消任务」。"
            if teach_back
            else "是否确认生成家属支付请求？请明确说「确认办理」或「取消任务」。"
        )
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
        return self._response(
            ResponseCode.NEED_ELDER_CONFIRMATION,
            f"请确认：在{task.slots['due_date']} {task.slots['due_time']}提醒您「{task.slots['title']}」。",
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
            self.services.notification.send(
                self.db,
                family_id=task.family_id,
                recipient_role=ActorRole.FAMILY,
                event_type="approval_required",
                entity_id=task.id,
                message=f"老人请求办理：{self._summary(task)}。请在家属端核对后确认。",
            )
            self.db.append_audit(
                task.family_id,
                actor.actor_id,
                "ELDER_CONFIRMED",
                task.id,
                {"version": task.version, "approval_digest": task.approval_digest},
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
                "老人端确认完成，已向家人发送接力请求。家人确认前不会执行支付或身份类操作。",
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
                if reminder.status == ReminderStatus.COMPLETED:
                    message = "这件事已经完成，不需要重复操作。"
                    code = ResponseCode.DUPLICATE_BLOCKED
                else:
                    self.db.update_reminder_status(reminder.id, ReminderStatus.COMPLETED, "completed_at", now)
                    message = "这件事已标记完成，我们做得可真棒。"
                    code = ResponseCode.TASK_COMPLETED
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
        if any(k in text for k in ["身份证", "银行卡", "人脸认证", "医疗记录"]):
            slots["face_verification" if "人脸" in text else "sensitive_form"] = True
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
        TaskType.REMINDER: ("提醒", "日历", "待办", "别忘了"),
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

    @classmethod
    def _is_yes(cls, text: str) -> bool:
        normalized = text.replace(" ", "")
        if any(k in normalized for k in ["不确认", "不要", "不用", "不办", "算了", "取消"]):
            return False
        if cls._is_bare_yes(text):
            return True
        return any(k in normalized for k in ["确认办理", "确认", "可以", "好的", "办吧", "交吧", "没问题", "是的"])

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
        pending = [
            item
            for item in self.db.list_reminders(actor.family_id, limit=100)
            if item.elder_id == actor.actor_id
            and item.status in {ReminderStatus.SCHEDULED, ReminderStatus.NOTIFIED, ReminderStatus.ACKNOWLEDGED}
        ]
        if not pending:
            return self._response(
                ResponseCode.OK, "您现在没有待办提醒，没有需要取消的。", session,
                ui={"theme": "blue", "speak": True},
            )
        named = [item for item in pending if item.title and item.title in text]
        target = named[0] if len(named) == 1 else (pending[0] if len(pending) == 1 else None)
        if target is None:
            listed = "；".join(
                f"{item.due_at.strftime('%m月%d日 %H:%M')}{item.title}" for item in pending[:3]
            )
            return self._response(
                ResponseCode.NEED_MORE_INFO,
                f"您有{len(pending)}条提醒：{listed}。要取消哪一条？说出它的名字就行。",
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
            f"已经取消提醒：{target.title}，原定{target.due_at.strftime('%m月%d日 %H:%M')}。",
            session,
            data={"cancelled_reminder_id": target.id},
            ui={"theme": "blue", "speak": True},
        )

    @staticmethod
    def _sounds_unsure(text: str) -> bool:
        """"我不知道" is an answer. Repeating the question at it is not a reply."""
        return any(k in text for k in [
            "不知道", "不清楚", "不懂", "说不好", "拿不准", "随便", "都行", "你看着办", "你决定",
        ])

    @staticmethod
    def _is_cancel(text: str) -> bool:
        return any(k in text for k in ["取消任务", "停止办理", "不办了", "算了"])

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

    def _companion_reply(self, text: str, session_id: str = "") -> str:
        if not session_id:
            reply, _, _ = companion.compose_reply(text, companion.CompanionContext())
            return reply
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
        return reply

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
        return ChatResponse(
            code=code,
            message=message,
            mode=session.mode,
            task_id=task.id if task else None,
            task_status=task.status if task else None,
            risk_level=task.risk_level if task else None,
            approval_digest=task.approval_digest if task else None,
            ui=ui or {"theme": "orange" if session.mode == Mode.COMPANION else "blue", "speak": True},
            data=data or {},
        )


__all__ = ["YouHuoEngine", "EngineError", "AuthorizationError", "IdempotencyConflict"]
