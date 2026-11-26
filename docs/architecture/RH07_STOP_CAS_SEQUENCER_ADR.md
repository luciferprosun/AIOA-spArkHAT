# RH-07 shared STOP/CAS sequencer

Status: **fixture candidate only**. The 2026-11-26 local mission authorizes both event orders for disposable
engineering qualification. Production activation requires a separate decision. Ordinary Native still denies the route before START.

## Decision

Use a supervisor-owned Unix listener to sequence a Core control slot and a
broker publication slot. The daemon never reads or changes Core authority,
never creates a witness and never settles. It pins both peer PID/UID/GID tuples
at launch and checks the exact epoch, role, and binding digest. The broker
continues to validate the RH-06 signed grant from original Core START and
durably consumes the original attempt before requesting its slot.

| Order | Effect and Core state |
| --- | --- |
| Core control slot first, STOP/revoke commits | Broker's signed final Core revalidation refuses. No ref link. If START already exists, intent and reservation stay UNKNOWN and outbox stays HELD. |
| Broker slot first, Core revalidation passes, exclusive link succeeds | STOP waits for the broker's completed slot. The link cannot be reversed by STOP. UNKNOWN/HELD continues until authenticated evidence permits one existing Core settlement. |
| Slot or release outcome is ambiguous | No new slot if the durable marker remains. No new CAS for the consumed attempt. Missing evidence retains UNKNOWN/HELD. |

The slot is not the effect. The link is irreversible when the kernel succeeds.
Directory synchronization and separate signed witness and completion still
follow. The fixture holds the sequencer slot through all of those steps.
Under the qualification contract STOP may wait after the publisher wins its
slot. A caller must observe the durable Core transaction to report committed STOP. Userspace cannot atomically commit an independent Core STOP and
preempt that syscall without a common serialization mechanism. Keep the ordinary
route fail-closed until the ordering is approved and enforced.

## State transitions

```text
empty -> persist + fsync outstanding -> grant one slot
grant -> authenticated DONE after work -> unlink + fsync marker -> closed ACK
grant -> peer loss / timer / crash / ambiguous error -> outstanding -> deny
restart + outstanding -> deny all new slots
```

Start only with the protected supervisor-owned state directory and its
exclusive leader lock. A new daemon or changed epoch does not clear the
outstanding marker. The fixture has no automatic reset. A later recovery port
reads existing evidence and can settle without asking for a publication slot.
Separately, the broker's original durable attempt record survives sequencer
slot closure and prohibits another link for the same START.

The queue is bounded. Admitted control waiters are preferred over a new
publication. Waiting for a grant times out before the mutation can run. Loss
of the closed ACK after a caller received a slot means the Core mutation may
already have committed. A caller must read back durable Core state and must not
tell the operator that STOP committed on timeout alone. Neither a timer nor
socket close proves physical writer exclusion. If an already authorized
publisher survives a deadline or supervisor failure, it might still finish
its current link. The outstanding marker fences any new slot and Core STOP
cannot overtake it. Host scheduling, saturated queues and filesystem stalls
mean hard STOP latency is not guaranteed.

## Lock order and coverage

1. A participating Core mutation obtains its slot **before** beginning the
   Core transaction. Per-thread nesting reuses an existing slot inside the
   pinned process. A child process cannot inherit this shortcut.
2. Broker finishes durable attempt consumption and releases that file lock.
   It obtains the sequence slot, then the fixture broker guard, then asks Core
   for a fresh signed release over the authenticated socket. Core checks the
   live binding at the sequencer before and after its fresh read transaction.
   That transaction ends before the reply. Core's release responder does not
   acquire a second slot. The broker then rechecks the held repository/ref
   parent, object and time before link and sync.
3. Core state is the authorization checked by the response, including consumed
   warrant, revocation, kill and current epoch. The trusted work callback is
   populated from fixture task state. A production callback must bind the
   original route and work handle and honor task cancellation. No transaction
   is held open across broker or sequencer IPC.

| Core invalidation | Control-slot boundary and evidence |
| --- | --- |
| Warrant revoke | `CoreWarrantLedger.revoke` enters before its transaction. RH-07 tests race a real revoke with final release in both orders. |
| Kill, explicit epoch | Governor `_change` and `start_epoch` enter before the runner. After either invalidation, final Core read refuses a previously exported grant. |
| Money policy and execution capacity | Both direct epoch writers enter the registered runner gate around the transaction, including its commit. Money time is sampled after acquisition. RH-07 tests observe the durable slot during money authority rechecks and the real capacity write from the operator entry. Capacity still requires its own quiescence, live captures and consumed warrant. |
| Coding task stop, cancel, drain, close | `CoreCodingTasks.request` gates stop/cancel before touching owned cancellation tokens. Drain changes admission and cancels retained work under the gate, then joins outside it. Close delegates to drain. RH-07 tests exercise stop/cancel of synthetic owned work, drain and final refusal. |
| Core close and Native lifecycle | CoreAdmission.close and TransactionRunner.close enter before invalidating admission or the backing store. Native lifecycle quarantine, invalidate, begin/abort capacity review, activate and drain use the runner gate around invalidation. MissionService.stop/close use its registered foundation gate. RH-04 tests cover admission close versus link and invalidation versus capacity activation. RH-07 exercises both close entries before final release. |

Lifecycle construction precedes binding. A phase that is already fenced cannot regain
publication authority through cleanup. Release checks the original binding, work and live
epoch while a broker slot is active. A Core transaction failure returns a signed DENY.
An ambiguous sequencing outcome still fences the service. The IPC client rejects a new
connection from inside a retryable Core transaction.

These results cover the listed entry points with a registered gate. The fixture callback
uses a synthetic owned cancellation token. It does not install a production work handle
or a supervisor. The existing Native route continues to require its registered local
gate; substituting this IPC adapter there would require qualification of normal apply,
fresh verifier recovery and all role-specific OS permissions.

Engineering disposition: integrate disabled. External review was not performed.
Production activation, qualified separate-UID custody and host acceptance remain open.
