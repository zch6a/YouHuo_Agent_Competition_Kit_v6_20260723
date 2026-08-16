from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from youhuo.database import Database
from youhuo.engine import YouHuoEngine
from youhuo.models import SessionCreateRequest
from youhuo.services import FixedClock, Services


@pytest.fixture(autouse=True, scope="session")
def _never_write_the_database_into_the_repo(tmp_path_factory):
    """跑测试不许在仓库里留下数据库和审计密钥。

    `create_app()` 的库路径默认是 `os.getenv("YOUHUO_DB_PATH", "data/youhuo.db")`
    ——**相对路径**，落在进程启动的那个目录，也就是仓库根。绝大多数测试都老老实实
    传了 `tmp_path / "xxx.db"`，但只要有一个没传，跑一次 pytest 就会在 `data/` 下
    生成一个运行时数据库**和一把新的 HMAC 审计链密钥**。

    这不是假设：`test_baseline_api.py` 和 `test_surface_registry.py` 里共四处
    `create_app()` 没传路径，`check_artifacts_v6` 的 `leaked_artifacts` 每次都能
    在跑完 pytest 之后抓到它们。而这个仓库的远端是公开的，并且有过审计密钥进公开
    仓库的前科——`api.py` 顶部那段注释记的就是同一件事的上一次。

    单独改那四处不够：下一个人写 `create_app()` 时会再犯一次，而且要等到打包检查
    才发现。在这里兜住，整套测试就**结构上**没有能力写进仓库；四处调用也一并改成
    显式传路径，两道都留着。

    session 作用域 + autouse：必须在任何测试导入 app 之前就位。
    """
    os.environ.setdefault(
        "YOUHUO_DB_PATH",
        str(tmp_path_factory.mktemp("youhuo-db") / "suite.db"),
    )


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
