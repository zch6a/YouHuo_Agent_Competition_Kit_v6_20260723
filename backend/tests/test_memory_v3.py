from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from youhuo.database import Database
from youhuo.memory_vault import (
    ConsentMemoryVault,
    MemoryDecision,
    MemoryProposal,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)


@pytest.fixture
def vault(tmp_path):
    db = Database(tmp_path / "memory.db")
    db.seed_demo()
    yield db, ConsentMemoryVault(db)
    db.close()


def proposal(scope=MemoryScope.PRIVATE, sensitivity=MemorySensitivity.PREFERENCE):
    return MemoryProposal(
        elder_id="elder-demo",
        key="常用医院",
        value="第一医院",
        sensitivity=sensitivity,
        scope=scope,
        purpose="减少重复询问",
        ttl_days=30,
    )


def test_memory_is_proposed_not_active(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal())
    assert item.status == MemoryStatus.PROPOSED
    assert service.list_visible("fam-demo", "elder-demo", viewer_role="elder") == []


def test_elder_can_approve_memory(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal())
    approved = service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=True))
    assert approved.status == MemoryStatus.ACTIVE
    assert service.list_visible("fam-demo", "elder-demo", viewer_role="elder")[0].value == "第一医院"


def test_private_memory_hidden_from_family(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal(scope=MemoryScope.PRIVATE))
    service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=True))
    assert service.list_visible("fam-demo", "elder-demo", viewer_role="family") == []


def test_shared_memory_visible_to_family(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal(scope=MemoryScope.FAMILY_SHARED))
    service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=True))
    assert len(service.list_visible("fam-demo", "elder-demo", viewer_role="family")) == 1


def test_memory_can_be_rejected(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal())
    rejected = service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=False))
    assert rejected.status == MemoryStatus.REVOKED


def test_memory_can_be_revoked(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal())
    service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=True))
    revoked = service.revoke("fam-demo", "elder-demo", item.id)
    assert revoked.status == MemoryStatus.REVOKED


def test_wrong_elder_cannot_decide(vault):
    _, service = vault
    item = service.propose("fam-demo", proposal())
    with pytest.raises(PermissionError):
        service.decide("fam-demo", "other", MemoryDecision(memory_id=item.id, approve=True))


def test_expired_memory_is_hidden(vault):
    db, service = vault
    item = service.propose("fam-demo", proposal())
    item = service.decide("fam-demo", "elder-demo", MemoryDecision(memory_id=item.id, approve=True))
    item.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.update_memory(item)
    assert service.list_visible("fam-demo", "elder-demo", viewer_role="elder") == []
    assert db.get_memory(item.id).status == MemoryStatus.EXPIRED
