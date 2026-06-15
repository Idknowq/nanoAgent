from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)
from nano_agent.tools.errors import ToolExecutionError, ToolInputError, ToolTimeoutError

SCP_STYLE_SSH_URL = re.compile(r"^git@[^:\s]+:[^\s]+$")


class CloneRepoInput(ToolInput):
    repo_url: str = Field(min_length=1)
    depth: int = Field(default=1, ge=1, le=100)


class CloneRepoTool(RuntimeTool):
    """Clone the run's repository into an empty agent workspace."""

    name = "clone_repo"
    description = "Clone the target Git repository into the current agent workspace."
    approval_level = ApprovalLevel.NETWORK
    category = "git"
    requires_workspace = True
    workspace_must_exist = False
    is_mutating = True
    input_model = CloneRepoInput
    input_schema = CloneRepoInput.model_json_schema()

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        repo_url = input_data["repo_url"]
        self._validate_repo_url(repo_url)
        if repo_url != context.repo_url:
            raise ToolInputError("repo_url must match the repository for the current run")

        workspace = context.workspace_path
        if workspace.exists():
            if not workspace.is_dir():
                raise ToolInputError("workspace is not a directory")
            if any(workspace.iterdir()):
                raise ToolInputError("workspace must be empty before clone")
        else:
            workspace.mkdir(parents=True)

        started = time.monotonic()
        completed = self._run_git(
            ["clone", "--depth", str(input_data["depth"]), "--", repo_url, "."],
            cwd=workspace,
            timeout=context.config.command_timeout_seconds,
        )
        duration = time.monotonic() - started
        if completed.returncode != 0:
            stderr_tail = completed.stderr[-context.config.stderr_tail_chars :]
            stdout_tail = completed.stdout[-context.config.stdout_tail_chars :]
            return ToolResult.failure(
                code="clone_failed",
                message=f"git clone failed with exit code {completed.returncode}",
                data={
                    "exit_code": completed.returncode,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                    "duration_seconds": duration,
                },
            )

        commit = self._git_value(["rev-parse", "HEAD"], workspace, context)
        branch = self._git_value(["branch", "--show-current"], workspace, context)
        remote_url = self._git_value(["remote", "get-url", "origin"], workspace, context)
        return ToolResult(
            success=True,
            summary=f"cloned repository at commit {commit}",
            data={
                "workspace": ".",
                "commit": commit,
                "branch": branch,
                "remote_url": remote_url,
                "duration_seconds": duration,
            },
        )

    def _git_value(self, args: list[str], workspace: Path, context: ToolContext) -> str:
        completed = self._run_git(
            args,
            cwd=workspace,
            timeout=context.config.command_timeout_seconds,
        )
        if completed.returncode != 0:
            raise ToolExecutionError(
                f"git {' '.join(args)} failed with exit code {completed.returncode}"
            )
        return completed.stdout.strip()

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeoutError(f"git command exceeded {timeout}s") from exc
        except FileNotFoundError as exc:
            raise ToolExecutionError("git executable was not found") from exc
        except OSError as exc:
            raise ToolExecutionError(f"failed to execute git: {exc}") from exc

    def _validate_repo_url(self, repo_url: str) -> None:
        if repo_url.startswith("-") or any(ord(char) < 32 for char in repo_url):
            raise ToolInputError("invalid repository URL")
        if SCP_STYLE_SSH_URL.fullmatch(repo_url):
            return

        parsed = urlparse(repo_url)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or not parsed.path.strip("/"):
            raise ToolInputError("repository URL must use https, ssh, or git@host:path")


def _build_clone_repo_tool(context: ToolContext) -> CloneRepoTool:
    return CloneRepoTool()


register_tool_factory(CloneRepoTool.name, _build_clone_repo_tool)
