# RH-04 Native #69 forward gate boundary

Status: local non-activating candidate, `BLOCKED_HOST / BLOCKED_SECURITY_REVIEW`.
This work does not prove or enable the Native #69 forward path.

## Implemented candidate

- Native local operation v3 records trusted host-configured `device_id`, exact
  repository and existing ref-parent `(dev, ino)`, ref name, zero old OID and
  expected commit OID. Older v2 operations remain readable but have no device
  or physical binding and cannot enter the cold witness recovery seam.
- The local Native route now refuses publication unless its Core runner and
  publisher share the explicitly configured `NativeStopCasGate`, and the
  durable operation is v3. The regular Native composition does not configure
  this gate or a qualified device. `for_local_patch` therefore fails closed
  while constructing the route, before Core START is written. A direct call
  to the dispatch method also rejects before object or ref publication.
- When configured for an isolated candidate, Core governor mutations, warrant
  revocation, Native admission invalidation, mission STOP/close and coding task
  STOP/cancel use the same optional gate as the publisher. The publisher holds
  it across the last Core release callback, descriptor/ref-parent checks and
  exclusive `os.link`. Group-write storage paths are rejected. The expected
  existing ref-parent identity is compared with the held descriptor and again
  at the link boundary.
- A cold recovery port is injectable into `CoreCodingTasks`, but the only
  implementation in this branch is explicitly disposable-fixture-only. It is
  reached through the controller's existing `request("reconcile", {task_id})`
  action, resolves synthetic fixture material from trusted test setup, invokes
  the fixed verifier in a fresh process, and passes a typed
  `VerifiedNativeWitness` to the task settlement transaction.
- That transaction checks the original task, signed capsule, unknown local
  patch step, original local-zero START, route plan/capsule link, original
  request bindings, and current settlement epoch. It applies the existing Core
  intent resolution and appends the Native task's `VERIFIED` receipt in one
  Core transaction. It never calls the publisher or broker. A later takeover
  epoch can settle a witness only when the current epoch remains unchanged from
  verification through commit; the request stays bound to its original epoch.
- The verifier returns separate effect, producer sync, witness signature,
  readback durability and producer completion facts, plus the signed witness
  and completion hashes and publication `(dev, ino, ctime_ns)`. The adapter
  compares those values with its own subsequent readback before constructing
  Core evidence. Readback `fsync()` is not treated as proof of the producer's
  prior directory sync.

## STOP/CAS order and approval gate

The candidate gate is advisory `flock` plus in-process thread serialization.
Its synthetic race test establishes these candidate outcomes:

1. A revocation/kill transaction that commits before the publisher acquires
   the final gate is observed by release validation and prevents the link.
2. If the publisher already owns the final gate and completes release
   validation, a concurrent STOP waits; the exclusive ref link wins and STOP
   commits afterward.
3. STOP after link likewise follows the completed CAS.
4. Gate acquisition failure, timeout, inode replacement, unsafe parent, or
   changed physical identity refuses the link.

This gate order is a change to the stronger documented immediate pre-link STOP
semantics. The existing interface cannot atomically sample an external STOP
request and perform the link syscall. The production transition is
`REQUIRES_OWNER_SECURITY_APPROVAL`; this candidate is not activated. A STOP
that arrives after the final authorization check but before `os.link` cannot
preempt a publisher that already owns the gate. This remains the exact
irreversibility boundary and the primary semantic blocker.

The gate is not automatically installed on a `TransactionRunner`. Only the
relevant STOP/revoke/kill operations explicitly acquire it. Its directory and
lock are same-UID owned; same-UID code can replace the pathname outside a held
critical section, and the mechanism is not usable by the distinct broker UID
without a reviewed cross-UID design. A same-UID actor can also rename the
already-validated ref-parent directory after its early descriptor/path check
and before the final link. The broker pins the opened directory descriptor and
checks its identity and current pathname before linking, so a replacement that
persists through that check is rejected. Those checks do not atomically lock
the directory's namespace: a rename/replacement can still race between the
final pathname check and `os.link`, potentially linking into the pinned
directory after it has been moved. This residual path TOCTOU is a production
blocker; same-UID tests do not establish protection against a malicious host
process. Core or broker death with an independent production executor and
durable Core journal ordering have not been proven. No writable directory
descriptor is treated as an exact-ref capability.

## Evidence and limits

The integration fixture creates a public Core coding task, synthetic capsule,
original UNKNOWN/HELD Core local-zero intent, route-step record and disposable
broker repository. It intentionally seeds task receipt history instead of
running the full Native producer/approval/apply graph. It reaches recovery
through `CoreCodingTasks.request("reconcile")`, not Q09 intent-only settlement.
The fixture proves START, reservation UNKNOWN and outbox HELD before broker
dispatch. The disposable broker crashes after its witness is durable. A
separate Core process recovers through the fresh verifier and commits the
original intent and Native task in one Core transaction. Deterministic fault
injection persists that settlement, drops its Core acknowledgment, and exits
the process. A second fresh Core process performs concurrent and repeated
recovery; the intent revision and task receipt each advance once, the outbox is
PENDING, the reservation is COMMITTED, and broker dispatch count remains one.
One isolated fixture replaces the published ref inode before first recovery;
another replaces it immediately after fresh-process verification but before
the Core transaction's settlement callback. Both prove the task remains
UNKNOWN, intent Unknown, reservation UNKNOWN, outbox HELD, and dispatch count
one. The settlement callback also rechecks the disposable ref inode, ctime,
witness and completion bytes inside the Core transaction. This narrows, but
does not atomically eliminate, the interval between that final physical check
and durable Core commit. RH-02's tests also cover broker process crashes and
restart-denied attempts.

The synthetic gate/race tests use one UID and a test runner explicitly bound to
the gate. The regular Native composition does not pass the gate or trusted
device ID; route construction therefore fails before START. The runtime
remains same-process Git plumbing and no production executor, enrollment,
signer key, trusted verifier channel, or exact-ref sandbox policy is
configured. The test port's context resolver is a fixture closure, not a
durable production resolver. Cold task recovery is exercised after restart,
but not the full Native `apply` route, production broker IPC or separate
executor process. The final in-transaction fixture check is not a lock over the
filesystem and does not prove current ref identity through Core commit. A
same-UID replacement after that check and before durable commit remains an
untested physical-state race. Historical Native #69 proof and containment
inventory were not available and were not reconstructed.

Host qualification is read-only. The observed machine is Linux Mint 22.2,
kernel `7.0.0-38-generic`, Python `3.12.3`, Git `2.43.0`, systemd `255`,
Bubblewrap `0.9.0`, cgroup v2 with no delegated child controllers, AppArmor
module loaded but profile visibility denied, 1.2 GiB available memory and
about 3.7 GiB available disk. It is not the pinned Ubuntu 24.04 Noble profile.
Namespace actions and separate-UID behavior were not tested. No packages,
users, services, mounts, host keys, or system settings were changed.

## Minimal production integration patchlist

1. Extend the trusted Native composition in `runtime/meta_hackathon/native_authority.py`
   to bind one durable device identity, a shared Core STOP/CAS gate, the
   separately launched broker client, and a production cold-recovery port.
   Keep the default path disabled until all bindings exist.
2. In `runtime/mission/git_publish.py`, derive the v3 request only from the
   authorized plan and pinned repository/ref observations. Persist START,
   UNKNOWN/HELD and outbox before broker contact; reject any missing or changed
   identity without redispatch.
3. Move ref publication to a separately owned broker with OS-enforced exact
   repository/ref confinement and a reviewed cross-UID STOP gate. The current
   in-process Git plumbing and same-UID file lock are not production custody.
4. Replace `DisposableNativeTaskWitnessPort` with a resolver over durable Core
   task, capsule, route-step and intent records. Return verifier results over
   an authenticated process channel, then atomically reconcile the original
   intent and task in the existing Core transaction.
5. Qualify signer custody, producer fsync completion, restart behavior and the
   complete Native apply-to-recovery path on pinned Ubuntu 24.04 Noble x86_64.

Protected checkpoints: Native owner/security approval of STOP ordering;
Core security review of original-intent and task reconciliation; executor
identity/key/path custody review; and independent Noble host acceptance. No
checkpoint is satisfied by this same-UID synthetic fixture.

## Required protected review before any activation

1. Obtain explicit owner/security approval for the STOP linearization and
   document the permitted ordering in the Core contract.
2. Design a cross-UID gate and launch model with trusted lock custody, crash
   behavior, Core transaction ordering and bounded failure semantics.
3. Persist the device, executor enrollment/key epoch, original route identity,
   exact plan/ref physical binding and one-attempt association from trusted
   Native records before external effect. Old incomplete v2 records stay held.
4. Move exact-ref publication to a separately qualified executor identity with
   OS-enforced storage confinement; review descriptor custody and path races.
5. Establish non-Core-accessible signing-key custody, rotation/revocation,
   producer completion semantics and an authenticated verifier-to-Core result
   channel.
6. Implement a production durable resolver for the existing Native task,
   capsule, route step and original Core intent. The synthetic fixture covers
   Core restart, settlement ACK loss, atomic task/intent update and no
   redispatch; repeat those checks through the production resolver and store.
7. Run the full independent producer/verifier acceptance on pinned Ubuntu 24.04
   Noble x86_64 and receive independent security sign-off.

Until all gates pass, production release is blocked, historical Native #69 is
`UNKNOWN / HELD / BLOCKED_SECURITY_REVIEW`, and
`NATIVE_FORWARD_PATH_VERIFIED: NO`.
