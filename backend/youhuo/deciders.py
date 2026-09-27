"""决策器层：把「判断」从「生成」里拆出来。

## 这一层从哪来

照 Jev 的 Agent 分层范式（2026-09 海外技术社区集中讨论的那套）：
**单体 agent → 生成层 + 一堆小决策器**。原话是这么说的：

    该不该调这个工具、这请求有没有风险、该用哪个模型、输出对不对，
    全塞进同一个上下文，让它自己想。这种范式在 demo 阶段无敌，
    上生产撞三堵墙：**慢、贵、说不清为什么**。

    判断要的是固定选项、可校准的概率、能调的阈值、能画的 ROC。
    生成模型给你的是一段「我觉得这个操作有风险，建议人工确认」，
    除了照办，无法量化。

这个项目本来就是分层的——`SafetyPolicy` / `TeachBackVerifier` /
`DelegationPolicy` / `TaskVerifier` / `DocumentGuard` / `PurposeBoundPolicy` /
`SyncConflictPolicy` / `SemanticGateway` 八个判断点各司其职。缺的不是"拆开"，
是判断层最值钱的那部分：

    grep -rniE "confidence|threshold|阈值|决策" backend/youhuo/  →  **零命中**
    `TeachBackVerifier.requires_teach_back(...)` 只回 True/False
    风险等级存在，但"多大把握才敢自动办"这根线写在 if/else 里，散着

所以这一层补三件事：**概率**、**集中的阈值**、**三态**。

## 照抄 Jev 的四条设计原则

1. **每个问题只问一件具体的事**——"相当于一个懂行的人看几秒钟就能拍板的判断"。
   要权衡多个因素的，拆开分别问，在代码里用公式合起来。
2. **confidence 不等于最高那个选项的概率**——它是从整个概率分布的形状算出来的，
   分布越平越低（见 `confidence_of`）。
3. **阈值不是一个数**——"同一个系统里不同动作该卡在不同水位"。
   钱卡最严，只查不付最松（见 `ROUTE_THRESHOLDS`）。
4. **三态**——高置信自动执行、中置信谨慎推进（让老人确认）、低置信不动手。
   "别让模型在没把握的时候硬猜，把不确定导给人。"

## 分工（Jev 官方那页"已知毛边"反过来给的划分）

    算术、计数、日期比较、格式校验  →  代码（本模块不做，交给调用方）
    语义判断                        →  本模块
    写东西、长推理                  →  生成模型（本模块不碰）

`deciders` 只回答选择题，一个字都不生成。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence

__all__ = [
    "Triage", "Choice", "Score", "Noul",
    "confidence_of", "ROUTE_THRESHOLDS", "route",
    "IntentDecider", "RiskDecider", "GraspDecider", "InterruptDecider",
    "DecisionChain", "decide_chain",
]


class Triage(StrEnum):
    """三态输出。照 Jev 落地三步的第三条。"""

    AUTO = "auto"        # 高置信 —— 直接办
    CONFIRM = "confirm"  # 中置信 —— 谨慎推进，让老人确认
    HANDOFF = "handoff"  # 低置信 —— 不动手，交给本人


def confidence_of(probabilities: Mapping[str, float]) -> float:
    """从**整个分布的形状**算置信度——不是取最高那个概率。

    Jev 文档特意点明这两者不是一回事：

        confidence 不等于最高那个选项的概率，它是从整个概率分布的形状
        算出来的，分布越平越低。

    差别在哪：`{A: 0.55, B: 0.45}` 和 `{A: 0.55, B: 0.05, C: 0.40}` 的
    最高概率一样（都 0.55），但前者是"两个都像"，后者是"一个像、另一个
    明显不像"——后者更该敢下手。只看 max 的话这两者分不开。

    这里用**归一化熵的补**：

        只有一个选项           → 1.0（没有不确定性可言）
        均匀铺在 n 个选项上     → 0.0（完全说不准）
        {A:0.9, B:0.1}         → ≈0.53
        {A:0.55, B:0.45}       → ≈0.007

    分布越平越低，符合 Jev 的描述。文档也说了"你不必用它的定义，
    完整概率都给你了，可以自己算"——这里就是自己算的那一种。
    """
    vals = [float(p) for p in probabilities.values() if float(p) > 0.0]
    if not vals:
        return 0.0
    if len(vals) == 1:
        return 1.0
    total = sum(vals)
    if total <= 0:
        return 0.0
    norm = [p / total for p in vals]
    entropy = -sum(p * math.log(p) for p in norm)
    max_entropy = math.log(len(norm))
    if max_entropy <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - entropy / max_entropy))


def _normalise(scores: Mapping[str, float]) -> dict[str, float]:
    """把任意打分归一化成概率。全 0 时退化成均匀分布（而不是除以零）。"""
    clean = {k: max(0.0, float(v)) for k, v in scores.items()}
    total = sum(clean.values())
    if total <= 0:
        n = len(clean) or 1
        return {k: 1.0 / n for k in clean}
    return {k: v / total for k, v in clean.items()}


@dataclass(frozen=True)
class Choice:
    """从列表里选一个。Jev 三种题型之一。"""

    question: str
    options: tuple[str, ...]
    probabilities: dict[str, float]
    choice: str
    confidence: float

    @classmethod
    def of(cls, question: str, scores: Mapping[str, float]) -> "Choice":
        probs = _normalise(scores)
        best = max(probs, key=lambda k: (probs[k], k))
        return cls(question=question, options=tuple(scores.keys()),
                   probabilities=probs, choice=best,
                   confidence=confidence_of(probs))


@dataclass(frozen=True)
class Score:
    """按有序的描述性等级打分。Jev 三种题型之一。"""

    question: str
    levels: tuple[str, ...]
    probabilities: dict[str, float]
    score: str
    value: float
    confidence: float

    @classmethod
    def of(cls, question: str, levels: Sequence[str],
           scores: Mapping[str, float]) -> "Score":
        probs = _normalise(scores)
        best = max(probs, key=lambda k: (probs[k], k))
        idx = list(levels).index(best) if best in levels else 0
        return cls(question=question, levels=tuple(levels),
                   probabilities=probs, score=best, value=float(idx),
                   confidence=confidence_of(probs))


@dataclass(frozen=True)
class Noul:
    """「这句话是真的吗」，返回 0~1 的一个数。Jev 三种题型之一。"""

    question: str
    value: float
    confidence: float

    @classmethod
    def of(cls, question: str, value: float,
           confidence: float | None = None) -> "Noul":
        v = max(0.0, min(1.0, float(value)))
        # 二值题的分布形状：越靠近 0 或 1 越确定
        c = confidence if confidence is not None else abs(v - 0.5) * 2.0
        return cls(question=question, value=v, confidence=max(0.0, min(1.0, c)))


#: 阈值表。**照 Jev 那条原则：阈值不是一个数，不同动作卡在不同水位。**
#:
#: 每一项是 `(auto 线, confirm 线)`：
#:   auto 线不为 None 且 confidence ≥ auto → 直接办
#:   confidence ≥ confirm                  → 先让老人确认
#:   否则                                  → 不动手，交给本人
#:
#: **`auto` 线写 `None` 表示这个动作根本没有自动档。** 这不是保守，是
#: Jev 官方那段示例的写法——它给的账户场景里，`approve_transfer`（转账）
#: 那支是这样的：
#:
#:     elif action.choice == "approve_transfer":
#:         if confidence > 0.9:
#:             confirm_then_execute(account_id)   # 高风险高把握，**确认后**执行
#:         else:
#:             ask_user_to_confirm(account_id)    # 高风险中等把握，先核实
#:
#: 注意高把握那一支走的是"确认后执行"，不是直接执行。**钱这一类动作，
#: 把握再大也要过一遍人。** 我第一版给 `pay_bill` 留了 0.95 的自动档，
#: 实测「帮我交一下这个月的电费」把握 1.00 就直接判成 `auto` 了——
#: 一个明确要花钱的操作被自动执行，而这正是这个产品最不该做的事
#: （`teach_back.py`："Money is the one place a wrong number cannot be
#: undone by talking"）。
#:
#: 水位是按"办错了多疼"定的：
#:   `pay_bill`  钱划走要不回来 → **无自动档**，最高到"确认后执行"
#:   `hospital`  订错了还能打电话改 → 有自动档，但线很高
#:   `reminder` / `form`  能撤回 → 中等
#:   `query`     只查不付，错了没有后果 → 最松
#:   `companion` 聊天，顶多说错一句话 → 最松
#:
#: **改优先级就改这张表里的一个数，不用去动任何一个决策器。**
ROUTE_THRESHOLDS: dict[str, tuple[float | None, float]] = {
    "pay_bill": (None, 0.70),
    "hospital": (0.90, 0.65),
    "form": (0.85, 0.55),
    "reminder": (0.80, 0.45),
    "query": (0.75, 0.40),
    "companion": (0.60, 0.30),
}


def route(confidence: float, action: str = "query") -> Triage:
    """把置信度按**这个动作的水位**路由成三态。

    没登记过的动作按最保守的 `pay_bill` 走——新加的动作忘了登记时，
    宁可多问一句，也不要默认放开。
    """
    auto_line, confirm_line = ROUTE_THRESHOLDS.get(action, ROUTE_THRESHOLDS["pay_bill"])
    if auto_line is not None and confidence >= auto_line:
        return Triage.AUTO
    if confidence >= confirm_line:
        return Triage.CONFIRM
    return Triage.HANDOFF


# ── 四个决策器：小优每次行动前各回答一个具体问题 ──────────────────────────
#
# 刻意**不合并成一个大判断**。Jev 那条原则是"要权衡多个因素的，拆开分别问，
# 在代码里用你自己的公式合起来"——合成公式在 `decide_chain` 里，一眼能看全。

#: 办正事的动作词。**只做字面命中，不做语义推断**——语义那部分交给
#: `StructuredIntentClient`（配了模型时），这里负责"没配模型也能跑"。
_ERRAND_WORDS = (
    "挂号", "挂个号", "看医生", "预约", "缴费", "交费", "水费", "电费",
    "燃气费", "话费", "提醒", "吃药", "填表", "报名", "办一下", "帮我办",
    "查一下", "查查", "交一下",
)

#: **明确**要找人说话的信号——出现就基本确定是聊天，不是办事。
_COMPANION_STRONG = ("找无忧伴", "聊聊天", "说说话", "陪我", "唠唠", "拉家常")

#: 情绪词——可能是想找人聊，也可能只是陈述心情。
#: 和强信号分开是因为它们**该给不同的分**：句子里出现"说说话"，
#: 那是在要人陪；只出现"心里烦"，那可能只是叹了口气。
_COMPANION_MOOD = (
    "闷", "孤单", "想你", "难受", "睡不着", "心里", "烦", "高兴", "开心", "无聊",
)

#: 说**身体不舒服**的信号词。
#:
#: 这一类单独成一个意图，不走办事流程、也不当"想聊两句"——
#: 它是这个产品最该接住的一句话。实测：加上这一条之前，
#: 「我有点不舒服」被判成"办正事 0.01 → handoff"，也就是"让她再说一遍"，
#: 而正确反应是关心她、并按紧急程度决定要不要现在告诉家人。
_URGENT_WORDS = (
    "不舒服", "头晕", "头疼", "疼", "痛", "摔", "跌倒", "胸闷",
    "喘不上", "恶心", "发烧", "起不来", "没力气", "心慌", "发晕", "眼前发黑",
)
#: 注意这里**没有"难受"**：它太含混——「心里难受」是情绪（归
#: `_COMPANION_MOOD`），不是身体不适。实测把它放进来之后，
#: 「…回来一个人待着，心里难受」被判成身体不适、绕过了情绪记录那条路。

#: **付款动作**词。判断"这件事要不要动钱"看的是动作，不是话题。
#:
#: 原先这里写的是"句子里有没有『元/块/钱』"，于是「水费**多少钱**」被判成
#: "钱划走要不回来"、走最严的那档。而它只是问一句价钱，一分钱都不动。
#: 实测抓到的。按 Jev 那条原则，风险决策器问的是"**要执行的动作**办错了
#: 多疼"——查询没有后果。
_PAY_ACTION_WORDS = (
    "缴费", "交费", "交一下", "帮我交", "帮我付", "付款", "转账", "划走",
    "去交", "把费交了", "缴一下", "付一下",
)

#: **不论句子长短**都算指代不明的说法——这些本身就是"没说清"，不可能是修饰语。
_VAGUE_STRONG = ("那个啥", "就那个", "什么来着", "那个东西", "那个谁")

#: **光杆**指代词：只在短句里才算说不清。
#:
#: 为什么要分强弱、为什么要看长度：`这个` / `那个` 在长句里绝大多数时候是
#: **修饰语**——「帮我交一下**这个**月的电费」「查一下**这个**月水费」。
#: 一开始把它们和"那个啥"混在一张表里、又只看"有没有出现"，实测两句都栽了：
#: 一个明确要缴费的句子落到意图 confidence 0.05、路由到 handoff。
#:
#: 现在：`这个` / `那个` 只在 6 字以内的短句里才算指代不明
#: （「那个」「就那个」算，而上面那两句 8 字以上、不算）。
_VAGUE_WEAK = ("那个", "这个", "什么")


def _too_short(compact: str) -> bool:
    """信息量本身不够，谈不上判断。"""
    return len(compact) <= 4


def _vague_ref(compact: str) -> bool:
    """是不是"她心里有指、话里没有"。**带长度条件**，理由见 `_VAGUE_WEAK`。"""
    if any(w in compact for w in _VAGUE_STRONG):
        return True
    return len(compact) <= 6 and any(w in compact for w in _VAGUE_WEAK)


class IntentDecider:
    """老人这句话是要**办正事**、**只想聊两句**、还是**说不清**？

    三个选项对应三条完全不同的路，所以它是链上的第一环——
    后面三个决策器问什么，取决于它选了什么。
    """

    QUESTION = "老人这句话想做什么？"
    #: 四个选项，`说自己不舒服` 单列——它既不是办事也不是闲聊，
    #: 走的是"关心 + 按紧急程度通知家人"那条路。
    OPTIONS = ("办正事", "只想聊两句", "说自己不舒服", "说不清")

    @classmethod
    def decide(cls, text: str, *, has_errand_slot: bool = False) -> Choice:
        raw = (text or "").strip()
        compact = raw.replace(" ", "")
        scores = {o: 0.0 for o in cls.OPTIONS}

        # **先算办事意图**：身体不适只在**没有办事意图时**才算。
        # 「我膝盖疼，帮我挂号」是在办事——她要的是挂号，不是被通知家人。
        # 实测：不收紧这一条，`test_chitchat_that_also_answers_is_still_an_answer`
        # 和 `test_chatting_about_being_lonely_records_a_mood` 两条当场红
        # （后者是"心里难受"被当成了身体不适，那句心里话没能记进情绪档案）。
        hits = [w for w in _ERRAND_WORDS if w in compact]
        if hits:
            # 命中越多越像办正事，但收益递减——命中 3 个和命中 1 个都是"办正事"
            scores["办正事"] = 0.55 + 0.15 * min(len(hits), 3)
        if has_errand_slot:
            # 任务已经在流程里（上一轮问过"哪一种账单"，这轮她答了），
            # 那就是在办事，不用再猜
            scores["办正事"] += 0.45

        u_hits = [w for w in _URGENT_WORDS if w in compact]
        if u_hits and not hits:
            scores["说自己不舒服"] = 0.60 + 0.15 * min(len(u_hits), 3)

        c_strong = [w for w in _COMPANION_STRONG if w in compact]
        c_mood = [w for w in _COMPANION_MOOD if w in compact]
        if c_strong:
            scores["只想聊两句"] = 0.75 + 0.10 * min(len(c_strong), 2)
        elif c_mood:
            scores["只想聊两句"] = 0.50 + 0.12 * min(len(c_mood), 3)
        c_hits = c_strong or c_mood

        # 「说不清」在两种情况下给分：句子太短、或指代不明。
        # 两个条件都带长度，理由见 `_VAGUE_WEAK` 上面那段——
        # 这是实测抓出来的两次误判换来的。
        if _too_short(compact) or _vague_ref(compact):
            scores["说不清"] = 0.5 + 0.1 * min(int(_too_short(compact)), 1)
        # 兜底：三类信号**一个都没命中**时才给"办正事"垫一点分。
        # `not u_hits` 是实测补上的——漏了它，「我有点不舒服」会在已经
        # 明确判成"说自己不舒服"之后又被垫上"办正事 0.30 + 说不清 0.25"，
        # 分布被摊平，意图 confidence 掉到 0.11。
        if not hits and not c_hits and not u_hits and len(compact) > 4:
            # 有话、但两类信号都没命中：仍偏"办正事"（老人开机就是为了办事），
            # 但分数压低，让 confidence 自己落到中低区，由阈值决定要不要问一句。
            #
            # **用 `+=` 不用 `=`**：上面"指代不明"可能已经给过"说不清"分了，
            # 赋值会把它盖掉。实测抓到的——「帮我弄那个」原本被盖成
            # 说不清 0.25 < 办正事 0.30，于是**选出了"办正事"**，
            # 而它明明是一句"她心里有指、话里没有"的话。
            scores["办正事"] += 0.30
            scores["说不清"] += 0.25

        return Choice.of(cls.QUESTION, scores)


class RiskDecider:
    """这件事办错了有多疼？四个等级，**顺序有意义**。

    等级直接沿用项目已有的 `risk_level`（`v6_models.py`：1~4）和
    `TaskType`，不另造一套——分层是为了把判断说清楚，不是为了多一层概念。
    """

    QUESTION = "这件事的后果等级？"
    LEVELS = ("没有后果", "能撤回", "有代价但能改", "钱划走要不回来")

    #: `TaskType` → 等级下标。挂号订错了还能打电话改，钱划走了不能——
    #: 这是 `teach_back.py` 里那条理由，这里沿用同一个划分。
    _BY_TASK = {
        "bill_payment": 3,
        "hospital_registration": 2,
        "form_assistance": 1,
        "reminder": 1,
    }

    @classmethod
    def decide(cls, *, task_type: str | None = None,
               risk_level: int | None = None,
               mentions_money: bool = False) -> Score:
        idx = cls._BY_TASK.get(str(task_type or ""), 0)
        # 项目自己的 risk_level（1~4）也认，取两者高的那个——
        # 宁可判重，不要判轻
        if risk_level:
            idx = max(idx, max(0, min(3, int(risk_level) - 1)))
        if mentions_money:
            idx = max(idx, 3)

        scores = {lv: 0.0 for lv in cls.LEVELS}
        scores[cls.LEVELS[idx]] = 0.85
        # 相邻档也分一点概率：等级判断本身就带模糊，"有代价"和"不可逆"
        # 之间不该是断崖。
        #
        # 权重是量出来的：给 0.15 时 confidence 只有 0.35，看起来像"系统对
        # 这件事的后果几乎没判断"——而实际上等级是确定的（`TaskType` 直接映射），
        # 模糊的只是**相邻档**。0.075 让 confidence 落在 0.5 上下，读起来
        # 与事实相符：主档很确定，边界上有点含糊。
        for nb in (idx - 1, idx + 1):
            if 0 <= nb < len(cls.LEVELS):
                scores[cls.LEVELS[nb]] += 0.075
        return Score.of(cls.QUESTION, cls.LEVELS, scores)


class GraspDecider:
    """我对**这次理解**有多确定？

    注意它和 `IntentDecider` 的 confidence 不是一回事：那个是"三个选项里
    我多倾向某一个"，这个是"综合输入质量之后，我敢不敢照这个理解往下走"。
    拆开是因为它们会分开用——意图很明确但话没听全（比如录音断了一半），
    前者高、后者低。
    """

    QUESTION = "我对这次理解有多确定？"

    @classmethod
    def decide(cls, text: str, intent: Choice,
               *, asr_confidence: float | None = None) -> Noul:
        raw = (text or "").strip()
        compact = raw.replace(" ", "")

        # 底：意图分布本身的把握
        base = intent.confidence

        # 输入长度：太短信息不够。3 字以下砍一刀
        if len(compact) < 3:
            base *= 0.5
        elif len(compact) < 6:
            base *= 0.8

        # 指代词：说明她心里有指、话里没有。同样走 `_vague_ref` 的强弱判断——
        # 长句里的"这个/那个"多半是修饰语（"这个月的电费"），不该打折。
        if _vague_ref(compact):
            base *= 0.6

        # 语音识别自己的把握（有就采信，没有就不猜）
        if asr_confidence is not None:
            base *= max(0.3, min(1.0, float(asr_confidence)))

        return Noul.of(cls.QUESTION, base)


class InterruptDecider:
    """要不要**打扰家人**？

    这一条是这个产品最在意的判断之一：老人端首页写着"今天不用一直盯着看"，
    而"打扰"是有代价的——打扰多了家人就不看了，真正要紧的那次也会被忽略。
    """

    QUESTION = "这件事要不要惊动家人？"
    OPTIONS = ("不打扰", "记下来就好", "现在就告诉家人")

    @classmethod
    def decide(cls, *, risk: Score, intent: Choice,
               elder_said_not_to: bool = False,
               urgent: bool = False) -> Choice:
        scores = {o: 0.0 for o in cls.OPTIONS}
        level = risk.value

        if urgent:
            scores["现在就告诉家人"] = 0.9
        elif level >= 3:
            # 钱的事：家人本来就要参与拍板
            scores["现在就告诉家人"] = 0.7
            scores["记下来就好"] = 0.2
        elif level == 2:
            scores["记下来就好"] = 0.6
            scores["现在就告诉家人"] = 0.2
        else:
            scores["不打扰"] = 0.8

        if intent.choice == "只想聊两句":
            # 陪伴聊天**不进家人日报**（这一页的承诺）。所以它的结论只有
            # "不打扰"——哪怕刚才风险算高了，也不能把聊天内容捅给家人
            scores = {o: 0.0 for o in cls.OPTIONS}
            scores["不打扰"] = 0.95

        if elder_said_not_to:
            # 她明确说了别告诉孩子 —— 除紧急外一律尊重
            if not urgent:
                scores = {o: 0.0 for o in cls.OPTIONS}
                scores["不打扰"] = 0.9

        return Choice.of(cls.QUESTION, scores)


@dataclass(frozen=True)
class DecisionChain:
    """一条链跑完的结果。四个决策器各自的答案 + 最终路由。"""

    intent: Choice
    risk: Score
    grasp: Noul
    interrupt: Choice
    action_key: str
    triage: Triage
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def headline(self) -> str:
        """一句话说清这次判断——给玻璃盒用。"""
        return (f"想做的事：{self.intent.choice}"
                f"（{self.intent.confidence:.2f}）｜"
                f"后果：{self.risk.score}"
                f"（{self.risk.confidence:.2f}）｜"
                f"把握：{self.grasp.value:.2f}｜"
                f"家人：{self.interrupt.choice}")


def _action_key(intent: Choice, risk: Score, task_type: str | None) -> str:
    """决定用哪一档水位。**这一步是代码，不是判断**——所以放在决策器外面。"""
    if intent.choice in ("只想聊两句", "说自己不舒服"):
        return "companion"   # 都不进办事流程，水位对它没有实际作用
    mapping = {
        "bill_payment": "pay_bill",
        "hospital_registration": "hospital",
        "form_assistance": "form",
        "reminder": "reminder",
    }
    if task_type and str(task_type) in mapping:
        return mapping[str(task_type)]
    if risk.value >= 3:
        return "pay_bill"      # 涉及钱的、又没登记过 → 按最严的走
    return "query"


def decide_chain(text: str, *, task_type: str | None = None,
                 risk_level: int | None = None,
                 has_errand_slot: bool = False,
                 asr_confidence: float | None = None,
                 elder_said_not_to: bool = False,
                 urgent: bool = False) -> DecisionChain:
    """跑完整条链：意图 → 风险 → 把握 → 打扰 → 路由。

    合成公式就在这儿，一眼能看全。要调优先级：改 `ROUTE_THRESHOLDS` 里的数，
    或者改这里的顺序——**不用去重写任何一个决策器**。
    """
    intent = IntentDecider.decide(text, has_errand_slot=has_errand_slot)
    # 「要不要动钱」看的是**付款动作**，不是句子里有没有"钱"字——
    # 「水费多少钱」是查询，「帮我交电费」才是付款。见 `_PAY_ACTION_WORDS`。
    risk = RiskDecider.decide(
        task_type=task_type, risk_level=risk_level,
        mentions_money=any(w in (text or "") for w in _PAY_ACTION_WORDS))
    grasp = GraspDecider.decide(text, intent, asr_confidence=asr_confidence)
    # 她说了身体不舒服 → 按紧急处理。**不用调用方再传一次 `urgent`**：
    # 那句话本身就是紧急信号，让它由文本自己决定，少一个"忘了传"的机会。
    urgent_final = urgent or intent.choice == "说自己不舒服"
    interrupt = InterruptDecider.decide(risk=risk, intent=intent,
                                        elder_said_not_to=elder_said_not_to,
                                        urgent=urgent_final)
    action = _action_key(intent, risk, task_type)

    notes: list[str] = []
    # 意图不明时**先问清楚再说别的**，不拿一个"说不清"的意图去往下走
    if intent.choice == "说不清":
        triage = Triage.HANDOFF
        notes.append("意图说不清 → 先问一句，不往下办")
    elif intent.choice == "说自己不舒服":
        # 身体不适不走办事流程，也不"让她再说一遍"——那是 handoff 的字面含义，
        # 但对这句话是错的反应。关心她，然后由 `InterruptDecider` 决定
        # 要不要现在就告诉家人。
        triage = Triage.HANDOFF
        notes.append("在说身体不舒服 → 走关怀路径，不办事、也不要求她重复")
    elif intent.choice == "只想聊两句":
        # 聊天不办事，路由对它没意义
        triage = Triage.AUTO
        notes.append("只是聊两句 → 不进办事流程")
    else:
        triage = route(grasp.value, action)
        if triage is Triage.CONFIRM:
            notes.append(f"把握 {grasp.value:.2f} 落在 {action} 的确认档 → 先跟老人核对")
        elif triage is Triage.HANDOFF:
            notes.append(f"把握 {grasp.value:.2f} 低于 {action} 的确认档 → 不动手")

    return DecisionChain(intent=intent, risk=risk, grasp=grasp,
                         interrupt=interrupt, action_key=action,
                         triage=triage, notes=tuple(notes))
