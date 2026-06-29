from __future__ import annotations

import json
import sys
from pathlib import Path

from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig
from nano_agent.mcp.manager import MCPRuntimeManager
from nano_agent.mcp.models import MCPServerConfig
from nano_agent.models import LLMResponse, RunStatus, ToolUseRequest


def write_mock_mcp_server(tmp_path: Path) -> tuple[Path, Path]:
    """Write a mock MCP server that records shutdown by creating a marker file."""
    marker = tmp_path / "mcp_shutdown.txt"
    script = tmp_path / "mock_mcp_runtime_server.py"
    script.write_text(
        f"""
import json
import pathlib
import sys

initialized = False
marker = pathlib.Path({str(marker)!r})

def respond(request, result=None, error=None):
    payload = {{"jsonrpc": "2.0", "id": request["id"]}}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    print(json.dumps(payload), flush=True)

try:
    for line in sys.stdin:
        request = json.loads(line)
        method = request["method"]
        if "id" not in request:
            if method == "notifications/initialized":
                initialized = True
            continue
        if method == "initialize":
            respond(request, {{
                "protocolVersion": "2025-06-18",
                "capabilities": {{"tools": {{}}}},
                "serverInfo": {{"name": "mock", "version": "0.1.0"}},
            }})
        elif method == "tools/list" and initialized:
            respond(request, {{
                "tools": [{{
                    "name": "search_issues",
                    "description": "Search issues.",
                    "inputSchema": {{"type": "object", "properties": {{"query": {{"type": "string"}}}}}},
                }}]
            }})
        elif method == "tools/call" and initialized:
            query = request["params"]["arguments"]["query"]
            respond(request, {{
                "content": [{{"type": "text", "text": f"results for {{query}}"}}],
                "isError": False,
            }})
        else:
            respond(request, error={{"code": -32000, "message": "not initialized"}})
finally:
    marker.write_text("closed", encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script, marker


def make_server(script: Path, *, enabled: bool = True) -> MCPServerConfig:
    """Build a stdio config for the mock MCP server."""
    return MCPServerConfig(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
        enabled=enabled,
    )


class MCPCallingLLM:
    """Fake LLM that calls a discovered MCP tool and then finishes."""

    def __init__(self) -> None:
        self.calls = 0  # Number of LLM calls observed.
        self.seen_tool_names: list[list[str]] = []  # Tool names exposed per LLM call.

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.seen_tool_names.append([tool.name for tool in tools])
        if self.calls == 1:
            assert "mock__search_issues" in self.seen_tool_names[-1]
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="mcp-search",
                        name="mock__search_issues",
                        input={"query": "repo:owner/repo is:open"},
                    )
                ],
            )
        assert any(
            message.role == "tool" and "results for repo:owner/repo is:open" in message.content
            for message in messages
        )
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "MCP tool was called.",
                        "root_cause": "The runtime exposed an MCP tool.",
                        "resolution": "Called the mock MCP tool and received a result.",
                        "verification_summary": "Mock MCP tool returned expected output.",
                    },
                )
            ],
        )


class FinishWithoutMCPToolLLM:
    """Fake LLM that verifies MCP tools are absent and finishes."""

    def __init__(self) -> None:
        self.seen_tool_names: list[str] = []  # Tool names exposed to the LLM.

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        del messages
        self.seen_tool_names = [tool.name for tool in tools]
        assert "mock__search_issues" not in self.seen_tool_names
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "MCP is disabled.",
                        "root_cause": "The config did not enable MCP.",
                        "resolution": "Finished without MCP tools.",
                        "verification_summary": "No MCP tool was exposed.",
                    },
                )
            ],
        )


async def test_mcp_runtime_manager_skips_disabled_servers(tmp_path: Path) -> None:
    script, _ = write_mock_mcp_server(tmp_path)
    manager = MCPRuntimeManager((make_server(script, enabled=False),))

    await manager.start()
    try:
        assert manager.tool_registry().names() == set()
    finally:
        await manager.shutdown()


async def test_mcp_runtime_manager_registers_enabled_server_tools(tmp_path: Path) -> None:
    script, marker = write_mock_mcp_server(tmp_path)
    manager = MCPRuntimeManager((make_server(script),))

    await manager.start()
    try:
        assert manager.tool_registry().names() == {"mock__search_issues"}
    finally:
        await manager.shutdown()

    assert marker.read_text(encoding="utf-8") == "closed"


async def test_nano_agent_exposes_mcp_tool_when_enabled(tmp_path: Path) -> None:
    script, marker = write_mock_mcp_server(tmp_path)
    llm = MCPCallingLLM()
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        max_steps=5,
        mcp_enabled=True,
        mcp_servers=(make_server(script),),
        subagents_enabled=False,
    )
    agent = NanoAgent(config=config, llm=llm)

    result = await agent.run(
        repo_url="https://example.com/repo.git",
        user_request="Use MCP.",
    )

    assert result.status is RunStatus.COMPLETED
    assert llm.calls == 2
    assert marker.read_text(encoding="utf-8") == "closed"


async def test_nano_agent_does_not_start_mcp_when_disabled(tmp_path: Path) -> None:
    script, marker = write_mock_mcp_server(tmp_path)
    llm = FinishWithoutMCPToolLLM()
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        max_steps=1,
        mcp_enabled=False,
        mcp_servers=(make_server(script),),
        subagents_enabled=False,
    )
    agent = NanoAgent(config=config, llm=llm)

    result = await agent.run(
        repo_url="https://example.com/repo.git",
        user_request="Do not use MCP.",
    )

    assert result.status is RunStatus.COMPLETED
    assert "mock__search_issues" not in llm.seen_tool_names
    assert not marker.exists()
