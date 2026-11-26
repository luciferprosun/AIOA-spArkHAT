# RH-01/RH-02 local implementation handoff

Base: PR #69 commit `8bf94361e8d0fdeabc25007b4faeefd33cc0cf8a`, tree `4b0c991a90c9b86712a04266d8acb73de8f91f46`.

RH-01 commit: `RH-01: authenticated broker contract and executor enrollment`.
RH-02 commit: `e5c4c795063af13927e3a7bcb99c338dc03bbc44` (`RH-02: isolated one-attempt CAS broker and verifier`).

Focused command:

```sh
PYTHONPATH=.:tests python3 -B -m unittest -v \
  test_redhat_broker_protocol test_redhat_native_cas_broker
```

The prototype uses a bounded canonical Unix socket request, kernel peer credentials, fixed trusted public enrollment, a single-use durable attempt guard, synthetic permit/revocation locking, exact create-only ref publication, the existing v1 witness, a separately ordered signed producer-completion record, and a new-process verifier. Tests use only disposable bare repositories and generated identities. A test-only reconciler permits one decision for the original start, intent and reservation and measures zero ref-link redispatch after uncertain outcomes.

The successful pre-permit STOP guarantee is serialized with permit by the fixture guard lock. After permit, STOP cannot revoke an attempt. This changes the stronger existing Core pre-link authorization-check contract. The permit, guard and STOP semantics require owner security approval before production use. A crash after permit is UNKNOWN/HELD and cannot replay, even if the crash happened before the ref link.

Three durability facts remain distinct: readback can observe the ref and re-sync current witness storage, while the signed completion record establishes that the fixture producer's persistence calls returned in the designed order. A v1 signature alone cannot prove its own directory sync. This is a software fixture trust assertion, not independent kernel attestation.

The executor runs as the fixture UID. This does not prove independent UID ownership, production key custody, systemd/AppArmor/cgroup isolation or the qualified Ubuntu Noble host. The existing read-only Git child is preserved. The prototype has not changed Core authority, journal or settlement. No live publication occurred. Native forward qualification remains blocked and historical Native #69 remains UNKNOWN/HELD.

RH-03 is implemented on `local/redhat-native69-rh03` (`d37f192` Core adapter and fixture recovery; `9f7637e` Core mapping and handoff). Its adapter binds the RH-02 broker request to the existing durable Core START, warrant, reservation, owner scope and outbox, while production release remains disabled. The test-only recovery path verifies the original witness in a fresh process and settles through the existing intent journal; focused adapter, recovery, Core-intent and Native cold-controller tests pass. It does not wire production Native task state or close the independent executor/STOP trust boundary. RH-04 must integrate the original Native route/task state, establish an owner-approved cross-process STOP/release contract and separate executor/key custody, then qualify the complete path on pinned Ubuntu Noble. Keep unavailable evidence fail-closed.

## Current consolidated status

RH-04 has since added the non-activating Native task/recovery candidate, and
RH-05B ported that work plus the RH-03 late fixes onto fetched Cloud `main`.
The integrated source, current regression results and outstanding production
gates are recorded in [RED_HAT_RH05B_HANDOFF.md](RED_HAT_RH05B_HANDOFF.md).
