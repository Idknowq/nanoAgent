from __future__ import annotations

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.prompts.assembler import PromptAssembler
from nano_agent.skills.session import SkillSession
from nano_agent.tools.activate_skill import ActivateSkillTool
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult
from nano_agent.models import ToolUseRequest


class SkillActivationHook(NoOpHook):
    """Append a newly activated skill body after its tool result."""

    def __init__(self, session: SkillSession) -> None:
        self.session = session  # 保存当前 run 已成功激活的 Skill。

    def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> HookResult | None:
        del context, duration_seconds
        if not isinstance(tool, ActivateSkillTool) or not result.success:
            return None
        if not result.data.get("newly_activated"):
            return None
        loaded = self.session.get(str(tool_use.input["name"]))
        return HookResult(
            injected_messages=[PromptAssembler.active_skill_message(loaded)]
        )
