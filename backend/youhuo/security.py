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
        r"我迷路了|找不到家",
        # 「救命恩人」「救命钱」「救命稻草」是成语，不是求救。
        r"救命(?!恩|钱|稻草|之恩)|快救我",
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
        # 「到」不是错别字，是中文 ASR 把「倒」听错时最常见的写法。原来只认「倒」，
        # 于是「我摔到了」这句最普通的求救整条漏掉。
        r"(摔|跌|滑|绊|栽)(倒|到)",
        r"摔(了|着|伤|疼|坏|得|趴|的)",
        r"(摔|跌)跤|(摔|跌|栽)了?[个一]?[大]?跟头|(摔|跌)了一?跤",
        r"(摔|跌|滚)下(来|去|楼梯|台阶|床|椅子)",
        # 只描述结果、不含「摔」字的求救——老人报跌倒最常用的其实是这一类。
        r"(趴|躺|倒|坐|跪)在?地(上|下)",
        r"(起|爬|站)不(来|动|起来)",
        r"起不了身|动弹不得|下不来床",
        # 原本在 _emergency_patterns 里，绕过了下面两道守卫，于是
        # 「我怕摔倒了起不来」被当成正在发生的紧急情况。挪进来受同样的约束。
        r"摔倒[^。！]{0,10}(起不来|不能动)",
    )
    #: 摔东西不是摔跤。
    _object_fall = (
        r"(把|将)[^，。！？]{0,10}(摔|扔)|"
        r"(碗|杯子?|盘子?|碟|锅|手机|遥控器|眼镜|拐杖|花瓶|盆|东西)[^，。！？]{0,4}摔"
    )
    #: 「跌倒」出现在名词性词组里说的是话题，不是事件。这类词紧跟在动词**之后**
    #: （跌倒风险、跌倒讲座），位置敏感的守卫看不见它们，所以单列一条按相邻判断。
    _fall_as_topic = (
        r"(跌倒|摔倒)(风险|讲座|评估|培训|宣传|知识|须知|预防|问题)|"
        r"防(止|范)?(跌倒|摔倒)"
    )
    #: 第三人称主语：别人摔倒不是这位老人摔倒。第一人称出现时以第一人称为准。
    #:
    #: 「我」后面紧跟亲属称谓时是**领属**不是主语——「我孙子摔倒了」说的是孙子。
    #: 少了这个否定前瞻，第三人称守卫会被一个"我"字轻易关掉。
    _first_person = r"我(?!孙|儿|女|老伴|外孙|家)|俺|自己"
    _other_person = (
        r"孙(子|女)|外孙|儿子|女儿|老伴|邻居|楼(上|下)|老(王|李|张|刘|陈)|"
        r"别人|那个人|电视|新闻|同事|病友|护士|医生说"
    )
    #: Recounting an old fall is a story, not a call for help. Do not page family.
    _past_narrative = (
        r"上(个)?月|上(个)?星期|上(个)?礼拜|上次|上回|去年|前年|前几年|几年前|"
        r"以前|从前|当年|那年|那次|那回|有一回|有一次|小时候|年轻(的)?时|曾经|"
        r"出院|康复|好利索|养好了"
    )
    #: Worrying about falling is the opposite of having fallen.
    #:
    #: 「小心」「注意」被移出去了：「我不小心摔倒了」是老人报告跌倒**最自然**的说法，
    #: 把它当成假设，等于把最常见的一句真实求救静音。
    #: 「别」「不要」留下，但和其余一样只在**动词之前**才算假设——见 `_guarded_hit`。
    _hypothetical = (
        r"怕|担心|万一|要是|如果|假如|别|不要|避免|以防|会不会|容易|"
        r"防(止|范)|风险|讲座|评估|培训|宣传|梦见|万一"
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
        # 紧急模式原来是整句直接匹配，跳过了下面那两道守卫，于是
        # 「我怕着火，睡前都检查一遍」「电视剧里那人昏倒了」都会真的惊动家属。
        # 现在与跌倒判定走同一套子句 + 位置敏感的守卫。
        if cls._guarded_hit(normalized, cls._emergency_patterns):
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
            hit = cls._first_match(clause, cls._fall_patterns)
            if hit is None:
                continue
            # 摔的是碗还是人。
            if re.search(cls._object_fall, clause):
                continue
            # 「跌倒风险评估」「防跌倒讲座」说的是话题，不是这位老人刚摔了。
            if re.search(cls._fall_as_topic, clause):
                continue
            # 第三人称主语——除非同一子句里出现第一人称，那就以第一人称为准
            # （"我扶邻居的时候我也摔倒了"）。
            if not re.search(cls._first_person, clause) and re.search(cls._other_person, clause):
                continue
            # **位置敏感**：只有出现在跌倒动词**之前**的指示词才算假设或回忆。
            #
            # 原来是整句包含即否决，代价是把最自然的几句真实求救静音了：
            #   「我不小心摔倒了」——「小心」在词表里
            #   「我摔倒了怕站不起来」——「怕」在词表里，而这句比裸「我摔倒了」更急
            #   「我摔倒了别告诉我儿子」——「别」在词表里
            # 中文里假设和回忆的标记几乎总在动词前（怕摔、万一摔、去年摔），
            # 动词后出现的是后果和请求，不是假设。
            if cls._marker_before(clause, cls._hypothetical, hit):
                continue
            if cls._marker_before(clause, cls._past_narrative, hit):
                continue
            return True
        return False

    @classmethod
    def _guarded_hit(cls, normalized: str, patterns: tuple[str, ...]) -> bool:
        """子句级 + 位置敏感的匹配，供紧急模式与跌倒判定共用。"""
        for clause in re.split(r"[，。！？；,.!?;\s]+", normalized):
            hit = cls._first_match(clause, patterns)
            if hit is None:
                continue
            if not re.search(cls._first_person, clause) and re.search(cls._other_person, clause):
                continue
            if cls._marker_before(clause, cls._hypothetical, hit):
                continue
            if cls._marker_before(clause, cls._past_narrative, hit):
                continue
            return True
        return False

    @staticmethod
    def _first_match(clause: str, patterns: tuple[str, ...]) -> int | None:
        """最靠前的一个命中位置；没有命中返回 None。"""
        positions = [
            match.start()
            for pattern in patterns
            if (match := re.search(pattern, clause)) is not None
        ]
        return min(positions) if positions else None

    @staticmethod
    def _marker_before(clause: str, marker: str, verb_at: int) -> bool:
        """指示词是否出现在动词之前。"""
        for match in re.finditer(marker, clause):
            if match.start() < verb_at:
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
