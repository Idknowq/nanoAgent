"""Agent loop hook extension points."""

from nano_agent.hooks.audit import AuditHook, ToolAuditRecord
from nano_agent.hooks.base import AgentHook, HookResult, NoOpHook
from nano_agent.hooks.permission import (
    PermissionDeniedError,
    PermissionHook,
    PermissionPolicy,
)
from nano_agent.hooks.rate_limit import RateLimitHook

__all__ = [
    "AgentHook",
    "AuditHook",
    "HookResult",
    "NoOpHook",
    "PermissionDeniedError",
    "PermissionHook",
    "PermissionPolicy",
    "RateLimitHook",
    "ToolAuditRecord",
]
