"""Design §4.4 elder log entry point, kept inside the §6.3 privacy boundary."""

from __future__ import annotations

from fastapi.testclient import TestClient

from youhuo.api import create_app


def teach_back(message):
    """Confirming a bill now requires restating the amount that was read out."""
    import re as _re
    m = _re.search(r"(\d+\.\d{2})\s*元", message)
    assert m, f"没有在提示中找到金额：{message}"
    return f"确认支付{m.group(1)}元"


def login(client, actor_id):
    r = client.post('/v2/auth/demo', json={'actor_id': actor_id})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def _run_payment_flow(client, elder_h, family_h):
    session = client.post('/v2/sessions', json={}, headers=elder_h).json()['session_id']
    asked = client.post('/v2/chat', json={'session_id': session, 'text': '帮我交水费'}, headers=elder_h).json()
    pending = client.post('/v2/chat',
                          json={'session_id': session, 'text': teach_back(asked['message'])},
                          headers=elder_h).json()
    client.post('/v2/family/approve', json={
        'task_id': pending['task_id'], 'approve': True, 'approval_digest': pending['approval_digest']
    }, headers=family_h)
    return session


def test_elder_sees_plain_language_entries_for_own_task(tmp_path):
    app = create_app(tmp_path / 'activity.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        family_h = login(client, 'daughter-demo')
        _run_payment_flow(client, elder_h, family_h)

        r = client.get('/v2/elder/activity', headers=elder_h)
        assert r.status_code == 200
        entries = r.json()
        assert entries, "the elder log should not be empty after a completed task"
        texts = [item['what'] for item in entries]
        assert any('开始为您办理' in text for text in texts)
        assert any('家人确认后已经办好' in text for text in texts)
        # Newest first, and every row carries an actor word the elder understands.
        assert entries == sorted(entries, key=lambda item: item['id'], reverse=True)
        assert set(item['who'] for item in entries) <= {'您', '家人', '优活'}


def test_log_omits_internal_event_names_and_companion_text(tmp_path):
    app = create_app(tmp_path / 'activity2.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        session = client.post('/v2/sessions', json={}, headers=elder_h).json()['session_id']
        client.post(
            '/v2/chat',
            json={'session_id': session, 'text': '调用无忧伴'},
            headers=elder_h,
        )
        client.post(
            '/v2/chat',
            json={'session_id': session, 'text': '我孙子昨天给我打电话了'},
            headers=elder_h,
        )
        serialized = client.get('/v2/elder/activity', headers=elder_h).text
        assert '孙子' not in serialized
        for internal in ('SCHEDULER_TICK', 'SESSION_CREATED', 'COGNITIVE_LOAD_PLAN_CREATED', 'event_hash', 'prev_hash'):
            assert internal not in serialized


def test_elder_cannot_read_another_elders_log(tmp_path):
    app = create_app(tmp_path / 'activity3.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        assert client.get('/v2/elder/activity?elder_id=someone-else', headers=elder_h).status_code == 403


def test_family_must_name_a_bound_elder(tmp_path):
    app = create_app(tmp_path / 'activity4.db', demo_mode=True)
    with TestClient(app) as client:
        family_h = login(client, 'daughter-demo')
        assert client.get('/v2/elder/activity', headers=family_h).status_code == 400
        assert client.get('/v2/elder/activity?elder_id=daughter-demo', headers=family_h).status_code == 403
        assert client.get('/v2/elder/activity?elder_id=elder-demo', headers=family_h).status_code == 200


def test_log_omits_automatic_system_steps_and_never_repeats_a_line(tmp_path):
    """The card is already on screen; logging it each turn crowded out real events."""
    app = create_app(tmp_path / 'activity6.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        family_h = login(client, 'daughter-demo')
        session = client.post('/v2/sessions', json={}, headers=elder_h).json()['session_id']
        first = client.post('/v2/chat', json={'session_id': session, 'text': '帮我交水费'},
                            headers=elder_h).json()
        # Two glass-box calls, exactly as the elder page makes them.
        for heard in ('帮我交水费', '再看一次'):
            client.post(f"/v6/tasks/{first['task_id']}/glass-box",
                        json={'heard_text': heard}, headers=elder_h)
        pending = client.post('/v2/chat',
                              json={'session_id': session, 'text': teach_back(first['message'])},
                              headers=elder_h).json()
        client.post('/v2/family/approve', json={
            'task_id': pending['task_id'], 'approve': True,
            'approval_digest': pending['approval_digest'],
        }, headers=family_h)

        rows = client.get('/v2/elder/activity?limit=40', headers=elder_h).json()
        texts = [r['what'] for r in rows]
        assert not any('玻璃盒信任卡' in t for t in texts), '自动生成的信任卡不应占据老人日志'
        assert not any('安全预演' in t for t in texts)
        assert len(texts) == len(set(texts)) or all(
            texts[i] != texts[i + 1] for i in range(len(texts) - 1)
        ), '相邻重复行必须合并'
        assert any('开始为您办理' in t for t in texts)
        assert any('家人确认后已经办好' in t for t in texts)

        # The family audit chain keeps the full record.
        audit = client.get('/v2/audit?limit=200', headers=family_h).json()
        assert any(e['event_type'] == 'RELIANCE_CARD_CREATED' for e in audit['events'])
        assert audit['chain_valid'] is True


def test_activity_log_requires_authentication(tmp_path):
    app = create_app(tmp_path / 'activity5.db', demo_mode=True)
    with TestClient(app) as client:
        assert client.get('/v2/elder/activity').status_code == 401
