# Native #69 C-01 broker evidence

Stack base is Draft #68 at `f6bf5c9cc1b1d070467838f0743e8174ce2339dd`,
tree `594c6321663daab074530e5030c822e4e37b6a84`. Main observed at preflight
was `9d8b61c6dce9cccbf32ce8dfc2dc87682567dd9c`. No local QA comment was
visible on #68 at preflight.

## Implemented boundary

`runtime.red_hat.witness` implements the versioned exact binding, public
executor enrollment input, bounded signed envelope, and descriptor-relative
create-only publication and readback. P-256 signatures cover canonical
JSON. The registered key fingerprint is derived from public SPKI. The caller
must obtain that registration independently of the witness. The signing key
stays with the caller, which is a synthetic producer in the fixture.

Persistence reuses the Native exclusive link primitive. An unnamed 0400
inode is written and synced, linked into an executor-owned 0700 directory,
then the directory is synced before persistence returns. Readback checks
owner, mode, link count, size, stable file identity, envelope canonicality,
signature, and exact bindings against the supplied pinned observations.
Readback also syncs the directory. A surviving link and successful readback
can establish durability at verification time. They do not prove the writer
completed its original directory barrier. No result from this module is
wired to settlement.

The existing Native route keeps the writable descriptor in Core and the
Git subprocess receives a synthetic read-only view. Its pre-link release
runs current authorization and cancellation checks in process. Sending the
writable dirfd using SCM_RIGHTS would grant a different process the ability
to link within that directory. Peer UID alone would authenticate neither the
durable START nor the one permitted release. The current controller also
requires the original process-local CAS acknowledgement for settlement.

Forward integration is `BLOCKED_SECURITY_REVIEW`. The missing adapter must
authenticate one original request against persisted START, supervise the
executor holding its key and ref descriptor, and preserve release and STOP
through the link. It must resolve the distinct-UID access to executor-private
witness storage without broadening Git or verifier authority, and establish
the durability barrier needed by Core on independent readback. Witness
primitives take trusted descriptors and scope inputs. They supply no
enrollment policy, transport authentication, key isolation, or revocation.

## Tests

```sh
PYTHONPATH=.:tests python -B -m unittest -v \
  test_native69_witness_fixture test_native_git_cold_controller \
  test_native_git_publication_boundary test_nz25_intent_cold_read \
  test_nz13_native_coding_lifecycle test_core_intent
```

Cloud result is 47 PASS, 0 FAIL, 0 SKIP. Use the pinned test dependency `uuid6==2025.0.1`. The isolated broker fixture
exercises the contract with actual ref inode observations and reads the
witness from a fresh process after losing ACK. Core tests cover retained
UNKNOWN and HELD, stale epochs, and no redispatch in existing recovery. A
registered broker release, malformed IPC handoff, and positive witness-backed
Core settlement cannot be exercised through the production path on this branch.

## Prior broader-run classification

Reproduced the 25 confinement methods without changing their outcomes.
A diagnostic wrapper recorded each `GIT_RUNTIME_CHANGED` denial and delegated
to the original guard. All 18 affected methods reached that guard. Observed
`/usr/bin/git` SHA-256 was
`356db14e102d68a1a37d8a1ac577dfd678d45d46e92f468bef8b7154e7bfdc60`,
while the required pin begins `eb54b535467e0975`. The tests did not reach their
intended confinement boundary. Rerun on the qualified host to test that behavior.

| Method in `test_nz11_git_confinement` | Prior result | Classification | Observed cause |
| --- | --- | --- | --- |
| `test_config_alias_during_namespace_setup_has_no_foreign_write` | ERROR | ENVIRONMENT_MISMATCH | Pin denial before the observation hook |
| `test_kernel_sealing_denial_never_executes_an_unsealed_runtime` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_memfd_sealing_works_when_python_omits_linux_constant_names` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_native_ref_cas_excludes_cooperating_git_writers` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_new_ref_with_other_packed_refs_preserves_packed_storage` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_real_git_object_publication_and_readback` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_real_git_ref_create_is_atomic_and_never_replayed` | ERROR | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_existing_git_locks_are_denied_without_removing_or_mutating_them` | FAIL (2 subtests) | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_existing_object_hardlink_after_scan_has_no_foreign_metadata_write` | FAIL | ENVIRONMENT_MISMATCH | Pin denial before the observation hook |
| `test_existing_packed_ref_cannot_be_shadowed_by_zero_old_create` | FAIL | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_loose_ref_prefix_conflicts_are_denied` | FAIL (2 subtests) | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_nested_ref_parent_replacement_cannot_publish_into_displaced_directory` | FAIL | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_objects_swap_after_preflight_cannot_write_outside_target` | FAIL | ENVIRONMENT_MISMATCH | Pin denial before the observation hook |
| `test_packed_ref_appearing_during_git_execution_denies_publication` | FAIL | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_packed_ref_prefix_conflicts_are_denied` | FAIL (2 subtests) | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_ref_parent_swap_after_preflight_cannot_write_outside_target` | FAIL | ENVIRONMENT_MISMATCH | Pin denial before the observation hook |
| `test_ref_publication_rechecks_release_and_cleans_locks_on_denial` | FAIL | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |
| `test_replaced_ref_lock_is_denied_without_deleting_foreign_lock` | FAIL | ENVIRONMENT_MISMATCH | `GIT_RUNTIME_CHANGED` |

## Operator handoff

Provision the pinned Noble host from the
[qualification manifest](NATIVE_HOST_QUALIFICATION.md). Run the existing
[operator commands](RED_HAT_NATIVE_WITNESS.md) and rerun the confinement module
with the exact source commit and tree. Before forward acceptance, review the
separate executor enrollment, descriptor and release protocol. Exercise
revocation, malformed and lost handoff, every publication and witness crash
boundary, and fresh-process reconcile/apply. Require exactly one settlement
after durable witness and lost ACK with zero redispatches. Keep historical #69
UNKNOWN and HELD under its [separate gate](NATIVE69_HISTORICAL_EXCEPTION.md).
