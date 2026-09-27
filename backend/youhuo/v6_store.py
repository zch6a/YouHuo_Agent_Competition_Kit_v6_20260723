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

    #: 这张表上可以改的列。顺序要和下面那条 INSERT 的占位符对得上。
    #: 列名和 `InteractionProfileUpdate` 的字段名一一同名——
    #: `model_fields_set` 直接拿来筛就靠这一点。
    _PROFILE_COLUMNS = (
        "speech_rate", "verbosity", "max_options", "max_sentence_chars",
        "repeat_sensitive", "teach_back_high_risk", "font_scale",
        "hearing_support", "dialect_hint",
    )

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
            #: 只覆盖调用方**真的送来**的列。
            #:
            #: 原先每一列都写成 payload 的值，而这个模型每个字段都有默认值——
            #: 于是没送的字段不是「保持不变」，是**回到默认**。实测最疼的一条：
            #: 她说「我听不清」之后档案是 `hearing_support=True,
            #: max_sentence_chars=24`，随后任何一次不带这两个字段的 PUT
            #: 都会把它们打回 `False / 42`，而她只是按了一下「保存我的习惯」。
            #:
            #: 用 `model_fields_set` 判断，不拿「值等于默认值」去猜：
            #: 后者会把一次真的「改回默认」当成没送。
            #: （`v4_store.upsert_safety_policy` 是同一个形状，同一天修的。）
            values = {
                "speech_rate": payload.speech_rate,
                "verbosity": payload.verbosity.value,
                "max_options": payload.max_options,
                "max_sentence_chars": payload.max_sentence_chars,
                "repeat_sensitive": int(payload.repeat_sensitive),
                "teach_back_high_risk": int(payload.teach_back_high_risk),
                "font_scale": payload.font_scale,
                "hearing_support": int(payload.hearing_support),
                "dialect_hint": payload.dialect_hint,
            }
            touched = [c for c in self._PROFILE_COLUMNS if c in payload.model_fields_set]
            sets = [f"{c}=excluded.{c}" for c in touched] + [
                "updated_by=excluded.updated_by",
                "updated_at=excluded.updated_at",
                "version=excluded.version",
            ]
            conn.execute(
                f"""
                INSERT INTO interaction_profiles_v6(
                    family_id,elder_id,{",".join(self._PROFILE_COLUMNS)},
                    updated_by,updated_at,version
                ) VALUES (?,?,{",".join("?" * len(self._PROFILE_COLUMNS))},?,?,?)
                ON CONFLICT(family_id,elder_id) DO UPDATE SET {",".join(sets)}
                """,
                (
                    family_id,
                    payload.elder_id,
                    *(values[c] for c in self._PROFILE_COLUMNS),
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
        # `status` is a constant, not state. This is the only writer of the
        # column and nothing can change it afterwards: the protocol has no
        # "end a study" operation (see the note in add_observation). It stays
        # in the row and in the response because the shipped plugin contract
        # xiaoyi/plugin_openapi_v6.generated.json already publishes the field;
        # do not add a reader that branches on it.
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
        # Scoped by family only, deliberately not by status. A row in
        # study_sessions_v6 is a participant enrolment (anonymous code, role,
        # consent version), not a time-boxed sitting: docs/30_V6_USER_STUDY_
        # PROTOCOL.md §6 enumerates the whole feature as register-participant,
        # record-observation, aggregate-summary, and observations accumulate
        # against one enrolment across both conditions and all six tasks. So
        # there is no "this study is over" state to check, and the column below
        # only ever holds one value. The former `AND status='active'` clause
        # could not reject anything; it read like a protection and was not one.
        # If withdrawal of consent is ever added it must delete the row (§5 data
        # minimisation), not flip a flag, so this lookup would still be right.
        with self.db._lock:
            session = self.conn.execute(
                "SELECT id FROM study_sessions_v6 WHERE family_id=? AND id=?",
                (family_id, payload.session_id),
            ).fetchone()
        if session is None:
            raise ValueError("用户实验会话不存在或不属于当前家庭。")
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
