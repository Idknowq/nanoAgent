from __future__ import annotations

import json
import time

from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, RunStatus, RunSummary, ToolCallRecord
from nano_agent.services.llm import LLMClient
from nano_agent.tools.base import ToolRegistry


class AgentLoop:
    """Claude Code 风格的核心循环：LLM 响应、工具调用、工具结果回填、继续循环。"""

    def __init__(self, config: AgentConfig, llm: LLMClient, tools: ToolRegistry) -> None:
        self.config = config  # 保存最大步数等循环控制配置。
        self.llm = llm  # 保存当前使用的 LLM 客户端。
        self.tools = tools  # 保存本轮 Agent 可调用的工具注册表。

    def run(self, run: RunSummary, initial_messages: list[AgentMessage]) -> RunSummary:
        messages = list(initial_messages)
        run.messages = messages

        for _ in range(self.config.max_steps):
            response = self.llm.complete(messages=messages, tools=self.tools.specs())
            messages.append(
                AgentMessage(
                    role="assistant",
                    content=response.content,
                    tool_uses=response.tool_uses,
                )
            )

            if response.stop_reason == "end_turn":
                run.status = RunStatus.SUCCEEDED
                run.messages = messages
                return run

            for tool_use in response.tool_uses:
                tool = self.tools.get(tool_use.name)
                started = time.monotonic()
                result = tool.run(tool_use.input)
                duration = time.monotonic() - started
                run.tool_calls.append(
                    ToolCallRecord(
                        tool_name=tool.name,
                        input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                        output_summary=result.summary,
                        approval_level=tool.approval_level,
                        duration_seconds=duration,
                        success=result.success,
                    )
                )
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                        tool_call_id=tool_use.id,
                    )
                )

            run.messages = messages

        run.status = RunStatus.FAILED
        run.notes.append(f"Agent loop exceeded max_steps={self.config.max_steps}")
        run.messages = messages
        return run
