"""JSON-RPC 2.0 and MCP protocol types.

Implements the MCP (Model Context Protocol) specification wire format.
Ref: https://modelcontextprotocol.io
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JsonRpcVersion(StrEnum):
    V2 = "2.0"


# ---- JSON-RPC 2.0 ----

class JsonRpcRequest(BaseModel):
    jsonrpc: JsonRpcVersion = JsonRpcVersion.V2
    id: int | str
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any = None


class JsonRpcResponse(BaseModel):
    jsonrpc: JsonRpcVersion = JsonRpcVersion.V2
    id: int | str | None = None  # null id for notifications
    result: Any = None
    error: JsonRpcError | None = None

    @property
    def success(self) -> bool:
        return self.error is None


class JsonRpcNotification(BaseModel):
    jsonrpc: JsonRpcVersion = JsonRpcVersion.V2
    method: str
    params: dict[str, Any] | None = None


# ---- MCP Initialization ----

class ClientCapabilities(BaseModel):
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


class ServerCapabilities(BaseModel):
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


class InitializeParams(BaseModel):
    protocol_version: str = "2024-11-05"
    capabilities: ClientCapabilities = Field(default_factory=ClientCapabilities)
    client_info: dict[str, str] = Field(
        default_factory=lambda: {"name": "nanoAgent", "version": "0.1.0"}
    )


class ImplementationInfo(BaseModel):
    name: str
    version: str


class InitializeResult(BaseModel):
    protocol_version: str
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
    server_info: ImplementationInfo
    instructions: str | None = None


# ---- MCP Tools ----

class MCPTool(BaseModel):
    """MCP tool definition returned by tools/list."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCallParams(BaseModel):
    name: str
    arguments: dict[str, Any] | None = None


class ToolCallResult(BaseModel):
    content: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False


# ---- MCP Resources ----

class ResourceContent(BaseModel):
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None


class MCPResource(BaseModel):
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None


# ---- MCP Prompts ----

class MCPPrompt(BaseModel):
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] | None = None


class PromptMessage(BaseModel):
    role: str
    content: dict[str, Any] = Field(default_factory=dict)


class GetPromptResult(BaseModel):
    description: str = ""
    messages: list[PromptMessage] = Field(default_factory=list)


# ---- Error codes ----

class MCPErrorCode:
    """Standard JSON-RPC and MCP error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_NOT_INITIALIZED = -32002
    UNKNOWN_ERROR = -32001
