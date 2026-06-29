from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class JSONRPCError(BaseModel):
    """JSON-RPC error object returned by an MCP server."""

    code: int  # Stable JSON-RPC error code.
    message: str  # Human-readable error message.
    data: Any = None  # Optional structured error details.


class JSONRPCRequest(BaseModel):
    """Single JSON-RPC request sent to an MCP server."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"  # JSON-RPC protocol version.
    id: int  # Request id used to match the response.
    method: str  # Remote method name.
    params: dict[str, Any] | None = None  # Optional method arguments.


class JSONRPCNotification(BaseModel):
    """Single JSON-RPC notification sent to an MCP server."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"  # JSON-RPC protocol version.
    method: str  # Remote notification method name.
    params: dict[str, Any] | None = None  # Optional notification arguments.


class JSONRPCResponse(BaseModel):
    """Single JSON-RPC response received from an MCP server."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"  # JSON-RPC protocol version.
    id: int  # Request id echoed by the server.
    result: dict[str, Any] | None = None  # Successful response payload.
    error: JSONRPCError | None = None  # Error response payload.

    @model_validator(mode="after")
    def validate_result_or_error(self) -> JSONRPCResponse:
        """Ensure a response contains exactly one of result or error."""
        if (self.result is None) == (self.error is None):
            raise ValueError("JSON-RPC response requires exactly one of result or error")
        return self
