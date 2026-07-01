# Security Model

nanoAgent runs repository automation with explicit permission boundaries. It is not a general sandbox for untrusted code.

## Default Permissions

By default, high-risk actions are denied:

- workspace file edits require `--allow-write`
- command execution requires `--allow-command`

Use the smallest permission set needed for the task.

## Workspace Containment

Filesystem tools resolve paths inside the active workspace and reject paths that escape it. Editing `.git` internals is blocked.

Run artifacts are written under `.nano/runs/<run_id>/`. Cloned workspaces are written under `.nano/workspaces/` by default.

## Command Execution

Command execution uses the run environment prepared by nanoAgent. The runtime redirects `HOME`, `TMPDIR`, and cache paths to run-local locations when isolation is enabled.

Command execution can still run arbitrary project scripts. Review the target repository before enabling `--allow-command`.

## MCP Tokens

MCP servers may receive sensitive tokens. For GitHub MCP:

- prefer read-only mode
- use a token with the smallest practical scope
- avoid committing `.env`
- keep CI secrets separate from local tokens

## Recommended Usage

- Start with read-only analysis.
- Enable writes only after the agent has identified a concrete patch.
- Enable commands only when tests or build steps are needed.
- Keep GitHub MCP read-only unless write operations are intentional.
