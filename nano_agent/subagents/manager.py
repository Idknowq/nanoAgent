from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.background.cancellation import AgentCancelledError, CancellationToken
from nano_agent.context.compactor import CompactionStore, ContextCompactor
from nano_agent.hooks.base import AgentHook
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.loop import AgentLoop, AgentLoopLimitError
from nano_agent.models import ApprovalLevel, RunStatus, RunSummary
from nano_agent.persistence.message_store import MessageStore
from nano_agent.persistence.summary_store import SummaryStore
from nano_agent.services.llm import LLMClient
from nano_agent.subagents.context import SubagentContextBuilder
from nano_agent.subagents.models import (
    SubagentErrorKind,
    PreparedSubagent,
    SubagentRequest,
    SubagentResult,
    SubagentState,
    SubagentStatus,
)
from nano_agent.subagents.store import SubagentStore
from nano_agent.tools.base import ToolContext, ToolRegistry, build_default_tool_registry
from nano_agent.tools.finish_run import FinishRunTool


class SubagentManager:
    """Create and synchronously execute isolated one-level subagents."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        llm: LLMClient,
        parent_context: ToolContext,
        parent_tools: ToolRegistry,
        hooks_factory: Callable[[], list[AgentHook]] | None = None,
        context_builder: SubagentContextBuilder | None = None,
        store: SubagentStore | None = None,
        summary_store: SummaryStore | None = None,
        llm_factory: Callable[[], LLMClient] | None = None,
    ) -> None:
        self.config = config  # 保存子 Agent 的额度和恢复配置。
        self.llm = llm  # 复用父运行配置的 LLM 客户端。
        self.parent_context = parent_context  # 保存父运行上下文和工作区信息。
        self.parent_tool_names = parent_tools.names()  # 保存父 Agent 当前拥有的工具名称。
        self.child_tool_names = (
            build_default_tool_registry(parent_context).names()
        )  # 保存隔离子环境可重新构造的工具名称。
        self.background_tool_names = {
            spec.name
            for spec in parent_tools.specs()
            if spec.approval_level == ApprovalLevel.READ
            and spec.category == "filesystem"
            and not spec.is_mutating
        } & self.child_tool_names  # 保存后台模式允许使用的只读仓库工具。
        self.hooks_factory = hooks_factory or (
            lambda: build_default_hooks(config)
        )  # 为每个子 Agent 创建独立 hook 实例。
        self.context_builder = (
            context_builder or SubagentContextBuilder()
        )  # 构造不包含父消息历史的子上下文。
        self.store = store or SubagentStore()  # 持久化子 Agent 状态和生命周期事件。
        self.summary_store = summary_store or SummaryStore()  # 持久化子运行执行摘要。
        self.llm_factory = llm_factory or (lambda: self.llm)  # 为每个子运行提供 LLM 客户端。

    async def run(self, request: SubagentRequest) -> SubagentResult:
        return await self.execute(self.prepare(request))

    def prepare(self, request: SubagentRequest) -> PreparedSubagent:
        self._validate_request(request)
        subagent_id = self.store.next_id(self.parent_context.run_dir)
        run_id = f"{self.parent_context.run_id}-{subagent_id}"
        run_dir = self.parent_context.run_dir / "subagents" / subagent_id
        allowed_tools = self._validate_tools(request.allowed_tools)
        state = SubagentState(
            subagent_id=subagent_id,
            parent_run_id=self.parent_context.run_id,
            status=SubagentStatus.CREATED,
            task=request.task,
            allowed_tools=tuple(sorted(allowed_tools)),
        )
        self.store.save(run_dir, state)

        run = RunSummary(
            run_id=run_id,
            repo_url=self.parent_context.repo_url,
            workspace_path=self.parent_context.workspace_path,
            status=RunStatus.PENDING,
            artifacts={
                "messages": "messages.jsonl",
                "state": "subagent.json",
                "result": "result.json",
                "summary": "summary.json",
            },
        )
        return PreparedSubagent(
            request=request,
            run=run,
            run_dir=str(run_dir),
            allowed_tools=tuple(sorted(allowed_tools)),
            state=state,
        )

    def validate_background_request(self, request: SubagentRequest) -> None:
        names = set(request.allowed_tools or self.config.subagent_default_tools)
        denied = names - self.background_tool_names
        if denied:
            allowed = ", ".join(sorted(self.background_tool_names)) or "none"
            raise ValueError(
                "Background subagents cannot use these tools: "
                + ", ".join(sorted(denied))
                + f". Allowed background tools are: {allowed}. "
                "Omit allowed_tools to use the default read-only set."
            )

    async def execute(
        self,
        prepared: PreparedSubagent,
        cancellation_token: CancellationToken | None = None,
    ) -> SubagentResult:
        run = prepared.run
        state = prepared.state
        run_dir = Path(prepared.run_dir)
        if state.status != SubagentStatus.CREATED:
            raise ValueError(f"Subagent is not executable from status {state.status.value}")
        if cancellation_token is not None and cancellation_token.cancelled:
            return self.cancel(prepared)

        run.status = RunStatus.RUNNING
        state.transition(SubagentStatus.RUNNING)
        state.started_at = datetime.now(timezone.utc)
        self.store.save(run_dir, state)

        try:
            result = await self._execute(
                prepared.request,
                run,
                run_dir,
                set(prepared.allowed_tools),
                state.subagent_id,
                cancellation_token,
            )
        except AgentLoopLimitError as exc:
            run.status = RunStatus.FAILED
            run.notes.append(str(exc))
            result = self._failure_result(
                run,
                state.subagent_id,
                run_dir,
                SubagentErrorKind.LLM_CALL_LIMIT,
                str(exc),
            )
        except AgentCancelledError as exc:
            run.status = RunStatus.CANCELLED
            run.notes.append(str(exc))
            result = SubagentResult(
                subagent_id=state.subagent_id,
                parent_run_id=self.parent_context.run_id,
                status=SubagentStatus.CANCELLED,
                error_kind=SubagentErrorKind.CANCELLED,
                error=str(exc),
                steps_used=run.steps,
                llm_calls_used=run.llm_call_count,
                run_dir=str(run_dir),
            )
        except Exception as exc:  # noqa: BLE001 - delegation must not terminate the parent loop.
            run.status = RunStatus.FAILED
            run.notes.append(f"{type(exc).__name__}: {exc}")
            result = self._failure_result(
                run,
                state.subagent_id,
                run_dir,
                SubagentErrorKind.EXECUTION_ERROR,
                f"{type(exc).__name__}: {exc}",
            )

        return self._finalize(prepared, result)

    def cancel(self, prepared: PreparedSubagent) -> SubagentResult:
        if prepared.state.status != SubagentStatus.CREATED:
            raise ValueError(
                f"Only a created subagent can be cancelled before execution: "
                f"{prepared.state.status.value}"
            )
        prepared.run.status = RunStatus.CANCELLED
        result = SubagentResult(
            subagent_id=prepared.state.subagent_id,
            parent_run_id=self.parent_context.run_id,
            status=SubagentStatus.CANCELLED,
            error_kind=SubagentErrorKind.CANCELLED,
            error="Background job was cancelled before execution.",
            run_dir=prepared.run_dir,
        )
        return self._finalize(prepared, result)

    def _finalize(
        self,
        prepared: PreparedSubagent,
        result: SubagentResult,
    ) -> SubagentResult:
        run = prepared.run
        state = prepared.state
        run_dir = Path(prepared.run_dir)
        state.transition(result.status)
        finished_at = datetime.now(timezone.utc)
        state.finished_at = finished_at
        state.result = result
        run.finished_at = finished_at
        self.summary_store.save(run_dir, run)
        self.store.save_result(run_dir, result)
        self.store.save(run_dir, state)
        return result

    def _validate_request(self, request: SubagentRequest) -> None:
        if self.parent_context.delegation_depth > 0 or self.parent_context.subagent_id is not None:
            raise ValueError("Subagents cannot create other subagents.")
        if len(request.task) > self.config.subagent_max_task_chars:
            raise ValueError(
                f"Subagent task exceeds {self.config.subagent_max_task_chars} characters"
            )
        if (
            request.context is not None
            and len(request.context) > self.config.subagent_max_context_chars
        ):
            raise ValueError(
                f"Subagent context exceeds {self.config.subagent_max_context_chars} characters"
            )
        if request.max_steps > self.config.subagent_max_steps:
            raise ValueError(
                f"Subagent max_steps exceeds configured limit {self.config.subagent_max_steps}"
            )
        if request.max_llm_calls > self.config.subagent_max_llm_calls:
            raise ValueError(
                "Subagent max_llm_calls exceeds configured limit "
                f"{self.config.subagent_max_llm_calls}"
            )

    async def _execute(
        self,
        request: SubagentRequest,
        run: RunSummary,
        run_dir: Path,
        allowed_tools: set[str],
        subagent_id: str,
        cancellation_token: CancellationToken | None,
    ) -> SubagentResult:
        child_config = self.config.model_copy(update={"max_steps": request.max_steps})
        context = ToolContext(
            run_id=run.run_id,
            parent_run_id=self.parent_context.run_id,
            subagent_id=subagent_id,
            delegation_depth=self.parent_context.delegation_depth + 1,
            repo_url=self.parent_context.repo_url,
            workspace_path=self.parent_context.workspace_path,
            run_dir=run_dir,
            runtime_dir=run_dir / "runtime",
            config=child_config,
            max_steps=request.max_steps,
        )
        registry = build_default_tool_registry(context).selected(
            allowed_tools | {FinishRunTool.name}
        )
        message_store = MessageStore(run_dir)
        child_llm = self.llm_factory()
        compactor = ContextCompactor(
            config=child_config,
            llm=child_llm,
            store=CompactionStore(run.run_id, run_dir, message_store),
            repo_url=context.repo_url,
            workspace_path=context.workspace_path,
        )
        hooks: list[AgentHook] = self.hooks_factory()
        loop = AgentLoop(
            config=child_config,
            llm=child_llm,
            tools=registry,
            context=context,
            hooks=hooks,
            message_store=message_store,
            compactor=compactor,
            max_llm_calls=request.max_llm_calls,
            reserve_final_step=True,
            cancellation_token=cancellation_token,
        )
        completed = await loop.run(run, self.context_builder.build(request))
        return self._result_from_run(completed, context.subagent_id or "unknown", run_dir)

    def _validate_tools(self, requested: tuple[str, ...]) -> set[str]:
        names = set(requested or self.config.subagent_default_tools)
        unavailable_to_parent = names - self.parent_tool_names
        if unavailable_to_parent:
            raise ValueError(
                "Subagent tools are unavailable to the parent agent: "
                + ", ".join(sorted(unavailable_to_parent))
            )
        unavailable_to_child = names - self.child_tool_names
        if unavailable_to_child:
            raise ValueError(
                "Subagent tools cannot be constructed in an isolated child context: "
                + ", ".join(sorted(unavailable_to_child))
            )
        names.discard("delegate_task")
        names.discard(FinishRunTool.name)
        return names

    def _result_from_run(
        self,
        run: RunSummary,
        subagent_id: str,
        run_dir: Path,
    ) -> SubagentResult:
        report = run.completion_report
        if run.status == RunStatus.COMPLETED and report is not None:
            output = self._bounded_output(report.resolution)
            return SubagentResult(
                subagent_id=subagent_id,
                parent_run_id=self.parent_context.run_id,
                status=SubagentStatus.SUCCEEDED,
                output=output,
                steps_used=run.steps,
                llm_calls_used=run.llm_call_count,
                completion_report=report,
                run_dir=str(run_dir),
            )
        if run.status == RunStatus.BLOCKED:
            error = report.resolution if report is not None else "Subagent is blocked."
            return SubagentResult(
                subagent_id=subagent_id,
                parent_run_id=self.parent_context.run_id,
                status=SubagentStatus.BLOCKED,
                error_kind=SubagentErrorKind.BLOCKED,
                error=self._bounded_output(error),
                steps_used=run.steps,
                llm_calls_used=run.llm_call_count,
                completion_report=report,
                run_dir=str(run_dir),
            )
        kind = (
            SubagentErrorKind.STEP_LIMIT
            if any("max_steps" in note for note in run.notes)
            else SubagentErrorKind.EXECUTION_ERROR
        )
        error = report.resolution if report is not None else f"Subagent ended with {run.status}."
        return self._failure_result(run, subagent_id, run_dir, kind, error)

    def _failure_result(
        self,
        run: RunSummary,
        subagent_id: str,
        run_dir: Path,
        kind: SubagentErrorKind,
        error: str,
    ) -> SubagentResult:
        return SubagentResult(
            subagent_id=subagent_id,
            parent_run_id=self.parent_context.run_id,
            status=SubagentStatus.FAILED,
            error_kind=kind,
            error=self._bounded_output(error),
            steps_used=run.steps,
            llm_calls_used=run.llm_call_count,
            completion_report=run.completion_report,
            run_dir=str(run_dir),
        )

    def _bounded_output(self, value: str) -> str:
        limit = self.config.subagent_max_result_chars
        if len(value) <= limit:
            return value
        marker = "...[truncated]"
        return value[: limit - len(marker)] + marker
