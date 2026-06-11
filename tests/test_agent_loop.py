from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.base import NoOpHook
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.permissions.errors import PermissionDeniedError
from nano_agent.services.llm import LLMClient
from nano_agent.tools.base import ToolContext, ToolRegistry, build_default_tool_registry
from nano_agent.tools.bash import BashTool
from nano_agent.tools.todo import TodoWriteTool


class OneToolUseLLM:
    """测试用 LLM，第一轮请求工具，第二轮结束。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录 LLM 被调用次数。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="call bash",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="toolu_1",
                        name="bash",
                        input={"command": "printf hello"},
                    )
                ],
            )
        return LLMResponse(content="end_turn", stop_reason="end_turn")


class RecordingHook(NoOpHook):
    """测试用 hook，记录 loop 扩展点是否被调用。"""

    def __init__(self) -> None:
        self.events: list[str] = []  # 保存 hook 调用事件名称。

    def before_llm_call(self, context, messages, tools):  # type: ignore[no-untyped-def]
        self.events.append("before_llm_call")

    def after_llm_call(self, context, response):  # type: ignore[no-untyped-def]
        self.events.append("after_llm_call")

    def before_tool_call(self, context, tool, tool_use):  # type: ignore[no-untyped-def]
        self.events.append("before_tool_call")

    def after_tool_call(self, context, tool, tool_use, result):  # type: ignore[no-untyped-def]
        self.events.append("after_tool_call")


def test_agent_loop_executes_tool_and_records_result(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=config,
    )
    tools = ToolRegistry([BashTool(config=config, cwd=tmp_path)])
    loop = AgentLoop(config=config, llm=llm, tools=tools, context=context)
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    result = loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert result.status == "succeeded"
    assert result.tool_calls[0].tool_name == "bash"
    assert result.tool_calls[0].success
    assert any(message.role == "tool" for message in result.messages)


def test_agent_loop_calls_hooks(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=config,
    )
    tools = ToolRegistry([BashTool(config=config, cwd=tmp_path)])
    hook = RecordingHook()
    loop = AgentLoop(config=config, llm=llm, tools=tools, context=context, hooks=[hook])
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert "before_llm_call" in hook.events
    assert "after_llm_call" in hook.events
    assert "before_tool_call" in hook.events
    assert "after_tool_call" in hook.events


def test_default_tool_registry_exposes_metadata(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=config,
    )

    specs = build_default_tool_registry(context).specs()

    bash = next(spec for spec in specs if spec.name == "bash")
    assert bash.category == "execution"
    assert bash.requires_workspace
    assert bash.is_mutating


def test_permission_hook_rejects_unapproved_bash(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=config,
    )
    tools = ToolRegistry([BashTool(config=config, cwd=tmp_path)])
    loop = AgentLoop(
        config=config,
        llm=llm,
        tools=tools,
        context=context,
        hooks=build_default_hooks(config),
    )
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    with pytest.raises(PermissionDeniedError):
        loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])


def test_permission_hook_allows_bash_with_auto_approve(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5, auto_approve=True)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=config,
    )
    tools = ToolRegistry([BashTool(config=config, cwd=tmp_path)])
    loop = AgentLoop(
        config=config,
        llm=llm,
        tools=tools,
        context=context,
        hooks=build_default_hooks(config),
    )
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    result = loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert result.status == "succeeded"


def test_todo_write_is_optional_tool() -> None:
    config = AgentConfig()
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=Path("."),
        config=config,
    )
    tool = TodoWriteTool()

    result = tool.run({"action": "add", "title": "Inspect README"}, context)

    assert result.success
    assert result.data["todos"][0]["title"] == "Inspect README"
