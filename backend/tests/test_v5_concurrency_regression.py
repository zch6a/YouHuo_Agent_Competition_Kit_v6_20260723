from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from youhuo.database import Database


def test_shared_sqlite_connection_serializes_concurrent_auth_audit_reads(tmp_path) -> None:
    db = Database(tmp_path / "concurrent.db")
    db.seed_demo()
    now = datetime.now(UTC)
    db.store_auth_token("parallel-token", "elder-demo", now, now + timedelta(hours=1))

    def reader(_: int) -> bool:
        for _ in range(60):
            actor = db.resolve_auth_token("parallel-token")
            if actor is None or actor.actor_id != "elder-demo":
                return False
            if not db.verify_audit_chain("fam-demo"):
                return False
        return True

    def writer(index: int) -> bool:
        for step in range(20):
            db.append_audit("fam-demo", "system-demo", "CONCURRENCY_REGRESSION", f"{index}-{step}", {"step": step})
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(reader, range(12))) + list(pool.map(writer, range(4)))
    assert all(results)
    assert db.verify_audit_chain("fam-demo") is True
    db.close()
