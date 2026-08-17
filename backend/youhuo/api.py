from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from starlette.datastructures import MutableHeaders
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .database import Database, DemoIdentities, IdempotencyConflict
from .engine import AuthorizationError, EngineError, YouHuoEngine, semantic_model_configured
from .privacy import elder_activity_entries, task_view
from .document_guard import DocumentAnalysis, DocumentAnalysisRequest, DocumentGuard
from .memory_vault import ConsentMemoryVault, MemoryDecision, MemoryItem, MemoryProposal
from .orchestration import DelegationDecision, DelegationPolicy, TaskGraph, TaskPlanner
from .tool_registry import ToolDryRunResult, ToolManifest, build_default_registry
from .v3_models import DelegationPreviewRequest, ToolDryRunRequest
from .app_api import build_app_router
from .v4_api import build_v4_router
from .v4_services import MedicationKnowledgeBase
from .v4_store import V4FeatureStore
from .v5_api import build_v5_router
from .v5_store import V5FeatureStore
from .tts import NeuralVoice
from .v6_api import build_v6_router
from .v6_store import V6FeatureStore
from .baseline_api import build_baseline_router
from .baseline_store import BaselineStore
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


def create_app(
    db_path: str | Path | None = None,
    *,
    demo_mode: bool | None = None,
    seed_baseline_history: bool | None = None,
) -> FastAPI:
    """
    `seed_baseline_history` 铺一段合成的作息历史，好让个性化基线在演示里立刻有东西可看。

    **默认关闭，而且必须默认关闭。** 它写的是 `activity_events_v4`——一张运营表，
    无交互预警（`evaluate_inactivity`）会取其中的 `MAX(occurred_at)`。默认打开时，
    这些"今天"的合成事件让一条以 2026-07-23 为 now 的既有测试再也触发不了预警：
    最后一次活动落在了查询时点之后。合成回填悄悄改掉真实功能的输入，是比"演示里
    没东西看"糟糕得多的一件事。

    所以它是显式开关：部署演示和 `run_demo` 打开，测试默认不打开。
    """
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
    baseline_store = BaselineStore(db)
    seed_history = (
        seed_baseline_history
        if seed_baseline_history is not None
        else os.getenv("YOUHUO_SEED_BASELINE", "false").lower() == "true"
    )
    # 三个数据状态。空态掩盖布局问题，所以「补数据」不是锦上添花的收尾项。
    #
    #   empty      什么都不种。pytest 默认——一整批对话流程测试依赖
    #              「这个家庭一开始没有待办」（取消按名字找、裸「嗯」确认、访客隔离计数）。
    #   normal     3 条提醒 + 一笔**完整证据链**的已完成缴费 + 21 天作息基线。
    #   attention  normal 之上再有需要注意的偏离。
    #
    # `YOUHUO_SEED_BASELINE=true` 等价于 `normal`，保留兼容：`run_demo.ps1` 和四个
    # 闸门脚本都在用它。
    demo_state = os.getenv("YOUHUO_DEMO_STATE", "").lower()
    if not demo_state:
        demo_state = "normal" if seed_history else "empty"
    if demo_state not in {"empty", "normal", "attention"}:
        raise RuntimeError(
            f"YOUHUO_DEMO_STATE={demo_state!r} 不认识，只有 empty|normal|attention"
        )
    seed_history = demo_state in {"normal", "attention"}

    if seed_history:
        demo_ids = DemoIdentities.for_suffix("demo")
        baseline_store.seed_demo_for()
        # 没有待办，老人端首页第一屏永远是「今天没有要办的事。」
        # ——这个产品最重要的一屏在演示里是空的。
        db.seed_demo_reminders(demo_ids)
        # 一笔完整的已完成缴费。只写 `status='completed'` 的话，Trust Receipt 和
        # Audit 都会拿到一条残缺的链，而那两页的全部价值就是链本身。
        db.seed_demo_scenario(demo_ids, "completed_bill_payment")
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
        # Swagger UI 与 ReDoc 在这个应用里必然是白屏，所以不要提供它们。
        #
        # 这套响应头是 `default-src 'self'; script-src 'self'`，没有 unsafe-inline、
        # 没有 nonce，而中间件对**每一个**响应下发。FastAPI 默认的 docs 页有三处必然被
        # 拦：jsdelivr CDN 的 JS 与 CSS，加一段内联 `<script>`；自托管那两个静态文件
        # 也救不了内联那一段。评委页上原先有一个「接口文档」按钮指向 /docs——点开是
        # 一片空白加三条 CSP 违规。
        #
        # 关掉之后 /docs 是 404，而 404 是实话；白屏看起来像产品坏了。接口定义仍然
        # 完整可取：`/openapi.json` 是纯 JSON，不受 CSP 约束，离线也能打开，评委页的
        # 按钮现在指向它。
        docs_url=None,
        redoc_url=None,
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
            # `/api/v1/speech` 和 `/v6/speech/` 同样豁免：合成一句要 ~1.5 秒，
            # 而这把锁是全进程共享的——不豁免的话，老人点一次朗读，
            # 别人的每一个请求都要排在它后面。
            if (path.startswith("/static/") or path in _LOCK_EXEMPT_PATHS
                    or path.startswith("/v6/speech/") or path == "/api/v1/speech"):
                await self.app(scope, receive, send)
                return
            async with sqlite_request_lock:
                await self.app(scope, receive, send)

    _SECURITY_HEADERS = (
        (
            b"content-security-policy",
            # `style-src` 放开了 `'unsafe-inline'`。
            #
            # 这是一处**真的放宽，不掩饰**。新前端（`/app`）的十个页面把山水图层的
            # 定位全写在 `style="left:0;top:112px;..."` 里，几十处每屏；严格
            # `style-src 'self'` 会把它们全部丢弃，结果是山水堆到左上角、卡片塌掉。
            #
            # 放开的代价说清楚：内联样式可被用来做数据渗出（例如
            # `background:url(...)` 带走内容）和界面伪装。保住的是更要紧的那条——
            # `script-src 'self'` 一步没动，没有 `unsafe-inline`、没有 `unsafe-eval`、
            # 没有 CDN，脚本仍然只能来自本站。样式注入需要先有注入点，而注入点
            # 在 `script-src` 收紧的前提下本来就是通局条件。
            b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            b"img-src 'self' data:; "
            # blob: is required to play locally synthesized WAV audio; it is
            # created in-page from a same-origin response, never fetched.
            b"media-src 'self' blob:; "
            # 桌面演示舞台把真实 App 装进一个 390x844 的 iframe 里。
            #
            # 这是一处**真的放宽**，不掩饰：`frame-ancestors` 从 `'none'` 放到 `'self'`，
            # `X-Frame-Options` 从 `DENY` 放到 `SAMEORIGIN`。保住的安全属性是"第三方站点
            # 不能把我们的页面套进它的框里"——点击劫持的实际威胁面——放开的只有我们
            # 自己的 `/stage`。
            #
            # 残余风险说清楚：一个同源 XSS 现在可以把我们自己的页面套进框。但在
            # `script-src 'self'` 且无内联、无 CDN 的前提下，同源 XSS 本身就已经是
            # 通局条件，套不套框不改变结局。
            #
            # 为什么必须是真 iframe 而不是 `transform: scale()`：App 得在 390px 视口里
            # **真的**跑起来——媒体查询、`env(safe-area-inset-*)`、`100dvh`、抽屉的
            # `position: fixed` 全都依赖真实视口宽度。缩放只是把桌面布局拍小，
            # 那是另一个东西。
            b"frame-src 'self'; "
            b"connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'",
        ),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"SAMEORIGIN"),
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

    # --- 新前端（山水版）-----------------------------------------------------
    #
    # 这一版走「前端优先」：界面先定稿，后端按它的契约补接口。十个页面是一组
    # 互相跳转的静态 HTML，自带 `assets/js` 那套 mock/rest 双模客户端。
    #
    # `/app` 单独挂一条路由而不是并进现有的六页：那六页有自己的四层令牌体系和
    # 一整套判据，两套东西混在一个目录里，谁都说不清哪条规则该管谁。
    # 页面之间用相对路径互相引用（`../assets/css/app.css`、`../art/png/…`、
    # `records.html`），所以直接按磁盘结构从 `/static/app/` 提供，一处都不用改写。
    # `/app` 只做一个跳转，给人一个短地址。
    @app.get("/app", include_in_schema=False)
    def elder_app_entry() -> RedirectResponse:
        return RedirectResponse(url="/static/app/pages/home.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        """浏览器不管你有没有，每开一页都会去要一次 `/favicon.ico`。

        没有这条路由的后果实测：山水版那十七页（它们不像老六页那样自己声明
        `<link rel="icon">`）每次加载都在控制台留一条
        「Failed to load resource: 404」。那不是产品缺陷，但它是**噪音**——
        而噪音的代价是真错误混在里面看不出来。这一轮扫十七页时，
        每一页唯一那条「控制台错误」都是它。

        图标复用 PWA 那一套现成的（`manifest.webmanifest` 指的就是这几个），
        不另做一份，免得哪天换了品牌图只改一处。
        """
        return FileResponse(
            static_dir / "icons" / "icon-192.png",
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

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

    @app.get("/stage", include_in_schema=False)
    def demo_stage() -> FileResponse:
        """桌面演示舞台：手机框 + 框内真实 App。

        它**不是**产品的一部分，是答辩、录屏和截图用的展示环境。控制条只存在于这一页，
        六个 App 页面里不出现——一位老人不该在自己的界面上看到"场景：诈骗"这种按钮。
        """
        return FileResponse(static_dir / "stage.html")

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
        # 每位访客的沙箱也要有自己的作息历史，否则新开的家庭永远停在"还在熟悉
        # 他的生活规律"，个性化基线这个核心创新点在公网演示里就是一片空白。
        # 与默认家庭同一个开关：合成回填只在演示部署里发生。
        if seed_history:
            baseline_store.seed_demo_for(suffix)
            db.seed_demo_reminders(ids)
            db.seed_demo_scenario(ids, "completed_bill_payment")
            # 照护页的「身体」与「心情」两段实测是空的（0 条 / event_count=0）。
            # 它们和上面三样一样是**演示历史**，所以挂在同一个开关上：真实部署
            # 不受影响。`v4_store.seed_demo()` 那个是无条件调用的，因为它种的是
            # 安全策略——那是配置，不是历史。
            v4_store.seed_demo_content(suffix)
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
        entity_id: str | None = Query(default=None, max_length=128),
    ) -> dict[str, Any]:
        """完整办事审计。给了 `entity_id` 就只回那一件事的链。

        `entity_id` 是**加法**：不给就和以前完全一样。加它的理由是可信中心那份凭证
        ——它要的是一件事的完整链，而原先只能「取最近 200 条再在客户端筛」。
        一个家庭用久了，第 201 条之前的事务就再也拼不出完整的链，而页面看不出来：
        它会渲染一份**少了前几步**的凭证，而凭证的全部价值就是「每一步都在」。

        权限一行没动：仍然只对绑定家属开放，过滤发生在 `family_id` 之内，
        所以它不可能变成一条跨家庭读取的路。
        """
        if actor.role != ActorRole.FAMILY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="完整办事审计仅向绑定家属开放。")
        events = db.list_audit(actor.family_id, limit=limit, entity_id=entity_id)
        return {
            # 链自校验始终针对**整条**家庭链，不是过滤后的子集：一条被截出来的
            # 子序列里 `prev_hash` 本来就接不上，拿它做自校验会永远报「链断了」。
            "chain_valid": db.verify_audit_chain(actor.family_id),
            "events": [event.model_dump(mode="json") for event in events],
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

    # 山水版老人端（`/app`）的门面。它把那一版前端写死的 `/api/v1/...` 路径翻译到
    # 真实业务上——复述核验、任务状态机、审计链都是同一份，不是第二套。
    # demo_mode 决定「没带令牌」是退回演示老人还是 401。
    # 不传的话这一层在真实部署里也会把演示家庭的数据发给任何人。
    app.include_router(build_app_router(db, engine, v4_store, demo_mode=resolved_demo_mode, voice=neural_voice))
    app.include_router(build_v4_router(db, v4_store, current_actor, medication_kb))
    app.include_router(build_v5_router(db, v5_store, current_actor))
    app.include_router(build_v6_router(db, v6_store, current_actor, neural_voice))
    app.include_router(
        build_baseline_router(db, baseline_store, current_actor, baseline_store.errand_facts)
    )

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
