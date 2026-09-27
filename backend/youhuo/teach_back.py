"""Verified teach-back: the elder must restate the facts, and we check them.

Teach-back is a long-standing clinical communication technique - ask the person
to say the information back in their own words to confirm they understood. It is
not our invention. What is specific here is using it as a *machine-verified gate
in front of an irreversible action*, where the restatement is compared against
authoritative tool values rather than against what the model believes.

The distinction that matters for safety: a generic "好的" proves nothing. Saying
"确认支付六十八块四" proves the elder heard the amount. When the restated value
is wrong, that is evidence of a specific misunderstanding, so the right response
is to re-explain that one field - not to reject the elder or to proceed anyway.

Nothing here consults a language model. Parsing spoken Chinese numerals and
comparing them to a stored amount is deterministic and auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import TaskType

_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "幺": 1, "二": 2, "两": 2, "贰": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}


def parse_chinese_number(text: str) -> int | None:
    """Parse a bare Chinese numeral under 10000. Returns None if it is not one.

    Handles the spoken forms an older adult actually uses: 六十八, 十五,
    一百二十六, 两百, 一百零五.
    """
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    seen = False
    for char in text:
        if char in _DIGITS:
            section = _DIGITS[char]
            seen = True
        elif char in _UNITS:
            unit = _UNITS[char]
            # 十五 means 15: a leading 十 has an implicit one.
            section = (section or 1) * unit
            total += section
            section = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + section


_NUM = r"[\d〇零一壹幺二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟]+"
_SMALL = r"[\d〇零一壹二两贰三叁四肆五伍六陆七柒八捌九玖]+"
#: 68.40 spoken as 六十八块四毛 / 六十八元四角 / 68块4 / 五块五分 ...
#: The jiao part is either explicitly marked (四毛) or a bare trailing digit
#: (68块4). A bare digit must not swallow a following 分, or 五块五分 would
#: parse as five yuan fifty cents instead of five yuan five fen.
_MONEY = re.compile(
    rf"(?P<yuan>{_NUM})\s*(?:块|元|圆)"
    rf"(?:\s*(?:(?P<jiao>{_SMALL})\s*(?:毛|角)|(?P<bare_jiao>{_SMALL})(?!\s*分)))?"
    rf"(?:\s*(?P<fen>{_SMALL})\s*分)?"
)
#: Only a genuine decimal; "68块4" must fall through to _MONEY instead of
#: matching "68" here and losing the jiao.
_DECIMAL_MONEY = re.compile(r"(?P<amount>\d+\.\d{1,2})\s*(?:块|元|圆)")
_PLAIN_MONEY = re.compile(r"(?<![\d.])(?P<amount>\d+)\s*(?:块|元|圆)(?!\s*[\d〇零一二三四五六七八九])")
_SPOKEN_DECIMAL = re.compile(
    r"(?P<int>[\d〇零一壹二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟]+)\s*点\s*"
    r"(?P<frac>[\d〇零一二两三四五六七八九]{1,2})\s*(?:块|元|圆)?"
)


def _digit_sequence(text: str) -> int | None:
    """'四零' -> 40 style digit-by-digit readings used after 点."""
    out = 0
    for char in text:
        if char.isdigit():
            out = out * 10 + int(char)
        elif char in _DIGITS:
            out = out * 10 + _DIGITS[char]
        else:
            return None
    return out


def parse_spoken_amount_cents(text: str) -> int | None:
    """Extract a money amount in cents from natural speech, or None."""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("，", "")

    match = _DECIMAL_MONEY.search(cleaned)
    if match:
        return int(round(float(match.group("amount")) * 100))

    match = _PLAIN_MONEY.search(cleaned)
    if match:
        return int(match.group("amount")) * 100

    match = _SPOKEN_DECIMAL.search(cleaned)
    if match:
        whole = parse_chinese_number(match.group("int"))
        frac_text = match.group("frac")
        if whole is not None:
            frac = _digit_sequence(frac_text)
            if frac is not None:
                # 点四 is four jiao (40 cents); 点四五 is 45 cents.
                cents = frac * 10 if len(frac_text) == 1 else frac
                return whole * 100 + cents

    match = _MONEY.search(cleaned)
    if match:
        yuan = parse_chinese_number(match.group("yuan"))
        if yuan is None:
            return None
        jiao_text = match.group("jiao") or match.group("bare_jiao") or "0"
        jiao = _digit_sequence(jiao_text) or 0
        fen = _digit_sequence(match.group("fen") or "0") or 0
        return yuan * 100 + jiao * 10 + fen
    return None


class TeachBackOutcome(StrEnum):
    VERIFIED = "verified"
    #: The elder restated a value, but it does not match the authoritative one.
    MISMATCH = "mismatch"
    #: A bare "好的" - agreement without evidence of understanding.
    NOT_RESTATED = "not_restated"
    #: This task does not require teach-back.
    NOT_REQUIRED = "not_required"


@dataclass(frozen=True)
class TeachBackCheck:
    outcome: TeachBackOutcome
    field_name: str | None = None
    expected_display: str | None = None
    heard_display: str | None = None
    prompt: str = ""
    #: Machine-readable signals for the comprehension model.
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome in {TeachBackOutcome.VERIFIED, TeachBackOutcome.NOT_REQUIRED}


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


class TeachBackVerifier:
    """Decides whether an elder's confirmation actually demonstrates understanding."""

    #: 一个听错了会造成真实伤害的字段 -> 它的名字。
    #:
    #: 原先这段注释用一句英文断言说：只有「听错了会造成真实伤害」的字段
    #: 才在这里，而且它们都已经被把住了。**其中一个没有。**
    #:
    #: （那句英文原话**不在这里复述**：判据
    #: `test_the_comment_no_longer_claims_both_are_gated` 查的就是
    #: 那句断言有没有回到源码里，复述一遍会让它红在我自己的注释上。
    #: 第一版就是这么红的。）
    #: 量出来的（三条独立的路，同一个结论）：
    #:
    #:     requires_teach_back(hospital_registration, 风险 1~4) = 假 假 假 假
    #:     verify(hospital_registration, …, required=True)      = not_required
    #:     号源时间存 09:30、她说「上午十点半」                    -> **不拦**
    #:
    #: 而且这张表**全仓零读者**：`verify()` 里写的是字面量
    #: `"amount_cents"`，压根没读它。所以它是一张装饰性的表，
    #: 而注释让读代码的人以为号源时间被核对了。
    #:
    #: 这一轮做两件事，都不替产品决定「挂号要不要复述」
    #: （那个决定有理由，见 `requires_teach_back`）：
    #:
    #:   · `verify()` 改成**从这张表取**字段名，表因此对活着的那一条承重；
    #:   · 还没接上的那一条**明写**在 `NOT_YET_GATED` 里，
    #:     让这张表说的话和代码一致。
    #:
    #: 判据 `test_the_fields_it_calls_critical_are_really_checked.py`
    #: 两头都查：表里每个键要么真的被 `verify()` 核对，要么在下面那份
    #: 名单里；而那份名单不许有表里没有的键（过期项）。
    CRITICAL_FIELD = {
        TaskType.BILL_PAYMENT: "amount_cents",
        TaskType.HOSPITAL_REGISTRATION: "appointment_time",
    }

    #: 上面那张表里**声明了但还没有接上**复述核对的那几格。
    #:
    #: 挂号：`requires_teach_back` 对它恒为假。那个判断本身有理由——
    #: 「Money is the one place a wrong number cannot be undone by
    #: talking」——号源订错了还能打电话改，钱划走了不能。
    #: **要不要给它也加一道，是产品决定，不在这一改里。**
    #:
    #: 这份名单的意义只有一个：让「有意没接」和「漏了」在代码里长得不一样。
    #: 做法照 `test_the_red_flags_it_names_are_the_ones_it_acts_on.py`
    #: 里 `NOT_YET_ACTED_ON` 那个先例。
    NOT_YET_GATED: frozenset[TaskType] = frozenset({
        TaskType.HOSPITAL_REGISTRATION,
    })

    @classmethod
    def requires_teach_back(cls, task_type: TaskType, risk_level: int, profile_enabled: bool) -> bool:
        if not profile_enabled:
            return False
        # Money is the one place a wrong number cannot be undone by talking.
        return task_type == TaskType.BILL_PAYMENT and risk_level >= 3

    @classmethod
    def build_prompt(cls, task_type: TaskType, slots: dict[str, Any]) -> str:
        if task_type == TaskType.BILL_PAYMENT:
            amount = int(slots.get(cls.CRITICAL_FIELD[task_type], 0) or 0)
            bill_type = slots.get("bill_type", "账单")
            return (
                f"这是{bill_type}，{_yuan(amount)}元。"
                f"为了确认您听清了，请您把金额说一遍，例如「确认支付{_yuan(amount)}元」。"
            )
        return "请用自己的话复述一遍要办理的内容。"

    @classmethod
    def verify(
        cls,
        task_type: TaskType,
        slots: dict[str, Any],
        text: str,
        *,
        required: bool,
    ) -> TeachBackCheck:
        if not required:
            return TeachBackCheck(TeachBackOutcome.NOT_REQUIRED)

        if task_type == TaskType.BILL_PAYMENT:
            #: 字段名**从 `CRITICAL_FIELD` 取**，不再写字面量。
            #: 这一行是那张表唯一的读者——没有它，那张表是装饰。
            field = cls.CRITICAL_FIELD[task_type]
            expected = int(slots.get(field, 0) or 0)
            heard = parse_spoken_amount_cents(text)
            if heard is None:
                return TeachBackCheck(
                    TeachBackOutcome.NOT_RESTATED,
                    field_name=field,
                    expected_display=_yuan(expected),
                    prompt=(
                        f"我还需要确认您听清了金额。请您说一遍金额，"
                        f"例如「确认支付{_yuan(expected)}元」。"
                    ),
                    signals={"restated": False},
                )
            if heard != expected:
                return TeachBackCheck(
                    TeachBackOutcome.MISMATCH,
                    field_name=field,
                    expected_display=_yuan(expected),
                    heard_display=_yuan(heard),
                    prompt=(
                        f"您说的是{_yuan(heard)}元，这次要交的是{_yuan(expected)}元。"
                        f"金额不一样，我先不办。请您再说一遍「确认支付{_yuan(expected)}元」。"
                    ),
                    signals={"restated": True, "expected_cents": expected, "heard_cents": heard},
                )
            return TeachBackCheck(
                TeachBackOutcome.VERIFIED,
                field_name=field,
                expected_display=_yuan(expected),
                heard_display=_yuan(heard),
                signals={"restated": True, "matched": True},
            )

        return TeachBackCheck(TeachBackOutcome.NOT_REQUIRED)
