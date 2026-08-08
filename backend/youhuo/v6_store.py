from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .database import Database, iso, utcnow
from .models import AuthContext
from .utils import new_id
from .v6_models import (
    InteractionProfile,
    InteractionProfileUpdate,
    StudyObservation,
    StudyObservationCreate,
    StudySession,
    StudySessionCreate,
)


class V6FeatureStore:
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
                CREATE TABLE IF NOT EXISTS interaction_profiles_v6(
                    family_id TEXT NOT NULL REFERENCES families(id),
                    elder_id TEXT NOT NULL REFERENCES actors(id),
                    speech_rate REAL NOT NULL,
                    verbosity TEXT NOT NULL,
                    max_options INTEGER NOT NULL,
                    max_sentence_chars INTEGER NOT NULL,
                    repeat_sensitive INTEGER NOT NULL CHECK(repeat_sensitive IN (0,1)),
                    teach_back_high_risk INTEGER NOT NULL CHECK(teach_back_high_risk IN (0,1)),
                    font_scale REAL NOT NULL,
                    hearing_support INTEGER NOT NULL CHECK(hearing_support IN (0,1)),
                    dialect_hint TEXT,
                    updated_by TEXT NOT NULL REFERENCES actors(id),
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY(family_id,elder_id)
                );

                CREATE TABLE IF NOT EXISTS study_sessions_v6(
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL REFERENCES families(id),
                    participant_code TEXT NOT NULL,
                    role TEXT NOT NULL,
                    consent_version TEXT NOT NULL,
                    age_band TEXT,
                    device_type TEXT NOT NULL,
                    notes TEXT,
                    created_by TEXT NOT NULL REFERENCES actors(id),
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    UNIQUE(family_id,participant_code)
                );

                CREATE TABLE IF NOT EXISTS study_observations_v6(
                    id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL REFERENCES families(id),
                    session_id TEXT NOT NULL REFERENCES study_sessions_v6(id) ON DELETE CASCADE,
                    scenario TEXT NOT NULL,
                    success INTEGER NOT NULL CHECK(success IN (0,1)),
                    duration_seconds REAL NOT NULL,
                    clarification_count INTEGER NOT NULL,
                    assistance_count INTEGER NOT NULL,
                    perceived_ease INTEGER NOT NULL,
                    trust_calibration INTEGER NOT NULL,
                    comments TEXT,
                    created_by TEXT NOT NULL REFERENCES actors(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_study_obs_v6_family ON study_observations_v6(family_id,session_id,created_at);
                """
            )

    def get_profile(self, family_id: str, elder_id: str) -> InteractionProfile:
        with self.db._lock:
            row = self.conn.execute(
                "SELECT * FROM interaction_profiles_v6 WHERE family_id=? AND elder_id=?",
                (family_id, elder_id),
            ).fetchone()
        if row is None:
            return InteractionProfile(
                family_id=family_id,
                elder_id=elder_id,
                speech_rate=0.88,
                verbosity="gentle",
                max_options=3,
                max_sentence_chars=42,
                repeat_sensitive=True,
                teach_back_high_risk=True,
                font_scale=1.25,
                hearing_support=False,
                dialect_hint=None,
                updated_by="system",
                updated_at=utcnow(),
                version=1,
            )
        return self._profile(row)

    def upsert_profile(
        self,
        family_id: str,
        actor: AuthContext,
        payload: InteractionProfileUpdate,
    ) -> InteractionProfile:
        now = utcnow()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT version FROM interaction_profiles_v6 WHERE family_id=? AND elder_id=?",
                (family_id, payload.elder_id),
            ).fetchone()
            version = (int(row["version"]) + 1) if row else 1
            conn.execute(
                """
                INSERT INTO interaction_profiles_v6(
                    family_id,elder_id,speech_rate,verbosity,max_options,max_sentence_chars,
                    repeat_sensitive,teach_back_high_risk,font_scale,hearing_support,dialect_hint,
                    updated_by,updated_at,version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(family_id,elder_id) DO UPDATE SET
                    speech_rate=excluded.speech_rate,
                    verbosity=excluded.verbosity,
                    max_options=excluded.max_options,
                    max_sentence_chars=excluded.max_sentence_chars,
                    repeat_sensitive=excluded.repeat_sensitive,
                    teach_back_high_risk=excluded.teach_back_high_risk,
                    font_scale=excluded.font_scale,
                    hearing_support=excluded.hearing_support,
                    dialect_hint=excluded.dialect_hint,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at,
                    version=excluded.version
                """,
                (
                    family_id,
                    payload.elder_id,
                    payload.speech_rate,
                    payload.verbosity.value,
                    payload.max_options,
                    payload.max_sentence_chars,
                    int(payload.repeat_sensitive),
                    int(payload.teach_back_high_risk),
                    payload.font_scale,
                    int(payload.hearing_support),
                    payload.dialect_hint,
                    actor.actor_id,
                    iso(now),
                    version,
                ),
            )
        return self.get_profile(family_id, payload.elder_id)

    def create_study_session(
        self,
        family_id: str,
        actor: AuthContext,
        payload: StudySessionCreate,
    ) -> StudySession:
        session_id = new_id("study")
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO study_sessions_v6(
                    id,family_id,participant_code,role,consent_version,age_band,device_type,notes,
                    created_by,created_at,status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    family_id,
                    payload.participant_code,
                    payload.role.value,
                    payload.consent_version,
                    payload.age_band,
                    payload.device_type,
                    payload.notes,
                    actor.actor_id,
                    iso(now),
                    "active",
                ),
            )
        return StudySession(
            id=session_id,
            family_id=family_id,
            created_by=actor.actor_id,
            created_at=now,
            status="active",
            **payload.model_dump(),
        )

    def list_study_sessions(self, family_id: str) -> list[StudySession]:
        with self.db._lock:
            rows = self.conn.execute(
                "SELECT * FROM study_sessions_v6 WHERE family_id=? ORDER BY created_at",
                (family_id,),
            ).fetchall()
        return [self._study_session(row) for row in rows]

    def add_observation(
        self,
        family_id: str,
        actor: AuthContext,
        payload: StudyObservationCreate,
    ) -> StudyObservation:
        with self.db._lock:
            session = self.conn.execute(
                "SELECT id FROM study_sessions_v6 WHERE family_id=? AND id=? AND status='active'",
                (family_id, payload.session_id),
            ).fetchone()
        if session is None:
            raise ValueError("用户实验会话不存在、已结束或不属于当前家庭。")
        obs_id = new_id("obs")
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO study_observations_v6(
                    id,family_id,session_id,scenario,success,duration_seconds,clarification_count,
                    assistance_count,perceived_ease,trust_calibration,comments,created_by,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    obs_id,
                    family_id,
                    payload.session_id,
                    payload.scenario,
                    int(payload.success),
                    payload.duration_seconds,
                    payload.clarification_count,
                    payload.assistance_count,
                    payload.perceived_ease,
                    payload.trust_calibration,
                    payload.comments,
                    actor.actor_id,
                    iso(now),
                ),
            )
        return StudyObservation(
            id=obs_id,
            family_id=family_id,
            created_by=actor.actor_id,
            created_at=now,
            **payload.model_dump(),
        )

    def list_observations(self, family_id: str) -> list[StudyObservation]:
        with self.db._lock:
            rows = self.conn.execute(
                "SELECT * FROM study_observations_v6 WHERE family_id=? ORDER BY created_at",
                (family_id,),
            ).fetchall()
        return [self._observation(row) for row in rows]

    @staticmethod
    def _profile(row: sqlite3.Row) -> InteractionProfile:
        return InteractionProfile(
            family_id=row["family_id"],
            elder_id=row["elder_id"],
            speech_rate=float(row["speech_rate"]),
            verbosity=row["verbosity"],
            max_options=int(row["max_options"]),
            max_sentence_chars=int(row["max_sentence_chars"]),
            repeat_sensitive=bool(row["repeat_sensitive"]),
            teach_back_high_risk=bool(row["teach_back_high_risk"]),
            font_scale=float(row["font_scale"]),
            hearing_support=bool(row["hearing_support"]),
            dialect_hint=row["dialect_hint"],
            updated_by=row["updated_by"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
            version=int(row["version"]),
        )

    @staticmethod
    def _study_session(row: sqlite3.Row) -> StudySession:
        return StudySession(
            id=row["id"],
            family_id=row["family_id"],
            participant_code=row["participant_code"],
            role=row["role"],
            consent_version=row["consent_version"],
            age_band=row["age_band"],
            device_type=row["device_type"],
            notes=row["notes"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=row["status"],
        )

    @staticmethod
    def _observation(row: sqlite3.Row) -> StudyObservation:
        return StudyObservation(
            id=row["id"],
            family_id=row["family_id"],
            session_id=row["session_id"],
            scenario=row["scenario"],
            success=bool(row["success"]),
            duration_seconds=float(row["duration_seconds"]),
            clarification_count=int(row["clarification_count"]),
            assistance_count=int(row["assistance_count"]),
            perceived_ease=int(row["perceived_ease"]),
            trust_calibration=int(row["trust_calibration"]),
            comments=row["comments"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
