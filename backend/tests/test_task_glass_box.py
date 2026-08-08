"""Design §4.3: the glass-box card and safe preview built from a real task."""

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


def start(client, headers, text):
    session = client.post('/v2/sessions', json={}, headers=headers).json()['session_id']
    return session, client.post('/v2/chat', json={'session_id': session, 'text': text}, headers=headers).json()


def glass_box(client, headers, task_id, heard='帮我办一下'):
    r = client.post(f'/v6/tasks/{task_id}/glass-box', json={'heard_text': heard}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_payment_card_speaks_plain_words_and_preview_tracks_state(tmp_path):
    app = create_app(tmp_path / 'gb1.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        session, first = start(client, elder_h, '帮我交水费')
        task_id = first['task_id']

        awaiting_elder = glass_box(client, elder_h, task_id, '帮我交水费')
        assert awaiting_elder['action_label'] == '生成家属支付请求'
        assert awaiting_elder['policy_action'] == 'create_payment_request'
        card = awaiting_elder['card']
        assert card['current_step'] == '等待您复述确认'
        assert card['action_summary'] == '准备执行：生成家属支付请求（风险等级4）'
        # No internal status enum leaks into elder-facing copy.
        for internal in ('awaiting_elder_confirmation', 'bill_payment', 'create_payment_request'):
            assert internal not in card['action_summary']
        assert awaiting_elder['preview']['authorization']['decision'] == 'require_elder_confirmation'

        client.post('/v2/chat',
                    json={'session_id': session, 'text': teach_back(first['message'])},
                    headers=elder_h)
        awaiting_family = glass_box(client, elder_h, task_id, '确认支付')
        assert awaiting_family['card']['current_step'] == '等待家属接力确认'
        assert awaiting_family['preview']['authorization']['decision'] == 'require_family_approval'


def test_payment_preview_uses_only_allow_listed_fields(tmp_path):
    app = create_app(tmp_path / 'gb2.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        _, first = start(client, elder_h, '帮我交水费')
        preview = glass_box(client, elder_h, first['task_id'])['preview']
        allowed = preview['authorization']['allowed_arguments']
        assert set(allowed) == {'bill_id', 'amount_cents', 'elder_id', 'recipient_family_id'}
        assert preview['authorization']['stripped_fields'] == []
        assert '不会自动扣款' in preview['will_not_do']


def test_registration_card_reports_reversible_reservation(tmp_path):
    app = create_app(tmp_path / 'gb3.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        _, first = start(client, elder_h, '帮我挂明天下午两点第一医院骨科王医生的号')
        result = glass_box(client, elder_h, first['task_id'], '帮我挂骨科号')
        assert result['action_label'] == '预约挂号号源'
        assert result['policy_action'] == 'reserve_appointment'
        assert result['card']['reversible'] is True
        # The card separates a verified tool source from an unverified spoken one.
        sources = result['card']['data_sources']
        assert any(item['trusted'] and item['verified'] for item in sources)
        assert any(not item['trusted'] for item in sources)
        assert result['card']['warning'] is not None


def test_reminder_card_is_low_risk_and_decided_by_the_elder(tmp_path):
    app = create_app(tmp_path / 'gb4.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        _, first = start(client, elder_h, '提醒我明天上午九点复诊')
        result = glass_box(client, elder_h, first['task_id'], '提醒我复诊')
        assert result['action_label'] == '创建提醒'
        assert result['policy_action'] == 'create_reminder'
        assert '老人本人决定' in result['card']['who_decides']


def test_glass_box_is_scoped_to_the_family_and_the_elder(tmp_path):
    app = create_app(tmp_path / 'gb5.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        _, first = start(client, elder_h, '帮我交水费')
        assert client.post('/v6/tasks/task-does-not-exist/glass-box',
                           json={'heard_text': '你好'}, headers=elder_h).status_code == 404
        assert client.post(f"/v6/tasks/{first['task_id']}/glass-box",
                           json={'heard_text': '你好'}).status_code == 401


def test_glass_box_is_audited(tmp_path):
    app = create_app(tmp_path / 'gb6.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        family_h = login(client, 'daughter-demo')
        _, first = start(client, elder_h, '帮我交水费')
        glass_box(client, elder_h, first['task_id'])
        audit = client.get('/v2/audit?limit=100', headers=family_h).json()
        assert audit['chain_valid'] is True
        events = [e for e in audit['events'] if e['event_type'] == 'RELIANCE_CARD_CREATED']
        assert events and events[-1]['payload']['policy_action'] == 'create_payment_request'
