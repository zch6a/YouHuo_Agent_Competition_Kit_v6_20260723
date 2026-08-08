"""Optional MCP preview server.

Not part of the verified core runtime. Install a compatible stable `mcp` package
separately. This server exposes only read-only planning/preview functions and
never executes payment, booking, identity or other side effects.
"""
from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit("Install a compatible stable MCP Python SDK to run this optional example.") from exc

from youhuo.models import RiskLevel, TaskType
from youhuo.orchestration import DelegationPolicy, TaskPlanner

mcp = FastMCP("YouHuo Governed Preview Tools")


@mcp.tool()
def get_task_plan(task_type: str) -> dict:
    """Return the authoritative read-only task graph for a supported task type."""
    return TaskPlanner.plan(TaskType(task_type)).model_dump(mode="json")


@mcp.tool()
def preview_delegation(
    task_type: str,
    risk_level: int,
    amount_cents: int = 0,
    ambiguity: float = 0.0,
    tool_is_reversible: bool = False,
) -> dict:
    """Preview human-confirmation requirements. This function has no side effect."""
    return DelegationPolicy.decide(
        TaskType(task_type),
        RiskLevel(risk_level),
        amount_cents=amount_cents,
        ambiguity=ambiguity,
        tool_is_reversible=tool_is_reversible,
    ).model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
