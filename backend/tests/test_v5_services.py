from __future__ import annotations

from datetime import UTC, datetime

import pytest

from youhuo.v5_models import (
    ActionAuthorizeRequest,
    AuthorizationDecision,
    DataFact,
    DataOrigin,
    DataSensitivity,
    ProofEvent,
    SyncSensitivity,
    TaskProofBundle,
    TranscriptCandidate,
    VoiceResolutionStatus,
    VoiceTurnRequest,
)
from youhuo.v5_services import (
    MerkleProofService,
    MetricsCalculator,
    PrivacyRedactor,
    PurposeBoundPolicy,
    SyncConflictPolicy,
    VoiceConsensusEngine,
)


def candidate(text: str, confidence: float = 0.95, engine: str = "test") -> TranscriptCandidate:
    return TranscriptCandidate(text=text, confidence=confidence, engine=engine)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("帮我交水费", "bill_payment"),
        ("明天下午挂骨科", "hospital_registration"),
        ("晚上八点提醒我吃药", "reminder"),
        ("调用无忧伴陪我聊聊", "companion"),
        ("附近药店怎么走", "navigation"),
        ("救命我摔倒起不来", "emergency"),
    ],
)
def test_voice_intents(text: str, intent: str) -> None:
    result = VoiceConsensusEngine.resolve(
        VoiceTurnRequest(elder_id="elder-demo", candidates=[candidate(text), candidate(text, 0.9, "backup")])
    )
    assert result.status == VoiceResolutionStatus.ACCEPTED
    assert result.semantic_intent == intent
    assert len(result.consensus_digest) == 64


def test_voice_high_risk_low_confidence_requires_clarification() -> None:
    result = VoiceConsensusEngine.resolve(
        VoiceTurnRequest(
            elder_id="elder-demo",
            candidates=[candidate("帮我支付水费", 0.71)],
            side_effect_possible=True,
        )
    )
    assert result.status == VoiceResolutionStatus.CLARIFY
    assert result.resolved_text is None
    assert "确认" in (result.clarification_prompt or "") or "查询" in (result.clarification_prompt or "")


def test_voice_candidate_contradiction_is_not_guessed() -> None:
    result = VoiceConsensusEngine.resolve(
        VoiceTurnRequest(
            elder_id="elder-demo",
            candidates=[candidate("确认办理缴费", 0.91), candidate("取消不要缴费", 0.90, "backup")],
            side_effect_possible=True,
        )
    )
    assert result.status == VoiceResolutionStatus.CLARIFY
    assert "candidate_contradiction" in result.safety_flags
    assert result.ambiguity >= 0.9


def test_voice_emergency_kept_even_with_low_confidence() -> None:
    result = VoiceConsensusEngine.resolve(
        VoiceTurnRequest(elder_id="elder-demo", candidates=[candidate("救命我胸口痛", 0.42)])
    )
    assert result.status == VoiceResolutionStatus.ACCEPTED
    assert "possible_emergency" in result.safety_flags


def payment_request(**overrides):
    data = {
        "elder_id": "elder-demo",
        "goal": "帮我交本月水费",
        "action": "create_payment_request",
        "arguments": {"bill_id": "b1", "amount_cents": 6840, "elder_id": "elder-demo"},
        "facts": [
            DataFact(
                name="bill_id",
                value="b1",
                origin=DataOrigin.TRUSTED_TOOL,
                purpose="bill_payment",
                trusted_for_control=True,
            ),
            DataFact(
                name="amount_cents",
                value=6840,
                origin=DataOrigin.TRUSTED_TOOL,
                purpose="bill_payment",
                trusted_for_control=True,
            ),
            DataFact(
                name="elder_id",
                value="elder-demo",
                origin=DataOrigin.SYSTEM,
                purpose="bill_payment",
                sensitivity=DataSensitivity.HIGH,
                trusted_for_control=True,
            ),
        ],
        "ambiguity": 0.0,
        "user_confirmed": True,
        "family_approvals": 1,
        "reversible": True,
    }
    data.update(overrides)
    return ActionAuthorizeRequest(**data)


def test_policy_allows_purpose_bound_payment_request() -> None:
    result = PurposeBoundPolicy.authorize(payment_request())
    assert result.decision == AuthorizationDecision.ALLOW
    assert result.purpose_bound is True
    assert result.allowed_arguments["amount_cents"] == 6840


def test_policy_never_allows_agent_to_execute_payment() -> None:
    payload = payment_request(action="execute_payment", arguments={})
    result = PurposeBoundPolicy.authorize(payload)
    assert result.decision == AuthorizationDecision.DENY


def test_policy_strips_untrusted_document_control_field() -> None:
    payload = payment_request(
        facts=[
            DataFact(name="bill_id", value="b1", origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
            DataFact(name="amount_cents", value=999999, origin=DataOrigin.UNTRUSTED_DOCUMENT, purpose="bill_payment"),
            DataFact(name="elder_id", value="elder-demo", origin=DataOrigin.SYSTEM, purpose="bill_payment", sensitivity=DataSensitivity.HIGH, trusted_for_control=True),
        ]
    )
    result = PurposeBoundPolicy.authorize(payload)
    assert result.decision == AuthorizationDecision.CLARIFY
    assert "amount_cents" in result.stripped_fields


def test_policy_requires_elder_confirmation() -> None:
    result = PurposeBoundPolicy.authorize(payment_request(user_confirmed=False))
    assert result.decision == AuthorizationDecision.REQUIRE_ELDER_CONFIRMATION


def test_policy_requires_family_approval() -> None:
    result = PurposeBoundPolicy.authorize(payment_request(family_approvals=0))
    assert result.decision == AuthorizationDecision.REQUIRE_FAMILY_APPROVAL


def test_policy_denies_goal_mismatch() -> None:
    result = PurposeBoundPolicy.authorize(payment_request(goal="我只想聊聊孙子"))
    assert result.decision == AuthorizationDecision.DENY


def test_policy_denies_non_reversible_reservation() -> None:
    payload = ActionAuthorizeRequest(
        elder_id="elder-demo",
        goal="帮我挂人民医院骨科",
        action="reserve_appointment",
        arguments={
            "elder_id": "elder-demo",
            "hospital": "人民医院",
            "department": "骨科",
            "date": "2026-07-30",
            "time": "14:00",
        },
        facts=[],
        user_confirmed=True,
        reversible=False,
    )
    result = PurposeBoundPolicy.authorize(payload)
    assert result.decision == AuthorizationDecision.DENY


def test_merkle_bundle_verifies_and_tamper_fails() -> None:
    now = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)

    class Event:
        event_type = "TASK_CREATED"
        actor_id = "elder-demo"
        created_at = now
        payload = {"x": 1}
        event_hash = "a" * 64

    bundle = MerkleProofService.build_bundle(
        bundle_id="proof-1",
        task_id="task-1",
        family_id="fam-demo",
        task_snapshot={"id": "task-1", "status": "completed"},
        audit_events=[Event()],
        audit_chain_valid=True,
        generated_at=now,
    )
    assert MerkleProofService.verify(bundle).valid is True
    tampered = bundle.model_copy(update={"merkle_root": "0" * 64})
    assert MerkleProofService.verify(tampered).valid is False


def test_merkle_root_is_deterministic() -> None:
    leaves = [MerkleProofService.hash_leaf({"i": i}) for i in range(7)]
    assert MerkleProofService.root(leaves) == MerkleProofService.root(list(leaves))
    assert len(MerkleProofService.root(leaves)) == 64


@pytest.mark.parametrize(
    ("sensitivity", "base", "current", "expected"),
    [
        (SyncSensitivity.NORMAL, 3, 3, True),
        (SyncSensitivity.NORMAL, 2, 3, True),
        (SyncSensitivity.PERSONAL, 1, 3, False),
        (SyncSensitivity.HIGH, 3, 3, True),
        (SyncSensitivity.HIGH, 2, 3, False),
    ],
)
def test_sync_conflict_policy(sensitivity, base, current, expected) -> None:
    assert SyncConflictPolicy.may_auto_merge(sensitivity, base, current) is expected


def test_privacy_redactor_masks_common_identifiers() -> None:
    text = "电话13812345678，身份证110101199001011234，银行卡6222021234567890123"
    redacted = PrivacyRedactor.redact_text(text)
    assert "13812345678" not in redacted
    assert "110101199001011234" not in redacted
    assert "6222021234567890123" not in redacted


def test_privacy_redactor_hides_secret_keys_recursively() -> None:
    value = {"name": "王奶奶", "token": "secret", "nested": {"验证码": "123456"}}
    redacted = PrivacyRedactor.redact_value(value)
    assert redacted["token"] == "[已隐藏]"
    assert redacted["nested"]["验证码"] == "[已隐藏]"


def test_metrics_rates_zero_safe() -> None:
    assert MetricsCalculator.rates({}) == {
        "voice_clarification_rate": 0.0,
        "policy_deny_rate": 0.0,
        "saga_completion_rate": 0.0,
        "sync_conflict_rate": 0.0,
    }


def test_policy_clarifies_when_trusted_and_untrusted_control_values_conflict() -> None:
    payload = payment_request(
        facts=[
            DataFact(name="bill_id", value="b1", origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
            DataFact(name="amount_cents", value=6840, origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
            DataFact(name="amount_cents", value=999999, origin=DataOrigin.UNTRUSTED_DOCUMENT, purpose="bill_payment"),
            DataFact(name="elder_id", value="elder-demo", origin=DataOrigin.SYSTEM, purpose="bill_payment", sensitivity=DataSensitivity.HIGH, trusted_for_control=True),
        ]
    )
    result = PurposeBoundPolicy.authorize(payload)
    assert result.decision == AuthorizationDecision.CLARIFY
    assert "amount_cents" in result.stripped_fields
    assert any("冲突" in reason for reason in result.reasons)


def test_policy_accepts_untrusted_document_only_as_corroboration_when_value_matches_trusted_tool() -> None:
    payload = payment_request(
        facts=[
            DataFact(name="bill_id", value="b1", origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
            DataFact(name="amount_cents", value=6840, origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
            DataFact(name="amount_cents", value=6840, origin=DataOrigin.UNTRUSTED_DOCUMENT, purpose="bill_payment"),
            DataFact(name="elder_id", value="elder-demo", origin=DataOrigin.SYSTEM, purpose="bill_payment", sensitivity=DataSensitivity.HIGH, trusted_for_control=True),
        ]
    )
    result = PurposeBoundPolicy.authorize(payload)
    assert result.decision == AuthorizationDecision.ALLOW
    assert result.allowed_arguments["amount_cents"] == 6840
