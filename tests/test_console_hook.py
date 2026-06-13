from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from nano_agent.config import AgentConfig
from nano_agent.hooks.console import (
    ConsoleEvent,
    ConsoleEventType,
    ConsoleProgressHook,
    ConsoleSection,
    RichConsoleRenderer,
)
from nano_agent.hooks.permission import PermissionDeniedError, PermissionHook, PermissionPolicy
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, LLMUsage, RunSummary, ToolUseRequest
from nano_agent.tools.base import ToolContext, ToolRegistry, ToolResult
from nano_agent.tools.run_command import RunCommandTool
from nano_agent.tools.todo import TodoWriteTool


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "run-1",
        config=AgentConfig(workspace_root=tmp_path),
        current_step=2,
        max_steps=20,
    )


class RecordingRenderer:
    def __init__(self) -> None:
        self.events: list[ConsoleEvent] = []
        self.sections: list[ConsoleSection] = []

    def render_event(self, event: ConsoleEvent) -> None:
        self.events.append(event)

    def render_sections(self, sections: list[ConsoleSection]) -> None:
        self.sections.extend(sections)


class StaticSectionProvider:
    def build_sections(self, context, **kwargs):  # type: ignore[no-untyped-def]
        return [ConsoleSection(key="todo", title="Todos", lines=["[pending] Inspect"])]


class FailingRenderer:
    def render_event(self, event):  # type: ignore[no-untyped-def]
        raise OSError("console unavailable")

    def render_sections(self, sections):  # type: ignore[no-untyped-def]
        raise OSError("section unavailable")


class RiskyCommandLLM:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="call-1",
                    name="run_command",
                    input={"program": "python3", "args": ["-c", "print('hello')"]},
                )
            ],
        )


def test_console_hook_renders_llm_lifecycle(tmp_path: Path) -> None:
    renderer = RecordingRenderer()
    hook = ConsoleProgressHook(renderer=renderer)
    context = make_context(tmp_path)

    hook.before_llm_call(context, [], [])
    hook.after_llm_call(
        context,
        LLMResponse(
            stop_reason="tool_use",
            provider="test",
            model="test-model",
            usage=LLMUsage(input_tokens=100, output_tokens=20, cached_tokens=50),
            tool_uses=[ToolUseRequest(id="call-1", name="read_file")],
        ),
    )
    hook.after_llm_call(context, LLMResponse(stop_reason="end_turn"))

    assert [event.type for event in renderer.events] == [
        ConsoleEventType.LLM_STARTED,
        ConsoleEventType.LLM_COMPLETED,
        ConsoleEventType.LLM_COMPLETED,
    ]
    assert renderer.events[0].step == 2
    assert renderer.events[1].model == "test-model"
    assert renderer.events[1].requested_tool_count == 1
    assert renderer.events[1].input_tokens == 100
    assert renderer.events[1].cached_tokens == 50
    assert renderer.events[2].stop_reason == "end_turn"


def test_console_hook_renders_tool_success_failure_and_sections(tmp_path: Path) -> None:
    renderer = RecordingRenderer()
    hook = ConsoleProgressHook(
        renderer=renderer,
        section_providers=[StaticSectionProvider()],
    )
    context = make_context(tmp_path)
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(id="call-1", name=tool.name)

    hook.before_tool_call(context, tool, tool_use)
    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="ok"),
        0.125,
    )
    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult.failure(code="invalid_input", message="bad input"),
        0.01,
    )

    assert renderer.events[0].type == ConsoleEventType.TOOL_STARTED
    assert renderer.events[0].tool_name == "todo_write"
    assert renderer.events[1].result_summary == "ok"
    assert renderer.events[1].duration_seconds == 0.125
    assert renderer.events[1].success
    assert renderer.events[2].result_summary == "bad input"
    assert not renderer.events[2].success
    assert [section.key for section in renderer.sections] == ["todo", "todo"]


def test_console_hook_renders_errors(tmp_path: Path) -> None:
    renderer = RecordingRenderer()
    hook = ConsoleProgressHook(renderer=renderer)

    hook.on_error(make_context(tmp_path), RuntimeError("broken"))

    assert renderer.events[0].type == ConsoleEventType.ERROR
    assert renderer.events[0].result_summary == "RuntimeError: broken"


def test_console_hook_isolates_renderer_errors(tmp_path: Path) -> None:
    hook = ConsoleProgressHook(
        renderer=FailingRenderer(),
        section_providers=[StaticSectionProvider()],
    )
    context = make_context(tmp_path)
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(id="call-1", name=tool.name)

    hook.before_llm_call(context, [], [])
    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="ok"),
        0.01,
    )

    assert hook.render_errors == ["console unavailable", "console unavailable", "section unavailable"]
    errors = hook.render_errors
    errors.append("external mutation")
    assert "external mutation" not in hook.render_errors


def test_rich_console_renderer_outputs_events_and_sections() -> None:
    output = StringIO()
    renderer = RichConsoleRenderer(
        Console(file=output, color_system=None, force_terminal=False, width=120)
    )
    event = ConsoleEvent(
        type=ConsoleEventType.LLM_STARTED,
        run_id="run-1",
        step=1,
        max_steps=20,
    )

    renderer.render_event(event)
    renderer.render_sections(
        [ConsoleSection(key="run", title="Run", lines=["step: 1/20", "status: running"])]
    )

    assert output.getvalue().splitlines() == [
        "● LLM 1/20 request",
        "Run",
        "  step: 1/20",
        "  status: running",
    ]


def test_permission_rejection_renders_error_without_tool_running(tmp_path: Path) -> None:
    renderer = RecordingRenderer()
    console_hook = ConsoleProgressHook(renderer=renderer)
    context = make_context(tmp_path)
    loop = AgentLoop(
        config=context.config,
        llm=RiskyCommandLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry([RunCommandTool()]),
        context=context,
        hooks=[PermissionHook(PermissionPolicy()), console_hook],
    )

    with pytest.raises(PermissionDeniedError):
        loop.run(
            RunSummary(run_id=context.run_id, repo_url=context.repo_url),
            [AgentMessage(role="user", content="start")],
        )

    event_types = [event.type for event in renderer.events]
    assert event_types == [
        ConsoleEventType.LLM_STARTED,
        ConsoleEventType.LLM_COMPLETED,
        ConsoleEventType.ERROR,
    ]
    assert ConsoleEventType.TOOL_STARTED not in event_types
    assert "PermissionDeniedError" in str(renderer.events[-1].result_summary)
