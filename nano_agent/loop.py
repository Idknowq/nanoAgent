from __future__ import annotations

import json
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nano_agent.config import AgentConfig
from nano_agent.background.cancellation import AgentCancelledError, CancellationToken
from nano_agent.context.compactor import ContextCompactor
from nano_agent.hooks.base import AgentHook
from nano_agent.hooks.pipeline import HookPipeline
from nano_agent.models import (
    AgentMessage,
    ApprovalLevel,
    CompletionReport,
    LLMResponse,
    LLMStopReason,
    RunStatus,
    RunSummary,
    ToolCallRecord,
    ToolUseRequest,
)
from nano_agent.persistence.message_store import MessageStore
from nano_agent.services.llm import LLMClient
from nano_agent.services.errors import LLMErrorKind, LLMServiceError, normalize_llm_error
from nano_agent.services.retry import RetryPolicy
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolRegistry, ToolResult, ToolSpec
from nano_agent.tools.finish_run import FinishRunTool


class AgentLoopLimitError(RuntimeError):
    """Raised when a configured physical LLM call budget is exhausted."""


@dataclass
class _ToolExecutionOutcome:
    """One completed tool-use protocol item ready to persist and append."""

    tool_name: str  # Tool name to expose to round-level background query detection.
    result: ToolResult  # Normalized tool execution result.
    record: ToolCallRecord  # Durable summary record for RunSummary.tool_calls.
    message: AgentMessage  # Protocol tool result message to append to the conversation.
    completion_report: CompletionReport | None = None  # Valid finish_run report, if any.
    hook_messages: list[AgentMessage] = field(default_factory=list)  # Deferred hook output.


@dataclass
class _PreparedToolInvocation:
    """Validated concurrent tool invocation after ordered before-tool hooks."""

    tool_use: ToolUseRequest  # Original LLM tool request.
    tool: RuntimeTool  # Runtime tool instance selected from the registry.
    started: float  # Monotonic timestamp used for duration accounting.
    hook_messages: list[AgentMessage] = field(default_factory=list)  # Deferred hook output.


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
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_llm_calls: int | None = None,
        reserve_final_step: bool = False,
        cancellation_token: CancellationToken | None = None,
        idle_waiter: Callable[[float], Awaitable[bool]] | None = None,
    ) -> None:
        self.config = config  # 保存最大步数等循环控制配置。
        self.llm = llm  # 保存当前使用的 LLM 客户端。
        self.tools = tools  # 保存本轮 Agent 可调用的工具注册表。
        self.context = context  # 保存本轮 Agent 的工具运行上下文。
        self.hook_pipeline = HookPipeline(hooks)  # 统一执行 hook 扩展点。
        self.message_store = message_store  # 保存未压缩的完整协议消息流。
        self.compactor = compactor  # LLM 调用前的上下文压缩管线，可为空。
        self.retry_policy = retry_policy or RetryPolicy(
            base_seconds=config.llm_retry_base_seconds,
            max_seconds=config.llm_retry_max_seconds,
            jitter_seconds=config.llm_retry_jitter_seconds,
        )
        self.sleeper = sleeper
        self.max_llm_calls = max_llm_calls  # 当前 loop 允许的物理 LLM 调用上限。
        self.reserve_final_step = reserve_final_step  # 是否保留最后一步提交终止总结。
        self.cancellation_token = cancellation_token  # 当前运行的合作式取消信号。
        self.idle_waiter = idle_waiter  # 等待任一后台 Job 完成的运行时回调。

    async def run(self, run: RunSummary, initial_messages: list[AgentMessage]) -> RunSummary:
        messages = list(initial_messages)
        run.messages = messages
        if self.message_store is not None:
            self.message_store.append_many(messages)
        invalid_end_turns = 0

        loop_iterations = self.config.max_steps + int(self.reserve_final_step)
        for step_index in range(loop_iterations):
            self._raise_if_cancelled()
            self.context.current_step = min(step_index + 1, self.config.max_steps)
            self.context.max_steps = self.config.max_steps
            run.steps = self.context.current_step
            tool_specs = self.tools.specs()
            finalization_step = (
                self.reserve_final_step and step_index >= self.config.max_steps - 1
            )
            finalization_correction = (
                self.reserve_final_step and step_index == self.config.max_steps
            )
            if finalization_step:
                self._append_messages(
                    messages,
                    [
                        AgentMessage(
                            role="system",
                            content=(
                                (
                                    "Your previous finalization response was invalid. This is the "
                                    "only protocol-correction call. Do not request any investigation "
                                    "or file tools. Call finish_run exactly once as the only tool "
                                    "call, summarizing the reliable evidence already collected. "
                                    "Use blocked or failed if the delegated task is incomplete."
                                )
                                if finalization_correction
                                else (
                                    "This is the final response opportunity. Do not perform further "
                                    "investigation. Summarize the reliable evidence already collected "
                                    "and call finish_run as the only tool call. Use completed only when "
                                    "the delegated task is complete; otherwise use blocked or failed "
                                    "and state the partial findings and remaining uncertainty."
                                )
                            ),
                        )
                    ],
                )
                tool_specs = [
                    spec for spec in tool_specs if spec.name == FinishRunTool.name
                ]
            if self.compactor is not None:
                self._raise_if_cancelled()
                summary_calls = self.compactor.summary_llm_call_count
                messages = await self.compactor.prepare(messages, tool_specs)
                run.llm_call_count += self.compactor.summary_llm_call_count - summary_calls
            response, messages, deferred_hook_messages = await self._call_llm_with_recovery(
                run,
                messages,
                tool_specs,
            )
            self._raise_if_cancelled()

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
                if finalization_step and not finalization_correction:
                    run.messages = messages
                    continue
                if finalization_correction:
                    run.status = RunStatus.FAILED
                    run.notes.append(f"Agent loop exceeded max_steps={self.config.max_steps}")
                    run.notes.append(
                        "Agent finalization failed after one protocol-correction call."
                    )
                    run.completion_report = self._protocol_failure_report(
                        "The model ended the finalization correction without a valid "
                        "finish_run tool call."
                    )
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
            round_tool_results: list[tuple[str, ToolResult]] = []
            outcomes = await self._execute_tool_batch(
                response.tool_uses,
                finalization_step=finalization_step,
                finish_is_exclusive=finish_is_exclusive,
            )
            for outcome in outcomes:
                run.tool_calls.append(outcome.record)
                round_tool_results.append((outcome.tool_name, outcome.result))
                self._append_messages(messages, [outcome.message])
                if (
                    outcome.tool_name == FinishRunTool.name
                    and finish_is_exclusive
                    and outcome.result.error_code == "background_jobs_active"
                    and self.idle_waiter is not None
                ):
                    await self._idle_wait(messages)
                if outcome.completion_report is not None:
                    self._append_messages(
                        messages,
                        [
                            *deferred_hook_messages,
                            *self._ordered_hook_messages(outcomes),
                        ],
                    )
                    run.completion_report = outcome.completion_report
                    run.status = outcome.completion_report.status
                    run.messages = messages
                    return run

            if self._only_active_background_queries(round_tool_results):
                await self._idle_wait(messages)
            self._append_messages(
                messages,
                [
                    *deferred_hook_messages,
                    *self._ordered_hook_messages(outcomes),
                ],
            )
            run.messages = messages

        run.status = RunStatus.FAILED
        run.notes.append(f"Agent loop exceeded max_steps={self.config.max_steps}")
        if self.reserve_final_step:
            resolution = (
                "The model did not submit a valid finish_run after the reserved finalization "
                "call and one protocol-correction call."
            )
        else:
            resolution = (
                f"Agent loop exceeded max_steps={self.config.max_steps} without a valid "
                "finish_run."
            )
        run.completion_report = self._protocol_failure_report(resolution)
        run.messages = messages
        return run

    async def _execute_tool_batch(
        self,
        tool_uses: list[ToolUseRequest],
        *,
        finalization_step: bool,
        finish_is_exclusive: bool,
    ) -> list[_ToolExecutionOutcome]:
        """Execute one LLM tool-use batch with conservative concurrency boundaries."""
        outcomes: list[_ToolExecutionOutcome] = []
        concurrent_group: list[ToolUseRequest] = []
        concurrent_group_key: str | None = None

        async def flush_concurrent_group() -> None:
            nonlocal concurrent_group, concurrent_group_key
            if not concurrent_group:
                return
            outcomes.extend(
                await self._execute_concurrent_tool_group(
                    concurrent_group,
                    finish_is_exclusive=finish_is_exclusive,
                )
            )
            concurrent_group = []
            concurrent_group_key = None

        for tool_use in tool_uses:
            group_key = self._concurrent_group_key(
                tool_use,
                finalization_step=finalization_step,
            )
            if group_key is None:
                await flush_concurrent_group()
                outcomes.append(
                    await self._execute_tool_use(
                        tool_use,
                        finalization_step=finalization_step,
                        finish_is_exclusive=finish_is_exclusive,
                    )
                )
                continue
            if concurrent_group and group_key != concurrent_group_key:
                await flush_concurrent_group()
            concurrent_group.append(tool_use)
            concurrent_group_key = group_key

        await flush_concurrent_group()
        return outcomes

    def _concurrent_group_key(
        self,
        tool_use: ToolUseRequest,
        *,
        finalization_step: bool,
    ) -> str | None:
        """Return a batch key for tools that are safe to invoke concurrently."""
        if finalization_step and tool_use.name != FinishRunTool.name:
            return None
        try:
            tool = self.tools.get(tool_use.name)
        except KeyError:
            return None
        if (
            tool.requires_exclusive_execution
            or tool.is_mutating
            or not tool.can_run_concurrently
        ):
            return None
        return tool.conflict_group or tool.name

    async def _execute_concurrent_tool_group(
        self,
        tool_uses: list[ToolUseRequest],
        *,
        finish_is_exclusive: bool,
    ) -> list[_ToolExecutionOutcome]:
        """Run a group of concurrency-safe tools while preserving protocol order."""
        if len(tool_uses) == 1:
            return [
                await self._execute_tool_use(
                    tool_uses[0],
                    finalization_step=False,
                    finish_is_exclusive=finish_is_exclusive,
                )
            ]

        prepared: list[_PreparedToolInvocation] = []
        try:
            for tool_use in tool_uses:
                tool = self.tools.get(tool_use.name)
                self._raise_if_cancelled()
                started = time.monotonic()
                hook_messages: list[AgentMessage] = []
                hook_messages.extend(
                    await self.hook_pipeline.before_tool_call(self.context, tool, tool_use)
                )
                prepared.append(
                    _PreparedToolInvocation(
                        tool_use=tool_use,
                        tool=tool,
                        started=started,
                        hook_messages=hook_messages,
                    )
                )
        except Exception as exc:
            await self.hook_pipeline.on_error(self.context, exc)
            raise

        async def invoke(prepared_call: _PreparedToolInvocation) -> tuple[ToolResult, float]:
            result = await prepared_call.tool.invoke(prepared_call.tool_use.input, self.context)
            return result, time.monotonic() - prepared_call.started

        tasks = [asyncio.create_task(invoke(prepared_call)) for prepared_call in prepared]
        try:
            results = await asyncio.gather(*tasks)
        except Exception as exc:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.hook_pipeline.on_error(self.context, exc)
            raise

        outcomes: list[_ToolExecutionOutcome] = []
        try:
            for prepared_call, (result, duration) in zip(prepared, results, strict=True):
                completion_report: CompletionReport | None = None
                if isinstance(prepared_call.tool, FinishRunTool) and result.success:
                    result, completion_report = self._validate_completion(
                        result,
                        finish_is_exclusive=finish_is_exclusive,
                    )
                prepared_call.hook_messages.extend(
                    await self.hook_pipeline.after_tool_call(
                        self.context,
                        prepared_call.tool,
                        prepared_call.tool_use,
                        result,
                        duration,
                    )
                )
                self._raise_if_cancelled()
                outcomes.append(
                    self._tool_success_outcome(
                        prepared_call.tool_use,
                        prepared_call.tool,
                        result=result,
                        duration=duration,
                        completion_report=completion_report,
                        hook_messages=prepared_call.hook_messages,
                    )
                )
        except Exception as exc:
            await self.hook_pipeline.on_error(self.context, exc)
            raise

        return outcomes

    async def _execute_tool_use(
        self,
        tool_use: ToolUseRequest,
        *,
        finalization_step: bool,
        finish_is_exclusive: bool,
    ) -> _ToolExecutionOutcome:
        """Execute one tool-use request and return ordered protocol artifacts."""
        if finalization_step and tool_use.name != FinishRunTool.name:
            result = ToolResult.failure(
                code="finalization_tool_denied",
                message="Only finish_run is available during the reserved finalization step.",
            )
            return self._tool_failure_outcome(
                tool_use,
                result=result,
                approval_level=ApprovalLevel.READ,
            )
        try:
            tool = self.tools.get(tool_use.name)
        except KeyError:
            result = ToolResult.failure(
                code="tool_not_found",
                message=f"Tool not found: {tool_use.name}",
            )
            return self._tool_failure_outcome(
                tool_use,
                result=result,
                approval_level=ApprovalLevel.READ,
            )

        started = time.monotonic()
        hook_messages: list[AgentMessage] = []
        completion_report: CompletionReport | None = None
        try:
            self._raise_if_cancelled()
            hook_messages.extend(
                await self.hook_pipeline.before_tool_call(self.context, tool, tool_use)
            )
            result = await tool.invoke(tool_use.input, self.context)
            if isinstance(tool, FinishRunTool) and result.success:
                result, completion_report = self._validate_completion(
                    result,
                    finish_is_exclusive=finish_is_exclusive,
                )
            duration = time.monotonic() - started
            hook_messages.extend(
                await self.hook_pipeline.after_tool_call(
                    self.context,
                    tool,
                    tool_use,
                    result,
                    duration,
                )
            )
            self._raise_if_cancelled()
        except Exception as exc:
            await self.hook_pipeline.on_error(self.context, exc)
            raise

        return self._tool_success_outcome(
            tool_use,
            tool,
            result=result,
            duration=duration,
            completion_report=completion_report,
            hook_messages=hook_messages,
        )

    def _tool_success_outcome(
        self,
        tool_use: ToolUseRequest,
        tool: RuntimeTool,
        *,
        result: ToolResult,
        duration: float,
        completion_report: CompletionReport | None,
        hook_messages: list[AgentMessage],
    ) -> _ToolExecutionOutcome:
        """Build protocol artifacts for a tool that reached runtime invocation."""
        return _ToolExecutionOutcome(
            tool_name=tool.name,
            result=result,
            record=ToolCallRecord(
                tool_call_id=tool_use.id,
                tool_name=tool.name,
                input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                output_summary=result.summary,
                approval_level=tool.approval_level,
                duration_seconds=duration,
                success=result.success,
            ),
            message=self._tool_result_message(tool_use.id, result),
            completion_report=completion_report,
            hook_messages=hook_messages,
        )

    def _tool_failure_outcome(
        self,
        tool_use: ToolUseRequest,
        *,
        result: ToolResult,
        approval_level: ApprovalLevel,
    ) -> _ToolExecutionOutcome:
        """Build protocol artifacts for a tool request rejected before invocation."""
        return _ToolExecutionOutcome(
            tool_name=tool_use.name,
            result=result,
            record=ToolCallRecord(
                tool_call_id=tool_use.id,
                tool_name=tool_use.name,
                input_summary=json.dumps(tool_use.input, ensure_ascii=False),
                output_summary=result.summary,
                approval_level=approval_level,
                duration_seconds=0.0,
                success=False,
            ),
            message=self._tool_result_message(tool_use.id, result),
        )

    @staticmethod
    def _ordered_hook_messages(outcomes: list[_ToolExecutionOutcome]) -> list[AgentMessage]:
        """Flatten deferred hook output in LLM tool-use order."""
        messages: list[AgentMessage] = []
        for outcome in outcomes:
            messages.extend(outcome.hook_messages)
        return messages

    @staticmethod
    def _tool_result_message(tool_call_id: str, result: ToolResult) -> AgentMessage:
        """Convert one ToolResult into the protocol tool message."""
        return AgentMessage(
            role="tool",
            content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
            tool_call_id=tool_call_id,
        )

    async def _call_llm_with_recovery(
        self,
        run: RunSummary,
        messages: list[AgentMessage],
        tool_specs: list[ToolSpec],
    ) -> tuple[LLMResponse, list[AgentMessage], list[AgentMessage]]:
        transient_retries = 0
        continuation_count = 0
        reactive_used = False
        invalid_response_used = False
        attempt_type = "primary"
        attempt_index = 0
        recovered_from: str | None = None
        retry_delay: float | None = None

        while True:
            try:
                response, deferred = await self._perform_llm_request(
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
                if exc.kind == LLMErrorKind.INVALID_RESPONSE and not invalid_response_used:
                    invalid_response_used = True
                    self._append_messages(
                        messages,
                        [
                            AgentMessage(
                                role="system",
                                content=(
                                    "The provider returned an invalid response, usually malformed "
                                    "tool-call arguments. Regenerate the complete next response. "
                                    "If calling a tool, emit a new complete tool call with valid "
                                    "JSON arguments that match its schema. Do not continue, reuse, "
                                    "or repair fragments from the invalid tool call."
                                ),
                            )
                        ],
                    )
                    attempt_type = "invalid_response"
                    attempt_index = 1
                    recovered_from = failed_call_id
                    retry_delay = None
                    continue
                if exc.retryable and transient_retries < self.config.llm_max_transient_retries:
                    transient_retries += 1
                    retry_delay = self.retry_policy.delay_seconds(exc, transient_retries)
                    await self._sleep(retry_delay)
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
                    outcome = await self.compactor.reactive_compact(messages, tool_specs)
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

    async def _perform_llm_request(
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
        self._raise_if_cancelled()

        try:
            self._append_messages(
                messages,
                await self.hook_pipeline.before_llm_call(self.context, messages, tool_specs),
            )
        except Exception as exc:
            await self.hook_pipeline.on_error(self.context, exc)
            raise

        run.llm_call_count += 1
        self.context.current_llm_started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        try:
            response = await self.llm.complete(messages=messages, tools=tool_specs)
        except AgentCancelledError:
            raise
        except Exception as exc:
            self.context.current_llm_duration_seconds = time.monotonic() - started
            normalized = normalize_llm_error(exc)
            await self.hook_pipeline.on_error(self.context, normalized)
            if normalized is exc:
                raise
            raise normalized from exc

        self.context.current_llm_duration_seconds = time.monotonic() - started
        try:
            deferred.extend(await self.hook_pipeline.after_llm_call(self.context, response))
        except Exception as exc:
            await self.hook_pipeline.on_error(self.context, exc)
            raise
        self._raise_if_cancelled()
        return response, deferred

    def _raise_if_cancelled(self) -> None:
        if self.cancellation_token is not None:
            self.cancellation_token.raise_if_cancelled()

    async def _sleep(self, delay_seconds: float) -> None:
        if self.cancellation_token is None:
            await self.sleeper(delay_seconds)
            return
        if await asyncio.to_thread(self.cancellation_token.wait, delay_seconds):
            self.cancellation_token.raise_if_cancelled()

    async def _idle_wait(self, messages: list[AgentMessage]) -> None:
        if self.idle_waiter is None:
            return
        completed = await self.idle_waiter(self.config.background_idle_wait_timeout_seconds)
        if completed:
            return
        self._append_messages(
            messages,
            [
                AgentMessage(
                    role="system",
                    content=(
                        "Background jobs are still active after the runtime idle wait. "
                        "Continue useful foreground work if available. Do not poll their "
                        "status repeatedly."
                    ),
                )
            ],
        )

    @staticmethod
    def _only_active_background_queries(
        tool_results: list[tuple[str, ToolResult]],
    ) -> bool:
        query_tools = {"delegated_task_get", "delegated_task_list"}
        active_statuses = {"queued", "running", "cancel_requested"}
        if not tool_results or any(
            name not in query_tools or not result.success for name, result in tool_results
        ):
            return False
        jobs: list[dict] = []
        for _, result in tool_results:
            job = result.data.get("background_job")
            if isinstance(job, dict):
                jobs.append(job)
            listed = result.data.get("background_jobs")
            if isinstance(listed, list):
                jobs.extend(item for item in listed if isinstance(item, dict))
        return any(job.get("status") in active_statuses for job in jobs)

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

    def _append_messages(
        self,
        target: list[AgentMessage],
        messages: list[AgentMessage],
    ) -> None:
        target.extend(messages)
        if self.message_store is not None:
            self.message_store.append_many(messages, self.context.current_llm_call_id)
