"""Tests for DockerSandbox."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nano_agent.sandbox.docker import DockerSandbox, DockerSandboxError


def _ok(stdout=""):
    """Return a mock subprocess.CompletedProcess with returncode 0."""
    return type("result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()


def _err(stderr=""):
    """Raise CalledProcessError to simulate check=True failures."""
    raise subprocess.CalledProcessError(1, "cmd", stderr=stderr)


class TestDockerSandbox:
    def test_default_properties(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        assert sb.name.startswith("nanoagent-")
        assert sb.running is False

    def test_start_creates_container(self, tmp_path: Path):
        sb = DockerSandbox(image="python:3.11", workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [_ok(), _ok()]  # inspect ok, run ok
            sb.start()
            assert sb.running

    def test_start_pulls_missing_image(self, tmp_path: Path):
        sb = DockerSandbox(image="rare:latest", workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _ok(""),             # inspect fails (returncode != 0?)
            ]
            # Actually inspect failure returns result with returncode=1, not exception
            # Fix: use returncode-based check
            mock_run.reset_mock()
        # Let's fix the code behavior: _ensure_image doesn't use check=True
        # So we need to test differently
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                type("r", (), {"returncode": 1})(),  # inspect fails
                _ok(),  # pull ok
                _ok(),  # run ok
            ]
            sb.start()
            assert sb.running

    def test_start_failure_raises(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _ok(),  # inspect ok
                subprocess.CalledProcessError(1, "run", stderr="port in use"),
            ]
            with pytest.raises(DockerSandboxError, match="port in use"):
                sb.start()

    def test_run_executes_command(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _ok(),  # inspect
                _ok(),  # run container
                type("r", (), {"returncode": 0, "stdout": "hello", "stderr": ""})(),  # exec
            ]
            sb.start()
            code, stdout, stderr = sb.run(["echo", "hello"])
            assert code == 0
            assert stdout == "hello"

    def test_run_passes_env_vars(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _ok(),  # inspect
                _ok(),  # run container
                _ok(),  # exec
            ]
            sb.start()
            sb.run(["cmd"], env={"KEY": "val"})
            exec_call = mock_run.call_args_list[2]
            args = exec_call[0][0]
            assert "-e" in args
            assert "KEY=val" in args

    def test_run_when_stopped(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        code, stdout, stderr = sb.run(["cmd"])
        assert code == -1
        assert "not running" in stderr

    def test_stop_removes_container(self, tmp_path: Path):
        sb = DockerSandbox(workspace=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _ok(),  # inspect
                _ok(),  # run container
                _ok(),  # stop
            ]
            sb.start()
            sb.stop()
            assert sb.running is False

    def test_network_disabled_flag(self, tmp_path: Path):
        sb2 = DockerSandbox(workspace=tmp_path, network_disabled=False)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [_ok(), _ok()]
            sb2.start()
            run_call = mock_run.call_args_list[1]
            args = run_call[0][0]
            assert "--network=none" not in args
