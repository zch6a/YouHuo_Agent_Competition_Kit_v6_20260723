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

from .models import TaskStatus
from .security import SafetyPolicy
from .teach_back import parse_spoken_amount_cents
from .utils import canonical_json, clean_user_text, normalize_text, semantic_hash
from .utils import parse_month_day, parse_time_text
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

    #: 语气词。**「那个」「这个」「就是」后面紧跟汉字时不剥**——
    #: 那时候它们不是语气词，是指示代词/系词。
    #:
    #: 实测（`/v5/voice/resolve`）：
    #:     「帮我交这个月的水费」 -> normalized/resolved 「帮我交月的水费」
    #:     「把刚才那个提醒取消掉」 -> 「把刚才提醒取消掉」
    #:
    #: 前一句把账期弄没了，后一句把「哪一条」弄没了，而这个引擎的活儿
    #: 正是「把 N-best 并成一个**可审计**的结果」——它产出的那句话
    #: 得是她真说过的话。`resolved_text` / `normalized_text` 会连同
    #: 整份 resolution 落进 `voice_turns_v5.resolution_json`，
    #: 也进 `consensus_digest`，所以审计里留下的是一句没人说过的话。
    #:
    #: 同一个形状这一场里是第三次：`_BARE_YES` 那段警告的「中」在
    #: 「中午」里、`companion.py` 里「脚脖子」含着「脖子」。
    #: **一个词是不是语气词，取决于它后面跟着什么。**
    #:
    #: 「嗯」「呃」「然后」「麻烦你」「帮我一下」「请你」不加这道守卫：
    #: 它们没有「后面跟汉字就变成实词」这个问题（「然后」是连词，
    #: 剥掉不改变指称）。
    _FILLERS = re.compile(
        r"(?:嗯+|呃+|然后|麻烦你|帮我一下|请你|"
        r"(?:那个|这个|就是)(?![\u4e00-\u9fff]))")
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
        #: **半角也要剥。** 上面 `clean_user_text` 会先做一遍 NFKC，
        #: 全角的「，」「！」「？」到这儿已经是半角 `,` `!` `?` 了
        #: ——原先这张表只写了全角，那三个字符**永远匹配不到**。
        #: 实测 `_normalize("那个，我想问一下")` 回的是 `",我想问一下"`，
        #: 开头挂着一个半角逗号，而这句话会落进
        #: `voice_turns_v5.resolution_json`。
        #: （「。」「、」不在 NFKC 的映射里，所以那两个全角的要留着。）
        return text.strip("，。！？、,.!? \u3000")

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
        #: 口语那一支。原先这里是一条只认阿拉伯数字的正则
        #: `(\d{1,2})月(\d{1,2})[日号]`，于是「九月二十号」返回 None——
        #: 而上面 `_contradiction` 那句 `if item.get(field) is not None`
        #: 会把这次比较**整条丢掉**（`len(set([])) > 1` 为假），
        #: 于是差六天的两个候选被判为「不冲突」，status=accepted。
        #:
        #: 搬到 `utils.parse_month_day`，和 `parse_time_text` 共用同一个
        #: 中文数字解析器——三个兄弟字段里，金额和时间一直认口语，
        #: 只有日期这一个是在这个文件里手写的。
        spoken = parse_month_day(text)
        if spoken:
            return f"md:{spoken}"
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
        #: 这两个量原先直接写在下面那个 elif 里，阈值也在那里写了一遍。
        #: 抽出来有两个好处：阈值只有一处出处，而且**措辞分得清成因**
        #: ——「置信度真的低」和「保守」是两件事，见 `_clarification`。
        #:
        #: **必须放在这条 `if/elif` 链之前。** 它们原本是夹在链中间的两个赋值，
        #: 而 Python 的链中间不能有别的语句——于是重构的时候第三个分支从 `elif`
        #: 掉成了 `if`，它在紧急那一支**之后**执行，把 `ACCEPTED` 覆盖成了
        #: `CLARIFY`。**紧急那一支就此变成死代码**：一个说「救命我摔倒起不来」的
        #: 老人，综合置信度 0.643–0.6755（阈值 0.68）本来该按上面那句注释直接
        #: 接受、交由安全流程，却会被反问「您刚才是不是在说……」。
        #: 实测 `elderbench_v5` v5-0076..0082 **七条全红**，正是这一支存在的理由。
        low_confidence = confidence < (0.82 if high_risk else 0.68)
        thin_evidence = high_risk and len(normalized) == 1 and weights[0] < 0.88
        if not best:
            status = VoiceResolutionStatus.BLOCKED
            prompt = "我没有听清，请您再说一遍。"
            resolved: str | None = None
        elif "possible_emergency" in safety_flags:
            status = VoiceResolutionStatus.ACCEPTED
            prompt = None
            resolved = best
            reasons.append("紧急表达优先保留，交由安全流程立即处理。")
        elif contradiction or low_confidence or thin_evidence:
            status = VoiceResolutionStatus.CLARIFY
            prompt = cls._clarification(best, intent, contradiction, low_confidence)
            resolved = None
            #: 成因**逐条写**，而且只说成立的那一条。
            #:
            #: 原先这里**无条件**追加一句「副作用任务采用保守阈值，
            #: 宁可澄清也不猜测。」——三个成因（冲突 / 置信度低 /
            #: 证据太薄）共用它，而且 `side_effect_possible=False`
            #: 的轮次也照样写上。实测：
            #:
            #:     候选「今天天气不错」0.41 / 0.38
            #:     side_effect_possible=False，话里也没有高风险词
            #:     -> rationale 里就有那句「**副作用任务**采用保守阈值」
            #:
            #: 澄清这个**决定**是对的（0.6755 < 0.68）；写下来的**理由**
            #: 是假的。而这份 rationale 是这个产品的卖点之一——
            #: 审计里留一条不成立的因，比不留更糟。
            #:
            #: 第 285 条修过同一条链子的另一层：那次修的是**给她听的**
            #: 提示语（一个结果三个成因一句措辞），这一次是**审计理由**。
            threshold = 0.82 if high_risk else 0.68
            if thin_evidence:
                reasons.append(
                    f"副作用任务只有一个候选，其置信度 {weights[0]:.2f} "
                    "不足 0.88，宁可澄清也不猜测。")
            if low_confidence:
                reasons.append(
                    ("副作用任务的保守阈值" if high_risk else "普通轮次的阈值")
                    + f"是 {threshold}，而综合置信度 {confidence:.3f} "
                    "低于它，宁可澄清也不猜测。")
            #: 冲突那一条上面已经写过了（`N-best候选在确认/否定、金额或
            #: 日期上存在冲突。`），不再重复一句同义的。
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
    def _clarification(best: str, intent: str, contradiction: bool,
                       low_confidence: bool) -> str:
        """要她再说一遍时说的那句话。**按成因分，不要一句盖三种。**

        CLARIFY 有三个成因（见调用处）：矛盾、置信度真的低、
        以及**高风险且只有一个候选且权重不够硬**。最后那个是保守，
        不是听不清。

        原先后两支都写死「我没有完全听清」，于是实测出现过这种返回：

            confidence = **0.9285**
            clarification_prompt = 「我没有完全听清。您刚才是不是想说：
                                    帮我提醒一下？请说「是」或重新说一遍。」

        **同一份返回里，置信度字段说 93%，措辞说没听清**，
        而且它把她那句话一字不差念了回来。和第 273 条那个
        「一个标志两个成因、措辞只有一句」是同一个形状。

        界限算得出来：`confidence = 0.55*weight + 0.45*agreement`，
        单候选 agreement=1，所以 `0.55w + 0.45 >= 0.82` 即
        **weight >= 0.6727** 就是「听清了但我保守」。
        """
        if contradiction:
            return f"我听到的内容有两种可能。请您明确说「确认办理」或「取消办理」。我刚才听到：{best or '未听清'}。"
        if intent == "bill_payment":
            return "我想确认一下：您是要查询账单，还是要发起缴费？请说「只查询」或「发起缴费」。"
        if intent == "hospital_registration":
            #: 例句里那家医院**必须是挂号目录里真有的**。
            #:
            #: 这里原先写「人民医院」，而目录（`services.py::_catalog`）
            #: 只有「第一医院」和「第二医院」。实测她照着例句一字不改地说
            #: 「明天下午挂人民医院骨科」，回的是
            #: 「请选择医院，目前可用：第一医院、第二医院。」——
            #: **产品让她说的那句话，产品自己办不了。**
            #:
            #: 「人民医院」大概是从 `v6_services.py:886` 那一侧抄来的
            #: （那一行是 `for hospital in ("第一医院", "人民医院", "中心医院")`）
            #: ——两层两套医院词表，那件事比这一修大，记在 KNOWN_ISSUES 里。
            #:
            #: `engine.py:808-812` 记着同一个形状的另一次：
            #: 提示语列出的选项解析不了，「最刺眼的是「第一」：
            #: 提示语自己就写着「第一医院、第二医院」」。
            #:
            #: 科室用「骨科」：驱动确认过它在第一医院名下真的能挂
            #: （说完只剩医生和时间两个槽位）。
            if low_confidence:
                return "我没有完全听清医院或时间。请您慢一点说，例如「明天下午挂第一医院骨科」。"
            return "这一步我要跟您核准医院和时间。请您说一遍，例如「明天下午挂第一医院骨科」。"
        if low_confidence:
            return f"我没有完全听清。您刚才是不是想说：{best or '这件事'}？请说「是」或重新说一遍。"
        return f"这一步我要跟您核对一遍。您刚才是不是想说：{best or '这件事'}？请说「是」或重新说一遍。"


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

    #: **不许控制上面那些字段的来源。两个成员，不是一个。**
    #:
    #: `youhuo-safe-preview` 和 `youhuo-purpose-bound-policy` 两份 SKILL 的
    #: 不变量原文是：「OCR、网页、**模型推断**等不可信来源不得控制金额、
    #: 账户、授权或执行标志」。这里原先只写了 `DataOrigin.UNTRUSTED_DOCUMENT`
    #: 一个成员（三处：上面两处取值、下面那处判断），于是同一句话里点名的
    #: `MODEL_INFERENCE` 从旁边溜过去了。
    #:
    #: 驱动实测（7 种来源 × 2 种 `trusted_for_control`，对
    #: `create_payment_request` 的 `amount_cents` 填 999900 = 9999.00 元，
    #: 而真实账单 68.40 元）：
    #:
    #:     untrusted_document   两种都 clarify + 剥掉      对
    #:     **model_inference**  两种都 **allow + 留着**    错
    #:
    #: 对 `MODEL_INFERENCE` 而言原先**整个块被跳过**，所以连
    #: `trusted_for_control=False` 都放行——比「自称有控制权就放行」还宽。
    #:
    #: 其余五个（`user_voice` / `user_text` / `family` / `trusted_tool` /
    #: `system`）**必须**能控制：她自己说出金额（复述确认走的就是
    #: `user_voice`）被剥掉的话，整条缴费流程就没了。判据
    #: `test_a_guessed_amount_cannot_control_a_payment.py` 两侧都钉住，
    #: 并要求 `DataOrigin` 的每个成员都被分类——加一个新来源就红，
    #: 逼下一个人先决定它能不能控制钱，而不是默认放行。
    #: 这张表是**唯一的出处**：集合从它算出来，剥离理由那句话也从它取词。
    #: 写成两份名单的话，加一个来源时只改一份就是下一个同形状的缺陷。
    #: 字典**有序**，所以两个来源同时命中时那句话的措辞是确定的——
    #: 用 `frozenset` 迭代会随进程的字符串哈希变，理由文案就会跟着飘。
    #:
    #: 措辞要点出**是哪一类**来源：模型推断被挡下来时说成「文档」是句不准的话。
    _UNTRUSTED_WORDS = {
        DataOrigin.UNTRUSTED_DOCUMENT: "不可信文档中",
        DataOrigin.MODEL_INFERENCE: "模型推断出来",
    }
    _UNTRUSTED_FOR_CONTROL = frozenset(_UNTRUSTED_WORDS)

    _HIGH_SENSITIVITY_ALLOWED = {
        "create_payment_request": {"elder_id"},
        "reserve_appointment": {"elder_id"},
        "store_health_summary": {"elder_id", "summary"},
        "emergency_contact": {"elder_id", "location", "health_summary"},
    }

    @classmethod
    def _untrusted_words(cls, origins: Iterable[DataOrigin]) -> str:
        """这一格里那些不可信来源，念成人话。

        按 `_UNTRUSTED_WORDS` 的书写顺序拼，所以两个来源同时命中时措辞固定。
        """
        present = set(origins)
        hit = [words for origin, words in cls._UNTRUSTED_WORDS.items()
               if origin in present]
        return "、".join(hit) if hit else "不可信来源"

    @classmethod
    def authorize(cls, payload: ActionAuthorizeRequest) -> ActionAuthorization:
        reasons: list[str] = []
        stripped: list[str] = []
        required: list[str] = []
        allowed_arguments: dict[str, Any] = {}
        # 被放行、但**一条来源都没申报**的字段。`purpose_bound` 报的就是这一件事，
        # 详见 `_result` 的 docstring。三条提前返回都放行了零个字段，所以传空表
        # ——不是「碰巧对」，是同一条规则在「没有字段流出去」时的取值。
        unbound: list[str] = []
        spec = cls._SPECS.get(payload.action)
        if spec is None:
            # 没有注册就没有「这个动作允许哪些采集目的」这份清单，也就无从谈绑定。
            # 这一支和下面两支的区别是实质的：这里缺的是**判据本身**，
            # 那两支只是恰好没有字段需要判。
            return cls._result(
                AuthorizationDecision.DENY,
                ["动作没有在受控工具清单中注册。"],
                {},
                list(payload.arguments),
                [],
                None,
                payload,
            )
        if spec.forbidden:
            return cls._result(
                AuthorizationDecision.DENY,
                ["该动作被产品安全边界明确禁止，不能由Agent执行。"],
                {},
                list(payload.arguments),
                [],
                unbound,
                payload,
            )
        if spec.emergency_only and not payload.emergency:
            return cls._result(
                AuthorizationDecision.DENY,
                ["该能力仅允许在明确紧急状态下调用。"],
                {},
                list(payload.arguments),
                [],
                unbound,
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
            if fact.trusted_for_control and fact.origin not in cls._UNTRUSTED_FOR_CONTROL:
                trusted_values_by_name.setdefault(fact_key, set()).add(serialized_value)
            if fact.origin in cls._UNTRUSTED_FOR_CONTROL:
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
            if (origins & cls._UNTRUSTED_FOR_CONTROL) and fact_key in cls._CONTROL_FIELDS:
                trusted_values = trusted_values_by_name.get(fact_key, set())
                untrusted_values = untrusted_values_by_name.get(fact_key, set())
                argument_value = canonical_json(value)
                if not trusted_control.get(fact_key, False) or not trusted_values:
                    stripped.append(key)
                    reasons.append(
                        f"{cls._untrusted_words(origins)}的 {key} 不能控制副作用或授权。")
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
            if not purposes:
                # 上面那道目的检查是 `if purposes and not …`——**一条来源都没申报的
                # 字段会整条跳过它**，然后照常放行。默认 `facts=[]`，所以这不是构造
                # 出来的路径：不带 facts 送一笔 create_payment_request，
                # amount_cents（受控字段）就是这样进 allowed_arguments 的。
                # 决定不变（这里只记账、不改判），但这一笔不能再自称目的绑定。
                unbound.append(key)
            allowed_arguments[key] = value
        missing = sorted(spec.required_fields - allowed_arguments.keys())
        if missing:
            reasons.append("缺少必需字段：" + "、".join(missing))
            return cls._result(
                AuthorizationDecision.CLARIFY, reasons, allowed_arguments, stripped, ["补充必需信息"], unbound, payload
            )
        if not cls._goal_aligned(payload.goal, payload.action):
            reasons.append("动作与老人当前明确目标不一致。")
            return cls._result(AuthorizationDecision.DENY, reasons, allowed_arguments, stripped, [], unbound, payload)
        if payload.ambiguity >= 0.35:
            reasons.append("输入歧义超过副作用动作阈值。")
            return cls._result(
                AuthorizationDecision.CLARIFY, reasons, allowed_arguments, stripped, ["老人重新确认目标"], unbound, payload
            )
        if spec.reversible_required and not payload.reversible:
            reasons.append("该步骤必须使用可撤销的预留/草稿接口，不能直接不可逆提交。")
            return cls._result(AuthorizationDecision.DENY, reasons, allowed_arguments, stripped, [], unbound, payload)
        if spec.elder_confirmation and not payload.user_confirmed:
            required.append("老人本人确认")
            return cls._result(
                AuthorizationDecision.REQUIRE_ELDER_CONFIRMATION,
                reasons or ["副作用动作必须由老人确认。"],
                allowed_arguments,
                stripped,
                required,
                unbound,
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
                unbound,
                payload,
            )
        # 这句话原先对「一条来源都没申报」的请求也照说——它声称的正是
        # 「字段来源满足」。改成只在真的都申报了目的时才说。
        reasons.append(
            "动作、目的、字段来源、权限和确认条件均满足。"
            if not unbound
            else "动作、权限和确认条件均满足；字段来源未全部申报，见下。"
        )
        return cls._result(AuthorizationDecision.ALLOW, reasons, allowed_arguments, stripped, [], unbound, payload)

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
        unbound: list[str] | None,
        payload: ActionAuthorizeRequest,
    ) -> ActionAuthorization:
        """`unbound` 决定 `purpose_bound`，并把不绑定的原因说给读的人听。

        ## 原先 `purpose_bound` 不携带信息

        它是**调用点传进来的字面量**：只有「动作没有在受控工具清单中注册」那一支
        传 `False`，其余九支全部传 `True`。也就是说
        `purpose_bound == (spec is not None)`——而这件事 `reasons[0]` 已经逐字
        说了（「动作没有在受控工具清单中注册。」）。实测十条路径，
        `purpose_bound` 只有那一支是 False。`common.js` 把它渲染成「目的绑定」。

        ## 而它不只是无聊，它会说错

        剥离循环里的目的检查是 `if purposes and not purposes.intersection(...)`
        ——`payload.facts` 默认是空表，**一条来源都没申报的字段 `purposes` 为空，
        整条跳过这道检查，然后照常进 `allowed_arguments`**。实测：

            action=create_payment_request, facts=[]
            arguments={bill_id, amount_cents, elder_id}
              → decision=allow, stripped=[], purpose_bound=true
                reasons=[「动作、目的、字段来源、权限和确认条件均满足。」]

        `amount_cents` 在 `_CONTROL_FIELDS` 里。一笔连来源都没申报的金额走到
        allow，而同一份响应说「字段来源满足」、「目的绑定：是」。这不是少说一句，
        是说反了。

        ## 现在它表达什么

        `purpose_bound` = **这次决定放行的每一个字段，都申报过采集来源，
        且申报的目的在这个动作的清单里**。

        - `None`：动作没注册，连「允许哪些目的」这份清单都不存在——不是没通过
          检查，是没有检查可做，所以不能声称绑定。
        - `[]`：放行的字段全都申报了目的（含「一个字段都没放行」的情形：
          没有东西流出去，也就没有东西是不绑定的）。
        - 非空：这几个字段被放行了却没申报来源，名字直接写进 `reasons`。

        它仍然是纯函数：只看 `payload`，不读库。`run_mass_audit_v5.py`
        拿它跑一百万条合成用例，这一点不能变。

        ## 为什么不顺手把这些字段也剥掉

        剥掉就改了 `decision`——一个不带 facts 的调用方会从 allow 变成
        clarify/deny。这一层是**策略模拟器**：`ActionAuthorizeRequest` 里没有
        task_id，`user_confirmed` / `family_approvals` 都是调用方自报，服务端
        无从核实，两个调用方也都不执行任何东西。让模拟器如实报出「这一笔我没法
        声称目的绑定」是它能诚实做到的事；替真实闸门做判决不是。
        """
        purpose_bound = unbound is not None and not unbound
        if unbound:
            reasons = [
                *reasons,
                "字段 " + "、".join(sorted(unbound)) + " 没有申报采集来源与目的，"
                "本次决定不能声称目的绑定。",
            ]
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
    def verify(cls, bundle: TaskProofBundle, *,
               recorded: str | None = None,
               require_record: bool = False) -> ProofVerifyResult:
        """校验一份凭据。

        ## `recorded` 是什么，为什么它是这里最要紧的一项

        下面那五项检查**全都是自洽性检查**：重算的 root 跟包自己声称的 root 比、
        重算的 digest 跟包自己声称的 digest 比，而 `audit_chain_claim` 干脆就是
        `bundle.audit_chain_valid`——包自己说自己有效。

        也就是说，凭空造一份包（事件随便编、两个哈希按规则算对、
        `audit_chain_valid` 填 true）能拿到「通过」。这五项能挡住的只有
        **改过的**包，挡不住**新造的**包。

        `recorded` 是服务器留存的那份原文（`proof_bundles_v5.bundle_json`）。
        传了它，才是在回答「这份东西是不是我们出的」。

        ## `require_record`：「自洽」和「是我们出的」是两个问题

        不带它（默认）时，这个方法只回答第一个问题——结构对不对。
        单元判据就是这么用的，也适合校验一份从别处拿来的包。
        这时「库里没有这个 id」不判否，只在 `message` 里说清边界。

        带上它时，回答第二个问题。**端点必须带**：服务器总是知道自己有没有
        出过这份凭据，那时把一份从没出过的包报成「通过」，就是给出一个假的
        保证——界面上的绿勾看的是 `valid`，不是 `message`。

        实测这道检查挡住了前五项挡不住的两种伪造：

            冒用一个真实 id、内容全编          前五项全 True
            真的那一份、只把 generated_at 倒签  前五项全 True
                                              （它不参与 proof_digest 的计算）
        """
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
            # 这一项是包自己声明的，不是这里验出来的。留着是因为一份声明
            # 「当时审计链是断的」的凭据本来就不该算通过；但它证明不了任何事。
            "audit_chain_claim": bundle.audit_chain_valid,
        }
        matched: bool | None = None
        if recorded is not None:
            submitted = canonical_json(bundle.model_dump(mode="json"))
            matched = hmac.compare_digest(recorded, submitted)
            checks["matches_server_record"] = matched
        elif require_record:
            # 端点这一侧「查不到」= 这台服务从没出过这份凭据。
            matched = False
            checks["matches_server_record"] = False
        valid = all(checks.values())
        if matched is False and recorded is None:
            message = "服务器上没有这份凭据的留存记录——它不是这台服务出的。"
        elif matched is False:
            message = "这份凭据和服务器留存的那一份不一致。"
        elif not valid:
            message = "证明包验证失败。"
        elif matched:
            message = "证明包验证通过，而且和服务器留存的那一份逐字一致。"
        else:
            # 自洽，但没去比留存记录（`require_record=False`）。
            # **说清楚这句话的边界**：上面五项挡得住改过的包，挡不住新造的包。
            message = "证明包自身是自洽的，但没有和服务器的留存记录比对，不能据此认定它出自这里。"
        return ProofVerifyResult(valid=valid, checks=checks, message=message)


class ExplanationService:
    #: 「系统听懂了什么」这一格最多列几条。
    #:
    #: 这个数原先是写死在切片里的一个裸 12，**没有任何说明**，
    #: 而超出去的那几条**直接消失、卡上一句话都没有**。
    #:
    #: 用独立对照源（直接读库里那一列槽位 JSON，不读
    #: `/v2/tasks` 那个删减过的 `details` 视图）量出来的，同一笔水费：
    #:
    #:     家属点头前   够格上屏 13 行，卡上 12 行   少 1 行
    #:     家属点头后   够格上屏 16 行，卡上 12 行   **少 4 行**
    #:                  没上屏的：payment_request_id、period、
    #:                            task_graph_digest、teach_back_attempts
    #:
    #: `period` 是「所属月份」、`teach_back_attempts` 是「复述了几遍」
    #: ——后者正是这个产品那条招牌安全机制的证据，而它从评委那一屏上
    #: 消失了。留下哪 11 条靠的是 `slots` 的插入顺序，不是重要性。
    #:
    #: 这和 KNOWN_ISSUES 第 296 条（「它不数它没念出来的那几条」）
    #: 是同一个形状，而那一条当时判成了缺陷。
    #:
    #: **上限本身不动**（12 条是版面决定，这里不替产品改版面）。
    #: 改的是「剩下的那几条不许无声无息」。
    UNDERSTOOD_CAP = 12

    #: 一笔事务办完之后，`task.result` 里**真的存在**的那几个回执号 → 屏幕上的说法。
    #:
    #: 名字不是猜的，是三条写入路径给的（`services.py` 的 `book` / `settle` /
    #: `ReminderService.create`，经 `engine.py:991` 和 `engine.py:1143` 落库）：
    #:
    #:     挂号  {"appointment_id": "appt-…", …,        "verification": {…}}
    #:     缴费  {"bill_id": "bill-water-2026-07-demo", "verification": {…}}
    #:     提醒  {"reminder_id": "rem-…", "title": …,   "verification": {…}}
    _RECEIPT_LABELS: tuple[tuple[str, str], ...] = (
        ("appointment_id", "挂号回执号"),
        ("bill_id", "缴费账单编号"),
        ("reminder_id", "提醒编号"),
    )

    #: 每一类事务在办的过程中读到的那一份记录：
    #:     任务类型 → (「读到了」的槽位判据, 来源说法, 用途, 括号里报哪几个槽位)
    #:
    #: 判据一律是「工具把答案写回槽位了」。只凭任务类型就宣称读过某份记录，
    #: 和原先那两行常量是同一个毛病——那句话对每一笔都成立，也就对每一笔都没有信息。
    _DOMAIN_SOURCES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
        "bill_payment": (
            "bill_id", "家庭账单记录", "核对是哪一张账单、金额和缴费期限",
            ("bill_type", "period"),
        ),
        "hospital_registration": (
            "hospital", "医院出诊号源目录", "核对这家医院这个科室这位医生有没有号",
            ("hospital", "department"),
        ),
        "reminder": (
            "due_date", "这条提醒的日期和时间", "按老人所在时区算出到点提醒的时刻",
            ("due_date", "due_time"),
        ),
        "form_assistance": (
            "form_goal", "老人本人说明的表单事项", "协助填写，身份认证一律不代办",
            (),
        ),
    }

    @classmethod
    def completion_evidence(cls, task: Any) -> list[str]:
        """这一笔办完之后，记录里**真的存在**的那几项凭据。

        ## 原先找的是三个不存在的键

        `v5_api.py` 那一行找 `payment_receipt` / `receipt_id` /
        `verification_digest`——这三个名字**全仓库只出现在那一行**，
        没有任何代码写过它们。而一笔真办完的缴费，`task.result` 是（实测）：

            {"bill_id": "bill-water-2026-07-demo",
             "verification": {"accepted": true, "proof_digest": "cd5b03…"}}

        于是走完整条真流程——老人复述金额、家人接力点头、状态核验通过——评委页
        「办成的凭据」那一行仍然是兜底句「任务尚未生成权威完成证据」。一笔每一步
        都留了痕的缴费，恰恰在最该证明它留了痕的那一格上说自己没有凭据。

        挂号和提醒当时是好的，因为 `appointment_id` / `reminder_id` 恰好是真键
        ——五个名字里蒙对了两个，而那两个把这个缺陷盖住了。

        ## 为什么必须先看状态

        `bill_id` 出现在 `task.result` 里**不等于**这笔钱交了。一张已经缴过的
        账单再被要求缴一次，`engine.py:723` 把任务判成 `cancelled` 并写下
        `{"bill_id": …, "period": …}`——实测就是这个形状。不看状态就认 `bill_id`，
        这一格会给一笔**从没执行过**的事务印出一个账单编号。那是编造证据，
        比少一行糟得多。

        所以：没办完的一律不给凭据；办完了就只报记录里有的那几项。
        """
        if task.status.value != TaskStatus.COMPLETED.value:
            return []
        result = task.result or {}
        lines = [f"{label}：{result[key]}" for key, label in cls._RECEIPT_LABELS if result.get(key)]
        verification = result.get("verification")
        if isinstance(verification, dict) and verification.get("accepted") is True:
            digest = verification.get("proof_digest")
            lines.append(f"状态核验：已通过（摘要 {digest}）" if digest else "状态核验：已通过")
        return lines

    @staticmethod
    def _no_evidence_line(task: Any) -> str:
        """一格空着的时候说哪一句。

        「还没办完」和「办完了但记录里没留下凭据」是两件事，原先是同一句
        「任务尚未生成权威完成证据」。后者真实存在：种子那笔已完成缴费的
        `result` 是 `{"paid": True, "authority": …, "amount_yuan": …}`，
        既没有回执号也没有核验块（见交回的越界发现）。对它说「尚未生成」是错的。
        """
        if task.status.value != TaskStatus.COMPLETED.value:
            return "任务尚未生成权威完成证据"
        return "这一笔已经收尾，但记录里没有留下可核验的完成凭据"

    @classmethod
    def _data_used(cls, task: Any, approvals: list[dict[str, Any]], *, has_params: bool) -> list[dict[str, str]]:
        """这一笔**实际**用到了哪些数据。

        原先是两行字面常量（`老人明确输入` / `受控工具返回`）。实测对一个
        `awaiting_family_approval` 的风险 4 缴费任务和一个 `completed` 的缴费
        任务**逐字相同**——而评委页把这一格渲染成「用到了哪些数据」，读起来像是
        这一笔算出来的。一句对每一笔都成立的话，等于没说。

        每一行都挂在一个能从记录里读出来的判据上，读不出来的就不出现这一行。
        「宁可少一行，也不要编一行」：这一格的价值全在「它只说这一笔的事」。
        """
        slots = task.slots or {}
        result = task.result or {}
        rows: list[dict[str, str]] = []
        if has_params:
            # 判据和「系统听懂了什么」共用一份过滤结果（见 `build`），
            # 这样两格不可能一边列着参数、一边说没用到参数。
            rows.append({"source": "这一笔记下的事项参数",
                         "purpose": "确定要办的是哪一件事、按什么参数办"})
        domain = cls._DOMAIN_SOURCES.get(task.task_type.value)
        if domain:
            gate, source, purpose, detail_keys = domain
            if slots.get(gate):
                detail = " ".join(str(slots[key]) for key in detail_keys if slots.get(key))
                rows.append({"source": f"{source}（{detail}）" if detail else source,
                             "purpose": purpose})
        if slots.get("elder_confirmation_hash"):
            rows.append({"source": "老人本人复述的内容",
                         "purpose": "核对听到的金额或事项和要办的是同一件"})
        if approvals or slots.get("family_approved"):
            rows.append({"source": "家人在确认表上的接力决定",
                         "purpose": "重要的事两边都点头才执行"})
        if result:
            rows.append({"source": "受控工具返回的执行结果",
                         "purpose": "核对最终状态，而不是听模型说办成了"})
        if isinstance(result.get("verification"), dict):
            rows.append({"source": "状态核验器的判定",
                         "purpose": "决定这一笔算不算办成"})
        return rows

    @classmethod
    def _stored_data(cls, task: Any, approvals: list[dict[str, Any]]) -> list[str]:
        """为这一笔存下了什么。同上：每一行都要有判据，拿不到就不说。"""
        slots = task.slots or {}
        result = task.result or {}
        stored = ["这一笔的状态、类型和必要参数"]
        if slots.get("elder_confirmation_hash"):
            stored.append("老人复述核验的摘要（存摘要，不存原话）")
        if task.approval_digest:
            stored.append("家人批准绑定的参数摘要（参数一改，原批准即失效）")
        if approvals:
            stored.append(f"家人确认表上的{len(approvals)}条决定")
        if slots.get("payment_request_id"):
            stored.append("发给家人的付款请求编号（优活自己不扣款）")
        verification = result.get("verification")
        if isinstance(verification, dict) and verification.get("proof_digest"):
            stored.append("这一笔的状态核验摘要")
        # 至少有一条：调阅这张卡本身就会往链上写一条（`v5_api.py` 的
        # `TASK_EXPLANATION_VIEWED`）。评委页那段自述说的就是这件事。
        stored.append("这一笔的审计事件（调阅这张卡本身也会记一条）")
        return stored

    @classmethod
    def _capped(cls, understood: list[str]) -> list[str]:
        """超出上限时，**把少了几条说出来**。

        末尾那一句里刻意**不带**「：」，因为 `judge.js` 的 `slotLine`
        按「：」把每一行拆成「键：值」去查词表。不带的话它原样留着。
        （带也不会出错——查不到的键会退回原值，渲染结果一样——
        但不带更不容易被将来的人读错。）
        """
        cap = cls.UNDERSTOOD_CAP
        if len(understood) <= cap:
            return list(understood)
        hidden = len(understood) - (cap - 1)
        return understood[:cap - 1] + [
            f"另有{hidden}项没有列出来，这一格最多列{cap}项。"]

    @classmethod
    def build(cls, task: Any, approvals: list[dict[str, Any]], evidence: list[str]) -> ExplanationCard:
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
        # `understood` 的第一项是任务类型，不是参数；有没有参数看的是它之后还剩不剩。
        data_used = cls._data_used(task, approvals, has_params=len(understood) > 1)
        stored = cls._stored_data(task, approvals)
        return ExplanationCard(
            task_id=task.id,
            summary=f"{task.task_type.value} · {task.status.value}",
            current_status=task.status.value,
            risk_level=int(task.risk_level),
            what_i_understood=cls._capped(understood),
            why_this_action=why,
            data_used=data_used,
            confirmations=confirmations or ["尚无确认记录"],
            completion_evidence=evidence or [cls._no_evidence_line(task)],
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

    #: 由弱到强。用来取「更严的那一个」，不是给界面看的。
    _RANK: dict[SyncSensitivity, int] = {
        SyncSensitivity.NORMAL: 0,
        SyncSensitivity.PERSONAL: 1,
        SyncSensitivity.HIGH: 2,
    }

    @classmethod
    def governing_sensitivity(cls, stored: object, incoming: SyncSensitivity) -> SyncSensitivity:
        """这次合并按哪个敏感度判：**库里那一列和这次报上来的，取更严的。**

        ## 为什么不能只用写入方报的那个

        `may_auto_merge` 原先拿的是 `payload.sensitivity`——**由写入方自己声明
        这条数据敏不敏感**。而 `SyncOperationRequest.sensitivity` 的默认值
        就是 `NORMAL`，也就是不填就自动拿到最弱的保护。

        实测（同一个操作，只改自报的那个标签）：

            诚实报 high + 过期的 base_version  → conflict
                「高敏感数据不会自动覆盖，需要老人或家属明确选择。」
            自报 normal + 同样过期的 base_version → applied
                一个服药剂量从 5 静默变成 500

        更糟的是原先那条 UPDATE 还把库里那一列覆盖成写入方报的值，
        所以**一次成功的降级会留存**，之后每一次写入都不再受保护。

        这和 `proofs/verify` 是同一个形状：权威副本就在同一行数据上，
        而判断用的是调用方自己说的话。

        ## 库里那个值读不出来时按最严处理

        这一列是从枚举写进去的，理论上不会解析失败。真失败了就当 HIGH——
        一条剂量该不该被自动覆盖，读不出标签时的正确答案是「先别覆盖，
        让人来选」，不是「按最宽松的来」。
        """
        try:
            base = SyncSensitivity(str(stored))
        except ValueError:
            return SyncSensitivity.HIGH
        return base if cls._RANK[base] >= cls._RANK[incoming] else incoming


class PrivacyRedactor:
    # 边界是「不紧邻字母或数字」。理由和 `privacy.py` 里那一段完全相同：
    # `(?<!\d)...(?!\d)` 只排除相邻的数字，而十六进制摘要里那串数字紧邻的是
    # 十六进制**字母**，于是摘要会被从中间切开换成 `[账号已隐藏]`。
    # 实测 20 万个 sha256 有 4.58% 会被改掉。
    #
    # **这是这个仓库里的第二份脱敏器**（另一份在 `privacy.py`），两份的范围
    # 还不一样（这里 16–19 位，那边 13–19 位）。没有合并成一份：两者的语义
    # 有别（那边的验证码规则要先看上文有没有出现「验证码」），合并要改行为。
    # 判据 `test_a_digest_survives_redaction.py` 同时钉住两份，
    # 所以改了一份忘了另一份会红。
    _EDGE_L = r"(?<![0-9A-Za-z])"
    _EDGE_R = r"(?![0-9A-Za-z])"
    _PHONE = re.compile(
        _EDGE_L + r"(1[3-9]\d(?:[ -]?\d){8}|\d{3,4}[ -]?\d{7,8})" + _EDGE_R)
    _ID = re.compile(_EDGE_L + r"\d{17}[\dXx]" + _EDGE_R)
    _CARD = re.compile(_EDGE_L + r"(?:\d[ -]?){16,19}" + _EDGE_R)
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
