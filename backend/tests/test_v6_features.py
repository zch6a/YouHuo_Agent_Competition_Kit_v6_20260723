from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.v6_models import InteractionPlanRequest, InteractionProfile
from youhuo.v6_services import CognitiveLoadGovernor, SemanticGateway


def login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_v6_default_profile_and_high_risk_teach_back(tmp_path) -> None:
    app = create_app(tmp_path / "v6_profile.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        profile = client.get("/v6/profiles/elder-demo", headers=elder)
        assert profile.status_code == 200
        assert profile.json()["max_options"] == 3
        plan = client.post(
            "/v6/interaction/plan",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "message": "系统将提交本月水费付款请求，请确认金额和账单对象。",
                "options": ["确认办理", "取消办理", "请女儿看看", "稍后再说"],
                "risk_level": 4,
                "asr_confidence": 0.93,
                "reversible": False,
            },
        )
        assert plan.status_code == 200, plan.text
        body = plan.json()
        assert body["mode"] == "one_question"
        assert body["require_teach_back"] is True
        assert len(body["visible_options"]) <= 1
        assert "用自己的话再说一遍" in body["speak_text"]


def test_v6_family_cannot_disable_elder_high_risk_teach_back(tmp_path) -> None:
    app = create_app(tmp_path / "v6_profile_guard.db", demo_mode=True)
    with TestClient(app) as client:
        family = login(client, "daughter-demo")
        response = client.put(
            "/v6/profiles/elder-demo",
            headers=family,
            json={
                "elder_id": "elder-demo",
                "speech_rate": 0.9,
                "verbosity": "standard",
                "max_options": 2,
                "max_sentence_chars": 40,
                "repeat_sensitive": True,
                "teach_back_high_risk": False,
                "font_scale": 1.3,
                "hearing_support": False,
            },
        )
        assert response.status_code == 403


def test_v6_elder_can_update_own_profile_and_not_other_family(tmp_path) -> None:
    app = create_app(tmp_path / "v6_profile_update.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        updated = client.put(
            "/v6/profiles/elder-demo",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "speech_rate": 0.75,
                "verbosity": "concise",
                "max_options": 2,
                "max_sentence_chars": 28,
                "repeat_sensitive": True,
                "teach_back_high_risk": True,
                "font_scale": 1.5,
                "hearing_support": True,
                "dialect_hint": "东北口音",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["speech_rate"] == 0.75
        assert updated.json()["version"] == 1
        forbidden = client.get("/v6/profiles/nonexistent", headers=elder)
        assert forbidden.status_code == 403


def test_v6_low_confidence_shrinks_turn_and_repeats(tmp_path) -> None:
    app = create_app(tmp_path / "v6_low_confidence.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        result = client.post(
            "/v6/interaction/plan",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "message": "请选择第一医院骨科王医生、李医生、张医生或者其他医生，并确认明天下午两点。",
                "options": ["王医生", "李医生", "张医生", "其他医生"],
                "risk_level": 3,
                "asr_confidence": 0.55,
                "recent_retries": 2,
                "current_step": "选择医生",
            },
        ).json()
        assert result["require_repeat_confirmation"] is True
        assert result["turn_budget"] == 1
        assert result["cognitive_load_score"] > 0.4
        assert result["hidden_option_count"] >= 3


def test_v6_reliance_card_marks_untrusted_source(tmp_path) -> None:
    app = create_app(tmp_path / "v6_reliance.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        result = client.post(
            "/v6/reliance/card",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "heard_text": "帮我交水费",
                "goal": "查询并处理本月水费",
                "current_step": "核对账单",
                "action": "create_payment_request",
                "risk_level": 4,
                "reversible": True,
                "confirmations": ["老人复述金额", "女儿扫码支付"],
                "evidence": [
                    {"label": "水费账单", "source": "trusted_bill_api", "trusted": True, "verified": True},
                    {"label": "OCR备注", "source": "uploaded_image", "trusted": False, "verified": False},
                ],
                "next_step": "请老人复述账单金额",
            },
        )
        assert result.status_code == 200
        data = result.json()
        assert "家属" in data["who_decides"]
        assert "OCR备注" in data["warning"]
        assert data["confidence_message"].startswith("已核验1项")


def test_v6_safe_preview_strips_untrusted_amount(tmp_path) -> None:
    app = create_app(tmp_path / "v6_preview.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        result = client.post(
            "/v6/actions/preview",
            headers=elder,
            json={
                "elder_id": "elder-demo",
                "goal": "交水费",
                "action": "create_payment_request",
                "arguments": {"bill_id": "b1", "amount_cents": 999999, "elder_id": "elder-demo", "secret": "x"},
                "facts": [
                    {"name": "bill_id", "value": "b1", "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                    {"name": "amount_cents", "value": 999999, "origin": "untrusted_document", "purpose": "bill_payment"},
                    {"name": "elder_id", "value": "elder-demo", "origin": "system", "sensitivity": 3, "purpose": "bill_payment", "trusted_for_control": True},
                ],
                "user_confirmed": True,
                "family_approvals": 1,
                "reversible": True,
            },
        )
        assert result.status_code == 200
        data = result.json()
        assert data["authorization"]["decision"] == "clarify"
        assert "amount_cents" in data["authorization"]["stripped_fields"]
        assert "secret" in data["authorization"]["stripped_fields"]
        assert any("自动扣款" in item for item in data["will_not_do"])


def test_v6_semantic_gateway_deterministic_and_emergency_first(tmp_path) -> None:
    app = create_app(tmp_path / "v6_semantic.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        hospital = client.post(
            "/v6/semantic/parse",
            headers=elder,
            json={"elder_id": "elder-demo", "text": "帮我挂人民医院骨科的号"},
        ).json()
        assert hospital["intent"] == "hospital_registration"
        assert hospital["slots"]["hospital"] == "人民医院"
        assert hospital["model_used"] is False
        emergency = client.post(
            "/v6/semantic/parse",
            headers=elder,
            json={"elder_id": "elder-demo", "text": "我摔倒了起不来，救命"},
        ).json()
        assert emergency["intent"] == "emergency"
        assert "possible_emergency" in emergency["safety_flags"]
        unknown = client.post(
            "/v6/semantic/parse",
            headers=elder,
            json={"elder_id": "elder-demo", "text": "那个事情帮我弄一下"},
        ).json()
        assert unknown["needs_clarification"] is True


@pytest.mark.parametrize(
    "text",
    [
        "我没有摔倒",
        "我怕摔倒",
        "邻居摔倒了",
        "反诈宣传说不要给验证码",
        "正规客服不会要求验证码",
    ],
)
def test_semantic_gateway_safety_classification_cannot_drift_from_main_policy(text) -> None:
    frame = SemanticGateway.parse(type("Req", (), {"text": text, "permit_remote_model": False})())
    assert frame.intent not in {"emergency", "scam_risk"}
    assert frame.safety_flags == []


def test_v6_study_registry_requires_family_and_summarizes(tmp_path) -> None:
    app = create_app(tmp_path / "v6_study.db", demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, "elder-demo")
        family = login(client, "daughter-demo")
        forbidden = client.post(
            "/v6/studies/sessions",
            headers=elder,
            json={"participant_code": "E001", "role": "elder", "consent_version": "v1"},
        )
        assert forbidden.status_code == 403
        created = client.post(
            "/v6/studies/sessions",
            headers=family,
            json={
                "participant_code": "E001",
                "role": "elder",
                "consent_version": "v1",
                "age_band": "70-79",
                "device_type": "HarmonyOS phone",
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["id"]
        for i, success in enumerate((True, False, True)):
            observation = client.post(
                "/v6/studies/observations",
                headers=family,
                json={
                    "session_id": session_id,
                    "scenario": f"scenario-{i}",
                    "success": success,
                    "duration_seconds": 40 + i * 10,
                    "clarification_count": i,
                    "assistance_count": 0 if success else 1,
                    "perceived_ease": 5 - i,
                    "trust_calibration": 4,
                },
            )
            assert observation.status_code == 200, observation.text
        summary = client.get("/v6/studies/summary", headers=family)
        assert summary.status_code == 200
        data = summary.json()
        assert data["session_count"] == 1
        assert data["observation_count"] == 3
        assert data["task_success_rate"] == 0.666667
        assert "知情同意" in data["caution"]


def test_v6_duplicate_participant_code_is_rejected(tmp_path) -> None:
    app = create_app(tmp_path / "v6_study_duplicate.db", demo_mode=True)
    with TestClient(app) as client:
        family = login(client, "daughter-demo")
        payload = {"participant_code": "F001", "role": "family", "consent_version": "v1"}
        assert client.post("/v6/studies/sessions", headers=family, json=payload).status_code == 200
        assert client.post("/v6/studies/sessions", headers=family, json=payload).status_code == 409


def test_v6_competition_evidence_has_official_score_dimensions(tmp_path) -> None:
    app = create_app(tmp_path / "v6_board.db", demo_mode=True)
    with TestClient(app) as client:
        family = login(client, "daughter-demo")
        response = client.get("/v6/competition/evidence", headers=family)
        assert response.status_code == 200
        data = response.json()
        assert data["project_version"] == "6.0.0"
        assert sum(item["score_weight"] for item in data["items"]) == 100
        assert len(data["top_three_story"]) == 3
        assert any("不承诺" in item for item in data["hard_no_claims"])


def test_cognitive_governor_property_limits_options() -> None:
    profile = InteractionProfile(
        family_id="f",
        elder_id="e",
        speech_rate=0.9,
        verbosity="gentle",
        max_options=3,
        max_sentence_chars=42,
        repeat_sensitive=True,
        teach_back_high_risk=True,
        font_scale=1.3,
        hearing_support=False,
        dialect_hint=None,
        updated_by="system",
        updated_at="2026-07-23T00:00:00Z",
        version=1,
    )
    for risk in range(1, 5):
        for retries in range(0, 5):
            request = InteractionPlanRequest(
                elder_id="e",
                message="请选择一个选项并确认后继续办理",
                options=[f"选项{i}" for i in range(8)],
                risk_level=risk,
                asr_confidence=max(0.0, 1 - retries * 0.2),
                recent_retries=retries,
                reversible=risk < 4,
            )
            plan = CognitiveLoadGovernor.plan(profile, request)
            assert len(plan.visible_options) <= 3
            assert 0 <= plan.cognitive_load_score <= 1
            if risk >= 3:
                assert plan.require_teach_back
                assert plan.turn_budget == 1


def test_semantic_gateway_never_returns_tool_calls() -> None:
    for text in ("交水费", "挂人民医院骨科", "提醒我明天复诊", "有人要我的验证码", "随便弄一下"):
        frame = SemanticGateway.parse(type("Req", (), {"text": text, "permit_remote_model": False})())
        assert frame.intent in SemanticGateway.ALLOWED_INTENTS
        assert set(frame.slots).issubset(SemanticGateway.ALLOWED_SLOTS)
        assert "tool_calls" not in frame.model_dump()
