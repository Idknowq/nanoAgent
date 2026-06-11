from __future__ import annotations

import json
import time

from nano_agent.hooks.base import AgentHook
from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, LLMResponse, RunStatus, RunSummary, ToolCallRecord
from nano_agent.services.llm import LLMClient
from nano_agent.tools.base import ToolContext, ToolRegistry, ToolResult


class AgentLoop:
    """Claude Code 风格的核心循环：LLM 响应、工具调用、工具结果回填、继续循环。"""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        tools: ToolRegistry,
        context: ToolContext,
        hooks: list[AgentHook] | None = None,
    ) -> None:
        self.config = config  # 保存最大步数等循环控制配置。
        self.llm = llm  # 保存当前使用的 LLM 客户端。
        self.tools = tools  # 保存本轮 Agent 可调用的工具注册表。
        self.context = context  # 保存本轮 Agent 的工具运行上下文。
        self.hooks = hooks or []  # 保存 loop 扩展点列表。

    def run(self, run: RunSummary, initial_messages: list[AgentMessage]) -> RunSummary:
        messages = list(initial_messages)
        run.messages = messages

        for step_index in range(self.config.max_steps):
            tool_specs = self.tools.specs()
            try:
                for hook in self.hooks:
                    hook.before_llm_call(self.context, messages, tool_specs)
                response = self.llm.complete(messages=messages, tools=tool_specs)
                for hook in self.hooks:
                    hook.after_llm_call(self.context, response)
            except Exception as exc:
                for hook in self.hooks:
                    hook.on_error(self.context, exc)
                raise

            self._print_progress(step_index + 1, response)
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
                try:
                    tool = self.tools.get(tool_use.name)
                except KeyError:
                    result = ToolResult.failure(
                        code="tool_not_found",
                        message=f"Tool not found: {tool_use.name}",
                    )
                    run.tool_calls.append(
                        ToolCallRecord(
                            tool_name=tool_use.name,
                            input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                            output_summary=result.summary,
                            approval_level="read",
                            duration_seconds=0.0,
                            success=False,
                        )
                    )
                    messages.append(
                        AgentMessage(
                            role="tool",
                            content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                            tool_call_id=tool_use.id,
                        )
                    )
                    continue
                started = time.monotonic()
                try:
                    for hook in self.hooks:
                        hook.before_tool_call(self.context, tool, tool_use)
                    result = tool.invoke(tool_use.input, self.context)
                    for hook in self.hooks:
                        hook.after_tool_call(self.context, tool, tool_use, result)
                except Exception as exc:
                    for hook in self.hooks:
                        hook.on_error(self.context, exc)
                    raise
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

    def _print_progress(self, step: int, response: LLMResponse) -> None:
        if response.stop_reason == "tool_use":
            tool_names = ", ".join(tool_use.name for tool_use in response.tool_uses)
            print(
                f"[{step}/{self.config.max_steps}] LLM response | "
                f"tool_use \u2192 {tool_names or 'no tools'}"
            )
            return
        print(f"[{step}/{self.config.max_steps}] LLM response | end_turn \u2192 succeeded")
