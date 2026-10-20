# Gmail Gateway — Actual Offline Test Receipt

Date: 2026-10-20. Branch: feature/aioa-gmail-gateway.

## Exact source and execution

- Tested GitHub source head: 9b40682a5bb66e4ef9d0b315b9d32150c0abe550.
- The exact tested source was fetched from that branch into an isolated scratch directory; no changes to Sprint33/Sprint34/GOLD72 source or Codex sessions.
- Command: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. nice -n 19 timeout 25s python3 -B -m unittest discover -s tests -p 'test_gmail_*.py' -q
- Finished: 36 tests / **36 PASS**, **0 FAIL**, **0 ERROR**, result OK.
- Elapsed as reported by unittest: 0.704 seconds.
- Verified remote scratch blob identities match tested GitHub files:
  - runtime/communication/gmail/wire.py: d7683e088463019127e738403a528cffc232ddc5
  - tests/test_gmail_wire.py: 045b58dfae48e5c67a0616e589dbe0e9eee9d098
  - runtime/communication/outbox.py: f765f15f143d45a9e1456d196bc4bdaa8a741e28
  - tests/test_gmail_contracts.py: 3e1e05ce5677dbc3c4f15b15207752494a966e83

## Preserved first RED outcome

At initial commit d3fb80acda9e6df0a3fe7f094680585ffdd74eea, first real test run had 25 discovered, 1 FAIL + 16 ERROR. Causes:
1. Strict type(path) is Path rejected PosixPath, blocking all SQLite setup tests.
2. The parser presented folded Message-ID with leading header whitespace; expectation incorrectly assumed no folding.

Commit ffc805dc5de215ed5de1473299e3d1c8a5c4b2ac corrected both. Subsequent run: 25 PASS / 0 FAIL / 0 ERROR (0.657s).

Gmail JSON wire codec was added in commit 9b40682a5bb66e4ef9d0b315b9d32150c0abe550 and latest run: 36 PASS. The complete test sequence is recorded honestly, not rewritten to conceal RED.

## Qualified scope: OFFLINE ONLY

- Immutable strict mail proposals, deterministic plaintext MIME and canonical SHA fingerprint.
- Metadata-only SQLite outbox, conservative UNKNOWN_SEND, replay rejection, restart readback, basic local integrity detection.
- Hermetic FakeGmail simulates receipt, duplicate denial and lost response after acceptance.
- Pure Gmail messages.send JSON body generation (base64url of the pinned MIME bytes) and strict provider ACK parsing. No HTTP request.
- No Gmail OAuth, no credential broker or token, no Google API network request, no real send, no selected-inbox read and no M12 real-owner authorization.

## Unqualified / blocked

- Native AIOA CoreSendWarrant consumption for real mailbox effects; current CoreAdmission and public test fixtures alone are insufficient.
- Browser/Android identity and secure approval presentation, live STOP semantics while HTTP in flight.
- Gmail send exactly-once guarantee (provider has no native idempotency key).
- Actual power-loss durability proof, hostile host tamper resistance, production-grade credential custody and scoped user-data egress rules.
- CC/BCC, HTML, attachments and reply threads deliberately fail closed.
- This focused suite is NOT full AIOA regression or independent code/security review.

**Verdict:** G0/G1/G2 code and first Gmail wire codec exist; the 36-unit-test offline subset is PASS. LIVE_SEND remains BLOCKED and next gate is expanded G3 negative suite followed by an independent security review.
