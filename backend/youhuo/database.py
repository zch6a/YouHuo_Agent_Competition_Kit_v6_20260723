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
from datetime import UTC, datetime, timedelta
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
from .utils import canonical_json


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
                (ids.elder_id, "elder", "王奶奶"),
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
        self, family_id: str, actor_id: str, event_type: str, entity_id: str | None, payload: dict[str, Any]
    ) -> AuditEvent:
        created_at = utcnow()
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

    def list_audit(self, family_id: str, limit: int = 200) -> list[AuditEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events WHERE family_id=? ORDER BY id DESC LIMIT ?", (family_id, limit)
            ).fetchall()
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
