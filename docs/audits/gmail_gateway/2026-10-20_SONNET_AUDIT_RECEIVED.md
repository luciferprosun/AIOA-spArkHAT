# A03 — Sonnet independent Gmail Gateway audit (received answer)

**Date:** 2026-10-20
**Author:** Claude Sonnet, per user attribution
**Completeness:** The provided answer is preserved below; the model offered but did not supply a full 16-section report.
**Status:** UNVERIFIED, research only; no code or live access approved.

---

I researched the scope classifications and answer your final question below. I haven't inspected the repo, so anything about existing AIOA modules is an assumption. The full 16-section report would be long, so I can put it in a doc if you want it.

**Recommended architecture**
Build it as an in-process Python adapter behind the existing Core, not a separate service. Use no REST endpoint and no second authority plane. You need about four new pieces; the rest of your 12 proposed components are probably existing Core features under new names (pending repo check):

- MailProviderPort: a narrow interface with create_draft, send_exact, read_thread and reconcile.
- GmailAdapter: the only module that touches tokens. Models never see credentials or the Gmail client.
- OutboxLedger: SQLite with a state machine of PROPOSED → APPROVED → SENDING → SENT | UNKNOWN_SEND | FAILED.
- ReplyCorrelator: matches replies by thread ID, In-Reply-To and your request ID.

Approval should bind to a hash over {task_id, recipient, subject, body, attachments, scope, expiry}. The adapter recomputes that hash at send time and refuses any mismatch. Core should reuse its existing approval, STOP and replay logic.

**Scope classification**
Google's [scopes page](https://developers.google.com/workspace/gmail/api/auth/scopes) lists gmail.send as sensitive and gmail.readonly, gmail.compose and gmail.metadata as restricted. The snippet I retrieved was garbled around gmail.modify and mail.google.com. Third-party guides classify both as restricted and gmail.labels as non-sensitive, but verify those directly. Restricted scopes bring verification and a security assessment if you distribute the app. For a single-owner app in Testing mode, the practical issues are a warning screen and a 7-day refresh-token expiry (from memory; verify).

**Minimum scopes**
- **MVP A (draft and send):** gmail.send only. It sends but cannot create drafts, so drafts live in AIOA, which is the better design anyway.
- **MVP B (read and summarize):** gmail.readonly, which is restricted. gmail.metadata can't read bodies and, as far as I know, can't search them. Please verify that.
- **MVP C (send and monitor):** gmail.send plus gmail.readonly.

**A flaw in the current proposal**
gmail.send alone cannot read the Sent folder, so it can't reconcile UNKNOWN_SEND. Gmail has no native idempotency for messages.send, so the safe design is:

1. Persist SENDING before the call.
2. On a lost response, move to UNKNOWN_SEND and block all retries.
3. Reconcile either by the owner checking Sent, or by a gmail.readonly search for the request ID embedded in the message.

With send-only scope, reconciliation is therefore manual. Whether Gmail preserves a client-supplied Message-ID is not something I verified, so test it in G2.

**OAuth**
- Use a Desktop client with the loopback redirect and PKCE.
- The old out-of-band flow is deprecated.
- Authorization happens on the Linux machine; Android only triggers it. No tokens ever cross to the phone.
- Store the refresh token in the OS keyring or a mode-0600 file outside the repo, and revoke it via Google's revoke endpoint on STOP.
- Treat invalid_grant as a hard failure that needs the owner.

**Fastest route to the first real email**
1. **G0–G1 (about 2–3 days):** build the simulator, ledger, hash binding and negative tests offline.
2. **G2 (about 1 day):** connect a dedicated test Gmail account with gmail.send only.
3. **G3:** send one owner-approved message to yourself first, then to Natalia.

Reply handling comes after that. Until then the owner pastes her reply as untrusted evidence. A pasted reply carries no restricted scope, no sender-identity claims and no verification burden.

**Conditions for connecting your account**
- The offline suite is green, including the double-send, stale-approval and STOP-mid-call tests.
- You use a test account first, not your main one.
- GOLD72 is isolated (separate runtime, credentials and evidence).
- You've read the exact consent screen.
- No message contents go into logs, prompts or the repo.

**Blocked until further authorization**
- Any gmail.readonly, gmail.modify or mail.google.com scope.
- Auto-send and auto-retry after UNKNOWN.
- Sending any real email before G3 approval.
- Forwarding email bodies to external model providers. Google's Limited Use rules and GDPR both apply, and Natalia's address and her reply are third-party personal data.
- Chromium work.
- An email-derived claim that could authorize execution or change policy.

**Further mistakes in the brief**
- Treating sender identity as provable. Gmail's Authentication-Results header (SPF/DKIM/DMARC) is a signal, not proof.
- Reading a reply's "consent" as broader than the message itself.

I'd verify the quota numbers, the Testing-mode token lifetime, Message-ID handling and gmail.metadata search limits against Google's docs before G2.

---

External audit archived as received; Google policy claims need separate primary-source checking.