<p align="center">
  <h1 align="center">🤖 nanoAgent</h1>
  <p align="center">
    A lightweight async Coding Agent for repository diagnosis, repair, and tool integration
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B%20%7C%20CI%203.13-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/stability-experimental-orange" alt="Stability" />
</p>

---

## 📖 Overview

nanoAgent is a lightweight async Coding Agent prototype that pulls a Git repository, analyzes its
structure, pinpoints root causes, and performs verified fixes within an isolated execution
environment. The central idea is to **give the LLM tools and let it work**: it operates inside a
controlled loop, observing, reasoning, acting, and reporting until the task is done.

Unlike a one-shot Q&A session, nanoAgent will:

- 🔍 Actively explore the repository structure and search for relevant code
- 🧪 Reproduce test failures and compare against expected behavior
- ✏️ Make precise source changes rather than weakening assertions
- 🔄 Retry on transient errors and compact context when it grows too large
- 📋 Deliver a structured completion report with evidence, risks, and changed files

Current phase: the core runtime has completed its asyncio migration. `NanoAgent.run()`,
`AgentLoop.run()`, LLM calls, runtime tools, hooks, command execution, task state transitions,
background jobs, and subagent scheduling all run through async interfaces. MCP support is now
available behind explicit configuration, with a built-in provider for the official GitHub MCP
server.

---

## ✨ Features

| Feature | Description |
|------|------|
| ⚡ **Async Runtime** | Async LLM calls, tool invocation, hooks, subprocess execution, and subagent scheduling |
| 🧠 **Tool-Use Loop** | LLM requests tools → execute → inject results → continue reasoning until done |
| 🔧 **Rich Built-in Tools** | Repository cloning, file I/O, grep search, shell commands, code editing, task management |
| 📦 **Isolated Runtime** | Per-run venv, sandboxed HOME / TMPDIR / cache directories |
| 🗜️ **Multi-Layer Compaction** | Budget → Snip → Micro → LLM summary → Reactive, five-tier progressive reduction |
| 🔄 **Resilient Recovery** | Exponential backoff for transients, bounded continuation for truncation, correction for invalid tool calls |
| 🔌 **Extensible Hooks** | Permission, audit, metrics, skill injection — composable at each loop boundary |
| 👥 **Subagent Delegation** | Background subagent jobs scheduled with `asyncio.Task`, up to 2 concurrent read-only subagents |
| 📋 **Persistent Task Tracking** | Dependency graph (`blocked_by`), lifecycle state machine, background Job linkage |
| 🌐 **MCP Integration** | Optional MCP runtime with stdio/http configuration and GitHub MCP provider support |
| 📝 **Structured Reports** | Every run produces `report.md` with problem, root cause, changed files, verification, and risks |
| 🎯 **On-Demand Skills** | Built-in Python / Node / Django / GitHub Actions domain skills, activated by the model when needed |

---

## 🚀 Quick Start

### Prerequisites

- Python ≥ 3.11. Local development and GitHub Actions currently use Python 3.13.
- DeepSeek API key ([get one here](https://platform.deepseek.com))
- Docker, only when using the built-in GitHub MCP provider

### Installation

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Optional GitHub MCP configuration:

```env
GITHUB_MCP_DOCKER_IMAGE=ghcr.io/github/github-mcp-server
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
GITHUB_TOOLSETS=context,repos,issues,pull_requests
GITHUB_READ_ONLY=1
```

### Usage

```bash
# Basic: diagnose and fix a repository
nano-agent run https://github.com/user/repo \
  "Fix the failing tests in test_login.py"

# Enable writes and command execution
nano-agent run https://github.com/user/repo \
  "Refactor error handling in utils.py" \
  --allow-write --allow-command

# Custom step count and background timeout
nano-agent run https://github.com/user/repo \
  "Run the full test suite and fix every failure" \
  --max-steps 200 --background-idle-wait-timeout 120

# Expose tools from the official GitHub MCP server
nano-agent run https://github.com/user/repo \
  "Search related GitHub issues before changing the code" \
  --mcp-github
```

When the run finishes, the terminal prints a compact summary. The full report lives at
`.nano/runs/<run_id>/report.md`.

---

## 📁 Project Structure

```
nano_agent/
├── agent.py              # Async top-level entry point — wires components and launches the loop
├── loop.py               # Async tool-use loop engine with error recovery
├── cli.py                # Typer CLI entry point, using asyncio.run at the process boundary
├── config.py             # AgentConfig — single source of truth for all runtime parameters
├── models.py             # Pydantic data models: messages, responses, run state
├── workspace.py          # Isolated workspace management and run summaries
├── tools/                # Runtime tools
│   ├── base.py           #   RuntimeTool ABC + ToolRegistry
│   ├── clone_repo.py     #   Repository cloning
│   ├── list_files.py     #   Directory listing
│   ├── grep.py           #   Code search
│   ├── read_file.py      #   File reading with offset/limit
│   ├── edit_file.py      #   Exact-string file editing
│   ├── run_command.py    #   Shell command execution
│   ├── finish_run.py     #   Termination protocol
│   ├── todo.py           #   Short-lived execution checklist
│   ├── activate_skill.py #   Skill activation
│   ├── delegate_task.py  #   Subagent delegation + query/cancel
│   └── tasks.py          #   Persistent task CRUD
├── services/             # LLM service layer
│   ├── llm.py            #   LLMClient Protocol + scripted test client
│   ├── openai_compatible.py  # OpenAI-compatible client (DeepSeek)
│   ├── errors.py         #   Error classification and normalization
│   ├── retry.py          #   Exponential backoff with jitter
│   └── registry.py       #   Provider registration and factory
├── hooks/                # Loop extension points
│   ├── base.py           #   AgentHook Protocol (5 callbacks)
│   ├── permission.py     #   Permission gating
│   ├── console.py        #   Terminal progress display
│   ├── llm_metrics.py    #   LLM call metrics recording
│   ├── audit.py          #   Tool call audit trail
│   └── skill_activation.py   # Skill body injection
├── context/              # Context compaction
│   ├── compactor.py      #   Five-layer compaction pipeline + persistence
│   └── state.py          #   Compaction state builder
├── subagents/            # Subagent system
│   ├── manager.py        #   Subagent creation and async execution
│   ├── context.py        #   Subagent context builder
│   ├── models.py         #   Subagent data models
│   └── store.py          #   Subagent state persistence
├── background/           # Background job scheduling
│   ├── supervisor.py     #   asyncio.Task scheduler with bounded concurrency
│   ├── hook.py           #   Completion notification hook
│   ├── cancellation.py   #   Cooperative cancellation token
│   └── store.py          #   Job snapshot persistence
├── mcp/                  # Model Context Protocol integration
│   ├── manager.py        #   MCP runtime lifecycle and tool registration
│   ├── session.py        #   MCP initialize / tools/list / tools/call session
│   ├── transport.py      #   stdio and HTTP transports
│   ├── tool_adapter.py   #   RuntimeTool adapter for MCP tools
│   ├── providers.py      #   Provider registry
│   └── github.py         #   GitHub MCP Docker provider config
├── tasks/                # Persistent task management
│   ├── service.py        #   Task lifecycle service
│   ├── store.py          #   File-based task storage
│   └── models.py         #   Task data models
├── prompts/              # Prompt assembly
│   ├── assembler.py      #   Initial conversation builder
│   └── templates/        #   Markdown prompt templates
│       ├── core.md       #     Stable core prompt (cache-friendly)
│       └── repository_design.md  # Task template
├── skills/               # Domain knowledge skills
│   ├── registry.py       #   Skill discovery and metadata
│   ├── session.py        #   Skill activation session
│   └── builtin/          #   Built-in skills (Python / Node / Django / GitHub Actions)
├── memory/               # Cross-run memory
│   └── store.py          #   JSONL memory store with tag-based filtering
├── runtime/              # Execution environment isolation
│   └── environment.py    #   Venv creation, PATH sanitization, env var redirection
└── persistence/          # File-based persistence
    ├── message_store.py  #   Append-only message stream
    ├── config_store.py   #   Config snapshot
    ├── prompt_store.py   #   Prompt composition metadata
    ├── report_store.py   #   Report rendering
    └── summary_store.py  #   Run summary
```

---

## ⚙️ Configuration

All settings live in `AgentConfig` (`nano_agent/config.py`). CLI flags override defaults.

### Context & Tokens

| Parameter | Default | Description |
|------|------|------|
| `context_max_input_tokens` | 256,000 | Input token budget |
| `context_auto_compact_ratio` | 0.8 | Fraction at which auto-compaction triggers |
| `max_auto_compactions` | 3 | Maximum auto-compaction rounds per run |
| `tool_result_budget_chars` | 32,000 | Character budget per tool-result batch |
| `snip_keep_head` / `snip_keep_tail` | 8 / 32 | Messages retained at head/tail during snip |

### Subagents

| Parameter | Default | Description |
|------|------|------|
| `subagent_max_steps` | 50 | Maximum loop steps for a child agent |
| `subagent_max_llm_calls` | 75 | LLM call budget for a child agent |
| `subagent_max_result_chars` | 16,000 | Max characters in a subagent result |
| `background_max_workers` | 2 | Maximum concurrent background subagents |
| `background_max_jobs` | 8 | Maximum non-terminal jobs at once |

### Error Recovery

| Parameter | Default | Description |
|------|------|------|
| `llm_max_transient_retries` | 4 | Maximum transient error retries |
| `llm_retry_base_seconds` | 5.0 | Base seconds for exponential backoff |
| `llm_retry_max_seconds` | 60.0 | Cap on local backoff delay |
| `llm_max_continuations` | 2 | Maximum continuation requests after truncation |

See `nano_agent/config.py` for the full set of parameters.

### MCP

MCP is disabled by default. The CLI currently exposes the registered GitHub provider with
`--mcp-github`. When enabled, nanoAgent starts the official GitHub MCP server through Docker using
stdio transport, discovers remote tools with `tools/list`, and exposes them to the agent with
namespaced local names such as `github__search_repositories`.

| Environment Variable | Default | Description |
|------|------|------|
| `GITHUB_MCP_DOCKER_IMAGE` | `ghcr.io/github/github-mcp-server` | Docker image used for the official GitHub MCP server |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | required | Token passed to the MCP server process |
| `GITHUB_TOOLSETS` | `context,repos,issues,pull_requests` | GitHub MCP toolsets to expose |
| `GITHUB_READ_ONLY` | `1` | Keep GitHub MCP operations read-only by default |

For GitHub Actions smoke tests, store the token as the repository secret
`MCP_GITHUB_PERSONAL_ACCESS_TOKEN`; GitHub does not allow custom secret names that start with
`GITHUB_`.

---

## 🧪 Development

```bash
# Run all tests
.venv/bin/python -m pytest -q

# Run a single test file
.venv/bin/python -m pytest -q tests/test_agent_loop.py

# Run tests matching a keyword
.venv/bin/python -m pytest -q -k "compaction"

# Lint
.venv/bin/python -m ruff check .

# Syntax check
.venv/bin/python -m compileall -q nano_agent tests
```

GitHub Actions includes two workflows:

- `.github/workflows/ci.yml` runs compile checks, unit tests, and Ruff on pushes and pull requests.
- `.github/workflows/github-mcp-smoke.yml` is manual-only and exercises the GitHub MCP integration
  when the required secret is configured.

### Testing Approach

Tests use mock LLM clients (e.g., `OneToolUseLLM`, `ScriptedMvpLLMClient`) that produce
deterministic, scripted responses — no real API calls needed. Test files mirror the source
module layout under `tests/`.

### Run Artifacts

Each run stores artifacts under `.nano/runs/<run_id>/`:

```
.nano/runs/20240601120000/
├── summary.json              # Machine-readable run summary
├── messages.jsonl            # Full append-only conversation stream
├── prompt.json               # Prompt assembly metadata
├── report.md                 # Structured final report
├── llm_calls.jsonl           # Per-call LLM metrics (optional)
├── audit.jsonl               # Tool call audit trail (optional)
├── context_checkpoint.json   # Latest active context snapshot (optional)
├── compactions.jsonl         # Compaction event records
├── tasks/                    # Persistent task snapshots
├── subagents/                # Subagent execution artifacts
├── tool-results/             # Persisted large tool outputs
└── transcripts/              # Full conversation copies before compaction
```

---

## 🔄 How It Works

```
User request → Prompt assembly → LLM call
                    ↑                ↓
             Context compaction   Tool use?
                    ↑              ↓ yes    no → finish_run → report.md
             Tool results ← Execute tools
                    ↓
           Append to history → Next LLM call
```

1. **Prompt Assembly** — stable core prompt + skill catalog + retrieved memories + user task
2. **LLM Reasoning** — if the model returns `tool_use`, parse the requested tool and arguments
3. **Pre-Tool Hooks** — permission checks, audit logging
4. **Tool Execution** — run the tool in the isolated environment, capture the result
5. **Post-Tool Hooks** — metrics recording, progress display
6. **Context Compaction** — if approaching the token budget, apply progressive compaction
7. **Result Injection** — append tool output to conversation history, continue the loop
8. **Termination** — the model calls `finish_run` with a structured completion report

### Async Execution Model

nanoAgent's production control flow is async-first:

- `NanoAgent.run()` and `AgentLoop.run()` are async entry points.
- LLM providers use async network clients.
- Runtime tools and hooks expose async interfaces.
- `run_command`, repository cloning, and runtime environment setup use async subprocess APIs.
- Safe tool calls from the same LLM response can run concurrently while preserving tool-result order.
- Background subagents are scheduled as `asyncio.Task` instances with independent contexts,
  compactors, message stores, and cancellation tokens.
- Task state and background job state are serialized with `asyncio.Lock` boundaries.
- MCP stdio servers are started with async subprocess transport; MCP sessions run through async
  initialize, tool discovery, tool calls, and shutdown.

Some file-backed stores and filesystem-heavy tools still use `asyncio.to_thread()` around
synchronous atomic writes or directory/file scanning. This is intentional where Python has no
native cross-platform async file API and where preserving atomic write semantics matters.

---

## 🎯 Design Principles

- **Evidence-Driven** — every conclusion must be backed by tool output; no guesswork
- **Minimal Change** — fix only the root cause; skip unrelated refactors
- **Verifiable** — every change must be confirmed by test or command output
- **Graceful Degradation** — compress context progressively rather than truncating abruptly
- **Resilience by Default** — network jitter, model overload, and output truncation all have recovery paths

---

## ⚠️ Current Limitations

- Only DeepSeek is supported as an LLM provider (via OpenAI-compatible protocol)
- Subagents are limited to one level of delegation (children cannot create grandchild agents)
- MCP provider registration is currently explicit; the CLI exposes GitHub MCP only
- Token estimation uses a conservative character ratio, not a real tokenizer
- Cache behavior depends on the provider's implementation details
- Background jobs have no process-restart recovery

---

## 📄 License

MIT
