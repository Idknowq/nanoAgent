"""MCP client with stdio and HTTP transport support.

Connects to MCP-compatible servers, performs the initialize handshake,
and provides typed convenience methods for tools/resources/prompts.
"""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from nano_agent.mcp.protocol import (
    GetPromptResult,
    InitializeParams,
    InitializeResult,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    MCPPrompt,
    MCPResource,
    MCPTool,
    ResourceContent,
    ToolCallParams,
    ToolCallResult,
)


class MCPTransportError(RuntimeError):
    """Raised when transport communication fails."""


class MCPProtocolError(RuntimeError):
    """Raised when the server returns a JSON-RPC error."""


class MCPTransport(ABC):
    """Abstract transport for MCP client-server communication."""

    def start(self) -> None:
        """Initialize transport resources. No-op by default; override if needed."""

    @abstractmethod
    def send(self, message: bytes) -> None:
        """Send a raw JSON-RPC message."""

    @abstractmethod
    def receive(self) -> bytes:
        """Receive a raw JSON-RPC message (blocking)."""

    @abstractmethod
    def close(self) -> None:
        """Clean up transport resources."""


class StdioTransport(MCPTransport):
    """Launch an MCP server as a subprocess, communicate over stdin/stdout.

    Messages are newline-delimited JSON on stdout; requests are written to stdin.
    """

    def __init__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        self._command = command
        self._process: subprocess.Popen[bytes] | None = None
        self._env = env

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
        )

    def send(self, message: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise MCPTransportError("Transport not started")
        try:
            self._process.stdin.write(message + b"\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPTransportError(f"Write failed: {exc}") from exc

    def receive(self) -> bytes:
        if self._process is None or self._process.stdout is None:
            raise MCPTransportError("Transport not started")
        line = self._process.stdout.readline()
        if not line:
            stderr_info = ""
            if self._process.stderr is not None:
                try:
                    remaining = self._process.stderr.read()
                    if remaining:
                        stderr_text = remaining.decode("utf-8", errors="replace")[-500:]
                        stderr_info = f" stderr: {stderr_text}"
                except OSError:
                    pass
            raise MCPTransportError(
                f"Server stdout closed unexpectedly.{stderr_info}"
            )
        return line.rstrip(b"\n")

    def close(self) -> None:
        if self._process is None:
            return
        try:
            self._process.stdin.close()
        except OSError:
            pass
        # Drain stdout to prevent pipe-buffer deadlock during wait.
        try:
            if self._process.stdout is not None:
                self._process.stdout.read()
        except OSError:
            pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self._process = None


class MCPClient:
    """MCP protocol client with typed convenience methods.

    Usage:
        transport = StdioTransport(["python", "-m", "my_mcp_server"])
        client = MCPClient(transport)
        client.start()
        tools = client.list_tools()
        result = client.call_tool("search", {"query": "..."})
        client.close()
    """

    def __init__(self, transport: MCPTransport) -> None:
        self._transport = transport
        self._request_id = 0
        self._server_capabilities: dict[str, Any] | None = None
        self._server_info: dict[str, str] | None = None
        self._initialized = False

    # ---- lifecycle ----

    def start(self) -> InitializeResult:
        """Start transport and perform MCP initialize handshake."""
        self._transport.start()
        return self._initialize()

    def close(self) -> None:
        self._transport.close()
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def server_capabilities(self) -> dict[str, Any] | None:
        return self._server_capabilities

    @property
    def server_info(self) -> dict[str, str] | None:
        return self._server_info

    # ---- tools ----

    def list_tools(self) -> list[MCPTool]:
        """Discover tools exposed by the MCP server."""
        result = self._request("tools/list")
        tools_raw = result.get("tools", [])
        return [MCPTool.model_validate(t) for t in tools_raw]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        """Call a tool on the MCP server and return the result."""
        params = ToolCallParams(name=name, arguments=arguments or {})
        raw = self._request("tools/call", params.model_dump(mode="json"))
        return ToolCallResult.model_validate(raw)

    # ---- resources ----

    def list_resources(self) -> list[MCPResource]:
        """Discover resources exposed by the MCP server."""
        result = self._request("resources/list")
        resources_raw = result.get("resources", [])
        return [MCPResource.model_validate(r) for r in resources_raw]

    def read_resource(self, uri: str) -> ResourceContent:
        """Read the content of an MCP resource."""
        raw = self._request("resources/read", {"uri": uri})
        contents = raw.get("contents", [{}])
        if not contents:
            raise MCPProtocolError(f"Resource '{uri}' returned no content")
        return ResourceContent.model_validate(contents[0])

    # ---- prompts ----

    def list_prompts(self) -> list[MCPPrompt]:
        """Discover prompt templates exposed by the MCP server."""
        result = self._request("prompts/list")
        prompts_raw = result.get("prompts", [])
        return [MCPPrompt.model_validate(p) for p in prompts_raw]

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        """Get a rendered prompt from the MCP server."""
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        raw = self._request("prompts/get", params)
        return GetPromptResult.model_validate(raw)

    # ---- internal ----

    def _initialize(self) -> InitializeResult:
        init_params = InitializeParams()
        raw = self._request("initialize", init_params.model_dump(mode="json"))
        result = InitializeResult.model_validate(raw)
        self._server_capabilities = result.capabilities.model_dump(mode="json")
        self._server_info = result.server_info.model_dump(mode="json")
        self._initialized = True
        # Send initialized notification
        self._notify("notifications/initialized")
        return result

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._request_id += 1
        request = JsonRpcRequest(id=self._request_id, method=method, params=params)
        raw_request = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        self._transport.send(raw_request.encode("utf-8"))
        # Receive, skipping server notifications (which have no id or a
        # different id) until we get the response matching our request.
        max_skipped = 10
        for _ in range(max_skipped + 1):
            raw_response = self._transport.receive()
            try:
                response = JsonRpcResponse.model_validate_json(raw_response)
            except Exception as exc:
                raise MCPProtocolError(f"Failed to parse response: {exc}") from exc
            # Skip notifications or mismatched responses
            if response.id is not None and response.id != self._request_id:
                continue
            if response.id is None:
                continue
            if response.error is not None:
                raise MCPProtocolError(
                    f"MCP error {response.error.code}: {response.error.message}"
                )
            return response.result
        raise MCPProtocolError(
            "Too many server notifications — response for request "
            f"#{self._request_id} not received"
        )

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        notification = JsonRpcNotification(method=method, params=params)
        raw = json.dumps(notification.model_dump(mode="json"), ensure_ascii=False)
        self._transport.send(raw.encode("utf-8"))
