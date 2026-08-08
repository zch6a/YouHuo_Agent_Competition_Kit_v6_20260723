from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.datastructures import MutableHeaders
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .database import Database, IdempotencyConflict
from .engine import AuthorizationError, EngineError, YouHuoEngine, semantic_model_configured
from .privacy import elder_activity_entries, task_view
from .document_guard import DocumentAnalysis, DocumentAnalysisRequest, DocumentGuard
from .memory_vault import ConsentMemoryVault, MemoryDecision, MemoryItem, MemoryProposal
from .orchestration import DelegationDecision, DelegationPolicy, TaskGraph, TaskPlanner
from .tool_registry import ToolDryRunResult, ToolManifest, build_default_registry
from .v3_models import DelegationPreviewRequest, ToolDryRunRequest
from .v4_api import build_v4_router
from .v4_services import MedicationKnowledgeBase
from .v4_store import V4FeatureStore
from .v5_api import build_v5_router
from .v5_store import V5FeatureStore
from .tts import NeuralVoice
from .v6_api import build_v6_router
from .v6_store import V6FeatureStore
from .models import (
    ActorRole,
    AuthContext,
    ChatRequest,
    ChatResponse,
    DemoLoginRequest,
    DemoLoginResponse,
    ElderActivityEntry,
    FamilyApprovalRequest,
    FamilyReminderCreateRequest,
    ReminderActionRequest,
    ReminderEvaluationRequest,
    SessionCreateRequest,
    SessionCreateResponse,
    TaskView,
    TaskType,
    VisitorSandboxResponse,
)


def create_app(db_path: str | Path | None = None, *, demo_mode: bool | None = None) -> FastAPI:
    resolved_db = Path(db_path or os.getenv("YOUHUO_DB_PATH", "data/youhuo.db"))
    resolved_db.parent.mkdir(parents=True, exist_ok=True)
    db = Database(resolved_db)
    db.seed_demo()
    engine = YouHuoEngine(db)
    memory_vault = ConsentMemoryVault(db)
    tool_registry = build_default_registry()
    v4_store = V4FeatureStore(db)
    v4_store.seed_demo()
    medication_kb = MedicationKnowledgeBase()
    v5_store = V5FeatureStore(db)
    v6_store = V6FeatureStore(db)
    # Optional offline neural voice; absent package or model simply means the
    # elder client keeps using the browser's own speech synthesis.
    neural_voice = NeuralVoice(Path(__file__).resolve().parents[2])
    resolved_demo_mode = (
        demo_mode
        if demo_mode is not None
        else os.getenv("YOUHUO_DEMO_MODE", "true").strip().casefold() in {"1", "true", "yes", "on"}
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        neural_voice.warm_up_async()
        yield
        db.close()

    app = FastAPI(
        title="优活 Agent API",
        version="6.0.0",
        description=(
            "面向独居老人的家庭协同式可信生活智能体。语言层只负责理解；"
            "办事、循环事务、情绪陪伴、记忆、健康、用药、位置安全与家庭协同由可审计代码控制；"
            "v5新增语音共识、目的绑定策略、可恢复Saga、离线同步、破窗访问与可验证证明；"
            "v6新增认知负荷治理、玻璃盒依赖校准、安全预演、受约束语义网关与真实用户实验工具链。"
        ),
        lifespan=lifespan,
    )
    app.state.db = db
    app.state.engine = engine
    app.state.demo_mode = resolved_demo_mode
    app.state.v4_store = v4_store
    app.state.v5_store = v5_store
    app.state.v6_store = v6_store

    # The competition prototype intentionally uses one SQLite connection so the
    # package remains offline and easy to reproduce. SQLite cursors on a shared
    # connection must not overlap across FastAPI worker threads, therefore all
    # API/database requests are serialized. Static UI assets remain concurrent.
    # Production deployments should replace this with a pooled server database.
    sqlite_request_lock = asyncio.Lock()

    # Both middlewares are plain ASGI rather than BaseHTTPMiddleware. The latter
    # wraps every request in an anyio task group with memory object streams,
    # which measured ~12ms of overhead per request here and got worse with
    # concurrency (76 rps at 1 connection down to 26 rps at 100). Pure ASGI
    # keeps identical behaviour without that cost.
    _LOCK_EXEMPT_PATHS = frozenset({"/", "/elder", "/family", "/care", "/trust", "/judge", "/ping"})

    class SQLiteSerializationMiddleware:
        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            path = scope["path"]
            # Static assets, UI pages and speech synthesis never touch the
            # database; speech in particular takes ~1.5s per clause and holding
            # the shared lock would stall every other request.
            if path.startswith("/static/") or path in _LOCK_EXEMPT_PATHS or path.startswith("/v6/speech/"):
                await self.app(scope, receive, send)
                return
            async with sqlite_request_lock:
                await self.app(scope, receive, send)

    _SECURITY_HEADERS = (
        (
            b"content-security-policy",
            b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            # blob: is required to play locally synthesized WAV audio; it is
            # created in-page from a same-origin response, never fetched.
            b"media-src 'self' blob:; "
            b"connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        ),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"microphone=(self), camera=(self), geolocation=(self)"),
        (b"cache-control", b"no-store"),
    )

    class SecurityHeadersMiddleware:
        def __init__(self, app) -> None:
            self.app = app

        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            async def send_with_headers(message) -> None:
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    for name, value in _SECURITY_HEADERS:
                        headers.setdefault(name.decode(), value.decode())
                await send(message)

            await self.app(scope, receive, send_with_headers)

    app.add_middleware(SQLiteSerializationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    bearer = HTTPBearer(auto_error=False)

    def current_actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AuthContext:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少Bearer访问令牌。")
        actor = db.resolve_auth_token(credentials.credentials)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌无效或已过期。")
        return actor

    def handle_engine_error(exc: Exception) -> HTTPException:
        if isinstance(exc, IdempotencyConflict):
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        if isinstance(exc, AuthorizationError):
            return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        if isinstance(exc, EngineError):
            return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        # Must be served from the origin root: a worker's scope cannot rise above
        # its own path, and /static/sw.js could only ever control /static/.
        return FileResponse(
            static_dir / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def web_manifest() -> FileResponse:
        return FileResponse(
            static_dir / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @app.get("/elder", include_in_schema=False)
    def elder_ui() -> FileResponse:
        return FileResponse(static_dir / "elder.html")

    @app.get("/family", include_in_schema=False)
    def family_ui() -> FileResponse:
        return FileResponse(static_dir / "family.html")

    @app.get("/care", include_in_schema=False)
    def care_ui() -> FileResponse:
        return FileResponse(static_dir / "care.html")

    @app.get("/trust", include_in_schema=False)
    def trust_ui() -> FileResponse:
        return FileResponse(static_dir / "trust.html")

    @app.get("/judge", include_in_schema=False)
    def judge_ui() -> FileResponse:
        return FileResponse(static_dir / "judge.html")

    @app.get("/ping", include_in_schema=False)
    async def ping() -> dict[str, str]:
        """Database-free liveness endpoint used by deployment and load checks."""
        return {"status": "ok", "version": "6.0.0"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        configured = semantic_model_configured()
        return {
            "status": "ok",
            "version": "6.0.0",
            "audit_chain_valid": db.verify_audit_chain("fam-demo"),
            # The service never *requires* a model: routing degrades to the
            # deterministic classifier. When one is configured it advises the
            # semantic layer only, and never authorization.
            "llm_required": False,
            "semantic_model_configured": configured,
            "semantic_mode": "model_advised" if configured else "deterministic_only",
            "model_can_authorize": False,
            "demo_mode": resolved_demo_mode,
        }

    @app.post("/v2/auth/demo", response_model=DemoLoginResponse)
    def demo_login(payload: DemoLoginRequest) -> DemoLoginResponse:
        if not resolved_demo_mode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="演示登录已关闭。")
        try:
            token, actor, expires_at = engine.demo_login(payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        return DemoLoginResponse(access_token=token, actor=actor, expires_at=expires_at)

    @app.post("/v2/auth/visitor", response_model=VisitorSandboxResponse)
    def visitor_sandbox() -> VisitorSandboxResponse:
        """Hand a first-time visitor their own isolated demo household.

        A public, login-free deployment otherwise puts every visitor into the same
        family, so two people looking at once see each other's reminders and can
        overwrite each other's tasks. Family isolation is already enforced on
        `family_id` everywhere, so a fresh family is a real sandbox rather than a
        cosmetic one. The browser keeps the ids and reuses them on reload.
        """
        if not resolved_demo_mode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="演示访客入口已关闭。")
        suffix = f"v{secrets.token_hex(6)}"
        ids = db.seed_demo(suffix)
        v4_store.seed_demo(suffix)
        elder_token, elder, expires_at = engine.demo_login(ids.elder_id)
        family_token, _, _ = engine.demo_login(ids.daughter_id)
        return VisitorSandboxResponse(
            elder_id=ids.elder_id,
            daughter_id=ids.daughter_id,
            son_id=ids.son_id,
            family_id=ids.family_id,
            elder_token=elder_token,
            family_token=family_token,
            expires_at=expires_at,
            actor=elder,
        )

    @app.post("/v2/sessions", response_model=SessionCreateResponse)
    def create_session_endpoint(
        payload: SessionCreateRequest, actor: AuthContext = Depends(current_actor)
    ) -> SessionCreateResponse:
        try:
            session = engine.create_session(actor, payload)
        except Exception as exc:
            raise handle_engine_error(exc) from exc
        return SessionCreateResponse(
            session_id=session.session_id,
            family_id=session.family_id,
            elder_id=session.elder_id,
            mode=session.mode,
        )

    @app.post("/v2/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, actor: AuthContext = Depends(current_actor)) -> ChatResponse:
        try:
            return engine.handle(actor, payload)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.post("/v2/family/approve", response_model=ChatResponse)
    def approve(
        payload: FamilyApprovalRequest, actor: AuthContext = Depends(current_actor)
    ) -> ChatResponse:
        try:
            return engine.approve(actor, payload)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.post("/v2/family/reminders", response_model=ChatResponse)
    def create_family_reminder(
        payload: FamilyReminderCreateRequest, actor: AuthContext = Depends(current_actor)
    ) -> ChatResponse:
        try:
            return engine.create_family_reminder(actor, payload)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.post("/v2/reminders/{reminder_id}/acknowledge", response_model=ChatResponse)
    def acknowledge_reminder(
        reminder_id: str,
        payload: ReminderActionRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> ChatResponse:
        try:
            return engine.reminder_action(actor, reminder_id, "acknowledge", payload.request_id)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.post("/v2/reminders/{reminder_id}/complete", response_model=ChatResponse)
    def complete_reminder(
        reminder_id: str,
        payload: ReminderActionRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> ChatResponse:
        try:
            return engine.reminder_action(actor, reminder_id, "complete", payload.request_id)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.post("/v2/demo/scheduler/evaluate")
    def scheduler_evaluate(
        payload: ReminderEvaluationRequest,
        actor: AuthContext = Depends(current_actor),
    ) -> dict[str, int]:
        if not resolved_demo_mode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="演示调度入口已关闭。")
        try:
            return engine.scheduler_tick(actor, payload.now)
        except Exception as exc:
            raise handle_engine_error(exc) from exc

    @app.get("/v2/tasks", response_model=list[TaskView])
    def list_tasks(
        actor: AuthContext = Depends(current_actor),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[TaskView]:
        tasks = db.list_tasks(actor.family_id, limit=limit)
        if actor.role == ActorRole.ELDER:
            tasks = [task for task in tasks if task.elder_id == actor.actor_id]
        return [task_view(task) for task in tasks]

    @app.get("/v2/reminders")
    def list_reminders(
        actor: AuthContext = Depends(current_actor),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        reminders = db.list_reminders(actor.family_id, limit=limit)
        if actor.role == ActorRole.ELDER:
            reminders = [item for item in reminders if item.elder_id == actor.actor_id]
        return [item.model_dump(mode="json") for item in reminders]

    @app.get("/v2/notifications")
    def list_notifications(
        actor: AuthContext = Depends(current_actor),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        role = ActorRole.FAMILY if actor.role == ActorRole.FAMILY else ActorRole.ELDER
        return [item.model_dump(mode="json") for item in db.list_notifications(actor.family_id, role, limit=limit)]

    @app.get("/v2/audit")
    def list_audit(
        actor: AuthContext = Depends(current_actor),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="完整办事审计仅向绑定家属开放。")
        return {
            "chain_valid": db.verify_audit_chain(actor.family_id),
            "events": [event.model_dump(mode="json") for event in db.list_audit(actor.family_id, limit=limit)],
        }

    @app.get("/v2/elder/activity", response_model=list[ElderActivityEntry])
    def elder_activity(
        actor: AuthContext = Depends(current_actor),
        elder_id: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=30, ge=1, le=200),
    ) -> list[ElderActivityEntry]:
        """Plain-language activity log for the elder home page (design §4.4).

        The elder sees what happened to their own tasks and reminders without the
        family-only audit internals, and companion chat text never appears here.
        """
        if actor.role == ActorRole.ELDER:
            target = actor.actor_id
            if elder_id is not None and elder_id != target:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能查看自己的记录。")
        elif actor.role == ActorRole.FAMILY:
            if elder_id is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定要查看的老人。")
            if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="老人账户不属于当前家庭。")
            target = elder_id
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权查看老人记录。")

        def entity_belongs_to_elder(entity_id: str | None) -> bool | None:
            if not entity_id:
                return None
            if entity_id.startswith("task"):
                task = db.get_task(entity_id)
                return None if task is None else task.elder_id == target
            if entity_id.startswith("rem"):
                reminder = db.get_reminder(entity_id)
                return None if reminder is None else reminder.elder_id == target
            return None

        # Read a wider window than `limit` because the allow-list drops most rows.
        events = db.list_audit(actor.family_id, limit=min(limit * 10, 2000))
        return elder_activity_entries(
            events, entity_belongs_to_elder=entity_belongs_to_elder, elder_id=target
        )[:limit]

    @app.get("/v3/plans/{task_type}", response_model=TaskGraph)
    def task_plan(task_type: TaskType, actor: AuthContext = Depends(current_actor)) -> TaskGraph:
        del actor
        return TaskPlanner.plan(task_type)

    @app.post("/v3/delegation/preview", response_model=DelegationDecision)
    def delegation_preview(
        payload: DelegationPreviewRequest, actor: AuthContext = Depends(current_actor)
    ) -> DelegationDecision:
        del actor
        return DelegationPolicy.decide(
            payload.task_type,
            payload.risk_level,
            amount_cents=payload.amount_cents,
            ambiguity=payload.ambiguity,
            tool_is_reversible=payload.tool_is_reversible,
        )

    @app.post("/v3/documents/analyze", response_model=DocumentAnalysis)
    def analyze_document(
        payload: DocumentAnalysisRequest, actor: AuthContext = Depends(current_actor)
    ) -> DocumentAnalysis:
        result = DocumentGuard.analyze(payload)
        db.append_audit(
            actor.family_id, actor.actor_id, "DOCUMENT_ANALYZED", None,
            {"kind": result.kind.value, "safe_for_autofill": result.safe_for_autofill, "source_digest": result.source_digest},
        )
        return result

    @app.get("/v3/tools", response_model=list[ToolManifest])
    def list_tool_manifests(actor: AuthContext = Depends(current_actor)) -> list[ToolManifest]:
        del actor
        return tool_registry.manifests()

    @app.post("/v3/tools/{tool_name}/dry-run", response_model=ToolDryRunResult)
    def tool_dry_run(
        tool_name: str, payload: ToolDryRunRequest, actor: AuthContext = Depends(current_actor)
    ) -> ToolDryRunResult:
        result = tool_registry.dry_run(tool_name, payload.arguments)
        db.append_audit(
            actor.family_id, actor.actor_id, "TOOL_DRY_RUN", tool_name,
            {"allowed": result.allowed, "warning_count": len(result.warnings)},
        )
        return result

    @app.post("/v3/memories/propose", response_model=MemoryItem)
    def propose_memory(
        payload: MemoryProposal, actor: AuthContext = Depends(current_actor)
    ) -> MemoryItem:
        if actor.role == ActorRole.ELDER:
            if payload.elder_id != actor.actor_id:
                raise HTTPException(status_code=403, detail="只能为自己提出记忆项。")
        elif actor.role == ActorRole.FAMILY:
            if not db.actor_in_family(payload.elder_id, actor.family_id, ActorRole.ELDER.value):
                raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")
        else:
            raise HTTPException(status_code=403, detail="当前角色无权提出记忆项。")
        item = memory_vault.propose(actor.family_id, payload)
        db.append_audit(
            actor.family_id, actor.actor_id, "MEMORY_PROPOSED", item.id,
            {"key": item.key, "sensitivity": item.sensitivity.value, "scope": item.scope.value},
        )
        return item

    @app.post("/v3/memories/decide", response_model=MemoryItem)
    def decide_memory(
        payload: MemoryDecision, actor: AuthContext = Depends(current_actor)
    ) -> MemoryItem:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以批准长期记忆。")
        try:
            item = memory_vault.decide(actor.family_id, actor.actor_id, payload)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.append_audit(
            actor.family_id, actor.actor_id, "MEMORY_APPROVED" if payload.approve else "MEMORY_REJECTED", item.id,
            {"key": item.key},
        )
        return item

    @app.delete("/v3/memories/{memory_id}", response_model=MemoryItem)
    def revoke_memory(memory_id: str, actor: AuthContext = Depends(current_actor)) -> MemoryItem:
        if actor.role != ActorRole.ELDER:
            raise HTTPException(status_code=403, detail="只有老人本人可以撤销长期记忆。")
        try:
            item = memory_vault.revoke(actor.family_id, actor.actor_id, memory_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        db.append_audit(actor.family_id, actor.actor_id, "MEMORY_REVOKED", item.id, {"key": item.key})
        return item

    @app.get("/v3/memories/{elder_id}", response_model=list[MemoryItem])
    def list_memories(elder_id: str, actor: AuthContext = Depends(current_actor)) -> list[MemoryItem]:
        if actor.role == ActorRole.ELDER and elder_id != actor.actor_id:
            raise HTTPException(status_code=403, detail="只能查看自己的记忆。")
        if actor.role == ActorRole.FAMILY and not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
            raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")
        return memory_vault.list_visible(actor.family_id, elder_id, viewer_role=actor.role.value)

    app.include_router(build_v4_router(db, v4_store, current_actor, medication_kb))
    app.include_router(build_v5_router(db, v5_store, current_actor))
    app.include_router(build_v6_router(db, v6_store, current_actor, neural_voice))

    return app


#: Built on first access rather than at import.
#:
#: `app = create_app()` at module scope meant that *importing* this module
#: created `data/youhuo.db`, seeded it with demo data and generated an HMAC
#: audit key — as a side effect, in whatever directory the process happened to
#: start in. Every test run, every tooling import and every editor that loaded
#: the module left a live database behind, which is how one ended up committed.
#:
#: PEP 562 keeps `uvicorn youhuo.api:app` working unchanged (uvicorn resolves the
#: attribute, which builds it), while `from youhuo.api import create_app` and
#: plain `import youhuo.api` now touch nothing on disk.
_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    global _app
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _app is None:
        _app = create_app()
    return _app
