# RH-03 Core mapping and implementation boundary

Status: local RH-03 prototype; production broker release remains disabled.

## Existing authorization and START

`CoreServiceGuard.dispatch_registered_remote_git` is the Native route entry at
`runtime/service_guard/service.py:39-96`. It uses the already-registered
`CoreRemoteGitRoute`, `route.target_guard()`, the admitted Core principal,
the existing journal and the current reservation. Before any external effect,
its transaction calls `CoreIntentJournal._start_in_transaction` at
`runtime/mission/intent.py:147-240`. That one Core transaction validates the
operation hash, warrant, reservation and current epoch; consumes the warrant;
marks the reservation UNKNOWN; and stores the intent plus HELD outbox.

`CoreIntentJournal._load` at `runtime/mission/intent.py:51-92` is the durable
source of truth. It checks the exact warrant and operation digests, original
epoch, liability ID, intent/outbox digest and state, warrant consumption, and
reservation binding/state/evidence. RH-03's `CoreIntentAdapter` reads this
projection only through the same `TransactionRunner` and existing Core
principal. Its stable `start_digest` commits the original record key, owner
scope digest, warrant, operation, reservation, liability and epoch. The
`intent_digest` reconstructs the immutable pessimistic START body after
settlement so that a late verifier can still name the same original START.

## Owner, device and epoch

The owner identity is `canonical_sha256(CoreWarrantLedger.scope)`, where scope
is the full `OwnerScope(tenant_id, owner_id, space_id, slot_id)` from
`runtime/core_admission.py:69-81`. Warrant owner scope, task, operation class,
lease epoch and approval are revalidated by the ledger. The RH-03 request's
`owner_id` is this full scope digest.

Current local Native records do not persist a broker `device_id`. The Native
operator admission row in `runtime/meta_hackathon/native_authority.py:910-922`
binds operator admission, instance, source and capsule, but no device. A device
ID must come from trusted host enrollment/configuration; request JSON and model
input cannot supply it. The adapter consequently requires `trusted_device_id`
as a trusted configuration argument. It does not infer device identity from
Core state.

The operation's `lease_epoch` is the original authorization epoch and stays in
the witness binding. `CoreDualGovernor` may advance its current epoch for a
readback takeover. RH-03 records that current value separately as
`settlement_epoch`; the transaction rechecks it before calling Core settlement.
A stale verifier result is rejected and can be re-read without redispatch.

## Exact physical publication binding

The actual local Native operation in `CoreRemoteGitRoute._local_patch_operation`
at `runtime/mission/git_publish.py:1471-1490` records the plan digest, capsule,
source base, commit SHA, tree SHA and exact ref. The current durable Core intent
does not record the repository device/inode or ref-directory device/inode;
the repository identity remains on the in-memory `LocalGitPlan`/route. It also
does not have a separate durable old-OID field (the existing create contract
uses the all-zero old OID).

The adapter accepts only the exact local Native operation schema/profile or an
explicit RH-03 disposable-fixture schema. For the Native profile, absent pinned
filesystem identities make `CoreStartBinding` incomplete and any broker
request is rejected. The fixture path stores repo/ref directory identities,
exact ref, zero old OID and new OID inside the fixture operation, so tests can
exercise substitutions. This does not prove the production plan/host identity
handoff. A production adapter must receive those identities from the original
trusted Native plan and compare them to freshly opened descriptors before
release and readback.

## STOP and physical CAS

For the Native local route, `CoreServiceGuard.dispatch_registered_remote_git`
creates durable START before dispatch, then defines `release()` at
`runtime/service_guard/service.py:76-87`. For a Native local patch that callback
rechecks `route.check()`, cancellation, current consumed warrant/governor
authorization in the Core transaction, Native work-handle checks and the
source/plan. `CoreRemoteGitRoute._dispatch_local_patch` calls the callback
around fixed object plumbing and passes it as `before_ref_link` to
`_bounded_git(... update-ref ...)` at `runtime/mission/git_publish.py:1216-1239`.

`LinuxSandboxBroker._git_publish_new` at
`runtime/mission/sandbox_linux.py:1358-1395` writes and fsyncs an unnamed
temporary ref inode, calls `before_ref_link`, checks cancellation once more,
then `os.link` performs the exclusive create. That exact `os.link` is the
irreversible ref CAS attempt. The parent directory is fsynced and the inode is
checked afterward.

This is a fresh pre-link authorization/cancellation check, not an atomic
serialization of the Core transaction with the link syscall. The transaction
returns before the subsequent cancellation check and `os.link`; a concurrent
durable revocation, kill or epoch change can commit in that interval unless an
additional common lock orders both paths. `route.target_guard()` and the Native
work/cancel tokens are process-local. Preserve the current callback and fail
closed; do not describe a synthetic permit as equivalent or stronger.

RH-02's fixture `AttemptGuard` uses a separate state-directory `flock` to order
fixture STOP with fixture permit/attempt persistence. The fixture broker later
rechecks under that lock before `os.link`, but the lock is not acquired by Core
revocation, governor kill or Native cancellation. It does not close the Core
TOCTOU gap. Its durable permit is test dedup evidence only. `SCM_RIGHTS` for a
writable directory FD is likewise not an exact-ref capability.

No production `COMMIT_PERMIT_DURABLE` state was introduced. If owners choose a
permit linearization point that allows a later STOP to lose to the permit, that
weakens the current immediate pre-link check and requires explicit owner and
independent security approval. An OFD lock is only a candidate kernel primitive;
the actual STOP, revocation, Core-journal commit, broker CAS, process-crash and
lock-order semantics must be demonstrated before relying on it.

## Independent verification and settlement

RH-02's `runtime/red_hat/verifier.py` verifies the signed v1 witness and the
separately signed producer completion record against fresh ref/inode
observations. It exposes distinct facts for effect observation, producer effect
sync, witness signature, readback durability and producer witness sync
attestation. Readback `fsync()` does not retroactively prove the producer's
directory `fsync()`; the completion signature is still a producer assertion,
not a kernel attestation.

RH-03's fixture recovery helper starts the fixed verifier in a fresh Python
process with only the pinned fixture root FD and public enrollment/request,
checks the process identity/result shape, then constructs Core evidence refs
from the verified witness/completion bytes and physical readback. It accepts no
caller-provided `Reconciliation`. It settles through the existing
`CoreIntentJournal.apply_resolution_in_transaction` at
`runtime/mission/intent.py:272-290`, whose exact-repeat path is idempotent and
whose conflict path rejects. Intent, governor reservation and outbox update
remain in the existing Core transaction. Duplicate and concurrent fixture
recovery calls therefore produce one journal revision/settlement and no broker
redispatch.

This test path is deliberately limited to the original Core intent journal. It
does not transition the Native coding task to VERIFIED. Production
`CoreCodingTasks._native_git_begin_settlement` still requires the original
process-local `cas_ack` tuple at `runtime/mission/coding_tasks.py:1285-1325`,
and cold `_native_git_reconcile` requires the retained original route/work
handle. A fresh process cannot reconstruct that proof from a ref or SQL row.
The Native task must remain UNKNOWN until a reviewed verifier-backed hook is
added to the original Native task transition.

## Minimal RH-04 production boundary

1. Keep `MissionService`, `CoreAdmission`, `CoreWarrantLedger`,
   `CoreIntentJournal`, `CoreDualGovernor`, `TransactionRunner`, Native task
   state and outbox as the only authority and settlement store.
2. Extend the existing registered Native route with a deterministic host-side
   binding to its original route/plan, exact ref/OIDs, repository/ref directory
   identity, owner/device enrollment, executor key/enrollment and original
   START. Do not accept a model-created request.
3. Define a shared STOP/revocation/release serialization primitive that all
   relevant Core STOP/revoke/kill paths and the broker CAS use through the link
   syscall, with durable journal ordering, crash analysis and lock ownership.
   Until that and owner approval exist, keep independent broker dispatch off.
4. Add a trusted verifier-to-original-Core reconciliation port. It must check
   fresh witness data against the original Core record, settle that same intent
   under the current fenced Core epoch, and update the Native task's original
   state without synthesizing `cas_ack` or a new START.
5. Qualify separate executor UID, OS-enforced path confinement, signing key
   custody and the pinned Noble host. Test crash/restart, STOP races, foreign
   same-OID/ref replacement, concurrent settlement and zero redispatch before
   any production enablement.

Until then, `require_production_release()` returns `BLOCKED_SECURITY_REVIEW`,
historical Native #69 remains UNKNOWN/HELD, and
`NATIVE_FORWARD_PATH_VERIFIED` remains NO.
