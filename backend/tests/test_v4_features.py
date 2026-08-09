from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.models import ChatRequest, Mode, ResponseCode
from youhuo.v4_models import MedicalDocumentKind, POIKind, RoutineFrequency
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


def login(client: TestClient, actor_id: str) -> dict[str, str]:
    response = client.post('/v2/auth/demo', json={'actor_id': actor_id})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    ('frequency', 'kwargs', 'expected_date'),
    [
        (RoutineFrequency.DAILY, {}, date(2026, 7, 23)),
        (RoutineFrequency.WEEKLY, {'weekdays': [4]}, date(2026, 7, 24)),
        (RoutineFrequency.MONTHLY, {'day_of_month': 31}, date(2026, 8, 31)),
    ],
)
def test_recurrence_next_due(frequency, kwargs, expected_date):
    current = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    due = RecurrenceEngine.next_after(
        current_due_utc=current,
        frequency=frequency,
        interval=1,
        time_local='09:00',
        timezone='Asia/Shanghai',
        weekdays=kwargs.get('weekdays', []),
        day_of_month=kwargs.get('day_of_month'),
    )
    assert due.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date() == expected_date


def test_monthly_recurrence_clamps_short_month():
    current = datetime(2026, 1, 31, 1, 0, tzinfo=UTC)
    due = RecurrenceEngine.next_after(
        current_due_utc=current, frequency=RoutineFrequency.MONTHLY, interval=1,
        time_local='09:00', timezone='Asia/Shanghai', weekdays=[], day_of_month=31,
    )
    assert due.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date() == date(2026, 2, 28)


@pytest.mark.parametrize(
    ('text', 'label', 'pause', 'notify'),
    [
        ('今天挺开心的', 'positive', False, False),
        ('我一个人很孤单，没人陪', 'lonely', True, False),
        ('我心里难受，什么都不想做', 'low_mood', True, False),
        ('我很担心，睡不着怎么办', 'anxious', True, False),
        ('气死我了，烦死了', 'angry', True, False),
        ('我不想活了', 'urgent', True, True),
    ],
)
def test_emotion_analysis(text, label, pause, notify):
    result = EmotionAnalyzer.analyze(text)
    assert result.label.value == label
    assert result.should_pause_task is pause
    assert result.should_notify_family is notify


def test_emotional_task_pause_and_resume(env):
    db, engine, elder, _, session = env
    first = engine.handle(elder, ChatRequest(session_id=session.session_id, text='帮我挂号'))
    assert first.task_id
    paused = engine.handle(elder, ChatRequest(session_id=session.session_id, text='我心里难受，什么都不想做'))
    assert paused.code == ResponseCode.CHAT
    assert paused.mode == Mode.COMPANION
    assert paused.data['task_state_preserved'] is True
    assert db.get_session(session.session_id).active_task_id == first.task_id
    resumed = engine.handle(elder, ChatRequest(session_id=session.session_id, text='继续办事'))
    assert resumed.code == ResponseCode.MODE_SWITCHED
    assert resumed.mode == Mode.YOUHUO
    assert resumed.task_id == first.task_id


def test_emotion_report_does_not_store_raw_chat(tmp_path):
    app = create_app(tmp_path / 'emotion.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        family = login(client, 'daughter-demo')
        raw = '我一个人很孤单，这是不应出现在家属周报里的原文'
        r = client.post('/v4/emotions/analyze', headers=elder, json={'elder_id': 'elder-demo', 'text': raw})
        assert r.status_code == 200
        report = client.get('/v4/reports/emotion/elder-demo?period_start=2026-07-01&period_end=2026-07-31', headers=family)
        assert report.status_code == 200
        serialized = report.text
        assert raw not in serialized and '不应出现在家属周报' not in serialized
        assert report.json()['summary']['raw_text_included'] is False


def test_routine_materialization_idempotent(tmp_path):
    app = create_app(tmp_path / 'routine.db', demo_mode=True)
    with TestClient(app) as client:
        family = login(client, 'daughter-demo')
        elder = login(client, 'elder-demo')
        payload = {
            'elder_id': 'elder-demo', 'title': '每月交水费', 'category': 'payment',
            'frequency': 'monthly', 'interval': 1, 'day_of_month': 25,
            'time_local': '09:00', 'timezone': 'Asia/Shanghai', 'start_date': '2026-07-25',
            'escalation_after_minutes': 60,
        }
        created = client.post('/v4/routines', headers=family, json=payload)
        assert created.status_code == 200
        body = {'now': '2026-07-22T00:00:00Z', 'horizon_days': 60}
        first = client.post('/v4/routines/materialize', headers=family, json=body)
        second = client.post('/v4/routines/materialize', headers=family, json=body)
        assert first.status_code == second.status_code == 200
        occurrences = client.get('/v4/routine-occurrences/elder-demo', headers=elder).json()
        unique = {(row['routine_id'], row['due_at']) for row in occurrences}
        assert len(unique) == len(occurrences) >= 1
        done = client.post(f"/v4/routine-occurrences/{occurrences[0]['id']}/complete", headers=elder)
        assert done.status_code == 200 and done.json()['status'] == 'completed'


def test_item_memory_family_proposal_requires_elder_consent(tmp_path):
    app = create_app(tmp_path / 'item.db', demo_mode=True)
    with TestClient(app) as client:
        family = login(client, 'daughter-demo')
        elder = login(client, 'elder-demo')
        proposed = client.post('/v4/items', headers=family, json={
            'elder_id': 'elder-demo', 'label': '家门钥匙', 'category': 'key',
            'location_text': '玄关第二个抽屉', 'scope': 'family_shared', 'sensitivity': 'personal',
        })
        assert proposed.status_code == 200 and proposed.json()['status'] == 'proposed'
        before = client.get('/v4/items/elder-demo?q=钥匙', headers=family).json()
        assert len(before['matches']) == 1 and before['matches'][0]['status'] == 'proposed'
        assert '没有找到已获得您同意保存' in before['spoken_answer']
        approved = client.post('/v4/items/decide', headers=elder, json={'record_id': proposed.json()['id'], 'approve': True})
        assert approved.status_code == 200 and approved.json()['status'] == 'active'
        after = client.get('/v4/items/elder-demo?q=钥匙', headers=family).json()
        assert len(after['matches']) == 1 and '玄关' in after['spoken_answer']


def test_contact_face_demo_is_exact_digest_only(tmp_path):
    app = create_app(tmp_path / 'face.db', demo_mode=True)
    with TestClient(app) as client:
        family = login(client, 'daughter-demo')
        elder = login(client, 'elder-demo')
        proposed = client.post('/v4/contacts', headers=family, json={
            'elder_id': 'elder-demo', 'display_name': '李医生', 'relation': '家庭医生', 'phone': '13800138000'
        }).json()
        client.post('/v4/contacts/decide', headers=elder, json={'record_id': proposed['id'], 'approve': True})
        image = base64.b64encode(b'competition-demo-face-image').decode()
        enrolled = client.post('/v4/contacts/faces/enroll', headers=elder, json={
            'elder_id': 'elder-demo', 'contact_id': proposed['id'], 'image_b64': image
        })
        assert enrolled.status_code == 200
        matched = client.post('/v4/contacts/faces/match', headers=elder, json={'elder_id': 'elder-demo', 'image_b64': image})
        assert matched.status_code == 200 and matched.json()['matched'] is True
        assert matched.json()['production_ready'] is False
        different = base64.b64encode(b'different-frame').decode()
        miss = client.post('/v4/contacts/faces/match', headers=elder, json={'elder_id': 'elder-demo', 'image_b64': different})
        assert miss.status_code == 200 and miss.json()['matched'] is False


def test_medical_report_interpretation_and_followup(tmp_path):
    app = create_app(tmp_path / 'medical.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        text = '体检日期2026年7月20日。血压 138/86 mmHg，空腹血糖 6.2 mmol/L，发现结节。建议2026年8月20日复查。'
        result = client.post('/v4/medical-reports/analyze', headers=elder, json={
            'elder_id': 'elder-demo', 'kind': 'checkup_report', 'text': text,
            'source_name': '体检报告', 'create_followup_reminder': True,
        })
        assert result.status_code == 200
        data = result.json()
        assert data['review_required'] is True
        assert data['follow_up_date'] == '2026-08-20'
        assert any(item['term'] == '结节' for item in data['terms'])
        assert '不是诊断' in data['summary_for_elder']
        events = client.get('/v4/health/events/elder-demo', headers=elder).json()
        assert any(item['kind'] == 'checkup' for item in events)


def test_health_fhir_export(tmp_path):
    app = create_app(tmp_path / 'fhir.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        created = client.post('/v4/health/events', headers=elder, json={
            'elder_id': 'elder-demo', 'kind': 'visit', 'title': '骨科复诊',
            'event_at': '2026-07-23T09:00:00Z', 'payload': {'hospital': '第一医院'},
            'source': 'manual', 'scope': 'family_summary',
        })
        assert created.status_code == 200
        bundle = client.get('/v4/health/fhir/elder-demo', headers=elder).json()
        assert bundle['resourceType'] == 'Bundle' and bundle['type'] == 'collection'
        assert any(entry['resource']['subject']['reference'] == 'Patient/elder-demo' for entry in bundle['entry'])


def test_medication_consent_dose_inventory_and_interaction(tmp_path):
    app = create_app(tmp_path / 'med.db', demo_mode=True)
    with TestClient(app) as client:
        family = login(client, 'daughter-demo')
        elder = login(client, 'elder-demo')
        plan = client.post('/v4/medications', headers=family, json={
            'elder_id': 'elder-demo', 'display_name': '阿司匹林', 'normalized_name': '阿司匹林',
            'dose_text': '每次1片', 'times_local': ['08:00'], 'start_date': '2026-07-23',
            'stock_units': 10, 'units_per_dose': 1, 'source': '家属建议',
        })
        assert plan.status_code == 200 and plan.json()['active'] is False
        decided = client.post('/v4/medications/decide', headers=elder, json={'record_id': plan.json()['id'], 'approve': True})
        assert decided.status_code == 200 and decided.json()['active'] is True
        dose = client.post(f"/v4/medications/{plan.json()['id']}/doses", headers=elder, json={
            'scheduled_at': '2026-07-23T00:00:00Z', 'status': 'taken', 'note': '已服用'
        })
        assert dose.status_code == 200
        duplicate = client.post(f"/v4/medications/{plan.json()['id']}/doses", headers=elder, json={
            'scheduled_at': '2026-07-23T00:00:00Z', 'status': 'taken', 'note': '重复'
        })
        assert duplicate.status_code == 409
        inventory = client.get(f"/v4/medications/{plan.json()['id']}/inventory", headers=elder).json()
        assert inventory['stock_units'] == 9 and inventory['days_remaining'] == 9
        interaction = client.post('/v4/medications/interactions/check', headers=elder, json={
            'medication_names': ['华法林', '阿司匹林']
        }).json()
        assert interaction['findings'][0]['severity'] == 'high'
        assert interaction['requires_pharmacist_review'] is True
        unknown = client.post('/v4/medications/interactions/check', headers=elder, json={
            'medication_names': ['未知药甲', '未知药乙']
        }).json()
        assert unknown['findings'] == [] and '不代表一定安全' in unknown['warning']


@pytest.mark.parametrize(
    ('lat', 'lon', 'accuracy', 'expected'),
    [
        (39.9042, 116.3974, 20, True),
        (39.9500, 116.4500, 20, False),
    ],
)
def test_location_geofence_clear_cases(lat, lon, accuracy, expected):
    result = LocationSafety.evaluate_geofence(
        latitude=lat, longitude=lon, accuracy_m=accuracy,
        home_lat=39.9042, home_lon=116.3974, radius_m=1000,
    )
    assert result.inside_home_area is expected
    assert result.alert_created is (expected is False)


def test_geofence_ambiguous_boundary_does_not_alert():
    result = LocationSafety.evaluate_geofence(
        latitude=39.9132, longitude=116.3974, accuracy_m=150,
        home_lat=39.9042, home_lon=116.3974, radius_m=1000,
    )
    assert result.inside_home_area is None
    assert result.alert_created is False


def test_a_future_heartbeat_is_rejected(tmp_path):
    """一条未来的心跳能永久关掉无交互预警，所以写入侧必须拒绝它。

    `evaluate_inactivity` 算的是 `now - last`。last 在未来，这个差值恒为负，
    `inactive_minutes >= threshold` 永远不成立——报警从此不再触发，而界面上只会
    显示"一直很正常"。
    """
    app = create_app(tmp_path / 'future.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        far_future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
        response = client.post('/v4/safety/heartbeat', headers=elder, json={
            'elder_id': 'elder-demo', 'occurred_at': far_future, 'kind': 'voice',
        })
        assert response.status_code == 422, response.text

        # 但设备时钟允许小幅前偏，否则真机上正常的心跳会被拒。
        skewed = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
        accepted = client.post('/v4/safety/heartbeat', headers=elder, json={
            'elder_id': 'elder-demo', 'occurred_at': skewed, 'kind': 'voice',
        })
        assert accepted.status_code in (200, 201), accepted.text


def test_inactivity_alert_survives_a_future_row_already_in_the_table(tmp_path):
    """读的一侧也要自己站得住，不能假设写进来的都是干净的。

    写入校验挡不住那条规则生效之前就已经落库的行。这是一条安全告警，它不该因为
    库里有一条脏数据就永远沉默。
    """
    app = create_app(tmp_path / 'poisoned.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        family = login(client, 'daughter-demo')
        client.put('/v4/safety/policy', headers=family, json={
            'elder_id': 'elder-demo', 'inactivity_minutes': 60, 'home_lat': 39.9042,
            'home_lon': 116.3974, 'geofence_radius_m': 1000, 'notify_community': False,
        })
        now = datetime.now(UTC)
        client.post('/v4/safety/heartbeat', headers=elder, json={
            'elder_id': 'elder-demo', 'occurred_at': (now - timedelta(hours=5)).isoformat(),
            'kind': 'voice',
        })
        # 绕过模型，直接往表里塞一条未来记录——模拟修复前留下的数据。
        app.state.v4_store.add_activity(
            'fam-demo', 'elder-demo', 'voice', now + timedelta(days=30), {},
        )
        result = client.post('/v4/safety/inactivity/evaluate', headers=family,
                             json={'now': now.isoformat()})
        assert result.status_code == 200, result.text
        row = next(r for r in result.json() if r['elder_id'] == 'elder-demo')
        assert row['alert_created'] is True, row
        assert row['inactive_minutes'] is not None and row['inactive_minutes'] > 0, row


def test_inactivity_sos_poi_and_devices(tmp_path):
    app = create_app(tmp_path / 'safety.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        family = login(client, 'daughter-demo')
        policy = client.put('/v4/safety/policy', headers=family, json={
            'elder_id': 'elder-demo', 'inactivity_minutes': 60, 'home_lat': 39.9042,
            'home_lon': 116.3974, 'geofence_radius_m': 1000, 'notify_community': True,
        })
        assert policy.status_code == 200
        client.post('/v4/safety/heartbeat', headers=elder, json={
            'elder_id': 'elder-demo', 'occurred_at': '2026-07-23T08:00:00Z', 'kind': 'voice'
        })
        inactivity = client.post('/v4/safety/inactivity/evaluate', headers=family, json={'now': '2026-07-23T10:00:01Z'})
        assert inactivity.status_code == 200 and inactivity.json()[0]['alert_created'] is True
        sos = client.post('/v4/safety/sos', headers=elder, json={
            'elder_id': 'elder-demo', 'include_community': True, 'latitude': 39.9, 'longitude': 116.4
        })
        assert sos.status_code == 200 and sos.json()['family_notified'] is True
        assert sos.json()['community_escalation_prepared'] is True
        pois = client.get('/v4/navigation/nearby?latitude=39.9042&longitude=116.3974&kind=hospital', headers=elder)
        assert pois.status_code == 200 and pois.json()[0]['kind'] == 'hospital'
        device = client.post('/v4/devices', headers=elder, json={
            'actor_id': 'elder-demo', 'device_id': 'elder-phone-1', 'platform': 'HarmonyOS',
            'brand': 'Huawei', 'device_name': '老人手机', 'push_capable': True,
        })
        assert device.status_code == 200
        forged = client.post('/v4/devices', headers=family, json={
            'actor_id': 'elder-demo', 'device_id': 'forged', 'platform': 'Android',
            'brand': 'Other', 'device_name': '伪造设备', 'push_capable': True,
        })
        assert forged.status_code == 403


def test_remote_assistance_is_bounded_and_elder_controlled(tmp_path):
    app = create_app(tmp_path / 'assist.db', demo_mode=True)
    with TestClient(app) as client:
        family = login(client, 'daughter-demo')
        elder = login(client, 'elder-demo')
        allowed = client.post('/v4/assistance', headers=family, json={
            'elder_id': 'elder-demo', 'requested_capabilities': ['view_current_step', 'speak_guidance'],
            'expires_in_minutes': 15,
        })
        assert allowed.status_code == 200 and allowed.json()['status'] == 'pending'
        approved = client.post('/v4/assistance/decide', headers=elder, json={
            'record_id': allowed.json()['id'], 'approve': True
        })
        assert approved.status_code == 200 and approved.json()['status'] == 'approved'
        forbidden = client.post('/v4/assistance', headers=family, json={
            'elder_id': 'elder-demo', 'requested_capabilities': ['screen_takeover', 'payment'],
            'expires_in_minutes': 15,
        })
        assert forbidden.status_code == 409


def test_monthly_report_care_graph_and_capability_truth_table(tmp_path):
    app = create_app(tmp_path / 'report.db', demo_mode=True)
    with TestClient(app) as client:
        elder = login(client, 'elder-demo')
        family = login(client, 'daughter-demo')
        report = client.post('/v4/reports/monthly', headers=family, json={'elder_id': 'elder-demo', 'year': 2026, 'month': 7})
        assert report.status_code == 200
        assert 'routine_occurrences' in report.json()['summary']
        assert report.json()['summary']['raw_companion_chat_included'] is False
        graph = client.get('/v4/care-graph/elder-demo', headers=family)
        assert graph.status_code == 200 and graph.json()['elder_id'] == 'elder-demo'
        caps = client.get('/v4/capabilities', headers=elder)
        assert caps.status_code == 200 and len(caps.json()) >= 8
        assert any('prototype' in item['state'] or 'demo' in item['state'] for item in caps.json())
        assert any(item['state'] == 'implemented' for item in caps.json())


def test_low_priority_notification_budget_aggregates():
    decision = FamilyAttentionBudget.decide('monthly_digest', unread_low_priority=7)
    assert decision.deliver_now is False and decision.channel == 'digest'
    urgent = FamilyAttentionBudget.decide('sos', unread_low_priority=100)
    assert urgent.deliver_now is True and urgent.channel == 'push'


def test_face_digest_deterministic_and_not_biometric():
    assert FaceTemplateService.template(b'abc') == FaceTemplateService.template(b'abc')
    assert FaceTemplateService.template(b'abc') != FaceTemplateService.template(b'abd')
    assert FaceTemplateService.ENGINE_NAME == 'exact-image-digest-demo'


def test_medication_inventory_boundaries():
    critical = InventoryService.forecast(plan_id='p', stock_units=1, units_per_dose=1, doses_per_day=1, today=date(2026, 7, 23))
    normal = InventoryService.forecast(plan_id='p', stock_units=30, units_per_dose=1, doses_per_day=1, today=date(2026, 7, 23))
    assert critical.alert_level == 'critical'
    assert normal.alert_level == 'normal'


def test_medication_kb_aliases_and_explicit_scope():
    kb = MedicationKnowledgeBase()
    result = kb.check(['warfarin', 'aspirin'])
    assert result.findings and result.findings[0].medication_a == '华法林'
    assert '有限规则集' in result.database_scope


def test_medical_interpreter_never_claims_diagnosis():
    result = MedicalReportInterpreter.analyze(
        kind=MedicalDocumentKind.CHECKUP_REPORT,
        text='检查发现结节，建议8月20日复查。',
        today=date(2026, 7, 23),
    )
    assert '不是诊断' in result.summary_for_elder
    assert result.review_required is True


def test_fhir_export_is_structural_not_claimed_certification():
    bundle = HealthFHIRExporter.bundle(elder_id='e', health_events=[], medication_plans=[])
    assert bundle['resourceType'] == 'Bundle'
    assert bundle['meta']['tag'][0]['code'] == 'prototype-not-clinical'


def test_capability_matrix_is_truthful():
    items = CapabilityMatrix.all()
    names = {item['capability'] for item in items}
    assert 'face_contact_memory' in names and 'medication_management' in names
    face = next(item for item in items if item['capability'] == 'face_contact_memory')
    assert face['state'] == 'safe_demo_only' and '真实人脸识别' in face['safety_boundary']
