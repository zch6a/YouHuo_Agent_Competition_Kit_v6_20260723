from __future__ import annotations

import argparse
import json
from pathlib import Path

from youhuo.elderbench import evaluate_cases, generate_cases, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and execute the deterministic ElderBench v3 core suite.")
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/elderbench_v3.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("reports/elderbench_v3.json"))
    args = parser.parse_args()
    cases = generate_cases()
    write_jsonl(args.dataset, cases)
    report = evaluate_cases(cases)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
