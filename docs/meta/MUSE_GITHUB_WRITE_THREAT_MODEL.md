# Native GitHub WRITE threat model

Status: design for offline implementation; production dispatch is not enabled.
This document does not authorize a new remote operation or change liability
policy. See `MUSE_GITHUB_WRITE_GAP_ANALYSIS.md` for verified source boundaries.

## Authority and trust boundaries

The model supplies proposed content only. Its successful, complete LIVE receipt
and content digest must match the current admitted source. A truncated reply,
historical reply, manually substituted JSON, repository README instruction or
MCP annotation cannot approve a tool. Core validates the proposal independently.

The owner reviews the exact operation, repository name AND ID, base commit,
new branch, every path and complete UTF-8 content, commit message and draft PR
title/body. A separate exact digest-bound warrant expires within the existing
owner admission. An unlimited chat money allocation grants no remote authority.
The same Core, governor, warrant ledger, intent journal, audit and outbox remain
authoritative. The Native source/capsule, revocation, kill and deadline checks
are repeated immediately before release of each approved remote step.

Credentials stay in native private storage, never model context, browser state,
command arguments, remote content, diagnostics or public receipts. Only an
installation credential or fine-grained PAT limited to repository ID 1445911975
with Contents write and Pull Requests write is eligible. A broad development
`gh` token is not a fallback. Credential scope must be established explicitly;
a successful public repository GET alone does not prove token restriction.

## Remote object and reference strategy

Prefer immutable Git Data objects and a create-only final ref to updating a
branch through the Contents API. Explicit parent and tree binding avoid a
concurrent branch update silently becoming a different commit parent. Reuse
existing Git object hashing and plan/diff machinery where applicable.

Only `aioa/muse-<new-operation-id>` may be created, with a known immutable parent.
Every file is new, ordinary mode 100644, bounded UTF-8, under `agent-demo/`.
Reject traversal, absolute paths, ambiguous separators, control characters,
symlinks, submodules, executable modes, duplicate/prefix-conflicting paths,
hidden/auto-load locations and any existing target. No PATCH/update ref, force,
reset, main modification, workflow/settings mutation or merge operation exists
in the transport allowlist. Model data cannot select hosts or endpoint paths.

All remote writes, including unreachable preparatory Git objects, are declared
in the reviewed operation. A draft PR may be created only after commit/ref/files
were independently verified. It is verified again using a separate PR GET.

## Ambiguity, replay and restart

The existing atomic START consumes the exact warrant, reserves risk, writes the
intent and holds its outbox before any network mutation. A versioned remote
zero-currency contract is necessary; do not impersonate a local network-OFF
operation. Per-step durable state must precede network writes. Network code
must execute outside retryable database callbacks. No transport retry loop.

Any lost ACK, timeout, 409, 422, 429, 5xx or malformed response stops further
mutations. Partial remote objects or a created branch remain retained UNKNOWN
until independent readback proves the declared effect. Missing evidence does
not prove no effect. Restart and duplicate operation IDs permit readback only;
they never recreate a dispatch marker. No cleanup DELETE is implicitly allowed.

Independent GET verifies exact ref name, commit SHA, parent, complete tree/modes,
blob bytes/manifest and PR head/base/repository/draft identity. Prefix-matching
refs, truncated trees, model-supplied links and the mutation ACK are insufficient.
Only then may Core reconcile and sign its durable receipt with the existing
host identity. A host-signed receipt does not imply a GitHub GPG-signed commit.

## Current owner-wide liability barrier

At audit time governor version 43 / epoch 15 retained six COMMITTED and two
UNKNOWN reservations. The original `chat-spend-f15ea88b5afb499e980356edfa312dfd`
holds 0.0040435 USD; the owner-submitted 03:18 request
`chat-spend-f2749c92a43b1ed7697b271162c8bb55` holds 0.0092485 USD. These are
reservation bounds, not invoices. Seven uncertain chat/provider/read records
and both paired-device records were preserved. No original provider response,
usage or provider completion ID was retained for either incomplete response.

The documented Meta Responses retrieval API does not establish a receipt for
these original Chat Completions requests. No independent resolution has been
found or applied. Current result: `BLOCKED_OWNER_LIABILITY_UNKNOWN`.

This implementation must not introduce an unrelated-effects exception. Such a
policy would be a separate change with its own analysis, tests and informed
owner decision. A new scope, governor, epoch, host, UID or database is not a
valid way to make the current operation pass.

## Required negative tests

Test exact source/expiry/grant/diff/repository mismatches; forged model authority;
path and file-mode attacks; key echo; base/ref races; incomplete or forged GET
evidence; lost response before/after every mutation; duplicate/restarted requests;
credential absence/overscope; 401/403/409/422/429/5xx; cancellation and revocation;
old UNKNOWN and unresolved intent barriers; and receipt restart verification.
All development transports are isolated fixtures with network disabled.

## Primary references

- [Git trees](https://docs.github.com/en/rest/git/trees): explicit tree modes,
  `base_tree` semantics, bounded complete tree reads.
- [Git commits](https://docs.github.com/en/rest/git/commits): immutable parent/tree
  construction and distinction between content evidence and GPG verification.
- [Git references](https://docs.github.com/en/rest/git/refs): exact-ref lookup and
  create-only reference operation.
- [Pull requests](https://docs.github.com/en/rest/pulls/pulls): draft PR creation
  and independent head/base verification.
- [Installation repositories](https://docs.github.com/en/rest/apps/installations):
  installation credential repository scope observation.
- [Meta API reference](https://dev.meta.ai/docs/api-reference) and
  [Chat Completions schema](https://dev.meta.ai/docs/api-reference/chat-completions/schemas):
  endpoint distinction and finish reason semantics.
