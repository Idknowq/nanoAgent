from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone

from nano_agent.config import AgentConfig
from nano_agent.context.compactor import ContextCompactor
from nano_agent.hooks.base import AgentHook, HookResult
from nano_agent.models import (
    AgentMessage,
    CompletionReport,
    LLMResponse,
    LLMStopReason,
    RunStatus,
    RunSummary,
    ToolCallRecord,
)
from nano_agent.persistence.message_store import MessageStore
from nano_agent.services.llm import LLMClient
from nano_agent.services.errors import LLMErrorKind, LLMServiceError, normalize_llm_error
from nano_agent.services.retry import RetryPolicy
from nano_agent.tools.base import ToolContext, ToolRegistry, ToolResult, ToolSpec
from nano_agent.tools.finish_run import FinishRunTool


class AgentLoopLimitError(RuntimeError):
    """Raised when a configured physical LLM call budget is exhausted."""


class AgentLoop:
    """Claude Code 风格的核心循环：LLM 响应、工具调用、工具结果回填、继续循环。"""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        tools: ToolRegistry,
        context: ToolContext,
        hooks: list[AgentHook] | None = None,
        message_store: MessageStore | None = None,
        compactor: ContextCompactor | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_llm_calls: int | None = None,
    ) -> None:
        self.config = config  # 保存最大步数等循环控制配置。
        self.llm = llm  # 保存当前使用的 LLM 客户端。
        self.tools = tools  # 保存本轮 Agent 可调用的工具注册表。
        self.context = context  # 保存本轮 Agent 的工具运行上下文。
        self.hooks = hooks or []  # 保存 loop 扩展点列表。
        self.message_store = message_store  # 保存未压缩的完整协议消息流。
        self.compactor = compactor  # LLM 调用前的上下文压缩管线，可为空。
        self.retry_policy = retry_policy or RetryPolicy(
            base_seconds=config.llm_retry_base_seconds,
            max_seconds=config.llm_retry_max_seconds,
            jitter_seconds=config.llm_retry_jitter_seconds,
        )
        self.sleeper = sleeper
        self.max_llm_calls = max_llm_calls  # 当前 loop 允许的物理 LLM 调用上限。

    def run(self, run: RunSummary, initial_messages: list[AgentMessage]) -> RunSummary:
        messages = list(initial_messages)
        run.messages = messages
        if self.message_store is not None:
            self.message_store.append_many(messages)
        invalid_end_turns = 0

        for step_index in range(self.config.max_steps):
            self.context.current_step = step_index + 1
            self.context.max_steps = self.config.max_steps
            run.steps = self.context.current_step
            tool_specs = self.tools.specs()
            if self.compactor is not None:
                summary_calls = self.compactor.summary_llm_call_count
                messages = self.compactor.prepare(messages, tool_specs)
                run.llm_call_count += self.compactor.summary_llm_call_count - summary_calls
            response, messages, deferred_hook_messages = self._call_llm_with_recovery(
                run,
                messages,
                tool_specs,
            )

            self._append_messages(
                messages,
                [
                    AgentMessage(
                        role="assistant",
                        content=response.content,
                        tool_uses=response.tool_uses,
                    )
                ],
            )

            if response.stop_reason == LLMStopReason.END_TURN:
                self._append_messages(messages, deferred_hook_messages)
                if not self.tools.contains(FinishRunTool.name):
                    run.status = RunStatus.COMPLETED
                    run.messages = messages
                    return run
                invalid_end_turns += 1
                if invalid_end_turns == 1:
                    self._append_messages(
                        messages,
                        [
                            AgentMessage(
                                role="system",
                                content=(
                                    "The run is not finished. Submit exactly one finish_run "
                                    "tool call with a structured completed, blocked, or failed "
                                    "report. Plain end_turn does not determine run status."
                                ),
                            )
                        ],
                    )
                    run.messages = messages
                    continue
                run.status = RunStatus.FAILED
                run.completion_report = self._protocol_failure_report(
                    "The model ended twice without a valid finish_run tool call."
                )
                run.messages = messages
                return run

            if response.stop_reason in {
                LLMStopReason.CONTENT_FILTER,
                LLMStopReason.UNKNOWN,
            }:
                self._append_messages(messages, deferred_hook_messages)
                run.status = RunStatus.FAILED
                run.completion_report = self._protocol_failure_report(
                    f"LLM response stopped with {response.stop_reason.value}."
                )
                run.messages = messages
                return run

            finish_is_exclusive = (
                len(response.tool_uses) == 1
                and response.tool_uses[0].name == FinishRunTool.name
            )
            for tool_use in response.tool_uses:
                try:
                    tool = self.tools.get(tool_use.name)
                except KeyError:
                    result = ToolResult.failure(
                        code="tool_not_found",
                        message=f"Tool not found: {tool_use.name}",
                    )
                    run.tool_calls.append(
                        ToolCallRecord(
                            tool_call_id=tool_use.id,
                            tool_name=tool_use.name,
                            input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                            output_summary=result.summary,
                            approval_level="read",  # type: ignore
                            duration_seconds=0.0,
                            success=False,
                        )
                    )
                    self._append_messages(
                        messages,
                        [
                            AgentMessage(
                                role="tool",
                                content=json.dumps(
                                    result.model_dump(mode="json"), ensure_ascii=False
                                ),
                                tool_call_id=tool_use.id,
                            )
                        ],
                    )
                    continue
                started = time.monotonic()
                completion_report: CompletionReport | None = None
                try:
                    for hook in self.hooks:
                        self._append_hook_messages(
                            deferred_hook_messages,
                            hook.before_tool_call(self.context, tool, tool_use),
                        )
                    result = tool.invoke(tool_use.input, self.context)
                    if isinstance(tool, FinishRunTool) and result.success:
                        result, completion_report = self._validate_completion(
                            result,
                            finish_is_exclusive=finish_is_exclusive,
                        )
                    duration = time.monotonic() - started
                    for hook in self.hooks:
                        self._append_hook_messages(
                            deferred_hook_messages,
                            hook.after_tool_call(
                                self.context,
                                tool,
                                tool_use,
                                result,
                                duration,
                            ),
                        )
                except Exception as exc:
                    for hook in self.hooks:
                        hook.on_error(self.context, exc)
                    raise
                run.tool_calls.append(
                    ToolCallRecord(
                        tool_call_id=tool_use.id,
                        tool_name=tool.name,
                        input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                        output_summary=result.summary,
                        approval_level=tool.approval_level,
                        duration_seconds=duration,
                        success=result.success,
                    )
                )
                self._append_messages(
                    messages,
                    [
                        AgentMessage(
                            role="tool",
                            content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                            tool_call_id=tool_use.id,
                        )
                    ],
                )
                if completion_report is not None:
                    self._append_messages(messages, deferred_hook_messages)
                    run.completion_report = completion_report
                    run.status = completion_report.status
                    run.messages = messages
                    return run

            self._append_messages(messages, deferred_hook_messages)
            run.messages = messages

        run.status = RunStatus.FAILED
        run.notes.append(f"Agent loop exceeded max_steps={self.config.max_steps}")
        run.completion_report = self._protocol_failure_report(
            f"Agent loop exceeded max_steps={self.config.max_steps} without a valid finish_run."
        )
        run.messages = messages
        return run

    def _call_llm_with_recovery(
        self,
        run: RunSummary,
        messages: list[AgentMessage],
        tool_specs: list[ToolSpec],
    ) -> tuple[LLMResponse, list[AgentMessage], list[AgentMessage]]:
        transient_retries = 0
        continuation_count = 0
        reactive_used = False
        attempt_type = "primary"
        attempt_index = 0
        recovered_from: str | None = None
        retry_delay: float | None = None

        while True:
            try:
                response, deferred = self._perform_llm_request(
                    run,
                    messages,
                    tool_specs,
                    attempt_type=attempt_type,
                    attempt_index=attempt_index,
                    recovered_from=recovered_from,
                    retry_delay=retry_delay,
                )
            except LLMServiceError as exc:
                failed_call_id = self.context.current_llm_call_id
                if exc.retryable and transient_retries < self.config.llm_max_transient_retries:
                    transient_retries += 1
                    retry_delay = self.retry_policy.delay_seconds(exc, transient_retries)
                    self.sleeper(retry_delay)
                    attempt_type = "transient"
                    attempt_index = transient_retries
                    recovered_from = failed_call_id
                    continue
                if (
                    exc.kind == LLMErrorKind.PROMPT_TOO_LONG
                    and not reactive_used
                    and self.compactor is not None
                    and self.compactor.can_reactive_compact()
                ):
                    outcome = self.compactor.reactive_compact(messages, tool_specs)
                    reactive_used = True
                    if not outcome.reduced:
                        raise LLMServiceError(
                            "reactive compact did not reduce estimated context size "
                            f"({outcome.before_estimated_tokens} -> "
                            f"{outcome.after_estimated_tokens} tokens)",
                            kind=LLMErrorKind.PROMPT_TOO_LONG,
                            status_code=exc.status_code,
                        ) from exc
                    messages = outcome.messages
                    attempt_type = "reactive"
                    attempt_index = 1
                    recovered_from = failed_call_id
                    retry_delay = None
                    continue
                raise

            if response.stop_reason != LLMStopReason.MAX_TOKENS:
                return response, messages, deferred

            truncated_call_id = self.context.current_llm_call_id
            self._append_messages(
                messages,
                [AgentMessage(role="assistant", content=response.content)],
            )
            self._append_messages(messages, deferred)
            if continuation_count >= self.config.llm_max_continuations:
                raise LLMServiceError(
                    "LLM output remained truncated after "
                    f"{self.config.llm_max_continuations} continuation request(s)",
                    kind=LLMErrorKind.OUTPUT_TRUNCATED,
                )

            continuation_count += 1
            self._append_messages(
                messages,
                [
                    AgentMessage(
                        role="system",
                        content=self._continuation_prompt(response),
                    )
                ],
            )
            attempt_type = "continuation"
            attempt_index = continuation_count
            recovered_from = truncated_call_id
            retry_delay = None

    def _perform_llm_request(
        self,
        run: RunSummary,
        messages: list[AgentMessage],
        tool_specs: list[ToolSpec],
        *,
        attempt_type: str,
        attempt_index: int,
        recovered_from: str | None,
        retry_delay: float | None,
    ) -> tuple[LLMResponse, list[AgentMessage]]:
        if self.max_llm_calls is not None and run.llm_call_count >= self.max_llm_calls:
            raise AgentLoopLimitError(
                f"Agent loop exceeded max_llm_calls={self.max_llm_calls}"
            )
        self.context.current_llm_call_id = self._llm_call_id(attempt_type, attempt_index)
        self.context.current_llm_started_at = None
        self.context.current_llm_duration_seconds = None
        self.context.current_llm_attempt_type = attempt_type
        self.context.current_llm_attempt_index = attempt_index
        self.context.current_llm_recovered_from = recovered_from
        self.context.current_llm_retry_delay_seconds = retry_delay
        deferred: list[AgentMessage] = []

        for hook in self.hooks:
            self._append_hook_messages_to_conversation(
                messages,
                hook.before_llm_call(self.context, messages, tool_specs),
            )

        run.llm_call_count += 1
        self.context.current_llm_started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        try:
            response = self.llm.complete(messages=messages, tools=tool_specs)
        except Exception as exc:
            self.context.current_llm_duration_seconds = time.monotonic() - started
            normalized = normalize_llm_error(exc)
            for hook in self.hooks:
                hook.on_error(self.context, normalized)
            if normalized is exc:
                raise
            raise normalized from exc

        self.context.current_llm_duration_seconds = time.monotonic() - started
        for hook in self.hooks:
            self._append_hook_messages(
                deferred,
                hook.after_llm_call(self.context, response),
            )
        return response, deferred

    def _llm_call_id(self, attempt_type: str, attempt_index: int) -> str:
        base = f"llm-{self.context.current_step}"
        if attempt_type == "primary":
            return base
        return f"{base}-{attempt_type}-{attempt_index}"

    @staticmethod
    def _continuation_prompt(response: LLMResponse) -> str:
        if response.truncated_tool_call or response.tool_uses:
            return (
                "The previous response was truncated while producing a tool call. "
                "Do not continue or reuse partial JSON. Regenerate the complete tool call "
                "as a new call, without repeating completed prose."
            )
        return (
            "The previous response was truncated by the output token limit. Continue from "
            "where it stopped without repeating completed content. Complete the current "
            "action or submit finish_run."
        )

    def _validate_completion(
        self,
        result: ToolResult,
        *,
        finish_is_exclusive: bool,
    ) -> tuple[ToolResult, CompletionReport | None]:
        report = CompletionReport.model_validate(result.data["completion_report"])
        if not finish_is_exclusive:
            return (
                ToolResult.failure(
                    code="invalid_completion",
                    message="finish_run must be the only tool call in the LLM response",
                    data={
                        "validation_errors": [
                            "finish_run must be the only tool call in the LLM response"
                        ]
                    },
                ),
                None,
            )
        return result, report

    @staticmethod
    def _protocol_failure_report(reason: str) -> CompletionReport:
        return CompletionReport(
            status=RunStatus.FAILED,
            problem="The agent did not submit a valid final result.",
            root_cause="The finish_run termination protocol was not completed.",
            resolution=reason,
            remaining_risks=["Repository work may be incomplete or unverified."],
        )

    def _append_hook_messages(
        self,
        target: list[AgentMessage],
        result: HookResult | None,
    ) -> None:
        if result is not None:
            target.extend(result.injected_messages)

    def _append_hook_messages_to_conversation(
        self,
        target: list[AgentMessage],
        result: HookResult | None,
    ) -> None:
        if result is not None:
            self._append_messages(target, result.injected_messages)

    def _append_messages(
        self,
        target: list[AgentMessage],
        messages: list[AgentMessage],
    ) -> None:
        target.extend(messages)
        if self.message_store is not None:
            self.message_store.append_many(messages, self.context.current_llm_call_id)
