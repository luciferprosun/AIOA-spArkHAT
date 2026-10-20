# C1 — independent read-only review of Gmail G3

Review only; do not run OAuth, contact Gmail, inspect credentials, modify main,
change Linux/GOLD72 worktrees, install packages, send messages or grant effects.
The owner has NOT asked this session to start a separate Codex process.

Base: `d53e96f4e124ccafa79d3e64996c163730be55e2` on
`luciferprosun/AIOA-spArkHAT`, branch `feature/aioa-gmail-gateway`.
Candidate: `cfb4551b67757aaf1ff80840ddc74da9cc57c987`; compare its Git blob manifest to
`g3_evidence/SOURCE_MANIFEST.json`.

Scope: `runtime/communication/{contracts.py,canonical_mime.py,outbox.py,
fakes/gmail.py,gmail/wire.py}`, `tests/test_gmail_outbox.py`,
`tests/test_gmail_g3_security.py`, and G3 documentation. Existing public Core
admission and approval-token fixtures do not authenticate a production owner.

Review these boundaries:
1. Substituted MIME with an attacker-recomputed hash must not bind to a proposal.
2. New proposal ID/nonce for the same task must not grant another attempt.
3. Atomicity with two processes; crash after SENDING; no UNKNOWN retry.
4. Corrupt non-SENDING history, row spoofing, unknown DB layout and resource cap.
5. Symlink/hardlink/WAL/parent replacement defenses and their same-UID limits.
6. Unicode rejection, canonical timestamps, fake admission revalidation.
7. Mixed error/success ACK, nonfinite JSON and false recipient-delivery claims.
8. Whether remaining task/account/warrant/STOP gaps are honestly BLOCKED.

Read original and new tests; record each finding with severity, exact source
location, reproducer, minimum correction and acceptance test. Independent review
may return BLOCK. Do not turn author test results into independent evidence.

Optional execution ONLY after the owner permits it: in a distinct checkout,
standard-library unittest using `python3 -B -m unittest discover -s tests
-p 'test_gmail_*.py' -v`. On the actual supported Python 3.12, run the focused
suite and required nearby Core regressions; keep source and environment hashes.
The author's 64-method result used Python 3.13.5 and a verified source slice,
not the full AIOA repository. No production or merge approval follows from it.
