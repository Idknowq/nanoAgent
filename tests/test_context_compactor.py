import json
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.context.compactor import (
    MICRO_COMPACT_MESSAGE,
    CompactionStore,
    ContextCompactor,
)
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.persistence.message_store import MessageStore


class SummaryLLM:
    """测试用摘要模型，固定返回可预测的压缩摘要。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录摘要请求次数。
        self.messages: list[AgentMessage] = []  # 记录最近一次摘要请求。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.messages = list(messages)
        return LLMResponse(content="Goal and verified repository state.", stop_reason="end_turn")


def build_compactor(
    tmp_path: Path,
    config: AgentConfig,
) -> tuple[ContextCompactor, SummaryLLM, MessageStore]:
    """构造隔离的压缩器、摘要模型和原始消息存储。"""

    llm = SummaryLLM()
    run_dir = tmp_path / "run"
    message_store = MessageStore(run_dir)
    compactor = ContextCompactor(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        store=CompactionStore("run-1", run_dir, message_store),
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path / "workspace",
    )
    return compactor, llm, message_store


def tool_exchange(call_id: str, content: str) -> list[AgentMessage]:
    """创建一组合法的 assistant tool_use 与 tool_result 消息。"""

    return [
        AgentMessage(
            role="assistant",
            content="read",
            tool_uses=[ToolUseRequest(id=call_id, name="read_file", input={"path": "a.py"})],
        ),
        AgentMessage(role="tool", content=content, tool_call_id=call_id),
    ]


def test_tool_result_budget_persists_largest_latest_result(tmp_path: Path) -> None:
    config = AgentConfig(
        tool_result_budget_chars=250,
        tool_result_preview_chars=16,
    )
    compactor, _, store = build_compactor(tmp_path, config)
    large = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "x" * 600}}
    )
    small = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "small"}}
    )
    messages = [
        AgentMessage(role="user", content="inspect"),
        AgentMessage(
            role="assistant",
            content="read files",
            tool_uses=[
                ToolUseRequest(id="large", name="read_file", input={"path": "large.py"}),
                ToolUseRequest(id="small", name="read_file", input={"path": "small.py"}),
            ],
        ),
        AgentMessage(role="tool", content=large, tool_call_id="large"),
        AgentMessage(role="tool", content=small, tool_call_id="small"),
    ]
    store.append_many(messages)

    prepared = compactor.tool_result_budget(messages)

    replacement = json.loads(prepared[2].content)
    persisted = compactor.workspace_path / replacement["data"]["persisted_output"]["path"]
    assert persisted.read_text(encoding="utf-8").strip() == large
    assert replacement["data"]["persisted_output"]["path_base"] == "workspace"
    assert "Use read_file on that path" in replacement["data"]["recovery"]
    assert prepared[3].content == small
    assert messages[2].content == large


def test_tool_result_budget_enforces_latest_batch_total(tmp_path: Path) -> None:
    config = AgentConfig(
        tool_result_budget_chars=3_000,
        tool_result_preview_chars=16,
    )
    compactor, _, store = build_compactor(tmp_path, config)
    first = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "a" * 2_000}}
    )
    second = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "b" * 2_000}}
    )
    messages = [
        AgentMessage(role="user", content="inspect"),
        AgentMessage(
            role="assistant",
            content="read files",
            tool_uses=[
                ToolUseRequest(id="first", name="read_file", input={"path": "first.py"}),
                ToolUseRequest(id="second", name="read_file", input={"path": "second.py"}),
            ],
        ),
        AgentMessage(role="tool", content=first, tool_call_id="first"),
        AgentMessage(role="tool", content=second, tool_call_id="second"),
    ]
    store.append_many(messages)

    prepared = compactor.tool_result_budget(messages)

    assert prepared[2].content != first or prepared[3].content != second
    prepared_total = len(prepared[2].content) + len(prepared[3].content)
    assert prepared_total <= config.tool_result_budget_chars


def test_tool_result_budget_excludes_workspace_artifact_dir_from_git(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        tool_result_budget_chars=250,
        tool_result_preview_chars=16,
    )
    compactor, _, store = build_compactor(tmp_path, config)
    exclude_path = compactor.workspace_path / ".git" / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True)
    exclude_path.write_text("# local excludes\n", encoding="utf-8")
    large = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "x" * 600}}
    )
    messages = [
        AgentMessage(role="user", content="inspect"),
        AgentMessage(
            role="assistant",
            content="read file",
            tool_uses=[ToolUseRequest(id="large", name="read_file", input={"path": "large.py"})],
        ),
        AgentMessage(role="tool", content=large, tool_call_id="large"),
    ]
    store.append_many(messages)

    compactor.tool_result_budget(messages)

    assert ".nano-agent/" in exclude_path.read_text(encoding="utf-8")


def test_snip_compact_keeps_tool_protocol_boundaries(tmp_path: Path) -> None:
    config = AgentConfig(
        context_max_input_tokens=1_000,
        context_output_reserve_tokens=0,
        snip_compact_ratio=0.1,
        snip_keep_head=2,
        snip_keep_tail=2,
    )
    compactor, _, _ = build_compactor(tmp_path, config)
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        AgentMessage(role="assistant", content="old " * 100),
        AgentMessage(role="user", content="continue " * 100),
        *tool_exchange(
            "tool-1",
            json.dumps({"success": True, "summary": "read", "data": {"content": "result"}}),
        ),
        AgentMessage(role="assistant", content="done"),
    ]

    prepared = compactor.snip_compact(messages, [])

    tool_index = next(index for index, message in enumerate(prepared) if message.role == "tool")
    assert prepared[tool_index - 1].role == "assistant"
    assert prepared[tool_index - 1].tool_uses[0].id == prepared[tool_index].tool_call_id
    assert any("earlier messages removed" in message.content for message in prepared)


def test_snip_compact_ignores_message_count_below_token_threshold(tmp_path: Path) -> None:
    config = AgentConfig(
        context_max_input_tokens=10_000,
        context_output_reserve_tokens=0,
        snip_compact_ratio=0.9,
        snip_keep_head=2,
        snip_keep_tail=2,
    )
    compactor, _, _ = build_compactor(tmp_path, config)
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        *[AgentMessage(role="assistant", content=f"message-{index}") for index in range(100)],
    ]

    prepared = compactor.snip_compact(messages, [])

    assert prepared == messages


def test_micro_compact_only_replaces_old_large_tool_results(tmp_path: Path) -> None:
    config = AgentConfig(
        micro_keep_recent_tool_results=1,
        micro_tool_result_min_chars=100,
    )
    compactor, _, _ = build_compactor(tmp_path, config)
    old = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "x" * 300}}
    )
    recent = json.dumps(
        {"success": True, "summary": "read", "data": {"content": "y" * 300}}
    )
    messages = [
        AgentMessage(role="user", content="inspect"),
        *tool_exchange("old", old),
        *tool_exchange("recent", recent),
    ]

    prepared = compactor.micro_compact(messages)
    tool_messages = [message for message in prepared if message.role == "tool"]

    assert json.loads(tool_messages[0].content)["summary"] == MICRO_COMPACT_MESSAGE
    assert tool_messages[1].content == recent


def test_prepare_compacts_history_and_persists_transcript(tmp_path: Path) -> None:
    config = AgentConfig(
        context_max_input_tokens=1_000,
        context_output_reserve_tokens=0,
        context_auto_compact_ratio=0.1,
        snip_compact_ratio=1,
        micro_tool_result_min_chars=10_000,
        max_auto_compactions=1,
    )
    compactor, llm, store = build_compactor(tmp_path, config)
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        AgentMessage(role="assistant", content="analysis " * 100),
        AgentMessage(role="user", content="continue " * 100),
    ]
    store.append_many(messages)

    prepared = compactor.prepare(messages, [])

    assert llm.calls == 1
    assert compactor.summary_llm_call_count == 1
    assert llm.messages[0].role == "system"
    assert "compact continuation state" in llm.messages[0].content
    assert "Derived state:" in llm.messages[1].content
    assert prepared[0:2] == messages[0:2]
    assert "<conversation_summary>" in prepared[-1].content
    assert (store.path.parent / "context_checkpoint.json").exists()
    assert list((store.path.parent / "transcripts").glob("auto-*.jsonl"))
    record = json.loads(
        (store.path.parent / "compactions.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["compaction_type"] == "auto"
    assert record["success"] is True


def test_reactive_compact_keeps_prefix_and_recent_messages(tmp_path: Path) -> None:
    config = AgentConfig(reactive_keep_recent_messages=3)
    compactor, _, store = build_compactor(tmp_path, config)
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        *[AgentMessage(role="assistant", content=f"message-{index}") for index in range(10)],
    ]
    store.append_many(messages)

    outcome = compactor.reactive_compact(messages, [])
    prepared = outcome.messages

    assert prepared[0:2] == messages[0:2]
    assert "Reactive compact applied" in prepared[2].content
    assert [message.content for message in prepared[-3:]] == [
        "message-7",
        "message-8",
        "message-9",
    ]
    assert outcome.reduced
    assert outcome.after_estimated_tokens < outcome.before_estimated_tokens
    assert compactor.can_reactive_compact() is False
