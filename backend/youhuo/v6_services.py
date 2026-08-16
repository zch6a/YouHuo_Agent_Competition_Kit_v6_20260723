from __future__ import annotations

import hashlib
import os
import re
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from .llm import LLMConfigurationError, OpenAICompatibleConfig, StructuredIntentClient
from .models import TaskRecord, TaskStatus, TaskType
from .security import SafetyPolicy
from .utils import canonical_json, clean_user_text, combine_date_time, restore_cjk_punctuation
from .v5_models import ActionAuthorizeRequest, AuthorizationDecision, DataFact, DataOrigin, DataSensitivity
from .v5_services import PurposeBoundPolicy
from .v6_models import (
    CompetitionEvidenceBoard,
    CompetitionEvidenceItem,
    ConfirmationStyle,
    InteractionPlan,
    InteractionPlanRequest,
    InteractionProfile,
    RelianceCard,
    RelianceCardRequest,
    SafePreview,
    SafePreviewRequest,
    SemanticFrame,
    SemanticParseRequest,
    SourceEvidence,
    StudyObservation,
    StudySummary,
    TaskGlassBox,
    VerbosityMode,
)


class CognitiveLoadGovernor:
    """Adapts a turn to an older adult's interaction profile.

    The governor deliberately does not decide business authorization. It only
    controls how much information is presented and how confirmation is asked.
    """

    _JARGON = {
        "身份认证": "确认是您本人",
        "授权": "同意让系统使用",
        "提交": "正式办理",
        "撤销": "取消并恢复",
        "审批": "请家人确认",
        "地理围栏": "常用活动范围",
        "异常": "和平时不一样",
        "凭据": "证明信息",
        "幂等": "重复点击也只办理一次",
    }

    @classmethod
    def plan(cls, profile: InteractionProfile, request: InteractionPlanRequest) -> InteractionPlan:
        message = cls._simplify(request.message)
        max_chars = profile.max_sentence_chars
        if profile.verbosity == VerbosityMode.CONCISE:
            max_chars = min(max_chars, 32)
        elif profile.verbosity == VerbosityMode.GENTLE:
            max_chars = min(max_chars + 10, 90)

        low_confidence = request.asr_confidence < (0.88 if request.risk_level >= 3 else 0.72)
        # Observed comprehension closes the loop: the governor stops guessing at
        # difficulty from risk alone and reacts to how this elder actually did on
        # previous teach-backs. `struggling` is only ever set from real outcomes.
        struggling = bool(request.comprehension_difficulty >= 0.34)
        overloaded = request.recent_retries >= 2 or struggling
        high_risk = request.risk_level >= 3
        one_question_mode = high_risk or low_confidence or overloaded

        sentences = cls._sentences(message)
        if one_question_mode:
            visual_text = sentences[0] if sentences else message
        else:
            keep = 2 if profile.verbosity != VerbosityMode.CONCISE else 1
            visual_text = "。".join(sentences[:keep]) or message
        visual_text = cls._truncate_at_boundary(visual_text, max_chars)
        # _sentences strips terminal punctuation and the join only puts it back
        # between sentences, so the last one used to end mid-air.
        if visual_text and visual_text[-1] not in "。！？…":
            visual_text += "。"

        max_options = 1 if one_question_mode and high_risk else profile.max_options
        visible_options = request.options[:max_options]
        hidden_count = max(0, len(request.options) - len(visible_options))

        require_teach_back = bool(
            request.force_teach_back
            or (profile.teach_back_high_risk and high_risk)
            or (high_risk and not request.reversible)
            # An elder who has recently mis-stated a value gets teach-back even
            # on a step that would otherwise have been a plain yes/no.
            or (struggling and request.risk_level >= 2)
        )
        require_repeat = bool(profile.repeat_sensitive and (low_confidence or request.recent_retries > 0))

        if require_teach_back:
            confirmation_style = ConfirmationStyle.TEACH_BACK
            speak_text = f"{visual_text}。为了避免办错，请您用自己的话再说一遍要办理的内容。"
            expected = "老人复述关键对象、金额或时间"
        elif request.risk_level >= 4:
            confirmation_style = ConfirmationStyle.FAMILY_RELAY
            speak_text = f"{visual_text}。这一步需要您先确认，再请家人接力。"
            expected = "老人确认后等待家属审批"
        else:
            confirmation_style = ConfirmationStyle.YES_NO
            speak_text = visual_text
            if visible_options:
                speak_text += "。您可以说：" + "，".join(visible_options)
            expected = "老人选择一个选项或要求重复"

        if require_repeat:
            speak_text = "我刚才没有完全听清。" + speak_text
        if hidden_count:
            speak_text += f"。还有{hidden_count}个选择，需要时我再慢慢说。"

        length_component = min(1.0, len(speak_text) / max(1, profile.max_sentence_chars * 2))
        option_component = min(1.0, len(request.options) / 4)
        risk_component = request.risk_level / 4
        retry_component = min(1.0, request.recent_retries / 3)
        uncertainty_component = 1.0 - request.asr_confidence
        comprehension_component = request.comprehension_difficulty
        score = min(
            1.0,
            0.26 * length_component
            + 0.17 * option_component
            + 0.19 * risk_component
            + 0.12 * retry_component
            + 0.12 * uncertainty_component
            + 0.14 * comprehension_component,
        )

        rationale: list[str] = []
        if one_question_mode:
            rationale.append("当前采用一次只问一件事，降低工作记忆负担。")
        if visible_options:
            rationale.append(f"本轮最多展示{len(visible_options)}个选项。")
        if require_teach_back:
            rationale.append("高风险步骤使用复述确认，而不是只问‘是/否’。")
        if low_confidence:
            rationale.append("语音置信度不足，优先澄清，不猜测。")
        if overloaded:
            rationale.append("连续重试较多，自动缩短句子并减少选项。")
        if struggling:
            rationale.append("最近的复述确认出现过听错，本轮进一步放慢并加强核对。")
        if not request.reversible:
            rationale.append("操作不可轻易撤销，确认强度提高。")

        digest = hashlib.sha256(
            canonical_json(
                {
                    "profile": profile.model_dump(mode="json"),
                    "request": request.model_dump(mode="json"),
                    "speak_text": speak_text,
                    "visible_options": visible_options,
                    "teach_back": require_teach_back,
                }
            ).encode("utf-8")
        ).hexdigest()
        return InteractionPlan(
            mode="one_question" if one_question_mode else "guided",
            speak_text=speak_text,
            visual_text=visual_text,
            visible_options=visible_options,
            hidden_option_count=hidden_count,
            # Someone who has been mishearing values also gets slower speech.
            speech_rate=profile.speech_rate * (0.92 if require_repeat else 1.0) * (0.94 if struggling else 1.0),
            font_scale=profile.font_scale,
            require_repeat_confirmation=require_repeat,
            require_teach_back=require_teach_back,
            confirmation_style=confirmation_style,
            cognitive_load_score=round(score, 6),
            turn_budget=1 if one_question_mode else min(3, max(1, len(visible_options))),
            next_expected_response=expected,
            rationale=rationale,
            comprehension_difficulty=round(request.comprehension_difficulty, 6),
            plan_digest=digest,
        )

    @classmethod
    def _simplify(cls, text: str) -> str:
        # clean_user_text stays: the message can carry text that came from a tool
        # and must not smuggle control characters onto the elder's screen. But its
        # NFKC pass turns every ，into a halfwidth comma, which is wrong in the
        # Chinese sentence the elder actually reads.
        result = restore_cjk_punctuation(clean_user_text(text, max_length=3000))
        for source, target in cls._JARGON.items():
            result = result.replace(source, target)
        result = re.sub(r"\s+", " ", result).strip()
        return result

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [piece.strip(" ，,。.!！？?；;") for piece in re.split(r"[。！？!?；;\n]+", text) if piece.strip()]

    @staticmethod
    def _truncate_at_boundary(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        candidate = text[:limit]
        for mark in ("，", ",", "、", "；", ";"):
            idx = candidate.rfind(mark)
            if idx >= max(8, limit // 2):
                return candidate[:idx]
        return candidate.rstrip() + "…"


class RelianceCardService:
    @staticmethod
    def build(request: RelianceCardRequest) -> RelianceCard:
        verified = sum(1 for item in request.evidence if item.verified)
        untrusted = [item.label for item in request.evidence if not item.trusted]
        if request.risk_level >= 4:
            who = "老人确认后，由绑定家属完成最终接力"
        elif request.risk_level >= 3:
            who = "老人本人决定是否继续，必要时家属共同确认"
        else:
            who = "老人本人决定，Agent只提供辅助"
        confidence = (
            f"已核验{verified}项来源。" if verified else "当前信息仍需核验，系统不会把推测当成事实。"
        )
        warning = None
        if untrusted:
            warning = "以下内容只作为参考，不会直接控制工具：" + "、".join(untrusted[:4])
        digest = hashlib.sha256(canonical_json(request.model_dump(mode="json")).encode("utf-8")).hexdigest()
        return RelianceCard(
            title="优活正在怎样帮助您",
            heard=request.heard_text,
            goal=request.goal,
            current_step=request.current_step,
            action_summary=f"准备执行：{request.action}（风险等级{request.risk_level}）",
            data_sources=[item.model_dump(mode="json") for item in request.evidence],
            who_decides=who,
            reversible=request.reversible,
            next_step=request.next_step,
            confidence_message=confidence,
            warning=warning,
            card_digest=digest,
        )


class SafePreviewService:
    @staticmethod
    def preview(request: SafePreviewRequest) -> SafePreview:
        authorization = PurposeBoundPolicy.authorize(
            ActionAuthorizeRequest(
                elder_id=request.elder_id,
                goal=request.goal,
                action=request.action,
                arguments=request.arguments,
                facts=request.facts,
                ambiguity=request.ambiguity,
                user_confirmed=request.user_confirmed,
                family_approvals=request.family_approvals,
                reversible=request.reversible,
                emergency=request.emergency,
            )
        )
        decision = authorization.decision
        if decision == AuthorizationDecision.ALLOW:
            summary = "安全预演通过；正式执行前仍会再次核对最终参数。"
        elif decision == AuthorizationDecision.REQUIRE_ELDER_CONFIRMATION:
            summary = "参数基本可用，但必须由老人本人确认后才能继续。"
        elif decision == AuthorizationDecision.REQUIRE_FAMILY_APPROVAL:
            summary = "该操作需要绑定家属接力，Agent不能独立完成。"
        elif decision == AuthorizationDecision.CLARIFY:
            summary = "信息存在歧义，系统将先澄清，不会猜测执行。"
        else:
            summary = "安全预演已阻断该操作。"

        will_do = [f"只使用允许字段：{key}" for key in authorization.allowed_arguments]
        if not will_do:
            will_do = ["不会产生真实副作用"]
        will_not = ["不会自动扣款", "不会读取或提交验证码", "不会把陪聊原文发送给家属"]
        if authorization.stripped_fields:
            will_not.append("不会使用被剥离字段：" + "、".join(authorization.stripped_fields))
        rollback = "操作支持撤销或补偿，失败时恢复到执行前状态。" if request.reversible else "操作不可自动撤销，因此必须提高人工确认强度。"
        data_use = []
        for fact in request.facts:
            trust = "可用于控制" if fact.trusted_for_control else "仅作参考"
            data_use.append(f"{fact.name}：用途={fact.purpose}，来源={fact.origin.value}，{trust}")
        digest = hashlib.sha256(
            canonical_json(
                {
                    "request": request.model_dump(mode="json"),
                    "authorization": authorization.model_dump(mode="json"),
                }
            ).encode("utf-8")
        ).hexdigest()
        return SafePreview(
            authorization=authorization,
            plain_summary=summary,
            will_do=will_do,
            will_not_do=will_not,
            required_humans=authorization.required_confirmations,
            rollback_plan=rollback,
            data_use_summary=data_use,
            preview_digest=digest,
        )


class TaskGlassBoxService:
    """Builds the design §4.3 glass box for a real task.

    The elder-facing card must describe the action in ordinary words and the
    preview must authorize the action the engine would actually run. Both are
    derived from the stored task, so neither can drift from what will happen.
    """

    #: task type -> (plain action label, registered policy action)
    _ACTIONS: dict[TaskType, tuple[str, str | None]] = {
        TaskType.BILL_PAYMENT: ("生成家属支付请求", "create_payment_request"),
        TaskType.HOSPITAL_REGISTRATION: ("预约挂号号源", "reserve_appointment"),
        TaskType.REMINDER: ("创建提醒", "create_reminder"),
        TaskType.FORM_ASSISTANCE: ("逐项语音辅助填写", None),
    }

    _STEP_WORDS: dict[TaskStatus, tuple[str, str]] = {
        TaskStatus.COLLECTING: ("正在收集需要的信息", "请回答下一个问题"),
        TaskStatus.AWAITING_ELDER_CONFIRMATION: ("等待您复述确认", "请您复述一遍要办的事"),
        TaskStatus.AWAITING_FAMILY_APPROVAL: ("等待家属接力确认", "请家人在家属端核对后确认"),
        TaskStatus.EXECUTING: ("正在执行", "请稍候，完成后会核对对方系统状态"),
        TaskStatus.COMPLETED: ("已完成并核验", "无需再操作"),
        TaskStatus.CANCELLED: ("已取消", "需要的话可以重新开始"),
        TaskStatus.FAILED: ("未成功，已安全停下", "可以重新发起，没有产生实际操作"),
    }

    @staticmethod
    def _fact(name: str, value: Any, purpose: str, *, trusted: bool) -> DataFact:
        return DataFact(
            name=name,
            value=value,
            origin=DataOrigin.TRUSTED_TOOL if trusted else DataOrigin.USER_VOICE,
            sensitivity=DataSensitivity.PERSONAL,
            purpose=purpose,
            trusted_for_control=trusted,
        )

    @classmethod
    def _payment(cls, task: TaskRecord) -> tuple[str, dict[str, Any], list[DataFact], list[SourceEvidence]]:
        slots = task.slots
        amount_cents = int(slots.get("amount_cents", 0) or 0)
        period = str(slots.get("period", "") or "")
        bill_type = str(slots.get("bill_type", "生活账单") or "生活账单")
        goal = f"{period}{bill_type}缴费".strip()
        arguments = {
            "bill_id": slots.get("bill_id"),
            "amount_cents": amount_cents,
            "elder_id": task.elder_id,
            "recipient_family_id": task.family_id,
        }
        facts = [
            cls._fact("amount_cents", amount_cents, "bill_payment", trusted=True),
            cls._fact("bill_id", slots.get("bill_id"), "bill_payment", trusted=True),
        ]
        evidence = [
            SourceEvidence(
                label=f"{period}{bill_type} {amount_cents / 100:.2f}元",
                source="账单服务",
                trusted=True,
                verified=True,
            )
        ]
        if slots.get("due_date"):
            evidence.append(
                SourceEvidence(label=f"缴费截止 {slots['due_date']}", source="账单服务", trusted=True, verified=True)
            )
        return goal, arguments, facts, evidence

    @staticmethod
    def _advisory(task: TaskRecord) -> set[str]:
        """Slot names a language model supplied; never presented as verified."""
        return set(task.slots.get("advisory_fields") or [])

    @classmethod
    def _registration(cls, task: TaskRecord) -> tuple[str, dict[str, Any], list[DataFact], list[SourceEvidence]]:
        slots = task.slots
        arguments = {
            "elder_id": task.elder_id,
            "hospital": slots.get("hospital"),
            "department": slots.get("department"),
            "doctor": slots.get("doctor"),
            "date": slots.get("appointment_date"),
            "time": slots.get("appointment_time"),
        }
        advisory = cls._advisory(task)
        # A hospital name the model guessed is not a verified tool value.
        hospital_trusted = "hospital" not in advisory
        facts = [
            cls._fact("hospital", slots.get("hospital"), "hospital_registration", trusted=hospital_trusted),
            cls._fact("department", slots.get("department"), "hospital_registration", trusted=False),
            cls._fact("date", slots.get("appointment_date"), "hospital_registration", trusted=False),
            cls._fact("time", slots.get("appointment_time"), "hospital_registration", trusted=False),
        ]
        evidence = [
            SourceEvidence(
                label=f"{slots.get('hospital', '医院')} 可预约号源",
                source="挂号服务" if hospital_trusted else "语音理解模型（待核验）",
                trusted=hospital_trusted,
                verified=hospital_trusted,
            ),
            SourceEvidence(
                label=f"{slots.get('department', '科室')} {slots.get('appointment_date', '')} {slots.get('appointment_time', '')}".strip(),
                source="语音理解模型（待核验）" if advisory & {"department", "appointment_date", "appointment_time"} else "老人语音",
                trusted=False,
                verified=False,
            ),
        ]
        return "医院挂号", arguments, facts, evidence

    @classmethod
    def _reminder(cls, task: TaskRecord) -> tuple[str, dict[str, Any], list[DataFact], list[SourceEvidence]]:
        slots = task.slots
        due_at = None
        if slots.get("due_date") and slots.get("due_time"):
            due_at = combine_date_time(str(slots["due_date"]), str(slots["due_time"]))
        arguments = {"elder_id": task.elder_id, "title": slots.get("title"), "due_at": due_at}
        facts = [cls._fact("title", slots.get("title"), "reminder", trusted=False)]
        evidence = [
            SourceEvidence(
                label=f"{slots.get('due_date', '')} {slots.get('due_time', '')} {slots.get('title', '待办')}".strip(),
                source="老人语音",
                trusted=False,
                verified=False,
            )
        ]
        return "提醒", arguments, facts, evidence

    @classmethod
    def build(cls, task: TaskRecord, heard_text: str, *, family_approvals: int) -> TaskGlassBox:
        action_label, policy_action = cls._ACTIONS[task.task_type]
        current_step, next_step = cls._STEP_WORDS[task.status]
        # The elder has already confirmed once the task left the confirmation state.
        user_confirmed = task.status in {
            TaskStatus.AWAITING_FAMILY_APPROVAL,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETED,
        }
        # A request that has not executed yet can still be withdrawn.
        reversible = task.status != TaskStatus.COMPLETED

        goal = "逐项语音辅助填写"
        arguments: dict[str, Any] = {}
        facts: list[DataFact] = []
        evidence: list[SourceEvidence] = []
        if task.task_type == TaskType.BILL_PAYMENT:
            goal, arguments, facts, evidence = cls._payment(task)
        elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
            goal, arguments, facts, evidence = cls._registration(task)
        elif task.task_type == TaskType.REMINDER:
            goal, arguments, facts, evidence = cls._reminder(task)

        confirmations = ["老人本人"]
        if int(task.risk_level) >= 4:
            confirmations.append("绑定家属")

        card = RelianceCardService.build(
            RelianceCardRequest(
                elder_id=task.elder_id,
                heard_text=heard_text,
                goal=goal,
                current_step=current_step,
                action=action_label,
                risk_level=int(task.risk_level),
                reversible=reversible,
                confirmations=confirmations,
                evidence=evidence,
                next_step=next_step,
            )
        )

        preview = None
        if policy_action is not None:
            preview = SafePreviewService.preview(
                SafePreviewRequest(
                    elder_id=task.elder_id,
                    goal=goal,
                    action=policy_action,
                    arguments={key: value for key, value in arguments.items() if value is not None},
                    facts=facts,
                    ambiguity=0.0,
                    user_confirmed=user_confirmed,
                    family_approvals=family_approvals,
                    reversible=True,
                    emergency=False,
                )
            )
        return TaskGlassBox(
            task_id=task.id,
            action_label=action_label,
            policy_action=policy_action,
            card=card,
            preview=preview,
        )


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


class SemanticGateway:
    """Constrained semantic parser with deterministic fallback.

    Remote model output is advisory and validated. The gateway never exposes a
    tool-call interface and never changes policy decisions.
    """

    ALLOWED_INTENTS = {
        "hospital_registration",
        "bill_payment",
        "reminder",
        "form_assistance",
        "companion",
        "emergency",
        "scam_risk",
        "cancel",
        "confirm",
        "unknown",
    }
    ALLOWED_SLOTS = {
        "hospital",
        "department",
        "doctor",
        "date",
        "time",
        "bill_type",
        "period",
        "amount_cents",
        "title",
        "due_at",
    }
    _state = _CircuitState()
    _lock = threading.Lock()

    @classmethod
    def parse(cls, request: SemanticParseRequest) -> SemanticFrame:
        heuristic = cls._heuristic(request.text)
        remote_requested = request.permit_remote_model and os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL")
        if remote_requested and cls._circuit_available():
            try:
                remote = cls._remote(request.text)
                cls._record_success()
                intent = remote.intent if remote.intent in cls.ALLOWED_INTENTS else "unknown"
                slots = {k: v for k, v in remote.extracted_slots.items() if k in cls.ALLOWED_SLOTS}
                confidence = min(float(remote.confidence), 0.95)
                needs = confidence < 0.72 or intent == "unknown"
                prompt = cls._clarification(intent) if needs else None
                return cls._frame(
                    intent=intent,
                    confidence=confidence,
                    slots=slots,
                    needs=needs,
                    prompt=prompt,
                    source="remote_model_validated",
                    model_used=True,
                    flags=heuristic[4],
                    text=request.text,
                )
            except Exception:
                cls._record_failure()
        return cls._frame(
            intent=heuristic[0],
            confidence=heuristic[1],
            slots=heuristic[2],
            needs=heuristic[3],
            prompt=cls._clarification(heuristic[0]) if heuristic[3] else None,
            source="deterministic_fallback",
            model_used=False,
            flags=heuristic[4],
            text=request.text,
        )

    @classmethod
    def _remote(cls, text: str):
        config = OpenAICompatibleConfig.from_env()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return StructuredIntentClient(config).classify(text)
            except (ValueError, LLMConfigurationError, Exception) as exc:  # network/model errors are advisory only
                last_error = exc
                if attempt == 0:
                    time.sleep(0.05)
        assert last_error is not None
        raise last_error

    @classmethod
    def _circuit_available(cls) -> bool:
        with cls._lock:
            return time.monotonic() >= cls._state.opened_until

    @classmethod
    def _record_success(cls) -> None:
        with cls._lock:
            cls._state.failures = 0
            cls._state.opened_until = 0.0

    @classmethod
    def _record_failure(cls) -> None:
        with cls._lock:
            cls._state.failures += 1
            if cls._state.failures >= 3:
                cls._state.opened_until = time.monotonic() + 30.0

    @classmethod
    def _heuristic(cls, text: str) -> tuple[str, float, dict[str, Any], bool, list[str]]:
        normalized = clean_user_text(text, max_length=2000)
        flags: list[str] = []
        # Reuse the same guarded safety detector as the main conversation path.
        # Maintaining a second keyword-only safety classifier here had drifted:
        # "我没有摔倒" became emergency and anti-fraud education became scam_risk.
        signal = SafetyPolicy.detect_safety_signal(normalized)
        if signal is not None and signal.category == "emergency":
            flags.append("possible_emergency")
            return "emergency", 0.98, {}, False, flags
        if signal is not None and signal.category == "suspected_scam":
            flags.append("possible_scam")
            return "scam_risk", 0.96, {}, False, flags
        if any(term in normalized for term in ("取消", "不办了", "算了")):
            return "cancel", 0.9, {}, False, flags
        # Scheduling verbs express the user's requested action even when the
        # reminder contains medical nouns such as 「复诊」.
        if any(term in normalized for term in ("提醒", "日历", "待办", "别忘了", "闹钟", "到时候叫我")):
            return "reminder", 0.88, {"title": normalized[:80]}, False, flags
        if any(term in normalized for term in ("挂号", "医院", "医生", "科室", "看病")):
            slots: dict[str, Any] = {}
            for hospital in ("第一医院", "人民医院", "中心医院"):
                if hospital in normalized:
                    slots["hospital"] = hospital
            for department in ("骨科", "内科", "眼科", "心内科", "神经内科"):
                if department in normalized:
                    slots["department"] = department
            time_match = re.search(r"(上午|下午|晚上)?\s*(\d{1,2})[点时]", normalized)
            if time_match:
                slots["time"] = "".join(piece for piece in time_match.groups() if piece)
            needs = not {"hospital", "department"}.issubset(slots)
            return "hospital_registration", 0.86 if not needs else 0.7, slots, needs, flags
        if any(term in normalized for term in ("水费", "电费", "燃气费", "缴费", "交费", "账单")):
            bill_type = next((term for term in ("水费", "电费", "燃气费") if term in normalized), None)
            needs = bill_type is None
            return "bill_payment", 0.88 if bill_type else 0.7, {"bill_type": bill_type} if bill_type else {}, needs, flags
        if any(term in normalized for term in ("聊聊", "无忧伴", "孤单", "陪我说说话")):
            return "companion", 0.9, {}, False, flags
        if any(term in normalized for term in ("确认", "没问题", "就这样")):
            return "confirm", 0.85, {}, False, flags
        return "unknown", 0.45, {}, True, flags

    @classmethod
    def _clarification(cls, intent: str) -> str:
        return {
            "hospital_registration": "请再告诉我医院和科室，一次说一个也可以。",
            "bill_payment": "请说清楚是水费、电费还是燃气费。",
            "unknown": "我还不确定您想办什么。可以说‘帮我挂号’、‘查水费’或‘提醒我’。",
        }.get(intent, "我没有完全听清，请您慢一点再说一遍。")

    @staticmethod
    def _frame(
        *,
        intent: str,
        confidence: float,
        slots: dict[str, Any],
        needs: bool,
        prompt: str | None,
        source: str,
        model_used: bool,
        flags: list[str],
        text: str,
    ) -> SemanticFrame:
        digest = hashlib.sha256(
            canonical_json(
                {
                    "text": text,
                    "intent": intent,
                    "confidence": confidence,
                    "slots": slots,
                    "needs": needs,
                    "source": source,
                }
            ).encode("utf-8")
        ).hexdigest()
        return SemanticFrame(
            intent=intent,
            confidence=round(confidence, 6),
            slots=slots,
            needs_clarification=needs,
            clarification_prompt=prompt,
            parser_source=source,
            model_used=model_used,
            safety_flags=flags,
            frame_digest=digest,
        )


class StudySummaryService:
    @staticmethod
    def summarize(sessions: list[Any], observations: list[StudyObservation]) -> StudySummary:
        durations = [item.duration_seconds for item in observations]
        successes = [1 if item.success else 0 for item in observations]
        return StudySummary(
            session_count=len(sessions),
            observation_count=len(observations),
            task_success_rate=round(sum(successes) / len(successes), 6) if successes else 0.0,
            median_duration_seconds=round(statistics.median(durations), 3) if durations else 0.0,
            mean_clarifications=round(statistics.fmean(item.clarification_count for item in observations), 3) if observations else 0.0,
            mean_assistance=round(statistics.fmean(item.assistance_count for item in observations), 3) if observations else 0.0,
            mean_perceived_ease=round(statistics.fmean(item.perceived_ease for item in observations), 3) if observations else 0.0,
            mean_trust_calibration=round(statistics.fmean(item.trust_calibration for item in observations), 3) if observations else 0.0,
            caution="这些指标只代表已录入的知情同意用户实验；空数据或模拟数据不得宣传为真实老人结论。",
        )


class CompetitionEvidenceService:
    @staticmethod
    def board(now: datetime | None = None) -> CompetitionEvidenceBoard:
        generated = now or datetime.now(UTC)
        return CompetitionEvidenceBoard(
            competition="中国高校计算机大赛—人工智能创意赛·鸿蒙高校创新赛·Agent创新方向",
            project_version="6.0.0",
            items=[
                CompetitionEvidenceItem(
                    dimension="创新性",
                    score_weight=50,
                    readiness="strong_prototype",
                    evidence=[
                        "认知负荷治理器：一次只问一件事、选项上限、复述确认",
                        "老人自主权包络与家庭接力",
                        "证明式完成、目的绑定策略与可恢复任务",
                        "玻璃盒依赖校准卡：告诉老人系统听到什么、为何确认、谁做决定",
                    ],
                    remaining_gap=["真实老人共创数据", "HarmonyOS真机端A2A伴随态展示"],
                ),
                CompetitionEvidenceItem(
                    dimension="作品完整度",
                    score_weight=20,
                    readiness="high_backend_medium_native",
                    # 「评委导览」是这一页改名前的旧称，现在它叫「事务证据工作台」。
                    # 同一轮改名只跟到了前端，后端这句字符串留在了原地——于是页面自己
                    # 报出的名字和它列举自己时用的名字对不上。
                    evidence=["老人端、家属端、照护中心、可信实验室、事务证据工作台", "挂号/缴费/提醒完整沙箱闭环", "自动化测试与专项Benchmark"],
                    remaining_gap=["DevEco Studio编译签名", "官方Core Speech、Push、Location正式联调"],
                ),
                CompetitionEvidenceItem(
                    dimension="前景评估",
                    score_weight=20,
                    readiness="credible",
                    evidence=["面向独居老人数字生活障碍", "家属只在关键节点介入", "工具适配器可扩展至社区/医院/公共服务"],
                    remaining_gap=["社区或养老机构合作意向", "真实服务接口与部署成本测算"],
                ),
                CompetitionEvidenceItem(
                    dimension="规范性",
                    score_weight=10,
                    readiness="strong",
                    evidence=["能力真值表与过度宣传禁区", "隐私、审计、权限和医学边界", "可复验脚本、依赖锁定与第三方声明"],
                    remaining_gap=["按最终官方模板逐项复核", "真机截图、发布态证据和原创性签署"],
                ),
            ],
            top_three_story=[
                "老人说一句跳跃、含糊的话，优活仍能锁住事务并降低认知负担。",
                "高风险步骤不靠模型自信，而由老人复述、家属接力、策略层和最终状态共同证明。",
                "系统明确告诉老人自己听到了什么、为什么要确认以及最终是否真的办成。",
            ],
            hard_no_claims=[
                "不宣称已接入真实医院、银行或支付清算系统",
                "不宣称提供医疗诊断或完整药品相互作用判断",
                "不宣称自动化测试等于真实老人实验",
                "不宣称HarmonyOS工程壳已经完成HAP真机验证",
                "不承诺绝对零错误或保证获得特定名次",
            ],
            generated_at=generated,
        )
