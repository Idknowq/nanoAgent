from __future__ import annotations

import json
from typing import Any

from nano_agent.mcp.models import MCPToolCallResult, MCPToolDefinition
from nano_agent.mcp.session import MCPClientSession, MCPRemoteError, MCPSessionError
from nano_agent.mcp.transport import MCPProtocolError, MCPTransportError
from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class MCPToolAdapter(RuntimeTool):
    """RuntimeTool wrapper around one discovered MCP tool."""

    def __init__(self, session: MCPClientSession, definition: MCPToolDefinition) -> None:
        self._session = session  # Session used to call the remote MCP tool.
        self._definition = definition  # Discovered MCP tool metadata.
        self.name = definition.tool_name
        self.description = definition.description or f"MCP tool {definition.tool_name}"
        self.input_schema = definition.input_schema
        self.category = "mcp"
        self.approval_level = ApprovalLevel.READ
        self.enabled = True
        self.requires_workspace = False
        self.is_mutating = False
        self.can_run_concurrently = True
        self.conflict_group = f"mcp:{definition.server_name}"
        self.requires_exclusive_execution = False

    async def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        """Call the remote MCP tool and convert its result to ToolResult."""
        try:
            result = await self._session.call_tool(self._definition, input_data)
        except MCPRemoteError as exc:
            return ToolResult.failure(code="mcp_remote_error", message=str(exc))
        except MCPSessionError as exc:
            return ToolResult.failure(code="mcp_session_error", message=str(exc))
        except MCPProtocolError as exc:
            return ToolResult.failure(code="mcp_protocol_error", message=str(exc))
        except MCPTransportError as exc:
            return ToolResult.failure(code="mcp_transport_error", message=str(exc))

        summary = _summarize_tool_call_result(result)
        data = {"content": result.content, "raw": result.raw}
        if result.is_error:
            return ToolResult.failure(
                code="mcp_tool_error",
                message=summary,
                data=data,
            )
        return ToolResult(success=True, summary=summary, data=data)


def _summarize_tool_call_result(result: MCPToolCallResult) -> str:
    """Build a short summary from MCP text content blocks."""
    text_parts: list[str] = []
    for item in result.content:
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])
    summary = "\n".join(text_parts).strip()
    if not summary:
        return "MCP tool completed"
    json_summary = _summarize_json_text(summary)
    if json_summary is not None:
        return json_summary
    if len(summary) > 500:
        return summary[:497] + "..."
    return summary


def _summarize_json_text(text: str) -> str | None:
    """Return a compact summary for JSON text content."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        return _summarize_json_object(value)
    if isinstance(value, list):
        return f"MCP tool returned JSON array with {len(value)} item(s)"
    return f"MCP tool returned JSON {type(value).__name__}"


def _summarize_json_object(value: dict[str, Any]) -> str:
    """Return a compact summary for a JSON object."""
    if isinstance(value.get("items"), list) and isinstance(value.get("total_count"), int):
        return (
            "MCP tool returned JSON object "
            f"with total_count={value['total_count']} and {len(value['items'])} item(s)"
        )
    keys = list(value)[:5]
    key_text = ", ".join(keys)
    if len(value) > len(keys):
        key_text += ", ..."
    return f"MCP tool returned JSON object with keys: {key_text}"
