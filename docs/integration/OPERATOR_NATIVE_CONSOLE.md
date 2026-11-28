# Native operator READ metadata

Explicit NativeConsoleBinding extends the existing token/local-origin protected
GET authority timeline and its existing panel. Default binding is absent. Bound
WebRuntimeService requires exact AgentRuntime/LiteScheduler/GuardLoopBinding and
the identical native guard, governor Core and runner; no model input selects them.

Whitelisted fields: exact Nebius model identity (availability not checked by READ),
Core owner mode/hash, conservative money/risk bounds as exact decimal strings,
reservation state counts/open UNKNOWN or DISPATCHED liabilities, kill/current local
epoch, historical approval/revocation record presence, receipt graph digest and
phase status, optional current admitted context hashes and fixture shadow readback.
CSR commit/receipt presence is not a verdict or effect proof. There is no new
provider, memory engine, authority, listener or executable UI control. Existing
CPL, Cockroach and Non-Zero controls and token guards are preserved.

READ snapshots are separate component observations, not an atomic global view.
Mutation timestamp is not a freshness clock. Missing values remain UNKNOWN/null,
not zero/false. Errors redact exception details. GET failure clears previous UI
metadata to UNKNOWN. No private task/owner names, raw source/prompt, approval token,
signer or commands are exported. Existing human-effect controls remain separate.

Final review C0/I0/M1: failed-refresh source coverage does not execute DOM behavior.
42 original and 75 repaired focused tests PASS; final exact-runtime patch rechecked
20 affected tests PASS. Final candidate suite is a later gate, not implied here.

## Terminal pairing status

In an admitted owner session with the local mobile Core running:

```sh
aioa-sparkhat-web --mobile-operator pairing-status --state-dir "$native_state_dir"
```

The command uses the existing private operator socket and `pairing_list` READ.
It reports counts of durable approved and revoked devices and current sessions
associated with those devices. After a restart the approvals remain visible
in the totals. Expired access paths and sessions bound to the previous Core
instance do not count. The approval total measures the owner journal. Current
transport and origin eligibility are assessed when the device reconnects.
Admission errors are returned by the existing operator
route. Output has no device identity, invitation, SAS or credential.

The terminal use case appeared in the Companion desktop instructions as
`aioa-remote devices list`. This implementation uses the current Core's
existing read contract. It requires no Companion gateway or storage migration.
