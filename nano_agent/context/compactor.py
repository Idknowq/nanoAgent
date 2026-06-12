from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nano_agent.config import AgentConfig
from nano_agent.context.snapshot import RunContextBuilder
from nano_agent.models import AgentMessage
from nano_agent.persistence.json_io import atomic_write_json
from nano_agent.persistence.message_store import MessageStore
from nano_agent.services.llm import LLMClient
from nano_agent.tools.base import ToolSpec

MICRO_COMPACT_MESSAGE = "[Earlier tool result compacted. Re-run if needed.]"


class CompactionRecord(BaseModel):
    """One persisted context compaction event."""

    schema_version: int = 1  # 压缩记录的数据结构版本。
    timestamp: datetime  # 压缩发生时间。
    run_id: str  # 压缩所属的 Agent 运行标识。
    compaction_type: Literal["auto", "reactive"]  # 自动摘要或应急裁剪。
    attempt: int  # 当前类型压缩在本次 run 内的尝试序号。
    before_estimated_tokens: int  # 压缩前估算输入 token。
    after_estimated_tokens: int  # 压缩后估算输入 token。
    transcript_path: str  # 压缩前完整 transcript 的 run 相对路径。
    success: bool  # 压缩是否成功产生更小的活动上下文。
    error_message: str | None = None  # 摘要失败或压缩无效时的错误说明。


class ContextSizeEstimator:
    """Estimate request size without depending on a provider tokenizer."""

    def __init__(self, chars_per_token: int = 3) -> None:
        self.chars_per_token = chars_per_token  # 字符到 token 的保守换算比例。

    def estimate(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> int:
        payload = {
            "messages": [message.model_dump(mode="json") for message in messages],
            "tools": [tool.model_dump(mode="json") for tool in tools],
        }
        characters = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return max(1, (characters + self.chars_per_token - 1) // self.chars_per_token)


class CompactionStore:
    """Persist large tool results, transcripts, checkpoints, and compaction events."""

    def __init__(self, run_id: str, run_dir: Path, message_store: MessageStore | None) -> None:
        self.run_id = run_id  # 当前 Agent 运行标识。
        self.run_dir = run_dir  # 当前 run 的持久化目录。
        self.message_store = message_store  # 原始追加式消息存储，可为空。
        self._transcript_sequence = 0  # 当前进程内 transcript 递增序号。

    def persist_tool_result(self, tool_call_id: str, content: str) -> Path:
        digest = hashlib.sha256(tool_call_id.encode("utf-8")).hexdigest()[:20]
        target = self.run_dir / "tool-results" / f"{digest}.json"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as file:
                file.write(content)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
        return target

    def write_transcript(
        self,
        messages: list[AgentMessage],
        *,
        compaction_type: Literal["auto", "reactive"],
        attempt: int,
    ) -> Path:
        self._transcript_sequence += 1
        target = (
            self.run_dir
            / "transcripts"
            / f"{compaction_type}-{attempt:03d}-{self._transcript_sequence:03d}.jsonl"
        )
        source = (
            self.message_store.load_messages()
            if self.message_store is not None and self.message_store.path.exists()
            else messages
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as file:
            for message in source:
                file.write(message.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())
        return target

    def save_checkpoint(self, messages: list[AgentMessage]) -> Path:
        target = self.run_dir / "context_checkpoint.json"
        atomic_write_json(
            target,
            {
                "schema_version": 1,
                "run_id": self.run_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "messages": [message.model_dump(mode="json") for message in messages],
            },
        )
        return target

    def append_record(self, record: CompactionRecord) -> None:
        target = self.run_dir / "compactions.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as file:
            file.write(record.model_dump_json() + "\n")
            file.flush()
            os.fsync(file.fileno())


class ContextCompactor:
    """Run cheap context preprocessing before LLM-backed and reactive compaction."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        llm: LLMClient,
        store: CompactionStore,
        repo_url: str,
        workspace_path: Path,
        estimator: ContextSizeEstimator | None = None,
    ) -> None:
        self.config = config  # 当前 Agent 的上下文压缩配置。
        self.llm = llm  # 生成 compact summary 时使用的模型客户端。
        self.store = store  # 保存大结果、transcript、checkpoint 和审计记录。
        self.repo_url = repo_url  # 当前运行对应的仓库地址。
        self.workspace_path = workspace_path  # 当前运行对应的工作区路径。
        self.estimator = estimator or ContextSizeEstimator()  # 请求 token 估算器。
        self.auto_compact_attempts = 0  # 已执行的自动摘要压缩次数。
        self.reactive_compact_attempts = 0  # 已执行的应急压缩次数。
        self.summary_llm_call_count = 0  # 自动摘要额外发起的 LLM 调用次数。

    def prepare(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> list[AgentMessage]:
        if not self.config.context_compaction_enabled:
            return messages
        prepared = self.tool_result_budget(messages)
        prepared = self.snip_compact(prepared)
        prepared = self.micro_compact(prepared)
        while (
            self.should_auto_compact(prepared, tools)
            and self.auto_compact_attempts < self.config.max_auto_compactions
        ):
            compacted = self.compact_history(prepared, tools)
            if self.estimator.estimate(compacted, tools) >= self.estimator.estimate(
                prepared, tools
            ):
                prepared = compacted
                break
            prepared = compacted
        self.store.save_checkpoint(prepared)
        return prepared

    def tool_result_budget(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        copied = self._copy_messages(messages)
        latest = self._latest_tool_batch(copied)
        total = sum(len(message.content) for message in latest)
        if total <= self.config.tool_result_budget_chars:
            return copied
        for message in sorted(latest, key=lambda item: len(item.content), reverse=True):
            if total <= self.config.tool_result_budget_chars:
                break
            original_chars = len(message.content)
            path = self.store.persist_tool_result(message.tool_call_id or "unknown", message.content)
            preview = message.content[: self.config.tool_result_preview_chars]
            replacement = self._persisted_tool_result(
                message,
                path,
                original_chars=original_chars,
                preview=preview,
            )
            if len(replacement) >= original_chars:
                continue
            message.content = replacement
            total -= original_chars - len(message.content)
        return copied

    def snip_compact(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        copied = self._copy_messages(messages)
        if len(copied) <= self.config.snip_message_threshold:
            return copied
        head_end = min(self.config.snip_keep_head, len(copied))
        tail_start = max(head_end, len(copied) - self.config.snip_keep_tail)
        head_end = self._extend_head_boundary(copied, head_end)
        tail_start = self._extend_tail_boundary(copied, tail_start)
        if head_end >= tail_start:
            return copied
        removed = tail_start - head_end
        placeholder = AgentMessage(
            role="system",
            content=(
                f"[{removed} earlier messages removed from active context. "
                "Full history is persisted in the run transcript.]"
            ),
        )
        return [*copied[:head_end], placeholder, *copied[tail_start:]]

    def micro_compact(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        copied = self._copy_messages(messages)
        tool_results = [message for message in copied if message.role == "tool"]
        keep = self.config.micro_keep_recent_tool_results
        compactable = tool_results[:-keep] if keep else tool_results
        for message in compactable:
            if len(message.content) < self.config.micro_tool_result_min_chars:
                continue
            message.content = self._micro_tool_result(message)
        return copied

    def should_auto_compact(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> bool:
        usable = max(
            1,
            self.config.context_max_input_tokens
            - self.config.context_output_reserve_tokens,
        )
        threshold = int(usable * self.config.context_auto_compact_ratio)
        return self.estimator.estimate(messages, tools) >= threshold

    def compact_history(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> list[AgentMessage]:
        self.auto_compact_attempts += 1
        before = self.estimator.estimate(messages, tools)
        transcript = self.store.write_transcript(
            messages,
            compaction_type="auto",
            attempt=self.auto_compact_attempts,
        )
        try:
            summary = self._summarize(messages, transcript)
            compacted = self._summary_context(messages, summary, transcript)
            after = self.estimator.estimate(compacted, tools)
            success = after < before
            error = None if success else "summary did not reduce estimated context size"
        except Exception as exc:
            compacted = messages
            after = before
            success = False
            error = str(exc)[:2_000]
        self.store.append_record(
            CompactionRecord(
                timestamp=datetime.now(timezone.utc),
                run_id=self.store.run_id,
                compaction_type="auto",
                attempt=self.auto_compact_attempts,
                before_estimated_tokens=before,
                after_estimated_tokens=after,
                transcript_path=self._relative_path(transcript),
                success=success,
                error_message=error,
            )
        )
        return compacted

    def reactive_compact(
        self,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> list[AgentMessage]:
        if self.reactive_compact_attempts >= self.config.max_reactive_compactions:
            return messages
        self.reactive_compact_attempts += 1
        before = self.estimator.estimate(messages, tools)
        transcript = self.store.write_transcript(
            messages,
            compaction_type="reactive",
            attempt=self.reactive_compact_attempts,
        )
        prefix = self._stable_prefix(messages)
        tail_start = max(len(prefix), len(messages) - self.config.reactive_keep_recent_messages)
        tail_start = self._extend_tail_boundary(messages, tail_start)
        notice = AgentMessage(
            role="system",
            content=(
                "[Reactive compact applied after a prompt-too-long error. "
                f"Earlier history is persisted at {self._relative_path(transcript)}.]"
            ),
        )
        compacted = [*prefix, notice, *self._copy_messages(messages[tail_start:])]
        after = self.estimator.estimate(compacted, tools)
        self.store.append_record(
            CompactionRecord(
                timestamp=datetime.now(timezone.utc),
                run_id=self.store.run_id,
                compaction_type="reactive",
                attempt=self.reactive_compact_attempts,
                before_estimated_tokens=before,
                after_estimated_tokens=after,
                transcript_path=self._relative_path(transcript),
                success=after < before,
                error_message=None if after < before else "reactive compact did not reduce size",
            )
        )
        self.store.save_checkpoint(compacted)
        return compacted

    def can_reactive_compact(self) -> bool:
        return self.reactive_compact_attempts < self.config.max_reactive_compactions

    def _summarize(self, messages: list[AgentMessage], transcript: Path) -> str:
        snapshot = RunContextBuilder().build(
            repo_url=self.repo_url,
            workspace_path=self.workspace_path,
            current_step=0,
            max_steps=self.config.max_steps,
            messages=messages,
        )
        conversation = json.dumps(
            [message.model_dump(mode="json") for message in messages],
            ensure_ascii=False,
        )
        prompt = (
            "Summarize this coding-agent conversation so work can continue after context "
            "compaction. Preserve the original goal, explicit user constraints, repository "
            "facts, important files and symbols, edits made, commands and test results, "
            "failed approaches, current hypotheses, activated skills, remaining work, and "
            "exact blockers. Never claim verification succeeded unless the transcript says "
            "it did.\n\n"
            f"Transcript: {self._relative_path(transcript)}\n"
            f"Derived state:\n{snapshot.to_prompt()}\n\n"
            f"Conversation:\n{conversation}"
        )
        self.summary_llm_call_count += 1
        response = self.llm.complete([AgentMessage(role="user", content=prompt)], tools=[])
        summary = response.content.strip()
        if not summary:
            raise RuntimeError("compaction summary was empty")
        return summary

    def _summary_context(
        self,
        messages: list[AgentMessage],
        summary: str,
        transcript: Path,
    ) -> list[AgentMessage]:
        preserved = self._stable_prefix(messages)
        active_skills = [
            message
            for message in messages
            if message.role == "system" and "<active_skill>" in message.content
        ]
        seen = {message.content for message in preserved}
        for message in active_skills:
            if message.content not in seen:
                preserved.append(message.model_copy(deep=True))
                seen.add(message.content)
        preserved.append(
            AgentMessage(
                role="system",
                content=(
                    "<conversation_summary>\n"
                    f"<transcript>{self._relative_path(transcript)}</transcript>\n"
                    f"{summary}\n"
                    "</conversation_summary>"
                ),
            )
        )
        return preserved

    @staticmethod
    def _stable_prefix(messages: list[AgentMessage]) -> list[AgentMessage]:
        preserved: list[AgentMessage] = []
        first_user_added = False
        for message in messages:
            if message.role == "system" and not first_user_added:
                preserved.append(message.model_copy(deep=True))
                continue
            if message.role == "user" and not first_user_added:
                preserved.append(message.model_copy(deep=True))
                first_user_added = True
                break
            break
        return preserved

    @staticmethod
    def _latest_tool_batch(messages: list[AgentMessage]) -> list[AgentMessage]:
        last_assistant = -1
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "assistant" and messages[index].tool_uses:
                last_assistant = index
                break
        if last_assistant < 0:
            return []
        tool_ids = {tool_use.id for tool_use in messages[last_assistant].tool_uses}
        return [
            message
            for message in messages[last_assistant + 1 :]
            if message.role == "tool" and message.tool_call_id in tool_ids
        ]

    @staticmethod
    def _extend_head_boundary(messages: list[AgentMessage], head_end: int) -> int:
        if head_end <= 0 or head_end >= len(messages):
            return head_end
        previous = messages[head_end - 1]
        if previous.role != "assistant" or not previous.tool_uses:
            return head_end
        tool_ids = {tool_use.id for tool_use in previous.tool_uses}
        while (
            head_end < len(messages)
            and messages[head_end].role == "tool"
            and messages[head_end].tool_call_id in tool_ids
        ):
            head_end += 1
        return head_end

    @staticmethod
    def _extend_tail_boundary(messages: list[AgentMessage], tail_start: int) -> int:
        if tail_start <= 0 or tail_start >= len(messages):
            return tail_start
        current = messages[tail_start]
        if current.role != "tool" or not current.tool_call_id:
            return tail_start
        for index in range(tail_start - 1, -1, -1):
            message = messages[index]
            if message.role == "assistant" and any(
                tool_use.id == current.tool_call_id for tool_use in message.tool_uses
            ):
                return index
            if message.role == "assistant":
                break
        return tail_start

    def _persisted_tool_result(
        self,
        message: AgentMessage,
        path: Path,
        *,
        original_chars: int,
        preview: str,
    ) -> str:
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            payload = {"success": True, "summary": "large tool result persisted", "data": {}}
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        payload["data"] = {
            "persisted_output": {
                "path": self._relative_path(path),
                "characters": original_chars,
                "sha256": hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
                "preview": preview,
            },
            "recovery": "Re-run the original tool call if full content is needed.",
            **{
                key: value
                for key, value in data.items()
                if key not in {"content", "stdout_tail", "stderr_tail"}
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _micro_tool_result(message: AgentMessage) -> str:
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            return MICRO_COMPACT_MESSAGE
        success = bool(payload.get("success"))
        compacted = {
            "success": success,
            "summary": MICRO_COMPACT_MESSAGE,
            "data": {"compacted": True},
            "error_code": payload.get("error_code"),
            "error_message": payload.get("error_message") if not success else None,
        }
        return json.dumps(compacted, ensure_ascii=False)

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.store.run_dir).as_posix()

    @staticmethod
    def _copy_messages(messages: list[AgentMessage]) -> list[AgentMessage]:
        return [message.model_copy(deep=True) for message in messages]


def is_prompt_too_long_error(error: Exception) -> bool:
    """Return whether a provider error represents context-window exhaustion."""

    code = getattr(error, "code", None)
    if code is None:
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            nested_error = body.get("error")
            nested_code = nested_error.get("code") if isinstance(nested_error, dict) else None
            code = body.get("code") or nested_code
    if str(code).lower() in {
        "context_length_exceeded",
        "max_context_window",
        "prompt_is_too_long",
        "prompt_too_long",
    }:
        return True
    message = str(error).lower()
    markers = (
        "context_length_exceeded",
        "maximum context length",
        "max_context_window",
        "prompt is too long",
        "prompt_too_long",
        "too many tokens",
    )
    return any(marker in message for marker in markers)
