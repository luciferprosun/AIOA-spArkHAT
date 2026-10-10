# ApprovalToken v1 offline fixture

Q02 adds `runtime/mcp_bridge/approval.py`. This isolated primitive is not wired
into transport, policy admission, signing custody, or execution. The fixture
signer exists only in `tests/test_mcp_approval.py`, using the public RFC 8032
section 7.1 TEST 1 seed. The verifier pins its public key and the key ID
`fixture-rfc8032-1`; callers cannot supply a replacement key. These public test
keys cannot establish human authority. Successful verification returns
`OFFLINE_PUBLIC_TEST_KEY` evidence with `grants_effect_authority=False`.

The immutable schema requires exactly these string fields: `version`,
`approval_id`, `task_id`, `task_fingerprint`, `nonce`, `scope`, `resource`,
`risk_class`, `issued_at`, `expires_at`, `key_id`, `signature`. Version is
`mcp.approval.v1`. UUIDs must be canonical lowercase and nonnil; nonce and task
fingerprint use 64 lowercase hex characters; Ed25519 signatures use 128.
Scope and resource are exact opaque bindings supplied independently by the
verification caller. Strings must be nonempty, bounded to 512 characters, NFC,
and free of control characters and surrogates. Non-NFC variants fail closed.

Signing bytes are UTF-8 JSON of all fields except `signature`, sorted by field
name, with comma/colon separators, unescaped Unicode and no whitespace.
The version provides domain separation. Full wire JSON follows the same rules;
the decoder rejects duplicate fields, unknown/missing fields, alternate wire
serialization, invalid UTF-8 and inputs larger than 8192 bytes. UTC timestamps
use exactly `YYYY-MM-DDTHH:MM:SSZ`; validity is issued-inclusive,
expiry-exclusive, checked against explicit caller-supplied aware UTC time.

The task fingerprint uses the existing `TaskEnvelope.fingerprint` canonical
SHA-256 algorithm without changing its semantics. It binds protocol version,
task ID, project, operation, risk, payload, idempotency key and source; existing
task creation time is excluded. Verification recomputes the current fingerprint,
checks the task ID/risk, and checks the independent expected scope/resource.
Every approval field other than the signature itself is signed.

Ed25519 uses the locally available `cryptography` backend (tested with 41.0.7).
No dependency was downloaded or added to the core install. Import is lazy;
absence of the backend denies verification with `ContractError`. The test suite
requires that backend and fails rather than skipping verification if absent.

This local format has not been negotiated with a worker or validated LIVE.
Nonce issuance, durable one-use consumption, receipt-first replay, lost-ACK
reconciliation and warrants remain separate gates. Repeated verification is
only repeated evidence, never permission for a repeated effect. Existing
WRITE_LOCAL/EXEC_LOCAL human gates remain in place. Remote `approval.status`
remains `BLOCKED_PRIVACY_PROJECTION` because the worker currently returns full
approval records; enabling it requires a separately reviewed minimal projection.

Offline checks:

```sh
python3 -B -m unittest discover -s tests -p 'test_mcp_approval.py' -v
python3 -B -m unittest discover -s tests -p 'test_mcp_*.py' -v
```

Tests cover RFC 8032 known signature bytes, valid round trips, immutable fields,
strict schema/encoding, forged fields, wrong key/signature, all signed-field
tampering, independently bound scope/resource/risk/task mismatches, edited tasks,
expiry boundaries, Unicode, missing backend and unchanged authority policy.
