from __future__ import annotations

import hashlib
import json
import sqlite3
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .database import Database, iso, utcnow
from .models import ActorRole, ReminderRecord, ReminderStatus
from .utils import canonical_json, new_id
from .v4_models import (
    AssistanceRequestRecord,
    ContactCreate,
    ContactRecord,
    DeviceRecord,
    DeviceRegisterRequest,
    DoseRecord,
    DoseRecordRequest,
    EmotionAnalysis,
    EmotionEvent,
    HealthEventCreate,
    HealthEventRecord,
    ItemMemoryCreate,
    ItemMemoryRecord,
    MedicationPlanCreate,
    MedicationPlanRecord,
    OccurrenceStatus,
    PrivacyReport,
    RoutineCreate,
    RoutineFrequency,
    RoutineOccurrence,
    RoutineRecord,
    RoutineStatus,
    SafetyPolicyUpdate,
    ShareScope,
)
from .v4_services import RecurrenceEngine


class V4FeatureStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db._conn  # package-internal shared connection by design

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('schema_version','4');

            CREATE TABLE IF NOT EXISTS recurring_routines(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
                interval_n INTEGER NOT NULL CHECK(interval_n BETWEEN 1 AND 24),
                weekdays_json TEXT NOT NULL,
                day_of_month INTEGER,
                time_local TEXT NOT NULL,
                timezone TEXT NOT NULL,
                start_date TEXT NOT NULL,
                next_due_at TEXT NOT NULL,
                escalation_after_minutes INTEGER NOT NULL,
                positive_message TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active','paused','archived')),
                created_by TEXT NOT NULL REFERENCES actors(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routines_due ON recurring_routines(status,next_due_at);
            CREATE INDEX IF NOT EXISTS idx_routines_family_elder ON recurring_routines(family_id,elder_id);

            CREATE TABLE IF NOT EXISTS routine_occurrences(
                id TEXT PRIMARY KEY,
                routine_id TEXT NOT NULL REFERENCES recurring_routines(id),
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                due_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('scheduled','completed','skipped','overdue')),
                reminder_id TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(routine_id,due_at)
            );
            CREATE INDEX IF NOT EXISTS idx_occurrence_family_due ON routine_occurrences(family_id,due_at);

            CREATE TABLE IF NOT EXISTS emotion_events(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                label TEXT NOT NULL,
                valence REAL NOT NULL,
                arousal REAL NOT NULL,
                distress REAL NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                text_digest TEXT NOT NULL,
                privacy_safe_note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_emotion_elder_created ON emotion_events(family_id,elder_id,created_at);

            CREATE TABLE IF NOT EXISTS privacy_reports(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                report_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(elder_id,report_type,period_start,period_end)
            );

            CREATE TABLE IF NOT EXISTS item_memories_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                label TEXT NOT NULL,
                category TEXT NOT NULL,
                location_text TEXT NOT NULL,
                notes TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                scope TEXT NOT NULL,
                photo_sha256 TEXT,
                created_by TEXT NOT NULL REFERENCES actors(id),
                consented_by TEXT REFERENCES actors(id),
                consent_status TEXT NOT NULL CHECK(consent_status IN ('proposed','active','rejected')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(elder_id,label)
            );
            CREATE INDEX IF NOT EXISTS idx_item_memory_elder ON item_memories_v4(family_id,elder_id,label);

            CREATE TABLE IF NOT EXISTS contact_profiles_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                display_name TEXT NOT NULL,
                relation TEXT NOT NULL,
                phone_masked TEXT,
                phone_digest TEXT,
                notes TEXT NOT NULL,
                scope TEXT NOT NULL,
                face_template_digest TEXT,
                consented_by TEXT REFERENCES actors(id),
                consent_status TEXT NOT NULL CHECK(consent_status IN ('proposed','active','rejected')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(elder_id,display_name,relation)
            );
            CREATE INDEX IF NOT EXISTS idx_contact_face ON contact_profiles_v4(family_id,elder_id,face_template_digest);

            CREATE TABLE IF NOT EXISTS medical_documents_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                kind TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                extracted_json TEXT NOT NULL,
                simplified_json TEXT NOT NULL,
                review_required INTEGER NOT NULL CHECK(review_required IN (0,1)),
                created_at TEXT NOT NULL,
                UNIQUE(elder_id,source_digest)
            );

            CREATE TABLE IF NOT EXISTS health_events_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                event_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                scope TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_health_events_elder ON health_events_v4(family_id,elder_id,event_at);

            CREATE TABLE IF NOT EXISTS medication_plans_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                display_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                dose_text TEXT NOT NULL,
                times_json TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                stock_units REAL NOT NULL CHECK(stock_units >= 0),
                units_per_dose REAL NOT NULL CHECK(units_per_dose > 0),
                source TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0,1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_medication_elder_active ON medication_plans_v4(family_id,elder_id,active);

            CREATE TABLE IF NOT EXISTS medication_doses_v4(
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES medication_plans_v4(id),
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('taken','skipped','missed')),
                recorded_at TEXT NOT NULL,
                note TEXT NOT NULL,
                UNIQUE(plan_id,scheduled_at)
            );

            CREATE TABLE IF NOT EXISTS safety_policies_v4(
                elder_id TEXT PRIMARY KEY REFERENCES actors(id),
                family_id TEXT NOT NULL REFERENCES families(id),
                inactivity_minutes INTEGER NOT NULL,
                home_lat REAL,
                home_lon REAL,
                geofence_radius_m INTEGER NOT NULL,
                notify_community INTEGER NOT NULL CHECK(notify_community IN (0,1)),
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS safety_contacts_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                name TEXT NOT NULL,
                contact_role TEXT NOT NULL,
                channel TEXT NOT NULL,
                address_masked TEXT NOT NULL,
                priority INTEGER NOT NULL,
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
            );

            CREATE TABLE IF NOT EXISTS activity_events_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_elder ON activity_events_v4(family_id,elder_id,occurred_at);

            CREATE TABLE IF NOT EXISTS location_events_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_m REAL NOT NULL,
                occurred_at TEXT NOT NULL,
                source TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_location_elder ON location_events_v4(family_id,elder_id,occurred_at);

            CREATE TABLE IF NOT EXISTS devices_v4(
                device_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                actor_id TEXT NOT NULL REFERENCES actors(id),
                platform TEXT NOT NULL,
                brand TEXT NOT NULL,
                device_name TEXT NOT NULL,
                trust_level TEXT NOT NULL,
                push_capable INTEGER NOT NULL CHECK(push_capable IN (0,1)),
                last_seen_at TEXT NOT NULL,
                registered_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_family_actor ON devices_v4(family_id,actor_id);

            CREATE TABLE IF NOT EXISTS assistance_requests_v4(
                id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL REFERENCES families(id),
                elder_id TEXT NOT NULL REFERENCES actors(id),
                requested_by TEXT NOT NULL REFERENCES actors(id),
                capabilities_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired','closed')),
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_assistance_family_status ON assistance_requests_v4(family_id,status);
            """
        )

    def seed_demo(self, suffix: str = "demo") -> None:
        """Seed v4 safety defaults for one demo household. See Database.seed_demo."""
        from .database import DemoIdentities

        ids = DemoIdentities.for_suffix(suffix)
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO safety_policies_v4(
                    elder_id,family_id,inactivity_minutes,home_lat,home_lon,geofence_radius_m,notify_community,updated_at
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (ids.elder_id, ids.family_id, 720, 39.9042, 116.3974, 1500, 1, iso(now)),
            )
            conn.execute(
                """INSERT OR IGNORE INTO safety_contacts_v4(
                    id,family_id,elder_id,name,contact_role,channel,address_masked,priority,enabled
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (f"contact-grid-{suffix}", ids.family_id, ids.elder_id, "社区网格员",
                 "community", "phone", "***-***-8899", 3, 1),
            )

    # ----- authorization helpers -----
    def ensure_elder(self, family_id: str, elder_id: str) -> None:
        if not self.db.actor_in_family(elder_id, family_id, ActorRole.ELDER.value):
            raise PermissionError("老人账户不属于当前家庭。")

    # ----- routines -----
    def create_routine(self, family_id: str, actor_id: str, payload: RoutineCreate) -> RoutineRecord:
        self.ensure_elder(family_id, payload.elder_id)
        now = utcnow()
        routine = RoutineRecord(
            id=new_id("routine"),
            family_id=family_id,
            elder_id=payload.elder_id,
            title=payload.title,
            category=payload.category,
            frequency=payload.frequency,
            interval=payload.interval,
            weekdays=payload.weekdays,
            day_of_month=payload.day_of_month,
            time_local=payload.time_local,
            timezone=payload.timezone,
            start_date=payload.start_date,
            next_due_at=RecurrenceEngine.first_due(payload),
            escalation_after_minutes=payload.escalation_after_minutes,
            positive_message=payload.positive_message,
            status=RoutineStatus.ACTIVE,
            created_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO recurring_routines(
                    id,family_id,elder_id,title,category,frequency,interval_n,weekdays_json,day_of_month,time_local,
                    timezone,start_date,next_due_at,escalation_after_minutes,positive_message,status,created_by,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    routine.id, routine.family_id, routine.elder_id, routine.title, routine.category.value,
                    routine.frequency.value, routine.interval, canonical_json(routine.weekdays), routine.day_of_month,
                    routine.time_local, routine.timezone, routine.start_date.isoformat(), iso(routine.next_due_at),
                    routine.escalation_after_minutes, routine.positive_message, routine.status.value, routine.created_by,
                    iso(routine.created_at), iso(routine.updated_at),
                ),
            )
        return routine

    def list_routines(self, family_id: str, elder_id: str | None = None) -> list[RoutineRecord]:
        if elder_id:
            rows = self.conn.execute(
                "SELECT * FROM recurring_routines WHERE family_id=? AND elder_id=? ORDER BY created_at DESC",
                (family_id, elder_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM recurring_routines WHERE family_id=? ORDER BY created_at DESC", (family_id,)
            ).fetchall()
        return [self._row_routine(row) for row in rows]

    @staticmethod
    def _row_routine(row: sqlite3.Row) -> RoutineRecord:
        from .v4_models import RoutineCategory
        return RoutineRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], title=row["title"],
            category=RoutineCategory(row["category"]), frequency=RoutineFrequency(row["frequency"]),
            interval=row["interval_n"], weekdays=json.loads(row["weekdays_json"]), day_of_month=row["day_of_month"],
            time_local=row["time_local"], timezone=row["timezone"], start_date=date.fromisoformat(row["start_date"]),
            next_due_at=datetime.fromisoformat(row["next_due_at"]), escalation_after_minutes=row["escalation_after_minutes"],
            positive_message=row["positive_message"], status=RoutineStatus(row["status"]), created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def materialize_routines(self, family_id: str, now: datetime, horizon_days: int) -> dict[str, int]:
        horizon = now + timedelta(days=horizon_days)
        routines = [item for item in self.list_routines(family_id) if item.status == RoutineStatus.ACTIVE]
        created = 0
        duplicates = 0
        for routine in routines:
            due = routine.next_due_at
            guard = 0
            while due <= horizon and guard < 500:
                guard += 1
                occurrence_id = new_id("occ")
                reminder = ReminderRecord(
                    id=new_id("reminder"), family_id=family_id, elder_id=routine.elder_id, title=routine.title,
                    due_at=due, escalation_after_minutes=routine.escalation_after_minutes,
                    status=ReminderStatus.SCHEDULED, source=f"routine:{routine.id}", created_by=routine.created_by,
                    created_at=now,
                )
                inserted_reminder = self.db.insert_reminder(reminder)
                try:
                    with self.db.transaction() as conn:
                        conn.execute(
                            """INSERT INTO routine_occurrences(
                                id,routine_id,family_id,elder_id,due_at,status,reminder_id,completed_at,created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?)""",
                            (
                                occurrence_id, routine.id, family_id, routine.elder_id, iso(due),
                                OccurrenceStatus.SCHEDULED.value, reminder.id if inserted_reminder else None, None, iso(now),
                            ),
                        )
                    created += 1
                except sqlite3.IntegrityError:
                    duplicates += 1
                due = RecurrenceEngine.next_after(
                    current_due_utc=due, frequency=routine.frequency, interval=routine.interval,
                    weekdays=routine.weekdays, day_of_month=routine.day_of_month,
                    time_local=routine.time_local, timezone=routine.timezone,
                )
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE recurring_routines SET next_due_at=?,updated_at=? WHERE id=?",
                    (iso(due), iso(now), routine.id),
                )
        return {"routines": len(routines), "occurrences_created": created, "duplicates": duplicates}

    def list_occurrences(self, family_id: str, elder_id: str | None = None) -> list[RoutineOccurrence]:
        query = "SELECT * FROM routine_occurrences WHERE family_id=?"
        args: list[Any] = [family_id]
        if elder_id:
            query += " AND elder_id=?"
            args.append(elder_id)
        query += " ORDER BY due_at DESC LIMIT 500"
        rows = self.conn.execute(query, args).fetchall()
        return [
            RoutineOccurrence(
                id=row["id"], routine_id=row["routine_id"], family_id=row["family_id"], elder_id=row["elder_id"],
                due_at=datetime.fromisoformat(row["due_at"]), status=OccurrenceStatus(row["status"]),
                reminder_id=row["reminder_id"], completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def complete_occurrence(self, family_id: str, elder_id: str, occurrence_id: str) -> RoutineOccurrence:
        row = self.conn.execute(
            "SELECT o.*,r.positive_message FROM routine_occurrences o JOIN recurring_routines r ON r.id=o.routine_id WHERE o.id=?",
            (occurrence_id,),
        ).fetchone()
        if not row or row["family_id"] != family_id or row["elder_id"] != elder_id:
            raise PermissionError("循环事务不属于当前老人。")
        when = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE routine_occurrences SET status='completed',completed_at=? WHERE id=?",
                (iso(when), occurrence_id),
            )
        if row["reminder_id"]:
            reminder = self.db.get_reminder(row["reminder_id"])
            if reminder and reminder.status != ReminderStatus.COMPLETED:
                self.db.update_reminder_status(reminder.id, ReminderStatus.COMPLETED, "completed_at", when)
        return [item for item in self.list_occurrences(family_id, elder_id) if item.id == occurrence_id][0]

    # ----- emotion -----
    def add_emotion_event(self, family_id: str, elder_id: str, text: str, source: str, analysis: EmotionAnalysis) -> EmotionEvent:
        self.ensure_elder(family_id, elder_id)
        event = EmotionEvent(
            id=new_id("emotion"), family_id=family_id, elder_id=elder_id, label=analysis.label,
            valence=analysis.valence, arousal=analysis.arousal, distress=analysis.distress,
            confidence=analysis.confidence, source=source,
            text_digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            privacy_safe_note=analysis.privacy_safe_note, created_at=utcnow(),
        )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO emotion_events(
                    id,family_id,elder_id,label,valence,arousal,distress,confidence,source,text_digest,privacy_safe_note,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.id, event.family_id, event.elder_id, event.label.value, event.valence, event.arousal,
                    event.distress, event.confidence, event.source, event.text_digest, event.privacy_safe_note, iso(event.created_at),
                ),
            )
        return event

    def list_emotion_events(self, family_id: str, elder_id: str, start: datetime, end: datetime) -> list[EmotionEvent]:
        rows = self.conn.execute(
            """SELECT * FROM emotion_events WHERE family_id=? AND elder_id=? AND created_at>=? AND created_at<?
               ORDER BY created_at""",
            (family_id, elder_id, iso(start), iso(end)),
        ).fetchall()
        from .v4_models import EmotionLabel
        return [
            EmotionEvent(
                id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], label=EmotionLabel(row["label"]),
                valence=row["valence"], arousal=row["arousal"], distress=row["distress"], confidence=row["confidence"],
                source=row["source"], text_digest=row["text_digest"], privacy_safe_note=row["privacy_safe_note"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def generate_emotion_report(self, family_id: str, elder_id: str, period_start: date, period_end: date) -> PrivacyReport:
        self.ensure_elder(family_id, elder_id)
        start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        events = self.list_emotion_events(family_id, elder_id, start_dt, end_dt)
        labels: dict[str, int] = {}
        for event in events:
            labels[event.label.value] = labels.get(event.label.value, 0) + 1
        avg_distress = sum(event.distress for event in events) / len(events) if events else 0.0
        previous_mid = period_start - timedelta(days=(period_end - period_start).days + 1)
        previous = self.list_emotion_events(
            family_id, elder_id,
            datetime.combine(previous_mid, datetime.min.time(), tzinfo=UTC), start_dt,
        )
        previous_avg = sum(event.distress for event in previous) / len(previous) if previous else 0.0
        delta = avg_distress - previous_avg
        if delta > 0.15:
            trend = "distress_increasing"
        elif delta < -0.15:
            trend = "distress_decreasing"
        else:
            trend = "stable_or_insufficient"
        notes = sorted({event.privacy_safe_note for event in events})
        summary = {
            "event_count": len(events), "label_counts": labels, "average_distress": round(avg_distress, 3),
            "trend": trend, "safe_suggestions": notes[:4],
            "raw_text_included": False, "diagnosis_provided": False,
        }
        return self._save_report(family_id, elder_id, "emotion_weekly", period_start, period_end, summary)

    def _save_report(
        self, family_id: str, elder_id: str, report_type: str, period_start: date, period_end: date, summary: dict[str, Any]
    ) -> PrivacyReport:
        now = utcnow()
        existing = self.conn.execute(
            """SELECT * FROM privacy_reports WHERE elder_id=? AND report_type=? AND period_start=? AND period_end=?""",
            (elder_id, report_type, period_start.isoformat(), period_end.isoformat()),
        ).fetchone()
        if existing:
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE privacy_reports SET summary_json=?,generated_at=? WHERE id=?",
                    (canonical_json(summary), iso(now), existing["id"]),
                )
            report_id = existing["id"]
        else:
            report_id = new_id("report")
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO privacy_reports(
                        id,family_id,elder_id,report_type,period_start,period_end,summary_json,generated_at
                    ) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        report_id, family_id, elder_id, report_type, period_start.isoformat(), period_end.isoformat(),
                        canonical_json(summary), iso(now),
                    ),
                )
        return PrivacyReport(
            id=report_id, family_id=family_id, elder_id=elder_id, report_type=report_type,
            period_start=period_start, period_end=period_end, summary=summary, generated_at=now,
            privacy_guarantee="不包含聊天原文、具体人物或私密话题；仅提供聚合趋势，且不构成医学诊断。",
        )

    # ----- item memory -----
    def create_item(self, family_id: str, actor_id: str, payload: ItemMemoryCreate, actor_role: ActorRole) -> ItemMemoryRecord:
        self.ensure_elder(family_id, payload.elder_id)
        consented_by = payload.elder_id if actor_role == ActorRole.ELDER and actor_id == payload.elder_id else None
        status = "active" if consented_by else "proposed"
        now = utcnow()
        item = ItemMemoryRecord(
            id=new_id("item"), family_id=family_id, elder_id=payload.elder_id, label=payload.label,
            category=payload.category, location_text=payload.location_text, notes=payload.notes,
            sensitivity=payload.sensitivity, scope=payload.scope, photo_sha256=payload.photo_sha256,
            created_by=actor_id, consented_by=consented_by, status=status, created_at=now, updated_at=now,
        )
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO item_memories_v4(
                        id,family_id,elder_id,label,category,location_text,notes,sensitivity,scope,photo_sha256,
                        created_by,consented_by,consent_status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item.id, item.family_id, item.elder_id, item.label, item.category.value, item.location_text,
                        item.notes, item.sensitivity.value, item.scope.value, item.photo_sha256, item.created_by,
                        item.consented_by, item.status, iso(item.created_at), iso(item.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("同名实物备忘已存在，请先修改原记录。") from exc
        return item

    def search_items(self, family_id: str, elder_id: str, query: str, viewer_role: ActorRole) -> list[ItemMemoryRecord]:
        self.ensure_elder(family_id, elder_id)
        rows = self.conn.execute(
            """SELECT * FROM item_memories_v4 WHERE family_id=? AND elder_id=?
               AND (label LIKE ? OR location_text LIKE ? OR notes LIKE ?) ORDER BY updated_at DESC""",
            (family_id, elder_id, f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
        items = [self._row_item(row) for row in rows]
        if viewer_role == ActorRole.FAMILY:
            items = [item for item in items if item.scope != ShareScope.PRIVATE]
        return items

    @staticmethod
    def _row_item(row: sqlite3.Row) -> ItemMemoryRecord:
        from .v4_models import ItemCategory, MemorySensitivityV4
        return ItemMemoryRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], label=row["label"],
            category=ItemCategory(row["category"]), location_text=row["location_text"], notes=row["notes"],
            sensitivity=MemorySensitivityV4(row["sensitivity"]), scope=ShareScope(row["scope"]),
            photo_sha256=row["photo_sha256"], created_by=row["created_by"], consented_by=row["consented_by"], status=row["consent_status"],
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def decide_item(self, family_id: str, elder_id: str, item_id: str, approve: bool) -> ItemMemoryRecord:
        row = self.conn.execute("SELECT * FROM item_memories_v4 WHERE id=?", (item_id,)).fetchone()
        if not row or row["family_id"] != family_id or row["elder_id"] != elder_id:
            raise PermissionError("实物备忘不属于当前老人。")
        if row["consent_status"] != "proposed":
            raise ValueError("该实物备忘已经处理。")
        status = "active" if approve else "rejected"
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE item_memories_v4 SET consent_status=?,consented_by=?,updated_at=? WHERE id=?",
                (status, elder_id if approve else None, iso(utcnow()), item_id),
            )
        updated = self.conn.execute("SELECT * FROM item_memories_v4 WHERE id=?", (item_id,)).fetchone()
        return self._row_item(updated)

    # ----- contacts / exact demo face template -----
    @staticmethod
    def _mask_phone(phone: str | None) -> tuple[str | None, str | None]:
        if not phone:
            return None, None
        digits = "".join(ch for ch in phone if ch.isdigit())
        masked = ("*" * max(0, len(digits) - 4)) + digits[-4:]
        return masked, hashlib.sha256(phone.encode("utf-8")).hexdigest()

    def create_contact(self, family_id: str, actor_id: str, payload: ContactCreate, actor_role: ActorRole) -> ContactRecord:
        self.ensure_elder(family_id, payload.elder_id)
        consented_by = payload.elder_id if actor_role == ActorRole.ELDER and actor_id == payload.elder_id else None
        status = "active" if consented_by else "proposed"
        masked, digest = self._mask_phone(payload.phone)
        now = utcnow()
        record = ContactRecord(
            id=new_id("person"), family_id=family_id, elder_id=payload.elder_id,
            display_name=payload.display_name, relation=payload.relation, phone_masked=masked,
            notes=payload.notes, scope=payload.scope, face_template_digest=None,
            consented_by=consented_by, status=status, created_at=now, updated_at=now,
        )
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO contact_profiles_v4(
                        id,family_id,elder_id,display_name,relation,phone_masked,phone_digest,notes,scope,
                        face_template_digest,consented_by,consent_status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.id, family_id, payload.elder_id, payload.display_name, payload.relation, masked, digest,
                        payload.notes, payload.scope.value, None, consented_by, status, iso(now), iso(now),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该亲友档案已经存在。") from exc
        return record

    def get_contact(self, contact_id: str) -> ContactRecord | None:
        row = self.conn.execute("SELECT * FROM contact_profiles_v4 WHERE id=?", (contact_id,)).fetchone()
        return self._row_contact(row) if row else None

    def list_contacts(self, family_id: str, elder_id: str, viewer_role: ActorRole) -> list[ContactRecord]:
        rows = self.conn.execute(
            "SELECT * FROM contact_profiles_v4 WHERE family_id=? AND elder_id=? ORDER BY display_name",
            (family_id, elder_id),
        ).fetchall()
        contacts = [self._row_contact(row) for row in rows]
        if viewer_role == ActorRole.FAMILY:
            contacts = [item for item in contacts if item.scope != ShareScope.PRIVATE]
        return contacts

    @staticmethod
    def _row_contact(row: sqlite3.Row) -> ContactRecord:
        return ContactRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], display_name=row["display_name"],
            relation=row["relation"], phone_masked=row["phone_masked"], notes=row["notes"], scope=ShareScope(row["scope"]),
            face_template_digest=row["face_template_digest"], consented_by=row["consented_by"], status=row["consent_status"],
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def decide_contact(self, family_id: str, elder_id: str, contact_id: str, approve: bool) -> ContactRecord:
        contact = self.get_contact(contact_id)
        if not contact or contact.family_id != family_id or contact.elder_id != elder_id:
            raise PermissionError("亲友档案不属于当前老人。")
        if contact.status != "proposed":
            raise ValueError("该亲友档案已经处理。")
        status = "active" if approve else "rejected"
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE contact_profiles_v4 SET consent_status=?,consented_by=?,updated_at=? WHERE id=?",
                (status, elder_id if approve else None, iso(utcnow()), contact_id),
            )
        return self.get_contact(contact_id)  # type: ignore[return-value]

    def enroll_face_digest(self, family_id: str, elder_id: str, contact_id: str, digest: str) -> ContactRecord:
        contact = self.get_contact(contact_id)
        if not contact or contact.family_id != family_id or contact.elder_id != elder_id or contact.status != "active":
            raise PermissionError("亲友档案不属于当前家庭。")
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE contact_profiles_v4 SET face_template_digest=?,updated_at=? WHERE id=?",
                (digest, iso(now), contact_id),
            )
        return self.get_contact(contact_id)  # type: ignore[return-value]

    def match_face_digest(self, family_id: str, elder_id: str, digest: str) -> ContactRecord | None:
        row = self.conn.execute(
            """SELECT * FROM contact_profiles_v4 WHERE family_id=? AND elder_id=? AND face_template_digest=? AND consent_status='active'""",
            (family_id, elder_id, digest),
        ).fetchone()
        return self._row_contact(row) if row else None

    # ----- health documents / timeline -----
    def save_medical_document(
        self, family_id: str, elder_id: str, source_name: str, analysis: Any
    ) -> str:
        self.ensure_elder(family_id, elder_id)
        existing = self.conn.execute(
            "SELECT id FROM medical_documents_v4 WHERE elder_id=? AND source_digest=?",
            (elder_id, analysis.source_digest),
        ).fetchone()
        if existing:
            return str(existing["id"])
        doc_id = new_id("medicaldoc")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO medical_documents_v4(
                    id,family_id,elder_id,kind,source_name,source_digest,extracted_json,simplified_json,review_required,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc_id, family_id, elder_id, analysis.kind.value, source_name, analysis.source_digest,
                    canonical_json({"dates": analysis.dates, "measurements": analysis.measurements, "follow_up_date": analysis.follow_up_date}),
                    canonical_json({"terms": analysis.terms, "summary": analysis.summary_for_elder, "cautions": analysis.caution_flags}),
                    1, iso(utcnow()),
                ),
            )
        return doc_id

    def create_health_event(self, family_id: str, payload: HealthEventCreate) -> HealthEventRecord:
        self.ensure_elder(family_id, payload.elder_id)
        record = HealthEventRecord(id=new_id("health"), family_id=family_id, created_at=utcnow(), **payload.model_dump())
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO health_events_v4(
                    id,family_id,elder_id,kind,title,event_at,payload_json,source,scope,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.id, family_id, record.elder_id, record.kind.value, record.title, iso(record.event_at),
                    canonical_json(record.payload), record.source, record.scope.value, iso(record.created_at),
                ),
            )
        return record

    def list_health_events(self, family_id: str, elder_id: str, viewer_role: ActorRole) -> list[HealthEventRecord]:
        rows = self.conn.execute(
            "SELECT * FROM health_events_v4 WHERE family_id=? AND elder_id=? ORDER BY event_at DESC LIMIT 500",
            (family_id, elder_id),
        ).fetchall()
        from .v4_models import HealthEventKind
        events = [
            HealthEventRecord(
                id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], kind=HealthEventKind(row["kind"]),
                title=row["title"], event_at=datetime.fromisoformat(row["event_at"]), payload=json.loads(row["payload_json"]),
                source=row["source"], scope=ShareScope(row["scope"]), created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
        if viewer_role == ActorRole.FAMILY:
            events = [event for event in events if event.scope != ShareScope.PRIVATE]
        return events

    # ----- medications -----
    def create_medication_plan(self, family_id: str, payload: MedicationPlanCreate, actor_role: ActorRole) -> MedicationPlanRecord:
        self.ensure_elder(family_id, payload.elder_id)
        now = utcnow()
        record = MedicationPlanRecord(
            id=new_id("medplan"), family_id=family_id, active=(actor_role == ActorRole.ELDER), created_at=now, updated_at=now, **payload.model_dump()
        )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO medication_plans_v4(
                    id,family_id,elder_id,display_name,normalized_name,dose_text,times_json,start_date,end_date,
                    stock_units,units_per_dose,source,active,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.id, family_id, record.elder_id, record.display_name, record.normalized_name,
                    record.dose_text, canonical_json(record.times_local), record.start_date.isoformat(),
                    record.end_date.isoformat() if record.end_date else None, record.stock_units, record.units_per_dose,
                    record.source, int(record.active), iso(now), iso(now),
                ),
            )
        return record

    def list_medication_plans(self, family_id: str, elder_id: str) -> list[MedicationPlanRecord]:
        rows = self.conn.execute(
            "SELECT * FROM medication_plans_v4 WHERE family_id=? AND elder_id=? ORDER BY active DESC,created_at DESC",
            (family_id, elder_id),
        ).fetchall()
        return [self._row_medication(row) for row in rows]

    @staticmethod
    def _row_medication(row: sqlite3.Row) -> MedicationPlanRecord:
        return MedicationPlanRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], display_name=row["display_name"],
            normalized_name=row["normalized_name"], dose_text=row["dose_text"], times_local=json.loads(row["times_json"]),
            start_date=date.fromisoformat(row["start_date"]), end_date=date.fromisoformat(row["end_date"]) if row["end_date"] else None,
            stock_units=row["stock_units"], units_per_dose=row["units_per_dose"], source=row["source"], active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_medication_plan(self, plan_id: str) -> MedicationPlanRecord | None:
        row = self.conn.execute("SELECT * FROM medication_plans_v4 WHERE id=?", (plan_id,)).fetchone()
        return self._row_medication(row) if row else None

    def approve_medication_plan(self, family_id: str, elder_id: str, plan_id: str, approve: bool) -> MedicationPlanRecord:
        plan = self.get_medication_plan(plan_id)
        if not plan or plan.family_id != family_id or plan.elder_id != elder_id:
            raise PermissionError("用药计划不属于当前老人。")
        with self.db.transaction() as conn:
            if approve:
                conn.execute("UPDATE medication_plans_v4 SET active=1,updated_at=? WHERE id=?", (iso(utcnow()), plan_id))
            else:
                conn.execute("DELETE FROM medication_plans_v4 WHERE id=? AND active=0", (plan_id,))
        if not approve:
            return plan.model_copy(update={"active": False, "updated_at": utcnow()})
        return self.get_medication_plan(plan_id)  # type: ignore[return-value]

    def record_dose(self, family_id: str, actor_id: str, plan_id: str, payload: DoseRecordRequest) -> DoseRecord:
        plan = self.get_medication_plan(plan_id)
        if not plan or plan.family_id != family_id:
            raise PermissionError("用药计划不属于当前家庭。")
        now = utcnow()
        record = DoseRecord(
            id=new_id("dose"), plan_id=plan_id, scheduled_at=payload.scheduled_at,
            status=payload.status, recorded_at=now, note=payload.note,
        )
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO medication_doses_v4(id,plan_id,scheduled_at,status,recorded_at,note)
                       VALUES (?,?,?,?,?,?)""",
                    (record.id, plan_id, iso(record.scheduled_at), record.status.value, iso(now), record.note),
                )
                if record.status.value == "taken":
                    conn.execute(
                        """UPDATE medication_plans_v4 SET stock_units=MAX(0,stock_units-units_per_dose),updated_at=? WHERE id=?""",
                        (iso(now), plan_id),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该时间点的服药记录已存在。") from exc
        self.db.append_audit(family_id, actor_id, "MEDICATION_DOSE_RECORDED", plan_id, {"status": record.status.value})
        return record

    def medication_adherence(self, family_id: str, elder_id: str, start: date, end: date) -> dict[str, Any]:
        plans = self.list_medication_plans(family_id, elder_id)
        plan_ids = [plan.id for plan in plans]
        if not plan_ids:
            return {"total": 0, "taken": 0, "skipped": 0, "missed": 0, "adherence_rate": None}
        placeholders = ",".join("?" for _ in plan_ids)
        rows = self.conn.execute(
            f"""SELECT status,COUNT(*) AS c FROM medication_doses_v4 WHERE plan_id IN ({placeholders})
                AND scheduled_at>=? AND scheduled_at<? GROUP BY status""",
            [*plan_ids, f"{start.isoformat()}T00:00:00+00:00", f"{(end + timedelta(days=1)).isoformat()}T00:00:00+00:00"],
        ).fetchall()
        counts = {row["status"]: int(row["c"]) for row in rows}
        total = sum(counts.values())
        return {
            "total": total, "taken": counts.get("taken", 0), "skipped": counts.get("skipped", 0),
            "missed": counts.get("missed", 0),
            "adherence_rate": round(counts.get("taken", 0) / total, 3) if total else None,
        }

    # ----- safety/location -----
    def upsert_safety_policy(self, family_id: str, payload: SafetyPolicyUpdate) -> dict[str, Any]:
        self.ensure_elder(family_id, payload.elder_id)
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO safety_policies_v4(
                    elder_id,family_id,inactivity_minutes,home_lat,home_lon,geofence_radius_m,notify_community,updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(elder_id) DO UPDATE SET inactivity_minutes=excluded.inactivity_minutes,
                home_lat=excluded.home_lat,home_lon=excluded.home_lon,geofence_radius_m=excluded.geofence_radius_m,
                notify_community=excluded.notify_community,updated_at=excluded.updated_at""",
                (
                    payload.elder_id, family_id, payload.inactivity_minutes, payload.home_lat, payload.home_lon,
                    payload.geofence_radius_m, int(payload.notify_community), iso(now),
                ),
            )
        return self.get_safety_policy(family_id, payload.elder_id)

    def get_safety_policy(self, family_id: str, elder_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM safety_policies_v4 WHERE family_id=? AND elder_id=?", (family_id, elder_id)
        ).fetchone()
        if not row:
            return {
                "elder_id": elder_id, "family_id": family_id, "inactivity_minutes": 720,
                "home_lat": None, "home_lon": None, "geofence_radius_m": 1500,
                "notify_community": False, "updated_at": None,
            }
        result = dict(row)
        result["notify_community"] = bool(result["notify_community"])
        return result

    def add_activity(self, family_id: str, elder_id: str, kind: str, occurred_at: datetime, metadata: dict[str, Any]) -> str:
        self.ensure_elder(family_id, elder_id)
        event_id = new_id("activity")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO activity_events_v4(id,family_id,elder_id,kind,occurred_at,metadata_json) VALUES (?,?,?,?,?,?)",
                (event_id, family_id, elder_id, kind, iso(occurred_at), canonical_json(metadata)),
            )
        return event_id

    def evaluate_inactivity(self, family_id: str, now: datetime) -> list[dict[str, Any]]:
        policies = self.conn.execute("SELECT * FROM safety_policies_v4 WHERE family_id=?", (family_id,)).fetchall()
        results: list[dict[str, Any]] = []
        for policy in policies:
            row = self.conn.execute(
                "SELECT occurred_at FROM activity_events_v4 WHERE elder_id=? ORDER BY occurred_at DESC LIMIT 1",
                (policy["elder_id"],),
            ).fetchone()
            last = datetime.fromisoformat(row["occurred_at"]) if row else None
            inactive_minutes = (now - last).total_seconds() / 60 if last else float("inf")
            threshold = int(policy["inactivity_minutes"])
            alert = inactive_minutes >= threshold
            if alert:
                self.db.add_notification(
                    family_id, ActorRole.FAMILY, "inactivity_check", "老人端长时间无交互，请先电话核实情况。",
                    policy["elder_id"],
                )
            results.append(
                {
                    "elder_id": policy["elder_id"], "last_activity_at": last.isoformat() if last else None,
                    "inactive_minutes": None if inactive_minutes == float("inf") else round(inactive_minutes, 1),
                    "threshold_minutes": threshold, "alert_created": alert,
                }
            )
        return results

    def add_location(
        self, family_id: str, elder_id: str, latitude: float, longitude: float, accuracy_m: float, occurred_at: datetime, source: str
    ) -> str:
        self.ensure_elder(family_id, elder_id)
        event_id = new_id("location")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO location_events_v4(
                    id,family_id,elder_id,latitude,longitude,accuracy_m,occurred_at,source
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (event_id, family_id, elder_id, latitude, longitude, accuracy_m, iso(occurred_at), source),
            )
            # Minimize location retention: keep only the latest 200 events per elder.
            conn.execute(
                """DELETE FROM location_events_v4 WHERE elder_id=? AND id NOT IN (
                    SELECT id FROM location_events_v4 WHERE elder_id=? ORDER BY occurred_at DESC LIMIT 200
                )""",
                (elder_id, elder_id),
            )
        return event_id

    def safety_contacts(self, family_id: str, elder_id: str, include_community: bool) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM safety_contacts_v4 WHERE family_id=? AND elder_id=? AND enabled=1
               AND (?=1 OR contact_role!='community') ORDER BY priority""",
            (family_id, elder_id, int(include_community)),
        ).fetchall()
        return [dict(row) for row in rows]

    # ----- device / remote assistance -----
    def register_device(self, family_id: str, payload: DeviceRegisterRequest) -> DeviceRecord:
        if not self.db.actor_in_family(payload.actor_id, family_id):
            raise PermissionError("设备所属账户不在当前家庭。")
        now = utcnow()
        existing = self.conn.execute("SELECT registered_at FROM devices_v4 WHERE device_id=?", (payload.device_id,)).fetchone()
        registered_at = datetime.fromisoformat(existing["registered_at"]) if existing else now
        trust = "verified_demo_account" if payload.platform.casefold() in {"harmonyos", "web", "android", "ios"} else "unknown"
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO devices_v4(
                    device_id,family_id,actor_id,platform,brand,device_name,trust_level,push_capable,last_seen_at,registered_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET actor_id=excluded.actor_id,platform=excluded.platform,brand=excluded.brand,
                device_name=excluded.device_name,trust_level=excluded.trust_level,push_capable=excluded.push_capable,
                last_seen_at=excluded.last_seen_at""",
                (
                    payload.device_id, family_id, payload.actor_id, payload.platform, payload.brand, payload.device_name,
                    trust, int(payload.push_capable), iso(now), iso(registered_at),
                ),
            )
        return DeviceRecord(
            **payload.model_dump(), family_id=family_id, trust_level=trust, last_seen_at=now, registered_at=registered_at
        )

    def list_devices(self, family_id: str) -> list[DeviceRecord]:
        rows = self.conn.execute("SELECT * FROM devices_v4 WHERE family_id=? ORDER BY last_seen_at DESC", (family_id,)).fetchall()
        return [
            DeviceRecord(
                actor_id=row["actor_id"], device_id=row["device_id"], platform=row["platform"], brand=row["brand"],
                device_name=row["device_name"], push_capable=bool(row["push_capable"]), family_id=row["family_id"],
                trust_level=row["trust_level"], last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
                registered_at=datetime.fromisoformat(row["registered_at"]),
            )
            for row in rows
        ]

    def create_assistance_request(
        self, family_id: str, actor_id: str, elder_id: str, capabilities: list[str], expires_in_minutes: int
    ) -> AssistanceRequestRecord:
        self.ensure_elder(family_id, elder_id)
        allowed = {"view_current_step", "speak_guidance", "highlight_control", "submit_low_risk_form"}
        requested = sorted(set(capabilities))
        if any(item not in allowed for item in requested):
            raise ValueError("远程协助只允许查看步骤、语音指导、控件高亮和低风险表单提交，禁止屏幕接管或支付。")
        now = utcnow()
        record = AssistanceRequestRecord(
            id=new_id("assist"), family_id=family_id, elder_id=elder_id, requested_by=actor_id,
            requested_capabilities=requested, status="pending", expires_at=now + timedelta(minutes=expires_in_minutes),
            created_at=now,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO assistance_requests_v4(
                    id,family_id,elder_id,requested_by,capabilities_json,status,expires_at,created_at,resolved_at
                ) VALUES (?,?,?,?,?,?,?,?,NULL)""",
                (
                    record.id, family_id, elder_id, actor_id, canonical_json(requested), record.status,
                    iso(record.expires_at), iso(now),
                ),
            )
        return record

    def decide_assistance(self, family_id: str, elder_id: str, request_id: str, approve: bool) -> AssistanceRequestRecord:
        row = self.conn.execute("SELECT * FROM assistance_requests_v4 WHERE id=?", (request_id,)).fetchone()
        if not row or row["family_id"] != family_id or row["elder_id"] != elder_id:
            raise PermissionError("远程协助请求不属于当前老人。")
        if row["status"] != "pending":
            raise ValueError("远程协助请求已经处理。")
        now = utcnow()
        if datetime.fromisoformat(row["expires_at"]) <= now:
            new_status = "expired"
        else:
            new_status = "approved" if approve else "rejected"
        with self.db.transaction() as conn:
            conn.execute("UPDATE assistance_requests_v4 SET status=?,resolved_at=? WHERE id=?", (new_status, iso(now), request_id))
        return AssistanceRequestRecord(
            id=row["id"], family_id=row["family_id"], elder_id=row["elder_id"], requested_by=row["requested_by"],
            requested_capabilities=json.loads(row["capabilities_json"]), status=new_status,
            expires_at=datetime.fromisoformat(row["expires_at"]), created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=now,
        )

    # ----- reports / graph helpers -----
    def monthly_report(self, family_id: str, elder_id: str, year: int, month: int) -> PrivacyReport:
        self.ensure_elder(family_id, elder_id)
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        start_iso = f"{start.isoformat()}T00:00:00+00:00"
        next_month = end + timedelta(days=1)
        end_iso = f"{next_month.isoformat()}T00:00:00+00:00"
        occurrence_rows = self.conn.execute(
            """SELECT status,COUNT(*) AS c FROM routine_occurrences WHERE family_id=? AND elder_id=?
               AND due_at>=? AND due_at<? GROUP BY status""",
            (family_id, elder_id, start_iso, end_iso),
        ).fetchall()
        occurrence_counts = {row["status"]: int(row["c"]) for row in occurrence_rows}
        task_rows = self.conn.execute(
            """SELECT status,COUNT(*) AS c FROM tasks WHERE family_id=? AND elder_id=?
               AND created_at>=? AND created_at<? GROUP BY status""",
            (family_id, elder_id, start_iso, end_iso),
        ).fetchall()
        task_counts = {row["status"]: int(row["c"]) for row in task_rows}
        medication = self.medication_adherence(family_id, elder_id, start, end)
        safety_count = self.conn.execute(
            """SELECT COUNT(*) AS c FROM notifications WHERE family_id=? AND event_type IN
               ('sos','urgent_emotion','geofence_exit','inactivity_check') AND created_at>=? AND created_at<?""",
            (family_id, start_iso, end_iso),
        ).fetchone()["c"]
        completed = occurrence_counts.get("completed", 0)
        total_occ = sum(occurrence_counts.values())
        summary = {
            "routine_occurrences": occurrence_counts,
            "routine_completion_rate": round(completed / total_occ, 3) if total_occ else None,
            "agent_tasks": task_counts,
            "medication_adherence": medication,
            "safety_attention_events": int(safety_count),
            "positive_message": "本月已经完成的每一件小事都值得肯定。",
            "raw_companion_chat_included": False,
        }
        return self._save_report(family_id, elder_id, "monthly_care", start, end, summary)

    def raw_health_rows(self, family_id: str, elder_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        health = [item.model_dump(mode="json") for item in self.list_health_events(family_id, elder_id, ActorRole.ELDER)]
        meds = [item.model_dump(mode="json") for item in self.list_medication_plans(family_id, elder_id)]
        return health, meds
