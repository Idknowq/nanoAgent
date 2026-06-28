from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Condition, RLock

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
    """Run isolated subagents with bounded concurrency and durable job state."""

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
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="nano-subagent",
        )  # 执行后台子 Agent 的有限线程池。
        self._jobs: dict[str, BackgroundJob] = {}  # 当前进程创建的 Job 最新快照。
        self._futures: dict[str, Future[None]] = {}  # Job 对应的线程池 Future。
        self._prepared: dict[str, PreparedSubagent] = {}  # Job 对应的已持久化子运行输入。
        self._tokens: dict[str, CancellationToken] = {}  # Job 对应的合作式取消信号。
        self._events: deque[BackgroundCompletionEvent] = deque()  # 尚未投递的终态通知。
        self._observed: set[str] = set()  # 已通过查询或通知交付给父 Agent 的终态 Job。
        self._lock = RLock()  # 串行化内存状态转换和任务提交。
        self._completion = Condition(self._lock)  # 等待任一 Job 进入终态的条件变量。
        self._closed = False  # Supervisor 是否已经停止接收新 Job。

    def submit(
        self,
        request: SubagentRequest,
        *,
        task_id: str | None = None,
    ) -> BackgroundJob:
        with self._lock:
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
                self._validate_task_submission(task_id)
            self.manager.validate_background_request(request)
            prepared = self.manager.prepare(request)
            job = BackgroundJob(
                job_id=self.store.next_id(),
                subagent_id=prepared.state.subagent_id,
                task_id=task_id,
            )
            token = CancellationToken()
            self._jobs[job.job_id] = job
            self._prepared[job.job_id] = prepared
            self._tokens[job.job_id] = token
            self.store.save(job)
            self._futures[job.job_id] = self._executor.submit(
                self._run_job,
                job.job_id,
                prepared,
                token,
            )
            return job.model_copy(deep=True)

    def get(self, job_id: str, *, observe: bool = False) -> BackgroundJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                if observe and job.status in TERMINAL_JOB_STATUSES:
                    self._observed.add(job_id)
                return job.model_copy(deep=True)
        return self.store.get(job_id)

    def list(
        self,
        status: BackgroundJobStatus | None = None,
        *,
        observe: bool = False,
    ) -> list[BackgroundJob]:
        with self._lock:
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

    def wait_for_completion(self, timeout: float) -> bool:
        with self._completion:
            if self._has_unobserved_event():
                return True
            return self._completion.wait_for(
                self._has_unobserved_event,
                timeout=timeout,
            )

    async def wait_for_completion_async(self, timeout: float) -> bool:
        """Wait for a terminal Job event without blocking the caller's event loop."""
        return await asyncio.to_thread(self.wait_for_completion, timeout)

    def cancel(self, job_id: str) -> BackgroundJob:
        prepared_cancel: PreparedSubagent | None = None
        with self._lock:
            job = self._require_job(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return job.model_copy(deep=True)
            token = self._tokens[job_id]
            token.cancel()
            future = self._futures[job_id]
            if job.status == BackgroundJobStatus.QUEUED and future.cancel():
                prepared_cancel = self._prepared[job_id]
            else:
                job.status = BackgroundJobStatus.CANCEL_REQUESTED
                self.store.save(job)
        if prepared_cancel is not None:
            result = self.manager.cancel(prepared_cancel)
            self._complete(job_id, result)
        return self.get(job_id)

    def drain_events(self) -> list[BackgroundCompletionEvent]:
        with self._lock:
            events = [
                event for event in self._events if event.job_id not in self._observed
            ]
            self._events.clear()
            self._observed.update(event.job_id for event in events)
            return events

    def has_active_jobs(self) -> bool:
        with self._lock:
            return bool(self._active_jobs())

    def shutdown(self, *, cancel_active: bool = True) -> None:
        with self._lock:
            self._closed = True
            job_ids = [job.job_id for job in self._active_jobs()]
        if cancel_active:
            for job_id in job_ids:
                self.cancel(job_id)
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run_job(
        self,
        job_id: str,
        prepared: PreparedSubagent,
        token: CancellationToken,
    ) -> None:
        with self._lock:
            job = self._require_job(job_id)
            if token.cancelled:
                result = self.manager.cancel(prepared)
                self._complete(job_id, result)
                return
            job.status = BackgroundJobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            self.store.save(job)
        self._start_task(job)
        result = asyncio.run(self.manager.execute(prepared, token))
        self._complete(job_id, result)

    def _complete(self, job_id: str, result: SubagentResult) -> None:
        with self._lock:
            job = self._require_job(job_id)
            if job.status in TERMINAL_JOB_STATUSES:
                return
            job.result = result
            job.error = result.error
            try:
                self._finish_task(job)
            except Exception as exc:  # noqa: BLE001 - Job completion must remain observable.
                task_error = f"Linked Task update failed: {type(exc).__name__}: {exc}"
                job.error = f"{job.error}; {task_error}" if job.error else task_error
            job.status = self._job_status(result.status)
            job.finished_at = datetime.now(timezone.utc)
            self._prepared.pop(job_id, None)
            self._tokens.pop(job_id, None)
            self.store.save(job)
            self._events.append(
                BackgroundCompletionEvent(
                    job_id=job.job_id,
                    subagent_id=job.subagent_id,
                    task_id=job.task_id,
                    status=job.status,
                )
            )
            self._completion.notify_all()

    def _validate_task_submission(self, task_id: str) -> None:
        if self.task_service is None:
            raise BackgroundJobError(
                "Task integration is unavailable",
                code="task_integration_unavailable",
            )
        task = self.task_service.get(task_id)
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

    def _start_task(self, job: BackgroundJob) -> None:
        if job.task_id is not None and self.task_service is not None:
            self.task_service.update(
                job.task_id,
                status=TaskStatus.IN_PROGRESS,
                owner=job.job_id,
                error="",
            )

    def _finish_task(self, job: BackgroundJob) -> None:
        if job.task_id is None or self.task_service is None or job.result is None:
            return
        result = job.result
        if result.status == SubagentStatus.SUCCEEDED:
            self.task_service.update(
                job.task_id,
                status=TaskStatus.COMPLETED,
                result=result.output or "Subagent completed successfully.",
                error="",
            )
        elif result.status == SubagentStatus.BLOCKED:
            self.task_service.update(
                job.task_id,
                status=TaskStatus.BLOCKED,
                error=result.error or "Subagent was blocked.",
            )
        elif result.status == SubagentStatus.CANCELLED:
            task = self.task_service.get(job.task_id)
            if task.status == TaskStatus.IN_PROGRESS:
                self.task_service.update(
                    job.task_id,
                    status=TaskStatus.PENDING,
                    error=result.error or "Background execution was cancelled.",
                )
        else:
            self.task_service.update(
                job.task_id,
                status=TaskStatus.FAILED,
                error=result.error or "Subagent execution failed.",
            )

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
