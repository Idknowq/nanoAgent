from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    """Requested path is invalid for the current agent workspace."""


def resolve_workspace_path(
    workspace: Path,
    requested_path: str,
    *,
    must_exist: bool = False,
    allow_root: bool = True,
) -> Path:
    """Resolve a relative path and ensure it cannot escape the workspace."""
    if not requested_path.strip():
        raise WorkspacePathError("path cannot be empty")

    supplied = Path(requested_path)
    if supplied.is_absolute():
        raise WorkspacePathError("absolute paths are not allowed")

    root = workspace.resolve()
    if root.exists() and not root.is_dir():
        raise WorkspacePathError("workspace is not a directory")

    candidate = (root / supplied).resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise WorkspacePathError("path escapes workspace")
    if not allow_root and candidate == root:
        raise WorkspacePathError("workspace root is not allowed")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(requested_path)

    return candidate


def workspace_relative_path(workspace: Path, path: Path) -> str:
    """Return a stable POSIX-style path relative to the workspace."""
    return path.resolve(strict=False).relative_to(workspace.resolve()).as_posix() or "."


def reject_git_internal_path(workspace: Path, path: Path) -> None:
    """Reject access to Git's internal metadata directory."""
    relative = path.resolve(strict=False).relative_to(workspace.resolve())
    if ".git" in relative.parts:
        raise WorkspacePathError(".git paths are not allowed")
