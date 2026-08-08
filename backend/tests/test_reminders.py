from __future__ import annotations

from datetime import timedelta

import pytest

from youhuo.engine import AuthorizationError
from youhuo.models import FamilyReminderCreateRequest, ReminderStatus


def test_family_create_reminder(env, fixed_now):
    db, engine, elder, family, session = env
    response = engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(elder_id=elder.actor_id, title="准备病历", due_at=fixed_now + timedelta(hours=1)),
    )
    assert response.code.value == "task_completed"
    reminder = db.list_reminders("fam-demo")[0]
    assert reminder.source == "family_app"


def test_elder_cannot_create_family_reminder(env, fixed_now):
    db, engine, elder, family, session = env
    with pytest.raises(AuthorizationError):
        engine.create_family_reminder(
            elder,
            FamilyReminderCreateRequest(elder_id=elder.actor_id, title="准备病历", due_at=fixed_now + timedelta(hours=1)),
        )


def test_scheduler_notifies_then_escalates(env, fixed_now):
    db, engine, elder, family, session = env
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(
            elder_id=elder.actor_id, title="复诊", due_at=fixed_now - timedelta(minutes=31), escalation_after_minutes=30
        ),
    )
    first = engine.scheduler_tick(family, fixed_now - timedelta(minutes=30))
    assert first["notified"] == 1
    second = engine.scheduler_tick(family, fixed_now)
    assert second["escalated"] == 1
    reminder = db.list_reminders("fam-demo")[0]
    assert reminder.status == ReminderStatus.ESCALATED


def test_scheduler_is_idempotent(env, fixed_now):
    db, engine, elder, family, session = env
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(elder_id=elder.actor_id, title="吃药", due_at=fixed_now - timedelta(minutes=60), escalation_after_minutes=30),
    )
    engine.scheduler_tick(family, fixed_now - timedelta(minutes=59))
    engine.scheduler_tick(family, fixed_now)
    again = engine.scheduler_tick(family, fixed_now + timedelta(hours=1))
    assert again == {"notified": 0, "escalated": 0, "advance_notified": 0}


def test_reminder_acknowledge_and_complete(env, fixed_now):
    db, engine, elder, family, session = env
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(elder_id=elder.actor_id, title="吃药", due_at=fixed_now),
    )
    reminder = db.list_reminders("fam-demo")[0]
    ack = engine.reminder_action(elder, reminder.id, "acknowledge", "ack1")
    assert ack.code.value == "ok"
    done = engine.reminder_action(elder, reminder.id, "complete", "done1")
    assert done.code.value == "task_completed"
    assert db.get_reminder(reminder.id).status == ReminderStatus.COMPLETED


def test_completed_reminder_not_escalated(env, fixed_now):
    db, engine, elder, family, session = env
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(elder_id=elder.actor_id, title="吃药", due_at=fixed_now - timedelta(hours=2)),
    )
    reminder = db.list_reminders("fam-demo")[0]
    engine.reminder_action(elder, reminder.id, "complete", None)
    result = engine.scheduler_tick(family, fixed_now)
    assert result == {"notified": 0, "escalated": 0, "advance_notified": 0}


def test_family_scheduler_is_scoped_to_own_family(env, fixed_now):
    db, engine, elder, family, session = env
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
    engine.create_family_reminder(
        family,
        FamilyReminderCreateRequest(elder_id=elder.actor_id, title="本家庭提醒", due_at=fixed_now),
    )
    engine.create_family_reminder(
        other_family,
        FamilyReminderCreateRequest(elder_id="other-elder", title="另一家庭提醒", due_at=fixed_now),
    )
    result = engine.scheduler_tick(family, fixed_now)
    assert result == {"notified": 1, "escalated": 0, "advance_notified": 0}
    assert db.list_reminders("fam-demo")[0].status == ReminderStatus.NOTIFIED
    assert db.list_reminders("fam-other")[0].status == ReminderStatus.SCHEDULED
