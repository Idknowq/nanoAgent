from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.rate_limit import RateLimitHook
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.tools.base import ToolContext, ToolRegistry
from nano_agent.tools.read_file import ReadFileTool
from nano_agent.tools.todo import TodoWriteTool


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=AgentConfig(workspace_root=tmp_path),
    )


def tool_use(name: str, call_id: int) -> ToolUseRequest:
    return ToolUseRequest(id=f"call-{call_id}", name=name)


class RepeatingTodoLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.saw_reminder = False

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.saw_reminder = self.saw_reminder or any(
            message.role == "system" and "consecutive times" in message.content
            for message in messages
        )
        if self.calls <= 3:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id=f"todo-{self.calls}",
                        name="todo_write",
                        input={"action": "add", "title": f"Task {self.calls}"},
                    )
                ],
            )
        return LLMResponse(content="done", stop_reason="end_turn")


def test_rate_limit_warns_after_consecutive_threshold(tmp_path: Path) -> None:
    hook = RateLimitHook(max_consecutive_calls=2)
    tool = ReadFileTool()
    context = make_context(tmp_path)

    first = hook.before_tool_call(context, tool, tool_use(tool.name, 1))
    second = hook.before_tool_call(context, tool, tool_use(tool.name, 2))
    third = hook.before_tool_call(context, tool, tool_use(tool.name, 3))

    assert first is None
    assert second is None
    assert third is not None
    assert "3 consecutive times" in third.injected_messages[0].content
    assert hook.consecutive_calls == 3


def test_rate_limit_resets_when_tool_name_changes(tmp_path: Path) -> None:
    hook = RateLimitHook(max_consecutive_calls=2)
    read_file = ReadFileTool()
    todo = TodoWriteTool()
    context = make_context(tmp_path)

    hook.before_tool_call(context, read_file, tool_use(read_file.name, 1))
    hook.before_tool_call(context, read_file, tool_use(read_file.name, 2))
    switched = hook.before_tool_call(context, todo, tool_use(todo.name, 3))
    next_read = hook.before_tool_call(context, read_file, tool_use(read_file.name, 4))

    assert switched is None
    assert next_read is None
    assert hook.consecutive_calls == 1


def test_rate_limit_continues_warning_without_blocking(tmp_path: Path) -> None:
    hook = RateLimitHook(max_consecutive_calls=1)
    tool = TodoWriteTool()
    context = make_context(tmp_path)

    hook.before_tool_call(context, tool, tool_use(tool.name, 1))
    second = hook.before_tool_call(context, tool, tool_use(tool.name, 2))
    third = hook.before_tool_call(context, tool, tool_use(tool.name, 3))

    assert second is not None
    assert third is not None
    assert "2 consecutive times" in second.injected_messages[0].content
    assert "3 consecutive times" in third.injected_messages[0].content


def test_rate_limit_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RateLimitHook(max_consecutive_calls=0)


def test_rate_limit_injects_reminder_without_blocking_loop(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path, max_steps=4)
    context = make_context(tmp_path)
    llm = RepeatingTodoLLM()
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry([TodoWriteTool()]),
        context=context,
        hooks=[RateLimitHook(max_consecutive_calls=2)],
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "succeeded"
    assert len(result.tool_calls) == 3
    assert all(call.success for call in result.tool_calls)
    assert llm.saw_reminder
