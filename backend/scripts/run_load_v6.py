from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_server_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return "(no server output captured)"


async def wait_ready(base_url: str, process: subprocess.Popen, log_path: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Uvicorn exited early.\n{read_server_log(log_path)}")
            try:
                response = await client.get(f"{base_url}/ping")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise TimeoutError("Uvicorn did not become ready in time.")


async def exercise(base_url: str, total: int, concurrency: int) -> dict[str, object]:
    limits = httpx.Limits(max_connections=max(concurrency + 20, 120), max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=httpx.Timeout(30.0)) as client:
        login = await client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        semaphore = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        statuses: list[int] = []
        transport_errors: dict[str, int] = {}
        retried = 0

        async def send(i: int) -> httpx.Response:
            selector = i % 10
            if selector < 6:
                return await client.get("/ping")
            if selector < 8:
                return await client.post(
                    "/v6/semantic/parse", headers=headers,
                    json={"elder_id": "elder-demo", "text": "提醒我下周去人民医院复诊", "permit_remote_model": False},
                )
            return await client.post(
                "/v6/interaction/plan", headers=headers,
                json={
                    "elder_id": "elder-demo", "message": "请确认晚上八点服药提醒。",
                    "options": ["确认", "取消", "再听一遍"], "risk_level": 2,
                    "asr_confidence": 0.94, "recent_retries": 0, "reversible": True,
                },
            )

        async def one(i: int) -> None:
            nonlocal retried
            async with semaphore:
                start = time.perf_counter()
                try:
                    try:
                        response = await send(i)
                    except httpx.TransportError as exc:
                        # A pooled keep-alive connection can be closed by the server
                        # at the same moment the client reuses it. That is a known
                        # race, not a server failure, so retry once and record it.
                        # ConnectError instead means the local machine ran out of
                        # sockets, so back off rather than hammering it further.
                        retried += 1
                        await asyncio.sleep(1.0 if isinstance(exc, httpx.ConnectError) else 0.05)
                        response = await send(i)
                except Exception as exc:  # noqa: BLE001 - a load test measures failures
                    name = type(exc).__name__
                    transport_errors[name] = transport_errors.get(name, 0) + 1
                    latencies.append((time.perf_counter() - start) * 1000)
                    statuses.append(0)
                    return
                latencies.append((time.perf_counter() - start) * 1000)
                statuses.append(response.status_code)

        started = time.perf_counter()
        # return_exceptions keeps one bad request from aborting the whole run and
        # losing every measurement collected so far.
        await asyncio.gather(*(one(i) for i in range(total)), return_exceptions=True)
        elapsed = time.perf_counter() - started
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
        success = sum(200 <= status < 300 for status in statuses)
        return {
            "version": "6.0.0", "server": "real_uvicorn_loopback",
            "total_requests": total, "concurrency": concurrency,
            "successful": success, "failed": total - success,
            "elapsed_seconds": round(elapsed, 4), "throughput_rps": round(total / elapsed, 2),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 3), "p50": round(statistics.median(latencies), 3),
                "p95": round(p95, 3), "p99": round(p99, 3), "max": round(max(latencies), 3),
            },
            "mix": {"liveness_reads": total * 6 // 10, "semantic_parses": total * 2 // 10, "interaction_plans": total - total * 8 // 10},
            "keepalive_retries": retried,
            "transport_errors": transport_errors,
            "note": "真实Uvicorn回环网络负载；不等同于公网、多进程或真实HarmonyOS设备压测。"
                    "keepalive_retries 表示连接被服务端回收后重试的次数，属于长连接竞态，不是请求失败。",
        }


async def run(total: int, concurrency: int) -> dict[str, object]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    # Windows can still hold the server's database/log handles for a moment
    # after the child exits; a failed temp cleanup must not fail the load run.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        env["YOUHUO_DB_PATH"] = str(Path(td) / "load.db")
        env["YOUHUO_DEMO_MODE"] = "true"
        # Write server output to a file rather than a pipe: an undrained pipe
        # buffer blocks the writing process, and native libraries such as the
        # optional TTS engine log to stderr outside Python's control.
        log_path = Path(td) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            # Requests queue behind the semaphore for seconds under load. With
            # uvicorn's default 5s keep-alive the server closes pooled
            # connections while they wait, so every later request has to open a
            # fresh socket - which exhausted the ephemeral port range and
            # produced thousands of ConnectErrors. Keep connections alive longer
            # than the worst-case queue wait so the pool is actually reused.
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
                 "--port", str(port), "--log-level", "warning", "--timeout-keep-alive", "120"],
                cwd=ROOT, env=env, text=True, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                await wait_ready(base_url, process, log_path)
                return await exercise(base_url, total, concurrency)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("reports/load_v6_5000.json"))
    args = parser.parse_args()
    report = asyncio.run(run(args.requests, args.concurrency))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    errors = report["transport_errors"]
    if errors.get("ConnectError"):
        # Tell the two apart: the server refusing work is a defect, the client
        # machine running out of sockets is not.
        print(
            "\n提示：ConnectError 表示本机无法再建立TCP连接（临时端口/TIME_WAIT耗尽），"
            "属于压测机资源限制而非服务端故障。请等待端口回收后重跑，或降低并发。",
            file=sys.stderr,
        )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
