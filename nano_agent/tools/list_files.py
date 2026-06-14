from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)
from nano_agent.tools.errors import ToolInputError
from nano_agent.tools.path_utils import WorkspacePathError, resolve_workspace_path

IGNORED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


class ListFilesInput(ToolInput):
    path: str = Field(
        default=".",
        description="Workspace-relative directory path. Use '.' for the workspace root.",
    )  # 需要列出的工作区相对目录。
    max_depth: int = Field(default=2, ge=0, le=10)  # 递归列出的最大目录深度。
    max_entries: int = Field(default=500, ge=1, le=5000)  # 最多返回的文件条目数。
    include_hidden: bool = False  # 是否包含普通隐藏文件和目录。


class FileEntry(BaseModel):
    path: str  # 文件或目录相对工作区的路径。
    type: Literal["file", "directory", "symlink"]  # 当前条目的文件系统类型。
    size: int | None = None  # 普通文件的字节数，目录和符号链接为空。


class ListFilesTool(RuntimeTool):
    """List a bounded directory tree without following symlinks."""

    name = "list_files"
    description = (
        "List files and directories using a workspace-relative path. "
        "Use path='.' for the workspace root instead of an absolute path."
    )
    approval_level = ApprovalLevel.READ
    category = "filesystem"
    requires_workspace = True
    input_model = ListFilesInput
    input_schema = ListFilesInput.model_json_schema()

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        requested_path = input_data["path"]
        supplied = Path(requested_path)
        if supplied.is_absolute() and supplied.resolve(strict=False) == (
            context.workspace_path.resolve(strict=False)
        ):
            requested_path = "."
        try:
            root = resolve_workspace_path(
                context.workspace_path,
                requested_path,
                must_exist=True,
            )
        except (WorkspacePathError, FileNotFoundError) as exc:
            raise ToolInputError(str(exc)) from exc

        if not root.is_dir():
            raise ToolInputError(f"not a directory: {requested_path}")

        workspace = context.workspace_path.resolve()
        entries: list[FileEntry] = []
        skipped: list[str] = []
        stack: list[tuple[Path, int]] = [(root, 0)]
        truncated = False

        while stack:
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as iterator:
                    children = sorted(iterator, key=lambda entry: entry.name)
            except OSError:
                skipped.append(directory.relative_to(workspace).as_posix() or ".")
                continue

            child_directories: list[Path] = []
            for child in children:
                if child.name in IGNORED_NAMES:
                    continue
                if not input_data["include_hidden"] and child.name.startswith("."):
                    continue
                if len(entries) >= input_data["max_entries"]:
                    truncated = True
                    break

                path = Path(child.path)
                relative_path = path.relative_to(workspace).as_posix()
                try:
                    if child.is_symlink():
                        entries.append(FileEntry(path=relative_path, type="symlink"))
                    elif child.is_dir(follow_symlinks=False):
                        entries.append(FileEntry(path=relative_path, type="directory"))
                        if depth < input_data["max_depth"]:
                            child_directories.append(path)
                    elif child.is_file(follow_symlinks=False):
                        size = child.stat(follow_symlinks=False).st_size
                        entries.append(FileEntry(path=relative_path, type="file", size=size))
                except OSError:
                    skipped.append(relative_path)

            if truncated:
                break
            stack.extend((path, depth + 1) for path in reversed(child_directories))

        entries.sort(key=lambda entry: entry.path)
        root_path = root.relative_to(workspace).as_posix() or "."
        return ToolResult(
            success=True,
            summary=f"listed {len(entries)} entries under {root_path}",
            data={
                "root": root_path,
                "entries": [entry.model_dump(mode="json") for entry in entries],
                "entry_count": len(entries),
                "truncated": truncated,
                "skipped": sorted(skipped),
            },
        )


def _build_list_files_tool(context: ToolContext) -> ListFilesTool:
    return ListFilesTool()


register_tool_factory(ListFilesTool.name, _build_list_files_tool)
