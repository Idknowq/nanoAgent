# Development Guide

## Environment

Use the project virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Checks

```bash
.venv/bin/python -m compileall -q nano_agent tests
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## Important Paths

- `nano_agent/loop.py`: agent tool-use loop
- `nano_agent/tools/`: built-in runtime tools
- `nano_agent/hooks/`: extension hooks
- `nano_agent/context/`: compaction
- `nano_agent/background/`: background job scheduling
- `nano_agent/subagents/`: subagent execution
- `nano_agent/mcp/`: MCP runtime, providers, and tool adapter
- `tests/`: unit and integration tests

## Adding a Tool

1. Add the tool under `nano_agent/tools/`.
2. Implement an async `run()` method.
3. Register the tool factory.
4. Add focused tests under `tests/`.
5. Update docs if the tool is user-facing.

## Adding an MCP Provider

1. Add provider-specific config in `nano_agent/mcp/`.
2. Register it in `nano_agent/mcp/providers.py`.
3. Add CLI or config wiring only if users need to enable it directly.
4. Add tests for config validation and tool exposure.
5. Document setup in `docs/mcp.md`.

## Commit Style

Use concise scoped messages, for example:

```text
update(async): unify cancellation and state locks
docs(readme): simplify public documentation
fix(mcp): stabilize stdio response handling
```
