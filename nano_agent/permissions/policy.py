from __future__ import annotations

from pydantic import BaseModel, Field

from nano_agent.hooks.base import NoOpHook
from nano_agent.models import ApprovalLevel
from nano_agent.permissions.errors import PermissionDeniedError
from nano_agent.tools.base import RuntimeTool, ToolContext


class PermissionPolicy(BaseModel):
    """工具调用权限决策策略。

    MVP 只区分自动允许和需要审批。后续可以扩展为按工具、命令、run 或用户
    偏好配置不同授权策略。
    """

    auto_approved_levels: set[ApprovalLevel] = Field(
        default_factory=lambda: {ApprovalLevel.READ}
    )  # 无需用户确认即可执行的权限等级集合。

    def requires_approval(self, level: ApprovalLevel) -> bool:
        return level not in self.auto_approved_levels


class PermissionHook(NoOpHook):
    """基于 PermissionPolicy 的工具调用前置检查。"""

    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy  # 保存本 hook 使用的权限策略。

    def before_tool_call(self, context: ToolContext, tool: RuntimeTool, tool_use) -> None: # type: ignore
        if self.policy.requires_approval(tool.approval_level):
            raise PermissionDeniedError(
                f"Tool '{tool.name}' requires approval level '{tool.approval_level}'."
            )
