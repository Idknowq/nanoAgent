"""Agent loop hook extension points."""

from nano_agent.hooks.base import AgentHook, HookResult, NoOpHook
from nano_agent.hooks.permission import (
    PermissionDeniedError,
    PermissionHook,
    PermissionPolicy,
)

__all__ = [
    "AgentHook",
    "HookResult",
    "NoOpHook",
    "PermissionDeniedError",
    "PermissionHook",
    "PermissionPolicy",
]
