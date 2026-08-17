from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .models import (
    ActorRole,
    AuditEvent,
    AuthContext,
    NotificationRecord,
    ReminderRecord,
    ReminderStatus,
    RiskLevel,
    SessionState,
    TaskRecord,
    TaskStatus,
    TaskType,
)
from .utils import canonical_json, local_now, local_zone


class IdempotencyConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoIdentities:
    """The four actor ids and the family id of one seeded demo household."""

    suffix: str
    family_id: str
    elder_id: str
    daughter_id: str
    son_id: str
    system_id: str

    #: Visitor suffixes are generated, so constrain them: they become primary keys.
    _SAFE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

    @classmethod
    def for_suffix(cls, suffix: str) -> DemoIdentities:
        if not cls._SAFE.match(suffix):
            raise ValueError("演示家庭标识只能包含小写字母、数字和连字符。")
        return cls(
            suffix=suffix,
            family_id=f"fam-{suffix}",
            elder_id=f"elder-{suffix}",
            daughter_id=f"daughter-{suffix}",
            son_id=f"son-{suffix}",
            system_id=f"system-{suffix}",
        )


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._audit_key = self._load_or_create_audit_key()
        self._init_schema()

    def _load_or_create_audit_key(self) -> bytes:
        explicit = os.getenv("YOUHUO_AUDIT_KEY")
        if explicit:
            return hashlib.sha256(explicit.encode("utf-8")).digest()
        if self.path == ":memory:":
            return secrets.token_bytes(32)
        db_path = Path(self.path)
        key_path = db_path.with_suffix(db_path.suffix + ".audit.key")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            raw = key_path.read_bytes()
            if len(raw) != 32:
                raise RuntimeError(f"invalid audit key file: {key_path}")
            return raw
        raw = secrets.token_bytes(32)
        key_path.write_bytes(raw)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return raw

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('schema_version','3');

            CREATE TABLE IF NOT EXISTS families(
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actors(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                role TEXT NOT NULL CHECK(role IN ('elder','family','system')),
                display_name TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_actors_family_role ON actors(family_id,role);

            CREATE TABLE IF NOT EXISTS auth_tokens(
                token_hash TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL REFERENCES actors(id),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_actor ON auth_tokens(actor_id,expires_at);

            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                mode TEXT NOT NULL,
                active_task_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                risk_level INTEGER NOT NULL,
                slots_json TEXT NOT NULL,
                semantic_key TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                approval_digest TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deferred_topics_json TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_family_status ON tasks(family_id,status);
            CREATE INDEX IF NOT EXISTS idx_tasks_semantic ON tasks(family_id,semantic_key);

            CREATE TABLE IF NOT EXISTS audit_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                entity_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_audit_family_id ON audit_events(family_id,id);

            CREATE TABLE IF NOT EXISTS idempotency(
                scope TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(scope,request_id)
            );

            CREATE TABLE IF NOT EXISTS bills(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                bill_type TEXT NOT NULL,
                period TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                due_date TEXT NOT NULL,
                paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN (0,1)),
                paid_at TEXT,
                UNIQUE(family_id,bill_type,period)
            );

            CREATE TABLE IF NOT EXISTS appointments(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                hospital TEXT NOT NULL,
                department TEXT NOT NULL,
                doctor TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(elder_id,hospital,department,appointment_date,appointment_time)
            );

            CREATE TABLE IF NOT EXISTS reminders(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                escalation_after_minutes INTEGER NOT NULL DEFAULT 30,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                created_by TEXT NOT NULL REFERENCES actors(id),
                created_at TEXT NOT NULL,
                notified_at TEXT,
                acknowledged_at TEXT,
                completed_at TEXT,
                escalated_at TEXT,
                UNIQUE(elder_id,title,due_at)
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status,due_at);

            -- One row per (reminder, lead time) so the T-24h/T-12h/T-1h ladder in
            -- the design brief fires exactly once even if the scheduler ticks often.
            CREATE TABLE IF NOT EXISTS reminder_advance_notices(
                reminder_id TEXT NOT NULL REFERENCES reminders(id),
                lead_minutes INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY(reminder_id,lead_minutes)
            );

            -- Observed evidence of how well this elder is following the
            -- conversation. Only outcome labels are stored: no utterance text,
            -- so the comprehension model can never leak what was said.
            CREATE TABLE IF NOT EXISTS comprehension_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                task_id TEXT,
                signal TEXT NOT NULL,
                field_name TEXT,
                attempts INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comprehension_elder
                ON comprehension_events(family_id,elder_id,id);

            CREATE TABLE IF NOT EXISTS notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family_id TEXT NOT NULL REFERENCES families(id),
                recipient_role TEXT NOT NULL CHECK(recipient_role IN ('elder','family','system')),
                event_type TEXT NOT NULL,
                entity_id TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_family_role ON notifications(family_id,recipient_role,id);

            CREATE TABLE IF NOT EXISTS memory_items(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                memory_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                sensitivity TEXT NOT NULL CHECK(sensitivity IN ('preference','personal','sensitive')),
                scope TEXT NOT NULL CHECK(scope IN ('private','family_summary','family_shared')),
                purpose TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('proposed','active','revoked','expired')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consent_actor_id TEXT,
                UNIQUE(elder_id,memory_key,status)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_family_elder ON memory_items(family_id,elder_id,status);

            CREATE TABLE IF NOT EXISTS approval_votes(
                task_id TEXT NOT NULL REFERENCES tasks(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                decision TEXT NOT NULL CHECK(decision IN ('approve','reject')),
                approval_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(task_id,actor_id)
            );
            CREATE INDEX IF NOT EXISTS idx_approval_votes_task ON approval_votes(task_id,decision);
            """
        )
        self._migrate()

    def _migrate(self) -> None:
        """给已经存在的库补列。

        **这是这个仓库第一次做迁移**，所以写清楚为什么不能只改上面的建表语句：
        `CREATE TABLE IF NOT EXISTS` 对**已经存在**的表什么都不做。改了上面那段，
        新建的库有新列，而任何一个已经跑过的库（开发机、演示部署、竞赛机上那份）
        永远停在旧结构上——然后代码按新列去查，当场 `no such column`。
        这种缺陷只在"升级"路径上出现，全新环境里测不出来。

        用 `PRAGMA table_info` 判断，而不是 `try: ALTER except: pass`：
        后者会把真正的错误（磁盘满、库损坏）一起吞掉，变成一次静默的半迁移。
        """
        wanted = [
            # 紧急联系人的电话。此前 `actors` 只有 id/family_id/role/display_name，
            # 于是 `/api/v1/contacts` 只能回 `phone: null`，界面上写「还没有留电话」。
            # 号码是 PII：这一列**允许为空且默认为空**，不种任何演示号码——
            # 编一个出来，老人真按下去会拨错人。
            ("actors", "phone", "TEXT"),
        ]
        with self._lock:
            for table, column, decl in wanted:
                cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                if column in cols:
                    continue
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            self._conn.commit()

    def seed_demo(self, suffix: str = "demo") -> DemoIdentities:
        """Seed one self-contained demo family.

        Parameterised by suffix so a public deployment can give every visitor
        their own sandbox: family isolation is enforced on `family_id` throughout,
        so separate families cannot see each other's tasks, bills or audit trail.
        The default "demo" reproduces the original fixed ids exactly.
        """
        ids = DemoIdentities.for_suffix(suffix)
        now = utcnow()
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO families(id,display_name) VALUES (?,?)",
                (ids.family_id, "优活示范家庭"),
            )
            for actor_id, role, name in (
                # 名字跟着头像走。`app/art/png/avatar.png` 与
                # `profile_avatar_large.png` 是同一位老先生，而演示里这个名字
                # 会出现在「我的」「我的资料」和每一张凭证上——名字和照片对不上，
                # 是评委第一眼就会看到的东西。这套素材只有这一张人像，
                # 所以改名字，不是改图。
                (ids.elder_id, "elder", "王爷爷"),
                (ids.daughter_id, "family", "女儿"),
                (ids.son_id, "family", "儿子"),
                (ids.system_id, "system", "优活系统"),
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO actors(id,family_id,role,display_name) VALUES (?,?,?,?)",
                    (actor_id, ids.family_id, role, name),
                )
            for bill_id, bill_type, period, cents, due in [
                ("bill-water-2026-07", "水费", "2026-07", 6840, "2026-07-28"),
                ("bill-electric-2026-07", "电费", "2026-07", 12650, "2026-07-30"),
                ("bill-gas-2026-07", "燃气费", "2026-07", 5230, "2026-07-31"),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO bills(id,family_id,bill_type,period,amount_cents,due_date,paid) VALUES (?,?,?,?,?,?,0)",
                    (f"{bill_id}-{suffix}", ids.family_id, bill_type, period, cents, due),
                )
        if self.count_audit(ids.family_id) == 0:
            self.append_audit(
                ids.family_id, ids.system_id, "DEMO_SEEDED", None, {"at": iso(now), "schema": 3}
            )
        return ids

    #: 一次完整缴费的八拍，以及每一拍相对当天 08:00 的偏移（秒）。
    #:
    #: **偏移不是装饰。** 它们让事件在产生时就带真实间隔：
    #:
    #:     11:26:04 提出        11:27:02 老人确认金额    11:28:26 执行
    #:     11:26:16 核对账单    11:27:38 请家人确认      11:28:41 拿到回执
    #:     11:26:31 请复述      11:28:11 家人同意
    #:
    #: 八拍的类型必须是 `trust.js` 的 `RECEIPT_STEPS` 认得的那些，否则凭证会把它们
    #: 渲染成「系统留下一条记录」——那条兜底是给未来新增事件类型留的，不是给这里用的。
    _BILL_SCENARIO: tuple[tuple[int, str, str, dict[str, Any]], ...] = (
        (12364, "TASK_CREATED", "elder",
         {"task_type": "bill_payment", "risk": 3, "semantic_basis": "hybrid"}),
        # `attempts` 不是可选的：真实引擎写它（`engine.py:1302`），种子漏了它。
        #
        # 后果不是「少一个字段」，是**可信中心的凭证正文里印着「第 undefined 次通过」**
        # ——`trust.js` 的模板读 `p.attempts`，读到 undefined 就原样拼进中文里。
        # 那一行出现在一整页都在讲「这里每一条都可核验」的地方，而它躲过了每一道闸门
        # （对比度只读颜色，点击遍历只看有没有抛异常，截图看的是尺寸与溢出）。
        #
        # 渲染那一侧已经改成「不知道就不说这一句」，但种子仍然要补上：**演示数据的
        # 载荷形状必须和真实引擎一样**，否则演示验证过的东西和生产跑的不是一回事，
        # 这类偏差还会以别的形式再咬一次。
        (12376, "TEACH_BACK_VERIFIED", "system",
         {"expected": "68.40", "heard": "68.40", "attempts": 1}),
        (12391, "ELDER_CONFIRMED", "elder", {"amount_yuan": "68.40"}),
        (12422, "FAMILY_APPROVAL_RECORDED", "system", {"required": True}),
        (12458, "NOTIFICATION_CREATED", "system",
         {"recipient_role": "family", "event_type": "approval_required"}),
        (12491, "FAMILY_APPROVED_AND_EXECUTED", "daughter",
         {"amount_yuan": "68.40", "authority": "北京自来水公司"}),
        (12506, "NOTIFICATION_CREATED", "system",
         {"recipient_role": "elder", "event_type": "task_completed"}),
    )

    def seed_demo_scenario(self, ids: DemoIdentities, scenario: str) -> int:
        """按**语义**播一个场景，不是撒十几条散落的 INSERT。

        `normal` 状态那笔「已完成缴费」如果只写一行 `tasks.status='completed'`，
        到了 Audit 页就会出现「UI 看起来完成了，但证据链残缺」——而那一页的全部价值
        就是证据链。所以一次播完：任务记录 + 八拍审计事件，时间戳带真实间隔。

        幂等：任务 id 是确定的，已存在就直接返回 0。
        """
        if scenario != "completed_bill_payment":
            raise ValueError(f"没有这个场景：{scenario}")

        task_id = f"task-seed-bill-{ids.suffix}"
        with self.transaction() as conn:
            exists = conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
        if exists:
            return 0

        now = utcnow()
        base = datetime.combine(now.date(), dtime(8, 0), tzinfo=UTC)
        slots = {"bill_type": "水费", "period": "2026-07", "amount_cents": 6840}
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO tasks(id,family_id,elder_id,task_type,status,risk_level,
                       slots_json,semantic_key,version,approval_digest,created_at,updated_at,
                       deferred_topics_json,result_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, ids.family_id, ids.elder_id, "bill_payment", "completed", 3,
                 canonical_json(slots), f"bill_payment:水费:2026-07", 1,
                 self._event_hash(f"seed|{ids.suffix}|68.40")[:40],
                 iso(base + timedelta(seconds=12364)),
                 iso(base + timedelta(seconds=12506)),
                 canonical_json([]),
                 canonical_json({"paid": True, "authority": "北京自来水公司",
                                 "amount_yuan": "68.40"})),
            )

        actors = {"elder": ids.elder_id, "daughter": ids.daughter_id, "system": ids.system_id}
        for offset, event_type, who, payload in self._BILL_SCENARIO:
            self.append_audit(
                ids.family_id, actors[who], event_type, task_id,
                {**payload, "task_id": task_id},
                created_at=base + timedelta(seconds=offset),
            )
        return len(self._BILL_SCENARIO)

    def seed_demo_reminders(self, ids: DemoIdentities) -> int:
        """给演示家庭放三条待办，由女儿建立。

        **刻意不放在 `seed_demo()` 里。** 试过一次：`seed_demo` 是**测试也在用**的那个
        种子函数，往里塞待办当场红了 12 条——「取消」按名字找待办、裸「嗯」确认、
        访客隔离计数，全都依赖"这个家庭一开始没有待办"。所以单独一个方法，
        只从演示路径（`visitor_sandbox` 与启动时的默认家庭）调，且只在 `seed_history`
        打开时调；真实部署与 pytest 默认都不会碰到它。

        为什么需要：没有它，老人端首页第一屏永远写着「今天没有要办的事。」——而
        `/v2/auth/visitor` 给**每个浏览器**开一个全新家庭，所以那是每一位打开演示链接
        的人看到的第一屏（实测新访客 `/v2/reminders` 返回 0 条）。
        这和 `api.py` 给作息历史做回填的理由是同一条：演示家庭需要一段过去，
        才看得出产品在做什么。

        锚在「今天当地 08:00」而不是 `now`：同一天里反复调用要落在同一个 `due_at` 上，
        否则表上的 `UNIQUE(elder_id,title,due_at)` 挡不住重复，刷几次就堆出十几条。
        用相对偏移而不是绝对日期，是为了它在比赛当天不会变成过去时——那样首页又空了，
        只是这次以一种更难发现的方式。

        **当地**而不是 UTC：原先锚在 08:00 UTC，配上同样不换算的显示端，
        界面上看起来是对的（存 11:00 显示 11:00），但存下来的是 11:00 UTC——
        东八区的晚上七点。这一层内部自洽，跨出去就错：循环例程排出来的提醒
        存的是真实时刻，「每天早上八点」于是显示成 00:00。
        现在两端都按当地时区处理，**界面上的字符串和原来完全一样**，
        变的是它们背后指向的时刻。
        """
        now = utcnow()
        midnight = datetime.combine(local_now(now).date(), dtime(8, 0), tzinfo=local_zone())
        made = 0
        with self.transaction() as conn:
            for offset_h, title in ((3, "复诊前准备病历"),
                                    (6, "下午四点吃降压药"),
                                    (27, "明天上午去社区量血压")):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO reminders"
                    "(id,family_id,elder_id,title,due_at,escalation_after_minutes,"
                    " status,source,created_by,created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"rem-seed-{offset_h}-{ids.suffix}", ids.family_id, ids.elder_id, title,
                     iso(midnight + timedelta(hours=offset_h)), 60,
                     "scheduled", "family", ids.daughter_id, iso(now)),
                )
                made += cursor.rowcount or 0
        return made

    # --- actors/auth ---
    def actor(self, actor_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()

    def auth_context_for_actor(self, actor_id: str) -> AuthContext | None:
        row = self.actor(actor_id)
        if not row:
            return None
        return AuthContext(
            actor_id=row["id"], family_id=row["family_id"], role=ActorRole(row["role"]), display_name=row["display_name"]
        )

    def list_bills(self, family_id: str) -> list[sqlite3.Row]:
        """这个家庭的全部账单。

        原先没有这个方法，于是 `/api/v1` 只能暴露**一张写死的水费**
        （`app_api._WATER_BILL`）——而库里其实躺着三张（水费 68.40、电费 126.50、
        燃气费 52.30）。前端那张「我的账单」于是永远只有一件事可办。
        未付的排前面，同组按到期日——快到期的先看到。
        """
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM bills WHERE family_id=? ORDER BY paid ASC, due_date ASC",
                (family_id,),
            ).fetchall()

    def get_bill(self, bill_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()

    def list_appointments(self, family_id: str, elder_id: str | None = None) -> list[sqlite3.Row]:
        """就医安排。表和 `insert_appointment` 一直都在，**没有任何地方读它**。"""
        sql = "SELECT * FROM appointments WHERE family_id=?"
        args: list[Any] = [family_id]
        if elder_id:
            sql += " AND elder_id=?"
            args.append(elder_id)
        sql += " ORDER BY appointment_date ASC, appointment_time ASC"
        with self._lock:
            return self._conn.execute(sql, tuple(args)).fetchall()

    def mark_notification_read(self, notification_id: str, family_id: str, when: datetime) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE notifications SET read_at=? WHERE id=? AND family_id=? AND read_at IS NULL",
                (iso(when), notification_id, family_id),
            )
            return cur.rowcount > 0

    def first_audit_at(self, family_id: str) -> datetime | None:
        """这个家庭最早那条审计的时间——「优活陪伴您 N 天」的**真实**依据。

        `families` 表没有建档日期，所以此前 `/profile` 的 `days` 只能回 null。
        审计链的第一条就是这份记录的开端，那是真数据，不是编的。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(created_at) FROM audit_events WHERE family_id=?", (family_id,)
            ).fetchone()
        if not row or not row[0]:
            return None
        try:
            return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except ValueError:
            return None

    def list_actors(self, family_id: str) -> list[sqlite3.Row]:
        """一个家庭里的所有成员。

        原先只有按 id 单取的 `actor()`，于是「紧急联系人」这类要**列出家人**的界面
        无处取数，只能把 `elder-demo` / `daughter-demo` / `son-demo` 这几个 id
        写死在调用方——那等于把演示数据焊进产品代码，换一个家庭就全空。
        排序把老人自己放最后：这张表是给老人看的联系人，他不需要联系自己。
        """
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM actors WHERE family_id=? "
                "ORDER BY CASE role WHEN 'family' THEN 0 WHEN 'system' THEN 1 ELSE 2 END, display_name",
                (family_id,),
            ).fetchall()

    def update_reminder_fields(
        self, reminder_id: str, family_id: str, title: str, due_at: datetime
    ) -> bool:
        """改一条提醒的名字和时间。

        为什么不能「取消旧的再建一条」：`reminders` 上有
        `UNIQUE(elder_id,title,due_at)`，同名同时间会撞唯一键；而且那样会在审计里
        留下「取消 + 新建」两行，而实际发生的是**一件事**——把八点挪到九点。
        """
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE reminders SET title=?,due_at=? WHERE id=? AND family_id=? "
                "AND status='scheduled'",
                (title, iso(due_at), reminder_id, family_id),
            )
            return cur.rowcount > 0

    def get_appointment(self, appointment_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM appointments WHERE id=?", (appointment_id,)
            ).fetchone()

    def cancel_appointment(self, appointment_id: str, family_id: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE appointments SET status='cancelled' "
                "WHERE id=? AND family_id=? AND status!='cancelled'",
                (appointment_id, family_id),
            )
            return cur.rowcount > 0

    def set_actor_phone(self, actor_id: str, family_id: str, phone: str | None) -> bool:
        """给家庭成员登记电话。`None` / 空串表示清掉。

        带上 `family_id` 一起匹配，不是只按 actor_id 改——跨家庭写入是这类
        「按主键改一行」的方法最容易出的洞，而这里改的是**紧急时会被拨出去的号码**。
        """
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE actors SET phone=? WHERE id=? AND family_id=?",
                (phone or None, actor_id, family_id),
            )
            return cur.rowcount > 0

    def actor_in_family(self, actor_id: str, family_id: str, required_role: str | None = None) -> bool:
        row = self.actor(actor_id)
        if row is None or row["family_id"] != family_id:
            return False
        return required_role is None or row["role"] == required_role

    @staticmethod
    def token_hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def store_auth_token(self, raw_token: str, actor_id: str, created_at: datetime, expires_at: datetime) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO auth_tokens(token_hash,actor_id,created_at,expires_at,revoked_at) VALUES (?,?,?,?,NULL)",
                (self.token_hash(raw_token), actor_id, iso(created_at), iso(expires_at)),
            )

    def resolve_auth_token(self, raw_token: str, now: datetime | None = None) -> AuthContext | None:
        now = now or utcnow()
        with self._lock:
            row = self._conn.execute(
                """SELECT a.* FROM auth_tokens t JOIN actors a ON a.id=t.actor_id
                   WHERE t.token_hash=? AND t.revoked_at IS NULL AND t.expires_at>?""",
                (self.token_hash(raw_token), iso(now)),
            ).fetchone()
        if not row:
            return None
        return AuthContext(
            actor_id=row["id"], family_id=row["family_id"], role=ActorRole(row["role"]), display_name=row["display_name"]
        )

    # --- sessions ---
    def create_session(self, session: SessionState) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO sessions(id,family_id,elder_id,mode,active_task_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    session.session_id,
                    session.family_id,
                    session.elder_id,
                    session.mode.value,
                    session.active_task_id,
                    iso(session.created_at),
                    iso(session.updated_at),
                ),
            )

    def get_session(self, session_id: str) -> SessionState | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        return SessionState(
            session_id=row["id"],
            family_id=row["family_id"],
            elder_id=row["elder_id"],
            mode=row["mode"],
            active_task_id=row["active_task_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_session(self, session: SessionState) -> None:
        session.updated_at = utcnow()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET mode=?,active_task_id=?,updated_at=? WHERE id=?",
                (session.mode.value, session.active_task_id, iso(session.updated_at), session.session_id),
            )

    def clear_task_from_sessions(self, task_id: str, elder_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET active_task_id=NULL,updated_at=? WHERE elder_id=? AND active_task_id=?",
                (iso(utcnow()), elder_id, task_id),
            )

    # --- tasks ---
    def create_task(self, task: TaskRecord) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO tasks(id,family_id,elder_id,task_type,status,risk_level,slots_json,semantic_key,
                   version,approval_digest,created_at,updated_at,deferred_topics_json,result_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.id,
                    task.family_id,
                    task.elder_id,
                    task.task_type.value,
                    task.status.value,
                    int(task.risk_level),
                    canonical_json(task.slots),
                    task.semantic_key,
                    task.version,
                    task.approval_digest,
                    iso(task.created_at),
                    iso(task.updated_at),
                    canonical_json(task.deferred_topics),
                    canonical_json(task.result),
                ),
            )

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def update_task(self, task: TaskRecord, *, bump_version: bool = True) -> None:
        task.updated_at = utcnow()
        if bump_version:
            task.version += 1
        with self.transaction() as conn:
            conn.execute(
                """UPDATE tasks SET status=?,risk_level=?,slots_json=?,semantic_key=?,version=?,approval_digest=?,
                   updated_at=?,deferred_topics_json=?,result_json=? WHERE id=?""",
                (
                    task.status.value,
                    int(task.risk_level),
                    canonical_json(task.slots),
                    task.semantic_key,
                    task.version,
                    task.approval_digest,
                    iso(task.updated_at),
                    canonical_json(task.deferred_topics),
                    canonical_json(task.result),
                    task.id,
                ),
            )

    def list_tasks(self, family_id: str, limit: int = 100) -> list[TaskRecord]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE family_id=? ORDER BY created_at DESC LIMIT ?", (family_id, limit)
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def find_duplicate(self, family_id: str, semantic_key: str, exclude_task_id: str | None = None) -> TaskRecord | None:
        params: list[Any] = [family_id, semantic_key]
        excluding = ""
        if exclude_task_id:
            excluding = "AND id<>?"
            params.append(exclude_task_id)
        row = self._conn.execute(
            f"""SELECT * FROM tasks WHERE family_id=? AND semantic_key=? {excluding}
               AND status IN ('collecting','awaiting_elder_confirmation','awaiting_family_approval','executing','completed')
               ORDER BY created_at DESC LIMIT 1""",
            tuple(params),
        ).fetchone()
        return self._row_to_task(row) if row else None

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            family_id=row["family_id"],
            elder_id=row["elder_id"],
            task_type=TaskType(row["task_type"]),
            status=TaskStatus(row["status"]),
            risk_level=RiskLevel(row["risk_level"]),
            slots=json.loads(row["slots_json"]),
            semantic_key=row["semantic_key"],
            version=row["version"],
            approval_digest=row["approval_digest"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            deferred_topics=json.loads(row["deferred_topics_json"]),
            result=json.loads(row["result_json"]),
        )

    # --- idempotency ---
    def get_idempotent_response(self, scope: str, request_id: str | None, fingerprint: str) -> dict[str, Any] | None:
        if not request_id:
            return None
        row = self._conn.execute(
            "SELECT request_fingerprint,response_json FROM idempotency WHERE scope=? AND request_id=?",
            (scope, request_id),
        ).fetchone()
        if not row:
            return None
        if not hmac.compare_digest(row["request_fingerprint"], fingerprint):
            raise IdempotencyConflict("request_id was already used with a different payload")
        return json.loads(row["response_json"])

    def save_idempotent_response(
        self, scope: str, request_id: str | None, fingerprint: str, response: dict[str, Any]
    ) -> None:
        if not request_id:
            return
        encoded = canonical_json(response)
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT request_fingerprint,response_json FROM idempotency WHERE scope=? AND request_id=?",
                (scope, request_id),
            ).fetchone()
            if existing:
                if not hmac.compare_digest(existing["request_fingerprint"], fingerprint):
                    raise IdempotencyConflict("request_id was already used with a different payload")
                return
            conn.execute(
                "INSERT INTO idempotency(scope,request_id,request_fingerprint,response_json,created_at) VALUES (?,?,?,?,?)",
                (scope, request_id, fingerprint, encoded, iso(utcnow())),
            )

    # --- audit ---
    def _event_hash(self, canonical: str) -> str:
        return hmac.new(self._audit_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def append_audit(
        self, family_id: str, actor_id: str, event_type: str, entity_id: str | None,
        payload: dict[str, Any], *, created_at: datetime | None = None
    ) -> AuditEvent:
        """`created_at` 只给演示播种用——**它是 DemoClock 的钩子，不是显示层的美化。**

        为什么需要这个参数：这个方法本来自己取 `utcnow()`，于是一次播种里连续追加的
        事件全落在同一毫秒附近。实测审计链六条时间戳挤在 **20 毫秒**内，
        「家人点了同意」与「他确认了这一笔」相隔 **8 毫秒**——而可信中心唯一的工作
        就是让人相信这件事真实发生过，那串时间戳当场把它否掉了。

        正确的修法是让事件在**产生时**就带真实间隔，而不是在前端渲染时改写显示值。
        `displayTime = fakeTimeForPresentation(...)` 那种做法会伤害整个 Evidence
        Platform 的可信度：三个表面读的是同一份事实，一旦其中一个开始美化，
        它们就不再是同一份了。

        安全性没有削弱：`created_at` 本来就在 `canonical` 串里参与哈希，
        所以传进来的时间同样被链锁住，改一个时间戳后面全部对不上。
        """
        created_at = created_at or utcnow()
        payload_json = canonical_json(payload)
        with self.transaction() as conn:
            last = conn.execute(
                "SELECT event_hash FROM audit_events WHERE family_id=? ORDER BY id DESC LIMIT 1", (family_id,)
            ).fetchone()
            prev_hash = last[0] if last else "GENESIS"
            canonical = "|".join([family_id, actor_id, event_type, entity_id or "", payload_json, iso(created_at), prev_hash])
            event_hash = self._event_hash(canonical)
            cursor = conn.execute(
                """INSERT INTO audit_events(family_id,actor_id,event_type,entity_id,payload_json,created_at,prev_hash,event_hash)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (family_id, actor_id, event_type, entity_id, payload_json, iso(created_at), prev_hash, event_hash),
            )
            event_id = int(cursor.lastrowid)
        return AuditEvent(
            id=event_id,
            family_id=family_id,
            actor_id=actor_id,
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
            created_at=created_at,
            prev_hash=prev_hash,
            event_hash=event_hash,
        )

    def count_audit(self, family_id: str) -> int:
        # sqlite3 cursors on a shared connection must not overlap across worker threads.
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM audit_events WHERE family_id=?", (family_id,)).fetchone()[0])

    def list_audit(
        self, family_id: str, limit: int = 200, entity_id: str | None = None
    ) -> list[AuditEvent]:
        """审计事件，按时间正序。给了 `entity_id` 就只取那一件事的。

        为什么需要按事务过滤：可信中心的凭证要的是**一件事的完整链**，而它原先的
        做法是取最近 200 条再在客户端按 `entity_id` 筛。那两件事不一样——一个家庭
        用久了，第 201 条之前的事务就再也拼不出完整的链，而页面上看不出来：
        它会渲染出一份**少了前几步**的凭证，而凭证的全部价值就是「每一步都在」。

        过滤放在 SQL 里而不是取完再筛：limit 要作用在**这一件事的事件**上，
        不是作用在整个家庭的流水上。
        """
        sql = "SELECT * FROM audit_events WHERE family_id=?"
        params: list[Any] = [family_id]
        if entity_id is not None:
            sql += " AND entity_id=?"
            params.append(entity_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        rows = list(reversed(rows))
        return [self._row_to_audit(row) for row in rows]

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            family_id=row["family_id"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            entity_id=row["entity_id"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
        )

    def verify_audit_chain(self, family_id: str) -> bool:
        prev_hash = "GENESIS"
        # Materialize rows while holding the connection lock. Iterating a live cursor
        # while another thread writes can otherwise raise sqlite3.InterfaceError.
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events WHERE family_id=? ORDER BY id ASC", (family_id,)
            ).fetchall()
        for row in rows:
            event = self._row_to_audit(row)
            payload_json = canonical_json(event.payload)
            canonical = "|".join(
                [event.family_id, event.actor_id, event.event_type, event.entity_id or "", payload_json, iso(event.created_at), prev_hash]
            )
            expected = self._event_hash(canonical)
            if not hmac.compare_digest(event.prev_hash, prev_hash) or not hmac.compare_digest(event.event_hash, expected):
                return False
            prev_hash = event.event_hash
        return True

    # --- bills/appointments ---
    def unpaid_bill(self, family_id: str, bill_type: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM bills WHERE family_id=? AND bill_type=? AND paid=0 ORDER BY due_date LIMIT 1",
            (family_id, bill_type),
        ).fetchone()
        return dict(row) if row else None

    # --- comprehension evidence -------------------------------------------
    def record_comprehension_event(
        self, *, family_id: str, elder_id: str, task_id: str | None,
        signal: str, field_name: str | None, attempts: int,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO comprehension_events(
                       family_id,elder_id,task_id,signal,field_name,attempts,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (family_id, elder_id, task_id, signal, field_name, int(attempts), iso(utcnow())),
            )

    def comprehension_summary(self, family_id: str, elder_id: str, window: int = 20) -> dict[str, Any]:
        """Recent teach-back outcomes for one elder, newest first.

        `recent_signals` is ordered newest-first so callers can weight by
        recency: an elder who has since recovered must not stay labelled as
        struggling because of mistakes made several conversations ago.
        """
        rows = self._conn.execute(
            """SELECT signal, attempts FROM comprehension_events
               WHERE family_id=? AND elder_id=? ORDER BY id DESC LIMIT ?""",
            (family_id, elder_id, window),
        ).fetchall()
        total = len(rows)
        verified = sum(1 for row in rows if row["signal"] == "verified")
        mismatched = sum(1 for row in rows if row["signal"] == "mismatch")
        not_restated = sum(1 for row in rows if row["signal"] == "not_restated")
        repeated = sum(1 for row in rows if int(row["attempts"]) > 1)
        return {
            "observations": total,
            "verified": verified,
            "mismatched": mismatched,
            "not_restated": not_restated,
            "needed_more_than_one_attempt": repeated,
            "first_try_rate": round(verified / total, 4) if total else None,
            "recent_signals": [row["signal"] for row in rows],
        }

    def latest_paid_bill(self, family_id: str, bill_type: str) -> dict[str, Any] | None:
        """Most recently settled bill of a type, used to tell "already done" apart
        from "no such bill" instead of reporting both as a completed task."""
        row = self._conn.execute(
            "SELECT * FROM bills WHERE family_id=? AND bill_type=? AND paid=1 ORDER BY paid_at DESC LIMIT 1",
            (family_id, bill_type),
        ).fetchone()
        return dict(row) if row else None

    def mark_bill_paid(self, family_id: str, bill_id: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE bills SET paid=1,paid_at=? WHERE family_id=? AND id=? AND paid=0",
                (iso(utcnow()), family_id, bill_id),
            )
            return cursor.rowcount == 1

    def insert_appointment(self, data: dict[str, str]) -> bool:
        try:
            with self.transaction() as conn:
                conn.execute(
                    """INSERT INTO appointments(
                        id,family_id,elder_id,hospital,department,doctor,appointment_date,appointment_time,status,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        data["id"], data["family_id"], data["elder_id"], data["hospital"], data["department"],
                        data["doctor"], data["appointment_date"], data["appointment_time"], "confirmed", iso(utcnow()),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    # --- reminders/notifications ---
    def insert_reminder(self, reminder: ReminderRecord) -> bool:
        try:
            with self.transaction() as conn:
                conn.execute(
                    """INSERT INTO reminders(id,family_id,elder_id,title,due_at,escalation_after_minutes,status,source,
                       created_by,created_at,notified_at,acknowledged_at,completed_at,escalated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        reminder.id, reminder.family_id, reminder.elder_id, reminder.title, iso(reminder.due_at),
                        reminder.escalation_after_minutes, reminder.status.value, reminder.source, reminder.created_by,
                        iso(reminder.created_at), None, None, None, None,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_reminder(self, reminder_id: str) -> ReminderRecord | None:
        row = self._conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        return self._row_to_reminder(row) if row else None

    def list_reminders(self, family_id: str, limit: int = 100) -> list[ReminderRecord]:
        rows = self._conn.execute(
            "SELECT * FROM reminders WHERE family_id=? ORDER BY due_at ASC LIMIT ?", (family_id, limit)
        ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    @staticmethod
    def _row_to_reminder(row: sqlite3.Row) -> ReminderRecord:
        return ReminderRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], title=row["title"],
            due_at=datetime.fromisoformat(row["due_at"]), escalation_after_minutes=row["escalation_after_minutes"],
            status=ReminderStatus(row["status"]), source=row["source"], created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            notified_at=datetime.fromisoformat(row["notified_at"]) if row["notified_at"] else None,
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            escalated_at=datetime.fromisoformat(row["escalated_at"]) if row["escalated_at"] else None,
        )

    def cancel_reminder(self, reminder_id: str, family_id: str, elder_id: str) -> bool:
        """Cancel an elder's own pending reminder. Already-finished ones are left alone.

        Separate from `update_reminder_status` because there is no cancelled_at
        column, and because this one is reachable by voice and so must scope
        itself to the caller's family and elder rather than trust the id.
        """
        with self.transaction() as conn:
            cursor = conn.execute(
                """UPDATE reminders SET status=? WHERE id=? AND family_id=? AND elder_id=?
                   AND status IN ('scheduled','notified','acknowledged')""",
                (ReminderStatus.CANCELLED.value, reminder_id, family_id, elder_id),
            )
            return cursor.rowcount == 1

    def update_reminder_status(self, reminder_id: str, status: ReminderStatus, timestamp_field: str, when: datetime) -> bool:
        allowed = {"notified_at", "acknowledged_at", "completed_at", "escalated_at"}
        if timestamp_field not in allowed:
            raise ValueError("invalid reminder timestamp field")
        with self.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE reminders SET status=?,{timestamp_field}=? WHERE id=?",
                (status.value, iso(when), reminder_id),
            )
            return cursor.rowcount == 1

    def due_reminders(self, now: datetime, family_id: str | None = None) -> list[ReminderRecord]:
        if family_id is None:
            rows = self._conn.execute(
                """SELECT * FROM reminders WHERE status IN ('scheduled','notified','acknowledged') AND due_at<=?
                   ORDER BY due_at ASC""",
                (iso(now),),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM reminders WHERE family_id=?
                   AND status IN ('scheduled','notified','acknowledged') AND due_at<=?
                   ORDER BY due_at ASC""",
                (family_id, iso(now)),
            ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def upcoming_reminders(
        self, now: datetime, horizon_minutes: int, family_id: str | None = None
    ) -> list[ReminderRecord]:
        """Reminders that are still ahead of `now` but inside the advance-notice horizon."""
        horizon = now + timedelta(minutes=horizon_minutes)
        if family_id is None:
            rows = self._conn.execute(
                """SELECT * FROM reminders WHERE status IN ('scheduled','notified','acknowledged')
                   AND due_at>? AND due_at<=? ORDER BY due_at ASC""",
                (iso(now), iso(horizon)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM reminders WHERE family_id=?
                   AND status IN ('scheduled','notified','acknowledged')
                   AND due_at>? AND due_at<=? ORDER BY due_at ASC""",
                (family_id, iso(now), iso(horizon)),
            ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def record_advance_notice(self, reminder_id: str, lead_minutes: int, when: datetime) -> bool:
        """Claim one rung of the advance-notice ladder. False means it already fired."""
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO reminder_advance_notices(reminder_id,lead_minutes,sent_at) VALUES (?,?,?)",
                    (reminder_id, int(lead_minutes), iso(when)),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def sent_advance_notices(self, reminder_id: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT lead_minutes FROM reminder_advance_notices WHERE reminder_id=? ORDER BY lead_minutes DESC",
            (reminder_id,),
        ).fetchall()
        return [int(row["lead_minutes"]) for row in rows]

    # --- family approval quorum ---
    def record_approval_vote(
        self, task_id: str, actor_id: str, decision: str, approval_digest: str, created_at: datetime | None = None
    ) -> bool:
        created_at = created_at or utcnow()
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO approval_votes(task_id,actor_id,decision,approval_digest,created_at) VALUES (?,?,?,?,?)",
                    (task_id, actor_id, decision, approval_digest, iso(created_at)),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def count_approval_votes(self, task_id: str, decision: str = "approve") -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM approval_votes WHERE task_id=? AND decision=?", (task_id, decision)
        ).fetchone()
        return int(row["c"]) if row else 0

    def list_approval_votes(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT actor_id,decision,approval_digest,created_at FROM approval_votes WHERE task_id=? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- consent-aware memory ---
    def create_memory(self, item: Any) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO memory_items(id,family_id,elder_id,memory_key,value_json,sensitivity,scope,purpose,status,
                   created_at,updated_at,expires_at,consent_actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item.id, item.family_id, item.elder_id, item.key, canonical_json(item.value),
                    item.sensitivity.value, item.scope.value, item.purpose, item.status.value,
                    iso(item.created_at), iso(item.updated_at), iso(item.expires_at), item.consent_actor_id,
                ),
            )

    def get_memory(self, memory_id: str) -> Any | None:
        row = self._conn.execute("SELECT * FROM memory_items WHERE id=?", (memory_id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def update_memory(self, item: Any) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE memory_items SET value_json=?,sensitivity=?,scope=?,purpose=?,status=?,updated_at=?,
                   expires_at=?,consent_actor_id=? WHERE id=?""",
                (canonical_json(item.value), item.sensitivity.value, item.scope.value, item.purpose, item.status.value,
                 iso(item.updated_at), iso(item.expires_at), item.consent_actor_id, item.id),
            )

    def list_memories(self, family_id: str, elder_id: str) -> list[Any]:
        rows = self._conn.execute(
            "SELECT * FROM memory_items WHERE family_id=? AND elder_id=? ORDER BY created_at DESC",
            (family_id, elder_id),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Any:
        from .memory_vault import MemoryItem, MemoryScope, MemorySensitivity, MemoryStatus
        return MemoryItem(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], key=row["memory_key"],
            value=json.loads(row["value_json"]), sensitivity=MemorySensitivity(row["sensitivity"]),
            scope=MemoryScope(row["scope"]), purpose=row["purpose"], status=MemoryStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]), consent_actor_id=row["consent_actor_id"],
        )

    def add_notification(
        self, family_id: str, recipient_role: ActorRole, event_type: str, message: str, entity_id: str | None = None
    ) -> NotificationRecord:
        created_at = utcnow()
        with self.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO notifications(family_id,recipient_role,event_type,entity_id,message,created_at,read_at)
                   VALUES (?,?,?,?,?,?,NULL)""",
                (family_id, recipient_role.value, event_type, entity_id, message, iso(created_at)),
            )
            notification_id = int(cursor.lastrowid)
        return NotificationRecord(
            id=notification_id, family_id=family_id, recipient_role=recipient_role, event_type=event_type,
            entity_id=entity_id, message=message, created_at=created_at,
        )

    def list_notifications(self, family_id: str, role: ActorRole, limit: int = 100) -> list[NotificationRecord]:
        rows = self._conn.execute(
            """SELECT * FROM notifications WHERE family_id=? AND recipient_role=? ORDER BY id DESC LIMIT ?""",
            (family_id, role.value, limit),
        ).fetchall()
        return [
            NotificationRecord(
                id=row["id"], family_id=row["family_id"], recipient_role=ActorRole(row["recipient_role"]),
                event_type=row["event_type"], entity_id=row["entity_id"], message=row["message"],
                created_at=datetime.fromisoformat(row["created_at"]),
                read_at=datetime.fromisoformat(row["read_at"]) if row["read_at"] else None,
            )
            for row in rows
        ]
