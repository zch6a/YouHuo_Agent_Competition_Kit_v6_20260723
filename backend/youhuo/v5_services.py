from __future__ import annotations

import hashlib
import hmac
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Iterable

from .security import SafetyPolicy
from .teach_back import parse_spoken_amount_cents
from .utils import canonical_json, clean_user_text, normalize_text, semantic_hash
from .utils import parse_time_text
from .v5_models import (
    ActionAuthorization,
    ActionAuthorizeRequest,
    AuthorizationDecision,
    DataOrigin,
    DataSensitivity,
    ExplanationCard,
    ProofEvent,
    ProofVerifyResult,
    SagaKind,
    SyncSensitivity,
    TaskProofBundle,
    VoiceResolutionStatus,
    VoiceTurnRequest,
    VoiceTurnResolution,
)


class VoiceConsensusEngine:
    """Resolve N-best ASR candidates conservatively for older-adult voice interaction.

    The engine deliberately prefers clarification over guessing when a turn can
    trigger side effects. It is deterministic and provider-agnostic so the same
    safety behavior applies to browser speech recognition, HarmonyOS ASR, or a
    realtime voice stack such as LiveKit.
    """

    _FILLERS = re.compile(r"(?:嗯+|呃+|那个|这个|就是|然后|麻烦你|帮我一下|请你)")
    _SPACES = re.compile(r"\s+")
    _NEGATION = {"不", "别", "取消", "不要", "不用", "停止"}
    _AFFIRMATION = {"确认", "同意", "可以", "继续", "办理", "提交"}
    _HIGH_RISK_TERMS = {"支付", "转账", "验证码", "密码", "身份证", "人脸", "银行卡", "删除"}
    _EMERGENCY_TERMS = {"救命", "摔倒", "起不来", "胸口痛", "呼吸困难", "煤气", "走失", "迷路"}
    _SCAM_TERMS = {"验证码", "安全账户", "刷流水", "屏幕共享", "远程控制", "先转账", "中奖"}

    @classmethod
    def _normalize(cls, text: str) -> str:
        text = clean_user_text(text, max_length=2000)
        text = cls._FILLERS.sub("", text)
        text = cls._SPACES.sub("", text)
        return text.strip("，。！？、 ")

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        if a == b:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()

    @classmethod
    def _intent(cls, text: str) -> str:
        """Return the task domain before the dialogue-control act.

        Older adults often say a control phrase and a domain in the same turn,
        for example ``确认办理水费`` or ``提醒我下周复诊``.  Returning only
        ``confirm`` or ``hospital_registration`` would lose the domain needed
        for a safe, concrete clarification.  The precedence below therefore
        keeps emergencies first, explicit reminder/scheduling acts ahead of
        medical nouns, and domain intents ahead of generic confirm/cancel acts.
        """
        signal = SafetyPolicy.detect_safety_signal(text)
        if signal is not None and signal.category == "emergency":
            return "emergency"

        reminder_terms = {"提醒", "日历", "待办", "记得", "闹钟", "到时候叫我", "别忘了"}
        if any(term in text for term in reminder_terms):
            return "reminder"

        domain_mapping = [
            ("bill_payment", {"水费", "电费", "燃气费", "缴费", "交费", "账单"}),
            ("hospital_registration", {"挂号", "医院", "医生", "科室", "骨科", "看病", "复诊"}),
            ("medication", {"吃药", "服药", "药量", "补药", "药盒"}),
            ("companion", {"聊聊", "陪我", "无忧伴", "心里", "孤单", "难过"}),
            ("navigation", {"导航", "怎么走", "药店", "菜市场", "在哪里"}),
        ]
        scores = [(name, sum(1 for term in terms if term in text)) for name, terms in domain_mapping]
        best_name, best_score = max(scores, key=lambda item: item[1])
        if best_score:
            return best_name

        if any(term in text for term in {"取消", "别办", "不要了", "停止"}):
            return "cancel"
        if any(term in text for term in cls._AFFIRMATION):
            return "confirm"
        return "unknown"

    @classmethod
    def _contradiction(cls, candidates: list[str]) -> bool:
        if len(candidates) < 2:
            return False
        has_negative = [any(term in text for term in cls._NEGATION) for text in candidates]
        has_affirm = [any(term in text for term in cls._AFFIRMATION) for text in candidates]
        if any(has_negative) and any(has_affirm):
            return True
        # Compare critical semantic slots, not just surface similarity.  The old
        # amount regex read both ``1,234元`` and ``2,234元`` as ``234元``; ISO
        # dates, relative dates and HH:MM times were not compared at all.  High
        # ASR similarity must never override disagreement on a side-effect value.
        signatures = [cls._critical_slot_signature(text) for text in candidates]
        for field in ("amount_cents", "date", "time"):
            values = [item[field] for item in signatures if item.get(field) is not None]
            if len(set(values)) > 1:
                return True
        return False

    @classmethod
    def _critical_slot_signature(cls, text: str) -> dict[str, Any]:
        return {
            "amount_cents": parse_spoken_amount_cents(text),
            "date": cls._date_signature(text),
            "time": parse_time_text(text),
        }

    @staticmethod
    def _date_signature(text: str) -> str | None:
        # Preserve relative meaning without depending on the server clock.
        for token in ("大后天", "后天", "明天", "今天", "今日"):
            if token in text:
                return f"relative:{token}"
        weekday = re.search(r"(下周|下星期|本周|这周|星期|周)([一二三四五六日天])", text)
        if weekday:
            return f"weekday:{weekday.group(1)}{weekday.group(2)}"
        absolute = re.search(r"(?<!\d)(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?(?!\d)", text)
        if absolute:
            return f"ymd:{int(absolute.group(1)):04d}-{int(absolute.group(2)):02d}-{int(absolute.group(3)):02d}"
        month_day = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})(?:日|号)(?!\d)", text)
        if month_day:
            return f"md:{int(month_day.group(1)):02d}-{int(month_day.group(2)):02d}"
        return None

    @classmethod
    def resolve(cls, payload: VoiceTurnRequest) -> VoiceTurnResolution:
        normalized = [cls._normalize(item.text) for item in payload.candidates]
        weights = [max(0.01, item.confidence) for item in payload.candidates]
        cluster_scores: list[float] = []
        for i, current in enumerate(normalized):
            score = 0.0
            for j, other in enumerate(normalized):
                score += weights[j] * cls._similarity(current, other)
            cluster_scores.append(score)
        best_index = max(range(len(normalized)), key=lambda idx: (cluster_scores[idx], weights[idx], -idx))
        best = normalized[best_index]
        total_weight = sum(weights)
        agreement = cluster_scores[best_index] / total_weight if total_weight else 0.0
        confidence = min(1.0, 0.55 * weights[best_index] + 0.45 * agreement)
        ambiguity = max(0.0, min(1.0, 1.0 - agreement))
        contradiction = cls._contradiction(normalized)
        intent = cls._intent(best)
        safety_flags: list[str] = []
        signals = [SafetyPolicy.detect_safety_signal(text) for text in normalized]
        if any(signal is not None and signal.category == "emergency" for signal in signals):
            safety_flags.append("possible_emergency")
        if any(signal is not None and signal.category == "suspected_scam" for signal in signals):
            safety_flags.append("possible_scam")
        if contradiction:
            safety_flags.append("candidate_contradiction")
        high_risk = payload.side_effect_possible or any(term in best for term in cls._HIGH_RISK_TERMS)
        reasons = [f"best_candidate_engine={payload.candidates[best_index].engine}", f"agreement={agreement:.3f}"]
        if contradiction:
            reasons.append("N-best候选在确认/否定、金额或日期上存在冲突。")
        if not best:
            status = VoiceResolutionStatus.BLOCKED
            prompt = "我没有听清，请您再说一遍。"
            resolved: str | None = None
        elif "possible_emergency" in safety_flags:
            status = VoiceResolutionStatus.ACCEPTED
            prompt = None
            resolved = best
            reasons.append("紧急表达优先保留，交由安全流程立即处理。")
        elif contradiction or confidence < (0.82 if high_risk else 0.68) or (high_risk and len(normalized) == 1 and weights[0] < 0.88):
            status = VoiceResolutionStatus.CLARIFY
            prompt = cls._clarification(best, intent, contradiction)
            resolved = None
            reasons.append("副作用任务采用保守阈值，宁可澄清也不猜测。")
        else:
            status = VoiceResolutionStatus.ACCEPTED
            prompt = None
            resolved = best
        digest = hashlib.sha256(
            canonical_json(
                {
                    "candidates": [item.model_dump(mode="json") for item in payload.candidates],
                    "normalized": normalized,
                    "resolved": resolved,
                    "intent": intent,
                }
            ).encode("utf-8")
        ).hexdigest()
        return VoiceTurnResolution(
            status=status,
            resolved_text=resolved,
            normalized_text=best or None,
            confidence=round(confidence, 6),
            ambiguity=round(max(ambiguity, 0.9 if contradiction else 0.0), 6),
            semantic_intent=intent,
            clarification_prompt=prompt,
            safety_flags=safety_flags,
            consensus_digest=digest,
            rationale=reasons,
        )

    @staticmethod
    def _clarification(best: str, intent: str, contradiction: bool) -> str:
        if contradiction:
            return f"我听到的内容有两种可能。请您明确说「确认办理」或「取消办理」。我刚才听到：{best or '未听清'}。"
        if intent == "bill_payment":
            return "我想确认一下：您是要查询账单，还是要发起缴费？请说「只查询」或「发起缴费」。"
        if intent == "hospital_registration":
            return "我没有完全听清医院或时间。请您慢一点说，例如「明天下午挂人民医院骨科」。"
        return f"我没有完全听清。您刚才是不是想说：{best or '这件事'}？请说「是」或重新说一遍。"


@dataclass(frozen=True)
class ActionSpec:
    allowed_fields: frozenset[str]
    required_fields: frozenset[str]
    allowed_purposes: frozenset[str]
    risk: int
    elder_confirmation: bool = False
    family_approvals: int = 0
    reversible_required: bool = False
    emergency_only: bool = False
    forbidden: bool = False


class PurposeBoundPolicy:
    """Reference monitor for task alignment and purpose-bound data flow.

    The policy engine is deliberately outside the LLM. It follows policy-as-code
    separation: the engine returns a decision and never performs the side effect.
    """

    VERSION = "youhuo-policy-v5.1"
    _SPECS: dict[str, ActionSpec] = {
        "lookup_bill": ActionSpec(
            frozenset({"bill_type", "period", "elder_id"}),
            frozenset({"bill_type"}),
            frozenset({"bill_lookup", "bill_payment"}),
            risk=1,
        ),
        "create_payment_request": ActionSpec(
            frozenset({"bill_id", "amount_cents", "elder_id", "recipient_family_id"}),
            frozenset({"bill_id", "amount_cents", "elder_id"}),
            frozenset({"bill_payment"}),
            risk=4,
            elder_confirmation=True,
            family_approvals=1,
        ),
        "execute_payment": ActionSpec(
            frozenset(), frozenset(), frozenset(), risk=4, forbidden=True
        ),
        "reserve_appointment": ActionSpec(
            frozenset({"elder_id", "hospital", "department", "doctor", "date", "time"}),
            frozenset({"elder_id", "hospital", "department", "date", "time"}),
            frozenset({"hospital_registration", "medical_followup"}),
            risk=3,
            elder_confirmation=True,
            reversible_required=True,
        ),
        "create_reminder": ActionSpec(
            frozenset({"elder_id", "title", "due_at", "timezone"}),
            frozenset({"elder_id", "title", "due_at"}),
            frozenset({"reminder", "medication", "medical_followup"}),
            risk=2,
            elder_confirmation=True,
        ),
        "send_family_notification": ActionSpec(
            frozenset({"elder_id", "event_type", "summary", "urgency"}),
            frozenset({"elder_id", "event_type", "summary"}),
            frozenset({"task_escalation", "safety", "emergency", "care_summary"}),
            risk=2,
        ),
        "store_health_summary": ActionSpec(
            frozenset({"elder_id", "summary", "source_digest", "review_required"}),
            frozenset({"elder_id", "summary", "source_digest"}),
            frozenset({"health_record"}),
            risk=3,
            elder_confirmation=True,
        ),
        "emergency_contact": ActionSpec(
            frozenset({"elder_id", "reason", "location", "health_summary"}),
            frozenset({"elder_id", "reason"}),
            frozenset({"emergency"}),
            risk=4,
            emergency_only=True,
        ),
        "disclose_companion_chat": ActionSpec(
            frozenset(), frozenset(), frozenset(), risk=4, forbidden=True
        ),
        "submit_identity_secret": ActionSpec(
            frozenset(), frozenset(), frozenset(), risk=4, forbidden=True
        ),
        "medication_diagnosis": ActionSpec(
            frozenset(), frozenset(), frozenset(), risk=4, forbidden=True
        ),
    }
    _CONTROL_FIELDS = {"approve", "confirmed", "recipient", "amount_cents", "account", "execute", "scope"}
    _HIGH_SENSITIVITY_ALLOWED = {
        "create_payment_request": {"elder_id"},
        "reserve_appointment": {"elder_id"},
        "store_health_summary": {"elder_id", "summary"},
        "emergency_contact": {"elder_id", "location", "health_summary"},
    }

    @classmethod
    def authorize(cls, payload: ActionAuthorizeRequest) -> ActionAuthorization:
        reasons: list[str] = []
        stripped: list[str] = []
        required: list[str] = []
        allowed_arguments: dict[str, Any] = {}
        spec = cls._SPECS.get(payload.action)
        if spec is None:
            return cls._result(
                AuthorizationDecision.DENY,
                ["动作没有在受控工具清单中注册。"],
                {},
                list(payload.arguments),
                [],
                False,
                payload,
            )
        if spec.forbidden:
            return cls._result(
                AuthorizationDecision.DENY,
                ["该动作被产品安全边界明确禁止，不能由Agent执行。"],
                {},
                list(payload.arguments),
                [],
                True,
                payload,
            )
        if spec.emergency_only and not payload.emergency:
            return cls._result(
                AuthorizationDecision.DENY,
                ["该能力仅允许在明确紧急状态下调用。"],
                {},
                list(payload.arguments),
                [],
                True,
                payload,
            )
        purpose_by_name: dict[str, set[str]] = {}
        origin_by_name: dict[str, set[DataOrigin]] = {}
        sensitivity_by_name: dict[str, DataSensitivity] = {}
        trusted_control: dict[str, bool] = {}
        trusted_values_by_name: dict[str, set[str]] = {}
        untrusted_values_by_name: dict[str, set[str]] = {}
        for fact in payload.facts:
            fact_key = cls._field_key(fact.name)
            purpose_by_name.setdefault(fact_key, set()).add(fact.purpose)
            origin_by_name.setdefault(fact_key, set()).add(fact.origin)
            sensitivity_by_name[fact_key] = max(
                sensitivity_by_name.get(fact_key, DataSensitivity.PUBLIC), fact.sensitivity
            )
            trusted_control[fact_key] = trusted_control.get(fact_key, False) or fact.trusted_for_control
            serialized_value = canonical_json(fact.value)
            if fact.trusted_for_control and fact.origin != DataOrigin.UNTRUSTED_DOCUMENT:
                trusted_values_by_name.setdefault(fact_key, set()).add(serialized_value)
            if fact.origin == DataOrigin.UNTRUSTED_DOCUMENT:
                untrusted_values_by_name.setdefault(fact_key, set()).add(serialized_value)
        for key, value in payload.arguments.items():
            if key not in spec.allowed_fields:
                stripped.append(key)
                reasons.append(f"字段 {key} 不属于动作Schema，已剥离。")
                continue
            fact_key = cls._field_key(key)
            purposes = purpose_by_name.get(fact_key, set())
            if purposes and not purposes.intersection(spec.allowed_purposes):
                stripped.append(key)
                reasons.append(f"字段 {key} 的采集目的与当前动作不匹配。")
                continue
            origins = origin_by_name.get(fact_key, set())
            if DataOrigin.UNTRUSTED_DOCUMENT in origins and fact_key in cls._CONTROL_FIELDS:
                trusted_values = trusted_values_by_name.get(fact_key, set())
                untrusted_values = untrusted_values_by_name.get(fact_key, set())
                argument_value = canonical_json(value)
                if not trusted_control.get(fact_key, False) or not trusted_values:
                    stripped.append(key)
                    reasons.append(f"不可信文档中的 {key} 不能控制副作用或授权。")
                    continue
                # A trusted tool and an OCR/document can mention the same field.
                # Conflicting values must never be silently merged: the user sees
                # a clarification instead of the Agent selecting whichever source
                # is convenient.  Identical corroborating values remain usable.
                if argument_value not in trusted_values or any(item not in trusted_values for item in untrusted_values):
                    stripped.append(key)
                    reasons.append(f"字段 {key} 的可信来源与不可信文档值冲突，必须重新核验。")
                    continue
            sensitivity = sensitivity_by_name.get(fact_key, DataSensitivity.PUBLIC)
            if sensitivity >= DataSensitivity.HIGH and key not in cls._HIGH_SENSITIVITY_ALLOWED.get(payload.action, set()):
                stripped.append(key)
                reasons.append(f"高敏感字段 {key} 对当前动作并非必要，按最小化原则移除。")
                continue
            allowed_arguments[key] = value
        missing = sorted(spec.required_fields - allowed_arguments.keys())
        if missing:
            reasons.append("缺少必需字段：" + "、".join(missing))
            return cls._result(
                AuthorizationDecision.CLARIFY, reasons, allowed_arguments, stripped, ["补充必需信息"], True, payload
            )
        if not cls._goal_aligned(payload.goal, payload.action):
            reasons.append("动作与老人当前明确目标不一致。")
            return cls._result(AuthorizationDecision.DENY, reasons, allowed_arguments, stripped, [], True, payload)
        if payload.ambiguity >= 0.35:
            reasons.append("输入歧义超过副作用动作阈值。")
            return cls._result(
                AuthorizationDecision.CLARIFY, reasons, allowed_arguments, stripped, ["老人重新确认目标"], True, payload
            )
        if spec.reversible_required and not payload.reversible:
            reasons.append("该步骤必须使用可撤销的预留/草稿接口，不能直接不可逆提交。")
            return cls._result(AuthorizationDecision.DENY, reasons, allowed_arguments, stripped, [], True, payload)
        if spec.elder_confirmation and not payload.user_confirmed:
            required.append("老人本人确认")
            return cls._result(
                AuthorizationDecision.REQUIRE_ELDER_CONFIRMATION,
                reasons or ["副作用动作必须由老人确认。"],
                allowed_arguments,
                stripped,
                required,
                True,
                payload,
            )
        if payload.family_approvals < spec.family_approvals:
            required.append(f"至少{spec.family_approvals}名绑定家属批准")
            return cls._result(
                AuthorizationDecision.REQUIRE_FAMILY_APPROVAL,
                reasons or ["资金或高风险步骤需要家属接力。"],
                allowed_arguments,
                stripped,
                required,
                True,
                payload,
            )
        reasons.append("动作、目的、字段来源、权限和确认条件均满足。")
        return cls._result(AuthorizationDecision.ALLOW, reasons, allowed_arguments, stripped, [], True, payload)

    @staticmethod
    def _field_key(name: str) -> str:
        """Canonical schema identifier used for provenance/conflict matching.

        Field names are identifiers, not user-visible prose.  Treating their case
        as semantically different lets ``Amount_cents`` bypass the provenance map
        for the ``amount_cents`` control field.
        """
        return unicodedata.normalize("NFKC", name).strip().casefold()

    @staticmethod
    def _goal_aligned(goal: str, action: str) -> bool:
        goal = normalize_text(goal)
        groups = {
            "lookup_bill": {"账单", "水费", "电费", "燃气", "缴费", "查询"},
            "create_payment_request": {"支付", "缴费", "水费", "电费", "燃气费", "账单", "交水费", "交电费", "交燃气费"},
            "reserve_appointment": {"挂号", "预约", "医院", "医生", "看病", "复诊"},
            "create_reminder": {"提醒", "日历", "待办", "吃药", "复查"},
            "send_family_notification": {"通知", "提醒家人", "兜底", "求助", "报告"},
            "store_health_summary": {"体检", "报告", "健康档案", "保存"},
            "emergency_contact": {"救命", "紧急", "摔倒", "胸口痛", "迷路", "煤气"},
        }
        tokens = groups.get(action, set())
        if not tokens:
            return False

        # Keyword presence is not consent.  "不要支付水费" used to satisfy the
        # same token test as "支付水费" and could reach ALLOW once boolean
        # confirmation fields were true.  Keep common "don't forget to remind"
        # wording affirmative, then reject action tokens under an explicit
        # cancel/negative scope.
        scan = re.sub(r"(?:不要|别)忘(?:了|记)?", "", goal)
        negative_terms = {
            "lookup_bill": {"查询", "查", "看账单"},
            "create_payment_request": {"支付", "缴费", "缴", "交", "付款", "扣款", "转账"},
            "reserve_appointment": {"挂号", "预约", "看病", "复诊"},
            "create_reminder": {"提醒", "建提醒", "创建提醒"},
            "send_family_notification": {"通知", "提醒家人", "发消息"},
            "store_health_summary": {"保存", "存档", "写入"},
            "emergency_contact": {"联系", "呼叫", "通知"},
        }.get(action, tokens)
        token_pattern = "|".join(re.escape(token) for token in sorted(negative_terms, key=len, reverse=True))
        negation = r"(?:取消|停止|不要|别|不用|不想|不需要|无需|暂不|先不|不再|别再)"
        # Negation can wrap a short object phrase ("取消这笔水费支付"), include
        # polite fillers ("先不替我缴费"), or trail the verb ("支付水费先不要").
        # Restrict the window to the action phrase so an unrelated negative
        # clause such as "不用查账单，帮我支付水费" does not block payment.
        scoped_gap = r"[^，,。！？!?；;]{0,8}"
        if re.search(rf"{negation}(?:再)?{scoped_gap}(?:{token_pattern})", scan):
            return False
        if re.search(rf"(?:{token_pattern}){scoped_gap}{negation}", scan):
            return False
        return any(token in goal for token in tokens)

    @classmethod
    def _result(
        cls,
        decision: AuthorizationDecision,
        reasons: list[str],
        allowed: dict[str, Any],
        stripped: list[str],
        confirmations: list[str],
        purpose_bound: bool,
        payload: ActionAuthorizeRequest,
    ) -> ActionAuthorization:
        digest = hashlib.sha256(
            canonical_json(
                {
                    "policy": cls.VERSION,
                    "decision": decision.value,
                    "goal": payload.goal,
                    "action": payload.action,
                    "allowed": allowed,
                    "stripped": sorted(stripped),
                    "confirmations": confirmations,
                }
            ).encode("utf-8")
        ).hexdigest()
        return ActionAuthorization(
            decision=decision,
            reasons=reasons,
            allowed_arguments=allowed,
            stripped_fields=sorted(set(stripped)),
            required_confirmations=confirmations,
            policy_version=cls.VERSION,
            decision_digest=digest,
            purpose_bound=purpose_bound,
        )


@dataclass(frozen=True)
class SagaStepDefinition:
    name: str
    requires_human: bool = False
    reversible: bool = False
    compensation_name: str | None = None


class SagaCatalog:
    VERSION = "youhuo-saga-v5.0"
    _DEFINITIONS: dict[SagaKind, tuple[SagaStepDefinition, ...]] = {
        SagaKind.MEDICAL_APPOINTMENT: (
            SagaStepDefinition("collect_preferences", requires_human=True),
            SagaStepDefinition("reserve_slot", reversible=True, compensation_name="release_slot"),
            SagaStepDefinition("elder_confirm", requires_human=True),
            SagaStepDefinition("submit_booking", reversible=True, compensation_name="cancel_booking"),
            SagaStepDefinition("create_calendar_reminder", reversible=True, compensation_name="cancel_reminder"),
            SagaStepDefinition("verify_final_state"),
        ),
        SagaKind.BILL_PAYMENT: (
            SagaStepDefinition("locate_bill"),
            SagaStepDefinition("elder_confirm", requires_human=True),
            SagaStepDefinition("family_approval", requires_human=True),
            SagaStepDefinition("generate_payment_request", reversible=True, compensation_name="expire_payment_request"),
            SagaStepDefinition("observe_authoritative_payment_state"),
            SagaStepDefinition("verify_final_state"),
        ),
        SagaKind.REPORT_FOLLOWUP: (
            SagaStepDefinition("extract_followup_date"),
            SagaStepDefinition("human_review", requires_human=True),
            SagaStepDefinition("create_reminder", reversible=True, compensation_name="cancel_reminder"),
            SagaStepDefinition("notify_family"),
            SagaStepDefinition("verify_final_state"),
        ),
        SagaKind.MEDICATION_REFILL: (
            SagaStepDefinition("forecast_inventory"),
            SagaStepDefinition("elder_confirm", requires_human=True),
            SagaStepDefinition("family_review", requires_human=True),
            SagaStepDefinition("create_refill_reminder", reversible=True, compensation_name="cancel_reminder"),
            SagaStepDefinition("verify_final_state"),
        ),
    }

    @classmethod
    def steps(cls, kind: SagaKind) -> tuple[SagaStepDefinition, ...]:
        return cls._DEFINITIONS[kind]


class MerkleProofService:
    VERSION = "youhuo-proof-v5.0"

    @staticmethod
    def hash_leaf(value: Any) -> str:
        return hashlib.sha256(("leaf:" + canonical_json(value)).encode("utf-8")).hexdigest()

    @staticmethod
    def hash_node(left: str, right: str) -> str:
        return hashlib.sha256(("node:" + left + right).encode("ascii")).hexdigest()

    @classmethod
    def root(cls, leaves: Iterable[str]) -> str:
        level = list(leaves)
        if not level:
            return hashlib.sha256(b"empty").hexdigest()
        while len(level) > 1:
            if len(level) % 2:
                level.append(level[-1])
            level = [cls.hash_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        return level[0]

    @classmethod
    def build_bundle(
        cls,
        *,
        bundle_id: str,
        task_id: str,
        family_id: str,
        task_snapshot: dict[str, Any],
        audit_events: list[Any],
        audit_chain_valid: bool,
        generated_at: datetime,
    ) -> TaskProofBundle:
        proof_events: list[ProofEvent] = []
        leaves: list[str] = []
        for index, event in enumerate(audit_events, start=1):
            payload_digest = hashlib.sha256(canonical_json(event.payload).encode("utf-8")).hexdigest()
            item = ProofEvent(
                sequence=index,
                event_type=event.event_type,
                actor_id=event.actor_id,
                created_at=event.created_at,
                payload_digest=payload_digest,
                event_hash=event.event_hash,
            )
            proof_events.append(item)
            leaves.append(cls.hash_leaf(item.model_dump(mode="json")))
        snapshot_digest = hashlib.sha256(canonical_json(task_snapshot).encode("utf-8")).hexdigest()
        leaves.insert(0, cls.hash_leaf({"task_snapshot_digest": snapshot_digest}))
        root = cls.root(leaves)
        proof_digest = hashlib.sha256(
            canonical_json(
                {
                    "id": bundle_id,
                    "task_id": task_id,
                    "family_id": family_id,
                    "snapshot": snapshot_digest,
                    "audit_chain_valid": audit_chain_valid,
                    "merkle_root": root,
                    "version": cls.VERSION,
                }
            ).encode("utf-8")
        ).hexdigest()
        return TaskProofBundle(
            id=bundle_id,
            task_id=task_id,
            family_id=family_id,
            generated_at=generated_at,
            task_snapshot_digest=snapshot_digest,
            audit_chain_valid=audit_chain_valid,
            merkle_root=root,
            events=proof_events,
            proof_digest=proof_digest,
            verification_version=cls.VERSION,
        )

    @classmethod
    def verify(cls, bundle: TaskProofBundle) -> ProofVerifyResult:
        leaves = [cls.hash_leaf({"task_snapshot_digest": bundle.task_snapshot_digest})]
        sequence_ok = True
        for expected, event in enumerate(bundle.events, start=1):
            sequence_ok = sequence_ok and event.sequence == expected
            leaves.append(cls.hash_leaf(event.model_dump(mode="json")))
        root_ok = hmac.compare_digest(cls.root(leaves), bundle.merkle_root)
        digest = hashlib.sha256(
            canonical_json(
                {
                    "id": bundle.id,
                    "task_id": bundle.task_id,
                    "family_id": bundle.family_id,
                    "snapshot": bundle.task_snapshot_digest,
                    "audit_chain_valid": bundle.audit_chain_valid,
                    "merkle_root": bundle.merkle_root,
                    "version": bundle.verification_version,
                }
            ).encode("utf-8")
        ).hexdigest()
        digest_ok = hmac.compare_digest(digest, bundle.proof_digest)
        version_ok = bundle.verification_version == cls.VERSION
        checks = {
            "event_sequence": sequence_ok,
            "merkle_root": root_ok,
            "proof_digest": digest_ok,
            "version": version_ok,
            "audit_chain_claim": bundle.audit_chain_valid,
        }
        valid = all(checks.values())
        return ProofVerifyResult(valid=valid, checks=checks, message="证明包验证通过。" if valid else "证明包验证失败。")


class ExplanationService:
    @staticmethod
    def build(task: Any, approvals: list[dict[str, Any]], evidence: list[str]) -> ExplanationCard:
        slots = task.slots
        understood: list[str] = [f"任务类型：{task.task_type.value}"]
        sensitive_names = {"id_number", "phone", "account", "identity_token", "face_template"}
        for key, value in slots.items():
            if key.startswith("_") or key in sensitive_names:
                continue
            if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 120:
                understood.append(f"{key}：{value}")
        confirmations = [f"{row['actor_id']}：{row['decision']}" for row in approvals]
        if task.status.value in {"awaiting_elder_confirmation", "awaiting_family_approval"}:
            confirmations.append("仍有确认步骤未完成")
        why = [
            f"风险等级为{int(task.risk_level)}，因此采用对应确认与工具权限。",
            "模型只负责理解表达，状态变化由确定性代码和Schema约束完成。",
        ]
        if task.approval_digest:
            why.append("批准绑定了任务版本和关键参数，参数改变后原批准失效。")
        data_used = [
            {"source": "老人明确输入", "purpose": "完成当前任务"},
            {"source": "受控工具返回", "purpose": "核对最终状态"},
        ]
        stored = ["任务状态和必要字段", "确认/批准记录", "最小化审计事件"]
        return ExplanationCard(
            task_id=task.id,
            summary=f"{task.task_type.value} · {task.status.value}",
            current_status=task.status.value,
            risk_level=int(task.risk_level),
            what_i_understood=understood[:12],
            why_this_action=why,
            data_used=data_used,
            confirmations=confirmations or ["尚无确认记录"],
            completion_evidence=evidence or ["任务尚未生成权威完成证据"],
            reversible=task.status.value not in {"completed", "cancelled"},
            undo_guidance="尚未完成时可取消；已完成事项需按对应服务规则撤销，系统不会承诺所有外部操作都可逆。",
            stored_data=stored,
            privacy_note="无忧伴聊天原文、验证码、密码和支付凭据不会出现在解释卡中。",
        )


class SyncConflictPolicy:
    @staticmethod
    def may_auto_merge(sensitivity: SyncSensitivity, base_version: int, current_version: int) -> bool:
        if sensitivity == SyncSensitivity.HIGH:
            return base_version == current_version
        return base_version >= current_version - 1


class PrivacyRedactor:
    _PHONE = re.compile(r"(?<!\d)(1[3-9]\d(?:[ -]?\d){8}|\d{3,4}[ -]?\d{7,8})(?!\d)")
    _ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
    _CARD = re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)")
    _SECRET_KEYS = {
        "password", "passwd", "pwd", "验证码", "校验码", "密码",
        "token", "access_token", "refresh_token", "api_key", "apikey",
        "secret", "client_secret", "identity_token", "face_template_digest",
    }

    @classmethod
    def redact_text(cls, value: str) -> str:
        value = cls._PHONE.sub("[手机号已隐藏]", value)
        value = cls._ID.sub("[身份证号已隐藏]", value)
        value = cls._CARD.sub("[账号已隐藏]", value)
        return value[:1000]

    @classmethod
    def redact_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls.redact_text(value)
        if isinstance(value, list):
            return [cls.redact_value(item) for item in value]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                canonical = normalize_text(key).replace("-", "_").replace(" ", "_")
                if canonical in cls._SECRET_KEYS:
                    result[key] = "[已隐藏]"
                else:
                    result[key] = cls.redact_value(item)
            return result
        return value


class MetricsCalculator:
    @staticmethod
    def safe_rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    @classmethod
    def rates(cls, counters: dict[str, int]) -> dict[str, float]:
        return {
            "voice_clarification_rate": cls.safe_rate(counters.get("voice_clarify", 0), counters.get("voice_total", 0)),
            "policy_deny_rate": cls.safe_rate(counters.get("policy_deny", 0), counters.get("policy_total", 0)),
            "saga_completion_rate": cls.safe_rate(counters.get("saga_completed", 0), counters.get("saga_total", 0)),
            "sync_conflict_rate": cls.safe_rate(counters.get("sync_conflict", 0), counters.get("sync_total", 0)),
        }
