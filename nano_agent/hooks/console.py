from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field
from rich.console import Console
from rich.text import Text

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
    type: ConsoleEventType  # 生命周期事件类型。
    run_id: str  # 当前 Agent run 标识。
    step: int  # 当前主循环步骤。
    max_steps: int  # 主循环最大步骤数。
    tool_name: str | None = None  # 工具事件对应的工具名。
    tool_input_summary: str | None = None  # 工具关键输入的紧凑摘要。
    result_summary: str | None = None  # 工具结果或错误摘要。
    success: bool | None = None  # 工具或 LLM 调用是否成功。
    duration_seconds: float | None = None  # 调用耗时。
    provider: str | None = None  # LLM provider。
    model: str | None = None  # LLM 模型名。
    stop_reason: str | None = None  # LLM 停止原因。
    requested_tool_count: int = 0  # LLM 请求的工具数量。
    attempt_type: str = "primary"  # primary、transient、continuation 或 reactive。
    attempt_index: int = 0  # 当前恢复类型内的尝试序号。
    retry_delay_seconds: float | None = None  # transient 请求前等待时间。
    input_tokens: int | None = None  # LLM 输入 token 数。
    output_tokens: int | None = None  # LLM 输出 token 数。
    cached_tokens: int | None = None  # LLM 缓存命中 token 数。


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
        if event.type == ConsoleEventType.LLM_STARTED:
            attempt = ""
            if event.attempt_type != "primary":
                attempt = f" {event.attempt_type} {event.attempt_index}"
            delay = (
                f" after {event.retry_delay_seconds:.2f}s"
                if event.retry_delay_seconds is not None
                else ""
            )
            self.console.print(
                Text(
                    f"● LLM {event.step}/{event.max_steps}{attempt} request{delay}",
                    style="bold cyan",
                )
            )
            return
        if event.type == ConsoleEventType.LLM_COMPLETED:
            self.console.print(self._llm_completed(event))
            return
        if event.type == ConsoleEventType.TOOL_STARTED:
            detail = f"  {event.tool_input_summary}" if event.tool_input_summary else ""
            self.console.print(
                Text(f"→ {event.tool_name}{detail}", style="bold blue")
            )
            return
        if event.type == ConsoleEventType.TOOL_COMPLETED:
            marker = "✓" if event.success else "✗"
            style = "green" if event.success else "bold red"
            duration = f"  {event.duration_seconds:.2f}s" if event.duration_seconds is not None else ""
            detail = f"  {event.result_summary}" if event.result_summary else ""
            self.console.print(
                Text(f"{marker} {event.tool_name}{duration}{detail}", style=style)
            )
            return
        self.console.print(
            Text(f"✗ {event.result_summary or 'Unknown error'}", style="bold red")
        )

    def render_sections(self, sections: list[ConsoleSection]) -> None:
        for section in sections:
            self.console.print(Text(section.title, style="bold"))
            for line in section.lines:
                self.console.print(Text(f"  {line}", style="dim"))

    @staticmethod
    def _llm_completed(event: ConsoleEvent) -> Text:
        model = event.model or event.provider or "unknown-model"
        duration = f"{event.duration_seconds:.2f}s" if event.duration_seconds is not None else "-"
        parts = [f"✓ LLM {event.step}/{event.max_steps}", model, duration]
        if event.input_tokens is not None:
            token_detail = f"in {RichConsoleRenderer._format_tokens(event.input_tokens)}" # type: ignore
            if event.output_tokens is not None:
                token_detail += (
                    f" · out {RichConsoleRenderer._format_tokens(event.output_tokens)}" # type: ignore
                )
            if event.cached_tokens is not None and event.input_tokens > 0:
                token_detail += f" · cache {event.cached_tokens / event.input_tokens:.0%}"
            parts.append(token_detail)
        parts.append(
            f"{event.requested_tool_count} tool(s)"
            if event.requested_tool_count
            else str(event.stop_reason or "end_turn")
        )
        return Text("  ".join(parts), style="cyan")


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
            attempt_type=context.current_llm_attempt_type,
            attempt_index=context.current_llm_attempt_index,
            retry_delay_seconds=context.current_llm_retry_delay_seconds,
        )
        return None

    def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> HookResult | None:
        usage = response.usage
        self._render_event(
            context,
            ConsoleEventType.LLM_COMPLETED,
            provider=response.provider or context.config.llm_provider,
            model=response.model or context.config.llm_model,
            stop_reason=response.stop_reason,
            requested_tool_count=len(response.tool_uses),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached_tokens=usage.cached_tokens if usage else None,
            duration_seconds=context.current_llm_duration_seconds,
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
            tool_name=tool.name,
            tool_input_summary=self._tool_input_summary(tool_use),
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
        self._render_event(
            context,
            ConsoleEventType.TOOL_COMPLETED,
            tool_name=tool.name,
            success=result.success,
            duration_seconds=duration_seconds,
            result_summary=(result.error_message or result.summary)[:200],
        )
        self._render_sections(context, tool=tool, tool_use=tool_use, result=result)
        return None

    def on_error(self, context: ToolContext, error: Exception) -> HookResult | None:
        self._render_event(
            context,
            ConsoleEventType.ERROR,
            result_summary=f"{type(error).__name__}: {error}",
        )
        return None

    def _render_event(
        self,
        context: ToolContext,
        event_type: ConsoleEventType,
        *,
        tool_name: str | None = None,
        tool_input_summary: str | None = None,
        result_summary: str | None = None,
        success: bool | None = None,
        duration_seconds: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        stop_reason: str | None = None,
        requested_tool_count: int = 0,
        attempt_type: str = "primary",
        attempt_index: int = 0,
        retry_delay_seconds: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_tokens: int | None = None,
    ) -> None:
        event = ConsoleEvent(
            type=event_type,
            run_id=context.run_id,
            step=context.current_step,
            max_steps=context.max_steps,
            tool_name=tool_name,
            tool_input_summary=tool_input_summary,
            result_summary=result_summary,
            success=success,
            duration_seconds=duration_seconds,
            provider=provider,
            model=model,
            stop_reason=stop_reason,
            requested_tool_count=requested_tool_count,
            attempt_type=attempt_type,
            attempt_index=attempt_index,
            retry_delay_seconds=retry_delay_seconds,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        try:
            self.renderer.render_event(event)
        except Exception as exc:  # noqa: BLE001 - console failures must not stop the Agent.
            self._render_errors.append(str(exc))

    @staticmethod
    def _tool_input_summary(tool_use: ToolUseRequest) -> str:
        input_data = tool_use.input
        if tool_use.name in {"read_file", "edit_file", "list_files"}:
            return str(input_data.get("path", "."))
        if tool_use.name == "run_command":
            program = str(input_data.get("program", ""))
            args = " ".join(str(value) for value in input_data.get("args", []))
            return f"{program} {args}".strip()[:160]
        if tool_use.name == "activate_skill":
            return str(input_data.get("name", ""))
        if tool_use.name == "finish_run":
            return str(input_data.get("status", ""))
        return ""

    @staticmethod
    def _format_tokens(value: int) -> str:
        if value < 1_000:
            return str(value)
        return f"{value / 1_000:.1f}k"

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
