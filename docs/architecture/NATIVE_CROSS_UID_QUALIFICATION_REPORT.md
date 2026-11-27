# Native role-separated readback candidate

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

Only the explicit readback entry takes the new storage contract. The regular
fixture still enforces private same-UID storage, and the broker launch
continues to require its existing same-UID configuration. A common reader
group permits the required read without granting group write. A filesystem
mode check cannot constrain the broker to one destination name. An
AppArmor label identifies a domain, while the operator must separately
authenticate its actual policy and prove the allowed syscall. Policy names
alone convey no write authority. Production remains disabled.

The operator's sibling probe now creates an unnamed inode on the pinned
ref parent and requires denial at the same link operation used by
publication. Failure during setup and absence of the parent are distinct
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
  test_native_role_storage test_native_object_ingress test_native_qualification_channel \
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

Implementation remains open for writer-side admission and exact-ref OS
policy, import and evidence creation under the shared storage modes,
supervisor launch with broker-only signer FD, Core apply into the role
layout, and the combined crash harness. The offline checks exercise real
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
