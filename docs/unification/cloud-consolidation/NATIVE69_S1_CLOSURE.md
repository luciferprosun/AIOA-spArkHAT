# Native69 S1 local checkpoint

**Status** — V2 qualification kit candidate. Cross-UID S1 is BLOCKED_HOST in the Local environment. Production Native remains disabled.

The local continuation starts at PR #84 `015d70bab5588ce15e47940a0b4e4f4230b54129` (tree `7ab3174e620b6f0abd51503b51661f45171dbb4e`), based on main `4b2c55d9ab90810b99ec0337cae5eef581d53534` (tree `efa9face37bf5ddf94245a82f2c0d265cf473a31`). The local evidence manifest identifies the tested commit and tree.

| Component | Implemented or measured | Remaining S1 condition |
| --- | --- | --- |
| Core admission and dispatch | Existing approval, START, outbox, final release and attempt fence | Real Core role with active local session and polkit admission through normal apply |
| Broker | Existing signed Git object import, precise post-link and pre-completion faults, signed post-fsync stage after sequencer close | Effective confinement for exact ref, objects and evidence, including process and FD custody |
| Sequencer | Existing STOP/CAS ordering, a create-only incarnation fence, and rejection of the same publication binding by a still-running S1 daemon | Execute document-defined Q/D cases through the real services on Noble |
| Cold readback | Original START, post-fsync supervisor confirmation, minimal readback graph, and settlement writes scoped to the verified adapter | Execute C4 and C5 with different UIDs on Noble |
| Host | Read-only Mint 22.2 x86-64 preflight | Independently pinned, disposable Noble x86-64, genuine host management receipt, loaded AppArmor and real admission |
| Evidence and production | No production activation or historical access; fixture conditions documented separately | Qualified independent operator run and separate approval for exact source, host and STOP/CAS activation |

## Acceptance scope

Every real-role scenario H0, P1, C1–C5, R1–R2, N1–N5, F1–F4, B1–B3, Q1–Q3, D1–D4, E1, S1B and I1 in the S1 mission is NOT_RUN. The host launched zero qualifying sessions. Publication, settlement and redispatch counts for those scenarios are unavailable.

| Offline scenario | Expected and locally exercised | Limit |
| --- | --- | --- |
| C1/C2 | A physically visible ref after the injected exit leaves no qualifying witness and no fixture settlement; an explicit repeated request adds no attempt | Same UID, process exit on the same boot |
| C3 | Witness bytes survive, producer completion is missing, settlement denied | Same UID and disposable fixture |
| C4/R1/R2 | One counted link attempt, one verified fixture publication, one create-only fixture decision, zero additional links after two injected replay requests; two independent verifier processes | Fixture decision and separate RH04 Core tests; no production-shaped S1 result |
| F1/F2 | Actual direct-child pidfd prevents closure before exit; simulated nonempty subtree, foreign signature and wrong binding deny | No kernel-level FD custody proof |
| Q3 | S1 incarnation rejects same-state sequencer restart, even when the old slot name is absent | The existing protocol cannot infer peer receipt from successful socket send. D1–D4 cover the separate server and client outcomes in socket fixtures |

The V2 launcher source, installer, service definition and CLI are under
`scripts/unification/native_s1/`. A systemd unit owns the delegated cgroup
anchor. The foreground coordinator directly owns the parked and then
confined broker so its original pidfd remains valid through verification
of the empty cgroup. The Core remains in a real active seat0 login session
and starts only after the user-side polkit agent registers for the original
PID and start time. The same program starts a fresh Core in recovery-only
mode and an independent verifier. The case runner retains the original
records and measures the physical link, settlement revisions, Native
route invocations, and explicit replay separately.

The offline D test exercises four CLOSED fault positions with a live
sequencer and real Unix sockets. A malformed or unread DONE and a failed
slot fsync poison the live sequencer. A durable server close releases
queued STOP even if delivery of CLOSED fails. The same publication binding
is consumed in that live incarnation and the broker emits no completion
stage without a checked CLOSED response. The E test uses an actual visible
primary record after simulated directory-fsync EIO, then a fresh consumer.
Only a separate root-owned terminal signal establishes that the primary
fsync returned. It is a same-boot protocol step.

Follow the [operator instructions](../../architecture/NOBLE_QUALIFICATION_OPERATOR.md)
for installation, the exact host preflight, scenario commands and private
evidence export. Parser-only policy checks and the unprivileged seccomp
test do not cover role startup or exact-ref confinement under the Noble
kernel. The paired N4/F1/F2 cases require the actual kernel and profile.
B2 drives changed signature, witness fields and an authenticated response
with the wrong challenge. F4 couples the old attempt's relaunch denial
with a fresh broker's denied write opens on the prior ref, object, witness
and completion. S1B drives a conflicting mount pin and reopens the original
journal for a separate authorized read of its unchanged revisions. I1
reports synthetic HELD isolation separately and stays NOT_RUN without
original historical retention evidence.

## Release and retention

| Path | Authority and resources | Availability in this checkpoint |
| --- | --- | --- |
| Core packaged entrypoints | Installed distributions and ordinary Core authority | Subject to the wheel/sdist smoke in the local evidence; local installation alone conveys no effect authorization |
| Chokidar observations | PR #83 isolated diagnostic repository, creation observation only | Evidence from Windows and Noble reviewed by KarmaDue; evaluator remains UNIMPLEMENTED. [Artifact review](https://github.com/luciferprosun/AIOA-spArkHAT/issues/14#issuecomment-7225102745) |
| Native publication | Original Core warrant, reservation, scoped repo/ref, attempt fence and sequencer | Production fails closed with BLOCKED_SECURITY_REVIEW. S1 is unqualified and S2 is NOT_QUALIFIED |
| Official MCP READ | Core READ intent and official v1.0.5 test contract | Offline contract only. LIVE needs owner-bound authorization, signer, target and fresh original-journal readback |
| Historical Native69 | Original journal, ref, reservation and evidence scope | UNKNOWN / HELD. This mission did not retrieve originals or establish independent retention |
| Other LIVE lanes, repair #41 and legacy | Their original independent gates | No new acceptance. Retain legacy HOLD |

The sequencer fence covers the physical state directory, including requests
for different task IDs, refs or epochs. A fresh task or state namespace is
not evidence of isolation from the historical operation. No release of the
historic reservation, retry, retroactive proof, external publication or
Product Hunt submission was performed. Public demonstrations can use
clearly labeled synthetic evidence only. Deployment and activation stay separate.

## Local integration and later review

Keep PR #83 and #84 distinct. #83's diagnostic workflow remains independently
reviewable and should be integrated only after fresh evidence and protection
checks. Keep #84 as a draft while the installed coordinator or required
qualification and review are outstanding. Verify `Installed packaging` and
`certify` for Python 3.11 and 3.12 and standard CodeQL on the final remote SHA.
Historical green runs do not cover a new candidate. Use the ordinary protected
merge path only when separately authorized.

S2 is queued separately for durable boot-crossing state and authenticated
writer succession. It requires independently reviewed exclusive fencing,
physical re-identification after reboot, authenticated evidence and fault
tests across boot and loss of /run. There is no automatic reset or replay.

## N2 and N3 verifier handles

After checking the producer signatures, the verifier measures the real
readback in the signed challenge flow. It reuses the borrowed read-only
file and directory descriptors for the published ref, its loose commit,
and the two producer records. The report contains the file and parent
identities, mount IDs, modes, owners, byte digests and effective role
identity before the signed reply. Core still needs the complete verified
reply and its own physical recheck to settle.

N2 opens the existing exact and sibling refs for write, attempts replacement
and unlink in both directions, and attempts creation at a known absent
sibling. N3 attempts exclusive creation of the ref lock, packed refs, the
packed refs lock and a new object in the commit's prefix directory. It also
attempts write opens of the existing commit and both evidence files. The
post-publication exact ref is already present, so the dedicated creation
probe uses the unoccupied sibling. Each target is checked before and after.
The attempt-state lock has a separate probe. The coordinator also executes
the same ref, object and evidence syscalls on independent writable scratch
targets so an invalid syscall or missing input cannot count as confinement.

For this DAC and AppArmor layout only `EACCES` or `EPERM` at the planned
operation counts as a denial. The local fixture measures ordinary DAC with
the read handles. A complete N2 or N3 receipt requires the admitted Noble
host and the live verifier actor. A passing scratch control conveys no
publication authority.
