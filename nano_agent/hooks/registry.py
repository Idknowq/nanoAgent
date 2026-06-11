from __future__ import annotations

from nano_agent.config import AgentConfig
from nano_agent.hooks.base import AgentHook
from nano_agent.models import ApprovalLevel
from nano_agent.permissions.policy import PermissionHook, PermissionPolicy


def build_default_hooks(config: AgentConfig) -> list[AgentHook]:
    """构建默认 hook 列表，后续权限、审计、恢复机制在这里汇总。"""
    auto_approved = {ApprovalLevel.READ}
    if config.auto_approve:
        auto_approved.add(ApprovalLevel.EXECUTE_SAFE)
        auto_approved.add(ApprovalLevel.EXECUTE_RISKY)
    return [PermissionHook(PermissionPolicy(auto_approved_levels=auto_approved))]
