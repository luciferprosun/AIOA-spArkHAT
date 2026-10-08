# Native dual cost/risk governor — local scope

The Block 07 candidate extends the existing CoreAdmission, TransactionRunner,
insert-only OPERATION journal and native AuditEvent/Outbox. It creates no store,
principal, provider manager, effect warrant or worker permission. Host composition
supplies immutable policy and an admitted Core principal; model/task text cannot
change limits, start an epoch or control the kill switch.

## Accounting and boundaries

Money is integer nanoUSD; risk is an integer operational allowance, **not a
probability**. Both dimensions are checked and reserved in the same serializable
transaction at task, owner/provider and global levels. Global means all tasks and
providers within the supported **single-owner Core namespace**. Hosted cross-owner
accounting remains OPEN. Full reserved bounds count cumulatively for the policy
lifetime, including settled charges; there is no automatic reset or refund.

`RESERVED → DISPATCHED → COMMITTED` records an acknowledged local dispatch marker
and pessimistic full-bound charge. `UNKNOWN` retains both dimensions. A release
requires current durable RESERVED state and emits a no-dispatch certificate in
the same transaction. DISPATCHED/UNKNOWN cannot be refunded or sent again.
Reserve/marker ACK loss never grants send permission. READ and receipt-only
reconciliation remain available under kill. Verified target receipt replay can
finish interrupted accounting without repeating the target operation.

The local dispatch-marker transaction is the bookkeeping linearization point.
It re-reads current epoch, kill, circuit and exposure. It is **not an atomic
database/HTTP transaction**: a kill after this committed boundary cannot cancel
an in-flight effect, refund it or license a retry. ServiceGuard still consumes
its original human-bound effect handle and rechecks current consent, revocation,
expiry and target state at its original target boundary. Governor approval is
never human approval.

## Explicit composition and compatibility

`GovernorBinding` is host-only composition. The existing Nebius port reserves an
exact native ProviderRequest digest and upward integer cost bound before its
transport. Prices/ceiling use bounded rational arithmetic independent of mutable
Decimal context. ProviderResponse settlement binds the complete native response
digest without storing content. Known no-transport denials retain the existing
ProviderError contract and release legacy LITE units; ambiguous ACKs remain UNKNOWN.

ServiceGuard optionally shares this same Core/runner and reserves effect risk
before durable intent. Its human authority and target-native deduplication remain
required. Existing **unbound** provider/guard composition preserves its prior
behavior; this checkpoint does not claim every legacy path is governed. The
unified opt-in reviewer path is a later convergence stage, not a live default.

New ServiceGuard namespaces use the existing native audit chain. An existing raw
SERVICE_GUARD namespace continues its original append-only format after validating
its record bindings. Historical rows are not rewritten. Governor adoption of that
legacy namespace fails closed and needs a separately designed migration. Mixed
legacy/native namespaces are rejected. Native audit timestamps are nondecreasing
journal ordering stamps, **not database commit times or authority clocks**.

## Recovery and limits

Kill is an operator policy barrier; per-provider CLOSED/OPEN/HALF_OPEN circuits
use failure threshold, cooldown and multiple recovery successes. One HALF_OPEN
probe is admitted at a time; restart takeover preserves exposure and opens an
unfinished probe. UNKNOWN reconciliation does not count as recovery success.
Unsafe clock movement blocks new admission/dispatch, while READ and kill
activation remain available. Explicit admitted operator epoch takeover provides
forward-clock recovery; it never erases reservations or changes limits.

History is bounded and fails closed: fewer than 1024 scoped OPERATION rows,
at most 128 reservations and 32 providers. There is no automatic compaction or
retention deletion. A full/corrupt history needs operator review. Native port
tests use repository-supported durable and transaction-fault fixtures; they do
not certify a newly deployed CockroachDB, distributed fencing or external
exactly-once execution. Production signer custody remains OPEN.

## Verification claims

PRV scope is bounded local fixtures and actual native contracts. Tests cover
paired boundaries/overflow, concurrent reserve, idempotency, restart and ACK
loss, time skew, kill/revocation/stale epoch, UNKNOWN exposure, half-open recovery,
native/legacy audit compatibility, governed offline Nebius and one disposable
target. The candidate evidence is external and records failed/RED observations
separately. Full candidate/CI/cloud/LIVE readiness require their own gates.

LIVE WRITE/EXEC remains disabled. MCP stays external and READ_ONLY. No provider
network call, deployment, main integration or production key custody is implied.
