from __future__ import annotations

import json

import pytest

from youhuo.database import IdempotencyConflict
from youhuo.models import ChatRequest, FamilyApprovalRequest
from .helpers import chat, confirm_bill


def test_chat_idempotency_same_payload(env):
    db, engine, elder, family, session = env
    req = ChatRequest(session_id=session.session_id, text="帮我交水费", request_id="same-1")
    a = engine.handle(elder, req)
    b = engine.handle(elder, req)
    assert a.model_dump() == b.model_dump()
    assert len(db.list_tasks("fam-demo")) == 1


def test_chat_idempotency_conflict(env):
    db, engine, elder, family, session = env
    engine.handle(elder, ChatRequest(session_id=session.session_id, text="帮我交水费", request_id="same-2"))
    with pytest.raises(IdempotencyConflict):
        engine.handle(elder, ChatRequest(session_id=session.session_id, text="帮我交电费", request_id="same-2"))


def test_request_id_is_scoped_by_actor_and_session(env):
    db, engine, elder, family, session = env
    a = engine.handle(elder, ChatRequest(session_id=session.session_id, text="帮我交水费", request_id="shared"))
    # A separate session may reuse the same client-generated request id safely.
    from youhuo.models import SessionCreateRequest
    session2 = engine.create_session(elder, SessionCreateRequest())
    b = engine.handle(elder, ChatRequest(session_id=session2.session_id, text="帮我交电费", request_id="shared"))
    assert a.task_id != b.task_id


def test_approval_idempotency(env):
    db, engine, elder, family, session = env
    asked = chat(engine, elder, session, "帮我交水费")
    pending = confirm_bill(engine, elder, session, asked.message)
    req = FamilyApprovalRequest(
        task_id=pending.task_id, approve=True, approval_digest=pending.approval_digest, request_id="approve-once"
    )
    a = engine.approve(family, req)
    b = engine.approve(family, req)
    assert a.model_dump() == b.model_dump()


def test_audit_chain_valid(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    assert db.verify_audit_chain("fam-demo")


def test_audit_tamper_detected(env):
    db, engine, elder, family, session = env
    chat(engine, elder, session, "帮我交水费")
    row = db._conn.execute("SELECT id,payload_json FROM audit_events WHERE family_id=? ORDER BY id DESC LIMIT 1", ("fam-demo",)).fetchone()
    payload = json.loads(row["payload_json"]); payload["risk"] = 999
    db._conn.execute("UPDATE audit_events SET payload_json=? WHERE id=?", (json.dumps(payload), row["id"]))
    assert not db.verify_audit_chain("fam-demo")


def test_audit_all_events_not_first_100k(tmp_path):
    from youhuo.database import Database
    db = Database(tmp_path / "chain.db")
    with db.transaction() as conn:
        conn.execute("INSERT INTO families(id,display_name) VALUES ('f','F')")
        conn.execute("INSERT INTO actors(id,family_id,role,display_name) VALUES ('a','f','system','S')")
    for i in range(1005):
        db.append_audit("f", "a", "E", str(i), {"i": i})
    assert db.verify_audit_chain("f")
    db._conn.execute("UPDATE audit_events SET payload_json='{}' WHERE family_id='f' AND id=(SELECT MAX(id) FROM audit_events)")
    assert not db.verify_audit_chain("f")
    db.close()
