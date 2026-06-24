# Repository Guidelines

## Project Structure & Module Organization

`nano_agent/` contains the Python package. Key modules include `tools/` for runtime tools, `context/` for compaction, `services/` for LLM clients, `prompts/` and `prompts/templates/` for prompt assembly, `subagents/` and `background/` for delegated work, `tasks/` for persistent task state, and `persistence/` for run artifacts. Tests live under `tests/`, with tool-specific tests in `tests/tools/` and runtime environment tests in `tests/runtime/`. Documentation is in `README.md`, `README_zh.md`, and `docs/`. Runtime outputs are written under `.nano/` and should not be committed.

## Build, Test, and Development Commands

Use Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the CLI during development:

```bash
python -m nano_agent.cli run https://github.com/example/repo "Inspect and repair verified defects."
```

Run all tests:

```bash
.venv/bin/python -m pytest -q
```

If local proxy variables interfere with OpenAI client construction, clear them for tests:

```bash
env -u ALL_PROXY -u HTTP_PROXY -u HTTPS_PROXY .venv/bin/python -m pytest -q
```

## Coding Style & Naming Conventions

Use 4-space indentation and Python type hints. Keep modules focused by domain: new tools belong in `nano_agent/tools/`, stateful services in their matching package, and tests in the corresponding `tests/test_*.py` file. `ruff` is configured for line length 100 and `py311`; follow that limit even when not running a formatter.

## Testing Guidelines

The project uses `pytest`. Add or update targeted tests for behavioral changes, especially around tool protocols, persistence, context compaction, task state transitions, and subagent scheduling. Name tests descriptively, for example `test_tool_result_budget_repairs_truncated_persisted_result`. Prefer focused unit tests plus one integration-style loop test when changing agent control flow.

## Commit & Pull Request Guidelines

Git history uses concise conventional-style messages such as `feat(agent): ...`, `fix(context): ...`, and `update(config&skill): ...`. Keep commits scoped and avoid mixing generated run artifacts with code changes. Pull requests should include a short problem statement, implementation summary, tests run, and any remaining risks or limitations.

## Agent-Specific Instructions

Do not commit `.nano/`, `.venv/`, caches, or local `.env` files. Preserve append-only run artifacts and message protocol semantics when changing persistence or compaction. When modifying tool access, verify path containment and permission behavior with tests.
