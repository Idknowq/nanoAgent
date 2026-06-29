from __future__ import annotations

from typing import Any

from nano_agent.mcp.jsonrpc import JSONRPCNotification, JSONRPCRequest, JSONRPCResponse
from nano_agent.mcp.models import MCPInitializeResult, MCPServerConfig, MCPToolDefinition
from nano_agent.mcp.transport import MCPProtocolError, StdioMCPTransport


MCP_PROTOCOL_VERSION = "2025-06-18"


class MCPSessionError(Exception):
    """Base error for MCP client session failures."""


class MCPSessionNotInitializedError(MCPSessionError):
    """Raised when an operation requires a completed initialize call."""


class MCPRemoteError(MCPSessionError):
    """Raised when the MCP server returns a JSON-RPC error."""


class MCPClientSession:
    """Client session for MCP initialize and tool discovery."""

    def __init__(self, server: MCPServerConfig, transport: StdioMCPTransport) -> None:
        self._server = server  # MCP server configuration and namespace.
        self._transport = transport  # Transport used for JSON-RPC requests.
        self._next_request_id = 1  # Monotonic JSON-RPC request id.
        self._initialized = False  # Whether initialize has completed successfully.
        self._initialize_result: MCPInitializeResult | None = None  # Last initialize result.

    async def start(self) -> None:
        """Start the underlying MCP transport."""
        await self._transport.start()

    async def initialize(self) -> MCPInitializeResult:
        """Initialize the MCP session and store negotiated server metadata."""
        response = await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "nanoAgent",
                    "version": "0.1.0",
                },
            },
        )
        result = self._require_result(response, "initialize")
        initialize_result = self._parse_initialize_result(result)
        await self._transport.notify(JSONRPCNotification(method="notifications/initialized"))
        self._initialize_result = initialize_result
        self._initialized = True
        return initialize_result

    async def list_tools(self) -> list[MCPToolDefinition]:
        """Return tools exposed by the initialized MCP server."""
        if not self._initialized:
            raise MCPSessionNotInitializedError("MCP session must be initialized before tools/list")
        response = await self._request("tools/list", None)
        result = self._require_result(response, "tools/list")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise MCPProtocolError("MCP tools/list result requires tools list")
        return [self._parse_tool(tool) for tool in tools]

    async def shutdown(self) -> None:
        """Shutdown the underlying transport."""
        await self._transport.shutdown()

    @property
    def initialize_result(self) -> MCPInitializeResult | None:
        """Return the stored initialize result, if initialization has completed."""
        return self._initialize_result

    async def _request(self, method: str, params: dict[str, Any] | None) -> JSONRPCResponse:
        """Send one JSON-RPC request through the transport."""
        request = JSONRPCRequest(id=self._next_request_id, method=method, params=params)
        self._next_request_id += 1
        return await self._transport.request(request)

    def _require_result(self, response: JSONRPCResponse, method: str) -> dict[str, Any]:
        """Return a successful response result or convert remote errors."""
        if response.error is not None:
            raise MCPRemoteError(f"MCP server returned error for {method}: {response.error.message}")
        if response.result is None:
            raise MCPProtocolError(f"MCP server returned no result for {method}")
        return response.result

    def _parse_initialize_result(self, result: dict[str, Any]) -> MCPInitializeResult:
        """Parse an MCP initialize result."""
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise MCPProtocolError("MCP initialize result requires protocolVersion")
        capabilities = result.get("capabilities", {})
        server_info = result.get("serverInfo", {})
        if not isinstance(capabilities, dict):
            raise MCPProtocolError("MCP initialize capabilities must be an object")
        if not isinstance(server_info, dict):
            raise MCPProtocolError("MCP initialize serverInfo must be an object")
        return MCPInitializeResult(
            protocol_version=protocol_version,
            capabilities=capabilities,
            server_info=server_info,
            raw=result,
        )

    def _parse_tool(self, raw_tool: Any) -> MCPToolDefinition:
        """Parse one MCP tools/list entry into a namespaced definition."""
        if not isinstance(raw_tool, dict):
            raise MCPProtocolError("MCP tool entry must be an object")
        remote_name = raw_tool.get("name")
        if not isinstance(remote_name, str) or not remote_name:
            raise MCPProtocolError("MCP tool entry requires name")
        description = raw_tool.get("description", "")
        if not isinstance(description, str):
            raise MCPProtocolError("MCP tool description must be a string")
        input_schema = raw_tool.get("inputSchema", {})
        if not isinstance(input_schema, dict):
            raise MCPProtocolError("MCP tool inputSchema must be an object")
        try:
            return MCPToolDefinition(
                server_name=self._server.name,
                remote_name=remote_name,
                tool_name=f"{self._server.name}.{remote_name}",
                description=description,
                input_schema=input_schema,
            )
        except ValueError as exc:
            raise MCPProtocolError("MCP tool name is not namespace-safe") from exc
