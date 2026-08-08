"""公开免登录部署：每个访客一份独立数据。

页面原先写死 `elder-demo`。在本机没问题，放到公网就错了：所有访客落进同一个
家庭，两个人同时看会互相看到对方的待办，也能改掉对方的任务。`/v2/auth/visitor`
给每个浏览器播种一个独立家庭；家庭隔离本来就按 family_id 强制执行，所以这是
真的沙箱而不是装饰。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.database import DemoIdentities


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "visitor.db", demo_mode=True))


def _visitor(client: TestClient) -> dict:
    response = client.post("/v2/auth/visitor")
    assert response.status_code == 200, response.text
    return response.json()


def _reminders(client: TestClient, visitor: dict) -> list[str]:
    headers = {"Authorization": f"Bearer {visitor['elder_token']}"}
    return [item["title"] for item in client.get("/v2/reminders", headers=headers).json()]


def _create_reminder(client: TestClient, visitor: dict, title: str) -> None:
    headers = {"Authorization": f"Bearer {visitor['elder_token']}"}
    session = client.post("/v2/sessions", json={}, headers=headers).json()["session_id"]
    for text in (f"提醒我明天上午九点{title}", "确认办理"):
        client.post("/v2/chat", json={"session_id": session, "text": text}, headers=headers)


# --- identity generation --------------------------------------------------


def test_each_visitor_gets_a_distinct_household(client):
    a, b = _visitor(client), _visitor(client)
    assert a["family_id"] != b["family_id"]
    assert a["elder_id"] != b["elder_id"]


def test_visitor_ids_are_constrained():
    """They become primary keys, so the suffix cannot be arbitrary text."""
    DemoIdentities.for_suffix("v0123abcd")
    for bad in ("../etc", "UPPER", "has space", "semi;colon", "", "x" * 40):
        with pytest.raises(ValueError):
            DemoIdentities.for_suffix(bad)


def test_the_fixed_demo_household_still_works(client):
    """The laptop demo and every existing script rely on these ids."""
    for actor in ("elder-demo", "daughter-demo", "son-demo"):
        assert client.post("/v2/auth/demo", json={"actor_id": actor}).status_code == 200


def test_visitor_endpoint_is_off_when_demo_mode_is(tmp_path):
    closed = TestClient(create_app(tmp_path / "closed.db", demo_mode=False))
    assert closed.post("/v2/auth/visitor").status_code == 404


# --- the isolation itself -------------------------------------------------


def test_one_visitor_cannot_see_anothers_reminders(client):
    a, b = _visitor(client), _visitor(client)
    _create_reminder(client, a, "复诊")
    assert _reminders(client, a) == ["复诊"]
    assert _reminders(client, b) == []


def test_cross_household_profile_read_is_refused(client):
    a, b = _visitor(client), _visitor(client)
    response = client.get(
        f"/v6/profiles/{a['elder_id']}",
        headers={"Authorization": f"Bearer {b['elder_token']}"},
    )
    assert response.status_code == 403


def test_cross_household_write_is_refused(client):
    a, b = _visitor(client), _visitor(client)
    response = client.post(
        "/v2/family/reminders",
        json={"elder_id": a["elder_id"], "title": "越权", "due_at": "2026-08-10T09:00:00+00:00"},
        headers={"Authorization": f"Bearer {b['family_token']}"},
    )
    assert response.status_code == 403


def test_audit_chains_do_not_mix(client):
    a, b = _visitor(client), _visitor(client)
    _create_reminder(client, a, "复诊")
    for visitor in (a, b):
        payload = client.get(
            "/v2/audit?limit=200", headers={"Authorization": f"Bearer {visitor['family_token']}"}
        ).json()
        events = payload if isinstance(payload, list) else payload.get("events", [])
        families = {e.get("family_id") for e in events if isinstance(e, dict)}
        assert families <= {visitor["family_id"], None}, families


def test_each_household_gets_its_own_unpaid_bills(client):
    """Bill ids are per-family too, or one visitor's payment settles another's."""
    a, b = _visitor(client), _visitor(client)
    headers_a = {"Authorization": f"Bearer {a['elder_token']}"}
    session = client.post("/v2/sessions", json={}, headers=headers_a).json()["session_id"]
    first = client.post(
        "/v2/chat", json={"session_id": session, "text": "帮我交水费"}, headers=headers_a
    ).json()
    assert "68.40" in first["message"], first["message"]

    headers_b = {"Authorization": f"Bearer {b['elder_token']}"}
    session_b = client.post("/v2/sessions", json={}, headers=headers_b).json()["session_id"]
    theirs = client.post(
        "/v2/chat", json={"session_id": session_b, "text": "帮我交水费"}, headers=headers_b
    ).json()
    # B's bill is still outstanding regardless of what A is doing with theirs.
    assert "68.40" in theirs["message"], theirs["message"]


def test_visitor_household_is_fully_seeded(client):
    """A sandbox missing its v4 safety defaults would fail on the care page."""
    visitor = _visitor(client)
    headers = {"Authorization": f"Bearer {visitor['elder_token']}"}
    policy = client.get(f"/v4/safety/policy/{visitor['elder_id']}", headers=headers)
    assert policy.status_code == 200, policy.text
    assert policy.json()["elder_id"] == visitor["elder_id"]
