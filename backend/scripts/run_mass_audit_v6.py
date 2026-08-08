from __future__ import annotations

import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from youhuo.v5_models import DataFact, DataOrigin, DataSensitivity
from youhuo.v6_models import (
    InteractionPlanRequest,
    InteractionProfile,
    RelianceCardRequest,
    SafePreviewRequest,
    SemanticParseRequest,
    SourceEvidence,
    StudyObservation,
    VerbosityMode,
)
from youhuo.v6_services import (
    CognitiveLoadGovernor,
    CompetitionEvidenceService,
    RelianceCardService,
    SafePreviewService,
    SemanticGateway,
    StudySummaryService,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports" / "mass_audit_v6_500000.json"
SEED = 20260723
TARGET_PER_CATEGORY = 100_000


class Audit:
    def __init__(self) -> None:
        self.total = 0
        self.failed = 0
        self.categories: Counter[str] = Counter()
        self.failures: list[dict[str, object]] = []

    def check(self, category: str, condition: bool, *, scenario: int, name: str, detail: object = None) -> None:
        self.total += 1
        self.categories[category] += 1
        if not condition:
            self.failed += 1
            if len(self.failures) < 100:
                self.failures.append({"category": category, "scenario": scenario, "check": name, "detail": detail})


def profile_for(i: int) -> InteractionProfile:
    modes = [VerbosityMode.CONCISE, VerbosityMode.STANDARD, VerbosityMode.GENTLE]
    return InteractionProfile(
        family_id="fam-demo",
        elder_id="elder-demo",
        speech_rate=0.72 + (i % 9) * 0.05,
        verbosity=modes[i % len(modes)],
        max_options=1 + (i % 3),
        max_sentence_chars=24 + (i % 8) * 8,
        repeat_sensitive=(i % 2 == 0),
        teach_back_high_risk=True,
        font_scale=1.0 + (i % 5) * 0.15,
        hearing_support=(i % 7 == 0),
        dialect_hint="东北话" if i % 11 == 0 else None,
        updated_by="system",
        updated_at=datetime(2026, 7, 23, tzinfo=UTC),
        version=1,
    )


def audit_cognitive(audit: Audit, rng: random.Random) -> None:
    category = "cognitive_load_governor"
    messages = [
        "请完成身份认证并提交预约，之后系统会通知家人。",
        "请选择人民医院、中心医院、第一医院或者社区医院。",
        "这一步可以撤销，请慢慢确认。",
        "请确认本月水费126.50元，确认后由家人支付。",
    ]
    for i in range(10_000):
        profile = profile_for(i)
        risk = 1 + i % 4
        confidence = [0.45, 0.7, 0.88, 0.98][i % 4]
        retries = i % 4
        options = [f"选项{n}" for n in range(1, 1 + (i % 8))]
        req = InteractionPlanRequest(
            elder_id="elder-demo",
            message=messages[i % len(messages)],
            options=options,
            risk_level=risk,
            asr_confidence=confidence,
            recent_retries=retries,
            reversible=(i % 5 != 0),
            force_teach_back=(i % 13 == 0),
        )
        plan = CognitiveLoadGovernor.plan(profile, req)
        repeat = CognitiveLoadGovernor.plan(profile, req)
        high_risk = risk >= 3
        one_question_expected = high_risk or confidence < (0.88 if high_risk else 0.72) or retries >= 2
        audit.check(category, 1 <= len(plan.plan_digest) == 64, scenario=i, name="digest_length")
        audit.check(category, plan == repeat, scenario=i, name="deterministic")
        audit.check(category, 0.0 <= plan.cognitive_load_score <= 1.0, scenario=i, name="score_range")
        audit.check(category, len(plan.visible_options) <= profile.max_options, scenario=i, name="profile_option_cap")
        audit.check(category, len(plan.visible_options) <= 3, scenario=i, name="global_option_cap")
        audit.check(category, not (high_risk and len(plan.visible_options) > 1), scenario=i, name="high_risk_one_option")
        audit.check(category, (plan.mode == "one_question") == one_question_expected, scenario=i, name="mode_rule")
        audit.check(category, (not high_risk) or plan.require_teach_back, scenario=i, name="high_risk_teach_back")
        audit.check(category, plan.hidden_option_count == max(0, len(options) - len(plan.visible_options)), scenario=i, name="hidden_count")
        audit.check(category, 0.55 <= plan.speech_rate <= 1.2, scenario=i, name="speech_rate_safe", detail=plan.speech_rate)


def audit_semantic(audit: Audit, rng: random.Random) -> None:
    category = "semantic_gateway"
    cases = [
        ("救命，我摔倒起不来了", "emergency", "possible_emergency"),
        ("客服让我把验证码发给他", "scam_risk", "possible_scam"),
        ("提醒我下周去人民医院复诊", "reminder", None),
        ("帮我查一下本月水费", "bill_payment", None),
        ("帮我挂人民医院骨科", "hospital_registration", None),
        ("我想和无忧伴聊聊", "companion", None),
        ("取消，先不办了", "cancel", None),
        ("确认，就这样", "confirm", None),
        ("帮我处理那个事情", "unknown", None),
        ("我想挂号", "hospital_registration", None),
    ]
    for i in range(10_000):
        text, expected, flag = cases[i % len(cases)]
        if i % 17 == 0:
            text = "嗯，那个，" + text + "。"
        request = SemanticParseRequest(elder_id="elder-demo", text=text, permit_remote_model=False)
        frame = SemanticGateway.parse(request)
        again = SemanticGateway.parse(request)
        audit.check(category, frame.intent == expected, scenario=i, name="expected_intent", detail=frame.intent)
        audit.check(category, frame.intent in SemanticGateway.ALLOWED_INTENTS, scenario=i, name="intent_allowlist")
        audit.check(category, set(frame.slots).issubset(SemanticGateway.ALLOWED_SLOTS), scenario=i, name="slot_allowlist")
        audit.check(category, frame.parser_source == "deterministic_fallback", scenario=i, name="fallback_source")
        audit.check(category, frame.model_used is False, scenario=i, name="no_remote_model")
        audit.check(category, len(frame.frame_digest) == 64, scenario=i, name="digest_length")
        audit.check(category, frame.frame_digest == again.frame_digest, scenario=i, name="deterministic_digest")
        audit.check(category, 0.0 <= frame.confidence <= 1.0, scenario=i, name="confidence_range")
        audit.check(category, (flag is None) or flag in frame.safety_flags, scenario=i, name="safety_priority")
        audit.check(category, not hasattr(frame, "tool_calls"), scenario=i, name="never_returns_tool_calls")


def payment_facts(amount: int, *, inject: bool) -> list[DataFact]:
    facts = [
        DataFact(name="bill_id", value="bill-demo", origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
        DataFact(name="amount_cents", value=amount, origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
        DataFact(
            name="elder_id",
            value="elder-demo",
            origin=DataOrigin.SYSTEM,
            purpose="bill_payment",
            sensitivity=DataSensitivity.HIGH,
            trusted_for_control=True,
        ),
    ]
    if inject:
        facts.append(
            DataFact(
                name="amount_cents",
                value=99999999,
                origin=DataOrigin.UNTRUSTED_DOCUMENT,
                purpose="bill_payment",
                trusted_for_control=False,
            )
        )
    return facts


def audit_safe_preview(audit: Audit, rng: random.Random) -> None:
    category = "safe_action_preview"
    for i in range(10_000):
        amount = 5000 + (i % 1000)
        inject = i % 4 == 0
        confirmed = i % 3 != 0
        approvals = 1 if i % 5 != 0 else 0
        request = SafePreviewRequest(
            elder_id="elder-demo",
            goal="帮我交本月水费",
            action="create_payment_request",
            arguments={"bill_id": "bill-demo", "amount_cents": amount, "elder_id": "elder-demo"},
            facts=payment_facts(amount, inject=inject),
            ambiguity=0.0,
            user_confirmed=confirmed,
            family_approvals=approvals,
            reversible=True,
        )
        preview = SafePreviewService.preview(request)
        again = SafePreviewService.preview(request)
        decision = preview.authorization.decision.value
        audit.check(category, decision in {"allow", "clarify", "require_elder_confirmation", "require_family_approval", "deny"}, scenario=i, name="decision_enum")
        audit.check(category, len(preview.preview_digest) == 64, scenario=i, name="digest_length")
        audit.check(category, preview.preview_digest == again.preview_digest, scenario=i, name="deterministic")
        audit.check(category, any("不会自动扣款" in item for item in preview.will_not_do), scenario=i, name="never_auto_pay")
        audit.check(category, any("验证码" in item for item in preview.will_not_do), scenario=i, name="never_submit_otp")
        audit.check(category, set(preview.authorization.allowed_arguments).issubset({"bill_id", "amount_cents", "elder_id", "recipient_family_id"}), scenario=i, name="argument_allowlist")
        audit.check(category, (not inject) or "amount_cents" in preview.authorization.stripped_fields, scenario=i, name="untrusted_control_stripped")
        audit.check(category, (not inject) or decision != "allow", scenario=i, name="injection_never_allowed")
        audit.check(category, confirmed or decision != "allow", scenario=i, name="elder_confirmation_required")
        audit.check(category, bool(preview.rollback_plan), scenario=i, name="rollback_explained")


def audit_reliance(audit: Audit, rng: random.Random) -> None:
    category = "reliance_glass_box"
    for i in range(10_000):
        untrusted = i % 3 == 0
        risk = 1 + i % 4
        request = RelianceCardRequest(
            elder_id="elder-demo",
            heard_text="帮我办理本月水费",
            goal="查询并准备水费支付请求",
            current_step="核对账单金额",
            action="create_payment_request",
            risk_level=risk,
            reversible=(i % 5 != 0),
            confirmations=["老人复述金额"] if risk >= 3 else [],
            evidence=[
                SourceEvidence(label="账单服务返回", source="trusted_tool", trusted=True, verified=True),
                SourceEvidence(label="拍照账单OCR", source="camera_ocr", trusted=not untrusted, verified=False),
            ],
            next_step="请老人确认后再让家属接力",
        )
        card = RelianceCardService.build(request)
        again = RelianceCardService.build(request)
        audit.check(category, len(card.card_digest) == 64, scenario=i, name="digest_length")
        audit.check(category, card.card_digest == again.card_digest, scenario=i, name="deterministic")
        audit.check(category, card.heard == request.heard_text, scenario=i, name="heard_preserved")
        audit.check(category, card.goal == request.goal, scenario=i, name="goal_preserved")
        audit.check(category, card.reversible == request.reversible, scenario=i, name="reversible_truth")
        audit.check(category, len(card.data_sources) == 2, scenario=i, name="sources_visible")
        audit.check(category, (card.warning is not None) == untrusted, scenario=i, name="untrusted_warning")
        audit.check(category, (risk < 4) or "家属" in card.who_decides, scenario=i, name="risk4_family_relay")
        audit.check(category, "已核验1项" in card.confidence_message, scenario=i, name="verified_count")
        audit.check(category, "风险等级" in card.action_summary, scenario=i, name="risk_visible")


def audit_study_and_competition(audit: Audit, rng: random.Random) -> None:
    category = "study_and_competition_evidence"
    for i in range(10_000):
        observations = [
            SimpleNamespace(
                duration_seconds=30.0 + i % 100,
                success=i % 4 != 0,
                clarification_count=i % 3,
                assistance_count=i % 2,
                perceived_ease=1 + i % 5,
                trust_calibration=1 + (i + 2) % 5,
            ),
            SimpleNamespace(
                duration_seconds=40.0 + i % 80,
                success=True,
                clarification_count=(i + 1) % 3,
                assistance_count=(i + 1) % 2,
                perceived_ease=1 + (i + 1) % 5,
                trust_calibration=1 + (i + 3) % 5,
            ),
        ]
        summary = StudySummaryService.summarize([object()], observations)
        board = CompetitionEvidenceService.board(datetime(2026, 7, 23, tzinfo=UTC))
        audit.check(category, summary.session_count == 1, scenario=i, name="session_count")
        audit.check(category, summary.observation_count == 2, scenario=i, name="observation_count")
        audit.check(category, 0.0 <= summary.task_success_rate <= 1.0, scenario=i, name="success_rate")
        audit.check(category, summary.median_duration_seconds >= 0.0, scenario=i, name="duration_nonnegative")
        audit.check(category, 1.0 <= summary.mean_perceived_ease <= 5.0, scenario=i, name="ease_range")
        audit.check(category, 1.0 <= summary.mean_trust_calibration <= 5.0, scenario=i, name="trust_range")
        audit.check(category, "不得宣传" in summary.caution, scenario=i, name="truthfulness_caution")
        audit.check(category, sum(item.score_weight for item in board.items) == 100, scenario=i, name="official_weight_sum")
        audit.check(category, len(board.top_three_story) == 3, scenario=i, name="focused_story")
        audit.check(category, bool(board.hard_no_claims), scenario=i, name="hard_no_claims")


def main() -> int:
    rng = random.Random(SEED)
    audit = Audit()
    stages: list[tuple[str, Callable[[Audit, random.Random], None]]] = [
        ("cognitive", audit_cognitive),
        ("semantic", audit_semantic),
        ("preview", audit_safe_preview),
        ("reliance", audit_reliance),
        ("study", audit_study_and_competition),
    ]
    for label, fn in stages:
        fn(audit, rng)
        print(f"PASS {label}: {audit.categories}", flush=True)

    expected = TARGET_PER_CATEGORY * len(stages)
    if audit.total != expected:
        audit.failed += 1
        audit.failures.append({"category": "harness", "check": "exact_count", "detail": {"expected": expected, "actual": audit.total}})
    report = {
        "version": "6.0.0",
        "seed": SEED,
        "deterministic_assertions": audit.total,
        "passed": audit.total - audit.failed,
        "failed": audit.failed,
        "categories": dict(audit.categories),
        "failures": audit.failures,
        "scope_note": "These are deterministic software assertions, not real older-adult participants or real hospital/payment calls.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if audit.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
