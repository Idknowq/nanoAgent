from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.models import AgentMessage


class MessageRecord(BaseModel):
    """One ordered message from the LLM conversation protocol."""

    schema_version: int = 1  # 消息记录的数据结构版本。
    sequence: int  # 消息在当前运行中的递增序号。
    timestamp: datetime  # 消息写入持久化文件的时间。
    llm_call_id: str | None  # 消息关联的 LLM 调用标识；初始消息为空。
    message: AgentMessage  # 完整的 Agent 协议消息。


class MessageStore:
    """Append and recover the complete message stream for one run."""

    filename = "messages.jsonl"

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / self.filename
        self._sequence = self._existing_record_count()

    def append(self, message: AgentMessage, llm_call_id: str | None = None) -> MessageRecord:
        self._sequence += 1
        record = MessageRecord(
            sequence=self._sequence,
            timestamp=datetime.now(timezone.utc),
            llm_call_id=llm_call_id,
            message=message,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(record.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
        return record

    async def append_async(
        self,
        message: AgentMessage,
        llm_call_id: str | None = None,
    ) -> MessageRecord:
        """Append one message without blocking the event loop."""

        return await asyncio.to_thread(self.append, message, llm_call_id)

    def append_many(
        self,
        messages: list[AgentMessage],
        llm_call_id: str | None = None,
    ) -> None:
        for message in messages:
            self.append(message, llm_call_id)

    async def append_many_async(
        self,
        messages: list[AgentMessage],
        llm_call_id: str | None = None,
    ) -> None:
        """Append messages without blocking the event loop."""

        await asyncio.to_thread(self.append_many, messages, llm_call_id)

    def load_messages(self) -> list[AgentMessage]:
        if not self.path.exists():
            return []
        records = [
            MessageRecord.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        records.sort(key=lambda record: record.sequence)
        return [record.message for record in records]

    async def load_messages_async(self) -> list[AgentMessage]:
        """Load persisted messages without blocking the event loop."""

        return await asyncio.to_thread(self.load_messages)

    def _existing_record_count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())
