from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from nano_agent.hooks.base import AgentHook, HookResult
from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, RunStatus, RunSummary, ToolCallRecord
from nano_agent.persistence.message_store import MessageStore
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
        message_store: MessageStore | None = None,
    ) -> None:
        self.config = config  # 保存最大步数等循环控制配置。
        self.llm = llm  # 保存当前使用的 LLM 客户端。
        self.tools = tools  # 保存本轮 Agent 可调用的工具注册表。
        self.context = context  # 保存本轮 Agent 的工具运行上下文。
        self.hooks = hooks or []  # 保存 loop 扩展点列表。
        self.message_store = message_store

    def run(self, run: RunSummary, initial_messages: list[AgentMessage]) -> RunSummary:
        messages = list(initial_messages)
        run.messages = messages
        if self.message_store is not None:
            self.message_store.append_many(messages)

        for step_index in range(self.config.max_steps):
            self.context.current_step = step_index + 1
            self.context.max_steps = self.config.max_steps
            self.context.current_llm_call_id = f"llm-{self.context.current_step}"
            self.context.current_llm_started_at = None
            self.context.current_llm_duration_seconds = None
            run.steps = self.context.current_step
            run.llm_call_count += 1
            tool_specs = self.tools.specs()
            deferred_hook_messages: list[AgentMessage] = []
            started: float | None = None
            try:
                for hook in self.hooks:
                    self._append_hook_messages_to_conversation(
                        messages,
                        hook.before_llm_call(self.context, messages, tool_specs),
                    )
                self.context.current_llm_started_at = datetime.now(timezone.utc)
                started = time.monotonic()
                response = self.llm.complete(messages=messages, tools=tool_specs)
                self.context.current_llm_duration_seconds = time.monotonic() - started
                for hook in self.hooks:
                    self._append_hook_messages(
                        deferred_hook_messages,
                        hook.after_llm_call(self.context, response),
                    )
            except Exception as exc:
                if started is not None:
                    self.context.current_llm_duration_seconds = time.monotonic() - started
                for hook in self.hooks:
                    hook.on_error(self.context, exc)
                raise

            self._append_messages(
                messages,
                [
                    AgentMessage(
                        role="assistant",
                        content=response.content,
                        tool_uses=response.tool_uses,
                    )
                ],
            )

            if response.stop_reason == "end_turn":
                self._append_messages(messages, deferred_hook_messages)
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
                            approval_level="read",  # type: ignore
                            duration_seconds=0.0,
                            success=False,
                        )
                    )
                    self._append_messages(
                        messages,
                        [
                            AgentMessage(
                                role="tool",
                                content=json.dumps(
                                    result.model_dump(mode="json"), ensure_ascii=False
                                ),
                                tool_call_id=tool_use.id,
                            )
                        ],
                    )
                    continue
                started = time.monotonic()
                try:
                    for hook in self.hooks:
                        self._append_hook_messages(
                            deferred_hook_messages,
                            hook.before_tool_call(self.context, tool, tool_use),
                        )
                    result = tool.invoke(tool_use.input, self.context)
                    duration = time.monotonic() - started
                    for hook in self.hooks:
                        self._append_hook_messages(
                            deferred_hook_messages,
                            hook.after_tool_call(
                                self.context,
                                tool,
                                tool_use,
                                result,
                                duration,
                            ),
                        )
                except Exception as exc:
                    for hook in self.hooks:
                        hook.on_error(self.context, exc)
                    raise
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
                self._append_messages(
                    messages,
                    [
                        AgentMessage(
                            role="tool",
                            content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                            tool_call_id=tool_use.id,
                        )
                    ],
                )

            self._append_messages(messages, deferred_hook_messages)
            run.messages = messages

        run.status = RunStatus.FAILED
        run.notes.append(f"Agent loop exceeded max_steps={self.config.max_steps}")
        run.messages = messages
        return run

    def _append_hook_messages(
        self,
        target: list[AgentMessage],
        result: HookResult | None,
    ) -> None:
        if result is not None:
            target.extend(result.injected_messages)

    def _append_hook_messages_to_conversation(
        self,
        target: list[AgentMessage],
        result: HookResult | None,
    ) -> None:
        if result is not None:
            self._append_messages(target, result.injected_messages)

    def _append_messages(
        self,
        target: list[AgentMessage],
        messages: list[AgentMessage],
    ) -> None:
        target.extend(messages)
        if self.message_store is not None:
            self.message_store.append_many(messages, self.context.current_llm_call_id)
