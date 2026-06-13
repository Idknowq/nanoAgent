# nanoAgent

`nanoAgent` is a lightweight AI Agent prototype for repository diagnosis and small-scope code repair.

Current phase: single-agent tool-use loop with guarded tools, run persistence, and
cache-oriented prompt composition.

Planned MVP loop:

1. Send the user request and current context to the LLM.
2. If the LLM returns `tool_use`, call the requested tool.
3. Append the tool result back into the message history.
4. Continue the loop until the LLM returns `end_turn`.
5. Keep `todo_write` as an optional short-lived session planning tool.
6. Use structured `run_command` execution only when a dedicated tool is insufficient.

Prompt assembly uses a stable Markdown core plus selective skill and memory injection. See
[docs/prompt-architecture.md](docs/prompt-architecture.md).

The active conversation is bounded by tool-result persistence, structural trimming,
micro-compaction, LLM-generated summaries, and a one-shot prompt-too-long fallback. The raw
protocol stream remains available in each run's `messages.jsonl`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## CLI

```bash
nano-agent run https://github.com/example/repo
```

During early development, use:

```bash
python -m nano_agent.cli run https://github.com/example/repo
```
