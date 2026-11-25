# AIOA Red HAT RH-05B integration handoff

Status: **local review candidate; production execution remains disabled**.

## Source integration

- Integration branch: `codex/redhat-rh05b-consolidate-20261125`.
- Base: fetched Cloud `origin/main` at `1d475a2aef3437854386e7d8a0e1c998735753fe`.
- Ported source history: witness `8bf9436`, RH-01 `24c58bd`, RH-02 `e5c4c79`, RH-03 `d37f192` and `9f7637e`, RH-03 late fixes `7513f30` and `d60246b`, then RH-04 `4b81f1a`.
- The RH-03/RH-04 overlap in `core_adapter.py` was resolved semantically. RH-04's v3 device binding, typed witness, task receipt recovery and in-transaction physical recheck are retained. RH-03's strict verifier-result hash validation and its journal-only recovery recheck of the ref inode/ctime and witness/completion bytes are also retained. The independent `verifier.py` implementation is unchanged between the two candidate heads.
- Latest-main `CHECKPOINT.json` and `RED_HAT_NATIVE_WITNESS.md` match the fetched main exactly. The Cloud fixture in `test_native69_witness_fixture.py` remains alongside the RH witness verification and signature tests.
- No canonical checkout, protected branch, Cloud branch, credentials, services, system packages or production repository refs were changed. No live Git operation occurred.

## Umask regression fix

The RH-04 test now explicitly sets and asserts owner-only `0700` mode for the repository ref path and its ancestors, exercises the allowed safe-directory path, then explicitly sets and asserts `0770` and checks that `GIT_STORAGE_OWNER_OR_MOUNT` rejects it. This avoids relying on `mkdir(mode=...)` when the process umask masks permission bits. The focused test passed in separate shells under umasks `0077` and `0022`; the full RH-04 suite passed as well. Runtime policy was not weakened.

## Verification

The local integrated candidate passed these focused commands:

```sh
PYTHONPATH=.:tests python3 -B -m unittest -q test_redhat_broker_protocol test_redhat_native_cas_broker
PYTHONPATH=.:tests python3 -B -m unittest -q test_redhat_core_adapter test_redhat_core_recovery
PYTHONPATH=.:tests python3 -B -m unittest -q test_redhat_rh04_native_task_gate
PYTHONPATH=.:tests python3 -B -m unittest -q test_native69_witness_fixture test_native_git_publication_boundary test_core_intent
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -q test_native_git_cold_controller
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -q test_nz13_native_coding_lifecycle
PYTHONPATH=.:tests /home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -q test_nz13_native_coding_flow
```

Results: 23 + 9 + 18 + 33 + 1 + 11 + 29 = **124 passed**, 0 failed, 0 errors, 0 skipped. The umask target also passed once under each requested shell umask. These are focused disposable-fixture and regression results, not hosted CI or production qualification.

## Security boundary and remaining blockers

- The real Native composition still does not install a qualified production gate/device binding. The route remains fail-closed when those trusted inputs are absent; production release reports `BLOCKED_SECURITY_REVIEW`.
- RH-04's candidate gate orders STOP/revocation against the final link, but that changes the prior immediate pre-link STOP guarantee and requires explicit owner/security approval. No such approval is implied by this prototype.
- Broker/executor/verifier fixtures run under one UID. A separate executor identity, cross-UID synchronization, kernel-enforced exact-ref confinement and production signing-key custody remain unproven.
- The filesystem ref/evidence check and Core durable transaction cannot be atomic. A same-UID host process can still race filesystem namespace state around the final check.
- No pinned Ubuntu 24.04 Noble host qualification, production process channel or real Native producer-to-verifier acceptance has been completed. `NATIVE_FORWARD_PATH_VERIFIED` remains `NO`.
- Historical Native #69 remains `UNKNOWN / HELD / BLOCKED_SECURITY_REVIEW`; no evidence was reconstructed or altered. NonZero retirement remains on hold.

`LIVE_EFFECTS: NONE`
`NATIVE_PRODUCTION_ENABLED: NO`
`NATIVE_FORWARD_PATH_VERIFIED: NO`
`HISTORICAL_NATIVE69: UNKNOWN / HELD`
