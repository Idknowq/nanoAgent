import inspect
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from nano_agent.cli import app, run
from nano_agent.config import AgentConfig
from nano_agent.models import CompletionReport, RunStatus, RunSummary


def test_cli_max_steps_default_comes_from_agent_config() -> None:
    parameters = inspect.signature(run).parameters

    assert parameters["max_steps"].default == AgentConfig().max_steps
    assert (
        parameters["background_idle_wait_timeout"].default
        == AgentConfig().background_idle_wait_timeout_seconds
    )


def test_cli_exposes_explicit_permission_flags() -> None:
    parameters = inspect.signature(run).parameters

    assert "user_request" in parameters
    assert "allow_command" in parameters
    assert "allow_write" in parameters
    assert "auto_approve" not in parameters
    assert "auto_approve_write" not in parameters


def test_cli_help_uses_renamed_permission_options() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], terminal_width=160)

    assert result.exit_code == 0
    assert "--allow-command" in result.stdout
    assert "--allow-write" in result.stdout
    assert "--background-idle-wai" in result.stdout
    assert "--auto-approve" not in result.stdout


def test_cli_prints_compact_status_without_summary_content(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """CLI 只展示运行状态和报告路径，不输出报告正文或完整 JSON。"""

    now = datetime.now(timezone.utc)
    result = RunSummary(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        status=RunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        steps=3,
        llm_call_count=4,
        completion_report=CompletionReport(
            status=RunStatus.COMPLETED,
            problem="SECRET REPORT CONTENT",
            root_cause="cause",
            resolution="resolution",
        ),
    )

    received: dict[str, str] = {}

    async def fake_run(self, repo_url: str, user_request: str) -> RunSummary:  # type: ignore[no-untyped-def]
        received["repo_url"] = repo_url
        received["user_request"] = user_request
        return result

    monkeypatch.setattr("nano_agent.cli.NanoAgent.run", fake_run)
    runner = CliRunner()

    response = runner.invoke(
        app,
        [
            "run",
            "https://example.com/repo.git",
            "Inspect Click help generation and tests.",
            "--workdir",
            str(tmp_path / "workspaces"),
        ],
    )

    assert response.exit_code == 0
    assert "Status" in response.output
    assert "completed" in response.output
    assert "report.md" in response.output
    assert "SECRET REPORT CONTENT" not in response.output
    assert '"completion_report"' not in response.output
    assert received == {
        "repo_url": "https://example.com/repo.git",
        "user_request": "Inspect Click help generation and tests.",
    }
