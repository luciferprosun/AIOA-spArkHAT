# Native role-separated writer and readback candidate

Date 2026-11-27. Local owns branch `local/native-cross-uid-qualification`.
The base is `4b2c55d9ab90810b99ec0337cae5eef581d53534`, tree
`efa9face37bf5ddf94245a82f2c0d265cf473a31`. This branch covers the disposable
Native storage/readback contract, the S1 service runner and their tests.

## Contract and trust boundary

| Resource | Candidate owner and access | Physical and restart checks |
| --- | --- | --- |
| Session anchor and repository ancestors | Root with a dedicated reader group, mode 0750 | Reopen by descriptor, require the original device, inode and mount, and compare named directories. |
| Object and exact-ref directories | Broker with the reader group, mode 2750 | Broker-authored loose objects and the exact loose ref use 0440. Root owns the static repository metadata. The tree walk rejects links, redirection, foreign mounts, packed refs and lockfiles. |
| Evidence directory | Broker with the reader group, mode 2750 | Require the enrolled owner, group, mode and original evidence directory. Verify exact record bytes and ref inode/ctime again in Core's settlement transaction. |
| Core, broker and verifier | Distinct process UIDs/GIDs, one supplementary read group, distinct enforcing AppArmor domains | The readback entry requires one pinned mount namespace, real/effective/saved IDs, no capabilities, NoNewPrivs and non-dumpability. All pinned objects refer to that namespace. |
| Sequencer, journal, signer and enrollment | Isolated sequencer state, Core-owned journal, broker-only private signer and separate verifier identity | Existing START, release, attempt fence, signed witness/completion and fresh verifier challenge remain in force. The V2 operator supervisor launches these services under the role contract. |

The explicit writer entry uses the original signed Core authority, durable
attempt fence, sequencer slot and final Core release. Version 2 signs the
digest of the trusted role descriptor alongside the original binding.
Version 1 remains valid in the original private fixture. Shared readers
require the signed descriptor identity. The writer creates the unnamed
ref inode in a separately pinned staging directory on the same mount and
checks its inherited group and mode before publication. Objects, witness
and completion use group read with no group write. The startup entry
validates the writer role and closes its private signer FD after loading.
The cold resolver reads the original consumed warrant from Core's signed
task and capsule records, persisted START and Git step.

The root-controlled writer-policy bytes pin the reviewed configuration
input. A proof of the actual loaded policy remains essential. The
renderer emits the broker's storage rules with only the approved ref as
a ref-link destination. AppArmor's mediation of the anonymous source
inode and the actual denial of alternate mutations remain host acceptance
requirements. A kernel denial at staging or link stays fail-closed.

The operator's sibling probe creates an unnamed inode on the pinned staging
directory for shared storage and requires denial at the same link operation
used by publication. Failure during setup and absence of the parent are distinct
from denial at link. Unexpected success retains an empty sentinel and
fails the probe. The probe itself never creates a valid ref. An operator manifest may set
`native.reader_gid` to the dedicated group, distinct from all primary role
GIDs. The one-shot supervisor drops its capability bounding set before
launching the shared-storage probe and checks the resulting supplementary
groups and empty bounding set inside the child. This launch requires
CAP_SETPCAP in addition to the existing supervisor credential transition
privileges. The signer loader can use those same role constraints and still checks
the existing enrolled P-256 key and read-only FD. The probe remains
separate from real role services and no
privileged instance of this launcher was run here.

## Reproduction and remaining acceptance

Use the project venv on the reviewed checkout. Keep the privilege-requiring
operator lane separate from hosted CI.

```bash
umask 077
PYTHONPATH=.:runtime:tests python3 -B -m unittest -v \
  test_native_qualified_writer test_native_role_storage test_native_object_ingress test_native_qualification_channel \
  test_redhat_rh07_sequence test_redhat_rh06_authenticated_boundary \
  test_redhat_rh04_native_task_gate test_redhat_native_cas_broker \
  test_native_role_supervisor test_noble_qualification_tools test_native_service_startup
python3 -B tests/nz12_source_policy.py
python3 -B -m runtime.tools.nonzero_architecture --project-root .
git diff --check
```

Operator preflight uses the repository's [Noble pin template and runbook](NOBLE_QUALIFICATION_OPERATOR.md).
Provide the trusted digest and management receipt independently, from a
disposable attested Noble x86_64 instance. The observed laptop was Mint
22.2 and returned `BLOCKED_HOST` without an enforcing role domain or an
external host receipt. No privileged execution was attempted.

Core now has a two-phase read-only target view. Trusted host construction
attaches `CoreTargetStorage` with `NativeHostCompositionConfig.with_qualification_target`.
The initial view pins the layout and does not accept a broker-owned ref before the
capsule. Before `review_effect` can construct the Git route, the supervisor must
supply a `NativeQualificationPort` for the capsule's exact ref whose storage
projects to the same reader. The live Core observes that exact ref through the
bound port. A cold process must attach the full reader for the original ref
before the first host observation. The composition digest retains the same
pre-capsule identity; the original signed `START` binds the full role layout
and exact ref independently. The fixed Git child mounts the target read-only
and rejects publish forms in this profile before opening repository directories.

## Sprint service and cold startup boundary

`NativeMobileComposition` accepts the qualification sequence only during Core
construction, before the controller can issue a STOP mutation. The live service
attaches the publication port after checking the signed task's review receipt
and capsule-derived ref. It reuses that pre-registered gate for the entire
publication route. Broker, verifier and sequencer have callable service
entrypoints. They start listening under their own credentials and report
readiness over a private control connection. The broker checks the signer before
readiness; the sequencer pins its state directory and refuses publication
readiness when a previous slot is unresolved. The parent's readiness helper
observes the child through a pidfd; service IPC still checks kernel peer credentials.

On a cold launch the existing Core opens its pinned store and loads its original
host identity. Before the first target observation, `ColdNativeBootstrap` performs
one read transaction over the authenticated task history, signed capsule,
consumed warrant, START, outbox, reservation and Git step. It verifies the source,
original ref, storage digest, device/inode, mount and boot pins before binding a
reader. This does not issue a grant or authorize another publication. A cold
service can attach `DurableRoleRecoveryPort` and ask a pinned verifier to read the
evidence using a fresh, Core-signed challenge over that same START.

At the V1 checkpoint the installed process coordinator, complete AppArmor profiles and service units
remain open. The callable start entrypoints do not yet provision, launch or
supervise the four services from the operator CLI. In particular the Core process
must be in a real active local session as its own UID for the existing loginctl
and polkit admission, including after restart. A booted system unit alone does
not establish that admission. Host-side policy and identity verification remain
necessary before any privileged execution.

The writer pins
the private attempt-state directory in the signed contract and rejects a
replacement rather than inheriting an empty attempt fence. /run
supports a process restart on the same boot only. The offline checks exercise real
temporary descriptors, mode checks, and the existing fixture route.
They do not qualify a separate UID. All scenarios involving separate real
roles are `NOT_RUN`, with zero attempts launched and no cross-UID effect
or settlement counters. The next test on a qualified host must establish
both allowed link and sibling/foreign/rename denials under the same
effective policy. It must then use normal Native apply and fresh Core
and verifier processes for STOP/revoke, post-link crash, lost ACK and
repeated reconciliation with separate publication and settlement counts.

Historical Native69 remains UNKNOWN / HELD. This candidate does not reopen
its journal or provide any new authority for LIVE or legacy retirement.

## Writer policy fragment

Generate and syntax-check rules from a reviewed checkout.

```bash
python3 -B -m scripts.unification.native_writer_policy \
  --session "$session" --exact-ref "$exact_ref" > "$private/broker.storage"
{ printf 'profile aioa-native-review {\n'; cat "$private/broker.storage"; printf '}\n'; } \
  > "$private/parser-only.profile"
/usr/sbin/apparmor_parser --skip-kernel-load --skip-cache "$private/parser-only.profile"
```

Use the same pinned staging directory with both the sibling-link probe and
the writer. Populate the staging device and inode pins when the manifest
selects the shared reader group. Staging is mode 2700, broker-owned with
the reader GID, and on the same mount as the ref parent. The candidate
imports objects and records with mode 0440 using a 0027 umask. Preserve the
actual role, policy, source and host receipts privately.

## S1 writer lifecycle checkpoint

The S1 RoleStorage schema pins the nondelegated cgroup directory on a
separate cgroup2 mount. The writer must match the supervisor's create-only
launch and process records before opening the signer. The supervisor
primitive keeps the original unreaped child pidfd and checks the pinned
cgroup subtree for `populated 0`. A separate private channel carries a
broker signature over the exact execution binding and completion bytes.
The broker emits this stage after completion persistence and the
sequencer close acknowledgement. A later verifier sync cannot create it.

The closure binds the original boot, layout, process identity, execution
binding and completion digest. The cold bootstrap requires it before
attaching the original reader. The verifier checks it before reading
evidence, and Core checks it again during settlement. Shared-storage
verification through the legacy fixture entry is rejected. Broker and
sequencer IPC reject unexpected ancillary data and close received FDs.
The S1 sequencer service consumes a create-only incarnation marker so
the same state cannot serve again after same-boot process restart,
including after uncertainty during slot unlink or directory fsync.

This checkpoint still needs an installed coordinator, exact-ref profiles,
role units and same-policy positive/negative proof of containment. A
pidfd and empty subtree do not detect an already exported FD, writable
aliases or a new writer started by another unit. The root lifecycle
records assume exclusive operation provisioning by the trusted launcher.
See [S1 closure and release scope](../unification/cloud-consolidation/NATIVE69_S1_CLOSURE.md).

## V2 integration checkpoint

The supervised operator candidate now provides an installed launcher, a
scope-limited systemd cgroup holder, rendered profiles, real role entrypoints,
startup and readiness barriers, and a case/collection CLI. Product admission
still calls the existing logind/polkit check from the active local Core login
session. The disposable foreground application uses its existing capacity,
review, approval and apply path. The same executable later opens the original
SQLite store in a narrow cold composition without a publisher, routes or
authorization endpoints.

Cold COMMIT reads retain the original Core capability shape. The transaction
view rejects writes absent the private settlement permit kept in the
authenticated verifier adapter. All journal START paths reject cold mode.
The exact original witness can still settle the task and intent within one
existing transaction. An original revision check and fresh verifier challenge
are required on repeated recovery.

The supervisor requires an additional terminal signal before observing the
effect. Failure of the primary writer-closed directory fsync leaves the name
visible without this signal. D1–D4 cover the live sequencer after missing
DONE, failed fsync, failed CLOSED transmission, and a sent but unconsumed
CLOSED. The same original slot admission is consumed in each case.

See the V2 section of the [operator procedure](NOBLE_QUALIFICATION_OPERATOR.md).
Installed service coordination, AppArmor exact-link behavior, real kernel
FD custody and full distinct-UID recovery still require execution on the
externally approved Noble guest. Local evidence is scoped to the final Git
tree and distinguishes parser checks, unprivileged syscall checks, and
same-UID fixtures from real operator sessions.
