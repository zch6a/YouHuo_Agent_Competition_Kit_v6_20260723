"""跌倒识别：主链曾经是最严的一层。

`v5_services._EMERGENCY_TERMS` and `v6_services` both treated a bare 摔倒 as
urgent, but the chat chain — the one surface an elder actually talks to —
required "起不来" to follow it. "我摔倒了" therefore got the errand menu.

Widening it is only safe if the guards hold: an elder recounting an old fall or
worrying about a future one must not page the family.
"""

from __future__ import annotations

import pytest

from youhuo.security import SafetyPolicy

from .helpers import chat


def _is_emergency(text: str) -> bool:
    signal = SafetyPolicy.detect_safety_signal(text)
    return signal is not None and signal.category == "emergency"


@pytest.mark.parametrize(
    "text",
    [
        "我摔倒了",
        "我摔了",
        "我跌倒了",
        "我刚摔了一跤",
        "我在厕所滑倒了",
        "我绊倒了，腿很疼",
        "我摔着腰了",
        "我站不起来了",
        "我摔倒了起不来",
        # An old fall mentioned alongside a fresh one is still a fresh one.
        "刚才摔倒了，上个月也摔过",
    ],
)
def test_present_fall_is_an_emergency(text):
    assert _is_emergency(text), text


@pytest.mark.parametrize(
    "text",
    [
        "我上个月摔倒过",
        "上次摔倒以后我就很小心",
        "去年摔倒住了院，现在好利索了",
        "我年轻时摔过一次",
        "我怕摔倒",
        "我担心晚上起夜会摔倒",
        "小心别摔倒",
        "浴室要装扶手，万一摔倒了不好",
    ],
)
def test_remembered_or_feared_falls_do_not_page_family(text):
    assert not _is_emergency(text), text


@pytest.mark.parametrize("text", ["帮我交水费", "我想我老伴了", "今天天气不错", "提醒我明天吃药"])
def test_ordinary_turns_are_untouched(text):
    assert not _is_emergency(text), text


def test_chat_chain_raises_a_safety_alert_and_notifies_family(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "我摔倒了")
    assert response.code.value == "safety_alert"
    assert "摔倒" in response.message
    events = [e.event_type for e in db.list_audit("fam-demo", 50)]
    assert "SAFETY_SIGNAL" in events


def test_fall_alert_beats_the_task_lock(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    # A fall mid-errand must not be parked as chitchat.
    response = chat(engine, elder, session, "我摔倒了")
    assert response.code.value == "safety_alert"


def test_the_reply_does_not_tell_the_elder_to_stand_up(env):
    db, engine, elder, family, session = env
    message = chat(engine, elder, session, "我摔倒了").message
    assert "先别急着站起来" in message
    assert "急救" in message
