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
receipt, expected binding and management public key. The controller and cold Core entry points below implement the candidate
profile. Acceptance requires measured exclusion and power-loss evidence on
the operator-selected host.

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

## Operator path on the S2 candidate

This draft depends on the role services and the atomic cold settlement from
PR #84 (436070d). Install the reviewed S2 candidate and its matching kit on
the designated Noble guest. The production composition has no S2 launcher.
The following procedure uses a controller-owned raw NBD export as the
candidate backend. Platform approval and qualification apply to a specific
deployment of that backend.

### Controller and volume

Provide a private mode-0700 controller directory. Its pre-provisioned
`disk.raw` must be a single-link mode-0600 disposable raw file with a
512-byte aligned size. Keep the SQLite catalogue and receipts outside
guest snapshots and all backing-file paths outside the hypervisor client's
direct write access. The controller filesystem must honor fsync and user
xattrs. Losing the catalogue denies I/O. Never restore it to an earlier
generation. Each boot gets a single-use NBD export credential. Keep the
credential and domain XML private.

```sh
python -m scripts.unification.native_s2.storage --root "$ctl" --volume "$volume_hash" initialize
python -m scripts.unification.native_s2.storage --root "$ctl" --volume "$volume_hash" \
  advance --from-generation 0 --credential-output "$private/boot-a-export"
PYTHONPATH="$checkout" nbdkit --foreground --unix "$private/data.sock" python \
  "$checkout/scripts/unification/native_s2/nbd_export.py" root="$ctl"
```

Provision a raw libvirt NBD disk using the credential as its export name
and the private Unix socket as its only backing route. Use cache `none`
or `directsync`. Grant access only to the controller and the assigned QEMU
process. The export serializes I/O and generation replacement, flushes
each write and permanently consumes the attachment. A backend I/O error
poisons the generation. Keep the OS disk too, including the console role
and the original account assignments. Mount the approved ext4 or XFS disk
at `/run/aioa-qualification` on each boot. The supervisor checks its UUID
and device. Its session contains the journal, consumed warrant, sequencer,
attempt guard, Git and immutable evidence. Session keys and sockets use
tmpfs. The v1 producer signatures include the device and inode numbers.
A different device number or a lost signed inode keeps the operation held.

Provide a libvirt virtio channel named `org.aioa.native69.s2` with a
controller-only Unix source in bind mode. Only the guest's root supervisor
opens the character device. The Core and broker use their existing private
supervisor sockets. The broker needs a fresh signed answer for the original
START at admission and final release.

### One controlled window

Each controller-pinned plan contains exactly these fields.

| Field | Source |
| --- | --- |
| `vm_uuid`, `session`, `case` | Designated disposable domain, fresh 32-character lowercase hex session, and C1, C2, C3, C4a or C4b |
| `source_sha`, `tree`, `boot_sha256` | Reviewed checkout and independent boot measurement |
| `authority_spki` | ASCII base64 DER P-256 management public key. Preserve its exact file bytes, including any newline |
| `volume` | Object with `volume_sha256`, `filesystem_uuid`, integer `generation`, and `authority_spki_sha256` (SHA-256 of the public-key file bytes) |

Pin the running domain XML on the controller. The digest covers its
canonical XML, excluding the transient connected/disconnected state of
the named virtio channel. The controller checks the UUID, channel path,
NBD socket, actual consumed export credential and disk model again before
issuing the hard cut.

```sh
virsh --connect "$uri" dumpxml "$vm_uuid" | python -c \
  'import sys; from scripts.unification.native_s2.controller import config_digest; print(config_digest(sys.stdin.buffer.read()))'
python -m scripts.unification.native_s2.controller --plan "$plan_a" --plan-sha256 "$plan_a_sha" \
  --root "$ctl" --receipts "$private/runs" --socket-dir "$channel_dir" --nbd-socket "$private/data.sock" \
  --key "$management_private_key" --libvirt-uri "$uri" --domain-xml-sha256 "$trusted_xml_sha"
```

From the admitted local console, after usual host preflight:

```sh
sudo /usr/local/libexec/aioa-native-s1 s2-run --plan "$plan_a" --plan-sha256 "$plan_a_sha" \
  --manifest-sha256 "$boot_a_manifest_sha"
```

The supervisor synchronizes the original profile and START before
dispatch. The off-guest record distinguishes authorization, live admission,
the observed barrier, the hypervisor request and confirmed power-off.
C4a cuts with the broker parked at `witness_durable`. C4b parks the Core
before ACK, permits the broker to exit without sending it, and requires
the unreaped exit, empty cgroup, signed terminal stage and both directory
barriers before requesting power removal. Covering all four windows and
both C4 variants uses five fresh intents. Inspect the actual crash disk
on boot B for each one.

### Cold read and signing

Advance the same controller volume using `advance --from-generation "$old_generation"
--cold-read --credential-output "$private/boot-b-export"`. Attach the new
credential only to the authorized successor. Its storage generation permits
journal settlement and refuses writer admission. Obtain fresh management
and host manifests for boot B. Provision a fresh verifier keypair and its
public SPKI. The root-only guest media directory contains `verifier.pem`.
The cold Core opens the original task and signed capsule in the existing
journal. It has no broker, release port or publisher.

For C4b generate an unsigned expectation from the controller receipts and
the live catalogue. The operator checks the actual predecessor write and
reattach denials, backend identity, boot pair, policy epoch, independent
reader identity and source pins before signing the existing v1 envelope.
The helper has no signing capability. Provision the signed `receipt.json`
and `expected.json` in the private guest media. Deliver the expectation
digest independently.

```sh
python -m scripts.unification.native_s2.expected --root "$ctl" --log "$private/runs/$session" \
  --plan "$plan_b" --plan-sha256 "$plan_b_sha" --verifier-spki "$public_reader_key" \
  --current-epoch "$measured_epoch" --output "$private/expected.json"
sudo /usr/local/libexec/aioa-native-s1 s2-read --plan "$plan_b" --plan-sha256 "$plan_b_sha" \
  --manifest "$boot_b_manifest" --manifest-sha256 "$boot_b_manifest_sha" --management-receipt "$boot_b_receipt" \
  --original-sha256 "$original_file_sha" --start-sha256 "$original_start_file_sha" \
  --media "$private_guest_media" --expected-sha256 "$expected_sha"
```

Take the original and START file hashes from the off-guest
`authorized.json`. For an incomplete window omit `--expected-sha256`.
The output includes the raw Core observation, Git fsck, observed ref and
proof hashes, dispatches and settlement counts. Positive C4b checks two
reads, then launches a second cold Core and verifier. Retain each output,
including failures, on the controller. A newly attached clone or an expired
receipt cannot turn a held START into a publish request.

### Offline checks

```sh
PYTHONPATH=.:tests python -B -m unittest test_native_s2_receipt test_native_s2_storage test_native_s2_recovery
PYTHONPATH=. python -B tests/native_s2_nbd_acceptance.py
```

The second command needs libnbd's Python binding, nbdkit and its Python
plugin. It opens an actual disposable NBD export and checks an old
connection's nonempty write returns EPERM, duplicate and old attachments
fail, and a new writer reads and writes the expected bytes. Qualification
on the selected controller still needs the measured storage model, actual
guest cuts and independent review.
