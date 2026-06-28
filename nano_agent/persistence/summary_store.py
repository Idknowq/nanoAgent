from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from nano_agent.models import RunStatus, RunSummary
from nano_agent.persistence.json_io import atomic_write_json


class PersistedRunSummary(BaseModel):
    """Small user-facing run summary; detailed events live in JSONL files."""

    schema_version: int = 1  # 运行摘要的数据结构版本。
    run_id: str  # 本次 Agent 运行的唯一标识。
    repo_url: str  # 本次运行处理的仓库地址。
    workspace_path: Path | None  # 本次运行使用的隔离工作区路径。
    status: RunStatus  # 本次运行的最终或当前状态。
    started_at: datetime  # 本次运行的开始时间。
    finished_at: datetime | None  # 本次运行的结束时间；运行中为空。
    duration_seconds: float | None  # 本次运行的总耗时；运行中为空。
    steps: int  # Agent loop 实际执行的步骤数。
    llm_call_count: int  # 本次运行发起的 LLM 调用次数。
    tool_call_count: int  # 本次运行发起的工具调用总数。
    successful_tool_calls: int  # 成功完成的工具调用数量。
    failed_tool_calls: int  # 返回失败结果的工具调用数量。
    final_message: str | None  # 最后一条非空 assistant 回复。
    notes: list[str] = Field(default_factory=list)  # 运行过程中的补充说明。
    artifacts: dict[str, str] = Field(default_factory=dict)  # 运行产物名称和相对路径。

    @classmethod
    def from_run(cls, run: RunSummary) -> PersistedRunSummary:
        duration = None
        if run.finished_at is not None:
            duration = max(0.0, (run.finished_at - run.started_at).total_seconds())
        final_message = next(
            (
                message.content
                for message in reversed(run.messages)
                if message.role == "assistant" and message.content
            ),
            None,
        )
        successful_calls = sum(call.success for call in run.tool_calls)
        return cls(
            run_id=run.run_id,
            repo_url=run.repo_url,
            workspace_path=run.workspace_path,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=duration,
            steps=run.steps,
            llm_call_count=run.llm_call_count,
            tool_call_count=len(run.tool_calls),
            successful_tool_calls=successful_calls,
            failed_tool_calls=len(run.tool_calls) - successful_calls,
            final_message=final_message,
            notes=run.notes,
            artifacts={key: str(value) for key, value in run.artifacts.items()},
        )


class SummaryStore:
    filename = "summary.json"

    def save(self, run_dir: Path, run: RunSummary) -> Path:
        target = run_dir / self.filename
        summary = PersistedRunSummary.from_run(run)
        atomic_write_json(target, summary.model_dump(mode="json"))
        return target

    async def save_async(self, run_dir: Path, run: RunSummary) -> Path:
        """Persist the run summary without blocking the event loop."""

        return await asyncio.to_thread(self.save, run_dir, run)
