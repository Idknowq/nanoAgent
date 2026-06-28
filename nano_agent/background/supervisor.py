from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone

from nano_agent.background.cancellation import CancellationToken
from nano_agent.background.errors import BackgroundJobError
from nano_agent.background.models import (
    TERMINAL_JOB_STATUSES,
    BackgroundCompletionEvent,
    BackgroundJob,
    BackgroundJobStatus,
)
from nano_agent.background.store import BackgroundJobStore
from nano_agent.subagents.manager import SubagentManager
from nano_agent.subagents.models import (
    PreparedSubagent,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)
from nano_agent.tasks.models import TaskStatus
from nano_agent.tasks.service import TaskService


class BackgroundJobSupervisor:
    """Run isolated subagents as asyncio tasks with bounded concurrency."""

    def __init__(
        self,
        *,
        manager: SubagentManager,
        store: BackgroundJobStore,
        max_workers: int,
        max_jobs: int,
        max_result_chars: int = 12_000,
        task_service: TaskService | None = None,
    ) -> None:
        self.manager = manager  # 创建和执行隔离子 Agent 的统一入口。
        self.store = store  # 保存当前主运行的 Job 快照和生命周期事件。
        self.max_jobs = max_jobs  # 允许同时处于非终态的 Job 数量上限。
        self.max_result_chars = max_result_chars  # 回传父 Agent 的单个结果字符预算。
        self.task_service = task_service  # 可选的持久化 Task 状态联动服务。
        self._semaphore = asyncio.Semaphore(max_workers)  # 限制正在执行的子 Agent 数量。
        self._jobs: dict[str, BackgroundJob] = {}  # 当前进程创建的 Job 最新快照。
        self._tasks: dict[str, asyncio.Task[None]] = {}  # Job 对应的后台 asyncio Task。
        self._prepared: dict[str, PreparedSubagent] = {}  # Job 对应的已持久化子运行输入。
        self._tokens: dict[str, CancellationToken] = {}  # Job 对应的合作式取消信号。
        self._events: deque[BackgroundCompletionEvent] = deque()  # 尚未投递的终态通知。
        self._observed: set[str] = set()  # 已通过查询或通知交付给父 Agent 的终态 Job。
        self._lock = asyncio.Lock()  # 串行化内存状态转换和任务提交。
        self._completion = asyncio.Condition(self._lock)  # 等待任一 Job 进入终态。
        self._closed = False  # Supervisor 是否已经停止接收新 Job。

    async def submit(
        self,
        request: SubagentRequest,
        *,
        task_id: str | None = None,
    ) -> BackgroundJob:
        """Queue one background subagent job."""

        async with self._lock:
            if self._closed:
                raise BackgroundJobError(
                    "Background supervisor is closed",
                    code="supervisor_closed",
                )
            if len(self._active_jobs()) >= self.max_jobs:
                raise BackgroundJobError(
                    f"Background job limit reached: {self.max_jobs}",
                    code="background_job_limit",
                )
            if task_id is not None:
                await self._validate_task_submission(task_id)
            self.manager.validate_background_request(request)
            prepared = self.manager.prepare(request)
            job = BackgroundJob(
                job_id=await asyncio.to_thread(self.store.next_id),
                subagent_id=prepared.state.subagent_id,
                task_id=task_id,
            )
            token = CancellationToken()
            self._jobs[job.job_id] = job
            self._prepared[job.job_id] = prepared
            self._tokens[job.job_id] = token
            await self._save_job(job)
            self._tasks[job.job_id] = asyncio.create_task(
                self._run_job(job.job_id, prepared, token)
            )
            return job.model_copy(deep=True)

    async def get(self, job_id: str, *, observe: bool = False) -> BackgroundJob:
        """Get the latest job snapshot."""

        async with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                if observe and job.status in TERMINAL_JOB_STATUSES:
                    self._observed.add(job_id)
                return job.model_copy(deep=True)
        return await asyncio.to_thread(self.store.get, job_id)

    async def list(
        self,
        status: BackgroundJobStatus | None = None,
        *,
        observe: bool = False,
    ) -> list[BackgroundJob]:
        """List in-memory jobs created during the current process."""

        async with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda job: int(job.job_id.removeprefix("job-")),
            )
            if status is not None:
                jobs = [job for job in jobs if job.status == status]
            if observe:
                self._observed.update(
                    job.job_id for job in jobs if job.status in TERMINAL_JOB_STATUSES
                )
            return [job.model_copy(deep=True) for job in jobs]

    async def wait_for_completion(self, timeout: float) -> bool:
        """Wait until any unobserved job reaches a terminal state."""

        async with self._completion:
            if self._has_unobserved_event():
                return True
            try:
                await asyncio.wait_for(
                    self._completion.wait_for(self._has_unobserved_event),
                    timeout=timeout,
                )
            except TimeoutError:
                return False
            return True

    async def cancel(self, job_id: str) -> BackgroundJob:
        """Cancel a queued or running job."""

        prepared_cancel: PreparedSubagent | None = None
        async with self._lock:
            job = self._require_job(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return job.model_copy(deep=True)
            token = self._tokens[job_id]
            token.cancel()
            task = self._tasks[job_id]
            if job.status == BackgroundJobStatus.QUEUED:
                prepared_cancel = self._prepared[job_id]
                task.cancel()
            else:
                job.status = BackgroundJobStatus.CANCEL_REQUESTED
                await self._save_job(job)
        if prepared_cancel is not None:
            result = self.manager.cancel(prepared_cancel)
            await self._complete(job_id, result)
        return await self.get(job_id)

    async def drain_events(self) -> list[BackgroundCompletionEvent]:
        """Return terminal job events that have not yet been observed."""

        async with self._lock:
            events = [
                event for event in self._events if event.job_id not in self._observed
            ]
            self._events.clear()
            self._observed.update(event.job_id for event in events)
            return events

    async def has_active_jobs(self) -> bool:
        """Return whether any queued, running, or cancelling jobs remain."""

        async with self._lock:
            return bool(self._active_jobs())

    async def shutdown(self, *, cancel_active: bool = True) -> None:
        """Stop accepting jobs and wait for running job tasks to finish."""

        async with self._lock:
            self._closed = True
            job_ids = [job.job_id for job in self._active_jobs()]
        if cancel_active:
            for job_id in job_ids:
                await self.cancel(job_id)
        async with self._lock:
            tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_job(
        self,
        job_id: str,
        prepared: PreparedSubagent,
        token: CancellationToken,
    ) -> None:
        async with self._semaphore:
            async with self._lock:
                job = self._require_job(job_id)
                if job.status in TERMINAL_JOB_STATUSES:
                    return
                if token.cancelled:
                    result = self.manager.cancel(prepared)
                    await self._complete_locked(job_id, result)
                    return
                job.status = BackgroundJobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                await self._save_job(job)
            await self._start_task(job)
            try:
                result = await self.manager.execute(prepared, token)
            except asyncio.CancelledError:
                result = self.manager.cancel(prepared)
            await self._complete(job_id, result)

    async def _complete(self, job_id: str, result: SubagentResult) -> None:
        async with self._lock:
            await self._complete_locked(job_id, result)

    async def _complete_locked(self, job_id: str, result: SubagentResult) -> None:
        job = self._require_job(job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            return
        job.result = result
        job.error = result.error
        try:
            await self._finish_task(job)
        except Exception as exc:  # noqa: BLE001 - Job completion must remain observable.
            task_error = f"Linked Task update failed: {type(exc).__name__}: {exc}"
            job.error = f"{job.error}; {task_error}" if job.error else task_error
        job.status = self._job_status(result.status)
        job.finished_at = datetime.now(timezone.utc)
        self._prepared.pop(job_id, None)
        self._tokens.pop(job_id, None)
        await self._save_job(job)
        self._events.append(
            BackgroundCompletionEvent(
                job_id=job.job_id,
                subagent_id=job.subagent_id,
                task_id=job.task_id,
                status=job.status,
            )
        )
        self._completion.notify_all()

    async def _validate_task_submission(self, task_id: str) -> None:
        if self.task_service is None:
            raise BackgroundJobError(
                "Task integration is unavailable",
                code="task_integration_unavailable",
            )
        task = await self.task_service.get(task_id)
        if task.status != TaskStatus.PENDING:
            raise BackgroundJobError(
                f"Task is not ready for execution: {task_id} ({task.status.value})",
                code="task_not_ready",
            )
        if any(job.task_id == task_id for job in self._active_jobs()):
            raise BackgroundJobError(
                f"Task already has an active background job: {task_id}",
                code="task_already_running",
            )

    async def _start_task(self, job: BackgroundJob) -> None:
        if job.task_id is not None and self.task_service is not None:
            await self.task_service.update(
                job.task_id,
                status=TaskStatus.IN_PROGRESS,
                owner=job.job_id,
                error="",
            )

    async def _finish_task(self, job: BackgroundJob) -> None:
        if job.task_id is None or self.task_service is None or job.result is None:
            return
        result = job.result
        if result.status == SubagentStatus.SUCCEEDED:
            await self.task_service.update(
                job.task_id,
                status=TaskStatus.COMPLETED,
                result=result.output or "Subagent completed successfully.",
                error="",
            )
        elif result.status == SubagentStatus.BLOCKED:
            await self.task_service.update(
                job.task_id,
                status=TaskStatus.BLOCKED,
                error=result.error or "Subagent was blocked.",
            )
        elif result.status == SubagentStatus.CANCELLED:
            task = await self.task_service.get(job.task_id)
            if task.status == TaskStatus.IN_PROGRESS:
                await self.task_service.update(
                    job.task_id,
                    status=TaskStatus.PENDING,
                    error=result.error or "Background execution was cancelled.",
                )
        else:
            await self.task_service.update(
                job.task_id,
                status=TaskStatus.FAILED,
                error=result.error or "Subagent execution failed.",
            )

    async def _save_job(self, job: BackgroundJob) -> None:
        await asyncio.to_thread(self.store.save, job)

    def _active_jobs(self) -> list[BackgroundJob]:
        return [job for job in self._jobs.values() if job.status not in TERMINAL_JOB_STATUSES]

    def _has_unobserved_event(self) -> bool:
        return any(event.job_id not in self._observed for event in self._events)

    def _require_job(self, job_id: str) -> BackgroundJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise BackgroundJobError(
                f"Background job not found: {job_id}",
                code="job_not_found",
            )
        return job

    @staticmethod
    def _job_status(status: SubagentStatus) -> BackgroundJobStatus:
        return {
            SubagentStatus.SUCCEEDED: BackgroundJobStatus.SUCCEEDED,
            SubagentStatus.BLOCKED: BackgroundJobStatus.BLOCKED,
            SubagentStatus.FAILED: BackgroundJobStatus.FAILED,
            SubagentStatus.CANCELLED: BackgroundJobStatus.CANCELLED,
        }[status]
