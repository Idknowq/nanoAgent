"""Tests for MCP tool adapter and registration bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.mcp.client import MCPClient, MCPTransport
from nano_agent.mcp.protocol import (
    InitializeResult,
    ImplementationInfo,
    JsonRpcResponse,
    MCPTool,
    ServerCapabilities,
)
from nano_agent.mcp.tools import (
    MCPToolAdapter,
    build_mcp_context_messages,
    discover_and_register,
)
from nano_agent.tools.base import ToolContext, ToolRegistry


class FakeMCPTransport(MCPTransport):
    """Transport that returns scripted JSON-RPC responses."""

    def __init__(self, responses: list[bytes]):
        self.sent: list[bytes] = []
        self._responses = responses
        self._idx = 0

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    def receive(self) -> bytes:
        if self._idx >= len(self._responses):
            raise RuntimeError("No more responses")
        resp = self._responses[self._idx]
        self._idx += 1
        return resp

    def close(self) -> None:
        pass


def _init_response() -> bytes:
    return json.dumps(
        JsonRpcResponse(
            id=1,
            result=InitializeResult(
                protocol_version="2024-11-05",
                capabilities=ServerCapabilities(tools={}),
                server_info=ImplementationInfo(name="test", version="1.0"),
            ).model_dump(mode="json"),
        ).model_dump(mode="json")
    ).encode()


def _tools_list_response(id_val: int, tools: list[dict]) -> bytes:
    return json.dumps(
        JsonRpcResponse(id=id_val, result={"tools": tools}).model_dump(mode="json")
    ).encode()


def _tool_call_response(id_val: int, content: list[dict], is_error: bool = False) -> bytes:
    return json.dumps(
        JsonRpcResponse(
            id=id_val,
            result={"content": content, "is_error": is_error},
        ).model_dump(mode="json")
    ).encode()


class TestMCPToolAdapter:
    def test_adapter_forwards_call(self, tmp_path: Path):
        transport = FakeMCPTransport(
            [
                _init_response(),
                _tool_call_response(2, [{"type": "text", "text": "ok"}]),
            ]
        )
        client = MCPClient(transport)
        client.start()

        mcp_tool = MCPTool(
            name="search",
            description="Search docs",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        adapter = MCPToolAdapter(mcp_tool, client)
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )

        result = adapter.invoke({"q": "test"}, context)
        assert result.success
        assert "ok" in result.summary

    def test_adapter_handles_error(self, tmp_path: Path):
        transport = FakeMCPTransport(
            [
                _init_response(),
                _tool_call_response(2, [{"type": "text", "text": "not found"}], is_error=True),
            ]
        )
        client = MCPClient(transport)
        client.start()

        mcp_tool = MCPTool(name="bad", description="fails")
        adapter = MCPToolAdapter(mcp_tool, client)
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        result = adapter.invoke({}, context)
        assert not result.success
        assert result.error_code == "mcp_tool_returned_error"


def _resource_list_response(id_val: int, resources: list[dict]) -> bytes:
    return json.dumps(
        JsonRpcResponse(id=id_val, result={"resources": resources}).model_dump(
            mode="json"
        )
    ).encode()


def _prompt_list_response(id_val: int, prompts: list[dict]) -> bytes:
    return json.dumps(
        JsonRpcResponse(id=id_val, result={"prompts": prompts}).model_dump(mode="json")
    ).encode()


class TestBuildMCPContextMessages:
    def test_builds_resource_and_prompt_context(self):
        transport = FakeMCPTransport(
            [
                _init_response(),
                _resource_list_response(
                    2,
                    [{"uri": "file:///doc", "name": "docs", "description": "API docs"}],
                ),
                _prompt_list_response(
                    3,
                    [{"name": "review", "description": "Code review prompt"}],
                ),
            ]
        )
        client = MCPClient(transport)
        client.start()
        messages = build_mcp_context_messages(client)
        assert len(messages) == 1
        assert "API docs" in messages[0].content
        assert "Code review prompt" in messages[0].content

    def test_empty_resources_and_prompts(self):
        transport = FakeMCPTransport(
            [
                _init_response(),
                _resource_list_response(2, []),
                _prompt_list_response(3, []),
            ]
        )
        client = MCPClient(transport)
        client.start()
        messages = build_mcp_context_messages(client)
        assert messages == []

    def test_handles_errors_gracefully(self):
        """Should not crash if resource/prompt listing fails."""
        transport = FakeMCPTransport(
            [
                _init_response(),
                json.dumps(
                    JsonRpcResponse(
                        id=2,
                        error={"code": -32601, "message": "Method not found"},
                        result=None,
                    ).model_dump(mode="json")
                ).encode(),
                json.dumps(
                    JsonRpcResponse(
                        id=3,
                        error={"code": -32601, "message": "Method not found"},
                        result=None,
                    ).model_dump(mode="json")
                ).encode(),
            ]
        )
        client = MCPClient(transport)
        client.start()
        # The client raises on error, but build_mcp_context_messages catches
        messages = build_mcp_context_messages(client)
        assert messages == []


class TestDiscoverAndRegister:
    def test_registers_all_tools(self, tmp_path: Path):
        tools = [
            {"name": "tool_a", "description": "A", "input_schema": {}},
            {"name": "tool_b", "description": "B", "input_schema": {}},
        ]
        transport = FakeMCPTransport(
            [_init_response(), _tools_list_response(2, tools)]
        )
        client = MCPClient(transport)
        client.start()

        registry = ToolRegistry()
        adapters = discover_and_register(client, registry)

        assert len(adapters) == 2
        assert registry.get("tool_a") is not None
        assert registry.get("tool_b") is not None
        assert registry.get("tool_a").name == "tool_a"

    def test_empty_tools_list(self, tmp_path: Path):
        transport = FakeMCPTransport(
            [_init_response(), _tools_list_response(2, [])]
        )
        client = MCPClient(transport)
        client.start()

        registry = ToolRegistry()
        adapters = discover_and_register(client, registry)

        assert adapters == []

    def test_duplicate_tool_name_raises(self, tmp_path: Path):
        tools = [
            {"name": "dup", "description": "first", "input_schema": {}},
            {"name": "dup", "description": "second", "input_schema": {}},
        ]
        transport = FakeMCPTransport(
            [_init_response(), _tools_list_response(2, tools)]
        )
        client = MCPClient(transport)
        client.start()

        registry = ToolRegistry()
        with pytest.raises(ValueError, match="already registered"):
            discover_and_register(client, registry)
