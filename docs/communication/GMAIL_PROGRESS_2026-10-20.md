# AIOA Gmail Gateway — Implementation Progress

Branch: feature/aioa-gmail-gateway.
Status: OFFLINE_SOURCE_IMPLEMENTED; NO GMAIL OAUTH, NO LIVE SEND, NO APPROVED OWNER M12.

## Committed phases

- G0: Python packaging compatibility and authority surface map; one Core only; protected approval boundaries documented.
- G1: Immutable MailProposalV1, strict recipient/subject/body/expiry/nonce validation, deterministic plain-text MIME and exact SHA-256.
- G2: Metadata-only SQLite Outbox Ledger (private store, WAL + synchronous FULL), conservative UNKNOWN_SEND recovery, duplicate/replay denial, synthetic FakeGmail only.
- G4 (partial): Gmail messages.send pure JSON wire codec and 200 ACK parser, WITHOUT HTTP client or OAuth. Cannot send real email.

## Completed smoke campaign before G4 partial

- Commit: ffc805dc5de215ed5de1473299e3d1c8a5c4b2ac.
- 2026-10-20: isolated low-priority execution of Python unittest discover, on separate scratch copy; not the Codex Sprint34 runtime.
- Result: 25 tests / 25 PASS / 0 FAIL / 0 ERROR. Two initial RED issues (pathlib.PosixPath strict check and folded Message-ID parser expectation) were fixed and retested. No Gmail account, API calls, HTTP, token or new external dependency.
- This is NOT full project regression, independent security approval, or an authorization to enable production effects.

## Next required actions

1. Re-run exact current-source smoke suite after G4 partial and record counts separately.
2. Complete a larger negative test matrix: corrupted ledger/ACK, unknown, STOP, races, scope mismatch, attachment/HTML/Bcc denied.
3. Review design for a native service effect gate bound to genuine (not fixture) AIOA Core warrants; source reconcile with sealed Linux Sprint34. No effect gate exists in this branch.
4. Prepare Linux Desktop OAuth with system browser, loopback + PKCE and keyring in a LATER separate owner-approved phase, not as unattended agent setup.
5. Exact first real email send is a separate explicit human-approved action. Scoped mailbox reply reading requires its own restricted OAuth permission gate.

**Never equate offline PASS with real Gmail or production M12 owner approval.**
