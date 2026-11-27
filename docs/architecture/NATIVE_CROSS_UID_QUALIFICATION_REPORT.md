# Native role-separated writer and readback candidate

Date 2026-11-27. Local owns branch `local/native-cross-uid-qualification`.
The base is `4b2c55d9ab90810b99ec0337cae5eef581d53534`, tree
`efa9face37bf5ddf94245a82f2c0d265cf473a31`. This branch changes only the
disposable Native storage/readback contract, operator probe and their tests.

## Contract and trust boundary

| Resource | Candidate owner and access | Physical and restart checks |
| --- | --- | --- |
| Session anchor and repository ancestors | Root with a dedicated reader group, mode 0750 | Reopen by descriptor, require the original device, inode and mount, and compare named directories. |
| Object and exact-ref directories | Broker with the reader group, mode 2750 | Broker-authored loose objects and the exact loose ref use 0440. Root owns the static repository metadata. The tree walk rejects links, redirection, foreign mounts, packed refs and lockfiles. |
| Evidence directory | Broker with the reader group, mode 2750 | Require the enrolled owner, group, mode and original evidence directory. Verify exact record bytes and ref inode/ctime again in Core's settlement transaction. |
| Core, broker and verifier | Distinct process UIDs/GIDs, one supplementary read group, distinct enforcing AppArmor domains | The readback entry requires one pinned mount namespace, real/effective/saved IDs, no capabilities, NoNewPrivs and non-dumpability. All pinned objects refer to that namespace. |
| Sequencer, journal, signer and enrollment | Existing supervisor-only sequencer state, Core-owned journal, broker-only private signer and separate verifier identity | Existing START, release, attempt fence, signed witness/completion and fresh verifier challenge remain in force. The supervisor does not yet launch these services with this contract. |

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
  test_native_role_supervisor test_noble_qualification_tools
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

Implementation remains open for the installed supervisor that launches real
Core, broker, verifier and sequencer processes, authenticates the loaded
policy, and assembles the initial and cold configuration from trusted pins.
The policy renderer emits storage rules for a reviewed complete AppArmor profile.
The cold resolver is callable
from the existing controller with a trusted host composition. The writer pins
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
