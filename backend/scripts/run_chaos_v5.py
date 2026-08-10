from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from youhuo.database import Database
from youhuo.models import ActorRole, AuthContext
from youhuo.v5_models import SagaAdvanceRequest, SagaCreateRequest, SagaKind, SagaOutcome
from youhuo.v5_store import V5FeatureStore
from youhuo.provenance import source_digest


def advance(store: V5FeatureStore, actor: AuthContext, saga_id: str, version: int, key: str, output: dict[str, Any], outcome: SagaOutcome = SagaOutcome.SUCCESS, error: str | None = None):
    return store.advance_saga(
        "fam-demo",
        actor,
        saga_id,
        SagaAdvanceRequest(outcome=outcome, output=output, error_code=error, idempotency_key=key, expected_version=version),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=400)
    parser.add_argument("--output", type=Path, default=Path("reports/chaos_v5_400.json"))
    args = parser.parse_args()
    failures: list[dict[str, Any]] = []
    assertions = 0
    completed = 0
    compensated = 0
    conflicts_blocked = 0
    duplicate_replays = 0

    def check(condition: bool, detail: dict[str, Any]) -> None:
        nonlocal assertions
        assertions += 1
        if not condition and len(failures) < 100:
            failures.append(detail)

    with tempfile.TemporaryDirectory() as td:
        db = Database(Path(td) / "chaos.db")
        db.seed_demo()
        store = V5FeatureStore(db)
        elder = AuthContext(actor_id="elder-demo", family_id="fam-demo", role=ActorRole.ELDER, display_name="张奶奶")
        family = AuthContext(actor_id="daughter-demo", family_id="fam-demo", role=ActorRole.FAMILY, display_name="女儿")
        system = AuthContext(actor_id="system-demo", family_id="fam-demo", role=ActorRole.SYSTEM, display_name="系统")
        half = args.scenarios // 2
        for i in range(half):
            saga = store.create_saga("fam-demo", elder.actor_id, SagaCreateRequest(
                elder_id="elder-demo", kind=SagaKind.BILL_PAYMENT, goal="交本月水费", context={"case": i}, request_id=f"chaos-pay-{i}"
            ))
            check(saga.version == 1 and saga.current_step_index == 0, {"case": i, "phase": "create"})
            current = advance(store, system, saga.id, 1, f"p-{i}-1", {"bill_id": f"b{i}", "amount_cents": 1000+i})
            current = advance(store, elder, saga.id, 2, f"p-{i}-2", {"confirmed": True})
            current = advance(store, family, saga.id, 3, f"p-{i}-3", {"approved": True})
            current = advance(store, system, saga.id, 4, f"p-{i}-4", {"request_id": f"req{i}"})
            current = advance(store, system, saga.id, 5, f"p-{i}-5", {"paid": True, "receipt": f"r{i}"})
            current = advance(store, system, saga.id, 6, f"p-{i}-6", {"verified": True})
            check(current.status.value == "completed", {"case": i, "phase": "complete", "status": current.status.value})
            check(current.version == 7, {"case": i, "phase": "version", "version": current.version})
            replay = advance(store, system, saga.id, 6, f"p-{i}-6", {"verified": True})
            check(replay.version == 7, {"case": i, "phase": "idempotency"})
            duplicate_replays += 1
            try:
                advance(store, system, saga.id, 6, f"p-{i}-6", {"verified": False})
            except ValueError:
                conflicts_blocked += 1
            else:
                check(False, {"case": i, "phase": "idempotency_key_reuse_not_blocked"})
            completed += 1

        for i in range(args.scenarios - half):
            saga = store.create_saga("fam-demo", elder.actor_id, SagaCreateRequest(
                elder_id="elder-demo", kind=SagaKind.MEDICAL_APPOINTMENT, goal="挂人民医院骨科", context={"case": i}, request_id=f"chaos-med-{i}"
            ))
            current = advance(store, elder, saga.id, 1, f"m-{i}-1", {"hospital": "人民医院", "department": "骨科"})
            current = advance(store, system, saga.id, 2, f"m-{i}-2", {"reservation": f"hold-{i}"})
            current = advance(store, elder, saga.id, 3, f"m-{i}-3", {}, SagaOutcome.FAILURE, "elder_declined")
            check(current.status.value == "compensated", {"case": i, "phase": "compensate", "status": current.status.value})
            check(current.steps[1].status.value == "compensated", {"case": i, "phase": "release_slot"})
            log = current.context.get("compensation_log", [])
            check(bool(log) and log[0]["compensation"] == "release_slot", {"case": i, "phase": "compensation_log", "log": log})
            try:
                advance(store, system, saga.id, 3, f"m-{i}-4", {}, SagaOutcome.SUCCESS)
            except ValueError:
                conflicts_blocked += 1
            else:
                check(False, {"case": i, "phase": "terminal_advance_not_blocked"})
            compensated += 1
        db.close()

    report = {
        "version": "5.0.0",
        "scenarios": args.scenarios,
        "assertions": assertions,
        "completed_sagas": completed,
        "compensated_sagas": compensated,
        "duplicate_replays": duplicate_replays,
        "invalid_or_conflicting_advances_blocked": conflicts_blocked,
        "failed": len(failures),
        "failures": failures,
        "note": "SQLite沙箱中的故障注入与恢复测试，不代表真实医院/支付平台故障演练。",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 盖上被验证那棵树的指纹。读一份报告不等于跑过一次验证——check_artifacts_v6
    # 会重算并比对，对不上就判过期。见 youhuo/provenance.py。
    report["source_digest"] = source_digest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
