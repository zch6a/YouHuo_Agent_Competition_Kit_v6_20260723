"""个性化基线、生活日报与兜底预警的 HTTP 接口。

四个端点，对应设计稿的四个核心创新点：

    POST /v7/environment/samples      ① 环境读数上报（设备推给我们，不主动采集）
    GET  /v7/baseline/{elder_id}      ① 他自己的常态 vs 今天
    GET  /v7/care/{elder_id}          ①③ 基于基线与环境的关怀动作
    GET  /v7/daily-report/{elder_id}  ②④ 给子女的生活日报，含推送决定

权限：**只有老人和家属两种身份**能访问，老人只能看自己的，家属只能看本家庭的。
日报是家属侧视图，但老人本人也能看——一份关于自己的报告不让本人看，与这个项目
"过程透明"的立场相悖。SYSTEM 身份被显式拒绝：它存在的意义是审计归属，不是一个
可以代表任何人读数据的账号。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from .baseline_models import (
    AlertDecision,
    BaselineSnapshot,
    CareAction,
    DailyReport,
    EnvironmentSample,
)
from .baseline_services import (
    BaselineAnalyzer,
    CareComposer,
    DailyReportBuilder,
    EnvironmentReader,
    ErrandFacts,
    FallbackAlerting,
)
from .baseline_store import BaselineStore
from .baseline_store import DEFAULT_TIMEZONE, _zone
from .database import Database, utcnow


def _local_today(now: datetime) -> date:
    """"今天"必须是老人所在时区的今天。

    用 UTC 的今天，在 UTC+8 就等于把一天切在早上八点：老人 06:00 起床会被算进
    "昨天"，而日报在早上七点打开时会说"今天还没有记录"。
    """
    return now.astimezone(_zone(DEFAULT_TIMEZONE)).date()


#: 可以回看多久。基线窗口本身只有 30 天，再往前查不到任何东西。
MAX_LOOKBACK_DAYS = 365


def _validated_day(day: date | None, today: date) -> date:
    """把 `day` 收进一个合理区间。

    不做这件事的后果是 500 而不是 400：`observations()` 里要算
    `today + timedelta(days=2)` 和 `today - timedelta(days=31)`，再送进
    `iso()` 做 `astimezone(UTC)`。`day=9999-12-31` 溢出、`day=0001-01-01` 也溢出，
    三个 GET 端点同时崩，而 `day` 就写在公开的 `/openapi.json` 里。前端把参数拼错
    一次（`?day=a&day=b` 时 FastAPI 取最后一个）同样能触发。
    """
    if day is None:
        return today
    if day > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能查询未来的日期。",
        )
    if day < today - timedelta(days=MAX_LOOKBACK_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"最多回看 {MAX_LOOKBACK_DAYS} 天。",
        )
    return day
from .models import ActorRole, AuthContext


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentAck(StrictModel):
    sample_id: str
    accepted: bool
    note: str


class DailyReportEnvelope(StrictModel):
    """日报 + 这份日报要不要现在就推给子女。

    两者放在一起返回，是因为它们必须由同一份快照得出。分成两个端点调用两次，就会
    出现"日报说一切正常、推送说赶紧回家"这种自相矛盾的情况——而那正是子女再也不
    信任这个 App 的开始。
    """

    report: DailyReport
    alert: AlertDecision


def build_baseline_router(
    db: Database,
    store: BaselineStore,
    current_actor: Callable[..., AuthContext],
    errand_facts: Callable[[str, str, date], ErrandFacts],
) -> APIRouter:
    router = APIRouter(prefix="/v7", tags=["v7 个性化基线与生活日报"])

    def require_elder_access(actor: AuthContext, elder_id: str) -> None:
        # 白名单，不是黑名单。原来只对 ELDER 做主体收敛，于是第三种角色 SYSTEM
        # 落进下面那条家庭检查后一路放行——`POST /v2/auth/demo {"actor_id":
        # "system-demo"}` 拿到的 token 能读整份生活日报、也能写环境读数。
        # SYSTEM 存在的意义是审计归属，不是一个可以代表任何人读数据的身份。
        if actor.role not in (ActorRole.ELDER, ActorRole.FAMILY):
            raise HTTPException(status_code=403, detail="该身份不能访问生活基线数据。")
        if actor.role == ActorRole.ELDER and actor.actor_id != elder_id:
            raise HTTPException(status_code=403, detail="只能访问自己的生活基线数据。")
        if not db.actor_in_family(elder_id, actor.family_id, ActorRole.ELDER.value):
            raise HTTPException(status_code=403, detail="老人账户不属于当前家庭。")

    def _snapshot(actor: AuthContext, elder_id: str, day: date) -> BaselineSnapshot:
        observations = store.observations(
            family_id=actor.family_id, elder_id=elder_id, today=day
        )
        local_now = utcnow().astimezone(_zone(DEFAULT_TIMEZONE))
        # 只有在看"今天"时才需要压制未过完的通道；回看历史某一天时那一天已经完整。
        now_minutes = (
            local_now.hour * 60.0 + local_now.minute
            if day == local_now.date() else None
        )
        return BaselineAnalyzer.snapshot(
            elder_id=elder_id,
            observations=observations,
            today_values=store.today_values(observations, day),
            today=day,
            now_minutes=now_minutes,
        )

    def _environment(actor: AuthContext, elder_id: str, now: datetime):
        sample = store.latest_environment(family_id=actor.family_id, elder_id=elder_id)
        return EnvironmentReader.read(sample, now=now)

    @router.post(
        "/environment/samples",
        response_model=EnvironmentAck,
        status_code=status.HTTP_201_CREATED,
    )
    def record_environment(
        payload: EnvironmentSample,
        actor: AuthContext = Depends(current_actor),
    ) -> EnvironmentAck:
        """接收一次室内环境读数。

        刻意只收温度、湿度、光照——没有图像。设计稿把这一点写进了产品定位：
        家庭空间不是公共区域，长期视频监控会让老人产生心理压力。
        """
        require_elder_access(actor, payload.elder_id)
        if payload.temperature_c is None and payload.humidity_pct is None and payload.lux is None:
            raise HTTPException(status_code=400, detail="至少需要温度、湿度或光照中的一项。")
        sample_id = store.record_environment(family_id=actor.family_id, sample=payload)
        db.append_audit(
            family_id=actor.family_id,
            actor_id=actor.actor_id,
            event_type="environment.sample",
            entity_id=sample_id,
            # 只留元数据，不留读数本身——审计链是给"谁在何时做了什么"用的，
            # 把每一条温湿度都塞进去只会把真正的关键操作淹掉。
            payload={"elder_id": payload.elder_id, "source": payload.source},
        )
        return EnvironmentAck(
            sample_id=sample_id,
            accepted=True,
            note="已记录。本端点不接收任何图像。",
        )

    @router.get("/baseline/{elder_id}", response_model=BaselineSnapshot)
    def get_baseline(
        elder_id: str,
        day: date | None = Query(default=None, description="默认今天（老人所在时区）"),
        actor: AuthContext = Depends(current_actor),
    ) -> BaselineSnapshot:
        """这位老人**自己的**常态，以及今天偏离了多少。"""
        require_elder_access(actor, elder_id)
        return _snapshot(actor, elder_id, _validated_day(day, _local_today(utcnow())))

    @router.get("/care/{elder_id}", response_model=CareAction)
    def get_care(
        elder_id: str,
        day: date | None = Query(default=None, description="默认今天（老人所在时区）"),
        actor: AuthContext = Depends(current_actor),
    ) -> CareAction:
        """基于基线与此刻环境生成的关怀动作：说什么、要不要调日程、灯光建议。"""
        require_elder_access(actor, elder_id)
        now = utcnow()
        snapshot = _snapshot(actor, elder_id, _validated_day(day, _local_today(now)))
        return CareComposer.compose(
            snapshot=snapshot,
            environment=_environment(actor, elder_id, now),
            now=now,
        )

    @router.get("/daily-report/{elder_id}", response_model=DailyReportEnvelope)
    def get_daily_report(
        elder_id: str,
        day: date | None = Query(default=None, description="默认今天（老人所在时区）"),
        actor: AuthContext = Depends(current_actor),
    ) -> DailyReportEnvelope:
        """给子女的生活日报，以及"现在要不要打扰您"的决定。"""
        require_elder_access(actor, elder_id)
        now = utcnow()
        target = _validated_day(day, _local_today(now))
        snapshot = _snapshot(actor, elder_id, target)
        errands = errand_facts(actor.family_id, elder_id, target)
        report = DailyReportBuilder.build(
            snapshot=snapshot,
            errands=errands,
            environment=_environment(actor, elder_id, now),
            generated_at=now,
        )
        alert = FallbackAlerting.decide(snapshot=snapshot, errands=errands)
        return DailyReportEnvelope(report=report, alert=alert)

    return router
