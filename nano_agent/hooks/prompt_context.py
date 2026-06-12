from __future__ import annotations

from nano_agent.context.snapshot import RunContextBuilder, RunContextSnapshot
from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import AgentMessage
from nano_agent.prompts.assembler import PromptAssembler
from nano_agent.tools.base import ToolContext, ToolSpec


class PromptContextHook(NoOpHook):
    """Append changed runtime context without rewriting conversation history."""

    def __init__(self, context_builder: RunContextBuilder | None = None) -> None:
        self.context_builder = context_builder or RunContextBuilder()  # 构建运行状态快照。
        self._last_snapshot: RunContextSnapshot | None = None  # 上一次 LLM 调用前的状态。

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
        if self._last_snapshot is None:
            self._last_snapshot = snapshot
            return None
        update = self.context_builder.diff(self._last_snapshot, snapshot)
        self._last_snapshot = snapshot
        if update.has_changes:
            return HookResult(
                injected_messages=[PromptAssembler.context_update_message(update)]
            )
        return None
