from __future__ import annotations

import sqlite3  # 兜住 create_memory 的唯一约束冲突，见 propose()

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
    #: 这一条的正文有没有被摘掉。
    #:
    #: 只有 `list_visible` 会把它置真：`family_summary` 那一档给家人看的时候，
    #: `value` 会被换成 `None`。带着这个标记，拿到这条记录的人**知道自己拿到的
    #: 是残的**，不会把 `value is None` 当成「她记了个空的」。
    content_withheld: bool = False


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
        """提一条要她长期记住的事。同一个 key 已经在等她点头时，抛 `ValueError`。

        表上有 `UNIQUE(elder_id, memory_key, status)`。这一条之前这里直接 INSERT，
        冲突时 `sqlite3.IntegrityError` 一路冒到 FastAPI，客户端收到的是
        **500 Internal Server Error**——家人把同一件事提两遍，屏幕上出现
        「我这边出了点问题」，而真相只是「你已经提过了」。

        为什么一直没人碰到：这条路径到 2026-08-27 才第一次从界面上可达
        （在那之前 `/v3/memories/propose` 零个前端消费者），判据也只走「第一次提」。

        `ValueError` 是这个模块已有的约定：`api.py` 把它映成 409 + `str(exc)`
        （`decide()` 那一侧早就这么用了）。
        """
        now = datetime.now(UTC)
        already = [
            m for m in self.db.list_memories(family_id, proposal.elder_id)
            if m.key == proposal.key and m.status is MemoryStatus.PROPOSED
        ]
        if already:
            raise ValueError("这一条已经在等他点头了。等他先决定，再提新的内容。")
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
        try:
            self.db.create_memory(item)
        except sqlite3.IntegrityError as exc:
            #: 上面查过一遍了；这里是**并发下的最后一道**。落到 IntegrityError
            #: 上就又是 500，所以两处说同一句人话。
            raise ValueError("这一条已经在等他点头了。等他先决定，再提新的内容。") from exc
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
            elif item.scope is MemoryScope.FAMILY_SHARED:
                #: 这一档她同意的就是「家人能看到内容」，原样给。
                visible.append(item)
            elif item.scope is MemoryScope.FAMILY_SUMMARY:
                #: 这一档她同意的是「家人能看到**有这一条**」——不是内容。
                #:
                #: 原先这两档合在一个 `in {…}` 里、都 `append(item)`，
                #: 于是中间这一档**只有标签、没有实现**。实测（家人提一条
                #: family_summary 的记忆，她点头之后用家人令牌去读）：
                #:
                #:     她点头前读到：scope = 「家人能看到有这一条」
                #:     家人实际拿到：detail = 「只给摘要的内容-存折在床头柜」
                #:
                #: 她是**按这两个词的区别**决定点不点头的：「让家人知道我记了件事」
                #: 和「让家人看见我记了什么」，对一个把钥匙、存折写进去的人来说
                #: 完全是两回事。
                #:
                #: 摘在这里而不是摘在渲染那一层：读这份清单的有**两条路**——
                #: `/v3/memories/{elder}`（`api.py` 直接把 MemoryItem 发出去）和
                #: `/api/v1/memories`（`app_api._memory_view` 再渲染一道）。
                #: 只补渲染那一层的话，`/v3` 照样把正文发出去。
                visible.append(item.model_copy(
                    update={"value": None, "content_withheld": True}))
        return visible
