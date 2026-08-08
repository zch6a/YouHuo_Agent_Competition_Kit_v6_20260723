from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .database import Database, iso, utcnow
from .models import ActorRole, AuthContext
from .utils import canonical_json, new_id, request_fingerprint
from .v5_models import (
    ActionAuthorization,
    ActionAuthorizeRequest,
    BreakGlassRecord,
    BreakGlassRequest,
    MetricsSnapshot,
    PrivacyCategory,
    PrivacyEraseResult,
    PrivacyExportBundle,
    SagaAdvanceRequest,
    SagaCreateRequest,
    SagaKind,
    SagaOutcome,
    SagaRecord,
    SagaStatus,
    SagaStepRecord,
    SagaStepStatus,
    SyncConflictRecord,
    SyncConflictResolutionRequest,
    SyncOperationRequest,
    SyncOperationResult,
    SyncOutcome,
    SyncSensitivity,
    TaskProofBundle,
    TraceSpanCreate,
    VoiceTurnRequest,
    VoiceTurnResolution,
)
from .v5_services import MetricsCalculator, PrivacyRedactor, SagaCatalog, SyncConflictPolicy


class V5FeatureStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db._conn  # The feature store shares the Database transaction/lock boundary.

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_turns_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                request_json TEXT NOT NULL,
                resolution_json TEXT NOT NULL,
                status TEXT NOT NULL,
                intent TEXT NOT NULL,
                consensus_digest TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_voice_turns_v5_family ON voice_turns_v5(family_id,elder_id,created_at);

            CREATE TABLE IF NOT EXISTS policy_decisions_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                action TEXT NOT NULL,
                goal_digest TEXT NOT NULL,
                decision TEXT NOT NULL,
                decision_digest TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_policy_decisions_v5_family ON policy_decisions_v5(family_id,created_at);

            CREATE TABLE IF NOT EXISTS sagas_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                kind TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step_index INTEGER NOT NULL,
                context_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_by TEXT NOT NULL REFERENCES actors(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sagas_v5_family_status ON sagas_v5(family_id,status,updated_at);

            CREATE TABLE IF NOT EXISTS saga_steps_v5(
                id TEXT PRIMARY KEY,
                saga_id TEXT NOT NULL REFERENCES sagas_v5(id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_human INTEGER NOT NULL CHECK(requires_human IN (0,1)),
                reversible INTEGER NOT NULL CHECK(reversible IN (0,1)),
                compensation_name TEXT,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                error_code TEXT,
                started_at TEXT,
                completed_at TEXT,
                UNIQUE(saga_id,step_index)
            );

            CREATE TABLE IF NOT EXISTS saga_advances_v5(
                saga_id TEXT NOT NULL REFERENCES sagas_v5(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                version_after INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(saga_id,idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS sync_entities_v5(
                family_id TEXT NOT NULL REFERENCES families(id),
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                value_json TEXT NOT NULL,
                version INTEGER NOT NULL,
                lamport_clock INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(family_id,entity_type,entity_id,field_name)
            );

            CREATE TABLE IF NOT EXISTS sync_operations_v5(
                operation_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                device_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                base_version INTEGER NOT NULL,
                resulting_version INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_conflicts_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                current_value_json TEXT NOT NULL,
                incoming_value_json TEXT NOT NULL,
                current_version INTEGER NOT NULL,
                incoming_base_version INTEGER NOT NULL,
                sensitivity TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sync_conflicts_v5_family ON sync_conflicts_v5(family_id,status,created_at);

            CREATE TABLE IF NOT EXISTS break_glass_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                requested_by TEXT NOT NULL REFERENCES actors(id),
                reason TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_break_glass_v5_family ON break_glass_v5(family_id,elder_id,status,expires_at);

            CREATE TABLE IF NOT EXISTS proof_bundles_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                task_id TEXT NOT NULL REFERENCES tasks(id),
                proof_digest TEXT NOT NULL UNIQUE,
                bundle_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trace_spans_v5(
                trace_id TEXT NOT NULL,
                span_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                parent_span_id TEXT,
                name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                status TEXT NOT NULL,
                attributes_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trace_spans_v5_family ON trace_spans_v5(family_id,started_at);

            CREATE TABLE IF NOT EXISTS privacy_actions_v5(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                action TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                affected_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def ensure_elder(self, family_id: str, elder_id: str) -> None:
        if not self.db.actor_in_family(elder_id, family_id, ActorRole.ELDER.value):
            raise PermissionError("老人账户不属于当前家庭。")

    def record_voice_turn(
        self,
        family_id: str,
        actor_id: str,
        payload: VoiceTurnRequest,
        result: VoiceTurnResolution,
    ) -> str:
        self.ensure_elder(family_id, payload.elder_id)
        turn_id = new_id("voice")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO voice_turns_v5(
                    id,family_id,elder_id,actor_id,request_json,resolution_json,status,intent,consensus_digest,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    turn_id,
                    family_id,
                    payload.elder_id,
                    actor_id,
                    canonical_json(payload.model_dump(mode="json")),
                    canonical_json(result.model_dump(mode="json")),
                    result.status.value,
                    result.semantic_intent,
                    result.consensus_digest,
                    iso(utcnow()),
                ),
            )
        return turn_id

    def record_policy_decision(
        self,
        family_id: str,
        actor_id: str,
        payload: ActionAuthorizeRequest,
        result: ActionAuthorization,
    ) -> str:
        self.ensure_elder(family_id, payload.elder_id)
        decision_id = new_id("policy")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO policy_decisions_v5(
                    id,family_id,elder_id,actor_id,action,goal_digest,decision,decision_digest,request_json,result_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    family_id,
                    payload.elder_id,
                    actor_id,
                    payload.action,
                    hashlib.sha256(payload.goal.encode("utf-8")).hexdigest(),
                    result.decision.value,
                    result.decision_digest,
                    canonical_json(payload.model_dump(mode="json")),
                    canonical_json(result.model_dump(mode="json")),
                    iso(utcnow()),
                ),
            )
        return decision_id

    # ----- durable saga -----
    def create_saga(self, family_id: str, actor_id: str, payload: SagaCreateRequest) -> SagaRecord:
        self.ensure_elder(family_id, payload.elder_id)
        if payload.request_id:
            row = self.conn.execute(
                "SELECT id FROM sagas_v5 WHERE family_id=? AND json_extract(context_json,'$._request_id')=?",
                (family_id, payload.request_id),
            ).fetchone()
            if row:
                existing = self.get_saga(family_id, row["id"])
                assert existing
                return existing
        now = utcnow()
        saga_id = new_id("saga")
        definitions = SagaCatalog.steps(payload.kind)
        first_status = SagaStepStatus.AWAITING_HUMAN if definitions[0].requires_human else SagaStepStatus.RUNNING
        saga_status = SagaStatus.AWAITING_HUMAN if definitions[0].requires_human else SagaStatus.ACTIVE
        context = dict(payload.context)
        if payload.request_id:
            context["_request_id"] = payload.request_id
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO sagas_v5(
                    id,family_id,elder_id,kind,goal,status,current_step_index,context_json,version,created_by,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    saga_id,
                    family_id,
                    payload.elder_id,
                    payload.kind.value,
                    payload.goal,
                    saga_status.value,
                    0,
                    canonical_json(context),
                    1,
                    actor_id,
                    iso(now),
                    iso(now),
                ),
            )
            for index, definition in enumerate(definitions):
                status = first_status if index == 0 else SagaStepStatus.PENDING
                conn.execute(
                    """INSERT INTO saga_steps_v5(
                        id,saga_id,step_index,name,status,requires_human,reversible,compensation_name,
                        input_json,output_json,error_code,started_at,completed_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id("step"),
                        saga_id,
                        index,
                        definition.name,
                        status.value,
                        int(definition.requires_human),
                        int(definition.reversible),
                        definition.compensation_name,
                        canonical_json(context if index == 0 else {}),
                        "{}",
                        None,
                        iso(now) if index == 0 else None,
                        None,
                    ),
                )
        saga = self.get_saga(family_id, saga_id)
        assert saga
        return saga

    def get_saga(self, family_id: str, saga_id: str) -> SagaRecord | None:
        row = self.conn.execute("SELECT * FROM sagas_v5 WHERE id=? AND family_id=?", (saga_id, family_id)).fetchone()
        if not row:
            return None
        steps = self.conn.execute(
            "SELECT * FROM saga_steps_v5 WHERE saga_id=? ORDER BY step_index", (saga_id,)
        ).fetchall()
        return self._row_saga(row, steps)

    def list_sagas(self, family_id: str, elder_id: str | None = None) -> list[SagaRecord]:
        if elder_id:
            self.ensure_elder(family_id, elder_id)
            rows = self.conn.execute(
                "SELECT * FROM sagas_v5 WHERE family_id=? AND elder_id=? ORDER BY updated_at DESC", (family_id, elder_id)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM sagas_v5 WHERE family_id=? ORDER BY updated_at DESC", (family_id,)
            ).fetchall()
        return [
            self._row_saga(
                row,
                self.conn.execute("SELECT * FROM saga_steps_v5 WHERE saga_id=? ORDER BY step_index", (row["id"],)).fetchall(),
            )
            for row in rows
        ]

    @staticmethod
    def _row_saga(row: sqlite3.Row, steps: list[sqlite3.Row]) -> SagaRecord:
        return SagaRecord(
            id=row["id"],
            family_id=row["family_id"],
            elder_id=row["elder_id"],
            kind=SagaKind(row["kind"]),
            goal=row["goal"],
            status=SagaStatus(row["status"]),
            current_step_index=row["current_step_index"],
            context=json.loads(row["context_json"]),
            version=row["version"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            steps=[
                SagaStepRecord(
                    id=step["id"],
                    saga_id=step["saga_id"],
                    step_index=step["step_index"],
                    name=step["name"],
                    status=SagaStepStatus(step["status"]),
                    requires_human=bool(step["requires_human"]),
                    reversible=bool(step["reversible"]),
                    compensation_name=step["compensation_name"],
                    input_data=json.loads(step["input_json"]),
                    output_data=json.loads(step["output_json"]),
                    error_code=step["error_code"],
                    started_at=datetime.fromisoformat(step["started_at"]) if step["started_at"] else None,
                    completed_at=datetime.fromisoformat(step["completed_at"]) if step["completed_at"] else None,
                )
                for step in steps
            ],
        )

    def advance_saga(
        self,
        family_id: str,
        actor: AuthContext,
        saga_id: str,
        payload: SagaAdvanceRequest,
    ) -> SagaRecord:
        fingerprint = request_fingerprint(payload.model_dump(mode="json"))
        duplicate = self.conn.execute(
            "SELECT request_fingerprint FROM saga_advances_v5 WHERE saga_id=? AND idempotency_key=?",
            (saga_id, payload.idempotency_key),
        ).fetchone()
        if duplicate:
            if duplicate["request_fingerprint"] != fingerprint:
                raise ValueError("同一个幂等键被用于不同的Saga推进内容。")
            existing = self.get_saga(family_id, saga_id)
            if not existing:
                raise ValueError("Saga不存在。")
            return existing
        saga = self.get_saga(family_id, saga_id)
        if not saga:
            raise ValueError("Saga不存在或不属于当前家庭。")
        if actor.role == ActorRole.ELDER and saga.elder_id != actor.actor_id:
            raise PermissionError("只能推进自己的任务。")
        if saga.version != payload.expected_version:
            raise ValueError(f"Saga版本冲突：当前版本为{saga.version}。")
        if saga.status in {SagaStatus.COMPLETED, SagaStatus.COMPENSATED, SagaStatus.CANCELLED}:
            raise ValueError("Saga已经结束。")
        step = saga.steps[saga.current_step_index]
        if step.requires_human:
            elder_steps = {"collect_preferences", "elder_confirm"}
            family_steps = {"family_approval", "family_review"}
            if step.name in elder_steps and actor.role != ActorRole.ELDER:
                raise PermissionError("该步骤必须由老人本人确认。")
            if step.name in family_steps and actor.role != ActorRole.FAMILY:
                raise PermissionError("该步骤必须由绑定家属确认。")
            if step.name not in elder_steps | family_steps and actor.role not in {ActorRole.ELDER, ActorRole.FAMILY}:
                raise PermissionError("该步骤必须由老人或绑定家属推进。")
        elif actor.role != ActorRole.SYSTEM:
            raise PermissionError("自动工具步骤只能由受控系统执行层推进。")
        now = utcnow()
        next_version = saga.version + 1
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM sagas_v5 WHERE id=? AND family_id=?", (saga_id, family_id)
            ).fetchone()
            if not current or current["version"] != payload.expected_version:
                raise ValueError("Saga在提交期间被其他设备更新，请刷新后重试。")
            if payload.outcome == SagaOutcome.SUCCESS:
                conn.execute(
                    """UPDATE saga_steps_v5 SET status=?,output_json=?,error_code=NULL,completed_at=?
                       WHERE saga_id=? AND step_index=?""",
                    (SagaStepStatus.COMPLETED.value, canonical_json(payload.output), iso(now), saga_id, saga.current_step_index),
                )
                if saga.current_step_index + 1 >= len(saga.steps):
                    new_status = SagaStatus.COMPLETED
                    new_index = saga.current_step_index
                else:
                    new_index = saga.current_step_index + 1
                    next_step = saga.steps[new_index]
                    next_step_status = (
                        SagaStepStatus.AWAITING_HUMAN if next_step.requires_human else SagaStepStatus.RUNNING
                    )
                    new_status = SagaStatus.AWAITING_HUMAN if next_step.requires_human else SagaStatus.ACTIVE
                    conn.execute(
                        """UPDATE saga_steps_v5 SET status=?,input_json=?,started_at=?
                           WHERE saga_id=? AND step_index=?""",
                        (next_step_status.value, canonical_json(payload.output), iso(now), saga_id, new_index),
                    )
                context = json.loads(current["context_json"])
                context[f"step_{saga.current_step_index}_output"] = payload.output
                conn.execute(
                    """UPDATE sagas_v5 SET status=?,current_step_index=?,context_json=?,version=?,updated_at=? WHERE id=?""",
                    (new_status.value, new_index, canonical_json(context), next_version, iso(now), saga_id),
                )
            elif payload.outcome == SagaOutcome.WAITING:
                conn.execute(
                    """UPDATE saga_steps_v5 SET status=?,output_json=?,error_code=? WHERE saga_id=? AND step_index=?""",
                    (
                        SagaStepStatus.AWAITING_HUMAN.value,
                        canonical_json(payload.output),
                        payload.error_code,
                        saga_id,
                        saga.current_step_index,
                    ),
                )
                conn.execute(
                    "UPDATE sagas_v5 SET status=?,version=?,updated_at=? WHERE id=?",
                    (SagaStatus.AWAITING_HUMAN.value, next_version, iso(now), saga_id),
                )
            else:
                conn.execute(
                    """UPDATE saga_steps_v5 SET status=?,output_json=?,error_code=?,completed_at=?
                       WHERE saga_id=? AND step_index=?""",
                    (
                        SagaStepStatus.FAILED.value,
                        canonical_json(payload.output),
                        payload.error_code or "unspecified_failure",
                        iso(now),
                        saga_id,
                        saga.current_step_index,
                    ),
                )
                conn.execute(
                    "UPDATE sagas_v5 SET status=?,version=?,updated_at=? WHERE id=?",
                    (SagaStatus.COMPENSATING.value, next_version, iso(now), saga_id),
                )
                completed = conn.execute(
                    """SELECT * FROM saga_steps_v5 WHERE saga_id=? AND step_index<? AND status=?
                       ORDER BY step_index DESC""",
                    (saga_id, saga.current_step_index, SagaStepStatus.COMPLETED.value),
                ).fetchall()
                compensation_log: list[dict[str, Any]] = []
                for prior in completed:
                    if prior["reversible"]:
                        conn.execute(
                            "UPDATE saga_steps_v5 SET status=?,completed_at=? WHERE id=?",
                            (SagaStepStatus.COMPENSATED.value, iso(now), prior["id"]),
                        )
                        compensation_log.append(
                            {"step": prior["name"], "compensation": prior["compensation_name"], "at": iso(now)}
                        )
                context = json.loads(current["context_json"])
                context["compensation_log"] = compensation_log
                conn.execute(
                    """UPDATE sagas_v5 SET status=?,context_json=?,version=?,updated_at=? WHERE id=?""",
                    (SagaStatus.COMPENSATED.value, canonical_json(context), next_version, iso(now), saga_id),
                )
            conn.execute(
                """INSERT INTO saga_advances_v5(saga_id,idempotency_key,request_fingerprint,version_after,created_at)
                   VALUES (?,?,?,?,?)""",
                (saga_id, payload.idempotency_key, fingerprint, next_version, iso(now)),
            )
        updated = self.get_saga(family_id, saga_id)
        assert updated
        return updated

    # ----- offline-first sync -----
    def apply_sync(self, family_id: str, actor: AuthContext, payload: SyncOperationRequest) -> SyncOperationResult:
        if not self.db.actor_in_family(actor.actor_id, family_id):
            raise PermissionError("设备操作人不属于当前家庭。")
        device = self.conn.execute(
            "SELECT * FROM devices_v4 WHERE device_id=? AND family_id=? AND actor_id=?",
            (payload.device_id, family_id, actor.actor_id),
        ).fetchone()
        if not device:
            return SyncOperationResult(
                outcome=SyncOutcome.REJECTED,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                field_name=payload.field_name,
                version=0,
                value=None,
                conflict_id=None,
                message="设备未登记或不属于当前操作人。",
            )
        duplicate = self.conn.execute(
            "SELECT * FROM sync_operations_v5 WHERE operation_id=?", (payload.operation_id,)
        ).fetchone()
        if duplicate:
            current = self.conn.execute(
                """SELECT * FROM sync_entities_v5 WHERE family_id=? AND entity_type=? AND entity_id=? AND field_name=?""",
                (family_id, payload.entity_type, payload.entity_id, payload.field_name),
            ).fetchone()
            return SyncOperationResult(
                outcome=SyncOutcome.DUPLICATE,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                field_name=payload.field_name,
                version=duplicate["resulting_version"],
                value=json.loads(current["value_json"]) if current else None,
                conflict_id=None,
                message="重复离线操作已按operation_id幂等处理。",
            )
        current = self.conn.execute(
            """SELECT * FROM sync_entities_v5 WHERE family_id=? AND entity_type=? AND entity_id=? AND field_name=?""",
            (family_id, payload.entity_type, payload.entity_id, payload.field_name),
        ).fetchone()
        incoming_json = canonical_json(payload.value)
        payload_digest = hashlib.sha256(canonical_json(payload.model_dump(mode="json")).encode("utf-8")).hexdigest()
        now = utcnow()
        with self.db.transaction() as conn:
            if current is None:
                version = 1
                conn.execute(
                    """INSERT INTO sync_entities_v5(
                        family_id,entity_type,entity_id,field_name,value_json,version,lamport_clock,device_id,sensitivity,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        family_id,
                        payload.entity_type,
                        payload.entity_id,
                        payload.field_name,
                        incoming_json,
                        version,
                        payload.lamport_clock,
                        payload.device_id,
                        payload.sensitivity.value,
                        iso(now),
                    ),
                )
                outcome = SyncOutcome.APPLIED
                conflict_id = None
                message = "离线操作已创建并同步。"
                result_value = payload.value
            else:
                current_value = json.loads(current["value_json"])
                if current_value == payload.value:
                    version = current["version"]
                    outcome = SyncOutcome.DUPLICATE
                    conflict_id = None
                    message = "内容与云端一致，无需重复更新。"
                    result_value = current_value
                elif payload.base_version == current["version"] or (
                    SyncConflictPolicy.may_auto_merge(payload.sensitivity, payload.base_version, current["version"])
                    and payload.lamport_clock > current["lamport_clock"]
                ):
                    version = current["version"] + 1
                    conn.execute(
                        """UPDATE sync_entities_v5 SET value_json=?,version=?,lamport_clock=?,device_id=?,sensitivity=?,updated_at=?
                           WHERE family_id=? AND entity_type=? AND entity_id=? AND field_name=?""",
                        (
                            incoming_json,
                            version,
                            max(payload.lamport_clock, current["lamport_clock"] + 1),
                            payload.device_id,
                            payload.sensitivity.value,
                            iso(now),
                            family_id,
                            payload.entity_type,
                            payload.entity_id,
                            payload.field_name,
                        ),
                    )
                    outcome = SyncOutcome.APPLIED
                    conflict_id = None
                    message = "离线操作已按版本和Lamport时钟合并。"
                    result_value = payload.value
                else:
                    version = current["version"]
                    conflict_id = new_id("conflict")
                    conn.execute(
                        """INSERT INTO sync_conflicts_v5(
                            id,family_id,entity_type,entity_id,field_name,current_value_json,incoming_value_json,
                            current_version,incoming_base_version,sensitivity,status,created_at,resolved_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                        (
                            conflict_id,
                            family_id,
                            payload.entity_type,
                            payload.entity_id,
                            payload.field_name,
                            current["value_json"],
                            incoming_json,
                            current["version"],
                            payload.base_version,
                            payload.sensitivity.value,
                            "open",
                            iso(now),
                        ),
                    )
                    outcome = SyncOutcome.CONFLICT
                    message = "检测到跨设备冲突；高敏感数据不会自动覆盖，需要老人或家属明确选择。"
                    result_value = current_value
            conn.execute(
                """INSERT INTO sync_operations_v5(
                    operation_id,family_id,actor_id,device_id,entity_type,entity_id,field_name,base_version,
                    resulting_version,outcome,payload_digest,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload.operation_id,
                    family_id,
                    actor.actor_id,
                    payload.device_id,
                    payload.entity_type,
                    payload.entity_id,
                    payload.field_name,
                    payload.base_version,
                    version,
                    outcome.value,
                    payload_digest,
                    iso(now),
                ),
            )
        return SyncOperationResult(
            outcome=outcome,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            field_name=payload.field_name,
            version=version,
            value=result_value,
            conflict_id=conflict_id,
            message=message,
        )

    def list_sync_conflicts(self, family_id: str, status: str = "open") -> list[SyncConflictRecord]:
        rows = self.conn.execute(
            "SELECT * FROM sync_conflicts_v5 WHERE family_id=? AND status=? ORDER BY created_at DESC",
            (family_id, status),
        ).fetchall()
        return [self._row_conflict(row) for row in rows]

    @staticmethod
    def _row_conflict(row: sqlite3.Row) -> SyncConflictRecord:
        return SyncConflictRecord(
            id=row["id"],
            family_id=row["family_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            field_name=row["field_name"],
            current_value=json.loads(row["current_value_json"]),
            incoming_value=json.loads(row["incoming_value_json"]),
            current_version=row["current_version"],
            incoming_base_version=row["incoming_base_version"],
            sensitivity=SyncSensitivity(row["sensitivity"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        )

    def resolve_sync_conflict(
        self,
        family_id: str,
        actor: AuthContext,
        payload: SyncConflictResolutionRequest,
    ) -> SyncOperationResult:
        if actor.role not in {ActorRole.ELDER, ActorRole.FAMILY}:
            raise PermissionError("只有老人或绑定家属可以解决跨设备冲突。")
        row = self.conn.execute(
            "SELECT * FROM sync_conflicts_v5 WHERE id=? AND family_id=? AND status='open'",
            (payload.conflict_id, family_id),
        ).fetchone()
        if not row:
            raise ValueError("冲突不存在或已经处理。")
        value = json.loads(row["current_value_json"])
        new_version = row["current_version"]
        now = utcnow()
        with self.db.transaction() as conn:
            if payload.resolution == "accept_incoming":
                value = json.loads(row["incoming_value_json"])
                new_version += 1
                conn.execute(
                    """UPDATE sync_entities_v5 SET value_json=?,version=?,lamport_clock=lamport_clock+1,updated_at=?
                       WHERE family_id=? AND entity_type=? AND entity_id=? AND field_name=?""",
                    (
                        canonical_json(value),
                        new_version,
                        iso(now),
                        family_id,
                        row["entity_type"],
                        row["entity_id"],
                        row["field_name"],
                    ),
                )
            conn.execute(
                "UPDATE sync_conflicts_v5 SET status=?,resolved_at=? WHERE id=?",
                (payload.resolution, iso(now), payload.conflict_id),
            )
        return SyncOperationResult(
            outcome=SyncOutcome.APPLIED,
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            field_name=row["field_name"],
            version=new_version,
            value=value,
            conflict_id=payload.conflict_id,
            message="跨设备冲突已由明确的人类选择解决。",
        )

    # ----- emergency break-glass -----
    def create_break_glass(
        self,
        family_id: str,
        actor: AuthContext,
        payload: BreakGlassRequest,
    ) -> BreakGlassRecord:
        self.ensure_elder(family_id, payload.elder_id)
        if actor.role != ActorRole.FAMILY:
            raise PermissionError("紧急破窗访问只能由绑定家属发起。")
        allowed_scopes = {"location", "health_summary", "emergency_contacts", "active_tasks"}
        forbidden = {"companion_chat", "payment_credentials", "identity_secret", "full_medical_record"}
        requested = set(payload.scopes)
        if requested.intersection(forbidden):
            raise PermissionError("紧急访问也不能读取陪聊原文、支付凭据或身份秘密。")
        if not requested.issubset(allowed_scopes):
            raise ValueError("请求包含未注册的紧急访问范围。")
        active = self.conn.execute(
            """SELECT id FROM break_glass_v5 WHERE family_id=? AND elder_id=? AND requested_by=? AND status='active'
               AND expires_at>?""",
            (family_id, payload.elder_id, actor.actor_id, iso(utcnow())),
        ).fetchone()
        if active:
            existing = self.get_break_glass(family_id, active["id"])
            assert existing
            return existing
        created_at = utcnow()
        expires_at = created_at + timedelta(minutes=payload.duration_minutes)
        record = BreakGlassRecord(
            id=new_id("breakglass"),
            family_id=family_id,
            elder_id=payload.elder_id,
            requested_by=actor.actor_id,
            reason=payload.reason,
            scopes=sorted(requested),
            status="active",
            created_at=created_at,
            expires_at=expires_at,
            closed_at=None,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO break_glass_v5(
                    id,family_id,elder_id,requested_by,reason,scopes_json,status,created_at,expires_at,closed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    record.id,
                    family_id,
                    payload.elder_id,
                    actor.actor_id,
                    payload.reason,
                    canonical_json(record.scopes),
                    record.status,
                    iso(created_at),
                    iso(expires_at),
                ),
            )
        self.db.add_notification(
            family_id,
            ActorRole.ELDER,
            "BREAK_GLASS_OPENED",
            f"家属因紧急情况临时查看：{'、'.join(record.scopes)}。访问将在{payload.duration_minutes}分钟后自动失效。",
            record.id,
        )
        self.db.add_notification(
            family_id,
            ActorRole.FAMILY,
            "BREAK_GLASS_OPENED",
            "紧急访问已经开启并完整留痕；仅允许最小必要范围。",
            record.id,
        )
        return record

    def get_break_glass(self, family_id: str, record_id: str) -> BreakGlassRecord | None:
        row = self.conn.execute(
            "SELECT * FROM break_glass_v5 WHERE id=? AND family_id=?", (record_id, family_id)
        ).fetchone()
        return self._row_break_glass(row) if row else None

    def list_break_glass(self, family_id: str, elder_id: str) -> list[BreakGlassRecord]:
        self.ensure_elder(family_id, elder_id)
        self.expire_break_glass()
        rows = self.conn.execute(
            "SELECT * FROM break_glass_v5 WHERE family_id=? AND elder_id=? ORDER BY created_at DESC",
            (family_id, elder_id),
        ).fetchall()
        return [self._row_break_glass(row) for row in rows]

    @staticmethod
    def _row_break_glass(row: sqlite3.Row) -> BreakGlassRecord:
        return BreakGlassRecord(
            id=row["id"],
            family_id=row["family_id"],
            elder_id=row["elder_id"],
            requested_by=row["requested_by"],
            reason=row["reason"],
            scopes=json.loads(row["scopes_json"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
        )

    def close_break_glass(self, family_id: str, actor: AuthContext, record_id: str) -> BreakGlassRecord:
        row = self.conn.execute(
            "SELECT * FROM break_glass_v5 WHERE id=? AND family_id=?", (record_id, family_id)
        ).fetchone()
        if not row:
            raise ValueError("紧急访问记录不存在。")
        if actor.actor_id != row["requested_by"] and actor.role != ActorRole.ELDER:
            raise PermissionError("只有发起家属或老人本人可以提前关闭紧急访问。")
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE break_glass_v5 SET status='closed',closed_at=? WHERE id=? AND status='active'",
                (iso(now), record_id),
            )
        updated = self.get_break_glass(family_id, record_id)
        assert updated
        return updated

    def expire_break_glass(self) -> int:
        now = utcnow()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE break_glass_v5 SET status='expired',closed_at=? WHERE status='active' AND expires_at<=?",
                (iso(now), iso(now)),
            )
        return int(cursor.rowcount)

    # ----- proof / explanation helpers -----
    def approval_rows(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT actor_id,decision,approval_digest,created_at FROM approval_votes WHERE task_id=? ORDER BY created_at",
            (task_id,),
        ).fetchall()]

    def store_proof(self, bundle: TaskProofBundle) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO proof_bundles_v5(id,family_id,task_id,proof_digest,bundle_json,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    bundle.id,
                    bundle.family_id,
                    bundle.task_id,
                    bundle.proof_digest,
                    canonical_json(bundle.model_dump(mode="json")),
                    iso(bundle.generated_at),
                ),
            )

    # ----- privacy -----
    _PRIVACY_TABLES: dict[PrivacyCategory, tuple[str, str]] = {
        PrivacyCategory.EMOTION_EVENTS: ("emotion_events", "elder_id"),
        PrivacyCategory.LOCATION_HISTORY: ("location_events_v4", "elder_id"),
        PrivacyCategory.ITEM_MEMORIES: ("item_memories_v4", "elder_id"),
        PrivacyCategory.CONTACT_PROFILES: ("contact_profiles_v4", "elder_id"),
        PrivacyCategory.MEDICAL_DOCUMENTS: ("medical_documents_v4", "elder_id"),
        PrivacyCategory.HEALTH_EVENTS: ("health_events_v4", "elder_id"),
        PrivacyCategory.DEVICE_HISTORY: ("devices_v4", "actor_id"),
    }

    def privacy_export(
        self,
        family_id: str,
        elder_id: str,
        categories: list[PrivacyCategory],
    ) -> PrivacyExportBundle:
        self.ensure_elder(family_id, elder_id)
        records: dict[str, list[dict[str, Any]]] = {}
        for category in categories:
            table, elder_column = self._PRIVACY_TABLES[category]
            rows = self.conn.execute(
                f"SELECT * FROM {table} WHERE family_id=? AND {elder_column}=? ORDER BY rowid",
                (family_id, elder_id),
            ).fetchall()
            records[category.value] = [PrivacyRedactor.redact_value(dict(row)) for row in rows]
        generated_at = utcnow()
        digest = hashlib.sha256(
            canonical_json({"elder_id": elder_id, "categories": [item.value for item in categories], "records": records}).encode(
                "utf-8"
            )
        ).hexdigest()
        return PrivacyExportBundle(
            elder_id=elder_id,
            generated_at=generated_at,
            categories=categories,
            records=records,
            manifest_digest=digest,
            note="导出已隐藏常见手机号、身份证号、账号和秘密字段；审计链与法定留痕不包含在可删除数据中。",
        )

    def privacy_erase(
        self,
        family_id: str,
        actor: AuthContext,
        elder_id: str,
        categories: list[PrivacyCategory],
        execute: bool,
    ) -> PrivacyEraseResult:
        self.ensure_elder(family_id, elder_id)
        if actor.role != ActorRole.ELDER or actor.actor_id != elder_id:
            raise PermissionError("只有老人本人可以执行个人数据删除。")
        affected: dict[str, int] = {}
        if execute:
            with self.db.transaction() as conn:
                for category in categories:
                    table, elder_column = self._PRIVACY_TABLES[category]
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE family_id=? AND {elder_column}=?", (family_id, elder_id)
                    )
                    affected[category.value] = int(cursor.rowcount)
                conn.execute(
                    """INSERT INTO privacy_actions_v5(
                        id,family_id,elder_id,actor_id,action,categories_json,affected_json,created_at
                    ) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        new_id("privacy"),
                        family_id,
                        elder_id,
                        actor.actor_id,
                        "erase",
                        canonical_json([item.value for item in categories]),
                        canonical_json(affected),
                        iso(utcnow()),
                    ),
                )
        else:
            for category in categories:
                table, elder_column = self._PRIVACY_TABLES[category]
                affected[category.value] = int(
                    self.conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE family_id=? AND {elder_column}=?",
                        (family_id, elder_id),
                    ).fetchone()[0]
                )
        return PrivacyEraseResult(
            executed=execute,
            elder_id=elder_id,
            categories=categories,
            affected_rows=affected,
            preserved_records=["安全审计链", "审批证据摘要", "已经发生的支付/挂号外部回执"],
            message=("指定类别已删除。" if execute else "这是删除预览，尚未修改任何数据。"),
        )

    # ----- traces / metrics -----
    def add_trace(self, family_id: str, actor_id: str, payload: TraceSpanCreate) -> None:
        duration = (payload.ended_at - payload.started_at).total_seconds()
        if duration < 0 or duration > 86400:
            raise ValueError("trace时间范围无效。")
        attributes = PrivacyRedactor.redact_value(payload.attributes)
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trace_spans_v5(
                    trace_id,span_id,family_id,actor_id,parent_span_id,name,started_at,ended_at,status,attributes_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload.trace_id,
                    payload.span_id,
                    family_id,
                    actor_id,
                    payload.parent_span_id,
                    payload.name,
                    iso(payload.started_at),
                    iso(payload.ended_at),
                    payload.status,
                    canonical_json(attributes),
                ),
            )

    def metrics(self, family_id: str) -> MetricsSnapshot:
        def count(query: str, params: tuple[Any, ...] = ()) -> int:
            return int(self.conn.execute(query, params).fetchone()[0])

        counters = {
            "voice_total": count("SELECT COUNT(*) FROM voice_turns_v5 WHERE family_id=?", (family_id,)),
            "voice_clarify": count(
                "SELECT COUNT(*) FROM voice_turns_v5 WHERE family_id=? AND status='clarify'", (family_id,)
            ),
            "policy_total": count("SELECT COUNT(*) FROM policy_decisions_v5 WHERE family_id=?", (family_id,)),
            "policy_deny": count(
                "SELECT COUNT(*) FROM policy_decisions_v5 WHERE family_id=? AND decision='deny'", (family_id,)
            ),
            "saga_total": count("SELECT COUNT(*) FROM sagas_v5 WHERE family_id=?", (family_id,)),
            "saga_completed": count(
                "SELECT COUNT(*) FROM sagas_v5 WHERE family_id=? AND status='completed'", (family_id,)
            ),
            "saga_compensated": count(
                "SELECT COUNT(*) FROM sagas_v5 WHERE family_id=? AND status='compensated'", (family_id,)
            ),
            "sync_total": count("SELECT COUNT(*) FROM sync_operations_v5 WHERE family_id=?", (family_id,)),
            "sync_conflict": count(
                "SELECT COUNT(*) FROM sync_operations_v5 WHERE family_id=? AND outcome='conflict'", (family_id,)
            ),
            "open_break_glass": count(
                "SELECT COUNT(*) FROM break_glass_v5 WHERE family_id=? AND status='active' AND expires_at>?",
                (family_id, iso(utcnow())),
            ),
            "trace_errors": count(
                "SELECT COUNT(*) FROM trace_spans_v5 WHERE family_id=? AND status='error'", (family_id,)
            ),
        }
        return MetricsSnapshot(
            generated_at=utcnow(),
            counters=counters,
            rates=MetricsCalculator.rates(counters),
            audit_chain_valid=self.db.verify_audit_chain(family_id),
            privacy_note="指标仅含聚合计数，不含陪聊原文、验证码、密码、身份号码或精确位置。",
        )
