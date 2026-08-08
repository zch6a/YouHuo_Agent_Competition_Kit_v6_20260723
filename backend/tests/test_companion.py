"""无忧伴 (companion mode) continuity.

Three defects motivated these tests, all reproduced against a live server:

1. Three consecutive disclosures — "我想我老伴了" / "他走了三年了" /
   "我今天一个人在家很没意思" — were answered with the identical sentence.
2. "我想找个人说说话" did not switch modes at all.
3. After parking a topic, the agent offered "要不要接着聊", and then answered
   "好啊" with the errand menu.
"""

from __future__ import annotations

from youhuo import companion
from youhuo.companion import CompanionContext, Theme

from .helpers import chat


# --- classification -------------------------------------------------------


def test_bereavement_wins_over_family_cue():
    # "老伴走了" contains no family word, but "我儿子走了" does not exist as a
    # phrase we want read as a cheerful family anecdote either. Order matters.
    assert companion.classify_theme("我想我老伴了") is Theme.BEREAVEMENT
    assert companion.classify_theme("他走了三年了") is Theme.BEREAVEMENT


def test_theme_classification_covers_each_label():
    cases = {
        "我孙子昨天来电话了": Theme.FAMILY,
        "我今天一个人在家很没意思": Theme.LONELY,
        "最近老是睡不着": Theme.SLEEP,
        "我年轻时在纺织厂干过": Theme.MEMORY,
        "这两天腰疼得厉害": Theme.BODY,
        "今天天气不错": Theme.DAILY,
        "嗯": Theme.OPEN,
    }
    for text, expected in cases.items():
        assert companion.classify_theme(text) is expected, text


def test_wants_companion_accepts_natural_phrasings():
    for text in ("调用无忧伴", "我想找个人说说话", "陪我聊聊天", "唠唠嗑"):
        assert companion.wants_companion(text), text
    assert not companion.wants_companion("帮我交水费")


# --- continuity -----------------------------------------------------------


def test_repeated_theme_gets_a_different_line():
    context = CompanionContext()
    first, _, _ = companion.compose_reply("我想我老伴了", context)
    second, _, _ = companion.compose_reply("他走了三年了", context)
    assert first != second


def test_three_disclosures_are_three_distinct_replies():
    context = CompanionContext()
    replies = [
        companion.compose_reply(text, context)[0]
        for text in ("我想我老伴了", "他走了三年了", "我今天一个人在家很没意思")
    ]
    assert len(set(replies)) == 3


def test_contact_suggestion_offered_once_and_is_declinable():
    context = CompanionContext()
    companion.compose_reply("我想我老伴了", context)
    second, _, offered = companion.compose_reply("他走了三年了", context)
    assert offered
    assert "您说不用也完全可以" in second
    # A heavy theme recurring again must not nag.
    _, _, offered_again = companion.compose_reply("老伴的忌日快到了", context)
    assert not offered_again


def test_context_stores_labels_not_utterances():
    context = CompanionContext()
    companion.compose_reply("我和孙子聊一个非常私密的家庭故事", context)
    serialized = str(context.snapshot()) + str(vars(context))
    assert "私密" not in serialized
    assert context.snapshot()["turns"] == 1


# --- resume offer ---------------------------------------------------------


def test_accept_and_decline_are_distinguished():
    assert companion.accepts_resume("好啊")
    assert not companion.accepts_resume("不用了")
    assert companion.declines_resume("先不聊了")
    # "不想说" contains no accept word but must never read as consent.
    assert not companion.accepts_resume("不想说")


# --- end to end through the engine ---------------------------------------


def test_parked_topic_is_actually_resumed(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "对了我孙子昨天来电话了")
    done = chat(engine, elder, session, "确认办理")
    assert "孙子" in done.message
    assert done.data.get("resume_offer") is True

    resumed = chat(engine, elder, session, "好啊")
    assert resumed.mode.value == "companion"
    assert resumed.data.get("resumed_topic") is True
    # It must open on the parked theme, not the generic errand menu.
    assert "帮我挂号" not in resumed.message


def test_declining_the_resume_offer_stays_in_youhuo(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "对了我孙子昨天来电话了")
    chat(engine, elder, session, "确认办理")

    declined = chat(engine, elder, session, "不用了")
    assert declined.mode.value == "youhuo"
    assert "无忧伴" in declined.message  # told how to come back


def test_resume_offer_is_consumed_after_one_turn(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "对了我孙子昨天来电话了")
    chat(engine, elder, session, "确认办理")

    # Elder moves on to a new errand instead of answering the offer.
    moved_on = chat(engine, elder, session, "帮我交水费")
    assert moved_on.task_id
    # A later "好啊" must not retroactively trigger the stale offer.
    after = chat(engine, elder, session, "好啊")
    assert after.data.get("resumed_topic") is not True


def test_engine_companion_replies_do_not_repeat(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "调用无忧伴")
    replies = [
        chat(engine, elder, session, text).message
        for text in ("我想我老伴了", "他走了三年了", "我今天一个人在家很没意思")
    ]
    assert len(set(replies)) == 3


def test_natural_phrasing_switches_to_companion(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "我想找个人说说话")
    assert response.mode.value == "companion"


def test_parked_topic_survives_a_duplicate_blocked_task(env):
    """The offer must not be tied to the task succeeding.

    An elder who books the same appointment twice, chatting in between, still
    raised a topic. Dropping it because the booking turned out to be a duplicate
    would silently break the promise for the one case where the elder is already
    mildly confused.
    """
    db, engine, elder, family, session = env
    for text in ("我膝盖疼，帮我挂号", "第一医院", "王医生", "明天", "下午两点", "确认办理"):
        chat(engine, elder, session, text)

    for text in ("我膝盖疼，帮我挂号", "第一医院", "王医生"):
        chat(engine, elder, session, text)
    parked = chat(engine, elder, session, "我孙子昨天来电话了")
    assert "暂存" in parked.message
    chat(engine, elder, session, "明天")
    blocked = chat(engine, elder, session, "下午两点")

    assert blocked.code.value == "duplicate_blocked"
    assert blocked.data.get("resume_offer") is True
    assert chat(engine, elder, session, "好啊").data.get("resumed_topic") is True


def test_in_memory_session_state_is_bounded(env):
    """Nothing persists or evicts this state, so the cap is the only bound."""
    from youhuo.engine import _SESSION_STATE_LIMIT, _remember

    store: dict[str, str] = {}
    for index in range(_SESSION_STATE_LIMIT + 50):
        _remember(store, f"session-{index}", "x")
    assert len(store) == _SESSION_STATE_LIMIT
    assert "session-0" not in store          # oldest evicted
    assert f"session-{_SESSION_STATE_LIMIT + 49}" in store

    # Touching a session keeps it alive.
    _remember(store, f"session-{_SESSION_STATE_LIMIT}", "x")
    for index in range(_SESSION_STATE_LIMIT + 50, _SESSION_STATE_LIMIT + 100):
        _remember(store, f"session-{index}", "x")
    assert f"session-{_SESSION_STATE_LIMIT}" in store


def test_resumed_topic_text_is_not_audited(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    aside = "对了我孙子昨天来电话了说他考上大学了"
    chat(engine, elder, session, aside)
    chat(engine, elder, session, "确认办理")
    chat(engine, elder, session, "好啊")
    serialized = "\n".join(str(e.payload) for e in db.list_audit("fam-demo", 200))
    assert "考上大学" not in serialized
