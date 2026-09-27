"""主动服务的曲柄：服务器自己每隔 N 秒敲一次调度器。

## 为什么要有它

KNOWN_ISSUES 第 297 条量过：提前提醒（24h / 12h / 1h 三级、幂等去重）这台机器
是好的，缺的只有「谁来敲」——`SchedulerService.tick` 的调用方只有一个名字里
写着 demo 的端点和测试。第 297 条后来的解法是让桌面小优在本机定时敲，但它连的
是**本机**后端；队友在手机上打开的公网那一台，没有任何人在敲。
官方三大核心之一「主动服务」，在真正的演示面上是空的。

## 三条规矩

1. **默认关。** 只认显式的 `YOUHUO_SCHEDULER_INTERVAL_S`（>0 才开）。巡检闸门
   （`check_dead_controls` 这类「点一下，看屏幕变没变」的仪器）要是撞上后台
   定时发出的通知，会把一个死控件量成「有反应」——探针的副作用满足了判据。
2. **掉了要看得见。** `/health` 报 `enabled / interval_s / last_tick_at / ticks /
   errors / last_error`。`last_tick_at` 不再往前走，就是它死了。
3. **不往审计链灌水。** 每分钟一条 `SCHEDULER_TICK` 一天就是 1440 行，而这个
   仓库已经四次栽在「真事件被挤出有限窗口」上。发出去的提醒本身有通知记录，
   这里只把累计数放在内存里给 `/health` 看。
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any


class ProactiveLoop:
    MIN_INTERVAL_S = 5.0

    def __init__(self, engine: Any, interval_s: float) -> None:
        self.engine = engine
        self.interval_s = float(interval_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.ticks = 0
        self.errors = 0
        self.last_tick_at: datetime | None = None
        self.last_result: dict[str, int] | None = None
        self.last_error: str | None = None
        self.totals: dict[str, int] = {}

    @classmethod
    def from_env(cls, engine: Any) -> "ProactiveLoop":
        raw = os.getenv("YOUHUO_SCHEDULER_INTERVAL_S", "").strip()
        try:
            interval = float(raw) if raw else 0.0
        except ValueError:
            interval = 0.0
        if interval > 0:
            interval = max(cls.MIN_INTERVAL_S, interval)
        return cls(engine, interval)

    @property
    def enabled(self) -> bool:
        return self.interval_s > 0

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="youhuo-proactive", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)

    def _run(self) -> None:
        # 先等一个周期再敲：启动那一刻种子还在写，别抢。
        while not self._stop.wait(self.interval_s):
            self.tick_once()

    def tick_once(self) -> dict[str, int] | None:
        """敲一次。系统身份、不限家庭——和 `engine.scheduler_tick` 用系统令牌时一样。"""
        try:
            now = self.engine.services.clock.now()
            with self.engine._lock:
                result = self.engine.services.scheduler.tick(
                    self.engine.db, self.engine.services.notification, now, family_id=None,
                )
        except Exception as exc:  # 一次失败不许让线程死掉；记下来给 /health 看
            with self._lock:
                self.errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return None
        with self._lock:
            self.ticks += 1
            self.last_tick_at = now
            self.last_result = dict(result)
            for key, value in result.items():
                self.totals[key] = self.totals.get(key, 0) + int(value)
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "interval_s": self.interval_s if self.enabled else None,
                "running": self._thread is not None and self._thread.is_alive(),
                "ticks": self.ticks,
                "errors": self.errors,
                "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
                "last_result": self.last_result,
                "totals": dict(self.totals),
                "last_error": self.last_error,
            }
