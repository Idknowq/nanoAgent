from __future__ import annotations

import hashlib

from nano_agent.context.snapshot import RunContextBuilder
from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import AgentMessage
from nano_agent.prompts.assembler import PromptAssembler
from nano_agent.tools.base import ToolContext, ToolSpec


class PromptContextHook(NoOpHook):
    """Append changed runtime context without rewriting conversation history."""

    def __init__(self, context_builder: RunContextBuilder | None = None) -> None:
        self.context_builder = context_builder or RunContextBuilder()  # 构建运行状态快照。
        self._last_context_hash: str | None = None  # 最近一次上下文快照摘要。

    def before_llm_call(
        self,
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> HookResult | None:
        del tools
        snapshot = self.context_builder.build(
            repo_url=context.repo_url,
            workspace_path=context.workspace_path,
            current_step=context.current_step,
            max_steps=context.max_steps,
            messages=messages,
        )
        context_message = PromptAssembler.context_message(snapshot)
        semantic_context = snapshot.model_dump(exclude={"current_step", "max_steps"})
        context_hash = hashlib.sha256(repr(semantic_context).encode("utf-8")).hexdigest()
        has_tool_results = any(message.role == "tool" for message in messages)
        if self._last_context_hash is None and not has_tool_results:
            self._last_context_hash = context_hash
        if context_hash != self._last_context_hash:
            self._last_context_hash = context_hash
            return HookResult(injected_messages=[context_message])
        return None
