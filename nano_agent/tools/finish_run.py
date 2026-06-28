from __future__ import annotations

from collections.abc import Callable

from pydantic import Field

from nano_agent.models import ApprovalLevel, CompletionReport, TerminalRunStatus
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)


class FinishRunInput(ToolInput):
    status: TerminalRunStatus  # Agent 声明的最终运行状态。
    problem: str = Field(min_length=1)  # 问题或任务目标概述。
    root_cause: str = Field(min_length=1)  # 根因或当前判断。
    resolution: str = Field(min_length=1)  # 已实施修复或处理方式。
    changed_files: list[str] = Field(default_factory=list)  # 修改的仓库相对路径。
    verification_summary: str = ""  # 验证范围和结果摘要。
    remaining_risks: list[str] = Field(default_factory=list)  # 尚存风险。
    blockers: list[str] = Field(default_factory=list)  # 阻塞原因。


class FinishRunTool(RuntimeTool):
    """Submit a structured final result for runtime validation and report generation."""

    name = "finish_run"
    description = (
        "Finish the run with a structured completed, blocked, or failed report. "
        "Summarize verification performed without including internal tool call ids."
    )
    approval_level = ApprovalLevel.READ
    category = "lifecycle"
    input_model = FinishRunInput
    input_schema = FinishRunInput.model_json_schema()

    def __init__(self, active_jobs_provider: Callable[[], bool] | None = None) -> None:
        self.active_jobs_provider = active_jobs_provider  # 查询当前主运行是否仍有后台 Job。

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        del context
        if self.active_jobs_provider is not None and self.active_jobs_provider():
            return ToolResult.failure(
                code="background_jobs_active",
                message=(
                    "Cannot finish while background jobs are queued, running, "
                    "or awaiting cancellation."
                ),
            )
        report = CompletionReport.model_validate(input_data)
        return ToolResult(
            success=True,
            summary=f"submitted {report.status.value} completion report",
            data={"completion_report": report.model_dump(mode="json")},
        )


def _build_finish_run_tool(context: ToolContext) -> FinishRunTool:
    del context
    return FinishRunTool()


register_tool_factory(FinishRunTool.name, _build_finish_run_tool)
