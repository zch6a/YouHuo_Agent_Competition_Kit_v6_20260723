"""个性化基线：这套机制的数学必须先站得住。

这是核心创新点。它会对子女说"您父亲今天偏离了常态"——一句会让人放下工作赶回家的
话。所以这里测的不是"函数跑通了"，而是那些一旦错了就会让这句话变成谎言的性质：

* 时间是圆的（跨午夜的人不能天天误报）；
* 一次住院不能毁掉此后的基线，也不能让此后什么都测不出来；
* 极端规律的人不能被自己的规律惩罚；
* 数据不够就必须说不知道，而不是猜。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from youhuo.baseline import (
    MARKED_SIGMA,
    MIN_DAYS,
    MIN_SPREAD_MINUTES,
    Channel,
    Observation,
    Verdict,
    _circular_delta,
    _circular_median_minutes,
    build_baseline,
    evaluate,
    minutes_of_day,
    overall_verdict,
)

TODAY = date(2026, 8, 9)


def obs(channel: Channel, values: list[float], *, end: date = TODAY) -> list[Observation]:
    """把一串值铺到 end 之前的连续若干天上。"""
    return [
        Observation(day=end - timedelta(days=len(values) - i), channel=channel, value=v)
        for i, v in enumerate(values)
    ]


def at(hhmm: str) -> float:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


# --- 时间是圆的 -------------------------------------------------------------


def test_midnight_median_does_not_land_at_noon():
    """{23:50, 00:10} 的线性中位数是 12:00 —— 正好落在这个人绝不可能起床的时刻。"""
    values = [at("23:50"), at("00:10"), at("23:55"), at("00:05"), at("00:00")]
    median = _circular_median_minutes(values)
    assert abs(_circular_delta(median, at("00:00"))) <= 10, (
        f"跨午夜的中位数落到了 {median / 60:.1f} 点"
    )


@pytest.mark.parametrize(
    "value,center,expected",
    [
        (at("00:30"), at("23:30"), 60.0),    # 晚一小时，不是早 23 小时
        (at("23:30"), at("00:30"), -60.0),   # 早一小时
        (at("08:00"), at("07:00"), 60.0),
        (at("12:00"), at("00:00"), 720.0),   # 边界：正好半天
    ],
)
def test_circular_delta_takes_the_short_way_round(value, center, expected):
    assert _circular_delta(value, center) == pytest.approx(expected)


def test_a_night_owl_is_not_permanently_abnormal():
    """常在午夜前后就寝的人，用线性统计会天天"偏离"。"""
    history = obs(Channel.SLEEP, [at("23:40"), at("00:10"), at("23:50"), at("00:20"),
                                  at("23:55"), at("00:05"), at("23:45"), at("00:15")])
    baseline = build_baseline(history, Channel.SLEEP, today=TODAY)
    assert baseline.established
    today_value = at("00:00")
    result = evaluate(baseline, today_value, label="就寝")
    assert result.verdict is Verdict.TYPICAL, result.explanation


# --- 稳健性 -----------------------------------------------------------------


def test_one_hospital_day_does_not_move_the_baseline():
    """均值会被一个极端值拽走；中位数不会。"""
    normal = [at("06:00")] * 9
    baseline_before = build_baseline(obs(Channel.WAKE, normal), Channel.WAKE, today=TODAY)
    with_outlier = build_baseline(
        obs(Channel.WAKE, normal + [at("14:00")]), Channel.WAKE, today=TODAY
    )
    assert abs(with_outlier.center - baseline_before.center) <= 1.0, (
        "一次 14:00 起床把常态拽走了；这正是均值不能用的原因"
    )


def test_one_hospital_day_does_not_blind_the_detector():
    """标准差会被极端值撑大，此后什么都测不出来。MAD 不会。"""
    normal = [at("06:00") + (i % 3) * 5 for i in range(12)]
    baseline = build_baseline(
        obs(Channel.WAKE, normal + [at("14:00")]), Channel.WAKE, today=TODAY
    )
    # 离群点之后，一个真正晚起的日子仍然必须被抓到。
    result = evaluate(baseline, at("10:00"), label="起床")
    assert result.verdict is Verdict.MARKED, (
        f"离群点撑大了尺度，10:00 起床已经测不出来了：{result.explanation}"
    )


def test_a_perfectly_regular_person_is_not_punished_for_it():
    """每天 6:00 准点起床的人 MAD = 0，此后早一分钟都是无穷个 sigma。"""
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    assert baseline.spread >= MIN_SPREAD_MINUTES
    result = evaluate(baseline, at("06:20"), label="起床")
    assert result.verdict is Verdict.TYPICAL, (
        f"晚起 20 分钟就报异常，这种系统一周之内就会被子女静音：{result.explanation}"
    )
    assert result.sigma is not None and result.sigma < 1.0


# --- 数据不够就说不知道 -----------------------------------------------------


def test_a_short_history_yields_no_verdict():
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * (MIN_DAYS - 1)),
                              Channel.WAKE, today=TODAY)
    assert not baseline.established
    result = evaluate(baseline, at("14:00"), label="起床")
    assert result.verdict is Verdict.UNKNOWN, (
        "用不到一周的数据宣称偏离，就是把统一规则换了个说法"
    )
    assert result.sigma is None
    assert str(MIN_DAYS) in result.explanation


def test_no_observation_today_is_unknown_not_typical():
    """没有记录不等于一切正常——这个区别在养老场景里是性命攸关的。"""
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    result = evaluate(baseline, None, label="起床")
    assert result.verdict is Verdict.UNKNOWN
    assert result.verdict is not Verdict.TYPICAL


def test_today_is_excluded_from_its_own_baseline():
    """否则异常越大，标准被拉得越多，异常越测不出来。"""
    history = obs(Channel.WAKE, [at("06:00")] * 14)
    today_obs = Observation(day=TODAY, channel=Channel.WAKE, value=at("13:00"))
    baseline = build_baseline(history + [today_obs], Channel.WAKE, today=TODAY)
    assert abs(baseline.center - at("06:00")) < 1.0
    assert evaluate(baseline, at("13:00"), label="起床").verdict is Verdict.MARKED


# --- 千人千面：同一天，两位老人，两种结论 -----------------------------------


def test_two_elders_same_day_opposite_verdicts():
    """设计稿里的那个例子：老人 A 上午散步，老人 B 上午在家读书。

    统一规则对其中一位必然是错的。这条测试就是这个创新点本身。
    """
    walker = build_baseline(obs(Channel.OUTING, [2, 2, 3, 2, 2, 3, 2, 2, 2, 3]),
                            Channel.OUTING, today=TODAY)
    reader = build_baseline(obs(Channel.OUTING, [0, 0, 0, 1, 0, 0, 0, 0, 1, 0]),
                            Channel.OUTING, today=TODAY)

    # 今天两个人都出门 0 次。
    assert evaluate(reader, 0, label="外出").verdict is Verdict.TYPICAL, "读书的老人闭门不出是常态"
    assert evaluate(walker, 0, label="外出").verdict is not Verdict.TYPICAL, (
        "散步的老人一次没出门，才是值得注意的事"
    )


# --- 说人话 -----------------------------------------------------------------


def test_the_explanation_is_in_the_elders_own_units():
    """"偏离 3.2 个标准差"对子女没有意义。"""
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    result = evaluate(baseline, at("09:40"), label="起床")
    assert "sigma" not in result.explanation.lower()
    assert "标准差" not in result.explanation
    assert "3 小时 40 分钟" in result.explanation, result.explanation
    assert "晚" in result.explanation
    assert "06:00" in result.explanation


def test_direction_is_stated_not_just_magnitude():
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    assert "早" in evaluate(baseline, at("02:00"), label="起床").explanation
    assert "晚" in evaluate(baseline, at("10:00"), label="起床").explanation


# --- 汇总 -------------------------------------------------------------------


def test_the_worst_channel_wins_rather_than_the_average():
    """三个通道正常、一个显著偏离，重要的是那一个。"""
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    typical = [evaluate(baseline, at("06:05"), label="起床") for _ in range(3)]
    marked = evaluate(baseline, at("13:00"), label="起床")
    assert overall_verdict(typical + [marked]) is Verdict.MARKED


def test_all_unknown_stays_unknown():
    empty = build_baseline([], Channel.WAKE, today=TODAY)
    assert overall_verdict([evaluate(empty, None, label="起床")]) is Verdict.UNKNOWN


# --- 阈值本身 ---------------------------------------------------------------


def test_marked_needs_a_real_departure():
    """阈值不能低到把日常波动也算上——那样日报就没人看了。"""
    baseline = build_baseline(obs(Channel.WAKE, [at("06:00")] * 14), Channel.WAKE, today=TODAY)
    assert baseline.spread == MIN_SPREAD_MINUTES
    just_under = baseline.spread * MARKED_SIGMA - 5
    assert evaluate(baseline, at("06:00") + just_under, label="起床").verdict is not Verdict.MARKED
    assert evaluate(baseline, at("06:00") + baseline.spread * MARKED_SIGMA + 5,
                    label="起床").verdict is Verdict.MARKED


def test_minutes_of_day_round_trips():
    assert minutes_of_day(datetime(2026, 8, 9, 6, 30)) == 390.0
    assert minutes_of_day(datetime(2026, 8, 9, 0, 0)) == 0.0
    assert minutes_of_day(datetime(2026, 8, 9, 23, 59)) == 1439.0


def test_baseline_is_order_independent():
    """同一批数据换个顺序必须得到同一个基线，否则结论不可复现。"""
    values = [at("06:00"), at("06:30"), at("05:30"), at("07:00"), at("06:15"),
              at("05:45"), at("06:45"), at("06:10")]
    first = build_baseline(obs(Channel.WAKE, values), Channel.WAKE, today=TODAY)
    second = build_baseline(obs(Channel.WAKE, list(reversed(values))), Channel.WAKE, today=TODAY)
    assert first.center == second.center
    assert first.spread == second.spread
