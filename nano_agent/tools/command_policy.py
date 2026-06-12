from __future__ import annotations

from pathlib import Path

from nano_agent.tools.errors import ToolInputError

ALLOWED_PROGRAMS = frozenset(
    {
        "cargo",
        "git",
        "go",
        "mvn",
        "node",
        "npm",
        "pytest",
        "python3",
        "pip",
        "ruff",
    }
)


def validate_program(program: str) -> str:
    """Require a bare executable name from the command allowlist."""
    if Path(program).name != program or "/" in program or "\\" in program:
        raise ToolInputError("program must be a bare executable name")
    if program not in ALLOWED_PROGRAMS:
        raise ToolInputError(f"program is not allowed: {program}")
    return program
