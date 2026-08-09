"""个性化基线：拿这位老人**自己**的常态当尺子。

这是本项目的核心创新点，也是它和市面上养老设备的分界线。传统规则是统一的——
"超过 8 小时没有移动 = 异常"。可是老人 A 每天上午散步、老人 B 每天上午在家读书，
同一条规则对其中一位必然是错的：要么天天误报，要么调到永远不报。

所以这里不判断"老人是否发生危险"，而是判断"今天是否偏离**他自己**的常态"。

设计上有五个地方是刻意的，每一个都对应一种会让这套机制变成噪音源的失败：

1. **时间是圆的。** 22:50 和 00:10 的中位数是 23:30，不是 11:30。一个常在午夜前后
   就寝的老人，用线性统计会得到一个横跨白天的荒谬基线，然后每天都"偏离"。这里把
   时刻映射到单位圆上做统计。
2. **用中位数和 MAD，不用均值和标准差。** 一次住院、一次儿女来访就是一个极端值；
   均值会被它拽走，标准差会被它撑大到此后什么都测不出来。中位数和 MAD 对单个离群
   点免疫。
3. **离散度有下限。** 一位每天 6:00 准时起床的老人 MAD = 0，此后早一分钟都是无穷
   多个 sigma。给 MAD 一个下限（默认 25 分钟），规律的人才不会被自己的规律惩罚。
4. **样本不够就说不知道。** 少于 `MIN_DAYS` 天的数据不构成基线。这时 `established`
   为 False，不产出任何偏离结论——用三天数据宣称"偏离常态"，就是把统一规则换了个
   说法而已，正是这套机制要取代的东西。
5. **偏离不等于危险。** 输出的是 `deviation`（偏离程度）和面向老人的关怀动作，
   不是报警。报警要不要发，由兜底预警那一层结合"该办的事"另行决定。

全部是确定性纯函数，没有模型、没有随机数、没有时钟依赖（`today` 必须显式传入）。
理由和这个项目的其它部分一样：一个会对老人说"您今天不太对劲"的判断，必须能被逐步
复现和解释，而不是一个谁也说不清的分数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

# --- 可调参数。集中在这里，因为它们全都是"多敏感才算合适"的产品判断。---------

#: 少于这么多天的观测就不认为存在基线。
MIN_DAYS: int = 7

#: MAD 的下限（分钟）。规律的人不该被自己的规律惩罚。
MIN_SPREAD_MINUTES: float = 25.0

#: MAD 的**上限**（分钟）。超过它就不认为存在可比的常态。
#:
#: 这条不是调参，是修一个会让整套机制对目标人群失效的缺陷。时刻通道的偏差被
#: `_circular_delta` 钳在 ±720 以内，所以 `sigma = |delta| / spread <= 720 / spread`。
#: spread 一旦超过 720/3.5 ≈ 205.7，`MARKED` 在数学上就**永远不可能出现**；超过
#: 720/2.0 = 360，连 `NOTICE` 都不可能。而 `FallbackAlerting` 只在 MARKED 时推送。
#:
#: 也就是说：作息越乱的老人越测不出来，而节律紊乱恰恰是这个产品最该关注的人群。
#: 系统不会报错，只会每天安静地说"和平常差不多"。实测「住院两周后回家」这种再普通
#: 不过的历史（7 天 09:00 起 + 7 天 20:00 起）就足以让就寝通道永久失明。
#:
#: 取 120：MARKED 需要 3.5×120 = 7 小时的偏离——对一个 MAD 本就有两小时的人，
#: 七小时确实算异常。再大就该承认"他本来就没有常态"，而不是假装能比。
MAX_SPREAD_MINUTES: float = 120.0

#: 次数类通道的 MAD 下限（次）。
MIN_SPREAD_COUNT: float = 0.8

#: 偏离多少个"个人尺度"算轻度/显著。3.0 大致对应正态下的千分之三，
#: 但这里用的是 MAD 而不是标准差，所以它是一个稳健的经验阈值而非概率断言。
NOTICE_SIGMA: float = 2.0
MARKED_SIGMA: float = 3.5

#: 只保留最近这么多天参与基线计算——人的作息会随季节和身体状况漂移，
#: 半年前的规律不该继续当作今天的标准。
WINDOW_DAYS: int = 30


class Channel(StrEnum):
    """基线观察的几个通道。

    刻意只有这几个，而且都能从**已有**的事件流里算出来，不需要摄像头，也不需要
    老人多做任何事。"看不见，但能感知"落到工程上就是这个意思。
    """

    WAKE = "wake"                 # 当天第一次活动 —— 起床
    SLEEP = "sleep"               # 当天最后一次活动 —— 就寝
    OUTING = "outing"             # 离家次数
    MEDICATION = "medication"     # 服药时刻
    CONVERSATION = "conversation" # 与优活说话的次数


class Verdict(StrEnum):
    #: 还没到能下结论的时候：今天没过完，或者这个通道还没攒够历史。
    #: 这是**预期之内**的不知道，不该影响当天的总体结论。
    PENDING = "pending"
    #: 本该有记录却一条都没有。这不是"轻于正常"，是"不知道"，而在养老场景里
    #: "一整天没有任何活动记录"恰恰是最该被看见的一种情况。
    UNKNOWN = "unknown"
    TYPICAL = "typical"    # 符合他自己的常态
    NOTICE = "notice"      # 轻度偏离
    MARKED = "marked"      # 显著偏离


#: 时刻类通道用圆周统计，次数类通道用普通统计。
_TIME_CHANNELS = frozenset({Channel.WAKE, Channel.SLEEP, Channel.MEDICATION})


@dataclass(frozen=True)
class Observation:
    """某一天、某个通道的一个观测值。

    `minutes` 对时刻类通道是"当天 0 点起的分钟数"，对次数类通道是次数本身。
    """

    day: date
    channel: Channel
    value: float


@dataclass(frozen=True)
class ChannelBaseline:
    """一个通道上，这位老人自己的常态。"""

    channel: Channel
    established: bool
    days: int
    center: float       # 时刻类：0–1440 的分钟数；次数类：次数
    spread: float       # 已经过下限处理的 MAD
    reason: str         # 为什么 established 是这个值——面向人的说明

    def is_time(self) -> bool:
        return self.channel in _TIME_CHANNELS


@dataclass(frozen=True)
class ChannelDeviation:
    """今天在这个通道上偏离了多少。"""

    channel: Channel
    verdict: Verdict
    observed: float | None
    center: float | None
    delta_minutes: float | None   # 带符号：正 = 比常态晚 / 多
    sigma: float | None           # 偏离了几个"个人尺度"
    explanation: str              # 一句面向人的话，不是分数


# --- 圆周统计 ---------------------------------------------------------------


def _circular_median_minutes(values: list[float]) -> float:
    """一天之内时刻的中位数，按圆周计算。

    线性中位数在这里是错的：{23:50, 00:10} 的线性中位数是 12:00，正好落在这个人
    绝不可能起床的时刻上。做法是把每个候选点当作"圆心"，取使圆周绝对偏差之和最小
    的那个——即圆周意义上的 L1 中心，对离群点的稳健性和普通中位数一致。

    候选集就取观测值本身（中位数本来就落在样本点上），所以是精确解而不是搜索。
    """
    if not values:
        raise ValueError("空样本没有中位数")
    normalized = [float(value) % 1440.0 for value in values]
    if any(not math.isfinite(value) for value in normalized):
        raise ValueError("圆周中位数不能包含 NaN 或无穷值")

    costs: dict[float, float] = {}
    for candidate in set(normalized):
        costs[candidate] = sum(abs(_circular_delta(v, candidate)) for v in normalized)
    best_cost = min(costs.values())
    tied = [candidate for candidate, cost in costs.items() if abs(cost - best_cost) <= 1e-9]
    if len(tied) == 1:
        return tied[0]

    # Never break a circular tie by the absolute clock value (for example,
    # "pick the smaller HH:MM").  That changes the answer when every observation
    # is rotated by the same amount.  Instead compare each tied candidate only by
    # its signed relative deltas to the sample; those signatures are invariant to
    # a common rotation and independent of input order.
    signatures: dict[float, tuple[float, ...]] = {
        candidate: tuple(sorted(round(_circular_delta(v, candidate), 9) for v in normalized))
        for candidate in tied
    }
    best_signature = min(signatures.values())
    winners = [candidate for candidate, signature in signatures.items() if signature == best_signature]
    if len(winners) != 1:
        # A perfectly symmetric sample (for example two antipodal times) has no
        # mathematically well-defined single rotation-equivariant median.  Failing
        # closed is safer than inventing a clock-dependent answer.
        raise ValueError("圆周中位数存在不可消解的对称并列")
    return winners[0]


def _circular_delta(value: float, center: float) -> float:
    """value 相对 center 的带符号差，落在 (-720, 720]。

    正数表示"比常态晚"。跨午夜时这一点尤其重要：常态 23:30、今天 00:30，答案是
    +60 分钟（晚了一小时），不是 -1380 分钟（早了 23 小时）。
    """
    delta = (value - center) % 1440.0
    if delta > 720.0:
        delta -= 1440.0
    return delta


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mad(values: list[float], center: float, *, circular: bool) -> float:
    """中位绝对偏差。用它而不是标准差，是为了让一次住院不至于毁掉此后的基线。"""
    if circular:
        deviations = [abs(_circular_delta(v, center)) for v in values]
    else:
        deviations = [abs(v - center) for v in values]
    return _median(deviations)


# --- 基线 -------------------------------------------------------------------


def build_baseline(
    observations: list[Observation],
    channel: Channel,
    *,
    today: date,
    window_days: int = WINDOW_DAYS,
    min_days: int = MIN_DAYS,
) -> ChannelBaseline:
    """从这位老人自己的历史里算出一个通道的常态。

    `today` 必须显式传入：一个会对老人下结论的函数不能依赖挂钟，否则它的输出不可
    复现，测试也只能靠运气。
    """
    horizon = today - timedelta(days=window_days)
    circular = channel in _TIME_CHANNELS

    # One calendar day is one vote.  Counting raw rows lets duplicated observations
    # from a single day satisfy MIN_DAYS and lets that day dominate the median.
    # Invalid numeric rows invalidate only their own day; they are never allowed to
    # flow through comparisons where NaN would make every threshold test false.
    daily: dict[date, list[float]] = {}
    invalid_days: set[date] = set()
    for observation in observations:
        if observation.channel is not channel or not (horizon <= observation.day < today):
            continue
        value = float(observation.value)
        if not math.isfinite(value):
            invalid_days.add(observation.day)
            continue
        daily.setdefault(observation.day, []).append(value)
    for day in invalid_days:
        daily.pop(day, None)

    values: list[float] = []
    for day_values in daily.values():
        try:
            values.append(_circular_median_minutes(day_values) if circular else _median(day_values))
        except ValueError:
            # Contradictory/symmetric duplicates on one day do not get an
            # arbitrary representative and do not count toward MIN_DAYS.
            continue

    if len(values) < min_days:
        return ChannelBaseline(
            channel=channel,
            established=False,
            days=len(values),
            center=0.0,
            spread=0.0,
            reason=f"只有 {len(values)} 天的记录，不足 {min_days} 天，还不能说这是他的常态。",
        )

    try:
        center = _circular_median_minutes(values) if circular else _median(values)
    except ValueError:
        return ChannelBaseline(
            channel=channel,
            established=False,
            days=len(values),
            center=0.0,
            spread=0.0,
            reason="这些记录在圆周上完全对称，无法得到唯一且稳定的个人常态。",
        )
    raw = _mad(values, center, circular=circular)
    floor = MIN_SPREAD_MINUTES if circular else MIN_SPREAD_COUNT
    spread = max(raw, floor)

    if circular and raw > MAX_SPREAD_MINUTES:
        # 他本来就没有一个可比的常态。诚实说"不知道"，而不是给出一个
        # 数学上永远不会报警的基线——后者每天都会说"和平常差不多"。
        return ChannelBaseline(
            channel=channel,
            established=False,
            days=len(values),
            center=center,
            spread=spread,
            reason=(
                f"他这{len(values)}天的{_channel_word(channel)}时间本身就很不规律"
                f"（前后差{_duration(raw)}），暂时没有可比的常态。"
            ),
        )

    return ChannelBaseline(
        channel=channel,
        established=True,
        days=len(values),
        center=center,
        spread=spread,
        reason=f"基于最近 {len(values)} 天的记录。",
    )


def _channel_word(channel: Channel) -> str:
    return {
        Channel.WAKE: "起床",
        Channel.SLEEP: "就寝",
        Channel.MEDICATION: "服药",
        Channel.OUTING: "外出",
        Channel.CONVERSATION: "说话",
    }[channel]


def evaluate(
    baseline: ChannelBaseline,
    observed: float | None,
    *,
    label: str,
) -> ChannelDeviation:
    """今天这个通道偏离了多少。`label` 是给人看的通道名，例如"起床"。"""
    if not baseline.established:
        # 没有基线是**预期之内**的不知道：还没攒够，或者他本来就没有常态。
        # 用 PENDING，别让它把一个正常的日子说成"还不好说"。
        return ChannelDeviation(
            channel=baseline.channel,
            verdict=Verdict.PENDING,
            observed=observed,
            center=None,
            delta_minutes=None,
            sigma=None,
            explanation=f"{label}：{baseline.reason}",
        )
    if (
        not math.isfinite(float(baseline.center))
        or not math.isfinite(float(baseline.spread))
        or baseline.spread <= 0
    ):
        return ChannelDeviation(
            channel=baseline.channel,
            verdict=Verdict.UNKNOWN,
            observed=None,
            center=None,
            delta_minutes=None,
            sigma=None,
            explanation=f"{label}：个人基线数据无效，需要重新采集。",
        )
    if observed is None or not math.isfinite(float(observed)):
        # 有基线、也过了该有记录的时候，却没有一条有效数值——这是 UNKNOWN。
        # NaN 尤其不能继续往下走：NaN 的大小比较全部为 False，会把异常静默
        # 落进 TYPICAL 分支，形成 fail-open。
        return ChannelDeviation(
            channel=baseline.channel,
            verdict=Verdict.UNKNOWN,
            observed=None,
            center=baseline.center,
            delta_minutes=None,
            sigma=None,
            explanation=f"{label}：今天还没有有效记录。",
        )

    observed = float(observed)
    if baseline.is_time():
        delta = _circular_delta(observed, baseline.center)
    else:
        delta = observed - baseline.center
    sigma = abs(delta) / baseline.spread

    if sigma >= MARKED_SIGMA:
        verdict = Verdict.MARKED
    elif sigma >= NOTICE_SIGMA:
        verdict = Verdict.NOTICE
    else:
        verdict = Verdict.TYPICAL

    return ChannelDeviation(
        channel=baseline.channel,
        verdict=verdict,
        observed=observed,
        center=baseline.center,
        delta_minutes=delta,
        sigma=sigma,
        explanation=_describe(baseline, label, delta, verdict),
    )


def _describe(baseline: ChannelBaseline, label: str, delta: float, verdict: Verdict) -> str:
    """用这位老人自己的单位说话，不是用分数。

    "偏离 3.2 个标准差"对子女没有意义。"比他平常晚了一小时四十分"才有——它同时
    告诉对方发生了什么、以及这算不算多。
    """
    if verdict is Verdict.TYPICAL:
        if baseline.is_time():
            return f"{label}：和平常差不多（{_clock(baseline.center)} 前后）。"
        return f"{label}：和平常差不多。"

    if baseline.is_time():
        direction = "晚" if delta > 0 else "早"
        return (
            f"{label}：比他平常{direction}了{_duration(abs(delta))}"
            f"（平常{_clock(baseline.center)}前后）。"
        )
    direction = "多" if delta > 0 else "少"
    return f"{label}：比他平常{direction}了 {abs(delta):.0f} 次（平常 {baseline.center:.0f} 次）。"


def _clock(minutes: float) -> str:
    total = int(round(minutes)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def _duration(minutes: float) -> str:
    total = int(round(minutes))
    if total < 60:
        return f"{total} 分钟"
    hours, rest = divmod(total, 60)
    return f"{hours} 小时" if rest == 0 else f"{hours} 小时 {rest} 分钟"


def minutes_of_day(moment: datetime) -> float:
    """把一个时间点折成"当天 0 点起的分钟数"。"""
    return moment.hour * 60.0 + moment.minute + moment.second / 60.0


def overall_verdict(deviations: list[ChannelDeviation]) -> Verdict:
    """把各通道汇总成一句话的结论。

    取最严重的那一个，而不是求平均：三个通道正常、一个通道显著偏离，重要的是那
    一个。平均会把它稀释成"大致正常"，而那正是子女最需要看见的一天。

    **`UNKNOWN` 排在 `TYPICAL` 之上**，这一条是被一个具体场景换来的：老人整天零
    活动、零位置、零对话，只有护工代记了一次服药——四个通道 UNKNOWN、一个 TYPICAL，
    而原来的顺序让那一个 TYPICAL 赢了，日报头条写"今天和他平常差不多"。
    "不知道"不是"比正常轻"；在养老场景里，"一整天没有任何记录"正是最该被看见的
    那一天。

    `PENDING` 则相反，排在最后：今天没过完、或某个通道还没攒够历史，都是预期之内的，
    不该把一个正常的早晨说成"还不好说"。
    """
    for level in (Verdict.MARKED, Verdict.NOTICE, Verdict.UNKNOWN, Verdict.TYPICAL):
        if any(d.verdict is level for d in deviations):
            return level
    return Verdict.PENDING
