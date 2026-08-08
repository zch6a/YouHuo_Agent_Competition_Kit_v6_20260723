from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import RiskLevel, TaskType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DelegationPreviewRequest(StrictModel):
    task_type: TaskType
    risk_level: RiskLevel
    amount_cents: int = Field(default=0, ge=0, le=100_000_000)
    ambiguity: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_is_reversible: bool = False


class ToolDryRunRequest(StrictModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
