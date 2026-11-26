# RH-06 STOP/CAS decision

**Status: PENDING.** Owner and independent security approval are required before wiring a shared gate into the Native runtime. RH-06 fixture opt-in does not grant approval.

## Proposed ordering

Use design A: one trusted, bounded sequencing service for the final broker
publication and durable Core STOP/revoke transactions. Core owns the journal,
warrant and policy decision. The sequencer can order events but cannot grant or
settle operations. The broker independently checks the signed START binding and
holds the one-attempt fence. The irreversible action is a successful exclusive
ref link, not the gate acquisition, an ACK, or a matching OID.

| Order | Ref | Original Core state |
| --- | --- | --- |
| STOP/revoke commits first | Link forbidden. Old ref or absence preserved. | No new START if stopped before START. After START, UNKNOWN with reservation UNKNOWN and outbox HELD until authenticated resolution. |
| Publisher holds final gate, Core revalidates, then link succeeds | New OID. Concurrent STOP commits after link. | UNKNOWN / HELD until witness and completion verify. Then one atomic Applied / VERIFIED settlement of the original reservation and task. |
| Release IPC fails, lock or clock is ambiguous, or a party crashes | No further link attempt. A previous link may already exist. | Keep UNKNOWN / HELD unless independent evidence proves the original effect. |

This explicitly allows a STOP request after final release validation to wait
behind the publisher. It is a change from interpreting STOP as able to preempt
until the syscall. The owner must decide whether the bounded wait is acceptable.
Provisional design: bound gate lifetime and make waiting STOP win over any new
publisher. A caller timeout is not a committed STOP. If a bound is exceeded,
close admission to new effects and require reconciliation of the original
attempt. Never transfer a timed-out lease to a competing publisher while the
prior executor might still link.

## Design comparison

- **A, shared sequencer:** order is common to the Core writer and broker. Acquire
  the sequencing slot before any involved Core write transaction. End final
  Core read validation before broker link and do not hold database transactions
  over socket I/O. Hold the sequencing slot through link or confirmed broker
  death. Bound IPC and gate admission, give STOP priority on contention, and
  reject when the sequencer cannot prove who holds the slot. A bare shared
  lock-owning FD is insufficient. Verify after reboot that any old attempt is
  still fenced in durable storage.
- **B, broker-only gate:** a broker can order its own STOP messages and link.
  Peer credentials, a signed grant and final Core revalidation do not by
  themselves serialize an independent Core revocation transaction with the
  link. A Core grant delayed on IPC can be stale at effect time. Adopting this
  design would require routing every relevant Core STOP/revoke write through a
  common ordering protocol and specifying fail-closed behavior when the broker
  is unavailable. RH-06 chooses A because the ordering needs to include both
  domains without giving the broker authorization or journal authority.

The implemented fixture uses existing RH-02 broker STOP and one-attempt state
and RH-04 Core settlement. They are **separate** local mechanisms. A signed
fixture grant does not constitute a live final revalidation against durable
Core STOP. The shared cross-UID sequencer is pending owner decision and is not
implemented or exercised by this candidate.

- [ ] Native owner approves both orderings and the bounded waiting policy.
- [ ] Independent security reviewer approves lock order, crash fencing, and
  cross-UID authority and descriptor custody.
- Decision reference / owner / date:
- Security sign-off reference / reviewer / date:
