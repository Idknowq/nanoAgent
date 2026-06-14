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
        "python",
        "python3",
        "pip",
        "ruff",
    }
)

STRUCTURED_TOOL_SUGGESTIONS = {
    "cat": (
        "program is not allowed: cat. Use read_file with path, or with "
        "line_start/line_end for a bounded line range"
    ),
    "head": (
        "program is not allowed: head. Use read_file with line_start=1 and line_end set "
        "to the last required line"
    ),
    "sed": (
        "program is not allowed: sed. Use read_file with line_start and line_end for an "
        "inclusive line range"
    ),
}


def validate_program(program: str) -> str:
    """Require a bare executable name from the command allowlist."""
    if Path(program).name != program or "/" in program or "\\" in program:
        raise ToolInputError("program must be a bare executable name")
    if program not in ALLOWED_PROGRAMS:
        raise ToolInputError(
            STRUCTURED_TOOL_SUGGESTIONS.get(
                program,
                f"program is not allowed: {program}",
            )
        )
    return program
