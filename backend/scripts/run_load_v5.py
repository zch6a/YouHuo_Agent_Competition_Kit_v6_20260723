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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_ready(base_url: str, process: subprocess.Popen[str], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=2)
                raise RuntimeError(f"Uvicorn exited early.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
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
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=timeout) as client:
        login = await client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        semaphore = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        statuses: list[int] = []

        async def one(i: int) -> None:
            async with semaphore:
                start = time.perf_counter()
                if i % 5:
                    response = await client.get("/ping")
                else:
                    response = await client.post(
                        "/v5/voice/resolve",
                        headers=headers,
                        json={
                            "elder_id": "elder-demo",
                            "candidates": [
                                {"text": "晚上八点提醒我吃药", "confidence": 0.96, "engine": "load-a"},
                                {"text": "晚上8点提醒吃药", "confidence": 0.91, "engine": "load-b"},
                            ],
                            "side_effect_possible": False,
                        },
                    )
                latencies.append((time.perf_counter() - start) * 1000)
                statuses.append(response.status_code)

        started = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(total)))
        elapsed = time.perf_counter() - started
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
        success = sum(200 <= status < 300 for status in statuses)
        return {
            "version": "5.0.0",
            "server": "real_uvicorn_loopback",
            "total_requests": total,
            "concurrency": concurrency,
            "successful": success,
            "failed": total - success,
            "elapsed_seconds": round(elapsed, 4),
            "throughput_rps": round(total / elapsed, 2),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 3),
                "p50": round(statistics.median(latencies), 3),
                "p95": round(p95, 3),
                "p99": round(p99, 3),
                "max": round(max(latencies), 3),
            },
            "mix": {"liveness_reads": total - total // 5, "voice_writes": total // 5},
            "note": "真实Uvicorn回环网络负载；单机SQLite比赛原型按数据库请求串行化，不等同于公网、多进程或分布式生产压测。",
        }


async def run(total: int, concurrency: int) -> dict[str, object]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        backend = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = str(backend)
        env["YOUHUO_DB_PATH"] = str(Path(td) / "load.db")
        env["YOUHUO_DEMO_MODE"] = "true"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "youhuo.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=backend.parent,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            await wait_ready(base_url, process)
            return await exercise(base_url, total, concurrency)
        finally:
            process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("reports/load_v5_5000.json"))
    args = parser.parse_args()
    report = asyncio.run(run(args.requests, args.concurrency))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
