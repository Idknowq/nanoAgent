from __future__ import annotations

from nano_agent.mcp.models import MCPToolDefinition
from nano_agent.mcp.session import MCPClientSession
from nano_agent.mcp.tool_adapter import MCPToolAdapter
from nano_agent.tools.base import ToolRegistry


def build_mcp_tool_registry(
    session: MCPClientSession,
    definitions: list[MCPToolDefinition],
) -> ToolRegistry:
    """Build a ToolRegistry from discovered MCP tool definitions."""
    return ToolRegistry([MCPToolAdapter(session, definition) for definition in definitions])
