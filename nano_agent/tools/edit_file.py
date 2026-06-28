from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from pydantic import ConfigDict, Field, field_validator

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
    reject_git_internal_path,
    resolve_workspace_path,
    workspace_relative_path,
)


class EditFileInput(ToolInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(min_length=1)
    old_text: str = Field(min_length=1)
    new_text: str
    expected_replacements: int = Field(default=1, ge=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path cannot be empty")
        return value


class EditFileTool(RuntimeTool):
    """Apply an exact text replacement to one workspace file."""

    name = "edit_file"
    description = "Replace exact text in an existing UTF-8 file in the agent workspace."
    approval_level = ApprovalLevel.WRITE
    category = "filesystem"
    requires_workspace = True
    is_mutating = True
    input_model = EditFileInput
    input_schema = EditFileInput.model_json_schema()

    def audit_input(self, input_data: dict) -> dict:
        old_text = input_data.get("old_text")
        new_text = input_data.get("new_text")
        return {
            "path": input_data.get("path"),
            "old_text_chars": len(old_text) if isinstance(old_text, str) else None,
            "new_text_chars": len(new_text) if isinstance(new_text, str) else None,
            "expected_replacements": input_data.get("expected_replacements", 1),
        }

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        try:
            path = resolve_workspace_path(
                context.workspace_path,
                input_data["path"],
                must_exist=True,
                allow_root=False,
            )
            reject_git_internal_path(context.workspace_path, path)
        except (WorkspacePathError, FileNotFoundError) as exc:
            raise ToolInputError(str(exc)) from exc

        if not path.is_file():
            raise ToolInputError(f"not a regular file: {input_data['path']}")

        try:
            file_stat = path.stat()
        except OSError as exc:
            raise ToolExecutionError(f"failed to inspect file: {exc}") from exc
        if file_stat.st_size > context.config.max_file_bytes:
            raise ToolInputError(
                f"file exceeds max_file_bytes={context.config.max_file_bytes}"
            )

        try:
            with path.open("rb") as file:
                data = file.read(context.config.max_file_bytes + 1)
        except OSError as exc:
            raise ToolExecutionError(f"failed to read file: {exc}") from exc
        if len(data) > context.config.max_file_bytes:
            raise ToolInputError(
                f"file exceeds max_file_bytes={context.config.max_file_bytes}"
            )
        if b"\x00" in data:
            raise ToolInputError(f"binary file is not supported: {input_data['path']}")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolInputError(f"file is not valid UTF-8: {input_data['path']}") from exc

        old_text = input_data["old_text"]
        new_text = input_data["new_text"]
        if old_text == new_text:
            raise ToolInputError("old_text and new_text must differ")

        expected = input_data["expected_replacements"]
        actual = content.count(old_text)
        if actual != expected:
            raise ToolInputError(f"expected {expected} matches, found {actual}")

        updated = content.replace(old_text, new_text, expected)
        updated_data = updated.encode("utf-8")
        if len(updated_data) > context.config.max_file_bytes:
            raise ToolInputError(
                f"updated file exceeds max_file_bytes={context.config.max_file_bytes}"
            )

        self._atomic_write(path, updated, stat.S_IMODE(file_stat.st_mode))
        relative_path = workspace_relative_path(context.workspace_path, path)
        return ToolResult(
            success=True,
            summary=f"replaced {expected} occurrence(s) in {relative_path}",
            data={
                "path": relative_path,
                "replacements": expected,
                "bytes_before": len(data),
                "bytes_after": len(updated_data),
            },
        )

    def _atomic_write(self, path: Path, content: str, mode: int) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp:
                temp.write(content)
                temp.flush()
                os.fsync(temp.fileno())
                temp_path = Path(temp.name)
            os.chmod(temp_path, mode)
            os.replace(temp_path, path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ToolExecutionError(f"failed to write file atomically: {exc}") from exc


def _build_edit_file_tool(context: ToolContext) -> EditFileTool:
    return EditFileTool()


register_tool_factory(EditFileTool.name, _build_edit_file_tool)
