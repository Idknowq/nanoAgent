from __future__ import annotations

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.subagents.manager import SubagentManager
from nano_agent.subagents.models import SubagentRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolResult


class DelegateTaskInput(ToolInput):
    task: str = Field(min_length=1)  # 需要子 Agent 独立完成的任务描述。
    context: str | None = None  # 显式传递给子 Agent 的背景信息。
    allowed_tools: tuple[str, ...] = ()  # 请求授予子 Agent 的业务工具名称。
    max_steps: int | None = Field(default=None, ge=1)  # 请求的最大循环步骤数。
    max_llm_calls: int | None = Field(default=None, ge=1)  # 请求的 LLM 调用预算。


class DelegateTaskTool(RuntimeTool):
    """Delegate one scoped task to an isolated, synchronously executed subagent."""

    name = "delegate_task"  # 工具注册名称。
    description = (
        "Delegate one bounded, independent, read-heavy investigation to an isolated subagent. "
        "Use when examining several files or a separate subsystem would consume substantial "
        "main-context space. Pass only necessary context and the narrowest useful tools. "
        "The parent transcript is not copied and the subagent returns a bounded result."
    )  # 暴露给 LLM 的工具用途说明。
    approval_level = ApprovalLevel.READ  # 委派工具自身不直接修改工作区。
    category = "delegation"  # 工具所属的功能分类。
    input_model = DelegateTaskInput  # 工具输入参数校验模型。
    input_schema = DelegateTaskInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager  # 执行子 Agent 创建、运行和结果收集。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        if context.delegation_depth > 0 or context.subagent_id is not None:
            return ToolResult.failure(
                code="recursive_delegation_denied",
                message="Subagents cannot create other subagents.",
            )
        config = context.config
        task = input_data["task"]
        delegated_context = input_data["context"]
        if len(task) > config.subagent_max_task_chars:
            return ToolResult.failure(
                code="task_too_long",
                message=f"task exceeds {config.subagent_max_task_chars} characters",
            )
        if (
            delegated_context is not None
            and len(delegated_context) > config.subagent_max_context_chars
        ):
            return ToolResult.failure(
                code="context_too_long",
                message=f"context exceeds {config.subagent_max_context_chars} characters",
            )
        request = SubagentRequest(
            task=task,
            context=delegated_context,
            allowed_tools=input_data["allowed_tools"],
            max_steps=min(
                input_data["max_steps"] or config.subagent_max_steps,
                config.subagent_max_steps,
            ),
            max_llm_calls=min(
                input_data["max_llm_calls"] or config.subagent_max_llm_calls,
                config.subagent_max_llm_calls,
            ),
        )
        try:
            result = self.manager.run(request)
        except ValueError as exc:
            return ToolResult.failure(code="invalid_subagent_request", message=str(exc))
        return ToolResult(
            success=result.status == "succeeded",
            summary=f"{result.subagent_id} finished with status {result.status.value}",
            data={
                "subagent_result": result.model_dump(
                    mode="json",
                    exclude={"completion_report"},
                )
            },
            error_code=result.error_kind.value if result.error_kind else None,
            error_message=result.error,
        )
