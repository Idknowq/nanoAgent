from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """一条可检索记忆记录。"""

    namespace: str  # 记忆命名空间，例如 repo、run、failure。
    key: str  # 命名空间内的记录标识。
    value: str  # 记忆正文，当前用纯文本保存。
    tags: list[str] = Field(default_factory=list)  # 辅助检索和分类的标签。
    expires_at: datetime | None = None  # TTL 过期时间；为空则永不过期。


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
        records = self._load_all()
        key = (record.namespace, record.key)
        replaced = False
        for i, existing in enumerate(records):
            if (existing.namespace, existing.key) == key:
                records[i] = record
                replaced = True
                break
        if not replaced:
            records.append(record)
        self._write_all(records)

    def _load_all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        return [
            MemoryRecord.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def delete(self, namespace: str, key: str) -> bool:
        """Delete a record by namespace + key. Returns True if deleted."""
        records = self._load_all()
        new_records = [r for r in records if (r.namespace, r.key) != (namespace, key)]
        if len(new_records) == len(records):
            return False
        self._write_all(new_records)
        return True

    def search(
        self,
        namespaces: str | list[str],
        *,
        tags: set[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        now = datetime.now(timezone.utc)
        records = [r for r in self._load_all() if r.expires_at is None or r.expires_at > now]
        namespace_set = {namespaces} if isinstance(namespaces, str) else set(namespaces)
        matches = [record for record in records if record.namespace in namespace_set]
        if tags:
            matches = [record for record in matches if tags.intersection(record.tags)]
        return sorted(matches, key=lambda record: (record.namespace, record.key))[:limit]

    def _write_all(self, records: list[MemoryRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            for r in records:
                file.write(r.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
