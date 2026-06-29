from __future__ import annotations

from nano_agent.mcp.models import MCPServerConfig, MCPTransportType
from nano_agent.mcp.registry import build_mcp_tool_registry
from nano_agent.mcp.session import MCPClientSession
from nano_agent.mcp.transport import StdioMCPTransport
from nano_agent.tools.base import ToolRegistry


class MCPRuntimeManager:
    """Owns MCP server sessions and exposes discovered runtime tools."""

    def __init__(self, servers: tuple[MCPServerConfig, ...]) -> None:
        self._servers = servers  # Configured MCP servers for the current run.
        self._sessions: list[MCPClientSession] = []  # Sessions that must be shut down.
        self._tool_registry = ToolRegistry()  # Combined registry of discovered MCP tools.

    async def start(self) -> None:
        """Start enabled MCP servers and discover their tools."""
        for server in self._servers:
            if not server.enabled:
                continue
            session = self._build_session(server)
            self._sessions.append(session)
            await session.start()
            await session.initialize()
            definitions = await session.list_tools()
            server_registry = build_mcp_tool_registry(session, definitions)
            for tool in server_registry.tools():
                self._tool_registry.register(tool)

    async def shutdown(self) -> None:
        """Shutdown all started MCP sessions."""
        for session in reversed(self._sessions):
            await session.shutdown()
        self._sessions.clear()

    def tool_registry(self) -> ToolRegistry:
        """Return the combined MCP tool registry."""
        return self._tool_registry

    def _build_session(self, server: MCPServerConfig) -> MCPClientSession:
        """Create a client session for one MCP server config."""
        if server.transport is not MCPTransportType.STDIO:
            raise ValueError(f"Unsupported MCP transport: {server.transport}")
        return MCPClientSession(
            server=server,
            transport=StdioMCPTransport(server),
        )
