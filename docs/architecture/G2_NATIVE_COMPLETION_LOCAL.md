# Local native required-task completion (G2 tranche)

This additive route binds declared required work to existing native offline jobs.
It does not enable a provider, executor, background scheduler or remote service.
Ordinary JobEnvelope v1 jobs remain UNVERIFIED advisory bookkeeping: DONE alone
does not mean the user's work completed.

## Supported composition

The trusted admitted host submits a `TaskCompletionBinding` with
`CoreDualGovernor.submit_job(principal, envelope, completion=binding)`. The binding
fixes owner scope, task identity, immutable graph digest, completion candidate and
same-owner `TaskDependency` references before execution. It uses the fixed predicate
`APPLIED_FOR_REQUIRED_EFFECTS`: required liability-bearing ancestors of the chosen
candidate must have independently reconciled Applied outcomes. This establishes
the declared effect condition, not arbitrary business or product success.

The ledger must be explicitly initialized with `CoreLiabilityLedger.initialize`
or an admitted UNKNOWN record. Absent state never means clean. A genuinely clean
initialized graph may complete without fabricating an effect receipt. Every graph
reference must exist, including references on unrelated branches. Valid NotApplied
on an unrelated branch does not taint a clean candidate; NotApplied on a required
ancestor clears uncertainty but denies required goal success.

`finish_job` evaluates the ledger and recursively required job/ledger references
inside the same existing TransactionRunner callback that settles the reservation
and appends DONE. No nested runner, read-then-unconditional-write or second truth
store is introduced. Dependencies require required-bound native DONE plus current
valid ledger evidence. Advisory DONE, absent tasks, cycles, foreign scope, drift,
OPEN, ESCALATED and corrupt evidence deny. Traversal retains the existing 512 total
node budget and adds a conservative 128 unique task cap. Shared descendants are
counted once. Composition supports the same Core, runner, owner namespace and
governor deployment. Unavailable/differently deployed references fail closed.

The transaction backend must serialize all these reads with the terminal write.
The local test backend holds a process/file lock for the entire transaction and
uses revision CAS. Cockroach's existing adapter requests SERIALIZABLE, but this
tranche does not certify a live database, RLS or a distributed deployment.

## History, replay and authority

Required histories carry strict versioned binding/proof metadata. Binding presence
and content are immutable; a required terminal history cannot gain another version.
Matching submit/begin/finish replay returns retained metadata without another
result, settlement, verifier invocation or fixture step. Missing/null/unknown
metadata, downgrade and changed replay inputs reject. Existing v1 advisory history
is read with its original shape and cannot be upgraded in place, including after
DONE. A new task identity is required for a new semantic contract.

Only opted-in native jobs expose `task_completion=COMPLETED` for DONE and
`completion_scope=LOCAL_NATIVE_REQUIRED_JOB`. Provider verification remains
UNVERIFIED, authority NONE and transport OFFLINE. Stored hashes and proofs are
bounded provenance metadata, not execution authority or independent truth. The
existing ledger still requires an explicitly injected trusted verifier that
establishes distinct receipt/no-effect certificate and independent readback.
Provider text, missing receipts and `reconciled=true` do not close uncertainty.

Kill prevents required success promotion; current Core admission is revalidated
before transaction commit, and fresh retries re-read epoch, kill and dependency
evidence. A denied finish retains STARTED and conservative budget accounting.
Already committed history is not reinterpreted during matching replay; inspection
requires a currently admitted READ principal. Advisory delayed accounting and safe
reconciliation/readback behavior retain their previous meaning. Committed spend
remains counted against the governor; replay does not release or charge it again.

Graphs cannot gain or drop slots after initialization. Planned ambiguous effects
need predeclared liability references. Replanning creates A-prime and the trusted
host must retain B/transitive requirements. A late graph replacement or CLOSED
UNKNOWN redelivery is rejected with a fixed conflict reason; historical DONE/proof
is unchanged. Conflicting observations require explicit review evidence, retained
in this tranche's external test log, rather than an invented second truth store.

## Scope and verification limits

Tests invoke actual governor terminal writes, deterministic conflict schedules,
post-evaluation revocation, competing finalization and fresh processes reopening
the same fixture store. Lost closure ACK is read back without repeating the trusted
verifier; lost result ACK does not duplicate history or settlement. Packaging
acceptance executes installed Core/ledger/governor/binding behavior from wheel and
sdist with checkout hidden, isolated PID/network and no PYTHONPATH/test helpers.
Its copy-on-write backend is explicitly acceptance-only.

These results prove the declared local native route. They are not power-loss
durability, distributed exactly-once, live provider or production signer evidence.
Host omission of a binding/dependency or selection of a semantically wrong clean
candidate cannot be inferred by this narrow API. Wider AgentRuntime, CPL and CLI/Web
final response routes still need the later accepted product integration; this is
not global G2 closure, G3/G4/G9/G10, Desktop-v1 or a hackathon release. Master v2 and
ADR-013 acceptance remain required for the wider profile. Public demo and video
execution remain HUMAN_ONLY.
