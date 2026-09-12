# Non-Zero Durable Truth

The canonical workflow contracts persist `Run`, `ActionProposal`, `Approval`, `IdempotencyRecord`, `Checkpoint`, and append-oriented `AuditEvent` records. The existing DynamoDB state-table skeleton remains a single table with string `PK`/`SK` keys, no GSI, `PAY_PER_REQUEST`, and item-level `GetItem`, `PutItem`, and `UpdateItem` authority only.

## Invariants Implemented

- Pydantic contracts retain UUIDv7 identities, closed enums, UTC timestamps, budget counters, hashes, authority, and explicit failure values after DynamoDB serialization and reconstruction.
- Runs start at `RECEIVED` version 1. State changes require the expected state/version and the application transition table. Entering `APPROVED` additionally requires a separate durable positive `Approval` for the matching proposal.
- An `ActionProposal` is a write-before-execute object and always remains distinct from approval. Duplicate proposals and decisions are create-only conflicts.
- Semantic idempotency keys derive from the run, typed action, exact sandbox target, precondition, authority, and evidence—not a random UUID alone. Exact duplicates reconcile to the existing record; incompatible ownership fails explicitly.
- Checkpoints preserve a versioned last-safe state, resume metadata, and tool/result hashes. Recovery classification distinguishes new, safe-resumable, awaiting-approval, reconciliation-required, and terminal runs without claiming full recovery execution.
- Audit events are immutable create-only records addressed by UUIDv7 event identity. No overwrite, delete, scan, or table-wide operation exists in the repository contract.
- Storage absence remains distinguishable from provider failure. DynamoDB failures become explicit retryable dependency errors; production code never silently falls back to the test-only in-memory repository.

## Write Before Execute

The durable mechanics support the future sequence `PROPOSE -> durable proposal -> AWAITING_APPROVAL -> durable human APPROVED -> semantic idempotency registration -> EXECUTE -> VERIFY -> durable evidence -> SUCCESS_WITH_EVIDENCE`. The prerequisite loader requires the approved run, awaiting proposal, positive decision, idempotency ownership, and approved checkpoint before a future executor can receive a proof bundle.

This step does **not** implement the EC2 side effect, complete HITL pause/resume, restart reconciliation, production deployment, or end-to-end `SUCCESS_WITH_EVIDENCE`. All validation uses local fakes; no live DynamoDB write or AWS resource mutation occurred.
