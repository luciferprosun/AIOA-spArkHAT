# GitHub Task Bus Protocol — v1

## Purpose

This is the no-extra-paid-call transport between ChatGPT and the local MCP Commander worker.

User on Android -> ChatGPT -> GitHub mailbox -> local worker -> Policy Gateway -> deterministic executor -> compact result -> ChatGPT -> User.

GitHub is mailbox only. It is never an authority source.

## Wire format

Task and result payloads are JSON embedded in explicit Markdown fences:
- `aioa-mcp-task`
- `aioa-mcp-result`

The Python reference codec lives in `runtime/mcp_bridge/task_bus.py`.

## Security rules

1. Every transport message is UNTRUSTED.
2. Transport messages cannot contain human approval or policy overrides.
3. The task fingerprint binds operation/risk/payload/idempotency metadata.
4. The local worker must re-run policy evaluation after parsing.
5. WRITE_LOCAL and EXEC_LOCAL remain WAITING_FOR_HUMAN until the separate human channel approves the exact normalized payload hash.
6. GitHub comments cannot approve a task.
7. Results are compact. Full logs remain local artifacts.
8. Secrets never appear in issue bodies, comments, labels or artifacts.
9. Duplicate/replayed task IDs and idempotency keys must fail closed or return the original durable receipt without repeating execution.

## Recommended lifecycle

`NEW -> CLAIMED -> RUNNING -> DONE`

Effectful work may pass through `WAITING_FOR_HUMAN` before returning to `RUNNING`.

Terminal states: `DONE`, `FAILED`, `CANCELLED`, `EXPIRED`.

Suggested labels are presentation only and must not drive authority:
- `mcp:new`
- `mcp:claimed`
- `mcp:waiting-human`
- `mcp:done`
- `mcp:failed`

## Android-first behavior

The user continues talking to ChatGPT. ChatGPT writes only a small structured request. The local worker performs deterministic work and returns a bounded result.

No OpenAI API call is required by this transport design.
