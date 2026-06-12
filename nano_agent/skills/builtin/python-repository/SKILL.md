---
name: python-repository
description: Diagnose Python repositories, pytest failures, packaging problems, and dependency issues. Use when Python project markers or Python failures are present.
compatibility: Python tooling may be required for verification.
metadata:
  version: "1.0"
---

# Python Repository Diagnosis

- Inspect `pyproject.toml`, dependency files, package layout, and test configuration first.
- Prefer the project's declared environment and test commands over guessed commands.
- Distinguish dependency, import-path, collection, assertion, lint, and runtime failures.
- Run a focused failing test before broadening to the full suite.
- Avoid changing package metadata or dependency constraints unless the evidence requires it.
- Report the exact command and exit result used for verification.
