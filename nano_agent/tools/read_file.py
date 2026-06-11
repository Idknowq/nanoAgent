from __future__ import annotations

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)
from nano_agent.tools.errors import ToolExecutionError, ToolInputError
from nano_agent.tools.path_utils import (
    WorkspacePathError,
    resolve_workspace_path,
    workspace_relative_path,
)


class ReadFileInput(ToolInput):
    path: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1)


class ReadFileTool(RuntimeTool):
    """Read a bounded text segment from a file in the agent workspace."""

    name = "read_file"
    description = "Read part of a text file in the current agent workspace."
    approval_level = ApprovalLevel.READ
    category = "filesystem"
    requires_workspace = True
    input_model = ReadFileInput
    input_schema = ReadFileInput.model_json_schema()

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        try:
            path = resolve_workspace_path(
                context.workspace_path,
                input_data["path"],
                must_exist=True,
                allow_root=False,
            )
        except (WorkspacePathError, FileNotFoundError) as exc:
            raise ToolInputError(str(exc)) from exc

        if not path.is_file():
            raise ToolInputError(f"not a regular file: {input_data['path']}")

        offset = input_data["offset"]
        requested_limit = input_data["limit"]
        limit = min(requested_limit or context.config.max_file_bytes, context.config.max_file_bytes)

        try:
            with path.open("rb") as file:
                file.seek(offset)
                chunk = file.read(limit + 1)
        except OSError as exc:
            raise ToolExecutionError(f"failed to read file: {exc}") from exc

        truncated = len(chunk) > limit
        data = chunk[:limit]
        if b"\x00" in data:
            raise ToolInputError(f"binary file is not supported: {input_data['path']}")

        content = data.decode("utf-8", errors="replace")
        relative_path = workspace_relative_path(context.workspace_path, path)
        return ToolResult(
            success=True,
            summary=f"read {len(data)} bytes from {relative_path}",
            data={
                "path": relative_path,
                "content": content,
                "offset": offset,
                "bytes_read": len(data),
                "next_offset": offset + len(data),
                "truncated": truncated,
            },
        )


def _build_read_file_tool(context: ToolContext) -> ReadFileTool:
    return ReadFileTool()


register_tool_factory(ReadFileTool.name, _build_read_file_tool)
