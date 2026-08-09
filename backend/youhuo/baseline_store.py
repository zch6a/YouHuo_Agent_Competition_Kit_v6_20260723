"""基线的持久化：环境读数入库，以及从**已有**事件流里推导观测值。

值得说明的是这里**没有**新增行为采集。起床、就寝、外出、服药、说话这五个通道全部
从项目里已经存在的表推导出来：

    activity_events_v4   → 起床（当天首次活动）、就寝（当天末次活动）
    location_events_v4   → 外出次数
    medication_doses_v4  → 服药时刻
    sessions             → 与优活说话的次数

也就是说，个性化基线不要求老人多做任何一件事，也不要求家里多装一个摄像头。设计稿
"看不见，但能感知"落到工程上就是这句话。唯一新增的输入是环境读数，而它是一个**上报
端点**——设备推给我们，我们不主动采集，没有设备时整套机制照常工作。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: 目标市场。真实产品应当按老人档案存各自的时区；在拿到那份数据之前，用一个明确
#: 写出来的默认值，好过默默地用 UTC——后者会把每个人的"一天"切在早上八点。
DEFAULT_TIMEZONE = "Asia/Shanghai"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # 没有 tz 数据库时退回 UTC，并且是显式的：分天会偏，但不会崩。
        return ZoneInfo("UTC")

from .baseline import Channel, Observation, minutes_of_day
from .baseline_models import EnvironmentSample
from .baseline_services import ErrandFacts
from .database import Database, iso, utcnow
from .utils import new_id


class BaselineStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db._conn

    def _init_schema(self) -> None:
        with self.db._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS environment_samples_v7(
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL REFERENCES families(id),
                    elder_id TEXT NOT NULL REFERENCES actors(id),
                    temperature_c REAL,
                    humidity_pct REAL,
                    lux REAL,
                    occurred_at TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_env_elder
                    ON environment_samples_v7(family_id,elder_id,occurred_at);
                """
            )
            self.conn.commit()

    # --- 环境 ---------------------------------------------------------------

    def record_environment(self, *, family_id: str, sample: EnvironmentSample) -> str:
        sample_id = new_id("env")
        with self.db._lock:
            self.conn.execute(
                """INSERT INTO environment_samples_v7
                   (id,family_id,elder_id,temperature_c,humidity_pct,lux,occurred_at,source)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (sample_id, family_id, sample.elder_id, sample.temperature_c,
                 sample.humidity_pct, sample.lux, iso(sample.occurred_at), sample.source),
            )
            self.conn.commit()
        return sample_id

    def latest_environment(self, *, family_id: str, elder_id: str) -> EnvironmentSample | None:
        with self.db._lock:
            row = self.conn.execute(
                """SELECT elder_id,temperature_c,humidity_pct,lux,occurred_at,source
                   FROM environment_samples_v7
                   WHERE family_id=? AND elder_id=?
                   ORDER BY occurred_at DESC LIMIT 1""",
                (family_id, elder_id),
            ).fetchone()
        if row is None:
            return None
        return EnvironmentSample(
            elder_id=row["elder_id"],
            temperature_c=row["temperature_c"],
            humidity_pct=row["humidity_pct"],
            lux=row["lux"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            source=row["source"],
        )

    # --- 从既有事件流推导观测 -----------------------------------------------

    def observations(
        self,
        *,
        family_id: str,
        elder_id: str,
        today: date,
        window_days: int = 30,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> list[Observation]:
        """窗口内每一天、每个通道的观测值，**按老人所在时区**分天。

        时区不是可选的讲究，是正确性问题。时间戳按 UTC 存，但"一天"和"几点起床"
        都是本地概念。在 UTC+8 直接用 UTC 分天会有两个后果：

        * 早上 6:00 起床（北京）= 前一天 22:00 UTC，于是落进**昨天**那一格；
        * 一天的分界线变成北京时间早上 8 点，正好切在老人起床和吃早饭中间。

        结果是每一天的"起床时刻"其实是前一天的晚间活动，基线学到的是一个不存在的
        作息。这类错误不会报错，只会安静地给出很有说服力的错误结论。

        所以这里把时间戳全部取回来，在 Python 里换算到本地时区再分桶——SQLite 的
        `substr(occurred_at,1,10)` 做不了时区换算，而它正是原来出错的地方。
        """
        zone = _zone(timezone)
        # 窗口两端各放宽一天，避免边界那天因为时区偏移被截掉半截。
        since = iso(datetime.combine(today - timedelta(days=window_days + 1), datetime.min.time()))
        until = iso(datetime.combine(today + timedelta(days=2), datetime.min.time()))
        lower = today - timedelta(days=window_days)

        def local(stamp: str) -> datetime:
            moment = datetime.fromisoformat(stamp)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return moment.astimezone(zone)

        out: list[Observation] = []
        # 逐通道先按本地日聚合，再产出观测。
        first_last: dict[date, list[datetime]] = {}
        outings: dict[date, int] = {}
        doses: dict[date, list[datetime]] = {}
        talks: dict[date, int] = {}

        with self.db._lock:
            for row in self.conn.execute(
                """SELECT occurred_at FROM activity_events_v4
                   WHERE family_id=? AND elder_id=? AND occurred_at>=? AND occurred_at<?""",
                (family_id, elder_id, since, until),
            ):
                moment = local(row["occurred_at"])
                first_last.setdefault(moment.date(), []).append(moment)

            for row in self.conn.execute(
                """SELECT occurred_at FROM location_events_v4
                   WHERE family_id=? AND elder_id=? AND occurred_at>=? AND occurred_at<?""",
                (family_id, elder_id, since, until),
            ):
                day = local(row["occurred_at"]).date()
                outings[day] = outings.get(day, 0) + 1

            # medication_doses_v4 里没有 elder_id/family_id，要经 medication_plans_v4
            # 关联；时间列是 recorded_at（实际记录）而不是 scheduled_at（计划）——
            # 基线要学的是这个人真实的服药习惯，不是他曾经设过的闹钟。
            # 只取 status='taken'：漏服和跳过不该被算成"他习惯这个点吃药"。
            for row in self.conn.execute(
                """SELECT d.recorded_at AS at FROM medication_doses_v4 d
                   JOIN medication_plans_v4 p ON p.id = d.plan_id
                   WHERE p.family_id=? AND p.elder_id=? AND d.status='taken'
                     AND d.recorded_at>=? AND d.recorded_at<?""",
                (family_id, elder_id, since, until),
            ):
                moment = local(row["at"])
                doses.setdefault(moment.date(), []).append(moment)

            # 说话：会话条数。只数条数，不碰任何内容。
            for row in self.conn.execute(
                """SELECT created_at FROM sessions
                   WHERE family_id=? AND elder_id=? AND created_at>=? AND created_at<?""",
                (family_id, elder_id, since, until),
            ):
                day = local(row["created_at"]).date()
                talks[day] = talks.get(day, 0) + 1

        def keep(day: date) -> bool:
            return lower <= day <= today

        for day, moments in first_last.items():
            if not keep(day):
                continue
            out.append(Observation(day, Channel.WAKE, minutes_of_day(min(moments))))
            out.append(Observation(day, Channel.SLEEP, minutes_of_day(max(moments))))
        for day, count in outings.items():
            if keep(day):
                out.append(Observation(day, Channel.OUTING, float(count)))
        for day, moments in doses.items():
            if keep(day):
                out.append(Observation(day, Channel.MEDICATION, minutes_of_day(min(moments))))
        for day, count in talks.items():
            if keep(day):
                out.append(Observation(day, Channel.CONVERSATION, float(count)))
        return out

    # --- ② 日报需要的"今天该办的事" -----------------------------------------

    def errand_facts(self, family_id: str, elder_id: str, day: date) -> ErrandFacts:
        """今天的提醒与任务办得怎么样。

        提醒和任务分开数是有原因的：提醒是"该做一件事"，任务是"优活正在替他做一件
        事"。子女关心的"有没有事情要误"两者都算，但"在等您确认"只可能来自任务——
        提醒不需要家属批准。
        """
        start = iso(datetime.combine(day, datetime.min.time()))
        end = iso(datetime.combine(day + timedelta(days=1), datetime.min.time()))
        lines: list[str] = []

        with self.db._lock:
            reminders = self.conn.execute(
                """SELECT title,status,due_at FROM reminders
                   WHERE family_id=? AND elder_id=? AND due_at>=? AND due_at<?
                   ORDER BY due_at""",
                (family_id, elder_id, start, end),
            ).fetchall()
            awaiting = self.conn.execute(
                """SELECT COUNT(*) AS n FROM tasks
                   WHERE family_id=? AND elder_id=? AND status='awaiting_family_approval'""",
                (family_id, elder_id),
            ).fetchone()["n"]

        due_today = len(reminders)
        completed = 0
        overdue = 0
        now_iso = iso(datetime.combine(day + timedelta(days=1), datetime.min.time()))
        for row in reminders:
            if row["status"] == "completed":
                completed += 1
                lines.append(f"{row['title']}：已完成。")
            elif row["due_at"] < now_iso and row["status"] != "cancelled":
                overdue += 1
                lines.append(f"{row['title']}：还没办。")
            else:
                lines.append(f"{row['title']}：待办。")
        if awaiting:
            lines.append(f"有 {awaiting} 项在等家属确认。")

        return ErrandFacts(
            due_today=due_today,
            completed=completed,
            awaiting_family=int(awaiting),
            overdue=overdue,
            lines=tuple(lines),
        )

    # --- 演示数据 -----------------------------------------------------------

    def seed_demo_for(self, suffix: str = "demo", *, today: date | None = None, days: int = 21) -> int:
        """按项目既有的 suffix 约定播种，供默认演示家庭和每位访客的独立沙箱共用。

        与 `Database.seed_demo` / `V4FeatureStore.seed_demo` 保持同一种调用形态，
        否则新增一户人家时总会漏掉其中一个。
        """
        from .database import DemoIdentities

        ids = DemoIdentities.for_suffix(suffix)
        return self.seed_demo(
            family_id=ids.family_id,
            elder_id=ids.elder_id,
            # 本地的今天，与读取端保持同一个定义。
            today=today or utcnow().astimezone(_zone(DEFAULT_TIMEZONE)).date(),
            days=days,
        )

    def seed_demo(self, *, family_id: str, elder_id: str, today: date, days: int = 21) -> int:
        """给演示家庭铺一段可信的作息历史。

        没有历史，基线就诚实地说"还在熟悉他的生活规律"——这对真实用户是对的，但
        评委在演示里会什么都看不到。所以这里补一段**确定性**的历史：一位早上 6:05
        前后起床、21:30 前后就寝、每天出门两趟、8:00 服药的老人。

        没有随机数。偏移量由天数索引算出，所以同一天跑两次得到同一份数据，演示
        可复现，测试也能对着具体数字断言。刻意留了几天小幅波动，否则 MAD 会是 0，
        看到的就是一个"完美"到不真实的基线。

        返回写入的事件条数。已存在则跳过（幂等），重复调用不会把基线越铺越密。
        """
        with self.db._lock:
            existing = self.conn.execute(
                "SELECT COUNT(*) AS n FROM activity_events_v4 WHERE family_id=? AND elder_id=?",
                (family_id, elder_id),
            ).fetchone()["n"]
        if existing:
            return 0

        # 每天的小幅偏移（分钟），循环使用。真人不会分秒不差，但也不会天天乱来。
        wake_jitter = [0, 8, -6, 12, 3, -9, 5]
        sleep_jitter = [0, -11, 7, 4, -5, 14, -3]
        outings = [2, 2, 3, 2, 1, 2, 3]

        # 全部按**本地时间**构造，再由 iso() 转成 UTC 存库。
        # 直接写 naive 的 06:05 会被当作 06:05 UTC，也就是北京时间下午两点——
        # 演示里这位老人会显得每天下午才起床。
        zone = _zone(DEFAULT_TIMEZONE)

        def at_local(day: date, hours: int, minutes: int) -> datetime:
            return datetime.combine(day, datetime.min.time(), tzinfo=zone) + timedelta(
                hours=hours, minutes=minutes
            )

        # 一个演示用的服药计划，好让"服药"通道也有基线。真实部署里这行数据来自
        # 老人或家属自己建的计划，不会走这条路径。
        plan_id = new_id("plan")
        with self.db._lock:
            has_plan = self.conn.execute(
                "SELECT id FROM medication_plans_v4 WHERE family_id=? AND elder_id=? LIMIT 1",
                (family_id, elder_id),
            ).fetchone()
            if has_plan:
                plan_id = has_plan["id"]
            else:
                stamp = iso(datetime.combine(today - timedelta(days=days), datetime.min.time()))
                self.conn.execute(
                    """INSERT INTO medication_plans_v4(
                           id,family_id,elder_id,display_name,normalized_name,dose_text,
                           times_json,start_date,end_date,stock_units,units_per_dose,
                           source,active,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (plan_id, family_id, elder_id, "降压药", "降压药", "一次一片",
                     '["08:00"]', (today - timedelta(days=days)).isoformat(), None,
                     60.0, 1.0, "demo_seed", 1, stamp, stamp),
                )

        # 今天只铺到"现在"为止。
        #
        # 把今天一整天都铺上，等于在上午十点声称这位老人晚上九点半已经睡了——一条
        # 未来的活动记录。它不只是难看：无交互预警取 MAX(occurred_at)，未来的事件
        # 会让"多久没动静了"永远算成负数，预警从此不再触发。这正是本轮已经踩过
        # 一次的那类错误。
        horizon = utcnow()

        written = 0
        with self.db._lock:
            # 从 0 开始：今天也要有记录。
            #
            # 只铺过去、不铺今天，日报就永远停在"今天还没有记录"——这在真实场景里
            # 是对的（凌晨确实还没起床），但在演示里意味着评委看到的每一栏都是
            # "还不好说"，而这恰恰是要展示的功能。今天铺成一个**正常**的一天，
            # 想看偏离时由界面上的按钮真实地补一条晚起记录。
            for index in range(0, days + 1):
                day = today - timedelta(days=index)
                wake = at_local(day, 6, 5 + wake_jitter[index % 7])
                sleep = at_local(day, 21, 30 + sleep_jitter[index % 7])
                for moment, kind in ((wake, "morning_activity"), (sleep, "evening_activity")):
                    if moment > horizon:
                        continue
                    self.conn.execute(
                        """INSERT INTO activity_events_v4(id,family_id,elder_id,kind,occurred_at,metadata_json)
                           VALUES(?,?,?,?,?,?)""",
                        (new_id("act"), family_id, elder_id, kind, iso(moment), "{}"),
                    )
                    written += 1
                for trip in range(outings[index % 7]):
                    moment = at_local(day, 9 + trip * 4, 20)
                    if moment > horizon:
                        continue
                    self.conn.execute(
                        """INSERT INTO location_events_v4
                           (id,family_id,elder_id,latitude,longitude,accuracy_m,occurred_at,source)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (new_id("loc"), family_id, elder_id, 39.9042, 116.3974, 25.0,
                         iso(moment), "demo_seed"),
                    )
                    written += 1

                # 服药：8:00 前后，只记实际服下的。
                taken = at_local(day, 8, wake_jitter[index % 7])
                scheduled = at_local(day, 8, 0)
                if taken > horizon:
                    continue
                self.conn.execute(
                    """INSERT OR IGNORE INTO medication_doses_v4
                       (id,plan_id,scheduled_at,status,recorded_at,note)
                       VALUES(?,?,?,?,?,?)""",
                    (new_id("dose"), plan_id, iso(scheduled), "taken", iso(taken), ""),
                )
                written += 1
            self.conn.commit()
        return written

    @staticmethod
    def today_values(observations: list[Observation], today: date) -> dict[Channel, float | None]:
        """今天各通道的值。

        没有记录的通道给 None 而不是 0：外出 0 次和"今天还没有位置数据"是两回事，
        在养老场景里把后者当成前者会得出完全相反的结论。
        """
        values: dict[Channel, float | None] = {c: None for c in Channel}
        for observation in observations:
            if observation.day == today:
                values[observation.channel] = observation.value
        return values
