from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from youhuo.v4_models import MedicalDocumentKind, RoutineFrequency
from youhuo.v4_services import (
    CapabilityMatrix,
    EmotionAnalyzer,
    FamilyAttentionBudget,
    InventoryService,
    LocationSafety,
    MedicalReportInterpreter,
    MedicationKnowledgeBase,
    RecurrenceEngine,
)


def generate_cases() -> list[dict]:
    cases: list[dict] = []
    emotions = [
        ('今天很开心', 'positive', False), ('我很孤单没人陪', 'lonely', True),
        ('我心里难受想哭', 'low_mood', True), ('我很担心睡不着', 'anxious', True),
        ('气死我了烦死了', 'angry', True), ('我不想活了', 'urgent', True),
        ('今天和平时一样', 'calm', False),
    ]
    for i in range(20):
        text, label, pause = emotions[i % len(emotions)]
        cases.append({'id': f'emotion-{i:03d}', 'category': 'emotion', 'input': {'text': text}, 'expected': {'label': label, 'pause': pause}})

    for i in range(20):
        frequency = ['daily', 'weekly', 'monthly'][i % 3]
        cases.append({
            'id': f'recurrence-{i:03d}', 'category': 'recurrence',
            'input': {'frequency': frequency, 'interval': 1 + i % 3, 'weekdays': [4] if frequency == 'weekly' else [], 'day': 31 if frequency == 'monthly' else None},
            'expected': {'future': True},
        })

    location_inputs = [
        (39.9042, 116.3974, 20, 'inside'),
        (39.9500, 116.4500, 20, 'outside'),
        (39.9132, 116.3974, 150, 'ambiguous'),
        (39.9042, 116.3974, 500, 'inside'),
    ]
    for i in range(20):
        lat, lon, accuracy, expected = location_inputs[i % len(location_inputs)]
        cases.append({'id': f'location-{i:03d}', 'category': 'location', 'input': {'lat': lat, 'lon': lon, 'accuracy': accuracy}, 'expected': {'state': expected}})

    reports = [
        ('体检日期2026年7月20日，血压138/86，建议2026年8月20日复查。', '2026-08-20'),
        ('空腹血糖6.2 mmol/L，糖化血红蛋白6.1%，请医生解释。', None),
        ('影像提示结节，建议8月20日随访。', '2026-08-20'),
        ('报告出现危急值，请立即就医。', None),
    ]
    for i in range(20):
        text, follow = reports[i % len(reports)]
        cases.append({'id': f'medical-{i:03d}', 'category': 'medical', 'input': {'text': text}, 'expected': {'follow': follow, 'review': True}})

    pairs = [
        (['华法林', '阿司匹林'], 'high'), (['warfarin', 'ibuprofen'], 'high'),
        (['硝酸甘油', '西地那非'], 'critical'), (['二甲双胍', '西咪替丁'], 'moderate'),
        (['未知药甲', '未知药乙'], None),
    ]
    for i in range(20):
        meds, severity = pairs[i % len(pairs)]
        cases.append({'id': f'medication-{i:03d}', 'category': 'medication', 'input': {'medications': meds, 'stock': i + 1}, 'expected': {'severity': severity}})

    for i in range(20):
        cases.append({
            'id': f'governance-{i:03d}', 'category': 'governance',
            'input': {'event': 'sos' if i % 2 else 'monthly_digest', 'unread': 10},
            'expected': {'immediate': bool(i % 2)},
        })
    return cases


def evaluate(cases: list[dict]) -> dict:
    kb = MedicationKnowledgeBase()
    failures: list[dict] = []
    category: dict[str, dict[str, int]] = {}
    current = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    for case in cases:
        ok = False
        detail: dict = {}
        cat = case['category']
        if cat == 'emotion':
            result = EmotionAnalyzer.analyze(case['input']['text'])
            ok = result.label.value == case['expected']['label'] and result.should_pause_task == case['expected']['pause']
            detail = result.model_dump(mode='json')
        elif cat == 'recurrence':
            frequency = RoutineFrequency(case['input']['frequency'])
            due = RecurrenceEngine.next_after(
                current_due_utc=current, frequency=frequency, interval=case['input']['interval'],
                weekdays=case['input']['weekdays'], day_of_month=case['input']['day'],
                time_local='09:00', timezone='Asia/Shanghai',
            )
            ok = due > current
            if frequency == RoutineFrequency.WEEKLY:
                ok = ok and due.astimezone(ZoneInfo('Asia/Shanghai')).weekday() == 4
            detail = {'due': due.isoformat()}
        elif cat == 'location':
            result = LocationSafety.evaluate_geofence(
                latitude=case['input']['lat'], longitude=case['input']['lon'], accuracy_m=case['input']['accuracy'],
                home_lat=39.9042, home_lon=116.3974, radius_m=1000,
            )
            state = 'ambiguous' if result.inside_home_area is None else ('inside' if result.inside_home_area else 'outside')
            ok = state == case['expected']['state'] and (not result.alert_created or state == 'outside')
            detail = result.model_dump(mode='json')
        elif cat == 'medical':
            result = MedicalReportInterpreter.analyze(
                kind=MedicalDocumentKind.CHECKUP_REPORT, text=case['input']['text'], today=date(2026, 7, 23)
            )
            ok = result.follow_up_date == case['expected']['follow'] and result.review_required and '不是诊断' in result.summary_for_elder
            detail = result.model_dump(mode='json')
        elif cat == 'medication':
            result = kb.check(case['input']['medications'])
            severity = result.findings[0].severity if result.findings else None
            forecast = InventoryService.forecast(
                plan_id='p', stock_units=case['input']['stock'], units_per_dose=1, doses_per_day=1, today=date(2026, 7, 23)
            )
            ok = severity == case['expected']['severity'] and result.requires_pharmacist_review and forecast.days_remaining is not None
            detail = {'severity': severity, 'warning': result.warning, 'forecast': forecast.model_dump(mode='json')}
        elif cat == 'governance':
            decision = FamilyAttentionBudget.decide(case['input']['event'], unread_low_priority=case['input']['unread'])
            ok = decision.deliver_now == case['expected']['immediate']
            caps = {item['capability'] for item in CapabilityMatrix.all()}
            ok = ok and 'health_record_export' in caps and 'face_contact_memory' in caps
            detail = {'decision': decision.__dict__}
        bucket = category.setdefault(cat, {'passed': 0, 'failed': 0})
        if ok:
            bucket['passed'] += 1
        else:
            bucket['failed'] += 1
            failures.append({'id': case['id'], 'category': cat, 'detail': detail})
    total = len(cases)
    return {
        'version': 'ElderBench-v4', 'total': total, 'passed': total - len(failures), 'failed': len(failures),
        'pass_rate': round((total - len(failures)) / total, 6), 'category_results': category, 'failures': failures,
        'scope_note': 'Deterministic benchmark cases; not a substitute for older-adult user studies, clinical validation, or device certification.',
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, default=Path('evaluation/elderbench_v4.jsonl'))
    parser.add_argument('--report', type=Path, default=Path('reports/elderbench_v4.json'))
    args = parser.parse_args()
    cases = generate_cases()
    args.dataset.parent.mkdir(parents=True, exist_ok=True)
    args.dataset.write_text('\n'.join(json.dumps(case, ensure_ascii=False) for case in cases) + '\n', encoding='utf-8')
    report = evaluate(cases)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
