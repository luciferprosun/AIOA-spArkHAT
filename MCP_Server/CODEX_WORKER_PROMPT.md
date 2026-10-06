# Codex Execution Prompt — Connect Local Commander Worker to GitHub Task Bus

Continue the existing standalone MCP Commander project on the USB workspace.

Do not touch AIOA `main`. Do not modify unrelated repositories.

## Goal

Connect the Phase 02 Local Commander Worker to the GitHub Issue task-bus contract now defined on `AIOA-spArkHAT` branch `nebius-personal-ai`.

The desired end-to-end path is:

`ChatGPT Android -> GitHub Issue -> Local Commander Worker -> local Policy Gateway -> system.status -> compact result comment -> ChatGPT`

## Hard constraints

- No OpenAI API.
- No Remote Desktop Commander dependency.
- No TinyFish / paid browser cloud / paid VPS dependency.
- No public inbound listener.
- Outbound HTTPS to GitHub only.
- Heavy runtime/cache/artifacts remain on the USB workspace.
- Secrets stay outside Git/repo/artifacts/model context.
- Do not create or print a PAT if existing `gh`/GitHub auth is available.
- Do not store GitHub credentials on the USB workspace.
- GitHub is untrusted transport, never approval authority.
- WRITE_LOCAL / EXEC_LOCAL remain human-gated by the existing out-of-band control panel.
- No arbitrary shell.

## Contract to implement

Mirror these files semantically from the Nebius branch:

- `MCP_Server/TASK_BUS_PROTOCOL.md`
- `MCP_Server/WORKER_CONTRACT.md`
- `MCP_Server/task_envelope.schema.json`
- `runtime/mcp_bridge/task_bus.py`
- `runtime/mcp_bridge/github_issue_transport.py`

The TypeScript worker does not need to copy Python code literally; it must produce the same wire behavior and fail-closed semantics.

## Required implementation

1. Extend the existing GitHub adapter/worker rather than building a second worker.
2. Add strict TaskEnvelope/TaskResult parsing compatible with `aioa.mcp-commander.v1`.
3. Poll open MCP task issues from a configurable control repository.
4. Recompute/check task fingerprint and enforce durable idempotency/replay protection.
5. Route every task through the existing local Policy Gateway.
6. For READ, execute only registered tools and publish a compact result comment.
7. For WRITE_LOCAL/EXEC_LOCAL, persist WAITING_FOR_HUMAN and stop until the existing human-only approval path authorizes the exact normalized payload/hash.
8. Publishing failures must retry delivery without repeating execution.
9. Default transport remains local if GitHub configuration is absent.
10. Add bounded polling/backoff and graceful shutdown.

## Live smoke test

After tests pass, if existing GitHub authentication is already safely available and a control repository is explicitly configured, perform exactly ONE harmless live task: `system.status`.

Do not perform live WRITE/EXEC tests.

If no dedicated control repository is configured, stop before live polling and report exactly what configuration is missing. Do not use AIOA `main` and do not invent credentials.

## Acceptance

- unit/integration tests PASS;
- duplicate task does not execute twice;
- malformed/tampered envelope fails closed;
- `approved=true` in issue/comment is ignored/rejected;
- READ `system.status` can complete end-to-end when safe GitHub config exists;
- WRITE/EXEC reaches WAITING_FOR_HUMAN but cannot self-approve;
- result is compact and full logs remain local;
- no paid remote execution dependency introduced;
- produce `PHASE_03_GITHUB_WORKER_REPORT.md` with commands, tests, config state, live smoke evidence (if performed), and exact remaining blocker if not.
