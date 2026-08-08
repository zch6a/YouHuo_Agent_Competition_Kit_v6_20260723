"""Compatibility helpers for explicit-consent binding.

The v2 runtime keeps authorization in :mod:`youhuo.security`; this module is
intentionally small so older integrations can import a stable digest helper
without introducing a second policy engine.
"""
from __future__ import annotations

from .models import TaskRecord
from .security import SafetyPolicy


class ApprovalTokenError(ValueError):
    pass


class ReferenceMonitorError(PermissionError):
    pass


def action_digest(task: TaskRecord, summary: str = "") -> str:
    del summary
    return SafetyPolicy.approval_digest(task)
