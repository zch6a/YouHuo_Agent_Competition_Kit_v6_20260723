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
import tempfile
import time
import urllib.error
from pathlib import Path

# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

ROOT = Path(__file__).resolve().parents[2]
DB_ARTIFACTS = (
    "data/youhuo.db",
    "data/youhuo.db-wal",
    "data/youhuo.db-shm",
    "data/youhuo.db.audit.key",
)
def _free_port() -> int:
    """向系统要一个空闲端口，不写死。

    原先是 `PORT = 8011`。这个脚本每轮都要起一个服务器再关掉，而刚关掉的监听端口
    会停在 TIME_WAIT——于是紧挨着重跑一次（比如手工验证完立刻跑整条链）就会
    「服务未能启动」。**2026-08-14 这一天整条验证链两次报红都是它**，两次都不是
    代码问题。`check_contrast.py:_free_port()` 早就为同一件事写着一整段说明，
    这个脚本没跟上。

    那一段的两条教训一并照抄：不保持 socket 打开来占位（那样 uvicorn 自己也
    bind 不上），并且记住本进程发过的号（"bind 0、读号、close" 连调两次可能
    拿到同一个）。
    """
    import socket

    issued: set[int] = getattr(_free_port, "_issued", set())
    _free_port._issued = issued  # type: ignore[attr-defined]
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port in issued:
            continue
        issued.add(port)
        return port
    raise RuntimeError("连 50 次都没要到一个没发过的端口")


PORT = _free_port()
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
    """等服务器起来。**用 `open_local`，不能用裸 `urlopen`。**

    这台机器上有 `HTTP_PROXY=http://127.0.0.1:7897`。实测：服务器已经打印
    `Uvicorn running`，而这个循环连打 15 次 `/ping` 全部 `urlopen error timed out`
    ——**服务器自己的日志里一条请求都没有**，也就是那些请求根本没到它这儿，
    是被送去代理挂死的；第 16 次才通。而这个循环原本是 40s 上限、每次 2s 超时
    加 0.5s 间隔 ≈ 16 次，**正好卡在边界上**。所以它时灵时不灵，报出来的话是
    「服务未能启动」——把**代理配置**说成**服务器起不来**。2026-08-14 整条验证链
    两次报红都是它。理由与做法都在 `localhttp.py` 里，那里是唯一一份实现
    （第一版我在这个文件里另写了一个 opener，两份实现必然漂）。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open_local(f"{BASE}/ping", timeout=2) as response:
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
        # 不让子进程缓冲自己的输出。上面那个日志文件在服务器**还活着**的时候
        # 读出来是空的——`log.flush()` 只刷我这边的句柄，刷不到它那边。
        # 第一次实测正好是 bind 失败、进程已退出（缓冲随之落盘），所以那次看起来是好的。
        "PYTHONUNBUFFERED": "1",
    }
    # 服务器的输出收进一个临时文件，**不是 DEVNULL**。
    #
    # 原先两路都丢进 DEVNULL，于是它起不来时这道检查只会说「服务未能启动，功能审核
    # 中止。」——一句不含任何原因的话。实测撞上过一次（端口 8011 处于 TIME_WAIT），
    # 为了知道是什么，我不得不在外面手工重跑一遍。真正的原因当时就打印在 stderr 上，
    # 只是被扔掉了。
    log = tempfile.NamedTemporaryFile(
        mode="w+", suffix=".log", prefix="youhuo-audit-server-",
        encoding="utf-8", delete=False)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--app-dir", "backend"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_for_server():
            log.flush()
            try:
                tail = Path(log.name).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                tail = f"（连服务器日志都读不到：{exc}）"
            print(f"服务未能启动（端口 {PORT}），功能审核中止。它自己说的是：")
            for line in (tail.strip().splitlines() or ["（一个字都没输出）"])[-15:]:
                print(f"    {line}")
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
        # 日志文件自己删掉（`delete=False` 是为了在服务器还活着的时候也能读它——
        # Windows 上一个 `delete=True` 的 NamedTemporaryFile 没法被第二个句柄打开）。
        # 重试，理由和 `clean_database()` 的 docstring 一样：Windows 在子进程退出后
        # 还会短暂持有这个文件。实测两次连跑会漏下一个——单次 unlink 是够不着的。
        try:
            log.close()
        except OSError:
            pass
        for attempt in range(20):
            try:
                Path(log.name).unlink(missing_ok=True)
                break
            except OSError:
                if attempt == 19:
                    print(f"（没能删掉临时日志 {log.name}，不影响结论）")
                else:
                    time.sleep(0.25)
        clean_database()


if __name__ == "__main__":
    raise SystemExit(main())
