from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.runtime.environment import ExecutionEnvironmentManager


def test_environment_redirects_package_manager_state(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "run-1" / "runtime"
    manager = ExecutionEnvironmentManager(runtime_dir, AgentConfig())

    environment = manager.build_environment()

    assert environment["HOME"] == str(runtime_dir / "home")
    assert environment["TMPDIR"] == str(runtime_dir / "tmp")
    assert environment["PIP_CACHE_DIR"] == str(runtime_dir / "pip-cache")
    assert environment["npm_config_prefix"] == str(runtime_dir / "npm-prefix")
    assert environment["npm_config_cache"] == str(runtime_dir / "npm-cache")
    assert environment["CARGO_HOME"] == str(runtime_dir / "cargo-home")
    assert environment["CARGO_INSTALL_ROOT"] == str(runtime_dir / "cargo-install")
    assert environment["GOPATH"] == str(runtime_dir / "go")
    assert environment["GOCACHE"] == str(runtime_dir / "go-cache")
    assert "VIRTUAL_ENV" not in environment


def test_python_environments_are_scoped_to_individual_runs(tmp_path: Path) -> None:
    first = ExecutionEnvironmentManager(tmp_path / "run-1" / "runtime", AgentConfig())
    second = ExecutionEnvironmentManager(tmp_path / "run-2" / "runtime", AgentConfig())

    first_python = first.resolve_program("python3")
    second_python = second.resolve_program("python3")

    assert first_python != second_python
    assert first.runtime_dir in first_python.parents
    assert second.runtime_dir in second_python.parents
