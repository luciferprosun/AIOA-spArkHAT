# RH-04 Native #69 handoff

This is the historical handoff for source commit `4b81f1a` on its original local
branch. RH-05B later consolidated that candidate with the RH-03 late fixes on
the then-current Cloud `main`; see [RED_HAT_RH05B_HANDOFF.md](RED_HAT_RH05B_HANDOFF.md)
for integrated source, tests, reviews and current blockers.

Status: **local non-activating prototype; production remains blocked**.

## Source and scope

- Base: RH-03 commit `9f7637e5b4dbe567d02f0d730aa3e0fe77c49a0f`.
- Branch: `local/redhat-native69-rh04` in `/home/l/projects/AIOA_REDHAT_RH01_RH02`.
- Canonical checkout and Cloud refs were not changed. No fetch, push, merge, live operation, OS provisioning, service change, or key provisioning occurred.
- The runtime candidate remains disabled by default. It does not claim `NATIVE_FORWARD_PATH_VERIFIED` and does not modify historical Native #69.

## Delivered candidate

- Added the opt-in `NativeStopCasGate`, bound only when explicitly installed on the existing `TransactionRunner`. Core governor kill/epoch changes, warrant revocation, Native lifecycle stop/invalidation, task cancel/drain, `MissionService` stop/close and `CoreAdmission.close` share this gate when configured. Publication holds it from the last release validation through the exclusive ref `os.link`.
- Added v3 local operation identity fields: trusted host device ID, repository `(dev, ino)`, existing ref-parent `(dev, ino)`, exact ref, old OID and new OID. Legacy v2 remains readable but is not accepted for cold Native witness recovery. Normal Native composition does not provide the gate or trusted device ID, so route construction fails before Core START.
- For a v3 ref, plumbing no longer creates a missing parent. It verifies the opened parent and repository pathname before creating a lock, then rechecks the parent at the final link boundary.
- Added an explicitly disposable recovery port through `CoreCodingTasks.request("reconcile", {"task_id": ...})`. It resolves synthetic test material outside task payloads, invokes the fixed independent verifier in a fresh process, binds the result to the original Core START and task records, then settles the existing Core intent and appends the Native task's VERIFIED receipt in one Core transaction. It does not fabricate the process-local `cas_ack`, call the broker, or redispatch.
- Typed fixture evidence carries separate witness/completion hashes, combined receipt/readback hashes, and the observed publication inode/ctime. The Core transaction checks those hashes against reconciliation evidence references. The Python value is not an authenticated production capability.

## STOP and irreversibility

The synthetic gate imposes this total order: if Core STOP/revocation acquires the gate first, it commits and the publisher's release check prevents link. If the publisher acquires the gate, completes release validation and reaches the link section first, STOP waits and commits afterward. The exact irreversible attempt is the exclusive `os.link` that creates the ref. This ordering changes the documented stronger immediate pre-link STOP behavior and is marked `REQUIRES_OWNER_SECURITY_APPROVAL`; the candidate is not activated.

The gate is cooperative and same-UID. It does not serialize an uncooperative same-UID writer, and its lock custody is not suitable for a distinct executor UID without a reviewed cross-UID design. Kernel lock release after a process crash is tested, but production Core transaction ordering, independent broker death behavior, and a qualified process/UID trust boundary remain unproven. The ref-parent descriptor and pathname are checked before the link, but the pathname check and `os.link` are not one atomic namespace operation. A same-UID actor can rename the directory in that interval and make the pinned directory reachable elsewhere; this physical-path race remains a production blocker.

## Test evidence

`tests/test_redhat_rh04_native_task_gate.py` exercises synthetic disposable Core, task, broker and Git state. The positive recovery case seeds task receipt history and the durable route-step link; it does **not** run the full Native producer/approval/apply graph. It asserts UNKNOWN/HELD before broker dispatch, then drives the actual task controller's reconcile action. Independent processes perform verification and Core recovery. Deterministic transaction fault injection persists both the original intent settlement and task VERIFIED receipt, drops the settlement acknowledgment, exits the process, and demonstrates idempotent recovery after restart. The test observes one task receipt advancement, one Core intent revision, COMMITTED reservation, PENDING outbox, one broker dispatch and no redispatch. Negative cases replace a same-OID ref inode before verification and after verifier return but before the Core settlement callback, plus ref-parent replacement before lock creation. All retain UNKNOWN/HELD with no extra dispatch. The callback rereads the fixture ref/witness/completion inside the Core transaction; filesystem state is still not atomic with the Core commit.

The helper uses the synthetic `DurableFactory` filesystem store, not the production Core SQL backend. Fresh verifier subprocess output is a same-UID test pipe, not a production authenticated verifier-to-Core channel.

Focused local results: RH-01/RH-02 broker protocol and executor suites: 23
passed; RH-03 adapter/recovery/Core intent suites: 30 passed; Native Git
publication boundary: 7 passed; cold controller: 1 passed; Native lifecycle:
11 passed; Native coding flow/history: 29 passed; RH-04 gate/task recovery:
18 passed. Total: 119 passed, 0 failed, 0 errors, 0 skipped. Static source
compilation covered 17 changed Python files without writing bytecode;
`git diff --check` passed. The host probe is read-only and does not test
namespace actions or a separate executor UID.

Exact offline test commands:

```sh
PYTHONPATH=.:tests python3 -B -m unittest -v test_redhat_broker_protocol test_redhat_native_cas_broker
PYTHONPATH=.:tests python3 -B -m unittest -v test_redhat_core_adapter test_redhat_core_recovery test_core_intent
PYTHONPATH=.:tests python3 -B -m unittest -v test_native_git_publication_boundary
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -v test_native_git_cold_controller
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -v test_nz13_native_coding_lifecycle
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -v test_nz13_native_coding_flow
PYTHONPATH=.:tests python3 -B -m unittest -v test_redhat_rh04_native_task_gate
```

The cold-controller/lifecycle/flow tests use the existing project venv because
system Python does not have the repository's Pydantic dependency. No packages
were installed. The test matrix used disposable Core and Git state; it did not
exercise live Native actions or production broker dispatch.

## Host and trust blockers

Read-only probe found Linux Mint 22.2, kernel `7.0.0-38-generic`, Python `3.12.3`, Git `2.43.0`, systemd `255`, Bubblewrap `0.9.0`, cgroup v2 without delegated child controllers, AppArmor module loaded but profile visibility denied, about 1.1 GiB currently available memory and 3.7 GiB free disk. This is not the pinned Ubuntu 24.04 Noble x86_64 environment. Namespace actions and separate executor UID behavior were not tested.

Production activation still requires:

1. Owner/security approval of the gate's STOP linearization.
2. A production Native composition that supplies durable trusted device, route/plan, physical identity, enrollment and one-attempt association before any effect; incomplete v2 history must remain HELD.
3. A separate executor UID with OS-enforced exact-ref confinement and a reviewed cross-UID lock/descriptor custody model.
4. Executor private signing-key custody unavailable to Core/model, with rotation/revocation and trustworthy producer durability semantics.
5. A production durable Native task/route resolver and authenticated verifier-to-Core result channel.
6. Independent acceptance on pinned Ubuntu 24.04 Noble x86_64 and independent security sign-off.
7. A read-only inventory, isolated restore and replay-denial proof for the original Native #69 records before historical containment can be claimed.

No historical source record, private key, or backup was reconstructed. The historical state remains `UNKNOWN / HELD / BLOCKED_SECURITY_REVIEW`.

## Next integration boundary

After owner approval, RH-05 should wire a production resolver and gate into the original Native task/route composition while retaining the One-Core journal, task authority, reservation and outbox. First prove fail-closed route construction and durable START on an approved test configuration; then test a separately owned broker through the original `apply` route, crash/restart and authenticated fresh-verifier settlement on Noble. Do not enable production execution until the independent UID/key/path and STOP review gates pass.

`NATIVE_FORWARD_PATH_VERIFIED: NO`
`PRODUCTION_ENABLED: NO`
`HISTORICAL_NATIVE69: UNKNOWN / HELD`
`PUSH: NONE`
`MERGE: NONE`
