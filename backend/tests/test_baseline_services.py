"""基线服务层：关怀语、生活日报与兜底预警。

`test_baseline.py` 管数学，这里管**说出口的话和推送的决定**。两者的失败方式完全不同：
数学错了结论是错的，这一层错了则是结论对、但产品变成了一个没人再看的通知源，或者
一个会让老人开始隐瞒的评判者。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from youhuo.baseline import Channel, Observation, Verdict
from youhuo.baseline_models import EnvironmentComfort, EnvironmentSample
from youhuo.baseline_services import (
    BaselineAnalyzer,
    CareComposer,
    DailyReportBuilder,
    EnvironmentReader,
    ErrandFacts,
    FallbackAlerting,
)

TODAY = date(2026, 8, 9)
NOW = datetime(2026, 8, 9, 10, 0)


def at(hhmm: str) -> float:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def history(**channels: list[float]) -> list[Observation]:
    out: list[Observation] = []
    for name, values in channels.items():
        channel = Channel(name)
        for i, value in enumerate(values):
            out.append(Observation(day=TODAY - timedelta(days=len(values) - i),
                                   channel=channel, value=value))
    return out


REGULAR = history(
    wake=[at("06:00")] * 14,
    sleep=[at("21:30")] * 14,
    outing=[2.0] * 14,
    medication=[at("08:00")] * 14,
    conversation=[6.0] * 14,
)

TODAY_NORMAL = {
    Channel.WAKE: at("06:10"), Channel.SLEEP: at("21:35"),
    Channel.OUTING: 2.0, Channel.MEDICATION: at("08:05"), Channel.CONVERSATION: 6.0,
}
TODAY_LATE = dict(TODAY_NORMAL, **{Channel.WAKE: at("10:30")})


def snap(today_values: dict, observations: list[Observation] = REGULAR):
    return BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=observations,
        today_values=today_values, today=TODAY,
    )


def env(**kw) -> EnvironmentSample:
    return EnvironmentSample(elder_id="elder-demo", occurred_at=NOW, source="test", **kw)


def read(sample: EnvironmentSample | None):
    return EnvironmentReader.read(sample, now=NOW)


# --- 环境读数 ---------------------------------------------------------------


def test_no_sensor_is_unknown_not_comfortable():
    """把"没有传感器"当成"一切都好"，是这类产品最常见也最危险的偷懒。"""
    reading = read(None)
    assert reading.comforts == (EnvironmentComfort.UNKNOWN,)
    assert reading.note is None


def test_a_stale_sample_is_not_treated_as_now():
    old = EnvironmentSample(elder_id="e", occurred_at=NOW - timedelta(hours=5), source="t",
                            temperature_c=12.0)
    reading = EnvironmentReader.read(old, now=NOW)
    assert reading.comforts == (EnvironmentComfort.UNKNOWN,)
    assert reading.note and "过期" in reading.note


@pytest.mark.parametrize("kwargs,expected", [
    ({"temperature_c": 14.0}, EnvironmentComfort.COLD),
    ({"temperature_c": 33.0}, EnvironmentComfort.HOT),
    ({"humidity_pct": 20.0}, EnvironmentComfort.DRY),
    ({"humidity_pct": 85.0}, EnvironmentComfort.HUMID),
    ({"lux": 10.0}, EnvironmentComfort.DARK),
    ({"temperature_c": 22.0, "humidity_pct": 50.0, "lux": 300.0}, EnvironmentComfort.COMFORTABLE),
])
def test_comfort_classification(kwargs, expected):
    assert expected in read(env(**kwargs)).comforts


# --- ① 关怀语：同样的偏离，不同的环境，不同的话 -----------------------------


def test_same_deviation_different_environment_different_words():
    """这就是"联动环境感知"的全部意思：偏离一样，但屋里冷和屋里正常要说不同的话。"""
    warm = CareComposer.compose(snapshot=snap(TODAY_LATE),
                                environment=read(env(temperature_c=22.0)), now=NOW)
    cold = CareComposer.compose(snapshot=snap(TODAY_LATE),
                                environment=read(env(temperature_c=13.0)), now=NOW)
    assert warm.spoken != cold.spoken
    assert "加件衣服" in cold.spoken
    assert "加件衣服" not in warm.spoken
    assert "13" in cold.spoken


def test_late_wake_suggests_moving_the_morning_along():
    action = CareComposer.compose(snapshot=snap(TODAY_LATE), environment=read(None), now=NOW)
    assert action.schedule_hints, "起得晚却没有任何日程建议"
    assert any("往后" in h for h in action.schedule_hints)


def test_care_words_state_rather_than_judge():
    """说"您今天起得比平常晚"是陈述，说"您今天不正常"是评判。

    对一位独居老人，后者说多了就会让他开始隐瞒——而隐瞒正是这套系统最怕的东西。
    """
    action = CareComposer.compose(snapshot=snap(TODAY_LATE),
                                  environment=read(env(temperature_c=13.0)), now=NOW)
    for word in ("异常", "不正常", "警告", "危险", "偏离"):
        assert word not in action.spoken, f"对老人说的话里出现了「{word}」：{action.spoken}"


def test_nothing_wrong_says_so_plainly():
    action = CareComposer.compose(snapshot=snap(TODAY_NORMAL),
                                  environment=read(env(temperature_c=22.0, lux=300.0)), now=NOW)
    assert "和平常一样" in action.spoken
    assert action.suggest_mode is None
    assert action.schedule_hints == []


def test_before_a_baseline_exists_it_says_so_and_does_nothing():
    thin = history(wake=[at("06:00")] * 3)
    action = CareComposer.compose(snapshot=snap({Channel.WAKE: at("13:00")}, thin),
                                  environment=read(None), now=NOW)
    assert "熟悉" in action.spoken
    assert action.suggest_mode is None
    assert action.light is None


# --- ③ 灯光与模式 -----------------------------------------------------------


def test_marked_deviation_switches_to_companion_and_soft_light():
    """显著偏离时老人需要的是有人说话，不是一个办事菜单。"""
    action = CareComposer.compose(snapshot=snap(TODAY_LATE), environment=read(None), now=NOW)
    assert action.suggest_mode == "companion"
    assert action.light is not None
    assert action.light.warm and action.light.breathing
    assert action.light.brightness_pct < 100


def test_a_light_cue_is_a_suggestion_not_a_claim():
    """本项目不附带智能家居设备，也不该假装能控制别人家的灯。"""
    action = CareComposer.compose(snapshot=snap(TODAY_LATE), environment=read(None), now=NOW)
    assert action.light is not None and action.light.applied is False


def test_a_dark_room_alone_raises_brightness_without_hijacking_the_mode():
    action = CareComposer.compose(snapshot=snap(TODAY_NORMAL),
                                  environment=read(env(lux=5.0)), now=NOW)
    assert action.light is not None and action.light.brightness_pct >= 70
    assert action.suggest_mode is None, "只是屋里暗，不该把老人拽进陪伴模式"


# --- ② 生活日报 -------------------------------------------------------------


def test_the_report_leads_with_a_conclusion_not_a_table():
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_LATE), errands=ErrandFacts(),
        environment=read(None), generated_at=NOW,
    )
    assert report.headline
    assert "平常" in report.headline, "结论必须是和他自己比，而不是一个绝对值"


def test_every_line_carries_his_own_normal():
    """"昨晚 23:40 就寝"是数据；"比他平常晚了两小时"才是子女能据以行动的信息。"""
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_LATE), errands=ErrandFacts(),
        environment=read(None), generated_at=NOW,
    )
    rhythm = next(s for s in report.sections if s.title == "作息")
    assert any("平常" in line for line in rhythm.lines), rhythm.lines


def test_the_report_never_contains_companion_chat():
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_NORMAL), errands=ErrandFacts(),
        environment=read(None), generated_at=NOW,
    )
    assert "陪伴聊天" in report.privacy_note and "不包含" in report.privacy_note


def test_a_quiet_day_suggests_nothing_rather_than_padding():
    """一份每天都有待办的日报，等于没有日报。"""
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_NORMAL), errands=ErrandFacts(due_today=1, completed=1),
        environment=read(None), generated_at=NOW,
    )
    assert report.suggested_for_family == []
    assert report.overall is Verdict.TYPICAL


def test_a_bad_day_gets_concrete_suggestions():
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_LATE),
        errands=ErrandFacts(due_today=2, awaiting_family=1, overdue=1),
        environment=read(None), generated_at=NOW,
    )
    joined = " ".join(report.suggested_for_family)
    assert "确认" in joined and "超期" in joined
    assert any("聊两句" in s for s in report.suggested_for_family)


def test_section_verdict_reflects_its_own_channels():
    report = DailyReportBuilder.build(
        snapshot=snap(TODAY_LATE), errands=ErrandFacts(),
        environment=read(None), generated_at=NOW,
    )
    rhythm = next(s for s in report.sections if s.title == "作息")
    meds = next(s for s in report.sections if s.title == "用药")
    assert rhythm.verdict is Verdict.MARKED
    assert meds.verdict is Verdict.TYPICAL, "用药正常却被作息带成了异常"


# --- ④ 兜底预警：重点是它**不推**什么 ---------------------------------------


def test_deviation_alone_does_not_interrupt_the_family():
    decision = FallbackAlerting.decide(snapshot=snap(TODAY_LATE), errands=ErrandFacts())
    assert decision.push is False
    assert decision.channel == "digest"
    assert decision.baseline_deviated and not decision.errand_at_risk


def test_a_due_errand_alone_does_not_interrupt_the_family():
    decision = FallbackAlerting.decide(snapshot=snap(TODAY_NORMAL),
                                       errands=ErrandFacts(overdue=1))
    assert decision.push is False
    assert decision.errand_at_risk and not decision.baseline_deviated


def test_both_together_is_the_shape_worth_interrupting_for():
    decision = FallbackAlerting.decide(snapshot=snap(TODAY_LATE),
                                       errands=ErrandFacts(overdue=1))
    assert decision.push is True and decision.channel == "push"
    assert decision.baseline_deviated and decision.errand_at_risk


def test_a_normal_day_notifies_nobody():
    decision = FallbackAlerting.decide(snapshot=snap(TODAY_NORMAL), errands=ErrandFacts())
    assert decision.push is False and decision.channel == "none"


def test_an_emergency_bypasses_the_whole_rule():
    """兜底预警是给"渐变"用的，不是给 SOS 用的。"""
    decision = FallbackAlerting.decide(snapshot=snap(TODAY_NORMAL),
                                       errands=ErrandFacts(), emergency=True)
    assert decision.push is True and decision.channel == "push"


def test_the_reason_is_always_stated():
    for values, errands in ((TODAY_NORMAL, ErrandFacts()), (TODAY_LATE, ErrandFacts(overdue=1))):
        decision = FallbackAlerting.decide(snapshot=snap(values), errands=errands)
        assert decision.reason, "每一个推送/不推送的决定都必须能解释"


# --- 还没过完的一天不许当成过完了 -------------------------------------------


def test_no_bedtime_verdict_before_bedtime():
    """上午十点打开日报，看到"就寝：比他平常晚了 8 小时 35 分钟"。

    这是真实截图里出现过的一句话。当天最后一条活动记录是早上六点起床，系统把它
    当成了就寝时刻，而 06:05 相对 21:30 在圆周上确实"晚了 8 小时 35 分"。算术没错，
    错在一天还没过完就下结论。一份会这样说话的日报，子女第三天就会关掉通知。
    """
    morning = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.WAKE: at("06:05"), Channel.SLEEP: at("06:05")},
        today=TODAY, now_minutes=at("10:00"),
    )
    sleep = next(d for d in morning.deviations if d.channel is Channel.SLEEP)
    assert sleep.verdict is Verdict.UNKNOWN, sleep.explanation
    assert "还没过完" in sleep.explanation
    assert morning.overall is not Verdict.MARKED


@pytest.mark.parametrize("hour", ["06:00", "09:30", "12:00", "15:00", "18:00", "21:00"])
def test_no_bedtime_verdict_at_any_hour_before_bedtime(hour):
    """整个白天都不许对"昨晚睡得怎么样"下结论。

    09:30 这一格是真实踩过的：平常 21:30 就寝，此时圆周差恰好 720 分钟，落在
    "是否已过就寝时间"这个单阈值判断的边界外侧，于是给出"晚睡了 8 小时 35 分"。
    单个阈值在对跖点必然出错，所以判断条件是一个窗口。
    """
    snapshot = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.SLEEP: at("06:05")}, today=TODAY, now_minutes=at(hour),
    )
    sleep = next(d for d in snapshot.deviations if d.channel is Channel.SLEEP)
    assert sleep.verdict is Verdict.UNKNOWN, f"{hour}: {sleep.explanation}"


def test_bedtime_is_judged_once_it_is_genuinely_late():
    late_night = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.SLEEP: at("00:40")},
        today=TODAY, now_minutes=at("00:45"),
    )
    sleep = next(d for d in late_night.deviations if d.channel is Channel.SLEEP)
    assert sleep.verdict is Verdict.MARKED, sleep.explanation
    assert "晚" in sleep.explanation


def test_counts_are_not_judged_low_before_the_day_is_over():
    """早上九点出门 0 次不是异常，只是天还早。"""
    morning = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.OUTING: 0.0}, today=TODAY, now_minutes=at("09:00"),
    )
    outing = next(d for d in morning.deviations if d.channel is Channel.OUTING)
    assert outing.verdict is Verdict.UNKNOWN, outing.explanation


def test_counts_are_judged_low_once_the_day_is_over():
    evening = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.OUTING: 0.0}, today=TODAY, now_minutes=at("21:00"),
    )
    outing = next(d for d in evening.deviations if d.channel is Channel.OUTING)
    assert outing.verdict in (Verdict.NOTICE, Verdict.MARKED), outing.explanation


def test_an_unusually_high_count_is_flagged_at_any_hour():
    """"比平常少"要等一天过完；"比平常多"任何时候都已经成立。"""
    morning = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.OUTING: 9.0}, today=TODAY, now_minutes=at("09:00"),
    )
    outing = next(d for d in morning.deviations if d.channel is Channel.OUTING)
    assert outing.verdict is Verdict.MARKED, outing.explanation


def test_a_past_day_is_always_judged_in_full():
    """回看昨天时那一天已经完整，不该再压制任何通道。"""
    yesterday = BaselineAnalyzer.snapshot(
        elder_id="elder-demo", observations=REGULAR,
        today_values={Channel.OUTING: 0.0}, today=TODAY, now_minutes=None,
    )
    outing = next(d for d in yesterday.deviations if d.channel is Channel.OUTING)
    assert outing.verdict in (Verdict.NOTICE, Verdict.MARKED)


# --- 千人千面，端到端 -------------------------------------------------------


def test_two_elders_same_day_get_different_care():
    """设计稿的核心主张：同一天、同样的行为，两位老人得到不同的结论。"""
    walker = history(outing=[2.0] * 14)
    reader = history(outing=[0.0] * 14)
    today = {Channel.OUTING: 0.0}

    walker_action = CareComposer.compose(snapshot=snap(today, walker),
                                         environment=read(None), now=NOW)
    reader_action = CareComposer.compose(snapshot=snap(today, reader),
                                         environment=read(None), now=NOW)

    assert "出门" in walker_action.spoken, "常散步的老人一天没出门，该问一句"
    assert "和平常一样" in reader_action.spoken, "常在家读书的老人不出门是他的常态"
