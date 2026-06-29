import inspect
import re
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from nano_agent.cli import app, build_cli_config, run
from nano_agent.config import AgentConfig
from nano_agent.mcp.github import GITHUB_TOKEN_ENV
from nano_agent.mcp.models import MCPServerConfig, MCPTransportType
from nano_agent.models import CompletionReport, RunStatus, RunSummary


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plain_cli_output(text: str) -> str:
    """Remove terminal styling from Typer/Rich output for stable CI assertions."""
    return ANSI_ESCAPE_RE.sub("", text)


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
    assert "mcp_github" in parameters
    assert "background_idle_wait_timeout" in parameters
    assert "auto_approve" not in parameters
    assert "auto_approve_write" not in parameters


def test_cli_help_uses_renamed_permission_options() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], terminal_width=160)
    output = plain_cli_output(result.stdout)

    assert result.exit_code == 0
    assert "allow-command" in output
    assert "allow-write" in output
    assert "mcp-github" in output
    assert "auto-approve" not in output


def test_cli_config_disables_mcp_by_default(tmp_path: Path) -> None:
    """CLI 默认不启动外部 MCP server。"""

    config = build_cli_config(
        workdir=tmp_path / "workspaces",
        max_steps=3,
        background_idle_wait_timeout=1.0,
        allow_command=False,
        allow_write=False,
        llm="deepseek",
        model=None,
        mcp_github=False,
    )

    assert config.mcp_enabled is False
    assert config.mcp_servers == ()


def test_cli_config_adds_github_mcp_server(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """CLI 显式启用 GitHub MCP 时写入 GitHub server 配置。"""

    server = MCPServerConfig(
        name="github",
        transport=MCPTransportType.STDIO,
        command="docker",
        args=("run", "ghcr.io/github/github-mcp-server"),
    )
    def build_servers(names: tuple[str, ...]) -> tuple[MCPServerConfig, ...]:
        assert names == ("github",)
        return (server,)

    monkeypatch.setattr("nano_agent.cli.build_mcp_provider_configs", build_servers)

    config = build_cli_config(
        workdir=tmp_path / "workspaces",
        max_steps=3,
        background_idle_wait_timeout=1.0,
        allow_command=False,
        allow_write=False,
        llm="deepseek",
        model=None,
        mcp_github=True,
    )

    assert config.mcp_enabled is True
    assert config.mcp_servers == (server,)


def test_cli_reports_missing_github_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """启用 GitHub MCP 但缺 token 时，CLI 返回明确错误。"""

    def missing_token() -> MCPServerConfig:
        raise ValueError(f"{GITHUB_TOKEN_ENV} is required")

    def build_servers(names: tuple[str, ...]) -> tuple[MCPServerConfig, ...]:
        assert names == ("github",)
        return (missing_token(),)

    monkeypatch.setattr("nano_agent.cli.build_mcp_provider_configs", build_servers)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "https://example.com/repo.git",
            "Inspect repo.",
            "--mcp-github",
        ],
        terminal_width=160,
    )

    assert result.exit_code != 0
    output = plain_cli_output(result.output)
    assert GITHUB_TOKEN_ENV in output
    assert "required" in output


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
