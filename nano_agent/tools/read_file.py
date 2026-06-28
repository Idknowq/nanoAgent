from __future__ import annotations

from pydantic import Field, model_validator

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
    path: str = Field(min_length=1)  # 需要读取的工作区相对文件路径。
    offset: int | None = Field(default=None, ge=0)  # 字节模式的起始偏移。
    limit: int | None = Field(default=None, ge=1)  # 字节模式的最大读取字节数。
    line_start: int | None = Field(default=None, ge=1)  # 行模式的起始行号，包含该行。
    line_end: int | None = Field(default=None, ge=1)  # 行模式的结束行号，包含该行。

    @model_validator(mode="after")
    def validate_read_mode(self) -> ReadFileInput:
        uses_byte_mode = self.offset is not None or self.limit is not None
        uses_line_mode = self.line_start is not None or self.line_end is not None
        if uses_byte_mode and uses_line_mode:
            raise ValueError(
                "offset/limit and line_start/line_end are mutually exclusive"
            )
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_start is required when line_end is provided")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ReadFileTool(RuntimeTool):
    """Read a bounded text segment from a file in the agent workspace."""

    name = "read_file"
    description = (
        "Read a bounded part of a workspace text file. Use line_start and line_end for an "
        "inclusive line range instead of run_command with sed, head, or cat. Alternatively, "
        "use offset and limit for byte-based paging or a byte_offset returned by grep. The "
        "line and byte modes are mutually exclusive."
    )
    approval_level = ApprovalLevel.READ
    category = "filesystem"
    requires_workspace = True
    input_model = ReadFileInput
    input_schema = ReadFileInput.model_json_schema()

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
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

        if input_data["line_start"] is not None:
            data, result_data = self._read_lines(
                path,
                input_data["line_start"],
                input_data["line_end"],
                context.config.max_file_bytes,
            )
        else:
            data, result_data = self._read_bytes(
                path,
                input_data["offset"] or 0,
                input_data["limit"],
                context.config.max_file_bytes,
            )
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
                "bytes_read": len(data),
                **result_data,
            },
        )

    @staticmethod
    def _read_bytes(
        path,
        offset: int,
        requested_limit: int | None,
        max_file_bytes: int,
    ) -> tuple[bytes, dict]:
        limit = min(requested_limit or max_file_bytes, max_file_bytes)
        try:
            with path.open("rb") as file:
                file.seek(offset)
                chunk = file.read(limit + 1)
        except OSError as exc:
            raise ToolExecutionError(f"failed to read file: {exc}") from exc

        data = chunk[:limit]
        return data, {
            "offset": offset,
            "next_offset": offset + len(data),
            "truncated": len(chunk) > limit,
        }

    @staticmethod
    def _read_lines(
        path,
        line_start: int,
        line_end: int | None,
        max_file_bytes: int,
    ) -> tuple[bytes, dict]:
        selected: list[bytes] = []
        bytes_read = 0
        last_line = line_start - 1
        truncated = False
        try:
            with path.open("rb") as file:
                for line_number, line in enumerate(file, start=1):
                    if line_number < line_start:
                        continue
                    if line_end is not None and line_number > line_end:
                        break
                    if bytes_read + len(line) > max_file_bytes:
                        remaining = max_file_bytes - bytes_read
                        if remaining:
                            selected.append(line[:remaining])
                            bytes_read += remaining
                        truncated = True
                        break
                    selected.append(line)
                    bytes_read += len(line)
                    last_line = line_number
        except OSError as exc:
            raise ToolExecutionError(f"failed to read file: {exc}") from exc

        return b"".join(selected), {
            "line_start": line_start,
            "line_end": last_line,
            "next_line": last_line + 1 if truncated else None,
            "truncated": truncated,
        }


def _build_read_file_tool(context: ToolContext) -> ReadFileTool:
    return ReadFileTool()


register_tool_factory(ReadFileTool.name, _build_read_file_tool)
