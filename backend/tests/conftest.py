from __future__ import annotations

from datetime import UTC, datetime

import pytest

from youhuo.database import Database
from youhuo.engine import YouHuoEngine
from youhuo.models import SessionCreateRequest
from youhuo.services import FixedClock, Services


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 7, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path, fixed_now):
    db = Database(tmp_path / "test.db")
    db.seed_demo()
    services = Services.build(FixedClock(fixed_now))
    engine = YouHuoEngine(db, services)
    elder = db.auth_context_for_actor("elder-demo")
    family = db.auth_context_for_actor("daughter-demo")
    assert elder and family
    session = engine.create_session(elder, SessionCreateRequest())
    yield db, engine, elder, family, session
    db.close()
