from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_CONTROL_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}
_CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def clean_user_text(text: str, *, max_length: int) -> str:
    """Normalize user text and remove invisible/control characters.

    NFKC reduces full-width and compatibility variants that can hide control-like
    instructions. New lines are collapsed because the voice UI is single-turn.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(ch if unicodedata.category(ch) not in _CONTROL_CATEGORIES else " " for ch in normalized)
    normalized = " ".join(normalized.replace("\x00", " ").split())
    if not normalized:
        raise ValueError("text cannot be blank")
    if len(normalized) > max_length:
        normalized = normalized[:max_length]
    return normalized


#: NFKC folds full-width CJK punctuation to ASCII, which is what we want for
#: untrusted input but not for text an elder reads back. Restored only between
#: two CJK characters, so "08:00" and "126.50" keep their ASCII forms — the
#: speech normaliser matches those by regex and would miss "08：00".
#:
#: 两侧的字符类**必须把 CJK 标点也算进来**（U+3001–U+301F：、。「」『』《》【】…）。
#: 第一版只写了 U+4E00–U+9FFF（统一表意文字），于是 `」` 不算「CJK 字符」，
#: 任何 `…「X」，…` 里的逗号折成半角之后再也没被还原过。而 `「」` 正是这个项目
#: 规定的引号样式，中招的恰好是指令最密的那些句子。实测那一句：
#:
#:     最近一条记录是今天的「血压」,记的是138/86 mmHg。我只是把记录念给您听，不做判断。
#:                         ^ 半角                                        ^ 全角
#:
#: 同一句话里两个逗号一半一全，差别只在左边那个字是 `」` 还是汉字。
#: 语料量过：1493 条会上屏的短句里 11 条变化，条条是修好（含老人端主帮助句、
#: 办事确认指令、三条医疗升级提示）；而必须留半角的那些——时间、小数、
#: `血压 138/86 mmHg`——一条都没变，因为数字两侧不在新加的这一段里。
_CJK_PUNCTUATION = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？",
                    #: 本轮补的。端到端实测：`v4_api.py:324` 那条真实的提醒标题
                    #: 「按体检报告建议复查（请先与医生确认）」过治理器之后变成
                    #: 半角 `(...)`。和逗号那一条是同一个机制、同一处修法。
                    "(": "（", ")": "）"}
#: 汉字 + CJK 标点。分成常量是为了两侧写同一份，别再出现一侧宽一侧窄。
_CJK_CONTEXT = r"\u4e00-\u9fff\u3001-\u301f"
#: **只看左边。** 原先还要求右边也是 CJK，于是
#:
#:     待办提醒:CT复查。 / :B超检查。 / :120复诊。 / :8点的药。   <- 没还原
#:     待办提醒：量血压。 / ：吃降压药。 / ：做CT。                <- 还原了
#:
#: 左边都是「醒」，差别只在右边是字母数字还是汉字。而且右边要求有字
#: 意味着**句末**的标点一个都没还原过——每一句问句和感叹句都以半角
#: `?` / `!` 结尾（「这件事要叫什么名字?」「…我们做得可真棒!」）。
#:
#: 语料标定过（后端全部含汉字的字面量，先 NFKC 折半角再还原，比新旧两版）：
#: 变化的都是修好，**没有**把 `HH:MM` 之类改成全角。保护时间/小数的
#: 其实是**左侧**——`08:00` 左边是 `8`、`1,000` 左边是 `1`、
#: `血压 138/86` 里根本没有这几个标点——所以放宽右侧碰不到它们。
#: 那条反面判据的四个用例逐个验过全部不变：
#:     "上午 08:00 吃药" "体重 126.50 公斤" "血压 138/86 mmHg" "abc:def"
#:
#: 而正面那条判据（`test_a_record_is_read_as_chinese.py:183-186`）查的正是
#: 「有没有半角标点紧跟在 CJK 后面」——它检查的条件就是这条新规则本身。
#: 判据一直比实现宽，这一改让两边对上。
_BETWEEN_CJK = re.compile(rf"(?<=[{_CJK_CONTEXT}])([,;:!?()])")

#: 省略号单独一条，**因为 `.` 不能进上面那个字符类**：`126.50` 的点
#: 左边是 `6` 不是汉字，所以放进去也碰不到它——但 `08:00、12:00` 这类
#: 串里的点一旦被误配，`speech.js` 的正则就匹配不到金额了。稳妥起见分开。
#:
#: NFKC 把「…」(U+2026) 展成三个半角句点，中文的「……」是两个 U+2026，
#: 于是变成六个。按每三个点还原一个来算，「……」和「…」都对得上。
#: 左侧同样只看汉字/CJK 标点，所以 `126.50`（点左边是 `6`）不受影响。
_ELLIPSIS_AFTER_CJK = re.compile(rf"(?<=[{_CJK_CONTEXT}])(\.{{3,}})")


def restore_cjk_punctuation(text: str) -> str:
    """Undo NFKC's punctuation folding inside Chinese prose.

    ## 本轮补了两类：全角括号和省略号

    原先这张表只有五个（，；：！？）。取样集**枚举**中文文案会用到的
    39 个标点逐个过流水线，被 NFKC 折掉而没还原的有 **15 个**；按界面
    文案里的用量排，真正在用的是全角括号和省略号（其余十个用量 0–4 处，
    多在技术上下文里，点名记在判据的 `DEFERRED` 里）。

    端到端实测（`v4_api.py:324` 真实的提醒标题写法）：

        原文         按体检报告建议复查（请先与医生确认）。要改说「改成……」。
        过治理器后   按体检报告建议复查(请先与医生确认)。
                              ^^^^^^^^^^^^^^^^^^ 半角括号

    「只看左边」这个设计不动：它正是保护 `08:00` / `126.50` / `138/86`
    的那一条（见上面那段注释的语料标定）。括号进同一个字符类，所以
    `abc(def)` 这类技术串照样不受影响——`(` 左边是 `c` 不是汉字。
    """
    restored = _BETWEEN_CJK.sub(lambda m: _CJK_PUNCTUATION[m.group(1)], text)
    return _ELLIPSIS_AFTER_CJK.sub(
        lambda m: "…" * (len(m.group(1)) // 3) + "." * (len(m.group(1)) % 3),
        restored,
    )


def normalize_text(text: str) -> str:
    try:
        return clean_user_text(text, max_length=10000).casefold()
    except ValueError:
        return ""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def semantic_hash(parts: list[Any]) -> str:
    normalized = "|".join(normalize_text(str(p)) for p in parts if p is not None and str(p) != "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def request_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _cn_integer(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token in _CN_NUM:
        return _CN_NUM[token]
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_NUM.get(left, 1) if left else 1
        ones = _CN_NUM.get(right, 0) if right else 0
        return tens * 10 + ones
    if token and all(ch in _CN_NUM for ch in token):
        result = 0
        for ch in token:
            result = result * 10 + _CN_NUM[ch]
        return result
    return None


def parse_relative_date(text: str, today: date) -> str | None:
    text = unicodedata.normalize("NFKC", text)
    if "大后天" in text:
        return (today + timedelta(days=3)).isoformat()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "今天" in text or "今日" in text:
        return today.isoformat()

    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    m_week = re.search(r"(下周|下星期|本周|这周|星期|周)([一二三四五六日天])", text)
    if m_week:
        prefix, day_token = m_week.groups()
        target = weekday_map[day_token]
        days_ahead = (target - today.weekday()) % 7
        if prefix in {"下周", "下星期"}:
            days_ahead = days_ahead + 7 if days_ahead == 0 else days_ahead
            if days_ahead < 7:
                days_ahead += 7
        elif days_ahead == 0 and prefix in {"星期", "周"}:
            days_ahead = 7
        return (today + timedelta(days=days_ahead)).isoformat()

    # Numeric boundaries are required on both ends.  Keep yearful and yearless
    # forms separate: with an optional year, ``12026-08-10`` can otherwise fall
    # back to the tail ``08-10`` and still be accepted as this year's date.
    match = re.search(r"(?<!\d)(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?(?!\d)", text)
    has_explicit_year = match is not None
    if match is None:
        match = re.search(r"(?<![\d年/-])(\d{1,2})[月/-](\d{1,2})日?(?!\d)", text)
    if match:
        if has_explicit_year:
            year, month, day = (int(match.group(index)) for index in (1, 2, 3))
        else:
            year = today.year
            month, day = (int(match.group(index)) for index in (1, 2))
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not has_explicit_year and candidate < today:
            try:
                candidate = date(today.year + 1, month, day)
            except ValueError:
                return None
        return candidate.isoformat()
    return None


def parse_time_text(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text)
    m = re.search(
        r"(凌晨|早上|上午|中午|下午|傍晚|晚上)?\s*([零〇一二两三四五六七八九十\d]{1,3})[点时:]"
        r"(?:(半)|([零〇一二两三四五六七八九十\d]{1,3})分?)?",
        text,
    )
    if not m:
        return None
    part, hour_token, half, minute_token = m.groups()
    hour = _cn_integer(hour_token)
    minute = 30 if half else (_cn_integer(minute_token) if minute_token else 0)
    if hour is None or minute is None:
        return None
    if part in {"下午", "傍晚", "晚上"} and hour < 12:
        hour += 12
    elif part == "中午" and hour < 11:
        hour += 12
    elif part in {"凌晨", "早上", "上午"} and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_month_day(text: str) -> str | None:
    """从一句话里取出「几月几号」，中文数字和阿拉伯数字都认，回 `MM-DD`。

    和 `parse_time_text` 放在一起、共用同一个 `_cn_integer`，是因为**它们是
    同一类东西**。这一条原先不在这里：它是 `v5_services._date_signature`
    里手写的一条 `(\\d{1,2})月(\\d{1,2})[日号]`，**只认阿拉伯数字**。

    实测那个后果（`POST /v5/voice/resolve`，两个 N-best 候选）：

        「挂九月二十号上午的号」 / 「挂九月二十六号上午的号」
            两边 `_date_signature` 都是 None
            -> `_contradiction` 判为不冲突 -> status=accepted，歧义度 0.023
        同一对换成「挂9月20号」 / 「挂9月26号」
            -> md:09-20 / md:09-26 -> 冲突 -> status=clarify

    守卫本身是好的，只有这个解析器认不出她真正会说的那种说法。而
    `youhuo-voice-consensus` 的 Policy 把日期和金额并列（「金额或日期发生
    冲突时不得猜测」），金额那一侧一直认口语
    （`parse_spoken_amount_cents("六十八元四角") == 6840`），
    时间那一侧也一直认（`parse_time_text("上午九点") == "09:00"`）——
    三个兄弟字段里只有日期这一个是瞎的。

    `_contradiction` 里那句 `if item.get(field) is not None` 是放大器：
    解析不出来的说法，这次比较**整条被丢掉**，而 `len(set([])) > 1` 为假,
    也就是「不冲突」。解析器的覆盖面就是这条守卫的覆盖面。
    """
    normalized = unicodedata.normalize("NFKC", text)
    m = re.search(
        r"(?<![\d〇零一二两三四五六七八九十])"
        r"([\d〇零一二两三四五六七八九十]{1,3})\s*月\s*"
        r"([\d〇零一二两三四五六七八九十]{1,4})\s*[日号]",
        normalized,
    )
    if not m:
        return None
    month = _cn_integer(m.group(1))
    day = _cn_integer(m.group(2))
    if month is None or day is None:
        return None
    #: 越界的就当没认出来，宁可不报冲突，也不要拿一个假签名去比。
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    return f"{month:02d}-{day:02d}"


#: 老人所在的时区。
#:
#: 这个常量原先只在 `baseline_store.py` 有一份，v7 日报靠它把"今天"切在本地零点，
#: 那份注释写得很清楚：「用 UTC 的今天，在 UTC+8 就等于把一天切在早上八点」。
#: 而 v2 的提醒链路和语音回读完全不知道它存在——于是同一个产品里，v7 日报的"今天"
#: 和 v2 提醒的"今天"是两个不同的日子，而"现在几点了"答的是格林尼治时间。
#: 放在 utils 里，两边共用一份。
LOCAL_TIMEZONE = "Asia/Shanghai"


def local_zone() -> ZoneInfo:
    return ZoneInfo(LOCAL_TIMEZONE)


def local_now(now: datetime) -> datetime:
    """换算到老人所在时区。一切要读出**墙上时间**的地方都必须先过这一步。"""
    return now.astimezone(local_zone())


def local_today(now: datetime) -> date:
    """"今天"是老人所在时区的今天，不是 UTC 的今天。"""
    return local_now(now).date()


def combine_date_time(date_iso: str, time_hhmm: str) -> str:
    """把"哪一天"和"几点"拼成一个**带本地偏移**的 ISO 串。

    原先返回的是无时区的裸串，调用方紧接着 `.replace(tzinfo=UTC)`——那等于宣称老人
    说的"上午九点"是格林尼治的九点，实际存成了北京 17:00。带上偏移之后，调用方只需
    `astimezone(UTC)` 换算存储。
    """
    d = date.fromisoformat(date_iso)
    h, m = [int(x) for x in time_hhmm.split(":")]
    return datetime.combine(d, time(hour=h, minute=m), tzinfo=local_zone()).isoformat()
