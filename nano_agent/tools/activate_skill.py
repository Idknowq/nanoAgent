from __future__ import annotations

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.persistence.skill_activation_store import SkillActivationStore
from nano_agent.skills.registry import SkillFormatError
from nano_agent.skills.session import SkillSession
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolResult
from nano_agent.tools.errors import ToolInputError


class ActivateSkillInput(ToolInput):
    name: str = Field(min_length=1)  # 需要加载完整正文的已注册 Skill 名称。


class ActivateSkillTool(RuntimeTool):
    """Activate one registered skill and make its body available next turn."""

    name = "activate_skill"
    description = (
        "Load the complete instructions for one available skill by name. "
        "Use only when its metadata clearly matches the task and the specialized procedure "
        "will materially improve the next actions; activation adds a model turn."
    )
    approval_level = ApprovalLevel.READ
    category = "skills"
    input_model = ActivateSkillInput
    input_schema = ActivateSkillInput.model_json_schema()

    def __init__(
        self,
        session: SkillSession,
        activation_store: SkillActivationStore | None = None,
    ) -> None:
        self.session = session  # 保存当前 run 的 Skill 激活状态。
        self.activation_store = activation_store  # 可选的激活审计存储。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        name = input_data["name"]
        try:
            loaded, newly_activated = self.session.activate(name)
        except (KeyError, SkillFormatError) as exc:
            raise ToolInputError(str(exc)) from exc

        if self.activation_store is not None:
            self.activation_store.append(
                context=context,
                skill=loaded,
                newly_activated=newly_activated,
            )
        status = "activated" if newly_activated else "already active"
        return ToolResult(
            success=True,
            summary=f"skill '{name}' {status}",
            data={
                "name": name,
                "newly_activated": newly_activated,
                "content_sha256": loaded.content_sha256,
            },
        )
