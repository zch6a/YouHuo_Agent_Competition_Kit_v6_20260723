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


def test_api_auth_and_full_payment(tmp_path):
    app = create_app(tmp_path / 'api.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        family_h = login(client, 'daughter-demo')
        session = client.post('/v2/sessions', json={}, headers=elder_h).json()['session_id']
        a = client.post('/v2/chat', json={'session_id': session, 'text': '帮我交水费'}, headers=elder_h)
        assert a.status_code == 200
        b = client.post('/v2/chat',
                        json={'session_id': session, 'text': teach_back(a.json()['message'])},
                        headers=elder_h)
        pending = b.json(); assert pending['approval_digest']
        c = client.post('/v2/family/approve', json={
            'task_id': pending['task_id'], 'approve': True, 'approval_digest': pending['approval_digest']
        }, headers=family_h)
        assert c.status_code == 200 and c.json()['code'] == 'task_completed'


def test_api_requires_bearer(tmp_path):
    app = create_app(tmp_path / 'api2.db', demo_mode=True)
    with TestClient(app) as client:
        assert client.get('/v2/tasks').status_code == 401
        assert client.post('/v2/sessions', json={}).status_code == 401


def test_api_extra_fields_rejected(tmp_path):
    app = create_app(tmp_path / 'api3.db', demo_mode=True)
    with TestClient(app) as client:
        h = login(client, 'elder-demo')
        r = client.post('/v2/sessions', json={'family_id': 'attacker'}, headers=h)
        assert r.status_code == 422


def test_api_idempotency_conflict_409(tmp_path):
    app = create_app(tmp_path / 'api4.db', demo_mode=True)
    with TestClient(app) as client:
        h = login(client, 'elder-demo')
        session = client.post('/v2/sessions', json={}, headers=h).json()['session_id']
        body = {'session_id': session, 'text': '帮我交水费', 'request_id': 'x'}
        assert client.post('/v2/chat', json=body, headers=h).status_code == 200
        body['text'] = '帮我交电费'
        assert client.post('/v2/chat', json=body, headers=h).status_code == 409


def test_api_cross_role_denied(tmp_path):
    app = create_app(tmp_path / 'api5.db', demo_mode=True)
    with TestClient(app) as client:
        family_h = login(client, 'daughter-demo')
        assert client.post('/v2/sessions', json={}, headers=family_h).status_code == 403


def test_demo_login_can_be_disabled(tmp_path):
    app = create_app(tmp_path / 'api6.db', demo_mode=False)
    with TestClient(app) as client:
        assert client.post('/v2/auth/demo', json={'actor_id': 'elder-demo'}).status_code == 404


def test_health(tmp_path):
    app = create_app(tmp_path / 'api7.db', demo_mode=True)
    with TestClient(app) as client:
        data = client.get('/health').json()
        assert data['status'] == 'ok' and data['version'] == '6.0.0' and data['audit_chain_valid'] is True


def test_task_api_returns_privacy_preserving_projection(tmp_path):
    app = create_app(tmp_path / 'api-task-view.db', demo_mode=True)
    with TestClient(app) as client:
        elder_h = login(client, 'elder-demo')
        family_h = login(client, 'daughter-demo')
        session = client.post('/v2/sessions', json={}, headers=elder_h).json()['session_id']
        first = client.post('/v2/chat', json={'session_id': session, 'text': '帮我交水费'}, headers=elder_h).json()
        client.post('/v2/chat', json={'session_id': session, 'text': '我孙子昨天来电话了'}, headers=elder_h)
        tasks = client.get('/v2/tasks', headers=family_h).json()
        task = next(item for item in tasks if item['id'] == first['task_id'])
        assert task['summary'].endswith('68.40元')
        assert task['details']['amount_yuan'] == '68.40'
        serialized = str(task)
        assert 'deferred_topics' not in task
        assert 'slots' not in task
        assert 'semantic_key' not in task
        assert 'elder_confirmation_hash' not in serialized
        assert '孙子昨天来电话' not in serialized


def test_static_ui_does_not_interpolate_server_data_with_innerhtml(tmp_path):
    app = create_app(tmp_path / 'api-static.db', demo_mode=True)
    static_dir = __import__('pathlib').Path(__file__).resolve().parents[1] / 'static'
    family_js = (static_dir / 'family.js').read_text(encoding='utf-8')
    elder_js = (static_dir / 'elder.js').read_text(encoding='utf-8')
    care_js = (static_dir / 'care.js').read_text(encoding='utf-8')
    # Clearing a container is allowed; dynamic values must be inserted using textContent.
    assert 'div.innerHTML = `' not in family_js
    assert 'div.innerHTML = `' not in elder_js
    assert 'innerHTML = `' not in care_js


def test_security_headers_are_set(tmp_path):
    app = create_app(tmp_path / 'api-headers.db', demo_mode=True)
    with TestClient(app) as client:
        response = client.get('/elder')
        assert response.status_code == 200
        assert "default-src 'self'" in response.headers['content-security-policy']
        assert response.headers['x-content-type-options'] == 'nosniff'
        # 有意修改：DENY → SAMEORIGIN，为了桌面演示舞台把真实 App 装进同源 iframe。
        #
        # 这是一处**真的放宽**，不掩饰。保住的安全属性是"第三方站点不能把我们的页面
        # 套进它的框里"——点击劫持的实际威胁面——放开的只有我们自己的 `/stage`。
        # CSP 的 `frame-ancestors 'self'` 与它成对，下面一并钉住。
        #
        # 残余风险：一个同源 XSS 现在可以把我们自己的页面套进框。但在
        # `script-src 'self'` 且无内联、无 CDN 的前提下，同源 XSS 本身已经是通局条件，
        # 套不套框不改变结局。
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
        csp = response.headers['content-security-policy']
        assert "frame-ancestors 'self'" in csp, "跨站套框的防护不能丢"
        assert "frame-ancestors 'none'" not in csp
        # 放宽只到 'self' 为止：出现任何主机名或通配符都说明有人把它继续放开了。
        ancestors = next(
            part.strip() for part in csp.split(";")
            if part.strip().startswith("frame-ancestors")
        )
        assert ancestors.split()[1:] == ["'self'"], f"frame-ancestors 被放开了：{ancestors}"
        assert response.headers['cache-control'] == 'no-store'


def test_v4_care_page_is_served(tmp_path):
    app = create_app(tmp_path / 'api-care-page.db', demo_mode=True)
    with TestClient(app) as client:
        response = client.get('/care')
        assert response.status_code == 200
        # 钉 <h1>，不钉 <title>。
        #
        # 这一条原先断言 `'全景照护中心' in response.text`。照护页重构之后 h1 改成了
        # 「照护中心」，而这条测试**照样绿**——因为 `<title>` 里还留着旧字样。它于是
        # 在校验一个浏览器标签页标题，而不是用户在页面上看得见的任何东西。
        import re
        assert re.search(r"<h1[^>]*>照护中心</h1>", response.text), '照护页没有渲染它自己的主标题'
        assert '/static/care.js' in response.text


def test_generated_openapi_contains_v4_endpoints(tmp_path):
    app = create_app(tmp_path / 'api-openapi-v4.db', demo_mode=True)
    with TestClient(app) as client:
        schema = client.get('/openapi.json').json()
        for path in [
            '/v4/routines', '/v4/emotions/analyze', '/v4/medical-reports/analyze',
            '/v4/medications/interactions/check', '/v4/location/ping',
            '/v4/reports/monthly', '/v4/capabilities',
        ]:
            assert path in schema['paths']
