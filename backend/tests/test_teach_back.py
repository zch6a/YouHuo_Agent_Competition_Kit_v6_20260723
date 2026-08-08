"""Verified teach-back: agreement is not evidence of understanding.

The README lists 复述确认 as a core innovation and design §4.2 spells out the
exact phrasing. Before this, `_is_yes` accepted a bare "好的" for a risk-4
payment, so the gate existed only on paper. These tests pin the real behaviour.
"""

from __future__ import annotations

import pytest

from youhuo.models import ResponseCode, TaskType
from youhuo.teach_back import (
    TeachBackOutcome,
    TeachBackVerifier,
    parse_chinese_number,
    parse_spoken_amount_cents,
)
from .helpers import amount_from, chat, confirm_bill


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("text,cents", [
    ("确认支付68.40元", 6840),
    ("确认支付六十八块四", 6840),
    ("六十八块四毛", 6840),
    ("六十八元四角", 6840),
    ("六十八点四元", 6840),
    ("68块4", 6840),
    ("一百二十六块五毛", 12650),
    ("一百零五块", 10500),
    ("十五块", 1500),
    ("两百块", 20000),
    ("五块五分", 505),
    ("我确认支付一百二十六块五毛整", 12650),
])
def test_spoken_amounts_an_elder_would_actually_say(text, cents):
    assert parse_spoken_amount_cents(text) == cents


@pytest.mark.parametrize("text", ["好的", "确认办理", "就这样吧", "可以", ""])
def test_agreement_without_a_number_is_not_an_amount(text):
    assert parse_spoken_amount_cents(text) is None


@pytest.mark.parametrize("text,value", [
    ("六十八", 68), ("一百二十六", 126), ("两百", 200), ("十五", 15), ("一百零五", 105),
])
def test_chinese_numerals(text, value):
    assert parse_chinese_number(text) == value


# ------------------------------------------------------------------ verifier

def test_only_money_is_gated():
    """Asking an elder to recite everything would itself be a load failure."""
    assert TeachBackVerifier.requires_teach_back(TaskType.BILL_PAYMENT, 4, True) is True
    assert TeachBackVerifier.requires_teach_back(TaskType.REMINDER, 4, True) is False
    assert TeachBackVerifier.requires_teach_back(TaskType.BILL_PAYMENT, 2, True) is False
    assert TeachBackVerifier.requires_teach_back(TaskType.BILL_PAYMENT, 4, False) is False


def test_verifier_outcomes():
    slots = {"amount_cents": 6840, "bill_type": "水费"}
    verify = lambda text: TeachBackVerifier.verify(TaskType.BILL_PAYMENT, slots, text, required=True)

    assert verify("确认支付68.40元").outcome is TeachBackOutcome.VERIFIED
    assert verify("确认支付六十八块四").outcome is TeachBackOutcome.VERIFIED

    missing = verify("好的")
    assert missing.outcome is TeachBackOutcome.NOT_RESTATED
    assert not missing.passed and "68.40" in missing.prompt

    wrong = verify("确认支付六百八十块")
    assert wrong.outcome is TeachBackOutcome.MISMATCH
    assert not wrong.passed
    assert wrong.heard_display == "680.00" and wrong.expected_display == "68.40"
    # The elder is told what they said and what it should be, not just "no".
    assert "680.00" in wrong.prompt and "68.40" in wrong.prompt


# ------------------------------------------------------------------ end to end

def test_bare_agreement_no_longer_settles_a_bill(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    assert asked.code == ResponseCode.NEED_ELDER_CONFIRMATION
    # The prompt must tell the elder exactly what to say.
    assert "确认支付" in asked.message and amount_from(asked.message) in asked.message

    vague = chat(engine, elder, session, "好的")
    assert vague.code == ResponseCode.NEED_ELDER_CONFIRMATION
    assert vague.data["teach_back"] == "not_restated"
    assert db.unpaid_bill("fam-demo", "水费") is not None, "没有复述金额时绝不能扣款"


def test_wrong_amount_is_caught_and_explained(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    wrong = chat(engine, elder, session, "确认支付六百八十块")
    assert wrong.code == ResponseCode.NEED_ELDER_CONFIRMATION
    assert wrong.data["teach_back"] == "mismatch"
    assert wrong.data["heard"] == "680.00"
    assert db.unpaid_bill("fam-demo", "水费") is not None


def test_correct_restatement_proceeds_to_family_relay(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    ok = confirm_bill(engine, elder, session, asked.message)
    assert ok.code == ResponseCode.NEED_FAMILY_APPROVAL
    assert ok.approval_digest


def test_recovery_after_a_wrong_restatement(env):
    """A miss is a misunderstanding to correct, not a lockout."""
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    chat(engine, elder, session, "确认支付九百块")
    recovered = confirm_bill(engine, elder, session, asked.message)
    assert recovered.code == ResponseCode.NEED_FAMILY_APPROVAL


def test_every_attempt_is_audited(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    chat(engine, elder, session, "好的")
    chat(engine, elder, session, "确认支付九百块")
    confirm_bill(engine, elder, session, asked.message)
    events = [e for e in db.list_audit("fam-demo", limit=200)
              if e.event_type.startswith("TEACH_BACK_")]
    assert [e.event_type for e in events] == [
        "TEACH_BACK_REJECTED", "TEACH_BACK_REJECTED", "TEACH_BACK_VERIFIED"
    ]
    assert db.verify_audit_chain("fam-demo") is True


def test_comprehension_signals_accumulate(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    chat(engine, elder, session, "确认支付九百块")
    confirm_bill(engine, elder, session, asked.message)
    summary = db.comprehension_summary("fam-demo", "elder-demo")
    assert summary["observations"] == 2
    assert summary["mismatched"] == 1 and summary["verified"] == 1
    assert summary["first_try_rate"] == 0.5


def test_comprehension_record_never_stores_what_was_said(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    chat(engine, elder, session, "确认支付九百块乱说的话")
    rows = db._conn.execute("SELECT * FROM comprehension_events").fetchall()
    for row in rows:
        assert "乱说" not in "".join(str(value) for value in tuple(row))


def test_registration_and_reminders_are_not_gated(env):
    """Teach-back is for money; gating everything would add load, not safety."""
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我挂明天下午两点第一医院骨科王医生的号")
    done = chat(engine, elder, session, "确认办理")
    assert done.code == ResponseCode.TASK_COMPLETED
