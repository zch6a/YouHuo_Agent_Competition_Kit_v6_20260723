"""个性化基线的服务层：把"他自己的常态"变成关怀、日报和预警。

分成四块，对应设计稿的四个核心创新点：

* `BaselineAnalyzer`  ① 基线本身（数学在 `baseline.py`，这里负责组装成快照）
* `EnvironmentReader` ① 的"联动环境感知"——温湿度/光照，无摄像头
* `CareComposer`      ①③ 结合基线与环境生成语音安抚、日程调整、灯光建议
* `DailyReportBuilder`② 生活日报
* `FallbackAlerting`  ④ 兜底预警：只在"偏离 + 事情临期"同时成立时才打扰子女

全部确定性。`now` / `today` 一律显式传入，不读挂钟——一个会让子女放下工作赶回家的
判断，必须能在测试里逐字节复现。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .baseline import (
    Channel,
    ChannelBaseline,
    ChannelDeviation,
    Observation,
    Verdict,
    build_baseline,
    evaluate,
    minutes_of_day,
    overall_verdict,
)
from .baseline_models import (
    AlertDecision,
    BaselineSnapshot,
    CareAction,
    ChannelBaselineView,
    ChannelDeviationView,
    DailyReport,
    EnvironmentComfort,
    EnvironmentSample,
    ErrandDigest,
    LightCue,
    ReportSection,
)

#: 通道的中文名。集中一处，日报、关怀语和端上显示共用同一套说法。
CHANNEL_LABELS: dict[Channel, str] = {
    Channel.WAKE: "起床",
    Channel.SLEEP: "就寝",
    Channel.OUTING: "外出",
    Channel.MEDICATION: "服药",
    Channel.CONVERSATION: "说话",
}

#: 舒适区间。取自居室热舒适的常规建议，并对老年人偏冷敏感做了收紧：
#: 老年人体温调节能力下降，18°C 对年轻人只是"有点凉"，对独居老人是失温风险的起点。
COLD_C = 18.0
HOT_C = 30.0
DRY_PCT = 30.0
HUMID_PCT = 70.0
#: 室内照度低于此值，正常活动（读报、走动）已经吃力。
DARK_LUX = 50.0


def _clock(minutes: float) -> str:
    total = int(round(minutes)) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


# --- ① 基线快照 -------------------------------------------------------------


class BaselineAnalyzer:
    """把原始观测组装成"他自己的常态 vs 今天"。"""

    CHANNELS: tuple[Channel, ...] = (
        Channel.WAKE,
        Channel.SLEEP,
        Channel.OUTING,
        Channel.MEDICATION,
        Channel.CONVERSATION,
    )

    #: 计数类通道在这个本地时刻之前不下"比平常少"的结论——一天还没过完，
    #: 出门次数当然还没攒够。20:00 之后才算这一天基本定型。
    COUNT_CUTOFF_MINUTES: float = 20 * 60

    #: 就寝判断的时间窗：晚于平常就寝时间 45 分钟才开始判断，超过 6 小时就不再判断。
    #:
    #: 需要一个**窗口**而不是单个阈值。只写"是否已过就寝时间"会在对跖点出问题：
    #: 平常 21:30 就寝，早上 09:30 时"距就寝已过 720 分钟"，用 `> 720` 判断恰好落在
    #: 边界外侧，于是第二天早上会得出"昨晚晚睡了 8 小时 35 分"——那条活动记录其实
    #: 是今天早上的起床。上界把这种情况排除掉：过了六小时，看到的就是新的一天了。
    SLEEP_GRACE_MINUTES: float = 45.0
    SLEEP_WINDOW_MINUTES: float = 6 * 60

    @classmethod
    def snapshot(
        cls,
        *,
        elder_id: str,
        observations: list[Observation],
        today_values: dict[Channel, float | None],
        today: date,
        now_minutes: float | None = None,
    ) -> BaselineSnapshot:
        """
        `now_minutes` 是"此刻是本地时间几点"（0–1440）。给了它，尚未过完的一天就不会
        被当成已经过完的一天来评判。

        这不是锦上添花。缺了它，上午十点打开日报会看到"就寝：比他平常晚了 8 小时
        35 分钟"——因为当天最后一条活动记录是早上六点起床，而系统把它当成了就寝
        时刻。一份会这样说话的日报，子女会在第三天关掉通知。
        """
        baselines: list[ChannelBaselineView] = []
        deviations: list[ChannelDeviationView] = []
        raw_deviations: list[ChannelDeviation] = []

        for channel in cls.CHANNELS:
            label = CHANNEL_LABELS[channel]
            baseline = build_baseline(observations, channel, today=today)
            observed = today_values.get(channel)
            if now_minutes is not None and baseline.established:
                observed = cls._withhold_if_premature(
                    channel, observed, baseline.center, now_minutes
                )
            deviation = evaluate(baseline, observed, label=label)
            if observed is None and today_values.get(channel) is not None:
                # 数据是有的，只是这一天还没走到能下结论的时候——这是 PENDING，
                # 不是 UNKNOWN。区分这两者，日报才能既不在上午虚报"还不好说"，
                # 又不会把"整天一条记录都没有"说成"和平常差不多"。
                deviation = ChannelDeviation(
                    channel=channel, verdict=Verdict.PENDING, observed=None,
                    center=baseline.center, delta_minutes=None, sigma=None,
                    explanation=f"{label}：今天还没过完，现在下结论太早。",
                )
            raw_deviations.append(deviation)

            baselines.append(ChannelBaselineView(
                channel=channel,
                label=label,
                established=baseline.established,
                days=baseline.days,
                center_text=cls._format(channel, baseline.center) if baseline.established else None,
                reason=baseline.reason,
            ))
            deviations.append(ChannelDeviationView(
                channel=channel,
                label=label,
                verdict=deviation.verdict,
                observed_text=cls._format(channel, deviation.observed) if deviation.observed is not None else None,
                center_text=cls._format(channel, deviation.center) if deviation.center is not None else None,
                delta_minutes=deviation.delta_minutes,
                explanation=deviation.explanation,
            ))

        overall = overall_verdict(raw_deviations)
        observed_days = len({o.day for o in observations if o.day < today})
        established = any(b.established for b in baselines)
        return BaselineSnapshot(
            elder_id=elder_id,
            day=today,
            overall=overall,
            headline=cls._headline(overall, raw_deviations, established, observed_days),
            baselines=baselines,
            deviations=deviations,
            observed_days=observed_days,
            established=established,
        )

    @classmethod
    def _withhold_if_premature(
        cls, channel: Channel, observed: float | None, center: float, now_minutes: float
    ) -> float | None:
        """一天还没过完时，哪些结论不能下。

        每一条都对应一种如果不做就会出现的假警报：

        * **就寝**：还没到平常的就寝时间，最后一条活动记录只是"目前为止最后一次"，
          不是就寝。这正是上午十点出现"晚了 8 小时"的原因。
        * **外出 / 说话**：一天没过完，次数当然还没攒够。"比平常少"要等到晚上再说；
          "比平常多"任何时候都成立，所以只压制偏少的那一侧。
        """
        if observed is None:
            return None
        if channel is Channel.SLEEP:
            # 用圆周差算"距平常就寝时间过了多久"，跨午夜的人才不会被误判。
            elapsed = (now_minutes - center) % 1440.0
            if not (cls.SLEEP_GRACE_MINUTES <= elapsed <= cls.SLEEP_WINDOW_MINUTES):
                return None
            return observed
        if channel in (Channel.OUTING, Channel.CONVERSATION):
            if now_minutes < cls.COUNT_CUTOFF_MINUTES and observed < center:
                return None
            return observed
        return observed

    @staticmethod
    def _format(channel: Channel, value: float | None) -> str | None:
        if value is None:
            return None
        if channel in (Channel.WAKE, Channel.SLEEP, Channel.MEDICATION):
            return _clock(value)
        return f"{value:.0f} 次"

    @staticmethod
    def _headline(
        overall: Verdict,
        deviations: list[ChannelDeviation],
        established: bool,
        observed_days: int,
    ) -> str:
        if not established:
            return (
                f"还在熟悉他的生活规律（已记录 {observed_days} 天）。"
                "在攒够之前，不会拿别人的标准来评价他。"
            )
        if overall is Verdict.PENDING:
            return "今天还没过完，还不到下结论的时候。"
        if overall is Verdict.UNKNOWN:
            # 这句话现在有分量了：本该有记录却一条都没有。
            missing = [d.explanation for d in deviations if d.verdict is Verdict.UNKNOWN]
            lead = f"（{missing[0]}）" if missing else ""
            return f"今天该有的记录还没出现{lead}，建议打个电话问一声。"
        if overall is Verdict.TYPICAL:
            return "今天和他平常差不多。"
        worst = [d for d in deviations if d.verdict in (Verdict.MARKED, Verdict.NOTICE)]
        worst.sort(key=lambda d: -(d.sigma or 0.0))
        lead = worst[0].explanation if worst else ""
        prefix = "今天和他平常不太一样" if overall is Verdict.MARKED else "今天有一点和平常不同"
        return f"{prefix}：{lead}"


# --- ① 环境感知 -------------------------------------------------------------


@dataclass(frozen=True)
class EnvironmentReading:
    sample: EnvironmentSample | None
    comforts: tuple[EnvironmentComfort, ...]
    note: str | None


class EnvironmentReader:
    """把一条环境读数变成几个可判断的状态。

    没有读数时返回 UNKNOWN 而不是"舒适"——把"没有传感器"当成"一切都好"，正是这类
    产品最常见也最危险的偷懒。
    """

    #: 超过这么久的读数不再代表"此刻"。
    FRESH = timedelta(hours=2)

    @classmethod
    def read(cls, sample: EnvironmentSample | None, *, now: datetime) -> EnvironmentReading:
        if sample is None:
            return EnvironmentReading(None, (EnvironmentComfort.UNKNOWN,), None)
        # 用**绝对值**。带符号的差让未来时间戳得到一个负数，于是永远"新鲜"——
        # 一条 9999 年的读数会永久盖住所有真实读数。时间戳偏离此刻太远，无论朝哪个
        # 方向，都不能代表"现在屋里什么样"。
        if abs(now - sample.occurred_at) > cls.FRESH:
            return EnvironmentReading(
                sample,
                (EnvironmentComfort.UNKNOWN,),
                "室内环境数据已经过期，这次没有参考它。",
            )

        comforts: list[EnvironmentComfort] = []
        parts: list[str] = []
        if sample.temperature_c is not None:
            parts.append(f"{sample.temperature_c:.0f}℃")
            if sample.temperature_c < COLD_C:
                comforts.append(EnvironmentComfort.COLD)
            elif sample.temperature_c > HOT_C:
                comforts.append(EnvironmentComfort.HOT)
        if sample.humidity_pct is not None:
            parts.append(f"湿度 {sample.humidity_pct:.0f}%")
            if sample.humidity_pct < DRY_PCT:
                comforts.append(EnvironmentComfort.DRY)
            elif sample.humidity_pct > HUMID_PCT:
                comforts.append(EnvironmentComfort.HUMID)
        if sample.lux is not None and sample.lux < DARK_LUX:
            comforts.append(EnvironmentComfort.DARK)

        if not comforts:
            comforts.append(EnvironmentComfort.COMFORTABLE)
        note = "屋里" + "、".join(parts) + "。" if parts else None
        return EnvironmentReading(sample, tuple(comforts), note)


# --- ①③ 关怀动作 -----------------------------------------------------------


class CareComposer:
    """结合"他自己的常态"和"此刻的环境"，生成一句该说的话。

    这里是①"定制适配他作息的语音安抚、日程调整"和③"联动双色双模式灯光"的落点。

    有一条规则贯穿始终：**偏离不是指控**。说"您今天起得比平常晚"是陈述，说"您今天
    不正常"是评判；对一位独居老人，后者说多了就会让他开始隐瞒。所有措辞都按前者写。
    """

    @classmethod
    def compose(
        cls,
        *,
        snapshot: BaselineSnapshot,
        environment: EnvironmentReading,
        now: datetime,
    ) -> CareAction:
        marked = [d for d in snapshot.deviations if d.verdict is Verdict.MARKED]
        notice = [d for d in snapshot.deviations if d.verdict is Verdict.NOTICE]
        comforts = set(environment.comforts)

        spoken: list[str] = []
        hints: list[str] = []
        rationale: list[str] = []

        if not snapshot.established:
            spoken.append("我还在慢慢熟悉您的作息，这几天先不打扰您。")
            rationale.append("基线尚未建立，不做任何偏离判断。")
            return CareAction(
                elder_id=snapshot.elder_id,
                spoken="".join(spoken),
                rationale="".join(rationale),
                environment_note=environment.note,
            )

        # --- 作息偏离对应的话与日程建议 ---
        for deviation in marked + notice:
            if deviation.channel is Channel.WAKE and (deviation.delta_minutes or 0) > 0:
                spoken.append("今天起得比平常晚一些，不着急，慢慢来。")
                hints.append("上午的事项可以往后挪一挪，不用赶。")
                rationale.append(f"起床晚于常态（{deviation.explanation}）。")
            elif deviation.channel is Channel.SLEEP and (deviation.delta_minutes or 0) > 0:
                spoken.append("昨晚睡得比平常晚，白天想睡就眯一会儿。")
                rationale.append(f"就寝晚于常态（{deviation.explanation}）。")
            elif deviation.channel is Channel.OUTING and (deviation.delta_minutes or 0) < 0:
                spoken.append("今天还没怎么出门，要是身上不舒服，跟我说一声。")
                rationale.append(f"外出少于常态（{deviation.explanation}）。")
            elif deviation.channel is Channel.MEDICATION:
                spoken.append("今天的药和平常的时间不太一样，需要我提醒您吗？")
                hints.append("确认今天的服药时间是否需要调整。")
                rationale.append(f"服药时间偏离常态（{deviation.explanation}）。")
            elif deviation.channel is Channel.CONVERSATION and (deviation.delta_minutes or 0) < 0:
                spoken.append("今天您话比平常少，我在这儿陪着您。")
                rationale.append(f"交流少于常态（{deviation.explanation}）。")

        # --- 环境联动：同样的偏离，屋里冷和屋里暗要说不同的话 ---
        if EnvironmentComfort.COLD in comforts:
            temp = environment.sample.temperature_c if environment.sample else None
            spoken.append(f"屋里有点凉（{temp:.0f}℃），先加件衣服吧。" if temp is not None else "屋里有点凉，先加件衣服吧。")
            rationale.append("室温低于 18℃，老年人体温调节能力下降，偏冷是失温风险的起点。")
        elif EnvironmentComfort.HOT in comforts:
            spoken.append("屋里有点热，记得喝口水。")
            rationale.append("室温高于 30℃。")
        if EnvironmentComfort.DRY in comforts:
            spoken.append("屋里比较干，多喝点水。")
            rationale.append("湿度低于 30%。")
        if EnvironmentComfort.DARK in comforts:
            spoken.append("屋里有点暗，我把灯调亮一点好吗？")
            rationale.append("照度低于 50 lux，正常读报走动已经吃力。")

        # --- ③ 灯光与模式 ---
        light: LightCue | None = None
        suggest_mode: str | None = None
        if marked:
            # 显著偏离时主动切到陪伴模式：这时老人需要的是有人说话，不是一个办事菜单。
            suggest_mode = "companion"
            light = LightCue(
                brightness_pct=45,
                warm=True,
                breathing=True,
                reason="作息显著偏离常态，切到暖光慢呼吸，配合无忧伴陪伴模式主动安抚。",
            )
            rationale.append("显著偏离，建议切换陪伴模式。")
        elif EnvironmentComfort.DARK in comforts:
            light = LightCue(
                brightness_pct=70,
                warm=True,
                breathing=False,
                reason="室内照度过低，建议提高亮度。",
            )

        if not spoken:
            spoken.append("今天一切都和平常一样，您安心。")
            rationale.append("各通道均在个人常态范围内。")

        return CareAction(
            elder_id=snapshot.elder_id,
            spoken="".join(spoken),
            suggest_mode=suggest_mode,
            schedule_hints=hints,
            light=light,
            rationale="".join(rationale),
            environment_note=environment.note,
        )


# --- ② 生活日报 -------------------------------------------------------------


@dataclass(frozen=True)
class ErrandFacts:
    """日报需要的办事事实。由调用方从既有任务/提醒表里取，这里不碰数据库。"""

    due_today: int = 0
    completed: int = 0
    awaiting_family: int = 0
    overdue: int = 0
    #: 具体条目，已经是可读的一句话。
    lines: tuple[str, ...] = ()


class DailyReportBuilder:
    """生活日报（②）。

    设计稿的原话是"日报不再是单纯数据罗列"。所以这里做的两件事是：**先给结论**，
    以及**每一项都带上他自己的常态**。"昨晚 23:40 就寝"是数据；"比他平常晚了两小时"
    才是子女能据以行动的信息。
    """

    PRIVACY_NOTE = "本日报不包含无忧伴陪伴聊天的任何原文，只有类别与趋势。"

    @classmethod
    def build(
        cls,
        *,
        snapshot: BaselineSnapshot,
        errands: ErrandFacts,
        environment: EnvironmentReading,
        generated_at: datetime,
    ) -> DailyReport:
        sections: list[ReportSection] = []

        rhythm_lines = [d.explanation for d in snapshot.deviations
                        if d.channel in (Channel.WAKE, Channel.SLEEP)]
        activity_lines = [d.explanation for d in snapshot.deviations
                          if d.channel in (Channel.OUTING, Channel.CONVERSATION)]
        health_lines = [d.explanation for d in snapshot.deviations
                        if d.channel is Channel.MEDICATION]

        for title, channels, lines in (
            ("作息", (Channel.WAKE, Channel.SLEEP), rhythm_lines),
            ("活动与交流", (Channel.OUTING, Channel.CONVERSATION), activity_lines),
            ("用药", (Channel.MEDICATION,), health_lines),
        ):
            relevant = [d.verdict for d in snapshot.deviations if d.channel in channels]
            sections.append(ReportSection(
                title=title,
                verdict=cls._worst(relevant),
                lines=lines,
            ))

        suggestions = cls._suggestions(snapshot, errands)
        return DailyReport(
            elder_id=snapshot.elder_id,
            day=snapshot.day,
            generated_at=generated_at,
            overall=snapshot.overall,
            headline=snapshot.headline,
            sections=sections,
            errands=ErrandDigest(
                due_today=errands.due_today,
                completed=errands.completed,
                awaiting_family=errands.awaiting_family,
                overdue=errands.overdue,
                lines=list(errands.lines),
            ),
            suggested_for_family=suggestions,
            privacy_note=cls.PRIVACY_NOTE,
            environment_note=environment.note,
        )

    @staticmethod
    def _worst(verdicts: Iterable[Verdict]) -> Verdict:
        # 与 overall_verdict 同一套顺序：UNKNOWN 高于 TYPICAL，PENDING 最低。
        values = list(verdicts)
        for level in (Verdict.MARKED, Verdict.NOTICE, Verdict.UNKNOWN, Verdict.TYPICAL):
            if level in values:
                return level
        return Verdict.PENDING

    @staticmethod
    def _suggestions(snapshot: BaselineSnapshot, errands: ErrandFacts) -> list[str]:
        """具体到"您可以做什么"，而不是"请注意"。

        空列表是一个有意义的结果：明确告诉子女今天不用操心，比硬凑一条建议更可信。
        一份每天都有待办的日报，等于没有日报。
        """
        out: list[str] = []
        if errands.awaiting_family:
            out.append(f"有 {errands.awaiting_family} 项在等您确认，其中包含支付或身份环节。")
        if errands.overdue:
            out.append(f"有 {errands.overdue} 项已经超期，建议直接打个电话问一声。")
        if snapshot.overall is Verdict.MARKED:
            out.append("今天作息和他平常差得比较多，方便的话晚上跟他聊两句。")
        return out


# --- ④ 兜底预警 -------------------------------------------------------------


class FallbackAlerting:
    """要不要现在就打扰子女。

    规则是**两个条件同时成立**才推送：基线偏离（显著），并且有该办的事临期或超期。

    单独的偏离不推——起晚一次不需要惊动谁；单独的临期也不推——那是提醒老人的事，
    走既有的 T-24/T-12/T-1 阶梯。两者同时出现才是真正需要子女兜底的形状：他今天状态
    不对，而且有件事要误。

    这条规则的价值在于它**不推**什么。一个每天推三条"老人今天起晚了"的 App，两周内
    就会被子女静音，然后真正要紧的那一条也一起消失了。
    """

    @staticmethod
    def decide(
        *,
        snapshot: BaselineSnapshot,
        errands: ErrandFacts,
        emergency: bool = False,
    ) -> AlertDecision:
        # 紧急事件永远直达，不受这条规则约束——兜底预警是给"渐变"用的，
        # 不是给 SOS 用的。SOS 走既有的即时通道。
        if emergency:
            return AlertDecision(
                push=True, channel="push",
                reason="紧急事件立即通知，不经过基线判断。",
                baseline_deviated=snapshot.overall is Verdict.MARKED,
                errand_at_risk=True,
            )

        deviated = snapshot.overall is Verdict.MARKED
        at_risk = errands.overdue > 0 or errands.awaiting_family > 0

        if deviated and at_risk:
            return AlertDecision(
                push=True, channel="push",
                reason="他今天状态和平常差得比较多，而且有事情要误了——这两件同时发生才值得打扰您。",
                baseline_deviated=True, errand_at_risk=True,
            )
        if deviated:
            return AlertDecision(
                push=False, channel="digest",
                reason="只是作息和平常不同，没有事情要误；放进今天的日报，不单独打扰。",
                baseline_deviated=True, errand_at_risk=False,
            )
        if at_risk:
            return AlertDecision(
                push=False, channel="digest",
                reason="有事情临期，但他今天状态和平常一样；先按既有提醒阶梯提醒他本人。",
                baseline_deviated=False, errand_at_risk=True,
            )
        return AlertDecision(
            push=False, channel="none",
            reason="今天一切照常，不需要通知。",
            baseline_deviated=False, errand_at_risk=False,
        )
