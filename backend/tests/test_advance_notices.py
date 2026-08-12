"""Design §5.3: T-24h / T-12h / T-1h advance-notice ladder before the due time."""

from __future__ import annotations

from datetime import timedelta

from youhuo.models import ActorRole, FamilyReminderCreateRequest, ReminderStatus
from youhuo.services import SchedulerService


def _create(engine, family, elder, fixed_now, hours_ahead: float, title: str = "复诊"):
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(
            elder_id=elder.actor_id, title=title, due_at=fixed_now + timedelta(hours=hours_ahead)
        ),
    )


def _advance_messages(db):
    """Advance-notice texts in the order the elder received them."""
    return [
        item.message
        for item in reversed(db.list_notifications("fam-demo", ActorRole.ELDER, limit=100))
        if item.event_type == "reminder_advance_notice"
    ]


def test_ladder_fires_once_per_rung_as_due_time_approaches(env, fixed_now):
    db, engine, elder, family, _ = env
    _create(engine, family, elder, fixed_now, hours_ahead=30)

    # Still outside the 24h horizon: nothing fires.
    assert engine.scheduler_tick(family, fixed_now)["advance_notified"] == 0

    at_24 = engine.scheduler_tick(family, fixed_now + timedelta(hours=6))
    assert at_24["advance_notified"] == 1
    at_12 = engine.scheduler_tick(family, fixed_now + timedelta(hours=18))
    assert at_12["advance_notified"] == 1
    at_1 = engine.scheduler_tick(family, fixed_now + timedelta(hours=29))
    assert at_1["advance_notified"] == 1

    # Each notice states the real remaining time at the moment it was sent.
    assert _advance_messages(db) == [
        "提前提醒:还有约24小时就到「复诊」了。",
        "提前提醒:还有约12小时就到「复诊」了。",
        "提前提醒:还有约1小时就到「复诊」了。",
    ]


def test_notice_states_real_remaining_time_not_the_rung_name(env, fixed_now):
    """A reminder created only 3 hours out consumes the 24h/12h rungs silently."""
    db, engine, elder, family, _ = env
    _create(engine, family, elder, fixed_now, hours_ahead=3)
    assert engine.scheduler_tick(family, fixed_now)["advance_notified"] == 1
    assert _advance_messages(db) == ["提前提醒:还有约3小时就到「复诊」了。"]


def test_ladder_is_idempotent_across_repeated_ticks(env, fixed_now):
    db, engine, elder, family, _ = env
    _create(engine, family, elder, fixed_now, hours_ahead=30)
    later = fixed_now + timedelta(hours=6)
    first = engine.scheduler_tick(family, later)
    repeat = engine.scheduler_tick(family, later)
    assert first["advance_notified"] == 1
    assert repeat["advance_notified"] == 0
    assert len(_advance_messages(db)) == 1


def test_late_first_tick_announces_the_real_remaining_time(env, fixed_now):
    """An offline gap must not replay stale "还有24小时" text half an hour before the event."""
    db, engine, elder, family, _ = env
    _create(engine, family, elder, fixed_now, hours_ahead=30)
    result = engine.scheduler_tick(family, fixed_now + timedelta(hours=29, minutes=30))
    assert result["advance_notified"] == 1
    # The notification pipeline normalises the fullwidth colon to ASCII.
    messages = _advance_messages(db)
    assert messages == ["提前提醒:还有约30分钟就到「复诊」了。"]
    # All three rungs are consumed, so nothing replays later.
    reminder = db.list_reminders("fam-demo")[0]
    assert sorted(db.sent_advance_notices(reminder.id)) == [60, 720, 1440]
    assert engine.scheduler_tick(family, fixed_now + timedelta(hours=29, minutes=45))["advance_notified"] == 0


def test_completed_reminder_stops_the_ladder(env, fixed_now):
    db, engine, elder, family, _ = env
    _create(engine, family, elder, fixed_now, hours_ahead=30)
    reminder = db.list_reminders("fam-demo")[0]
    engine.reminder_action(elder, reminder.id, "complete", None)
    assert engine.scheduler_tick(family, fixed_now + timedelta(hours=29))["advance_notified"] == 0
    assert db.get_reminder(reminder.id).status == ReminderStatus.COMPLETED


def test_advance_ladder_is_scoped_to_the_requesting_family(env, fixed_now):
    db, engine, elder, family, _ = env
    with db.transaction() as conn:
        conn.execute("INSERT INTO families(id,display_name) VALUES (?,?)", ("fam-other", "另一家庭"))
        conn.execute(
            "INSERT INTO actors(id,family_id,role,display_name) VALUES (?,?,?,?)",
            ("other-elder", "fam-other", "elder", "另一老人"),
        )
        conn.execute(
            "INSERT INTO actors(id,family_id,role,display_name) VALUES (?,?,?,?)",
            ("other-family", "fam-other", "family", "另一家属"),
        )
    other_family = db.auth_context_for_actor("other-family")
    assert other_family is not None
    _create(engine, family, elder, fixed_now, hours_ahead=20, title="本家庭复诊")
    engine.create_family_reminder(
        other_family,
        FamilyReminderCreateRequest(
            elder_id="other-elder", title="另一家庭复诊", due_at=fixed_now + timedelta(hours=20)
        ),
    )
    assert engine.scheduler_tick(family, fixed_now)["advance_notified"] == 1
    assert not _advance_messages(db)[0].startswith("另一家庭")
    assert len(db.sent_advance_notices(db.list_reminders("fam-other")[0].id)) == 0


def test_lead_times_match_the_design_brief():
    assert SchedulerService.ADVANCE_LEAD_MINUTES == (24 * 60, 12 * 60, 60)
