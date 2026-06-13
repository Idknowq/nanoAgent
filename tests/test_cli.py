import inspect

from typer.testing import CliRunner

from nano_agent.cli import app, run
from nano_agent.config import AgentConfig


def test_cli_max_steps_default_comes_from_agent_config() -> None:
    parameter = inspect.signature(run).parameters["max_steps"]

    assert parameter.default == AgentConfig().max_steps


def test_cli_exposes_explicit_permission_flags() -> None:
    parameters = inspect.signature(run).parameters

    assert "allow_command" in parameters
    assert "allow_write" in parameters
    assert "auto_approve" not in parameters
    assert "auto_approve_write" not in parameters


def test_cli_help_uses_renamed_permission_options() -> None:
    result = CliRunner().invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--allow-command" in result.stdout
    assert "--allow-write" in result.stdout
    assert "--auto-approve" not in result.stdout
