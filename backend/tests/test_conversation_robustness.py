"""多轮对话稳健性：老人不会照着演示脚本说话。

Every case here came from driving a live engine with utterances a real elder
would produce — acknowledgements, corrections, dialect, second thoughts — and
reading what came back. The worst find was silent data corruption: any word the
engine did not recognise while awaiting confirmation was poured into the task's
free-text slot, so "谢谢" became the reminder's title.
"""

from __future__ import annotations

import pytest

from youhuo.models import ReminderStatus, ResponseCode, TaskType

from .helpers import chat, confirm_bill


# --- an unrecognised reply must never rewrite the task --------------------


@pytest.mark.parametrize("acknowledgement", ["嗯", "中", "行", "对", "成", "好"])
def test_bare_acknowledgements_confirm_a_low_risk_task(env, acknowledgement):
    """"中" is a yes in much of northern China; "嗯" is the default everywhere."""
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    response = chat(engine, elder, session, acknowledgement)
    assert response.code == ResponseCode.TASK_COMPLETED
    reminders = db.list_reminders("fam-demo")
    assert [r.title for r in reminders] == ["复诊"]


@pytest.mark.parametrize("noise", ["谢谢", "你在干什么", "今天天气真好啊"])
def test_unparsed_reply_does_not_overwrite_the_title(env, noise):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    response = chat(engine, elder, session, noise)
    task = db.get_task(response.task_id)
    assert task.slots["title"] == "复诊"


def test_unparsed_reply_reads_the_task_back_instead_of_repeating(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    response = chat(engine, elder, session, "你在干什么")
    assert response.data.get("unparsed_confirmation_reply") is True
    assert "复诊" in response.message
    assert "取消任务" in response.message


def test_a_real_correction_at_confirmation_is_applied(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    response = chat(engine, elder, session, "改成下午三点")
    task = db.get_task(response.task_id)
    assert task.slots["due_time"] == "15:00"
    assert task.slots["title"] == "复诊"  # the content survived the time change


def test_retitling_replaces_only_the_content(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    response = chat(engine, elder, session, "不是复诊，是取药")
    task = db.get_task(response.task_id)
    assert task.slots["title"] == "取药"
    assert task.slots["due_time"] == "09:00"  # the time survived the retitle


def test_acknowledgement_still_cannot_settle_a_bill(env):
    """Teach-back is the gate for money; widening 'yes' must not open it."""
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    response = chat(engine, elder, session, "嗯")
    assert response.code == ResponseCode.NEED_ELDER_CONFIRMATION
    assert response.data.get("teach_back") == "not_restated"


def test_teach_back_still_settles_a_bill(env):
    db, engine, elder, family, session = env
    prompt = chat(engine, elder, session, "帮我交水费")
    response = confirm_bill(engine, elder, session, prompt.message)
    assert response.code != ResponseCode.NEED_ELDER_CONFIRMATION


# --- corrections are acknowledged out loud --------------------------------


def test_correction_is_read_back(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我挂明天上午十点第一医院内科的号")
    response = chat(engine, elder, session, "不对，我要后天")
    assert "改成" in response.message
    task = db.get_task(response.task_id)
    assert task.slots["appointment_date"] == "2026-07-24"


def test_chitchat_mentioning_a_day_does_not_move_the_appointment(env):
    """"今天天气真好" parses as a date. It is not an answer to anything."""
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "帮我挂明天上午十点第一医院内科的号")
    before = db.get_task(first.task_id).slots["appointment_date"]
    chat(engine, elder, session, "今天天气真好")
    assert db.get_task(first.task_id).slots["appointment_date"] == before


def test_chitchat_that_also_answers_is_still_an_answer(env):
    """Only incidental date/time scraping is discarded, not a real slot value."""
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "我膝盖疼，帮我挂号")
    chat(engine, elder, session, "第一医院吧，我孙子说那儿好")
    assert db.get_task(first.task_id).slots["hospital"] == "第一医院"


# --- dead ends ------------------------------------------------------------


def test_confirming_an_incomplete_task_says_what_is_missing(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我挂明天上午十点第一医院内科的号")
    response = chat(engine, elder, session, "确认办理")
    assert "还差一项" in response.message


def test_not_knowing_is_answered_with_help_not_the_same_question(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "我膝盖疼，帮我挂号")
    plain = chat(engine, elder, session, "第一医院吧")
    assert "没关系" not in plain.message

    db2, engine2, elder2, family2, session2 = env
    chat(engine2, elder2, session2, "我要挂号")
    response = chat(engine2, elder2, session2, "我不知道")
    assert "没关系" in response.message
    assert "先选第一个" in response.message


# --- undo -----------------------------------------------------------------


def test_cancelling_the_reminder_just_created(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "确认办理")
    response = chat(engine, elder, session, "算了，不要了")
    assert response.code == ResponseCode.TASK_COMPLETED
    assert "取消" in response.message
    assert db.list_reminders("fam-demo")[0].status == ReminderStatus.CANCELLED


def test_the_undo_window_is_one_turn(env):
    """"算了" much later is about something else; cancelling then is silent harm."""
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "确认办理")
    chat(engine, elder, session, "今天几号")
    chat(engine, elder, session, "算了，不要了")
    assert db.list_reminders("fam-demo")[0].status != ReminderStatus.CANCELLED


def test_cancel_by_name_does_not_create_a_new_reminder(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "确认办理")
    chat(engine, elder, session, "今天几号")  # consume the one-turn undo window
    response = chat(engine, elder, session, "把刚才那个提醒取消掉")
    assert response.code == ResponseCode.TASK_COMPLETED
    assert "复诊" in response.message
    assert db.list_reminders("fam-demo")[0].status == ReminderStatus.CANCELLED


def test_ambiguous_cancel_lists_instead_of_guessing(env):
    db, engine, elder, family, session = env
    for spoken in ("提醒我明天上午九点复诊", "提醒我后天下午三点取药"):
        chat(engine, elder, session, spoken)
        chat(engine, elder, session, "确认办理")
        chat(engine, elder, session, "今天几号")
    response = chat(engine, elder, session, "把提醒取消掉")
    assert response.code == ResponseCode.NEED_MORE_INFO
    assert response.data["pending_reminders"] == 2
    assert all(r.status != ReminderStatus.CANCELLED for r in db.list_reminders("fam-demo"))


def test_cancel_with_nothing_pending_is_graceful(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "把提醒取消掉")
    assert "没有待办提醒" in response.message


# --- a second errand in the same breath -----------------------------------


def test_second_errand_is_remembered_and_offered(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "帮我挂明天下午两点第一医院骨科王医生的号，顺便把水费也交了")
    assert first.data["pending_errand"] == "缴费"
    done = chat(engine, elder, session, "确认办理")
    assert done.data.get("errand_offer") is True
    taken_up = chat(engine, elder, session, "好")
    assert taken_up.task_id is not None
    assert db.get_task(taken_up.task_id).task_type == TaskType.BILL_PAYMENT


def test_declining_the_second_errand_drops_it(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我挂明天下午两点第一医院骨科王医生的号，顺便把水费也交了")
    chat(engine, elder, session, "确认办理")
    declined = chat(engine, elder, session, "不用了")
    assert declined.task_id is None
    assert "先放着" in declined.message


def test_one_errand_is_not_split_into_two(env):
    """"提醒我明天交水费" is a reminder, not a reminder plus a payment."""
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "提醒我明天上午九点交水费")
    assert response.data.get("pending_errand") is None


# --- what the elder actually reads on screen ------------------------------


def test_chinese_punctuation_survives_the_adaptation_pass():
    """NFKC turned every ，into a halfwidth comma in the text shown to the elder."""
    from youhuo.utils import restore_cjk_punctuation

    assert restore_cjk_punctuation("用药计划,所以查不到") == "用药计划，所以查不到"
    assert restore_cjk_punctuation("要登记的话,可以让家人添加") == "要登记的话，可以让家人添加"
    # ASCII inside values must stay ASCII: speech.js matches times and amounts
    # by regex and would miss "08：00".
    assert restore_cjk_punctuation("时间是08:00、12:00") == "时间是08:00、12:00"
    assert restore_cjk_punctuation("126.50元") == "126.50元"


def test_adapted_message_keeps_full_width_commas_and_ends_in_a_period(env):
    from youhuo.v6_models import InteractionPlanRequest
    from youhuo.v6_services import CognitiveLoadGovernor
    from youhuo.v6_store import V6FeatureStore

    db, engine, elder, family, session = env
    profile = V6FeatureStore(db).get_profile("fam-demo", "elder-demo")
    plan = CognitiveLoadGovernor.plan(
        profile,
        InteractionPlanRequest(
            elder_id="elder-demo",
            message="您现在没有登记在册的用药计划，所以我这边查不到今天该吃什么药。",
            risk_level=1,
        ),
    )
    assert "，" in plan.visual_text
    assert "," not in plan.visual_text
    assert plan.visual_text.endswith("。")
