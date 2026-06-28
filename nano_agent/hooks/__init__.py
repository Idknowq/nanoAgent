"""Agent loop hook extension points."""

from nano_agent.hooks.audit import AuditHook, ToolAuditRecord
from nano_agent.hooks.base import AgentHook, HookResult, NoOpHook
from nano_agent.hooks.console import (
    ConsoleEvent,
    ConsoleEventType,
    ConsoleProgressHook,
    ConsoleRenderer,
    ConsoleSection,
    ConsoleSectionProvider,
    RichConsoleRenderer,
)
from nano_agent.hooks.llm_metrics import LLMCallRecord, LLMMetricsHook
from nano_agent.hooks.permission import (
    PermissionDeniedError,
    PermissionHook,
    PermissionPolicy,
)
from nano_agent.hooks.pipeline import HookPipeline

__all__ = [
    "AgentHook",
    "AuditHook",
    "ConsoleEvent",
    "ConsoleEventType",
    "ConsoleProgressHook",
    "ConsoleRenderer",
    "ConsoleSection",
    "ConsoleSectionProvider",
    "HookResult",
    "HookPipeline",
    "LLMCallRecord",
    "LLMMetricsHook",
    "NoOpHook",
    "PermissionDeniedError",
    "PermissionHook",
    "PermissionPolicy",
    "RichConsoleRenderer",
    "ToolAuditRecord",
]
