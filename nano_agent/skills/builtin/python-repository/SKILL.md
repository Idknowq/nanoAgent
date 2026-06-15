---
name: python-repository
description: Investigate and repair Python repository failures involving pytest, imports, packaging, dependencies, or runtime behavior. Activate when the task requires Python-specific diagnosis or verification, not merely because Python files exist.
compatibility: Python tooling may be required for verification.
metadata:
  version: "2.0"
---

# Python Repository Repair

## Orient

- Read applicable repository instructions and the nearest `pyproject.toml`, `setup.cfg`,
  `setup.py`, `tox.ini`, `pytest.ini`, dependency files, and package layout only as needed.
- Infer the supported Python versions, test runner, optional dependency groups, and source layout
  from repository evidence. Do not assume a generic installation command.
- Prefer project-declared commands. With the available command tool, use structured forms such as
  `python -m pytest`, `pytest`, `pip install -e .`, or the repository's supported equivalent.

## Diagnose

- Start from the reported test, traceback, symbol, or behavior. Run the smallest useful
  reproduction before broad collection when practical.
- Classify the failure before editing: environment or dependency setup, import/collection,
  packaging, fixture/setup, assertion mismatch, exception behavior, state leakage, or performance.
- Trace from the failing assertion or exception into the implementation and its callers. Compare
  neighboring APIs and tests to infer intended behavior.
- Check edge cases at the same abstraction boundary: empty input, invalid input, alternate types,
  ordering, mutation, caching, and version compatibility when relevant.

## Repair

- Change implementation code rather than weakening tests unless the user explicitly requests a
  test change or the test itself is demonstrably wrong.
- Preserve public APIs and compatibility unless the task requires a change.
- Avoid dependency or packaging edits unless the failure is actually caused there.
- Do not add broad exception handling, global state resets, or special cases for one visible test
  without evidence that they represent the intended general behavior.

## Verify

1. Re-run the original focused reproduction.
2. Run the nearest affected test file or package.
3. Run broader pytest, Ruff, packaging, or import checks when supported and proportionate.
4. If setup or dependencies prevent verification, report the exact failing command and separate
   that blocker from confidence in the code change.
