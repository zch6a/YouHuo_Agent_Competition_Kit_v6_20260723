from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from youhuo.v5_models import TranscriptCandidate, VoiceTurnRequest
from youhuo.v5_services import VoiceConsensusEngine
from youhuo.v6_models import InteractionPlanRequest, InteractionProfile
from youhuo.v6_services import CognitiveLoadGovernor

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evaluation" / "voicebench_youhuo_v6.jsonl"
REPORT = ROOT / "reports" / "voicebench_v6.json"


def main() -> int:
    if not DATA.exists():
        raise RuntimeError(f"missing dataset: {DATA}")
    profile = InteractionProfile(
        family_id="fam-demo", elder_id="elder-demo", speech_rate=0.88, verbosity="gentle",
        max_options=3, max_sentence_chars=42, repeat_sensitive=True, teach_back_high_risk=True,
        font_scale=1.25, hearing_support=False, dialect_hint=None, updated_by="system",
        updated_at=datetime(2026, 7, 23, tzinfo=UTC), version=1,
    )
    failures: list[dict] = []
    categories: Counter[str] = Counter()
    total = 0
    for line in DATA.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        total += 1
        categories[case["category"]] += 1
        resolution = VoiceConsensusEngine.resolve(
            VoiceTurnRequest(
                elder_id="elder-demo",
                candidates=[TranscriptCandidate(**item) for item in case["candidates"]],
                side_effect_possible=case["side_effect_possible"],
            )
        )
        errors: list[str] = []
        if resolution.status.value != case["expected_status"]:
            errors.append(f"status={resolution.status.value}")
        if resolution.semantic_intent != case["expected_intent"]:
            errors.append(f"intent={resolution.semantic_intent}")
        expected_flag = case.get("expected_flag")
        if expected_flag and expected_flag not in resolution.safety_flags:
            errors.append(f"missing_flag={expected_flag}")
        plan = CognitiveLoadGovernor.plan(
            profile,
            InteractionPlanRequest(
                elder_id="elder-demo", message=case["message"], options=case["options"],
                risk_level=case["risk_level"], asr_confidence=resolution.confidence,
                recent_retries=1 if resolution.status.value == "clarify" else 0,
                reversible=case["risk_level"] < 4,
            ),
        )
        if len(plan.visible_options) > 3:
            errors.append("too_many_options")
        if bool(plan.require_teach_back) != bool(case["expect_teach_back"]):
            errors.append(f"teach_back={plan.require_teach_back}")
        if not 0 <= plan.cognitive_load_score <= 1:
            errors.append("invalid_load_score")
        if errors:
            failures.append({"id": case["id"], "errors": errors})
    report = {
        "dataset": DATA.name,
        "synthetic_text_cases": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "categories": dict(categories),
        "failures": failures[:50],
        "limitations": [
            "This benchmark uses synthetic transcript candidates, not real audio recordings.",
            "Dialect and acoustic robustness still require consented recordings and device tests.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
