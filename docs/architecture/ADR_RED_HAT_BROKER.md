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
