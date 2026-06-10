from __future__ import annotations

from pydantic import BaseModel, Field

from nano_agent.models import ApprovalLevel


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
