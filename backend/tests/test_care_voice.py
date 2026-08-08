"""语音可达层：次要模式能不能真的用嘴问出来。

Before this layer, 15 of 20 natural elderly utterances hit the same fallback
line — the medication, health, contact and accessibility features existed only
as REST endpoints. These tests pin the reachability and, more importantly, the
boundaries: the errand classifier still wins, nothing here writes care data,
and no answer makes a clinical claim.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from youhuo import care_voice
from youhuo.care_voice import CareIntent
from youhuo.models import ActorRole
from youhuo.v4_models import (
    ContactCreate,
    DoseRecordRequest,
    HealthEventCreate,
    HealthEventKind,
    MedicationPlanCreate,
)
from youhuo.v4_store import V4FeatureStore

from .helpers import chat


@pytest.fixture
def care_env(env, fixed_now):
    """The demo family plus two medication plans, a vital sign and a contact."""
    db, engine, elder, family, session = env
    store = V4FeatureStore(db)
    store.seed_demo()
    plan = store.create_medication_plan(
        "fam-demo",
        MedicationPlanCreate(
            elder_id="elder-demo", display_name="苯磺酸氨氯地平", normalized_name="amlodipine",
            dose_text="每次1片", times_local=["08:00", "20:00"], start_date=date(2026, 7, 1),
            stock_units=9, units_per_dose=1,
        ),
        ActorRole.ELDER,
    )
    store.create_medication_plan(
        "fam-demo",
        MedicationPlanCreate(
            elder_id="elder-demo", display_name="二甲双胍", normalized_name="metformin",
            dose_text="每次2片", times_local=["12:00"], start_date=date(2026, 7, 1),
            stock_units=60, units_per_dose=2,
        ),
        ActorRole.ELDER,
    )
    store.create_health_event("fam-demo", HealthEventCreate(
        elder_id="elder-demo", kind=HealthEventKind.CHECKUP, title="社区量血压",
        event_at=fixed_now - timedelta(days=1), payload={"收缩压": 148, "舒张压": 86},
    ))
    store.create_contact("fam-demo", "daughter-demo", ContactCreate(
        elder_id="elder-demo", display_name="李慧", relation="女儿",
        phone="13900001111", notes="住在同城",
    ), ActorRole.FAMILY)
    return db, engine, elder, family, session, store, plan


# --- classification boundaries -------------------------------------------


def test_reminder_still_beats_medication_query():
    """The whole layer is only consulted when the errand classifier found nothing."""
    from youhuo.engine import YouHuoEngine

    assert YouHuoEngine._classify_task("明天九点提醒我吃药") is not None
    assert YouHuoEngine._classify_task("我今天吃药了吗") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我今天吃药了吗", CareIntent.MEDICATION_TODAY),
        ("药吃了没", CareIntent.MEDICATION_TODAY),
        ("我的降压药还剩几片", CareIntent.MEDICATION_STOCK),
        ("二甲双胍还够吃吗", CareIntent.MEDICATION_STOCK),
        ("我每天都吃什么药", CareIntent.MEDICATION_LIST),
        ("我血压怎么样", CareIntent.HEALTH_RECENT),
        ("上次量的血压是多少", CareIntent.HEALTH_RECENT),
        ("我今天有什么事", CareIntent.SCHEDULE_TODAY),
        ("给我女儿打个电话", CareIntent.CONTACT_REACH),
        ("你能干什么", CareIntent.CAPABILITY_HELP),
        ("你说慢点", CareIntent.SPEAK_SLOWER),
        ("我听不清", CareIntent.HEARING_SUPPORT),
        ("再说一遍", CareIntent.REPEAT),
        ("今天几号", CareIntent.ORIENTATION),
        ("现在几点了", CareIntent.ORIENTATION),
        ("我头有点晕", CareIntent.SYMPTOM_MENTION),
        ("这两天腰疼", CareIntent.SYMPTOM_MENTION),
    ],
)
def test_classify(text, expected):
    assert care_voice.classify(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "帮我交水费", "我想我老伴了", "今天天气不错", "调用无忧伴", "确认办理",
        "我孙子昨天来电话了",
        # Talking *about* speed, not asking us to change ours.
        "医生说快点去医院",
        "他说话太快我记不住",
        # Comprehension, not hearing, and about someone else.
        "我听不懂医生说的",
    ],
)
def test_classify_leaves_other_traffic_alone(text):
    assert care_voice.classify(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你说得太快了", CareIntent.SPEAK_SLOWER),
        ("说慢点", CareIntent.SPEAK_SLOWER),
        ("慢一点说", CareIntent.SPEAK_SLOWER),
        ("你说太慢了", CareIntent.SPEAK_FASTER),
        # "你说快点" is an instruction to speed up; "你说快了" is a complaint that
        # we already are. Both start 你说快.
        ("你说快点", CareIntent.SPEAK_FASTER),
        ("你说快了", CareIntent.SPEAK_SLOWER),
        ("你说慢了", CareIntent.SPEAK_FASTER),
    ],
)
def test_speech_rate_phrasings(text, expected):
    assert care_voice.classify(text) is expected


# --- answers come from authoritative state -------------------------------


def test_medication_today_counts_real_doses(care_env):
    db, engine, elder, family, session, store, plan = care_env
    response = chat(engine, elder, session, "我今天吃药了吗")
    assert response.data["care_intent"] == CareIntent.MEDICATION_TODAY.value
    assert response.data["planned_doses"] == 3  # 2 + 1 scheduled times
    assert response.data["recorded_taken"] == 0
    # Never assert the elder did not take it — only that nothing was recorded.
    assert "记录" in response.message


def test_medication_today_reflects_a_recorded_dose(care_env):
    db, engine, elder, family, session, store, plan = care_env
    store.record_dose("fam-demo", "elder-demo", plan.id, DoseRecordRequest(
        scheduled_at=datetime(2026, 7, 22, 0, 0, tzinfo=UTC), status="taken",
    ))
    response = chat(engine, elder, session, "我今天吃药了吗")
    assert response.data["recorded_taken"] == 1


def test_stock_answer_leads_with_the_urgent_drug(care_env):
    db, engine, elder, family, session, store, plan = care_env
    message = chat(engine, elder, session, "我的药还够吃吗").message
    # 氨氯地平 runs out in ~4 days, 二甲双胍 in ~30. The elder may stop listening
    # after the first clause, so the urgent one must come first.
    assert message.index("氨氯地平") < message.index("二甲双胍")


def test_stock_narrows_to_the_drug_the_elder_named(care_env):
    db, engine, elder, family, session, store, plan = care_env
    response = chat(engine, elder, session, "氨氯地平还剩几片")
    assert response.data["narrowed_by_name"] is True
    assert "二甲双胍" not in response.message


def test_unresolvable_drug_class_is_admitted_not_guessed(care_env):
    db, engine, elder, family, session, store, plan = care_env
    response = chat(engine, elder, session, "我的降压药还剩几片")
    # There is no drug-class table, so the system must widen the answer and say
    # why rather than assert which pill is the antihypertensive.
    assert response.data["unresolved_class_term"] is True
    assert response.data["narrowed_by_name"] is False
    assert "分不出" in response.message


def test_health_answer_reads_the_record_without_interpreting_it(care_env):
    db, engine, elder, family, session, store, plan = care_env
    message = chat(engine, elder, session, "我血压怎么样").message
    assert "148" in message
    assert "不做判断" in message
    for clinical in ("正常", "偏高", "建议吃", "危险", "没问题"):
        assert clinical not in message


def test_contact_answer_does_not_claim_to_place_a_call(care_env):
    db, engine, elder, family, session, store, plan = care_env
    message = chat(engine, elder, session, "给我女儿打个电话").message
    assert "李慧" in message
    assert "不能替您拨号" in message


def test_schedule_reads_real_reminders(care_env):
    db, engine, elder, family, session, store, plan = care_env
    chat(engine, elder, session, "提醒我明天上午九点复诊")
    chat(engine, elder, session, "确认办理")
    response = chat(engine, elder, session, "我今天有什么事")
    assert response.data["count"] == 1
    assert "复诊" in response.message


def test_empty_state_says_so_instead_of_inventing(env):
    db, engine, elder, family, session = env
    for text in ("我今天吃药了吗", "我血压怎么样", "给我女儿打个电话"):
        message = chat(engine, elder, session, text).message
        assert "没有" in message or "还没有" in message


# --- accessibility is the elder's own call --------------------------------


def test_speak_slower_actually_moves_the_stored_profile(env):
    db, engine, elder, family, session = env
    before = engine.v6.get_profile("fam-demo", "elder-demo").speech_rate
    chat(engine, elder, session, "你说慢点")
    after = engine.v6.get_profile("fam-demo", "elder-demo").speech_rate
    assert after < before


def test_speech_rate_cannot_leave_the_contract_bounds(env):
    db, engine, elder, family, session = env
    for _ in range(12):
        chat(engine, elder, session, "你说慢点")
    assert engine.v6.get_profile("fam-demo", "elder-demo").speech_rate >= 0.6
    for _ in range(20):
        chat(engine, elder, session, "说太慢了")
    assert engine.v6.get_profile("fam-demo", "elder-demo").speech_rate <= 1.2


def test_hearing_support_shortens_sentences(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "我听不清")
    profile = engine.v6.get_profile("fam-demo", "elder-demo")
    assert profile.hearing_support is True
    assert profile.max_sentence_chars <= 24


def test_profile_change_is_visible_in_the_elders_own_log(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "你说慢点")
    events = [e.event_type for e in db.list_audit("fam-demo", 50)]
    assert "CARE_PROFILE_SPEECH_RATE" in events


def test_repeat_says_the_previous_line_again(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "你能干什么").message
    repeated = chat(engine, elder, session, "再说一遍").message
    assert first in repeated
    # Repeating a repeat must not nest the prefix.
    again = chat(engine, elder, session, "再说一遍").message
    assert again.count("我再说一遍：") == 1


def test_repeat_with_no_history_is_graceful(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "再说一遍")
    assert response.data["had_previous"] is False


# --- the layer must not weaken the trust core -----------------------------


def test_care_queries_never_create_a_task(care_env):
    db, engine, elder, family, session, store, plan = care_env
    for text in ("我今天吃药了吗", "我血压怎么样", "我今天有什么事", "你说慢点"):
        response = chat(engine, elder, session, text)
        assert response.task_id is None
        assert session.active_task_id is None


def test_care_query_cannot_interrupt_an_active_task(care_env):
    db, engine, elder, family, session, store, plan = care_env
    first = chat(engine, elder, session, "帮我交水费")
    assert first.task_id
    during = chat(engine, elder, session, "我今天吃药了吗")
    # The rigid task lock still owns the turn; the care layer sits behind it.
    assert during.data.get("care_intent") is None
    assert db.get_session(session.session_id).active_task_id == first.task_id


def test_orientation_answers_from_the_clock(env, fixed_now):
    db, engine, elder, family, session = env
    message = chat(engine, elder, session, "今天几号").message
    assert f"{fixed_now.month}月{fixed_now.day}日" in message
    assert "星期" in message


def test_bare_symptom_offers_instead_of_booking(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "我膝盖疼")
    # An ache is not a request to book anything.
    assert response.task_id is None
    assert response.data["care_intent"] == CareIntent.SYMPTOM_MENTION.value
    assert "帮我挂号" in response.message


def test_symptom_plus_intent_still_books(env):
    db, engine, elder, family, session = env
    response = chat(engine, elder, session, "我膝盖疼，帮我挂号")
    assert response.task_id is not None


def test_symptom_answer_gives_no_clinical_advice(env):
    db, engine, elder, family, session = env
    message = chat(engine, elder, session, "我头有点晕").message
    assert "不能看病" in message
    assert "急救" in message  # names the red flags without diagnosing
    for advice in ("吃点", "多喝", "量一下血压", "可能是", "应该是"):
        assert advice not in message


def test_symptom_in_companion_mode_gets_the_companion_reply(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "调用无忧伴")
    response = chat(engine, elder, session, "这两天腰疼得厉害")
    # A disclosure while chatting must not be answered with a service boundary.
    assert response.data.get("care_intent") is None
    assert "不能看病" not in response.message


def test_care_layer_writes_no_medication_data(care_env):
    db, engine, elder, family, session, store, plan = care_env
    before = store.medication_adherence("fam-demo", "elder-demo", date(2026, 7, 22), date(2026, 7, 22))
    for text in ("我今天吃药了吗", "我的药还够吃吗", "我都吃什么药"):
        chat(engine, elder, session, text)
    after = store.medication_adherence("fam-demo", "elder-demo", date(2026, 7, 22), date(2026, 7, 22))
    assert before == after
