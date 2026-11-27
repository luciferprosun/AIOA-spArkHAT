# Native69 S1 local checkpoint

**Status** — cross-UID S1 BLOCKED_HOST and implementation incomplete. Production Native remains disabled.

The local continuation starts at PR #84 `015d70bab5588ce15e47940a0b4e4f4230b54129` (tree `7ab3174e620b6f0abd51503b51661f45171dbb4e`), based on main `4b2c55d9ab90810b99ec0337cae5eef581d53534` (tree `efa9face37bf5ddf94245a82f2c0d265cf473a31`). The local evidence manifest identifies the tested commit and tree.

| Component | Implemented or measured | Remaining S1 condition |
| --- | --- | --- |
| Core admission and dispatch | Existing approval, START, outbox, final release and attempt fence | Real Core role with active local session and polkit admission through normal apply |
| Broker | Existing signed Git object import, precise post-link and pre-completion faults, signed post-fsync stage after sequencer close | Effective confinement for exact ref, objects and evidence, including process and FD custody |
| Sequencer | Existing STOP/CAS ordering and create-only S1 incarnation fence | Review the same-process lost close-ack case and qualify unchanged STOP ingress against the installed services |
| Cold readback | Original START, closure gate before physical observations, verifier response digest and settlement rechecks | Complete one-service-per-role coordinator and real same-boot restart evidence |
| Host | Read-only Mint 22.2 x86-64 preflight | Independently pinned, disposable Noble x86-64, genuine host management receipt, loaded AppArmor and real admission |
| Evidence and production | No production activation or historical access; fixture conditions documented separately | Qualified independent operator run and separate approval for exact source, host and STOP/CAS activation |

## Acceptance scope

Every real-role scenario H0, P1, C1–C5, R1–R2, N1–N5, F1–F4, B1–B3, Q1–Q3, E1, S1B and I1 in the S1 mission is NOT_RUN. The host launched zero qualifying sessions. Publication, settlement and redispatch counts for those scenarios are unavailable.

| Offline scenario | Expected and locally exercised | Limit |
| --- | --- | --- |
| C1/C2 | A physically visible ref after the injected exit leaves no qualifying witness and no fixture settlement; an explicit repeated request adds no attempt | Same UID, process exit on the same boot |
| C3 | Witness bytes survive, producer completion is missing, settlement denied | Same UID and disposable fixture |
| C4/R1/R2 | One counted link attempt, one verified fixture publication, one create-only fixture decision, zero additional links after two injected replay requests; two independent verifier processes | Fixture decision and separate RH04 Core tests; no production-shaped S1 result |
| F1/F2 | Actual direct-child pidfd prevents closure before exit; simulated nonempty subtree, foreign signature and wrong binding deny | No kernel-level FD custody proof |
| Q3 | S1 incarnation rejects same-state sequencer restart, even when the old slot name is absent | The existing protocol cannot infer peer receipt from successful socket send. Same-process close-ACK ambiguity is open |

The launcher must place the broker behind an authenticated startup barrier before its process record is released. The supervisor must stay outside the broker cgroup and retain the unreaped child pidfd. The launch must bind policy, namespaces, socket parents, actual role IDs and allowlisted descriptors to the same operation. Positive publication and the write-denial matrix must run with the same effective policy. See [operator preflight](../../architecture/NOBLE_QUALIFICATION_OPERATOR.md) and [role layout](../../architecture/NATIVE_CROSS_UID_QUALIFICATION_REPORT.md). The currently installed entrypoint is a probe, and no command today qualifies P1.

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
