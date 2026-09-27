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

from . import __version__
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

    #: 一句话接在另一句后面时，终止标点只留一个。
    #:
    #: 和 `plan()` 里那四处判断用**同一组字符**：那几处保证 `visual_text`
    #: 一定以其中之一结尾，`_append_clause` 据此决定要不要补。
    #: 两处各写一份字符集，迟早分叉成「一边认为已经有句号、一边认为没有」。
    _TERMINALS = "。！？…"

    #: 需要她再说一遍时，开头那句提示。**按成因分两句。**
    #:
    #: `plan()` 里那个标志有两个成因：
    #:
    #:     require_repeat = repeat_sensitive and (low_confidence or recent_retries > 0)
    #:
    #: 原先两个成因共用一句「我刚才没有完全听清」。在第二个成因上，
    #: 那是一句它并不知道的事实——而在真会发的那个载体上，
    #: 第二个成因就是**默认**：
    #:
    #:     elder.js:809   asr_confidence 写死 1.0 -> low_confidence 恒为 False
    #:     elder.js:1065  recentRetries += 1 在提交任务的 catch(e) 里（断网/接口失败）
    #:     elder.js:1950  recentRetries += 1 在 rec.onerror 里，错误码包含
    #:                    audio-capture（根本没有麦克风）、network（语音没送出去）、
    #:                    aborted（那次听被打断了）
    #:
    #: 她家里断网、或这台手机没有麦克风，她听到的都是「我刚才没有完全听清」。
    #: 1065 行**下面第二行**的注释记着同一课——「『系统暂时不可用』是错的诊断。
    #: 她自己家里断网时，说的是我们坏了」。同一个错诊断，在念出来的那句里还活着。
    #:
    #: 后一句刻意**不说原因**：这一层分不出是误听、断网还是没有麦克风，
    #: 那就不要替它猜一个。「我慢一点说」是真的，由 `speech_rate * 0.92` 兜着。
    _MISHEARD_PREFIX = "我刚才没有完全听清。"
    _RETRY_PREFIX = "这一步我们再来一次，我慢一点说。"

    @classmethod
    def _append_clause(cls, head: str, clause: str) -> str:
        """把 `clause` 接在 `head` 后面，**不重复终止标点**。

        原先四处都是 `f"{head}。{clause}"`，无条件补一个句号。而
        `visual_text` 已经保证以终止标点结尾，于是必然拼出「。。」——
        实测六个用例 `speak_text` 6/6 中招，`visual_text` 0/6。
        **她听到的正是 `speak_text`。**

        `head` 为空时直接回 `clause`：那时补一个句号会让整句以标点开头。
        """
        if not head:
            return clause
        if head[-1] in cls._TERMINALS:
            return head + clause
        return head + "。" + clause

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
        if visual_text and visual_text[-1] not in cls._TERMINALS:
            visual_text += "。"

        # SKILL 的不变量是「每轮最多展示三个选项；**高风险或连续失败时最多一个**」。
        #
        # 原先这里是 `one_question_mode and high_risk`。而上面那行
        # `one_question_mode = high_risk or low_confidence or overloaded`
        # 让这个合取**恒等于 `high_risk`**——`one_question_mode` 在里面一个
        # 作用都没有，只是让这一行读起来像是照顾到了它。
        #
        # 实测（5 个选项、低风险 2、置信度 0.95）：
        #     连续失败 2 次 -> 摆了 3 个     连续失败 3 次 -> 摆了 3 个
        # 而同一趟 `cognitive_load_score` 从 0.58 涨到 0.62——
        # 它**量到了**那几次失败，只是没拿这个信号去收窄选项。
        #
        # `low_confidence` 刻意**不**进这个条件：SKILL 只点了「高风险」和
        # 「连续失败」两样，置信度不足那一条走的是「先澄清，不能猜测」，
        # 那是要不要追问，不是摆几个按钮。判据两侧都钉
        # （`test_low_confidence_alone_does_not_collapse_the_choices`）。
        max_options = 1 if high_risk or overloaded else profile.max_options
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

        # 要她开口的那两档，屏幕上必须留着「做什么」那一句。
        #
        # `one_question_mode` 取的是 `sentences[0]`——而这几条消息都是
        # 「事实。指令。」的写法，第一句是事实。实测 risk=4 的付款确认，
        # `visual_text` 只剩「查到7 月的电费是126.50元，截止日期是7 月 30 日。」，
        # 「请您把金额说一遍」和「不想办就说「取消任务」」两句都掉了。
        #
        # 语音那一路是补了的（下面 `speak_text` 那句），但这一页专门为「语音不响」
        # 留了「⌨ 用打字说」——走那条路的人，屏幕是她唯一的通道。
        #
        # 42 个字装不下事实 + 指令，二者只能留一句时**留指令**：
        # 付款的指令里本来就带着金额，事实那句不带任何可执行的东西。
        #: 第三个析取项是为急救那一类开的窄门，理由写在
        #: `_EMERGENCY_MARKERS` 上面。**前两项一个都不能动**：
        #: 低风险收着说是有意的决定。
        needs_her_move = (require_teach_back or request.risk_level >= 4
                          or cls._is_emergency_advice(message))
        if needs_her_move:
            asks = cls._ask_sentences(sentences)
            if asks and not cls._ask_sentences([visual_text]):
                # 先试整句。量过这几条真实消息：付款确认 63 字、复述不符 52 字、
                # 诈骗提醒 42 字，都在 90 以内——**根本不用在事实和指令之间二选一**。
                #
                # 上一版只留指令句，于是复述不符那一条只剩「请您再说一遍…」，
                # 「您说的是800.00元」和「我先不办」都掉了：她不知道自己说错了。
                whole = "。".join(sentences)
                if whole and whole[-1] not in cls._TERMINALS:
                    whole += "。"
                if len(whole) <= cls._ASK_CHAR_CEILING:
                    visual_text = whole
                else:
                    # 真的超了才退回「优先留指令句」——没有指令的那一屏是死路。
                    #
                    # **但别只留指令。** 上面那一课（只留指令句，于是
                    # 「您说的是800.00元」掉了，她不知道自己说错了）在这条
                    # 退路上一样成立。实测症状回话走的正是这一支——整句
                    # 95 字，只超了 5 个字：只留指令的话，屏幕上一上来就是
                    # 「要是突然加重…直接打急救电话或者叫人。」，
                    # 而她说的只是牙有点疼，开头那句「听着您不太舒服」
                    # 一个字都不剩。装得下就把第一句一起留着。
                    lead = ([sentences[0]] if sentences
                            and sentences[0] not in asks else [])
                    joined = "。".join(lead + asks)
                    if joined and joined[-1] not in cls._TERMINALS:
                        joined += "。"
                    if len(joined) > cls._ASK_CHAR_CEILING:
                        # 连第一句都装不下，那就还是只留指令。
                        joined = "。".join(asks)
                        if joined and joined[-1] not in cls._TERMINALS:
                            joined += "。"
                    visual_text = cls._truncate_at_boundary(
                        joined, cls._ASK_CHAR_CEILING)
                if visual_text and visual_text[-1] not in cls._TERMINALS:
                    visual_text += "。"

        # 下面四处原先都是无条件拼一个「。」：`f"{visual_text}。…"`。
        #
        # 而上面 126-138 行费了功夫保证 `visual_text` **一定**以「。！？…」
        # 之一结尾。前一段的努力保证了后一段必然重复——两处各自都「对」，
        # 合起来才错。实测六个用例（句号结尾 / 无标点结尾 / 列选项 / 重试三次 /
        # 问号结尾 / 引号结尾）：**`speak_text` 6/6 出现「。。」**，
        # 而 `visual_text` 0/6。**她听到的正是 `speak_text`。**
        #: 选项到底**念出口了没有**。下面 `hidden_count` 那一句原先是
        #: **无条件**拼的，而「您可以说：…」只在 YES_NO 那一支拼。
        #:
        #: 实测（risk=3、6 个选项、听得清、没重试）：
        #:     visible_options = ['第一医院']            只留了一个
        #:     speak_text = 「请选择医院。为了避免办错，请您用自己的话
        #:                   再说一遍要办理的内容。**还有5个选择**，
        #:                   需要时我再慢慢说。」
        #:
        #: 那个 5 是 `6 - 1` 算出来的，而那个「1」**一个字都没念出来**。
        #: 她听到「还有5个选择」，却从没听到第一个是什么。这是个语音
        #: 优先的产品，`visible_options` 在语音载体上根本不出声。
        #:
        #: 复述那一支和家属接力那一支问的不是「选哪个」，所以修法是
        #: **那两支不报这个数**，而不是硬把选项塞进去——塞进去会让
        #: 「请您用自己的话再说一遍」后面跟一串医院名，那是另一句错话。
        options_spoken = False
        if require_teach_back:
            confirmation_style = ConfirmationStyle.TEACH_BACK
            speak_text = cls._append_clause(
                visual_text, "为了避免办错，请您用自己的话再说一遍要办理的内容。")
            expected = "老人复述关键对象、金额或时间"
        elif request.risk_level >= 4:
            confirmation_style = ConfirmationStyle.FAMILY_RELAY
            speak_text = cls._append_clause(
                visual_text, "这一步需要您先确认，再请家人接力。")
            expected = "老人确认后等待家属审批"
        else:
            confirmation_style = ConfirmationStyle.YES_NO
            speak_text = visual_text
            if visible_options:
                speak_text = cls._append_clause(
                    speak_text, "您可以说：" + "，".join(visible_options))
                options_spoken = True
            expected = "老人选择一个选项或要求重复"

        if require_repeat:
            # 只有 `low_confidence` 那一支才有资格说「没听清」。
            # 另一支是重试驱动的，成因这一层看不见——见 `_RETRY_PREFIX`。
            speak_text = (cls._MISHEARD_PREFIX if low_confidence
                          else cls._RETRY_PREFIX) + speak_text
        #: 只在**真的把选项念出来了**的时候才报剩下几个。见上面那段。
        if hidden_count and options_spoken:
            speak_text = cls._append_clause(
                speak_text, f"还有{hidden_count}个选择，需要时我再慢慢说。")

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
            rationale.append("高风险步骤使用复述确认，而不是只问「是/否」。")
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

    #: 「这一句在要求她做点什么」的标记。**不是从空气里想的**，是这几条真实
    #: 消息里用的词（`engine.py` 的 `user_message` / `BillingService`）：
    #:
    #:     请您把金额说一遍，例如「确认支付126.50元」
    #:     不想办就说「取消任务」
    #:     请您再说一遍「确认支付126.50元」
    #:     请不要透露密码、验证码，也不要立即转账
    #:
    #: 只用来「挑出该留的那一句」，挑错了最坏的结果是多留一句话，
    #: 不会少留——所以宁可宽一点。
    _ASK_MARKERS = ("请", "说一遍", "再说", "取消", "不要", "别")

    #: 要她开口时，`visual_text` 允许超出「舒适字数」到这个数。
    #: 取的是 `InteractionProfile.max_sentence_chars` 自己的取值上界，
    #: 不另设一个数——那样又多一个要维护的常量。
    _ASK_CHAR_CEILING = 90

    #: 带着急救指引的消息，**不按「低风险就收着说」处理**。
    #:
    #: 实测：她说「我牙有点疼」，回包 risk_level 是空的（外壳按
    #: `elder.js:972` 传 1），整句 95 字，而屏幕上和念出来都只剩
    #: 「听着您不太舒服。我不能看病，也不敢替医生判断。」
    #: ——六个红旗词（急救/叫人/站不稳/说不清话/胸口发闷/突然加重）
    #: 一个都没到她那儿。她拿到的是一句免责声明，没有出路。
    #:
    #: 这道门是**窄的**：不是「凡有指令都全文照登」。低风险要收着说
    #: 是这个类存在的理由，`test_a_low_risk_line_is_still_shortened`
    #: 专门守着它。这里只放急救这一类。
    #:
    #: 词是量出来的：整包 1268 条中文串里「急救」命中 5 条、
    #: 「拨打 120」命中 2 条，七条全是真的急救指引，没有一条误伤。
    #:
    #: 用「拨打 120」而不是光一个「120」：后者会命中
    #: 「这个月电费是120.50元」这样的金额。
    #:
    #: **「叫人」量过之后没有收进来。** 它命中 3 条，而那 3 条全是
    #: 「急救」那 5 条的子集——也就是说它在现有语料上**不可能有一个
    #: 独立见证**：删掉它，没有任何一条判据会红。一个拿不到见证的
    #: 放宽只扩大误伤面，不扩大覆盖。哪天有一句「叫人」而不提急救的
    #: 指引出现，再连同它的见证一起加。
    _EMERGENCY_MARKERS = ("急救", "拨打 120")

    @classmethod
    def _is_emergency_advice(cls, message: str) -> bool:
        """这条消息里有没有「现在该去叫人/打电话」这种出路。"""
        return any(m in message for m in cls._EMERGENCY_MARKERS)

    @classmethod
    def _ask_sentences(cls, sentences: list[str]) -> list[str]:
        """这些句子里，哪几句在要求她做点什么。"""
        return [s for s in sentences if any(m in s for m in cls._ASK_MARKERS)]

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
                # **这一条出口也要留记号。**
                #
                # 原来它直接 return，不带任何标记；而 `plan()` 紧接着会补一个
                # 「。」（末字不是终止标点），于是一句被剪掉一半的话在屏幕上
                # 长得像说完了。实测：「接下来有3件事：…病历、…吃降压药。」
                # ——说 3 件，列了 2 件，掉的是明天那件社区量血压。
                #
                # 42 字上限下扫过一遍：1492 条会上屏的中文串里，32 条走这条出口
                # 被无声剪掉，其中包括「要是突然加重、说不清话、站不稳……」
                # 那句红旗建议，和只剩「要登记的话。」的半句话。
                #
                # 长度仍然守得住：`idx < len(candidate) <= limit`，所以
                # `candidate[:idx]` 最多 limit-1 个字，加一个「…」正好不超。
                return candidate[:idx].rstrip() + "…"
        # 省略号是**追加**上去的，所以要先给它留一个字的位置。
        #
        # 原先是 `text[:limit] + "…"`——给它 90 就回 91。而
        # `max_sentence_chars` 的取值上界正是 90（`le=90`），也就是说把舒适字数
        # 拉到最大的那位老人，每一句都可能比她设的上限多一个字。
        # 一个函数被告知了上限，就不该越过它。
        return text[:max(1, limit - 1)].rstrip() + "…"


class RelianceCardService:
    """§4.3 的依赖卡。**卡上每一格都必须来自请求里的某个字段**。

    `confirmations` 曾经是这条规矩的反例：`RelianceCardRequest` 收它、
    `TaskGlassBoxService` 算它并传进来，而这里一次都没读过，`RelianceCard`
    也没有对应的字段。实测发三条 `["老人复述金额", "女儿扫码支付",
    "社区网格员在场"]`，响应的 12 个键里一个都没有，三条字符串在整个响应体里
    搜不到——而 `StrictModel` 的 `extra="forbid"` 让调用方以为凡是收下的字段
    都有用（拼错一个字母就是 422）。同一个形状上一轮删掉的是
    `ActivityHeartbeatRequest.metadata`。

    ## 为什么是并进 `who_decides`，不是给卡片加一个新字段

    加字段没有出口：`static/glassbox.js:52` 的 `renderGlassBox` 是**逐格手写**
    的（`我听到` / `要办的事` / `现在这一步` / `准备做` / `谁来决定` / `能否撤销`
    / `下一步` / `信息核验`），不是遍历键名的渲染器。新加一个
    `card.confirmations` 只会多一个没人画的键——正是这一轮要消掉的那个形状，
    而 `static/` 不在本次改动范围内。`who_decides` 已经被画在「谁来决定」那一格。

    ## 为什么这两者本来就该是同一句话

    `who_decides` 和 `TaskGlassBoxService` 那份 `confirmations` 是**同一个输入
    （`risk_level`）的两次独立推导**，而且两处的档位不一样：`who_decides` 在 4
    和 3 各分一次，`confirmations` 只在 4 分一次。于是 `risk_level == 3` 时前者
    说「必要时家属共同确认」，后者只给 `["老人本人"]`——两句话已经不一致了，只是
    因为后者从来没被读过，所以谁都没看见。并成一句之后，风险档位仍然是那句
    政策判断（打头，保持原样），名单是这一步的具体清单，各自说清自己是什么。
    """

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
        # 名单是调用方给的具体清单，风险档位是政策判断，两者都留在这一格里。
        # 去重但保序：同一个人被列两次，念给老人听就是重复播报。
        named: list[str] = []
        for person in request.confirmations:
            if person not in named:
                named.append(person)
        if named:
            who = f"{who}；这一步需要点头的人：" + "、".join(named)
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

    #: 状态 →（现在这一步，下一步）。**第一列逐字等于 `static/common.js` 的
    #: `STATUS_WORD`（自称那一份），一个字都不许在这里另发明一句。**
    #:
    #: 这是那七份状态词表的最后一份。前六份都在前端，上一轮收敛进了 `common.js`；
    #: 这一份在后端，而它是**唯一一份真的从服务器发出去的**——所以它漂了，屏幕上
    #: 就是两句话，而前端那几道判据一条也管不到它。
    #:
    #: ## 实测它上屏的整条路（真打接口拿响应体，不是读代码猜的）
    #:
    #: `build()` 读这张表 → `RelianceCard.current_step` / `next_step` →
    #: `POST /v6/tasks/{id}/glass-box` 的响应体 → `static/glassbox.js:73` 的
    #: 「现在这一步」和 `:77` 的「下一步」两行。请求方两处，都是老人自己那一屏：
    #: `elder.js:855`（设计一二主壳，只在需要确认时摆卡）与
    #: `elder3.js:1000`（设计三，每一回合都摆，所以它什么状态都能摆出来）。
    #:
    #: ## 收敛之前是四处不一致，不是一处
    #:
    #: 上一轮点名的只有 `executing`。把这张表和 `STATUS_WORD` 逐字比，七个键里差四个
    #: （左边是这里原先写的，右边是 `common.js` 的标准说法）：
    #:
    #:     collecting                    正在收集需要的信息  →  正在收集信息
    #:     awaiting_elder_confirmation   等待您复述确认      →  等您复述确认
    #:     awaiting_family_approval      等待家属接力确认    →  等家人接力
    #:     executing                     正在执行           →  正在办理
    #:
    #: 四处全部实测上过屏。前三处走自然路径：「帮我交水费」一句就到
    #: `awaiting_elder_confirmation`，复述一遍金额到 `awaiting_family_approval`，
    #: 「我想挂个号」（不说医院科室）到 `collecting`。`executing` 走的是
    #: `database.py:551` 记下的那条**卡住**的路——缴费推到 executing 之后
    #: `billing.settle` 抛 `KeyError('bill_id')`，任务回不去。也就是说这一格最
    #: 可能被读到的时候，正是一笔钱不知道办成没有、老人最需要看懂屏幕的时候。
    #:
    #: 而 `elder.js` 一个回合里那两句话是**上下挨着**的：气泡角标走它自己的
    #: `STATE_WORD[data.task_status]`（值等于 `STATUS_WORD`），玻璃盒那一行走这里。
    #: 于是同一拍、同一屏，上面写「等您复述确认」，下面写「等待您复述确认」——
    #: 读的人没法判断这是同一件事，也没法判断哪一句更重。
    #:
    #: ## 为什么是字面副本，不是在这里去读 common.js
    #:
    #: `common.js` 是静态资源，不是 Python 模块。让请求路径去读它、现场解析 JS，
    #: 等于给每一次玻璃盒调用加一次文件读和一个手写解析器，而这个仓库已经栽过
    #: 「解析器把代码当注释吃掉」（见 `tests/helpers.py::strip_js_comments` 那段
    #: 注释）——那种漏报在结果里长得和绿一模一样。项目里已有的做法是**字面副本
    #: 加判据逐字钉住**：`common.js:771` 那段注释写的就是 `/app` 那两份为什么可以
    #: 是字面量——「一份被判据钉住的副本是安全的；没被钉住的那五份就是上面那张表」。
    #: 这里照办，钉它的是 `test_one_status_word_reaches_every_surface.py`，
    #: 它从 `TaskStatus` 取键、从 `common.js` 解析说法，再真打一遍接口对响应体。
    #:
    #: 第二列（下一步）**没有**对应的共享表：它是这一层独有的一句提示，不是状态
    #: 标签，`common.js` 里没有它的位置。判据只钉第一列，另外钉住第二列不许把状态
    #: 枚举名漏到屏幕上。
    _STEP_WORDS: dict[TaskStatus, tuple[str, str]] = {
        TaskStatus.COLLECTING: ("正在收集信息", "请回答下一个问题"),
        TaskStatus.AWAITING_ELDER_CONFIRMATION: ("等您复述确认", "请您复述一遍要办的事"),
        TaskStatus.AWAITING_FAMILY_APPROVAL: ("等家人接力", "请家人核对后确认"),
        TaskStatus.EXECUTING: ("正在办理", "请稍候，完成后会核对对方系统状态"),
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
        # A request that has not executed yet can still be withdrawn. Both
        # consumers below must read this same value: the card tells the elder
        # whether she can still back out, and the policy layer refuses actions
        # that are declared irreversible (see `reserve_appointment`'s
        # `reversible_required`). Handing the card the computed value and the
        # policy a literal `True` made one response body contradict itself -
        # `card.reversible` false next to a rollback plan promising an undo -
        # and left that policy gate permanently unreachable from here.
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
                    reversible=reversible,
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
            #: 这一格和 `engine.py` 的兜底话、`elder.js` 的开场气泡是
            #: **同一件事的三个载体**：她没说清要办什么时看到的那张目录。
            #: 三处原先都缺填表那一条线。
            "unknown": "我还不确定您想办什么。可以说「帮我挂号」、「查水费」、"
                       "「提醒我」或「帮我填表」。",
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
            # 和 `/v5/capability-truth` 的 `version` 读同一个常量。这两处此前各写
            # 一个字面量（`"6.0.0"` 和 `"5.0.0"`），于是同一个产品在两张评委页上
            # 有两个版本号。值本身没变，变的是不再有第二处可以单独漂移。
            project_version=__version__,
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
