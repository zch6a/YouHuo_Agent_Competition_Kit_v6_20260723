"""个性化基线与生活日报的数据契约。

命名沿用项目既有约定：`StrictModel`（`extra="forbid"`），所有面向老人或子女的字符串
都是**已经可以直接念出来的话**，不是需要前端再拼装的字段——播报文案散落在前端，就
意味着 Web、鸿蒙和小艺三端各说各的。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .baseline import Channel, Verdict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 环境感知 ---------------------------------------------------------------


class EnvironmentSample(StrictModel):
    """一次室内环境读数。

    刻意**不含**任何图像。设计稿把这一点列为产品定位的一部分："看不见，但能感知"——
    家庭空间不是公共区域，长期视频监控会让老人产生心理压力，而这类产品最终被拔掉电源
    的原因往往就是这个。温湿度和光照足以支撑"今天是否正常"的判断。

    本项目**不附带任何传感器**。这是一个上报端点，由智能家居设备或鸿蒙分布式设备推送，
    与既有的 `/v4/location/ping` 是同一种关系。没有设备时日报照常工作，只是少一层环境
    联动——而不是假装读到了数据。
    """

    elder_id: str = Field(min_length=1, max_length=128)
    temperature_c: float | None = Field(default=None, ge=-40.0, le=60.0)
    humidity_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    lux: float | None = Field(default=None, ge=0.0, le=200000.0)
    occurred_at: datetime
    source: str = Field(default="unknown", min_length=1, max_length=64)

    @field_validator("occurred_at")
    @classmethod
    def within_a_sane_window(cls, value: datetime) -> datetime:
        """读数必须落在"最近 7 天到 5 分钟后"之间。

        温湿度光照三项都有 `ge/le`，唯独时间戳原来什么约束都没有，而它恰恰是三者里
        后果最重的一个：

        * `latest_environment` 按 `occurred_at DESC LIMIT 1` 取"此刻"，
        * `EnvironmentReader.read` 用 `now - occurred_at > FRESH` 判过期，未来时间戳
          的差是**负数**，永远通过新鲜度检查。

        两者叠加，一条 9999 年的读数会永久排在最前、永久"新鲜"，此后所有真实读数都
        再也顶不掉它。这不是理论攻击：`care.js` 上报用的是**客户端时钟**，演示机或
        鸿蒙设备时钟走快，就会把这户人家的环境读数钉死，而且不会自愈、日志里也看不
        出异常。

        顺带堵掉一个 500：`iso()` 会做 `astimezone(UTC)`，`0001-01-01T00:00:00+08:00`
        换算后落到 0000 年直接 OverflowError——而 +08:00 正是本项目的默认时区，
        不是刻意构造的极端值。Pydantic 拦不住它，因为**换算前**这个值是合法的。
        """
        now = datetime.now(UTC)
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        if moment > now + timedelta(minutes=5):
            raise ValueError("读数时间不能超过当前时间 5 分钟——请检查上报设备的时钟。")
        if moment < now - timedelta(days=7):
            raise ValueError("读数时间过旧（超过 7 天），不作为当前环境。")
        return value


class EnvironmentComfort(StrEnum):
    UNKNOWN = "unknown"
    COMFORTABLE = "comfortable"
    COLD = "cold"
    HOT = "hot"
    DRY = "dry"
    HUMID = "humid"
    DARK = "dark"


# --- 基线 -------------------------------------------------------------------


class ChannelBaselineView(StrictModel):
    channel: Channel
    label: str
    established: bool
    days: int
    #: 时刻类通道给 "06:00"，次数类通道给 "2 次"。给字符串而不是原始分钟数，是因为
    #: 三个端都要显示它，各自格式化就会各自格式化错。
    center_text: str | None
    reason: str


class ChannelDeviationView(StrictModel):
    channel: Channel
    label: str
    verdict: Verdict
    observed_text: str | None
    center_text: str | None
    #: 带符号：正 = 比常态晚 / 多。给子女看的是 `explanation`，这个字段留给端上排序。
    delta_minutes: float | None
    explanation: str


class BaselineSnapshot(StrictModel):
    """一位老人在某一天的"他自己的常态 vs 今天"。"""

    elder_id: str
    day: date
    overall: Verdict
    headline: str
    baselines: list[ChannelBaselineView]
    deviations: list[ChannelDeviationView]
    #: 观测窗口内的天数。少于阈值时全部通道都是 unknown，这里说明还差多少。
    observed_days: int
    established: bool


# --- 关怀动作（① 的"联动环境感知"部分）-------------------------------------


class LightCue(StrictModel):
    """给灯光设备的建议。

    **没有驱动任何灯**。本项目不附带智能家居设备，也不该假装能控制别人家的灯。这里
    输出的是一个建议状态，由已接入的设备去执行；`applied` 恒为 False，直到真的有设备
    回报执行结果。把"建议"和"已执行"分开，是这个项目一贯的做法——只有权威状态返回
    成功，才敢对老人说"办好了"。
    """

    brightness_pct: int = Field(ge=0, le=100)
    warm: bool
    breathing: bool
    reason: str
    applied: bool = False


class CareAction(StrictModel):
    """基于"他自己的常态 + 此刻的环境"生成的关怀动作。"""

    elder_id: str
    #: 直接播报给老人的话。已经是口语，不需要再加工。
    spoken: str
    #: 建议切换到的角色模式；偏离显著时主动切到无忧伴陪伴模式。
    suggest_mode: str | None = None
    #: 日程调整建议，例如把上午的复诊提醒往后挪。空列表表示不需要调整。
    schedule_hints: list[str] = Field(default_factory=list)
    light: LightCue | None = None
    #: 为什么是这个动作——面向子女和评委，也是审计里留痕的那一句。
    rationale: str
    environment_note: str | None = None


# --- 生活日报（②）----------------------------------------------------------


class ReportSection(StrictModel):
    title: str
    verdict: Verdict
    lines: list[str]


class ErrandDigest(StrictModel):
    """今天该办的事办得怎么样。日报里子女最先看的一块。"""

    due_today: int
    completed: int
    awaiting_family: int
    overdue: int
    lines: list[str]


class DailyReport(StrictModel):
    """给子女的生活日报（②）。

    设计稿的要求是"日报不再是单纯数据罗列，AI 基于基线对比，标注'今日作息偏离自身
    常态'，子女一眼识别老人异常"。所以结构是**结论在最前**：`headline` 一句话说完
    今天怎么样，`overall` 给颜色，后面才是分项。

    隐私边界与既有规则一致：**不包含无忧伴陪伴聊天的任何原文**。日报里出现的情绪信息
    只有类别和趋势。
    """

    elder_id: str
    day: date
    generated_at: datetime
    overall: Verdict
    headline: str
    #: 与常态对比的分项。
    sections: list[ReportSection]
    errands: ErrandDigest
    #: 需要子女做点什么的具体建议；空列表表示"今天不用您操心"。
    suggested_for_family: list[str]
    #: 明确写出这份日报**没有**包含什么，这是要给子女看的，不是注释。
    privacy_note: str
    environment_note: str | None = None


# --- 兜底预警（④）----------------------------------------------------------


class AlertDecision(StrictModel):
    """要不要现在就打扰子女。

    设计稿的要求："仅基线偏离 + 该办的事情临近预期才推送紧急提醒，大幅减少无效消息"。

    这条规则的价值不在于它推送了什么，而在于它**不推**什么。一个每天推三条"老人今天
    起晚了"的 App，两周内就会被子女静音，然后真正要紧的那一条也一起消失了。
    """

    push: bool
    channel: str        # "push" | "digest" | "none"
    reason: str
    #: 触发推送需要同时满足的两个条件，各自是否满足——写出来，便于解释和调试。
    baseline_deviated: bool
    errand_at_risk: bool
