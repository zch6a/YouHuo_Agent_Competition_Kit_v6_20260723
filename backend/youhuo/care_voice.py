"""语音可达层：让次要模式真的能用嘴问出来。

v6 已经实现了用药计划、服药依从、库存预测、健康时间线、亲友档案、循环事项和
适老交互档案——但它们只有 REST 接口。老人端主链对下面这些话一律回同一句
“我在听。您可以说…”：

    我今天吃药了吗 / 我的降压药还剩几片 / 我血压怎么样 / 我今天有什么事 /
    给我女儿打个电话 / 你说慢点 / 再说一遍 / 我听不清

对一个语音优先的适老产品，这等于这些能力不存在。本模块把它们接回主链。

三条边界，和主链其余部分保持一致：

1. **只读优先。** 查询直接用权威数据回答；真正有副作用的动作仍然走原来的
   任务链和确认门，不在这里悄悄写数据。
2. **唯一的写操作是老人改自己的交互档案**（语速、字号、听力支持）。这不需要
   家属批准——它是老人对自己怎么被对话的选择。
3. **不做医学判断。** 血压、血糖只复述记录值和测量时间，不解读、不建议用药。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any


class CareIntent(StrEnum):
    MEDICATION_TODAY = "medication_today"      # 今天吃药了吗
    MEDICATION_STOCK = "medication_stock"      # 药还剩多少
    MEDICATION_LIST = "medication_list"        # 我都吃什么药
    HEALTH_RECENT = "health_recent"            # 上次血压/体检怎么样
    SCHEDULE_TODAY = "schedule_today"          # 我今天有什么事
    CONTACT_REACH = "contact_reach"            # 给我女儿打电话
    SPEAK_SLOWER = "speak_slower"              # 你说慢点
    SPEAK_FASTER = "speak_faster"              # 说快点
    HEARING_SUPPORT = "hearing_support"        # 我听不清
    REPEAT = "repeat"                          # 再说一遍
    CAPABILITY_HELP = "capability_help"        # 你能干什么
    ORIENTATION = "orientation"                # 今天几号、现在几点
    SYMPTOM_MENTION = "symptom_mention"        # 我头有点晕


#: Ordered; first match wins. Written as regexes because bare keywords are too
#: greedy: "吃药" alone appears in "提醒我吃药", which must stay a reminder task.
_CUES: tuple[tuple[CareIntent, tuple[str, ...]], ...] = (
    # Accessibility first — an elder who cannot hear the reply cannot use
    # anything else, and these phrasings never overlap with a care query.
    (CareIntent.REPEAT, (r"再说一(遍|次)", r"重复一(遍|次)", r"没听清.{0,4}再", r"你刚(才|刚)说(的)?什么")),
    # 听不懂 is deliberately absent: that is comprehension, not hearing, and
    # "我听不懂医生说的" is something an elder tells 无忧伴 about someone else.
    (CareIntent.HEARING_SUPPORT, (r"听不(清|见)", r"声音(太)?小", r"大点声", r"说(大)?声点")),
    # These must be about *our* speech. Without the second person or an explicit
    # 太, "医生说快点去医院" reads as a request to change the speaking rate.
    # "你说快了" is a complaint (slow down); "你说快点" is an instruction (speed
    # up). Both start "你说快", so the complaint forms have to be spelled out.
    (CareIntent.SPEAK_SLOWER, (
        r"说(得)?太快", r"(你|您)说快了", r"慢(点|一点|些)(说|讲)", r"(说|讲)慢(点|一点|些)",
    )),
    (CareIntent.SPEAK_FASTER, (
        r"说(得)?太慢", r"(你|您)说慢了", r"(你|您)(说|讲)快(点|一点)?",
    )),
    # Medication stock before adherence: "还剩几片" is about supply, not intake.
    (CareIntent.MEDICATION_STOCK, (
        r"药.{0,6}(还剩|剩[多几]|够不够|够吃|不够了|快没了|没(有)?了)",
        r"(还剩|剩下).{0,4}(几片|多少片|几粒|几天)",
        # Elders name the drug instead of saying 药: "二甲双胍还够吃吗". These
        # quantity phrasings are distinctive enough to stand on their own.
        r"还够吃|够不够吃|还能吃几天|快吃完|(还剩|剩)[多几][少片粒天]",
        r"要不要.{0,4}买药", r"该(去)?买药了吗",
    )),
    (CareIntent.MEDICATION_TODAY, (
        r"(今天|今儿|早上|中午|晚上).{0,4}(吃|服).{0,2}药.{0,4}(了吗|没有|没|了没)",
        r"药.{0,4}(吃|服)(了吗|了没|没有)",
        r"我.{0,4}(吃|服)(过)?药了吗",
        r"(忘|漏).{0,4}(吃|服)药",
    )),
    (CareIntent.MEDICATION_LIST, (
        r"(都|要|该|在)(吃|服).{0,2}(什么|哪些|几种)药", r"我的?药.{0,4}(有哪些|都有什么)",
        r"我的用药(计划|安排)", r"每天.{0,4}吃(什么|哪些)药",
    )),
    (CareIntent.HEALTH_RECENT, (
        r"(血压|血糖|体检|化验|心率|体温|血脂).{0,8}(怎么样|多少|高不高|正常吗|结果)",
        r"(上次|最近|前几天).{0,6}(血压|血糖|体检|化验|量的)",
        r"我(的)?(血压|血糖).{0,4}(有点|是不是)?(高|低)",
        r"(查|看).{0,4}(我的)?(健康|体检|血压)(记录)?",
    )),
    (CareIntent.SCHEDULE_TODAY, (
        r"(今天|今儿|明天|这两天).{0,4}(有(什么|啥)|什么)(事|安排|活动|日程)",
        r"我.{0,4}(有什么|还有什么).{0,2}(事|安排)",
        r"(日程|安排|待办).{0,4}(是什么|有哪些|看一下)",
        r"接下来.{0,4}(要|该)(做|办)什么",
    )),
    (CareIntent.CONTACT_REACH, (
        r"(给|帮我给|帮我).{0,6}(打(个)?电话|联系|连线|通个话)",
        r"我要(找|联系).{0,4}(儿子|女儿|孙子|孙女|老伴|家人|家属)",
        r"(儿子|女儿|孙子|孙女|家人)的?(电话|号码)是多少",
    )),
    (CareIntent.CAPABILITY_HELP, (
        r"你(能|会|可以)(做什么|干什么|帮我做什么|干啥)",
        r"(有|都有)(什么|哪些)功能", r"我(能|可以)(让你|跟你)(做|说)什么",
        r"怎么(用|使唤)你", r"你会(干|做)什么",
    )),
    # Temporal orientation is a daily need for elders living alone, and getting
    # it from a wall calendar is exactly the friction this product exists to remove.
    (CareIntent.ORIENTATION, (
        r"今天(是)?(几号|什么日子|星期几|礼拜几|周几)",
        r"现在(是)?(几点|什么时候|什么时间)",
        r"今(儿|天)(是)?(初几|哪天)",
    )),
    # Last: a symptom mentioned in passing. Emergencies were already handled by
    # SafetyPolicy before we get here, so this is the non-urgent remainder.
    (CareIntent.SYMPTOM_MENTION, (
        r"(头|脑袋).{0,3}(晕|昏|沉|疼|痛)",
        r"(腰|腿|胳膊|肩膀|脖子|后背|膝盖|关节|胃|嗓子).{0,3}(疼|痛|酸|麻|不舒服)",
        r"咳嗽|发烧|发热",
        r"没(有)?力气|浑身乏力|累得慌",
        r"(胃口|食欲).{0,3}(不好|不行|差)",
        r"(睡不着|失眠).{0,4}(好几天|一直|老是)",
        r"(耳朵|眼睛).{0,3}(不舒服|难受|花|响)",
    )),
)


def classify(text: str) -> CareIntent | None:
    for intent, patterns in _CUES:
        if any(re.search(pattern, text) for pattern in patterns):
            return intent
    return None


@dataclass
class CareAnswer:
    """A resolved answer plus the label that goes into the audit chain."""

    message: str
    audit_event: str
    data: dict[str, Any] = field(default_factory=dict)
    #: Set when the elder changed their own interaction profile.
    profile_update: dict[str, Any] | None = None


# --------------------------------------------------------------------- 说法

def _clock_time(value: datetime) -> str:
    """Local wall-clock rendering. speech.js turns this into spoken Chinese."""
    return value.strftime("%H:%M")


def _day_phrase(target: date, today: date) -> str:
    delta = (target - today).days
    return {0: "今天", 1: "明天", 2: "后天", -1: "昨天"}.get(delta, f"{target.month}月{target.day}日")


def _join(parts: list[str], limit: int = 3) -> str:
    """Elders lose the thread past three items; say the rest as a count."""
    if len(parts) <= limit:
        return "、".join(parts)
    return "、".join(parts[:limit]) + f"，还有{len(parts) - limit}项"


# ------------------------------------------------------------------ 回答构造

def answer_medication_today(
    *, plans: list[Any], adherence: dict[str, Any], now: datetime
) -> CareAnswer:
    if not plans:
        return CareAnswer(
            "您现在没有登记在册的用药计划，所以我这边查不到今天该吃什么药。"
            "要登记的话，可以让家人在家属端添加。",
            "CARE_QUERY_MEDICATION_TODAY",
            {"plans": 0},
        )
    active = [plan for plan in plans if plan.active]
    total_doses = sum(len(plan.times_local) for plan in active)
    taken = int(adherence.get("taken", 0))
    if total_doses == 0:
        return CareAnswer(
            "您的用药计划还没有家人确认，暂时不用按它吃药。",
            "CARE_QUERY_MEDICATION_TODAY",
            {"plans": len(plans), "active": 0},
        )
    if taken >= total_doses:
        message = f"今天该吃的{total_doses}次药都记上了，您已经吃完了。"
    elif taken == 0:
        upcoming = sorted({time for plan in active for time in plan.times_local})
        message = (
            f"今天还没有服药记录。按计划要吃{total_doses}次，"
            f"时间是{_join(upcoming)}。"
        )
    else:
        message = f"今天计划吃{total_doses}次，已经记下{taken}次，还差{total_doses - taken}次。"
    # Never assert the elder did not take it — only that nothing was recorded.
    message += " 我只能看到记录，如果您吃了但没记，可以让家人补一条。"
    return CareAnswer(
        message,
        "CARE_QUERY_MEDICATION_TODAY",
        {"planned_doses": total_doses, "recorded_taken": taken, "as_of": _clock_time(now)},
    )


def match_plans_by_name(plans: list[Any], text: str) -> list[Any]:
    """Plans the elder named outright.

    Only literal name matches count. Mapping a colloquial class like "降压药" onto
    a specific drug would be a clinical claim this system has no source for, so
    an unmatched class term falls through to "all plans, most urgent first"
    rather than a confident guess about which pill they meant.
    """
    matched = []
    for plan in plans:
        names = [plan.display_name, getattr(plan, "normalized_name", "")]
        if any(_name_spoken(name, text) for name in names if name):
            matched.append(plan)
    return matched


#: Elders say "氨氯地平", the record says "苯磺酸氨氯地平". Accept any run of at
#: least this many characters from the registered name; shorter overlaps start
#: matching unrelated words.
_NAME_MATCH_MIN = 3


def _name_spoken(name: str, text: str) -> bool:
    if name in text:
        return True
    if len(name) <= _NAME_MATCH_MIN:
        return False
    return any(
        name[start:start + length] in text
        for length in range(len(name) - 1, _NAME_MATCH_MIN - 1, -1)
        for start in range(len(name) - length + 1)
    )


#: Colloquial drug classes an elder is likely to say. We can recognise that they
#: narrowed the question without being able to resolve which plan they meant.
_CLASS_TERMS = ("降压药", "血压药", "降糖药", "血糖药", "降脂药", "安眠药", "止疼药", "止痛药", "心脏药")


def answer_medication_stock(*, forecasts: list[tuple[Any, Any]], text: str = "", narrowed: bool = False) -> CareAnswer:
    if not forecasts:
        return CareAnswer(
            "我这边没有查到登记的药品库存。", "CARE_QUERY_MEDICATION_STOCK", {"plans": 0}
        )
    order = {"normal": 0, "unknown": 1, "warning": 2, "critical": 3}
    # Most urgent first: the elder may stop listening after the first clause, and
    # the drug that runs out in four days must not be the one they miss.
    ranked = sorted(
        forecasts,
        key=lambda pair: (
            pair[1].days_remaining if pair[1].days_remaining is not None else float("inf")
        ),
    )
    lines: list[str] = []
    worst = "normal"
    for plan, forecast in ranked:
        if forecast.days_remaining is None:
            lines.append(f"{plan.display_name}还有{plan.stock_units:g}个单位，没设服用频次，算不出能吃几天")
        else:
            lines.append(f"{plan.display_name}还能吃大约{int(forecast.days_remaining)}天")
        if order[forecast.alert_level] > order[worst]:
            worst = forecast.alert_level

    prefix = ""
    unresolved_class = (
        not narrowed
        and len(ranked) > 1
        and any(term in text for term in _CLASS_TERMS)
    )
    if unresolved_class:
        # Say why we widened it instead of quietly answering a different question.
        prefix = "我这边按药名记的，分不出哪种是您说的那类，把在吃的都说一下："
    message = prefix + "；".join(lines) + "。"
    if worst == "critical":
        message += " 快吃完了，建议这两天就去补。要我记一条提醒吗？"
    elif worst == "warning":
        message += " 一周之内会用完，方便时补一下。要我记一条提醒吗？"
    return CareAnswer(
        message,
        "CARE_QUERY_MEDICATION_STOCK",
        {
            "alert_level": worst,
            "plans": len(ranked),
            "narrowed_by_name": narrowed,
            "unresolved_class_term": unresolved_class,
        },
    )


def answer_medication_list(*, plans: list[Any]) -> CareAnswer:
    active = [plan for plan in plans if plan.active]
    if not active:
        return CareAnswer(
            "您现在没有已确认的用药计划。", "CARE_QUERY_MEDICATION_LIST", {"active": 0}
        )
    lines = [
        f"{plan.display_name}，{plan.dose_text}，{_join(list(plan.times_local))}"
        for plan in active
    ]
    return CareAnswer(
        "您在吃的是：" + "；".join(lines) + "。这些是家人确认过的计划，我不改剂量。",
        "CARE_QUERY_MEDICATION_LIST",
        {"active": len(active)},
    )


def answer_health_recent(*, events: list[Any], now: datetime) -> CareAnswer:
    if not events:
        return CareAnswer(
            "我这边还没有您的健康记录。量了血压或者做了体检，可以让家人记进来，以后您问我就能说了。",
            "CARE_QUERY_HEALTH_RECENT",
            {"events": 0},
        )
    latest = events[0]
    when = _day_phrase(latest.event_at.date(), now.date())
    detail = ""
    readable = {
        key: value
        for key, value in latest.payload.items()
        if isinstance(value, (int, float, str)) and not isinstance(value, bool)
    }
    if readable:
        detail = "，" + "、".join(f"{key} {value}" for key, value in list(readable.items())[:3])
    return CareAnswer(
        f"最近一条记录是{when}的“{latest.title}”{detail}。"
        f"我只是把记录念给您听，不做判断；身体上的事请以医生的说法为准。",
        "CARE_QUERY_HEALTH_RECENT",
        {"events": len(events), "latest_kind": latest.kind.value},
    )


def answer_schedule_today(*, reminders: list[Any], now: datetime) -> CareAnswer:
    if not reminders:
        return CareAnswer(
            "接下来一天里没有安排。要加一件事，您可以说“提醒我明天上午九点复诊”。",
            "CARE_QUERY_SCHEDULE",
            {"count": 0},
        )
    parts = [
        f"{_day_phrase(item.due_at.date(), now.date())}{_clock_time(item.due_at)}{item.title}"
        for item in reminders
    ]
    return CareAnswer(
        f"接下来有{len(reminders)}件事：" + _join(parts) + "。",
        "CARE_QUERY_SCHEDULE",
        {"count": len(reminders)},
    )


def _spoken_phone(masked: str | None) -> str:
    """Say a masked number the way a person does, not as a cardinal.

    The stored form is `*******1111`. Read literally a synthesiser says
    "一千一百一十一", which is not a phone number in any language. Chinese
    speakers say "尾号一一一一", and speech.js reads the digits after 尾号
    one at a time.
    """
    if not masked:
        return "还没有登记"
    tail = "".join(ch for ch in masked if ch.isdigit())
    if not tail:
        return "还没有登记"
    return f"尾号{tail[-4:]}"


def answer_contact_reach(*, contacts: list[Any], text: str) -> CareAnswer:
    """We never place a call. Say who is reachable and hand it to the elder.

    The competition build has no telephony, and quietly pretending otherwise
    would be exactly the kind of unverifiable claim the rest of this system is
    built to avoid.
    """
    if not contacts:
        return CareAnswer(
            "我这边还没有存联系人。让家人在家属端添加之后，我就能告诉您找谁。",
            "CARE_QUERY_CONTACT",
            {"contacts": 0},
        )
    wanted = next((c for c in contacts if c.relation and c.relation in text), None)
    if wanted is None:
        wanted = next((c for c in contacts if c.display_name and c.display_name in text), None)
    if wanted is not None:
        return CareAnswer(
            f"{wanted.display_name}（{wanted.relation}）的号码{_spoken_phone(wanted.phone_masked)}。"
            "比赛演示版不能替您拨号，需要您自己拨，或者我给家人发条消息请他们回电。",
            "CARE_QUERY_CONTACT",
            {"matched": True},
        )
    names = _join([f"{c.display_name}（{c.relation}）" for c in contacts])
    return CareAnswer(
        f"您可以联系：{names}。您说找谁，我把号码念给您。",
        "CARE_QUERY_CONTACT",
        {"matched": False, "contacts": len(contacts)},
    )


_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def answer_orientation(*, now: datetime) -> CareAnswer:
    # No year: speech.js drops it for the current year too, and "2026年" written
    # out would be read as a cardinal number rather than digit by digit. The
    # HH:MM form is left for speech.js to turn into "下午两点半".
    return CareAnswer(
        f"今天是{now.month}月{now.day}日，{_WEEKDAYS[now.weekday()]}，"
        f"现在{_clock_time(now)}。",
        "CARE_QUERY_ORIENTATION",
        {"date": now.date().isoformat()},
    )


def answer_symptom_mention() -> CareAnswer:
    """Acknowledge, offer the thing we can actually do, and name the red flags.

    Deliberately does not book anything: an elder saying "我头有点晕" has not
    asked for a hospital appointment, and starting one would be the agent
    deciding something it was not asked to decide. It also gives no advice —
    naming when to stop talking to us and call for help is not a diagnosis.
    """
    return CareAnswer(
        "听着您不太舒服。我不能看病，也不敢替医生判断。"
        "要我帮您挂个号吗？说“帮我挂号”就行；也可以说“提醒我明天去医院”。"
        "要是突然加重、说不清话、站不稳或者胸口发闷，别等我，直接打急救电话或者叫人。",
        "CARE_SYMPTOM_ACKNOWLEDGED",
        {"offered_registration": True, "clinical_advice": False},
    )


def answer_capability_help() -> CareAnswer:
    return CareAnswer(
        "我能帮您做这些：挂号看病、查水电燃气费和缴费、记提醒和日程、"
        "查今天的药吃了没和药还剩多少、念最近的健康记录、找家里人的号码。"
        "想找人说话，就说“调用无忧伴”。您一次说一件就行。",
        "CARE_QUERY_HELP",
    )


# ------------------------------------------------- 老人自助调节交互档案（写）

#: Bounds mirror InteractionProfileUpdate so a voice command can never push the
#: profile outside what the REST contract allows.
_RATE_MIN, _RATE_MAX = 0.6, 1.2
_RATE_STEP = 0.08


def adjust_profile(intent: CareIntent, profile: Any) -> CareAnswer | None:
    """Return the profile change the elder just asked for, or None."""
    if intent is CareIntent.SPEAK_SLOWER:
        new_rate = round(max(_RATE_MIN, profile.speech_rate - _RATE_STEP), 3)
        if new_rate >= profile.speech_rate:
            return CareAnswer(
                "已经是最慢的语速了。如果还是跟不上，可以说“我听不清”，我会一句一句地说。",
                "CARE_PROFILE_SPEECH_RATE",
                {"speech_rate": profile.speech_rate, "changed": False},
            )
        return CareAnswer(
            "好，我说慢一点。",
            "CARE_PROFILE_SPEECH_RATE",
            {"speech_rate": new_rate, "changed": True},
            profile_update={"speech_rate": new_rate},
        )
    if intent is CareIntent.SPEAK_FASTER:
        new_rate = round(min(_RATE_MAX, profile.speech_rate + _RATE_STEP), 3)
        if new_rate <= profile.speech_rate:
            return CareAnswer(
                "已经是最快的语速了。",
                "CARE_PROFILE_SPEECH_RATE",
                {"speech_rate": profile.speech_rate, "changed": False},
            )
        return CareAnswer(
            "好，我说快一点。",
            "CARE_PROFILE_SPEECH_RATE",
            {"speech_rate": new_rate, "changed": True},
            profile_update={"speech_rate": new_rate},
        )
    if intent is CareIntent.HEARING_SUPPORT:
        update: dict[str, Any] = {"hearing_support": True, "max_sentence_chars": 24}
        rate = round(max(_RATE_MIN, profile.speech_rate - _RATE_STEP), 3)
        if rate < profile.speech_rate:
            update["speech_rate"] = rate
        return CareAnswer(
            "好，我把句子说短一点、慢一点，字也调大。您要是还听不清，就说“再说一遍”。",
            "CARE_PROFILE_HEARING_SUPPORT",
            {"hearing_support": True, "max_sentence_chars": 24},
            profile_update=update,
        )
    return None


def answer_repeat(last_message: str | None) -> CareAnswer:
    if not last_message:
        return CareAnswer(
            "我们还没聊过什么，您直接说要办的事就行。", "CARE_REPEAT", {"had_previous": False}
        )
    return CareAnswer(
        "我再说一遍：" + last_message, "CARE_REPEAT", {"had_previous": True}
    )


#: Horizon for "我今天有什么事". A day plus a little, so an evening question
#: still surfaces tomorrow morning's appointment.
SCHEDULE_HORIZON = timedelta(hours=30)

__all__ = [
    "CareIntent",
    "CareAnswer",
    "classify",
    "adjust_profile",
    "answer_capability_help",
    "answer_contact_reach",
    "answer_health_recent",
    "answer_medication_list",
    "answer_medication_stock",
    "answer_medication_today",
    "answer_orientation",
    "answer_repeat",
    "answer_schedule_today",
    "answer_symptom_mention",
    "match_plans_by_name",
    "SCHEDULE_HORIZON",
]
