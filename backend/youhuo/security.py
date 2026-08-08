from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .models import RiskLevel, TaskRecord, TaskType
from .utils import canonical_json, clean_user_text


@dataclass(frozen=True)
class SafetySignal:
    category: str
    severity: int
    message: str
    notify_family: bool


class SafetyPolicy:
    """Deterministic security boundary around language-model output.

    The model may suggest an intent or wording, but it cannot grant permission,
    mutate authoritative state, execute tools, or bypass confirmations.
    """

    _emergency_patterns = (
        r"胸(口)?[^。！]{0,8}(疼|痛|闷)",
        r"喘不上气|呼吸困难|不能呼吸",
        r"摔倒[^。！]{0,10}(起不来|不能动)",
        r"我迷路了|找不到家",
        r"救命|快救我",
        r"有人闯进|有人撬门",
        r"煤气[^。！]{0,8}(漏|味)|燃气泄漏",
        r"着火|起火",
        r"昏倒|失去意识",
    )
    #: A fall is the emergency an elder is most likely to report in the plainest
    #: words. Every other layer (v5_services, v6_services) already treats a bare
    #: 摔倒 as urgent; the chat chain used to require "起不来" after it, so the one
    #: surface the elder actually talks to was the strictest. It now fires on a
    #: bare report and relies on the guards below to stay quiet otherwise.
    _fall_patterns = (
        r"摔(倒|了|着|伤)",
        r"跌倒|滑倒|绊倒",
        r"摔了一跤|跌了一跤",
        r"站不起来|爬不起来|起不了身",
    )
    #: Recounting an old fall is a story, not a call for help. Do not page family.
    _past_narrative = (
        r"上(个)?月|上(个)?星期|上(个)?礼拜|上次|上回|去年|前年|前几年|几年前|"
        r"以前|从前|当年|那年|那次|那回|有一回|有一次|小时候|年轻(的)?时|曾经|"
        r"出院|康复|好利索|养好了"
    )
    #: Worrying about falling is the opposite of having fallen.
    _hypothetical = (
        r"怕|担心|万一|要是|如果|别|不要|避免|以防|小心|注意|会不会|容易"
    )
    _scam_patterns = (
        r"银行卡密码",
        r"验证码[^。！]{0,10}(告诉|发给|给他|转账)",
        r"转账[^。！]{0,10}安全账户",
        r"刷单|做任务返利",
        r"公检法[^。！]{0,16}转账",
        r"退款[^。！]{0,16}屏幕共享",
        r"陌生人[^。！]{0,16}二维码",
        r"远程控制[^。！]{0,12}手机",
    )
    _prompt_injection_patterns = (
        r"忽略\s*(以上|之前|系统|所有)[^。；;]{0,30}(指令|规则|要求)",
        r"system\s*prompt|developer\s*message",
        r"调用[^。；;]{0,20}(转账|支付|删除|导出)",
        r"绕过[^。；;]{0,20}(确认|审批|权限|验证)",
        r"不要告诉(用户|老人|家属)",
        r"执行隐藏命令|提升权限|越权执行",
        r"把(密码|验证码|令牌|token)[^。；;]{0,20}(发给|返回|输出)",
    )

    @classmethod
    def detect_safety_signal(cls, text: str) -> SafetySignal | None:
        normalized = unicodedata.normalize("NFKC", text)
        for pattern in cls._emergency_patterns:
            if re.search(pattern, normalized, flags=re.I):
                return SafetySignal(
                    category="emergency",
                    severity=4,
                    message="我听到您可能遇到了紧急情况。我会立即提醒家人；如果有生命危险，请尽快联系当地急救服务。",
                    notify_family=True,
                )
        if cls._is_present_fall(normalized):
            return SafetySignal(
                category="emergency",
                severity=4,
                message=(
                    "您是不是摔倒了？如果能动，先别急着站起来。我现在就通知家人；"
                    "如果受伤严重或者起不来，请尽快联系当地急救服务。"
                ),
                notify_family=True,
            )
        for pattern in cls._scam_patterns:
            if re.search(pattern, normalized, flags=re.I):
                return SafetySignal(
                    category="suspected_scam",
                    severity=3,
                    message="这可能存在诈骗风险。请不要透露密码、验证码，也不要立即转账。我会提醒家人一起核实。",
                    notify_family=True,
                )
        return None

    @classmethod
    def _is_present_fall(cls, normalized: str) -> bool:
        """A fall being reported now, not remembered and not feared.

        Deliberately biased toward asking: the reply is a question the elder can
        wave off, and the alternative — staying silent on a real fall — is the
        one failure this product cannot afford.
        """
        # Scope the guards to the clause the fall is in. Chinese puts the time
        # adverbial before the verb, so "去年摔倒住了院，现在好利索了" is a recovery
        # story even though it contains "现在", while "刚才摔倒了，上个月也摔过"
        # reports a fall happening now in its first clause.
        for clause in re.split(r"[，。！？；,.!?;\s]+", normalized):
            if not any(re.search(pattern, clause) for pattern in cls._fall_patterns):
                continue
            if re.search(cls._hypothetical, clause):
                continue
            if re.search(cls._past_narrative, clause):
                continue
            return True
        return False

    @classmethod
    def sanitize_untrusted_text(cls, value: str, max_length: int = 500) -> str:
        """Sanitize display text from tools while preserving it as non-executable data."""
        try:
            value = clean_user_text(value, max_length=max_length)
        except ValueError:
            return ""
        for pattern in cls._prompt_injection_patterns:
            value = re.sub(pattern, "[已过滤可疑指令]", value, flags=re.I)
        return value

    @classmethod
    def contains_prompt_injection(cls, value: str) -> bool:
        normalized = unicodedata.normalize("NFKC", value)
        return any(re.search(pattern, normalized, flags=re.I) for pattern in cls._prompt_injection_patterns)

    @staticmethod
    def risk_for(task_type: TaskType, slots: dict[str, Any]) -> RiskLevel:
        if task_type == TaskType.BILL_PAYMENT:
            return RiskLevel.HIGH
        if task_type == TaskType.HOSPITAL_REGISTRATION:
            return RiskLevel.SENSITIVE
        if task_type == TaskType.FORM_ASSISTANCE:
            sensitive_keys = {"id_card", "bank_card", "face_verification", "medical_record"}
            return RiskLevel.HIGH if sensitive_keys.intersection(slots) else RiskLevel.SENSITIVE
        if task_type == TaskType.REMINDER:
            return RiskLevel.LOW
        return RiskLevel.INFORMATION

    @staticmethod
    def requires_family_approval(risk: RiskLevel) -> bool:
        return risk >= RiskLevel.HIGH

    @staticmethod
    def requires_elder_confirmation(risk: RiskLevel) -> bool:
        return risk >= RiskLevel.LOW

    @staticmethod
    def may_execute(role: str, risk: RiskLevel, elder_confirmed: bool, family_approved: bool) -> bool:
        if risk >= RiskLevel.HIGH:
            return role == "system" and elder_confirmed and family_approved
        if risk >= RiskLevel.LOW:
            return role == "system" and elder_confirmed
        return role == "system"

    @staticmethod
    def approval_digest(task: TaskRecord) -> str:
        """Bind family approval to the exact task snapshot to stop TOCTOU changes."""
        immutable = {
            "task_id": task.id,
            "task_type": task.task_type.value,
            "risk": int(task.risk_level),
            "semantic_key": task.semantic_key,
            "version": task.version,
            "slots": {
                key: value
                for key, value in task.slots.items()
                if key not in {"family_approved", "family_approver", "elder_confirmed", "payment_request_id"}
            },
        }
        return hashlib.sha256(canonical_json(immutable).encode("utf-8")).hexdigest()
