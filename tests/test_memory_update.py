"""Tests for memory_update tool."""

from __future__ import annotations

from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.memory.store import JsonlMemoryStore, MemoryRecord
from nano_agent.tools.base import ToolContext
from nano_agent.tools.memory_update import MemoryUpdateInput, MemoryUpdateTool


def test_memory_update_add(tmp_path: Path):
    memory_file = tmp_path / "memory.jsonl"
    config = AgentConfig(memory_path=memory_file)
    context = ToolContext(
        run_id="test",
        repo_url="https://github.com/test/repo",
        workspace_path=tmp_path,
        run_dir=tmp_path,
        config=config,
    )
    tool = MemoryUpdateTool()
    result = tool.invoke(
        {
            "action": "add",
            "namespace": "test_ns",
            "key": "k1",
            "value": "hello world",
            "tags": ["test"],
        },
        context,
    )
    assert result.success
    # Verify persisted
    store = JsonlMemoryStore(memory_file)
    records = store.search("test_ns")
    assert len(records) == 1
    assert records[0].value == "hello world"


def test_memory_update_upsert(tmp_path: Path):
    memory_file = tmp_path / "memory.jsonl"
    # Pre-populate
    store = JsonlMemoryStore(memory_file)
    store.add(MemoryRecord(namespace="ns", key="k1", value="old"))

    config = AgentConfig(memory_path=memory_file)
    context = ToolContext(
        run_id="test",
        repo_url="https://github.com/test/repo",
        workspace_path=tmp_path,
        run_dir=tmp_path,
        config=config,
    )
    tool = MemoryUpdateTool()
    result = tool.invoke(
        {"action": "upsert", "namespace": "ns", "key": "k1", "value": "new"},
        context,
    )
    assert result.success
    records = store.search("ns")
    assert len(records) == 1
    assert records[0].value == "new"


def test_memory_update_no_path(tmp_path: Path):
    config = AgentConfig(memory_path=None)
    context = ToolContext(
        run_id="test",
        repo_url="https://github.com/test/repo",
        workspace_path=tmp_path,
        run_dir=tmp_path,
        config=config,
    )
    tool = MemoryUpdateTool()
    result = tool.invoke(
        {"action": "add", "namespace": "x", "key": "y", "value": "z"},
        context,
    )
    assert not result.success
    assert result.error_code == "no_memory_path"


def test_memory_update_input_validation():
    parsed = MemoryUpdateInput(
        action="add", namespace="ns", key="k", value="v", tags=["a"]
    )
    assert parsed.namespace == "ns"
    assert parsed.tags == ["a"]


def test_upsert_new_record(tmp_path: Path):
    """upsert on a non-existing key should create it."""
    memory_file = tmp_path / "memory.jsonl"
    config = AgentConfig(memory_path=memory_file)
    context = ToolContext(
        run_id="test",
        repo_url="https://github.com/test/repo",
        workspace_path=tmp_path,
        run_dir=tmp_path,
        config=config,
    )
    tool = MemoryUpdateTool()
    result = tool.invoke(
        {"action": "upsert", "namespace": "ns", "key": "new_key", "value": "created"},
        context,
    )
    assert result.success
    store = JsonlMemoryStore(memory_file)
    records = store.search("ns")
    assert len(records) == 1
    assert records[0].value == "created"
