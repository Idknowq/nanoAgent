from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from nano_agent.background.errors import BackgroundJobError
from nano_agent.background.models import BackgroundJob, BackgroundJobEvent
from nano_agent.persistence.json_io import atomic_write_json


class BackgroundJobStore:
    """Async-locked run-local persistence for background job snapshots and events."""

    events_filename = "events.jsonl"  # Job 生命周期追加日志文件名。

    def __init__(self, run_dir: Path) -> None:
        self.jobs_dir = run_dir / "background" / "jobs"  # 当前主运行的 Job 持久化目录。
        self._lock = asyncio.Lock()  # 串行化 Job 标识分配和文件写入。

    async def next_id(self) -> str:
        """Allocate the next job id under the async store lock."""

        async with self._lock:
            highest = 0  # 已持久化 Job 文件中的最大数字序号。
            if self.jobs_dir.is_dir():
                for path in self.jobs_dir.glob("job-*.json"):
                    match = re.fullmatch(r"job-(\d+)\.json", path.name)
                    if path.is_file() and match is not None:
                        highest = max(highest, int(match.group(1)))
            return f"job-{highest + 1}"

    async def save(self, job: BackgroundJob) -> Path:
        """Persist one job snapshot and event under the async store lock."""

        async with self._lock:
            target = self.jobs_dir / f"{job.job_id}.json"
            atomic_write_json(target, job.model_dump(mode="json"))
            event = BackgroundJobEvent(job_id=job.job_id, status=job.status)
            events_path = self.jobs_dir / self.events_filename
            with events_path.open("a", encoding="utf-8") as file:
                file.write(event.model_dump_json() + "\n")
                file.flush()
                os.fsync(file.fileno())
            return target

    async def get(self, job_id: str) -> BackgroundJob:
        """Load one persisted job snapshot under the async store lock."""

        async with self._lock:
            path = self.jobs_dir / f"{job_id}.json"
            if not re.fullmatch(r"job-\d+", job_id) or not path.is_file():
                raise BackgroundJobError(
                    f"Background job not found: {job_id}",
                    code="job_not_found",
                )
            return BackgroundJob.model_validate_json(path.read_text(encoding="utf-8"))
