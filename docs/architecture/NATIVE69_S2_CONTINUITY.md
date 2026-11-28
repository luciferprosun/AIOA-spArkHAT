# Native S2 reboot qualification contract

S1 runs on one boot and uses `/run`. S2 requires a separate persistent
volume profile and a trusted exclusive gate outside the restored volume.
Production Native remains disabled. A new boot without verified succession
preserves the original `UNKNOWN / HELD` and every outstanding attempt fence.

## Durable state and external exclusion

The existing Core transaction commits the original START, consumed authority
and reservation before requesting any effect. Put the Core store, sequencer
ledger, attempt guard, Git objects and ref, and producer and terminal records
on the pinned persistent volume. Persist the approved writer generation
before admission and fsync each newly created file and its parent after each
publish step. Hash the pinned filesystem and volume credentials in the
operation binding. On any I/O failure retain the fence and use readback.
The control sockets and per-process descriptors can still use `/run`.

Require a management-controlled monotonic generation independent of the
guest's restorable storage. The manager must enforce exclusion at the
storage layer. A new generation requires proof that the former writer
cannot write or reuse authority, including after clone or snapshot restore.
A guest-generated counter, a boot ID or a path match alone conveys no
exclusion. All participants must refuse when the authority is unavailable.

## Separate managed continuity receipt

The qualification CLI verifies the externally issued
`aioa.native.s2-exclusive-readback.v1` envelope. The expected file binds the
original START, intent and reservation and old policy epoch to the trusted
volume, predecessor boot and generation, old public key and digests of
the original witness, completion and writer-closed evidence. It also binds
the fresh boot, strictly advanced externally observed generation, reader
identity, challenge and current policy epoch. The management key signs the
exact projection, time limit and assertion of predecessor exclusion.
Supply the expected binding and key digests independently of the guest.

```sh
python3 -B -m scripts.unification.native_s2_receipt \
  --expected "$trusted_expected" --expected-sha256 "$trusted_expected_sha256" \
  --receipt "$management_receipt" --authority-spki "$management_spki" \
  --authority-spki-sha256 "$trusted_management_spki_sha256"
```

This CLI only verifies continuity evidence. Core must independently derive
and verify the original bindings, compare physical volume and Git content,
verify the original signatures and authenticated closure, and use its
existing atomic settlement transaction. The CLI only reads the specified
receipt, expected binding and management public key. Before integration the project must select the
external exclusive storage provider and integrate durable generation
binding, the pinned persistent layout and the cold Core read-only client.

## Qualification on the admitted host

For each trial keep a fresh intent and isolated VM, confirm the external
barrier and cut power from outside the guest without guest sync. Preserve
the stopped disk before inspection. Record source/tree, cache and flush
settings, filesystem, physical volume, boot pair, generation, external
counts, and original authorization and evidence digests.

| Barrier | Expected result after cold start |
| --- | --- |
| C1 (link before directory fsync) | Either ref observation is possible. HELD, zero redispatch. |
| C2 (effect durable before witness) | An existing ref cannot settle. HELD, zero redispatch. |
| C3 (witness before completion) | HELD, zero redispatch. |
| C4 (complete evidence before ACK) | One original settlement only when Core independently verifies the proofs and exclusive successor. |

Also require denial for stale snapshots, cloned volumes, missing or altered
evidence and two simultaneous attempts to replace the same writer. Loss of
`/run` must never make an already consumed operation eligible. The release
profile must prove that the disk model honors fsync. Until these receipts
exist, S2 remains `NOT_QUALIFIED` and the historical operation stays held.
