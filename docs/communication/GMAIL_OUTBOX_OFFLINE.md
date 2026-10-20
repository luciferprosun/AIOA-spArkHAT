# AIOA Gmail Outbox — Offline G2 contract

**Only synthetic mail.** No OAuth client, no Gmail HTTP adapter, no real owner approval, no live SDK, no browser tool, no token file.

The metadata-only OutboxLedger uses a private SQLite database, WAL mode and synchronous=FULL. Its parent directory MUST exist and be owner-only (0700); database file created 0600. The ledger deliberately records no email body, recipient address, OAuth token, attachment contents or raw MIME. The per-row digest detects accidental corruption but is NOT a cryptographic authenticity signature against a malicious privileged host.

State flow:
PREPARED -> SENDING -> SENT_ACCEPTED_BY_API
                    -> UNKNOWN_SEND
If the process crashes during SENDING, recover_interrupted marks UNKNOWN_SEND, without any send. Once an attempt leaves PREPARED, a second begin/prepare for the same proposal is always denied. A negative Sent-folder search, when added later, must NEVER prove non-delivery.

**Security boundary:** prepare, begin_attempt and provider_accepted are record-writing primitives only. They do not authorize effects or contact providers. The FakeGmail and simulate_once functions are under runtime.communication.fakes, use strictly typed OfflineFixtureAdmission(grants_effect_authority=False), and can only emit synthetic fixture identifiers. The fake test grant MUST NEVER be accepted by a production Gmail adapter.

Before implementing real send, add a signed/verified owner-bound CoreEffectAdmission adapter, source pin, durable warrant consumption (integrated with existing Core, not a second signer), STOP before network dispatch, exact immutable MIME approval, broker credential custody, strict timeout/unknown-handling and independent security review.

G2 proof gates:
- true crashed/reopened SQLite attempt goes to UNKNOWN_SEND
- after timeout, no second fake call from repeat task
- changed owner scope, recipient/body, nonce, MIME hash or expired synthetic approval denies
- tampered row is rejected; no logs/persisted PII
- concurrency across two SQLite connections denies second begin
- zero network calls or real Gmail credentials

**Known limitations for later review:** SQLite durability depends on actual host/disk power-loss guarantees, filesystem isolation and controlled single-writer scope; Python in-process fake approval is no human authority; production exactly-once email delivery is not offered by Gmail; a row digest is not tamper-proof; full support for attachments, HTML, threading and BCC remains disabled.
