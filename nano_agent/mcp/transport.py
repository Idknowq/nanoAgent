from __future__ import annotations

import asyncio
import json
import os

from pydantic import ValidationError

from nano_agent.mcp.jsonrpc import JSONRPCNotification, JSONRPCRequest, JSONRPCResponse
from nano_agent.mcp.models import MCPServerConfig, MCPTransportType


class MCPTransportError(Exception):
    """Base error for MCP transport failures."""


class MCPTransportNotStartedError(MCPTransportError):
    """Raised when a request is attempted before the transport starts."""


class MCPTransportTimeoutError(MCPTransportError):
    """Raised when a transport operation exceeds its timeout."""


class MCPTransportClosedError(MCPTransportError):
    """Raised when the subprocess closes before returning a response."""


class MCPProtocolError(MCPTransportError):
    """Raised when the server returns invalid JSON-RPC data."""


class StdioMCPTransport:
    """Async stdio transport for a local MCP server subprocess."""

    def __init__(self, config: MCPServerConfig, timeout_seconds: float = 30.0) -> None:
        if config.transport is not MCPTransportType.STDIO:
            raise ValueError("StdioMCPTransport requires stdio MCP server config")
        self._config = config  # Server process configuration.
        self._timeout_seconds = timeout_seconds  # Default timeout for I/O operations.
        self._process: asyncio.subprocess.Process | None = None  # Active server subprocess.

    async def start(self) -> None:
        """Start the configured MCP server subprocess."""
        if self._process is not None:
            return
        if self._config.command is None:
            raise ValueError("stdio MCP server requires command")
        env = os.environ.copy()
        env.update(self._config.env)
        self._process = await asyncio.create_subprocess_exec(
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Send one JSON-RPC request and wait for its matching response."""
        process = self._require_process()
        if process.stdin is None or process.stdout is None:
            raise MCPTransportClosedError("stdio MCP server pipes are unavailable")

        payload = request.model_dump(exclude_none=True)
        line = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            process.stdin.write(line)
            await asyncio.wait_for(process.stdin.drain(), timeout=self._timeout_seconds)
            response_line = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise MCPTransportTimeoutError("timed out waiting for MCP stdio response") from exc
        except BrokenPipeError as exc:
            raise MCPTransportClosedError("stdio MCP server stdin closed") from exc

        if not response_line:
            raise MCPTransportClosedError("stdio MCP server exited without a response")

        response = self._parse_response(response_line)
        if response.id != request.id:
            raise MCPProtocolError(
                f"JSON-RPC response id {response.id} did not match request id {request.id}"
            )
        return response

    async def notify(self, notification: JSONRPCNotification) -> None:
        """Send one JSON-RPC notification without waiting for a response."""
        process = self._require_process()
        if process.stdin is None:
            raise MCPTransportClosedError("stdio MCP server stdin is unavailable")

        payload = notification.model_dump(exclude_none=True)
        line = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            process.stdin.write(line)
            await asyncio.wait_for(process.stdin.drain(), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            raise MCPTransportTimeoutError("timed out sending MCP stdio notification") from exc
        except BrokenPipeError as exc:
            raise MCPTransportClosedError("stdio MCP server stdin closed") from exc

    async def shutdown(self) -> None:
        """Close the subprocess and tolerate repeated shutdown calls."""
        process = self._process
        if process is None:
            return
        self._process = None

        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            await process.stdin.wait_closed()

        try:
            await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)
            return
        except TimeoutError:
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=self._timeout_seconds)
            return
        except TimeoutError:
            process.kill()
            await process.wait()

    def _require_process(self) -> asyncio.subprocess.Process:
        """Return the active process or fail if the transport is not started."""
        if self._process is None:
            raise MCPTransportNotStartedError("stdio MCP transport is not started")
        if self._process.returncode is not None:
            raise MCPTransportClosedError("stdio MCP server is no longer running")
        return self._process

    def _parse_response(self, line: bytes) -> JSONRPCResponse:
        """Parse one stdout line into a JSON-RPC response."""
        try:
            raw = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPProtocolError("stdio MCP server returned invalid JSON") from exc
        try:
            return JSONRPCResponse.model_validate(raw)
        except ValidationError as exc:
            raise MCPProtocolError("stdio MCP server returned invalid JSON-RPC response") from exc
