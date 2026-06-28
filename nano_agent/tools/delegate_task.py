from __future__ import annotations

from collections import Counter

from pydantic import Field

from nano_agent.background.models import BackgroundJob, BackgroundJobStatus
from nano_agent.background.presentation import public_job_data, public_subagent_result
from nano_agent.background.supervisor import BackgroundJobSupervisor
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
    run_in_background: bool = False  # 是否立即返回 Job 句柄并在后台执行。
    task_id: str | None = Field(default=None, pattern=r"^task-\d+$")  # 可选的持久化 Task 关联。


class DelegatedTaskGetInput(ToolInput):
    job_id: str = Field(pattern=r"^job-\d+$")  # 需要查询的后台 Job 标识。


class DelegatedTaskListInput(ToolInput):
    status: BackgroundJobStatus | None = None  # 可选的 Job 状态过滤条件。


class DelegatedTaskCancelInput(ToolInput):
    job_id: str = Field(pattern=r"^job-\d+$")  # 需要取消的后台 Job 标识。


class DelegateTaskTool(RuntimeTool):
    """Delegate one scoped task to an isolated synchronous or background subagent."""

    name = "delegate_task"  # 工具注册名称。
    description = (
        "Delegate one bounded, independent, read-heavy investigation to an isolated subagent. "
        "Use when examining several files or a separate subsystem would consume substantial "
        "main-context space. Pass only necessary context and the narrowest useful tools. "
        "The parent transcript is not copied and the subagent returns a bounded result. When "
        "task_id is provided for background execution, the runtime manages that Task's "
        "execution status and result."
    )  # 暴露给 LLM 的工具用途说明。
    approval_level = ApprovalLevel.READ  # 委派工具自身不直接修改工作区。
    category = "delegation"  # 工具所属的功能分类。
    input_model = DelegateTaskInput  # 工具输入参数校验模型。
    input_schema = DelegateTaskInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(
        self,
        manager: SubagentManager,
        supervisor: BackgroundJobSupervisor | None = None,
    ) -> None:
        self.manager = manager  # 执行子 Agent 创建、运行和结果收集。
        self.supervisor = supervisor  # 可选的后台 Job 调度器。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
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
            if input_data["run_in_background"]:
                if self.supervisor is None:
                    return ToolResult.failure(
                        code="background_tasks_unavailable",
                        message="Background task execution is unavailable.",
                    )
                job = await self.supervisor.submit(request, task_id=input_data["task_id"])
                return ToolResult(
                    success=True,
                    summary=f"{job.job_id} queued for {job.subagent_id}",
                    data={
                        "background_job": _job_data(job, config.subagent_max_result_chars)
                    },
                )
            if input_data["task_id"] is not None:
                return ToolResult.failure(
                    code="task_id_requires_background",
                    message="task_id can only be used with run_in_background=true",
                )
            result = await self.manager.run(request)
        except ValueError as exc:
            return ToolResult.failure(code="invalid_subagent_request", message=str(exc))
        return ToolResult(
            success=result.status == "succeeded",
            summary=f"{result.subagent_id} finished with status {result.status.value}",
            data={
                "subagent_result": public_subagent_result(
                    result,
                    config.subagent_max_result_chars,
                )
            },
            error_code=result.error_kind.value if result.error_kind else None,
            error_message=result.error,
        )


class DelegatedTaskGetTool(RuntimeTool):
    """Get the latest state and bounded result for one background delegation."""

    name = "delegated_task_get"
    description = "Get the latest state and result for one background job_id."
    approval_level = ApprovalLevel.READ
    category = "delegation"
    input_model = DelegatedTaskGetInput
    input_schema = DelegatedTaskGetInput.model_json_schema()

    def __init__(self, supervisor: BackgroundJobSupervisor) -> None:
        self.supervisor = supervisor  # 查询当前主运行的后台 Job。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        job = await self.supervisor.get(input_data["job_id"], observe=True)
        return ToolResult(
            success=True,
            summary=f"{job.job_id} is {job.status.value}",
            data={
                "background_job": _job_data(
                    job,
                    context.config.subagent_max_result_chars,
                )
            },
        )


class DelegatedTaskListTool(RuntimeTool):
    """List background delegations created during the current run."""

    name = "delegated_task_list"
    description = "List background jobs, optionally filtered by lifecycle status."
    approval_level = ApprovalLevel.READ
    category = "delegation"
    input_model = DelegatedTaskListInput
    input_schema = DelegatedTaskListInput.model_json_schema()

    def __init__(self, supervisor: BackgroundJobSupervisor) -> None:
        self.supervisor = supervisor  # 枚举当前主运行的后台 Job。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        jobs = await self.supervisor.list(input_data["status"], observe=True)
        status_counts = Counter(job.status for job in jobs)
        status_summary = ", ".join(
            f"{status_counts[status]} {status.value}"
            for status in BackgroundJobStatus
            if status_counts[status]
        )
        summary = f"listed {len(jobs)} background job(s)"
        if status_summary:
            summary = f"{summary}: {status_summary}"
        return ToolResult(
            success=True,
            summary=summary,
            data={
                "background_jobs": [
                    _job_data(job, context.config.subagent_max_result_chars)
                    for job in jobs
                ]
            },
        )


class DelegatedTaskCancelTool(RuntimeTool):
    """Request cancellation of one queued or running background delegation."""

    name = "delegated_task_cancel"
    description = (
        "Cancel a queued background job immediately or request cooperative cancellation "
        "of a running job."
    )
    approval_level = ApprovalLevel.READ
    category = "delegation"
    input_model = DelegatedTaskCancelInput
    input_schema = DelegatedTaskCancelInput.model_json_schema()

    def __init__(self, supervisor: BackgroundJobSupervisor) -> None:
        self.supervisor = supervisor  # 取消当前主运行的指定后台 Job。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        job = await self.supervisor.cancel(input_data["job_id"])
        job = await self.supervisor.get(job.job_id, observe=True)
        return ToolResult(
            success=True,
            summary=f"{job.job_id} is {job.status.value}",
            data={
                "background_job": _job_data(
                    job,
                    context.config.subagent_max_result_chars,
                )
            },
        )


def _job_data(job: BackgroundJob, max_result_chars: int) -> dict:
    return public_job_data(job, max_result_chars)
