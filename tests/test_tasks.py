import asyncio
import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.tasks.errors import TaskError
from nano_agent.tasks.models import TaskBlockedReason, TaskStatus
from nano_agent.tasks.service import TaskService
from nano_agent.tasks.store import TaskStore
from nano_agent.tools.base import ToolContext, build_default_tool_registry
from nano_agent.tools.tasks import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool


def make_service(tmp_path: Path) -> TaskService:
    return TaskService(TaskStore(tmp_path / "run"))


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "run",
        config=AgentConfig(
            console_progress_enabled=False,
            llm_calls_enabled=False,
            audit_enabled=False,
        ),
    )


async def test_task_ids_survive_service_recreation(tmp_path: Path) -> None:
    first_service = make_service(tmp_path)
    first = await first_service.create(subject="First", description="First task")
    second_service = make_service(tmp_path)

    second = await second_service.create(subject="Second", description="Second task")

    assert first.task_id == "task-1"
    assert second.task_id == "task-2"


async def test_concurrent_task_creates_get_unique_ids(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    tasks = await asyncio.gather(
        *[
            service.create(subject=f"Task {index}", description="Run work")
            for index in range(10)
        ]
    )

    task_ids = sorted(
        (task.task_id for task in tasks),
        key=lambda value: int(value.split("-")[1]),
    )
    assert task_ids == [f"task-{index}" for index in range(1, 11)]


async def test_task_with_incomplete_dependency_is_blocked_then_unlocked(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    upstream = await service.create(subject="Upstream", description="Prepare input")
    downstream = await service.create(
        subject="Downstream",
        description="Consume input",
        blocked_by=(upstream.task_id,),
    )

    assert downstream.status == TaskStatus.BLOCKED
    assert downstream.blocked_reason == TaskBlockedReason.DEPENDENCY

    await service.update(upstream.task_id, status=TaskStatus.IN_PROGRESS)
    await service.update(upstream.task_id, status=TaskStatus.COMPLETED, result="ready")

    unlocked = await service.get(downstream.task_id)
    assert unlocked.status == TaskStatus.PENDING
    assert unlocked.blocked_reason is None


async def test_external_block_is_not_unlocked_by_dependency_completion(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    upstream = await service.create(subject="Upstream", description="Prepare input")
    downstream = await service.create(
        subject="Downstream",
        description="Consume input",
        blocked_by=(upstream.task_id,),
    )
    await service.update(downstream.task_id, status=TaskStatus.BLOCKED, error="Need credentials")

    await service.update(upstream.task_id, status=TaskStatus.IN_PROGRESS)
    await service.update(upstream.task_id, status=TaskStatus.COMPLETED)

    still_blocked = await service.get(downstream.task_id)
    assert still_blocked.status == TaskStatus.BLOCKED
    assert still_blocked.blocked_reason == TaskBlockedReason.EXTERNAL


async def test_missing_self_and_cyclic_dependencies_are_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = await service.create(subject="First", description="First task")
    second = await service.create(
        subject="Second",
        description="Second task",
        blocked_by=(first.task_id,),
    )

    with pytest.raises(TaskError) as missing:
        await service.create(
            subject="Missing",
            description="Missing dependency",
            blocked_by=("task-99",),
        )
    assert missing.value.code == "invalid_dependency"

    with pytest.raises(TaskError) as self_dependency:
        await service.update(first.task_id, blocked_by=(first.task_id,))
    assert self_dependency.value.code == "invalid_dependency"

    with pytest.raises(TaskError) as cycle:
        await service.update(first.task_id, blocked_by=(second.task_id,))
    assert cycle.value.code == "dependency_cycle"

    with pytest.raises(TaskError) as duplicate:
        await service.update(second.task_id, blocked_by=(first.task_id, first.task_id))
    assert duplicate.value.code == "invalid_dependency"


async def test_incomplete_dependency_prevents_start(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    upstream = await service.create(subject="Upstream", description="Prepare input")
    downstream = await service.create(
        subject="Downstream",
        description="Consume input",
        blocked_by=(upstream.task_id,),
    )

    with pytest.raises(TaskError) as error:
        await service.update(downstream.task_id, status=TaskStatus.PENDING)

    assert error.value.code == "dependency_incomplete"


async def test_in_progress_task_cannot_add_incomplete_dependency(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    dependency = await service.create(subject="Dependency", description="Prepare input")
    task = await service.create(subject="Task", description="Run work")
    await service.update(task.task_id, status=TaskStatus.IN_PROGRESS)

    with pytest.raises(TaskError) as error:
        await service.update(task.task_id, blocked_by=(dependency.task_id,))

    assert error.value.code == "dependency_incomplete"


async def test_failed_task_can_retry_but_terminal_task_cannot_reopen(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    task = await service.create(subject="Task", description="Run work")
    await service.update(task.task_id, status=TaskStatus.IN_PROGRESS)
    await service.update(task.task_id, status=TaskStatus.FAILED, error="failed")

    retried = await service.update(task.task_id, status=TaskStatus.PENDING)
    assert retried.status == TaskStatus.PENDING

    await service.update(task.task_id, status=TaskStatus.IN_PROGRESS)
    await service.update(task.task_id, status=TaskStatus.COMPLETED)
    with pytest.raises(TaskError) as error:
        await service.update(task.task_id, status=TaskStatus.PENDING)
    assert error.value.code == "invalid_task_transition"


async def test_task_snapshots_and_events_are_persisted(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    task = await service.create(subject="Persist", description="Persist task")
    await service.update(task.task_id, status=TaskStatus.IN_PROGRESS, owner="main")

    tasks_dir = tmp_path / "run" / "tasks"
    snapshot = json.loads((tasks_dir / "task-1.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (tasks_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert snapshot["status"] == "in_progress"
    assert snapshot["owner"] == "main"
    assert [event["event_type"] for event in events] == ["created", "updated"]


async def test_task_tools_create_get_list_and_update(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    context = make_context(tmp_path)
    create_tool = TaskCreateTool(service)
    get_tool = TaskGetTool(service)
    list_tool = TaskListTool(service)
    update_tool = TaskUpdateTool(service)

    created = await create_tool.invoke(
        {"subject": "Inspect", "description": "Inspect repository"},
        context,
    )
    loaded = await get_tool.invoke({"task_id": "task-1"}, context)
    updated = await update_tool.invoke(
        {"task_id": "task-1", "status": "in_progress", "owner": "main"},
        context,
    )
    listed = await list_tool.invoke({"status": "in_progress"}, context)

    assert created.success
    assert loaded.data["task"]["task_id"] == "task-1"
    assert updated.data["task"]["status"] == "in_progress"
    assert [task["task_id"] for task in listed.data["tasks"]] == ["task-1"]


async def test_task_tools_return_stable_errors(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    context = make_context(tmp_path)

    missing = await TaskGetTool(service).invoke({"task_id": "task-9"}, context)
    invalid_dependency = await TaskCreateTool(service).invoke(
        {
            "subject": "Blocked",
            "description": "Needs missing task",
            "blocked_by": ["task-9"],
        },
        context,
    )

    assert missing.error_code == "task_not_found"
    assert invalid_dependency.error_code == "invalid_dependency"


async def test_task_tools_are_not_part_of_subagent_default_registry(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    names = build_default_tool_registry(context).names()

    assert "task_create" not in names
    assert "task_get" not in names
    assert "task_list" not in names
    assert "task_update" not in names
