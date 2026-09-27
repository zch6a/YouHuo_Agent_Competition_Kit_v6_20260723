"""`/api/v1` —— 山水版老人端前端的后端门面。

这一层是「前端优先」的产物：界面先定稿，后端按它已经写死的契约补接口
（见 `backend/static/app/docs/BACKEND_INTEGRATION.md`）。

**它是门面，不是第二套业务。** 每一个接口都往下调真实服务：

    POST /payments/{id}/teach-back  →  TeachBackVerifier.verify（真的核对金额）
    POST /payments/{id}/execute     →  真实任务状态机 + 家人二次确认
    GET  /payments/{id}/certificate →  真实审计链（database.list_audit，按事务过滤）
    GET  /records                   →  真实审计流水

为什么翻译放在后端而不是改前端：那十个页面的 `assets/js/api-client.js` 里路径是
写死的，改前端等于把 Codex 的产出重写一遍。翻译放在这里，前端一行不用动，
而业务逻辑仍然只有一份。

**没有的数据就说没有。** 天气、空气、体感、睡眠、位置凭证、设备凭证这些后端
确实没有，一律回 `null`，由前端决定怎么显示——不编。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .asr import UnsupportedAudio
from .baseline_services import EnvironmentComfort, EnvironmentReader
from .database import IdempotencyConflict
from .memory_vault import (
    MemoryItem,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)
from .app_schemas import (
    AppAgenda,
    AppAppointmentCreated,
    AppAppointmentList,
    AppBill,
    AppBillList,
    AppCertificate,
    AppContact,
    AppContactList,
    AppDailyReport,
    AppDoseRecorded,
    AppEmergencyResult,
    AppEmotionReview,
    AppHealthRecorded,
    AppHealthSummary,
    AppListenResult,
    AppListenStatus,
    AppMedicationDecided,
    AppMedicationToday,
    AppMemoryDecided,
    AppMemoryList,
    AppNotificationList,
    AppNotificationRead,
    AppPaymentMoved,
    AppPaymentPrepared,
    AppPendingMedicationList,
    AppPrivacyErased,
    AppPrivacyErasePreview,
    AppPrivacyExport,
    AppProfile,
    AppRecordList,
    AppReminderChanged,
    AppReminderCreated,
    AppReminderList,
    AppRoutineChanged,
    AppRoutineList,
    AppSettings,
    AppSpeechStatus,
    AppTeachBackResult,
    AppVoiceSession,
    AppWaterBill,
)
#: 「谁动的」那条规则的事实源在 privacy 那一层，导入同一个集合。
from .privacy import _ELDER_ACTIVITY_LABELS, _WHO_FROM_ACTOR
#: 紧急访问那四个范围的中文说法。**导入同一个函数，不抄一份表。**
#: `v5_store._SCOPE_WORDS` 的注释里记着它存在的理由：原来那句通知直接把
#: 范围名拼进去，于是她屏幕上是「家属因紧急情况临时查看：location。」
#: 这里再抄一份中文名，两处迟早分叉，而分叉的症状是两屏对同一次访问
#: 说出不同的范围，两边各自都不报错。
from .v5_store import _SCOPE_WORDS, _scope_words
from .security import SafetyPolicy
from .services import BILL_COMPANY
from .utils import local_now, local_today, local_zone, request_fingerprint, semantic_hash
from .models import (
    ActorRole,
    AuthContext,
    ChatRequest,
    FamilyReminderCreateRequest,
    ReminderRecord,
    ReminderStatus,
    RiskLevel,
    SessionState,
    TaskRecord,
    TaskStatus,
    TaskType,
)
from .teach_back import TeachBackOutcome, TeachBackVerifier

#: 演示用的老人身份。这一版前端不带令牌（它的 `api-client.js` 走 cookie），
#: 所以身份在服务端固定到演示家庭的老人，与 `/v2/auth/demo` 用的是同一套数据。
_DEMO_ELDER = "elder-demo"

#: 点头的那个家人。查库定的，不是猜的：
#:   elder-demo / daughter-demo / son-demo / system-demo（家庭 fam-demo）
#: 取「女儿」这一个，因为凭证上要写清是**谁**点的头——写一个不存在的人比不写更糟。
_DEMO_FAMILY = "daughter-demo"

#: 家人点头之后写的那条审计。用大写下划线，和主引擎那套保持一致，
#: 这样记录页的翻译表能认出它（那张表的 key 是查库查出来的，见 `_WORDS`）。
_EV_FAMILY_APPROVED = "FAMILY_APPROVED_AND_EXECUTED"

#: 这一笔水费是**演示数据**，金额与单位跟现有 demo seed 一致。
#: 真接上营业厅之后换成查询即可，前端契约不变。
_WATER_BILL = {
    "id": "water-current",
    "type": "水费支付",
    "amount_cents": 6840,
    "company": "示例自来水公司",
    "account_tail": "1234",
    "month": "本月",
}

#: 这一端**借用记忆表存自己的东西**时用的键。
#:
#: 它们不是「优活替这位老人记下来的事」，是这一层的存储细节，所以
#: 「记忆」那张列表不许列它们，同意/拒绝/忘掉三条路也不许作用在它们上。
#:
#: 实测（老人拖一下字号滑块之后读 `/api/v1/memories`）：
#:
#:     优活替您记着 1 件事。哪一条不想让它记了，随时可以忘掉。
#:       key      elder_app_settings
#:       detail   voiceSpeaker：0
#:
#: 两个英文内部标识印在老人屏幕上（界面上不许出现英文枚举值是硬约束），
#: 而那句话下面就是「忘掉」——她按一下，`revoke` 把这一条置成 REVOKED，
#: `_pref_item` 从此跳过它，**她自己的发音人和配色就没了**。
#: 一个破坏性动作，挂在一张说的是别的事情的屏幕上。
_INTERNAL_MEMORY_KEYS = frozenset({"elder_app_settings"})

#: 审计事件类型。前端不认这些字符串，它们只在后端之间用。
_EV_PREPARED = "app.payment.prepared"
_EV_TEACH_BACK = "app.payment.teach_back"
_EV_AWAITING_FAMILY = "app.payment.awaiting_family"
_EV_SOS = "app.emergency.requested"
#: 提醒与设置。**加一个事件类型就必须同时加一条 `_WORDS`**——否则记录页会
#: 落到兜底文案「办了一件事」，而那一行看起来完全正常，没有任何东西会报红。
_EV_REMINDER_CREATED = "app.reminder.created"
_EV_REMINDER_DONE = "app.reminder.completed"
_EV_REMINDER_CANCELLED = "app.reminder.cancelled"
_EV_SETTINGS_CHANGED = "app.settings.changed"
_EV_APPOINTMENT_CREATED = "app.appointment.created"
_EV_SOS_NOTIFY_FAILED = "app.emergency.notify_failed"
_EV_CONTACT_PHONE_SET = "app.contact.phone_set"
_EV_HEALTH_RECORDED = "app.health.recorded"
_EV_REMINDER_MOVED = "app.reminder.moved"
_EV_APPOINTMENT_CANCELLED = "app.appointment.cancelled"
_EV_MEDICATION_DECIDED = "app.medication.decided"
_EV_MEMORY_DECIDED = "app.memory.decided"
_EV_MEMORY_FORGOTTEN = "app.memory.forgotten"
_EV_ROUTINE_CREATED = "app.routine.created"
_EV_ROUTINE_PAUSED = "app.routine.paused"
_EV_ROUTINE_RESUMED = "app.routine.resumed"
#: 删除个人数据。这是这三个新端点里**唯一**的写操作——导出、心情回顾、生活日报
#: 都是纯读，一条审计都不该写（写了就意味着"看一眼"改动了状态）。
_EV_PRIVACY_ERASED = "app.privacy.erased"


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


class _AlreadyCalled(Exception):
    """一分钟内已经呼叫过了。

    用异常而不是 `if` 嵌套，是为了让「不重复推送」和「推送失败」共用同一个出口——
    两者都要走到「呼叫本身照记、只是不发第二条」那个分支，而它们的**原因不同**，
    所以只有后者写 `notify_failed` 审计。
    """


#: 已经走完的事务状态。用它判断「这张账单还有没有一笔在飞」。
#: 单列出来是因为「哪些算结束了」这件事以后还会有人问，
#: 而写成散在各处的 `not in {...}` 迟早会有一处漏掉 CANCELLED。
_TASK_DONE = frozenset({
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
})


def _parse_when(raw: str) -> datetime:
    """把老人说得出的时间变成一个时刻。

    两种写法：`HH:MM`（今天，已经过点就顺延到明天）和完整 ISO 串。

    「过点顺延」不是小聪明，是这一层唯一合理的解释：9 点的时候说「设 8 点吃药」，
    意思显然是明天 8 点，而不是造一条建出来就已经过期的提醒。

    抽成函数是因为**建提醒和改提醒必须用同一套解析**——两处各写一遍，
    迟早会有一处忘了顺延，而那一处建出来的提醒永远不会响。
    """
    now = datetime.now(UTC)
    try:
        if len(raw) <= 5 and ":" in raw:
            hh, mm = (int(x) for x in raw.split(":", 1))
            # 老人说的「八点」是**墙上时间**，不是 UTC 的八点。
            #
            # 原先这里直接 `now(UTC).replace(hour=8)`，配上显示端同样直接
            # `strftime` 回去——这一层内部自洽（说八点看到八点），
            # 但存下来的时刻是 08:00 UTC，在东八区实际是下午四点。
            # 提醒的到点判定、升级计时、和例程排出来的提醒都按真实时刻走，
            # 所以这一条只在**跨出这一层**的时候暴露：
            # 例程建的「每天八点」显示成 00:00，因为那是真的八点。
            local = local_now(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
            due = local.astimezone(UTC)
            return due + timedelta(days=1) if due < now else due
        due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return due if due.tzinfo else due.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="这个时间看不懂，请再说一遍。") from None


def _bounds_of(model: Any, field: str) -> tuple[int, int]:
    """从一个 Pydantic 模型的字段上读出 `ge` / `le`。

    为了让「同一个字段两条路」用**同一个**来源：抄一份数字下来，
    哪天家属那条路改了界，这一侧还按旧界放行，而且没人会发现。
    读不到界就当场炸——静默退回一个猜出来的界，等于把这条判据关掉。
    """
    meta = model.model_fields[field].metadata
    low = next((m.ge for m in meta if getattr(m, "ge", None) is not None), None)
    high = next((m.le for m in meta if getattr(m, "le", None) is not None), None)
    if low is None or high is None:
        raise RuntimeError(
            f"{model.__name__}.{field} 上没有 ge/le 了（读到 {meta!r}），"
            f"老人那条路的界就没有出处了——先决定界是什么，再改这里。")
    return int(low), int(high)


def build_app_router(db, engine, v4_store=None, *, demo_mode: bool = True, voice=None,
                     v6_store=None, memory_vault=None, ears=None,
                     baseline_store=None) -> APIRouter:

    class _IdempotentRoute(APIRoute):
        """带 `Idempotency-Key` 的写请求，重放同一个响应。

        ## 为什么做在路由层，不是逐个端点加参数

        这一层有十来个写端点，以后还会加。逐个加 `idempotency_key` 参数的失败方式是
        **漏掉一个不会有任何东西提醒**——那个端点从此没有幂等，而它看起来和别的
        一模一样。做在路由层，新加的端点自动就有。

        ## 和「连点两下」那一批是两件事

        那一批（execute 早返回、prepare 复用在飞的一笔、SOS 节流）守的是
        **业务语义**：同一件事不许发生两次，不管请求长什么样。
        这里守的是**传输层**：同一个请求被重发（客户端超时重试、代理重投），
        应当拿回第一次的那个答案，而不是再执行一次。

        两者都要。业务判断挡不住「同一个请求发两遍但状态还没落库」的竞态；
        幂等键挡不住「用户真的按了两次不同的请求」。

        ## 只缓存 2xx——而这一条目前其实碰不到

        意图是：把一个 400 缓存下来，等于让客户端修好参数重试时仍然拿到那个 400，
        而它的 `Idempotency-Key` 多半没变。失败不该被钉死。

        **但实测下来这个判断是死代码**：这一层的失败都走 `HTTPException`，
        它让路由处理器**抛出**而不是返回，`await original(request)` 之后的代码
        根本执行不到（拿探针包了 `save_idempotent_response` 验过，一次都没被调）。
        「失败不钉住 key」这条性质是成立的，只是不靠这个判断成立。

        判断留着：以后要是有端点**返回**（而不是抛出）一个 4xx/5xx，它就生效了。
        写清楚它现在碰不到，是为了下一个人不要以为这条已经被覆盖了。
        """

        def get_route_handler(self):
            original = super().get_route_handler()

            async def handler(request: Request) -> Response:
                if request.method not in {"POST", "PUT", "PATCH"}:
                    return await original(request)
                key = request.headers.get("Idempotency-Key")
                if not key:
                    return await original(request)

                body = await request.body()
                # 指纹带上路径：同一个 key 用在两个不同端点上是调用方的错，
                # 应当报冲突，而不是把 A 的响应回给 B。
                scope = "app_api"
                fingerprint = request_fingerprint(
                    {"path": request.url.path, "body": body.decode("utf-8", "replace")}
                )
                try:
                    cached = db.get_idempotent_response(scope, key, fingerprint)
                except IdempotencyConflict as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        #: 措辞用 `IdempotencyConflict.WORDS`，不在这里再抄一份：
                        #: 两处各写一份，屏幕上迟早出现同一件事的两种说法。
                        detail=IdempotencyConflict.WORDS,
                    ) from exc
                if cached is not None:
                    return JSONResponse(cached, headers={"Idempotency-Replayed": "true"})

                response = await original(request)
                if 200 <= response.status_code < 300:
                    raw = getattr(response, "body", None)
                    if raw:
                        try:
                            db.save_idempotent_response(
                                scope, key, fingerprint, json.loads(raw)
                            )
                        except (ValueError, TypeError):
                            pass      # 不是 JSON 就不缓存，别把响应弄坏
                return response

            return handler

    router = APIRouter(prefix="/api/v1", tags=["elder-app"], route_class=_IdempotentRoute)
    bearer = HTTPBearer(auto_error=False)

    def _actor(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AuthContext:
        """这次请求是谁。

        原先这一层**没有身份概念**：`_ctx()` 无条件返回 `elder-demo`，
        写死在源码里。演示时看不出问题（只有一个家庭），但它意味着
        这一整层不能给第二个人用——而且真要部署出去的话，
        任何人访问 `/api/v1/*` 都会拿到演示家庭的账单、支付和整条审计链。

        现在三条路，顺序不能换：

        ① 带了令牌 → 按令牌解析，和 `/v2` 走的是同一个 `resolve_auth_token`
        ② 带了令牌但无效 → **401，不许退回演示身份**。
           过期令牌静默变成演示老人，是比没有鉴权更糟的一种失败：
           调用方以为自己登录着，实际在操作别人的数据。
        ③ 没带令牌 → **只有演示模式下**才退回演示老人。
           非演示部署下没令牌就是 401。
        """
        if credentials is not None and credentials.scheme.casefold() == "bearer":
            actor = db.resolve_auth_token(credentials.credentials)
            if actor is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="访问令牌无效或已过期。",
                )
            return actor

        if not demo_mode:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少访问令牌。",
            )
        ctx = db.auth_context_for_actor(_DEMO_ELDER)
        if ctx is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="演示数据还没有铺好。",
            )
        return ctx

    def _elder_of(ctx: AuthContext) -> str:
        """这次请求是在看**哪位老人**的数据。

        老人自己登录 → 就是他本人。家人登录 → 他家里那位老人
        （这一层是老人端的门面，家人拿令牌进来时看的仍然是老人的日程和账单）。
        写死 `elder-demo` 的时候这个区别不存在，所以它一直没有被表达出来。
        """
        if ctx.role is ActorRole.ELDER:
            return ctx.actor_id
        for row in db.list_actors(ctx.family_id):
            if row["role"] == "elder":
                return row["id"]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="这个家庭里还没有登记老人。"
        )

    def _only_the_elder(ctx: AuthContext, what: str) -> None:
        """这一类决定**只能由老人本人做**。

        ## 这道守卫为什么必须写在这一层

        底层两处早就有它：

            /v3/memories/decide      `actor.role != ELDER → 403 只有老人本人可以批准长期记忆。`
            /v4/medications/decide   `actor.role != ELDER → 403 只有老人本人可以激活家属补充的用药计划。`

        而这一层的 `_decide_memory` / `_decide_plan` 照抄了调用、**没有照抄守卫**，
        并且传的是 `_elder_of(ctx)`——家人令牌会被解析成「她家那位老人」，
        于是底层那句「只有本人」的校验，被一个不属于调用者的 id 满足了。

        实测（女儿的令牌）：

            /v3/memories/decide          403  只有老人本人可以批准长期记忆。
            /api/v1/memories/{id}/approve 200  好，我记住「早上散步的时间」了
            /api/v1/memories/{id}/forget  200  好，「早上散步的时间」我不再记着了
            /api/v1/medications/{id}/approve 200  好，钙片从今天开始按计划吃。

        同一个控制，一层有一层没有。而这五个决定恰恰是这个产品的立身之本：
        「同意记忆」要她点头才记，家属补的药要她点头才吃。家人能替她点，
        这两句话就都不成立了——**而两边界面都正常，审计里还老老实实记着是女儿干的**。

        `_elder_of()` 存在是对的（家人看老人的日程和账单，那是只读）。
        它不该被用在**代替她做决定**的路径上，这是那个函数与这个守卫的分界。
        """
        if ctx.role is not ActorRole.ELDER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"只有老人本人可以{what}。",
            )

    def _approver_of(ctx: AuthContext) -> AuthContext:
        """谁来点这个头。

        原先写死 `daughter-demo`。现在取这个家庭里的家人成员；
        请求本身就是家人发来的话，就是他自己——**家人点头必须记真人**，
        凭证上「谁点的头」这一格是这个产品的核心。
        """
        if ctx.role is ActorRole.FAMILY:
            return ctx
        preferred = sorted(
            (r for r in db.list_actors(ctx.family_id) if r["role"] == "family"),
            key=lambda a: (a["id"] != _DEMO_FAMILY, a["display_name"]),
        )
        for row in preferred:
            approver = db.auth_context_for_actor(row["id"])
            if approver is not None:
                return approver
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="这个家庭还没有登记可以确认的家人。",
        )

    def _task_or_404(ctx: AuthContext, task_id: str) -> TaskRecord:
        task = db.get_task(task_id)
        if task is None or task.family_id != ctx.family_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="没有找到这件事。"
            )
        return task

    # ---- 档案 ---------------------------------------------------------------

    @router.get("/profile")
    def profile(ctx: AuthContext = Depends(_actor)) -> AppProfile:
        # 「优活已陪伴您 N 天」。
        #
        # 原先这里是写死的 `None`，注释写着「后端没有建档日期这个字段，不编」——
        # 那时是对的。但审计链的**第一条**就是这份记录的开端，那是真数据：
        # `families` 表确实没有建档日期，`audit_events` 却有时间戳。
        # 不足一天算 1 天，不是 0——用了半天说「陪伴您 0 天」是奇怪的。
        first = db.first_audit_at(ctx.family_id)
        days = None
        if first is not None:
            if first.tzinfo is None:
                first = first.replace(tzinfo=UTC)
            days = max(1, (datetime.now(UTC) - first).days + 1)
        return {
            "name": ctx.display_name,
            "days": days,
            # 天气和空气这一层**确实**没有数据源（没有外部气象接口），保持 null。
            "weather": None,
            "air": None,
            # 体感不一样：`/v7/environment/samples` 一直在收温湿度和光照
            # （`environment_samples_v7` 表、`latest_environment()` 读回、
            # `EnvironmentReader` 判冷热干湿暗），而这一层从来没有去读它——
            # 存进去的读数在 `/v7` 那一侧有人用，在老人自己的首页上没有。
            # `home.html` 的 `data-bind="profile.comfort"` 早就在那儿，
            # 外层 `data-hide-when-empty` 所以看起来只是"这一行没内容"。
            #
            # 那块 ESP32-S3 板子上的 DHT11 和光照传感器供的正是这三个数。
            "comfort": _comfort_line(ctx),
        }

    def _comfort_line(ctx: AuthContext) -> str | None:
        """「屋里26℃、湿度58%。」——没有新鲜读数时回 None，不编。

        ## 为什么只在"新鲜"时给

        `EnvironmentReader` 对没读数和过期读数都回 `UNKNOWN`，但过期那一支的
        `note` 是一句诊断话（「室内环境数据已经过期，这次没有参考它。」）。
        那句话出现在老人首页的大标题下面是不对的——它是给排查用的，
        不是给她看的。所以判据是 `UNKNOWN 不在 comforts 里`，
        而不是「note 非空」。

        ## 为什么直接用 note，不自己拼一句

        冷热干湿暗那几个字怎么说，`CareComposer` 已经有一套（而且刻意写成
        「偏离不是指控」的语气）。在这里再拼一遍就是第二个事实源，
        迟早两处不一致。这一层只借它已经算好的那句话。
        """
        if baseline_store is None:
            return None
        try:
            elder_id = _elder_of(ctx)
        except HTTPException:
            # 这个家庭还没登记老人。首页不该因为少一行体感就整个 404。
            return None
        sample = baseline_store.latest_environment(
            family_id=ctx.family_id, elder_id=elder_id
        )
        reading = EnvironmentReader.read(sample, now=datetime.now(UTC))
        if EnvironmentComfort.UNKNOWN in reading.comforts:
            return None
        return reading.note

    # ---- 今日日程 -----------------------------------------------------------

    #: 就医安排顺带建的那条提醒带这个 `source`。
    #:
    #: 它是 `appointments` 和 `reminders` 之间**唯一**的联系——没有外键。
    #: 抽成常量是因为它现在有两个使用点（写的时候和读的时候），
    #: 散成两个字面量的失败方式是改一处、另一处静默地再也匹配不上，
    #: 而表现只是「地点那一格又空了」，不报任何错。
    _APPOINTMENT_SOURCE = "elder-app-appointment"

    def _appointment_place(ctx: AuthContext, item: dict[str, Any],
                           source: str, today: date) -> str | None:
        """这一件如果是一次就医安排，给出「医院 · 科室」；否则 None。

        ## 为什么不按标题反解

        那条提醒的标题是 `去{医院}{科室}就诊`，看起来可以从里面把医院抠出来。
        但那是拿**显示文本**当数据用：改一次文案，这里就静默地不准了。
        `source` 是 `create_appointment` 明确写下的标记，是真正的联系。

        ## 同一时刻有两条就医安排时不猜

        没有外键，只能按「今天 + 这个钟点」去对。两条同一时刻的安排会让
        「是哪一家医院」没有唯一答案——那时回 None。
        **首页少一行地点，比指错一家医院好**：老人会照着它出门。
        """
        if source != _APPOINTMENT_SOURCE:
            return None
        hit = None
        for row in db.list_appointments(ctx.family_id, _elder_of(ctx)):
            # 已取消的不给地点。取消是两张表一起改的，但万一只改了一半，
            # 这里也不该把一个已取消的门诊指给她。
            if str(row["status"]) == "cancelled":
                continue
            if str(row["appointment_date"]) != today.isoformat():
                continue
            if str(row["appointment_time"] or "")[:5] != item["time"]:
                continue
            if hit is not None:
                return None
            hit = row
        if hit is None:
            return None
        hospital = str(hit["hospital"] or "").strip()
        if not hospital:
            return None
        department = str(hit["department"] or "").strip()
        return f"{hospital} · {department}" if department else hospital

    @router.get("/agenda")
    def agenda(ctx: AuthContext = Depends(_actor)) -> AppAgenda:
        """首页那两张卡（「接下来」和「今日安排」）的真实数据源。

        原稿这两张卡是写死的——「14:00 心内科复诊 · 和睦家医院 2号楼3层」「08:00
        吃降压药」。那是稿子，不是这位老人的事。这里改成读真实提醒表。

        `place` 只在这一件确实是一次**就医安排**时才有值（见 `_appointment_place`）。
        别的提醒后端真没有地点字段，那时仍然回 null——宁可不显示，也不编一个医院。
        """
        now = datetime.now(UTC)
        today = local_now(now).date()      # 「今天」按老人所在时区切，不按 UTC
        items = []
        #: 提醒 id → 它的 `source`。只留在服务端，不进响应（英文标记）。
        sources: dict[str, str] = {}
        # 只取「今天前后」那一段。
        #
        # 原先是 `limit=60` 不带窗口，而那条 SQL 是升序 + LIMIT——
        # 留下的是**最老的** 60 条。历史一攒多，今天的行就被挤出去，
        # 这一屏**永久**写着「今天没有安排」，而 `/api/v1/reminders`
        # 里今天那几条都还在。实测：过去 80 条时 count=0 / next=None。
        # 触发条件只是时间流逝（一条每天的例程约两个月）。
        #
        # 窗口刻意比「今天」宽一天：本地当天的界限换算成 UTC 之后，
        # 边界上那几条（本地 00:10 = UTC 前一天 16:10）不能被切掉。
        # **「今天」这道判断仍然由下面那句 `due.date() != today` 说最终话**，
        # SQL 只负责别把相关的行挤出窗口。
        #
        # limit 从 60 提到 200：窗口有界之后 limit 只是安全阀，
        # 而一条按小时重复的例程三天就能超过 60 条。
        day_start = local_now(now).replace(hour=0, minute=0, second=0, microsecond=0)
        for r in db.list_reminders(
            ctx.family_id,
            limit=200,
            since=day_start - timedelta(days=1),
            until=day_start + timedelta(days=2),
        ):
            if r.elder_id != _elder_of(ctx):
                continue
            # 一律换算到老人所在时区再比日期、再读钟点。
            #
            # 原先这里直接拿 UTC 的 `date()` 和 `strftime`。同一层内自洽，
            # 但**跨出这一层就错**：例程排出来的提醒存的是真实时刻，
            # 「每天早上八点」于是显示成 00:00。
            due = local_now(r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=UTC))
            if due.date() != today:
                continue
            # 取消掉的不在今天的安排里。
            #
            # 原来只把 COMPLETED / ACKNOWLEDGED 当成"办完了"，于是一条**已取消**的
            # 提醒既不算完成、也没被排除，照样进「今日安排」，还能被挑成「接下来」。
            # 实测的样子：在用药页取消「吃钙片」，那一条当场变成「已取消」，
            # 而首页顶上仍然写着「07:30 吃钙片」——同一条提醒，两个屏幕两种说法。
            if r.status is ReminderStatus.CANCELLED:
                continue
            # **「知道了」不是「办完了」。**
            #
            # 这两个原先合并成一个 `done`，屏幕上一起写「已完成」。后果：老人在
            # 一条用药提醒上按「我知道了」，日程上那一行当场变成「已完成」——
            # 系统替她宣称她吃过药了，而她只是说了句知道。她第二天回头看记录，
            # 看到的是一件她其实没做的事被记成做了。
            #
            # 同一件事在设计一那边是分开的：`elder.js` 的 `REMINDER_STATUS` 里
            # `acknowledged` 是「知道了」，语气 `todo`（还没办）。也就是说这一层
            # 和那一层对同一条提醒的说法是相反的——这个项目为「两套实现各自
            # 都对、跨子系统才错」栽过一次（字号语速与 SOS）。
            #
            # `done` 只认真的办完了。它同时决定「接下来」挑哪一件
            # （下面 `undone = [it for it in items if not it["done"]]`）：
            # 按过「知道了」的那件药还是没吃，它就该继续待在「接下来」。
            acknowledged = r.status is ReminderStatus.ACKNOWLEDGED
            done = r.status is ReminderStatus.COMPLETED
            # `source` 只留在服务端。它是英文标记（`elder-app-appointment`），
            # 放进响应就会有人直接摆到屏幕上——这一层的规矩是界面上不出现
            # 英文枚举值。这里只用它来判断「这一件是不是一次就医安排」。
            sources[r.id] = str(r.source or "")
            items.append(
                {
                    "id": r.id,
                    "time": due.strftime("%H:%M"),
                    "title": r.title,
                    "done": done,
                    "status": "已完成" if done else ("知道了" if acknowledged else "待进行"),
                    "at": due.isoformat(),
                }
            )
        items.sort(key=lambda x: x["time"])

        # 「接下来」= 今天**还没做**的第一件。
        #
        # 第一版要求「时间还在此刻之后」，结果傍晚打开首页时这张卡是空的——
        # 而那两件事只是过了点、并没有做完。对一位老人来说，一件过点还没吃的药
        # 恰恰是最该摆在「接下来」的东西，不是该被藏起来的东西。
        # 优先取还没到点的；都过点了就取最早那一件，并标出来它已经过点。
        undone = [it for it in items if not it["done"]]
        #: 按**时刻**比，不按字符串比。
        #:
        #: `at` 带 `+08:00`，`now.isoformat()` 带 `+00:00`；字典序把两个偏移量
        #: 都忽略掉，比的是「北京钟面」对「UTC 钟面」，而前者恒等于后者 +8。
        #: 结果是过点不到 8 小时的事全判成「还没到点」，`overdue` 恒为 False。
        #: 实测：晚上 11 点，首页把下午四点该吃的降压药写成「到点提醒」。
        ahead = [it for it in undone if datetime.fromisoformat(it["at"]) > now]
        pick = (ahead or undone or [None])[0]
        nxt = None
        if pick is not None:
            overdue = datetime.fromisoformat(pick["at"]) <= now
            nxt = {
                "time": pick["time"],
                "title": pick["title"],
                # 原来这里恒为 None，注释写着「后端没有地点字段——不编一个医院
                # 出来」。那句话对**提醒**是对的，对**就医安排**不对：
                # `appointments` 表一直存着 hospital / department，
                # `/api/v1/appointments` 也在读它。少的只是这一层没去对上。
                #
                # 于是「接下来 · 09:30 去市第一医院心内科就诊」这一行，
                # 明明知道是哪家医院，却在地点那一格里说不知道。
                "place": _appointment_place(ctx, pick, sources.get(pick["id"], ""), today),
                "note": "这一件已经过点了。" if overdue else None,
                "overdue": overdue,
            }
        return {"next": nxt, "today": items, "count": len(items)}

    # ---- 健康概览（「我的」那一屏）------------------------------------------

    @router.get("/health-summary")
    def health_summary(ctx: AuthContext = Depends(_actor)) -> AppHealthSummary:
        """「我的」页那一排健康数字的真实来源。

        原稿这里写死了「今日健康 良好 / 心率 72 次每分 / 血压 120/78 / 睡眠 7.5 小时」。
        后端的实情是：有一张 `health_events_v4` 事件表（真的记了什么就有什么），
        **没有**体征快照，也**完全没有**睡眠这一项。

        所以这里回的是「记到了什么」，不是「他现在怎么样」——这两件事差得很远，
        而把后者编出来正是这个产品最不该做的。取不到的一律 null。
        """
        metrics: list[dict[str, Any]] = []
        events = []
        if v4_store is not None:
            try:
                # 视角传**调用者的角色**。写死 `ELDER` 的话，
                # `list_health_events` 那句 `if viewer_role == FAMILY: 滤掉 PRIVATE`
                # 就永远不生效，家人读这一屏会读到老人标了私密的身体记录——
                # 而这些数字下面还印着「记到了什么」，看起来完全正常。
                # 同一个文件里 `/api/v1/memories` 犯的是同一个错，一并修了。
                events = v4_store.list_health_events(
                    ctx.family_id, _elder_of(ctx), ctx.role
                )
            except Exception:
                events = []

        # 按**测量项**去重，不是按事件类别。
        #
        # 原先的 key 是 `kind`，而 `HealthEventKind` 只有 checkup/visit/medication/note
        # 四个值——血压、体重、血糖、体温**全都是 checkup**。于是先记血压再记体重，
        # 体重把血压顶掉，那一屏只剩最后记的那一项。实测：连记两条，`metrics` 只有一条。
        latest: dict[str, Any] = {}
        for e in events:                       # 已按时间倒序，第一条即最新
            label = str(getattr(e, "title", "")) or str(getattr(e, "kind", "")) or "其他"
            if label not in latest:
                latest[label] = e

        for label, e in list(latest.items())[:6]:
            payload = getattr(e, "payload", None) or {}
            # 拿不到值就**留空**，不要把标题填进去。
            #
            # 原先兜底到 `title`，于是标签和值变成同一串字：屏幕上是
            # 「早晨量了血压:132/84 —— 早晨量了血压:132/84」。那些事件的 payload 里
            # 存的是 `systolic`/`diastolic` 这类结构化字段，本来就没有 `value`；
            # 兜底把「这条记录没有单一读数」显示成了「读数等于它的标题」。
            raw = payload.get("value") or payload.get("text")
            metrics.append(
                {
                    "label": label,
                    "value": str(raw) if raw else None,
                    "unit": payload.get("unit"),
                    "at": e.event_at.isoformat() if getattr(e, "event_at", None) else None,
                }
            )

        return {
            # 「今日健康 良好」是一句结论。后端没有做这个判断的依据，就不下这个结论。
            "overall": None,
            "metrics": metrics,
            "recorded": len(events),
            "note": None if metrics else "还没有记到身体数据。",
        }

    # ---- 账单 ---------------------------------------------------------------

    @router.get("/bills/water/current")
    def current_water_bill(ctx: AuthContext = Depends(_actor)) -> AppWaterBill:
        """当前这一笔水费。**读真表，不再返回源码里那个字典。**

        原先这里返回硬编码的 `_WATER_BILL`，`paidAt` 则去扫「任意一笔已完成的
        缴费事务」取时间。两个缺陷都是实测出来的：

        ① **两个端点报的不是同一张账单。** 这里回 `water-current`，而 `/bills`
           回的是真 id `bill-water-2026-07-demo`。客户端拿前者去
           `GET /bills/{id}` 当场 404——两条路说的是同一件事，id 却对不上。

        ② **付之前 `paidAt` 就已经有值了。** 那个扫描不区分是哪一张账单，
           而演示种子里本来就有一笔已完成的缴费（`task-seed-bill-demo`）。
           于是一张没付的账单，显示着另一笔交易的支付时间——
           和凭证页写死「交易成功」是同一类错误：宣称一件没发生的事。

        现在 `paidAt` 取这张账单**自己的** `paid_at`。
        """
        row = _current_water_row(ctx)
        if row is None:
            raise HTTPException(status_code=404, detail="现在没有水费账单。")
        return _water_view(row)

    def _current_water_row(ctx: AuthContext):
        """这个家庭「当前」那张水费。

        优先未缴的（那才是老人要办的事）；全都缴清了就给最近一张，
        让界面能显示「已缴清」而不是空白。`list_bills` 已经按
        「未缴在前、到期日升序」排好。
        """
        water = [r for r in db.list_bills(ctx.family_id) if r["bill_type"] == "水费"]
        if not water:
            return None
        return next((r for r in water if not r["paid"]), water[0])

    def _water_view(row) -> dict[str, Any]:
        """老端点 `/bills/water/current` 的形状。

        和 `_bill_view` 不一样，而且不能合并：这个形状是前端先定稿、后端跟着补的，
        它有 `accountTail` 而没有 `paid`/`period`。合并会让调用方当场读不到字段。
        `accountTail` 库里没有这一列，取账单 id 的后四位——它是稳定的、
        而且不是编出来的号码。
        """
        period = str(row["period"] or "")
        paid_at = row["paid_at"]
        if paid_at:
            try:
                when = datetime.fromisoformat(str(paid_at).replace("Z", "+00:00"))
                #: 走老人所在时区再格式化。这个文件里同一个坑记过三次
                #: （提醒的钟点、通知的钟点），凭证这几处当时漏了。
                paid_at = local_now(when).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        return {
            "id": row["id"],
            # 前端那一页显示的是「水费支付」，而库里的 `bill_type` 是「水费」。
            "type": f"{row['bill_type']}支付",
            "amount": _yuan(int(row["amount_cents"] or 0)),
            "company": _BILL_COMPANY.get(row["bill_type"]) or "",
            "accountTail": str(row["id"])[-4:],
            "month": (period.split("-", 1)[1].lstrip("0") + "月") if "-" in period else period,
            "paidAt": paid_at,
        }

    #: 账单类型 → 收费单位。**这一份不在这里定义**，从 `services.BILL_COMPANY` 取。
    #:
    #: 它原先是这个路由工厂里的一个局部字典，于是槽位那一侧（`billing.lookup`）
    #: 没有它——语音建的支付凭证上「向谁交的钱」永远是空的，而按钮建的有值。
    #: 同一张凭证、同一笔水费，两条路径两个结果。表挪到填槽的地方去了，
    #: 这里只是引用；两份会分叉，一份不会。
    _BILL_COMPANY = BILL_COMPANY

    def _bill_view(row: Any) -> dict[str, Any]:
        kind = row["bill_type"]
        period = str(row["period"] or "")
        return {
            "id": row["id"],
            "type": kind,
            "amount": _yuan(int(row["amount_cents"] or 0)),
            "amountCents": int(row["amount_cents"] or 0),
            "company": _BILL_COMPANY.get(kind),
            "month": (period.split("-", 1)[1].lstrip("0") + "月") if "-" in period else period,
            "period": period,
            "dueDate": row["due_date"],
            "paid": bool(row["paid"]),
            "status": "已缴清" if row["paid"] else "待缴纳",
            "paidAt": row["paid_at"],
        }

    @router.get("/bills")
    def list_bills(ctx: AuthContext = Depends(_actor)) -> AppBillList:
        """这个家庭的**全部**账单。

        原先 `/api/v1` 只暴露一张写死的水费，而库里躺着三张（水费 68.40、
        电费 126.50、燃气费 52.30）。于是前端那张「我的账单」永远只有一件事可办，
        而演示里最容易被问到的一句话正是「除了水费还能干什么」。
        """
        rows = db.list_bills(ctx.family_id)
        items = [_bill_view(r) for r in rows]
        unpaid = [i for i in items if not i["paid"]]
        return {
            "items": items,
            "count": len(items),
            "unpaidCount": len(unpaid),
            "unpaidTotal": _yuan(sum(i["amountCents"] for i in unpaid)),
        }

    #: 单张账单。
    #:
    #: 这里原先写着一句「声明顺序有讲究，`/bills/water/current` 必须排在前面，
    #: 否则 `water` 会被当成 bill_id 吃掉」——**那句是错的，我没验就写了下来。**
    #: 变异测试时把一条 `/bills/{bill_id}` 塞到前面，`/bills/water/current` 照样 200：
    #: 后者是三段路径，而路径参数只匹配一段，两者根本不可能相撞。
    #:
    #: 真正会被吃掉的是**同为两段**的路径。所以如果将来加
    #: `/bills/unpaid` 这种，它才必须排在这一条前面。
    @router.get("/bills/{bill_id}")
    def one_bill(bill_id: str, ctx: AuthContext = Depends(_actor)) -> AppBill:
        row = db.get_bill(bill_id)
        if row is None or row["family_id"] != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这张账单。")
        return _bill_view(row)

    # ---- 就医安排 -----------------------------------------------------------

    @router.get("/appointments")
    def list_appointments(ctx: AuthContext = Depends(_actor)) -> AppAppointmentList:
        """挂号/复诊。`appointments` 表和 `insert_appointment` 一直都在，
        **没有任何地方读它**——所以「就医安排」那一页此前只能拿提醒凑。
        """
        # 哪些「今天/以后仍然会响」的就医提醒还活着。用来回答下面每一条
        # 「到点还会不会提醒她」——取消范围是单向的，只取消提醒时这一条
        # 仍然写着「已预约」，那就是在暗示一件不成立的事。
        #
        # **每一条安排各自按时刻取窗口，不要翻最老的 200 条。**
        #
        # 原先是一次 `db.list_reminders(ctx.family_id, limit=200)`。那条 SQL 是
        # `ORDER BY due_at ASC LIMIT ?`，所以家里一旦攒下 200 条**更早**的提醒，
        # 就医那条提醒就不在这一页里，`live` 里没有它，这一行于是说
        # 「到点不会提醒」——而那条提醒真的还排着、到点真的会响。
        #
        # 实测剂量反应（同一段代码，只有历史行数不同）：
        #
        #     0 行 / 150 行 -> reminds=True    205 行 -> reminds=**False**
        #                                       而提醒行 status=scheduled
        #
        # 方向和 `cancel_appointment` 那一处相反：那边是**过度承诺**
        # （说撤了、其实没撤），这边是**承诺不足**。轻一些，但仍然是假话，
        # 而且它会引着家人再加一条重复的提醒。
        #
        # `database.py:1328` 的注释更早就为 `/agenda` 记过同一个坑，
        # `since`/`until` 也早就在那里了——同一个仓库、同一个坑，
        # 一处修好了别处照旧。注释写在别的函数上，不拦人。
        rows = list(db.list_appointments(ctx.family_id, _elder_of(ctx)))
        elder_id = _elder_of(ctx)
        live: set[str] = set()
        for row in rows:
            #: 时刻从这一行安排自己的 `date`/`time` 重算，用和建的时候
            #: **同一套**本地时区换算（`create_appointment` / `cancel_appointment`
            #: 都是这一套）。算不出来就跳过——那种安排本来就没带出提醒
            #: （`reminderId` 是 null），`reminds` 为 False 是实话。
            try:
                naive = datetime.fromisoformat(
                    f"{row['appointment_date']}T"
                    f"{row['appointment_time'] or '09:00'}:00")
                want = naive.replace(
                    tzinfo=local_now(datetime.now(UTC)).tzinfo).astimezone(UTC)
            except (ValueError, TypeError, KeyError):
                continue
            for r in db.list_reminders(
                    ctx.family_id, limit=50,
                    since=want - timedelta(minutes=1),
                    until=want + timedelta(minutes=1)):
                if (r.elder_id == elder_id
                        and str(r.source or "") == _APPOINTMENT_SOURCE
                        and r.status not in {ReminderStatus.CANCELLED,
                                             ReminderStatus.COMPLETED}):
                    live.add(local_now(
                        r.due_at if r.due_at.tzinfo
                        else r.due_at.replace(tzinfo=UTC)
                    ).strftime("%Y-%m-%d %H:%M"))
        items = []
        for row in rows:
            when = f"{row['appointment_date']} {str(row['appointment_time'] or '')[:5]}"
            items.append({
                "id": row["id"],
                "hospital": row["hospital"],
                "department": row["department"],
                "doctor": row["doctor"],
                "date": row["appointment_date"],
                "time": row["appointment_time"],
                # 已取消的安排本来就不该提醒；其余按「那条提醒还活着吗」回答。
                "reminds": (str(row["status"]) != "cancelled") and (when in live),
                # 界面上不出现英文枚举值。`insert_appointment` 写进去的是
                # `confirmed`（写死在那个方法里），别的三个是这张表的 CHECK 允许的值。
                "status": {"confirmed": "已预约", "booked": "已预约",
                           "cancelled": "已取消",
                           "completed": "已完成"}.get(str(row["status"]), "已预约"),
            })
        return {"items": items, "count": len(items)}

    @router.post("/appointments")
    def create_appointment(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppAppointmentCreated:
        """记一次就医安排，并**同时建一条到点提醒**。

        只写 `appointments` 表是不够的：那张表没有任何东西会到点提醒老人，
        而「记下来」和「到时候会叫我」在老人那里是同一件事。所以两张表一起写——
        提醒的标题带上医院和科室，于是它也会被 `_kind_of` 归进「就医」，
        「今日安排」里按就医筛得到。
        """
        body = body or {}
        hospital = str(body.get("hospital") or "").strip()
        date = str(body.get("date") or body.get("appointment_date") or "").strip()
        time_s = str(body.get("time") or body.get("appointment_time") or "").strip()
        if not hospital:
            raise HTTPException(status_code=400, detail="还没有说去哪家医院。")
        if not date:
            raise HTTPException(status_code=400, detail="还没有说哪一天。")

        now = datetime.now(UTC)
        appt_id = f"appt-{uuid.uuid4().hex[:12]}"
        department = str(body.get("department") or "").strip()
        ok = db.insert_appointment({
            "id": appt_id,
            "family_id": ctx.family_id,
            "elder_id": _elder_of(ctx),
            "hospital": hospital,
            "department": department,
            "doctor": str(body.get("doctor") or "").strip(),
            "appointment_date": date,
            "appointment_time": time_s or "09:00",
        })
        if not ok:
            raise HTTPException(status_code=409, detail="这一条没能存下来，请再试一次。")

        # 顺带建提醒。建不出来不该让整件事失败——安排已经记下了。
        reminder_id = None
        #: 时刻已经过去时，提醒建了也永远不会响。见下面那一段。
        already_past = False
        try:
            # 家属填的 09:30 是**墙上时间**，不是 UTC 的 09:30。
            #
            # 原先直接拼 `+00:00`。列表读回来看不出异样——它把家属填的
            # `date` / `time` 原样播回去——而**那条提醒的真实时刻偏了八小时**：
            #
            #     家属填         2026-08-26 09:30 本地
            #     due_at 存成    2026-08-26T09:30:00Z
            #     实际会响       2026-08-26 17:30 本地   ← 门诊早就结束了
            #
            # 老人会在看完门诊之后被提醒去看那个门诊。而这一页上每一处显示
            # 都是对的，因为它们读的是 `appointments` 表里那两个字符串，
            # 不是提醒的时刻。
            #
            # `_parse_when` 上面那段注释讲的正是这件事，它对 `HH:MM` 已经
            # 用 `local_now()` 处理过了；这里是同一个坑的另一个入口。
            naive = datetime.fromisoformat(f"{date}T{(time_s or '09:00')}:00")
            due = naive.replace(tzinfo=local_now(now).tzinfo).astimezone(UTC)
            title = f"去{hospital}{department}就诊" if department else f"去{hospital}就诊"
            #: 过去的时刻**照样建提醒**，但下面那句话不许承诺会提醒。
            #:
            #: 第一版是直接不建。全套跑出六条红（都在就医/提醒那一族），
            #: 因为「今天」和「接下来」是**从提醒表**读的：套件在下午跑，
            #: 上午那两场门诊于是从她的当天视图里整个消失了。
            #: 而这一格的设计明确要留住过点的事——见 `agenda` 那一段：
            #: 「都过点了就取最早那一件，并标出来它已经过点」。
            #:
            #: 两件事别混：**不许承诺一个到不了的提醒**（对），
            #: **不建这条日程**（过头了，等于把她今天该看见的东西删掉）。
            if due <= now:
                already_past = True
            record = ReminderRecord(
                id=f"rem-{uuid.uuid4().hex[:12]}",
                family_id=ctx.family_id,
                elder_id=_elder_of(ctx),
                title=title,
                due_at=due,
                escalation_after_minutes=60,
                status=ReminderStatus.SCHEDULED,
                # 这个标记是「今日安排」那一格能说出医院名字的唯一依据，
                # 见 `_APPOINTMENT_SOURCE` 上面那段。
                source=_APPOINTMENT_SOURCE,
                created_by=ctx.actor_id,
                created_at=now,
            )
            if db.insert_reminder(record):
                reminder_id = record.id
        except (ValueError, TypeError):
            reminder_id = None

        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_APPOINTMENT_CREATED,
            entity_id=appt_id,
            #: `elder_id` 同上：实体号是 `appt-…`，家人替她约的那一次
            #: 她自己的记录页上原先一行都没有。
            payload={"hospital": hospital, "date": date,
                     "time": time_s or "09:00", "elder_id": _elder_of(ctx)},
        )
        return {
            "ok": True,
            "id": appt_id,
            "reminderId": reminder_id,
            #: 承诺只在**真的会响**的时候说。
            #: 时刻已经过去 -> 提醒建了也不会响，那就照实说；
            #: 提醒没建出来 -> 什么都不承诺。
            "message": f"记好了，{date} {time_s or '09:00'} 去{hospital}。"
                       + ("这个时间已经过去了，就不另外提醒了。" if already_past
                          else _voice(ctx, "到点我会提醒您。",
                                      "到点我会提醒老人。") if reminder_id
                          else ""),
        }

    # ---- 通知 ---------------------------------------------------------------

    @router.post("/notifications/{notification_id}/read")
    def read_notification(notification_id: str, ctx: AuthContext = Depends(_actor)) -> AppNotificationRead:
        """标成已读。没有这一步，通知只会越堆越多，红点永远下不去。

        **只标得动发给自己的那些**——`recipient_role` 见
        `Database.mark_notification_read` 的说明。
        """
        if not db.mark_notification_read(
            notification_id, ctx.family_id, datetime.now(UTC), recipient_role=ctx.role
        ):
            raise HTTPException(status_code=404, detail="没有找到这条通知，或者它已经读过了。")
        return {"ok": True, "id": notification_id, "status": "已读"}

    # ---- 语音会话 -----------------------------------------------------------

    @router.post("/voice/sessions")
    def open_voice_session(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppVoiceSession:
        """开一个真实会话；带了 `utterance` 就真的过一遍语义引擎。"""
        now = datetime.now(UTC)
        # 字段名是 `session_id` 不是 `id`；`StrictModel` 是 extra="forbid"，
        # 传错一个键就直接 500，不会静默忽略。
        session = SessionState(
            session_id=f"sess-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_elder_of(ctx),
            created_at=now,
            updated_at=now,
        )
        db.create_session(session)

        understood = None
        utterance = (body or {}).get("utterance")
        if utterance:
            reply = engine.handle(
                ctx, ChatRequest(session_id=session.session_id, text=str(utterance))
            )
            # `ChatResponse` 的字段是 `message` / `code` / `task_status`，没有 `reply`。
            understood = {
                "reply": reply.message,
                "code": str(reply.code),
                "taskId": reply.task_id,
                "taskStatus": str(reply.task_status) if reply.task_status else None,
                "taskType": (reply.data or {}).get("task_type"),
            }
        return {"id": session.session_id, "status": "listening", "understood": understood}

    # ---- 支付：准备 / 复述 / 执行 --------------------------------------------

    @router.post("/payments/prepare")
    def prepare_payment(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppPaymentPrepared:
        """建一件**真的**缴费事务，并把复述提示词一并给前端。

        风险取 HIGH：`TeachBackVerifier.requires_teach_back` 只在 `BILL_PAYMENT`
        且 risk >= 3 时要求复述——这正是这一版演示要展示的那条线。
        """
        # 要付哪一张。
        #
        # 指名了就按 id 取；没指名就取**当前这张水费**——那是这个产品的主路径。
        #
        # 两处历史：原先这里无视 body，永远建一笔水费（而库里有三张账单，
        # 「我的账单」上点电费办出来的却是水费）；而不指名时用的是源码里那个
        # 硬编码字典 `_WATER_BILL`，它的 id 是编的 `water-current`，
        # 和 `/bills` 报的真 id 对不上。现在两条路都落到同一张真表上。
        wanted = str((body or {}).get("billId") or "").strip()
        if wanted and wanted != _WATER_BILL["id"]:
            row = db.get_bill(wanted)
            if row is None or row["family_id"] != ctx.family_id:
                raise HTTPException(status_code=404, detail="没有找到这张账单。")
        else:
            row = _current_water_row(ctx)
            if row is None:
                raise HTTPException(status_code=404, detail="现在没有水费账单。")
        if row["paid"]:
            raise HTTPException(status_code=409, detail="这一张已经交过了。")

        # 这张账单已经有一笔在办了，就把那一笔给他，别再建一笔。
        #
        # 实测：连点两下「继续办理」，拿到两个不同的事务号——同一张账单两笔在飞。
        # 老人接着在其中一笔上复述、另一笔永远悬着，而「我的账单」上那张仍然未缴。
        # 这一层原先完全没有幂等保护，而重复点击是老人端最常见的操作。
        for existing in db.list_tasks(ctx.family_id, limit=60):
            if (
                existing.task_type is TaskType.BILL_PAYMENT
                and existing.status not in _TASK_DONE
                and existing.slots.get("bill_id") == row["id"]
            ):
                return {
                    "id": existing.id,
                    "status": "awaiting_teach_back",
                    "amount": _yuan(int(existing.slots.get("amount_cents") or 0)),
                    "prompt": TeachBackVerifier.build_prompt(
                        TaskType.BILL_PAYMENT, existing.slots
                    ),
                }

        period = str(row["period"] or "")
        b = {
            "id": row["id"],
            "type": row["bill_type"],
            "amount_cents": int(row["amount_cents"] or 0),
            "company": _BILL_COMPANY.get(row["bill_type"]) or "",
            "account_tail": str(row["id"])[-4:],
            "month": (period.split("-", 1)[1].lstrip("0") + "月") if "-" in period else period,
        }

        # 槽位**从真实账单查询里来**，不在这里手工拼一份。
        #
        # 原来这里是手写的 5 个键，没有 `bill_id`。后果只在跨端时才显形：
        # 这一笔在旧家人端 `/v2/tasks` 里看得见（同一张任务表），女儿点「同意」，
        # 审批通过、状态推到 `executing`，**然后 `billing.settle` 抛 KeyError('bill_id')
        # 挂在半路**——一笔卡在「执行中」的钱，两端都显示不出它到底怎么了。
        #
        # `engine.py:725` 的写法就是 `task.slots.update(lookup.data)`。照它来，
        # 这一层才真的是门面而不是第二套业务——那正是这个文件开头写的话。
        # 查不到就退回本地那份演示账单：宁可少一个字段，也不要在这里编一个 bill_id
        # 让 `settle` 拿着去结一笔不存在的账。
        slots: dict[str, Any] = {
            "bill_type": b["type"].replace("支付", ""),
            "amount_cents": b["amount_cents"],
            "company": b["company"],
            "account_tail": b["account_tail"],
            "month": b["month"],
        }
        lookup = None
        try:
            lookup = engine.services.billing.lookup(db, ctx.family_id, slots["bill_type"])
        except Exception:  # noqa: BLE001 —— 查询挂了不该让老人点不动按钮
            lookup = None
        if lookup is not None and getattr(lookup, "ok", False) and lookup.data:
            slots.update(lookup.data)

        now = datetime.now(UTC)
        task = TaskRecord(
            id=f"pay-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_elder_of(ctx),
            task_type=TaskType.BILL_PAYMENT,
            status=TaskStatus.AWAITING_ELDER_CONFIRMATION,
            risk_level=RiskLevel.HIGH,
            slots=slots,
            # 语义键跟着真实 bill_id 走，这样查重才和主引擎认的是同一件事。
            semantic_key=f"bill:{slots.get('bill_id') or b['id']}:{slots['amount_cents']}",
            created_at=now,
            updated_at=now,
        )
        db.create_task(task)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_PREPARED,
            entity_id=task.id,
            payload={"amount_cents": b["amount_cents"], "company": b["company"]},
        )
        return {
            "id": task.id,
            "status": "awaiting_teach_back",
            "amount": _yuan(b["amount_cents"]),
            "prompt": TeachBackVerifier.build_prompt(TaskType.BILL_PAYMENT, slots),
        }

    @router.post("/payments/{payment_id}/teach-back")
    def teach_back(payment_id: str, body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppTeachBackResult:
        """真的核对老人念出来的金额。念错就停——这一条是整个产品的支点。

        支点就得由**她本人**踩。此前这里没有 `_only_the_elder`：女儿拿自己的
        令牌就能把金额念一遍拿到 `verified`，再 `execute`、再自己 `family-approve`，
        一个人走完三道门把钱付掉。引擎那一侧本来是关着的
        （`POST /v2/sessions` 对家属 403），只有这个门面漏了——
        和 `_only_the_elder` 文档里记的那三处是同一个形状：**照抄了调用，
        没有照抄守卫**。当时补了记忆两处、用药一处，漏了这一处。

        而复述通过会把 `elder_confirmed` 落进槽位（见下面），
        所以家属念一遍，等于替她按下了同意。
        """
        _only_the_elder(ctx, "念一遍金额确认这笔缴费")
        task = _task_or_404(ctx, payment_id)
        text = str((body or {}).get("text") or "")
        check = TeachBackVerifier.verify(task.task_type, task.slots, text, required=True)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_TEACH_BACK,
            entity_id=task.id,
            payload={
                "outcome": str(check.outcome),
                "expected": check.expected_display,
                "heard": check.heard_display,
            },
        )
        if check.outcome is TeachBackOutcome.VERIFIED:
            # 复述核对通过，在语义上**就是**老人的确认——所以在这里就把
            # `elder_confirmed` 落进槽位，和 `engine.py:882` 那两行一致。
            #
            # 不落的后果只在跨端时显形：这一笔在旧家人端看得见、女儿点得动，
            # 审批还会返回 200——然后 `TaskVerifier.verify` 查
            # `slots["elder_confirmed"]` 查不到，判「缺少老人确认」，把任务打成
            # `failed`。老人**明明念对了**，链上也有 verified 那一条，
            # 却因为门面少写一个槽位，被判成没确认过。
            done = task.model_copy(update={"slots": {
                **task.slots,
                "elder_confirmed": True,
                "elder_confirmation_hash": semantic_hash(["elder-confirmation", text]),
            }})
            db.update_task(done)
            task = db.get_task(task.id) or done
        words = {
            TeachBackOutcome.VERIFIED: "念对了，可以继续。",
            TeachBackOutcome.MISMATCH: "听到的金额和账单上的不一样，先停下。",
            TeachBackOutcome.NOT_RESTATED: "没有听到您把金额念出来，请再说一遍。",
            TeachBackOutcome.NOT_REQUIRED: "这一件不需要复述。",
        }
        return {
            "ok": check.passed,
            "matched": check.passed,
            "outcome": str(check.outcome),
            "expected": check.expected_display,
            "heard": check.heard_display,
            "message": words.get(check.outcome, ""),
        }

    @router.post("/payments/{payment_id}/execute")
    def execute_payment(payment_id: str, body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppPaymentMoved:
        """推进这件事。

        **不会因为前端调了就直接扣钱。** 高风险缴费要家人点头，所以这里把状态推到
        「等家人确认」并写审计。前端拿到 `awaiting_family` 就该照实显示。
        """
        task = _task_or_404(ctx, payment_id)
        if task.status is TaskStatus.COMPLETED:
            return {"ok": True, "status": "paid", "certificateId": task.id}
        # 已经在等家人了，再点一次不做任何事。
        #
        # 不加这一条的后果实测过：连点两下，链上出现**两条**
        # `app.payment.awaiting_family`。审计链是这个产品的全部价值，
        # 而它把发生过一次的事记成了两次——看链的人会以为老人确认了两遍。
        # 老人手抖、以为没反应、网络慢了再按一次，是这一端最常见的操作，
        # 不是边角情况。
        if task.status is TaskStatus.AWAITING_FAMILY_APPROVAL:
            return {
                "ok": True,
                "status": "awaiting_family",
                "certificateId": task.id,
                "message": "已经提交过了，正在等家里第二个人点头。",
            }

        # 复述必须先过：查这一件事的审计链里有没有一条 verified。
        events = db.list_audit(ctx.family_id, limit=200, entity_id=task.id)
        verified = any(
            e.event_type == _EV_TEACH_BACK
            and (e.payload or {}).get("outcome") == str(TeachBackOutcome.VERIFIED)
            for e in events
        )
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="还没有通过复述确认，不能继续。",
            )

        moved = task.model_copy(
            update={
                "status": TaskStatus.AWAITING_FAMILY_APPROVAL,
                "approval_digest": None,
                "updated_at": datetime.now(UTC),
            }
        )
        db.update_task(moved)

        # 审批摘要。**这一段照 `engine.py:893-899` 的两步来，顺序不能换。**
        #
        # 实测发现的缺口：这一笔在旧家人端 `/v2/tasks` 里**看得见**（同一张任务表、
        # 同一个 `bill_payment`），但 `approval_digest` 是 null，而
        # `/v2/family/approve` 要求它是字符串——于是女儿在 `/family` 上点「同意」
        # 收到 422。两块屏幕看的是同一笔事务，却只有一块能推动它。
        #
        # 为什么必须先写、再读回来、再算：摘要要盖在**持久化之后**的任务上
        # （版本号已经 +1）。在内存里的副本上算，`engine.py:1046` 那次重算会对不上，
        # 审批当场被判成「摘要不符」——那是一条防篡改判据，不该被自己人绊倒。
        # 第二次写 `bump_version=False`，否则版本又变了，摘要再次失效。
        stored = db.get_task(task.id) or moved
        stored.approval_digest = SafetyPolicy.approval_digest(stored)
        db.update_task(stored, bump_version=False)

        # **喊人。** 上面那段注释说「照 `engine.py` 的两步来」——它只抄了那两步。
        # 引擎在挂起时做的是四件事（`engine.py:914-935`）：改状态、算摘要、
        # **发通知**、写审计。门面抄了第一二四件，把第三件漏了。
        #
        # 实测两条路对照（同一份种子、同一张水费）：
        #   门面 /api/v1 -> awaiting_family_approval，家人收件箱 1 -> 1（涨 0 条）
        #   引擎 /v2/chat -> awaiting_family_approval，家人收件箱 1 -> 2
        # 老人在山水版上交的钱就停在那儿，家人永远不知道有人在等他。
        #
        # 走 `NotificationService.send` 而不是 `db.add_notification`：前者
        # 还会写一条带 notification_id 的 `NOTIFICATION_CREATED` 审计
        # （`services.py:352`）。只落通知行会重犯同一个毛病——抄一部分。
        #
        # 正文取 `engine._summary(task)`：两块家人屏幕上这句话必须一字不差，
        # 在这里另拼一份措辞，迟早和引擎那份分叉。
        engine.services.notification.send(
            db,
            family_id=ctx.family_id,
            recipient_role=ActorRole.FAMILY,
            event_type="approval_required",
            entity_id=task.id,
            message=f"老人请求办理：{engine._summary(stored)}。请您核对之后确认。",
        )
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_AWAITING_FAMILY,
            entity_id=task.id,
            payload={"amount_cents": task.slots.get("amount_cents"),
                     "approval_digest": stored.approval_digest},
        )
        return {
            "ok": True,
            "status": "awaiting_family",
            "certificateId": task.id,
            "message": "已提交，等家里第二个人点头之后才会真的付。",
        }

    @router.post("/payments/{payment_id}/family-approve")
    def family_approve(payment_id: str, body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppPaymentMoved:
        """家人点头，这一笔才真的走完。

        没有这一步，链条就停在 `awaiting_family` 永远不动——凭证页会一直显示
        「等家人点头」，而演示里没有任何办法把它推完。那不是"安全"，那是断掉。

        **这是家人的动作，不是老人的。** 所以身份取家人，写进审计的也是家人的
        `actor_id`——凭证上「谁点的头」必须是真的。老人自己点不动这一步。
        """
        task = _task_or_404(ctx, payment_id)
        if task.status is TaskStatus.COMPLETED:
            return {"ok": True, "status": "paid", "certificateId": task.id}
        if task.status is not TaskStatus.AWAITING_FAMILY_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="这一笔还没有走到等家人确认这一步。",
            )

        approver = _approver_of(ctx)

        # **真的去把那张账单结掉。**
        #
        # 原先这里只把任务状态改成 COMPLETED 就返回了——凭证会说「交易成功」、
        # 链上也有家人那一条，而 `bills` 表里 `paid` 还是 0。后果有两个，
        # 都在演示里会被看到：「我的账单」上这一张仍然写着「待缴纳」；
        # 而且**可以再付一次**，因为没有任何东西记得它付过了。
        #
        # 旧家人端那条路（`/v2/family/approve`）一直是调 `billing.settle` 的，
        # 所以这个缺口只存在于这一层门面——两块屏幕办同一件事，
        # 一块把账结了，一块没有。
        bill_id = task.slots.get("bill_id")
        settle_note = None
        if bill_id:
            try:
                result = engine.services.billing.settle(db, ctx.family_id, str(bill_id))
                if not result.ok:
                    # 结不掉不该把这一笔判成失败——钱这一侧的状态机已经走完了。
                    # 但要留痕，否则「账单还欠着」会变成一个查不出来的现象。
                    settle_note = result.code
            except Exception as exc:      # noqa: BLE001
                settle_note = f"settle_failed:{type(exc).__name__}"

        done = task.model_copy(
            update={"status": TaskStatus.COMPLETED, "updated_at": datetime.now(UTC)}
        )
        db.update_task(done)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=approver.actor_id,          # 家人，不是老人
            event_type=_EV_FAMILY_APPROVED,
            entity_id=task.id,
            payload={
                "amount_cents": task.slots.get("amount_cents"),
                "approved_by": approver.display_name,
                "bill_id": bill_id,
                # 结账没成功的话，把原因留在链上。不写的话，「账单还欠着」
                # 会变成一个从任何地方都查不出来的现象。
                **({"settle_note": settle_note} if settle_note else {}),
            },
        )
        return {
            "ok": True,
            "status": "paid",
            "certificateId": task.id,
            "approvedBy": approver.display_name,
            "message": f"{approver.display_name}已确认，这一笔办好了。",
        }

    # ---- 记录 ---------------------------------------------------------------

    #: 事件类型 → 给人看的说法。
    #:
    #: 界面上不许出现 `app.payment.teach_back` 这种内部枚举——这一条是这个项目的
    #: 硬约束，而记录页是最容易漏的地方（它直接把流水铺开给老人看）。
    #: 认不出来的事件一律说「办了一件事」，不把原始字符串漏到屏幕上。
    #: 这张表是**查库查出来的**，不是读代码猜的。
    #:
    #: 我在这里连错两版：先写 `task.created` 这种点号命名，再改成 `task_completed`
    #: 这种小写下划线（那是从源码里 grep 到的字面量）。而库里真正存的是
    #: **全大写下划线** `TASK_CREATED` / `TEACH_BACK_VERIFIED`。
    #: 两版都「看起来正常」——记录页照样渲染，每一条都落到兜底的「办了一件事」，
    #: 八条里零条翻译对，而屏幕上完全看不出哪里不对。
    #: 最后是 `SELECT event_type, COUNT(*) FROM audit_events GROUP BY 1` 定的案。
    _WORDS: dict[str, tuple[str, str, str]] = {
        # 主引擎写的（大写，来自库里的实际取值）
        "TASK_CREATED": ("开始办一件事", "服务", "record_request"),
        "ELDER_CONFIRMED": ("您确认了", "支付", "record_confirm"),
        "TEACH_BACK_VERIFIED": ("复述核对通过", "支付", "record_confirm"),
        "FAMILY_APPROVAL_RECORDED": ("家人已点头", "支付", "record_family"),
        "FAMILY_APPROVED_AND_EXECUTED": ("家人同意后已办好", "支付", "record_water"),
        "NOTIFICATION_CREATED": ("发出一条通知", "服务", "record_request"),
        "DEMO_SEEDED": ("铺好了这个家庭的起始数据", "服务", "record_request"),
        # 这里曾经有四条**永远命中不了**的：
        #
        #     TASK_REJECTED  APPROVAL_REQUIRED  REMINDER_DUE  REMINDER_ESCALATED
        #
        # 它们是把**通知**的事件名按**审计**的写法写进了审计词表。
        # 两套命名空间的约定不一样：审计事件是大写下划线（`append_audit` 写的），
        # 通知事件是小写下划线（`add_notification` 写的，如 `approval_required`、
        # `reminder_due`、`reminder_escalated`）。于是这四条在两边都对不上。
        #
        # 逐个核过全包（不只看字面量，`append_audit` 有四处是动态拼名字的）：
        # 这四个在 `backend/youhuo` 里除了这张表本身之外一次都没出现。
        #
        # 删掉而不是留着：一份带着永不命中项的清单，会让下一个人以为
        # 「这类事件已经有词了」。而真正危险的方向是反过来——发了却没词，
        # 那一行会退成兜底「办了一件事」，屏幕上完全正常、没有任何东西报红。
        # 那个方向现在由 `test_every_audit_event_has_a_word.py` 钉住。
        #
        # 注意 `MEDICATION_PLAN_PROPOSED` 和 `MEMORY_REJECTED` **没有**一起删：
        # 它们看起来也像死键，实测是活的——前者由 `v4_api.py` 的三元表达式选出、
        # 后者由 `api.py` 的三元表达式选出。删掉会让那两行退成兜底。
        # 本门面自己写的（小写点号，与上面刻意不同名，便于区分来源）
        "app.payment.prepared": ("发起申请", "支付", "record_request"),
        "app.payment.teach_back": ("复述确认", "支付", "record_confirm"),
        "app.payment.awaiting_family": ("等家人确认", "支付", "record_family"),
        "app.emergency.requested": ("紧急呼叫", "服务", "record_family"),
        "app.reminder.created": ("加了一条提醒", "健康", "record_confirm"),
        "app.reminder.completed": ("办好了一件事", "健康", "record_confirm"),
        "app.reminder.cancelled": ("取消了一条提醒", "健康", "record_confirm"),
        "app.settings.changed": ("改了设置", "服务", "record_request"),
        "app.appointment.created": ("记下一次就医安排", "健康", "record_confirm"),
        "app.emergency.notify_failed": ("紧急呼叫没能通知到家人", "服务", "record_family"),
        "app.contact.phone_set": ("登记了紧急联系电话", "服务", "record_family"),
        "app.health.recorded": ("记了一次身体数据", "健康", "record_confirm"),
        "app.reminder.moved": ("改了提醒的时间", "健康", "record_confirm"),
        "app.appointment.cancelled": ("取消了一次就医安排", "健康", "record_confirm"),
        "app.medication.decided": ("确认了一份用药计划", "健康", "record_confirm"),
        "app.memory.decided": ("决定了一条要不要记", "服务", "record_confirm"),
        "app.memory.forgotten": ("让优活忘掉一条", "服务", "record_request"),
        #: 下面三条**去掉了写死的主语**。这一屏（`AppRecord`）没有
        #: `who` 字段，所以约定是不带主语；写死一个主语就是在断言
        #: 它并不知道的事。实测（elder 令牌提议一条记忆）：
        #:
        #:     审计     MEMORY_PROPOSED actor=elder-demo   <- 她自己提的
        #:     记录页   「家人想让优活记一件事」
        #:     活动页   who=您「想让优活记住一件事，等您点头。」  <- 对的
        #:
        #: `privacy._WHO_FROM_ACTOR` 认得这 33 个事件的动作人会变，
        #: 这张表里其中 3 条把「家人」写死在标题里。两张表，
        #: 一张知道、一张写死。
        "MEMORY_PROPOSED": ("想让优活记一件事，等您点头", "服务", "record_family"),
        "MEMORY_APPROVED": ("同意记住一件事", "服务", "record_confirm"),
        "MEMORY_REJECTED": ("没有同意记那一件", "服务", "record_confirm"),
        "MEMORY_REVOKED": ("让优活忘掉一条", "服务", "record_request"),
        # 服药记录由 `v4_store.record_dose` 自己写（大写下划线那一批）。
        # 这一层不重复写一条：同一件事在记录页出现两行，看起来像吃了两次。
        "MEDICATION_DOSE_RECORDED": ("记了一次服药", "健康", "record_confirm"),
        "MEDICATION_PLAN_DECIDED": ("确认了一份用药计划", "健康", "record_confirm"),
        "MEDICATION_PLAN_PROPOSED": ("加了一份用药计划，等您点头", "健康", "record_family"),
        # 登录本身对老人没意义，但它**已经在**审计链里，而记录页读的就是审计链。
        # 不给它名字，它就以「办了一件事」出现在时间线上——看起来像个缺陷。
        # 不删（这一层不该决定审计链里少一条），给它一句能读懂的话。
        "DEMO_LOGIN": ("登录了优活", "服务", "record_request"),
        "app.routine.created": ("加了一件固定安排", "健康", "record_confirm"),
        "app.routine.paused": ("暂停了一件固定安排", "健康", "record_confirm"),
        "app.routine.resumed": ("恢复了一件固定安排", "健康", "record_confirm"),
        # 例程排期由 `v4_store.materialize_routines` 那一侧写。
        "ROUTINES_MATERIALIZED": ("排好了接下来的固定安排", "健康", "record_confirm"),
        "ROUTINE_OCCURRENCE_COMPLETED": ("完成了一件固定安排", "健康", "record_confirm"),
        # 删除个人数据。这一条**必须**在记录页上留名：它是不可逆的，而落到兜底的
        # 「办了一件事」会让整条时间线上最重的一步看起来和别的一样轻。
        "app.privacy.erased": ("删掉了一批个人数据", "服务", "record_request"),
        # ------------------------------------------------------------------
        # 下面这一批是补上来的。补的理由是量出来的，不是补全癖：
        #
        # 她问了十一句最普通的话（「我今天的药吃了吗」「今天有什么安排」
        # 「我女儿的电话是多少」），这一屏 18 行里 **9 行写着「办了一件事」**，
        # 前端只渲染 4 行、时间线只用最前 3 行——于是那 3 行全是空话，
        # 而「再说一遍」念给她听的正是 `items[0].title`，也就是「办了一件事。」
        #
        # 漏得这么整齐是因为 `engine.py:393` 那一处的事件名是**动态传入**的
        # （`answer.audit_event`），`care_voice.py` 里那 12 个 `CARE_*` 一个都不在
        # 源码里以字面量出现在这张表旁边。上面那句「这张表是查库查出来的」
        # 只查到了当时那一版跑出来的那些码。
        #
        # `records()` 读的是 `db.list_audit(family_id)`——**整个家庭的全部审计，
        # 没有白名单**。所以家属侧、v4/v5/v6 写的事件同样会出现在她眼前。
        # 全量清单是 AST 数 `append_audit` 第三个实参数出来的（94 个字面量
        # + 6 处动态调用点逐个解开），凡是「改变了什么」的都在这里给了词，
        # 凡是「只是读了一下 / 内部路由」的都在 `_MACHINERY` 里列名。
        # ------------------------------------------------------------------
        # 主引擎：一件事的一生
        "TASK_EXECUTED": ("这件事办妥了", "服务", "record_confirm"),
        "TASK_FAILED": ("没能办成，已安全停下", "服务", "record_request"),
        "TASK_CANCELLED": ("这件事停下了", "服务", "record_request"),
        "TASK_SLOT_CORRECTED": ("更正了其中一项信息", "服务", "record_confirm"),
        "TEACH_BACK_REJECTED": ("复述没对上，停在原地", "支付", "record_request"),
        "FAMILY_REJECTED": ("家人没有同意", "支付", "record_family"),
        "FAMILY_APPROVED_EXECUTION_FAILED": ("家人同意了，但这件事没办成", "支付", "record_family"),
        "FAMILY_REMINDER_CREATED": ("家人替您加了一条提醒", "健康", "record_family"),
        # 语音改提醒状态那一路：事件名是 `f"REMINDER_{action.upper()}"`
        # （`engine.py:1279`），`action` 只有 `acknowledge` / `complete` 两个取值，
        # 逐个核过——所以这里是两条，不是猜一个前缀。
        "REMINDER_ACKNOWLEDGE": ("您说知道了", "健康", "record_confirm"),
        "REMINDER_COMPLETE": ("办好了一件事", "健康", "record_confirm"),
        "REMINDER_CANCELLED": ("取消了一条提醒", "健康", "record_confirm"),
        # 安全与情绪
        "SAFETY_SIGNAL": ("优活觉得这件事要当心", "服务", "record_request"),
        # 09-22 新增的「说身体不舒服 -> 通知家人」。原先没有说法，她那一屏会写「办了一件事」。
        "UNWELL_SIGNAL": ("您说身体不舒服，已经告诉家里人", "服务", "record_request"),
        "SUSPICIOUS_INSTRUCTION_BLOCKED": ("挡下了一句可疑的话", "服务", "record_request"),
        "SOS_TRIGGERED": ("按了紧急求助", "服务", "record_family"),
        "EMOTIONAL_TASK_PAUSE": ("先陪您说话，原来那件事先放着", "服务", "record_request"),
        "EMOTIONAL_TASK_RESUMED": ("回来接着办原来那件事", "服务", "record_confirm"),
        # 这一条**存下了关于她的东西**（`emotion_events` 里那一行，她可以删）。
        # 所以它必须在她自己的记录上留名——看不到就等于不知道被记了。
        "EMOTION_SIGNAL_RECORDED": ("记下了您的心情", "服务", "record_confirm"),
        "EMOTION_SIGNAL_RECORD_FAILED": ("心情没能记下来", "服务", "record_request"),
        # `care_voice.py` 那一批里，只有这三条**改变了或存下了什么**。
        # 另外九条纯问答在 `_MACHINERY` 里，理由写在那边。
        "CARE_SYMPTOM_ACKNOWLEDGED": ("说了身体不舒服", "健康", "record_confirm"),
        "CARE_PROFILE_SPEECH_RATE": ("改了说话的快慢", "服务", "record_confirm"),
        "CARE_PROFILE_HEARING_SUPPORT": ("改了听得清一点的设置", "服务", "record_confirm"),
        # v4：身体、用药、单据、联系人、设备
        "HEALTH_EVENT_CREATED": ("记了一次身体数据", "健康", "record_confirm"),
        "MEDICAL_DOCUMENT_ANALYZED": ("整理了一份就医单据", "健康", "record_confirm"),
        # 「谁看过我的就医单据」正是她该看得到的一行，所以它有词而不是机务。
        "MEDICAL_DOCUMENT_READ": ("有人看了您的就医单据", "健康", "record_family"),
        # 同一条道理，同一个形状：有人调阅了她某件事的说明。
        # 原先它在 `_MACHINERY` 里，理由写的是「只是打开看了看，没动任何东西」
        # ——而那正是上面这一行当年被否掉的那个理由。
        "TASK_EXPLANATION_VIEWED": ("有人调阅了这件事的说明", "服务", "record_family"),
        "MEDICATION_PLAN_ACTIVATED": ("一份用药计划开始生效", "健康", "record_confirm"),
        "ROUTINE_CREATED": ("加了一件固定安排", "健康", "record_confirm"),
        "ITEM_MEMORY_DECIDED": ("决定了一件东西记不记", "服务", "record_confirm"),
        "ITEM_MEMORY_ACTIVATED": ("记住了一件东西放在哪儿", "服务", "record_confirm"),
        "ITEM_MEMORY_PROPOSED": ("想让优活记一件东西，等您点头", "服务", "record_family"),
        "CONTACT_PROFILE_CREATED": ("加了一位联系人", "服务", "record_family"),
        "CONTACT_PROFILE_DECIDED": ("确认了一位联系人", "服务", "record_family"),
        "FACE_DEMO_TEMPLATE_ENROLLED": ("录了一次人脸样本", "服务", "record_confirm"),
        "DEVICE_REGISTERED": ("接上了一台设备", "服务", "record_confirm"),
        "SAFETY_POLICY_UPDATED": ("改了安全设置", "服务", "record_confirm"),
        #: 请求和决定是两件事，两条都要有话。措辞里**不出现「您」**，
        #: 这样家人端那一格可以逐字用同一句，不必再开一条他称说法。
        #: 走出常去的范围、并且**真的**提醒了家人。措辞不带「您」，
        #: 家人端那一格就能逐字用同一句。
        "GEOFENCE_ALERT_RAISED": ("离开了常去的范围，已经提醒家人", "服务", "record_family"),
        "ASSISTANCE_REQUESTED": ("家人请求了一次远程协助", "服务", "record_family"),
        "ASSISTANCE_DECIDED": ("决定了一次远程协助", "服务", "record_family"),
        "DOCUMENT_ANALYZED": ("看懂了一份材料", "服务", "record_confirm"),
        # v5：破窗查看、隐私、对账
        #
        # 破窗三条一条都不能少。**有人在紧急情况下看了她的资料**，
        # 这是她最该在自己的记录上看到的一类事；落成「办了一件事」
        # 等于把它藏进噪音里。
        "BREAK_GLASS_OPENED": ("开启了紧急查看权限", "服务", "record_family"),
        "BREAK_GLASS_VIEWED": ("有人用紧急权限看了您的资料", "服务", "record_family"),
        "BREAK_GLASS_CLOSED": ("关闭了紧急查看权限", "服务", "record_family"),
        "PRIVACY_ERASE_EXECUTED": ("删掉了一批个人数据", "服务", "record_request"),
        "PRIVACY_EXPORT_CREATED": ("导出了一份个人数据", "服务", "record_request"),
        "OFFLINE_SYNC_CONFLICT_RESOLVED": ("两处记录不一样，已经对齐", "服务", "record_confirm"),
        "TASK_PROOF_GENERATED": ("生成了一份完成证明", "服务", "record_confirm"),
        "VOICE_CONSENSUS_RESOLVED": ("有句话没听准，重新对了一遍", "服务", "record_confirm"),
        # v6：托付与说话方式
        "RELIANCE_CARD_CREATED": ("出了一张托付说明卡", "服务", "record_confirm"),
        "INTERACTION_PROFILE_UPDATED": ("改了跟您说话的方式", "服务", "record_confirm"),
    }

    #: 不上老人这一屏的内部事件。**列名，不是悄悄丢掉。**
    #:
    #: 这一屏叫「办事记录」，空态写「还没有办过事」。而下面这些不是「事」：
    #: 有的是纯问答（她问「今天几号」，答完什么都没变），有的是内部路由、
    #: 定时器、判据仪表。它们照旧完整写进审计链，家属与评委那一侧
    #: （`/v2/audit`，带完整 payload）一条不少；只是不占她那 4 个槽位。
    #:
    #: 为什么要有这张表，而不是「没有词就落兜底」：兜底那句「办了一件事」
    #: 会**顶掉**她真办过的事。实测她问十一句家常，时间线那 3 行全是空话，
    #: 「再说一遍」念的也是它。所以每个新事件类型必须在这里二选一：
    #: **要么给一句人话，要么在这张表里写明为什么不给。**
    #: 两张表都不在，`test_every_audit_event_has_a_word.py` 会报红。
    #:
    #: 跳过的条数会作为 `machinery` 返回并显示在她那一屏上
    #: （「另有 N 条系统记录」）——不做成看不见的差额。
    #: 同意和不同意，在她的记录页上不能是同一句话。
    #:
    #: `_WORDS` 是「事件类型 → 一句人话」的静态表，可**这个事件的意思在
    #: payload 里**：`{"approved": true|false}`。表里只写了一句
    #: 「确认了一份用药计划」，于是她按下「先不吃」之后，她自己的记录页上
    #: 出现的还是「确认了一份用药计划」——一条说她同意了她其实回绝了的药。
    #:
    #: 实测（同一次会话里，一份同意、一份拒绝）：
    #:
    #:     decline 拒绝药Y -> 200 {"message": "好，拒绝药Y先不吃，我把它取消了。"}
    #:     她的记录页       -> "确认了一份用药计划"   <- 就是被拒的那一份
    #:     审计链           -> app.medication.decided {"approved": false, "name": "拒绝药Y"}
    #:
    #: 判断依据一直躺在 payload 里，是渲染这一步把它丢了。
    #:
    #: 「没有同意」这个说法照 `MEMORY_REJECTED`（「没有同意记那一件」）来，
    #: 不另起一套口气。
    _DECISION_WORDS: dict[str, dict[bool, str]] = {
        "app.medication.decided": {
            True: "确认了一份用药计划",
            False: "没有同意那份用药计划",
        },
        "MEDICATION_PLAN_DECIDED": {
            True: "确认了一份用药计划",
            False: "没有同意那份用药计划",
        },
        #: 记忆的同意/回绝。原先两种结果都印「决定了一条要不要记」——
        #: 同一批表、同一个形状，只是另一个成员。实测：
        #:
        #:     {"approved": true,  "key": "不想被打扰的日子"} -> 「决定了一条要不要记」
        #:     {"approved": false, "key": "爱喝的茶"}         -> 「决定了一条要不要记」
        #:
        #: 而端点自己的回话是分得清的（「好，我记住…了」/「好，…我不记。」），
        #: 信息在决定那一刻有，到记录页丢了。
        "app.memory.decided": {
            True: "同意记下这一条",
            False: "没有同意记下这一条",
        },
    }

    #: 记录行的**宾语**：payload 里「是哪一件」的那几个键，按显示顺序。
    #:
    #: 这几类事件的 `note` 原先一律是空串，于是她的记录页上只剩动词。实测
    #: （做一串事之后逐行对照审计链）：
    #:
    #:     她读到              note   payload 里其实有
    #:     加了一条提醒          ''     title  = 买菜要带钥匙
    #:     记下一次就医安排       ''     hospital = 市第一医院, time = 09:30
    #:     取消了一次就医安排      ''     hospital = 市第一医院
    #:     记了一次身体数据       ''     label  = 血压
    #:     加了一件固定安排       ''     title  = 量血压, repeat = 每天, time = 08:30
    #:     暂停 / 恢复固定安排    ''     title  = 量血压
    #:
    #: 放大它的是朗读那一路：`elder3.js` 把 `${title}。${note || ''}` 交给
    #: 「再说一遍」，于是她按下去听到的是「取消了一次就医安排。」——
    #: **取消了哪一次，一个字都没有。**
    #:
    #: 只收**人话**的键。`kind`（`checkup`）这类英文枚举一律不进来——
    #: 界面上不许出现英文枚举值。体征的**读数**也不进来：审计链会被导出、
    #: 会被人看，这一层只记「记了哪一项」（同 `_EV_HEALTH_RECORDED` 那处注释）。
    _NOTE_KEYS: dict[str, tuple[str, ...]] = {
        "app.reminder.created": ("title",),
        "app.reminder.cancelled": ("title",),
        "app.appointment.created": ("hospital", "time"),
        "app.appointment.cancelled": ("hospital",),
        "app.health.recorded": ("label",),
        "app.routine.created": ("title", "repeat", "time"),
        "app.routine.paused": ("title",),
        "app.routine.resumed": ("title",),
        #: 这一条的宾语是**药名**，配合 `_DECISION_WORDS` 一起看才完整：
        #: 「没有同意那份用药计划 · 拒绝药Y」。
        "app.medication.decided": ("name",),
        #: 下面四条是这一轮补的。上面那张症状表列的就是它们，而
        #: `created`/`cancelled` 当时补了、`moved`/`completed` 漏了——
        #: 两个被覆盖的兄弟中间夹着两个没覆盖的。实测（逐行对照审计链）：
        #:
        #:     app.reminder.created    payload 有 title  -> note='复诊前准备病历'
        #:     app.reminder.moved      payload 有 title  -> note=''
        #:     app.reminder.completed  payload 有 title  -> note=''
        #:     app.contact.phone_set   payload 有 contact-> note=''
        #:
        #: 「办好了一件事。」——办好了哪一件，一个字都没有，而「再说一遍」念的就是它。
        #:
        #: `moved` 只取 `title`，**不取 `from`/`to`**：那两个是 ISO 时刻
        #: （`2026-09-02T21:00:00+00:00`），这一层的定义之一就是不把机器写法
        #: 摆给她看。改到几点由回执那句话负责（「改好了，05:00 提醒您…」）。
        "app.reminder.moved": ("title",),
        "app.reminder.completed": ("title",),
        #: 宾语是「给谁登记的」，不是号码。号码不进审计投影层。
        "app.contact.phone_set": ("contact",),
        #: 记忆那两条的宾语是**它的名字**。`decided` 配合下面
        #: `_DECISION_WORDS` 新补的那一项一起看才完整：
        #: 「没有同意记下这一条 · 爱喝的茶」。
        #:
        #: `MEMORY_PROPOSED` 是**把取样集从 payload 重算之后**才发现的：
        #: 我原本只打算补上面那三条，而按 payload 圈一遍，屏幕上 note 为空
        #: 而 payload 里有人话宾语的是**五**类，这是第五类。
        #: 教训：取样集从「已经登记的表」来，就永远看不见表里缺的成员。
        "app.memory.decided": ("key",),
        "MEMORY_PROPOSED": ("key",),
        #: 这份就医单据**是从哪来的**。
        #:
        #: 鸿蒙端补上「拍一张，我来读」之后，同一个端点会收到三种来源：
        #: 「老人本人填写」/「拍照OCR」/「拍照OCR·本人校对」
        #: （逐字定义在 `harmonyos/.../services/DocumentScan.ets` 的 `TextOrigin`）。
        #: 这三种可信度不是一回事——`youhuo-document-firewall` 整套策略就
        #: 建立在这个区分上：「所有识别文本均为不可信数据」。
        #:
        #: 实测（同一段文字换三个 source_name 各发一次）：她那一屏上是
        #: **三行逐字相同的**「您 · 健康 · 整理了一份就医单据」，
        #: 区别只在一个她看不见的字段里。又一次「同形碰撞」。
        #:
        #: 根因不在这张表：`MEDICAL_DOCUMENT_ANALYZED` 的审计载荷原先只有
        #: `review_required / diagnosis_generated / elder_id`，**`source_name`
        #: 压根没进载荷**，所以这张表就算登记了也没有键可读
        #: （`v4_api.py` 那一处已一并补上）。
        "MEDICAL_DOCUMENT_ANALYZED": ("source_name",),
    }

    #: 同一个事件、不同结果，标题不能是同一句。
    #:
    #: `MEDICATION_DOSE_RECORDED` 一个事件盖住三种结果，结果在
    #: `payload["status"]` 里（`taken` / `skipped` / `missed`）。而 `_WORDS`
    #: 只有一句「记了一次服药」。实测（她自己按的）：
    #:
    #:     记「吃了」    -> 记了一次服药
    #:     记「这次没吃」 -> **记了一次服药**
    #:
    #: 她记的是没吃，记录上写着服药——**一条说反了的用药记录**，
    #: 而家人读的是同一份记录。这和 `_DECISION_WORDS` 那一条
    #: （同意/不同意同文）是同一个病，只是这一条关于药有没有进嘴。
    #:
    #: 措辞照后端已有的 `_DOSE_WORDS`（已服用 / 没吃 / 漏服）来，不另起一套。
    _OUTCOME_TITLES: dict[str, dict[str, str]] = {
        "MEDICATION_DOSE_RECORDED": {
            "taken": "记了一次服药",
            "skipped": "记了一次没吃",
            "missed": "记了一次漏服",
        },
    }

    _MACHINERY: frozenset[str] = frozenset({
        # 纯问答：答完，世界没有任何改变。这九条是她每天最常问的话，
        # 也正是把时间线整条冲成空话的那九条。
        "CARE_QUERY_MEDICATION_TODAY",
        "CARE_QUERY_MEDICATION_LIST",
        "CARE_QUERY_MEDICATION_STOCK",
        "CARE_QUERY_SCHEDULE",
        "CARE_QUERY_HEALTH_RECENT",
        "CARE_QUERY_CONTACT",
        "CARE_QUERY_ORIENTATION",
        "CARE_QUERY_HELP",
        "CARE_REPEAT",
        # 陪聊的内部观察。`COMPANION_THEME_OBSERVED` **每一轮**写一条，
        # 而它在全仓里只出现在写它的那一行——没有任何读者。
        "COMPANION_THEME_OBSERVED",
        "COMPANION_TOPIC_RESUMED",
        # 界面模式切换（优活 / 无忧伴）。屏幕颜色变了，事没变。
        "MODE_SWITCHED",
        # 每一轮对话都写一条的呈现计划。
        #
        # 这一条我先给了词，判据全绿，**打开真页面**才看出来：她那一屏
        # 最上面两行都是它，时间线三行里占了两行。`elder3.js` 每收到一句
        # agent 的话都过一遍 `POST /v6/interaction/plan`，而那个端点每次
        # 都写一条审计。它算的是「这一轮怎么呈现」，不是她办的事。
        #
        # 我那几段旅程走的是 `/v2/chat`，页面走的是 `/v6/interaction/plan`——
        # 判据绿，屏幕错。所以运行时那张网现在也走这条路（见判据文件）。
        "COGNITIVE_LOAD_PLAN_CREATED",
        # 只是打开看了看，没动任何东西。
        #
        # `TASK_EXPLANATION_VIEWED` **从这里搬走了**（往下看 `_WORDS`）。
        # 「只是看了看」这个理由在这个仓库里已经被否过一次：
        # `MEDICAL_DOCUMENT_READ` 同样是「只是看了看」，而它有词、不在这里，
        # 那一行的注释写着「『谁看过我的就医单据』正是她该看得到的一行」。
        # 实测家属 `GET /v5/tasks/{id}/explain` 回的 `what_i_understood` 里
        # 有 `amount_cents：6840`、`bill_id`、`bill_type`——那不是空看一眼，
        # 是把她这笔钱的细节读走了，而她那两屏当时一行都没有。
        "SAFE_ACTION_PREVIEWED",
        "PRIVACY_ERASE_PREVIEWED",
        "MEDICATION_INTERACTION_DEMO_CHECK",
        # 内部管道：会话、语义路由、编排、定时器、试跑。
        "SESSION_CREATED",
        "SEMANTIC_ROUTED",
        "SEMANTIC_FRAME_PARSED",
        "SAGA_CREATED",
        "SAGA_ADVANCED",
        "SCHEDULER_TICK",
        # 小优的大脑想了一轮：记的是用了哪些工具和耗时，她那一屏不需要这一行。
        "AGENT_TURN",
        "TOOL_DRY_RUN",
        "OFFLINE_SYNC_OPERATION",
        "PURPOSE_BOUND_POLICY_DECISION",
        # 评委/研究侧的仪表，不是她的事。
        "USER_STUDY_SESSION_CREATED",
        "USER_STUDY_OBSERVATION_ADDED",
        # 环境采样，一次一条。她那一屏不是传感器日志。
        "environment.sample",
    })

    #: 同一条记录，**给家属看**时的说法。
    #:
    #: `family3.js` 拿家属令牌读的是同一个 `/api/v1/records`，而这一层是
    #: 后端预翻的——前端那套 `AUDIT_WORD_OTHER` 换不掉已经翻好的话。
    #: 于是女儿那一屏上曾经写着「记下了您的心情」（是她母亲的心情）、
    #: 「您确认了」（确认的人不是她）、「家人替您加了一条提醒」（加的人就是她）。
    #:
    #: **键是可推的，不是一份要维护的清单**：凡是 `_WORDS` 里自称说「您」的，
    #: 这里必须有一条；不说「您」的不许在这里出现（同一句话抄两遍，
    #: 将来只会改一份）。这条规则和前端 `common.js` 那两张表用的是同一条，
    #: 由 `test_the_family_never_hears_you_about_someone_else.py` 钉住。
    _WORDS_OTHER: dict[str, str] = {
        "ELDER_CONFIRMED": "老人确认了",
        "UNWELL_SIGNAL": "老人说身体不舒服，已通知家人",
        "FAMILY_REMINDER_CREATED": "家人替老人加了一条提醒",
        "REMINDER_ACKNOWLEDGE": "老人说知道了",
        "EMOTIONAL_TASK_PAUSE": "先陪老人说话，原来那件事先放着",
        "EMOTION_SIGNAL_RECORDED": "记下了老人的心情",
        "MEDICAL_DOCUMENT_READ": "有人看了老人的就医单据",
        "BREAK_GLASS_VIEWED": "有人用紧急权限看了老人的资料",
        "INTERACTION_PROFILE_UPDATED": "改了跟老人说话的方式",
        #: 下面三条跟着 `_WORDS` 去掉主语那一改一起加。
        #: 自称版用「等您点头」，家属在读别人的事时不能对她说「您」，
        #: 所以他称版说「等老人点头」——称呼照这张表原有八条的约定。
        "MEMORY_PROPOSED": "想让优活记一件事，等老人点头",
        "ITEM_MEMORY_PROPOSED": "想让优活记一件东西，等老人点头",
        "MEDICATION_PLAN_PROPOSED": "加了一份用药计划，等老人点头",
    }

    _OUTCOME_WORDS = {
        "verified": "念对了",
        "mismatch": "念的金额对不上，已停下",
        "not_restated": "没有把金额念出来",
        "not_required": "这一件不用复述",
    }

    @router.get("/records")
    def records(
        type: str | None = Query(default=None),
        limit: int = Query(default=80, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        ctx: AuthContext = Depends(_actor),
    ) -> AppRecordList:
        """真实审计流水，翻成人话之后再给前端。

        **分页在筛选之后做。** 反过来（先切 80 条再按类别筛）会得到一个
        随类别变化的、看起来像 bug 的结果：选「支付」只剩两条，而库里有二十条，
        因为前 80 条审计里恰好只有两条是支付。老人不会理解这件事，
        而它在界面上和「真的只有两条」长得一模一样。

        所以先取一批足够大的（`limit+offset` 之上再留一截给筛选损耗），
        翻译、筛完之后再切页。`total` 是**筛完的总数**，不是这一页的条数——
        没有它，调用方无法判断还有没有下一页。
        """
        events = db.list_audit(ctx.family_id, limit=max(500, (limit + offset) * 4))
        #: 她自己在读，还是家属在读。称呼由此决定，循环外算一次。
        reading_own = ctx.role is ActorRole.ELDER
        items = []
        machinery = 0
        for e in reversed(events):
            if e.event_type in _MACHINERY:
                # 内部事件不占她的槽位，但**要报数**——见 `_MACHINERY` 的说明。
                machinery += 1
                continue
            title, kind, icon = _WORDS.get(
                e.event_type, ("办了一件事", "服务", "record_request")
            )
            if not reading_own and e.event_type in _WORDS_OTHER:
                # 家属在读别人的事，不能对她说「您」。见 `_WORDS_OTHER`。
                title = _WORDS_OTHER[e.event_type]
            payload = e.payload or {}
            #: 同意还是没同意，取决于 payload，不取决于事件类型。见 `_DECISION_WORDS`。
            decision = _DECISION_WORDS.get(e.event_type)
            if decision is not None and payload.get("approved") is not None:
                title = decision[bool(payload.get("approved"))]
            #: 同一个事件的三种结果，见 `_OUTCOME_TITLES`。认不出的结果保持原样，
            #: 不硬套——宁可说得笼统，不能说反。
            outcome = _OUTCOME_TITLES.get(e.event_type)
            if outcome is not None:
                title = outcome.get(str(payload.get("status")), title)
            note = ""
            if e.event_type == "app.payment.teach_back":
                note = _OUTCOME_WORDS.get(str(payload.get("outcome")), "")
                if payload.get("heard") and payload.get("expected"):
                    note += f"（听到 {payload['heard']}，账单是 {payload['expected']}）"
            elif e.event_type == _EV_PRIVACY_ERASED:
                # 删掉了什么，**当事人过后要查得到**。
                #
                # 原先这一条的 `note` 是空串：类别和条数就在 payload 里躺着，
                # 没有渲染。而她家人走 `/v2/audit` 拿得到完整 payload。
                # 实测（老人自己删掉 3 条心情记录之后）：
                #
                #     老人 /api/v1/records  {"title":"删掉了一批个人数据","note":""}
                #     家人 /v2/audit        {"affected":{"emotion_events":3}, ...}
                #
                # 删的那一刻她是被告知的（那个响应写着「已经删掉：心情记录 3 条」），
                # 但过后回自己的记录页看就没有了。**一个不可逆的操作，
                # 只有当事人事后查不到自己删了什么**，方向不该是这样。
                #
                # 用 `_PRIVACY_WORDS` 翻成中文：payload 里存的是枚举取值
                # （`emotion_events`），界面上不许出现英文枚举值。
                # 认不出来的落到「其他数据」而不是原样显示——那条路径由
                # `_PRIVACY_WORDS` 的枚举覆盖判据保证走不到，但真走到了
                # 也不该把一个英文标识甩到老人眼前。
                parts = []
                for key, count in (payload.get("affected") or {}).items():
                    n = int(count or 0)
                    if n > 0:
                        parts.append(f"{_PRIVACY_WORDS.get(str(key), '其他数据')} {n} 条")
                if parts:
                    note = "、".join(parts)
            elif e.event_type in ("BREAK_GLASS_OPENED", "BREAK_GLASS_VIEWED"):
                # 家人用紧急权限看了她什么，**她自己的记录上要写清是哪些范围**。
                #
                # 原先这两行的 `note` 都是空串。实测（家人开一次、读一次）：
                #
                #     她的记录页  「开启了紧急查看权限」        note=''
                #                 「有人用紧急权限看了您的资料」 note=''
                #     那次实际给出去的（`GET /v5/break-glass/{id}/view`）：
                #                 位置（经纬度+精度）、5 条就医体检记录、
                #                 亲友名单与电话
                #
                # 载荷里 `scopes` 一直躺着，没有渲染。一次不可逆的隐私开放，
                # 当事人事后查不到被看了哪些范围——和 `_EV_PRIVACY_ERASED`
                # 那一条是同一个形状，而破窗是这个作品信任叙事的正中心。
                #
                # **两条都要**：`privacy.py` 把「开了权限」和「真的读了」分成
                # 两个事件名，全部理由就是它们是两件事。只修一条就是「守卫点了
                # 一个成员的名字、兄弟从旁边溜过去」。
                #
                # 中文说法**复用 `v5_store._scope_words`**，不在这里新写一份：
                # 那张表的注释里记着，范围名曾经原样念给过她听
                # （「家属因紧急情况临时查看：location。」）。
                #
                # 也不走下面 `_NOTE_KEYS` 那条通路：它做的是
                # `str(payload.get(k))`，对一个 list 会把
                # `['active_tasks', 'location']` 这个 Python repr 印到她屏幕上
                # ——既是英文枚举又是机器写法，两条都违反本项目的硬规则。
                #
                # 顺序按 `_SCOPE_WORDS` 的定义重排：载荷里是按**英文名**字母序
                # （`active_tasks` 在最前），念出来顺序无意义；重排后敏感度高的
                # 在前，而且与载荷顺序无关（确定性）。
                order = list(_SCOPE_WORDS)
                scopes = sorted(
                    (str(s) for s in (payload.get("scopes") or [])),
                    key=lambda s: (order.index(s) if s in order else len(order), s),
                )
                if scopes:
                    note = _scope_words(scopes)
            elif e.event_type in _NOTE_KEYS:
                #: 缺的键直接跳过——payload 是历史数据，老行里可能没有新键。
                parts = [str(payload.get(k)).strip() for k in _NOTE_KEYS[e.event_type]
                         if str(payload.get(k) or "").strip()]
                note = " · ".join(parts)
            elif payload.get("amount_cents") is not None:
                note = f"金额 ¥{_yuan(int(payload['amount_cents']))}"
            when = e.created_at
            # 记录页的钟点也按老人所在时区读。审计时刻本来就是真实 UTC 时刻，
            # 直接 strftime 会让「刚才那一笔」显示成八小时前。
            shown = local_now(when if when.tzinfo else when.replace(tzinfo=UTC)) if when else None
            items.append(
                {
                    "id": e.id,
                    "title": title,
                    "note": note,
                    "kind": kind,
                    "icon": icon,
                    "time": shown.strftime("%H:%M") if shown else "",
                    "at": when.isoformat() if when else None,
                    "entityId": e.entity_id,
                    #: 谁动的。规则照 `privacy.elder_activity_entries`
                    #: 那一行（`who = "您" if actor == elder else "家人"`），
                    #: 集合也**导入同一个**——抄一份名单迟早分叉。
                    #:
                    #: 没有它的时候，她自己改字号和女儿远程改字号在这一屏上
                    #: 是逐字相同的两行「改了设置」（实测），同形的碰撞六对。
                    #: 覆盖集压在字面表**之上**，次序不能反：上面那段
                    #: 注释记着的「同形碰撞六对」就是靠覆盖集分开的。
                    #:
                    #: 回退到字面表这一步原先没有，于是「字面上就知道是谁」
                    #: 的 **39 个**事件在这一屏上一律 None，而**同一件事
                    #: 在活动页上说得出**（两屏都是给她看的，同一个受众）。
                    #: 实测破窗那三步：
                    #:
                    #:     记录页  「有人用紧急权限看了您的资料」 who=None
                    #:     活动页  who=家人 「家人用紧急权限读了您的资料。」
                    #:
                    #: 里面还有 `SOS_TRIGGERED`（她按了紧急求助）、
                    #: `FAMILY_REJECTED`、`TASK_FAILED`——她因此分不出
                    #: 「优活做的」「家人做的」「您做的」。
                    #:
                    #: **两张表都没有的仍然留空。** 统一按 actor 算是错的，
                    #: 实测两头都错：`SAFETY_SIGNAL` 的 actor 是**她**而
                    #: 做判断的是**优活**；`NOTIFICATION_CREATED` /
                    #: `TEACH_BACK_VERIFIED` / `DEMO_SEEDED` 的 actor 是
                    #: `system-*`，按 actor 算会说成「家人」——
                    #: 一句假话比留空糟。
                    #:
                    #: （`DEMO_LOGIN` 两张表都没有，所以她这一屏仍然
                    #: 分不出「登录了优活」是她还是女儿。那是另一条，
                    #: 记在 KNOWN_ISSUES 里，不在这一改里顺手带。）
                    #: **谁做的这件事，要按读的人换称呼。**
                    #: `_elder_of(ctx)` 不看调用方角色（和那次
                    #: `viewer_role` 泄露同一个函数），所以家属打开自己
                    #: 那一屏，一行**她**做的事原先写着「您」——
                    #: 在跟家属说「这是你做的」。
                    #: 他称一律第三人称：她做的写「老人」，家人做的写
                    #: 「家人」，两边都不会说成读者自己。
                    "who": _who_word(
                        ctx,
                        ("您" if e.actor_id == _elder_of(ctx) else "家人")
                        if e.event_type in _WHO_FROM_ACTOR
                        else _ELDER_ACTIVITY_LABELS.get(
                            e.event_type, (None,))[0]
                    ),
                }
            )
        if type and type not in {"全部", "all"}:
            items = [i for i in items if i["kind"] == type]
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "items": page,
            # `total` = 筛完的**总数**（用来判断还有没有下一页）。
            # `count` = 这一页有几条。
            #
            # 两个都给，是因为这个端点原先只有 `total`，而它的语义是「全部」，
            # 和别的列表端点那个「这一页有几条」的 `count` 撞了名。
            # 直接改名会掀翻调用方，所以补上 `count` 并把语义写清楚——
            # 一个叫 total 一个叫 count，各自是什么，看字段名猜不出来。
            "total": total,
            "count": len(page),
            "hasMore": offset + len(page) < total,
            # 这一批里被 `_MACHINERY` 挡掉的条数。**摆出来**，不做成
            # 「总数对不上」的隐形差额：她那一屏会写「另有 N 条系统记录」。
            #
            # 和 `total` 一样，它统的是上面那一次取数窗口之内的条数
            # （`max(500, (limit+offset)*4)`），不是开天辟地以来的全部。
            "machinery": machinery,
        }

    # ---- 凭证 ---------------------------------------------------------------

    @router.get("/payments/{payment_id}/certificate")
    def certificate(payment_id: str, ctx: AuthContext = Depends(_actor)) -> AppCertificate:
        """一件事的**完整**审计链。

        `list_audit` 带 `entity_id` 走 SQL 过滤，拿到的是这一件事从头到尾的每一步，
        而不是最近 200 条里恰好属于它的那几条。凭证的全部价值就是「每一步都在」。
        """
        task = _task_or_404(ctx, payment_id)
        events = db.list_audit(ctx.family_id, limit=500, entity_id=payment_id)
        chain = [
            {
                "action": e.event_type,
                "at": e.created_at.isoformat() if e.created_at else None,
                "by": e.actor_id,
                "digest": (e.event_hash[:12] + "…") if e.event_hash else None,
            }
            for e in reversed(events)
        ]
        # 谁点的头。**两条路径都要认。**
        #
        # 这一笔可以由两个地方批准：山水版自己的 `/api/v1/.../family-approve`
        # （写 `FAMILY_APPROVED_AND_EXECUTED`，payload 里带 `approved_by`），
        # 或者旧家人端 `/family` 的「同意」按钮（走 `/v2/family/approve`，
        # 它把批准人写进 `slots["family_approver"]`）。实测两块屏幕看的是
        # **同一笔事务**，所以只认自己那条事件，就会在女儿从 `/family` 点头时
        # 把「谁点的头」显示成空——而凭证上这一格恰恰是最不能空的。
        approved_by = None
        for e in reversed(events):
            who = (e.payload or {}).get("approved_by")
            if who:
                approved_by = who
                break
        if approved_by is None:
            approver_id = task.slots.get("family_approver")
            if approver_id:
                row = db.actor(approver_id)
                approved_by = row["display_name"] if row else approver_id

        #: 这一笔有没有金额。**「没有这一格」不许折成 0.00。**
        #:
        #: 原先是 `_yuan(int(task.slots.get("amount_cents", 0) or 0))`——
        #: 一个默认值同时又是一个合法值，于是「这件事不涉及钱」和
        #: 「这件事是 0 元」在响应里长得一模一样。
        #:
        #: 而高风险的表单辅助也要家人接力（`security.py` 把带
        #: `face_verification` / `id_card` / `bank_card` / `medical_record`
        #: 的判成 HIGH，HIGH 就要家人点头），所以**不涉及钱的事真的会
        #: 走到接力屏**。实测一件人脸认证表单辅助：凭证回 amount="0.00"，
        #: 而 `"0.00"` 在 JS 里是真值，`family3.js:515` 那道
        #: `yuan ? ... : ''` 照样点着，屏幕上是
        #:
        #:     帮您填表已经核对到最后一步。金额 ¥0.00，确认后系统才会继续执行。
        #:
        #: 那一屏唯一的职责就是「按下去之前先核对」，而它编了一个货币事实；
        #: `¥0.00` 摆在「帮您填表」旁边还会被读成「这件事不花钱」。
        #:
        #: 三个消费者的守卫**本来就是照 null 写的**
        #: （`family3.js:512`、`page-family-approve.js:253`、`app.js:981`），
        #: 所以修在这里，三屏一起对。这也和下面 `type` / `paidAt` /
        #: `elements` 已经在守的那条规矩一致：有真值给真值，没有给 null。
        _cents = task.slots.get("amount_cents")
        return {
            "id": payment_id,
            "amount": (_yuan(int(_cents))
                       if _cents is not None and str(_cents) != "" else None),
            "company": task.slots.get("company"),
            #: 这一笔是什么费。页面上那个标题原先没人给值，于是保留了
            #: `hydrate()` 从**当前账单**绑上去的字——实测一笔停在
            #: `awaiting_family_approval` 的电费，凭证顶着「水费支付」
            #: 和另一笔的「完成时间」。取自这一笔自己的 slots，取不到就 None。
            "type": (f"{task.slots['bill_type']}支付"
                     if task.slots.get("bill_type") else None),
            "status": str(task.status),
            "approvedBy": approved_by,
            # 办完的时刻。没办完就是 null——不拿「现在」冒充「办好的时候」。
            #: 同上：`updated_at` 是 UTC 时刻，直接 `strftime` 会让凭证比
            #: 记录页早八小时——实测种子那一笔凭证写 11:28、记录页写 19:28。
            "paidAt": (
                local_now(task.updated_at).strftime("%Y-%m-%d %H:%M")
                if task.status is TaskStatus.COMPLETED and task.updated_at
                else None
            ),
            # 整条链是否没被动过——真的重算一遍哈希。
            "chainValid": db.verify_audit_chain(ctx.family_id),
            "chain": chain,
            # 稿子上的「凭证要素」：有真值的给真值，没有的给 null。
            # 界面上宁可少一格，也不摆一个编出来的位置或设备。
            "elements": {
                "voiceTeachBack": next(
                    (c["digest"] for c in chain if c["action"] == _EV_TEACH_BACK), None
                ),
                "location": None,
                "device": None,
                # 给人看的时刻，不是 ISO 原始串。
                # 界面上直接甩一个 `2026-08-16T18:09:04.118210+00:00` 出来，
                # 对一位老人等于没说。
                "time": (
                    local_now(datetime.fromisoformat(chain[-1]["at"]))
                    .strftime("%Y-%m-%d %H:%M:%S")
                    if chain and chain[-1]["at"]
                    else None
                ),
            },
        }

    # ---- 念给他听 ------------------------------------------------------------
    #
    # 设置页能存「语速」，而在这之前**没有任何东西按这个速度念**——
    # 这一层根本没有合成入口。存了一个没人读的偏好，比不提供这个设置更糟：
    # 老人以为自己调过了。
    #
    # 后端其实是齐的：`NeuralVoice.synthesize(text, speed)` 在，
    # `/v6/speech/synthesize` 也在。缺的是**把存下来的语速接到合成调用上**，
    # 以及一个不需要 v2 令牌的入口。

    @router.get("/speech/status")
    def speech_status(ctx: AuthContext = Depends(_actor)) -> AppSpeechStatus:
        """能不能本地合成，以及**这位老人**的语速是多少。

        客户端拿它决定走本地合成还是浏览器合成——两条路的语速要一致，
        所以速度也在这里给，不让调用方自己去 `/settings` 拼。
        """
        prefs = _read_prefs(ctx)
        st = voice.status() if voice is not None else {
            "available": False, "engine": None,
            "fallback": "browser_speech_synthesis",
            "note": "这台服务没有装离线合成。",
        }
        return {
            "available": bool(st.get("available")),
            "engine": st.get("engine"),
            "speed": float(prefs["voiceSpeed"]),
            # 有几个声音可挑、现在用的是哪个。单音色模型上就是 1 和 0，
            # 界面据此决定要不要显示「换个声音」那一栏——
            # 只有一个声音时摆一个选择器出来，是在承诺一件做不到的事。
            "speakers": int(st.get("speakers") or 1),
            # 报**实际会用的那个**：她选过就是她选的，没选过就是模型的默认音色。
            # 这里原先是 `prefs.get("voiceSpeaker", ...)`，而偏好里那个键一直是 0，
            # 于是无论模型默认几号，界面都说 0——一句永远为真的假话。
            "speaker": (int(prefs["voiceSpeaker"]) if prefs.get("voiceSpeaker") is not None
                        else int(st.get("speaker") or 0)),
            "model": st.get("model"),
            "kind": st.get("kind"),
            "fallback": st.get("fallback") or "browser_speech_synthesis",
            "note": st.get("note"),
        }

    @router.post("/speech", responses={200: {"content": {"audio/wav": {}}}})
    def speak(
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> Response:
        """把一句话念出来，**用这位老人自己存的语速**。

        `speed` 可以显式传（试听时要能不改设置就听不同档），不传就读他的偏好——
        那才是「语速这个设置真的生效了」的意思。

        模型不在时回 503 并说清楚回落到哪里，不假装念了。
        （这台机器上就是这样：`sherpa-onnx` 装着，但 `data/tts/` 下没有模型，
        它不进交付包。）
        """
        body = body or {}
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="没有要念的话。")
        if len(text) > 300:
            # 一次念三百字以上，老人早就走开了；而合成是同步的，会占住这个进程。
            raise HTTPException(status_code=400, detail="一次念的话太长了，分成几句。")

        prefs = _read_prefs(ctx)
        raw_speed = body.get("speed")
        speed = float(raw_speed) if raw_speed is not None else float(prefs["voiceSpeed"])
        speed = min(max(speed, 0.6), 1.6)
        raw_sid = body.get("speaker")
        if raw_sid is not None:
            speaker = int(raw_sid)                 # 试听：以传进来的为准
        else:
            pref_sid = prefs.get("voiceSpeaker")
            # **她没选过就传 None**，让模型自己决定用哪个音色。
            # 这里原先兜的是 0，那个 0 会一路显式传到 `synthesize`，
            # 把 `tts.py` 里「不给中文用英文音色」那道防线整条绕过。
            speaker = int(pref_sid) if pref_sid is not None else None

        if voice is None or not voice.available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="这台服务上没有离线语音，请用设备自带的朗读。",
            )
        try:
            wav, sample_rate = voice.synthesize(text, speed, sid=speaker)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # 传了 None 的话，用的是模型自己那个默认音色——**在合成之后**才问它是几号，
        # 因为 `default_sid` 是加载引擎时才定下来的（之前是 -1「还没定」）。
        used = speaker if speaker is not None else max(0, getattr(voice, "default_sid", 0))
        return Response(
            content=wav,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store",
                "X-Sample-Rate": str(sample_rate),
                # 让调用方能核对「用的确实是我存的那个语速和那个声音」。
                "X-Speech-Speed": f"{speed:.2f}",
                "X-Speech-Speaker": str(used),
            },
        )

    # ---- 听他说 --------------------------------------------------------------
    #
    # 上面那一半（念）通了很久，**这一半一直不存在**：整个后端没有任何端点
    # 收音频字节，网页端的识别全在浏览器里（`SpeechRecognition`）。
    #
    # 在浏览器上这不算缺口。**在一块板子上是缺口**——ESP32-S3 上的 INMP441
    # 采到 I2S PCM，那上面没有浏览器，这段音频此前无处可送。
    #
    # 这条路**只出文字，不做任何事**。认出「帮我交水费」不会去交水费：
    # 要办事仍然得再走一次 `/v2/chat` 和它后面的确认。把识别和动作合成一步，
    # 等于让一次误识别直接变成一笔交易。

    from .web_asr import WebEars
    web_ears = WebEars()

    def _web_voice_actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(status_code=401, detail="请刷新页面后再试。")
        return _actor(credentials)

    @router.get("/listen/web/status")
    def web_listen_status(ctx: AuthContext = Depends(_web_voice_actor)):
        return web_ears.status()

    @router.post("/listen/web")
    async def web_listen(request: Request, ctx: AuthContext = Depends(_web_voice_actor)) -> AppListenResult:
        from starlette.concurrency import run_in_threadpool
        limit = 16000 * 2 * 20 + 44
        chunks = bytearray()
        async for chunk in request.stream():
            if len(chunks) + len(chunk) > limit:
                raise HTTPException(status_code=413, detail="一次最多说20秒。")
            chunks.extend(chunk)
        try:
            return await run_in_threadpool(web_ears.transcribe, bytes(chunks))
        except (UnsupportedAudio, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/listen/status")
    def listen_status(ctx: AuthContext = Depends(_actor)) -> AppListenStatus:
        """这台服务能不能听。板子开采之前先问这个。"""
        if ears is None:
            return {
                "available": False, "engine": None, "kind": None, "model": None,
                "rate": 16000, "max_seconds": 30,
                "fallback": "browser_speech_recognition",
                "note": "这台服务没有装离线识别。",
            }
        return ears.status()

    @router.post("/listen")
    async def listen(
        request: Request,
        rate: int | None = Query(default=None, ge=8000, le=48000),
        ctx: AuthContext = Depends(_actor),
    ) -> AppListenResult:
        """把一段音频认成文字。

        请求体是**裸的音频字节**，不是 JSON：

            Content-Type: audio/wav              带头的 16 位 WAV
            Content-Type: application/octet-stream + ?rate=16000
                                                 裸 PCM（板子上最省事的那种）

        采样率必须是 16000。服务端不替你重采样——不带低通的降采样会混叠，
        识别率掉了以后第一个被怀疑的是麦克风，不是这里。

        没有模型时回 503。**不回一个空字符串**：认出一句空话和根本没认，
        在调用方那里长得一样，而两者该做的事相反。
        """
        blob = await request.body()
        if not blob:
            raise HTTPException(status_code=400, detail="没有音频数据。")
        if ears is None or not ears.available:
            note = ears.status().get("note") if ears is not None else None
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=note or "这台服务上没有离线识别，请用设备自带的语音输入。",
            )
        try:
            return ears.transcribe(blob, rate)
        except UnsupportedAudio as exc:
            # 音频不对是 400。和 503 分开，否则板子上一个配错的采样率
            # 会被当成「服务器没装模型」，然后没人去看固件。
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ---- 记一次身体数据 ------------------------------------------------------
    #
    # `/health-summary` 读 `health_events_v4`，而**此前没有任何地方往里写**——
    # 三个演示状态（empty/normal/attention）下 `metrics` 都是 `[]`，
    # 那一屏永远显示「还没有记到身体数据。」。接口是通的，只是没有入口。
    #
    # `HealthEventKind` 是**事件类别**（checkup/visit/medication/note），不是体征。
    # 老人要记的是「今天量了血压 128/82」，所以落成 `checkup` 加一个带值和单位的
    # payload——不新造枚举，那张表和 v4 的其他消费方共用。

    #: 老人说得出的那几种 → (事件类别, 默认单位)。
    #: 认不出来的按「随手记一笔」处理，**不硬塞进某一类**——
    #: 一条归错类的健康记录，比一条没归类的更难发现。
    _VITAL_KINDS: dict[str, tuple[str, str | None]] = {
        "血压": ("checkup", "mmHg"),
        "血糖": ("checkup", "mmol/L"),
        "体重": ("checkup", "kg"),
        "体温": ("checkup", "℃"),
        "心率": ("checkup", "次/分"),
        "用药": ("medication", None),
        "就诊": ("visit", None),
    }

    #: **收进来**的方向：她在界面上选的中文 -> 库里的枚举值。
    #:
    #: 名字带上方向不是讲究，是这一处栽过的原因：这两张表原先**同名**
    #: （都叫 `_SCOPE_WORDS`），而它们都是 `build_app_router` 的局部名，
    #: 后绑定的那张「印出去」的表把这张遮住了。于是下面那句 `.get("私密")`
    #: 在一张没有「私密」这个键的表里查，落到默认值 `family_summary`——
    #: 她选了「只有我看得到」，存进去却是家人可见的，屏幕上一句异样都没有。
    _SCOPE_FROM_WORD = {"私密": "private", "家人可见": "family_summary",
                        "家人详情": "family_shared"}

    @router.post("/health/events")
    def record_health_event(
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> AppHealthRecorded:
        """记一次身体数据。

        `value` 保持**字符串**：血压是「128/82」，不是一个数。
        强行拆成两个数字字段，会让「128/82」和「体重 62.5」没法用同一条路径记，
        而老人念出来的就是这两种形状。
        """
        if v4_store is None:
            raise HTTPException(status_code=503, detail="这台服务上没有开健康记录。")
        body = body or {}
        label = str(body.get("type") or body.get("label") or "").strip()
        value = str(body.get("value") or "").strip()
        if not label:
            raise HTTPException(status_code=400, detail="还没有说记的是哪一项。")
        if not value:
            raise HTTPException(status_code=400, detail=f"还没有说{label}是多少。")

        kind, default_unit = _VITAL_KINDS.get(label, ("note", None))
        unit = str(body.get("unit") or "").strip() or default_unit
        scope = _SCOPE_FROM_WORD.get(str(body.get("scope") or ""), "family_summary")

        from .v4_models import HealthEventCreate

        now = datetime.now(UTC)
        raw_at = str(body.get("at") or "").strip()
        event_at = now
        if raw_at:
            try:
                event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                if event_at.tzinfo is None:
                    event_at = event_at.replace(tzinfo=UTC)
            except ValueError:
                raise HTTPException(status_code=400, detail="这个时间看不懂，请再说一遍。")

        # 一分钟内同一项同一个值，当成手抖。
        #
        # 实测连点两下「记血压」留下**两条一模一样的记录**。血压量两次是正常的，
        # 所以不能一律拒绝——但一分钟内同一项同一个读数，只可能是重复提交。
        # 这条线画在「值也相同」上：真的量了两次，第二次的数字几乎不会一模一样。
        #
        # ## 这里原先传的是 `ActorRole.ELDER`，注释还写着「是**对的**，别改」
        #
        # 那段话说对了一半：**判断**用全量视角确实更严。错的是**拿判断结果
        # 往外说**——下面那个分支把命中那条记录的 `id` 和「它存在」这件事
        # 一起回给了调用者。实测：
        #
        #     老人记一条**私密**血压 140/95（家人列表里看不到）
        #     家人记一模一样的一笔 -> 200
        #         id      = 那条私密记录的 id
        #         message = 「刚才已经记过一次血压 140/95mmHg了。」
        #         身体记录条数不变          <- 家人这一笔还被丢掉了
        #     对照：换个数字 -> 「记好了……」，条数 +1
        #
        # 也就是：家人试着记一个值，看回的是哪一句，就能问出老人有没有一条
        # 他看不见的私密记录；而他自己那一笔无声无息地没了，回执还是绿的。
        #
        # 改成**按调用者视角**去重：
        #   · 老人自己连按两下——她看得见全部，照旧拦得住（原缺陷仍然修着）；
        #   · 家人连按两下——两条都是家人可见的，照旧拦得住；
        #   · 家人撞上老人的私密记录——从他的视角没有这一条，他那一笔正常记下，
        #     什么也不泄露。
        #
        # 第三种会留下两条同值记录（一条私密、一条家人可见）。那不是重复提交，
        # 是两个人各记了一次，其中一次她不想让人看见。为并掉它而泄露它的存在、
        # 并且丢掉家人那一笔，代价是反的。
        try:
            recent = v4_store.list_health_events(
                ctx.family_id, _elder_of(ctx), ctx.role
            )
        except Exception:      # noqa: BLE001
            recent = []
        window = datetime.now(UTC) - timedelta(minutes=1)
        for e in recent:
            when = getattr(e, "event_at", None)
            if when and when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if (
                when and when > window
                and str(getattr(e, "title", "")) == label
                and str((getattr(e, "payload", None) or {}).get("value") or "") == value
            ):
                return {
                    "ok": True,
                    "id": e.id,
                    "label": label,
                    "value": value,
                    "unit": unit,
                    "at": when.isoformat(),
                    "message": f"刚才已经记过一次{label} {value}{unit or ''}了。",
                }

        try:
            record = v4_store.create_health_event(
                ctx.family_id,
                HealthEventCreate(
                    elder_id=_elder_of(ctx),
                    kind=kind,
                    title=label,
                    event_at=event_at,
                    payload={"value": value, **({"unit": unit} if unit else {})},
                    source="elder-app",
                    scope=scope,
                ),
            )
        except Exception as exc:      # noqa: BLE001 —— 校验失败要说人话，不是 500
            raise HTTPException(status_code=400, detail=f"这一条没能记下来：{exc}") from exc

        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_HEALTH_RECORDED,
            entity_id=record.id,
            # 值本身**不进审计链**。链会被导出、会被人看，而体征是健康隐私；
            # 记「记了哪一项、什么时候」足够回答「这条数据哪来的」。
            #
            #: `elder_id` 是给**她那一屏**用的，照 `app.routine.created` 那条写
            #: （`privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。实体号是 `health-…`，
            #: 归属判断解析不出来，家人替她记的那一条会被「动作不是她做的」丢掉。
            #: 实测补之前：家人替她记一次血压，`/v2/elder/activity` **一行都没有**。
            payload={"label": label, "kind": kind, "elder_id": _elder_of(ctx)},
        )
        return {
            "ok": True,
            "id": record.id,
            "label": label,
            "value": value,
            "unit": unit,
            "at": event_at.isoformat(),
            "message": f"记好了，{label} {value}{unit or ''}。",
        }

    # ---- 紧急呼叫 -----------------------------------------------------------

    @router.post("/emergency/call")
    def emergency_call(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppEmergencyResult:
        """记一次真实的紧急呼叫。不会真的拨号——那要电话能力，这里只留证据。"""
        # 一分钟内按第二次，不再重复叫人。
        #
        # 实测连点两下，家人收到**两条**一模一样的通知。紧急呼叫尤其不能刷屏：
        # 真出事时家人手机上应该是一条清楚的呼叫，不是一串重复消息——
        # 重复本身会让人以为是系统故障，从而降低这条通知的可信度。
        #
        # **但不能直接拒绝。** 老人可能真的需要再喊一次（第一次没人接）。
        # 所以呼叫本身照记（审计链上每一次按下都在），只是不重复推送。
        #
        # **这一段必须在写本次审计之前。** 第一版放在后面，于是它查到的是
        # **自己刚写的那一条**，`recent_sos` 恒为真——实测的后果是
        # 紧急呼叫从此一条通知都不发。一个「防重复」的改动，
        # 把这个 App 里最要紧的功能整个关掉了，而接口照样 200。
        recent_sos = False
        cutoff = datetime.now(UTC) - timedelta(minutes=1)
        #: **在 SQL 里按事件类型筛**，limit 才作用在「呼叫」上。
        #:
        #: 原先取整条家庭流水的最新 20 条再在 Python 里认 `_EV_SOS`：
        #: 这一分钟里只要又产生 20 条别的审计（家人赶过来的路上翻几屏就够）,
        #: 第一次按下就被挤出视野，第二次按下查不到它，
        #: 家人收到**第二条一模一样的**紧急通知——正是上面那段注释
        #: 要防的事。去重只看得见 20 条，就不叫「一分钟内」。
        for e in db.list_audit(ctx.family_id, limit=20, event_types=(_EV_SOS,)):
            if e.created_at and e.created_at > cutoff:
                recent_sos = True
                break

        # 按**安全策略**取接力名单，而不是自己拍一个。
        #
        # 这一层原先完全不看 `safety_policies_v4`：它只找家庭成员发一条通知，
        # 于是社区网格员永远不在名单里——而「家人没接就升级到社区」正是那份
        # 策略存在的理由，`notify_community` 这个开关也就从来没有被读过。
        # 同一个 App 里两套 SOS，其中一套绕开了产品自己的安全策略。
        #
        # 和 v4 那一侧对齐的一点：**不声称已经联系了社区**。那一侧也只是
        # `community_escalation_prepared`——这个原型不自动拨号。
        escalation: list[dict[str, Any]] = []
        community_prepared = False
        try:
            policy = v4_store.get_safety_policy(ctx.family_id, _elder_of(ctx))
            contacts = v4_store.safety_contacts(
                ctx.family_id, _elder_of(ctx),
                include_community=bool(policy.get("notify_community")),
            )
            for row in contacts:
                role = str(row.get("contact_role") or "")
                if role == "community":
                    community_prepared = True
                escalation.append({
                    "name": str(row.get("name") or ""),
                    "role": "社区" if role == "community" else "家人",
                    # 已经打过码的那一列。这一屏不该出现完整号码。
                    "contact": str(row.get("address_masked") or ""),
                    "priority": int(row.get("priority") or 99),
                })
        except Exception:      # noqa: BLE001 —— 名单取不到不能让呼叫本身失败
            escalation, community_prepared = [], False

        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_SOS,
            entity_id=f"sos-{uuid.uuid4().hex[:10]}",
            payload={
                "source": (body or {}).get("source", "elder-app"),
                "community_escalation_prepared": community_prepared,
                "escalation_count": len(escalation),
            },
        )

        # **真的把家人叫起来。**
        #
        # 原先这里只写一条审计就返回「已记录这次呼叫，并按顺序联系紧急联系人」——
        # 而**没有任何人被联系**。审计是给事后查的，通知才是给当下用的。
        # 一个按了不会叫人的紧急按钮，是这个 App 里最不能有的东西。
        #
        # 联系人取真实家庭成员（不是老人自己、不是系统账号），逐个发通知；
        # 发不出去不能让这次呼叫本身失败——那会让老人以为没按上。
        notified: list[str] = []
        try:
            if recent_sos:
                raise _AlreadyCalled
            # 主要联系人排最前。
            #
            # `list_actors` 按 role 再按名字排，于是「儿子」排在「女儿」前面——
            # 而 `/contacts` 把女儿标成 `primary`（`_DEMO_FAMILY`）。
            # 不排的话，联系人页上写着「女儿 · 第一个联系」，真按下去联系的是儿子。
            # 紧急时联系错人，是这个 App 里代价最大的一种不一致。
            people = sorted(
                db.list_actors(ctx.family_id),
                key=lambda a: (a["id"] != _DEMO_FAMILY, a["display_name"]),
            )
            for row in people:
                if row["id"] == _elder_of(ctx) or row["role"] != "family":
                    continue
                engine.services.notification.send(
                    db,
                    family_id=ctx.family_id,
                    recipient_role=ActorRole.FAMILY,
                    event_type="emergency_call",
                    entity_id=f"sos-{ctx.actor_id}",
                    message=f"{ctx.display_name}按下了紧急呼叫，请尽快联系。",
                )
                notified.append(row["display_name"])
                break   # 通知是按家庭发的，不是按人发的——发一条就够，别刷屏
        except _AlreadyCalled:
            pass          # 一分钟内已经叫过了，不重复推送。呼叫本身照记。
        except Exception as exc:      # noqa: BLE001
            db.append_audit(
                family_id=ctx.family_id,
                actor_id=ctx.actor_id,
                event_type=_EV_SOS_NOTIFY_FAILED,
                entity_id=f"sos-{ctx.actor_id}",
                payload={"error": type(exc).__name__},
            )

        if recent_sos:
            message = "刚才那次呼叫已经发出去了，家人正在赶来。要是很急，请直接拨打 120。"
        elif notified:
            message = "已经记下这次呼叫，正在联系" + "、".join(notified) + "。"
        else:
            message = "已经记下这次呼叫。这个家庭还没有登记可以联系的家人，请直接拨打 120。"
        if community_prepared:
            # 措辞上**不说已经联系了社区**。名单上有，和已经打过，是两件事，
            # 而这个原型不自动拨号。说成后者，是在紧急场景里给一个假保证。
            message += "家人要是没接，社区网格员也在名单上。"
        return {
            "ok": True,
            "status": "contacting",
            "notified": notified,
            # 说的话要跟着实际发生的事走：真发出去了才说"正在联系"。
            "message": message,
            # 顺序来自 `safety_contacts` 的 `ORDER BY priority`，这里不再排一遍：
            # 变异证明那句 `sorted()` 永远改变不了任何结果——一行改不动东西的
            # 代码，下次读它的人会以为顺序是这里定的，然后去改错地方。
            "escalation": escalation,
            "communityPrepared": community_prepared,
        }

    # ---- 提醒：用药 / 就医 / 其他 -------------------------------------------
    #
    # `reminders` 表**没有类型字段**（只有 title / due_at / status / source），
    # 所以类别只能从标题认。这不是猜：`seed_demo_reminders` 写进去的就是
    # 「吃降压药」「心内科复诊」这种，语音引擎建的提醒也走同一批词。
    # 认不出来的一律归「其他」——不硬塞进某一类，否则界面上「用药提醒」里会
    # 冒出一件跟药无关的事，而那比少一条更糟。

    # 顺序有意义：先匹配到的先算。「复诊前准备病历」既有「复诊」也没有药，
    # 归就医；而「取药」两个词都沾，按这个顺序归用药——去医院取的还是药。
    _KIND_WORDS: dict[str, tuple[str, ...]] = {
        # 只写「药」不够：实测新建「吃钙片」被归成了「其他」——钙片、胶囊、
        # 维生素都是用药，却一个「药」字都没有。**不能只写「片」**，
        # 那会把「看照片」也算进来。所以逐个写完整词。
        "用药": ("药", "服药", "吃药", "钙片", "含片", "胶囊", "维生素",
                 "冲剂", "滴眼", "胰岛素", "降压", "降糖", "输液", "打针"),
        # **「就诊」必须在里面。** `create_appointment` 建的那条提醒标题是
        # `去{医院}{科室}就诊`（本文件 `title = f"去{hospital}..."` 那一行），
        # 而医院名不一定含「医院」二字：市一院、协和、华山、仁济、瑞金、
        # 同济、阜外、安贞、社区卫生服务中心——实测 12 个真实医院名里 9 个
        # 落进了「其他」。于是就医安排页有 12 条，而按「就医」筛只有 3 条。
        "就医": ("就诊", "复诊", "门诊", "挂号", "看病", "医院", "体检", "检查", "取号"),
        "健康": ("量血压", "测血糖", "血压", "血糖", "体重", "散步", "锻炼", "运动"),
    }

    def _kind_of(title: str) -> str:
        for kind, words in _KIND_WORDS.items():
            if any(w in title for w in words):
                return kind
        return "其他"

    def _reminder_view(r: Any, now: datetime) -> dict[str, Any]:
        utc = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=UTC)
        # 钟点和日期给人看，要用老人所在时区；`at` 仍给 UTC 时刻（机器用）。
        due = local_now(utc)
        # **「知道了」不是「办完了」。**
        #
        # 这一行原先是 `r.status in {COMPLETED, ACKNOWLEDGED}`，于是老人在一条
        # 用药提醒上按「我知道了」，这个端点当场回 `done=True` / `已完成`——
        # 而读它的是 `page-schedule.js`、`page-medication.js`、`page-health.js`
        # 三个页面，也就是**用药提醒页在声称药已经吃了**。
        #
        # 同一件事在 `/api/v1/agenda` 里已经分开了（见那里的长注释），
        # 而这一层没跟着改。实测同一条只按过「知道了」的提醒：
        #
        #     /v2/reminders        acknowledged
        #     /api/v1/agenda       知道了      done=False
        #     /api/v1/reminders    已完成      done=True     ← 这里
        #     /api/v1/daily-report 「还没办。」
        #
        # 一条提醒，四个读者三种说法。`done` 只认真的办完了。
        acknowledged = r.status is ReminderStatus.ACKNOWLEDGED
        done = r.status is ReminderStatus.COMPLETED
        cancelled = r.status == ReminderStatus.CANCELLED
        return {
            "id": r.id,
            "title": r.title,
            "kind": _kind_of(r.title),
            "time": due.strftime("%H:%M"),
            "date": due.strftime("%m月%d日"),
            "at": utc.isoformat(),
            "done": done,
            "cancelled": cancelled,
            # 界面上不出现英文枚举值——这里就把状态翻成人话，前端直接显示。
            # 「知道了」和 `/agenda` 用同一个词，两屏说法一致。
            "status": (
                "已取消" if cancelled
                else ("已完成" if done else ("知道了" if acknowledged else "待进行"))
            ),
            # 按过「知道了」但没办的，过了点仍然算过点——她说了句知道，
            # 药还没吃。这条跟着 `done` 走，所以自动就对了。
            "overdue": (not done) and (not cancelled) and utc < now,
        }

    def _my_reminders(ctx: AuthContext) -> list[Any]:
        """她自己的提醒，**从昨天起**往后。

        原先是 `db.list_reminders(ctx.family_id, limit=200)` 不带窗口，
        而那条 SQL 是 `ORDER BY due_at ASC LIMIT ?`——留下的是**最老的**
        200 条。家里攒够 200 条更早的提醒之后，今天和以后的一条都进不来，
        读这个端点的四个界面同时变空，而数据一直在表里：

            app/assets/js/page-schedule.js    今日事项 + 顶上那张「接下来」
            app/assets/js/page-medication.js  用药提醒（?kind=用药）
            app/assets/js/page-health.js      健康待办（?kind=健康）
            app/assets/js/page-me.js          我的（「提醒 N 条」）

        触发条件只是时间流逝：一天一条约 200 天，一天三条（这个产品
        自己举的早中晚吃药）约 68 天。`database.py:1328` 的注释早就为
        `/agenda` 记过这个坑，`/agenda` 也早就带上窗口了。

        **下界留一天**：本地当天的界限换算成 UTC 之后，边界上那几条
        （本地 00:10 = UTC 前一天 16:10）不能被切掉；而且她昨天漏掉的
        那一条要还看得见（`_reminder_view` 会把它标成过点）。

        **刻意没有上界。** `/agenda` 有 `until=day_start+2d`，因为那一屏
        只讲今天；这个端点是用药 / 就医 / 今日事项共用的源，那两屏要
        看得见接下来的安排（种子里就有一条「明天上午去社区量血压」）。
        抄一个上界过来会让「明天以后」从三个界面上消失。

        窗口有界之后 `limit` 只是安全阀，不再是取样口径。
        """
        day_start = local_now(datetime.now(UTC)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        return [
            r for r in db.list_reminders(
                ctx.family_id, limit=200,
                since=day_start - timedelta(days=1),
            )
            if r.elder_id == _elder_of(ctx)
        ]

    @router.get("/reminders")
    def reminders(kind: str | None = Query(default=None), ctx: AuthContext = Depends(_actor)) -> AppReminderList:
        """用药提醒 / 就医安排 / 今日事项 三个界面共用的真实数据源。

        `kind` 取「用药」「就医」「其他」，不传就是全部。传一个不认识的值回空表，
        不报错——界面上一个筛选按钮点出 500 比点出空列表糟得多。
        """
        now = datetime.now(UTC)
        items = [_reminder_view(r, now) for r in _my_reminders(ctx)]
        if kind:
            items = [it for it in items if it["kind"] == kind]
        return {
            "items": items,
            "count": len(items),
            "kinds": sorted({it["kind"] for it in items}),
        }

    #: 「多久之后告诉家人」的界。**不抄数字**，从家属那条路的模型上读——
    #: 同一个字段两条路，抄一份下来就是下一次两边漂移的起点。
    _ESCALATION_BOUNDS = _bounds_of(
        FamilyReminderCreateRequest, "escalation_after_minutes")
    _ESCALATION_DEFAULT = (
        FamilyReminderCreateRequest.model_fields[
            "escalation_after_minutes"].default)

    def _escalation_minutes(body: dict[str, Any]) -> int:
        """她要等多久才让家人知道。

        以前这里是 `int(body.get("escalationAfterMinutes") or 30)`。
        **`0 or 30` 在 Python 里是 30**，所以她说「到点就告诉家人」被悄悄
        改成等半小时；而且一个界都没有，实测 `-5` 和 `525600` 都存得下。

        `services.py:541` 拿这个数算升级时刻：

            threshold = due_at + timedelta(minutes=escalation_after_minutes)

        `-5` 会让升级时刻落在到点**之前**——她还没来得及应答，家人已经
        被催了；`525600` 等于永远不升级。

        最能说明 30 不是深思熟虑的下界的是：同一个意思写成字符串 `"0"`
        就存下了 0（`"0"` 是真值），写成数字 `0` 才变 30。

        界和家属那条路（`FamilyReminderCreateRequest`，`ge=5, le=1440`）
        一致，超界不再静默改写，而是 400 加一句人话。
        """
        low, high = _ESCALATION_BOUNDS
        given = body.get("escalationAfterMinutes")
        if given is None or given == "":
            return int(_ESCALATION_DEFAULT)
        try:
            minutes = int(given)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="「多久之后告诉家人」要填一个分钟数。") from None
        if minutes < low or minutes > high:
            raise HTTPException(
                status_code=400,
                detail=f"「多久之后告诉家人」要在{low}到{high}分钟之间，"
                       f"这次收到的是{minutes}。")
        return minutes

    @router.post("/reminders")
    def create_reminder(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppReminderCreated:
        """老人自己加一条提醒。**真的写进提醒表**，不是回一个 ok 就算了。

        时间用 `HH:MM`（今天）或完整 ISO 串。给的时间已经过点就顺延到明天——
        对一位老人来说「设 8 点吃药」在 9 点设，意思显然是明天 8 点，
        而不是一条建出来就已经过期的提醒。
        """
        body = body or {}
        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="还没有说要提醒什么。")

        now = datetime.now(UTC)
        raw = str(body.get("at") or body.get("time") or "").strip()
        due = _parse_when(raw) if raw else now + timedelta(hours=1)

        record = ReminderRecord(
            id=f"rem-{uuid.uuid4().hex[:12]}",
            family_id=ctx.family_id,
            elder_id=_elder_of(ctx),
            title=title,
            due_at=due,
            escalation_after_minutes=_escalation_minutes(body),
            status=ReminderStatus.SCHEDULED,
            source="elder-app",
            created_by=ctx.actor_id,
            created_at=now,
        )
        if not db.insert_reminder(record):
            raise HTTPException(status_code=409, detail="这一条没能存下来，请再试一次。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_CREATED,
            entity_id=record.id,
            payload={"title": title, "due_at": due.isoformat()},
        )
        # **说出来的钟点必须和卡片上的一致。**
        #
        # 这一行原先是 `due.strftime('%H:%M')`，而 `due` 是 UTC 时刻。
        # 于是**同一个响应体自相矛盾**（实测，本地 15:28）：
        #
        #     message   「记好了，11:30 提醒您PROBE 吃药。」
        #     item.time  "19:30"
        #     item.at    "2026-08-25T11:30:00+00:00"   ← 存的时刻是对的
        #
        # 存储早就修好了（`services.py` 里那段注释复盘的正是这件事），
        # 漏的是这句念给她听的话。语音是这个产品的主界面，
        # 而这是一条用药提醒。
        return {"ok": True, "item": _reminder_view(record, now),
                "message": _voice(
                    ctx,
                    f"记好了，{local_now(due).strftime('%H:%M')} 提醒您{title}。",
                    f"记好了，{local_now(due).strftime('%H:%M')} 提醒老人{title}。")}

    @router.post("/reminders/{reminder_id}/done")
    def complete_reminder(reminder_id: str, ctx: AuthContext = Depends(_actor)) -> AppReminderChanged:
        """办完了。写的是真状态，记录页当场就能看到这一条。"""
        now = datetime.now(UTC)
        existing = db.get_reminder(reminder_id)
        if existing is None or existing.family_id != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这一条提醒。")
        if not db.update_reminder_status(
                reminder_id, ReminderStatus.COMPLETED, "completed_at", now):
            # 说清是哪一种「改不了」。原先一律回「这一条现在改不了。」，
            # 而这两种情形老人该做的事不一样：一条已取消的事不该被记成办完，
            # 一条已经记过的不用再记。
            if existing.status is ReminderStatus.CANCELLED:
                raise HTTPException(
                    status_code=409,
                    detail="这一条已经取消了，不会再记成办好。要办的话重新加一条。")
            raise HTTPException(status_code=409, detail="这一条已经记过办好了，不用再记。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_DONE,
            entity_id=reminder_id,
            payload={"title": existing.title},
        )
        return {"ok": True, "id": reminder_id, "status": "已完成",
                "message": f"好的，{existing.title}已经记成办好了。"}

    @router.post("/reminders/{reminder_id}/cancel")
    def cancel_reminder(reminder_id: str, ctx: AuthContext = Depends(_actor)) -> AppReminderChanged:
        existing = db.get_reminder(reminder_id)
        if existing is None or existing.family_id != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这一条提醒。")
        if not db.cancel_reminder(reminder_id, ctx.family_id, _elder_of(ctx)):
            raise HTTPException(status_code=409, detail="这一条现在取消不了。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_CANCELLED,
            entity_id=reminder_id,
            payload={"title": existing.title},
        )
        # 就医安排带出来的那条提醒被单独取消时，**把话说全**。
        #
        # 取消范围是单向的：取消就医安排会连带撤提醒，并且回话里说出来
        # （「到点的提醒也一起撤了。」）；反过来只取消提醒，就医列表仍然
        # 写着「已预约」。实测过：那一屏有一条「第二人民医院 15:00 已预约」，
        # 而「今日安排」是 0 条——没有任何东西会叫她去。
        #
        # 不在这里连带取消那条安排：一次点击把一条**医疗**记录删掉，
        # 她之后既不会被提醒、也没有记录可查，比现在更糟。
        # 所以记录留着，但这句话要说清接下来该去哪里做。
        extra = ""
        if str(existing.source or "") == _APPOINTMENT_SOURCE:
            extra = "到点不再提醒了。这一次的安排还记在「就医安排」里，要一起取消就在那儿操作。"
        return {"ok": True, "id": reminder_id, "status": "已取消",
                "message": f"已经把「{existing.title}」取消了。{extra}"}

    @router.patch("/reminders/{reminder_id}")
    def reschedule_reminder(
        reminder_id: str,
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> AppReminderChanged:
        """改时间或改名字。

        此前这一层只能**建、办好、取消**——想把「八点吃药」挪到九点，唯一的办法是
        取消再建一条。那会在记录里留下「取消了一条提醒 + 加了一条提醒」两行，
        而实际发生的是一件事。审计链要能说清真正发生了什么。

        已经办好或取消的不许改：那是已经结束的事，改它等于篡改记录。
        """
        body = body or {}
        existing = db.get_reminder(reminder_id)
        if existing is None or existing.family_id != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这一条提醒。")
        if existing.status in {ReminderStatus.COMPLETED, ReminderStatus.CANCELLED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="这一条已经结束了，改不了。可以另外加一条。",
            )

        title = str(body.get("title") or "").strip() or existing.title
        due = existing.due_at
        raw = str(body.get("at") or body.get("time") or "").strip()
        if raw:
            due = _parse_when(raw)

        changed = existing.model_copy(update={"title": title, "due_at": due})
        # `insert_reminder` 是 INSERT，改不了已有行；表上有 `UNIQUE(elder_id,title,due_at)`，
        # 所以取消旧的再建新的会在同名同时间时撞唯一键。走 SQL 直改这一行。
        #
        # 直改**也会**撞那个唯一键：改到的那一刻上已经有一条同名提醒时，
        # `sqlite3.IntegrityError` 从 `update_reminder_fields` 里原样抛出去，
        # 一路穿到调用方 → 500。实测：老人看到「过一会儿再试」，
        # 而再试一百次都是同一个 500——因为撞的是数据，不是时机。
        #
        # 这里译成 409 和一句说得清的话。**不自动改名也不自动挪分钟**：
        # 那等于替她决定了一件她没说过的事，而她要的是「和那条合并」还是
        # 「换个时间」，只有她知道。
        try:
            moved = db.update_reminder_fields(reminder_id, ctx.family_id, title, due)
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail=f"那个时间已经有一条「{title}」了。换个时间，或者先把那一条取消。",
            ) from None
        if not moved:
            raise HTTPException(status_code=409, detail="这一条现在改不了。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_REMINDER_MOVED,
            entity_id=reminder_id,
            payload={"title": title, "from": existing.due_at.isoformat(),
                     "to": due.isoformat()},
        )
        return {
            "ok": True,
            "id": reminder_id,
            "status": "待进行",
            # 同上：`due` 是 UTC，念出来要走老人所在时区。
            # 实测原先「改好了，12:45 提醒您」而列表里是 20:45。
            "message": _voice(
                ctx,
                f"改好了，{local_now(due).strftime('%H:%M')} 提醒您{title}。",
                f"改好了，{local_now(due).strftime('%H:%M')} 提醒老人{title}。"),
        }

    # ---- 用药 ---------------------------------------------------------------
    #
    # 这一层此前只有「用药提醒」——一条到点响的提醒。而「今天这几次吃了没」
    # 「药还能吃几天」是另一回事，v4 早就做完了（计划、库存推算、服药记录），
    # 只是没有老人端入口。产品自己的帮助词已经在承诺这两件事：
    # 「查今天的药吃了没和药还剩多少」。
    #
    # **只读和记录，不建计划、不改剂量。** `create_medication_plan` 对 ELDER
    # 角色建的计划直接 `active=True`——把它接到老人端，等于老人可以自己给自己
    # 开一份用药计划并立刻生效。产品在话术里已经划过这条线。

    _STOCK_WORDS = {"normal": "充足", "warning": "一周内用完",
                    "critical": "快吃完了", "unknown": "不清楚"}
    _DOSE_WORDS = {"taken": "已服用", "skipped": "没吃", "missed": "漏服"}

    def _forecast(plan):
        """这份计划还能吃几天。v4 的 `InventoryService` 算，这里不另写一套。"""
        from .v4_services import InventoryService

        return InventoryService.forecast(
            plan_id=plan.id,
            stock_units=plan.stock_units,
            units_per_dose=plan.units_per_dose,
            doses_per_day=len(plan.times_local),
            today=local_now(datetime.now(UTC)).date(),
        )

    def _slot_at(day, hhmm: str) -> datetime:
        """把计划里的「08:00」变成那一天当地八点对应的 UTC 时刻。

        计划里的时间是**墙上时间**。直接当 UTC 用的话，东八区的早八点会记成
        下午四点——落到第二天的窗口里去，于是「今天吃了没」永远查不到刚记的那条。
        """
        hour, _, minute = hhmm.partition(":")
        local = datetime.combine(day, datetime.min.time(), tzinfo=local_zone())
        local = local.replace(hour=int(hour), minute=int(minute or 0))
        return local.astimezone(UTC)

    def _today_doses(ctx: AuthContext):
        """今天的每一格 + 每份计划的库存，一次算完。

        读与记录两个端点都要这份数据，分开算迟早有一处的时区或状态映射走样。
        """
        today = local_now(datetime.now(UTC)).date()
        plans = [p for p in v4_store.list_medication_plans(ctx.family_id, _elder_of(ctx)) if p.active]
        # 窗口按当地一天取。传当地日期给按 UTC 比较的 SQL 会漏掉当地深夜那几格，
        # 所以前后各放一天，再按当地日期筛回来。
        recorded = v4_store.list_doses(
            ctx.family_id, _elder_of(ctx), today - timedelta(days=1), today + timedelta(days=1)
        )
        by_slot = {}
        for d in recorded:
            when = d.scheduled_at if d.scheduled_at.tzinfo else d.scheduled_at.replace(tzinfo=UTC)
            by_slot[(d.plan_id, when.astimezone(UTC).isoformat())] = d

        doses = []
        for plan in plans:
            if today < plan.start_date or (plan.end_date is not None and today > plan.end_date):
                continue
            for hhmm in plan.times_local:
                slot = _slot_at(today, hhmm)
                hit = by_slot.get((plan.id, slot.isoformat()))
                doses.append({
                    "planId": plan.id,
                    "name": plan.display_name,
                    "doseText": plan.dose_text,
                    "time": hhmm,
                    "status": _DOSE_WORDS.get(hit.status.value, "待服用") if hit else "待服用",
                    "pending": hit is None,
                    "scheduledAt": slot.isoformat(),
                })
        doses.sort(key=lambda d: d["time"])
        return today, plans, doses

    def _plan_views(plans):
        views = []
        for plan in plans:
            f = _forecast(plan)
            days = getattr(f, "days_remaining", None)
            depletion = getattr(f, "estimated_depletion_date", None)
            views.append({
                "id": plan.id,
                "name": plan.display_name,
                "doseText": plan.dose_text,
                "times": list(plan.times_local),
                "daysRemaining": int(days) if days is not None else None,
                "depletionDate": depletion.isoformat() if depletion else None,
                "stockLabel": _STOCK_WORDS.get(f.alert_level, "不清楚"),
                "alertLevel": f.alert_level,
                "stockUnits": float(plan.stock_units),
            })
        return views

    @router.get("/medications")
    def medications_today(ctx: AuthContext = Depends(_actor)) -> AppMedicationToday:
        """今天该吃什么、吃了没、还能吃几天。

        `summary` 那句话是照 `care_voice.answer_medication_today` 的口径写的，
        包括最后那半句「我只能看到记录」——**没有记录不等于没吃**，
        这一层不许把「查不到」说成「您没吃」。
        """
        today, plans, doses = _today_doses(ctx)
        views = _plan_views(plans)
        planned = len(doses)
        taken = sum(1 for d in doses if d["status"] == "已服用")
        # 「还差几次」数的是**没有记录**的那些，不是「planned - taken」。
        # 记成「没吃」的那一格是有记录的，它不该被算进「还差」——
        # 三格全记过、其中一格没吃时，那个减法会说「还差1次」，
        # 于是老人去找一次并不存在的药。
        pending = sum(1 for d in doses if d["pending"])

        if not plans:
            summary = _voice(
                ctx,
                "您现在没有登记在册的用药计划。要登记的话，可以让家人帮您添加。",
                "老人现在没有登记在册的用药计划。")
        elif planned == 0:
            summary = _voice(
                ctx,
                "今天没有安排服药，请核对计划的开始和结束日期。",
                "老人今天没有安排服药，请核对计划的开始和结束日期。")
        elif pending == 0 and taken >= planned:
            summary = _voice(
                ctx,
                f"今天该吃的{planned}次药都记上了，您已经吃完了。",
                f"今天该吃的{planned}次药都记上了，她已经吃完了。")
        elif pending == 0:
            summary = f"今天该吃的{planned}次都记好了，其中{planned - taken}次记的是没吃。"
        elif taken == 0 and pending == planned:
            times = "、".join(sorted({d["time"] for d in doses}))
            summary = f"今天还没有服药记录。按计划要吃{planned}次，时间是{times}。"
        else:
            summary = f"今天计划吃{planned}次，已经记下{planned - pending}次，还差{pending}次。"
        if plans:
            summary += _voice(
                ctx,
                " 我只能看到记录，如果您吃了但没记，可以让家人补一条。",
                " 我只能看到记录，如果她吃了但没记，您可以替她补一条。")

        # 一周内会用完的，单独给一句——库存这件事埋在列表里老人看不见。
        low = [v for v in views if v["alertLevel"] in ("warning", "critical")]
        low.sort(key=lambda v: v["daysRemaining"] if v["daysRemaining"] is not None else 10**6)
        warning = None
        if low:
            head = low[0]
            if head["daysRemaining"] is not None:
                warning = f"{head['name']}还能吃大约{head['daysRemaining']}天，方便时补一下。"
            else:
                warning = f"{head['name']}的库存算不出能吃几天，麻烦家人核对一下。"

        return {
            "doses": doses,
            "plans": views,
            "plannedCount": planned,
            "takenCount": taken,
            "pendingCount": pending,
            "summary": summary,
            "stockWarning": warning,
        }

    def _points_at_slot(raw: str, slot: dict[str, Any]) -> bool:
        """`raw` 指的是不是这一格。**比时刻，不比字符串。**

        原先是 `raw in (d["scheduledAt"], d["time"])`——逐字符比。于是同一个
        时刻换一种合法的 ISO 写法就匹配不上，实测（列表给的是
        `2026-08-24T18:00:00+00:00`）：

            "2026-08-24T18:00:00+00:00"  → 200 已服用
            "2026-08-25T02:00:00+08:00"  → 400「今天这份药没有这个时间点。」
            "2026-08-24T18:00:00Z"       → 400 同上

        后两个和第一个是**同一时刻**。而这个仓库里 `at` 字段的偏移约定本身
        就不统一（`/api/v1/agenda` 发 `+08:00`、`/api/v1/reminders` 发
        `+00:00`），所以一个照着别处抄的客户端会稳定地打不中。
        打不中的后果不是报错就完了——那格药会一直显示「待服用」。

        `HH:MM` 那种写法照旧支持：老人端就是按钟点说事的。
        """
        if raw == slot["time"]:
            return True
        try:
            want = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            # 连 ISO 都不是，退回逐字符比——总比直接判不中好。
            return raw == slot["scheduledAt"]
        if want.tzinfo is None:
            # 不带偏移的当成**老人所在时区的墙上时间**。这一层对
            # 「几点」的约定一直是墙上时间（`_parse_when`、`_slot_at` 都是），
            # 当成 UTC 会让一个没写偏移的客户端整整偏八小时。
            want = want.replace(tzinfo=local_now(datetime.now(UTC)).tzinfo)
        return want == datetime.fromisoformat(slot["scheduledAt"])

    def _record_dose(ctx: AuthContext, plan_id: str, body: dict[str, Any] | None, status_value: str):
        body = body or {}
        today, plans, doses = _today_doses(ctx)
        plan = next((p for p in plans if p.id == plan_id), None)
        if plan is None:
            raise HTTPException(status_code=404, detail="没有找到这份用药计划。")

        raw = str(body.get("scheduledAt") or body.get("time") or "").strip()
        if raw:
            slot = next((d for d in doses if d["planId"] == plan_id
                         and _points_at_slot(raw, d)), None)
            if slot is None:
                raise HTTPException(status_code=400, detail="今天这份药没有这个时间点。")
        else:
            # 没指定就取**今天还没记的最早一格**。老人按的是「吃了」这个动作，
            # 不该要求他先选是哪一次。都记过了才报错——那时再默默记一条，
            # 记的就是一件没发生的事。
            slot = next((d for d in doses if d["planId"] == plan_id and d["pending"]), None)
            if slot is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"今天{plan.display_name}该吃的都记过了。",
                )

        if not slot["pending"]:
            # 同一格再点一次：不重复扣库存，也不当成失败。
            fresh = next((v for v in _plan_views(plans) if v["id"] == plan_id), None)
            return {
                "ok": True,
                "planId": plan_id,
                "scheduledAt": slot["scheduledAt"],
                "status": slot["status"],
                "message": f"{slot['time']}这次已经记过「{slot['status']}」了。",
                "daysRemaining": fresh["daysRemaining"] if fresh else None,
                "alreadyRecorded": True,
            }

        from .v4_models import DoseRecordRequest, DoseStatus

        # 构造放在 try **外面**。放里面的话 Pydantic 的校验错会被下面那个
        # `except ValueError` 吞成 409「已经记过了」——实测过一次：`note=""`
        # 触发了「不能为空」的校验器，端点回的却是「这一格记过了」，
        # 而那一格根本还没记。不填 note 就别传，它有默认值。
        request = DoseRecordRequest(
            scheduled_at=datetime.fromisoformat(slot["scheduledAt"]),
            status=DoseStatus(status_value),
        )
        try:
            v4_store.record_dose(ctx.family_id, ctx.actor_id, plan_id, request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            # 表上 `UNIQUE(plan_id, scheduled_at)`。上面已经挡过一次，
            # 走到这里说明两个请求同时进来了——仍然不是失败。
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        after = v4_store.get_medication_plan(plan_id)
        fresh = _plan_views([after])[0] if after else None
        word = _DOSE_WORDS[status_value]
        message = f"记下了，{slot['time']}的{plan.display_name}{word}。"
        if status_value == "taken" and fresh and fresh["alertLevel"] in ("warning", "critical"):
            message += f"这个药还能吃大约{fresh['daysRemaining']}天，方便时补一下。"
        return {
            "ok": True,
            "planId": plan_id,
            "scheduledAt": slot["scheduledAt"],
            "status": word,
            "message": message,
            "daysRemaining": fresh["daysRemaining"] if fresh else None,
            "alreadyRecorded": False,
        }

    @router.post("/medications/{plan_id}/taken")
    def record_taken(plan_id: str, body: dict[str, Any] | None = None,
                     ctx: AuthContext = Depends(_actor)) -> AppDoseRecorded:
        """记一次「吃了」。会扣库存。"""
        return _record_dose(ctx, plan_id, body, "taken")

    @router.post("/medications/{plan_id}/skipped")
    def record_skipped(plan_id: str, body: dict[str, Any] | None = None,
                       ctx: AuthContext = Depends(_actor)) -> AppDoseRecorded:
        """记一次「没吃」。**不扣库存**——药还在。"""
        return _record_dose(ctx, plan_id, body, "skipped")

    # ---- 固定安排（循环例程）----------------------------------------------
    #
    # 此前这一层只能建**一次性**提醒：想说「每天早上八点提醒我量血压」，
    # 唯一的办法是一天建一条。而 v4 的 `recurring_routines` 早就做完了，
    # 只是**两张表都是空的**——建好了从没被用过。
    #
    # 和提醒不是两个事实源：例程是生成器，`materialize_routines` 为每一次发生
    # 真的插一条提醒（`source="routine:<id>"`），所以 `/agenda` 自动认它们。
    #
    # ## 为什么建完要立刻 materialize
    #
    # `POST /v4/routines/materialize` **只允许家属或系统触发**
    # （`v4_api.py:122`）。老人自己建的例程如果不当场排期，就会一直停在那儿
    # **什么都不发生**——而界面上它看起来建好了。这一层是产品自己的后端，
    # 建完顺手把这条例程近期的发生排出来，是把老人刚才那个请求做完，
    # 不是替他触发一次全家范围的重排。

    _ROUTINE_CATEGORIES = {"life": "生活", "medication": "用药", "medical": "就医",
                           "payment": "缴费", "social": "社交"}
    _CATEGORY_BACK = {v: k for k, v in _ROUTINE_CATEGORIES.items()}
    _WEEKDAY_WORDS = ["一", "二", "三", "四", "五", "六", "日"]
    #: 建完立刻排多久。45 天（v4 的默认）会一口气生成 45 条提醒，
    #: 把今日安排和提醒列表冲垮。老人这一屏要的是「最近这一周」。
    _ROUTINE_HORIZON_DAYS = 7

    def _repeat_text(r) -> str:
        freq = getattr(r.frequency, "value", str(r.frequency))
        if freq == "daily":
            return "每天" if r.interval == 1 else f"每{r.interval}天"
        if freq == "weekly":
            if r.weekdays:
                days = "、".join(_WEEKDAY_WORDS[d] for d in sorted(r.weekdays)
                                 if 0 <= d < len(_WEEKDAY_WORDS))
                return f"每周{days}"
            return "每周"
        if freq == "monthly":
            return f"每月{r.day_of_month}号" if r.day_of_month else "每月"
        return "定期"

    def _next_occurrence(family_id: str, routine_id: str) -> datetime | None:
        """这条例程**真实存在**的最早未来场次。

        为什么不能用 `next_due_at`：那是 `materialize_routines` 的**游标**
        （`v4_store.py` 在 while 循环**出来之后**才写它），
        结构上保证落在地平线之后。实测建一条「每天 07:30」：
        真实排出 7 条（本地 09-01…09-07），而列表那一行说
        `nextText='09月08日 07:30'`——那一刻一条提醒都没有，
        它之前还排着 7 条。「下次」既不是最近的一次，
        也不是真的会发生的一次。

        取不到就 None。地平线用尽之后（第 8 天起）确实没有下一次了
        ——见 KNOWN_ISSUES 第 185 条。屏幕上留白比报一个假日期好，
        而且那个空白正好把一个静默故障变成看得见的。
        """
        now = datetime.now(UTC)
        marker = f"routine:{routine_id}"
        #: `list_reminders` 按 due_at 升序，第一条命中就是最早的。
        #: `since=now` 把窗口收在未来，顺带避开历史那一大堆。
        for row in db.list_reminders(family_id, limit=500, since=now):
            if str(row.source or "") != marker:
                continue
            if row.status in (ReminderStatus.COMPLETED,
                              ReminderStatus.CANCELLED):
                continue
            return row.due_at
        return None

    def _routine_view(r, family_id: str) -> dict[str, Any]:
        status = getattr(r.status, "value", str(r.status))
        nxt = _next_occurrence(family_id, r.id)
        local = local_now(nxt if nxt and nxt.tzinfo else
                          (nxt.replace(tzinfo=UTC) if nxt else datetime.now(UTC)))
        return {
            "id": r.id,
            "title": r.title,
            "repeatText": _repeat_text(r),
            "time": r.time_local,
            "category": _ROUTINE_CATEGORIES.get(
                getattr(r.category, "value", str(r.category)), "生活"),
            "status": "进行中" if status == "active" else "已暂停",
            "active": status == "active",
            "nextAt": nxt.isoformat() if nxt else None,
            "nextText": local.strftime("%m月%d日 %H:%M") if nxt else None,
        }

    def _materialize(ctx: AuthContext) -> int:
        """把这个家庭近期该发生的例程排成提醒，返回新排上的条数。"""
        try:
            result = v4_store.materialize_routines(
                ctx.family_id, datetime.now(UTC), _ROUTINE_HORIZON_DAYS
            )
        except Exception:      # noqa: BLE001 —— 排期失败不能让建例程本身失败
            return 0
        # 键名是 `occurrences_created`。第一版猜成了 `created`，于是恒为 0——
        # 而端点照样回 200，说「最近一周还没有要排的」，**实际排了 8 条**。
        # 猜字段名的代价就是这个：不报错，只是说了句假话。
        return int((result or {}).get("occurrences_created", 0))

    @router.get("/routines")
    def list_routines(ctx: AuthContext = Depends(_actor)) -> AppRoutineList:
        """我的固定安排。每天/每周/每月要做的那些事。"""
        rows = v4_store.list_routines(ctx.family_id, _elder_of(ctx))
        items = [_routine_view(r, ctx.family_id) for r in rows]
        running = [i for i in items if i["active"]]
        return {
            "items": items,
            "count": len(items),
            # `message` 说的是**这一份清单里有什么**，不能只数在跑的那些。
            #
            # 原先是 `if running`：停掉唯一一条之后，同一个响应里
            # `count: 1` 和「您还没有固定安排」并排出现——一句话和它旁边的
            # 数字互相打架，而两边都来自这一行代码。停掉不等于没有；
            # 屏幕上那条还在，她还能把它恢复。
            "message": (
                _voice(ctx,
                       "您还没有固定安排。像「每天早上八点量血压」这种，可以让我记下来。",
                       "老人还没有固定安排。像「每天早上八点量血压」这种，您可以替她记下来。")
                if not items
                else (_voice(ctx, f"您有{len(items)}件固定安排。",
                             f"老人有{len(items)}件固定安排。")
                      if len(running) == len(items)
                      else _voice(
                          ctx,
                          f"您有{len(items)}件固定安排，其中{len(items) - len(running)}件先停着。",
                          f"老人有{len(items)}件固定安排，其中{len(items) - len(running)}件先停着。"))),
        }

    @router.post("/routines")
    def create_routine(body: dict[str, Any] | None = None,
                       ctx: AuthContext = Depends(_actor)) -> AppRoutineChanged:
        """加一件固定安排，并把最近一周该发生的排成提醒。"""
        body = body or {}
        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="这件事要叫什么名字？")

        raw_time = str(body.get("time") or body.get("at") or "").strip()
        if not re.fullmatch(r"\d{1,2}:\d{2}", raw_time):
            raise HTTPException(status_code=400, detail="时间要写成「08:00」这样。")
        hour, minute = (int(x) for x in raw_time.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise HTTPException(status_code=400, detail="这个时间不存在。")
        time_local = f"{hour:02d}:{minute:02d}"

        repeat = str(body.get("repeat") or "每天").strip()
        freq = {"每天": "daily", "daily": "daily", "每周": "weekly", "weekly": "weekly",
                "每月": "monthly", "monthly": "monthly"}.get(repeat)
        if freq is None:
            raise HTTPException(status_code=400, detail="重复方式只支持每天、每周、每月。")

        weekdays = body.get("weekdays") or []
        try:
            weekdays = sorted({int(d) for d in weekdays})
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="星期几这个值看不懂。")
        if any(d < 0 or d > 6 for d in weekdays):
            raise HTTPException(status_code=400, detail="星期几要在 0（周一）到 6（周日）之间。")
        if freq == "weekly" and not weekdays:
            raise HTTPException(status_code=400, detail="每周的话，要说清是周几。")

        day_of_month = body.get("dayOfMonth")
        if freq == "monthly":
            try:
                day_of_month = int(day_of_month)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="每月的话，要说清是几号。")
            # 上限 28：29–31 号不是每个月都有，排到二月就会静默少一次，
            # 而老人只会看到「这个月怎么没提醒我」。
            if not 1 <= day_of_month <= 28:
                raise HTTPException(status_code=400, detail="日期要在 1 到 28 号之间。")
        else:
            day_of_month = None

        category = _CATEGORY_BACK.get(str(body.get("category") or "").strip(), "life")

        from .v4_models import RoutineCreate

        try:
            record = v4_store.create_routine(
                ctx.family_id, ctx.actor_id,
                RoutineCreate(
                    elder_id=_elder_of(ctx), title=title, category=category,
                    frequency=freq, weekdays=weekdays, day_of_month=day_of_month,
                    time_local=time_local,
                    start_date=local_now(datetime.now(UTC)).date(),
                ),
            )
        except Exception as exc:      # noqa: BLE001 —— 校验失败要说人话
            raise HTTPException(status_code=400, detail=f"这件事没能记下来：{exc}") from exc

        scheduled = _materialize(ctx)
        view = _routine_view(record, ctx.family_id)
        db.append_audit(
            family_id=ctx.family_id, actor_id=ctx.actor_id,
            event_type=_EV_ROUTINE_CREATED, entity_id=record.id,
            #: `elder_id` 是给**她那一屏**用的（`privacy._ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
            #: 实体号是 `routine-…`，归属判断解析不出来，家人建的那一条会被
            #: 「动作不是她做的」丢掉——而这是一件每天到点就会打断她的安排。
            payload={"title": title, "repeat": view["repeatText"],
                     "time": time_local, "scheduled": scheduled,
                     "elder_id": record.elder_id},
        )
        # 话跟着实际发生的事走：一条都没排上就不能说「已经排好了」。
        message = (_voice(ctx,
                          f"好，{view['repeatText']}{time_local}提醒您{title}。",
                          f"好，{view['repeatText']}{time_local}提醒老人{title}。")
                   if scheduled else
                   f"记下了：{view['repeatText']}{time_local}{title}。最近一周还没有要排的。")
        return {"ok": True, "id": record.id, "title": title,
                "status": view["status"], "message": message, "scheduled": scheduled}

    def _switch_routine(ctx: AuthContext, routine_id: str, active: bool) -> dict[str, Any]:
        from .v4_models import RoutineStatus

        try:
            record = v4_store.set_routine_status(
                ctx.family_id, _elder_of(ctx), routine_id,
                RoutineStatus.ACTIVE if active else RoutineStatus.PAUSED,
            )
        except PermissionError:
            raise HTTPException(status_code=404, detail="没有找到这件固定安排。")
        scheduled = _materialize(ctx) if active else 0
        db.append_audit(
            family_id=ctx.family_id, actor_id=ctx.actor_id,
            event_type=_EV_ROUTINE_RESUMED if active else _EV_ROUTINE_PAUSED,
            entity_id=routine_id,
            #: 同上：暂停别人给她排的安排，她那一屏也要看得到——
            #: 「明天早上不会再叫我了」这件事她得知道。
            payload={"title": record.title, "scheduled": scheduled,
                     "elder_id": record.elder_id},
        )
        return {
            "ok": True, "id": routine_id, "title": record.title,
            "status": "进行中" if active else "已暂停",
            # 暂停**不撤已经排出去的提醒**。说清楚，否则老人以为今天那条也没了。
            "message": (_voice(ctx,
                               f"好，{record.title}继续按原来的安排提醒您。",
                               f"好，{record.title}继续按原来的安排提醒老人。") if active
                        else f"好，{record.title}先不提醒了。已经排出去的那几条还在。"),
            "scheduled": scheduled,
        }

    @router.post("/routines/{routine_id}/pause")
    def pause_routine(routine_id: str, ctx: AuthContext = Depends(_actor)) -> AppRoutineChanged:
        """先不提醒了。不删——已经排出去的提醒原样留着。"""
        return _switch_routine(ctx, routine_id, False)

    @router.post("/routines/{routine_id}/resume")
    def resume_routine(routine_id: str, ctx: AuthContext = Depends(_actor)) -> AppRoutineChanged:
        """继续提醒。"""
        return _switch_routine(ctx, routine_id, True)

    # ---- 同意记忆 -----------------------------------------------------------
    #
    # 「同意记忆 + 可核验的代办」是这个产品的核心主张，而老人端此前**一个入口都没有**：
    # 他既看不到系统记住了什么，也撤不回。
    #
    # v3 那一侧是完整的，规则也明确：家属可以**提**，只有老人本人能**批准**和
    # **撤销**（`api.py:678`「只有老人本人可以批准长期记忆」/ `:694`）。
    # 这条流程按设计必须在老人端完成——而那个屏不存在。
    #
    # **走 `memory_vault`，不重写它的逻辑。** 过期自动转 `expired`、
    # 批准时写 `consent_actor_id`、按角色过滤可见性，这些都在 vault 里。
    # 这一层重写一遍就是第三次「同一件事两个实现」（前两次是字号语速和 SOS）。

    _SENS_WORDS = {"preference": "偏好", "personal": "个人信息", "sensitive": "敏感信息"}
    #: **印出去**的方向：库里的枚举值 -> 说给她听的话。
    #: 和上面那张 `_SCOPE_FROM_WORD` 是一对，方向相反——
    #: 两张表原先同名，后者把前者遮住过一次。
    _SCOPE_TO_WORD = {"private": "只有我看得到",
                      "family_summary": "家人能看到有这一条",
                      "family_shared": "家人能看到内容"}

    def _memory_detail(value: Any) -> str:
        """把 JSON 值拍成一句能念的话。

        `value` 是自由 JSON。直接 `str(dict)` 会给老人看到 `{'茶': '龙井'}`——
        大括号和引号在这一屏上没有任何意义。
        """
        if isinstance(value, dict):
            parts = [f"{k}：{v}" for k, v in value.items()
                     if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
            return "；".join(parts) if parts else "（没有可以直接读出来的内容）"
        if isinstance(value, list):
            return "、".join(str(x) for x in value[:6]) or "（空）"
        if isinstance(value, bool):
            return "是" if value else "否"
        return str(value)

    def _memory_view(item) -> dict[str, Any]:
        now = datetime.now(UTC)
        exp = getattr(item, "expires_at", None)
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        days = int((exp - now).total_seconds() // 86400) if exp else None
        created = getattr(item, "created_at", None)
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return {
            "id": item.id,
            "key": item.key,
            #: 正文被摘掉的那一条，说清楚「没给」，不要让它渲染成 `None`
            #: （`_memory_detail` 最后一行是 `str(value)`，那会把一个英文
            #: `None` 甩到界面上——界面上不许出现英文枚举值）。
            "detail": ("（家人只知道有这一条，看不到内容）"
                       if getattr(item, "content_withheld", False)
                       else _memory_detail(item.value)),
            "purpose": item.purpose,
            "sensitivity": _SENS_WORDS.get(
                getattr(item.sensitivity, "value", str(item.sensitivity)), "偏好"),
            "scope": _SCOPE_TO_WORD.get(
                getattr(item.scope, "value", str(item.scope)), "只有我看得到"),
            "since": created.isoformat() if created else "",
            "expiresAt": exp.isoformat() if exp else None,
            "daysLeft": max(0, days) if days is not None else None,
        }

    def _is_internal(item) -> bool:
        """这一条是不是这一层借记忆表存的自己的东西（见 `_INTERNAL_MEMORY_KEYS`）。"""
        return getattr(item, "key", None) in _INTERNAL_MEMORY_KEYS

    @router.get("/memories")
    def list_memories(ctx: AuthContext = Depends(_actor)) -> AppMemoryList:
        """系统记住了您什么，以及有没有等您点头的。

        分两段：**已经生效的**和**家人提了在等您的**。
        混在一起的话，「它已经记住了」和「它想记住」看起来是同一件事——
        而后者还没有得到同意。
        """
        if memory_vault is None:
            return {"items": [], "pending": [], "count": 0, "pendingCount": 0,
                    "message": "这台机器上没有开启记忆功能。"}
        elder = _elder_of(ctx)
        # 视角是**调用者自己的角色**，不是写死的 "elder"。
        #
        # ## 写死会漏什么
        #
        # `list_visible` 的规则是：`viewer_role == "elder"` 给全部，否则只给
        # `family_summary` / `family_shared`。这一行原先写死 `"elder"`，
        # 而 `_elder_of(ctx)` 又会把家人令牌解析成「她家那位老人」——
        # 于是**家人读到老人所有 `private` 的长期记忆，连正文一起**。
        #
        # 实测（老人自己记的一条 `scope=private`「老伴的忌日 / 十月初三，
        # 那天她不想被打扰」）：
        #
        #     老人 GET /api/v1/memories   老伴的忌日  只有我看得到  十月初三，…
        #     女儿 GET /api/v1/memories   老伴的忌日  只有我看得到  十月初三，…   ← 泄露
        #     女儿 GET /v3/memories/{id}  （空）                              ← 这一层是对的
        #
        # 屏幕上那一格写着**「只有我看得到」**，而它正被别人看着。
        # `api.py:786` 同一件事传的是 `viewer_role=actor.role.value`，
        # 也就是说这一层照抄了调用、没照抄视角——和上一轮那五个「本人同意」
        # 被绕过是同一个形状，同一个 `_elder_of()`。
        viewer = "elder" if ctx.role is ActorRole.ELDER else ctx.role.value
        # 生效的走 vault：它顺带把过期的转成 expired 并落库。
        # 借这张表存的设置要滤掉——它不是「优活替她记下来的事」。
        active = [m for m in memory_vault.list_visible(
            ctx.family_id, elder, viewer_role=viewer) if not _is_internal(m)]
        # 待确认的 vault 不返回（它只给 ACTIVE），直接查——
        # 所以 `list_visible` 那道范围过滤**够不到这一段**，得在这里再滤一次。
        # 少了这一句，一条老人自己提的私密项在她点头之前是全家可见的，
        # 点头之后反而藏起来了：越是没定的事越公开，正好反了。
        pending = [m for m in db.list_memories(ctx.family_id, elder)
                   if m.status == MemoryStatus.PROPOSED and not _is_internal(m)]
        if ctx.role is not ActorRole.ELDER:
            pending = [m for m in pending if m.scope in {
                MemoryScope.FAMILY_SUMMARY, MemoryScope.FAMILY_SHARED}]

        items = [_memory_view(m) for m in active]
        pend = [_memory_view(m) for m in pending]
        #: 措辞按**读的人**分两套。这条规矩这个文件自己写过
        #: （`:1886`：「自称版用「等您点头」，家属在读别人的事时不能对她说
        #: 「您」」），只是这三句一直没被纳进来。
        #:
        #: 上面那段注释记的是**同一个端点**上的内容泄露
        #: （`viewer_role` 写死成 "elder"，家人读到她所有 private 的正文）。
        #: 那一轮修了内容、没修措辞——同一个端点，一半修了一半没修。
        #:
        #: 实测家属那一侧三种状态读到的话：
        #:
        #:     有 1 件事想记下来，等**您**点头。
        #:     优活替**您**记着 1 件事。哪一条不想让它记了，随时可以忘掉。
        #:     优活现在什么都没替**您**记。
        #:
        #: 第一句尤其糟：它让家人去「点头」，而
        #: `POST /api/v1/memories/{id}/approve` 对家人是 **403
        #: 「只有老人本人可以决定要不要记住这一条。」**。
        #: 「随时可以忘掉」同理——`/forget` 对家人也是 403。
        #: 一句指向被禁动作的话比不说更糟，这是这个仓库自己的规矩
        #: （`engine.py` 那一句 "an offer that is not honoured is worse
        #: than none"）。
        #:
        #: 所以他称那一套**一个家人做不到的动作都不提**，只说这件事在等谁。
        if pend:
            msg = _voice(ctx,
                         f"有 {len(pend)} 件事想记下来，等您点头。",
                         f"有 {len(pend)} 件事想记下来，等老人点头。")
        elif items:
            msg = _voice(
                ctx,
                f"优活替您记着 {len(items)} 件事。哪一条不想让它记了，随时可以忘掉。",
                f"优活替老人记着 {len(items)} 件事。记不记由老人自己定。")
        else:
            msg = _voice(ctx, "优活现在什么都没替您记。",
                         "优活现在什么都没替老人记。")
        return {"items": items, "pending": pend, "count": len(items),
                "pendingCount": len(pend), "message": msg}

    def _voice(ctx: AuthContext, mine: str, theirs: str) -> str:
        """同一件事两种说法：她自己读到的，和家人读到的。

        `/api/v1` 这一层是**两个角色共用的**——家人那几块屏读的是同一批端点。
        而这一层的话原先一律是自称版（「等您点头」「提醒您」「您还没有…」），
        于是家人读到的是一句对**他**说「您」的话。

        这条规矩这个文件自己写过（`:1886`：「自称版用「等您点头」，家属在读
        别人的事时不能对她说「您」」），只是它管的是审计词表
        （`_WORDS` / `_WORDS_OTHER`），这一层的**消息**一直没纳进来。

        他称那一套的措辞受一条约束：**不许提家人做不到的动作**。
        哪些做得到是驱动量过的，不是猜的：

            记一次服药   `/api/v1/medications/{id}/taken`    家属 200
            同意一份药   `/api/v1/medications/{id}/approve`  家属 **403**
            建固定安排   `/api/v1/routines`                  家属 200
            停/恢复安排  `/api/v1/routines/{id}/pause|resume` 家属 200
            建提醒      `/api/v1/reminders`                  家属 200
            点头记忆     `/api/v1/memories/{id}/approve`     家属 **403**

        所以「可以替她补一条」「您可以替她记下来」敢写，
        而待确认用药那一句**不提**任何让家人去确认的动作。
        """
        return mine if ctx.role is ActorRole.ELDER else theirs

    def _who_word(ctx: AuthContext, who: str | None) -> str | None:
        """「谁做的」那一栏的称呼，也要按读的人换。

        **两个来源都会给出「您」**：`_WHO_FROM_ACTOR` 那一支按动作人算，
        另一支取的是 `_ELDER_ACTIVITY_LABELS[event][0]`——而那张表的第一格
        本来就是自称版的主语（`MODE_SWITCHED: ("您", "mode")`）。

        第一版我只改了前一支，判据照样红，因为那一行来自后一支。
        所以做成一个漏斗：两支都从这里出去。
        """
        return _voice(ctx, "您", "老人") if who == "您" else who

    def _refuse_internal(ctx: AuthContext, memory_id: str) -> None:
        """借记忆表存的东西，不许走同意/拒绝/忘掉这三条路。

        只把它从列表里滤掉是不够的：这三条路按 id 收参数，id 一旦泄漏
        （审计里就有）照样能作用在设置上，而「忘掉」在这里是不可逆的。
        对老人报的是「没有找到这一条」——从她的角度这是真的，
        那张列表上从来没有过这一条。
        """
        item = db.get_memory(memory_id)
        if item is not None and _is_internal(item):
            raise HTTPException(status_code=404, detail="没有找到这一条。")

    def _decide_memory(ctx: AuthContext, memory_id: str, approve: bool) -> dict[str, Any]:
        if memory_vault is None:
            raise HTTPException(status_code=404, detail="这台机器上没有开启记忆功能。")
        from .memory_vault import MemoryDecision

        _only_the_elder(ctx, "决定要不要记住这一条")
        _refuse_internal(ctx, memory_id)
        try:
            # 同上：传本人的 id，让 vault 自己那道身份校验真的合上。
            item = memory_vault.decide(ctx.family_id, ctx.actor_id,
                                       MemoryDecision(memory_id=memory_id, approve=approve))
        except PermissionError:
            raise HTTPException(status_code=404, detail="没有找到这一条。")
        except ValueError as exc:
            # vault 对「已经处理过的」抛 ValueError。再点一次不算失败，
            # 但也不能说成「刚刚记下了」。
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        db.append_audit(
            family_id=ctx.family_id, actor_id=ctx.actor_id,
            event_type=_EV_MEMORY_DECIDED, entity_id=memory_id,
            payload={"approved": approve, "key": item.key},
        )
        return {
            "ok": True, "id": memory_id, "key": item.key,
            "status": "已记住" if approve else "没有记",
            "message": (f"好，我记住「{item.key}」了。不想让我记的时候说一声就忘掉。"
                        if approve else f"好，「{item.key}」我不记。"),
        }

    @router.post("/memories/{memory_id}/approve")
    def approve_memory(memory_id: str, ctx: AuthContext = Depends(_actor)) -> AppMemoryDecided:
        """同意让优活记住这一条。"""
        return _decide_memory(ctx, memory_id, True)

    @router.post("/memories/{memory_id}/decline")
    def decline_memory(memory_id: str, ctx: AuthContext = Depends(_actor)) -> AppMemoryDecided:
        """不让它记。"""
        return _decide_memory(ctx, memory_id, False)

    @router.post("/memories/{memory_id}/forget")
    def forget_memory(memory_id: str, ctx: AuthContext = Depends(_actor)) -> AppMemoryDecided:
        """撤回一条已经生效的记忆。

        **这是这套机制的关键动作**——「可撤回」是「同意」成立的前提。
        撤回之后 `list_visible` 不再返回它，读它的地方拿到的是空。
        """
        if memory_vault is None:
            raise HTTPException(status_code=404, detail="这台机器上没有开启记忆功能。")
        # 「可撤回」是「同意」成立的前提，所以撤回也只能是本人。
        # 家人能替她忘掉，等于这份同意从来就不属于她。
        _only_the_elder(ctx, "决定不再记住这一条")
        _refuse_internal(ctx, memory_id)
        try:
            item = memory_vault.revoke(ctx.family_id, ctx.actor_id, memory_id)
        except PermissionError:
            raise HTTPException(status_code=404, detail="没有找到这一条。")
        db.append_audit(
            family_id=ctx.family_id, actor_id=ctx.actor_id,
            event_type=_EV_MEMORY_FORGOTTEN, entity_id=memory_id,
            payload={"key": item.key},
        )
        return {"ok": True, "id": memory_id, "key": item.key, "status": "已忘掉",
                "message": f"好，「{item.key}」我不再记着了。"}

    # ---- 家人加的药，等老人点头 -------------------------------------------
    #
    # `create_medication_plan` 对 FAMILY 角色建的计划是 `active=False`，
    # 而 `/v4/medications/decide` **只允许老人本人**调用
    # （`v4_api.py:342`「只有老人本人可以激活家属补充的用药计划」）。
    #
    # 也就是说这条流程按设计必须由老人这一端完成，而老人这一端此前没有入口：
    # 女儿在家属端加了一份钙片，它就永远停在待确认，老人看不见、也点不了同意，
    # 而且**不报任何错**——两边界面都正常。

    @router.get("/medications/pending")
    def pending_medications(ctx: AuthContext = Depends(_actor)) -> AppPendingMedicationList:
        """家人加了、还等着您点头的用药计划。"""
        rows = [p for p in v4_store.list_medication_plans(ctx.family_id, _elder_of(ctx))
                if not p.active]
        items = [{
            "id": p.id,
            "name": p.display_name,
            "doseText": p.dose_text,
            "times": list(p.times_local),
            "addedAt": p.created_at.isoformat(),
        } for p in rows]
        return {
            "items": items,
            "count": len(items),
            "message": (
                _voice(ctx,
                       "家里人给您加了" + "、".join(i["name"] for i in items)
                       + "，您看要不要开始吃。",
                       "家里人给老人加了" + "、".join(i["name"] for i in items)
                       + "，等她决定要不要开始吃。")
                if items else
                _voice(ctx, "没有等您确认的用药计划。",
                       "没有等老人确认的用药计划。")),
        }

    def _decide_plan(ctx: AuthContext, plan_id: str, approve: bool) -> dict[str, Any]:
        # 家属补的药要她本人点头才算数——这条流程的全部意义就在这里。
        # 上面那段注释引的正是这条规则（`v4_api.py:342`），而这个函数原先
        # 没有执行它：家人令牌经 `_elder_of()` 解析成老人的 id，底层校验就过了。
        _only_the_elder(ctx, "决定要不要吃这份药")
        plan = v4_store.get_medication_plan(plan_id)
        if plan is None or plan.family_id != ctx.family_id or plan.elder_id != _elder_of(ctx):
            raise HTTPException(status_code=404, detail="没有找到这份用药计划。")
        if plan.active:
            # 已经同意过的再点一次不算失败——但也不能说成「刚刚同意了」。
            return {"ok": True, "id": plan_id, "name": plan.display_name,
                    "active": True, "message": f"{plan.display_name}之前已经确认过了。"}
        try:
            # 传**调用者本人**的 id，不是 `_elder_of(ctx)`。
            #
            # 底层 `approve_medication_plan` 自己有一道身份校验，而门面原先
            # 递给它的是「她家那位老人」的 id——于是那道锁被一个不属于调用者的
            # 钥匙打开了。上面的 `_only_the_elder` 已经挡住了家人，这里改成
            # 本人 id 是让**第二道锁也真的合上**：万一哪天上面那道被绕过，
            # 这一层不会自己把钥匙递过去。
            after = v4_store.approve_medication_plan(
                ctx.family_id, ctx.actor_id, plan_id, approve)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_MEDICATION_DECIDED,
            entity_id=plan_id,
            payload={"approved": approve, "name": plan.display_name},
        )
        return {
            "ok": True,
            "id": plan_id,
            "name": plan.display_name,
            "active": bool(after.active),
            "message": (f"好，{plan.display_name}从今天开始按计划吃。" if approve
                        else f"好，{plan.display_name}先不吃，我把它取消了。"),
        }

    @router.post("/medications/{plan_id}/approve")
    def approve_medication(plan_id: str, ctx: AuthContext = Depends(_actor)) -> AppMedicationDecided:
        """同意开始吃这份药。"""
        return _decide_plan(ctx, plan_id, True)

    @router.post("/medications/{plan_id}/decline")
    def decline_medication(plan_id: str, ctx: AuthContext = Depends(_actor)) -> AppMedicationDecided:
        """先不吃。计划会被删掉，家人可以重新加。"""
        return _decide_plan(ctx, plan_id, False)

    @router.post("/appointments/{appointment_id}/cancel")
    def cancel_appointment(
        appointment_id: str,
        ctx: AuthContext = Depends(_actor),
    ) -> AppReminderChanged:
        """取消一次就医安排，并把它带出来的那条提醒一起取消。

        只取消 `appointments` 那一行是不够的：建安排时**同时**建了一条到点提醒
        （不建的话没有任何东西会叫老人）。只取消一半，老人到点还是会被提醒
        去一个已经取消了的门诊——那比不提醒更糟。
        """
        row = db.get_appointment(appointment_id)
        if row is None or row["family_id"] != ctx.family_id:
            raise HTTPException(status_code=404, detail="没有找到这次就医安排。")
        if str(row["status"]) == "cancelled":
            raise HTTPException(status_code=409, detail="这一次已经取消过了。")
        if not db.cancel_appointment(appointment_id, ctx.family_id):
            raise HTTPException(status_code=409, detail="这一次现在取消不了。")

        # 连带那条提醒。标题**加时刻**一起认，而且最多撤一条。
        #
        # 原先只按标题找，并且把所有同名的都撤掉。后果实测过：
        # 同一家医院同一个科室约了两次（8/26 09:30 和 9/2 14:00），
        # 取消其中一次，**两条提醒一起变成 cancelled**——另一次的门诊还在，
        # 而没有任何东西会再叫老人去。两边界面都正常：就医列表里那一次
        # 还写着「已预约」。
        #
        # 时刻从这一行安排自己的 `date`/`time` 重算，用和建的时候**同一套**
        # 本地时区换算——两处用不同的换算，这里就会一条也找不到，
        # 变成「安排取消了、提醒还在响」，那是另一个方向的同一个错。
        hospital = row["hospital"]
        department = row["department"] or ""
        title = f"去{hospital}{department}就诊" if department else f"去{hospital}就诊"
        want_due = None
        try:
            naive = datetime.fromisoformat(
                f"{row['appointment_date']}T{row['appointment_time'] or '09:00'}:00")
            want_due = naive.replace(
                tzinfo=local_now(datetime.now(UTC)).tzinfo).astimezone(UTC)
        except (ValueError, TypeError, KeyError):
            want_due = None

        def _same_moment(r) -> bool:
            if want_due is None:
                return True          # 算不出时刻就退回只按标题，但仍然只撤一条
            due = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=UTC)
            return abs((due - want_due).total_seconds()) < 60

        killed = 0
        # **按时刻取窗口，不要翻最老的 200 条。**
        #
        # 原先是 `db.list_reminders(ctx.family_id, limit=200)`。那条 SQL 是
        # `ORDER BY due_at ASC LIMIT ?`（`database.py:1328` 的注释已经为
        # `/agenda` 记过同一个坑），所以家里一旦攒下 200 条**更早**的提醒，
        # 这一条就永远不在这一页里，一条也撤不到。
        #
        # 实测剂量反应（同一段代码，只有历史行数不同）：
        #
        #     0   行 -> 「…到点的提醒也一起撤了。」  status=cancelled
        #     210 行 -> 「…」（后半句自己没了）      status=**scheduled**
        #                她主屏 today 里还有这一条
        #
        # 也就是上面那段 docstring 说「那比不提醒更糟」的那件事。
        #
        # 窗口是 `_same_moment`（<60 秒）的**超集**，所以只会比原来更宽、
        # 不会漏；而「最多撤一条」那道闸在下面原样留着，
        # 同一家医院两次门诊仍然只撤对应的那一次。
        # 算不出时刻时退回原来的整页扫描，行为一个字不变。
        window = ({"since": want_due - timedelta(minutes=1),
                   "until": want_due + timedelta(minutes=1)}
                  if want_due is not None else {})
        #: `statuses=` 是**无条件**的。下面那个循环自己就写着
        #: `r.status is ReminderStatus.SCHEDULED`，所以这一筛只是把循环
        #: 本来就要跳过的行交给 SQL 去跳——**一个候选都不会少**；而它让
        #: 这个调用点在任何分支上都是有界的（`window` 为空字典时也是）。
        #:
        #: 上面那段注释说「算不出时刻时退回原来的整页扫描」。那个退路仍在，
        #: 但它现在退到「她待办的 200 条」，不再是「整张表最老的 200 条」
        #: ——那段注释实测过的剂量反应（210 行历史 -> 一条也撤不到）因此
        #: 不再可能：过去的行连候选都进不来。
        for r in db.list_reminders(
                ctx.family_id, limit=200,
                statuses=(ReminderStatus.SCHEDULED,), **window):
            if killed:
                break                # 一次安排对一条提醒，撤到就停
            if (r.title == title and r.status is ReminderStatus.SCHEDULED
                    and _same_moment(r)):
                if db.cancel_reminder(r.id, ctx.family_id, r.elder_id):
                    killed += 1

        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_APPOINTMENT_CANCELLED,
            entity_id=appointment_id,
            #: `elder_id` 同上。取消比新增更要紧：一件已经出现在她首页上的事
            #: 被别人撤掉了，她那一屏关于这件事原先是零行。
            payload={"hospital": hospital, "reminders_cancelled": killed,
                     "elder_id": _elder_of(ctx)},
        )
        return {
            "ok": True,
            "id": appointment_id,
            "status": "已取消",
            "message": f"已经取消{hospital}那一次。"
                       + ("到点的提醒也一起撤了。" if killed else ""),
        }

    # ---- 紧急联系人 ----------------------------------------------------------

    #: 家庭角色 → 界面上的称呼。库里的 `role` 只有 elder/family/system 三个值，
    #: 而屏幕上不许出现英文枚举值。`display_name` 本身就是「女儿」「儿子」，
    #: 所以称呼直接用它，这张表只兜底 role。
    _ROLE_WORDS = {"family": "家人", "system": "系统", "elder": "本人"}

    @router.get("/contacts")
    def contacts(ctx: AuthContext = Depends(_actor)) -> AppContactList:
        """紧急联系人。真的读家庭成员表，不是三行写死的卡片。

        `phone` 此前恒为 `null`，因为 `actors` 表根本没有那一列。现在有了
        （见 `Database._migrate`），但**演示数据里一个号码都不种**——
        编一个出来，老人真按下去会拨错人。真实部署用 `PUT` 那个端点填。

        ## 社区那一类也在这份名单里

        紧急呼叫的回话说的是「家人要是没接，**社区网格员也在名单上**」，
        而这份名单此前只有 `actors` 表里的家人。实测：那句话说了「社区网格员」，
        而这里回的是 `['儿子','女儿','优活系统']`——**她去紧急联系人页核对，
        找不到那个人**。社区联系人只活在紧急响应的 `escalation` 里，
        那是按下呼叫之后才看得到的东西。

        一句关于紧急路径的话不成立，比别处的不一致重：她真需要的时候，
        以为有人兜底。所以这里把 `safety_contacts_v4` 一起读出来，
        让那份名单和那句话说的是同一件事。

        `phone` 仍然是 null：库里那一列是**已经打过码**的（`***-***-8899`），
        拨不出去，而这一格在界面上是可拨的样子。谁在名单上是她要知道的，
        号码不是。
        """
        elder = _elder_of(ctx)
        people = []
        for row in db.list_actors(ctx.family_id):
            if row["id"] == elder:
                continue
            people.append({
                "id": row["id"],
                "name": row["display_name"],
                "role": _ROLE_WORDS.get(row["role"], "家人"),
                "phone": row["phone"] if "phone" in row.keys() else None,
                "primary": row["id"] == _DEMO_FAMILY,
            })
        if v4_store is not None:
            try:
                policy = v4_store.get_safety_policy(ctx.family_id, elder)
                for row in v4_store.safety_contacts(
                        ctx.family_id, elder,
                        include_community=bool(policy.get("notify_community"))):
                    role = str(row.get("contact_role") or "")
                    if role != "community":
                        # 家人那一类已经从 `actors` 出来了；再列一遍会出现两个女儿。
                        continue
                    people.append({
                        "id": str(row.get("id") or ""),
                        "name": str(row.get("name") or ""),
                        "role": "社区",
                        "phone": None,
                        "primary": False,
                    })
            except Exception:      # noqa: BLE001
                # 取不到社区名单不能让整页失败——那一页是紧急时要看的。
                # 少一条比整页空白好。
                pass
        return {"items": people, "count": len(people)}

    def _is_safety_contact(ctx: AuthContext, contact_id: str) -> bool:
        """这个 id 是不是 `safety_contacts_v4` 里的一条。

        只为把上面那句 404 说准用。取不到就当不是——问「这是哪一种错」
        的时候本身再抛一个错，只会把原来那个错盖掉。
        """
        try:
            elder = _elder_of(ctx)
            policy = v4_store.get_safety_policy(ctx.family_id, elder)
            return any(
                str(r.get("id") or "") == contact_id
                for r in v4_store.safety_contacts(
                    ctx.family_id, elder,
                    include_community=bool(policy.get("notify_community")))
            )
        except Exception:      # noqa: BLE001 —— 见 docstring
            return False

    @router.put("/contacts/{contact_id}/phone")
    def set_contact_phone(
        contact_id: str,
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> AppContact:
        """给一位家人登记电话。传空串或 null 表示清掉。

        **只允许家人身份来改。** 紧急联系人的号码是紧急时真会被拨出去的东西；
        让老人端自己改它，等于把这个产品最后一道人工兜底交给最容易被诱导的一方
        （这个产品的整条设计线就是「高风险动作要第二个人点头」）。

        校验刻意宽松：这一版只做长度和字符集，不做归属地/运营商判断——
        座机、分机、境外号码都要能填，而一个填不进去的紧急联系人比没有更糟。
        """
        if ctx.role is not ActorRole.FAMILY:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="紧急联系人的电话只能由家人登记。",
            )
        row = db.actor(contact_id)
        if row is None or row["family_id"] != ctx.family_id:
            # 社区那一类联系人现在也在 `/contacts` 那份名单里（见那里的说明），
            # 但它不是 `actors` 的一行，所以到不了这里。原来一律回
            # 「这个家庭里没有这个人。」——而她**在名单上看得到那个人**，
            # 那句话读起来像系统弄丢了它。说准是哪一种。
            if v4_store is not None and _is_safety_contact(ctx, contact_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="社区那一类联系人的电话不在这里改，由社区一方维护。")
            raise HTTPException(status_code=404, detail="这个家庭里没有这个人。")

        raw = (body or {}).get("phone")
        phone = None
        if raw is not None and str(raw).strip():
            phone = re.sub(r"[\s\-()]", "", str(raw))
            if not re.fullmatch(r"\+?\d{5,20}", phone):
                raise HTTPException(status_code=400, detail="这个号码看起来不对，请再检查一下。")

        if not db.set_actor_phone(contact_id, ctx.family_id, phone):
            raise HTTPException(status_code=404, detail="这个家庭里没有这个人。")
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_CONTACT_PHONE_SET,
            entity_id=contact_id,
            # **号码本身不进审计。** 审计链是给人看的、会被导出的，
            # 而这是 PII。记「谁给谁登记了/清空了」就够回答「这个号码哪来的」。
            payload={"contact": row["display_name"], "cleared": phone is None},
        )
        fresh = db.actor(contact_id)
        return {
            "id": contact_id,
            "name": fresh["display_name"],
            "role": _ROLE_WORDS.get(fresh["role"], "家人"),
            "phone": fresh["phone"] if "phone" in fresh.keys() else None,
            "primary": contact_id == _DEMO_FAMILY,
        }

    # ---- 设置：字号与语音 ----------------------------------------------------
    #
    # ## 字号和语速**不在这一层存**
    #
    # 它们是 v6 交互档案（`interaction_profiles_v6`）的两列，那张表才是事实源。
    # 我一开始在 `memory_items` 里另存了一份，那是个真缺陷，实测长这样：
    #
    #     老人说「说慢一点」 → 它回答「好，我说慢一点。」
    #                        → 档案 0.88 降到 0.80
    #                        → 而 App 仍然用 1.0 念
    #
    # 也就是**它答应了，然后用原速念**。反过来拖滑块，档案不动，
    # 下一次「说慢一点」从档案的旧值继续往下减。字号同理：App 说 1.6，
    # `/v6/interaction/plan` 仍按 1.25 排版。
    #
    # 两边各自都对，合起来才错——所以两边的测试都不会红。
    #
    # ## 夹取范围跟着档案走
    #
    # 档案的约束是 speech_rate 0.6–1.2、font_scale 1.0–1.8（`v6_models.py`），
    # 越界会被 Pydantic 打回。这一层原来允许 voiceSpeed 到 1.6、fontScale 到 0.9，
    # 现在收进档案的范围里。fontScale 下限 1.0 是有意的：适老界面不该比常规更小。
    #
    # ## 发音人和高对比仍在 `memory_items`
    #
    # 档案里没有这两列，而它们只跟这一端有关（哪个 TTS 音色、要不要高对比配色），
    # 不参与 v6 那套自适应。留在 `sensitivity='preference'` 的同意记忆里，
    # 顺带获得撤回与审计。

    _PREF_KEY = "elder_app_settings"
    #: 只剩这一端独有的两项。字号语速从档案读，不在这里兜默认——
    #: 在这里再写一份默认值，就是把刚拆掉的第二事实源又建回来。
    _PREF_DEFAULTS = {"highContrast": False,
                       # 换了声音要存下来——不存的话下次打开又变回第一个，
                       # 而「我明明换过」是最让人怀疑功能有没有做的一种表现。
                       #
                       # **默认是 None，不是 0。** 这两个值在这里不一样：
                       # None = 「她没选过，跟模型走」，0 = 「她选了 0 号」。
                       #
                       # 原先默认写 0，后果是 `speak()` 把一个**显式的** 0 传给
                       # `synthesize`，于是 `tts.py` 里那句「不会默认用 0——
                       # 那等于让一个英文声音念中文」整条被绕过（它只在 sid is None
                       # 时才生效，而范围检查 `0 <= 0 < 103` 也放行）。
                       # 实测：这个项目里**没有任何前端能选发音人**
                       #（`backend/static` 下所有 .js 与鸿蒙侧 ArkTS 各零处），
                       # 所以那个 0 是所有人、每一句话的实际取值，
                       # kokoro 的 `default_sid = 3` 从来没被用到过。
                       "voiceSpeaker": None}
    #: 和 `InteractionProfileUpdate` 的 Field 约束一致。写死一份是因为这一层
    #: 要在调 upsert **之前**夹好——否则越界会变成 422，而老人只是拖了个滑块。
    _RATE_LO, _RATE_HI = 0.6, 1.2
    _FONT_LO, _FONT_HI = 1.0, 1.6

    def _pref_item(ctx: AuthContext):
        for item in db.list_memories(ctx.family_id, _elder_of(ctx)):
            if item.key == _PREF_KEY and item.status != MemoryStatus.REVOKED:
                return item
        return None

    def _profile(ctx: AuthContext):
        """这位老人的 v6 交互档案。没有 v6 store 时返回 None。

        `build_app_router` 允许不传 v6_store（测试里有单独构造这个路由的用法），
        那种情况下退回本层的偏好项——功能不掉，只是不与档案同步。
        """
        if v6_store is None:
            return None
        return v6_store.get_profile(ctx.family_id, _elder_of(ctx))

    def _read_prefs(ctx: AuthContext) -> dict[str, Any]:
        """这位老人当前生效的字号语速与本端偏好。

        抽出来是因为**朗读那一端也要读它**：`POST /speech` 必须按这里的语速念，
        否则那个设置又变成一个没人读的值。两处各写一遍解析，迟早有一处忘了兜默认。
        """
        item = _pref_item(ctx)
        values = dict(_PREF_DEFAULTS)
        if item is not None and isinstance(item.value, dict):
            # 老库里可能还留着旧版写进去的 fontScale / voiceSpeed。
            # 只取本端仍然管的那几个键，别让旧值盖掉档案。
            values.update({k: v for k, v in item.value.items() if k in _PREF_DEFAULTS})
        prof = _profile(ctx)
        if prof is not None:
            values["fontScale"] = round(min(max(float(prof.font_scale), _FONT_LO), _FONT_HI), 3)
            values["voiceSpeed"] = round(float(prof.speech_rate), 3)
        else:
            legacy = item.value if (item is not None and isinstance(item.value, dict)) else {}
            values["fontScale"] = float(legacy.get("fontScale", 1.25))
            values["voiceSpeed"] = float(legacy.get("voiceSpeed", 0.88))
        values["saved"] = item is not None or (prof is not None and prof.updated_by != "system")
        #: 上一次是谁调的。
        #:
        #: `saved` 只说明「库里有这一行」，**不说明是谁写的**。而 `/elder3`
        #: 拿它渲染「这是您自己调过的 / 现在是默认设置」——于是女儿一改，
        #: 她自己那一屏就写着**她自己**调的。实测（家人令牌 PUT 之后她再 GET）：
        #:
        #:     PUT  /api/v1/settings（家人）-> 200 {"saved": true, ...}
        #:     GET  /api/v1/settings（老人）-> {"saved": true, ...}
        #:     她那一屏：「这是您自己调过的」
        #:
        #: 作者身份不用新开一张表：交互档案上本来就有 `updated_by`，
        #: 而 `put_settings` 是拿调用方的 `ctx` 去 `upsert_profile` 的
        #: （`v6_store.upsert_profile(family_id, actor, payload)`）。
        #: 档案缺席时退回偏好项的 `consent_actor_id`（那一项只在创建时写，
        #: 所以只当兜底用）。
        changed_by = None
        if prof is not None and prof.updated_by != "system":
            changed_by = prof.updated_by
        elif item is not None:
            changed_by = item.consent_actor_id
        values["savedByFamily"] = bool(
            values["saved"] and changed_by is not None and changed_by != _elder_of(ctx))
        return values

    @router.get("/settings")
    def get_settings(ctx: AuthContext = Depends(_actor)) -> AppSettings:
        return _read_prefs(ctx)

    @router.put("/settings")
    def put_settings(body: dict[str, Any] | None = None, ctx: AuthContext = Depends(_actor)) -> AppSettings:
        """改字号 / 语速。**真的存下来**，换一页、重开都还在。"""
        body = body or {}
        now = datetime.now(UTC)
        values = _read_prefs(ctx)
        values.pop("saved", None)
        item = _pref_item(ctx)
        for key, cast in (("fontScale", float), ("voiceSpeed", float),
                          ("highContrast", bool), ("voiceSpeaker", int)):
            if key in body:
                try:
                    values[key] = cast(body[key])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{key} 这个值看不懂。")
        # 字号夹在能用的范围里。前端滑到 3 倍会让整屏只剩两个字。
        values["fontScale"] = round(min(max(float(values["fontScale"]), _FONT_LO), _FONT_HI), 3)
        values["voiceSpeed"] = round(min(max(float(values["voiceSpeed"]), _RATE_LO), _RATE_HI), 3)
        # 发音人不在这里夹上界：能挑几个取决于**当前装的哪个模型**，
        # 而这一层不该知道那件事。超范围由合成那一侧夹回来（它拿得到 num_speakers）。
        # 负数在任何模型上都非法，挡在这里。
        _sid = values.get("voiceSpeaker")
        values["voiceSpeaker"] = None if _sid is None else max(0, int(_sid))

        # 字号语速写回交互档案。合并的写法照 `engine.py:1606` 那一处——
        # `upsert_profile` 要的是**完整**的 update 模型，只传两个字段会把
        # verbosity / max_options / hearing_support 这些一并重置成默认值。
        prof = _profile(ctx)
        if prof is not None:
            from .v6_models import InteractionProfileUpdate

            merged = prof.model_dump(exclude={"family_id", "updated_by", "updated_at", "version"})
            merged["font_scale"] = values["fontScale"]
            merged["speech_rate"] = values["voiceSpeed"]
            v6_store.upsert_profile(ctx.family_id, ctx, InteractionProfileUpdate(**merged))

        # 本端独有的两项才落 `memory_items`。
        stored = {k: values[k] for k in _PREF_DEFAULTS}
        if item is None:
            item = MemoryItem(
                id=f"mem-{uuid.uuid4().hex[:12]}",
                family_id=ctx.family_id,
                elder_id=_elder_of(ctx),
                key=_PREF_KEY,
                value=stored,
                sensitivity=MemorySensitivity.PREFERENCE,
                scope=MemoryScope.PRIVATE,
                purpose="记住这位老人在手机端的发音人与配色偏好。字号语速在交互档案里。",
                status=MemoryStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=3650),
                consent_actor_id=ctx.actor_id,
            )
            db.create_memory(item)
        else:
            db.update_memory(item.model_copy(update={"value": stored, "updated_at": now}))
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_SETTINGS_CHANGED,
            entity_id=_PREF_KEY,
            #: `elder_id` 是给**她那一屏**用的（`_ABOUT_HER_EVEN_IF_ANOTHER_ACTED`）。
            #: 实体号是个常量（`elder_app_settings`），归属判断解析不出来，
            #: 家人改的那一条会被「动作不是她做的」丢掉。
            #:
            #: 而字号和语速落在按 `family_id` 建的那份交互档案上（上面几行），
            #: 一家一份——家人一改，**她屏幕上的字就跟着变**。
            payload={**values, "elder_id": _elder_of(ctx)},
        )
        #: `savedByFamily` 按**这一次**是谁改的算，不是回头再读一次库——
        #: 这一次的调用方就在手里，没有必要绕。
        return {**values, "saved": True,
                "savedByFamily": ctx.actor_id != _elder_of(ctx),
                "message": "设置已经记住了。"}

    # ---- 通知 ---------------------------------------------------------------

    @router.get("/notifications")
    def notifications(role: str | None = Query(default=None), ctx: AuthContext = Depends(_actor)) -> AppNotificationList:
        """通知。默认是**发给老人自己**的那些。

        `role=家人` 取发给家人的那一批——按了紧急呼叫之后，老人那一屏要能回答
        「到底通知到人了没有」，而那条通知按设计是发给家人的（不是发给他自己：
        「王爷爷按下了紧急呼叫」这句话给他本人看没有意义）。

        这里原先还写着「没有这个参数的话，这个端点在演示里永远是空的」。
        那句话曾经是真的，但成因是**种子的缺陷**而不是设计：种子只写了
        「已创建通知」那一拍审计，从没真的建过通知行。补上之后，
        演示家庭里老人这一侧有一条「账单已经由家人确认支付。」。
        """
        items = []
        try:
            wanted = ActorRole.FAMILY if role in ("家人", "family") else ActorRole.ELDER
            rows = db.list_notifications(ctx.family_id, wanted, 50)
        except Exception:
            rows = []
        for n in rows:
            created = getattr(n, "created_at", None)
            # 字段名是 `message`。
            #
            # 原先写的是 `getattr(n,"title",None) or getattr(n,"body","")`——
            # 那两个属性**都不存在**（`notifications` 表的列是
            # id/family_id/recipient_role/event_type/entity_id/message/created_at/read_at），
            # 于是每一条通知的标题都是**空字符串**。`getattr` 带默认值把
            # 「取错了字段」变成了「这条通知没有内容」，接口照样 200，
            # 列表照样有 1 条——只是每一条都是空的。
            items.append({
                "id": getattr(n, "id", None),
                "title": getattr(n, "message", "") or "",
                "eventType": getattr(n, "event_type", None),
                "read": getattr(n, "read_at", None) is not None,
                "at": created.isoformat() if created else None,
                # 钟点走老人所在时区。原先直接 `created.strftime(...)`，
                # 而 `created` 是 UTC 时刻——于是家人的通知列表把**刚刚发生**
                # 的紧急呼叫标成八小时前。实测（老人本地 15:15 按下紧急呼叫）：
                #
                #     /api/v1/notifications  time = "08月25日 07:15"
                #     /api/v1/records        time = "15:15"
                #
                # 同一件事，两屏差八小时；而通知那一屏正是家人最该立刻反应的。
                "time": (local_now(created).strftime("%m月%d日 %H:%M")
                         if created else None),
            })
        return {"items": items, "count": len(items)}

    # ==== 下面三组：v4/v5/v7 里有能力，老人端此前没有入口 =======================
    #
    #: 惰性构造的下游 store。`api.py` 只把 v4 / v6 传进这一层，v5 与 v7 没有，
    #: 而 `api.py` 不归这一轮改。两个 store 的 `_init_schema` 都是
    #: `CREATE TABLE IF NOT EXISTS`，再建一个实例是安全的；它们又都通过
    #: `self.db._conn` / `self.db._lock` 共用同一条连接，所以读写的和 `/v5`、`/v7`
    #: 是**同一份数据**，不是第二个副本。
    _downstream: dict[str, Any] = {}

    def _v5_store(request: Request):
        """优先用 `api.py` 已经建好的那一个（`app.state.v5_store`）。"""
        store = getattr(request.app.state, "v5_store", None)
        if store is not None:
            return store
        if "v5" not in _downstream:
            from .v5_store import V5FeatureStore

            _downstream["v5"] = V5FeatureStore(db)
        return _downstream["v5"]

    _V7_BASELINE = "/v7/baseline/{elder_id}"
    _V7_DAILY_REPORT = "/v7/daily-report/{elder_id}"

    def _v7_call(path: str, elder: str, day, ctx: AuthContext):
        """直接调 `/v7` 那两个端点的**函数本体**。

        为什么调它们，而不是把 `baseline_api._snapshot` 那六行抄过来：那六行里有
        两处这个项目踩过的坑——「今天」要按老人所在时区切（用 UTC 就等于把一天切在
        早上八点），以及当天没过完时要压制还没到点的通道（不压制的话上午十点打开
        会看到「就寝：比平常晚了 8 小时」）。抄一份就是第二个实现，而
        「同一件事两套实现」在这个项目里已经红过三次（字号语速、SOS、导航命名空间）。

        按**路径**取，不按下标：v7 以后再加端点，下标会静默指向另一个函数，
        而返回的东西长得很像，屏幕上看不出来。
        """
        if "v7" not in _downstream:
            from .baseline_api import build_baseline_router
            from .baseline_store import BaselineStore

            store = BaselineStore(db)
            # `current_actor` 给一个永远不会被调用的占位：下面每次都显式传
            # `actor=`，依赖注入只在 FastAPI 解析真实请求时才会走到。
            router7 = build_baseline_router(
                db, store, lambda: None, store.errand_facts
            )
            _downstream["v7"] = {
                r.path: r.endpoint for r in router7.routes if isinstance(r, APIRoute)
            }
        fn = _downstream["v7"].get(path)
        if fn is None:
            # v7 改了路径就在这里当场停下，而不是让这一屏悄悄少半边内容。
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="生活日报暂时用不了。",
            )
        # `day=` **必须**显式传。这两个函数的默认值是 `Query(default=None)` 那个
        # 对象本身，不是 `None`——直接调用时 FastAPI 不在链路上，没人替它解析，
        # 漏传就会拿一个 Query 实例去和 date 比大小，报一个看不懂的 TypeError。
        return fn(elder, day=day, actor=ctx)

    # ---- 隐私：把我的数据导出来 / 删掉 ----------------------------------------
    #
    # 底层两个端点早就在（`POST /v5/privacy/export`、`POST /v5/privacy/erase`），
    # 老人端**没有入口**：他既拿不到自己的数据，也删不掉自己的数据。
    #
    # 这一层不新增任何业务逻辑，只做三件事：
    #
    #   ① 七个英文类别名翻成他认得的说法
    #   ② 把删除拆成「先看一眼」和「确认」两步，中间用一个绑定了条数的令牌
    #   ③ 回执上写清**删了什么、还剩什么**——只说「已删除」是在给一个做不到的承诺
    #
    # **导出是纯读，它一条审计都不写。** 底层 `/v5/privacy/export` 那一侧会写
    # `PRIVACY_EXPORT_CREATED`，需要留痕的调用方走那条；这一层是老人在自己屏幕上
    # 看一眼自己的东西，而「看一眼」不许改动任何状态。这个项目为这条性质付过代价：
    # `trust.js` 的凭证页曾经在渲染时真的发起过一笔缴费。

    #: 七类可以导出 / 删除的数据。键是 `PrivacyCategory` 的取值。
    #: **加一类就必须同时加一条**——漏掉的那一类在请求里会被判成「不认识」，
    #: 而它在 `/v5` 那一侧是真能删的。`test_app_privacy.py` 按枚举逐条核对。
    _PRIVACY_WORDS: dict[str, str] = {
        # 不是一个可勾选的类别，而是「删任何一类都连带删掉」的那一项
        # （见 `v5_store.privacy_erase`）。有名字是因为它一旦真的删到了
        # 东西，就会出现在她的记录页上——那里不许露出表名。
        "trace_spans_v5": "操作留痕",
        "emotion_events": "心情记录",
        "location_history": "去过哪儿",
        "item_memories": "东西放在哪儿",
        "contact_profiles": "亲友档案",
        "medical_documents": "就医单据",
        "health_events": "身体数据",
        "device_history": "用过的设备",
    }
    _PRIVACY_KEYS = {word: key for key, word in _PRIVACY_WORDS.items()}

    def _privacy_word(key: str) -> str:
        """漏翻的那一类**当场停下**，不给兜底。

        别处（记录页那张 `_WORDS`）漏一条会落到「办了一件事」，难看但无害。
        这里不行：兜底会把 `emotion_events` 这种键印到屏幕上，而两类共用一个
        兜底名会让它们在导出里挤进同一个格子——那时条数就不再对得上任何东西。
        """
        word = _PRIVACY_WORDS.get(key)
        if word is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="有一类数据还没有中文说法，这次先不导出，免得说不清删了什么。",
            )
        return word

    def _privacy_self(ctx: AuthContext) -> str:
        """导出和删除**只有老人本人**能做。

        这一层别的端点允许家人拿令牌进来看老人的数据（它是老人端的门面）。
        这两个不行，而且不是这一层自己立的规矩：`v5_store.privacy_erase` 里写着
        「只有老人本人可以执行个人数据删除」，`/v5/privacy/export` 同样只放行本人。
        在这里先拦一道，是为了给一句人话，而不是让底层抛一个 PermissionError
        变成 500。
        """
        if ctx.role is not ActorRole.ELDER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="这一项只有老人本人能做。您可以陪着他一起看，但不能替他决定。",
            )
        return ctx.actor_id

    def _privacy_categories(names: Any) -> list[Any]:
        """请求里收**中文**类别名，不收 `emotion_events`。

        前端不该知道表名。这一层里已经有同样的做法（记忆那一屏的 `_SCOPE_WORDS`
        就是「私密」→`private`）。不认识的名字当场 400 并把可选项列出来——
        悄悄忽略一个拼错的类别，等于按用户没要求的范围去删。
        """
        from .v5_models import PrivacyCategory

        if not names:
            return list(PrivacyCategory)
        if not isinstance(names, list):
            raise HTTPException(status_code=400, detail="要删哪几类，请给一个列表。")
        picked: list[PrivacyCategory] = []
        for raw in names:
            key = _PRIVACY_KEYS.get(str(raw).strip())
            if key is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{raw}」不是一类可以删的数据。可以选："
                           + "、".join(_PRIVACY_KEYS),
                )
            item = PrivacyCategory(key)
            if item not in picked:
                picked.append(item)
        return picked

    def _privacy_buckets(counts: dict[str, int], categories) -> list[dict[str, Any]]:
        """把删除／导出的条数翻成「类别名 + 条数」，给屏幕用。

        **桶是按 `counts` 里真有的东西建的，不只按请求的类别。**

        原先它只遍历 `categories`，于是 `counts` 里出现一个不属于任何可勾选
        类别的键时，那一项会被**静默丢掉**：`v5_store.privacy_erase` 现在会
        连带删掉她自己的执行留痕（`trace_spans_v5`，那张表有 `actor_id`
        但不是一个可勾选类别，理由见那个方法），执行时真的删了，而预览和
        删除回话里一个字都不提。

        她会看到「确认之后会删掉：心情记录 7 条，一共 7 条」，然后被删掉 12 条。
        两边都不报错——`total` 是这里算出来的，所以它和屏幕自洽。

        请求的类别即使是 0 条也照旧列出（她勾了就该看到结果，哪怕是 0）；
        额外那些只在真有条数时才追加，否则会多出一句「操作留痕 0 条」。
        """
        named = [
            {"name": _privacy_word(c.value), "count": int(counts.get(c.value, 0) or 0)}
            for c in categories
        ]
        asked = {c.value for c in categories}
        extra = [
            {"name": _privacy_word(key), "count": int(count or 0)}
            for key, count in sorted(counts.items())
            if key not in asked and int(count or 0) > 0
        ]
        return named + extra

    def _spell_out(buckets: list[dict[str, Any]]) -> str:
        return "、".join(f"{b['name']} {b['count']} 条" for b in buckets if b["count"])

    def _erase_token(ctx: AuthContext, elder: str, counts: dict[str, int]) -> str:
        """把「您看到的那一份」和「您确认的那一次」绑在一起。

        令牌算的是**类别加当时的条数**。它保证的**不是**防伪造——这两个端点本来
        就只有老人本人进得来，而且算法就写在这里，谁都算得出。它保证的是
        **确认的对象和您看到的那一份是同一份**：中间数据变了，条数就变了，
        令牌对不上，第二步会请您重看一遍。

        要防的是这个：回执上写着「删掉 7 条」，实际删了 9 条，而两边都不报错。
        顺带也挡住了「一个裸 POST 就把数据抹了」——那一条另有 400 分支明说。
        """
        return semantic_hash([
            "app.privacy.erase", ctx.family_id, elder,
            *(f"{key}={counts[key]}" for key in sorted(counts)),
        ])

    @router.get("/privacy/data")
    def export_my_data(
        request: Request, ctx: AuthContext = Depends(_actor)
    ) -> AppPrivacyExport:
        """「把优活替我存的东西导出来」。

        **这是一个纯读端点。** 它不写审计、不落库、不碰任何一笔事务。
        """
        elder = _privacy_self(ctx)
        from .v5_models import PrivacyCategory

        categories = list(PrivacyCategory)
        bundle = _v5_store(request).privacy_export(ctx.family_id, elder, categories)
        counts = {key: len(rows) for key, rows in bundle.records.items()}
        buckets = _privacy_buckets(counts, categories)
        total = sum(b["count"] for b in buckets)
        kinds = [b for b in buckets if b["count"]]
        generated = bundle.generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=UTC)
        return {
            "generatedAt": local_now(generated).isoformat(),
            "buckets": buckets,
            "total": total,
            #: 截断是为了能念出来。完整摘要在 `/v5/privacy/export` 那一侧。
            "digest": bundle.manifest_digest[:12] + "…",
            # 键换成中文，行内容原样给。行里是**存着的数据本身**（已经过
            # `PrivacyRedactor` 脱敏），不是界面文案——一份不含数据的「导出」
            # 不是导出。屏幕上要显示的是 `buckets` 和 `message`。
            "records": {_privacy_word(k): v for k, v in bundle.records.items()},
            "note": bundle.note,
            "message": (
                f"优活替您存着 {total} 条记录，分 {len(kinds)} 类："
                + _spell_out(kinds)
                + "。这份是您自己的，可以存下来，也可以给家人看。"
            ) if total else "这几类里，优活现在没有替您存任何记录。",
        }

    @router.post("/privacy/erase/preview")
    def preview_erase(
        request: Request,
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> AppPrivacyErasePreview:
        """删除的**第一步**：先看一眼要删掉什么。这一步什么都不删。

        「重要的事两边都同意才办」是这个产品的核心主张。删除没有第二个人可以
        点头（按设计只有本人能删），所以两次同意都由本人给：看一眼，再确认。
        """
        elder = _privacy_self(ctx)
        categories = _privacy_categories((body or {}).get("categories"))
        result = _v5_store(request).privacy_erase(
            ctx.family_id, ctx, elder, categories, False
        )
        buckets = _privacy_buckets(result.affected_rows, categories)
        total = sum(b["count"] for b in buckets)
        preserved = list(result.preserved_records)
        return {
            "willDelete": buckets,
            "total": total,
            "preserved": preserved,
            "confirmToken": _erase_token(ctx, elder, result.affected_rows),
            "message": (
                "还没有删。确认之后会删掉：" + _spell_out(buckets)
                + f"，一共 {total} 条。这些会留下来："
                + "、".join(preserved) + "。删掉的找不回来。"
            ) if total else (
                "这几类里现在没有可以删的记录。"
                + "、".join(preserved) + "本来就不在可删的范围里。"
            ),
        }

    @router.post("/privacy/erase")
    def erase_my_data(
        request: Request,
        body: dict[str, Any] | None = None,
        ctx: AuthContext = Depends(_actor),
    ) -> AppPrivacyErased:
        """删除的**第二步**：真的删。要带上第一步给的 `confirmToken`。"""
        elder = _privacy_self(ctx)
        body = body or {}
        categories = _privacy_categories(body.get("categories"))
        token = str(body.get("confirmToken") or "").strip()
        if not token:
            raise HTTPException(
                status_code=400,
                detail="删除要先看一眼、再确认。请先打开「看看要删掉什么」。",
            )
        store = _v5_store(request)
        # 再数一遍，而且以**这一遍**为准：令牌对得上，说明现在的情况和您刚才
        # 看到的那一份一模一样。
        seen = store.privacy_erase(ctx.family_id, ctx, elder, categories, False)
        if token != _erase_token(ctx, elder, seen.affected_rows):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="刚才看到的情况已经变了。请再看一遍要删掉什么，然后重新确认。",
            )
        if sum(int(n or 0) for n in seen.affected_rows.values()) == 0:
            # 「本来就没有可删的」不是一次成功的删除。回 409，让界面照着说，
            # 而不是画一个绿勾让老人以为刚刚抹掉了什么。
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="这几类里现在没有可以删的记录，什么都没有改动。",
            )
        result = store.privacy_erase(ctx.family_id, ctx, elder, categories, True)
        db.append_audit(
            family_id=ctx.family_id,
            actor_id=ctx.actor_id,
            event_type=_EV_PRIVACY_ERASED,
            entity_id=elder,
            payload={
                "categories": [c.value for c in categories],
                "affected": result.affected_rows,
            },
        )
        buckets = _privacy_buckets(result.affected_rows, categories)
        total = sum(b["count"] for b in buckets)
        preserved = list(result.preserved_records)
        return {
            "ok": True,
            "deleted": buckets,
            "total": total,
            "preserved": preserved,
            "message": (
                "已经删掉：" + _spell_out(buckets) + f"，一共 {total} 条。"
                + "还留着：" + "、".join(preserved)
                + "。留下的这几样是为了将来能查清楚谁在什么时候办了什么，删不掉。"
            ),
        }

    # ---- 心情回顾 -------------------------------------------------------------
    #
    # 底层是 `/v4/reports/emotion/{elder}`——一份**汇总**：类别计数、趋势、
    # 几句建议。聊天原文不在里面，连原文的指纹也不在。
    # 「他和无忧伴聊过的话不会出现在这里」是写在界面上的承诺，这一层不许把它破掉。

    _MOOD_WORDS = {
        "positive": "心情不错", "calm": "平静", "lonely": "孤单",
        "low_mood": "低落", "anxious": "着急", "angry": "烦躁",
        "urgent": "急着要人帮忙",
    }
    #: 底层的趋势一共只有这三个取值（`v4_store.generate_emotion_report`）。
    #:
    #: **这一层不做趋势判断。** 它只是把底层算出来的那个值说成人话。
    #: KNOWN_ISSUES 记着：上一个 agent 做情绪时，它自己写的测试报「情绪趋势是
    #: 编造出来的上升」，那批改动整段回退。结论归底层，门面只负责翻译。
    _TREND_WORDS = {
        "distress_increasing": "比上一段时间紧张一些",
        "distress_decreasing": "比上一段时间松快一些",
        "stable_or_insufficient": "和上一段时间差不多，或者记录还不够多",
    }

    @router.get("/emotions/review")
    def emotion_review(
        days: int = Query(default=14, ge=1, le=31),
        ctx: AuthContext = Depends(_actor),
    ) -> AppEmotionReview:
        """「我这段时间心情怎么样」。"""
        if v4_store is None:
            raise HTTPException(status_code=404, detail="这台机器上没有开启心情记录。")
        elder = _elder_of(ctx)
        # 「今天」按老人所在时区切。用 UTC 的今天，在东八区等于把一天切在早上八点。
        end = local_today(datetime.now(UTC))
        start = end - timedelta(days=days - 1)
        summary = (
            v4_store.generate_emotion_report(ctx.family_id, elder, start, end).summary
            or {}
        )
        counts = summary.get("label_counts") or {}
        moods = sorted(
            (
                {"name": _MOOD_WORDS.get(str(label), "说不上来"), "count": int(n)}
                for label, n in counts.items() if int(n) > 0
            ),
            key=lambda m: (-m["count"], m["name"]),
        )
        count = int(summary.get("event_count") or 0)
        return {
            "days": days,
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
            "count": count,
            "moods": moods,
            # 认不出来的取值给一句**不下结论**的话。说「记录还不够多」是在替
            # 底层解释原因，而这一层并不知道原因。
            "trend": _TREND_WORDS.get(
                str(summary.get("trend")), "这段时间的变化，暂时说不上来。"
            ),
            # 底层已经筛过：只有**真的在建议做点什么**的那几句才在这里。
            "suggestions": [str(s) for s in (summary.get("safe_suggestions") or [])],
            #: 这一句是**隐私承诺**。原先自称版给家人读，成了
            #: 「您和无忧伴聊过的话不会出现在这里」——而家人不和无忧伴聊天，
            #: 一句承诺说给了错的人。
            "privacyNote": _voice(
                ctx,
                "这里只有心情的类别和变化。您和无忧伴聊过的话不会出现在这里。",
                "这里只有心情的类别和变化。老人和无忧伴聊过的话不会出现在这里。"),
            "message": (
                f"这 {days} 天里记下 {count} 次心情，最多的是"
                f"{moods[0]['name'] if moods else '说不上来'}。"
            ) if count else f"这 {days} 天里还没有记下心情。没有记录不等于不好，只是没有可说的。",
        }

    # ---- 我这几天怎么样 --------------------------------------------------------
    #
    # 底层是 `/v7/daily-report/{elder}` 与 `/v7/baseline/{elder}`。日报按设计是
    # 子女侧视图，但一份关于自己的报告不让本人看，与这个项目「过程透明」的立场相悖
    # ——`baseline_api.py` 顶上就是这么写的，它也确实放行了老人本人。缺的只是入口。

    _VERDICT_WORDS = {
        "typical": "和平常一样",
        "notice": "和平常有点不一样",
        "marked": "和平常差得比较多",
        "unknown": "今天还没有记录",
        "pending": "现在还说不准",
    }
    #: verdict -> 色调。`family3.js` 的 `say()` 认得的就是这三档
    #: （空 = 中性底色，`warning` / `bad` 在 `family3-wiring.css` 里各有一条）。
    #:
    #: `unknown`（今天还没有记录）给 `warning` 而不是中性：这一壳没有
    #: `common.js` 里那第三种「看得见但不喊」的色调。两害相权宁可让它看得见
    #: ——「今天还没有记录」本身就是要人看一眼的事。
    _VERDICT_TONES = {
        "typical": "",
        "notice": "warning",
        "marked": "bad",
        "unknown": "warning",
        "pending": "",
    }
    _ALERT_WORDS = {
        "push": "已经提醒家人看一眼。",
        "digest": "不单独打扰家人，会并进给家人的日报里。",
        "none": "今天不会因为这些打扰家人。",
    }

    @router.get("/daily-report")
    def my_daily_report(
        day: date | None = Query(default=None, description="默认今天（老人所在时区）"),
        ctx: AuthContext = Depends(_actor),
    ) -> AppDailyReport:
        """「我这几天怎么样」——他自己的常态，和今天差在哪儿。

        给的是**结构化的值**（平常几点 / 今天几点 / 一句中文判断），不是底层那几句
        `explanation`。那几句是写给子女的：「比**他**平常晚了 1 小时 40 分」——
        照搬到老人自己这一屏上人称就错了，而在这里改写人称同样不行
        （`其他` 会被改成 `其您`）。
        """
        elder = _elder_of(ctx)
        envelope = _v7_call(_V7_DAILY_REPORT, elder, day, ctx)
        snapshot = _v7_call(_V7_BASELINE, elder, day, ctx)
        report, alert = envelope.report, envelope.alert

        usual = {b.channel: b.center_text for b in snapshot.baselines}
        because = []
        if alert.baseline_deviated:
            #: 这一条进的是 `familyWillSeeBecause`——**字段名自己就说了
            #: 是给家人看的**，而句子却是自称版。
            because.append(_voice(ctx, "今天的作息和您平常不一样",
                                  "今天的作息和老人平常不一样"))
        if alert.errand_at_risk:
            because.append("有该办的事快要误了")
        errands = report.errands
        return {
            "day": report.day.isoformat(),
            "todayWord": _VERDICT_WORDS.get(report.overall.value, "说不准"),
            "todayTone": _VERDICT_TONES.get(report.overall.value, "warning"),
            "established": snapshot.established,
            "observedDays": snapshot.observed_days,
            "channels": [
                {
                    "name": d.label,
                    "usual": usual.get(d.channel) or d.center_text,
                    "today": d.observed_text,
                    "word": _VERDICT_WORDS.get(d.verdict.value, "说不准"),
                }
                for d in snapshot.deviations
            ],
            "errands": {
                "dueToday": errands.due_today,
                "done": errands.completed,
                "waitingFamily": errands.awaiting_family,
                "overdue": errands.overdue,
                "lines": list(errands.lines),
            },
            "familyWillSee": _ALERT_WORDS.get(
                alert.channel, "家人那边这次没有给出处理方式。"
            ),
            "familyWillSeeBecause": because,
            "environmentNote": report.environment_note,
            "privacyNote": report.privacy_note,
            "message": _voice(
                ctx,
                f"优活已经记了您 {snapshot.observed_days} 天的作息，"
                "还在熟悉您的规律，暂时不下结论。",
                f"优活已经记了老人 {snapshot.observed_days} 天的作息，"
                "还在熟悉她的规律，暂时不下结论。"
            ) if not snapshot.established else (
                # 判断词自带主语（「今天还没有记录」），前面**不能**再加一个「今天」
                # ——拼出来是「今天今天还没有记录」。五个取值里有两个是这样，
                # 而另外三个拼起来完全通顺，所以只看一眼演示数据是发现不了的。
                f"{_VERDICT_WORDS.get(report.overall.value, '说不准')}。"
                f"该办的 {errands.due_today} 件里办好了 {errands.completed} 件。"
            ),
        }

    return router
