from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .utils import clean_user_text, new_id


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemorySensitivity(StrEnum):
    PREFERENCE = "preference"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"


class MemoryScope(StrEnum):
    PRIVATE = "private"
    FAMILY_SUMMARY = "family_summary"
    FAMILY_SHARED = "family_shared"


class MemoryStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class MemoryProposal(StrictModel):
    elder_id: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=80)
    value: Any
    sensitivity: MemorySensitivity
    scope: MemoryScope = MemoryScope.PRIVATE
    purpose: str = Field(min_length=1, max_length=240)
    ttl_days: int = Field(default=180, ge=1, le=3650)

    @field_validator("key", "purpose")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_user_text(value, max_length=240)


class MemoryItem(StrictModel):
    id: str
    family_id: str
    elder_id: str
    key: str
    value: Any
    sensitivity: MemorySensitivity
    scope: MemoryScope
    purpose: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    consent_actor_id: str | None = None


class MemoryDecision(StrictModel):
    memory_id: str
    approve: bool


class ConsentMemoryVault:
    """Consent-first long-term memory service.

    Sensitive memories never become active merely because a model inferred them.
    The elder must explicitly approve a proposal, and every item has a purpose,
    sharing scope and expiry time.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    def propose(self, family_id: str, proposal: MemoryProposal) -> MemoryItem:
        now = datetime.now(UTC)
        item = MemoryItem(
            id=new_id("memory"),
            family_id=family_id,
            elder_id=proposal.elder_id,
            key=proposal.key,
            value=proposal.value,
            sensitivity=proposal.sensitivity,
            scope=proposal.scope,
            purpose=proposal.purpose,
            status=MemoryStatus.PROPOSED,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=proposal.ttl_days),
        )
        self.db.create_memory(item)
        return item

    def decide(self, family_id: str, elder_actor_id: str, decision: MemoryDecision) -> MemoryItem:
        item = self.db.get_memory(decision.memory_id)
        if item is None or item.family_id != family_id or item.elder_id != elder_actor_id:
            raise PermissionError("记忆项不属于当前老人。")
        if item.status != MemoryStatus.PROPOSED:
            raise ValueError("记忆项已经处理。")
        item.status = MemoryStatus.ACTIVE if decision.approve else MemoryStatus.REVOKED
        item.consent_actor_id = elder_actor_id if decision.approve else None
        item.updated_at = datetime.now(UTC)
        self.db.update_memory(item)
        return item

    def revoke(self, family_id: str, elder_actor_id: str, memory_id: str) -> MemoryItem:
        item = self.db.get_memory(memory_id)
        if item is None or item.family_id != family_id or item.elder_id != elder_actor_id:
            raise PermissionError("记忆项不属于当前老人。")
        item.status = MemoryStatus.REVOKED
        item.updated_at = datetime.now(UTC)
        self.db.update_memory(item)
        return item

    def list_visible(self, family_id: str, elder_id: str, *, viewer_role: str) -> list[MemoryItem]:
        now = datetime.now(UTC)
        visible: list[MemoryItem] = []
        for item in self.db.list_memories(family_id, elder_id):
            if item.status == MemoryStatus.ACTIVE and item.expires_at <= now:
                item.status = MemoryStatus.EXPIRED
                item.updated_at = now
                self.db.update_memory(item)
            if item.status != MemoryStatus.ACTIVE:
                continue
            if viewer_role == "elder":
                visible.append(item)
            elif item.scope in {MemoryScope.FAMILY_SUMMARY, MemoryScope.FAMILY_SHARED}:
                visible.append(item)
        return visible
