from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from youhuo.api import create_app


def login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def register_device(client: TestClient, headers: dict[str, str], actor_id: str, device_id: str) -> None:
    response = client.post(
        "/v4/devices",
        headers=headers,
        json={
            "actor_id": actor_id,
            "device_id": device_id,
            "platform": "HarmonyOS",
            "brand": "demo",
            "device_name": device_id,
            "push_capable": True,
        },
    )
    assert response.status_code == 200, response.text


def test_v5_voice_and_policy_are_audited(tmp_path) -> None:
    app = create_app(tmp_path / "v5_voice.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        voice = client.post(
            "/v5/voice/resolve",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "candidates": [
                    {"text": "帮我交水费", "confidence": 0.96, "engine": "harmony-asr"},
                    {"text": "帮我缴水费", "confidence": 0.92, "engine": "backup"},
                ],
                "side_effect_possible": True,
            },
        )
        assert voice.status_code == 200
        assert voice.json()["semantic_intent"] == "bill_payment"

        policy = client.post(
            "/v5/actions/authorize",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "goal": "帮我交本月水费",
                "action": "create_payment_request",
                "arguments": {"bill_id": "bill-water-2026-07", "amount_cents": 6840, "elder_id": "elder-demo"},
                "facts": [
                    {"name": "bill_id", "value": "bill-water-2026-07", "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                    {"name": "amount_cents", "value": 6840, "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                    {"name": "elder_id", "value": "elder-demo", "origin": "system", "sensitivity": 3, "purpose": "bill_payment", "trusted_for_control": True},
                ],
                "user_confirmed": True,
                "family_approvals": 1,
                "reversible": True,
            },
        )
        assert policy.status_code == 200
        assert policy.json()["decision"] == "allow"

        family = login(client, "daughter-demo")
        audit = client.get("/v2/audit", headers=family).json()
        types = {event["event_type"] for event in audit["events"]}
        assert "VOICE_CONSENSUS_RESOLVED" in types
        assert "PURPOSE_BOUND_POLICY_DECISION" in types


def test_v5_untrusted_amount_never_authorizes_payment(tmp_path) -> None:
    app = create_app(tmp_path / "v5_policy.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        response = client.post(
            "/v5/actions/authorize",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "goal": "帮我交本月水费",
                "action": "create_payment_request",
                "arguments": {"bill_id": "b", "amount_cents": 999999, "elder_id": "elder-demo"},
                "facts": [
                    {"name": "bill_id", "value": "b", "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                    {"name": "amount_cents", "value": 999999, "origin": "untrusted_document", "purpose": "bill_payment"},
                    {"name": "elder_id", "value": "elder-demo", "origin": "system", "sensitivity": 3, "purpose": "bill_payment", "trusted_for_control": True},
                ],
                "user_confirmed": True,
                "family_approvals": 1,
            },
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "clarify"
        assert "amount_cents" in response.json()["stripped_fields"]


def test_v5_durable_saga_role_gates_and_completion(tmp_path) -> None:
    app = create_app(tmp_path / "v5_saga.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        system = login(client, "system-demo")
        family = login(client, "daughter-demo")
        created = client.post(
            "/v5/sagas",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "kind": "bill_payment",
                "goal": "交本月水费",
                "context": {"bill_type": "水费"},
                "request_id": "saga-payment-1",
            },
        )
        assert created.status_code == 200, created.text
        saga = created.json()
        assert saga["status"] == "active" and saga["version"] == 1

        forbidden = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=elder,
            json={"outcome": "success", "output": {"bill_id": "b1"}, "idempotency_key": "a1", "expected_version": 1},
        )
        assert forbidden.status_code == 403

        step1 = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=system,
            json={"outcome": "success", "output": {"bill_id": "b1", "amount_cents": 6840}, "idempotency_key": "a1", "expected_version": 1},
        )
        assert step1.status_code == 200
        current = step1.json()
        assert current["status"] == "awaiting_human" and current["steps"][1]["name"] == "elder_confirm"

        elder_confirm = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=elder,
            json={"outcome": "success", "output": {"confirmed": True}, "idempotency_key": "a2", "expected_version": 2},
        )
        assert elder_confirm.status_code == 200
        assert elder_confirm.json()["steps"][2]["name"] == "family_approval"

        wrong_role = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=elder,
            json={"outcome": "success", "output": {"approved": True}, "idempotency_key": "a3", "expected_version": 3},
        )
        assert wrong_role.status_code == 403
        family_confirm = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=family,
            json={"outcome": "success", "output": {"approved": True}, "idempotency_key": "a3", "expected_version": 3},
        )
        assert family_confirm.status_code == 200

        version = 4
        for index, output in enumerate(
            [
                {"request_id": "pay-req"},
                {"paid": True, "receipt": "receipt-1"},
                {"verified": True},
            ],
            start=4,
        ):
            response = client.post(
                f"/v5/sagas/{saga['id']}/advance",
                headers=system,
                json={
                    "outcome": "success",
                    "output": output,
                    "idempotency_key": f"a{index}",
                    "expected_version": version,
                },
            )
            assert response.status_code == 200, response.text
            version += 1
        assert response.json()["status"] == "completed"

        duplicate = client.post(
            f"/v5/sagas/{saga['id']}/advance",
            headers=system,
            json={"outcome": "success", "output": {"verified": True}, "idempotency_key": "a6", "expected_version": 6},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["version"] == 7


def test_v5_saga_compensates_reversible_steps(tmp_path) -> None:
    app = create_app(tmp_path / "v5_compensate.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        system = login(client, "system-demo")
        created = client.post(
            "/v5/sagas",
            headers=elder,
            json={"elder_id": "elder-demo", "kind": "medical_appointment", "goal": "挂人民医院骨科"},
        ).json()
        saga_id = created["id"]
        r1 = client.post(
            f"/v5/sagas/{saga_id}/advance",
            headers=elder,
            json={"outcome": "success", "output": {"hospital": "人民医院"}, "idempotency_key": "c1", "expected_version": 1},
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/v5/sagas/{saga_id}/advance",
            headers=system,
            json={"outcome": "success", "output": {"reservation": "hold-1"}, "idempotency_key": "c2", "expected_version": 2},
        )
        assert r2.status_code == 200
        r3 = client.post(
            f"/v5/sagas/{saga_id}/advance",
            headers=elder,
            json={"outcome": "failure", "error_code": "elder_declined", "output": {}, "idempotency_key": "c3", "expected_version": 3},
        )
        assert r3.status_code == 200
        data = r3.json()
        assert data["status"] == "compensated"
        assert data["steps"][1]["status"] == "compensated"
        assert data["context"]["compensation_log"][0]["compensation"] == "release_slot"


def test_v5_offline_sync_conflict_requires_human_for_high_data(tmp_path) -> None:
    app = create_app(tmp_path / "v5_sync.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        family = login(client, "daughter-demo")
        register_device(client, elder, "elder-demo", "elder-phone")
        register_device(client, family, "daughter-demo", "daughter-phone")
        t0 = datetime(2026, 7, 23, 10, 0, tzinfo=UTC).isoformat()
        first = client.post(
            "/v5/sync/operations",
            headers=elder,
            json={
                "operation_id": "op-1",
                "device_id": "elder-phone",
                "entity_type": "health_profile",
                "entity_id": "elder-demo",
                "field_name": "preferred_hospital",
                "value": "人民医院",
                "base_version": 0,
                "lamport_clock": 1,
                "sensitivity": "high",
                "occurred_at": t0,
            },
        )
        assert first.status_code == 200 and first.json()["outcome"] == "applied"
        conflict = client.post(
            "/v5/sync/operations",
            headers=family,
            json={
                "operation_id": "op-2",
                "device_id": "daughter-phone",
                "entity_type": "health_profile",
                "entity_id": "elder-demo",
                "field_name": "preferred_hospital",
                "value": "协和医院",
                "base_version": 0,
                "lamport_clock": 2,
                "sensitivity": "high",
                "occurred_at": t0,
            },
        )
        assert conflict.status_code == 200 and conflict.json()["outcome"] == "conflict"
        conflict_id = conflict.json()["conflict_id"]
        listed = client.get("/v5/sync/conflicts", headers=family)
        assert listed.status_code == 200 and listed.json()[0]["id"] == conflict_id
        resolved = client.post(
            "/v5/sync/conflicts/resolve",
            headers=elder,
            json={"conflict_id": conflict_id, "resolution": "accept_incoming"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["value"] == "协和医院"


def test_v5_sync_rejects_unregistered_device(tmp_path) -> None:
    app = create_app(tmp_path / "v5_sync_reject.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        response = client.post(
            "/v5/sync/operations",
            headers=elder,
            json={
                "operation_id": "unknown-device-op",
                "device_id": "unknown",
                "entity_type": "routine",
                "entity_id": "r1",
                "field_name": "title",
                "value": "复诊",
                "base_version": 0,
                "lamport_clock": 1,
                "sensitivity": "normal",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        assert response.status_code == 200 and response.json()["outcome"] == "rejected"


def test_v5_break_glass_minimal_scope_and_explicit_close(tmp_path) -> None:
    app = create_app(tmp_path / "v5_breakglass.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        family = login(client, "daughter-demo")
        ping = client.post(
            "/v4/location/ping",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "latitude": 39.9043,
                "longitude": 116.3975,
                "accuracy_m": 20,
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        assert ping.status_code == 200
        opened = client.post(
            "/v5/break-glass",
            headers=family,
            json={
                "elder_id": "elder-demo",
                "reason": "老人主动呼救后电话中断，需要确认最近位置",
                "scopes": ["location", "emergency_contacts"],
                "duration_minutes": 10,
            },
        )
        assert opened.status_code == 200
        record = opened.json()
        viewed = client.get(f"/v5/break-glass/{record['id']}/view", headers=family)
        assert viewed.status_code == 200
        assert "location" in viewed.json()["scopes"]
        closed = client.post(f"/v5/break-glass/{record['id']}/close", headers=elder)
        assert closed.status_code == 200 and closed.json()["status"] == "closed"
        denied = client.get(f"/v5/break-glass/{record['id']}/view", headers=family)
        assert denied.status_code == 403


def test_v5_break_glass_never_exposes_companion_chat(tmp_path) -> None:
    app = create_app(tmp_path / "v5_breakglass_forbidden.db", demo_mode=True)
    with TestClient(app) as client:
        family = login(client, "daughter-demo")
        response = client.post(
            "/v5/break-glass",
            headers=family,
            json={
                "elder_id": "elder-demo",
                "reason": "紧急情况需要查看",
                "scopes": ["companion_chat"],
                "duration_minutes": 10,
            },
        )
        assert response.status_code == 403


def test_v5_explanation_and_merkle_proof(tmp_path) -> None:
    app = create_app(tmp_path / "v5_proof.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        session = client.post("/v2/sessions", headers=elder, json={}).json()["session_id"]
        chat = client.post(
            "/v2/chat",
            headers=elder,
            json={"session_id": session, "text": "帮我挂号", "request_id": "proof-chat-1"},
        )
        assert chat.status_code == 200
        task_id = chat.json()["task_id"]
        explanation = client.get(f"/v5/tasks/{task_id}/explain", headers=elder)
        assert explanation.status_code == 200
        assert explanation.json()["task_id"] == task_id
        proof = client.post(f"/v5/tasks/{task_id}/proof", headers=elder)
        assert proof.status_code == 200 and len(proof.json()["merkle_root"]) == 64
        verified = client.post("/v5/proofs/verify", json={"bundle": proof.json()})
        assert verified.status_code == 200 and verified.json()["valid"] is True
        tampered = proof.json()
        tampered["merkle_root"] = "0" * 64
        rejected = client.post("/v5/proofs/verify", json={"bundle": tampered})
        assert rejected.status_code == 200 and rejected.json()["valid"] is False


def test_v5_privacy_export_and_two_phase_erase(tmp_path) -> None:
    app = create_app(tmp_path / "v5_privacy.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        emotion = client.post(
            "/v4/emotions/analyze",
            headers=elder,
            json={"elder_id": "elder-demo", "text": "今天有点孤单", "source": "voice", "store_event": True},
        )
        assert emotion.status_code == 200
        export = client.post(
            "/v5/privacy/export",
            headers=elder,
            json={"elder_id": "elder-demo", "categories": ["emotion_events"]},
        )
        assert export.status_code == 200
        assert len(export.json()["records"]["emotion_events"]) == 1
        preview = client.post(
            "/v5/privacy/erase",
            headers=elder,
            json={"elder_id": "elder-demo", "categories": ["emotion_events"], "execute": False},
        )
        assert preview.status_code == 200 and preview.json()["affected_rows"]["emotion_events"] == 1
        execute = client.post(
            "/v5/privacy/erase",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "categories": ["emotion_events"],
                "execute": True,
                "confirmation_phrase": "我确认删除这些可删除数据",
            },
        )
        assert execute.status_code == 200 and execute.json()["affected_rows"]["emotion_events"] == 1
        after = client.post(
            "/v5/privacy/export",
            headers=elder,
            json={"elder_id": "elder-demo", "categories": ["emotion_events"]},
        )
        assert after.status_code == 200 and after.json()["records"]["emotion_events"] == []


def test_v5_family_cannot_export_or_erase_elder_private_data(tmp_path) -> None:
    app = create_app(tmp_path / "v5_privacy_denied.db", demo_mode=True)
    with TestClient(app) as client:
        family = login(client, "daughter-demo")
        export = client.post(
            "/v5/privacy/export",
            headers=family,
            json={"elder_id": "elder-demo", "categories": ["location_history"]},
        )
        assert export.status_code == 403
        erase = client.post(
            "/v5/privacy/erase",
            headers=family,
            json={"elder_id": "elder-demo", "categories": ["location_history"], "execute": False},
        )
        assert erase.status_code == 403


def test_v5_trace_redaction_and_metrics(tmp_path) -> None:
    app = create_app(tmp_path / "v5_metrics.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        family = login(client, "daughter-demo")
        started = datetime.now(UTC)
        trace = client.post(
            "/v5/traces",
            headers=elder,
            json={
                "trace_id": "trace-1",
                "span_id": "span-1",
                "name": "voice.resolve",
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(milliseconds=20)).isoformat(),
                "status": "ok",
                "attributes": {"phone": "13812345678", "token": "secret"},
            },
        )
        assert trace.status_code == 204
        metrics = client.get("/v5/metrics", headers=family)
        assert metrics.status_code == 200
        assert metrics.json()["audit_chain_valid"] is True
        denied = client.get("/v5/metrics", headers=elder)
        assert denied.status_code == 403


def test_v5_capability_truth_is_explicit(tmp_path) -> None:
    app = create_app(tmp_path / "v5_truth.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        response = client.get("/v5/capability-truth", headers=elder)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "5.0.0"
        assert any("真实医院" in item for item in data["adapters_not_claimed_as_production"])
