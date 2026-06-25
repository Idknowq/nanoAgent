from __future__ import annotations

import os
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

    def search(
        self,
        namespaces: str | list[str],
        *,
        tags: set[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        namespace_set = {namespaces} if isinstance(namespaces, str) else set(namespaces)
        records = [record for record in self._records if record.namespace in namespace_set]
        if tags:
            records = [record for record in records if tags.intersection(record.tags)]
        return sorted(records, key=lambda record: (record.namespace, record.key))[:limit]


class JsonlMemoryStore:
    """Small append-only memory store with deterministic metadata filtering."""

    def __init__(self, path: Path) -> None:
        self.path = path  # 保存 JSONL 记忆文件的目标路径。

    def add(self, record: MemoryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(record.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())

    def upsert(self, record: MemoryRecord) -> None:
        """Add or replace a record with the same namespace + key."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records: list[MemoryRecord] = []
        key = (record.namespace, record.key)
        replaced = False
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                existing = MemoryRecord.model_validate_json(line)
                if (existing.namespace, existing.key) == key:
                    records.append(record)
                    replaced = True
                else:
                    records.append(existing)
        if not replaced:
            records.append(record)
        with self.path.open("w", encoding="utf-8") as file:
            for r in records:
                file.write(r.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())

    def search(
        self,
        namespaces: str | list[str],
        *,
        tags: set[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        namespace_set = {namespaces} if isinstance(namespaces, str) else set(namespaces)
        records = [
            MemoryRecord.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        matches = [record for record in records if record.namespace in namespace_set]
        if tags:
            matches = [record for record in matches if tags.intersection(record.tags)]
        return sorted(matches, key=lambda record: (record.namespace, record.key))[:limit]
