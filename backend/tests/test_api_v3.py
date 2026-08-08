from __future__ import annotations

from fastapi.testclient import TestClient

from youhuo.api import create_app


def login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_v3_plan_and_tools(tmp_path):
    app = create_app(tmp_path / "v3api.db", demo_mode=True)
    with TestClient(app) as client:
        headers = login(client, "elder-demo")
        plan = client.get("/v3/plans/reminder", headers=headers)
        assert plan.status_code == 200 and len(plan.json()["graph_digest"]) == 64
        tools = client.get("/v3/tools", headers=headers)
        assert tools.status_code == 200 and len(tools.json()) == 3


def test_v3_document_analysis_audited(tmp_path):
    app = create_app(tmp_path / "v3doc.db", demo_mode=True)
    with TestClient(app) as client:
        elder_headers = login(client, "elder-demo")
        result = client.post(
            "/v3/documents/analyze",
            headers=elder_headers,
            json={"ocr_text": "2026年7月水费账单 应缴：68.40元", "kind": "auto"},
        )
        assert result.status_code == 200 and result.json()["safe_for_autofill"] is True
        family_headers = login(client, "daughter-demo")
        audit = client.get("/v2/audit", headers=family_headers).json()
        assert any(event["event_type"] == "DOCUMENT_ANALYZED" for event in audit["events"])


def test_v3_memory_consent_flow(tmp_path):
    app = create_app(tmp_path / "v3memory.db", demo_mode=True)
    with TestClient(app) as client:
        family_headers = login(client, "daughter-demo")
        proposed = client.post(
            "/v3/memories/propose",
            headers=family_headers,
            json={
                "elder_id": "elder-demo",
                "key": "常用医院",
                "value": "第一医院",
                "sensitivity": "preference",
                "scope": "family_shared",
                "purpose": "减少重复询问",
                "ttl_days": 30,
            },
        )
        assert proposed.status_code == 200 and proposed.json()["status"] == "proposed"
        elder_headers = login(client, "elder-demo")
        decided = client.post(
            "/v3/memories/decide",
            headers=elder_headers,
            json={"memory_id": proposed.json()["id"], "approve": True},
        )
        assert decided.status_code == 200 and decided.json()["status"] == "active"
        visible = client.get("/v3/memories/elder-demo", headers=family_headers)
        assert visible.status_code == 200 and len(visible.json()) == 1


def test_family_cannot_approve_memory(tmp_path):
    app = create_app(tmp_path / "v3memory2.db", demo_mode=True)
    with TestClient(app) as client:
        family_headers = login(client, "daughter-demo")
        proposed = client.post(
            "/v3/memories/propose",
            headers=family_headers,
            json={
                "elder_id": "elder-demo",
                "key": "爱好",
                "value": "戏曲",
                "sensitivity": "preference",
                "scope": "private",
                "purpose": "个性化陪伴",
                "ttl_days": 30,
            },
        ).json()
        denied = client.post(
            "/v3/memories/decide",
            headers=family_headers,
            json={"memory_id": proposed["id"], "approve": True},
        )
        assert denied.status_code == 403


def test_tool_dry_run_api_rejects_extra_argument(tmp_path):
    app = create_app(tmp_path / "v3tool.db", demo_mode=True)
    with TestClient(app) as client:
        headers = login(client, "elder-demo")
        response = client.post(
            "/v3/tools/calendar.create/dry-run",
            headers=headers,
            json={"arguments": {"title": "吃药", "due_at": "2026-07-30T09:00:00Z", "root": True}},
        )
        assert response.status_code == 200 and response.json()["allowed"] is False
