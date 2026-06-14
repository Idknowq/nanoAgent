import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.base import NoOpHook
from nano_agent.hooks.llm_metrics import LLMMetricsHook
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, LLMUsage, RunSummary
from nano_agent.services.errors import LLMErrorKind, LLMServiceError
from nano_agent.tools.base import ToolContext, ToolRegistry


class SuccessfulLLM:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return LLMResponse(
            content="done",
            stop_reason="end_turn",
            provider="deepseek",
            model="deepseek-test",
            usage=LLMUsage(
                input_tokens=10,
                output_tokens=4,
                total_tokens=14,
                cached_tokens=3,
            ),
        )


class FailingLLM:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider unavailable")


class RateLimitedOnceLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise LLMServiceError(
                "rate limited",
                kind=LLMErrorKind.RATE_LIMIT,
                status_code=429,
            )
        return LLMResponse(content="done", stop_reason="end_turn")


class FailingBeforeHook(NoOpHook):
    def before_llm_call(self, context, messages, tools):  # type: ignore[no-untyped-def]
        raise RuntimeError("hook failed before request")


def make_context(tmp_path: Path) -> ToolContext:
    config = AgentConfig(
        workspace_root=tmp_path,
        runs_root=tmp_path / "runs",
        llm_model="configured-model",
    )
    return ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=config.runs_root / "run-1",
        config=config,
    )


def read_records(context: ToolContext) -> list[dict]:
    path = context.run_dir / "llm_calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_llm_metrics_hook_records_usage_and_duration(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    loop = AgentLoop(
        config=context.config,
        llm=SuccessfulLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        hooks=[LLMMetricsHook()],
    )

    result = loop.run(
        RunSummary(run_id=context.run_id, repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    record = read_records(context)[0]
    assert result.llm_call_count == 1
    assert record["llm_call_id"] == "llm-1"
    assert record["provider"] == "deepseek"
    assert record["model"] == "deepseek-test"
    assert record["input_tokens"] == 10
    assert record["cached_tokens"] == 3
    assert record["duration_seconds"] >= 0
    assert record["success"]


def test_llm_metrics_hook_records_failed_calls(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    loop = AgentLoop(
        config=context.config,
        llm=FailingLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        hooks=[LLMMetricsHook()],
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        loop.run(
            RunSummary(run_id=context.run_id, repo_url=context.repo_url),
            [AgentMessage(role="user", content="start")],
        )

    record = read_records(context)[0]
    assert not record["success"]
    assert record["error_type"] == "LLMServiceError"
    assert record["error_kind"] == "unknown"
    assert record["error_message"] == "provider unavailable"


def test_llm_metrics_hook_does_not_record_unstarted_calls(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    loop = AgentLoop(
        config=context.config,
        llm=SuccessfulLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        hooks=[LLMMetricsHook(), FailingBeforeHook()],
    )

    with pytest.raises(RuntimeError, match="hook failed before request"):
        loop.run(
            RunSummary(run_id=context.run_id, repo_url=context.repo_url),
            [AgentMessage(role="user", content="start")],
        )

    assert not (context.run_dir / "llm_calls.jsonl").exists()


def test_llm_metrics_hook_records_recovery_attempt_metadata(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    context.config.llm_retry_jitter_seconds = 0
    loop = AgentLoop(
        config=context.config,
        llm=RateLimitedOnceLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        hooks=[LLMMetricsHook()],
        sleeper=lambda _: None,
    )

    loop.run(
        RunSummary(run_id=context.run_id, repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    failed, recovered = read_records(context)
    assert failed["error_kind"] == "rate_limit"
    assert failed["status_code"] == 429
    assert failed["attempt_type"] == "primary"
    assert recovered["attempt_type"] == "transient"
    assert recovered["attempt_index"] == 1
    assert recovered["recovered_from_call_id"] == "llm-1"
    assert recovered["retry_delay_seconds"] == 1
