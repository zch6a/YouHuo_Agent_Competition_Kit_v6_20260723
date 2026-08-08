from __future__ import annotations

from youhuo.elderbench import evaluate_cases, generate_cases


def test_elderbench_has_diverse_cases():
    cases = generate_cases()
    categories = {case.category.value for case in cases}
    assert len(cases) >= 30
    assert {"task_lock", "safety", "document", "delegation", "ambiguity"}.issubset(categories)


def test_elderbench_core_suite_passes():
    report = evaluate_cases(generate_cases())
    assert report.failed == 0
    assert report.pass_rate == 1.0
