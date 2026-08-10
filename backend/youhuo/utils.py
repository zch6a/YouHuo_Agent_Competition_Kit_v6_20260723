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
_CJK_PUNCTUATION = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？"}
_BETWEEN_CJK = re.compile(r"(?<=[一-鿿])([,;:!?])(?=[一-鿿])")


def restore_cjk_punctuation(text: str) -> str:
    """Undo NFKC's punctuation folding inside Chinese prose."""
    return _BETWEEN_CJK.sub(lambda m: _CJK_PUNCTUATION[m.group(1)], text)


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
