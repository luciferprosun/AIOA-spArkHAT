# Muse → Core → GitHub integration candidate

This candidate extends the existing Native composition. It is not a LIVE
acceptance receipt and must not replace the running Native before exact-SHA CI
and controlled owner-approved deployment. Main is unchanged. The running chat
repair is `16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd`.

## Implemented path

The 6 November follow-up adds fixed code/demo README context, exact binding from
the original model request and canonical provider receipt to the signed demo
READ, lease/session invalidation, bounded serialized chat history and private UI
cleanup. It also accepts GitHub's current opaque installation-token format.
These are candidate source changes, not a production deployment or a LIVE
WRITE receipt. The existing executor, state, policy and credential scope remain.

1. The existing Muse provider records a complete successful LIVE reply. Native
   verifies its current source/capsule, provider receipt and response digest.
   Partial, historical and manually substituted responses cannot propose WRITE.
2. The existing proposal parser accepts `aioa.muse.github-change.v1`. The source
   request must contain a current signed demo README READ. Core re-reads the
   canonical provider receipt and compares its binding with the cached request;
   projected flags or a pasted JSON reply alone cannot establish provenance. Model
   content is data; it cannot choose credentials, permissions, endpoints or grants.
3. Four public GitHub GETs bind the demonstration repository's numeric identity,
   main commit and independently reconstructed complete base tree. Repositories
   with existing Actions workflows require a separate review and are refused.
   Their base/tree must equal the signed context seen by Muse. Context reads
   have six separately bounded GETs through the existing READ-only recipe,
   including reconstructed root-tree/blob hashes and a final main drift check.
4. The existing `git_publish.py` creates an immutable plan with exact new files,
   full diff, content hashes, predicted tree/commit SHA, commit identity, branch,
   draft PR, source evidence, policy epoch and a five-minute review expiry.
5. Mission Control shows the complete review. A deliberate checkbox and button
   authorize that exact digest using the existing admitted PolicyKit owner.
   Chat spending permission does not authorize GitHub.
6. Existing Core warrant, governor, intent/outbox and ServiceGuard perform an
   atomic USD0/risk-reserved remote START. Any prior UNKNOWN blocks admission.
   A duplicate START cannot mint a credential or release another remote attempt.
7. Native mints a short-lived GitHub App token restricted to repository ID
   `1445911975`, Contents write and Pull Requests write (Metadata read). It
   independently lists token-visible repositories and records public scope proof
   in the same Core ledger. No ambient CLI token is read by this adapter.
8. Each of four create-only steps first commits a durable UNKNOWN marker: Git
   tree, Git commit, new branch ref, draft PR. These Git Data API operations are
   the remote equivalent of publishing the reviewed commit; no shell push is used.
9. Independent GETs verify ref, parent, complete tree, every blob's bytes/hash,
   and PR identity, head/base, title/body and draft/open/unmerged status. Only
   complete evidence settles the Core intent and produces a host-signed receipt.
10. Core records, policy decisions, warrant, scope evidence and receipt persist
    in the existing SQLite audit/outbox. Local history restores operation IDs.
    After restart, explicit reconciliation uses public GET only, without a WRITE
    credential or resurrecting an expired owner warrant.

## Bounded authority

Only `luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026` is writable. A proposal
adds one to four new UTF-8 `.py`, `.md` or `.txt` files under `agent-demo/`, at most
8 KiB each and 16 KiB total. No overwrite, executable mode, symlink, submodule,
workflow, hidden path, force update, direct main write, merge or DELETE exists.
The branch is `aioa/muse-<operation-id>`; the model cannot select it. The exact
owner warrant expires within both the review window and the current owner lease.

The executor permits at most 48 API requests and 120 seconds per dispatch.
Credential mint/scope verification has two separately bounded requests. Proposal
reads have four requests and a shared 40-second deadline. No automatic network
retry is performed, including for POST, 401/403, rate limits and timeouts. A new
owner-approved operation mints a fresh token; an in-flight mutation is never
replayed after refresh. Expired credentials stop before the next request.

STOP cancels existing transport, persists the stop flag and revokes any recorded
warrant. The stop flag cannot be overwritten by a late worker. Already released
effects remain UNKNOWN until independent evidence; STOP does not imply undo.
One verified Muse turn is bound durably to one operation, including repeat parse
requests with different browser-generated IDs.

Chat retains the existing 16 KiB serialized provider payload limit. When history
plus the new context would exceed the bounded allowance, it drops the oldest
complete user/assistant pairs before estimating and approving the new request.
JSON escaping is counted. This prevents a later explicit message from failing
solely because escaped earlier replies were counted as raw text.

## Current boundaries and external blockers

`enabled` remains false; local/mock tests do not qualify a LIVE capability.
No demo WRITE, paid Muse call or remote acceptance has been performed by the
implementing assistant. No test PR exists in the demonstration repository.

The existing local `gh` OAuth account is `luciferprosun`. Its broad development
scopes include repo, workflow and delete_repo. It is used for authorized source
development/read audits only, not as a runtime WRITE fallback. The connector's
installation ID `167861143` does not provide a local App private key. Installation
enumeration through the current CLI returned 403; no local App key/config was
found during the metadata audit. Runtime scope is therefore BLOCKED_EXTERNAL.

Two existing Meta financial UNKNOWN reservations remain held. Their original
provider response/usage evidence is unavailable. The existing owner-wide barrier
is preserved. No exception, reset, new scope or parallel governor has been added.

Existing CPL remains explicitly `BLOCKED_NATIVE_CPL_NOT_BOUND`, advisory only.
This change does not invent a CPL certificate or start its five provider calls.
Core policy and exact human approval are real; a LIVE CPL review is not claimed.

Partial remote objects/branch/PR after ambiguous failure are readback-only. If
the full declared result cannot be proven, the operation remains UNKNOWN, even
when only a preflight or credential request failed. Automatic continuation,
no-effect settlement and rollback are deliberately not inferred. A future undo
must be a separately reviewed revert commit/PR with its own warrant; branch
deletion, force push and main updates remain forbidden. This rollback executor
is not implemented in this candidate.

## Acceptance evidence required after deployment

- Exact candidate SHA: required CI PASS, including Core, packaging, JS and the
  isolated hosted browser gate. CodeQL SKIPPED must remain labelled SKIPPED.
- Same SQLite, TLS keys, host identity, pairing records and UNKNOWN retained.
- Genuine owner admission and configured repository-scoped App credential.
- Original UNKNOWN evidence resolved, or a separately analysed/tested policy
  change explicitly approved by the owner. This candidate does neither.
- Owner submits the Muse prompt, reviews the exact generated operation and
  grants its own WRITE warrant. The assistant cannot manufacture this approval.
- One Core-dispatched acceptance yields independently verified commit/PR URLs,
  operation ID, signed receipt and receipt SHA256. Only that proves LIVE WRITE.

Offline tests are intentionally labelled fixtures. In particular the Native
integration test patches a network port on a temporary Core: its signed fixture
receipt is not evidence of an actual GitHub operation.
