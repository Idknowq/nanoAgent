# Architecture

## Runtime Flow

```text
CLI
  -> NanoAgent
  -> AgentLoop
  -> LLM call
  -> tool calls
  -> hooks
  -> persistence
  -> report
```

`NanoAgent.run()` creates the run context, workspace, tool registry, hooks, stores, optional MCP runtime, and then starts `AgentLoop.run()`.

## Agent Loop

The loop follows a tool-use protocol:

1. Prepare active messages and tool specs.
2. Call the LLM.
3. Validate and execute requested tools.
4. Append tool results in the original `tool_use` order.
5. Repeat until the model calls `finish_run` or a limit is reached.

Safe tools from the same LLM response may run concurrently. Mutating tools are serialized.

## Tools and Hooks

Runtime tools implement async `run()` methods and return structured `ToolResult` values. Hooks wrap important boundaries:

- before and after LLM calls
- before and after tool calls
- error handling

Built-in hooks handle permissions, audit logs, console progress, metrics, skill injection, and background completion notices.

## Context Compaction

Context compaction keeps long runs within the input budget. It combines:

- large tool-result persistence
- snip compaction
- micro compaction
- LLM-backed summary compaction
- reactive compaction after provider limits

The active checkpoint is persisted so run artifacts remain inspectable.

## Tasks and Subagents

The task system stores persistent task records with status, owner, dependencies, result, and error fields. Background subagents run as `asyncio.Task` instances with bounded concurrency and cooperative cancellation.

Subagents are intentionally one level deep. They receive a scoped prompt, use read-only repository tools by default, and return a structured result to the parent loop.

## Persistence

Run artifacts are file-based and append-friendly. Important files include:

- `messages.jsonl`
- `summary.json`
- `prompt.json`
- `report.md`
- `audit.jsonl`
- `llm_calls.jsonl`
- `context_checkpoint.json`
- `compactions.jsonl`

Some file operations still use `asyncio.to_thread()` where Python lacks native cross-platform async file APIs or where atomic write semantics must be preserved.
