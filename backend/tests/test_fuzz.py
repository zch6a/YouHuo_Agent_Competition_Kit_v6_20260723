from __future__ import annotations

import random
import string

from youhuo.models import ChatRequest
from youhuo.utils import clean_user_text, parse_time_text


def test_random_unicode_input_never_crashes_engine(env):
    db, engine, elder, family, session = env
    rng = random.Random(20260722)
    alphabet = string.ascii_letters + string.digits + "帮我交水费挂号提醒孙子确认取消，。！？\u200b\uff21"
    for i in range(500):
        raw = ''.join(rng.choice(alphabet) for _ in range(rng.randint(1, 80)))
        cleaned = clean_user_text(raw, max_length=2000)
        result = engine.handle(elder, ChatRequest(session_id=session.session_id, text=cleaned, request_id=f'fuzz-{i}'))
        assert result.message
        # Cancel any active task periodically so fuzz cases remain independent.
        if i % 7 == 0:
            engine.handle(elder, ChatRequest(session_id=session.session_id, text='取消任务', request_id=f'cancel-{i}'))


def test_random_time_parser_bounds():
    rng = random.Random(7)
    for _ in range(2000):
        h = rng.randint(0, 40); m = rng.randint(0, 99)
        parsed = parse_time_text(f'{h}:{m:02d}')
        if parsed is not None:
            hh, mm = map(int, parsed.split(':'))
            assert 0 <= hh <= 23 and 0 <= mm <= 59
