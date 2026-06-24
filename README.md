<p align="center">
  <h1 align="center">🤖 nanoAgent</h1>
  <p align="center">
    A lightweight AI Agent for automated repository diagnosis & repair
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/stability-experimental-orange" alt="Stability" />
</p>

---

## 📖 Overview

nanoAgent is a lightweight AI Agent prototype that pulls a GitHub repository, analyzes its
structure, pinpoints root causes, and performs verified fixes — all within an isolated execution
environment. The central idea is to **give the LLM tools and let it work**: it operates inside a
controlled loop, observing, reasoning, and acting until the task is done.

Unlike a one-shot Q&A session, nanoAgent will:

- 🔍 Actively explore the repository structure and search for relevant code
- 🧪 Reproduce test failures and compare against expected behavior
- ✏️ Make precise source changes rather than weakening assertions
- 🔄 Retry on transient errors and compact context when it grows too large
- 📋 Deliver a structured completion report with evidence, risks, and changed files

Current phase: guarded tool-use loops with run persistence, cache-oriented prompt composition,
and bounded one-level subagent delegation.

---

## ✨ Features

| Feature | Description |
|------|------|
| 🧠 **Tool-Use Loop** | LLM requests tools → execute → inject results → continue reasoning until done |
| 🔧 **Rich Built-in Tools** | Repository cloning, file I/O, grep search, shell commands, code editing, task management |
| 📦 **Isolated Runtime** | Per-run venv, sandboxed HOME / TMPDIR / cache directories |
| 🗜️ **Multi-Layer Compaction** | Budget → Snip → Micro → LLM summary → Reactive, five-tier progressive reduction |
| 🔄 **Resilient Recovery** | Exponential backoff for transients, bounded continuation for truncation, correction for invalid tool calls |
| 🔌 **Extensible Hooks** | Permission, audit, metrics, skill injection — composable at each loop boundary |
| 👥 **Subagent Delegation** | Synchronous & background task delegation, up to 2 concurrent read-only subagents |
| 📋 **Persistent Task Tracking** | Dependency graph (`blocked_by`), lifecycle state machine, background Job linkage |
| 📝 **Structured Reports** | Every run produces `report.md` with problem, root cause, changed files, verification, and risks |
| 🎯 **On-Demand Skills** | Built-in Python / Node / Django / GitHub Actions domain skills, activated by the model when needed |

---

## 🚀 Quick Start

### Prerequisites

- Python ≥ 3.11
- DeepSeek API key ([get one here](https://platform.deepseek.com))

### Installation

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

### Usage

```bash
# Basic: diagnose and fix a repository
python -m nano_agent.cli run https://github.com/user/repo \
  "Fix the failing tests in test_login.py"

# Enable writes and command execution
python -m nano_agent.cli run https://github.com/user/repo \
  "Refactor error handling in utils.py" \
  --allow-write --allow-command

# Custom step count and background timeout
python -m nano_agent.cli run https://github.com/user/repo \
  "Run the full test suite and fix every failure" \
  --max-steps 200 --background-idle-wait-timeout 120
```

When the run finishes, the terminal prints a compact summary. The full report lives at
`.nano/runs/<run_id>/report.md`.

---

## 📁 Project Structure

```
nano_agent/
├── agent.py              # Top-level entry point — wires components and launches the loop
├── loop.py               # Core tool-use loop engine with full error recovery
├── cli.py                # Typer CLI entry point
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
│   ├── manager.py        #   Subagent creation & synchronous execution
│   ├── context.py        #   Subagent context builder
│   ├── models.py         #   Subagent data models
│   └── store.py          #   Subagent state persistence
├── background/           # Background job scheduling
│   ├── supervisor.py     #   Thread-pool scheduler with bounded concurrency
│   ├── hook.py           #   Completion notification hook
│   ├── cancellation.py   #   Cooperative cancellation token
│   └── store.py          #   Job snapshot persistence
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

---

## 🧪 Development

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_agent_loop.py

# Run tests matching a keyword
pytest -k "compaction"

# Lint
ruff check .
```

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
├── promt.json                # Prompt assembly metadata
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
- Token estimation uses a conservative character ratio, not a real tokenizer
- Cache behavior depends on the provider's implementation details
- Background jobs have no process-restart recovery

---

## 📄 License

MIT
