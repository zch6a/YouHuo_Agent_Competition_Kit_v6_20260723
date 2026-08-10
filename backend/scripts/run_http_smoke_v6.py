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

# 这个脚本不 import 应用代码（它只打 HTTP），但报告要盖上被验证那棵树的指纹，
# 所以把 backend/ 放进路径。见 youhuo/provenance.py。
sys.path.insert(0, str(ROOT / "backend"))
from youhuo.provenance import source_digest  # noqa: E402


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
    # Windows can still hold the server's log handle for a moment after the
    # child exits; a failed temp cleanup must not fail the smoke test.
    with tempfile.TemporaryDirectory(prefix="youhuo-v6-http-", ignore_cleanup_errors=True) as td:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        env["YOUHUO_DB_PATH"] = str(Path(td) / "smoke.db")
        env["YOUHUO_DEMO_MODE"] = "true"
        # A file, not a pipe: an undrained pipe buffer blocks the server, and
        # native libraries log to stderr outside Python's control.
        log_path = Path(td) / "server.log"
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15.0) as client:
                # Generous: this stage runs straight after the load test, when the
                # machine still has thousands of sockets in TIME_WAIT.
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            "server exited early\n"
                            + log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                        )
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
                assert h["version"] == "6.0.0" and h["audit_chain_valid"] is True
                assert "default-src 'self'" in health.headers["content-security-policy"]
                assert client.get("/judge").status_code == 200
                elder, family = login(client, "elder-demo"), login(client, "daughter-demo")

                default_profile = client.get("/v6/profiles/elder-demo", headers=elder)
                default_profile.raise_for_status()
                assert default_profile.json()["teach_back_high_risk"] is True

                saved = client.put(
                    "/v6/profiles/elder-demo",
                    headers=elder,
                    json={
                        "elder_id": "elder-demo", "speech_rate": 0.8, "verbosity": "gentle",
                        "max_options": 2, "max_sentence_chars": 38, "repeat_sensitive": True,
                        "teach_back_high_risk": True, "font_scale": 1.4,
                        "hearing_support": True, "dialect_hint": "东北话",
                    },
                )
                saved.raise_for_status()
                assert saved.json()["version"] >= 1 and saved.json()["font_scale"] == 1.4

                plan = post(client, "/v6/interaction/plan", {
                    "elder_id": "elder-demo",
                    "message": "请确认本月水费126.50元，之后请家人完成支付。",
                    "options": ["确认", "取消", "再听一遍", "问家人"],
                    "risk_level": 4, "asr_confidence": 0.75,
                    "recent_retries": 1, "reversible": False,
                }, elder)
                assert plan["mode"] == "one_question" and plan["require_teach_back"] is True
                assert len(plan["visible_options"]) <= 1

                semantic = post(client, "/v6/semantic/parse", {
                    "elder_id": "elder-demo", "text": "提醒我下周去人民医院复诊", "permit_remote_model": False,
                }, elder)
                assert semantic["intent"] == "reminder" and semantic["model_used"] is False

                preview = post(client, "/v6/actions/preview", {
                    "elder_id": "elder-demo", "goal": "帮我交本月水费", "action": "create_payment_request",
                    "arguments": {"bill_id": "b1", "amount_cents": 6840, "elder_id": "elder-demo"},
                    "facts": [
                        {"name": "bill_id", "value": "b1", "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                        {"name": "amount_cents", "value": 6840, "origin": "trusted_tool", "purpose": "bill_payment", "trusted_for_control": True},
                        {"name": "amount_cents", "value": 999999, "origin": "untrusted_document", "purpose": "bill_payment"},
                        {"name": "elder_id", "value": "elder-demo", "origin": "system", "sensitivity": 3, "purpose": "bill_payment", "trusted_for_control": True},
                    ],
                    "user_confirmed": True, "family_approvals": 1, "reversible": True,
                }, elder)
                assert preview["authorization"]["decision"] == "clarify"
                assert "amount_cents" in preview["authorization"]["stripped_fields"]

                card = post(client, "/v6/reliance/card", {
                    "elder_id": "elder-demo", "heard_text": "帮我交水费", "goal": "准备支付请求",
                    "current_step": "核对金额", "action": "create_payment_request", "risk_level": 4,
                    "reversible": True, "confirmations": ["老人复述金额"],
                    "evidence": [
                        {"label": "账单服务", "source": "trusted_tool", "trusted": True, "verified": True},
                        {"label": "账单照片", "source": "camera_ocr", "trusted": False, "verified": False},
                    ],
                    "next_step": "老人确认后请家属接力",
                }, elder)
                assert card["warning"] and "家属" in card["who_decides"]

                session = post(client, "/v6/studies/sessions", {
                    "participant_code": "E001", "role": "elder", "consent_version": "v1",
                    "age_band": "70-79", "device_type": "phone", "notes": "consented smoke record",
                }, family)
                observation = post(client, "/v6/studies/observations", {
                    "session_id": session["id"], "scenario": "语音挂号", "success": True,
                    "duration_seconds": 58.2, "clarification_count": 1, "assistance_count": 0,
                    "perceived_ease": 4, "trust_calibration": 4,
                }, family)
                assert observation["success"] is True
                summary = client.get("/v6/studies/summary", headers=family)
                summary.raise_for_status()
                assert summary.json()["session_count"] == 1 and summary.json()["task_success_rate"] == 1.0

                board = client.get("/v6/competition/evidence", headers=family)
                board.raise_for_status()
                payload = board.json()
                assert sum(item["score_weight"] for item in payload["items"]) == 100
                assert len(payload["top_three_story"]) == 3

                return {
                    "version": "6.0.0", "passed": True, "server": "real_uvicorn_loopback",
                    "checks": {
                        "health_and_security_headers": True,
                        "judge_walkthrough_page": True,
                        "interaction_profile_and_teach_back": True,
                        "medical_reminder_intent_priority": True,
                        "trusted_untrusted_value_conflict_blocked": True,
                        "glass_box_reliance_card": True,
                        "consented_user_study_registry": True,
                        "competition_evidence_board": True,
                    },
                }
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            log_handle.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/http_smoke_v6.json"))
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 盖上被验证那棵树的指纹。读一份报告不等于跑过一次验证——check_artifacts_v6
    # 会重算并比对，对不上就判过期。见 youhuo/provenance.py。
    result["source_digest"] = source_digest()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
