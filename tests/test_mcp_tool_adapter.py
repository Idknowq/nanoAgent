from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.mcp import (
    MCPClientSession,
    MCPProtocolError,
    MCPServerConfig,
    MCPToolDefinition,
    StdioMCPTransport,
)
from nano_agent.mcp.tool_adapter import MCPToolAdapter
from nano_agent.tools.base import ToolContext


def write_mock_server(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "mock_mcp_tool_server.py"
    path.write_text(source, encoding="utf-8")
    return path


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


def make_session(script: Path) -> MCPClientSession:
    server = MCPServerConfig(
        name="github",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
    )
    transport = StdioMCPTransport(server, timeout_seconds=1.0)
    return MCPClientSession(server=server, transport=transport)


async def discover_tool(session: MCPClientSession) -> MCPToolDefinition:
    await session.initialize()
    return (await session.list_tools())[0]


async def test_mcp_tool_adapter_calls_remote_tool(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

initialized = False
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        if request["method"] == "notifications/initialized":
            initialized = True
        continue
    if request["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
    elif request["method"] == "tools/list" and initialized:
        result = {
            "tools": [{
                "name": "search_issues",
                "description": "Search issues.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }]
        }
    elif request["method"] == "tools/call":
        result = {
            "content": [{
                "type": "text",
                "text": f"called {request['params']['name']} with {request['params']['arguments']['query']}",
            }],
            "isError": False,
            "seenName": request["params"]["name"],
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        definition = await discover_tool(session)
        tool = MCPToolAdapter(session, definition)
        result = await tool.invoke({"query": "repo:owner/repo is:open"}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert tool.name == "github__search_issues"
    assert tool.description == "Search issues."
    assert tool.input_schema == {"type": "object", "properties": {"query": {"type": "string"}}}
    assert result.success
    assert result.summary == "called search_issues with repo:owner/repo is:open"
    assert result.data["raw"]["seenName"] == "search_issues"


async def test_mcp_tool_adapter_summarizes_json_text_result(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
    elif request["method"] == "tools/list":
        result = {"tools": [{"name": "search_repositories", "inputSchema": {}}]}
    elif request["method"] == "tools/call":
        payload = {"total_count": 3146, "items": [{"name": "github-mcp-server"}]}
        result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        definition = await discover_tool(session)
        result = await MCPToolAdapter(session, definition).invoke({}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert result.success
    assert result.summary == "MCP tool returned JSON object with total_count=3146 and 1 item(s)"
    assert result.data["content"][0]["text"].startswith('{"total_count":')


async def test_mcp_tool_adapter_converts_tool_error_result(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
    elif request["method"] == "tools/list":
        result = {"tools": [{"name": "search_issues", "inputSchema": {}}]}
    elif request["method"] == "tools/call":
        result = {"content": [{"type": "text", "text": "remote tool failed"}], "isError": True}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        definition = await discover_tool(session)
        result = await MCPToolAdapter(session, definition).invoke({}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert not result.success
    assert result.error_code == "mcp_tool_error"
    assert result.error_message == "remote tool failed"


async def test_mcp_tool_adapter_converts_json_rpc_error(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    elif request["method"] == "tools/list":
        result = {"tools": [{"name": "search_issues", "inputSchema": {}}]}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    elif request["method"] == "tools/call":
        error = {"code": -32000, "message": "remote unavailable"}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": error}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        definition = await discover_tool(session)
        result = await MCPToolAdapter(session, definition).invoke({}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert not result.success
    assert result.error_code == "mcp_remote_error"
    assert "remote unavailable" in result.error_message


async def test_session_rejects_call_before_initialize(tmp_path: Path) -> None:
    script = write_mock_server(tmp_path, "import sys\nfor line in sys.stdin:\n    pass")
    session = make_session(script)
    definition = MCPToolDefinition(
        server_name="github",
        remote_name="search_issues",
        tool_name="github__search_issues",
    )

    await session.start()
    try:
        result = await MCPToolAdapter(session, definition).invoke({}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert not result.success
    assert result.error_code == "mcp_session_error"


async def test_session_rejects_tool_from_other_namespace(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)
    definition = MCPToolDefinition(
        server_name="linear",
        remote_name="search_issues",
        tool_name="linear__search_issues",
    )

    await session.start()
    try:
        await session.initialize()
        with pytest.raises(MCPProtocolError, match="different server namespace"):
            await session.call_tool(definition, {})
    finally:
        await session.shutdown()
