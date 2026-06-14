from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

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
from nano_agent.tools.path_utils import (
    WorkspacePathError,
    resolve_workspace_path,
    workspace_relative_path,
)

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
IGNORED_EXTENSIONS = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".bz2",
        ".class",
        ".dat",
        ".db",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".pyo",
        ".rar",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".svg",
        ".tar",
        ".ttf",
        ".war",
        ".woff",
        ".woff2",
        ".xz",
        ".zip",
    }
)
MAX_FILES_SEARCHED = 2_000
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_LINE_CHARS = 500


class GrepMatch(BaseModel):
    path: str  # 匹配文件相对工作区的路径。
    line_number: int  # 匹配内容所在的 1 起始行号。
    byte_offset: int  # 匹配行起点相对文件开头的字节偏移。
    line: str  # 经过长度限制的匹配行文本。
    context_before: list[str] = Field(default_factory=list)  # 匹配前的有限上下文行。
    context_after: list[str] = Field(default_factory=list)  # 匹配后的有限上下文行。


class GrepInput(ToolInput):
    pattern: str = Field(min_length=1, max_length=500)  # 需要搜索的正则表达式。
    path: str = Field(
        default=".",
        description="Workspace-relative file or directory path. Use '.' for the workspace root.",
    )  # 搜索起点的工作区相对路径。
    glob: str | None = Field(default=None, max_length=200)  # 可选文件名或相对路径 glob。
    ignore_case: bool = False  # 是否忽略正则匹配大小写。
    context_lines: int = Field(default=1, ge=0, le=5)  # 每个匹配返回的前后文行数。
    max_matches: int = Field(default=50, ge=1, le=100)  # 最多返回的匹配数量。


class GrepTool(RuntimeTool):
    """Search bounded workspace text files without invoking a shell command."""

    name = "grep"  # 工具注册名称。
    description = (
        "Search text files with a regex inside the workspace and return paths, line numbers, "
        "byte offsets, and bounded context. Use this structured tool instead of run_command "
        "with grep, sed, awk, find, or Python text-search scripts."
    )  # 暴露给 LLM 的工具用途说明。
    approval_level = ApprovalLevel.READ  # 文本搜索只读取工作区文件。
    category = "filesystem"  # 工具所属功能分类。
    requires_workspace = True  # 搜索依赖已存在的工作区。
    input_model = GrepInput  # 工具输入参数校验模型。
    input_schema = GrepInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        try:
            root = resolve_workspace_path(
                context.workspace_path,
                input_data["path"],
                must_exist=True,
            )
        except (WorkspacePathError, FileNotFoundError) as exc:
            raise ToolInputError(str(exc)) from exc

        try:
            pattern = re.compile(
                input_data["pattern"],
                re.IGNORECASE if input_data["ignore_case"] else 0,
            )
        except re.error as exc:
            raise ToolInputError(f"invalid regex pattern: {exc}") from exc

        matches: list[GrepMatch] = []
        files_searched = 0
        bytes_searched = 0
        truncated = False
        for path in self._candidate_files(root, input_data["glob"]):
            if files_searched >= MAX_FILES_SEARCHED or bytes_searched >= MAX_TOTAL_BYTES:
                truncated = True
                break
            try:
                size = path.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES or bytes_searched + size > MAX_TOTAL_BYTES:
                continue
            files_searched += 1
            bytes_searched += size
            file_matches = self._search_file(
                path,
                context.workspace_path,
                pattern,
                input_data["context_lines"],
                input_data["max_matches"] - len(matches),
            )
            matches.extend(file_matches)
            if len(matches) >= input_data["max_matches"]:
                truncated = True
                break

        return ToolResult(
            success=True,
            summary=f"found {len(matches)} matches across {files_searched} files",
            data={
                "pattern": input_data["pattern"],
                "matches": [match.model_dump(mode="json") for match in matches],
                "match_count": len(matches),
                "files_searched": files_searched,
                "bytes_searched": bytes_searched,
                "truncated": truncated,
            },
        )

    def _candidate_files(self, root: Path, glob_pattern: str | None) -> list[Path]:
        if root.is_symlink():
            return []
        if root.is_file():
            return [root] if self._is_searchable(root, root.parent, glob_pattern) else []
        if not root.is_dir():
            raise ToolInputError(f"not a file or directory: {root}")

        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_DIRS
                and not name.startswith(".")
                and not (Path(dirpath) / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if self._is_searchable(path, root, glob_pattern):
                    files.append(path)
                    if len(files) >= MAX_FILES_SEARCHED:
                        return files
        return files

    @staticmethod
    def _is_searchable(path: Path, root: Path, glob_pattern: str | None) -> bool:
        if path.is_symlink() or path.suffix.lower() in IGNORED_EXTENSIONS:
            return False
        if glob_pattern is None:
            return True
        relative = path.relative_to(root).as_posix() if root.is_dir() else path.name
        return fnmatch.fnmatch(path.name, glob_pattern) or fnmatch.fnmatch(
            relative,
            glob_pattern,
        )

    def _search_file(
        self,
        path: Path,
        workspace: Path,
        pattern: re.Pattern[str],
        context_lines: int,
        remaining: int,
    ) -> list[GrepMatch]:
        try:
            content = path.read_bytes()
        except OSError:
            return []
        if b"\x00" in content[:4_096]:
            return []

        raw_lines = content.splitlines(keepends=True)
        decoded = [
            raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            for raw_line in raw_lines
        ]
        matches: list[GrepMatch] = []
        byte_offset = 0
        for index, raw_line in enumerate(raw_lines):
            line = decoded[index]
            if pattern.search(line):
                matches.append(
                    GrepMatch(
                        path=workspace_relative_path(workspace, path),
                        line_number=index + 1,
                        byte_offset=byte_offset,
                        line=self._bounded_line(line),
                        context_before=[
                            self._bounded_line(value)
                            for value in decoded[max(0, index - context_lines) : index]
                        ],
                        context_after=[
                            self._bounded_line(value)
                            for value in decoded[index + 1 : index + 1 + context_lines]
                        ],
                    )
                )
                if len(matches) >= remaining:
                    break
            byte_offset += len(raw_line)
        return matches

    @staticmethod
    def _bounded_line(value: str) -> str:
        if len(value) <= MAX_LINE_CHARS:
            return value
        return value[: MAX_LINE_CHARS - 14] + "...[truncated]"


def _build_grep_tool(context: ToolContext) -> GrepTool:
    del context
    return GrepTool()


register_tool_factory(GrepTool.name, _build_grep_tool)
