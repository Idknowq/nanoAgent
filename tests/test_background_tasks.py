from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from nano_agent.background.cancellation import CancellationToken
from nano_agent.background.hook import BackgroundCompletionHook
from nano_agent.background.models import BackgroundJob, BackgroundJobStatus
from nano_agent.background.presentation import public_subagent_result
from nano_agent.background.store import BackgroundJobStore
from nano_agent.background.supervisor import BackgroundJobSupervisor
from nano_agent.config import AgentConfig
from nano_agent.models import CompletionReport, RunStatus, RunSummary
from nano_agent.subagents.models import (
    PreparedSubagent,
    SubagentErrorKind,
    SubagentRequest,
    SubagentResult,
    SubagentState,
    SubagentStatus,
)
from nano_agent.tasks.models import TaskStatus
from nano_agent.tasks.service import TaskService
from nano_agent.tasks.store import TaskStore
from nano_agent.tools.base import ToolContext
from nano_agent.tools.delegate_task import (
    DelegatedTaskGetTool,
    DelegatedTaskListTool,
    DelegateTaskTool,
)
from nano_agent.tools.finish_run import FinishRunTool


class ControlledSubagentManager:
    """Deterministic concurrent manager used to test Supervisor behavior."""

    def __init__(self) -> None:
        self.release = asyncio.Event()  # 允许测试控制所有运行中子 Agent 的完成时机。
        self.started: asyncio.Queue[str] = asyncio.Queue()  # 记录实际开始执行的子 Agent。
        self._next_id = 0  # 下一个测试子 Agent 数字序号。
        self._active = 0  # 当前正在执行的测试子 Agent 数量。
        self.max_active = 0  # 测试期间观察到的最大并发数。

    def validate_background_request(self, request: SubagentRequest) -> None:
        del request

    def prepare(self, request: SubagentRequest) -> PreparedSubagent:
        self._next_id += 1
        subagent_id = f"subagent-{self._next_id}"
        state = SubagentState(
            subagent_id=subagent_id,
            parent_run_id="parent",
            status=SubagentStatus.CREATED,
            task=request.task,
            allowed_tools=request.allowed_tools,
        )
        return PreparedSubagent(
            request=request,
            run=RunSummary(
                run_id=f"parent-{subagent_id}",
                repo_url="https://example.com/repo.git",
            ),
            run_dir=f"/tmp/{subagent_id}",
            allowed_tools=request.allowed_tools,
            state=state,
        )

    async def execute(
        self,
        prepared: PreparedSubagent,
        cancellation_token: CancellationToken | None = None,
    ) -> SubagentResult:
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        await self.started.put(prepared.state.subagent_id)
        try:
            while True:
                try:
                    await asyncio.wait_for(self.release.wait(), timeout=0.01)
                    break
                except TimeoutError:
                    pass
                if cancellation_token is not None and cancellation_token.cancelled:
                    return self._cancelled_result(prepared)
            if cancellation_token is not None and cancellation_token.cancelled:
                return self._cancelled_result(prepared)
            return SubagentResult(
                subagent_id=prepared.state.subagent_id,
                parent_run_id="parent",
                status=SubagentStatus.SUCCEEDED,
                output=f"completed {prepared.request.task}",
                completion_report=CompletionReport(
                    status=RunStatus.COMPLETED,
                    problem=prepared.request.task,
                    root_cause="Analysis task",
                    resolution=f"completed {prepared.request.task}",
                    verification_summary="Reviewed relevant files.",
                    remaining_risks=["One material risk."],
                ),
                run_dir=prepared.run_dir,
            )
        finally:
            self._active -= 1

    def cancel(self, prepared: PreparedSubagent) -> SubagentResult:
        return self._cancelled_result(prepared)

    @staticmethod
    def _cancelled_result(prepared: PreparedSubagent) -> SubagentResult:
        return SubagentResult(
            subagent_id=prepared.state.subagent_id,
            parent_run_id="parent",
            status=SubagentStatus.CANCELLED,
            error_kind=SubagentErrorKind.CANCELLED,
            error="cancelled",
            run_dir=prepared.run_dir,
        )


def make_request(name: str) -> SubagentRequest:
    return SubagentRequest(
        task=name,
        allowed_tools=("read_file",),
        max_steps=3,
        max_llm_calls=3,
    )


def make_supervisor(
    tmp_path: Path,
    manager: ControlledSubagentManager,
    *,
    max_workers: int = 2,
    max_jobs: int = 8,
    task_service: TaskService | None = None,
) -> BackgroundJobSupervisor:
    return BackgroundJobSupervisor(
        manager=manager,  # type: ignore[arg-type]
        store=BackgroundJobStore(tmp_path / "run"),
        max_workers=max_workers,
        max_jobs=max_jobs,
        task_service=task_service,
    )


async def wait_terminal(
    supervisor: BackgroundJobSupervisor,
    job_id: str,
    timeout: float = 1,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = await supervisor.get(job_id)
        if job.status in {
            BackgroundJobStatus.SUCCEEDED,
            BackgroundJobStatus.BLOCKED,
            BackgroundJobStatus.FAILED,
            BackgroundJobStatus.CANCELLED,
        }:
            return job
        await asyncio.sleep(0.005)
    raise AssertionError(f"job did not finish: {job_id}")


async def test_supervisor_runs_jobs_concurrently_with_worker_limit(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    supervisor = make_supervisor(tmp_path, manager, max_workers=2)
    first = await supervisor.submit(make_request("first"))
    second = await supervisor.submit(make_request("second"))

    assert {
        await asyncio.wait_for(manager.started.get(), timeout=1),
        await asyncio.wait_for(manager.started.get(), timeout=1),
    } == {
        first.subagent_id,
        second.subagent_id,
    }
    assert manager.max_active == 2

    manager.release.set()
    assert (await wait_terminal(supervisor, first.job_id)).status == BackgroundJobStatus.SUCCEEDED
    assert (await wait_terminal(supervisor, second.job_id)).status == BackgroundJobStatus.SUCCEEDED
    await supervisor.shutdown()


async def test_supervisor_keeps_excess_job_queued(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    supervisor = make_supervisor(tmp_path, manager, max_workers=1)
    first = await supervisor.submit(make_request("first"))
    second = await supervisor.submit(make_request("second"))

    assert await asyncio.wait_for(manager.started.get(), timeout=1) == first.subagent_id
    try:
        await asyncio.wait_for(manager.started.get(), timeout=0.05)
        second_started = True
    except TimeoutError:
        second_started = False
    assert not second_started
    assert (await supervisor.get(second.job_id)).status == BackgroundJobStatus.QUEUED

    manager.release.set()
    await wait_terminal(supervisor, first.job_id)
    await wait_terminal(supervisor, second.job_id)
    await supervisor.shutdown()


async def test_concurrent_submissions_receive_unique_job_ids(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    manager.release.set()
    supervisor = make_supervisor(tmp_path, manager, max_workers=4, max_jobs=20)

    jobs = await asyncio.gather(
        *[supervisor.submit(make_request(str(index))) for index in range(12)]
    )

    assert len({job.job_id for job in jobs}) == 12
    assert len({job.subagent_id for job in jobs}) == 12
    for job in jobs:
        await wait_terminal(supervisor, job.job_id)
    await supervisor.shutdown()


async def test_queued_and_running_jobs_can_be_cancelled(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    supervisor = make_supervisor(tmp_path, manager, max_workers=1)
    running = await supervisor.submit(make_request("running"))
    await asyncio.wait_for(manager.started.get(), timeout=1)
    queued = await supervisor.submit(make_request("queued"))

    assert (await supervisor.cancel(queued.job_id)).status == BackgroundJobStatus.CANCELLED
    running_status = (await supervisor.cancel(running.job_id)).status
    assert running_status in {
        BackgroundJobStatus.CANCEL_REQUESTED,
        BackgroundJobStatus.CANCELLED,
    }
    assert (await wait_terminal(supervisor, running.job_id)).status == BackgroundJobStatus.CANCELLED
    await supervisor.shutdown()


async def test_job_completion_updates_linked_task(tmp_path: Path) -> None:
    task_service = TaskService(TaskStore(tmp_path / "run"))
    task = await task_service.create(subject="Inspect", description="Inspect files")
    manager = ControlledSubagentManager()
    manager.release.set()
    supervisor = make_supervisor(tmp_path, manager, task_service=task_service)

    job = await supervisor.submit(make_request("inspect"), task_id=task.task_id)
    assert (await wait_terminal(supervisor, job.job_id)).status == BackgroundJobStatus.SUCCEEDED

    completed = await task_service.get(task.task_id)
    assert completed.status == TaskStatus.COMPLETED
    assert completed.owner == job.job_id
    assert completed.result == "completed inspect"
    await supervisor.shutdown()


async def test_cancelled_execution_returns_linked_task_to_pending(tmp_path: Path) -> None:
    task_service = TaskService(TaskStore(tmp_path / "run"))
    task = await task_service.create(subject="Inspect", description="Inspect files")
    manager = ControlledSubagentManager()
    supervisor = make_supervisor(tmp_path, manager, task_service=task_service)

    job = await supervisor.submit(make_request("inspect"), task_id=task.task_id)
    await asyncio.wait_for(manager.started.get(), timeout=1)
    await supervisor.cancel(job.job_id)
    assert (await wait_terminal(supervisor, job.job_id)).status == BackgroundJobStatus.CANCELLED
    assert (await task_service.get(task.task_id)).status == TaskStatus.PENDING
    await supervisor.shutdown()


async def test_completion_hook_delivers_terminal_event_once(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    manager.release.set()
    supervisor = make_supervisor(tmp_path, manager)
    job = await supervisor.submit(make_request("inspect"))
    await wait_terminal(supervisor, job.job_id)
    hook = BackgroundCompletionHook(supervisor)

    first = await hook.before_llm_call(None, [], [])  # type: ignore[arg-type]
    second = await hook.before_llm_call(None, [], [])  # type: ignore[arg-type]

    assert first is not None
    assert job.job_id in first.injected_messages[0].content
    assert "Reviewed relevant files." in first.injected_messages[0].content
    assert "One material risk." in first.injected_messages[0].content
    assert "run_dir" not in first.injected_messages[0].content
    assert second is None
    await supervisor.shutdown()


async def test_supervisor_idle_wait_unblocks_when_any_job_completes(tmp_path: Path) -> None:
    manager = ControlledSubagentManager()
    supervisor = make_supervisor(tmp_path, manager)
    await supervisor.submit(make_request("inspect"))
    await asyncio.wait_for(manager.started.get(), timeout=1)

    waiting = asyncio.create_task(supervisor.wait_for_completion(1))
    await asyncio.sleep(0)
    manager.release.set()

    assert await asyncio.wait_for(waiting, timeout=1)
    await supervisor.shutdown()


async def test_querying_terminal_job_suppresses_duplicate_completion_notice(
    tmp_path: Path,
) -> None:
    manager = ControlledSubagentManager()
    manager.release.set()
    supervisor = make_supervisor(tmp_path, manager)
    job = await supervisor.submit(make_request("inspect"))
    await wait_terminal(supervisor, job.job_id)
    await supervisor.get(job.job_id, observe=True)

    result = await BackgroundCompletionHook(supervisor).before_llm_call(None, [], [])  # type: ignore[arg-type]

    assert result is None
    await supervisor.shutdown()


async def test_finish_run_rejects_active_background_jobs(tmp_path: Path) -> None:
    context = ToolContext(
        run_id="run",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "run",
        config=AgentConfig(),
    )
    tool = FinishRunTool(lambda: True)

    result = await tool.invoke(
        {
            "status": RunStatus.COMPLETED,
            "problem": "Task",
            "root_cause": "Cause",
            "resolution": "Resolution",
        },
        context,
    )

    assert not result.success
    assert result.error_code == "background_jobs_active"


async def test_delegation_tools_submit_query_and_list_background_job(
    tmp_path: Path,
) -> None:
    manager = ControlledSubagentManager()
    manager.release.set()
    supervisor = make_supervisor(tmp_path, manager)
    context = ToolContext(
        run_id="run",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "run",
        config=AgentConfig(),
    )

    submitted = await DelegateTaskTool(manager, supervisor).invoke(  # type: ignore[arg-type]
        {
            "task": "inspect",
            "allowed_tools": ["read_file"],
            "max_steps": 3,
            "max_llm_calls": 3,
            "run_in_background": True,
        },
        context,
    )
    job_id = submitted.data["background_job"]["job_id"]
    await wait_terminal(supervisor, job_id)
    loaded = await DelegatedTaskGetTool(supervisor).invoke({"job_id": job_id}, context)
    listed = await DelegatedTaskListTool(supervisor).invoke(
        {"status": "succeeded"},
        context,
    )

    assert submitted.success
    assert loaded.data["background_job"]["job_id"] == job_id
    assert loaded.data["background_job"]["result"]["completion_report"][
        "verification_summary"
    ] == "Reviewed relevant files."
    assert loaded.data["background_job"]["result"]["completion_report"][
        "remaining_risks"
    ] == ["One material risk."]
    assert "run_dir" not in loaded.data["background_job"]["result"]
    assert [job["job_id"] for job in listed.data["background_jobs"]] == [job_id]
    assert listed.summary == "listed 1 background job(s): 1 succeeded"
    await supervisor.shutdown()


async def test_delegated_task_list_summary_counts_jobs_by_status(tmp_path: Path) -> None:
    class StubSupervisor:
        async def list(
            self,
            status: BackgroundJobStatus | None,
            *,
            observe: bool,
        ) -> list[BackgroundJob]:
            assert status is None
            assert observe
            return [
                BackgroundJob(
                    job_id="job-1",
                    subagent_id="subagent-1",
                    status=BackgroundJobStatus.RUNNING,
                ),
                BackgroundJob(
                    job_id="job-2",
                    subagent_id="subagent-2",
                    status=BackgroundJobStatus.SUCCEEDED,
                ),
            ]

    context = ToolContext(
        run_id="run",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "run",
        config=AgentConfig(),
    )

    result = await DelegatedTaskListTool(StubSupervisor()).invoke({}, context)  # type: ignore[arg-type]

    assert result.summary == "listed 2 background job(s): 1 running, 1 succeeded"


async def test_public_subagent_result_enforces_configured_character_budget() -> None:
    long_text = "x" * 10_000
    result = SubagentResult(
        subagent_id="subagent-1",
        parent_run_id="parent",
        status=SubagentStatus.SUCCEEDED,
        output=long_text,
        run_dir="/tmp/subagent-1",
        completion_report=CompletionReport(
            status=RunStatus.COMPLETED,
            problem=long_text,
            root_cause=long_text,
            resolution=long_text,
            verification_summary=long_text,
            remaining_risks=[long_text] * 20,
            blockers=[long_text] * 20,
        ),
    )

    payload = public_subagent_result(result, 1_000)

    assert len(json.dumps(payload, ensure_ascii=False)) <= 1_000
    assert payload["completion_report"]["remaining_risks"]
