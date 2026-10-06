# Verified READ Payload Contracts

This file records planner-side payloads that have been observed working through
the live private GitHub Task Bus into the local MCP Commander worker.

GitHub remains transport only. These schemas do not grant authority and do not
replace local Policy Gateway validation.

## Verified live READ operations

- `system.status`: `{}`
- `git.status`: `{}`
- `git.branches`: `{}`
- `git.diff`: optional bounded `max_bytes`, `max_lines`
- `git.log`: optional bounded `limit`
- `fs.list`: `path` plus optional bounded `limit`
- `fs.stat`: `path`
- `fs.read`: `path` plus optional bounded `bytes`, `lines`
- `fs.search`: `query` plus optional bounded `max_hits`
- `artifact.list`: `{}`
- `artifact.get`: `artifact_id` plus optional bounded `max_bytes`, `max_lines`

Paths are planner-restricted to project-relative values without `..`.

## Unverified READ schemas

The planner must refuse to emit these until their local payload contract is
observed or documented:

- `approval.status`
- `patch.propose`
- `provider.status`
- `provider.models`

On 2026-10-06, a live `approval.status` task with payload `{}` correctly
failed with `INVALID_ARGUMENTS`. The failure was treated as evidence that the
payload contract must be discovered instead of guessed.

## Current live evidence

A bounded `artifact.get` successfully returned metadata plus an untrusted
content range originating from a prior `fs.read` artifact. This confirms the
ChatGPT -> private GitHub -> local worker -> Policy Gateway -> artifact result
round trip without enabling remote WRITE/EXEC.
