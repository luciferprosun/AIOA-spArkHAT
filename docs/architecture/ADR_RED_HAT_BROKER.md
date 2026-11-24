# ADR: Red HAT disposable Native CAS broker prototype

Status: prototype only. Production integration requires independent security review and owner approval.

## Decision

Use a bounded, canonical, length-prefixed Unix stream socket. Authenticate the connected Core peer with kernel `SO_PEERCRED` against trusted launcher configuration. The broker accepts only an exact `BrokerRequest` independently supplied by its trusted launcher and a matching, currently valid public executor enrollment. The model cannot provide that request or its authorization. A P-256 private signing key belongs to the executor identity. This prototype loads its test key only from a mode-restricted fixture file. Production key custody is not implemented.

The broker serves one connection per process and one exact ref-create operation. It receives an already opened, pinned disposable repository root and trusted identity, enrollment, Core peer and epochs from its launcher. It accepts no shell command, path override or network instruction. Git object inspection in this prototype uses an absolute, fixed `/usr/bin/git` read-only command. A sealed create-only temporary inode and exclusive hard link implement the test ref create. The exact link is the irreversible CAS attempt. Failure, uncertain sync, interruption or missing witness ACK retains UNKNOWN/HELD and consumes the attempt.

Before permit, acquire the same guard `flock` used by STOP. Under the lock, validate the durable STOP marker, exact repo/ref bindings, Core and broker epochs, enrollment validity, request expiry and authorization callback. Persist the create-only permit record and consumed attempt before releasing the lock. STOP records and syncs revocation under this same lock. Thus STOP and permit have a total order. STOP that wins prevents CAS. Permit that wins means a later STOP cannot revoke the already permitted operation. This differs from the existing Native pre-link release contract, which rechecks Core authorization immediately before ref link. The broker callback here is fixture-only. Production transition is `REQUIRES_OWNER_SECURITY_APPROVAL`.

The guard is a crash fence, not an approval database. It admits one consumed attempt and rejects restart, duplicate nonce and every replay. It cannot authorize an operation. The existing One-Core journal remains authoritative. No Core or Cloud-owned source is changed.

## Witness durability

Retain `aioa.native-cas-witness.v1` and its existing P-256 validation. The broker records effect inode and post-link effect-directory sync evidence in the v1 witness after the ref link. A verifier checks the witness against fresh repository/ref observations in another process.

V1 cannot truthfully claim that its own witness file and directory sync completed: the signed bytes must exist before file sync, and the witness directory sync follows publication. This prototype therefore writes a separate create-only, executor-signed completion record only after the witness persistence call returns. The completion binds the request, witness bytes and effect inode. A fresh process requires both records and observes the actual ref. Readback re-sync establishes current durability, while the separately signed completion authenticates that the producer's ordered persistence calls returned. Neither field alone is proof that a malicious producer performed a kernel barrier faithfully. Production needs an independently reviewed storage trust boundary and ordering protocol.

Report `effect_observed`, `producer_effect_sync_completed`, `witness_bytes_verified`, `witness_durable_at_readback`, and `producer_witness_sync_attested` separately. A test-only decision can settle once for the fixed original intent after successful independent verification. It is not production Core settlement.

## Isolation and STOP boundary

Tests run the broker and verifier as fresh processes against temporary Git repositories and synthetic identities. The current test broker has the same UID as the fixture owner. It does not prove separate-UID ownership, AppArmor confinement, a production credential store or a qualified Noble host. Passing a writable directory FD would not grant an exact-ref capability or avoid the filesystem ownership and write-permission checks. Production CAS custody remains blocked until the independent executor can own and validate the repository operation under a reviewed descriptor and identity contract.

The exclusive link is the point of irreversibility. The guard lock serializes STOP with permit creation, not with an external Core revocation transaction. There is an intentional semantic gap after permit consumption: crash before CAS and crash after CAS are indistinguishable to recovery. Neither authorizes a second CAS. The existing Core and reservation remain UNKNOWN/HELD without independently verified evidence. Ordinary `flock` is not OFD-lock authentication and does not establish ordering with the Core journal.

## Qualification boundary

The fixture test matrix verifies ordering and refusal paths, actual link dispatch count, lost ACK recovery, signed evidence freshness, synthetic single settlement and zero redispatch. It cannot set `NATIVE_FORWARD_PATH_VERIFIED`. RH-03 must integrate a durable Core-derived one-attempt permit and a separate qualified broker while preserving or explicitly obtaining approval for the stronger existing pre-link STOP check. Then independent review must test original Core settlement on a pinned qualified host. Historical Native #69 remains `UNKNOWN / HELD / BLOCKED_SECURITY_REVIEW`.

## RH-03 decision: disabled Core adapter, fixture-only recovery

RH-03 adds `runtime/red_hat/core_adapter.py`. It reads the original intent,
warrant consumption, reservation, epoch, outbox, owner scope and liability
through the existing `CoreIntentJournal` and `TransactionRunner`. It binds
fixture requests to exact physical fixture identities when those values are in
the authorized fixture operation. Current Native local operation state does
not durably contain the full repository/ref-directory device/inode tuple, and
the broker nonce/challenge/permit are not stored in a Core permit record; the
adapter therefore does not manufacture a production request or release grant.
`require_production_release()` always fails with
`BLOCKED_SECURITY_REVIEW`.

The fixture-only recovery method runs the existing RH-02 verifier in a fresh
Python process, then feeds its evidence through the original Core journal's
`apply_resolution_in_transaction`. It never accepts a caller-provided
`Reconciliation`. The test covers ACK loss, a missing witness retaining
UNKNOWN/HELD, post-revocation historical readback, a request permit that expires
before recovery, two concurrent initial settlement attempts, repeated
settlement and zero redispatch. This demonstrates the existing intent-ledger
settlement primitive with RH-02 evidence in fixture state; it does not traverse
`CoreServiceGuard`, the Native task state machine or its process-local CAS ACK.

Precise STOP semantics: the existing Core path performs fresh pre-link
authorization and cancellation checks, but the transaction and checks are not
held atomically through `os.link`. The fixture `flock` serializes only fixture
STOP with fixture broker release. No common Core/revocation/broker lock exists.
Therefore neither path proves linearizable STOP-versus-CAS, and no production
permit transition is approved by this ADR. The existing Native callback remains
the reference contract; its cross-process realization is blocked pending a
reviewed serialization mechanism and owner security approval.

`CoreIntentJournal` settlement is idempotent for an identical reconciliation,
but current Native task settlement additionally requires the original
process-local `CoreCodingTasks.cas_ack`, Native route and work handle. RH-03
does not forge or reconstruct them. The fixture test settles the original
journal intent only; production Native task state remains UNKNOWN/HELD. Full
source mapping and the narrow RH-04 proposal are in
`RED_HAT_RH03_CORE_MAPPING.md` and `RED_HAT_RH03_HANDOFF.md`.
