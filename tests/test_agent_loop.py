from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.services.llm import LLMClient
from nano_agent.tools.base import ToolRegistry
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


def test_agent_loop_executes_tool_and_records_result(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    tools = ToolRegistry([BashTool(config=config, cwd=tmp_path)])
    loop = AgentLoop(config=config, llm=llm, tools=tools)
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    result = loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert result.status == "succeeded"
    assert result.tool_calls[0].tool_name == "bash"
    assert result.tool_calls[0].success
    assert any(message.role == "tool" for message in result.messages)


def test_todo_write_is_optional_tool() -> None:
    tool = TodoWriteTool()

    result = tool.run({"action": "add", "title": "Inspect README"})

    assert result.success
    assert result.data["todos"][0]["title"] == "Inspect README"
