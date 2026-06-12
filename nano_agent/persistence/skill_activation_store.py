from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.skills.registry import LoadedSkill
from nano_agent.tools.base import ToolContext


class SkillActivationRecord(BaseModel):
    schema_version: int = 1  # Skill 激活记录的数据结构版本。
    timestamp: datetime  # Skill 激活工具的执行时间。
    run_id: str  # 激活所属的 Agent 运行标识。
    llm_call_id: str | None  # 请求激活 Skill 的 LLM 调用标识。
    skill_name: str  # 被请求激活的 Skill 名称。
    content_sha256: str  # 激活时 Skill 正文的内容摘要。
    newly_activated: bool  # 本次调用是否首次加载该 Skill。


class SkillActivationStore:
    """Append skill activation metadata without persisting skill bodies."""

    filename = "skill_activations.jsonl"  # 每个 run 的 Skill 激活记录文件名。

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / self.filename  # 当前 run 的 Skill 激活记录路径。

    def append(
        self,
        *,
        context: ToolContext,
        skill: LoadedSkill,
        newly_activated: bool,
    ) -> None:
        record = SkillActivationRecord(
            timestamp=datetime.now(timezone.utc),
            run_id=context.run_id,
            llm_call_id=context.current_llm_call_id,
            skill_name=skill.descriptor.metadata.name,
            content_sha256=skill.content_sha256,
            newly_activated=newly_activated,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(record.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
