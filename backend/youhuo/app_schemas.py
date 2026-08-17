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
    #: 用哪个发音人。多音色模型（Kokoro 中文有男女多个）上才有意义；
    #: 单音色模型永远是 0。
    voiceSpeaker: int = 0
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


# ---- 用药 -------------------------------------------------------------------
#
# v4 那一侧（`/v4/medications*`）早就把用药计划、库存推算、服药记录都做完了，
# 而 `/api/v1` 一个入口都没有——老人端只有「用药提醒」，那只是一条到点响的提醒，
# 和「今天这几次吃了没」「药还能吃几天」是两回事。产品自己的帮助词
# （`care_voice.answer_capability_help`）已经在对老人承诺后面这两件事。
#
# 这一层**只读和记录，不建计划、不改剂量**。这不是省事：`create_medication_plan`
# 对 ELDER 角色建的计划直接 `active=True`，等于老人可以自己给自己开一份用药计划
# 并立刻生效。产品在自己的话术里已经划过这条线——「要登记的话，可以让家人在
# 家属端添加」「这些是家人确认过的计划，我不改剂量」。

class AppDose(StrictModel):
    """今天某一格：哪个药、几点、吃了没。"""
    planId: str
    name: str
    #: 「一次一片」。原样来自计划，不做解析——把它拆成数字再拼回去，
    #: 只会在某个写法上拼错，而这是药。
    doseText: str
    time: str
    #: 已服用 / 没吃 / 漏服 / 待服用。界面直接显示，所以是中文，不是枚举值。
    status: str
    #: 还没记录的那些。界面靠它决定要不要摆「吃了」按钮。
    pending: bool
    #: 记录这一格要回传的时刻。客户端不用自己拼时区。
    scheduledAt: str


class AppMedicationPlan(StrictModel):
    id: str
    name: str
    doseText: str
    times: list[str]
    #: 还能吃几天。没设服用频次时算不出来，回 null——不是 0。
    daysRemaining: int | None = None
    #: 预计哪天吃完，`YYYY-MM-DD`。
    depletionDate: str | None = None
    #: 充足 / 一周内用完 / 快吃完了 / 不清楚。同样是给人看的中文。
    stockLabel: str
    #: 原始告警档（normal/warning/critical/unknown），给客户端做样式判断用。
    #: 界面上不显示它——显示的是上面那个中文。
    alertLevel: str
    stockUnits: float


class AppMedicationToday(StrictModel):
    #: 今天的每一格，按时间排。
    doses: list[AppDose]
    plans: list[AppMedicationPlan]
    plannedCount: int
    takenCount: int
    #: 还没有任何记录的格数。**不等于** plannedCount - takenCount：
    #: 记成「没吃」的那一格是有记录的，不该被算进「还差几次」。
    pendingCount: int
    #: 一句能直接念出来的话。语音端和界面用同一句，避免两处各写一遍。
    summary: str
    #: 有药要在一周内用完时非空，例如「降压药还能吃大约 5 天」。
    stockWarning: str | None = None


# ---- 固定安排（循环例程）---------------------------------------------------
#
# 和「提醒」不是同一件事：提醒是一次性的一条，例程是**生成器**。
# `materialize_routines` 会为每一次发生真的插一条提醒
# （`source="routine:<id>"`），并在 `routine_occurrences.reminder_id` 上留下关联。
# 所以老人端的今日安排会自动认它们，这一层不用再拼一遍。

class AppRoutine(StrictModel):
    id: str
    title: str
    #: 每天 / 每周一、三 / 每月 5 号。给人看的一句话，不是枚举值。
    repeatText: str
    time: str
    #: 生活 / 用药 / 就医 / 缴费 / 社交。
    category: str
    #: 进行中 / 已暂停。
    status: str
    active: bool
    #: 下一次什么时候。已暂停的仍然给出原本的下次时间，界面上灰着显示。
    nextAt: str | None = None
    nextText: str | None = None


class AppRoutineList(StrictModel):
    items: list[AppRoutine]
    count: int
    message: str


class AppRoutineChanged(StrictModel):
    ok: bool
    id: str
    title: str
    status: str
    message: str
    #: 这次操作真的生成了几条提醒。0 表示**什么都没排上**——
    #: 那时界面不能说「已经排好了」。
    scheduled: int = 0


class AppPendingMedication(StrictModel):
    id: str
    name: str
    doseText: str
    times: list[str]
    addedAt: str


class AppPendingMedicationList(StrictModel):
    items: list[AppPendingMedication]
    count: int
    message: str


class AppMedicationDecided(StrictModel):
    ok: bool
    id: str
    name: str
    active: bool
    message: str


class AppDoseRecorded(StrictModel):
    ok: bool
    planId: str
    scheduledAt: str
    status: str
    message: str
    #: 记「吃了」会扣库存，所以这里回最新的剩余天数，界面不用再拉一次。
    daysRemaining: int | None = None
    #: 这一格之前已经记过了——第二次点不算失败，但也不重复扣库存。
    alreadyRecorded: bool = False


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


class AppSpeechStatus(StrictModel):
    #: 这台服务能不能本地合成。false = 客户端该用设备自带的朗读。
    available: bool
    engine: str | None = None
    #: **这位老人自己存的语速。** 放在这里而不是让调用方去 `/settings` 拼，
    #: 是因为本地合成和浏览器合成两条路的语速必须一致——分成两处取，迟早会不一致。
    speed: float
    #: 有几个声音可挑。只有 1 时界面不该摆「换个声音」那一栏——
    #: 摆了就是在承诺一件做不到的事。
    speakers: int = 1
    speaker: int = 0
    model: str | None = None
    #: vits / matcha / kokoro。三种音质差得很远，出问题第一件事就是问装的是哪个。
    kind: str | None = None
    fallback: str
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


class AppEscalationContact(StrictModel):
    """接力名单上的一个人。号码是**打码**的——这一屏不该把完整号码摆出来。"""
    name: str
    #: 家人 / 社区。界面显示这个，不是 `family`/`community`。
    role: str
    contact: str
    #: 越小越先联系。来自 `safety_contacts_v4.priority`。
    priority: int


class AppEmergencyResult(StrictModel):
    ok: bool
    status: str
    #: 真的被通知到的人。空表示**没有任何人被通知**——那时 `message` 会让他打 120。
    notified: list[str]
    message: str
    #: 安全策略给出的接力名单。此前这一层完全不看策略，于是社区网格员
    #: 永远不在名单里——而「家人没接就升级到社区」正是那份策略存在的理由。
    escalation: list[AppEscalationContact] = []
    #: 策略说要通知社区、并且确实有社区联系人。**不表示已经联系了社区**：
    #: 这个原型不自动拨号，v4 那一侧同样只是「准备好」。
    communityPrepared: bool = False


__all__ = [name for name in dir() if name.startswith("App")]
