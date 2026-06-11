from __future__ import annotations

from nano_agent.config import AgentConfig
from nano_agent.hooks.audit import AuditHook
from nano_agent.hooks.base import AgentHook
from nano_agent.hooks.console import ConsoleProgressHook
from nano_agent.hooks.permission import PermissionHook, PermissionPolicy
from nano_agent.hooks.rate_limit import RateLimitHook
from nano_agent.models import ApprovalLevel


def build_default_hooks(config: AgentConfig) -> list[AgentHook]:
    """构建默认 hook 列表，后续权限、审计、恢复机制在这里汇总。"""
    auto_approved = {
        ApprovalLevel.READ,
        ApprovalLevel.NETWORK,
        ApprovalLevel.EXECUTE_SAFE,
    }
    if config.auto_approve:
        auto_approved.add(ApprovalLevel.EXECUTE_RISKY)
    if config.auto_approve_write:
        auto_approved.add(ApprovalLevel.WRITE)
    hooks: list[AgentHook] = [
        PermissionHook(PermissionPolicy(auto_approved_levels=auto_approved)),
    ]
    if config.console_progress_enabled:
        hooks.append(ConsoleProgressHook())
    hooks.append(RateLimitHook(max_consecutive_calls=config.max_consecutive_tool_calls))
    if config.audit_enabled:
        hooks.append(AuditHook(max_input_chars=config.audit_max_input_chars))
    return hooks
