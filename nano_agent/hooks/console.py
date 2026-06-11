from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field
from rich.console import Console

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import LLMResponse, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class ConsoleEventType(StrEnum):
    LLM_STARTED = "llm_started"
    LLM_COMPLETED = "llm_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    ERROR = "error"


class ConsoleEvent(BaseModel):
    type: ConsoleEventType
    run_id: str
    step: int
    max_steps: int
    message: str
    tool_name: str | None = None
    success: bool | None = None
    duration_seconds: float | None = None


class ConsoleSection(BaseModel):
    key: str
    title: str
    lines: list[str] = Field(default_factory=list)


class ConsoleRenderer(Protocol):
    def render_event(self, event: ConsoleEvent) -> None:
        """Render one lifecycle event."""

    def render_sections(self, sections: list[ConsoleSection]) -> None:
        """Render additional status sections."""


class ConsoleSectionProvider(Protocol):
    def build_sections(
        self,
        context: ToolContext,
        *,
        tool: RuntimeTool | None = None,
        tool_use: ToolUseRequest | None = None,
        result: ToolResult | None = None,
    ) -> list[ConsoleSection]: # type: ignore
        """Build optional sections from the latest runtime state."""


class RichConsoleRenderer:
    """Default line-oriented renderer backed by Rich."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def render_event(self, event: ConsoleEvent) -> None:
        self.console.print(event.message, markup=False)

    def render_sections(self, sections: list[ConsoleSection]) -> None:
        for section in sections:
            self.console.print(section.title, markup=False)
            for line in section.lines:
                self.console.print(f"  {line}", markup=False)


class ConsoleProgressHook(NoOpHook):
    """Render Agent lifecycle progress without coupling output to AgentLoop."""

    def __init__(
        self,
        renderer: ConsoleRenderer | None = None,
        section_providers: list[ConsoleSectionProvider] | None = None,
    ) -> None:
        self.renderer = renderer or RichConsoleRenderer()
        self.section_providers = list(section_providers or [])
        self._render_errors: list[str] = []

    @property
    def render_errors(self) -> list[str]:
        return list(self._render_errors)

    def before_llm_call(self, context, messages, tools) -> HookResult | None:  # type: ignore[no-untyped-def]
        self._render_event(
            context,
            ConsoleEventType.LLM_STARTED,
            f"[{context.current_step}/{context.max_steps}] LLM request",
        )
        return None

    def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> HookResult | None:
        if response.stop_reason == "tool_use":
            tool_names = ", ".join(tool_use.name for tool_use in response.tool_uses)
            detail = f"tool_use -> {tool_names or 'no tools'}"
        else:
            detail = "end_turn"
        self._render_event(
            context,
            ConsoleEventType.LLM_COMPLETED,
            f"[{context.current_step}/{context.max_steps}] LLM response | {detail}",
        )
        return None

    def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> HookResult | None:
        self._render_event(
            context,
            ConsoleEventType.TOOL_STARTED,
            f"[{context.current_step}/{context.max_steps}] Tool {tool.name} | running",
            tool_name=tool.name,
        )
        return None

    def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> HookResult | None:
        status = "succeeded" if result.success else "failed"
        error_detail = f" | {result.error_code}" if result.error_code else ""
        self._render_event(
            context,
            ConsoleEventType.TOOL_COMPLETED,
            (
                f"[{context.current_step}/{context.max_steps}] Tool {tool.name} | "
                f"{status}{error_detail} | {duration_seconds:.2f}s"
            ),
            tool_name=tool.name,
            success=result.success,
            duration_seconds=duration_seconds,
        )
        self._render_sections(context, tool=tool, tool_use=tool_use, result=result)
        return None

    def on_error(self, context: ToolContext, error: Exception) -> HookResult | None:
        self._render_event(
            context,
            ConsoleEventType.ERROR,
            (
                f"[{context.current_step}/{context.max_steps}] Error | "
                f"{type(error).__name__}: {error}"
            ),
        )
        return None

    def _render_event(
        self,
        context: ToolContext,
        event_type: ConsoleEventType,
        message: str,
        *,
        tool_name: str | None = None,
        success: bool | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        event = ConsoleEvent(
            type=event_type,
            run_id=context.run_id,
            step=context.current_step,
            max_steps=context.max_steps,
            message=message,
            tool_name=tool_name,
            success=success,
            duration_seconds=duration_seconds,
        )
        try:
            self.renderer.render_event(event)
        except Exception as exc:  # noqa: BLE001 - console failures must not stop the Agent.
            self._render_errors.append(str(exc))

    def _render_sections(
        self,
        context: ToolContext,
        *,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
    ) -> None:
        try:
            sections: list[ConsoleSection] = []
            for provider in self.section_providers:
                sections.extend(
                    provider.build_sections(
                        context,
                        tool=tool,
                        tool_use=tool_use,
                        result=result,
                    )
                )
            if sections:
                self.renderer.render_sections(sections)
        except Exception as exc:  # noqa: BLE001 - status sections are observational only.
            self._render_errors.append(str(exc))
