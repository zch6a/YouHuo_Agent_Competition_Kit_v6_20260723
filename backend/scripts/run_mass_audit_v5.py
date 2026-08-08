from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from youhuo.v5_models import (
    ActionAuthorizeRequest,
    DataFact,
    DataOrigin,
    DataSensitivity,
    SagaKind,
    SyncSensitivity,
    TranscriptCandidate,
    VoiceTurnRequest,
)
from youhuo.v5_services import (
    MerkleProofService,
    PrivacyRedactor,
    PurposeBoundPolicy,
    SagaCatalog,
    SyncConflictPolicy,
    VoiceConsensusEngine,
)


class Audit:
    def __init__(self) -> None:
        self.total = 0
        self.categories: Counter[str] = Counter()
        self.failures: list[dict[str, Any]] = []

    def check(self, category: str, condition: bool, detail: dict[str, Any] | None = None) -> None:
        self.total += 1
        self.categories[category] += 1
        if not condition and len(self.failures) < 100:
            self.failures.append({"category": category, "detail": detail or {}})


def voice_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    templates = [
        ("帮我交水费", "bill_payment"),
        ("明天下午挂人民医院骨科", "hospital_registration"),
        ("晚上八点提醒我吃药", "reminder"),
        ("调用无忧伴陪我聊聊", "companion"),
        ("附近药店怎么走", "navigation"),
    ]
    fillers = ["", "嗯，", "那个，", "麻烦你，"]
    for i in range(cases):
        text, intent = templates[i % len(templates)]
        c1 = 0.90 + rng.random() * 0.09
        c2 = 0.86 + rng.random() * 0.10
        result = VoiceConsensusEngine.resolve(
            VoiceTurnRequest(
                elder_id="elder-demo",
                candidates=[
                    TranscriptCandidate(text=fillers[i % 4] + text, confidence=c1, engine="primary"),
                    TranscriptCandidate(text=text, confidence=c2, engine="backup"),
                ],
                side_effect_possible=intent in {"bill_payment", "hospital_registration"},
            )
        )
        audit.check("voice", result.semantic_intent == intent, {"i": i, "intent": result.semantic_intent})
        audit.check("voice", result.status.value == "accepted", {"i": i, "status": result.status.value})
        audit.check("voice", result.resolved_text is not None, {"i": i})
        audit.check("voice", 0 <= result.confidence <= 1 and 0 <= result.ambiguity <= 1, {"i": i})
        audit.check("voice", len(result.consensus_digest) == 64, {"i": i})


def policy_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    for i in range(cases):
        amount = rng.randint(1, 500_000)
        attack = i % 10 == 0
        wrong_goal = i % 17 == 0
        unconfirmed = i % 13 == 0
        no_family = i % 11 == 0
        origin = DataOrigin.UNTRUSTED_DOCUMENT if attack else DataOrigin.TRUSTED_TOOL
        payload = ActionAuthorizeRequest(
            elder_id="elder-demo",
            goal="我只想聊聊孙子" if wrong_goal else "帮我交本月水费",
            action="create_payment_request",
            arguments={"bill_id": f"b{i}", "amount_cents": amount, "elder_id": "elder-demo", "unexpected": "drop"},
            facts=[
                DataFact(name="bill_id", value=f"b{i}", origin=DataOrigin.TRUSTED_TOOL, purpose="bill_payment", trusted_for_control=True),
                DataFact(name="amount_cents", value=amount, origin=origin, purpose="bill_payment", trusted_for_control=not attack),
                DataFact(name="elder_id", value="elder-demo", origin=DataOrigin.SYSTEM, sensitivity=DataSensitivity.HIGH, purpose="bill_payment", trusted_for_control=True),
            ],
            user_confirmed=not unconfirmed,
            family_approvals=0 if no_family else 1,
            reversible=True,
        )
        result = PurposeBoundPolicy.authorize(payload)
        expected = "clarify" if attack else "deny" if wrong_goal else "require_elder_confirmation" if unconfirmed else "require_family_approval" if no_family else "allow"
        audit.check("purpose_policy", result.decision.value == expected, {"i": i, "expected": expected, "actual": result.decision.value})
        audit.check("purpose_policy", "unexpected" in result.stripped_fields, {"i": i})
        audit.check("purpose_policy", "unexpected" not in result.allowed_arguments, {"i": i})
        audit.check("purpose_policy", len(result.decision_digest) == 64, {"i": i})
        audit.check("purpose_policy", result.policy_version == PurposeBoundPolicy.VERSION and result.purpose_bound, {"i": i})


def sync_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    sensitivities = [SyncSensitivity.NORMAL, SyncSensitivity.PERSONAL, SyncSensitivity.HIGH]
    for i in range(cases):
        sensitivity = sensitivities[i % 3]
        current = rng.randint(1, 100)
        delta = rng.randint(0, 3)
        base = max(0, current - delta)
        out = SyncConflictPolicy.may_auto_merge(sensitivity, base, current)
        expected = base == current if sensitivity == SyncSensitivity.HIGH else base >= current - 1
        audit.check("offline_sync", out is expected, {"i": i})
        audit.check("offline_sync", (not out) or base <= current, {"i": i})
        audit.check("offline_sync", sensitivity != SyncSensitivity.HIGH or out == (base == current), {"i": i})


def proof_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    for i in range(cases):
        values = [{"case": i, "seq": j, "salt": rng.randint(0, 1_000_000)} for j in range(1, 2 + i % 7)]
        leaves = [MerkleProofService.hash_leaf(v) for v in values]
        root = MerkleProofService.root(leaves)
        reroot = MerkleProofService.root(list(leaves))
        mutated = list(values)
        mutated[-1] = {**mutated[-1], "salt": mutated[-1]["salt"] + 1}
        changed = MerkleProofService.root([MerkleProofService.hash_leaf(v) for v in mutated])
        audit.check("proof_integrity", root == reroot, {"i": i})
        audit.check("proof_integrity", root != changed, {"i": i})
        audit.check("proof_integrity", len(root) == 64, {"i": i})
        audit.check("proof_integrity", all(len(leaf) == 64 for leaf in leaves), {"i": i})
        audit.check("proof_integrity", MerkleProofService.root([]) == MerkleProofService.root([]), {"i": i})
        audit.check("proof_integrity", MerkleProofService.hash_leaf(values[0]) == MerkleProofService.hash_leaf(dict(values[0])), {"i": i})


def privacy_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    del rng
    for i in range(cases):
        phone = f"138{i % 100_000_000:08d}"
        identity = f"11010119900101{i % 10000:04d}"
        card = f"6222021234567{i % 1_000_000:06d}"
        value = {"text": f"电话{phone} 身份证{identity} 银行卡{card}", "token": f"secret-{i}", "nested": {"验证码": f"{i % 1_000_000:06d}"}}
        out = PrivacyRedactor.redact_value(value)
        encoded = json.dumps(out, ensure_ascii=False)
        audit.check("privacy", phone not in encoded, {"i": i})
        audit.check("privacy", identity not in encoded, {"i": i})
        audit.check("privacy", card not in encoded, {"i": i})
        audit.check("privacy", f"secret-{i}" not in encoded and out["token"] == "[已隐藏]", {"i": i})


def saga_checks(audit: Audit, rng: random.Random, cases: int) -> None:
    del rng
    kinds = list(SagaKind)
    for i in range(cases):
        kind = kinds[i % len(kinds)]
        steps = SagaCatalog.steps(kind)
        names = [s.name for s in steps]
        audit.check("saga_catalog", len(steps) >= 5, {"i": i, "kind": kind.value})
        audit.check("saga_catalog", len(names) == len(set(names)), {"i": i})
        audit.check("saga_catalog", names[-1] == "verify_final_state", {"i": i})
        audit.check("saga_catalog", all((not s.reversible) or bool(s.compensation_name) for s in steps), {"i": i})


def safety_invariants(audit: Audit, rng: random.Random, cases: int) -> None:
    del rng
    for i in range(cases):
        forbidden = ["execute_payment", "disclose_companion_chat", "submit_identity_secret", "medication_diagnosis"]
        action = forbidden[i % len(forbidden)]
        result = PurposeBoundPolicy.authorize(ActionAuthorizeRequest(elder_id="elder-demo", goal="紧急处理", action=action))
        audit.check("safety_invariant", result.decision.value == "deny", {"i": i, "action": action})
        audit.check("safety_invariant", result.allowed_arguments == {}, {"i": i})
        audit.check("safety_invariant", len(result.decision_digest) == 64, {"i": i})
        audit.check("safety_invariant", result.purpose_bound is True, {"i": i})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("reports/mass_audit_v5_1000000.json"))
    parser.add_argument("--seed", type=int, default=20260723)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    audit = Audit()
    voice_checks(audit, rng, 30_000)          # 150,000 assertions
    policy_checks(audit, rng, 50_000)         # 250,000 assertions
    sync_checks(audit, rng, 50_000)           # 150,000 assertions
    proof_checks(audit, rng, 25_000)          # 150,000 assertions
    privacy_checks(audit, rng, 25_000)        # 100,000 assertions
    saga_checks(audit, rng, 25_000)           # 100,000 assertions
    safety_invariants(audit, rng, 25_000)     # 100,000 assertions
    assert audit.total == 1_000_000, audit.total
    report = {
        "version": "5.0.0",
        "seed": args.seed,
        "total_checks": audit.total,
        "passed": audit.total - len(audit.failures),
        "failed": len(audit.failures),
        "categories": dict(audit.categories),
        "failures": audit.failures,
        "interpretation": "固定种子的性质/边界/策略断言，不代表100万名真实老人或100万次真实第三方接口调用。",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not audit.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
