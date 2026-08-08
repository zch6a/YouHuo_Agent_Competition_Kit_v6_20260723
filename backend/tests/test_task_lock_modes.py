from __future__ import annotations

from .helpers import chat


def test_task_lock_defers_chitchat(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "帮我交水费")
    locked = chat(engine, elder, session, "对了，我孙子昨天给我打电话了")
    assert "暂存" in locked.message
    task = db.get_task(first.task_id)
    assert task.deferred_topics


def test_deferred_topic_restored_after_completion(env):
    db, engine, elder, family, session = env
    first = chat(engine, elder, session, "提醒我明天上午九点复诊")
    locked = chat(engine, elder, session, "我孙子最近放暑假了")
    final = chat(engine, elder, session, "确认")
    assert "刚才" in final.message and "孙子" in final.message


def test_cannot_switch_companion_during_active_task(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    response = chat(engine, elder, session, "调用无忧伴")
    assert "没有办完" in response.message


def test_switch_to_companion_and_back(env):
    db, engine, elder, family, session = env
    a = chat(engine, elder, session, "调用无忧伴")
    assert a.mode.value == "companion"
    b = chat(engine, elder, session, "我想孙子了")
    assert b.code.value == "chat"
    c = chat(engine, elder, session, "调用优活")
    assert c.mode.value == "youhuo"


def test_task_request_in_companion_switches_to_youhuo(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "调用无忧伴")
    response = chat(engine, elder, session, "帮我交水费")
    assert response.mode.value == "youhuo"
    assert response.task_id


def test_companion_chat_not_written_to_task_audit_payload(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "调用无忧伴")
    private_story = "我和孙子聊一个非常私密的家庭故事"
    chat(engine, elder, session, private_story)
    serialized = "\n".join(str(e.payload) for e in db.list_audit("fam-demo", 100))
    assert private_story not in serialized
