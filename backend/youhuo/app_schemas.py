"""`/api/v1` 的响应模型。

## 为什么单独有这个文件

这一层的 25 个端点原先全部返回 `dict[str, Any]`。FastAPI 拿这个注解生成出来的
OpenAPI 是：

    {"additionalProperties": true, "type": "object", "title": "Response Profile …"}

**有名字，零字段。** 对照老接口那一批：171 个模型，字段清清楚楚，
而其中属于 `/api/v1` 的**一个都没有**。也就是说，任何人想按 OpenAPI
生成一个客户端（新前端、鸿蒙端、第三方），拿到的是 25 个 `object`。

契约只活在两个地方：这一层的源码，和我写的那些测试。源码不是给外面看的，
测试也不会被工具消费。所以补上模型——**它同时是文档和校验**：
FastAPI 会拿它过滤和校验真实响应，字段名写错、少给一个键，
在测试里就是一条红，而不是等前端拿到 `undefined` 才发现。

## 一条刻意的选择：`extra="forbid"`

项目里 `StrictModel` 是 `extra="forbid"`。这里**继续用它**，因为这一层最常见的
错误就是「后端偷偷多给/少给一个字段，前端悄悄读到 undefined」。
多给会当场报错，比静默通过好。

## 命名

统一 `App` 前缀，和老接口那 171 个模型区分开——它们同名不同义的风险是真的
（比如两边都会想叫 `Bill`）。
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .models import StrictModel


# ---- 档案 / 设置 -----------------------------------------------------------

class AppProfile(StrictModel):
    name: str
    #: 「优活已陪伴您 N 天」。取自这个家庭最早那条审计的时间；一条都没有时为 null。
    days: int | None = None
    #: 下面三个后端确实没有数据源。**保留字段并回 null**，而不是删掉：
    #: 删掉的话前端读到 `undefined`，和「后端给了 null」在 JS 里长得一样，
    #: 但含义完全不同——一个是「这个概念不存在」，一个是「有这个概念，今天没有值」。
    weather: str | None = None
    air: str | None = None
    comfort: str | None = None


class AppSettings(StrictModel):
    #: 服务端夹在 0.9–1.6。前端**必须**以返回值为准，不能假设传什么就是什么。
    fontScale: float
    voiceSpeed: float
    highContrast: bool
    #: 这位老人有没有存过自己的偏好。false = 现在显示的是默认值。
    saved: bool
    message: str | None = None


# ---- 账单 ------------------------------------------------------------------

class AppBill(StrictModel):
    id: str
    type: str
    #: 给人看的金额字符串（两位小数，不带货币符号）。
    amount: str
    #: 给算术用的分。两个都给，是因为前端拿 `amount` 做减法一定会出错。
    amountCents: int
    company: str | None = None
    month: str
    period: str
    dueDate: str | None = None
    paid: bool
    #: 中文。界面上不出现英文枚举值，所以翻译在这一层完成。
    status: str
    paidAt: str | None = None


class AppBillList(StrictModel):
    items: list[AppBill]
    count: int
    unpaidCount: int
    unpaidTotal: str


class AppWaterBill(StrictModel):
    """老端点 `/bills/water/current` 的形状。

    和 `AppBill` **不一样**，而且不能合并：这个形状是前端先定稿、后端跟着补的，
    它有 `accountTail` 而没有 `paid`/`period`。合并会让那一页当场读不到字段。
    """
    id: str
    type: str
    amount: str
    company: str
    accountTail: str
    month: str
    paidAt: str | None = None


# ---- 提醒 / 日程 -----------------------------------------------------------

class AppReminder(StrictModel):
    id: str
    title: str
    #: 用药 / 就医 / 健康 / 其他。从标题认出来的——`reminders` 表没有类型字段。
    kind: str
    time: str
    date: str
    at: str
    done: bool
    cancelled: bool
    status: str
    overdue: bool


class AppReminderList(StrictModel):
    items: list[AppReminder]
    count: int
    kinds: list[str]


class AppReminderCreated(StrictModel):
    ok: bool
    item: AppReminder
    message: str


class AppReminderChanged(StrictModel):
    ok: bool
    id: str
    status: str
    message: str


class AppAgendaNext(StrictModel):
    time: str
    title: str
    #: 后端没有地点字段。回 null，界面上宁可不显示地点，也不编一个医院。
    place: str | None = None
    note: str | None = None
    overdue: bool


class AppAgendaItem(StrictModel):
    id: str
    time: str
    title: str
    done: bool
    status: str
    at: str


class AppAgenda(StrictModel):
    next: AppAgendaNext | None = None
    today: list[AppAgendaItem]
    count: int


# ---- 就医安排 --------------------------------------------------------------

class AppAppointment(StrictModel):
    id: str
    hospital: str
    department: str | None = None
    doctor: str | None = None
    date: str
    time: str
    status: str


class AppAppointmentList(StrictModel):
    items: list[AppAppointment]
    count: int


class AppAppointmentCreated(StrictModel):
    ok: bool
    id: str
    #: 建安排时顺带建的那条到点提醒。建不出来时为 null——安排本身仍然算成功。
    reminderId: str | None = None
    message: str


# ---- 联系人 / 通知 ---------------------------------------------------------

class AppContact(StrictModel):
    id: str
    name: str
    role: str
    #: `actors` 表没有电话这一列。**永远是 null**，不许编一个号码——
    #: 老人真按下去会拨错人。
    phone: str | None = None
    primary: bool


class AppContactList(StrictModel):
    items: list[AppContact]
    count: int


class AppNotification(StrictModel):
    #: `notifications` 表的主键是自增整数，不是字符串 id。照实写。
    id: int | None = None
    #: 通知正文。库里那一列叫 `message`——这里曾经取的是 `title`/`body`
    #: 两个**不存在**的属性，于是每条通知的标题都是空字符串，而接口照样 200。
    title: str
    eventType: str | None = None
    read: bool = False
    at: str | None = None
    time: str | None = None


class AppNotificationList(StrictModel):
    items: list[AppNotification]
    count: int


class AppNotificationRead(StrictModel):
    ok: bool
    id: str
    status: str


# ---- 语音 ------------------------------------------------------------------

class AppUnderstood(StrictModel):
    reply: str
    code: str
    taskId: str | None = None
    taskStatus: str | None = None
    taskType: str | None = None


class AppVoiceSession(StrictModel):
    id: str
    status: str
    #: 这次会话**没带话**时为 null——没有话，引擎不可能理解任何东西。
    understood: AppUnderstood | None = None


# ---- 支付 ------------------------------------------------------------------

class AppPaymentPrepared(StrictModel):
    id: str
    status: str
    amount: str
    #: 要老人念出来的那一句。前端应当**原样显示**并原样送回来。
    prompt: str


class AppTeachBackResult(StrictModel):
    ok: bool
    #: 念对了没有。`false` 时这一笔**不许**继续。
    matched: bool
    outcome: str
    expected: str | None = None
    heard: str | None = None
    message: str


class AppPaymentMoved(StrictModel):
    ok: bool
    #: `awaiting_family` / `paid`。**不是**「已支付」——推进不等于付掉。
    status: str
    certificateId: str
    approvedBy: str | None = None
    message: str | None = None


class AppChainStep(StrictModel):
    action: str
    at: str | None = None
    by: str
    digest: str | None = None


class AppCertElements(StrictModel):
    voiceTeachBack: str | None = None
    location: str | None = None
    device: str | None = None
    time: str | None = None


class AppCertificate(StrictModel):
    id: str
    amount: str
    company: str | None = None
    #: 英文事务状态（`completed` / `awaiting_family_approval` …）。
    #: **前端必须翻译它再显示**——界面上不出现英文枚举值。
    #: 这一个刻意不翻：凭证要能和审计链对上，而链上记的就是这些值。
    status: str
    approvedBy: str | None = None
    paidAt: str | None = None
    chainValid: bool
    chain: list[AppChainStep]
    elements: AppCertElements


# ---- 记录 ------------------------------------------------------------------

class AppRecord(StrictModel):
    #: 审计表的主键是自增整数。
    id: int | None = None
    title: str
    #: 那一步的补充说明（比如复述「念错了金额，已停下」）。没有就是空串。
    note: str = ""
    kind: str
    icon: str
    time: str | None = None
    at: str | None = None
    entityId: str | None = None


class AppRecordList(StrictModel):
    items: list[AppRecord]
    #: 筛完之后的**总数**，不是这一页的条数。没有它，调用方无法判断还有没有下一页。
    #:
    #: 这个端点原先只有 `total`，而别的列表端点用的是 `count`（「这一页几条」）——
    #: 同一个词在两处指不同的东西。直接改名会掀翻调用方，所以两个都给，
    #: 各自的语义写在这里：看字段名是猜不出来的。
    total: int
    #: 这一页有几条。
    count: int
    hasMore: bool = False


# ---- 健康 / 紧急 -----------------------------------------------------------

class AppHealthMetric(StrictModel):
    label: str
    value: str | None = None
    unit: str | None = None
    at: str | None = None


class AppHealthSummary(StrictModel):
    overall: str | None = None
    metrics: list[AppHealthMetric]
    recorded: int
    note: str | None = None


class AppHealthRecorded(StrictModel):
    ok: bool
    id: str
    label: str
    #: 保持字符串：血压是「128/82」，不是一个数。拆成两个数字字段的话，
    #: 「128/82」和「体重 62.5」就没法用同一条路径记，而老人念出来的就是这两种形状。
    value: str
    unit: str | None = None
    at: str
    message: str


class AppEmergencyResult(StrictModel):
    ok: bool
    status: str
    #: 真的被通知到的人。空表示**没有任何人被通知**——那时 `message` 会让他打 120。
    notified: list[str]
    message: str


__all__ = [name for name in dir() if name.startswith("App")]
