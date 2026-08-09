from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .models import RiskLevel, TaskRecord, TaskType
from .utils import canonical_json, clean_user_text


def _fuzzy_word(word: str, *, gap: int = 2) -> str:
    """Regex for a short risk keyword that tolerates tiny ASR/text insertions."""
    spacer = rf"[^。！？；;\n]{{0,{gap}}}"
    return spacer.join(re.escape(char) for char in word)


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
        r"胸(口)?[^。！]{0,8}?(疼|痛|闷)",
        r"喘不上气|呼吸困难|不能呼吸",
        r"我迷路了|找不到家",
        # 「救命恩人」「救命钱」「救命稻草」是成语，不是求救。
        r"救命(?!恩|钱|稻草|之恩)|快救我",
        r"有人闯进|有人撬门",
        r"煤气[^。！]{0,8}?(漏|味)|燃气泄漏",
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
        r"(把|将)[^，。！？]{0,10}?(摔|扔)|"
        r"(碗|杯子?|盘子?|碟|锅|手机|遥控器|眼镜|拐杖|花瓶|盆|东西)[^，。！？]{0,4}?摔"
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
        r"妈(妈)?|母亲|爸(爸)?|父亲|丈夫|妻子|爱人|朋友|同学|哥哥|姐姐|弟弟|妹妹|"
        r"女婿|儿媳|亲戚|保姆|护工|别人|那个人|电视|新闻|同事|病友|护士|医生说"
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
        r"怕|担心|不想|不愿|差点|差一点|险些|万一|要是|如果|假如|别|不要|避免|以防|会不会|容易|"
        r"防(止|范)|风险|讲座|评估|培训|宣传|梦见|万一"
    )
    # Scam phrases must tolerate the particles/fillers that naturally occur in
    # Chinese speech and ASR output.  The tolerance is character-level rather
    # than only between whole words, so inserting one benign syllable/character
    # inside "远程控制" or "二维码" cannot turn the detector off.
    _BANK_PASSWORD = rf"{_fuzzy_word('银行卡')}[^。！？]{{0,6}}{_fuzzy_word('密码')}"
    _VERIFY_CODE = _fuzzy_word("验证码")
    _TRANSFER = _fuzzy_word("转账")
    _SAFE_ACCOUNT = _fuzzy_word("安全账户")
    _BRUSH_ORDER = _fuzzy_word("刷单")
    _TASK = _fuzzy_word("任务")
    _REBATE = _fuzzy_word("返利")
    _POLICE = _fuzzy_word("公检法")
    _REFUND = _fuzzy_word("退款")
    _SCREEN_SHARE = rf"(?:{_fuzzy_word('屏幕共享')}|{_fuzzy_word('共享屏幕')})"
    _STRANGER = _fuzzy_word("陌生人")
    _QR = _fuzzy_word("二维码")
    _REMOTE_CONTROL = _fuzzy_word("远程控制")
    _PHONE = _fuzzy_word("手机")
    _scam_patterns = (
        rf"(?:有人|对方|陌生人|客服|骗子|他|她|他们|让我|叫我|要我|要求我|索要)[^。！？]{{0,20}}{_BANK_PASSWORD}|"
        rf"{_BANK_PASSWORD}[^。！？]{{0,12}}(?:告诉|透露|提供|发给|给他|给对方|报给)",
        rf"(?:有人|对方|陌生人|客服|骗子|他|她|他们|让我|叫我|要我|要求我|索要)[^。！？]{{0,20}}{_VERIFY_CODE}|"
        rf"{_VERIFY_CODE}[^。！？]{{0,12}}(?:告诉|透露|提供|发给|给他|给对方|转账)",
        rf"(?:{_TRANSFER}[^。！？]{{0,14}}{_SAFE_ACCOUNT}|{_SAFE_ACCOUNT}[^。！？]{{0,14}}{_TRANSFER})",
        rf"{_BRUSH_ORDER}|{_fuzzy_word('做')}[^。！？]{{0,6}}{_TASK}[^。！？]{{0,10}}{_REBATE}",
        rf"{_POLICE}[^。！？]{{0,20}}{_TRANSFER}",
        rf"{_REFUND}[^。！？]{{0,20}}{_SCREEN_SHARE}",
        rf"{_STRANGER}[^。！？]{{0,20}}{_QR}",
        rf"{_REMOTE_CONTROL}[^。！？]{{0,16}}{_PHONE}",
    )
    _scam_report_marker = (
        r"(?:有人|对方|陌生人|骗子|所谓客服|他|她|他们|来电|短信|群里)"
        r"[^。！？]{0,20}(?:让我|叫我|要我|要求我|索要我|诱导我)|"
        r"客服[^。！？]{0,12}(?:让我|叫我|要我|要求我|索要我)|(?:让|叫|要|要求)我"
    )
    _anti_scam_marker = (
        r"反诈|防骗|防诈骗|诈骗宣传|诈骗案例|诈骗手法|诈骗套路|警方提醒|公安提醒|"
        r"安全提示|温馨提示|谨防诈骗|警惕诈骗|预防诈骗|防范诈骗|"
        r"(?:都是|属于|这是|这类|此类|是)(?:电信|网络|电信网络)?诈骗"
    )
    _protective_directive = (
        r"(?:不要|别|切勿|勿|严禁|不得|不能|不应|不会|不可以|绝不|从不|"
        r"千万不要|千万别|请勿|莫)[^。！？]{0,18}"
        r"(?:告诉|透露|提供|发送|发给|转账|扫码|共享|下载|安装|远程控制|要求|索要)|"
        r"(?:验证码|银行[^。！？]{0,3}卡[^。！？]{0,6}密码)[^。！？]{0,10}"
        r"(?:不要|别|切勿|勿|严禁|不得|不能|不应|不会|不可以|绝不|千万不要|千万别|请勿)"
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
        # ASR/OCR frequently inserts spaces inside Chinese words ("呼吸 困难",
        # "没有 胸口痛").  Treat those spaces as formatting, otherwise they can
        # both hide a real emergency and separate a negation from the symptom,
        # flipping the same input from a miss into a false alert.
        normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
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
        for clause in re.split(r"[。！？；;\n]+", normalized):
            if not clause:
                continue
            clause_protective = re.search(cls._protective_directive, clause, flags=re.I) is not None
            # Keep ordinary scam clauses intact because some signatures span a
            # contrast word ("退款但要共享屏幕").  Only split when a protective
            # directive exists and could otherwise mask a second unsafe request.
            segments = (
                re.split(r"[，,]+|(?:但是|不过|可是|后来|随后|接着|然后|但|却|又)", clause)
                if clause_protective
                else [clause]
            )
            for segment in segments:
                if not segment:
                    continue
                reported_request = re.search(cls._scam_report_marker, segment, flags=re.I) is not None
                educational = re.search(cls._anti_scam_marker, segment, flags=re.I) is not None
                protective = re.search(cls._protective_directive, segment, flags=re.I) is not None
                if protective:
                    continue
                if educational and not reported_request:
                    continue
                for pattern in cls._scam_patterns:
                    if re.search(pattern, segment, flags=re.I):
                        return SafetySignal(
                            category="suspected_scam",
                            severity=3,
                            message="这可能存在诈骗风险。请不要透露密码、验证码，也不要立即转账。我会提醒家人一起核实。",
                            notify_family=True,
                        )
        return None

    @classmethod
    def _is_present_fall(cls, normalized: str) -> bool:
        """A fall being reported now, not remembered, negated, or about someone else."""
        for clause in re.split(r"[。！？；.!?;\n]+", normalized):
            for start, end in cls._match_spans(clause, cls._fall_patterns):
                # Guards are attached to this exact event occurrence.  A bowl being
                # dropped earlier in the same clause must not hide a later self-fall.
                if cls._span_overlaps_pattern(clause, start, end, cls._object_fall):
                    continue
                if cls._span_overlaps_pattern(clause, start, end, cls._fall_as_topic):
                    continue
                if cls._event_belongs_to_other_person(clause, start):
                    continue
                if cls._negated_immediately_before(clause, start):
                    continue
                if cls._marker_before(clause, cls._hypothetical, start):
                    continue
                if cls._marker_before(clause, cls._past_narrative, start):
                    continue
                return True
        return False

    @classmethod
    def _guarded_hit(cls, normalized: str, patterns: tuple[str, ...]) -> bool:
        """Check each event occurrence with local subject/negation/time guards."""
        # Keep commas inside the sentence while locating the event so phrases
        # like "胸口，真的很痛" can still match.  The guard helpers below scope
        # their look-behind to the nearest comma, so a past/third-person clause
        # does not suppress a later first-person emergency.
        for clause in re.split(r"[。！？；.!?;\n]+", normalized):
            for start, _end in cls._match_spans(clause, patterns):
                if cls._event_belongs_to_other_person(clause, start):
                    continue
                if cls._negated_immediately_before(clause, start):
                    continue
                if cls._marker_before(clause, cls._hypothetical, start):
                    continue
                if cls._marker_before(clause, cls._past_narrative, start):
                    continue
                return True
        return False

    @staticmethod
    def _match_spans(clause: str, patterns: tuple[str, ...]) -> list[tuple[int, int]]:
        spans = {match.span() for pattern in patterns for match in re.finditer(pattern, clause)}
        return sorted(spans)

    @staticmethod
    def _span_overlaps_pattern(clause: str, start: int, end: int, pattern: str) -> bool:
        return any(match.start() <= start < match.end() or start <= match.start() < end for match in re.finditer(pattern, clause))

    @classmethod
    def _event_belongs_to_other_person(cls, clause: str, event_at: int) -> bool:
        """The nearest explicit person mention before the event owns the event."""
        local, offset = cls._local_prefix(clause, event_at)
        first = [m.start() for m in re.finditer(cls._first_person, local)]
        other = [m.start() for m in re.finditer(cls._other_person, local)]
        if not other:
            return False
        return max(other) > (max(first) if first else -1)

    @classmethod
    def _negated_immediately_before(cls, clause: str, event_at: int) -> bool:
        prefix, _offset = cls._local_prefix(clause, event_at)
        prefix = prefix.rstrip("，,、 ")
        return re.search(
            r"(?:没有|并没有|并没|没|并未|未曾|不曾|不再|不是|并非|未|不)(?:真的|实际|真正)?$",
            prefix,
        ) is not None

    @classmethod
    def _marker_before(cls, clause: str, marker: str, verb_at: int) -> bool:
        """指示词是否出现在动词之前。"""
        prefix, _offset = cls._local_prefix(clause, verb_at)
        return re.search(marker, prefix) is not None

    @staticmethod
    def _local_prefix(clause: str, event_at: int) -> tuple[str, int]:
        """Text since the nearest comma-like boundary before this event."""
        before = clause[:event_at]
        boundary = max(before.rfind(mark) for mark in ("，", ",", "、"))
        start = boundary + 1
        return before[start:], start

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
