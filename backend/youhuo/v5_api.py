from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status

from . import __version__
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
from .v4_store import V4FeatureStore
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

    @router.post("/voice/resolve", response_model=VoiceTurnResolution,
                 operation_id="resolveVoice")
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

    @router.post("/actions/authorize", response_model=ActionAuthorization,
                 operation_id="authorizeAction")
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

    @router.post("/sagas", response_model=SagaRecord,
                 operation_id="createSaga")
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

    @router.post("/sync/operations", response_model=SyncOperationResult,
                 operation_id="applySyncOperation")
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

    @router.post("/break-glass", response_model=BreakGlassRecord,
                 operation_id="openBreakGlass")
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
            {"status": record.status, "elder_id": record.elder_id},
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
            # 那一列存的可能是 `V4FeatureStore.ACCURACY_UNKNOWN`（-1，因为
            # 列是 NOT NULL，没法存 NULL）。**这个数不许出现在家属眼前**：
            # 一位家属在紧急查看里读到「精度 -1 米」是一句没有意义的话，
            # 读到 0 更糟——那是「精确到米」的意思，而实际上根本没这个数。
            # 翻回 `null`，让「没有这个数」就显示成没有。
            location = dict(row) if row else {"status": "no_recent_location"}
            if location.get("accuracy_m") == V4FeatureStore.ACCURACY_UNKNOWN:
                location["accuracy_m"] = None
            result["scopes"]["location"] = location
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
            # `elder_id` 要写进来：老人端二的记录页靠「载荷里点名了她」
            # 才敢把别人做的这条留给她看（见 `privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
            # 少了它，那一屏只会显示「开了权限」，不会显示「资料真的被读了」。
            {"elder_id": record.elder_id, "scopes": record.scopes},
        )
        return result

    @router.get("/tasks/{task_id}/explain", response_model=ExplanationCard)
    def explain_task(task_id: str, actor: AuthContext = Depends(current_actor)) -> ExplanationCard:
        task = db.get_task(task_id)
        if not task or task.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="任务不存在。")
        require_elder_access(actor, task.elder_id)
        # 「办成的凭据」读的是 `task.result` 里**真的被写进去过**的那几个键。
        #
        # 原先这里是一份五个名字的清单，其中 `payment_receipt` / `receipt_id` /
        # `verification_digest` 全仓库只出现在这一行，从没有人写过它们；剩下两个
        # （`appointment_id` / `reminder_id`）恰好是真键，于是挂号和提醒是好的，
        # 而缴费——真实形状是 `{"bill_id": …, "verification": {…}}`——走完整条
        # 「老人复述 → 家人点头 → 状态核验」之后，评委页仍然说它没有凭据。
        #
        # 名单和状态门都挪进了 `ExplanationService.completion_evidence`：那里能
        # 和写入方（`services.py` / `engine.py`）的形状对着写注释，也能单独测。
        card = ExplanationService.build(
            task,
            store.approval_rows(task_id),
            ExplanationService.completion_evidence(task),
        )
        db.append_audit(actor.family_id, actor.actor_id, "TASK_EXPLANATION_VIEWED", task_id, {"status": task.status.value})
        return card

    @router.post("/tasks/{task_id}/proof", response_model=TaskProofBundle,
                 operation_id="createTaskProof")
    def create_task_proof(task_id: str, actor: AuthContext = Depends(current_actor)) -> TaskProofBundle:
        task = db.get_task(task_id)
        if not task or task.family_id != actor.family_id:
            raise HTTPException(status_code=404, detail="任务不存在。")
        require_elder_access(actor, task.elder_id)
        #: **在 SQL 里按 `entity_id` 筛**，limit 才作用在「这一件事」上。
        #:
        #: 原先取整条家庭流水的最新 2000 条再在 Python 里认 `entity_id`。
        #: 一个家庭用久了，第 2000 条之前的那些步就再也进不了这份凭据——
        #: 而端点照样 200，`merkle_root` 照样算得出来，校验端点照样说它是好的。
        #: 一份**少了前几步**的凭证，和一份完整的从外面看长得一模一样，
        #: 而凭证的全部价值就是「每一步都在」。
        #:
        #: `list_audit` 的 docstring 把这个坑写了两遍（凭证链 200 条、
        #: 她那一屏 300 条）。这是第三处。
        events = db.list_audit(actor.family_id, limit=2000, entity_id=task_id)
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
        """校验一份凭据，**并且和服务器留存的那一份对一遍**。

        原先这里只传 `payload.bundle`，于是校验的每一项都是那份包自己跟自己对
        （见 `MerkleProofService.verify` 的 docstring）。`store_proof` 一直在写
        `proof_bundles_v5`，而没有任何地方读它——真正那一份就躺在库里，
        校验却从不看它。

        这条端点**故意不要令牌**（凭据要能被第三方核验，那是它的意义）。
        按 id 查留存记录只泄露「这个 id 存不存在、对不对得上」，不返回内容；
        id 是 `new_id("proof")` 生成的，枚举不出来。
        """
        return MerkleProofService.verify(
            payload.bundle,
            recorded=store.recorded_proof_json(payload.bundle.id),
            # 端点必须严：这台服务知道自己有没有出过这份凭据。
            # 查不到就判否，而不是回「自洽」——界面上的绿勾看的是 `valid`。
            require_record=True,
        )

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
        """记一条 span。**这一版刻意只写不读，下面是理由。**

        现状（实测）：`app.routes` 里路径含 `trace` 或 `span` 的路由只有这一条
        `POST /v5/traces`；写进 `trace_spans_v5` 的行，全仓唯一的读取是
        `V5FeatureStore.metrics()` 里一句 `COUNT(*) … WHERE status='error'`，
        也就是 `GET /v5/metrics` 的 `trace_errors`。发两条 span（一条 ok、一条
        error）之后 `trace_errors` 是 1——两行里只有这一个整数出得来，span 树、
        父子关系、脱敏后的 `attributes` 没有任何读回路径。

        ## 为什么不补一条读它的端点

        补 `GET /v5/traces/{trace_id}` 需要一个真实消费方，否则只是把「收下一个
        没人看的 blob」换成「后端有、前端没画」——同一个毛病换个位置。而这个项目
        **已经决定过**这件事：`ONBOARDING.md` 把 `/v5/…traces` 列在「明确不该上
        老人端的」里面。span 树是给工程排障用的，不是给老人或子女看的界面，
        老人端多一屏 span 列表对她没有任何意义。所以这一版保持只写。

        ## 那「没人读」这件事怎么算说清了

        两点，都是行为不是措辞：

        一，`/v5/capability-truth` 把「隐私脱敏运行指标与Trace」列进
        `implemented_and_tested`。脱敏确实做了（`add_trace` 里
        `PrivacyRedactor.redact_value`），但**从外面验证不了**，所以那条声明只能
        靠读代码相信。`tests/test_nothing_is_accepted_and_dropped.py` 直接查库
        断言写进去的是脱敏后的值，把这条声明变成可复核的。

        二，只写的表没有下游读者，意味着**写入时没被挡住的坏数据此后永远不会被
        发现**。`V5FeatureStore.add_trace` 的 docstring 记着两个实测到的例子
        （span 编号撞车会静默删掉别人那一行；结构上不可能的父链一律 204），
        那两道检查现在是这张表唯一的读者。
        """
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
        """这一版真正做到了什么、哪些只是适配层。

        `version` 原先硬编码 `"5.0.0"`，而 `/v6/competition/evidence` 的
        `project_version` 是 `"6.0.0"`——**同一个产品两个版本号，而且两页都在评委
        面前**。权威来源是 `pyproject.toml` 的 `version = "6.0.0"`
        （`scripts/check_artifacts_v6.py` 就是按它检查的，`/health`、`/ping` 和
        FastAPI 的 `info.version` 也都是 6.0.0），所以 5.0.0 是错的那一个。

        这里读 `youhuo.__version__`，不再写第四个字面量：那个常量已经存在
        （`youhuo/__init__.py`，值就是 6.0.0），此前**一个消费者都没有**。
        用它等于少一处会各自漂移的字面量，不是新造一个来源。
        `pyproject.toml` 与它一致这件事由
        `tests/test_nothing_is_accepted_and_dropped.py` 钉住。
        """
        del actor
        return {
            "version": __version__,
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
