from __future__ import annotations

from pydantic import BaseModel, Field

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import ApprovalLevel, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext


class PermissionDeniedError(PermissionError):
    """Tool call was rejected by the active permission policy."""


class PermissionPolicy(BaseModel):
    """Define which tool approval levels can run without confirmation."""

    auto_approved_levels: set[ApprovalLevel] = Field(
        default_factory=lambda: {
            ApprovalLevel.READ,
            ApprovalLevel.NETWORK,
            ApprovalLevel.EXECUTE_SAFE,
        }
    )

    def requires_approval(self, level: ApprovalLevel) -> bool:
        return level not in self.auto_approved_levels


class PermissionHook(NoOpHook):
    """Reject tool calls that require approval under the active policy."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    async def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> HookResult | None:
        if self.policy.requires_approval(tool.approval_level):
            raise PermissionDeniedError(
                f"Tool '{tool.name}' requires approval level '{tool.approval_level}'."
            )
        return None
