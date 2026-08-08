from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import RiskLevel
from .security import SafetyPolicy


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolManifest(StrictModel):
    name: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: RiskLevel
    read_only: bool
    reversible: bool
    requires_elder_confirmation: bool
    requires_family_approval: bool
    untrusted_output_fields: list[str] = Field(default_factory=list)


class ToolDryRunResult(StrictModel):
    allowed: bool
    tool_name: str
    normalized_arguments: dict[str, Any]
    required_confirmations: list[str]
    warnings: list[str]


class SafeToolRegistry:
    """Schema-first registry with explicit risk metadata and dry-run validation."""

    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, manifest: ToolManifest, handler: Callable[..., Any] | None = None) -> None:
        if manifest.name in self._manifests:
            raise ValueError(f"工具已注册：{manifest.name}")
        self._manifests[manifest.name] = manifest
        if handler:
            self._handlers[manifest.name] = handler

    def manifests(self) -> list[ToolManifest]:
        return [self._manifests[name] for name in sorted(self._manifests)]

    def dry_run(self, name: str, arguments: dict[str, Any]) -> ToolDryRunResult:
        manifest = self._manifests.get(name)
        if manifest is None:
            return ToolDryRunResult(
                allowed=False,
                tool_name=name,
                normalized_arguments={},
                required_confirmations=[],
                warnings=["工具不在允许列表中"],
            )
        properties = manifest.input_schema.get("properties", {})
        required = set(manifest.input_schema.get("required", []))
        unknown = sorted(set(arguments).difference(properties))
        missing = sorted(required.difference(arguments))
        warnings: list[str] = []
        if unknown:
            warnings.append("存在未声明参数：" + "、".join(unknown))
        if missing:
            warnings.append("缺少必填参数：" + "、".join(missing))
        normalized: dict[str, Any] = {}
        for key, value in arguments.items():
            if key not in properties:
                continue
            schema = properties[key]
            expected = schema.get("type")
            if expected == "string":
                normalized[key] = SafetyPolicy.sanitize_untrusted_text(str(value), max_length=500)
            elif expected == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    warnings.append(f"参数{key}类型错误")
                else:
                    minimum = schema.get("minimum")
                    maximum = schema.get("maximum")
                    if minimum is not None and value < minimum:
                        warnings.append(f"参数{key}低于最小值")
                    elif maximum is not None and value > maximum:
                        warnings.append(f"参数{key}高于最大值")
                    else:
                        normalized[key] = value
            elif expected == "boolean":
                if isinstance(value, bool):
                    normalized[key] = value
                else:
                    warnings.append(f"参数{key}类型错误")
            else:
                normalized[key] = value
        confirmations: list[str] = []
        if manifest.requires_elder_confirmation:
            confirmations.append("elder")
        if manifest.requires_family_approval:
            confirmations.append("family")
        return ToolDryRunResult(
            allowed=not warnings,
            tool_name=name,
            normalized_arguments=normalized,
            required_confirmations=confirmations,
            warnings=warnings,
        )


def build_default_registry() -> SafeToolRegistry:
    registry = SafeToolRegistry()
    registry.register(
        ToolManifest(
            name="hospital.book",
            purpose="提交已经由老人确认的医院挂号预约",
            input_schema={
                "type": "object",
                "required": ["hospital", "department", "doctor", "appointment_date", "appointment_time"],
                "properties": {
                    "hospital": {"type": "string"},
                    "department": {"type": "string"},
                    "doctor": {"type": "string"},
                    "appointment_date": {"type": "string"},
                    "appointment_time": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "required": ["appointment_id"]},
            risk_level=RiskLevel.SENSITIVE,
            read_only=False,
            reversible=True,
            requires_elder_confirmation=True,
            requires_family_approval=False,
            untrusted_output_fields=["hospital_message"],
        )
    )
    registry.register(
        ToolManifest(
            name="billing.settle",
            purpose="确认由家属完成的账单支付并同步状态",
            input_schema={
                "type": "object",
                "required": ["bill_id", "amount_cents"],
                "properties": {
                    "bill_id": {"type": "string"},
                    "amount_cents": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "required": ["bill_id", "paid"]},
            risk_level=RiskLevel.HIGH,
            read_only=False,
            reversible=False,
            requires_elder_confirmation=True,
            requires_family_approval=True,
            untrusted_output_fields=["provider_message"],
        )
    )
    registry.register(
        ToolManifest(
            name="calendar.create",
            purpose="创建老人已确认的日历提醒",
            input_schema={
                "type": "object",
                "required": ["title", "due_at"],
                "properties": {"title": {"type": "string"}, "due_at": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={"type": "object", "required": ["reminder_id"]},
            risk_level=RiskLevel.LOW,
            read_only=False,
            reversible=True,
            requires_elder_confirmation=True,
            requires_family_approval=False,
        )
    )
    return registry
