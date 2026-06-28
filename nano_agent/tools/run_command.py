from __future__ import annotations

import os
import signal
import subprocess
import time

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.runtime.environment import ExecutionEnvironmentManager
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)
from nano_agent.tools.command_policy import validate_program
from nano_agent.tools.errors import ToolExecutionError, ToolInputError
from nano_agent.tools.path_utils import (
    WorkspacePathError,
    resolve_workspace_path,
    workspace_relative_path,
)


class RunCommandInput(ToolInput):
    program: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list, max_length=256)
    cwd: str = "."
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class RunCommandTool(RuntimeTool):
    """Run one allowlisted program without invoking a shell."""

    name = "run_command"
    description = "Run an allowlisted program with structured arguments in the agent workspace."
    approval_level = ApprovalLevel.EXECUTE_RISKY
    category = "execution"
    requires_workspace = True
    is_mutating = True
    input_model = RunCommandInput
    input_schema = RunCommandInput.model_json_schema()

    async def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        program = validate_program(input_data["program"])
        try:
            cwd = resolve_workspace_path(
                context.workspace_path,
                input_data["cwd"],
                must_exist=True,
            )
        except (WorkspacePathError, FileNotFoundError) as exc:
            raise ToolInputError(str(exc)) from exc
        if not cwd.is_dir():
            raise ToolInputError(f"command cwd is not a directory: {input_data['cwd']}")

        started = time.monotonic()
        environment_manager = ExecutionEnvironmentManager(
            runtime_dir=context.runtime_dir or context.run_dir / "runtime",
            config=context.config,
        )
        resolved_program = environment_manager.resolve_program(program)
        argv = [program, *input_data["args"]]
        process_argv = [str(resolved_program), *input_data["args"]]
        timeout = input_data["timeout_seconds"] or context.config.command_timeout_seconds
        timeout = min(timeout, 600)

        try:
            process = subprocess.Popen(
                process_argv,
                cwd=cwd,
                env=environment_manager.build_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise ToolExecutionError(f"executable was not found: {program}") from exc
        except OSError as exc:
            raise ToolExecutionError(f"failed to start command: {exc}") from exc

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout, stderr = self._terminate_process_group(process)

        duration = time.monotonic() - started
        stdout_tail = stdout[-context.config.stdout_tail_chars :]
        stderr_tail = stderr[-context.config.stderr_tail_chars :]
        data = {
            "argv": argv,
            "resolved_program": str(resolved_program),
            "execution_environment": (
                "isolated" if context.config.execution_isolation_enabled else "host"
            ),
            "cwd": workspace_relative_path(context.workspace_path, cwd),
            "exit_code": process.returncode,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "duration_seconds": duration,
            "timed_out": timed_out,
        }
        if timed_out:
            return ToolResult.failure(
                code="timeout",
                message=f"command exceeded {timeout}s",
                data=data,
            )
        if process.returncode != 0:
            return ToolResult.failure(
                code="command_failed",
                message=f"command exited with code {process.returncode}",
                data=data,
            )
        return ToolResult(
            success=True,
            summary=f"exit_code=0, duration={duration:.2f}s",
            data=data,
        )

    def _terminate_process_group(
        self,
        process: subprocess.Popen[str],
    ) -> tuple[str, str]:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return process.communicate()


def _build_run_command_tool(context: ToolContext) -> RunCommandTool:
    return RunCommandTool()


register_tool_factory(RunCommandTool.name, _build_run_command_tool)
