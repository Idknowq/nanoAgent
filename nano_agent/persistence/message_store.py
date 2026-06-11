from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.models import AgentMessage


class MessageRecord(BaseModel):
    """One ordered message from the LLM conversation protocol."""

    schema_version: int = 1
    sequence: int
    timestamp: datetime
    llm_call_id: str | None
    message: AgentMessage


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

    def append_many(
        self,
        messages: list[AgentMessage],
        llm_call_id: str | None = None,
    ) -> None:
        for message in messages:
            self.append(message, llm_call_id)

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

    def _existing_record_count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())
