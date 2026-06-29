from __future__ import annotations

import sys
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.mcp import MCPClientSession, MCPServerConfig, StdioMCPTransport
from nano_agent.mcp.registry import build_mcp_tool_registry
from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import ToolContext


def write_mock_mcp_server(tmp_path: Path) -> Path:
    """Write a minimal MCP server script used for stdio integration tests."""
    script = tmp_path / "mock_mcp_integration_server.py"
    script.write_text(
        """
import json
import sys

initialized = False

def respond(request, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": request["id"]}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    print(json.dumps(payload), flush=True)

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if "id" not in request:
        if method == "notifications/initialized":
            initialized = True
        continue
    if method == "initialize":
        respond(request, {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-github", "version": "0.1.0"},
        })
    elif method == "tools/list":
        if not initialized:
            respond(request, error={"code": -32000, "message": "not initialized"})
            continue
        respond(request, {
            "tools": [{
                "name": "search_issues",
                "description": "Search issues.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }]
        })
    elif method == "tools/call":
        if not initialized:
            respond(request, error={"code": -32000, "message": "not initialized"})
            continue
        params = request["params"]
        if params["name"] != "search_issues":
            respond(request, error={"code": -32602, "message": "unknown tool"})
            continue
        query = params["arguments"]["query"]
        respond(request, {
            "content": [{"type": "text", "text": f"results for {query}"}],
            "isError": False,
        })
""".strip(),
        encoding="utf-8",
    )
    return script


def make_context(tmp_path: Path) -> ToolContext:
    """Create the minimal ToolContext needed to invoke an MCP adapter."""
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


async def test_mcp_stdio_tool_lifecycle_end_to_end(tmp_path: Path) -> None:
    script = write_mock_mcp_server(tmp_path)
    server = MCPServerConfig(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
    )
    session = MCPClientSession(
        server=server,
        transport=StdioMCPTransport(server, timeout_seconds=1.0),
    )

    await session.start()
    try:
        initialize_result = await session.initialize()
        definitions = await session.list_tools()
        registry = build_mcp_tool_registry(session, definitions)
        tool = registry.get("mock.search_issues")
        result = await tool.invoke({"query": "repo:owner/repo is:open"}, make_context(tmp_path))
    finally:
        await session.shutdown()

    assert initialize_result.server_info == {"name": "mock-github", "version": "0.1.0"}
    assert registry.names() == {"mock.search_issues"}
    assert result.success
    assert result.summary == "results for repo:owner/repo is:open"


async def test_mcp_integration_registry_specs(tmp_path: Path) -> None:
    script = write_mock_mcp_server(tmp_path)
    server = MCPServerConfig(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
    )
    session = MCPClientSession(
        server=server,
        transport=StdioMCPTransport(server, timeout_seconds=1.0),
    )

    await session.start()
    try:
        await session.initialize()
        registry = build_mcp_tool_registry(session, await session.list_tools())
    finally:
        await session.shutdown()

    spec = registry.specs()[0]
    assert spec.name == "mock.search_issues"
    assert spec.category == "mcp"
    assert spec.approval_level is ApprovalLevel.READ
    assert spec.can_run_concurrently
    assert spec.conflict_group == "mcp:mock"
