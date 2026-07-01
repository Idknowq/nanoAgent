# Getting Started

## Requirements

- Python 3.11 or newer. CI currently runs on Python 3.13.
- A DeepSeek API key.
- Docker only if you enable GitHub MCP.

## Install

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Configure

```bash
cp .env.example .env
```

Set the required LLM environment variables:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

## Run

Read-only analysis:

```bash
nano-agent run https://github.com/user/repo \
  "Inspect the repository and explain why the tests fail"
```

Allow source edits and command execution:

```bash
nano-agent run https://github.com/user/repo \
  "Fix the failing tests" \
  --allow-write --allow-command
```

## Output

Each run writes artifacts under `.nano/runs/<run_id>/`:

- `report.md`: user-facing final report
- `summary.json`: machine-readable run summary
- `messages.jsonl`: append-only conversation stream
- `audit.jsonl`: tool-call audit trail when enabled
- `llm_calls.jsonl`: LLM call metrics when enabled
- `tasks/`: persisted task snapshots
- `subagents/`: background subagent artifacts

## Common Failures

- Missing `DEEPSEEK_API_KEY`: set it in `.env`.
- `nano-agent` not found: run `pip install -e .` inside the virtual environment.
- Tool call denied: add `--allow-write` or `--allow-command` only when the task requires it.
- GitHub MCP fails to start: check Docker, token configuration, and `GITHUB_READ_ONLY`.
