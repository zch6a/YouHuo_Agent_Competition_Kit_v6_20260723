from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .database import Database, utcnow
from .models import ActorRole, AuthContext
from .privacy import task_view
from .utils import new_id
from .v5_models import (
    ActionAuthorization,
    ActionAuthorizeRequest,
    BreakGlassRecord,
    BreakGlassRequest,
    ExplanationCard,
    MetricsSnapshot,
    PrivacyEraseRequest,
    PrivacyEraseResult,
    PrivacyExportBundle,
    PrivacyExportRequest,
    ProofVerifyRequest,
    ProofVerifyResult,
    SagaAdvanceRequest,
    SagaCreateRequest,
    SagaRecord,
    SyncConflictRecord,
    SyncConflictResolutionRequest,
    SyncOperationRequest,
    SyncOperationResult,
    TaskProofBundle,
    TraceSpanCreate,
    VoiceTurnRequest,
    VoiceTurnResolution,
)
from .v5_services import ExplanationService, MerkleProofService, PurposeBoundPolicy, VoiceConsensusEngine
from .v5_store import V5FeatureStore


def build_v5_router(
    db: Database,
    store: V5FeatureStore,
    current_actor: Callable[..., AuthContext],
) -> APIRouter:
    router = APIRouter(prefix="/v5", tags=["v5 trustworthy elder agent"])

    def require_elder_access(actor: AuthContext, elder_id: str) -> None:
        if actor.role == ActorRole.ELDER and actor.actor_id != elder_id:
            raise HTTPException(status_code=403, detail="只能访问自己的数据。")
        if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
            raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")

    def map_error(exc: Exception) -> HTTPException:
        if isinstance(exc, PermissionError):
            return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        if "版本冲突" in str(exc) or "幂等键" in str(exc) or "已经处理" in str(exc):
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @router.post("/voice/resolve", response_model=VoiceTurnResolution)
    def resolve_voice(
        payload: VoiceTurnRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> VoiceTurnResolution:
        require_elder_access(actor, payload.elder_id)
        result = VoiceConsensusEngine.resolve(payload)
        turn_id = store.record_voice_turn(actor.family_id, actor.actor_id, payload, result)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "VOICE_CONSENSUS_RESOLVED",
            turn_id,
            {
                "elder_id": payload.elder_id,
                "status": result.status.value,
                "intent": result.semantic_intent,
                "confidence": result.confidence,
                "ambiguity": result.ambiguity,
                "safety_flags": result.safety_flags,
                "consensus_digest": result.consensus_digest,
            },
        )
        return result

    @router.post("/actions/authorize", response_model=ActionAuthorization)
    def authorize_action(
        payload: ActionAuthorizeRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> ActionAuthorization:
        require_elder_access(actor, payload.elder_id)
        result = PurposeBoundPolicy.authorize(payload)
        decision_id = store.record_policy_decision(actor.family_id, actor.actor_id, payload, result)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "PURPOSE_BOUND_POLICY_DECISION",
            decision_id,
            {
                "elder_id": payload.elder_id,
                "action": payload.action,
                "decision": result.decision.value,
                "decision_digest": result.decision_digest,
                "stripped_fields": result.stripped_fields,
            },
        )
        return result

    @router.post("/sagas", response_model=SagaRecord)
    def create_saga(
        payload: SagaCreateRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SagaRecord:
        require_elder_access(actor, payload.elder_id)
        try:
            saga = store.create_saga(actor.family_id, actor.actor_id, payload)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "SAGA_CREATED",
            saga.id,
            {"kind": saga.kind.value, "elder_id": saga.elder_id, "version": saga.version},
        )
        return saga

    @router.get("/sagas", response_model=list[SagaRecord])
    def list_sagas(
        elder_id: str | None = Query(default=None, max_length=128),
        actor: AuthContext = Depends(current_actor),
    ) -> list[SagaRecord]:
        if elder_id:
            require_elder_access(actor, elder_id)
        elif actor.role == ActorRole.ELDER:
            elder_id = actor.actor_id
        return store.list_sagas(actor.family_id, elder_id)

    @router.get("/sagas/{saga_id}", response_model=SagaRecord)
    def get_saga(saga_id: str, actor: AuthContext = Depends(current_actor)) -> SagaRecord:
        saga = store.get_saga(actor.family_id, saga_id)
        if not saga:
            raise HTTPException(status_code=404, detail="Saga不存在。")
        require_elder_access(actor, saga.elder_id)
        return saga

    @router.post("/sagas/{saga_id}/advance", response_model=SagaRecord)
    def advance_saga(
        saga_id: str,
        payload: SagaAdvanceRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SagaRecord:
        try:
            before = store.get_saga(actor.family_id, saga_id)
            if not before:
                raise ValueError("Saga不存在。")
            require_elder_access(actor, before.elder_id)
            updated = store.advance_saga(actor.family_id, actor, saga_id, payload)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "SAGA_ADVANCED",
            saga_id,
            {
                "outcome": payload.outcome.value,
                "from_version": payload.expected_version,
                "to_version": updated.version,
                "status": updated.status.value,
                "current_step_index": updated.current_step_index,
            },
        )
        return updated

    @router.post("/sync/operations", response_model=SyncOperationResult)
    def apply_sync(
        payload: SyncOperationRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SyncOperationResult:
        try:
            result = store.apply_sync(actor.family_id, actor, payload)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "OFFLINE_SYNC_OPERATION",
            payload.operation_id,
            {
                "device_id": payload.device_id,
                "entity_type": payload.entity_type,
                "entity_id": payload.entity_id,
                "field_name": payload.field_name,
                "outcome": result.outcome.value,
                "version": result.version,
                "conflict_id": result.conflict_id,
            },
        )
        return result

    @router.get("/sync/conflicts", response_model=list[SyncConflictRecord])
    def list_sync_conflicts(
        conflict_status: str = Query(default="open", pattern=r"^(open|keep_current|accept_incoming)$"),
        actor: AuthContext = Depends(current_actor),
    ) -> list[SyncConflictRecord]:
        return store.list_sync_conflicts(actor.family_id, conflict_status)

    @router.post("/sync/conflicts/resolve", response_model=SyncOperationResult)
    def resolve_sync_conflict(
        payload: SyncConflictResolutionRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> SyncOperationResult:
        try:
            result = store.resolve_sync_conflict(actor.family_id, actor, payload)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "OFFLINE_SYNC_CONFLICT_RESOLVED",
            payload.conflict_id,
            {"resolution": payload.resolution, "version": result.version},
        )
        return result

    @router.post("/break-glass", response_model=BreakGlassRecord)
    def open_break_glass(
        payload: BreakGlassRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> BreakGlassRecord:
        try:
            record = store.create_break_glass(actor.family_id, actor, payload)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "BREAK_GLASS_OPENED",
            record.id,
            {
                "elder_id": record.elder_id,
                "scopes": record.scopes,
                "reason_digest": __import__("hashlib").sha256(record.reason.encode("utf-8")).hexdigest(),
                "expires_at": record.expires_at.isoformat(),
            },
        )
        return record

    @router.get("/break-glass/{elder_id}", response_model=list[BreakGlassRecord])
    def list_break_glass(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[BreakGlassRecord]:
        require_elder_access(actor, elder_id)
        return store.list_break_glass(actor.family_id, elder_id)

    @router.post("/break-glass/{record_id}/close", response_model=BreakGlassRecord)
    def close_break_glass(record_id: str, actor: AuthContext = Depends(current_actor)) -> BreakGlassRecord:
        try:
            record = store.close_break_glass(actor.family_id, actor, record_id)
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "BREAK_GLASS_CLOSED",
            record_id,
            {"status": record.status},
        )
        return record

    @router.get("/break-glass/{record_id}/view")
    def view_break_glass(record_id: str, actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        store.expire_break_glass()
        record = store.get_break_glass(actor.family_id, record_id)
        if not record or record.status != "active" or record.expires_at <= utcnow():
            raise HTTPException(status_code=403, detail="紧急访问不存在或已经失效。")
        if actor.actor_id != record.requested_by:
            raise HTTPException(status_code=403, detail="只有本次紧急访问的发起家属可以查看。")
        result: dict[str, Any] = {"record_id": record.id, "expires_at": record.expires_at, "scopes": {}}
        if "location" in record.scopes:
            row = db._conn.execute(
                """SELECT latitude,longitude,accuracy_m,occurred_at FROM location_events_v4
                   WHERE family_id=? AND elder_id=? ORDER BY occurred_at DESC LIMIT 1""",
                (actor.family_id, record.elder_id),
            ).fetchone()
            result["scopes"]["location"] = dict(row) if row else {"status": "no_recent_location"}
        if "health_summary" in record.scopes:
            rows = db._conn.execute(
                """SELECT kind,title,event_at,source FROM health_events_v4
                   WHERE family_id=? AND elder_id=? ORDER BY event_at DESC LIMIT 5""",
                (actor.family_id, record.elder_id),
            ).fetchall()
            result["scopes"]["health_summary"] = [dict(row) for row in rows]
        if "emergency_contacts" in record.scopes:
            rows = db._conn.execute(
                """SELECT name,contact_role,channel,address_masked,priority FROM safety_contacts_v4
                   WHERE family_id=? AND elder_id=? AND enabled=1 ORDER BY priority""",
                (actor.family_id, record.elder_id),
            ).fetchall()
            result["scopes"]["emergency_contacts"] = [dict(row) for row in rows]
        if "active_tasks" in record.scopes:
            result["scopes"]["active_tasks"] = [
                task_view(task).model_dump(mode="json")
                for task in db.list_tasks(actor.family_id, limit=50)
                if task.elder_id == record.elder_id and task.status.value not in {"completed", "cancelled", "failed"}
            ]
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "BREAK_GLASS_VIEWED",
            record.id,
            {"scopes": record.scopes},
        )
        return result

    @router.get("/tasks/{task_id}/explain", response_model=ExplanationCard)
    def explain_task(task_id: str, actor: AuthContext = Depends(current_actor)) -> ExplanationCard:
        task = db.get_task(task_id)
        if not task or task.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="任务不存在。")
        require_elder_access(actor, task.elder_id)
        evidence: list[str] = []
        for key in ("appointment_id", "payment_receipt", "receipt_id", "reminder_id", "verification_digest"):
            if task.result.get(key):
                evidence.append(f"{key}={task.result[key]}")
        card = ExplanationService.build(task, store.approval_rows(task_id), evidence)
        db.append_audit(actor.family_id, actor.actor_id, "TASK_EXPLANATION_VIEWED", task_id, {"status": task.status.value})
        return card

    @router.post("/tasks/{task_id}/proof", response_model=TaskProofBundle)
    def create_task_proof(task_id: str, actor: AuthContext = Depends(current_actor)) -> TaskProofBundle:
        task = db.get_task(task_id)
        if not task or task.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="任务不存在。")
        require_elder_access(actor, task.elder_id)
        events = [event for event in db.list_audit(actor.family_id, limit=2000) if event.entity_id == task_id]
        snapshot = task.model_dump(mode="json")
        bundle = MerkleProofService.build_bundle(
            bundle_id=new_id("proof"),
            task_id=task_id,
            family_id=actor.family_id,
            task_snapshot=snapshot,
            audit_events=events,
            audit_chain_valid=db.verify_audit_chain(actor.family_id),
            generated_at=utcnow(),
        )
        store.store_proof(bundle)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "TASK_PROOF_GENERATED",
            task_id,
            {"proof_digest": bundle.proof_digest, "merkle_root": bundle.merkle_root, "event_count": len(events)},
        )
        return bundle

    @router.post("/proofs/verify", response_model=ProofVerifyResult)
    def verify_proof(payload: ProofVerifyRequest) -> ProofVerifyResult:
        return MerkleProofService.verify(payload.bundle)

    @router.post("/privacy/export", response_model=PrivacyExportBundle)
    def export_privacy_data(
        payload: PrivacyExportRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> PrivacyExportBundle:
        if actor.role != ActorRole.ELDER or actor.actor_id != payload.elder_id:
            raise HTTPException(status_code=403, detail="完整个人数据导出只允许老人本人发起。")
        result = store.privacy_export(actor.family_id, payload.elder_id, payload.categories)
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "PRIVACY_EXPORT_CREATED",
            payload.elder_id,
            {"categories": [item.value for item in payload.categories], "manifest_digest": result.manifest_digest},
        )
        return result

    @router.post("/privacy/erase", response_model=PrivacyEraseResult)
    def erase_privacy_data(
        payload: PrivacyEraseRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> PrivacyEraseResult:
        try:
            result = store.privacy_erase(
                actor.family_id, actor, payload.elder_id, payload.categories, payload.execute
            )
        except Exception as exc:
            raise map_error(exc) from exc
        db.append_audit(
            actor.family_id,
            actor.actor_id,
            "PRIVACY_ERASE_EXECUTED" if payload.execute else "PRIVACY_ERASE_PREVIEWED",
            payload.elder_id,
            {"categories": [item.value for item in payload.categories], "affected": result.affected_rows},
        )
        return result

    @router.post("/traces", status_code=204)
    def add_trace(payload: TraceSpanCreate, actor: AuthContext = Depends(current_actor)) -> None:
        try:
            store.add_trace(actor.family_id, actor.actor_id, payload)
        except Exception as exc:
            raise map_error(exc) from exc

    @router.get("/metrics", response_model=MetricsSnapshot)
    def metrics(actor: AuthContext = Depends(current_actor)) -> MetricsSnapshot:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=403, detail="聚合运行指标仅向绑定家属展示。")
        return store.metrics(actor.family_id)

    @router.get("/capability-truth")
    def capability_truth(actor: AuthContext = Depends(current_actor)) -> dict[str, Any]:
        del actor
        return {
            "version": "5.0.0",
            "implemented_and_tested": [
                "N-best语音共识与高风险澄清",
                "目的绑定数据流与外部策略决策",
                "可恢复Saga、幂等推进和补偿",
                "离线多设备同步、版本冲突与人工解决",
                "限时破窗访问、最小范围与完整留痕",
                "解释卡与Merkle完成证明包",
                "老人个人数据导出和可删除类别预览/执行",
                "隐私脱敏运行指标与Trace",
            ],
            "adapters_not_claimed_as_production": [
                "真实医院、支付、账号、Push、地图和社区接口",
                "DevEco Studio真机编译与正式小艺审核",
                "临床药物相互作用数据库和医疗诊断",
                "生产级人脸识别与跨App远程接管",
                "50万或100万名真实老人测试",
            ],
        }

    return router
