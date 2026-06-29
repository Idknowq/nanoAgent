from __future__ import annotations

import os
import shutil

import pytest
from dotenv import load_dotenv

from nano_agent.mcp import MCPClientSession, StdioMCPTransport
from nano_agent.mcp.github import GITHUB_TOKEN_ENV, build_github_mcp_stdio_config
from nano_agent.mcp.registry import build_mcp_tool_registry


load_dotenv()

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GITHUB_MCP_SMOKE") != "1",
    reason="set RUN_GITHUB_MCP_SMOKE=1 to run GitHub MCP smoke tests",
)


@pytest.mark.skipif(not os.environ.get(GITHUB_TOKEN_ENV), reason=f"{GITHUB_TOKEN_ENV} is not set")
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
async def test_github_mcp_stdio_lists_read_only_tools() -> None:
    config = build_github_mcp_stdio_config()
    session = MCPClientSession(
        server=config,
        transport=StdioMCPTransport(config, timeout_seconds=60.0),
    )

    await session.start()
    try:
        await session.initialize()
        definitions = await session.list_tools()
        registry = build_mcp_tool_registry(session, definitions)
    finally:
        await session.shutdown()

    assert definitions
    assert all(definition.tool_name.startswith("github__") for definition in definitions)
    assert registry.names()
