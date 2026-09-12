# AU-2 risk evaluation — decision only

```text
AU2_IMPLEMENTED = NO
AU2_GLOBAL_EVENT_CHAIN_IMPLEMENTED = NO
PORTABLE_B4_LOCAL_SNAPSHOT_INTEGRITY = YES
AU2_RISK = HIGH
AU2_RECOMMENDATION = DEFER_UNTIL_AFTER_SUBMISSION
```

This remains the design verdict for a global append-only event chain and is not deployment
authority. B4 separately added a versioned, typed SHA-256 envelope around complete local durable
truth and sandbox snapshots. That detects corruption and ordinary content edits without changing
the canonical `AuditEvent` schema or claiming an externally anchored signature.

## Evidence-backed decision

| Question | Current evidence | Decision signal |
| --- | --- | --- |
| Would AU-2 change `AuditEvent`? | `AuditEvent` has an immutable event identity and redacted payload hash, but no previous-event hash, sequence, or run chain head. Adding those fields directly changes serialized durable records. | Migration and compatibility risk. |
| Would it touch critical paths? | HITL, investigation, remediation, verification, and recovery all append audit events. A chain update would sit on each of those paths. | Demo-stability risk is high. |
| Can it be additive? | A separate versioned chain-head record is possible, but correctness still needs canonical ordering, conditional concurrency control, conflict recovery, omission detection, and an export/query boundary. The current repository reads audit events only by exact identity and its IAM policy has no query or transaction action. | Lower schema risk, but still a new persistence and IAM surface. |
| Are existing gates stable? | P0, P1, deterministic AU-3 evidence, and clean-clone proof are green without AU-2. | Do not disturb the proven boundary. |
| Is near-term reviewer value material? | AU-3 already gives judges deterministic claim-to-source/test/commit traceability. AU-2 would improve event-ledger continuity, but it does not close a blocker for the no-live submission boundary. | Marginal benefit before submission. |

## Why the risk is HIGH

A correct hash chain cannot be added as a cosmetic digest. It must define total ordering, the genesis value, canonical redacted event bytes, atomic head advancement, concurrent-writer behavior, retry semantics, export verification, and migration/backfill rules. An additive design would likely need a separate chain-head key plus a conditional or transactional write that remains consistent with the immutable audit event. That changes the durable append behavior used by recovery and the mutation path.

Implementing only hashes on individual events would not prove continuity or omission resistance and would overstate the result. AU-2 therefore remains unimplemented until after the submission is frozen. A future package must be independently scoped, preserve existing records, add explicit compatibility tests, and re-run P0/P1 before promotion.
