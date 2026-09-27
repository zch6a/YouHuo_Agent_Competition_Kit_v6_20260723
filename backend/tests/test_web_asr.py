import io
import wave

import pytest
from fastapi.testclient import TestClient
from youhuo.api import create_app
from youhuo.web_asr import WebEars


def wav(seconds=1, rate=16000):
    b = io.BytesIO()
    with wave.open(b, 'wb') as w:
        w.setparams((1, 2, rate, 0, 'NONE', ''))
        w.writeframes(bytes(int(rate * seconds) * 2))
    return b.getvalue()


def test_audio_validation_and_busy_guard():
    ears = WebEars()
    ears.model = object()
    with pytest.raises(ValueError):
        ears.transcribe(wav(rate=8000))
    with pytest.raises(ValueError):
        ears.transcribe(wav(seconds=21))
    with pytest.raises(ValueError):
        ears.transcribe(b'broken')
    ears.decode_lock.acquire()
    with pytest.raises(RuntimeError, match='另一段'):
        ears.transcribe(wav())
    ears.decode_lock.release()


def test_web_audio_auth_limits_and_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(WebEars, 'status', lambda _: {'available': True, 'warming': False})
    heard = []
    def transcribe(_, data):
        heard.append(data)
        return {'text': '明天浇花', 'heard': True, 'seconds': 1, 'kind': 'vosk-cn'}
    monkeypatch.setattr(WebEars, 'transcribe', transcribe)
    with TestClient(create_app(tmp_path / 'voice.db', demo_mode=True)) as client:
        assert client.get('/api/v1/listen/web/status').status_code == 401
        assert client.post('/api/v1/listen/web', content=wav()).status_code == 401
        token = client.post('/v2/auth/demo', json={'actor_id': 'elder-demo'}).json()['access_token']
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'audio/wav'}
        assert client.get('/api/v1/listen/web/status', headers=headers).json()['available']
        assert client.post('/api/v1/listen/web', headers=headers, content=bytes(640045)).status_code == 413
        assert not heard
        r = client.post('/api/v1/listen/web', headers=headers, content=wav())
        assert r.status_code == 200
        assert r.json()['text'] == '明天浇花'
        assert heard == [wav()]
        monkeypatch.setattr(WebEars, 'transcribe', lambda *_: (_ for _ in ()).throw(RuntimeError('正在准备')))
        assert client.post('/api/v1/listen/web', headers=headers, content=wav()).status_code == 503
