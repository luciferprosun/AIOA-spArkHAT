# RH-06 cross-UID threat model

## Authority and evidence

Core's durable START, active consumed warrant, governor policy, reservation and
HELD outbox remain authoritative. The versioned execution binding is derived
from those records, with a fresh nonce and mount/enrollment metadata inside the
authorized v3 operation. Recomputing a request or permit digest conveys no
authority. The fixture broker checks an exact launch-time expected binding,
pinned Core P-256 signature and Unix peer PID/UID/GID before it consumes an
attempt. The signed request transitively binds the additional metadata to the
existing v1 witness and completion record. An empty or interrupted ACK is
uncertain and cannot release the consumed attempt a second time.

The independently launched verifier checks broker enrollment, ref identity,
witness and completion, then signs a result for the exact binding and the
Core's fresh challenge. The recovery fixture pins a verifier key distinct from
the Core and broker keys, checks peer credentials and response freshness, and
uses the existing Core readback and transaction rechecks. Only that transaction
can move the original intent and task to Applied / VERIFIED. Neither an OID
match nor possession of a signed result can authorize dispatch.

## Required isolation

The workstation test runs use one UID and synthetic role keys. Future Noble
tests must provision separate unprivileged Core, broker and verifier identities.
A narrowly privileged supervisor pins executables, endpoints, UID/GID, key
epochs and policy. It supplies a broker-owned, private key or protected signer
FD. Core receives only public enrollment data and an IPC client. Verify that
Core cannot read the signing key, ptrace the broker, inherit its signing FD or
write the protected ref. Private test keys are never workflow artifacts.
Verifier access must be scoped to read-only evidence/ref apertures or a reviewed
descriptor handoff and cannot inherit the signing key. The existing fixture
expects broker-owned private directories, so this custody model needs separate
implementation and qualification.

Bind repository and exact ref parent with dev/inode and boot-local mount
identity. The synthetic boundary currently accepts direct loose refs only. The
mount check fails closed after boot context changes. An independently authorized
cross-reboot storage identity and attempt-state restoration protocol is
required to recover across those changes. A plain directory FD can ordinarily
address all names in that directory. The host design must constrain the
executor at the OS boundary to the single permitted write target and protect
each ancestor against renames and replacement, including by Core. Verify
confinement with positive publication and explicit denial of sibling writes
under the installed policy. Review the mount namespace, LSM where needed,
allowed files, source inode/descriptor custody and mount identity visibility
before providing any path or writable FD. openat2 alone does not serialize
rename against link. The signed binding and same-UID software checks do not
prove kernel confinement or prevent a same-UID replacement after the last
readback check and before the Core commit.

## Crash and reboot

Durably consume the attempt before any link. A link is irreversible before the
directory fsync returns. Witness persistence occurs after effect sync, and the
separate signed completion is generated only after witness-file and directory
sync return. A verifier can check signed producer assertions and present
readback durability. A later fsync cannot attest the earlier producer call.
A crash between the link and durable evidence may leave a matching ref with
UNKNOWN / HELD indefinitely. Protected attempt state, including after broker
restart, forbids new link. A valid witness plus completion allows reconciliation
through the original Core transaction. An ACK lost after settlement only
permits idempotent readback.

## Hosted qualification proposal

Use a dedicated, separately approved workflow or ephemeral runner with a
pinned Noble x86_64 image digest and signed package snapshot, explicit
provenance and minimal read-only repository permissions. Run only manually on
a reviewed commit, with no PR-controlled privileged execution, no credentials
persisted from checkout, no production secrets and no writable production
repositories. Provision identities and policy inside that machine only. Deny
network to the test roles once prerequisites are verified. Preflight and fail
on package, image, UID, key, confinement and mount drift. Record bounded public
outputs and exact source tree. Publish no key material. Review workflow
permissions and confinement before enabling the run. No privileged workflow is
added or dispatched by this candidate.

See [the pending STOP decision](RH06_STOP_CAS_OWNER_DECISION.md).
