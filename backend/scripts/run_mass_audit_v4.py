from __future__ import annotations

import argparse
import calendar
import json
import random
import tempfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from youhuo.database import Database
from youhuo.models import ActorRole
from youhuo.v4_models import (
    EmotionLabel,
    HealthEventKind,
    MedicalDocumentKind,
    RoutineCreate,
    RoutineFrequency,
    RoutineCategory,
    ShareScope,
)
from youhuo.v4_services import (
    CapabilityMatrix,
    EmotionAnalyzer,
    FaceTemplateService,
    FamilyAttentionBudget,
    HealthFHIRExporter,
    InventoryService,
    LocationSafety,
    MedicalReportInterpreter,
    MedicationKnowledgeBase,
    RecurrenceEngine,
)
from youhuo.v4_store import V4FeatureStore


class Audit:
    def __init__(self) -> None:
        self.total = 0
        self.failures: list[dict[str, object]] = []
        self.categories: Counter[str] = Counter()

    def check(self, category: str, condition: bool, detail: dict[str, object] | None = None) -> None:
        self.total += 1
        self.categories[category] += 1
        if not condition and len(self.failures) < 100:
            self.failures.append({'category': category, 'detail': detail or {}})


def recurrence_checks(audit: Audit, rng: random.Random, n: int) -> None:
    frequencies = [RoutineFrequency.DAILY, RoutineFrequency.WEEKLY, RoutineFrequency.MONTHLY]
    tz = ZoneInfo('Asia/Shanghai')
    for i in range(n):
        year = rng.randint(2024, 2038)
        month = rng.randint(1, 12)
        day = rng.randint(1, calendar.monthrange(year, month)[1])
        current = datetime(year, month, day, rng.randint(0, 23), rng.randint(0, 59), tzinfo=UTC)
        frequency = frequencies[i % 3]
        interval = rng.randint(1, 4)
        weekdays = sorted(set(rng.randint(0, 6) for _ in range(rng.randint(1, 4)))) if frequency == RoutineFrequency.WEEKLY else []
        dom = rng.randint(1, 31) if frequency == RoutineFrequency.MONTHLY else None
        due = RecurrenceEngine.next_after(
            current_due_utc=current, frequency=frequency, interval=interval, weekdays=weekdays,
            day_of_month=dom, time_local=f'{rng.randint(0,23):02d}:{rng.randint(0,59):02d}', timezone='Asia/Shanghai',
        )
        local = due.astimezone(tz)
        ok = due > current and due.tzinfo is not None
        if frequency == RoutineFrequency.WEEKLY:
            ok = ok and local.weekday() in weekdays
        if frequency == RoutineFrequency.MONTHLY:
            ok = ok and local.day == min(dom or 1, calendar.monthrange(local.year, local.month)[1])
        audit.check('recurrence', ok, {'i': i, 'frequency': frequency.value})


def emotion_checks(audit: Audit, rng: random.Random, n: int) -> None:
    samples = [
        ('今天很开心，谢谢你', EmotionLabel.POSITIVE, False),
        ('我一个人很孤单，没人陪', EmotionLabel.LONELY, True),
        ('心里难受，什么都不想做', EmotionLabel.LOW_MOOD, True),
        ('我很担心，睡不着怎么办', EmotionLabel.ANXIOUS, True),
        ('气死我了，烦死了', EmotionLabel.ANGRY, True),
        ('我不想活了', EmotionLabel.URGENT, True),
        ('今天和平常一样', EmotionLabel.CALM, False),
    ]
    for i in range(n):
        text, expected, pause = samples[i % len(samples)]
        text = ('嗯，' * rng.randint(0, 2)) + text
        result = EmotionAnalyzer.analyze(text)
        ok = (
            result.label == expected and result.should_pause_task == pause and
            -1 <= result.valence <= 1 and 0 <= result.distress <= 1 and
            ('原文' not in result.privacy_safe_note)
        )
        if expected == EmotionLabel.URGENT:
            ok = ok and result.should_notify_family
        audit.check('emotion_privacy', ok, {'i': i, 'label': result.label.value})


def location_checks(audit: Audit, rng: random.Random, n: int) -> None:
    home_lat, home_lon, radius = 39.9042, 116.3974, 1200
    for i in range(n):
        offset_m = rng.uniform(0, 3500)
        bearing_sign = -1 if rng.random() < 0.5 else 1
        lat = home_lat + bearing_sign * offset_m / 111_000
        accuracy = rng.uniform(5, 400)
        result = LocationSafety.evaluate_geofence(
            latitude=lat, longitude=home_lon, accuracy_m=accuracy,
            home_lat=home_lat, home_lon=home_lon, radius_m=radius,
        )
        distance = result.distance_from_home_m or 0
        ambiguous = abs(distance - radius) <= accuracy
        if ambiguous:
            ok = result.inside_home_area is None and not result.alert_created
        elif distance > radius + accuracy:
            ok = result.inside_home_area is False and result.alert_created
        else:
            ok = result.inside_home_area is True and not result.alert_created
        audit.check('location_geofence', ok, {'i': i, 'distance': distance, 'accuracy': accuracy})


def medication_checks(audit: Audit, rng: random.Random, n: int) -> None:
    kb = MedicationKnowledgeBase()
    pairs = [
        (['华法林', '阿司匹林'], 'high'),
        (['warfarin', 'ibuprofen'], 'high'),
        (['硝酸甘油', '西地那非'], 'critical'),
        (['二甲双胍', '西咪替丁'], 'moderate'),
        (['未知药甲', '未知药乙'], None),
    ]
    today = date(2026, 7, 23)
    for i in range(n):
        names, severity = pairs[i % len(pairs)]
        if rng.random() < 0.5:
            names = list(reversed(names))
        result = kb.check(names)
        forecast = InventoryService.forecast(
            plan_id='p', stock_units=rng.uniform(0, 100), units_per_dose=rng.uniform(0.25, 3),
            doses_per_day=rng.randint(1, 4), today=today,
        )
        found = result.findings[0].severity if result.findings else None
        ok = (
            found == severity and result.requires_pharmacist_review and
            '不代表一定安全' in result.warning and forecast.stock_units >= 0 and
            forecast.units_per_day > 0 and forecast.days_remaining is not None
        )
        audit.check('medication_safety', ok, {'i': i, 'expected': severity, 'found': found})


def medical_fhir_checks(audit: Audit, rng: random.Random, n: int) -> None:
    templates = [
        '体检日期2026年7月20日，血压 138/86 mmHg，建议2026年8月20日复查。',
        '空腹血糖 6.2 mmol/L，糖化血红蛋白 6.1%，请医生解释。',
        '影像提示结节，不等于诊断，建议8月20日随访。',
        '报告出现危急值，请立即就医。',
    ]
    for i in range(n):
        text = templates[i % len(templates)]
        analysis = MedicalReportInterpreter.analyze(
            kind=MedicalDocumentKind.CHECKUP_REPORT, text=text, today=date(2026, 7, 23)
        )
        event = {
            'id': f'e{i}', 'kind': HealthEventKind.CHECKUP.value, 'event_at': datetime(2026, 7, 23, tzinfo=UTC).isoformat(),
            'title': '体检记录', 'scope': ShareScope.FAMILY_SUMMARY.value,
        }
        bundle = HealthFHIRExporter.bundle(elder_id='elder-demo', health_events=[event], medication_plans=[])
        ok = (
            analysis.review_required and '不是诊断' in analysis.summary_for_elder and
            len(analysis.source_digest) == 64 and bundle['resourceType'] == 'Bundle' and
            bundle['meta']['tag'][0]['code'] == 'prototype-not-clinical'
        )
        audit.check('medical_fhir', ok, {'i': i})


def governance_checks(audit: Audit, rng: random.Random, n: int) -> None:
    caps = CapabilityMatrix.all()
    cap_names = {str(item['capability']) for item in caps}
    for i in range(n):
        payload = f'frame-{rng.randint(0, 1000000)}'.encode()
        digest = FaceTemplateService.template(payload)
        low = FamilyAttentionBudget.decide('monthly_digest', unread_low_priority=5 + i % 10)
        urgent = FamilyAttentionBudget.decide('sos', unread_low_priority=100)
        ok = (
            len(digest) == 64 and digest == FaceTemplateService.template(payload) and
            not low.deliver_now and low.channel == 'digest' and urgent.deliver_now and
            {'face_contact_memory', 'medication_management', 'health_record_export'}.issubset(cap_names)
        )
        audit.check('governance_schema', ok, {'i': i})


def stateful_checks(audit: Audit, rng: random.Random, n: int) -> None:
    del rng
    with tempfile.TemporaryDirectory() as td:
        db = Database(Path(td) / 'audit.db')
        db.seed_demo()
        store = V4FeatureStore(db)
        store.seed_demo()
        spec = RoutineCreate(
            elder_id='elder-demo', title='每日固定事务', category=RoutineCategory.LIFE,
            frequency=RoutineFrequency.DAILY, interval=1, time_local='09:00', timezone='Asia/Shanghai',
            start_date=date(2026, 7, 23), escalation_after_minutes=60,
        )
        record = store.create_routine('fam-demo', 'daughter-demo', spec)
        first = store.materialize_routines('fam-demo', datetime(2026, 7, 22, tzinfo=UTC), 2)
        baseline = [x for x in store.list_occurrences('fam-demo', 'elder-demo') if x.routine_id == record.id]
        for i in range(n):
            again = store.materialize_routines('fam-demo', datetime(2026, 7, 22, tzinfo=UTC), 2)
            occurrences = [x for x in store.list_occurrences('fam-demo', 'elder-demo') if x.routine_id == record.id]
            ok = (
                len(baseline) == 1 and len(occurrences) == 1 and
                first['occurrences_created'] == 1 and again['occurrences_created'] == 0
            )
            audit.check('stateful_idempotency', ok, {'i': i})
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=Path('reports/mass_audit_v4_500000.json'))
    parser.add_argument('--seed', type=int, default=20260723)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    audit = Audit()
    recurrence_checks(audit, rng, 100_000)
    emotion_checks(audit, rng, 100_000)
    location_checks(audit, rng, 100_000)
    medication_checks(audit, rng, 75_000)
    medical_fhir_checks(audit, rng, 50_000)
    governance_checks(audit, rng, 74_000)
    stateful_checks(audit, rng, 1_000)
    report = {
        'version': '4.0.0', 'seed': args.seed, 'total_checks': audit.total,
        'passed': audit.total - len(audit.failures), 'failed': len(audit.failures),
        'categories': dict(audit.categories), 'failures': audit.failures,
        'interpretation': (
            'This is a deterministic engineering/property audit. It is not 500,000 real users, '
            'real clinical encounters, or physical-device trials.'
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['failed'] == 0 and report['total_checks'] == 500_000 else 1


if __name__ == '__main__':
    raise SystemExit(main())
