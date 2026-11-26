# RH-07 shared STOP/CAS sequencer

Status: **fixture candidate only**. Owner approval and independent activation
sign-off are pending. Ordinary Native still denies the route before START.

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
The owner must explicitly accept the case where STOP has to wait after the
publisher wins its slot. The older interpretation could attempt to cancel up
to link. Userspace cannot atomically commit an independent Core STOP and
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

Read-only source audit found optional gate hooks on warrant revoke,
governor kill/start_epoch, task stop/cancel/drain, Native lifecycle transitions,
and admission/mission close. Tests exercise existing Core **warrant revoke,
kill and explicit start_epoch** against the same broker slot. This does not
prove exhaustive mutation coverage. In particular, governor
`apply_execution_capacity` and `apply_money_policy` can increment durable epoch
through direct runner transactions without this gate. The existing capacity
admission/quiescence fence is a further route-specific proof obligation.
Money policy is called from chat session and mobile operator paths. Those
shared files stay with Cloud. No claim of a bypass in a qualified route is
made, and no qualified route is wired. Before activation, audit lock ordering,
scope invalidation, admission/mission close and task cancellation on every
actual ingress and cover those mutations with a single reviewed order.

- [ ] Owner accepts the two orders and the observable STOP wait/failure contract.
- [ ] Independent reviewer accepts full mutation coverage, recovery and host enforcement.
- Owner decision / date:
- Security decision / date:
