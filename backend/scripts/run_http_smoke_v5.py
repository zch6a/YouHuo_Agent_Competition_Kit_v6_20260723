from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def login(client: httpx.Client, actor_id: str) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": actor_id})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def post(client: httpx.Client, path: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    r = client.post(path, json=body, headers=headers)
    r.raise_for_status()
    return r.json()


def run() -> dict[str, Any]:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="youhuo-v5-http-") as td:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        env["YOUHUO_DB_PATH"] = str(Path(td) / "smoke.db")
        env["YOUHUO_DEMO_MODE"] = "true"
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate(timeout=2)
                        raise RuntimeError(f"server exited early\nstdout={stdout}\nstderr={stderr}")
                    try:
                        health = client.get("/health")
                        if health.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("server did not become healthy")

                h = health.json()
                assert h["version"] == "5.0.0" and h["audit_chain_valid"] is True
                assert "default-src 'self'" in health.headers["content-security-policy"]
                assert client.get("/trust").status_code == 200
                elder, family, system = login(client, "elder-demo"), login(client, "daughter-demo"), login(client, "system-demo")

                voice = post(client, "/v5/voice/resolve", {
                    "elder_id": "elder-demo",
                    "candidates": [
                        {"text": "帮我交水费", "confidence": 0.96, "engine": "harmony"},
                        {"text": "帮我缴水费", "confidence": 0.92, "engine": "backup"},
                    ],
                    "side_effect_possible": True,
                }, elder)
                assert voice["status"] == "accepted" and voice["semantic_intent"] == "bill_payment"

                attack = post(client, "/v5/actions/authorize", {
                    "elder_id": "elder-demo", "goal": "帮我交本月水费", "action": "create_payment_request",
                    "arguments": {"bill_id": "b1", "amount_cents": 999999, "elder_id": "elder-demo"},
                    "facts": [
                        {"name": "bill_id", "value": "b1", "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                        {"name": "amount_cents", "value": 999999, "origin": "untrusted_document", "purpose": "bill_payment"},
                        {"name": "elder_id", "value": "elder-demo", "origin": "system", "sensitivity": 3, "purpose": "bill_payment", "trusted_for_control": True},
                    ],
                    "user_confirmed": True, "family_approvals": 1,
                }, elder)
                assert attack["decision"] == "clarify" and "amount_cents" in attack["stripped_fields"]

                saga = post(client, "/v5/sagas", {
                    "elder_id": "elder-demo", "kind": "bill_payment", "goal": "交本月水费", "request_id": "http-v5-saga"
                }, elder)
                saga = post(client, f"/v5/sagas/{saga['id']}/advance", {
                    "outcome": "success", "output": {"bill_id": "b1", "amount_cents": 6840}, "idempotency_key": "h1", "expected_version": 1
                }, system)
                assert saga["status"] == "awaiting_human"
                saga = post(client, f"/v5/sagas/{saga['id']}/advance", {
                    "outcome": "success", "output": {"confirmed": True}, "idempotency_key": "h2", "expected_version": 2
                }, elder)
                saga = post(client, f"/v5/sagas/{saga['id']}/advance", {
                    "outcome": "success", "output": {"approved": True}, "idempotency_key": "h3", "expected_version": 3
                }, family)
                assert saga["version"] == 4

                break_glass = post(client, "/v5/break-glass", {
                    "elder_id": "elder-demo", "reason": "老人呼救且电话无法接通", "scopes": ["location", "health_summary"], "duration_minutes": 10
                }, family)
                assert break_glass["status"] == "active"
                view = client.get(f"/v5/break-glass/{break_glass['id']}/view", headers=family)
                view.raise_for_status()
                assert "companion_chat" not in json.dumps(view.json(), ensure_ascii=False)

                truth = client.get("/v5/capability-truth", headers=elder)
                truth.raise_for_status()
                metrics = client.get("/v5/metrics", headers=family)
                metrics.raise_for_status()
                assert any("目的绑定" in item for item in truth.json()["implemented_and_tested"])
                return {
                    "version": "5.0.0", "passed": True, "server": "real_uvicorn_loopback",
                    "checks": {
                        "health_and_security_headers": True,
                        "trust_lab_page": True,
                        "n_best_voice_consensus": True,
                        "untrusted_document_control_blocked": True,
                        "durable_saga_role_gates": True,
                        "break_glass_minimum_scope": True,
                        "capability_truth_and_metrics": True,
                    },
                }
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/http_smoke_v5.json"))
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
