# Day 11 — Restart-Safe Recovery and Reconciliation

`RecoveryCoordinator` is an internal deterministic service, not a sixth Strands tool. Its input contains only durable `run_id` and optional `proposal_id` references. It reloads Run, ActionProposal, Approval, Idempotency, Checkpoint and VerificationEvidence records before deciding whether to reconstruct HITL, return approved work as ready, resume read-only verification, reconcile a lost acknowledgement or preserve a terminal result. Model or user prose cannot select the recovery action.

Active recovery uses a short versioned checkpoint lease and the repository's conditional write boundary. Concurrent attempts cannot both own the same recovery window; an expired lease can be reclaimed after a process crash. Checkpoints persist only versionable identifiers, state and hashes—never opaque Strands/runtime objects. Every classification, observation, deferral and completion is linked to run, trace, correlation and proposal identity in a redacted AuditEvent.

`RECOVERY_REQUIRED` is deliberately reconcilable only through `VERIFYING`. An unresolved idempotency claim with no executor acknowledgement is never replayed. If the configured exact sandbox target is independently observed as stopped, the approved action can close using a dedicated `RECOVERY_READ_BACK` verification proof without fabricating an AWS acknowledgement. `stopping` is polled within the existing fixed verification budget; `running`, ambiguous, corrupt or unavailable state remains operator-visible and never triggers another stop.

Existing positive approvals and verified results reconcile idempotently after restart. `AWAITING_APPROVAL` reconstructs the exact proposal-bound interrupt. A duplicate semantically identical decision retains the original durable timestamp; a conflicting decision remains rejected.

Day 11 tests use only in-memory/DynamoDB fakes and scoped fake `DescribeInstances` responses. No executor is reachable from the recovery package, no new EC2 write symbol or IAM action was added, and no live AWS read or mutation occurred.
