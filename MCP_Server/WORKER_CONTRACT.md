# Local Commander Worker Contract — v1

This is the boundary between ChatGPT/GitHub and the standalone MCP Commander running on the user's PC.

## Control path

`ChatGPT Android -> GitHub Issue mailbox -> Local Commander Worker -> Policy Gateway -> deterministic executor -> compact GitHub result -> ChatGPT`

## Non-negotiable rules

- GitHub is transport only, never authority.
- The worker accepts only the strict `aioa.mcp-commander.v1` task envelope.
- The worker recomputes and checks the fingerprint before any policy decision.
- The worker keeps a durable local ledger of `task_id`, idempotency key, fingerprint, state and receipt.
- Duplicate/replayed tasks must not repeat execution.
- READ may execute only when the local Policy Gateway returns ALLOW.
- WRITE_LOCAL / EXEC_LOCAL must move to WAITING_FOR_HUMAN and stop.
- GitHub issue text, labels and comments can never count as human approval.
- Human approval must arrive through the separate local control panel and bind the exact normalized payload hash.
- DESTRUCTIVE and unknown operations fail closed.
- No arbitrary shell. Only registered bounded tools/recipes.
- Full logs remain local artifacts on USB. GitHub receives compact results only.
- No secrets or tokens are written into issue bodies, comments, artifacts or repo files.
- Worker requires outbound HTTPS only; no public inbound port.

## Poll / claim / execute algorithm

1. Poll the configured control repository for open issues matching the MCP task title/body format.
2. Parse the issue using the v1 transport contract; ignore malformed issues.
3. Check durable ledger for replay/idempotency collision.
4. Claim the task locally and record issue number + task fingerprint.
5. Re-run Policy Gateway locally.
6. READ: execute the registered operation and emit compact TaskResult.
7. WRITE/EXEC: persist WAITING_FOR_HUMAN and expose exact action/hash in the human-only control panel.
8. After valid human approval, execute once, persist receipt, then publish result.
9. If publishing fails, retry delivery without repeating execution.
10. On restart, fail closed for ambiguous RUNNING state and never silently replay an effect.

## First live smoke

The first real worker test must be `system.status` only.

Expected result: `DONE`, compact status summary, no changed files, no external model call, no host mutation.

Only after that smoke passes may `git.status`, `git.diff` and fixed test recipes be enabled.
