<p align="center">
  <h1 align="center">🤖 nanoAgent</h1>
  <p align="center">
    A lightweight async Coding Agent for repository diagnosis, repair, and tool integration.
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B%20%7C%20CI%203.13-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/stability-experimental-orange" alt="Stability" />
</p>

---

## 📖 Overview

nanoAgent is an experimental Coding Agent that clones a Git repository, explores the codebase,
uses tools to diagnose problems, applies scoped fixes, verifies the result, and writes a structured
run report.

The core runtime is async-first: LLM calls, tools, hooks, subprocesses, task state, background
subagents, and MCP sessions all run through async interfaces.

## ✨ Features

| Feature | Description |
| --- | --- |
| 🧠 Tool-use loop | LLM requests tools, nanoAgent executes them, and results are injected back in order. |
| 🔧 Built-in tools | Repository, filesystem, search, command, edit, task, and delegation tools. |
| ⚡ Async runtime | LLM calls, tools, hooks, subprocesses, task state, subagents, and MCP sessions use async interfaces. |
| 📦 Isolated runs | Each run gets an isolated workspace and run-local execution environment. |
| 🗜️ Context compaction | Long runs use layered compaction to stay within the model input budget. |
| 👥 Background subagents | Read-only subagents run as bounded `asyncio.Task` jobs. |
| 🌐 MCP integration | Optional MCP runtime with built-in GitHub MCP provider support. |
| 📝 Run artifacts | Reports, messages, metrics, audit logs, tasks, and subagent output are stored under `.nano/runs/<run_id>/`. |

## 🚀 Quick Start

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
```

Edit `.env`:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Run:

```bash
nano-agent run https://github.com/user/repo \
  "Fix the failing tests in test_login.py" \
  --allow-write --allow-command
```

The final report is written to `.nano/runs/<run_id>/report.md`.

## 🌐 GitHub MCP

GitHub MCP is optional and disabled by default. To enable it, configure:

```env
GITHUB_MCP_DOCKER_IMAGE=ghcr.io/github/github-mcp-server
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
GITHUB_TOOLSETS=context,repos,issues,pull_requests
GITHUB_READ_ONLY=1
```

Then run:

```bash
nano-agent run https://github.com/user/repo \
  "Search related GitHub issues before changing the code" \
  --mcp-github
```

## 📚 Documentation

- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [MCP Integration](docs/mcp.md)
- [Security Model](docs/security.md)
- [Development Guide](docs/development.md)

Chinese documentation: [README_zh.md](README_zh.md)

## ⚠️ Current Limitations

- DeepSeek is the only built-in LLM provider.
- Subagents are limited to one delegation level.
- GitHub is the only registered MCP provider exposed by the CLI.
- Token estimation uses a conservative character ratio, not a provider tokenizer.
- Background jobs do not recover after process restart.

## 📄 License

MIT
