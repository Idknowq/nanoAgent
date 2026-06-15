from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock

from nano_agent.persistence.json_io import atomic_write_json
from nano_agent.subagents.models import (
    SubagentLifecycleEvent,
    SubagentResult,
    SubagentState,
)


class SubagentStore:
    filename = "subagent.json"  # 子 Agent 最新状态快照文件名。
    lifecycle_filename = "lifecycle.jsonl"  # 子 Agent 生命周期追加日志文件名。
    result_filename = "result.json"  # 子 Agent 完整结构化结果文件名。

    def __init__(self) -> None:
        self._id_lock = Lock()  # 串行化同一 Manager 内的子 Agent 标识分配。

    def next_id(self, parent_run_dir: Path) -> str:
        with self._id_lock:
            subagents_dir = parent_run_dir / "subagents"  # 当前父运行的子 Agent 根目录。
            subagents_dir.mkdir(parents=True, exist_ok=True)
            highest = 0  # 已存在子 Agent 目录中的最大数字序号。
            for path in subagents_dir.iterdir():
                match = re.fullmatch(r"subagent-(\d+)", path.name)
                if path.is_dir() and match is not None:
                    highest = max(highest, int(match.group(1)))
            subagent_id = f"subagent-{highest + 1}"
            (subagents_dir / subagent_id).mkdir()
            return subagent_id

    def save(self, run_dir: Path, state: SubagentState) -> Path:
        target = run_dir / self.filename
        atomic_write_json(target, state.model_dump(mode="json"))
        event = SubagentLifecycleEvent(
            subagent_id=state.subagent_id,
            parent_run_id=state.parent_run_id,
            status=state.status,
        )
        with (run_dir / self.lifecycle_filename).open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
        return target

    def save_result(self, run_dir: Path, result: SubagentResult) -> Path:
        target = run_dir / self.result_filename  # 完整结果的原子写入目标。
        atomic_write_json(target, result.model_dump(mode="json"))
        return target
