from __future__ import annotations

from datetime import datetime, timezone

from nano_agent.tasks.errors import TaskError
from nano_agent.tasks.models import TaskBlockedReason, TaskRecord, TaskStatus
from nano_agent.tasks.store import TaskStore


class TaskService:
    """Apply task lifecycle and dependency rules over one run-local store."""

    def __init__(self, store: TaskStore) -> None:
        self.store = store  # 保存当前主运行的 Task 持久化接口。

    def create(
        self,
        *,
        subject: str,
        description: str,
        blocked_by: tuple[str, ...] = (),
    ) -> TaskRecord:
        task_id = self.store.next_id()  # 为新 Task 分配的持久化递增标识。
        dependencies = self._normalize_dependencies(task_id, blocked_by)
        status, reason = self._dependency_state(dependencies)
        task = TaskRecord(
            task_id=task_id,
            subject=subject,
            description=description,
            status=status,
            blocked_by=dependencies,
            blocked_reason=reason,
        )
        self.store.save(task, event_type="created", previous_status=None)
        return task

    def get(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def list(self, status: TaskStatus | None = None) -> list[TaskRecord]:
        tasks = self.store.list()
        if status is None:
            return tasks
        return [task for task in tasks if task.status == status]

    def update(
        self,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        blocked_by: tuple[str, ...] | None = None,
        owner: str | None = None,
        result: str | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        task = self.store.get(task_id)
        updates = (subject, description, status, blocked_by, owner, result, error)
        if all(value is None for value in updates):
            raise TaskError("Task update contains no changes", code="invalid_task_input")
        if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise TaskError(
                f"Terminal task cannot be updated: {task.task_id}",
                code="invalid_task_transition",
            )
        previous_status = task.status
        if subject is not None:
            task.subject = subject
        if description is not None:
            task.description = description
        if blocked_by is not None:
            task.blocked_by = self._normalize_dependencies(task_id, blocked_by)
            self._validate_acyclic(task)
            if (
                task.status == TaskStatus.IN_PROGRESS
                and self._incomplete_dependencies(task.blocked_by)
            ):
                raise TaskError(
                    f"In-progress task cannot add incomplete dependencies: {task.task_id}",
                    code="dependency_incomplete",
                )
        if owner is not None:
            task.owner = owner
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error

        if status is not None:
            self._transition(task, status)
        elif blocked_by is not None and (
            task.status == TaskStatus.PENDING
            or (
                task.status == TaskStatus.BLOCKED
                and task.blocked_reason == TaskBlockedReason.DEPENDENCY
            )
        ):
            task.status, task.blocked_reason = self._dependency_state(task.blocked_by)

        task.updated_at = datetime.now(timezone.utc)
        self.store.save(task, event_type="updated", previous_status=previous_status)
        if task.status == TaskStatus.COMPLETED:
            self._unlock_dependents(task.task_id)
        return task

    def _transition(self, task: TaskRecord, target: TaskStatus) -> None:
        allowed = {
            TaskStatus.PENDING: {
                TaskStatus.IN_PROGRESS,
                TaskStatus.BLOCKED,
                TaskStatus.CANCELLED,
            },
            TaskStatus.IN_PROGRESS: {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.CANCELLED,
            },
            TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.CANCELLED},
            TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.CANCELLED},
            TaskStatus.COMPLETED: set(),
            TaskStatus.CANCELLED: set(),
        }
        if target == task.status == TaskStatus.BLOCKED:
            task.blocked_reason = TaskBlockedReason.EXTERNAL
            return
        if target == task.status:
            return
        if target not in allowed[task.status]:
            raise TaskError(
                f"Invalid task transition: {task.status.value} -> {target.value}",
                code="invalid_task_transition",
            )
        if target in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
            incomplete = self._incomplete_dependencies(task.blocked_by)
            if incomplete:
                raise TaskError(
                    f"{task.task_id} is blocked by incomplete tasks: {', '.join(incomplete)}",
                    code="dependency_incomplete",
                )
            task.blocked_reason = None
        elif target == TaskStatus.BLOCKED:
            task.blocked_reason = TaskBlockedReason.EXTERNAL
        task.status = target

    def _normalize_dependencies(
        self,
        task_id: str,
        blocked_by: tuple[str, ...],
    ) -> tuple[str, ...]:
        dependencies = tuple(dict.fromkeys(blocked_by))
        if len(dependencies) != len(blocked_by):
            raise TaskError(
                f"Task dependencies contain duplicates: {task_id}",
                code="invalid_dependency",
            )
        if task_id in dependencies:
            raise TaskError(
                f"Task cannot depend on itself: {task_id}",
                code="invalid_dependency",
            )
        for dependency in dependencies:
            try:
                self.store.get(dependency)
            except TaskError as exc:
                raise TaskError(
                    f"Task dependency does not exist: {dependency}",
                    code="invalid_dependency",
                ) from exc
        return dependencies

    def _validate_acyclic(self, updated: TaskRecord) -> None:
        tasks = {task.task_id: task for task in self.store.list()}
        tasks[updated.task_id] = updated

        def visit(task_id: str, path: set[str]) -> None:
            if task_id in path:
                raise TaskError(
                    f"Task dependency cycle includes {task_id}",
                    code="dependency_cycle",
                )
            task = tasks.get(task_id)
            if task is None:
                return
            next_path = {*path, task_id}
            for dependency in task.blocked_by:
                visit(dependency, next_path)

        visit(updated.task_id, set())

    def _dependency_state(
        self,
        blocked_by: tuple[str, ...],
    ) -> tuple[TaskStatus, TaskBlockedReason | None]:
        if self._incomplete_dependencies(blocked_by):
            return TaskStatus.BLOCKED, TaskBlockedReason.DEPENDENCY
        return TaskStatus.PENDING, None

    def _incomplete_dependencies(self, blocked_by: tuple[str, ...]) -> list[str]:
        return [
            task_id
            for task_id in blocked_by
            if self.store.get(task_id).status != TaskStatus.COMPLETED
        ]

    def _unlock_dependents(self, completed_task_id: str) -> None:
        for task in self.store.list():
            if (
                completed_task_id in task.blocked_by
                and task.status == TaskStatus.BLOCKED
                and task.blocked_reason == TaskBlockedReason.DEPENDENCY
                and not self._incomplete_dependencies(task.blocked_by)
            ):
                previous_status = task.status
                task.status = TaskStatus.PENDING
                task.blocked_reason = None
                task.updated_at = datetime.now(timezone.utc)
                self.store.save(
                    task,
                    event_type="dependency_unblocked",
                    previous_status=previous_status,
                )
