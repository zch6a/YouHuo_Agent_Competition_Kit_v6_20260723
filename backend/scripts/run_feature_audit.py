"""Start a clean server, run the feature-by-feature audit, then shut it down.

Guarantees a truly empty database: SQLite WAL mode keeps -wal/-shm sidecars that
survive deleting the .db alone, which would replay a previous run's rows into a
supposedly clean database and break audit-chain verification.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_ARTIFACTS = (
    "data/youhuo.db",
    "data/youhuo.db-wal",
    "data/youhuo.db-shm",
    "data/youhuo.db.audit.key",
)
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"


def clean_database(retries: int = 20) -> None:
    """Windows keeps the file locked briefly after the server exits."""
    for name in DB_ARTIFACTS:
        path = ROOT / name
        for attempt in range(retries):
            if not path.exists():
                break
            try:
                path.unlink()
                break
            except PermissionError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.25)


def wait_for_server(timeout: float = 40.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/ping", timeout=2) as response:
                if json.loads(response.read())["status"] == "ok":
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    clean_database()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        # 个性化基线要有历史才有东西可验；这个开关默认关闭（见 create_app），
        # 所以审核这里必须显式打开。
        "YOUHUO_SEED_BASELINE": "true",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--app-dir", "backend"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_server():
            print("服务未能启动，功能审核中止。")
            return 1
        result = subprocess.run(
            [sys.executable, str(ROOT / "backend/scripts/verify_features_v6.py"), "--base", BASE],
            cwd=ROOT, env=env,
        )
        return result.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        clean_database()


if __name__ == "__main__":
    raise SystemExit(main())
