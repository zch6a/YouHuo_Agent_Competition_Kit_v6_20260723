"""The offline neural voice is an upgrade, never a dependency.

These tests pin the contract that matters: with no model configured the service
still works and says so, and the synthesis endpoint stays authenticated and
bounded either way.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.tts import NeuralVoice


def login(client, actor_id):
    r = client.post('/v2/auth/demo', json={'actor_id': actor_id})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def app_without_model(tmp_path, name):
    app = create_app(tmp_path / name, demo_mode=True)
    # Point the voice at a directory that cannot contain a model.
    app.state.db  # noqa: B018 - keep the app fully constructed
    return app


def test_voice_status_reports_unavailable_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUHUO_TTS_MODEL_DIR', str(tmp_path / 'no-such-model'))
    with TestClient(create_app(tmp_path / 'v1.db', demo_mode=True)) as client:
        elder = login(client, 'elder-demo')
        status = client.get('/v6/speech/voice', headers=elder).json()
        assert status['available'] is False
        assert status['model_present'] is False
        assert status['fallback'] == 'browser_speech_synthesis'


def test_synthesis_degrades_with_503_rather_than_failing_the_turn(tmp_path, monkeypatch):
    monkeypatch.setenv('YOUHUO_TTS_MODEL_DIR', str(tmp_path / 'no-such-model'))
    with TestClient(create_app(tmp_path / 'v2.db', demo_mode=True)) as client:
        elder = login(client, 'elder-demo')
        r = client.post('/v6/speech/synthesize', json={'text': '您好'}, headers=elder)
        assert r.status_code == 503
        assert '浏览器语音' in r.json()['detail']


def test_synthesis_requires_authentication(tmp_path):
    with TestClient(create_app(tmp_path / 'v3.db', demo_mode=True)) as client:
        assert client.post('/v6/speech/synthesize', json={'text': '您好'}).status_code == 401
        assert client.get('/v6/speech/voice').status_code == 401


def test_synthesis_input_is_bounded(tmp_path):
    with TestClient(create_app(tmp_path / 'v4.db', demo_mode=True)) as client:
        elder = login(client, 'elder-demo')
        assert client.post('/v6/speech/synthesize',
                           json={'text': '啊' * 400}, headers=elder).status_code == 422
        assert client.post('/v6/speech/synthesize',
                           json={'text': '您好', 'speed': 9.0}, headers=elder).status_code == 422
        assert client.post('/v6/speech/synthesize',
                           json={'text': '您好', 'extra': 1}, headers=elder).status_code == 422


def test_chat_still_works_when_the_voice_is_absent(tmp_path, monkeypatch):
    """The elder turn must never depend on synthesis being available."""
    monkeypatch.setenv('YOUHUO_TTS_MODEL_DIR', str(tmp_path / 'no-such-model'))
    with TestClient(create_app(tmp_path / 'v5.db', demo_mode=True)) as client:
        elder = login(client, 'elder-demo')
        session = client.post('/v2/sessions', json={}, headers=elder).json()['session_id']
        r = client.post('/v2/chat', json={'session_id': session, 'text': '帮我交水费'}, headers=elder)
        assert r.status_code == 200 and r.json()['ui']['speak'] is True


def test_missing_model_is_reported_not_raised(tmp_path):
    voice = NeuralVoice(tmp_path, model_dir='definitely-not-here')
    assert voice.available is False
    assert voice.status()['model_present'] is False
    try:
        voice.synthesize('您好')
    except RuntimeError as exc:
        assert '未安装' in str(exc) or '未找到语音模型' in str(exc)
    else:
        raise AssertionError('缺少模型时必须抛出 RuntimeError 而不是静默返回')
