from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from youhuo.v5_models import (
    ActionAuthorizeRequest,
    AuthorizationDecision,
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


def run_case(case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    kind = case["kind"]
    if kind == "voice":
        payload = VoiceTurnRequest(
            elder_id="elder-demo",
            candidates=[TranscriptCandidate(**item) for item in case["candidates"]],
            side_effect_possible=case.get("side_effect_possible", False),
        )
        out = VoiceConsensusEngine.resolve(payload)
        expected = case["expected"]
        accepted_intents = expected.get("intent_any", [expected["intent"]])
        ok = out.status.value == expected["status"] and out.semantic_intent in accepted_intents
        for flag in expected.get("flags", []):
            ok = ok and flag in out.safety_flags
        return ok, out.model_dump(mode="json")

    if kind == "policy":
        out = PurposeBoundPolicy.authorize(ActionAuthorizeRequest(**case["request"]))
        expected = case["expected"]
        ok = out.decision.value == expected["decision"]
        for field in expected.get("stripped", []):
            ok = ok and field in out.stripped_fields
        return ok, out.model_dump(mode="json")

    if kind == "sync":
        out = SyncConflictPolicy.may_auto_merge(
            SyncSensitivity(case["sensitivity"]), case["base_version"], case["current_version"]
        )
        return out is case["expected"], {"result": out}

    if kind == "privacy":
        out = PrivacyRedactor.redact_value(case["value"])
        encoded = json.dumps(out, ensure_ascii=False)
        ok = all(item not in encoded for item in case["not_contains"])
        return ok, {"redacted": out}

    if kind == "saga_catalog":
        steps = SagaCatalog.steps(SagaKind(case["saga_kind"]))
        ok = (
            len(steps) == case["expected_steps"]
            and sum(step.requires_human for step in steps) == case["expected_human_steps"]
            and sum(step.reversible for step in steps) == case["expected_reversible_steps"]
        )
        return ok, {"steps": [step.name for step in steps]}

    if kind == "proof":
        leaves = [MerkleProofService.hash_leaf(item) for item in case["values"]]
        root = MerkleProofService.root(leaves)
        same = root == MerkleProofService.root(list(leaves))
        changed_values = list(case["values"])
        changed_values[-1] = {"tampered": True, "value": changed_values[-1]}
        changed_root = MerkleProofService.root([MerkleProofService.hash_leaf(item) for item in changed_values])
        ok = same and len(root) == 64 and changed_root != root
        return ok, {"root": root, "tampered_root": changed_root}

    raise ValueError(f"Unknown kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/elderbench_v5.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/elderbench_v5.json"))
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    failures: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()
    for case in cases:
        categories[case["kind"]] += 1
        try:
            ok, actual = run_case(case)
        except Exception as exc:  # report malformed benchmark case as failure
            ok, actual = False, {"error": type(exc).__name__, "message": str(exc)}
        if not ok and len(failures) < 100:
            failures.append({"id": case["id"], "kind": case["kind"], "actual": actual, "expected": case.get("expected")})
    report = {
        "version": "5.0.0",
        "dataset": str(args.dataset),
        "total": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "categories": dict(categories),
        "failures": failures,
        "compatibility_note": "v6 accepts either dialogue-act or task-domain intent for contradictory confirm/cancel candidates; the mandatory safety outcome remains clarify with candidate_contradiction.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
