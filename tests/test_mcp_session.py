from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nano_agent.mcp import (
    MCPClientSession,
    MCPProtocolError,
    MCPRemoteError,
    MCPServerConfig,
    MCPSessionNotInitializedError,
    StdioMCPTransport,
)


def write_mock_server(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "mock_mcp_session_server.py"
    path.write_text(source, encoding="utf-8")
    return path


def make_session(script: Path) -> MCPClientSession:
    server = MCPServerConfig(
        name="github",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
    )
    transport = StdioMCPTransport(server, timeout_seconds=1.0)
    return MCPClientSession(server=server, transport=transport)


async def test_session_initializes_and_lists_namespaced_tools(tmp_path: Path) -> None:
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
        result = {
            "protocolVersion": request["params"]["protocolVersion"],
            "serverInfo": {"name": "mock", "version": "0.1.0"},
            "capabilities": {"tools": {}},
        }
    elif request["method"] == "tools/list" and initialized:
        result = {
            "tools": [
                {
                    "name": "search_issues",
                    "description": "Search issues.",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        }
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32000, "message": "not initialized"},
        }), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        initialize_result = await session.initialize()
        tools = await session.list_tools()
    finally:
        await session.shutdown()

    assert initialize_result.protocol_version == "2025-06-18"
    assert initialize_result.server_info == {"name": "mock", "version": "0.1.0"}
    assert tools[0].server_name == "github"
    assert tools[0].remote_name == "search_issues"
    assert tools[0].tool_name == "github__search_issues"
    assert tools[0].description == "Search issues."
    assert tools[0].input_schema == {"type": "object", "properties": {}}


async def test_session_requires_initialize_before_list_tools(tmp_path: Path) -> None:
    script = write_mock_server(tmp_path, "import sys\nfor line in sys.stdin:\n    pass")
    session = make_session(script)

    await session.start()
    try:
        with pytest.raises(MCPSessionNotInitializedError):
            await session.list_tools()
    finally:
        await session.shutdown()


async def test_session_converts_remote_errors(tmp_path: Path) -> None:
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
    else:
        error = {"code": -32000, "message": "tools unavailable"}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": error}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        await session.initialize()
        with pytest.raises(MCPRemoteError, match="tools unavailable"):
            await session.list_tools()
    finally:
        await session.shutdown()


async def test_session_rejects_invalid_tool_name(tmp_path: Path) -> None:
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
    else:
        result = {"tools": [{"name": "issues.search", "inputSchema": {}}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        await session.initialize()
        with pytest.raises(MCPProtocolError, match="namespace-safe"):
            await session.list_tools()
    finally:
        await session.shutdown()


async def test_session_uses_incrementing_request_ids(tmp_path: Path) -> None:
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
    else:
        result = {"tools": [{"name": "search_issues", "inputSchema": {}}]}
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": result | {"requestId": request["id"]},
    }), flush=True)
""".strip(),
    )
    session = make_session(script)

    await session.start()
    try:
        initialize_result = await session.initialize()
        tools = await session.list_tools()
    finally:
        await session.shutdown()

    assert initialize_result.raw["requestId"] == 1
    assert tools[0].tool_name == "github__search_issues"
