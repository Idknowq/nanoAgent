from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.run_command import RunCommandTool


def make_context(
    tmp_path: Path,
    *,
    stdout_tail_chars: int = 16_000,
    stderr_tail_chars: int = 16_000,
) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=AgentConfig(
            workspace_root=tmp_path,
            command_timeout_seconds=5,
            stdout_tail_chars=stdout_tail_chars,
            stderr_tail_chars=stderr_tail_chars,
        ),
    )


def test_run_command_executes_structured_arguments(tmp_path: Path) -> None:
    result = RunCommandTool().invoke(
        {"program": "python3", "args": ["-c", "print('hello')"]},
        make_context(tmp_path),
    )

    assert result.success
    assert result.data["argv"] == ["python3", "-c", "print('hello')"]
    assert result.data["stdout_tail"] == "hello\n"
    assert result.data["cwd"] == "."


def test_run_command_uses_safe_workspace_cwd(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    result = RunCommandTool().invoke(
        {
            "program": "python3",
            "args": ["-c", "import os; print(os.path.basename(os.getcwd()))"],
            "cwd": "src",
        },
        make_context(tmp_path),
    )

    assert result.success
    assert result.data["stdout_tail"] == "src\n"
    assert result.data["cwd"] == "src"


def test_run_command_rejects_program_outside_allowlist(tmp_path: Path) -> None:
    result = RunCommandTool().invoke(
        {"program": "sh", "args": ["-c", "echo unsafe"]},
        make_context(tmp_path),
    )

    assert result.error_code == "invalid_input"
    assert "not allowed" in result.error_message


def test_run_command_rejects_program_path_and_cwd_escape(tmp_path: Path) -> None:
    program_path = RunCommandTool().invoke(
        {"program": "/usr/bin/python3", "args": ["--version"]},
        make_context(tmp_path),
    )
    cwd_escape = RunCommandTool().invoke(
        {"program": "python3", "cwd": ".."},
        make_context(tmp_path),
    )

    assert program_path.error_code == "invalid_input"
    assert cwd_escape.error_code == "invalid_input"


def test_run_command_returns_nonzero_exit_as_failure(tmp_path: Path) -> None:
    result = RunCommandTool().invoke(
        {"program": "python3", "args": ["-c", "raise SystemExit(7)"]},
        make_context(tmp_path),
    )

    assert not result.success
    assert result.error_code == "command_failed"
    assert result.data["exit_code"] == 7


def test_run_command_truncates_output_tails(tmp_path: Path) -> None:
    result = RunCommandTool().invoke(
        {
            "program": "python3",
            "args": ["-c", "import sys; print('abcdefgh'); print('12345678', file=sys.stderr)"],
        },
        make_context(tmp_path, stdout_tail_chars=5, stderr_tail_chars=4),
    )

    assert result.data["stdout_tail"] == "efgh\n"
    assert result.data["stderr_tail"] == "678\n"


def test_run_command_terminates_timed_out_process(tmp_path: Path) -> None:
    result = RunCommandTool().invoke(
        {
            "program": "python3",
            "args": ["-c", "import time; time.sleep(10)"],
            "timeout_seconds": 1,
        },
        make_context(tmp_path),
    )

    assert not result.success
    assert result.error_code == "timeout"
    assert result.data["timed_out"]
