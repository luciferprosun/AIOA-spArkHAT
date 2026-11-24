# AIOA Red HAT RH-03 local handoff

Base RH-02 HEAD: `e5c4c795063af13927e3a7bcb99c338dc03bbc44`  
Base tree: `817c08a6fdf1e448bf8d3df8e64cc13d963d814c`  
Branch: `local/redhat-native69-rh03`  
RH-03 implementation commit: `d37f192`  
Implementation tree: `133e0afa9d6bce564486124939b889d28e973d5e`

## Delivered

- `runtime/red_hat/core_adapter.py` reads and binds the original intent,
  consumed warrant, reservation, owner scope, original epoch and outbox through
  the existing `CoreIntentJournal`, `CoreDualGovernor` and
  `TransactionRunner`.
- Production release is disabled. `require_production_release()` returns
  `BLOCKED_SECURITY_REVIEW`. The current Native local intent lacks durable
  repository/ref-directory device/inode bindings, durable permit/nonce records
  and a cross-process Core STOP/revocation gate. The adapter does not invent
  them.
- `recover_disposable_fixture()` accepts only the explicit fixture schema and
  RH-02 disposable repository marker. It invokes the existing RH-02 verifier in
  a fresh Python process and settles only through the original journal's
  idempotent `apply_resolution_in_transaction`. It accepts no caller-supplied
  `Reconciliation` or Boolean.
- `tests/test_redhat_core_adapter.py` covers authentic Core intent binding,
  self-consistent permit non-authority, wrong owner/device/start/warrant/
  reservation/epoch/repository/ref/OIDs, unknown/revoked key, expired permit,
  revoked Core warrant and unrelated operation schema.
- `tests/test_redhat_core_recovery.py` uses an actual Q09 Core journal plus the
  RH-02 broker and fresh verifier processes against a disposable repository. It
  covers lost ACK, missing witness retaining UNKNOWN/HELD, post-revocation
  historical readback, recovery after the original short permit expires, two
  concurrent initial settlement calls, repeated settlement and zero
  redispatch.
- `RED_HAT_RH03_CORE_MAPPING.md` maps source-backed Core interfaces, STOP/CAS
  ordering, evidence, known gaps and the narrow RH-04 boundary. The RH-01/RH-02
  handoff now records the committed RH-02 SHA.

## Verification

```sh
PYTHONPATH=.:tests python3 -B -m unittest -v \
  test_redhat_core_adapter test_redhat_core_recovery
```

Result: **8 passed**, 0 failed, 0 errors, 0 skipped; 8.803 seconds. The recovery
test observes one broker dispatch and one loose ref publication. It asserts the
Core intent row revision increments exactly once; concurrent and later repeat
recovery return the same outcome. Missing witness leaves intent `Unknown`,
outbox `HELD`, and dispatch count at one.

```sh
PYTHONPATH=.:tests python3 -B -m unittest -v \
  test_redhat_broker_protocol test_redhat_native_cas_broker
```

Result: **23 passed**, 0 failed, 0 errors, 0 skipped; 75.335 seconds.

```sh
PYTHONPATH=.:tests python3 -B -m unittest -v \
  test_core_intent test_native_git_cold_controller
```

Result: 22 Core intent tests passed. The one Native cold-controller test could
not run its phases because the local Python environment lacks `pydantic`; the
producer phase failed importing it through
`runtime.nonzero_cloudops.models.errors`, and the dependent reopen phase then
had no fixture file. No package was installed. The Core intent tests passed,
including crash after START, failed verification, stale epoch and no replay.

`python3 -m py_compile` passed for the RH-03 adapter and tests.
`git diff --check` passed before commit.

## Security and integration status

- **STOP:** preserve the current immediate pre-link `release()` revalidation and
  cancellation callback. It checks Core state, warrant, epoch and Native
  bindings immediately before the link syscall, but the Core transaction is not
  locked through `os.link`; durable revocation/kill can race in that interval.
  RH-02's fixture `flock` is not a Core lock. Do not activate fixture
  `COMMIT_PERMIT_DURABLE` semantics without owner and independent security
  approval.
- **Identity:** RH-02 and RH-03 fixtures use the same OS UID. Device identity is
  absent from current Native local intent and must be supplied by trusted host
  enrollment. Separate executor UID and kernel-enforced exact-ref confinement
  are unproven.
- **Keys and verification:** fixture test keys and the verifier process are
  same-host/same-UID test components. The subprocess result is read from the
  directly spawned verifier pipe, then the RH-02 witness/completion and
  physical ref are used to construct Core evidence. There is no production
  verifier enrollment/result channel or production key store. The executor's
  signed completion is an ordered producer assertion, not kernel fsync
  attestation.
- **Native task:** fixture recovery settles the original Core intent journal,
  governor reservation and outbox. It does not traverse the Native
  `CoreServiceGuard`/`CoreRemoteGitRoute`/`CoreCodingTasks` task state machine.
  Cold Native settlement still requires the original process-local `cas_ack`,
  route and work handle. Production Native task state remains UNKNOWN.
- **Review:** both independent read-only reviewers confirm these boundaries.
  Security review requires a shared Core/STOP/revocation/CAS serialization
  contract, pinned physical identities, trusted device identity, separate UID,
  key custody, and exact-ref confinement. Recovery review confirms the fixture
  journal path is idempotent but distinguishes it from Native task settlement.
- **Cloud:** no Cloud-owned branch or canonical source was modified. The
  canonical checkout remains on `main` and clean. No push or merge occurred.

## Next RH-04 step

Obtain owner and Natalia review for STOP linearization before changing any
production release contract. Then design a narrow integration with the original
Native task, route and journal: source repository/ref device/inode bindings from
the trusted `LocalGitPlan`, use one shared crash-analyzed gate for stop/revoke
and the exact link syscall, and authenticate the independent verifier result to
the existing Core reconciliation path. Preserve the original intent and do
not reconstruct `cas_ack`. Repeat the full crash, race, separate-UID and
qualified Noble-host checks before enabling forward execution.

`NATIVE_FORWARD_PATH_VERIFIED: NO`  
`HISTORICAL_NATIVE69: UNKNOWN / HELD / BLOCKED_SECURITY_REVIEW`  
`LIVE_EFFECTS: NONE`  
`PUSH: NONE`  
`MERGE: NONE`
