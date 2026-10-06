# MCP Commander Sprint Checkpoint — 2026-10-06

Branch scope: `nebius-personal-ai` only. AIOA `main` remains untouched.

## Live transport verification

The private GitHub Task Bus is working end-to-end from ChatGPT to the local Commander worker and back.

Verified READ operations completed through the local Policy Gateway:

- `system.status` — PASS
- `git.status` — PASS; local Commander branch observed as `phase04r-read-expansion-effect-auth`, dirty
- `git.branches` — PASS
- `artifact.list` — PASS
- `git.diff` — PASS; bounded summary returned, full diff retained as local artifact
- `git.log` — PASS

All remote READ results returned compact `aioa-mcp-result` envelopes. No changed files were reported by the remote executor.

## AIOA/GitHub-side work completed

- Added strict parser for `MCP-COMMANDER-CLAIM/v1` comments.
- Worker claim is explicitly classified as `TRANSPORT_EVIDENCE_ONLY`.
- Claim objects cannot authorize effects.
- Added regression tests for forged approval fields, invalid hashes and invalid worker identity.
- Added `MCP_Server/LIVE_E2E_STATUS.md`.
- Extended branch-only CI with transport-claim trust-boundary tests.
- Latest MCP Nebius Bridge CI: SUCCESS.

## Local Codex coordination

The local Commander worktree is currently on branch `phase04r-read-expansion-effect-auth` and was observed dirty during the sprint. That indicates Codex is actively changing the standalone Commander. This sprint deliberately avoided local source writes to prevent conflicts.

## Current safety boundary

- GitHub = untrusted transport only.
- ChatGPT/GPT = planner/orchestrator.
- Local Policy Gateway = admission boundary.
- Worker claim = lease/evidence only.
- Live remote path = READ-only.
- `WRITE_LOCAL` and `EXEC_LOCAL` remain disabled for autonomous remote execution.
- Human approval remains the only future effect authority.

## Next checkpoint

After Codex finishes Phase 04R, compare its final report and clean commit against this live transport evidence, then decide whether to enable additional bounded READ operations such as `fs.list`, `fs.read`, `fs.search` and `artifact.get` for routine remote inspection.


## Sprint continuation — bounded READ expansion

Additional live READ operations were exercised through the private control mailbox:

- `fs.list` — PASS
- `fs.stat` — PASS
- `fs.read` — PASS
- `fs.search` — PASS
- `artifact.get` — PASS with bounded metadata and content range returned
- `approval.status` with `{}` — controlled FAIL: `INVALID_ARGUMENTS`

The `approval.status` failure is treated as contract evidence, not a worker fault. Its payload schema is now classified as unverified on the planner side and must not be guessed.

### Planner-side READ payload guard

Added a strict planner-side validation layer for verified READ payloads. It preserves existing compatibility such as optional boolean `git.status.short`, bounds numeric read parameters, blocks project-root escapes, validates artifact UUIDs, and rejects unverified READ schemas before they reach GitHub transport.

Unverified planner READ schemas currently blocked:

- `approval.status`
- `patch.propose`
- `provider.status`
- `provider.models`

CI initially detected a backward-compatibility regression in the new guard (`git.status {"short": ...}`). The failure was diagnosed from GitHub Actions job logs, fixed, and verified green.

Latest verified CI in this sprint:

- run #25 — SUCCESS
- run #26 — SUCCESS on Python 3.11 and 3.12

### Worker ownership decision

Question `[MCP-QUESTION] ... Single worker launcher ownership` was resolved with Option A:

- one phase-owned patched READ-only worker,
- preserve PID/start-ticks single-worker lock,
- no systemd/supervisor changes,
- `WRITE_LOCAL=false`,
- `EXEC_LOCAL=false`,
- GitHub remains transport only.

### Pending local discovery

Task `task-sprint-search-approval-schema-001` remains open in the private mailbox. It is a READ-only `fs.search` intended to discover the exact local `approval.status` schema. It has not yet been claimed. The hourly sprint monitor should resume this discovery when the worker resumes polling.

No AIOA `main` changes were made.


## Sprint continuation — artifact pagination hardening

The live worker confirmed additional bounded-artifact behavior:

- `artifact.get` with `max_bytes=1200`, `max_lines=30` -> controlled `INVALID_ARGUMENTS`
- `artifact.get` with `max_bytes=400`, `max_lines=12` -> PASS
- planner-side bounds were tightened to the live-verified values `400/12`
- CI runs #29, #30 and #31 -> SUCCESS

The search artifact for `approval.status` was successfully produced and the first bounded page showed documentation hits. It also returned `next_offset=400`, which provides evidence that the local artifact contract supports pagination semantics.

Pending task:

- Issue #43: paginated `artifact.get` with `offset=400`, `max_bytes=400`, `max_lines=12`
- do not create a duplicate while #43 remains open
- after PASS, use the returned source hit to read the exact local `approval.status` implementation and only then verify its payload schema

Remote WRITE/EXEC remain disabled. AIOA `main` remains untouched.
