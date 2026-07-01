# MCP Integration

MCP is optional and disabled by default. It lets nanoAgent expose tools implemented by external MCP servers through the same internal tool registry used by built-in tools.

## Current Support

The CLI currently exposes one registered provider:

- `github`: official GitHub MCP server, started through Docker with stdio transport

MCP tools are namespaced before being exposed to the LLM. For example, a GitHub tool named `search_repositories` becomes `github__search_repositories`.

## GitHub MCP Setup

Configure `.env`:

```env
GITHUB_MCP_DOCKER_IMAGE=ghcr.io/github/github-mcp-server
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
GITHUB_TOOLSETS=context,repos,issues,pull_requests
GITHUB_READ_ONLY=1
```

Run with GitHub MCP enabled:

```bash
nano-agent run https://github.com/user/repo \
  "Search related GitHub issues before changing the code" \
  --mcp-github
```

## GitHub Actions Secret

For the manual GitHub MCP smoke workflow, configure this repository secret:

```text
MCP_GITHUB_PERSONAL_ACCESS_TOKEN
```

GitHub does not allow custom secret names that start with `GITHUB_`, so the workflow maps this secret to `GITHUB_PERSONAL_ACCESS_TOKEN` at runtime.

## Safety Defaults

`GITHUB_READ_ONLY=1` is the default. Keep it enabled unless a task explicitly requires write access and the token scope has been reviewed.
