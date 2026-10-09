# NIGHT SPRINT — MCP / Nebius integration

Branch: `nebius-personal-ai` only. `main` remains frozen and untouched.

## Completed

- Created `MCP_Server/` integration workspace.
- Added strict MCP task/result contracts with lifecycle and idempotency fingerprinting.
- Added deny-by-default policy with READ / WRITE_LOCAL / EXEC_LOCAL / DESTRUCTIVE / OPEN_WORLD separation.
- Added AIOA observation adapter; Commander results are always `ADVISORY_ONLY` and cannot authorize effects.
- Added portable JSON task schema.
- Added GitHub task-bus Markdown/JSON codec.
- Added transport protocol documentation.
- Added authority projection compatible with AIOA/NonZero semantics without optional dependencies.
- Added branch-only GitHub Actions contract CI for Python 3.11 and 3.12.
- Verified ChatGPT Android session can create a GitHub task issue, read it back, post a compact result, and close it without Remote Desktop Commander or OpenAI API.

## Proven transport milestone

`ChatGPT Android -> GitHub mailbox -> result back to ChatGPT` is now proven at the connector layer.

GitHub remains transport only, never policy authority. Human approval is still out-of-band and cannot be carried by issue text or comments.

## Not activated yet

- No local PC worker has been pointed at the live GitHub mailbox yet.
- No arbitrary shell or browser execution has been enabled.
- No live Nebius inference call has been performed by this bridge.
- No AIOA `runtime/main.py` wiring has been added.
- No changes have been made to `main`.

## Next safe step

Configure the existing standalone MCP Commander worker to consume the same v1 task envelope and point it at a dedicated control channel. Run one harmless `system.status` or `git.status` end-to-end task. Only after that, attach the bridge to AIOA admission and then enable Nebius specialist calls under explicit policy.
