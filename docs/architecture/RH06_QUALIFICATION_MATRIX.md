# RH-06 qualification matrix

Base `853484d7fe39fabf2922ff87fcedd0a980807817`, tree
`11db20a7ebbac9ee5842e1b8510169987672c486`. Tested implementation
`b642ce1b826327e1d892b33d7d14ee96a87ab639`, tree
`0d33bc700465d736a5d3956fff29c6340ecddfc0`. Branch
`codex/native69-rh06-proof`. The follow-up documentation commit records the run.

Linux Mint 22.2 x86_64, kernel 7.0.0-38-generic, Python 3.12.3,
Git 2.43.0, cgroup v2. Broker, Core and verifier have distinct process IDs and
synthetic role keys but the same UID (1000). All writes and crash injection
occur in disposable fixtures. The available host has no qualified pinned
Ubuntu 24.04 Noble environment. The fixture uses a disk-backed test
transaction factory. It constructs the synthetic durable START and task rows
in test setup. Recovery goes through `CoreCodingTasks.request("reconcile")` in
a fresh Core process with an independent verifier process and their test-only
socket. The runtime's normal Native apply path stays disabled before START.

| Scenario | Local fixture | Qualified separate-UID Noble |
| --- | --- | --- |
| Exact Core START binding, wrong signer, owner, device, epoch, ref and repo | PASS, incorrect envelope denies before attempt consumption | NOT_RUN |
| Pinned mount drift and unsupported nested ref | PASS, no link | NOT_RUN |
| STOP wins and blocks ref publication | PASS, broker's local STOP guard, 0 link attempts and 0 settlements | NOT_RUN, Core STOP must share the approved gate |
| Publisher wins with concurrent STOP | PASS, broker's local guard, 1 link and subsequent STOP marker, no second link | NOT_RUN, durable Core STOP order still requires approval |
| Revoked warrant disallows grant export | PASS, Core denies fresh export | NOT_RUN, durable revoke after export is not connected to the broker |
| Crash after link before witness | UNKNOWN_HELD, 1 link, 0 settlements, 0 new CAS on retry | NOT_RUN |
| Crash after durable witness before ACK | VERIFIED_ONCE, 1 link, 1 intent revision increase and one original task settlement | NOT_RUN |
| Repeat reconciliation and broker retry after uncertainty | PASS, unchanged result and no second ref link | NOT_RUN |
| Wrong witness, same OID on replaced inode, stale enrollment or stale verifier challenge | PASS, UNKNOWN / HELD and no settlement | NOT_RUN |
| Authenticated verifier-to-Core port | PASS for pinned role keys, authenticated peer, challenge and signed response over local IPC | NOT_RUN, verifier key and read-only evidence aperture unqualified |
| Core cannot read broker signing key | NOT_RUN, same UID | BLOCKED_HOST |
| Kernel denies sibling refs and all unauthorized paths | NOT_RUN, software validation only | BLOCKED_HOST |
| Normal Native apply to cold recovery | NOT_RUN, fixture START and no runtime wiring | BLOCKED_HOST / BLOCKED_SECURITY_REVIEW |

The signed verifier reply is checked before settlement. The existing Core
transaction keeps evidence references and hashes. It does not archive the new
wire envelope. Filesystem observation and Core commit remain separate. See
[the threat model](RH06_CROSS_UID_THREAT_MODEL.md).

## Commands

Run from the isolated worktree. The last command uses the existing venv for
repository dependencies.

```sh
export PYTHONPATH=.:tests
python3 -B -m unittest -v test_redhat_rh06_authenticated_boundary
python3 -B -m unittest -q test_redhat_broker_protocol test_redhat_native_cas_broker
python3 -B -m unittest -q test_redhat_core_adapter test_redhat_core_recovery test_redhat_rh04_native_task_gate
python3 -B -m unittest -q test_native69_witness_fixture test_native_git_publication_boundary test_core_intent
/home/l/projects/AIOA_NZ_FULL_PRIVATE_20261106/venv/bin/python -B -m unittest -q test_native_git_cold_controller test_nz13_native_coding_lifecycle
python3 -B tests/nz12_source_policy.py
python3 -B -m runtime.tools.nonzero_architecture --project-root .
git diff --check origin/main...HEAD
```

The RH-06 suite passed 12 cases and the four baseline groups passed 23, 27,
33 and 12 cases. Total 107 passed, zero failures, errors or skips on the final
implementation. The initial RH-06 run exposed a fixture cleanup error from a
missing subprocess stdin pipe. The harness was corrected and the suite rerun.
Source policy, One-Core architecture, Python 3.11 grammar/interpreter
compilation and whitespace checks passed.

## Cloud handoff

Review the disabled fixture transport and the existing Core transaction
integration. Security, recovery and integration reviewers inspected the
candidate read-only. Review found a stale-enrollment risk and a mount check
against reopened paths. The candidate checks the trusted current enrollment
before accepting the verifier result and checks the actual held FDs in each
role, including the Core transaction. Security and recovery re-reviewed both
fixes. No production caller is installed and no protected acceptance workflow
is added.

Owner STOP/CAS approval is **PENDING**. Owner and independent security reviewer
must approve the [ordering decision](RH06_STOP_CAS_OWNER_DECISION.md).
Afterward, implement shared sequencing with final Core revalidation,
supervisor-controlled identity and storage, and the full Native apply/recovery
entry on a qualified Noble host. Historical Native #69 stays UNKNOWN / HELD
with its original reservation. This candidate neither qualifies Native
forward execution nor changes the historical state.
