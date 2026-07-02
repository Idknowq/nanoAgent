# Documentation

This directory keeps the public project documentation small and task-oriented.

- [Getting Started](getting-started.md): install, configure, run the first task, and inspect output.
- [Architecture](architecture.md): understand the agent loop, tools, hooks, compaction, subagents, and persistence.
- [MCP Integration](mcp.md): enable GitHub MCP and understand how MCP tools are exposed.
- [Security Model](security.md): understand write, command, workspace, and token boundaries.
- [Development Guide](development.md): run tests, lint, and extend tools or MCP providers.

## Internal Development Notes

- [Background Subagent Runtime Follow-ups](todo/background-subagent-runtime.md): pending
  work from the Django stress run, including task query semantics, wait behavior,
  finalization issues, and cache-impacting result delivery.

Interview material should stay outside the main documentation path unless it is rewritten for users.
