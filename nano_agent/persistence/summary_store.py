from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from nano_agent.models import RunStatus, RunSummary
from nano_agent.persistence.json_io import atomic_write_json


class PersistedRunSummary(BaseModel):
    """Small user-facing run summary; detailed events live in JSONL files."""

    schema_version: int = 1
    run_id: str
    repo_url: str
    workspace_path: Path | None
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    steps: int
    llm_call_count: int
    tool_call_count: int
    successful_tool_calls: int
    failed_tool_calls: int
    final_message: str | None
    notes: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)

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
