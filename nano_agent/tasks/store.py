from __future__ import annotations

import os
import re
from pathlib import Path

from nano_agent.persistence.json_io import atomic_write_json
from nano_agent.tasks.errors import TaskError
from nano_agent.tasks.models import TaskEvent, TaskRecord, TaskStatus


class TaskStore:
    events_filename = "events.jsonl"  # Task 变更事件的追加日志文件名。

    def __init__(self, run_dir: Path) -> None:
        self.tasks_dir = run_dir / "tasks"  # 当前主运行的 Task 持久化目录。

    def next_id(self) -> str:
        highest = 0  # 已持久化 Task 文件中的最大数字序号。
        if self.tasks_dir.is_dir():
            for path in self.tasks_dir.iterdir():
                match = re.fullmatch(r"task-(\d+)\.json", path.name)
                if path.is_file() and match is not None:
                    highest = max(highest, int(match.group(1)))
        return f"task-{highest + 1}"

    def save(
        self,
        task: TaskRecord,
        *,
        event_type: str,
        previous_status: TaskStatus | None,
    ) -> Path:
        target = self.tasks_dir / f"{task.task_id}.json"  # 当前 Task 快照写入路径。
        atomic_write_json(target, task.model_dump(mode="json"))
        event = TaskEvent(
            task_id=task.task_id,
            event_type=event_type,
            previous_status=previous_status,
            current_status=task.status,
        )
        events_path = self.tasks_dir / self.events_filename
        with events_path.open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
        return target

    def get(self, task_id: str) -> TaskRecord:
        path = self.tasks_dir / f"{task_id}.json"  # 被查询 Task 的快照路径。
        if not re.fullmatch(r"task-\d+", task_id) or not path.is_file():
            raise TaskError(f"Task not found: {task_id}", code="task_not_found")
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[TaskRecord]:
        if not self.tasks_dir.is_dir():
            return []
        tasks = [
            TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.tasks_dir.glob("task-*.json")
            if re.fullmatch(r"task-\d+\.json", path.name)
        ]
        return sorted(tasks, key=lambda task: int(task.task_id.removeprefix("task-")))
