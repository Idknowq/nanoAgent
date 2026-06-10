from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """一条可检索记忆记录。"""

    namespace: str  # 记忆命名空间，例如 repo、run、failure。
    key: str  # 命名空间内的记录标识。
    value: str  # 记忆正文，当前用纯文本保存。
    tags: list[str] = Field(default_factory=list)  # 辅助检索和分类的标签。


class InMemoryStore:
    """进程内记忆存储，用于持久化方案实现前的最小接口。"""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []  # 保存当前进程内的全部记忆记录。

    def add(self, record: MemoryRecord) -> None:
        self._records.append(record)

    def search(self, namespace: str) -> list[MemoryRecord]:
        return [record for record in self._records if record.namespace == namespace]


class JsonlMemoryStore:
    """预留的 JSONL 持久化记忆接口。"""

    def __init__(self, path: Path) -> None:
        self.path = path  # 保存 JSONL 记忆文件的目标路径。
