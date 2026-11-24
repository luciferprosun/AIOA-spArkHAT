# Red HAT v0.1 Native CAS witness

Forward integration is `BLOCKED_SECURITY_REVIEW`. The inspected main is
`9d8b61c6dce9cccbf32ce8dfc2dc87682567dd9c`, tree
`b1f7dc87ad15e7faf4e7b0cc0e56cdb3e2588a81`. This branch extends the isolated
custody fixture. PR B depends on forward-path acceptance. PR C remains optional.

## Trust boundary

`git_publish._bounded_git` calls `LinuxSandboxBroker._git_plumbing` in the
Core process. The Git subprocess receives a synthetic read-only view. The
parent writes the ref via an unnamed inode, checks the link after directory
fsync and closes the original descriptor before returning. The pre-link
release is an in-process authorization and cancellation check. The controller
uses a process-local CAS acknowledgement to guard settlement.

An independently registered broker must receive only the descriptors and
authorization for the original attempt. It must preserve the pre-link release
checks and own the publication descriptor through witness creation. A distinct
executor UID needs a reviewed custody handoff compatible with existing ownership
checks. Enrollment, key isolation, one-attempt handoff and independent witness
readback are missing on this base.

The proposed `aioa.native-cas-witness.v1` envelope binds witness ID, registered
executor and key ID, challenge, durable START, intent, consumed warrant,
reservation, physical repository and ref directory, exact ref, old and new
OIDs, original inode, durability stage and bounded timestamp. The broker
must durably create the authenticated envelope after publication and before
ACK. Core reconciliation must use the original journal record and recheck
epoch on settlement. Missing or unusable evidence keeps UNKNOWN and HELD.

## Offline fixture

From the checkout, with the project's test dependencies installed, run:

```sh
PYTHONPATH=.:tests python -B -m unittest -v \
  test_native69_witness_fixture test_native_git_cold_controller \
  test_native_git_publication_boundary test_nz25_intent_cold_read \
  test_nz13_native_coding_lifecycle test_core_intent
```

The custody fixture uses a temporary bare repository, synthetic enrollment and
explicit process exits. It tests pre-CAS exit, post-CAS exit before witness,
post-witness exit before ACK, foreign same-OID publication, tampering, duplicate
writes and replacement with the same OID on a different inode. The fresh
readback process verifies the fixture envelope without invoking publication.
Core fixture tests separately exercise retained reservations, stale epochs,
and no replay on cold recovery.

Cloud focused result on Python 3.12 with the pinned `uuid6==2025.0.1`:
44 PASS, 0 FAIL, 0 SKIP (`FIXTURE_PASS`). The broader command adds
`test_nz11_git_confinement` and hit `GIT_RUNTIME_CHANGED` on this host.
The independent broad run reported 51 passing methods, 11 failing methods,
seven errors and zero skips. The confinement cases require the pinned host
profile. No live broker or production repository was used by the tests.

## Qualified-host procedure

1. Provision the pinned Ubuntu 24.04 Noble profile in the
   [host qualification procedure](NATIVE_HOST_QUALIFICATION.md). Start with
   an empty private scratch directory, isolated journal and no production
   credentials. Record the source commit and tree with
   `git rev-parse HEAD 'HEAD^{tree}'`.
2. Run the command above. Then run the existing isolated host acceptance from
   the checkout using its documented pinned Codex test binary and a private
   artifact directory.

   ```sh
   : "${NATIVE_CODEX_PROBE:?Set to the pinned Codex acceptance binary}"
   evidence_dir="$(mktemp -d)"
   bash tests/nz12_ci_host.sh python -B tests/nz12_source_runner.py \
     tests/nz12_ci_acceptance.py --output "$evidence_dir" --codex "$NATIVE_CODEX_PROBE"
   ```

3. Before attempting forward qualification, land a reviewed broker enrollment
   and one-attempt handoff on the candidate. Use a fresh test repository and a
   dedicated executor key. Run the producer and readback from separate
   processes through normal reconcile/apply. Save the registered public key
   fingerprint, process and isolation evidence, original authorization
   bindings, held-state results, and a dispatch count for every crash point.
   Require one settlement after witness-before-ACK and zero redispatches in
   recovery. Repeat with a foreign writer, substituted identity, stale epoch,
   drift, and missing or tampered witness.
4. Record `NATIVE_FORWARD_PATH_VERIFIED` only upon passing the reviewed
   integrated path. This procedure has not been run. Historical #69 remains
   UNKNOWN and HELD under the
   [historical exception](NATIVE69_HISTORICAL_EXCEPTION.md).
