"""Agent loop hook extension points."""

from nano_agent.hooks.permission import (
    PermissionDeniedError,
    PermissionHook,
    PermissionPolicy,
)

__all__ = ["PermissionDeniedError", "PermissionHook", "PermissionPolicy"]
