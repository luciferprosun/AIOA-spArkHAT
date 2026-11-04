# Native Muse conversation session

With the owner's direct-chat preference enabled, Send (or Enter) submits a
message to Muse immediately. Successive messages share the existing in-memory
conversation. There is no per-message PolicyKit password or financial checkbox.
Shift+Enter inserts a newline. New conversation starts an empty context without
resending anything. Receipts remain available under each message's Evidence and
receipt details.

The default remains exact per-message approval. A Linux owner can explicitly
configure the direct-chat preference in the existing desktop launcher, after
the changed source has passed CI and been admitted for deployment:

```python
from runtime.mobile_gateway.desktop import launcher_files
files = launcher_files(verified_checkout, existing_state_dir, direct_chat=True)
```

This generates the ordinary launcher with `--mobile-chat-direct`. It installs
nothing. At each explicit launch, the existing native owner login is checked,
an active chat session is reused, or a new session is recorded through the
private UID-authenticated operator socket. Opening the launcher never sends a
prompt or calls the provider. The preference does not remove native login or
renew an expired owner admission silently.

For an already running, admitted Native of the same source, the equivalent
private commands are:

```sh
python3 -B -m runtime.webapp --mobile-operator chat-session-start \
  --mobile-chat-direct --state-dir /path/to/existing/native-state
python3 -B -m runtime.webapp --mobile-operator chat-session-status \
  --state-dir /path/to/existing/native-state
python3 -B -m runtime.webapp --mobile-operator chat-session-stop \
  --state-dir /path/to/existing/native-state
```

## Authority and accounting

The owner explicitly authorizes paid advisory text from `muse-spark-1.3` without
a local money ceiling. The same Core stores an audited grant bound to the
native owner session, assignment revision, host identity, source SHA, source
capsule, governor epoch and expiration. Expiration is no later than the existing
one-hour native admission or TLS expiry. Restart and native renewal invalidate
the in-memory grant. Old grant records remain evidence, never resumed authority.

An authenticated console Send authorizes its exact message under this grant.
The browser can call `chat_send`; it cannot call `chat_session_start`,
`chat_approve`, `budget_approve`, or native renewal. Origin, console cookie,
CSRF, Linux UID and current Core admission checks still apply. Android's v1
chat proposal continues to require its separate exact Linux approval.

Each message uses the existing request journal, warrant ledger, paired money
and risk reservation, one-attempt Meta transport and independently checked
receipt. The warrant's decision dependencies include the session grant digest.
The request is labelled `OWNER_SESSION_AND_SEND`, rather than implying that a
separate per-message approval dialog was displayed. The actual bounded payload
determines its reservation estimate. No arbitrary large dollar value stands in
for unlimited permission.

`aioa.governor.money-policy.v3` represents an absent monetary ceiling with JSON
`null` in all three money limit fields. It extends the existing immutable state
chain; v1/v2 history and bootstrap policy identity remain unchanged. UNKNOWN,
reservations, exposure, risk limits, kill state and circuits are retained.
Provider billing remains **UNVERIFIED**; estimates are not invoices or a provider
balance claim. Meta can still enforce its own account or rate limits.

This is unlimited **local monetary allocation**, not unlimited Core capacity.
Existing risk and history quotas still apply (the current Native bootstrap has
20 aggregate risk units, one reserved per message, and 128 reservation entries).
The grant does not reset those counters. Conversation text remains bounded RAM
with the existing 15-minute retention, 2,000-byte input and 512-token response
bounds. These constraints must not be described as infinite chat capacity.

Session end cancels its workers and advances the governor epoch so unused old
warrants cannot dispatch. Already dispatched or uncertain effects retain their
accounting. A repeated request ID is readback only, including when the first
attempt stopped between the durable proposal and dispatch. There are no paid
automatic retries. The session grants no GitHub WRITE, command execution,
knowledge save, device pairing, or tool approval.

Session sends remain `DISPATCHED` until their response and durable receipt are
validated. That state holds both reservations and bars replay. A genuinely
uncertain result becomes `UNKNOWN` and counts toward the existing failure
circuit. Successful messages no longer count as failures merely because they
were dispatched. Recovery of an already-open circuit still requires its normal
cooldown and two separately verified probe responses; it does not resolve any
older UNKNOWN reservation. Legacy exact-approval transport semantics are retained.

## Deployment and rollback

Publish and run the repository's existing CI before controlled deployment.
Keep the currently admitted Native unchanged until the candidate is verified.
Use the same state directory and existing host/TLS keys; inspect UNKNOWN and
pairing record digests before and after takeover. Do not copy secrets into a
worktree or use a new empty Core database. This feature changes source admission,
so a controlled Native restart is required to deploy it.

Enabling the session appends v3 money-policy history. Older releases, including
`2be99da7`, do not understand that new history and must not be used to reopen
the database afterward. Disabling the direct-chat preference or applying a
finite allocation with the new reader is supported; restoring an old SQLite
snapshot would discard audit/UNKNOWN and is not a rollback procedure.

## Verification

Tests use actual Core/SQLite transactions and synthetic provider HTTP, never
paid calls. Coverage includes successive conversational sends, exact local
HTTPS/CSRF admission, native-only grant creation, nonce/idempotency barriers,
lost-ACK readback, source/expiry/revocation checks before key loading, forged
fields and Android isolation, retained UNKNOWN, unchanged risk/kill controls,
source sealing and UI submission without a browser-supplied spending limit.
These tests do not certify a new LIVE model response or production deployment.
